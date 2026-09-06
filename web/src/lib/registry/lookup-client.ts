/**
 * `generated-client.ts`（クライアント安全・caveat / caveat_scope だけの小さいデータ）の
 * 上に立つ、caveat 専用の参照ヘルパ。
 *
 * `server-only` は付けない。`domain.ts`（13ファイルの利用側があり、うち証跡カードは
 * クライアントコンポーネント）と `web/src/lib/ai/caveats.ts` の両方から同期で呼ばれる。
 *
 * variable / unit の生テーブルにはここでは一切触れない（そちらは `./lookup.ts`。
 * D1 から動的に読む必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * `./index.ts`（server-only）を使うこと）。
 *
 * 分離の理由（code-review #4）: 以前は `./lookup.ts` 1本に caveat 関連もまとめて
 * 同居しており、caveatBody() だけを使いたいクライアントコンポーネント（domain.ts /
 * 証跡カード）も、variable(85件)・variable_alias(117件) の生テーブルをモジュール
 * 丸ごと import することで一緒に bundle へ引き込んでいた（+43.5KB）。
 *
 * docs/plans/PHASE_A.md §A-7 / §A-8。
 */
import {
  GENERATED_CAVEATS,
  GENERATED_CAVEAT_SCOPE,
  type GeneratedCaveat,
  type GeneratedCaveatScope,
} from "./generated-client";

const caveatByKey = new Map<string, GeneratedCaveat>(GENERATED_CAVEATS.map((c) => [c.key, c]));

export function caveatBody(key: string): string | undefined {
  return caveatByKey.get(key)?.bodyJa;
}

export function allCaveats(): readonly GeneratedCaveat[] {
  return GENERATED_CAVEATS;
}

/* ------------------------------------------------------------------ */
/* caveatsForTables（web/src/lib/ai/caveats.ts の中身。ここに置いて、
   caveats.ts は薄いラッパにする） */
/* ------------------------------------------------------------------ */

export interface CaveatRef {
  key: string;
  text: string;
}

const SCOPE_BY_KIND_REF = new Map<string, GeneratedCaveatScope[]>();
for (const s of GENERATED_CAVEAT_SCOPE) {
  const k = `${s.scopeKind}	${s.scopeRef}`;
  const list = SCOPE_BY_KIND_REF.get(k) ?? [];
  list.push(s);
  SCOPE_BY_KIND_REF.set(k, list);
}

const TABLE_PREFIX_SCOPES = GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "table_prefix");
const SYNTHETIC_TABLE_REFS = new Set(
  GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "table_synthetic").map((s) => s.scopeRef),
);

function caveatRefsFor(scopeKind: GeneratedCaveatScope["scopeKind"], scopeRef: string): CaveatRef[] {
  const rows = SCOPE_BY_KIND_REF.get(`${scopeKind}	${scopeRef}`) ?? [];
  return [...rows]
    .sort((a, b) => a.sortOrder - b.sortOrder)
    .map((r) => ({ key: r.caveatKey, text: caveatBody(r.caveatKey) ?? r.caveatKey }));
}

/**
 * ツールが触れたテーブル名から、該当する注記を決定論的に引く。
 *
 * 順序規則（現行の web/src/lib/ai/caveats.ts と同一。scripts/registry/build_caveat.py の
 * docstring に「caveat_scope から caveatsForTables() の順序を復元する方法」として書かれている
 * 手順をそのまま実装したもの）:
 *   1. 渡されたテーブルのどれかが table_synthetic のスコープに一致すれば、対応する
 *      caveat（synthetic）を最優先で先頭に置く。**一致したテーブルは全部見る**
 *      （レビュー指摘: 以前は最初に一致した1件だけを足して break していたため、
 *      複数の synthetic テーブルが別々の注記キーを持つようになった時点で
 *      2つ目以降が黙って失われる欠陥があった）。
 *   2. 渡されたテーブルを順に見て、各テーブルについて table / table_prefix のスコープに
 *      一致する行を sortOrder 昇順で足す。
 *   3. caveat の key で重複排除（先勝ち）。
 */
export function caveatsForTables(tables: readonly string[]): CaveatRef[] {
  const seen = new Map<string, CaveatRef>();
  const add = (refs: CaveatRef[]) => {
    for (const r of refs) if (!seen.has(r.key)) seen.set(r.key, r);
  };

  if (tables.some((t) => SYNTHETIC_TABLE_REFS.has(t))) {
    for (const t of tables) {
      if (SYNTHETIC_TABLE_REFS.has(t)) {
        add(caveatRefsFor("table_synthetic", t));
      }
    }
  }

  for (const t of tables) {
    add(caveatRefsFor("table", t));
    for (const prefixScope of TABLE_PREFIX_SCOPES) {
      if (t.startsWith(prefixScope.scopeRef)) {
        add(caveatRefsFor("table_prefix", prefixScope.scopeRef));
      }
    }
  }

  return [...seen.values()];
}

export function caveatKeysForTables(tables: readonly string[]): string[] {
  return caveatsForTables(tables).map((c) => c.key);
}
