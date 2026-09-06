import { notFound } from "next/navigation";
import { getSite, siteVariables } from "@/lib/queries";
import { SiteDetail } from "@/components/sites/SiteDetail";

export const dynamic = "force-dynamic";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = await getSite(decodeURIComponent(id));
  return { title: s?.name ?? "地点カルテ" };
}

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const siteId = decodeURIComponent(id);
  const [site, variables] = await Promise.all([getSite(siteId), siteVariables(siteId)]);
  if (!site) notFound();
  return <SiteDetail site={site} variables={variables} />;
}
