"use client";

import * as React from "react";
import Link from "next/link";
import { BarChart } from "@/components/viz/BarChart";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, DIVERGING, STATUS, INK } from "@/components/viz/palette";
import { fmt } from "@/components/viz/scales";
import { nf } from "@/components/ui";
import { MAP_METRICS } from "@/lib/registry/generated-client";
import { caveatBody } from "@/lib/registry/lookup-client";
import { withRegion } from "@/components/region-url";
import { AMAMI_STORY_HREF, AMAMI_STORY_LABEL, showAmamiStory } from "@/lib/stories/links";
import { REGION_ALL, regionUi, type RegionFilter } from "@/lib/region";
import { SiteMapLink } from "@/components/sites/SiteMapLink";
import type { CoralYearSummary } from "@/lib/home-highlights";

export function HomeHighlights({
  longitudinal,
  coral = [],
  landuse,
  redlist,
  effort,
  region = REGION_ALL,
}: {
  longitudinal: { site_id: string; name: string; elevation_m: number; zone: number; avg: number; n: number; unit: string | null; lat?: number | null; lon?: number | null }[];
  /** 奄美の②（サンゴ礁の被度）。`RegionUi.homeCoral` の地域だけ中身が入る。 */
  coral?: CoralYearSummary[];
  landuse: { watershed_id: string; water_system_name: string | null; delta: number; area_km2: number }[];
  redlist: { list_year: number; list_name: string; taxon_group_ja: string; direction: string; n: number }[];
  effort: { year: number; n: number; species_n: number; mesh_n: number; n_inat: number; n_gbif: number }[];
  /** 画面の地域。①②③の固定文言（境川・鶴見川・レッドリスト3版）は神奈川の数字なので、奄美（jp-46）では出さない。 */
  region?: RegionFilter;
}) {
  const ui = regionUi(region);
  const noFixedNarrative = !(ui?.hasFixedNarrative ?? true);
  // ①の指標・並び（地域の宣言。無ければ境川の BOD・標高順）
  const lg = ui?.highlightLongitudinal;
  const showLongitudinal = !noFixedNarrative || (!!lg && longitudinal.length > 0);
  const showCoral = !!ui?.homeCoral && coral.length > 0;
  const indicator = lg?.indicator ?? "BOD";
  const timeseriesHref = withRegion(
    lg
      ? `/timeseries?${new URLSearchParams({ variable: lg.variableId, ...(ui?.highlightWater ? { water: ui.highlightWater } : {}) }).toString()}`
      : "/timeseries",
    region,
  );
  // 土地利用の面積差の単位は地図指標と同じ registry の語彙（unit.yaml の km2）から引く
  const landuseUnit = MAP_METRICS.find((m) => m.id === "built_delta")?.unit ?? undefined;
  const unit = longitudinal[0]?.unit ?? null;

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

  const coralLines: LineSeries[] = React.useMemo(
    () => [
      { key: "cover", label: "サンゴ被度", color: SERIES[0], points: coral.map((c) => ({ x: c.year, y: c.coverMean, n: c.measured })) },
      { key: "bleach", label: "白化率（全体）", color: STATUS.critical, points: coral.map((c) => ({ x: c.year, y: c.bleachMean, n: c.bleachN })) },
    ],
    [coral],
  );

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
      {!showLongitudinal ? (
        <div className="card p-3.5">
          <div className="text-[13px] font-semibold">① 場所で比べる — 川を下ると水はどう変わるか</div>
          <p className="text-[11.5px] text-muted mt-1 leading-relaxed">
            奄美大島には、この概況で固定して見せる川（神奈川では境川）をまだ決めていません。時系列比較で水域を選んでください。
            <Link href={withRegion("/timeseries", region)} className="text-water underline ml-1">
              時系列比較を開く
            </Link>
          </p>
        </div>
      ) : lg ? (
        <ChartFrame
          title={`① 場所で比べる — 島の周りの海（${lg.waterLabel}）`}
          subtitle={`${longitudinal.length}地点の ${lg.indicator}（化学的酸素要求量、海域の環境基準の項目）の 2020年以降の平均。海は標高で並べられないので、基準点→監視点の順に並べてある`}
          table={
            <MiniTable
              columns={["地点", unit ? `${indicator}(${unit})` : indicator, "n"]}
              rows={longitudinal.map((r) => [r.name, r.avg, r.n])}
            />
          }
          note={
            <>
              値が大きいほど有機物による汚れが多い。地点の位置は名前の横のリンクから地図で確かめられる。
              <Link href={timeseriesHref} className="text-water underline ml-1">
                時系列比較で見る
              </Link>
            </>
          }
        >
          <BarChart
            data={longitudinal.map((r) => ({ key: r.site_id, label: r.name, value: r.avg }))}
            unit={unit}
            maxLabelWidth={90}
          />
          <ul className="px-3 pb-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
            {longitudinal.map((r) => (
              <li key={r.site_id} className="flex items-baseline justify-between gap-2">
                <span>{r.name}</span>
                <SiteMapLink name={r.name} lat={r.lat} lon={r.lon} />
              </li>
            ))}
          </ul>
        </ChartFrame>
      ) : (
        <ChartFrame
          title="① 場所で比べる — 川を下ると水はどう変わるか"
          subtitle="境川の5地点、2020年以降の BOD の平均。標高の高い順に並べてある"
          table={
            <MiniTable
              columns={["地点", "標高(m)", unit ? `BOD(${unit})` : "BOD", "n"]}
              rows={longitudinal.map((r) => [r.name, r.elevation_m, r.avg, r.n])}
            />
          }
          note={
            <>
              上流の常矢橋と下流の大道橋で 5 倍近い差がある。この差は10年間ずっと同じ向きで出ている。
              <Link href={withRegion("/timeseries", region)} className="text-water underline ml-1">
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
      )}

      {showCoral && (
        <ChartFrame
          title="② 年で比べる — サンゴ礁の被度（2004〜2017年度）"
          subtitle={`奄美大島とその周辺 ${Math.max(...coral.map((c) => c.spots))} スポットの、サンゴ被度と白化率（全体）のスポット平均。スポット調査（目視）`}
          legend={coralLines.map((s) => ({ label: s.label, color: s.color }))}
          height={190}
          table={
            <MiniTable
              columns={["年度", "スポット数", "被度平均(%)", "被度<5%", "白化率平均(%)"]}
              rows={coral.map((c) => [c.year, c.spots, c.coverMean === null ? "–" : fmt(c.coverMean), c.belowLimit, c.bleachMean === null ? "–" : fmt(c.bleachMean)])}
            />
          }
          note={
            <>
              データは 2017 年度で止まっている。それ以降の状態はこの図からは言えない。被度が「&lt;5」のスポット（毎年 2〜6 か所）は平均に入れていないので、平均はやや高めに出る。2016〜2017 年度は白化率が急に上がっている。
              <span className="block mt-1">{caveatBody("moniCoral")}</span>
              <span className="block mt-1">
                出典: 環境省 モニタリングサイト1000 サンゴ礁調査（SAN01、スポットチェック法）。
                <Link href={withRegion("/sources", region)} className="text-water underline ml-1">
                  出典一覧
                </Link>
              </span>
            </>
          }
        >
          <LineChart
            series={coralLines}
            height={190}
            unit="%"
            xFormat={(x) => String(Math.round(x))}
            yZero
          />
        </ChartFrame>
      )}

      {!showCoral && (
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
            {noFixedNarrative
              ? "鹿児島県レッドリストは版が1つだけで、版間の比較は出せない。"
              : "植物は改善が悪化を上回るのに対し、昆虫・クモは悪化が改善の 1.7 倍。分類群で向きが逆になっている。"}
            <Link href={withRegion("/biota", region)} className="text-water underline ml-1">
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
                    style={{ width: `${(a.横ばい / total) * 100}%`, background: INK.axis }}
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
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: INK.axis }} />
              横ばい
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ background: SERIES[0] }} />
              改善
            </span>
          </div>
        </div>
      </ChartFrame>
      )}

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
            {noFixedNarrative
              ? "同じ流域の水質と重ねると読み方が変わる。"
              : "境川・鶴見川の下流部で 5km² 以上増えている。同じ流域の水質と重ねると読み方が変わる。"}
            <Link href={withRegion("/map", region)} className="text-water underline ml-1">
              地図で塗り分ける
            </Link>
            <span className="block mt-1">{caveatBody("landuseDefinitionChange")}</span>
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
          unit={landuseUnit}
          maxLabelWidth={130}
          valueFormat={(v) => `+${fmt(v)} ${landuseUnit}`}
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

      {showAmamiStory(region) && (
        <div className="card p-3.5 lg:col-span-3">
          <div className="text-[13px] font-semibold">{AMAMI_STORY_LABEL}</div>
          <p className="text-[11.5px] text-muted mt-1 leading-relaxed">
            マングースの捕獲、豪雨の被害、土砂災害の区域を、出典ごとの数字のまま並べたページ。
            <Link href={AMAMI_STORY_HREF} className="text-water underline ml-1">
              開く
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}
