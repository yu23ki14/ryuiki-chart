#!/usr/bin/env python3
"""`observation`（`data/db/v2.sqlite`、b03 が作ったもの）から、ADR-0011 のキューブ
`observation_agg` を作る（ADR-0016 Phase B「ファクトとキューブ」縦に薄い1本）。

    .venv/bin/python3 scripts/b04_build_cube.py

`imputation='zero'` の系列だけを作る（design.md 5. 受け入れ条件・ADR-0016）。
`data/db/v2.sqlite` に `observation_agg` テーブルを（作り直して）追加する。

## 入出力について（design.md D8 と「共通」節の折り合い）

design.md D8 は `observation` と `observation_agg` を同じ `data/db/v2.sqlite` に
同居させると決めている。「入力は読み取り専用で開く」「出力は毎回作り直す」を
文字通りファイル単位で満たすと、`observation`（b03 の出力）を上書きしてしまう。
そこでここでは**テーブル単位**で守る: `v2.sqlite` は読み書き可能で開くが、
`observation` は一切変更しない（`SELECT` するだけ）。作り直すのは
`observation_agg` テーブルだけ（`migrate.common.replace_table`）。

## キューブの次元キー（design.md D5・ADR-0011）

    region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
    period_start, period_end, grain, input_grain, stat, imputation

- `obs_stat`: `observation` 側の統計量（alias が言う。例: pH の最大値/最小値を
  別々に配る出典では `obs_stat='max'`/`'min'` になる）。
- `stat`: **キューブ自身**が観測の集合に対して行う集計関数
  （`'mean'`/`'min'`/`'max'`）。日次セルは常に `stat='mean'`
  （v1 の `meas_daily.value` が `AVG(value)` なので、min/max は作らない）。
  月次セルも同様に `stat='mean'`。年次セルだけ `stat` ごとに別の行になる
  （`meas_year` の `avg`/`min`/`max` を再現するため。design.md D5・D6）。
- `input_grain`: 「積み上げの元になった**下位の格**」ではなく、
  **葉の observation（積み上げの末端にある生の観測行）の `period_grain`**
  と定義する（アドバイザー指摘・オーナー採用）。日次セルから積み上げた
  月次/年次セルは、日次を経由した回数によらず常に `'day'`
  （日→月→年のどの段を経由しても値は変わらない）。出典が直接配った
  年次値（`period_grain <> 'day'`）は、その `period_grain` をそのまま使う
  （`meas_year.kind` の daily/annual の区別に対応。design.md D5）。
- **月次・年次（daily 側）は、どちらも日次セル（`cube_day`）から直接作る。
  生の観測から作り直さない。** 月を経由してから年を作る（月平均の平均で年を作る）
  のではない——それでは重み付けが変わり v1 と一致しない（v1 の
  `web/scripts/build-derived.mjs` も `meas_month`/`meas_year(kind='daily')` の
  両方を `FROM meas_daily` で作っており、同じ経路）。出典が配った年次値
  （annual 側）だけは観測から直接作る。ADR-0011 の「粒度をまたぐ再集計をしない。
  日→月→年の順で積み上げ」は「生の観測から作り直さない」という意味であり、
  「年は必ず月を経由する」という意味ではない。

## imputation='zero'（design.md D2・b04 仕様）

`below_lod`/`not_detected` にだけ 0.0 を代入する。`above_lod`/`unknown` には
代入しない——`observation.value_num` は既に検閲行では NULL
（`scripts/migrate/censoring.resolve_value_num`）なので、この2つは
「代入しない」を「NULL のまま」で表せる。`n_censored` は `below_lod` の数、
`n_not_detected` は `not_detected` の数を別に持つ（ADR-0009 決定2）。

## unit_raw をキューブに持たない（B-1・レビュー指摘）

ADR-0011 が定義するキューブの列は `unit_id` までで、`unit_raw`（原表記の単位
文字列。例: `"mg/L"`）は無い。以前はここで `MAX(unit_raw)` を運んでおり、
`observation_agg` に v1 の語彙（原表記）が漏れていた。実測では `unit` は
`variable` だけの関数（1つの variable が2種以上の unit_raw を持つ例は0件）
なので、キューブが原表記を運ぶ必要は無い。次の縦線（`sensor_timeseries`）は
原表記単位に ×10 スケール表記7件という本物の罠を持つため、「キューブ経由で
原表記を運ぶ」配線をここで先例として残したくない。原表記が要る箇所（v1 の
`unit` 列）は `scripts/b05_project_v1.py` が `observation`（キューブではなく
ファクト）から引き戻す——CLAUDE.md の「レジストリの語彙ではないデータの癖は、
それを使う画面・モジュール側に1箇所だけ置く」と同じ原則を、この移行でも守る。

## ADR-0011 の列のうち、この縦線で埋めないもの

- `coverage_ratio`（期間内に実データがあった割合）: 「期間内に何個データが
  あるべきか」を決める暦（サンプリング頻度の期待値）をまだ持っていない
  （このデータには観測されなかった欠測日の情報が無く、母集団が定義できない）。
- `taxon_id`: `measurements` は生物の量ではない（この縦線に無関係。b03 と同じ理由）。
- `built_at`（構築時刻）: **意図的に持たない。** 実行時刻を書き込むと、
  受け入れ条件2（b03〜b05 を2回実行して `content_hash` がバイト一致すること）が
  構造的に満たせなくなる（`scripts/b01_derived_baseline.py` が実行時刻を
  一切書かないのと同じ理由）。`built_from` はこれとは別の話で書き込む
  （すぐ下の節）が、`scripts/b05_project_v1.py` の射影列には載らない——つまり
  `built_from` の値が変わっても b02 のゲート（射影の content_hash 比較）には
  一切影響しない。
- `n_places`: この縦線はロールアップしない（design.md 着手判定 #4。`meas_*` は
  地点別）ため、次元キーに `place_id` が必ず入り、どのセルも常に1地点だけを
  集約する。したがって常に `1`。今後ゾーン/流域へのロールアップを足すときに
  初めて意味を持つ列。

## SQLite の版を守る（アドバイザー指摘・オーナー採用）

**平均は SQLite の `AVG()` で計算する。pandas/numpy/Python の素朴な加算で計算し
直さない**（`_day_sql`/`_year_from_day_stats_sql`/`_year_annual_stats_sql` の
`AVG(v)` がこれに当たる）。これは走査順の問題ではなく**加算アルゴリズム**の問題:
SQLite 3.43 以降は `AVG()`/`SUM()` に Kahan-Babuška-Neumaier 加算（丸め誤差を
補正しながら足す）を使うが、それより前のバージョンは素朴な左→右加算に落ちる。
アドバイザーの実測では、素朴な加算だと `meas_year(kind='daily')` の
3,176/15,836 グループ（20%）で平均値がベースラインと食い違う。

この環境の `sqlite3` **CLI** は 3.37.2（条件を満たさない）だが、b04 が実際に
使うのは **Python 同梱の `sqlite3` モジュール**（3.49.1、条件を満たす）であり、
CLI とは別物。とはいえ「たまたま今の Python が新しいから通っている」を
黙って信用せず、実行のたびに検証する。満たさなければ、理由
（KBN 加算が無いと `meas_year` の20%が変わる）を示して起動時に止まる
（下記の明示的な `raise SystemExit`。`assert` にしない——`python -O`/
`PYTHONOPTIMIZE=1` で `assert` 文はまるごと消え、まさにこのガードが要る場面
＝古い SQLite で `meas_year` の約20%が黙って変わる場面で無効化されてしまう）。
`observation_agg.built_from` にも版を記録し、後から「どの SQLite で計算された
キューブか」を追跡できるようにする（ただし `built_from` は
`scripts/b05_project_v1.py` の射影に載らないので、この値が変わっても b02 の
ゲートには影響しない。同じ venv で2回実行する限りは値自体も変わらないため、
決定論の保証は崩れない）。

## 見送った案: `_day_sql`/`_month_sql`/`_year_from_day_stats_sql`/
`_year_annual_stats_sql` の4関数を1つのパラメータ化された関数に統合する

**採らない。** mean/min/max を1本の SELECT にまとめたことで（`stat`/`agg_fn`
という軸は消えたが）、残る違いは「生の観測→日次」「日次→月次」「日次→年次」
「生の観測→出典配布の年次」という**4つの異なる集計経路そのもの**である。
ADR-0021 決定2は、まさにこの経路の違いを `input_grain` というキーの一部として
残すと決めている。4つを共通のパラメータ袋（例: `from_table`/`where_clause`/
`group_by_extra` を引数に取る1関数）に押し込めると、コードは短くなるが
ADR が「区別して残せ」と言っている経路の違いがパラメータの陰に隠れ、読んで
分からなくなる。次に同じ整理を思いつく人が同じ検討をやり直さないよう、
この判断をここに残す。
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
# 「どの版の SQLite で AVG() を計算したキューブか」を追跡できるようにする
# （変更3）。同じ venv で2回実行する限りこの値は変わらないので、
# 決定論（content_hash のバイト一致）は崩さない。
DEFAULT_BUILT_FROM = f"observation (sqlite={sqlite3.sqlite_version})"

# ADR-0011 の次元キー（design.md D5）。列順はそのまま `observation_agg` の
# 列順の先頭に使う（b05 がこの並びに依存しないよう名前で参照するが、
# レポート等で人が読む順序としてもこれが正）。
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
# （唯一の定義。実際に 0 を代入するのはこの SQL 自身）から組み立てる
# （レビュー指摘: 以前はここに
# `IN ('below_lod', 'not_detected')` と直書きしていて、`scripts/migrate/censoring.py`
# の定義と2箇所に同じ規則があった。片方だけ変えると単体テスト・b03 のレポートと
# キューブの実際の値が静かに食い違うため、この唯一の定義から SQL 断片を作る）。
# `value_num` は b03 の時点で above_lod/unknown では既に NULL になっているので、
# ここでの CASE はこの2分岐だけで済む（明示的に書いて「代入しない」ことを読めるようにする）。
_ZERO_IMPUTED_IN_CLAUSE = ", ".join(f"'{c}'" for c in censoring.ZERO_IMPUTED_CENSORING)
_CREATE_OBS_ZERO_VIEW_SQL = f"""
CREATE TEMP VIEW obs_zero AS
SELECT *,
       CASE WHEN censoring IN ({_ZERO_IMPUTED_IN_CLAUSE}) THEN 0.0 ELSE value_num END AS v
