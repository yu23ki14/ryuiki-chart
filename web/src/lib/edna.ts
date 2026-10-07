/**
 * 神奈川県 eDNA（`edna_sites`・`edna_reads`。D1 の台帳表）を引く共通の実装。
 * MCP の `get_edna`（`lib/mcp/tools.ts`）と AI の `get_edna`（`lib/ai/tools.ts`）が同じ関数を呼ぶ。
 *
 * - 検出も不検出も返す（`detected_only` で検出だけに絞れる）。リード数は個体数ではない。
 * - 地点の座標は推定位置で誤差つき（coord_source・coordinate_uncertainty_m を行に載せる）。
 * - 絞り込みの文字列は LIKE の部分一致（D1 は LIKE のパターンが 50 バイトまで）。ID 一覧は取らない
 *   ので `json_each` は要らず、バインドは常に数個。
 * - 注意書き（リード数・推定座標・年度差・不検出の読み方）は registry の caveat を facet で引く。
 *   ここには文字列を持たない。
 */
import { z } from "zod";
import type { CubeDb, SqlParam } from "@/lib/cube/db";
import { idText, likeParam, likeText } from "@/lib/query-params";

export const EDNA_SOURCE_ID = "kanagawa_edna";
export const EDNA_MAX_ROWS = 500;
const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "YYYY-MM-DD");

/** MCP・AI 共通の入力（z.tuple は使わない。Workers AI が draft 2020-12 で検証して 400 になる）。 */
export const ednaInputSchema = z.object({
  mode: z
    .enum(["records", "by_site", "by_taxon"])
    .optional()
    .describe(
      "records=採水×分類群の明細（既定）、by_site=地点×採水ごとの要約（検出した分類群数・リード数合計）、" +
        "by_taxon=分類群ごとの要約（調べた回数 n_events と検出した回数 n_detected_events）",
    ),
  site_key: idText("地点キー（<ファイル名>:<地点ID>）。完全一致").optional(),
  area: likeText("水系・支川・市町村の部分一致（例: 相模川、厚木市）").optional(),
  taxon_id: idText("分類群の taxon_id（例: common:taxon:inat.122882）。完全一致").optional(),
  species: likeText("学名・和名・採用名の部分一致（例: ニホンウナギ）").optional(),
  from: isoDate.optional().describe("採水日の下限（YYYY-MM-DD）"),
  to: isoDate.optional().describe("採水日の上限（YYYY-MM-DD、含む）"),
  detected_only: z.boolean().optional().describe("true なら検出（リード数>0）だけ。既定 false で不検出（リード数 0）も返す"),
  limit: z.number().int().min(1).max(EDNA_MAX_ROWS).optional().describe(`返す行数の上限（既定 100、最大 ${EDNA_MAX_ROWS}）`),
  offset: z.number().int().min(0).optional().describe("読み飛ばす行数（ページング。結果が truncated のとき offset を進めて続きを取る。既定 0）"),
});
export type EdnaInput = z.infer<typeof ednaInputSchema>;

export const EDNA_DESCRIPTION =
  "神奈川県の環境DNA（eDNA、採水による検出。source_id=kanagawa_edna）の明細を、不検出（リード数 0）も含めて取る。" +
  "地点（site_key／水系・支川・市町村）・種（taxon_id／学名・和名）・採水日で絞り、mode で明細・地点要約・分類群要約を選ぶ。" +
  "eDNA は目視の観察とは性質が違うので、出現記録（get_occurrences）と比べるときは出典で分ける。";

export interface EdnaResult {
  mode: "records" | "by_site" | "by_taxon";
  /** 最大 limit+1 行（呼び出し側が `cap` で切って truncated を決める。他のツールと同じ流儀）。 */
  rows: Record<string, string | number | null>[];
  limit: number;
  offset: number;
}

const SITE_COLUMNS = `s.site_key AS site_key, s.fiscal_year AS fiscal_year, s.dataset_file AS dataset_file, s.program AS program, s.assay AS assay,
       s.water_system_ja AS water_system, s.tributary_ja AS tributary, s.municipality_ja AS municipality,
       s.lat AS lat, s.lon AS lon, s.coordinate_uncertainty_m AS coordinate_uncertainty_m, s.coord_source AS coord_source,
       s.collected_on AS collected_on`;

