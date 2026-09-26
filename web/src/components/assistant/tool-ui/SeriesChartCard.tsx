"use client";

import * as React from "react";
import Link from "next/link";
import type { ToolCallMessagePartProps } from "@assistant-ui/react";
import { Spinner } from "@/components/ui";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { ChartFrame } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, ZONE_LABELS, INK } from "@/components/viz/palette";
import { VARIABLE_LABEL } from "@/lib/registry/generated-client";
import { timeseriesUrl } from "@/lib/ai/links";
import { ProvenanceFooter, type Provenance } from "./ProvenanceFooter";
import { TOOL_LABEL } from "./ToolResultCard";

/**
 * get_timeseries だけの専用カード。既存の LineChart をそのまま使う（新しい作図コードは書かない）。
 * 証跡（SQL・件数・注記）は ToolResultCard と共通の ProvenanceFooter で、チャートの下に「そのまま」出す。
 *
 * Issue #48 PR-2: get_timeseries の戻り値が v1（meas_year 等の行）から `lib/cube` の
 * 生セル（`CellRow` 相当。水域/地点スコープ）・ゾーン集計（ゾーンスコープ）に変わった
 * （design §5「SeriesChartCard.tsx: TimeseriesData.grain に fiscal_year、kind→basis、
 * y は value_lod（無ければ value_zero）、x は period_start から求める」）。
 */

interface Scope {
  type: "water" | "site" | "zone";
  name?: string;
  siteId?: string;
}
interface SiteLite {
  siteId: string;
  name: string | null;
}
/** 水域/地点スコープの1点（`lib/cube` の CellRow 相当。stat ごとに別行 = mean/min/max）。 */
interface CellPoint {
  placeId: string;
  siteId: string | null;
  grain: string;
  periodStart: string;
  stat: string;
  n?: number;
  nCensored?: number;
  valueZero: number | null;
  valueLod: number | null;
}
/** ゾーンスコープの1点（get_timeseries が `summarize(...,'zone')` から組み立てる形）。 */
interface ZonePoint {
  zone: number;
  grain: string;
  year: number;
  nSites?: number;
  n?: number;
  valueZero: number | null;
  valueLod: number | null;
}
type Point = CellPoint | ZonePoint;

interface TimeseriesData {
  scope: Scope;
  sites?: SiteLite[];
  grain: "year" | "fiscal_year" | "month" | "day";
  /** 元データの粒度（"day"=検体値／"fiscal_year"=年度集計値／"year"=暦年値）。 */
  basis?: "day" | "fiscal_year" | "year";
  stat?: string;
  unit?: string | null;
  points: Point[];
}
interface ToolResultShape {
  data?: TimeseriesData;
  provenance?: Provenance;
  caveats?: string[];
  truncated?: boolean;
  truncatedNote?: string;
}
/** get_timeseries の inputSchema（tools.ts）そのまま。variableId は data 側に載らないので args から取る。 */
interface ToolArgs {
  variableId?: string;
}

/** variable_id の表示名（`VARIABLE_LABEL`。無ければ variable_id をそのまま出す）。 */
function variableLabel(variableId: string): string {
  return VARIABLE_LABEL[variableId]?.short ?? variableId;
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
  const variableId = (args as ToolArgs | undefined)?.variableId;

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
  const link = variableId
    ? timeseriesUrl({ variableId, scope: data.scope, grain: data.grain, basis: data.basis, stat: data.stat })
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
            {variableId && <> の {variableLabel(variableId)}</>}
          </>
        }
        subtitle={`${grainLabel(data.grain)}${data.basis ? ` ・ ${basisLabel(data.basis)}` : ""}`}
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

function grainLabel(grain: "year" | "fiscal_year" | "month" | "day"): string {
  return grain === "year" ? "年平均" : grain === "fiscal_year" ? "年度集計" : grain === "month" ? "月平均" : "日次";
}

function basisLabel(basis: "day" | "fiscal_year" | "year"): string {
  return basis === "day" ? "検体値" : basis === "fiscal_year" ? "年度集計値" : "暦年値";
}

/** `period_start`（`YYYY-01-01`/`YYYY-04-01`）からラベル年を取り出す。`lib/cube/series.ts`
 *  の `labelYear` と同じ式だが、そちらはサーバ専用の大きい generated.ts を経由するモジュール
 *  なのでクライアントからは import しない（1行の式をここに複製する）。 */
function labelYear(periodStart: string): number {
  return Number.parseInt(periodStart.slice(0, 4), 10);
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

function isZonePoint(p: Point): p is ZonePoint {
  return "zone" in p;
}

function buildSeries(data: TimeseriesData): {
  series: LineSeries[];
  unit: string | null;
  xFormat: (x: number) => string;
} {
  const { scope, grain, points } = data;
  const unit = data.unit ?? null;

  if (scope.type === "zone") {
    const byZone = new Map<number, ZonePoint[]>();
    for (const p of points) {
      if (!isZonePoint(p)) continue;
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
          .map((p) => ({ x: p.year, y: p.valueLod ?? p.valueZero, n: p.n }))
          .filter((p) => Number.isFinite(p.x))
          .sort((a, b) => a.x - b.x),
      }));
    return { series, unit, xFormat: (x) => String(Math.round(x)) };
  }

  // water / site スコープ: 色は「地点という実体」に固定する（TimeseriesExplorer と同じ考え方）。
  // sites は water スコープのときだけ埋まっている（site スコープは siteId 直指定で sites に触れないため）。
  const siteOrder = data.sites ?? [];
  const nameOf = (siteId: string) => siteOrder.find((s) => s.siteId === siteId)?.name ?? siteId;
  const colorOf = (siteId: string) => {
    const i = siteOrder.findIndex((s) => s.siteId === siteId);
    return i >= 0 && i < SERIES.length ? SERIES[i] : INK.muted;
  };

  // 年/年度グレインは stat ごとに別行（mean/min/max）で来る。チャートの折れ線は mean だけ使う
  // （min/max は get_timeseries の envelope/表側の情報であり、線を複数引くと読みにくくなる）。
  const cellPoints = points.filter((p): p is CellPoint => !isZonePoint(p) && (p.stat === undefined || p.stat === "mean"));

  const bySite = new Map<string, CellPoint[]>();
  for (const p of cellPoints) {
    const key = p.siteId ?? p.placeId;
    if (!key) continue;
    if (!bySite.has(key)) bySite.set(key, []);
    bySite.get(key)!.push(p);
  }
  const order = siteOrder.length ? siteOrder.map((s) => s.siteId) : [...bySite.keys()];

  const toX = (p: CellPoint): number => {
    if (grain === "year" || grain === "fiscal_year") return labelYear(p.periodStart);
    if (grain === "month") return ymToX(p.periodStart.slice(0, 7));
    return Date.parse(p.periodStart);
  };
  const xFormat = (x: number) =>
    grain === "year" || grain === "fiscal_year" ? String(Math.round(x)) : grain === "month" ? xToYm(x) : new Date(x).toISOString().slice(0, 10);

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
          const y = p.valueLod ?? p.valueZero;
          const n = p.n ?? 0;
          const nCensored = p.nCensored ?? 0;
          return {
            x: toX(p),
            y,
            n,
            censored: grain === "day" ? nCensored > 0 : nCensored > 0 && nCensored === n,
          };
        })
        .filter((p) => Number.isFinite(p.x))
        .sort((a, b) => a.x - b.x),
    }));

  return { series, unit, xFormat };
}
