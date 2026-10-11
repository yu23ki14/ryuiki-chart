import { d1CubeDb } from "@/lib/cube";
import { HazardChapter, MongooseChapter, RainChapter } from "@/components/stories/Chapters";
import { loadHazard, loadMongoose, loadRain } from "@/lib/stories/amami";

export const dynamic = "force-dynamic";

export const metadata = { title: "奄美の物語 | 流域カルテ" };

/**
 * 奄美の物語。物語は奄美の話なので、`?region=` は読まない（神奈川などに切り替えても内容は変わらない）。
 * 章の構造は `lib/stories/amami.ts`、数値・日付・注記は DB から。ここには数字を書かない。
 */
export default async function AmamiStoryPage() {
  const db = await d1CubeDb();
  const [mongoose, rain, hazard] = await Promise.all([loadMongoose(db), loadRain(db), loadHazard(db)]);
  return (
    <div className="flex-1 overflow-y-auto thin-scroll">
      <section className="max-w-[1180px] mx-auto px-6 pt-6">
        <h1 className="text-[22px] font-bold">奄美の物語</h1>
        <p className="text-[12.5px] text-muted mt-1 max-w-3xl leading-relaxed">
          外来種の根絶、豪雨災害、土砂災害の区域。公開データと行政文書から、出典ごとの数字を並べる。
        </p>
      </section>
      <MongooseChapter story={mongoose} />
      <RainChapter story={rain} />
      <HazardChapter story={hazard} />
    </div>
  );
}
