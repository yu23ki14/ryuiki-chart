export const MIN_CHARS: number;
export const SINGLE_MAX: number;
export const TARGET: number;
export const HARD_MAX: number;
export const OVERLAP: number;
export function normalizeBody(text: string | null | undefined): string;
export function chunkBody(body: string | null | undefined): { seq: number; c0: number; c1: number; text: string }[];
export const sha256: (s: string) => string;
export function vectorId(articleId: string, seq: number): string;
export function chunkShaOf(model: string, text: string): string;
export interface ArticleLike {
  article_id: string;
  title?: string | null;
  section?: string | null;
  kind: string;
  body_text?: string | null;
  body_sha256?: string | null;
  region_id: string;
  source_id: string;
  year?: number | null;
}
export interface Chunk {
  id: string;
  article_id: string;
  seq: number;
  c0: number;
  c1: number;
  text: string;
  chunk_sha: string;
  body_sha: string | null;
  metadata: Record<string, string | number | null | undefined>;
}
export function embedText(article: { title?: string | null; section?: string | null }, chunk: { text: string }): string;
export function chunksForArticle(a: ArticleLike, opts: { model: string; chunkerVersion?: number }): Chunk[];
