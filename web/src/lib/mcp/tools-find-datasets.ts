/**
 * MCP の `find_datasets`（外部ポータルの目録検索。docs/plans/MCP_EXTERNAL_CATALOG.md §4）。
 * `tools.ts` が `MCP_TOOLS` に `findDatasetsTool()` を登録する。入力検査・並び・truncated は `queryDatasets`
 * （`lib/catalog-search.ts`）が 1 回で決める。値は返さず、定義と最新を取る URL だけ返す。
 * 応答が大きいとき（`FIND_DATASETS_MCP_BYTE_BUDGET`）は行を先頭から減らし、`truncated` と `next_offset` で続きを取れる。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import { FIND_DATASETS_DESCRIPTION, FIND_DATASETS_MCP_BYTE_BUDGET, findDatasetsInputSchema, queryDatasets } from "@/lib/catalog-search";
import { fitHeadRows } from "@/lib/fit-head-rows";
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
      const fit = fitHeadRows(
        r.rows,
        r.truncated,
        (rows, more) => ({
          rows,
          offset: r.offset,
          ...(more ? { next_offset: r.offset + rows.length } : {}),
          ...(r.n_total !== null ? { n_total: r.n_total } : {}),
          ...(r.excluded_no_modified !== null
            ? { excluded_no_modified: r.excluded_no_modified, excluded_reason: "modified_since は metadata_modified が無いデータセット（e-Stat 等）を比べられないので除く" }
            : {}),
        }),
        FIND_DATASETS_MCP_BYTE_BUDGET,
      );
      const shown = new Set(fit.rows.map((d) => d.source_id));
      const sourceIds = r.source_ids.filter((id) => shown.has(id));
      return buildDataEnvelope({ ...a }, fit.data, sourceIds, {
        now: ctx.now,
        truncated: fit.more,
        caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds })),
      });
    },
  };
}
