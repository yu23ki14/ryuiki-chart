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
import hashlib
import json
import pathlib
import platform
import sqlite3
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEFAULT_OUT = ROOT / "reports" / "full_gate_proof.json"

# ADR-0016 Phase B のパイプラインに実際に影響するパス。ここに無いものが
# 変わっても証明は無効化されない（CI 側の `full-gate-proof-check` ジョブが
# 同じ集合で HEAD の tree ハッシュを計算し直し、1つでも違えば落とす）。
PIPELINE_FILE_GLOBS = ("scripts/b0*.py", "scripts/b1*.py")
PIPELINE_EXPLICIT_FILES = (
    "scripts/r01_build_registry.py",
    "reports/derived_baseline.json",
    "web/scripts/build-derived.mjs",
    "web/scripts/build-biota.mjs",
    "web/scripts/build-geo.mjs",
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

SOURCE_FILES = (
    "data/db/ryuiki.sqlite",
    "data/db/cells.sqlite",
    "data/processed/nlni_w12_watersheds.geojson",
    "data/processed/nlni_w12_watersheds.jsonl",
    "data/processed/nlni_l03b_landuse_by_watershed.csv",
    "data/processed/moe_ias_list.csv",
    "data/processed/taxon_crosswalk.csv",
)

CANDIDATE_FILES = (
    "v1_projection.sqlite",
    "v1_projection_occurrence.sqlite",
    "v1_projection_documents.sqlite",
    "v1_projection_place.sqlite",
    "v1_projection_taxon.sqlite",
)


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT), **kwargs)


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def git_path_hashes(paths: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in paths:
        result = _run(["git", "rev-parse", f"HEAD:{path}"], capture_output=True, text=True)
        if result.returncode != 0:
            sys.exit(f"git rev-parse HEAD:{path} に失敗した: {result.stderr}")
        hashes[path] = result.stdout.strip()
    return hashes


def source_hashes() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in SOURCE_FILES:
        path = ROOT / rel
        if not path.exists():
            sys.exit(f"原本が無い: {path}（CLAUDE.md「worktree の運用」に従い1ファイルずつ symlink すること）")
        out[rel] = _sha256_file(path)
    return out


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
    path_hashes = git_path_hashes(pipeline_paths)
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

    import re

    summary_match = re.search(
        r"(\d+)表中 一致: (\d+) / 宣言済み差分のみ: (\d+) / 不一致: (\d+) / 対象外: (\d+)",
        gate_result.stdout,
    )
    if not summary_match:
        sys.exit("b02_run_all_gates.py の出力からサマリ行を抽出できなかった。証明は書かない。")
    applied_match = re.search(r"適用した宣言済み差分: (\d+)件", gate_result.stdout)
    gate_summary = {
        "total": int(summary_match.group(1)),
        "n_match": int(summary_match.group(2)),
        "n_declared_only": int(summary_match.group(3)),
        "n_mismatch": int(summary_match.group(4)),
        "n_excluded": int(summary_match.group(5)),
        "n_applied": int(applied_match.group(1)) if applied_match else 0,
    }

    candidates = {}
    for name in CANDIDATE_FILES:
        db_path = ROOT / "data" / "db" / name
        candidates[name] = {
            "sha256": _sha256_file(db_path),
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
        "derived_reconciliation_all_md_sha256": _sha256_file(gate_out_md),
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
