/**
 * `generated.ts`（サーバ専用・unit / variable / variable_alias の生テーブル）の上に立つ、
 * 手書きの参照ヘルパ。
 *
 * `server-only` は付けていないが、`./generated.ts`（大きい生テーブル）に依存するため
 * クライアントコンポーネントから import しないこと。caveat 関連（クライアントからも
 * 使われる）は `./lookup-client.ts` に分けてある（code-review #4: 以前はここに
 * 全部同居しており、caveatBody() だけを使いたいクライアントコンポーネントも
 * variable(85件)・variable_alias(154件) の生テーブルをまるごと bundle に引き込んでいた）。
 *
 * D1 から動的に読む必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * `./index.ts`（server-only）を使うこと。ここでは扱わない。
 *
 * docs/plans/PHASE_A.md §A-7 / §A-8。**エイリアスは「出典 × 表記」で解決する**
 * （ADR-0010 決定1、docs/plans/PHASE_B_INTAKE.md #1）。`variable_alias` は
 * `(dataset, alias, sourceId)` 単位の行を持つため、同じ `(dataset, alias)` でも
 * `sourceId` 違いで複数行になりうる。ビルド時の表明
 * （`scripts/registry/build_unit_variable.py` の
 * `_assert_variable_unit_consistent_per_alias`）により、同じ `(dataset, alias)` を
 * 共有する行は `variableId`/`unitId` が必ず一致するので、`variableId`/`unitId` だけが
 * 要る場面（`resolveVariableInfo`）ではどの行を引いても曖昧さは無い。`stat`/`grain`の
 * ように行によって値が変わりうる情報が要る場面は `resolveAliasForSource` を使うこと。
 */
import { dedupeByAlias, pickPrimaryAlias } from "../../../scripts/lib/registry-codegen.mjs";
import {
  GENERATED_UNITS,
  GENERATED_VARIABLES,
  GENERATED_VARIABLE_ALIASES,
  type GeneratedUnit,
  type GeneratedVariable,
  type GeneratedVariableAlias,
} from "./generated";

/* ------------------------------------------------------------------ */
/* 索引（モジュール読み込み時に一度だけ作る。154件程度なので毎回舐めても軽いが、
   複数箇所から引かれるので Map にしておく） */
/* ------------------------------------------------------------------ */

const variableById = new Map<string, GeneratedVariable>(GENERATED_VARIABLES.map((v) => [v.variableId, v]));
const unitById = new Map<string, GeneratedUnit>(GENERATED_UNITS.map((u) => [u.unitId, u]));

function sourceKey(sourceId: string | null | undefined): string {
  return sourceId ?? "";
}

/**
 * (dataset, alias) -> 最初に見つかった行。`variableId`/`unitId` の解決だけが目的で、
 * `sourceId` は問わない（複数行あっても variableId/unitId は一致することが
 * ビルド時に保証されている）。`stat`/`grain` はここでは扱わない
 * （`resolveAliasForSource` を使うこと）。
 */
const firstAliasByDatasetAlias = new Map<string, GeneratedVariableAlias>();
/** (dataset, alias, sourceId) -> 行。厳密な1行引き（`resolveAliasForSource`）に使う。 */
const aliasBySourceKey = new Map<string, GeneratedVariableAlias>();
for (const a of GENERATED_VARIABLE_ALIASES) {
  const datasetAliasKey = `${a.dataset ?? ""}\t${a.alias}`;
  if (!firstAliasByDatasetAlias.has(datasetAliasKey)) firstAliasByDatasetAlias.set(datasetAliasKey, a);
  aliasBySourceKey.set(`${a.dataset ?? ""}\t${a.alias}\t${sourceKey(a.sourceId)}`, a);
}

