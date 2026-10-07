import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { SOURCE_ACCESS } from "@/lib/registry/generated-source";
import {
  FIND_DATASET_SOURCE_IDS,
  FIND_DATASETS_DESCRIPTION,
  findDatasetsInputSchema,
  FindDatasetsInputError,
  queryDatasets,
  type FindDatasetsInput,
} from "./catalog-search";

const BASE: Record<string, string> = {
  ckan_kanagawa_pref: "https://catalog.opendata.pref.kanagawa.jp",
  ckan_sagamihara: "https://opendata.city.sagamihara.kanagawa.jp",
  ckan_bodik_kanagawa: "https://data.bodik.jp",
  ckan_yokohama: "https://data.city.yokohama.lg.jp",
};

let raw: Database.Database;
const db = () => wrapSqlite(raw);
const q = (a: Record<string, unknown>) => queryDatasets(db(), findDatasetsInputSchema.parse(a));

function addDataset(o: {
  source: string;
  id: string;
  title?: string;
  desc?: string | null;
  org?: string | null;
  license?: string | null;
  tags?: string | null;
  groups?: string | null;
  modified?: string | null;
  portal?: string;
  resources?: { format: string | null; sheets?: object[] | null; name?: string }[];
}) {
  const portal = o.portal ?? (o.source.startsWith("estat") ? "estat" : "ckan");
  const key = `${o.source}:${o.id}`;
  const base = BASE[o.source];
  raw
    .prepare(
      `INSERT INTO external_dataset (dataset_key, source_id, portal, dataset_id, name, title, description, description_truncated, organization, license,
        license_url, groups, tags, n_resources, metadata_modified, page_url, api_url, fetched_at) VALUES (?,?,?,?,?,?,?,0,?,?,NULL,?,?,?,?,?,?,?)`,
    )
    .run(
      key, o.source, portal, o.id, portal === "ckan" ? `n_${o.id}` : null, o.title ?? `題名 ${o.id}`, o.desc ?? null, o.org ?? null, o.license ?? null,
      o.groups ?? null, o.tags ?? null, o.resources?.length ?? 0, o.modified ?? null,
      base ? `${base}/dataset/n_${o.id}` : `https://www.e-stat.go.jp/stat-search/files?stat_infid=${o.id}`,
      base ? `${base}/api/3/action/package_show?id=${o.id}` : null, "2026-08-29T00:00:00",
    );
  (o.resources ?? []).forEach((r, i) => {
    raw
      .prepare("INSERT INTO external_resource (resource_key, dataset_key, name, format, size, last_modified, direct_url, page_url, sheets_json) VALUES (?,?,?,?,?,?,?,?,?)")
      .run(`${o.source}:${o.id}_r${i}`, key, r.name ?? `資源${i}`, r.format, 100, null, `https://example.test/${o.id}/${i}`, null, r.sheets ? JSON.stringify(r.sheets) : null);
  });
}

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
  for (const s of FIND_DATASET_SOURCE_IDS) addDataset({ source: s, id: `${s}-1`, modified: "2026-01-01T00:00:00", resources: [{ format: "CSV" }] });
});
afterEach(() => raw.close());

describe("find_datasets: 全出典で動く", () => {
  it("FIND_DATASET_SOURCE_IDS の全件で 1 行以上返り、api_package_show（CKAN）か page（e-Stat）が非空", async () => {
    expect(FIND_DATASET_SOURCE_IDS.length).toBe(7);
    for (const s of FIND_DATASET_SOURCE_IDS) {
      const r = await q({ source_id: s });
      expect(r.rows.length, s).toBeGreaterThanOrEqual(1);
      const u = r.rows[0].urls;
      expect(u.page, s).toBeTruthy();
      if (s.startsWith("ckan_")) expect(u.api_package_show, s).toBe(`${BASE[s]}/api/3/action/package_show?id=${s}-1`);
      else expect(u.api_package_show, s).toBeNull();
      expect(r.source_ids).toEqual([s]);
    }
  });

  it("生成物の宣言（queryable_via に find_datasets）と FIND_DATASET_SOURCE_IDS が一致する", () => {
    const declared = Object.entries(SOURCE_ACCESS).filter(([, a]) => a.queryableVia.includes("find_datasets")).map(([id]) => id).sort();
    expect([...FIND_DATASET_SOURCE_IDS].sort()).toEqual(declared);
    for (const id of declared) expect(SOURCE_ACCESS[id].nSourceRowsBasis).toBe("catalog_datasets");
  });

  it("ツールの説明に、出典・fetched_at・api_package_show・license: null が書いてある", () => {
    for (const s of FIND_DATASET_SOURCE_IDS) expect(FIND_DATASETS_DESCRIPTION).toContain(s);
    expect(FIND_DATASETS_DESCRIPTION).toContain("fetched_at");
    expect(FIND_DATASETS_DESCRIPTION).toContain("api_package_show");
    expect(FIND_DATASETS_DESCRIPTION).toContain("license: null");
  });
});

