/**
 * レッドリスト（`taxon_assessment`）の問い合わせ（Issue #48 PR-3b、§2.2）。
 * 型確定コミット: 本体は未実装。
 */
import type { CubeDb } from "./db";

/** `registry/taxon/redlist_category.yaml`・`assessment_list.yaml` の生成定数の形。 */
export interface AssessmentVocab {
  categories: Readonly<Record<string, { labelJa: string; rank: number | null }>>;
  lists: Readonly<Record<string, { name: string; year: number }>>;
}

export type RedlistDirection = "悪化" | "改善" | "横ばい" | "前回記載なし";

export interface RedlistSummaryRow {
  listYear: number;
  listName: string;
  taxonGroupJa: string | null;
  direction: RedlistDirection;
  n: number;
}

export interface RedlistFlowRow {
  prevLabel: string;
  curLabel: string;
  direction: RedlistDirection;
  n: number;
}

export interface RedlistSpeciesRow {
  vernacularNameJa: string | null;
  scientificName: string | null;
  familyJa: string | null;
  taxonGroupJa: string | null;
  prevLabel: string;
  curLabel: string;
  prevRank: number;
  curRank: number;
  direction: RedlistDirection;
  nationalCategoryJa: string | null;
}

const TODO = (): never => {
  throw new Error("lib/cube/assessment: 未実装");
};

export async function redlistSummary(_db: CubeDb, _vocab?: AssessmentVocab): Promise<RedlistSummaryRow[]> {
  return TODO();
}

export async function redlistFlows(
  _db: CubeDb,
  _listYear: number,
  _group?: string,
  _vocab?: AssessmentVocab,
): Promise<RedlistFlowRow[]> {
  return TODO();
}

export async function redlistSpecies(
  _db: CubeDb,
  _listYear: number,
  _direction?: string,
  _group?: string,
  _limit?: number,
  _vocab?: AssessmentVocab,
): Promise<RedlistSpeciesRow[]> {
  return TODO();
}
