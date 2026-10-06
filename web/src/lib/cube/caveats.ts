/**
 * 注記引き（Issue #48 PR-1b、docs/plans/V2_SERVING_PR1.md §3.6・§6。Issue #35 で語彙を ADR-0013 に寄せた）。
 *
 * facet（`FacetRef` = scope_kind と scope_ref の組。kind は ADR-0013 の6種）で `caveat_scope` を引く。
 * 中身は `registry/caveat_scope.yaml`（宣言）を `scripts/registry/build_caveat.py` が書いた行。
 * scope_ref は ID か `キー=値` の選択式で、照合は完全一致（選択式は解釈しない）。このファイルの
 * ヘルパ（`placeKind`・`unitUnknownOf` 等）が、宣言と同じ文字列を作る。
 * v1 の「テーブル名で引く」経路（`caveatsForTables`）は廃止した。配信表名は `facetsForTables`
 * （dataset として引く）に置き換えた。
 *
 * クライアント安全（`generated-client.ts` だけに依存。`server-only` は付けない）。
 * `./series`/`./sql` からは **型だけ**を import する（`import type` は完全に消える
 * ——`series.ts` がサーバ側の大きい `generated.ts` を読んでいても、型だけの参照なら
 * クライアントバンドルに一切含まれない）。
 *
 * ## 並び（Issue #48 PR-1 統合 §5）
 *
 * `caveatsForFacets` は「順序付きの facet 参照の配列（`FacetRef[]`）」を受け取り、
 * 一般規則
 * (`(priority 降順, 初出順 昇順, sortOrder 昇順)` でソートし、caveat の key で先勝ち
 * 重複排除——`lookup-client.ts` の `resolveCaveatRefs()` を共有し、この並べ替え・
 * 重複排除自体は1箇所にしかない）で注記を引く。**facet の種類ごとにグループ化してから並べる、ということは
 * しない**——「渡された facet 参照の出現順」をそのまま使う。以前の実装は
 * `CaveatFacets`（`datasets`/`themes`/`placeKinds`/`sourceIds`/`tables` に分けたオブジェクト）
 * を受け取り、カテゴリ固定順（datasets→themes→placeKinds→sourceIds→tables）で平坦化して
 * いたため、`web/src/lib/ai/tools.ts` が渡す `["sites","site_var"]` のような「place_kind 系が
 * dataset 系より先に来る」複合で順序がずれていた。
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
import { GENERATED_CAVEAT_SCOPE, type CaveatScopeKind, type GeneratedCaveatScope } from "@/lib/registry/generated-client";
import { resolveCaveatRefs, type CaveatRef, type ScopeMatch } from "@/lib/registry/lookup-client";
import type { SeriesInfo } from "./series";
import type { Scope } from "./sql";

export type { CaveatRef };

/** `caveat_scope.scope_kind`（ADR-0013 の6種。`registry/caveat_scope.yaml` の vocabulary と同じ）。 */
export type FacetKind = CaveatScopeKind;

/** 1つの facet 参照（scope_kind と、宣言と完全一致する scope_ref）。 */
export interface FacetRef {
  readonly kind: FacetKind;
  readonly ref: string;
}

/** `place_kind=<種別>`（`site`/`zone`/`grid01` 等）。 */
export const placeKind = (kind: string): FacetRef => ({ kind: "place", ref: `place_kind=${kind}` });
/** `theme=<variable.theme>`。 */
export const variableTheme = (theme: string): FacetRef => ({ kind: "variable", ref: `theme=${theme}` });
/** 出典の版の集合。`source_id=<出典ID>`。 */
export const sourceEditionOf = (sourceId: string): FacetRef => ({ kind: "source_edition", ref: `source_id=${sourceId}` });
/** 「その変数かつ単位が付かない系列」の集合（unitUnknown の scope）。 */
export const unitUnknownOf = (variableId: string): FacetRef => ({
  kind: "observation_set",
  ref: `variable=${variableId}&unit_id=null`,
});
/**
 * D1 の配信表のうち、表そのものを dataset として注記を持つもの（`registry/caveat_scope.yaml` の
 * `dataset: sites`）。`measurements` 等の dataset 名は論理名であり D1 の表ではないので、
 * 同名の表名を渡されても引かない（v1 の表は DROP 済み。PR-5）。
 */
export const DATASET_TABLES: ReadonlySet<string> = new Set(["sites"]);

