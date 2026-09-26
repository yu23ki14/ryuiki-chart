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
 * （実測済み）。
 *
 * **ATTACH は既定で読み取り専用になるわけではない**——`SQLITE_AttachWrite`
 * （`SQLITE_DBCONFIG_ENABLE_ATTACH_WRITE`）は既定で ON であり、これは
 * 「ATTACH した DB を main 接続の読み書きモードに合わせて開く」という意味
 * （ON にしていても、main 自体が読み取り専用で開かれていれば ATTACH 先も
 * 読み取り専用になる。無効化した場合だけ ATTACH 先を強制的に読み取り専用に
 * 落とす、という向き）。ここで守りが効いているのは、main（`v2.sqlite`）を
 * `{readonly: true}` で開いているため（＝`SQLITE_OPEN_READONLY`）——
 * その読み書きモードを ATTACH した `registry`/`ryuiki` も継承する。
 * さらに `query_only = ON` を張ることで、ATTACH の継承に頼らない二重の
 * 書き込み拒否にしてある（`web/scripts/build-derived.mjs` 等、既存スクリプトの
 * ATTACH と同じファイルパスの書き方だが、あちらは読み書き可能な main に
 * ATTACH するため、この二重の読み取り専用化はここ〔serving-diff・テスト〕
 * 固有の事情）。
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
