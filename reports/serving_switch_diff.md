# serving-diff レポート

- git HEAD: `00daf69fed5dc07b7d980b2e56b7534b2956fde1`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `55a8c2c4c1409a691f31a2e25e21b4bd6d6db2b3fd0f7852837c7d6bd60613f2`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `zero` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-09-26T17:40:28.307Z
- 所要時間: 225.0s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | rain_div10 | day_split | synthetic_excluded | lod_imputation | unit_label_registry | float_rounding | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 24 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 5 |
| sites_list | 1 | 352 | 352 | 328 | 0 | 0 | 0 | 24 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8114 | 3927 | 2 | 0 | 0 | 80 | 0 | 4149 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 21 | 0 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1078 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 115 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 115918 | 44614 | 9 | 0 | 0 | 320 | 0 | 71187 | 0 | 0 |
| month_series_site | 1966 | 127491 | 126163 | 125489 | 2 | 0 | 0 | 2002 | 0 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 137350 | 137327 | 2 | 0 | 0 | 2203 | 0 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81250 | 30743 | 0 | 0 | 0 | 144 | 0 | 50435 | 0 | 0 |
| zone_series | 61 | 3710 | 3692 | 1369 | 0 | 0 | 0 | 72 | 0 | 2281 | 0 | 0 |
| climatology | 16 | 192 | 192 | 132 | 2 | 0 | 0 | 58 | 0 | 12 | 0 | 0 |
| zone_climatology | 16 | 619 | 595 | 403 | 0 | 0 | 0 | 216 | 0 | 40 | 0 | 0 |
| variable_catalog_by_variable | 1 | 53 | 53 | 21 | 0 | 0 | 0 | 4 | 0 | 28 | 0 | 1 |
| site_variables_by_variable | 250 | 7573 | 7547 | 3519 | 0 | 0 | 0 | 80 | 0 | 3990 | 0 | 2 |
| year_series_site_by_variable | 7569 | 105164 | 104750 | 39465 | 0 | 0 | 0 | 320 | 0 | 65175 | 0 | 258 |
| month_series_site_by_variable | 1966 | 127491 | 126163 | 125489 | 0 | 0 | 0 | 2002 | 0 | 0 | 0 | 2 |
| day_series_site_by_variable | 1966 | 139530 | 137350 | 137327 | 0 | 0 | 0 | 2203 | 0 | 0 | 0 | 2 |
| zone_series_by_variable | 159 | 3389 | 3371 | 1208 | 0 | 0 | 0 | 72 | 0 | 2121 | 0 | 0 |
| climatology_by_variable | 53 | 192 | 192 | 132 | 0 | 0 | 0 | 58 | 0 | 12 | 0 | 2 |
| zone_climatology_by_variable | 53 | 619 | 595 | 403 | 0 | 0 | 0 | 216 | 0 | 40 | 0 | 0 |
| water_bodies_for_variable_by_variable | 53 | 978 | 978 | 964 | 0 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

合計: runs=26007 rows_v1=863723 rows_v2=855963 matched=654121 unexplained=272


## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）

| table | key | kind |
| --- | --- | --- |
| var_catalog | ["浮遊物質量 SS"] | value_diff |

## unexplained の先頭20件

| query | params | kind | key | columns |
| --- | --- | --- | --- | --- |
| variable_catalog | {} | value_diff | ["溶存酸素量 DO"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["pH"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["浮遊物質量 SS"] | n,n_sites,y_to,n_daily,n_annual,n_censored |
| variable_catalog | {} | value_diff | ["気温"] | n,n_sites,y_to,n_daily |
| variable_catalog | {} | value_diff | ["水温"] | n,n_sites,y_to,n_daily |
| variable_catalog_by_variable | {} | value_diff | ["common:variable:water.ss"] | n,n_places,y_to,n_censored |
| site_variables_by_variable | {"site_id":"atsugi_river_water_quality__中津川"} | value_diff | ["common:variable:water.ss","day"] | n,avg |
| site_variables_by_variable | {"site_id":"atsugi_river_water_quality__中津川"} | value_diff | ["common:variable:water.ss","fiscal_year"] | n,avg |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2005] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2006] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2007] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2008] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2009] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2010] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2011] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2012] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2013] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2014] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2015] |  |
| year_series_site_by_variable | {"variable_id":"common:variable:water.cod","site_id":"atsugi_river_water_quality__中津川","basis":"fiscal_year"} | row_only_in_v1 | [2016] |  |

