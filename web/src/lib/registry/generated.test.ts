import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  GENERATED_CAVEATS,
  GENERATED_CAVEAT_SCOPE,
  NAME_JA,
  ZONE_INFO,
} from "@/lib/registry/generated-client";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, "..", "..", "..");
const GENERATED_SERVER_PATH = path.join(WEB, "src", "lib", "registry", "generated.ts");
const GENERATED_CLIENT_PATH = path.join(WEB, "src", "lib", "registry", "generated-client.ts");
// build-registry-ts.mjs と同じく RYUIKI_REGISTRY_DB を見る（code-review 指摘: 以前は
// data/db/registry.sqlite に決め打ちで、CI が --files-only 用に別ファイルへ書いても
// このテストの skip 判定にも子プロセスへ渡す入力パスにも反映されなかった）。
// scripts/r01_build_registry.py --files-only の既定の書き込み先も正規の registry.sqlite
// とは別ファイル（registry_files_only.sqlite）なので、環境変数を渡さなければ
// このテストは「正規の registry.sqlite がある環境だけ実行する」という元の意味を保つ。
const REGISTRY_DB = process.env.RYUIKI_REGISTRY_DB ?? path.join(WEB, "..", "data", "db", "registry.sqlite");
const BUILD_SCRIPT = path.join(WEB, "scripts", "build-registry-ts.mjs");

/**
 * `generated.ts`（サーバ専用）・`generated-client.ts`（クライアント安全）は生成物
 * （`web/scripts/build-registry-ts.mjs` が registry.sqlite から作る）。
 * 「再生成しても差分が出ない」ことが生成物の陳腐化を防ぐ受け入れ条件
 * （docs/plans/PHASE_A.md §A-7。2ファイルに分けた経緯は code-review #4）。
 *
 * registry.sqlite が無い環境（CI でレジストリのビルドを走らせていない等）では
 * このテストをスキップする（先にビルドが要る、というだけで
 * generated.ts / generated-client.ts 自体の内容が壊れているわけではないため）。
 */
const hasRegistryDb = fs.existsSync(REGISTRY_DB);

describe.skipIf(!hasRegistryDb)("build:registry:ts は再生成しても差分が無い", () => {
  it("regenerate produces byte-identical output（追跡対象の generated.ts / generated-client.ts は書き換えない）", () => {
    // build-registry-ts.mjs の入出力パスは環境変数で上書きできる（RYUIKI_REGISTRY_DB /
    // RYUIKI_REGISTRY_TS_OUT_SERVER / RYUIKI_REGISTRY_TS_OUT_CLIENT。スクリプト冒頭の
    // コメント参照）。実物のスクリプトをソース文字列の書き換え無しにそのまま
    // 一時ディレクトリ向けに実行し、生成物を追跡対象のファイルと比較する
    // （/simplify 修正6: 以前はスクリプトのソースをアンカー文字列で `.replace()` して
    // 実行しており、意味を変えない整形だけでもテストが落ちた）。
    const tmpDir = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), "registry-ts-check-"));
    const tmpOutServer = path.join(tmpDir, "generated.ts");
    const tmpOutClient = path.join(tmpDir, "generated-client.ts");
    try {
      execFileSync("node", [BUILD_SCRIPT], {
        cwd: WEB,
        stdio: "pipe",
        env: {
          ...process.env,
          RYUIKI_REGISTRY_DB: REGISTRY_DB,
          RYUIKI_REGISTRY_TS_OUT_SERVER: tmpOutServer,
          RYUIKI_REGISTRY_TS_OUT_CLIENT: tmpOutClient,
        },
      });

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

  it("caveat_scope は table/table_prefix のみ（優先度は scope_kind ではなく priority 列が持つ）", () => {
    expect(GENERATED_CAVEAT_SCOPE.length).toBeGreaterThan(0);
    expect(GENERATED_CAVEAT_SCOPE.every((s) => s.scopeKind === "table" || s.scopeKind === "table_prefix")).toBe(true);
    expect(GENERATED_CAVEAT_SCOPE.some((s) => s.priority > 0)).toBe(true);
  });

  it("和名台帳（NAME_JA、generated-client.ts）は54件", () => {
    expect(Object.keys(NAME_JA)).toHaveLength(54);
  });

  /**
   * `Plecoglossus altivelis`（アユ）に地域個体群の和名「リュウキュウアユ」が誤って
   * 付いていないことの回帰ガード（旧 domain.test.ts。code-review 指摘: これは「レジストリに
   * 語彙を足すたびに赤くなる」全件一致テストではなく、既知の1件の誤りが再発しないことだけを
   * 見る狭いテストなので、domain.ts 撤去後もここに残す価値がある）。
   *
   * `NAME_JA` は `registry/taxon/vernacular_ja.csv` 直読みで、taxa テーブルの和名を学名で
   * 機械結合したものではない。機械結合すると別地域の個体群の名前が付く事故が実際にあった
   * （`Plecoglossus altivelis` に「リュウキュウアユ」。docs/plans/PHASE_A.md §A-4）。
   */
  it("Plecoglossus altivelis に地域個体群の和名（リュウキュウアユ）が誤って付いていないこと", () => {
    expect(NAME_JA["Plecoglossus altivelis"]).not.toBe("リュウキュウアユ");
  });

  it("ZONE_INFO（generated-client.ts）は5件、zoneは1..5が過不足なく揃っている", () => {
    expect(ZONE_INFO).toHaveLength(5);
    expect(ZONE_INFO.map((z) => z.zone).sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5]);
    for (const z of ZONE_INFO) {
      expect(z.label.length).toBeGreaterThan(0);
      expect(z.cond.length).toBeGreaterThan(0);
    }
  });
});
