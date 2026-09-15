#!/usr/bin/env python3
"""`observation`（`data/db/v2.sqlite`、b03 が作ったもの）から、ADR-0011 のキューブ
`observation_agg`（ADR-0021・「センサーの縦線 設計 v2」T4 で拡張したキー）を作る
（ADR-0016 Phase B「ファクトとキューブ」）。

    .venv/bin/python3 scripts/b04_build_cube.py

`imputation='zero'` の系列だけを作る（design.md 5. 受け入れ条件・ADR-0016）。
`data/db/v2.sqlite` に `observation_agg` テーブルを（作り直して）追加する。

## 入出力について（design.md D8 と「共通」節の折り合い）

design.md D8 は `observation` と `observation_agg` を同じ `data/db/v2.sqlite` に
同居させると決めている。「入力は読み取り専用で開く」「出力は毎回作り直す」を
文字通りファイル単位で守ると、`observation`（b03 の出力）を上書きしてしまう。
そこでここでは**テーブル単位**で守る: `v2.sqlite` は読み書き可能で開くが、
`observation` は一切変更しない（`SELECT` するだけ）。作り直すのは
`observation_agg` テーブルだけ（`migrate.common.replace_table`）。
`registry.sqlite`（`variable.default_stat` を読むためだけに使う。下記
「日次セルの stat」節参照）は読み取り専用で ATTACH する。

## キューブの次元キー（design.md D5・ADR-0011・ADR-0021）

    region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
    period_start, period_end, grain, input_grain, stat, imputation

- `obs_stat`: `observation` 側の統計量（alias が言う。例: pH の最大値/最小値を
  別々に配る出典では `obs_stat='max'`/`'min'` になる）。
- `stat`: **キューブ自身**が観測の集合に対して行う集計関数
  （`'mean'`/`'min'`/`'max'`/`'sum'`）。
- `input_grain`: 「積み上げの元になった下位の格」ではなく、**葉の
  observation（積み上げの末端にある生の観測行）の `period_grain`** と定義する
  （アドバイザー指摘・オーナー採用）。日次セルから積み上げた月次/年次セルは、
  日次を経由した回数によらず、その日次セル自身の `input_grain` をそのまま
  引き継ぐ（`'day'` 直書きをやめる。T4-1）——日次セル自身が
  `period_grain IN ('day','hour','instant')` のどれから来たかによって
  `'day'`/`'hour'`/`'instant'` のいずれかになる。出典が直接配った月次・年次値
  （`period_grain IN ('month','year','fiscal_year')`）は、観測から直接作り、
  その `period_grain` をそのまま `input_grain` として使う（日次セルを経由
  しない。「出典配布セル」は常に `grain == input_grain`）。

## センサーの縦線 設計 v2 T4: このスクリプトで変わったこと

1. **毎時・瞬時の観測（`period_grain IN ('hour','instant')`）も日次セルに
   積み上げる。** `period_grain='day'` の観測と同様に「日」の格へ入るが、
   日付は `substr(period_start, 1, 10)`（区間の始まりの日付）を使う——
   `period_start` は b03（`scripts/migrate/period.py`）が既に「hour_ending の
   ラベル−1時間」を計算済みなので、ここでさらに時刻を補正する必要は無い
   （これが v1 のラベル日割りとの違いであり、正しい日割り。
   `scripts/b05_project_v1.py` の T5/T6 節参照）。
   `period_grain='month'`（jma_monthly）は日次セルを経由せず、年次の出典配布
   セルと対称な「出典配布の月次セル」になる。`period_grain IN ('year',
   'fiscal_year')` だけが出典配布の年次セルになる（今までの
   `period_grain <> 'day'` という広すぎる条件を、ここに閉じる——閉じないと
   毎時・月次の観測が誤って年次として吸い込まれる）。
2. **日次セルは全変数で `stat ∈ {mean, min, max}` を必ず作る。**
   `scripts/b05_project_v1.py` の `sensor_daily`（`avg`/`min`/`max` を
   ピボットする）が必要とする（設計 v2 T5(a)）。加えて、
   `variable.default_stat='sum'` かつ（`obs_stat IS NULL` または
   `obs_stat='sum'`）の系列だけ `stat='sum'` の行も足す（雨量のような
   加算可能な系列専用。`weather.precipitation`/`weather.sunshine_duration`
   等——実測ではどれも `measurements` データセットには現れない`weather.*`系
   variable_id なので、既存6テーブル（`measurements` 由来）はこの追加行の
   影響を一切受けない）。`jma_daily` の `降水量_最大_10分間`
   （`obs_stat='max_10min'`）のような「最大値」を宣言している系列には
   `sum` をかけない——`obs_stat` の条件がこれを防ぐ。
3. **`cube_day` を読む全箇所（月次・年次の積み上げ）で `stat='mean'` を
   明示的に絞る。** 日次セルが常に1系列1行だった旧実装と違い、今は
   同じ次元キー・同じ日に `mean`/`min`/`max`/`sum` の複数行がありうる。
   絞らないと月・年の平均に日次の min/max/sum が混ざり、**既存6テーブル
   （`measurements` 由来）の値まで黙って変わる**（アドバイザー・オーナーが
   最も疑わしいと指摘した箇所）。`scripts/b05_project_v1.py` の
   `meas_daily`/`meas_month` 側にも同じ絞り込みを足してある。
4. **年次の出典配布セルの件数は `grain = input_grain` で判定する**
   （`input_grain <> 'day'` という以前の条件は、月次の出典配布セル
   （`input_grain='month'`）まで年次として数えてしまうため使えない）。

## imputation='zero'（design.md D2・b04 仕様）

`below_lod`/`not_detected` にだけ 0.0 を代入する。`above_lod`/`unknown` には
代入しない——`observation.value_num` は既に検閲行では NULL
（`scripts/migrate/censoring.resolve_value_num`）なので、この2つは
「代入しない」を「NULL のまま」で表せる。`n_censored` は `below_lod` の数、
`n_not_detected` は `not_detected` の数を別に持つ（ADR-0009 決定2）。
`sensor_timeseries` 由来の行は `censoring` が常に `'none'`
（`scripts/b03_build_observation.py`）なので、この分岐の影響を受けない。

## unit_raw をキューブに持たない（B-1・レビュー指摘）

ADR-0011 が定義するキューブの列は `unit_id` までで、`unit_raw`（原表記の単位
文字列。例: `"mg/L"`）は無い。原表記が要る箇所（v1 の `unit` 列）は
`scripts/b05_project_v1.py` が `observation`（キューブではなくファクト）から
引き戻す。

## ADR-0011 の列のうち、この縦線で埋めないもの

- `coverage_ratio`（期間内に実データがあった割合）: サンプリング頻度の期待値
  をまだ持っていない。
- `taxon_id`: `measurements`/`sensor_timeseries` はどちらも生物の量ではない。
- `built_at`（構築時刻）: **意図的に持たない**（受け入れ条件の決定論・
  content_hash バイト一致が崩れるため）。
- `n_places`: この縦線はロールアップしない（次元キーに `place_id` が必ず
  入る）ため、常に `1`。

## SQLite の版を守る（アドバイザー指摘・オーナー採用）

**平均は SQLite の `AVG()` で計算する。pandas/numpy/Python の素朴な加算で計算し
直さない。** SQLite 3.43 以降は `AVG()`/`SUM()` に Kahan-Babuška-Neumaier 加算
（丸め誤差を補正しながら足す）を使うが、それより前のバージョンは素朴な
左→右加算に落ちる。アドバイザーの実測では、素朴な加算だと
`meas_year(kind='daily')` の3,176/15,836グループ（20%）で平均値がベースライン
と食い違う。この環境の `sqlite3` **CLI** は 3.37.2（条件を満たさない）だが、
b04 が実際に使うのは **Python 同梱の `sqlite3` モジュール**（3.49.1、条件を
満たす）——モジュール読み込み時点で `sqlite3.sqlite_version_info >= (3, 43,
0)` を検証し、満たさなければ `raise SystemExit` で止まる（`assert` にしない
——`python -O`/`PYTHONOPTIMIZE=1` ではまさにこのガードが要る場面で無効化
されてしまう）。`observation_agg.built_from` にも版を記録する。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import censoring, common  # noqa: E402

DEFAULT_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"

# SQLite 3.43 で AVG()/SUM() の加算が Kahan-Babuška-Neumaier に変わった
# （上のモジュール docstring「SQLite の版を守る」参照）。ここより前のバージョンでは
# 平均が黙って壊れる（アドバイザー実測: meas_year(kind='daily') の20%が変わる）ので、
# 黙って進まず、モジュール読み込み時点で止める。`assert` ではなく明示的な
# `raise SystemExit` にする（レビュー指摘: `python -O`/`PYTHONOPTIMIZE=1` では
# `assert` が丸ごと消え、SQLite 3.43 未満で `meas_year` の約20%が黙って変わる
# ことになる——チェックそのものが消えてよい理由が無い）。
_MIN_SQLITE_VERSION = (3, 43, 0)
if sqlite3.sqlite_version_info < _MIN_SQLITE_VERSION:
    raise SystemExit(
        f"sqlite3（Python 同梱、バージョン {sqlite3.sqlite_version}）が古すぎる。"
        f"SQLite {'.'.join(map(str, _MIN_SQLITE_VERSION))} 以降が必要——それより前は "
        "AVG()/SUM() が Kahan-Babuška-Neumaier 加算ではなく素朴な左→右加算に落ち、"
        "meas_year(kind='daily') の20%（アドバイザー実測: 3,176/15,836グループ）で"
        "平均値が変わる。sqlite3 CLI のバージョンではなく、この Python が import する "
        "sqlite3 モジュール（標準ライブラリに静的リンクされた版）のバージョンを見ている。"
    )

# `observation_agg.built_from` の既定値。SQLite の版を埋め込み、後から
# 「どの版の SQLite で AVG() を計算したキューブか」を追跡できるようにする。
# 同じ venv で2回実行する限りこの値は変わらないので、決定論（content_hash の
# バイト一致）は崩さない。
DEFAULT_BUILT_FROM = f"observation (sqlite={sqlite3.sqlite_version})"

# ADR-0011 の次元キー（design.md D5）。列順はそのまま `observation_agg` の
# 列順の先頭に使う。
DIM_COLUMNS = [
    "region_id", "place_id", "place_kind", "variable_id", "obs_stat", "unit_id",
    "value_grain", "period_start", "period_end", "grain", "input_grain", "stat", "imputation",
]

_CREATE_OBSERVATION_AGG_SQL = f"""
CREATE TABLE observation_agg (
  {", ".join(f'{c} TEXT' for c in DIM_COLUMNS)},
  value REAL,
  n INTEGER NOT NULL,
  n_censored INTEGER NOT NULL,
  n_not_detected INTEGER NOT NULL,
  n_places INTEGER NOT NULL,
  built_from TEXT NOT NULL,
  spec_version TEXT NOT NULL
)
"""

# `obs_zero`: `imputation='zero'` を適用した後の値（`v`）を作る SQL。
# 0 を代入する censoring の値は `censoring.ZERO_IMPUTED_CENSORING`
# （唯一の定義）から組み立てる。`sensor_timeseries` 由来の行は censoring が
# 常に 'none' なので、この CASE の対象にならず `value_num` がそのまま通る。
_ZERO_IMPUTED_IN_CLAUSE = ", ".join(f"'{c}'" for c in censoring.ZERO_IMPUTED_CENSORING)
_CREATE_OBS_ZERO_VIEW_SQL = f"""
CREATE TEMP VIEW obs_zero AS
SELECT *,
       CASE WHEN censoring IN ({_ZERO_IMPUTED_IN_CLAUSE}) THEN 0.0 ELSE value_num END AS v
