/**
 * `observation.ts`/`catalog.ts` が共有する SQL の断片（design §3.3「SQL の骨格」）。
 *
 * `IN (...)` を使わない方針: 意味のある集合（水域・ゾーン）は `place_source_ref`/`sites`/
 * `place_relation` との JOIN、呼び出し側が持つ任意の ID 一覧（地点 ID 配列等）は
 * `JOIN json_each(?)`（JSON 配列文字列を1パラメータで渡す）で表す。
 */
import { MAX_ID_LIST, type SqlParam } from "./db";
import { seriesKeySql, seriesKeyString, type SeriesKey } from "./series";

/** `observation_agg` のテーブルエイリアス。`assertD1Compatible` の ATTACH 時代の
 * 接頭辞検査（`c.`/`d.`）と字面が衝突しないよう、`c`/`d` 以外の文字を選ぶ。 */
export const OBS = "obs";

export type Scope =
  | { kind: "places"; placeIds: string[] }
  | { kind: "site"; siteId: string }
  | { kind: "water"; municipality: string }
  | { kind: "zone"; zone?: number }
  | { kind: "all_sites" };

export function jsonEachParam(values: readonly (string | number)[]): string {
  return JSON.stringify(values);
}

/** 系列の集合（`SeriesKey[]`）を `json_each(?)` で `SERIES_KEY_SQL` と等値 JOIN する断片。 */
export function seriesFilterSql(series: readonly SeriesKey[] | undefined, alias = OBS): { join: string; params: SqlParam[] } | undefined {
  if (!series || series.length === 0) return undefined;
  return {
    join: `JOIN json_each(?) sk ON sk.value = ${seriesKeySql(alias)}`,
    params: [jsonEachParam(series.map(seriesKeyString))],
  };
}

export interface ScopeSql {
  joins: string[];
  wheres: string[];
  params: SqlParam[];
  /** CellRow.siteId に使う SELECT 式（"NULL" または `<alias>.external_key`）。 */
  siteIdExpr: string;
}

/**
 * スコープを JOIN/WHERE に展開する（design §3.3）。
 *
 * `psr`（`place_source_ref`、`source_id='sites.site_id'`）は `all_sites` 以外は
 * INNER JOIN にする（design: 「psr は LEFT JOIN にしない」）。`all_sites` だけは
 * `sites` に無い地点（厚木の一部・地盤沈下観測点等）も含めるため psr を付けない。
 */
export function buildScopeSql(scope: Scope, alias = OBS): ScopeSql {
  const joins: string[] = [];
  const wheres: string[] = [];
  const params: SqlParam[] = [];
  let siteIdExpr = "NULL";

  switch (scope.kind) {
    case "places": {
      if (scope.placeIds.length > MAX_ID_LIST) {
        throw new Error(`buildScopeSql: places.placeIds が ${scope.placeIds.length} 件で上限 ${MAX_ID_LIST} を超えている`);
      }
      if (scope.placeIds.length === 0) {
        // 0件なら「常に偽」の WHERE にして0行を返す。
        wheres.push("1 = 0");
        break;
      }
      joins.push(`JOIN json_each(?) pid ON pid.value = ${alias}.place_id`);
      params.push(jsonEachParam(scope.placeIds));
      joins.push(`JOIN place_source_ref psr ON psr.place_id = ${alias}.place_id AND psr.source_id = 'sites.site_id'`);
      siteIdExpr = "psr.external_key";
      break;
    }
    case "site": {
      joins.push(`JOIN place_source_ref psr ON psr.place_id = ${alias}.place_id AND psr.source_id = 'sites.site_id'`);
      wheres.push("psr.external_key = ?");
      params.push(scope.siteId);
      siteIdExpr = "psr.external_key";
      break;
    }
    case "water": {
      joins.push(`JOIN place_source_ref psr ON psr.place_id = ${alias}.place_id AND psr.source_id = 'sites.site_id'`);
      joins.push(`JOIN sites s ON s.site_id = psr.external_key AND s.municipality = ?`);
      params.push(scope.municipality);
      siteIdExpr = "psr.external_key";
      break;
    }
    case "zone": {
      joins.push(`JOIN place_relation pr ON pr.child_id = ${alias}.place_id AND pr.relation = 'within'`);
      joins.push(`JOIN place_source_ref zref ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'`);
      joins.push(`JOIN place_source_ref psr ON psr.place_id = ${alias}.place_id AND psr.source_id = 'sites.site_id'`);
      if (scope.zone !== undefined) {
        wheres.push("CAST(zref.external_key AS INTEGER) = ?");
        params.push(scope.zone);
      }
      siteIdExpr = "psr.external_key";
      break;
    }
    case "all_sites": {
      // psr を付けない（design: sites に無い地点も含める）。
      break;
    }
  }

  // 「地点」スコープはすべて site の観測に絞る（流域・グリッドのセルは混ぜない）。
  wheres.push(`${alias}.place_kind = 'site'`);

  return { joins, wheres, params, siteIdExpr };
}

/** ゾーンの数値（`sites.zone` は "1".."5" の数字文字列）。 */
export function zoneExprSql(): string {
  return "CAST(zref.external_key AS INTEGER)";
}
