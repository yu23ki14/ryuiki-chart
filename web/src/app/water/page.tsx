import { WaterPage } from "@/components/water/WaterPage";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "水源マップ",
  description:
    "神奈川県内の町丁目をタップすると、その場所の水道水がどの川・ダム・地下水から来ているかが出る。",
};

export default function Page() {
  return <WaterPage />;
}
