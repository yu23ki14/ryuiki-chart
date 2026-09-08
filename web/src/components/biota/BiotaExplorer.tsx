"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { StackedArea, type StackSeries } from "@/components/viz/StackedArea";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { BarChart } from "@/components/viz/BarChart";
import { SlopeChart, type SlopeFlow } from "@/components/viz/SlopeChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, seriesColor, INK, STATUS } from "@/components/viz/palette";
import { Btn, inputCls, Spinner, Stat, nf, Provenance } from "@/components/ui";
import { speciesLabel, caveatBody } from "@/lib/registry/lookup-client";
import { useJson } from "@/components/useJson";
import { useSetPageContext } from "@/components/assistant/PageContextProvider";

type Tab = "effort" | "trend" | "ias" | "redlist";

const TABS: [Tab, string, string][] = [
  ["effort", "記録の中身", "誰が何を記録してきたか。件数を読む前に見る"],
  ["trend", "種のふえへり", "分類群の中でのシェアで前後の期間を比べる"],
  ["ias", "外来種", "生態系被害防止外来種リストに載る種の記録"],
  ["redlist", "レッドリスト版間比較", "2006年版から現行版へ、カテゴリーがどう動いたか"],
];

export function BiotaExplorer() {
  // ディープリンク用に、初期値だけ searchParams から取る（既存の useState 構造は保つ。書き戻しはしない）。
  const sp = useSearchParams();
  const [tab, setTab] = React.useState<Tab>(() => {
    const t = sp.get("tab");
    return t === "effort" || t === "trend" || t === "ias" || t === "redlist" ? t : "effort";
  });
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="no-print border-b border-line bg-surface px-4 py-2 flex items-center gap-1 flex-wrap">
        {TABS.map(([t, label, note]) => (
          <Btn key={t} active={tab === t} onClick={() => setTab(t)} title={note}>
            {label}
          </Btn>
        ))}
        <p className="text-[10.5px] text-muted ml-auto max-w-lg leading-snug">
          出典: GBIF（658,360件）と iNaturalist（165,332件）。神奈川県内の観察・標本記録。
        </p>
      </div>
      <div className="flex-1 overflow-y-auto thin-scroll p-4">
        {tab === "effort" && <EffortTab />}
        {tab === "trend" && <TrendTab />}
        {tab === "ias" && <IasTab />}
        {tab === "redlist" && <RedlistTab />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 1. 記録の中身                                                        */
/* ------------------------------------------------------------------ */

const GROUP_ORDER = ["鳥類", "被子植物", "昆虫類", "菌類", "シダ植物", "貝類・軟体動物", "魚類"];

function EffortTab() {
  useSetPageContext({ route: "/biota", title: "生物相", tab: "effort" });
  const { data, loading, error } = useJson<{
    groups: { year: number; taxon_group: string; n: number; mesh_n: number }[];
    effort: { year: number; n: number; species_n: number; mesh_n: number; n_inat: number; n_gbif: number }[];
    totals: { records: number; species: number; mesh: number; gbif: number; inat: number };
  }>("/api/biota?kind=effort");
  const [normalize, setNormalize] = React.useState(true);

  const { stacks, xs } = React.useMemo(() => {
    if (!data) return { stacks: [] as StackSeries[], xs: [] as number[] };
    const years = [...new Set(data.groups.map((g) => g.year))].filter((y) => y >= 2000).sort((a, b) => a - b);
    const keys = [...GROUP_ORDER];
    const map = new Map<string, Map<number, number>>();
    for (const k of [...keys, "その他"]) map.set(k, new Map());
    for (const g of data.groups) {
      if (g.year < 2000) continue;
      const k = keys.includes(g.taxon_group) ? g.taxon_group : "その他";
      const m = map.get(k)!;
      m.set(g.year, (m.get(g.year) ?? 0) + g.n);
    }
    return {
      xs: years,
      stacks: [...keys, "その他"].map((k, i) => ({
        key: k,
        label: k,
        color: k === "その他" ? "#c3cfcc" : seriesColor(i),
        values: map.get(k)!,
      })),
    };
  }, [data]);

  const effortSeries: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const e = data.effort.filter((r) => r.year >= 2000);
    return [
      { key: "gbif", label: "GBIF", color: SERIES[0], points: e.map((r) => ({ x: r.year, y: r.n_gbif })) },
      { key: "inat", label: "iNaturalist", color: SERIES[1], points: e.map((r) => ({ x: r.year, y: r.n_inat })) },
    ];
  }, [data]);

  const meshSeries: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const e = data.effort.filter((r) => r.year >= 2000);
    return [
      {
        key: "mesh",
        label: "メッシュ数",
        color: SERIES[2],
        points: e.map((r) => ({ x: r.year, y: r.mesh_n })),
      },
      {
        key: "sp",
        label: "種数",
        color: SERIES[6],
        points: e.map((r) => ({ x: r.year, y: r.species_n })),
      },
    ];
  }, [data]);

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  const last = data?.effort.at(-1);
  const total = data?.effort.reduce((s, r) => s + r.n, 0) ?? 0;

  return (
    <div className="space-y-4">
      <div className="card p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat
          label="生物レコード（全期間）"
          value={nf(data?.totals.records)}
          unit="件"
          note={`GBIF ${nf(data?.totals.gbif)} / iNaturalist ${nf(data?.totals.inat)}`}
        />
        <Stat label="学名（二名法）の種類" value={nf(data?.totals.species)} note="亜種・変種を種にまとめた数" />
        <Stat label="記録のある1kmメッシュ" value={nf(data?.totals.mesh)} note="0.01度グリッド。県内をほぼ覆う" />
        <Stat label="直近年の記録数" value={nf(last?.n ?? 0)} unit="件" note={`${last?.year ?? "–"}年`} />
      </div>

      <ChartFrame
        title="年ごとの記録の中身（分類群の構成）"
        subtitle="件数の増減を読む前に、その年に「誰が何を記録していたか」を見る図。中身は10年で入れ替わっている"
        legend={stacks.map((s) => ({ label: s.label, color: s.color }))}
        right={
          <div className="flex gap-0.5">
            <Btn active={normalize} onClick={() => setNormalize(true)}>
              構成比
            </Btn>
            <Btn active={!normalize} onClick={() => setNormalize(false)}>
              実数
            </Btn>
          </div>
        }
        table={
          <MiniTable
            columns={["年", ...stacks.map((s) => s.label)]}
            rows={xs.map((y) => [y, ...stacks.map((s) => s.values.get(y) ?? 0)])}
          />
        }
        note={
          <>
            {caveatBody("regimes")} {caveatBody("inatBackfill")} {caveatBody("fishClass")}
          </>
        }
      >
        {xs.length > 0 && (
          <StackedArea series={stacks} xs={xs} height={260} normalize={normalize} xFormat={(x) => String(Math.round(x))} unit="件" />
        )}
      </ChartFrame>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartFrame
          title="出典別の記録数"
          subtitle="2024年12月に GBIF 側の取り込みが途切れ、2025年以降は iNaturalist が主になる"
          legend={effortSeries.map((s) => ({ label: s.label, color: s.color }))}
          height={240}
          table={
            <MiniTable
              columns={["年", "GBIF", "iNaturalist"]}
              rows={(data?.effort ?? []).filter((r) => r.year >= 2000).map((r) => [r.year, r.n_gbif, r.n_inat])}
            />
          }
          note={caveatBody("gbifCutoff")}
        >
          <LineChart
            series={effortSeries}
            height={240}
            unit="件"
            xFormat={(x) => String(Math.round(x))}
            annotations={[{ x: 2024.95, label: "GBIF 取り込み終了", color: STATUS.critical }]}
            yZero
          />
        </ChartFrame>

        <ChartFrame
          title="観察努力の代理指標"
          subtitle="記録されたメッシュ数と種数。どちらも「生きものの量」ではなく「人の活動量」を写している"
          legend={[
            { label: "記録があった1kmメッシュ数", color: SERIES[2] },
            { label: "確認された種数", color: SERIES[6] },
          ]}
          height={240}
          table={
            <MiniTable
              columns={["年", "メッシュ数", "種数", "件数"]}
              rows={(data?.effort ?? []).filter((r) => r.year >= 2000).map((r) => [r.year, r.mesh_n, r.species_n, r.n])}
            />
          }
          note={caveatBody("effort")}
        >
          <LineChart series={meshSeries} height={240} xFormat={(x) => String(Math.round(x))} yZero />
        </ChartFrame>
      </div>

      <Provenance>
        GBIF Occurrence（神奈川県, GADM JPN.19_1）— データセットごとに CC0 / CC BY / CC BY-NC が混在。
        iNaturalist 観察記録（place 10918）— 観察ごとに個別ライセンス。総件数 {nf(total)} 件（1990年以降）。
      </Provenance>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 2. 種のふえへり                                                      */
/* ------------------------------------------------------------------ */

const TREND_GROUPS = ["鳥類", "昆虫類", "被子植物", "菌類", "貝類・軟体動物", "クモ・ダニ類"];

function TrendTab() {
  // ディープリンク用に、初期値だけ searchParams から取る（既存の useState 構造は保つ。書き戻しはしない）。
  const sp = useSearchParams();
  const [group, setGroup] = React.useState(() => sp.get("group") ?? "鳥類");
  const [a, setA] = React.useState<[number, number]>(() => {
    const a0 = Number(sp.get("a0"));
    const a1 = Number(sp.get("a1"));
    return Number.isFinite(a0) && Number.isFinite(a1) ? [a0, a1] : [2018, 2020];
  });
  const [b, setB] = React.useState<[number, number]>(() => {
    const b0 = Number(sp.get("b0"));
    const b1 = Number(sp.get("b1"));
    return Number.isFinite(b0) && Number.isFinite(b1) ? [b0, b1] : [2022, 2024];
  });
  const [picked, setPicked] = React.useState<string[]>(() => {
    const p = sp.get("picked");
    return p ? p.split(",").filter(Boolean) : [];
  });

  useSetPageContext({ route: "/biota", title: "生物相", tab: "trend", group, periodA: a, periodB: b, picked });

  const { data, loading, error } = useJson<{
    rows: { binom: string; en_name: string; n_a: number; n_b: number; total_a: number; total_b: number }[];
  }>(`/api/biota?kind=trend&group=${encodeURIComponent(group)}&a0=${a[0]}&a1=${a[1]}&b0=${b[0]}&b1=${b[1]}`);

  const scored = React.useMemo(() => {
    if (!data?.rows.length) return [];
    return data.rows
      .map((r) => {
        const pa = (r.n_a / (r.total_a || 1)) * 1000;
        const pb = (r.n_b / (r.total_b || 1)) * 1000;
        return { ...r, pa, pb, ratio: pa > 0 ? pb / pa : 0 };
      })
      .filter((r) => Number.isFinite(r.ratio) && r.ratio > 0)
      .sort((x, y) => y.ratio - x.ratio);
  }, [data]);

  const up = scored.slice(0, 10);
  const down = [...scored].reverse().slice(0, 10);

  const series = useJson<{ years: { binom: string; year: number; n: number; mesh_n: number }[] }>(
    picked.length ? `/api/biota?kind=species&binoms=${encodeURIComponent(picked.join(","))}` : "",
  );

  const lines: LineSeries[] = React.useMemo(() => {
    if (!series.data) return [];
    const byB = new Map<string, { x: number; y: number }[]>();
    for (const r of series.data.years) {
      if (!byB.has(r.binom)) byB.set(r.binom, []);
      byB.get(r.binom)!.push({ x: r.year, y: r.mesh_n });
    }
    return picked.slice(0, 8).map((bn, i) => ({
      key: bn,
      label: speciesLabel(bn),
      color: seriesColor(i),
      points: (byB.get(bn) ?? []).sort((p, q) => p.x - q.x),
    }));
  }, [series.data, picked]);

  const toggle = (bn: string) =>
    setPicked((p) => (p.includes(bn) ? p.filter((x) => x !== bn) : [...p, bn].slice(-8)));

  return (
    <div className="space-y-4">
      <div className="card p-3 flex items-end gap-3 flex-wrap">
        <label>
          <span className="block text-[10.5px] text-muted mb-1">分類群</span>
          <select className={inputCls + " w-44"} value={group} onChange={(e) => setGroup(e.target.value)}>
            {TREND_GROUPS.map((g) => (
              <option key={g}>{g}</option>
            ))}
          </select>
        </label>
        <YearRange label="前の期間" value={a} onChange={setA} />
        <YearRange label="後の期間" value={b} onChange={setB} />
        <p className="text-[10.5px] text-muted max-w-md ml-auto leading-snug">{caveatBody("share")}</p>
      </div>

      {loading && !data ? (
        <Spinner label="集計中" />
      ) : error ? (
        <p className="text-bad text-sm">{error}</p>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ChartFrame
            title={`シェアが増えた種（${group}）`}
            subtitle={`${a[0]}–${a[1]} → ${b[0]}–${b[1]}。分類群内の千分率の比。棒をクリックすると下の図に足せる`}
            table={
              <MiniTable
                columns={["種", `前期(‰)`, `後期(‰)`, "倍率", "前期件数", "後期件数"]}
                rows={up.map((r) => [speciesLabel(r.binom, r.en_name), r.pa, r.pb, r.ratio, r.n_a, r.n_b])}
              />
            }
          >
            <BarChart
              data={up.map((r) => ({
                key: r.binom,
                label: speciesLabel(r.binom, r.en_name),
                value: r.ratio,
                note: r.binom,
              }))}
              color={SERIES[2]}
              maxLabelWidth={170}
              valueFormat={(v) => `×${v.toFixed(2)}`}
              onClick={(d) => toggle(d.key)}
            />
          </ChartFrame>

          <ChartFrame
            title={`シェアが減った種（${group}）`}
            subtitle="同じ期間・同じ分母。1.0 を下回るほど、その分類群の中での存在感が減っている"
            table={
              <MiniTable
                columns={["種", `前期(‰)`, `後期(‰)`, "倍率", "前期件数", "後期件数"]}
                rows={down.map((r) => [speciesLabel(r.binom, r.en_name), r.pa, r.pb, r.ratio, r.n_a, r.n_b])}
              />
            }
          >
            <BarChart
              data={down.map((r) => ({
                key: r.binom,
                label: speciesLabel(r.binom, r.en_name),
                value: r.ratio,
                note: r.binom,
              }))}
              color={SERIES[1]}
              maxLabelWidth={170}
              valueFormat={(v) => `×${v.toFixed(2)}`}
              onClick={(d) => toggle(d.key)}
            />
          </ChartFrame>
        </div>
      )}

      <ChartFrame
        title="選んだ種の分布メッシュ数の推移"
        subtitle="件数ではなく「その種が記録された1kmメッシュの数」。同じ場所での重複記録に左右されにくい"
        legend={lines.map((s) => ({ label: s.label, color: s.color }))}
        height={280}
        table={
          <MiniTable
            columns={["種", "年", "メッシュ数", "件数"]}
            rows={(series.data?.years ?? []).map((r) => [speciesLabel(r.binom), r.year, r.mesh_n, r.n])}
          />
        }
        note="上の棒グラフをクリックすると種を足せる（最大8種）。もう一度クリックで外れる。"
      >
        <LineChart
          series={lines}
          height={280}
          xFormat={(x) => String(Math.round(x))}
          yZero
          emptyMessage="上の棒グラフから種を選んでください"
        />
      </ChartFrame>
    </div>
  );
}

function YearRange({
  label,
  value,
  onChange,
}: {
  label: string;
  value: [number, number];
  onChange: (v: [number, number]) => void;
}) {
  return (
    <div>
      <span className="block text-[10.5px] text-muted mb-1">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          className={inputCls + " w-[68px]"}
          value={value[0]}
          onChange={(e) => onChange([Number(e.target.value), value[1]])}
        />
        <span className="text-muted text-[11px]">–</span>
        <input
          type="number"
          className={inputCls + " w-[68px]"}
          value={value[1]}
          onChange={(e) => onChange([value[0], Number(e.target.value)])}
        />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 3. 外来種                                                            */
/* ------------------------------------------------------------------ */

const IAS_ORDER = ["緊急対策外来種", "重点対策外来種", "その他の総合対策外来種", "侵入予防外来種", "その他の定着予防外来種", "産業管理外来種"];

function IasTab() {
  useSetPageContext({ route: "/biota", title: "生物相", tab: "ias" });
  const { data, loading, error } = useJson<{
    rows: {
      ias_category: string;
      binom: string;
      name_ja: string | null;
      taxon_group: string;
      en_name: string;
      n: number;
      mesh_n: number;
      y_from: number;
      y_to: number;
      n_since_2020: number;
    }[];
  }>("/api/biota?kind=ias");
  const [cat, setCat] = React.useState<string>("すべて");
  const [picked, setPicked] = React.useState<string>("Hestina assimilis");

  const mesh = useJson<{ rows: { year: number; mlat: number; mlon: number; n: number }[] }>(
    picked ? `/api/biota?kind=mesh&binom=${encodeURIComponent(picked)}` : "",
  );
  const effort = useJson<{ effort: { year: number; mesh_n: number }[] }>("/api/biota?kind=effort");

  const rows = React.useMemo(
    () => (data?.rows ?? []).filter((r) => cat === "すべて" || r.ias_category === cat),
    [data, cat],
  );

  // 占有率 = その種が出たメッシュ数 ÷ その年に何かが記録されたメッシュ数
  const occupancy: LineSeries[] = React.useMemo(() => {
    if (!mesh.data || !effort.data) return [];
    const denom = new Map(effort.data.effort.map((e) => [e.year, e.mesh_n]));
    const byYear = new Map<number, Set<string>>();
    for (const r of mesh.data.rows) {
      if (!byYear.has(r.year)) byYear.set(r.year, new Set());
      byYear.get(r.year)!.add(`${r.mlat}_${r.mlon}`);
    }
    const pts = [...byYear.entries()]
      .filter(([y]) => y >= 2005 && (denom.get(y) ?? 0) > 0)
      .sort((x, y) => x[0] - y[0])
      .map(([y, s]) => ({ x: y, y: (s.size / (denom.get(y) as number)) * 100, n: s.size }));
    return [{ key: picked, label: speciesLabel(picked), color: SERIES[1], points: pts }];
  }, [mesh.data, effort.data, picked]);

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  const byCat = IAS_ORDER.map((c) => ({
    key: c,
    label: c,
    value: (data?.rows ?? []).filter((r) => r.ias_category === c).reduce((s, r) => s + r.n, 0),
  })).filter((r) => r.value > 0);

  return (
    <div className="space-y-4">
      <div className="card p-3">
        <p className="text-[12px] text-ink-2 leading-relaxed">
          外来種の判定に、原本の <code className="font-mono text-[11px]">is_alien</code> フラグは使っていない。
          {caveatBody("isAlien")}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartFrame
          title="対策カテゴリー別の記録数"
          subtitle="環境省 生態系被害防止外来種リストの区分。記録数であって個体数ではない"
          table={<MiniTable columns={["区分", "記録数"]} rows={byCat.map((r) => [r.label, r.value])} />}
        >
          <BarChart data={byCat} color={SERIES[1]} maxLabelWidth={170} unit="件" onClick={(d) => setCat(d.key)} />
        </ChartFrame>

        <ChartFrame
          title={`${speciesLabel(picked)} の分布メッシュ占有率`}
          subtitle="その年に記録があった全メッシュのうち、この種が出たメッシュの割合。観察努力の増加を割り算で除いている"
          legend={occupancy.map((s) => ({ label: s.label, color: s.color }))}
          height={260}
          table={
            <MiniTable
              columns={["年", "占有率(%)", "出現メッシュ数"]}
              rows={(occupancy[0]?.points ?? []).map((p) => [p.x, p.y as number, p.n ?? null])}
            />
          }
          note="この指標でも、記録する人が偏った場所に集中すれば動く。傾向の向きを見るための指標として使う。"
        >
          <LineChart
            series={occupancy}
            height={260}
            unit="%"
            xFormat={(x) => String(Math.round(x))}
            yZero
            emptyMessage="下の表から種を選んでください"
          />
        </ChartFrame>
      </div>

      <div className="card overflow-hidden">
        <div className="px-3.5 py-2 border-b border-line flex items-center gap-2 flex-wrap">
          <h3 className="text-[13px] font-semibold">外来種の記録一覧</h3>
          <select className={inputCls + " w-52 ml-auto"} value={cat} onChange={(e) => setCat(e.target.value)}>
            <option>すべて</option>
            {IAS_ORDER.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="overflow-auto thin-scroll max-h-[420px]">
          <table className="dtable">
            <thead>
              <tr>
                <th>区分</th>
                <th>学名</th>
                <th>和名（外来種リスト）</th>
                <th>分類群</th>
                <th>記録数</th>
                <th>メッシュ数</th>
                <th>初記録</th>
                <th>最新</th>
                <th>2020年以降</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((r) => (
                <tr
                  key={r.binom}
                  onClick={() => setPicked(r.binom)}
                  className="cursor-pointer"
                  style={picked === r.binom ? { background: "var(--water-soft)" } : undefined}
                >
                  <td>{r.ias_category}</td>
                  <td className="font-mono italic">{r.binom}</td>
                  <td>{r.name_ja ?? "–"}</td>
                  <td>{r.taxon_group}</td>
                  <td className="num">{nf(r.n)}</td>
                  <td className="num">{nf(r.mesh_n)}</td>
                  <td className="num">{r.y_from}</td>
                  <td className="num">{r.y_to}</td>
                  <td className="num">{nf(r.n_since_2020)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Provenance>
          環境省 生態系被害防止外来種リスト（公共データ利用規約 第1.0版 / PDL1.0）を学名の二名法キーで観察記録に結合したもの。
          国内由来の別地域個体群として掲載されている 7 種（タヌキ・オオバコ・カブトムシ・ヤマグワ・セイヨウミツバチ・ニホンジカ・ギシギシ）は
          県内の在来個体群と区別できないため除外している。和名はリスト側の表記で、県内の個体群と一致しない場合がある。
        </Provenance>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 4. レッドリスト版間比較                                              */
/* ------------------------------------------------------------------ */

function RedlistTab() {
  const [year, setYear] = React.useState(2022);
  const [group, setGroup] = React.useState<string>("");
  const [dir, setDir] = React.useState<string>("");

  useSetPageContext({ route: "/biota", title: "生物相", tab: "redlist", group: group || undefined });

  const { data, loading, error } = useJson<{
    flows: { prev_label: string; cur_label: string; direction: string; n: number }[];
    species: {
      vernacular_name_ja: string;
      scientific_name: string | null;
      family_ja: string | null;
      taxon_group_ja: string;
      prev_label: string;
      cur_label: string;
      prev_rank: number;
      cur_rank: number;
      direction: string;
      national_category_ja: string | null;
    }[];
    summary: { list_year: number; list_name: string; taxon_group_ja: string; direction: string; n: number }[];
  }>(`/api/biota?kind=redlist&year=${year}${group ? `&group=${encodeURIComponent(group)}` : ""}${dir ? `&direction=${encodeURIComponent(dir)}` : ""}`);

  const cats = React.useMemo(() => {
    const m = new Map<string, number>();
    for (const f of data?.flows ?? []) {
      m.set(f.prev_label, rankOf(f.prev_label));
      m.set(f.cur_label, rankOf(f.cur_label));
    }
    return [...m.entries()].map(([label, rank]) => ({ key: label, label, rank }));
  }, [data]);

  const flows: SlopeFlow[] = React.useMemo(
    () =>
      (data?.flows ?? []).map((f) => ({
        from: f.prev_label,
        to: f.cur_label,
        n: f.n,
        direction: f.direction as SlopeFlow["direction"],
      })),
    [data],
  );

  const counts = React.useMemo(() => {
    const c = { 悪化: 0, 改善: 0, 横ばい: 0 };
    for (const f of flows) if (f.direction in c) c[f.direction as keyof typeof c] += f.n;
    return c;
  }, [flows]);

  const groups = React.useMemo(
    () => [...new Set((data?.summary ?? []).filter((s) => s.list_year === year).map((s) => s.taxon_group_ja))],
    [data, year],
  );

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  return (
    <div className="space-y-4">
      <div className="card p-3 flex items-end gap-3 flex-wrap">
        <div>
          <span className="block text-[10.5px] text-muted mb-1">比較する版</span>
          <div className="flex gap-0.5">
            <Btn active={year === 2020} onClick={() => { setYear(2020); setGroup(""); }}>
              2020 植物編
            </Btn>
            <Btn active={year === 2022} onClick={() => { setYear(2022); setGroup(""); }}>
              2022 植物編
            </Btn>
            <Btn active={year === 2026} onClick={() => { setYear(2026); setGroup(""); }}>
              2026 昆虫・クモ
            </Btn>
          </div>
        </div>
        <label>
          <span className="block text-[10.5px] text-muted mb-1">分類群</span>
          <select className={inputCls + " w-44"} value={group} onChange={(e) => setGroup(e.target.value)}>
            <option value="">すべて</option>
            {groups.map((g) => (
              <option key={g}>{g}</option>
            ))}
          </select>
        </label>
        <div>
          <span className="block text-[10.5px] text-muted mb-1">向き</span>
          <div className="flex gap-0.5">
            {["", "悪化", "改善", "横ばい"].map((d) => (
              <Btn key={d || "all"} active={dir === d} onClick={() => setDir(d)}>
                {d || "すべて"}
              </Btn>
            ))}
          </div>
        </div>
        <div className="ml-auto flex gap-5">
          <Stat label="悪化" value={nf(counts.悪化)} unit="種" tone="bad" />
          <Stat label="改善" value={nf(counts.改善)} unit="種" tone="ok" />
          <Stat label="横ばい" value={nf(counts.横ばい)} unit="種" />
        </div>
      </div>

      <ChartFrame
        title={`2006年版 → ${year}年版：カテゴリーの移動`}
        subtitle="帯の太さが種数。上ほど深刻な区分。赤が悪化、青が改善、灰色が横ばい"
        legend={[
          { label: "悪化", color: "#d03b3b" },
          { label: "改善", color: "#2a78d6" },
          { label: "横ばい", color: "#c3cfcc" },
        ]}
        table={
          <MiniTable
            columns={["2006年版", `${year}年版`, "向き", "種数"]}
            rows={(data?.flows ?? []).map((f) => [f.prev_label, f.cur_label, f.direction, f.n])}
          />
        }
        note={
          <>
            カテゴリー表記は版ごとに揺れている（ローマ数字の「Ⅰ」とラテン文字の「I」、全角「Ａ」と半角「A」、余分な空白）。
            正規化してから突き合わせている。2006年版のカテゴリーは、各版が併記している「前回」欄から取っている
            （2006年版そのものは独立したレコードとして収録されていない）。
          </>
        }
      >
        {flows.length > 0 && (
          <SlopeChart
            categories={cats}
            flows={flows}
            leftLabel="2006年版"
            rightLabel={`${year}年版`}
            height={460}
            highlight={dir || null}
          />
        )}
      </ChartFrame>

      <div className="card overflow-hidden">
        <div className="px-3.5 py-2 border-b border-line">
          <h3 className="text-[13px] font-semibold">
            種ごとの移動{dir && `（${dir}のみ）`}
            <span className="ml-2 text-[11px] font-normal text-muted">{nf(data?.species.length ?? 0)} 種</span>
          </h3>
        </div>
        <div className="overflow-auto thin-scroll max-h-[460px]">
          <table className="dtable">
            <thead>
              <tr>
                <th>和名</th>
                <th>科</th>
                <th>分類群</th>
                <th>2006年版</th>
                <th></th>
                <th>{year}年版</th>
                <th>向き</th>
                <th>環境省</th>
              </tr>
            </thead>
            <tbody>
              {(data?.species ?? []).map((s, i) => (
                <tr key={i}>
                  <td className="font-medium">{s.vernacular_name_ja}</td>
                  <td className="text-muted">{s.family_ja ?? "–"}</td>
                  <td className="text-muted">{s.taxon_group_ja}</td>
                  <td>{s.prev_label}</td>
                  <td className="text-muted">→</td>
                  <td>{s.cur_label}</td>
                  <td
                    style={{
                      color: s.direction === "悪化" ? STATUS.critical : s.direction === "改善" ? SERIES[0] : INK.muted,
                    }}
                  >
                    {s.direction}
                  </td>
                  <td className="text-muted">{s.national_category_ja ?? "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Provenance>
          神奈川県レッドリスト2020（植物編）／神奈川県レッドデータブック2022（植物編）／神奈川県レッドリスト2026（昆虫類・クモ類）。
          神奈川県環境農政局緑政部自然環境保全課ほか（神奈川県サイトポリシー：出典記載により利用可）。
          2022年版には学名の記載が無いため和名で表示している。
        </Provenance>
      </div>
    </div>
  );
}

const RANKS: Record<string, number> = {
  絶滅: 70,
  野生絶滅: 65,
  絶滅危惧IA類: 60,
  絶滅危惧I類: 55,
  絶滅危惧IB類: 50,
  絶滅危惧II類: 40,
  地域個体群: 35,
  準絶滅危惧: 30,
  "希少種（2006年版）": 25,
  注目種: 20,
  情報不足: 10,
};
function rankOf(label: string): number {
  return RANKS[label] ?? 0;
}
