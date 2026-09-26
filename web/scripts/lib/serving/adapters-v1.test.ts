import { describe, expect, it } from "vitest";
import { snapshotSubset } from "./adapters-v1";

describe("snapshotSubset", () => {
  const all = Array.from({ length: 25 }, (_, i) => ({ site_id: `s${i}` }));

  it("every 個おきに1つ選ぶ", () => {
    const subset = snapshotSubset(all, { every: 10 });
    expect(subset).toEqual([{ site_id: "s0" }, { site_id: "s10" }, { site_id: "s20" }]);
  });

  it("plus で名指ししたものを、全体に実在すれば追加する", () => {
    const subset = snapshotSubset(all, { every: 10, plus: [{ site_id: "s5" }] });
    expect(subset).toContainEqual({ site_id: "s5" });
    expect(subset).toHaveLength(4);
  });

  it("plus が既に選ばれていれば重複させない", () => {
    const subset = snapshotSubset(all, { every: 10, plus: [{ site_id: "s0" }] });
    expect(subset).toHaveLength(3);
  });

  it("plus が全体に実在しなければ足さない", () => {
    const subset = snapshotSubset(all, { every: 10, plus: [{ site_id: "does-not-exist" }] });
    expect(subset).toHaveLength(3);
  });
});
