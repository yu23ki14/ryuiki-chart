import { getTableConfig, type SQLiteTable } from "drizzle-orm/sqlite-core";
import { describe, expect, it } from "vitest";
import * as cube from "@/db/schema-cube";
import * as registry from "@/db/schema-registry";
import * as v1 from "@/db/schema";
import { TABLE_META, TABLE_ORIGIN } from "@/lib/table-meta";

/** Drizzle のスキーマ 3 ファイル（`drizzle.config.ts` の schema）が定義する表名。 */
function schemaTableNames(): string[] {
  const names: string[] = [];
  for (const mod of [v1, registry, cube]) {
    for (const value of Object.values(mod)) {
      if (value && typeof value === "object" && Symbol.for("drizzle:IsDrizzleTable") in value) {
        names.push(getTableConfig(value as SQLiteTable).name);
      }
    }
  }
  return names;
}

describe("table-meta と D1 スキーマの整合", () => {
  it("D1 の全表（Drizzle のスキーマ）が TABLE_ORIGIN と TABLE_META に載っている", () => {
    const names = schemaTableNames().filter((n) => !n.startsWith("_")); // _seed_state などシード管理の内部表は除く
    expect(names.length).toBeGreaterThan(40);
    for (const name of names) {
      expect(TABLE_ORIGIN, name).toHaveProperty(name);
      expect(TABLE_META, name).toHaveProperty(name);
    }
  });

  it("地域で絞る切り替え（Issue #93）の新表 5 つは v2 由来", () => {
    for (const name of [
      "place_region",
      "summary_species_catalog_by_region",
      "summary_taxon_catalog_by_region",
      "summary_effort_year_by_region",
      "summary_variable_catalog_by_region",
    ]) {
      expect(TABLE_ORIGIN[name], name).toBe("v2");
      expect(TABLE_META[name], name).toBeTruthy();
    }
  });
});
