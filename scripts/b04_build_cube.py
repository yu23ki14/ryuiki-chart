#!/usr/bin/env python3
"""`observation`（`data/db/v2.sqlite`、b03 が作ったもの）から、ADR-0011 のキューブ
`observation_agg`（ADR-0021・「センサーの縦線 設計 v2」T4 で拡張したキー、
ADR-0009 決定4で `imputation` を列（`value_zero`/`value_lod`）に変えた形）を作る
（ADR-0016 Phase B「ファクトとキューブ」）。

    .venv/bin/python3 scripts/b04_build_cube.py

`value_zero`/`value_lod` の2系列を常に併記する（design.md 5. 受け入れ条件・
ADR-0016・ADR-0009 決定4）。`data/db/v2.sqlite` に `observation_agg` テーブルを
（作り直して）追加する。

## `imputation` は論理的な軸であり、物理的には列で持つ（ADR-0009 決定4）

以前の `observation_agg` は次元キーに `imputation ∈ {'zero'}` を持ち、
`value` 列（`below_lod`/`not_detected` に 0.0 を代入した後の値）だけを持つ
1系列だった。今回、`lod`（`below_lod` に `censoring_limit` を代入した系列）を
併記するにあたり、**次元キーから `imputation` を外し、`value` を
`value_zero`/`value_lod` の2列に分ける**（次元キーは13列→12列）。

理由（ADR-0009 決定4・オーナー決定）:
1. `imputation` はファクト行を分割する次元ではない——`zero`/`lod` の2系列は
   同じセルのメンバー（`n`/`n_censored`/`n_not_detected`/`n_places` はどちらも
   同じ）で、変わるのは代入する値だけ。次元キーに入れると「同じメンバーの
   セルが2行に分かれる」という誤ったモデルになる。
2. 全セル二重化（次元キーに残したまま `imputation` の値を増やす）は
   +462MB、列追加は +16MB で済む（実測は `docs/adr/0009-censored-values.md`
   決定4）。
3. 列にすることで「`lod` で引いたのに無い」が構造的に起きない
   （`zero`/`lod` は常に同じ行の2列として一緒に存在する）。

## `value_lod` の代入規則（ADR-0009 決定2・非対称）

- `value_zero`: `below_lod`/`not_detected` を 0.0 として平均に含める
  （**v1 の再現のため**。v1 は `value=0.0` の ND 行を `AVG`/`COUNT` に含めている）。
- `value_lod`: `below_lod` は `censoring_limit`（定量下限値）を代入するが、
  `not_detected` は**限界値が無いため代入せず、平均から除外する**
  （ADR-0009 決定2 の本来の規定）。`above_lod`/`unknown` はどちらの系列でも
  非メンバーのまま（0 を代入しない——0 は上限ではない。`unknown` は
  意味が分からない値を推測しないため）。
- 実装は「ND だけの格では `AVG` が NULL を返す」という一般形で書く
  （`CASE WHEN censoring = 'not_detected' THEN NULL ELSE ... END` を
  `AVG`/`MIN`/`MAX` に渡すだけで、SQL の NULL 無視の集約規則がそのまま
  「ND だけの格は NULL、1件でも非 ND があれば非 ND 分だけで計算」を実現する
  ——「ND を含むセルは全て 100% ND」という実データの性質には依存しない）。

## 入出力について（design.md D8 と「共通」節の折り合い）

design.md D8 は `observation` と `observation_agg` を同じ `data/db/v2.sqlite` に
同居させると決めている。「入力は読み取り専用で開く」「出力は毎回作り直す」を
文字通りファイル単位で守ると、`observation`（b03 の出力）を上書きしてしまう。
そこでここでは**テーブル単位**で守る: `v2.sqlite` は読み書き可能で開くが、
`observation` は一切変更しない（`SELECT` するだけ）。作り直すのは
`observation_agg` テーブルだけ（`migrate.common.staged_table`）。
`registry.sqlite`（`variable.default_stat` を読むためだけに使う。下記
「日次セルの stat」節参照）は読み取り専用で ATTACH する。

## 検証が全部通ってから本番名に差し替える（A-1）

以前は `common.replace_table`（DROP+CREATE、本番テーブル名 `observation_agg`
に対して実行）で作り直してから、最後に次元キーの一意性を検証していた。
`replace_table` の DROP+CREATE 自体は即座に確定するものではない
（`migrate.common.staged_table` の docstring 参照——Python 3.6 以降の
`sqlite3` は DDL の前に暗黙コミットしない）が、それより後に `conn.commit()`
を呼んでいたため、**一意性検証に失敗しても、それより前に確定した
`observation_agg` の中身は元に戻せなかった**（バグ）。今は
`migrate.common.staged_table` を使い、一意性検証（下記 C-3）・
`value_zero`/`value_lod` の関係の検証（下記「機械検証」節）まで含めて
全部通ってから本番名 `observation_agg` に差し替える。失敗すれば作業用
テーブルを `DROP` するだけで済み、前回の `observation_agg` はそのまま残る。

## キューブの次元キー（design.md D5・ADR-0011・ADR-0021・ADR-0009 決定4）

    region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
    period_start, period_end, grain, input_grain, stat

（旧キーから `imputation` を外した12列。`value_zero`/`value_lod` は次元では
なく値の列——「機械検証」節参照。）

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

## 機械検証: `value_zero`/`value_lod` の関係（ADR-0009 決定4）

`_assert_dimension_key_unique` の直後、同じ `with staged_table(...)` ブロック
内で `_assert_value_zero_lod_invariants` を呼ぶ。破れれば `staged_table` が
前回の `observation_agg` を残したまま止まる（A-1 と同じ安全策）。

1. `(value_lod IS NULL) = (n_not_detected = n)`（ND だけの格でのみ NULL）。
2. `n_censored = 0 AND n_not_detected = 0` ⇒ `value_lod IS value_zero`
   （ビット一致。検閲の無いセルでは代入の余地が無いので両系列は同じ値になる
   はず——day_stats/month_source_stats/year_source_stats がどちらも同じ
   `GROUP BY` の1パスで `AVG(v_zero)`/`AVG(v_lod)` 等を並べて計算しており、
   加算順序は自動的に揃っている）。
3. 両方が非 NULL ⇒ `value_lod >= value_zero`（`censoring_limit` は正なので、
   検閲行を1件でも含む格は `value_lod` が `value_zero` 以上になるはず）。

## SQLite の版を守る（アドバイザー指摘・オーナー採用）

**平均は SQLite の `AVG()` で計算する。pandas/numpy/Python の素朴な加算で計算し
直さない。** SQLite 3.43 未満だと `AVG()`/`SUM()` の加算アルゴリズムが違い、
平均値が黙って変わる行がある（実測は `docs/plans/PHASE_B_DOCUMENTS.md` §2
参照）。`build_cube()` の先頭で `common.require_sqlite_version()`
（`scripts/migrate/common.py`。b05・`scripts/b10_project_documents_v1.py`
と共有するガード——切り出した理由・**なぜモジュール読み込み時点で呼ばないか**
はそちらの docstring 参照）を呼ぶ。`observation_agg.built_from` にも
実際に使った SQLite の版を記録する。
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

# `observation_agg.built_from` の既定値。SQLite の版を埋め込み、後から
# 「どの版の SQLite で AVG() を計算したキューブか」を追跡できるようにする。
# 同じ venv で2回実行する限りこの値は変わらないので、決定論（content_hash の
# バイト一致）は崩さない。
DEFAULT_BUILT_FROM = f"observation (sqlite={sqlite3.sqlite_version})"

# ADR-0011 の次元キー（design.md D5）。列順はそのまま `observation_agg` の
# 列順の先頭に使う。ADR-0009 決定4: `imputation` は次元キーから外し、
# `value_zero`/`value_lod` の2列に分けた（モジュール docstring 参照）。
DIM_COLUMNS = [
    "region_id", "place_id", "place_kind", "variable_id", "obs_stat", "unit_id",
    "value_grain", "period_start", "period_end", "grain", "input_grain", "stat",
]

# `{table}` プレースホルダに本番名（`observation_agg`）または作業用テーブル名を
# 埋め込む（`migrate.common.staged_table` 参照。A-1）。
_CREATE_OBSERVATION_AGG_SQL = f"""
CREATE TABLE {{table}} (
  {", ".join(f'{c} TEXT' for c in DIM_COLUMNS)},
  value_zero REAL,
  value_lod REAL,
  n INTEGER NOT NULL,
  n_censored INTEGER NOT NULL,
  n_not_detected INTEGER NOT NULL,
  n_places INTEGER NOT NULL,
  built_from TEXT NOT NULL,
  spec_version TEXT NOT NULL
)
"""

# `obs_imputed`: `value_zero`/`value_lod` の両方を1回の VIEW 定義で持つ
# （ADR-0009 決定4「同じ GROUP BY の1パスで並べて計算する」）。0 を代入する
# censoring の値は `censoring.ZERO_IMPUTED_CENSORING`（唯一の定義）から組み
# 立てる。`value_lod` の代入規則は `censoring.CENSORING_BELOW_LOD`/
# `CENSORING_NOT_DETECTED`（唯一の定義）から組み立てる——「below_lod は
# censoring_limit、not_detected は NULL（限界値が無いので代入せず除外）、
# それ以外（none/above_lod/unknown）は value_num」の3分岐（モジュール
# docstring「value_lod の代入規則」参照）。`sensor_timeseries` 由来の行は
# censoring が常に 'none' なので、どちらの CASE でも `value_num` がそのまま
# 通る。
_ZERO_IMPUTED_IN_CLAUSE = ", ".join(f"'{c}'" for c in censoring.ZERO_IMPUTED_CENSORING)
_VALUE_LOD_CASE = (
    f"CASE WHEN censoring = '{censoring.CENSORING_BELOW_LOD}' THEN censoring_limit "
    f"WHEN censoring = '{censoring.CENSORING_NOT_DETECTED}' THEN NULL "
    "ELSE value_num END"
)
_CREATE_OBS_IMPUTED_VIEW_SQL = f"""
CREATE TEMP VIEW obs_imputed AS
SELECT *,
       CASE WHEN censoring IN ({_ZERO_IMPUTED_IN_CLAUSE}) THEN 0.0 ELSE value_num END AS v_zero,
       {_VALUE_LOD_CASE} AS v_lod
