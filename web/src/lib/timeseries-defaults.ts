/**
 * 時系列画面の既定の選び方（純関数）。地域をまたいで別の地域のデータを出さないためのもの。
 * - 項目: 希望（URL）→ 地域の既定 → 全体の既定 → その地域で件数が最も多い項目、の順に「その地域の項目一覧にあるもの」を採る。
 * - 水域: 希望が選べる一覧にあればそれ、無ければ先頭（地点数が最も多い水域）。一覧が空なら null（出すデータが無い）。
 */
export const GLOBAL_DEFAULT_VARIABLE = "common:variable:water.bod";

export function pickVariable(
  vars: readonly { variableId: string; n: number }[],
  candidates: readonly (string | null | undefined)[],
): string {
  const hit = candidates.find((c) => !!c && vars.some((v) => v.variableId === c));
  if (hit) return hit;
  // 一覧が空なら出すデータは無い。希望（無ければ全体の既定）をそのまま返す。
  if (vars.length === 0) return candidates.find((c) => !!c) || GLOBAL_DEFAULT_VARIABLE;
  return vars.reduce((a, b) => (b.n > a.n ? b : a)).variableId;
}

export function pickWater(available: readonly { name: string }[], pref: string): string | null {
  if (available.length === 0) return null;
  return available.some((w) => w.name === pref) ? pref : available[0].name;
}
