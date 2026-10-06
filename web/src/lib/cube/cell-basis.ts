/**
 * 「出典が配った粒度のセルか」「そのセルの basis は何か」の規則を置く**1か所**（Issue #32-2）。
 * クライアントコンポーネント（`SiteDetail.tsx`）からも import できるよう、何も import しない
 * （`series.ts` はサーバ専用の大きい `registry/generated.ts` を import するため）。
 *
 * ## 出典が配った粒度のセル（source-grain cell）
 *
 * - `input_grain = grain`: 出典が直接その粒度で配った値（年・年度・月）。
 * - `input_grain='month' AND grain='fiscal_year'`: 出典が年度で配った値のうち、日付が月までしか言えない
 *   日間平均値を月に復元し、b04 が `period_exceptions.yaml` の `rollup_to: [fiscal_year]` の宣言に
 *   従って年度へ積み上げ直したもの（厚木。旧来は年度番号から直接作っていた `input_grain='fiscal_year'` の
 *   セルと同じ意味）。**この条件は、その宣言（fiscal_year だけ）と対になっている**——別の粒度を
 *   宣言に足したらここにも足すこと。
 * - `input_grain='day'`（日次の積み上げ）・`hour`・`instant` は含まない。
 *
 * この規則を使う場所（同じ式を複製しない）:
 *   - TS: `isSourceGrainCell`・`basisOfCell`（`SiteDetail.tsx`・`catalog.ts`・`adapters-v2.ts`）。
 *   - SQL: `sourceGrainCellSql`（`observation.ts` の `inputGrain: "same"`）。
 *   - `web/serving_queries.yaml` の `variable_site_basis`/`variable_basis` の WHERE（YAML に直書きの
 *     SQL なので関数を使えない。`cell-basis.test.ts` が `sourceGrainCellSql("spv")` と同じ式が
 *     書かれていることを確かめる）。
 */

export type Basis = "day" | "fiscal_year" | "year";

/** 出典が配った粒度のセルか（`sourceGrainCellSql` と同じ規則。上の説明参照）。 */
export function isSourceGrainCell(cell: { grain: string; inputGrain: string }): boolean {
  return cell.inputGrain === cell.grain || (cell.inputGrain === "month" && cell.grain === "fiscal_year");
}

/** `isSourceGrainCell` の SQL 版。`alias` は `observation_agg`/`summary_place_variable` の別名。 */
export function sourceGrainCellSql(alias: string): string {
  return `(${alias}.input_grain = ${alias}.grain OR (${alias}.input_grain = 'month' AND ${alias}.grain = 'fiscal_year'))`;
}

/**
 * **basis はセルの性質**（`grain`/`input_grain` の組）として決める——系列の登録（`value_grain`）では
 * 決めない（Issue #48 PR-2 統合後修正A #1）。`value_grain='day'` として登録された系列でも、出典が
 * 一部の年だけ年度値を直接報告していれば `grain='fiscal_year'` のセルを持つことがある
 * （実測: 厚木系の中津川 BOD）。`input_grain='day'` は日次の積み上げ（day）、それ以外は
 * `grain='year'` なら year、そうでなければ fiscal_year。
 */
export function basisOfCell(cell: { grain: string; inputGrain: string }): Basis {
  if (cell.inputGrain === "day") return "day";
  return cell.grain === "year" ? "year" : "fiscal_year";
}