describe("find_datasets: 絞り込み", () => {
  beforeEach(() => {
    addDataset({ source: "ckan_bodik_kanagawa", id: "w1", title: "河川水質調査結果", desc: "相模川の水質", org: "厚木市", license: "CC BY", tags: "水質|河川", groups: "環境", modified: "2026-09-24T00:00:00", resources: [{ format: "XLSX" }, { format: "PDF" }] });
    addDataset({ source: "ckan_bodik_kanagawa", id: "w2", title: "広報あつぎ", org: "厚木市", license: null, tags: "広報", modified: "2025-04-01T00:00:00", resources: [{ format: "SHP,CSV" }, { format: "HTML" }] });
    addDataset({ source: "ckan_yokohama", id: "y1", title: "河川水位", desc: "水質ではない", org: "横浜市", tags: "河川", modified: "2026-03-01T00:00:00", resources: [{ format: "XHTML" }] });
  });

  it("q: 題名・説明・タグ・分野の部分一致。空白区切りは AND。3 語を超えるとエラー", async () => {
    expect((await q({ q: "水質" })).rows.map((r) => r.dataset_key).sort()).toEqual(["ckan_bodik_kanagawa:w1", "ckan_yokohama:y1"]);
    expect((await q({ q: "河川 水質" })).rows.map((r) => r.dataset_key).sort()).toEqual(["ckan_bodik_kanagawa:w1", "ckan_yokohama:y1"]);
    expect((await q({ q: "河川 水質 ではない" })).rows.map((r) => r.dataset_key)).toEqual(["ckan_yokohama:y1"]);
    expect((await q({ q: "環境" })).rows.map((r) => r.dataset_key)).toEqual(["ckan_bodik_kanagawa:w1"]); // groups
    await expect(q({ q: "あ い う え" })).rejects.toThrow(FindDatasetsInputError);
  });

  it("q の % と _ はそのまま文字として照合する（ワイルドカードにしない）", async () => {
    expect((await q({ q: "%" })).rows).toEqual([]);
    addDataset({ source: "ckan_sagamihara", id: "u1", title: "zq_x", resources: [] });
    addDataset({ source: "ckan_sagamihara", id: "u2", title: "zqAx", resources: [] });
    expect((await q({ q: "zq_x" })).rows.map((r) => r.title)).toEqual(["zq_x"]);
  });

  it("organization: 部分一致", async () => {
    expect((await q({ organization: "厚木" })).rows.map((r) => r.dataset_key).sort()).toEqual(["ckan_bodik_kanagawa:w1", "ckan_bodik_kanagawa:w2"]);
  });

  it("format: カンマ区切りの要素で照合する（SHP,CSV は CSV に当たり、XHTML は HTML に当たらない）", async () => {
    const csv = (await q({ format: "CSV" })).rows.map((r) => r.dataset_key);
    expect(csv).toContain("ckan_bodik_kanagawa:w2");
    expect(csv).not.toContain("ckan_bodik_kanagawa:w1");
    const html = (await q({ format: "HTML" })).rows.map((r) => r.dataset_key);
    expect(html).toEqual(["ckan_bodik_kanagawa:w2"]);
    expect((await q({ format: "SHP" })).rows.map((r) => r.dataset_key)).toEqual(["ckan_bodik_kanagawa:w2"]);
  });

  it("modified_since: metadata_modified が以降（収穫時点の値）。e-Stat（日付なし）は含まれない", async () => {
    const r = await q({ modified_since: "2026-03-01" });
    expect(r.rows.map((x) => x.dataset_key).sort()).toEqual(["ckan_bodik_kanagawa:w1", "ckan_yokohama:y1"]);
    await expect(q({ modified_since: "2026-13-45" })).rejects.toThrow(FindDatasetsInputError);
  });

  it("id: 完全一致で 1 件。資源を全件返す", async () => {
    const r = await q({ id: "ckan_bodik_kanagawa:w1" });
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0].urls.resources).toHaveLength(2);
    expect(r.rows[0].urls.resources?.[0].direct_url).toBe("https://example.test/w1/0");
  });

  it("source_id と組み合わせると AND", async () => {
    expect((await q({ source_id: "ckan_yokohama", q: "河川" })).rows.map((r) => r.dataset_key)).toEqual(["ckan_yokohama:y1"]);
    expect((await q({ source_id: "ckan_sagamihara", q: "河川" })).rows).toEqual([]);
  });
});

