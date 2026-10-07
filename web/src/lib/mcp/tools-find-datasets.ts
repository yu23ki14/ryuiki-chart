/**
 * MCP の `find_datasets`（外部ポータルの目録検索。docs/plans/MCP_EXTERNAL_CATALOG.md §4）。
 * `tools.ts` が `MCP_TOOLS` に `findDatasetsTool()` を登録する。入力検査・並び・truncated は `queryDatasets`
 * （`lib/catalog-search.ts`）が 1 回で決める。値は返さず、定義と最新を取る URL だけ返す。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import { FIND_DATASETS_DESCRIPTION, findDatasetsInputSchema, queryDatasets } from "@/lib/catalog-search";
import { McpInputError } from "./errors";
import type { McpContext, McpTool } from "./tools";

export function findDatasetsTool(): McpTool {
  const inputSchema = findDatasetsInputSchema.strict(); // MCP だけ strict（AI 側は既定のまま）
  return {
    name: "find_datasets",
    description: FIND_DATASETS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      const r = await queryDatasets(await ctx.db(), a, { onInputError: (m) => new McpInputError(m) });
      return buildDataEnvelope(
        { ...a },
        { rows: r.rows, offset: r.offset, ...(r.n_total !== null ? { n_total: r.n_total } : {}) },
        r.source_ids,
        { now: ctx.now, truncated: r.truncated, caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds: r.source_ids })) },
      );
    },
  };
}
