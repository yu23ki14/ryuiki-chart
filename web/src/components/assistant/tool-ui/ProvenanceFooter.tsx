"use client";

import * as React from "react";
import { caveatText } from "@/lib/ai/caveats";

export interface Provenance {
  tool: string;
  tables: string[];
  sql?: string;
  rowCount: number;
  elapsedMs: number;
}

/**
 * ツール結果の証跡（SQL・参照テーブル・注記）の折りたたみブロック。
 *
 * 元々 ToolResultCard の中に直書きしていたものをここへ切り出した。SeriesChartCard
 * （get_timeseries専用のチャートカード）も同じ証跡表示を必要とするため、2箇所に
 * 同じマークアップを重複させないための共通部品にしてある。見た目はそのまま。
 */
export function ProvenanceFooter({
  label,
  provenance,
  caveats = [],
  truncated,
  isError,
  open,
  onToggle,
  className = "",
  link,
}: {
  label: string;
  provenance?: Provenance;
  caveats?: string[];
  truncated?: boolean;
  isError?: boolean;
  open: boolean;
  onToggle: () => void;
  className?: string;
  /** 「〜で開く」の類のディープリンク。証跡の中、注記の下に置く。AIではなくカード側が機械的に生成したもの。 */
  link?: React.ReactNode;
}) {
  const hasSynthetic = caveats.includes("synthetic");

  return (
    <div className={className}>
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-muted hover:text-ink"
      >
        <span className={`shrink-0 ${isError ? "text-bad" : "text-water-ink"}`}>{isError ? "✕" : "✓"}</span>
        <span className="font-medium whitespace-nowrap">{label}</span>
        {provenance && (
          <span className="tnum text-[10.5px] whitespace-nowrap">
            {provenance.rowCount.toLocaleString("ja-JP")}件 ・ {Math.round(provenance.elapsedMs)}ms
          </span>
        )}
        {hasSynthetic && <span className="text-[10px] text-warn font-medium whitespace-nowrap">合成データ</span>}
        <span className="ml-auto text-[10px] shrink-0">{open ? "根拠を隠す ▲" : "根拠を見る ▼"}</span>
      </button>
      {open && (
        <div className="px-2.5 pb-2 pt-0.5 space-y-2">
          {provenance?.sql && (
            <pre className="text-[10.5px] font-mono whitespace-pre-wrap break-all bg-surface rounded border border-line p-2 overflow-x-auto thin-scroll">
              {provenance.sql}
            </pre>
          )}
          {provenance && (
            <p className="text-[10px] text-muted leading-relaxed">
              参照テーブル: {provenance.tables.length ? provenance.tables.join(", ") : "（なし）"}
              {truncated && <span className="text-warn"> ・応答が大きいため切り詰めました</span>}
            </p>
          )}
          {caveats.length > 0 && (
            <ul className="space-y-1">
              {caveats.map((key) => (
                <li
                  key={key}
                  className={`text-[10.5px] leading-relaxed ${key === "synthetic" ? "text-warn font-medium" : "text-muted"}`}
                >
                  {key === "synthetic" ? "⚠ " : ""}
                  {caveatText(key)}
                </li>
              ))}
            </ul>
          )}
          {isError && <p className="text-[10.5px] text-bad">ツールの実行でエラーが発生しました。</p>}
          {link}
        </div>
      )}
    </div>
  );
}
