/**
 * 応答エンベロープ（ADR-0014）。design §3.5。
 *
 * caveats は呼び出し側が `CaveatRef[]` を渡す形にしてあり、`envelope.ts` 自身は
 * caveat の解決ロジック（1b が作る `lib/cube/caveats.ts`）に依存しない
 * （オーナー決定: 「envelope.ts が caveats を要るなら CaveatRef[] を引数で受ける形にして
 * 依存させない」）。`CaveatRef` 型自体は既存の `@/lib/registry/lookup-client`（1a/1b どちらの
 * 新規ファイルでもない、既存の共有モジュール）からの型 import のみ。
 *
 * 消費者は PR-2（AI ツール）。PR-1 はテスト（フィクスチャ）だけで検証する。
 */
import type { CaveatRef } from "@/lib/registry/lookup-client";
import { unitSymbol } from "@/lib/registry/lookup";
import type { CubeDb, SqlParam } from "./db";
import { jsonEachParam } from "./sql";
import { seriesInfo, type Grain } from "./series";
import type { CellRow, CellSpec, Imputation } from "./observation";

export const ENVELOPE_SPEC_VERSION = "cube-envelope@1";

export interface EnvelopeColumn {
  name: string;
  type: "number" | "string";
  unit?: string | null;
  ucum?: string | null;
}

export interface EnvelopeCoverage {
  n_rows: number;
  n_places: number;
  n_censored: number;
  n_not_detected: number;
  period: { start: string | null; end: string | null; grain: string };
  imputation: Imputation;
}

export interface EnvelopeProvenance {
  source_id: string | null;
  name?: string;
  license?: string;
  n_rows: number;
}

export interface EnvelopeExcluded {
  by_license: number;
  by_embargo: number;
  reasons: string[];
}

export interface Envelope<R> {
  query: Record<string, unknown>;
  columns: EnvelopeColumn[];
  rows: R[];
  coverage: EnvelopeCoverage;
  provenance: EnvelopeProvenance[];
  excluded: EnvelopeExcluded;
  caveats: CaveatRef[];
  truncated: boolean;
  spec_version: string;
}

function resolveUnitColumn(rows: readonly CellRow[]): { unit: string | null; ucum: string | null } {
  const unitIds = new Set(rows.map((r) => r.series.unitId ?? null));
  if (unitIds.size !== 1) return { unit: null, ucum: null };
  const [unitId] = [...unitIds];
  return { unit: unitSymbol(unitId), ucum: null };
}

async function resolveProvenance(db: CubeDb, rows: readonly CellRow[]): Promise<EnvelopeProvenance[]> {
  const nRowsBySource = new Map<string | null, number>();
  for (const r of rows) {
    const info = seriesInfo(r.series);
    const sourceIds = info ? info.sourceIds : [null];
    for (const sourceId of sourceIds) {
      nRowsBySource.set(sourceId, (nRowsBySource.get(sourceId) ?? 0) + 1);
    }
  }

  const knownIds = [...nRowsBySource.keys()].filter((id): id is string => id !== null);
  const metaById = new Map<string, { name: string | null; license: string | null }>();
  if (knownIds.length > 0) {
    const params: SqlParam[] = [jsonEachParam(knownIds)];
    const sql = `
      SELECT source_id, name, license FROM source_registry
      JOIN json_each(?) sk ON sk.value = source_registry.source_id
    `;
    const metaRows = await db.all<{ source_id: string; name: string | null; license: string | null }>(sql, params);
    for (const m of metaRows) metaById.set(m.source_id, { name: m.name, license: m.license });
  }

  const out: EnvelopeProvenance[] = [];
  for (const [sourceId, n_rows] of nRowsBySource) {
    const meta = sourceId ? metaById.get(sourceId) : undefined;
    out.push({
      source_id: sourceId,
      name: meta?.name ?? undefined,
      license: meta?.license ?? undefined,
      n_rows,
    });
  }
  return out;
}

function grainLabel(grain: Grain | Grain[]): string {
  return Array.isArray(grain) ? grain.join(",") : grain;
}

/**
 * `queryCells()` が返した行を ADR-0014 のエンベロープ形に包む。DB へは
 * `source_registry`（来歴）だけを追加で引く。
 */
export async function buildEnvelope<R extends CellRow>(
  db: CubeDb,
  spec: CellSpec,
  rows: R[],
  opt?: { caveats?: CaveatRef[]; truncated?: boolean },
): Promise<Envelope<R>> {
  const placeIds = new Set<string>();
  let nCensored = 0;
  let nNotDetected = 0;
  let periodStart: string | null = null;
  let periodEnd: string | null = null;
  for (const r of rows) {
    placeIds.add(r.placeId);
    nCensored += r.nCensored;
    nNotDetected += r.nNotDetected;
    if (periodStart === null || r.periodStart < periodStart) periodStart = r.periodStart;
    if (periodEnd === null || r.periodStart > periodEnd) periodEnd = r.periodStart;
  }
  const { unit, ucum } = resolveUnitColumn(rows);

  // `imputation:'both'` は `value_zero`/`value_lod` を単位付きで両方の列にする
  // （design §2.1「`imputation:'both'` のとき columns に value_zero/value_lod を
  // 単位付きで両方」）。`zero`/`lod` はこれまでどおり単一の `value` 列（PR-1 の
  // 形をそのまま維持——既存の呼び出し側・テストを壊さない）。
  const columns: EnvelopeColumn[] =
    spec.imputation === "both"
      ? [
          { name: "place_id", type: "string" },
          { name: "period_start", type: "string" },
          { name: "value_zero", type: "number", unit, ucum },
          { name: "value_lod", type: "number", unit, ucum },
        ]
      : [
          { name: "place_id", type: "string" },
          { name: "period_start", type: "string" },
          { name: "value", type: "number", unit, ucum },
        ];

  const provenance = await resolveProvenance(db, rows);

  return {
    query: { ...spec },
    columns,
    rows,
    coverage: {
      n_rows: rows.length,
      n_places: placeIds.size,
      n_censored: nCensored,
      n_not_detected: nNotDetected,
      period: { start: periodStart, end: periodEnd, grain: grainLabel(spec.grain) },
      imputation: spec.imputation,
    },
    provenance,
    // `synthetic_included` は PR-2 で撤去した（D2。b03 が合成データを除くため、
    // `observation_agg` に合成データはもう載らない——design §0-2・§2.1「envelope.buildEnvelope」）。
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    caveats: opt?.caveats ?? [],
    truncated: opt?.truncated ?? false,
    spec_version: ENVELOPE_SPEC_VERSION,
  };
}
