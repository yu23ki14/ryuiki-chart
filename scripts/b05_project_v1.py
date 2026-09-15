#!/usr/bin/env python3
"""`observation_agg`（`data/db/v2.sqlite`、b04 が作ったキューブ）を v1 の派生
テーブル形（`meas_daily`/`meas_month`/`meas_year`/`meas_clim`/`site_var`/
`var_catalog`/`sensor_daily`/`rain_daily`/`sensor_hour_month`）に射影する
（ADR-0016 Phase B「ファクトとキューブ」縦に薄い1本。センサーの縦線の設計は
「センサーの縦線 設計 v2」オーナー決定・ADR-0023・ADR-0024 参照）。

    .venv/bin/python3 scripts/b05_project_v1.py

`data/db/v1_projection.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
9テーブルを書く。列名・列順は `reports/derived_baseline.json` の記録と完全に
一致させてある（`scripts/b02_derived_compare.py --tables ...` がそのまま
突き合わせられるように）。

## `meas_clim`/`site_var`/`var_catalog` はキューブのセルにしない（オーナー決定）

`docs/plans/PHASE_B_FACT_SLICE.md` D10 参照（変更なし。この3テーブルは
`measurements` 由来のみで、センサーの縦線とは無関係）。

## センサーの縦線 設計 v2 T5: `sensor_daily`/`rain_daily`/`sensor_hour_month`
は v1 の癖を射影にだけ置く

v1（`web/scripts/build-derived.mjs`）の3テーブルは、`sensor_timeseries` を
`phenomenon_time` の**ラベルの日付**（`substr(phenomenon_time,1,10)`）で
日割りしている。sagamihara/soramame の毎時値は hour_ending（ラベル＝区間の
終わり）なので、ラベル日割りは「23時〜24時の値をラベルの日（＝翌日）に
入れる」という、区間の境界をはみ出す集計になっている（v1 の癖。正しい
日割りは区間の始まりの日付）。キューブ（b04）はこれを直しており
（`substr(period_start,1,10)`。`period_start` は b03 が既にラベル−1時間を
計算済み）、そのためキューブの日次セルは v1 とビット一致しない。

- `sensor_daily`:
  - (a) `value_grain ∈ {day, instant}` の出典（hiratsuka/jma_daily/yokohama/
    合成）→ **キューブの日次セル**から（mean/min/max をピボット）。日次・
    瞬時はラベルの日付＝区間の始まりの日付なので v1 と一致する
    （`_SENSOR_DAILY_FROM_CUBE_SQL`）。
  - (b) `value_grain='hour'` の出典（sagamihara/soramame）→ **`observation`
    （L2）から `substr(period_raw,1,10)`（v1 のラベル日割り）で直接集計**し
    UNION ALL（`_SENSOR_DAILY_FROM_L2_SQL`）。キューブを経由しない——
    「メンバーの区間がセルの区間をはみ出す集計は、原理的にキューブのセルに
    なれない」（`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同じ理由）。
- `rain_daily`: 同じく L2 から（RAIN は sagamihara の毎時）。
  `ROUND(SUM(value_num)/10.0, 2)`、`COUNT(*)`、`GROUP BY substr(period_raw,1,10)`。
  `/10` は v1 の推測換算をそのまま再現するためだけに射影に置く（v1 のコメント
  「0.1mm 単位」。レジストリは RAIN の単位不明のまま・推測しない）。
- `sensor_hour_month`: 月×時刻の平年は D10 の2例目（climatology の軸は
  セルにしない）。L2 から、**月・時刻は `period_raw` から取る**
  （`period_start` だと hour_ending で1時間ずれる）。地点をまたいで混ぜる
  （v1 と同じ）。`value_grain IN ('hour', 'instant')`（25桁ラベルを持つ
  出典。v1 の `LENGTH(phenomenon_time) >= 13` と同じ範囲——10桁の日次・7桁の
  月次は除外される）。

## 逆引きの検証（tuple の一意性 / 関数性）を dataset ごとに分けて行う

`measurements`/`sensor_timeseries` はそれぞれ独立に
`(variable_id, grain, stat, unit_id) → alias` の関数性を検証する
（`assert_alias_is_function(work, dataset=...)`）。加えて、**tuple →
dataset の一意性**も検証する（`assert_alias_tuple_maps_to_single_dataset`。
T5）: 同じ `(variable_id, grain, stat, unit_id)` が `measurements` と
`sensor_timeseries` の両方の alias に現れていないことを確認する——崩れて
いると、同じキューブのセルが `meas_*` と `sensor_*` の両方の出力テーブルに
二重に現れる（各テーブルの逆引き JOIN は `dataset` ごとに絞っているだけで、
tuple 自体の一意性は保証していないため。実測では衝突0件だが、無防備な
ままにしない）。

## 数値はキューブから、ラベルは引き戻しで

（`measurements` 由来の6テーブルについては `docs/plans/PHASE_B_FACT_SLICE.md`
と変わらない。`site_id`/`variable`/`unit` の逆引きの仕組みは
`sensor_daily`/`rain_daily`/`sensor_hour_month` でも同じ `place_lookup`/
`*_alias_lookup`/`*_unit_lookup` を使う。）

## meas_year のピボット（design.md D5・D6）は変更なし

## T4-3: `cube_day` を読む箇所の `stat='mean'` 絞り込み

`_MEAS_DAILY_SQL`/`_MEAS_MONTH_SQL` に `AND c.stat = 'mean'` を明示的に足した
（b04 が日次セルに `mean`/`min`/`max`/`sum` の複数行を持つようになったため。
絞らないと `meas_daily`/`meas_month` の値に min/max/sum が混ざる——既存
6テーブルの値が黙って変わる、最も疑わしい箇所。`meas_month` は現状
measurements 側の月次出典配布セルが存在しない（`measurements` の
value_grain に `'month'` が無い）ため実害は無いが、将来の事故を防ぐために
同じ絞り込みを足す）。

## T6: 毎時→日次の正しさを機械で確かめる（`verify_hourly_daily_rollup`）

`value_grain='hour'` の各系列・各日 D について、
**キューブの日次セルの n = v1形（L2 のラベル日割り）の日 D の n
− (日 D のラベル 00 時の件数) + (日 D+1 のラベル 00 時の件数)**
が全日で成り立つことを検証する（時刻帯の9時間ずれ・日割りの誤りはこれで
捕まる）。あわせて、系列ごとの全期間の Σn・min・max がキューブの日次セルと
L2 で一致することも確認する。どちらも崩れていれば `MigrationError` で
止まる（ゲートがこの経路を直接見なくなる——`sensor_daily` の毎時分はキューブを
経由しないため——代わりの機械検証）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection.sqlite"
DEFAULT_BASELINE_JSON = ROOT / "reports" / "derived_baseline.json"

_DIM_SELECT7 = "variable_id, grain, stat, unit_id"  # alias_lookup の元キー（dataset内）


def _alias_lookup_sql(dataset: str) -> str:
    """`(variable_id, grain, stat, unit_id) → alias` の逆引き元 SQL
    （`dataset` でデータセットを絞る。`measurements`/`sensor_timeseries` の
    どちらでも使う）。

    NULL を含みうる `grain`/`stat`/`unit_id` を JOIN 条件で `IS` 比較すると
    SQLite は自動インデックスを使わず、`observation_agg`（200万行弱）との
    ネストループが実測で数分かかる。そのため呼び出し側で一時テーブルとして
    実体化し、NULL を空文字に正準化した「結合キー」列にインデックスを張って
    通常の等値 JOIN にする（`_materialize_lookup_tables` 参照）。`dataset` は
    このモジュール内の固定文字列（呼び出し側が渡すユーザー入力ではない）
    なのでバインドパラメータにせずそのまま埋め込む。
    """
    return f"""
    SELECT variable_id, grain, stat, unit_id, alias,
           variable_id || '|' || COALESCE(grain, '') || '|' || COALESCE(stat, '') || '|' ||
           COALESCE(unit_id, '') AS akey
    FROM reg.variable_alias
    WHERE dataset = '{dataset}'
    GROUP BY variable_id, grain, stat, unit_id
    """


def _unit_lookup_sql(source_table: str) -> str:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` の逆引き元
    SQL（`source_table`——`observation.source_table` の値——で絞る）。
    `observation_agg`（ADR-0011 のキューブ）は `unit_raw` を持たないため、
    `cube.observation`（キューブではなくファクト）から引く。
    """
    return f"""
    SELECT variable_id, value_grain, obs_stat, unit_id,
           variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' ||
           COALESCE(unit_id, '') AS akey,
           MAX(unit_raw) AS unit_raw
    FROM cube.observation
    WHERE source_table = '{source_table}'
    GROUP BY variable_id, value_grain, obs_stat, unit_id
    """


