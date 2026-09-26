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
import { seriesInfo, type Grain, type SeriesKey } from "./series";
import type { CellRow, CellSpec, Imputation, ZoneYearRow } from "./observation";

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

/** `source_registry` から名前・ライセンスを引く（`resolveProvenance`/`resolveSeriesSetProvenance` が共有）。 */
async function resolveSourceMeta(db: CubeDb, sourceIds: readonly string[]): Promise<Map<string, { name: string | null; license: string | null }>> {
  const metaById = new Map<string, { name: string | null; license: string | null }>();
  if (sourceIds.length === 0) return metaById;
  const params: SqlParam[] = [jsonEachParam(sourceIds)];
  const sql = `
    SELECT source_id, name, license FROM source_registry
    JOIN json_each(?) sk ON sk.value = source_registry.source_id
  `;
  const metaRows = await db.all<{ source_id: string; name: string | null; license: string | null }>(sql, params);
  for (const m of metaRows) metaById.set(m.source_id, { name: m.name, license: m.license });
  return metaById;
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
  const metaById = await resolveSourceMeta(db, knownIds);

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

/**
 * ゾーン集計（`ZoneYearRow`）用の来歴。行が特定の1系列に属さない
 * （`summarizeZone` は `GROUP BY` に系列キーを含めないため、複数系列を渡すと
 * 1つの zone-year 行に合算されうる——`observation.test.ts` の
 * 「mean と point の2系列を混ぜて渡すとゾーン内で合算される」参照）ため、
 * `resolveProvenance`（行ごとに精密な `n_rows` を数える）のような行単位の
 * 帰属はできない。`spec.series` に渡した全系列の出典を列挙し、`n_rows` には
 * 結果全体の行数をそのまま添える（「この結果にはこれらの出典が寄与しうる」
 * という近似。`buildZoneEnvelope` が使う）。
 */
async function resolveSeriesSetProvenance(db: CubeDb, series: readonly SeriesKey[], nRows: number): Promise<EnvelopeProvenance[]> {
  const sourceIdSet = new Set<string | null>();
  for (const s of series) {
    const info = seriesInfo(s);
    const sourceIds = info ? info.sourceIds : [null];
    for (const sourceId of sourceIds) sourceIdSet.add(sourceId);
  }

  const knownIds = [...sourceIdSet].filter((id): id is string => id !== null);
  const metaById = await resolveSourceMeta(db, knownIds);

  const out: EnvelopeProvenance[] = [];
  for (const sourceId of sourceIdSet) {
    const meta = sourceId ? metaById.get(sourceId) : undefined;
    out.push({
      source_id: sourceId,
      name: meta?.name ?? undefined,
      license: meta?.license ?? undefined,
      n_rows: nRows,
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

/**
 * ゾーン単位の封筒（`summarize(...,'zone')` の行、`ZoneYearRow`）。`buildEnvelope`
 * （`CellRow[]` 専用——`place_id`/`period_start`/`series` を行ごとに持つ前提）とは
 * 別関数にした（Issue #48 PR-2 統合後修正A #4）。`spec.imputation==='both'` で
 * `summarize()` を1回呼んだ結果（`avgZero`/`avgLod` を同じ行に持つ。
 * `observation.ts` の `summarizeZone` 参照）を渡す想定——AI の `get_timeseries`
 * （zone スコープ）が `imputation:'zero'`/`'lod'` を2回叩いて JS 側でキーを
 * 合わせていた簡易合成（`envelope: null` のまま）を、この関数1回に置き換える。
 *
 * `coverage.n_places` はゾーンの distinct 数（`ZoneYearRow` は地点個々の
 * `place_id` を持たないため、これがこの結果の「場所の単位」に一番近い）。
 * `provenance` は行単位ではなく `spec.series` 全体から解決する
 * （`resolveSeriesSetProvenance` docstring参照——ゾーン集計は複数系列を
 * 1行に合算しうるため、行ごとの精密な帰属ができない）。
 */
export async function buildZoneEnvelope(
  db: CubeDb,
  spec: CellSpec,
  rows: readonly ZoneYearRow[],
  opt?: { caveats?: CaveatRef[]; truncated?: boolean },
): Promise<Envelope<ZoneYearRow>> {
  const zones = new Set<number>();
  let nCensored = 0;
  let nNotDetected = 0;
  let yFrom: number | null = null;
  let yTo: number | null = null;
  for (const r of rows) {
    zones.add(r.zone);
    nCensored += r.nCensored;
    nNotDetected += r.nNotDetected;
    if (yFrom === null || r.year < yFrom) yFrom = r.year;
    if (yTo === null || r.year > yTo) yTo = r.year;
  }

  const series = spec.series ?? [];
  const unitIds = new Set(series.map((s) => s.unitId ?? null));
  const unit = unitIds.size === 1 ? unitSymbol([...unitIds][0]) : null;

  const columns: EnvelopeColumn[] = [
    { name: "zone", type: "number" },
    { name: "year", type: "number" },
    { name: "value_zero", type: "number", unit, ucum: null },
    { name: "value_lod", type: "number", unit, ucum: null },
  ];

  const provenance = await resolveSeriesSetProvenance(db, series, rows.length);

  return {
    query: { ...spec },
    columns,
    rows: [...rows],
    coverage: {
      n_rows: rows.length,
      n_places: zones.size,
      n_censored: nCensored,
      n_not_detected: nNotDetected,
      period: { start: yFrom !== null ? String(yFrom) : null, end: yTo !== null ? String(yTo) : null, grain: grainLabel(spec.grain) },
      imputation: spec.imputation,
    },
    provenance,
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    caveats: opt?.caveats ?? [],
    truncated: opt?.truncated ?? false,
    spec_version: ENVELOPE_SPEC_VERSION,
  };
}
