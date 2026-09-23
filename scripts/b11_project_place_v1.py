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

## `INSERT ... SELECT` の1文で組み立てる

`scripts/b05_project_v1.py` は行を一旦 Python のタプル列に読み出してから
`executemany()` で書き戻すが、この射影は行変換（結合・列の並べ替え）以外の
集計・ピボットが無い単純な JOIN なので、`CREATE TABLE`（v1 の宣言型で）に続けて
`INSERT INTO watershed_meta SELECT ... FROM reg.place ...` を1文で実行するだけで
足りる（余計な中間テーブル・Python 側のバッファを持たない）。
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
_CREATE_WATERSHED_META_SQL = """
CREATE TABLE watershed_meta (
  watershed_id TEXT, water_system_code TEXT, water_system_name TEXT,
  water_system_category TEXT, main_rivers TEXT, area_km2 REAL,
  centroid_lat REAL, centroid_lon REAL, data_year INTEGER, source_ref TEXT
)
"""

_INSERT_WATERSHED_META_SQL = """
INSERT INTO watershed_meta
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


def _assert_every_watershed_place_has_attrs_and_ref(work: sqlite3.Connection) -> None:
    """`place_kind='watershed'` の各行が、`place_watershed`（属性サテライト）と
    `place_source_ref(source_id='watershed_meta.watershed_id')`（v1 の watershed_id
    への逆引き）をそれぞれちょうど1件ずつ持つことを検証する。

    どちらか欠けている place があると `_INSERT_WATERSHED_META_SQL` の INNER JOIN が
    その行を黙って落とす（"欠落した行が出力に現れない"という一番気づきにくい壊れ方）。
    複数件あると逆に行が水増しされる。どちらも `place`/`place_watershed`/
    `place_source_ref` を作る `scripts/registry/build_place.py` 側の不変条件だが、
    射影する側でも独立に確かめておく（`scripts/b05_project_v1.py` の
    `_assert_site_maps_to_at_most_one_zone` 等と同じ、射影固有の防御）。
    """
    n_watershed_places = work.execute(
        "SELECT COUNT(*) FROM reg.place WHERE place_kind = 'watershed'"
    ).fetchone()[0]

    missing_attrs = work.execute(
        """
        SELECT p.place_id FROM reg.place p
        WHERE p.place_kind = 'watershed'
          AND NOT EXISTS (SELECT 1 FROM reg.place_watershed pw WHERE pw.place_id = p.place_id)
        LIMIT 5
        """
    ).fetchall()
    if missing_attrs:
        raise common.MigrationError(
            f"place_kind='watershed' なのに place_watershed に行が無い place がある"
            f"（例: {[r[0] for r in missing_attrs]}）。"
            "scripts/registry/build_place.py の watershed 節を確認すること。"
        )

    missing_ref = work.execute(
        """
        SELECT p.place_id FROM reg.place p
        WHERE p.place_kind = 'watershed'
          AND NOT EXISTS (
            SELECT 1 FROM reg.place_source_ref psr
            WHERE psr.place_id = p.place_id AND psr.source_id = 'watershed_meta.watershed_id'
          )
        LIMIT 5
        """
    ).fetchall()
    if missing_ref:
        raise common.MigrationError(
            "place_kind='watershed' なのに "
            "place_source_ref(source_id='watershed_meta.watershed_id') が無い place がある"
            f"（例: {[r[0] for r in missing_ref]}）。"
            "scripts/registry/build_place.py の watershed 節を確認すること。"
        )

    # (place_id, source_id) の一意性は r01 の ID_UNIQUENESS_CHECKS が全体として
    # 保証済みだが、"watershed_meta.watershed_id" だけに絞った関数性
    # （watershed_id → place_id が1対1）もここで独立に確認する。
    dup_ref = work.execute(
        """
        SELECT external_key, COUNT(*) AS n FROM reg.place_source_ref
        WHERE source_id = 'watershed_meta.watershed_id'
        GROUP BY external_key HAVING n > 1
        LIMIT 5
        """
    ).fetchall()
    if dup_ref:
        raise common.MigrationError(
            f"watershed_meta.watershed_id が複数の place_id に対応している: {dup_ref}"
        )

    print(f"  watershed place の属性/逆引きOK: {n_watershed_places:,} 件")


def build_projections(registry_db, out_path) -> dict[str, int]:
    """`data/db/v1_projection_place.sqlite` に `watershed_meta` を書き、
    テーブルごとの行数を返す（ログ表示用）。
    """
    work = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(work, registry_db, "reg")
        _assert_every_watershed_place_has_attrs_and_ref(work)
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
