#!/usr/bin/env python3
"""`observation_agg`（`data/db/v2.sqlite`、b04 が作ったキューブ）を v1 の派生
テーブル形（`meas_daily`/`meas_month`/`meas_year`/`meas_clim`/`site_var`/
`var_catalog`/`sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/
`zone_clim`/`landuse_watershed`/`landuse_change`）に射影する
（ADR-0016 Phase B「ファクトとキューブ」縦に薄い1本。センサーの縦線の設計は
「センサーの縦線 設計 v2」オーナー決定・ADR-0023・ADR-0024、ゾーンの縦線は
`docs/plans/PHASE_B_FACT_SLICE.md`（D11）・ADR-0022、土地利用の縦線（P-1b）は
`docs/plans/PHASE_B_LANDUSE.md` 参照）。

    .venv/bin/python3 scripts/b05_project_v1.py

`data/db/v1_projection.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
13テーブルを書く。列名・列順は `reports/derived_baseline.json` の記録と完全に
一致させてある（`scripts/b02_derived_compare.py --tables ...` がそのまま
突き合わせられるように）。

## ADR-0009 決定4: `observation_agg.value` は `value_zero`/`value_lod` に分かれた

v1 の13テーブルはすべて `imputation='zero'` 系列（旧 `value` 列、いまの
`value_zero`）の再現が対象。**このファイルは `value_zero` だけを読み、
`value_lod` は一度も読まない**——`value` → `value_zero` という列名の改称
そのものが「読み落とし」に対する機械保証になる（うっかり `value` を読む
コードが残っていれば `sqlite3.OperationalError: no such column` で必ず
止まる）。加えて `test_b05_ignores_value_lod_poison_test`
（`scripts/tests/test_b05_project_v1.py`）が、`value_lod` をどんな値に
書き換えても13テーブルの出力が1ビットも変わらないことを実際に確認する。

## `meas_clim`/`site_var`/`var_catalog` はキューブのセルにしない（オーナー決定）

`docs/plans/PHASE_B_FACT_SLICE.md` D10 参照（変更なし。この3テーブルは
`measurements` 由来のみで、センサーの縦線とは無関係）。

## `zone_year`/`zone_clim`（`place_relation` の最初の消費者。phase-b/zone-slice）

`docs/plans/PHASE_B_FACT_SLICE.md` D11 参照（この2テーブルも `measurements`
由来のみで、センサーの縦線とは無関係。レジストリの不変条件は
`scripts/r01_build_registry.py` 側、射影固有の前提は本ファイルの
`_assert_zone_edges_have_fraction_one` 等に分けてある——分担の理由も D11）。

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

## T4-3: 日次セルを読む箇所の `stat='mean'` 絞り込み（旧称 `cube_day`。
## b04 の C-1 でその名の一時テーブルは無くなったが、絞り込みの必要性自体は
## 変わらない）

`_MEAS_DAILY_SQL`/`_MEAS_MONTH_SQL` に `AND c.stat = 'mean'` を明示的に足した
（b04 が日次セルに `mean`/`min`/`max`/`sum` の複数行を持つようになったため。
絞らないと `meas_daily`/`meas_month` の値に min/max/sum が混ざる——既存
6テーブルの値が黙って変わる、最も疑わしい箇所。`meas_month` は現状
measurements 側の月次出典配布セルが存在しない（`measurements` の
value_grain に `'month'` が無い）ため実害は無いが、将来の事故を防ぐために
同じ絞り込みを足す）。

## T6: 毎時→日次の正しさを機械で確かめる（`verify_hourly_daily_rollup`）

`value_grain='hour'` の各系列・各日について、キューブの日次セルの件数が
v1形（L2 のラベル日割り）から期待される値と一致することを検証する（時刻帯の
9時間ずれ・日割りの誤りはこれで捕まる）。あわせて、系列ごとの全期間の
Σn・min・max がキューブの日次セルと L2 で一致することも確認する。**検証式の
正は `verify_hourly_daily_rollup` の docstring**（D-1: 同じ式をここに書き
下さない）。どちらも崩れていれば `MigrationError` で止まる（ゲートがこの
経路を直接見なくなる——`sensor_daily` の毎時分はキューブを経由しないため
——代わりの機械検証）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common, v1_projection_checks  # noqa: E402

# `PHASE_B_FACT_SLICE.md:457-459` の決定（検証関数群を別モジュールに分ける）
# で `scripts/migrate/v1_projection_checks.py` に移した検証関数群は、
# `occurrence_period`/`period` と同じ流儀で `v1_projection_checks.関数名(...)`
# のままモジュール参照で呼ぶ（/simplify 指摘: 以前はここに同名のモジュール
# 変数として再エクスポートしていたが、実体を持たない別名の分だけ経路が
# 増えるだけだった）。

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection.sqlite"
DEFAULT_BASELINE_JSON = ROOT / "reports" / "derived_baseline.json"

# B-5: `unit_lookup`/`obs_agg_keyed`/`label25_obs_keyed` の3箇所が同じ結合キー
# （`(variable_id, value_grain, obs_stat, unit_id)` を `|` で連結したもの）を
# 別々に書いていたものを1つに集約。`_alias_lookup_sql` の結合キー（`grain`/
# `stat` — variable_alias 自身の列名）はこれとは別物（列名が違う）なので、
# ここには含めない。
_AKEY_EXPR = (
    "variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' || "
    "COALESCE(unit_id, '')"
)


def _gkey_expr(prefix: str = "") -> str:
    """`year_keyed`/`day_keyed` が自己 JOIN のピボットに使う結合キー `gkey` の式
    （B-5: 2箇所で同じ式が重複していたものを1つに）。`prefix` は列参照の
    修飾子——`day_keyed` は `obs_agg_keyed` を別名 `c` で JOIN するため列名が
    曖昧になり、`"c."` を渡す必要がある（`year_keyed` は単一テーブルからの
    `SELECT *` なので不要、既定の `""` のまま）。
    """
    cols = ("place_id", "akey", "period_start", "input_grain")
    return " || '|' || ".join(f"{prefix}{c}" for c in cols)


# B-6: `day_keyed`（sensor_daily (a)。`input_grain` で絞る）と
# `label25_obs_keyed`（sensor_daily (b)・rain_daily・sensor_hour_month・T6。
# `value_grain` で絞る）は別々の列・別々の範囲を消費するが、どちらも
# `build_projections` の `assert_alias_is_function(work, "sensor_timeseries",
# grains=...)` が検証すべき「b05 が実際に読む grain」の一部を成す。以前は
# 3箇所（この2つの SQL の WHERE 句と assert の `grains=` タプル）が手書きの
# タプルとして独立に書かれていた。ここに1度だけ宣言し、SQL の WHERE も
# assert の `grains=` もここから作る（jma_monthly の積雪 alias の表記ゆれ
# （`grain='month'`）を射影が引きずらない、という今の意図は変えない——
# 'month' はどちらの集合にも含めない）。
_DAY_KEYED_INPUT_GRAINS = ("day", "instant")
_LABEL25_VALUE_GRAINS = ("hour", "instant")
_SENSOR_ALIAS_GRAINS = tuple(sorted(set(_DAY_KEYED_INPUT_GRAINS) | set(_LABEL25_VALUE_GRAINS)))


def _sql_in_clause(values: tuple[str, ...]) -> str:
    """`values`（このモジュール内の固定タプル。ユーザー入力ではない）を SQL の
    `IN (...)` に埋め込む文字列にする（`scripts/b04_build_cube.py` の
    `_ZERO_IMPUTED_IN_CLAUSE` と同じ考え方。バインドパラメータにしない）。
    """
    return ", ".join(f"'{v}'" for v in values)


# `scripts/migrate/common.raise_on_group_by_duplicates` への薄いエイリアス
# （/simplify 指摘2: `scripts/b08_project_occurrence_v1.py` の
# `place_mesh_lookup` の単射検証と実装がほぼ一字一句同じだったため集約した。
# このモジュール内の6箇所の呼び出しは `work`/`_raise_on_group_by_duplicates`
# という名前のまま変わらない）。
_raise_on_group_by_duplicates = common.raise_on_group_by_duplicates


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


def _place_lookup_sql(source_id: str) -> str:
    """`place_id -> v1 の外部キー`の逆引き元 SQL（`place_source_ref.source_id`
    で絞る）。`place_lookup`（`source_id='sites.site_id'`）と
    `watershed_place_lookup`（`source_id='watershed_meta.watershed_id'`、
    P-1b）の両方をこの関数で作る——以前は後者が前者のブロックをほぼ丸写し
    していたものを、`_alias_lookup_sql`/`_unit_lookup_sql` と同じ「引数だけ
    違う SQL 生成関数」という既存の流儀に揃えた（/simplify 指摘3）。
    """
    return f"SELECT place_id, external_key FROM reg.place_source_ref WHERE source_id = '{source_id}'"


def _unit_lookup_sql(source_table: str) -> str:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` の逆引き元
    SQL（`source_table`——`observation.source_table` の値——で絞る）。
    `observation_agg`（ADR-0011 のキューブ）は `unit_raw` を持たないため、
    `cube.observation`（キューブではなくファクト）から引く。
    """
    return f"""
    SELECT variable_id, value_grain, obs_stat, unit_id,
           {_AKEY_EXPR} AS akey,
           MAX(unit_raw) AS unit_raw
    FROM cube.observation
    WHERE source_table = '{source_table}'
    GROUP BY variable_id, value_grain, obs_stat, unit_id
    """


