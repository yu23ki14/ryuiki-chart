import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  GENERATED_CAVEATS,
  GENERATED_CAVEAT_SCOPE,
  GENERATED_UNITS,
  GENERATED_VARIABLES,
  GENERATED_VARIABLE_ALIASES,
  GENERATED_VERNACULAR_JA,
} from "@/lib/registry/generated";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..", "..", "..");
const GENERATED_PATH = path.join(WEB, "src", "lib", "registry", "generated.ts");
const REGISTRY_DB = path.join(WEB, "..", "data", "db", "registry.sqlite");

/**
 * `generated.ts` は生成物（`web/scripts/build-registry-ts.mjs` が
 * `data/db/registry.sqlite` から作る）。「再生成しても差分が出ない」ことが
 * 生成物の陳腐化を防ぐ受け入れ条件（docs/plans/PHASE_A.md §A-7）。
 *
 * `data/db/registry.sqlite` が無い環境（CI でレジストリのビルドを走らせていない等）では
 * このテストをスキップする（`pnpm run build:registry` が先に要る、というだけで
 * generated.ts 自体の内容が壊れているわけではないため）。
 */
const hasRegistryDb = fs.existsSync(REGISTRY_DB);

describe.skipIf(!hasRegistryDb)("build:registry:ts は再生成しても差分が無い", () => {
  it("regenerate produces byte-identical output", () => {
    const before = fs.readFileSync(GENERATED_PATH, "utf-8");
    execFileSync("node", ["scripts/build-registry-ts.mjs"], { cwd: WEB, stdio: "pipe" });
    const after = fs.readFileSync(GENERATED_PATH, "utf-8");
    try {
      expect(after).toBe(before);
    } finally {
      // 差分が無い前提のテストなので書き戻しは不要だが、万一 before != after だった場合に
      // 作業ツリーを壊れたままにしない。
      if (after !== before) fs.writeFileSync(GENERATED_PATH, before);
    }
  });
});

/**
 * 生成物の形の健全性（regenerate できない環境でも実行できる、軽い形チェック）。
 */
describe("generated.ts の形", () => {
  it("caveat は cells.notes 由来（207件）を含まない14件のまま", () => {
    expect(GENERATED_CAVEATS).toHaveLength(14);
    expect(GENERATED_CAVEATS.every((c) => !c.key.startsWith("cells."))).toBe(true);
  });

  it("caveat_scope は table/table_prefix/table_synthetic のみ", () => {
    expect(GENERATED_CAVEAT_SCOPE.length).toBeGreaterThan(0);
    expect(
      GENERATED_CAVEAT_SCOPE.every((s) => s.scopeKind === "table" || s.scopeKind === "table_prefix" || s.scopeKind === "table_synthetic"),
    ).toBe(true);
  });

  it("caveat_scope が参照する caveatKey はすべて GENERATED_CAVEATS に実在する", () => {
    const keys = new Set(GENERATED_CAVEATS.map((c) => c.key));
    for (const s of GENERATED_CAVEAT_SCOPE) expect(keys.has(s.caveatKey)).toBe(true);
  });

  it("variable_alias が参照する variableId / unitId は実在するもの以外は null", () => {
    const variableIds = new Set(GENERATED_VARIABLES.map((v) => v.variableId));
    const unitIds = new Set(GENERATED_UNITS.map((u) => u.unitId));
    for (const a of GENERATED_VARIABLE_ALIASES) {
      if (a.variableId !== null) expect(variableIds.has(a.variableId)).toBe(true);
      if (a.unitId !== null) expect(unitIds.has(a.unitId)).toBe(true);
    }
  });

  it("和名台帳（NAME_JA 由来）は54件", () => {
    expect(GENERATED_VERNACULAR_JA).toHaveLength(54);
  });
});
