/**
 * 単位ラベル（PR-2 design §2.1）。`registry.sqlite`/D1 の `unit` テーブルを引く
 * `@/lib/registry/lookup` の `unitSymbol` の薄い包みで、`lib/cube` の他のモジュール
 * （`envelope.ts`・`observation.ts`）と `serving-diff` の v2 アダプタが同じ1箇所を
 * 呼ぶための入り口。NULL（単位不明。D3 の `unitUnknown` 注記の対象）は呼び出し側が
 * そのまま持ち回る——ここで代わりの文字列を作らない（値も単位表記も変えない）。
 */
import { unitSymbol } from "@/lib/registry/lookup";

export function unitLabel(unitId: string | null): string | null {
  return unitSymbol(unitId) ?? null;
}