# `observation_agg` 側にも同じ形の結合キーを持つ VIEW を張る（`c.akey` として参照）。
_OBS_AGG_KEYED_VIEW_SQL = f"""
CREATE TEMP VIEW obs_agg_keyed AS
SELECT *,
       {_AKEY_EXPR} AS akey
FROM cube.observation_agg
"""

# ---------------------------------------------------------------------------
# measurements 由来 6テーブル（変更点: meas_daily/meas_month に stat='mean' を追加）
# ---------------------------------------------------------------------------

# ADR-0009 決定4: `observation_agg` の `value` は `value_zero`/`value_lod` の
# 2列に分かれた。v1 の全13テーブルは `imputation='zero'` の系列（旧 `value`
# 列）だけを再現する対象なので、ここでは `value_zero` だけを読む
# （`value_lod` は一度も読まない——毒入れテスト
# `test_b05_ignores_value_lod_poison_test` がこれを保証する）。
_MEAS_DAILY_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable, c.period_start AS d,
       c.value_zero AS value, c.n AS n_raw, c.n_censored AS n_censored, ul.unit_raw AS unit
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
       c.n AS n, c.value_zero AS avg, ul.unit_raw AS unit
FROM obs_agg_keyed c
JOIN place_lookup psr ON psr.place_id = c.place_id
JOIN alias_lookup al ON al.akey = c.akey
JOIN unit_lookup ul ON ul.akey = c.akey
WHERE c.grain = 'month' AND c.stat = 'mean'
"""

# B-5: `meas_year` と `sensor_daily`（キューブ由来の (a) 側）はどちらも同じ形
# ——`stat IN ('mean','min','max')` の3行を `gkey` で自己 JOIN して1行に
# ピボットし、`alias_lookup`/`unit_lookup`/`place_lookup` で v1 の名前に逆引き
# する——で、`table`（`year_keyed`/`day_keyed`）・`alias_lookup`/`unit_lookup`
# のテーブル名・`al.alias` の出力列名・テーブル固有の追加列だけが違う。
# `extra_head`（`al.alias AS ...` の直後、`m.n` の前に足す列）・`extra_tail`
# （`mx.value_zero AS max` の直後、`unit` の前に足す列）で差分を表す。
def _pivot_mean_min_max_sql(
    table: str, alias_lookup: str, unit_lookup: str, alias_column: str,
    extra_head: str = "", extra_tail: str = "",
) -> str:
    head = f"{extra_head}\n       " if extra_head else ""
    tail = f"{extra_tail}, " if extra_tail else ""
    return f"""
    SELECT psr.external_key AS site_id, al.alias AS {alias_column},
           {head}m.n AS n, m.value_zero AS avg, mn.value_zero AS min, mx.value_zero AS max,
           {tail}ul.unit_raw AS unit
    FROM {table} m
    JOIN {table} mn ON mn.gkey = m.gkey AND mn.stat = 'min'
    JOIN {table} mx ON mx.gkey = m.gkey AND mx.stat = 'max'
    JOIN {unit_lookup} ul ON ul.akey = m.akey
    JOIN place_lookup psr ON psr.place_id = m.place_id
    JOIN {alias_lookup} al ON al.akey = m.akey
    WHERE m.stat = 'mean'
    """


# 年次セルは stat ごとに別行（b04）。同じグループを1行にまとめるための結合キー
# （`year_keyed`。`_materialize_lookup_tables` 参照）。
_MEAS_YEAR_SQL = _pivot_mean_min_max_sql(
    "year_keyed", "alias_lookup", "unit_lookup", "variable",
    extra_head=(
        "CASE WHEN m.input_grain = 'day' THEN 'daily' ELSE 'annual' END AS kind,\n"
        "       CAST(substr(m.period_start, 1, 4) AS INT) AS year,"
    ),
    extra_tail="m.n_censored AS n_censored",
)

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
# ゾーン別2テーブル（`place_relation` の最初の消費者。D11参照。measurements
# 由来の meas_year/meas_month をそのままゾーンに束ねるだけで、キューブは
# 経由しない——D10/D11 と同じ理由）
# ---------------------------------------------------------------------------

# 地点→ゾーンの対応（D11参照）。実装メモ:
# - `zone_raw`（原文字列）と `zone_place_id`（`pr.parent_id`）は検証専用の列
#   ——外側の SELECT（`_ZONE_YEAR_SQL` 等）が読むのは `zone`/`site_id` だけ。
# - `place_lookup` に依存する（`psr` の JOIN 元）ため、`_materialize_lookup_
#   tables` の中で `place_lookup` の一意性検証（UNIQUE INDEX）の後に実行すること。
_SITE_ZONE_LOOKUP_SQL = """
CREATE TEMP TABLE site_zone_lookup AS
SELECT psr.external_key AS site_id,
       pr.parent_id AS zone_place_id,
       zref.external_key AS zone_raw,
       CAST(zref.external_key AS INT) AS zone,
       pr.fraction AS fraction
