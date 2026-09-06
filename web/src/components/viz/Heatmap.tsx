"use client";

import * as React from "react";
import { useSize } from "./useSize";
import { SEQ, INK } from "./palette";
import { fmt } from "./scales";

export interface HeatCell {
  x: number | string;
  y: number | string;
  v: number | null;
  n?: number;
}

/** 逐次ランプ（単一色相・明→暗）のセル図。凡例を必ず付ける。 */
export function Heatmap({
  cells,
  xDomain,
  yDomain,
  xLabel,
  yLabel,
  xFormat = String,
  yFormat = String,
  unit,
  height,
  cellGap = 2,
}: {
  cells: HeatCell[];
  xDomain: (number | string)[];
  yDomain: (number | string)[];
  xLabel?: string;
  yLabel?: string;
  xFormat?: (v: number | string) => string;
  yFormat?: (v: number | string) => string;
  unit?: string | null;
  height?: number;
  cellGap?: number;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hover, setHover] = React.useState<HeatCell | null>(null);
  const m = { top: 6, right: 8, bottom: 22, left: 46 };
  const h = height ?? yDomain.length * 18 + m.top + m.bottom;
  const w = Math.max(size.w, 260);
  const innerW = Math.max(w - m.left - m.right, 40);
  const innerH = Math.max(h - m.top - m.bottom, 30);
  const cw = innerW / Math.max(xDomain.length, 1);
  const ch = innerH / Math.max(yDomain.length, 1);

  const vals = cells.map((c) => c.v).filter((v): v is number => v !== null && Number.isFinite(v));
  const lo = vals.length ? Math.min(...vals) : 0;
  const hi = vals.length ? Math.max(...vals) : 1;
  const colorOf = (v: number | null) => {
    if (v === null || !Number.isFinite(v)) return "#f2f4f3";
    const t = (v - lo) / (hi - lo || 1);
    return SEQ[Math.min(SEQ.length - 1, Math.max(0, Math.round(t * (SEQ.length - 1))))];
  };

  const xi = new Map(xDomain.map((v, i) => [String(v), i]));
  const yi = new Map(yDomain.map((v, i) => [String(v), i]));

  return (
    <div ref={ref} className="relative">
      <svg width="100%" height={h} role="img" onMouseLeave={() => setHover(null)}>
        <g transform={`translate(${m.left},${m.top})`}>
          {cells.map((c, i) => {
            const ix = xi.get(String(c.x));
            const iy = yi.get(String(c.y));
            if (ix === undefined || iy === undefined) return null;
            return (
              <rect
                key={i}
                x={ix * cw}
                y={iy * ch}
                width={Math.max(cw - cellGap, 1)}
                height={Math.max(ch - cellGap, 1)}
                rx={1.5}
                fill={colorOf(c.v)}
                stroke={hover === c ? INK.primary : "none"}
                strokeWidth={1}
                onMouseEnter={() => setHover(c)}
              />
            );
          })}
          {yDomain.map((y, i) => (
            <text key={String(y)} x={-6} y={i * ch + ch / 2 + 3.5} textAnchor="end" fontSize={9.5} fill={INK.muted}>
              {yFormat(y)}
            </text>
          ))}
          {xDomain.map((x, i) =>
            xDomain.length <= 24 || i % Math.ceil(xDomain.length / 16) === 0 ? (
              <text key={String(x)} x={i * cw + cw / 2} y={innerH + 13} textAnchor="middle" fontSize={9.5} fill={INK.muted}>
                {xFormat(x)}
              </text>
            ) : null,
          )}
        </g>
      </svg>

      <div className="flex items-center gap-2 px-2 pt-1">
        <span className="text-[10px] text-muted tnum">{fmt(lo, unit)}</span>
        <div className="flex h-2 rounded overflow-hidden flex-1 max-w-[160px]">
          {SEQ.map((c) => (
            <span key={c} className="flex-1" style={{ background: c }} />
          ))}
        </div>
        <span className="text-[10px] text-muted tnum">{fmt(hi, unit)}</span>
        {(xLabel || yLabel) && (
          <span className="text-[10px] text-muted ml-2">
            横: {xLabel} / 縦: {yLabel}
          </span>
        )}
      </div>

      {hover && (
        <div className="pointer-events-none absolute top-0 right-0 card shadow-sm px-2 py-1 text-[11px]">
          <span className="tnum">
            {yFormat(hover.y)} × {xFormat(hover.x)}
          </span>
          <span className="ml-2 font-medium tnum">{fmt(hover.v, unit)}</span>
          {hover.n != null && <span className="ml-1.5 text-muted tnum">n={hover.n}</span>}
        </div>
      )}
    </div>
  );
}
