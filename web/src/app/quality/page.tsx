import { QualityDashboard } from "@/components/quality/QualityDashboard";

export const dynamic = "force-dynamic";
export const metadata = { title: "品質と進捗" };

export default function Page() {
  return <QualityDashboard />;
}
