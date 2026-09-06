"use client";

import * as React from "react";
import type { SourceSpecification } from "maplibre-gl";
import { MapCanvas, type MapLayerSpec } from "./MapCanvas";
import { SEQ, SEQ2, DIVERGING, ZONE_COLORS, ZONE_LABELS, ZONE_ELEV, STATUS } from "@/components/viz/palette";
import { Btn, nf, Spinner } from "@/components/ui";
import { useJson } from "@/components/useJson";
import { DATA_CAVEATS } from "@/lib/domain";
import { fmt } from "@/components/viz/scales";
import Link from "next/link";

type WsMetric = "org_density" | "site_n" | "org_redlist_n" | "built_delta" | "forest_delta" | "paddy_delta";
type MeshMetric = "n" | "species_n" | "rl_n";

const WS_METRICS: { id: WsMetric; label: string; note: string; diverging?: boolean; unit?: string }[] = [
  { id: "org_density", label: "生物記録の密度", note: "流域の面積あたりの観察・標本記録数（件/km²）", unit: "件/km²" },
  { id: "site_n", label: "観測地点の数", note: "その流域にある水質・気象などの観測地点", unit: "地点" },
  { id: "org_redlist_n", label: "レッドリスト種の記録数", note: "レッドリストのカテゴリーが付いた観察記録", unit: "件" },
  {
    id: "built_delta",
    label: "市街地の増減 2006→2016",
    note: "国土数値情報 土地利用細分メッシュ。建物用地の面積の差",
    diverging: true,
    unit: "km²",
  },
  { id: "forest_delta", label: "森林の増減 2006→2016", note: "同上・森林の面積の差", diverging: true, unit: "km²" },
  { id: "paddy_delta", label: "田の増減 2006→2016", note: "同上・田の面積の差", diverging: true, unit: "km²" },
];

const MESH_METRICS: { id: MeshMetric; label: string; note: string }[] = [
  { id: "n", label: "記録の件数", note: "同じ場所で何度も記録されると大きくなる" },
  { id: "species_n", label: "確認された種数", note: "件数が多くても種数が少ない場所がある" },
  { id: "rl_n", label: "レッドリスト種の記録数", note: "保全上の重要地点を探す" },
];

