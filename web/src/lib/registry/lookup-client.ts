/**
 * `generated-client.ts`（クライアント安全・小さいデータだけ）の上に立つ、
 * caveat・和名・短縮表示名の参照ヘルパ。
 *
 * `server-only` は付けない。13ファイルの画面側（うち証跡カードはクライアント
 * コンポーネント）と `web/src/lib/ai/caveats.ts` / `prompt.ts` の両方から同期で呼ばれる
 * （旧 domain.ts が薄いラッパとして持っていた口を、Phase B で撤去して
 * ここへ一本化した。docs/plans/PHASE_B_INTAKE.md #6）。
 *
 * variable / unit の生テーブルにはここでは一切触れない（そちらは `./lookup.ts`。
 * D1 から動的に読む必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * `./index.ts`（server-only）を使うこと）。
 *
 * 分離の理由（code-review #4）: 以前は `./lookup.ts` 1本に caveat 関連もまとめて
 * 同居しており、caveatBody() だけを使いたいクライアントコンポーネントも、
 * variable(85件)・variable_alias(117件) の生テーブルをモジュール丸ごと import する
 * ことで一緒に bundle へ引き込んでいた（+43.5KB）。
 *
 * docs/plans/PHASE_A.md §A-7 / §A-8。
 */
import {
  GENERATED_CAVEATS,
  GENERATED_CAVEAT_SCOPE,
  NAME_JA,
  REGION_TIME,
  VARIABLE_SHORT,
  type CaveatKey,
  type GeneratedCaveat,
  type GeneratedCaveatScope,
} from "./generated-client";

const caveatByKey = new Map<string, GeneratedCaveat>(GENERATED_CAVEATS.map((c) => [c.key, c]));

/**
 * 動的な（コンパイル時に既知でない）キーでの生の引き。無ければ undefined。
 * `caveat_scope` 由来の文字列キー（`caveatsForTables` / `web/src/lib/ai/caveats.ts`）専用。
 * 既知のキーを直書きする画面・prompt.ts は代わりに `caveatBody` を使うこと。
 */
export function tryCaveatBody(key: string): string | undefined {
  return caveatByKey.get(key)?.bodyJa;
}

/**
 * 既知の caveat キー（`CaveatKey`。build-registry-ts.mjs が生成する union、16件）専用の引き。
 * 存在しないキーは呼び出し側でコンパイルエラーになる（旧 domain.ts の DATA_CAVEATS /
 * BIOTA_CAVEATS 経由の mustCaveatBody() は実行時例外だった。docs/plans/PHASE_B_INTAKE.md #6）。
 * 画面・prompt.ts はこれを直接呼ぶ。
 *
 * ここで投げる例外は、CaveatKey の生成元（caveat テーブル）と GENERATED_CAVEATS の生成元が
 * 同じクエリである限り届かない防御であり、正常経路では起きない。
 */
export function caveatBody(key: CaveatKey): string {
  const body = tryCaveatBody(key);
  if (body === undefined) {
    throw new Error(`registry/caveat.yaml に "${key}" が無い（caveatBody が参照している）`);
  }
  return body;
}

export function allCaveats(): readonly GeneratedCaveat[] {
  return GENERATED_CAVEATS;
}

/** 水質項目の短い表示名。無ければそのまま返す（旧 domain.ts の shortVariable）。 */
export function shortVariable(v: string): string {
  return VARIABLE_SHORT[v] ?? v;
}

/**
 * 和名（本デモで人が確認した63件、`NAME_JA`）。無ければ英名、それも無ければ学名を返す
 * （旧 domain.ts の speciesLabel。organism_records に和名は入っておらず、taxa の和名を
 * 学名で機械結合すると別地域の個体群の名前が付く事故があるため、代表種だけ人が確認した
 * 和名をここで引く）。
 *
 * 第2引数 `label`（Issue #48 PR-3b・D4）は API が返す表示名（`lib/cube` の `speciesLabels`。
 * taxon 由来の和名→英名の順で選んだもの）。旧来の英名もそのまま渡せる。`NAME_JA` が先に勝つ
 * 規則は変えない。
 */
export function speciesLabel(binom: string, label?: string | null): string {
  const ja = NAME_JA[binom];
  if (ja) return ja;
  return label || binom;
}

/* ------------------------------------------------------------------ */
/* 注記の解決（`web/src/lib/cube/caveats.ts` の `caveatsForFacets` が使う共通規則） */
/* ------------------------------------------------------------------ */

