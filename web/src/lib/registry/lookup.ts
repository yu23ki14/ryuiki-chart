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
import {
  GENERATED_UNITS,
  GENERATED_VARIABLES,
  GENERATED_VARIABLE_ALIASES,
  type GeneratedUnit,
  type GeneratedVariable,
  type GeneratedVariableAlias,
} from "./generated";
import { MEASUREMENTS_DATASET } from "@/lib/cube/series";

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
 * （`resolveAliasForSource` を使うこと）。このキーは意図的に複数行が来うる
 * （`(dataset, alias)` は1対多で正しい）ので、先勝ちで無言のまま構わない。
 */
const firstAliasByDatasetAlias = new Map<string, GeneratedVariableAlias>();
/**
 * (dataset, alias, sourceId) -> 行。厳密な1行引き（`resolveAliasForSource`）に使う。
 * このキーは一意でなければならない（`scripts/registry/build_unit_variable.py` の
 * `_load_variable_alias_csv` が Python 側で assert している）が、SQLite の
 * `ix_variable_alias_dataset_alias_source` は非 UNIQUE 索引で D1 側では何も
 * 強制しない。別経路（例: 将来 D1 から直接読む経路）で重複が紛れ込むと、
 * 後勝ちで黙って上書きされ、`resolveAliasForSource` が誤った行を返しても
 * 誰も気づけない。ここで重複を検出したら例外を投げ、うるさく落とす
 * （code-review 指摘: 索引構築時点の防御を1本足す）。
 */
const aliasBySourceKey = new Map<string, GeneratedVariableAlias>();
for (const a of GENERATED_VARIABLE_ALIASES) {
  const datasetAliasKey = `${a.dataset ?? ""}\t${a.alias}`;
  if (!firstAliasByDatasetAlias.has(datasetAliasKey)) firstAliasByDatasetAlias.set(datasetAliasKey, a);

  const sourceKeyStr = `${a.dataset ?? ""}\t${a.alias}\t${sourceKey(a.sourceId)}`;
  if (aliasBySourceKey.has(sourceKeyStr)) {
    throw new Error(
      `variable_alias: (dataset, alias, sourceId) が重複している: ${sourceKeyStr}`,
    );
  }
  aliasBySourceKey.set(sourceKeyStr, a);
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

/** unit の表示用シンボル。無次元（symbol=null）は "" にする（旧 domain.ts の VARIABLE_UNIT_FALLBACK と同じ扱い）。 */
export function unitSymbol(unitId: string | null | undefined): string | null {
  if (!unitId) return null;
  const u = unitById.get(unitId);
  if (!u) return null;
  return u.symbol ?? "";
}

export interface CanonicalUnit {
  unitId: string;
  /** 正準単位の表示用シンボル（`unitSymbol` と同じ扱い。無次元は ""）。 */
  symbol: string;
  /** 値_正準 = 値_出典 × scale（線形のみ）。 */
  scale: number;
}

/**
 * 単位の正準単位と換算倍率（ADR-0023、Issue #31）。未知の unit_id・null は undefined
 * （換算しない・推測しない）。換算しない単位は自分自身・scale=1。
 */
export function canonicalOf(unitId: string | null | undefined): CanonicalUnit | undefined {
  const u = getUnit(unitId);
  if (!u) return undefined;
  const c = unitById.get(u.canonicalUnitId);
  if (!c) return undefined;
  return { unitId: c.unitId, symbol: c.symbol ?? "", scale: u.scaleToCanonical };
}

export type UnitBasis = "source" | "registry" | "mixed";

const aliasesByVariable = new Map<string, GeneratedVariableAlias[]>();
for (const a of GENERATED_VARIABLE_ALIASES) {
  if (!a.variableId) continue;
  const list = aliasesByVariable.get(a.variableId) ?? [];
  list.push(a);
  aliasesByVariable.set(a.variableId, list);
}

/**
 * 単位の根拠（Issue #31）。
 * - `unitId` が `undefined`（省略）なら variable の単位を使う。**明示的な null（単位不明の系列）は
 *   null を返す**（variable の既定に落とさない）。
 * - `dataset`（`measurements` / `sensor_timeseries` / 土地利用の本体名。`@年` は無視）を渡すと、
 *   その出典の alias だけで根拠を決める。省略すると全出典を畳み、出典で食い違えば 'mixed'。
 * - 該当する alias が無ければ null（推測しない）。
 * 'source'=原本が単位を報告 / 'registry'=原本に単位記載が無くレジストリが補った。宣言は
 * `variable_alias.unit_basis`（b04 が実データとの一致を出典ごとに機械検証している）。
 */
export function unitBasis(variableId: string, unitId?: string | null, dataset?: string): UnitBasis | null {
  const effective = unitId === undefined ? (variableById.get(variableId)?.unitId ?? null) : unitId;
  if (!effective) return null;
  const bases = new Set<string>();
  for (const a of aliasesByVariable.get(variableId) ?? []) {
    if (a.unitId !== effective || !a.unitBasis) continue;
    if (dataset !== undefined && a.dataset?.split("@", 1)[0] !== dataset) continue;
    bases.add(a.unitBasis);
  }
  if (bases.size === 0) return null;
  if (bases.size > 1) return "mixed";
  return [...bases][0] as UnitBasis;
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
  dataset: string = MEASUREMENTS_DATASET,
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

export function allVariables(): readonly GeneratedVariable[] {
  return GENERATED_VARIABLES;
}

export function allUnits(): readonly GeneratedUnit[] {
  return GENERATED_UNITS;
}
