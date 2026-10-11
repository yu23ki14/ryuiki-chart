import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { speciesCatalog } from "./catalog";
import type { CubeDb } from "./db";
import { sqliteCubeDb } from "./db-sqlite";

/**
 * 流域・期間・赤リストで絞った種の一覧（実データ。読み取り専用）。キューブ（v2.sqlite）と registry だけを読む——
 * v1 の表（ryuiki.sqlite の taxa など）は D1 に無いので、ryuiki の位置にも registry を渡して、それらに触れたら落ちるようにしてある。
 * v2.sqlite に `summary_taxon_red_list`（b13）が無い（古い）ときは飛ばす。`RYUIKI_V2_DB` で別の v2 を指せる。
 */
const REPO = path.resolve(__dirname, "../../../..");
const V2 = process.env.RYUIKI_V2_DB ?? path.join(REPO, "data/db/v2.sqlite");
const REGISTRY = path.join(REPO, "data/db/registry.sqlite");

function haveRedListTable(): boolean {
  if (![V2, REGISTRY].every((p) => fs.existsSync(p))) return false;
  const c = new Database(V2, { readonly: true });
  try {
    return c.prepare("SELECT 1 FROM sqlite_master WHERE name = 'summary_taxon_red_list'").get() !== undefined;
  } finally {
    c.close();
  }
}

const AMAMI_039 = "common:place:watershed.dem.amami-039";

describe.skipIf(!haveRedListTable())("実データ: speciesCatalog の流域・期間・赤リスト", () => {
  let db: CubeDb & { close(): void };
  beforeAll(() => {
    db = sqliteCubeDb({ v2: V2, registry: REGISTRY, ryuiki: REGISTRY });
  });
  afterAll(() => db.close());

  const scoped = { sourceIds: ["inaturalist_amami"], placeId: AMAMI_039, yearFrom: 2022, limit: 5000, withNames: true } as const;

  it("奄美の iNaturalist・dem-amami-039・2022年以降: n=1154・赤リスト 139 件・74 種。流域指定の行は n_located/n_places を持たない", async () => {
    const rows = await speciesCatalog(db, scoped);
    expect(rows.reduce((a, r) => a + r.n, 0)).toBe(1154);
    expect(rows.reduce((a, r) => a + r.nRedList, 0)).toBe(139);
    expect(rows.filter((r) => r.nRedList > 0)).toHaveLength(74);
    expect(rows[0]).not.toHaveProperty("nLocated");
    expect(rows[0]).not.toHaveProperty("nPlaces");
    // 件数のある種には必ずラベルがあり、無い種は空配列（件数とラベルの元が同じ判定結果）
    expect(rows.filter((r) => r.nRedList > 0 && r.redList!.length === 0)).toEqual([]);
    expect(rows.filter((r) => r.nRedList === 0 && r.redList!.length > 0)).toEqual([]);
  });

  it("アマミノクロウサギ: n_red_list=10。red_list に {jp-46, 絶滅危惧Ⅰ類（CR+EN）, kgrl2014} を含む", async () => {
    const rows = await speciesCatalog(db, scoped);
    const rabbit = rows.find((r) => r.binom === "Pentalagus furnessi")!;
    expect(rabbit.nRedList).toBe(10);
    expect(rabbit.label).toBe("アマミノクロウサギ");
    expect(rabbit.redList).toContainEqual(expect.objectContaining({ regionId: "jp-46", category: "絶滅危惧Ⅰ類（CR+EN）", source: "kgrl2014" }));
  });

  it("redListOnly は赤リストの記録がある種だけ（74 種）。ラベルの出所は県版と national", async () => {
    const rows = await speciesCatalog(db, { ...scoped, redListOnly: true });
    expect(rows).toHaveLength(74);
    const sources = new Set(rows.flatMap((r) => r.redList!.map((l) => l.source)));
    expect(sources.has("kgrl2014")).toBe(true);
    expect(sources.has("national")).toBe(true);
  });

  it("region 指定はその地域のラベルだけ。地域なしでは地域ごとのラベルが別々に並ぶ（1つに混ぜない）", async () => {
    const all = await speciesCatalog(db, { yearFrom: 2022, redListOnly: true, limit: 5000 });
    const amami = await speciesCatalog(db, { yearFrom: 2022, redListOnly: true, region: "jp-46", limit: 5000 });
    expect(amami.flatMap((r) => r.redList!).every((l) => l.regionId === "jp-46")).toBe(true);
    expect(new Set(all.flatMap((r) => r.redList!.map((l) => l.regionId)))).toEqual(new Set(["jp-14", "jp-46"]));
  }, 60_000); // 全地域の赤リスト種を集計するので重い（全体を回すと既定の 5 秒を超えうる）

  it("year_to で打ち切れる（流域なしの期間だけの指定）", async () => {
    const upto = await speciesCatalog(db, { sourceIds: ["inaturalist_amami"], yearFrom: 2022, yearTo: 2022, limit: 5000 });
    expect(upto.every((r) => r.yFrom === 2022 && r.yTo === 2022)).toBe(true);
  });
});
