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
import { regionTimeZone } from "@/lib/registry/lookup-client";
import { GENERATED_CAVEATS } from "@/lib/registry/generated-client";
import { unitSymbol } from "@/lib/registry/lookup";
import {
  dedupeSourceRefs,
  DEFAULT_REGION_ID,
  seriesSourceRefs,
  sourceCitation,
  type SourceCitation,
  type UpdateModeOrUndeclared,
} from "./source-meta";
import { seriesInfo, type Grain, type SeriesKey, type SourceRef } from "./series";
import type { CellRow, CellSpec, Imputation, ZoneYearRow } from "./observation";

/**
 * `cube-envelope@2`（Issue #40 Phase D）。@1 からの差分は加算のみ:
 * provenance に source_edition_id / fetched_at / update_mode / age_days / license_* / attribution、
 * coverage に oldest/newest_fetched_at、トップに cite_as / as_of / time_zone、
 * caveats に severity / kind。鮮度の閾値判定（stale）は持たない（ADR-0020）。
 */
export const ENVELOPE_SPEC_VERSION = "cube-envelope@2";

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
  /** この結果が引いた出典の取得日（ISO 8601、region の時刻帯つき）の最古・最新。全て取得日不明なら null。 */
  oldest_fetched_at: string | null;
  newest_fetched_at: string | null;
}

export interface EnvelopeProvenance {
  source_id: string;
  name?: string;
  license?: string;
  source_edition_id?: string;
  fetched_at?: string;
  /** 宣言が無い出典は `"undeclared"`（推測で埋めない）。 */
  update_mode?: UpdateModeOrUndeclared;
  age_days?: number;
  license_id?: string;
  license_class?: string;
  /** 出典の旗。出力を絞る根拠にしない（ADR-0028）。 */
  redistributable?: boolean;
  attribution?: string;
  /** この出典から引いた行数。数えていない（出典の一覧だけを載せる応答）ときは null（0 と書かない）。 */
  n_rows: number | null;
}

/** 注記。本文は registry（`caveat.yaml`）のもので、severity / kind もそのまま載せる（分類は #35 の責務）。 */
export interface EnvelopeCaveat extends CaveatRef {
  severity: string | null;
  kind: string | null;
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
  caveats: EnvelopeCaveat[];
  truncated: boolean;
  spec_version: string;
  /** 「出典名（取得日）」の並びと本サービス名。出典の引用にそのまま使える文字列。 */
  cite_as: string;
  /** `age_days` を数えた時点（ISO 8601、UTC）。 */
  as_of: string;
  /** `fetched_at`・`as_of` の時刻帯（`regionTimeZone()`）。 */
  time_zone: { region_id: string; tz_name: string; utc_offset: string };
}

export interface EnvelopeOpt {
  caveats?: CaveatRef[];
  truncated?: boolean;
  /** `age_days`・`as_of` の基準（テスト用。既定は現在時刻）。 */
  now?: Date;
  /** 時刻帯を決める region（既定 `DEFAULT_REGION_ID`）。 */
  regionId?: string;
}

function resolveUnitColumn(rows: readonly CellRow[]): { unit: string | null; ucum: string | null } {
  const unitIds = new Set(rows.map((r) => r.series.unitId ?? null));
  if (unitIds.size !== 1) return { unit: null, ucum: null };
  const [unitId] = [...unitIds];
  return { unit: unitSymbol(unitId), ucum: null };
}

/** 出典 ID 1件分の provenance 行（registry の生成物から引く。D1 は引かない）。 */
function provenanceRow(ref: SourceRef, nRows: number | null, now: Date, regionId: string): EnvelopeProvenance {
  const { sourceId, editionKey } = ref;
  const c: SourceCitation = sourceCitation(sourceId, { now, regionId, editionKey });
  return {
    source_id: sourceId,
    name: c.name ?? undefined,
    license: c.license ?? undefined,
    source_edition_id: c.source_edition_id ?? undefined,
    fetched_at: c.fetched_at ?? undefined,
    update_mode: c.update_mode,
    age_days: c.age_days ?? undefined,
    license_id: c.license_id ?? undefined,
    license_class: c.license_class ?? undefined,
    redistributable: c.redistributable ?? undefined,
    attribution: c.attribution ?? undefined,
    n_rows: nRows,
  };
}

