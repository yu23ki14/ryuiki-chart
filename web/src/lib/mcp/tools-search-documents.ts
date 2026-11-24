/**
 * MCP の `search_documents`（広報たつごうの記事を内容で探す。docs/plans/TATSUGO_KOHO_VECTOR.md §6）。
 * `MCP_TOOLS`（静的）には入れない。Workers AI・Vectorize のバインディングがあるときだけ `server.ts` が一覧と呼び出しに足す
 * （ローカル・CI ではツールが出ない。一覧のスナップショットは変わらない）。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import {
  SEARCH_DOCUMENTS_DESCRIPTION,
  VectorUnavailableError,
  defaultSearchDeps,
  searchDocuments,
  searchDocumentsInputSchema,
  type SearchDeps,
} from "@/lib/document-search";
import { McpInputError } from "./errors";
import type { McpContext, McpTool } from "./tools";

export function searchDocumentsTool(): McpTool {
  const inputSchema = searchDocumentsInputSchema.strict(); // MCP だけ strict
  return {
    name: "search_documents",
    description: SEARCH_DOCUMENTS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      const deps = ctx.vector ? await ctx.vector() : await defaultSearchDeps();
      if (!deps) throw new McpInputError("ベクトル検索はこの環境では使えない");
      let r;
      try {
        r = await searchDocuments(deps, a);
      } catch (e) {
        if (e instanceof VectorUnavailableError) throw new McpInputError("ベクトル検索に一時的に接続できない。get_records（record_set=document_articles の q）で探す");
        throw e;
      }
      return buildDataEnvelope({ ...a }, { mode: r.mode, rows: r.rows, ...(r.notes.length ? { notes: r.notes } : {}) }, r.source_ids, {
        now: ctx.now,
        caveats: caveatsForFacets(facetsForOccurrence({ places: [], sourceIds: r.source_ids })),
      });
    },
  };
}

/** `ctx.vector` の型（テストで偽物を渡す）。 */
export type VectorDepsLoader = () => Promise<SearchDeps | null>;
