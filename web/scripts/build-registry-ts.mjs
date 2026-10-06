#!/usr/bin/env node
/**
 * `web/src/lib/registry/generated.ts`（サーバ用）と
 * `web/src/lib/registry/generated-client.ts`（クライアント安全）を作る
 * （docs/plans/PHASE_A.md §A-7）。
 *
 * 読み取り元:
 *   - data/db/registry.sqlite（scripts/r01_build_registry.py が作る）の
 *     unit / variable / variable_alias / caveat / caveat_scope
 *   - registry/taxon/vernacular_ja.csv（旧 domain.ts の NAME_JA 54件＋PR-3b D4 の上書き9件の台帳）
 *   - registry/place/zone.yaml（旧 domain.ts の ZONE_INFO。registry.sqlite を経由せず
 *     直接読む。vernacular_ja.csv と同じ扱い）
 *   - registry/taxon/redlist_category.yaml・assessment_list.yaml（Issue #48 PR-3b。
 *     `REDLIST_CATEGORY`・`ASSESSMENT_LIST`。D1 に表は足さず、`taxon_assessment` の
 *     `category_code`/`list_id` をこの定数で引く。zone.yaml と同じ直読み）
 *
 * ## 2ファイルに分けている理由（レビュー指摘・code-review #4）
 *
 * 以前は1本の `generated.ts` に unit(28) / variable(85, description_ja込み) /
 * variable_alias(117, stat/grain/unitId込み) / caveat(14) / caveat_scope(約40) /
 * vernacular(54) を全部載せていた。旧 `domain.ts`（8つの client component から import
 * される）がこれを丸ごと import していたため、クライアントバンドルに
 * GENERATED_VARIABLES 22.7KB + GENERATED_VARIABLE_ALIASES 20.8KB が乗っていた
 * （domain.ts が実際に使うのは、そこから機械的に再構成した4つの派生ラベル表
 * だけなのに）。
 *
 * そのため:
 *   - `generated.ts`（サーバ専用）: unit / variable / variable_alias の生テーブル。
 *     `web/src/lib/registry/lookup.ts`（server-onlyではないが D1/大きいテーブルに
 *     依存するため、クライアントコンポーネントから import しないこと）が使う。
 *   - `generated-client.ts`（クライアント安全）: VARIABLE_SHORT / VARIABLE_NOTE /
 *     HIGHER_IS_WORSE / VARIABLE_UNIT_FALLBACK / NAME_JA（旧 domain.ts が実際に使っていた、
 *     派生済みの4+1個の Record）、ZONE_INFO・CaveatKey（Phase B で旧 domain.ts から
 *     移設。docs/plans/PHASE_B_INTAKE.md #6）と、caveat 18件・caveat_scope
 *     （小さいので両方に置いて問題ない）。生の variable / alias テーブルはここには載せない。
 *     VARIABLE_LABEL（variable_id キー。Issue #48 PR-2、docs/plans/V2_SERVING_PR2.md §5）
 *     は上記5個とは別枠——alias キー版を置き換えるのではなく並存する（PR-5 で
 *     alias キー版を落とすまで両方生きる）。
 *
 * 派生値の組み立てロジック（元は domain.ts が実行時に primaryAlias() 経由で
 * やっていた「代表エイリアスの選定」）は `web/scripts/lib/registry-codegen.mjs`
 * に移した（`domain.ts` の「代表エイリアスから機械的に再構成する」性質はそのまま、
 * 再構成する場所がビルド時に変わっただけ）。
 *
 * 再生成:
 *   cd web && npm run build:registry:ts
 *
 * 直接編集しない。中身を直したいときは registry/*.yaml / registry/*.csv /
 * scripts/registry/build_*.py / web/scripts/lib/registry-codegen.mjs 側を直してから、
 * このコマンドで作り直す。
 *
 * 入出力パスは環境変数で上書きできる（既定は下記の固定値）。
 * `web/src/lib/registry/generated.test.ts`（陳腐化ガード）が、このスクリプトの
 * ソースを文字列で書き換える代わりに、実物をこのまま一時ディレクトリ向けに実行して
 * 生成物の差分が無いことを確認するために使う（/simplify 修正6）:
 *   - RYUIKI_REGISTRY_DB: 入力の registry.sqlite
 *   - RYUIKI_VERNACULAR_CSV: 入力の vernacular_ja.csv
 *   - RYUIKI_ZONE_YAML: 入力の zone.yaml
 *   - RYUIKI_REDLIST_CATEGORY_YAML / RYUIKI_ASSESSMENT_LIST_YAML: 入力の
 *     registry/taxon/redlist_category.yaml / assessment_list.yaml
 *   - RYUIKI_REGISTRY_TS_OUT_SERVER / RYUIKI_REGISTRY_TS_OUT_CLIENT / RYUIKI_REGISTRY_TS_OUT_ID_MAP: 出力先
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { load as loadYaml } from "js-yaml";
import { parseCsvRecords } from "./lib/csv.mjs";
import { buildClientVariableMaps, buildVariableLabelMap } from "./lib/registry-codegen.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const REPO = path.resolve(WEB, "..");
const REGISTRY_DB = process.env.RYUIKI_REGISTRY_DB ?? path.join(REPO, "data", "db", "registry.sqlite");
const VERNACULAR_CSV =
  process.env.RYUIKI_VERNACULAR_CSV ?? path.join(REPO, "registry", "taxon", "vernacular_ja.csv");
const ZONE_YAML = process.env.RYUIKI_ZONE_YAML ?? path.join(REPO, "registry", "place", "zone.yaml");
const REDLIST_CATEGORY_YAML =
  process.env.RYUIKI_REDLIST_CATEGORY_YAML ?? path.join(REPO, "registry", "taxon", "redlist_category.yaml");
const ASSESSMENT_LIST_YAML =
  process.env.RYUIKI_ASSESSMENT_LIST_YAML ?? path.join(REPO, "registry", "taxon", "assessment_list.yaml");
const OUT_SERVER =
  process.env.RYUIKI_REGISTRY_TS_OUT_SERVER ?? path.join(WEB, "src", "lib", "registry", "generated.ts");
const OUT_CLIENT =
  process.env.RYUIKI_REGISTRY_TS_OUT_CLIENT ?? path.join(WEB, "src", "lib", "registry", "generated-client.ts");
const OUT_ID_MAP =
  process.env.RYUIKI_REGISTRY_TS_OUT_ID_MAP ?? path.join(WEB, "src", "lib", "registry", "generated-id-map.ts");
const MANIFESTS_DIR = process.env.RYUIKI_MANIFESTS_DIR ?? path.join(REPO, "manifests");
const SOURCE_COMMITTED = path.join(WEB, "src", "lib", "registry", "generated-source.ts");
const OUT_SOURCE =
  process.env.RYUIKI_REGISTRY_TS_OUT_SOURCE ?? path.join(WEB, "src", "lib", "registry", "generated-source.ts");

/** 入力ファイルが無ければヒントを添えて即座に落ちる（3つの入力（DB・CSV・YAML）で共通化）。 */
function requireFile(filePath, label, hint) {
  if (fs.existsSync(filePath)) return;
  console.error(`${label}が無い: ${filePath}${hint ? `\n${hint}` : ""}`);
  process.exit(1);
}
requireFile(
  REGISTRY_DB,
  "registry.sqlite",
  "先に `cd web && npm run build:registry`（scripts/r01_build_registry.py）で作る。",
);
requireFile(VERNACULAR_CSV, "和名台帳");
requireFile(ZONE_YAML, "zone.yaml");
requireFile(REDLIST_CATEGORY_YAML, "redlist_category.yaml");
requireFile(ASSESSMENT_LIST_YAML, "assessment_list.yaml");

