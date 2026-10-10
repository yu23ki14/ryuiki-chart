# Phase B ファクト移行 — occurrence の要約（O-1a）

`scripts/b06_build_occurrence.py` が `data/db/ryuiki.sqlite` の `organism_records` から `data/db/v2.sqlite` の `occurrence` を作った結果の要約。設計は `docs/plans/PHASE_B_OCCURRENCE.md`（O-1a節）参照。

- `organism_records` 総行数: **898,768**
- 合成データ（`is_synthetic=1`）を除外した行数: **0**（本番に出さない。Issue #48 PR-0 オーナー決定。実測では常に0——`organism_records` に合成の出現記録は無い。将来行が増えても黙って通さないための防御）
- 不在記録（`occurrence_status='ABSENT'`）を除外した行数: **2,790**（原本には残す。出現として数えない。2026-10-07 オーナー決定・ADR-0025。出典別: `gbif_kanagawa_occurrences` 2,790。マニフェストの `expected_absent_excluded_rows` と突合済み）
- `occurrence` 行数: **895,978**（合成データ・不在記録を除く全行を取り込む。ADR-0007原則1の例外——Issue #48 PR-0 オーナー決定）
- 日付あり（`period_raw` NOT NULL）: **887,565**
- 座標なし（`lat`/`lon` NULL）: **8,509**
- `taxon_id` NULL: **990**（うち日付あり: 912）

## adapter 経由の出典（`manifests/*.yml` の `adapter` が builtin でないもの）

| source_id | 取り込み行数 | attributes を持つ行 |
|---|---:|---:|
| `kanagawa_edna` | 13,263 | 13,263 |
| `kanagawa_kuma_sightings` | 400 | 400 |

## region 内訳

| region_id | 行数 |
|---|---:|
| `jp-14` | 834,565 |
| `jp-46` | 61,413 |

## 期間の形（12形）ごとの件数

| 形 | 行数 |
|---|---:|
| `day` | 806,294 |
| `day_interval` | 4,601 |
| `instant_millisecond_z` | 805 |
| `instant_minute` | 27,428 |
| `instant_minute_z` | 981 |
| `instant_minute_z_interval` | 57 |
| `instant_second` | 41,836 |
| `instant_second_z` | 145 |
| `month` | 2,447 |
| `month_interval` | 14 |
| `year` | 1,911 |
| `year_interval` | 1,046 |

- 'Z' → ローカル時刻の変換件数: **1,988**
- 変換で日が変わった件数: **231** / 月が変わった件数: **10** / 年が変わった件数: 0（1件でもあれば構築自体が止まる。D3の前提）

