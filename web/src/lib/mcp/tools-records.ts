/**
 * MCP の `get_records`（出典ごとの台帳表の明細。docs/plans/MCP_SOURCE_ACCESS.md §3）。
 * 登録は `tools.ts`（担当 A）が `MCP_TOOLS` に `getRecordsTool()` を足すだけ。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import {
  queryRecords,
  RecordsInputError,
  recordsInputSchema,
  RECORDS_DESCRIPTION,
  type RecordTableName,
} from "@/lib/records";
import { McpInputError, type McpContext, type McpTool } from "./tools";

export interface GetRecordsOptions {
  /**
   * `q`・`id` なしのときの `n_total`（事前計算の出典別件数）。統合時に `SOURCE_ACCESS` から渡す。
   * 未指定・null のときは `n_total` を載せない（リクエスト時に count(*) しない）。
   */
  nTotal?: (sourceId: string, table: RecordTableName) => number | null | undefined;
}

export function getRecordsTool(opt: GetRecordsOptions = {}): McpTool {
  const inputSchema = recordsInputSchema.strict(); // MCP だけ strict（AI 側は既定のまま）
  return {
    name: "get_records",
    description: RECORDS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      let r;
      try {
        r = await queryRecords(await ctx.db(), a);
      } catch (e) {
        if (e instanceof RecordsInputError) throw new McpInputError(e.message);
        throw e;
      }
      const rows = r.rows.slice(0, r.limit);
      const truncated = r.rows.length > r.limit;
      const nTotal = r.unfiltered ? opt.nTotal?.(r.source_id, r.table) : undefined;
      return buildDataEnvelope(
        { ...a },
        { table: r.table, rows, offset: r.offset, ...(nTotal != null ? { n_total: nTotal } : {}) },
        [r.source_id],
        { now: ctx.now, truncated, caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds: [r.source_id] })) },
      );
    },
  };
}
