# v1 派生テーブルのベースライン指紋（Phase B 受け入れゲート）

`scripts/b01_derived_baseline.py` が `data/db/derived.sqlite`（読み取り専用）から生成する。機械可読な本体は `reports/derived_baseline.json`。このファイルは人が読む要約。

再生成: `.venv/bin/python3 scripts/b01_derived_baseline.py`

テーブル数 **33** / 総行数 **2,070,295**（`data/db/derived.sqlite` より）。

「行き先」列は `docs/adr/0011-aggregation-cube.md` の「33テーブルの行き先」表（`scripts/reconcile/adr0011_destinations.yaml` にデータとして持つ）。

## テーブル一覧

| テーブル | 行数 | キー | キーの由来 | 行き先（ADR-0011） | 内容ハッシュ（先頭12桁） |
|---|---:|---|---|---|---|
| `doc_series` | 3,590 | `doc_id`, `table_id`, `row_key`, `fiscal_year` | auto | キューブ（入力 observation） | `be50c0f5f93f…` |
| `doc_series_meta` | 470 | `doc_id`, `table_id`, `row_key` | auto | document / variable のメタ | `5e85e2297dd3…` |
| `effort_year` | 57 | `year` | auto | キューブ（入力 occurrence） | `dbdefafec3d5…` |
| `ias_species` | 173 | `ias_category`, `binom` | auto | taxon / taxon_assessment（ADR-0019） | `df752c25506e…` |
| `landuse_change` | 2,904 | `watershed_id`, `landuse_name` | auto | キューブ（入力 observation） | `e4617a373bfd…` |
| `landuse_watershed` | 4,858 | `watershed_id`, `landuse_code` | auto | キューブ（入力 observation） | `7c837b116bee…` |
| `meas_clim` | 192 | `variable`, `month` | auto | キューブ（入力 observation） | `bbc99f64e3a4…` |
| `meas_daily` | 139,530 | `site_id`, `variable`, `d` | auto | キューブ（入力 observation） | `a28416972a6c…` |
| `meas_month` | 127,491 | `site_id`, `variable`, `year`, `month` | auto | キューブ（入力 observation） | `8c4030407415…` |
| `meas_year` | 116,076 | `site_id`, `variable`, `year`, `kind` | auto | キューブ（入力 observation） | `d97d87917878…` |
| `mesh_all` | 4,083 | `mlat`, `mlon` | auto | キューブ（入力 occurrence） | `03880f7e3c17…` |
| `mesh_species` | 4,086 | `mlat`, `mlon` | auto | キューブ（入力 occurrence） | `684c86e520b9…` |
| `mesh_year` | 37,043 | `mlat`, `mlon`, `year` | auto | キューブ（入力 occurrence） | `43e89c9ed6a7…` |
| `org_group_year` | 1,166 | `year`, `source_id`, `taxon_group` | auto | キューブ（入力 occurrence） | `39f1f9466618…` |
| `org_norm` | 816,856 | `record_id` | auto | L2 のファクト本体に統合 | `7885aaedc39e…` |
| `org_watershed` | 287 | `watershed_id` | auto | キューブ（入力 occurrence） | `3549af8bea37…` |
| `org_watershed_year` | 10,699 | `watershed_id`, `year` | auto | キューブ（入力 occurrence） | `b67fc5065b1d…` |
| `quality_monthly` | 39 | `ym` | auto | キューブ（入力 observation） | `b3c8ee83be0c…` |
| `rain_daily` | 3,654 | `d` | auto | キューブ（入力 observation） | `a28b6bb775d4…` |
| `redlist_change` | 2,884 | `assessment_id` | auto | taxon / taxon_assessment（ADR-0019） | `d16b457c6520…` |
| `redlist_map` | 44 | `raw` | pk | taxon / taxon_assessment（ADR-0019） | `f4fde3888c99…` |
| `sensor_daily` | 352,043 | `site_id`, `datastream`, `d` | auto | キューブ（入力 observation） | `7e4eaca07b03…` |
| `sensor_hour_month` | 2,112 | `datastream`, `month`, `hour` | auto | キューブ（入力 observation） | `620cedc0438d…` |
| `site_var` | 8,140 | `site_id`, `variable`, `kind` | auto | キューブ（入力 observation） | `955053147dae…` |
| `species2` | 23,618 | `binom` | auto | キューブ（入力 occurrence） | `f12a75184451…` |
| `species_mesh_year` | 276,163 | `year`, `mlat`, `mlon`, `binom` | auto | キューブ（入力 occurrence） | `6b8ec0b3ae53…` |
| `species_month` | 9,997 | `binom`, `month` | auto | キューブ（入力 occurrence） | `9f5f29fa7da8…` |
| `species_year2` | 116,899 | `year`, `binom` | auto | キューブ（入力 occurrence） | `b84445374b82…` |
| `var_catalog` | 58 | `variable` | auto | variable レジストリ | `5d998272632f…` |
| `watershed_meta` | 377 | `watershed_id` | pk | place の属性 | `b1c5ab27b15c…` |
| `watershed_rollup` | 377 | `watershed_id` | auto | place の属性 | `a4993f6e6ee5…` |
| `zone_clim` | 619 | `zone`, `variable`, `month` | auto | キューブ（入力 observation） | `cda4be8b6928…` |
| `zone_year` | 3,710 | `zone`, `variable`, `year`, `kind` | auto | キューブ（入力 observation） | `b3473f8394c3…` |

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

