import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { TABLE_ORIGIN } from "@/lib/table-meta";
import { caveatBody } from "@/lib/registry/lookup-client";
import type { CaveatKey } from "@/lib/registry/generated-client";
import { ednaCaveats, ednaCaveatsForSources, ednaInputSchema, queryEdna, type EdnaInput } from "./edna";

let raw: Database.Database;
let db: ReturnType<typeof wrapSqlite>;

const SITE = `INSERT INTO edna_sites (site_key, dataset_file, program, assay, fiscal_year, site_id_raw, water_system_ja, tributary_ja, municipality_ja,
  collected_on, lat, lon, coord_source, coordinate_uncertainty_m, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'kanagawa_edna','ref')`;
const READ = `INSERT INTO edna_reads (read_id, site_key, name_adopted, reads, is_detected, name_key, taxon_id, source_id)
  VALUES (?,?,?,?,?,?,?,'kanagawa_edna')`;

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  raw.prepare(`INSERT INTO taxon (taxon_id, scientific_name, canonical_binomial, rank, vernacular_name_ja) VALUES ('t:eel','Anguilla japonica','Anguilla japonica','species','ニホンウナギ')`).run();
  raw.prepare(`INSERT INTO taxon (taxon_id, scientific_name, canonical_binomial, rank, vernacular_name_ja) VALUES ('t:ayu','Plecoglossus altivelis','Plecoglossus altivelis','species','アユ')`).run();
  raw.prepare(SITE).run("f1:A1", "f1.xlsx", "kenmin", "fish_12S", 2021, "A1", "相模川", "中津川", "厚木市", "2021-06-01", 35.4, 139.3, "map_image", 500);
  raw.prepare(SITE).run("f1:A2", "f1.xlsx", "kenmin", "fish_12S", 2021, "A2", "酒匂川", null, "小田原市", "2022-06-01", null, null, "none", null);
  raw.prepare(READ).run("f1:A1:1", "f1:A1", "ニホンウナギ", 0, 0, "k1", "t:eel");
  raw.prepare(READ).run("f1:A1:2", "f1:A1", "アユ", 120, 1, "k2", "t:ayu");
  raw.prepare(READ).run("f1:A2:1", "f1:A2", "ニホンウナギ", 7, 1, "k1", "t:eel");
  raw.prepare(READ).run("f1:A2:2", "f1:A2", "アユ", 0, 0, "k2", "t:ayu");
  db = wrapSqlite(raw);
});
afterEach(() => raw.close());

const q = (a: EdnaInput = {}) => queryEdna(db, a);
const ids = (r: { rows: Record<string, unknown>[] }) => r.rows.map((x) => x.read_id);

