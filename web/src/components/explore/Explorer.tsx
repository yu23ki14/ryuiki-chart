"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { DataGrid } from "./DataGrid";
import { SqlConsole } from "./SqlConsole";
import { Btn, inputCls, Spinner, nf } from "@/components/ui";
import { SCHEMA_META, TABLE_META } from "@/lib/table-meta";
import type { Filter, FilterOp } from "@/lib/table-query";
import { useJson } from "@/components/useJson";

interface ColumnInfo {
  name: string;
  type: string;
  notnull: number;
  pk: number;
}
interface TableInfo {
  schema: string;
  name: string;
  rowCount: number;
  columns: ColumnInfo[];
  sql: string | null;
}
interface TableResult {
  columns: { name: string; type: string }[];
  rows: unknown[][];
  total: number;
  totalIsExact: boolean;
  elapsedMs: number;
  sql: string;
}
interface ColStats {
  column: string;
  type: string;
  n: number;
  nulls: number;
  distinct_n: number;
  top: { value: unknown; n: number }[];
  numeric: { min: number; max: number; avg: number } | null;
}

const OPS: { v: FilterOp; label: string }[] = [
  { v: "contains", label: "を含む" },
  { v: "starts", label: "で始まる" },
  { v: "=", label: "=" },
  { v: "!=", label: "≠" },
  { v: ">", label: ">" },
  { v: ">=", label: "≥" },
  { v: "<", label: "<" },
  { v: "<=", label: "≤" },
  { v: "isnull", label: "が空" },
  { v: "notnull", label: "が非空" },
];

