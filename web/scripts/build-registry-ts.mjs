#!/usr/bin/env node
/**
 * `web/src/lib/registry/generated.ts` を作る（docs/plans/PHASE_A.md §A-7）。
 *
 * 読み取り元:
 *   - data/db/registry.sqlite（scripts/r01_build_registry.py が作る）の
 *     unit / variable / variable_alias / caveat / caveat_scope
 *   - registry/taxon/vernacular_ja.csv（domain.ts の NAME_JA 54件をそのまま複製した台帳）
 *
 * ここで書き出す generated.ts は「クライアント安全・同期」の語彙定数だけを持つ。
 * caveats.ts がクライアントコンポーネント（証跡カード）からも import される同期 API
 * （caveatText() / CAVEAT_TEXT）なので、D1 の非同期読み出しに置き換えるとクライアント側が
 * 壊れる。そのため generated.ts はビルド時に静的な値へ落としておく。
 *
 * `cells.notes` 由来の caveat（207件）はここに含めない。クライアントに載せる必要がなく、
 * 量も大きいため（web/src/lib/registry/index.ts の D1 読み出し層の対象）。
 *
 * taxon（41,324件）・place（4,960件）もここには含めない。量が多すぎることに加え、
 * NAME_JA（54件）は domain.ts の手動確認済みの対象だけなので、taxon テーブル全体からではなく
 * registry/taxon/vernacular_ja.csv から直接読む。
 *
 * 再生成:
 *   cd web && npm run build:registry:ts
 *
 * 直接編集しない。中身を直したいときは registry/*.yaml / registry/*.csv /
 * scripts/registry/build_*.py 側を直してから、このコマンドで作り直す。
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..");
const REPO = path.resolve(WEB, "..");
const REGISTRY_DB = path.join(REPO, "data", "db", "registry.sqlite");
const VERNACULAR_CSV = path.join(REPO, "registry", "taxon", "vernacular_ja.csv");
const OUT = path.join(WEB, "src", "lib", "registry", "generated.ts");

if (!fs.existsSync(REGISTRY_DB)) {
  console.error(
    `registry.sqlite が無い: ${REGISTRY_DB}\n` +
      "先に `cd web && npm run build:registry`（scripts/r01_build_registry.py）で作る。",
  );
  process.exit(1);
}
if (!fs.existsSync(VERNACULAR_CSV)) {
  console.error(`和名台帳が無い: ${VERNACULAR_CSV}`);
  process.exit(1);
}

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
    `SELECT alias, source_scope, variable_id, unit_id, stat, grain FROM variable_alias ORDER BY id`,
  )
  .all()
  .map((r) => ({
    alias: r.alias,
    sourceScope: r.source_scope,
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
    `SELECT caveat_id, scope_kind, scope_ref, sort_order FROM caveat_scope
     WHERE scope_kind IN ('table', 'table_prefix', 'table_synthetic')
     ORDER BY scope_kind, scope_ref, sort_order`,
  )
  .all()
  .map((r) => ({
    scopeKind: r.scope_kind,
    scopeRef: r.scope_ref,
    caveatKey: r.caveat_id.slice(CAVEAT_ID_PREFIX.length),
    sortOrder: r.sort_order,
  }));

const vernacular = fs
  .readFileSync(VERNACULAR_CSV, "utf-8")
  .split("\n")
  .slice(1) // header
  .map((l) => l.trim())
  .filter(Boolean)
  .map((line) => {
    const [scientificName, vernacularNameJa] = line.split(",");
    return { scientificName, vernacularNameJa };
  });

db.close();

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

const header = `/**
 * 生成物。直接編集しない。
 *
 * 再生成: \`cd web && npm run build:registry:ts\`
 * 生成元: \`web/scripts/build-registry-ts.mjs\`（data/db/registry.sqlite と
 * registry/taxon/vernacular_ja.csv から作る）。
 *
 * クライアント安全（'server-only' は付けない。証跡カードなどクライアント
 * コンポーネントからも import される）。D1 から動的に引く必要があるもの
 * （taxon 全体・place・cells.notes 由来の caveat）はここには無い。
 * 読み出しは \`web/src/lib/registry/index.ts\`（server-only）を使う。
 *
 * docs/plans/PHASE_A.md §A-7
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
  sourceScope: string | null;
  variableId: string | null;
  unitId: string | null;
  stat: string | null;
  grain: string | null;
}

export type CaveatScopeKind = "table" | "table_prefix" | "table_synthetic";

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
}

export interface GeneratedVernacular {
  scientificName: string;
  vernacularNameJa: string;
}
`;

const out = `${header}
/** measurements.unit 9種 + sensor_timeseries.unit 22種を正準化したもの（registry/unit.yaml）。 */
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

/** 出典表記 -> 正準 variable の対応（registry/variable_alias.csv）。 */
export const GENERATED_VARIABLE_ALIASES: readonly GeneratedVariableAlias[] = ${emitObjectArray(
  variableAliases,
  ["alias", "sourceScope", "variableId", "unitId", "stat", "grain"],
)};

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
 * テーブル -> 注記キーのスコープ（caveat_scope の scope_kind in
 * ('table','table_prefix','table_synthetic')）。cell/cell_table（cells.notes 由来）は含めない。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder。scope 同士（渡されたテーブル間）の並びは
 * 呼び出し側がテーブル名を渡す順序に従う（scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = ${emitObjectArray(
  caveatScope,
  ["scopeKind", "scopeRef", "caveatKey", "sortOrder"],
)};

/**
 * 和名54件（registry/taxon/vernacular_ja.csv、domain.ts の NAME_JA をそのまま複製した台帳）。
 * taxon テーブル全体の vernacular_name_ja（8,324件、taxa 由来の別の母集団）とは別物。
 */
export const GENERATED_VERNACULAR_JA: readonly GeneratedVernacular[] = ${emitObjectArray(
  vernacular,
  ["scientificName", "vernacularNameJa"],
)};
`;

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, out);
console.log(
  `wrote ${path.relative(REPO, OUT)} ` +
    `(units=${units.length} variables=${variables.length} aliases=${variableAliases.length} ` +
    `caveats=${caveats.length} caveatScope=${caveatScope.length} vernacular=${vernacular.length})`,
);
