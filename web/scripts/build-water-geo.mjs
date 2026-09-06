#!/usr/bin/env node
/**
 * 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）の表示用 GeoJSON を作る。
 *
 *   node scripts/build-water-geo.mjs
 *
 * 入力:
 *   data/processed/estat_shozaiki_kanagawa.geojson  町丁目ポリゴン（c90_estat_shozaiki.py）
 *   data/db/ryuiki.sqlite の water_* テーブル       水源比率（scripts/m06_water.py）
 * 出力:
 *   data/processed/water_zones.geojson
 *
 * 画面はこのファイルだけを読み、D1 を触らない（設計図の「サーバーコストゼロ」）。
 * そのため水源カードに出す内容はすべてここで属性に焼き込む。
 *
 * 属性を s1/p1/s2/p2… と平たく持つのは MapLibre の都合。塗り分けは ["get","s1"] の
 * match 式で書くので、配列やオブジェクトのままだとスタイル式から引けない。
 * 上位 3 水源まで出し、残りは other にまとめる（設計図 §7 のリスク欄）。
 *
 * 割り付いていない町丁目は s1 を入れない。0 や「その他」で埋めない（§6-3）。
 * 画面はプロパティが無いことをもって「不明」と出す。
 *
 * ■ 比率不明（水源の顔ぶれだけ分かっている町丁目）
 * 資料が「この町丁目にはこの浄水場とこの浄水場の水が入る」とまでしか言っておらず、
 * 混合比が公表されていない配水系統がある（神奈川県営水道の相模原・平塚・厚木など）。
 * この町丁目は `water_zone_source_share.share` が NULL・`basis` が `unknown` で入る。
 * 平均や按分で埋めない（§6-3）ので、ここでは:
 *
 *   - `p1`/`p2`/`p3`（比率）を**入れない**。0 は入れない（0% と「不明」は別物）。
 *   - 代わりに `mixed: 1` を入れる。画面はこれを見てストライプで塗り、
 *     水源カードでは帯と % を出さずに「混合比は公表されていません」と書く。
 *   - `s1`/`s2`/`s3`（id）と `s1n`… は従来どおり入れるが、**並び順は source_id 順**。
 *     比率が無いので大小を付けない（先頭が「いちばん多い水源」ではない）。
 *   - `other`（4 水源目以降のまとめ）は**出さない**。比率の残余なので比率抜きには計算できず、
 *     0 や 1/N で埋めるのは按分と同じことになる。代わりに TOP_N に載らなかった水源が
 *     あるときだけ**その件数**を `other_n` に入れる（画面は「ほか N 水源」とだけ出す）。
 *     実データでは 2 水源の組み合わせしか出ていないので、いまのところ `other_n` は付かない。
 *
 * 根拠資料（water_zone_assignment → water_source_doc）も焼き込む。設計図 CP1 の
 * 「全割付に根拠資料が紐づいている」を画面で確かめられるようにするため。
 * ただし資料タイトル・URL・note は町丁目ごとに同じ文字列が何千回も出るので、
 * feature に直接埋めると数MB 増える。FeatureCollection の直下に辞書を置き、
 * feature には ID だけを入れる:
 *
 *   fc.docs  = { "<doc_id>": { title, url } }   → properties.doc_id
 *   fc.notes = { "<note_id>": "<note_ja>" }     → properties.note_id
 *
 * 町丁目の人口（e-Stat 2020年国勢調査）も `pop` として焼き込む。進み具合を「町丁目の数」ではなく
 * 「何人分の水源が分かっているか」で出すため。整数 1 個なので 5,089 件でも数十 KB しか増えない。
 *
 * note_id は note_ja の出現順に振る連番（実体を持つのは辞書だけ）。
 * note_ja は長いので NOTE_MAX 文字で切り、切ったら「…」を付ける。
 * 1 町丁目に複数の割付があるときは share が最大のものを採る。
 */
import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "..", "..");
const PROC = process.env.RYUIKI_PROCESSED_DIR ?? path.join(REPO, "data", "processed");
const DB_DIR = process.env.RYUIKI_DB_DIR ?? path.join(REPO, "data", "db");
const IN = path.join(PROC, "estat_shozaiki_kanagawa.geojson");
const OUT = path.join(PROC, "water_zones.geojson");

