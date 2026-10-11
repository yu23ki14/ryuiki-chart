import * as React from "react";
import { INK } from "@/components/viz/palette";
import {
  A10_STYLE,
  A15_STYLE,
  A45_FILL_VERIFIED,
  HAZARD_STYLE,
  NOTE_MIN_ZOOM,
  NOTE_TRUNCATED,
  PA_COLORS,
  belowMinZoom,
  type OverlayDecl,
  type OverlayId,
} from "@/lib/map/overlay-layers";

export interface OverlayLegendData {
  truncated?: boolean;
  sources?: { source_id: string; note?: string | null; license?: string | null }[];
}

function Swatch({ color, opacity, line }: { color: string; opacity: number; line?: boolean }) {
  return (
    <span
      className="inline-block w-3 h-3 rounded-sm shrink-0"
      style={line ? { border: `2px solid ${color}`, background: "transparent" } : { background: color, opacity, border: `1px solid ${INK.surface}` }}
      aria-hidden
    />
  );
}

/** 色には必ず文字ラベルを添える（STATUS の規約）。A10 の面積は出さない（入れ子で足せない）。 */
export function OverlayLegend({
  active,
  zoom,
  data,
}: {
  active: readonly OverlayDecl[];
  zoom: number | null;
  data: Partial<Record<OverlayId, OverlayLegendData | null>>;
}) {
  if (active.length === 0) return null;
  return (
    <div className="mt-2 border-t border-line pt-2">
      {active.map((d) => {
        const dd = data[d.id];
        const notes = (dd?.sources ?? []).filter((s) => s.note);
        return (
          <div key={d.id} className="mb-2 last:mb-0">
            <div className="text-[10.5px] font-semibold mb-1">{d.label}</div>
            {d.id === "hazard" && (
              <ul className="space-y-0.5">
                {(Object.keys(HAZARD_STYLE) as (keyof typeof HAZARD_STYLE)[]).map((k) => (
                  <li key={k} className="flex items-center gap-1.5 text-[10px] text-ink-2">
                    <Swatch color={HAZARD_STYLE[k].color} opacity={HAZARD_STYLE[k].opacity} />
                    {HAZARD_STYLE[k].label}
                  </li>
                ))}
                <li className="text-[10px] text-muted leading-snug">特別警戒区域は警戒区域の内側にある。</li>
              </ul>
            )}
            {d.id === "pa_a10" && (
              <ul className="space-y-0.5">
                {A10_STYLE.map((s) => (
                  <li key={s.code} className="flex items-center gap-1.5 text-[10px] text-ink-2">
                    <Swatch color={PA_COLORS.pa_a10} opacity={s.opacity} />
                    {s.label}
                  </li>
                ))}
              </ul>
            )}
            {d.id === "pa_a15" && (
              <ul className="space-y-0.5">
                {A15_STYLE.map((s) => (
                  <li key={s.code} className="flex items-center gap-1.5 text-[10px] text-ink-2">
                    <Swatch color={PA_COLORS.pa_a15} opacity={s.opacity} />
                    {s.label}
                  </li>
                ))}
              </ul>
            )}
            {d.id === "pa_a45" && (
              <div className="flex items-center gap-1.5 text-[10px] text-ink-2">
                <Swatch color={PA_COLORS.pa_a45} opacity={0.3} line={!A45_FILL_VERIFIED} />
                国有林{A45_FILL_VERIFIED ? "" : "（境界線）"}
              </div>
            )}
            {belowMinZoom(d, zoom) && <p className="text-[10px] text-muted mt-0.5">{NOTE_MIN_ZOOM}</p>}
            {dd?.truncated && <p className="text-[10px] text-muted mt-0.5 leading-snug">{NOTE_TRUNCATED}</p>}
            {notes.map((s) => (
              <p key={s.source_id} className="text-[10px] text-muted mt-0.5 leading-snug">
                {s.note}
              </p>
            ))}
          </div>
        );
      })}
    </div>
  );
}
