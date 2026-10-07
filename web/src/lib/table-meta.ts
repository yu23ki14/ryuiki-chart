/** テーブル / 出自の日本語説明。データ探索画面の道案内に使う。 */

/**
 * カタログ表は 1 つの D1 データベースに入っている。
 * 一覧の見出しに使う「どの原本から来たか」は SQLite のスキーマではなくこの表が持つ。
 */
export const SCHEMA_META: Record<string, { label: string; file: string; note: string }> = {
  main: {
    label: "流域DB",
    file: "ryuiki.sqlite 由来",
    note: "観測地点・出典レジストリ・自然環境の台帳（保護区・植生・哺乳類・出没記録・河川流路）・水道水の水源マップ",
  },
  c: {
    label: "行政文書DB",
    file: "cells.sqlite 由来",
    note: "PDF等の行政文書から抽出した表のセル単位データ。出典ページ・座標つき",
  },
  v2: {
    label: "観測キューブDB",
    file: "v2.sqlite 由来",
    note:
      "観測キューブ（Issue #48）と、その事前集計（summary_*）。" +
      "value_zero（定量下限未満を0とみなす）と value_lod（定量下限値とみなす）の両方を持つ。" +
      "画面・意図ツールは summary_variable_catalog/summary_place_variable などの事前集計経由で読む",
  },
  reg: {
    label: "語彙レジストリDB",
    file: "registry.sqlite 由来",
    note: "指標・単位・場所・分類群・注記の正準の語彙（registry/ 配下のファイルから生成）。観測キューブの variable_id・place_id・taxon_id の引き先",
  },
};

/** テーブル名 -> SCHEMA_META のキー。D1 に統合したので接頭辞からは分からない。 */
export const TABLE_ORIGIN: Record<string, string> = {
  // ryuiki.sqlite 由来
  sites: "main", source_registry: "main",
  // Tier 1 追加ソース（docs/UNDATAFIED_TIERS.md）。原本は ryuiki.sqlite。
  // mammal_mesh / wildlife_sightings は画面・API の読み手が無い（/api/nature は Issue #61 で撤去）。
  // AI の run_sql / describe_schema 用の台帳表として D1 に残している
  protected_areas: "main", vegetation_polygons: "main", mammal_mesh: "main",
  wildlife_sightings: "main", river_segments: "main",
  // 神奈川県 eDNA（scripts/m07_kanagawa_edna.py）。検出も不検出も。MCP/AI の get_edna と run_sql 用の台帳表
  edna_sites: "main", edna_reads: "main",
  // 外部ポータルの目録（scripts/m08_external_catalog.py。MCP/AI の find_datasets と run_sql 用。値は持たない）
  external_dataset: "main", external_resource: "main", external_resource_format: "main",
  // 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）。原本は data/water/*.csv → ryuiki.sqlite。
  // v2 にキューブ化しない台帳表として D1 に残す（Issue #61）。run_sql で「この町の水源はどこか」に答える用途
  water_utility: "main", water_source: "main", water_facility: "main",
  water_source_doc: "main", water_flow_edge: "main", water_zone: "main",
  water_zone_assignment: "main", water_zone_source_share: "main",
  // cells.sqlite 由来
  cells: "c", documents: "c", notes: "c",
  // v2.sqlite 由来（Issue #48）。観測キューブ・生物キューブと、その事前集計
  observation_agg: "v2", occurrence_agg: "v2",
  summary_variable_catalog: "v2", summary_place_variable: "v2",
  summary_taxon_catalog: "v2", summary_watershed_occurrence: "v2",
  summary_species_catalog: "v2", summary_group_year: "v2", summary_effort_year: "v2", summary_grid_catalog: "v2",
  // registry.sqlite 由来（語彙レジストリ）
  region: "reg", unit: "reg", variable: "reg", variable_alias: "reg",
  place: "reg", place_source_ref: "reg", place_relation: "reg", place_watershed: "reg",
  taxon: "reg", taxon_assessment: "reg", caveat: "reg", caveat_scope: "reg",
  license: "reg", source: "reg", source_edition: "reg", source_access: "reg",
};

