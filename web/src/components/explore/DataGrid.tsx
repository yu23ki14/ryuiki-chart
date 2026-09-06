"use client";

import * as React from "react";

export interface GridColumn {
  name: string;
  type?: string;
}

export function DataGrid({
  columns,
  rows,
  orderBy,
  dir,
  onSort,
  onColumnClick,
  maxHeight = "100%",
}: {
  columns: GridColumn[];
  rows: unknown[][];
  orderBy?: string;
  dir?: "asc" | "desc";
  onSort?: (col: string) => void;
  onColumnClick?: (col: string) => void;
  maxHeight?: string;
}) {
  const [cell, setCell] = React.useState<{ col: string; value: unknown } | null>(null);

  return (
    <>
      <div className="overflow-auto thin-scroll h-full" style={{ maxHeight }}>
        <table className="dtable">
          <thead>
            <tr>
              <th className="w-10 text-right text-muted font-normal">#</th>
              {columns.map((c) => {
                const sorted = orderBy === c.name;
                return (
                  <th key={c.name}>
                    <span className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        className="hover:text-water-ink"
                        onClick={() => onColumnClick?.(c.name)}
                        title="この列の要約を見る"
                      >
                        {c.name}
                      </button>
                      {onSort && (
                        <button
                          type="button"
                          onClick={() => onSort(c.name)}
                          className={`text-[9px] leading-none px-0.5 ${sorted ? "text-water" : "text-line-strong hover:text-muted"}`}
                          title="並べ替え"
                        >
                          {sorted ? (dir === "desc" ? "▼" : "▲") : "⇅"}
                        </button>
                      )}
                      {c.type && <span className="text-[9px] text-muted font-normal">{c.type.toLowerCase()}</span>}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="num text-muted text-[10.5px]">{i + 1}</td>
                {r.map((v, j) => {
                  const isNum = typeof v === "number";
                  const isNull = v === null || v === undefined;
                  const s = isNull ? "NULL" : typeof v === "object" ? "[blob]" : String(v);
                  return (
                    <td
                      key={j}
                      className={`${isNum ? "num" : ""} ${isNull ? "null" : ""}`}
                      title={s.length > 40 ? s : undefined}
                      onClick={() => s.length > 40 && setCell({ col: columns[j]?.name ?? "", value: v })}
                    >
                      {isNum ? formatNum(v as number) : s}
                    </td>
                  );
                })}
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="text-center text-muted py-8">
                  該当する行がありません
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {cell && (
        <div
          className="fixed inset-0 z-50 bg-ink/30 flex items-center justify-center p-8"
          onClick={() => setCell(null)}
        >
          <div className="card max-w-2xl w-full max-h-[70vh] overflow-auto thin-scroll" onClick={(e) => e.stopPropagation()}>
            <div className="px-3 py-2 border-b border-line text-[12px] font-semibold">{cell.col}</div>
            <pre className="p-3 text-[12px] whitespace-pre-wrap break-all font-mono">{String(cell.value)}</pre>
          </div>
        </div>
      )}
    </>
  );
}

function formatNum(n: number): string {
  if (!Number.isFinite(n)) return String(n);
  if (Number.isInteger(n)) return n.toLocaleString("ja-JP");
  return n.toLocaleString("ja-JP", { maximumFractionDigits: 6 });
}
