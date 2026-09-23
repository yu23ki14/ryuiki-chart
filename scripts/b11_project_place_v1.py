#!/usr/bin/env python3
"""`registry.sqlite` の `place`（place_kind='watershed'）⋈ `place_watershed` ⋈
`place_source_ref` を v1 の派生表 `watershed_meta` の形に射影する
（ADR-0016 Phase B「ファクトとキューブ」P-1a、
docs/plans/PHASE_B_PLACE_ATTRIBUTES.md）。

    .venv/bin/python3 scripts/b11_project_place_v1.py

`data/db/v1_projection_place.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
`watershed_meta` 1テーブルを書く。列名・列順・宣言型は `reports/derived_baseline.json`
の記録と完全に一致させてある（`scripts/b02_derived_compare.py --candidate ...
--tables watershed_meta` がそのまま突き合わせられるように）。

## `observation`/`observation_agg`（v2.sqlite）を経由しない

`scripts/b05_project_v1.py`（measurements/sensor_timeseries 由来）は L2/キューブ
から射影するが、watershed_meta は observation を一切経由しない静的な地理データの
転記（`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同じ「キューブのセルにしない」対象の
一種）。このスクリプトは `registry.sqlite` だけを読む——`--cube-db` のような引数は
無い。

## `INSERT ... SELECT` の1文で組み立てる（列名は明示する）

`scripts/b05_project_v1.py` は行を一旦 Python のタプル列に読み出してから
`executemany()` で書き戻すが、この射影は行変換（結合・列の並べ替え）以外の
集計・ピボットが無い単純な JOIN なので、`CREATE TABLE`（v1 の宣言型で）に続けて
`INSERT INTO watershed_meta (列名...) SELECT ... FROM reg.place ...` を1文で
実行するだけで足りる（余計な中間テーブル・Python 側のバッファを持たない）。
`INSERT` 側の列名を明示するのは、`CREATE TABLE` の列順と `SELECT` の列順という
2つの離れたリテラルを手で揃える形になっており、どちらかを並べ替えたときに
（同じ TEXT 型どうしなら）誰も気づけないため（code-review 指摘）。

## 検証してから書く（読み取り専用パスと書き込みパスを分ける）

`registry.sqlite` に対する検証（下記2関数）は、出力ファイルに一切触れない
読み取り専用の一時コネクション（`:memory:` に `reg` を ATTACH しただけ）で行う。
`common.fresh_sqlite(out_path)`（既存の出力ファイル・WAL/SHM を削除してから開く）は
その検証が**全部通ったあと**にしか呼ばない——先に呼んで書き込みを始めてから検証に
失敗すると、前回の正しい出力が消えたまま空/半端なファイルが残る
（`scripts/b05_project_v1.py` は検証を先に済ませてから `write_projections()` で
書き出す構成になっており、同じ順序をここでも守る。`common.fresh_sqlite` 自体が
原本（ryuiki/cells/derived）を誤って消せる問題は P-3 側の PR で `fresh_sqlite`
共通実装に対応するため、ここでは触れない）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_place.sqlite"

# v1（`web/scripts/build-geo.mjs`、`reports/derived_baseline.json`）と列名・列順・
# 宣言型を完全に一致させる。
_WATERSHED_META_COLUMNS = (
    "watershed_id", "water_system_code", "water_system_name",
    "water_system_category", "main_rivers", "area_km2",
    "centroid_lat", "centroid_lon", "data_year", "source_ref",
)

_CREATE_WATERSHED_META_SQL = """
CREATE TABLE watershed_meta (
  watershed_id TEXT, water_system_code TEXT, water_system_name TEXT,
  water_system_category TEXT, main_rivers TEXT, area_km2 REAL,
  centroid_lat REAL, centroid_lon REAL, data_year INTEGER, source_ref TEXT
)
"""

# INSERT 側にも列名を明示する（上記 docstring「INSERT ... SELECT の1文で組み立てる」
# 参照。`_WATERSHED_META_COLUMNS` と SELECT の AS 別名の並びを一致させること）。
_INSERT_WATERSHED_META_SQL = f"""
INSERT INTO watershed_meta ({", ".join(_WATERSHED_META_COLUMNS)})
SELECT
  psr.external_key AS watershed_id,
  pw.water_system_code AS water_system_code,
  p.name_ja AS water_system_name,
  pw.water_system_category AS water_system_category,
  pw.main_rivers AS main_rivers,
  p.area_km2 AS area_km2,
  p.lat AS centroid_lat,
  p.lon AS centroid_lon,
  pw.data_year AS data_year,
  p.definition_ref AS source_ref
