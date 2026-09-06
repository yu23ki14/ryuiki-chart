#!/usr/bin/env node
/**
 * MapLibre のワーカーを public/ に配置する。
 *
 * MapLibre はワーカーを `new URL('./maplibre-gl-worker.mjs', import.meta.url)` で解決するが、
 * Next.js（Turbopack）のチャンク URL からは解決できず 404 の HTML が返ってしまい、
 * 「Expected a JavaScript module script but the server responded with text/html」になって
 * GeoJSON のパースが永久に終わらない。素のファイルを public に置き、
 * setWorkerUrl() で明示的に指す。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "..", "node_modules", "maplibre-gl", "dist");
const DST = path.resolve(__dirname, "..", "public", "maplibre");

fs.mkdirSync(DST, { recursive: true });
const files = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];
for (const f of files) {
  const from = path.join(SRC, f);
  if (!fs.existsSync(from)) {
    console.error("見つかりません:", from);
    process.exit(1);
  }
  fs.copyFileSync(from, path.join(DST, f));
  console.log("copied", f, (fs.statSync(from).size / 1024).toFixed(0) + "KB");
}
