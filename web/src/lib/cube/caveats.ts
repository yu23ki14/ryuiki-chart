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

/** `caveat_scope.scope_kind`（v2 facet 行の種類。互換のための `table` も含む）。
 *  `variable`（PR-2 で追加。§6・D3）は `variable_id` 単位の注記（`unitUnknown` 等）用。 */
export type FacetKind = "dataset" | "variable_theme" | "place_kind" | "source_id" | "table" | "variable";

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

/**
 * 系列とスコープから facet 参照の並びを組み立てる（§3.6、PR-2 で D2 の synthetic push を
 * 撤去・`variable` facet を追加）。系列を順に見て、各系列について
 * `dataset`→`variable_theme`→`source_id`（複数）→`variable`（`variableId`。**`unitId`
 * が null の系列だけ**）の順に積む。最後に scope から決まる `place_kind` を1つ積む
 * （`'zone'` スコープだけ `place_kind='zone'`、それ以外（site/water/places/all_sites）は
 * `place_kind='site'`——`scripts/registry/build_caveat.py` の facet 対応表どおり）。
 *
 * **`variable` facet は `unitId===null` の系列だけに push する**（統合後の追加決定。
 * `unitUnknown` の対象 variable_id——`hydro.flow`/`water.water_temp`/
 * `air.photochemical_oxidant`/`weather.precipitation` 等8件——のうち `water.water_temp`
 * のように単位が分かっている実データの系列も同じ variable_id に混在するものがある。
 * variable_id 単位で無条件に push すると、単位が判明している系列にまで「単位不明」の
 * 注記が誤って付く——合成データの誤爆（PR-2 で撤去した synthetic push）と同じ種類の
 * 誤り。`unitId` が既知の系列は `variable` facet を push しない。
 *
 * **PR-2 で撤去**（design §0-2・D2）: 以前はここで合成データの系列（`sourceIds` に
 * null を含む）に続けて `dataset='synthetic'` を積んでいたが、実測で「合成専用の
 * 地点」ではなく実在地点に混在しており（例: SS/DO は atsugi の実データと同じ組を
 * 共有）、除外後も実データの系列に「合成データ」注記を誤って付けてしまう不正確な
 * 近似だった。b03 が合成行を除いた後の `observation_agg` には合成データが載らないため、
 * この push 自体が不要になった。
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
    if (s.unitId === null) push("variable", s.variableId);
  }

  push("place_kind", scope.kind === "zone" ? "zone" : "site");

  return refs;
}

/**
 * 生物出現（`occurrence_agg`）を引く画面・API・AI の facet（Issue #48 PR-3b、§2.2）。
 * `dataset=organism_records` を常に、`place_kind=grid01` を grid01 を引くとき、
 * `source_id=moe_ias_list` を IAS のときに積む（いずれも `registry/caveat.yaml`・
 * `build_caveat.py` に既にある v2 facet）。v1 表名ベースの `table` は使わない（危険16件 #1）。
 * `watershed` は専用の注記が無いので積まない（`organism_records` だけで足りる）。
 */
export function facetsForOccurrence(opt: { places: readonly ("grid01" | "watershed")[]; ias?: boolean }): FacetRef[] {
  const refs: FacetRef[] = [{ kind: "dataset", ref: "organism_records" }];
  if (opt.places.includes("grid01")) refs.push({ kind: "place_kind", ref: "grid01" });
  if (opt.ias) refs.push({ kind: "source_id", ref: "moe_ias_list" });
  return refs;
}