# `observation_agg` 側にも同じ形の結合キーを持つ VIEW を張る（`c.akey` として参照）。
_OBS_AGG_KEYED_VIEW_SQL = """
CREATE TEMP VIEW obs_agg_keyed AS
SELECT *,
       variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' ||
       COALESCE(unit_id, '') AS akey
FROM cube.observation_agg
"""

# ---------------------------------------------------------------------------
# measurements 由来 6テーブル（変更点: meas_daily/meas_month に stat='mean' を追加）
# ---------------------------------------------------------------------------

_MEAS_DAILY_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable, c.period_start AS d,
       c.value AS value, c.n AS n_raw, c.n_censored AS n_censored, ul.unit_raw AS unit
FROM obs_agg_keyed c
JOIN place_lookup psr ON psr.place_id = c.place_id
JOIN alias_lookup al ON al.akey = c.akey
JOIN unit_lookup ul ON ul.akey = c.akey
WHERE c.grain = 'day' AND c.stat = 'mean'
"""

_MEAS_MONTH_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable,
       substr(c.period_start, 1, 7) AS ym,
       CAST(substr(c.period_start, 1, 4) AS INT) AS year,
       CAST(substr(c.period_start, 6, 2) AS INT) AS month,
       c.n AS n, c.value AS avg, ul.unit_raw AS unit
FROM obs_agg_keyed c
JOIN place_lookup psr ON psr.place_id = c.place_id
JOIN alias_lookup al ON al.akey = c.akey
JOIN unit_lookup ul ON ul.akey = c.akey
WHERE c.grain = 'month' AND c.stat = 'mean'
"""

