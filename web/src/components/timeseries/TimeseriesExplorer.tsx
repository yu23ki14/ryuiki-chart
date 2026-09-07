"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { Heatmap } from "@/components/viz/Heatmap";
import { BarChart, ColumnChart } from "@/components/viz/BarChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, ZONE_LABELS, INK } from "@/components/viz/palette";
import { Btn, inputCls, Spinner, Provenance, nf } from "@/components/ui";
import { shortVariable, caveatBody } from "@/lib/registry/lookup-client";
import { VARIABLE_NOTE, HIGHER_IS_WORSE } from "@/lib/registry/generated-client";
import { MUNICIPALITY_LABEL } from "@/lib/municipality";
import { useJson } from "@/components/useJson";
import { useSetPageContext } from "@/components/assistant/PageContextProvider";

interface WaterBody {
  name: string;
  n_sites: number;
  elev_min: number | null;
  elev_max: number | null;
  n_meas: number;
  y_from: number | null;
  y_to: number | null;
}
interface VarRow {
  variable: string;
  unit: string | null;
  n: number;
  n_sites: number;
  y_from: number;
  y_to: number;
  n_daily: number;
  n_annual: number;
  n_censored: number;
}
interface Site {
  site_id: string;
  name: string;
  zone: number | null;
  elevation_m: number | null;
  lat: number;
  lon: number;
}

type Mode = "water" | "zone" | "season";

