/**
 * 生成物。直接編集しない。サーバ専用（応答封筒の provenance が引く出典メタ）。
 *
 * 再生成: `cd web && pnpm run build:registry:ts`
 * 生成元: `web/scripts/build-registry-ts.mjs`（data/db/registry.sqlite の source / source_edition /
 * license 表。正は `registry/source/{editions,license}.yaml` と原本の `source_registry`）。
 *
 * `updateMode` が null の edition は「宣言なし」（推測で埋めない。`registry/source/editions.yaml`）。
 * `fetchedAt` は取得日時の壁時計（`YYYY-MM-DDTHH:MM:SS`、時刻帯なし。時刻帯は region から決める）。
 */

export interface GeneratedSourceMeta {
  sourceId: string;
  nameJa: string | null;
  publisher: string | null;
  homepageUrl: string | null;
  supersededBy: string | null;
}

export interface GeneratedSourceEdition {
  editionId: string;
  sourceId: string;
  editionKey: string;
  vintage: string | null;
  fetchedAt: string | null;
  url: string | null;
  licenseId: string;
  licenseClass: string;
  /** 出典の旗。出力を絞る根拠にしない（ADR-0028）。 */
  redistributable: boolean | null;
  /** snapshot / append / revision / static。null = 宣言なし。 */
  updateMode: string | null;
  supersededBy: string | null;
}

export interface GeneratedLicense {
  licenseId: string;
  nameJa: string | null;
  spdxOrUrl: string | null;
  licenseClass: string;
  attributionText: string | null;
}