/**
 * `variable_alias.source_id IS NULL` は「出典未記録＝合成」の alias（`series.ts`）。合成データは
 * b03 が除外していて `observation_agg` に載らない（設計 §0・ADR-0028 の不変条件 1）ので、
 * その alias を provenance の行にしない（載せると存在しない合成データが寄与したように読める）。
 * 除外は provenance の行だけで、`rows` や `excluded` には触れない。
 */
function resolveProvenance(rows: readonly CellRow[], now: Date, regionId: string): EnvelopeProvenance[] {
  const counted = new Map<string, { ref: SourceRef; n: number }>();
  for (const r of rows) {
    for (const ref of seriesInfo(r.series)?.sourceRefs ?? []) {
      const key = `${ref.sourceId}\u0000${ref.editionKey ?? ""}`;
      const cur = counted.get(key) ?? { ref, n: 0 };
      cur.n += 1;
      counted.set(key, cur);
    }
  }
  return [...counted.values()].map(({ ref, n }) => provenanceRow(ref, n, now, regionId));
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
function resolveSeriesSetProvenance(series: readonly SeriesKey[], nRows: number, now: Date, regionId: string): EnvelopeProvenance[] {
  return seriesSourceRefs(series).map((ref) => provenanceRow(ref, nRows, now, regionId));
}

/** provenance の取得日の最古・最新（文字列比較。同じ時刻帯のオフセット付きなので辞書順が時刻順）。 */
function fetchedRange(provenance: readonly EnvelopeProvenance[]): { oldest: string | null; newest: string | null } {
  let oldest: string | null = null;
  let newest: string | null = null;
  for (const p of provenance) {
    if (!p.fetched_at) continue;
    if (oldest === null || p.fetched_at < oldest) oldest = p.fetched_at;
    if (newest === null || p.fetched_at > newest) newest = p.fetched_at;
  }
  return { oldest, newest };
}

const CAVEAT_META = new Map(GENERATED_CAVEATS.map((c) => [c.key, c]));

/** 注記に registry の severity / kind を添える。registry に無いキーは null（黙って作らない）。 */
function withCaveatMeta(caveats: readonly CaveatRef[]): EnvelopeCaveat[] {
  return caveats.map((c) => ({ ...c, severity: CAVEAT_META.get(c.key)?.severity ?? null, kind: CAVEAT_META.get(c.key)?.kind ?? null }));
}

/** 「流域カルテ。出典: A（取得 2026-08-30）、B（取得日不明）」。URL はホスト未決のため載せない。 */
function citeAs(provenance: readonly EnvelopeProvenance[]): string {
  const parts = provenance
    .map((p) => `${p.name ?? p.source_id}（${p.fetched_at ? `取得 ${p.fetched_at.slice(0, 10)}` : "取得日不明"}）`);
  return parts.length ? `流域カルテ。出典: ${parts.join("、")}` : "流域カルテ";
}

function envelopeMeta(provenance: readonly EnvelopeProvenance[], now: Date, regionId: string) {
  const tz = regionTimeZone(regionId);
  const { oldest, newest } = fetchedRange(provenance);
  return {
    range: { oldest_fetched_at: oldest, newest_fetched_at: newest },
    cite_as: citeAs(provenance),
    as_of: now.toISOString(),
    time_zone: { region_id: regionId, tz_name: tz.tzName, utc_offset: tz.utcOffset },
  };
}

function grainLabel(grain: Grain | Grain[]): string {
  return Array.isArray(grain) ? grain.join(",") : grain;
}

/**
 * `queryCells()` が返した行を ADR-0014 のエンベロープ形に包む。DB は引かない
 * （来歴・鮮度は registry の生成物から。`source-meta.ts`）。
 */
export function buildEnvelope<R extends CellRow>(spec: CellSpec, rows: R[], opt?: EnvelopeOpt): Envelope<R> {
  const now = opt?.now ?? new Date();
  const regionId = opt?.regionId ?? DEFAULT_REGION_ID;
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

  const provenance = resolveProvenance(rows, now, regionId);
  const meta = envelopeMeta(provenance, now, regionId);

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
      ...meta.range,
    },
    provenance,
    // `synthetic_included` は PR-2 で撤去した（D2。b03 が合成データを除くため、
    // `observation_agg` に合成データはもう載らない——design §0-2・§2.1「envelope.buildEnvelope」）。
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    caveats: withCaveatMeta(opt?.caveats ?? []),
    truncated: opt?.truncated ?? false,
    spec_version: ENVELOPE_SPEC_VERSION,
    cite_as: meta.cite_as,
    as_of: meta.as_of,
    time_zone: meta.time_zone,
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
export function buildZoneEnvelope(spec: CellSpec, rows: readonly ZoneYearRow[], opt?: EnvelopeOpt): Envelope<ZoneYearRow> {
  const now = opt?.now ?? new Date();
  const regionId = opt?.regionId ?? DEFAULT_REGION_ID;
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

  const provenance = resolveSeriesSetProvenance(series, rows.length, now, regionId);
  const meta = envelopeMeta(provenance, now, regionId);

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
      ...meta.range,
    },
    provenance,
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    caveats: withCaveatMeta(opt?.caveats ?? []),
    truncated: opt?.truncated ?? false,
    spec_version: ENVELOPE_SPEC_VERSION,
    cite_as: meta.cite_as,
    as_of: meta.as_of,
    time_zone: meta.time_zone,
  };
}

