import { describe, expect, it } from "vitest";
import { GENERATED_VARIABLE_ALIASES } from "@/lib/registry/generated";
import { SOURCE_EDITIONS, SOURCE_META } from "@/lib/registry/generated-source";
import { ageDays, currentEdition, fetchedAtIso, freshnessFor, OCCURRENCE_SOURCE_IDS, sourceCitation, sourceFreshness } from "./source-meta";

describe("source-meta（出典メタ。registry の生成物から引く）", () => {
  const NOW = new Date("2026-10-06T03:00:00Z");

  it("fetched_at に region の時刻帯を付ける", () => {
    expect(fetchedAtIso("2026-08-30T16:20:58")).toBe("2026-08-30T16:20:58+09:00");
    expect(() => fetchedAtIso("2026-08-30")).toThrow(/書式/);
  });

  it("age_days は region の暦日差", () => {
    expect(ageDays("2026-10-06T00:00:00", NOW)).toBe(0);
    expect(ageDays("2026-10-05T23:59:59", NOW)).toBe(1);
    // UTC では 10-06 だが JST では 10-07
    expect(ageDays("2026-10-06T00:00:00", new Date("2026-10-06T15:00:00Z"))).toBe(1);
  });

  it("全出典が現行の edition を持つ（取得日があれば fetched_at は時刻帯つき）", () => {
    for (const m of SOURCE_META) {
      const f = sourceFreshness(m.sourceId, { now: NOW });
      expect(f.source_edition_id, m.sourceId).not.toBeNull();
      if (f.fetched_at !== null) expect(f.fetched_at).toMatch(/\+09:00$/);
    }
  });

  it("update_mode は宣言値か 'undeclared'。NULL を別の値に倒さない", () => {
    for (const e of SOURCE_EDITIONS) {
      const f = sourceFreshness(e.sourceId, { now: NOW, editionKey: e.editionKey });
      expect(f.update_mode).toBe(e.updateMode ?? "undeclared");
    }
  });

  it("未知の出典は edition なし・undeclared・fetched_at null（推測で埋めない）", () => {
    expect(sourceFreshness("no_such_source", { now: NOW })).toEqual({
      source_id: "no_such_source",
      source_edition_id: null,
      fetched_at: null,
      update_mode: "undeclared",
      age_days: null,
    });
  });

  it("版が複数ある出典は editionKey で選べ、既定は取得日が最も新しい版", () => {
    const id = "nlni_l03b_landuse_by_watershed";
    expect(currentEdition(id, "2016")?.editionKey).toBe("2016");
    expect(currentEdition(id)?.editionKey).toBe("2006"); // 取得日 15:05 > 2016 の 15:03
  });

  it("旗（redistributable）を載せるが、ここで何も絞らない（旗が false の出典も引ける。ADR-0028）", () => {
    const flags = SOURCE_EDITIONS.map((e) => sourceCitation(e.sourceId, { now: NOW, editionKey: e.editionKey }).redistributable);
    expect(flags).toContain(false);
  });

  it("freshnessFor は重複を除く", () => {
    expect(freshnessFor(["a", "a", "b"]).map((f) => f.source_id)).toEqual(["a", "b"]);
  });

  it("OCCURRENCE_SOURCE_IDS は registry の出典として実在する", () => {
    const ids = new Set(SOURCE_META.map((m) => m.sourceId));
    for (const id of OCCURRENCE_SOURCE_IDS) expect(ids.has(id), id).toBe(true);
  });

  it("測定値系列（measurements）の出典に合成センサー出典は含まれない", () => {
    const sources = GENERATED_VARIABLE_ALIASES.filter((a) => a.dataset === "measurements").map((a) => a.sourceId);
    expect(sources.some((s) => s !== null && s.startsWith("synthetic"))).toBe(false);
  });
});
