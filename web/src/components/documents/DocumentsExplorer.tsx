"use client";

import * as React from "react";
import { LineChart, type LineSeries } from "@/components/viz/LineChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES, STATUS } from "@/components/viz/palette";
import { inputCls, Spinner, Stat, nf, Provenance } from "@/components/ui";
import { useJson } from "@/components/useJson";

/**
 * 行政文書から抽出した表の行キーは、表によって行見出しと列見出しが連結されている
 * （例: `湘南地域秦野市伊勢原市|清川村`）。信頼できるのは最後の `|` の後ろだけなので、
 * 表示名にはそこを使う。原文の行キーは別途そのまま見せる。
 *
 * この画面（DocumentsExplorer）だけが使う整形なので、レジストリの語彙ではなくここに置く
 * （旧 domain.ts の rowKeyLabel。docs/plans/PHASE_B_INTAKE.md #6）。
 */
function rowKeyLabel(rowKey: string): string {
  if (!rowKey) return "";
  const i = rowKey.lastIndexOf("|");
  const tail = i >= 0 ? rowKey.slice(i + 1) : rowKey;
  return tail.trim() || rowKey;
}

interface SeriesMeta {
  doc_id: string;
  table_id: string;
  row_key: string;
  label: string;
  page_no: number;
  n_years: number;
  y_from: number;
  y_to: number;
  unit: string | null;
  doc_title: string;
  publisher: string;
  url: string;
  license: string;
  n_warnings: number;
}
interface Warning {
  doc_id: string;
  doc_title: string;
  kind: string;
  page: number;
  reason: string;
  text: string;
}
interface Doc {
  doc_id: string;
  title: string;
  publisher: string;
  url: string;
  n_pages: number;
  fiscal_year: number | null;
  license: string;
  n_cells: number;
  n_notes: number;
  n_blocking: number;
}

const KIND_LABEL: Record<string, string> = {
  definition_change: "区分・定義の変更",
  comparability: "接続できない・遡及改定",
  survey_scope: "調査範囲・体制の変動",
  footnote: "注記・表記のゆれ",
  "": "その他",
};

