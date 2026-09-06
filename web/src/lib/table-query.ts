import { getD1, qi, D1_MAX_BOUND_PARAMS, type Row } from "./db";

export type FilterOp = "=" | "!=" | ">" | ">=" | "<" | "<=" | "contains" | "starts" | "isnull" | "notnull";

export interface Filter {
  col: string;
  op: FilterOp;
  val?: string;
}

export interface TableQuery {
  /**
   * どの原本から来たテーブルかの区分（main / c / d）。D1 では全テーブルが同じスキーマに
   * 入っているので SQL には使わない。画面のグループ分けのために往復しているだけ。
   */
  schema?: string;
  table: string;
  limit?: number;
  offset?: number;
  orderBy?: string;
  dir?: "asc" | "desc";
  q?: string;
  filters?: Filter[];
}

export interface TableQueryResult {
  columns: { name: string; type: string }[];
  rows: unknown[][];
  total: number;
  totalIsExact: boolean;
  elapsedMs: number;
  sql: string;
}

interface Col {
  name: string;
  type: string;
}

async function columnsOf(table: string): Promise<Col[]> {
  const db = await getD1();
  const cols = (await db.prepare(`PRAGMA table_info(${qi(table)})`).all<Col>()).results;
  if (cols.length === 0) throw new Error(`テーブルが見つかりません: ${table}`);
  return cols;
}

function buildWhere(
  cols: Col[],
  q: string | undefined,
  filters: Filter[] | undefined,
): { clause: string; params: unknown[] } {
  const parts: string[] = [];
  const params: unknown[] = [];
  const names = new Set(cols.map((c) => c.name));

  for (const f of filters ?? []) {
    if (!names.has(f.col)) continue;
    const c = qi(f.col);
    switch (f.op) {
      case "isnull":
        parts.push(`${c} IS NULL`);
        break;
      case "notnull":
        parts.push(`${c} IS NOT NULL`);
        break;
      case "contains":
        parts.push(`CAST(${c} AS TEXT) LIKE ? ESCAPE '\\'`);
        params.push(`%${escapeLike(f.val ?? "")}%`);
        break;
      case "starts":
        parts.push(`CAST(${c} AS TEXT) LIKE ? ESCAPE '\\'`);
        params.push(`${escapeLike(f.val ?? "")}%`);
        break;
      default: {
        const v = f.val ?? "";
        const num = Number(v);
        const isNum = v !== "" && Number.isFinite(num);
        parts.push(`${c} ${f.op} ?`);
        params.push(isNum ? num : v);
      }
    }
  }

  if (q && q.trim()) {
    const like = `%${escapeLike(q.trim())}%`;
    const textCols = cols.filter((c) => !/^(int|real|num|float|double)/i.test(c.type));
    const target = textCols.length ? textCols : cols;
    // D1 は 1 クエリ 100 バインドまで。列数の多いテーブルで全文検索しても収まるように切る。
    const room = D1_MAX_BOUND_PARAMS - params.length;
    const use = target.slice(0, Math.max(room, 0));
    if (use.length) {
      parts.push("(" + use.map((c) => `CAST(${qi(c.name)} AS TEXT) LIKE ? ESCAPE '\\'`).join(" OR ") + ")");
      for (let i = 0; i < use.length; i++) params.push(like);
    }
  }

  return { clause: parts.length ? " WHERE " + parts.join(" AND ") : "", params };
}

function escapeLike(s: string) {
  return s.replace(/[\\%_]/g, (m) => "\\" + m);
}

export async function queryTable(opts: TableQuery): Promise<TableQueryResult> {
  const db = await getD1();
  const { table } = opts;
  const cols = await columnsOf(table);
  const limit = Math.min(Math.max(opts.limit ?? 100, 1), 5000);
  const offset = Math.max(opts.offset ?? 0, 0);

  const { clause, params } = buildWhere(cols, opts.q, opts.filters);

  let order = "";
  if (opts.orderBy && cols.some((c) => c.name === opts.orderBy)) {
    order = ` ORDER BY ${qi(opts.orderBy)} ${opts.dir === "desc" ? "DESC" : "ASC"}`;
  }

  const from = `FROM ${qi(table)}${clause}`;
  const sql = `SELECT * ${from}${order} LIMIT ${limit} OFFSET ${offset}`;

  // フィルタなしなら全件数、ありなら上限つきで数える（巨大テーブルの保護）
  const CAP = 200_000;
  const countSql = clause
    ? `SELECT count(*) n FROM (SELECT 1 ${from} LIMIT ${CAP})`
    : `SELECT count(*) n FROM ${qi(table)}`;

  const t0 = performance.now();
  const rowStmt = params.length ? db.prepare(sql).bind(...params) : db.prepare(sql);
  const countStmt = clause ? db.prepare(countSql).bind(...params) : db.prepare(countSql);
  const [rows, count] = await Promise.all([
    rowStmt.raw<unknown[]>(),
    countStmt.first<{ n: number }>(),
  ]);
  const elapsedMs = performance.now() - t0;

  const total = count?.n ?? 0;

  return {
    columns: cols.map((c) => ({ name: c.name, type: c.type })),
    rows,
    total,
    totalIsExact: !clause || total < CAP,
    elapsedMs,
    sql,
  };
}

/** 列の要約（分布・欠損率）。ファセット的な絞り込みに使う。 */
export async function columnStats(table: string, column: string, topN = 30) {
  const db = await getD1();
  const cols = await columnsOf(table);
  const col = cols.find((c) => c.name === column);
  if (!col) throw new Error(`列が見つかりません: ${column}`);
  const t = qi(table);
  const c = qi(column);
  const isNumeric = /^(int|real|num|float|double)/i.test(col.type);

  const stmts = [
    db.prepare(
      `SELECT count(*) n, sum(CASE WHEN ${c} IS NULL OR ${c}='' THEN 1 ELSE 0 END) nulls,
              count(DISTINCT ${c}) distinct_n FROM ${t}`,
    ),
    db.prepare(
      `SELECT ${c} AS value, count(*) AS n FROM ${t} WHERE ${c} IS NOT NULL
       GROUP BY 1 ORDER BY 2 DESC LIMIT ${Math.min(Math.max(topN, 1), 200)}`,
    ),
  ];
  if (isNumeric) {
    stmts.push(db.prepare(`SELECT min(${c}) min, max(${c}) max, avg(${c}) avg FROM ${t} WHERE ${c} IS NOT NULL`));
  }

  const res = await db.batch(stmts);
  const base = (res[0].results as { n: number; nulls: number; distinct_n: number }[])[0];
  const top = res[1].results as { value: unknown; n: number }[];
  const numeric = isNumeric ? ((res[2].results as { min: number; max: number; avg: number }[])[0] ?? null) : null;

  return { column, type: col.type, ...base, top, numeric };
}

export function rowsToCsv(columns: string[], rows: unknown[][]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = typeof v === "object" ? "[blob]" : String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const out = [columns.map(esc).join(",")];
  for (const r of rows) out.push(r.map(esc).join(","));
  return out.join("\n");
}

export type { Row };