export interface CaveatRef {
  key: string;
  text: string;
}

/** スコープ行1つと、それが一致した参照（テーブル名・facet 参照）の初出順。 */
export interface ScopeMatch {
  scope: GeneratedCaveatScope;
  order: number;
}

/**
 * `matches`（スコープ行＋その参照の初出順）から、決定論的な注記の並びを作る
 * （`caveatsForTables` と `web/src/lib/cube/caveats.ts` の `caveatsForFacets` が
 * 使う一般規則。以前は同じソート＋重複排除がここと `caveatsForFacets` の
 * 2箇所に複製されていた）:
 *   1. `(priority 降順, order 昇順, sortOrder 昇順)` で並べる。`priority` は
 *      `synthetic`（合成データ由来）のように「他のどの参照より先に出す」注記を
 *      持つ scope 行だけが1で、他は既定の0（scope_kind に特殊な値を作らず、
 *      この優先度専用の列で表す。詳細は `web/src/db/schema-registry.ts` の
 *      `caveatScope` コメント）。
 *   2. caveat の key で重複排除（先勝ち）。
 */
export function resolveCaveatRefs(matches: readonly ScopeMatch[]): CaveatRef[] {
  const sorted = [...matches].sort((a, b) => {
    if (a.scope.priority !== b.scope.priority) return b.scope.priority - a.scope.priority;
    if (a.order !== b.order) return a.order - b.order;
    return a.scope.sortOrder - b.scope.sortOrder;
  });

  const seen = new Map<string, CaveatRef>();
  for (const { scope } of sorted) {
    if (seen.has(scope.caveatKey)) continue;
    seen.set(scope.caveatKey, { key: scope.caveatKey, text: tryCaveatBody(scope.caveatKey) ?? scope.caveatKey });
  }

  return [...seen.values()];
}

/**
 * 変数単位（scope_kind='variable'、scope_ref=variable_id）の注記の本文（画面の変数説明の下に出す。
 * 例: 流量の感潮域の逆流 flowTidalBackflow）。`theme=` 等の選択式は対象外。
 * 画面ごとの個別対応を書かず、変数の説明に注記をまとめて添えるための口。
 */
export function variableCaveatBodies(variableId: string): string[] {
  return GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "variable" && s.scopeRef === variableId)
    .sort((a, b) => a.sortOrder - b.sortOrder)
    .map((s) => tryCaveatBody(s.caveatKey) ?? s.caveatKey);
}

/**
 * 画面の変数説明（`VARIABLE_LABEL[id].note`）に、その変数に掛かる注記（`variableCaveatBodies`）を
 * 添えた文。どちらも無ければ undefined（呼び出し側が既定の文を出す）。
 */
export function variableNote(variableId: string): string | undefined {
  const parts = [VARIABLE_LABEL[variableId]?.note, ...variableCaveatBodies(variableId)].filter((x): x is string => !!x);
  return parts.length > 0 ? parts.join(" ") : undefined;
}

// ---------------------------------------------------------------------------
// region の時刻帯（Issue #32-3、ADR-0024）
// ---------------------------------------------------------------------------

export interface RegionTimeZone {
  /** IANA 時刻帯名（例 `Asia/Tokyo`）。 */
  tzName: string;
  /** UTC オフセット（`+HH:MM`/`-HH:MM`）。 */
  utcOffset: string;
}

let regionTimeById: Map<string, (typeof REGION_TIME)[number]> | undefined;

/**
 * `region_id`（`jp-14` 等）の時刻帯を引く（応答封筒〔ADR-0014〕・時刻の表示が使う口）。
 * 観測の `period_start`/`period_end` は時刻帯なしのローカル時刻（ADR-0024）で、その「ローカル」が
 * どの時刻帯かはここで決まる。**未知の region は例外にする**（黙って JST に倒さない。
 * registry/region.yaml に足し忘れたまま新しい地域のデータを出すと、ここで気づける）。
 */
export function regionTimeZone(regionId: string): RegionTimeZone {
  regionTimeById ??= new Map(REGION_TIME.map((r) => [r.regionId, r]));
  const r = regionTimeById.get(regionId);
  if (!r) {
    throw new Error(`regionTimeZone: region_id=${JSON.stringify(regionId)} は registry/region.yaml に無い`);
  }
  return { tzName: r.tzName, utcOffset: r.utcOffset };
}
