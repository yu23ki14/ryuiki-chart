/**
 * 遅延生成の `CubeDb` シングルトン（Issue #48 PR-2 /simplify #10）。
 *
 * `adapters-v2.ts`（本番 `v2.sqlite`）と `v1-compat.ts`（`--v1compat-db`）は
 * どちらも「初回の呼び出しで `sqliteCubeDb` を1回だけ開き、以降は使い回す」
 * という同じ形のモジュール変数シングルトンを持っていた（重複）。実体の
 * データベース接続は2つとも同時に開く必要がある（design §1「差分の差分」——
 * 同じプロセス内で本番接続と v1compat 接続を両方開く）ため、変数そのものは
 * 共有できない。ここでは「シングルトンを作るパターン」だけを共有し、
 * `createCubeDbSingleton()` を呼ぶたびに独立したインスタンスを返す。
 */
import type { CubeDb } from "@/lib/cube";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";

export interface SqliteCubeDbPaths {
  v2: string;
  registry: string;
  ryuiki: string;
}

export interface CubeDbSingleton {
  open(paths: SqliteCubeDbPaths): CubeDb & { close(): void };
  close(): void;
}

/** `onClose` は実際に開いていた（かつ閉じる直前の）DB に対してだけ呼ばれる
 *  （`adapters-v2.ts` の `aliasCatalogCache.delete(db)` 用）。 */
export function createCubeDbSingleton(onClose?: (db: CubeDb & { close(): void }) => void): CubeDbSingleton {
  let db: (CubeDb & { close(): void }) | undefined;
  return {
    open(paths: SqliteCubeDbPaths): CubeDb & { close(): void } {
      if (!db) db = sqliteCubeDb(paths);
      return db;
    },
    close(): void {
      if (db) onClose?.(db);
      db?.close();
      db = undefined;
    },
  };
}
