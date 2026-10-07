/**
 * MCP の `get_records`（出典ごとの台帳表の明細。docs/plans/MCP_SOURCE_ACCESS.md §3）。
 * `tools.ts` が `MCP_TOOLS` に `getRecordsTool()` を登録する。切り詰め・next_after・n_total・入力エラーの変換は
 * `queryRecords`（`lib/records.ts`）が 1 回で決める。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import { queryRecords, recordsInputSchema, RECORDS_DESCRIPTION } from "@/lib/records";
import { McpInputError } from "./errors";
import type { McpContext, McpTool } from "./tools";

export function getRecordsTool(): McpTool {
  const inputSchema = recordsInputSchema.strict(); // MCP だけ strict（AI 側は既定のまま）
  return {
    name: "get_records",
    description: RECORDS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      const r = await queryRecords(await ctx.db(), a, { onInputError: (m) => new McpInputError(m) });
      return buildDataEnvelope(
        { ...a },
        {
          record_set: r.record_set,
          rows: r.rows,
          offset: r.offset,
          ...(r.next_after !== null ? { next_after: r.next_after } : {}),
          ...(r.n_total !== null ? { n_total: r.n_total } : {}),
        },
        r.source_id === null ? [] : [r.source_id],
        { now: ctx.now, truncated: r.truncated, caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds: r.source_id === null ? [] : [r.source_id] })) },
      );
    },
  };
}