export function MapPage() {
  const [showWatersheds, setShowWatersheds] = React.useState(true);
  const [showSites, setShowSites] = React.useState(true);
  const [showMesh, setShowMesh] = React.useState(false);
  const [showRivers, setShowRivers] = React.useState(false);
  const [showEvents, setShowEvents] = React.useState(false);

  const [wsMetric, setWsMetric] = React.useState<WsMetric>("org_density");
  const [meshMetric, setMeshMetric] = React.useState<MeshMetric>("species_n");
  const [meshYear, setMeshYear] = React.useState<number | null>(null);
  const [sel, setSel] = React.useState<Record<string, unknown> | null>(null);
  const [selKind, setSelKind] = React.useState<"watershed" | "site" | "mesh" | "event" | null>(null);

  const ws = useJson<GeoJSON.FeatureCollection>("/api/geo/watersheds");
  const sites = useJson<GeoJSON.FeatureCollection>("/api/geo/sites");
  const mesh = useJson<GeoJSON.FeatureCollection>(
    showMesh ? `/api/geo/mesh${meshYear ? `?year=${meshYear}` : ""}` : "",
  );
  const rivers = useJson<GeoJSON.FeatureCollection>(showRivers ? "/geo/rivers.geojson" : "");
  const events = useJson<{
    interventions: { intervention_id: string; kind: string; site_name: string; lat: number; lon: number; started_on: string; quantity: number; quantity_unit: string; parcel: string; operator: string }[];
    decisions: { decision_id: string; meeting_name: string; meeting_date: string; decided: string; site_name: string; lat: number; lon: number; stalled_item_resolved: number }[];
  }>(showEvents ? "/api/geo/events" : "");

  const wsScale = React.useMemo(() => {
    if (!ws.data) return { breaks: [] as number[], min: 0, max: 0 };
    const vals = ws.data.features.map((f) => Number(f.properties?.[wsMetric])).filter((v) => Number.isFinite(v));
    const diverging = !!WS_METRICS.find((m) => m.id === wsMetric)?.diverging;
    return { breaks: quantileBreaks(vals, 8, diverging), min: Math.min(...vals), max: Math.max(...vals) };
  }, [ws.data, wsMetric]);
  const wsBreaks = wsScale.breaks;

  const meshScale = React.useMemo(() => {
    if (!mesh.data) return { breaks: [] as number[], min: 0, max: 0 };
    const vals = mesh.data.features
      .map((f) => Number(f.properties?.[meshMetric]))
      .filter((v) => Number.isFinite(v) && v > 0);
    if (!vals.length) return { breaks: [], min: 0, max: 0 };
    return { breaks: quantileBreaks(vals, 8, false), min: Math.min(...vals), max: Math.max(...vals) };
  }, [mesh.data, meshMetric]);
  const meshBreaks = meshScale.breaks;

  const sources: Record<string, SourceSpecification> = React.useMemo(() => {
    const s: Record<string, SourceSpecification> = {};
    if (ws.data) s["ry-ws"] = { type: "geojson", data: ws.data as never };
    if (sites.data) s["ry-sites"] = { type: "geojson", data: sites.data as never };
    if (mesh.data) s["ry-mesh"] = { type: "geojson", data: mesh.data as never };
    if (rivers.data) s["ry-rivers"] = { type: "geojson", data: rivers.data as never };
    if (events.data) {
      s["ry-events"] = {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [
            ...events.data.interventions
              .filter((i) => i.lat != null)
              .map((i) => ({
                type: "Feature" as const,
                geometry: { type: "Point" as const, coordinates: [i.lon, i.lat] },
                properties: { ...i, _kind: "intervention" },
              })),
            ...events.data.decisions
              .filter((d) => d.lat != null)
              .map((d) => ({
                type: "Feature" as const,
                geometry: { type: "Point" as const, coordinates: [d.lon, d.lat] },
                properties: { ...d, _kind: "decision" },
              })),
          ],
        } as never,
      };
    }
    return s;
  }, [ws.data, sites.data, mesh.data, rivers.data, events.data]);

  const layers: MapLayerSpec[] = React.useMemo(() => {
    const out: MapLayerSpec[] = [];
    if (showWatersheds && ws.data) {
      const diverging = !!WS_METRICS.find((m) => m.id === wsMetric)?.diverging;
      out.push({
        id: "ry-ws-fill",
        source: "ry-ws",
        interactive: true,
        spec: {
          type: "fill",
          paint: {
            "fill-color": stepExpr(wsMetric, wsBreaks, diverging) as never,
            // メッシュを重ねるときは流域の塗りを薄くして、2つの量が混ざらないようにする
            "fill-opacity": showMesh ? 0.22 : 0.62,
          },
        },
      });
      out.push({
        id: "ry-ws-line",
        source: "ry-ws",
        spec: { type: "line", paint: { "line-color": "#ffffff", "line-width": 0.7, "line-opacity": 0.8 } },
      });
    }
    if (showRivers && rivers.data) {
      out.push({
        id: "ry-rivers-line",
        source: "ry-rivers",
        spec: { type: "line", paint: { "line-color": "#2a78d6", "line-width": 1.1, "line-opacity": 0.7 } },
      });
    }
    if (showMesh && mesh.data) {
      out.push({
        id: "ry-mesh-fill",
        source: "ry-mesh",
        interactive: true,
        spec: {
          type: "fill",
          paint: {
            "fill-color": stepExpr(meshMetric, meshBreaks, false, SEQ2) as never,
            "fill-opacity": 0.78,
          },
        },
      });
    }
    if (showSites && sites.data) {
      out.push({
        id: "ry-sites-circle",
        source: "ry-sites",
        interactive: true,
        spec: {
          type: "circle",
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 3.6, 13, 8] as never,
            "circle-color": [
              "match",
              ["get", "zone"],
              1, ZONE_COLORS[1], 2, ZONE_COLORS[2], 3, ZONE_COLORS[3], 4, ZONE_COLORS[4], 5, ZONE_COLORS[5],
              "#9aa8a6",
            ] as never,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.6,
          },
        },
      });
    }
    if (showEvents && events.data) {
      out.push({
        id: "ry-events-circle",
        source: "ry-events",
        interactive: true,
        spec: {
          type: "circle",
          paint: {
            "circle-radius": 7,
            "circle-color": ["match", ["get", "_kind"], "intervention", STATUS.good, STATUS.warning] as never,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 2,
          },
        },
      });
    }
    return out;
  }, [showWatersheds, showSites, showMesh, showRivers, showEvents, ws.data, sites.data, mesh.data, rivers.data, events.data, wsMetric, meshMetric, wsBreaks, meshBreaks]);

  const wsMeta = WS_METRICS.find((m) => m.id === wsMetric)!;

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 relative min-w-0">
        <MapCanvas
          sources={sources}
          layers={layers}
          className="absolute inset-0"
          onFeatureClick={(f) => {
            const p = f.properties as Record<string, unknown>;
            setSel(p);
            setSelKind(
              f.layer.id.includes("ws") ? "watershed" : f.layer.id.includes("mesh") ? "mesh" : f.layer.id.includes("events") ? "event" : "site",
            );
          }}
          overlay={
            <div className="absolute bottom-6 left-2 z-10 card px-2.5 py-2 shadow-sm max-w-[220px] max-h-[calc(100%-4rem)] overflow-y-auto thin-scroll no-print">
              {showWatersheds && (
                <div className="mb-2">
                  <div className="text-[10.5px] font-semibold mb-1">{wsMeta.label}</div>
                  <Ramp
                    min={wsScale.min}
                    max={wsScale.max}
                    diverging={!!wsMeta.diverging}
                    unit={wsMeta.unit}
                  />
                </div>
              )}
              {showMesh && (
                <div className="mb-2">
                  <div className="text-[10.5px] font-semibold mb-1">
                    メッシュ: {MESH_METRICS.find((m) => m.id === meshMetric)?.label}
                    {meshYear && `（${meshYear}年）`}
                  </div>
                  <Ramp min={meshScale.min} max={meshScale.max} diverging={false} ramp={SEQ2} />
                </div>
              )}
              {showSites && (
                <div>
                  <div className="text-[10.5px] font-semibold mb-1">観測地点のゾーン</div>
                  <ul className="space-y-0.5">
                    {[1, 2, 3, 4, 5].map((z) => (
                      <li key={z} className="flex items-center gap-1.5 text-[10px] text-ink-2">
                        <span className="w-2.5 h-2.5 rounded-full border border-white" style={{ background: ZONE_COLORS[z] }} />
                        {z}. {ZONE_LABELS[z]}
                      </li>
                    ))}
                    <li className="flex items-center gap-1.5 text-[10px] text-muted">
                      <span className="w-2.5 h-2.5 rounded-full border border-white" style={{ background: "#9aa8a6" }} />
                      標高不明
                    </li>
                  </ul>
                </div>
              )}
            </div>
          }
        />
        {(ws.loading || sites.loading || mesh.loading || rivers.loading) && (
          <div className="absolute top-2 right-12 z-10 card px-2 py-1">
            <Spinner label="読み込み中" />
          </div>
        )}
      </div>

      <aside className="w-[300px] shrink-0 border-l border-line bg-surface overflow-y-auto min-h-0 thin-scroll no-print">
        <div className="p-3 border-b border-line">
          <h1 className="text-[14px] font-bold">流域マップ</h1>
          <p className="text-[11px] text-muted mt-0.5 leading-snug">
            国土数値情報 W12 の単位流域（377面・1977年版）を土台に、観測地点と生物記録を重ねる。
          </p>
        </div>

        <Section title="レイヤ">
          <Toggle checked={showWatersheds} onChange={setShowWatersheds} label="流域界（塗り分け）" />
          {showWatersheds && (
            <div className="pl-5 pb-1">
              {WS_METRICS.map((m) => (
                <label key={m.id} className="flex items-start gap-1.5 py-0.5 cursor-pointer">
                  <input
                    type="radio"
                    checked={wsMetric === m.id}
                    onChange={() => setWsMetric(m.id)}
                    className="mt-0.5"
                  />
                  <span className="text-[11.5px] leading-tight">
                    {m.label}
                    <span className="block text-[10px] text-muted">{m.note}</span>
                  </span>
                </label>
              ))}
            </div>
          )}
          <Toggle checked={showSites} onChange={setShowSites} label="観測地点（352）" />
          <Toggle checked={showMesh} onChange={setShowMesh} label="生物記録メッシュ（1km）" />
          {showMesh && (
            <div className="pl-5 pb-1">
              {MESH_METRICS.map((m) => (
                <label key={m.id} className="flex items-start gap-1.5 py-0.5 cursor-pointer">
                  <input type="radio" checked={meshMetric === m.id} onChange={() => setMeshMetric(m.id)} className="mt-0.5" />
                  <span className="text-[11.5px] leading-tight">
                    {m.label}
                    <span className="block text-[10px] text-muted">{m.note}</span>
                  </span>
                </label>
              ))}
              <div className="pt-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="text-[10.5px] text-muted">年</span>
                  <input
                    type="range"
                    min={2000}
                    max={2026}
                    step={1}
                    value={meshYear ?? 2026}
                    onChange={(e) => setMeshYear(Number(e.target.value))}
                    className="flex-1"
                  />
                  <span className="text-[11px] tnum w-9">{meshYear ?? "全期"}</span>
                </div>
                <Btn className="mt-1" active={meshYear === null} onClick={() => setMeshYear(null)}>
                  全期間で見る
                </Btn>
                {meshYear && (
                  <p className="text-[10px] text-muted mt-1 leading-snug">
                    年を動かすと、その年に記録があったメッシュだけが残る。近年ほどメッシュが増えるのは、観察者が増えたことの反映でもある。
                  </p>
                )}
              </div>
            </div>
          )}
          <Toggle checked={showRivers} onChange={setShowRivers} label="河川流路（W05・2,305本）" />
          <Toggle checked={showEvents} onChange={setShowEvents} label="介入と意思決定（合成データ）" />
        </Section>

        <div className="p-3 border-t border-line">
          <h2 className="text-[12px] font-semibold mb-1.5">選んだ地物</h2>
          {!sel && <p className="text-[11px] text-muted">地図をクリックすると内容が出ます。</p>}
          {sel && selKind === "watershed" && <WatershedCard p={sel} />}
          {sel && selKind === "site" && <SiteCard p={sel} />}
          {sel && selKind === "mesh" && <MeshCard p={sel} />}
          {sel && selKind === "event" && <EventCard p={sel} />}
        </div>

        <div className="p-3 border-t border-line text-[10px] text-muted leading-relaxed">
          <p className="mb-1.5">{DATA_CAVEATS.organismSite}</p>
          <p className="mb-1.5">{DATA_CAVEATS.zone}</p>
          <p>
            出典: 国土数値情報 流域界・非集水域 W12（国土数値情報利用約款）／河川 W05／土地利用細分メッシュ L03-b、
            環境省 公共用水域 水質測定点マスタ、GBIF・iNaturalist。
          </p>
        </div>
      </aside>
    </div>
  );
}

