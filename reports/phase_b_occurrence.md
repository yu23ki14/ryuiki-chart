# Phase B ファクト移行 — occurrence の要約（O-1a）

`scripts/b06_build_occurrence.py` が `data/db/ryuiki.sqlite` の `organism_records` から `data/db/v2.sqlite` の `occurrence` を作った結果の要約。設計は `docs/plans/PHASE_B_OCCURRENCE.md`（O-1a節）参照。

- `organism_records` 総行数: **824,092**
- 合成データ（`is_synthetic=1`）を除外した行数: **0**（本番に出さない。Issue #48 PR-0 オーナー決定。実測では常に0——`organism_records` に合成の出現記録は無い。将来行が増えても黙って通さないための防御）
- `occurrence` 行数: **824,092**（合成データを除く全行を取り込む。ADR-0007原則1の例外——Issue #48 PR-0 オーナー決定）
- 日付あり（`period_raw` NOT NULL）: **817,252**
- 座標なし（`lat`/`lon` NULL）: **400**
- `taxon_id` NULL: **853**（うち日付あり: 775）

## adapter 経由の出典（`manifests/*.yml` の `adapter` が builtin でないもの）

| source_id | 取り込み行数 | attributes を持つ行 |
|---|---:|---:|
| `kanagawa_kuma_sightings` | 400 | 400 |

## region 内訳

| region_id | 行数 |
|---|---:|
| `jp-14` | 824,092 |

## 期間の形（12形）ごとの件数

| 形 | 行数 |
|---|---:|
| `day` | 740,719 |
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

