import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, RECORD_SET_INSERT, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { sourceAccess } from "@/lib/cube/source-meta";
import { RECORD_SET_TABLES } from "@/lib/registry/generated-source";
import { issueLabel, periodicalCitation, pdfPageUrl } from "@/lib/periodical";
import { ARTICLE_TOPIC } from "@/lib/registry/generated-client";
import { TABLE_ORIGIN } from "@/lib/table-meta";
import {
  blockingNotes,
  clampLimit,
  countRecordsBy,
  INCLUDE_BODY_MAX_ROWS,
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
    const body = (def as { bodyCol?: string }).bodyCol;
    if (body) {
      expect(real.has(body), `${table}.${body}`).toBe(true);
      expect(d.cols, "本文は一覧の既定の列に入れない").not.toContain(body);
    }
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

  it("protected_areas: 一覧にジオメトリは無く、id 指定の 1 件だけ include_geometry で返す。神奈川の行は null", async () => {
    const ins = raw.prepare("INSERT INTO protected_areas (area_id, name_ja, source_id, geometry_geojson) VALUES (?,?,?,?)");
    ins.run("pa1", "奄美の自然公園", "nlni_a10_natparks_amami", '{"type":"Polygon","coordinates":[]}');
    ins.run("pa2", "神奈川の公園", "hiratsuka_parks", null);
    const list = await q({ source_id: "nlni_a10_natparks_amami" });
    expect(list.rows).toHaveLength(1);
    for (const row of list.rows) expect(row).not.toHaveProperty("geometry_geojson");
    const one = await q({ source_id: "nlni_a10_natparks_amami", id: "pa1", include_geometry: true });
    expect(one.rows[0].geometry_geojson).toEqual({ type: "Polygon", coordinates: [] });
    const none = await q({ source_id: "hiratsuka_parks", id: "pa2", include_geometry: true });
    expect(none.rows[0].geometry_geojson).toBeNull();
    await expect(q({ source_id: "nlni_a10_natparks_amami", include_geometry: true })).rejects.toThrow(RecordsInputError);
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
    await expect(readRecordSet(db, "sites", { order: [{ col: "site_id" }], withGeometry: true })).rejects.toThrow();
  });

  it("osm_waterways / osm_water_structures: 出典で絞り、ジオメトリは id 指定のときだけ。structures は source_ref で引く", async () => {
    put("osm_waterways", 101, "相模川", "osm_waterways");
    put("osm_waterways", 102, "酒匂川", "osm_waterways");
    const l = await q({ record_set: "osm_waterways", source_id: "osm_waterways", q: "相模" });
    expect(ids(l, "way_id")).toEqual([101]);
    expect(l.rows[0]).not.toHaveProperty("geometry_geojson");
    const one = await q({ record_set: "osm_waterways", source_id: "osm_waterways", id: "101", include_geometry: true });
    expect(one.rows[0].geometry_geojson).toEqual({ type: "LineString", coordinates: [] });
    put("osm_water_structures", "osm:node/10", "城山ダム", "osm_water_structures");
    put("osm_water_structures", "osm:node/11", "堰", "osm_water_structures");
    const s = await q({ record_set: "osm_water_structures", source_id: "osm_water_structures" });
    expect(ids(s, "source_ref")).toEqual(["osm:node/10", "osm:node/11"]);
    expect(ids(await q({ record_set: "osm_water_structures", source_id: "osm_water_structures", id: "osm:node/11" }), "name_ja")).toEqual(["堰"]);
    await expect(q({ record_set: "osm_waterways", source_id: "geoshape_sagami_river" })).rejects.toThrow(RecordsInputError);
  });

  it("documents: n_cells は置き換え済み（superseded=1）を数えない", async () => {
    raw.prepare("INSERT INTO documents (doc_id, title) VALUES ('d1','文書1'),('d2','文書2')").run();
    const ins = raw.prepare("INSERT INTO cells (doc_id, row_key, col_key, value, superseded) VALUES (?,?,?,?,?)");
    ins.run("d1", "a", "値", "1", 0);
    ins.run("d1", "b", "値", "2", 0);
    ins.run("d1", "a", "値", "0", 1);
    ins.run("d2", "a", "値", "0", 1); // 旧行だけの文書は 0
    const rows = await documentsList(db);
    expect(Object.fromEntries(rows.map((r) => [r.doc_id, r.n_cells]))).toEqual({ d1: 2, d2: 0 });
  });

  it("document_cells: superseded=0 の行だけ、doc_id で絞って読む。q は doc_id/row_key に効き、n_total も置き換え済みを除く", async () => {
    raw.prepare("INSERT INTO documents (doc_id, title) VALUES ('d1','文書1'),('d2','文書2')").run();
    const ins = raw.prepare("INSERT INTO cells (doc_id, row_key, col_key, value, fiscal_year, superseded) VALUES (?,?,?,?,?,?)");
    ins.run("d1", "総雨量", "値", "1000", null, 0);
    ins.run("d1", "総雨量", "値", "900", null, 1); // 置き換え済み
    ins.run("d1", "死者", "値", "3", null, 0);
    ins.run("d2", "総雨量", "値", "5", 2010, 0);
    const r = await readRecordSet(db, "document_cells", { eq: [{ col: "doc_id", value: "d1" }], select: ["row_key", "value"], order: [{ col: "row_key" }] });
    expect(r).toEqual([{ row_key: "死者", value: "3" }, { row_key: "総雨量", value: "1000" }]);
    const g = await q({ record_set: "document_cells", q: "d2" });
    expect(g.source_id).toBeNull();
    expect(ids(g, "value")).toEqual(["5"]);
    expect((await q({ record_set: "document_cells" })).n_total).toBeNull(); // 12 万行の表は全件 count しない
    expect((await q({ record_set: "document_cells" })).rows).toHaveLength(3); // 置き換え済みは除く
    await expect(q({ record_set: "document_cells", source_id: "dams_kanagawa" })).rejects.toThrow(RecordsInputError);
    expect(recordsInputSchema.safeParse({ record_set: "document_cells" }).success).toBe(true);
  });

  it("document_cells: doc_id の完全一致で絞れる（q の 50 バイト制限に当たらない長い doc_id でも）。出典付きの表では使えない", async () => {
    const long = "kanagawa_river_monitoring_h20_sagami_results_" + "x".repeat(40); // `_` が多く q には入らない長さ
    raw.prepare("INSERT INTO documents (doc_id, title) VALUES (?, 't'), ('other', 'o')").run(long);
    const ins = raw.prepare("INSERT INTO cells (doc_id, row_key, col_key, value, superseded) VALUES (?,?,?,?,?)");
    ins.run(long, "a", "値", "1", 0);
    ins.run(long, "b", "値", "2", 1); // 置き換え済み
    ins.run("other", "a", "値", "3", 0);
    const r = await q({ record_set: "document_cells", doc_id: long });
    expect(ids(r, "doc_id")).toEqual([long]);
    expect(r.n_total).toBeNull();
    expect(recordsInputSchema.safeParse({ record_set: "document_cells", q: long }).success).toBe(false);
    expect(recordsInputSchema.safeParse({ record_set: "document_cells", doc_id: long }).success).toBe(true);
    await expect(q({ record_set: "sites", source_id: "dams_kanagawa", doc_id: "d" })).rejects.toThrow(RecordsInputError);
  });
});