/* ------------------------------ 部品 ------------------------------ */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="p-3 border-b border-line">
      <h2 className="text-[12px] font-semibold mb-1.5">{title}</h2>
      {children}
    </div>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center gap-2 py-1 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="text-[12px]">{label}</span>
    </label>
  );
}

/** 段は8分位。両端に出すのは実際の最小・最大で、境界値ではない。 */
function Ramp({
  min,
  max,
  diverging,
  unit,
  ramp = SEQ,
}: {
  min: number;
  max: number;
  diverging: boolean;
  unit?: string;
  ramp?: readonly string[];
}) {
  const colors = diverging ? [...DIVERGING.neg, DIVERGING.mid, ...DIVERGING.pos] : [...ramp];
  return (
    <div>
      <div className="flex h-2.5 rounded overflow-hidden">
        {colors.map((c, i) => (
          <span key={i} className="flex-1" style={{ background: c }} />
        ))}
      </div>
      <div className="flex justify-between text-[9px] text-muted tnum mt-0.5">
        <span>{Number.isFinite(min) ? fmt(min) : "–"}</span>
        {diverging && <span>0</span>}
        <span>
          {Number.isFinite(max) ? fmt(max) : "–"}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
      <div className="text-[8.5px] text-muted mt-0.5">段は8分位（同じ数の地物が入るように区切る）</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5 text-[11px] border-b border-line last:border-0">
      <span className="text-muted shrink-0">{k}</span>
      <span className="ml-auto text-right tnum">{v}</span>
    </div>
  );
}

