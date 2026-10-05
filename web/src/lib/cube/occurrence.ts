/**
 * 生物出現のセル（`occurrence_agg`）を読む問い合わせ（Issue #48 PR-3b、
 * `docs/plans/V2_SERVING_PR3B.md` §2.2・§2.3・§4）。
 *
 * 全関数が `CubeDb` を第1引数に取り、任意の ID 一覧は `json_each(?)` 1個で渡す
 * （D1 のバインド 100 個制限を踏まない。`assertD1Compatible` が検査）。
 * **taxon 引き・place 引きの SQL は全部 `INDEXED BY`**（§0-2。第3索引 `ix_occurrence_agg_kind_grain_period` が
 * プランナの計画を壊すため。EXPLAIN は `occurrence.test.ts` で固定）。
 */
import { NAME_JA } from "@/lib/registry/generated-client";
import { MAX_ID_LIST, type CubeDb, type SqlParam } from "./db";
import { gridCellOfPlaceId } from "./grid";
import { jsonEachParam } from "./sql";

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


/** v1 の n≥80 の足切り（`species_month`/`species_mesh_year`。外す変更はしない。§2.2）。 */
export const SPECIES_MIN_N = 80;
/** 年族のセル（`year` と、日付が範囲の `survey_period`）。 */
const YEAR_GRAINS = "('year','survey_period')";
const DEFAULT_FROM = 1990;
const DEFAULT_TO = 2026;
/** 月別の下限（v1 `species_month` は 2018 年以降のみ）。 */
const MONTH_FROM = "2018-01-01";

/** 年の範囲 → `period_start` の文字列範囲（ISO 日付の辞書順。'2026' < '2026-01-01' < '2027'）。 */
function periodRange(from: number, to: number): [string, string] {
  return [String(from).padStart(4, "0"), String(to + 1).padStart(4, "0")];
}

function chunk<T>(xs: readonly T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < xs.length; i += size) out.push(xs.slice(i, i + size));
  return out;
}

function uniq(xs: readonly string[]): string[] {
  return [...new Set(xs)];
}

type R = Record<string, string | number | null>;

/** v1 `speciesYears`。年は `substr(period_start,1,4)`。窓の既定は 1990〜2026。 */
export async function speciesYears(
  db: CubeDb,
  binoms: readonly string[],
  opt: Partial<YearRange> = {},
): Promise<SpeciesYearRow[]> {
  const [lo, hi] = periodRange(opt.from ?? DEFAULT_FROM, opt.to ?? DEFAULT_TO);
  const out: SpeciesYearRow[] = [];
  for (const part of chunk(uniq(binoms), MAX_ID_LIST)) {
    const rows = await db.all<R>(
      `SELECT t.canonical_binomial AS binom,
              CAST(substr(o.period_start, 1, 4) AS INTEGER) AS year,
              SUM(o.n) AS n,
              COUNT(DISTINCT o.place_id) AS mesh_n
       FROM json_each(?) j
       JOIN taxon t INDEXED BY ix_taxon_binomial ON t.canonical_binomial = j.value
       JOIN occurrence_agg o INDEXED BY ${OCC_INDEX.taxonPeriod} ON o.taxon_id = t.taxon_id
       WHERE o.place_kind = 'grid01' AND o.grain IN ${YEAR_GRAINS}
         AND o.period_start >= ? AND o.period_start < ?
       GROUP BY t.canonical_binomial, year`,
      [jsonEachParam(part), lo, hi],
    );
    for (const r of rows) out.push({ binom: r.binom as string, year: r.year as number, n: r.n as number, meshN: r.mesh_n as number });
  }
  return out.sort((a, b) => a.year - b.year || (a.binom < b.binom ? -1 : a.binom > b.binom ? 1 : 0));
}

/** v1 `speciesMonths`。2018-01-01 以降の月セル。n≥80 の足切りは `summary_species_catalog.n`。 */
export async function speciesMonths(db: CubeDb, binoms: readonly string[]): Promise<SpeciesMonthRow[]> {
  const out: SpeciesMonthRow[] = [];
  for (const part of chunk(uniq(binoms), MAX_ID_LIST)) {
    const rows = await db.all<R>(
      `SELECT t.canonical_binomial AS binom,
              CAST(substr(o.period_start, 6, 2) AS INTEGER) AS month,
              SUM(o.n) AS n
       FROM json_each(?) j
       JOIN summary_species_catalog s ON s.binom = j.value AND s.n >= ?
       JOIN taxon t INDEXED BY ix_taxon_binomial ON t.canonical_binomial = s.binom
       JOIN occurrence_agg o INDEXED BY ${OCC_INDEX.taxonPeriod} ON o.taxon_id = t.taxon_id
       WHERE o.place_kind = 'grid01' AND o.grain = 'month' AND o.period_start >= ?
       GROUP BY t.canonical_binomial, month`,
      [jsonEachParam(part), SPECIES_MIN_N, MONTH_FROM],
    );
    for (const r of rows) out.push({ binom: r.binom as string, month: r.month as number, n: r.n as number });
  }
  return out.sort((a, b) => a.month - b.month || (a.binom < b.binom ? -1 : a.binom > b.binom ? 1 : 0));
}

