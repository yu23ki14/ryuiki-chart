# Phase B ファクト移行 — occurrence の要約（O-1a）

`scripts/b06_build_occurrence.py` が `data/db/ryuiki.sqlite` の `organism_records` から `data/db/v2.sqlite` の `occurrence` を作った結果の要約。設計は `docs/plans/PHASE_B_OCCURRENCE.md`（O-1a節）参照。

- `organism_records` 総行数: **823,692**
- `occurrence` 行数: **823,692**（全行取り込む。ADR-0007原則1）
- 日付あり（`period_raw` NOT NULL）: **816,856**
- 座標なし（`lat`/`lon` NULL）: **0**
- `taxon_id` NULL: **853**（うち日付あり: 775）

## region 内訳

| region_id | 行数 |
|---|---:|
| `jp-14` | 823,692 |

## 期間の形（12形）ごとの件数

| 形 | 行数 |
|---|---:|
| `day` | 740,323 |
| `day_interval` | 3,723 |
| `instant_millisecond_z` | 800 |
| `instant_minute` | 26,042 |
| `instant_minute_z` | 958 |
| `instant_minute_z_interval` | 57 |
| `instant_second` | 40,633 |
| `instant_second_z` | 143 |
| `month` | 1,320 |
| `month_interval` | 14 |
| `year` | 1,797 |
| `year_interval` | 1,046 |

- 'Z' → ローカル時刻の変換件数: **1,958**
- 変換で日が変わった件数: **221** / 月が変わった件数: **10** / 年が変わった件数: 0（1件でもあれば構築自体が止まる。D3の前提）

