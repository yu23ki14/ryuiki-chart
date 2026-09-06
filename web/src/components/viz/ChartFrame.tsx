"use client";

import * as React from "react";

/**
 * 図の外枠。凡例・出典・「表で見る」切替をすべての図に共通で付ける。
 * 色だけに意味を持たせない、という要件をここで担保する。
 */
export function ChartFrame({
  title,
  subtitle,
  legend,
  note,
  table,
  right,
  children,
  height,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  legend?: { label: string; color: string; dashed?: boolean }[];
  note?: React.ReactNode;
  /** 同じ数値を読める表。アクセシビリティ上の等価物 */
  table?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  height?: number;
}) {
  const [showTable, setShowTable] = React.useState(false);
  return (
    <figure className="card overflow-hidden">
      {(title || right) && (
        <figcaption className="flex items-start gap-3 px-3.5 pt-2.5 pb-2">
          <div className="min-w-0">
            {title && <h3 className="text-[13px] font-semibold leading-tight">{title}</h3>}
            {subtitle && <p className="text-[11px] text-muted mt-0.5 leading-snug">{subtitle}</p>}
          </div>
          <div className="ml-auto shrink-0 flex items-center gap-1.5">
            {right}
            {table && (
              <button
                onClick={() => setShowTable((v) => !v)}
                className="no-print text-[11px] px-1.5 py-0.5 rounded border border-line text-ink-2 hover:bg-surface-2"
                aria-pressed={showTable}
              >
                {showTable ? "図で見る" : "表で見る"}
              </button>
            )}
          </div>
        </figcaption>
      )}

      {legend && legend.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 px-3.5 pb-2">
          {legend.map((l) => (
            <li key={l.label} className="flex items-center gap-1.5 text-[11px] text-ink-2">
              <svg width="14" height="10" aria-hidden="true">
                <line
                  x1="0"
                  y1="5"
                  x2="14"
                  y2="5"
                  stroke={l.color}
                  strokeWidth="2.5"
                  strokeDasharray={l.dashed ? "3 2" : undefined}
                  strokeLinecap="round"
                />
              </svg>
              {l.label}
            </li>
          ))}
        </ul>
      )}

      <div style={height ? { height } : undefined} className="px-1">
        {showTable && table ? (
          <div className="overflow-auto thin-scroll max-h-full px-2.5 pb-2">{table}</div>
        ) : (
          children
        )}
      </div>

      {note && (
        <div className="px-3.5 py-2 text-[10.5px] text-muted leading-relaxed border-t border-line mt-1">{note}</div>
      )}
    </figure>
  );
}

/** 図の下に置く素の表（アクセシビリティ等価物） */
export function MiniTable({ columns, rows }: { columns: string[]; rows: (string | number | null)[][] }) {
  return (
    <table className="dtable text-[11px]">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((v, j) => (
              <td key={j} className={typeof v === "number" ? "num" : v === null ? "null" : ""}>
                {v === null ? "–" : typeof v === "number" ? v.toLocaleString("ja-JP", { maximumFractionDigits: 4 }) : v}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