/**
 * セルを返さない応答（カタログ・検索・出現の集計など）の封筒。`rows` の代わりに `data` を持ち、
 * 出典（`sourceIds`）の来歴・鮮度、注記、`excluded`（常に 0）、`cite_as` は `buildEnvelope` と同じ。
 * MCP の全ツール（`lib/mcp`）が、封筒を持たないツールでもこの形で返す（ADR-0014）。
 */
export interface DataEnvelope<D> {
  query: Record<string, unknown>;
  data: D;
  provenance: EnvelopeProvenance[];
  coverage: Pick<EnvelopeCoverage, "oldest_fetched_at" | "newest_fetched_at">;
  excluded: EnvelopeExcluded;
  caveats: EnvelopeCaveat[];
  truncated: boolean;
  spec_version: string;
  cite_as: string;
  as_of: string;
  time_zone: Envelope<unknown>["time_zone"];
}

export function buildDataEnvelope<D>(
  query: Record<string, unknown>,
  data: D,
  sources: readonly (string | SourceRef)[],
  opt?: EnvelopeOpt,
): DataEnvelope<D> {
  const now = opt?.now ?? new Date();
  const regionId = opt?.regionId ?? DEFAULT_REGION_ID;
  // 行数は数えていないので null（0 と書くと「0 行引いた」と読める）。出典の一覧だけを載せる。
  const provenance = dedupeSourceRefs(sources).map((ref) => provenanceRow(ref, null, now, regionId));
  const meta = envelopeMeta(provenance, now, regionId);
  return {
    query,
    data,
    provenance,
    coverage: meta.range,
    excluded: { by_license: 0, by_embargo: 0, reasons: [] },
    caveats: withCaveatMeta(opt?.caveats ?? []),
    truncated: opt?.truncated ?? false,
    spec_version: ENVELOPE_SPEC_VERSION,
    cite_as: meta.cite_as,
    as_of: meta.as_of,
    time_zone: meta.time_zone,
  };
}