FROM reg.place_relation pr
JOIN place_lookup psr ON psr.place_id = pr.child_id
JOIN reg.place_source_ref zref
  ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
WHERE pr.relation = 'within'
"""

_ZONE_YEAR_SQL = """
SELECT sz.zone AS zone, y.variable AS variable, y.kind AS kind, y.year AS year,
       COUNT(DISTINCT y.site_id) AS n_sites, SUM(y.n) AS n,
       AVG(y.avg) AS avg, MAX(y.unit) AS unit
FROM meas_year y
JOIN site_zone_lookup sz ON sz.site_id = y.site_id
GROUP BY sz.zone, y.variable, y.kind, y.year
"""

_ZONE_CLIM_SQL = """
SELECT sz.zone AS zone, m.variable AS variable, m.month AS month,
       COUNT(DISTINCT m.site_id) AS n_sites, SUM(m.n) AS n,
       AVG(m.avg) AS avg, MAX(m.unit) AS unit
FROM meas_month m
JOIN site_zone_lookup sz ON sz.site_id = m.site_id
GROUP BY sz.zone, m.variable, m.month
"""

# ---------------------------------------------------------------------------
# 土地利用2テーブル（P-1b、docs/plans/PHASE_B_LANDUSE.md）。observation の
# 出典配布の年次セル（b04 は無変更。ADR-0011「事前計算は place_kind IN
# {site,watershed,mesh3}」の watershed に既に該当し、既存の年次出典配布の
# 経路（`_year_source_stats_sql`/`_year_source_expand_sql`）をそのまま通る）
# から作る。`observation`/`observation_agg` の既存の行・セルには一切触れない
# （新しい variable_id・新しい place_kind='watershed' のセルが増えるだけ）。
# ---------------------------------------------------------------------------

# b03 の `LANDUSE_SOURCE_ID`（`scripts/b03_build_observation.py`）と同じ文字列。
# b05 は b03 の Python モジュールに依存しない（v2.sqlite/registry.sqlite という
# ファイルだけを読む設計）ため、ここでも定数として持つ（2箇所に文字列リテラルを
# 散らさないための唯一の置き場）。
_LANDUSE_SOURCE_ID = "nlni_l03b_landuse_by_watershed"
_LANDUSE_DATASET_PREFIX = f"{_LANDUSE_SOURCE_ID}@"


def _landuse_dataset(year: str) -> str:
    return f"{_LANDUSE_DATASET_PREFIX}{year}"


def _discover_landuse_years(work: sqlite3.Connection) -> list[str]:
    """`reg.variable_alias.dataset` の `nlni_l03b_landuse_by_watershed@<年>`
    という接頭辞から、実際に登録されている年版を導出する（コードレビュー
    指摘1: 年版のタプルを直書きすると、3つ目の版を variable_alias.csv に
    足したときに b03 は取り込むのに b05 の射影からは黙って落ちる）。

    `substr(dataset, 1, ?) = ?` で前方一致を取る（`LIKE` は `_` を1文字
    ワイルドカードとして解釈してしまい、`nlni_l03b_landuse_by_watershed` の
    アンダースコアが誤って任意の1文字にマッチしうるため使わない。
    コードレビュー指摘7）。

    1件も見つからなければ空リストを返す（エラーにしない）——本物の
    `registry.sqlite` には常に土地利用の alias が登録されているはずだが、
    土地利用を検証しない既存のフィクスチャ（`measurements`/`sensor_timeseries`
    だけの最小 `variable_alias`）は landuse の行を持たない。空リストなら
    `_landuse_watershed_sql([])` が0行の `landuse_watershed`（正しい列だけの
    空テーブル）を作り、`landuse_watershed`/`landuse_change` は空のまま
    通る——zone（`place_relation` が空でも `zone_year`/`zone_clim` が
    空のまま通る、D11 と同じ考え方）。
    """
    prefix_len = len(_LANDUSE_DATASET_PREFIX)
    rows = work.execute(
        "SELECT DISTINCT substr(dataset, ?) AS year_suffix "
        "FROM reg.variable_alias WHERE substr(dataset, 1, ?) = ? "
        "ORDER BY year_suffix",
        (prefix_len + 1, prefix_len, _LANDUSE_DATASET_PREFIX),
    ).fetchall()
    return [r[0] for r in rows]


# 区分の面積（area_km2）とセル数（n_cells）は、CSVの1行から作られた別々の
# variable（P-1b オーナー決定1）。alias 文字列は `f"{landuse_code_raw}:area_km2"`/
# `f"{landuse_code_raw}:n_cells"`（`scripts/b03_build_observation.py` の
# `_ingest_landuse` と同じ形）なので、`substr(alias, 1, instr(alias, ':') - 1)`
# で元の landuse_code_raw を、`substr(alias, instr(alias, ':') + 1)` で
# 指標名（`'area_km2'`/`'n_cells'`）を復元できる——CSVの `landuse_code_raw` を
# レジストリの別テーブルに複製せず、alias 文字列自身から引き戻す。
# 指標名の一致は `LIKE '%:n_cells'` ではなく `substr(...) = 'n_cells'` の
# **完全一致**にしてある（`n_cells` のアンダースコアが `LIKE` の1文字
# ワイルドカードと衝突するため。コードレビュー指摘7）。
def _landuse_watershed_year_sql(year: str) -> str:
    lookup = f"landuse_alias_lookup_{year}"
    return f"""
    SELECT wpl.external_key AS watershed_id, {year} AS year,
           substr(aal.alias, 1, instr(aal.alias, ':') - 1) AS landuse_code,
           v.name_ja AS landuse_name,
           CAST(ncell.value_zero AS INTEGER) AS n_cells,
           area.value_zero AS area_km2
    FROM obs_agg_keyed area
    JOIN {lookup} aal
      ON aal.akey = area.akey
     AND substr(aal.alias, instr(aal.alias, ':') + 1) = 'area_km2'
    JOIN reg.variable v ON v.variable_id = area.variable_id
    JOIN watershed_place_lookup wpl ON wpl.place_id = area.place_id
    JOIN obs_agg_keyed ncell
      ON ncell.place_id = area.place_id
     AND ncell.period_start = area.period_start
     AND ncell.grain = area.grain AND ncell.stat = area.stat
    JOIN {lookup} nal
      ON nal.akey = ncell.akey
     AND substr(nal.alias, instr(nal.alias, ':') + 1) = 'n_cells'
     AND substr(nal.alias, 1, instr(nal.alias, ':') - 1) = substr(aal.alias, 1, instr(aal.alias, ':') - 1)
    WHERE area.grain = 'year' AND area.stat = 'mean' AND area.place_kind = 'watershed'
      AND area.period_start = '{year}-01-01'
    """


# `area.period_start = '{year}-01-01'` の絞り込みが無いと、10区分は2006/2016
# 両方の年で同じ variable_id を共有する（P-1b オーナー決定2）ため、
# `landuse_alias_lookup_2006` が2016年のセルにも（akey が同じという理由だけで）
# 一致してしまい、2016年の面積に2006年の landuse_code を誤って付けてしまう
# （値そのものは変わらないが、行が指す年と landuse_code の対応が壊れる）。
def _landuse_watershed_sql(years: list[str]) -> str:
    if not years:
        # 土地利用の alias が1件も無いフィクスチャ用（`_discover_landuse_years`
        # 参照）。列だけ揃った0行の SELECT にする（`UNION ALL` に空リストを
        # 渡すと SQL 構文として空文字列になってしまうため）。
        return (
            "SELECT NULL AS watershed_id, NULL AS year, NULL AS landuse_code, "
            "NULL AS landuse_name, NULL AS n_cells, NULL AS area_km2 WHERE 0"
        )
    return "\nUNION ALL\n".join(_landuse_watershed_year_sql(year) for year in years)

# v1（`web/scripts/build-geo.mjs:100-110`）と同じ SQL（SUM(CASE...) を
# landuse_name でグループ化）。同じ日本語名を持つ10区分は年をまたいで同じ
# variable_id を共有しているため（P-1b オーナー決定2）、v1 と同じ GROUP BY で
# 同じ行の集合になる。`幹線交通用地`（2006のみ）・`道路`/`鉄道`（2016のみ）は
# 年をまたがない別の variable_id のままなので、v1 と同じく「全減」「全増」に
# なる（registry/caveat.yaml の definition_change caveat 参照）。
_LANDUSE_CHANGE_SQL = """
SELECT watershed_id, landuse_name,
       SUM(CASE WHEN year = 2006 THEN area_km2 ELSE 0 END) AS km2_2006,
       SUM(CASE WHEN year = 2016 THEN area_km2 ELSE 0 END) AS km2_2016,
       SUM(CASE WHEN year = 2016 THEN area_km2 ELSE 0 END)
         - SUM(CASE WHEN year = 2006 THEN area_km2 ELSE 0 END) AS delta_km2
