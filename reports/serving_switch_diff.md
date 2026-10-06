# serving-diff レポート

- git HEAD: `a6e9a3db8d80d418d873dd92309a30c6e3ebcd8f`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `2112cfc3ff09e8fb6cef1be59783381f41bdb2cb8ca751cd702067415142fffa`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `zero` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-10-05T14:56:34.510Z
- 所要時間: 211.9s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | day_split | synthetic_excluded | lod_imputation | unit_label_registry | float_rounding | watershed_memo | species_n_definition | month_cell_membership | vernacular_label_rule | undated_excluded | doc_label_rule | doc_warning_scope | doc_year_collapse | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 24 | 1 | 0 | 5 | 0 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sites_list | 1 | 352 | 352 | 328 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8114 | 3927 | 2 | 0 | 80 | 0 | 4149 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 21 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1078 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 115 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 115918 | 44614 | 9 | 0 | 320 | 0 | 71187 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| month_series_site | 1966 | 127491 | 126163 | 125489 | 2 | 0 | 2002 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 137350 | 137327 | 2 | 0 | 2203 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81250 | 30743 | 0 | 0 | 144 | 0 | 50435 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_series | 61 | 3710 | 3692 | 1369 | 0 | 0 | 72 | 0 | 2281 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| climatology | 16 | 192 | 192 | 132 | 2 | 0 | 60 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_climatology | 16 | 619 | 595 | 403 | 0 | 0 | 216 | 0 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| variable_catalog_by_variable | 1 | 53 | 53 | 21 | 1 | 0 | 5 | 0 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| site_variables_by_variable | 250 | 7573 | 7547 | 3519 | 2 | 0 | 80 | 0 | 3990 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_site_by_variable | 7569 | 105164 | 105006 | 39714 | 9 | 0 | 320 | 0 | 65175 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| month_series_site_by_variable | 1966 | 127491 | 126163 | 125489 | 2 | 0 | 2002 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day_series_site_by_variable | 1966 | 139530 | 137350 | 137327 | 2 | 0 | 2203 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_series_by_variable | 159 | 3389 | 3371 | 1208 | 0 | 0 | 72 | 0 | 2121 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| climatology_by_variable | 53 | 192 | 192 | 132 | 2 | 0 | 60 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_climatology_by_variable | 53 | 619 | 595 | 403 | 0 | 0 | 216 | 0 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable_by_variable | 53 | 978 | 978 | 964 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| effort_years | 1 | 37 | 37 | 37 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| taxon_group_years | 1 | 588 | 588 | 588 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_catalog | 1 | 23618 | 23618 | 20780 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2837 | 0 | 0 | 0 | 0 | 0 |
| species_labels | 1 | 23618 | 23618 | 20781 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2837 | 0 | 0 | 0 | 0 | 0 |
| species_years | 1702 | 31955 | 31955 | 31955 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_months | 1702 | 9997 | 9997 | 9978 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 19 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_mesh_years | 1702 | 276163 | 276163 | 276163 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_share_trend | 34 | 246 | 246 | 172 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 74 | 0 | 0 | 0 | 0 | 0 |
| mesh_all | 1 | 4083 | 4083 | 4083 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mesh_by_year | 57 | 37043 | 37043 | 37043 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ias_species | 1 | 173 | 173 | 173 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_summary | 1 | 30 | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_flows | 18 | 308 | 308 | 308 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_species | 18 | 4080 | 4080 | 4080 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| biota_totals | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| watershed_rollup | 1 | 377 | 377 | 191 | 0 | 0 | 0 | 0 | 0 | 0 | 186 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| watershed_year | 1 | 10699 | 10684 | 9515 | 0 | 0 | 0 | 0 | 0 | 0 | 1090 | 371 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| doc_series_meta | 1 | 470 | 414 | 163 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 20 | 245 | 61 | 0 |
| doc_series_points | 470 | 3293 | 3050 | 3050 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 243 | 0 |
| overview_counts | 1 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| landuse_highlight | 1 | 8 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

合計: runs=31723 rows_v1=1290511 rows_v2=1282693 matched=1073469 unexplained=0


