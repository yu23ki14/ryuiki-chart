# v1 派生テーブルのベースライン指紋（Phase B 受け入れゲート）

`scripts/b01_derived_baseline.py` が `data/db/derived.sqlite`（読み取り専用）から生成する。機械可読な本体は `reports/derived_baseline.json`。このファイルは人が読む要約。

再生成: `.venv/bin/python3 scripts/b01_derived_baseline.py`

テーブル数 **33** / 総行数 **56,282**（`data/db/derived.sqlite` より）。

「行き先」列は `docs/adr/0011-aggregation-cube.md` の「33テーブルの行き先」表（`scripts/reconcile/adr0011_destinations.yaml` にデータとして持つ）。

## テーブル一覧

| テーブル | 行数 | キー | キーの由来 | 行き先（ADR-0011） | 内容ハッシュ（先頭12桁） |
|---|---:|---|---|---|---|
| `doc_series` | 115 | `doc_id`, `table_id`, `row_key`, `fiscal_year` | declared | document/cell の証跡層からの射影 | `0a6217da96b9…` |
| `doc_series_meta` | 23 | `doc_id`, `table_id`, `row_key` | declared | document/cell の証跡層からの射影 | `0ba4658fe26d…` |
| `effort_year` | 21 | `year` | declared | キューブ（入力 occurrence） | `c382e59a5d74…` |
| `ias_species` | 12 | `ias_category`, `binom` | declared | taxon / taxon_assessment（ADR-0019） | `8cd31d9760a8…` |
| `landuse_change` | 2,904 | `watershed_id`, `landuse_name` | declared | キューブ（入力 observation） | `a594cefb0c43…` |
| `landuse_watershed` | 4,858 | `watershed_id`, `landuse_code` | declared | キューブ（入力 observation） | `db04b41e7324…` |
| `meas_clim` | 148 | `variable`, `month` | declared | キューブ（入力 observation） | `b04b32e7d7e3…` |
| `meas_daily` | 18,823 | `site_id`, `variable`, `d` | declared | キューブ（入力 observation） | `a7593c18a0b7…` |
| `meas_month` | 16,300 | `site_id`, `variable`, `year`, `month` | declared | キューブ（入力 observation） | `0aee543cf3b4…` |
| `meas_year` | 6,915 | `site_id`, `variable`, `year`, `kind` | declared | キューブ（入力 observation） | `25372127021d…` |
| `mesh_all` | 87 | `mlat`, `mlon` | declared | キューブ（入力 occurrence） | `a4595aa2e563…` |
| `mesh_species` | 89 | `mlat`, `mlon` | declared | キューブ（入力 occurrence） | `7b818167d435…` |
| `mesh_year` | 92 | `mlat`, `mlon`, `year` | declared | キューブ（入力 occurrence） | `41f485fcfbf4…` |
| `org_group_year` | 36 | `year`, `source_id`, `taxon_group` | declared | キューブ（入力 occurrence） | `74952d63456d…` |
| `org_norm` | 207 | `record_id` | declared | L2 のファクト本体に統合 | `5a2502161505…` |
| `org_watershed` | 52 | `watershed_id` | declared | キューブ（入力 occurrence） | `b6dc2aec2a16…` |
| `org_watershed_year` | 70 | `watershed_id`, `year` | declared | キューブ（入力 occurrence） | `dbcd3dc77ddd…` |
| `quality_monthly` | 39 | `ym` | declared | ADR-0017 書き込み系ログの射影 | `2f3ba74296da…` |
| `rain_daily` | 1 | `d` | declared | キューブ（入力 observation） | `81c589e45653…` |
| `redlist_change` | 2,884 | `assessment_id` | declared | taxon / taxon_assessment（ADR-0019） | `10177e492532…` |
| `redlist_map` | 44 | `raw` | pk | taxon / taxon_assessment（ADR-0019） | `62b0d97d1281…` |
| `sensor_daily` | 39 | `site_id`, `datastream`, `d` | declared | キューブ（入力 observation） | `4f4c50f4d06d…` |
| `sensor_hour_month` | 24 | `datastream`, `month`, `hour` | declared | キューブ（入力 observation） | `107cded1f0ad…` |
| `site_var` | 519 | `site_id`, `variable`, `kind` | declared | キューブ（入力 observation） | `9f72bdcf91d5…` |
| `species2` | 129 | `binom` | declared | キューブ（入力 occurrence） | `bae00385a6a6…` |
| `species_mesh_year` | 0 | `year`, `mlat`, `mlon`, `binom` | declared | キューブ（入力 occurrence） | `e3b0c44298fc…` |
| `species_month` | 0 | `binom`, `month` | declared | キューブ（入力 occurrence） | `e3b0c44298fc…` |
| `species_year2` | 133 | `year`, `binom` | declared | キューブ（入力 occurrence） | `d8990c7e2368…` |
| `var_catalog` | 25 | `variable` | declared | variable レジストリ | `62f855bc45c2…` |
| `watershed_meta` | 377 | `watershed_id` | pk | place の属性 | `f92c68ed26da…` |
| `watershed_rollup` | 377 | `watershed_id` | declared | place の属性 | `769a82a3d6e6…` |
| `zone_clim` | 328 | `zone`, `variable`, `month` | declared | キューブ（入力 observation） | `5ee6e843129e…` |
| `zone_year` | 611 | `zone`, `variable`, `year`, `kind` | declared | キューブ（入力 observation） | `87079799051d…` |

## キーの由来の内訳

- `pk`: 2テーブル
- `declared`: 31テーブル

`declared`（`scripts/reconcile/derived_keys.yaml` の宣言に頼ったテーブル）。宣言キーには「なぜ自動で決まらないか」の理由（`derived_keys.yaml` の`reason`）を必ず添えることになっているので、ここにその理由も出す:

- `doc_series`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `doc_series_meta`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `effort_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `ias_species`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `landuse_change`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `landuse_watershed`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `meas_clim`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `meas_daily`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `meas_month`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `meas_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `mesh_all`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `mesh_species`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `mesh_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `org_group_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `org_norm`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `org_watershed`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `org_watershed_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `quality_monthly`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `rain_daily`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `redlist_change`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `sensor_daily`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `sensor_hour_month`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `site_var`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `species2`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `species_mesh_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `species_month`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `species_year2`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `var_catalog`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `watershed_rollup`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `zone_clim`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。
- `zone_year`: sample: 全量ベースライン（reports/derived_baseline.json）の自動導出キーをそのまま宣言化。サンプルでは行数が少ないため、探索A/Bに任せると別の短い組み合わせで偶然一意になりうる。

## 数値列のサマリ

列数が多いテーブルもあるため、数値列ごとの詳細は JSON 側（`numeric_columns`）を参照。
ここでは数値列の個数だけを一覧にする。

| テーブル | 数値列の数 |
|---|---:|
| `doc_series` | 5 |
| `doc_series_meta` | 8 |
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
| `species_mesh_year` | 5 |
| `species_month` | 3 |
| `species_year2` | 3 |
| `var_catalog` | 7 |
| `watershed_meta` | 4 |
| `watershed_rollup` | 14 |
| `zone_clim` | 5 |
| `zone_year` | 5 |