function where(a: EdnaInput): { sql: string; params: SqlParam[] } {
  const conds: string[] = [];
  const params: SqlParam[] = [];
  if (a.site_key) {
    conds.push("s.site_key = ?");
    params.push(a.site_key);
  }
  if (a.area) {
    conds.push("(s.water_system_ja LIKE ? ESCAPE '\\' OR s.tributary_ja LIKE ? ESCAPE '\\' OR s.municipality_ja LIKE ? ESCAPE '\\')");
    const p = likeParam(a.area);
    params.push(p, p, p);
  }
  if (a.taxon_id) {
    conds.push("r.taxon_id = ?");
    params.push(a.taxon_id);
  }
  if (a.species) {
    conds.push("(t.scientific_name LIKE ? ESCAPE '\\' OR t.vernacular_name_ja LIKE ? ESCAPE '\\' OR r.name_adopted LIKE ? ESCAPE '\\')");
    const p = likeParam(a.species);
    params.push(p, p, p);
  }
  if (a.from) {
    conds.push("s.collected_on >= ?");
    params.push(a.from);
  }
  if (a.to) {
    conds.push("s.collected_on <= ?");
    params.push(a.to);
  }
  if (a.detected_only) conds.push("r.is_detected = 1");
  return { sql: conds.length ? `WHERE ${conds.join(" AND ")}` : "", params };
}

const FROM = `FROM edna_reads r
     JOIN edna_sites s ON s.site_key = r.site_key
     LEFT JOIN taxon t ON t.taxon_id = r.taxon_id`;

/** 分類群の単位。taxon が解決できない行（taxon_id NULL）は name_key で分ける（1つにまとめない）。 */
const TAXON_KEY = "COALESCE(r.taxon_id, r.name_key)";

export async function queryEdna(db: CubeDb, a: EdnaInput): Promise<EdnaResult> {
  const mode = a.mode ?? "records";
  const limit = a.limit ?? 100;
  const offset = a.offset ?? 0;
  const w = where(a);
  let sql: string;
  if (mode === "records") {
    sql = `SELECT ${SITE_COLUMNS},
       r.taxon_id AS taxon_id, t.scientific_name AS scientific_name, t.vernacular_name_ja AS vernacular_name_ja, t.rank AS taxon_rank,
       r.name_raw AS name_raw, r.name_adopted AS name_adopted, r.name_note AS name_note, r.genus_ja AS genus_ja,
       r.reliability AS reliability, r.pident_qcov AS pident_qcov,
       r.reads AS reads, r.is_detected AS is_detected, r.read_id AS read_id
     ${FROM} ${w.sql}
     ORDER BY s.collected_on, s.site_key, r.read_id LIMIT ? OFFSET ?`;
  } else if (mode === "by_site") {
    // 採水イベント = 地点（site_key）× 採水日。同じイベントの同じ分類群の複数行は1つにまとめ、どれか1行が検出なら検出。
    sql = `WITH ev AS (
       SELECT r.site_key AS site_key, ${TAXON_KEY} AS taxon_key, MAX(r.is_detected) AS detected, SUM(r.reads) AS reads
       ${FROM} ${w.sql}
       GROUP BY r.site_key, ${TAXON_KEY})
     SELECT ${SITE_COLUMNS},
       COUNT(*) AS n_taxa_tested, SUM(ev.detected) AS n_taxa_detected, SUM(ev.reads) AS reads_total
     FROM ev JOIN edna_sites s ON s.site_key = ev.site_key
     GROUP BY s.site_key
     ORDER BY s.collected_on, s.site_key LIMIT ? OFFSET ?`;
  } else {
    sql = `WITH ev AS (
       SELECT ${TAXON_KEY} AS taxon_key, MAX(r.taxon_id) AS taxon_id, r.site_key AS site_key, s.collected_on AS collected_on,
              MAX(r.is_detected) AS detected, SUM(r.reads) AS reads,
              MAX(t.scientific_name) AS scientific_name, MAX(t.vernacular_name_ja) AS vernacular_name_ja, MAX(r.name_adopted) AS name_adopted
       ${FROM} ${w.sql}
       GROUP BY ${TAXON_KEY}, r.site_key, s.collected_on)
     SELECT taxon_key, MAX(taxon_id) AS taxon_id, MAX(scientific_name) AS scientific_name, MAX(vernacular_name_ja) AS vernacular_name_ja,
       MAX(name_adopted) AS name_adopted,
       COUNT(*) AS n_events, SUM(detected) AS n_detected_events,
       COUNT(DISTINCT site_key) AS n_sites, COUNT(DISTINCT CASE WHEN detected = 1 THEN site_key END) AS n_sites_detected,
       SUM(reads) AS reads_total
     FROM ev
     GROUP BY taxon_key
     ORDER BY n_detected_events DESC, taxon_key LIMIT ? OFFSET ?`;
  }
  const rows = await db.all(sql, [...w.params, limit + 1, offset]);
  return { mode, rows, limit, offset };
}
