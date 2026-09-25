#!/usr/bin/env python3
"""縮小サンプルの成果物（`declaration_counts.yaml`・`derived_keys.yaml`・
`derived_baseline.json`/`.md`）を、**原本を使わず**サンプルそのものから作り直す
（Issue #29「縮小サンプル＋実行証明」A-4「空振りしていないことを数値で確かめる」）。

    .venv/bin/python3 scripts/s03_verify_sample_artifacts.py

`scripts/s01_build_sample.py` の `build_declaration_counts`/`build_derived_keys_yaml`
は「選択済みの rowid の集合」を受け取る形になっているが、**材料化済みのサンプル
（`data/db/ryuiki.sqlite` が既にサンプルそのものであるとき）は「そのテーブルの
全行」が選択済みの集合と同じ**なので、s01 の関数をそのまま再利用できる
（原本〔828MB〕を一切開かない）。

CI の `sample-gate` ジョブはこのスクリプトを実行した後 `git diff --exit-code
data/sample/` することで、「コミットされている宣言・ベースラインが、コミット
されているサンプル本体（.sql テキスト）・パイプラインのコードと一致している」
ことを確かめる。s01 を実行し忘れた／手で編集した、のどちらも検出する。

`derived_baseline.json`/`.md` は `scripts/b01_derived_baseline.py` をそのまま
呼ぶ（`data/db/derived.sqlite` は v1 のビルド〔build-derived.mjs 等〕がこの
ジョブの中で既に作っている前提）。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import s01_build_sample as s01  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_DERIVED_DB = ROOT / "data" / "db" / "derived.sqlite"
DEFAULT_BASELINE_JSON = ROOT / "reports" / "derived_baseline.json"
DEFAULT_OUT_DIR = ROOT / "data" / "sample"

_TABLES_NEEDED_FOR_COUNTS = ("measurements", "organism_records", "sensor_timeseries")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ryuiki-db", default=str(DEFAULT_RYUIKI_DB),
        help="材料化済みのサンプル ryuiki.sqlite（原本ではない）",
    )
    parser.add_argument("--derived-db", default=str(DEFAULT_DERIVED_DB))
    parser.add_argument(
        "--baseline-json", default=str(DEFAULT_BASELINE_JSON),
        help="全量の reports/derived_baseline.json（正。derived_keys.yaml の由来）",
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

    (out_dir / "derived_keys.yaml").write_text(s01.build_derived_keys_yaml(args.baseline_json), encoding="utf-8")
    print(f"→ {out_dir / 'derived_keys.yaml'}")

    ryuiki_conn.close()

    # derived_baseline.json/.md は b01 をそのまま呼ぶ（サンプルの derived.sqlite に対して）。
    b01_cmd = [
        sys.executable, str(ROOT / "scripts" / "b01_derived_baseline.py"),
        "--db", args.derived_db,
        "--keys-yaml", str(out_dir / "derived_keys.yaml"),
        "--out-json", str(out_dir / "derived_baseline.json"),
        "--out-md", str(out_dir / "derived_baseline.md"),
    ]
    subprocess.run(b01_cmd, check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
