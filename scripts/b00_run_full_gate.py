#!/usr/bin/env python3
"""原本のある手元で、Phase B パイプラインをゼロから通しで回し、33表の統合
ゲートが緑（終了コード0）のときだけ実行証明 `reports/full_gate_proof.json` を
書く（Issue #29「縮小サンプル＋実行証明」B）。

    .venv/bin/python3 scripts/b00_run_full_gate.py

CLAUDE.md の実行順（r01 → b03→b04→b05、b06→b09→b07→b08、b10、b11、b12）で
各スクリプトを引数無し（＝各スクリプト自身の既定パス）で呼び、最後に
`scripts/b02_run_all_gates.py` を呼ぶ。**このスクリプト自身はデータの値を
一切作らない**——各段のスクリプトを順に呼ぶだけの薄いオーケストレータで、
検証・変換ロジックは1行も持たない。

## 証明の中身

- パイプラインに影響するパス（`PIPELINE_PATHS` 参照）の git tree/blob ハッシュ
  （`git rev-parse HEAD:<path>`）。**作業ツリーがこれらのパスで clean で
  あることを要求する**（さもないと「HEAD の内容」と「実際に実行したコード」が
  ずれた証明になる）。
- 原本（`ryuiki.sqlite`・`cells.sqlite`・`data/processed` の入力）の sha256。
- 環境（Python のバージョン・`sqlite3` モジュールのバージョン、Node のバージョン・
  `better-sqlite3` が実際にリンクしている SQLite のバージョン）。
- `scripts/b02_run_all_gates.py` の要約（一致・宣言済み差分のみ・不一致・
  対象外・適用した宣言の数）、`reports/derived_reconciliation_all.md` の
  sha256、5つの candidate ファイルの `pipeline_fingerprint` の行。

**終了コードが0のときだけ証明を書く。** 途中のどこかで失敗すれば、証明を
書かずにそのまま非0で終了する（古い証明は上書きしない——直前の実行の
`reports/full_gate_proof.json` はそのまま残る）。
"""
from __future__ import annotations

import datetime
import json
import pathlib
import platform
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402
import s05_check_sample_gate_summary as s05  # noqa: E402
from reconcile import common as reconcile_common  # noqa: E402

DEFAULT_OUT = ROOT / "reports" / "full_gate_proof.json"

# ADR-0016 Phase B のパイプラインに実際に影響するパス。ここに無いものが
# 変わっても証明は無効化されない（CI 側の `full-gate-proof-check` ジョブが
# 同じ集合で HEAD の tree ハッシュを計算し直し、1つでも違えば落とす）。
PIPELINE_FILE_GLOBS = ("scripts/b0*.py", "scripts/b1*.py")
PIPELINE_EXPLICIT_FILES = (
    "scripts/r01_build_registry.py",
    "scripts/pipeline_inputs.py",
    # scripts/b00_run_full_gate.py 自身（このファイル）が import する
    # （b02 の出力の要約パースを重複させず s05 を再利用する。D1）。b00 は
    # `scripts/b0*.py` に一致して証明の対象パスに入るが、s05 は "s05" で
    # 始まるためそのグロブに一致しない——単体ファイルとして明示する。
    "scripts/s05_check_sample_gate_summary.py",
    # scripts/b06_build_occurrence.py・scripts/registry/build_taxon.py が import
    # する（scripts/ 直下の単体ファイルで、b0*/b1* にも scripts/registry/ にも
    # マッチしない。code-review 指摘）。
    "scripts/taxon_namespaces.py",
    # scripts/registry/common.py が SCHEMA_SQL として読む（同じく scripts/ 直下の
    # 単体ファイル。code-review 指摘）。
    "scripts/schema_registry.sql",
    "reports/derived_baseline.json",
    "web/scripts/build-derived.mjs",
    "web/scripts/build-biota.mjs",
    "web/scripts/build-geo.mjs",
    # web/scripts/build-geo.mjs が import する（code-review 指摘）。
    "web/scripts/lib/csv.mjs",
    "requirements.txt",
    "web/package.json",
    "web/pnpm-lock.yaml",
)
PIPELINE_DIRS = ("scripts/registry", "scripts/migrate", "scripts/reconcile", "registry")

