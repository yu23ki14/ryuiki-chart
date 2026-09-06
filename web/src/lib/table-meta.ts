/** テーブル / 出自の日本語説明。データ探索画面の道案内に使う。 */

/**
 * 全 56 テーブルは 1 つの D1 データベースに入っている。
 * 一覧の見出しに使う「どの原本から来たか」は SQLite のスキーマではなくこの表が持つ。
 */
export const SCHEMA_META: Record<string, { label: string; file: string; note: string }> = {
  main: {
    label: "流域DB",
    file: "ryuiki.sqlite 由来",
    note: "観測地点・イベント・測定値・生物レコードなど、アプリのデータモデル本体（DwC Event Core + eMoF 同型）",
  },
  c: {
    label: "行政文書DB",
    file: "cells.sqlite 由来",
    note: "PDF等の行政文書から抽出した表のセル単位データ。出典ページ・座標つき",
  },
  d: {
    label: "集計DB",
    file: "derived.sqlite 由来",
    note: "本デモが原本から生成した事前集計テーブル（描画高速化用・再生成可能）",
  },
};

/** テーブル名 -> SCHEMA_META のキー。D1 に統合したので接頭辞からは分からない。 */
export const TABLE_ORIGIN: Record<string, string> = {
  // ryuiki.sqlite 由来
  decisions: "main", event_observers: "main", events: "main", instruments: "main",
  interventions: "main", measurements: "main", observers: "main", organism_records: "main",
  protocols: "main", quality_transitions: "main", redlist_assessments: "main",
  sensor_timeseries: "main", sites: "main", source_registry: "main", taxa: "main",
  // Tier 1 追加ソース（docs/UNDATAFIED_TIERS.md）。原本は ryuiki.sqlite。
  protected_areas: "main", vegetation_polygons: "main", mammal_mesh: "main",
  wildlife_sightings: "main", river_segments: "main",
  // 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）。原本は data/water/*.csv → ryuiki.sqlite
  water_utility: "main", water_source: "main", water_facility: "main",
  water_source_doc: "main", water_flow_edge: "main", water_zone: "main",
  water_zone_assignment: "main", water_zone_source_share: "main",
  // cells.sqlite 由来
  cells: "c", documents: "c", extraction_log: "c", notes: "c",
  vocab_areas: "c", vocab_eras: "c", vocab_indicators: "c", vocab_units: "c",
  // derived.sqlite 由来
  doc_series: "d", doc_series_meta: "d", effort_year: "d", ias_species: "d",
  landuse_change: "d", landuse_watershed: "d", meas_clim: "d", meas_daily: "d",
  meas_month: "d", meas_year: "d", mesh_all: "d", mesh_species: "d", mesh_year: "d",
  org_group_year: "d", org_norm: "d", org_watershed: "d", org_watershed_year: "d",
  quality_monthly: "d", rain_daily: "d", redlist_change: "d", redlist_map: "d",
  sensor_daily: "d", sensor_hour_month: "d", site_var: "d", species2: "d",
  species_mesh_year: "d", species_month: "d", species_year2: "d", var_catalog: "d",
  watershed_meta: "d", watershed_rollup: "d", zone_clim: "d", zone_year: "d",
};

export const TABLE_META: Record<string, string> = {
  sites: "観測地点。ゾーン(Ridge to Reef 1-5)・座標・標高・市区町村・運用主体",
  events: "観測イベント（いつ・どこで・どのプロトコルで）。測定値と生物レコードの親",
  event_observers: "イベントと測定者の対応（測定者／立会者）",
  measurements: "測定値。水質項目を中心とした eMoF 相当のレコード",
  organism_records: "生物観察レコード。GBIF / iNaturalist 由来を含む Darwin Core 相当",
  sensor_timeseries: "センサー時系列（時別・日別）。OGC SensorThings の Observation 相当",
  taxa: "分類群マスタ。GBIF taxonKey・レッドリスト・外来種区分を保持",
  redlist_assessments: "レッドリストの版ごとの評価。版間のカテゴリー比較に使う",
  protocols: "測定プロトコル（手順の版）",
  instruments: "測定機器と校正記録",
  observers: "測定者（役割: 初級／訓練済／専門）",
  interventions: "介入記録（石積み・復田・駆除など）",
  decisions: "意思決定記録。会議で何が提示され何が決まったか",
  quality_transitions: "品質段階の遷移履歴（暫定→検証済→公開済）",
  source_registry: "出典レジストリ。取得元・ライセンス・再配布可否",
  documents: "抽出元の行政文書（PDF）",
  cells: "行政文書の表のセル。行キー・列キー・年度・出典ページつき",
  notes: "表に付随する注記。時系列比較を阻害する注記のフラグを含む",
  vocab_areas: "文書中に現れる地域名とその定義",
  vocab_indicators: "文書中に現れる指標名と単位・測定法",
  vocab_units: "文書中に現れる単位表記",
  vocab_eras: "文書中に現れる年号表記",
  extraction_log: "抽出処理のログ",
  protected_areas:
    "保護区・緑地・保存樹木の指定台帳。自然公園／特別緑地保全地区／近郊緑地保全区域／" +
    "歴史的風土保存地区／風致地区／都市公園／保存樹木を category_code で束ねている",
  vegetation_polygons:
    "現存植生図2024（環境省 いきもの地図）の神奈川県相当範囲。凡例・植生自然度つき。" +
    "形状は表示用に簡略化してあり、面積は緯度経度からの近似",
  mammal_mesh:
    "中大型哺乳類（タヌキ／キツネ／アナグマ）の3次メッシュ分布。1メッシュ×1調査年次=1行。" +
    "元の列名は survey_label に残してある",
  wildlife_sightings:
    "ツキノワグマの出没・目撃記録。頭数・状況（目撃／痕跡／捕殺）・区分（人里／山中）つき。" +
    "原本に座標が無いため lat/lon は空",
  river_segments:
    "相模川水系の河川流路。水系単位のため、県単位の nlni_w05 由来データに無い" +
    "山梨県側（桂川上流部）を含む",
  water_utility: "水道事業体。bulk（用水供給＝卸）と retail（末端給水）",
  water_source: "水道の水源（河川・ダム・地下水・湧水）。parent_id でダム→河川・支流→本流を辿れる",
  water_facility: "取水堰・浄水場・配水池。水源から蛇口までの経路のノード",
  water_source_doc: "水源マップの根拠資料。これが無い行はビルドで落とす",
  water_flow_edge:
    "流れの辺。「この施設に入る水のうち何割がこの上流ノード由来か」。" +
    "basis が nominal のものは施設能力比からの概算",
  water_zone: "町丁目（2020年国勢調査 小地域）。水源の割付単位。ポリゴンは静的アセット側",
  water_zone_assignment: "町丁目 → 給水元の浄水場・配水池の割付。混在する町丁目は share が 1.0 未満",
  water_zone_source_share:
    "派生。町丁目ごとの水源別ブレンド比率。zone_assignment から flow_edge を" +
    "上流へ再帰的に辿って合成したもの",
};

