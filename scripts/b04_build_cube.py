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
`value_zero`/`value_lod` の2列に分ける**（次元キーは13列→12列）。理由は
本ファイルでは繰り返さず ADR-0009 決定4 を正とする。

## `value_lod` の代入規則（非対称に実装。規則は ADR-0009 決定2 参照）

below_lod は `value_zero` で 0、`value_lod` で `censoring_limit`。
not_detected は**どちらの系列でも**代入せず平均・MIN/MAX から除外する
（ADR-0009 決定2・2026-10-06追記参照）。ND はセルのメンバーとして
`n`/`n_not_detected` には数える。どちらの系列に何が入るか・`above_lod`/`unknown`
が非メンバーである理由は本ファイルでは繰り返さず ADR-0009 決定2 を正とする。
実装は「ND だけの格では `AVG` が NULL を返す」という一般形（`CASE WHEN censoring=
'not_detected' THEN NULL ELSE ... END` を `AVG`/`MIN`/`MAX` に渡すだけ）で
書き、**「ND を含むセルは全て 100% ND」という実データの性質には依存しない**
（この性質は機械検証にだけ使う）。

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

`censoring='below_lod'` が `censoring_limit` を必ず持つことは `observation`
自身の不変条件として `scripts/b03_build_observation.py`（T1 不変条件の検査）
が保証済み（/simplify 指摘2: 「検証は書き手の不変条件と消費者固有の前提を
分ける・書き手が1回だけ保証する」という既存の分担にならう。
`docs/plans/PHASE_B_FACT_SLICE.md` D11 の `site_zone_lookup` の節参照）。
b04 側では検証しない。

## 機械検証: `value_zero`/`value_lod` の関係（ADR-0009 決定4）

`_assert_dimension_key_unique` の直後、同じ `with staged_table(...)` ブロック
内で `_assert_value_zero_lod_invariants`（検証のみ・戻り値なし）を呼ぶ。
レポート用の実測件数（検証4）は別関数 `_collect_value_zero_lod_stats` が返す
（/code-review 指摘13: 検証と統計収集を1つの関数に混ぜると、検証を外したときに
戻り値のキーが黙って消える——両者は目的も呼び出しタイミングも別)。
破れれば `staged_table` が前回の `observation_agg` を残したまま止まる
（A-1 と同じ安全策）。

**「葉の格」と「積み上げの格」で条件が違う**（/code-review 指摘1）。
`_IS_LEAF_SQL`（`grain = 'day' OR grain = input_grain`）で判定する——day セルは
`grain='day'` で常に葉（`input_grain` が day/hour/instant のどれでも `obs_imputed`
から直接作るため）。月次・年次の出典配布セルは `grain = input_grain`
（= `period_grain`）。積み上げ（月次・年次を日次セルから作る側）だけが
`grain != 'day' AND grain != input_grain` になる（`input_grain` は日次セルの
`input_grain`=day/hour/instant を引き継ぐため、`'month'`/`'year'` である
`grain` と一致しない）。

1. **葉の格**: `(value_lod IS NULL) = (n_not_detected = n)`（`n`/`n_not_detected`
   がどちらも `obs_imputed`〔観測行〕の個数なので単位が揃っている）。
   **積み上げの格**: `n_not_detected = 0 ⇒ value_lod IS NOT NULL`
   （片方向のみ）。積み上げの格の `n` は寄与した**日次セルの個数**、
   `n_not_detected` はその日次セルたちの `n_not_detected` の**和**（観測行の
   個数）で単位が違うため、`n_not_detected = n` を直接比べられない
   （/code-review 指摘1。実データでは ND が全部 fiscal_year の出典配布行に
   限られ日次の積み上げに乗らないため、単位混在の等式でもたまたま通っていた
   ——指示書が禁じた「現データの性質への依存」そのものだった）。値そのものの
   性質（積み上げの `value_lod` は、寄与した日次セルの `value_lod` が
   **全部** NULL のときだけ NULL になる）から、単位を混ぜずに導ける条件は
   「ND 観測が1件も無ければ全ND日は存在しえない」という片方向の含意だけ
   ——逆方向（`value_lod IS NULL ⇒ n_not_detected=0` にならない、程度の
   弱い言明）は、日次セルごとの ND 充足状況を追加で持たないと判定できない
   （ADR-0009 決定4・2026-09-25追記参照）。
4. **全ての格で** `(value_zero IS NULL) = (value_lod IS NULL)`
   （ND は両系列で除外されるので NULL 性が一致する。検証1とは別の違反件数・メッセージ）。
2. `n_censored = 0` ⇒ `value_lod IS value_zero`（ビット一致。below_lod の無い
   セルでは代入の余地が無いので両系列は同じ値になるはず。
   day_stats/month_source_stats/year_source_stats がどちらも同じ `GROUP BY` の
   1パスで `AVG(v_zero)`/`AVG(v_lod)` 等を並べて計算しており、加算順序は自動的に
   揃っている。積み上げの格でも同じ列を同じ順序で `AVG` するだけなのでビット
   一致が伝播する）。
3. **全てのセルで**、両方が非 NULL ⇒ `value_lod >= value_zero`。ND は両系列で
   除外され、両系列の差は below_lod の 0 → `censoring_limit`（正）だけなので、
   他のメンバーの符号によらず成り立つ。

## 単位の証拠検査（Issue #48 PR-1b §3.7、D3。危険#5「単位」の機械検証）

`registry/variable_alias.csv` の `unit_id` は「原本の `unit`（`unit_raw`）とレジストリの
`unit.symbol` が一致することを実測した」行だけを埋める、というのが D3 の受け入れ条件
（`docs/plans/V2_SERVING_PR1.md` D3。measurements データセットの alias 38行。流量の
1alias は原本にも単位が無いため NULL のまま）。`observation` は `unit_id`/`unit_raw` の
**両方**を持つ唯一の段（`observation_agg` は `unit_raw` を持たない。本ファイル冒頭の
「unit_raw をキューブに持たない」節参照）なので、この前提を機械的に検証できるのは
ここ（b04）だけ。`build_cube()` の先頭、ATTACH 直後に `_assert_unit_evidence()` を呼ぶ:

1. `source_table='measurements'` かつ `unit_id IS NOT NULL` の行はすべて `unit_raw` が
   `reg.unit.symbol` と一致すること（不一致0件）。D3 が実測に基づいて埋めたという
   前提が崩れていないかの回帰ガード。`measurements` に限るのは D3 の受け入れ条件
   自体が「measurements の alias 38行」だけを対象にしたため——`sensor_timeseries`
   は raw の表記ゆれ（例: "μg/m3" vs registry の symbol "ug/m3"）という別の既知の
   問題（実測48,489件）を抱えており、混ぜると検査が役に立たなくなる。
