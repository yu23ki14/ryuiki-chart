/**
 * ツール結果から画面のURLを組み立てる純関数群。
 *
 * AI にはツールとして持たせない（`set_view` の類はわざと作らない）。ここは「結果を見て
 * カード側が機械的にリンクを作る」ための場所で、生成した URL は普通の <Link> として出す。
 * 画面への遷移をモデルに行わせない、という Stage 2 の設計判断そのもの。
 */

export interface TimeseriesLinkScope {
  type: "water" | "site" | "zone";
  name?: string;
  siteId?: string;
}

export interface TimeseriesLinkInput {
  /** variable_id（`common:variable:...`）。alias 文字列ではない（Issue #48 PR-2 design §5）。 */
  variableId: string;
  scope: TimeseriesLinkScope;
  grain: "year" | "fiscal_year" | "month" | "day";
  basis?: "day" | "fiscal_year" | "year";
  stat?: string;
}

/**
 * /timeseries 画面で、get_timeseries の結果と同じ表示を開くURLを組み立てる。
 *
 * TimeseriesExplorer の UI には「水域の中で地点を比べる（年/月）」と「ゾーン（年のみ）」の
 * 2軸しか無く、単一地点スコープ（scope.type === "site"）や日次粒度（grain === "day"）は
 * 画面上でそのまま再現できない。誤解を招く近似のリンクを作るくらいなら、対応できないときは
 * リンクを出さない方を選ぶ（null を返す）。
 */
export function timeseriesUrl(input: TimeseriesLinkInput): string | null {
  if (input.scope.type === "site") return null;
  if (input.grain === "day") return null;
  if (input.scope.type === "water" && !input.scope.name) return null;

  const params = new URLSearchParams({ variable: input.variableId, grain: input.grain });
  if (input.scope.type === "water") {
    params.set("mode", "water");
    params.set("water", input.scope.name as string);
  } else {
    params.set("mode", "zone");
  }
  if (input.basis) params.set("basis", input.basis);
  if (input.stat) params.set("stat", input.stat);
  return `/timeseries?${params.toString()}`;
}

/**
 * /explore を SQL コンソールで、この SQL を入れた状態にして開くURL。
 * 実行はしない（「開く」だけ）。実行するかどうかは利用者が画面上で選ぶ。
 */
export function exploreSqlUrl(sql: string): string {
  return `/explore?${new URLSearchParams({ sql }).toString()}`;
}