// CSV パーサ（引用符・引用符内カンマ・引用符内改行・""エスケープ対応、ヘッダ検証つき）は
// `./lib/csv.mjs` に共通化した（削除済みの `build-geo.mjs` の手書きパーサと同じアルゴリズムの
// 再実装だったため。/simplify 修正3）。

const db = new Database(REGISTRY_DB, { readonly: true });

/* ------------------------------------------------------------------ */
/* 読み取り                                                            */
/* ------------------------------------------------------------------ */

const units = db
  .prepare(`SELECT unit_id, symbol, ucum, name_ja, quantity_kind, canonical_unit_id, scale_to_canonical FROM unit ORDER BY unit_id`)
  .all()
  .map((r) => ({
    unitId: r.unit_id,
    symbol: r.symbol,
    ucum: r.ucum,
    nameJa: r.name_ja,
    quantityKind: r.quantity_kind,
    canonicalUnitId: r.canonical_unit_id,
    scaleToCanonical: r.scale_to_canonical,
  }));

const variables = db
  .prepare(
    `SELECT variable_id, code, name_ja, name_en, theme, unit_id, value_type, default_stat,
            higher_is_worse, description_ja, status
     FROM variable ORDER BY variable_id`,
  )
  .all()
  .map((r) => ({
    variableId: r.variable_id,
    code: r.code,
    nameJa: r.name_ja,
    nameEn: r.name_en,
    theme: r.theme,
    unitId: r.unit_id,
    valueType: r.value_type,
    defaultStat: r.default_stat,
    higherIsWorse: r.higher_is_worse === null ? null : r.higher_is_worse !== 0,
    descriptionJa: r.description_ja,
    status: r.status,
  }));

const variableAliases = db
  .prepare(
    `SELECT alias, dataset, source_id, variable_id, unit_id, stat, grain, unit_basis, edition_key
     FROM variable_alias ORDER BY id`,
  )
  .all()
  .map((r) => ({
    alias: r.alias,
    dataset: r.dataset,
    sourceId: r.source_id,
    variableId: r.variable_id,
    unitId: r.unit_id,
    stat: r.stat || null,
    grain: r.grain,
    unitBasis: r.unit_basis || null,
    editionKey: r.edition_key || null,
  }));

// caveat_scope.scope_kind の語彙は registry/caveat_scope.yaml の `vocabulary`（ADR-0013 の6種）を
// 読む（二重管理しない。Issue #35）。`CaveatScopeKind` 型もここから生成する。
// cells.notes 由来（common:caveat:cells.*）の scope は生成物に含めない（下の WHERE 句。
// 以前は scope_kind で除外していたが、語彙を ADR に寄せたので caveat_id で除く）。
const CAVEAT_SCOPE_YAML =
  process.env.RYUIKI_CAVEAT_SCOPE_YAML ?? path.join(REPO, "registry", "caveat_scope.yaml");
