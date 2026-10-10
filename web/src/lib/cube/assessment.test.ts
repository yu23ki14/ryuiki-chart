import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { buildOccurrenceFixture, FX_VOCAB, type OccurrenceFixture } from "./__fixtures__/occurrence-fixture";
import { redlistFlows, redlistSpecies, redlistSummary, type AssessmentVocab } from "./assessment";

const vocab = FX_VOCAB as unknown as AssessmentVocab;

let fx: OccurrenceFixture;
beforeEach(() => {
  fx = buildOccurrenceFixture();
});
afterEach(() => fx.db.close());

describe("redlistSummary", () => {
  it("版×分類群×direction の件数。外来種リスト（kind≠red_list）と他地域（jp-46）の版は含めない", async () => {
    expect(await redlistSummary(fx.db, vocab)).toEqual([
      { listYear: 2020, listName: "RL2020", taxonGroupJa: "植物", direction: "前回記載なし", n: 1 },
      { listYear: 2020, listName: "RL2020", taxonGroupJa: "植物", direction: "横ばい", n: 1 },
      { listYear: 2020, listName: "RL2020", taxonGroupJa: "鳥類", direction: "悪化", n: 2 },
      { listYear: 2020, listName: "RL2020", taxonGroupJa: "鳥類", direction: "改善", n: 1 },
      { listYear: 2026, listName: "RL2026", taxonGroupJa: "鳥類", direction: "横ばい", n: 1 },
    ]);
  });
});

describe("redlistFlows", () => {
  it("前回・今回の両方にカテゴリがある行だけ。n 降順", async () => {
    expect(await redlistFlows(fx.db, 2020, undefined, vocab)).toEqual([
      { prevLabel: "絶滅危惧IB類", curLabel: "絶滅危惧IA類", direction: "悪化", n: 2 },
      { prevLabel: "絶滅危惧IA類", curLabel: "絶滅危惧IB類", direction: "改善", n: 1 },
      { prevLabel: "絶滅危惧II類", curLabel: "絶滅危惧II類", direction: "横ばい", n: 1 },
    ]);
  });
  it("分類群で絞れる", async () => {
    expect(await redlistFlows(fx.db, 2020, "植物", vocab)).toEqual([
      { prevLabel: "絶滅危惧II類", curLabel: "絶滅危惧II類", direction: "横ばい", n: 1 },
    ]);
  });
});

describe("redlistSpecies", () => {
  it("(cur_rank - prev_rank) 降順 → 和名。前回記載なしは出さない", async () => {
    const rows = await redlistSpecies(fx.db, 2020, undefined, undefined, 300, vocab);
    expect(rows.map((r) => [r.vernacularNameJa, r.direction])).toEqual([
      ["アルファ", "悪化"],
      ["イプシロン", "悪化"],
      ["ガンマ", "横ばい"],
      ["ベータ", "改善"],
    ]);
    expect(rows[0]).toMatchObject({ prevLabel: "絶滅危惧IB類", curLabel: "絶滅危惧IA類", prevRank: 50, curRank: 60, nationalCategoryJa: "国:NT" });
  });
  it("direction・group・limit", async () => {
    expect((await redlistSpecies(fx.db, 2020, "悪化", undefined, 300, vocab)).length).toBe(2);
    expect((await redlistSpecies(fx.db, 2020, "悪化", undefined, 1, vocab)).length).toBe(1);
    expect((await redlistSpecies(fx.db, 2020, undefined, "植物", 300, vocab)).map((r) => r.vernacularNameJa)).toEqual(["ガンマ"]);
  });
});