/** 上位いくつまで属性に出すか。これを増やすとファイルが太る。 */
const TOP_N = 3;

/** note_ja をここで切る。辞書に入れるので件数ではなく 1 本あたりの長さが効く。 */
const NOTE_MAX = 120;

if (!fs.existsSync(IN)) {
  console.error(
    `✗ ${IN} が無い。先に \`.venv/bin/python scripts/c90_estat_shozaiki.py\` を実行する。`,
  );
  process.exit(1);
}

const db = new Database(path.join(DB_DIR, "ryuiki.sqlite"), { readonly: true });
const hasTable = (n) =>
  db.prepare("SELECT count(*) n FROM sqlite_master WHERE type='table' AND name=?").get(n).n > 0;

/**
 * key_code -> [{source_id, name, type, share, confidence, basis, as_of}]
 * share 降順。share が NULL（比率非公表）の町丁目は SQLite で NULL が末尾に来るので
 * 実質 source_id 順に並ぶ。町丁目内で NULL と非 NULL が混ざることは無い（m06_water.py）。
 */
const byZone = new Map();
if (hasTable("water_zone_source_share") && hasTable("water_source")) {
  const rows = db
    .prepare(
      `SELECT z.key_code, z.source_id, z.share, z.confidence, z.basis, z.as_of,
              s.name AS source_name, s.type AS source_type, s.river_name_ja
         FROM water_zone_source_share z
         LEFT JOIN water_source s ON s.source_id = z.source_id
        ORDER BY z.key_code, z.share DESC, z.source_id`,
    )
    .all();
  for (const r of rows) {
    if (!byZone.has(r.key_code)) byZone.set(r.key_code, []);
    byZone.get(r.key_code).push(r);
  }
}

/**
 * key_code -> { doc_id, note }（share が最大の割付 1 件）。
 * 資料そのものは docs 辞書に 1 回だけ持つ。
 */
const docs = {};
const zoneDoc = new Map();
if (hasTable("water_zone_assignment") && hasTable("water_source_doc")) {
  const rows = db
    .prepare(
      `SELECT a.key_code, a.share, a.note_ja, d.doc_id, d.title, d.url
         FROM water_zone_assignment a
         LEFT JOIN water_source_doc d ON d.doc_id = a.source_doc_id
        ORDER BY a.key_code, a.share DESC, a.assignment_id`,
    )
    .all();
  for (const r of rows) {
    if (zoneDoc.has(r.key_code)) continue; // 先頭 = share 最大
    const note = truncate(r.note_ja, NOTE_MAX);
    if (!r.doc_id && !note) continue;
    if (r.doc_id && !docs[r.doc_id]) docs[r.doc_id] = { title: r.title ?? r.doc_id, url: r.url ?? null };
    zoneDoc.set(r.key_code, { doc_id: r.doc_id ?? null, note });
  }
}

/** note_ja の実体は辞書に 1 本だけ置き、feature は連番の ID を持つ。 */
const notes = {};
const noteId = new Map();
function internNote(note) {
  if (!note) return null;
  let id = noteId.get(note);
  if (id === undefined) {
    id = `n${noteId.size + 1}`;
    noteId.set(note, id);
    notes[id] = note;
  }
  return id;
}

function truncate(s, max) {
  if (!s) return null;
  const t = String(s).trim();
  if (!t) return null;
  return t.length > max ? `${t.slice(0, max)}…` : t;
}

/** key_code -> 人口。e-Stat の属性は water_zone に入っている（m06_water.py）。 */
const popByZone = new Map();
if (hasTable("water_zone")) {
  for (const r of db.prepare("SELECT key_code, population FROM water_zone").all()) {
    if (r.population != null) popByZone.set(r.key_code, r.population);
  }
}

db.close();

