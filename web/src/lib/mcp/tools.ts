/**
 * MCP の第1段 5 ツール（ADR-0014）。SDK 非依存（zod の入力スキーマ + execute）。
 *
 * ## 規則
 *
 * - 問い合わせは `@/lib/cube` の既存関数だけを呼ぶ（画面・AI と同じ層。MCP 専用の SQL は書かない）。
 *   ADR-0014「MCP で取れないものは画面にも出ていない」を、層2 の `serving_queries.yaml` と
 *   同じ関数を通すことで保つ。
 * - **任意 SQL・全表走査のツールは作らない**（ツール一覧と入力スキーマを `tools.test.ts` で固定）。
 * - 全ツールの応答は封筒（`cube-envelope@2`）。`excluded` は常に 0（ADR-0028。ライセンス・公開範囲で
 *   黙って減らさない）、`provenance` に `fetched_at`・`update_mode`・`age_days`、`cite_as`、注記を載せる。
 * - 利用者指定の `license_class`/`redistributable` 絞り込みは第1段では持たない（問い合わせ層が
 *   出典別の集計を持たず、持つには MCP 専用の SQL が要るため）。持つときも既定は絞らない（ADR-0028）。
 * - `z.tuple` を入力スキーマに使わない（Workers AI/JSON Schema の既知の罠）。
 */
import { z } from "zod";
import {
  buildDataEnvelope,
  OCCURRENCE_SOURCE_IDS,
  seriesSourceRefs,
  sourceFreshness,
  speciesCatalog,
  speciesMonths,
  speciesYears,
  timeseries,
  variableCatalog,
  watershedYears,
  waterBodies,
  MEASUREMENTS_DATASET,
  type CubeDb,
} from "@/lib/cube";
import { SOURCE_META } from "@/lib/registry/generated-source";
import { GENERATED_VARIABLES } from "@/lib/registry/generated";
import { VARIABLE_LABEL, ZONE_INFO } from "@/lib/registry/generated-client";
import { representativeSeries } from "@/lib/cube/series";
import { EDNA_DESCRIPTION, EDNA_SOURCE_ID, ednaCaveats, ednaInputSchema, queryEdna } from "@/lib/edna";
import { loadDatapackage } from "./datapackage";

export interface McpContext {
  db: () => Promise<CubeDb>;
  /** `dist/datapackage.json` の読み出し口（Workers は ASSETS、ローカルは public/）。テストで差し替える。 */
  datapackage?: () => Promise<unknown | null>;
  now?: Date;
}

export interface McpTool {
  name: string;
  description: string;
  inputSchema: z.ZodType;
  execute: (args: never, ctx: McpContext) => Promise<unknown>;
}

function defineTool<S extends z.ZodType>(t: {
  name: string;
  description: string;
  inputSchema: S;
  execute: (args: z.infer<S>, ctx: McpContext) => Promise<unknown>;
}): McpTool {
  return t; // execute の引数型は never を受け取る側（McpTool）に代入できる。as unknown で型を潰さない
}

/** 出典 1 件の行（describe_catalog の sources と search_registry の source で同じ形）。 */
function sourceRow(m: (typeof SOURCE_META)[number], now: Date | undefined) {
  return { ...sourceFreshness(m.sourceId, { now }), name: m.nameJa, publisher: m.publisher, superseded_by: m.supersededBy };
}

/** 出力行数の上限（コンテキストを溢れさせない。超えたら `truncated: true`）。 */
const MAX_ROWS = 500;
const limitSchema = z.number().int().min(1).max(MAX_ROWS).optional().describe(`返す行数の上限（既定 100、最大 ${MAX_ROWS}）`);

function cap<T>(rows: readonly T[], limit: number | undefined): { rows: T[]; truncated: boolean } {
  const n = limit ?? 100;
  return { rows: rows.slice(0, n), truncated: rows.length > n };
}

/** get_observations の grain='day' で from/to が無いときに読む期間（年）。 */
const DAY_DEFAULT_YEARS = 2;

