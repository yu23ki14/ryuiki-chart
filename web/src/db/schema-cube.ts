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

/**
 * 生物出現のキューブ（`organism_records` → `occurrence` → このキューブ。
 * ADR-0025 D2）。次元キー8列＋値2列（`n`/`n_red_list`）＋来歴2列の計12列。
 *
 * `region_id`/`source_id`/`grain`/`period_start`/`period_end`/`n`/`n_red_list`/
 * `built_from`/`spec_version` は NOT NULL、`place_id`/`place_kind`/`taxon_id`
 * は NULL を許容する（`scripts/b07_build_occurrence_cube.py` の
 * `_CREATE_OCCURRENCE_AGG_SQL` のまま——taxon_id が NULL のセルもデータを
 * 落とさず持つ、という同スクリプトの決定に合わせる）。
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
		builtFrom: text("built_from").notNull(),
		specVersion: text("spec_version").notNull(),
	},
	(table) => [
		index("ix_occurrence_agg_taxon_period").on(table.taxonId, table.periodStart),
		index("ix_occurrence_agg_place_period").on(table.placeId, table.periodStart),
	],
);