export function DocumentsExplorer() {
  const { data, loading, error } = useJson<{ series: SeriesMeta[]; docs: Doc[]; warnings: Warning[] }>(
    "/api/documents?kind=list",
  );
  const [picked, setPicked] = React.useState<SeriesMeta | null>(null);
  const [q, setQ] = React.useState("");
  const [minYears, setMinYears] = React.useState(4);

  // 未選択のときの既定値は、状態に書き込まず描画時に決める
  const sel =
    picked ??
    data?.series.find((s) => s.doc_id === "ghg_kennai_suikei_2023" && s.row_key.includes("合")) ??
    data?.series[0] ??
    null;
  const setSel = setPicked;

  const rows = React.useMemo(() => {
    const needle = q.trim();
    return (data?.series ?? [])
      .filter((s) => s.n_years >= minYears)
      .filter((s) => !needle || `${rowKeyLabel(s.row_key)} ${s.doc_title} ${s.publisher}`.includes(needle));
  }, [data, q, minYears]);

  return (
    <div className="flex-1 flex min-h-0">
      <aside className="w-[340px] shrink-0 border-r border-line bg-surface flex flex-col min-h-0 no-print">
        <div className="p-3 border-b border-line">
          <h1 className="text-[14px] font-bold">文書と統計</h1>
          <p className="text-[11px] text-muted mt-0.5 leading-snug">
            行政のPDFから抜き出した表のセル（119,533件）を、指標の系列として並べ直したもの。
            各点がどのPDFの何ページに由来するかを持っている。
          </p>
        </div>
        <div className="p-2 border-b border-line flex items-center gap-1.5">
          <input className={inputCls} placeholder="指標名・文書名で探す" value={q} onChange={(e) => setQ(e.target.value)} />
          <select
            className={inputCls + " w-auto"}
            value={minYears}
            onChange={(e) => setMinYears(Number(e.target.value))}
          >
            {[3, 4, 5, 8, 10].map((n) => (
              <option key={n} value={n}>
                {n}年+
              </option>
            ))}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto thin-scroll">
          {loading && (
            <div className="p-4">
              <Spinner label="読み込み中" />
            </div>
          )}
          {error && <p className="p-4 text-bad text-[12px]">{error}</p>}
          {rows.map((s) => {
            const active = sel?.doc_id === s.doc_id && sel?.table_id === s.table_id && sel?.row_key === s.row_key;
            return (
              <button
                key={`${s.doc_id}|${s.table_id}|${s.row_key}`}
                onClick={() => setSel(s)}
                className={`w-full text-left px-3 py-1.5 border-b border-line hover:bg-surface-2 ${
                  active ? "bg-water-soft" : ""
                }`}
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-[12px] font-medium truncate">{rowKeyLabel(s.row_key)}</span>
                  <span className="ml-auto text-[10px] text-muted tnum shrink-0">
                    {s.y_from}–{s.y_to}
                  </span>
                </div>
                <div className="text-[10px] text-muted truncate">{s.doc_title}</div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[9.5px] px-1 rounded bg-surface-2 tnum">{s.n_years}年分</span>
                  {s.unit && <span className="text-[9.5px] px-1 rounded bg-surface-2">{s.unit}</span>}
                  {s.n_warnings > 0 && (
                    <span
                      className="text-[9.5px] px-1 rounded text-white"
                      style={{ background: STATUS.serious }}
                      title="この文書には、単純な経年比較を妨げる注記がある"
                    >
                      ⚠ 比較注意 {s.n_warnings}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
          {!loading && rows.length === 0 && <p className="p-4 text-[12px] text-muted">該当する系列がありません。</p>}
        </div>
        <div className="p-2 border-t border-line text-[10px] text-muted tnum">
          {nf(rows.length)} 系列 / 全 {nf(data?.series.length ?? 0)} 系列（3年以上）
        </div>
      </aside>

      <div className="flex-1 overflow-y-auto thin-scroll p-4 min-w-0">
        {sel ? <SeriesView meta={sel} warnings={data?.warnings ?? []} /> : <p className="text-muted text-sm">左から指標を選んでください。</p>}
        <WarningSummary warnings={data?.warnings ?? []} docs={data?.docs ?? []} />
      </div>
    </div>
  );
}

function SeriesView({ meta, warnings }: { meta: SeriesMeta; warnings: Warning[] }) {
  const { data, loading } = useJson<{
    points: { fiscal_year: number; value: number; unit: string | null; page_no: number }[];
    notes: { note_id: string; kind: string; text: string; page: number; blocks_timeseries: number; reason: string }[];
  }>(
    `/api/documents?kind=series&doc=${encodeURIComponent(meta.doc_id)}&table=${encodeURIComponent(meta.table_id)}&row=${encodeURIComponent(meta.row_key)}`,
  );

  const series: LineSeries[] = React.useMemo(() => {
    if (!data) return [];
    return [
      {
        key: meta.row_key,
        label: rowKeyLabel(meta.row_key),
        color: SERIES[0],
        points: data.points.map((p) => ({ x: p.fiscal_year, y: p.value })),
      },
    ];
  }, [data, meta]);

  const blocking = (data?.notes ?? []).filter((n) => n.blocks_timeseries === 1);
  const docWarnings = warnings.filter((w) => w.doc_id === meta.doc_id);

  const first = data?.points[0];
  const last = data?.points.at(-1);
  const change = first && last && first.value !== 0 ? ((last.value - first.value) / Math.abs(first.value)) * 100 : null;

  return (
    <div className="space-y-4 mb-6">
      <div className="card p-3.5">
        <h2 className="text-[16px] font-bold">{rowKeyLabel(meta.row_key)}</h2>
        <p className="text-[11.5px] text-ink-2 mt-0.5">
          {meta.doc_title}（{meta.publisher}）— p.{meta.page_no}
        </p>
        <div className="flex gap-6 mt-2.5 flex-wrap">
          <Stat label="収録年度" value={`${meta.y_from}–${meta.y_to}`} note={`${meta.n_years} 年分`} />
          <Stat label={`最初の値（${first?.fiscal_year ?? "–"}）`} value={first ? first.value.toLocaleString("ja-JP") : "–"} unit={meta.unit ?? undefined} />
          <Stat label={`最後の値（${last?.fiscal_year ?? "–"}）`} value={last ? last.value.toLocaleString("ja-JP") : "–"} unit={meta.unit ?? undefined} />
          <Stat
            label="変化"
            value={change == null ? "–" : `${change > 0 ? "+" : ""}${change.toFixed(1)}`}
            unit="%"
            tone={change == null ? "default" : Math.abs(change) > 20 ? "warn" : "default"}
            note="最初と最後の比。途中の増減は図で確認すること"
          />
        </div>
      </div>

      {blocking.length > 0 && (
        <div className="card border-l-4" style={{ borderLeftColor: STATUS.serious }}>
          <div className="px-3.5 py-2 border-b border-line flex items-center gap-2">
            <span className="text-[13px] font-semibold">この数字を年で並べる前に読むこと</span>
            <span className="text-[10.5px] text-muted">{blocking.length} 件の注記</span>
          </div>
          <ul className="divide-y divide-line">
            {blocking.map((n) => (
              <li key={n.note_id} className="px-3.5 py-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-2 text-ink-2">
                    {KIND_LABEL[n.kind] ?? n.kind}
                  </span>
                  <span className="text-[10px] text-muted">p.{n.page}</span>
                </div>
                <p className="text-[12px] mt-1 leading-relaxed">{n.reason}</p>
                {n.text && (
                  <p className="text-[11px] text-muted mt-1 leading-relaxed border-l-2 border-line pl-2">{n.text}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ChartFrame
        title={`年度別の推移${meta.unit ? `（${meta.unit}）` : ""}`}
        subtitle="各点は、上の文書の該当ページの表のセルそのもの。値を作り直していない"
        height={300}
        table={
          <MiniTable
            columns={["年度", `値${meta.unit ? `（${meta.unit}）` : ""}`, "出典ページ"]}
            rows={(data?.points ?? []).map((p) => [p.fiscal_year, p.value, `p.${p.page_no}`])}
          />
        }
        note={
          docWarnings.length > 0
            ? "この文書には比較上の注記がある。上の枠を必ず読むこと。"
            : "この文書には、経年比較を妨げる注記は付いていない。"
        }
      >
        {loading && !data ? (
          <div className="p-8 text-center">
            <Spinner label="読み込み中" />
          </div>
        ) : (
          <LineChart series={series} height={300} unit={meta.unit} xFormat={(x) => `${Math.round(x)}`} yZero directLabels={false} />
        )}
      </ChartFrame>

      <div className="card p-3">
        <Provenance>
          {meta.doc_title}（{meta.publisher}）。ライセンス: {meta.license}。
          <a href={meta.url} target="_blank" rel="noopener noreferrer" className="text-water underline ml-1">
            元PDF
          </a>
          。表ID <code className="font-mono">{meta.table_id}</code> / 行キー{" "}
          <code className="font-mono break-all">{meta.row_key}</code>
          （行キーは表によって行見出しと列見出しが連結されていることがあるため、表示名は末尾のトークンを使っている）。
        </Provenance>
      </div>
    </div>
  );
}

function WarningSummary({ warnings, docs }: { warnings: Warning[]; docs: Doc[] }) {
  const [open, setOpen] = React.useState(false);
  const byKind = React.useMemo(() => {
    const m = new Map<string, Warning[]>();
    for (const w of warnings) {
      const k = w.kind || "";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(w);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [warnings]);

  return (
    <div className="card">
      <button
        className="w-full px-3.5 py-2.5 flex items-center gap-2 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="text-[13px] font-semibold">単純な経年比較を妨げる注記の一覧</span>
        <span className="text-[11px] text-muted">
          {nf(warnings.length)} 件 / {nf(new Set(warnings.map((w) => w.doc_id)).size)} 文書
        </span>
        <span className="ml-auto text-[11px] text-water">{open ? "閉じる" : "開く"}</span>
      </button>
      {open && (
        <div className="border-t border-line">
          <p className="px-3.5 py-2 text-[11.5px] text-ink-2 leading-relaxed">
            行政の統計は、区分の定義や調査体制が途中で変わる。ここに挙げるのは、
            数字を年で並べる前に読まないと誤読する注記で、抽出時に人が原文から書き起こしたもの。
            グラフの横に置くことが、このデモの目的のひとつ。
          </p>
          {byKind.map(([kind, ws]) => (
            <details key={kind} className="border-t border-line">
              <summary className="px-3.5 py-2 cursor-pointer text-[12px] font-medium">
                {KIND_LABEL[kind] ?? kind}
                <span className="ml-2 text-[11px] text-muted tnum">{ws.length} 件</span>
              </summary>
              <ul className="divide-y divide-line bg-surface-2">
                {ws.map((w, i) => (
                  <li key={i} className="px-3.5 py-2">
                    <div className="text-[10.5px] text-muted">
                      {w.doc_title} p.{w.page}
                    </div>
                    <p className="text-[12px] mt-0.5 leading-relaxed">{w.reason}</p>
                  </li>
                ))}
              </ul>
            </details>
          ))}
          <div className="px-3.5 py-2 border-t border-line text-[10.5px] text-muted">
            抽出元の文書は {nf(docs.length)} 件（うちセルが1行以上あるのは {nf(docs.filter((d) => d.n_cells > 0).length)} 件）。
          </div>
        </div>
      )}
    </div>
  );
}