describe("queryEdna", () => {
  it("既定は不検出も返す。地点の座標・誤差・根拠と元ファイルが付く", async () => {
    const r = await q();
    expect(ids(r)).toEqual(["f1:A1:1", "f1:A1:2", "f1:A2:1", "f1:A2:2"]);
    expect(r.rows[0]).toMatchObject({
      is_detected: 0, reads: 0, scientific_name: "Anguilla japonica", vernacular_name_ja: "ニホンウナギ",
      lat: 35.4, coordinate_uncertainty_m: 500, coord_source: "map_image", dataset_file: "f1.xlsx", fiscal_year: 2021,
    });
    expect(r.rows[2]).toMatchObject({ lat: null, coord_source: "none" });
  });

  it("detected_only は検出だけ", async () => {
    expect(ids(await q({ detected_only: true }))).toEqual(["f1:A1:2", "f1:A2:1"]);
  });

  it("地点・水系/市町村・種・採水日で絞れる", async () => {
    expect(ids(await q({ site_key: "f1:A2" }))).toEqual(["f1:A2:1", "f1:A2:2"]);
    expect(ids(await q({ area: "相模" }))).toEqual(["f1:A1:1", "f1:A1:2"]);
    expect(ids(await q({ area: "小田原" }))).toEqual(["f1:A2:1", "f1:A2:2"]);
    expect(ids(await q({ taxon_id: "t:ayu" }))).toEqual(["f1:A1:2", "f1:A2:2"]);
    expect(ids(await q({ species: "Anguilla" }))).toEqual(["f1:A1:1", "f1:A2:1"]);
    expect(ids(await q({ species: "アユ", detected_only: true }))).toEqual(["f1:A1:2"]);
    expect(ids(await q({ from: "2022-01-01" }))).toEqual(["f1:A2:1", "f1:A2:2"]);
    expect(ids(await q({ to: "2021-12-31" }))).toEqual(["f1:A1:1", "f1:A1:2"]);
    expect((await q({ area: "100%" })).rows).toEqual([]); // LIKE のメタ文字は効かない
  });

  it("ページング: limit と offset、has_more", async () => {
    const p1 = await q({ limit: 3 });
    expect(p1.rows).toHaveLength(3);
    expect(p1.has_more).toBe(true);
    const p2 = await q({ limit: 3, offset: 3 });
    expect(ids(p2)).toEqual(["f1:A2:2"]);
    expect(p2.has_more).toBe(false);
  });

  it("by_site: 地点×採水ごとの検出分類群数とリード数", async () => {
    const r = await q({ mode: "by_site" });
    expect(r.rows.map((x) => [x.site_key, x.n_taxa_tested, x.n_taxa_detected, x.reads_total])).toEqual([
      ["f1:A1", 2, 1, 120],
      ["f1:A2", 2, 1, 7],
    ]);
  });

  it("by_taxon: 調べた回数と検出した回数（不検出を分母に含む）", async () => {
    const r = await q({ mode: "by_taxon" });
    expect(r.rows.map((x) => [x.taxon_id, x.n_events, x.n_detected_events, x.n_sites_detected])).toEqual([
      ["t:ayu", 2, 1, 1],
      ["t:eel", 2, 1, 1],
    ]);
  });
});

describe("入力スキーマ", () => {
  it("未知の引数・不正な日付・上限超過は弾く。z.tuple（prefixItems）は無い", () => {
    expect(ednaInputSchema.safeParse({ mode: "nope" }).success).toBe(false);
    expect(ednaInputSchema.safeParse({ from: "2021/06/01" }).success).toBe(false);
    expect(ednaInputSchema.safeParse({ limit: 100000 }).success).toBe(false);
    expect(ednaInputSchema.safeParse({ area: "あ".repeat(16) }).success).toBe(false);
    expect(ednaInputSchema.safeParse({ unknown_arg: 1 }).success).toBe(true); // 既存ツールと同じ（zod 既定は余分なキーを捨てる）
    expect(JSON.stringify(ednaInputSchema.toJSONSchema())).not.toContain("prefixItems");
  });
});

describe("D1 への載せ方", () => {
  it("2表が TABLE_ORIGIN（シード対象の目録）にあり、migration で作られている。detections は載せない", () => {
    expect(TABLE_ORIGIN.edna_sites).toBe("main");
    expect(TABLE_ORIGIN.edna_reads).toBe("main");
    expect(TABLE_ORIGIN.edna_detections).toBeUndefined();
    const names = (raw.prepare("SELECT name FROM sqlite_master WHERE type='table'").all() as { name: string }[]).map((r) => r.name);
    expect(names).toEqual(expect.arrayContaining(["edna_sites", "edna_reads"]));
    expect(names).not.toContain("edna_detections");
  });
});

describe("注意書き", () => {
  it("dataset=kanagawa_edna の facet で registry から引く（4件。リード数・推定座標・年度差・不検出）", () => {
    const c = ednaCaveats();
    expect(c.map((x) => x.key).sort()).toEqual(["ednaCoords", "ednaNonDetect", "ednaReads", "ednaYearBasis"]);
    const body = c.map((x) => caveatBody(x.key as CaveatKey)).join("\n");
    expect(body).toMatch(/リード数/);
    expect(body).toMatch(/推定/);
    expect(body).toMatch(/不検出/);
  });
  it("出典に kanagawa_edna を含むときだけ付く", () => {
    expect(ednaCaveatsForSources(["kanagawa_edna", "inaturalist_kanagawa"])).toHaveLength(4);
    expect(ednaCaveatsForSources(["inaturalist_kanagawa"])).toEqual([]);
  });
});
