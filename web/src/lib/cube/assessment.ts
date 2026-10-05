/**
 * レッドリスト（`taxon_assessment`）の問い合わせ（Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §2.2）。
 *
 * `taxon_assessment`（`list_id` が `kind='red_list'` の3版、2,884 行）を1回で取り、
 * **カテゴリ名と順位は生成定数**（`REDLIST_CATEGORY`・`ASSESSMENT_LIST`。D1 に表は足さない）で引き、
 * `direction`（悪化/改善/横ばい/前回記載なし）を TS で付ける。規則は `scripts/b12_project_taxon_v1.py`
 * の `_v1_compat`/`_direction` と同じ（`not_listed` は label/rank を NULL に戻す＝前回記載なし）。
 * 1 版は最大 1,033 行なので行を取って TS で畳む。
 */
import * as generatedClient from "@/lib/registry/generated-client";
import type { CubeDb } from "./db";
import { jsonEachParam } from "./sql";

/** `registry/taxon/redlist_category.yaml`・`assessment_list.yaml` の生成定数の形。 */
export interface AssessmentVocab {
  categories: Readonly<Record<string, { labelJa: string; rank: number | null }>>;
  lists: Readonly<Record<string, { name: string; year: number; kind: string }>>;
}

/**
 * 生成定数（`generated-client.ts` の `REDLIST_CATEGORY`・`ASSESSMENT_LIST`。U1 が
 * `registry-codegen.mjs` で足す）から既定の語彙を組む。
 */
