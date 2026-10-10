/**
 * registry/place/zone.yaml（zone v2。docs/plans/AMAMI_STEP0.md §1.3・ADR-0031）の読み出し。
 *
 * 構造: definition_version（整数）/ note_ja / terrain / rule / zones（5件）。
 * `build-registry-ts.mjs` が呼び、`ZONE_INFO`（zone/label/cond）を作る。
 * 検査の正は `scripts/registry/zone_rule.py`（`load_zone_definition`）。ここは画面に要る最小限
 * （名称・短い条件文・版・注記の有無と zone の重複）だけを見る。判定規則の数値（terrain・rule）は
 * Python 側が正で、ここでは読まない。
 *
 * YAML のパースは呼び出し側（js-yaml）で済ませたオブジェクトを受け取る。ファイルを読まない純関数に
 * しておくと、新構造の小さなフィクスチャでテストできる。
 */

/** zone.yaml をパース済みのオブジェクトから { version, note, zoneInfo } を作る。形が違えば例外を投げる。 */
export function readZoneDefinition(doc, label = "registry/place/zone.yaml") {
  if (doc === null || typeof doc !== "object" || Array.isArray(doc)) {
    throw new Error(`${label} がマッピングになっていない（v2 は definition_version / zones を持つ。旧形式のリストではない）`);
  }
  if (!Number.isInteger(doc.definition_version)) {
    throw new Error(`${label} の definition_version が整数でない: ${JSON.stringify(doc.definition_version)}`);
  }
  if (typeof doc.note_ja !== "string" || !doc.note_ja.trim()) {
    throw new Error(`${label} に note_ja が無い`);
  }
  if (!Array.isArray(doc.zones) || doc.zones.length === 0) {
    throw new Error(`${label} の zones が空、または配列でない`);
  }
  const seen = new Set();
  const zoneInfo = [];
  for (const r of doc.zones) {
    if (!Number.isInteger(r?.zone)) throw new Error(`${label} の zones に整数の zone が無い項目がある`);
    if (seen.has(r.zone)) throw new Error(`${label} の zone が重複している: ${r.zone}`);
    seen.add(r.zone);
    if (!r.name_ja) throw new Error(`${label} の zone=${r.zone} に name_ja が無い`);
    if (!r.ui_condition_ja) throw new Error(`${label} の zone=${r.zone} に ui_condition_ja が無い`);
    zoneInfo.push({ zone: r.zone, label: r.name_ja, cond: r.ui_condition_ja });
  }
  zoneInfo.sort((a, b) => a.zone - b.zone);
  return { version: doc.definition_version, note: doc.note_ja.trim(), zoneInfo };
}
