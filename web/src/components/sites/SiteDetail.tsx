"use client";

import * as React from "react";
import Link from "next/link";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { Heatmap } from "@/components/viz/Heatmap";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { MapCanvas } from "@/components/map/MapCanvas";
import { SERIES, ZONE_COLORS, ZONE_LABELS, ZONE_ELEV } from "@/components/viz/palette";
import { Btn, Stat, nf, Provenance, Spinner } from "@/components/ui";
import { shortVariable, caveatBody } from "@/lib/registry/lookup-client";
import { VARIABLE_NOTE } from "@/lib/registry/generated-client";
import { MUNICIPALITY_LABEL } from "@/lib/municipality";
import { useJson } from "@/components/useJson";
import { fmt } from "@/components/viz/scales";
import { useSetPageContext } from "@/components/assistant/PageContextProvider";

interface Site {
  site_id: string;
  name: string | null;
  zone: number | null;
  lat: number;
  lon: number;
  elevation_m: number | null;
  municipality: string | null;
  operator: string | null;
  water_system_name: string | null;
  watershed: string | null;
  source_id: string | null;
  source_ref: string | null;
  treatment: string | null;
  established_on: string | null;
  n_meas: number;
  n_var: number;
}
interface Variable {
  variable: string;
  kind: string;
  n: number;
  y_from: number;
  y_to: number;
  avg: number;
  unit: string | null;
}

