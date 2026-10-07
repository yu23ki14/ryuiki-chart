import Database from "better-sqlite3";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";

vi.mock("server-only", () => ({}));

let raw: Database.Database;
vi.mock("@/lib/cube", async (orig) => ({
  ...(await orig<typeof import("@/lib/cube")>()),
  d1CubeDb: async () => wrapSqlite(raw),
}));

import { aiTools } from "./tools";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const run = (input: unknown) => (aiTools.find_datasets.execute as any)(input, { toolCallId: "t", messages: [] }) as Promise<any>;

beforeEach(() => {
  raw = new Database(":memory:");
  applyMigrations(raw);
});
afterEach(() => raw.close());

function add(id: string, desc: string, modified: string) {
  raw
    .prepare(
      `INSERT INTO external_dataset (dataset_key, source_id, portal, dataset_id, name, title, description, description_truncated, n_resources, metadata_modified, page_url, api_url, fetched_at)
       VALUES (?,?,?,?,?,?,?,0,0,?,?,?,?)`,
    )
    .run(`ckan_yokohama:${id}`, "ckan_yokohama", "ckan", id, `n_${id}`, `河川 ${id}`, desc, modified, `https://x.test/dataset/n_${id}`, `https://x.test/api/3/action/package_show?id=${id}`, "2026-08-30T16:21:00");
}

describe("find_datasets（AI）", () => {
  it("予算を超えるときは行数を減らし、offset で続きが取れる（欠落・重複なし）", async () => {
    const big = "あ".repeat(800);
    for (let i = 0; i < 40; i++) add(`d${String(i).padStart(2, "0")}`, big, `2026-01-${String(1 + (i % 28)).padStart(2, "0")}T00:00:00`);
    const seen: string[] = [];
    let offset = 0;
    for (let guard = 0; guard < 100; guard++) {
      const r = await run({ source_id: "ckan_yokohama", limit: 30, offset });
      expect(JSON.stringify(r.data).length).toBeLessThan(24 * 1024);
      seen.push(...r.data.rows.map((x: { dataset_key: string }) => x.dataset_key));
      if (!r.truncated) break;
      offset = seen.length;
      expect(r.data.offset).toBe(seen.length - r.data.rows.length);
    }
    expect(seen).toHaveLength(40);
    expect(new Set(seen).size).toBe(40);
  });

  it("入力エラーは例外にせず data.error で返す", async () => {
    const r = await run({});
    expect(r.data.error).toBeTruthy();
    expect(r.provenance.rowCount).toBe(0);
  });

  it("既定の件数は 10", async () => {
    for (let i = 0; i < 15; i++) add(`e${i}`, "x", "2026-02-01T00:00:00");
    const r = await run({ source_id: "ckan_yokohama" });
    expect(r.data.rows).toHaveLength(10);
    expect(r.truncated).toBe(true);
    expect(r.provenance.tables).toEqual(["external_dataset", "external_resource", "external_resource_format"]);
  });

  it("資源つきで予算を超えるときも、データセットの行を先頭から残す。資源のリストを間引かない（50 件のまま・続きは offset）", async () => {
    for (let i = 0; i < 6; i++) {
      add(`m${i}`, "x", `2026-03-0${1 + i}T00:00:00`);
      for (let j = 0; j < 60; j++) {
        raw
          .prepare("INSERT INTO external_resource (resource_key, dataset_key, name, format, direct_url) VALUES (?,?,?,?,?)")
          .run(`ckan_yokohama:m${i}_r${String(j).padStart(2, "0")}`, `ckan_yokohama:m${i}`, `資源 ${"あ".repeat(40)} ${j}`, "CSV", `https://x.test/${i}/${j}.csv?token=${"z".repeat(60)}`);
      }
    }
    const seen: string[] = [];
    let offset = 0;
    for (let guard = 0; guard < 20; guard++) {
      const r = await run({ source_id: "ckan_yokohama", include_resources: true, limit: 10, offset });
      expect(JSON.stringify(r.data).length).toBeLessThan(24 * 1024);
      for (const d of r.data.rows) {
        expect(d.urls.resources).toHaveLength(50); // 入れ子の配列は間引かない
        expect(d.resources_truncated).toBe(true);
      }
      seen.push(...r.data.rows.map((x: { dataset_key: string }) => x.dataset_key));
      if (!r.truncated) break;
      expect(r.data.next_offset).toBe(seen.length);
      expect(r.truncatedNote).toContain(`offset を ${seen.length}`);
      offset = seen.length;
    }
    expect(seen).toHaveLength(6);
    expect(new Set(seen).size).toBe(6);
  });
});