/** v1 `speciesMeshYears`。n≥80 の種だけ（それ未満は空配列）。 */
export async function speciesMeshYears(db: CubeDb, binom: string): Promise<SpeciesMeshYearRow[]> {
  const rows = await db.all<R>(
    `SELECT CAST(substr(o.period_start, 1, 4) AS INTEGER) AS year, o.place_id AS place_id, SUM(o.n) AS n
     FROM summary_species_catalog s
     JOIN taxon t INDEXED BY ix_taxon_binomial ON t.canonical_binomial = s.binom
     JOIN occurrence_agg o INDEXED BY ${OCC_INDEX.taxonPeriod} ON o.taxon_id = t.taxon_id
     WHERE s.binom = ? AND s.n >= ?
       AND o.place_kind = 'grid01' AND o.grain IN ${YEAR_GRAINS}
     GROUP BY year, o.place_id`,
    [binom, SPECIES_MIN_N],
  );
  const out: SpeciesMeshYearRow[] = [];
  for (const r of rows) {
    const cell = gridCellOfPlaceId(r.place_id as string);
    if (cell) out.push({ year: r.year as number, mlat: cell.mlat, mlon: cell.mlon, n: r.n as number });
  }
  return out.sort((a, b) => a.year - b.year || a.mlat - b.mlat || a.mlon - b.mlon);
}

/**
 * v1 `speciesShareTrend`。`group` の taxon を `summary_species_catalog` から引き、各 taxon の
 * セルを期間 A/B で SUM して binom に束ねる。`HAVING n_a>=40 AND n_b>=20`。`totalA/totalB` は
 * 足切り前の同じ group 全体の合計（v1 と同じ）。
 */
export async function speciesShareTrend(
  db: CubeDb,
  group: string,
  a: YearRange,
  b: YearRange,
  opt: SpeciesLabelOpt = {},
): Promise<ShareTrendRow[]> {
  const [aLo, aHi] = periodRange(a.from, a.to);
  const [bLo, bHi] = periodRange(b.from, b.to);
  const lo = aLo < bLo ? aLo : bLo;
  const hi = aHi > bHi ? aHi : bHi;
  const rows = await db.all<R>(
    `SELECT s.binom AS binom,
            SUM(CASE WHEN o.period_start >= ? AND o.period_start < ? THEN o.n ELSE 0 END) AS n_a,
            SUM(CASE WHEN o.period_start >= ? AND o.period_start < ? THEN o.n ELSE 0 END) AS n_b
     FROM summary_species_catalog s
     JOIN taxon t INDEXED BY ix_taxon_binomial ON t.canonical_binomial = s.binom
     JOIN occurrence_agg o INDEXED BY ${OCC_INDEX.taxonPeriod} ON o.taxon_id = t.taxon_id
     WHERE s.taxon_group = ?
       AND o.place_kind = 'grid01' AND o.grain IN ${YEAR_GRAINS}
       AND o.period_start >= ? AND o.period_start < ?
     GROUP BY s.binom`,
    [aLo, aHi, bLo, bHi, group, lo, hi],
  );
  let totalA = 0;
  let totalB = 0;
  for (const r of rows) {
    totalA += r.n_a as number;
    totalB += r.n_b as number;
  }
  const kept = rows.filter((r) => (r.n_a as number) >= 40 && (r.n_b as number) >= 20);
  const labels = await labelMap(db, kept.map((r) => r.binom as string), opt);
  return kept.map((r) => ({
    binom: r.binom as string,
    label: labels.get(r.binom as string) ?? (r.binom as string),
    nA: r.n_a as number,
    nB: r.n_b as number,
    totalA,
    totalB,
  }));
}

/** v1 `meshByYear`（`ix_occurrence_agg_kind_grain_period`）。 */
export async function meshByYear(db: CubeDb, year: number): Promise<MeshYearRow[]> {
  const [lo, hi] = periodRange(year, year);
  const rows = await db.all<R>(
    `SELECT o.place_id AS place_id, SUM(o.n) AS n,
            COUNT(DISTINCT t.canonical_binomial) AS species_n,
            SUM(o.n_red_list) AS rl_n
     FROM occurrence_agg o INDEXED BY ${OCC_INDEX.kindGrainPeriod}
     LEFT JOIN taxon t ON t.taxon_id = o.taxon_id
     WHERE o.place_kind = 'grid01' AND o.grain IN ${YEAR_GRAINS}
       AND o.period_start >= ? AND o.period_start < ?
     GROUP BY o.place_id`,
    [lo, hi],
  );
  const out: MeshYearRow[] = [];
  for (const r of rows) {
    const cell = gridCellOfPlaceId(r.place_id as string);
    if (cell) out.push({ mlat: cell.mlat, mlon: cell.mlon, n: r.n as number, speciesN: r.species_n as number, rlN: r.rl_n as number });
  }
  return out.sort((x, y) => x.mlat - y.mlat || x.mlon - y.mlon);
}