export function TimeseriesExplorer({ waters, vars }: { waters: WaterBody[]; vars: VarRow[] }) {
  // ディープリンク（AIのチャットカードの「時系列画面でこの表示を開く」など）用に、初期値だけ
  // searchParams から取る。既存の useState 構造はそのまま。URL への書き戻しはしない
  // （双方向同期は下の自動補正と競合するため。Stage 2 ではやらない設計）。
  const sp = useSearchParams();
  const [mode, setMode] = React.useState<Mode>(() => {
    const m = sp.get("mode");
    return m === "zone" || m === "season" ? m : "water";
  });
  const [variable, setVariable] = React.useState(() => sp.get("variable") ?? "生物化学的酸素要求量 BOD");
  const [waterPref, setWater] = React.useState(() => sp.get("water") ?? "境川（１）");
  const [grain, setGrain] = React.useState<"year" | "month">(() => (sp.get("grain") === "month" ? "month" : "year"));
  const [kindPref, setKindPref] = React.useState<"daily" | "annual">(() => (sp.get("kind") === "annual" ? "annual" : "daily"));
  const [hidden, setHidden] = React.useState<Set<string>>(new Set());

  const v = vars.find((x) => x.variable === variable);
  const hasAnnual = (v?.n_annual ?? 0) > 0;
  const hasDaily = (v?.n_daily ?? 0) > 0;

  // 項目によっては検体値と年度集計値のどちらかしか無い。
  // 状態を書き換えずに、描画時に「実際に使える方」へ寄せる。
  const kind: "daily" | "annual" = !hasDaily ? "annual" : !hasAnnual ? "daily" : kindPref;

  // 選んだ項目のデータを実際に持つ水域だけを選択肢にする。
  // 今の水域にその項目が無ければ、地点数が最も多い水域へ自動で移る。
  const waterOpts = useJson<{ waters: WaterBody[] }>(
    `/api/timeseries?mode=waters&variable=${encodeURIComponent(variable)}`,
  );
  const availableWaters = waterOpts.data?.waters ?? waters;
  // 選んだ項目のデータが今の水域に無ければ、地点数が最も多い水域を既定にする（状態は書き換えない）
  const water =
    availableWaters.length === 0 || availableWaters.some((w) => w.name === waterPref)
      ? waterPref
      : availableWaters[0].name;

  // アシスタントに渡すのは「今実際に描画されている値」。waterPref/kindPref という利用者の希望ではなく、
  // 上の自動補正を経た water/kind を渡す（ここを間違えると、画面に無いものをAIが語ることになる）。
  useSetPageContext({
    route: "/timeseries",
    title: "時系列比較",
    mode,
    variable,
    water,
    grain: mode === "water" ? grain : mode === "season" ? "month" : "year",
    kind,
  });

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* 絞り込みは1行に集約し、すべての図が同じ切り口で描き変わる */}
      <div className="no-print border-b border-line bg-surface px-4 py-2 flex items-end gap-3 flex-wrap">
        <div className="flex items-center gap-0.5 mr-1">
          {(
            [
              ["water", "水域の中で地点を比べる"],
              ["zone", "尾根から海まで（ゾーン）"],
              ["season", "季節でくらべる"],
            ] as [Mode, string][]
          ).map(([m, label]) => (
            <Btn key={m} active={mode === m} onClick={() => setMode(m)}>
              {label}
            </Btn>
          ))}
        </div>

        <label className="block">
          <span className="block text-[10.5px] text-muted mb-1">項目</span>
          <select className={inputCls + " w-56"} value={variable} onChange={(e) => setVariable(e.target.value)}>
            {vars.map((x) => (
              <option key={x.variable} value={x.variable}>
                {shortVariable(x.variable)}（{nf(x.n)}）
              </option>
            ))}
          </select>
        </label>

        {mode === "water" && (
          <label className="block">
            <span className="block text-[10.5px] text-muted mb-1">{MUNICIPALITY_LABEL}</span>
            <select
              className={inputCls + " w-56"}
              value={water}
              onChange={(e) => {
                setWater(e.target.value);
                setHidden(new Set());
              }}
            >
              {availableWaters.map((w) => (
                <option key={w.name} value={w.name}>
                  {w.name}（{w.n_sites}地点 / {nf(w.n_meas ?? (w as unknown as { n: number }).n)}件）
                </option>
              ))}
            </select>
          </label>
        )}

        {mode !== "season" && (
          <>
            <div>
              <span className="block text-[10.5px] text-muted mb-1">粒度</span>
              <div className="flex gap-0.5">
                {mode === "water" && (
                  <>
                    <Btn active={grain === "year"} onClick={() => setGrain("year")}>
                      年
                    </Btn>
                    <Btn active={grain === "month"} onClick={() => setGrain("month")}>
                      月
                    </Btn>
                  </>
                )}
              </div>
            </div>
            <div>
              <span className="block text-[10.5px] text-muted mb-1">元データ</span>
              <div className="flex gap-0.5">
                <Btn active={kind === "daily"} disabled={!hasDaily} onClick={() => setKindPref("daily")}>
                  検体値
                </Btn>
                <Btn active={kind === "annual"} disabled={!hasAnnual} onClick={() => setKindPref("annual")}>
                  年度集計値
                </Btn>
              </div>
            </div>
          </>
        )}

        {v && (
          <p className="text-[10.5px] text-muted max-w-md ml-auto leading-snug">
            {VARIABLE_NOTE[variable] ?? "　"}
            <br />
            {nf(v.n)} 行 / {v.n_sites} 地点 / {v.y_from}–{v.y_to}
            {v.n_censored > 0 && `　定量下限未満 ${((v.n_censored / v.n) * 100).toFixed(0)}%`}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll p-4">
        {mode === "water" && (
          <WaterMode
            water={water}
            variable={variable}
            grain={grain}
            kind={kind}
            unit={v?.unit ?? null}
            hidden={hidden}
            setHidden={setHidden}
          />
        )}
        {mode === "zone" && <ZoneMode variable={variable} kind={kind} unit={v?.unit ?? null} />}
        {mode === "season" && <SeasonMode variable={variable} unit={v?.unit ?? null} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 水域の中で地点を比べる                                              */
/* ------------------------------------------------------------------ */

function WaterMode({
  water,
  variable,
  grain,
  kind,
  unit,
  hidden,
  setHidden,
}: {
  water: string;
  variable: string;
  grain: "year" | "month";
  kind: "daily" | "annual";
  unit: string | null;
  hidden: Set<string>;
  setHidden: (s: Set<string>) => void;
}) {
  const { data, loading, error } = useJson<{
    sites: Site[];
    points: Record<string, number | string>[];
  }>(`/api/timeseries?mode=water&variable=${encodeURIComponent(variable)}&water=${encodeURIComponent(water)}&grain=${grain}&kind=${kind}`);

  // 季節と経年を1枚で見るためのヒートマップ（水域内の全地点の平均）
  const monthly = useJson<{ points: { site_id: string; ym: string; year: number; month: number; n: number; avg: number }[] }>(
    kind === "daily"
      ? `/api/timeseries?mode=water&variable=${encodeURIComponent(variable)}&water=${encodeURIComponent(water)}&grain=month&kind=daily`
      : "",
  );

  const ordered = React.useMemo(
    () => [...(data?.sites ?? [])].sort((a, b) => (b.elevation_m ?? -1) - (a.elevation_m ?? -1)),
    [data],
  );
  /** この項目のデータを実際に持つ地点だけを、標高順に並べたもの */
  const withData = React.useMemo(() => {
    const ids = new Set((data?.points ?? []).map((p) => String(p.site_id)));
    return ordered.filter((s) => ids.has(s.site_id));
  }, [ordered, data]);
  // 色は「地点という実体」に固定する。表示のオン/オフでは塗り替えない。
  const colorOf = React.useCallback(
    (id: string) => {
      const i = withData.findIndex((s) => s.site_id === id);
      return i >= 0 && i < SERIES.length ? SERIES[i] : INK.muted;
    },
    [withData],
  );

  const series: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const bySite = new Map<string, { x: number; y: number; n: number; censored: boolean }[]>();
    for (const p of data.points) {
      const id = String(p.site_id);
      const x = grain === "year" ? Number(p.year) : ymToX(String(p.ym));
      const y = Number(p.avg);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      if (!bySite.has(id)) bySite.set(id, []);
      bySite.get(id)!.push({
        x,
        y,
        n: Number(p.n ?? 0),
        censored: Number(p.n_censored ?? 0) > 0 && Number(p.n_censored) === Number(p.n),
      });
    }
    return withData
      .filter((s) => bySite.has(s.site_id) && !hidden.has(s.site_id))
      .slice(0, 8)
      .map((s) => ({
        key: s.site_id,
        label: `${s.name}${s.elevation_m != null ? ` ${Math.round(s.elevation_m)}m` : ""}`,
        color: colorOf(s.site_id),
        points: bySite.get(s.site_id)!.map((p) => ({ x: p.x, y: p.y, n: p.n, censored: p.censored })),
      }));
  }, [data, withData, grain, hidden, colorOf]);

  // 縦断プロファイル（最新年）
  const profile = React.useMemo(() => {
    if (!data) return { year: null as number | null, rows: [] as { key: string; label: string; value: number; color: string }[] };
    const years = data.points.map((p) => (grain === "year" ? Number(p.year) : Number(String(p.ym).slice(0, 4))));
    const latest = years.length ? Math.max(...years) : null;
    if (latest === null) return { year: null, rows: [] };
    const agg = new Map<string, { sum: number; n: number }>();
    for (const p of data.points) {
      const y = grain === "year" ? Number(p.year) : Number(String(p.ym).slice(0, 4));
      if (y !== latest) continue;
      const id = String(p.site_id);
      const a = agg.get(id) ?? { sum: 0, n: 0 };
      a.sum += Number(p.avg) * Number(p.n ?? 1);
      a.n += Number(p.n ?? 1);
      agg.set(id, a);
    }
    return {
      year: latest,
      rows: withData
        .filter((s) => agg.has(s.site_id))
        .map((s) => ({
          key: s.site_id,
          label: `${s.name}（${s.elevation_m != null ? Math.round(s.elevation_m) + "m" : "標高不明"}）`,
          value: agg.get(s.site_id)!.sum / agg.get(s.site_id)!.n,
          color: colorOf(s.site_id),
        })),
    };
  }, [data, withData, grain, colorOf]);

  const heat = React.useMemo(() => {
    const pts = monthly.data?.points ?? [];
    if (!pts.length) return { cells: [] as { x: number; y: number; v: number; n: number }[], years: [] as number[] };
    const agg = new Map<string, { sum: number; n: number }>();
    for (const p of pts) {
      const k = `${p.year}|${p.month}`;
      const a = agg.get(k) ?? { sum: 0, n: 0 };
      a.sum += p.avg * p.n;
      a.n += p.n;
      agg.set(k, a);
    }
    const years = [...new Set(pts.map((p) => p.year))].sort((a, b) => a - b);
    return {
      years,
      cells: [...agg.entries()].map(([k, a]) => {
        const [y, m] = k.split("|").map(Number);
        return { x: y, y: m, v: a.sum / a.n, n: a.n };
      }),
    };
  }, [monthly.data]);

  const worse = HIGHER_IS_WORSE[variable];

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="xl:col-span-2 space-y-4">
        <ChartFrame
          title={`${water} の ${shortVariable(variable)}｜地点別${grain === "year" ? "年平均" : "月平均"}`}
          subtitle={`線の色は地点。標高の高い順に色を固定してあるので、上から下へ川を下る並びになる。${
            worse === true ? "この項目は値が大きいほど汚れている。" : worse === false ? "この項目は値が小さいほど酸素が乏しい。" : ""
          }`}
          legend={series.map((s) => ({ label: s.label, color: s.color }))}
          height={320}
          table={
            <MiniTable
              columns={["地点", grain === "year" ? "年" : "年月", `平均${unit ? `（${unit}）` : ""}`, "n"]}
              rows={series.flatMap((s) =>
                s.points.map((p) => [
                  s.label,
                  grain === "year" ? String(p.x) : xToYm(p.x),
                  p.y as number,
                  p.n ?? null,
                ]),
              )}
            />
          }
          note={
            <>
              {caveatBody("duplicates")} {caveatBody("censored")}
              {kind === "annual" && ` ${caveatBody("measuredOn")}`}
            </>
          }
        >
          <LineChart
            series={series}
            height={320}
            unit={unit}
            xFormat={(x) => (grain === "year" ? String(Math.round(x)) : xToYm(x))}
            emptyMessage="この水域にこの項目のデータがありません"
          />
        </ChartFrame>

        <ChartFrame
          title={`同じ水域の地点を上流から下流へ並べる（${profile.year ?? "–"}年）`}
          subtitle="標高の高い順。川を下るにつれて値がどう変わるかを一本の棒で見る"
          table={<MiniTable columns={["地点", `値${unit ? `（${unit}）` : ""}`]} rows={profile.rows.map((r) => [r.label, r.value])} />}
        >
          {profile.rows.length ? (
            <BarChart data={profile.rows} unit={unit} maxLabelWidth={190} />
          ) : (
            <p className="text-[12px] text-muted p-6 text-center">データがありません</p>
          )}
        </ChartFrame>
      </div>

      <div className="xl:col-span-2 order-last xl:order-none">
        {kind === "daily" && (
        <ChartFrame
          title={`年 × 月のヒートマップ（${water} の全地点平均）`}
          subtitle="縦が月、横が年。季節の型が年をまたいで安定しているか、ある年だけ崩れているかを一枚で見る"
          table={
            <MiniTable
              columns={["年", "月", `平均${unit ? `（${unit}）` : ""}`, "n"]}
              rows={(monthly.data?.points ?? []).map((p) => [p.year, p.month, p.avg, p.n])}
            />
          }
          note="空白のセルはその月に採水が無かったことを示す。月1回の定期観測なので、欠けている月がある地点も多い。"
        >
          {heat.cells.length ? (
            <Heatmap
              cells={heat.cells}
              xDomain={heat.years}
              yDomain={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}
              xFormat={(v) => String(v)}
              yFormat={(v) => `${v}月`}
              xLabel="年"
              yLabel="月"
              unit={unit}
              height={230}
            />
          ) : (
            <p className="text-[12px] text-muted p-6 text-center">月別の集計がありません</p>
          )}
        </ChartFrame>
        )}
        {kind === "annual" && (
          <p className="text-[11.5px] text-muted card p-3 leading-relaxed">
            年度集計値には月の情報がないため、年 × 月のヒートマップは出せない。
            月別に見たい項目は「元データ: 検体値」に切り替えること。
          </p>
        )}
      </div>

      <div className="space-y-4">
        <div className="card p-3">
          <h3 className="text-[13px] font-semibold mb-2">
            地点（標高順）
            <span className="ml-1.5 text-[10.5px] font-normal text-muted">この項目のデータがある {withData.length} 地点</span>
          </h3>
          <ul className="space-y-0.5">
            {withData.map((s, i) => {
              const off = hidden.has(s.site_id);
              const over = i >= 8;
              return (
                <li key={s.site_id}>
                  <button
                    onClick={() => {
                      const next = new Set(hidden);
                      if (off) next.delete(s.site_id);
                      else next.add(s.site_id);
                      setHidden(next);
                    }}
                    className={`w-full text-left flex items-center gap-2 px-1.5 py-1 rounded hover:bg-surface-2 ${
                      off ? "opacity-40" : ""
                    }`}
                    disabled={over}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0 border"
                      style={{ background: over ? "transparent" : colorOf(s.site_id), borderColor: INK.axis }}
                    />
                    <span className="text-[12px] truncate">{s.name}</span>
                    <span className="ml-auto text-[10.5px] text-muted tnum shrink-0">
                      {s.elevation_m != null ? `${Math.round(s.elevation_m)}m` : "–"}
                    </span>
                    {s.zone != null && (
                      <span
                        className="text-[9px] px-1 rounded text-white shrink-0"
                        style={{ background: ZONE_COLORS[s.zone] }}
                        title={ZONE_LABELS[s.zone]}
                      >
                        Z{s.zone}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
          {withData.length > 8 && (
            <p className="text-[10px] text-muted mt-2">
              1枚の図に載せるのは8地点まで。9地点目以降は色を割り当てない（色を作り足すと見分けがつかなくなるため）。
            </p>
          )}
          <Provenance>
            環境省 公共用水域水質測定結果（政府標準利用規約準拠）。地点は環境省 水質測定点マスタ、標高は国土地理院 標高API。
          </Provenance>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* ゾーン（Ridge to Reef）                                             */
/* ------------------------------------------------------------------ */

function ZoneMode({ variable, kind, unit }: { variable: string; kind: "daily" | "annual"; unit: string | null }) {
  const { data, loading, error } = useJson<{
    points: { zone: number; year: number; n_sites: number; n: number; avg: number }[];
  }>(`/api/timeseries?mode=zone&variable=${encodeURIComponent(variable)}&kind=${kind}`);

  const series: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const byZone = new Map<number, { x: number; y: number; n: number }[]>();
    for (const p of data.points) {
      if (p.zone == null) continue;
      if (!byZone.has(p.zone)) byZone.set(p.zone, []);
      byZone.get(p.zone)!.push({ x: p.year, y: p.avg, n: p.n });
    }
    return [...byZone.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([z, pts]) => ({
        key: "z" + z,
        label: `${z}. ${ZONE_LABELS[z]}`,
        color: ZONE_COLORS[z],
        points: pts.sort((a, b) => a.x - b.x),
      }));
  }, [data]);

  const latest = React.useMemo(() => {
    if (!data?.points.length) return { year: 0, rows: [] as { key: string; label: string; value: number; color: string }[] };
    const y = Math.max(...data.points.map((p) => p.year));
    return {
      year: y,
      rows: data.points
        .filter((p) => p.year === y && p.zone != null)
        .sort((a, b) => a.zone - b.zone)
        .map((p) => ({
          key: "z" + p.zone,
          label: `${p.zone}. ${ZONE_LABELS[p.zone]}（${p.n_sites}地点）`,
          value: p.avg,
          color: ZONE_COLORS[p.zone],
        })),
    };
  }, [data]);

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <ChartFrame
        title={`ゾーン別の年平均｜${shortVariable(variable)}`}
        subtitle="尾根（1）から海（5）までの区分ごとに、その年の平均を並べたもの"
        legend={series.map((s) => ({ label: s.label, color: s.color }))}
        height={300}
        table={
          <MiniTable
            columns={["ゾーン", "年", `平均${unit ? `（${unit}）` : ""}`, "地点数"]}
            rows={(data?.points ?? []).map((p) => [`${p.zone}. ${ZONE_LABELS[p.zone]}`, p.year, p.avg, p.n_sites])}
          />
        }
        note={caveatBody("zone")}
      >
        <LineChart
          series={series}
          height={300}
          unit={unit}
          xFormat={(x) => String(Math.round(x))}
          emptyMessage="この項目にはゾーン別の集計がありません"
        />
      </ChartFrame>

      <ChartFrame
        title={`${latest.year} 年のゾーン間の差`}
        subtitle="同じ年の断面。ゾーンをまたぐ勾配があるかどうかを見る"
        table={<MiniTable columns={["ゾーン", `平均${unit ? `（${unit}）` : ""}`]} rows={latest.rows.map((r) => [r.label, r.value])} />}
        note="ゾーン1（標高800m超）には水質測定点が無いため、この図には現れない。"
      >
        {latest.rows.length ? (
          <BarChart data={latest.rows} unit={unit} maxLabelWidth={180} />
        ) : (
          <p className="text-[12px] text-muted p-6 text-center">データがありません</p>
        )}
      </ChartFrame>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 季節                                                                */
/* ------------------------------------------------------------------ */

function SeasonMode({ variable, unit }: { variable: string; unit: string | null }) {
  const { data, loading, error } = useJson<{
    overall: { month: number; n: number; avg: number; min: number; max: number }[];
    byZone: { zone: number; month: number; n: number; avg: number }[];
    rain: { month: number; mm: number }[];
  }>(`/api/timeseries?mode=season&variable=${encodeURIComponent(variable)}`);

  const zoneSeries: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const byZone = new Map<number, { x: number; y: number; n: number }[]>();
    for (const p of data.byZone) {
      if (p.zone == null) continue;
      if (!byZone.has(p.zone)) byZone.set(p.zone, []);
      byZone.get(p.zone)!.push({ x: p.month, y: p.avg, n: p.n });
    }
    return [...byZone.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([z, pts]) => ({
        key: "z" + z,
        label: `${z}. ${ZONE_LABELS[z]}`,
        color: ZONE_COLORS[z],
        points: pts.sort((a, b) => a.x - b.x),
      }));
  }, [data]);

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  const rain = data?.rain ?? [];

  return (
    <div className="space-y-4">
      <ChartFrame
        title={`月ごとの平均｜${shortVariable(variable)}（全期間・全地点）`}
        subtitle="ゾーンごとに月別平均を重ねる。上流ほど年間の振れ幅が小さいかどうかが読める"
        legend={zoneSeries.map((s) => ({ label: s.label, color: s.color }))}
        height={280}
        table={
          <MiniTable
            columns={["月", `全体平均${unit ? `（${unit}）` : ""}`, "最小", "最大", "n"]}
            rows={(data?.overall ?? []).map((p) => [`${p.month}月`, p.avg, p.min, p.max, p.n])}
          />
        }
      >
        <LineChart
          series={zoneSeries}
          height={280}
          unit={unit}
          xFormat={(x) => `${Math.round(x)}月`}
          xTicks={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]}
          emptyMessage="この項目には月別の集計がありません"
        />
      </ChartFrame>

      <ChartFrame
        title="同じ月の降水量（相模原・2015–2025 の月平均）"
        subtitle="水質の季節変化を読むときの背景。縦軸が違うので別の図として並べている（1枚に2つの軸を置かない）"
        note="相模原市 大気汚染常時監視 1時間値の RAIN。原本に単位の記載がないが、年合計が神奈川の年降水量と整合するため 0.1mm 単位とみなして mm に換算している。観測点の緯度経度が公開されていないため地図には出せない。"
      >
        <ColumnChart
          data={rain.map((r) => ({ x: r.month, value: r.mm }))}
          height={110}
          xFormat={(x) => `${Math.round(x)}月`}
          unit="mm"
          xDomain={[1, 12]}
        />
      </ChartFrame>
    </div>
  );
}

/* ------------------------------ 共通 ------------------------------ */

/** 'YYYY-MM' を「年 + 月/12」の数値に変換して連続軸に載せる */
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
