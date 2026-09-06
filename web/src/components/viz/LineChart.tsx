"use client";

import * as React from "react";
import { useSize } from "./useSize";
import { linear, log, extent, niceTicks, fmt, type LinearScale } from "./scales";
import { INK } from "./palette";

export interface LinePoint {
  x: number;
  y: number | null;
  /** 定量下限未満（value_raw が "<..."）。中抜きで描き、値としては信用しない */
  censored?: boolean;
  n?: number;
}

export interface LineSeries {
  key: string;
  label: string;
  color: string;
  points: LinePoint[];
  dashed?: boolean;
  /** 強調しない背景系列（スパゲッティの地の部分） */
  muted?: boolean;
}

export interface Annotation {
  x: number;
  label: string;
  color?: string;
}

export interface XBand {
  x0: number;
  x1: number;
  label?: string;
}

export function LineChart({
  series,
  height = 260,
  yLabel,
  unit,
  xFormat,
  xTicks,
  yScaleType = "linear",
  yZero = false,
  annotations,
  bands,
  directLabels = true,
  onPointClick,
  emptyMessage = "データがありません",
}: {
  series: LineSeries[];
  height?: number;
  yLabel?: string;
  unit?: string | null;
  xFormat: (x: number) => string;
  /** 明示的な x 目盛り。省略時は等間隔で自動 */
  xTicks?: number[];
  yScaleType?: "linear" | "log";
  yZero?: boolean;
  annotations?: Annotation[];
  bands?: XBand[];
  directLabels?: boolean;
  onPointClick?: (s: LineSeries, p: LinePoint) => void;
  emptyMessage?: string;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [hoverX, setHoverX] = React.useState<number | null>(null);

  const allPoints = React.useMemo(() => series.flatMap((s) => s.points), [series]);
  const hasData = allPoints.some((p) => p.y !== null && Number.isFinite(p.y));

  const m = { top: 10, right: directLabels ? 92 : 16, bottom: 26, left: 52 };
  const w = Math.max(size.w, 240);
  const innerW = Math.max(w - m.left - m.right, 40);
  const innerH = Math.max(height - m.top - m.bottom, 40);

  const xDomain = React.useMemo<[number, number]>(() => {
    const xs = allPoints.map((p) => p.x);
    return xs.length ? [Math.min(...xs), Math.max(...xs)] : [0, 1];
  }, [allPoints]);
  const x = linear(xDomain[0] === xDomain[1] ? [xDomain[0] - 1, xDomain[1] + 1] : xDomain, [0, innerW]);

  const ysRaw = allPoints.map((p) => p.y).filter((v): v is number => v !== null && Number.isFinite(v));
  let [ylo, yhi] = extent(ysRaw);
  if (yScaleType === "linear") {
    if (yZero) ylo = Math.min(0, ylo);
    const pad = (yhi - ylo) * 0.08 || Math.abs(yhi) * 0.1 || 1;
    ylo -= pad;
    yhi += pad;
    if (yZero) ylo = Math.min(0, ylo);
  }
  const y: LinearScale =
    yScaleType === "log"
      ? log([Math.max(ylo, 1e-6), yhi], [innerH, 0])
      : linear([ylo, yhi], [innerH, 0]);

  const yTickVals = yScaleType === "log" ? y.ticks() : niceTicks(ylo, yhi, 5);
  const xTickVals = xTicks ?? niceTicks(xDomain[0], xDomain[1], Math.min(8, Math.max(2, Math.floor(innerW / 80))));

  // ホバー中の x に最も近い各系列の点
  const hovered = React.useMemo(() => {
    if (hoverX === null) return null;
    const out: { s: LineSeries; p: LinePoint }[] = [];
    let bestX: number | null = null;
    for (const s of series) {
      let best: LinePoint | null = null;
      let bestD = Infinity;
      for (const p of s.points) {
        if (p.y === null) continue;
        const d = Math.abs(p.x - hoverX);
        if (d < bestD) {
          bestD = d;
          best = p;
        }
      }
      if (best && bestD < (xDomain[1] - xDomain[0]) / 12) {
        out.push({ s, p: best });
        if (bestX === null || Math.abs(best.x - hoverX) < Math.abs(bestX - hoverX)) bestX = best.x;
      }
    }
    if (!out.length || bestX === null) return null;
    const snapped = out.filter((o) => o.p.x === bestX);
    return { x: bestX, items: (snapped.length ? snapped : out).sort((a, b) => (b.p.y ?? 0) - (a.p.y ?? 0)) };
  }, [hoverX, series, xDomain]);

  if (!hasData) {
    return (
      <div ref={ref} style={{ height }} className="flex items-center justify-center text-[12px] text-muted">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div ref={ref} className="relative" style={{ height }}>
      <svg
        width="100%"
        height={height}
        role="img"
        aria-label={yLabel ? `${yLabel}の時系列` : "時系列グラフ"}
        onMouseLeave={() => setHoverX(null)}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const px = e.clientX - rect.left - m.left;
          if (px < -4 || px > innerW + 4) setHoverX(null);
          else setHoverX(x.invert(px));
        }}
      >
        <g transform={`translate(${m.left},${m.top})`}>
          {/* 期間の帯（比較対象など） */}
          {bands?.map((b, i) => (
            <g key={i}>
              <rect
                x={x(b.x0)}
                y={0}
                width={Math.max(x(b.x1) - x(b.x0), 1)}
                height={innerH}
                fill="var(--water-soft)"
                opacity={0.7}
              />
              {b.label && (
                <text x={x(b.x0) + 4} y={11} fontSize={9.5} fill={INK.muted}>
                  {b.label}
                </text>
              )}
            </g>
          ))}

          {/* 目盛り線（実線ヘアライン） */}
          {yTickVals.map((t) => (
            <line key={t} x1={0} x2={innerW} y1={y(t)} y2={y(t)} stroke={INK.grid} strokeWidth={1} />
          ))}
          {yTickVals.map((t) => (
            <text key={"l" + t} x={-7} y={y(t) + 3.5} textAnchor="end" fontSize={10} fill={INK.muted} className="tnum">
              {fmt(t)}
            </text>
          ))}
          {xTickVals.map((t) => (
            <text key={t} x={x(t)} y={innerH + 15} textAnchor="middle" fontSize={10} fill={INK.muted} className="tnum">
              {xFormat(t)}
            </text>
          ))}
          <line x1={0} x2={innerW} y1={innerH} y2={innerH} stroke={INK.axis} strokeWidth={1} />

          {/* 注記（台風など） */}
          {annotations?.map((a, i) => (
            <g key={i}>
              <line
                x1={x(a.x)}
                x2={x(a.x)}
                y1={0}
                y2={innerH}
                stroke={a.color ?? INK.axis}
                strokeWidth={1.5}
                opacity={0.6}
              />
              <text x={x(a.x) + 3} y={10} fontSize={9.5} fill={a.color ?? INK.secondary}>
                {a.label}
              </text>
            </g>
          ))}

          {/* 線 */}
          {series.map((s) => {
            const segs = toSegments(s.points);
            return (
              <g key={s.key} opacity={s.muted ? 0.28 : 1}>
                {segs.map((seg, i) => (
                  <path
                    key={i}
                    d={seg.map((p, j) => `${j === 0 ? "M" : "L"}${x(p.x)},${y(p.y as number)}`).join(" ")}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={s.muted ? 1.2 : 2}
                    strokeDasharray={s.dashed ? "4 3" : undefined}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                ))}
                {/* 検出下限未満の点は中抜きで描く */}
                {s.points
                  .filter((p) => p.censored && p.y !== null)
                  .map((p, i) => (
                    <circle
                      key={i}
                      cx={x(p.x)}
                      cy={y(p.y as number)}
                      r={3}
                      fill={INK.surface}
                      stroke={s.color}
                      strokeWidth={1.5}
                    />
                  ))}
              </g>
            );
          })}

          {/* 直接ラベル（4系列以下のとき、線の終端に） */}
          {directLabels &&
            series.length <= 4 &&
            series.map((s) => {
              const last = [...s.points].reverse().find((p) => p.y !== null);
              if (!last) return null;
              return (
                <text
                  key={s.key}
                  x={x(last.x) + 6}
                  y={y(last.y as number) + 3.5}
                  fontSize={10.5}
                  fill={INK.secondary}
                  fontWeight={500}
                >
                  {s.label.length > 8 ? s.label.slice(0, 7) + "…" : s.label}
                </text>
              );
            })}

          {/* クロスヘア */}
          {hovered && (
            <g pointerEvents="none">
              <line x1={x(hovered.x)} x2={x(hovered.x)} y1={0} y2={innerH} stroke={INK.axis} strokeWidth={1} />
              {hovered.items.map((it) => (
                <circle
                  key={it.s.key}
                  cx={x(it.p.x)}
                  cy={y(it.p.y as number)}
                  r={4.5}
                  fill={it.s.color}
                  stroke={INK.surface}
                  strokeWidth={2}
                />
              ))}
            </g>
          )}

          {/* クリック用の広い当たり判定 */}
          {onPointClick &&
            series.flatMap((s) =>
              s.points
                .filter((p) => p.y !== null)
                .map((p, i) => (
                  <circle
                    key={s.key + i}
                    cx={x(p.x)}
                    cy={y(p.y as number)}
                    r={9}
                    fill="transparent"
                    style={{ cursor: "pointer" }}
                    onClick={() => onPointClick(s, p)}
                  />
                )),
            )}
        </g>
      </svg>

      {hovered && (
        <Tooltip
          left={m.left + x(hovered.x)}
          width={w}
          items={hovered.items.map((it) => ({
            color: it.s.color,
            label: it.s.label,
            value: fmt(it.p.y, unit) + (it.p.censored ? "（下限未満）" : "") + (it.p.n ? ` / n=${it.p.n}` : ""),
          }))}
          title={xFormat(hovered.x)}
        />
      )}
    </div>
  );
}

