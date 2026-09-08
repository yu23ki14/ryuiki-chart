/**
 * `measurements.quality_stage` / `organism_records.quality_stage` /
 * `quality_transitions.from_stage`・`to_stage`（`@/lib/queries.ts`）が取りうる3値
 * （暫定→検証済→公開済の順で進む。旧 domain.ts の QUALITY_STAGES）。
 *
 * 指標・単位・注記・zone のような登録語彙ではないので `@/lib/registry/` には置かない
 * （docs/plans/PHASE_B_INTAKE.md #6）。`queries.ts` は `server-only` なのでクライアント
 * コンポーネントから読めず、この値の唯一の画面利用者である `QualityDashboard.tsx`
 * （`@/components/viz/palette.ts` の `QUALITY_STAGE` 配色経由）はクライアント
 * コンポーネントなので、`@/lib/municipality.ts` と同じ形で独立したファイルに置く
 * （/simplify 指摘: 「複数画面で使う非語彙の値は 1 箇所に置く」を貫くなら、
 * この値だけ palette.ts に間借りさせるのは一貫しない）。
 */
export const QUALITY_STAGES = ["暫定", "検証済", "公開済"] as const;
export type QualityStage = (typeof QUALITY_STAGES)[number];
