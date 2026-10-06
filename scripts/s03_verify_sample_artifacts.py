#!/usr/bin/env python3
"""縮小サンプルの成果物（`declaration_counts.yaml`）を、**原本を使わず**サンプルそのものから
作り直す（Issue #29「縮小サンプル＋実行証明」A-4「空振りしていないことを数値で確かめる」）。

    .venv/bin/python3 scripts/s03_verify_sample_artifacts.py

`scripts/s01_build_sample.py` の `build_declaration_counts` は「選択済みの rowid の集合」を
受け取る形になっているが、**材料化済みのサンプル（`data/db/ryuiki.sqlite` が既にサンプルそのもの
であるとき）は「そのテーブルの全行」が選択済みの集合と同じ**なので、s01 の関数をそのまま
再利用できる（原本〔828MB〕を一切開かない）。

CI の `sample-gate` ジョブはこのスクリプトを実行した後 `git diff --exit-code
data/sample/declaration_counts.yaml` することで、「コミットされている宣言が、コミットされている
サンプル本体（.sql テキスト）・パイプラインのコードと一致している」ことを確かめる。s01 を
実行し忘れた／手で編集した、のどちらも検出する。（Issue #48 PR-5 で、v1 のベースライン
`derived_baseline.json`・`derived_keys.yaml` の再生成は無くなった。）
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import s01_build_sample as s01  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_OUT_DIR = ROOT / "data" / "sample"

_TABLES_NEEDED_FOR_COUNTS = ("measurements", "organism_records", "sensor_timeseries")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ryuiki-db", default=str(DEFAULT_RYUIKI_DB),
        help="材料化済みのサンプル ryuiki.sqlite（原本ではない）",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    ryuiki_conn = s01._open_ro(args.ryuiki_db)

    # 材料化済みのサンプルでは「テーブルの全行」がそのまま選択済み集合。
    all_rows = {
        table: set(r[0] for r in ryuiki_conn.execute(f'SELECT rowid FROM "{table}"'))
        for table in _TABLES_NEEDED_FOR_COUNTS
    }

    counts = s01.build_declaration_counts(ryuiki_conn, all_rows)
    (out_dir / "declaration_counts.yaml").write_text(s01._dump_declaration_counts_yaml(counts), encoding="utf-8")
    print(f"→ {out_dir / 'declaration_counts.yaml'}")

    ryuiki_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