FROM observation
"""

_DIM_SELECT = ", ".join(DIM_COLUMNS[:7])  # region_id..value_grain（期間より前の7列）

# `built_from`/`spec_version` はどの SELECT でも「行ごとに同じ1つの値を複製する」
# だけの列。バインドパラメータで渡す（値がアポストロフィを含んでも構文エラーに
# ならないように）。
_BUILT_FROM_SELECT = "? AS built_from, ? AS spec_version"


# ---------------------------------------------------------------------------
# 日次セル（T4-2）
# ---------------------------------------------------------------------------
# 観測（period_grain IN ('day','hour','instant')）を「日」の格へ積み上げる。
# 日付は substr(period_start,1,10)（区間の始まりの日付。hour_ending の場合は
# b03 が既にラベル-1時間を計算済みなので、ここでの substr で正しい日になる。
# T4-1・T6）。mean/min/max/sum の4通りをここで一度に計算してから
# （C-2 と同じ考え方: 同じ GROUP BY を4回叩き直さない）、stat ごとに展開する。

def _day_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_grain,
           substr(period_start, 1, 10) AS period_start,
           substr(period_start, 1, 10) AS period_end,
           AVG(v) AS v_mean, MIN(v) AS v_min, MAX(v) AS v_max, SUM(v) AS v_sum,
           COUNT(*) AS n,
           SUM(censoring = 'below_lod') AS n_censored,
           SUM(censoring = 'not_detected') AS n_not_detected
    FROM obs_zero
    WHERE period_grain IN ('day', 'hour', 'instant') AND v IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_grain, substr(period_start, 1, 10)
    """


