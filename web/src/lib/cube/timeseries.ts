/**
 * 時系列（観測セル）を封筒つきで取る問い合わせ（AI の `get_timeseries` と MCP の
 * `get_observations` が同じ関数を通る。ADR-0014「MCP で取れないものは画面にも出ていない」を
 * 同じ経路で保つ。新しい SQL は書かず、`queryCells`/`summarize` の合成だけ）。
 *
 * 元は `lib/ai/tools.ts` の `get_timeseries` の本体。挙動は変えずに切り出した
 * （Issue #40 Phase D 担当 E）。
 */
import { buildEnvelope, buildZoneEnvelope, type Envelope, type EnvelopeOpt } from "./envelope";
import type { CubeDb } from "./db";
import { pivotYearCells, queryCells, summarize, toSeriesPoint } from "./observation";
import type { CellSpec } from "./observation";
import {
  representativeSeries,
  representativeSeriesForSources,
  basisOf,
  yearCellFilterForBasis,
  withTheme,
  MEASUREMENTS_DATASET,
  type Grain,
  type SeriesKey,
} from "./series";
import { sitesInWaterBody } from "./catalog";
import type { Scope } from "./sql";
import { unitLabel } from "./unit";
import { caveatsForFacets, facetsForSeries } from "./caveats";

export type TimeseriesScope =
  | { type: "water"; name: string }
  | { type: "site"; siteId: string }
  | { type: "zone" }
  /** 流域（土地利用など `place_kind='watershed'` の系列）。`placeId` 省略は全流域。 */
  | { type: "watershed"; placeId?: string };

/** 入力の組み合わせの誤り（呼び出し側が自分の入力エラーに変える。MCP は `McpInputError`）。 */
export class TimeseriesInputError extends Error {}
export type TimeseriesGrain = "year" | "fiscal_year" | "month" | "day";

export interface TimeseriesInput {
  variableId: string;
  scope: TimeseriesScope;
  grain: TimeseriesGrain;
  /** 非代表の統計量（p75/max 等）。省略時は代表系列。 */
  stat?: string;
  /** grain='day' のときの範囲 YYYY-MM-DD。 */
  from?: string;
  to?: string;
  /**
   * 出典で絞る（`variable_alias.source_id`）。指定すると、その出典が登録されている系列を dataset を問わず引く
   * （センサー系列・土地利用など measurements 以外）。省略時は従来どおり measurements の系列。
   */
  sourceIds?: readonly string[];
}

export interface TimeseriesResult {
  /** 登録された系列（`representativeSeries`）。空なら `envelope` は null。 */
  series: SeriesKey[];
  basis: "day" | "fiscal_year" | "year";
  unit: string | null;
  points: unknown[];
  sites?: Awaited<ReturnType<typeof sitesInWaterBody>>;
  /** `rows` は `points` と同じ（画面と同じピボット済みの点）。 */
  envelope: Envelope<unknown> | null;
  truncated: boolean;
}