FROM landuse_watershed
GROUP BY watershed_id, landuse_name
"""

# ---------------------------------------------------------------------------
# sensor_timeseries 由来 3テーブル（T5）
# ---------------------------------------------------------------------------

# (a) value_grain IN ('day', 'instant') はキューブの日次セルから（mean/min/max
# をピボット。`_pivot_mean_min_max_sql`——B-5）。`day_keyed` は
# `_materialize_lookup_tables` が sensor_alias_lookup の akey に絞って作る
# （measurements の日次セル約141万行を無駄にスキャンしない）。
_SENSOR_DAILY_FROM_CUBE_SQL = _pivot_mean_min_max_sql(
    "day_keyed", "sensor_alias_lookup", "sensor_unit_lookup", "datastream",
    extra_head="m.period_start AS d,",
)

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
    "meas_month": "SELECT * FROM meas_month",
    "meas_year": "SELECT * FROM meas_year",
    "meas_clim": _MEAS_CLIM_SQL,
    "site_var": _SITE_VAR_SQL,
    "var_catalog": _VAR_CATALOG_SQL,
    "sensor_daily": _SENSOR_DAILY_SQL,
    "rain_daily": _RAIN_DAILY_SQL,
    "sensor_hour_month": _SENSOR_HOUR_MONTH_SQL,
    "zone_year": _ZONE_YEAR_SQL,
    "zone_clim": _ZONE_CLIM_SQL,
    "landuse_watershed": "SELECT * FROM landuse_watershed",
    "landuse_change": _LANDUSE_CHANGE_SQL,
}


def _year_keyed_sql() -> str:
    return f"""
    CREATE TEMP TABLE year_keyed AS
    SELECT *,
           {_gkey_expr()} AS gkey
    FROM obs_agg_keyed
    WHERE grain IN ('year', 'fiscal_year')
    """


# sensor_daily (a) 用。sensor_alias_lookup の akey に絞って作る——measurements
# の日次セル（約141万行）を無駄にスキャンしない（`obs_agg_keyed` を JOIN の
# 時点で sensor 側の akey だけに絞り込む）。読む input_grain の範囲は
# `_DAY_KEYED_INPUT_GRAINS`（B-6: SQL の WHERE と `assert_alias_is_function` の
# `grains=` の両方をこの1つの定数から作る）。
def _day_keyed_sql() -> str:
    return f"""
    CREATE TEMP TABLE day_keyed AS
    SELECT c.*, {_gkey_expr("c.")} AS gkey
    FROM obs_agg_keyed c
    JOIN sensor_alias_lookup al ON al.akey = c.akey
    WHERE c.grain = 'day' AND c.input_grain IN ({_sql_in_clause(_DAY_KEYED_INPUT_GRAINS)})
    """


# sensor_daily (b)・rain_daily・sensor_hour_month で共有する、25桁ラベル
# （B-6: `_LABEL25_VALUE_GRAINS`）だけの一時テーブル。v1
# （sensor_daily/rain_daily/sensor_hour_month）はどれもこの範囲の observation
# をキューブを経由せず直接集計する（T5）。
def _label25_obs_keyed_sql() -> str:
    return f"""
    CREATE TEMP TABLE label25_obs_keyed AS
    SELECT *,
           {_AKEY_EXPR} AS akey
    FROM cube.observation
    WHERE value_grain IN ({_sql_in_clause(_LABEL25_VALUE_GRAINS)})
    """


def _materialize_lookup_tables(work: sqlite3.Connection, landuse_years: list[str]) -> None:
    """自動インデックスの効かない `IS`（NULL-safe）JOIN を、実体化した一時
    テーブル＋インデックスの通常の等値 JOIN に置き換える。`measurements`/
    `sensor_timeseries` の両方ぶんの逆引きテーブルと、`place_lookup` の
    直後に地点→ゾーンの対応（`site_zone_lookup`。`zone_year`/`zone_clim` が
    使う。ADR-0022 決定2の最初の消費者）をここで作る。

    `landuse_years`（`_discover_landuse_years()` が導出した年版の一覧。
    コードレビュー指摘1）ごとに土地利用の alias 逆引きテーブルを作る。
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

    work.execute(_year_keyed_sql())
    work.execute("CREATE INDEX year_keyed_gkey_stat ON year_keyed (gkey, stat)")

    work.execute(_day_keyed_sql())
    work.execute("CREATE INDEX day_keyed_gkey_stat ON day_keyed (gkey, stat)")

    work.execute(_label25_obs_keyed_sql())
    work.execute("CREATE INDEX label25_obs_keyed_akey ON label25_obs_keyed (akey)")

    work.execute(f"CREATE TEMP TABLE place_lookup AS {_place_lookup_sql('sites.site_id')}")
    _raise_on_group_by_duplicates(
        work,
        "SELECT place_id, COUNT(*) AS n FROM place_lookup GROUP BY place_id HAVING n > 1 LIMIT 5",
        (),
        lambda dup: (
            "place_source_ref（source_id='sites.site_id'）が place_id について単射でない"
            f"（同じ place_id に複数の external_key（site_id）が対応している。例: {dup}）。"
            "キューブのキー place_id から v1 の site_id を一意に復元できないため、射影が"
            "決まらない。place_source_ref 側の重複を解消してから再実行すること。"
        ),
    )
    work.execute("CREATE UNIQUE INDEX place_lookup_place_id ON place_lookup (place_id)")

    # 地点→ゾーン（site_zone_lookup。`place_lookup` に依存するため、この直後で
    # 作る）。検証は射影固有の前提だけ（D11参照。レジストリの不変条件は
    # scripts/r01_build_registry.py 側に移設済み）。
    v1_projection_checks._assert_place_relation_table_exists(work)
    work.execute(_SITE_ZONE_LOOKUP_SQL)
    v1_projection_checks._assert_zone_numbers_do_not_collide_across_zone_places(work)
    v1_projection_checks._assert_zone_edges_have_fraction_one(work)
    v1_projection_checks._assert_site_maps_to_at_most_one_zone(work)
    work.execute("CREATE UNIQUE INDEX site_zone_lookup_site_id ON site_zone_lookup (site_id)")

    # 土地利用（P-1b）。watershed の place_id -> v1 の watershed_id
    # （`_place_lookup_sql` は `place_lookup` と同じ関数——`source_id` が違うだけ）。
    work.execute(
        f"CREATE TEMP TABLE watershed_place_lookup AS "
        f"{_place_lookup_sql('watershed_meta.watershed_id')}"
    )
    _raise_on_group_by_duplicates(
        work,
        "SELECT place_id, COUNT(*) AS n FROM watershed_place_lookup GROUP BY place_id HAVING n > 1 LIMIT 5",
        (),
        lambda dup: (
            "place_source_ref（source_id='watershed_meta.watershed_id'）が place_id に"
            f"ついて単射でない（例: {dup}）。landuse_watershed の射影が決まらない。"
        ),
    )
    work.execute("CREATE UNIQUE INDEX watershed_place_lookup_place_id ON watershed_place_lookup (place_id)")

    # 版付き dataset（`nlni_l03b_landuse_by_watershed@<year>`）ごとの alias 逆引き
    # （`_alias_lookup_sql` は既存の measurements/sensor_timeseries と同じ関数を
    # 再利用する——dataset が違うだけ）。
    for year in landuse_years:
        lookup = f"landuse_alias_lookup_{year}"
        work.execute(f"CREATE TEMP TABLE {lookup} AS {_alias_lookup_sql(_landuse_dataset(year))}")
        work.execute(f"CREATE UNIQUE INDEX {lookup}_akey ON {lookup} (akey)")