describe("countRecordsBy / range（地図・物語用）", () => {
  const hz = (id: string, kind: string, ph: string, muni: string, lat: number, lon: number) =>
    raw
      .prepare("INSERT INTO hazard_zones (zone_id, zone_kind_ja, phenomenon_ja, municipality_ja, centroid_lat, centroid_lon, source_id) VALUES (?,?,?,?,?,?,'s')")
      .run(id, kind, ph, muni, lat, lon);

  it("groupBy ごとの件数を返し、合計は行数と一致する。許可リスト外の列・空の groupBy・対象外の表は例外", async () => {
    hz("z1", "警戒区域", "土石流", "奄美市", 28.3, 129.5);
    hz("z2", "警戒区域", "土石流", "奄美市", 28.3, 129.5);
    hz("z3", "特別警戒区域", "急傾斜地の崩壊", "龍郷町", 28.4, 129.6);
    const r = await countRecordsBy(db, "hazard_zones", ["municipality_ja", "phenomenon_ja", "zone_kind_ja"]);
    expect(r).toEqual([
      { municipality_ja: "奄美市", phenomenon_ja: "土石流", zone_kind_ja: "警戒区域", n: 2 },
      { municipality_ja: "龍郷町", phenomenon_ja: "急傾斜地の崩壊", zone_kind_ja: "特別警戒区域", n: 1 },
    ]);
    expect(r.reduce((a, x) => a + x.n, 0)).toBe(3);
    expect(await countRecordsBy(db, "hazard_zones", ["zone_kind_ja"], { eq: [{ col: "municipality_ja", value: "奄美市" }] })).toEqual([{ zone_kind_ja: "警戒区域", n: 2 }]);
    await expect(countRecordsBy(db, "hazard_zones", ["area_m2"])).rejects.toThrow();
    await expect(countRecordsBy(db, "hazard_zones", [])).rejects.toThrow();
    await expect(countRecordsBy(db, "hazard_zones", ["municipality_ja; DROP TABLE sites"])).rejects.toThrow();
    await expect(countRecordsBy(db, "sites", ["zone"])).rejects.toThrow();
    await expect(countRecordsBy(db, "protected_areas", ["category_code", "source_id"])).resolves.toEqual([]);
  });

  it("range: 許可リストの数値列だけ。両端を含む。許可リスト外・非有限は例外", async () => {
    hz("z1", "警戒区域", "土石流", "奄美市", 28.30, 129.50);
    hz("z2", "警戒区域", "土石流", "奄美市", 28.40, 129.50);
    const inRange = await readRecordSet(db, "hazard_zones", {
      range: [{ col: "centroid_lat", min: 28.3, max: 28.35 }, { col: "centroid_lon", min: 129, max: 130 }],
      order: [{ col: "zone_id" }],
      select: ["zone_id"],
    });
    expect(inRange.map((x) => x.zone_id)).toEqual(["z1"]);
    await expect(readRecordSet(db, "hazard_zones", { range: [{ col: "area_m2", min: 0, max: 1 }], order: [{ col: "zone_id" }] })).rejects.toThrow();
    await expect(readRecordSet(db, "hazard_zones", { range: [{ col: "centroid_lat", min: Number.NaN, max: 1 }], order: [{ col: "zone_id" }] })).rejects.toThrow();
    await expect(readRecordSet(db, "vegetation", { range: [{ col: "centroid_lat", min: 0, max: 1 }], order: [{ col: "feature_id" }] })).rejects.toThrow();
  });
});