2. `unit_id IS NULL AND unit_raw IS NOT NULL`（＝原本に単位はあるのにレジストリが
   まだ解決していない）行を `(source_table, variable_id, obs_stat, value_grain)` 単位で
   集計し、`scripts/migrate/unit_evidence_declarations.yaml` の宣言と**集合として**
   一致すること。宣言に無い新しい欠落（未解決のまま増えた分）だけでなく、宣言はあるが
   実データからは消えた分（解決済みなのに宣言を消し忘れている）も検出する
   （CLAUDE.md「宣言済み差分 > データを曲げる」——ゲートを緑にするために宣言を
   増やし続けるのではなく、宣言が腐ったら止める）。

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
import hashlib
import math
import pathlib
import random
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import censoring, common, cube_invariants, period  # noqa: E402

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
# セルのメンバー（`n` に数える観測）: v_zero が非 NULL の行に加え、ND の行
# （v_zero も v_lod も NULL。平均・MIN/MAX には入らないが、`n`/`n_not_detected`
# には数える。ND だけの格は value_zero/value_lod が両方 NULL になる）。
# above_lod/unknown の値無し行は非メンバー。
_MEMBER_SQL = f"(v_zero IS NOT NULL OR censoring = '{censoring.CENSORING_NOT_DETECTED}')"
_CREATE_OBS_IMPUTED_VIEW_SQL = f"""
CREATE TEMP VIEW obs_imputed AS
SELECT *,
       CASE WHEN censoring IN ({_ZERO_IMPUTED_IN_CLAUSE}) THEN 0.0
            WHEN censoring = '{censoring.CENSORING_NOT_DETECTED}' THEN NULL
            ELSE value_num END AS v_zero,
       {_VALUE_LOD_CASE} AS v_lod
FROM observation
"""

# 期間（period_start）より前の次元列（region_id..value_grain の7列）。`DIM_COLUMNS` から導く。
_PRE_PERIOD_DIM_COLUMNS = DIM_COLUMNS[: DIM_COLUMNS.index("period_start")]
_DIM_SELECT = ", ".join(_PRE_PERIOD_DIM_COLUMNS)

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
# セルのメンバーは `_MEMBER_SQL`（`v_zero IS NOT NULL` の行に加え、値を持たない
# not_detected の行。above_lod/unknown の値無し行は非メンバー）で決める。
# `value_zero`/`value_lod` は「どちらの系列も同じセルのメンバー」
# （ADR-0009 決定4 決定1）で、ND は `n`/`n_not_detected` には数えるが
# AVG/MIN/MAX/SUM には入らない（両系列とも NULL）。

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
    WHERE period_grain IN ('day', 'hour', 'instant') AND {_MEMBER_SQL}
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
    WHERE period_grain = 'month' AND {_MEMBER_SQL}
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
    WHERE period_grain IN ('year', 'fiscal_year') AND {_MEMBER_SQL}
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
# 年次・年度（月に復元した観測から、宣言した粒度へ積み上げる側。Issue #32-2）
# ---------------------------------------------------------------------------
# **宣言駆動**: `period_exceptions.yaml` の復元エントリが `rollup_to: [fiscal_year]` と宣言した粒度
# だけ作る（`period.declared_rollup_grains`）。何も宣言が無ければ何も作らない——jma_monthly のように
# 出典が月で配った値（`value_grain='month'`）は積み上げない（月値の平均の平均が年値として現れない）。
# 対象の行は「値は日間平均なのに日付が月までしか言えない」観測
# （`period_grain='month' AND value_grain<>'month'`。b03 が宣言に従って復元した行がこれに当たる）。
# 暦年（`year`）への積み上げは、両端が3か月・9か月の部分年になり、出典が配った粒度でもないため、
# 宣言が無い限り作らない。
#
# **観測の行から直接再集計する**（月セルの平均の平均にしない）。メンバー・検閲・n の規則は日次→年次
# （出典配布セル）と同じ（`_MEMBER_SQL`・`_CENSORED_COUNTS_SELECT`）: n はメンバーの観測行の個数、
# 欠月は n に現れる（数えないだけで、補完しない）。`input_grain='month'` を保つので、`grain=input_grain`
# の出典配布セル（`_cell_mode` の _MODE_SOURCE）とも、`input_grain='day'` の積み上げとも区別できる。
# 日付は文字列の切り出しだけで作る（日時関数を使わない。ADR-0024）。

# 月に復元した日間平均値（積み上げの対象行）。`cube_invariants.verify_month_year_rollup` が同じ規則を
# Python で独立に書き直している。
_ROLLUP_SOURCE_SQL = "period_grain = 'month' AND value_grain <> 'month'"


def _fiscal_start_year_sql(column: str = "period_start") -> str:
    """`column`（`YYYY-MM-DD` の文字列列）が属する年度の始まりの年（4月始まり）を返す SQL 式。
    `_year_from_month_stats_sql` と無作為抽出の結合キー（`_skey_sql`）が共有する。"""
    return (
        f"CASE WHEN CAST(substr({column}, 6, 2) AS INTEGER) >= 4 "
        f"THEN CAST(substr({column}, 1, 4) AS INTEGER) "
        f"ELSE CAST(substr({column}, 1, 4) AS INTEGER) - 1 END"
    )


def _year_from_month_stats_sql(grain: str) -> str:
    if grain == "year":
        start = "substr(period_start, 1, 4) || '-01-01'"
        end = "substr(period_start, 1, 4) || '-12-31'"
        key = "substr(period_start, 1, 4)"
    elif grain == "fiscal_year":
        fiscal = _fiscal_start_year_sql()
        start = f"printf('%04d', {fiscal}) || '-04-01'"
        end = f"printf('%04d', {fiscal} + 1) || '-03-31'"
        key = fiscal
    else:
        raise common.MigrationError(f"_year_from_month_stats_sql: 想定外の grain {grain!r}")
    return f"""
    SELECT {_DIM_SELECT}, {start} AS period_start, {end} AS period_end,
           '{grain}' AS grain,
           AVG(v_zero) AS vz_mean, MIN(v_zero) AS vz_min, MAX(v_zero) AS vz_max,
           AVG(v_lod) AS vl_mean, MIN(v_lod) AS vl_min, MAX(v_lod) AS vl_max,
           COUNT(*) AS n,
           {_CENSORED_COUNTS_SELECT}
    FROM obs_imputed
    WHERE {_ROLLUP_SOURCE_SQL} AND {_MEMBER_SQL}
    GROUP BY {_DIM_SELECT}, {key}
    """


def _year_from_month_expand_sql(stat: str, value_zero_column: str, value_lod_column: str) -> str:
    return f"""
    SELECT {_DIM_SELECT}, period_start, period_end,
           grain, 'month' AS input_grain, '{stat}' AS stat,
           {value_zero_column} AS value_zero, {value_lod_column} AS value_lod, {_AGG_TAIL_SELECT}
    FROM year_from_month_stats
    """


# ---------------------------------------------------------------------------
# 次元キーの一意性検証（C-3）
# ---------------------------------------------------------------------------
# day/month(day側/出典側)/year(day側/出典側) の5経路は grain/input_grain/stat
# の値で互いに排他のはずだが、それが崩れていないことを実測で確認する。
#
# 以前は全13列（現在は `imputation` を外した12列。ADR-0009 決定4）の
# GROUP BY（約22秒）で確認していた。いまは作業用テーブルに
# `DIM_COLUMNS`（12列）の `CREATE UNIQUE INDEX` を張ることで検証する——重複が無ければ索引の
# 作成が成功するだけで済み（実測 約12.9秒）、GROUP BY で全行を読み直すより
# 速い。実装（NULL の扱い・索引の使い捨て等）は `scripts/b07_build_occurrence_cube.py`
# とほぼ一字一句同じだったため、`scripts/migrate/common.assert_dimension_key_unique`
# に集約した（/simplify 指摘1）。ここでは `DIM_COLUMNS`・索引名・メッセージの
# 文言（b04 固有）だけを渡す薄い呼び出しにしてある。
_DIM_KEY_INDEX_NAME = "observation_agg_dim_key"

