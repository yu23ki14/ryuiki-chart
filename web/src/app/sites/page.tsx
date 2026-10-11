import { d1CubeDb, sites, MEASUREMENTS_DATASET as DATASET } from "@/lib/cube";
import { parseRegion, regionOf } from "@/lib/region";
import { SiteList } from "@/components/sites/SiteList";

export const dynamic = "force-dynamic";
export const metadata = { title: "地点カルテ" };

export default async function Page({ searchParams }: { searchParams: Promise<{ region?: string | string[] }> }) {
  const region = regionOf(parseRegion((await searchParams).region));
  const db = await d1CubeDb();
  const rows = await sites(db, { dataset: DATASET, ...(region ? { region } : {}) });
  return <SiteList sites={rows} />;
}