function WatershedCard({ p }: { p: Record<string, unknown> }) {
  const num = (k: string) => (p[k] == null ? null : Number(p[k]));
  return (
    <div>
      <div className="text-[13px] font-semibold">{String(p.water_system_name ?? "（水系名の推定なし）")}</div>
      <div className="text-[10px] text-muted font-mono mb-1.5">{String(p.watershed_id)}</div>
      <Row k="面積" v={`${fmt(num("area_km2"))} km²`} />
      <Row k="観測地点" v={`${nf(num("site_n") ?? 0)} 地点`} />
      <Row k="生物記録" v={`${nf(num("org_n") ?? 0)} 件`} />
      <Row k="うちレッドリスト種" v={`${nf(num("org_redlist_n") ?? 0)} 件`} />
      <Row k="市街地 2016" v={num("built_2016") != null ? `${fmt(num("built_2016"))} km²` : "–"} />
      <Row
        k="市街地の増減 06→16"
        v={num("built_delta") != null ? `${num("built_delta")! > 0 ? "+" : ""}${fmt(num("built_delta"))} km²` : "–"}
      />
      <Row
        k="森林の増減 06→16"
        v={num("forest_delta") != null ? `${num("forest_delta")! > 0 ? "+" : ""}${fmt(num("forest_delta"))} km²` : "–"}
      />
      <Row
        k="田の増減 06→16"
        v={num("paddy_delta") != null ? `${num("paddy_delta")! > 0 ? "+" : ""}${fmt(num("paddy_delta"))} km²` : "–"}
      />
      {p.main_rivers != null && (
        <p className="text-[10.5px] text-muted mt-1.5 leading-snug">主な河川: {String(p.main_rivers).replace(/\|/g, "、")}</p>
      )}
    </div>
  );
}