# Issue #48 PR-1 §1: `observation_agg` に張る永続索引。名前・列・列順は
# Drizzle（`web/src/db/schema-cube.ts` → `web/drizzle/migrations/0005_overrated_venom.sql`）
# が正——ここは写し。`scripts/tests/test_cube_index_parity.py` がマイグレーション SQL から
# 抜いた集合とこの定数の一致を機械検証するので、手で同期を保つ必要はない
# （ずれれば次の pytest 実行で落ちる）。`build_cube()` が `common.create_indexes()` 経由で
# `staged_table` の差し替え確定後に張る（`create_indexes` docstring 参照——
# 作業用テーブル段階で張ると2回目の実行が名前衝突を起こす）。
OBSERVATION_AGG_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_observation_agg_variable_place_grain_stat_period",
     ("variable_id", "place_id", "grain", "stat", "period_start")),
    ("ix_observation_agg_place_variable_grain", ("place_id", "variable_id", "grain")),
)


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

# 「葉の格」（obs_imputed から直接作る格）の判定式。day セルは grain='day'
# （常に葉——input_grain が day/hour/instant のどれでも葉）。月次・年次の
# 出典配布セルは grain=input_grain（=period_grain）。積み上げ（月次・年次を
# 日次セルから作る側）だけが grain != 'day' かつ grain != input_grain になる
# （モジュール docstring「機械検証」節参照）。
_IS_LEAF_SQL = "(grain = 'day' OR grain = input_grain)"

# 検証1: 葉の格では単位が揃った等式、積み上げの格では単位を混ぜない片方向の
# 含意だけを課す（/code-review 指摘1）。value_zero も ND を
# 除外するので、`value_zero IS NULL` と `value_lod IS NULL` は全ての格で一致する
# （葉・積み上げどちらでも。ND だけの格で両方 NULL、それ以外は両方非 NULL）。
_CHECK1_LEAF_VIOLATION_SQL = f"({_IS_LEAF_SQL} AND (value_lod IS NULL) != (n_not_detected = n))"
_CHECK1_ROLLUP_VIOLATION_SQL = f"(NOT {_IS_LEAF_SQL} AND n_not_detected = 0 AND value_lod IS NULL)"
_CHECK1_VIOLATION_SQL = f"({_CHECK1_LEAF_VIOLATION_SQL} OR {_CHECK1_ROLLUP_VIOLATION_SQL})"

# NULL 性の検証: value_zero と value_lod の NULL 性は全ての格で一致する。
_CHECK_NULL_MATCH_VIOLATION_SQL = "((value_zero IS NULL) != (value_lod IS NULL))"

# 検証2: 下限未満（below_lod）の無いセル（葉・積み上げどちらも）は両系列がビット
# 一致するはず。両系列が違うのは below_lod の代入値（0 か censoring_limit）だけ。
_CHECK2_VIOLATION_SQL = "(n_censored = 0 AND value_lod IS NOT value_zero)"

# 検証3: 全てのセルで value_lod >= value_zero（ND は両系列で除外されるので
# 分母・分子の構成が揃い、違いは below_lod の 0 → censoring_limit（正）だけ。モジュール docstring「機械検証」節参照）。
_CHECK3_VIOLATION_SQL = (
    "(value_zero IS NOT NULL AND value_lod IS NOT NULL AND value_lod < value_zero)"
)


def _assert_value_zero_lod_invariants(conn: sqlite3.Connection, staging: str) -> None:
    """`staging`（`staged_table` の作業用テーブル）に対して、`value_zero`/
    `value_lod` の不変条件（検証1〜3と NULL 性の検証）を検証する（検証のみ。レポート用の実測件数は
    `_collect_value_zero_lod_stats` が別に返す——/code-review 指摘13: 検証と
    統計収集を1つの関数に混ぜると、検証を外したときに戻り値のキーが黙って
    消える）。いずれかが崩れていれば `common.MigrationError` で例外の
    サンプル行つきで止まる。

    3つの違反条件を1回の SELECT でまとめて数える（/code-review 指摘12:
    以前は LIMIT 5 の探索クエリを3本、200万行を3回スキャンしていた）。
    違反が1件も無ければこの1クエリだけで終わる——サンプル行を取るための
    2つ目のクエリは、実際に違反があった検証についてだけ実行する。
    """
    n_bad1, n_bad2, n_bad3, n_bad_null = conn.execute(
        f"""
        SELECT
          SUM(CASE WHEN {_CHECK1_VIOLATION_SQL} THEN 1 ELSE 0 END),
          SUM(CASE WHEN {_CHECK2_VIOLATION_SQL} THEN 1 ELSE 0 END),
          SUM(CASE WHEN {_CHECK3_VIOLATION_SQL} THEN 1 ELSE 0 END),
          SUM(CASE WHEN {_CHECK_NULL_MATCH_VIOLATION_SQL} THEN 1 ELSE 0 END)
        FROM "{staging}"
        """
    ).fetchone()

    dim_cols = ", ".join(DIM_COLUMNS)

    if n_bad1:
        bad1 = conn.execute(
            f'SELECT {dim_cols}, grain, input_grain, value_lod, n_not_detected, n FROM "{staging}" '
            f"WHERE {_CHECK1_VIOLATION_SQL} LIMIT 5"
        ).fetchall()
        raise common.MigrationError(
            "observation_agg: value_lod IS NULL の条件が崩れている行がある"
            f"（例: {bad1}）。葉の格（grain='day' または grain=input_grain）では "
            "value_lod IS NULL は n_not_detected=n（ND だけの格）と一致するはず。"
            "積み上げの格（月次・年次を日次セルから作る側）は n（日次セルの個数）と "
            "n_not_detected（観測行の個数）の単位が違うため同じ式は使えず、"
            "n_not_detected=0 ならば value_lod は NULL にならない、という片方向の"
            "条件だけを課している——それが崩れている。"
        )
    if n_bad2:
        bad2 = conn.execute(
            f'SELECT {dim_cols}, value_zero, value_lod FROM "{staging}" '
            f"WHERE {_CHECK2_VIOLATION_SQL} LIMIT 5"
        ).fetchall()
        raise common.MigrationError(
            "observation_agg: below_lod を含まないセル（n_censored=0）で "
            f"value_lod と value_zero がビット一致しない行がある（例: {bad2}）。"
            "ADR-0009 決定4「below_lod の無いセルは両系列が同じ値」が崩れている。"
        )
    if n_bad3:
        bad3 = conn.execute(
            f'SELECT {dim_cols}, value_zero, value_lod, n_censored FROM "{staging}" '
            f"WHERE {_CHECK3_VIOLATION_SQL} LIMIT 5"
        ).fetchall()
        raise common.MigrationError(
            "observation_agg: value_lod が value_zero を下回る行がある"
            f"（例: {bad3}）。censoring_limit は正で、ND は両系列で除外されるので、"
            "他のメンバーの符号によらず value_lod は value_zero 以上になるはず"
            "（below_lod の限界値が0以下、または符号の取り違えの疑い。ADR-0009 決定4・"
            "2026-10-06追記参照）。"
        )
    if n_bad_null:
        bad_null = conn.execute(
            f'SELECT {dim_cols}, value_zero, value_lod, n, n_not_detected FROM "{staging}" '
            f"WHERE {_CHECK_NULL_MATCH_VIOLATION_SQL} LIMIT 5"
        ).fetchall()
        raise common.MigrationError(
            "observation_agg: value_zero と value_lod の NULL 性が食い違う行がある"
            f"（例: {bad_null}）。ND は両系列で除外されるので、どの格でも片方だけ NULL に"
            "なることはない（ADR-0009 決定2・2026-10-06追記参照）。"
        )


