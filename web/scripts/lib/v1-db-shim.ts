/**
 * serving-diff の v1 アダプタが `web/src/lib/queries.ts` を無変更で呼ぶための、
 * `@/lib/db`（D1 実装）と同じシグネチャ（`query`/`queryOne`/`queryChunked`/`ph`）を
 * 持つ better-sqlite3 版の実装。
 *
 * `web/scripts/lib/serving/register-aliases.mjs`（Node の `Module._resolveFilename`
 * を差し替えるプリロードスクリプト）が、queries.ts の `import { query, ... } from
 * "./db"` の解決先をこのファイルに差し替える。TypeScript の型検査はこの差し替えを
 * 知らない（`queries.ts` は普通に本物の `db.ts` を見て型検査される）ため、ここは
 * `db.ts` の型を import も継承もしない、独立した実装として書く。
 *
 * v1 のローカル開発（D1 統合より前）は ryuiki.sqlite を本体に cells.sqlite / derived.sqlite
 * を ATTACH していた（`web/src/lib/db.ts` の冒頭コメント参照）。queries.ts のテーブル名は
 * すべて無接頭辞（`sites`/`meas_year`/`documents` 等）なので、3ファイルの間でテーブル名が
 * 衝突しないことが前提（`web/src/lib/table-meta.ts` の TABLE_ORIGIN で確認済み）。
 * 原本は読み取り専用の規約（CLAUDE.md）。better-sqlite3 は `file:...?mode=ro` の URI
 * filename を解釈しない（実機で確認済み: SQLITE_OPEN_URI を付けずに開くため、
 * `file:` 接頭辞を渡すと `SqliteError: unable to open database file` になる）ので、
 * 素のパス＋ `{ readonly: true }` で開く。メイン接続を readonly で開くと ATTACH した
 * データベースへの書き込みも `attempt to write a readonly database` で弾かれることを
 * 実機で確認済み（Python 側の `sqlite3.connect(..., uri=True)` の `mode=ro` と実質的に
 * 同じ「読み取り専用」の保証を、better-sqlite3 の流儀で満たす）。
 *
 * パスの上書きは環境変数だけで行う（`RYUIKI_DB_DIR`＝3ファイルまとめて、
 * `RYUIKI_V1_DERIVED_DB`＝derived.sqlite だけを個別に、`--v1-source v1_projection`
 * 用）。**関数呼び出しでの上書き（module-level な設定関数）にしない**——このファイルは
 * `register-aliases.mjs` の `Module._resolveFilename` パッチ経由で queries.ts から
 * CJS require() され、`serving-diff.mts`/`adapters-v1.ts` からは通常の ESM import で
 * 読まれる。Node の ESM と CJS はモジュールキャッシュが別なので、同じこのファイルが
 * **複数の別インスタンスとして** 読み込まれる（実機で確認済み: ESM 側で呼んだ設定関数が
 * CJS 側のインスタンスに反映されず、`--v1-source v1_projection` が無視される事故が
 * 実際に起きた）。`process.env` はどちらの世界でも同じ1つのグローバルなので、
 * 「呼び出し時に毎回 env を読む」形にすることでインスタンスが複数あっても正しく動く。
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "../../..");

export interface V1DbPaths {
  ryuiki: string;
  cells: string;
  derived: string;
}

/** 呼び出しのたびに `process.env` を読んで組み立てる（モジュール読み込み時点で固定しない）。 */
function resolvePaths(): V1DbPaths {
  const dbDir = process.env.RYUIKI_DB_DIR ?? path.join(REPO_ROOT, "data", "db");
  return {
    ryuiki: path.join(dbDir, "ryuiki.sqlite"),
    cells: path.join(dbDir, "cells.sqlite"),
    derived: process.env.RYUIKI_V1_DERIVED_DB ?? path.join(dbDir, "derived.sqlite"),
  };
}

function openReadOnly(file: string): Database.Database {
  return new Database(file, { readonly: true, fileMustExist: true });
}

/** ATTACH 文の中では単純引用符しか使えないため、埋め込み前にエスケープする。 */
function sqlQuote(file: string): string {
  return file.replace(/'/g, "''");
}

let sharedDb: Database.Database | undefined;

/**
 * ryuiki.sqlite を本体に cells.sqlite（`c`）・derived.sqlite（`d`）を ATTACH した
 * 1つの接続を、プロセス内で使い回す（`--v1-only` の再実行やテストのために
 * 明示的に閉じたいときは `closeV1Db()`）。`paths` を省略すると `resolvePaths()`
 * が呼び出し時点の `process.env`（`RYUIKI_DB_DIR`/`RYUIKI_V1_DERIVED_DB`）から
 * 組み立てた既定パスを使う（上記モジュール docstring「関数呼び出しでの上書きに
 * しない」理由の節参照。設定関数は無い）。
 */
export function openV1Db(paths: V1DbPaths = resolvePaths()): Database.Database {
  if (sharedDb) return sharedDb;
  const db = openReadOnly(paths.ryuiki);
  db.exec(`ATTACH DATABASE '${sqlQuote(paths.cells)}' AS c`);
  db.exec(`ATTACH DATABASE '${sqlQuote(paths.derived)}' AS d`);
  sharedDb = db;
  return db;
}

export function closeV1Db(): void {
  sharedDb?.close();
  sharedDb = undefined;
}

export type Row = Record<string, string | number | null>;

/** `?` を n 個並べる。`web/src/lib/db.ts` の `ph` と同じ挙動。 */
export function ph(values: readonly unknown[]): string {
  return values.map(() => "?").join(",");
}

function run<T>(sql: string, params: readonly unknown[]): T[] {
  const db = openV1Db();
  const stmt = db.prepare(sql);
  const rows = params.length ? stmt.all(...(params as unknown[])) : stmt.all();
  return rows as T[];
}

export async function query<T = Row>(sql: string, params: readonly unknown[] = []): Promise<T[]> {
  return run<T>(sql, params);
}

export async function queryOne<T = Row>(
  sql: string,
  params: readonly unknown[] = [],
): Promise<T | undefined> {
  const rows = run<T>(sql, params);
  return rows[0];
}

/**
 * `@/lib/db` の `queryChunked` と同じ役割（D1 の 100 パラメータ上限を避けるための分割）。
 * better-sqlite3 にその上限は無いが、v1 アダプタが `queries.ts` を無変更で呼ぶ以上、
 * シグネチャと分割してから並べ直す前提（呼び出し側が ORDER BY に頼らない）を
 * 崩さないよう同じ既定値（80件ずつ）で分割する。
 */
export async function queryChunked<T = Row>(
  values: readonly unknown[],
  make: (chunk: readonly unknown[]) => { sql: string; params: readonly unknown[] },
  chunkSize = 80,
): Promise<T[]> {
  if (values.length === 0) return [];
  const out: T[] = [];
  for (let i = 0; i < values.length; i += chunkSize) {
    const chunk = values.slice(i, i + chunkSize);
    const { sql, params } = make(chunk);
    out.push(...run<T>(sql, params));
  }
  return out;
}