# CLAUDE.md の実行順（引数無し＝各スクリプトの既定パスをそのまま使う）。
PIPELINE_STEPS = (
    "scripts/r01_build_registry.py",
    "scripts/b03_build_observation.py",
    "scripts/b04_build_cube.py",
    "scripts/b05_project_v1.py",
    "scripts/b06_build_occurrence.py",
    "scripts/b09_build_occurrence_place.py",
    "scripts/b07_build_occurrence_cube.py",
    "scripts/b08_project_occurrence_v1.py",
    "scripts/b10_project_documents_v1.py",
    "scripts/b11_project_place_v1.py",
    "scripts/b12_project_taxon_v1.py",
)

DEFAULT_PROJECTION_MANIFEST = ROOT / "scripts" / "reconcile" / "projection_manifest.yaml"


def default_candidate_files() -> tuple[str, ...]:
    """5つの candidate ファイル名を `scripts/reconcile/projection_manifest.yaml`
    （正本、`scripts/b02_run_all_gates.py` が読むのと同じファイル）から読む。
    以前はここに5つを手で書き写しており、正本に candidate が増減しても
    追従し忘れる余地があった（code-review 指摘）。
    """
    manifest = reconcile_common.load_projection_manifest(DEFAULT_PROJECTION_MANIFEST)
    return tuple(sorted(manifest))


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT), **kwargs)


def collect_pipeline_paths() -> list[str]:
    paths: set[str] = set(PIPELINE_EXPLICIT_FILES) | set(PIPELINE_DIRS)
    for pattern in PIPELINE_FILE_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file():
                paths.add(str(p.relative_to(ROOT)))
    return sorted(paths)


