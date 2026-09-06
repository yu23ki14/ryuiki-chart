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
const FILES = [
  { src: "nlni_w05_rivers.geojson", dst: "rivers.geojson" },
  { src: "nlni_w12_watersheds.geojson", dst: "watersheds.geojson" },
  // 水源マップ（docs/WATER_SOURCE_MAP.md）。町丁目ポリゴンに水源比率を焼き込んだもの。
  // ブラウザが直接取る（/water は D1 を読まない）。作るのは scripts/build-water-geo.mjs。
  { src: "water_zones.geojson", dst: "water_zones.geojson" },
];

fs.mkdirSync(DST, { recursive: true });
// 名前を変えたときに古いものが残ってデプロイに乗り続けないように、知らないファイルは消す
for (const name of fs.readdirSync(DST)) {
  if (!FILES.some((f) => f.dst === name)) {
    fs.rmSync(path.join(DST, name));
    console.log(`removed ${name}`);
  }
}
let missing = 0;
for (const { src: f, dst: outName } of FILES) {
  const from = path.join(SRC, f);
  const to = path.join(DST, outName);
  const src = fs.existsSync(from) ? fs.statSync(from) : null;
  const dst = fs.existsSync(to) ? fs.statSync(to) : null;

  if (!src) {
    if (dst) {
      console.warn(`! ${f}: ${SRC} に無いので public/geo にあるものを使う`);
    } else {
      console.error(`✗ ${f} が ${SRC} にも public/geo にも無い。scripts/c31_nlni_w05.py などで再取得する。`);
      missing++;
    }
    continue;
  }
  // 出力は入力とサイズが違う（詰めるため）ので、更新の判定は mtime だけで見る
  if (dst && dst.mtimeMs >= src.mtimeMs) {
    console.log(`= ${outName} (最新)`);
    continue;
  }
  fs.writeFileSync(to, JSON.stringify(JSON.parse(fs.readFileSync(from, "utf8"))));
  const after = fs.statSync(to).size;
  console.log(`built ${f} → ${outName} ${(src.size / 1e6).toFixed(1)}MB → ${(after / 1e6).toFixed(1)}MB`);
}
if (missing) process.exit(1);
