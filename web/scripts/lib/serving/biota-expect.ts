/**
 * 生物系の5規則（`classify.ts` の `BiotaExpectations`）が「独立に組んだ中間点」として使う期待値を、
 * L2（`v2.sqlite` の `occurrence`/`occurrence_place`）・registry・`ryuiki.sqlite`・
 * `v1_projection_occurrence.sqlite`（b08 が書く `org_watershed_*_exact`）から**別の SQL で**作る
 * （Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §3.1・§5.4-3）。
 *
 * **`@/lib/cube` を import しない**: 画面と v2 アダプタが通る関数で期待値を作ると、v2 が間違っても
 * 期待値も同じく間違って「説明できた」ことになる（PR-2 §8.4 の再発防止）。`biota-expect.test.ts` が
 * このファイルのソースに `lib/cube` の import が無いことを機械的に確かめる。
 *
 * 読むのは全て読み取り専用。`ids`（回す問い合わせ id）に必要なものだけを読む（`--only` で生物系を
 * 回さないときに L2 を走査しない）。
 */
import fs from "node:fs";
import Database from "better-sqlite3";
import { binomMonthKey, watershedYearKey, type BiotaExpectations, type WsAllExpect, type WsYearExpect } from "./classify";

export interface BiotaPaths {
  /** `data/db/v2.sqlite`（L2 の `occurrence`/`occurrence_place`・`summary_taxon_catalog`）。 */
  v2: string;
  registry: string;
  ryuiki: string;
  /** `data/db/v1_projection_occurrence.sqlite`（b08。`org_watershed_year_exact`/`org_watershed_exact`）。 */
  v1Occurrence: string;
  /** `registry/taxon/vernacular_ja.csv`（人が確認した和名の台帳）。 */
  vernacularCsv: string;
}

/**
 * D4（オーナー決定）: 記録由来の和名補完（`vernacular_ja_basis='records'`）を表示名に使う。
 * 画面側の定数 `USE_RECORD_VERNACULAR`（`lib/cube/occurrence.ts`）と同じ値でなければならない
 * （`biota-expect.test.ts` が一致を確かめる。覆すときは両方を変える）。
 */
export const EXPECT_RECORD_VERNACULAR = true;

/** v1 の `effort_year`/`biotaTotals` が使う出典 ID（`web/src/lib/queries.ts`）。 */
const SOURCE_GBIF = "gbif_kanagawa_occurrences";
const SOURCE_INAT = "inaturalist_kanagawa";

const WATERSHED_PLACE_SOURCE = "watershed_meta.watershed_id";

/** 問い合わせ id → 必要な期待値。 */
const NEEDS: Readonly<Record<string, "wsYear" | "wsAll" | "month" | "labels" | "undated">> = {
  watershed_year: "wsYear",
  watershed_rollup: "wsAll",
  species_months: "month",
  species_labels: "labels",
  species_catalog: "labels",
  species_share_trend: "labels",
  biota_totals: "undated",
};

/**
 * 生物系の問い合わせ id（`serving_queries.yaml` の PR-3b の 17 件）。imputation（zero/lod）にも
 * v1互換キューブ（合成データ）にも依らないので、serving-diff はこれらについて zero 再実行と
 * `--v1compat-db` の第2接続での実行を省く。
 */
export const BIOTA_QUERY_IDS: ReadonlySet<string> = new Set([
  "effort_years",
  "taxon_group_years",
  "species_catalog",
  "species_labels",
  "species_years",
  "species_months",
  "species_mesh_years",
  "species_share_trend",
  "mesh_all",
  "mesh_by_year",
  "ias_species",
  "redlist_summary",
  "redlist_flows",
  "redlist_species",
  "biota_totals",
  "watershed_rollup",
  "watershed_year",
]);

