/**
 * place_id ⇔ v1 の識別子の変換（`lib/cube` 内の共有。DB を読まない純関数）。
 * place_id の分解は `lib/registry/parse-id.ts` の `parseId()` を唯一の口にする
 * （ADR-0004 規約1。ns と key の区切りは `.`）。
 */
import { buildPlaceId, parseId } from "@/lib/registry/parse-id";

const GRID_KEY_RE = /^(\d+)_(\d+)$/;
const WATERSHED_NS = "nlni";

/** `common:place:grid01.3520_13900` → `{ mlat: 3520, mlon: 13900 }`。形式違いは null。 */
export function gridCellOfPlaceId(placeId: string): { mlat: number; mlon: number } | null {
  const p = parseId(placeId);
  if (!p || p.scope !== "common" || p.kind !== "grid01") return null;
  const m = GRID_KEY_RE.exec(p.key);
  return m ? { mlat: Number(m[1]), mlon: Number(m[2]) } : null;
}

/** `common:place:watershed.nlni.<id>` → `<id>`（v1 の `watershed_id`）。形式違いは null。 */
export function watershedIdOfPlaceId(placeId: string): string | null {
  const p = parseId(placeId);
  return p && p.scope === "common" && p.kind === "watershed" && p.ns === WATERSHED_NS ? p.key : null;
}

export function placeIdOfWatershedId(watershedId: string): string {
  return buildPlaceId("common", "watershed", WATERSHED_NS, watershedId);
}
