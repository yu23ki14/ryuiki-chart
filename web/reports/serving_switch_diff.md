# serving-diff レポート

- git HEAD: `66f09897afd71e136d2a9cdea9407411cef3be40`
- v2 pipeline_fingerprint: `phase-b-fact-slice/v1`
- registry_build.input_fingerprint: `0d15a54a95412137edefe9967a2add24f9f0e53fe06db8bdacb159c4d1e4abb3`
- better-sqlite3 の SQLite 版: `3.53.4`
- imputation: `zero` / expand: `all` / v1-source: `derived`
- 生成日時: 2026-09-26T09:42:48.115Z
- 所要時間: 854.1s

## 問い合わせごとの集計

| id | runs | rows_v1 | rows_v2 | matched | declared | rain_div10 | day_split | synthetic_excluded | unit_label_registry | float_rounding | unexplained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| variable_catalog | 1 | 58 | 58 | 27 | 1 | 0 | 0 | 0 | 30 | 0 | 0 |
| sites_list | 1 | 352 | 352 | 352 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| site_variables | 250 | 8140 | 8140 | 3983 | 2 | 0 | 0 | 0 | 4155 | 0 | 0 |
| water_bodies | 1 | 26 | 26 | 26 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| water_bodies_for_variable | 58 | 1092 | 1092 | 1092 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| sites_in_water_body | 26 | 127 | 127 | 127 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_site | 8140 | 116076 | 116076 | 44838 | 9 | 0 | 0 | 0 | 71229 | 0 | 0 |
| month_series_site | 1966 | 127491 | 127493 | 127491 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| day_series_site | 1966 | 139530 | 139532 | 139530 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| year_series_water | 1432 | 81286 | 81286 | 30839 | 0 | 0 | 0 | 0 | 50447 | 0 | 0 |
| zone_series | 61 | 3710 | 3710 | 1425 | 0 | 0 | 0 | 0 | 2285 | 0 | 0 |
| climatology | 16 | 192 | 192 | 178 | 2 | 0 | 0 | 0 | 12 | 0 | 0 |
| zone_climatology | 16 | 619 | 619 | 571 | 0 | 0 | 0 | 0 | 48 | 0 | 0 |
| rain_daily | 1 | 3654 | 3653 | 2456 | 0 | 649 | 549 | 0 | 0 | 0 | 0 |
| rain_monthly_clim | 1 | 12 | 12 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 0 |
| rain_top_days | 1 | 10 | 10 | 0 | 0 | 1 | 13 | 0 | 0 | 0 | 0 |
| longitudinal_highlight | 2 | 23 | 23 | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

合計: runs=13939 rows_v1=482398 rows_v2=482401 matched=352958 unexplained=0

## 宣言済み差分の腐り（対象問い合わせが1件も対応しなかった宣言）

（無し。宣言済み差分は全て少なくとも1回は使われた）

## unexplained の先頭20件

（無し）

## 変異テスト（`--mutate`）

| mutation | unexplained | 検出できたか |
| --- | --- | --- |
| lod_instead_of_zero | 122525 | OK |
| drop_series | 239265 | OK |
| swap_kind | 77729 | OK |
| no_unit | 81232 | OK |
| month_off_by_one | 132730 | OK |
| include_watershed_cells | 0 | OK |
| rain_no_div10_rule | 650 | OK |
| day_split_rule_off | 574 | OK |
| declared_rot | 1 | OK |
