/**
 * 地域ごとのレッドリストの版と出典（Issue #93）。`ASSESSMENT_LIST`（registry 生成物）から機械的に引く。
 * server-only を付けない（レッドリスト画面＝クライアントも使う）。
 *
 * 全体（region 未指定）は現状維持で神奈川（jp-14）の版を出す（`cube/assessment.ts` と同じ規則）。
 */
import { REGIONS, type RegionId } from "@/lib/region";
import { ASSESSMENT_LIST } from "@/lib/registry/generated-client";

export const DEFAULT_REDLIST_REGION: RegionId = "jp-14";

export interface RedlistEdition {
  listId: string;
  year: number;
  /** ボタンの表示: 「2022 植物編」（リスト名の最初の全角かっこの中身。「。」以降と CSV は落とす） */
  label: string;
  name: string;
}

function shortLabel(name: string, year: number): string {
  const m = /（([^）]+)）/.exec(name);
  const inner = (m?.[1] ?? "").split("。")[0].replace(/CSV$/, "");
  return inner ? `${year} ${inner}` : String(year);
}

/** その地域のレッドリストの版（古い順）。 */
export function redlistEditions(region: RegionId | undefined): RedlistEdition[] {
  const r = region ?? DEFAULT_REDLIST_REGION;
  return Object.entries(ASSESSMENT_LIST)
    .filter(([, l]) => l.kind === "red_list" && l.region === r)
    .map(([listId, l]) => ({ listId, year: l.year, name: l.name, label: shortLabel(l.name, l.year) }))
    .sort((a, b) => a.year - b.year);
}

/** 既定で開く版の年（`RegionUi.defaultRedlistYear`、無ければ最新）。 */
export function defaultRedlistYear(region: RegionId | undefined): number {
  const r = region ?? DEFAULT_REDLIST_REGION;
  const eds = redlistEditions(r);
  const declared = REGIONS.find((x) => x.id === r)?.defaultRedlistYear;
  if (declared !== undefined && eds.some((e) => e.year === declared)) return declared;
  return eds.at(-1)?.year ?? 0;
}
