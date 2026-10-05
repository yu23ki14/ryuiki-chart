/**
 * place_id ⇔ v1 の識別子の変換（`lib/cube` 内の共有。DB を読まない純関数）。
 */

const GRID_RE = /^common:place:grid01\.(\d+)_(\d+)$/;
const WATERSHED_PREFIX = "common:place:watershed.nlni-";

/** `common:place:grid01.3520_13900` → `{ mlat: 3520, mlon: 13900 }`。形式違いは null。 */
export function gridCellOfPlaceId(placeId: string): { mlat: number; mlon: number } | null {
  const m = GRID_RE.exec(placeId);
  return m ? { mlat: Number(m[1]), mlon: Number(m[2]) } : null;
}

/** `common:place:watershed.nlni-<id>` → `<id>`（v1 の `watershed_id`）。形式違いは null。 */
export function watershedIdOfPlaceId(placeId: string): string | null {
  return placeId.startsWith(WATERSHED_PREFIX) && placeId.length > WATERSHED_PREFIX.length
    ? placeId.slice(WATERSHED_PREFIX.length)
    : null;
}

export function placeIdOfWatershedId(watershedId: string): string {
  return WATERSHED_PREFIX + watershedId;
}
