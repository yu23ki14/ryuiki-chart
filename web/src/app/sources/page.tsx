import { sourceRegistry, documentsList } from "@/lib/queries";
import { SourceRegistry } from "@/components/sources/SourceRegistry";

export const dynamic = "force-dynamic";
export const metadata = { title: "出典" };

export default async function Page() {
  const [sources, docs] = await Promise.all([sourceRegistry(), documentsList()]);
  return <SourceRegistry sources={sources} docs={docs} />;
}
