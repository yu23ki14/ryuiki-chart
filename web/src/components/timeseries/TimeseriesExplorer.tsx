"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { Heatmap } from "@/components/viz/Heatmap";
import { BarChart, ColumnChart } from "@/components/viz/BarChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, ZONE_COLORS, ZONE_LABELS, INK } from "@/components/viz/palette";
import { Btn, inputCls, Spinner, Provenance, nf } from "@/components/ui";
import { caveatBody } from "@/lib/registry/lookup-client";
import { VARIABLE_LABEL } from "@/lib/registry/generated-client";
import { MUNICIPALITY_LABEL } from "@/lib/municipality";
import { useJson } from "@/components/useJson";
import { useSetPageContext } from "@/components/assistant/PageContextProvider";

type Basis = "day" | "fiscal_year" | "year";
type Grain = "year" | "fiscal_year" | "month" | "day";

interface WaterBody {
  name: string;
  nSites: number;
  elevMin: number | null;
  elevMax: number | null;
  nMeas: number;
  yFrom: number | null;
  yTo: number | null;
}
interface VarRow {
  variableId: string;
  /** 単位の表示記号（サーバ側で解決済み。unit_id そのものではない）。 */
  unit: string | null;
  n: number;
  nPlaces: number;
  yFrom: number;
  yTo: number;
  nByBasis: { day: number; fiscalYear: number; year: number };
  nCensored: number;
  /** 非代表の統計量（p75/p90/max/min 等）。空なら選択肢を出さない（D4）。 */
  stats: string[];
}
interface Site {
  siteId: string;
  name: string | null;
  zone: number | null;
  elevationM: number | null;
  lat: number | null;
  lon: number | null;
}

type Mode = "water" | "zone" | "season";

/** variable_id の表示名（`VARIABLE_LABEL`。無ければ variable_id をそのまま出す）。 */
function variableLabel(variableId: string): string {
  return VARIABLE_LABEL[variableId]?.short ?? variableId;
}

function basisLabel(basis: Basis): string {
  return basis === "day" ? "検体値" : basis === "fiscal_year" ? "年度集計値" : "暦年値";
}

/** この項目が実際に持つ基準（元データの粒度）の一覧。day > fiscal_year > year の優先順で並ぶ。 */
function availableBasesOf(v: VarRow | undefined): Basis[] {
  if (!v) return [];
  const out: Basis[] = [];
  if (v.nByBasis.day > 0) out.push("day");
  if (v.nByBasis.fiscalYear > 0) out.push("fiscal_year");
  if (v.nByBasis.year > 0) out.push("year");
  return out;
}

