# 鹿児島県（奄美大島 `jp-46`）の収集定数の1件取得の確認（Step 1 の完了条件）

確認日: 2026-10-10 / 実施: `docs/plans/AMAMI_STEP0.md` §4 の担当C。データは取り込んでいない（件数・存在の確認のみ）。
値は `scripts/regions.py` の `jp-46`。各リクエストは1.5秒以上の間隔、User-Agent は `scripts/common.py` の `UA`（組織の代表連絡先。個人名なし）。

## GBIF（`gadmGid`、`/v1/occurrence/search?gadmGid=<gid>&limit=0`）

| gid | 自治体（GBIF の `gadm.level2.name`） | count |
|---|---|---|
| `JPN.19_1`（参考: 神奈川県） | — | 664,414 |
| `JPN.18.4_1` | Amami（奄美市） | 25,421 |
| `JPN.18.38_1` | Tatsugō（龍郷町） | 8,872 |
| `JPN.18.41_1` | Uken（宇検村） | 5,417 |
| `JPN.18.44_1` | Yamato（大和村） | 3,934 |
| `JPN.18.34_1` | Setouchi（瀬戸内町） | 4,230 |

書式は `JPN.18.<n>_1`（県 `JPN.18`、市町村 `.<n>`、末尾 `_1`）で確定。各 gid の先頭1件の座標（28.15〜28.46N, 129.3〜129.6E）が奄美大島の範囲にあることも確認した。
（`JPN.46.4_1` を試すと 1,830 件返るが別の地域〔JIS コードを GADM の番号と取り違えた値〕。**GADM の県番号はJISコードと別体系**）

## iNaturalist（`/v1/observations?place_id=<id>&per_page=1`、`total_results`）

| place_id | 名前（`/v1/places/<id>`） | total_results |
|---|---|---|
| 10918（参考: 神奈川県） | — | 176,000 |
| 34051 | Amami | 6,015 |
| 34081 | Setouchi | 2,169 |
| 34085 | Tatsugo | 1,954 |
| 34091 | Yamato | 1,659 |
| 34088 | Uken | 1,886 |

## 気象庁（etrn）

- 観測所表 `select/prefecture.php?prec_no=88`: 名瀬 `47909`（官署 `s`）、古仁屋 `0980`（アメダス `a`）、笠利 `1520`（アメダス `a`）が載っている。
  `prec_no=88` は鹿児島県（奄美地方）。
- 名瀬の月別 `view/monthly_s1.php?prec_no=88&block_no=47909&year=2023`: 表 12行（1〜12月）×28列が取れた
  （1月の現地気圧 1020.4hPa・降水量合計 104.5mm）。

## 水環境総合情報サイト（環境省。`StartCreation` → `download.aspx`、`p_kosui_location`、`prefcode='46'`）

- 測定点マスタの行数 12,451（`nendo` 別の行を含む）、`prefcode` はすべて `46`、絶対コード（`zettaicode`）は 446 地点。
  県全域の値で、奄美大島への絞り込みは取り込み時（Step 1 以降）にする。

## 最高峰の座標（`registry/region.yaml: terrain.summit`、地理院標高API `getelevation.php`）

| 山 | 宣言（座標・標高） | 地理院標高API の標高 |
|---|---|---|
| 蛭ヶ岳（`jp-14`） | 35.4863, 139.1389 / 1673m | 1672.6m（周囲の点は 1566〜1629m で、この点が山頂） |
| 湯湾岳（`jp-46`） | 28.2963, 129.3209 / 694m | 689.2m（周囲 0.0003〜0.001 度の点は 650〜689m。最大は 689.3m〔28.2960, 129.3213〕） |

宣言座標は山頂の画素に一致する。宣言値（694m）は国土地理院の山頂標高で、DEM の最大（約692m）との差は ±20m の検査に収まる。
