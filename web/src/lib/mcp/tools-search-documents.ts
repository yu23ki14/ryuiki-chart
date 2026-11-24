/**
 * MCP の `search_documents`（広報たつごうの記事を内容で探す。docs/plans/TATSUGO_KOHO_VECTOR.md §6）。
 * `MCP_TOOLS`（静的）には入れない。Workers AI・Vectorize のバインディングがあるときだけ `server.ts` の `toolsFor` が、
 * 取れた依存（deps）を閉じ込めて足す（ローカル・CI ではツールが出ない。一覧のスナップショットは変わらない）。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import { SEARCH_DOCUMENTS_DESCRIPTION, runSearchDocuments, searchDocumentsInputSchema, type SearchDeps } from "@/lib/document-search";
import { McpInputError } from "./errors";
import type { McpContext, McpTool } from "./tools";

export function searchDocumentsTool(deps: SearchDeps): McpTool {
  const inputSchema = searchDocumentsInputSchema.strict(); // MCP だけ strict
  return {
    name: "search_documents",
    description: SEARCH_DOCUMENTS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      const r = await runSearchDocuments(deps, a);
      if (!r.ok) throw new McpInputError(r.error);
      return buildDataEnvelope({ ...a }, r.data, r.outcome.source_ids, {
        now: ctx.now,
        caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds: r.outcome.source_ids })),
      });
    },
  };
}
