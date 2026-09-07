import { GENERATED_CAVEAT_SCOPE } from "@/lib/registry/generated-client";
import { caveatBody, caveatKeysForTables, caveatsForTables, type CaveatRef } from "@/lib/registry/lookup-client";

/**
 * ツールが触れたテーブル名から、該当する注記を決定論的に引く。
 *
 * 中身は `web/src/lib/registry/lookup.ts`（レジストリの `caveat` / `caveat_scope` 由来）に
 * 移した（docs/plans/PHASE_A.md §A-7）。以前はここに `domain.ts` の `DATA_CAVEATS` /
 * `BIOTA_CAVEATS` とテーブル→注記のマッピングを直書きしていたが、
 * 同じ情報がレジストリ（`registry/caveat.yaml` → `data/db/registry.sqlite`）に
 * 一級のデータとして載ったので、そちらを正とする。
 *
 * このファイル自体が持つ役割は変わっていない: モデルに注意書きを書かせない
 * （書かせると省略されうる）ための決定論的な参照点であること、
 * `caveatsForTables` の戻り値の形・順序・重複排除規則（`caveats.test.ts` の34ケース）を
 * 1つも変えないこと。
 *
 * server-only にしていないのも変わらず意図的。ツール結果には注記の「キー」だけを載せ
 * （本文はシステムプロンプトが持っているのでモデルは二重に受け取らなくてよい）、
 * 本文への引き直しは証跡カード（クライアント）が caveatText でやる。
 * `lookup.ts` は generated.ts（クライアント安全・同期）だけを見ているので、
 * このファイルもクライアントから import して問題ない。
 */

export type { CaveatRef };
export { caveatsForTables, caveatKeysForTables };

/**
 * 全注記のキー -> 本文。証跡カード（クライアント）とシステムプロンプトの両方が引く。
 *
 * 対象はテーブルに紐づく注記（`caveat_scope` に table/table_prefix/table_synthetic の
 * 行があるもの）だけ。`fishClass` / `inatBackfill` はテーブル→注記のマッピングに
 * 一度も登場しない（`BiotaExplorer.tsx` が `domain.ts` の `BIOTA_CAVEATS` から直接引いている）ため、
 * 以前の実装と同じくここには含まれない。
 */
export const CAVEAT_TEXT: Record<string, string> = Object.fromEntries(
  [...new Set(GENERATED_CAVEAT_SCOPE.map((s) => s.caveatKey))].map((key) => [key, caveatBody(key) ?? key]),
);

export function caveatText(key: string): string {
  return CAVEAT_TEXT[key] ?? key;
}
