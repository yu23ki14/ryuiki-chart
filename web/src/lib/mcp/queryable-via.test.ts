import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import { GENERATED_VARIABLE_ALIASES } from "@/lib/registry/generated";
import { RECORD_SET_TABLES, SOURCE_ACCESS, SOURCE_META } from "@/lib/registry/generated-source";
import { MCP_TOOLS, type McpContext } from "./tools";

/**
 * 受け入れ: describe_catalog が `queryable_via` に書いた（出典, ツール）の全組で、そのツールが実際に 1 行以上返す
 * （MCP_SOURCE_ACCESS.md §5.3。宣言と実際の食い違いを止める）。
 *  - get_records: インメモリ SQLite（drizzle のマイグレーションの DDL）に出典ごとに 1 行入れて全件。
 *  - get_observations / get_occurrences / get_edna: 原本・v2・registry が手元にあるときだけ、読み取り専用で開いた
 *    同じ問い合わせ層（better-sqlite3）で全件。無い環境（CI）では skip（`test_registry_source.py` と同じ流儀）。
 */
const NOW = new Date("2026-10-07T00:00:00Z");
const pairs = SOURCE_META.flatMap((m) => SOURCE_ACCESS[m.sourceId].queryableVia.map((tool) => [m.sourceId, tool] as const));

async function call(name: string, args: Record<string, unknown>, ctx: McpContext) {
  const tool = MCP_TOOLS.find((t) => t.name === name)!;
  const parsed = (tool.inputSchema as { parse: (a: unknown) => unknown }).parse(args);
  return (await tool.execute(parsed as never, ctx)) as { data: Record<string, unknown>; rows?: unknown[] };
}

describe("queryable_via の（出典, ツール）が実際に動く: get_records（インメモリ）", () => {
  const INSERT: Record<string, string> = {
    sites: "INSERT INTO sites (site_id, name, source_id) VALUES (?, '名', ?)",
    protected_areas: "INSERT INTO protected_areas (area_id, name_ja, source_id) VALUES (?, '名', ?)",
    vegetation: "INSERT INTO vegetation_polygons (feature_id, legend_name_ja, source_id) VALUES (?, '名', ?)",
    river_segments: "INSERT INTO river_segments (feature_id, name_ja, source_id) VALUES (?, '名', ?)",
    mammal_mesh: "INSERT INTO mammal_mesh (id, species_ja, source_id) VALUES (1, '名', ?)",
    sightings: "INSERT INTO wildlife_sightings (sighting_id, species_ja, source_id) VALUES (?, '名', ?)",
    assessments: "INSERT INTO taxon_assessment (assessment_id, vernacular_name_ja_raw, source_id, list_id) VALUES (?, '名', ?, 'rl')",
  };

  it("全出典・全 record_set で 1 行以上返る（件数 > 0 の宣言の裏づけ）", async () => {
    const raw = new Database(":memory:");
    applyMigrations(raw);
    const ctx: McpContext = { db: async () => wrapSqlite(raw), now: NOW };
    const recordPairs = pairs.filter(([, t]) => t === "get_records");
    expect(recordPairs.length).toBeGreaterThan(0);
    for (const [src] of recordPairs) {
      for (const set of SOURCE_ACCESS[src].tables) {
        const sql = INSERT[set];
        expect(sql, `${src}/${set}`).toBeTruthy();
        raw.prepare(sql).run(...(set === "mammal_mesh" ? [src] : [`${src}:1`, src]));
      }
    }
    for (const [src] of recordPairs) {
      for (const set of SOURCE_ACCESS[src].tables) {
        const r = await call("get_records", { source_id: src, record_set: set }, ctx);
        expect((r.data.rows as unknown[]).length, `${src}/${set}`).toBeGreaterThanOrEqual(1);
        expect(r.data.record_set).toBe(set);
        expect(RECORD_SET_TABLES[set]).toBeTruthy();
      }
    }
    raw.close();
  });
});

const REPO = path.resolve(__dirname, "../../../..");
const P = {
  v2: path.join(REPO, "data/db/v2.sqlite"),
  registry: path.join(REPO, "data/db/registry.sqlite"),
  ryuiki: path.join(REPO, "data/db/ryuiki.sqlite"),
  cells: path.join(REPO, "data/db/cells.sqlite"),
};
const haveReal = Object.values(P).every((p) => fs.existsSync(p));

describe.skipIf(!haveReal)("queryable_via の（出典, ツール）が実際に動く: 実データ（読み取り専用）", () => {
  it("全組で 1 行以上返る", async () => {
    const db = sqliteCubeDb(P);
    const ctx: McpContext = { db: async () => db, now: NOW };
    const failed: string[] = [];
    let ok = 0;
    for (const [src, tool] of pairs) {
      let n = 0;
      if (tool === "get_records") {
        for (const set of SOURCE_ACCESS[src].tables) n += ((await call(tool, { source_id: src, record_set: set, limit: 1 }, ctx)).data.rows as unknown[]).length;
      } else if (tool === "get_occurrences") {
        n = ((await call(tool, { kind: "species_catalog", source_ids: [src], limit: 1 }, ctx)).data.rows as unknown[])?.length ?? 0;
      } else if (tool === "get_edna") {
        const r = await call(tool, {}, ctx);
        n = ((r.data.rows ?? r.rows) as unknown[] | undefined)?.length ?? 0;
      } else if (tool === "get_observations") {
        const variableIds = [...new Set(GENERATED_VARIABLE_ALIASES.filter((a) => a.sourceId === src).map((a) => a.variableId))];
        // 出典の系列の変数ごとに、ゾーン平均 → 水域（地点ごと）の順で、粒度を変えて 1 行でも返るものを探す。
        for (const variableId of variableIds) {
          const waters = ((await call("describe_catalog", { what: "waters", variableId, limit: 50 }, ctx)).data.waters ?? []) as { name?: string; waterName?: string }[];
          // 地点単位の系列（大気・水位・地盤沈下）は水域に属さない。キューブに値のある地点（place_source_ref の site_id）も試す。
          const sites = await db.all<{ k: string; st: string }>(
            "SELECT DISTINCT s.external_key AS k, o.stat AS st FROM observation_agg o JOIN place_source_ref s ON s.place_id = o.place_id AND s.key_space = 'site_id' WHERE o.variable_id = ? LIMIT 12",
            [variableId],
          );
          const scopes = [
            { type: "zone" },
            ...waters.map((w) => ({ type: "water", name: w.name ?? w.waterName })),
            ...sites.map((x) => ({ type: "site", siteId: x.k, stat: x.st })),
          ];
          for (const sc of scopes) {
            const { stat, ...scope } = sc as { type: string; stat?: string };
            for (const grain of ["year", "fiscal_year", "month", "day"] as const) {
              const r = await call(tool, { variableId, scope, grain, from: "2000-01-01", limit: 1, ...(stat && stat !== "mean" ? { stat } : {}) }, ctx);
              n += (((r as { rows?: unknown[] }).rows ?? r.data?.rows) as unknown[] | undefined)?.length ?? 0;
              if (n) break;
            }
            if (n) break;
          }
          if (n) break;
        }
      }
      if (n >= 1) ok += 1;
      else failed.push(`${src}/${tool}`);
    }
    db.close();
    console.log(`queryable_via real check: ${ok}/${pairs.length} (failed: ${failed.join(", ") || "none"})`);
    expect(failed).toEqual([]);
  }, 120_000);
});
