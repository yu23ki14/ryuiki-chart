#!/usr/bin/env python3
"""`reports/full_gate_proof.json`（原本のある手元で `scripts/b00_run_full_gate.py`
が書いた実行証明、コミット済み）が**今の HEAD のパイプラインコードに対応して
いるか**を確かめる（CI の `full-gate-proof-check` ジョブから呼ぶ。原本は不要
——証明の JSON とコミット済みのコードだけで完結する）。

    python3 scripts/s04_check_full_gate_proof.py

**このスクリプトはワークフローの heredoc から切り出したもの**
（レビュー指摘: `.github/workflows/ci.yml` に直接埋め込んだ Python は
pytest で検証されないため、キーの付け方の食い違いのような不具合が
テストをすり抜けたまま CI に入ってしまった——実際に一度それが起きた。
`scripts/tests/test_s04_check_full_gate_proof.py` がこのファイルを検証する）。

確認する2点（`docs/plans/PHASE_B_RECONCILIATION.md` §5.2参照。**証明が本物で
あることまでは確かめられない**——確かめられるのはこの2点だけ）:

1. パイプラインのパス（`scripts/b00_run_full_gate.py` の
   `collect_pipeline_paths()`）の git tree/blob ハッシュを HEAD で計算し直し、
   証明の値と1つ残らず一致すること。
2. `data/sample/manifest.json` の原本・入力ファイルの sha256 が、証明の
   それと一致すること（サンプルと全量の証明が同じ原本のスナップショットに
   由来することの確認）。**比べる対象は両方が持つキーすべて**
   （`pipeline_inputs.SOURCE_FILE_KEYS` と同じキーの形を、
   `scripts/s01_build_sample.py`（manifest.json）・
   `scripts/b00_run_full_gate.py`（この証明）のどちらも使う——レビュー指摘対応。
   以前はキーの形が2箇所で食い違っており（`"ryuiki.sqlite"` 形と
   `"data/db/ryuiki.sqlite"` 形）、`KeyError` で落ちる不具合になっていた）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402

DEFAULT_PROOF = ROOT / "reports" / "full_gate_proof.json"
DEFAULT_MANIFEST = ROOT / "data" / "sample" / "manifest.json"


def _require_keys(data: dict, keys: tuple[str, ...], *, label: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        sys.exit(f"{label} に必須キーが無い（形が壊れている）: {missing}")


def check_pipeline_path_hashes(proof: dict, root: pathlib.Path) -> list[str]:
    """証明の `pipeline_path_hashes` が今の HEAD と一致するか。問題があれば、
    それを説明する行のリスト（人が読む1行ずつ）を返す（空なら問題無し）。
    """
    expected_paths = b00.collect_pipeline_paths()
    proof_paths = sorted(proof["pipeline_path_hashes"])
    if expected_paths != proof_paths:
        missing_in_proof = sorted(set(expected_paths) - set(proof_paths))
        extra_in_proof = sorted(set(proof_paths) - set(expected_paths))
        return [
            "証明が持つパスの集合が、今のコードが計算するパスの集合と一致しない"
            f"（証明にしか無い: {extra_in_proof} / 今のコードにしか無い: {missing_in_proof}）"
        ]

    problems = []
    for path in expected_paths:
        result = subprocess.run(
            ["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True, cwd=str(root),
        )
        if result.returncode != 0:
            problems.append(f"git rev-parse HEAD:{path} に失敗した: {result.stderr.strip()}")
            continue
        actual = result.stdout.strip()
        expected = proof["pipeline_path_hashes"][path]
        if actual != expected:
            problems.append(f"{path}: 証明={expected} / HEAD={actual}")
    return problems


def check_source_hashes_match_manifest(proof: dict, manifest: dict) -> list[str]:
    """証明の `source_hashes` と `manifest.json` の `source_files` が、
    **両方が持つキーすべて**で一致するか（レビュー指摘: 以前は
    `ryuiki.sqlite`/`cells.sqlite` の2つだけを、かつキーの形が食い違ったまま
    比べていた）。共通のキーが1つも無ければ、それ自体を問題として返す
    （黙って「比べる対象が無いので一致」とはしない）。
    """
    proof_hashes = proof["source_hashes"]
    manifest_hashes = manifest["source_files"]
    shared_keys = sorted(set(proof_hashes) & set(manifest_hashes))
    if not shared_keys:
        return [
            "証明の source_hashes と manifest.json の source_files に共通のキーが"
            f"1つも無い（証明: {sorted(proof_hashes)} / manifest.json: {sorted(manifest_hashes)}）"
        ]
    problems = []
    for key in shared_keys:
        if proof_hashes[key] != manifest_hashes[key]:
            problems.append(f"{key}: manifest.json={manifest_hashes[key]} / 証明={proof_hashes[key]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proof", default=str(DEFAULT_PROOF))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()

    proof_path = pathlib.Path(args.proof)
    if not proof_path.exists():
        sys.exit(f"{proof_path} が無い。scripts/b00_run_full_gate.py を実行してコミットすること。")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    _require_keys(proof, ("pipeline_path_hashes", "source_hashes"), label=str(proof_path))

    path_problems = check_pipeline_path_hashes(proof, ROOT)
    if path_problems:
        sys.exit(
            f"パイプラインのパスが証明と食い違う（{len(path_problems)}件）。原本のある手元で "
            "`.venv/bin/python3 scripts/b00_run_full_gate.py` を回して証明を更新すること:\n"
            + "\n".join(f"  - {p}" for p in path_problems)
        )
    print(f"OK: パイプラインのパス{len(proof['pipeline_path_hashes'])}件、証明と HEAD が一致")

    manifest_path = pathlib.Path(args.manifest)
    if not manifest_path.exists():
        sys.exit(f"{manifest_path} が無い。scripts/s01_build_sample.py を実行してコミットすること。")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require_keys(manifest, ("source_files",), label=str(manifest_path))

    hash_problems = check_source_hashes_match_manifest(proof, manifest)
    if hash_problems:
        sys.exit(
            f"{manifest_path} の原本 sha256 が証明の原本 sha256 と食い違う（{len(hash_problems)}件）。"
            "サンプルと全量の証明が同じ原本のスナップショットに由来していない。"
            "scripts/s01_build_sample.py と scripts/b00_run_full_gate.py を、同じ原本に対して"
            "両方回し直すこと:\n" + "\n".join(f"  - {p}" for p in hash_problems)
        )
    n_shared = len(set(proof["source_hashes"]) & set(manifest["source_files"]))
    print(f"OK: {manifest_path} の原本 sha256 と証明の原本 sha256 が一致（{n_shared}件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