FROM observation
"""

_DIM_SELECT = ", ".join(DIM_COLUMNS[:7])  # region_id..value_grain（期間より前の7列）

# `built_from`/`spec_version` はどの SELECT でも「行ごとに同じ1つの値を複製する」
# だけの列。バインドパラメータで渡す（値がアポストロフィを含んでも構文エラーに
# ならないように）。
_BUILT_FROM_SELECT = "? AS built_from, ? AS spec_version"

# B-4: `stat`/値列の組は4箇所（日次・年次(day側)・月次(出典側)・年次(出典側)の
# それぞれの展開ループ）で同じ3つ組を使っていた。ここに1つ宣言する。
# ADR-0009 決定4: 各 stat について value_zero 側・value_lod 側それぞれの列名を
# 持つ3つ組に拡張した。
_STAT_VALUE_COLUMNS = (
    ("mean", "vz_mean", "vl_mean"),
    ("min", "vz_min", "vl_min"),
    ("max", "vz_max", "vl_max"),
)

# B-4: INSERT 列の末尾（`n, n_censored, n_not_detected, 1 AS n_places,
# built_from, spec_version`）は5つの展開 SQL（日次×2・年次(day側)・
# 月次(出典側)・年次(出典側)）で同じ形だった。
_AGG_TAIL_SELECT = f"n, n_censored, n_not_detected,\n           1 AS n_places, {_BUILT_FROM_SELECT}"

# B-4: 検閲件数の式（below_lod/not_detected の個数）は3箇所（日次・
# 月次(出典側)・年次(出典側)の集計 SQL）で同じ形だった。
_CENSORED_COUNTS_SELECT = (
    "SUM(censoring = 'below_lod') AS n_censored,\n"
    "           SUM(censoring = 'not_detected') AS n_not_detected"
)


# ---------------------------------------------------------------------------
# 日次セル（T4-2）
# ---------------------------------------------------------------------------
# 観測（period_grain IN ('day','hour','instant')）を「日」の格へ積み上げる。
# 日付は substr(period_start,1,10)（区間の始まりの日付。hour_ending の場合は
# b03 が既にラベル-1時間を計算済みなので、ここでの substr で正しい日になる。
# T4-1・T6）。mean/min/max/sum の4通り × value_zero/value_lod の2系列を
# ここで一度に計算してから（C-2 と同じ考え方: 同じ GROUP BY を何度も叩き
# 直さない）、stat ごとに展開する。
#
# `WHERE v_zero IS NOT NULL` で絞る観測の集合（above_lod/unknown を除く）は
# 旧実装の `WHERE v IS NOT NULL` と同じ——`value_zero`/`value_lod` は
# 「どちらの系列も同じセルのメンバー」（ADR-0009 決定4 決定1）なので、
# メンバーシップは value_zero 側の非 NULL 性だけで決める。

def _day_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_grain,
           substr(period_start, 1, 10) AS period_start,
           substr(period_start, 1, 10) AS period_end,
           AVG(v_zero) AS vz_mean, MIN(v_zero) AS vz_min, MAX(v_zero) AS vz_max, SUM(v_zero) AS vz_sum,
           AVG(v_lod) AS vl_mean, MIN(v_lod) AS vl_min, MAX(v_lod) AS vl_max, SUM(v_lod) AS vl_sum,
           COUNT(*) AS n,
           {_CENSORED_COUNTS_SELECT}
    FROM obs_imputed
    WHERE period_grain IN ('day', 'hour', 'instant') AND v_zero IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_grain, substr(period_start, 1, 10)
    """


