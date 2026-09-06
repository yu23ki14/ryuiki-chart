import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
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
const BUILD_SCRIPT = path.join(WEB, "scripts", "build-registry-ts.mjs");

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

/**
 * build-registry-ts.mjs のソースのうち、書き出し先を決めている部分。
 * ここだけを一時パス（WEB は固定文字列、OUT は一時ファイル）に差し替えたコピーを作って実行する。
 * `web/scripts/` は他エージェントが編集中のため触れない。ファイル自体は一切書き換えず、
 * メモリ上の文字列に対して置換するだけ（一時ファイルへの書き出しは patched の実行結果のみ）。
 */
const PATH_SETUP_ANCHOR =
  'const __dirname = path.dirname(fileURLToPath(import.meta.url));\n' +
  'const WEB = path.resolve(__dirname, "..");\n' +
  'const REPO = path.resolve(WEB, "..");\n' +
  'const REGISTRY_DB = path.join(REPO, "data", "db", "registry.sqlite");\n' +
  'const VERNACULAR_CSV = path.join(REPO, "registry", "taxon", "vernacular_ja.csv");\n' +
  'const OUT = path.join(WEB, "src", "lib", "registry", "generated.ts");\n';

describe.skipIf(!hasRegistryDb)("build:registry:ts は再生成しても差分が無い", () => {
  it("regenerate produces byte-identical output（追跡対象の generated.ts は書き換えない）", () => {
    const original = fs.readFileSync(BUILD_SCRIPT, "utf-8");
    if (!original.includes(PATH_SETUP_ANCHOR)) {
      throw new Error(
        "build-registry-ts.mjs のパス定義（WEB/REPO/REGISTRY_DB/VERNACULAR_CSV/OUT）の書式が" +
          "想定と変わっている。このテストの一時出力先への差し替えが効かなくなっているので、" +
          "PATH_SETUP_ANCHOR を実物に合わせて更新すること。",
      );
    }

    const tmpDir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "registry-ts-check-"));
    const tmpOut = path.join(tmpDir, "generated.ts");
    try {
      // WEB/REGISTRY_DB は既知の絶対パスに固定し、OUT だけ一時ファイルに向ける。
      // スクリプト本体（web/scripts/build-registry-ts.mjs）には一切書き込まない。
      const patched = original.replace(
        PATH_SETUP_ANCHOR,
        `const WEB = ${JSON.stringify(WEB)};\n` +
          'const REPO = path.resolve(WEB, "..");\n' +
          `const REGISTRY_DB = ${JSON.stringify(REGISTRY_DB)};\n` +
          'const VERNACULAR_CSV = path.join(REPO, "registry", "taxon", "vernacular_ja.csv");\n' +
          `const OUT = ${JSON.stringify(tmpOut)};\n`,
      );

      // bare import（better-sqlite3 等）が web/node_modules を解決できるよう、
      // node をコード文字列（--input-type=module -e）で cwd=WEB のまま実行する。
      // ファイルとしてどこかに書き出す必要が無いので、web/scripts/ は触らずに済む。
      execFileSync("node", ["--input-type=module", "-e", patched], { cwd: WEB, stdio: "pipe" });

      const after = fs.readFileSync(tmpOut, "utf-8");
      const before = fs.readFileSync(GENERATED_PATH, "utf-8");
      expect(after).toBe(before);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
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