FROM observation
"""

_DIM_SELECT = ", ".join(DIM_COLUMNS[:7])  # region_id..value_grain（期間より前の7列）


# `built_from`/`spec_version` はどの SELECT でも「行ごとに同じ1つの値を複製する」
# だけの列で、集計にもキーにも関わらない。SQL に値を文字列として埋め込む
# （`f"'{built_from}'"`）と、値がアポストロフィを含んだときに構文エラーになる
# （レビュー指摘）。そのためここでは `?` のバインドパラメータにし、呼び出し側
# （`build_cube`）が `(built_from, spec_version)` を毎回そのまま `conn.execute`
# に渡す（`migrate.common.replace_table` も `params` を受けて素通しする）。
_BUILT_FROM_SELECT = "? AS built_from, ? AS spec_version"


def _day_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end, 'day' AS grain, 'day' AS input_grain,
           'mean' AS stat, 'zero' AS imputation,
           AVG(v) AS value,
           COUNT(*) AS n,
           SUM(censoring = 'below_lod') AS n_censored,
           SUM(censoring = 'not_detected') AS n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM obs_zero
    WHERE period_grain = 'day' AND v IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end
    """


def _month_sql() -> str:
    # 月次は日次セル（cube_day）から積み上げる（ADR-0011: 生の観測から作り直さない）。
    return f"""
    SELECT {_DIM_SELECT},
           date(period_start, 'start of month') AS period_start,
           date(period_start, 'start of month', '+1 month', '-1 day') AS period_end,
           'month' AS grain, 'day' AS input_grain, 'mean' AS stat, 'zero' AS imputation,
           AVG(value) AS value,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM cube_day
    GROUP BY {_DIM_SELECT}, date(period_start, 'start of month')
    """