# 年次セルは stat ごとに別行（b04）。同じグループを1行にまとめるための結合キー。
_MEAS_YEAR_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable,
       CASE WHEN m.input_grain = 'day' THEN 'daily' ELSE 'annual' END AS kind,
       CAST(substr(m.period_start, 1, 4) AS INT) AS year,
       m.n AS n, m.value AS avg, mn.value AS min, mx.value AS max,
       m.n_censored AS n_censored, ul.unit_raw AS unit
FROM year_keyed m
JOIN year_keyed mn ON mn.gkey = m.gkey AND mn.stat = 'min'
JOIN year_keyed mx ON mx.gkey = m.gkey AND mx.stat = 'max'
JOIN unit_lookup ul ON ul.akey = m.akey
JOIN place_lookup psr ON psr.place_id = m.place_id
JOIN alias_lookup al ON al.akey = m.akey
WHERE m.stat = 'mean'
"""

_MEAS_CLIM_SQL = """
SELECT variable, CAST(substr(d, 6, 2) AS INT) AS month,
       COUNT(*) AS n, AVG(value) AS avg,
       MIN(value) AS min, MAX(value) AS max, MAX(unit) AS unit
FROM meas_daily
GROUP BY variable, month
"""

_VAR_CATALOG_SQL = """
SELECT variable,
       MAX(unit) AS unit,
       SUM(n) AS n,
       COUNT(DISTINCT site_id) AS n_sites,
       MIN(year) AS y_from, MAX(year) AS y_to,
       SUM(CASE WHEN kind = 'daily' THEN n ELSE 0 END) AS n_daily,
       SUM(CASE WHEN kind = 'annual' THEN n ELSE 0 END) AS n_annual,
       SUM(n_censored) AS n_censored
FROM meas_year
GROUP BY variable
"""

_SITE_VAR_SQL = """
SELECT site_id, variable, kind, SUM(n) AS n, MIN(year) AS y_from, MAX(year) AS y_to,
       AVG(avg) AS avg, MAX(unit) AS unit
FROM meas_year
GROUP BY site_id, variable, kind
"""

# ---------------------------------------------------------------------------
# sensor_timeseries 由来 3テーブル（T5）
# ---------------------------------------------------------------------------

# (a) value_grain IN ('day', 'instant') はキューブの日次セルから（mean/min/max
# をピボット）。`day_keyed` は `_materialize_lookup_tables` が sensor_alias_lookup
# の akey に絞って作る（measurements の日次セル約141万行を無駄にスキャンしない）。
_SENSOR_DAILY_FROM_CUBE_SQL = """
SELECT psr.external_key AS site_id, al.alias AS datastream, m.period_start AS d,
       m.n AS n, m.value AS avg, mn.value AS min, mx.value AS max, ul.unit_raw AS unit
FROM day_keyed m
JOIN day_keyed mn ON mn.gkey = m.gkey AND mn.stat = 'min'
JOIN day_keyed mx ON mx.gkey = m.gkey AND mx.stat = 'max'
JOIN sensor_unit_lookup ul ON ul.akey = m.akey
JOIN place_lookup psr ON psr.place_id = m.place_id
JOIN sensor_alias_lookup al ON al.akey = m.akey
WHERE m.stat = 'mean'
"""

# (b) value_grain='hour' は L2（observation）から、v1 のラベル日割り
# （substr(period_raw,1,10)）で直接集計する（キューブを経由しない。D10 と
# 同じ理由。モジュール docstring 参照）。`label25_obs_keyed` は
# `value_grain IN ('hour','instant')` の観測（25桁ラベル）だけを持つ一時
# テーブル（`_materialize_lookup_tables` が作る。sensor_hour_month とも共有）。
_SENSOR_DAILY_FROM_L2_SQL = """
SELECT psr.external_key AS site_id, al.alias AS datastream,
       substr(o.period_raw, 1, 10) AS d,
       COUNT(*) AS n, AVG(o.value_num) AS avg, MIN(o.value_num) AS min, MAX(o.value_num) AS max,
       ul.unit_raw AS unit