def _materialize_projection_tables(work: sqlite3.Connection, landuse_years: list[str]) -> None:
    """逆引き済みの `meas_daily`/`meas_month`/`meas_year` をそれぞれ1回だけ
    一時テーブルに実体化する（`meas_clim`/`site_var`/`var_catalog` は
    `meas_daily`/`meas_year` から、`zone_year`/`zone_clim` は
    `meas_year`/`meas_month` からそれぞれ読む。`measurements` 専用で
    `sensor_timeseries` とは無関係——変更なし）。
    """
    work.execute(f"CREATE TEMP TABLE meas_daily AS {_MEAS_DAILY_SQL}")
    work.execute(f"CREATE TEMP TABLE meas_month AS {_MEAS_MONTH_SQL}")
    work.execute(f"CREATE TEMP TABLE meas_year AS {_MEAS_YEAR_SQL}")
    # landuse_change（`_LANDUSE_CHANGE_SQL`）が読むため実体化する（P-1b）。
    work.execute(f"CREATE TEMP TABLE landuse_watershed AS {_landuse_watershed_sql(landuse_years)}")


def _load_v1_keys(baseline_json_path) -> dict[str, list[str]]:
    """`v1_projection_checks.load_v1_keys` の薄いラッパ（テーブル名の集合を
    `_TABLE_SQL` から渡す）。既存の呼び出し側・テスト（`b05._load_v1_keys(path)`）
    はこのシグネチャのまま動く（PHASE_B_FACT_SLICE.md:457-459、検証関数群の
    分割）。
    """
    return v1_projection_checks.load_v1_keys(baseline_json_path, _TABLE_SQL)


