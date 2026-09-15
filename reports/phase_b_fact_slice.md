# Phase B ファクト移行 — observation の要約

`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の `measurements` から `data/db/v2.sqlite` の `observation` を作った結果の要約。詳細な設計判断は `docs/plans/PHASE_B_FACT_SLICE.md` 参照。

- `measurements` 総行数: **323,164**
- `observation` 行数: **323,164**
- alias（variable_alias）解決率: 323,164 / 323,164 （全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）
- place（place_source_ref）解決率: 323,164 / 323,164 （同上。全行解決）

## censoring の内訳（ADR-0009・design.md D2）

| censoring | 行数 |
|---|---:|
| `none` | 246,370 |
| `below_lod` | 75,701 |
| `not_detected` | 1,067 |
| `above_lod` | 26 |
| `unknown` | 0 |

`imputation='zero'` で値（0.0）が入る行（`below_lod` + `not_detected`）: **76,768行**（`above_lod`/`unknown` には代入しない。design.md D2）。

## value_grain != period_grain（design.md D4）

食い違う行: **3,840行**（すべて `period_exceptions.yaml` の宣言でカバーされている。宣言に無い食い違いが1件でもあれば b03 は例外で止まる）。

宣言ごとの実測件数（`period_exceptions.yaml`）:

| source_id | 該当行数 |
|---|---:|
| `atsugi_river_water_quality` | 3,840 |

