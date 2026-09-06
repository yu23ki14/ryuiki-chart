/**
 * D1 (SQLite) のスキーマ定義。
 *
 * 元は 3 つの SQLite ファイル (ryuiki / cells / derived) に分かれていたテーブルを
 * D1 の 1 データベースに統合したもの。テーブル名の衝突は無いのでそのまま並べている。
 *
 *   ryuiki.sqlite  … 原本（観測・生物・地点・出典）
 *   cells.sqlite   … 行政 PDF から抽出したセル
 *   derived.sqlite … 集計済みの派生テーブル
 *
 * derived.sqlite の多くの列は CREATE TABLE AS SELECT 由来で型宣言が空だったため、
 * 実データの typeof() を数えて text / integer / real を明示し直してある。
 *
 * このファイルを編集したら `npm run db:generate` でマイグレーションを作り直す。
 * drizzle/migrations/*.sql を直接書き換えない。
 */
import { sqliteTable, text, integer, real, index } from "drizzle-orm/sqlite-core";

export const decisions = sqliteTable("decisions", {
	decisionId: text("decision_id").primaryKey(),
	meetingName: text("meeting_name"),
	meetingDate: text("meeting_date"),
	presentedData: text("presented_data"),
	decided: text(),
	stalledItemResolved: integer("stalled_item_resolved"),
	participants: text(),
	url: text(),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
});

export const eventObservers = sqliteTable("event_observers", {
	eventId: text("event_id"),
	observerId: text("observer_id"),
	part: text(),
});

export const events = sqliteTable("events", {
	eventId: text("event_id").primaryKey(),
	siteId: text("site_id"),
	eventDate: text("event_date"),
	eventTime: text("event_time"),
	protocolId: text("protocol_id"),
	protocolVersion: text("protocol_version"),
	weather: text(),
	precip24HMm: real("precip_24h_mm"),
	waterTempC: real("water_temp_c"),
	photoCount: integer("photo_count"),
	gpsOffsetM: real("gps_offset_m"),
	isBackfilled: integer("is_backfilled").default(0),
	isRainTriggered: integer("is_rain_triggered").default(0),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
});

export const instruments = sqliteTable("instruments", {
	instrumentId: text("instrument_id").primaryKey(),
	kind: text(),
	model: text(),
	calibratedOn: text("calibrated_on"),
	calibrationNote: text("calibration_note"),
	uncalibratedFlag: integer("uncalibrated_flag").default(0),
});

export const interventions = sqliteTable("interventions", {
	interventionId: text("intervention_id").primaryKey(),
	siteId: text("site_id"),
	kind: text(),
	parcel: text(),
	quantity: real(),
	quantityUnit: text("quantity_unit"),
	startedOn: text("started_on"),
	finishedOn: text("finished_on"),
	operator: text(),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
});