describe("定期刊行物（periodical_issues・document_articles）", () => {
  const SRC = "tatsugo_koho_amami";

  const SERIES_LICENSE = "著作権は龍郷町に帰属（テスト用の文言）";
  const BODY1 = "秋名の川で外来種のカダヤシが見つかりました。駆除にご協力ください。";
  function seedPeriodical() {
    raw.prepare("INSERT INTO periodical_series (series_id, source_id, title, publisher, license) VALUES ('tatsugo_koho', ?, '広報たつごう', '龍郷町', ?)").run(SRC, SERIES_LICENSE);
    const iss = raw.prepare("INSERT INTO periodical_issues (issue_id, series_id, source_id, kind, year_month, year_month_to, fiscal_year, label_raw, n_files) VALUES (?,?,?,?,?,?,?,?,?)");
    iss.run("tatsugo_koho_202412", "tatsugo_koho", SRC, "monthly", "2024-12", null, 2024, "広報たつごう 2024年12月号", 2);
    iss.run("tatsugo_koho_201904", "tatsugo_koho", SRC, "monthly", "2019-04", "2019-05", 2019, "広報たつごう 2019年4・5月合併号", 1);
    iss.run("tatsugo_koho_201502s", "tatsugo_koho", SRC, "supplement", "2015-02", null, 2014, "別冊", 1);
    const doc = raw.prepare("INSERT INTO documents (doc_id, title, url) VALUES (?,?,?)");
    doc.run("tatsugo_koho_202412_p1", "広報たつごう 2024年12月号（その1）", "https://example.test/koho_202412_1.pdf");
    doc.run("tatsugo_koho_202412_p2", "広報たつごう 2024年12月号（その2）", "https://example.test/koho_202412_2.pdf");
    doc.run("tatsugo_koho_201904", "広報たつごう 2019年4・5月合併号", "https://example.test/koho_201904.pdf");
    const f = raw.prepare("INSERT INTO periodical_issue_files (doc_id, issue_id, part_no, page_offset, download_url) VALUES (?,?,?,?,?)");
    f.run("tatsugo_koho_202412_p1", "tatsugo_koho_202412", 1, 0, "https://example.test/koho_202412_1.pdf");
    f.run("tatsugo_koho_202412_p2", "tatsugo_koho_202412", 2, 24, "https://example.test/koho_202412_2.pdf");
    f.run("tatsugo_koho_201904", "tatsugo_koho_201904", 1, 0, "https://example.test/koho_201904.pdf");
    const art = raw.prepare(
      "INSERT INTO document_articles (article_id, issue_id, doc_id, source_id, kind, page_from, page_to, issue_page_from, issue_page_to, title, body_text, event_dates, extractor, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    );
    art.run("a1", "tatsugo_koho_202412", "tatsugo_koho_202412_p2", SRC, "article", 3, 3, 27, 27, "外来種を見かけたら", BODY1, '[{"raw":"令和6年12月1日","iso":"2024-12-01"}]', "rule:v1", 0.8);
    art.run("a2", "tatsugo_koho_202412", "tatsugo_koho_202412_p2", SRC, "article", 4, 5, 28, 29, "二ページの記事", "本文その2", null, "rule:v1", 0.9);
    art.run("a3", "tatsugo_koho_201904", "tatsugo_koho_201904", SRC, "article", 2, 2, 2, 2, "合併号の記事", "本文その3", null, "rule:v1", 0.9);
    art.run("a4", "tatsugo_koho_202412", "tatsugo_koho_202412_p1", SRC, "unsegmented", 1, 1, 1, 1, null, null, null, "rule:v1", 0.1);
    raw.prepare("INSERT INTO document_article_topics (article_id, topic_id, extractor, confidence) VALUES ('a1','wildlife_alien','rule:v1',0.8),('a1','river_water','rule:v1',0.6),('a2','tourism','rule:v1',0.7)").run();
    raw.prepare("INSERT INTO document_article_places (article_id, place_raw, place_type, place_id, match_method, confidence) VALUES ('a1','秋名','settlement',NULL,NULL,0.9),('a1','龍郷湾','coast','p:bay','exact_name',1)").run();
  }

  it("record_set だけで出典が決まる（出典 1 つ）。別の出典を付けると入力エラー。号の一覧は files（PDF の URL）と n_articles を持つ", async () => {
    seedPeriodical();
    const r = await q({ record_set: "periodical_issues" });
    expect(r.source_id).toBe(SRC);
    expect(ids(r, "issue_id")).toEqual(["tatsugo_koho_201502s", "tatsugo_koho_201904", "tatsugo_koho_202412"]);
    expect(r.n_total).toBe(sourceAccess(SRC)?.recordSetRows.periodical_issues); // 事前計算（実データの件数。生成物から）
    const dec = r.rows.find((x) => x.issue_id === "tatsugo_koho_202412")!;
    expect(dec.n_articles).toBe(2); // kind='article' だけ（unsegmented を数えない）
    expect(dec.files).toEqual([
      { doc_id: "tatsugo_koho_202412_p1", part_no: 1, page_offset: 0, pdf_url: "https://example.test/koho_202412_1.pdf" },
      { doc_id: "tatsugo_koho_202412_p2", part_no: 2, page_offset: 24, pdf_url: "https://example.test/koho_202412_2.pdf" },
    ]);
    expect(dec.citation).toBe("龍郷町「広報たつごう」2024年12月号");
    expect(r.rows.find((x) => x.issue_id === "tatsugo_koho_201904")!.citation).toBe("龍郷町「広報たつごう」2019年4・5月合併号");
    expect(r.rows.find((x) => x.issue_id === "tatsugo_koho_201502s")!.citation).toBe("龍郷町「広報たつごう」2015年2月 別冊");
    await expect(q({ record_set: "periodical_issues", source_id: "dams_kanagawa" })).rejects.toThrow(RecordsInputError);
  });

  it("号の絞り込み: year（暦年）・fiscal_year・issue（issue_id か YYYY-MM）。n_total は絞ると null", async () => {
    seedPeriodical();
    expect(ids(await q({ record_set: "periodical_issues", year: 2019 }), "issue_id")).toEqual(["tatsugo_koho_201904"]);
    expect(ids(await q({ record_set: "periodical_issues", fiscal_year: 2014 }), "issue_id")).toEqual(["tatsugo_koho_201502s"]);
    expect(ids(await q({ record_set: "periodical_issues", year: 2015, fiscal_year: 2019 }), "issue_id")).toEqual([]); // AND
    expect(ids(await q({ record_set: "periodical_issues", issue: "2024-12" }), "issue_id")).toEqual(["tatsugo_koho_202412"]);
    expect(ids(await q({ record_set: "periodical_issues", issue: "tatsugo_koho_201904" }), "issue_id")).toEqual(["tatsugo_koho_201904"]);
    expect((await q({ record_set: "periodical_issues", year: 2019 })).n_total).toBeNull();
    await expect(q({ record_set: "periodical_issues", topic: "tourism" })).rejects.toThrow(RecordsInputError);
    await expect(q({ record_set: "periodical_issues", include_body: true })).rejects.toThrow(RecordsInputError);
  });

  it("記事の一覧は本文を返さず has_body・body_chars だけ。citation（号内通しページ）・pdf_url（ファイル内ページ）・source_license を必ず付け、内部列は出さない", async () => {
    seedPeriodical();
    const r = await q({ record_set: "document_articles", issue: "2024-12" });
    expect(ids(r, "article_id")).toEqual(["a1", "a2", "a4"]);
    for (const row of r.rows) {
      expect(row).not.toHaveProperty("body_text");
      expect(row).not.toHaveProperty("doc_url");
      expect(row.source_license).toBe(SERIES_LICENSE);
    }
    const [a1, a2, a4] = r.rows;
    expect(a1).toMatchObject({ has_body: 1, body_chars: [...BODY1].length, year_month: "2024-12", fiscal_year: 2024 });
    expect(a1.citation).toBe("龍郷町「広報たつごう」2024年12月号 p.27");
    expect(a1.pdf_url).toBe("https://example.test/koho_202412_2.pdf#page=3");
    expect(a2.citation).toBe("龍郷町「広報たつごう」2024年12月号 p.28–29");
    expect(a2.pdf_url).toBe("https://example.test/koho_202412_2.pdf#page=4");
    expect(a4).toMatchObject({ has_body: 0, body_chars: null });
    expect(a1.event_dates).toEqual([{ raw: "令和6年12月1日", iso: "2024-12-01" }]);
    expect(a1.topics).toEqual([
      { topic_id: "river_water", confidence: 0.6, extractor: "rule:v1" },
      { topic_id: "wildlife_alien", confidence: 0.8, extractor: "rule:v1" },
    ]);
    expect(a1.places).toEqual([
      { place_raw: "秋名", place_type: "settlement", place_id: null, match_method: null, confidence: 0.9, extractor: "rule:v1" },
      { place_raw: "龍郷湾", place_type: "coast", place_id: "p:bay", match_method: "exact_name", confidence: 1, extractor: "rule:v1" },
    ]);
    expect(a4.topics).toEqual([]);
    expect((await q({ record_set: "document_articles", issue: "tatsugo_koho_201904" })).rows[0].citation).toBe("龍郷町「広報たつごう」2019年4・5月合併号 p.2");
  });

  it("topic・place_id・year・fiscal_year で絞る（バインドは数個。EXISTS）", async () => {
    seedPeriodical();
    expect(ids(await q({ record_set: "document_articles", topic: "wildlife_alien" }), "article_id")).toEqual(["a1"]);
    expect(ids(await q({ record_set: "document_articles", topic: "tourism", fiscal_year: 2024 }), "article_id")).toEqual(["a2"]);
    expect(ids(await q({ record_set: "document_articles", topic: "tourism", fiscal_year: 2019 }), "article_id")).toEqual([]);
    expect(ids(await q({ record_set: "document_articles", place_id: "p:bay" }), "article_id")).toEqual(["a1"]);
    expect(ids(await q({ record_set: "document_articles", year: 2019 }), "article_id")).toEqual(["a3"]);
    expect(ids(await q({ record_set: "document_articles", doc_id: "tatsugo_koho_202412_p1" }), "article_id")).toEqual(["a4"]);
  });

  it("本文: include_body=true か id 指定の 1 件だけ全文を返す。q は見出しと本文に効き、一致箇所の前後を match_snippet に返す（本文は返さない）", async () => {
    seedPeriodical();
    const one = await q({ record_set: "document_articles", id: "a1" });
    expect(one.rows[0].body_text).toBe(BODY1);
    expect(one.rows[0].citation).toBeTruthy();
    const withBody = await q({ record_set: "document_articles", issue: "2024-12", include_body: true });
    expect(withBody.rows.map((x) => x.body_text)).toEqual([BODY1, "本文その2", null]);
    expect(withBody.limit).toBe(INCLUDE_BODY_MAX_ROWS); // limit 省略は 20 件
    const hit = await q({ record_set: "document_articles", q: "カダヤシ" });
    expect(ids(hit, "article_id")).toEqual(["a1"]);
    expect(hit.rows[0]).not.toHaveProperty("body_text");
    expect(hit.rows[0].match_snippet).toBe(BODY1); // 前後 40 字に全体が収まる
    expect(ids(await q({ record_set: "document_articles", q: "合併号の記事" }), "article_id")).toEqual(["a3"]); // 見出しにも効く
    expect((await q({ record_set: "document_articles", q: "合併号の記事" })).rows[0].match_snippet).toBeNull();
    await expect(q({ record_set: "document_articles", include_body: true, limit: INCLUDE_BODY_MAX_ROWS + 1 })).rejects.toThrow(RecordsInputError);
  });

  it("長い本文の抜粋は前後各 40 字だけ", async () => {
    seedPeriodical();
    raw.prepare("UPDATE document_articles SET body_text = ? WHERE article_id = 'a2'").run("あ".repeat(100) + "カダヤシ" + "い".repeat(100));
    const r = await q({ record_set: "document_articles", q: "カダヤシ" });
    expect(r.rows.find((x) => x.article_id === "a2")!.match_snippet).toBe("あ".repeat(40) + "カダヤシ" + "い".repeat(40));
  });

  it("year は年をまたぐ合併号を両方の年で拾う。topic の説明は registry の語彙から作る", async () => {
    seedPeriodical();
    raw.prepare("INSERT INTO periodical_issues (issue_id, series_id, source_id, kind, year_month, year_month_to, fiscal_year) VALUES ('x','tatsugo_koho',?,'monthly','2019-12','2020-01',2019)").run(SRC);
    raw.prepare("INSERT INTO document_articles (article_id, issue_id, doc_id, source_id, kind) VALUES ('ax','x','tatsugo_koho_201904',?,'article')").run(SRC);
    for (const y of [2019, 2020]) expect(ids(await q({ record_set: "periodical_issues", year: y }), "issue_id")).toContain("x");
    expect(ids(await q({ record_set: "document_articles", year: 2020 }), "article_id")).toEqual(["ax"]);
    const desc = recordsInputSchema.shape.topic.unwrap().description ?? "";
    for (const t of ARTICLE_TOPIC) expect(desc).toContain(t.topicId);
  });

  it("入力の検査: 新しい入力は他の record_set では入力エラー。zod は範囲外・型違いを拒む", async () => {
    await expect(q({ record_set: "document_cells", fiscal_year: 2024 })).rejects.toThrow(RecordsInputError);
    await expect(q({ source_id: "dams_kanagawa", topic: "tourism" })).rejects.toThrow(RecordsInputError);
    await expect(q({ source_id: "dams_kanagawa", include_body: true })).rejects.toThrow(RecordsInputError);
    expect(recordsInputSchema.safeParse({ record_set: "document_articles", fiscal_year: 2024, topic: "tourism", include_body: true }).success).toBe(true);
    expect(recordsInputSchema.safeParse({ record_set: "document_articles", year: "2024" }).success).toBe(false);
    expect(recordsInputSchema.strict().safeParse({ record_set: "document_articles", cursor: "x" }).success).toBe(false);
  });

  it("citation・pdf_url の関数: 月刊・合併号・別冊・年またぎ・ページ範囲・年月が読めない", () => {
    expect(issueLabel({ kind: "monthly", year_month: "2024-04" })).toBe("2024年4月号");
    expect(issueLabel({ kind: "monthly", year_month: "2019-12", year_month_to: "2020-01" })).toBe("2019年12月・2020年1月合併号");
    expect(issueLabel({ kind: "supplement", year_month: "2015-02" })).toBe("2015年2月 別冊");
    expect(issueLabel({ kind: "monthly", year_month: null })).toBeNull();
    expect(periodicalCitation({ publisher: "龍郷町", title: "広報たつごう", kind: "monthly", year_month: "2024-04", page_from: 3, page_to: 3 })).toBe("龍郷町「広報たつごう」2024年4月号 p.3");
    expect(periodicalCitation({ kind: "monthly", year_month: "2024-04", page_from: 3 })).toBeNull(); // 系列の行が無いときは推測で埋めない
    expect(periodicalCitation({ publisher: "X町", title: "広報X", kind: "monthly", year_month: "2024-04", page_from: 3, page_to: 5 })).toBe("X町「広報X」2024年4月号 p.3–5");
    expect(periodicalCitation({ publisher: "X町", title: "広報X", kind: "monthly", year_month: "bad" })).toBeNull();
    expect(pdfPageUrl("https://a/b.pdf", 7)).toBe("https://a/b.pdf#page=7");
    expect(pdfPageUrl(null, 7)).toBeNull();
  });
});
