/**
 * v2（`lib/cube`）向けの注記引き（Issue #48 PR-1b、docs/plans/V2_SERVING_PR1.md §3.6・§6）。
 *
 * v1 の `web/src/lib/ai/caveats.ts`（`caveatsForTables`、テーブル名で引く）と対になる、
 * facet（`dataset`/`variable_theme`/`place_kind`/`source_id`）で引く版。中身は
 * `scripts/registry/build_caveat.py` が `caveat_scope` に足した v2 facet 行
 * （v1 の `table`/`table_prefix` 行の「隣」に追加しただけで、v1 側は1行も変えていない）。
 *
 * クライアント安全（`generated-client.ts` だけに依存。`server-only` は付けない）。
 * `./series`/`./sql` からは **型だけ**を import する（`import type` は完全に消える
 * ——`series.ts` がサーバ側の大きい `generated.ts` を読んでいても、型だけの参照なら
 * クライアントバンドルに一切含まれない）。
 *
 * ## 並び（Issue #48 PR-1 統合 §5）
 *
 * `caveatsForFacets` は「順序付きの facet 参照の配列（`FacetRef[]`）」を受け取り、
 * `web/src/lib/registry/lookup-client.ts` の `caveatsForTables()` と全く同じ一般規則
 * （`(priority 降順, 初出順 昇順, sortOrder 昇順)` でソートし、caveat の key で先勝ち
 * 重複排除——`lookup-client.ts` の `resolveCaveatRefs()` を共有し、この並べ替え・
 * 重複排除自体は1箇所にしかない）で注記を引く。**facet の種類ごとにグループ化してから並べる、ということは
 * しない**——`caveatsForTables` が「渡されたテーブル引数の出現順」をそのまま使うのと同じく、
 * `caveatsForFacets` も「渡された facet 参照の出現順」をそのまま使う。以前の実装は
 * `CaveatFacets`（`datasets`/`themes`/`placeKinds`/`sourceIds`/`tables` に分けたオブジェクト）
 * を受け取り、カテゴリ固定順（datasets→themes→placeKinds→sourceIds→tables）で平坦化して
 * いたため、`web/src/lib/ai/tools.ts` が渡す `["sites","site_var"]` のような「place_kind 系が
 * dataset 系より先に来る」複合で `caveatsForTables` と順序がずれていた
 * （`caveats.test.ts` の「既知の限界」テストが可視化していた）。
 *
 * ## `facetsForSeries` の型について（実装判断）
 *
 * `series`/`scope` は PR-1a（`web/src/lib/cube/series.ts`・`observation.ts`）の実際の
 * `SeriesInfo`/`Scope`（`CellSpec["scope"]` の型そのもの）をそのまま使う——構造的に
 * ほぼ満たすため、独自の最小インタフェースを別途定義しない（型だけの import なので
 * クライアント安全性は保たれる）。ただし `SeriesInfo` 自体は `theme`（`variable.theme`）
 * を持たない（`variable` の生テーブルはサーバ専用の `generated.ts` にしかなく、この
 * ファイルをクライアント安全のままにするため）。`theme` の解決は呼び出し側
 * （`variable` テーブルを既に読んでいる 1a の catalog.ts/series.ts 側）に委ね、
 * `SeriesFacetInput`（`SeriesInfo & { theme }`）として渡してもらう形にした。
 */
import { GENERATED_CAVEAT_SCOPE, type GeneratedCaveatScope } from "@/lib/registry/generated-client";
import { resolveCaveatRefs, type CaveatRef, type ScopeMatch } from "@/lib/registry/lookup-client";
import type { SeriesInfo } from "./series";
import type { Scope } from "./sql";

export type { CaveatRef };

/** `caveat_scope.scope_kind`（v2 facet 行の種類。互換のための `table` も含む）。 */
export type FacetKind = "dataset" | "variable_theme" | "place_kind" | "source_id" | "table";

/**
 * 1つの facet 参照。`kind="table"` は v1 のテーブル名（`caveatsForTables` と同じ一致方法。
 * `table_prefix` も見る）——v2 専用の呼び出しでは使わなくてよい。
 */
export interface FacetRef {
  readonly kind: FacetKind;
  readonly ref: string;
}

