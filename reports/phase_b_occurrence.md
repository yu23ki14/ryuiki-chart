# Phase B ファクト移行 — occurrence の要約（O-1a）

`scripts/b06_build_occurrence.py` が `data/db/ryuiki.sqlite` の `organism_records` から `data/db/v2.sqlite` の `occurrence` を作った結果の要約。設計は `docs/plans/PHASE_B_OCCURRENCE.md`（O-1a節）参照。

- `organism_records` 総行数: **948,410**
- 合成データ（`is_synthetic=1`）を除外した行数: **0**（本番に出さない。Issue #48 PR-0 オーナー決定。実測では常に0——`organism_records` に合成の出現記録は無い。将来行が増えても黙って通さないための防御）
- 不在記録（`occurrence_status='ABSENT'`）を除外した行数: **2,790**（原本には残す。出現として数えない。2026-10-07 オーナー決定・ADR-0025。出典別: `gbif_kanagawa_occurrences` 2,790。マニフェストの `expected_absent_excluded_rows` と突合済み）
- GBIF 経由の iNaturalist 観察（直取得と `source_ref` が一致）を除外した行数: **68,693**（原本には残す。直取得側を正にして二重に数えない。Issue #125。出典別: `gbif_amami_occurrences` 2,359, `gbif_kanagawa_occurrences` 66,334。結合で独立に数えた重複件数と突合済み。GBIF の iNaturalist 由来で直取得に一致しない行は残す。出典を絞るときは直取得の `inaturalist_*` を含めること）
- `occurrence` 行数: **876,927**（合成データ・不在記録・重複を除く全行を取り込む。ADR-0007原則1の例外——Issue #48 PR-0 オーナー決定）
- 日付あり（`period_raw` NOT NULL）: **868,514**
- 座標なし（`lat`/`lon` NULL）: **8,509**
- `taxon_id` NULL: **990**（うち日付あり: 912）

## adapter 経由の出典（`manifests/*.yml` の `adapter` が builtin でないもの）

| source_id | 取り込み行数 | attributes を持つ行 |
|---|---:|---:|
| `kanagawa_edna` | 13,263 | 13,263 |
| `kanagawa_kuma_sightings` | 400 | 400 |
| `moni1000_coast_shorebird` | 619 | 619 |
| `moni1000_coast_shorebird_amami` | 275 | 275 |
| `moni1000_forest_bird` | 9,208 | 9,208 |
| `moni1000_forest_bird_amami` | 5,303 | 5,303 |
| `moni1000_satochi_bird` | 18,261 | 18,261 |
| `moni1000_satochi_butterfly` | 14,395 | 14,395 |
| `moni1000_satochi_mammal` | 1,581 | 1,581 |

## 赤リスト判定を b06 が補った記録（出典が `red_list_category` を付けていなかったもの）

`scripts/migrate/redlist_fill.py`。`subspecies` は県版が亜種だけを載せている種の記録（`red_list_source` に掲載名が入る）。

| source_id | 規則 | 記録数 | 地域×学名の種類数 |
|---|---|---:|---:|
| `gbif_amami_occurrences` | national_exact | 456 | 105 |
| `gbif_amami_occurrences` | pref_exact | 4,665 | 325 |
| `gbif_amami_occurrences` | subspecies | 1,861 | 80 |
| `gbif_kanagawa_occurrences` | national_exact | 1,604 | 191 |
| `gbif_kanagawa_occurrences` | pref_exact | 2,937 | 200 |
| `gbif_kanagawa_occurrences` | subspecies | 553 | 15 |
| `inaturalist_amami` | subspecies | 208 | 59 |
| `inaturalist_kanagawa` | national_exact | 2 | 1 |
| `inaturalist_kanagawa` | pref_exact | 1,980 | 305 |
| `inaturalist_kanagawa` | subspecies | 152 | 22 |
| `kanagawa_edna` | national_exact | 448 | 11 |
| `kanagawa_edna` | pref_exact | 48 | 11 |
| `kanagawa_edna` | subspecies | 1 | 1 |
| `moni1000_coast_shorebird` | national_exact | 8 | 2 |
| `moni1000_coast_shorebird_amami` | pref_exact | 35 | 7 |
| `moni1000_coast_shorebird_amami` | subspecies | 27 | 5 |
| `moni1000_forest_bird_amami` | pref_exact | 665 | 2 |
| `moni1000_forest_bird_amami` | subspecies | 602 | 4 |
| `moni1000_satochi_butterfly` | pref_exact | 26 | 6 |

## region 内訳

| region_id | 行数 |
|---|---:|
| `jp-14` | 812,295 |
| `jp-46` | 64,632 |

## 期間の形（12形）ごとの件数

| 形 | 行数 |
|---|---:|
| `day` | 836,670 |
| `day_interval` | 4,601 |
| `instant_millisecond_z` | 805 |
| `instant_minute` | 1,182 |
| `instant_minute_z` | 110 |
| `instant_minute_z_interval` | 57 |
| `instant_second` | 1,305 |
| `instant_second_z` | 78 |
| `month` | 20,709 |
| `month_interval` | 14 |
| `year` | 1,937 |
| `year_interval` | 1,046 |

- 'Z' → ローカル時刻の変換件数: **1,050**
- 変換で日が変わった件数: **96** / 月が変わった件数: **8** / 年が変わった件数: 0（1件でもあれば構築自体が止まる。D3の前提）

