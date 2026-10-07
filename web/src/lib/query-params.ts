/**
 * 明細系ツール（`get_edna`・`get_records`）が共有する入力の部品。
 * 絞り込みの文字列は LIKE の部分一致（D1 は LIKE のパターンが 50 バイトまで）か、ID の完全一致。
 */
import { z } from "zod";

/** D1 の LIKE パターンは 50 バイトまで。`%` 2つとエスケープを含めた UTF-8 のバイト長で見る。 */
const MAX_LIKE_BYTES = 50;
export const likeParam = (v: string) => `%${v.replace(/[\\%_]/g, (c) => `\\${c}`)}%`;
const byteLength = (v: string) => new TextEncoder().encode(v).length;

/** 部分一致（LIKE）に使う文字列。パターンが 50 バイトに収まること（日本語なら 16 文字ほど）。 */
export const likeText = (what: string) =>
  z
    .string()
    .trim()
    .min(1)
    .refine((v) => byteLength(likeParam(v)) <= MAX_LIKE_BYTES, "長すぎる（部分一致の文字列は UTF-8 で 48 バイトまで。日本語なら 16 文字ほど）")
    .describe(what);
/** 完全一致の ID。長さは実データの値（地点キーは 162 文字ほど）に合わせて広く取る。 */
export const idText = (what: string) => z.string().trim().min(1).max(300).describe(what);
