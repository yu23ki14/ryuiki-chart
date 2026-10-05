/**
 * serving-diff の v1 oracle（`scripts/lib/serving/v1-queries.ts`）と v1 アダプタが使う、
 * better-sqlite3 版の `query`/`queryOne`/`queryChunked`/`ph`（`web/src/lib/db.ts` の D1 実装と
 * 同じシグネチャ）。PR-4 までは `web/src/lib/queries.ts` の `./db` import をプリロードで
 * 差し替える先だったが、oracle を `v1-queries.ts` へ移したので、今は直接 import される。
 *
 * v1 のローカル開発（D1 統合より前）は ryuiki.sqlite を本体に cells.sqlite / derived.sqlite
 * を ATTACH していた。v1 の SQL のテーブル名はすべて無接頭辞（`sites`/`meas_year`/`documents`
 * 等）なので、3ファイルの間でテーブル名が衝突しないことが前提。
 * 原本は読み取り専用の規約（CLAUDE.md）。better-sqlite3 は `file:...?mode=ro` の URI
 * filename を解釈しない（SQLITE_OPEN_URI を付けずに開くため）ので、素のパス＋
 * `{ readonly: true }` で開く。メイン接続を readonly で開くと ATTACH したデータベースへの
 * 書き込みも弾かれる。
 *
 * パスの上書きは環境変数だけで行う（`RYUIKI_DB_DIR`＝3ファイルまとめて、
 * `RYUIKI_V1_DERIVED_DB`＝derived.sqlite だけを個別に、`--v1-source v1_projection` 用）。
 * 呼び出し時に毎回 env を読む（過去に ESM/CJS でこのファイルが複数インスタンスになり、
 * module-level の設定関数が片方にしか効かない事故があったため。今は1インスタンスだが、
 * 設定が呼び出しの順序に依らない利点は残る）。
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
 * better-sqlite3 にその上限は無いが、v1 アダプタが `v1-queries.ts` が v1 関数を無変更で呼ぶ以上、
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
