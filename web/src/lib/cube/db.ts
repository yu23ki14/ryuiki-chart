/**
 * キューブ問い合わせ層（Issue #48 PR-1・`docs/plans/V2_SERVING_PR1.md`）の接続の抽象。
 *
 * `observation.ts`/`catalog.ts` は D1 でも better-sqlite3（`serving-diff`・実 DB 統合テスト・
 * vitest フィクスチャ）でも同じ SQL 文字列を投げられるよう、この `CubeDb` インタフェースだけに
 * 依存する。具体実装は `db-d1.ts`（Cloudflare D1）と `db-sqlite.ts`（Node、better-sqlite3）。
 */
import { D1_MAX_BOUND_PARAMS } from "@/lib/db";

export type SqlParam = string | number | null;
export type Row = Record<string, string | number | null>;

export interface CubeDb {
  readonly kind: "d1" | "sqlite";
  all<T = Row>(sql: string, params?: readonly SqlParam[]): Promise<T[]>;
}

/**
 * `IN (...)` に呼び出し側が持つ任意の ID 一覧をそのまま並べない規約（design §3.1）の上限。
 * 意味のある集合（水域・ゾーン等）は JOIN、任意の ID 一覧は `json_each(?)` で渡す。
 */
export const MAX_ID_LIST = 1000;

const MAX_LIKE_BYTES = 50;
/** `IN (` の直後にこれ以上 `?` が並んでいたら「IN に生の一覧を並べている」とみなす。 */
const MAX_ADJACENT_IN_PLACEHOLDERS = 7;

function byteLength(s: string): number {
  return new TextEncoder().encode(s).length;
}

/**
 * `sql` 中の `?` プレースホルダのうち、文字位置 `charPos` にあるものが何番目
 * （0-based）かを数える。`params` はこの通し番号でバインドされている前提
 * （`db.prepare(sql).bind(...params)` と同じ並び）。
 */
function placeholderIndexAt(sql: string, charPos: number): number {
  let count = -1;
  for (let i = 0; i <= charPos; i++) {
    if (sql[i] === "?") count++;
  }
  return count;
}

/**
 * D1 の制約を実装によらず静的に検査する（両実装が `all()` の先頭で呼ぶ。design §3.1）。
 *   - `params.length <= 100`
 *   - SQL 中の `LIKE` のリテラル/バインド文字列が 50 バイト以下
 *   - `ATTACH` / `d.` / `c.`（ATTACH 時代の名残の接頭辞）を含まない
 *   - `IN (` の直後に `?` が 8 個以上並ばない（一覧は `json_each(?)` で渡す規約）
 *
 * バイト長は Node の `Buffer` ではなく `TextEncoder`（Workers/D1 ランタイムでも動く）で数える。
 */
export function assertD1Compatible(sql: string, params: readonly SqlParam[] = []): void {
  if (params.length > D1_MAX_BOUND_PARAMS) {
    throw new Error(
      `assertD1Compatible: バインドパラメータが ${params.length} 個で D1 の上限 ${D1_MAX_BOUND_PARAMS} を超えている。SQL: ${sql.slice(0, 120)}…`,
    );
  }

  if (/\battach\b/i.test(sql)) {
    throw new Error(`assertD1Compatible: ATTACH は使えない（D1 は単一データベース）。SQL: ${sql.slice(0, 120)}…`);
  }

  // ATTACH 時代の `d.`/`c.` 接頭辞（`d.meas_year`・`c.cells` 等）の名残。
  // 現行の実装は観測キューブのテーブルエイリアスに `c`/`d` を使わない規約にしてあるので、
  // この正規表現が引っかかるのは本当に古い接頭辞が残っているときだけになる。
  const staleAttachPrefix = sql.match(/\b([cd])\.[A-Za-z_]/);
  if (staleAttachPrefix) {
    throw new Error(
      `assertD1Compatible: ATTACH 時代の接頭辞 '${staleAttachPrefix[1]}.' が残っている（D1 に ATTACH は無い）。SQL: ${sql.slice(0, 120)}…`,
    );
  }

  const inClause = new RegExp(`IN\\s*\\(\\s*(\\?\\s*,\\s*){${MAX_ADJACENT_IN_PLACEHOLDERS},}\\?`, "i");
  if (inClause.test(sql)) {
    throw new Error(
      `assertD1Compatible: IN (...) に${MAX_ADJACENT_IN_PLACEHOLDERS + 1}個以上のバインドを並べている。json_each(?) で渡す規約。SQL: ${sql.slice(0, 160)}…`,
    );
  }

  const likeRegex = /LIKE\s*(\?|'((?:[^'\\]|\\.)*)')/gi;
  for (const m of sql.matchAll(likeRegex)) {
    const literal = m[2];
    if (literal !== undefined) {
      if (byteLength(literal) > MAX_LIKE_BYTES) {
        throw new Error(
          `assertD1Compatible: LIKE のリテラル文字列が ${byteLength(literal)} バイトで上限 ${MAX_LIKE_BYTES} を超えている: '${literal}'`,
        );
      }
      continue;
    }
    // `LIKE ?` — 対応するバインドパラメータの実際の値を見る。
    const qOffsetInMatch = m[0].indexOf("?");
    const qPos = (m.index ?? 0) + qOffsetInMatch;
    const idx = placeholderIndexAt(sql, qPos);
    const val = params[idx];
    if (typeof val === "string" && byteLength(val) > MAX_LIKE_BYTES) {
      throw new Error(
        `assertD1Compatible: LIKE にバインドした文字列が ${byteLength(val)} バイトで上限 ${MAX_LIKE_BYTES} を超えている（パラメータ #${idx}）`,
      );
    }
  }
}
