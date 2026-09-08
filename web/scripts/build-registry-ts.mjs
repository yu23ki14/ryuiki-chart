#!/usr/bin/env node
/**
 * `web/src/lib/registry/generated.ts`（サーバ用）と
 * `web/src/lib/registry/generated-client.ts`（クライアント安全）を作る
 * （docs/plans/PHASE_A.md §A-7）。
 *
 * 読み取り元:
 *   - data/db/registry.sqlite（scripts/r01_build_registry.py が作る）の
 *     unit / variable / variable_alias / caveat / caveat_scope
 *   - registry/taxon/vernacular_ja.csv（旧 domain.ts の NAME_JA 54件をそのまま複製した台帳）
 *   - registry/place/zone.yaml（旧 domain.ts の ZONE_INFO。registry.sqlite を経由せず
 *     直接読む。vernacular_ja.csv と同じ扱い）
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
 *     移設。docs/plans/PHASE_B_INTAKE.md #6）と、caveat 14件・caveat_scope
 *     （小さいので両方に置いて問題ない）。生の variable / alias テーブルはここには載せない。
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
 *   - RYUIKI_REGISTRY_TS_OUT_SERVER / RYUIKI_REGISTRY_TS_OUT_CLIENT: 出力先
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { load as loadYaml } from "js-yaml";
import { parseCsvRecords } from "./lib/csv.mjs";
import { buildClientVariableMaps } from "./lib/registry-codegen.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const REPO = path.resolve(WEB, "..");
const REGISTRY_DB = process.env.RYUIKI_REGISTRY_DB ?? path.join(REPO, "data", "db", "registry.sqlite");
const VERNACULAR_CSV =
  process.env.RYUIKI_VERNACULAR_CSV ?? path.join(REPO, "registry", "taxon", "vernacular_ja.csv");
const ZONE_YAML = process.env.RYUIKI_ZONE_YAML ?? path.join(REPO, "registry", "place", "zone.yaml");
const OUT_SERVER =
  process.env.RYUIKI_REGISTRY_TS_OUT_SERVER ?? path.join(WEB, "src", "lib", "registry", "generated.ts");
const OUT_CLIENT =
  process.env.RYUIKI_REGISTRY_TS_OUT_CLIENT ?? path.join(WEB, "src", "lib", "registry", "generated-client.ts");

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

// CSV パーサ（引用符・引用符内カンマ・引用符内改行・""エスケープ対応、ヘッダ検証つき）は
// `./lib/csv.mjs` に共通化した（`web/scripts/build-geo.mjs` の手書きパーサと同じアルゴリズムの
// 再実装だったため。/simplify 修正3）。

const db = new Database(REGISTRY_DB, { readonly: true });

/* ------------------------------------------------------------------ */
/* 読み取り                                                            */
/* ------------------------------------------------------------------ */

const units = db
  .prepare(`SELECT unit_id, symbol, ucum, name_ja, quantity_kind FROM unit ORDER BY unit_id`)
  .all()
  .map((r) => ({
    unitId: r.unit_id,
    symbol: r.symbol,
    ucum: r.ucum,
    nameJa: r.name_ja,
    quantityKind: r.quantity_kind,
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
    `SELECT alias, dataset, source_id, variable_id, unit_id, stat, grain
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
  }));

// cells.notes 由来（common:caveat:cells.*）は除く。14件のみ。
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

const caveatScope = db
  .prepare(
    `SELECT caveat_id, scope_kind, scope_ref, sort_order, priority FROM caveat_scope
     WHERE scope_kind IN ('table', 'table_prefix')
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
const zoneInfo = zoneRows
  .map((r) => ({ zone: r.zone, label: r.name_ja, cond: r.ui_condition_ja }))
  .sort((a, b) => a.zone - b.zone);

// caveat キーの union 型（build-registry-ts.mjs が唯一の生成元。手書きしない）。
// 画面・prompt.ts が既知のキーを直接引くときの型チェックに使う
// （web/src/lib/registry/lookup-client.ts の caveatBody）。
// 0件だと `export type CaveatKey = ;` という不正な TS になってしまうので、うるさく落ちる。
const caveatKeys = caveats.map((c) => c.key);
if (caveatKeys.length === 0) {
  throw new Error("caveat が0件（registry.sqlite の caveat テーブルが空）。CaveatKey を生成できない。");
}

db.close();

/* ------------------------------------------------------------------ */
/* クライアント向け派生値（web/scripts/lib/registry-codegen.mjs）          */
/* ------------------------------------------------------------------ */

const { variableShort, variableNote, higherIsWorse, variableUnitFallback } = buildClientVariableMaps(
  variables,
  variableAliases,
  units,
);
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
  /** v1 のどのテーブルの表記か（measurements / sensor_timeseries）。以前の sourceScope。 */
  dataset: string | null;
  /** v1 source_registry.source_id。null = 出典未記録（is_synthetic=1 の行）。
   * source_registry/source_edition（ADR-0005）が入る Phase C で source_edition_id に
   * 置き換わる暫定形（docs/plans/PHASE_B_INTAKE.md #1/#9）。 */
  sourceId: string | null;
  variableId: string | null;
  unitId: string | null;
  stat: string | null;
  grain: string | null;
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
  ["alias", "dataset", "sourceId", "variableId", "unitId", "stat", "grain"],
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

export type CaveatScopeKind = "table" | "table_prefix";

/**
 * caveat の既知のキー14件の union（docs/plans/PHASE_B_INTAKE.md #6）。
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
 * 和名54件（registry/taxon/vernacular_ja.csv、旧 domain.ts の NAME_JA をそのまま複製した台帳）。
 * taxon テーブル全体の vernacular_name_ja（8,324件、taxa 由来の別の母集団）とは別物。
 */
export const NAME_JA: Readonly<Record<string, string>> = ${emitRecord(nameJa)};

/**
 * 注記14件（registry/caveat.yaml）。cells.notes 由来（207件）は含めない。
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
 * テーブル -> 注記キーのスコープ（caveat_scope の scope_kind in ('table','table_prefix')）。
 * cell/cell_table（cells.notes 由来）は含めない。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder。scope 同士（渡されたテーブル間）の並びは
 * 呼び出し側がテーブル名を渡す順序と priority（既定0。synthetic だけ1で最優先）に従う
 * （scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = ${emitObjectArray(
  caveatScope,
  ["scopeKind", "scopeRef", "caveatKey", "sortOrder", "priority"],
)};

/** Ridge to Reef ゾーン(1-5)の定義（registry/place/zone.yaml、旧 domain.ts の ZONE_INFO）。 */
export const ZONE_INFO: readonly GeneratedZone[] = ${emitObjectArray(zoneInfo, ["zone", "label", "cond"])};
`;

fs.mkdirSync(path.dirname(OUT_SERVER), { recursive: true });
fs.writeFileSync(OUT_SERVER, serverOut);
fs.writeFileSync(OUT_CLIENT, clientOut);
console.log(
  `wrote ${path.relative(REPO, OUT_SERVER)} ` +
    `(units=${units.length} variables=${variables.length} aliases=${variableAliases.length})`,
);
console.log(
  `wrote ${path.relative(REPO, OUT_CLIENT)} ` +
    `(variableShort=${Object.keys(variableShort).length} variableNote=${Object.keys(variableNote).length} ` +
    `higherIsWorse=${Object.keys(higherIsWorse).length} variableUnitFallback=${Object.keys(variableUnitFallback).length} ` +
    `nameJa=${Object.keys(nameJa).length} caveats=${caveats.length} caveatScope=${caveatScope.length} ` +
    `zones=${zoneInfo.length})`,
);
