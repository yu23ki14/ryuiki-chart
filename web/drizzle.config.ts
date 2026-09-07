import type { Config } from "drizzle-kit";

/**
 * スキーマ (src/db/schema.ts + src/db/schema-registry.ts) から D1 用の
 * マイグレーション SQL を生成する。出力先は wrangler.jsonc の migrations_dir と揃えてある。
 *
 *   npm run db:generate  -> drizzle/migrations/NNNN_*.sql を作る
 *   npm run db:migrate   -> wrangler d1 migrations apply ryuiki --local
 *
 * schema.ts が v1（既存69テーブル）、schema-registry.ts が Phase A の語彙レジストリ
 * （docs/plans/PHASE_A.md §A-1）。ファイルを分けてあるのは「既存テーブルの定義には
 * 一切触れていない」ことを diff で機械的に示すため。両方をここで拾う。
 */
export default {
  dialect: "sqlite",
  schema: ["./src/db/schema.ts", "./src/db/schema-registry.ts"],
  out: "./drizzle/migrations",
} satisfies Config;