function toSegments(points: LinePoint[]): LinePoint[][] {
  const sorted = [...points].sort((a, b) => a.x - b.x);
  const out: LinePoint[][] = [];
  let cur: LinePoint[] = [];
  for (const p of sorted) {
    if (p.y === null || !Number.isFinite(p.y)) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push(p);
  }
  if (cur.length) out.push(cur);
  return out;
}

export function Tooltip({
  left,
  width,
  title,
  items,
}: {
  left: number;
  width: number;
  title: string;
  items: { color: string; label: string; value: string }[];
}) {
  const flip = left > width * 0.6;
  return (
    <div
      className="pointer-events-none absolute top-2 z-10 card shadow-sm px-2 py-1.5 text-[11px] max-w-[240px]"
      style={flip ? { right: width - left + 10 } : { left: left + 10 }}
    >
      <div className="font-semibold mb-0.5 tnum">{title}</div>
      {items.slice(0, 10).map((it, i) => (
        <div key={i} className="flex items-center gap-1.5 leading-tight">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: it.color }} />
          <span className="truncate text-ink-2">{it.label}</span>
          <span className="ml-auto tnum font-medium">{it.value}</span>
        </div>
      ))}
      {items.length > 10 && <div className="text-muted">ほか {items.length - 10} 件</div>}
    </div>
  );
}
