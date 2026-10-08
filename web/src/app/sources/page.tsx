import { d1CubeDb } from "@/lib/cube";
import { documentsList } from "@/lib/records";
import { sourcePageRows } from "@/lib/source-catalog";
import { SourceRegistry } from "@/components/sources/SourceRegistry";

export const dynamic = "force-dynamic";
export const metadata = { title: "出典" };

export default async function Page() {
  const docs = await documentsList(await d1CubeDb());
  // 出典の正は registry（describe_catalog what='sources' と同じ行）。旧表 source_registry は読まない。
  const sources = sourcePageRows(new Date());
  return <SourceRegistry sources={sources} docs={docs} />;
}