export const SOURCE_META: readonly GeneratedSourceMeta[] = [
  { sourceId: "amami_biodiversity_strategy_amami", nameJa: "奄美大島生物多様性地域戦略（2020年3月改訂、計画期間2015〜2024年度）", publisher: "奄美大島自然保護協議会", homepageUrl: "https://www.vill.yamato.lg.jp/kikaku/kurashi/kankyo/shizenkankyo/shizenhogo/jore/documents/00_full.pdf", supersededBy: null },
  { sourceId: "amami_tourism_plans_amami", nameJa: "奄美群島エコツーリズム推進全体構想・奄美大島持続的観光マスタープラン", publisher: "奄美群島エコツーリズム推進協議会・鹿児島県", homepageUrl: "https://kyushu.env.go.jp/okinawa/amami-okinawa/plans/ecotourism/index.html", supersededBy: null },
  { sourceId: "atsugi_river_water_quality", nameJa: "厚木市 河川水質調査結果(相模川・中津川・小鮎川・玉川)", publisher: "厚木市", homepageUrl: "https://www.city.atsugi.kanagawa.jp/soshiki/seikatsukankyoka/2/3315.html", supersededBy: null },
  { sourceId: "ayu_upstream_migration", nameJa: "寒川取水堰 天然アユ遡上調査(相模川漁業協同組合連合会お知らせ記事より)", publisher: "相模川漁業協同組合連合会", homepageUrl: "http://sagamigawa-gyoren.jp/topics/2214/", supersededBy: null },
  { sourceId: "biodic_6th_kanagawa_report", nameJa: "第6回自然環境保全基礎調査 神奈川県報告書", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/reports2/6th/todouhuken/kanagawa/h16_kanagawa.pdf", supersededBy: null },
  { sourceId: "biodic_animal_distribution", nameJa: "自然環境保全基礎調査 動植物分布調査(全種調査) 対象種一覧", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/category/sizen/40.html", supersededBy: null },
  { sourceId: "biodic_kiban_datalist", nameJa: "生物多様性センター 基盤情報データリスト", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/category/kiban/datalist.html", supersededBy: null },
  { sourceId: "biodic_mammal_mesh_amami", nameJa: "中大型哺乳類分布調査(タヌキ・キツネ・アナグマ, いきもの地図/鹿児島県（奄美大島）相当bbox・3次メッシュ)", publisher: "環境省生物多様性センター", homepageUrl: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", supersededBy: null },
  { sourceId: "biodic_mammal_mesh_kanagawa", nameJa: "中大型哺乳類分布調査(タヌキ・キツネ・アナグマ, いきもの地図/神奈川県相当bbox・3次メッシュ)", publisher: "環境省生物多様性センター", homepageUrl: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", supersededBy: null },
  { sourceId: "biodic_veg2024_amami", nameJa: "現存植生図2024(いきもの地図/vg2024, 九州・沖縄ブロック・鹿児島県（奄美大島）相当bbox抽出)", publisher: "環境省生物多様性センター", homepageUrl: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", supersededBy: null },
  { sourceId: "biodic_veg2024_kanagawa", nameJa: "現存植生図2024(いきもの地図/vg2024, 関東ブロック・神奈川県相当bbox抽出)", publisher: "環境省生物多様性センター", homepageUrl: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", supersededBy: null },
  { sourceId: "biodic_vegcode_legend", nameJa: "植生調査共通凡例コード表(第2版, 2001-10-31~)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/dload/mesh_vg.html", supersededBy: null },
  { sourceId: "biodic_vegmesh_4th_kanagawa", nameJa: "植生調査 3次メッシュデータ 第4回自然環境保全基礎調査(1988-1992)（神奈川県相当メッシュ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/dload/mesh_vg.html", supersededBy: null },
  { sourceId: "biodic_vegmesh_5th_kanagawa", nameJa: "植生調査 3次メッシュデータ 第5回自然環境保全基礎調査(1992-1996)（神奈川県相当メッシュ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/dload/mesh_vg.html", supersededBy: null },
  { sourceId: "biodic_webgis", nameJa: "自然環境調査Web-GIS", publisher: "環境省生物多様性センター", homepageUrl: "http://gis.biodic.go.jp/webgis/", supersededBy: null },
  { sourceId: "bodik_kagoshima_ryuiki_chisui_amami", nameJa: "鹿児島県 奄美大島地域流域治水プロジェクト（BODIK）", publisher: "鹿児島県", homepageUrl: "https://data.bodik.jp/dataset/460001_1_01_ryuuikichisuipurojekuto", supersededBy: null },
  { sourceId: "buna_suitai_web", nameJa: "ブナ衰退WEB版(丹沢山地)", publisher: "神奈川県自然環境保全センター", homepageUrl: "https://www.agri-kanagawa.jp/WEB_buna/jittai_02rireki.html", supersededBy: null },
  { sourceId: "ckan_bodik_kanagawa", nameJa: "BODIK オープンデータカタログ(神奈川県内参加団体)", publisher: "BODIK(自治体クラウド推進機構) / 横須賀市・厚木市・真鶴町", homepageUrl: "https://data.bodik.jp/organization/142018+142123+143839", supersededBy: null },
  { sourceId: "ckan_env_bulk", nameJa: "CKAN 環境系リソース一括CSV化（神奈川県/相模原市）", publisher: "神奈川県・相模原市", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp", supersededBy: null },
  { sourceId: "ckan_kanagawa_pref", nameJa: "神奈川県オープンデータカタログ", publisher: "神奈川県", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp", supersededBy: null },
  { sourceId: "ckan_pdf_choju_higai", nameJa: "神奈川県 野生鳥獣による農作物被害状況（PDF、H30-R4）", publisher: "神奈川県 環境農政局 緑政部 自然環境保全課", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8", supersededBy: null },
  { sourceId: "ckan_pdf_choju_kyugo", nameJa: "神奈川県 傷病鳥獣救護実績（PDF、H22-R4）", publisher: "神奈川県 自然環境保全センター", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806", supersededBy: null },
  { sourceId: "ckan_pdf_ghg_kanagawa", nameJa: "神奈川県 温室効果ガス排出量・地球温暖化対策計画進捗（PDF由来）", publisher: "神奈川県 環境農政局", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp/dataset/38697849-5f80-4ec4-a02e-d84eb99dad49 ; https://catalog.opendata.pref.kanagawa.jp/dataset/73bcbaf9-8f49-4e67-adc0-bceb7b2ecf50 ; https://www.pref.kanagawa.jp/docs/ap4/cnt/f417509/shinontaikeikaku.html", supersededBy: null },
  { sourceId: "ckan_pdf_shinrin_toukei", nameJa: "統計資料集「神奈川の森林と林業」（PDF、ブロック済み）", publisher: "神奈川県 環境農政局 森林再生課", homepageUrl: "https://catalog.opendata.pref.kanagawa.jp/dataset/950a73db-1651-4bd3-8622-a3535477c1ef", supersededBy: null },
  { sourceId: "ckan_sagamihara", nameJa: "相模原市オープンデータカタログ", publisher: "相模原市", homepageUrl: "https://opendata.city.sagamihara.kanagawa.jp", supersededBy: null },
  { sourceId: "ckan_yokohama", nameJa: "横浜市オープンデータポータル", publisher: "横浜市", homepageUrl: "https://data.city.yokohama.lg.jp", supersededBy: null },
  { sourceId: "dams_kanagawa", nameJa: "神奈川県内主要ダム諸元(宮ヶ瀬・城山・相模・三保)", publisher: "国土交通省 関東地方整備局 / 神奈川県企業局", homepageUrl: "https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/ ; https://www.ktr.mlit.go.jp/sagami/", supersededBy: null },
  { sourceId: "dpri_gouu2010_amami", nameJa: "京都大学防災研究所 2010年奄美豪雨の調査速報（本文の雨量・被害）", publisher: "京都大学防災研究所（自然災害研究協議会災害調査団。竹林洋史）", homepageUrl: "https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf", supersededBy: null },
  { sourceId: "eadas_kanagawa", nameJa: "環境アセスメントデータベース EADAS（神奈川県事例）", publisher: "環境省大臣官房環境影響評価課", homepageUrl: "https://eadas.env.go.jp/", supersededBy: null },
  { sourceId: "env_kousui_annual_amami", nameJa: "環境省 公共用水域水質測定結果 年間値（奄美大島）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp", supersededBy: null },
  { sourceId: "env_kousui_annual_kanagawa", nameJa: "環境省 公共用水域水質測定結果 年間値（神奈川県）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp", supersededBy: null },
  { sourceId: "env_kousui_sample_amami", nameJa: "環境省 公共用水域水質測定結果 検体値（奄美大島）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", supersededBy: null },
  { sourceId: "env_kousui_sample_kanagawa", nameJa: "環境省 公共用水域水質測定結果 検体値（神奈川県）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", supersededBy: null },
  { sourceId: "env_kousui_stations_amami", nameJa: "環境省 公共用水域 水質測定点マスタ（奄美大島）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", supersededBy: null },
  { sourceId: "env_kousui_stations_kanagawa", nameJa: "環境省 公共用水域 水質測定点マスタ（神奈川県）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", supersededBy: null },
  { sourceId: "estat_agri_census_kanagawa", nameJa: "農林業センサス 市区町村別統計書(神奈川県) 農業経営体数・経営耕地面積・耕作放棄地面積", publisher: "農林水産省(e-Stat経由)", homepageUrl: "https://www.e-stat.go.jp/stat-search/files?page=1&layout=dataset&query=%E8%80%95%E4%BD%9C%E6%94%BE%E6%A3%84%E5%9C%B0%20%E7%A5%9E%E5%A5%88%E5%B7%9D%E7%9C%8C", supersededBy: null },
  { sourceId: "estat_census_population_kanagawa", nameJa: "令和7年国勢調査 速報集計 人口速報集計（男女別人口・世帯数, 2020年比較付き）神奈川県 市区町村別", publisher: "総務省統計局(e-Stat経由)", homepageUrl: "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040454825&fileKind=0", supersededBy: null },
  { sourceId: "estat_shozaiki_kanagawa", nameJa: "2020年国勢調査 小地域（町丁・字等別）境界データ 神奈川県", publisher: "総務省統計局 (e-Stat 統計地理情報システム)", homepageUrl: "https://www.e-stat.go.jp/gis/statmap-search?page=1&type=2&aggregateUnitForBoundary=A&toukeiCode=00200521&serveyId=A002005212020&prefCode=14&coordsys=1&format=shape", supersededBy: null },
  { sourceId: "etanzawa_siryousitu", nameJa: "丹沢資料室(一次資料アーカイブ)", publisher: "神奈川県 環境農政局 森林再生課 / 神奈川県自然環境保全センター", homepageUrl: "https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html", supersededBy: null },
  { sourceId: "gbif_amami_occurrences", nameJa: "GBIF Occurrence — 鹿児島県（奄美大島） (GADM JPN.18.4_1+JPN.18.38_1+JPN.18.41_1+JPN.18.44_1+JPN.18.34_1)", publisher: "GBIF", homepageUrl: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.18.4_1&gadm_gid=JPN.18.38_1&gadm_gid=JPN.18.41_1&gadm_gid=JPN.18.44_1&gadm_gid=JPN.18.34_1", supersededBy: null },
  { sourceId: "gbif_kanagawa", nameJa: "GBIF Occurrence — 神奈川県 (GADM JPN.19_1)", publisher: "GBIF", homepageUrl: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.19_1", supersededBy: "gbif_kanagawa_occurrences" },
  { sourceId: "gbif_kanagawa_occurrences", nameJa: "GBIF Occurrence — 神奈川県 (GADM JPN.19_1)", publisher: "GBIF", homepageUrl: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.19_1", supersededBy: null },
  { sourceId: "gbif_species_match", nameJa: "GBIF Backbone Taxonomy 学名照合（species/match API）", publisher: "Global Biodiversity Information Facility (GBIF)", homepageUrl: "https://api.gbif.org/v1/species/match", supersededBy: null },
  { sourceId: "geoshape_sagami_river", nameJa: "相模川水系 河川データ(水系単位, NII再パッケージ版)", publisher: "国立情報学研究所(NII) geoshape.ex.nii.ac.jp / 原データ: 国土交通省 国土数値情報(KSJ) W05 河川", homepageUrl: "https://geoshape.ex.nii.ac.jp/river/resource/830307/stream.json", supersededBy: null },
  { sourceId: "geospatial_jp_agri_point_2021_sagami", nameJa: "農地筆ポリゴン2021 重心点データ（相模川流域市町村, geospatial.jp）", publisher: "農林水産省（配信: 一般社団法人社会基盤情報流通推進協議会 aigid, G空間情報センター）", homepageUrl: "https://www.geospatial.jp/ckan/dataset/agri-point-2021-14", supersededBy: null },
  { sourceId: "geospatial_jp_agri_poly_2021_sagami", nameJa: "農地筆ポリゴン2021 ポリゴン本体（相模川流域市町村, geospatial.jp, 生ファイルのみ）", publisher: "農林水産省（配信: aigid, G空間情報センター）", homepageUrl: "https://www.geospatial.jp/ckan/dataset/agri-poly-2021-14", supersededBy: null },
  { sourceId: "geospatial_jp_kanagawa_catalog", nameJa: "G空間情報センター 神奈川県・相模川流域関連データセット目録", publisher: "国土交通省 G空間情報センター（運営: 一般社団法人 社会基盤情報流通推進協議会）", homepageUrl: "https://www.geospatial.jp/ckan/dataset?q=神奈川", supersededBy: null },
  { sourceId: "geospatial_jp_kokudo_landclass_kanagawa", nameJa: "国土調査 20万分の1土地分類基本調査等 神奈川県（生ファイルのみ）", publisher: "国土交通省 国土政策局 国土情報課", homepageUrl: "https://www.geospatial.jp/ckan/dataset/mlit-kokudo-2", supersededBy: null },
  { sourceId: "geospatial_jp_kokudo_river_sagami", nameJa: "国土調査 主要水系調査（一級水系）相模川地域（生ファイルのみ）", publisher: "国土交通省 国土政策局 国土情報課", homepageUrl: "https://www.geospatial.jp/ckan/dataset/mlit-kokudo-6", supersededBy: null },
  { sourceId: "geospatial_jp_plateau_kanagawa", nameJa: "G空間情報センター PLATEAU 神奈川県内市町村 3D都市モデル目録", publisher: "国土交通省 Project PLATEAU", homepageUrl: "https://www.geospatial.jp/ckan/dataset?q=plateau", supersededBy: null },
  { sourceId: "geospatial_jp_pointcloud_kanagawa", nameJa: "G空間情報センター 神奈川県 航空レーザ測量3次元点群データ目録", publisher: "神奈川県 環境農政局緑政部森林再生課", homepageUrl: "https://www.geospatial.jp/ckan/dataset/kanagawa-2022-pointcloud", supersededBy: null },
  { sourceId: "gsi_dem_terrain", nameJa: "国土地理院 標高タイル（DEM10B）から計算した地点の地形指標", publisher: "国土交通省国土地理院", homepageUrl: "https://maps.gsi.go.jp/development/demtile.html", supersededBy: null },
  { sourceId: "gsi_elevation_grid", nameJa: "国土地理院 標高API グリッド取得（神奈川県相当範囲）", publisher: "国土交通省国土地理院", homepageUrl: "https://maps.gsi.go.jp/development/elevation_s.html", supersededBy: null },
  { sourceId: "gsi_elevation_grid_amami", nameJa: "国土地理院 標高API グリッド取得（鹿児島県（奄美大島）相当範囲）", publisher: "国土交通省国土地理院", homepageUrl: "https://maps.gsi.go.jp/development/elevation_s.html", supersededBy: null },
  { sourceId: "gsi_kiban_chizu_joho", nameJa: "基盤地図情報（基本項目・数値標高モデル等）ダウンロードサービス", publisher: "国土交通省国土地理院", homepageUrl: "https://service.gsi.go.jp/kiban/", supersededBy: null },
  { sourceId: "gsj_geology_points", nameJa: "20万分の1日本シームレス地質図V2 地点別地質判定（相模川流域グリッド）", publisher: "産業技術総合研究所 地質調査総合センター(GSJ)", homepageUrl: "https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.json?point=<lat>,<lon>", supersededBy: null },
  { sourceId: "gsj_seamless_legend", nameJa: "20万分の1日本シームレス地質図V2 凡例（全凡例）", publisher: "産業技術総合研究所 地質調査総合センター(GSJ)", homepageUrl: "https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.csv", supersededBy: null },
  { sourceId: "hadano_preserved_trees", nameJa: "秦野市 保存樹木一覧", publisher: "秦野市", homepageUrl: "https://www.city.hadano.kanagawa.jp/material/files/group/6/142115_preserve_tree.csv", supersededBy: null },
  { sourceId: "hiratsuka_parks", nameJa: "平塚市オープンデータ 公園一覧", publisher: "平塚市", homepageUrl: "https://www.city.hiratsuka.kanagawa.jp/common/200204844.csv", supersededBy: null },
  { sourceId: "hiratsuka_taiki", nameJa: "平塚市 大気環境状況 確定値1時間値（日別集計）", publisher: "平塚市環境保全課", homepageUrl: "https://hiratsukataiki.sakura.ne.jp/download-kakutei.php", supersededBy: null },
  { sourceId: "hiratsuka_taiki_stations", nameJa: "平塚市 大気環境状況 測定局一覧", publisher: "平塚市環境保全課", homepageUrl: "https://hiratsukataiki.sakura.ne.jp/download-kakutei.php", supersededBy: null },
  { sourceId: "ikilog", nameJa: "いきものログ（市民参加型生物観察記録DB）", publisher: "環境省", homepageUrl: "https://ikilog.biodic.go.jp/", supersededBy: null },
  { sourceId: "inaturalist_amami", nameJa: "iNaturalist 観察記録 — 鹿児島県（奄美大島） (place 34051 + 34081 + 34085 + 34091 + 34088)", publisher: "iNaturalist", homepageUrl: "https://www.inaturalist.org/observations?place_id=34051&place_id=34081&place_id=34085&place_id=34091&place_id=34088", supersededBy: null },
  { sourceId: "inaturalist_kanagawa", nameJa: "iNaturalist 観察記録 — 神奈川県 (place 10918)", publisher: "iNaturalist", homepageUrl: "https://www.inaturalist.org/observations?place_id=10918", supersededBy: null },
  { sourceId: "jma_daily_nase", nameJa: "気象庁 過去の気象データ 日別値（名瀬 47909）", publisher: "気象庁", homepageUrl: "https://www.data.jma.go.jp/stats/etrn/view/daily_s1.php?prec_no=88&block_no=47909", supersededBy: null },
  { sourceId: "jma_daily_yokohama", nameJa: "気象庁 過去の気象データ 日別値（横浜 47670）", publisher: "気象庁", homepageUrl: "https://www.data.jma.go.jp/stats/etrn/view/daily_s1.php?prec_no=46&block_no=47670", supersededBy: null },
  { sourceId: "jma_monthly_amami", nameJa: "気象庁 過去の気象データ 月別値（奄美大島 主要地点）", publisher: "気象庁", homepageUrl: "https://www.data.jma.go.jp/stats/etrn/index.php", supersededBy: null },
  { sourceId: "jma_monthly_kanagawa", nameJa: "気象庁 過去の気象データ 月別値（神奈川県 主要地点）", publisher: "気象庁", homepageUrl: "https://www.data.jma.go.jp/stats/etrn/index.php", supersededBy: null },
  { sourceId: "jma_sst_amami", nameJa: "気象庁 沿岸の海面水温（奄美群島 海域617〜620）", publisher: "気象庁", homepageUrl: "https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan/engan_KG.html", supersededBy: null },
  { sourceId: "jma_stations_amami", nameJa: "気象庁 奄美大島 観測地点一覧（アメダス+官署）", publisher: "気象庁", homepageUrl: "https://www.jma.go.jp/bosai/amedas/const/amedastable.json", supersededBy: null },
  { sourceId: "jma_stations_kanagawa", nameJa: "気象庁 神奈川県 観測地点一覧（アメダス+官署）", publisher: "気象庁", homepageUrl: "https://www.jma.go.jp/bosai/amedas/const/amedastable.json", supersededBy: null },
  { sourceId: "kagoshima_habu_amami", nameJa: "鹿児島県 ハブ咬傷者数・ハブ買上数（奄美、保健所・市町村別、H28〜R7年度）", publisher: "鹿児島県 保健福祉部薬務課", homepageUrl: "https://www.pref.kagoshima.jp/ae10/kenko-fukushi/yakuji-eisei/habu/index.html", supersededBy: null },
  { sourceId: "kagoshima_irikomi_amami", nameJa: "奄美群島入込客・入域客数（海路・空路）", publisher: "鹿児島県 大島支庁総務企画課（BODIK）", homepageUrl: "https://data.bodik.jp/dataset/460001_guntou_irikomi_nyuiki", supersededBy: null },
  { sourceId: "kagoshima_kasen_choui_amami", nameJa: "鹿児島県 河川砂防情報システムデータ（潮位・奄美大島・日別）", publisher: "鹿児島県 土木部河川課（BODIK）", homepageUrl: "https://data.bodik.jp/dataset/460001_choui", supersededBy: null },
  { sourceId: "kagoshima_kasen_dam_amami", nameJa: "鹿児島県 河川砂防情報システムデータ（ダム諸量・奄美大島・日別）", publisher: "鹿児島県 土木部河川課（BODIK）", homepageUrl: "https://data.bodik.jp/dataset/460001_dam", supersededBy: null },
  { sourceId: "kagoshima_kasen_stations_amami", nameJa: "鹿児島県 河川砂防情報システム 観測所（奄美大島）", publisher: "鹿児島県 土木部河川課", homepageUrl: "https://www.pref.kagoshima.jp/ah08/infra/kasen-sabo/sabo/jyouhoushisutemu.html", supersededBy: null },
  { sourceId: "kagoshima_kasen_suii_amami", nameJa: "鹿児島県 河川砂防情報システムデータ（水位（通常）・奄美大島・日別）", publisher: "鹿児島県 土木部河川課（BODIK）", homepageUrl: "https://data.bodik.jp/dataset/460001_suii", supersededBy: null },
  { sourceId: "kagoshima_kasen_suii_kiki_amami", nameJa: "鹿児島県 河川砂防情報システムデータ（水位（危機管理型）・奄美大島・日別）", publisher: "鹿児島県 土木部河川課（BODIK）", homepageUrl: "https://data.bodik.jp/dataset/460001_suii", supersededBy: null },
  { sourceId: "kagoshima_noneko_amami", nameJa: "奄美大島のノネコ捕獲状況（2018〜2022年度、2023年3月末現在）", publisher: "環境省 九州地方環境事務所 沖縄奄美自然環境事務所 奄美野生生物保護センター", homepageUrl: "https://kyushu.env.go.jp/okinawa/awcc/Wild-dog-Wild-cat.html", supersededBy: null },
  { sourceId: "kagoshima_ordinance_species", nameJa: "鹿児島県指定希少野生動植物（令和8年9月現在 59種）", publisher: "鹿児島県 環境林務部 自然保護課", homepageUrl: "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/zyorei/03007006.html", supersededBy: null },
  { sourceId: "kagoshima_redlist", nameJa: "鹿児島県レッドリスト（平成26年改訂。動物・植物の掲載ページは平成27年度改訂）", publisher: "鹿児島県 環境林務部 自然保護課", homepageUrl: "http://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/reddata/plant-list4.html", supersededBy: null },
  { sourceId: "kagoshima_umigame_amami", nameJa: "鹿児島県 ウミガメ上陸・産卵確認状況（市町村別、R7年度版）", publisher: "鹿児島県 環境林務部 自然保護課", homepageUrl: "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/umigame/umigame.html", supersededBy: null },
  { sourceId: "kagoshima_univ_gouu2010_amami", nameJa: "鹿児島大学 2010年奄美豪雨災害の総合的調査研究報告書（雨量・被害）", publisher: "鹿児島大学奄美豪雨災害調査委員会", homepageUrl: "https://bousai.kagoshima-u.ac.jp/wpo/wp-content/uploads/2024/03/2010_gouu.pdf", supersededBy: null },
  { sourceId: "kanagawa_dam_mizugame", nameJa: "かながわの水がめ（相模川・酒匂川水系 降水量/貯水量/ダム諸量）", publisher: "神奈川県企業庁", homepageUrl: "https://kanagawa-dam.jp/", supersededBy: null },
  { sourceId: "kanagawa_edna", nameJa: "神奈川県 環境DNA調査結果（県民協働・プロジェクト）", publisher: "神奈川県 環境農政局 環境部 水・大気環境課", homepageUrl: "https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html", supersededBy: null },
  { sourceId: "kanagawa_green_conservation", nameJa: "かながわのみどりの保全（指定状況PDF4種）", publisher: "神奈川県環境農政局", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f10578/index.html", supersededBy: null },
  { sourceId: "kanagawa_ikimono_chousa", nameJa: "かながわ生きもの調査 年度別結果", publisher: "神奈川県", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1195000.html", supersededBy: null },
  { sourceId: "kanagawa_jiban_chinka", nameJa: "地盤沈下調査結果(令和4〜6年度、観測井戸・水準点)", publisher: "神奈川県 環境農政局 環境部環境課 水環境グループ", homepageUrl: "https://www.pref.kanagawa.jp/docs/pf7/cnt/f41044/p81475.html", supersededBy: null },
  { sourceId: "kanagawa_kuma_sightings", nameJa: "神奈川県 ツキノワグマ目撃等情報(年度別個票)", publisher: "神奈川県 環境農政局 緑政部自然環境保全課", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f3813/index.html", supersededBy: null },
  { sourceId: "kanagawa_natural_parks", nameJa: "県内の自然公園（指定状況一覧）", publisher: "神奈川県環境農政局", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f5842/p16572.html", supersededBy: null },
  { sourceId: "kanagawa_rdb2006_animals", nameJa: "神奈川県レッドデータ生物調査報告書2006（レッドリスト集計結果・一覧）", publisher: "神奈川県立生命の星・地球博物館", homepageUrl: "https://nh.kanagawa-museum.jp/assets/icp/contents/1657590295853/simple/RedData2006_shukeikekka_ichiran.pdf", supersededBy: null },
  { sourceId: "kanagawa_rdb2006_errata", nameJa: "神奈川県レッドデータ生物調査報告書2006 正誤表", publisher: "神奈川県立生命の星・地球博物館", homepageUrl: "https://nh.kanagawa-museum.jp/publications/other/reddata.html", supersededBy: null },
  { sourceId: "kanagawa_rdb2022_plants", nameJa: "神奈川県レッドデータブック2022 植物編", publisher: "神奈川県環境農政局緑政部自然環境保全課", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1197000.html", supersededBy: null },
  { sourceId: "kanagawa_redlist", nameJa: "神奈川県レッドリスト（2020植物編・2026昆虫類クモ類）", publisher: "神奈川県環境農政局緑政部自然環境保全課", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1061385.html", supersededBy: null },
  { sourceId: "kanagawa_redlist_categories", nameJa: "神奈川県レッドリスト カテゴリー区分表", publisher: "神奈川県環境農政局緑政部自然環境保全課", homepageUrl: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1196500.html", supersededBy: null },
  { sourceId: "kanagawa_river_citizen_survey", nameJa: "神奈川県 河川のモニタリング調査(相模川・酒匂川、動植物等調査+県民参加型調査)", publisher: "神奈川県 環境農政局 水源環境保全課(環境科学センター実施)", homepageUrl: "https://www.pref.kanagawa.jp/docs/b4f/suigen/top.html", supersededBy: null },
  { sourceId: "kanagawa_shizenshi_bibliography", nameJa: "神奈川自然誌資料 バックナンバー書誌目録（論文タイトル・著者・ページ・PDFリンク）", publisher: "神奈川県立生命の星・地球博物館", homepageUrl: "https://nh.kanagawa-museum.jp/publications/nhr/index.html", supersededBy: null },
  { sourceId: "kasen_kokusei_sagami", nameJa: "河川水辺の国勢調査（相模川）", publisher: "国土交通省 関東地方整備局 京浜河川事務所", homepageUrl: "https://www.ktr.mlit.go.jp/keihin/keihin00294.html", supersededBy: null },
  { sourceId: "miyagase_storage_status", nameJa: "宮ケ瀬ダム貯水状況のお知らせ", publisher: "国土交通省 関東地方整備局 相模川水系広域ダム管理事務所", homepageUrl: "https://www.ktr.mlit.go.jp/sagami/sagami01113.html", supersededBy: null },
  { sourceId: "mlit_amami_action_plan_amami", nameJa: "国土交通省 奄美大島 行動計画（2016年）", publisher: "国土交通省", homepageUrl: "https://www.mlit.go.jp/common/001294716.pdf", supersededBy: null },
  { sourceId: "mlit_river_hydro", nameJa: "国土交通省 水文水質データベース", publisher: "国土交通省", homepageUrl: "https://www1.river.go.jp/", supersededBy: null },
  { sourceId: "moe_amami_wh_plans_amami", nameJa: "環境省 奄美の世界自然遺産関連の計画・評価シート（包括的管理計画・マングース・ノネコ・モニタリング評価）", publisher: "環境省 九州地方環境事務所 沖縄奄美自然環境事務所", homepageUrl: "https://kyushu.env.go.jp/okinawa/amami-okinawa/plans/index.html", supersededBy: null },
  { sourceId: "moe_ias_list", nameJa: "生態系被害防止外来種リスト（我が国の生態系等に被害を及ぼすおそれのある外来種リスト）", publisher: "環境省 自然環境局", homepageUrl: "https://www.env.go.jp/nature/intro/2outline/iaslist.html", supersededBy: null },
  { sourceId: "moe_meisui_kanagawa", nameJa: "名水百選（神奈川県分: 秦野盆地湧水群・洒水の滝/滝沢川）", publisher: "環境省", homepageUrl: "https://water-pub.env.go.jp/water-pub/mizu-site/meisui/", supersededBy: null },
  { sourceId: "moe_mongoose_amami", nameJa: "環境省 奄美大島 マングース捕獲数・わな日・CPUE（2000〜2022年度）", publisher: "環境省 沖縄奄美自然環境事務所", homepageUrl: "https://kyushu.env.go.jp/okinawa/press_00065.html", supersededBy: null },
  { sourceId: "moe_redlist", nameJa: "環境省レッドリスト（分類群ごとの最新版）", publisher: "環境省／生物多様性センター いきものログ", homepageUrl: "https://www.env.go.jp/nature/kisho/hozen/redlist/", supersededBy: null },
  { sourceId: "moe_satoyama_kanagawa", nameJa: "重要里地里山 選定地一覧（神奈川県）", publisher: "環境省", homepageUrl: "https://www.env.go.jp/nature/satoyama/14_kanagawa/kanagawa.html", supersededBy: null },
  { sourceId: "moni1000_coast_shorebird", nameJa: "モニタリングサイト1000 沿岸域(シギ・チドリ類)調査（神奈川県サイトのみ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/coast.html", supersededBy: null },
  { sourceId: "moni1000_forest_bird", nameJa: "モニタリングサイト1000 森林・草原調査 陸生鳥類調査（神奈川県サイトのみ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/forest.html", supersededBy: null },
  { sourceId: "moni1000_lake_aquaticplants", nameJa: "モニタリングサイト1000 陸水域(湖沼)水生植物調査(KOS07)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/wetlands.html", supersededBy: null },
  { sourceId: "moni1000_lake_benthos", nameJa: "モニタリングサイト1000 陸水域(湖沼)底生動物調査(KOS04)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/wetlands.html", supersededBy: null },
  { sourceId: "moni1000_lake_fish", nameJa: "モニタリングサイト1000 陸水域(湖沼)淡水魚調査(KOS06)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/wetlands.html", supersededBy: null },
  { sourceId: "moni1000_satochi_bird", nameJa: "モニタリングサイト1000 里地鳥類調査（神奈川県サイトのみ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/village.html", supersededBy: null },
  { sourceId: "moni1000_satochi_butterfly", nameJa: "モニタリングサイト1000 里地チョウ類調査（神奈川県サイトのみ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/village.html", supersededBy: null },
  { sourceId: "moni1000_satochi_mammal", nameJa: "モニタリングサイト1000 里地中・大型哺乳類調査(自動撮影)（神奈川県サイトのみ抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/village.html", supersededBy: null },
  { sourceId: "moni1000_sites", nameJa: "モニタリングサイト1000 サイト一覧（全国・神奈川抽出）", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/site_list.html", supersededBy: null },
  { sourceId: "moni1000_waterfowl", nameJa: "モニタリングサイト1000 ガンカモ類調査(GAN01)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/wetlands.html", supersededBy: null },
  { sourceId: "moni1000_wetland_vegetation", nameJa: "モニタリングサイト1000 陸水域(湿原)湿原植生調査(SIT01)", publisher: "環境省生物多様性センター", homepageUrl: "https://www.biodic.go.jp/moni1000/wetlands.html", supersededBy: null },
  { sourceId: "nlni_a03_metro_area", nameJa: "国土数値情報 三大都市圏（全国）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A03.html", supersededBy: null },
  { sourceId: "nlni_a10_natparks", nameJa: "国土数値情報 自然公園地域（神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html", supersededBy: null },
  { sourceId: "nlni_a10_natparks_amami", nameJa: "国土数値情報 自然公園地域（鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html", supersededBy: null },
  { sourceId: "nlni_a15_wildlife", nameJa: "国土数値情報 鳥獣保護区（神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html", supersededBy: null },
  { sourceId: "nlni_a15_wildlife_amami", nameJa: "国土数値情報 鳥獣保護区（鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html", supersededBy: null },
  { sourceId: "nlni_a45_forest", nameJa: "国土数値情報 森林地域（国有林小班・神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html", supersededBy: null },
  { sourceId: "nlni_a45_forest_amami", nameJa: "国土数値情報 森林地域（国有林小班・鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html", supersededBy: null },
  { sourceId: "nlni_c23_coastline", nameJa: "国土数値情報 海岸線（神奈川県・鹿児島県奄美周辺）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C23.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_2006", nameJa: "国土数値情報 土地利用細分メッシュ（神奈川県流域内, 2006年）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_2006_amami", nameJa: "国土数値情報 土地利用細分メッシュ（鹿児島県（奄美大島）, 2006年）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_2016", nameJa: "国土数値情報 土地利用細分メッシュ（神奈川県流域内, 2016年）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_2016_amami", nameJa: "国土数値情報 土地利用細分メッシュ（鹿児島県（奄美大島）, 2016年）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_by_watershed", nameJa: "土地利用細分メッシュ 流域別集計（神奈川県 2006/2016）", publisher: "国土交通省 国土数値情報ダウンロードサイト（本収集で集計）", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_l03b_landuse_by_watershed_amami", nameJa: "土地利用細分メッシュ 流域別集計（鹿児島県（奄美大島） 2006/2016）", publisher: "国土交通省 国土数値情報ダウンロードサイト（本収集で集計）", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", supersededBy: null },
  { sourceId: "nlni_p05_city_hall", nameJa: "国土数値情報 市町村役場等及び公的集会施設", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05.html", supersededBy: null },
  { sourceId: "nlni_w05_river_nodes", nameJa: "国土数値情報 河川（河川端点・神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", supersededBy: null },
  { sourceId: "nlni_w05_river_nodes_amami", nameJa: "国土数値情報 河川（河川端点・鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", supersededBy: null },
  { sourceId: "nlni_w05_rivers", nameJa: "国土数値情報 河川（流路・神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", supersededBy: null },
  { sourceId: "nlni_w05_rivers_amami", nameJa: "国土数値情報 河川（流路・鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", supersededBy: null },
  { sourceId: "nlni_w07_watershed_mesh", nameJa: "国土数値情報 流域メッシュ（神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W07.html", supersededBy: null },
  { sourceId: "nlni_w12_watersheds", nameJa: "国土数値情報 流域界・非集水域（神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", supersededBy: null },
  { sourceId: "nlni_w12_watersheds_amami", nameJa: "国土数値情報 流域界・非集水域（鹿児島県（奄美大島））", publisher: "国土交通省 国土数値情報ダウンロードサイト", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", supersededBy: null },
  { sourceId: "nlni_w12_watersheds_by_system", nameJa: "国土数値情報 流域界 旧水系域コード別集計（神奈川県）", publisher: "国土交通省 国土数値情報ダウンロードサイト（本収集で集計）", homepageUrl: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", supersededBy: null },
  { sourceId: "osm_amami_farmland", nameJa: "OSM 鹿児島県（奄美大島） 農地（landuse=farmland, meadow）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_amami_forest", nameJa: "OSM 鹿児島県（奄美大島） 森林（landuse=forest, natural=wood）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_amami_protected_area", nameJa: "OSM 鹿児島県（奄美大島） 保護区（nature_reserve, protected_area）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_amami_water", nameJa: "OSM 鹿児島県（奄美大島） 水系（水域・河川）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_kanagawa_farmland", nameJa: "OSM 神奈川県 農地（landuse=farmland, meadow）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_kanagawa_forest", nameJa: "OSM 神奈川県 森林（landuse=forest, natural=wood）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_kanagawa_protected_area", nameJa: "OSM 神奈川県 保護区（nature_reserve, protected_area）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "osm_kanagawa_water", nameJa: "OSM 神奈川県 水系（水域・河川）", publisher: "OpenStreetMap contributors", homepageUrl: "https://overpass-api.de/api/interpreter", supersededBy: null },
  { sourceId: "resas_api", nameJa: "RESAS-API (地域経済分析システム)", publisher: "内閣官房・内閣府 デジタル田園都市国家構想実現会議事務局", homepageUrl: "https://opendata.resas-portal.go.jp/", supersededBy: null },
  { sourceId: "rinya_forest_stats_prefecture", nameJa: "都道府県別森林率・人工林率", publisher: "林野庁", homepageUrl: "https://www.rinya.maff.go.jp/j/keikaku/genkyou/r4/attach/xls/1-1.xlsx", supersededBy: null },
  { sourceId: "rinya_lidar_kanagawa_status", nameJa: "森林情報オープンデータ化(航空レーザ計測)神奈川県公開状況", publisher: "林野庁", homepageUrl: "https://www.rinya.maff.go.jp/j/keikaku/smartforest/smart_forestry.html", supersededBy: null },
  { sourceId: "sagami_livecams", nameJa: "相模川ライブカメラ地点一覧", publisher: "国土交通省 関東地方整備局 京浜河川事務所", homepageUrl: "https://www.ktr.mlit.go.jp/keihin/keihin01459.html", supersededBy: null },
  { sourceId: "sagami_seibi_keikaku_mirror", nameJa: "相模川・中津川河川整備計画(京浜河川事務所ポータル)", publisher: "国土交通省 関東地方整備局 京浜河川事務所 / 神奈川県", homepageUrl: "https://www.ktr.mlit.go.jp/keihin/keihin_index056.html", supersededBy: null },
  { sourceId: "sagamihara_digital_archive", nameJa: "さがみはらデジタルアーカイブ 生物カテゴリ目録（相模原市立博物館 自然史標本）", publisher: "相模原市（相模原市立博物館）", homepageUrl: "https://digital-sagamihara.jp/digital-archive/?category=5", supersededBy: null },
  { sourceId: "sagamihara_taiki_hourly", nameJa: "相模原市 大気汚染常時監視測定結果 1時間値（流域デモ抽出）", publisher: "相模原市", homepageUrl: "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", supersededBy: null },
  { sourceId: "sagamihara_taiki_stations", nameJa: "相模原市 大気汚染常時監視 測定局一覧", publisher: "相模原市", homepageUrl: "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", supersededBy: null },
  { sourceId: "satonavi_donkai", nameJa: "里なび 保全活動団体・エリア検索「自然塾丹沢ドン会」", publisher: "環境省 自然環境局 自然環境計画課", homepageUrl: "https://www.env.go.jp/nature/satoyama/satonavi/group/12.html", supersededBy: null },
  { sourceId: "snet_kahaku", nameJa: "サイエンスミュージアムネット S-Net（自然史標本横断検索）", publisher: "国立科学博物館", homepageUrl: "https://science-net.kahaku.go.jp/", supersededBy: null },
  { sourceId: "soramame_hourly_amami", nameJa: "環境省 そらまめ君 1時間値（奄美大島 流域デモ1局）", publisher: "環境省", homepageUrl: "https://soramame.env.go.jp/download", supersededBy: null },
  { sourceId: "soramame_hourly_kanagawa", nameJa: "環境省 そらまめ君 1時間値（神奈川県 流域デモ4局）", publisher: "環境省", homepageUrl: "https://soramame.env.go.jp/download", supersededBy: null },
  { sourceId: "soramame_stations_amami", nameJa: "環境省 そらまめ君 測定局マスタ（奄美大島）", publisher: "環境省", homepageUrl: "https://soramame.env.go.jp/", supersededBy: null },
  { sourceId: "soramame_stations_kanagawa", nameJa: "環境省 そらまめ君 測定局マスタ（神奈川県）", publisher: "環境省", homepageUrl: "https://soramame.env.go.jp/", supersededBy: null },
  { sourceId: "tanzawa_shika_suigen_docs", nameJa: "丹沢 ニホンジカ管理実績・保護管理計画/水源環境保全再生 最終評価報告書", publisher: "神奈川県 環境農政局 自然環境保全課 / 水源環境保全・再生かながわ県民会議", homepageUrl: "https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html", supersededBy: null },
  { sourceId: "tanzawa_species_list_1997", nameJa: "丹沢のビジターセンター 生き物リスト(哺乳類/鳥類/は虫類/両生類/昆虫)", publisher: "神奈川県立 秦野ビジターセンター・西丹沢ビジターセンター(公益財団法人神奈川県公園協会)", homepageUrl: "https://www.kanagawa-park.or.jp/tanzawavc/ikimono1.html", supersededBy: null },
  { sourceId: "tanzawa_visitor_centers", nameJa: "丹沢情報発信基地ビジターセンター(秦野VC・西丹沢VC)", publisher: "神奈川県 環境農政局 環境部 自然環境保全センター", homepageUrl: "https://www.pref.kanagawa.jp/docs/f4y/02yama/visitor.html", supersededBy: null },
  { sourceId: "water_source_docs", nameJa: "水道水の水源マップ 根拠資料（事業体の水質検査計画・事業概要）", publisher: "各水道事業体", homepageUrl: "https://www.kwsa.or.jp/ ほか", supersededBy: null },
  { sourceId: "water_trace_kawasaki", nameJa: "川崎市上下水道局 令和8年度水質検査計画 p11 図−7 の塗り分けのラスタ読み取り", publisher: "川崎市上下水道局", homepageUrl: "https://www.city.kawasaki.jp/800/page/0000083603.html", supersededBy: null },
  { sourceId: "water_trace_yokohama", nameJa: "横浜市水道局 令和8年度水質検査計画 p11 給水区域図のラスタ読み取り", publisher: "横浜市水道局", homepageUrl: "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/suidosui/suishitsu-keikaku.html", supersededBy: null },
  { sourceId: "ylist", nameJa: "YList 植物和名ー学名インデックス（日本産維管束植物 和名-学名インデックス）", publisher: "米倉浩司・梶田忠（琉球大学熱帯生物圏研究センター）", homepageUrl: "http://ylist.info/", supersededBy: null },
  { sourceId: "yokohama_bio_indicator", nameJa: "横浜市 環境管理計画年次報告書 資料編(河川 生物指標水質評価)", publisher: "横浜市(みどり環境局)", homepageUrl: "https://www.city.yokohama.lg.jp/kurashi/machizukuri-kankyo/kankyohozen/emp/shiryou.html", supersededBy: null },
  { sourceId: "yokohama_river_waterlevel", nameJa: "横浜市 河川水位オープンデータ", publisher: "横浜市(下水道河川局)", homepageUrl: "https://www.city.yokohama.lg.jp/kurashi/machizukuri-kankyo/kasen-gesuido/kasen/suibou/opendata.html", supersededBy: null },
];

export const SOURCE_EDITIONS: readonly GeneratedSourceEdition[] = [
  { editionId: "common:edition:amami_biodiversity_strategy_amami.20261011", sourceId: "amami_biodiversity_strategy_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T01:02:48", url: "https://www.vill.yamato.lg.jp/kikaku/kurashi/kankyo/shizenkankyo/shizenhogo/jore/documents/00_full.pdf", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:amami_tourism_plans_amami.20261011", sourceId: "amami_tourism_plans_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T01:02:48", url: "https://kyushu.env.go.jp/okinawa/amami-okinawa/plans/ecotourism/index.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:atsugi_river_water_quality.20260830", sourceId: "atsugi_river_water_quality", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:20:58", url: "https://www.city.atsugi.kanagawa.jp/soshiki/seikatsukankyoka/2/3315.html", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "static", supersededBy: null },
  { editionId: "common:edition:ayu_upstream_migration.20260829", sourceId: "ayu_upstream_migration", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:14:49", url: "http://sagamigawa-gyoren.jp/topics/2214/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_6th_kanagawa_report.20260829", sourceId: "biodic_6th_kanagawa_report", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:09:55", url: "https://www.biodic.go.jp/reports2/6th/todouhuken/kanagawa/h16_kanagawa.pdf", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_animal_distribution.20260829", sourceId: "biodic_animal_distribution", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:13:35", url: "https://www.biodic.go.jp/category/sizen/40.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_kiban_datalist.20260829", sourceId: "biodic_kiban_datalist", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:13:51", url: "https://www.biodic.go.jp/category/kiban/datalist.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_mammal_mesh_amami.20261010", sourceId: "biodic_mammal_mesh_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:26", url: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_mammal_mesh_kanagawa.20260830", sourceId: "biodic_mammal_mesh_kanagawa", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:16:37", url: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_veg2024_amami.20261010", sourceId: "biodic_veg2024_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:13", url: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_veg2024_kanagawa.20260830", sourceId: "biodic_veg2024_kanagawa", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:16:23", url: "https://pl-moej.gisservice.jp/arcgis/apps/experiencebuilder/experience?id=8ba29c091ba04870a8c7e5265fb9fb6c", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_vegcode_legend.20260829", sourceId: "biodic_vegcode_legend", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:12:18", url: "https://www.biodic.go.jp/dload/mesh_vg.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_vegmesh_4th_kanagawa.20260829", sourceId: "biodic_vegmesh_4th_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:12:18", url: "https://www.biodic.go.jp/dload/mesh_vg.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_vegmesh_5th_kanagawa.20260829", sourceId: "biodic_vegmesh_5th_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:12:18", url: "https://www.biodic.go.jp/dload/mesh_vg.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:biodic_webgis.20260829", sourceId: "biodic_webgis", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:13:51", url: "http://gis.biodic.go.jp/webgis/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:bodik_kagoshima_ryuiki_chisui_amami.20261011", sourceId: "bodik_kagoshima_ryuiki_chisui_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T01:02:48", url: "https://data.bodik.jp/dataset/460001_1_01_ryuuikichisuipurojekuto", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:buna_suitai_web.20260829", sourceId: "buna_suitai_web", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:02:08", url: "https://www.agri-kanagawa.jp/WEB_buna/jittai_02rireki.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_bodik_kanagawa.20260830", sourceId: "ckan_bodik_kanagawa", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:31:45", url: "https://data.bodik.jp/organization/142018+142123+143839", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_env_bulk.20260829", sourceId: "ckan_env_bulk", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:32:52", url: "https://catalog.opendata.pref.kanagawa.jp", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_kanagawa_pref.20260829", sourceId: "ckan_kanagawa_pref", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:40:39", url: "https://catalog.opendata.pref.kanagawa.jp", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_pdf_choju_higai.20260829", sourceId: "ckan_pdf_choju_higai", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:01:56", url: "https://catalog.opendata.pref.kanagawa.jp/dataset/f9a64735-c8f9-420c-b008-c4eed1973fe8", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_pdf_choju_kyugo.20260829", sourceId: "ckan_pdf_choju_kyugo", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:01:56", url: "https://catalog.opendata.pref.kanagawa.jp/dataset/7aa8dba2-3ce1-4baf-a870-012ecd04a806", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_pdf_ghg_kanagawa.20260829", sourceId: "ckan_pdf_ghg_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:01:56", url: "https://catalog.opendata.pref.kanagawa.jp/dataset/38697849-5f80-4ec4-a02e-d84eb99dad49 ; https://catalog.opendata.pref.kanagawa.jp/dataset/73bcbaf9-8f49-4e67-adc0-bceb7b2ecf50 ; https://www.pref.kanagawa.jp/docs/ap4/cnt/f417509/shinontaikeikaku.html", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_pdf_shinrin_toukei.20260829", sourceId: "ckan_pdf_shinrin_toukei", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:02:22", url: "https://catalog.opendata.pref.kanagawa.jp/dataset/950a73db-1651-4bd3-8622-a3535477c1ef", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_sagamihara.20260829", sourceId: "ckan_sagamihara", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:40:39", url: "https://opendata.city.sagamihara.kanagawa.jp", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ckan_yokohama.20260830", sourceId: "ckan_yokohama", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:21:00", url: "https://data.city.yokohama.lg.jp", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:dams_kanagawa.20260829", sourceId: "dams_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:58:50", url: "https://www.pref.kanagawa.jp/docs/vh6/cnt/f8018/ ; https://www.ktr.mlit.go.jp/sagami/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:dpri_gouu2010_amami.20261011", sourceId: "dpri_gouu2010_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T12:00:39", url: "https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:eadas_kanagawa.20260829", sourceId: "eadas_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:08:21", url: "https://eadas.env.go.jp/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:env_kousui_annual_amami.20261010", sourceId: "env_kousui_annual_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:34", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:env_kousui_annual_kanagawa.20260829", sourceId: "env_kousui_annual_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:01", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/kousui/dataMap.asp", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:env_kousui_sample_amami.20261010", sourceId: "env_kousui_sample_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:51", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:env_kousui_sample_kanagawa.20260829", sourceId: "env_kousui_sample_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:32", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:env_kousui_stations_amami.20261010", sourceId: "env_kousui_stations_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:05", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:env_kousui_stations_kanagawa.20260829", sourceId: "env_kousui_stations_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:05:51", url: "https://water-pub.env.go.jp/water-pub/mizu-site/mizu/download/", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:estat_agri_census_kanagawa.20260829", sourceId: "estat_agri_census_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:29:20", url: "https://www.e-stat.go.jp/stat-search/files?page=1&layout=dataset&query=%E8%80%95%E4%BD%9C%E6%94%BE%E6%A3%84%E5%9C%B0%20%E7%A5%9E%E5%A5%88%E5%B7%9D%E7%9C%8C", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:estat_census_population_kanagawa.20260829", sourceId: "estat_census_population_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:31:49", url: "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000040454825&fileKind=0", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:estat_shozaiki_kanagawa.20260905", sourceId: "estat_shozaiki_kanagawa", editionKey: "20260905", vintage: null, fetchedAt: "2026-09-05T16:54:15", url: "https://www.e-stat.go.jp/gis/statmap-search?page=1&type=2&aggregateUnitForBoundary=A&toukeiCode=00200521&serveyId=A002005212020&prefCode=14&coordsys=1&format=shape", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:etanzawa_siryousitu.20260829", sourceId: "etanzawa_siryousitu", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:03:15", url: "https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gbif_amami_occurrences.20261010", sourceId: "gbif_amami_occurrences", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:32:29", url: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.18.4_1&gadm_gid=JPN.18.38_1&gadm_gid=JPN.18.41_1&gadm_gid=JPN.18.44_1&gadm_gid=JPN.18.34_1", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:gbif_kanagawa.20260829", sourceId: "gbif_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T17:37:13", url: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.19_1", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: "snapshot", supersededBy: "common:edition:gbif_kanagawa_occurrences.20260829" },
  { editionId: "common:edition:gbif_kanagawa_occurrences.20260829", sourceId: "gbif_kanagawa_occurrences", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T18:46:34", url: "https://www.gbif.org/occurrence/search?gadm_gid=JPN.19_1", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:gbif_species_match.20260829", sourceId: "gbif_species_match", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:10:09", url: "https://api.gbif.org/v1/species/match", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geoshape_sagami_river.20260830", sourceId: "geoshape_sagami_river", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:13", url: "https://geoshape.ex.nii.ac.jp/river/resource/830307/stream.json", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_agri_point_2021_sagami.20260829", sourceId: "geospatial_jp_agri_point_2021_sagami", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:32:50", url: "https://www.geospatial.jp/ckan/dataset/agri-point-2021-14", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_agri_poly_2021_sagami.20260829", sourceId: "geospatial_jp_agri_poly_2021_sagami", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:33:33", url: "https://www.geospatial.jp/ckan/dataset/agri-poly-2021-14", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_kanagawa_catalog.20260829", sourceId: "geospatial_jp_kanagawa_catalog", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:31:24", url: "https://www.geospatial.jp/ckan/dataset?q=神奈川", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_kokudo_landclass_kanagawa.20260829", sourceId: "geospatial_jp_kokudo_landclass_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:33:33", url: "https://www.geospatial.jp/ckan/dataset/mlit-kokudo-2", licenseId: "custom_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_kokudo_river_sagami.20260829", sourceId: "geospatial_jp_kokudo_river_sagami", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:33:33", url: "https://www.geospatial.jp/ckan/dataset/mlit-kokudo-6", licenseId: "custom_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_plateau_kanagawa.20260829", sourceId: "geospatial_jp_plateau_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:31:24", url: "https://www.geospatial.jp/ckan/dataset?q=plateau", licenseId: "plateau_site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:geospatial_jp_pointcloud_kanagawa.20260829", sourceId: "geospatial_jp_pointcloud_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:31:24", url: "https://www.geospatial.jp/ckan/dataset/kanagawa-2022-pointcloud", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsi_dem_terrain.20261010", sourceId: "gsi_dem_terrain", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:00:26", url: "https://maps.gsi.go.jp/development/demtile.html", licenseId: "gsi_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsi_elevation_grid.20260829", sourceId: "gsi_elevation_grid", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:39:04", url: "https://maps.gsi.go.jp/development/elevation_s.html", licenseId: "gsi_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsi_elevation_grid_amami.20261010", sourceId: "gsi_elevation_grid_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T12:12:14", url: "https://maps.gsi.go.jp/development/elevation_s.html", licenseId: "gsi_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsi_kiban_chizu_joho.20260829", sourceId: "gsi_kiban_chizu_joho", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:23:45", url: "https://service.gsi.go.jp/kiban/", licenseId: "gsi_terms", licenseClass: "open_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsj_geology_points.20260829", sourceId: "gsj_geology_points", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:29:58", url: "https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.json?point=<lat>,<lon>", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:gsj_seamless_legend.20260829", sourceId: "gsj_seamless_legend", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:26:05", url: "https://gbank.gsj.jp/seamless/v2/api/1.3.1/legend.csv", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:hadano_preserved_trees.20260830", sourceId: "hadano_preserved_trees", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:15:00", url: "https://www.city.hadano.kanagawa.jp/material/files/group/6/142115_preserve_tree.csv", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:hiratsuka_parks.20260830", sourceId: "hiratsuka_parks", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:15:00", url: "https://www.city.hiratsuka.kanagawa.jp/common/200204844.csv", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:hiratsuka_taiki.20260830", sourceId: "hiratsuka_taiki", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:14:32", url: "https://hiratsukataiki.sakura.ne.jp/download-kakutei.php", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:hiratsuka_taiki_stations.20260830", sourceId: "hiratsuka_taiki_stations", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:14:32", url: "https://hiratsukataiki.sakura.ne.jp/download-kakutei.php", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ikilog.20260829", sourceId: "ikilog", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:04:57", url: "https://ikilog.biodic.go.jp/", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:inaturalist_amami.20261010", sourceId: "inaturalist_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:32:40", url: "https://www.inaturalist.org/observations?place_id=34051&place_id=34081&place_id=34085&place_id=34091&place_id=34088", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:inaturalist_kanagawa.20260829", sourceId: "inaturalist_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:22:16", url: "https://www.inaturalist.org/observations?place_id=10918", licenseId: "per_item_mixed", licenseClass: "mixed", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:jma_daily_nase.20261010", sourceId: "jma_daily_nase", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:08", url: "https://www.data.jma.go.jp/stats/etrn/view/daily_s1.php?prec_no=88&block_no=47909", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:jma_daily_yokohama.20260829", sourceId: "jma_daily_yokohama", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:10:56", url: "https://www.data.jma.go.jp/stats/etrn/view/daily_s1.php?prec_no=46&block_no=47670", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:jma_monthly_amami.20261010", sourceId: "jma_monthly_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:15", url: "https://www.data.jma.go.jp/stats/etrn/index.php", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:jma_monthly_kanagawa.20260829", sourceId: "jma_monthly_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:10:54", url: "https://www.data.jma.go.jp/stats/etrn/index.php", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:jma_sst_amami.20261010", sourceId: "jma_sst_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:29:35", url: "https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan/engan_KG.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:jma_stations_amami.20261010", sourceId: "jma_stations_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:29:40", url: "https://www.jma.go.jp/bosai/amedas/const/amedastable.json", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:jma_stations_kanagawa.20260829", sourceId: "jma_stations_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:10:43", url: "https://www.jma.go.jp/bosai/amedas/const/amedastable.json", licenseId: "gov_standard_2_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_habu_amami.20261010", sourceId: "kagoshima_habu_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T23:49:22", url: "https://www.pref.kagoshima.jp/ae10/kenko-fukushi/yakuji-eisei/habu/index.html", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_irikomi_amami.20261010", sourceId: "kagoshima_irikomi_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T23:49:22", url: "https://data.bodik.jp/dataset/460001_guntou_irikomi_nyuiki", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_kasen_choui_amami.20261010", sourceId: "kagoshima_kasen_choui_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:37:44", url: "https://data.bodik.jp/dataset/460001_choui", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:kagoshima_kasen_dam_amami.20261010", sourceId: "kagoshima_kasen_dam_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:38:45", url: "https://data.bodik.jp/dataset/460001_dam", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:kagoshima_kasen_stations_amami.20261010", sourceId: "kagoshima_kasen_stations_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:35:43", url: "https://www.pref.kagoshima.jp/ah08/infra/kasen-sabo/sabo/jyouhoushisutemu.html", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_kasen_suii_amami.20261010", sourceId: "kagoshima_kasen_suii_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:37:13", url: "https://data.bodik.jp/dataset/460001_suii", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:kagoshima_kasen_suii_kiki_amami.20261010", sourceId: "kagoshima_kasen_suii_kiki_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T18:37:14", url: "https://data.bodik.jp/dataset/460001_suii", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:kagoshima_noneko_amami.20261010", sourceId: "kagoshima_noneko_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T23:49:16", url: "https://kyushu.env.go.jp/okinawa/awcc/Wild-dog-Wild-cat.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_ordinance_species.20261010", sourceId: "kagoshima_ordinance_species", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T16:41:35", url: "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/zyorei/03007006.html", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_redlist.20261010", sourceId: "kagoshima_redlist", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T16:41:29", url: "http://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/reddata/plant-list4.html", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_umigame_amami.20261010", sourceId: "kagoshima_umigame_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T23:49:16", url: "https://www.pref.kagoshima.jp/ad04/kurashi-kankyo/kankyo/yasei/umigame/umigame.html", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kagoshima_univ_gouu2010_amami.20261011", sourceId: "kagoshima_univ_gouu2010_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T12:00:39", url: "https://bousai.kagoshima-u.ac.jp/wpo/wp-content/uploads/2024/03/2010_gouu.pdf", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_dam_mizugame.20260829", sourceId: "kanagawa_dam_mizugame", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:35", url: "https://kanagawa-dam.jp/", licenseId: "all_rights_reserved", licenseClass: "restricted", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_edna.20261007", sourceId: "kanagawa_edna", editionKey: "20261007", vintage: null, fetchedAt: "2026-10-07T13:28:13", url: "https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:kanagawa_green_conservation.20260830", sourceId: "kanagawa_green_conservation", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:15:00", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f10578/index.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_ikimono_chousa.20260829", sourceId: "kanagawa_ikimono_chousa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:04:57", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1195000.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_jiban_chinka.20260830", sourceId: "kanagawa_jiban_chinka", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:16", url: "https://www.pref.kanagawa.jp/docs/pf7/cnt/f41044/p81475.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: "revision", supersededBy: null },
  { editionId: "common:edition:kanagawa_kuma_sightings.20260830", sourceId: "kanagawa_kuma_sightings", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:09:58", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f3813/index.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:kanagawa_natural_parks.20260830", sourceId: "kanagawa_natural_parks", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:14:54", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f5842/p16572.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_rdb2006_animals.20261010", sourceId: "kanagawa_rdb2006_animals", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T16:20:35", url: "https://nh.kanagawa-museum.jp/assets/icp/contents/1657590295853/simple/RedData2006_shukeikekka_ichiran.pdf", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_rdb2006_errata.20260830", sourceId: "kanagawa_rdb2006_errata", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:17", url: "https://nh.kanagawa-museum.jp/publications/other/reddata.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_rdb2022_plants.20260829", sourceId: "kanagawa_rdb2022_plants", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T16:47:25", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1197000.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_redlist.20260829", sourceId: "kanagawa_redlist", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:51:37", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1061385.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_redlist_categories.20260829", sourceId: "kanagawa_redlist_categories", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:51:37", url: "https://www.pref.kanagawa.jp/docs/t4i/cnt/f12655/p1196500.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_river_citizen_survey.20260829", sourceId: "kanagawa_river_citizen_survey", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:00:40", url: "https://www.pref.kanagawa.jp/docs/b4f/suigen/top.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kanagawa_shizenshi_bibliography.20260829", sourceId: "kanagawa_shizenshi_bibliography", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:31:23", url: "https://nh.kanagawa-museum.jp/publications/nhr/index.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:kasen_kokusei_sagami.20260829", sourceId: "kasen_kokusei_sagami", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:52:43", url: "https://www.ktr.mlit.go.jp/keihin/keihin00294.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:miyagase_storage_status.20260829", sourceId: "miyagase_storage_status", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:59:23", url: "https://www.ktr.mlit.go.jp/sagami/sagami01113.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:mlit_amami_action_plan_amami.20261011", sourceId: "mlit_amami_action_plan_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T01:02:48", url: "https://www.mlit.go.jp/common/001294716.pdf", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:mlit_river_hydro.20260829", sourceId: "mlit_river_hydro", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:35", url: "https://www1.river.go.jp/", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_amami_wh_plans_amami.20261011", sourceId: "moe_amami_wh_plans_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T01:02:48", url: "https://kyushu.env.go.jp/okinawa/amami-okinawa/plans/index.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_ias_list.20260829", sourceId: "moe_ias_list", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:52:40", url: "https://www.env.go.jp/nature/intro/2outline/iaslist.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_meisui_kanagawa.20260829", sourceId: "moe_meisui_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:09:33", url: "https://water-pub.env.go.jp/water-pub/mizu-site/meisui/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_mongoose_amami.20261011", sourceId: "moe_mongoose_amami", editionKey: "20261011", vintage: null, fetchedAt: "2026-10-11T10:54:38", url: "https://kyushu.env.go.jp/okinawa/press_00065.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_redlist.20260829", sourceId: "moe_redlist", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:54:16", url: "https://www.env.go.jp/nature/kisho/hozen/redlist/", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moe_satoyama_kanagawa.20260829", sourceId: "moe_satoyama_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:49", url: "https://www.env.go.jp/nature/satoyama/14_kanagawa/kanagawa.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_coast_shorebird.20260829", sourceId: "moni1000_coast_shorebird", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/coast.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_forest_bird.20260829", sourceId: "moni1000_forest_bird", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/forest.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_lake_aquaticplants.20260829", sourceId: "moni1000_lake_aquaticplants", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/wetlands.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_lake_benthos.20260829", sourceId: "moni1000_lake_benthos", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/wetlands.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_lake_fish.20260829", sourceId: "moni1000_lake_fish", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/wetlands.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_satochi_bird.20260829", sourceId: "moni1000_satochi_bird", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:57:28", url: "https://www.biodic.go.jp/moni1000/village.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_satochi_butterfly.20260829", sourceId: "moni1000_satochi_butterfly", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:57:28", url: "https://www.biodic.go.jp/moni1000/village.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_satochi_mammal.20260829", sourceId: "moni1000_satochi_mammal", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:57:28", url: "https://www.biodic.go.jp/moni1000/village.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_sites.20260829", sourceId: "moni1000_sites", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:51:45", url: "https://www.biodic.go.jp/moni1000/site_list.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_waterfowl.20260829", sourceId: "moni1000_waterfowl", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/wetlands.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:moni1000_wetland_vegetation.20260829", sourceId: "moni1000_wetland_vegetation", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:01:14", url: "https://www.biodic.go.jp/moni1000/wetlands.html", licenseId: "biodic_terms", licenseClass: "custom_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a03_metro_area.20260829", sourceId: "nlni_a03_metro_area", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:07:53", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A03.html", licenseId: "cc_by", licenseClass: "cc_by", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a10_natparks.20260829", sourceId: "nlni_a10_natparks", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:17", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a10_natparks_amami.20261010", sourceId: "nlni_a10_natparks_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:30", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A10-v3_1.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a15_wildlife.20260829", sourceId: "nlni_a15_wildlife", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:06:20", url: "https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a15_wildlife_amami.20261010", sourceId: "nlni_a15_wildlife_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:33", url: "https://nlftp.mlit.go.jp/ksj/jpgis/datalist/KsjTmplt-A15.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a45_forest.20260829", sourceId: "nlni_a45_forest", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:05:34", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_a45_forest_amami.20261010", sourceId: "nlni_a45_forest_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:49", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A45.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_c23_coastline.20261010", sourceId: "nlni_c23_coastline", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T01:35:14", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C23.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_2006.20260829", sourceId: "nlni_l03b_landuse_2006", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:05:31", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_2006_amami.20261010", sourceId: "nlni_l03b_landuse_2006_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T12:12:09", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_2016.20260829", sourceId: "nlni_l03b_landuse_2016", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:03:45", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_2016_amami.20261010", sourceId: "nlni_l03b_landuse_2016_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T12:11:55", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_by_watershed.2006", sourceId: "nlni_l03b_landuse_by_watershed", editionKey: "2006", vintage: "2006", fetchedAt: "2026-08-29T15:05:31", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: "revision", supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_by_watershed.2016", sourceId: "nlni_l03b_landuse_by_watershed", editionKey: "2016", vintage: "2016", fetchedAt: "2026-08-29T15:03:45", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: "revision", supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_by_watershed_amami.2006", sourceId: "nlni_l03b_landuse_by_watershed_amami", editionKey: "2006", vintage: "2006", fetchedAt: "2026-10-10T12:12:09", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: "revision", supersededBy: null },
  { editionId: "common:edition:nlni_l03b_landuse_by_watershed_amami.2016", sourceId: "nlni_l03b_landuse_by_watershed_amami", editionKey: "2016", vintage: "2016", fetchedAt: "2026-10-10T12:11:55", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: "revision", supersededBy: null },
  { editionId: "common:edition:nlni_p05_city_hall.20260829", sourceId: "nlni_p05_city_hall", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:07:53", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w05_river_nodes.20260829", sourceId: "nlni_w05_river_nodes", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:52:05", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w05_river_nodes_amami.20261010", sourceId: "nlni_w05_river_nodes_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:20", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w05_rivers.20260829", sourceId: "nlni_w05_rivers", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:52:05", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w05_rivers_amami.20261010", sourceId: "nlni_w05_rivers_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:19", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W05.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w07_watershed_mesh.20260829", sourceId: "nlni_w07_watershed_mesh", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:07:53", url: "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-W07.html", licenseId: "nlni_noncommercial", licenseClass: "noncommercial", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w12_watersheds.20260829", sourceId: "nlni_w12_watersheds", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:51:16", url: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w12_watersheds_amami.20261010", sourceId: "nlni_w12_watersheds_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:53", url: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:nlni_w12_watersheds_by_system.20260829", sourceId: "nlni_w12_watersheds_by_system", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:07:53", url: "https://nlftp.mlit.go.jp/ksj/gmlold/datalist/gmlold_KsjTmplt-W12.html", licenseId: "nlni_terms", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_amami_farmland.20261010", sourceId: "osm_amami_farmland", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:56", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_amami_forest.20261010", sourceId: "osm_amami_forest", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:31:19", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_amami_protected_area.20261010", sourceId: "osm_amami_protected_area", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:32:28", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_amami_water.20261010", sourceId: "osm_amami_water", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:35", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_kanagawa_farmland.20260829", sourceId: "osm_kanagawa_farmland", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:24:33", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_kanagawa_forest.20260829", sourceId: "osm_kanagawa_forest", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:24:32", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_kanagawa_protected_area.20260829", sourceId: "osm_kanagawa_protected_area", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:24:33", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:osm_kanagawa_water.20260829", sourceId: "osm_kanagawa_water", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:24:32", url: "https://overpass-api.de/api/interpreter", licenseId: "odbl_1_0", licenseClass: "share_alike", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:resas_api.20260829", sourceId: "resas_api", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:32:33", url: "https://opendata.resas-portal.go.jp/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:rinya_forest_stats_prefecture.20260829", sourceId: "rinya_forest_stats_prefecture", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:23:44", url: "https://www.rinya.maff.go.jp/j/keikaku/genkyou/r4/attach/xls/1-1.xlsx", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:rinya_lidar_kanagawa_status.20260829", sourceId: "rinya_lidar_kanagawa_status", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:23:45", url: "https://www.rinya.maff.go.jp/j/keikaku/smartforest/smart_forestry.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:sagami_livecams.20260829", sourceId: "sagami_livecams", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:53:29", url: "https://www.ktr.mlit.go.jp/keihin/keihin01459.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:sagami_seibi_keikaku_mirror.20260830", sourceId: "sagami_seibi_keikaku_mirror", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:18", url: "https://www.ktr.mlit.go.jp/keihin/keihin_index056.html", licenseId: "pdl_1_0", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:sagamihara_digital_archive.20260829", sourceId: "sagamihara_digital_archive", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:29:56", url: "https://digital-sagamihara.jp/digital-archive/?category=5", licenseId: "cc0_1_0", licenseClass: "public_domain", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:sagamihara_taiki_hourly.20260829", sourceId: "sagamihara_taiki_hourly", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:11:45", url: "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
  { editionId: "common:edition:sagamihara_taiki_stations.20260829", sourceId: "sagamihara_taiki_stations", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:11:40", url: "https://opendata.city.sagamihara.kanagawa.jp/dataset/taiki", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:satonavi_donkai.20260830", sourceId: "satonavi_donkai", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:18", url: "https://www.env.go.jp/nature/satoyama/satonavi/group/12.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:snet_kahaku.20260829", sourceId: "snet_kahaku", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:05:23", url: "https://science-net.kahaku.go.jp/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:soramame_hourly_amami.20261010", sourceId: "soramame_hourly_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:30:04", url: "https://soramame.env.go.jp/download", licenseId: "soramame_terms", licenseClass: "custom_terms", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:soramame_hourly_kanagawa.20260829", sourceId: "soramame_hourly_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:53:33", url: "https://soramame.env.go.jp/download", licenseId: "soramame_terms", licenseClass: "custom_terms", redistributable: true, updateMode: "snapshot", supersededBy: null },
  { editionId: "common:edition:soramame_stations_amami.20261010", sourceId: "soramame_stations_amami", editionKey: "20261010", vintage: null, fetchedAt: "2026-10-10T11:29:41", url: "https://soramame.env.go.jp/", licenseId: "soramame_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:soramame_stations_kanagawa.20260829", sourceId: "soramame_stations_kanagawa", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:53:16", url: "https://soramame.env.go.jp/", licenseId: "soramame_terms", licenseClass: "custom_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:tanzawa_shika_suigen_docs.20260829", sourceId: "tanzawa_shika_suigen_docs", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:02:51", url: "https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:tanzawa_species_list_1997.20260829", sourceId: "tanzawa_species_list_1997", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T15:09:41", url: "https://www.kanagawa-park.or.jp/tanzawavc/ikimono1.html", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:tanzawa_visitor_centers.20260830", sourceId: "tanzawa_visitor_centers", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:23:18", url: "https://www.pref.kanagawa.jp/docs/f4y/02yama/visitor.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:water_source_docs.20260905", sourceId: "water_source_docs", editionKey: "20260905", vintage: null, fetchedAt: "2026-09-05T23:32:36", url: "https://www.kwsa.or.jp/ ほか", licenseId: "site_policy", licenseClass: "open_terms", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:water_trace_kawasaki.20260905", sourceId: "water_trace_kawasaki", editionKey: "20260905", vintage: null, fetchedAt: "2026-09-05T22:55:46", url: "https://www.city.kawasaki.jp/800/page/0000083603.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:water_trace_yokohama.20260905", sourceId: "water_trace_yokohama", editionKey: "20260905", vintage: null, fetchedAt: "2026-09-05T19:01:57", url: "https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/suishitsu/suidosui/suishitsu-keikaku.html", licenseId: "site_policy", licenseClass: "open_terms", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:ylist.20260829", sourceId: "ylist", editionKey: "20260829", vintage: null, fetchedAt: "2026-08-29T14:54:42", url: "http://ylist.info/", licenseId: "terms_unconfirmed", licenseClass: "unconfirmed", redistributable: false, updateMode: null, supersededBy: null },
  { editionId: "common:edition:yokohama_bio_indicator.20260830", sourceId: "yokohama_bio_indicator", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:30:16", url: "https://www.city.yokohama.lg.jp/kurashi/machizukuri-kankyo/kankyohozen/emp/shiryou.html", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: null, supersededBy: null },
  { editionId: "common:edition:yokohama_river_waterlevel.20260830", sourceId: "yokohama_river_waterlevel", editionKey: "20260830", vintage: null, fetchedAt: "2026-08-30T16:30:14", url: "https://www.city.yokohama.lg.jp/kurashi/machizukuri-kankyo/kasen-gesuido/kasen/suibou/opendata.html", licenseId: "cc_by", licenseClass: "cc_by", redistributable: true, updateMode: "append", supersededBy: null },
];

/** 出現データ（occurrence_agg）の出典。マニフェスト（target=occurrence）由来。画面用 API・MCP の provenance/freshness が使う。 */
export const OCCURRENCE_SOURCE_IDS: readonly string[] = ["gbif_amami_occurrences","gbif_kanagawa_occurrences","inaturalist_amami","inaturalist_kanagawa","kanagawa_edna","kanagawa_kuma_sightings"];

/** 出典ごとの状態（registry/source/access.yaml と manifests/ から r01 が作る。MCP_SOURCE_ACCESS.md §1）。 */
export interface GeneratedSourceAccess {
  state: "queryable" | "not_queryable";
  /** 取れるツール名（get_observations / get_occurrences / get_edna / get_records / find_datasets）。取れないなら空。 */
  queryableVia: string[];
  /** get_records で引ける record_set（記録の集合名。空なら get_records の対象外）。 */
  tables: string[];
  /** record_set → その出典の行数（get_records の n_total。原本の表の行数で、出典で絞った数）。 */
  recordSetRows: Record<string, number>;
  /** 原本の行数（キューブの集計行数ではない）。取れない出典は null。 */
  nSourceRows: number | null;
  nSourceRowsBasis: "source_rows" | "registry_record_count" | "catalog_datasets" | "none";
  /** 件数を数えた原本の最新取得日時（決定論のため実行時刻ではない）。 */
  countedAt: string | null;
  /** 取れない理由コード（queryableVia が空のとき必須）。 */
  reason: string | null;
  reasonJa: string | null;
  reasonNote: string | null;
}

/** 合成データの出典を除く全出典（SOURCE_META と同じキー）。 */
export const SOURCE_ACCESS: Readonly<Record<string, GeneratedSourceAccess>> = {
  "amami_biodiversity_strategy_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "amami_tourism_plans_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "atsugi_river_water_quality": {
    "state": "queryable",
    "queryableVia": [
      "get_observations",
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 4
    },
    "nSourceRows": 4560,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "ayu_upstream_migration": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "biodic_6th_kanagawa_report": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "biodic_animal_distribution": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "biodic_kiban_datalist": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "map_service",
    "reasonJa": "地図サービス（WebGIS）。値は外部サービス側にある",
    "reasonNote": null
  },
  "biodic_mammal_mesh_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "biodic_mammal_mesh_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "mammal_mesh"
    ],
    "recordSetRows": {
      "mammal_mesh": 75240
    },
    "nSourceRows": 75240,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "biodic_veg2024_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "vegetation"
    ],
    "recordSetRows": {
      "vegetation": 9979
    },
    "nSourceRows": 9979,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "biodic_veg2024_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "vegetation"
    ],
    "recordSetRows": {
      "vegetation": 13206
    },
    "nSourceRows": 13206,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "biodic_vegcode_legend": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "biodic_vegmesh_4th_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "biodic_vegmesh_5th_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "biodic_webgis": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "map_service",
    "reasonJa": "地図サービス（WebGIS）。値は外部サービス側にある",
    "reasonNote": null
  },
  "bodik_kagoshima_ryuiki_chisui_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "buna_suitai_web": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_collected",
    "reasonJa": "未収集（取得手段が未着手、または登録のみ）",
    "reasonNote": null
  },
  "ckan_bodik_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 680,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "ckan_env_bulk": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "ckan_kanagawa_pref": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 811,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "ckan_pdf_choju_higai": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "ckan_pdf_choju_kyugo": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "ckan_pdf_ghg_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "ckan_pdf_shinrin_toukei": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "ckan_sagamihara": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 114,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "ckan_yokohama": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 654,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "dams_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 4
    },
    "nSourceRows": 4,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "dpri_gouu2010_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "eadas_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "env_kousui_annual_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 2521,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "env_kousui_annual_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 98328,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "env_kousui_sample_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 1380,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "env_kousui_sample_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 214725,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "env_kousui_stations_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 25
    },
    "nSourceRows": 25,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "env_kousui_stations_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 290
    },
    "nSourceRows": 290,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "estat_agri_census_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 5,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "estat_census_population_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 1,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "estat_shozaiki_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "find_datasets"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 1,
    "nSourceRowsBasis": "catalog_datasets",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "etanzawa_siryousitu": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "gbif_amami_occurrences": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 47874,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "gbif_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "superseded",
    "reasonJa": "別の出典に置き換わった（superseded_by 参照）",
    "reasonNote": "gbif_kanagawa_occurrences に置き換わった。値はそちらで取る"
  },
  "gbif_kanagawa_occurrences": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 658360,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "gbif_species_match": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "geoshape_sagami_river": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "river_segments"
    ],
    "recordSetRows": {
      "river_segments": 1547
    },
    "nSourceRows": 1547,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "geospatial_jp_agri_point_2021_sagami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "geospatial_jp_agri_poly_2021_sagami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_collected",
    "reasonJa": "未収集（取得手段が未着手、または登録のみ）",
    "reasonNote": null
  },
  "geospatial_jp_kanagawa_catalog": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "catalog_only",
    "reasonJa": "データ目録（メタデータ）で、観測値・記録そのものではない",
    "reasonNote": null
  },
  "geospatial_jp_kokudo_landclass_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "geospatial_jp_kokudo_river_sagami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "geospatial_jp_plateau_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "catalog_only",
    "reasonJa": "データ目録（メタデータ）で、観測値・記録そのものではない",
    "reasonNote": null
  },
  "geospatial_jp_pointcloud_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "catalog_only",
    "reasonJa": "データ目録（メタデータ）で、観測値・記録そのものではない",
    "reasonNote": null
  },
  "gsi_dem_terrain": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "gsi_elevation_grid": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "gsi_elevation_grid_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "gsi_kiban_chizu_joho": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "gsj_geology_points": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "gsj_seamless_legend": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "hadano_preserved_trees": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "protected_areas"
    ],
    "recordSetRows": {
      "protected_areas": 30
    },
    "nSourceRows": 30,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "hiratsuka_parks": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "protected_areas"
    ],
    "recordSetRows": {
      "protected_areas": 290
    },
    "nSourceRows": 290,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "hiratsuka_taiki": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 245513,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "hiratsuka_taiki_stations": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 5
    },
    "nSourceRows": 5,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "ikilog": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "inaturalist_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 13539,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "inaturalist_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 165332,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_daily_nase": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 20496,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_daily_yokohama": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 19420,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_monthly_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 6277,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_monthly_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 13821,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_sst_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 65412,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_stations_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 3
    },
    "nSourceRows": 3,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "jma_stations_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 12
    },
    "nSourceRows": 12,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_habu_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "kagoshima_irikomi_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "kagoshima_kasen_choui_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 20508,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_kasen_dam_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 57591,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_kasen_stations_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 12
    },
    "nSourceRows": 12,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_kasen_suii_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 69120,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_kasen_suii_kiki_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 11832,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_noneko_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "kagoshima_ordinance_species": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "assessments"
    ],
    "recordSetRows": {
      "assessments": 59
    },
    "nSourceRows": 59,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_redlist": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "assessments"
    ],
    "recordSetRows": {
      "assessments": 2810
    },
    "nSourceRows": 2810,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kagoshima_umigame_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "kagoshima_univ_gouu2010_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "kanagawa_dam_mizugame": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "external_api",
    "reasonJa": "外部 API・CGI・現況ページ。値は提供元に問い合わせる",
    "reasonNote": "動的 JSON の現況。蓄積した履歴が無い"
  },
  "kanagawa_edna": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences",
      "get_edna"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 134443,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_green_conservation": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "protected_areas"
    ],
    "recordSetRows": {
      "protected_areas": 379
    },
    "nSourceRows": 379,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_ikimono_chousa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "kanagawa_jiban_chinka": {
    "state": "queryable",
    "queryableVia": [
      "get_observations",
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 74
    },
    "nSourceRows": 3286,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_kuma_sightings": {
    "state": "queryable",
    "queryableVia": [
      "get_occurrences",
      "get_records"
    ],
    "tables": [
      "sightings"
    ],
    "recordSetRows": {
      "sightings": 400
    },
    "nSourceRows": 400,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_natural_parks": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "protected_areas"
    ],
    "recordSetRows": {
      "protected_areas": 29
    },
    "nSourceRows": 29,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_rdb2006_animals": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_in_d1",
    "reasonJa": "原本には行があるが、D1 にその表が無い（本番では引けない）",
    "reasonNote": null
  },
  "kanagawa_rdb2006_errata": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "kanagawa_rdb2022_plants": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "assessments"
    ],
    "recordSetRows": {
      "assessments": 1033
    },
    "nSourceRows": 1033,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_redlist": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "assessments"
    ],
    "recordSetRows": {
      "assessments": 1851
    },
    "nSourceRows": 1851,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "kanagawa_redlist_categories": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "kanagawa_river_citizen_survey": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_in_d1",
    "reasonJa": "原本には行があるが、D1 にその表が無い（本番では引けない）",
    "reasonNote": null
  },
  "kanagawa_shizenshi_bibliography": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "kasen_kokusei_sagami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "miyagase_storage_status": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "external_api",
    "reasonJa": "外部 API・CGI・現況ページ。値は提供元に問い合わせる",
    "reasonNote": "現況のスナップショット（更新のたびに内容が上書きされる）"
  },
  "mlit_amami_action_plan_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "mlit_river_hydro": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "external_api",
    "reasonJa": "外部 API・CGI・現況ページ。値は提供元に問い合わせる",
    "reasonNote": null
  },
  "moe_amami_wh_plans_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "moe_ias_list": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "assessments"
    ],
    "recordSetRows": {
      "assessments": 429
    },
    "nSourceRows": 429,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "moe_meisui_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moe_mongoose_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "document_cells",
    "reasonJa": "行政文書の表として cells に入れてある（出典の列は無い）。/documents・run_sql・get_records の record_set=documents で読む",
    "reasonNote": null
  },
  "moe_redlist": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_in_d1",
    "reasonJa": "原本には行があるが、D1 にその表が無い（本番では引けない）",
    "reasonNote": null
  },
  "moe_satoyama_kanagawa": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_coast_shorebird": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_forest_bird": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_lake_aquaticplants": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "moni1000_lake_benthos": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "moni1000_lake_fish": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "moni1000_satochi_bird": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_satochi_butterfly": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_satochi_mammal": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "moni1000_sites": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 30
    },
    "nSourceRows": 30,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "moni1000_waterfowl": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "moni1000_wetland_vegetation": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "nlni_a03_metro_area": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_collected",
    "reasonJa": "未収集（取得手段が未着手、または登録のみ）",
    "reasonNote": null
  },
  "nlni_a10_natparks": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": "data/processed に 4 ファイル。D1 の表は無い"
  },
  "nlni_a10_natparks_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_a15_wildlife": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_a15_wildlife_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_a45_forest": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_a45_forest_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_c23_coastline": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_l03b_landuse_2006": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_l03b_landuse_2006_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_l03b_landuse_2016": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_l03b_landuse_2016_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_l03b_landuse_by_watershed": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 4858,
    "nSourceRowsBasis": "registry_record_count",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "nlni_l03b_landuse_by_watershed_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 283,
    "nSourceRowsBasis": "registry_record_count",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "nlni_p05_city_hall": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_collected",
    "reasonJa": "未収集（取得手段が未着手、または登録のみ）",
    "reasonNote": null
  },
  "nlni_w05_river_nodes": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w05_river_nodes_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w05_rivers": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w05_rivers_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w07_watershed_mesh": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "not_collected",
    "reasonJa": "未収集（取得手段が未着手、または登録のみ）",
    "reasonNote": null
  },
  "nlni_w12_watersheds": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w12_watersheds_amami": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "nlni_w12_watersheds_by_system": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_amami_farmland": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_amami_forest": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_amami_protected_area": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_amami_water": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_kanagawa_farmland": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_kanagawa_forest": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_kanagawa_protected_area": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "osm_kanagawa_water": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "resas_api": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "rinya_forest_stats_prefecture": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "rinya_lidar_kanagawa_status": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "sagami_livecams": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 16
    },
    "nSourceRows": 16,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "sagami_seibi_keikaku_mirror": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "sagamihara_digital_archive": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "sagamihara_taiki_hourly": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 175344,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "sagamihara_taiki_stations": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 2
    },
    "nSourceRows": 2,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "satonavi_donkai": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "snet_kahaku": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "blocked_access",
    "reasonJa": "ログイン・APIキー・利用アンケート・JS 画面などで、自動取得できていない",
    "reasonNote": null
  },
  "soramame_hourly_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 17697,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "soramame_hourly_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_observations"
    ],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": 168793,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "soramame_stations_amami": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 1
    },
    "nSourceRows": 1,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "soramame_stations_kanagawa": {
    "state": "queryable",
    "queryableVia": [
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 4
    },
    "nSourceRows": 4,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  },
  "tanzawa_shika_suigen_docs": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "pdf_document",
    "reasonJa": "PDF の文書のまま。表として取り出していない",
    "reasonNote": null
  },
  "tanzawa_species_list_1997": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "tanzawa_visitor_centers": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "water_source_docs": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "d1_no_source_column",
    "reasonJa": "D1 の表に出典の列が無く、表の行をどの出典のものか機械的に引けない",
    "reasonNote": null
  },
  "water_trace_kawasaki": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "d1_no_source_column",
    "reasonJa": "D1 の表に出典の列が無く、表の行をどの出典のものか機械的に引けない",
    "reasonNote": null
  },
  "water_trace_yokohama": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "d1_no_source_column",
    "reasonJa": "D1 の表に出典の列が無く、表の行をどの出典のものか機械的に引けない",
    "reasonNote": null
  },
  "ylist": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "license",
    "reasonJa": "利用条件が不明のため取得していない",
    "reasonNote": null
  },
  "yokohama_bio_indicator": {
    "state": "not_queryable",
    "queryableVia": [],
    "tables": [],
    "recordSetRows": {},
    "nSourceRows": null,
    "nSourceRowsBasis": "none",
    "countedAt": null,
    "reason": "file_only",
    "reasonJa": "収集済みだが D1 に投入していない（data/processed のファイルのみ）",
    "reasonNote": null
  },
  "yokohama_river_waterlevel": {
    "state": "queryable",
    "queryableVia": [
      "get_observations",
      "get_records"
    ],
    "tables": [
      "sites"
    ],
    "recordSetRows": {
      "sites": 54
    },
    "nSourceRows": 75528,
    "nSourceRowsBasis": "source_rows",
    "countedAt": "2026-10-11T12:00:39",
    "reason": null,
    "reasonJa": null,
    "reasonNote": null
  }
};

