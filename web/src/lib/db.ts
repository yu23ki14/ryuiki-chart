import "server-only";
import { getCloudflareContext } from "@opennextjs/cloudflare";
import { drizzle, type DrizzleD1Database } from "drizzle-orm/d1";
import * as schema from "@/db/schema";
import { TABLE_ORIGIN } from "./table-meta";

/**
 * D1 接続層。
 *
 * 元は 3 つの SQLite ファイルを better-sqlite3 で開き、`d.` / `c.` で ATTACH していた。
 * D1 は 1 ワーカー 1 データベースで ATTACH が無いので、56 テーブルを 1 つの D1 に統合し、
 * 接頭辞なしの素のテーブル名で引く。どの原本から来たテーブルかは `TABLE_ORIGIN` が持つ。
 *
 * ローカル開発では wrangler / miniflare が `.wrangler/state/v3/d1/` に持つ SQLite を、
 * `initOpenNextCloudflareForDev()`（next.config.ts）経由で `next dev` から触っている。
 *
 * D1 の制約で効いてくるもの:
 *   - バインドパラメータは 1 クエリ 100 個まで  -> `IN (...)` は `queryChunked` で分割する
 *   - SQL 文は 100KB まで
 *   - 1 文の実行は 30 秒まで
 *   - 書き込み系はアプリから一切使わない（原本は読み取り専用のまま）
 */

/** D1 の「1 クエリあたりのバインドパラメータ」上限 */
export const D1_MAX_BOUND_PARAMS = 100;

/** `IN (...)` を分割するときの 1 回あたりの値の数。残りは固定パラメータ用に空けておく。 */
const CHUNK = 80;

export async function getD1(): Promise<D1Database> {
  const { env } = await getCloudflareContext({ async: true });
  const db = env.DB;
  if (!db) {
    throw new Error(
      "D1 バインディング DB が無い。wrangler.jsonc の d1_databases と、" +
        "next.config.ts の initOpenNextCloudflareForDev() を確認する。",
    );
  }
  return db;
}

/** Drizzle 版。スキーマを使った型付きの問い合わせ用。 */
export async function getDb(): Promise<DrizzleD1Database<typeof schema>> {
  return drizzle(await getD1(), { schema });
}

export type Row = Record<string, string | number | null | Uint8Array>;

/** `?` を n 個並べる。`IN (${ph(ids)})` の形で使う。 */
export function ph(values: readonly unknown[]): string {
  return values.map(() => "?").join(",");
}

function checkParams(sql: string, params: readonly unknown[]) {
  if (params.length > D1_MAX_BOUND_PARAMS) {
    throw new Error(
      `バインドパラメータが ${params.length} 個で D1 の上限 ${D1_MAX_BOUND_PARAMS} を超えている。` +
        `queryChunked で分割する。SQL: ${sql.slice(0, 120)}…`,
    );
  }
}

/** パラメータ付きの SELECT を実行して行を返す。 */
export async function query<T = Row>(sql: string, params: readonly unknown[] = []): Promise<T[]> {
  checkParams(sql, params);
  const db = await getD1();
  const stmt = params.length ? db.prepare(sql).bind(...params) : db.prepare(sql);
  const res = await stmt.all<T>();
  return res.results;
}

export async function queryOne<T = Row>(
  sql: string,
  params: readonly unknown[] = [],
): Promise<T | undefined> {
  checkParams(sql, params);
  const db = await getD1();
  const stmt = params.length ? db.prepare(sql).bind(...params) : db.prepare(sql);
  return (await stmt.first<T>()) ?? undefined;
}

/**
 * `IN (...)` の中身が 100 個の上限に触れうる問い合わせを、値のかたまりに分けて投げる。
 * 各かたまりが独立に成り立つ SELECT（行の選択）でのみ使えること。
 * 全体で集計する SQL（SUM / 全体比など）には使わない。
 */
export async function queryChunked<T = Row>(
  values: readonly unknown[],
  make: (chunk: readonly unknown[]) => { sql: string; params: readonly unknown[] },
  chunkSize = CHUNK,
): Promise<T[]> {
  if (values.length === 0) return [];
  if (values.length <= chunkSize) {
    const { sql, params } = make(values);
    return query<T>(sql, params);
  }
  const db = await getD1();
  const stmts: D1PreparedStatement[] = [];
  for (let i = 0; i < values.length; i += chunkSize) {
    const { sql, params } = make(values.slice(i, i + chunkSize));
    checkParams(sql, params);
    stmts.push(db.prepare(sql).bind(...params));
  }
  const results = await db.batch<T>(stmts);
  return results.flatMap((r) => r.results);
}

