import type { Config } from "drizzle-kit";

/**
 * スキーマ (src/db/schema.ts) から D1 用のマイグレーション SQL を生成する。
 * 出力先は wrangler.jsonc の migrations_dir と揃えてある。
 *
 *   npm run db:generate  -> drizzle/migrations/NNNN_*.sql を作る
 *   npm run db:migrate   -> wrangler d1 migrations apply ryuiki --local
 */
export default {
  dialect: "sqlite",
  schema: "./src/db/schema.ts",
  out: "./drizzle/migrations",
} satisfies Config;
