import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { sqliteCubeDb } from "./db-sqlite";

/**
 * `sqliteCubeDb()` は3つの独立した sqlite ファイル（v2/registry/ryuiki）を ATTACH して、
 * 非修飾テーブル名（`observation_agg`→main、`variable`→reg、`sites`→r）で引けることを
 * 確かめる（フィクスチャ〔`cube-fixture.ts`〕は全テーブルが同じ in-memory DB に同居して
 * いるため ATTACH 自体は経由しない。ここだけが ATTACH の配線を検証する）。
 */
describe("sqliteCubeDb", () => {
  let dir: string;
  let paths: { v2: string; registry: string; ryuiki: string };

  beforeEach(() => {
    dir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "cube-db-sqlite-test-"));
    paths = { v2: path.join(dir, "v2.sqlite"), registry: path.join(dir, "registry.sqlite"), ryuiki: path.join(dir, "ryuiki.sqlite") };

    const v2 = new Database(paths.v2);
    v2.exec("CREATE TABLE observation_agg (place_id TEXT, variable_id TEXT, value_zero REAL)");
    v2.exec("INSERT INTO observation_agg VALUES ('p1','v1',1.5)");
    v2.close();

    const reg = new Database(paths.registry);
    reg.exec("CREATE TABLE variable (variable_id TEXT PRIMARY KEY, name_ja TEXT)");
    reg.exec("INSERT INTO variable VALUES ('v1','テスト指標')");
    reg.close();

    const ryuiki = new Database(paths.ryuiki);
    ryuiki.exec("CREATE TABLE sites (site_id TEXT PRIMARY KEY, name TEXT)");
    // observation_agg.place_id と同じキー（'p1'）で JOIN できるようにしてある
    // （実際の place_id ↔ site_id の対応は place_source_ref 経由だが、ここは
    // ATTACH の配線だけを確かめる最小のフィクスチャなので簡略化している）。
    ryuiki.exec("INSERT INTO sites VALUES ('p1','テスト地点')");
    ryuiki.close();
  });

  afterEach(() => {
    fs.rmSync(dir, { recursive: true, force: true });
  });

  it("main（v2）・reg（registry）・r（ryuiki）を非修飾テーブル名で JOIN できる", async () => {
    const db = sqliteCubeDb(paths);
    try {
      const rows = await db.all<{ place_id: string; name_ja: string; name: string }>(`
        SELECT o.place_id, v.name_ja, s.name
        FROM observation_agg o
        JOIN variable v ON v.variable_id = o.variable_id
        JOIN sites s ON s.site_id = o.place_id
      `);
      expect(rows).toEqual([{ place_id: "p1", name_ja: "テスト指標", name: "テスト地点" }]);
    } finally {
      db.close();
    }
  });

  it("kind は 'sqlite'", () => {
    const db = sqliteCubeDb(paths);
    expect(db.kind).toBe("sqlite");
    db.close();
  });

  it("読み取り専用で開く（書き込みを試みると例外）", async () => {
    const db = sqliteCubeDb(paths);
    try {
      await expect(db.all("INSERT INTO observation_agg VALUES ('p2','v1',2.0)")).rejects.toThrow();
    } finally {
      db.close();
    }
  });

  it("assertD1Compatible を経由する（101 パラメータで例外）", async () => {
    const db = sqliteCubeDb(paths);
    try {
      const params = Array.from({ length: 101 }, (_, i) => i);
      await expect(db.all("SELECT 1", params)).rejects.toThrow(/バインドパラメータ/);
    } finally {
      db.close();
    }
  });

  it("excludePlaceIds: 指定した place_id を observation_agg から除いた TEMP VIEW で覆う（--pretend-synthetic-excluded 用）", async () => {
    const db = sqliteCubeDb(paths, { excludePlaceIds: ["p1"] });
    try {
      const rows = await db.all<{ place_id: string }>("SELECT place_id FROM observation_agg");
      expect(rows).toEqual([]);
      // 読み取り専用のまま（TEMP VIEW を張っても query_only は効いている）。
      await expect(db.all("INSERT INTO observation_agg VALUES ('p2','v1',2.0)")).rejects.toThrow();
    } finally {
      db.close();
    }
  });

  it("excludePlaceIds を渡さなければ全件そのまま", async () => {
    const db = sqliteCubeDb(paths, {});
    try {
      const rows = await db.all<{ place_id: string }>("SELECT place_id FROM observation_agg");
      expect(rows).toEqual([{ place_id: "p1" }]);
    } finally {
      db.close();
    }
  });
});
