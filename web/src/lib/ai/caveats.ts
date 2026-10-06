import { GENERATED_CAVEAT_SCOPE } from "@/lib/registry/generated-client";
import { tryCaveatBody, type CaveatRef } from "@/lib/registry/lookup-client";
import { caveatsForFacets, facetsForTables } from "@/lib/cube/caveats";

/**
 * ツールが触れたテーブル名から、該当する注記を決定論的に引く（モデルに注意書きを書かせない——
 * 書かせると省略されうる——ための決定論的な参照点）。
 *
 * 配信表名は dataset として引く（`facetsForTables`。Issue #35 で v1 の table/table_prefix スコープを
 * 廃止し、`registry/caveat_scope.yaml` の dataset に一本化した。今 dataset を持つ配信表は `sites`）。
 * 中身は `web/src/lib/cube/caveats.ts`（レジストリの `caveat` / `caveat_scope` 由来）。
 *
 * server-only にしていないのは意図的。ツール結果には注記の「キー」だけを載せ
 * （本文はシステムプロンプトが持っているのでモデルは二重に受け取らなくてよい）、
 * 本文への引き直しは証跡カード（クライアント）が caveatText でやる。
 */

export type { CaveatRef };

export function caveatsForTables(tables: readonly string[]): CaveatRef[] {
  return caveatsForFacets(facetsForTables(tables));
}

export function caveatKeysForTables(tables: readonly string[]): string[] {
  return caveatsForTables(tables).map((c) => c.key);
}

/**
 * 全注記のキー -> 本文。証跡カード（クライアント）とシステムプロンプトの両方が引く。
 *
 * 対象は `caveat_scope` に行があるものだけ。`fishClass` / `inatBackfill` は
 * `registry/caveat_scope.yaml` の `unscoped`（意図して付けない）で、`BiotaExplorer.tsx` が
 * `caveatBody("fishClass"/"inatBackfill")` を直接引くため、ここには含まれない。
 */
export const CAVEAT_TEXT: Record<string, string> = Object.fromEntries(
  [...new Set(GENERATED_CAVEAT_SCOPE.map((s) => s.caveatKey))].map((key) => [key, tryCaveatBody(key) ?? key]),
);

export function caveatText(key: string): string {
  return CAVEAT_TEXT[key] ?? key;
}
