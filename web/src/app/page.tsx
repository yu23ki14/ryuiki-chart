import Link from "next/link";
import {
  overviewStats,
  longitudinalHighlight,
  landuseHighlight,
  redlistSummary,
  effortYears,
} from "@/lib/queries";
import { HomeHighlights } from "@/components/HomeHighlights";
import { Stat, nf } from "@/components/ui";
import { DATA_CAVEATS } from "@/lib/domain";
import { PageContextSetter } from "@/components/assistant/PageContextProvider";
import { EXPLORE_ENABLED } from "@/lib/features";

export const dynamic = "force-dynamic";

const SECTIONS = [
  {
    href: "/map",
    title: "流域マップ",
    body: "国土数値情報の単位流域 377 面に、観測地点・生物記録・土地利用の変化を重ねる。ベースマップは OpenStreetMap／地理院タイルを切り替えられる。",
  },
  {
    href: "/timeseries",
    title: "時系列比較",
    body: "同じ川の地点を上流から下流へ並べる、尾根から海までのゾーンで比べる、季節で比べる。年 × 月のヒートマップも同時に出る。",
  },
  {
    href: "/biota",
    title: "生物相",
    body: "82万件の観察記録。件数ではなく分類群内のシェアで増減を見る。外来種の分布、レッドリストの版間比較。",
  },
  {
    href: "/sites",
    title: "地点カルテ",
    body: "観測地点 352 件の一覧と個票。その地点が何を、いつから、どれだけ測っているか。",
  },
  {
    href: "/documents",
    title: "文書と統計",
    body: "行政PDFの表から抜き出した 119,533 セル。各点が「どの文書の何ページ」に由来するかを持ち、比較を妨げる注記を並べて出す。",
  },
  {
    href: "/quality",
    title: "品質と進捗",
    body: "提出→検証→公開のパイプライン、検証者ごとの差し戻し率、機器の校正、介入と意思決定のタイムライン。",
  },
  {
    href: "/explore",
    title: "データ探索",
    body: "D1 の中身を直接見る。テーブル閲覧・列の要約・任意の SELECT・CSV 書き出し。参照系の SQL しか通さない。",
    flag: EXPLORE_ENABLED,
  },
  {
    href: "/sources",
    title: "出典",
    body: "101 のデータソースと 98 の文書。ライセンスと再配布可否を1件ずつ。",
  },
].filter((s) => s.flag !== false);

export default async function Home() {
  // D1 は 1 クエリ 1 往復。まとめて投げる。
  const [s, longitudinal, landuse, redlist, effort] = await Promise.all([
    overviewStats(),
    longitudinalHighlight(),
    landuseHighlight(),
    redlistSummary(),
    effortYears(),
  ]);

  return (
    <div className="flex-1 overflow-y-auto thin-scroll">
      <PageContextSetter context={{ route: "/", title: "概況" }} />
      <section className="border-b border-line bg-surface">
        <div className="max-w-[1180px] mx-auto px-6 py-8">
          <p className="text-[11px] tracking-[0.16em] text-muted uppercase">Watershed Chart — Demo</p>
          <h1 className="text-[30px] font-bold leading-tight mt-1">
            尾根から海までを、一枚のカルテにする
          </h1>
          <p className="text-[14px] text-ink-2 mt-3 max-w-3xl leading-relaxed">
            流域を、水質・生物・土地利用・行政統計を横断して1つの単位として見るための画面です。
            神奈川県の公開データだけで組んであります。値はいずれも原本の数字であり、欠けている所は欠けたまま示します。
          </p>
          <p className="text-[12px] text-muted mt-2 max-w-3xl leading-relaxed">
            これは要求定義（流域カルテ / Watershed Chart）に対するデモ実装です。実運用の対象地である鹿児島県龍郷町のデータはまだ無いため、
            構造が同じ公開データが揃う神奈川県で作っています。地点・測定項目・フォームは設定で差し替えられる前提で作ってあります。
          </p>

          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-5 mt-6">
            <Stat label="観測地点" value={nf(s?.n_sites)} unit="件" />
            <Stat label="測定値" value={nf(s?.n_meas)} unit="行" note={`${s?.y_from}–${s?.y_to}`} />
            <Stat label="生物レコード" value={nf(s?.n_org)} unit="件" />
            <Stat label="センサー観測" value={nf(s?.n_sensor)} unit="行" />
            <Stat label="単位流域" value={nf(s?.n_watersheds)} unit="面" />
            <Stat label="観測イベント" value={nf(s?.n_events)} unit="件" />
            <Stat label="出典" value={nf(s?.n_sources)} unit="件" />
          </div>
        </div>
      </section>

      <section className="max-w-[1180px] mx-auto px-6 py-6">
        <h2 className="text-[16px] font-bold">この3つが、時系列で比べるということ</h2>
        <p className="text-[12px] text-muted mt-1 max-w-3xl leading-relaxed">
          「増えた／減った」を言うには、比べてよい相手を選ぶ必要があります。ここでは、場所で比べる・版で比べる・年で比べる、の3つを例に出します。
        </p>
        <HomeHighlights longitudinal={longitudinal} landuse={landuse} redlist={redlist} effort={effort} />
      </section>

      <section className="max-w-[1180px] mx-auto px-6 pb-6">
        <h2 className="text-[16px] font-bold mb-3">画面</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {SECTIONS.map((sec) => (
            <Link
              key={sec.href}
              href={sec.href}
              className="card p-3.5 hover:border-water transition-colors block"
            >
              <div className="text-[13.5px] font-semibold">{sec.title}</div>
              <p className="text-[11.5px] text-ink-2 mt-1 leading-relaxed">{sec.body}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="max-w-[1180px] mx-auto px-6 pb-10">
        <div className="card p-4">
          <h2 className="text-[14px] font-bold">このデータで気をつけること</h2>
          <p className="text-[11.5px] text-muted mt-1 leading-relaxed">
            画面のどこにいても、根拠と限界が数字のそばにあるようにしています。主なものをここにまとめます。
          </p>
          <ul className="mt-3 space-y-2">
            {[
              ["日付の形式が2種類ある", DATA_CAVEATS.measuredOn],
              ["「0」は本当に0ではない", DATA_CAVEATS.censored],
              ["同じ日に同じ項目が複数行ある", DATA_CAVEATS.duplicates],
              ["ゾーンは公式の区分ではない", DATA_CAVEATS.zone],
              ["生物レコードは地点に紐づいていない", DATA_CAVEATS.organismSite],
              ["生物の件数は観察努力を写している", DATA_CAVEATS.effort],
              ["一部は合成データ", DATA_CAVEATS.synthetic],
            ].map(([t, b]) => (
              <li key={t} className="border-l-2 border-line pl-3">
                <div className="text-[12.5px] font-medium">{t}</div>
                <p className="text-[11.5px] text-ink-2 mt-0.5 leading-relaxed">{b}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
