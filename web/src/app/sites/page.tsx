import { d1CubeDb, sites, MEASUREMENTS_DATASET as DATASET } from "@/lib/cube";
import { SiteList } from "@/components/sites/SiteList";

export const dynamic = "force-dynamic";
export const metadata = { title: "地点カルテ" };

export default async function Page() {
  const db = await d1CubeDb();
  const rows = await sites(db, { dataset: DATASET });
  return <SiteList sites={rows} />;
}
