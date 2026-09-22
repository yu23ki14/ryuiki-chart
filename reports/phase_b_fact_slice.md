# Phase B ファクト移行 — observation の要約

`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の `measurements`・`sensor_timeseries` から `data/db/v2.sqlite` の `observation` を作った結果の要約。設計判断は `docs/plans/PHASE_B_FACT_SLICE.md`（measurements の縦線）と「センサーの縦線 設計 v2」オーナー決定・関連 ADR（`docs/adr/0023-*`・`0024-*`）参照。

- 入力（`measurements`+`sensor_timeseries`）総行数: **1,041,003**
- `observation` 総行数: **1,041,003**

## 出典: `measurements`

- `measurements` 総行数: **323,164**
- `observation` 行数: **323,164**
- alias（variable_alias）解決率: 323,164 / 323,164 （全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 323,164 / 323,164 （同上。全行解決）

### censoring の内訳（ADR-0009・design.md D2）

| censoring | 行数 |
|---|---:|
| `none` | 246,370 |
| `below_lod` | 75,701 |
| `not_detected` | 1,067 |
| `above_lod` | 26 |
| `unknown` | 0 |

`imputation='zero'` で値（0.0）が入る行（`below_lod` + `not_detected`）: **76,768行**（`above_lod`/`unknown` には代入しない。design.md D2）。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **3,840行**

## 出典: `sensor_timeseries`

- `sensor_timeseries` 総行数: **717,839**
- `observation` 行数: **717,839**
- alias（variable_alias）解決率: 717,839 / 717,839 （全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 717,839 / 717,839 （同上。全行解決）

センサーに検閲の概念は無い（design.md T3）。`censoring` は常に `'none'`・`value_raw` は常に NULL。`sensor_timeseries.result IS NULL` の行はそのまま `value_num=NULL` で運び、b04 の `WHERE v IS NOT NULL` でキューブから自然に除外される。

value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ許される）: **0行**