def _collect_value_zero_lod_stats(conn: sqlite3.Connection, staging: str) -> dict:
    """レポート用の実測件数（検証4）を返す。検証（`_assert_value_zero_lod_invariants`）
    とは別関数にする（/code-review 指摘13）。2つの COUNT を1回の SELECT に
    まとめる（/code-review 指摘12）。

    `!=`（SQL の3値論理。NULL を含む比較は NULL＝真でも偽でもない）で数える
    ——`value_lod IS NULL` の格（ND だけの格）は自動的にこのカウントから
    除外される。「IS NOT」（NULL-safe、NULL を「異なる」として数える）にすると
    両者の集合が重なってしまい、`n_value_lod_null` と足し合わせて報告する
    意味が無くなる（設計ブリーフ 検証4「重なり0」の前提）。
    """
    n_value_lod_differs, n_value_lod_null = conn.execute(
        f'SELECT SUM(value_lod != value_zero), SUM(value_lod IS NULL) FROM "{staging}"'
    ).fetchone()
    return {
        "n_value_lod_differs": n_value_lod_differs or 0,
        "n_value_lod_null": n_value_lod_null or 0,
    }


# ---------------------------------------------------------------------------
# 単位の証拠検査（Issue #48 PR-1b §3.7、D3。モジュール docstring
# 「単位の証拠検査」節参照）
# ---------------------------------------------------------------------------

UNIT_EVIDENCE_DECLARATIONS_YAML = ROOT / "scripts" / "migrate" / "unit_evidence_declarations.yaml"
PERIOD_EXCEPTIONS_YAML = period.DEFAULT_EXCEPTIONS_YAML


def _load_unit_evidence_declarations(path=UNIT_EVIDENCE_DECLARATIONS_YAML) -> set[tuple]:
    doc = common.load_yaml(path)
    entries = doc.get("declared") or []
    return {
        (e["source_table"], e["variable_id"], e.get("obs_stat"), e["value_grain"])
        for e in entries
    }


def _assert_unit_evidence(conn: sqlite3.Connection, declarations_path=UNIT_EVIDENCE_DECLARATIONS_YAML) -> dict:
    """`observation`（`unit_id`/`unit_raw` を両方持つ唯一の段）に対する単位の証拠を
    検証する（D3、モジュール docstring「単位の証拠検査」節参照）。`conn` は
    `reg`（registry.sqlite）が ATTACH 済みであること。戻り値はレポート用の実測件数。

    **`reg.unit` テーブルが無ければ止まる**（Issue #48 PR-1 §4。以前はここで
    黙って素通りしていたため、`unit` を持たない縮小フィクスチャ
    （`scripts/tests/migrate_fixtures.py` の `make_registry_db()`）を使うテストは
    この検証（検証1・検証2とも）を一度も実行しないまま緑になっていた——
    `scripts/tests/test_b04_build_cube.py` の該当節で発見。本物の `registry.sqlite`
    は `scripts/registry/build_unit_variable.py` が必ず `unit` を作るので実運用では
    元々このエラーに当たらない。`make_registry_db()` は既定で `unit` を持つ
    （`DEFAULT_UNITS`）ので、テストも通常はここで止まらない）。検証1
    （symbol 不一致）は `reg.unit` さえあれば常に行う。

    `declarations_path=None`: 検証2（宣言されていない欠落／宣言の腐り）だけを
    丸ごとスキップする（検証1は上記のとおり常に行う）。本物の宣言 YAML
    （`UNIT_EVIDENCE_DECLARATIONS_YAML`）は実データ全体を前提にした宣言なので、
    それとは無関係な小さな合成フィクスチャで `build_cube()` を呼ぶだけの
    一般テストが「本物の宣言と自分のフィクスチャの中身が食い違う」で落ちるのを
    避けるための逃げ道。`build_cube()` はこの値を `unit_evidence_declarations_path`
    引数としてそのまま受け取り、テストは呼び出しごとに明示的に `None` を渡す
    （`build_cube()` の docstring 参照。Issue #48 PR-1 §4: 以前は
    `scripts/tests/conftest.py` の autouse フィクスチャが `UNIT_EVIDENCE_DECLARATIONS_YAML`
    をモジュールグローバルごと monkeypatch していたが、本番の `main()` が
    引数を渡し忘れても検査が黙って消えない設計に直すため引数化した）。
    単位の証拠検査そのものを検証するテスト（`test_b04_build_cube.py` の
    該当節）は常に実在する宣言ファイルを明示的に渡すので、この分岐には
    入らない。
    """
    common.assert_attached_table_exists(
        conn, "reg", "unit",
        hint="registry.sqlite に unit が無い。scripts/registry/build_unit_variable.py で作り直すこと"
        "（テストなら scripts/tests/migrate_fixtures.make_registry_db の units 引数で持たせること）。",
    )

    # 検証1は `measurements` データセットに限る（D3 の受け入れ条件・実測が
    # 「measurements の alias 38行」だけを対象にしたため）。`sensor_timeseries` は
    # 別の既知の問題（symbol の表記ゆれ。例: raw "μg/m3" vs registry symbol
    # "ug/m3"、"0.1%" の全角/半角違い等。実測で 48,489 件、モジュール docstring
    # §9-5 相当・設計書 D3 の対象外）を抱えており、ここに混ぜると D3 と無関係な
    # 大量の不一致で検査そのものが役に立たなくなる。
    n_mismatch = conn.execute(
        """
        SELECT COUNT(*) FROM observation o
        JOIN reg.unit u ON u.unit_id = o.unit_id
        WHERE o.unit_raw IS NOT NULL AND o.unit_raw <> u.symbol
          AND o.source_table = 'measurements'
        """
    ).fetchone()[0]
    if n_mismatch:
        sample = conn.execute(
            """
            SELECT o.source_table, o.variable_id, o.unit_id, o.unit_raw, u.symbol
            FROM observation o
            JOIN reg.unit u ON u.unit_id = o.unit_id
            WHERE o.unit_raw IS NOT NULL AND o.unit_raw <> u.symbol
              AND o.source_table = 'measurements'
            LIMIT 5
            """
        ).fetchall()
        raise common.MigrationError(
            f"observation（source_table='measurements'）: unit_id が埋まっている行の "
            f"unit_raw が registry の unit.symbol と一致しない行が {n_mismatch:,} 件ある"
            f"（例: {sample}）。D3（registry/variable_alias.csv の unit_id は実測した"
            "一致だけを埋める）の前提が崩れている。"
        )

    # 検査3は宣言 YAML の有無（declarations_path）と無関係に必ず走る。
    n_basis = _assert_unit_basis_evidence(conn)

    if declarations_path is None:
        return {"n_unit_symbol_mismatch": n_mismatch, "n_unit_evidence_declared": 0, "n_unit_basis_series": n_basis}

    rows = conn.execute(
        """
        SELECT DISTINCT source_table, variable_id, obs_stat, value_grain
        FROM observation
        WHERE unit_id IS NULL AND unit_raw IS NOT NULL
        """
    ).fetchall()
    actual = {(r[0], r[1], r[2], r[3]) for r in rows}
    declared = _load_unit_evidence_declarations(declarations_path)

    missing = actual - declared
    stale = declared - actual
    if missing or stale:
        # tuple の要素（obs_stat 等）に None と str が混在しうるため、文字列化してから
        # ソートする（素の `sorted()` は比較不能で `TypeError` になりうる——エラー経路
        # 自体が別の例外で落ちると原因が分かりにくくなる）。
        if missing:
            missing_str = sorted(str(t) for t in missing)
        if stale:
            stale_str = sorted(str(t) for t in stale)
        parts = []
        if missing:
            parts.append(
                f"宣言されていない欠落（unit_id NULL かつ unit_raw NOT NULL）が "
                f"{len(missing):,} 系列ある: {missing_str}。"
                f"{declarations_path} に列挙するか、registry/variable_alias.csv の "
                "unit_id を実測に基づいて埋めて解決すること（推測で埋めない）。"
            )
        if stale:
            parts.append(
                f"{declarations_path} に宣言があるが実データにはもう存在しない"
                f"（解決済みの）系列が {len(stale):,} 件ある: {stale_str}。"
                "宣言を削除すること（宣言済み差分の腐り——CLAUDE.md「宣言済み差分 > "
                "データを曲げる」）。"
            )
        raise common.MigrationError(" / ".join(parts))

    return {
        "n_unit_symbol_mismatch": n_mismatch,
        "n_unit_evidence_declared": len(declared),
        "n_unit_basis_series": n_basis,
    }


