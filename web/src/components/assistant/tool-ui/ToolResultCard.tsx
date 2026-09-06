"use client";

import * as React from "react";
import Link from "next/link";
import type { ToolCallMessagePartProps } from "@assistant-ui/react";
import { Spinner } from "@/components/ui";
import { exploreSqlUrl } from "@/lib/ai/links";
import { EXPLORE_ENABLED } from "@/lib/features";
import { ProvenanceFooter, type Provenance } from "./ProvenanceFooter";

/** src/lib/ai/tools.ts の ToolResult<T> と同じ形。JSON で往復するのでここでは緩く受ける。 */
interface ToolResultShape {
  provenance?: Provenance;
  /** 注記はキーだけ流れてくる。本文は caveats.ts の caveatText で引く（往復のトークンを減らすため）。 */
  caveats?: string[];
  truncated?: boolean;
}

export const TOOL_LABEL: Record<string, string> = {
  list_catalog: "一覧を取得",
  get_timeseries: "時系列を取得",
  get_seasonality: "季節性を取得",
  get_sites: "地点を検索",
  get_biota_trend: "生物の推移を取得",
  get_redlist: "レッドリストを取得",
  get_overview: "概況を取得",
  get_quality_progress: "品質進捗を取得",
  describe_schema: "テーブル定義を確認",
  run_sql: "SQLを実行",
};

/**
 * ツール結果の証跡カード。この設計の肝: モデルの出力（文章）には一切頼らず、
 * ToolResult の provenance / caveats を機械的に描く。既定は畳んでおき「根拠を見る」で開く。
 * assistant-ui 側では `MessagePrimitive.Parts` の `tools.Fallback` として、get_timeseries 以外の
 * 全ツール共通で使う（get_timeseries だけは SeriesChartCard がチャート付きで描く）。
 */
export function ToolResultCard(props: ToolCallMessagePartProps) {
  const [open, setOpen] = React.useState(false);
  const { toolName, result, isError, status } = props;
  const label = TOOL_LABEL[toolName] ?? toolName;

  if (status.type === "running" && result === undefined) {
    return (
      <div className="my-1.5 rounded border border-line bg-surface-2 px-2.5 py-1.5">
        <Spinner label={`${label}…`} />
      </div>
    );
  }

  const r = (result ?? {}) as ToolResultShape;
  const provenance = r.provenance;
  const caveats = r.caveats ?? [];
  const hasSynthetic = caveats.includes("synthetic");

  return (
    <div
      className={`my-1.5 rounded border text-[11px] ${
        hasSynthetic ? "border-warn/50 bg-warn/5" : "border-line bg-surface-2"
      }`}
    >
      <ProvenanceFooter
        label={label}
        provenance={provenance}
        caveats={caveats}
        truncated={r.truncated}
        isError={isError}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        link={
          // run_sql のときだけ、実行した SQL をデータ探索画面で開けるようにする。AI に遷移させるのではなく
          // 普通の <Link>。開くだけで実行はしない（実行するかは利用者が画面上で選ぶ）。
          EXPLORE_ENABLED && toolName === "run_sql" && provenance?.sql ? (
            <Link href={exploreSqlUrl(provenance.sql)} className="inline-block text-[10.5px] text-water-ink underline decoration-dotted">
              この SQL をデータ探索で開く →
            </Link>
          ) : undefined
        }
      />
    </div>
  );
}
