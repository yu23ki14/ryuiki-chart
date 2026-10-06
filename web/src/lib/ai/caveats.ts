import { GENERATED_CAVEAT_SCOPE } from "@/lib/registry/generated-client";
import { tryCaveatBody } from "@/lib/registry/lookup-client";

/**
 * ツール結果の注記キー -> 本文。モデルに注意書きを書かせない（書かせると省略されうる）ため、
 * 注記は `web/src/lib/cube/caveats.ts`（`caveatKeysForFacets`。レジストリの `caveat_scope` 由来）が
 * 決定論的に引き、ツール結果にはキーだけを載せる（本文はシステムプロンプトが持っている）。
 * 本文への引き直しは証跡カード（クライアント）が `caveatText` でやるので、server-only にしていない。
 */

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
