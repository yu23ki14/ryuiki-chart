import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const require = createRequire(path.join(WEB, "package.json"));
export const Database = require("better-sqlite3");
export const D1_STATE = path.join(WEB, ".wrangler", "state", "v3", "d1", "miniflare-D1DatabaseObject");
export const DB_NAME = "ryuiki";
export const qi = (n) => `"${String(n).replace(/"/g, '""')}"`;
export const isInternal = (n) =>
  n.startsWith("_cf_") || n.startsWith("sqlite_") || n === "d1_migrations" || n === "_seed_state";

export function findLocalD1() {
  const files = fs.readdirSync(D1_STATE)
    .filter((f) => f.endsWith(".sqlite") && f !== "metadata.sqlite")
    .map((f) => path.join(D1_STATE, f));
  if (files.length !== 1) throw new Error(`ローカル D1 を一意に決められない: ${JSON.stringify(files)}`);
  return files[0];
}

/** wrangler d1 execute --remote --json。複数文を渡すと文ごとの結果配列が返る。 */
export function wranglerRemote(sql) {
  const out = execFileSync(
    "pnpm",
    ["wrangler", "d1", "execute", DB_NAME, "--remote", "-y", "--json", "--command", sql],
    { encoding: "utf8", maxBuffer: 256 * 1024 * 1024, cwd: WEB, env: process.env, stdio: ["ignore", "pipe", "inherit"] },
  );
  return JSON.parse(out.slice(out.indexOf("[")));
}

/** `pnpm wrangler <args>`（ローカルの wrangler。web/ で実行。標準出力を文字列で返す）。ベクトル検索のスクリプトも使う。 */
export function wrangler(args, { quiet = false } = {}) {
  if (!quiet) console.log(`$ wrangler ${args.join(" ").slice(0, 160)}`);
  return execFileSync("pnpm", ["wrangler", ...args], { encoding: "utf8", maxBuffer: 256 * 1024 * 1024, cwd: WEB, env: process.env, stdio: ["ignore", "pipe", "inherit"] });
}

/** `.env.local` 形式（KEY=VALUE）を読んで、環境変数に無いものだけ足したオブジェクトを返す。値は表示・ログしない。 */
export function loadEnvFile(file = path.join(WEB, ".env.local")) {
  const env = { ...process.env };
  if (fs.existsSync(file)) {
    for (const l of fs.readFileSync(file, "utf8").split("\n")) {
      const m = /^([A-Z_][A-Z0-9_]*)=(.*)$/.exec(l);
      if (m && env[m[1]] === undefined) env[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
    }
  }
  return env;
}
