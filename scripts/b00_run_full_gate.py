#!/usr/bin/env python3
"""原本のある手元で、Phase B パイプラインをゼロから通しで回し、配信側の
スナップショット指紋（`web/scripts/serving-snapshot.mts --mode fingerprint`）が
終了コード0で出たときだけ実行証明 `reports/serving_fingerprint.json` を書く
（Issue #29「縮小サンプル＋実行証明」B。Issue #48 PR-5 で v1 との突合ゲート
`b02_run_all_gates.py` が消え、`reports/full_gate_proof.json` の後継になった）。

    .venv/bin/python3 scripts/b00_run_full_gate.py

`web/package.json` の `build:v2` と同じ順の7段（r01 → b03 → b04 → b06 → b09 →
b07 → b13）で各段のスクリプトを呼び（`PIPELINE_STEPS`。引数無し＝既定パス）、
続けて executor（全量。cwd=`web/`）を呼ぶ。**このスクリプト自身はデータの値を
一切作らない**——各段を順に呼ぶだけの薄いオーケストレータで、検証・変換の
ロジックは1行も持たない。キューブの自己不変条件（b04/b07/b09 の検査、b04 の
無作為抽出セルの独立再計算）は各段が走る中で働き、**どれかが落ちれば段が非0で
終わるので証明は書かれない**——その終了コード0が自己不変条件の証拠で、実行結果
そのものは証明に記録しない（止まることは各段の変異テストが守る）。

## 証明の中身

- パイプラインに影響するパス（`collect_pipeline_paths()`）の git tree/blob
  ハッシュ（`git rev-parse HEAD:<path>`）。**作業ツリーがこれらのパスで clean で
  あることを要求する**（さもないと「HEAD の内容」と「実際に実行したコード」が
  ずれた証明になる）。
- 原本（`ryuiki.sqlite`・`cells.sqlite`・`data/processed` の入力）の sha256。
- 環境（Python のバージョン・`sqlite3` モジュールのバージョン、Node のバージョン・
  `better-sqlite3` が実際にリンクしている SQLite のバージョン）。
- `v2.sqlite`・`registry.sqlite` の `pipeline_fingerprint` の行。
- executor の出力 `queries`（問い合わせごと・run ごとの `n_rows`・`sums`・`hash`）と、
  書き換える前の（コミット済みの）証明との差分の件数 `changes_vs_previous`。

**終了コードが0のときだけ証明を書く。** 途中のどこかで失敗すれば、証明を
書かずにそのまま非0で終了する（古い証明は上書きしない）。
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import pathlib
import platform
import sqlite3
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402

DEFAULT_OUT = ROOT / "reports" / "serving_fingerprint.json"
SCHEMA_VERSION = 1

# ADR-0016 Phase B のパイプラインに実際に影響するパス。ここに無いものが
# 変わっても証明は無効化されない（CI 側の `full-gate-proof-check` ジョブが
# 同じ集合で HEAD の tree ハッシュを計算し直し、1つでも違えば落とす）。
PIPELINE_FILE_GLOBS = ("scripts/b0*.py", "scripts/b1*.py")
PIPELINE_EXPLICIT_FILES = (
    "scripts/r01_build_registry.py",
    "scripts/pipeline_inputs.py",
    # scripts/b06_build_occurrence.py・scripts/registry/build_taxon.py が import
    # する（scripts/ 直下の単体ファイルで、b0*/b1* にも scripts/registry/ にも
    # マッチしない。code-review 指摘）。
    "scripts/taxon_namespaces.py",
    # scripts/migrate/period.py が import する元号表（requests 非依存。Issue #32-2）。
    "scripts/era_table.py",
    # scripts/registry/common.py が SCHEMA_SQL として読む（同じく scripts/ 直下の
    # 単体ファイル。code-review 指摘）。
    "scripts/schema_registry.sql",
    # 配信側のスナップショット（Issue #48 PR-5）: 何を・どう測るかの宣言と executor。
    "web/serving_queries.yaml",
    "web/scripts/serving-snapshot.mts",
    # registry の生成物（generated*.ts）を作るスクリプトと、それが import するもの
    # （`web/scripts/lib/csv.mjs` は build-registry-ts.mjs 経由）。executor・画面が読む語彙の入力。
    "web/scripts/build-registry-ts.mjs",
    "web/scripts/lib/registry-codegen.mjs",
    "web/scripts/lib/csv.mjs",
    # web/src/lib/cube が `@/` 別名で import する単体ファイル（cube/db-sqlite・cube/*.ts → db / schema-cube）。
    "web/src/lib/db.ts",
    "web/src/db/schema-cube.ts",
    "requirements.txt",
    "web/package.json",
    "web/pnpm-lock.yaml",
)
# `aggregations`（Issue #48 PR-2 §4: `scripts/b13_build_summary.py` が読む
# `aggregations/serving.yaml`）を含む。ディレクトリのまま tree ハッシュを取る。
PIPELINE_DIRS = ("scripts/registry", "scripts/migrate", "scripts/reconcile", "registry", "aggregations")
# 配下のファイルに展開して個別の blob ハッシュを取るディレクトリ（テストと
# フィクスチャは `PIPELINE_EXCLUDE_GLOBS` で外す——テストを直しただけで証明が
# 無効になるのを避ける）。`scripts/s04_check_full_gate_proof.py` も同じ関数を使う。
# `web/src/lib/registry` は cube/series と executor が語彙の読み出し（lookup*.ts・generated*.ts）で使う。
PIPELINE_EXPANDED_DIRS = ("web/scripts/lib/serving", "web/src/lib/cube", "web/src/lib/registry")
PIPELINE_EXCLUDE_GLOBS = ("**/*.test.ts", "**/__fixtures__/**")

# `web/package.json` の `build:v2` と同じ順（`test_build_v2_script_order.py` が守る）。
# 各要素は `(script, args)`——`args` は素の `main()` 呼び出し（引数無し＝既定パス）なら `()`。
PIPELINE_STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scripts/r01_build_registry.py", ()),
    ("scripts/b03_build_observation.py", ()),
    ("scripts/b04_build_cube.py", ()),
    ("scripts/b06_build_occurrence.py", ()),
    ("scripts/b09_build_occurrence_place.py", ()),
    ("scripts/b07_build_occurrence_cube.py", ()),
    ("scripts/b13_build_summary.py", ()),
)

# executor（cwd=`web/`）。`--out` は呼び出し側が足す。
SERVING_FINGERPRINT_COMMAND = (
    "pnpm", "exec", "tsx", "--import", "./scripts/lib/serving/register-aliases.mjs",
    "./scripts/serving-snapshot.mts", "--mode", "fingerprint",
)


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT), **kwargs)


def _tracked_files_under(directory: str) -> list[str]:
    """`directory` 配下の git 管理下のファイル（作業ツリーの clean は別に確かめる）。"""
    result = _run(["git", "ls-files", "--", directory], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git ls-files {directory} に失敗した: {result.stderr}")
    return result.stdout.splitlines()


def _is_excluded(path: str) -> bool:
    # fnmatch の `*` は `/` も越える（`**/__fixtures__/**` が任意の深さに効く）。
    return any(fnmatch.fnmatch(path, pattern) for pattern in PIPELINE_EXCLUDE_GLOBS)


def collect_pipeline_paths() -> list[str]:
    paths: set[str] = set(PIPELINE_EXPLICIT_FILES) | set(PIPELINE_DIRS)
    for pattern in PIPELINE_FILE_GLOBS:
        for p in sorted(ROOT.glob(pattern)):
            if p.is_file():
                paths.add(str(p.relative_to(ROOT)))
    for directory in PIPELINE_EXPANDED_DIRS:
        paths.update(f for f in _tracked_files_under(directory) if not _is_excluded(f))
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
    返す必要があるため（D3）。戻り値は `(取得できたパスのハッシュ, 失敗した行の説明)`
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
    共通——両方とも `pipeline_inputs.compute_source_hashes()` しか呼ばない）。
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


def run_serving_fingerprint() -> list[dict]:
    """executor（`--mode fingerprint`、全量）を呼び、`queries`（問い合わせごと・run ごとの
    `n_rows`/`sums`/`hash`）を返す。executor の空振り検査（全 run が0行など）で非0に
    なれば、そのまま止まる。executor の出力は `{"queries": [...]}` だけを受け、形が違えば落とす。
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "fingerprint"  # 拡張子なし（パイプラインの入力ファイル名の検出に拾われないため）
        result = subprocess.run([*SERVING_FINGERPRINT_COMMAND, "--out", str(out)], cwd=str(ROOT / "web"))
        if result.returncode != 0:
            sys.exit(f"serving-snapshot（--mode fingerprint）が非0で終了した（{result.returncode}）。証明は書かない。")
        data = json.loads(out.read_text(encoding="utf-8"))
    queries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(queries, list) or not queries:
        sys.exit("serving-snapshot の出力に queries が無い（形が壊れている）。証明は書かない。")
    return queries


