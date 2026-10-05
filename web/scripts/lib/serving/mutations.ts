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
  | "include_watershed_cells"
  // 生物系（PR-3b §3.3）
  | "label_wrong"
  | "drop_species_rows"
  | "inflate_n"
  // 文書・流域（PR-4 §5.2）
  | "doc_label_wrong"
  | "doc_drop_point"
  | "inflate_site_n";

export type ClassifyMutationName =
  | "day_split_rule_off"
  | "declared_rot"
  | "synthetic_rule_off"
  | "lod_rule_off"
  // 生物系5規則の無効化（PR-3b §3.3）
  | "memo_rule_off"
  | "species_n_rule_off"
  | "month_rule_off"
  | "label_rule_off"
  | "undated_rule_off"
  // 文書系列3規則の無効化（PR-4 §5.2）
  | "doc_label_rule_off"
  | "doc_warning_rule_off"
  | "doc_collapse_rule_off";

/** v1 側だけを狂わせる変異（design §8.1 U4「新しい変異 …merge_rule_off」）。
 *  `merge-v1.ts` の alias→variable_id 束ねを止め、`*_by_variable` 問い合わせの
 *  v1 側を alias 粒度のまま返す——v2 側は variable_id で束ねたままなのでキーが
 *  食い違い、`row_only_in_v1`/`row_only_in_v2` が大量に出て必ず unexplained>0
 *  （または `rowsByKey` の重複キー例外）になる。 */
export type V1MutationName = "merge_rule_off";

export const ROW_MUTATION_NAMES: readonly RowMutationName[] = [
  "lod_instead_of_zero",
  "drop_series",
  "swap_kind",
  "no_unit",
  "month_off_by_one",
  "include_watershed_cells",
  "label_wrong",
  "drop_species_rows",
  "inflate_n",
  "doc_label_wrong",
  "doc_drop_point",
  "inflate_site_n",
];

export const CLASSIFY_MUTATION_NAMES: readonly ClassifyMutationName[] = [
  "day_split_rule_off",
  "declared_rot",
  "synthetic_rule_off",
  "lod_rule_off",
  "memo_rule_off",
  "species_n_rule_off",
  "month_rule_off",
  "label_rule_off",
  "undated_rule_off",
  "doc_label_rule_off",
  "doc_warning_rule_off",
  "doc_collapse_rule_off",
];

export const V1_MUTATION_NAMES: readonly V1MutationName[] = ["merge_rule_off"];

export const ALL_MUTATION_NAMES: readonly string[] = [
  ...ROW_MUTATION_NAMES,
  ...CLASSIFY_MUTATION_NAMES,
  ...V1_MUTATION_NAMES,
];

export function isRowMutation(name: string): name is RowMutationName {
  return (ROW_MUTATION_NAMES as readonly string[]).includes(name);
}

export function isClassifyMutation(name: string): name is ClassifyMutationName {
  return (CLASSIFY_MUTATION_NAMES as readonly string[]).includes(name);
}

export function isV1Mutation(name: string): name is V1MutationName {
  return (V1_MUTATION_NAMES as readonly string[]).includes(name);
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
  month_off_by_one: ["month_series_site", "climatology", "zone_climatology", "species_months"],
  // 生物系（PR-3b §3.3）。表に無い名前は「全問い合わせに効く」になるので対象を必ず書く。
  label_wrong: ["species_labels"],
  drop_species_rows: ["species_years"],
  inflate_n: ["effort_years", "mesh_by_year", "ias_species", "overview_counts"],
  // 文書・流域（PR-4 §5.2）。
  doc_label_wrong: ["doc_series_meta"],
  doc_drop_point: ["doc_series_points"],
  inflate_site_n: ["watershed_rollup"],
};

/**
 * 変異ごとの「意味を持つ imputation」（§7-1）。表に無い名前はどの imputation でも意味を持つ。
 * `lod_rule_off` は `lod_imputation` 規則を止める変異で、zero 実行ではその規則が説明する差が無いので
 * 当てても何も落ちない（以前は `--mutate all` が zero 実行でこれを当てて NG になっていた）。
 */
const MUTATION_REQUIRES_IMPUTATION: Readonly<Record<string, "zero" | "lod">> = {
  lod_rule_off: "lod",
};