FROM reg.place p
JOIN reg.place_source_ref psr
  ON psr.place_id = p.place_id AND psr.source_id = 'watershed_meta.watershed_id'
JOIN reg.place_watershed pw ON pw.place_id = p.place_id
WHERE p.place_kind = 'watershed'
"""


def _assert_place_watershed_table_exists(work: sqlite3.Connection) -> None:
    """`reg.place_watershed` テーブルが存在することを確認する（無いと素の
    `sqlite3.OperationalError`（no such table）になり原因が分かりにくいため。
    `scripts/b05_project_v1.py` の `_assert_place_relation_table_exists()` と
    同じ形）。Phase B `phase-b/place-attributes`（P-1a）で新設されたテーブルなので、
    それより前にビルドした古い registry.sqlite には無い。
    """
    row = work.execute(
        "SELECT 1 FROM reg.sqlite_master WHERE type = 'table' AND name = 'place_watershed'"
    ).fetchone()
    if row is None:
        raise common.MigrationError(
            "registry.sqlite に place_watershed テーブルが無い（Phase B "
            "`phase-b/place-attributes` で新設されたテーブルなので、それより前に"
            "ビルドした古い registry.sqlite には無い）。"
            "scripts/r01_build_registry.py で registry.sqlite を作り直すこと。"
        )


def _assert_no_duplicate_watershed_source_ref_per_place(work: sqlite3.Connection) -> None:
    """`place_source_ref(source_id='watershed_meta.watershed_id')` が `place_id`
    について単射であることを検証する（射影固有の防御）。

    同じ place に対応する行が2つあると、`_INSERT_WATERSHED_META_SQL` の
    `JOIN reg.place_source_ref psr ON psr.place_id = p.place_id AND ...` が
    その place を2回ヒットさせ、377件が378件に水増しされる——一番気づきにくい
    壊れ方（行数だけを見ていると気づけない。code-review 指摘: 以前は
    `external_key` で GROUP BY しており、この水増しを検出できていなかった）。
    `(place_id, source_id)` の一意性自体は r01 の `ID_UNIQUENESS_CHECKS` が
    build_place.py の出力に対して保証済みだが（レジストリ全体の不変条件）、
    射影する側でも独立に確かめる（`scripts/b05_project_v1.py` の
    `_assert_site_maps_to_at_most_one_zone` 等と同じ、射影固有の防御）。
    """
    dup = work.execute(
        """
        SELECT psr.place_id, COUNT(*) AS n FROM reg.place_source_ref psr
        WHERE psr.source_id = 'watershed_meta.watershed_id'
        GROUP BY psr.place_id HAVING COUNT(*) > 1
        LIMIT 5
        """
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "place_source_ref(source_id='watershed_meta.watershed_id') が place_id に"
            f"ついて単射でない（同じ place に複数の external_key が対応している）: {dup}\n"
            "watershed_meta への射影が行を水増しする。scripts/registry/build_place.py の "
            "watershed 節、または r01 の ID_UNIQUENESS_CHECKS を確認すること。"
        )


def _validate_registry(registry_db) -> None:
    """`registry_db` を読み取り専用の一時コネクションで検証する。出力ファイルには
    一切触れない（`build_projections()` の docstring「検証してから書く」参照）。
    """
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, registry_db, "reg")
        _assert_place_watershed_table_exists(work)
        _assert_no_duplicate_watershed_source_ref_per_place(work)
    finally:
        work.close()


def build_projections(registry_db, out_path) -> dict[str, int]:
    """`registry_db` を検証してから `data/db/v1_projection_place.sqlite` に
    `watershed_meta` を書き、テーブルごとの行数を返す（ログ表示用）。

    検証が1つでも失敗すれば `out_path` には一切触れない（前回の正しい出力が
    残る。docstring「検証してから書く」参照）。
    """
    _validate_registry(registry_db)

    work = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(work, registry_db, "reg")
        work.execute(_CREATE_WATERSHED_META_SQL)
        work.execute(_INSERT_WATERSHED_META_SQL)
        work.commit()
        n = work.execute("SELECT COUNT(*) FROM watershed_meta").fetchone()[0]
    finally:
        work.close()
    return {"watershed_meta": n}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step(f"v1 形へ射影して {args.out} に書き出し") as info:
        counts = build_projections(registry_db, args.out)
        info["n"] = sum(counts.values())

    for table, n in sorted(counts.items()):
        print(f"  {table}: {n:,}行")


if __name__ == "__main__":
    main()
