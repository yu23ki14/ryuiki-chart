"use client";

import * as React from "react";
import Link from "next/link";
import type { ToolCallMessagePartProps } from "@assistant-ui/react";
import { Spinner } from "@/components/ui";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { ChartFrame } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, ZONE_LABELS, INK } from "@/components/viz/palette";
import { shortVariable } from "@/lib/domain";
import { timeseriesUrl } from "@/lib/ai/links";
import { ProvenanceFooter, type Provenance } from "./ProvenanceFooter";
import { TOOL_LABEL } from "./ToolResultCard";

/**
 * get_timeseries だけの専用カード。既存の LineChart をそのまま使う（新しい作図コードは書かない）。
 * 証跡（SQL・件数・注記）は ToolResultCard と共通の ProvenanceFooter で、チャートの下に「そのまま」出す。
 */

interface Scope {
  type: "water" | "site" | "zone";
  name?: string;
  siteId?: string;
}
interface SiteLite {
  site_id: string;
  name: string;
}
/** meas_year / meas_month / meas_daily / zone_year の行を緩くまとめて受ける（grain によってどの列が来るかが違う） */
interface SeriesPoint {
  site_id?: string;
  zone?: number;
  year?: number;
  ym?: string;
  month?: number;
  d?: string;
  n?: number;
  avg?: number;
  value?: number;
  n_censored?: number;
  unit?: string | null;
}
interface TimeseriesData {
  scope: Scope;
  sites?: SiteLite[];
  grain: "year" | "month" | "day";
  kind?: "daily" | "annual";
  /** var_catalog 由来。月次・日次の点列には unit が入っていないのでこちらを使う。 */
  unit?: string | null;
  points: SeriesPoint[];
}
interface ToolResultShape {
  data?: TimeseriesData;
  provenance?: Provenance;
  caveats?: string[];
  truncated?: boolean;
  truncatedNote?: string;
}
/** get_timeseries の inputSchema（tools.ts）そのまま。variable は data 側に載らないので args から取る。 */
interface ToolArgs {
  variable?: string;
}

export function SeriesChartCard(props: ToolCallMessagePartProps) {
  const [open, setOpen] = React.useState(false);
  const { result, isError, status, args } = props;
  const label = TOOL_LABEL.get_timeseries;

  if (status.type === "running" && result === undefined) {
    return (
      <div className="my-1.5 rounded border border-line bg-surface-2 px-2.5 py-1.5">
        <Spinner label={`${label}…`} />
      </div>
    );
  }

  const r = (result ?? {}) as ToolResultShape;
  const data = r.data;
  const provenance = r.provenance;
  const caveats = r.caveats ?? [];
  const variable = (args as ToolArgs | undefined)?.variable;

  // データが無い/エラーのときは無理にチャートを描かず、証跡カードだけを出す（他ツールと同じ体裁）。
  if (!data || isError) {
    return (
      <div className="my-1.5 rounded border border-line bg-surface-2 text-[11px]">
        <ProvenanceFooter
          label={label}
          provenance={provenance}
          caveats={caveats}
          truncated={r.truncated}
          isError={isError}
          open={open}
          onToggle={() => setOpen((v) => !v)}
        />
      </div>
    );
  }

  const { series, unit, xFormat } = buildSeries(data);
  const link = variable
    ? timeseriesUrl({ variable, scope: data.scope, grain: data.grain, kind: data.kind })
    : null;

  // ChartFrame をそのまま使う（新しい作図コードは書かない）。証跡は ChartFrame の note スロットに
  // 置く。note は素の文字列専用ではなく ReactNode を受けるので、折りたたみ式の ProvenanceFooter を
  // そのまま渡せる——ToolResultCard 側の見た目を複製せずに済む。
  return (
    <div className="my-1.5">
      {r.truncatedNote && (
        <p className="text-[10.5px] text-warn font-medium mb-1 px-0.5">
          間引き表示 — 点が多いため一部を間引いて描画している（実件数は下の「根拠を見る」で確認できる）
        </p>
      )}
      <ChartFrame
        title={
          <>
            {scopeTitle(data.scope)}
            {variable && <> の {shortVariable(variable)}</>}
          </>
        }
        subtitle={`${grainLabel(data.grain)}${data.kind ? ` ・ ${data.kind === "daily" ? "検体値" : "年度集計値"}` : ""}`}
        legend={series.map((s) => ({ label: s.label, color: s.color }))}
        height={190}
        note={
          <ProvenanceFooter
            label={label}
            provenance={provenance}
            caveats={caveats}
            truncated={r.truncated}
            isError={isError}
            open={open}
            onToggle={() => setOpen((v) => !v)}
            className="-mx-3.5 -my-2"
            link={
              link && (
                <Link href={link} className="inline-block text-[10.5px] text-water-ink underline decoration-dotted">
                  時系列画面でこの表示を開く →
                </Link>
              )
            }
          />
        }
      >
        <LineChart
          series={series}
          height={190}
          unit={unit}
          xFormat={xFormat}
          directLabels={false}
          emptyMessage="この条件のデータがありません"
        />
      </ChartFrame>
    </div>
  );
}

