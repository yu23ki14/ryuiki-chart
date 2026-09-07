# v1 派生テーブルのベースライン指紋（Phase B 受け入れゲート）

`scripts/b01_derived_baseline.py` が `data/db/derived.sqlite`（読み取り専用）から生成する。機械可読な本体は `reports/derived_baseline.json`。このファイルは人が読む要約。

再生成: `.venv/bin/python3 scripts/b01_derived_baseline.py`

テーブル数 **33** / 総行数 **2,070,295**（`data/db/derived.sqlite` より）。

「行き先」列は `docs/adr/0011-aggregation-cube.md` の「33テーブルの行き先」表（`scripts/reconcile/adr0011_destinations.yaml` にデータとして持つ）。

## テーブル一覧

| テーブル | 行数 | キー | キーの由来 | 行き先（ADR-0011） | 内容ハッシュ（先頭12桁） |
|---|---:|---|---|---|---|
| `doc_series` | 3,590 | `doc_id`, `table_id`, `row_key`, `fiscal_year` | auto | キューブ（入力 observation） | `96ae6c398ae0…` |
| `doc_series_meta` | 470 | `doc_id`, `table_id`, `row_key` | auto | document / variable のメタ | `202705d0b57d…` |
| `effort_year` | 57 | `year` | auto | キューブ（入力 occurrence） | `a01031c1c9b3…` |
| `ias_species` | 173 | `ias_category`, `binom` | auto | taxon / taxon_assessment（ADR-0019） | `88cbdb76b28c…` |
| `landuse_change` | 2,904 | `watershed_id`, `landuse_name` | auto | キューブ（入力 observation） | `a594cefb0c43…` |
| `landuse_watershed` | 4,858 | `watershed_id`, `landuse_code` | auto | キューブ（入力 observation） | `db04b41e7324…` |
| `meas_clim` | 192 | `variable`, `month` | auto | キューブ（入力 observation） | `fa96f472a574…` |
| `meas_daily` | 139,530 | `site_id`, `variable`, `d` | auto | キューブ（入力 observation） | `a9ed0998dbf3…` |
| `meas_month` | 127,491 | `site_id`, `variable`, `year`, `month` | auto | キューブ（入力 observation） | `c92c2f07fefe…` |
| `meas_year` | 116,076 | `site_id`, `variable`, `year`, `kind` | auto | キューブ（入力 observation） | `c6f262c2e332…` |
| `mesh_all` | 4,083 | `mlat`, `mlon` | auto | キューブ（入力 occurrence） | `8071eb8670eb…` |
| `mesh_species` | 4,086 | `mlat`, `mlon` | auto | キューブ（入力 occurrence） | `455a82185536…` |
| `mesh_year` | 37,043 | `mlat`, `mlon`, `year` | auto | キューブ（入力 occurrence） | `9e791ab84952…` |
| `org_group_year` | 1,166 | `year`, `source_id`, `taxon_group` | auto | キューブ（入力 occurrence） | `cc527f27b2bf…` |
| `org_norm` | 816,856 | `record_id` | auto | L2 のファクト本体に統合 | `5f250f1e4d91…` |
| `org_watershed` | 287 | `watershed_id` | auto | キューブ（入力 occurrence） | `eacafbea90c0…` |
| `org_watershed_year` | 10,699 | `watershed_id`, `year` | auto | キューブ（入力 occurrence） | `fc10b0e61c6a…` |
| `quality_monthly` | 39 | `ym` | auto | キューブ（入力 observation） | `2f3ba74296da…` |
| `rain_daily` | 3,654 | `d` | auto | キューブ（入力 observation） | `a7790e2f73f2…` |
| `redlist_change` | 2,884 | `assessment_id` | auto | taxon / taxon_assessment（ADR-0019） | `10177e492532…` |
| `redlist_map` | 44 | `raw` | pk | taxon / taxon_assessment（ADR-0019） | `62b0d97d1281…` |
| `sensor_daily` | 352,043 | `site_id`, `datastream`, `d` | auto | キューブ（入力 observation） | `81367b247430…` |
| `sensor_hour_month` | 2,112 | `datastream`, `month`, `hour` | auto | キューブ（入力 observation） | `6839057563cf…` |
| `site_var` | 8,140 | `site_id`, `variable`, `kind` | auto | キューブ（入力 observation） | `d7232dd6093e…` |
| `species2` | 23,618 | `binom` | auto | キューブ（入力 occurrence） | `ad4d57336f59…` |
| `species_mesh_year` | 276,163 | `year`, `mlat`, `mlon`, `binom` | auto | キューブ（入力 occurrence） | `f835fcdf2c67…` |
| `species_month` | 9,997 | `binom`, `month` | auto | キューブ（入力 occurrence） | `88f7706e59a8…` |
| `species_year2` | 116,899 | `year`, `binom` | auto | キューブ（入力 occurrence） | `ba7f4a898f97…` |
| `var_catalog` | 58 | `variable` | auto | variable レジストリ | `9c57c75ef50c…` |
| `watershed_meta` | 377 | `watershed_id` | pk | place の属性 | `f92c68ed26da…` |
| `watershed_rollup` | 377 | `watershed_id` | auto | place の属性 | `3aebcd5b56e4…` |
| `zone_clim` | 619 | `zone`, `variable`, `month` | auto | キューブ（入力 observation） | `eacb0b5b50a2…` |
| `zone_year` | 3,710 | `zone`, `variable`, `year`, `kind` | auto | キューブ（入力 observation） | `a56af9109ae8…` |

## キーの由来の内訳

- `pk`: 2テーブル
- `auto`: 31テーブル

`declared` は0件。33テーブルすべて自動導出できた（`scripts/reconcile/derived_keys.yaml` は現時点で空）。

## 数値列のサマリ

列数が多いテーブルもあるため、数値列ごとの詳細は JSON 側（`numeric_columns`）を参照。
ここでは数値列の個数だけを一覧にする。

| テーブル | 数値列の数 |
|---|---:|
| `doc_series` | 4 |
| `doc_series_meta` | 7 |
| `effort_year` | 6 |
| `ias_species` | 5 |
| `landuse_change` | 3 |
| `landuse_watershed` | 3 |
| `meas_clim` | 5 |
| `meas_daily` | 3 |
| `meas_month` | 4 |
| `meas_year` | 6 |
| `mesh_all` | 6 |
| `mesh_species` | 4 |
| `mesh_year` | 6 |
| `org_group_year` | 4 |
| `org_norm` | 7 |
| `org_watershed` | 5 |
| `org_watershed_year` | 5 |
| `quality_monthly` | 4 |
| `rain_daily` | 2 |
| `redlist_change` | 3 |
| `redlist_map` | 1 |
| `sensor_daily` | 4 |
| `sensor_hour_month` | 5 |
| `site_var` | 4 |
| `species2` | 5 |
| `species_mesh_year` | 4 |
| `species_month` | 2 |
| `species_year2` | 3 |
| `var_catalog` | 7 |
| `watershed_meta` | 4 |
| `watershed_rollup` | 14 |
| `zone_clim` | 5 |
| `zone_year` | 5 |