def _assert_unit_basis_evidence(conn: sqlite3.Connection) -> int:
    """検査3（Issue #31）: `variable_alias.unit_basis`（単位の根拠の宣言）と `observation` の実態の一致。

    `unit_basis='registry'` は「原本に単位の記載が無く（`unit_raw IS NULL`）レジストリが補った」、
    `'source'` は「原本が単位を報告している（`unit_raw IS NOT NULL`）」。AI がこの区別を根拠として
    ユーザーに語るので、宣言が実態とずれたまま黙って通さない。

    観測は alias を持たないので `(dataset, variable_id, unit_id)` 単位で突き合わせる（dataset は
    `observation.source_table`。土地利用の alias は `<table>@<年>` なので `@` 以降を落として比べる）。
    出典ごとに逆の宣言をしても、同じ組に対する宣言として個別に検証される:
    - 実データにある (dataset, variable_id, unit_id, basis) が宣言されていなければ止まる（宣言漏れ）。
    - 宣言された basis が、同じ (dataset, variable_id, unit_id) の実データに1行も無ければ止まる
      （宣言の腐り。その組が実データに全く無い合成専用 alias は対象外）。
    戻り値は突き合わせた (dataset, variable_id, unit_id) の数。

    reg.variable_alias に unit_basis 列が無ければ SQLite が OperationalError で止まる
    （registry は schema_registry.sql から作られ、鮮度は r01 の指紋が担保するので個別の列検査はしない）。
    """
    actual = {
        (t, v, u, "source" if has_raw else "registry")
        for t, v, u, has_raw in conn.execute(
            "SELECT source_table, variable_id, unit_id, unit_raw IS NOT NULL FROM observation "
            "WHERE unit_id IS NOT NULL GROUP BY 1, 2, 3, 4"
        )
    }
    declared = {
        (d.split("@", 1)[0] if d else d, v, u, b)
        for d, v, u, b in conn.execute(
            "SELECT DISTINCT dataset, variable_id, unit_id, unit_basis FROM reg.variable_alias WHERE unit_id IS NOT NULL"
        )
    }
    keys = {a[:3] for a in actual}
    missing = actual - declared
    stale = {d for d in declared if d[:3] in keys and d not in actual}
    if missing or stale:
        parts = []
        if missing:
            parts.append(
                f"実データにあるが variable_alias.unit_basis に宣言が無い (dataset, variable_id, unit_id, basis) が "
                f"{len(missing):,} 組: {sorted(missing, key=str)[:10]}"
            )
        if stale:
            parts.append(
                f"unit_basis の宣言があるが実データに該当行が無い組が {len(stale):,}: {sorted(stale, key=str)[:10]}"
            )
        raise common.MigrationError(
            " / ".join(parts) + "。registry/variable_alias.csv の unit_basis を実測に基づいて直すこと（推測で埋めない）。"
        )
    return len(keys)


# ---------------------------------------------------------------------------
# 無作為抽出セルの独立再計算（Issue #48 PR-5 §2.3。モジュール docstring
# 「機械検証」節の補足）
# ---------------------------------------------------------------------------
# v1 との突合（b02）が無くなった後の「キューブの値は観測から正しく作られているか」の
# 検査。`staging` のセルを層別に無作為抽出し、`observation` の該当行から Python
# （`math.fsum`）で値を求め直して比べる。**SQL の式（`_day_stats_sql` 等）を使い回さない**
# ——同じ式の同じバグを見逃すため、集計の規則だけを読んで別の書き方で組んである。
# 欠落セル（観測にはあるのにキューブに無い）は抽出の対象外（見るのは「あるセルの値」）。

SAMPLE_CELLS_PER_STRATUM = 200
SAMPLE_CENSORED_CELLS_PER_STRATUM = 50

# セルが観測のどの行から作られるか（`_cell_mode`）。`plen` は日付の先頭何文字で
# 同じセルに入れるか（None は period_start/period_end の完全一致）。
_MODE_DAY, _MODE_MONTH_FROM_DAY, _MODE_YEAR_FROM_DAY, _MODE_SOURCE = "day", "month_from_day", "year_from_day", "source"
# Issue #32-2: 月で配られた観測から直接積み上げた年（暦年）・年度のセル。
_MODE_YEAR_FROM_MONTH, _MODE_FISCAL_FROM_MONTH = "year_from_month", "fiscal_from_month"
_MODE_PREFIX_LEN = {
    _MODE_DAY: 10, _MODE_MONTH_FROM_DAY: 7, _MODE_YEAR_FROM_DAY: 4, _MODE_SOURCE: None,
    _MODE_YEAR_FROM_MONTH: 4, _MODE_FISCAL_FROM_MONTH: 4,
}

_KEY_SEP = "\x1f"
_KEY_NULL = "\x1e"


def _cell_mode(grain: str, input_grain: str) -> str:
    if grain == "day":
        return _MODE_DAY
    if input_grain == "month" and grain == "year":
        return _MODE_YEAR_FROM_MONTH
    if input_grain == "month" and grain == "fiscal_year":
        return _MODE_FISCAL_FROM_MONTH
    if grain == input_grain:  # 出典配布セル（month/year/fiscal_year）
        return _MODE_SOURCE
    if grain == "month":
        return _MODE_MONTH_FROM_DAY
    if grain == "year":
        return _MODE_YEAR_FROM_DAY
    raise common.MigrationError(f"observation_agg: 想定外の (grain, input_grain)=({grain!r}, {input_grain!r})")


def _sample_seed(observation_fingerprint: str, spec_version: str) -> int:
    """入力が同じなら同じ抽出（決定論）、入力が変われば別の抽出になる seed。"""
    return int(hashlib.sha256(f"{observation_fingerprint}|{spec_version}".encode()).hexdigest()[:8], 16)