def build_projections(
    cube_db, registry_db, baseline_json=DEFAULT_BASELINE_JSON, *,
    verified_fingerprints_out: dict[str, str] | None = None,
) -> dict[str, list[tuple]]:
    """13テーブルぶんの `(columns, rows)` を返す（ファイルには書かない）。

    `meas_clim`/`site_var`/`var_catalog`/`zone_year`/`zone_clim`（`meas_year`/
    `meas_month` からの再集計）と `sensor_daily`/`rain_daily`/
    `sensor_hour_month`（L2 の直接集計）が `AVG()`/`SUM()` を使うため、
    先頭で `common.require_sqlite_version()` を呼ぶ
    （`scripts/migrate/common.py`。b04・b10 と共有するガード）。

    `verified_fingerprints_out`（省略可、`main()` が渡す）: 渡すと、この関数が
    下の (a) チェックで実際に検証した `observation`/`observation_agg` の
    **その時点の**指紋を書き込む。呼び出し側はこれを `write_projections()`
    にそのまま渡す（/code-review 指摘の根本対応: 以前は `write_projections`
    が `cube_db` を**改めて開いて**指紋を読み直していたため、この関数の
    検証と `write_projections` の書き込みの間に b04 が `cube_db` を作り直して
    コミットすると、「検証した時点の値」ではなく「今読み直した新しい値」が
    系譜として記録され、実際にはその指紋が指す内容とは違う〔古い〕データから
    作った射影に、新しい指紋を系譜として紐付けてしまう——b11 の (b) 検査を
    すり抜ける。検証した値をそのまま運ぶことでこの穴を塞ぐ）。この関数の
    戻り値（`projections` dict）は既存の呼び出し・テスト〔27箇所〕と
    互換のまま変えない——追加情報はこのキーワード専用引数でだけ渡す。
    """
    common.require_sqlite_version()
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, cube_db, "cube")
        common.attach_readonly(work, registry_db, "reg")
        with common.track_reads(work) as reads:
            # 段階間の指紋（Issue #37 #1）: b04 が最後に記録した observation_agg の
            # 指紋と、今 ATTACH した cube_db の内容が一致することを、射影を始める
            # 前に確認する。`upstream_schemas={"observation": "cube"}`
            # （コードレビュー指摘: (a) の自己一致だけでは「observation_agg 自身は
            # 無傷だが、b03 だけ作り直されて b04 が再実行されていない」壊れ方を
            # 検出できない。observation_agg が記録した系譜〔消費した observation
            # の指紋〕と、observation 自身が今記録している自己指紋を突き合わせる
            # (b) を有効にする——observation は observation_agg と同じ v2.sqlite
            # 〔ここでは "cube" 別名〕にあるので、上流の生データを読み直さず安く
            # 確認できる）。戻り値（検証した時点の自己指紋）を捕まえておく
            # ——`write_projections` がこれとは別に読み直さないようにするため。
            agg_fingerprint = common.assert_stage_fingerprint_fresh(
                work, "observation_agg", schema="cube",
                rebuild_hint="scripts/b04_build_cube.py を再実行すること。",
                upstream_schemas={"observation": "cube"},
            )
            # 段階間の指紋（Issue #37 #1。/code-review 指摘の穴埋め）: b05 は
            # `observation_agg` だけでなく `cube.observation` 自体も直接読む
            # （`_unit_lookup_sql`——meas_daily/meas_month/meas_year 等の unit_raw
            # 逆引き——と `_label25_obs_keyed_sql`——sensor_daily/rain_daily/
            # sensor_hour_month が使う `label25_obs_keyed`）。上の
            # `observation_agg` の (b) は「`observation_agg` が消費した時点の
            # observation の指紋」と「observation 自身の今の自己申告」を比べる
            # だけで、**observation 自身の現在のバイト列**は見ていない
            # （b03 の `staged_table` の差し替えと `record_stage_fingerprint`
            # が同じトランザクションになった今も、原理上は別の経路で
            # `observation` が直接改変される可能性が残るため、b05 が実際に
            # 読む対象には独立した (a) を掛ける）。`observation` は基底テーブル
            # （系譜を持たない）なので `upstream_schemas` は渡さない。
            obs_fingerprint = common.assert_stage_fingerprint_fresh(
                work, "observation", schema="cube",
                rebuild_hint="scripts/b03_build_observation.py を再実行すること。",
            )
            if verified_fingerprints_out is not None:
                verified_fingerprints_out["observation_agg"] = agg_fingerprint
                verified_fingerprints_out["observation"] = obs_fingerprint
            v1_projection_checks.assert_alias_is_function(work, "measurements")
            # b05 が実際に消費する grain（B-6: `_SENSOR_ALIAS_GRAINS`。
            # day_keyed の input_grain 範囲と label25_obs_keyed の value_grain
            # 範囲を合わせたもの）だけに絞る（assert_alias_is_function の
            # docstring 参照。jma_monthly の積雪3変数にある month 限定の alias
            # 重複は射影対象外なので見ない）。
            v1_projection_checks.assert_alias_is_function(work, "sensor_timeseries", grains=_SENSOR_ALIAS_GRAINS)
            # 土地利用（P-1b）: 版付き dataset（年）ごとに関数性を検証する
            # （`assert_alias_is_function` は dataset を1つ受け取る既存の関数を
            # そのまま再利用——年ごとに独立して「区分コード -> variable_id」が
            # 一意であることを確認する）。年の一覧はレジストリから動的に導出する
            # （コードレビュー指摘1。`_LANDUSE_YEARS` の直書きをやめた）。
            landuse_years = _discover_landuse_years(work)
            for year in landuse_years:
                v1_projection_checks.assert_alias_is_function(work, _landuse_dataset(year))
            v1_projection_checks.assert_alias_tuple_maps_to_single_dataset(work)
            v1_projection_checks.assert_unit_raw_is_function(work)
            # ゾーン（place_relation）の射影固有の検証は _materialize_lookup_tables
            # の中、site_zone_lookup を実体化した直後で行う（D11参照。レジストリの
            # 不変条件は r01 側で保証済み）。
            _materialize_lookup_tables(work, landuse_years)
            _materialize_projection_tables(work, landuse_years)
            v1_projection_checks.verify_hourly_daily_rollup(work)
            out = {}
            for table, sql in _TABLE_SQL.items():
                cur = work.execute(sql)
                columns = [d[0] for d in cur.description]
                out[table] = (columns, cur.fetchall())
            v1_projection_checks.assert_v1_keys_are_unique(out, _load_v1_keys(baseline_json))
            # 読み取りの機械監査（Issue #37 #1、Tier 1。/simplify 指摘A）:
            # この関数が実際に ATTACH 先（cube/reg）から読んだ表のうち、
            # 指紋機構の対象（reg は registry_build という別機構を持つため
            # 自動的に対象外）が、上の2つの `assert_stage_fingerprint_fresh`
            # で検証した表（`declared`）に含まれることを確認する——新しい
            # JOIN・SELECT を足したのに検証を足し忘れた見落としを機械的に
            # 検出する。
            common.assert_all_reads_verified(
                work, reads, {"observation", "observation_agg"},
                context="b05_project_v1.build_projections",
            )
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
    "zone_year": (
        "CREATE TABLE zone_year (zone INTEGER, variable TEXT, kind TEXT, year INTEGER, "
        "n_sites INTEGER, n INTEGER, avg REAL, unit TEXT)"
    ),
    "zone_clim": (
        "CREATE TABLE zone_clim (zone INTEGER, variable TEXT, month INTEGER, "
        "n_sites INTEGER, n INTEGER, avg REAL, unit TEXT)"
    ),
    "landuse_watershed": (
        "CREATE TABLE landuse_watershed (watershed_id TEXT, year INTEGER, landuse_code TEXT, "
        "landuse_name TEXT, n_cells INTEGER, area_km2 REAL)"
    ),
    # km2_2006/km2_2016/delta_km2 は型を宣言しない（コードレビュー指摘5）。
    # v1（`web/scripts/build-geo.mjs`）は `CREATE TABLE landuse_change AS
    # SELECT ...` という CTAS で、集計式の列には型が宣言されない
    # （`reports/derived_baseline.json` の該当3列も `type: ""`）。
    # `SUM(CASE WHEN year=2006 THEN area_km2 ELSE 0 END)` は、該当年の行が
    # 1件も無いグループでは全項が整数リテラル `0` になり、SQLite の SUM()
    # は整数だけを足した結果を INTEGER の 0 で返す——型を REAL と宣言すると
    # INSERT 時に REAL へ強制変換されてしまい、v1 の storage class
    # （INTEGER 0 のままの行がある）と食い違う。型を宣言しなければ、
    # SELECT が計算した storage class（INTEGER か REAL か）がそのまま
    # 保持される。数値としての値は REAL 宣言でも型無し宣言でも変わらない
    # ——ここで直すのは storage class（`typeof()`）の一致だけ。
    "landuse_change": (
        "CREATE TABLE landuse_change (watershed_id TEXT, landuse_name TEXT, "
        "km2_2006, km2_2016, delta_km2)"
    ),
}