function scopeTitle(scope: Scope): string {
  if (scope.type === "water") return scope.name ?? "水域";
  if (scope.type === "site") return scope.siteId ? `地点 ${scope.siteId}` : "地点";
  return "ゾーン別";
}

function grainLabel(grain: "year" | "month" | "day"): string {
  return grain === "year" ? "年平均" : grain === "month" ? "月平均" : "日次";
}

/** 'YYYY-MM' を「年 + 月/12」の数値に変換して連続軸に載せる（TimeseriesExplorer と同じ変換） */
function ymToX(ym: string): number {
  const y = Number(ym.slice(0, 4));
  const m = Number(ym.slice(5, 7));
  return y + (m - 0.5) / 12;
}
function xToYm(x: number): string {
  const y = Math.floor(x);
  const m = Math.min(12, Math.max(1, Math.round((x - y) * 12 + 0.5)));
  return `${y}-${String(m).padStart(2, "0")}`;
}

function buildSeries(data: TimeseriesData): {
  series: LineSeries[];
  unit: string | null;
  xFormat: (x: number) => string;
} {
  const { scope, grain, points } = data;
  const unit = data.unit ?? points.find((p) => p.unit)?.unit ?? null;

  if (scope.type === "zone") {
    const byZone = new Map<number, SeriesPoint[]>();
    for (const p of points) {
      if (p.zone == null) continue;
      if (!byZone.has(p.zone)) byZone.set(p.zone, []);
      byZone.get(p.zone)!.push(p);
    }
    const series: LineSeries[] = [...byZone.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([z, pts]) => ({
        key: `z${z}`,
        label: `${z}. ${ZONE_LABELS[z] ?? ""}`,
        color: ZONE_COLORS[z] ?? INK.muted,
        points: pts
          .map((p) => ({ x: Number(p.year), y: typeof p.avg === "number" ? p.avg : null, n: p.n }))
          .filter((p) => Number.isFinite(p.x))
          .sort((a, b) => a.x - b.x),
      }));
    return { series, unit, xFormat: (x) => String(Math.round(x)) };
  }

  // water / site スコープ: 色は「地点という実体」に固定する（TimeseriesExplorer と同じ考え方）。
  // sites は water スコープのときだけ埋まっている（site スコープは siteId 直指定で sites に触れないため）。
  const siteOrder = data.sites ?? [];
  const nameOf = (siteId: string) => siteOrder.find((s) => s.site_id === siteId)?.name ?? siteId;
  const colorOf = (siteId: string) => {
    const i = siteOrder.findIndex((s) => s.site_id === siteId);
    return i >= 0 && i < SERIES.length ? SERIES[i] : INK.muted;
  };

  const bySite = new Map<string, SeriesPoint[]>();
  for (const p of points) {
    if (!p.site_id) continue;
    if (!bySite.has(p.site_id)) bySite.set(p.site_id, []);
    bySite.get(p.site_id)!.push(p);
  }
  const order = siteOrder.length ? siteOrder.map((s) => s.site_id) : [...bySite.keys()];

  let toX: (p: SeriesPoint) => number;
  let xFormat: (x: number) => string;
  if (grain === "year") {
    toX = (p) => Number(p.year);
    xFormat = (x) => String(Math.round(x));
  } else if (grain === "month") {
    toX = (p) => ymToX(String(p.ym));
    xFormat = (x) => xToYm(x);
  } else {
    toX = (p) => Date.parse(String(p.d));
    xFormat = (x) => new Date(x).toISOString().slice(0, 10);
  }

  const series: LineSeries[] = order
    .filter((id) => bySite.has(id))
    .slice(0, SERIES.length)
    .map((id) => ({
      key: id,
      label: nameOf(id),
      color: colorOf(id),
      points: bySite
        .get(id)!
        .map((p) => {
          const yRaw = typeof p.avg === "number" ? p.avg : p.value;
          return {
            x: toX(p),
            y: typeof yRaw === "number" && Number.isFinite(yRaw) ? yRaw : null,
            n: p.n,
            censored: grain === "day" ? (p.n_censored ?? 0) > 0 : (p.n_censored ?? 0) > 0 && p.n_censored === p.n,
          };
        })
        .filter((p) => Number.isFinite(p.x))
        .sort((a, b) => a.x - b.x),
    }));

  return { series, unit, xFormat };
}
