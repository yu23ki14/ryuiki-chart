import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildPlaceId, parseId } from "./parse-id";

describe("parseId（ADR-0004 規約1。ns と key の区切りは最初の '.'）", () => {
  it.each([
    ["jp-14:place:site.env-pubwater.0142", "jp-14", "site", "env-pubwater", "0142"],
    ["jp-14:place:site.atsugi-river.%E7%8E%89%E5%B7%9D", "jp-14", "site", "atsugi-river", "%E7%8E%89%E5%B7%9D"],
    ["common:place:watershed.nlni.83030-0001", "common", "watershed", "nlni", "83030-0001"],
    ["jp-14:place:zone.r2r.3", "jp-14", "zone", "r2r", "3"],
    ["common:place:grid01.3520_13900", "common", "grid01", null, "3520_13900"],
    // key が '.' を含んでも ns は最初の '.' で決まる
    ["jp-14:place:site.jma.a.b.c", "jp-14", "site", "jma", "a.b.c"],
  ])("place: %s", (id, scope, kind, ns, key) => {
    const p = parseId(id);
    expect(p).not.toBeNull();
    expect([p!.scope, p!.entity, p!.kind, p!.ns, p!.key]).toEqual([scope, "place", kind, ns, key]);
    expect(buildPlaceId(p!.scope, p!.kind!, p!.ns, p!.key)).toBe(id);
  });

  it("place 以外は local を最初の '.' で ns と key に切る", () => {
    expect(parseId("common:taxon:gbif.123")).toMatchObject({ entity: "taxon", ns: "gbif", key: "123" });
    expect(parseId("common:taxon:ryuiki-taxa.abc")).toMatchObject({ ns: "ryuiki-taxa", key: "abc" });
    expect(parseId("common:variable:water.bod")).toMatchObject({ ns: "water", key: "bod" });
  });

  it.each([
    "jp-14:place:site.jma-jma_0387", // 旧形式（'-' 区切り）を黙って誤分割しない
    "common:place:watershed.nlni-83030-0001",
    "jp-14:place:zone.r2r-3",
    "no-colon",
    "a:b",
    "common:place:",
    "common:place:site.",
  ])("形が崩れた ID は null: %s", (bad) => {
    expect(parseId(bad)).toBeNull();
  });
});

/**
 * ID の中身を parseId() を通さず読む実装が散らばると、区切りの規則（最初の '.'）が
 * 二重管理になる（R2）。place_id の接頭辞をリテラルで書いている非テストのソースを禁じる。
 */
describe("place_id の分解口は parseId() だけ", () => {
  const SRC = path.resolve(__dirname, "..", "..");
  const ALLOWED = new Set(["generated-id-map.ts"]);

  function walk(dir: string, out: string[] = []): string[] {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name === "__fixtures__" || e.name === "__snapshots__") continue;
        walk(p, out);
      } else if (/\.(ts|tsx)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) {
        out.push(p);
      }
    }
    return out;
  }

  it("`:place:<kind>.` のリテラル接頭辞で ID を切る処理が無い", () => {
    const offenders = walk(SRC)
      .filter((f) => !ALLOWED.has(path.basename(f)))
      .filter((f) =>
        fs
          .readFileSync(f, "utf-8")
          .split("\n")
          .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l)) // コメント行は除く
          .some((l) => /["'`](common|jp-\d+):place:(site|watershed|zone|grid01)\./.test(l)),
      )
      .map((f) => path.relative(SRC, f));
    expect(offenders).toEqual([]);
  });
});
