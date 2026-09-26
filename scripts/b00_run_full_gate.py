#!/usr/bin/env python3
"""原本のある手元で、Phase B パイプラインをゼロから通しで回し、33表の統合
ゲートが緑（終了コード0）のときだけ実行証明 `reports/full_gate_proof.json` を
書く（Issue #29「縮小サンプル＋実行証明」B）。

    .venv/bin/python3 scripts/b00_run_full_gate.py

CLAUDE.md の実行順（r01 → b03→b04→b05、b06→b09→b07→b13→b08、b10、b11、b12、
最後に Issue #48 PR-2 §1(d) の v1互換キューブ4段 b03→b04→b05→b11）で各段の
スクリプトを呼び（`PIPELINE_STEPS` の `args`——大半は既定パスのまま引数無し、
v1互換キューブの4段だけ `--include-synthetic`/`--out`/`--cube-db` を渡す）、
最後に `scripts/b02_run_all_gates.py` を呼ぶ。**このスクリプト自身はデータの
値を一切作らない**——各段のスクリプトを順に呼ぶだけの薄いオーケストレータで、
検証・変換ロジックは1行も持たない（唯一の例外が `data/db/v2.sqlite` →
`data/db/v2_v1compat.sqlite` の複製——下段参照。これも変換ではなく複製）。

v1互換キューブの段は、既定パスのまま書く2本目の b05（`--cube-db
data/db/v2_v1compat.sqlite`、`--out` は渡さないため既定の
`data/db/v1_projection.sqlite` に書く）が、その直前の素の b05 が書いた
「合成データ除外後」の `v1_projection.sqlite` を「合成データを含む」内容で
**意図的に上書きし**、続く2本目の b11（`--cube-db data/db/v2_v1compat.sqlite`、
`--out` は渡さないため既定の `data/db/v1_projection_place.sqlite` に書く）が
同様に `watershed_rollup` を上書きする——これにより最後の
`b02_run_all_gates.py`（無変更）が実際には v1互換キューブ由来の内容を読み、
v1（`derived.sqlite`）とそのまま一致する（`scripts/b03_build_observation.py`
モジュール docstring「合成データを除く」節参照）。

2本目の b11 が `--cube-db` に必要とする `data/db/v2_v1compat.sqlite` は、
`observation`/`observation_agg`（合成データ込み）だけでなく `occurrence`/
`occurrence_place`/`occurrence_agg`（合成データの影響を受けない、通常の
v2.sqlite のもの）も持つ必要がある——b11 の (b) 系譜チェック
（`_assert_rollup_input_fingerprints_fresh`）が `site_var`（observation 系）と
`org_watershed`（occurrence 系）の両方の系譜を、渡された **1つの** `--cube-db`
に対して突き合わせるため。`v1compat 段の直前（b03 --include-synthetic の前）に
`data/db/v2.sqlite`（この時点で observation/occurrence 両方のキューブが揃って
いる）を丸ごと `data/db/v2_v1compat.sqlite` へ複製する——b03/b04
（`migrate.common.staged_table`）は `observation`/`observation_agg` だけを
差し替えるため、複製した `occurrence` 系のテーブルはそのまま残る。

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
import shutil
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
# `aggregations`（Issue #48 PR-2 §4: `scripts/b13_build_summary.py` が読む
# `aggregations/serving.yaml`）を追加。
PIPELINE_DIRS = ("scripts/registry", "scripts/migrate", "scripts/reconcile", "registry", "aggregations")

# CLAUDE.md の実行順。各要素は `(script, args)`——`args` は素の `main()` 呼び出し
# （引数無し＝既定パス）なら `()`（Issue #48 PR-2 §1・§4: v1互換キューブの3段
# だけが追加の引数を持つため、全段を組にして揃えた）。
PIPELINE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scripts/r01_build_registry.py", ()),
    ("scripts/b03_build_observation.py", ()),
    ("scripts/b04_build_cube.py", ()),
    ("scripts/b05_project_v1.py", ()),
    ("scripts/b06_build_occurrence.py", ()),
    ("scripts/b09_build_occurrence_place.py", ()),
    ("scripts/b07_build_occurrence_cube.py", ()),
    # Issue #48 PR-2 §4: summary 2表（observation_agg から）。v1互換の
    # 診断キューブより前——build:v2 と同じ相対順序（test_build_v2_script_order.py
    # の部分列検証）に揃える。
    ("scripts/b13_build_summary.py", ()),
    ("scripts/b08_project_occurrence_v1.py", ()),
    ("scripts/b10_project_documents_v1.py", ()),
    ("scripts/b11_project_place_v1.py", ()),
    ("scripts/b12_project_taxon_v1.py", ()),
    # Issue #48 PR-2 §1(d): 診断専用の「v1互換キューブ」——b03 に
    # `--include-synthetic` を渡し、合成データ込みで observation/
    # observation_agg/v1_projection.sqlite を別ファイル
    # （data/db/v2_v1compat.sqlite）に作り直す。b05 は `--out` を渡さない
    # （既定のまま data/db/v1_projection.sqlite——上の素の b05 が書いた
    # 「合成データ除外後」の内容を、ここで意図的に「合成データを含む」
    # 内容で上書きする）。これにより、直後に呼ぶ b02_run_all_gates.py
    # （無変更・既定のパスのまま）が実際には v1互換キューブ由来の
    # v1_projection.sqlite を読み、v1（derived.sqlite、合成データを含む）と
    # 一致する——b03 の合成データ除外という新しい差分を、宣言済み差分を
    # 増やさずに説明する（scripts/b03_build_observation.py モジュール
    # docstring「合成データを除く」節・PR-2 設計 §1）。
    (
        "scripts/b03_build_observation.py",
        ("--include-synthetic", "--out", "data/db/v2_v1compat.sqlite"),
    ),
    (
        "scripts/b04_build_cube.py",
        (
            "--out", "data/db/v2_v1compat.sqlite",
            # 合成データを含む observation には、本番では既定除外により
            # 消えた未解決の単位系列が残る（scripts/migrate/
            # unit_evidence_declarations.yaml のコメント参照）。
            "--unit-evidence-declarations-yaml",
            "scripts/migrate/unit_evidence_declarations_v1compat.yaml",
        ),
    ),
    ("scripts/b05_project_v1.py", ("--cube-db", "data/db/v2_v1compat.sqlite")),
    # watershed_rollup（b11）は site_var（上の b05 が今書き換えた、合成データ
    # 込みの v1_projection.sqlite）と org_watershed（v1_projection_occurrence.sqlite、
    # 合成データの影響を受けない）を ATTACH して結合するだけの射影だが、
    # 自分の (b) 系譜チェック（`_assert_rollup_input_fingerprints_fresh`）が
    # `--cube-db` に ATTACH した v2.sqlite 相当の `observation_agg`/`occurrence`/
    # `occurrence_place` の自己指紋と site_var/org_watershed の系譜を突き合わせる
    # ため、既定の `--cube-db`（data/db/v2.sqlite、合成データ除外後）のままだと
    # 「site_var は v2_v1compat.sqlite の observation_agg を消費したのに、
    # 渡された cube_db は違う」で落ちる。v2_v1compat.sqlite を渡す必要がある——
    # ただし v2_v1compat.sqlite は上の b03/b04 が `observation`/`observation_agg`
    # だけを差し替えた（`migrate.common.staged_table` はそのテーブルにしか
    # 触れない）ファイルなので、`occurrence`/`occurrence_place`/`occurrence_agg`
    # を最初から持たせておく必要がある——`main()` がこの段の直前で
    # `data/db/v2.sqlite` を丸ごと `data/db/v2_v1compat.sqlite` へ複製してから
    # 上の b03 --include-synthetic を実行する（下の `_COPY_V2_FOR_V1COMPAT_BEFORE`
    # 参照）。`--out` は渡さない（既定のまま data/db/v1_projection_place.sqlite——
    # 素の b11（上の無引数の段）が書いた「合成データ除外後」の内容を、ここで
    # 意図的に「合成データを含む」内容へ上書きする。b05 と同じ理由）。
    ("scripts/b11_project_place_v1.py", ("--cube-db", "data/db/v2_v1compat.sqlite")),
)

# `main()` が PIPELINE_STEPS を順に実行する際、この段の**直前**に
# `data/db/v2.sqlite`（この時点で観測・出現の両方のキューブが揃っている）を
# 丸ごと `data/db/v2_v1compat.sqlite` へ複製する（`shutil.copy2`。上の
# b11 のコメント参照）。`scripts/b03_build_observation.py --include-synthetic`
# は `migrate.common.staged_table` で `observation` テーブルだけを差し替える
# ため、複製した `occurrence`/`occurrence_place`/`occurrence_agg`
# （合成データの影響を受けない）はそのまま残る——b11 の `--cube-db` 検証に
# 両方（observation 系・occurrence 系）が要る。
_COPY_V2_FOR_V1COMPAT_BEFORE = (
    "scripts/b03_build_observation.py",
    ("--include-synthetic", "--out", "data/db/v2_v1compat.sqlite"),
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

    for step, args in PIPELINE_STEPS:
        if (step, args) == _COPY_V2_FOR_V1COMPAT_BEFORE:
            # Issue #48 PR-2 §1(d)（`_COPY_V2_FOR_V1COMPAT_BEFORE` 定義のコメント・
            # モジュール docstring 参照）: v1互換キューブの b11 が `occurrence`/
            # `occurrence_place`/`occurrence_agg` も必要とするため、この段の
            # b03 --include-synthetic を実行する前に v2.sqlite を丸ごと複製する。
            v2_path = ROOT / "data" / "db" / "v2.sqlite"
            v1compat_path = ROOT / "data" / "db" / "v2_v1compat.sqlite"
            print(f"$ cp {v2_path} {v1compat_path}")
            shutil.copy2(v2_path, v1compat_path)
        result = _run([sys.executable, step, *args])
        if result.returncode != 0:
            sys.exit(f"{step} {' '.join(args)} が非0で終了した（{result.returncode}）。証明は書かない。")

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
