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

export interface SqliteCubeDbOptions {
  /**
   * serving-diff の `--pretend-synthetic-excluded`（Issue #48 PR-1 §9-4）専用:
   * ここに挙げた `place_id` の観測を `observation_agg` から除いた「仮想の v2」を作る
   * （PR-2 で合成データを実際に除いた後の見え方を事前に確かめるための道具。
   * 値そのものは変えない・v2.sqlite も書き換えない）。
   *
   * 実装は `observation_agg` という名前の TEMP VIEW を張って本物のテーブルを覆う
   * （SQLite の非修飾名の解決順は TEMP → main → ATTACH 順で、TEMP が勝つ——
   * `observation.ts`/`catalog.ts` はテーブル名を非修飾で書いているので、
   * この関数を呼んだこのコネクションに限って自動的に効く。恒久的な変更ではなく
   * この接続を close() すれば消える）。
   */
  excludePlaceIds?: readonly string[];
}

function sqlString(path: string): string {
  return path.replace(/'/g, "''");
}

export function sqliteCubeDb(paths: SqliteCubeDbPaths, opts?: SqliteCubeDbOptions): CubeDb & { close(): void } {
  const db = new Database(paths.v2, { readonly: true, fileMustExist: true });
  db.exec(`ATTACH DATABASE '${sqlString(paths.registry)}' AS reg`);
  db.exec(`ATTACH DATABASE '${sqlString(paths.ryuiki)}' AS r`);

  if (opts?.excludePlaceIds && opts.excludePlaceIds.length > 0) {
    // `query_only = ON`（下）より前に作る: `CREATE TEMP VIEW` は temp スキーマへの
    // 書き込みなので、先に `query_only` を立てると（temp を含む全スキーマが対象）
    // "attempt to write a readonly database" で失敗する（実測）。
    //
    // VIEW の定義はバインドパラメータを保持できない（`CREATE VIEW` は自分の
    // SQL 文字列だけを持ち、実行時にパラメータを渡す仕組みが無い）ので、
    // ここだけは JSON 配列リテラルを直接埋め込む（呼び出し側が組み立てた
    // 内部の値——外部入力ではない——なので、他のクエリのように `json_each(?)`
    // にできないのはこの1箇所だけの例外）。
    const idsJson = sqlString(JSON.stringify(opts.excludePlaceIds));
    db.exec(`
      CREATE TEMP VIEW observation_agg AS
      SELECT o.* FROM main.observation_agg o
      WHERE o.place_id NOT IN (SELECT value FROM json_each('${idsJson}'))
    `);
  }

  db.pragma("query_only = ON");

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