function SiteCard({ p }: { p: Record<string, unknown> }) {
  const z = p.zone == null ? null : Number(p.zone);
  return (
    <div>
      <div className="text-[13px] font-semibold">{String(p.name ?? "（名称なし）")}</div>
      <div className="text-[10px] text-muted font-mono mb-1.5 break-all">{String(p.site_id)}</div>
      {z != null && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="w-3 h-3 rounded-full" style={{ background: ZONE_COLORS[z] }} />
          <span className="text-[11px]">
            ゾーン {z}. {ZONE_LABELS[z]}
          </span>
          <span className="text-[10px] text-muted">{ZONE_ELEV[z]}</span>
        </div>
      )}
      <Row k="標高" v={p.elevation_m != null ? `${fmt(Number(p.elevation_m))} m` : "–"} />
      <Row k="水域・地域" v={String(p.municipality ?? "–")} />
      <Row k="水系" v={String(p.water_system_name ?? "–")} />
      <Row k="運用" v={String(p.operator ?? "–")} />
      <Row k="測定値" v={`${nf(Number(p.n_meas ?? 0))} 件 / ${nf(Number(p.n_var ?? 0))} 項目`} />
      {p.treatment != null && String(p.treatment) !== "" && <Row k="区分" v={String(p.treatment)} />}
      <div className="mt-2 flex gap-1.5">
        <Link
          href={`/sites/${encodeURIComponent(String(p.site_id))}`}
          className="text-[11px] px-2 py-1 rounded border border-water text-water-ink bg-water-soft"
        >
          地点カルテを開く
        </Link>
        {p.source_ref != null && String(p.source_ref).startsWith("http") && (
          <a
            href={String(p.source_ref).split(" ")[0]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] px-2 py-1 rounded border border-line text-ink-2"
          >
            出典
          </a>
        )}
      </div>
    </div>
  );
}