export function generatedAssessmentVocab(): AssessmentVocab {
  const g = generatedClient as unknown as {
    REDLIST_CATEGORY?: AssessmentVocab["categories"];
    ASSESSMENT_LIST?: AssessmentVocab["lists"];
  };
  if (!g.REDLIST_CATEGORY || !g.ASSESSMENT_LIST) {
    throw new Error("generated-client に REDLIST_CATEGORY/ASSESSMENT_LIST が無い（pnpm run build:registry-ts を回す）");
  }
  return { categories: g.REDLIST_CATEGORY, lists: g.ASSESSMENT_LIST };
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

const NOT_LISTED = "not_listed";

interface ChangeRow {
  listYear: number;
  listName: string;
  taxonGroupJa: string | null;
  familyJa: string | null;
  vernacularNameJa: string | null;
  scientificName: string | null;
  nationalCategoryJa: string | null;
  prevLabel: string | null;
  prevRank: number | null;
  curLabel: string | null;
  curRank: number | null;
  direction: RedlistDirection;
}

function resolve(code: string | null, vocab: AssessmentVocab): { label: string | null; rank: number | null } {
  if (code === null || code === NOT_LISTED) return { label: null, rank: null };
  const c = vocab.categories[code];
  return c ? { label: c.labelJa, rank: c.rank } : { label: null, rank: null };
}

/** v1（`build-biota.mjs`）の CASE 式と同じ（今回側が NULL なら横ばいに落ちる）。 */
function directionOf(cur: number | null, prev: number | null): RedlistDirection {
  if (prev === null) return "前回記載なし";
  if (cur === null) return "横ばい";
  if (cur > prev) return "悪化";
  if (cur < prev) return "改善";
  return "横ばい";
}

async function changeRows(db: CubeDb, vocab: AssessmentVocab, listYear?: number): Promise<ChangeRow[]> {
  const listIds = Object.entries(vocab.lists)
    .filter(([, l]) => l.kind === "red_list")
    .map(([id]) => id);
  const params: (string | number)[] = [jsonEachParam(listIds)];
  let where = "list_id IN (SELECT value FROM json_each(?))";
  if (listYear !== undefined) {
    where += " AND list_year = ?";
    params.push(listYear);
  }
  const rows = await db.all<Record<string, string | number | null>>(
    `SELECT assessment_id, list_id, list_year, taxon_group_ja, family_ja, vernacular_name_ja_raw,
            scientific_name_raw, national_category_raw, category_code, prev_category_code
     FROM taxon_assessment WHERE ${where} ORDER BY assessment_id`,
    params,
  );
  return rows.map((r) => {
    const cur = resolve(r.category_code as string | null, vocab);
    const prev = resolve(r.prev_category_code as string | null, vocab);
    return {
      listYear: r.list_year as number,
      listName: vocab.lists[r.list_id as string]?.name ?? (r.list_id as string),
      taxonGroupJa: r.taxon_group_ja as string | null,
      familyJa: r.family_ja as string | null,
      vernacularNameJa: r.vernacular_name_ja_raw as string | null,
      scientificName: r.scientific_name_raw as string | null,
      nationalCategoryJa: r.national_category_raw as string | null,
      prevLabel: prev.label,
      prevRank: prev.rank,
      curLabel: cur.label,
      curRank: cur.rank,
      direction: directionOf(cur.rank, prev.rank),
    };
  });
}

/** `?`/`<`/`>` でバイト列順（SQLite の BINARY）に寄せた比較。null は先頭（ASC の NULLS FIRST）。 */
function cmp(a: string | null, b: string | null): number {
  if (a === b) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  return a < b ? -1 : 1;
}

/** v1 `redlistSummary`。 */
export async function redlistSummary(db: CubeDb, vocab: AssessmentVocab = generatedAssessmentVocab()): Promise<RedlistSummaryRow[]> {
  const rows = await changeRows(db, vocab);
  const acc = new Map<string, RedlistSummaryRow>();
  for (const r of rows) {
    const key = `${r.listYear}\u0000${r.listName}\u0000${r.taxonGroupJa ?? ""}\u0000${r.taxonGroupJa === null ? 1 : 0}\u0000${r.direction}`;
    const cur = acc.get(key);
    if (cur) cur.n++;
    else acc.set(key, { listYear: r.listYear, listName: r.listName, taxonGroupJa: r.taxonGroupJa, direction: r.direction, n: 1 });
  }
  return [...acc.values()].sort(
    (a, b) => a.listYear - b.listYear || cmp(a.taxonGroupJa, b.taxonGroupJa) || cmp(a.direction, b.direction),
  );
}

/** v1 `redlistFlows`（前回・今回の両方にカテゴリがある行だけ）。 */
export async function redlistFlows(
  db: CubeDb,
  listYear: number,
  group?: string,
  vocab: AssessmentVocab = generatedAssessmentVocab(),
): Promise<RedlistFlowRow[]> {
  const rows = await changeRows(db, vocab, listYear);
  const acc = new Map<string, RedlistFlowRow>();
  for (const r of rows) {
    if (r.prevLabel === null || r.curLabel === null) continue;
    if (group && r.taxonGroupJa !== group) continue;
    const key = `${r.prevLabel}\u0000${r.curLabel}\u0000${r.direction}`;
    const cur = acc.get(key);
    if (cur) cur.n++;
    else acc.set(key, { prevLabel: r.prevLabel, curLabel: r.curLabel, direction: r.direction, n: 1 });
  }
  return [...acc.values()].sort(
    (a, b) => b.n - a.n || cmp(a.prevLabel, b.prevLabel) || cmp(a.curLabel, b.curLabel),
  );
}

/** v1 `redlistSpecies`（`ORDER BY (cur_rank - prev_rank) DESC, vernacular_name_ja LIMIT`）。 */
export async function redlistSpecies(
  db: CubeDb,
  listYear: number,
  direction?: string,
  group?: string,
  limit = 300,
  vocab: AssessmentVocab = generatedAssessmentVocab(),
): Promise<RedlistSpeciesRow[]> {
  const rows = await changeRows(db, vocab, listYear);
  const out: RedlistSpeciesRow[] = [];
  for (const r of rows) {
    if (r.prevLabel === null || r.curLabel === null || r.prevRank === null || r.curRank === null) continue;
    if (direction && r.direction !== direction) continue;
    if (group && r.taxonGroupJa !== group) continue;
    out.push({
      vernacularNameJa: r.vernacularNameJa,
      scientificName: r.scientificName,
      familyJa: r.familyJa,
      taxonGroupJa: r.taxonGroupJa,
      prevLabel: r.prevLabel,
      curLabel: r.curLabel,
      prevRank: r.prevRank,
      curRank: r.curRank,
      direction: r.direction,
      nationalCategoryJa: r.nationalCategoryJa,
    });
  }
  out.sort((a, b) => b.curRank - b.prevRank - (a.curRank - a.prevRank) || cmp(a.vernacularNameJa, b.vernacularNameJa));
  return out.slice(0, limit);
}
