import { DocumentsExplorer } from "@/components/documents/DocumentsExplorer";

export const dynamic = "force-dynamic";
export const metadata = { title: "文書と統計" };

export default function Page() {
  return <DocumentsExplorer />;
}