/** v1 `org_watershed_year`。画面の読み手は無い（serving-diff の `watershed_year` 用）。 */
export async function watershedYears(db: CubeDb, opt: { placeId?: string } = {}): Promise<WatershedYearRow[]> {
  const params: SqlParam[] = [];
  let index: string = OCC_INDEX.kindGrainPeriod;
  let where = "o.place_kind = 'watershed' AND o.place_id IS NOT NULL AND o.grain IN " + YEAR_GRAINS;
  if (opt.placeId !== undefined) {
    index = OCC_INDEX.placePeriod;
    where += " AND o.place_id = ?";
    params.push(opt.placeId);
  }
  const rows = await db.all<R>(
    `SELECT o.place_id AS place_id, CAST(substr(o.period_start, 1, 4) AS INTEGER) AS year,
            SUM(o.n) AS n, SUM(o.n_alien) AS n_alien, SUM(o.n_red_list) AS n_red_list,
            COUNT(DISTINCT o.taxon_id) AS species_n
     FROM occurrence_agg o INDEXED BY ${index}
     WHERE ${where}
     GROUP BY o.place_id, year`,
    params,
  );
  return rows
    .map((r) => ({
      placeId: r.place_id as string,
      year: r.year as number,
      n: r.n as number,
      nAlien: r.n_alien as number,
      nRedList: r.n_red_list as number,
      speciesN: r.species_n as number,
    }))
    .sort((x, y) => (x.placeId < y.placeId ? -1 : x.placeId > y.placeId ? 1 : x.year - y.year));
}

/** 代表 taxon の名前の素材（`resolveNames`・`catalog.ts` の `iasSpecies` が使う）。 */
export interface TaxonNames {
  ja: string | null;
  jaBasis: string | null;
  en: string | null;
}

/**
 * binom → 代表 taxon（`summary_taxon_catalog.n` が最大。同数は taxon_id 昇順）の名前。
 * `ix_taxon_binomial` で引く。
 */
export async function resolveNames(db: CubeDb, binoms: readonly string[]): Promise<Map<string, TaxonNames>> {
  const best = new Map<string, { n: number; id: string; names: TaxonNames }>();
  for (const part of chunk(uniq(binoms), MAX_ID_LIST)) {
    const rows = await db.all<R>(
      `SELECT t.canonical_binomial AS binom, t.taxon_id AS taxon_id,
              t.vernacular_name_ja AS ja, t.vernacular_ja_basis AS basis, t.vernacular_name_en AS en,
              COALESCE(tc.n, 0) AS n
       FROM json_each(?) j
       JOIN taxon t INDEXED BY ix_taxon_binomial ON t.canonical_binomial = j.value
       LEFT JOIN summary_taxon_catalog tc ON tc.taxon_id = t.taxon_id`,
      [jsonEachParam(part)],
    );
    for (const r of rows) {
      const binom = r.binom as string;
      const n = r.n as number;
      const id = r.taxon_id as string;
      const cur = best.get(binom);
      if (!cur || n > cur.n || (n === cur.n && id < cur.id)) {
        best.set(binom, { n, id, names: { ja: r.ja as string | null, jaBasis: r.basis as string | null, en: r.en as string | null } });
      }
    }
  }
  return new Map([...best].map(([k, v]) => [k, v.names]));
}

/**
 * 表示名の選び方の**唯一の場所**（§2.3、§5.4-2）: `NAME_JA`（人が確認した和名）→
 * taxon の和名（`records:false` なら basis が override/taxa のものだけ）→ 英名 → binom。
 */
export function pickLabel(binom: string, names: TaxonNames | undefined, records: boolean): string {
  const fixed = NAME_JA[binom];
  if (fixed) return fixed;
  if (names) {
    const basisOk = records || names.jaBasis === "override" || names.jaBasis === "taxa";
    if (names.ja && basisOk) return names.ja;
    if (names.en) return names.en;
  }
  return binom;
}

async function labelMap(db: CubeDb, binoms: readonly string[], opt: SpeciesLabelOpt): Promise<Map<string, string>> {
  const records = opt.records ?? USE_RECORD_VERNACULAR;
  const names = await resolveNames(db, binoms);
  return new Map(uniq(binoms).map((b) => [b, pickLabel(b, names.get(b), records)]));
}

/** §2.3 の表示名（API は `{binom, label}` を返す）。 */
export async function speciesLabels(
  db: CubeDb,
  binoms: readonly string[],
  opt: SpeciesLabelOpt = {},
): Promise<SpeciesLabel[]> {
  const m = await labelMap(db, binoms, opt);
  return uniq(binoms).map((b) => ({ binom: b, label: m.get(b) ?? b }));
}
