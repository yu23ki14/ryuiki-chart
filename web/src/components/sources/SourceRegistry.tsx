"use client";

import * as React from "react";
import { Btn, inputCls, Stat, nf } from "@/components/ui";
import { STATUS } from "@/components/viz/palette";
import type { DocumentRow } from "@/lib/records";
import type { SourcePageRow } from "@/lib/source-catalog";

type Source = SourcePageRow;
type Doc = DocumentRow;

/** 出典の license_class（registry）から、バッジに出す短いラベルと色調を決める。ライセンス文の自由記述は読まない。 */
const LICENSE_BADGE: Record<string, { label: string; tone: "open" | "gov" | "share" | "check" }> = {
  public_domain: { label: "パブリックドメイン", tone: "open" },
  cc_by: { label: "CC BY", tone: "open" },
  open_terms: { label: "公開利用規約", tone: "gov" },
  share_alike: { label: "継承条件あり", tone: "share" },
  noncommercial: { label: "非商用", tone: "share" },
  mixed: { label: "混在", tone: "check" },
  custom_terms: { label: "個別条件", tone: "check" },
  restricted: { label: "制限あり", tone: "check" },
  unconfirmed: { label: "要確認", tone: "check" },
  unknown: { label: "不明", tone: "check" },
};
function licenseBadge(licenseClass: string | null): { label: string; tone: "open" | "gov" | "share" | "check" } {
  return (licenseClass && LICENSE_BADGE[licenseClass]) || { label: "不明", tone: "check" };
}

const TONE: Record<string, string> = {
  open: "#0ca30c",
  gov: "#2a78d6",
  share: "#eda100",
  check: "#d03b3b",
};

export function SourceRegistry({ sources, docs }: { sources: Source[]; docs: Doc[] }) {
  const [q, setQ] = React.useState("");
  const [only, setOnly] = React.useState<"all" | "used" | "redist" | "check">("used");
  const [tab, setTab] = React.useState<"sources" | "docs">("sources");

  const rows = React.useMemo(() => {
    const needle = q.trim();
    return sources.filter((s) => {
      if (only === "used" && s.queryable_via.length === 0) return false;
      if (only === "redist" && s.redistributable !== true) return false;
      if (only === "check" && s.redistributable === true) return false;
      if (needle && !`${s.name} ${s.publisher} ${s.source_id} ${s.license}`.includes(needle)) return false;
      return true;
    });
  }, [sources, q, only]);

  const readable = sources.filter((s) => s.queryable_via.length > 0).length;
  const redist = sources.filter((s) => s.redistributable === true).length;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="no-print border-b border-line bg-surface px-4 py-2.5">
        <h1 className="text-[15px] font-bold">出典とライセンス</h1>
        <p className="text-[11px] text-muted mt-0.5 max-w-3xl leading-snug">
          この画面に出ている数字は、すべて公開データに由来する。取得元・取得日・ライセンス・再配布可否を1件ずつ記録してあり、
          再配布できないものは数値を再掲せずリンクだけを示す設計にしている。
        </p>
        <div className="flex items-end gap-3 flex-wrap mt-2">
          <div className="flex gap-0.5">
            <Btn active={tab === "sources"} onClick={() => setTab("sources")}>
              データソース（{sources.length}）
            </Btn>
            <Btn active={tab === "docs"} onClick={() => setTab("docs")}>
              抽出元の文書（{docs.length}）
            </Btn>
          </div>
          {tab === "sources" && (
            <>
              <input className={inputCls + " w-56"} placeholder="名称・発行者で探す" value={q} onChange={(e) => setQ(e.target.value)} />
              <div className="flex gap-0.5">
                {(
                  [
                    ["used", "ツールで取れる"],
                    ["redist", "再配布可"],
                    ["check", "要確認"],
                    ["all", "すべて"],
                  ] as [typeof only, string][]
                ).map(([k, label]) => (
                  <Btn key={k} active={only === k} onClick={() => setOnly(k)}>
                    {label}
                  </Btn>
                ))}
              </div>
            </>
          )}
          <div className="ml-auto flex gap-6">
            <Stat label="登録ソース" value={nf(sources.length)} unit="件" />
            <Stat label="再配布可" value={nf(redist)} unit="件" note={`要確認 ${sources.length - redist} 件`} />
            <Stat label="ツールで取れる" value={nf(readable)} unit="件" />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto thin-scroll">
        {tab === "sources" ? (
          <table className="dtable">
            <thead>
              <tr>
                <th>名称</th>
                <th>発行者</th>
                <th>取得日</th>
                <th>ライセンス</th>
                <th>再配布</th>
                <th>原本の行数</th>
                <th>取り方</th>
                <th>source_id</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => {
                const b = licenseBadge(s.license_class);
                return (
                  <tr key={s.source_id}>
                    <td className="max-w-[420px]">
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-water-ink hover:underline">
                          {s.name ?? s.source_id}
                        </a>
                      ) : (
                        (s.name ?? s.source_id)
                      )}
                    </td>
                    <td className="text-muted">{s.publisher}</td>
                    <td className="text-muted">{s.fetched_at ? s.fetched_at.slice(0, 10) : "–"}</td>
                    <td title={s.license ?? ""}>
                      <span
                        className="text-[10.5px] px-1.5 py-0.5 rounded border"
                        style={{ borderColor: TONE[b.tone], color: TONE[b.tone] }}
                      >
                        {b.label}
                      </span>
                    </td>
                    <td>
                      {s.redistributable === true ? (
                        <span className="text-[11px] text-ok">可</span>
                      ) : (
                        <span className="text-[11px]" style={{ color: STATUS.critical }}>
                          要確認
                        </span>
                      )}
                    </td>
                    <td className="num">{s.n_source_rows == null ? "–" : nf(s.n_source_rows)}</td>
                    <td className="text-muted" title={s.unavailable_reason_ja ?? ""}>
                      {s.queryable_via.length > 0 ? s.queryable_via.join("・") : "取れない"}
                    </td>
                    <td className="font-mono text-[10.5px] text-muted">{s.source_id}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <table className="dtable">
            <thead>
              <tr>
                <th>文書</th>
                <th>発行者</th>
                <th>年度</th>
                <th>ページ</th>
                <th>抽出セル</th>
                <th>注記</th>
                <th>比較注意</th>
                <th>ライセンス</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.doc_id}>
                  <td className="max-w-[460px]">
                    <a href={d.url ?? undefined} target="_blank" rel="noopener noreferrer" className="text-water-ink hover:underline">
                      {d.title}
                    </a>
                  </td>
                  <td className="text-muted">{d.publisher}</td>
                  <td className="num">{d.fiscal_year ?? "–"}</td>
                  <td className="num">{d.n_pages}</td>
                  <td className="num">{nf(d.n_cells)}</td>
                  <td className="num">{d.n_notes}</td>
                  <td className="num">
                    {d.n_blocking > 0 ? (
                      <span className="text-[10.5px] px-1.5 py-0.5 rounded text-white" style={{ background: STATUS.serious }}>
                        {d.n_blocking}
                      </span>
                    ) : (
                      <span className="text-muted">–</span>
                    )}
                  </td>
                  <td className="text-muted">{d.license}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="no-print border-t border-line bg-surface px-4 py-2 text-[10.5px] text-muted leading-relaxed">
        再配布可否は収集時に人が判断して記録したもので、法的な保証ではない。実際の再利用にあたっては各発行者の規約を確認すること。
        「かながわの水がめ」（無断複製・転用不可）のように数値を再掲できないソースは、この画面のどのグラフにも使っていない。
      </div>
    </div>
  );
}