requireFile(CAVEAT_SCOPE_YAML, "caveat_scope.yaml");
const CAVEAT_SCOPE_KINDS = loadYaml(fs.readFileSync(CAVEAT_SCOPE_YAML, "utf-8")).vocabulary;
if (!Array.isArray(CAVEAT_SCOPE_KINDS) || CAVEAT_SCOPE_KINDS.length === 0) {
  throw new Error("registry/caveat_scope.yaml の vocabulary が空");
}

// cells.notes 由来（common:caveat:cells.*）は除く。18件のみ。
const CAVEAT_ID_PREFIX = "common:caveat:";
const CELLS_PREFIX = `${CAVEAT_ID_PREFIX}cells.`;
const caveats = db
  .prepare(
    `SELECT caveat_id, severity, kind, body_ja FROM caveat
     WHERE caveat_id NOT LIKE '${CELLS_PREFIX}%' ORDER BY caveat_id`,
  )
  .all()
  .map((r) => ({
    key: r.caveat_id.slice(CAVEAT_ID_PREFIX.length),
    severity: r.severity,
    kind: r.kind,
    bodyJa: r.body_ja,
  }));

const caveatScopeKindList = CAVEAT_SCOPE_KINDS.map((k) => `'${k}'`).join(", ");
const caveatScope = db
  .prepare(
    `SELECT caveat_id, scope_kind, scope_ref, sort_order, priority FROM caveat_scope
     WHERE scope_kind IN (${caveatScopeKindList}) AND caveat_id NOT LIKE '${CELLS_PREFIX}%'
     ORDER BY scope_kind, scope_ref, sort_order`,
  )
  .all()
  .map((r) => ({
    scopeKind: r.scope_kind,
    scopeRef: r.scope_ref,
    caveatKey: r.caveat_id.slice(CAVEAT_ID_PREFIX.length),
    sortOrder: r.sort_order,
    priority: r.priority,
  }));

const vernacular = parseCsvRecords(fs.readFileSync(VERNACULAR_CSV, "utf-8"), [
  "scientific_name",
  "vernacular_name_ja",
  "source",
]).map((r) => ({
  scientificName: r.scientific_name,
  vernacularNameJa: r.vernacular_name_ja,
}));

// registry/place/zone.yaml を直接読む（registry.sqlite を経由しない。vernacular_ja.csv と
// 同じ扱い）。scripts/registry/build_place.py も同じファイルを読むが、あちらは
// condition_ja（不等号表記、definition_ref の一文に埋め込む）を使い、こちらは
// ui_condition_ja（画面・AIツール向けの短い日本語表記、旧 domain.ts の ZONE_INFO.cond）を
// 使う。用途が違う別々の列なので統合しない（zone.yaml のコメント参照）。
const zoneRows = loadYaml(fs.readFileSync(ZONE_YAML, "utf-8"));
{
  const seenZones = new Set();
  for (const r of zoneRows) {
    if (seenZones.has(r.zone)) {
      throw new Error(`registry/place/zone.yaml の zone が重複している: ${r.zone}`);
    }
    seenZones.add(r.zone);
    if (!r.ui_condition_ja) {
      throw new Error(`registry/place/zone.yaml の zone=${r.zone} に ui_condition_ja が無い`);
    }
  }
}
// region（時刻帯の語彙。Issue #32-3、ADR-0024）。registry.sqlite の `region` 表（手書きの正は
// registry/region.yaml）から作る。応答封筒（ADR-0014）が `regionTimeZone()` で引く。
const regionTime = db
  .prepare(`SELECT region_id, tz_name, utc_offset FROM region ORDER BY region_id`)
  .all()
  .map((r) => ({ regionId: r.region_id, tzName: r.tz_name, utcOffset: r.utc_offset }));

const zoneInfo = zoneRows
  .map((r) => ({ zone: r.zone, label: r.name_ja, cond: r.ui_condition_ja }))
  .sort((a, b) => a.zone - b.zone);

// レッドリストのカテゴリー（code -> 表示名・順位）と評価リストの台帳（Issue #48 PR-3b §2.4）。
// registry.sqlite には表が無い（`taxon_assessment.category_code`/`list_id` がこのコードを
// 参照するだけ）ので、zone.yaml と同じく YAML を直接読む。rank は「悪化/改善」の比較順序
// （大きいほど深刻）で、`not_listed` だけ null（前回記載なし）。
const redlistCategoryRows = loadYaml(fs.readFileSync(REDLIST_CATEGORY_YAML, "utf-8")).categories;
const redlistCategory = {};
for (const r of redlistCategoryRows) {
  if (r.code in redlistCategory) {
    throw new Error(`registry/taxon/redlist_category.yaml の code が重複している: ${r.code}`);
  }
  if (!r.label_ja) throw new Error(`registry/taxon/redlist_category.yaml の code=${r.code} に label_ja が無い`);
  redlistCategory[r.code] = { labelJa: r.label_ja, rank: r.rank ?? null, scope: r.scope };
}
const assessmentListRows = loadYaml(fs.readFileSync(ASSESSMENT_LIST_YAML, "utf-8")).lists;
const assessmentList = {};
for (const r of assessmentListRows) {
  if (r.list_id in assessmentList) {
    throw new Error(`registry/taxon/assessment_list.yaml の list_id が重複している: ${r.list_id}`);
  }
  if (r.codelist && r.codelist !== "redlist_category") {
    throw new Error(`registry/taxon/assessment_list.yaml の list_id=${r.list_id} の codelist が未知: ${r.codelist}`);
  }
  assessmentList[r.list_id] = {
    name: r.name,
    year: r.year,
    kind: r.kind,
    region: r.region,
    codelist: r.codelist ?? null,
  };
}

