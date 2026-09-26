# serving-diff レポート

- git HEAD: `19d87fc7c18bb99a4d61c7a36c9cdc99aab8bd56`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `55a8c2c4c1409a691f31a2e25e21b4bd6d6db2b3fd0f7852837c7d6bd60613f2`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `lod` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-09-26T17:33:40.009Z
- 所要時間: 281.5s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | rain_div10 | day_split | synthetic_excluded | lod_imputation | unit_label_registry | float_rounding | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 24 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 5 |
| sites_list | 1 | 352 | 352 | 328 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8114 | 3034 | 2 | 0 | 0 | 80 | 4407 | 4149 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 21 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1078 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 115 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 115918 | 37697 | 9 | 0 | 0 | 320 | 65656 | 71187 | 0 | 0 |
| month_series_site | 1966 | 127491 | 126163 | 113075 | 2 | 0 | 0 | 2002 | 12414 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 137350 | 124837 | 2 | 0 | 0 | 2203 | 12490 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81250 | 25981 | 0 | 0 | 0 | 144 | 46184 | 50435 | 0 | 0 |
| zone_series | 61 | 3710 | 3692 | 915 | 0 | 0 | 0 | 63 | 2458 | 2281 | 0 | 9 |
| climatology | 16 | 192 | 192 | 41 | 0 | 0 | 0 | 45 | 91 | 12 | 0 | 15 |
| zone_climatology | 16 | 619 | 595 | 185 | 0 | 0 | 0 | 180 | 218 | 40 | 0 | 36 |
| variable_catalog_by_variable | 1 | 53 | 53 | 21 | 0 | 0 | 0 | 4 | 0 | 28 | 0 | 1 |
| site_variables_by_variable | 250 | 7573 | 7547 | 2643 | 0 | 0 | 0 | 80 | 4390 | 3990 | 0 | 2 |
| year_series_site_by_variable | 7569 | 105164 | 104750 | 32645 | 0 | 0 | 0 | 320 | 65559 | 65175 | 0 | 258 |
| month_series_site_by_variable | 1966 | 127491 | 126163 | 113075 | 0 | 0 | 0 | 2002 | 12414 | 0 | 0 | 2 |
| day_series_site_by_variable | 1966 | 139530 | 137350 | 124837 | 0 | 0 | 0 | 2203 | 12490 | 0 | 0 | 2 |
| zone_series_by_variable | 159 | 3389 | 3371 | 778 | 0 | 0 | 0 | 63 | 2434 | 2121 | 0 | 9 |
| climatology_by_variable | 53 | 192 | 192 | 41 | 0 | 0 | 0 | 45 | 91 | 12 | 0 | 15 |
| zone_climatology_by_variable | 53 | 619 | 595 | 185 | 0 | 0 | 0 | 180 | 218 | 40 | 0 | 36 |
| water_bodies_for_variable_by_variable | 53 | 978 | 978 | 964 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

合計: runs=26007 rows_v1=863723 rows_v2=855963 matched=582543 unexplained=390
lod_moved（zero→lod で値が動いたと確認できたキー数の合計。上表の `lod_imputation` 列と同じ）: 241514

## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）

| table | key | kind |
| --- | --- | --- |
| meas_clim | ["浮遊物質量 SS",10] | value_diff |
| meas_clim | ["浮遊物質量 SS",11] | value_diff |
| var_catalog | ["浮遊物質量 SS"] | value_diff |

## unexplained の先頭20件

| query | params | kind | key | columns |
| --- | --- | --- | --- | --- |
| variable_catalog | {} | value_diff | ["溶存酸素量 DO"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["pH"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["浮遊物質量 SS"] | n,n_sites,y_to,n_daily,n_annual,n_censored |
| variable_catalog | {} | value_diff | ["気温"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["水温"] | n,n_sites,y_to,n_daily |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [3,2023] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [3,2024] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [3,2025] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [4,2023] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [4,2024] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [4,2025] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [5,2023] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [5,2024] | n_sites,n,avg |
| zone_series | {"alias":"浮遊物質量 SS","kind":"daily"} | value_diff | [5,2025] | n_sites,n,avg |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [1] | n,avg,min |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [2] | n,avg,min |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [3] | n,avg,min |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [4] | n,avg,min |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [5] | n,avg,min |
| climatology | {"alias":"浮遊物質量 SS"} | value_diff | [6] | n,avg,min |

