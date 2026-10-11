"use client";

import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { INK, SERIES } from "@/components/viz/palette";
import { fmt } from "@/components/viz/scales";
import type { HazardKindPanel } from "@/lib/stories/amami";

const ROW_H = 26;
const LABEL_W = 84;
const VALUE_W = 52;
const BAR_W = 420;

/**
 * 市町村 × 現象の積み上げ棒。区分（警戒・特別警戒）ごとに別の面で、区分をまたいだ総数は棒にしない。
 * 棒の長さは全面で共通の目盛り。色は現象（凡例に文字ラベル）。
 */
export function HazardStacked({ panels }: { panels: HazardKindPanel[] }) {
  const phenomena = [...new Set(panels.flatMap((p) => p.phenomena))];
  const color = (ph: string) => SERIES[phenomena.indexOf(ph) % SERIES.length];
  const max = Math.max(...panels.flatMap((p) => p.municipalities.map((m) => m.total)), 1);
  const legend = phenomena.map((ph) => ({ label: ph, color: color(ph) }));
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {panels.map((p) => (
        <ChartFrame
          key={p.kind}
          title={p.kind}
          subtitle="市町村別の区域数（現象ごとに積み上げ）"
          legend={legend}
          note="特別警戒は警戒の内側にある。面積は区分をまたいで足さない。件数だけを示す。"
          table={
            <MiniTable
              columns={["市町村", ...p.phenomena, "計"]}
              rows={p.municipalities.map((m) => [m.name, ...p.phenomena.map((ph) => m.byPhenomenon[ph] ?? 0), m.total])}
            />
          }
        >
          <svg viewBox={`0 0 ${LABEL_W + BAR_W + VALUE_W} ${p.municipalities.length * ROW_H + 6}`} width="100%" role="img" aria-label={`${p.kind}の市町村別の区域数`}>
            {p.municipalities.map((m, i) => {
              let x = LABEL_W;
              return (
                <g key={m.name} transform={`translate(0,${i * ROW_H + 3})`}>
                  <text x={LABEL_W - 6} y={ROW_H / 2 + 3} textAnchor="end" fontSize={11} fill={INK.secondary}>
                    {m.name}
                  </text>
                  {p.phenomena.map((ph) => {
                    const w = ((m.byPhenomenon[ph] ?? 0) / max) * BAR_W;
                    const seg = <rect key={ph} x={x} y={3} width={w} height={ROW_H - 8} fill={color(ph)} />;
                    x += w;
                    return seg;
                  })}
                  <text x={x + 5} y={ROW_H / 2 + 3} fontSize={10.5} fill={INK.muted} className="tnum">
                    {fmt(m.total)}
                  </text>
                </g>
              );
            })}
          </svg>
        </ChartFrame>
      ))}
    </div>
  );
}
