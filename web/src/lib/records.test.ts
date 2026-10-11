import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, RECORD_SET_INSERT, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { sourceAccess } from "@/lib/cube/source-meta";
import { RECORD_SET_TABLES } from "@/lib/registry/generated-source";
import { TABLE_ORIGIN } from "@/lib/table-meta";
import {
  blockingNotes,
  clampLimit,
  docNotes,
  documentsList,
  queryRecords,
  readRecordSet,
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

const put = (t: RecordSetName, pk: string | number, name: string, source: string) => RECORD_SET_INSERT[t](raw, pk, name, source);

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  db = wrapSqlite(raw);
});
afterEach(() => raw.close());

const q = (a: Partial<RecordsInput>) => queryRecords(db, a);
const ids = (r: { rows: Record<string, unknown>[] }, pk: string) => r.rows.map((x) => x[pk]);

describe("RECORD_TABLES（許可リスト）", () => {
  it.each(Object.entries(RECORD_TABLES))("%s の列がすべて実在し、主キー・検索列・source_id を含む", (_set, def) => {
    const table = def.table;
    const real = new Set(raw.prepare(`PRAGMA table_info(${table})`).all().map((c) => (c as { name: string }).name));
    const d = def as { table: string; pk: string; search: readonly string[]; cols: readonly string[]; geometry?: string; sourceless?: boolean; };
    for (const k of Object.keys((def as { exprs?: object }).exprs ?? {})) real.add(k);
    for (const c of [...d.cols, ...d.search, d.pk, ...(d.geometry ? [d.geometry] : [])]) expect(real.has(c), `${table}.${c}`).toBe(true);
    expect(d.cols).toContain(d.pk);
    if (!d.sourceless) expect(d.cols).toContain("source_id");
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
    // 出典に紐付かない record_set（documents・document_notes）は access.yaml の対象外
    const sourced = Object.entries(RECORD_TABLES).filter(([, d]) => !("sourceless" in d)).map(([k]) => k);
    expect(Object.keys(RECORD_SET_TABLES).sort()).toEqual(sourced.sort());
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
    raw.prepare("INSERT INTO sites (site_id, name, operator, watershed, geohash, treatment, is_synthetic) VALUES ('a','旧名','県','w1','xyz','t',1)").run();
    const r = await q({ source_id: "dams_kanagawa" });
    expect(ids(r, "site_id")).toEqual(["a"]);
    // 旧表 sites に行がある地点だけ、流域・管理者が付く（place の名前が優先）。観測局（旧表に無い）は NULL
    expect(r.rows[0]).toMatchObject({ name: "ダムA", operator: "県", watershed: "w1", place_id: "p:a" });
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

  it("hazard_zones: 一覧にジオメトリは無く、zone_id 指定の 1 件だけ include_geometry で返す", async () => {
    put("hazard_zones", "kyu527-0094-01:y:1", "急・長浜１", "bodik_kagoshima_dosha_amami");
    put("hazard_zones", "kyu527-0094-01:y:2", "急・長浜１", "bodik_kagoshima_dosha_amami");
    const list = await q({ source_id: "bodik_kagoshima_dosha_amami" });
    expect(list.rows).toHaveLength(2);
    for (const row of list.rows) expect(row).not.toHaveProperty("geometry_geojson");
    const one = await q({ source_id: "bodik_kagoshima_dosha_amami", id: "kyu527-0094-01:y:2", include_geometry: true });
    expect(one.rows[0].geometry_geojson).toEqual({ type: "Polygon", coordinates: [] });
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
  it("出典 enum・表 enum・limit 上限・q の長さ・strict で未知のキーを拒否", () => {
    expect(recordsInputSchema.safeParse(ok).success).toBe(true);
    expect(recordsInputSchema.safeParse({ source_id: "moe_redlist" }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, limit: 501 }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, record_set: "sqlite_master" }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ ...ok, q: "あ".repeat(17) }).success).toBe(false);
    expect(recordsInputSchema.strict().safeParse({ ...ok, columns: ["geohash"] }).success).toBe(false);
    expect(recordsInputSchema.strict().safeParse({ ...ok, where: "1=1" }).success).toBe(false);
  });

  it("行政文書（documents・document_notes）は出典に紐付かず record_set 単独で引く。source_id を付けると入力エラー", async () => {
    raw.prepare("INSERT INTO documents (doc_id, title, publisher) VALUES ('d1','文書1','県'), ('d2','文書2','国')").run();
    raw.prepare("INSERT INTO cells (doc_id) VALUES ('d1'), ('d1')").run();
    const ins = raw.prepare("INSERT INTO notes (note_id, doc_id, kind, page, blocks_timeseries) VALUES (?,?,?,?,?)");
    ins.run("n1", "d1", "定義変更", 3, 1);
    ins.run(null, "d1", "脚注", 1, 0);
    ins.run("n3", "d2", "定義変更", 2, 1);
    const docs = await q({ record_set: "documents" });
    expect(docs.source_id).toBeNull();
    expect(docs.n_total).toBe(2); // 出典に紐付かない表は表全体の行数
    expect(docs.rows.find((r) => r.doc_id === "d1")).toMatchObject({ n_cells: 2, n_notes: 2, n_blocking: 1 });
    expect(docs.rows.find((r) => r.doc_id === "d2")).toMatchObject({ n_cells: 0, n_notes: 1, n_blocking: 1 });
    expect(Object.keys(docs.rows[0])).not.toContain("local_path");
    // note_id が NULL の注記も、行の note_rowid で並び・ページングし・id で引ける
    const all = await q({ record_set: "document_notes", limit: 2 });
    expect(all.truncated).toBe(true);
    const rest = await q({ record_set: "document_notes", limit: 2, after: all.next_after as string });
    expect(all.rows.length + rest.rows.length).toBe(3);
    const nullNote = [...all.rows, ...rest.rows].find((r) => r.note_id === null)!;
    expect(ids(await q({ record_set: "document_notes", id: String(nullNote.note_rowid) }), "note_rowid")).toEqual([nullNote.note_rowid]);
    expect(ids(await q({ record_set: "document_notes", q: "d2" }), "note_id")).toEqual(["n3"]); // q は doc_id にも効く
    await expect(q({ record_set: "documents", source_id: "dams_kanagawa" })).rejects.toThrow(RecordsInputError);
    await expect(q({ record_set: "sites" })).rejects.toThrow(RecordsInputError);
    // 画面用の関数も同じ定義・同じ builder を通る
    expect((await documentsList(db)).map((d) => d.doc_id)).toEqual(["d1", "d2"]); // n_cells の多い順
    const warnings = await blockingNotes(db, await documentsList(db));
    expect(warnings.map((n) => [n.doc_title, n.kind])).toEqual([["文書1", "定義変更"], ["文書2", "定義変更"]]);
    expect((await docNotes(db, "d1")).map((n) => n.note_id)).toEqual(["n1", null]);
  });

  it("limit は builder で丸める（NaN・負・0 は既定値、上限超は上限）", () => {
    expect(clampLimit(Number.NaN)).toBe(100);
    expect(clampLimit(-5)).toBe(100);
    expect(clampLimit(0)).toBe(100);
    expect(clampLimit(10_000)).toBe(500);
    expect(clampLimit(7.9)).toBe(7);
    expect(clampLimit(Number.NaN, 2000, 5000)).toBe(2000);
    expect(clampLimit(9999, 2000, 5000)).toBe(5000);
  });
});

describe("readRecordSet（地図用。get_records と同じ列定義）", () => {
  it("絞り込み・並び・上限・ジオメトリ（文字列のまま）。許可リスト外の列は例外", async () => {
    raw.prepare("INSERT INTO protected_areas (area_id, name_ja, category_code, area_ha, lat, lon, source_id) VALUES ('a','A','park',1,35,139,'s'),('b','B','park',5,35,139,'s'),('c','C','tree',9,35,139,'s')").run();
    const r = await readRecordSet(db, "protected_areas", { eq: [{ col: "category_code", value: "park" }], order: [{ col: "area_ha", desc: true }], limit: 1 });
    expect(r.map((x) => x.area_id)).toEqual(["b"]);
    put("river_segments", "r1", "相模川", "geoshape_sagami_river");
    const g = await readRecordSet(db, "river_segments", { order: [{ col: "feature_id" }], withGeometry: true });
    expect(typeof g[0].geometry_geojson).toBe("string");
    await expect(readRecordSet(db, "river_segments", { order: [{ col: "x; DROP TABLE sites" }] })).rejects.toThrow();
    await expect(readRecordSet(db, "protected_areas", { order: [{ col: "area_id" }], withGeometry: true })).rejects.toThrow();
  });
});
