import { describe, expect, it } from "vitest";
import { OCCURRENCE_SOURCE_IDS, SOURCE_REGION } from "@/lib/registry/generated-source";

describe("出現データの出典の地域宣言", () => {
  it("OCCURRENCE_SOURCE_IDS の全てに SOURCE_REGION がある（出典基準と region_id 基準の絞りが一致する前提）", () => {
    for (const id of OCCURRENCE_SOURCE_IDS) expect(SOURCE_REGION[id], id).toBeDefined();
  });
});
