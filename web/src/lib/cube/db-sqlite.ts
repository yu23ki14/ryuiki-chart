/**
 * better-sqlite3 実装（Node 専用）。アプリ（Cloudflare Workers）からは import しない。
 * テスト（フィクスチャ）と `serving-diff` が使う（design §3.1）。
 *
 * `v2.sqlite` を読み取り専用で開き、`registry.sqlite`/`ryuiki.sqlite` を ATTACH する
 * （原本は読み取り専用の規約——CLAUDE.md）。SQL は非修飾テーブル名で書く
 * （`observation_agg`→main、`place_source_ref`/`variable_alias`等→reg、
 * `sites`/`source_registry`→r。テーブル名が重複しないので SQLite が一意に解決する。
 * D1 と同じ SQL 文字列がそのまま両方で動く）。
 *
 * ATTACH は `file:...?mode=ro` の URI 形にしない: better-sqlite3 は
 * `sqlite3_open_v2()` を呼ぶときに `SQLITE_OPEN_URI` フラグを立てないため
 * （`better-sqlite3/src/objects/database.cpp` の `JS_new`——`mask` に
 * `SQLITE_OPEN_URI` が無い）、ATTACH 文字列も URI として解釈されず、
 * "file:...?mode=ro" という文字列そのものをファイル名として開こうとして失敗する
 * （実測済み）。その代わり SQLite は既定で「ATTACH した DB は常に読み取り専用で
 * 開く」（`SQLITE_DBCONFIG_ENABLE_ATTACH_WRITE` を明示的に有効にしないかぎり。
 * `sqlite3.c` の `attachFunc`: `if ((db->flags & SQLITE_AttachWrite)==0) flags
 * |= SQLITE_OPEN_READONLY`）ため、素のファイルパスで ATTACH するだけで読み取り
 * 専用の規約は自動的に守られる（`web/scripts/build-derived.mjs` 等、既存スクリプトの
 * ATTACH と同じ書き方）。
 */
import Database from "better-sqlite3";
import { assertD1Compatible, type CubeDb, type Row, type SqlParam } from "./db";

export interface SqliteCubeDbPaths {
  v2: string;
  registry: string;
  ryuiki: string;
}

function sqlString(path: string): string {
  return path.replace(/'/g, "''");
}

export function sqliteCubeDb(paths: SqliteCubeDbPaths): CubeDb & { close(): void } {
  const db = new Database(paths.v2, { readonly: true, fileMustExist: true });
  db.pragma("query_only = ON");
  db.exec(`ATTACH DATABASE '${sqlString(paths.registry)}' AS reg`);
  db.exec(`ATTACH DATABASE '${sqlString(paths.ryuiki)}' AS r`);

  return {
    kind: "sqlite",
    async all<T = Row>(sql: string, params: readonly SqlParam[] = []): Promise<T[]> {
      assertD1Compatible(sql, params);
      const stmt = db.prepare(sql);
      const rows = params.length ? stmt.all(...(params as unknown[])) : stmt.all();
      return rows as T[];
    },
    close() {
      db.close();
    },
  };
}
