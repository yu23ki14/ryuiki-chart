# ライセンス台帳（LICENSE_MATRIX）

対象: `source_registry`（本書更新時点で **101ソース**。うち redistributable=1 が81件、
redistributable=0 が20件）。

**更新 2026-08-29（GBIF完走反映）**: GBIF収集は第3ラウンドで完走し、`source_registry` に
`gbif_kanagawa_occurrences`（658,360行・`redistributable=1`）として**登録済み**になった。
これにより「台帳にはあるがsource_registry未登録」というギャップは解消し、DwC-A で
GBIF由来行がソース単位で除外されることは無くなった（除外は**レコード単位ライセンスのみ**）。

なお `source_registry` には第2ラウンド時点の旧登録 `gbif_kanagawa`（586,300行）も残っている。
削除すると監査ができなくなるため**削除せず**、`notes` 冒頭に `【SUPERSEDED 2026-08-29】` を付して
無効であることを明示した。**ソース数・行数を集計する際はこの1件を除外すること**
（redistributable=1 の record_count 合計は、除外して 2,422,370 行 / 含めると 3,008,670 行）。
`scripts/x01_dwca.py` の GBIF_ALIAS フォールバックは、旧名だけが
登録されている環境でも動作するよう引き続き維持している。

**本タスクで追加したレコード単位ライセンス列**: `organism_records` に
`record_license`（元表記そのまま）・`license_class`（open/noncommercial/unknown/restricted）・
`commercial_ok`（0/1）の3列を追加し、iNaturalist・GBIFの実際の値をマッピングして
埋めた（推測によるマッピングはしていない。実測値は §4.5 参照）。
`scripts/x01_dwca.py`は既定でlicense_classが`noncommercial`/`unknown`のoccurrenceを
DwC-Aから除外するようになった（`--include-noncommercial`で無効化可能）。

## 分類基準

| 区分 | 意味 |
|---|---|
| 再配布可（オープン） | CC BY / CC0 / 政府標準利用規約 / 国土数値情報利用約款（商用可・出典明示で再配布可）など、追加条件なく再配布・商用利用可能と判断できるもの |
| 条件付き | 非商用限定、ODbL等の継承(Share-Alike)条件、出典明示必須＋二次利用は要問合せ、利用規約が「要確認」で開放性が確認できないもの、レコード単位でライセンスが混在するもの（inaturalist/GBIF）を含む |
| 再配布不可 | `source_registry.redistributable=0`。無断複製禁止・要問合せ・要確認のまま未解決、またはアカウント登録/フォーム同意が必要で取得自体を見送ったもの |

**注意**: DwC-A出力におけるソース単位の除外基準は `source_registry.redistributable` フラグの0/1のみである（COLLECTOR_CONTRACTの指示通り）。したがって下表で「条件付き」に分類されていても`redistributable=1`のソースはDwC-Aに**含まれる**（レコード単位ライセンスによる別の除外は §4.5 参照）。「条件付き」は主に**商用提案時に別途確認が必要な残存リスク**を示す目的の分類であり、`redistributable`フラグの代替ではない。