def _day_expand_sql(stat: str, value_column: str) -> str:
    # `stat`/`value_column` は呼び出し側の固定引数（ユーザー入力ではない）。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'day' AS grain, period_grain AS input_grain, '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM day_stats
    """


def _day_sum_expand_sql() -> str:
    # T4-2: variable.default_stat='sum' かつ (obs_stat IS NULL または
    # obs_stat='sum') の系列だけ sum の日次セルを足す。「最大値」等を宣言
    # している系列（obs_stat='max_10min' 等）には合計をかけない。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'day' AS grain, period_grain AS input_grain, 'sum' AS stat, 'zero' AS imputation,
           v_sum AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM day_stats
    WHERE variable_id IN (SELECT variable_id FROM reg.variable WHERE default_stat = 'sum')
      AND (obs_stat IS NULL OR obs_stat = 'sum')
    """


# ---------------------------------------------------------------------------
# 月次・年次（日次セルから積み上げる側。T4-1「月・年の積み上げは日次セルから。
# input_grain は cube_day から引き継ぐ」）
# ---------------------------------------------------------------------------
# ADR-0011「粒度をまたぐ再集計をしない」は「生の観測から作り直さない」という
# 意味であり、「年は必ず月を経由する」という意味ではない——v1
# （web/scripts/build-derived.mjs）も meas_month/meas_year(kind='daily') の
# 両方を FROM meas_daily で作っており、同じ経路（月を経由しない）。
#
# cube_day は「直前に observation_agg へ書いた日次セルそのもの」を読み返す
# だけ（`build_cube` 参照）——_day_stats_sql/_day_expand_sql をもう一度
# 計算し直さない。`WHERE stat='mean'` は必須（T4-3。絞らないと月・年の
# 平均に日次の min/max/sum が混ざる）。