export function SiteDetail({ site, variables }: { site: Site; variables: Variable[] }) {
  const [variable, setVariable] = React.useState(variables[0]?.variable ?? "");
  const kind = (variables.find((v) => v.variable === variable)?.kind ?? "daily") as "daily" | "annual";
  const unit = variables.find((v) => v.variable === variable)?.unit ?? null;
  const [grain, setGrain] = React.useState<"day" | "month" | "year">("month");

  useSetPageContext({
    route: "/sites/[id]",
    title: site.name ?? site.site_id,
    siteId: site.site_id,
    name: site.name ?? site.site_id,
    zone: site.zone,
    nMeas: site.n_meas,
  });

  const { data, loading } = useJson<{
    year: { year: number; n: number; avg: number; min: number; max: number; n_censored: number }[];
    month: { ym: string; year: number; month: number; n: number; avg: number }[];
    day: { d: string; value: number; n_censored: number }[];
  }>(
    variable
      ? `/api/timeseries?mode=site&variable=${encodeURIComponent(variable)}&site=${encodeURIComponent(site.site_id)}&kind=${kind}`
      : "",
  );

  const series: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    if (grain === "year")
      return [
        {
          key: "y",
          label: shortVariable(variable),
          color: SERIES[0],
          points: data.year.map((p) => ({
            x: p.year,
            y: p.avg,
            n: p.n,
            censored: p.n_censored > 0 && p.n_censored === p.n,
          })),
        },
      ];
    if (grain === "month")
      return [
        {
          key: "m",
          label: shortVariable(variable),
          color: SERIES[0],
          points: data.month.map((p) => ({ x: p.year + (p.month - 0.5) / 12, y: p.avg, n: p.n })),
        },
      ];
    return [
      {
        key: "d",
        label: shortVariable(variable),
        color: SERIES[0],
        points: data.day.map((p) => ({
          x: dayToX(p.d),
          y: p.value,
          censored: p.n_censored > 0,
        })),
      },
    ];
  }, [data, grain, variable]);

  const heat = React.useMemo(() => {
    if (!data?.month.length) return { cells: [], years: [] as number[] };
    return {
      years: [...new Set(data.month.map((p) => p.year))].sort((a, b) => a - b),
      cells: data.month.map((p) => ({ x: p.year, y: p.month, v: p.avg, n: p.n })),
    };
  }, [data]);

  const sources = React.useMemo(
    () => ({
      "ry-site": {
        type: "geojson" as const,
        data: {
          type: "FeatureCollection" as const,
          features: [
            {
              type: "Feature" as const,
              geometry: { type: "Point" as const, coordinates: [site.lon, site.lat] },
              properties: {},
            },
          ],
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

  const url = site.source_ref?.startsWith("http") ? site.source_ref.split(" ")[0] : null;

  return (
    <div className="flex-1 overflow-y-auto thin-scroll">
      <div className="border-b border-line bg-surface px-4 py-3">
        <div className="flex items-start gap-4 flex-wrap">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <Link href="/sites" className="text-[11px] text-water hover:underline no-print">
                ← 地点一覧
              </Link>
              <h1 className="text-[18px] font-bold">{site.name ?? site.site_id}</h1>
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
            <p className="text-[11px] text-muted font-mono mt-0.5">{site.site_id}</p>
          </div>
          <div className="flex gap-6 ml-auto flex-wrap">
            <Stat label="標高" value={site.elevation_m != null ? fmt(site.elevation_m) : "–"} unit="m" />
            <Stat label="測定値" value={nf(site.n_meas)} unit="件" note={`${site.n_var} 項目`} />
            <Stat label={MUNICIPALITY_LABEL} value={<span className="text-[15px]">{site.municipality ?? "–"}</span>} />
            <Stat label="水系" value={<span className="text-[15px]">{site.water_system_name ?? "–"}</span>} note={site.watershed ?? undefined} />
          </div>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 space-y-4">
          <ChartFrame
            title={`${shortVariable(variable)} の推移`}
            subtitle={VARIABLE_NOTE[variable] ?? "この地点で記録されている値の推移"}
            right={
              <div className="flex gap-0.5">
                {kind === "daily" && (
                  <>
                    <Btn active={grain === "day"} onClick={() => setGrain("day")}>
                      日
                    </Btn>
                    <Btn active={grain === "month"} onClick={() => setGrain("month")}>
                      月
                    </Btn>
                  </>
                )}
                <Btn active={grain === "year"} onClick={() => setGrain("year")}>
                  年
                </Btn>
              </div>
            }
            height={300}
            table={
              <MiniTable
                columns={["年", `平均${unit ? `（${unit}）` : ""}`, "最小", "最大", "n", "下限未満"]}
                rows={(data?.year ?? []).map((p) => [p.year, p.avg, p.min, p.max, p.n, p.n_censored])}
              />
            }
            note={
              <>
                {caveatBody("duplicates")} {caveatBody("censored")}
              </>
            }
          >
            {loading && !data ? (
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

          {kind === "daily" && heat.cells.length > 0 && (
            <ChartFrame
              title="年 × 月のヒートマップ"
              subtitle="縦が月、横が年。季節の型と、それが崩れた年を同時に見る"
              table={
                <MiniTable
                  columns={["年", "月", `平均${unit ? `（${unit}）` : ""}`, "n"]}
                  rows={(data?.month ?? []).map((p) => [p.year, p.month, p.avg, p.n])}
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
            <MapCanvas
              sources={sources}
              layers={layers}
              center={[site.lon, site.lat]}
              zoom={12}
              className="relative h-56"
            />
            <div className="px-3 py-2 text-[11px] text-muted tnum">
              {site.lat.toFixed(5)}, {site.lon.toFixed(5)}　運用: {site.operator ?? "–"}
              {site.established_on && `　設置: ${site.established_on}`}
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="px-3 py-2 border-b border-line text-[13px] font-semibold">
              測定項目
              <span className="ml-1.5 text-[10.5px] font-normal text-muted">クリックで切替</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto thin-scroll">
              {variables.map((v) => (
                <button
                  key={v.variable + v.kind}
                  onClick={() => setVariable(v.variable)}
                  className={`w-full text-left px-3 py-1.5 border-b border-line last:border-0 hover:bg-surface-2 ${
                    variable === v.variable ? "bg-water-soft" : ""
                  }`}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-[12px] truncate">{shortVariable(v.variable)}</span>
                    <span className="ml-auto text-[10.5px] text-muted tnum shrink-0">{nf(v.n)}</span>
                  </div>
                  <div className="text-[10px] text-muted tnum">
                    {v.y_from}–{v.y_to}　{v.kind === "annual" ? "年度集計値" : "検体値"}
                    {v.unit ? `　平均 ${fmt(v.avg, v.unit)}` : ""}
                  </div>
                </button>
              ))}
              {variables.length === 0 && (
                <p className="p-3 text-[12px] text-muted">この地点には測定値がありません（地点マスタのみ）。</p>
              )}
            </div>
          </div>

          <div className="card p-3">
            <Provenance>
              出典 ID: <code className="font-mono">{site.source_id ?? "–"}</code>
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