export function TimeseriesExplorer({ waters, vars }: { waters: WaterBody[]; vars: VarRow[] }) {
  // ディープリンク（AIのチャットカードの「時系列画面でこの表示を開く」など）用に、初期値だけ
  // searchParams から取る。既存の useState 構造はそのまま。URL への書き戻しはしない
  // （双方向同期は下の自動補正と競合するため。Stage 2 ではやらない設計）。
  const sp = useSearchParams();
  const [mode, setMode] = React.useState<Mode>(() => {
    const m = sp.get("mode");
    return m === "zone" || m === "season" ? m : "water";
  });
  const [variableId, setVariableId] = React.useState(() => sp.get("variable") ?? "common:variable:water.bod");
  const [waterPref, setWater] = React.useState(() => sp.get("water") ?? "境川（１）");
  const [grainPref, setGrainPref] = React.useState<"year" | "month">(() => (sp.get("grain") === "month" ? "month" : "year"));
  const [basisPref, setBasisPref] = React.useState<Basis>(() => {
    const b = sp.get("basis");
    return b === "fiscal_year" || b === "year" ? b : "day";
  });
  const [statPref, setStatPref] = React.useState(() => sp.get("stat") ?? "representative");
  const [hidden, setHidden] = React.useState<Set<string>>(new Set());

  const v = vars.find((x) => x.variableId === variableId);
  const availableBases = availableBasesOf(v);
  // 項目によっては検体値・年度集計値・暦年値のうち1つしか無い。状態を書き換えずに、
  // 描画時に「実際に使える方」へ寄せる（v1 の kind 自動補正と同じ考え方）。
  const basis: Basis = availableBases.includes(basisPref) ? basisPref : (availableBases[0] ?? "day");
  const grain: Grain = basis === "day" ? grainPref : basis;
  const statOptions = v?.stats ?? [];
  const stat = statPref !== "representative" && statOptions.includes(statPref) ? statPref : "representative";

  // 選んだ項目のデータを実際に持つ水域だけを選択肢にする。
  // 今の水域にその項目が無ければ、地点数が最も多い水域へ自動で移る。
  const waterOpts = useJson<{ waters: WaterBody[] }>(
    `/api/timeseries?mode=waters&variable=${encodeURIComponent(variableId)}&stat=${stat}`,
  );
  const availableWaters = waterOpts.data?.waters ?? waters;
  // 選んだ項目のデータが今の水域に無ければ、地点数が最も多い水域を既定にする（状態は書き換えない）
  const water =
    availableWaters.length === 0 || availableWaters.some((w) => w.name === waterPref)
      ? waterPref
      : availableWaters[0].name;

  // アシスタントに渡すのは「今実際に描画されている値」。waterPref/basisPref という利用者の希望ではなく、
  // 上の自動補正を経た water/basis を渡す（ここを間違えると、画面に無いものをAIが語ることになる）。
  useSetPageContext({
    route: "/timeseries",
    title: "時系列比較",
    mode,
    variableId,
    water,
    grain: mode === "season" ? "month" : mode === "zone" ? (basis === "fiscal_year" ? "fiscal_year" : "year") : grain,
    basis,
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
          <select className={inputCls + " w-56"} value={variableId} onChange={(e) => setVariableId(e.target.value)}>
            {vars.map((x) => (
              <option key={x.variableId} value={x.variableId}>
                {variableLabel(x.variableId)}（{nf(x.n)}）
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
                  {w.name}（{w.nSites}地点 / {nf(w.nMeas)}件）
                </option>
              ))}
            </select>
          </label>
        )}

        {mode !== "season" && (
          <>
            <div>
              <span className="block text-[10.5px] text-muted mb-1">元データ</span>
              <div className="flex gap-0.5">
                <Btn active={basis === "day"} disabled={!availableBases.includes("day")} onClick={() => setBasisPref("day")}>
                  検体値
                </Btn>
                <Btn active={basis === "fiscal_year"} disabled={!availableBases.includes("fiscal_year")} onClick={() => setBasisPref("fiscal_year")}>
                  年度集計値
                </Btn>
                {availableBases.includes("year") && (
                  <Btn active={basis === "year"} onClick={() => setBasisPref("year")}>
                    暦年値
                  </Btn>
                )}
              </div>
            </div>
            {mode === "water" && basis === "day" && (
              <div>
                <span className="block text-[10.5px] text-muted mb-1">粒度</span>
                <div className="flex gap-0.5">
                  <Btn active={grainPref === "year"} onClick={() => setGrainPref("year")}>
                    年
                  </Btn>
                  <Btn active={grainPref === "month"} onClick={() => setGrainPref("month")}>
                    月
                  </Btn>
                </div>
              </div>
            )}
            {statOptions.length > 0 && (
              <div>
                <span className="block text-[10.5px] text-muted mb-1">統計量</span>
                <select className={inputCls} value={stat} onChange={(e) => setStatPref(e.target.value)}>
                  <option value="representative">代表値（平均）</option>
                  {statOptions.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </>
        )}

        {v && (
          <p className="text-[10.5px] text-muted max-w-md ml-auto leading-snug">
            {VARIABLE_LABEL[variableId]?.note ?? "　"}
            <br />
            {nf(v.n)} 行 / {v.nPlaces} 地点 / {v.yFrom}–{v.yTo}
            {v.nCensored > 0 && `　定量下限未満 ${((v.nCensored / v.n) * 100).toFixed(0)}%`}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll p-4">
        {mode === "water" && (
          <WaterMode
            water={water}
            variableId={variableId}
            grain={grain}
            basis={basis}
            stat={stat}
            unit={v?.unit ?? null}
            hidden={hidden}
            setHidden={setHidden}
          />
        )}
        {mode === "zone" && <ZoneMode variableId={variableId} basis={basis} stat={stat} unit={v?.unit ?? null} />}
        {mode === "season" && <SeasonMode variableId={variableId} stat={stat} unit={v?.unit ?? null} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 水域の中で地点を比べる                                              */
/* ------------------------------------------------------------------ */

/** `lib/cube` の `YearPoint`（`imputation='lod'` で取ったときの緩い受け）。 */
interface YearApiPoint {
  siteId: string | null;
  year: number;
  n: number;
  nCensored: number;
  value: { mean: number | null; min: number | null; max: number | null };
}
/** `lib/cube` の `SeriesPoint`（month/day、緩い受け）。 */
interface SeriesApiPoint {
  siteId: string | null;
  periodStart: string;
  n: number;
  nCensored: number;
  value: number | null;
}

function WaterMode({
  water,
  variableId,
  grain,
  basis,
  stat,
  unit,
  hidden,
  setHidden,
}: {
  water: string;
  variableId: string;
  grain: Grain;
  basis: Basis;
  stat: string;
  unit: string | null;
  hidden: Set<string>;
  setHidden: (s: Set<string>) => void;
}) {
  const qs = `variable=${encodeURIComponent(variableId)}&water=${encodeURIComponent(water)}&basis=${basis}&stat=${stat}`;
  const { data, loading, error } = useJson<{
    sites: Site[];
    points: (YearApiPoint | SeriesApiPoint)[];
    /** 応答が実際に組み立てた grain（Issue #48 PR-2 code-review #6 参照）。 */
    grain: Grain;
  }>(`/api/timeseries?mode=water&${qs}&grain=${grain}`);

  // 季節と経年を1枚で見るためのヒートマップ（水域内の全地点の平均、検体値〔basis=day〕のみ）
  const monthly = useJson<{ points: SeriesApiPoint[] }>(
    basis === "day" ? `/api/timeseries?mode=water&${qs}&grain=month` : "",
  );

  const ordered = React.useMemo(
    () => [...(data?.sites ?? [])].sort((a, b) => (b.elevationM ?? -1) - (a.elevationM ?? -1)),
    [data],
  );

  /**
   * `data.points`（grain によって `YearApiPoint[]`／`SeriesApiPoint[]` と形が違う）を
   * `{siteId, year, x, y, n, nCensored}` の共通形に正規化する。以降の `series`/`profile`
   * はこの1つの配列だけを見ればよく、grain ごとの分岐を1箇所に集約できる。
   *
   * 形の分岐は**応答自身の `data.grain`** で決める（呼び出し元の `grain` prop では
   * 決めない）。読み込み中は前回の応答（前の grain の形）を保持したまま `grain`
   * prop だけ新しい値に切り替わるため、prop で分岐すると「新しい grain の形として
   * 前回の応答を読む」ミスマッチが起きる（Issue #48 PR-2 code-review #6）。
   */
  const normalized = React.useMemo(() => {
    if (!data) return [] as { siteId: string; year: number; x: number; y: number | null; n: number; nCensored: number }[];
    if (data.grain === "year" || data.grain === "fiscal_year") {
      return (data.points as YearApiPoint[]).map((p) => ({
        siteId: String(p.siteId),
        year: p.year,
        x: p.year,
        y: p.value.mean,
        n: p.n,
        nCensored: p.nCensored,
      }));
    }
    return (data.points as SeriesApiPoint[]).map((p) => ({
      siteId: String(p.siteId),
      year: Number(p.periodStart.slice(0, 4)),
      x: data.grain === "month" ? ymToX(p.periodStart.slice(0, 7)) : Date.parse(p.periodStart),
      y: p.value,
      n: p.n,
      nCensored: p.nCensored,
    }));
  }, [data]);

  /** この項目のデータを実際に持つ地点だけを、標高順に並べたもの */
  const withData = React.useMemo(() => {
    const ids = new Set(normalized.map((p) => p.siteId));
    return ordered.filter((s) => ids.has(s.siteId));
  }, [ordered, normalized]);
  // 色は「地点という実体」に固定する。表示のオン/オフでは塗り替えない。
  const colorOf = React.useCallback(
    (id: string) => {
      const i = withData.findIndex((s) => s.siteId === id);
      return i >= 0 && i < SERIES.length ? SERIES[i] : INK.muted;
    },
    [withData],
  );

  const series: LineSeries[] = React.useMemo(() => {
    const bySite = new Map<string, { x: number; y: number; n: number; censored: boolean }[]>();
    for (const p of normalized) {
      if (p.y === null || !Number.isFinite(p.x)) continue;
      if (!bySite.has(p.siteId)) bySite.set(p.siteId, []);
      bySite.get(p.siteId)!.push({ x: p.x, y: p.y, n: p.n, censored: p.nCensored > 0 && p.nCensored === p.n });
    }
    return withData
      .filter((s) => bySite.has(s.siteId) && !hidden.has(s.siteId))
      .slice(0, 8)
      .map((s) => ({
        key: s.siteId,
        label: `${s.name}${s.elevationM != null ? ` ${Math.round(s.elevationM)}m` : ""}`,
        color: colorOf(s.siteId),
        points: bySite.get(s.siteId)!,
      }));
  }, [normalized, withData, hidden, colorOf]);

  // 縦断プロファイル（最新年）
  const profile = React.useMemo(() => {
    if (!normalized.length) return { year: null as number | null, rows: [] as { key: string; label: string; value: number; color: string }[] };
    const latest = Math.max(...normalized.map((p) => p.year));
    const agg = new Map<string, { sum: number; n: number }>();
    for (const p of normalized) {
      if (p.year !== latest || p.y === null) continue;
      const a = agg.get(p.siteId) ?? { sum: 0, n: 0 };
      a.sum += p.y * (p.n || 1);
      a.n += p.n || 1;
      agg.set(p.siteId, a);
    }
    return {
      year: latest,
      rows: withData
        .filter((s) => agg.has(s.siteId))
        .map((s) => ({
          key: s.siteId,
          label: `${s.name}（${s.elevationM != null ? Math.round(s.elevationM) + "m" : "標高不明"}）`,
          value: agg.get(s.siteId)!.sum / agg.get(s.siteId)!.n,
          color: colorOf(s.siteId),
        })),
    };
  }, [normalized, withData, colorOf]);

  const heat = React.useMemo(() => {
    const pts = monthly.data?.points ?? [];
    if (!pts.length) return { cells: [] as { x: number; y: number; v: number; n: number }[], years: [] as number[] };
    const agg = new Map<string, { sum: number; n: number }>();
    for (const p of pts) {
      if (typeof p.value !== "number") continue;
      const year = Number(p.periodStart.slice(0, 4));
      const month = Number(p.periodStart.slice(5, 7));
      const k = `${year}|${month}`;
      const a = agg.get(k) ?? { sum: 0, n: 0 };
      a.sum += p.value * p.n;
      a.n += p.n;
      agg.set(k, a);
    }
    const years = [...new Set(pts.map((p) => Number(p.periodStart.slice(0, 4))))].sort((a, b) => a - b);
    return {
      years,
      cells: [...agg.entries()].map(([k, a]) => {
        const [y, m] = k.split("|").map(Number);
        return { x: y, y: m, v: a.sum / a.n, n: a.n };
      }),
    };
  }, [monthly.data]);

  const worse = VARIABLE_LABEL[variableId]?.higherIsWorse;

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
      <div className="xl:col-span-2 space-y-4">
        <ChartFrame
          title={`${water} の ${variableLabel(variableId)}｜地点別${grain === "month" ? "月平均" : "年平均"}`}
          subtitle={`線の色は地点。標高の高い順に色を固定してあるので、上から下へ川を下る並びになる。${
            worse === true ? "この項目は値が大きいほど汚れている。" : worse === false ? "この項目は値が小さいほど酸素が乏しい。" : ""
          }`}
          legend={series.map((s) => ({ label: s.label, color: s.color }))}
          height={320}
          table={
            <MiniTable
              columns={["地点", grain === "month" ? "年月" : "年", `平均${unit ? `（${unit}）` : ""}`, "n"]}
              rows={series.flatMap((s) =>
                s.points.map((p) => [
                  s.label,
                  grain === "month" ? xToYm(p.x) : String(p.x),
                  p.y as number,
                  p.n ?? null,
                ]),
              )}
            />
          }
          note={
            <>
              {caveatBody("duplicates")} {caveatBody("censoredLod")}
              {basis === "fiscal_year" && ` ${caveatBody("measuredOn")}`}
            </>
          }
        >
          <LineChart
            series={series}
            height={320}
            unit={unit}
            xFormat={(x) => (grain === "month" ? xToYm(x) : String(Math.round(x)))}
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
        {basis === "day" && (
        <ChartFrame
          title={`年 × 月のヒートマップ（${water} の全地点平均）`}
          subtitle="縦が月、横が年。季節の型が年をまたいで安定しているか、ある年だけ崩れているかを一枚で見る"
          table={
            <MiniTable
              columns={["年", "月", `平均${unit ? `（${unit}）` : ""}`, "n"]}
              rows={heat.cells.map((c) => [c.x, c.y, c.v, c.n])}
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
        {basis !== "day" && (
          <p className="text-[11.5px] text-muted card p-3 leading-relaxed">
            {basisLabel(basis)}には月の情報がないため、年 × 月のヒートマップは出せない。
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
              const off = hidden.has(s.siteId);
              const over = i >= 8;
              return (
                <li key={s.siteId}>
                  <button
                    onClick={() => {
                      const next = new Set(hidden);
                      if (off) next.delete(s.siteId);
                      else next.add(s.siteId);
                      setHidden(next);
                    }}
                    className={`w-full text-left flex items-center gap-2 px-1.5 py-1 rounded hover:bg-surface-2 ${
                      off ? "opacity-40" : ""
                    }`}
                    disabled={over}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0 border"
                      style={{ background: over ? "transparent" : colorOf(s.siteId), borderColor: INK.axis }}
                    />
                    <span className="text-[12px] truncate">{s.name}</span>
                    <span className="ml-auto text-[10.5px] text-muted tnum shrink-0">
                      {s.elevationM != null ? `${Math.round(s.elevationM)}m` : "–"}
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

function ZoneMode({ variableId, basis, stat, unit }: { variableId: string; basis: Basis; stat: string; unit: string | null }) {
  const { data, loading, error } = useJson<{
    points: { zone: number; year: number; nSites: number; n: number; avg: number | null }[];
  }>(`/api/timeseries?mode=zone&variable=${encodeURIComponent(variableId)}&basis=${basis}&stat=${stat}`);

  const series: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const byZone = new Map<number, { x: number; y: number; n: number }[]>();
    for (const p of data.points) {
      if (p.zone == null || typeof p.avg !== "number") continue;
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
        .filter((p) => p.year === y && p.zone != null && typeof p.avg === "number")
        .sort((a, b) => a.zone - b.zone)
        .map((p) => ({
          key: "z" + p.zone,
          label: `${p.zone}. ${ZONE_LABELS[p.zone]}（${p.nSites}地点）`,
          value: p.avg as number,
          color: ZONE_COLORS[p.zone],
        })),
    };
  }, [data]);

  if (loading && !data) return <Spinner label="読み込み中" />;
  if (error) return <p className="text-bad text-sm">{error}</p>;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <ChartFrame
        title={`ゾーン別の${basis === "fiscal_year" ? "年度" : "年"}平均｜${variableLabel(variableId)}`}
        subtitle="尾根（1）から海（5）までの区分ごとに、その年の平均を並べたもの"
        legend={series.map((s) => ({ label: s.label, color: s.color }))}
        height={300}
        table={
          <MiniTable
            columns={["ゾーン", "年", `平均${unit ? `（${unit}）` : ""}`, "地点数"]}
            rows={(data?.points ?? []).map((p) => [`${p.zone}. ${ZONE_LABELS[p.zone]}`, p.year, p.avg, p.nSites])}
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

function SeasonMode({ variableId, stat, unit }: { variableId: string; stat: string; unit: string | null }) {
  const { data, loading, error } = useJson<{
    overall: { month: number; n: number; avg: number | null; min: number | null; max: number | null }[];
    byZone: { zone: number; month: number; n: number; avg: number | null }[];
    rain: { month: number; n: number; avg: number | null }[];
  }>(`/api/timeseries?mode=season&variable=${encodeURIComponent(variableId)}&stat=${stat}`);

  const zoneSeries: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    const byZone = new Map<number, { x: number; y: number; n: number }[]>();
    for (const p of data.byZone) {
      if (p.zone == null || typeof p.avg !== "number") continue;
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
        title={`月ごとの平均｜${variableLabel(variableId)}（全期間・全地点）`}
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
        note={`相模原市 大気汚染常時監視 1時間値の RAIN。${caveatBody("unitUnknown")}観測点の緯度経度が公開されていないため地図には出せない。`}
      >
        <ColumnChart
          data={rain.map((r) => ({ x: r.month, value: r.avg ?? 0 }))}
          height={110}
          xFormat={(x) => `${Math.round(x)}月`}
          unit={null}
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
