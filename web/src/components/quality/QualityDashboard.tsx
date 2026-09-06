"use client";

import * as React from "react";
import { StackedArea, type StackSeries } from "@/components/viz/StackedArea";
import { BarChart } from "@/components/viz/BarChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, STATUS, QUALITY_STAGE, INK } from "@/components/viz/palette";
import { Btn, Stat, Spinner, nf, Provenance } from "@/components/ui";
import { useJson } from "@/components/useJson";
import { DATA_CAVEATS } from "@/lib/domain";
import { fmt } from "@/components/viz/scales";

interface Payload {
  monthly: { ym: string; submitted: number; verified: number; published: number; returned: number }[];
  byActor: { actor: string; pass: number; reject: number; publish: number }[];
  totals: { submitted: number; verified: number; published: number; returned: number; targets: number };
  observers: { role: string; org: string; n_people: number; n_events: number }[];
  instruments: {
    instrument_id: string;
    kind: string;
    model: string | null;
    calibrated_on: string | null;
    uncalibrated_flag: number;
  }[];
  pairs: {
    site_id: string;
    site_name: string | null;
    measured_on: string;
    variable: string;
    v1: number;
    v2: number;
    diff: number;
    unit: string | null;
  }[];
  interventions: {
    intervention_id: string;
    kind: string;
    parcel: string;
    quantity: number;
    quantity_unit: string;
    started_on: string;
    finished_on: string;
    operator: string;
    site_name: string | null;
  }[];
  decisions: {
    decision_id: string;
    meeting_name: string;
    meeting_date: string;
    decided: string;
    stalled_item_resolved: number;
    participants: string;
    site_name: string | null;
  }[];
  protocols: { protocol_id: string; name: string; domain: string; steps_json: string; url: string }[];
}

type Tab = "pipeline" | "field" | "governance";

export function QualityDashboard() {
  const { data, loading, error } = useJson<Payload>("/api/quality");
  const [tab, setTab] = React.useState<Tab>("pipeline");

  if (loading && !data)
    return (
      <div className="p-8">
        <Spinner label="読み込み中" />
      </div>
    );
  if (error) return <p className="p-6 text-bad text-sm">{error}</p>;
  if (!data) return null;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="no-print border-b border-line bg-surface px-4 py-2 flex items-center gap-1 flex-wrap">
        <Btn active={tab === "pipeline"} onClick={() => setTab("pipeline")}>
          品質のパイプライン
        </Btn>
        <Btn active={tab === "field"} onClick={() => setTab("field")}>
          現場の体制
        </Btn>
        <Btn active={tab === "governance"} onClick={() => setTab("governance")}>
          介入と意思決定
        </Btn>
        <p className="text-[10.5px] text-muted ml-auto max-w-lg leading-snug">{DATA_CAVEATS.synthetic}</p>
      </div>
      <div className="flex-1 overflow-y-auto thin-scroll p-4">
        {tab === "pipeline" && <PipelineTab data={data} />}
        {tab === "field" && <FieldTab data={data} />}
        {tab === "governance" && <GovernanceTab data={data} />}
      </div>
    </div>
  );
}

/* ------------------------------ 品質 ------------------------------ */