// caveat キーの union 型（build-registry-ts.mjs が唯一の生成元。手書きしない）。
// 画面・prompt.ts が既知のキーを直接引くときの型チェックに使う
// （web/src/lib/registry/lookup-client.ts の caveatBody）。
// 0件だと `export type CaveatKey = ;` という不正な TS になってしまうので、うるさく落ちる。
const caveatKeys = caveats.map((c) => c.key);
if (caveatKeys.length === 0) {
  throw new Error("caveat が0件（registry.sqlite の caveat テーブルが空）。CaveatKey を生成できない。");
}

// 旧 place_id → 新 place_id（registry.sqlite の id_map。下の idMapOut が使う）。
const legacyPlaceIds = db
  .prepare("SELECT old_id, new_id FROM id_map WHERE entity = 'place' ORDER BY old_id")
  .all();

// 出典メタ（source / source_edition / license。Issue #39 Phase C、Issue #40 Phase D 担当 E）。
// 応答封筒（ADR-0014）の provenance が毎応答 D1 の source_registry を引かずに済むよう、
// 件数が小さく不変なこの3表を生成物に焼く（rows_read 0）。サーバ専用。
// 合成データの出典（`synthetic_*`。b03/b06 が除外し、dist も出さない）は生成物に載せない。出典メタの読み出し口
// （MCP の describe_catalog/search_registry・応答封筒）に合成の出典が出ないことを、ここ（生成の段階）で保証する。
const SYNTHETIC_SOURCE_PREFIX = "synthetic_";
const isSyntheticSource = (sourceId) => String(sourceId).startsWith(SYNTHETIC_SOURCE_PREFIX);
const WALL_CLOCK = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/;
const sourceMeta = db
  .prepare(`SELECT source_id, name_ja, publisher, homepage_url, superseded_by FROM source ORDER BY source_id`)
  .all()
  .filter((r) => !isSyntheticSource(r.source_id))
  .map((r) => ({ sourceId: r.source_id, nameJa: r.name_ja, publisher: r.publisher, homepageUrl: r.homepage_url, supersededBy: r.superseded_by }));
const sourceEditions = db
  .prepare(
    `SELECT edition_id, source_id, edition_key, vintage, fetched_at, url, license_id, license_class,
            redistributable, update_mode, superseded_by
     FROM source_edition ORDER BY source_id, edition_key`,
  )
  .all()
  .filter((r) => !isSyntheticSource(r.source_id))
  .map((r) => ({
    editionId: r.edition_id,
    sourceId: r.source_id,
    editionKey: r.edition_key,
    vintage: r.vintage,
    fetchedAt: r.fetched_at,
    url: r.url,
    licenseId: r.license_id,
    licenseClass: r.license_class,
    redistributable: r.redistributable === null ? null : r.redistributable !== 0,
    updateMode: r.update_mode,
    supersededBy: r.superseded_by,
  }));
// fetched_at の書式（壁時計 YYYY-MM-DDTHH:MM:SS。時刻帯なし）はここ（ビルド時）で検査する。リクエスト時は投げない。
for (const e of sourceEditions) {
  if (e.fetchedAt !== null && !WALL_CLOCK.test(e.fetchedAt)) {
    throw new Error(`source_edition.fetched_at の書式が YYYY-MM-DDTHH:MM:SS ではない: ${e.editionId} = ${JSON.stringify(e.fetchedAt)}`);
  }
}

// 出現データの出典 = マニフェスト（target=occurrence）。新出典を adapter で足せば web を触らずに provenance/freshness に載る。
// `r01 --files-only`（原本の ryuiki.sqlite を開かない CI のビルド）は source / source_edition / license を作らない
// （原本の source_registry が要る）。その registry では出典メタ（generated-source.ts の SOURCE_META 等）を
// 再生成できないので、**既存の generated-source.ts を保持**し、registry との照合は「files-only のため未照合」と明示してスキップする。
// 出典メタはフルビルド（原本のある環境の `pnpm run build:registry:ts`）でだけ更新する。
// ただしマニフェスト由来の OCCURRENCE_SOURCE_IDS は registry を要さないので、files-only でも保持した生成物と突合して止める。
const filesOnly = (() => {
  try {
    return db.prepare("SELECT mode FROM registry_build").get()?.mode === "files_only";
  } catch {
    return false;
  }
})();
const knownSourceIds = new Set(sourceMeta.map((m) => m.sourceId));
const occurrenceSourceIds = fs
  .readdirSync(MANIFESTS_DIR)
  .filter((f) => f.endsWith(".yml"))
  .sort()
  .map((f) => ({ file: f, doc: loadYaml(fs.readFileSync(path.join(MANIFESTS_DIR, f), "utf8")) }))
  .filter(({ doc }) => doc?.target === "occurrence")
  .map(({ file, doc }) => {
    if (!filesOnly && !knownSourceIds.has(doc.source)) {
      throw new Error(`manifests/${file} の source=${doc.source} が registry の source に無い（r01 を再実行すること）`);
    }
    return doc.source;
  });

