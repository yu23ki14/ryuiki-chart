import Link from "next/link";
import type { HazardStory, MongooseStory, RainStory } from "@/lib/stories/amami";
import { nf } from "@/components/ui";
import { HazardStacked } from "./HazardStacked";
import { MongooseCharts } from "./MongooseCharts";
import { RainChart } from "./RainChart";
import { DamageTableView, NoteList, SourceList } from "./Parts";

function Chapter({ no, title, lead, children }: { no: string; title: string; lead: string; children: React.ReactNode }) {
  return (
    <section className="max-w-[1180px] mx-auto px-6 py-5 space-y-3">
      <header>
        <div className="text-[11px] text-muted tracking-wide">{no}</div>
        <h2 className="text-[18px] font-bold">{title}</h2>
        <p className="text-[12px] text-muted mt-1 max-w-3xl leading-relaxed">{lead}</p>
      </header>
      {children}
    </section>
  );
}

/** 章の見出しとつなぎ文。事実は主張せず、数値・日付・注記は DB から出す。 */
export function MongooseChapter({ story }: { story: MongooseStory }) {
  return (
    <Chapter no="一" title="マングースの根絶" lead="捕獲の記録と、根絶宣言についての注記を、出典の文面のまま並べる。">
      <MongooseCharts total={story.total} cpue={story.cpue} />
      <NoteList title="この数表の注意" notes={story.notes} />
      <NoteList title="根絶宣言" notes={story.declaration} />
      <SourceList docs={story.docs} />
    </Chapter>
  );
}

export function RainChapter({ story }: { story: RainStory }) {
  const peak = story.peak;
  return (
    <Chapter no="二" title="豪雨と被害" lead="ここから先は出典ごとの数字を並べる。食い違う数は、どれにも寄せない。">
      <RainChart days={story.days} unit={story.unit} band={story.band} />
      {peak && (
        <p className="text-[12px] text-ink-2">
          日降水量が最大の日: {peak.date}（{nf(peak.mm, 1)} {story.unit ?? ""}）
          {peak.maxHourMm !== null && `。その日の最大1時間降水量 ${nf(peak.maxHourMm, 1)} ${story.unit ?? ""}`}
        </p>
      )}
      <NoteList
        title="雨量の読み方"
        notes={[
          { key: "definition", text: story.rainNotes.definitionChange },
          { key: "owner", text: story.rainNotes.stationOwner },
        ]}
      />
      <DamageTableView table={story.damage} />
      <div className="card p-3.5">
        <h3 className="text-[13px] font-semibold mb-1.5">流域治水プロジェクトのダムの容量</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {story.chisui.dams.map((d) => (
            <table key={d.dam} className="dtable text-[11.5px]">
              <thead>
                <tr>
                  <th colSpan={2}>{d.dam}</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.col}>
                    <td>{r.col}</td>
                    <td className="num">
                      {nf(r.value)} {r.unit ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
        <p className="text-[10.5px] text-muted mt-1.5">数値のみを出典から抽出した。文章は転載しない。</p>
      </div>
      <SourceList docs={story.docs} />
    </Chapter>
  );
}

export function HazardChapter({ story }: { story: HazardStory }) {
  const { total, flooded } = story.rivers;
  return (
    <Chapter no="三" title="島の川と土砂災害" lead="土砂災害警戒区域を、区分と現象に分けて数える。因果は述べない。">
      <HazardStacked panels={story.panels} />
      {total && flooded && (
        <p className="text-[12px] text-ink-2">
          京大の速報より: 二級河川 {nf(total.value)}{total.unit ?? ""}のうち、氾濫した二級河川は {nf(flooded.value)}{flooded.unit ?? ""}。
        </p>
      )}
      <p className="text-[12px]">
        <Link href={story.mapHref} className="text-water underline">
          流域マップで土砂災害警戒区域を見る
        </Link>
      </p>
      <SourceList docs={story.docs} />
    </Chapter>
  );
}
