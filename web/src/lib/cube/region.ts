/**
 * 地域で絞る SQL 断片と出典の地域（Issue #93、`docs/plans/REGION_FILTER.md` §3-2）。
 * `region` が undefined のときは何も足さない（全体は現状と同じ SQL 文字列・パラメータ）。
 */
import type { RegionId } from "@/lib/region";
import { SOURCE_REGION } from "@/lib/registry/generated-source";
import type { SqlParam } from "./db";

/** `<alias>.region_id = ?` 単体（" AND " は付けない）。region が undefined なら sql は ""。 */
export function regionPred(
  alias: string,
  region: RegionId | undefined,
): { sql: string; params: SqlParam[] } {
  if (region === undefined) return { sql: "", params: [] };
  return { sql: `${alias}.region_id = ?`, params: [region] };
}

/** place_region への INNER JOIN 断片（alias の place_id が region に属するものだけ）。 */
export function placeRegionJoin(
  placeAlias: string,
  region: RegionId | undefined,
): { joins: string[]; params: SqlParam[] } {
  if (region === undefined) return { joins: [], params: [] };
  return {
    joins: [`JOIN place_region prg ON prg.place_id = ${placeAlias}.place_id AND prg.region_id = ?`],
    params: [region],
  };
}

/** 出典の地域（マニフェスト由来の生成物 SOURCE_REGION）。未宣言は undefined。 */
export function sourceRegion(sourceId: string): RegionId | undefined {
  return SOURCE_REGION[sourceId];
}

/** 出典がその地域に属するか。region undefined は常に true。地域未宣言の出典も true（共通出典）。 */
export function sourceInRegion(sourceId: string, region: RegionId | undefined): boolean {
  if (region === undefined) return true;
  const r = sourceRegion(sourceId);
  return r === undefined || r === region;
}

/** その地域の出典 ID。region undefined は全部。地域未宣言の出典は常に含める（共通出典）。 */
export function sourcesOfRegion<T extends string>(ids: readonly T[], region: RegionId | undefined): T[] {
  return ids.filter((id) => sourceInRegion(id, region));
}
