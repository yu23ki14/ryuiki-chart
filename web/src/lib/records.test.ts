import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { sourceAccess } from "@/lib/cube/source-meta";
import { RECORD_SET_TABLES } from "@/lib/registry/generated-source";
import { TABLE_ORIGIN } from "@/lib/table-meta";
import {
  queryRecords,
  RecordsInputError,
  recordsInputSchema,
  recordSetsOf,
  RECORD_SOURCE_IDS,
  RECORD_TABLES,
  type RecordsInput,
  type RecordSetName,
} from "./records";

let raw: Database.Database;
let db: ReturnType<typeof wrapSqlite>;

/** 表ごとに、主キー・名称・出典だけを入れる最小の INSERT（NOT NULL 列があればここで埋める）。 */
const INSERT: Record<RecordSetName, string> = {
  sites: "INSERT INTO sites (site_id, name, source_id) VALUES (?, ?, ?)",
  protected_areas: "INSERT INTO protected_areas (area_id, name_ja, source_id) VALUES (?, ?, ?)",
  vegetation:
    'INSERT INTO vegetation_polygons (feature_id, legend_name_ja, source_id, geometry_geojson) VALUES (?, ?, ?, \'{"type":"Polygon","coordinates":[]}\')',
  river_segments:
    'INSERT INTO river_segments (feature_id, name_ja, source_id, geometry_geojson) VALUES (?, ?, ?, \'{"type":"LineString","coordinates":[]}\')',
  mammal_mesh: "INSERT INTO mammal_mesh (id, species_ja, source_id) VALUES (?, ?, ?)",
  sightings: "INSERT INTO wildlife_sightings (sighting_id, species_ja, source_id) VALUES (?, ?, ?)",
  assessments: "INSERT INTO taxon_assessment (assessment_id, vernacular_name_ja_raw, source_id, list_id) VALUES (?, ?, ?, 'rl')",
};

const put = (t: RecordSetName, pk: string | number, name: string, source: string) => raw.prepare(INSERT[t]).run(pk, name, source);

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  db = wrapSqlite(raw);
});
afterEach(() => raw.close());

const q = (a: Partial<RecordsInput> & Pick<RecordsInput, "source_id">) => queryRecords(db, a);
const ids = (r: { rows: Record<string, unknown>[] }, pk: string) => r.rows.map((x) => x[pk]);

describe("RECORD_TABLES（許可リスト）", () => {
  it.each(Object.entries(RECORD_TABLES))("%s の列がすべて実在し、主キー・検索列・source_id を含む", (_set, def) => {
    const table = def.table;
    const real = new Set(raw.prepare(`PRAGMA table_info(${table})`).all().map((c) => (c as { name: string }).name));
    const d = def as { table: string; pk: string; search: readonly string[]; cols: readonly string[]; geometry?: string };
    for (const c of [...d.cols, ...d.search, d.pk, ...(d.geometry ? [d.geometry] : [])]) expect(real.has(c), `${table}.${c}`).toBe(true);
    expect(d.cols).toContain(d.pk);
    expect(d.cols).toContain("source_id");
    expect(d.cols).not.toContain(d.geometry ?? "(none)");
    expect(new Set(d.cols).size).toBe(d.cols.length);
  });

  it("除外した列（内部フラグ・ジオメトリ）は許可リストに無い", () => {
    for (const c of ["geohash", "treatment", "is_synthetic"]) expect(RECORD_TABLES.sites.cols).not.toContain(c);
    expect(RECORD_TABLES.vegetation.cols).not.toContain("geometry_geojson");
    expect(RECORD_TABLES.river_segments.cols).not.toContain("geometry_geojson");
  });

  it("全表が D1 の表（TABLE_ORIGIN に載っている）", () => {
    for (const t of Object.keys(RECORD_TABLES)) expect(TABLE_ORIGIN, t).toHaveProperty(RECORD_TABLES[t as keyof typeof RECORD_TABLES].table);
  });

  it("出典 × record_set の宣言（SOURCE_ACCESS）は許可リストの record_set だけを指し、record_set → 表の対応は access.yaml の 1 か所", () => {
    expect(Object.keys(RECORD_SET_TABLES).sort()).toEqual(Object.keys(RECORD_TABLES).sort());
    for (const s of RECORD_SOURCE_IDS) {
      const sets = recordSetsOf(s);
      expect(sets.length, s).toBeGreaterThan(0);
      for (const t of sets) expect(RECORD_TABLES, `${s}/${t}`).toHaveProperty(t);
    }
  });
});