/** 観測データ（measurements・sensor_timeseries・土地利用）の出典。マニフェスト（target=observation）由来。get_observations で取れる。 */
export const OBSERVATION_SOURCE_IDS: readonly string[] = ["atsugi_river_water_quality","env_kousui_annual_amami","env_kousui_annual_kanagawa","env_kousui_sample_amami","env_kousui_sample_kanagawa","hiratsuka_taiki","jma_daily_nase","jma_daily_yokohama","jma_monthly_amami","jma_monthly_kanagawa","jma_sst_amami","kagoshima_kasen_choui_amami","kagoshima_kasen_dam_amami","kagoshima_kasen_suii_amami","kagoshima_kasen_suii_kiki_amami","kanagawa_jiban_chinka","nlni_l03b_landuse_by_watershed","nlni_l03b_landuse_by_watershed_amami","sagamihara_taiki_hourly","soramame_hourly_amami","soramame_hourly_kanagawa","yokohama_river_waterlevel"];

/** get_records の record_set → D1 の表（registry/source/access.yaml の record_sets。この対応の正はそこ 1 か所）。 */
export const RECORD_SET_TABLES: Readonly<Record<string, string>> = {
  "sites": "place",
  "protected_areas": "protected_areas",
  "vegetation": "vegetation_polygons",
  "river_segments": "river_segments",
  "mammal_mesh": "mammal_mesh",
  "sightings": "wildlife_sightings",
  "assessments": "taxon_assessment"
};