# 年次は mean/min/max の3行になる（design.md D5・D6）が、3つとも同じ次元キー・
# 同じ入力行に対する集計なので、GROUP BY を3回叩き直す必要は無い（C-2・
# レビュー指摘: 実測で年次だけで全体の約32%を占めていた）。まず
# `_year_from_day_stats_sql`/`_year_annual_stats_sql` で `v_mean`/`v_min`/`v_max`
# を1本の SELECT にまとめて一時テーブルへ、そこから
# `_year_from_day_expand_sql`/`_year_annual_expand_sql` で `stat` リテラルと
# 対応する値列だけを変えた3本の INSERT に展開する（`build_cube` 参照）。


def _year_from_day_stats_sql() -> str:
    # 年次（daily側）は日次セル（cube_day）から積み上げる。
    return f"""
    SELECT {_DIM_SELECT},
           date(period_start, 'start of year') AS period_start,
           date(period_start, 'start of year', '+1 year', '-1 day') AS period_end,
           AVG(value) AS v_mean, MIN(value) AS v_min, MAX(value) AS v_max,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected
    FROM cube_day
    GROUP BY {_DIM_SELECT}, date(period_start, 'start of year')
    """


def _year_from_day_expand_sql(stat: str, value_column: str) -> str:
    # `stat`/`value_column` はこの関数の固定引数（呼び出し側が 'mean'/'min'/'max'
    # と対応する v_mean/v_min/v_max のリテラルを渡す。ユーザー入力ではない）
    # なので、これ自体はバインドパラメータにしない。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'year' AS grain, 'day' AS input_grain, '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM year_from_day_stats
    """


def _year_annual_stats_sql() -> str:
    # 出典が直接配った年次値（period_grain <> 'day'）。観測から直接作る
    # （日次セルを経由しない＝ input_grain は period_grain そのもの）。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end, period_grain,
           AVG(v) AS v_mean, MIN(v) AS v_min, MAX(v) AS v_max,
           COUNT(*) AS n,
           SUM(censoring = 'below_lod') AS n_censored,
           SUM(censoring = 'not_detected') AS n_not_detected
    FROM obs_zero
    WHERE period_grain <> 'day' AND v IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end, period_grain
    """


