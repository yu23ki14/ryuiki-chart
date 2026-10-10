#!/usr/bin/env node
/**
 * 地図が使う GeoJSON を data/processed から public/geo に配置する。
 *
 * Workers にファイルシステムは無いので、GeoJSON は静的アセットとして配る。
 * ここに置いたものがビルドで .open-next/assets に入り、
 *   - 河川   : ブラウザが /geo/nlni_w05_rivers.geojson を直接取る（Worker を通さない）
 *   - 流域界 : src/lib/geo.ts が ASSETS バインディング経由で読み、D1 の集計を載せて返す
 * となる。public/maplibre と同じく生成物なので .gitignore 済み。
 *
 * data/processed が無くても、既に public/geo に置いてあれば通す。
 * （原本データを持たないマシンでコードだけ直してデプロイする場合のため）
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..", "..");
const SRC = process.env.RYUIKI_PROCESSED_DIR ?? path.join(REPO, "data", "processed");
const DST = path.resolve(__dirname, "..", "public", "geo");

/**
 * 画面で使う GeoJSON。ここに足したら src/lib/geo.ts か MapPage 側の参照も足すこと。
 *
 * 公開パスは原本のファイル名（国土数値情報のレイヤ番号入り）ではなく短い名前にする。
 * 出典は source_registry と /sources 側が持っているので、URL に持たせる必要が無い。
 *
 * 単純なコピーではなく JSON を読み直して詰めて書く。理由は 2 つ。
 *   1. ビルド時に壊れた GeoJSON を弾ける
 *   2. Cloudflare のアセットは**内容ハッシュで重複排除される**。2026-09-02 に watersheds の
 *      実体が壊れて 500 を返す状態になり、名前を変えて上げ直しても同じハッシュ＝同じ壊れた実体を
 *      指したままだった。バイト列が変われば別の実体になる。詰めた結果は入力が同じなら毎回同じ。
 */
//
// src が配列のものは、地域ごとのファイルを順に連結して 1 つの FeatureCollection にする（先頭が神奈川）。
// 奄美側が無ければ神奈川だけで通す。神奈川（先頭）の feature 数が減っていないことは書き出し時に検査する。
//
// 地域ファイルは「<基本名>.geojson（神奈川）」と「<基本名>_<slug>.geojson」（scripts/regions.py の slug。
// 例: _amami）。slug は英数字だけ許すので `_columns.csv` 等の別ファイルは拾わない。名前順で、基本名が先頭。
function regionalGeojson(base) {
  const re = new RegExp(`^${base}(_[a-z0-9]+)?\\.geojson$`);
  const names = fs.existsSync(SRC) ? fs.readdirSync(SRC).filter((n) => re.test(n)) : [];
  // 基本名（神奈川）を必ず先頭に。無くても先頭の名前は返す（無いことを下で検出する）
  return [`${base}.geojson`, ...names.filter((n) => n !== `${base}.geojson`).sort()];
}
const FILES = [
  { src: regionalGeojson("nlni_w05_rivers"), dst: "rivers.geojson" },
  { src: regionalGeojson("nlni_w12_watersheds"), dst: "watersheds.geojson" },
  // 水源マップ（docs/WATER_SOURCE_MAP.md）。町丁目ポリゴンに水源比率を焼き込んだもの。
  // ブラウザが直接取る（/water は D1 を読まない）。作るのは scripts/build-water-geo.mjs。
  { src: "water_zones.geojson", dst: "water_zones.geojson" },
];