const licenses = db
  .prepare(`SELECT license_id, name_ja, spdx_or_url, license_class, attribution_text FROM license ORDER BY license_id`)
  .all()
  .map((r) => ({
    licenseId: r.license_id,
    nameJa: r.name_ja,
    spdxOrUrl: r.spdx_or_url,
    licenseClass: r.license_class,
    attributionText: r.attribution_text,
  }));

db.close();

/* ------------------------------------------------------------------ */
/* クライアント向け派生値（web/scripts/lib/registry-codegen.mjs）          */
/* ------------------------------------------------------------------ */

const { variableShort, variableNote, higherIsWorse, variableUnitFallback } = buildClientVariableMaps(
  variables,
  variableAliases,
  units,
);
const variableLabel = buildVariableLabelMap(variables, variableAliases);
const nameJa = Object.fromEntries(vernacular.map((v) => [v.scientificName, v.vernacularNameJa]));

/* ------------------------------------------------------------------ */
/* 書き出し                                                            */
/* ------------------------------------------------------------------ */

function esc(s) {
  return JSON.stringify(s);
}

function tsValue(v) {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean" || typeof v === "number") return String(v);
  return esc(v);
}

function emitObjectArray(rows, fields) {
  const lines = rows.map((row) => {
    const body = fields.map((f) => `${f}: ${tsValue(row[f])}`).join(", ");
    return `  { ${body} },`;
  });
  return `[\n${lines.join("\n")}\n]`;
}

/** `Record<string, ...>` リテラルを書き出す（キー順は入力オブジェクトの挿入順＝決定論的）。 */
function emitRecord(obj) {
  const lines = Object.entries(obj).map(([k, v]) => `  ${esc(k)}: ${tsValue(v)},`);
  return `{\n${lines.join("\n")}\n}`;
}

/**
 * `Record<string, { field1, field2, ... }>` リテラルを書き出す（`VARIABLE_LABEL` 用。
 * `emitRecord()` は値がスカラーの Record しか書けないため別関数にした）。
 */
function emitNestedRecord(obj, fields) {
  const lines = Object.entries(obj).map(([k, row]) => {
    const body = fields.map((f) => `${f}: ${tsValue(row[f])}`).join(", ");
    return `  ${esc(k)}: { ${body} },`;
  });
  return `{\n${lines.join("\n")}\n}`;
}

const SERVER_HEADER = `/**
 * 生成物。直接編集しない。サーバ専用（unit / variable / variable_alias の生テーブル）。
 *
 * 再生成: \`cd web && npm run build:registry:ts\`
 * 生成元: \`web/scripts/build-registry-ts.mjs\`（data/db/registry.sqlite から作る）。
 *
 * クライアントバンドルに含めないこと。ここを import してよいのは
 * \`web/src/lib/registry/lookup.ts\`（server-only ではないが、D1 から引く大きい
 * テーブルを持つためクライアントコンポーネントから import しない）だけ。
 * クライアント安全な語彙定数（VARIABLE_SHORT 等）・caveat は
 * \`./generated-client.ts\` を使う。
 *
 * docs/plans/PHASE_A.md §A-7 / code-review #4（クライアントバンドル+65KB問題）
 */

export interface GeneratedUnit {
  unitId: string;
  symbol: string | null;
  ucum: string | null;
  nameJa: string | null;
  quantityKind: string | null;
  /** 正準単位（ADR-0023、Issue #31）。換算しない単位は自分自身。 */
  canonicalUnitId: string;
  /** 値_正準 = 値_出典 × scaleToCanonical（線形のみ。オフセット換算は扱わない）。 */
  scaleToCanonical: number;
}

export interface GeneratedVariable {
  variableId: string;
  code: string | null;
  nameJa: string | null;
  nameEn: string | null;
  theme: string | null;
  unitId: string | null;
  valueType: string | null;
  defaultStat: string | null;
  higherIsWorse: boolean | null;
  descriptionJa: string | null;
  status: string | null;
}

export interface GeneratedVariableAlias {
  alias: string;
  /** どの原本の表記か（measurements / sensor_timeseries / 土地利用は出典名そのもの。版は editionKey）。以前の sourceScope。 */
  dataset: string | null;
  /** source_registry.source_id（bare。cube・D1 も bare）。null = 出典未記録（is_synthetic=1 の行）。 */
  sourceId: string | null;
  variableId: string | null;
  unitId: string | null;
  stat: string | null;
  grain: string | null;
  /** unit_id の根拠。'source'=原本が報告 / 'registry'=原本に単位記載が無くレジストリが補った。unitId が無い行は null。 */
  unitBasis: "source" | "registry" | null;
  /** 出典の版（土地利用 2006/2016。Issue #39 Phase C。以前は dataset に @<年> を後置していた）。null = 全 edition 共通。 */
  editionKey: string | null;
}
`;

