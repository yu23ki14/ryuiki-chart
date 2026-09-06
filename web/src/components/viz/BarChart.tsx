"use client";

import * as React from "react";
import { useSize } from "./useSize";
import { linear, band, niceTicks, fmt } from "./scales";
import { INK, SERIES } from "./palette";

export interface BarDatum {
  key: string;
  label: string;
  value: number;
  color?: string;
  note?: string;
}

/** 横棒。順位・大きさの比較用。1系列は必ず1色（値で塗り分けない）。 */
export function BarChart({
  data,
  height,
  unit,
  color = SERIES[0],
  maxLabelWidth = 150,
  onClick,
  highlightKey,
  valueFormat = (v: number) => fmt(v, unit),
}: {
  data: BarDatum[];
  height?: number;
  unit?: string | null;
  color?: string;
  maxLabelWidth?: number;
  onClick?: (d: BarDatum) => void;
  highlightKey?: string;
  valueFormat?: (v: number) => string;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hover, setHover] = React.useState<string | null>(null);
  const rowH = 20;
  const h = height ?? data.length * rowH + 26;
  const m = { top: 4, right: 56, bottom: 20, left: maxLabelWidth };
  const w = Math.max(size.w, 240);
  const innerW = Math.max(w - m.left - m.right, 40);
  const innerH = Math.max(h - m.top - m.bottom, 20);

  const max = Math.max(...data.map((d) => d.value), 0);
  const x = linear([0, max || 1], [0, innerW]);
  const yb = band(data.map((d) => d.key), [0, innerH], 0.25);
  const ticks = niceTicks(0, max || 1, 4);

  return (
    <div ref={ref} style={{ height: h }}>
      <svg width="100%" height={h} role="img">
        <g transform={`translate(${m.left},${m.top})`}>
          {ticks.map((t) => (
            <line key={t} x1={x(t)} x2={x(t)} y1={0} y2={innerH} stroke={INK.grid} strokeWidth={1} />
          ))}
          {ticks.map((t) => (
            <text key={"t" + t} x={x(t)} y={innerH + 13} textAnchor="middle" fontSize={9.5} fill={INK.muted} className="tnum">
              {fmt(t)}
            </text>
          ))}
          {data.map((d) => {
            const yy = yb.at(d.key);
            const bw = Math.max(x(d.value), 2);
            const dim = highlightKey && highlightKey !== d.key;
            return (
              <g
                key={d.key}
                opacity={dim ? 0.35 : 1}
                onMouseEnter={() => setHover(d.key)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onClick?.(d)}
                style={onClick ? { cursor: "pointer" } : undefined}
              >
                <rect x={-m.left} y={yy - 2} width={m.left + innerW + m.right} height={yb.bandwidth + 4} fill={hover === d.key ? "var(--water-soft)" : "transparent"} />
                <text x={-8} y={yy + yb.bandwidth / 2 + 3.5} textAnchor="end" fontSize={11} fill={INK.secondary}>
                  {d.label.length > 20 ? d.label.slice(0, 19) + "…" : d.label}
                </text>
                <rect x={0} y={yy} width={bw} height={yb.bandwidth} rx={3} fill={d.color ?? color} />
                <text
                  x={bw + 5}
                  y={yy + yb.bandwidth / 2 + 3.5}
                  fontSize={10.5}
                  fill={INK.secondary}
                  className="tnum"
                >
                  {valueFormat(d.value)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}

/** 縦棒（時間軸に沿った量。降水量など） */
export function ColumnChart({
  data,
  height = 90,
  color = SERIES[1],
  xFormat,
  unit,
  xDomain,
}: {
  data: { x: number; value: number }[];
  height?: number;
  color?: string;
  xFormat: (x: number) => string;
  unit?: string | null;
  /** 上下の図と x 軸を揃えるために外から渡す */
  xDomain?: [number, number];
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hover, setHover] = React.useState<number | null>(null);
  const m = { top: 6, right: 92, bottom: 18, left: 52 };
  const w = Math.max(size.w, 240);
  const innerW = Math.max(w - m.left - m.right, 40);
  const innerH = Math.max(height - m.top - m.bottom, 20);

  const xs = data.map((d) => d.x);
  const dom: [number, number] = xDomain ?? [Math.min(...xs, 0), Math.max(...xs, 1)];
  const x = linear(dom, [0, innerW]);
  const max = Math.max(...data.map((d) => d.value), 1);
  const y = linear([0, max], [innerH, 0]);
  const bw = Math.max(Math.min(innerW / Math.max(data.length, 1) - 1, 14), 1);

  return (
    <div ref={ref} style={{ height }} className="relative">
      <svg width="100%" height={height} role="img" onMouseLeave={() => setHover(null)}>
        <g transform={`translate(${m.left},${m.top})`}>
          <line x1={0} x2={innerW} y1={innerH} y2={innerH} stroke={INK.axis} />
          <text x={-7} y={9} textAnchor="end" fontSize={9.5} fill={INK.muted} className="tnum">
            {fmt(max)}
          </text>
          {data.map((d, i) => {
            const hh = Math.max(innerH - y(d.value), d.value > 0 ? 1.5 : 0);
            return (
              <rect
                key={i}
                x={x(d.x) - bw / 2}
                y={innerH - hh}
                width={bw}
                height={hh}
                rx={Math.min(2, bw / 2)}
                fill={color}
                opacity={hover === null || hover === i ? 0.85 : 0.4}
                onMouseEnter={() => setHover(i)}
              />
            );
          })}
        </g>
      </svg>
      {hover !== null && data[hover] && (
        <div className="pointer-events-none absolute top-0 card shadow-sm px-2 py-1 text-[11px]" style={{ left: Math.min(m.left + x(data[hover].x) + 8, w - 130) }}>
          <span className="tnum font-semibold">{xFormat(data[hover].x)}</span>
          <span className="ml-2 tnum">{fmt(data[hover].value, unit)}</span>
        </div>
      )}
    </div>
  );
}