def assert_paths_clean(paths: list[str]) -> None:
    result = _run(["git", "status", "--porcelain", "--"] + paths, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git status に失敗した: {result.stderr}")
    if result.stdout.strip():
        sys.exit(
            "パイプラインに影響するパスに未コミットの変更がある。証明はコミット済みの"
            f"コードに対してのみ書ける（CLAUDE.md）。差分:\n{result.stdout}"
        )


def git_path_hashes(paths: list[str]) -> tuple[dict[str, str], list[str]]:
    """`paths`（HEAD からの相対パス）それぞれの git tree/blob ハッシュ
    （`git rev-parse HEAD:<path>`）を引く。

    **ここでは `sys.exit` しない**——`scripts/s04_check_full_gate_proof.py` の
    `check_pipeline_path_hashes` がこの関数をそのまま再利用し、失敗を
    「証明と食い違う」問題の一覧（人が読む1行ずつ）の一部としてまとめて
    返す必要があるため（D3。以前は s04 が同じ git rev-parse ループを
    別実装していた）。戻り値は `(取得できたパスのハッシュ, 失敗した行の説明)`
    ——このファイルの `main()` は `problems` があれば自分で `sys.exit` する。
    """
    hashes: dict[str, str] = {}
    problems: list[str] = []
    for path in paths:
        result = _run(["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True)
        if result.returncode != 0:
            problems.append(f"git rev-parse HEAD:{path} に失敗した: {result.stderr.strip()}")
            continue
        hashes[path] = result.stdout.strip()
    return hashes, problems


def source_hashes() -> dict[str, str]:
    """`pipeline_inputs.SOURCE_FILE_KEYS` をキーにした sha256（キーの形は
    `scripts/s01_build_sample.py` の `manifest.json["source_files"]` と
    共通——レビュー指摘対応。両方とも `pipeline_inputs.compute_source_hashes()`
    しか呼ばない）。
    """
    try:
        return pipeline_inputs.compute_source_hashes(
            ROOT / "data" / "db" / "ryuiki.sqlite",
            ROOT / "data" / "db" / "cells.sqlite",
            ROOT / "data" / "processed",
        )
    except FileNotFoundError as e:
        sys.exit(f"{e}（CLAUDE.md「worktree の運用」に従い1ファイルずつ symlink すること）")


def detect_environment() -> dict[str, str]:
    node_version = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    better_sqlite3_version = subprocess.run(
        [
            "node", "-e",
            "const Database=require('better-sqlite3');const db=new Database(':memory:');"
            "console.log(db.prepare('select sqlite_version() as v').get().v);db.close();",
        ],
        cwd=str(ROOT / "web"), capture_output=True, text=True,
    ).stdout.strip()
    return {
        "python_version": platform.python_version(),
        "python_sqlite3_version": sqlite3.sqlite_version,
        "node_version": node_version,
        "better_sqlite3_sqlite_version": better_sqlite3_version,
    }


def read_pipeline_fingerprint_rows(db_path: pathlib.Path) -> list[dict] | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='pipeline_fingerprint'"
        ).fetchone()
        if not exists:
            return None
        cols = [r[1] for r in conn.execute("PRAGMA table_info(pipeline_fingerprint)")]
        rows = conn.execute(f"SELECT {', '.join(cols)} FROM pipeline_fingerprint ORDER BY table_name").fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def main() -> int:
    pipeline_paths = collect_pipeline_paths()
    assert_paths_clean(pipeline_paths)
    head = _run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    path_hashes, hash_problems = git_path_hashes(pipeline_paths)
    if hash_problems:
        sys.exit(
            "パイプラインのパスの git ハッシュ取得に失敗した（"
            f"{len(hash_problems)}件）:\n" + "\n".join(f"  - {p}" for p in hash_problems)
        )
    src_hashes = source_hashes()

    for step in PIPELINE_STEPS:
        result = _run([sys.executable, step])
        if result.returncode != 0:
            sys.exit(f"{step} が非0で終了した（{result.returncode}）。証明は書かない。")

    gate_out_md = ROOT / "reports" / "derived_reconciliation_all.md"
    gate_result = _run(
        [sys.executable, "scripts/b02_run_all_gates.py"], capture_output=True, text=True,
    )
    print(gate_result.stdout)
    print(gate_result.stderr, file=sys.stderr)
    if gate_result.returncode != 0:
        sys.exit(f"scripts/b02_run_all_gates.py が非0で終了した（{gate_result.returncode}）。証明は書かない。")

    # b02 の出力の要約パースは scripts/s05_check_sample_gate_summary.py と
    # 同じ正規表現・同じ辞書の形が要る（CI の sample-gate ジョブが同じ出力を
    # 読む）。二重に持って食い違う余地を無くすため、そちらの `parse_summary`
    # をそのまま呼ぶ（D1）。抽出できなければ `parse_summary` 自身が
    # `sys.exit` する。
    gate_summary = s05.parse_summary(gate_result.stdout)

    candidates = {}
    for name in default_candidate_files():
        db_path = ROOT / "data" / "db" / name
        candidates[name] = {
            "sha256": pipeline_inputs.sha256_file(db_path),
            "pipeline_fingerprint_rows": read_pipeline_fingerprint_rows(db_path),
        }

    proof = {
        "schema_version": 1,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_head": head,
        "pipeline_path_hashes": path_hashes,
        "source_hashes": src_hashes,
        "environment": detect_environment(),
        "gate_summary": gate_summary,
        "derived_reconciliation_all_md_sha256": pipeline_inputs.sha256_file(gate_out_md),
        "candidates": candidates,
    }

    out_path = DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"→ {out_path}")
    print(
        f"{gate_summary['total']}表中 一致: {gate_summary['n_match']} / "
        f"宣言済み差分のみ: {gate_summary['n_declared_only']} / 不一致: {gate_summary['n_mismatch']} / "
        f"対象外: {gate_summary['n_excluded']}（適用した宣言済み差分: {gate_summary['n_applied']}件）"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
