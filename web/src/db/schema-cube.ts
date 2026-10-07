/**
 * キューブ（ADR-0011・ADR-0021・ADR-0025・ADR-0009 決定4）のスキーマ定義。
 *
 * `observation_agg`/`occurrence_agg` は `data/db/v2.sqlite`（`scripts/b04_build_cube.py`・
 * `scripts/b07_build_occurrence_cube.py` が作る）の実物の列をそのまま宣言している
 * （列名・列順・NOT NULL は各スクリプトの `_CREATE_OBSERVATION_AGG_SQL`/
 * `_CREATE_OCCURRENCE_AGG_SQL` を正とする——ここは追随する）。
 *
 * **L2（`observation`/`occurrence`/`occurrence_place`）は D1 に入れない**
 * （Issue #48・ADR-0001「D1 は L3 の配信キャッシュ」）。ここに定義するのは
 * キューブ（L3）の2表だけ。`occurrence_place` はレジストリ側にも v2 側にも
 * D1 の消費者がまだ無いので、`schema-registry.ts` の `place_relation`/
 * `place_watershed` と同じ判断で見送る。
 *
 * 索引は Issue #48 の指定どおり（画面・AI の代表的な問い合わせ:
 * 「ある指標のある地点の時系列」「ある地点の指標一覧」「ある分類群の時系列」
 * 「ある地点の生物記録」）:
 *   - `observation_agg(variable_id, place_id, grain, stat, period_start)`
 *   - `observation_agg(place_id, variable_id, grain)`
 *   - `occurrence_agg(taxon_id, period_start)`
 *   - `occurrence_agg(place_id, period_start)`
 *   - `occurrence_agg(place_kind, grain, period_start)`（Issue #48 PR-3a D6・
 *     ADR-0030 D3 追記。族〔year/month〕・place_kind〔grid01/watershed〕が
 *     2つずつに増えたため、年の地図クエリ〔ある年の grid01/watershed 全体〕が
 *     この3列で絞らないと全表走査になる）
 *
 * このファイルを編集したら `npm run db:generate` でマイグレーションを作り直す。
 * drizzle/migrations/*.sql を直接書き換えない。`schema.ts`/`schema-registry.ts` と
 * ファイルを分けてある理由も同じ（既存テーブル定義への無変更を diff で示すため）。
 * `drizzle.config.ts` の `schema` 配列に加えてある。
 */
import { sqliteTable, text, integer, real, index } from "drizzle-orm/sqlite-core";

/**
 * 観測のキューブ（`measurements`/`sensor_timeseries`/土地利用CSV → `observation`
 * → このキューブ。ADR-0016 Phase B「ファクトとキューブ」）。
 *
 * 次元キー12列（`region_id`〜`stat`）＋値2列（`value_zero`/`value_lod`。
 * ADR-0009 決定4で `imputation` を次元キーから外し値の列に分けた形）＋
 * 件数4列＋来歴2列の計20列。`imputation`/`value` という列は**持たない**
 * （PR #26 以前の13列キーの旧形——`web/scripts/seed-d1-local.mjs` が
 * この列集合で旧い `v2.sqlite` を拒否する）。
 *
 * `n`/`n_censored`/`n_not_detected`/`n_places` は `observation`（L2）の
 * 観測行を数えた値で NOT NULL（`scripts/b04_build_cube.py` の
 * `_CREATE_OBSERVATION_AGG_SQL` 参照）。次元キー・値列は NULL を許容する
 * （`place_id`/`unit_id` 等が NULL になりうる実データがあるため——
 * 同スクリプトの `_CREATE_OBSERVATION_AGG_SQL` も NOT NULL を付けていない）。
 */