FROM label25_obs_keyed o
JOIN sensor_alias_lookup al ON al.akey = o.akey
JOIN sensor_unit_lookup ul ON ul.akey = o.akey
JOIN place_lookup psr ON psr.place_id = o.place_id
WHERE o.value_grain = 'hour' AND o.value_num IS NOT NULL
GROUP BY psr.external_key, al.alias, substr(o.period_raw, 1, 10)
"""

_SENSOR_DAILY_SQL = f"""
{_SENSOR_DAILY_FROM_CUBE_SQL}
UNION ALL
{_SENSOR_DAILY_FROM_L2_SQL}
"""

# 相模原の雨量は 0.1mm 単位（v1 のコメント「原本に unit の記載が無いので mm に
# 直した」をそのまま再現するためだけに /10 する。レジストリは RAIN の単位を
# 推測しない）。L2 から、v1 のラベル日割りで直接集計する（datastream='RAIN'
# の等価物として al.alias='RAIN' を使う——sagamihara_taiki_hourly の RAIN
# エイリアスの alias 文字列そのものが 'RAIN' なので一致する）。
_RAIN_DAILY_SQL = """
SELECT substr(o.period_raw, 1, 10) AS d,
       ROUND(SUM(o.value_num) / 10.0, 2) AS mm,
       COUNT(*) AS n_hours
FROM label25_obs_keyed o
JOIN sensor_alias_lookup al ON al.akey = o.akey
WHERE o.value_grain = 'hour' AND al.alias = 'RAIN' AND o.value_num IS NOT NULL
GROUP BY substr(o.period_raw, 1, 10)
"""

# 時刻×月のヒートマップ。月・時刻は period_raw から取る（period_start だと
# hour_ending で1時間ずれる。モジュール docstring 参照）。地点をまたいで混ぜる
# （v1 と同じ。site_id を GROUP BY に持たない）。
_SENSOR_HOUR_MONTH_SQL = """
SELECT al.alias AS datastream,
       CAST(substr(o.period_raw, 6, 2) AS INT) AS month,
       CAST(substr(o.period_raw, 12, 2) AS INT) AS hour,
       COUNT(*) AS n, AVG(o.value_num) AS avg, MAX(o.value_num) AS max
