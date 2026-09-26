"use client";

import * as React from "react";
import Link from "next/link";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { Heatmap } from "@/components/viz/Heatmap";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { MapCanvas } from "@/components/map/MapCanvas";
import { SERIES, ZONE_COLORS, ZONE_LABELS, ZONE_ELEV } from "@/components/viz/palette";
import { Btn, Stat, nf, Provenance, Spinner } from "@/components/ui";
import { caveatBody } from "@/lib/registry/lookup-client";
import { VARIABLE_LABEL } from "@/lib/registry/generated-client";
import { MUNICIPALITY_LABEL } from "@/lib/municipality";
import { useJson } from "@/components/useJson";
import { fmt } from "@/components/viz/scales";
import { useSetPageContext } from "@/components/assistant/PageContextProvider";

interface Site {
  siteId: string;
  name: string | null;
  zone: number | null;
  lat: number | null;
  lon: number | null;
  elevationM: number | null;
  municipality: string | null;
  operator: string | null;
  waterSystemName: string | null;
  watershed: string | null;
  sourceId: string | null;
  sourceRef: string | null;
  treatment: string | null;
  establishedOn: string | null;
  nMeas: number;
  nVariables: number;
}
/** `catalog.siteVariables()`（`SiteSeriesRow`）をクライアント向けに単位だけ解決した形
 *  （page.tsx が `unitLabel(v.series.unitId)` で解決してから渡す。クライアントからは
 *  `@/lib/registry/lookup`〔サーバ専用の大きい generated.ts を経由〕を呼ばないため）。 */
interface Variable {
  variableId: string;
  obsStat: string | null;
  grain: string;
  inputGrain: string;
  n: number;
  yFrom: number;
  yTo: number;
  avg: number | null;
  unit: string | null;
}

type Basis = "day" | "fiscal_year" | "year";

/**
 * `lib/cube/series.ts` の `basisOfCell` と同じ式（クライアント安全のため複製——
 * `series.ts` はサーバ専用の大きい `registry/generated.ts` を import するため、
 * クライアントコンポーネントからは直接 import しない）。
 *
 * **basis はセルの性質**（`grain`/`inputGrain` の組）で決める——`value_grain`
 * （系列の登録）では決めない（Issue #48 PR-2 統合後修正A #1）。`value_grain='day'`
 * として登録された系列でも、出典が一部の年だけ年度値を直接報告していれば
 * `grain='fiscal_year'` のセルを持つ（実測: 厚木系の中津川 BOD）。
 */
function basisOfCell(cell: { grain: string; inputGrain: string }): Basis {
  if (cell.inputGrain === "day") return "day";
  return cell.grain === "year" ? "year" : "fiscal_year";
}

/** `series.ts` の `REPRESENTATIVE_OBS_STATS`（`[null, "mean", "point"]`）と同じ判定
 *  （クライアント安全のため複製）。非代表（p75/p90/max/min 等）だけ `obsStat` を
 *  そのまま `stat` クエリパラメータに使う（Issue #48 PR-2 code-review #2）。 */
function isRepresentativeObsStat(obsStat: string | null): boolean {
  return obsStat === null || obsStat === "mean" || obsStat === "point";
}

/** 「測定項目」一覧・選択状態の一意キー（`variableId`＋`obsStat`＋`grain`＋`inputGrain`）。
 *  同じ variableId でも basis（年度集計値/検体値）や obsStat（代表/非代表）違いで
 *  複数行になりうるため、選択の単位は variableId だけでは足りない（Issue #48 PR-2
 *  code-review #2）。リストの `key` prop と同じ組み立てを共有する。 */
function rowKey(v: { variableId: string; obsStat: string | null; grain: string; inputGrain: string }): string {
  return v.variableId + (v.obsStat ?? "") + v.grain + v.inputGrain;
}

function variableLabel(variableId: string): string {
  return VARIABLE_LABEL[variableId]?.short ?? variableId;
}

/** `/api/timeseries?mode=site` の年セル応答（`lib/cube` の `YearPoint`、緩い受け）。 */
interface YearApiPoint {
  year: number;
  n: number;
  nCensored: number;
  value: { mean: number | null; min: number | null; max: number | null };
}
/** 同 month/day セル応答（`lib/cube` の `SeriesPoint`、緩い受け）。 */
interface SeriesApiPoint {
  periodStart: string;
  n: number;
  nCensored: number;
  value: number | null;
}
interface SiteTimeseriesResponse<P> {
  points: P[];
}

