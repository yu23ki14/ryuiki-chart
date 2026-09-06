"use client";

import * as React from "react";
import { useSize } from "./useSize";
import { INK } from "./palette";

export interface SlopeCategory {
  key: string;
  label: string;
  /** 大きいほど深刻。並び順に使う */
  rank: number;
}

export interface SlopeFlow {
  from: string;
  to: string;
  n: number;
  direction: "悪化" | "改善" | "横ばい";
}

const DIR_COLOR: Record<string, string> = {
  悪化: "#d03b3b",
  改善: "#2a78d6",
  横ばい: "#c3cfcc",
};

/**
 * 2時点のカテゴリ間の移動を、左右2列＋帯で見せる（サンキー図の簡略版）。
 * カテゴリは順序尺度なので、上下の位置そのものに意味がある。
 */
export function SlopeChart({
  categories,
  flows,
  leftLabel,
  rightLabel,
  height = 440,
  onFlowClick,
  highlight,
}: {
  categories: SlopeCategory[];
  flows: SlopeFlow[];
  leftLabel: string;
  rightLabel: string;
  height?: number;
  onFlowClick?: (f: SlopeFlow) => void;
  highlight?: string | null;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hover, setHover] = React.useState<SlopeFlow | null>(null);
  const w = Math.max(size.w, 320);
  const m = { top: 24, bottom: 8, left: 132, right: 132 };
  const innerH = height - m.top - m.bottom;
  const colW = 16;
  const xL = m.left;
  const xR = w - m.right - colW;

  const cats = React.useMemo(() => [...categories].sort((a, b) => b.rank - a.rank), [categories]);
  const leftTotals = new Map<string, number>();
  const rightTotals = new Map<string, number>();
  for (const f of flows) {
    leftTotals.set(f.from, (leftTotals.get(f.from) ?? 0) + f.n);
    rightTotals.set(f.to, (rightTotals.get(f.to) ?? 0) + f.n);
  }
  const total = flows.reduce((s, f) => s + f.n, 0) || 1;
  const gap = 6;
  const usableH = Math.max(innerH - gap * (cats.length - 1), 20);

  const posOf = (totals: Map<string, number>) => {
    const out = new Map<string, { y: number; h: number }>();
    let y = 0;
    for (const c of cats) {
      const v = totals.get(c.key) ?? 0;
      const h = (v / total) * usableH;
      out.set(c.key, { y, h });
      y += h + gap;
    }
    return out;
  };
  const L = posOf(leftTotals);
  const R = posOf(rightTotals);

  const lOffset = new Map<string, number>();
  const rOffset = new Map<string, number>();
  const ribbons = [...flows]
    .sort(
      (a, b) =>
        cats.findIndex((c) => c.key === b.from) - cats.findIndex((c) => c.key === a.from) || b.n - a.n,
    )
    .map((f) => {
      const l = L.get(f.from);
      const r = R.get(f.to);
      if (!l || !r) return null;
      const hh = (f.n / total) * usableH;
      const ly = l.y + (lOffset.get(f.from) ?? 0);
      const ry = r.y + (rOffset.get(f.to) ?? 0);
      lOffset.set(f.from, (lOffset.get(f.from) ?? 0) + hh);
      rOffset.set(f.to, (rOffset.get(f.to) ?? 0) + hh);
      return { f, ly, ry, hh };
    })
    .filter((x): x is { f: SlopeFlow; ly: number; ry: number; hh: number } => x !== null);

  return (
    <div ref={ref} className="relative" style={{ height }}>
      <svg width="100%" height={height} role="img" aria-label={`${leftLabel} から ${rightLabel} へのカテゴリー移動`}>
        <text x={xL + colW / 2} y={13} textAnchor="middle" fontSize={11} fontWeight={600} fill={INK.secondary}>
          {leftLabel}
        </text>
        <text x={xR + colW / 2} y={13} textAnchor="middle" fontSize={11} fontWeight={600} fill={INK.secondary}>
          {rightLabel}
        </text>
        <g transform={`translate(0,${m.top})`}>
          {ribbons.map((rb, i) => {
            const { f, ly, ry, hh } = rb;
            const x0 = xL + colW;
            const x1 = xR;
            const cx = (x0 + x1) / 2;
            const d = `M${x0},${ly} C${cx},${ly} ${cx},${ry} ${x1},${ry} L${x1},${ry + hh} C${cx},${ry + hh} ${cx},${ly + hh} ${x0},${ly + hh} Z`;
            const dim = highlight && highlight !== f.direction;
            return (
              <path
                key={i}
                d={d}
                fill={DIR_COLOR[f.direction]}
                opacity={hover === f ? 0.75 : dim ? 0.06 : 0.32}
                onMouseEnter={() => setHover(f)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onFlowClick?.(f)}
                style={onFlowClick ? { cursor: "pointer" } : undefined}
              />
            );
          })}

          {cats.map((c) => {
            const l = L.get(c.key);
            const r = R.get(c.key);
            return (
              <g key={c.key}>
                {l && l.h > 0 && (
                  <>
                    <rect x={xL} y={l.y} width={colW} height={Math.max(l.h, 1)} fill={INK.secondary} rx={2} />
                    <text x={xL - 6} y={l.y + l.h / 2 + 3.5} textAnchor="end" fontSize={10.5} fill={INK.secondary}>
                      {c.label}
                      <tspan fill={INK.muted}> {leftTotals.get(c.key)}</tspan>
                    </text>
                  </>
                )}
                {r && r.h > 0 && (
                  <>
                    <rect x={xR} y={r.y} width={colW} height={Math.max(r.h, 1)} fill={INK.secondary} rx={2} />
                    <text x={xR + colW + 6} y={r.y + r.h / 2 + 3.5} fontSize={10.5} fill={INK.secondary}>
                      {c.label}
                      <tspan fill={INK.muted}> {rightTotals.get(c.key)}</tspan>
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      {hover && (
        <div className="pointer-events-none absolute top-1 left-1/2 -translate-x-1/2 card shadow-sm px-2 py-1 text-[11px] whitespace-nowrap">
          <span className="font-medium">{hover.from}</span> → <span className="font-medium">{hover.to}</span>
          <span className="ml-2 tnum">{hover.n} 種</span>
          <span className="ml-1.5 font-medium" style={{ color: DIR_COLOR[hover.direction] }}>
            {hover.direction}
          </span>
        </div>
      )}
    </div>
  );
}
