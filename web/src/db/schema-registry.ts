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
 * `taxon_name` / `taxon_assessment`（ADR-0019）は Phase A では作らない
 * （Issue #48 PR-0 で `taxon_assessment`・`place_relation`・`place_watershed` を
 * 追加した。理由・列の由来は各テーブルの定義コメント参照）。
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

/**
 * region（ADR-0002。`jp-14` 等）ごとの時刻帯の語彙（Issue #32-3、ADR-0024）。手書きの正は
 * `registry/region.yaml`。観測の日時は時刻帯なしのローカル時刻で持ち（ADR-0024）、その
 * 「ローカル」の意味（IANA 名と UTC オフセット）をここから引く。
 */
export const region = sqliteTable("region", {
	regionId: text("region_id").primaryKey(),
	nameJa: text("name_ja").notNull(),
	tzName: text("tz_name").notNull(),
	utcOffset: text("utc_offset").notNull(),
	evidence: text(),
});

/** 単位。symbol は人間向けの原表記、ucum は UCUM 準拠のコード。 */
export const unit = sqliteTable("unit", {
	unitId: text("unit_id").primaryKey(),
	symbol: text(),
	ucum: text(),
	nameJa: text("name_ja"),
	quantityKind: text("quantity_kind"),
	/** 正準単位（ADR-0023、Issue #31）。換算しない単位は自分自身。 */
	// registry.sqlite 側は NOT NULL（build_unit_variable.py が全行に明示させる）。D1 側は
	// D1 の既存テーブルへの ALTER TABLE ADD COLUMN は NOT NULL かつ既定値なしを許さない（SQLite の制約）ため
	// nullable。値は常に埋まる（seed が registry.sqlite からそのまま写す）。
	canonicalUnitId: text("canonical_unit_id"),
	/** 値_正準 = 値_出典 × scale。線形のみ（オフセット換算は扱わない）。 */
	scaleToCanonical: real("scale_to_canonical").notNull().default(1),
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
 * 出典表記 → 正準 variable の対応。**エイリアスは「出典 × 表記」で解決する**
 * （ADR-0010 決定1）。`alias` が v1 の `measurements.variable` /
 * `sensor_timeseries.datastream` の生の文字列、`dataset` はそのどちらのテーブルの
 * 表記か（`measurements` / `sensor_timeseries`。以前の `source_scope` を改名した。
 * 「出典スコープ」を名乗りながらテーブル名だけを持っていたのが
 * docs/plans/PHASE_B_INTAKE.md #1 の中身なので、実態に合わせて改名した）、
 * `sourceId` は v1 `source_registry.source_id`（空 = 出典未記録。`is_synthetic=1` の行）。
 *
 * 同じ `(dataset, alias)` でも `sourceId` が違えば `grain`/`stat` が異なりうる
 * （例: 環境省公共用水域水質の同じ項目名でも、年度代表値の出典と検体値の出典で
 * 粒度が違う）。1つの `(dataset, alias, sourceId)` の組につき1行（PK は
 * 別に自動採番の id を持つ。公開 ID ではないので ADR-0004「ID は不変」の対象外）。
 * `sourceId` は `source_registry`/`source_edition`（ADR-0005）が入る Phase C で
 * `source_edition_id` に置き換わる**暫定形**（docs/plans/PHASE_B_INTAKE.md #9 と
 * 同じ性質の暫定接続点）。
 *
 * `grain`/`stat` は一次資料調査（docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md）済みで、
 * `(dataset, alias, sourceId)` の組ごとに固定1値に決まる（`atsugi_river_water_quality`
 * の「日付書式の混在」も統計量としては全期間 `mean`/`day` で確定するため、行ごとに
 * 値が変わる宣言的な列は持たない）。
 *
 * 逆引きは `alias` と `variable_id` の両方から行うのでどちらにも索引を張る。
 * `(dataset, alias, sourceId)` はビルド時の一意性検証（`build_unit_variable.py`）と
 * 完全一致の読み出し（`resolveAliasForSource`）に使うので複合索引も張る。
 */
export const variableAlias = sqliteTable("variable_alias", {
	id: integer().primaryKey({ autoIncrement: true }),
	alias: text().notNull(),
	dataset: text(),
	sourceId: text("source_id"),
	variableId: text("variable_id"),
	unitId: text("unit_id"),
	stat: text(),
	grain: text(),
	/** unit_id の根拠: 'source'（原本が報告）/ 'registry'（原本に単位記載が無くレジストリが補った）。 */
	unitBasis: text("unit_basis"),
	note: text(),
},
(table) => [
	index("ix_variable_alias_alias").on(table.alias),
	index("ix_variable_alias_variable").on(table.variableId),
	index("ix_variable_alias_dataset_alias_source").on(table.dataset, table.alias, table.sourceId),
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
 * 空間単位どうしの関係（ADR-0006・ADR-0022）。Phase B `phase-b/region-scope` で新設。
 * 「地点 -> ゾーン」（`parent_id`=ゾーンの place_id, `child_id`=地点の place_id,
 * `relation`='within'）と「地点 -> 流域」（`sites.watershed` 由来）の2種類を持つ
 * （`scripts/registry/build_place.py`「place_relation」節）。`fraction` は
 * NOT NULL とし、全体を含む関係には 1.0 を入れる。`(parent_id, child_id, relation)`
 * の一意性は DDL の UNIQUE 制約ではなく `scripts/r01_build_registry.py` 側の
 * Python 表明で検証する（`registry.sqlite` と同じ流儀）。
 *
 * Phase A/B 当初は「消費者がまだ無い」として D1 には載せていなかったが、
 * Issue #48（PR-0）でゾーン・流域の JOIN が要る消費者ができたため追加した。
 */
export const placeRelation = sqliteTable("place_relation", {
	id: integer().primaryKey({ autoIncrement: true }),
	parentId: text("parent_id").notNull(),
	childId: text("child_id").notNull(),
	relation: text().notNull(),
	fraction: real().notNull(),
	basis: text(),
},
(table) => [
	index("ix_place_relation_parent").on(table.parentId),
	index("ix_place_relation_child").on(table.childId),
]);

/**
 * `place_kind='watershed'` だけが持つ属性サテライト（旧 `derived.watershed_meta`
 * の残り4列。`scripts/registry/build_place.py`「watershed」節）。1 place_id
 * につき高々1行（1:1）。`main_rivers` は主要河川が無い流域向けの空文字列を
 * そのまま持つ（NULL に丸めない）。Issue #48（PR-0）で D1 に追加。
 */
export const placeWatershed = sqliteTable("place_watershed", {
	placeId: text("place_id").primaryKey(),
	waterSystemCode: text("water_system_code"),
	waterSystemCategory: text("water_system_category"),
	mainRivers: text("main_rivers"),
	dataYear: integer("data_year"),
});

/**
 * 分類群レジストリ（ADR-0019。taxon_id の名前空間分割・分類補完は Phase B
 * `phase-b/occurrence-registry`。決定と理由の正は ADR-0019 の日付付き追記、
 * 実測の正は `docs/plans/PHASE_B_OCCURRENCE.md`——ここには実装に必要な最小限だけ書く）。
 *
 * `taxon_id` は出典ごとに名前空間を分ける: GBIF 由来は `common:taxon:gbif.<GBIFのtaxonKey>`、
 * iNaturalist 由来は `common:taxon:inat.<iNatのtaxon.id>`（GBIF の taxonKey とは無関係な
 * 別の数値空間。以前は両方を `gbif.<key>` に混ぜて9件衝突していた——詳細は ADR-0019）。
 * `taxa`（v1）由来で GBIF 未照合のものは `common:taxon:ryuiki-taxa.<学名をスラッグ化したもの>`。
 * `gbif_taxon_key` 列は本物の GBIF taxonKey のときだけ埋める（iNat 由来行は常に NULL。
 * 理由は `scripts/registry/common.py` の `taxon_id_inat()` docstring）。
 *
 * `status` は `accepted` / `unresolved` / `needs_review`（分類の多数決が不確か
 * ——同数、または属が複数classにまたがる——な taxon。accepted/unresolved どちらの
 * 行にも起こりうる。実測件数は `docs/plans/PHASE_B_OCCURRENCE.md`）の3値で、
 * `synonym` は無い。`accepted_taxon_id` は現状すべて NULL（`docs/plans/PHASE_B_INTAKE.md`
 * §8。`c24_taxon_crosswalk.py` の `accepted_scientific_name` を誤用しないこと）。
 *
 * `kingdom`/`phylum`/`order`/`classification_basis` は `scripts/schema_registry.sql` の
 * `registry.sqlite` 側にはあるが、意図的にここ（D1 側）には載せていない
 * （オーナー決定。`registry/README.md`「taxon の名前空間分割と分類補完」参照）。
 * `canonical_binomial`/`class`/`family`/`taxon_group` は Issue #48（PR-0）で
 * D1 の消費者ができたため追加した。
 * `status='needs_review'` は既存の `status` 列にそのまま乗るので、D1 側の
 * スキーマ変更なしで既にシードされている。
 *
 * `vernacularNameEn`/`vernacularJaBasis`（Issue #48 PR-3a、D4）:
 * `vernacularNameEn` は `organism_records.vernacular_name` のうちラテン文字だけの
 * 値を (名前空間, taxon_key) ごとに最頻値で選んだもの（gbif/inat 由来の行にだけ
 * 付く）。「英名」ではなく「ラテン文字の俗名」であることに注意（ローマ字表記・
 * 属の仮名も入りうる。`registry/README.md` 参照）。`vernacularJaBasis` は
 * `vernacularNameJa` の出処（`override`/`taxa`/`records`）——`records` は
 * `vernacularNameJa` が NULL の行にだけ、記録由来の非ラテン文字の最頻値で
 * 補完したことを示す（既存の値は1件も変えない。`scripts/registry/build_taxon.py`
 * モジュール docstring 参照）。
 */
export const taxon = sqliteTable("taxon", {
	taxonId: text("taxon_id").primaryKey(),
	scientificName: text("scientific_name"),
	canonicalBinomial: text("canonical_binomial"),
	rank: text(),
	class: text(),
	family: text(),
	taxonGroup: text("taxon_group"),
	gbifTaxonKey: text("gbif_taxon_key"),
	vernacularNameJa: text("vernacular_name_ja"),
	vernacularNameEn: text("vernacular_name_en"),
	vernacularJaBasis: text("vernacular_ja_basis"),
	status: text(),
	acceptedTaxonId: text("accepted_taxon_id"),
},
(table) => [
	index("ix_taxon_gbif_key").on(table.gbifTaxonKey),
	index("ix_taxon_binomial").on(table.canonicalBinomial),
]);

/**
 * 版ごとの分類群の評価（ADR-0019 の最小形。P-2。v1 の `redlist_assessments`
 * 〔3版〕と `taxa.ias_category` 由来の外来種評価を、同じ「あるリストがある
 * 分類群に付けた評価」という構造に統合したもの。`scripts/registry/
 * build_taxon_assessment.py`）。`list_id` は `registry/taxon/assessment_list.yaml`
 * のコードリスト。`category_code`/`prev_category_code` は正規化したコード
 * （`list_id='moe_ias_2015'` の行は専用のコードリストを持たないため常に NULL）。
 * `*_raw` 列は原表記を無加工で残す。`taxon_id` は解決できた行だけ埋める
 * （NULL もありうる）。`vernacular_name_ja_resolved` は `moe_ias_2015` の行だけが
 * 持つ、v1 の `taxa.vernacular_name_ja`（3出典をまたいだ畳み込み済みの和名）相当。
 *
 * Phase A/B 当初は D1 の消費者が無いとして見送っていたが、Issue #48（PR-0）で
 * D1 に追加した。`in_scope`（Issue #48 PR-3a、D7）は
 * `registry/taxon/assessment_scope_exclusions.yaml` の除外7種を `(list_id,
 * scientific_name_raw の二名法)` で機械的に一致させて 0、他の全行を 1 にした
 * 可視化列——**このテーブル自体は行を1件も除外しない**（`scientific_name_raw`
 * の429行＋2,884行はそのまま。`scripts/registry/build_taxon_assessment.py`
 * モジュール docstring「除外7種」「`in_scope`」参照）。
 */
export const taxonAssessment = sqliteTable("taxon_assessment", {
	assessmentId: text("assessment_id").primaryKey(),
	listId: text("list_id").notNull(),
	listYear: integer("list_year"),
	taxonId: text("taxon_id"),
	scientificNameRaw: text("scientific_name_raw"),
	vernacularNameJaRaw: text("vernacular_name_ja_raw"),
	vernacularNameJaResolved: text("vernacular_name_ja_resolved"),
	taxonGroupJa: text("taxon_group_ja"),
	taxonSubgroupJa: text("taxon_subgroup_ja"),
	familyJa: text("family_ja"),
	categoryRaw: text("category_raw"),
	categoryCode: text("category_code"),
	prevCategoryRaw: text("prev_category_raw"),
	prevCategoryCode: text("prev_category_code"),
	nationalCategoryRaw: text("national_category_raw"),
	origin: text(),
	sourceId: text("source_id"),
	inScope: integer("in_scope"),
	/**
	 * `binom_of(scientific_name_raw)`（二名法。取れなければ NULL。Issue #48 PR-3b §2.4）。
	 * IAS は `taxon_id` が 346/429 しか解決しないので、v1 の `ias_species` 相当は
	 * この列で結合する。
	 */
	binom: text(),
	/** `in_scope=0` の理由コード（`domestic_origin` / `subspecies_binomial_contraction`、重なれば `,` 連結）。Issue #34。 */
	scopeReason: text("scope_reason"),
},
(table) => [
	index("ix_taxon_assessment_list").on(table.listId),
	index("ix_taxon_assessment_taxon").on(table.taxonId),
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
 * `scope_kind` は ADR-0013 の6種（`variable`/`place`/`source_edition`/`observation_set`/`dataset`/`taxon`）。
 * `scope_ref` は ID か `キー=値` の選択式で、照合は完全一致（宣言は `registry/caveat_scope.yaml`。
 * Issue #35 で旧語彙の `table`/`table_prefix`/`cell`/`cell_table` 等から移した）。
 * 「渡された参照のうちどれを先頭に出すか」という**優先規則**は `scope_kind` の値では表さず、
 * `priority` 列（既定0・大きいほど優先）が持つ。読み出し側は
 * `(priority, 呼び出し側が渡した参照の順序, sort_order)` の一般規則1本で済む。
 * `sort_order` は「同じ (scope_kind, scope_ref) の中での宣言順」だけを表す。
 * 詳細は `scripts/registry/build_caveat.py` の docstring。
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
