#!/usr/bin/env python3
"""v2.sqlite（`data/db/v2.sqlite`。`scripts/b04_build_cube.py`・
`scripts/b07_build_occurrence_cube.py` が書く `observation_agg`/`occurrence_agg`）が
「今のパイプラインの spec で書かれたキューブ」かどうかだけを判定する（ビルドはしない）。

    .venv/bin/python3 scripts/check_v2_fresh.py [--v2-db PATH]

`scripts/r01_build_registry.py --check-fresh` と同じ終了コードの流儀
（`migrate.common.V2_CHECK_EXIT_FRESH`=0 / `V2_CHECK_EXIT_STALE`=10 / それ以外=判定不能）。
`web/scripts/ensure-v2.sh`（mtime 判定と合わせて「どちらかが古いと言えば作り直す」）と
`web/scripts/seed-d1-local.mjs`（同じ判定をシード直前に子プロセスとして再確認し、
古ければ拒否する）がこの終了コードを読む。

## ここで見るもの・見ないもの（Issue #48 PR-0 コードレビュー指摘）

- **見る**: `observation_agg`/`occurrence_agg` それぞれの
  `pipeline_fingerprint.spec_version` が `scripts/migrate/common.py` の
  `OBSERVATION_AGG_SPEC_VERSION`/`OCCURRENCE_SPEC_VERSION`
  （`common.V2_CUBE_SPEC_VERSIONS` にまとめてある）と一致するか
  （`migrate.common.check_v2_cube_fresh()`）。PR #26 以前の13列キー
  （`imputation`/`value` 列、`pipeline_fingerprint` 表自体が無い）を
  この形で検出する。
- **見ない**: 列集合そのもの（D1 に実際に投入する側——`web/src/db/schema-cube.ts`
  で宣言し、シード先 D1 自身の `PRAGMA table_info` と突き合わせる——は
  `web/scripts/seed-d1-local.mjs` の役目。Python 側は D1 のスキーマを知らない
  ため、ここでは持たない。定数の正本を1箇所に保つため——コードレビュー指摘:
  以前は `web/scripts/seed-d1-local.mjs` に `scripts/migrate/common.py` の
  定数と `web/src/db/schema-cube.ts` の列宣言、両方の手書きの写しを持っていた）。
  原本（ryuiki/cells）や v2 パイプラインのコード・宣言ファイルから見て古いか
  （= 内容が今の入力から作り直したものと一致するか）も見ない——
  `scripts/r01_build_registry.py --check-fresh` と違い、v2 パイプラインは
  まだ `compute_input_fingerprint()` 相当の「入力全体の指紋」を持たない
  （段階間の指紋〔`assert_stage_fingerprint_fresh`〕はビルド自身が実行時に
  検証する自己整合性のチェックであり、原本ファイルの mtime とは別物）。
  `web/scripts/ensure-v2.sh` が mtime 判定でこの穴を別途塞ぐ。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# `migrate.common` は sqlite3/hashlib/os/pathlib/json/time と
# `scripts/reconcile/common.py`（PyYAML が無くても import できる。
# `reconcile.common` が `try: import yaml except ImportError: yaml = None` で
# 遅延させているため）にしか依存しない。`--check-fresh` 系の CLI は
# PyYAML の無い環境でも動く必要がある（r01 と同じ理由。fix 1）ので、
# ここでも `migrate.common` 以外は import しない。
from migrate import common  # noqa: E402

DEFAULT_V2_DB = ROOT / "data" / "db" / "v2.sqlite"


def check_fresh(v2_db: pathlib.Path) -> int:
    """`v2_db` が新鮮なら `common.V2_CHECK_EXIT_FRESH`、古ければ
    `common.V2_CHECK_EXIT_STALE` を返す。理由は stderr に1行以上出す。
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
        problems = common.check_v2_cube_fresh(conn)
    except sqlite3.DatabaseError as exc:
        print(f"v2.sqlite が読めない（壊れている可能性）: {v2_db}（{exc}）", file=sys.stderr)
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
    args = parser.parse_args()
    sys.exit(check_fresh(pathlib.Path(args.v2_db)))


if __name__ == "__main__":
    main()
