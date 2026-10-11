/**
 * D1 (SQLite) のスキーマ定義（v1・原本由来の表）。
 *
 * 元は 3 つの SQLite ファイル (ryuiki / cells / derived) に分かれていたテーブルを
 * D1 の 1 データベースに統合したもの。いま残っているのは ryuiki.sqlite（地点・出典・
 * 保護区などの台帳・水道）と cells.sqlite（行政 PDF から抽出したセル）由来の表だけで、
 * 集計済みの派生テーブル（derived.sqlite 由来 33 表）と、キューブに置き換わった
 * 観測・生物の原本表は Issue #48 PR-5 で撤去した（マイグレーション 0010 で DROP）。
 *
 * このファイルを編集したら `npm run db:generate` でマイグレーションを作り直す。
 * drizzle/migrations/*.sql を直接書き換えない。
 */
import { sql } from "drizzle-orm";
import { sqliteTable, text, integer, real, index, primaryKey } from "drizzle-orm/sqlite-core";
// 依存なしの定数ファイル（drizzle-kit は `@/` エイリアスを解決しないので相対 import）。
import { DOC_SERIES_WHERE } from "../lib/cube/doc-series-where";

export const sites = sqliteTable("sites", {
	siteId: text("site_id").primaryKey(),
	name: text(),
	nameEn: text("name_en"),
	watershed: text(),
	zone: integer(),
	lat: real(),
	lon: real(),
	elevationM: real("elevation_m"),
	geohash: text(),
	municipality: text(),
	muniCode: text("muni_code"),
	treatment: text(),
	establishedOn: text("established_on"),
	operator: text(),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
});

export const sourceRegistry = sqliteTable("source_registry", {
	sourceId: text("source_id").primaryKey(),
	name: text(),
	publisher: text(),
	url: text(),
	category: text(),
	accessMethod: text("access_method"),
	format: text(),
	license: text(),
	redistributable: integer(),
	fetchedAt: text("fetched_at"),
	recordCount: integer("record_count"),
	notes: text(),
});

export const cells = sqliteTable("cells", {
	id: integer().primaryKey({ autoIncrement: true }),
	docId: text("doc_id").notNull().references(() => documents.docId),
	docSha256: text("doc_sha256"),
	pageNo: integer("page_no"),
	tableId: text("table_id"),
	rowKey: text("row_key"),
	colKey: text("col_key"),
	valueRaw: text("value_raw"),
	value: text(),
	valueType: text("value_type"),
	unit: text(),
	fiscalYear: integer("fiscal_year"),
	eraRaw: text("era_raw"),
	sourceText: text("source_text"),
	sourceBbox: text("source_bbox"),
	notesRef: text("notes_ref"),
	isTotal: integer("is_total").default(0),
	merged: integer().default(0),
	unreadableReason: text("unreadable_reason"),
	confidence: real(),
	extractor: text(),
	verifiedBy: text("verified_by"),
	extractedAt: text("extracted_at"),
	superseded: integer().default(0),
},
(table) => [
	index("ix_cells_doc").on(table.docId, table.pageNo, table.tableId),
	// 文書の数値系列（lib/cube/documents.ts）。述語は問い合わせの WHERE と一字一句同じ（DOC_SERIES_WHERE）。
	index("ix_cells_series").on(table.docId, table.tableId, table.rowKey).where(sql.raw(DOC_SERIES_WHERE)),
]);

export const documents = sqliteTable("documents", {
	docId: text("doc_id").primaryKey(),
	title: text(),
	publisher: text(),
	url: text(),
	localPath: text("local_path"),
	docSha256: text("doc_sha256"),
	nPages: integer("n_pages"),
	fiscalYear: integer("fiscal_year"),
	license: text(),
	fetchedAt: text("fetched_at"),
});

export const notes = sqliteTable("notes", {
	// 原本では TEXT PRIMARY KEY だが 207 行のうち 30 行が NULL（SQLite は非 INTEGER の
	// 主キーに NULL を許す）。PRIMARY KEY にすると NOT NULL が付いて原本が入らないので、
	// 原本の実態に合わせて素の列にしてある。id の無い注記があるという事実を消さない。
	noteId: text("note_id"),
	docId: text("doc_id"),
	tableIds: text("table_ids"),
	kind: text(),
	text: text(),
	page: integer(),
	blocksTimeseries: integer("blocks_timeseries"),
	reason: text(),
});

