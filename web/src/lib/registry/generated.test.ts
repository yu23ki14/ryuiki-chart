import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { describe, expect, it } from "vitest";
import {
  GENERATED_UNITS,
  GENERATED_VARIABLES,
  GENERATED_VARIABLE_ALIASES,
} from "@/lib/registry/generated";
import {
  GENERATED_CAVEATS,
  GENERATED_CAVEAT_SCOPE,
  NAME_JA,
} from "@/lib/registry/generated-client";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..", "..", "..");
const GENERATED_SERVER_PATH = path.join(WEB, "src", "lib", "registry", "generated.ts");
const GENERATED_CLIENT_PATH = path.join(WEB, "src", "lib", "registry", "generated-client.ts");
const REGISTRY_DB = path.join(WEB, "..", "data", "db", "registry.sqlite");
const BUILD_SCRIPT = path.join(WEB, "scripts", "build-registry-ts.mjs");
const REGISTRY_CODEGEN = path.join(WEB, "scripts", "lib", "registry-codegen.mjs");

/**
 * `generated.ts`（サーバ専用）・`generated-client.ts`（クライアント安全）は生成物
 * （`web/scripts/build-registry-ts.mjs` が `data/db/registry.sqlite` から作る）。
 * 「再生成しても差分が出ない」ことが生成物の陳腐化を防ぐ受け入れ条件
 * （docs/plans/PHASE_A.md §A-7。2ファイルに分けた経緯は code-review #4）。
 *
 * `data/db/registry.sqlite` が無い環境（CI でレジストリのビルドを走らせていない等）では
 * このテストをスキップする（`pnpm run build:registry` が先に要る、というだけで
 * generated.ts / generated-client.ts 自体の内容が壊れているわけではないため）。
 */
const hasRegistryDb = fs.existsSync(REGISTRY_DB);

/**
 * build-registry-ts.mjs のソースのうち、書き出し先とコード生成ロジックの読み込み元を
 * 決めている部分。ここだけを一時パス（WEB は固定文字列、OUT_* は一時ファイル、
 * registry-codegen.mjs は絶対パス）に差し替えたコピーを作って実行する。
 *
 * registry-codegen.mjs の import を絶対パスに差し替える理由: この検証は
 * `execFileSync("node", ["--input-type=module", "-e", patched], {cwd: WEB})` で
 * ソースを文字列として渡して実行する。Node の `--input-type=module -e` は相対 import を
 * ファイルの位置ではなく cwd 基準で解決するため、本来の相対 import
 * `"./lib/registry-codegen.mjs"`（`web/scripts/build-registry-ts.mjs` から見た相対パス）は
 * cwd=WEB のときに `web/lib/registry-codegen.mjs`（存在しない）に解決されてしまう。
 * 実行時の解決を壊さないよう、本体のソースは相対 import のままにし、検証用にコピーした
 * 文字列だけ絶対パスに変換する。
 */
const PATH_SETUP_ANCHOR =
  'const __dirname = path.dirname(fileURLToPath(import.meta.url));\n' +
  'const WEB = path.resolve(__dirname, "..");\n' +
  'const REPO = path.resolve(WEB, "..");\n' +
  'const REGISTRY_DB = path.join(REPO, "data", "db", "registry.sqlite");\n' +
  'const VERNACULAR_CSV = path.join(REPO, "registry", "taxon", "vernacular_ja.csv");\n' +
  'const OUT_SERVER = path.join(WEB, "src", "lib", "registry", "generated.ts");\n' +
  'const OUT_CLIENT = path.join(WEB, "src", "lib", "registry", "generated-client.ts");\n';

const CODEGEN_IMPORT_ANCHOR = 'import { buildClientVariableMaps } from "./lib/registry-codegen.mjs";\n';

describe.skipIf(!hasRegistryDb)("build:registry:ts は再生成しても差分が無い", () => {
  it("regenerate produces byte-identical output（追跡対象の generated.ts / generated-client.ts は書き換えない）", () => {
    const original = fs.readFileSync(BUILD_SCRIPT, "utf-8");
    if (!original.includes(PATH_SETUP_ANCHOR)) {
      throw new Error(
        "build-registry-ts.mjs のパス定義（WEB/REPO/REGISTRY_DB/VERNACULAR_CSV/OUT_SERVER/OUT_CLIENT）の" +
          "書式が想定と変わっている。このテストの一時出力先への差し替えが効かなくなっているので、" +
          "PATH_SETUP_ANCHOR を実物に合わせて更新すること。",
      );
    }
    if (!original.includes(CODEGEN_IMPORT_ANCHOR)) {
      throw new Error(
        "build-registry-ts.mjs の registry-codegen.mjs の import 文の書式が想定と変わっている。" +
          "CODEGEN_IMPORT_ANCHOR を実物に合わせて更新すること。",
      );
    }

    const tmpDir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "registry-ts-check-"));
    const tmpOutServer = path.join(tmpDir, "generated.ts");
    const tmpOutClient = path.join(tmpDir, "generated-client.ts");
    try {
      // WEB/REGISTRY_DB は既知の絶対パスに固定し、OUT_* だけ一時ファイルに向ける。
      // スクリプト本体（web/scripts/build-registry-ts.mjs）には一切書き込まない。
      const patched = original
        .replace(
          PATH_SETUP_ANCHOR,
          `const WEB = ${JSON.stringify(WEB)};\n` +
            'const REPO = path.resolve(WEB, "..");\n' +
            `const REGISTRY_DB = ${JSON.stringify(REGISTRY_DB)};\n` +
            'const VERNACULAR_CSV = path.join(REPO, "registry", "taxon", "vernacular_ja.csv");\n' +
            `const OUT_SERVER = ${JSON.stringify(tmpOutServer)};\n` +
            `const OUT_CLIENT = ${JSON.stringify(tmpOutClient)};\n`,
        )
        .replace(
          CODEGEN_IMPORT_ANCHOR,
          `import { buildClientVariableMaps } from ${JSON.stringify(pathToFileURL(REGISTRY_CODEGEN).href)};\n`,
        );

      // bare import（better-sqlite3 等）が web/node_modules を解決できるよう、
      // node をコード文字列（--input-type=module -e）で cwd=WEB のまま実行する。
      // ファイルとしてどこかに書き出す必要が無いので、web/scripts/ は触らずに済む。
      execFileSync("node", ["--input-type=module", "-e", patched], { cwd: WEB, stdio: "pipe" });

      expect(fs.readFileSync(tmpOutServer, "utf-8")).toBe(fs.readFileSync(GENERATED_SERVER_PATH, "utf-8"));
      expect(fs.readFileSync(tmpOutClient, "utf-8")).toBe(fs.readFileSync(GENERATED_CLIENT_PATH, "utf-8"));
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});

/**
 * 生成物の形の健全性（regenerate できない環境でも実行できる、軽い形チェック）。
 */
describe("generated.ts / generated-client.ts の形", () => {
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

  it("variable_alias が参照する variableId / unitId は実在するもの以外は null（generated.ts、サーバ専用）", () => {
    const variableIds = new Set(GENERATED_VARIABLES.map((v) => v.variableId));
    const unitIds = new Set(GENERATED_UNITS.map((u) => u.unitId));
    for (const a of GENERATED_VARIABLE_ALIASES) {
      if (a.variableId !== null) expect(variableIds.has(a.variableId)).toBe(true);
      if (a.unitId !== null) expect(unitIds.has(a.unitId)).toBe(true);
    }
  });

  it("和名台帳（NAME_JA、generated-client.ts）は54件", () => {
    expect(Object.keys(NAME_JA)).toHaveLength(54);
  });
});
