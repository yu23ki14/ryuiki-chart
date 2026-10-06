/**
 * 遅延生成の `CubeDb` シングルトン。`adapters-v2.ts`（`v2.sqlite`）が「初回の呼び出しで `sqliteCubeDb` を
 * 1回だけ開き、以降は使い回す」ために使う。`createCubeDbSingleton()` を呼ぶたびに独立したインスタンスを返す。
 */
import type { CubeDb } from "@/lib/cube";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";

export interface SqliteCubeDbPaths {
  v2: string;
  registry: string;
  ryuiki: string;
  /** `cells.sqlite`（文書系列）。無ければ ATTACH しない。 */
  cells?: string;
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
