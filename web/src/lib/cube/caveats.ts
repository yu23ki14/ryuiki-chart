/**
 * v2（`lib/cube`）向けの注記引き（Issue #48 PR-1b、docs/plans/V2_SERVING_PR1.md §3.6・§6）。
 *
 * v1 の `web/src/lib/ai/caveats.ts`（`caveatsForTables`、テーブル名で引く）と対になる、
 * facet（`dataset`/`variable_theme`/`place_kind`/`source_id`）で引く版。中身は
 * `scripts/registry/build_caveat.py` が `caveat_scope` に足した v2 facet 行
 * （v1 の `table`/`table_prefix` 行の「隣」に追加しただけで、v1 側は1行も変えていない）。
 *
 * クライアント安全（`generated-client.ts` だけに依存。`server-only` は付けない）。
 * `web/src/lib/registry/lookup-client.ts` の `caveatsForTables()` と同じ一般規則
 * （`(priority 降順, 出現順 昇順, sortOrder 昇順)` でソートし、caveat の key で先勝ち
 * 重複排除）を facet 版に一般化しただけで、特殊分岐は無い。
 *
 * ## `facetsForSeries` の型について（実装判断）
 *
 * 設計書 §3.6 は `facetsForSeries(series: SeriesInfo[], scope: CellSpec["scope"])` という
 * シグネチャを示すが、`SeriesInfo`/`CellSpec` は Issue #48 PR-1a（`web/src/lib/cube/series.ts`・
 * `observation.ts`）がこの PR と並行して作るもので、まだ存在しない。ファイル衝突を避けるため
 * （設計書 §8: 「`web/src/lib/cube/` では `caveats.ts` と `caveats.test.ts` 以外を作らない」）、
 * ここでは 1a の型を import せず、必要最小限のフィールドだけを持つ自前のインタフェース
 * （`SeriesFacetInput`/`SeriesFacetScope`）で受ける。1a の `SeriesInfo`/`CellSpec["scope"]` は
 * 構造的にこれを満たす形になる想定なので、実際の呼び出し側はそのまま渡せる。
 *
 * `SeriesInfo` 自体は `theme`（`variable.theme`）を持たない（§3.2 の定義参照）。
 * `variable` の生テーブルはサーバ専用の `generated.ts` にしかなく、このファイルを
 * クライアント安全のままにするため、`theme` の解決は呼び出し側
 * （`variable` テーブルを既に読んでいる 1a の catalog.ts/series.ts 側）に委ね、
 * `SeriesFacetInput.theme` として渡してもらう形にした。
 */
import { GENERATED_CAVEAT_SCOPE, type GeneratedCaveatScope } from "@/lib/registry/generated-client";
import { tryCaveatBody, type CaveatRef } from "@/lib/registry/lookup-client";

export type { CaveatRef };

/** `caveatsForFacets` の入力。渡された facet は種類ごとに、値の配列として複数持てる。 */
export interface CaveatFacets {
  datasets?: readonly string[];
  themes?: readonly string[];
  placeKinds?: readonly string[];
  sourceIds?: readonly string[];
  /** v1 のテーブル名（`caveatsForTables` と同じ一致方法。table_prefix も見る）。
   * v2 専用の呼び出しでは省略してよい。 */
  tables?: readonly string[];
}

type FacetListKey = "datasets" | "themes" | "placeKinds" | "sourceIds" | "tables";

/** `CaveatFacets` の各フィールドが対応する `caveat_scope.scope_kind`。
 * `tables` だけは `table`（`table_prefix` は別途あつかう。下記参照）。 */
const FACET_TO_SCOPE_KIND: Record<FacetListKey, GeneratedCaveatScope["scopeKind"]> = {
  datasets: "dataset",
  themes: "variable_theme",
  placeKinds: "place_kind",
  sourceIds: "source_id",
  tables: "table",
};

// facet の出現順（datasets, themes, placeKinds, sourceIds, tables の順に平坦化。§3.6）。
const FACET_ORDER: readonly FacetListKey[] = ["datasets", "themes", "placeKinds", "sourceIds", "tables"];

const SCOPES_BY_KIND = new Map<string, GeneratedCaveatScope[]>();
for (const s of GENERATED_CAVEAT_SCOPE) {
  const list = SCOPES_BY_KIND.get(s.scopeKind);
  if (list) list.push(s);
  else SCOPES_BY_KIND.set(s.scopeKind, [s]);
}
const TABLE_PREFIX_SCOPES = SCOPES_BY_KIND.get("table_prefix") ?? [];

/**
 * facet（`dataset`/`variable_theme`/`place_kind`/`source_id`、および互換のための
 * `table`/`table_prefix`）から、該当する注記を決定論的に引く。
 *
 * 並び: `(priority 降順, facet の出現順 昇順, sortOrder 昇順)` でソートし、caveat の
 * key で先勝ち重複排除する（`web/src/lib/registry/lookup-client.ts` の
 * `caveatsForTables()` と同じ規則。詳細は同ファイルの docstring・
 * `scripts/registry/build_caveat.py` の docstring参照）。
 */