describe("queryRecords", () => {
  it("宣言済みの全 (出典, 表) で 1 行以上返り、行の source_id は出典を含む", async () => {
    let n = 1;
    for (const s of RECORD_SOURCE_IDS) for (const t of recordSetsOf(s) as RecordSetName[]) put(t, t === "mammal_mesh" ? n++ : `${s}:1`, "名", s);
    for (const s of RECORD_SOURCE_IDS) {
      for (const t of recordSetsOf(s) as RecordSetName[]) {
        const r = await q({ source_id: s, record_set: t });
        expect(r.rows.length, `${s}/${t}`).toBeGreaterThanOrEqual(1);
        expect(r.record_set).toBe(t);
        for (const row of r.rows) expect(String(row.source_id).split("|")).toContain(s);
      }
    }
  });

  it("他の出典の行は返らない。返す列は許可リストだけ（SELECT * でない）", async () => {
    put("sites", "a", "ダムA", "dams_kanagawa");
    put("sites", "b", "気象B", "jma_stations_kanagawa");
    raw.prepare("UPDATE sites SET geohash='xyz', treatment='t', is_synthetic=1 WHERE site_id='a'").run();
    const r = await q({ source_id: "dams_kanagawa" });
    expect(ids(r, "site_id")).toEqual(["a"]);
    expect(Object.keys(r.rows[0]).sort()).toEqual([...RECORD_TABLES.sites.cols].sort());
  });

  it("複合の値を持つ表（compositeSource）だけ、a|b を区切りの完全一致で照合する。どちらの出典からも見え、前方・後方一致の別出典には見えない", async () => {
    const def = RECORD_TABLES.assessments as { compositeSource?: boolean };
    def.compositeSource = true;
    try {
      await compositeCase();
    } finally {
      delete def.compositeSource;
    }
    // 既定（複合の値を持たない表）は source_id = ? の完全一致。a|b の行は a では引けない
    expect(ids(await q({ source_id: "moe_ias_list" }), "assessment_id")).toEqual(["x2"]);
  });

  async function compositeCase() {
    put("assessments", "x1", "両方", "kanagawa_redlist|moe_ias_list");
    put("assessments", "x2", "IASだけ", "moe_ias_list");
    put("assessments", "x3", "別物", "moe_ias_list_old");
    put("assessments", "x4", "別物2", "my_moe_ias_list");
    expect(ids(await q({ source_id: "moe_ias_list" }), "assessment_id")).toEqual(["x1", "x2"]);
    const other = await queryRecords(db, { source_id: "kanagawa_redlist", record_set: "assessments" });
    expect(ids(other, "assessment_id")).toEqual(["x1"]);
  }

  it("id（完全一致）と q（部分一致。LIKE のメタ文字は効かない）", async () => {
    put("sites", "s1", "城山ダム", "dams_kanagawa");
    put("sites", "s2", "宮ヶ瀬ダム", "dams_kanagawa");
    put("sites", "s3", "100%", "dams_kanagawa");
    expect(ids(await q({ source_id: "dams_kanagawa", id: "s2" }), "site_id")).toEqual(["s2"]);
    expect(ids(await q({ source_id: "dams_kanagawa", q: "ダム" }), "site_id")).toEqual(["s1", "s2"]);
    expect(ids(await q({ source_id: "dams_kanagawa", q: "%" }), "site_id")).toEqual(["s3"]);
    expect(ids(await q({ source_id: "dams_kanagawa", q: "_" }), "site_id")).toEqual([]);
    // n_total は q・id なしのときだけ（事前計算。sites のこの出典の行数）
    expect((await q({ source_id: "dams_kanagawa", q: "ダム" })).n_total).toBeNull();
    expect((await q({ source_id: "dams_kanagawa", id: "s1" })).n_total).toBeNull();
    expect((await q({ source_id: "dams_kanagawa" })).n_total).toBe(sourceAccess("dams_kanagawa")?.recordSetRows.sites);
  });

  it("整数の主キー（mammal_mesh）でも id で引け、主キー昇順で並ぶ", async () => {
    for (const i of [10, 2, 33]) put("mammal_mesh", i, "タヌキ", "biodic_mammal_mesh_kanagawa");
    expect(ids(await q({ source_id: "biodic_mammal_mesh_kanagawa" }), "id")).toEqual([2, 10, 33]);
    expect(ids(await q({ source_id: "biodic_mammal_mesh_kanagawa", id: "10" }), "id")).toEqual([10]);
  });

  it("limit/offset のページングで重複・欠落が無い。truncated は limit を超えるときだけ", async () => {
    for (let i = 1; i <= 7; i++) put("protected_areas", `a${i}`, `区${i}`, "hiratsuka_parks");
    const seen: unknown[] = [];
    for (let offset = 0; ; offset += 3) {
      const r = await q({ source_id: "hiratsuka_parks", limit: 3, offset });
      expect(r.rows.length).toBeLessThanOrEqual(3);
      seen.push(...ids(r, "area_id"));
      if (!r.truncated) break;
    }
    expect(seen).toEqual(["a1", "a2", "a3", "a4", "a5", "a6", "a7"]);
  });

  it("after（keyset）で最後まで辿れる。next_after は truncated のときだけ。offset と併用は入力エラー", async () => {
    for (const i of [10, 2, 33, 4, 5]) put("mammal_mesh", i, "タヌキ", "biodic_mammal_mesh_kanagawa");
    const seen: unknown[] = [];
    let after: string | undefined;
    for (;;) {
      const r = await q({ source_id: "biodic_mammal_mesh_kanagawa", limit: 2, after });
      seen.push(...ids(r, "id"));
      if (!r.truncated) {
        expect(r.next_after).toBeNull();
        break;
      }
      after = r.next_after as string;
    }
    expect(seen).toEqual([2, 4, 5, 10, 33]);
    await expect(q({ source_id: "biodic_mammal_mesh_kanagawa", after: "2", offset: 1 })).rejects.toThrow(RecordsInputError);
  });

  it("ジオメトリ: 一覧では返さない。id 指定の 1 件だけ include_geometry で返す", async () => {
    put("vegetation", "v1", "ブナ", "biodic_veg2024_kanagawa");
    put("vegetation", "v2", "スギ", "biodic_veg2024_kanagawa");
    const list = await q({ source_id: "biodic_veg2024_kanagawa" });
    for (const row of list.rows) expect(row).not.toHaveProperty("geometry_geojson");
    const one = await q({ source_id: "biodic_veg2024_kanagawa", id: "v1", include_geometry: true });
    expect(one.rows[0].geometry_geojson).toEqual({ type: "Polygon", coordinates: [] });
    await expect(q({ source_id: "biodic_veg2024_kanagawa", include_geometry: true })).rejects.toThrow(RecordsInputError);
    await expect(q({ source_id: "biodic_veg2024_kanagawa", q: "ブ", include_geometry: true })).rejects.toThrow(RecordsInputError);
    await expect(q({ source_id: "dams_kanagawa", id: "x", include_geometry: true })).rejects.toThrow(RecordsInputError);
  });

  it("vegetation を limit=500 で引いても geometry を含まず 500KB 以内", async () => {
    const ins = raw.prepare("INSERT INTO vegetation_polygons (feature_id, legend_name_ja, source_id, geometry_geojson) VALUES (?,?,?,?)");
    const big = JSON.stringify({ type: "Polygon", coordinates: [Array.from({ length: 400 }, (_, i) => [139 + i / 1000, 35 + i / 1000])] });
    for (let i = 0; i < 600; i++) ins.run(`v${String(i).padStart(4, "0")}`, "ブナ林", "biodic_veg2024_kanagawa", big);
    const r = await q({ source_id: "biodic_veg2024_kanagawa", limit: 500 });
    expect(r.rows).toHaveLength(500);
    expect(r.truncated).toBe(true);
    expect(JSON.stringify(r.rows).length).toBeLessThan(500_000);
    expect(JSON.stringify(r.rows)).not.toContain("coordinates");
  });

  it("出典に無い表・対象外の出典は RecordsInputError", async () => {
    await expect(q({ source_id: "dams_kanagawa", record_set: "assessments" })).rejects.toThrow(RecordsInputError);
    await expect(queryRecords(db, { source_id: "nope" as never })).rejects.toThrow(RecordsInputError);
  });
});

describe("recordsInputSchema", () => {
  const ok = { source_id: "dams_kanagawa" };
  it("source_id 必須・出典 enum・表 enum・limit 上限・q の長さ・strict で未知のキーを拒否", () => {
    expect(recordsInputSchema.safeParse(ok).success).toBe(true);
    expect(recordsInputSchema.safeParse({}).success).toBe(false);
    expect(recordsInputSchema.safeParse({ source_id: "moe_redlist" }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, limit: 501 }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, record_set: "sqlite_master" }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, q: "あ".repeat(17) }).success).toBe(false);
    expect(recordsInputSchema.strict().safeParse({ ...ok, columns: ["geohash"] }).success).toBe(false);
    expect(recordsInputSchema.strict().safeParse({ ...ok, where: "1=1" }).success).toBe(false);
  });
});
