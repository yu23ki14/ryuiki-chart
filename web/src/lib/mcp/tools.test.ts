import { describe, expect, it } from "vitest";
import { listTools } from "./server";

/**
 * 公開範囲の不変条件 5: 任意 SQL・全表走査が MCP に無い。ツール一覧と入力スキーマをスナップショットで固定する
 * （`EXPLORE_ENABLED` とは独立に成立する）。ツールを足す・入力を広げる変更は、このスナップショットの差分として
 * レビューに出る。
 */
describe("MCP ツール一覧（第1段 5 本）", () => {
  it("名前は 5 本で、SQL・表を直接触るツールが無い", () => {
    const names = listTools().map((t) => t.name);
    expect(names).toEqual(["describe_catalog", "search_registry", "get_observations", "get_occurrences", "get_edna", "export_dataset"]);
    expect(names.join(",")).not.toMatch(/sql|query|table|schema/);
  });

  it("どのツールの入力にも SQL・表名・任意の WHERE を受ける引数が無い", () => {
    const keys: string[] = [];
    const walk = (v: unknown) => {
      if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === "object") {
        for (const [k, x] of Object.entries(v)) {
          if (k === "properties") keys.push(...Object.keys(x as object));
          walk(x);
        }
      }
    };
    walk(listTools().map((t) => t.inputSchema));
    expect(keys.filter((k) => /sql|where|table|statement|expr/i.test(k))).toEqual([]);
  });

  it("z.tuple（prefixItems）を使っていない（Workers AI の JSON Schema 検証の既知の罠）", () => {
    expect(JSON.stringify(listTools())).not.toContain("prefixItems");
  });

  it("入力スキーマのスナップショット", () => {
    expect(listTools()).toMatchSnapshot();
  });
});