## 生物系の規則ごとの moved（PR-3b）

| rule | query | moved（キー数） |
| --- | --- | --- |
| vernacular_label_rule | species_catalog | 2837 |
| vernacular_label_rule | species_labels | 2837 |
| month_cell_membership | species_months | 19 |
| vernacular_label_rule | species_share_trend | 74 |
| undated_excluded | biota_totals | 1 |
| watershed_memo | watershed_rollup | 186 |
| watershed_memo | watershed_year | 1090 |
| species_n_definition | watershed_year | 371 |

## 文書系列の規則ごとの moved（PR-4）

| rule | query | moved（キー数） |
| --- | --- | --- |
| doc_label_rule | doc_series_meta | 20 |
| doc_warning_scope | doc_series_meta | 245 |
| doc_year_collapse | doc_series_meta | 61 |
| doc_year_collapse | doc_series_points | 243 |

廃止列（比べない。D2）: `overview_counts` の `n_meas`・`n_sensor`・`n_events`

### 表示名の動き（`vernacular_label_rule` の label_moved）

| query | label_moved（v1→v2 の文字種） | 件数 |
| --- | --- | --- |
| species_catalog | 日本語→学名のみ | 1186 |
| species_catalog | 日本語→日本語 | 593 |
| species_catalog | 英名等→学名のみ | 270 |
| species_catalog | 学名のみ→日本語 | 255 |
| species_catalog | 英名等→日本語 | 200 |
| species_catalog | 中国語等→日本語 | 167 |
| species_catalog | 英名等→英名等 | 71 |
| species_catalog | 日本語→英名等 | 64 |
| species_catalog | 中国語等→学名のみ | 23 |
| species_catalog | 学名のみ→英名等 | 5 |
| species_catalog | 中国語等→英名等 | 3 |
| species_labels | 日本語→学名のみ | 1186 |
| species_labels | 日本語→日本語 | 593 |
| species_labels | 英名等→学名のみ | 270 |
| species_labels | 学名のみ→日本語 | 255 |
| species_labels | 英名等→日本語 | 200 |
| species_labels | 中国語等→日本語 | 167 |
| species_labels | 英名等→英名等 | 71 |
| species_labels | 日本語→英名等 | 64 |
| species_labels | 中国語等→学名のみ | 23 |
| species_labels | 学名のみ→英名等 | 5 |
| species_labels | 中国語等→英名等 | 3 |
| species_share_trend | 日本語→日本語 | 30 |
| species_share_trend | 中国語等→日本語 | 21 |
| species_share_trend | 英名等→英名等 | 16 |
| species_share_trend | 日本語→英名等 | 4 |
| species_share_trend | 日本語→学名のみ | 2 |
| species_share_trend | 英名等→日本語 | 1 |

## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）

（無し。宣言済み差分は全て少なくとも1回は使われた）

## unexplained の先頭20件

（無し）

## 変異テスト（`--mutate`）

| mutation | unexplained | 検出できたか |
| --- | --- | --- |
| lod_instead_of_zero | 199516 | OK |
| drop_series | 636484 | OK |
| swap_kind | 77560 | OK |
| no_unit | 126544 | OK |
| month_off_by_one | 142631 | OK |
| include_watershed_cells | 0 | OK |
| label_wrong | 1 | OK |
| drop_species_rows | 31955 | OK |
| inflate_n | 37254 | OK |
| doc_label_wrong | 1 | OK |
| doc_drop_point | 432 | OK |
| inflate_site_n | 377 | OK |
| day_split_rule_off | 12 | OK |
| declared_rot | 2 | OK |
| synthetic_rule_off | 10129 | OK |
| memo_rule_off | 1276 | OK |
| species_n_rule_off | 371 | OK |
| month_rule_off | 19 | OK |
| label_rule_off | 5748 | OK |
| undated_rule_off | 1 | OK |
| doc_label_rule_off | 20 | OK |
| doc_warning_rule_off | 245 | OK |
| doc_collapse_rule_off | 304 | OK |
| merge_rule_off | 381251 | OK |

- skipped: `lod_rule_off`（lod 実行のみ（現在は zero））