/** 一覧から除いた出典の件数と理由（合成データ。出典メタの読み出し口に合成の出典を出さない既存の保証）。 */
export const SOURCE_EXCLUDED_FROM_LIST: Readonly<Record<string, number>> = {"synthetic":1};

/** get_records で引ける出典（SOURCE_ACCESS の tables が空でないもの）。 */
export const RECORD_SOURCE_IDS: readonly string[] = ["atsugi_river_water_quality","biodic_mammal_mesh_kanagawa","biodic_veg2024_amami","biodic_veg2024_kanagawa","dams_kanagawa","env_kousui_stations_amami","env_kousui_stations_kanagawa","geoshape_sagami_river","hadano_preserved_trees","hiratsuka_parks","hiratsuka_taiki_stations","jma_stations_amami","jma_stations_kanagawa","kagoshima_kasen_stations_amami","kagoshima_ordinance_species","kagoshima_redlist","kanagawa_green_conservation","kanagawa_jiban_chinka","kanagawa_kuma_sightings","kanagawa_natural_parks","kanagawa_rdb2022_plants","kanagawa_redlist","moe_ias_list","moni1000_sites","sagami_livecams","sagamihara_taiki_stations","soramame_stations_amami","soramame_stations_kanagawa","yokohama_river_waterlevel"];