function PipelineTab({ data }: { data: Payload }) {
  const t = data.totals;
  const rejectRate = t.verified + t.returned > 0 ? (t.returned / (t.verified + t.returned)) * 100 : 0;
  const pendings = t.submitted - t.verified - t.returned;

  const months = React.useMemo(() => data.monthly.map((m) => ymToX(m.ym)), [data.monthly]);
  const stacks: StackSeries[] = React.useMemo(() => {
    const mk = (key: keyof Payload["monthly"][number], label: string, color: string) => ({
      key: String(key),
      label,
      color,
      values: new Map(data.monthly.map((m) => [ymToX(m.ym), Number(m[key] ?? 0)])),
    });
    return [
      mk("submitted", "提出（暫定）", QUALITY_STAGE.暫定.color),
      mk("verified", "検証通過", QUALITY_STAGE.検証済.color),
      mk("published", "公開", QUALITY_STAGE.公開済.color),
      mk("returned", "差し戻し", STATUS.critical),
    ];
  }, [data.monthly]);

  const actors = React.useMemo(
    () =>
      data.byActor
        .filter((a) => a.pass + a.reject > 0)
        .map((a) => ({
          key: a.actor,
          label: a.actor,
          value: (a.reject / (a.pass + a.reject)) * 100,
        })),
    [data.byActor],
  );

  return (
    <div className="space-y-4">
      <div className="card p-4 grid grid-cols-2 md:grid-cols-5 gap-4">
        <Stat label="提出（暫定）" value={nf(t.submitted)} unit="件" note="現地測定者による初期提出" />
        <Stat label="専門家の検証を通過" value={nf(t.verified)} unit="件" tone="ok" />
        <Stat label="公開まで到達" value={nf(t.published)} unit="件" tone="ok" />
        <Stat label="差し戻し" value={nf(t.returned)} unit="件" tone="warn" note={`差し戻し率 ${rejectRate.toFixed(1)}%`} />
        <Stat
          label="暫定のまま滞留"
          value={nf(pendings)}
          unit="件"
          tone="warn"
          note="まだ検証に回っていないもの"
        />
      </div>

      <ChartFrame
        title="月ごとの品質パイプライン"
        subtitle="提出 → 専門家の抜き取り検証 → 公開。差し戻しは再測定を促したもの"
        legend={stacks.map((s) => ({ label: s.label, color: s.color }))}
        table={
          <MiniTable
            columns={["年月", "提出", "検証通過", "公開", "差し戻し"]}
            rows={data.monthly.map((m) => [m.ym, m.submitted, m.verified, m.published, m.returned])}
          />
        }
        note="品質段階の遷移履歴があるのは合成データ 2,265 件のみ。実在の環境省データ 313,053 件は最初から「公開済」で固定されており、遷移が記録されていない。"
      >
        {months.length > 0 && (
          <StackedArea series={stacks} xs={months} height={250} xFormat={(x) => xToYm(x)} unit="件" />
        )}
      </ChartFrame>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartFrame
          title="検証者ごとの差し戻し率"
          subtitle="抜き取り検証を担当した研究監修5名。判定の厳しさが人によってどれくらい違うか"
          table={
            <MiniTable
              columns={["検証者", "合格", "差し戻し", "差し戻し率(%)"]}
              rows={data.byActor
                .filter((a) => a.pass + a.reject > 0)
                .map((a) => [a.actor, a.pass, a.reject, (a.reject / (a.pass + a.reject)) * 100])}
            />
          }
          note="差し戻し率が人によって 14.6%〜19.3% と幅がある。判定基準をそろえる運用が要る、という読み方をする指標。"
        >
          <BarChart data={actors} color={SERIES[3]} unit="%" maxLabelWidth={90} valueFormat={(v) => `${v.toFixed(1)}%`} />
        </ChartFrame>

        <div className="card overflow-hidden">
          <div className="px-3.5 py-2.5 border-b border-line">
            <h3 className="text-[13px] font-semibold">ペア測定の食い違い</h3>
            <p className="text-[11px] text-muted mt-0.5">
              同じ地点・同じ日・同じ項目を2人で測った記録。差が大きいものから並べている
            </p>
          </div>
          <div className="max-h-[320px] overflow-auto thin-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>地点</th>
                  <th>日付</th>
                  <th>項目</th>
                  <th>値1</th>
                  <th>値2</th>
                  <th>差</th>
                </tr>
              </thead>
              <tbody>
                {data.pairs.slice(0, 60).map((p, i) => (
                  <tr key={i}>
                    <td>{p.site_name ?? p.site_id}</td>
                    <td className="tnum">{p.measured_on}</td>
                    <td>{p.variable}</td>
                    <td className="num">{fmt(p.v1)}</td>
                    <td className="num">{fmt(p.v2)}</td>
                    <td className="num" style={{ color: Math.abs(p.diff) > 2 ? STATUS.critical : INK.secondary }}>
                      {fmt(p.diff, p.unit)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-3.5 py-2 border-t border-line text-[10.5px] text-muted leading-relaxed">
            差の大きい行（気温で 24℃ の差など）は、入力ミスを模して合成データに埋め込まれたもの。
            実運用では、この表がそのまま「人に確認を求めるキュー」になる。
          </div>
        </div>
      </div>

      <Provenance>
        品質段階の遷移（3,372件）と検証者は合成データ。実在の測定値 313,053 件には遷移履歴が無い。
        測定値そのものの出典は環境省 公共用水域水質測定結果。
      </Provenance>
    </div>
  );
}

/* ------------------------------ 現場 ------------------------------ */

function FieldTab({ data }: { data: Payload }) {
  const byRole = React.useMemo(() => {
    const m = new Map<string, { people: number; events: number }>();
    for (const o of data.observers) {
      const a = m.get(o.role) ?? { people: 0, events: 0 };
      a.people += o.n_people;
      a.events += o.n_events;
      m.set(o.role, a);
    }
    return [...m.entries()];
  }, [data.observers]);

  const uncal = data.instruments.filter((i) => i.uncalibrated_flag === 1);
  const steps = React.useMemo(() => {
    const p = data.protocols.find((x) => x.steps_json && x.steps_json !== "[]");
    if (!p) return null;
    try {
      return { p, steps: JSON.parse(p.steps_json) as { title: string; description: string }[] };
    } catch {
      return null;
    }
  }, [data.protocols]);

  return (
    <div className="space-y-4">
      <div className="card p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        {byRole.map(([role, a]) => (
          <Stat key={role} label={`${role}の測定者`} value={nf(a.people)} unit="名" note={`のべ ${nf(a.events)} 回の参加`} />
        ))}
        <Stat
          label="未校正の機器"
          value={nf(uncal.length)}
          unit={`/ ${data.instruments.length} 台`}
          tone={uncal.length > 0 ? "warn" : "ok"}
          note="校正日の記録が無いもの"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card overflow-hidden">
          <div className="px-3.5 py-2.5 border-b border-line">
            <h3 className="text-[13px] font-semibold">測定者の内訳</h3>
            <p className="text-[11px] text-muted mt-0.5">役割（初級／訓練済／専門）と所属</p>
          </div>
          <table className="dtable">
            <thead>
              <tr>
                <th>役割</th>
                <th>所属</th>
                <th>人数</th>
                <th>参加回数</th>
              </tr>
            </thead>
            <tbody>
              {data.observers.map((o, i) => (
                <tr key={i}>
                  <td>{o.role}</td>
                  <td>{o.org}</td>
                  <td className="num">{o.n_people}</td>
                  <td className="num">{nf(o.n_events)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-3.5 py-2 border-t border-line text-[10.5px] text-muted">
            観測者の情報があるイベントは 29,947 件中 676 件（2.3%）だけ。残りは環境省の公開データで、測定者の記録が無い。
          </div>
        </div>

        <div className="card overflow-hidden">
          <div className="px-3.5 py-2.5 border-b border-line">
            <h3 className="text-[13px] font-semibold">機器と校正</h3>
            <p className="text-[11px] text-muted mt-0.5">未校正の機器のデータには印を付ける、という要件に対応する台帳</p>
          </div>
          <div className="max-h-[340px] overflow-auto thin-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>機器ID</th>
                  <th>種類</th>
                  <th>型式</th>
                  <th>校正日</th>
                  <th>状態</th>
                </tr>
              </thead>
              <tbody>
                {data.instruments.map((i) => (
                  <tr key={i.instrument_id}>
                    <td className="font-mono text-[11px]">{i.instrument_id}</td>
                    <td>{i.kind}</td>
                    <td className="text-muted">{i.model ?? "–"}</td>
                    <td className="tnum">{i.calibrated_on ?? "–"}</td>
                    <td>
                      {i.uncalibrated_flag ? (
                        <span className="text-[10.5px] px-1.5 py-0.5 rounded text-white" style={{ background: STATUS.warning, color: "#3a2a00" }}>
                          ⚠ 未校正
                        </span>
                      ) : (
                        <span className="text-[10.5px] text-ok">校正済</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {steps && (
        <div className="card overflow-hidden">
          <div className="px-3.5 py-2.5 border-b border-line">
            <h3 className="text-[13px] font-semibold">{steps.p.name}</h3>
            <p className="text-[11px] text-muted mt-0.5">
              手順を画面に埋め込むための元データ。原本は {steps.steps.length} ステップの構造化データとして保持されている
            </p>
          </div>
          <ol className="divide-y divide-line">
            {steps.steps.map((s, i) => (
              <li key={i} className="px-3.5 py-2.5 flex gap-3">
                <span className="shrink-0 w-6 h-6 rounded-full bg-water-soft text-water-ink text-[11px] font-bold flex items-center justify-center">
                  {i + 1}
                </span>
                <div>
                  <div className="text-[12.5px] font-medium">{s.title}</div>
                  <p className="text-[11.5px] text-ink-2 mt-0.5 leading-relaxed">{s.description}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="px-3.5 py-2 border-t border-line">
            <Provenance>
              神奈川県 県民参加型 河川モニタリング調査マニュアル（神奈川県環境科学センター）。
              <a href={steps.p.url} target="_blank" rel="noopener noreferrer" className="text-water underline ml-1">
                元PDF
              </a>
            </Provenance>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------ ガバナンス ------------------------------ */

function GovernanceTab({ data }: { data: Payload }) {
  const items = React.useMemo(() => {
    const a = data.interventions.map((i) => ({
      kind: "intervention" as const,
      date: i.started_on,
      end: i.finished_on,
      title: `${i.kind}　${i.parcel}`,
      detail: `${fmt(i.quantity)} ${i.quantity_unit}　実施: ${i.operator}`,
      site: i.site_name,
      resolved: false,
      id: i.intervention_id,
    }));
    const b = data.decisions.map((d) => ({
      kind: "decision" as const,
      date: d.meeting_date,
      end: d.meeting_date,
      title: d.meeting_name,
      detail: d.decided,
      site: d.site_name,
      resolved: d.stalled_item_resolved === 1,
      id: d.decision_id,
    }));
    return [...a, ...b].sort((x, y) => x.date.localeCompare(y.date));
  }, [data]);

  const resolved = data.decisions.filter((d) => d.stalled_item_resolved === 1).length;

  return (
    <div className="space-y-4">
      <div className="card p-4 grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="介入の記録" value={nf(data.interventions.length)} unit="件" note="石積み・復田・駆除" />
        <Stat label="意思決定の記録" value={nf(data.decisions.length)} unit="件" note="寄合・審議会・検討委員会" />
        <Stat
          label="停滞案件が動いた回数"
          value={nf(resolved)}
          unit="件"
          tone="ok"
          note="データを出した結果、止まっていた案件が実行に移った回数"
        />
        <Stat
          label="投入された人日"
          value={nf(data.interventions.filter((i) => i.quantity_unit === "人日").reduce((s, i) => s + i.quantity, 0))}
          unit="人日"
        />
      </div>

      <div className="card overflow-hidden">
        <div className="px-3.5 py-2.5 border-b border-line">
          <h3 className="text-[13px] font-semibold">介入と意思決定のタイムライン</h3>
          <p className="text-[11px] text-muted mt-0.5">
            「測ったものが、いつ・どの場で使われたか」を1本の時間軸に置く。意思決定の記録をデータモデルの一級市民として持つことが、この基盤の考え方
          </p>
        </div>
        <ol className="divide-y divide-line">
          {items.map((it) => (
            <li key={it.id} className="px-3.5 py-2.5 flex gap-3">
              <div className="shrink-0 w-24 text-[11px] text-muted tnum pt-0.5">{it.date}</div>
              <div
                className="shrink-0 w-2.5 h-2.5 rounded-full mt-1"
                style={{ background: it.kind === "intervention" ? STATUS.good : STATUS.warning }}
              />
              <div className="min-w-0">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-[12.5px] font-medium">{it.title}</span>
                  {it.site && <span className="text-[10.5px] text-muted">{it.site}</span>}
                  {it.resolved && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded text-white" style={{ background: STATUS.good }}>
                      停滞案件が動いた
                    </span>
                  )}
                </div>
                <p className="text-[11.5px] text-ink-2 mt-0.5 leading-relaxed">{it.detail}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="px-3.5 py-2 border-t border-line">
          <Provenance>
            介入 20 件・意思決定 14 件はいずれも合成データ（デモ用に生成したもの）。実在の記録ではない。
            紐づく地点と測定値は実在のレコードを指している。
          </Provenance>
        </div>
      </div>
    </div>
  );
}

function ymToX(ym: string): number {
  return Number(ym.slice(0, 4)) + (Number(ym.slice(5, 7)) - 0.5) / 12;
}
function xToYm(x: number): string {
  const y = Math.floor(x);
  const m = Math.min(12, Math.max(1, Math.round((x - y) * 12 + 0.5)));
  return `${y}-${String(m).padStart(2, "0")}`;
}
