/**
 * 外部キーの親を先にしたテーブルの並び（export-d1-sql.mjs の出力順）。
 * 本番への `wrangler d1 execute --file` は 1 ファイルごとに 1 トランザクションで、外部キーが有効なので、
 * 子表が親より先に入ると FK 違反になる。固定の配列でなく SQLite の `PRAGMA foreign_key_list` から導く。
 * 親子の関係が無いテーブルは入力の順（名前順）のまま。自己参照・対象外のテーブルへの参照は無視する。
 * 循環があれば例外（黙って壊れた順序を返さない）。
 */
export function orderByForeignKeys(db, tables) {
  const set = new Set(tables);
  const parents = new Map(
    tables.map((t) => [
      t,
      new Set(
        db
          .prepare(`PRAGMA foreign_key_list("${t.replace(/"/g, '""')}")`)
          .all()
          .map((r) => r.table)
          .filter((p) => p !== t && set.has(p)),
      ),
    ]),
  );
  const out = [];
  const done = new Set();
  while (out.length < tables.length) {
    const next = tables.find((t) => !done.has(t) && [...parents.get(t)].every((p) => done.has(p)));
    if (next === undefined) {
      throw new Error(`外部キーが循環している: ${tables.filter((t) => !done.has(t)).join(", ")}`);
    }
    out.push(next);
    done.add(next);
  }
  return out;
}