## 1. 再配布可（オープン）
| source_id | 名称 | 提供元 | 行数 | redistributable | ライセンス要旨 | 判定理由 | 根拠URL | 再配布してよいか |
|---|---|---|---|---|---|---|---|---|
| ckan_pdf_choju_higai | 神奈川県 野生鳥獣による農作物被害状況（PDF、H30-R4） | 神奈川県 環境農政局 緑政部 自然環境保全課 | 20 | 1 | クリエイティブ・コモンズ-表示(CC-BY) | クリエイティブ・コモンズ-表示(CC-BY)。野生鳥獣農作物被害状況PDF20文書。アライグマ集計区分の定義変更(R3→R4)等の時系列比較を妨げる注記あり | https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1 | 含める |
| ckan_pdf_choju_kyugo | 神奈川県 傷病鳥獣救護実績（PDF、H22-R4） | 神奈川県 自然環境保全センター | 39 | 1 | クリエイティブ・コモンズ-表示(CC-BY) | クリエイティブ・コモンズ-表示(CC-BY)。傷病鳥獣救護実績PDF39文書。鳥インフルエンザ対策による受入休止年度(H28-29)の注記あり | https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd | 含める |
| ckan_pdf_ghg_kanagawa | 神奈川県 温室効果ガス排出量・地球温暖化対策計画進捗（PDF由来） | 神奈川県 環境農政局 | 8 | 1 | クリエイティブ・コモンズ-表示(CC-BY) | クリエイティブ・コモンズ-表示(CC-BY)。神奈川県温室効果ガス排出量関連PDF8文書をcells.sqliteに構造化。P4注記でblocks_timeseries多数(排出係数の年度改定・集計方法変更・基準年度変遷) | https://catalog.opendata.pref.kanagawa.jp/dataset/38697849-5f80-4ec4-a02e-d84eb9 | 含める |
| ckan_pdf_shinrin_toukei | 統計資料集「神奈川の森林と林業」（PDF、ブロック済み） | 神奈川県 環境農政局 森林再生課 | 0 | 1 | クリエイティブ・コモンズ-表示(CC-BY) | クリエイティブ・コモンズ-表示(CC-BY)。統計資料集「神奈川の森林と林業」。スキャン画像PDFでテキストレイヤーが無くOCR環境未導入のため構造化データの抽出は断念(record_count=0、documentsのみ3件登録) | https://catalog.opendata.pref.kanagawa.jp/dataset/950a73db-1651-4bd3-8622-a35354 | 含めない |
| env_kousui_annual_kanagawa | 環境省 公共用水域水質測定結果 年間値（神奈川県） | 環境省 | 98328 | 1 | 環境省 水環境総合情報サイト（政府標準利用規約準拠 / 出典明示で利用可） https://water-pub.env.go.jp/water-pub/mizu-site/env.asp | 政府標準利用規約準拠・出典明示で利用可（環境省水環境総合情報サイト明記） | https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp | 含める |
| env_kousui_sample_kanagawa | 環境省 公共用水域水質測定結果 検体値（神奈川県） | 環境省 | 214725 | 1 | 環境省 水環境総合情報サイト（政府標準利用規約準拠 / 出典明示で利用可） https://water-pub.env.go.jp/water-pub/mizu-site/env.asp | 同上 | https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/ | 含める |
| env_kousui_stations_kanagawa | 環境省 公共用水域 水質測定点マスタ（神奈川県） | 環境省 | 324 | 1 | 環境省 水環境総合情報サイト（政府標準利用規約準拠 / 出典明示で利用可） https://water-pub.env.go.jp/water-pub/mizu-site/env.asp | 同上 | https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/ | 含める |
| estat_agri_census_kanagawa | 農林業センサス 市区町村別統計書(神奈川県) 農業経営体数・経営耕地面積・耕作放棄地面積 | 農林水産省(e-Stat経由) | 6422 | 1 | 政府標準利用規約2.0 (e-Stat) | 政府標準利用規約2.0（e-Stat）。秘匿値(X)はnullのまま保持 | https://www.e-stat.go.jp/stat-search/files?page=1&layout=dataset&query=%E8%80%95 | 含める |
| estat_census_population_kanagawa | 令和7年国勢調査 速報集計 人口速報集計（男女別人口・世帯数, 2020年比較付き）神奈川県 市区町村別 | 総務省統計局(e-Stat経由) | 806 | 1 | 政府標準利用規約2.0 (e-Stat) | 同上 | https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040454825&fileKi | 含める |
| gbif_species_match | GBIF Backbone Taxonomy 学名照合（species/match API） | Global Biodiversity Information Facility (GBIF) | 2677 | 1 | GBIF Backbone Taxonomy は CC BY 4.0（https://doi.org/10.15468/39omei） | GBIF Backbone Taxonomy CC BY 4.0 | https://api.gbif.org/v1/species/match | 含める |
| geospatial_jp_agri_point_2021_sagami | 農地筆ポリゴン2021 重心点データ（相模川流域市町村, geospatial.jp） | 農林水産省（配信: 一般社団法人社会基盤情報流通推進協議会 aigid, G空間情報センター） | 140734 | 1 | CC-BY 4.0 | CC-BY 4.0。相模川流域18市町村の農地筆重心点140734行 | https://www.geospatial.jp/ckan/dataset/agri-point-2021-14 | 含める |
| geospatial_jp_agri_poly_2021_sagami | 農地筆ポリゴン2021 ポリゴン本体（相模川流域市町村, geospatial.jp, 生ファイルのみ） | 農林水産省（配信: aigid, G空間情報センター） | 0 | 1 | CC-BY 4.0 | CC-BY 4.0。属性抽出未実施(record_count=0)、生SHPのみdata/raw保存 | https://www.geospatial.jp/ckan/dataset/agri-poly-2021-14 | 含めない |
| geospatial_jp_plateau_kanagawa | G空間情報センター PLATEAU 神奈川県内市町村 3D都市モデル目録 | 国土交通省 Project PLATEAU | 14 | 1 | PLATEAU Site Policy「3. 著作権について」に拠る（実質CC-BY 4.0相当） | PLATEAU Site Policy（実質CC-BY4.0相当）。目録14件のみ、3D実体データは未取得 | https://www.geospatial.jp/ckan/dataset?q=plateau | 含める |
| geospatial_jp_pointcloud_kanagawa | G空間情報センター 神奈川県 航空レーザ測量3次元点群データ目録 | 神奈川県 環境農政局緑政部森林再生課 | 5 | 1 | cc-by（データ提供元クレジット表記必須の付帯条件あり） | cc-by（提供元クレジット表記必須の付帯条件あり）。目録5件のみ、点群実体は未取得 | https://www.geospatial.jp/ckan/dataset/kanagawa-2022-pointcloud | 含める |
| gsj_geology_points | 20万分の1日本シームレス地質図V2 地点別地質判定（相模川流域グリッド） | 産業技術総合研究所 地質調査総合センター(GSJ) | 156 | 1 | 政府標準利用規約（第2.0版）準拠。出典明示で改変含む自由利用・商用利用可（利用申請不要）。CC BY 4.0（表示4.0国際）と互換性があり、CC BYに従うことでも利用可能（https://www.gsj.jp/license/lice | 政府標準利用規約2.0準拠。出典明示で改変含む自由利用・商用利用可（利用申請不要、CC BY 4.0とも互換） | https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.json?point=<lat>,<lon> | 含める |
| gsj_seamless_legend | 20万分の1日本シームレス地質図V2 凡例（全凡例） | 産業技術総合研究所 地質調査総合センター(GSJ) | 2416 | 1 | 政府標準利用規約（第2.0版）準拠。出典明示で改変含む自由利用・商用利用可（利用申請不要）。CC BY 4.0（表示4.0国際）と互換性があり、CC BYに従うことでも利用可能（https://www.gsj.jp/license/lice | 同上 | https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.csv | 含める |
| hiratsuka_taiki | 平塚市の大気環境状況 確定値1時間値 | 平塚市（環境保全課） | 0 | 1 | 利用条件の明示なし（自治体公開データ・出典明示前提） | ライセンス自体は「出典明示前提」でオープン相当だが、そらまめ君/相模原市と重複のため本タスクでは未取得(record_count=0) | https://hiratsukataiki.sakura.ne.jp/ | 含めない |
| jma_daily_yokohama | 気象庁 過去の気象データ 日別値（横浜 47670） | 気象庁 | 19420 | 1 | 気象庁ホームページ利用規約（政府標準利用規約 2.0 準拠 / CC BY 4.0 互換） https://www.jma.go.jp/jma/kishou/info/coment.html | 気象庁ホームページ利用規約（政府標準利用規約2.0準拠/CC BY 4.0互換） | https://www.data.jma.go.jp/stats/etrn/view/daily_s1.php?prec_no=46&block_no=4767 | 含める |
| jma_monthly_kanagawa | 気象庁 過去の気象データ 月別値（神奈川県 主要地点） | 気象庁 | 13821 | 1 | 気象庁ホームページ利用規約（政府標準利用規約 2.0 準拠 / CC BY 4.0 互換） https://www.jma.go.jp/jma/kishou/info/coment.html | 同上 | https://www.data.jma.go.jp/stats/etrn/index.php | 含める |
| jma_stations_kanagawa | 気象庁 神奈川県 観測地点一覧（アメダス+官署） | 気象庁 | 12 | 1 | 気象庁ホームページ利用規約（政府標準利用規約 2.0 準拠 / CC BY 4.0 互換） https://www.jma.go.jp/jma/kishou/info/coment.html | 同上 | https://www.jma.go.jp/bosai/amedas/const/amedastable.json | 含める |
| mlit_river_hydro | 国土交通省 水文水質データベース | 国土交通省 | 0 | 1 | 公共データ利用規約（第1.0版） | 公共データ利用規約（第1.0版）。ただしrobots的注意書きにより自動収集を見送り、record_count=0 | https://www1.river.go.jp/ | 含めない |
| moe_ias_list | 生態系被害防止外来種リスト（我が国の生態系等に被害を及ぼすおそれのある外来種リスト） | 環境省 自然環境局 | 429 | 1 | 公共データ利用規約（第1.0版）PDL1.0（環境省ホームページコンテンツの利用について）: https://www.env.go.jp/mail.html | 公共データ利用規約(第1.0版)PDL1.0。429行 | https://www.env.go.jp/nature/intro/2outline/iaslist.html | 含める |
| moe_redlist | 環境省レッドリスト（分類群ごとの最新版） | 環境省／生物多様性センター いきものログ | 6105 | 1 | 第5次RL(CSV)はCC BY 4.0（いきものログ記載）。環境省サイトは公共データ利用規約(第1.0版)PDL1.0。 | 第5次RL(CSV)はCC BY 4.0明記。環境省サイト全体はPDL1.0。6105行 | https://www.env.go.jp/nature/kisho/hozen/redlist/ | 含める |
| nlni_l03b_landuse_2006 | 国土数値情報 土地利用細分メッシュ（神奈川県流域内, 2006年） | 国土交通省 国土数値情報ダウンロードサイト | 297085 | 1 | 国土数値情報利用約款 / ダウンロードページ記載の使用許諾条件「商用可」 https://nlftp.mlit.go.jp/ksj/other/agreement.html | ダウンロードページ記載の使用許諾条件「商用可」。297085行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html | 含める |
| nlni_l03b_landuse_2016 | 国土数値情報 土地利用細分メッシュ（神奈川県流域内, 2016年） | 国土交通省 国土数値情報ダウンロードサイト | 297085 | 1 | 国土数値情報利用約款 / 平成28年度分は「適用する利用規約に基づく（オープンデータ）」 https://nlftp.mlit.go.jp/ksj/other/agreement.html | 「適用する利用規約に基づく（オープンデータ）」。297085行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html | 含める |
| nlni_l03b_landuse_by_watershed | 土地利用細分メッシュ 流域別集計（神奈川県 2006/2016） | 国土交通省 国土数値情報ダウンロードサイト（本収集で集計） | 4858 | 1 | 国土数値情報利用約款 / 平成28年度分は「適用する利用規約に基づく（オープンデータ）」 https://nlftp.mlit.go.jp/ksj/other/agreement.html | 上記2件からの派生集計（本収集内で計算）。4858行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html | 含める |
| nlni_w12_watersheds | 国土数値情報 流域界・非集水域（神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 377 | 1 | 国土数値情報利用約款（出典明示で商用利用・再配布可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | 国土数値情報利用約款：出典明示で商用利用・再配布可と明記。377行 | https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html | 含める |
| nlni_w12_watersheds_by_system | 国土数値情報 流域界 旧水系域コード別集計（神奈川県） | 国土交通省 国土数値情報ダウンロードサイト（本収集で集計） | 9 | 1 | 国土数値情報利用約款（出典明示で商用利用・再配布可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | 同上からの派生集計。9行 | https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html | 含める |
| rinya_forest_stats_prefecture | 都道府県別森林率・人工林率 | 林野庁 | 48 | 1 | 公共データ利用規約(第1.0版)PDL1.0 (農林水産省ウェブサイトのコンテンツ利用規約、出典: https://www.maff.go.jp/j/use/link.html ; 出典記載必須・改変時の明記必須) | 公共データ利用規約(第1.0版)PDL1.0（出典記載必須）。48行 | https://www.rinya.maff.go.jp/j/keikaku/genkyou/r4/attach/xls/1-1.xlsx | 含める |
| rinya_lidar_kanagawa_status | 森林情報オープンデータ化(航空レーザ計測)神奈川県公開状況 | 林野庁 | 1 | 1 | 公共データ利用規約(第1.0版)PDL1.0 (農林水産省ウェブサイトのコンテンツ利用規約、出典: https://www.maff.go.jp/j/use/link.html ; G空間情報センター側の実データは別ライセンス条件の可能性あ | 同上。目録1行のみ、実体(点群等)は未取得 | https://www.rinya.maff.go.jp/j/keikaku/smartforest/smart_forestry.html | 含める |
| sagamihara_digital_archive | さがみはらデジタルアーカイブ 生物カテゴリ目録（相模原市立博物館 自然史標本） | 相模原市（相模原市立博物館） | 15737 | 1 | 目録情報はCC0 1.0 全世界パブリック・ドメイン提供(https://digital-sagamihara.jp/terms 2-1)。個別資料の画像2次利用は所蔵機関(市立博物館)へ要問合せのため画像は未取得。 | 目録情報はCC0 1.0明記。個別資料の画像は別途問合せ必要のため未取得（目録15737行のみ対象） | https://digital-sagamihara.jp/digital-archive/?category=5 | 含める |
| sagamihara_taiki_hourly | 相模原市 大気汚染常時監視測定結果 1時間値（流域デモ抽出） | 相模原市 | 175344 | 1 | クリエイティブ・コモンズ 表示 (CC BY) https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki | CC BY（相模原市オープンデータ）。175344行。単位は公開元に記載なくunit=NULLのまま | https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki | 含める |
| sagamihara_taiki_stations | 相模原市 大気汚染常時監視 測定局一覧 | 相模原市 | 7 | 1 | クリエイティブ・コモンズ 表示 (CC BY) https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki | 同上。7行 | https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki | 含める |
| soramame_hourly_kanagawa | 環境省 そらまめ君 1時間値（神奈川県 流域デモ4局） | 環境省 | 168793 | 1 | 環境省 そらまめ君 利用規約（出典明示による利用可 / 速報値・確定値は国立環境研究所 環境数値データベース）https://soramame.env.go.jp/policy | 環境省そらまめ君利用規約（出典明示による利用可）。168793行。速報値であり確定値と異なる場合がある旨の注記あり | https://soramame.env.go.jp/download | 含める |
| soramame_stations_kanagawa | 環境省 そらまめ君 測定局マスタ（神奈川県） | 環境省 | 92 | 1 | 環境省 そらまめ君 利用規約（出典明示による利用可 / 速報値・確定値は国立環境研究所 環境数値データベース）https://soramame.env.go.jp/policy | 同上。92行 | https://soramame.env.go.jp/ | 含める |

## 2. 条件付き
| source_id | 名称 | 提供元 | 行数 | redistributable | ライセンス要旨 | 判定理由 | 根拠URL | 再配布してよいか |
|---|---|---|---|---|---|---|---|---|
| biodic_6th_kanagawa_report | 第6回自然環境保全基礎調査 神奈川県報告書 | 環境省生物多様性センター | 97 | 1 | 環境省ウェブサイト利用規約(要確認) | 環境省サイト利用規約(要確認)。record_countはPDFページ数(97)で表データ抽出は未実施(cells.sqliteにdocuments登録のみ) | https://www.biodic.go.jp/reports2/6th/todouhuken/kanagawa/h16_kanagawa.pdf | 含める |
| biodic_vegcode_legend | 植生調査共通凡例コード表(第2版, 2001-10-31~) | 環境省生物多様性センター | 1247 | 1 | 生物多様性センターウェブサイト利用規約 | 「生物多様性センターウェブサイト利用規約」とのみ記載でCC表記なし・要確認。全国共通コード表1247行 | https://www.biodic.go.jp/dload/mesh_vg.html | 含める |
| biodic_vegmesh_4th_kanagawa | 植生調査 3次メッシュデータ 第4回自然環境保全基礎調査(1988-1992)（神奈川県相当メッシュ抽出） | 環境省生物多様性センター | 5482 | 1 | 生物多様性センターウェブサイト利用規約 | 同上（要確認）。植生3次メッシュ5482行、バウンディングボックス抽出で行政界外を含み得る | https://www.biodic.go.jp/dload/mesh_vg.html | 含める |
| biodic_vegmesh_5th_kanagawa | 植生調査 3次メッシュデータ 第5回自然環境保全基礎調査(1992-1996)（神奈川県相当メッシュ抽出） | 環境省生物多様性センター | 5489 | 1 | 生物多様性センターウェブサイト利用規約 | 同上（要確認）。5489行 | https://www.biodic.go.jp/dload/mesh_vg.html | 含める |
| ckan_env_bulk | CKAN 環境系リソース一括CSV化（神奈川県/相模原市） | 神奈川県・相模原市 | 977 | 1 | CC BY 4.0 / CC BY-NC 4.0（データセット個別） | ★データセットごとにCC BY 4.0 / CC BY-NC 4.0が混在（977リソースを一括処理、個票ライセンスの行単位検証は未実施）。CC BY-NC分の混入リスクあり | https://catalog.opendata.pref.kanagawa.jp | 含める |
| ckan_kanagawa_pref | 神奈川県オープンデータカタログ | 神奈川県 | 811 | 1 | 各データセット個別（多くは CC BY 4.0 / 政府標準利用規約） | 「多くはCC BY 4.0/政府標準利用規約」との記載で全件確認ではない（目録811件、個別データセットのライセンス未検証） | https://catalog.opendata.pref.kanagawa.jp | 含める |
| ckan_sagamihara | 相模原市オープンデータカタログ | 相模原市 | 114 | 1 | 各データセット個別（多くは CC BY 4.0 / 政府標準利用規約） | 同上（114件、個別データセットのライセンス未検証） | https://opendata.city.sagamihara.kanagawa.jp | 含める |
| dams_kanagawa | 神奈川県内主要ダム諸元(宮ヶ瀬・城山・相模・三保) | 国土交通省 関東地方整備局 / 神奈川県企業局 | 4 | 1 | 政府標準利用規約(第2.0版)相当（要確認） | 「政府標準利用規約(第2.0版)相当（要確認）」。城山ダムはWayback Machine保存版から取得、緯度経度はWikipedia Geohack由来 | https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/ ; https://www.ktr.mlit.go.jp/sa | 含める |
| gbif_kanagawa_occurrences | GBIF Occurrence — 神奈川県 (GADM JPN.19_1) | GBIF | 658360 | 1 | 各データセット個別 (CC0/CC BY/CC BY-NC が混在。license列に保持) | ★GBIF occurrence本体。★データセット単位でCC0/CC BY/CC BY-NCが混在(license列に保持)。**2026-08-29の第3ラウンドで収集完走・source_registry登録済み**（658,360行、重複0）。レコード単位ライセンスの実測(確定値): CC BY 4.0 591,612 / CC BY-NC 4.0 62,460 / CC0 1.0 4,288。`organism_records.record_license/license_class/commercial_ok`に反映済みで、`scripts/x01_dwca.py`は既定でCC BY-NC分(62,460件)をDwC-Aから除外する（§4.5）。**表示なし(unknown)・SA/ND(restricted)は0件**。GBIF側count=659,399に対し1,039件が未取得のまま残る（区画取得不能93+日付欠損958。内訳は`data/logs/gbif_partition_report.csv`）。以前あった命名不整合（source_registry側'gbif_kanagawa' vs 実データ側'gbif_kanagawa_occurrences'）は収集側コードの修正が第3ラウンドに反映されたため解消。旧登録'gbif_kanagawa'は監査のため【SUPERSEDED】注記付きで残置（本書冒頭参照） | https://www.gbif.org/occurrence/search?gadm_gid=JPN.19_1 | 含める（ただし`license_class`が`noncommercial`の62,460件はDwC-Aから既定で除外。マスタDBには全件保持し列で区別） |
| geospatial_jp_kanagawa_catalog | G空間情報センター 神奈川県・相模川流域関連データセット目録 | 国土交通省 G空間情報センター（運営: 一般社団法人 社会基盤情報流通推進協議会） | 429 | 1 | データセットごとに異なる（cc-by, ol=独自利用規約, ogl=政府標準利用規約, notspecified 等混在。個票の license 列参照） | 「データセットごとに異なる（cc-by,ol=独自利用規約,ogl=政府標準利用規約,notspecified等混在。個票のlicense列参照）」目録429件で個別未検証 | https://www.geospatial.jp/ckan/dataset?q=神奈川 | 含める |
| inaturalist_kanagawa | iNaturalist 観察記録 — 神奈川県 (place 10918) | iNaturalist | 165332 | 1 | 観察ごとに個別 (CC0/CC BY/CC BY-NC/全権利留保。license_code列に保持) | ★観察ごとに個別ライセンス(license_code列)。実測: cc-by-nc 113,284 / cc-by 27,975 / ライセンスなし(None) 21,058 / cc0 1,511 / cc-by-sa 677 / cc-by-nc-sa 573 / 空文字 172 / cc-by-nc-nd 80 / cc-by-nd 2（全165,332件）。非商用・無許諾ライセンスが合計約82%を占める。**本タスクで解消**: `organism_records`に`record_license`/`license_class`/`commercial_ok`列を追加し、上記の値を反映した（license_class内訳: noncommercial 113,937 / open 29,486 / unknown 21,230 / restricted 679）。`scripts/x01_dwca.py`は既定でnoncommercial(cc-by-nc系)・unknown(表示なし)をDwC-Aから除外する（**本ソース分**でDwC-Aに含まれるのは open 29,486 + restricted 679 = 30,165件。GBIF分595,900件を加えたDwC-A全体は626,065件）。マスタDB `data/db/ryuiki.sqlite` にはlicense_classを問わず全件保持するが、列で区別できる（§4.5） | https://www.inaturalist.org/observations?place_id=10918 | 含める |
| kanagawa_rdb2006_animals | 神奈川県レッドデータ生物調査報告書2006（レッドリスト集計結果・一覧） | 神奈川県立生命の星・地球博物館 | 0 | 1 | 神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: https://www.pref.kanagawa.jp/master/sitepolicy.html | 神奈川県サイトポリシー：出典記載で利用可だが書籍転載等の二次的利用は所管所属へ事前問合せ必要。record_count=0（PDFのみ、表抽出は別担当範囲） | https://nh.kanagawa-museum.jp/assets/icp/contents/1657590295853/simple/RedData20 | 含めない |
| kanagawa_rdb2022_plants | 神奈川県レッドデータブック2022 植物編 | 神奈川県環境農政局緑政部自然環境保全課 | 0 | 1 | 神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: https://www.pref.kanagawa.jp/master/sitepolicy.html | 同上。record_count=0 | https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1197000.html | 含めない |
| kanagawa_redlist | 神奈川県レッドリスト（2020植物編・2026昆虫類クモ類） | 神奈川県環境農政局緑政部自然環境保全課 | 1851 | 1 | 神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: https://www.pref.kanagawa.jp/master/sitepolicy.html | 同上（出典記載可・二次利用要問合せ）。1851行、taxaテーブルの神奈川RL列の元データ | https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1061385.html | 含める |
| kanagawa_redlist_categories | 神奈川県レッドリスト カテゴリー区分表 | 神奈川県環境農政局緑政部自然環境保全課 | 22 | 1 | 神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: https://www.pref.kanagawa.jp/master/sitepolicy.html | 同上。22行 | https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1196500.html | 含める |
| kanagawa_river_citizen_survey | 神奈川県 河川のモニタリング調査(相模川・酒匂川、動植物等調査+県民参加型調査) | 神奈川県 環境農政局 水源環境保全課(環境科学センター実施) | 20 | 1 | 政府標準利用規約(第2.0版)相当（要確認） | 「政府標準利用規約(第2.0版)相当（要確認）」。参加人数集計20行のみ、地点別データなし | https://www.pref.kanagawa.jp/docs/b4f/suigen/top.html | 含める |
| kanagawa_shizenshi_bibliography | 神奈川自然誌資料 バックナンバー書誌目録（論文タイトル・著者・ページ・PDFリンク） | 神奈川県立生命の星・地球博物館 | 831 | 1 | サイト著作権表記: 『当サイトに掲載されているコンテンツ（文章、イラスト、写真、動画など）は、著作権の対象となっています。「引用」等の著作権法上認められている範囲において自由にご利用になれます。コンテンツを利用する際には、出典を記載してくだ | 博物館サイト著作権表記：引用の範囲内利用可・出典記載必須。831行は書誌情報(タイトル・著者・ページ)のみでPDF本文は含まず | https://nh.kanagawa-museum.jp/publications/nhr/index.html | 含める |
| kasen_kokusei_sagami | 河川水辺の国勢調査（相模川） | 国土交通省 関東地方整備局 京浜河川事務所 | 6 | 1 | 政府標準利用規約(第2.0版)相当・国交省地方整備局サイトの二次利用ルールに準拠（要確認） | 「政府標準利用規約(第2.0版)相当・国交省地方整備局サイトの二次利用ルールに準拠（要確認）」。6件はdocuments登録のみで表抽出なし | https://www.ktr.mlit.go.jp/keihin/keihin00294.html | 含める |
| miyagase_storage_status | 宮ケ瀬ダム貯水状況のお知らせ | 国土交通省 関東地方整備局 相模川水系広域ダム管理事務所 | 0 | 1 | 政府標準利用規約(第2.0版)相当（要確認） | 同上（要確認）。record_count=0（スナップショットのみ、時系列化見送り） | https://www.ktr.mlit.go.jp/sagami/sagami01113.html | 含めない |
| moe_meisui_kanagawa | 名水百選（神奈川県分: 秦野盆地湧水群・洒水の滝/滝沢川） | 環境省 | 2 | 1 | 環境省ウェブサイト著作権・リンクについてに準拠(要確認) | 「環境省ウェブサイト著作権・リンクについてに準拠（要確認）」。2行、緯度経度は非公開 | https://water-pub.env.go.jp/water-pub/mizu-site/meisui/ | 含める |
| moe_satoyama_kanagawa | 重要里地里山 選定地一覧（神奈川県） | 環境省 | 28 | 1 | 環境省ウェブサイト著作権・リンクについてに準拠(要確認) | 「環境省ウェブサイト著作権・リンクについてに準拠（要確認）」。28行 | https://www.env.go.jp/nature/satoyama/14_kanagawa/kanagawa.html | 含める |
| moni1000_coast_shorebird | モニタリングサイト1000 沿岸域(シギ・チドリ類)調査（神奈川県サイトのみ抽出） | 環境省生物多様性センター | 620 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★生物多様性センターウェブサイト利用規約（要事前アンケート回答）。利用アンケートフォーム経由でzip取得(SIG02)。620行 | https://www.biodic.go.jp/moni1000/coast.html | 含める |
| moni1000_forest_bird | モニタリングサイト1000 森林・草原調査 陸生鳥類調査（神奈川県サイトのみ抽出） | 環境省生物多様性センター | 9433 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上（要事前アンケート回答、SIN04）。9433行 | https://www.biodic.go.jp/moni1000/forest.html | 含める |
| moni1000_lake_aquaticplants | モニタリングサイト1000 陸水域(湖沼)水生植物調査(KOS07) | 環境省生物多様性センター | 0 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上。フォーム送信を試行しサーバエラーで取得失敗（record_count=0） | https://www.biodic.go.jp/moni1000/wetlands.html | 含めない |
| moni1000_lake_benthos | モニタリングサイト1000 陸水域(湖沼)底生動物調査(KOS04) | 環境省生物多様性センター | 0 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上。全国7湖沼に神奈川県内サイトなしのため取得なし（record_count=0） | https://www.biodic.go.jp/moni1000/wetlands.html | 含めない |
| moni1000_lake_fish | モニタリングサイト1000 陸水域(湖沼)淡水魚調査(KOS06) | 環境省生物多様性センター | 0 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上。フォーム送信を試行しサーバエラーで取得失敗（record_count=0） | https://www.biodic.go.jp/moni1000/wetlands.html | 含めない |
| moni1000_satochi_bird | モニタリングサイト1000 里地鳥類調査（神奈川県サイトのみ抽出） | 環境省生物多様性センター | 18396 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上（要事前アンケート回答、SAT02）。18396行 | https://www.biodic.go.jp/moni1000/village.html | 含める |
| moni1000_satochi_butterfly | モニタリングサイト1000 里地チョウ類調査（神奈川県サイトのみ抽出） | 環境省生物多様性センター | 14529 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上（SAT07）。14529行 | https://www.biodic.go.jp/moni1000/village.html | 含める |
| moni1000_satochi_mammal | モニタリングサイト1000 里地中・大型哺乳類調査(自動撮影)（神奈川県サイトのみ抽出） | 環境省生物多様性センター | 2031 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上（SAT03）。2031行 | https://www.biodic.go.jp/moni1000/village.html | 含める |
| moni1000_sites | モニタリングサイト1000 サイト一覧（全国・神奈川抽出） | 環境省生物多様性センター | 1055 | 1 | 政府標準利用規約(準拠を想定、要確認) | サイト一覧のみはHTML(都道府県別ページ)から取得しておりアンケートフォームは経由していない。ライセンスは「政府標準利用規約(準拠を想定、要確認)」。1055行（神奈川30件）。sitesテーブルの一部としてアプリDBに組み込み済み | https://www.biodic.go.jp/moni1000/site_list.html | 含める |
| moni1000_waterfowl | モニタリングサイト1000 ガンカモ類調査(GAN01) | 環境省生物多様性センター | 0 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★アンケートフォーム経由取得を試行。神奈川県内地点なし（record_count=0） | https://www.biodic.go.jp/moni1000/wetlands.html | 含めない |
| moni1000_wetland_vegetation | モニタリングサイト1000 陸水域(湿原)湿原植生調査(SIT01) | 環境省生物多様性センター | 0 | 1 | 生物多様性センターウェブサイト利用規約(要事前アンケート回答) | ★同上。神奈川県内地点なし（record_count=0） | https://www.biodic.go.jp/moni1000/wetlands.html | 含めない |
| nlni_a10_natparks | 国土数値情報 自然公園地域（神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 21 | 1 | 国土数値情報利用約款 + ダウンロードページ記載の使用許諾条件「非商用」（出典明示で利用可・商用利用不可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | ★国土数値情報利用約款＋ダウンロードページ記載「非商用」の使用許諾条件。redistributable=1だが商用利用不可。21行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html | 含める |
| nlni_a15_wildlife | 国土数値情報 鳥獣保護区（神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 173 | 1 | 国土数値情報利用約款 + ダウンロードページ記載の使用許諾条件「非商用」（出典明示で利用可・商用利用不可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | ★同上「非商用」。173行 | https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html | 含める |
| nlni_a45_forest | 国土数値情報 森林地域（国有林小班・神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 1673 | 1 | オープンデータ（CC BY 4.0）／国土数値情報利用約款。ダウンロードページ原文「適用する利用規約に基づく（オープンデータ）」 https://nlftp.mlit.go.jp/ksj/other/agreement.html | 「オープンデータ（CC BY 4.0）」表記だがダウンロードページ原文注記「本製品を複製する場合には、国土地理院の長の承認を得なければなりません」あり。CC BY表記と矛盾しうるため要確認扱いとした。1673行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html | 含める |
| nlni_w05_river_nodes | 国土数値情報 河川（河川端点・神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 2439 | 1 | 国土数値情報利用約款 + ダウンロードページ記載の使用許諾条件「非商用」（出典明示で利用可・商用利用不可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | ★ダウンロードページ記載「非商用」。2439行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html | 含める |
| nlni_w05_rivers | 国土数値情報 河川（流路・神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 2305 | 1 | 国土数値情報利用約款 + ダウンロードページ記載の使用許諾条件「非商用」（出典明示で利用可・商用利用不可） https://nlftp.mlit.go.jp/ksj/other/agreement.html | ★同上「非商用」。2305行 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html | 含める |
| osm_kanagawa_farmland | OSM 神奈川県 農地（landuse=farmland, meadow） | OpenStreetMap contributors | 15396 | 1 | ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: https://www.openstreetmap.org/copyright） | ★ODbL 1.0（Share-Alike・帰属表示の継承条件あり）。15396行 | https://overpass-api.de/api/interpreter | 含める |
| osm_kanagawa_forest | OSM 神奈川県 森林（landuse=forest, natural=wood） | OpenStreetMap contributors | 12868 | 1 | ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: https://www.openstreetmap.org/copyright） | ★同上。12868行 | https://overpass-api.de/api/interpreter | 含める |
| osm_kanagawa_protected_area | OSM 神奈川県 保護区（nature_reserve, protected_area） | OpenStreetMap contributors | 17 | 1 | ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: https://www.openstreetmap.org/copyright） | ★同上。17行 | https://overpass-api.de/api/interpreter | 含める |
| osm_kanagawa_water | OSM 神奈川県 水系（水域・河川） | OpenStreetMap contributors | 10695 | 1 | ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: https://www.openstreetmap.org/copyright） | ★同上。10695行 | https://overpass-api.de/api/interpreter | 含める |
| sagami_livecams | 相模川ライブカメラ地点一覧 | 国土交通省 関東地方整備局 京浜河川事務所 | 16 | 1 | 政府標準利用規約(第2.0版)相当（要確認） | 「政府標準利用規約(第2.0版)相当（要確認）」。緯度経度はカメラ地図の中心座標で実測点でない可能性あり。16行 | https://www.ktr.mlit.go.jp/keihin/keihin01459.html | 含める |
| tanzawa_shika_suigen_docs | 丹沢 ニホンジカ管理実績・保護管理計画/水源環境保全再生 最終評価報告書 | 神奈川県 環境農政局 自然環境保全課 / 水源環境保全・再生かながわ県民会議 | 4 | 1 | 政府標準利用規約(第2.0版)相当（要確認） | 「政府標準利用規約(第2.0版)相当（要確認）」。4件はdocuments登録のみで表抽出なし | https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html | 含める |

## 3. 再配布不可
| source_id | 名称 | 提供元 | 行数 | redistributable | ライセンス要旨 | 判定理由 | 根拠URL | 再配布してよいか |
|---|---|---|---|---|---|---|---|---|
| ayu_upstream_migration | 寒川取水堰 天然アユ遡上調査(相模川漁業協同組合連合会お知らせ記事より) | 相模川漁業協同組合連合会 | 32 | 0 | 利用条件の明示なし(要問合せ)。相模川漁連の公開告知記事のため出典明記の上での引用は可能と判断 | redistributable=0（利用条件明示なし・要問合せ）。processed CSV/JSONLは既に生成済み(32行)——再配布不可 | http://sagamigawa-gyoren.jp/topics/2214/ | 含める |
| biodic_animal_distribution | 自然環境保全基礎調査 動植物分布調査(全種調査) 対象種一覧 | 環境省生物多様性センター | 0 | 0 | 生物多様性センターウェブサイト利用規約 | redistributable=0、record_count=0（全国種一覧のみでメッシュ分布データではないため未取得） | https://www.biodic.go.jp/category/sizen/40.html | 含めない |
| biodic_kiban_datalist | 生物多様性センター 基盤情報データリスト | 環境省生物多様性センター | 0 | 0 | 生物多様性センターウェブサイト利用規約 | redistributable=0、record_count=0（入口ページのみ、実データなし） | https://www.biodic.go.jp/category/kiban/datalist.html | 含めない |
| biodic_webgis | 自然環境調査Web-GIS | 環境省生物多様性センター | 0 | 0 | 要確認 | redistributable=0、record_count=0 | http://gis.biodic.go.jp/webgis/ | 含めない |
| buna_suitai_web | ブナ衰退WEB版(丹沢山地) | 神奈川県自然環境保全センター | 0 | 0 | 政府標準利用規約(第2.0版)相当（要確認） | redistributable=0、record_count=0（表がすべて画像でCSV化不可） | https://www.agri-kanagawa.jp/WEB_buna/jittai_02rireki.html | 含めない |
| eadas_kanagawa | 環境アセスメントデータベース EADAS（神奈川県事例） | 環境省大臣官房環境影響評価課 | 0 | 0 | EADAS利用規約(要確認 /Service/AboutTermofuse) | redistributable=0、record_count=0 | https://eadas.env.go.jp/ | 含めない |
| etanzawa_siryousitu | 丹沢資料室(一次資料アーカイブ) | 神奈川県 環境農政局 森林再生課 / 神奈川県自然環境保全センター | 0 | 0 | 政府標準利用規約(第2.0版)相当（要確認） | redistributable=0、record_count=0（リンク確認のみ） | https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html | 含めない |
| geospatial_jp_kokudo_landclass_kanagawa | 国土調査 20万分の1土地分類基本調査等 神奈川県（生ファイルのみ） | 国土交通省 国土政策局 国土情報課 | 5 | 0 | 独自利用規約(ol) | redistributable=0。readme原文「成果をそのまま複製して有償・無償に関わらず頒布することは禁じます」。生SHPのみdata/rawに保存済み(属性抽出なし) | https://www.geospatial.jp/ckan/dataset/mlit-kokudo-2 | 含める |
| geospatial_jp_kokudo_river_sagami | 国土調査 主要水系調査（一級水系）相模川地域（生ファイルのみ） | 国土交通省 国土政策局 国土情報課 | 40 | 0 | 独自利用規約(ol) | 同上。readme原文で複製頒布禁止。生SHPのみdata/rawに保存済み | https://www.geospatial.jp/ckan/dataset/mlit-kokudo-6 | 含める |
| gsi_kiban_chizu_joho | 基盤地図情報（基本項目・数値標高モデル等）ダウンロードサービス | 国土交通省国土地理院 | 0 | 0 | 国土地理院コンテンツ利用規約（公共データ利用規約(PDL1.0)相当）https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html　※基盤地図情報は測量法上の基本測量成果であり複製・ | redistributable=0。要ユーザー登録・ログインのため未取得（人間の承認待ち、COLLECTOR_CONTRACT準拠） | https://service.gsi.go.jp/kiban/ | 含めない |
| ikilog | いきものログ（市民参加型生物観察記録DB） | 環境省 | 0 | 0 | 生物多様性センターウェブサイト利用規約 | redistributable=0、record_count=0（検索APIフロー未再現のため中断） | https://ikilog.biodic.go.jp/ | 含めない |
| kanagawa_dam_mizugame | かながわの水がめ（相模川・酒匂川水系 降水量/貯水量/ダム諸量） | 神奈川県企業庁 | 0 | 0 | 無断複製・転用不可（サイトポリシー） | redistributable=0。サイトポリシー原文「無断で複製・転用することはできません」。record_count=0（未取得） | https://kanagawa-dam.jp/ | 含めない |
| kanagawa_ikimono_chousa | かながわ生きもの調査 年度別結果 | 神奈川県 | 0 | 0 | 要確認(転載条件の明記なし) | redistributable=0、record_count=0（表形式データなし、PDFのみ） | https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1195000.html | 含めない |
| nlni_a03_metro_area | 国土数値情報 三大都市圏（全国） | 国土交通省 国土数値情報ダウンロードサイト | 0 | 0 | オープンデータ（CC BY 4.0） | redistributable=0（DB上の値。ライセンス自体はCC BY 4.0でオープンだが、測地系変換コスト等の理由で未取得のためregister時にredistributable=0とされたと推定）。record_count=0 | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A03.html | 含めない |
| nlni_p05_city_hall | 国土数値情報 市町村役場等及び公的集会施設 | 国土交通省 国土数値情報ダウンロードサイト | 0 | 0 | 要確認 | redistributable=0（DB上の値）。ライセンスは要確認、record_count=0（正しいURLに未対応、未取得） | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05.html | 含めない |
| nlni_w07_watershed_mesh | 国土数値情報 流域メッシュ（神奈川県） | 国土交通省 国土数値情報ダウンロードサイト | 0 | 0 | ダウンロードページ記載の使用許諾条件「非商用」 | redistributable=0（DB上の値）。使用許諾条件「非商用」。record_count=0（W12で代替できるため未取得） | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W07.html | 含めない |
| resas_api | RESAS-API (地域経済分析システム) | 内閣官房・内閣府 デジタル田園都市国家構想実現会議事務局 | 0 | 0 | 不明(要利用規約確認、登録前のため未確認) | redistributable=0。APIキー取得に利用登録フォームが必須なため未取得（COLLECTOR_CONTRACT準拠） | https://opendata.resas-portal.go.jp/ | 含めない |
| snet_kahaku | サイエンスミュージアムネット S-Net（自然史標本横断検索） | 国立科学博物館 | 0 | 0 | 国立科学博物館の利用規約に準拠(要確認) | redistributable=0、record_count=0（重複回避のため未取得） | https://science-net.kahaku.go.jp/ | 含めない |
| tanzawa_species_list_1997 | 丹沢のビジターセンター 生き物リスト(哺乳類/鳥類/は虫類/両生類/昆虫) | 神奈川県立 秦野ビジターセンター・西丹沢ビジターセンター(公益財団法人神奈川県公園協会) | 324 | 0 | 要確認(ビジターセンター運営元への利用許諾確認が必要) | ★redistributable=0（ビジターセンター運営元への利用許諾確認が必要、要確認ライセンス）。processed HTML由来CSVは既に生成済み(324行)——再配布不可 | https://www.kanagawa-park.or.jp/tanzawavc/ikimono1.html | 含める |
| ylist | YList 植物和名ー学名インデックス（日本産維管束植物 和名-学名インデックス） | 米倉浩司・梶田忠（琉球大学熱帯生物圏研究センター） | 0 | 0 | ライセンス表示なし（引用形式のみ指定） | redistributable=0、record_count=0。再配布可否の明示なし（引用形式の指定のみ）のため取得せず | http://ylist.info/ | 含めない |

## 4. 特に注意すべき事項（個別記載）

### 4.1 国土数値情報「非商用」条件（W05河川・A10自然公園・A15鳥獣保護区）
`nlni_w05_river_nodes`(2439行) / `nlni_w05_rivers`(2305行) / `nlni_a10_natparks`(21行) / `nlni_a15_wildlife`(173行) は
いずれも `source_registry.redistributable=1` として登録されているが、国土数値情報ダウンロードページに記載された
使用許諾条件は明示的に「非商用」である。**商用提案・商用サービスへの掲載時にはこの4ソース由来のデータ
（河川流路・河川端点・自然公園地域・鳥獣保護区ポリゴン）を商用利用可能なライセンスのデータに差し替える必要がある。**
なお同じ国土数値情報でも `nlni_w12_watersheds`（流域界）・`nlni_l03b_landuse_*`（土地利用細分メッシュ）・
`nlni_a45_forest`（森林地域、ただし4.3参照）は商用可の許諾条件になっており、データセットごとに条件が異なる点に注意。

### 4.2 モニタリングサイト1000 — 利用アンケートフォームへの同意
`moni1000_coast_shorebird` / `moni1000_forest_bird` / `moni1000_satochi_bird` / `moni1000_satochi_butterfly` /
`moni1000_satochi_mammal` / `moni1000_lake_*`(3件, 取得失敗) / `moni1000_waterfowl`(取得失敗) /
`moni1000_wetland_vegetation`(取得失敗) は、収集エージェントの記録上「利用アンケートフォーム経由でzip取得」と
明記されている。**環境省生物多様性センターの当該データダウンロードには利用目的等を申告するアンケートフォームへの
回答が必要であり、本プロジェクトの収集作業においてこのフォームが自動的に送信された経緯がある**
（`docs/COLLECTOR_CONTRACT.md` 末尾は「外部サイトのフォーム送信」を人間の承認なしに行うことを明確に禁止しており、
本件はこの契約が導入される前後の境界的な事案である可能性がある。人間側で、(a) 実際に送信されたフォームの内容
（申告した利用目的・組織名等）の確認、(b) 環境省側への事後確認の要否、を判断する必要がある）。
なお `moni1000_sites`（サイト一覧、1055行）はアンケートフォームを経由しない公開HTMLページからの取得であり、
この注意事項の対象外。

### 4.3 国土数値情報 A45森林地域 — CC BY表記とページ注記の矛盾
`nlni_a45_forest`(1673行) はライセンス欄で「オープンデータ（CC BY 4.0）」とされているが、収集時のノートには
ダウンロードページの原文注記として「本製品を複製する場合には、国土地理院の長の承認を得なければなりません。」
との記載も残されている。CC BY 4.0（複製・再配布に許諾不要）とこの注記は文面上矛盾するため、本台帳では
「条件付き（要確認）」として扱った。商用提案に用いる前に原典ページで確認すること。

### 4.4 `redistributable=0` だがファイルは既に生成されているもの
`tanzawa_species_list_1997`（324行、`data/processed/tanzawa_species_list_1997.csv`等）と
`ayu_upstream_migration`（32行、`data/processed/ayu_upstream_migration.csv`等）は、いずれも
`source_registry.redistributable=0` として登録されているにもかかわらず、収集エージェントが実際に
CSV/JSONLファイルを生成済みである（アプリDBの`sites`/`measurements`/`organism_records`のいずれにも
現時点では取り込まれていない＝孤立した処理済みファイルとして`data/processed/`に存在するのみ）。
**この2ソースは `redistributable=0` であり、第三者への再配布・引用元としての明示はできない。**

### 4.5 iNaturalist / GBIF のレコード単位ライセンス — 本タスクで解消

（旧版の本節では、per-recordライセンスが未フィルタで再配布されうる問題を「本番運用前に解消すべき
ギャップ」として記録していた。本タスクでこの問題に対応したため、対応内容と実測結果を以下に記す。）

`inaturalist_kanagawa`・`gbif_kanagawa_occurrences`（GBIF occurrence本体）は、いずれも
**個々の観察記録ごとに異なるライセンス**（CC0 / CC BY / CC BY-NC / CC BY-SA / CC BY-ND /
ライセンスなし（全著作権留保）等）を持つ。

**対応内容**:
1. `organism_records`に`record_license`（元表記そのまま）・`license_class`
   （open/noncommercial/unknown/restricted）・`commercial_ok`（0/1）の3列を追加した
   （`ALTER TABLE ... ADD COLUMN`。既存の実データ行はUPDATEで埋め、DELETE/DROPは行っていない）。
2. 実際に出現したライセンス原表記を先に集計し、`data/processed/license_code_mapping.csv`
   として出力してから、その値だけをマッピングする表（`scripts/m03_organisms.py`の`LICENSE_MAP`）を
   適用した。表示のない値（`None`・空文字）は推測で`open`に分類せず、`unknown`として扱った。
   未知の値が出現した場合は`unknown`・commercial_ok=0とし、標準出力に警告を出す実装にしている
   （本タスク実行時点では未知の値は出現していない）。
3. `scripts/x01_dwca.py`を修正し、既定で`license_class`が`noncommercial`（CC BY-NC系）または
   `unknown`（表示なし）のoccurrenceをDwC-Aから除外するようにした
   （`--include-noncommercial`オプションで無効化可能。既定はOFF）。occurrenceの`license`列には
   `record_license`をそのまま出力するようにした（従来は常に空文字だった）。
4. マスタDB `data/db/ryuiki.sqlite` は license_class に関わらず**全件保持**する
   （削除はしない）。どの行が再配布・商用利用できるかは `license_class` /
   `commercial_ok` 列で判別する。

**実測結果**（2026-08-29 GBIF完走反映後の**確定値**。organism_records 823,692件の全件集計。
原表記の内訳は `data/processed/license_code_mapping.csv`）:

| source | license_class | 件数 | 原表記の内訳 |
|---|---|---|---|
| gbif_kanagawa_occurrences | open | 591,612 + 4,288 = **595,900** | CC BY 4.0 591,612 / CC0 1.0 4,288 |
| gbif_kanagawa_occurrences | noncommercial | **62,460** | CC BY-NC 4.0 |
| inaturalist_kanagawa | noncommercial | **113,937** | cc-by-nc 113,284 / cc-by-nc-sa 573 / cc-by-nc-nd 80 |
| inaturalist_kanagawa | open | **29,486** | cc-by 27,975 / cc0 1,511 |
| inaturalist_kanagawa | unknown | **21,230** | ライセンス表示なし(None) 21,058 / 空文字 172 |
| inaturalist_kanagawa | restricted | **679** | cc-by-sa 677 / cc-by-nd 2（商用利用自体は可だがShare-Alike/改変禁止の条件あり） |

合計: open 625,386 / noncommercial 176,397 / unknown 21,230 / restricted 679。
GBIF側に `unknown`（表示なし）は1件も無く、`restricted`（SA/ND）も0件だった。
未知のライセンス表記の検出も0件（`LICENSE_MAP` への追記は不要だった）。

DwC-A（`data/dwca/`）は既定で noncommercial(176,397) + unknown(21,230) = 197,627件を除外し、
open(625,386) + restricted(679) = **626,065件**を収録する。
**ソース単位での除外は0件**（`gbif_kanagawa_occurrences` が `source_registry` に登録されたため）。
除外の詳細は `data/dwca/EXCLUDED_LICENSE.md` に実行のたびに記録される。

**注意 — 生物観察データ全体の約24%は依然として再配布できない**: 823,692件のうち
noncommercial + unknown の 197,627件（**24.0%**）はDwC-Aから除外されている。
マスタDB `data/db/ryuiki.sqlite` にはこれらも**全件保持**しているため、そこから
再配布・商用利用する場合は必ず `license_class IN ('open','restricted')` または
`commercial_ok=1` で絞り込むこと（絞り込むと 626,065件）。

**既知の命名不整合の修正**: 従来`source_registry`に登録されるsource_idは`"gbif_kanagawa"`、
`organism_records.source_id`の実データは`"gbif_kanagawa_occurrences"`で、文字列として一致しない
状態だった。本タスクで`scripts/c02_gbif.py`・`scripts/c02_gbif_repair.py`の`register()`呼び出しを
`"gbif_kanagawa_occurrences"`に統一修正し、実データ側の名称にsource_registryを合わせた
（他スクリプトが`"gbif_kanagawa"`という文字列を参照していないことを`grep -rn`で確認済み。
参照していたのは`c02_gbif.py`/`c02_gbif_repair.py`のregister呼び出しのみ）。

**【2026-08-29 解消済み】** 第3ラウンドは修正後のコードで走ったため `source_registry` に
`gbif_kanagawa_occurrences` が正しく登録され、全テーブルを対象にした孤児検査で**孤児0件**を確認した
（`x01_dwca.py`の「未登録ソースによる除外」も occurrence=0 / measurement=0）。
第2ラウンド時点の旧登録 `gbif_kanagawa`（586,300行）は、`REBUILD.md`が想定していたUPDATE文では
主キー衝突で統合できない（両名が既に存在するため）。監査可能性を優先して**削除もリネームもせず**、
`notes` 冒頭に `【SUPERSEDED 2026-08-29】` を付して無効であることを明示する方針を採った。
GBIF_ALIASフォールバックは旧名だけが登録されている環境のために残してある。

### 4.6 CKANバルク収集・国土数値情報カタログの「混在ライセンス」
`ckan_env_bulk`（977件）・`ckan_kanagawa_pref`（811件）・`ckan_sagamihara`（114件）・
`geospatial_jp_kanagawa_catalog`（429件）は、いずれも収集ノートに「データセットごとにライセンスが異なる
（CC BY 4.0 / CC BY-NC 4.0 / 独自利用規約 / notspecified 等混在）」と明記されており、
本タスクの時間内には個票（リソース）単位でのライセンス再検証を行っていない。
商用提案に個別データセットを引用する場合は、そのデータセット固有のライセンスを都度確認すること。

### 4.7 OSM（OpenDatabaseLicense 1.0）
`osm_kanagawa_farmland`/`forest`/`protected_area`/`water`（合計約39000行、代表点座標のみ）はODbL 1.0が適用され、
(1) 帰属表示（"© OpenStreetMap contributors"）、(2) Share-Alike（このデータから作成した派生データベースを
公開する場合は同一または互換ライセンスで公開する義務）の2条件がある。**「流域カルテ」パッケージ全体を
単一のライセンス（例:CC BY 4.0）で一括配布する場合、OSM由来部分にShare-Alike条件を引き継がせる必要があるか、
あるいはOSM由来テーブルを独立した扱いにする必要があるかを法務的に確認すること。**

## 5. このデモを商用提案に載せる場合に確認が必要な項目

- **国土数値情報「非商用」4ソース**（W05河川2種・A10自然公園・A15鳥獣保護区）を商用提案の地図・図表に使う場合は、
  商用利用可能な代替データ（例: OSM河川・保護区データ、または別途許諾を得た国土数値情報データ）への差し替えを検討する。
- **モニタリングサイト1000**: 利用アンケートフォームが自動送信された経緯について、環境省生物多様性センターへの
  事後確認・許諾状況の確認を行う（申告した利用目的・提供組織名の妥当性を含む）。
  → **2026-08-29 に暫定対応済み**: フォーム経由で取得した10ソース（実データがあるのは
  `moni1000_satochi_bird`/`_mammal`/`_butterfly`・`moni1000_forest_bird`・`moni1000_coast_shorebird`
  の5件、計44,965行）を `redistributable=0` に変更し、**再配布不可として台帳に記録**した。
  データは削除しておらず `data/raw/`・`data/processed/` にすべて保全してある
  （権限者の追認が得られれば `redistributable=1` に戻すだけでよい。**再取得は不要**）。
  なお送信された所属名は「NPO法人コード・フォー・ジャパン」だったが、実際の法人格は
  **一般社団法人**であり、**組織について事実と異なる申告がなされている**。
  **追認・事後連絡の判断そのものは人間にしかできない**（`docs/nextstep.md` B-2）。
- **iNaturalist / GBIF のper-record非商用・無許諾ライセンス**: 本タスクで解消済み（§4.5）。
  `scripts/x01_dwca.py`は既定でCC BY-NC・ライセンスなしのレコードをDwC-Aから機械的に除外する。
  マスタDB側はlicense_class/commercial_ok列で区別のうえ全件保持しているため、
  商用提案でこのDBを直接使う場合は`commercial_ok=1`（または
  `license_class IN ('open','restricted')`）の絞り込みを必ず使うこと。
- **CKANバルク収集・G空間情報センター目録のライセンス混在**: 商用提案で個別データセットを引用する場合は、
  そのデータセットのライセンスを個票で再確認する。
- **OSM(ODbL)のShare-Alike条件**: 統合データベース全体のライセンス表示とOSM由来データの扱いを整理する。
- **神奈川県レッドリスト/レッドデータブック系（kanagawa_redlist等）**: 「出典記載で利用可、二次的利用（書籍転載等）は
  事前問合せ」という条件のため、taxaテーブル経由でレッドリストカテゴリを商用提案の図表に使う場合は出典表記を徹底し、
  大規模な転載相当の利用（原表そのものの再配布等）は所管所属へ事前確認する。
- **国土数値情報A45森林地域のCC BY表記とページ注記の矛盾**（4.3参照）を原典で再確認する。
- **`redistributable=0`のtanzawa_species_list_1997・ayu_upstream_migration**は生成済みファイルがあるが、
  `redistributable=0` である。商用提案で丹沢の生物相・アユ遡上数に言及する場合はこの2ソースを引用元として
  明示できない（別途許諾を得るか、環境省いきものログ等の代替ソースを検討する）。
- ~~**GBIFのsource_id命名不整合**~~ → **2026-08-29に解消**（4.5参照）。孤児0件を確認済み。
  ただし `source_registry` に旧登録 `gbif_kanagawa`（586,300行、`【SUPERSEDED】`注記付き）が
  残っているため、**ソース数・行数を集計する際はこの1件を除外すること**。
- **GBIF由来62,460件（CC BY-NC 4.0）は商用利用できない**。iNaturalistのnoncommercial 113,937件・
  unknown 21,230件と合わせ、生物観察記録 823,692件のうち **197,627件（24.0%）が再配布・商用利用の
  対象外**である。マスタDBはこれらも全件保持しているため、商用提案でこのDBを使う場合は
  `commercial_ok=1` の絞り込みを必ず経由すること。