const fc = JSON.parse(fs.readFileSync(IN, "utf8"));
let assigned = 0;
/** うち「顔ぶれは分かるが混合比が非公表」の町丁目（mixed=1 を入れたもの）。 */
let mixedZones = 0;
for (const f of fc.features) {
  const p = f.properties;
  const pop = popByZone.get(p.key_code);
  if (pop != null) p.pop = pop;
  // 根拠資料は比率が解けたかどうかに関わらず、割付があれば付ける
  // （上流が未入力で比率が出ない町丁目でも、何を見て割り付けたかは示せる）。
  const doc = zoneDoc.get(p.key_code);
  if (doc) {
    if (doc.doc_id) p.doc_id = doc.doc_id;
    const nid = internNote(doc.note);
    if (nid) p.note_id = nid;
  }
  const list = byZone.get(p.key_code);
  if (!list || list.length === 0) continue; // 未割付。属性を足さない = 「不明」
  assigned++;
  // 比率が 1 つでも NULL なら、その町丁目は「顔ぶれだけ分かっている」扱い（冒頭コメント）。
  // 片方だけ % を出すことはしない。
  const mixed = list.some((r) => r.share == null);
  if (mixed) mixedZones++;
  const top = list.slice(0, TOP_N);
  const rest = list.slice(TOP_N).reduce((a, r) => a + (r.share ?? 0), 0);
  top.forEach((r, i) => {
    const n = i + 1;
    p[`s${n}`] = r.source_id;
    p[`s${n}n`] = r.source_name ?? r.source_id;
    p[`s${n}t`] = r.source_type ?? null;
    if (!mixed) p[`p${n}`] = Math.round((r.share ?? 0) * 1000) / 1000;
    if (r.river_name_ja) p[`s${n}r`] = r.river_name_ja;
  });
  if (mixed) {
    p.mixed = 1;
    // 比率が無いので other（残余）は計算できない。件数だけ渡す。
    if (list.length > TOP_N) p.other_n = list.length - TOP_N;
  } else if (rest > 0.0005) {
    p.other = Math.round(rest * 1000) / 1000;
  }
  // 経路のいちばん弱い値。UI はこれで「概算」ラベルと確信度を出す。
  p.conf = weakest(["low", "medium", "high"], list.map((r) => r.confidence));
  p.basis = weakest(
    ["unknown", "nominal", "estimated", "measured"],
    list.map((r) => r.basis),
    "nominal",
  );
  p.as_of = list[0].as_of;
}

/**
 * 語彙のいちばん弱い値。語彙外・空が混ざったら fallback（既定は先頭 = いちばん弱い値）。
 * basis は `unknown`（比率非公表）を足したので、語彙外のときに `unknown` へ落ちないよう
 * 呼び出し側が fallback に `nominal` を渡す。
 */
function weakest(order, values, fallback = order[0]) {
  let best = null;
  for (const v of values) {
    if (!order.includes(v)) return fallback;
    if (best === null || order.indexOf(v) < order.indexOf(best)) best = v;
  }
  return best ?? fallback;
}

fc.name = "water_zones";
// 資料と note は feature に埋めず、ここに 1 本ずつ置く（冒頭コメント）。
fc.docs = docs;
fc.notes = notes;
fc.note =
  `町丁目 ${fc.features.length} 件のうち ${assigned} 件に水源を焼き込み済み` +
  `（うち ${mixedZones} 件は混合比が非公表で mixed=1・比率なし）。` +
  `属性の無い町丁目は未割付（不明）。`;
fs.writeFileSync(OUT, JSON.stringify(fc));
const mb = (fs.statSync(OUT).size / 1e6).toFixed(1);
console.log(
  `built water_zones.geojson  町丁目 ${fc.features.length} / 割付済み ${assigned} ` +
    `(${((assigned / fc.features.length) * 100).toFixed(1)}%)` +
    `  うち比率あり ${assigned - mixedZones} / 比率非公表 ${mixedZones}  ${mb} MB` +
    `  資料 ${Object.keys(docs).length} 件 / note ${Object.keys(notes).length} 種 ` +
    `（根拠付き ${zoneDoc.size} 町丁目）`,
);
if (assigned > 0 && zoneDoc.size < assigned) {
  console.warn(
    `! 根拠資料の無い割付が ${assigned - zoneDoc.size} 町丁目ある。` +
      "設計図 CP1 の完了条件は「全割付に根拠資料が紐づいている」。",
  );
}
if (fs.statSync(OUT).size > 20 * 1024 * 1024) {
  console.warn(
    "! 20MB を超えた。Cloudflare の静的アセットは 1 ファイル 25MiB まで。" +
      "docs/WATER_SOURCE_MAP.md §4 に従って PMTiles への切り替えを検討する。",
  );
}
