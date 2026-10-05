# serving-diff レポート

- git HEAD: `57bf331744dfa89cad617c412bcfa7689d3e8710`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `2112cfc3ff09e8fb6cef1be59783381f41bdb2cb8ca751cd702067415142fffa`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `lod` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-10-05T13:36:23.051Z
- 所要時間: 213.8s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | day_split | synthetic_excluded | lod_imputation | unit_label_registry | float_rounding | watershed_memo | species_n_definition | month_cell_membership | vernacular_label_rule | undated_excluded | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 24 | 1 | 0 | 5 | 0 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sites_list | 1 | 352 | 352 | 328 | 0 | 0 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8114 | 3034 | 2 | 0 | 80 | 4409 | 4149 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 21 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1078 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 115 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 115918 | 37697 | 9 | 0 | 320 | 65665 | 71187 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| month_series_site | 1966 | 127491 | 126163 | 113075 | 2 | 0 | 2002 | 12414 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 137350 | 124837 | 2 | 0 | 2203 | 12490 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81250 | 25981 | 0 | 0 | 144 | 46184 | 50435 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_series | 61 | 3710 | 3692 | 915 | 0 | 0 | 72 | 2467 | 2281 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| climatology | 16 | 192 | 192 | 41 | 2 | 0 | 60 | 106 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_climatology | 16 | 619 | 595 | 185 | 0 | 0 | 216 | 254 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| variable_catalog_by_variable | 1 | 53 | 53 | 21 | 1 | 0 | 5 | 0 | 28 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| site_variables_by_variable | 250 | 7573 | 7547 | 2643 | 2 | 0 | 80 | 4392 | 3990 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_site_by_variable | 7569 | 105164 | 105006 | 32894 | 9 | 0 | 320 | 65568 | 65175 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| month_series_site_by_variable | 1966 | 127491 | 126163 | 113075 | 2 | 0 | 2002 | 12414 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| day_series_site_by_variable | 1966 | 139530 | 137350 | 124837 | 2 | 0 | 2203 | 12490 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_series_by_variable | 159 | 3389 | 3371 | 778 | 0 | 0 | 72 | 2443 | 2121 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| climatology_by_variable | 53 | 192 | 192 | 41 | 2 | 0 | 60 | 106 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| zone_climatology_by_variable | 53 | 619 | 595 | 185 | 0 | 0 | 216 | 254 | 40 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable_by_variable | 53 | 978 | 978 | 964 | 0 | 0 | 14 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| effort_years | 1 | 37 | 37 | 37 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| taxon_group_years | 1 | 588 | 588 | 588 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_catalog | 1 | 23618 | 23618 | 20780 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2837 | 0 | 0 |
| species_labels | 1 | 23618 | 23618 | 20781 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2837 | 0 | 0 |
| species_years | 1702 | 31955 | 31955 | 31955 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_months | 1702 | 9997 | 9997 | 9978 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 19 | 0 | 0 | 0 |
| species_mesh_years | 1702 | 276163 | 276163 | 276163 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| species_share_trend | 34 | 246 | 246 | 172 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 74 | 0 | 0 |
| mesh_all | 1 | 4083 | 4083 | 4083 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| mesh_by_year | 57 | 37043 | 37043 | 37043 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ias_species | 1 | 173 | 173 | 173 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_summary | 1 | 30 | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_flows | 18 | 308 | 308 | 308 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| redlist_species | 18 | 4080 | 4080 | 4080 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| biota_totals | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| watershed_rollup | 1 | 287 | 287 | 101 | 0 | 0 | 0 | 0 | 0 | 0 | 186 | 0 | 0 | 0 | 0 | 0 |
| watershed_year | 1 | 10699 | 10684 | 9515 | 0 | 0 | 0 | 0 | 0 | 0 | 1090 | 371 | 0 | 0 | 0 | 0 |

合計: runs=31250 rows_v1=1286649 rows_v2=1279130 matched=998579 unexplained=0
lod_moved（zero→lod で値が動いたと確認できたキー数の合計。上表の `lod_imputation` 列と同じ）: 241656

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