def _day_expand_sql(stat: str, value_zero_column: str, value_lod_column: str) -> str:
    # `stat`/`value_*_column` は呼び出し側の固定引数（ユーザー入力ではない）。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'day' AS grain, period_grain AS input_grain, '{stat}' AS stat,
           {value_zero_column} AS value_zero, {value_lod_column} AS value_lod, {_AGG_TAIL_SELECT}
    FROM day_stats
    """


def _day_sum_expand_sql() -> str:
    # T4-2: variable.default_stat='sum' かつ (obs_stat IS NULL または
    # obs_stat='sum') の系列だけ sum の日次セルを足す。「最大値」等を宣言
    # している系列（obs_stat='max_10min' 等）には合計をかけない。
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'day' AS grain, period_grain AS input_grain, 'sum' AS stat,
           vz_sum AS value_zero, vl_sum AS value_lod, {_AGG_TAIL_SELECT}
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
# C-1: 以前は `cube_day`（`observation_agg` の日次セル全体、約4秒かけて丸ごと
# コピー）を経由して `stat='mean'` を絞り込んでいた。月次・年次の積み上げが
# 実際に使うのは `stat='mean'` の行だけ（月次は AVG(value) だけ、年次は
# AVG/MIN/MAX(value) のどれも「日次の平均」列に対する集計）なので、
# `cube_day` に丸ごとコピーする意味が無い。作業用テーブル（`staging`）を
# `WHERE grain='day' AND stat='mean'` で直接絞り込んで読む——この時点では
# まだ月次・年次の行を挿入していないので、`WHERE grain='day'` は「今ある
# 日次セルだけ」を正しく指す。`INSERT INTO staging SELECT ... FROM staging
# WHERE ...` という自己参照は SQLite が単一の SELECT 実行中は安定したスナップ
# ショットを読むため安全（挿入した 'month'/'year' 行が同じ WHERE 句に
# 再マッチすることはない。実測で確認済み）。
#
# ADR-0009 決定4: `value_zero`/`value_lod` それぞれを AVG() する
# （`AVG(value_lod)` は日次セルの `value_lod` が NULL の日〔100% ND の日〕を
# 自動的に無視する——SQL の集約関数の NULL 無視規則がそのまま「ND だけの
# 日次セルは月次平均から除外する」を実現する。特別扱いのコードは不要）。

def _month_from_day_sql(staging: str) -> str:
    return f"""
    SELECT {_DIM_SELECT},
           date(period_start, 'start of month') AS period_start,
           date(period_start, 'start of month', '+1 month', '-1 day') AS period_end,
           'month' AS grain, input_grain, 'mean' AS stat,
           AVG(value_zero) AS value_zero, AVG(value_lod) AS value_lod,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected,
           1 AS n_places, {_BUILT_FROM_SELECT}
    FROM "{staging}"
    WHERE grain = 'day' AND stat = 'mean'
    GROUP BY {_DIM_SELECT}, input_grain, date(period_start, 'start of month')
    """


def _year_from_day_stats_sql(staging: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, input_grain,
           date(period_start, 'start of year') AS period_start,
           date(period_start, 'start of year', '+1 year', '-1 day') AS period_end,
           AVG(value_zero) AS vz_mean, MIN(value_zero) AS vz_min, MAX(value_zero) AS vz_max,
           AVG(value_lod) AS vl_mean, MIN(value_lod) AS vl_min, MAX(value_lod) AS vl_max,
           COUNT(*) AS n, SUM(n_censored) AS n_censored, SUM(n_not_detected) AS n_not_detected
    FROM "{staging}"
    WHERE grain = 'day' AND stat = 'mean'
    GROUP BY {_DIM_SELECT}, input_grain, date(period_start, 'start of year')
    """


