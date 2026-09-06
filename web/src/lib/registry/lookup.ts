/**
 * `generated.ts`（サーバ専用・unit / variable / variable_alias の生テーブル）の上に立つ、
 * 手書きの参照ヘルパ。
 *
 * `server-only` は付けていないが、`./generated.ts`（大きい生テーブル）に依存するため
 * クライアントコンポーネントから import しないこと。caveat 関連（クライアントからも
 * 使われる）は `./lookup-client.ts` に分けてある（code-review #4: 以前はここに
 * 全部同居しており、caveatBody() だけを使いたいクライアントコンポーネントも
 * variable(85件)・variable_alias(117件) の生テーブルをまるごと bundle に引き込んでいた）。
 *
 * D1 から動的に読む必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * `./index.ts`（server-only）を使うこと。ここでは扱わない。
 *
 * docs/plans/PHASE_A.md §A-7 / §A-8。
 */
import {
  GENERATED_UNITS,
  GENERATED_VARIABLES,
  GENERATED_VARIABLE_ALIASES,
  type GeneratedUnit,
  type GeneratedVariable,
  type GeneratedVariableAlias,
} from "./generated";

/* ------------------------------------------------------------------ */
/* 索引（モジュール読み込み時に一度だけ作る。117件程度なので毎回舐めても軽いが、
   複数箇所から引かれるので Map にしておく） */
/* ------------------------------------------------------------------ */

const variableById = new Map<string, GeneratedVariable>(GENERATED_VARIABLES.map((v) => [v.variableId, v]));
const unitById = new Map<string, GeneratedUnit>(GENERATED_UNITS.map((u) => [u.unitId, u]));

/** (sourceScope, alias) -> 行。同じ alias 文字列でも sourceScope が違えば別物になりうる。 */
const aliasIndex = new Map<string, GeneratedVariableAlias>(
  GENERATED_VARIABLE_ALIASES.map((a) => [`${a.sourceScope ?? ""}	${a.alias}`, a]),
);

/** variableId ごとのエイリアス行（sourceScope 別）。primaryAlias の算出に使う。 */
const aliasesByVariable = new Map<string, GeneratedVariableAlias[]>();
for (const a of GENERATED_VARIABLE_ALIASES) {
  if (!a.variableId) continue;
  const list = aliasesByVariable.get(a.variableId) ?? [];
  list.push(a);
  aliasesByVariable.set(a.variableId, list);
}

/* ------------------------------------------------------------------ */
/* 基本の引き                                                          */
/* ------------------------------------------------------------------ */

export function getVariable(variableId: string): GeneratedVariable | undefined {
  return variableById.get(variableId);
}

export function getUnit(unitId: string | null | undefined): GeneratedUnit | undefined {
  return unitId ? unitById.get(unitId) : undefined;
}

/** unit の表示用シンボル。無次元（symbol=null）は "" にする（domain.ts の VARIABLE_UNIT_FALLBACK と同じ扱い）。 */
export function unitSymbol(unitId: string | null | undefined): string | null {
  if (!unitId) return null;
  const u = unitById.get(unitId);
  if (!u) return null;
  return u.symbol ?? "";
}

/** 出典表記（`measurements.variable` 等の生文字列）から variable_alias 行を引く。既定は measurements。 */
export function resolveAlias(
  alias: string,
  sourceScope: string = "measurements",
): GeneratedVariableAlias | undefined {
  return aliasIndex.get(`${sourceScope}	${alias}`);
}

export interface ResolvedVariableInfo {
  variableId: string;
  code: string | null;
  nameJa: string | null;
  unit: string | null;
  higherIsWorse: boolean | null;
  descriptionJa: string | null;
}

/**
 * 出典表記 -> 正準 variable の情報一式。alias 行が明示する unit_id（例: pH の
 * dimensionless 上書き）を優先し、無ければ variable 側の unit_id を使う。
 * ツール結果に `variable_id` / `unit` を載せるときの唯一の入り口（web/src/lib/ai/tools.ts）。
 */
export function resolveVariableInfo(
  alias: string,
  sourceScope: string = "measurements",
): ResolvedVariableInfo | undefined {
  const aliasRow = resolveAlias(alias, sourceScope);
  if (!aliasRow?.variableId) return undefined;
  const v = variableById.get(aliasRow.variableId);
  if (!v) return undefined;
  return {
    variableId: v.variableId,
    code: v.code,
    nameJa: v.nameJa,
    unit: unitSymbol(aliasRow.unitId ?? v.unitId),
    higherIsWorse: v.higherIsWorse,
    descriptionJa: v.descriptionJa,
  };
}

/**
 * variable_id ごとの「代表エイリアス」を選ぶ。
 *
 * ルール（scripts/registry/build_variable.py 側のデータからは分からない、
 * このアプリの表示都合の選択なのでここに置く）:
 *   1. grain が 'fiscal_year' でない行があれば、それを使う
 *      （検体値ベースの表記を年度代表値の別名より優先する）。
 *   2. 無ければ（=その variable の出典表記が年度代表値しか無い）、
 *      variable.default_stat と一致する stat の行を使う（無ければ先頭行）。
 *
 * `web/src/lib/registry/generated-client.ts` の VARIABLE_SHORT / VARIABLE_NOTE /
 * HIGHER_IS_WORSE は、ビルド時に `web/scripts/lib/registry-codegen.mjs`（この関数と
 * 同じ規則）がこの代表エイリアスをキーにして再現する。両者は独立実装だが同じ規則を
 * 実装しているので、`web/src/lib/registry/primary-alias.test.ts` が一致を確認する。
 */
export function primaryAlias(
  variableId: string,
  sourceScope: string = "measurements",
): GeneratedVariableAlias | undefined {
  const rows = (aliasesByVariable.get(variableId) ?? []).filter((a) => a.sourceScope === sourceScope);
  if (rows.length === 0) return undefined;
  const nonFiscal = rows.find((a) => a.grain !== "fiscal_year");
  if (nonFiscal) return nonFiscal;
  const v = variableById.get(variableId);
  const wantStat = v?.defaultStat ?? null;
  return rows.find((a) => (a.stat ?? null) === wantStat) ?? rows[0];
}

export function allVariables(): readonly GeneratedVariable[] {
  return GENERATED_VARIABLES;
}

export function allUnits(): readonly GeneratedUnit[] {
  return GENERATED_UNITS;
}
