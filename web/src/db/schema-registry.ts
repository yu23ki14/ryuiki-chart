/**
 * 語彙レジストリ（Phase A, docs/plans/PHASE_A.md §A-1）のスキーマ定義。
 *
 * unit / variable / variable_alias / place / place_source_ref / taxon / caveat / caveat_scope。
 * （計画時点は caveat 単体で7テーブルの想定だったが、A-5 実装時に caveat/caveat_scope の
 * 2テーブルに分けた。理由は caveat の定義コメントを参照）
 * ID 規約は docs/adr/0004-identifiers.md。中身（行）は
 * `scripts/r01_build_registry.py`（→ scripts/registry/build_*.py）が
 * 読み取り専用の原本（ryuiki.sqlite / cells.sqlite / derived.sqlite）から
 * `data/db/registry.sqlite` として生成し、`seed-d1-local.mjs` の4本目の
 * ソースとして他の3ファイルと同じ経路で D1 に乗る。
 *
 * `taxon_name` / `taxon_assessment`（ADR-0019）は Phase A では作らない。
 *
 * 既存の `schema.ts`（v1・69テーブル）とはあえてファイルを分けてある。
 * 「既存テーブルの定義には一切触れていない」ことを diff だけで機械的に示すため
 * （schema.ts 側の差分を 0 行にする）。drizzle-kit にはどちらも
 * `drizzle.config.ts` の `schema` 配列経由で読ませている。
 *
 * このファイルを編集したら `npm run db:generate` でマイグレーションを作り直す。
 * drizzle/migrations/*.sql を直接書き換えない。
 */
import { sqliteTable, text, integer, real, index } from "drizzle-orm/sqlite-core";

/** 単位。symbol は人間向けの原表記、ucum は UCUM 準拠のコード。 */
export const unit = sqliteTable("unit", {
	unitId: text("unit_id").primaryKey(),
	symbol: text(),
	ucum: text(),
	nameJa: text("name_ja"),
	quantityKind: text("quantity_kind"),
});

/**
 * 正準の指標。`measurements.variable` / `sensor_timeseries.datastream` の
 * 出典別名は variable_alias 側に持ち、ここには名前から単位・粒度・統計量を
 * 剥がした後の正準形だけを置く（ADR-0010）。
 */
export const variable = sqliteTable("variable", {
	variableId: text("variable_id").primaryKey(),
	code: text(),
	nameJa: text("name_ja"),
	nameEn: text("name_en"),
	theme: text(),
	unitId: text("unit_id"),
	valueType: text("value_type"),
	defaultStat: text("default_stat"),
	higherIsWorse: integer("higher_is_worse"),
	descriptionJa: text("description_ja"),
	status: text(),
});

/**
 * 出典表記 → 正準 variable の対応。`alias` が v1 の `measurements.variable` /
 * `sensor_timeseries.datastream` の生の文字列。1エイリアスにつき1行（PK は
 * 別に自動採番の id を持つ。alias 自体は出典をまたいで再利用されうるため
 * 一意にならない）。逆引きは `alias` と `variable_id` の両方から行うのでどちらにも
 * 索引を張る。
 */
export const variableAlias = sqliteTable("variable_alias", {
	id: integer().primaryKey({ autoIncrement: true }),
	alias: text().notNull(),
	sourceScope: text("source_scope"),
	variableId: text("variable_id"),
	unitId: text("unit_id"),
	stat: text(),
	grain: text(),
	note: text(),
},
(table) => [
	index("ix_variable_alias_alias").on(table.alias),
	index("ix_variable_alias_variable").on(table.variableId),
]);

/**
 * 空間単位（ADR-0006）。Phase A で登録するのは集計軸として実在するものだけ
 * （site / watershed / grid01 / zone）。`place_relation` と `geometry_ref` は
 * Phase A では持たない（点→place の解決も含め Phase B）。
 *
 * `grid01` は当初 `mesh3`（3次メッシュ = 30秒×45秒）の想定だったが、実装時に
 * `mesh_all` の実体が3次メッシュではなく独自の 0.01 度グリッドだと分かったため改名した。
 * ADR-0006 のコードリストにまだ `grid01` は無い（docs/plans/PHASE_B_INTAKE.md §11）。
 */
export const place = sqliteTable("place", {
	placeId: text("place_id").primaryKey(),
	regionId: text("region_id"),
	placeKind: text("place_kind"),
	nameJa: text("name_ja"),
	lat: real(),
	lon: real(),
	elevationM: real("elevation_m"),
	areaKm2: real("area_km2"),
	definitionRef: text("definition_ref"),
	status: text(),
},
(table) => [
	index("ix_place_kind").on(table.placeKind),
]);

/**
 * v1 の出典側識別子（`sites.site_id` / `watershed_meta.watershed_id` /
 * `mlat,mlon` 等）から place への対応。「v1 を動かさずに並走させる」ための
 * 接続点（PHASE_A.md §A-3）。`external_key` からの逆引きが主な引き方。
 */