const serverOut = `${SERVER_HEADER}
/** measurements.unit 9種 + sensor_timeseries.unit 22種を正準化したものに、一次資料由来の
 * 単位（m3/s。どちらの原本にも出現しない）を加えた29件（registry/unit.yaml）。 */
export const GENERATED_UNITS: readonly GeneratedUnit[] = ${emitObjectArray(units, [
  "unitId",
  "symbol",
  "ucum",
  "nameJa",
  "quantityKind",
  "canonicalUnitId",
  "scaleToCanonical",
])};

/** 正準の指標（registry/variable.yaml）。名前から単位・粒度・統計量を剥がした後の形。 */
export const GENERATED_VARIABLES: readonly GeneratedVariable[] = ${emitObjectArray(variables, [
  "variableId",
  "code",
  "nameJa",
  "nameEn",
  "theme",
  "unitId",
  "valueType",
  "defaultStat",
  "higherIsWorse",
  "descriptionJa",
  "status",
])};

/** 出典表記 -> 正準 variable の対応（registry/variable_alias.csv、154行。エイリアスは
 * 出典 × 表記で解決する — ADR-0010 決定1）。 */
export const GENERATED_VARIABLE_ALIASES: readonly GeneratedVariableAlias[] = ${emitObjectArray(
  variableAliases,
  ["alias", "dataset", "sourceId", "variableId", "unitId", "stat", "grain", "unitBasis", "editionKey"],
)};
`;

const CLIENT_HEADER = `/**
 * 生成物。直接編集しない。クライアント安全（'server-only' は付けない。
 * 証跡カードなどクライアントコンポーネントからも import される）。
 *
 * 再生成: \`cd web && npm run build:registry:ts\`
 * 生成元: \`web/scripts/build-registry-ts.mjs\`（data/db/registry.sqlite と
 * registry/taxon/vernacular_ja.csv・registry/place/zone.yaml から作る。派生値の組み立ては
 * \`web/scripts/lib/registry-codegen.mjs\`）。
 *
 * VARIABLE_SHORT 等は、生の variable(85件)/variable_alias(117件) テーブルから
 * 「代表エイリアス」を選んで再構成した派生値であり、生テーブルそのものではない
 * （レビュー指摘・code-review #4: 以前は旧 domain.ts が実行時にこの再構成を
 * 行っており、その結果クライアントバンドルに生テーブル全体が乗っていた）。生テーブルが
 * 要る場合は \`./generated.ts\`（サーバ専用）を使う。
 *
 * D1 から動的に引く必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * ここには無い。読み出しは \`web/src/lib/registry/index.ts\`（server-only）を使う。
 *
 * docs/plans/PHASE_A.md §A-7 / code-review #4 / docs/plans/PHASE_B_INTAKE.md #6
 */

export interface GeneratedVernacular {
  scientificName: string;
  vernacularNameJa: string;
}

export type CaveatScopeKind = ${CAVEAT_SCOPE_KINDS.map((k) => esc(k)).join(" | ")};

/**
 * caveat の既知のキー18件の union（docs/plans/PHASE_B_INTAKE.md #6）。
 * 画面・\`web/src/lib/ai/prompt.ts\` が \`caveatBody(key)\`（lookup-client.ts）を直接
 * 呼ぶときの型で、存在しないキーはここでコンパイルエラーになる（旧 domain.ts の
 * mustCaveatBody() は実行時例外だった）。
 */
export type CaveatKey = ${caveatKeys.map((k) => esc(k)).join(" | ")};

export interface GeneratedCaveat {
  key: string;
  severity: string | null;
  kind: string | null;
  bodyJa: string;
}

export interface GeneratedCaveatScope {
  scopeKind: CaveatScopeKind;
  scopeRef: string;
  caveatKey: string;
  sortOrder: number;
  /** 優先度（既定0・大きいほど優先）。synthetic 由来の scope 行だけ1。
   * scope_kind ではなくこの列が「先頭に出すべきか」を表す（docs/plans/PHASE_A.md §A-7、
   * scripts/registry/build_caveat.py の docstring）。 */
  priority: number;
}

/** Ridge to Reef ゾーン(1-5)。registry/place/zone.yaml から作る（旧 domain.ts の ZONE_INFO）。 */
export interface GeneratedZone {
  zone: number;
  label: string;
  cond: string;
}

/** region（\`jp-14\` 等）の時刻帯（registry/region.yaml。Issue #32-3、ADR-0024）。 */
export interface GeneratedRegionTime {
  regionId: string;
  /** IANA 時刻帯名（例 \`Asia/Tokyo\`）。 */
  tzName: string;
  /** UTC オフセット（\`+HH:MM\`/\`-HH:MM\`）。 */
  utcOffset: string;
}

/** \`REDLIST_CATEGORY\` の1エントリ（Issue #48 PR-3b §2.4）。rank が null は「前回記載なし」。 */
export interface GeneratedRedlistCategory {
  labelJa: string;
  rank: number | null;
  scope: string;
}

/** \`ASSESSMENT_LIST\` の1エントリ（Issue #48 PR-3b §2.4）。 */
export interface GeneratedAssessmentList {
  name: string;
  year: number;
  kind: string;
  region: string;
  codelist: string | null;
}

/** \`VARIABLE_LABEL\` の1エントリ（Issue #48 PR-2、docs/plans/V2_SERVING_PR2.md §5）。 */
export interface GeneratedVariableLabel {
  short: string;
  note: string | null;
  higherIsWorse: boolean | null;
}
`;

