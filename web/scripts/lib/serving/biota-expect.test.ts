/**
 * `biota-expect.ts`（生物系5規則の期待値を L2 等から独立に作る層）のテスト。
 *
 * 一時ディレクトリに最小の sqlite 4 つ（v2＝L2、registry、ryuiki、b08 の exact）と台帳 CSV を作り、
 * `loadBiotaExpectations` が設計書 §3.1 の定義どおりの値を返すことを確かめる。実データは使わない。
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import Database from "better-sqlite3";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { USE_RECORD_VERNACULAR } from "@/lib/cube/occurrence";
import {
  BIOTA_QUERY_IDS,
  EXPECT_RECORD_VERNACULAR,
  biotaNeeds,
  expectedLabels,
  loadBiotaExpectations,
  parseVernacularCsv,
  type BiotaPaths,
  type TaxonNameRow,
} from "./biota-expect";
import { binomMonthKey, watershedYearKey } from "./classify";

const HERE = path.dirname(fileURLToPath(import.meta.url));

describe("独立性（設計書 §5.4-3）", () => {
  it("biota-expect.ts のソースは lib/cube を import しない（正解を v2 の経路で作らない）", () => {
    const src = fs.readFileSync(path.join(HERE, "biota-expect.ts"), "utf8");
    // コメントには lib/cube という語が出てくる（独立性の説明）ので、import/require/動的 import の文だけを見る。
    expect(src).not.toMatch(/^\s*(import|export)\b[^;]*\bfrom\s+["'][^"']*lib\/cube/m);
    expect(src).not.toMatch(/\b(require|import)\(\s*["'][^"']*lib\/cube/);
  });

  it("classify.ts のソースも lib/cube を import しない", () => {
    const src = fs.readFileSync(path.join(HERE, "classify.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["']@\/lib\/cube/);
  });

  it("D4 の定数は画面側（lib/cube の USE_RECORD_VERNACULAR）と同じ値（覆すときは両方を変える）", () => {
    expect(EXPECT_RECORD_VERNACULAR).toBe(USE_RECORD_VERNACULAR);
  });
});

describe("parseVernacularCsv", () => {
  it("ヘッダを飛ばし、学名→和名。クォートされたカンマも扱う", () => {
    const m = parseVernacularCsv('scientific_name,vernacular_name_ja,source\nHypsipetes amaurotis,ヒヨドリ,domain.ts\n"Fx, b",ビー,x\n\n');
    expect(m.get("Hypsipetes amaurotis")).toBe("ヒヨドリ");
    expect(m.get("Fx, b")).toBe("ビー");
    expect(m.size).toBe(2);
  });
});

describe("expectedLabels（D4: NAME_JA → 代表 taxon の和名 → 英名 → binom）", () => {
  const taxa: TaxonNameRow[] = [
    { taxon_id: "t1", canonical_binomial: "Fx a", vernacular_name_ja: null, vernacular_name_en: "Alpha", vernacular_ja_basis: null },
    { taxon_id: "t2", canonical_binomial: "Fx a", vernacular_name_ja: "アルファ", vernacular_name_en: null, vernacular_ja_basis: "records" },
    { taxon_id: "t3", canonical_binomial: "Fx b", vernacular_name_ja: "ベータ", vernacular_name_en: "Beta", vernacular_ja_basis: "taxa" },
    { taxon_id: "t4", canonical_binomial: "Fx c", vernacular_name_ja: null, vernacular_name_en: null, vernacular_ja_basis: null },
    { taxon_id: "t5", canonical_binomial: "Fx d", vernacular_name_ja: "デルタ（記録）", vernacular_name_en: "Delta", vernacular_ja_basis: "records" },
    { taxon_id: "t6", canonical_binomial: "Fx e", vernacular_name_ja: "同数1", vernacular_name_en: null, vernacular_ja_basis: "taxa" },
    { taxon_id: "t7", canonical_binomial: "Fx e", vernacular_name_ja: "同数2", vernacular_name_en: null, vernacular_ja_basis: "taxa" },
  ];
  const n = new Map([["t1", 5], ["t2", 50], ["t3", 3], ["t5", 9], ["t6", 4], ["t7", 4]]);
  const fixed = new Map([["Fx b", "固定名"]]);

  it("記録由来を使う: 件数最大の taxon の和名。台帳（NAME_JA）が最優先。無ければ英名→binom。同数は taxon_id 昇順", () => {
    const m = expectedLabels(taxa, n, fixed, true);
    expect(m.get("Fx a")).toBe("アルファ");
    expect(m.get("Fx b")).toBe("固定名");
    expect(m.get("Fx c")).toBe("Fx c");
    expect(m.get("Fx d")).toBe("デルタ（記録）");
    expect(m.get("Fx e")).toBe("同数1");
  });

  it("記録由来を使わない: basis が override/taxa のものだけ和名にし、records は英名へ落とす", () => {
    const m = expectedLabels(taxa, n, fixed, false);
    expect(m.get("Fx a")).toBe("Fx a"); // 代表は t2（records）。和名は使わず、t2 に英名も無いので binom
    expect(m.get("Fx d")).toBe("Delta"); // records の和名は使わず英名へ
    expect(m.get("Fx e")).toBe("同数1"); // taxa 由来は使う
    expect(m.get("Fx b")).toBe("固定名");
  });
});

describe("loadBiotaExpectations（フィクスチャの sqlite 4 つ）", () => {
  let dir: string;
  let paths: BiotaPaths;

  beforeAll(() => {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), "biota-expect-"));
    paths = {
      v2: path.join(dir, "v2.sqlite"),
      registry: path.join(dir, "registry.sqlite"),
      ryuiki: path.join(dir, "ryuiki.sqlite"),
      v1Occurrence: path.join(dir, "v1_projection_occurrence.sqlite"),
      vernacularCsv: path.join(dir, "vernacular_ja.csv"),
    };

    // registry: taxon・place_source_ref
    const reg = new Database(paths.registry);
    reg.exec(`
      CREATE TABLE taxon (taxon_id TEXT PRIMARY KEY, canonical_binomial TEXT, vernacular_name_ja TEXT, vernacular_name_en TEXT, vernacular_ja_basis TEXT);
      CREATE TABLE place_source_ref (source_id TEXT, external_key TEXT, place_id TEXT);
      INSERT INTO taxon VALUES ('t1','Fx a',NULL,'Alpha',NULL), ('t2','Fx a','アルファ',NULL,'records'), ('t3','Fx b','ベータ','Beta','taxa');
      INSERT INTO place_source_ref VALUES ('watershed_meta.watershed_id','W1','common:place:watershed.nlni-W1');
    `);
    reg.close();

    // v2（L2）: occurrence・occurrence_place・summary_taxon_catalog
    const v2 = new Database(paths.v2);
    v2.exec(`
      CREATE TABLE occurrence (record_id TEXT, taxon_id TEXT, period_raw TEXT, period_start TEXT, period_end TEXT);
      CREATE TABLE occurrence_place (record_id TEXT, place_kind TEXT, place_id TEXT);
      CREATE TABLE summary_taxon_catalog (taxon_id TEXT, n INTEGER);
      INSERT INTO summary_taxon_catalog VALUES ('t1',5),('t2',50),('t3',3);
      -- r1: 3月の1日（v1 も v2 も 3 月）
      INSERT INTO occurrence VALUES ('r1','t1','2020-03-15','2020-03-15','2020-03-15');
      -- r2: 月をまたぐ日区間（v1 は period_raw の月=3、v2 は同一月でないので月セルに入らない）
      INSERT INTO occurrence VALUES ('r2','t1','2020-03-31/2020-04-02','2020-03-31','2020-04-02');
      -- r3: 'Z'（v1 は period_raw の月=1、v2 は JST 換算後の period_start の月=2）
      INSERT INTO occurrence VALUES ('r3','t3','2020-01-31T20:00Z','2020-02-01T05:00:00','2020-02-01T05:00:00');
      -- r4: 年粒度（v1 は長さ4で対象外、v2 は同一月でない）
      INSERT INTO occurrence VALUES ('r4','t1','2019','2019-01-01','2019-12-31');
      -- r5: 日付なし
      INSERT INTO occurrence VALUES ('r5','t1',NULL,NULL,NULL);
      -- r6: 2018 年より前
      INSERT INTO occurrence VALUES ('r6','t1','2010-05-05','2010-05-05','2010-05-05');
      INSERT INTO occurrence_place VALUES ('r1','watershed','common:place:watershed.nlni-W1'),('r2','watershed','common:place:watershed.nlni-W1'),
        ('r3','watershed','common:place:watershed.nlni-W1'),('r4','watershed','common:place:watershed.nlni-W1'),('r5','watershed','common:place:watershed.nlni-W1'),
        ('r6','watershed',NULL);
    `);
    v2.close();

    const ry = new Database(paths.ryuiki);
    ry.exec(`
      CREATE TABLE organism_records (record_id TEXT, observed_on TEXT, source_id TEXT);
      INSERT INTO organism_records VALUES ('a','2020-01-01','gbif_kanagawa_occurrences'),('b',NULL,'gbif_kanagawa_occurrences'),
        ('c','','inaturalist_kanagawa'),('d','202','inaturalist_kanagawa'),('e','2021','inaturalist_kanagawa'),('f',NULL,'other_source');
    `);
    ry.close();

    const occ = new Database(paths.v1Occurrence);
    occ.exec(`
      CREATE TABLE org_watershed_year_exact (watershed_id TEXT, year INT, n, species_n, alien_n, redlist_n);
      CREATE TABLE org_watershed_exact (watershed_id TEXT, n, alien_n, redlist_n, y_from, y_to);
      INSERT INTO org_watershed_year_exact VALUES ('W1',2020,3,1,0,2), ('W1',2019,1,1,NULL,NULL);
      INSERT INTO org_watershed_exact VALUES ('W1',4,0,2,2019,2020);
    `);
    occ.close();

    fs.writeFileSync(paths.vernacularCsv, "scientific_name,vernacular_name_ja,source\nFx b,固定名,test\n");
  });

  afterAll(() => fs.rmSync(dir, { recursive: true, force: true }));

  it("biotaNeeds: 問い合わせ id から必要な期待値だけを選ぶ（--only で生物系を回さなければ空）", () => {
    expect(biotaNeeds(["variable_catalog", "effort_years"]).size).toBe(0);
    expect([...biotaNeeds(["species_labels", "species_catalog", "watershed_year"])].sort()).toEqual(["labels", "wsYear"]);
    for (const id of ["watershed_year", "watershed_rollup", "species_months", "species_labels", "biota_totals"]) {
      expect(BIOTA_QUERY_IDS.has(id)).toBe(true);
    }
  });

  it("不要な期待値は読まない（空の問い合わせ集合では何も読まず、存在しないパスでも落ちない）", () => {
    const bogus: BiotaPaths = { v2: "/nonexistent/v2", registry: "/nonexistent/r", ryuiki: "/nonexistent/ry", v1Occurrence: "/nonexistent/o", vernacularCsv: "/nonexistent/c" };
    expect(loadBiotaExpectations(bogus, ["effort_years", "mesh_all"])).toEqual({});
  });

  it("wsYear: exact の n/alien/redlist と species_n（学名）に、L2 の COUNT(DISTINCT taxon_id)（日付ありのみ）を足す", () => {
    const b = loadBiotaExpectations(paths, ["watershed_year"]);
    // 2020: r1(t1) r2(t1) r3(t3) → taxon 2 種。exact の species_n は 1（学名の数え方）。
    expect(b.wsYear!.get(watershedYearKey("W1", 2020))).toEqual({ n: 3, alienN: 0, redlistN: 2, speciesNameN: 1, speciesTaxonN: 2 });
    // 2019: r4(t1) → 1 種。NULL の alien/redlist は 0 に。
    expect(b.wsYear!.get(watershedYearKey("W1", 2019))).toEqual({ n: 1, alienN: 0, redlistN: 0, speciesNameN: 1, speciesTaxonN: 1 });
  });

  it("wsAll: org_watershed_exact", () => {
    const b = loadBiotaExpectations(paths, ["watershed_rollup"]);
    expect(b.wsAll!.get("W1")).toEqual({ n: 4, alienN: 0, redlistN: 2 });
  });

  it("月: v1 は period_raw の月（長さ>=7・年>=2018）、v2 は同一月に収まる記録の period_start の月", () => {
    const b = loadBiotaExpectations(paths, ["species_months"]);
    // Fx a: r1 → v1 月3・v2 月3、r2 → v1 月3 だけ（月をまたぐ）。r4/r5/r6 はどちらにも入らない。
    expect(b.monthV1!.get(binomMonthKey("Fx a", 3))).toBe(2);
    expect(b.monthV2!.get(binomMonthKey("Fx a", 3))).toBe(1);
    // Fx b: r3 は v1 では月1（UTC の period_raw）、v2 では月2（JST の period_start）。
    expect(b.monthV1!.get(binomMonthKey("Fx b", 1))).toBe(1);
    expect(b.monthV2!.get(binomMonthKey("Fx b", 1))).toBeUndefined();
    expect(b.monthV2!.get(binomMonthKey("Fx b", 2))).toBe(1);
  });

  it("labels: 台帳（CSV）が最優先、代表 taxon は summary_taxon_catalog.n が最大のもの", () => {
    const b = loadBiotaExpectations(paths, ["species_labels"]);
    expect(b.labels!.get("Fx a")).toBe("アルファ");
    expect(b.labels!.get("Fx b")).toBe("固定名");
  });

  it("undated: observed_on が NULL・空・4 桁未満の件数を出典別に", () => {
    const b = loadBiotaExpectations(paths, ["biota_totals"]);
    // gbif: NULL 1／inat: '' と '202' の 2／other_source: NULL 1（全体には数えるが gbif/inat には数えない）
    expect(b.undated).toEqual({ records: 4, gbif: 1, inat: 2 });
  });
});