FROM label25_obs_keyed o
JOIN sensor_alias_lookup al ON al.akey = o.akey
WHERE o.value_num IS NOT NULL
GROUP BY al.alias, month, hour
"""

_TABLE_SQL = {
    "meas_daily": "SELECT * FROM meas_daily",
    "meas_month": _MEAS_MONTH_SQL,
    "meas_year": "SELECT * FROM meas_year",
    "meas_clim": _MEAS_CLIM_SQL,
    "site_var": _SITE_VAR_SQL,
    "var_catalog": _VAR_CATALOG_SQL,
    "sensor_daily": _SENSOR_DAILY_SQL,
    "rain_daily": _RAIN_DAILY_SQL,
    "sensor_hour_month": _SENSOR_HOUR_MONTH_SQL,
}


def _materialize_lookup_tables(work: sqlite3.Connection) -> None:
    """自動インデックスの効かない `IS`（NULL-safe）JOIN を、実体化した一時
    テーブル＋インデックスの通常の等値 JOIN に置き換える。`measurements`/
    `sensor_timeseries` の両方ぶんの逆引きテーブルをここで作る。
    """
    work.execute(_OBS_AGG_KEYED_VIEW_SQL)

    work.execute(f"CREATE TEMP TABLE alias_lookup AS {_alias_lookup_sql('measurements')}")
    work.execute("CREATE UNIQUE INDEX alias_lookup_akey ON alias_lookup (akey)")
    work.execute(f"CREATE TEMP TABLE unit_lookup AS {_unit_lookup_sql('measurements')}")
    work.execute("CREATE UNIQUE INDEX unit_lookup_akey ON unit_lookup (akey)")

    work.execute(f"CREATE TEMP TABLE sensor_alias_lookup AS {_alias_lookup_sql('sensor_timeseries')}")
    work.execute("CREATE UNIQUE INDEX sensor_alias_lookup_akey ON sensor_alias_lookup (akey)")
    work.execute(f"CREATE TEMP TABLE sensor_unit_lookup AS {_unit_lookup_sql('sensor_timeseries')}")
    work.execute("CREATE UNIQUE INDEX sensor_unit_lookup_akey ON sensor_unit_lookup (akey)")

    work.execute(
        """
        CREATE TEMP TABLE year_keyed AS
        SELECT *,
               place_id || '|' || akey || '|' || period_start || '|' || input_grain AS gkey
        FROM obs_agg_keyed
        WHERE grain IN ('year', 'fiscal_year')
        """
    )
    work.execute("CREATE INDEX year_keyed_gkey_stat ON year_keyed (gkey, stat)")

    # sensor_daily (a) 用。sensor_alias_lookup の akey に絞って作る——
    # measurements の日次セル（約141万行）を無駄にスキャンしない
    # （`obs_agg_keyed` を JOIN の時点で sensor 側の akey だけに絞り込む）。
    work.execute(
        """
        CREATE TEMP TABLE day_keyed AS
        SELECT c.*, c.place_id || '|' || c.akey || '|' || c.period_start || '|' || c.input_grain AS gkey
        FROM obs_agg_keyed c
        JOIN sensor_alias_lookup al ON al.akey = c.akey
        WHERE c.grain = 'day' AND c.input_grain IN ('day', 'instant')
        """
    )
    work.execute("CREATE INDEX day_keyed_gkey_stat ON day_keyed (gkey, stat)")

    # sensor_daily (b)・rain_daily・sensor_hour_month で共有する、25桁ラベル
    # （value_grain IN ('hour','instant')）だけの一時テーブル。v1
    # （sensor_daily/rain_daily/sensor_hour_month）はどれもこの範囲の
    # observation をキューブを経由せず直接集計する（T5）。
    work.execute(
        """
        CREATE TEMP TABLE label25_obs_keyed AS
        SELECT *,
               variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' ||
               COALESCE(unit_id, '') AS akey
        FROM cube.observation
        WHERE value_grain IN ('hour', 'instant')
        """
    )
    work.execute("CREATE INDEX label25_obs_keyed_akey ON label25_obs_keyed (akey)")

    work.execute(
        "CREATE TEMP TABLE place_lookup AS "
        "SELECT place_id, external_key FROM reg.place_source_ref WHERE source_id = 'sites.site_id'"
    )
    dup_places = work.execute(
        "SELECT place_id, COUNT(*) AS n FROM place_lookup GROUP BY place_id HAVING n > 1 LIMIT 5"
    ).fetchall()
    if dup_places:
        raise common.MigrationError(
            "place_source_ref（source_id='sites.site_id'）が place_id について単射でない"
            f"（同じ place_id に複数の external_key（site_id）が対応している。例: {dup_places}）。"
            "キューブのキー place_id から v1 の site_id を一意に復元できないため、射影が"
            "決まらない。place_source_ref 側の重複を解消してから再実行すること。"
        )
    work.execute("CREATE UNIQUE INDEX place_lookup_place_id ON place_lookup (place_id)")


def _materialize_projection_tables(work: sqlite3.Connection) -> None:
    """逆引き済みの `meas_daily`/`meas_year` をそれぞれ1回だけ一時テーブルに
    実体化する（`meas_clim`/`site_var`/`var_catalog` がここから読む。変更なし
    ——`measurements` 専用で `sensor_timeseries` とは無関係）。
    """
    work.execute(f"CREATE TEMP TABLE meas_daily AS {_MEAS_DAILY_SQL}")
    work.execute(f"CREATE TEMP TABLE meas_year AS {_MEAS_YEAR_SQL}")


def assert_alias_is_function(work, dataset: str = "measurements", grains: tuple[str, ...] | None = None) -> None:
    """`(variable_id, grain, stat, unit_id) → alias` が `dataset` 内で関数で
    あることを確認する。衝突があれば、どの組が何個の alias に割れているかを
    示して止まる——`MIN(alias)` 等で黙って1つを選ばない。

    `grains` を渡すと、その grain（`value_grain`）だけに絞って検証する。
    実データで `sensor_timeseries`/`jma_monthly_kanagawa` の積雪関連3変数
    （`weather.snow_depth_max`/`snowfall_depth_total`/
    `snowfall_depth_max_daily`）に、CSV の列名が年度によって揺れている
    らしく同じ `(variable_id, grain='month', stat, unit_id)` に2つの alias
    文字列（例: `'雪_最深 積雪'`／`'雪_最深積雪'`。全角スペースの有無だけの
    違い）が対応していることが実測で判明した。`sensor_daily`/`rain_daily`/
    `sensor_hour_month`（T5）はどれも `value_grain IN ('day','hour','instant')`
    しか消費せず、`grain='month'`（jma_monthly の出典配布月次値。design.md
    実測の要点「v1 の射影対象外」）は射影しない——この重複は b05 が実際に
    読む範囲の外にあるので、呼び出し側が `grains` で消費範囲だけに絞って
    検証する（月次の重複自体は登録の負債として残るが、機能には影響しない）。
    """
    grain_filter = ""
    params: tuple = (dataset,)
    if grains is not None:
        placeholders = ", ".join("?" for _ in grains)
        grain_filter = f" AND grain IN ({placeholders})"
        params = (dataset, *grains)
    dup = work.execute(
        f"""
        SELECT variable_id, grain, stat, unit_id, COUNT(DISTINCT alias) AS n_alias
        FROM reg.variable_alias
        WHERE dataset = ?{grain_filter}
        GROUP BY variable_id, grain, stat, unit_id
        HAVING n_alias > 1
        """,
        params,
    ).fetchall()
    if dup:
        raise common.MigrationError(
            f"({dataset}) (variable_id, grain, stat, unit_id) -> alias が関数になっていない"
            f"（同じ組に複数の alias がある）: {dup}\n"
            "b05 は『どちらの alias を v1 の variable/datastream 名として使うか』を推測できない"
            "ため、variable_alias 側の重複を解消してから再実行すること。"
        )


def assert_alias_tuple_maps_to_single_dataset(work) -> None:
    """`(variable_id, grain, stat, unit_id)` が `measurements` と
    `sensor_timeseries` の両方の alias に対応していないことを確認する
    （設計 v2 T5）。崩れていると、同じキューブのセルが `meas_*` と
    `sensor_*` の両方の出力テーブルに二重に現れる——各テーブルの逆引き JOIN
    は `dataset` ごとに絞っているだけで、tuple 自体が2つの dataset に
    またがらないことまでは保証していないため。実測では衝突0件だが、
    `assert_alias_is_function` が捕まえる壊れ方（順方向の衝突）とは別の
    壊れ方なので、そのまま残す。
    """
    dup = work.execute(
        """
        SELECT variable_id, grain, stat, unit_id,
               COUNT(DISTINCT dataset) AS n_dataset, GROUP_CONCAT(DISTINCT dataset) AS datasets
        FROM reg.variable_alias
        GROUP BY variable_id, grain, stat, unit_id
        HAVING n_dataset > 1
        """
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "(variable_id, grain, stat, unit_id) が複数の dataset にまたがっている"
            f"（同じキューブのセルが meas_* と sensor_* の両方の出力テーブルに二重に現れる"
            f"恐れがある）: {dup}\nvariable_alias 側で tuple が dataset をまたいで重複しない"
            "ようにしてから再実行すること。"
        )


def assert_unit_raw_is_function(work) -> None:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` が関数で
    あることを確認する（B-1）。`cube.observation`（ファクト）全体——
    `measurements`/`sensor_timeseries` の両方——を見る。実測では衝突0件
    （1つの系列は1種類の単位しか持たない）だが、将来2種以上の unit_raw を
    持つ系列が現れたら、どの組が何種に割れているかを示して止まる。
    """
    dup = work.execute(
        """
        SELECT variable_id, value_grain, obs_stat, unit_id, COUNT(DISTINCT unit_raw) AS n_unit_raw
        FROM cube.observation
        GROUP BY variable_id, value_grain, obs_stat, unit_id
        HAVING n_unit_raw > 1
        """
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "(variable_id, value_grain, obs_stat, unit_id) -> unit_raw が関数になっていない"
            f"（同じ系列に複数の unit_raw がある）: {dup}\n"
            "b05 は『どの unit_raw を v1 の unit 表記として使うか』を推測できないため、"
            "該当する系列の unit_raw の食い違いを解消してから再実行すること。"
        )