export const SAMPLE_QUERIES: { title: string; note: string; sql: string }[] = [
  {
    title: "地点一覧（ゾーン付き）",
    note: "Ridge to Reef のゾーン別に観測地点を見る",
    sql: `SELECT site_id, name, zone, elevation_m, municipality, operator, lat, lon
FROM sites
WHERE lat IS NOT NULL
ORDER BY zone, elevation_m DESC
LIMIT 200`,
  },
  {
    title: "測定項目の一覧と期間",
    note: "どの水質項目が何年分あるかを一望する",
    sql: `SELECT variable, unit, count(*) AS n,
       count(DISTINCT site_id) AS sites,
       min(substr(measured_on,1,4)) AS y_from,
       max(substr(measured_on,1,4)) AS y_to
FROM measurements
GROUP BY variable, unit
ORDER BY n DESC`,
  },
  {
    title: "地点×年 の水質平均（BOD）",
    note: "時系列比較の元になる形。variable を変えれば他項目も同じ",
    sql: `SELECT m.site_id, s.name, substr(m.measured_on,1,4) AS year,
       round(avg(m.value),3) AS avg_value, count(*) AS n
FROM measurements m JOIN sites s USING (site_id)
WHERE m.variable LIKE '%BOD%' AND m.value IS NOT NULL
GROUP BY 1,2,3
HAVING n >= 4
ORDER BY s.name, year
LIMIT 500`,
  },
  {
    title: "生物レコードの年次推移（分類群別）",
    note: "観察努力の増加も一緒に写ることに注意",
    sql: `SELECT substr(observed_on,1,4) AS year, kingdom, count(*) AS n
FROM organism_records
WHERE observed_on >= '2000' AND kingdom IS NOT NULL AND kingdom <> ''
GROUP BY 1,2
ORDER BY 1 DESC, 3 DESC`,
  },
  {
    title: "外来種の年次推移",
    note: "is_alien=1 のレコードを種別に数える",
    sql: `SELECT vernacular_name, scientific_name,
       count(*) AS n,
       min(substr(observed_on,1,4)) AS first_year,
       max(substr(observed_on,1,4)) AS last_year
FROM organism_records
WHERE is_alien = 1
GROUP BY 1,2
ORDER BY n DESC
LIMIT 100`,
  },
  {
    title: "レッドリストの版間比較",
    note: "同じ和名が複数の版に登場するものを並べる",
    sql: `SELECT vernacular_name_ja, taxon_group_ja,
       group_concat(list_year || ':' || COALESCE(category_ja, category_code, '-'), '  →  ') AS history,
       count(*) AS versions
FROM redlist_assessments
WHERE vernacular_name_ja IS NOT NULL
GROUP BY 1,2
HAVING versions > 1
ORDER BY versions DESC, vernacular_name_ja
LIMIT 200`,
  },
  {
    title: "センサー時系列（降雨と光化学オキシダント）",
    note: "10年・時別のデータ。日別に丸めて返す",
    sql: `SELECT substr(phenomenon_time,1,10) AS day, datastream,
       round(sum(result),2) AS daily_sum, count(*) AS n
FROM sensor_timeseries
WHERE datastream = 'RAIN' AND phenomenon_time >= '2024-01'
GROUP BY 1,2
ORDER BY 1 DESC
LIMIT 300`,
  },
  {
    title: "行政文書から抽出した指標",
    note: "行政文書のセル。同じ指標が複数年度にあるものを探す",
    sql: `SELECT row_key, col_key, count(DISTINCT fiscal_year) AS years,
       min(fiscal_year) AS y_from, max(fiscal_year) AS y_to, count(*) AS n
FROM cells
WHERE fiscal_year IS NOT NULL AND value_type = 'number'
GROUP BY 1,2
HAVING years >= 3
ORDER BY years DESC, n DESC
LIMIT 200`,
  },
  {
    title: "出典レジストリ（ライセンス別）",
    note: "再配布可否まで含めて確認する",
    sql: `SELECT category, license, redistributable, count(*) AS n,
       sum(record_count) AS records
FROM source_registry
GROUP BY 1,2,3
ORDER BY n DESC`,
  },
];
