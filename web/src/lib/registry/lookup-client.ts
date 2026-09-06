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

const TABLE_SCOPES = GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "table");
const TABLE_PREFIX_SCOPES = GENERATED_CAVEAT_SCOPE.filter((s) => s.scopeKind === "table_prefix");

/**
 * ツールが触れたテーブル名から、該当する注記を決定論的に引く。
 *
 * **単一の一般規則**（現行の web/src/lib/ai/caveats.ts と同一の結果を返す。
 * scripts/registry/build_caveat.py の docstring に書かれている手順をそのまま実装したもの）:
 *   1. 渡されたテーブルを順に見て、各テーブルについて table / table_prefix のスコープに
 *      一致する行をすべて集める（「このスコープ行がどのテーブル引数にマッチしたか」の
 *      インデックスを記録しておく）。
 *   2. 集めた行を `(priority 降順, マッチしたテーブルの呼び出し順 昇順, sortOrder 昇順)` で
 *      並べる。`priority` は `synthetic`（合成データ由来テーブル）のように「他のどの
 *      テーブルより先に出す」注記を持つ scope 行だけが1で、他は既定の0
 *      （scope_kind に特殊な値を作らず、この優先度専用の列で表す。詳細は
 *      `web/src/db/schema-registry.ts` の `caveatScope` コメント）。
 *   3. caveat の key で重複排除（先勝ち）。
 *
 * `scope_kind === 'table_synthetic'` のような特殊分岐は無い。「synthetic を最優先で
 * 先頭に置く」という以前の挙動は、synthetic のスコープ行だけが priority=1 を持つことから
 * 自然に再現される（レビュー指摘: 以前の特殊分岐は「最初に一致した1テーブルだけ処理して
 * break する」バグを実際に生んだ）。
 */
export function caveatsForTables(tables: readonly string[]): CaveatRef[] {
  const tableOrder = new Map<string, number>();
  tables.forEach((t, i) => {
    if (!tableOrder.has(t)) tableOrder.set(t, i);
  });

  const matches: { scope: GeneratedCaveatScope; order: number }[] = [];
  for (const t of tables) {
    const order = tableOrder.get(t)!;
    for (const s of TABLE_SCOPES) {
      if (s.scopeRef === t) matches.push({ scope: s, order });
    }
    for (const s of TABLE_PREFIX_SCOPES) {
      if (t.startsWith(s.scopeRef)) matches.push({ scope: s, order });
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
    seen.set(scope.caveatKey, { key: scope.caveatKey, text: caveatBody(scope.caveatKey) ?? scope.caveatKey });
  }

  return [...seen.values()];
}

export function caveatKeysForTables(tables: readonly string[]): string[] {
  return caveatsForTables(tables).map((c) => c.key);
}