export const observationAgg = sqliteTable(
	"observation_agg",
	{
		regionId: text("region_id"),
		placeId: text("place_id"),
		placeKind: text("place_kind"),
		variableId: text("variable_id"),
		obsStat: text("obs_stat"),
		unitId: text("unit_id"),
		valueGrain: text("value_grain"),
		periodStart: text("period_start"),
		periodEnd: text("period_end"),
		grain: text(),
		inputGrain: text("input_grain"),
		stat: text(),
		valueZero: real("value_zero"),
		valueLod: real("value_lod"),
		n: integer().notNull(),
		nCensored: integer("n_censored").notNull(),
		nNotDetected: integer("n_not_detected").notNull(),
		nPlaces: integer("n_places").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [
		index("ix_observation_agg_variable_place_grain_stat_period").on(
			table.variableId,
			table.placeId,
			table.grain,
			table.stat,
			table.periodStart,
		),
		index("ix_observation_agg_place_variable_grain").on(table.placeId, table.variableId, table.grain),
	],
);

// `occurrence_agg` の索引名（Issue #48 PR-3b §6-1）。taxon 引きの問い合わせは
// `INDEXED BY ${OCCURRENCE_AGG_INDEX.taxonPeriod}` を付ける（第3索引
// `kindGrainPeriod` がプランナに選ばれて 100 秒超かかる罠の回避。設計書 §0-2）——
// `INDEXED BY` は索引が無いと実行時エラーになるので、名前はここ1箇所に置き、
// `scripts/b07_build_occurrence_cube.py` の `OCCURRENCE_AGG_INDEXES` と
// `scripts/tests/test_cube_index_parity.py` が一致を機械検証する。
export const OCCURRENCE_AGG_INDEX = {
	taxonPeriod: "ix_occurrence_agg_taxon_period",
	placePeriod: "ix_occurrence_agg_place_period",
	kindGrainPeriod: "ix_occurrence_agg_kind_grain_period",
} as const;

/**
 * 生物出現のキューブ（`organism_records` → `occurrence` → このキューブ。
 * ADR-0025 D2）。次元キー8列＋値3列（`n`/`n_red_list`/`n_alien`）＋来歴2列の
 * 計13列。
 *
 * `n_alien`（Issue #48 PR-3a D3。Issue #34 で `SUM(is_alien_in_scope)` に変更）は v1
 * `org_watershed.alien_n`/`watershed_rollup.org_alien_n` の後継——JOIN で導くより加法で正確・速い。
 * `is_alien_in_scope` は b06 が、記録の二名法が `taxon_assessment`（moe_ias_2015）に `in_scope=1` で
 * 載っているかから導く（原本の `is_alien` 旗は種内で 1/0 が混在するため使わない。除外規則は
 * `registry/taxon/assessment_scope_exclusions.yaml`）。
 *
 * PR-3a で `place_kind`/`grain` の取りうる値が増えた: `place_kind` は
 * `grid01`（既存）に加えて `watershed`（O-2。流域に解決できない日付あり記録は
 * `place_kind='watershed', place_id NULL` のセルとして持つ——ADR-0025/0026
 * D1「データを落とさない」）、`grain` は年族 `{year, survey_period}`（既存）に
 * 加えて月族 `{month}`（同一月に収まる記録だけの分割）を持つ。
 *
 * `region_id`/`source_id`/`grain`/`period_start`/`period_end`/`n`/`n_red_list`/
 * `n_alien`/`built_from`/`spec_version` は NOT NULL、`place_id`/`place_kind`/
 * `taxon_id` は NULL を許容する（`scripts/b07_build_occurrence_cube.py` の
 * `_CREATE_OCCURRENCE_AGG_SQL` のまま——taxon_id/place_id が NULL のセルも
 * データを落とさず持つ、という同スクリプトの決定に合わせる）。
 */
export const occurrenceAgg = sqliteTable(
	"occurrence_agg",
	{
		regionId: text("region_id").notNull(),
		sourceId: text("source_id").notNull(),
		placeId: text("place_id"),
		placeKind: text("place_kind"),
		taxonId: text("taxon_id"),
		grain: text().notNull(),
		periodStart: text("period_start").notNull(),
		periodEnd: text("period_end").notNull(),
		n: integer().notNull(),
		nRedList: integer("n_red_list").notNull(),
		// `.default(0)`: 既存 D1（データの入った `occurrence_agg`）に対する
		// `ALTER TABLE ADD COLUMN` が既定値なしだと失敗するため（SQLite は
		// NOT NULL な列を既存の非空テーブルに追加するとき既定値を要求する）。
		// 新規ビルドの b07 は常に実測値で埋めるので、この既定値が実際に使われる
		// のは「移行の瞬間の既存行」だけ。Issue #48 PR-3a 統合 /code-review 指摘2。
		nAlien: integer("n_alien").notNull().default(0),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [
		index(OCCURRENCE_AGG_INDEX.taxonPeriod).on(table.taxonId, table.periodStart),
		index(OCCURRENCE_AGG_INDEX.placePeriod).on(table.placeId, table.periodStart),
		index(OCCURRENCE_AGG_INDEX.kindGrainPeriod).on(table.placeKind, table.grain, table.periodStart),
	],
);

/**
 * summary 4表（Issue #48 PR-2・PR-3a、`aggregations/serving.yaml` →
 * `scripts/b13_build_summary.py`）。
 *
 * `observation_agg`（キューブ、上の `observationAgg`）を「年グレイン（year/fiscal_year）・
 * site・stat='mean'」に絞って事前集計した2表（`summaryVariableCatalog`/
 * `summaryPlaceVariable`、PR-2）に加え、`occurrence_agg`（上の `occurrenceAgg`）を
 * 「grid01・年族」「watershed・年族」に絞って事前集計した2表
 * （`summaryTaxonCatalog`/`summaryWatershedOccurrence`、PR-3a）の計4表。列は
 * `aggregations/serving.yaml` の同名の宣言（group_by＋measures）と1対1で
 * 対応させてある——ここを触ったら YAML 側と `scripts/b13_build_summary.py` の
 * CREATE 文も合わせて直すこと。次元キー＋測度＋来歴2列（`built_from`/
 * `spec_version`。`observationAgg`/`occurrenceAgg` と同じ形）。
 *
 * `catalog.ts`（PR-3b で生物系の同種モジュールが加わる予定）はこれらを
 * `source:'summary'`（既定）で読む。variable_id/binom 単位への束ね・代表化は
 * ここではなく問い合わせ層の仕事（このテーブル自体は系列＝tuple 単位、または
 * `taxon_id`/`place_id` そのものの単位のまま）。
 */
export const summaryVariableCatalog = sqliteTable(
	"summary_variable_catalog",
	{
		variableId: text("variable_id"),
		obsStat: text("obs_stat"),
		unitId: text("unit_id"),
		valueGrain: text("value_grain"),
		grain: text(),
		inputGrain: text("input_grain"),
		n: integer().notNull(),
		nPlaces: integer("n_places").notNull(),
		yFrom: integer("y_from"),
		yTo: integer("y_to"),
		nCensored: integer("n_censored").notNull(),
		nNotDetected: integer("n_not_detected").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [index("ix_summary_variable_catalog_variable").on(table.variableId)],
);

/**
 * 地点×系列単位（v1 `site_var` 相当）。`avg_zero`/`avg_lod` を両方持つ（PR-2 で
 * lod 表示に切り替える画面用に lod を、既存比較用に zero も残す——ADR-0009 決定4）。
 */
export const summaryPlaceVariable = sqliteTable(
	"summary_place_variable",
	{
		placeId: text("place_id"),
		variableId: text("variable_id"),
		obsStat: text("obs_stat"),
		unitId: text("unit_id"),
		valueGrain: text("value_grain"),
		grain: text(),
		inputGrain: text("input_grain"),
		n: integer().notNull(),
		yFrom: integer("y_from"),
		yTo: integer("y_to"),
		avgZero: real("avg_zero"),
		avgLod: real("avg_lod"),
		nCensored: integer("n_censored").notNull(),
		nNotDetected: integer("n_not_detected").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [
		index("ix_summary_place_variable_place").on(table.placeId),
		index("ix_summary_place_variable_variable").on(table.variableId),
	],
);

/**
 * 種カタログ（Issue #48 PR-3a、v1 `species2`/`mesh_species` の後継）。
 * `occurrence_agg` を「grid01・年族（year/survey_period）」に絞って `taxon_id`
 * 単位で事前集計した形——`taxon_id IS NULL`（分類群未解決）の行も持つ
 * （データを落とさない）。binom 束ね・表示名・レッドリスト評価との突合は
 * ここではなく問い合わせ層（PR-3b）の仕事。
 *
 * `nPlaces`（v1 `mesh_species.mesh_n` 相当。`COUNT(DISTINCT place_id)`）・
 * `nYears`（`COUNT(DISTINCT year_of_period_start)`）は `count_distinct` に
 * `expr` を使う測度（`aggregations/serving.yaml` 参照）。
 */
export const summaryTaxonCatalog = sqliteTable(
	"summary_taxon_catalog",
	{
		taxonId: text("taxon_id"),
		n: integer().notNull(),
		nRedList: integer("n_red_list").notNull(),
		nAlien: integer("n_alien").notNull(),
		nPlaces: integer("n_places").notNull(),
		yFrom: integer("y_from"),
		yTo: integer("y_to"),
		nYears: integer("n_years").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [index("ix_summary_taxon_catalog_taxon").on(table.taxonId)],
);

/**
 * 流域ロールアップ（Issue #48 PR-3a、v1 `org_watershed`/`org_watershed_year`
 * の年集計側の後継）。`occurrence_agg` を「watershed・年族（year/survey_period）」
 * に絞って `place_id` 単位で事前集計した形——`place_id IS NULL`（流域に解決
 * できない日付あり記録、ADR-0025/0026 D1）の行も持つ。画面は
 * `place_id IS NOT NULL` で絞る。
 */
export const summaryWatershedOccurrence = sqliteTable(
	"summary_watershed_occurrence",
	{
		placeId: text("place_id"),
		n: integer().notNull(),
		nRedList: integer("n_red_list").notNull(),
		nAlien: integer("n_alien").notNull(),
		nTaxa: integer("n_taxa").notNull(),
		yFrom: integer("y_from"),
		yTo: integer("y_to"),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [index("ix_summary_watershed_occurrence_place").on(table.placeId)],
);

/**
 * 以下4表は Issue #48 PR-3b（D1）で足した binom 単位（`taxon.canonical_binomial`）の
 * summary。`occurrence_agg` を `registry.sqlite` の `taxon` と結合して作る
 * （`aggregations/serving.yaml` の `join: {taxon: registry}`。v1 の「二名法キーの
 * DISTINCT」と同じ種数を出すため）。いずれも最終粒度の表で再集計しない。
 * 列は YAML の宣言（group_by＋measures）と1対1——ここを触ったら YAML と
 * `scripts/b13_build_summary.py` も合わせて直すこと。
 *
 * 種カタログ（v1 `species2` の後継）。キーは `binom`（binom が取れない taxon・
 * `taxon_id IS NULL` の行は含まない）。`taxon_group`/`class`/`family` は v1 の
 * `MAX(...)` と同じ規則。
 */
export const summarySpeciesCatalog = sqliteTable(
	"summary_species_catalog",
	{
		binom: text(),
		taxonGroup: text("taxon_group"),
		class: text(),
		family: text(),
		n: integer().notNull(),
		nLocated: integer("n_located").notNull().default(0),
		nRedList: integer("n_red_list").notNull(),
		nAlien: integer("n_alien").notNull(),
		nPlaces: integer("n_places").notNull(),
		yFrom: integer("y_from"),
		yTo: integer("y_to"),
		nYears: integer("n_years").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [index("ix_summary_species_catalog_binom").on(table.binom)],
);

/**
 * 年×分類群×出典（v1 `org_group_year` の後継）。`taxon_id` が NULL・`taxon_group` が
 * NULL のセルは `taxon_group='未判定'`。年の窓（1970〜2026）は持たない（問い合わせの
 * WHERE で掛ける）。`n_places` は grid01 の DISTINCT。
 */
export const summaryGroupYear = sqliteTable(
	"summary_group_year",
	{
		year: integer(),
		taxonGroup: text("taxon_group"),
		sourceId: text("source_id"),
		n: integer().notNull(),
		nBinom: integer("n_binom").notNull(),
		nPlaces: integer("n_places").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [index("ix_summary_group_year_year").on(table.year)],
);

/**
 * 年ごとの努力量（v1 `effort_year` の後継）。`n_inat`/`n_gbif` は持たない——n は
 * 加法なので `summary_group_year` の `source_id` 別 `SUM(n)` から正確に引ける。
 */
export const summaryEffortYear = sqliteTable(
	"summary_effort_year",
	{
		year: integer(),
		n: integer().notNull(),
		nBinom: integer("n_binom").notNull(),
		nPlaces: integer("n_places").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
);

/**
 * グリッド通年（v1 `mesh_all`＋`mesh_species` の後継）。`n`/`n_red_list` は v1
 * `mesh_all` の窓（年 1970〜2026）を焼いてある（窓外のセルだけのグリッドは n=0 で
 * 1行出る）。`n_binom`/`n_red_binom` は v1 `mesh_species` と同じく窓なし。
 */
export const summaryGridCatalog = sqliteTable(
	"summary_grid_catalog",
	{
		placeId: text("place_id"),
		n: integer().notNull(),
		nRedList: integer("n_red_list").notNull(),
		nBinom: integer("n_binom").notNull(),
		nRedBinom: integer("n_red_binom").notNull(),
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
);
