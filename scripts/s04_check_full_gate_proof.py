#!/usr/bin/env python3
"""`reports/serving_fingerprint.json`（原本のある手元で `scripts/b00_run_full_gate.py`
が書いた実行証明、コミット済み。Issue #48 PR-5 で `full_gate_proof.json` の後継になった）が
**今の HEAD のパイプラインコードに対応しているか**を確かめる（CI の `full-gate-proof-check` ジョブから呼ぶ。原本は不要
——証明の JSON とコミット済みのコードだけで完結する）。

    python3 scripts/s04_check_full_gate_proof.py

**このスクリプトはワークフローの heredoc から切り出したもの**
（レビュー指摘: `.github/workflows/ci.yml` に直接埋め込んだ Python は
pytest で検証されないため、キーの付け方の食い違いのような不具合が
テストをすり抜けたまま CI に入ってしまった——実際に一度それが起きた。
`scripts/tests/test_s04_check_full_gate_proof.py` がこのファイルを検証する）。

確認する3点（**証明が本物であることまでは確かめられない**——確かめられるのは
この3点だけ）:

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
3. 証明の `schema_version` が今の形（`b00.SCHEMA_VERSION`）で、`queries[].id` の集合が
   HEAD の `web/serving_queries.yaml` の問い合わせの `id` の集合と一致すること
   （問い合わせを足したのに証明を作り直していない、を落とす）。PyYAML が無い環境
   （CI のこのジョブは `pip install` しない）でも動くよう、YAML は行の正規表現で読む。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402

DEFAULT_PROOF = ROOT / "reports" / "serving_fingerprint.json"
QUERIES_YAML = "web/serving_queries.yaml"
_QUERY_ID_RE = re.compile(r"^\s*-\s+id:\s*([A-Za-z0-9_.-]+)\s*(?:#.*)?$")
DEFAULT_MANIFEST = ROOT / "data" / "sample" / "manifest.json"


def _require_keys(data: dict, keys: tuple[str, ...], *, label: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        sys.exit(f"{label} に必須キーが無い（形が壊れている）: {missing}")


def check_pipeline_path_hashes(proof: dict) -> list[str]:
    """証明の `pipeline_path_hashes` が今の HEAD と一致するか。問題があれば、
    それを説明する行のリスト（人が読む1行ずつ）を返す（空なら問題無し）。

    git rev-parse の実行そのものは `scripts/b00_run_full_gate.py` の
    `git_path_hashes` を再利用する（D3。以前はここに同じループを別実装して
    おり、二重に持つと片方だけ直して食い違う余地があった）。
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

    hashes, problems = b00.git_path_hashes(expected_paths)
    for path in expected_paths:
        actual = hashes.get(path)
        if actual is None:
            continue  # git_path_hashes が既に problems に理由を積んでいる
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


def parse_query_ids(yaml_text: str) -> set[str]:
    """`serving_queries.yaml` の `queries:` セクションの `- id: xxx` の集合。"""
    ids: set[str] = set()
    in_queries = False
    for line in yaml_text.splitlines():
        if re.match(r"^queries:\s*$", line):
            in_queries = True
            continue
        if in_queries and re.match(r"^\S", line) and not line.startswith("#"):
            in_queries = False  # 次の最上位キー
        if in_queries:
            m = _QUERY_ID_RE.match(line)
            if m:
                ids.add(m.group(1))
    return ids


def check_schema_and_query_ids(proof: dict, head_queries_yaml: str) -> list[str]:
    """証明の `schema_version` と `queries[].id` の集合が、今のコードと対応しているか。"""
    problems: list[str] = []
    if proof.get("schema_version") != b00.SCHEMA_VERSION:
        problems.append(f"schema_version が {proof.get('schema_version')!r}（期待: {b00.SCHEMA_VERSION}）")
    head_ids = parse_query_ids(head_queries_yaml)
    if not head_ids:
        return problems + [f"{QUERIES_YAML} から問い合わせの id を1つも読めない（形が変わった可能性）"]
    proof_ids = {q.get("id") for q in proof.get("queries", [])}
    if proof_ids != head_ids:
        problems.append(
            "証明の queries[].id の集合が HEAD の問い合わせの id の集合と一致しない"
            f"（証明にしか無い: {sorted(proof_ids - head_ids)} / HEAD にしか無い: {sorted(head_ids - proof_ids)}）"
        )
    return problems


def _head_queries_yaml() -> str:
    result = subprocess.run(
        ["git", "show", f"HEAD:{QUERIES_YAML}"], cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.exit(f"git show HEAD:{QUERIES_YAML} に失敗した: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--proof", default=str(DEFAULT_PROOF))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args()

    proof_path = pathlib.Path(args.proof)
    if not proof_path.exists():
        sys.exit(f"{proof_path} が無い。scripts/b00_run_full_gate.py を実行してコミットすること。")
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    _require_keys(
        proof, ("schema_version", "pipeline_path_hashes", "source_hashes", "queries"), label=str(proof_path),
    )

    path_problems = check_pipeline_path_hashes(proof)
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

    query_problems = check_schema_and_query_ids(proof, _head_queries_yaml())
    if query_problems:
        sys.exit(
            f"証明が今の問い合わせの定義と食い違う（{len(query_problems)}件）。原本のある手元で "
            "`.venv/bin/python3 scripts/b00_run_full_gate.py` を回して証明を更新すること:\n"
            + "\n".join(f"  - {p}" for p in query_problems)
        )
    print(f"OK: 証明の問い合わせ{len(proof['queries'])}件が {QUERIES_YAML} と一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
