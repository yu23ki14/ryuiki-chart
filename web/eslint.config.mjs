import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // 生成物。手で直さないので lint もしない
    "worker-configuration.d.ts",
    ".open-next/**",
    "dist/**",
    // vendor 生成物（`prepare:maplibre` が node_modules からコピーする。web/.gitignore 済み）。
    // 手で直せない・直さないコードなので lint 対象から外す（docs/plans/PHASE_B_INTAKE.md #14）
    "public/maplibre/**",
  ]),
]);

export default eslintConfig;
