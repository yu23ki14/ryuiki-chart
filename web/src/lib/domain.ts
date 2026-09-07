/**
 * 領域知識。データ探索で分かった「原本の癖」をここに集約する。
 * 画面側で個別に補正を書かないための場所。
 *
 * @deprecated このファイルの定数は `web/src/lib/registry/generated-client.ts`
 * （レジストリ由来・docs/plans/PHASE_A.md §A-2〜A-5）から組み立てる薄い層になった（§A-8）。
 * 13ファイルの利用側（`page.tsx` / `MapPage` / `SiteList` / `TimeseriesExplorer` /
 * `BiotaExplorer` / `QualityDashboard` / `DocumentsExplorer` / `SiteDetail` /
 * `SeriesChartCard` / ai の4ファイル）は Phase A では書き換えない。エクスポートの
 * 名前・形・値は変えていない（`web/src/lib/domain.test.ts` が現行値と一致することを固定する）。
 * 完全な撤去は Phase B 以降。新しい値をここに書き足さない（レジストリ側に足す）。
 *
 * `rowKeyLabel()` / `speciesLabel()` / `shortVariable()` のような関数はレジストリの対象外
 * （§A-8 の指示どおり、そのまま残す）。
 *
 * 「代表エイリアスから機械的に再構成する」性質は変わっていないが、再構成そのものは
 * ビルド時（`web/scripts/lib/registry-codegen.mjs`）に前倒しした（code-review #4）。
 * 以前はここで実行時に `allVariables()` / `primaryAlias()` を呼んで組み立てており、
 * その結果 variable(85件)・variable_alias(117件) の生テーブルがまるごとクライアント
 * バンドルに乗っていた（+43.5KB）。`generated-client.ts` は既に組み立て済みの
 * Record だけを持つので、ここは import してそのまま re-export するだけでよい。
 */
import {
  VARIABLE_SHORT,
  VARIABLE_NOTE,
  HIGHER_IS_WORSE,
  VARIABLE_UNIT_FALLBACK,
  NAME_JA,
} from "@/lib/registry/generated-client";
import { caveatBody } from "@/lib/registry/lookup-client";

export { VARIABLE_SHORT, VARIABLE_NOTE, HIGHER_IS_WORSE, VARIABLE_UNIT_FALLBACK, NAME_JA };

/** レジストリに実在するキーの本文だけを使う。無ければビルド時に気づけるよう例外を投げる。 */
function mustCaveatBody(key: string): string {
  const body = caveatBody(key);
  if (body === undefined) throw new Error(`registry/caveat.yaml に "${key}" が無い（domain.ts が参照している）`);
  return body;
}

export function shortVariable(v: string): string {
  return VARIABLE_SHORT[v] ?? v;
}

export const ZONE_INFO = [
  { zone: 1, label: "山地源流域", cond: "標高 800m 超" },
  { zone: 2, label: "山地渓流", cond: "標高 400–800m" },
  { zone: 3, label: "丘陵・扇状地", cond: "標高 100–400m" },
  { zone: 4, label: "平野・沖積低地", cond: "標高 100m 以下・海岸から 2km 超" },
  { zone: 5, label: "河口・沿岸", cond: "標高 100m 以下・海岸から 2km 以内" },
] as const;

export const QUALITY_STAGES = ["暫定", "検証済", "公開済"] as const;
export type QualityStage = (typeof QUALITY_STAGES)[number];

/**
 * `sites.municipality` は出典によって中身が違う。
 * 環境省 公共用水域の 290 地点では水域名（河川名・湖沼名）が入り、
 * それ以外の 62 地点では市区町村名が入る。列名と中身が一致していないので、
 * 画面では「水域・地域」と呼ぶ。
 */
export const MUNICIPALITY_LABEL = "水域・地域";

/** 原本の癖。画面の注記に出して、読み手が誤解しないようにする。 */
export const DATA_CAVEATS = {
  measuredOn: mustCaveatBody("measuredOn"),
  censored: mustCaveatBody("censored"),
  duplicates: mustCaveatBody("duplicates"),
  zone: mustCaveatBody("zone"),
  organismSite: mustCaveatBody("organismSite"),
  effort: mustCaveatBody("effort"),
  synthetic: mustCaveatBody("synthetic"),
} as const;

/**
 * 和名の辞書（本デモで付与したもの、`NAME_JA`。上で import・re-export 済み）。
 *
 * organism_records に和名は入っておらず（vernacular_name は英名）、
 * taxa テーブルの和名を学名で機械結合すると別地域の個体群の名前が付いてしまう
 * （例: Plecoglossus altivelis に「リュウキュウアユ」）。
 * そのため、画面に出す代表種についてだけ人が確認した和名をここに持つ
 * （`registry/taxon/vernacular_ja.csv` に移した54件。taxon テーブル全体の
 * vernacular_name_ja、8,324件・taxa 由来の別の母集団とは別物）。
 * ここに無い種は学名と英名だけを表示し、和名を推測しない。
 */
export function speciesLabel(binom: string, enName?: string | null): string {
  const ja = NAME_JA[binom];
  if (ja) return ja;
  return enName || binom;
}

/** 生物データの観察努力に関する事実（画面に必ず添える） */
export const BIOTA_CAVEATS = {
  regimes: mustCaveatBody("regimes"),
  gbifCutoff: mustCaveatBody("gbifCutoff"),
  share: mustCaveatBody("share"),
  inatBackfill: mustCaveatBody("inatBackfill"),
  fishClass: mustCaveatBody("fishClass"),
  isAlien: mustCaveatBody("isAlien"),
} as const;

/**
 * 行政文書から抽出した表の行キーは、表によって行見出しと列見出しが連結されている
 * （例: `湘南地域秦野市伊勢原市|清川村`）。信頼できるのは最後の `|` の後ろだけなので、
 * 表示名にはそこを使う。原文の行キーは別途そのまま見せる。
 */
export function rowKeyLabel(rowKey: string): string {
  if (!rowKey) return "";
  const i = rowKey.lastIndexOf("|");
  const tail = i >= 0 ? rowKey.slice(i + 1) : rowKey;
  return tail.trim() || rowKey;
}
