/**
 * MCP と AI のツールが共有する `region` 引数（Issue #93。docs/plans/REGION_FILTER.md §3-1・§5）。
 *
 * - 値は `REGIONS`（UI の語彙の唯一の場所）から作る。registry に地域が増えたら enum も増える。
 * - 省略は全体（神奈川・奄美の合算）。`'all'` は enum に入れない（cube 層は `undefined` = 全体）。
 * - 不正値は入力エラーにする（URL の `?region=xx` を全体に倒す寛容さとは別。モデルの入力ミスは返して直させる）。
 * - `z.tuple` は使わない（Workers AI が draft 2020-12 で検証して 400 になる）。enum なら両 draft で同じ形。
 */
import { z } from "zod";
import { REGIONS, REGION_IDS } from "@/lib/region";

export const regionSchema = z
  .enum(REGION_IDS)
  .optional()
  .describe(
    "地域で絞る（" +
      REGIONS.map((r) => `${r.id}=${r.label}`).join("、") +
      "）。省略は全体（神奈川・奄美の合算）。地域で件数や出典が変わる",
  );

/** ツールの description / 読み方の末尾に足す一文。 */
export const REGION_NOTE =
  "region を省略すると全体（神奈川・奄美の合算）。地域で件数や出典が変わるので、利用者の関心が一方の地域なら region を指定する。";
