/**
 * place_id ⇔ v1 の識別子の変換（`lib/cube` 内の共有。DB を読まない純関数）。
 * place_id の分解は `lib/registry/parse-id.ts` の `parseId()` を唯一の口にする
 * （ADR-0004 規約1。ns と key の区切りは `.`）。
 */
import { buildPlaceId, parseId } from "@/lib/registry/parse-id";

const GRID_KEY_RE = /^(\d+)_(\d+)$/;
const WATERSHED_NS = "nlni";
/** 奄美の DEM 流域（Issue #94）。place は `watershed.dem.amami-NNN`、`watershed_id` は `dem-amami-NNN`。 */
const DEM_NS = "dem";
const DEM_ID_PREFIX = "dem-";

/** `common:place:grid01.3520_13900` → `{ mlat: 3520, mlon: 13900 }`。形式違いは null。 */
export function gridCellOfPlaceId(placeId: string): { mlat: number; mlon: number } | null {
  const p = parseId(placeId);
  if (!p || p.scope !== "common" || p.kind !== "grid01") return null;
  const m = GRID_KEY_RE.exec(p.key);
  return m ? { mlat: Number(m[1]), mlon: Number(m[2]) } : null;
}

/**
 * `common:place:watershed.nlni.<id>` → `<id>`、`common:place:watershed.dem.<key>` → `dem-<key>`
 * （`watershed_id`）。形式違いは null。`scripts/registry/common.py` と同じ入出力。
 */
export function watershedIdOfPlaceId(placeId: string): string | null {
  const p = parseId(placeId);
  if (!p || p.scope !== "common" || p.kind !== "watershed") return null;
  if (p.ns === WATERSHED_NS) return p.key;
  if (p.ns === DEM_NS) return `${DEM_ID_PREFIX}${p.key}`;
  return null;
}

export function placeIdOfWatershedId(watershedId: string): string {
  if (watershedId.startsWith(DEM_ID_PREFIX)) {
    return buildPlaceId("common", "watershed", DEM_NS, watershedId.slice(DEM_ID_PREFIX.length));
  }
  return buildPlaceId("common", "watershed", WATERSHED_NS, watershedId);
}
