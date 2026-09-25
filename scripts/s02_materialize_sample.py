#!/usr/bin/env python3
"""縮小サンプル（`data/sample/`、テキストでコミット済み）から、正規のパス
（`data/db/ryuiki.sqlite`・`data/db/cells.sqlite`・`data/processed/*`）へ
sqlite/ファイルを組み立てる（Issue #29「縮小サンプル＋実行証明」A-1・A-4）。

    .venv/bin/python3 scripts/s02_materialize_sample.py --i-am-in-a-throwaway-clone

**安全装置（必ず両方効く）**:

1. 展開先（`data/db/ryuiki.sqlite`・`data/db/cells.sqlite`・
   `data/processed/<wholesale ファイル>` のいずれか）にファイルがすでに
   あれば拒否する。
2. `GITHUB_ACTIONS` 環境変数（値が `"true"`）か、明示のフラグ
   `--i-am-in-a-throwaway-clone` が無ければ拒否する。

この2つは独立の防御（1つ目だけでも通常は原本を守れるが、CLAUDE.md
「worktree の運用」が明記するとおり、手元の本物のチェックアウトで
うっかり走らせて再生成できない原本を壊す事故を防ぐため、2つ目も必須にする）。

**手元で試すときは、CLAUDE.md「worktree の運用」に従い一時ディレクトリへの
`git clone` で行うこと。** 本物のチェックアウト・worktree の中でこのスクリプトを
実行しない。

`data/sample/ryuiki_schema.sql`+`data/sample/ryuiki/*.sql` →
`data/db/ryuiki.sqlite`、`data/sample/cells_schema.sql`+`data/sample/cells/*.sql`
→ `data/db/cells.sqlite`、`data/sample/processed/*` → `data/processed/*` の
コピー、の3種類を行う。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
from shutil import copyfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_DIR = ROOT / "data" / "sample"
DEFAULT_DATA_DB_DIR = ROOT / "data" / "db"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "processed"


def _materialize_sqlite(schema_sql_path: pathlib.Path, tables_dir: pathlib.Path, out_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(out_path))
    try:
        conn.executescript(schema_sql_path.read_text(encoding="utf-8"))
        for sql_file in sorted(tables_dir.glob("*.sql")):
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def planned_targets(sample_dir: pathlib.Path, data_db_dir: pathlib.Path, processed_dir: pathlib.Path) -> list[pathlib.Path]:
    targets = [data_db_dir / "ryuiki.sqlite", data_db_dir / "cells.sqlite"]
    processed_src_dir = sample_dir / "processed"
    if processed_src_dir.is_dir():
        targets += [processed_dir / p.name for p in sorted(processed_src_dir.iterdir())]
    return targets


def materialize(sample_dir: pathlib.Path, data_db_dir: pathlib.Path, processed_dir: pathlib.Path) -> list[pathlib.Path]:
    """展開先にすでにファイルが無いことを呼び出し側が確認済みという前提で、
    実際にファイルを書く。戻り値は書いたファイルのパスの一覧。
    """
    data_db_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    written: list[pathlib.Path] = []

    ryuiki_out = data_db_dir / "ryuiki.sqlite"
    _materialize_sqlite(sample_dir / "ryuiki_schema.sql", sample_dir / "ryuiki", ryuiki_out)
    written.append(ryuiki_out)

    cells_out = data_db_dir / "cells.sqlite"
    _materialize_sqlite(sample_dir / "cells_schema.sql", sample_dir / "cells", cells_out)
    written.append(cells_out)

    processed_src_dir = sample_dir / "processed"
    if processed_src_dir.is_dir():
        for src in sorted(processed_src_dir.iterdir()):
            dst = processed_dir / src.name
            copyfile(src, dst)
            written.append(dst)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-dir", default=str(DEFAULT_SAMPLE_DIR))
    parser.add_argument("--data-db-dir", default=str(DEFAULT_DATA_DB_DIR))
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument(
        "--i-am-in-a-throwaway-clone", action="store_true",
        help="使い捨ての checkout（git clone した一時ディレクトリ）で実行していることを明示する。"
        "本物のチェックアウト・worktree では絶対に付けないこと。",
    )
    args = parser.parse_args()

    if os.environ.get("GITHUB_ACTIONS") != "true" and not args.i_am_in_a_throwaway_clone:
        sys.exit(
            "安全装置: GITHUB_ACTIONS 環境変数（'true'）か --i-am-in-a-throwaway-clone のどちらも"
            "無いので拒否する。このスクリプトは data/db/ryuiki.sqlite・data/db/cells.sqlite・"
            "data/processed/* を上書きする。本物のチェックアウト・worktree では絶対に実行しないこと"
            "（CLAUDE.md「worktree の運用」）。手元で試すときは一時ディレクトリへの git clone で行う。"
        )

    sample_dir = pathlib.Path(args.sample_dir)
    data_db_dir = pathlib.Path(args.data_db_dir)
    processed_dir = pathlib.Path(args.processed_dir)

    targets = planned_targets(sample_dir, data_db_dir, processed_dir)
    existing = [t for t in targets if t.exists()]
    if existing:
        lines = "\n".join(f"  - {p}" for p in existing)
        sys.exit(
            f"安全装置: 展開先にファイルがすでにある（{len(existing)}件）ので拒否する:\n{lines}\n"
            "再生成できない原本を上書きする事故を防ぐため、既存のファイルがある状態では実行しない。"
        )

    written = materialize(sample_dir, data_db_dir, processed_dir)
    for path in written:
        print(f"→ {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
