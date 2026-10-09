import { describe, expect, it } from "vitest";
import { load as loadYaml } from "js-yaml";
import { readZoneDefinition } from "../../../scripts/lib/zone-definition.mjs";

/**
 * registry/place/zone.yaml（v2。docs/plans/AMAMI_STEP0.md §1.3）の読み出し。
 * 新構造の小さなフィクスチャで、build-registry-ts.mjs が使う読み出し（ZONE_INFO・版）を確かめる。
 */
const FIXTURE = `
definition_version: 2
note_ja: 島では山地が大半を占める。
terrain: { dem_tile_zoom: 14 }
rule: { coast_dist_max_m: 2000 }
zones:
  - { zone: 3, name_ja: 丘陵・台地・扇状地, condition_ja: c3, ui_condition_ja: u3 }
  - { zone: 1, name_ja: 山地源流域, condition_ja: c1, ui_condition_ja: u1 }
  - { zone: 2, name_ja: 山地渓流, condition_ja: c2, ui_condition_ja: u2 }
  - { zone: 5, name_ja: 河口・沿岸, condition_ja: c5, ui_condition_ja: u5 }
  - { zone: 4, name_ja: 平野・沖積低地, condition_ja: c4, ui_condition_ja: u4 }
`;

describe("readZoneDefinition（zone.yaml v2）", () => {
  it("zones を zone 昇順の ZONE_INFO 形（zone/label/cond）にし、版を返す", () => {
    const r = readZoneDefinition(loadYaml(FIXTURE));
    expect(r.version).toBe(2);
    expect(r.zoneInfo.map((z: { zone: number }) => z.zone)).toEqual([1, 2, 3, 4, 5]);
    expect(r.zoneInfo[2]).toEqual({ zone: 3, label: "丘陵・台地・扇状地", cond: "u3" });
    expect(r.note).toContain("山地");
  });

  it("旧形式（トップがリスト）・版なし・重複・欠落は止まる", () => {
    const doc = () => loadYaml(FIXTURE) as Record<string, unknown> & { zones: Record<string, unknown>[] };
    expect(() => readZoneDefinition([{ zone: 1 }])).toThrow(/マッピング/);
    expect(() => readZoneDefinition({ ...doc(), definition_version: "2" })).toThrow(/definition_version/);
    expect(() => readZoneDefinition({ ...doc(), note_ja: "" })).toThrow(/note_ja/);
    const dup = doc();
    dup.zones[0].zone = 1;
    expect(() => readZoneDefinition(dup)).toThrow(/重複/);
    const noCond = doc();
    delete noCond.zones[0].ui_condition_ja;
    expect(() => readZoneDefinition(noCond)).toThrow(/ui_condition_ja/);
    expect(() => readZoneDefinition({ ...doc(), zones: [] })).toThrow(/zones/);
  });
});