export function SiteDetail({ site, variables }: { site: Site; variables: Variable[] }) {
  const [selectedKey, setSelectedKey] = React.useState(() => (variables[0] ? rowKey(variables[0]) : ""));
  const selected = variables.find((v) => rowKey(v) === selectedKey);
  const variableId = selected?.variableId ?? "";
  const basis: Basis = selected ? basisOfCell(selected) : "day";
  const stat = selected ? (isRepresentativeObsStat(selected.obsStat) ? "representative" : selected.obsStat!) : "representative";
  const unit = selected?.unit ?? null;
  const [grainPref, setGrainPref] = React.useState<"day" | "month" | "year">("month");
  const grain = basis === "day" ? grainPref : "year";

  useSetPageContext({
    route: "/sites/[id]",
    title: site.name ?? site.siteId,
    siteId: site.siteId,
    name: site.name ?? site.siteId,
    zone: site.zone,
    nMeas: site.nMeas,
  });

  // `/api/timeseries?mode=site` は1回の応答につき1 grain しか返さない（design §0
  // 決定4・§2.2）ので、grain ごとに別々に取る（Issue #48 PR-2 code-review #1）。
  // 年セルは表（MiniTable）にも常に使うため grain の選択に関わらず常に取り、
  // 月セルはヒートマップにも使うため basis='day' の間は常に取る。日セルは
  // 実際に「日」表示を選んだときだけ取る。
  const baseQs = variableId
    ? `mode=site&variable=${encodeURIComponent(variableId)}&site=${encodeURIComponent(site.siteId)}&basis=${basis}&stat=${encodeURIComponent(stat)}`
    : "";
  const { data: yearData, loading: yearLoading } = useJson<SiteTimeseriesResponse<YearApiPoint>>(
    baseQs ? `/api/timeseries?${baseQs}&grain=${basis === "day" ? "year" : basis}` : "",
  );
  const { data: monthData, loading: monthLoading } = useJson<SiteTimeseriesResponse<SeriesApiPoint>>(
    baseQs && basis === "day" ? `/api/timeseries?${baseQs}&grain=month` : "",
  );
  const { data: dayData, loading: dayLoading } = useJson<SiteTimeseriesResponse<SeriesApiPoint>>(
    baseQs && basis === "day" && grain === "day" ? `/api/timeseries?${baseQs}&grain=day` : "",
  );

  const currentData = grain === "day" ? dayData : grain === "month" ? monthData : yearData;
  const currentLoading = grain === "day" ? dayLoading : grain === "month" ? monthLoading : yearLoading;

  const series: LineSeries[] = React.useMemo(() => {
    const label = variableLabel(variableId);
    if (grain === "year") {
      if (!yearData) return [];
      return [
        {
          key: "y",
          label,
          color: SERIES[0],
          points: yearData.points.map((p) => ({
            x: p.year,
            y: p.value.mean,
            n: p.n,
            censored: p.nCensored > 0 && p.nCensored === p.n,
          })),
        },
      ];
    }
    if (grain === "month") {
      if (!monthData) return [];
      return [
        {
          key: "m",
          label,
          color: SERIES[0],
          points: monthData.points.map((p) => ({ x: ymToX(p.periodStart.slice(0, 7)), y: p.value, n: p.n })),
        },
      ];
    }
    if (!dayData) return [];
    return [
      {
        key: "d",
        label,
        color: SERIES[0],
        points: dayData.points.map((p) => ({
          x: dayToX(p.periodStart),
          y: p.value,
          censored: (p.nCensored ?? 0) > 0,
        })),
      },
    ];
  }, [yearData, monthData, dayData, grain, variableId]);

  const heat = React.useMemo(() => {
    const points = monthData?.points ?? [];
    if (!points.length) return { cells: [] as { x: number; y: number; v: number; n: number }[], years: [] as number[] };
    const cells = points.filter((p) => typeof p.value === "number").map((p) => ({
      x: Number(p.periodStart.slice(0, 4)),
      y: Number(p.periodStart.slice(5, 7)),
      v: p.value as number,
      n: p.n,
    }));
    return { years: [...new Set(cells.map((c) => c.x))].sort((a, b) => a - b), cells };
  }, [monthData]);

  const sources = React.useMemo(
    () => ({
      "ry-site": {
        type: "geojson" as const,
        data: {
          type: "FeatureCollection" as const,
          features:
            site.lon != null && site.lat != null
              ? [
                  {
                    type: "Feature" as const,
                    geometry: { type: "Point" as const, coordinates: [site.lon, site.lat] },
                    properties: {},
                  },
                ]
              : [],
        },
      },
    }),
    [site.lat, site.lon],
  );
  const layers = React.useMemo(
    () => [
      {
        id: "ry-site-pt",
        source: "ry-site",
        spec: {
          type: "circle" as const,
          paint: {
            "circle-radius": 8,
            "circle-color": site.zone != null ? ZONE_COLORS[site.zone] : "#9aa8a6",
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 2.5,
          },
        },
      },
    ],
    [site.zone],
  );

  const url = site.sourceRef?.startsWith("http") ? site.sourceRef.split(" ")[0] : null;

  return (
    <div className="flex-1 overflow-y-auto thin-scroll">
      <div className="border-b border-line bg-surface px-4 py-3">
        <div className="flex items-start gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <Link href="/sites" className="text-[11px] text-water hover:underline no-print">
                ← 地点一覧
              </Link>
              <h1 className="text-[18px] font-bold">{site.name ?? site.siteId}</h1>
              {site.zone != null && (
                <span
                  className="text-[10.5px] px-1.5 py-0.5 rounded text-white"
                  style={{ background: ZONE_COLORS[site.zone] }}
                  title={ZONE_ELEV[site.zone]}
                >
                  ゾーン {site.zone}. {ZONE_LABELS[site.zone]}
                </span>
              )}
              {site.treatment && (
                <span className="text-[10.5px] px-1.5 py-0.5 rounded border border-line">{site.treatment}</span>
              )}
            </div>
            <p className="text-[11px] text-muted font-mono mt-0.5">{site.siteId}</p>
          </div>
          <div className="flex gap-6 ml-auto flex-wrap">
            <Stat label="標高" value={site.elevationM != null ? fmt(site.elevationM) : "–"} unit="m" />
            <Stat label="測定値" value={nf(site.nMeas)} unit="件" note={`${site.nVariables} 項目`} />
            <Stat label={MUNICIPALITY_LABEL} value={<span className="text-[15px]">{site.municipality ?? "–"}</span>} />
            <Stat label="水系" value={<span className="text-[15px]">{site.waterSystemName ?? "–"}</span>} note={site.watershed ?? undefined} />
          </div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-4">
          <ChartFrame
            title={`${variableLabel(variableId)} の推移`}
            subtitle={VARIABLE_LABEL[variableId]?.note ?? "この地点で記録されている値の推移"}
            right={
              <div className="flex gap-0.5">
                {basis === "day" && (
                  <>
                    <Btn active={grain === "day"} onClick={() => setGrainPref("day")}>
                      日
                    </Btn>
                    <Btn active={grain === "month"} onClick={() => setGrainPref("month")}>
                      月
                    </Btn>
                  </>
                )}
                <Btn active={grain === "year"} onClick={() => setGrainPref("year")}>
                  年
                </Btn>
              </div>
            }
            height={300}
            table={
              <MiniTable
                columns={["年", `平均${unit ? `（${unit}）` : ""}`, "最小", "最大", "n", "下限未満"]}
                rows={(yearData?.points ?? []).map((p) => [p.year, p.value.mean, p.value.min, p.value.max, p.n, p.nCensored])}
              />
            }
            note={
              <>
                {caveatBody("duplicates")} {caveatBody("censoredLod")}
              </>
            }
          >
            {currentLoading && !currentData ? (
              <div className="p-8 text-center">
                <Spinner label="読み込み中" />
              </div>
            ) : (
              <LineChart
                series={series}
                height={300}
                unit={unit}
                xFormat={(x) =>
                  grain === "year" ? String(Math.round(x)) : grain === "month" ? xToYm(x) : xToDay(x)
                }
                directLabels={false}
              />
            )}
          </ChartFrame>

          {basis === "day" && heat.cells.length > 0 && (
            <ChartFrame
              title="年 × 月のヒートマップ"
              subtitle="縦が月、横が年。季節の型と、それが崩れた年を同時に見る"
              table={
                <MiniTable
                  columns={["年", "月", `平均${unit ? `（${unit}）` : ""}`, "n"]}
                  rows={heat.cells.map((c) => [c.x, c.y, c.v, c.n])}
                />
              }
            >
              <Heatmap
                cells={heat.cells}
                xDomain={heat.years}
                yDomain={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}
                xFormat={(v) => String(v)}
                yFormat={(v) => `${v}月`}
                unit={unit}
                height={230}
              />
            </ChartFrame>
          )}
        </div>

        <div className="space-y-4">
          <div className="card overflow-hidden">
            <div className="px-3 py-2 border-b border-line text-[13px] font-semibold">位置</div>
            {site.lat != null && site.lon != null ? (
              <MapCanvas
                sources={sources}
                layers={layers}
                center={[site.lon, site.lat]}
                zoom={12}
                className="relative h-56"
              />
            ) : (
              <p className="p-6 text-[12px] text-muted text-center">座標が未登録の地点です</p>
            )}
            <div className="px-3 py-2 text-[11px] text-muted tnum">
              {site.lat != null && site.lon != null ? `${site.lat.toFixed(5)}, ${site.lon.toFixed(5)}` : "座標不明"}
              　運用: {site.operator ?? "–"}
              {site.establishedOn && `　設置: ${site.establishedOn}`}
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="px-3 py-2 border-b border-line text-[13px] font-semibold">
              測定項目
              <span className="ml-1.5 text-[10.5px] font-normal text-muted">クリックで切替</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto thin-scroll">
              {variables.map((v) => {
                const rowBasis = basisOfCell(v);
                const key = rowKey(v);
                return (
                  <button
                    key={key}
                    onClick={() => setSelectedKey(key)}
                    className={`w-full text-left px-3 py-1.5 border-b border-line last:border-0 hover:bg-surface-2 ${
                      selectedKey === key ? "bg-water-soft" : ""
                    }`}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="text-[12px] truncate">{variableLabel(v.variableId)}</span>
                      <span className="ml-auto text-[10.5px] text-muted tnum shrink-0">{nf(v.n)}</span>
                    </div>
                    <div className="text-[10px] text-muted tnum">
                      {v.yFrom}–{v.yTo}　{rowBasis === "day" ? "検体値" : rowBasis === "fiscal_year" ? "年度集計値" : "暦年値"}
                      {!isRepresentativeObsStat(v.obsStat) ? `　統計量: ${v.obsStat}` : ""}
                      {v.unit ? `　平均 ${fmt(v.avg ?? 0, v.unit)}` : ""}
                    </div>
                  </button>
                );
              })}
              {variables.length === 0 && (
                <p className="p-3 text-[12px] text-muted">この地点には測定値がありません（地点マスタのみ）。</p>
              )}
            </div>
          </div>

          <div className="card p-3">
            <Provenance>
              出典 ID: <code className="font-mono">{site.sourceId ?? "–"}</code>
              {url && (
                <>
                  {" / "}
                  <a href={url} target="_blank" rel="noopener noreferrer" className="text-water underline">
                    元データのページ
                  </a>
                </>
              )}
            </Provenance>
          </div>
        </div>
      </div>
    </div>
  );
}

function dayToX(d: string): number {
  const y = Number(d.slice(0, 4));
  const m = Number(d.slice(5, 7));
  const dd = Number(d.slice(8, 10));
  return y + (m - 1) / 12 + (dd - 1) / 365;
}
function xToDay(x: number): string {
  const y = Math.floor(x);
  const rest = (x - y) * 365;
  const dt = new Date(Date.UTC(y, 0, 1 + Math.round(rest)));
  return `${dt.getUTCFullYear()}-${String(dt.getUTCMonth() + 1).padStart(2, "0")}-${String(dt.getUTCDate()).padStart(2, "0")}`;
}
function xToYm(x: number): string {
  const y = Math.floor(x);
  const m = Math.min(12, Math.max(1, Math.round((x - y) * 12 + 0.5)));
  return `${y}-${String(m).padStart(2, "0")}`;
}
function ymToX(ym: string): number {
  const y = Number(ym.slice(0, 4));
  const m = Number(ym.slice(5, 7));
  return y + (m - 0.5) / 12;
}