export function Explorer({ tables }: { tables: TableInfo[] }) {
  // ディープリンク（AIのチャットカードの「このSQLをデータ探索で開く」）用に、?sql= が付いていれば
  // SQLコンソールをその内容で開いた状態にする。既存の useState 構造は保つ。URLへの書き戻しはしない。
  const sp = useSearchParams();
  const initialSql = sp.get("sql");
  const [mode, setMode] = React.useState<"table" | "sql">(() => (initialSql ? "sql" : "table"));
  const [sel, setSel] = React.useState<TableInfo>(
    tables.find((t) => t.name === "sites") ?? tables[0],
  );
  const [tableFilter, setTableFilter] = React.useState("");

  // 絞り込みの状態は「どのテーブルに対するものか」を一緒に持つ。
  // テーブルを切り替えたときは、state を書き換えるのではなく描画時に初期値へ戻す。
  interface View {
    key: string;
    q: string;
    qDraft: string;
    filters: Filter[];
    orderBy?: string;
    dir: "asc" | "desc";
    offset: number;
    statsColumn: string | null;
    showSchema: boolean;
  }
  const selKey = sel ? `${sel.schema}.${sel.name}` : "";
  const freshView = (key: string): View => ({
    key,
    q: "",
    qDraft: "",
    filters: [],
    orderBy: undefined,
    dir: "asc",
    offset: 0,
    statsColumn: null,
    showSchema: false,
  });
  const [viewState, setViewState] = React.useState<View>(() => freshView(selKey));
  const view = viewState.key === selKey ? viewState : freshView(selKey);
  const patch = (p: Partial<View>) => setViewState({ ...view, ...p });
  const { q, qDraft, filters, orderBy, dir, offset, statsColumn, showSchema } = view;

  const [limit, setLimit] = React.useState(100);

  const tableUrl = React.useMemo(() => {
    if (!sel) return "";
    const params = new URLSearchParams({
      schema: sel.schema,
      table: sel.name,
      limit: String(limit),
      offset: String(offset),
    });
    if (orderBy) {
      params.set("orderBy", orderBy);
      params.set("dir", dir);
    }
    if (q) params.set("q", q);
    if (filters.length) params.set("filters", JSON.stringify(filters));
    return `/api/table?${params}`;
  }, [sel, limit, offset, orderBy, dir, q, filters]);

  const { data, loading, error } = useJson<TableResult>(tableUrl);

  const statsUrl =
    sel && statsColumn
      ? `/api/column?schema=${sel.schema}&table=${sel.name}&column=${encodeURIComponent(statsColumn)}`
      : "";
  const { data: stats } = useJson<ColStats>(statsUrl);

  const grouped = React.useMemo(() => {
    const g = new Map<string, TableInfo[]>();
    const needle = tableFilter.trim().toLowerCase();
    for (const t of tables) {
      if (needle && !t.name.toLowerCase().includes(needle) && !(TABLE_META[t.name] ?? "").includes(tableFilter))
        continue;
      if (!g.has(t.schema)) g.set(t.schema, []);
      g.get(t.schema)!.push(t);
    }
    return g;
  }, [tables, tableFilter]);

  const page = Math.floor(offset / limit) + 1;
  const pages = data ? Math.max(1, Math.ceil(data.total / limit)) : 1;

  return (
    <div className="flex-1 flex min-h-0">
      {/* サイドバー */}
      <aside className="w-60 shrink-0 border-r border-line bg-surface flex flex-col min-h-0">
        <div className="p-2 border-b border-line">
          <input
            className={inputCls}
            placeholder="テーブルを検索"
            value={tableFilter}
            onChange={(e) => setTableFilter(e.target.value)}
          />
        </div>
        <div className="overflow-y-auto thin-scroll flex-1 py-1">
          {[...grouped.entries()].map(([schema, ts]) => {
            const meta = SCHEMA_META[schema] ?? { label: schema, file: schema, note: "" };
            return (
              <div key={schema} className="mb-2">
                <div className="px-2.5 pt-2 pb-1">
                  <div className="text-[11px] font-semibold text-ink">{meta.label}</div>
                  <div className="text-[9.5px] text-muted font-mono">{meta.file}</div>
                </div>
                {ts.map((t) => {
                  const active = sel?.schema === t.schema && sel?.name === t.name;
                  return (
                    <button
                      key={`${t.schema}.${t.name}`}
                      onClick={() => {
                        setSel(t);
                        setMode("table");
                      }}
                      className={`w-full text-left px-2.5 py-1 flex items-baseline gap-2 border-l-2 ${
                        active
                          ? "border-water bg-water-soft text-water-ink"
                          : "border-transparent hover:bg-surface-2 text-ink-2"
                      }`}
                      title={TABLE_META[t.name]}
                    >
                      <span className="text-[12px] font-mono truncate">{t.name}</span>
                      <span className="ml-auto text-[10px] text-muted tnum shrink-0">{nf(t.rowCount)}</span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </aside>

      {/* メイン */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        <div className="flex items-center gap-1 px-3 pt-2 border-b border-line bg-surface">
          <Btn active={mode === "table"} onClick={() => setMode("table")} className="rounded-b-none">
            テーブル閲覧
          </Btn>
          <Btn active={mode === "sql"} onClick={() => setMode("sql")} className="rounded-b-none">
            SQL コンソール
          </Btn>
          <span className="ml-auto text-[10.5px] text-muted pb-1">
            接続は読み取り専用（SQLite <code className="font-mono">query_only</code>）。原本は書き換わりません。
          </span>
        </div>

        {mode === "sql" ? (
          <SqlConsole initialSql={initialSql ?? undefined} />
        ) : !sel ? (
          <div className="p-6 text-muted text-sm">テーブルがありません</div>
        ) : (
          <div className="flex-1 flex flex-col min-h-0">
            {/* テーブル見出し */}
            <div className="px-3.5 py-2 border-b border-line bg-surface">
              <div className="flex items-baseline gap-2 flex-wrap">
                <h1 className="text-[15px] font-bold font-mono">{sel.name}</h1>
                <span className="text-[11px] text-muted tnum">{nf(sel.rowCount)} 行</span>
                <span className="text-[11px] text-muted">{sel.columns.length} 列</span>
                <button
                  className="text-[11px] text-water underline decoration-dotted"
                  onClick={() => patch({ showSchema: !showSchema })}
                >
                  {showSchema ? "定義を隠す" : "CREATE 文を見る"}
                </button>
              </div>
              {TABLE_META[sel.name] && (
                <p className="text-[11.5px] text-ink-2 mt-0.5">{TABLE_META[sel.name]}</p>
              )}
              {showSchema && (
                <pre className="mt-2 p-2 bg-surface-2 rounded border border-line text-[11px] font-mono overflow-auto thin-scroll max-h-52">
                  {sel.sql ?? "(定義なし)"}
                </pre>
              )}
            </div>

            {/* ツールバー */}
            <div className="px-3.5 py-2 border-b border-line bg-surface-2 flex items-center gap-2 flex-wrap">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  patch({ offset: 0, q: qDraft });
                }}
                className="flex items-center gap-1"
              >
                <input
                  className={inputCls + " w-56"}
                  placeholder="全文検索（テキスト列を横断）"
                  value={qDraft}
                  onChange={(e) => patch({ qDraft: e.target.value })}
                />
                <Btn type="submit">検索</Btn>
              </form>

              <FilterBuilder
                columns={sel.columns}
                onAdd={(f) => patch({ offset: 0, filters: [...filters, f] })}
              />

              <div className="flex items-center gap-1 ml-auto">
                <select
                  className={inputCls + " w-auto"}
                  value={limit}
                  onChange={(e) => {
                    patch({ offset: 0 });
                    setLimit(Number(e.target.value));
                  }}
                >
                  {[50, 100, 250, 500, 1000].map((n) => (
                    <option key={n} value={n}>
                      {n} 行/頁
                    </option>
                  ))}
                </select>
                <Btn disabled={offset === 0} onClick={() => patch({ offset: Math.max(0, offset - limit) })}>
                  ←
                </Btn>
                <span className="text-[11px] text-muted tnum px-1">
                  {page} / {nf(pages)}
                </span>
                <Btn disabled={!data || offset + limit >= data.total} onClick={() => patch({ offset: offset + limit })}>
                  →
                </Btn>
                <a
                  className="text-[12px] px-2.5 py-1 rounded border border-line bg-surface hover:bg-surface-2 text-ink-2"
                  href={`/api/table?${new URLSearchParams({
                    schema: sel.schema,
                    table: sel.name,
                    limit: "5000",
                    format: "csv",
                    ...(q ? { q } : {}),
                    ...(filters.length ? { filters: JSON.stringify(filters) } : {}),
                    ...(orderBy ? { orderBy, dir } : {}),
                  })}`}
                >
                  CSV
                </a>
              </div>

              {filters.length > 0 && (
                <div className="w-full flex items-center gap-1.5 flex-wrap pt-1">
                  {filters.map((f, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 text-[11px] bg-water-soft text-water-ink border border-water/30 rounded px-1.5 py-0.5"
                    >
                      <code className="font-mono">{f.col}</code>
                      {OPS.find((o) => o.v === f.op)?.label}
                      {f.val && <b className="font-semibold">{f.val}</b>}
                      <button
                        className="text-water/70 hover:text-bad"
                        onClick={() => patch({ filters: filters.filter((_, j) => j !== i), offset: 0 })}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  <button className="text-[11px] text-muted underline" onClick={() => patch({ filters: [], offset: 0 })}>
                    すべて解除
                  </button>
                </div>
              )}
            </div>

            {/* 結果 */}
            <div className="flex-1 min-h-0 flex">
              <div className="flex-1 min-w-0 flex flex-col">
                <div className="px-3.5 py-1 text-[11px] text-muted border-b border-line flex items-center gap-3">
                  {loading ? (
                    <Spinner label="読み込み中" />
                  ) : error ? (
                    <span className="text-bad">{error}</span>
                  ) : data ? (
                    <>
                      <span className="tnum">
                        {nf(data.total)}
                        {!data.totalIsExact && "+"} 行が該当
                      </span>
                      <span className="tnum">{data.elapsedMs.toFixed(0)} ms</span>
                      <code className="font-mono text-[10px] text-muted truncate">{data.sql}</code>
                    </>
                  ) : null}
                </div>
                <div className="flex-1 min-h-0">
                  {data && (
                    <DataGrid
                      columns={data.columns}
                      rows={data.rows}
                      orderBy={orderBy}
                      dir={dir}
                      onSort={(c) =>
                        patch(
                          orderBy === c
                            ? { offset: 0, dir: dir === "asc" ? "desc" : "asc" }
                            : { offset: 0, orderBy: c, dir: "asc" },
                        )
                      }
                      onColumnClick={(c) => patch({ statsColumn: c })}
                    />
                  )}
                </div>
              </div>

              {stats && (
                <aside className="w-64 shrink-0 border-l border-line bg-surface overflow-y-auto thin-scroll">
                  <div className="px-3 py-2 border-b border-line flex items-center">
                    <div>
                      <div className="text-[12px] font-mono font-semibold">{stats.column}</div>
                      <div className="text-[10px] text-muted">{stats.type || "型指定なし"}</div>
                    </div>
                    <button className="ml-auto text-muted hover:text-ink" onClick={() => patch({ statsColumn: null })}>
                      ×
                    </button>
                  </div>
                  <div className="p-3 space-y-2 text-[11px]">
                    <div className="flex justify-between">
                      <span className="text-muted">異なる値</span>
                      <span className="tnum">{nf(stats.distinct_n)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted">空/NULL</span>
                      <span className="tnum">
                        {nf(stats.nulls)}（{((stats.nulls / Math.max(stats.n, 1)) * 100).toFixed(1)}%）
                      </span>
                    </div>
                    {stats.numeric && (
                      <div className="pt-1 border-t border-line space-y-1">
                        <div className="flex justify-between">
                          <span className="text-muted">最小</span>
                          <span className="tnum">{nf(stats.numeric.min, 4)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted">平均</span>
                          <span className="tnum">{nf(stats.numeric.avg, 4)}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted">最大</span>
                          <span className="tnum">{nf(stats.numeric.max, 4)}</span>
                        </div>
                      </div>
                    )}
                    <div className="pt-1 border-t border-line">
                      <div className="text-muted mb-1">頻出値（クリックで絞り込み）</div>
                      {stats.top.map((t, i) => {
                        const pct = (t.n / Math.max(stats.n, 1)) * 100;
                        return (
                          <button
                            key={i}
                            className="w-full text-left group relative py-0.5"
                            onClick={() =>
                              patch({
                                offset: 0,
                                filters: [...filters, { col: stats.column, op: "=", val: String(t.value) }],
                              })
                            }
                          >
                            <div
                              className="absolute inset-y-0 left-0 bg-water-soft rounded-sm"
                              style={{ width: `${Math.max(pct, 1.5)}%` }}
                            />
                            <div className="relative flex gap-2 px-1">
                              <span className="truncate group-hover:text-water-ink">{String(t.value)}</span>
                              <span className="ml-auto tnum text-muted shrink-0">{nf(t.n)}</span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </aside>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FilterBuilder({ columns, onAdd }: { columns: ColumnInfo[]; onAdd: (f: Filter) => void }) {
  const [colPref, setCol] = React.useState("");
  const [op, setOp] = React.useState<FilterOp>("contains");
  const [val, setVal] = React.useState("");
  // テーブルが変わって列が入れ替わったら、先頭の列に戻す（状態は書き換えない）
  const col = columns.some((c) => c.name === colPref) ? colPref : (columns[0]?.name ?? "");
  const needsVal = op !== "isnull" && op !== "notnull";
  return (
    <form
      className="flex items-center gap-1"
      onSubmit={(e) => {
        e.preventDefault();
        if (!col) return;
        if (needsVal && !val) return;
        onAdd({ col, op, val: needsVal ? val : undefined });
        setVal("");
      }}
    >
      <select className={inputCls + " w-auto max-w-40"} value={col} onChange={(e) => setCol(e.target.value)}>
        {columns.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </select>
      <select className={inputCls + " w-auto"} value={op} onChange={(e) => setOp(e.target.value as FilterOp)}>
        {OPS.map((o) => (
          <option key={o.v} value={o.v}>
            {o.label}
          </option>
        ))}
      </select>
      {needsVal && (
        <input className={inputCls + " w-28"} placeholder="値" value={val} onChange={(e) => setVal(e.target.value)} />
      )}
      <Btn type="submit">＋条件</Btn>
    </form>
  );
}
