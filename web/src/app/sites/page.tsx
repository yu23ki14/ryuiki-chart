import { d1CubeDb, sites } from "@/lib/cube";
import { SiteList } from "@/components/sites/SiteList";

export const dynamic = "force-dynamic";
export const metadata = { title: "地点カルテ" };

/** measurements データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。 */
const DATASET = "measurements";

export default async function Page() {
  const db = await d1CubeDb();
  const rows = await sites(db, { dataset: DATASET });
  return <SiteList sites={rows} />;
}