def _pick_sample_rowids(conn: sqlite3.Connection, staging: str, seed: int) -> list[int]:
    """層（grain, input_grain, stat）ごとに、無作為の最大 `SAMPLE_CELLS_PER_STRATUM` セルと
    n が最大のセル1つ・検閲を含むセル（最大 `SAMPLE_CENSORED_CELLS_PER_STRATUM`）を選ぶ。"""
    rng = random.Random(seed)
    rowids: dict[tuple, list[int]] = {}
    best_n: dict[tuple, tuple[int, int]] = {}
    censored: dict[tuple, list[int]] = {}
    for rowid, grain, input_grain, stat, n, n_censored, n_nd in conn.execute(
        f'SELECT rowid, grain, input_grain, stat, n, n_censored, n_not_detected FROM "{staging}"'
    ):
        stratum = (grain, input_grain, stat)
        rowids.setdefault(stratum, []).append(rowid)
        if stratum not in best_n or n > best_n[stratum][0]:
            best_n[stratum] = (n, rowid)
        if n_censored or n_nd:
            censored.setdefault(stratum, []).append(rowid)
    picked: set[int] = set()
    for stratum in sorted(rowids):  # 層の順序を固定して抽出を決定論にする
        ids = rowids[stratum]
        picked.update(rng.sample(ids, min(len(ids), SAMPLE_CELLS_PER_STRATUM)))
        picked.add(best_n[stratum][1])
        cens = censored.get(stratum, [])
        picked.update(rng.sample(cens, min(len(cens), SAMPLE_CENSORED_CELLS_PER_STRATUM)))
    return sorted(picked)


def _imputed(censoring_value, value_num, censoring_limit) -> tuple:
    """**独立再計算のための意図的な重複**: 本体の集計 SQL（`_VALUE_LOD_CASE` など）と同じ規則を
    別の書き方で再実装している（同じ式の同じバグを見逃さないため。共通化しない）。
    観測1行の (value_zero 側, value_lod 側)。規則は ADR-0009 決定2（モジュール docstring）。
    v_zero/v_lod がどちらも None の行は値を持たない（ND は集計から除外するがセルのメンバー。
    above_lod/unknown で値が無いものは非メンバー）。"""
    if censoring_value in censoring.ZERO_IMPUTED_CENSORING:
        v_zero = 0.0
    elif censoring_value == censoring.CENSORING_NOT_DETECTED:
        v_zero = None  # ND は value_zero でも除外（メンバーではあるが値は無い）
    else:
        v_zero = value_num
    if censoring_value == censoring.CENSORING_BELOW_LOD:
        v_lod = censoring_limit
    elif censoring_value == censoring.CENSORING_NOT_DETECTED:
        v_lod = None
    else:
        v_lod = value_num
    return v_zero, v_lod


def _stat_of(values: list[float], stat: str):
    """**独立再計算のための意図的な重複**（`_imputed` と同じ理由。本体の SQL 集計と共通化しない）。
    `values`（None を除いたリスト）の mean/min/max/sum。空なら None。"""
    if not values:
        return None
    if stat == "mean":
        return math.fsum(values) / len(values)
    if stat == "min":
        return min(values)
    if stat == "max":
        return max(values)
    if stat == "sum":
        return math.fsum(values)
    raise common.MigrationError(f"observation_agg: 想定外の stat {stat!r}")


def _group_stats(obs_rows: list[tuple], stat: str) -> tuple:
    """観測行（(censoring, value_num, censoring_limit)）の集まりから、1つの葉の格の
    (value_zero, value_lod, n, n_censored, n_not_detected) を求める（日次セルと出典配布セル）。"""
    zeros: list[float] = []
    lods: list[float] = []
    n_censored = n_nd = 0
    n = 0
    for censoring_value, value_num, limit in obs_rows:
        v_zero, v_lod = _imputed(censoring_value, value_num, limit)
        is_nd = censoring_value == censoring.CENSORING_NOT_DETECTED
        if v_zero is None and not is_nd:
            continue  # 非メンバー（above_lod/unknown で値が無いもの）
        n += 1
        if v_zero is not None:
            zeros.append(v_zero)
        if v_lod is not None:
            lods.append(v_lod)
        n_censored += censoring_value == censoring.CENSORING_BELOW_LOD
        n_nd += is_nd
    return _stat_of(zeros, stat), _stat_of(lods, stat), n, n_censored, n_nd


def _rollup_stats(obs_rows: list[tuple], stat_of_days: str) -> tuple:
    """日次→月次・年次の積み上げ（日次セルの mean を `stat_of_days` で集計し直す。
    n は日次セルの個数、検閲件数は日次セルの合計）。`obs_rows` は
    (date, censoring, value_num, censoring_limit)。"""
    by_day: dict[str, list[tuple]] = {}
    for day, *rest in obs_rows:
        by_day.setdefault(day, []).append(tuple(rest))
    day_zero: list[float] = []
    day_lod: list[float] = []
    n_days = n_censored = n_nd = 0
    for rows in by_day.values():
        vz, vl, n, n_c, n_d = _group_stats(rows, "mean")
        if n == 0:
            continue  # メンバーの無い日はセルにならない
        n_days += 1  # ND だけの日もセルにはなる（値は NULL で平均には入らない）
        if vz is not None:
            day_zero.append(vz)
        if vl is not None:
            day_lod.append(vl)
        n_censored += n_c
        n_nd += n_d
    return _stat_of(day_zero, stat_of_days), _stat_of(day_lod, stat_of_days), n_days, n_censored, n_nd


def _skey_sql(mode: str) -> str:
    """`observation` 側の結合キー（セル側の `_cell_skey` と同じ並び）。NULL は番人文字に
    直す（`IS` の NULL 安全 JOIN は索引が効かないため、1本の文字列キーの等値にする）。"""
    parts = [f"IFNULL(o.{c}, char(30))" for c in _PRE_PERIOD_DIM_COLUMNS] + ["o.period_grain"]
    plen = _MODE_PREFIX_LEN[mode]
    if mode == _MODE_FISCAL_FROM_MONTH:
        # 年度の始まりの年（4月始まり）。セル側の period_start[:4] と同じ値になる。
        parts.append(f"printf('%04d', {_fiscal_start_year_sql('o.period_start')})")
    elif plen is None:
        parts += ["o.period_start", "o.period_end"]
    else:
        parts.append(f"substr(o.period_start, 1, {plen})")
    return " || char(31) || ".join(parts)


def _cell_skey(cell: dict, mode: str) -> str:
    parts = [_KEY_NULL if cell[c] is None else cell[c] for c in _PRE_PERIOD_DIM_COLUMNS] + [cell["input_grain"]]
    plen = _MODE_PREFIX_LEN[mode]
    if plen is None:
        parts += [cell["period_start"], cell["period_end"]]
    else:
        parts.append(cell["period_start"][:plen])
    return _KEY_SEP.join(parts)


def _expected_cell(cell: dict, mode: str, obs_rows: list[tuple]) -> tuple:
    """`obs_rows`（(period_start, censoring, value_num, censoring_limit)）から、セル
    `cell` の (value_zero, value_lod, n, n_censored, n_not_detected) を独立に求める。"""
    stat = cell["stat"]
    if mode in (_MODE_DAY, _MODE_SOURCE, _MODE_YEAR_FROM_MONTH, _MODE_FISCAL_FROM_MONTH):
        # 月から積み上げた年・年度は、観測の行から直接再集計する（葉の格と同じ式）。
        return _group_stats([r[1:] for r in obs_rows], stat)
    # 積み上げ: 月は日次の mean だけ、年は日次の mean を stat で集計する。
    stat_of_days = "mean" if mode == _MODE_MONTH_FROM_DAY else stat
    return _rollup_stats([(r[0][:10], *r[1:]) for r in obs_rows], stat_of_days)