export const measurements = sqliteTable("measurements", {
	measurementId: text("measurement_id").primaryKey(),
	eventId: text("event_id"),
	siteId: text("site_id"),
	measuredOn: text("measured_on"),
	variable: text(),
	variableEn: text("variable_en"),
	value: real(),
	valueRaw: text("value_raw"),
	unit: text(),
	method: text(),
	instrumentId: text("instrument_id"),
	detectionFlag: text("detection_flag"),
	qualityStage: text("quality_stage").default("暫定"),
	verifiedBy: text("verified_by"),
	verifiedOn: text("verified_on"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
},
(table) => [
	index("ix_meas_site").on(table.siteId, table.variable, table.measuredOn),
]);

export const observers = sqliteTable("observers", {
	observerId: text("observer_id").primaryKey(),
	displayName: text("display_name"),
	role: text(),
	org: text(),
	isSynthetic: integer("is_synthetic").default(1),
});

export const organismRecords = sqliteTable("organism_records", {
	recordId: text("record_id").primaryKey(),
	eventId: text("event_id"),
	siteId: text("site_id"),
	observedOn: text("observed_on"),
	scientificName: text("scientific_name"),
	vernacularName: text("vernacular_name"),
	taxonRank: text("taxon_rank"),
	kingdom: text(),
	phylum: text(),
	class: text(),
	order: text(),
	family: text(),
	genus: text(),
	taxonKey: text("taxon_key"),
	individualCount: real("individual_count"),
	density: real(),
	densityUnit: text("density_unit"),
	basisOfRecord: text("basis_of_record"),
	identifiedBy: text("identified_by"),
	identificationBasis: text("identification_basis"),
	identificationConfidence: real("identification_confidence"),
	lat: real(),
	lon: real(),
	coordinateUncertaintyM: real("coordinate_uncertainty_m"),
	redListCategory: text("red_list_category"),
	isAlien: integer("is_alien").default(0),
	qualityStage: text("quality_stage").default("暫定"),
	publicationScope: text("publication_scope").default("限定共有"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
	isSynthetic: integer("is_synthetic").default(0),
	recordLicense: text("record_license"),
	licenseClass: text("license_class"),
	commercialOk: integer("commercial_ok"),
},
(table) => [
	index("ix_org_license_class").on(table.licenseClass),
	index("ix_org_name").on(table.scientificName),
]);

export const protocols = sqliteTable("protocols", {
	protocolId: text("protocol_id").primaryKey(),
	name: text(),
	version: text(),
	domain: text(),
	stepsJson: text("steps_json"),
	sourceId: text("source_id"),
	url: text(),
});

export const qualityTransitions = sqliteTable("quality_transitions", {
	id: integer().primaryKey({ autoIncrement: true }),
	targetTable: text("target_table"),
	targetId: text("target_id"),
	fromStage: text("from_stage"),
	toStage: text("to_stage"),
	actor: text(),
	occurredAt: text("occurred_at"),
	note: text(),
});

export const redlistAssessments = sqliteTable("redlist_assessments", {
	assessmentId: text("assessment_id").primaryKey(),
	listName: text("list_name").notNull(),
	listYear: integer("list_year").notNull(),
	taxonGroupJa: text("taxon_group_ja"),
	taxonSubgroupJa: text("taxon_subgroup_ja"),
	familyJa: text("family_ja"),
	vernacularNameJa: text("vernacular_name_ja"),
	scientificName: text("scientific_name"),
	categoryCode: text("category_code"),
	categoryJa: text("category_ja"),
	categoryPrevJa: text("category_prev_ja"),
	nationalCategoryJa: text("national_category_ja"),
	noteJa: text("note_ja"),
	taxonId: text("taxon_id"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
},
(table) => [
	index("idx_rla_group").on(table.taxonGroupJa),
	index("idx_rla_vname").on(table.vernacularNameJa),
	index("idx_rla_year").on(table.listYear),
]);

export const sensorTimeseries = sqliteTable("sensor_timeseries", {
	id: integer().primaryKey({ autoIncrement: true }),
	siteId: text("site_id"),
	datastream: text(),
	phenomenonTime: text("phenomenon_time"),
	result: real(),
	unit: text(),
	instrumentId: text("instrument_id"),
	sourceId: text("source_id"),
	isSynthetic: integer("is_synthetic").default(0),
},
(table) => [
	index("ix_ts").on(table.siteId, table.datastream, table.phenomenonTime),
]);

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

export const taxa = sqliteTable("taxa", {
	taxonId: text("taxon_id").primaryKey(),
	scientificName: text("scientific_name"),
	vernacularNameJa: text("vernacular_name_ja"),
	taxonGroupJa: text("taxon_group_ja"),
	kingdom: text(),
	phylum: text(),
	class: text(),
	order: text(),
	family: text(),
	genus: text(),
	gbifTaxonKey: text("gbif_taxon_key"),
	gbifMatchType: text("gbif_match_type"),
	redlistKanagawa: text("redlist_kanagawa"),
	redlistNational: text("redlist_national"),
	iasCategory: text("ias_category"),
	sourceId: text("source_id"),
	sourceRef: text("source_ref"),
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

export const extractionLog = sqliteTable("extraction_log", {
	ts: text(),
	docId: text("doc_id"),
	pageNo: integer("page_no"),
	tableId: text("table_id"),
	role: text(),
	attempt: integer(),
	verdict: text(),
	failures: text(),
	note: text(),
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

export const vocabAreas = sqliteTable("vocab_areas", {
	docId: text("doc_id"),
	name: text(),
	definition: text(),
	foundDefinition: integer("found_definition"),
	pages: text(),
});

export const vocabEras = sqliteTable("vocab_eras", {
	docId: text("doc_id"),
	literal: text(),
	pages: text(),
});

export const vocabIndicators = sqliteTable("vocab_indicators", {
	docId: text("doc_id"),
	name: text(),
	unit: text(),
	method: text(),
	pages: text(),
});

export const vocabUnits = sqliteTable("vocab_units", {
	docId: text("doc_id"),
	literal: text(),
	quantity: text(),
	pages: text(),
});

export const docSeries = sqliteTable("doc_series", {
	docId: text("doc_id"),
	tableId: text("table_id"),
	pageNo: integer("page_no"),
	rowKey: text("row_key"),
	label: text(),
	fiscalYear: integer("fiscal_year"),
	value: real(),
	nCells: integer("n_cells"),
	unit: text(),
},
(table) => [
	index("ix_ds").on(table.docId, table.tableId, table.rowKey),
]);

export const docSeriesMeta = sqliteTable("doc_series_meta", {
	docId: text("doc_id"),
	tableId: text("table_id"),
	rowKey: text("row_key"),
	label: text(),
	pageNo: integer("page_no"),
	nYears: integer("n_years"),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
	unit: text(),
	vMin: real("v_min"),
	vMax: real("v_max"),
	docTitle: text("doc_title"),
	publisher: text(),
	url: text(),
	license: text(),
	nWarnings: integer("n_warnings"),
},
(table) => [
	index("ix_dsm").on(table.nYears),
]);

export const effortYear = sqliteTable("effort_year", {
	year: integer(),
	n: integer(),
	speciesN: integer("species_n"),
	meshN: integer("mesh_n"),
	nInat: integer("n_inat"),
	nGbif: integer("n_gbif"),
});

export const iasSpecies = sqliteTable("ias_species", {
	iasCategory: text("ias_category"),
	binom: text(),
	nameJa: text("name_ja"),
	taxonGroup: text("taxon_group"),
	enName: text("en_name"),
	n: integer(),
	meshN: integer("mesh_n"),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
	nSince2020: integer("n_since_2020"),
},
(table) => [
	index("ix_ias").on(table.n),
]);

export const landuseChange = sqliteTable("landuse_change", {
	watershedId: text("watershed_id"),
	landuseName: text("landuse_name"),
	km22006: real("km2_2006"),
	km22016: real("km2_2016"),
	deltaKm2: real("delta_km2"),
},
(table) => [
	index("ix_lc").on(table.watershedId),
]);

export const landuseWatershed = sqliteTable("landuse_watershed", {
	watershedId: text("watershed_id"),
	year: integer(),
	landuseCode: text("landuse_code"),
	landuseName: text("landuse_name"),
	nCells: integer("n_cells"),
	areaKm2: real("area_km2"),
},
(table) => [
	index("ix_lw").on(table.watershedId, table.year),
]);

export const measClim = sqliteTable("meas_clim", {
	variable: text(),
	month: integer(),
	n: integer(),
	avg: real(),
	min: real(),
	max: real(),
	unit: text(),
});

export const measDaily = sqliteTable("meas_daily", {
	siteId: text("site_id"),
	variable: text(),
	d: text(),
	value: real(),
	nRaw: integer("n_raw"),
	nCensored: integer("n_censored"),
	unit: text(),
},
(table) => [
	index("ix_md_site").on(table.siteId, table.variable, table.d),
	index("ix_md").on(table.variable, table.siteId, table.d),
]);

export const measMonth = sqliteTable("meas_month", {
	siteId: text("site_id"),
	variable: text(),
	ym: text(),
	year: integer(),
	month: integer(),
	n: integer(),
	avg: real(),
	unit: text(),
},
(table) => [
	index("ix_mm_site").on(table.siteId, table.variable, table.ym),
	index("ix_mm").on(table.variable, table.ym),
]);

export const measYear = sqliteTable("meas_year", {
	siteId: text("site_id"),
	variable: text(),
	kind: text(),
	year: integer(),
	n: integer(),
	avg: real(),
	min: real(),
	max: real(),
	nCensored: integer("n_censored"),
	unit: text(),
},
(table) => [
	index("ix_my_site").on(table.siteId, table.variable, table.kind, table.year),
	index("ix_my").on(table.variable, table.kind, table.year),
]);

export const meshAll = sqliteTable("mesh_all", {
	mlat: integer(),
	mlon: integer(),
	n: integer(),
	rlN: integer("rl_n"),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
});

export const meshSpecies = sqliteTable("mesh_species", {
	mlat: integer(),
	mlon: integer(),
	speciesN: integer("species_n"),
	rlSpeciesN: integer("rl_species_n"),
});

export const meshYear = sqliteTable("mesh_year", {
	mlat: integer(),
	mlon: integer(),
	year: integer(),
	n: integer(),
	speciesN: integer("species_n"),
	rlN: integer("rl_n"),
},
(table) => [
	index("ix_my2").on(table.year),
]);

export const orgGroupYear = sqliteTable("org_group_year", {
	year: integer(),
	taxonGroup: text("taxon_group"),
	sourceId: text("source_id"),
	n: integer(),
	speciesN: integer("species_n"),
	meshN: integer("mesh_n"),
},
(table) => [
	index("ix_ogy").on(table.year),
]);

export const orgNorm = sqliteTable("org_norm", {
	recordId: text("record_id"),
	sourceId: text("source_id"),
	yr: integer(),
	mo: integer(),
	binom: text(),
	scientificName: text("scientific_name"),
	vernacularName: text("vernacular_name"),
	rankL: text("rank_l"),
	cls: text(),
	kdm: text(),
	phy: text(),
	ord: text(),
	family: text(),
	lat: real(),
	lon: real(),
	mlat: integer(),
	mlon: integer(),
	redListCategory: text("red_list_category"),
	licenseClass: text("license_class"),
	isAlien: integer("is_alien"),
	taxonGroup: text("taxon_group"),
},
(table) => [
	index("ix_on_yr").on(table.yr),
	index("ix_on_mesh").on(table.mlat, table.mlon),
	index("ix_on_grp").on(table.taxonGroup, table.yr),
	index("ix_on_binom").on(table.binom, table.yr),
]);

export const orgWatershed = sqliteTable("org_watershed", {
	watershedId: text("watershed_id"),
	n: integer(),
	alienN: integer("alien_n"),
	redlistN: integer("redlist_n"),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
},
(table) => [
	index("ix_ow").on(table.watershedId),
]);

export const orgWatershedYear = sqliteTable("org_watershed_year", {
	watershedId: text("watershed_id"),
	year: integer(),
	n: integer(),
	speciesN: integer("species_n"),
	alienN: integer("alien_n"),
	redlistN: integer("redlist_n"),
},
(table) => [
	index("ix_owy").on(table.watershedId, table.year),
]);

export const qualityMonthly = sqliteTable("quality_monthly", {
	ym: text(),
	submitted: integer(),
	verified: integer(),
	published: integer(),
	returned: integer(),
});

export const rainDaily = sqliteTable("rain_daily", {
	d: text(),
	mm: real(),
	nHours: integer("n_hours"),
},
(table) => [
	index("ix_rain").on(table.d),
]);

export const redlistChange = sqliteTable("redlist_change", {
	assessmentId: text("assessment_id"),
	listName: text("list_name"),
	listYear: integer("list_year"),
	taxonGroupJa: text("taxon_group_ja"),
	taxonSubgroupJa: text("taxon_subgroup_ja"),
	familyJa: text("family_ja"),
	vernacularNameJa: text("vernacular_name_ja"),
	scientificName: text("scientific_name"),
	nationalCategoryJa: text("national_category_ja"),
	prevLabel: text("prev_label"),
	prevCode: text("prev_code"),
	prevRank: integer("prev_rank"),
	curLabel: text("cur_label"),
	curCode: text("cur_code"),
	curRank: integer("cur_rank"),
	direction: text(),
},
(table) => [
	index("ix_rc").on(table.listYear, table.direction),
]);

export const redlistMap = sqliteTable("redlist_map", {
	raw: text().primaryKey(),
	label: text(),
	code: text(),
	rank: integer(),
});

export const sensorDaily = sqliteTable("sensor_daily", {
	siteId: text("site_id"),
	datastream: text(),
	d: text(),
	n: integer(),
	avg: real(),
	min: real(),
	max: real(),
	unit: text(),
},
(table) => [
	index("ix_sd").on(table.datastream, table.d),
]);

export const sensorHourMonth = sqliteTable("sensor_hour_month", {
	datastream: text(),
	month: integer(),
	hour: integer(),
	n: integer(),
	avg: real(),
	max: real(),
});

export const siteVar = sqliteTable("site_var", {
	siteId: text("site_id"),
	variable: text(),
	kind: text(),
	n: integer(),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
	avg: real(),
	unit: text(),
},
(table) => [
	index("ix_sv_var").on(table.variable),
	index("ix_sv").on(table.siteId),
]);

export const species2 = sqliteTable("species2", {
	binom: text(),
	taxonGroup: text("taxon_group"),
	cls: text(),
	family: text(),
	enName: text("en_name"),
	redListCategory: text("red_list_category"),
	n: integer(),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
	nYears: integer("n_years"),
	meshN: integer("mesh_n"),
},
(table) => [
	index("ix_sp2_g").on(table.taxonGroup, table.n),
	index("ix_sp2").on(table.n),
]);

export const speciesMeshYear = sqliteTable("species_mesh_year", {
	binom: text(),
	year: integer(),
	mlat: integer(),
	mlon: integer(),
	n: integer(),
},
(table) => [
	index("ix_smy").on(table.binom, table.year),
]);

export const speciesMonth = sqliteTable("species_month", {
	binom: text(),
	month: integer(),
	n: integer(),
},
(table) => [
	index("ix_spm").on(table.binom),
]);

export const speciesYear2 = sqliteTable("species_year2", {
	binom: text(),
	year: integer(),
	n: integer(),
	meshN: integer("mesh_n"),
},
(table) => [
	index("ix_sy2").on(table.binom, table.year),
]);

export const varCatalog = sqliteTable("var_catalog", {
	variable: text(),
	unit: text(),
	n: integer(),
	nSites: integer("n_sites"),
	yFrom: integer("y_from"),
	yTo: integer("y_to"),
	nDaily: integer("n_daily"),
	nAnnual: integer("n_annual"),
	nCensored: integer("n_censored"),
});

export const watershedMeta = sqliteTable("watershed_meta", {
	watershedId: text("watershed_id").primaryKey(),
	waterSystemCode: text("water_system_code"),
	waterSystemName: text("water_system_name"),
	waterSystemCategory: text("water_system_category"),
	mainRivers: text("main_rivers"),
	areaKm2: real("area_km2"),
	centroidLat: real("centroid_lat"),
	centroidLon: real("centroid_lon"),
	dataYear: integer("data_year"),
	sourceRef: text("source_ref"),
});

export const watershedRollup = sqliteTable("watershed_rollup", {
	watershedId: text("watershed_id"),
	waterSystemName: text("water_system_name"),
	areaKm2: real("area_km2"),
	centroidLat: real("centroid_lat"),
	centroidLon: real("centroid_lon"),
	orgN: integer("org_n"),
	orgAlienN: integer("org_alien_n"),
	orgRedlistN: integer("org_redlist_n"),
	siteN: integer("site_n"),
	siteVarN: integer("site_var_n"),
	builtKm22016: real("built_km2_2016"),
	builtKm22006: real("built_km2_2006"),
	forestKm22016: real("forest_km2_2016"),
	forestKm22006: real("forest_km2_2006"),
	paddyKm22016: real("paddy_km2_2016"),
	paddyKm22006: real("paddy_km2_2006"),
},
(table) => [
	index("ix_wr").on(table.watershedId),
]);

export const zoneClim = sqliteTable("zone_clim", {
	zone: integer(),
	variable: text(),
	month: integer(),
	nSites: integer("n_sites"),
	n: integer(),
	avg: real(),
	unit: text(),
});

export const zoneYear = sqliteTable("zone_year", {
	zone: integer(),
	variable: text(),
	kind: text(),
	year: integer(),
	nSites: integer("n_sites"),
	n: integer(),
	avg: real(),
	unit: text(),
},
(table) => [
	index("ix_zy").on(table.variable, table.kind, table.year),
]);


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
