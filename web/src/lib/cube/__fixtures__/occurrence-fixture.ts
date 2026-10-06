/**
 * 生物系（Issue #48 PR-3b）のテスト用フィクスチャ。`better-sqlite3(":memory:")` に migrations を
 * 当て、`taxon`/`taxon_assessment`/`occurrence_agg` を手書きで入れ、summary 8表のうち生物系を
 * **同じセルから SQL で導出**する（`aggregations/serving.yaml` の宣言と同じ形。手書きの数値を
 * 別に持たない）。U1 の migration（0008）が入るまで summary 4表・`taxon_assessment.binom` は
 * migrations に無いので、ここで `IF NOT EXISTS`/列の有無確認で補う（入った後は何もしない）。
 *
 * 学名は実データと衝突しないよう架空（`Fx*`）。`NAME_JA` に勝たれる確認だけ実在の学名を使う
 * （`FX_NAME_JA_BINOM`）。
 */
import Database from "better-sqlite3";
import { NAME_JA } from "@/lib/registry/generated-client";
import { applyMigrations, wrapSqlite } from "./cube-fixture";
import type { CubeDb } from "../db";

const GBIF = "gbif_kanagawa_occurrences";
const INAT = "inaturalist_kanagawa";

const G1 = "common:place:grid01.3520_13900";
const G2 = "common:place:grid01.3521_13901";
const WS1 = "common:place:watershed.nlni.83030-0001";

/** `NAME_JA` にある実在の学名（1つ）。 */
export const FX_NAME_JA_BINOM = Object.keys(NAME_JA)[0]!;

export const FXO = {
  places: { g1: G1, g2: G2, ws1: WS1 },
  binoms: { alpha: "Fxa alpha", beta: "Fxb beta", gamma: "Fxc gamma", delta: "Fxd delta", named: FX_NAME_JA_BINOM },
  groups: { bird: "FxBird", plant: "FxPlant" },
} as const;

interface TaxonFx {
  id: string;
  binom: string | null;
  group: string | null;
  cls?: string | null;
  rank?: string | null;
  family?: string | null;
  ja?: string | null;
  basis?: string | null;
  en?: string | null;
}

const TAXA: TaxonFx[] = [
  { id: "common:taxon:fx_a", binom: "Fxa alpha", group: "FxBird", cls: "Aves", family: "FamA", ja: "アルファ", basis: "taxa" },
  { id: "common:taxon:fx_b1", binom: "Fxb beta", group: "FxBird", cls: "Aves", family: "FamB", en: "Beta bird small", rank: "species" },
  { id: "common:taxon:fx_b2", binom: "Fxb beta", group: "FxBird", cls: "Aves", family: "FamB", ja: "ベータ", basis: "records", en: "Beta bird", rank: "subspecies" },
  { id: "common:taxon:fx_c", binom: "Fxc gamma", group: "FxPlant", cls: "Mag", family: "FamC" },
  { id: "common:taxon:fx_d", binom: "Fxd delta", group: "FxPlant", cls: "Mag", family: "FamD", ja: "デルタ", basis: "override" },
  { id: "common:taxon:fx_n", binom: FX_NAME_JA_BINOM, group: "FxPlant", ja: "別の和名", basis: "records" },
];

interface Cell {
  src?: string;
  place: string | null;
  kind: "grid01" | "watershed";
  taxon: string | null;
  grain: "year" | "survey_period" | "month";
  start: string;
  n: number;
  red?: number;
  alien?: number;
}

const A = "common:taxon:fx_a";
const B1 = "common:taxon:fx_b1";
const B2 = "common:taxon:fx_b2";
const C = "common:taxon:fx_c";
const D = "common:taxon:fx_d";
const N = "common:taxon:fx_n";