describe("find_datasets: 入力検査", () => {
  it("条件なしは入力エラー（全件取りの拒否）。limit/offset だけでも同じ", async () => {
    await expect(queryDatasets(db(), findDatasetsInputSchema.parse({}))).rejects.toThrow(FindDatasetsInputError);
    await expect(queryDatasets(db(), findDatasetsInputSchema.parse({ limit: 5, offset: 1 }))).rejects.toThrow(/どれか 1 つ以上/);
  });

  it("MCP の strict は未知のキーを拒否する。長すぎる q も拒否する", () => {
    expect(() => findDatasetsInputSchema.strict().parse({ q: "x", sql: "select 1" })).toThrow();
    expect(() => findDatasetsInputSchema.parse({ q: "あ".repeat(17) })).toThrow(/長すぎる/);
    expect(() => findDatasetsInputSchema.parse({ q: "あ".repeat(16) })).not.toThrow();
  });

  it("include_resources と limit>10 の併用はエラー。limit<=10 なら資源を返す", async () => {
    await expect(q({ source_id: "ckan_yokohama", include_resources: true, limit: 11 })).rejects.toThrow(FindDatasetsInputError);
    await expect(q({ source_id: "ckan_yokohama", include_resources: true })).rejects.toThrow(FindDatasetsInputError); // 既定 limit は 20
    const r = await q({ source_id: "ckan_yokohama", include_resources: true, limit: 10 });
    expect(r.rows[0].urls.resources).toBeDefined();
    const bare = await q({ source_id: "ckan_yokohama", limit: 10 });
    expect(bare.rows[0].urls.resources).toBeUndefined();
  });

  it("未知の source_id・形式はスキーマで拒否", () => {
    expect(() => findDatasetsInputSchema.parse({ source_id: "kanagawa_edna" })).toThrow();
    expect(() => findDatasetsInputSchema.parse({ format: "DOCX" })).toThrow();
  });
});

describe("find_datasets: ページング", () => {
  it("limit/offset で重複・欠落がなく、並びは metadata_modified 降順・dataset_key 昇順", async () => {
    for (let i = 0; i < 25; i++) {
      addDataset({ source: "ckan_sagamihara", id: `p${String(i).padStart(2, "0")}`, modified: i % 5 === 0 ? null : `2026-0${1 + (i % 5)}-01T00:00:00`, resources: [] });
    }
    const all: string[] = [];
    for (let offset = 0; ; offset += 7) {
      const r = await q({ source_id: "ckan_sagamihara", limit: 7, offset });
      all.push(...r.rows.map((x) => x.dataset_key));
      expect(r.n_total).toBe(26);
      if (!r.truncated) break;
    }
    expect(all).toHaveLength(26);
    expect(new Set(all).size).toBe(26);
    const ref = raw
      .prepare("SELECT dataset_key FROM external_dataset WHERE source_id='ckan_sagamihara' ORDER BY metadata_modified DESC, dataset_key ASC")
      .all()
      .map((r) => (r as { dataset_key: string }).dataset_key);
    expect(all).toEqual(ref);
  });

  it("n_total は q なしのときだけ", async () => {
    expect((await q({ source_id: "ckan_yokohama" })).n_total).toBe(1);
    expect((await q({ q: "題名" })).n_total).toBeNull();
  });
});

