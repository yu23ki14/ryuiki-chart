# Phase B ファクト移行 — observation の要約

`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の `measurements`・`sensor_timeseries` と `data/processed/nlni_l03b_landuse_by_watershed.csv`（土地利用、P-1b）から `data/db/v2.sqlite` の `observation` を作った結果の要約。設計判断は `docs/plans/PHASE_B_FACT_SLICE.md`（measurements の縦線）と「センサーの縦線 設計 v2」オーナー決定・関連 ADR（`docs/adr/0023-*`・`0024-*`）、`docs/plans/PHASE_B_LANDUSE.md`（土地利用の縦線）参照。

- 入力（`measurements`+`sensor_timeseries`+土地利用CSV）総行数: **1,318,978**
- `observation` 総行数: **1,302,434**（出典ごとの 入力行数→observation行数: measurements=327,065→324,800, nlni_l03b_landuse_by_watershed=5,141→10,282, sensor_timeseries=986,772→967,352。土地利用だけ CSV の1行が面積・セル数の2 observation 行になるため、入力行数と observation 行数が1:1にならない）
- 合成データ（`is_synthetic=1`）を除外した行数（出典合計）: **21,685**（Issue #48 PR-0 オーナー決定。内訳は出典ごとの節を参照）

## 出典: `measurements`

- `measurements` 総行数: **327,065**
- 合成データ（`is_synthetic=1`）を除外した行数: **2,265**（既定で本番に出さない。Issue #48 PR-0 オーナー決定。alias/place 解決の前に弾くため、下の解決率には含めない）
- `observation` 行数: **324,800**
- alias（variable_alias）解決率: 324,800 / 324,800 （合成データを除いた行のうち。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 324,800 / 324,800 （同上。全行解決）

### censoring の内訳（ADR-0009・design.md D2）

| censoring | 行数 |
|---|---:|
| `none` | 246,918 |
| `below_lod` | 76,757 |
| `not_detected` | 1,078 |
| `above_lod` | 47 |
| `unknown` | 0 |

`value_zero` 系列で値（0.0）が入る行（`below_lod` のみ。`not_detected` は Issue #61 で除外に変更）: **76,757行**（`above_lod`/`unknown` には代入しない。design.md D2）。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **3,840行**

## 出典: `sensor_timeseries`

- `sensor_timeseries` 総行数: **986,772**
- 合成データ（`is_synthetic=1`）を除外した行数: **19,420**（既定で本番に出さない。Issue #48 PR-0 オーナー決定。alias/place 解決の前に弾くため、下の解決率には含めない）
- `observation` 行数: **967,352**
- alias（variable_alias）解決率: 967,352 / 967,352 （合成データを除いた行のうち。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 967,352 / 967,352 （同上。全行解決）

センサーに検閲の概念は無い（design.md T3）。`censoring` は常に `'none'`・`value_raw` は常に NULL。`sensor_timeseries.result IS NULL` の行はそのまま `value_num=NULL` で運び、b04 のメンバー条件（`_MEMBER_SQL`）でキューブから自然に除外される。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **0行**

## 出典: `nlni_l03b_landuse_by_watershed`

- `nlni_l03b_landuse_by_watershed` 総行数: **5,141**
- `observation` 行数: **10,282**
- alias（variable_alias）/ place（place_source_ref）解決率: 10,282 / 10,282 （CSV1行→面積・セル数の2 observation 行。全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）

検閲の概念は無い（`censoring` は常に `'none'`）。区分の面積（km2）とセル数（count）をそれぞれ別の variable として持つ（P-1b オーナー決定1）。region は `manifests/*.yml`（consumer='observation'）の宣言から決める（ADR-0022 決定3・P-1b オーナー決定3）。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **0行**