const CELLS: Cell[] = [
  // alpha（鳥）: A期 2000-2004 = 50、B期 2010-2014 = 90、n 合計 230 ≥ 80
  { place: G1, kind: "grid01", taxon: A, grain: "year", start: "2000-01-01", n: 50, src: GBIF },
  { place: G1, kind: "grid01", taxon: A, grain: "year", start: "2010-01-01", n: 30, src: GBIF },
  { place: G2, kind: "grid01", taxon: A, grain: "year", start: "2010-01-01", n: 60, red: 60, src: GBIF },
  { place: G1, kind: "grid01", taxon: A, grain: "year", start: "2021-01-01", n: 90, src: GBIF },
  { place: G2, kind: "grid01", taxon: A, grain: "survey_period", start: "2005-01-01", n: 4, src: GBIF },
  // 月セル（2018 以降だけ拾う）
  { place: G1, kind: "grid01", taxon: A, grain: "month", start: "2019-03-01", n: 40, src: GBIF },
  { place: G1, kind: "grid01", taxon: A, grain: "month", start: "2019-07-01", n: 60, src: GBIF },
  { place: G2, kind: "grid01", taxon: A, grain: "month", start: "2019-07-01", n: 5, src: GBIF },
  { place: G1, kind: "grid01", taxon: A, grain: "month", start: "2017-05-01", n: 9, src: GBIF },
  // beta（鳥、同じ binom の2 taxon。B2 が代表＝件数最大）
  { place: G1, kind: "grid01", taxon: B1, grain: "year", start: "2000-01-01", n: 5, src: INAT },
  { place: G1, kind: "grid01", taxon: B1, grain: "year", start: "2010-01-01", n: 1, src: INAT },
  { place: G2, kind: "grid01", taxon: B2, grain: "year", start: "2000-01-01", n: 50, src: INAT },
  { place: G2, kind: "grid01", taxon: B2, grain: "year", start: "2010-01-01", n: 30, src: INAT },
  // gamma（植物。n<80）
  { place: G1, kind: "grid01", taxon: C, grain: "year", start: "2022-01-01", n: 10, src: INAT },
  { place: G1, kind: "grid01", taxon: C, grain: "month", start: "2022-05-01", n: 10, src: INAT },
  // delta（植物。IAS。alien）
  { place: G2, kind: "grid01", taxon: D, grain: "year", start: "2022-01-01", n: 20, alien: 20, src: INAT },
  // 実在学名（NAME_JA 優先の確認用）
  { place: G1, kind: "grid01", taxon: N, grain: "year", start: "2022-01-01", n: 3, src: INAT },
  // taxon_id NULL（未判定）
  { place: G1, kind: "grid01", taxon: null, grain: "year", start: "2022-01-01", n: 7, src: INAT },
  // 1970 年より前（summary_grid_catalog の窓の外）
  { place: G2, kind: "grid01", taxon: A, grain: "year", start: "1950-01-01", n: 2, red: 2, src: GBIF },
  // watershed
  { place: WS1, kind: "watershed", taxon: A, grain: "year", start: "2020-01-01", n: 10, src: GBIF },
  { place: WS1, kind: "watershed", taxon: D, grain: "year", start: "2020-01-01", n: 20, alien: 20, src: INAT },
  { place: WS1, kind: "watershed", taxon: A, grain: "year", start: "2021-01-01", n: 5, red: 5, src: GBIF },
  { place: null, kind: "watershed", taxon: A, grain: "year", start: "2021-01-01", n: 3, src: GBIF },
];

/** `AssessmentVocab`（`assessment.ts`）と同じ形。実 registry の生成定数に依存しないテスト用。 */
export const FX_VOCAB = {
  categories: {
    CR: { labelJa: "絶滅危惧IA類", rank: 60 },
    EN: { labelJa: "絶滅危惧IB類", rank: 50 },
    VU: { labelJa: "絶滅危惧II類", rank: 40 },
    NT: { labelJa: "準絶滅危惧", rank: 30 },
    not_listed: { labelJa: "前回記載なし", rank: null },
  },
  lists: {
    rl2020: { name: "RL2020", year: 2020, kind: "red_list" },
    rl2026: { name: "RL2026", year: 2026, kind: "red_list" },
    moe_ias_2015: { name: "IAS", year: 2015, kind: "invasive" },
  },
} as const;

interface AssessFx {
  id: string;
  list: string;
  year: number | null;
  sci: string;
  ja: string;
  group: string;
  cat: string | null;
  prev: string | null;
  binom?: string | null;
  inScope?: number;
  catRaw?: string;
  resolved?: string | null;
  familyJa?: string | null;
}

const ASSESS: AssessFx[] = [
  { id: "rl2020_1", list: "rl2020", year: 2020, sci: "Fxa alpha", ja: "アルファ", group: "鳥類", cat: "CR", prev: "EN", familyJa: "アルファ科" }, // 悪化
  { id: "rl2020_2", list: "rl2020", year: 2020, sci: "Fxb beta", ja: "ベータ", group: "鳥類", cat: "EN", prev: "CR" }, // 改善
  { id: "rl2020_3", list: "rl2020", year: 2020, sci: "Fxc gamma", ja: "ガンマ", group: "植物", cat: "VU", prev: "VU" }, // 横ばい
  { id: "rl2020_4", list: "rl2020", year: 2020, sci: "Fxd delta", ja: "デルタ", group: "植物", cat: "NT", prev: "not_listed" }, // 前回記載なし
  { id: "rl2020_5", list: "rl2020", year: 2020, sci: "Fxe eps", ja: "イプシロン", group: "鳥類", cat: "CR", prev: "EN" }, // 悪化
  { id: "rl2026_1", list: "rl2026", year: 2026, sci: "Fxa alpha", ja: "アルファ", group: "鳥類", cat: "VU", prev: "VU" },
  { id: "ias_1", list: "moe_ias_2015", year: 2015, sci: "Fxd delta", ja: "デルタ", group: "植物", cat: null, prev: null, binom: "Fxd delta", catRaw: "総合対策外来種", resolved: "デルタ" },
  { id: "ias_2", list: "moe_ias_2015", year: 2015, sci: "Fxd delta", ja: "デルタ", group: "植物", cat: null, prev: null, binom: "Fxd delta", catRaw: "その他の総合対策外来種", resolved: "デルタ" },
  { id: "ias_3", list: "moe_ias_2015", year: 2015, sci: "Fxz zeta", ja: "ゼータ", group: "植物", cat: null, prev: null, binom: "Fxz zeta", catRaw: "総合対策外来種" }, // 記録なし
  { id: "ias_4", list: "moe_ias_2015", year: 2015, sci: "Fxa alpha", ja: "アルファ", group: "鳥類", cat: null, prev: null, binom: "Fxa alpha", catRaw: "除外", inScope: 0 },
];