export async function timeseries(db: CubeDb, input: TimeseriesInput, envelopeOpt?: Pick<EnvelopeOpt, "now" | "regionId">): Promise<TimeseriesResult> {
  const { variableId, scope, grain, stat, from, to, sourceIds } = input;
  const dataset = MEASUREMENTS_DATASET;
  // series は basis で絞り込まない（basis はセルの性質であって系列の登録
  // 〔value_grain〕ではない。Issue #48 PR-2 統合後修正A #1）——representativeSeries()
  // の全 value_grain をそのまま渡し、basis の絞り込みは `yearCellFilterForBasis()`
  // が返す grain/inputGrain でセル側（CellSpec）に行わせる。
  const all = sourceIds ? representativeSeriesForSources(variableId, sourceIds, stat ?? "representative") : representativeSeries(variableId, dataset, stat ?? "representative");
  // 毎時（`input_grain='hour'`）・月次（`'month'`）で配られた系列（センサー・気象月報）。セルの input_grain は出典が配った粒度のまま
  // （日次の積み上げ `'day'` でも年・年度の集計値 `'same'` でもない）。粒度が混ざる指定は分けて呼ばせる。
  const nativeGrains = new Set(all.map((s) => s.valueGrain));
  const native = nativeGrains.size === 1 && (nativeGrains.has("hour") || nativeGrains.has("month")) ? ([...nativeGrains][0] as "hour" | "month") : null;
  if (!native && (nativeGrains.has("hour") || nativeGrains.has("month")) && nativeGrains.size > 1) {
    throw new TimeseriesInputError("毎時・月次の系列とそれ以外の粒度の系列が混ざる。source_ids を分けて呼ぶ");
  }
  if (native && grain === "fiscal_year") throw new TimeseriesInputError(`${native === "hour" ? "毎時" : "月次"}の系列に fiscal_year は無い（year・month・day から選ぶ）`);
  const basis: "day" | "fiscal_year" | "year" = native
    ? "day"
    : grain === "fiscal_year"
      ? "fiscal_year"
      : grain === "month" || grain === "day"
        ? "day"
        : all.length > 0
          ? basisOf(all).basis
          : "day";
  const unitIds = new Set(all.map((s) => s.unitId));
  const unit = unitIds.size === 1 ? unitLabel([...unitIds][0]) : null;
  const period = from || to ? { from, to } : undefined;
  const basisFilter: { grain: Grain; inputGrain: CellSpec["inputGrain"] } = native
    ? { grain: "year", inputGrain: native }
    : yearCellFilterForBasis(basis);
  const cellGrain = grain === "year" || grain === "fiscal_year" ? [basisFilter.grain] : [grain];

  if (all.length === 0) return { series: all, basis, unit, points: [], envelope: null, truncated: false };

  const facetsScope: Scope =
    scope.type === "zone"
      ? { kind: "all_sites" }
      : scope.type === "water"
        ? { kind: "water", municipality: scope.name }
        : scope.type === "watershed"
          ? { kind: "watershed", placeId: scope.placeId }
          : { kind: "site", siteId: scope.siteId };
  const caveats = caveatsForFacets(facetsForSeries(all.map((s) => withTheme(s)), facetsScope));

  if (scope.type === "zone") {
    const spec: CellSpec = { series: all, scope: facetsScope, grain: cellGrain, inputGrain: basisFilter.inputGrain, period, imputation: "both" };
    // zero/lod を1回の SQL で両方計算する（`summarizeZone` 参照。Issue #48 PR-2 統合後修正A #4）。
    const { rows, truncated } = await summarize(db, spec, "zone");
    const points = rows.map((r) => ({ zone: r.zone, grain: r.grain, year: r.year, nSites: r.nSites, n: r.n, valueLod: r.avgLod, valueZero: r.avgZero }));
    const envelope = buildZoneEnvelope(spec, rows, { ...envelopeOpt, truncated, caveats });
    return { series: all, basis, unit, points, envelope, truncated };
  }

  // 出典指定のときは、その系列が属する dataset が1つに決まるときだけ dataset で絞る（複数なら絞らない）。
  const datasets = new Set(all.map((s) => s.dataset));
  const sitesDataset = sourceIds ? (datasets.size === 1 ? [...datasets][0] : undefined) : dataset;
  const sites = scope.type === "water" ? await sitesInWaterBody(db, scope.name, { dataset: sitesDataset }) : undefined;
  const isYearGrain = grain === "year" || grain === "fiscal_year";
  const spec: CellSpec = {
    series: all,
    scope: facetsScope,
    grain: cellGrain,
    stats: isYearGrain ? ["mean", "min", "max"] : ["mean"],
    inputGrain: basisFilter.inputGrain,
    period,
    imputation: "both",
  };
  const { rows: cells, truncated } = await queryCells(db, spec);
  // `envelope` の coverage/provenance（nNotDetected・出典の帰属）は生セル（`cells`）
  // からでないと正しく計算できない（ピボット後は落ちる情報がある）ので、先に生
  // セルで組み立ててから、`rows` だけ画面と同じピボット済みの点に差し替える
  // （Issue #48 PR-2 code-review #5）。
  const points = isYearGrain ? pivotYearCells(cells) : cells.map(toSeriesPoint);
  const rawEnvelope = buildEnvelope(spec, cells, { ...envelopeOpt, truncated, caveats });
  return { series: all, basis, unit, points, sites, envelope: { ...rawEnvelope, rows: points }, truncated };
}