def _close(expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    return math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-12)


def _assert_sampled_cells_recompute_from_observation(
    conn: sqlite3.Connection, staging: str, observation_fingerprint: str, spec_version: str,
) -> dict:
    """`staging` から層別に無作為抽出したセルを、`observation` から Python で求め直して
    突き合わせる。n・n_censored・n_not_detected は完全一致、value_zero/value_lod は
    相対誤差 1e-9（`fsum` と SQLite の AVG の加算順の差）で一致。食い違えば最大
    `cube_invariants.SAMPLE_LIMIT` 件を (次元キー・期間・期待・実際) つきで止める。
    抽出は `observation` の指紋と spec_version から決める（入力が同じなら同じ抽出）。
    戻り値はレポート用の統計。
    """
    rowids = _pick_sample_rowids(conn, staging, _sample_seed(observation_fingerprint, spec_version))
    cols = DIM_COLUMNS + ["value_zero", "value_lod", "n", "n_censored", "n_not_detected"]
    try:
        conn.execute("CREATE TEMP TABLE __sample_ids (cid INTEGER PRIMARY KEY)")
        conn.execute("CREATE TEMP TABLE __sample_cells (cid INTEGER, mode TEXT, skey TEXT)")
        conn.executemany("INSERT INTO __sample_ids VALUES (?)", [(r,) for r in rowids])
        cells: dict[int, dict] = {}
        for row in conn.execute(
            f'SELECT s.rowid, {", ".join("s." + c for c in cols)} FROM "{staging}" s '
            "JOIN __sample_ids i ON i.cid = s.rowid"
        ):
            cells[row[0]] = dict(zip(cols, row[1:]))
        modes = {cid: _cell_mode(c["grain"], c["input_grain"]) for cid, c in cells.items()}
        conn.executemany(
            "INSERT INTO __sample_cells VALUES (?,?,?)",
            [(cid, modes[cid], _cell_skey(c, modes[cid])) for cid, c in cells.items()],
        )
        conn.execute("CREATE INDEX __sample_cells_skey ON __sample_cells (skey)")

        obs_by_cell: dict[int, list[tuple]] = {cid: [] for cid in cells}
        for mode in sorted(set(modes.values())):
            for cid, period_start, censoring_value, value_num, limit in conn.execute(
                "SELECT s.cid, o.period_start, o.censoring, o.value_num, o.censoring_limit "
                "FROM observation o JOIN __sample_cells s "
                f"ON s.skey = {_skey_sql(mode)} WHERE s.mode = ?",
                (mode,),
            ):
                obs_by_cell[cid].append((period_start, censoring_value, value_num, limit))
    finally:
        conn.execute("DROP TABLE IF EXISTS __sample_cells")
        conn.execute("DROP TABLE IF EXISTS __sample_ids")

    mismatches = []
    for cid in rowids:
        cell = cells[cid]
        exp = _expected_cell(cell, modes[cid], obs_by_cell[cid])
        act = (cell["value_zero"], cell["value_lod"], cell["n"], cell["n_censored"], cell["n_not_detected"])
        if not (_close(exp[0], act[0]) and _close(exp[1], act[1]) and exp[2:] == act[2:]):
            mismatches.append((tuple(cell[c] for c in DIM_COLUMNS), "期待", exp, "実際", act))
    if mismatches:
        raise common.MigrationError(
            f"observation_agg: 無作為抽出したセルのうち{len(mismatches)}件が observation からの"
            f"独立な再計算と一致しない（例（上限{cube_invariants.SAMPLE_LIMIT}件、次元キー{DIM_COLUMNS}・"
            f"期待・実際。期待/実際は (value_zero, value_lod, n, n_censored, n_not_detected)）: "
            f"{mismatches[:cube_invariants.SAMPLE_LIMIT]}）。"
            "セルの集計 SQL（日次・月次・年次の経路）か value_zero/value_lod の代入規則が"
            "観測と食い違っている。"
        )
    return {
        "n_sampled_cells": len(rowids),
        "n_sampled_censored_cells": sum(1 for c in cells.values() if c["n_censored"] or c["n_not_detected"]),
    }


