/**
 * MCP の `get_watersheds`（流域の属性と境界。問い合わせは `lib/watersheds.ts`）。
 * `tools.ts` が `MCP_TOOLS` に `getWatershedsTool()` を登録する。
 */
import { z } from "zod";
import { buildDataEnvelope } from "@/lib/cube";
import { caveatsForFacets, placeKind, sourceEditionOf } from "@/lib/cube/caveats";
import { pickDefined } from "@/lib/cube/sql";
import { OUTSIDE_WATERSHED_NOTE, watersheds, WATERSHED_GEOJSON_PATH, WATERSHED_ID_RULE, type GeoLoader } from "@/lib/watersheds";
import { REGION_NOTE, regionSchema } from "./region-schema";
import type { McpContext, McpTool } from "./tools";

const MAX_PLACE_IDS = 20;
const MAX_ROWS = 500;
const DEFAULT_LIMIT = 100;

const inputSchema = z.object({
  region: regionSchema,
  place_ids: z.array(z.string()).min(1).max(MAX_PLACE_IDS).optional().describe(`流域の place_id（最大 ${MAX_PLACE_IDS}。例: common:place:watershed.dem.amami-039）。省略は地域内の全流域`),
  include_geometry: z.boolean().optional().describe("true で各流域の境界ポリゴン（GeoJSON の geometry）を載せる。place_ids を指定したときだけ使える（既定 false）"),
  limit: z.number().int().min(1).max(MAX_ROWS).optional().describe(`返す行数の上限（既定 ${DEFAULT_LIMIT}、最大 ${MAX_ROWS}）`),
}).strict().refine((a) => !a.include_geometry || a.place_ids !== undefined, {
  path: ["include_geometry"],
  message: "include_geometry=true は place_ids（最大 20）を指定したときだけ使える。全面の境界は応答の geojson_url（GeoJSON ファイル）から取る",
});

export const WATERSHEDS_DESCRIPTION =
  "流域の属性と境界を取る（地図にする・流域を選ぶとき用）。行ごとに place_id・region・name・area_km2・unit_kind" +
  "（basin=河口の流域／coast_group=沿岸の小流域群／island=小島。奄美の DEM 流域だけ）・merged_share（面積のうち小さな斜面を併合した割合）・" +
  "own_drainage_km2（出口の自前の集水面積）・main_rivers（'|' 区切り）・outlet_lat/outlet_lon（河口。奄美だけ）・centroid_lat/centroid_lon・source_id を返す。" +
  "include_geometry=true で境界（GeoJSON の geometry）も返すが、place_ids を指定したときだけ使える（全面は大きいので、応答の geojson_url から取る）。" +
  "応答には全面の GeoJSON の公開 URL（geojson_url）と、その properties.watershed_id と place_id の対応規則（watershed_id_rule）が付く。" +
  "get_occurrences の placeId・watershed_years・get_records の watershed 列は、ここで得た place_id を使う。" +
  "注意: " + OUTSIDE_WATERSHED_NOTE +
  REGION_NOTE;

export function getWatershedsTool(loadGeo?: GeoLoader): McpTool {
  return {
    name: "get_watersheds",
    description: WATERSHEDS_DESCRIPTION,
    inputSchema,
    execute: async (args: never, ctx: McpContext) => {
      const a = args as z.infer<typeof inputSchema>;
      const limit = a.limit ?? DEFAULT_LIMIT;
      const r = await watersheds(
        await ctx.db(),
        { ...pickDefined({ region: a.region, placeIds: a.place_ids }), includeGeometry: a.include_geometry === true, limit },
        loadGeo,
      );
      const sourceIds = [...new Set(r.rows.map((x) => x.source_id).filter((x): x is string => x !== null))];
      return buildDataEnvelope(
        { ...a },
        {
          rows: r.rows,
          n_total: r.nTotal,
          ...(r.notFound.length ? { not_found: r.notFound } : {}),
          geojson_url: ctx.origin ? new URL(WATERSHED_GEOJSON_PATH, ctx.origin).toString() : WATERSHED_GEOJSON_PATH,
          watershed_id_rule: WATERSHED_ID_RULE,
        },
        sourceIds,
        { now: ctx.now, truncated: r.nTotal > r.rows.length, caveats: caveatsForFacets([placeKind("watershed"), ...sourceIds.map(sourceEditionOf)]) },
      );
    },
  };
}