def _load_v1_keys(baseline_json_path) -> dict[str, list[str]]:
    data = json.loads(pathlib.Path(baseline_json_path).read_text(encoding="utf-8"))
    return {table: list(data["tables"][table]["key"]) for table in _TABLE_SQL}


def assert_v1_keys_are_unique(
    projections: dict[str, tuple[list[str], list[tuple]]], keys_by_table: dict[str, list[str]]
) -> None:
    """射影したテーブルそれぞれについて、v1（`derived_baseline.json`）のキー列
    で行が一意であることを確認する（アドバイザー指摘・オーナー採用）。
    """
    for table, (columns, rows) in projections.items():
        key_cols = keys_by_table[table]
        idx = [columns.index(c) for c in key_cols]
        counts: dict[tuple, int] = {}
        for row in rows:
            k = tuple(row[i] for i in idx)
            counts[k] = counts.get(k, 0) + 1
        dup = [(k, n) for k, n in counts.items() if n > 1][:5]
        if dup:
            raise common.MigrationError(
                f"{table}: v1 のキー {key_cols} が一意でない行がある（例（キー, 件数）: {dup}）。"
                "alias が複数の (variable_id, value_grain, obs_stat, unit_id) に対応している"
                "ため v1 の GROUP BY を復元できない。variable_alias 側で alias を出典ごとに"
                "分けるなど、v1 の1グループに対応する alias を1つに絞ってから再実行すること。"
            )


