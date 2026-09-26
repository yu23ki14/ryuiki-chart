import "server-only";
import { getD1 } from "@/lib/db";
import { assertD1Compatible, type CubeDb, type Row, type SqlParam } from "./db";

/**
 * D1 実装。既存 `@/lib/db` の `getD1()` を借りるだけで、それを置き換えない
 * （`queries.ts` は PR-5 まで既存 `db.ts` のまま。design §3.1）。
 */
export async function d1CubeDb(): Promise<CubeDb> {
  const db = await getD1();
  return {
    kind: "d1",
    async all<T = Row>(sql: string, params: readonly SqlParam[] = []): Promise<T[]> {
      assertD1Compatible(sql, params);
      const stmt = params.length ? db.prepare(sql).bind(...params) : db.prepare(sql);
      const res = await stmt.all<T>();
      return res.results;
    },
  };
}