def _run_hashes(query: dict) -> dict[str, str]:
    return {json.dumps(run["params"], sort_keys=True, ensure_ascii=False): run["hash"] for run in query["runs"]}


def compute_changes_vs_previous(previous: dict, queries: list[dict]) -> dict:
    """書き換える前の（コミット済みの）証明 `previous` と、今回の `queries` を run の
    `hash` で突き合わせた問い合わせごとの件数（同じ・変わった・増えた・減った）。
    run は `params` で対応づける。"""
    prev_by_id = {q["id"]: _run_hashes(q) for q in previous.get("queries", [])}
    per_query: dict[str, dict[str, int]] = {}
    for q in queries:
        new = _run_hashes(q)
        old = prev_by_id.get(q["id"], {})
        per_query[q["id"]] = {
            "same": sum(1 for k, h in new.items() if old.get(k) == h),
            "changed": sum(1 for k, h in new.items() if k in old and old[k] != h),
            "added": sum(1 for k in new if k not in old),
            "removed": sum(1 for k in old if k not in new),
        }
    # 前回にあって今回に無い問い合わせは、run が全部消えたものとして数える。
    new_ids = {q["id"] for q in queries}
    for qid, old in prev_by_id.items():
        if qid not in new_ids:
            per_query[qid] = {"same": 0, "changed": 0, "added": 0, "removed": len(old)}
    return {"previous_git_head": previous.get("git_head"), "per_query": per_query}


def load_previous_proof(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None  # 壊れた前回は比べる対象にしない（上書きして直す）


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
    previous = load_previous_proof(DEFAULT_OUT)  # 書き換える前に読む

    for step, args in PIPELINE_STEPS:
        result = _run([sys.executable, step, *args])
        if result.returncode != 0:
            sys.exit(f"{step} {' '.join(args)} が非0で終了した（{result.returncode}）。証明は書かない。")

    queries = run_serving_fingerprint()

    db_dir = ROOT / "data" / "db"
    proof = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_head": head,
        "pipeline_path_hashes": path_hashes,
        "source_hashes": src_hashes,
        "environment": detect_environment(),
        "pipeline_fingerprint_rows": {
            name: read_pipeline_fingerprint_rows(db_dir / name) for name in ("v2.sqlite", "registry.sqlite")
        },
        "queries": queries,
    }
    if previous is not None:
        proof["changes_vs_previous"] = compute_changes_vs_previous(previous, queries)

    out_path = DEFAULT_OUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(proof, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(f"→ {out_path}")
    print(f"問い合わせ {len(queries)} 件、run {sum(len(q['runs']) for q in queries)} 件の指紋を書いた")
    return 0


if __name__ == "__main__":
    sys.exit(main())
