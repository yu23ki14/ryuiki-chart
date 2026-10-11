import fs from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type { CubeDb } from "./db";
import { sqliteCubeDb } from "./db-sqlite";
import { speciesCatalog } from "./catalog";

const REPO = path.resolve(__dirname, "../../../..");
const P = {
  v2: path.join(REPO, "data/db/v2.sqlite"),
  registry: path.join(REPO, "data/db/registry.sqlite"),
  ryuiki: path.join(REPO, "data/db/ryuiki.sqlite"),
};
const haveReal = Object.values(P).every((p) => fs.existsSync(p));

describe.skipIf(!haveReal)("実データ（読み取り専用）: 流域・期間・赤リストで絞った種の一覧", () => {
  let db: CubeDb & { close(): void };
  beforeAll(() => {
    db = sqliteCubeDb(P);
  });
  afterAll(() => db.close());

  it("奄美の iNaturalist・dem-amami-039・2022年以降: n=1154・赤リスト 139 件・74 種。アマミノクロウサギは CR+EN・kgrl2014", async () => {
    const rows = await speciesCatalog(db, {
      sourceIds: ["inaturalist_amami"],
      placeId: "common:place:watershed.dem.amami-039",
      yearFrom: 2022,
      limit: 5000,
      withNames: true,
    });
    const sum = (f: (r: (typeof rows)[number]) => number) => rows.reduce((a, r) => a + f(r), 0);
    expect(sum((r) => r.n)).toBe(1154);
    expect(sum((r) => r.nRedList)).toBe(139);
    expect(rows.filter((r) => r.nRedList > 0)).toHaveLength(74);
    const rabbit = rows.find((r) => r.binom === "Pentalagus furnessi");
    expect(rabbit?.nRedList).toBe(10);
    expect(rabbit?.redListCategory).toBe("絶滅危惧Ⅰ類（CR+EN）");
    expect(rabbit?.redListSource).toBe("kgrl2014");
    expect(rabbit?.label).toBe("アマミノクロウサギ");
    // 赤リスト該当の種には必ずカテゴリがある（出所が引けない種を黙って落とさない）
    expect(rows.filter((r) => r.nRedList > 0 && !r.redListCategory)).toEqual([]);
  });

  it("redListOnly は赤リスト該当の種だけ。県版が無い種の出所は national", async () => {
    const rows = await speciesCatalog(db, {
      sourceIds: ["inaturalist_amami"],
      placeId: "common:place:watershed.dem.amami-039",
      yearFrom: 2022,
      redListOnly: true,
      limit: 5000,
    });
    expect(rows).toHaveLength(74);
    expect(rows.every((r) => r.nRedList > 0)).toBe(true);
    expect(new Set(rows.map((r) => r.redListSource))).toEqual(new Set(["kgrl2014", "national"]));
  });

  it("期間だけの指定（流域なし）でも動く。year_to で打ち切れる", async () => {
    const all = await speciesCatalog(db, { sourceIds: ["inaturalist_amami"], yearFrom: 2022, limit: 5000 });
    const upto = await speciesCatalog(db, { sourceIds: ["inaturalist_amami"], yearFrom: 2022, yearTo: 2022, limit: 5000 });
    expect(upto.reduce((a, r) => a + r.n, 0)).toBeLessThan(all.reduce((a, r) => a + r.n, 0));
    expect(upto.every((r) => r.yFrom === 2022 && r.yTo === 2022)).toBe(true);
  });
});