const clientOut = `${CLIENT_HEADER}
/**
 * 水質項目の短い表示名（旧 domain.ts の VARIABLE_SHORT）。
 * variable(85件)・variable_alias(117件)から「代表エイリアス」を選んで再構成した派生値。
 */
export const VARIABLE_SHORT: Readonly<Record<string, string>> = ${emitRecord(variableShort)};

/** 何を意味する指標か（旧 domain.ts の VARIABLE_NOTE）。ツールチップに出す。 */
export const VARIABLE_NOTE: Readonly<Record<string, string>> = ${emitRecord(variableNote)};

/** 上流→下流でこの向きに動くのが「悪化」か（旧 domain.ts の HIGHER_IS_WORSE）。 */
export const HIGHER_IS_WORSE: Readonly<Record<string, boolean>> = ${emitRecord(higherIsWorse)};

/** 単位が原本で NULL の項目に既知のものだけ補う（旧 domain.ts の VARIABLE_UNIT_FALLBACK）。 */
export const VARIABLE_UNIT_FALLBACK: Readonly<Record<string, string>> = ${emitRecord(variableUnitFallback)};

/**
 * \`variable_id\` キーの表示ラベル（Issue #48 PR-2、docs/plans/V2_SERVING_PR2.md §5）。
 * \`name_ja\` が NULL の variable も代表エイリアスの表記へ落として必ず持つ
 * （上の VARIABLE_SHORT 等——alias キー版——とは選定規則が違う。
 * \`web/scripts/lib/registry-codegen.mjs\` の \`buildVariableLabelMap()\` docstring参照）。
 * 対象は dataset='measurements' の alias を1つ以上持つ variable のみ。
 */
export const VARIABLE_LABEL: Readonly<Record<string, GeneratedVariableLabel>> = ${emitNestedRecord(
  variableLabel,
  ["short", "note", "higherIsWorse"],
)};

/**
 * 和名63件（registry/taxon/vernacular_ja.csv、旧 domain.ts の NAME_JA をそのまま複製した台帳）。
 * taxon テーブル全体の vernacular_name_ja（8,324件、taxa 由来の別の母集団）とは別物。
 */
export const NAME_JA: Readonly<Record<string, string>> = ${emitRecord(nameJa)};

/**
 * 注記18件（registry/caveat.yaml）。cells.notes 由来（207件）は含めない。
 * key は caveat_id から "common:caveat:" を外したもの
 * （web/src/lib/ai/caveats.ts が今返しているキー文字列と同じ）。
 */
export const GENERATED_CAVEATS: readonly GeneratedCaveat[] = ${emitObjectArray(caveats, [
  "key",
  "severity",
  "kind",
  "bodyJa",
])};

/**
 * 注記キー -> 範囲（scope）。caveat_scope の scope_kind は ADR-0013 の語彙
 * (${CAVEAT_SCOPE_KINDS.map((k) => `'${k}'`).join(", ")})。scopeRef は ID か \`キー=値\` の選択式
 * （registry/caveat_scope.yaml が宣言。照合は文字列の完全一致）。cells.notes 由来は含めない。
 * 引くのは \`lib/cube/caveats.ts\` の \`caveatsForFacets\`。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder（宣言順）。scope 同士の並びは
 * 呼び出し側が渡す facet の順序と priority（既定0。synthetic だけ1で最優先）に従う
 * （scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = ${emitObjectArray(
  caveatScope,
  ["scopeKind", "scopeRef", "caveatKey", "sortOrder", "priority"],
)};

/**
 * レッドリストのカテゴリー（registry/taxon/redlist_category.yaml。Issue #48 PR-3b §2.4）。
 * キーは \`taxon_assessment.category_code\`/\`prev_category_code\`。\`rank\` は悪化/改善を比べる順序
 * （大きいほど深刻）で、\`not_listed\` だけ null（v1 の「前回記載なし」。direction の判定では順位なし）。
 */
export const REDLIST_CATEGORY: Readonly<Record<string, GeneratedRedlistCategory>> = ${emitNestedRecord(
  redlistCategory,
  ["labelJa", "rank", "scope"],
)};

/**
 * 評価リストの台帳（registry/taxon/assessment_list.yaml。Issue #48 PR-3b §2.4）。
 * キーは \`taxon_assessment.list_id\`。\`kind='red_list'\` が県レッドリスト3版、\`'invasive'\` が外来種。
 */
export const ASSESSMENT_LIST: Readonly<Record<string, GeneratedAssessmentList>> = ${emitNestedRecord(
  assessmentList,
  ["name", "year", "kind", "region", "codelist"],
)};

/** Ridge to Reef ゾーン(1-5)の定義（registry/place/zone.yaml、旧 domain.ts の ZONE_INFO）。 */
export const ZONE_INFO: readonly GeneratedZone[] = ${emitObjectArray(zoneInfo, ["zone", "label", "cond"])};

/** region の時刻帯（registry/region.yaml の語彙。\`lookup-client.ts\` の \`regionTimeZone()\` が引く）。 */
export const REGION_TIME: readonly GeneratedRegionTime[] = ${emitObjectArray(regionTime, ["regionId", "tzName", "utcOffset"])};
`;

// 旧 place_id → 新 place_id（registry.sqlite の id_map。Issue #39 Phase C、ADR-0004 規約2）。
// 旧 ID を受けたら新 ID に解決するための表で、`lib/registry/legacy-id.ts` の `resolveLegacyId()` だけが読む。