const SCOPES_BY_KIND = new Map<string, GeneratedCaveatScope[]>();
for (const s of GENERATED_CAVEAT_SCOPE) {
  const list = SCOPES_BY_KIND.get(s.scopeKind);
  if (list) list.push(s);
  else SCOPES_BY_KIND.set(s.scopeKind, [s]);
}
const TABLE_PREFIX_SCOPES = SCOPES_BY_KIND.get("table_prefix") ?? [];

function facetKey(f: FacetRef): string {
  return `${f.kind}\u0000${f.ref}`;
}

/**
 * facet の並び（`FacetRef[]`。渡された順序をそのまま使う）から、該当する注記を
 * 決定論的に引く。
 *
 * 並び: `(priority 降順, facet の初出順 昇順, sortOrder 昇順)` でソートし、caveat の
 * key で先勝ち重複排除する（`web/src/lib/registry/lookup-client.ts` の
 * `caveatsForTables()` と一字一句同じ規則。詳細は同ファイルの docstring・
 * `scripts/registry/build_caveat.py` の docstring参照）。
 */
export function caveatsForFacets(facets: readonly FacetRef[]): CaveatRef[] {
  const order = new Map<string, number>();
  facets.forEach((f, i) => {
    const k = facetKey(f);
    if (!order.has(k)) order.set(k, i);
  });

  const matches: ScopeMatch[] = [];
  for (const f of facets) {
    const idx = order.get(facetKey(f))!;
    for (const s of SCOPES_BY_KIND.get(f.kind) ?? []) {
      if (s.scopeRef === f.ref) matches.push({ scope: s, order: idx });
    }
    if (f.kind === "table") {
      for (const s of TABLE_PREFIX_SCOPES) {
        if (f.ref.startsWith(s.scopeRef)) matches.push({ scope: s, order: idx });
      }
    }
  }

  return resolveCaveatRefs(matches);
}

export function caveatKeysForFacets(facets: readonly FacetRef[]): string[] {
  return caveatsForFacets(facets).map((c) => c.key);
}

/**
 * `facetsForSeries` が受け取る系列情報。1a の `SeriesInfo` に `theme` を足しただけ
 * （上記「実装判断」参照）。
 */
export type SeriesFacetInput = SeriesInfo & {
  /** `variable.theme`（例: `water`/`weather`/`landuse`）。不明なら null。 */
  readonly theme: string | null;
};

/** ある系列が合成データか（`series.ts` の `isSynthetic` と同じ規約: sourceIds に null を含む）。 */
function isSyntheticSeries(s: SeriesFacetInput): boolean {
  return s.sourceIds.some((id) => id === null);
}

/**
 * 系列とスコープから facet 参照の並びを組み立てる（§3.6）。
 * 系列を順に見て、各系列について `dataset`→`variable_theme`→`source_id`（複数）の順に
 * 積む（合成データの系列——`isSynthetic`——は続けて `dataset='synthetic'` も積む。D4 の
 * 規約）。最後に scope から決まる `place_kind` を1つ積む（`'zone'` スコープだけ
 * `place_kind='zone'`、それ以外（site/water/places/all_sites）は `place_kind='site'`——
 * `scripts/registry/build_caveat.py` の facet 対応表どおり）。
 *
 * 同じ `(kind, ref)` の組は「初めて現れたところ」だけを残す（`caveatsForFacets` の
 * 初出順ソートに使うため）。
 */
export function facetsForSeries(series: readonly SeriesFacetInput[], scope: Scope): FacetRef[] {
  const refs: FacetRef[] = [];
  const seen = new Set<string>();
  const push = (kind: FacetKind, ref: string) => {
    const k = facetKey({ kind, ref });
    if (seen.has(k)) return;
    seen.add(k);
    refs.push({ kind, ref });
  };

  for (const s of series) {
    push("dataset", s.dataset);
    if (s.theme !== null) push("variable_theme", s.theme);
    for (const id of s.sourceIds) {
      if (id !== null) push("source_id", id);
    }
    if (isSyntheticSeries(s)) push("dataset", "synthetic");
  }

  push("place_kind", scope.kind === "zone" ? "zone" : "site");

  return refs;
}