function MeshCard({ p }: { p: Record<string, unknown> }) {
  return (
    <div>
      <div className="text-[13px] font-semibold">1kmメッシュ</div>
      <div className="text-[10px] text-muted font-mono mb-1.5">
        {fmt(Number(p.lat))}, {fmt(Number(p.lon))}
      </div>
      <Row k="記録数" v={nf(Number(p.n ?? 0))} />
      <Row k="種数" v={nf(Number(p.species_n ?? 0))} />
      <Row k="レッドリスト種の記録" v={nf(Number(p.rl_n ?? 0))} />
      <p className="text-[10px] text-muted mt-1.5 leading-snug">
        件数が多くても種数が少ないメッシュは、同じ場所を繰り返し訪れる観察地点（探鳥地など）であることが多い。
      </p>
    </div>
  );
}

function EventCard({ p }: { p: Record<string, unknown> }) {
  const isInt = p._kind === "intervention";
  return (
    <div>
      <div className="text-[13px] font-semibold">{isInt ? `介入: ${String(p.kind)}` : String(p.meeting_name)}</div>
      <div className="text-[10px] text-muted mb-1.5">{String(p.site_name ?? "")}</div>
      {isInt ? (
        <>
          <Row k="区画" v={String(p.parcel ?? "–")} />
          <Row k="量" v={`${fmt(Number(p.quantity))} ${String(p.quantity_unit ?? "")}`} />
          <Row k="期間" v={`${String(p.started_on)} 〜 ${String(p.finished_on ?? "")}`} />
          <Row k="実施" v={String(p.operator ?? "–")} />
        </>
      ) : (
        <>
          <Row k="日付" v={String(p.meeting_date)} />
          <Row k="停滞案件の解消" v={Number(p.stalled_item_resolved) ? "あり" : "なし"} />
          <p className="text-[11px] mt-1.5 leading-relaxed">{String(p.decided ?? "")}</p>
        </>
      )}
      <p className="text-[10px] text-muted mt-1.5">この2つのレイヤは合成データ（デモ用に生成したもの）。</p>
    </div>
  );
}

/* ------------------------------ 計算 ------------------------------ */

/** 分位でクラス分けする。発散指標のときは 0 を必ず境界に入れる。 */
function quantileBreaks(values: number[], classes: number, diverging: boolean): number[] {
  const v = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (v.length === 0) return [];
  if (diverging) {
    const neg = v.filter((x) => x < 0);
    const pos = v.filter((x) => x > 0);
    const q = (arr: number[], k: number) =>
      arr.length ? arr[Math.min(arr.length - 1, Math.floor((k / 4) * arr.length))] : 0;
    return [
      neg.length ? q(neg, 1) : -0.001,
      neg.length ? q(neg, 2) : -0.0005,
      neg.length ? q(neg, 3) : -0.0001,
      0,
      pos.length ? q(pos, 1) : 0.0001,
      pos.length ? q(pos, 2) : 0.0005,
      pos.length ? q(pos, 3) : 0.001,
    ];
  }
  const out: number[] = [];
  for (let i = 1; i < classes; i++) out.push(v[Math.floor((i / classes) * v.length)]);
  // 同値が続くと段が潰れるので単調増加に整える
  for (let i = 1; i < out.length; i++) if (out[i] <= out[i - 1]) out[i] = out[i - 1] + 1e-6;
  return out;
}

function stepExpr(
  field: string,
  breaks: number[],
  diverging: boolean,
  ramp: readonly string[] = SEQ,
): unknown[] {
  const colors = diverging ? [...DIVERGING.neg, DIVERGING.mid, ...DIVERGING.pos] : [...ramp];
  if (!breaks.length) return ["to-color", colors[0]];
  const expr: unknown[] = ["step", ["coalesce", ["get", field], -9999], colors[0]];
  breaks.forEach((b, i) => expr.push(b, colors[Math.min(i + 1, colors.length - 1)]));
  return expr;
}
