/**
 * `<scope>:<entity>:<local>` を分解する唯一の口（ADR-0004 規約1。Python 側の
 * `scripts/registry/common.py` の `parse_id()` と同じ規則。DB を読まない純関数）。
 *
 * - scope・entity は最初の2つの `:` で切る。
 * - place の local は `<kind>.<ns>.<key>`（`PLACE_KINDS_WITHOUT_NAMESPACE` の kind は
 *   `<kind>.<key>`）。ns と key は**最初の `.`** で切る（key は `.` を含みうるので
 *   「最後の `.`」で切ってはいけない。ns は `.` と `:` を含まない）。
 * - place 以外は local を `<ns>.<key>` とみなして最初の `.` で切る（`.` が無ければ ns=null）。
 *
 * 形が崩れていれば null（黙って誤分割しない）。ID の中身を `startsWith`・正規表現・
 * `split(".")` で直接読まず、必ずこれを通す（`parse-id.test.ts` が散在を検査する）。
 */

/** ns を持たない place_kind（Python の `PLACE_KINDS_WITHOUT_NAMESPACE` と同じ集合）。 */
export const PLACE_KINDS_WITHOUT_NAMESPACE: ReadonlySet<string> = new Set(["grid01"]);

const NAMESPACE_RE = /^[a-z0-9_-]+$/;

export interface ParsedId {
  scope: string;
  entity: string;
  local: string;
  /** place のときだけ。 */
  kind: string | null;
  ns: string | null;
  key: string;
}

export function parseId(id: string): ParsedId | null {
  const i1 = id.indexOf(":");
  if (i1 <= 0) return null;
  const i2 = id.indexOf(":", i1 + 1);
  if (i2 <= i1 + 1) return null;
  const scope = id.slice(0, i1);
  const entity = id.slice(i1 + 1, i2);
  const local = id.slice(i2 + 1);
  if (!local) return null;
  if (entity === "place") {
    const d1 = local.indexOf(".");
    if (d1 <= 0 || d1 === local.length - 1) return null;
    const kind = local.slice(0, d1);
    const tail = local.slice(d1 + 1);
    if (PLACE_KINDS_WITHOUT_NAMESPACE.has(kind)) return { scope, entity, local, kind, ns: null, key: tail };
    const d2 = tail.indexOf(".");
    if (d2 <= 0 || d2 === tail.length - 1) return null;
    const ns = tail.slice(0, d2);
    if (!NAMESPACE_RE.test(ns)) return null;
    return { scope, entity, local, kind, ns, key: tail.slice(d2 + 1) };
  }
  const d = local.indexOf(".");
  if (d < 0) return { scope, entity, local, kind: null, ns: null, key: local };
  return { scope, entity, local, kind: null, ns: local.slice(0, d), key: local.slice(d + 1) };
}

/** place の `<scope>:place:<kind>.<ns>.<key>` を組み立てる（ns を持たない kind は ns=null）。 */
export function buildPlaceId(scope: string, kind: string, ns: string | null, key: string): string {
  return ns ? `${scope}:place:${kind}.${ns}.${key}` : `${scope}:place:${kind}.${key}`;
}