def _year_annual_expand_sql(stat: str, value_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           period_grain AS grain, period_grain AS input_grain,
           '{stat}' AS stat, 'zero' AS imputation,
           {value_column} AS value, n, n_censored, n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM year_annual_stats
    """


def build_cube(conn, built_from: str = DEFAULT_BUILT_FROM, spec_version: str = common.SPEC_VERSION) -> dict:
    """`conn`（`observation` を持つ読み書き可能な接続）に `observation_agg` を作る。

    `conn` 自身は読み取り専用で開かない（`observation` と同じファイルに書くため。
    モジュール docstring 参照）。ここでは `observation` を変更する SQL を
    一切実行しない（`SELECT`/一時 VIEW の作成のみ）。

    戻り値はレポート用の統計（grain ごとの行数）。
    """
    params = (built_from, spec_version)
    conn.execute(_CREATE_OBS_ZERO_VIEW_SQL)
    # 月次・年次（daily側）は cube_day から直接作る（モジュール docstring
    # 「キューブの次元キー」参照）。以前はここで `cube_month` という一時テーブルも
    # 作っていたが、`_month_sql` は実際には `cube_day` から作り直しており
    # （下の INSERT がそれ）、`cube_month` は一度も読まれずに DROP されるだけの
    # 無駄な中間テーブルだった（レビュー指摘。127,493行ぶんの CREATE TABLE AS
    # SELECT を毎回無駄に実行していた）。そのため `cube_month` 自体を作らない。
    common.replace_table(
        conn,
        "cube_day",
        f"CREATE TEMP TABLE cube_day AS {_day_sql()}",
        params,
    )

    common.replace_table(conn, "observation_agg", _CREATE_OBSERVATION_AGG_SQL)
    insert_cols = ", ".join(
        DIM_COLUMNS + ["value", "n", "n_censored", "n_not_detected", "n_places", "built_from", "spec_version"]
    )
    insert_sql = f"INSERT INTO observation_agg ({insert_cols}) "

    # 日次は `cube_day` をそのまま INSERT する。`cube_day` は `_day_sql()` の
    # SELECT 句をそのまま `CREATE TEMP TABLE AS` した中身なので、列名の並びは
    # `insert_cols` と一致している（列名で SELECT するので、たまたま順序が
    # 合っているのではなく、名前が合っていることを保証する）。C-1・レビュー指摘:
    # 以前はここで `_day_sql()` をもう一度実行しており、`cube_day` を作るのに
    # 使ったのと同じ集計を独立にもう1回計算していた（全体の約1割を無駄にしていた）。
    conn.execute(insert_sql + f"SELECT {insert_cols} FROM cube_day")
    n_day = conn.execute("SELECT COUNT(*) FROM observation_agg WHERE grain='day'").fetchone()[0]

    conn.execute(insert_sql + _month_sql(), params)
    n_month = conn.execute("SELECT COUNT(*) FROM observation_agg WHERE grain='month'").fetchone()[0]

    # 年次（daily側）: mean/min/max を1本の GROUP BY でまとめて計算し（C-2）、
    # `stat` リテラルと対応する値列だけを変えた3本の INSERT に展開する。
    common.replace_table(
        conn, "year_from_day_stats", f"CREATE TEMP TABLE year_from_day_stats AS {_year_from_day_stats_sql()}"
    )
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _year_from_day_expand_sql(stat, value_column), params)

    # 年次（annual側 = 出典が直接配った年次値）も同様にまとめて計算する。
    common.replace_table(
        conn, "year_annual_stats", f"CREATE TEMP TABLE year_annual_stats AS {_year_annual_stats_sql()}"
    )
    for stat, value_column in (("mean", "v_mean"), ("min", "v_min"), ("max", "v_max")):
        conn.execute(insert_sql + _year_annual_expand_sql(stat, value_column), params)

    n_year_daily = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE grain='year' AND input_grain='day'"
    ).fetchone()[0]
    # 「出典が直接配った年次値」の grain は 'year'（暦年。kanagawa_jiban_chinka）とは
    # 限らない。'fiscal_year'（年度。env_kousui_annual・atsugi の例外分）もありうる
    # （design.md D4）。この経路は `_year_annual_stats_sql` の WHERE 句
    # （`period_grain <> 'day'`）だけで決まるので、`input_grain <> 'day'` で判定する
    # （`grain='year'` に絞ると 'fiscal_year' の分（env_kousui_annual 98,328行ぶん）を
    # 数え損なう。実データで発見）。
    n_year_annual = conn.execute(
        "SELECT COUNT(*) FROM observation_agg WHERE input_grain <> 'day'"
    ).fetchone()[0]

    conn.execute('DROP TABLE IF EXISTS "cube_day"')
    conn.execute('DROP TABLE IF EXISTS "year_from_day_stats"')
    conn.execute('DROP TABLE IF EXISTS "year_annual_stats"')
    conn.execute("DROP VIEW IF EXISTS obs_zero")
    conn.commit()

    # 次元キーが本当に一意か（同じキーの行が複数できていないか）を確認する。
    # day/month/year(daily)/year(annual) の4つの経路は grain/input_grain の
    # 値で互いに排他のはずだが、それが崩れていないことを実測で確認する
    # （「たまたま今のデータでは一意」ではなく、この実行で一意であることを
    # 毎回検証する）。
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
        "n_month": n_month,
        "n_year_daily": n_year_daily,
        "n_year_annual": n_year_annual,
        "n_total": n_day + n_month + n_year_daily + n_year_annual,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_DB), help="observation を持つ v2.sqlite（読み書き）")
    args = parser.parse_args()

    db_path = pathlib.Path(args.out)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b03_build_observation.py` を実行すること。"
        )

    conn = sqlite3.connect(str(db_path))
    try:
        n_observation = conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0]
        print(f"▶ 読み書き可能で開く（observation は変更しない）: {db_path} / observation {n_observation:,}行")
        with common.timed_step("observation_agg を構築") as info:
            stats = build_cube(conn)
            info["n"] = stats["n_total"]
    finally:
        conn.close()

    print(
        f"  内訳: day={stats['n_day']:,} / month={stats['n_month']:,} / "
        f"year(daily)={stats['n_year_daily']:,} / year(annual)={stats['n_year_annual']:,}"
    )


if __name__ == "__main__":
    main()