export const placeSourceRef = sqliteTable("place_source_ref", {
	id: integer().primaryKey({ autoIncrement: true }),
	placeId: text("place_id"),
	externalKey: text("external_key"),
	sourceId: text("source_id"),
},
(table) => [
	index("ix_place_source_ref_external").on(table.externalKey),
	index("ix_place_source_ref_place").on(table.placeId),
]);

/**
 * 分類群レジストリ（ADR-0019）。GBIF 由来は `taxon_id = common:taxon:gbif.<key>`、
 * `taxa`（v1）由来で GBIF 未照合のものは `common:taxon:ryuiki-taxa.<学名をスラッグ化したもの>`
 * （`taxa` の主キーではない。学名を小文字化・記号を `%` エスケープして作った ID）。
 * 現状の `status` は `accepted` / `unresolved` の2値のみで、`synonym` は無い。
 * `accepted_taxon_id` は現状すべて NULL。将来 `status='synonym'` の行を持たせて
 * 正の taxon を指させるための列（ADR-0004 規約2: ID は不変、実体が変わったら
 * 新 ID を作り旧 ID は残す）で、まだ埋めていない。
 * 上流の `scripts/c24_taxon_crosswalk.py` の `accepted_scientific_name` 列は
 * GBIF の `acceptedUsageKey`（受理名）を引いたものではなく、一致したノード自身の学名を
 * 転記しているだけだったと判明している。列名と実態が食い違いやすい箇所なので、
 * `accepted_taxon_id` を埋めるときは誤用しないこと（docs/plans/PHASE_B_INTAKE.md §8）。
 */
export const taxon = sqliteTable("taxon", {
	taxonId: text("taxon_id").primaryKey(),
	scientificName: text("scientific_name"),
	rank: text(),
	gbifTaxonKey: text("gbif_taxon_key"),
	vernacularNameJa: text("vernacular_name_ja"),
	status: text(),
	acceptedTaxonId: text("accepted_taxon_id"),
},
(table) => [
	index("ix_taxon_gbif_key").on(table.gbifTaxonKey),
]);

/**
 * 注意事項（ADR-0013）。`caveat_id` は `web/src/lib/ai/caveats.ts` が今返している
 * キー文字列をそのまま使う（`common:caveat:<key>`）。`cells.notes` 由来は
 * `common:caveat:cells.<note の主キー>`。
 *
 * PHASE_A.md §A-5 の計画では `caveat` 単体に `scope_kind`/`scope_ref` を持たせる
 * 7列構成だったが、実装時に「1つの注記が複数のテーブルに掛かる」
 * （例: `censored` は `measurements`/`meas_year`/`meas_month` など9テーブルに掛かる）
 * ことが分かり、`caveat_id` を主キーにしたままでは 1:N を表せなかった。
 * そのため `caveat` は注記そのもの（このテーブル）に絞り、スコープは
 * 下の `caveatScope` に切り出した（計画の7テーブル→8テーブルの逸脱。
 * 理由の詳細は `scripts/registry/build_caveat.py` の docstring）。
 */
export const caveat = sqliteTable("caveat", {
	caveatId: text("caveat_id").primaryKey(),
	severity: text(),
	kind: text(),
	titleJa: text("title_ja"),
	bodyJa: text("body_ja"),
	quote: text(),
});

/**
 * `caveat` が掛かる範囲。1注記に対して複数行になりうる（1:N）。
 * `scope_kind` は**一致方法だけ**を表す（`table` / `table_prefix` / `cell` / `cell_table`）。
 * 「渡されたテーブルのうちどれを先頭に出すか」という**優先規則**は `scope_kind` の値では
 * 表さず、`priority` 列（既定0・大きいほど優先）が持つ。以前は `scope_kind='table_synthetic'`
 * という専用の一致方法を作ってこの優先規則を表していたが、優先度は本来「一致方法」ではないため
 * `caveatsForTables()` 側に特殊分岐が必要になり、実際にバグ（複数 synthetic テーブルのうち
 * 最初の1件しか注記を拾わない）を生んだ。`priority` を切り出したことで、読み出し側は
 * `(priority, 呼び出し側が渡したテーブルの順序, sort_order)` の一般規則1本で済む。
 * `sort_order` は「同じ (scope_kind, scope_ref) の中での並び」だけを表し、scope 同士の並びは
 * 呼び出し側が渡すテーブル名の順序に従う。詳細は `scripts/registry/build_caveat.py` の docstring。
 */
export const caveatScope = sqliteTable("caveat_scope", {
	id: integer().primaryKey({ autoIncrement: true }),
	caveatId: text("caveat_id"),
	scopeKind: text("scope_kind"),
	scopeRef: text("scope_ref"),
	sortOrder: integer("sort_order"),
	priority: integer().notNull().default(0),
},
(table) => [
	index("ix_caveat_scope_scope").on(table.scopeKind, table.scopeRef),
	index("ix_caveat_scope_caveat").on(table.caveatId),
]);