export const TABLE_META: Record<string, string> = {
  sites: "観測地点。ゾーン(Ridge to Reef 1-5)・座標・標高・市区町村・運用主体",
  source_registry: "出典レジストリ。取得元・ライセンス・再配布可否",
  documents: "抽出元の行政文書（PDF）",
  cells: "行政文書の表のセル。行キー・列キー・年度・出典ページつき",
  notes: "表に付随する注記。時系列比較を阻害する注記のフラグを含む",
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
  edna_sites:
    "神奈川県 環境DNA（eDNA）の採水地点（ファイル×調査地点列）。lat/lon は推定位置で、" +
    "根拠 coord_source と誤差 coordinate_uncertainty_m つき（公開データに座標は無い）",
  edna_reads:
    "eDNA の検出・不検出（地点×採水×分類群のリード数。0 は不検出）。リード数は個体数ではない。" +
    "taxon_id は registry の taxon に結ぶ",
  external_dataset:
    "外部ポータル（CKAN 4 インスタンス・e-Stat）のデータセット目録。題名・説明・提供者・ライセンス・" +
    "最新を取る URL（api_url）つき。値は持たない。metadata_modified は fetched_at 時点",
  external_resource:
    "外部ポータルの資源（ファイル）。形式（format は原文）・サイズ・直リンク。sheets_json は見出しを検出できたものだけ列名を持つ",
  external_resource_format:
    "外部ポータルの資源の形式を正規化して要素ごとに 1 行にした照合用の表（'SHP,CSV' は 2 行。XLSK→XLSX、'.CSV'→CSV）",
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
  observation_agg:
    "観測キューブ。(variable_id, place_id, grain, stat, period_start) 単位のセル。" +
    "value_zero/value_lod の両方を持つ。画面・意図ツールは直接読まず summary_* 経由で読む",
  summary_variable_catalog:
    "指標カタログの事前集計。variable_id 単位（束ねる前）で observation_agg の年グレイン・" +
    "stat='mean' セルを集計したもの。list_catalog(what='variables') の元",
  summary_place_variable:
    "地点×指標の事前集計。(place_id, variable_id, obs_stat, unit_id, value_grain) 単位で" +
    "observation_agg の年グレイン・stat='mean' セルを集計したもの。get_sites の元",
  summary_species_catalog:
    "種カタログの事前集計。学名（二名法 binom）単位の記録数・レッドリスト/外来種の記録数・" +
    "出現グリッド数・出現年。日付のある生物レコードだけ。n>=80 の足切りの元",
  summary_group_year:
    "分類群×年×出典の事前集計（記録数・種数・グリッド数）。日付のある生物レコードだけ",
  summary_effort_year:
    "年ごとの観察努力（記録数・種数・グリッド数）の事前集計。日付のある生物レコードだけ",
  summary_taxon_catalog:
    "分類群カタログの事前集計（taxon_id 単位）。生物レコードのキューブ occurrence_agg を束ねたもの",
  summary_watershed_occurrence:
    "流域ごとの生物記録数・外来種記録数・レッドリスト記録数の事前集計。日付のある生物レコードだけ",
  occurrence_agg:
    "生物レコードのキューブ。(taxon_id, place_id, 年, 月 など) 単位の記録数。" +
    "画面・意図ツールは直接読まず summary_* 経由で読む（行数が多いので集計時は条件で絞ること）",
  summary_grid_catalog:
    "0.01度グリッドごとの記録数・レッドリスト記録数・種数（年1970〜2026の窓）の事前集計",
  unit: "単位レジストリ。unit_id・表記・変換係数",
  variable: "指標レジストリ。正準の variable_id・和名・単位・higher_is_worse・説明",
  variable_alias: "出典ごとの指標名（表記違い）から正準の variable_id への対応",
  place: "場所レジストリ。地点・流域・ゾーン・0.01度グリッドの place_id・名称・座標・面積",
  place_source_ref: "place と出典側のキー（site_id・watershed_id など）の対応",
  place_relation: "場所どうしの包含関係（地点→流域・ゾーンなど）",
  place_watershed: "流域（place）の水系コード・水系区分・主な河川・データ年",
  region: "地域（region_id）の時刻帯。IANA 名と UTC オフセット（観測日時はこの時刻帯のローカル時刻）",
  taxon: "分類群レジストリ。taxon_id・学名・和名・分類階級",
  taxon_assessment: "分類群ごとのレッドリスト・外来種などの評価（版・カテゴリー）",
  caveat: "データの癖・注記の本文（キー単位）",
  caveat_scope: "注記がどの dataset・指標・場所種別・出典にかかるかの対応",
  license: "出典のライセンス（license_id・名称・分類 license_class・表示文言）。原文の自由記述は source_edition.license_raw",
  source: "出典（不変）。source_registry と並走。置換された出典は superseded_by で新しい出典を指す",
  source_edition:
    "出典の版（取得回または出典自身の版）。取得日・URL・ライセンス・再配布可否・件数・置換先。" +
    "再配布可否・ライセンス分類は出典の旗で、出力を絞る根拠にしない",
  source_access:
    "出典ごとの「ツールで値が取れるか」。state（queryable/not_queryable）・queryable_via（取れるツール）・" +
    "n_source_rows（原本の行数。キューブの集計行数ではない）・取れない理由 reason",
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
    note: "どの指標が何年分あるかを一望する（事前集計 summary_variable_catalog）",
    sql: `SELECT v.variable_id, v.name_ja, c.unit_id, c.value_grain,
       sum(c.n) AS n, max(c.n_places) AS places,
       min(c.y_from) AS y_from, max(c.y_to) AS y_to
FROM summary_variable_catalog c JOIN variable v USING (variable_id)
GROUP BY 1,2,3,4
ORDER BY n DESC
LIMIT 200`,
  },
  {
    title: "地点ごとの水質平均（BOD）",
    note: "事前集計 summary_place_variable。value_grain（検体値か年度集計値か）と obs_stat を必ず見る。variable を変えれば他項目も同じ",
    sql: `SELECT p.name_ja AS site, s.value_grain, s.obs_stat, s.unit_id,
       s.y_from, s.y_to, s.n, round(s.avg_lod, 3) AS avg_lod, round(s.avg_zero, 3) AS avg_zero
FROM summary_place_variable s
JOIN place p USING (place_id)
JOIN variable v USING (variable_id)
WHERE p.place_kind = 'site' AND v.code LIKE '%bod%'
ORDER BY p.name_ja, s.value_grain
LIMIT 500`,
  },
  {
    title: "生物レコードの年次推移（分類群別）",
    note: "観察努力の増加も一緒に写ることに注意（事前集計 summary_group_year。日付のある記録だけ）",
    sql: `SELECT year, taxon_group, sum(n) AS n, sum(n_binom) AS species
FROM summary_group_year
WHERE year >= 2000
GROUP BY 1,2
ORDER BY 1 DESC, 3 DESC
LIMIT 500`,
  },
  {
    title: "外来種の記録数",
    note: "環境省の外来種リスト（moe_ias_2015）に載る種を、記録数の多い順に並べる",
    sql: `SELECT a.vernacular_name_ja_resolved AS name_ja, a.binom,
       c.n, c.y_from, c.y_to
FROM taxon_assessment a JOIN summary_species_catalog c USING (binom)
WHERE a.list_id = 'moe_ias_2015' AND a.in_scope = 1
ORDER BY c.n DESC
LIMIT 100`,
  },
  {
    title: "レッドリストの版間比較",
    note: "同じ和名が複数の版に登場するものを並べる",
    sql: `SELECT vernacular_name_ja_raw AS name_ja, taxon_group_ja,
       group_concat(list_year || ':' || COALESCE(category_code, category_raw, '-'), '  →  ') AS history,
       count(*) AS versions
FROM taxon_assessment
WHERE vernacular_name_ja_raw IS NOT NULL AND list_year IS NOT NULL
GROUP BY 1,2
HAVING versions > 1
ORDER BY versions DESC, name_ja
LIMIT 200`,
  },
  {
    title: "降水量の日別合計（センサー）",
    note: "観測キューブ observation_agg の日別 sum。件数が多いので variable_id・grain・stat・期間で必ず絞る",
    sql: `SELECT place_id, period_start AS day, round(value_lod, 2) AS daily_sum, n
FROM observation_agg
WHERE variable_id = 'common:variable:weather.precipitation'
  AND grain = 'day' AND stat = 'sum' AND period_start >= '2024-01'
ORDER BY period_start DESC
LIMIT 300`,
  },
  {
    title: "行政文書から抽出した指標",
    note: "行政文書のセル。同じ指標が複数年度にあるものを探す",
    sql: `SELECT doc_id, table_id, row_key, count(DISTINCT fiscal_year) AS years,
       min(fiscal_year) AS y_from, max(fiscal_year) AS y_to, count(*) AS n
FROM cells
WHERE superseded = 0 AND fiscal_year IS NOT NULL AND value_type IN ('int','float')
GROUP BY 1,2,3
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