describe("find_datasets: 応答の中身（根拠のあるものだけ）", () => {
  it("license が空の行は null（除外しない）。tags・groups は配列", async () => {
    addDataset({ source: "ckan_kanagawa_pref", id: "nl", title: "ライセンス不明", license: null, tags: "a|b", groups: "g1|g2", resources: [] });
    const r = await q({ id: "ckan_kanagawa_pref:nl" });
    expect(r.rows[0].license).toBeNull();
    expect(r.rows[0].tags).toEqual(["a", "b"]);
    expect(r.rows[0].groups).toEqual(["g1", "g2"]);
    expect((await q({ q: "ライセンス不明" })).rows).toHaveLength(1);
  });

  it("columns: 見出しを検出できた資源があれば available（根拠つき）、無ければ not_extracted。header: null のシートは返さない列を推測しない", async () => {
    addDataset({
      source: "ckan_kanagawa_pref", id: "h1", title: "見出しあり",
      resources: [
        { format: "XLSX", sheets: [{ sheet: "S1", n_rows: 10, n_cols: 2, header: ["地点", "値"], header_basis: "converted_csv_first_row" }, { sheet: "S2", n_rows: 3, n_cols: 3, header: null }] },
        { format: "CSV" },
      ],
    });
    addDataset({ source: "ckan_kanagawa_pref", id: "h2", title: "見出しなし", resources: [{ format: "XLSX", sheets: [{ sheet: null, n_rows: 5, n_cols: 4, header: null }] }] });

    const list = (await q({ q: "見出し" })).rows;
    const byKey = Object.fromEntries(list.map((r) => [r.dataset_key, r]));
    expect(byKey["ckan_kanagawa_pref:h1"].data_definition.columns.status).toBe("available"); // 一覧（資源なし）でも同じ
    expect(byKey["ckan_kanagawa_pref:h1"].data_definition.sheets).toBeUndefined();
    expect(byKey["ckan_kanagawa_pref:h2"].data_definition.columns).toMatchObject({ status: "not_extracted", basis: null });

    const detail = (await q({ id: "ckan_kanagawa_pref:h1" })).rows[0];
    const sheets = detail.data_definition.sheets!;
    expect(sheets.map((s) => [s.sheet, s.header])).toEqual([["S1", ["地点", "値"]], ["S2", null]]);
    expect(sheets[0].header_basis).toBe("converted_csv_first_row");
    expect(sheets[0].resource_key).toBe("ckan_kanagawa_pref:h1_r0");
  });

  it("formats: 資源の形式別の件数（SHP,CSV は両方に数える。形式なしは unspecified）", async () => {
    addDataset({ source: "ckan_sagamihara", id: "f1", title: "形式", resources: [{ format: "SHP,CSV" }, { format: "CSV" }, { format: null }] });
    expect((await q({ q: "形式" })).rows[0].formats).toEqual({ SHP: 1, CSV: 2, unspecified: 1 });
    expect((await q({ id: "ckan_sagamihara:f1" })).rows[0].formats).toEqual({ SHP: 1, CSV: 2, unspecified: 1 });
  });

  it("access: CKAN は auth none、e-Stat は appId_for_api_only で最新の確認方法を返す", async () => {
    const ckan = (await q({ source_id: "ckan_yokohama" })).rows[0];
    expect(ckan.access.auth).toBe("none");
    expect(ckan.access.how_to_get_latest).toContain("api_package_show");
    expect(ckan.fetched_at).toBe("2026-08-29T00:00:00");
    const e = (await q({ source_id: "estat_agri_census_kanagawa" })).rows[0];
    expect(e.access.auth).toBe("appId_for_api_only");
    expect(e.urls.api_package_show).toBeNull();
    expect(e.access.search_url).toMatch(/^https:\/\/www\.e-stat\.go\.jp\//);
  });

  it("一覧（資源なし）の応答は 100 件で 200KB 以内", async () => {
    const long = "説明".repeat(300);
    for (let i = 0; i < 100; i++) {
      addDataset({ source: "ckan_yokohama", id: `big${i}`, title: `大きい${i}`, desc: long, org: "横浜市", tags: "a|b|c|d", groups: "g", modified: "2026-05-01T00:00:00", resources: Array.from({ length: 5 }, () => ({ format: "CSV" })) });
    }
    const r = await q({ source_id: "ckan_yokohama", limit: 100 });
    expect(r.rows).toHaveLength(100);
    expect(JSON.stringify(r).length).toBeLessThan(200 * 1024);
  });
});

describe("型", () => {
  it("FindDatasetsInput は z.tuple を含まない", () => {
    const x: FindDatasetsInput = { q: "a" };
    expect(JSON.stringify(findDatasetsInputSchema.shape)).not.toContain("prefixItems");
    expect(x.q).toBe("a");
  });
});
