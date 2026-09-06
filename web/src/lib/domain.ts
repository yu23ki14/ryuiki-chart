/**
 * 領域知識。データ探索で分かった「原本の癖」をここに集約する。
 * 画面側で個別に補正を書かないための場所。
 *
 * @deprecated このファイルの定数は `web/src/lib/registry/generated.ts`
 * （レジストリ由来・docs/plans/PHASE_A.md §A-2〜A-5）から組み立てる薄い層になった（§A-8）。
 * 13ファイルの利用側（`page.tsx` / `MapPage` / `SiteList` / `TimeseriesExplorer` /
 * `BiotaExplorer` / `QualityDashboard` / `DocumentsExplorer` / `SiteDetail` /
 * `SeriesChartCard` / ai の4ファイル）は Phase A では書き換えない。エクスポートの
 * 名前・形・値は変えていない（`web/src/lib/domain.test.ts` が現行値と一致することを固定する）。
 * 完全な撤去は Phase B 以降。新しい値をここに書き足さない（レジストリ側に足す）。
 *
 * `rowKeyLabel()` / `speciesLabel()` / `shortVariable()` のような関数はレジストリの対象外
 * （§A-8 の指示どおり、そのまま残す）。
 */
import {
  GENERATED_VARIABLE_ALIASES,
  GENERATED_VERNACULAR_JA,
  type GeneratedVariable,
} from "@/lib/registry/generated";
import { allVariables, caveatBody, primaryAlias, unitSymbol } from "@/lib/registry/lookup";

/** レジストリに実在するキーの本文だけを使う。無ければビルド時に気づけるよう例外を投げる。 */
function mustCaveatBody(key: string): string {
  const body = caveatBody(key);
  if (body === undefined) throw new Error(`registry/caveat.yaml に "${key}" が無い（domain.ts が参照している）`);
  return body;
}

interface PrimaryMeasurementAlias {
  variable: GeneratedVariable;
  alias: string;
  grain: string | null;
}

/**
 * `variable_alias`（source_scope='measurements'）の中から、各 variable の
 * 「代表エイリアス」（`primaryAlias()`、web/src/lib/registry/lookup.ts 参照）だけを集めたもの。
 * VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE はすべてここから作る
 * （代表エイリアスの選び方は共通。使う列と、値が無いときに落とすかどうかが違うだけ）。
 */
const PRIMARY_MEASUREMENT_ALIASES: PrimaryMeasurementAlias[] = allVariables()
  .map((variable) => ({ variable, row: primaryAlias(variable.variableId, "measurements") }))
  .filter((x): x is { variable: GeneratedVariable; row: NonNullable<ReturnType<typeof primaryAlias>> } => !!x.row)
  .map(({ variable, row }) => ({ variable, alias: row.alias, grain: row.grain }));

/** 水質項目の短い表示名（原本の variable は長いものがある） */
export const VARIABLE_SHORT: Record<string, string> = Object.fromEntries(
  PRIMARY_MEASUREMENT_ALIASES
    // grain='fiscal_year' しか出典表記が無い項目（健康項目27種・全窒素・全燐など）は対象にしない。
    // domain.ts の原文もこれらを「短縮」していない（原表記がすでに正式な学術記号か、
    // 出典側コードそのままで、短縮の必要が無い）。primaryAlias が fiscal_year に落ちるのは
    // 「検体値・年度集計値混在（grain='mixed'/'day'）の出典表記が無い」variable だけなので、
    // この条件で domain.ts の元の対象範囲（7件）とちょうど一致する。
    .filter(({ grain }) => grain !== "fiscal_year")
    .filter(({ variable, alias }) => variable.nameJa && variable.nameJa !== alias)
    .map(({ variable, alias }) => [alias, variable.nameJa as string]),
);

/**
 * 単位が原本で NULL の項目に、既知のものだけ補う（推測はしない）。
 *
 * `variable`（正準の指標）側の unit_id ではなく、`variable_alias` の行が個別に
 * unit_id を明示している（＝出典表記ごとの上書き）ケースだけを見る。pH 系の3表記
 * （本体・最大値・最小値）がこれにあたる（registry/variable_alias.csv の note に
 * 「domain.ts の VARIABLE_UNIT_FALLBACK が pH は無次元と既に明記」とある）。
 */
export const VARIABLE_UNIT_FALLBACK: Record<string, string> = Object.fromEntries(
  GENERATED_VARIABLE_ALIASES.filter((a) => a.sourceScope === "measurements" && a.unitId)
    .map((a) => [a.alias, unitSymbol(a.unitId)] as const)
    .filter((pair): pair is [string, string] => pair[1] === ""),
);

export function shortVariable(v: string): string {
  return VARIABLE_SHORT[v] ?? v;
}

/** 何を意味する指標か。ツールチップに出す。 */
export const VARIABLE_NOTE: Record<string, string> = Object.fromEntries(
  PRIMARY_MEASUREMENT_ALIASES.filter(({ grain }) => grain !== "fiscal_year")
    .filter(({ variable }) => variable.descriptionJa)
    .map(({ variable, alias }) => [alias, variable.descriptionJa as string]),
);

/** 上流→下流でこの向きに動くのが「悪化」か。矢印の向きに使う。 */
export const HIGHER_IS_WORSE: Record<string, boolean> = Object.fromEntries(
  PRIMARY_MEASUREMENT_ALIASES.filter(({ variable }) => variable.higherIsWorse !== null).map(({ variable, alias }) => [
    alias,
    variable.higherIsWorse as boolean,
  ]),
);

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
 * 和名の辞書（本デモで付与したもの）。
 *
 * organism_records に和名は入っておらず（vernacular_name は英名）、
 * taxa テーブルの和名を学名で機械結合すると別地域の個体群の名前が付いてしまう
 * （例: Plecoglossus altivelis に「リュウキュウアユ」）。
 * そのため、画面に出す代表種についてだけ人が確認した和名をここに持つ
 * （`registry/taxon/vernacular_ja.csv` に移した54件。taxon テーブル全体の
 * vernacular_name_ja、8,324件・taxa 由来の別の母集団とは別物）。
 * ここに無い種は学名と英名だけを表示し、和名を推測しない。
 */
export const NAME_JA: Record<string, string> = Object.fromEntries(
  GENERATED_VERNACULAR_JA.map((v) => [v.scientificName, v.vernacularNameJa]),
);

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