// water_zones.geojson は原本から再生成できる生成物。data/processed にも public/geo にも無いときだけ
// build-water-geo.mjs で作る（ホストで `pnpm run dev` するとき・docker のどちらでも同じ挙動になる）。
if (
  !fs.existsSync(path.join(SRC, "water_zones.geojson")) &&
  !fs.existsSync(path.join(DST, "water_zones.geojson"))
) {
  console.log("▶ water_zones.geojson が無いので作る (build-water-geo.mjs)");
  const r = spawnSync(process.execPath, [path.join(__dirname, "build-water-geo.mjs")], { stdio: "inherit" });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

// 入力の集合のスタンプ。public/geo は知らないファイルを消す（デプロイに乗せない）ので、その外に置く。
const STAMP = path.resolve(__dirname, "..", "node_modules", ".cache", "ryuiki-geo-inputs.json");
function readStamps() {
  try {
    return JSON.parse(fs.readFileSync(STAMP, "utf8"));
  } catch {
    return {};
  }
}
function writeStamps(v) {
  fs.mkdirSync(path.dirname(STAMP), { recursive: true });
  fs.writeFileSync(STAMP, JSON.stringify(v));
}

fs.mkdirSync(DST, { recursive: true });
// 名前を変えたときに古いものが残ってデプロイに乗り続けないように、知らないファイルは消す
for (const name of fs.readdirSync(DST)) {
  if (!FILES.some((f) => f.dst === name)) {
    fs.rmSync(path.join(DST, name));
    console.log(`removed ${name}`);
  }
}
let missing = 0;
for (const { src: srcSpec, dst: outName } of FILES) {
  const names = Array.isArray(srcSpec) ? srcSpec : [srcSpec];
  const label = names[0];
  const froms = names.map((n) => path.join(SRC, n)).filter((p) => fs.existsSync(p));
  const to = path.join(DST, outName);
  const dst = fs.existsSync(to) ? fs.statSync(to) : null;

  // 先頭（神奈川）が無ければ入力なし扱い。奄美だけがあっても神奈川を欠いた配信にはしない。
  if (!fs.existsSync(path.join(SRC, names[0]))) {
    if (dst) {
      console.warn(`! ${label}: ${SRC} に無いので public/geo にあるものを使う`);
    } else {
      console.error(`✗ ${label} が ${SRC} にも public/geo にも無い。scripts/c31_nlni_w05.py などで再取得する。`);
      missing++;
    }
    continue;
  }
  const srcMtime = Math.max(...froms.map((p) => fs.statSync(p).mtimeMs));
  const srcSize = froms.reduce((a, p) => a + fs.statSync(p).size, 0);
  // 入力の集合（名前・サイズ・mtime）をスタンプに残し、変わったら（ファイルの追加・削除も）作り直す。
  // 最新 mtime だけだと、古い奄美ファイルを後から足した・消したときに気づけない。
  const inputsKey = JSON.stringify(froms.map((p) => [path.basename(p), fs.statSync(p).size, fs.statSync(p).mtimeMs]));
  const stamps = readStamps();
  // 出力は入力とサイズが違う（詰めるため）ので、更新の判定はスタンプと mtime で見る
  if (dst && dst.mtimeMs >= srcMtime && stamps[outName] === inputsKey) {
    console.log(`= ${outName} (最新)`);
    continue;
  }
  const parts = froms.map((p) => JSON.parse(fs.readFileSync(p, "utf8")));
  const merged = { ...parts[0], features: parts.flatMap((g) => g.features ?? []) };
  const base = (parts[0].features ?? []).length;
  if (base === 0 || merged.features.length < base) {
    console.error(`✗ ${outName}: feature 数が神奈川 (${base}) を下回る (${merged.features.length})`);
    process.exit(1);
  }
  fs.writeFileSync(to, JSON.stringify(merged));
  stamps[outName] = inputsKey;
  writeStamps(stamps);
  const after = fs.statSync(to).size;
  console.log(
    `built ${froms.length} file(s) → ${outName} features ${parts.map((g) => (g.features ?? []).length).join("+")}=${merged.features.length} ` +
      `${(srcSize / 1e6).toFixed(1)}MB → ${(after / 1e6).toFixed(1)}MB`,
  );
}
if (missing) process.exit(1);