export function biotaNeeds(ids: Iterable<string>): Set<"wsYear" | "wsAll" | "month" | "labels" | "undated"> {
  const out = new Set<"wsYear" | "wsAll" | "month" | "labels" | "undated">();
  for (const id of ids) {
    const n = NEEDS[id];
    if (n) out.add(n);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* 表示名の期待値（純関数）                                              */
/* ------------------------------------------------------------------ */

/** CSV の1行を分割する（ダブルクォートで囲まれたカンマ・`""` エスケープに対応）。 */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") {
      out.push(cur);
      cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

/** `registry/taxon/vernacular_ja.csv`（scientific_name, vernacular_name_ja, source）→ binom → 和名。 */
export function parseVernacularCsv(text: string): Map<string, string> {
  const out = new Map<string, string>();
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  for (const line of lines.slice(1)) {
    const [name, ja] = splitCsvLine(line);
    if (name && ja) out.set(name, ja);
  }
  return out;
}

export interface TaxonNameRow {
  taxon_id: string;
  canonical_binomial: string;
  vernacular_name_ja: string | null;
  vernacular_name_en: string | null;
  vernacular_ja_basis: string | null;
  rank: string | null;
}

/**
 * D4（改訂）の表示名の定義（設計書 §0 D4・§2.3）から、binom ごとの期待ラベルを作る。
 * `NAME_JA`（`vernacular_ja.csv`）→ 和名を持つ taxon のうち種の階級（rank='species'）で
 * `summary_taxon_catalog.n` 最大 → 和名を持つ taxon（種より下を含む）で n 最大 →
 * binom の全 taxon で n 最大のものの英名 → binom。同数は taxon_id の昇順。
 * `records:false` なら和名の候補を basis が override/taxa のものに絞る。
 */
export function expectedLabels(
  taxa: readonly TaxonNameRow[],
  nByTaxon: ReadonlyMap<string, number>,
  fixedJa: ReadonlyMap<string, string>,
  records: boolean,
): Map<string, string> {
  type Pick = { n: number; row: TaxonNameRow };
  const beats = (n: number, row: TaxonNameRow, cur: Pick | undefined) =>
    !cur || n > cur.n || (n === cur.n && row.taxon_id < cur.row.taxon_id);
  const top = new Map<string, Pick>();
  const jaSp = new Map<string, Pick>();
  const jaAny = new Map<string, Pick>();
  for (const t of taxa) {
    const n = nByTaxon.get(t.taxon_id) ?? 0;
    const b = t.canonical_binomial;
    if (beats(n, t, top.get(b))) top.set(b, { n, row: t });
    if (t.vernacular_name_ja && (records || t.vernacular_ja_basis === "override" || t.vernacular_ja_basis === "taxa")) {
      if (beats(n, t, jaAny.get(b))) jaAny.set(b, { n, row: t });
      if (t.rank === "species" && beats(n, t, jaSp.get(b))) jaSp.set(b, { n, row: t });
    }
  }
  const out = new Map<string, string>();
  for (const [binom, { row }] of top) {
    const ja = (jaSp.get(binom) ?? jaAny.get(binom))?.row.vernacular_name_ja;
    out.set(binom, fixedJa.get(binom) || ja || row.vernacular_name_en || binom);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* DB を読む部分                                                         */
/* ------------------------------------------------------------------ */

function sqlString(path: string): string {
  return path.replace(/'/g, "''");
}

interface Rows {
  all(sql: string, params?: unknown[]): Record<string, unknown>[];
}

function openReadOnly(path: string, attach: Record<string, string>): { rows: Rows; close(): void } {
  const db = new Database(path, { readonly: true, fileMustExist: true });
  for (const [alias, p] of Object.entries(attach)) db.exec(`ATTACH DATABASE '${sqlString(p)}' AS ${alias}`);
  db.pragma("query_only = ON");
  return {
    rows: { all: (sql, params = []) => db.prepare(sql).all(...params) as Record<string, unknown>[] },
    close: () => db.close(),
  };
}

/** 流域×年: b08 の exact（記録自身の流域）＋ L2 から `COUNT(DISTINCT taxon_id)`（v2 の種数の定義）。 */
function loadWsYear(paths: BiotaPaths): Map<string, WsYearExpect> {
  const out = new Map<string, WsYearExpect>();
  const occ = openReadOnly(paths.v1Occurrence, {});
  try {
    for (const r of occ.rows.all(`SELECT watershed_id, year, n, species_n, alien_n, redlist_n FROM org_watershed_year_exact`)) {
      out.set(watershedYearKey(r.watershed_id as string, r.year as number), {
        n: r.n as number,
        speciesNameN: r.species_n as number,
        alienN: (r.alien_n as number | null) ?? 0,
        redlistN: (r.redlist_n as number | null) ?? 0,
        speciesTaxonN: null,
      });
    }
  } finally {
    occ.close();
  }
  const l2 = openReadOnly(paths.v2, { reg: paths.registry });
  try {
    // 日付のある記録（`period_start` が非NULL）だけ。年は `period_start` の先頭4桁（v2 の年セルと同じ）。
    // 流域は `occurrence_place` → registry の `place_source_ref`（v1 の watershed_id）。lib/cube の
    // placeId 変換は使わない。
    const rows = l2.rows.all(
      `SELECT psr.external_key AS ws, CAST(substr(o.period_start, 1, 4) AS INTEGER) AS year,
              COUNT(DISTINCT o.taxon_id) AS taxon_n
       FROM occurrence o
       JOIN occurrence_place op ON op.record_id = o.record_id AND op.place_kind = 'watershed' AND op.place_id IS NOT NULL
       JOIN reg.place_source_ref psr ON psr.place_id = op.place_id AND psr.source_id = ?
       WHERE o.period_start IS NOT NULL
       GROUP BY psr.external_key, year`,
      [WATERSHED_PLACE_SOURCE],
    );
    for (const r of rows) {
      const cur = out.get(watershedYearKey(r.ws as string, r.year as number));
      if (cur) cur.speciesTaxonN = r.taxon_n as number;
    }
  } finally {
    l2.close();
  }
  return out;
}

function loadWsAll(paths: BiotaPaths): Map<string, WsAllExpect> {
  const out = new Map<string, WsAllExpect>();
  const occ = openReadOnly(paths.v1Occurrence, {});
  try {
    for (const r of occ.rows.all(`SELECT watershed_id, n, alien_n, redlist_n FROM org_watershed_exact`)) {
      out.set(r.watershed_id as string, {
        n: r.n as number,
        alienN: (r.alien_n as number | null) ?? 0,
        redlistN: (r.redlist_n as number | null) ?? 0,
      });
    }
  } finally {
    occ.close();
  }
  return out;
}

/**
 * 月別の件数（2018 年以降）を、v1 の所属規則と v2 の月セルの所属規則で別々に数える。
 * - v1（`scripts/b08_project_occurrence_v1.py` の `species_month`）: 月＝`period_raw` の `substr(6,2)`
 *   （長さ>=7）、年＝`period_raw` の先頭4桁>=2018。
 * - v2（月セル）: 期間が1つの月に収まる記録（`period_start` と `period_end` の年月が同じ）、
 *   `period_start`>=2018-01-01、月＝`period_start` の月（'Z' 付きの時刻は b06 が UTC オフセット換算済み）。
 */
function loadMonth(paths: BiotaPaths): { v1: Map<string, number>; v2: Map<string, number> } {
  const l2 = openReadOnly(paths.v2, { reg: paths.registry });
  const v1 = new Map<string, number>();
  const v2 = new Map<string, number>();
  try {
    for (const r of l2.rows.all(
      `SELECT t.canonical_binomial AS binom, CAST(substr(o.period_raw, 6, 2) AS INTEGER) AS month, COUNT(*) AS n
       FROM occurrence o JOIN reg.taxon t ON t.taxon_id = o.taxon_id
       WHERE o.period_raw IS NOT NULL AND length(o.period_raw) >= 7
         AND CAST(substr(o.period_raw, 1, 4) AS INTEGER) >= 2018
         AND t.canonical_binomial IS NOT NULL AND t.canonical_binomial <> ''
       GROUP BY t.canonical_binomial, month`,
    )) {
      v1.set(binomMonthKey(r.binom as string, r.month as number), r.n as number);
    }
    for (const r of l2.rows.all(
      `SELECT t.canonical_binomial AS binom, CAST(substr(o.period_start, 6, 2) AS INTEGER) AS month, COUNT(*) AS n
       FROM occurrence o JOIN reg.taxon t ON t.taxon_id = o.taxon_id
       WHERE o.period_start IS NOT NULL AND o.period_start >= '2018-01-01'
         AND substr(o.period_start, 1, 7) = substr(o.period_end, 1, 7)
         AND t.canonical_binomial IS NOT NULL AND t.canonical_binomial <> ''
       GROUP BY t.canonical_binomial, month`,
    )) {
      v2.set(binomMonthKey(r.binom as string, r.month as number), r.n as number);
    }
  } finally {
    l2.close();
  }
  return { v1, v2 };
}

function loadLabels(paths: BiotaPaths): Map<string, string> {
  const fixed = parseVernacularCsv(fs.readFileSync(paths.vernacularCsv, "utf8"));
  const l2 = openReadOnly(paths.v2, { reg: paths.registry });
  try {
    const taxa = l2.rows.all(
      `SELECT taxon_id, canonical_binomial, rank, vernacular_name_ja, vernacular_name_en, vernacular_ja_basis
       FROM reg.taxon WHERE canonical_binomial IS NOT NULL AND canonical_binomial <> ''`,
    ) as unknown as TaxonNameRow[];
    const nByTaxon = new Map<string, number>();
    for (const r of l2.rows.all(`SELECT taxon_id, n FROM summary_taxon_catalog`)) {
      nByTaxon.set(r.taxon_id as string, r.n as number);
    }
    return expectedLabels(taxa, nByTaxon, fixed, EXPECT_RECORD_VERNACULAR);
  } finally {
    l2.close();
  }
}

/** `organism_records`（v1 の原本）で、日付の無い（`observed_on` が NULL または 4 桁未満）記録の件数。 */
function loadUndated(paths: BiotaPaths): { records: number; gbif: number; inat: number } {
  const db = openReadOnly(paths.ryuiki, {});
  try {
    const rows = db.rows.all(
      `SELECT source_id, COUNT(*) AS n FROM organism_records
       WHERE observed_on IS NULL OR length(observed_on) < 4 GROUP BY source_id`,
    );
    let records = 0;
    let gbif = 0;
    let inat = 0;
    for (const r of rows) {
      const n = r.n as number;
      records += n;
      if (r.source_id === SOURCE_GBIF) gbif += n;
      if (r.source_id === SOURCE_INAT) inat += n;
    }
    return { records, gbif, inat };
  } finally {
    db.close();
  }
}

/** `ids`（回す問い合わせ id）に必要な期待値だけを読み込む。 */
export function loadBiotaExpectations(paths: BiotaPaths, ids: Iterable<string>): BiotaExpectations {
  const needs = biotaNeeds(ids);
  const out: BiotaExpectations = {};
  if (needs.has("wsYear")) out.wsYear = loadWsYear(paths);
  if (needs.has("wsAll")) out.wsAll = loadWsAll(paths);
  if (needs.has("month")) {
    const m = loadMonth(paths);
    out.monthV1 = m.v1;
    out.monthV2 = m.v2;
  }
  if (needs.has("labels")) out.labels = loadLabels(paths);
  if (needs.has("undated")) out.undated = loadUndated(paths);
  return out;
}