# `landuse_watershed`/`landuse_change`（P-1b）は `cube.observation_agg`
# （`obs_agg_keyed`）だけから作る——`cube.observation` を直接読む
# `_unit_lookup_sql`/`_label25_obs_keyed_sql` はどちらも通らない（`unit`
# 列自体を持たない。CLAUDE.md の CREATE 文参照）。残り11テーブルは
# `unit_lookup`/`sensor_unit_lookup`（`_unit_lookup_sql` 経由）または
# `label25_obs_keyed`（`_label25_obs_keyed_sql` 経由）のどちらかを介して
# `cube.observation` の内容に依存するため、系譜に `observation` も含める
# （/code-review 指摘: 直接読んでいるのに inputs に入っていなかった穴）。
_TABLES_WITHOUT_OBSERVATION_DEPENDENCY = frozenset({"landuse_watershed", "landuse_change"})


def write_projections(
    projections: dict[str, tuple[list[str], list[tuple]]], out_path, *,
    verified_fingerprints: dict[str, str] | None = None,
) -> None:
    """13テーブルを書き、それぞれの指紋を記録する（Issue #37 #1）。

    `verified_fingerprints`（`build_projections()` の
    `verified_fingerprints_out` で得た、`observation`/`observation_agg` の
    **検証した時点の**自己指紋）を渡すと、13テーブルの系譜に記録する——
    b11 が `site_var`/`landuse_watershed` を読む前に「今の observation_agg
    （さらにその系譜を辿って observation）から作られたものか」を確かめられる
    ようにするため（コードレビュー指摘: 系譜が無いと、b04 は再実行された
    のに b05 が再実行されていない壊れ方を b11 が検出できない）。
    `observation` は `landuse_watershed`/`landuse_change` 以外の11テーブルの
    系譜にだけ加える（`_TABLES_WITHOUT_OBSERVATION_DEPENDENCY` 参照——
    この2つは `observation_agg` だけから作るため）。省略した場合は系譜を
    記録しない（`build_projections()` を経由しない単体呼び出し用——`main()`
    は常に渡す）。

    **`cube_db` を受け取って改めて開き、指紋を読み直すことはしない**
    （/code-review 指摘の根本対応。以前はここで `cube_db` を再度 ATTACH して
    `read_recorded_fingerprint` していたため、`build_projections()` の (a)
    検証と、ここでの読み直しの間に b04 が `cube_db` を作り直してコミットする
    と、「検証した時点の値」ではなく「今読み直した新しい値」を系譜に記録
    してしまい、実際には古い内容から作った射影に新しい指紋を紐付ける
    ——b11 の (b) 検査をすり抜ける穴になっていた。呼び出し側
    〔`build_projections()`〕が検証した値をそのまま渡すことでこの穴を塞ぐ）。
    """
    agg_fingerprint = (verified_fingerprints or {}).get("observation_agg")
    obs_fingerprint = (verified_fingerprints or {}).get("observation")
    conn = common.fresh_sqlite(out_path)
    try:
        for table, (columns, rows) in projections.items():
            conn.execute(_CREATE_SQL[table])
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
        # 段階間の指紋（Issue #37 #1）: 全段の出力に指紋を持たせる方針どおり、
        # 13テーブル全てに記録する（b11 が site_var/landuse_watershed を読む前に
        # 検証する。/simplify 指摘: ループ本体の分岐を無くし、表ごとの系譜を
        # 先に1つの dict にまとめてから `record_stage_fingerprints` に渡す）。
        without_obs = {"observation_agg": agg_fingerprint} if agg_fingerprint else {}
        with_obs = {**without_obs, "observation": obs_fingerprint} if obs_fingerprint else without_obs
        lineage = {
            table: (without_obs if table in _TABLES_WITHOUT_OBSERVATION_DEPENDENCY else with_obs)
            for table in projections
        }
        common.record_stage_fingerprints(conn, projections, lineage=lineage)
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

    # 検証した時点の指紋をここで受け取り、write_projections にそのまま渡す
    # （/code-review 指摘の根本対応: cube_db を改めて開いて読み直さない）。
    verified_fingerprints: dict[str, str] = {}
    with common.timed_step("v1 形へ射影") as info:
        projections = build_projections(
            args.cube_db, registry_db, args.baseline_json,
            verified_fingerprints_out=verified_fingerprints,
        )
        info["n"] = sum(len(rows) for _, rows in projections.values())

    with common.timed_step(f"{args.out} に書き出し") as info:
        write_projections(projections, args.out, verified_fingerprints=verified_fingerprints)
        info["n"] = sum(len(rows) for _, rows in projections.values())

    for table, (_, rows) in sorted(projections.items()):
        print(f"  {table}: {len(rows):,}行")


if __name__ == "__main__":
    main()