export function caveatsForFacets(facets: CaveatFacets): CaveatRef[] {
  const matches: { scope: GeneratedCaveatScope; order: number }[] = [];
  let order = 0;

  for (const facetKey of FACET_ORDER) {
    const values = facets[facetKey] ?? [];
    const scopeKind = FACET_TO_SCOPE_KIND[facetKey];
    for (const value of values) {
      for (const s of SCOPES_BY_KIND.get(scopeKind) ?? []) {
        if (s.scopeRef === value) matches.push({ scope: s, order });
      }
      if (facetKey === "tables") {
        for (const s of TABLE_PREFIX_SCOPES) {
          if (value.startsWith(s.scopeRef)) matches.push({ scope: s, order });
        }
      }
      order += 1;
    }
  }

  matches.sort((a, b) => {
    if (a.scope.priority !== b.scope.priority) return b.scope.priority - a.scope.priority;
    if (a.order !== b.order) return a.order - b.order;
    return a.scope.sortOrder - b.scope.sortOrder;
  });

  const seen = new Map<string, CaveatRef>();
  for (const { scope } of matches) {
    if (seen.has(scope.caveatKey)) continue;
    seen.set(scope.caveatKey, { key: scope.caveatKey, text: tryCaveatBody(scope.caveatKey) ?? scope.caveatKey });
  }
  return [...seen.values()];
}

export function caveatKeysForFacets(facets: CaveatFacets): string[] {
  return caveatsForFacets(facets).map((c) => c.key);
}

/**
 * `facetsForSeries` が受け取る最小限の系列情報（上記「実装判断」参照）。
 * PR-1a の `series.ts` の `SeriesInfo` はこれを構造的に満たす。
 */
export interface SeriesFacetInput {
  /** v1 の `dataset`（`measurements`/`organism_records` 等）。 */
  readonly dataset: string;
  /** 系列を構成する alias の `source_id`。出典未記録（合成データ）の alias は null。 */
  readonly sourceIds: readonly (string | null)[];
  /** `variable.theme`（例: `water`/`weather`/`landuse`）。不明なら null。 */
  readonly theme: string | null;
}

/**
 * `facetsForSeries` が受け取る最小限のスコープ情報（上記「実装判断」参照）。
 * PR-1a の `observation.ts` の `CellSpec["scope"]` はこれを構造的に満たす
 * （`kind` だけを見るので、他のフィールド——`placeIds`/`siteId`/`municipality`/`zone`——は
 * 無くてもよい）。
 */
export interface SeriesFacetScope {
  readonly kind: "places" | "site" | "water" | "zone" | "all_sites";
}

/** ある系列が合成データか（`series.ts` の `isSynthetic` と同じ規約: sourceIds に null を含む）。 */
function isSyntheticSeries(s: SeriesFacetInput): boolean {
  return s.sourceIds.some((id) => id === null);
}

/**
 * 系列とスコープから facet を組み立てる（§3.6）。
 * - `datasets`: 渡された系列の `dataset` の和集合。合成データの系列
 *   （`isSynthetic`）が1つでもあれば `'synthetic'` も足す（D4 の規約）。
 * - `themes`: 渡された系列の `theme` の和集合（null は無視）。
 * - `placeKinds`: scope の種類から機械的に決める。`'zone'` スコープだけ
 *   `place_kind='zone'`、それ以外（site/water/places/all_sites）は
 *   `place_kind='site'`（`scripts/registry/build_caveat.py` の facet 対応表どおり—
 *   ゾーン単位に集計したセルだけが zone の注記の対象で、地点単位のセルは
 *   水域越しに見ても site のまま）。
 * - `sourceIds`: 渡された系列の `source_id` の和集合（null は除く）。
 *
 * 各集合は「初めて現れた順」を保つ（`caveatsForFacets` の出現順ソートに使うため、
 * `Set` そのままではなく配列として返す）。
 */
export function facetsForSeries(series: readonly SeriesFacetInput[], scope: SeriesFacetScope): CaveatFacets {
  const datasets: string[] = [];
  const themes: string[] = [];
  const sourceIds: string[] = [];
  const seenDatasets = new Set<string>();
  const seenThemes = new Set<string>();
  const seenSourceIds = new Set<string>();

  const addDataset = (d: string) => {
    if (seenDatasets.has(d)) return;
    seenDatasets.add(d);
    datasets.push(d);
  };

  for (const s of series) {
    addDataset(s.dataset);
    if (s.theme !== null && !seenThemes.has(s.theme)) {
      seenThemes.add(s.theme);
      themes.push(s.theme);
    }
    for (const id of s.sourceIds) {
      if (id === null) continue;
      if (seenSourceIds.has(id)) continue;
      seenSourceIds.add(id);
      sourceIds.push(id);
    }
    if (isSyntheticSeries(s)) addDataset("synthetic");
  }

  const placeKinds = [scope.kind === "zone" ? "zone" : "site"];

  return { datasets, themes, placeKinds, sourceIds };
}