/* ------------------------------------------------------------------ */
/* Tier 1 追加ソース（docs/UNDATAFIED_TIERS.md）                        */
/* 台帳・区域・メッシュ型のデータ。測定値は既存の measurements /        */
/* sensor_timeseries に入れているのでここには無い。                     */
/* 原本は ryuiki.sqlite（DDL は scripts/schema_tier1.sql）。            */
/* ------------------------------------------------------------------ */

/**
 * 保護区・緑地・保存樹木の指定台帳。
 * 自然公園 / 特別緑地保全地区 / 近郊緑地保全区域 / 歴史的風土保存地区 /
 * 風致地区 / 都市公園 / 保存樹木 を category_code で束ねている。
 * 面積を持たない点データ（保存樹木）も同じ表に同居する。
 */
export const protectedAreas = sqliteTable("protected_areas", {
	areaId: text("area_id").primaryKey(),
	nameJa: text("name_ja"),
	categoryJa: text("category_ja"),
	categoryCode: text("category_code"),
	municipalityJa: text("municipality_ja"),
	areaHa: real("area_ha"),
	areaHaRaw: text("area_ha_raw"),
	designatedOn: text("designated_on"),
	designatedOnRaw: text("designated_on_raw"),
	lat: real(),
	lon: real(),
	watershed: text(),
	zone: integer(),
	noteJa: text("note_ja"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("ix_pa_cat").on(table.categoryCode, table.municipalityJa),
]);

/**
 * 現存植生図2024（環境省 いきもの地図 ArcGIS REST）の神奈川県相当範囲。
 * `geometry_geojson` は表示用に simplify 済み。
 * `area_m2` は緯度経度からの近似で、厳密な測地面積ではない。
 */
export const vegetationPolygons = sqliteTable("vegetation_polygons", {
	featureId: text("feature_id").primaryKey(),
	legendCode: text("legend_code"),
	legendNameJa: text("legend_name_ja"),
	vegDivisionJa: text("veg_division_ja"),
	naturalness: real(),
	naturalnessClassJa: text("naturalness_class_ja"),
	surveyYear: integer("survey_year"),
	blockJa: text("block_ja"),
	areaM2: real("area_m2"),
	centroidLat: real("centroid_lat"),
	centroidLon: real("centroid_lon"),
	watershed: text(),
	geometryGeojson: text("geometry_geojson"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("ix_veg_legend").on(table.legendCode),
	// get_records: source_id = ? で絞って主キー順に読む（keyset ページング）
	index("ix_veg_source").on(table.sourceId, table.featureId),
]);

/**
 * 土砂災害警戒区域・特別警戒区域（鹿児島県、BODIK 460001_kgod016。奄美5市町村の指定済みポリゴン）。
 * 特別警戒区域は警戒区域の内側にあり、`area_m2`（ポリゴンごとの平面面積）を区分をまたいで足すと二重に数える。
 * 箇所番号は分割された区域で重複するので主キーは `zone_id`（`<箇所番号>:<r|y>:<連番>`）。
 * `designated_on` は公示日が読めた行だけ（原文の誤記 35 行は NULL で、`designated_on_raw` に原文）。
 */
export const hazardZones = sqliteTable("hazard_zones", {
	zoneId: text("zone_id").primaryKey(),
	siteCode: text("site_code"),
	siteNameJa: text("site_name_ja"),
	phenomenonCode: text("phenomenon_code"),
	phenomenonJa: text("phenomenon_ja"),
	zoneKindCode: text("zone_kind_code"),
	zoneKindJa: text("zone_kind_ja"),
	municipalityJa: text("municipality_ja"),
	localityJa: text("locality_ja"),
	riverNameJa: text("river_name_ja"),
	officeJa: text("office_ja"),
	designatedOn: text("designated_on"),
	designatedOnRaw: text("designated_on_raw"),
	noticeNoRaw: text("notice_no_raw"),
	areaM2: real("area_m2"),
	centroidLat: real("centroid_lat"),
	centroidLon: real("centroid_lon"),
	watershed: text(),
	geometryGeojson: text("geometry_geojson"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	// get_records: source_id = ? で絞って主キー順に読む（keyset ページング）
	index("ix_hz_source").on(table.sourceId, table.zoneId),
]);

/**
 * 中大型哺乳類の3次メッシュ分布（タヌキ / キツネ / アナグマ）。
 * 元データは年別の確認フラグが横に並ぶワイド形式で、1メッシュ×1調査年次=1行に展開してある。
 * `survey_label` に元の列名を残してある（第6回=dai6kai のように年を持たない列があるため）。
 */
export const mammalMesh = sqliteTable("mammal_mesh", {
	id: integer().primaryKey({ autoIncrement: true }),
	meshCode: text("mesh_code"),
	species: text(),
	speciesJa: text("species_ja"),
	surveyLabel: text("survey_label"),
	surveyYear: integer("survey_year"),
	confirmed: integer(),
	lat: real(),
	lon: real(),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("ix_mammal").on(table.species, table.surveyYear, table.meshCode),
	// get_records: source_id = ? で絞って主キー順に読む（keyset ページング）
	index("ix_mammal_source").on(table.sourceId, table.id),
]);

/**
 * 大型獣の出没・目撃記録（ツキノワグマ）。
 * 個体群管理の記録であって分類学的な観察記録ではないため organism_records とは分けている
 * （頭数・状況（目撃/痕跡/捕殺）・区分（人里/山中）に対応する Darwin Core の列が無い）。
 * 場所は地名テキストのみで原本に座標が無いため lat/lon は NULL のまま（推測で埋めていない）。
 */
export const wildlifeSightings = sqliteTable("wildlife_sightings", {
	sightingId: text("sighting_id").primaryKey(),
	speciesJa: text("species_ja"),
	fiscalYear: integer("fiscal_year"),
	observedOn: text("observed_on"),
	observedOnRaw: text("observed_on_raw"),
	observedTimeRaw: text("observed_time_raw"),
	individualCount: real("individual_count"),
	individualCountRaw: text("individual_count_raw"),
	situationJa: text("situation_ja"),
	localityJa: text("locality_ja"),
	areaKindJa: text("area_kind_ja"),
	municipalityJa: text("municipality_ja"),
	lat: real(),
	lon: real(),
	isPreliminary: integer("is_preliminary").default(0),
	noteJa: text("note_ja"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("ix_ws").on(table.speciesJa, table.fiscalYear),
]);

/**
 * 神奈川県 環境DNA（eDNA）の採水地点（`scripts/schema_edna.sql` の `edna_sites`、m07 が原本に作る）。
 * 地点 = ファイル × 調査地点列。lat/lon は台帳からの「推定位置」（公開データに座標は無い）で、
 * 根拠区分 coord_source と誤差 coordinate_uncertainty_m つき。判別不能は NULL。
 * AI の run_sql / MCP の get_edna 用の台帳表。出現レコード（occurrence）は b06 が別経路で作る。
 */
export const ednaSites = sqliteTable("edna_sites", {
	siteKey: text("site_key").primaryKey(),
	datasetFile: text("dataset_file").notNull(),
	program: text().notNull(),
	assay: text().notNull(),
	fiscalYear: integer("fiscal_year").notNull(),
	siteIdRaw: text("site_id_raw").notNull(),
	waterSystemRaw: text("water_system_raw"),
	waterSystemJa: text("water_system_ja"),
	tributaryRaw: text("tributary_raw"),
	tributaryJa: text("tributary_ja"),
	municipalityRaw: text("municipality_raw"),
	municipalityJa: text("municipality_ja"),
	collectedOn: text("collected_on"),
	collectedOnRaw: text("collected_on_raw"),
	lat: real(),
	lon: real(),
	coordSource: text("coord_source").notNull(),
	coordinateUncertaintyM: real("coordinate_uncertainty_m"),
	coordMethod: text("coord_method"),
	coordNote: text("coord_note"),
	sourceId: text("source_id").notNull(),
	sourceRef: text("source_ref").notNull(),
},
(table) => [
	index("ix_edna_sites_date").on(table.collectedOn),
	index("ix_edna_sites_region").on(table.waterSystemJa, table.tributaryJa),
]);

/**
 * eDNA の検出・不検出（`edna_reads`、約13.4万行）。値はリード数であって個体数ではない。
 * is_detected = (reads > 0)。0 は「その採水で検出されなかった」で、不在の証明ではない。
 * `edna_detections`（検出だけの投影）は reads から導けるので D1 には載せない。
 */
export const ednaReads = sqliteTable("edna_reads", {
	readId: text("read_id").primaryKey(),
	siteKey: text("site_key").notNull(),
	classJa: text("class_ja"),
	orderJa: text("order_ja"),
	familyJa: text("family_ja"),
	genusJa: text("genus_ja"),
	nameRaw: text("name_raw"),
	nameAdopted: text("name_adopted"),
	nameSciRaw: text("name_sci_raw"),
	nameNote: text("name_note"),
	reads: integer().notNull(),
	isDetected: integer("is_detected").notNull(),
	pidentQcov: real("pident_qcov"),
	reliability: text(),
	nationalRlRaw: text("national_rl_raw"),
	prefRlRaw: text("pref_rl_raw"),
	alienRaw: text("alien_raw"),
	nameKey: text("name_key").notNull(),
	taxonId: text("taxon_id"),
	sourceId: text("source_id").notNull(),
},
(table) => [
	index("ix_edna_reads_site").on(table.siteKey, table.isDetected),
	index("ix_edna_reads_taxon").on(table.taxonId, table.isDetected),
]);

/**
 * 河川流路。既存の `nlni_w05_rivers` は都道府県コード単位なので神奈川県内で切れているが、
 * こちらは水系コード 830307 単位なので、相模川の水源である山梨県側の桂川上流部を含む。
 */
export const riverSegments = sqliteTable("river_segments", {
	featureId: text("feature_id").primaryKey(),
	nameJa: text("name_ja"),
	sectionType: text("section_type"),
	prefectureJa: text("prefecture_ja"),
	lengthM: real("length_m"),
	startLat: real("start_lat"),
	startLon: real("start_lon"),
	endLat: real("end_lat"),
	endLon: real("end_lon"),
	geometryGeojson: text("geometry_geojson"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("ix_river_pref").on(table.prefectureJa),
]);


/**
 * 外部ポータルの目録（CKAN 4 インスタンス + e-Stat 7 件。docs/plans/MCP_EXTERNAL_CATALOG.md §1）。
 * 値は持たない。「どんなデータがあるか」の定義と、最新を取りに行く URL だけ（`find_datasets` が読む）。
 * `scripts/m08_external_catalog.py` が原本 ryuiki.sqlite に作る（DDL は `scripts/schema_catalog.sql`）。
 * metadata_modified・last_modified・size は収穫時点（fetched_at）の値。最新は api_url（package_show）が正。
 * license の空は NULL（不明。除外しない）。
 */
export const externalDataset = sqliteTable("external_dataset", {
	datasetKey: text("dataset_key").primaryKey(),
	sourceId: text("source_id").notNull(),
	portal: text().notNull(),
	datasetId: text("dataset_id").notNull(),
	name: text(),
	title: text().notNull(),
	description: text(),
	descriptionTruncated: integer("description_truncated").notNull().default(0),
	organization: text(),
	license: text(),
	licenseUrl: text("license_url"),
	groups: text(),
	tags: text(),
	nResources: integer("n_resources").notNull().default(0),
	/** 見出しを検出できた資源の数（m08 が sheets_json から数える。find_datasets は sheets_json を展開しない）。 */
	nWithHeader: integer("n_with_header").notNull().default(0),
	metadataModified: text("metadata_modified"),
	pageUrl: text("page_url").notNull(),
	apiUrl: text("api_url"),
	fetchedAt: text("fetched_at").notNull(),
},
(table) => [
	index("ix_ed_source_modified").on(table.sourceId, table.metadataModified),
	index("ix_ed_org").on(table.organization),
]);

/** 外部ポータルの資源（ファイル）。sheets_json は NULL か `[{sheet, n_rows, n_cols, header: [...] | null, header_basis?}]`。 */
export const externalResource = sqliteTable("external_resource", {
	resourceKey: text("resource_key").primaryKey(),
	datasetKey: text("dataset_key").notNull(),
	name: text(),
	format: text(),
	size: integer(),
	lastModified: text("last_modified"),
	directUrl: text("direct_url"),
	pageUrl: text("page_url"),
	sheetsJson: text("sheets_json"),
},
(table) => [
	index("ix_er_dataset").on(table.datasetKey),
]);

/**
 * 資源の format を正規化して要素ごとに 1 行（前後の空白と先頭の '.' を除き大文字・別名を寄せる。空は 'unspecified'）。
 * `find_datasets` の format 絞りが等号で引くための照合用。原文は `external_resource.format`。m08 が作る。
 */
export const externalResourceFormat = sqliteTable("external_resource_format", {
	datasetKey: text("dataset_key").notNull(),
	formatNorm: text("format_norm").notNull(),
	resourceKey: text("resource_key").notNull(),
},
(table) => [
	primaryKey({ columns: [table.datasetKey, table.formatNorm, table.resourceKey] }),
	index("ix_erf_format").on(table.formatNorm, table.datasetKey),
]);

/* ------------------------------------------------------------------ *
 * 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）
 *
 * 設計図のエンティティ名（utility / facility / zone …）はこの D1 では一般的すぎて
 * 61 テーブルの中で意味が取れないので、すべて `water_` を前に付けてある。対応は:
 *   utility → water_utility        facility   → water_facility
 *   water_source → water_source    flow_edge  → water_flow_edge
 *   source_doc → water_source_doc  zone       → water_zone
 *   zone_assignment → water_zone_assignment
 *   zone_source_share → water_zone_source_share
 *
 * 原本は `data/water/*.csv`（手で育てるので Git 管理下）。`scripts/m06_water.py` が
 * 検証してから ryuiki.sqlite に入れ、既存の seed / export 経路で D1 に乗る。
 * ジオメトリはここに持たない。町丁目のポリゴンは静的アセット
 * （/geo/water_zones.geojson）に水源比率ごと焼き込んであり、画面は D1 を読まない。
 * ------------------------------------------------------------------ */

/**
 * 水道事業体。kind は bulk（用水供給＝卸）と retail（末端給水）。
 * 神奈川県内広域水道企業団は bulk、横浜市水道局や県営水道は retail。
 */
export const waterUtility = sqliteTable("water_utility", {
	utilityId: text("utility_id").primaryKey(),
	name: text(),
	kind: text(),
	noteJa: text("note_ja"),
});

/**
 * 水源。河川・ダム・地下水・湧水。
 * parent_id は自己参照で「ダム→その河川」「支流→本流」「市の地下水→涵養域」を表す。
 * river_name_ja は既存の river_segments / nlni_w05_rivers の名称への名寄せ用で、
 * ここが埋まっていると水源カードから /map の該当河川へ飛べる。推測で埋めない。
 */
export const waterSource = sqliteTable("water_source", {
	sourceId: text("source_id").primaryKey(),
	name: text(),
	type: text(),
	riverSystem: text("river_system"),
	parentId: text("parent_id"),
	riverNameJa: text("river_name_ja"),
	lat: real(),
	lon: real(),
	noteJa: text("note_ja"),
	sourceDocId: text("source_doc_id"),
});

/** 取水堰・浄水場・配水池・分岐。flow_edge のノードになる。 */
export const waterFacility = sqliteTable("water_facility", {
	facilityId: text("facility_id").primaryKey(),
	utilityId: text("utility_id"),
	name: text(),
	type: text(),
	lat: real(),
	lon: real(),
	noteJa: text("note_ja"),
	sourceDocId: text("source_doc_id"),
},
(table) => [
	index("ix_wfac_utility").on(table.utilityId),
]);

/**
 * 根拠資料。source_doc_id が空の行はビルドで落とす（設計図 §6-1）。
 * PDF の実体は data/raw/water/ に置く（Git 管理外）。url + sha256 で再取得できるようにする。
 */
export const waterSourceDoc = sqliteTable("water_source_doc", {
	docId: text("doc_id").primaryKey(),
	title: text(),
	publisher: text(),
	url: text(),
	publishedAt: text("published_at"),
	retrievedAt: text("retrieved_at"),
	localPath: text("local_path"),
	sha256: text(),
	licenseJa: text("license_ja"),
});

/**
 * 流れの辺。「to_id の施設に入る水のうち何割が from_id 由来か」。
 * 同じ to_id × 同じ有効期間の share は合計 1.0（m06_water.py が検証する）。
 * basis: measured（年報の実測）/ estimated（按分などの推計）/ nominal（施設能力比。UI で「概算」）。
 */
export const waterFlowEdge = sqliteTable("water_flow_edge", {
	edgeId: text("edge_id").primaryKey(),
	fromId: text("from_id"),
	toId: text("to_id"),
	share: real(),
	basis: text(),
	validFrom: text("valid_from"),
	validTo: text("valid_to"),
	sourceDocId: text("source_doc_id"),
	noteJa: text("note_ja"),
},
(table) => [
	index("ix_wedge_to").on(table.toId, table.validFrom),
]);

/**
 * 町丁目（e-Stat 2020年国勢調査 小地域）。key_code が主キー。
 * 分断された町丁目は原本で複数レコードに分かれているが、KEY_CODE で 1 行に束ねてある
 * （parts に元のレコード数が入る）。ポリゴンはここではなく静的アセット側。
 */
export const waterZone = sqliteTable("water_zone", {
	keyCode: text("key_code").primaryKey(),
	muniCode: text("muni_code"),
	cityName: text("city_name"),
	sName: text("s_name"),
	name: text(),
	parts: integer(),
	population: integer(),
	households: integer(),
	areaKm2: real("area_km2"),
	centroidLat: real("centroid_lat"),
	centroidLon: real("centroid_lon"),
},
(table) => [
	index("ix_wzone_city").on(table.cityName),
]);

/**
 * 町丁目 → 給水元の施設（浄水場・配水池）の割付。
 * 複数系統が混在する町丁目だけ share が 1.0 未満になる。ポリゴンは分割しない（設計図 §7）。
 * confidence: high / medium / low。推測で high を付けない。
 */
export const waterZoneAssignment = sqliteTable("water_zone_assignment", {
	assignmentId: text("assignment_id").primaryKey(),
	keyCode: text("key_code"),
	facilityId: text("facility_id"),
	share: real(),
	confidence: text(),
	validFrom: text("valid_from"),
	validTo: text("valid_to"),
	sourceDocId: text("source_doc_id"),
	noteJa: text("note_ja"),
},
(table) => [
	index("ix_wza_key").on(table.keyCode),
	index("ix_wza_fac").on(table.facilityId),
]);

/**
 * 派生。zone_assignment から flow_edge を上流へ再帰的に辿って水源まで到達させ、
 * source_id ごとに合算したもの。m06_water.py が生成する（手で書かない）。
 * 卸→末端の 2 段ブレンドもこの再帰で表現される。
 */
export const waterZoneSourceShare = sqliteTable("water_zone_source_share", {
	keyCode: text("key_code"),
	sourceId: text("source_id"),
	share: real(),
	confidence: text(),
	basis: text(),
	asOf: text("as_of"),
},
(table) => [
	index("ix_wzss_key").on(table.keyCode),
	index("ix_wzss_src").on(table.sourceId),
]);

/**
 * シード投入の状態。アプリのデータではなく、開発環境の都合で持つ内部テーブル。
 * 原本 SQLite のフィンガープリント（サイズ + mtime）を入れておき、
 * 一致していれば docker 起動時のシードを飛ばす。
 * 先頭が `_` のテーブルはデータ探索画面の一覧から除外している。
 */
export const seedState = sqliteTable("_seed_state", {
	key: text().primaryKey(),
	value: text(),
	updatedAt: text("updated_at"),
});