/** 配信表名（`sites`）を dataset として引く。それ以外の表名は何にも一致しない。 */
export const facetsForTables = (tables: readonly string[]): FacetRef[] =>
  tables.filter((t) => DATASET_TABLES.has(t)).map((t) => ({ kind: "dataset", ref: t }));

function facetKey(f: FacetRef): string {
  return `${f.kind}\u0000${f.ref}`;
}

/** (scope_kind, scope_ref) → その scope 行。モジュールで1回だけ作る索引（完全一致の引き）。 */
const SCOPES_BY_FACET = new Map<string, GeneratedCaveatScope[]>();
for (const s of GENERATED_CAVEAT_SCOPE) {
  const k = facetKey({ kind: s.scopeKind, ref: s.scopeRef });
  const list = SCOPES_BY_FACET.get(k);
  if (list) list.push(s);
  else SCOPES_BY_FACET.set(k, [s]);
}

/**
 * facet の並び（`FacetRef[]`。渡された順序をそのまま使う）から、該当する注記を
 * 決定論的に引く。
 *
 * 並び: `(priority 降順, facet の初出順 昇順, sortOrder 昇順)` でソートし、caveat の
 * key で先勝ち重複排除する（`web/src/lib/registry/lookup-client.ts` の `resolveCaveatRefs`。
 * 詳細は `scripts/registry/build_caveat.py` の docstring参照）。
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
    for (const s of SCOPES_BY_FACET.get(facetKey(f)) ?? []) matches.push({ scope: s, order: idx });
  }

  return resolveCaveatRefs(matches);
}

export function caveatKeysForFacets(facets: readonly FacetRef[]): string[] {
  return caveatsForFacets(facets).map((c) => c.key);
}

/**
 * 変数単位（`variable:<variable_id>`。例: 流量の逆流 flowTidalBackflow、透明度の aboveLod）の注記。
 * 画面の注意書き欄に出す口で、`caveatsForFacets` と同じ索引・同じ並べ替え・重複排除規則を使う。
 */
export function variableCaveats(variableId: string): CaveatRef[] {
  return caveatsForFacets([{ kind: "variable", ref: variableId }]);
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
 * 撤去・`variable` facet を追加。Issue #35 で語彙を ADR-0013 に寄せた）。系列を順に見て、
 * 各系列について dataset → variable（`theme=`）→ source_edition（`source_id=`、複数）→
 * variable（`variableId`）→ observation_set（`variable=<id>&unit_id=null`。**`unitId` が null の
 * 系列だけ**）の順に積む。最後に scope から決まる place（`place_kind=`）を1つ積む
 * （`'zone'` スコープだけ `zone`、それ以外（site/water/places/all_sites）は `site`——
 * `registry/caveat_scope.yaml` の宣言どおり）。
 *
 * **変数単位の注記**（`hydro.flow` の逆流 flowTidalBackflow、`water.transparency` の
 * aboveLod）は `variable:<variable_id>` で、単位の有無によらずその変数の全系列に付く。
 * 一方 `unitUnknown` は **`unitId===null` の系列だけ**（`variable=<id>&unit_id=null`）。
 * variable_id 単位で無条件に付けると、単位が判明している系列（`water.water_temp` の一部等、
 * 同じ variable_id に単位の分かる実データが混在する）にまで「単位不明」が誤って付く。
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
  // 同じ (kind, ref) は初出だけを残す（Map は挿入順）。
  const refs = new Map<string, FacetRef>();
  const push = (f: FacetRef) => {
    const k = facetKey(f);
    if (!refs.has(k)) refs.set(k, f);
  };

  for (const s of series) {
    push({ kind: "dataset", ref: s.dataset });
    if (s.theme !== null) push(variableTheme(s.theme));
    for (const id of s.sourceIds) {
      if (id !== null) push(sourceEditionOf(id));
    }
    // 変数単位の注記（hydro.flow の逆流など）は単位の有無によらず付く。
    push({ kind: "variable", ref: s.variableId });
    // 単位が付かない系列だけ unitUnknown（単位が判明している系列に誤って付けない）。
    if (s.unitId === null) push(unitUnknownOf(s.variableId));
  }

  push(placeKind(scope.kind === "zone" ? "zone" : "site"));

  return [...refs.values()];
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
  if (opt.places.includes("grid01")) refs.push(placeKind("grid01"));
  if (opt.ias) refs.push(sourceEditionOf("moe_ias_list"));
  return refs;
}
