import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { LEGACY_PLACE_ID_MAP } from "./generated-id-map";
import { legacyPlaceIdToCurrent, resolveLegacyId } from "./legacy-id";
import { parseId } from "./parse-id";

// 正は registry/id_map/place.csv（手書きの宣言。生成物 generated-id-map.ts との一致もここで固定する）。
const CSV = path.resolve(__dirname, "..", "..", "..", "..", "registry", "id_map", "place.csv");

function loadCsv(): { old: string; neu: string }[] {
  const lines = fs.readFileSync(CSV, "utf-8").trim().split("\n");
  expect(lines[0]).toBe("old_id,new_id,reason,spec_version");
  return lines.slice(1).map((l) => {
    const [old, neu] = l.split(",");
    return { old, neu };
  });
}

describe("旧 place_id の受理（resolveLegacyId）", () => {
  const rows = loadCsv();

  it("宣言（place.csv）の全行が旧→新で引ける（生成物と宣言が一致）", () => {
    expect(rows.length).toBeGreaterThan(0);
    expect(Object.keys(LEGACY_PLACE_ID_MAP)).toHaveLength(rows.length);
    for (const { old, neu } of rows) {
      expect(legacyPlaceIdToCurrent(old)).toBe(neu);
      expect(resolveLegacyId(old)).toEqual({ id: neu, resolvedFrom: old });
    }
  });

  it("新 ID は parseId() で分解でき、旧 ID は分解できない（区切りが違う）。zone の昇格前 ID（jp-14:place:zone.r2r.N）だけは例外", () => {
    // zone は jp-14 から common へ昇格した。昇格前の `zone.r2r.N` は今の区切りで分解できる（zone.r2r-N は分解できない）。
    const isPromotedZoneOld = (old: string) => /^jp-14:place:zone\.r2r\.\d+$/.test(old);
    for (const { old, neu } of rows) {
      expect(parseId(neu)).not.toBeNull();
      if (isPromotedZoneOld(old)) {
        expect(neu).toBe(old.replace("jp-14:", "common:"));
        expect(parseId(old)).not.toBeNull();
      } else {
        expect(parseId(old)).toBeNull();
      }
    }
  });

  it("新 ID・grid01・未知の ID は恒等（resolvedFrom なし）", () => {
    for (const id of [
      "jp-14:place:site.jma.jma_0387",
      "common:place:grid01.3520_13900", // grid01 は ID が変わっていない
      "common:place:watershed.nlni.83030-0001",
      "common:place:watershed.nlni-none",
      "unknown",
      "",
    ]) {
      expect(legacyPlaceIdToCurrent(id)).toBeNull();
      expect(resolveLegacyId(id)).toEqual({ id });
    }
  });

  it("Object.prototype のキー（constructor 等）を旧 ID と取り違えない", () => {
    expect(legacyPlaceIdToCurrent("constructor")).toBeNull();
    expect(resolveLegacyId("__proto__")).toEqual({ id: "__proto__" });
  });
});
