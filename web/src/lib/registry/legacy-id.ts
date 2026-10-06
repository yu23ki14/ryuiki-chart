/**
 * 旧 ID の受理（ADR-0004 規約2、Issue #39 Phase C、docs/plans/ISSUE39_PHASE_C.md §2.7）。
 *
 * place の ns と key の区切りが `-` から `.` に変わったため、旧 ID（例
 * `jp-14:place:site.jma-jma_0387`）を含む既存のリンクが壊れないよう、旧 ID を受けたら
 * 新 ID に解決する。入口はこの1か所。DB は読まない（`generated-id-map.ts` は
 * `registry/id_map/place.csv` 由来の生成物）。
 *
 * 適用の約束:
 * - 画面: サーバ側で新 ID の URL へ 308 リダイレクトする。
 * - API・AI ツール: 新 ID で処理し、応答に `resolvedFrom: <旧 ID>` を付ける。
 * - どちらでも解決しない ID は従来どおり not found。
 * - AI のディープリンクは新 ID で生成する（旧 ID は生成しない）。
 * - 旧 ID の受理は恒久的に残す（撤去時期は決めない）。
 */
import { LEGACY_PLACE_ID_MAP } from "./generated-id-map";

/** 旧 ID なら新 ID を返す。新 ID（または未知の ID）は null（= 解決不要・解決不能）。 */
export function legacyPlaceIdToCurrent(id: string): string | null {
  return Object.prototype.hasOwnProperty.call(LEGACY_PLACE_ID_MAP, id) ? LEGACY_PLACE_ID_MAP[id] : null;
}

export interface ResolvedPlaceId {
  /** 処理に使う ID（新 ID）。 */
  id: string;
  /** 旧 ID で受けたときだけ、その旧 ID。 */
  resolvedFrom?: string;
}

/** 新 ID はそのまま通し、旧 ID は新 ID に解決する。未知の ID もそのまま返す（not found は呼び出し側）。 */
export function resolveLegacyId(id: string): ResolvedPlaceId {
  const current = legacyPlaceIdToCurrent(id);
  return current === null ? { id } : { id: current, resolvedFrom: id };
}
