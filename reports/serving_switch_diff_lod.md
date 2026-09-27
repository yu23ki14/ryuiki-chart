# serving-diff レポート

- git HEAD: `2ebb02dd0d7c81d8834f8f878c1a1af5c033b588`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `55a8c2c4c1409a691f31a2e25e21b4bd6d6db2b3fd0f7852837c7d6bd60613f2`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `lod` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-09-27T03:23:09.428Z
- 所要時間: 263.0s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | day_split | synthetic_excluded | lod_imputation | unit_label_registry | float_rounding | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 24 | 1 | 0 | 5 | 0 | 30 | 0 | 0 |
| sites_list | 1 | 352 | 352 | 328 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8114 | 3034 | 2 | 0 | 80 | 4409 | 4149 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 21 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1078 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 115 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 115918 | 37697 | 9 | 0 | 320 | 65665 | 71187 | 0 | 0 |
| month_series_site | 1966 | 127491 | 126163 | 113075 | 2 | 0 | 2002 | 12414 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 137350 | 124837 | 2 | 0 | 2203 | 12490 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81250 | 25981 | 0 | 0 | 144 | 46184 | 50435 | 0 | 0 |
| zone_series | 61 | 3710 | 3692 | 915 | 0 | 0 | 72 | 2467 | 2281 | 0 | 0 |
| climatology | 16 | 192 | 192 | 41 | 2 | 0 | 60 | 106 | 12 | 0 | 0 |
| zone_climatology | 16 | 619 | 595 | 185 | 0 | 0 | 216 | 254 | 40 | 0 | 0 |
| variable_catalog_by_variable | 1 | 53 | 53 | 21 | 1 | 0 | 5 | 0 | 28 | 0 | 0 |
| site_variables_by_variable | 250 | 7573 | 7547 | 2643 | 2 | 0 | 80 | 4392 | 3990 | 0 | 0 |
| year_series_site_by_variable | 7569 | 105164 | 105006 | 32894 | 9 | 0 | 320 | 65568 | 65175 | 0 | 0 |
| month_series_site_by_variable | 1966 | 127491 | 126163 | 113075 | 2 | 0 | 2002 | 12414 | 0 | 0 | 0 |
| day_series_site_by_variable | 1966 | 139530 | 137350 | 124837 | 2 | 0 | 2203 | 12490 | 0 | 0 | 0 |
| zone_series_by_variable | 159 | 3389 | 3371 | 778 | 0 | 0 | 72 | 2443 | 2121 | 0 | 0 |
| climatology_by_variable | 53 | 192 | 192 | 41 | 2 | 0 | 60 | 106 | 12 | 0 | 0 |
| zone_climatology_by_variable | 53 | 619 | 595 | 185 | 0 | 0 | 216 | 254 | 40 | 0 | 0 |
| water_bodies_for_variable_by_variable | 53 | 978 | 978 | 964 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

合計: runs=26007 rows_v1=863723 rows_v2=856219 matched=582792 unexplained=0
lod_moved（zero→lod で値が動いたと確認できたキー数の合計。上表の `lod_imputation` 列と同じ）: 241656

## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）

（無し。宣言済み差分は全て少なくとも1回は使われた）

## unexplained の先頭20件

（無し）

## 変異テスト（`--mutate`）

| mutation | unexplained | 検出できたか |
| --- | --- | --- |
| day_split_rule_off | 12 | OK |
| declared_rot | 2 | OK |
| drop_series | 424624 | OK |
| include_watershed_cells | 0 | OK |
| lod_instead_of_zero | 199516 | OK |
| merge_rule_off | 381251 | OK |
| month_off_by_one | 129895 | OK |
| no_unit | 125974 | OK |
| swap_kind | 79526 | OK |
| synthetic_rule_off | 10129 | OK |
| lod_rule_off | 241656 | OK |
