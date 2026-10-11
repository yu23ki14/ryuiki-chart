"use client";

import { LineChart } from "@/components/viz/LineChart";
import { ChartFrame, MiniTable } from "@/components/viz/ChartFrame";
import { SERIES } from "@/components/viz/palette";

const DAY_MS = 86_400_000;
const dayNo = (date: string) => Date.parse(`${date}T00:00:00Z`) / DAY_MS;
const dayLabel = (x: number) => {
  const d = new Date(x * DAY_MS);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
};

/** 名瀬の日雨量（合計）。豪雨期間を帯で示す。 */
export function RainChart({
  days,
  unit,
  band,
}: {
  days: { date: string; mm: number }[];
  unit: string | null;
  band: { from: string; to: string };
}) {
  return (
    <ChartFrame
      title="名瀬の日降水量（気象庁）"
      subtitle={unit ? `日合計。単位: ${unit}。帯は豪雨の期間` : "日合計。帯は豪雨の期間"}
      table={<MiniTable columns={["日付", `日降水量${unit ? `（${unit}）` : ""}`]} rows={days.map((d) => [d.date, d.mm])} />}
    >
      <LineChart
        series={[{ key: "rain", label: "名瀬", color: SERIES[0], points: days.map((d) => ({ x: dayNo(d.date), y: d.mm })) }]}
        height={240}
        unit={unit}
        xFormat={dayLabel}
        yZero
        bands={[{ x0: dayNo(band.from), x1: dayNo(band.to), label: "豪雨の期間" }]}
      />
    </ChartFrame>
  );
}
