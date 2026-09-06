import { shortVariable } from "@/lib/domain";

/**
 * 画面の「状態」のスナップショット。データそのもの（表示中の行や点列）は含めない。
 * 古くなるし、トークンを食う。数値が要る質問はサーバ側がツールで取り直す。
 *
 * ルートごとの判別可能ユニオン。1スナップショットは 1KB 以内を目安にする
 * （フィールドは画面の「今の状態」を表す短い値だけで、配列や生データを持たない）。
 */
export type PageContext =
  | { route: "/"; title: string }
  | {
      route: "/timeseries";
      title: string;
      /** "water" | "zone" | "season" */
      mode: string;
      variable: string;
      /** 自動補正後の実効値（TimeseriesExplorer の water）。利用者の希望 waterPref ではない */
      water: string;
      /** 今のモードで実際に使われている粒度。zone は常に year、season は月別なので "month" */
      grain: string;
      /** 自動補正後の実効値（TimeseriesExplorer の kind）。利用者の希望 kindPref ではない */
      kind: string;
    }
  | {
      route: "/biota";
      title: string;
      /** "effort" | "trend" | "ias" | "redlist" */
      tab: string;
      group?: string;
      periodA?: [number, number];
      periodB?: [number, number];
      picked?: string[];
    }
  | {
      route: "/sites/[id]";
      title: string;
      siteId: string;
      name: string;
      zone: number | null;
      nMeas?: number;
    }
  // それ以外の画面は route と画面名だけ。PageContextProvider がパスから機械的に埋める。
  | { route: string; title: string };

const TIMESERIES_MODE_LABEL: Record<string, string> = {
  water: "水域の中で地点を比べる",
  zone: "尾根から海まで（ゾーン）で比べる",
  season: "季節でくらべる",
};
const BIOTA_TAB_LABEL: Record<string, string> = {
  effort: "記録の中身",
  trend: "種のふえへり",
  ias: "外来種",
  redlist: "レッドリスト版間比較",
};

/**
 * モデルに渡す1行説明。JSON をそのまま読ませてもよいが、日本語の一文にしておくと
 * システムプロンプトの中で扱いやすい（プロンプト側はこれ + 生JSONの両方を持つ）。
 */
export function describePageContext(ctx: PageContext): string {
  // switch(ctx.route) では絞り込めない: フォールバック分岐の route は string 型なので、
  // "/timeseries" 等のどのリテラルとも両立してしまい、判別共用体として narrow されない。
  // 各分岐だけに存在するプロパティの有無（in 演算子）で判別する。
  if (ctx.route === "/") return "概況画面（トップページ）を見ている。";
  if ("variable" in ctx) {
    const modeLabel = TIMESERIES_MODE_LABEL[ctx.mode] ?? ctx.mode;
    const parts = [`時系列比較画面。${modeLabel}`, `項目「${ctx.variable}」`];
    if (ctx.mode === "water" && ctx.water) parts.push(`水域「${ctx.water}」`);
    parts.push(`粒度=${ctx.grain === "year" ? "年" : ctx.grain === "month" ? "月" : ctx.grain}`);
    parts.push(`元データ=${ctx.kind === "daily" ? "検体値" : ctx.kind === "annual" ? "年度集計値" : ctx.kind}`);
    return parts.join("、") + "。";
  }
  if ("tab" in ctx) {
    const tabLabel = BIOTA_TAB_LABEL[ctx.tab] ?? ctx.tab;
    const parts = [`生物相画面。タブ「${tabLabel}」`];
    if (ctx.group) parts.push(`分類群「${ctx.group}」`);
    if (ctx.periodA && ctx.periodB) parts.push(`前期間 ${ctx.periodA.join("–")} / 後期間 ${ctx.periodB.join("–")}`);
    if (ctx.picked?.length) parts.push(`選択中の種: ${ctx.picked.join(", ")}`);
    return parts.join("、") + "。";
  }
  if ("siteId" in ctx) {
    return (
      `地点カルテ（個票）画面。地点「${ctx.name}」（ID: ${ctx.siteId}）` +
      `${ctx.zone != null ? `、ゾーン${ctx.zone}` : "、ゾーン不明"}` +
      `${ctx.nMeas != null ? `、測定値 ${ctx.nMeas.toLocaleString("ja-JP")} 件` : ""}を見ている。`
    );
  }
  return `「${ctx.title}」画面（${ctx.route}）を見ている。`;
}

const GENERIC_QUESTIONS = ["境川のBODは上流と下流でどう違う？", "鳥類の記録は増えている？", "このアプリにはどんなテーブルがある？"];

/**
 * EmptyState（Thread.tsx）に出す質問例。今の画面の実際の値を埋め込む。
 * 値が無い/汎用的な画面では一般例に落とす。
 */
export function suggestedQuestions(ctx: PageContext | null): string[] {
  if (!ctx) return GENERIC_QUESTIONS;
  // describePageContext と同じ理由で、route ではなく各分岐固有のプロパティで判別する。
  if (ctx.route === "/") {
    return ["このアプリにはどんなテーブルがある？", "流域ごとに生物記録が多いのはどこ？", "水質データで欠けているものは？"];
  }
  if ("variable" in ctx) {
    const v = shortVariable(ctx.variable);
    if (ctx.mode === "zone") {
      return [`${v}はゾーンによってどう違う？`, `${v}に季節性はある？`, "このアプリにはどんなテーブルがある？"];
    }
    if (ctx.mode === "season") {
      return [
        `${v}の季節変化にはどんな理由が考えられる？`,
        ctx.water ? `${ctx.water}の${v}はここ数年でどう変わった？` : `${v}はゾーンによってどう違う？`,
      ];
    }
    if (!ctx.water) return GENERIC_QUESTIONS;
    return [`${ctx.water}の${v}は上流と下流でどう違う？`, `${ctx.water}の${v}はここ数年でどう変わった？`, `${v}の値が大きい/小さいと何を意味する？`];
  }
  if ("tab" in ctx) {
    if (ctx.tab === "trend" && ctx.group) {
      return [`${ctx.group}の中でシェアが増えている種は？`, "この増減は観察努力の影響ではない？"];
    }
    if (ctx.tab === "redlist") return ["レッドリストで悪化した種にはどんな傾向がある？", "改善した種は何がきっかけ？"];
    if (ctx.tab === "ias") return ["外来種の分布は広がっている？", "対策カテゴリー別の記録数は？"];
    return ["鳥類の記録は増えている？", "GBIFとiNaturalistで記録の中身はどう違う？"];
  }
  if ("siteId" in ctx) {
    return [`${ctx.name}ではどんな項目を測っている？`, `${ctx.name}の値は近くの地点と比べてどう？`, "このアプリにはどんなテーブルがある？"];
  }
  return GENERIC_QUESTIONS;
}
