# Phase B ファクト移行 — observation の要約

`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の `measurements`・`sensor_timeseries` と `data/processed/nlni_l03b_landuse_by_watershed.csv`（土地利用、P-1b）から `data/db/v2.sqlite` の `observation` を作った結果の要約。設計判断は `docs/plans/PHASE_B_FACT_SLICE.md`（measurements の縦線）と「センサーの縦線 設計 v2」オーナー決定・関連 ADR（`docs/adr/0023-*`・`0024-*`）、`docs/plans/PHASE_B_LANDUSE.md`（土地利用の縦線）参照。

- 入力（`measurements`+`sensor_timeseries`+土地利用CSV）総行数: **1,045,861**
- `observation` 総行数: **1,029,034**（出典ごとの 入力行数→observation行数: measurements=323,164→320,899, nlni_l03b_landuse_by_watershed=4,858→9,716, sensor_timeseries=717,839→698,419。土地利用だけ CSV の1行が面積・セル数の2 observation 行になるため、入力行数と observation 行数が1:1にならない）
- 合成データ（`is_synthetic=1`）を除外した行数（出典合計）: **21,685**（Issue #48 PR-0 オーナー決定。`--include-synthetic` を渡した診断専用の実行では 0 のまま——除外していないため。内訳は出典ごとの節を参照）

## 出典: `measurements`

- `measurements` 総行数: **323,164**
- 合成データ（`is_synthetic=1`）を除外した行数: **2,265**（既定で本番に出さない。Issue #48 PR-0 オーナー決定。alias/place 解決の前に弾くため、下の解決率には含めない）
- `observation` 行数: **320,899**
- alias（variable_alias）解決率: 320,899 / 320,899 （合成データを除いた行のうち。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 320,899 / 320,899 （同上。全行解決）

### censoring の内訳（ADR-0009・design.md D2）

| censoring | 行数 |
|---|---:|
| `none` | 244,105 |
| `below_lod` | 75,701 |
| `not_detected` | 1,067 |
| `above_lod` | 26 |
| `unknown` | 0 |

`imputation='zero'` で値（0.0）が入る行（`below_lod` + `not_detected`）: **76,768行**（`above_lod`/`unknown` には代入しない。design.md D2）。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **3,840行**

## 出典: `sensor_timeseries`

- `sensor_timeseries` 総行数: **717,839**
- 合成データ（`is_synthetic=1`）を除外した行数: **19,420**（既定で本番に出さない。Issue #48 PR-0 オーナー決定。alias/place 解決の前に弾くため、下の解決率には含めない）
- `observation` 行数: **698,419**
- alias（variable_alias）解決率: 698,419 / 698,419 （合成データを除いた行のうち。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 698,419 / 698,419 （同上。全行解決）

センサーに検閲の概念は無い（design.md T3）。`censoring` は常に `'none'`・`value_raw` は常に NULL。`sensor_timeseries.result IS NULL` の行はそのまま `value_num=NULL` で運び、b04 の `WHERE v_zero IS NOT NULL` でキューブから自然に除外される。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **0行**

## 出典: `nlni_l03b_landuse_by_watershed`

- `nlni_l03b_landuse_by_watershed` 総行数: **4,858**
- `observation` 行数: **9,716**
- alias（variable_alias）/ place（place_source_ref）解決率: 9,716 / 9,716 （CSV1行→面積・セル数の2 observation 行。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）

検閲の概念は無い（`censoring` は常に `'none'`）。区分の面積（km2）とセル数（count）をそれぞれ別の variable として持つ（P-1b オーナー決定1）。region は `source_regions.yaml`（consumer='observation'）の宣言から決める（ADR-0022 決定3・P-1b オーナー決定3）。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **0行**

