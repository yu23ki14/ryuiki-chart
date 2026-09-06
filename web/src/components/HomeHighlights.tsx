"use client";

import * as React from "react";
import Link from "next/link";
import { BarChart } from "@/components/viz/BarChart";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, DIVERGING, STATUS } from "@/components/viz/palette";
import { fmt } from "@/components/viz/scales";
import { nf } from "@/components/ui";

export function HomeHighlights({
  longitudinal,
  landuse,
  redlist,
  effort,
}: {
  longitudinal: { site_id: string; name: string; elevation_m: number; zone: number; avg: number; n: number; unit: string | null }[];
  landuse: { watershed_id: string; water_system_name: string | null; delta: number; area_km2: number }[];
  redlist: { list_year: number; list_name: string; taxon_group_ja: string; direction: string; n: number }[];
  effort: { year: number; n: number; species_n: number; mesh_n: number; n_inat: number; n_gbif: number }[];
}) {
  const unit = longitudinal[0]?.unit ?? "mg/L";

  const rlByYear = React.useMemo(() => {
    const m = new Map<number, { 悪化: number; 改善: number; 横ばい: number }>();
    for (const r of redlist) {
      if (r.direction === "前回記載なし") continue;
      const a = m.get(r.list_year) ?? { 悪化: 0, 改善: 0, 横ばい: 0 };
      if (r.direction in a) a[r.direction as keyof typeof a] += r.n;
      m.set(r.list_year, a);
    }
    return [...m.entries()].sort((a, b) => a[0] - b[0]);
  }, [redlist]);

  const effortLines: LineSeries[] = React.useMemo(
    () => [
      {
        key: "gbif",
        label: "GBIF",
        color: SERIES[0],
        points: effort.filter((e) => e.year >= 2005).map((e) => ({ x: e.year, y: e.n_gbif })),
      },
      {
        key: "inat",
        label: "iNaturalist",
        color: SERIES[1],
        points: effort.filter((e) => e.year >= 2005).map((e) => ({ x: e.year, y: e.n_inat })),
      },
    ],
    [effort],
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-4">
      <ChartFrame
        title="① 場所で比べる — 川を下ると水はどう変わるか"
        subtitle="境川の5地点、2020年以降の BOD の平均。標高の高い順に並べてある"
        table={
          <MiniTable
            columns={["地点", "標高(m)", `BOD(${unit})`, "n"]}
            rows={longitudinal.map((r) => [r.name, r.elevation_m, r.avg, r.n])}
          />
        }
        note={
          <>
            上流の常矢橋と下流の大道橋で 5 倍近い差がある。この差は10年間ずっと同じ向きで出ている。
            <Link href="/timeseries" className="text-water underline ml-1">
              時系列比較で見る
            </Link>
          </>
        }
      >
        <BarChart
          data={longitudinal.map((r) => ({
            key: r.site_id,
            label: `${r.name}（${Math.round(r.elevation_m)}m）`,
            value: r.avg,
            color: ZONE_COLORS[r.zone] ?? SERIES[0],
          }))}
          unit={unit}
          maxLabelWidth={140}
        />
      </ChartFrame>

      <ChartFrame
        title="② 版で比べる — レッドリストは20年でどう動いたか"
        subtitle="2006年版から各版へ。カテゴリーが1段でも重くなった種を「悪化」と数える"
        table={
          <MiniTable
            columns={["版", "悪化", "改善", "横ばい"]}
            rows={rlByYear.map(([y, a]) => [`${y}年版`, a.悪化, a.改善, a.横ばい])}
          />
        }
        note={
          <>
            植物は改善が悪化を上回るのに対し、昆虫・クモは悪化が改善の 1.7 倍。分類群で向きが逆になっている。
            <Link href="/biota" className="text-water underline ml-1">
              版間比較を開く
            </Link>
          </>
        }
      >
        <div className="px-3 py-2 space-y-3">
          {rlByYear.map(([year, a]) => {
            const total = a.悪化 + a.改善 + a.横ばい || 1;
            return (
              <div key={year}>
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-[12px] font-medium">{year}年版</span>
                  <span className="text-[10.5px] text-muted">
                    {year === 2026 ? "昆虫類・クモ類" : "植物ほか"}
                  </span>
                  <span className="ml-auto text-[10.5px] text-muted tnum">{nf(total)} 種</span>
                </div>
                <div className="flex h-5 gap-[2px] rounded overflow-hidden">
                  <div
                    style={{ width: `${(a.悪化 / total) * 100}%`, background: STATUS.critical }}
                    className="flex items-center justify-center"
                    title={`悪化 ${a.悪化} 種`}
                  >
                    {a.悪化 / total > 0.12 && <span className="text-[10px] text-white tnum">{a.悪化}</span>}
                  </div>
                  <div
                    style={{ width: `${(a.横ばい / total) * 100}%`, background: "#c3cfcc" }}
                    className="flex items-center justify-center"
                    title={`横ばい ${a.横ばい} 種`}
                  >
                    {a.横ばい / total > 0.12 && <span className="text-[10px] text-ink-2 tnum">{a.横ばい}</span>}
                  </div>
                  <div
                    style={{ width: `${(a.改善 / total) * 100}%`, background: SERIES[0] }}
                    className="flex items-center justify-center"
                    title={`改善 ${a.改善} 種`}
                  >
                    {a.改善 / total > 0.12 && <span className="text-[10px] text-white tnum">{a.改善}</span>}
                  </div>
                </div>
              </div>
            );
          })}
          <div className="flex gap-3 text-[10.5px] text-muted pt-1">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: STATUS.critical }} />
              悪化
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#c3cfcc" }} />
              横ばい
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES[0] }} />
              改善
            </span>
          </div>
        </div>
      </ChartFrame>

      <ChartFrame
        title="③ 年で比べる — 10年で市街地が増えた流域"
        subtitle="土地利用細分メッシュ 2006年 → 2016年。建物用地の面積の差が大きい順"
        table={
          <MiniTable
            columns={["流域", "水系", "増加(km²)", "流域面積(km²)"]}
            rows={landuse.map((r) => [r.watershed_id, r.water_system_name ?? "–", r.delta, r.area_km2])}
          />
        }
        note={
          <>
            境川・鶴見川の下流部で 5km² 以上増えている。同じ流域の水質と重ねると読み方が変わる。
            <Link href="/map" className="text-water underline ml-1">
              地図で塗り分ける
            </Link>
          </>
        }
      >
        <BarChart
          data={landuse.map((r) => ({
            key: r.watershed_id,
            label: `${r.water_system_name ?? "?"} ${r.watershed_id.slice(-4)}`,
            value: r.delta,
          }))}
          color={DIVERGING.pos[2]}
          unit="km²"
          maxLabelWidth={130}
          valueFormat={(v) => `+${fmt(v)} km²`}
        />
      </ChartFrame>

      <div className="lg:col-span-3">
        <ChartFrame
          title="比べる前に — 記録の量そのものが変わっている"
          subtitle="生物レコードの出典別件数。2017年以降の急増は観察者の増加であり、生きものの増加ではない"
          legend={effortLines.map((s) => ({ label: s.label, color: s.color }))}
          height={200}
          table={
            <MiniTable
              columns={["年", "GBIF", "iNaturalist", "種数", "メッシュ数"]}
              rows={effort.filter((e) => e.year >= 2005).map((e) => [e.year, e.n_gbif, e.n_inat, e.species_n, e.mesh_n])}
            />
          }
          note="GBIF 側の取り込みは2024年12月で途切れている。2025年以降の減少はデータの都合。件数をそのまま比べないための土台として、この図をどの画面にも置いている。"
        >
          <LineChart
            series={effortLines}
            height={200}
            unit="件"
            xFormat={(x) => String(Math.round(x))}
            yZero
            annotations={[{ x: 2024.95, label: "GBIF 取り込み終了", color: STATUS.critical }]}
          />
        </ChartFrame>
      </div>
    </div>
  );
}