const idMapOut = [
  "/**",
  " * 生成物。直接編集しない。サーバ専用（旧 place_id → 新 place_id の対応）。",
  " *",
  " * 再生成: `cd web && npm run build:registry:ts`",
  " * 生成元: `web/scripts/build-registry-ts.mjs`（data/db/registry.sqlite の id_map 表。",
  " * 正は `registry/id_map/place.csv`）。",
  " */",
  "",
  "/** 旧 place_id → 現行の place_id（ADR-0004 規約1 の改定で ns と key の区切りが `-` から `.` になったもの）。 */",
  "export const LEGACY_PLACE_ID_MAP: Readonly<Record<string, string>> = {",
  ...legacyPlaceIds.map((r) => `  ${JSON.stringify(r.old_id)}: ${JSON.stringify(r.new_id)},`),
  "};",
  "",
].join("\n");

const sourceOut = `/**
 * 生成物。直接編集しない。サーバ専用（応答封筒の provenance が引く出典メタ）。
 *
 * 再生成: \`cd web && pnpm run build:registry:ts\`
 * 生成元: \`web/scripts/build-registry-ts.mjs\`（data/db/registry.sqlite の source / source_edition /
 * license 表。正は \`registry/source/{editions,license}.yaml\` と原本の \`source_registry\`）。
 *
 * \`updateMode\` が null の edition は「宣言なし」（推測で埋めない。\`registry/source/editions.yaml\`）。
 * \`fetchedAt\` は取得日時の壁時計（\`YYYY-MM-DDTHH:MM:SS\`、時刻帯なし。時刻帯は region から決める）。
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

export const SOURCE_META: readonly GeneratedSourceMeta[] = ${emitObjectArray(sourceMeta, ["sourceId", "nameJa", "publisher", "homepageUrl", "supersededBy"])};

export const SOURCE_EDITIONS: readonly GeneratedSourceEdition[] = ${emitObjectArray(sourceEditions, [
  "editionId",
  "sourceId",
  "editionKey",
  "vintage",
  "fetchedAt",
  "url",
  "licenseId",
  "licenseClass",
  "redistributable",
  "updateMode",
  "supersededBy",
])};

/** 出現データ（occurrence_agg）の出典。マニフェスト（target=occurrence）由来。画面用 API・MCP の provenance/freshness が使う。 */
export const OCCURRENCE_SOURCE_IDS: readonly string[] = ${JSON.stringify(occurrenceSourceIds)};

export const LICENSES: readonly GeneratedLicense[] = ${emitObjectArray(licenses, ["licenseId", "nameJa", "spdxOrUrl", "licenseClass", "attributionText"])};
`;

fs.mkdirSync(path.dirname(OUT_SERVER), { recursive: true });
if (filesOnly) {
  const kept = fs.readFileSync(SOURCE_COMMITTED, "utf8");
  const m = /export const OCCURRENCE_SOURCE_IDS: readonly string\[\] = (\[.*?\]);/.exec(kept);
  if (!m || m[1] !== JSON.stringify(occurrenceSourceIds)) {
    throw new Error(
      `files-only のため出典メタは再生成しないが、保持した generated-source.ts の OCCURRENCE_SOURCE_IDS が manifests/（target=occurrence）` +
        `${JSON.stringify(occurrenceSourceIds)} と食い違う。原本のある環境で \`pnpm run build:registry:ts\`（フルビルド）を実行して更新すること`,
    );
  }
  if (path.resolve(OUT_SOURCE) !== path.resolve(SOURCE_COMMITTED)) fs.writeFileSync(OUT_SOURCE, kept); // 出力先が別なら保持した内容を写す（再生成テストがバイト一致を確かめられる）
  console.log("files-only のため出典メタ（generated-source.ts）は再生成せず既存を保持した（registry との照合は未実施）");
} else {
  fs.writeFileSync(OUT_SOURCE, sourceOut);
}
fs.writeFileSync(OUT_SERVER, serverOut);
fs.writeFileSync(OUT_CLIENT, clientOut);
fs.writeFileSync(OUT_ID_MAP, idMapOut);
console.log(
  `wrote ${path.relative(REPO, OUT_SERVER)} ` +
    `(units=${units.length} variables=${variables.length} aliases=${variableAliases.length})`,
);
if (!filesOnly) console.log(`wrote ${path.relative(REPO, OUT_SOURCE)} (sources=${sourceMeta.length} editions=${sourceEditions.length} licenses=${licenses.length})`);
console.log(`wrote ${path.relative(REPO, OUT_ID_MAP)} (legacyPlaceIds=${legacyPlaceIds.length})`);
console.log(
  `wrote ${path.relative(REPO, OUT_CLIENT)} ` +
    `(variableShort=${Object.keys(variableShort).length} variableNote=${Object.keys(variableNote).length} ` +
    `higherIsWorse=${Object.keys(higherIsWorse).length} variableUnitFallback=${Object.keys(variableUnitFallback).length} ` +
    `variableLabel=${Object.keys(variableLabel).length} ` +
    `nameJa=${Object.keys(nameJa).length} caveats=${caveats.length} caveatScope=${caveatScope.length} ` +
    `zones=${zoneInfo.length} regions=${regionTime.length})`,
);