function hasColumn(db: Database.Database, table: string, col: string): boolean {
  return (db.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[]).some((c) => c.name === col);
}

function ensureSchema(db: Database.Database): void {
  if (!hasColumn(db, "taxon_assessment", "binom")) db.exec(`ALTER TABLE taxon_assessment ADD COLUMN binom text`);
  if (!hasColumn(db, "taxon_assessment", "in_scope")) db.exec(`ALTER TABLE taxon_assessment ADD COLUMN in_scope integer`);
  for (const col of ["vernacular_name_en", "vernacular_ja_basis"]) {
    if (!hasColumn(db, "taxon", col)) db.exec(`ALTER TABLE taxon ADD COLUMN ${col} text`);
  }
  if (!hasColumn(db, "occurrence_agg", "n_alien")) db.exec(`ALTER TABLE occurrence_agg ADD COLUMN n_alien integer NOT NULL DEFAULT 0`);
  db.exec(`
    CREATE TABLE IF NOT EXISTS summary_species_catalog (
      binom text NOT NULL, taxon_group text, "class" text, family text,
      n integer NOT NULL, n_red_list integer NOT NULL, n_alien integer NOT NULL, n_places integer NOT NULL,
      y_from integer, y_to integer, n_years integer NOT NULL, built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_group_year (
      year integer NOT NULL, taxon_group text NOT NULL, source_id text NOT NULL,
      n integer NOT NULL, n_binom integer NOT NULL, n_places integer NOT NULL, built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_effort_year (
      year integer NOT NULL, n integer NOT NULL, n_binom integer NOT NULL, n_places integer NOT NULL,
      built_from text NOT NULL, spec_version text NOT NULL);
    CREATE TABLE IF NOT EXISTS summary_grid_catalog (
      place_id text NOT NULL, n integer NOT NULL, n_red_list integer NOT NULL, n_binom integer NOT NULL, n_red_binom integer NOT NULL,
      built_from text NOT NULL, spec_version text NOT NULL);
  `);
}

function seed(db: Database.Database): void {
  const tx = db.prepare(
    `INSERT INTO taxon (taxon_id, scientific_name, canonical_binomial, "class", family, rank, taxon_group, vernacular_name_ja, vernacular_name_en, vernacular_ja_basis)
     VALUES (@id,@binom,@binom,@cls,@family,@rank,@group,@ja,@en,@basis)`,
  );
  for (const t of TAXA) tx.run({ id: t.id, binom: t.binom, group: t.group, cls: t.cls ?? null, family: t.family ?? null, rank: t.rank ?? null, ja: t.ja ?? null, en: t.en ?? null, basis: t.basis ?? null });

  const oc = db.prepare(
    `INSERT INTO occurrence_agg (region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end, n, n_red_list, n_alien, built_from, spec_version)
     VALUES ('kanagawa',@src,@place,@kind,@taxon,@grain,@start,@start,@n,@red,@alien,'fixture:occurrence-fixture','fixture@1')`,
  );
  for (const c of CELLS) oc.run({ src: c.src ?? GBIF, place: c.place, kind: c.kind, taxon: c.taxon, grain: c.grain, start: c.start, n: c.n, red: c.red ?? 0, alien: c.alien ?? 0 });

  const as = db.prepare(
    `INSERT INTO taxon_assessment (assessment_id, list_id, list_year, scientific_name_raw, vernacular_name_ja_raw, vernacular_name_ja_resolved, taxon_group_ja, family_ja,
        category_raw, category_code, prev_category_code, national_category_raw, binom, in_scope)
     VALUES (@id,@list,@year,@sci,@ja,@resolved,@group,@familyJa,@catRaw,@cat,@prev,'国:NT',@binom,@inScope)`,
  );
  for (const a of ASSESS) {
    as.run({ id: a.id, list: a.list, year: a.year, sci: a.sci, ja: a.ja, resolved: a.resolved ?? null, group: a.group, familyJa: a.familyJa ?? null, catRaw: a.catRaw ?? a.cat, cat: a.cat, prev: a.prev, binom: a.binom ?? null, inScope: a.inScope ?? 1 });
  }

  seedSummaries(db);
}