/* ------------------------------------------------------------------ */
/* 任意 SQL（データエクスプローラ用）                                   */
/* ------------------------------------------------------------------ */

const FORBIDDEN =
  /\b(insert|update|delete|drop|alter|create|replace|attach|detach|vacuum|reindex|pragma|begin|commit|rollback)\b/i;

export class SqlError extends Error {}

export interface SqlResult {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  truncated: boolean;
  elapsedMs: number;
  sql: string;
}

/**
 * ユーザーが書いた SQL を実行する。
 * D1 側でも書き込みは通らないが、誤爆時のメッセージを分かりやすくするため事前に弾く。
 */
export async function runUserSql(sql: string, maxRows = 1000): Promise<SqlResult> {
  const trimmed = sql.trim().replace(/;+\s*$/, "");
  if (!trimmed) throw new SqlError("SQL が空です");
  if (trimmed.includes(";")) throw new SqlError("複数ステートメントは実行できません（; は末尾のみ）");
  if (FORBIDDEN.test(trimmed)) {
    throw new SqlError("参照系（SELECT / WITH / EXPLAIN）のみ実行できます。この DB は読み取り専用です。");
  }
  if (!/^\s*(select|with|explain|values)\b/i.test(trimmed)) {
    throw new SqlError("SELECT / WITH / EXPLAIN で始まる文だけ実行できます");
  }

  const db = await getD1();
  const t0 = performance.now();
  let raw: [string[], ...unknown[][]];
  try {
    raw = await db.prepare(trimmed).raw<unknown[]>({ columnNames: true });
  } catch (e) {
    throw new SqlError(e instanceof Error ? e.message : String(e));
  }
  const elapsedMs = performance.now() - t0;

  const [columns, ...rows] = raw;
  return {
    columns: columns ?? [],
    rows: rows.slice(0, maxRows),
    rowCount: rows.length,
    truncated: rows.length > maxRows,
    elapsedMs,
    sql: trimmed,
  };
}

/* ------------------------------------------------------------------ */
/* スキーマ情報                                                        */
/* ------------------------------------------------------------------ */

export interface ColumnInfo {
  name: string;
  type: string;
  notnull: number;
  pk: number;
}

export interface TableInfo {
  /** どの原本から来たテーブルか（main = ryuiki / c = cells / d = derived）。D1 では全部 main スキーマ。 */
  schema: string;
  name: string;
  rowCount: number;
  columns: ColumnInfo[];
  sql: string | null;
}

/** マイグレーション管理・シード状態・miniflare の内部テーブルは一覧に出さない。 */
const HIDDEN_TABLES = /^(_cf_|sqlite_|d1_migrations$|_seed_state$)/;

export async function listTables(): Promise<TableInfo[]> {
  const db = await getD1();

  const master = (
    await db
      .prepare("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
      .all<{ name: string; sql: string | null }>()
  ).results.filter((t) => !HIDDEN_TABLES.test(t.name));

  // 56 テーブル分の table_info と count(*) を 1 往復にまとめる
  const stmts: D1PreparedStatement[] = [];
  for (const t of master) {
    stmts.push(db.prepare(`PRAGMA table_info(${qi(t.name)})`));
    stmts.push(db.prepare(`SELECT count(*) AS n FROM ${qi(t.name)}`));
  }
  const res = await db.batch(stmts);

  return master.map((t, i) => ({
    schema: TABLE_ORIGIN[t.name] ?? "main",
    name: t.name,
    rowCount: (res[i * 2 + 1].results as { n: number }[])[0]?.n ?? 0,
    columns: res[i * 2].results as unknown as ColumnInfo[],
    sql: t.sql,
  }));
}

/** シード投入済みか。未投入なら画面に「まだ空」と出す。 */
export async function isSeeded(): Promise<boolean> {
  const db = await getD1();
  const row = await db
    .prepare("SELECT value FROM _seed_state WHERE key = 'sources'")
    .first<{ value: string | null }>();
  return Boolean(row?.value);
}

/** 識別子のクォート */
export function qi(name: string): string {
  return `"${name.replace(/"/g, '""')}"`;
}