/** find_datasets で引ける出典（外部ポータルの目録。registry/source/access.yaml の catalog を宣言した出典。MCP_EXTERNAL_CATALOG.md §5）。 */
export const FIND_DATASET_SOURCE_IDS: readonly string[] = ["ckan_bodik_kanagawa","ckan_kanagawa_pref","ckan_sagamihara","ckan_yokohama","estat_agri_census_kanagawa","estat_census_population_kanagawa","estat_shozaiki_kanagawa"];

export const LICENSES: readonly GeneratedLicense[] = [
  { licenseId: "all_rights_reserved", nameJa: "無断複製・転用不可", spdxOrUrl: null, licenseClass: "restricted", attributionText: null },
  { licenseId: "biodic_terms", nameJa: "環境省生物多様性センターウェブサイト利用規約", spdxOrUrl: "https://www.biodic.go.jp/", licenseClass: "custom_terms", attributionText: "出典を明示する" },
  { licenseId: "cc0_1_0", nameJa: "CC0 1.0 全世界パブリック・ドメイン提供", spdxOrUrl: "https://creativecommons.org/publicdomain/zero/1.0/", licenseClass: "public_domain", attributionText: null },
  { licenseId: "cc_by", nameJa: "クリエイティブ・コモンズ 表示（CC BY）", spdxOrUrl: "https://creativecommons.org/licenses/by/4.0/", licenseClass: "cc_by", attributionText: "出典（提供元・データセット名）を表示する" },
  { licenseId: "custom_terms", nameJa: "出典独自の利用規約（ol）", spdxOrUrl: null, licenseClass: "custom_terms", attributionText: null },
  { licenseId: "gov_standard_2_0", nameJa: "政府標準利用規約（第2.0版）", spdxOrUrl: "https://www.digital.go.jp/resources/open_data/", licenseClass: "open_terms", attributionText: "出典を記載する" },
  { licenseId: "gsi_terms", nameJa: "国土地理院コンテンツ利用規約", spdxOrUrl: "https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html", licenseClass: "open_terms", attributionText: "出典を表記する" },
  { licenseId: "nlni_noncommercial", nameJa: "国土数値情報利用約款（非商用）", spdxOrUrl: "https://nlftp.mlit.go.jp/ksj/other/agreement.html", licenseClass: "noncommercial", attributionText: "出典（国土数値情報）を明示する" },
  { licenseId: "nlni_terms", nameJa: "国土数値情報利用約款（商用可・オープンデータ）", spdxOrUrl: "https://nlftp.mlit.go.jp/ksj/other/agreement.html", licenseClass: "open_terms", attributionText: "出典（国土数値情報）を明示する" },
  { licenseId: "odbl_1_0", nameJa: "Open Database License 1.0（ODbL）", spdxOrUrl: "https://opendatacommons.org/licenses/odbl/1-0/", licenseClass: "share_alike", attributionText: "© OpenStreetMap contributors" },
  { licenseId: "pdl_1_0", nameJa: "公共データ利用規約（第1.0版、PDL1.0）", spdxOrUrl: "https://www.kantei.go.jp/jp/singi/it2/densi/pdf/opendata_ver1.0.pdf", licenseClass: "open_terms", attributionText: "出典を記載する（改変時は改変した旨も明記）" },
  { licenseId: "per_item_mixed", nameJa: "データセット（または観察）ごとに個別", spdxOrUrl: null, licenseClass: "mixed", attributionText: null },
  { licenseId: "plateau_site_policy", nameJa: "PLATEAU Site Policy（著作権について）", spdxOrUrl: null, licenseClass: "open_terms", attributionText: null },
  { licenseId: "site_policy", nameJa: "自治体・機関ウェブサイトの利用規約（出典明示で利用可）", spdxOrUrl: null, licenseClass: "open_terms", attributionText: "出典を明記する" },
  { licenseId: "soramame_terms", nameJa: "環境省 そらまめ君 利用規約", spdxOrUrl: "https://soramame.env.go.jp/policy", licenseClass: "custom_terms", attributionText: "出典を明示する" },
  { licenseId: "terms_unconfirmed", nameJa: "利用条件が未確認（要確認・明示なし）", spdxOrUrl: null, licenseClass: "unconfirmed", attributionText: null },
  { licenseId: "unknown", nameJa: "ライセンス未分類（写像漏れ）", spdxOrUrl: null, licenseClass: "unknown", attributionText: null },
];