const YEAR_FAMILY = `o.place_kind = 'grid01' AND o.grain IN ('year','survey_period')`;
const META = `'fixture:occurrence-fixture', 'fixture@1'`;

/** summary を同じセルから導出する（`aggregations/serving.yaml` の宣言と同じ形）。 */
function seedSummaries(db: Database.Database): void {
  db.exec(`
    INSERT INTO summary_taxon_catalog (taxon_id, n, n_red_list, n_alien, n_places, y_from, y_to, n_years, built_from, spec_version)
    SELECT o.taxon_id, SUM(o.n), SUM(o.n_red_list), SUM(o.n_alien), COUNT(DISTINCT o.place_id),
           MIN(CAST(substr(o.period_start,1,4) AS INTEGER)), MAX(CAST(substr(o.period_start,1,4) AS INTEGER)),
           COUNT(DISTINCT substr(o.period_start,1,4)), ${META}
    FROM occurrence_agg o WHERE ${YEAR_FAMILY} GROUP BY o.taxon_id;

    INSERT INTO summary_watershed_occurrence (place_id, n, n_red_list, n_alien, n_taxa, y_from, y_to, built_from, spec_version)
    SELECT o.place_id, SUM(o.n), SUM(o.n_red_list), SUM(o.n_alien), COUNT(DISTINCT o.taxon_id),
           MIN(CAST(substr(o.period_start,1,4) AS INTEGER)), MAX(CAST(substr(o.period_start,1,4) AS INTEGER)), ${META}
    FROM occurrence_agg o WHERE o.place_kind = 'watershed' AND o.grain IN ('year','survey_period') GROUP BY o.place_id;

    INSERT INTO summary_species_catalog (binom, taxon_group, "class", family, n, n_red_list, n_alien, n_places, y_from, y_to, n_years, built_from, spec_version)
    SELECT t.canonical_binomial, MAX(t.taxon_group), MAX(t."class"), MAX(t.family),
           SUM(o.n), SUM(o.n_red_list), SUM(o.n_alien), COUNT(DISTINCT o.place_id),
           MIN(CAST(substr(o.period_start,1,4) AS INTEGER)), MAX(CAST(substr(o.period_start,1,4) AS INTEGER)),
           COUNT(DISTINCT substr(o.period_start,1,4)), ${META}
    FROM occurrence_agg o JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_FAMILY} AND t.canonical_binomial IS NOT NULL GROUP BY t.canonical_binomial;

    INSERT INTO summary_group_year (year, taxon_group, source_id, n, n_binom, n_places, built_from, spec_version)
    SELECT CAST(substr(o.period_start,1,4) AS INTEGER), COALESCE(t.taxon_group, '未判定'), o.source_id,
           SUM(o.n), COUNT(DISTINCT t.canonical_binomial), COUNT(DISTINCT o.place_id), ${META}
    FROM occurrence_agg o LEFT JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_FAMILY} GROUP BY 1, 2, 3;

    INSERT INTO summary_effort_year (year, n, n_binom, n_places, built_from, spec_version)
    SELECT CAST(substr(o.period_start,1,4) AS INTEGER), SUM(o.n), COUNT(DISTINCT t.canonical_binomial), COUNT(DISTINCT o.place_id), ${META}
    FROM occurrence_agg o LEFT JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_FAMILY} GROUP BY 1;

    INSERT INTO summary_grid_catalog (place_id, n, n_red_list, n_binom, n_red_binom, built_from, spec_version)
    SELECT o.place_id,
           SUM(CASE WHEN substr(o.period_start,1,4) BETWEEN '1970' AND '2026' THEN o.n ELSE 0 END),
           SUM(CASE WHEN substr(o.period_start,1,4) BETWEEN '1970' AND '2026' THEN o.n_red_list ELSE 0 END),
           COUNT(DISTINCT t.canonical_binomial),
           COUNT(DISTINCT CASE WHEN o.n_red_list > 0 THEN t.canonical_binomial END), ${META}
    FROM occurrence_agg o LEFT JOIN taxon t ON t.taxon_id = o.taxon_id
    WHERE ${YEAR_FAMILY} AND o.place_id IS NOT NULL GROUP BY o.place_id;
  `);
}

export interface OccurrenceFixture {
  db: CubeDb & { close(): void };
  raw: Database.Database;
}

export function buildOccurrenceFixture(): OccurrenceFixture {
  const raw = new Database(":memory:");
  applyMigrations(raw);
  ensureSchema(raw);
  seed(raw);
  return { db: wrapSqlite(raw), raw };
}
