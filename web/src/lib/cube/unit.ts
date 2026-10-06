/**
 * 単位ラベル（PR-2 design §2.1）。`registry.sqlite`/D1 の `unit` テーブルを引く
 * `@/lib/registry/lookup` の `unitSymbol` の薄い包みで、`lib/cube` の他のモジュール
 * （`envelope.ts`・`observation.ts`）と `serving-diff` の v2 アダプタが同じ1箇所を
 * 呼ぶための入り口。NULL（単位不明。D3 の `unitUnknown` 注記の対象）は呼び出し側が
 * そのまま持ち回る——ここで代わりの文字列を作らない（値も単位表記も変えない）。
 */
import { canonicalOf, unitSymbol } from "@/lib/registry/lookup";

export function unitLabel(unitId: string | null): string | null {
  return unitSymbol(unitId) ?? null;
}

/**
 * 正準単位での読み出し（ADR-0023、Issue #31）。キューブ（`observation_agg`）は出典単位のまま
 * 持ち（値も unit_id も無改変）、読む側がここで正準単位へ寄せる。換算は `unit` レジストリの
 * `canonical_unit_id`/`scale_to_canonical`（線形のみ）。単位不明（null）・未知の単位は
 * 換算せずそのまま返す（推測しない）。出典単位は `sourceUnitId` に残る。
 */
export interface CanonicalValue {
  value: number | null;
  unitId: string | null;
  sourceUnitId: string | null;
}

export function toCanonical(value: number | null, unitId: string | null): CanonicalValue {
  const c = canonicalOf(unitId);
  if (!c) return { value, unitId, sourceUnitId: unitId };
  return { value: value === null ? null : value * c.scale, unitId: c.unitId, sourceUnitId: unitId };
}

/** `canonicalizeCells` が換算する値の列（`CellRow` の値3列）。 */
const VALUE_COLUMNS = ["value", "valueZero", "valueLod"] as const;

/**
 * セル行（`CellRow` 互換）の値列を正準単位へ換算し、`series.unitId` を正準にした新しい行を返す。
 * 元の `series.unitId` は `sourceUnitId` に残す。入力は変更しない。
 */
export function canonicalizeCells<
  T extends { series: { unitId: string | null } } & Record<(typeof VALUE_COLUMNS)[number], number | null>,
>(rows: readonly T[]): (T & { sourceUnitId: string | null })[] {
  return rows.map((r) => {
    const out: T & { sourceUnitId: string | null } = { ...r, sourceUnitId: r.series.unitId };
    for (const col of VALUE_COLUMNS) {
      (out as Record<string, number | null>)[col] = toCanonical(r[col], r.series.unitId).value;
    }
    out.series = { ...r.series, unitId: toCanonical(null, r.series.unitId).unitId };
    return out;
  });
}
