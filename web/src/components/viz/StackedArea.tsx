"use client";

import * as React from "react";
import { useSize } from "./useSize";
import { linear, niceTicks, fmt, fmtCompact } from "./scales";
import { INK } from "./palette";

export interface StackSeries {
  key: string;
  label: string;
  color: string;
  /** x -> value */
  values: Map<number, number>;
}

/**
 * 積み上げ面。構成比の変化を見せる。
 * `normalize` を立てると 100% 積み上げになり、全体量の増減の影響を外して構成だけを見られる。
 */
export function StackedArea({
  series,
  xs,
  height = 240,
  xFormat,
  normalize = false,
  unit,
}: {
  series: StackSeries[];
  xs: number[];
  height?: number;
  xFormat: (x: number) => string;
  normalize?: boolean;
  unit?: string | null;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hoverX, setHoverX] = React.useState<number | null>(null);
  const m = { top: 8, right: 14, bottom: 24, left: 52 };
  const w = Math.max(size.w, 260);
  const innerW = Math.max(w - m.left - m.right, 40);
  const innerH = Math.max(height - m.top - m.bottom, 40);

  const x = linear([Math.min(...xs), Math.max(...xs)], [0, innerW]);
  const totals = new Map(xs.map((xx) => [xx, series.reduce((s, se) => s + (se.values.get(xx) ?? 0), 0)]));
  const maxTotal = normalize ? 1 : Math.max(...[...totals.values()], 1);
  const y = linear([0, maxTotal], [innerH, 0]);

  // 各系列の下端・上端
  const stacks: { s: StackSeries; pts: { x: number; y0: number; y1: number }[] }[] = [];
  const base = new Map(xs.map((xx) => [xx, 0]));
  for (const s of series) {
    const pts = xs.map((xx) => {
      const t = totals.get(xx) ?? 0;
      const raw = s.values.get(xx) ?? 0;
      const v = normalize ? (t > 0 ? raw / t : 0) : raw;
      const y0 = base.get(xx) ?? 0;
      const y1 = y0 + v;
      base.set(xx, y1);
      return { x: xx, y0, y1 };
    });
    stacks.push({ s, pts });
  }

  const hovered = hoverX === null ? null : xs.reduce((a, b) => (Math.abs(b - hoverX) < Math.abs(a - hoverX) ? b : a), xs[0]);

  return (
    <div ref={ref} className="relative" style={{ height }}>
      <svg
        width="100%"
        height={height}
        role="img"
        onMouseLeave={() => setHoverX(null)}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          setHoverX(x.invert(e.clientX - r.left - m.left));
        }}
      >
        <g transform={`translate(${m.left},${m.top})`}>
          {(normalize ? [0, 0.25, 0.5, 0.75, 1] : niceTicks(0, maxTotal, 4)).map((t) => (
            <g key={t}>
              <line x1={0} x2={innerW} y1={y(t)} y2={y(t)} stroke={INK.grid} />
              <text x={-7} y={y(t) + 3.5} textAnchor="end" fontSize={9.5} fill={INK.muted} className="tnum">
                {normalize ? `${Math.round(t * 100)}%` : fmtCompact(t)}
              </text>
            </g>
          ))}
          {stacks.map(({ s, pts }) => {
            const top = pts.map((p) => `${x(p.x)},${y(p.y1)}`).join(" L");
            const bottom = [...pts].reverse().map((p) => `${x(p.x)},${y(p.y0)}`).join(" L");
            return <path key={s.key} d={`M${top} L${bottom} Z`} fill={s.color} opacity={0.88} />;
          })}
          {niceTicks(Math.min(...xs), Math.max(...xs), 8).map((t) => (
            <text key={t} x={x(t)} y={innerH + 15} textAnchor="middle" fontSize={9.5} fill={INK.muted} className="tnum">
              {xFormat(t)}
            </text>
          ))}
          <line x1={0} x2={innerW} y1={innerH} y2={innerH} stroke={INK.axis} />
          {hovered !== null && (
            <line x1={x(hovered)} x2={x(hovered)} y1={0} y2={innerH} stroke={INK.primary} strokeWidth={1} opacity={0.5} />
          )}
        </g>
      </svg>
      {hovered !== null && (
        <div
          className="pointer-events-none absolute top-1 card shadow-sm px-2 py-1.5 text-[11px] max-w-[220px]"
          style={x(hovered) > innerW * 0.6 ? { right: 8 } : { left: m.left + x(hovered) + 10 }}
        >
          <div className="font-semibold mb-0.5 tnum">{xFormat(hovered)}</div>
          {[...series]
            .map((s) => ({ s, v: s.values.get(hovered) ?? 0 }))
            .filter((r) => r.v > 0)
            .sort((a, b) => b.v - a.v)
            .slice(0, 9)
            .map(({ s, v }) => (
              <div key={s.key} className="flex items-center gap-1.5 leading-tight">
                <span className="w-2 h-2 rounded-full shrink-0" style={{ background: s.color }} />
                <span className="truncate text-ink-2">{s.label}</span>
                <span className="ml-auto tnum font-medium">
                  {normalize
                    ? `${(((totals.get(hovered) ?? 0) > 0 ? v / (totals.get(hovered) as number) : 0) * 100).toFixed(1)}%`
                    : fmt(v, unit)}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
