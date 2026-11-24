import type { Chunk } from "./chunk.mjs";

export interface ManifestEntry {
  id: string;
  article_id: string;
  chunk_sha: string;
}
export function desiredState(chunks: Pick<Chunk, "id" | "article_id" | "chunk_sha">[]): Map<string, ManifestEntry>;
export function diffState(
  desired: Map<string, ManifestEntry>,
  manifest: Map<string, ManifestEntry>,
): { upsert: string[]; delete: string[]; unchanged: number; changedArticles: string[] };
export function idsToWithdraw(manifest: Map<string, ManifestEntry>, o: { articleIds?: string[]; docPrefixes?: string[] }): string[];
export function applyWithdraw(manifest: Map<string, ManifestEntry>, ids: string[]): Set<string>;
export function toNdjson(rows: unknown[]): string;
export function vectorRow(
  chunk: Chunk,
  values: ArrayLike<number>,
  model: string,
): { id: string; values: number[]; metadata: Record<string, string | number> };
