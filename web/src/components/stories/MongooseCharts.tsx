"use client";

import { ColumnChart } from "@/components/viz/BarChart";
import { LineChart } from "@/components/viz/LineChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES } from "@/components/viz/palette";
import type { DocSeriesPoint } from "@/lib/cube/documents";

const yearLabel = (x: number) => `${x}`;

/** 総捕獲頭数（柱）と CPUE（線）。単位が違うので重ねず、2枚に分ける。 */
export function MongooseCharts({ total, cpue }: { total: DocSeriesPoint[]; cpue: DocSeriesPoint[] }) {
  const totalUnit = total[0]?.unit ?? null;
  const cpueUnit = cpue[0]?.unit ?? null;
  const xs = [...total, ...cpue].map((p) => p.fiscalYear);
  const domain: [number, number] = [Math.min(...xs), Math.max(...xs)];
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <ChartFrame
        title="総捕獲頭数（年度）"
        subtitle={totalUnit ? `単位: ${totalUnit}` : undefined}
        table={<MiniTable columns={["年度", `総捕獲頭数${totalUnit ? `（${totalUnit}）` : ""}`]} rows={total.map((p) => [yearLabel(p.fiscalYear), p.value])} />}
      >
        <ColumnChart data={total.map((p) => ({ x: p.fiscalYear, value: p.value }))} height={200} color={SERIES[0]} xFormat={yearLabel} unit={totalUnit} xDomain={domain} />
      </ChartFrame>
      <ChartFrame
        title="わな捕獲の CPUE（年度）"
        subtitle={cpueUnit ? `単位: ${cpueUnit}` : undefined}
        table={<MiniTable columns={["年度", `CPUE${cpueUnit ? `（${cpueUnit}）` : ""}`]} rows={cpue.map((p) => [yearLabel(p.fiscalYear), p.value])} />}
      >
        <LineChart
          series={[{ key: "cpue", label: "CPUE", color: SERIES[1], points: cpue.map((p) => ({ x: p.fiscalYear, y: p.value })) }]}
          height={200}
          unit={cpueUnit}
          xFormat={yearLabel}
          yZero
        />
      </ChartFrame>
    </div>
  );
}
