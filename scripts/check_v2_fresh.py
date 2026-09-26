#!/usr/bin/env python3
"""v2.sqlite（`data/db/v2.sqlite`。`scripts/b03_build_observation.py`〜
`scripts/b09_build_occurrence_place.py` が書く `observation`/`observation_agg`/
`occurrence`/`occurrence_agg`/`occurrence_place`）が「今の入力（原本・
`data/processed`・`registry.sqlite`）とパイプラインのコードから作ったもの」か
どうかだけを判定する（ビルドはしない）。

    .venv/bin/python3 scripts/check_v2_fresh.py [--v2-db PATH] [--ryuiki-db PATH]
        [--registry-db PATH] [--processed-dir PATH]

`scripts/r01_build_registry.py --check-fresh` と同じ終了コードの流儀
（`migrate.common.V2_CHECK_EXIT_FRESH`=0 / `V2_CHECK_EXIT_STALE`=10 / それ以外=判定不能）。
`web/scripts/ensure-v2.sh`（db:setup/entrypoint の作り直し判定）と
`web/scripts/seed-d1-local.mjs`（同じ判定をシード直前に子プロセスとして再確認し、
古ければ拒否する）がこの終了コードを読む。

## ここで見るもの・見ないもの（Issue #48 PR-0 /simplify 指摘1）

- **見る**:
  1. `observation_agg`/`occurrence_agg` それぞれの `pipeline_fingerprint.spec_version`
     が `scripts/migrate/common.py` の `OBSERVATION_AGG_SPEC_VERSION`/
     `OCCURRENCE_SPEC_VERSION`（`common.V2_CUBE_SPEC_VERSIONS`）と一致するか
     （`migrate.common.check_v2_cube_fresh()`）。PR #26 以前の13列キー
     （`imputation`/`value` 列、`pipeline_fingerprint` 表自体が無い）をこの形で検出する。
  2. v2.sqlite が最後にビルドされたときの入力（読み取り専用の原本の該当4表・
     `data/processed` の入力2つ・`registry.sqlite` 自身の `registry_build.
     input_fingerprint`）とパイプラインのコードの中身が、**今の入力・コードと
     一致するか**（`migrate.common.compute_v2_input_fingerprint()`/
     `diff_v2_input_fingerprint()`。以前の `web/scripts/ensure-v2.sh` が手書きの
     `V2_INPUTS` の mtime 走査で担っていた役割——「原本・入力・コードが変わって
     いたら古いと判定する」——を、ここに一本化した。手書きの一覧の漏れ・
     symlink の lstat mtime・「mtime は新しいが中身は古い」を見逃す弱点を、
     入力の中身の指紋一本に揃えることで解消する。詳細は
     `scripts/migrate/common.py` の該当セクション参照）。
- **見ない**: 列集合そのもの（D1 に実際に投入する側——`web/src/db/schema-cube.ts`
  で宣言し、シード先 D1 自身の `PRAGMA table_info` と突き合わせる——は
  `web/scripts/seed-d1-local.mjs` の役目。Python 側は D1 のスキーマを知らない
  ため、ここでは持たない）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# `migrate.common` は sqlite3/hashlib/os/pathlib/json/subprocess/sys/time と
# `scripts/reconcile/common.py`（PyYAML が無くても import できる。
# `reconcile.common` が `try: import yaml except ImportError: yaml = None` で
# 遅延させているため）・`scripts/pipeline_inputs.py`（依存無し）にしか依存
# しない。`--check-fresh` 系の CLI は PyYAML の無い環境でも動く必要がある
# （r01 と同じ理由。fix 1）ので、ここでも `migrate.common` 以外は import しない。
# `compute_v2_input_fingerprint()` が v2 パイプライン5段を import してコードの
# 指紋を計算するときも、フレッシュなサブプロセス（`-I -S`）で行うため PyYAML を
# 要求しない（`scripts/migrate/common.py` の `_v2_pipeline_code_files()` 参照。
# `test_cli_does_not_import_yaml` がこれを壊さないことを確認する）。
from migrate import common  # noqa: E402

DEFAULT_V2_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "processed"


def check_fresh(
    v2_db: pathlib.Path,
    *,
    ryuiki_db: pathlib.Path | None = None,
    registry_db: pathlib.Path | None = None,
    processed_dir: pathlib.Path | None = None,
) -> int:
    """`v2_db` が新鮮なら `common.V2_CHECK_EXIT_FRESH`、古ければ
    `common.V2_CHECK_EXIT_STALE` を返す。理由は stderr に1行以上出す。

    `ryuiki_db`/`registry_db`/`processed_dir` を省略すると
    `compute_v2_input_fingerprint()` 自身の既定（リポジトリの既定パス、
    `registry_db` は `RYUIKI_REGISTRY_DB` 環境変数も考慮）を使う。
    """
    if not v2_db.exists():
        print(f"v2.sqlite が無い: {v2_db}", file=sys.stderr)
        return common.V2_CHECK_EXIT_STALE

    try:
        conn = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        print(f"v2.sqlite が開けない: {v2_db}（{exc}）", file=sys.stderr)
        return common.V2_CHECK_EXIT_STALE

    try:
        problems = common.check_v2_pipeline_fresh(
            conn, ryuiki_db=ryuiki_db, registry_db=registry_db, processed_dir=processed_dir,
        )
    except sqlite3.DatabaseError as exc:
        print(f"v2.sqlite が読めない(壊れている可能性): {v2_db}（{exc}）", file=sys.stderr)
        return common.V2_CHECK_EXIT_STALE
    finally:
        conn.close()

    if problems:
        print(f"v2.sqlite が古い: {v2_db}", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return common.V2_CHECK_EXIT_STALE

    print(f"✔ 新鮮: {v2_db}")
    return common.V2_CHECK_EXIT_FRESH


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--v2-db", default=str(DEFAULT_V2_DB),
        help=f"判定対象の v2.sqlite（既定 {DEFAULT_V2_DB}）。",
    )
    parser.add_argument(
        "--ryuiki-db", default=str(DEFAULT_RYUIKI_DB),
        help=f"measurements/sensor_timeseries/organism_records/sites を持つ ryuiki.sqlite（既定 {DEFAULT_RYUIKI_DB}）。",
    )
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument(
        "--processed-dir", default=str(DEFAULT_PROCESSED_DIR),
        help=f"data/processed の入力の場所（既定 {DEFAULT_PROCESSED_DIR}）。",
    )
    args = parser.parse_args()
    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    sys.exit(
        check_fresh(
            pathlib.Path(args.v2_db),
            ryuiki_db=pathlib.Path(args.ryuiki_db),
            registry_db=registry_db,
            processed_dir=pathlib.Path(args.processed_dir),
        )
    )


if __name__ == "__main__":
    main()