def _month_from_day_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT},
           date(period_start, 'start of month') AS period_start,
           date(period_start, 'start of month', '+1 month', '-1 day') AS period_end,
           'month' AS grain, input_grain, 'mean' AS stat, 'zero' AS imputation,
           AVG(value) AS value,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM cube_day
    WHERE stat = 'mean'
    GROUP BY {_DIM_SELECT}, input_grain, date(period_start, 'start of month')
    """


def _year_from_day_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, input_grain,
           date(period_start, 'start of year') AS period_start,
           date(period_start, 'start of year', '+1 year', '-1 day') AS period_end,
           AVG(value) AS v_mean, MIN(value) AS v_min, MAX(value) AS v_max,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected
    FROM cube_day
    WHERE stat = 'mean'
    GROUP BY {_DIM_SELECT}, input_grain, date(period_start, 'start of year')
    """


def _year_from_day_expand_sql(stat: str, value_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'year' AS grain, input_grain, '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM year_from_day_stats
    """


# ---------------------------------------------------------------------------
# 月次・年次（出典配布側。日次セルを経由せず観測から直接作る。T4-1）
# ---------------------------------------------------------------------------
# 月次（jma_monthly、period_grain='month'）は年次の出典配布セルと対称
# （grain=input_grain='month'）。年次（period_grain IN ('year','fiscal_year')）
# は今までの `period_grain <> 'day'` という広すぎる条件をここに閉じる
# （閉じないと月次・毎時の観測まで年次として吸い込まれてしまう）。

def _month_source_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           AVG(v) AS v_mean, MIN(v) AS v_min, MAX(v) AS v_max,
           COUNT(*) AS n,
           SUM(censoring = 'below_lod') AS n_censored,
           SUM(censoring = 'not_detected') AS n_not_detected
    FROM obs_zero
    WHERE period_grain = 'month' AND v IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end
    """


def _month_source_expand_sql(stat: str, value_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'month' AS grain, 'month' AS input_grain, '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM month_source_stats
    """


def _year_source_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end, period_grain,
           AVG(v) AS v_mean, MIN(v) AS v_min, MAX(v) AS v_max,
           COUNT(*) AS n,
           SUM(censoring = 'below_lod') AS n_censored,
           SUM(censoring = 'not_detected') AS n_not_detected
    FROM obs_zero
    WHERE period_grain IN ('year', 'fiscal_year') AND v IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end, period_grain
    """


def _year_source_expand_sql(stat: str, value_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           period_grain AS grain, period_grain AS input_grain,
           '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM year_source_stats
    """


def build_cube(
    conn,
    registry_db=DEFAULT_REGISTRY_DB,
    built_from: str = DEFAULT_BUILT_FROM,
    spec_version: str = common.SPEC_VERSION,
) -> dict:
    """`conn`（`observation` を持つ読み書き可能な接続）に `observation_agg` を作る。

    `conn` 自身は読み取り専用で開かない（`observation` と同じファイルに書くため。
    モジュール docstring 参照）。`registry_db`（`variable.default_stat` を読む
    ためだけに使う。T4-2）は読み取り専用で ATTACH する。ここでは `observation`
    を変更する SQL を一切実行しない（`SELECT`/一時 VIEW・TEMP TABLE の作成のみ）。

    戻り値はレポート用の統計（経路ごとの行数）。
    """
    params = (built_from, spec_version)
    common.attach_readonly(conn, registry_db, "reg")
    conn.execute(_CREATE_OBS_ZERO_VIEW_SQL)

    common.replace_table(conn, "observation_agg", _CREATE_OBSERVATION_AGG_SQL)
    insert_cols = ", ".join(
        DIM_COLUMNS + ["value", "n", "n_censored", "n_not_detected", "n_places", "built_from", "spec_version"]
    )
    insert_sql = f"INSERT INTO observation_agg ({insert_cols}) "

    # 日次（T4-2）。
    common.replace_table(conn, "day_stats", f"CREATE TEMP TABLE day_stats AS {_day_stats_sql()}")
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _day_expand_sql(stat, value_column), params)
    conn.execute(insert_sql + _day_sum_expand_sql(), params)
    n_day = conn.execute("SELECT COUNT(*) FROM observation_agg WHERE grain='day'").fetchone()[0]

    # cube_day: 直前に書いた日次セルそのものを読み返す（列の並びは
    # observation_agg の列そのもの。_day_stats_sql をもう一度計算し直さない）。
    common.replace_table(
        conn, "cube_day", "CREATE TEMP TABLE cube_day AS SELECT * FROM observation_agg WHERE grain='day'"
    )

    # 月次（日次から積み上げ）。
    conn.execute(insert_sql + _month_from_day_sql(), params)
    n_month_from_day = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE grain='month' AND input_grain IN ('day','hour','instant')"
    ).fetchone()[0]

    # 年次（日次から積み上げ）。mean/min/max を1本の GROUP BY でまとめて計算し、
    # stat リテラルと対応する値列だけを変えた3本の INSERT に展開する。
    common.replace_table(
        conn, "year_from_day_stats", f"CREATE TEMP TABLE year_from_day_stats AS {_year_from_day_stats_sql()}"
    )
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _year_from_day_expand_sql(stat, value_column), params)
    n_year_from_day = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE grain='year' AND input_grain IN ('day','hour','instant')"
    ).fetchone()[0]

    # 月次（出典配布側。jma_monthly。年次の出典配布セルと対称）。
    common.replace_table(
        conn, "month_source_stats", f"CREATE TEMP TABLE month_source_stats AS {_month_source_stats_sql()}"
    )
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _month_source_expand_sql(stat, value_column), params)

    # 年次（出典配布側）。
    common.replace_table(
        conn, "year_source_stats", f"CREATE TEMP TABLE year_source_stats AS {_year_source_stats_sql()}"
    )
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _year_source_expand_sql(stat, value_column), params)

    # 出典配布セルの件数は grain = input_grain（積み上げを経由しない）で判定する
    # （T4-4）。`input_grain <> 'day'` という以前の条件は月次の出典配布セル
    # （input_grain='month'）まで拾ってしまうため、ここには使わない。
    n_month_source = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE grain='month' AND grain = input_grain"
    ).fetchone()[0]
    n_year_source = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE grain IN ('year','fiscal_year') AND grain = input_grain"
    ).fetchone()[0]

    conn.execute('DROP TABLE IF EXISTS "day_stats"')
    conn.execute('DROP TABLE IF EXISTS "cube_day"')
    conn.execute('DROP TABLE IF EXISTS "year_from_day_stats"')
    conn.execute('DROP TABLE IF EXISTS "month_source_stats"')
    conn.execute('DROP TABLE IF EXISTS "year_source_stats"')
    conn.execute("DROP VIEW IF EXISTS obs_zero")
    conn.commit()

    # 次元キーが本当に一意か（同じキーの行が複数できていないか）を確認する。
    # day/month(day側/出典側)/year(day側/出典側) の5経路は grain/input_grain/
    # stat の値で互いに排他のはずだが、それが崩れていないことを実測で確認する。
    key_cols = ", ".join(DIM_COLUMNS)
    dup = conn.execute(
        f"SELECT {key_cols}, COUNT(*) c FROM observation_agg GROUP BY {key_cols} HAVING c > 1 LIMIT 5"
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "observation_agg の次元キーが一意でない行がある"
            f"（例: {dup}）。day/month/year の集計経路が重なっている可能性がある。"
        )

    return {
        "n_day": n_day,
        "n_month_from_day": n_month_from_day,
        "n_month_source": n_month_source,
        "n_year_from_day": n_year_from_day,
        "n_year_source": n_year_source,
        "n_total": n_day + n_month_from_day + n_month_source + n_year_from_day + n_year_source,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_DB), help="observation を持つ v2.sqlite（読み書き）")
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"variable.default_stat を読む registry.sqlite。既定は RYUIKI_REGISTRY_DB 環境変数、"
        f"それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    db_path = pathlib.Path(args.out)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b03_build_observation.py` を実行すること。"
        )

    # `uri=True` で開く（`common.attach_readonly` が ATTACH に使う
    # `file:...?mode=ro` を URI として解釈させるため。無いと素の相対/絶対パス
    # として扱われ、レジストリの ATTACH が `unable to open database` で失敗する
    # ——実測で踏んだ。`scripts/b03_build_observation.py`/`b05_project_v1.py` の
    # `:memory:` 接続が `uri=True` を付けているのと同じ理由）。
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        n_observation = conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
        print(f"▶ 読み書き可能で開く（observation は変更しない）: {db_path} / observation {n_observation:,}行")
        print(f"▶ 読み取り専用で開く: {registry_db}")
        with common.timed_step("observation_agg を構築") as info:
            stats = build_cube(conn, registry_db)
            info["n"] = stats["n_total"]
    finally:
        conn.close()

    print(
        f"  内訳: day={stats['n_day']:,} / "
        f"month(day側)={stats['n_month_from_day']:,} / month(出典側)={stats['n_month_source']:,} / "
        f"year(day側)={stats['n_year_from_day']:,} / year(出典側)={stats['n_year_source']:,}"
    )


if __name__ == "__main__":
    main()