# ---------------------------------------------------------------------------
# T6: 毎時→日次の正しさの機械検証
# ---------------------------------------------------------------------------

_HOUR_SERIES_DIM = "region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain"


def verify_hourly_daily_rollup(work: sqlite3.Connection, sample_limit: int = 20) -> dict:
    """`value_grain='hour'` の各系列・各日 D について、
    **キューブの日次セルの n = v1形（L2 のラベル日割り）の日 D の n
    − (日 D のラベル 00 時の件数) + (日 D+1 のラベル 00 時の件数)**
    が全日で成り立つことを検証する（T6）。あわせて、系列ごとの全期間の
    Σn・min・max がキューブの日次セルと L2 で一致することも確認する。

    どちらか一方でも崩れていれば `common.MigrationError` で止まる。
    戻り値は検証した件数（レポート用）。`_materialize_lookup_tables` の後
    （`label25_obs_keyed`/`day_keyed` を使う）に呼ぶ。
    """
    # 日ごとの v1形の件数と、「ラベルが00:00:00（日をまたぐ24時ラベル）の件数」
    # を同じクエリで求める。
    v1_daily = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, substr(period_raw, 1, 10) AS d,
               COUNT(*) AS n,
               SUM(CASE WHEN substr(period_raw, 12, 8) = '00:00:00' THEN 1 ELSE 0 END) AS n_midnight
        FROM label25_obs_keyed
        WHERE value_grain = 'hour' AND value_num IS NOT NULL
        GROUP BY {_HOUR_SERIES_DIM}, d
        """
    ).fetchall()

    # キューブの日次セル（stat='mean'。n は mean/min/max のどれでも同じ値）。
    # day_keyed は value_grain IN ('day','instant') のみに絞って作られている
    # ため（`_materialize_lookup_tables`）、ここでは observation_agg を直接見る。
    cube_daily = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, period_start AS d, n
        FROM cube.observation_agg
        WHERE grain = 'day' AND input_grain = 'hour' AND stat = 'mean'
        """
    ).fetchall()

    v1_n: dict[tuple, int] = {}
    v1_midnight: dict[tuple, int] = {}
    for row in v1_daily:
        key = row[:7]
        d = row[7]
        v1_n[(key, d)] = row[8]
        v1_midnight[(key, d)] = row[9]

    cube_n: dict[tuple, int] = {}
    for row in cube_daily:
        key = row[:7]
        d = row[7]
        cube_n[(key, d)] = row[8]

    all_days = set(v1_n) | set(cube_n)
    mismatches: list[tuple] = []
    for key, d in all_days:
        d_next = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        expected = v1_n.get((key, d), 0) - v1_midnight.get((key, d), 0) + v1_midnight.get((key, d_next), 0)
        actual = cube_n.get((key, d), 0)
        if expected != actual:
            mismatches.append((key, d, expected, actual))
    if mismatches:
        raise common.MigrationError(
            "T6: キューブの日次セルの n が v1形のラベル日割りから期待される値と"
            f"食い違う日がある（{len(mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, 日, 期待値, 実際の値)）: {mismatches[:sample_limit]}）。"
            "scripts/migrate/period.py の hour_ending 変換（ラベル-1時間）または"
            "scripts/b04_build_cube.py の日割り（substr(period_start,1,10)）を確認すること。"
        )

    # 系列ごとの全期間の Σn・min・max が一致すること。
    l2_totals = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, COUNT(*) AS n, MIN(value_num) AS vmin, MAX(value_num) AS vmax
        FROM label25_obs_keyed
        WHERE value_grain = 'hour' AND value_num IS NOT NULL
        GROUP BY {_HOUR_SERIES_DIM}
        """
    ).fetchall()
    cube_totals = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM},
               SUM(CASE WHEN stat = 'mean' THEN n END) AS n,
               MIN(CASE WHEN stat = 'min' THEN value END) AS vmin,
               MAX(CASE WHEN stat = 'max' THEN value END) AS vmax
        FROM cube.observation_agg
        WHERE grain = 'day' AND input_grain = 'hour'
        GROUP BY {_HOUR_SERIES_DIM}
        """
    ).fetchall()
    l2_by_key = {row[:7]: row[7:] for row in l2_totals}
    cube_by_key = {row[:7]: row[7:] for row in cube_totals}
    total_mismatches = []
    for key in set(l2_by_key) | set(cube_by_key):
        l2_vals = l2_by_key.get(key)
        cube_vals = cube_by_key.get(key)
        if l2_vals != cube_vals:
            total_mismatches.append((key, l2_vals, cube_vals))
    if total_mismatches:
        raise common.MigrationError(
            "T6: 系列ごとの全期間の Σn・min・max が L2 とキューブの日次セルで食い違う"
            f"（{len(total_mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, L2側(n,min,max), キューブ側(n,min,max))）: "
            f"{total_mismatches[:sample_limit]}）。"
        )

    return {"n_series_days_checked": len(all_days), "n_series_checked": len(set(l2_by_key) | set(cube_by_key))}