def _year_from_day_expand_sql(stat: str, value_zero_column: str, value_lod_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'year' AS grain, input_grain, '{stat}' AS stat,
           {value_zero_column} AS value_zero, {value_lod_column} AS value_lod, {_AGG_TAIL_SELECT}
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
           AVG(v_zero) AS vz_mean, MIN(v_zero) AS vz_min, MAX(v_zero) AS vz_max,
           AVG(v_lod) AS vl_mean, MIN(v_lod) AS vl_min, MAX(v_lod) AS vl_max,
           COUNT(*) AS n,
           {_CENSORED_COUNTS_SELECT}
    FROM obs_imputed
    WHERE period_grain = 'month' AND v_zero IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end
    """


def _month_source_expand_sql(stat: str, value_zero_column: str, value_lod_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           'month' AS grain, 'month' AS input_grain, '{stat}' AS stat,
           {value_zero_column} AS value_zero, {value_lod_column} AS value_lod, {_AGG_TAIL_SELECT}
    FROM month_source_stats
    """


def _year_source_stats_sql() -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end, period_grain,
           AVG(v_zero) AS vz_mean, MIN(v_zero) AS vz_min, MAX(v_zero) AS vz_max,
           AVG(v_lod) AS vl_mean, MIN(v_lod) AS vl_min, MAX(v_lod) AS vl_max,
           COUNT(*) AS n,
           {_CENSORED_COUNTS_SELECT}
    FROM obs_imputed
    WHERE period_grain IN ('year', 'fiscal_year') AND v_zero IS NOT NULL
    GROUP BY {_DIM_SELECT}, period_start, period_end, period_grain
    """


def _year_source_expand_sql(stat: str, value_zero_column: str, value_lod_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           period_grain AS grain, period_grain AS input_grain,
           '{stat}' AS stat,
           {value_zero_column} AS value_zero, {value_lod_column} AS value_lod, {_AGG_TAIL_SELECT}
    FROM year_source_stats
    """


# ---------------------------------------------------------------------------
# 次元キーの一意性検証（C-3）
# ---------------------------------------------------------------------------
# day/month(day側/出典側)/year(day側/出典側) の5経路は grain/input_grain/stat
# の値で互いに排他のはずだが、それが崩れていないことを実測で確認する。
#
# 以前は全13列の GROUP BY（約22秒）で確認していた。いまは作業用テーブルに
# 13列の `CREATE UNIQUE INDEX` を張ることで検証する——重複が無ければ索引の
# 作成が成功するだけで済み（実測 約12.9秒）、GROUP BY で全行を読み直すより
# 速い。実装（NULL の扱い・索引の使い捨て等）は `scripts/b07_build_occurrence_cube.py`
# とほぼ一字一句同じだったため、`scripts/migrate/common.assert_dimension_key_unique`
# に集約した（/simplify 指摘1）。ここでは `DIM_COLUMNS`・索引名・メッセージの
# 文言（b04 固有）だけを渡す薄い呼び出しにしてある。
_DIM_KEY_INDEX_NAME = "observation_agg_dim_key"


def _assert_dimension_key_unique(conn: sqlite3.Connection, staging: str) -> None:
    common.assert_dimension_key_unique(
        conn, staging, DIM_COLUMNS,
        index_name=_DIM_KEY_INDEX_NAME,
        table_label="observation_agg",
        cause_hint="day/month/year の集計経路が重なっている可能性がある。",
    )


# ---------------------------------------------------------------------------
# value_zero / value_lod の関係の検証（ADR-0009 決定4。モジュール docstring
# 「機械検証」節参照）
# ---------------------------------------------------------------------------

def _assert_value_zero_lod_invariants(conn: sqlite3.Connection, staging: str) -> dict:
    """`staging`（`staged_table` の作業用テーブル）に対して、`value_zero`/
    `value_lod` の3つの不変条件を検証する。戻り値はレポート用の実測件数
    （検証4）。いずれかが崩れていれば `common.MigrationError` で例外の
    サンプル行つきで止まる。
    """
    dim_cols = ", ".join(DIM_COLUMNS)

    bad1 = conn.execute(
        f'SELECT {dim_cols}, value_lod, n_not_detected, n FROM "{staging}" '
        "WHERE (value_lod IS NULL) != (n_not_detected = n) LIMIT 5"
    ).fetchall()
    if bad1:
        raise common.MigrationError(
            "observation_agg: value_lod IS NULL が n_not_detected=n と一致しない行がある"
            f"（例: {bad1}）。ADR-0009 決定4「value_lod は not_detected だけの格でのみ "
            "NULL になる」が崩れている。"
        )

    bad2 = conn.execute(
        f'SELECT {dim_cols}, value_zero, value_lod FROM "{staging}" '
        "WHERE n_censored = 0 AND n_not_detected = 0 AND value_lod IS NOT value_zero LIMIT 5"
    ).fetchall()
    if bad2:
        raise common.MigrationError(
            "observation_agg: 検閲を含まないセル（n_censored=0 AND n_not_detected=0）で "
            f"value_lod と value_zero がビット一致しない行がある（例: {bad2}）。"
            "ADR-0009 決定4「検閲の無いセルは両系列が同じ値」が崩れている。"
        )

    bad3 = conn.execute(
        f'SELECT {dim_cols}, value_zero, value_lod FROM "{staging}" '
        "WHERE value_zero IS NOT NULL AND value_lod IS NOT NULL AND value_lod < value_zero LIMIT 5"
    ).fetchall()
    if bad3:
        raise common.MigrationError(
            "observation_agg: value_lod が value_zero を下回るセルがある"
            f"（例: {bad3}）。censoring_limit は正のはずなので、両方が非 NULL な格の "
            "value_lod は value_zero 以上になるはず（below_lod の限界値が0以下、"
            "または符号の取り違えの疑い）。"
        )

    # `!=`（SQL の3値論理。NULL を含む比較は NULL＝真でも偽でもない）で数える
    # ——`value_lod IS NULL` の格（ND だけの格）は自動的にこのカウントから
    # 除外される。「IS NOT」（NULL-safe、NULL を「異なる」として数える）にすると
    # 両者の集合が重なってしまい、`n_value_lod_null` と足し合わせて報告する
    # 意味が無くなる（設計ブリーフ 検証4「重なり0」の前提）。
    n_value_lod_differs = conn.execute(
        f'SELECT COUNT(*) FROM "{staging}" WHERE value_lod != value_zero'
    ).fetchone()[0]
    n_value_lod_null = conn.execute(
        f'SELECT COUNT(*) FROM "{staging}" WHERE value_lod IS NULL'
    ).fetchone()[0]
    return {"n_value_lod_differs": n_value_lod_differs, "n_value_lod_null": n_value_lod_null}


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
    `observation_agg` 本体は `migrate.common.staged_table`（A-1）で作り直す
    ——検証（次元キーの一意性・`value_zero`/`value_lod` の関係）まで全部通って
    から本番名に差し替える。

    戻り値はレポート用の統計（経路ごとの行数・`value_zero`/`value_lod` の
    差分件数）。

    `AVG()`/`SUM()` を実行する前に `common.require_sqlite_version()` を呼ぶ
    （モジュール docstring「SQLite の版を守る」参照）。
    """
    common.require_sqlite_version()
    params = (built_from, spec_version)
    common.attach_readonly(conn, registry_db, "reg")
    conn.execute(_CREATE_OBS_IMPUTED_VIEW_SQL)

    with common.staged_table(conn, "observation_agg", _CREATE_OBSERVATION_AGG_SQL) as staging:
        insert_cols = ", ".join(
            DIM_COLUMNS
            + ["value_zero", "value_lod", "n", "n_censored", "n_not_detected", "n_places", "built_from", "spec_version"]
        )
        insert_sql = f'INSERT INTO "{staging}" ({insert_cols}) '

        # 日次（T4-2）。C-2: COUNT(*) を打ち直さず、直前の INSERT の
        # cursor.rowcount を積み上げて件数にする。
        common.replace_table(conn, "day_stats", f"CREATE TEMP TABLE day_stats AS {_day_stats_sql()}")
        n_day = 0
        for stat, vz_col, vl_col in _STAT_VALUE_COLUMNS:
            cur = conn.execute(insert_sql + _day_expand_sql(stat, vz_col, vl_col), params)
            n_day += cur.rowcount
        n_day += conn.execute(insert_sql + _day_sum_expand_sql(), params).rowcount

        # 月次（日次から積み上げ。C-1: cube_day を経由せず staging を直接読む）。
        n_month_from_day = conn.execute(insert_sql + _month_from_day_sql(staging), params).rowcount

        # 年次（日次から積み上げ）。mean/min/max を1本の GROUP BY でまとめて
        # 計算し、stat リテラルと対応する値列だけを変えた3本の INSERT に展開する。
        common.replace_table(
            conn, "year_from_day_stats",
            f"CREATE TEMP TABLE year_from_day_stats AS {_year_from_day_stats_sql(staging)}",
        )
        n_year_from_day = 0
        for stat, vz_col, vl_col in _STAT_VALUE_COLUMNS:
            cur = conn.execute(insert_sql + _year_from_day_expand_sql(stat, vz_col, vl_col), params)
            n_year_from_day += cur.rowcount

        # 月次（出典配布側。jma_monthly。年次の出典配布セルと対称）。
        common.replace_table(
            conn, "month_source_stats", f"CREATE TEMP TABLE month_source_stats AS {_month_source_stats_sql()}"
        )
        n_month_source = 0
        for stat, vz_col, vl_col in _STAT_VALUE_COLUMNS:
            cur = conn.execute(insert_sql + _month_source_expand_sql(stat, vz_col, vl_col), params)
            n_month_source += cur.rowcount

        # 年次（出典配布側）。
        common.replace_table(
            conn, "year_source_stats", f"CREATE TEMP TABLE year_source_stats AS {_year_source_stats_sql()}"
        )
        n_year_source = 0
        for stat, vz_col, vl_col in _STAT_VALUE_COLUMNS:
            cur = conn.execute(insert_sql + _year_source_expand_sql(stat, vz_col, vl_col), params)
            n_year_source += cur.rowcount

        # B-4: 一時テーブルの DROP をループに（cube_day は C-1 で無くなった）。
        for t in ("day_stats", "year_from_day_stats", "month_source_stats", "year_source_stats"):
            conn.execute(f'DROP TABLE IF EXISTS "{t}"')
        conn.execute("DROP VIEW IF EXISTS obs_imputed")

        # 次元キーが本当に一意か（同じキーの行が複数できていないか）を確認する
        # （C-3）。ここで失敗すれば staged_table が作業用テーブルを破棄し、
        # 前回の observation_agg がそのまま残る（A-1）。
        _assert_dimension_key_unique(conn, staging)
        # value_zero/value_lod の3つの不変条件（ADR-0009 決定4）。
        value_stats = _assert_value_zero_lod_invariants(conn, staging)

    return {
        "n_day": n_day,
        "n_month_from_day": n_month_from_day,
        "n_month_source": n_month_source,
        "n_year_from_day": n_year_from_day,
        "n_year_source": n_year_source,
        "n_total": n_day + n_month_from_day + n_month_source + n_year_from_day + n_year_source,
        **value_stats,
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
    # `--out` を `sqlite3.connect` で直接開く（`fresh_sqlite` を経由しない）ため、
    # ここで個別に検査する（`scripts/migrate/common.py` の
    # `reject_protected_source_db` の docstring 参照）。
    common.reject_protected_source_db(db_path)
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
    print(
        f"  value_zero/value_lod: 食い違うセル={stats['n_value_lod_differs']:,} / "
        f"value_lod が NULL のセル={stats['n_value_lod_null']:,}"
    )


if __name__ == "__main__":
    main()