def build_cube(
    conn,
    registry_db=DEFAULT_REGISTRY_DB,
    built_from: str = DEFAULT_BUILT_FROM,
    spec_version: str = common.OBSERVATION_AGG_SPEC_VERSION,
    unit_evidence_declarations_path=UNIT_EVIDENCE_DECLARATIONS_YAML,
    period_exceptions_path=PERIOD_EXCEPTIONS_YAML,
) -> dict:
    """`conn`（`observation` を持つ読み書き可能な接続）に `observation_agg` を作る。

    `conn` 自身は読み取り専用で開かない（`observation` と同じファイルに書くため。
    モジュール docstring 参照）。`registry_db`（`variable.default_stat` を読む
    ためだけに使う。T4-2）は読み取り専用で ATTACH する。ここでは `observation`
    を変更する SQL を一切実行しない（`SELECT`/一時 VIEW・TEMP TABLE の作成のみ）。
    `observation_agg` 本体は `migrate.common.staged_table`（A-1）で作り直す
    ——検証（次元キーの一意性・`value_zero`/`value_lod` の関係）まで全部通って
    から本番名に差し替える。

    `period_exceptions_path`（Issue #32-2。既定は実ファイル）: `rollup_to` の宣言（月に復元した
    観測を年度などへ積み上げるか）を読む。宣言が無ければ月 → 年・年度のセルは作らない。

    `unit_evidence_declarations_path`（Issue #48 PR-1 §4。既定は実ファイル
    `UNIT_EVIDENCE_DECLARATIONS_YAML`）: `_assert_unit_evidence()` の検証2
    （宣言の過不足）に渡す宣言 YAML のパス。`None` は検証2を丸ごとスキップする
    （`_assert_unit_evidence()` の docstring 参照）。**既定を実ファイルにしてある
    のは、本番経路（`main()`）がこの引数を渡し忘れても検査が黙って消えないよう
    にするため**——`None` を明示できるのはテストのフィクスチャ呼び出しだけ
    （本物の宣言は実データ全体が前提のため、小さな合成フィクスチャでは
    正しく判定できない。`scripts/tests/test_b04_build_cube.py`/
    `test_b05_project_v1.py` の呼び出しを参照）。以前はモジュールレベルの
    `UNIT_EVIDENCE_DECLARATIONS_YAML` を `scripts/tests/conftest.py` の
    autouse フィクスチャで `None` に monkeypatch していたが、これだと
    テストを1つも書かずに `build_cube()` を直接叩く経路（本番の `main()` も
    含む）が検証2の無効化に気づけない構造だったため、引数化した。

    戻り値はレポート用の統計（経路ごとの行数・`value_zero`/`value_lod` の
    差分件数）。

    `AVG()`/`SUM()` を実行する前に `common.require_sqlite_version()` を呼ぶ
    （モジュール docstring「SQLite の版を守る」参照）。
    """
    common.require_sqlite_version()
    # 段階間の指紋（Issue #37 #1・#45）: b03 が最後に記録した observation の指紋と
    # 今の observation の内容が一致することを、集計を始める前に確認する
    # （b03 が別内容で再実行された後、b04 が再実行されていない事故を検出する）。
    # 系譜（observation_agg の inputs）は手で書かない——`lineage` が段の先頭から
    # 実際に読んだ表（observation・registry の `reg`）を集め、`staged_table` が
    # 差し替え時に自動で記録する。`verify` していない上流を読めば止まる。
    with common.LineageTracker(conn, external={"reg": common.registry_external(registry_db)}) as lineage:
        observation_fingerprint = lineage.verify(
            "observation", rebuild_hint="scripts/b03_build_observation.py を再実行すること。",
        )
        # below_lod が censoring_limit を必ず持つことは b03 が保証済み（/simplify 指摘2）。
        params = (built_from, spec_version)
        common.attach_readonly(conn, registry_db, "reg")

        # 単位の証拠検査（D3、モジュール docstring「単位の証拠検査」節参照）。
        # observation_agg を作り始める前に確認する（observation_agg 自体は unit_raw を
        # 持たないため、この検証ができるのは observation を直接読めるここだけ）。
        # 呼び出し側が渡した `unit_evidence_declarations_path`（既定は実ファイル。
        # 上記 docstring 参照）をそのまま `_assert_unit_evidence()` に渡す。
        unit_evidence_stats = _assert_unit_evidence(conn, declarations_path=unit_evidence_declarations_path)

        # 自己不変条件（Issue #48 PR-5: v1 射影 b05 から移した。`migrate/cube_invariants.py`）。
        # 系列の逆引き（alias・単位表記）が一意でなければ、キューブのセルがどの出典・
        # どの単位の系列なのか決まらない。
        cube_invariants.assert_alias_is_function(conn)
        cube_invariants.assert_alias_tuple_maps_to_single_dataset(conn)
        cube_invariants.assert_unit_raw_is_function(conn)

        conn.execute(_CREATE_OBS_IMPUTED_VIEW_SQL)

        with common.staged_table(
            conn, "observation_agg", _CREATE_OBSERVATION_AGG_SQL,
            lineage=lineage,
            fingerprint_spec_version=spec_version,
        ) as staging:
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

            # 年次・年度（出典が月で配った観測から。Issue #32-2。観測の行から直接再集計）。
            rollup_grains = period.declared_rollup_grains(period.load_period_exceptions(period_exceptions_path))
            n_year_from_month = 0
            for grain in rollup_grains:
                common.replace_table(
                    conn, "year_from_month_stats",
                    f"CREATE TEMP TABLE year_from_month_stats AS {_year_from_month_stats_sql(grain)}",
                )
                for stat, vz_col, vl_col in _STAT_VALUE_COLUMNS:
                    cur = conn.execute(insert_sql + _year_from_month_expand_sql(stat, vz_col, vl_col), params)
                    n_year_from_month += cur.rowcount

            # B-4: 一時テーブルの DROP をループに（cube_day は C-1 で無くなった）。
            for t in ("day_stats", "year_from_day_stats", "month_source_stats", "year_source_stats", "year_from_month_stats"):
                conn.execute(f'DROP TABLE IF EXISTS "{t}"')
            conn.execute("DROP VIEW IF EXISTS obs_imputed")

            # 次元キーが本当に一意か（同じキーの行が複数できていないか）を確認する
            # （C-3）。ここで失敗すれば staged_table が作業用テーブルを破棄し、
            # 前回の observation_agg がそのまま残る（A-1）。
            _assert_dimension_key_unique(conn, staging)

            # value_zero/value_lod の3つの不変条件（ADR-0009 決定4）。検証と
            # 統計収集を分ける（/code-review 指摘13）。
            _assert_value_zero_lod_invariants(conn, staging)
            # T6: 毎時→日次の件数・Σn・min・max が observation と一致する（移設）。
            cube_invariants.verify_hourly_daily_rollup(conn, staging)
            # Issue #32-2: 月 → 年・年度の積み上げの保存則（n・検閲件数の和、値の min/max）。
            month_rollup_stats = cube_invariants.verify_month_year_rollup(conn, staging, rollup_grains)
            # 無作為抽出したセルを observation から独立に求め直す（Issue #48 PR-5 §2.3）。
            sample_stats = _assert_sampled_cells_recompute_from_observation(
                conn, staging, observation_fingerprint, spec_version,
            )
            value_stats = _collect_value_zero_lod_stats(conn, staging)
    # ここまで来たら staged_table が観測差し替えと同じトランザクションで
    # observation_agg の指紋・系譜（消費した observation の指紋）も記録済み
    # （Issue #37 #1・/code-review 指摘の根本対応。「内容は新しいが指紋は
    # 古い」状態を作れなくする）。b05 はこの指紋を見て「今の observation_agg
    # から作った v1_projection.sqlite か」を検証する。

    # Issue #48 PR-1 §1: 索引は差し替え確定後（本番テーブル名）に張る
    # （`common.create_indexes` docstring 参照）。
    common.create_indexes(conn, "observation_agg", OBSERVATION_AGG_INDEXES)

    return {
        "n_day": n_day,
        "n_month_from_day": n_month_from_day,
        "n_month_source": n_month_source,
        "n_year_from_day": n_year_from_day,
        "n_year_source": n_year_source,
        "n_year_from_month": n_year_from_month,
        "n_total": n_day + n_month_from_day + n_month_source + n_year_from_day + n_year_source + n_year_from_month,
        **month_rollup_stats,
        **value_stats,
        **sample_stats,
        **unit_evidence_stats,
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
    parser.add_argument(
        "--unit-evidence-declarations-yaml", default=str(UNIT_EVIDENCE_DECLARATIONS_YAML),
        help="単位の証拠検査（D3・検証2）が読む宣言 YAML。既定は本番の "
        f"{UNIT_EVIDENCE_DECLARATIONS_YAML}。（合成データを含む診断用の observation 向けの別宣言は、"
        "v1互換キューブの撤去〔Issue #48 PR-5〕とともに無くなった。）",
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
            # 本番経路は実ファイルを明示的に渡す（既定と同じ値だが、渡し忘れて
            # 検証2が黙って消える事故を機械的に防ぐため——build_cube() の
            # docstring 参照）。`--unit-evidence-declarations-yaml` の既定値も
            # 同じ実ファイルなので、CLI 引数を追加しても通常実行の挙動は
            # 1ビットも変わらない。
            stats = build_cube(
                conn, registry_db,
                unit_evidence_declarations_path=args.unit_evidence_declarations_yaml,
            )
            info["n"] = stats["n_total"]
    finally:
        conn.close()

    print(
        f"  内訳: day={stats['n_day']:,} / "
        f"month(day側)={stats['n_month_from_day']:,} / month(出典側)={stats['n_month_source']:,} / "
        f"year(day側)={stats['n_year_from_day']:,} / year(出典側)={stats['n_year_source']:,} / "
        f"年度等(month側・宣言駆動)={stats['n_year_from_month']:,}"
    )
    print(
        f"  value_zero/value_lod: 食い違うセル={stats['n_value_lod_differs']:,} / "
        f"value_lod が NULL のセル={stats['n_value_lod_null']:,}"
    )


if __name__ == "__main__":
    main()