const READING_RULES =
  "読み方: 値は定量下限未満を value_lod（下限値で代用）と value_zero（0 で代用）の両方で返す。" +
  "n_censored・n_not_detected が多い系列は下限付近の値を平均した結果なので断定しない。" +
  "caveats は必ず利用者に伝える。provenance の fetched_at・update_mode・age_days から、データの新しさと更新方式を判断する" +
  "（update_mode が undeclared の出典は更新方式が未宣言）。欠測を補完しない。";

export const MCP_TOOLS: McpTool[] = [
  defineTool({
    name: "describe_catalog",
    description:
      "流域カルテにどんな測定項目・水域・ゾーン・出典があるかを一覧する。まず全体像を掴むときに使う。" +
      "what='variables' は測定項目（variableId を get_observations に渡す）、'waters' は水域、'zones' は Ridge to Reef ゾーン、" +
      "'sources' は出典（取得日・更新方式つき）。" +
      READING_RULES,
    inputSchema: z.object({
      what: z.enum(["variables", "waters", "zones", "sources"]).describe("一覧する対象"),
      variableId: z.string().optional().describe("what='waters' のとき、この項目のデータを持つ水域に絞る（variables の variableId）"),
      limit: limitSchema,
    }),
    execute: async ({ what, variableId, limit }, ctx) => {
      const query = { what, variableId: variableId ?? null, limit: limit ?? null };
      const opt = { now: ctx.now };
      if (what === "zones") return buildDataEnvelope(query, { zones: [...ZONE_INFO] }, [], opt);
      if (what === "sources") {
        const { rows, truncated } = cap(
          SOURCE_META.map((m) => sourceRow(m, ctx.now)),
          limit ?? MAX_ROWS,
        );
        return buildDataEnvelope(query, { sources: rows }, [], { ...opt, truncated });
      }
      const db = await ctx.db();
      if (what === "waters") {
        const all = variableId
          ? await waterBodies(db, { series: representativeSeries(variableId, MEASUREMENTS_DATASET) })
          : await waterBodies(db, { dataset: MEASUREMENTS_DATASET });
        const { rows, truncated } = cap(all, limit);
        return buildDataEnvelope(query, { waters: rows }, [], { ...opt, truncated });
      }
      const all = await variableCatalog(db, { dataset: MEASUREMENTS_DATASET });
      const { rows, truncated } = cap(all, limit);
      const sourceIds = rows.flatMap((r) => seriesSourceRefsOf(r.variableId));
      return buildDataEnvelope(
        query,
        { variables: rows.map((r) => ({ ...r, label: VARIABLE_LABEL[r.variableId]?.short ?? null })) },
        sourceIds,
        { ...opt, truncated },
      );
    },
  }),

  defineTool({
    name: "search_registry",
    description:
      "語彙（測定項目・出典・生物種）を名前で検索する。変数名や種名の表記ゆれから ID（variableId・sourceId・学名）を引くときに使う。" +
      "kind='variable' は測定項目、'source' は出典、'species' は出現記録のある種（和名・学名）。",
    inputSchema: z.object({
      kind: z.enum(["variable", "source", "species"]).describe("検索する語彙"),
      query: z.string().min(1).max(100).describe("部分一致の検索語（和名・英名・ID の一部）"),
      limit: limitSchema,
    }),
    execute: async ({ kind, query, limit }, ctx) => {
      const q = query.trim().toLowerCase();
      const hit = (...xs: (string | null | undefined)[]) => xs.some((x) => x != null && x.toLowerCase().includes(q));
      const opt = { now: ctx.now };
      if (kind === "variable") {
        const rows = GENERATED_VARIABLES.filter((v) => hit(v.variableId, v.code, v.nameJa, v.nameEn, VARIABLE_LABEL[v.variableId]?.short)).map((v) => ({
          variableId: v.variableId,
          nameJa: v.nameJa,
          nameEn: v.nameEn,
          theme: v.theme,
          unitId: v.unitId,
        }));
        const c = cap(rows, limit);
        return buildDataEnvelope({ kind, query, limit: limit ?? null }, { matches: c.rows }, [], { ...opt, truncated: c.truncated });
      }
      if (kind === "source") {
        const rows = SOURCE_META.filter((m) => hit(m.sourceId, m.nameJa, m.publisher)).map((m) => sourceRow(m, ctx.now));
        const c = cap(rows, limit);
        return buildDataEnvelope({ kind, query, limit: limit ?? null }, { matches: c.rows }, [], { ...opt, truncated: c.truncated });
      }
      // species: cube 層の speciesCatalog に検索語を渡して絞る（学名・和名の部分一致。MCP 専用の SQL は持たない）。
      const n = (limit ?? 100) + 1; // 1 件多く取って truncated を判定する
      const catalog = await speciesCatalog(await ctx.db(), { search: query, limit: n, withNames: true });
      const rows = catalog.map((s) => ({ binom: s.binom, label: s.label ?? null, taxonGroup: s.taxonGroup, n: s.n }));
      const c = cap(rows, limit);
      return buildDataEnvelope(
        { kind, query, limit: limit ?? null },
        { matches: c.rows },
        OCCURRENCE_SOURCE_IDS,
        { ...opt, truncated: c.truncated },
      );
    },
  }),

  defineTool({
    name: "get_observations",
    description:
      "ある測定項目の時系列を取る（水質・気象・水文など）。scope で水域（地点ごと）・1地点・ゾーン平均を選び、grain で粒度を選ぶ。" +
      "応答は封筒（rows・coverage・provenance・caveats・excluded・cite_as）。" +
      READING_RULES,
    inputSchema: z.object({
      variableId: z.string().describe("測定項目の ID（describe_catalog / search_registry で引く）"),
      scope: z.discriminatedUnion("type", [
        z.object({ type: z.literal("water"), name: z.string().describe("水域名（describe_catalog what='waters'）") }),
        z.object({ type: z.literal("site"), siteId: z.string().describe("地点 ID") }),
        z.object({ type: z.literal("zone") }),
      ]),
      grain: z.enum(["year", "fiscal_year", "month", "day"]).describe("時間の粒度。year=暦年、fiscal_year=年度（4月始まり）、month=月、day=日。zone は year/fiscal_year のみ意味を持つ"),
      stat: z.string().optional().describe("非代表の統計量（p75/p90/max/min）。省略時は代表系列"),
      from: z.string().optional().describe(`grain='day' の開始日 YYYY-MM-DD（grain='day' で from/to とも省略すると直近 ${DAY_DEFAULT_YEARS} 年）`),
      to: z.string().optional().describe("grain='day' の終了日 YYYY-MM-DD"),
      limit: limitSchema,
    }),
    execute: async ({ limit, ...input }, ctx) => {
      // grain='day' で期間が無いと全期間の日次を読む。直近 DAY_DEFAULT_YEARS 年に絞り、query に反映して黙らない。
      if (input.grain === "day" && !input.from && !input.to) {
        const now = ctx.now ?? new Date();
        input.from = `${now.getUTCFullYear() - DAY_DEFAULT_YEARS}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-${String(now.getUTCDate()).padStart(2, "0")}`;
      }
      const r = await timeseries(await ctx.db(), input, { now: ctx.now });
      if (!r.envelope) {
        // 該当する系列が登録されていない。空の封筒（出典なし）で返し、黙って別の系列に倒さない。
        return buildDataEnvelope({ ...input }, { rows: [] }, [], { now: ctx.now });
      }
      const c = cap(r.envelope.rows, limit);
      return { ...r.envelope, rows: c.rows, truncated: r.envelope.truncated || c.truncated, sites: r.sites };
    },
  }),

  defineTool({
    name: "get_occurrences",
    description:
      "生物の出現記録（GBIF・iNaturalist）の集計を取る。kind='species_catalog' は種の一覧（件数の多い順、group で分類群を絞る）、" +
      "'species_years'/'species_months' は種ごとの年別・月別件数（binoms に学名）、'watershed_years' は流域ごとの年別件数。" +
      "出現記録は観察努力量に偏るため、件数の増減を生息数の増減と読まない。" +
      "source_ids で出典（gbif_kanagawa_occurrences・inaturalist_kanagawa・kanagawa_edna・kanagawa_kuma_sightings）を絞れる（省略時は全出典の合算）。" +
      "eDNA（kanagawa_edna）は採水による検出で、目視の観察とは性質が違うので、比べるときは出典で分ける。",
    inputSchema: z.object({
      kind: z.enum(["species_catalog", "species_years", "species_months", "watershed_years"]).describe("集計の種類"),
      group: z.string().optional().describe("kind='species_catalog' の分類群（例: 鳥類）"),
      binoms: z.array(z.string()).max(20).optional().describe("kind='species_years'/'species_months' の学名（最大 20）"),
      placeId: z.string().optional().describe("kind='watershed_years' の流域 place_id（省略時は全流域）"),
      source_ids: z
        .array(z.enum(OCCURRENCE_SOURCE_IDS as unknown as [string, ...string[]]))
        .min(1)
        .max(OCCURRENCE_SOURCE_IDS.length)
        .optional()
        .describe("出典で絞る（省略時は全出典の合算）。例: ['kanagawa_edna']"),
      limit: limitSchema,
    }),
    execute: async ({ kind, group, binoms, placeId, source_ids, limit }, ctx) => {
      const db = await ctx.db();
      const sourceIds = source_ids ?? [...OCCURRENCE_SOURCE_IDS]; // 未指定は全出典（絞り込みなし）
      const filter = source_ids ? { sourceIds: source_ids } : {};
      const query = { kind, group: group ?? null, binoms: binoms ?? null, placeId: placeId ?? null, source_ids: source_ids ?? null, limit: limit ?? null };
      let rows: unknown[];
      if (kind === "species_catalog") rows = await speciesCatalog(db, { group: group ?? null, limit: (limit ?? 100) + 1, withNames: true, ...filter });
      else if (kind === "watershed_years") rows = await watershedYears(db, { placeId, ...filter });
      else {
        if (!binoms?.length) throw new McpInputError(`kind='${kind}' には binoms（学名）が要る`);
        rows = kind === "species_years" ? await speciesYears(db, binoms, filter) : await speciesMonths(db, binoms, filter);
      }
      const c = cap(rows, limit);
      return buildDataEnvelope(query, { rows: c.rows, n_total: rows.length }, sourceIds, { now: ctx.now, truncated: c.truncated });
    },
  }),

  defineTool({
    name: "get_edna",
    description: EDNA_DESCRIPTION,
    inputSchema: ednaInputSchema,
    execute: async (args, ctx) => {
      const result = await queryEdna(await ctx.db(), args);
      return buildDataEnvelope(
        { ...args },
        { mode: result.mode, rows: result.rows, has_more: result.has_more, limit: result.limit, offset: result.offset },
        [EDNA_SOURCE_ID],
        { now: ctx.now, truncated: result.has_more, caveats: ednaCaveats() },
      );
    },
  }),

  defineTool({
    name: "export_dataset",
    description:
      "配布用データセット（dist/ の Parquet）の目録を返す。datapackage.json が指す各ファイルの相対パスと sha256 だけで、" +
      "ファイルそのものは返さない（配信は別）。配布物が未配備のときは available=false と理由を返す。",
    inputSchema: z.object({}),
    execute: async (_args, ctx) => {
      const pkg = await (ctx.datapackage ?? loadDatapackage)();
      if (pkg === null) {
        return buildDataEnvelope({}, { available: false, reason: "dist/datapackage.json が配備されていない（配信は未実施）" }, [], { now: ctx.now });
      }
      return buildDataEnvelope({}, { available: true, resources: datapackageResources(pkg) }, [], { now: ctx.now });
    },
  }),
];

export class McpInputError extends Error {}

/** `datapackage.json`（Frictionless）の resources から、パスと sha256 とサイズだけを取り出す（他の項目は渡さない）。 */
export function datapackageResources(pkg: unknown): { name: string | null; path: string | null; sha256: string | null; bytes: number | null }[] {
  const resources = (pkg as { resources?: unknown }).resources;
  if (!Array.isArray(resources)) return [];
  return resources.map((r: Record<string, unknown>) => {
    const raw = typeof r.sha256 === "string" ? r.sha256 : typeof r.hash === "string" ? r.hash : null;
    return {
      name: typeof r.name === "string" ? r.name : null,
      path: typeof r.path === "string" ? r.path : null,
      sha256: raw ? raw.replace(/^sha256:/, "") : null,
      bytes: typeof r.bytes === "number" ? r.bytes : null,
    };
  });
}

function seriesSourceRefsOf(variableId: string) {
  return seriesSourceRefs(representativeSeries(variableId, MEASUREMENTS_DATASET));
}
