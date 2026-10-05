/**
 * 生物出現のセル（`occurrence_agg`）を読む問い合わせ（Issue #48 PR-3b、
 * `docs/plans/V2_SERVING_PR3B.md` §2.2・§2.3・§4）。
 *
 * 型確定コミット: 本体は未実装（U3・U4 が型に載るための足場）。
 */
import type { CubeDb } from "./db";

/** `occurrence_agg` の索引名（Drizzle `schema-cube.ts`・`scripts/` 側と一致させる。1箇所）。 */
export const OCC_INDEX = {
  taxonPeriod: "ix_occurrence_agg_taxon_period",
  placePeriod: "ix_occurrence_agg_place_period",
  kindGrainPeriod: "ix_occurrence_agg_kind_grain_period",
} as const;

/**
 * D4（オーナー決定）: 記録由来の和名補完（`vernacular_ja_basis='records'`）を表示名に使う。
 * 覆すときはここだけ false にする（serving-diff の `vernacular_label_rule` の期待値と
 * 画面が1行で揃う）。
 */
export const USE_RECORD_VERNACULAR = true;

export interface YearRange {
  from: number;
  to: number;
}

export interface SpeciesYearRow {
  binom: string;
  year: number;
  n: number;
  /** `COUNT(DISTINCT place_id)`（grid01）。v1 `species_year2.mesh_n`。 */
  meshN: number;
}

export interface SpeciesMonthRow {
  binom: string;
  month: number;
  n: number;
}

export interface SpeciesMeshYearRow {
  year: number;
  mlat: number;
  mlon: number;
  n: number;
}

export interface ShareTrendRow {
  binom: string;
  /** §2.3 の表示名（`speciesLabels` と同じ規則）。 */
  label: string;
  nA: number;
  nB: number;
  totalA: number;
  totalB: number;
}

export interface MeshYearRow {
  mlat: number;
  mlon: number;
  n: number;
  speciesN: number;
  rlN: number;
}

export interface WatershedYearRow {
  /** `common:place:watershed.nlni-<id>` */
  placeId: string;
  year: number;
  n: number;
  nAlien: number;
  nRedList: number;
  /** `COUNT(DISTINCT taxon_id)`（v1 の学名全文 DISTINCT とは定義が違う。D1・§0-1）。 */
  speciesN: number;
}

export interface SpeciesLabel {
  binom: string;
  label: string;
}

export interface SpeciesLabelOpt {
  /** 既定 `USE_RECORD_VERNACULAR`。false なら `override`/`taxa` 由来の和名だけ。 */
  records?: boolean;
}

const TODO = (): never => {
  throw new Error("lib/cube/occurrence: 未実装");
};

/** v1 `speciesYears`。年は `substr(period_start,1,4)`。窓の既定は 1990〜2026。 */
export async function speciesYears(
  _db: CubeDb,
  _binoms: readonly string[],
  _opt?: Partial<YearRange>,
): Promise<SpeciesYearRow[]> {
  return TODO();
}

/** v1 `speciesMonths`。2018-01-01 以降の月セル。n≥80 の足切りは `summary_species_catalog.n`。 */
export async function speciesMonths(_db: CubeDb, _binoms: readonly string[]): Promise<SpeciesMonthRow[]> {
  return TODO();
}

/** v1 `speciesMeshYears`。n≥80 の種だけ（それ未満は空配列）。 */
export async function speciesMeshYears(_db: CubeDb, _binom: string): Promise<SpeciesMeshYearRow[]> {
  return TODO();
}

/** v1 `speciesShareTrend`。`HAVING n_a>=40 AND n_b>=20`。 */
export async function speciesShareTrend(
  _db: CubeDb,
  _group: string,
  _a: YearRange,
  _b: YearRange,
  _opt?: SpeciesLabelOpt,
): Promise<ShareTrendRow[]> {
  return TODO();
}

/** v1 `meshByYear`（`ix_occurrence_agg_kind_grain_period`）。 */
export async function meshByYear(_db: CubeDb, _year: number): Promise<MeshYearRow[]> {
  return TODO();
}

/** v1 `org_watershed_year`。画面の読み手は無い（serving-diff の `watershed_year` 用）。 */
export async function watershedYears(_db: CubeDb, _opt?: { placeId?: string }): Promise<WatershedYearRow[]> {
  return TODO();
}

/** §2.3 の表示名（API は `{binom, label}` を返す）。 */
export async function speciesLabels(
  _db: CubeDb,
  _binoms: readonly string[],
  _opt?: SpeciesLabelOpt,
): Promise<SpeciesLabel[]> {
  return TODO();
}