def build_projections(
    cube_db, registry_db, baseline_json=DEFAULT_BASELINE_JSON
) -> dict[str, list[tuple]]:
    """9テーブルぶんの `(columns, rows)` を返す（ファイルには書かない）。"""
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, cube_db, "cube")
        common.attach_readonly(work, registry_db, "reg")
        assert_alias_is_function(work, "measurements")
        # b05 が実際に消費する grain（day/hour/instant）だけに絞る
        # （assert_alias_is_function の docstring 参照。jma_monthly の
        # 積雪3変数にある month 限定の alias 重複は射影対象外なので見ない）。
        assert_alias_is_function(work, "sensor_timeseries", grains=("day", "hour", "instant"))
        assert_alias_tuple_maps_to_single_dataset(work)
        assert_unit_raw_is_function(work)
        _materialize_lookup_tables(work)
        _materialize_projection_tables(work)
        verify_hourly_daily_rollup(work)
        out = {}
        for table, sql in _TABLE_SQL.items():
            cur = work.execute(sql)
            columns = [d[0] for d in cur.description]
            out[table] = (columns, cur.fetchall())
        assert_v1_keys_are_unique(out, _load_v1_keys(baseline_json))
        return out
    finally:
        work.close()


_CREATE_SQL = {
    "meas_daily": (
        "CREATE TABLE meas_daily (site_id TEXT, variable TEXT, d TEXT, value REAL, "
        "n_raw INTEGER, n_censored INTEGER, unit TEXT)"
    ),
    "meas_month": (
        "CREATE TABLE meas_month (site_id TEXT, variable TEXT, ym TEXT, year INTEGER, "
        "month INTEGER, n INTEGER, avg REAL, unit TEXT)"
    ),
    "meas_year": (
        "CREATE TABLE meas_year (site_id TEXT, variable TEXT, kind TEXT, year INTEGER, "
        "n INTEGER, avg REAL, min REAL, max REAL, n_censored INTEGER, unit TEXT)"
    ),
    "meas_clim": (
        "CREATE TABLE meas_clim (variable TEXT, month INTEGER, n INTEGER, avg REAL, "
        "min REAL, max REAL, unit TEXT)"
    ),
    "site_var": (
        "CREATE TABLE site_var (site_id TEXT, variable TEXT, kind TEXT, n INTEGER, "
        "y_from INTEGER, y_to INTEGER, avg REAL, unit TEXT)"
    ),
    "var_catalog": (
        "CREATE TABLE var_catalog (variable TEXT, unit TEXT, n INTEGER, n_sites INTEGER, "
        "y_from INTEGER, y_to INTEGER, n_daily INTEGER, n_annual INTEGER, n_censored INTEGER)"
    ),
    "sensor_daily": (
        "CREATE TABLE sensor_daily (site_id TEXT, datastream TEXT, d TEXT, n INTEGER, "
        "avg REAL, min REAL, max REAL, unit TEXT)"
    ),
    "rain_daily": "CREATE TABLE rain_daily (d TEXT, mm REAL, n_hours INTEGER)",
    "sensor_hour_month": (
        "CREATE TABLE sensor_hour_month (datastream TEXT, month INTEGER, hour INTEGER, "
        "n INTEGER, avg REAL, max REAL)"
    ),
}


def write_projections(projections: dict[str, tuple[list[str], list[tuple]]], out_path) -> None:
    conn = common.fresh_sqlite(out_path)
    try:
        for table, (columns, rows) in projections.items():
            conn.execute(_CREATE_SQL[table])
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube-db", default=str(DEFAULT_CUBE_DB), help="observation_agg を持つ v2.sqlite")
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--baseline-json",
        default=str(DEFAULT_BASELINE_JSON),
        help="v1 のキー列を読む derived_baseline.json（assert_v1_keys_are_unique 用）",
    )
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {args.cube_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("v1 形へ射影") as info:
        projections = build_projections(args.cube_db, registry_db, args.baseline_json)
        info["n"] = sum(len(rows) for _, rows in projections.values())

    with common.timed_step(f"{args.out} に書き出し") as info:
        write_projections(projections, args.out)
        info["n"] = sum(len(rows) for _, rows in projections.values())

    for table, (_, rows) in sorted(projections.items()):
        print(f"  {table}: {len(rows):,}行")


if __name__ == "__main__":
    main()
