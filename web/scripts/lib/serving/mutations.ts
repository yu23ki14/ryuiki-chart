/**
 * 「変異で拾う」の実装（設計書 §5.3）。既知の誤りを注入して、serving-diff が
 * 必ず unexplained > 0（または `declared_rot` なら終了コード2）で落ちることを
 * 確かめるための道具。
 *
 * 2種類に分かれる:
 *   - 行レベルの変異（v2 側の `NormRow[]` を、比較する前に書き換える）
 *   - 分類器レベルの変異（`ClassifyContext` の一部を上書きする——特定の規則を
 *     無効化する、宣言を1件だけ無視する）
 *
 * どちらも `applyRowMutation`/`applyClassifyMutation` から名前で呼ぶ。存在しない
 * 名前は例外にする（`--mutate` の打ち間違いを静かに無視しない）。
 */
import type { NormRow, ScalarParam } from "./normalize";
import type { DeclaredRotOptions, KnownRule } from "./classify";

export type RowMutationName =
  | "lod_instead_of_zero"
  | "drop_series"
  | "swap_kind"
  | "no_unit"
  | "month_off_by_one"
  | "include_watershed_cells";

export type ClassifyMutationName = "rain_no_div10_rule" | "day_split_rule_off" | "declared_rot";

export const ROW_MUTATION_NAMES: readonly RowMutationName[] = [
  "lod_instead_of_zero",
  "drop_series",
  "swap_kind",
  "no_unit",
  "month_off_by_one",
  "include_watershed_cells",
];

export const CLASSIFY_MUTATION_NAMES: readonly ClassifyMutationName[] = [
  "rain_no_div10_rule",
  "day_split_rule_off",
  "declared_rot",
];

export const ALL_MUTATION_NAMES: readonly string[] = [...ROW_MUTATION_NAMES, ...CLASSIFY_MUTATION_NAMES];

export function isRowMutation(name: string): name is RowMutationName {
  return (ROW_MUTATION_NAMES as readonly string[]).includes(name);
}

export function isClassifyMutation(name: string): name is ClassifyMutationName {
  return (CLASSIFY_MUTATION_NAMES as readonly string[]).includes(name);
}

/**
 * 「どの問い合わせ id にこの行変異が意味を持つか」の唯一の宣言表。`undefined`
 * （表に無い名前）は「全問い合わせに効く」という意味（レコードの中身だけを見て
 * 判定する変異は queryId を問わない）。`applyRowMutation`（変異の適用時）と
 * `rowMutationAppliesTo`（`--mutate all` が回す対象を決めるとき）の両方が
 * これを見る——以前はこのガードが2箇所（`applyRowMutation` 内の if 文と、
 * この表が無かった頃の `rowMutationAppliesTo` 本体）に別々に書かれていた。
 */
const ROW_MUTATION_APPLIES_TO: Partial<Record<RowMutationName, readonly string[]>> = {
  swap_kind: ["year_series_site", "year_series_water"],
  month_off_by_one: ["month_series_site", "climatology", "zone_climatology"],
};

/** `--mutate all` 用に、対応するクエリ id 一覧を返す（無関係な id には no-op で効かない変異もある）。 */
export function rowMutationAppliesTo(name: RowMutationName, queryId: string): boolean {
  const ids = ROW_MUTATION_APPLIES_TO[name];
  return ids === undefined || ids.includes(queryId);
}

/**
 * v2 側の行を書き換える。`queryId` によって意味が無い変異は素通りする
 * （例: `swap_kind` は年次系列にしか意味が無いので、他の問い合わせでは no-op）。
 * 実際の DB を読まない・触らないので、フィクスチャの `NormRow[]` にもそのまま使える。
 */
export function applyRowMutation(name: RowMutationName, queryId: string, rows: readonly NormRow[]): NormRow[] {
  switch (name) {
    case "lod_instead_of_zero":
      // value_zero の代わりに value_lod を返してしまうバグの再現。ここではフィクスチャ/
      // 実行のどちらでも「avg 相当の主要な数値列を少しずらす」ことで同じ効果を作る
      // （検閲されたセルでだけ value_zero と value_lod が食い違うので、n_censored > 0 の
      // 行だけずらす）。
      return rows.map((r) => {
        if ((r.numeric.n_censored ?? 0) <= 0) return r;
        const bumped = { ...r.numeric };
        for (const col of ["avg", "value", "min", "max"] as const) {
          if (typeof bumped[col] === "number") bumped[col] = bumped[col]! + 1e6; // 検出しやすい大きなずれ
        }
        return { ...r, numeric: bumped };
      });
    case "drop_series":
      // 系列の統合先が1系列足りないケースの再現。単純に半分の行を丸ごと落とす。
      return rows.filter((_, i) => i % 2 === 0);
    case "swap_kind": {
      // daily/annual の取り違え = 隣り合う行どうしで数値を入れ替える
      // （year_series_site/year_series_water のみ意味がある）。
      // 行キーは変えない——比較はキーで突き合わせる（配列の並び順には依らない）ので、
      // 配列を丸ごと reverse() するだけでは差分にならない。実際に値を取り違える。
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      const swapped = [...rows];
      for (let i = 0; i + 1 < swapped.length; i += 2) {
        const a = swapped[i];
        const b = swapped[i + 1];
        swapped[i] = { ...a, numeric: b.numeric };
        swapped[i + 1] = { ...b, numeric: a.numeric };
      }
      return swapped;
    }
    case "no_unit":
      return rows.map((r) => ("unit" in r.label ? { ...r, label: { ...r.label, unit: null } } : r));
    case "month_off_by_one":
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      return rows.map((r) => {
        if (r.key.length === 0) return r;
        const shifted = [...r.key];
        const last = shifted[shifted.length - 1];
        if (typeof last === "number") shifted[shifted.length - 1] = last + 1;
        else if (typeof last === "string" && /^\d{4}-\d{2}$/.test(last)) {
          const [y, m] = last.split("-").map(Number);
          const nm = (m % 12) + 1;
          const ny = nm === 1 ? y + 1 : y;
          shifted[shifted.length - 1] = `${ny}-${String(nm).padStart(2, "0")}`;
        }
        return { ...r, key: shifted };
      });
    case "include_watershed_cells":
      // `place_kind='site'` の絞り込みを外す = 重複行が増える再現。行を複製して壊す。
      return rows.length ? [...rows, rows[0]] : [...rows];
    default: {
      const exhaustive: never = name;
      throw new Error(`未知の行変異: ${exhaustive}`);
    }
  }
}

export interface ClassifyMutationOptions {
  disabledRules?: Set<KnownRule>;
  declaredRot?: DeclaredRotOptions;
}

/** `ClassifyContext` に足し込む上書き分を返す（`serving-diff.mts` が spread する）。 */
export function applyClassifyMutation(
  name: ClassifyMutationName,
  opts: { declaredRotTarget?: DeclaredRotOptions } = {},
): ClassifyMutationOptions {
  switch (name) {
    case "rain_no_div10_rule":
      return { disabledRules: new Set<KnownRule>(["rain_div10"]) };
    case "day_split_rule_off":
      return { disabledRules: new Set<KnownRule>(["day_split"]) };
    case "declared_rot": {
      if (!opts.declaredRotTarget) {
        throw new Error("declared_rot には無視する宣言（table/key/kind）の指定が要る");
      }
      return { declaredRot: opts.declaredRotTarget };
    }
    default: {
      const exhaustive: never = name;
      throw new Error(`未知の分類器変異: ${exhaustive}`);
    }
  }
}

export type { ScalarParam };