/** `--mutate all` を現在の imputation で展開する。意味を持たない変異は `skipped`（理由つき）に分ける。 */
export function expandAllMutations(imputation: "zero" | "lod"): { names: string[]; skipped: { name: string; reason: string }[] } {
  const names: string[] = [];
  const skipped: { name: string; reason: string }[] = [];
  for (const name of ALL_MUTATION_NAMES) {
    const need = MUTATION_REQUIRES_IMPUTATION[name];
    if (need !== undefined && need !== imputation) {
      skipped.push({ name, reason: `${need} 実行のみ（現在は ${imputation}）` });
    } else {
      names.push(name);
    }
  }
  return { names, skipped };
}

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
    case "label_wrong":
      // 規則（vernacular_label_rule）が有効でも落ちること: v2 の1ラベルを、registry から再計算した
      // 期待ラベルと食い違う名前に差し替える。「ラベルが何であれ説明する」穴を塞げているかを見る。
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      return rows.map((r, i) => (i === 0 && "label" in r.label ? { ...r, label: { ...r.label, label: `${r.label.label ?? ""}（変異）` } } : r));
    case "drop_species_rows":
      // species_years の 1 run は 1 種なので、その種の行を全部落とす（row_only_in_v1）。
      return rowMutationAppliesTo(name, queryId) ? [] : [...rows];
    case "inflate_n":
      // 説明できる規則の無い問い合わせ（effort/mesh/ias）の n を +1 する。
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      // overview_counts は列名が n ではなく n_sites（1行だけの問い合わせ）。
      if (queryId === "overview_counts") {
        return rows.map((r) => (typeof r.numeric.n_sites === "number" ? { ...r, numeric: { ...r.numeric, n_sites: r.numeric.n_sites + 1 } } : r));
      }
      return rows.map((r) => (typeof r.numeric.n === "number" ? { ...r, numeric: { ...r.numeric, n: r.numeric.n + 1 } } : r));
    case "doc_label_wrong":
      // 規則（doc_label_rule）が有効でも落ちること: v2 の1 label を再計算（lastIndexOf）と食い違う文字列に差し替える。
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      return rows.map((r, i) => (i === 0 && "label" in r.label ? { ...r, label: { ...r.label, label: `${r.label.label ?? ""}（変異）` } } : r));
    case "doc_drop_point":
      // v2 の点は値が1種の年だけ（割れる年は最初から出ない）なので、1点落とせば v1 にだけ在る行になり、
      // doc_year_collapse（割れた年だけを説明する）では説明できない。
      return rowMutationAppliesTo(name, queryId) ? rows.slice(1) : [...rows];
    case "inflate_site_n":
      // 説明できる規則の無い列（site_n と土地利用1列）を +1 する。
      if (!rowMutationAppliesTo(name, queryId)) return [...rows];
      return rows.map((r) => {
        const numeric = { ...r.numeric };
        if (typeof numeric.site_n === "number") numeric.site_n += 1;
        if (typeof numeric.built_km2_2016 === "number") numeric.built_km2_2016 += 1;
        return { ...r, numeric };
      });
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
    case "day_split_rule_off":
      return { disabledRules: new Set<KnownRule>(["day_split"]) };
    case "synthetic_rule_off":
      return { disabledRules: new Set<KnownRule>(["synthetic_excluded"]) };
    case "lod_rule_off":
      return { disabledRules: new Set<KnownRule>(["lod_imputation"]) };
    case "memo_rule_off":
      return { disabledRules: new Set<KnownRule>(["watershed_memo"]) };
    case "species_n_rule_off":
      return { disabledRules: new Set<KnownRule>(["species_n_definition"]) };
    case "month_rule_off":
      return { disabledRules: new Set<KnownRule>(["month_cell_membership"]) };
    case "label_rule_off":
      return { disabledRules: new Set<KnownRule>(["vernacular_label_rule"]) };
    case "undated_rule_off":
      return { disabledRules: new Set<KnownRule>(["undated_excluded"]) };
    case "doc_label_rule_off":
      return { disabledRules: new Set<KnownRule>(["doc_label_rule"]) };
    case "doc_warning_rule_off":
      return { disabledRules: new Set<KnownRule>(["doc_warning_scope"]) };
    case "doc_collapse_rule_off":
      return { disabledRules: new Set<KnownRule>(["doc_year_collapse"]) };
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
