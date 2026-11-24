/**
 * 同期の差分計算（純関数）。マニフェスト＝前回 Vectorize に入れた（入れたはずの）状態。
 * 設計: docs/plans/TATSUGO_KOHO_VECTOR.md §5.4・§5.5
 */

/** チャンク列 → 望ましい状態 Map<id, {id, article_id, chunk_sha}>。 */
export function desiredState(chunks) {
  const m = new Map();
  for (const c of chunks) m.set(c.id, { id: c.id, article_id: c.article_id, chunk_sha: c.chunk_sha });
  return m;
}

/**
 * upsert: 新しい ID と chunk_sha が変わった ID。
 * delete: マニフェストにあって望ましい状態に無い ID（記事が消えた・短くなって seq の余りが出た・対象外になった）。
 */
export function diffState(desired, manifest) {
  const upsert = [];
  const del = [];
  let unchanged = 0;
  for (const [id, d] of desired) {
    const old = manifest.get(id);
    if (!old || old.chunk_sha !== d.chunk_sha) upsert.push(id);
    else unchanged++;
  }
  for (const id of manifest.keys()) if (!desired.has(id)) del.push(id);
  const changedArticles = new Set([...upsert, ...del].map((id) => (desired.get(id) ?? manifest.get(id)).article_id));
  return { upsert, delete: del, unchanged, changedArticles: [...changedArticles].sort() };
}

/** 取り下げ: マニフェストから、指定の article_id（完全一致）または doc_id 接頭辞（`<doc_id>:`）に当たる ID を引く。 */
export function idsToWithdraw(manifest, { articleIds = [], docPrefixes = [] }) {
  const ids = new Set(articleIds);
  const out = [];
  for (const [id, e] of manifest) {
    if (ids.has(e.article_id) || docPrefixes.some((p) => e.article_id.startsWith(p.endsWith(":") ? p : `${p}:`))) out.push(id);
  }
  return out;
}

/**
 * 取り下げの結果を状態へ反映する（マニフェストから消す）。返り値は**キャッシュからも消してよい** chunk_sha:
 * 他の記事（残るマニフェストの行）が同じ chunk_sha を使っているものは含めない（同じ文面の記事は鍵が同じ）。
 */
export function applyWithdraw(manifest, ids) {
  const shas = new Set();
  for (const id of ids) {
    const e = manifest.get(id);
    if (e) shas.add(e.chunk_sha);
    manifest.delete(id);
  }
  for (const e of manifest.values()) shas.delete(e.chunk_sha);
  return shas;
}

export const toNdjson = (rows) => rows.map((r) => JSON.stringify(r)).join("\n") + "\n";

/** Vectorize の upsert 1 行。metadata の null は入れない。 */
export function vectorRow(chunk, values, model) {
  const metadata = { article_id: chunk.article_id, seq: chunk.seq, c0: chunk.c0, c1: chunk.c1, chunk_sha: chunk.chunk_sha, model };
  if (chunk.body_sha) metadata.body_sha = chunk.body_sha;
  for (const [k, v] of Object.entries(chunk.metadata)) if (v !== null && v !== undefined) metadata[k] = v;
  return { id: chunk.id, values: Array.from(values), metadata };
}