/** variableId ごとのエイリアス行（dataset 別、source 違いを含む）。primaryAlias の算出に使う。 */
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
 *
 * `dataset` だけで引く（`sourceId` は問わない）。同じ `(dataset, alias)` の複数行は
 * `variableId`/`unitId` が一致することがビルド時に保証されているので、
 * どの行を引いても結果は変わらない。`stat`/`grain` は返さない（黙って1行分の
 * stat/grain を返すと、複数行のうちどれを引いたかで呼び出し側が誤った値を掴む。
 * それが要る場合は `resolveAliasForSource` を使うこと）。
 */
export function resolveVariableInfo(
  alias: string,
  dataset: string = "measurements",
): ResolvedVariableInfo | undefined {
  const aliasRow = firstAliasByDatasetAlias.get(`${dataset}\t${alias}`);
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
 * `(dataset, alias, sourceId)` の完全一致で厳密に1行を返す。`stat`/`grain`
 * が要る利用者（Phase B のファクト移行）はこちらを使うこと。一致が無ければ
 * `undefined`（推測で埋めない）。
 *
 * `sourceId` は `undefined`/`null` を「出典未記録」として同じ意味に扱う
 * （`variable_alias.source_id` が空の行 = `is_synthetic=1` のデータ）。
 */
export function resolveAliasForSource(
  alias: string,
  dataset: string,
  sourceId: string | null | undefined,
): GeneratedVariableAlias | undefined {
  return aliasBySourceKey.get(`${dataset}\t${alias}\t${sourceKey(sourceId)}`);
}

/**
 * variable_id ごとの「代表エイリアス」を選ぶ。
 *
 * ルール自体（scripts/registry/build_variable.py 側のデータからは分からない、このアプリの
 * 表示都合の選択）の実装は `web/scripts/lib/registry-codegen.mjs` の `pickPrimaryAlias()`
 * に1本化した（以前はここに一字一句同じロジックが独立に実装されており、規則を直すときに
 * 2箇所を直す必要があった。修正2）。ここでは D1/`generated.ts` 由来の行を
 * `(variableId, dataset)` で絞り込み、`dedupeByAlias()` で alias 単位に戻してから渡すだけの
 * 薄いラッパ。
 *
 * `dedupeByAlias()` が要る理由（Phase B, docs/plans/PHASE_B_INTAKE.md 設計D）:
 * `variable_alias` が `(dataset, alias)` 単位から `(dataset, alias, sourceId)` 単位に
 * 分かれたため、同じ alias 文字列が複数行（source 違い）になりうる。
 * `pickPrimaryAlias()` の「fiscal_year でない最初の行」判定は alias 単位の判定なので、
 * 渡す前に alias 文字列で重複を除き（CSV の行順を保ったまま最初の1つを残す）、
 * 1 alias = 1行の形に戻す。
 *
 * `web/src/lib/registry/generated-client.ts` の VARIABLE_SHORT / VARIABLE_NOTE /
 * HIGHER_IS_WORSE は、ビルド時に同じ `pickPrimaryAlias()`（+ 同じ `dedupeByAlias()`）を
 * 呼んでこの代表エイリアスをキーにして再現する（`web/scripts/build-registry-ts.mjs` 経由）。
 * `web/src/lib/registry/primary-alias.test.ts` は「2実装が一致するか」ではなく、
 * `pickPrimaryAlias()` という規則そのもの（fiscal_year 優先度・タイブレーク）を検証する。
 */
export function primaryAlias(
  variableId: string,
  dataset: string = "measurements",
): GeneratedVariableAlias | undefined {
  const rows = dedupeByAlias((aliasesByVariable.get(variableId) ?? []).filter((a) => a.dataset === dataset));
  const v = variableById.get(variableId);
  return pickPrimaryAlias(rows, v?.defaultStat ?? null) as GeneratedVariableAlias | undefined;
}

export function allVariables(): readonly GeneratedVariable[] {
  return GENERATED_VARIABLES;
}

export function allUnits(): readonly GeneratedUnit[] {
  return GENERATED_UNITS;
}
