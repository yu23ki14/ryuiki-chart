import { listSites } from "@/lib/queries";
import { SiteList } from "@/components/sites/SiteList";

export const dynamic = "force-dynamic";
export const metadata = { title: "地点カルテ" };

export default async function Page() {
  return <SiteList sites={await listSites()} />;
}
