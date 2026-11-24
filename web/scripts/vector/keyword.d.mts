export function queryTerms(q: string, max?: number): string[];
export function keywordRank(
  terms: string[],
  hits: Map<string, Iterable<string>>,
  df: Map<string, number>,
  N: number,
): { article_id: string; score: number }[];
export function rrf(rankings: string[][], k?: number): { article_id: string; score: number }[];
