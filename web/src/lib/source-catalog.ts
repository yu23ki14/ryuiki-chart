/**
 * 出典の一覧の行（`describe_catalog what='sources'`・`search_registry`・`/sources` 画面で共有）。
 * 出典の正は registry（`SOURCE_META`・`SOURCE_ACCESS`・edition/license）の 1 系統。旧表 `source_registry` は読まない。
 */
import { sourceAccess, sourceCitation, sourceFreshness } from "@/lib/cube/source-meta";
import { SOURCE_EXCLUDED_FROM_LIST, SOURCE_META } from "@/lib/registry/generated-source";

type Meta = (typeof SOURCE_META)[number];

/** SOURCE_ACCESS は SOURCE_META と同じ出典を網羅する（r01・build-registry-ts・tools.test.ts が固定）。無いのは生成物の不整合。 */
function sourceAccessOrThrow(sourceId: string) {
  const a = sourceAccess(sourceId);
  if (!a) throw new Error(`SOURCE_ACCESS に出典 ${sourceId} が無い（pnpm run build:registry:ts を再実行する）`);
  return a;
}

/** 出典 1 件の行（describe_catalog の sources と search_registry の source で同じ形）。 */
export function sourceRow(m: Meta, now: Date | undefined) {
  const a = sourceAccessOrThrow(m.sourceId);
  return {
    ...sourceFreshness(m.sourceId, { now }),
    name: m.nameJa,
    publisher: m.publisher,
    superseded_by: m.supersededBy,
    queryable_via: a.queryableVia,
    record_sets: a.tables,
    // 原本の行数（キューブの集計行数ではない。get_observations の n とは別物）。取れない出典は null。
    n_source_rows: a.nSourceRows,
    n_source_rows_basis: a.nSourceRowsBasis,
    counted_at: a.countedAt,
    unavailable_reason: a.reason,
    unavailable_reason_ja: a.reasonJa,
    unavailable_note: a.reasonNote,
  };
}

/** `describe_catalog(sources)` の集計済みの件数。モデルに一覧を数えさせない（「123 件中 9 件」の誤りの対策）。 */
export function sourceSummary(metas: readonly Meta[]) {
  const by_tool: Record<string, number> = {};
  const by_reason: Record<string, number> = {};
  let queryable = 0;
  for (const m of metas) {
    const a = sourceAccessOrThrow(m.sourceId);
    if (a.state === "queryable") queryable += 1;
    for (const t of a.queryableVia) by_tool[t] = (by_tool[t] ?? 0) + 1;
    if (a.reason) by_reason[a.reason] = (by_reason[a.reason] ?? 0) + 1;
  }
  // by_tool は重複あり（kanagawa_edna は get_occurrences と get_edna の両方）。重複なしの数は queryable。
  // excluded: 一覧から除いた出典の件数と理由（合成データ。total には含めない）。
  return { total: metas.length, queryable, not_queryable: metas.length - queryable, by_tool, by_reason, excluded: { ...SOURCE_EXCLUDED_FROM_LIST } };
}

/** `/sources` 画面の行。`sourceRow`（describe_catalog と同じ）に、画面が見せる取得元 URL・ライセンスを足す。 */
export function sourcePageRow(m: Meta, now: Date | undefined) {
  const c = sourceCitation(m.sourceId, { now });
  return {
    ...sourceRow(m, now),
    url: m.homepageUrl,
    license: c.license,
    license_class: c.license_class,
    redistributable: c.redistributable,
  };
}
export type SourcePageRow = ReturnType<typeof sourcePageRow>;

/** `/sources` 画面の全行（describe_catalog と同じ SOURCE_META）。原本の行数の多い順（行数が無い出典は最後）。 */
export function sourcePageRows(now: Date | undefined): SourcePageRow[] {
  return SOURCE_META.map((m) => sourcePageRow(m, now)).sort((a, b) => (b.n_source_rows ?? -1) - (a.n_source_rows ?? -1));
}
