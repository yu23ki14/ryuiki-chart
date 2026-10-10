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
  OBSERVATION_SOURCE_IDS,
  OCCURRENCE_SOURCE_IDS,
  seriesSourceRefs,
  sourceAccess,
  speciesCatalog,
  speciesMonths,
  speciesCatalogCounts,
  speciesYearsWithCoverage,
  timeseries,
  TimeseriesInputError,
  variableCatalog,
  watershedYears,
  waterBodies,
  MEASUREMENTS_DATASET,
  type CubeDb,
} from "@/lib/cube";
import { SOURCE_META } from "@/lib/registry/generated-source";
import { sourceRow, sourceSummary } from "@/lib/source-catalog";
import { GENERATED_VARIABLES } from "@/lib/registry/generated";
import { VARIABLE_LABEL, ZONE_INFO } from "@/lib/registry/generated-client";
import { representativeSeries } from "@/lib/cube/series";
import { EDNA_DESCRIPTION, EDNA_SOURCE_ID, ednaInputSchema, queryEdna } from "@/lib/edna";
import { caveatsForFacets, facetsForOccurrence } from "@/lib/cube/caveats";
import { SPECIES_MIN_N } from "@/lib/cube/occurrence";
import { loadDatapackage } from "./datapackage";
import { McpInputError } from "./errors";
import { getRecordsTool } from "./tools-records";
import { findDatasetsTool } from "./tools-find-datasets";

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

/** 出力行数の上限（コンテキストを溢れさせない。超えたら `truncated: true`）。 */
const MAX_ROWS = 500;
const limitSchema = z.number().int().min(1).max(MAX_ROWS).optional().describe(`返す行数の上限（既定 100、最大 ${MAX_ROWS}）`);

/**
 * 出現記録の注記。結果に含まれる出典の source facet だけで、registry から機械的に引く（出典の分岐は書かない）。
 * MCP は件数を返すので、割合で比べる画面の注記（grid01 の share）は引かない（places は空）。
 */
function occurrenceCaveats(sourceIds: readonly string[]) {
  return caveatsForFacets(facetsForOccurrence({ places: [], sourceIds }));
}

/**
 * species_months で行が空だった種の理由を返す。足切りそのものは外さない。
 * 足切りの判定列は `summary_species_catalog.n_located`（座標のある記録の件数。仮の名前。A の統合後に合わせる）。
 * 1回の完全一致の問い合わせ（binom IN json_each）で n と n_located を引く。
 *  - suppressed: 足切り（n_located < min_n）。n（座標なしを含む）と n_located を添える。
 *  - no_located_month_cells: 足切りは通ったが、指定の出典の月セルが無い（出典の絞り込み・2018年以降のみ等）。
 *  - not_in_catalog: カタログに無い学名。
 */
async function monthsEmptyReasons(db: CubeDb, binoms: readonly string[], rows: readonly { binom: string }[], sourceIds: readonly string[]) {
  const have = new Set(rows.map((r) => r.binom));
  const missing = [...new Set(binoms)].filter((b) => !have.has(b));
  const out = {
    suppressed: [] as { binom: string; n: number; n_located: number; min_n: number }[],
    no_located_month_cells: [] as { binom: string; source_ids: string[] }[],
    not_in_catalog: [] as string[],
  };
  if (!missing.length) return out;
  const byBinom = await speciesCatalogCounts(db, missing);
  for (const binom of missing) {
    const hit = byBinom.get(binom);
    if (!hit) out.not_in_catalog.push(binom);
    else if (hit.nLocated < SPECIES_MIN_N) out.suppressed.push({ binom, n: hit.n, n_located: hit.nLocated, min_n: SPECIES_MIN_N });
    else out.no_located_month_cells.push({ binom, source_ids: [...sourceIds] });
  }
  return out;
}

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
      "'sources' は出典（取得日・更新方式・取れるツール queryable_via・取れない理由つき。queryable_via が find_datasets の出典は外部ポータルの目録で、値ではなく定義と最新の URL を find_datasets で引く）。" +
      "出典の件数・ツール別の件数・取れない理由別の件数は応答の summary を使う（一覧を自分で数えない）。" +
      "n_source_rows は原本の行数で、get_observations の n（集計に使った件数）とは別物（find_datasets の出典では目録のデータセット数。n_source_rows_basis=catalog_datasets）。" +
      READING_RULES,
    inputSchema: z.object({
      what: z.enum(["variables", "waters", "zones", "sources"]).describe("一覧する対象"),
      variableId: z.string().optional().describe("what='waters' のとき、この項目のデータを持つ水域に絞る（variables の variableId）"),
      queryable: z.boolean().optional().describe("what='sources' のとき、ツールで値が取れる出典（true）／取れない出典（false）に絞る"),
      limit: limitSchema,
    }).strict(),
    execute: async ({ what, variableId, queryable, limit }, ctx) => {
      const query = { what, variableId: variableId ?? null, queryable: queryable ?? null, limit: limit ?? null };
      const opt = { now: ctx.now };
      if (what === "zones") return buildDataEnvelope(query, { zones: [...ZONE_INFO] }, [], opt);
      if (what === "sources") {
        const picked =
          queryable === undefined ? SOURCE_META : SOURCE_META.filter((m) => (sourceAccess(m.sourceId)?.state === "queryable") === queryable);
        const { rows, truncated } = cap(
          picked.map((m) => sourceRow(m, ctx.now)),
          limit ?? MAX_ROWS,
        );
        // summary は絞り込みに関わらず全出典の集計（「全部で何件・何が取れるか」を数えさせない）。
        return buildDataEnvelope(query, { summary: sourceSummary(SOURCE_META), sources: rows }, [], { ...opt, truncated });
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
    }).strict(),
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
      "ある測定項目の時系列を取る（水質・気象・水文など）。scope で水域（地点ごと）・1地点・ゾーン平均・流域を選び、grain で粒度を選ぶ。" +
      "source_ids を省略すると水質などの測定値系の系列（従来どおり）。大気（相模原・そらまめ）・河川水位（横浜）のセンサー系列や" +
      "土地利用（流域ごと、scope.type='watershed'）は source_ids で出典を指定して引く（出典は describe_catalog what='sources' の queryable_via に get_observations があるもの）。" +
      "センサー系列は毎時の観測を日・月・年に積んだ値なので、密な日次は scope=site と from/to で絞り、広く見るなら grain=month/year にする" +
      "（grain='day' で from/to とも省略すると直近 " + DAY_DEFAULT_YEARS + " 年）。" +
      "同じ測定項目・粒度の系列を複数の出典が共有するとき、セルは出典で分けられない（provenance に出典が並ぶ）。" +
      "応答は封筒（rows・coverage・provenance・caveats・excluded・cite_as）。" +
      READING_RULES,
    inputSchema: z.object({
      variableId: z.string().describe("測定項目の ID（describe_catalog / search_registry で引く）"),
      scope: z.discriminatedUnion("type", [
        z.object({ type: z.literal("water"), name: z.string().describe("水域名（describe_catalog what='waters'）") }).strict(),
        z.object({ type: z.literal("site"), siteId: z.string().describe("地点 ID") }).strict(),
        z.object({ type: z.literal("zone") }).strict(),
        z.object({ type: z.literal("watershed"), placeId: z.string().optional().describe("流域の place_id（省略は全流域。土地利用など流域単位の系列用）") }).strict(),
      ]),
      source_ids: z
        .array(z.enum(OBSERVATION_SOURCE_IDS as unknown as [string, ...string[]]))
        .min(1)
        .max(OBSERVATION_SOURCE_IDS.length)
        .optional()
        .describe("出典で絞る（その出典の系列を dataset を問わず引く）。省略時は測定値系（measurements）の系列。例: ['soramame_hourly_kanagawa']"),
      grain: z.enum(["year", "fiscal_year", "month", "day"]).describe("時間の粒度。year=暦年、fiscal_year=年度（4月始まり）、month=月、day=日。zone は year/fiscal_year のみ意味を持つ"),
      stat: z.string().optional().describe("非代表の統計量（p75/p90/max/min）。省略時は代表系列"),
      from: z.string().optional().describe(`grain='day' の開始日 YYYY-MM-DD（grain='day' で from/to とも省略すると直近 ${DAY_DEFAULT_YEARS} 年）`),
      to: z.string().optional().describe("grain='day' の終了日 YYYY-MM-DD"),
      limit: limitSchema,
    }).strict(),
    execute: async ({ limit, ...input }, ctx) => {
      // grain='day' で期間が無いと全期間の日次を読む。直近 DAY_DEFAULT_YEARS 年に絞り、query に反映して黙らない。
      if (input.grain === "day" && !input.from && !input.to) {
        const now = ctx.now ?? new Date();
        input.from = `${now.getUTCFullYear() - DAY_DEFAULT_YEARS}-${String(now.getUTCMonth() + 1).padStart(2, "0")}-${String(now.getUTCDate()).padStart(2, "0")}`;
      }
      const { source_ids, ...rest } = input;
      let r;
      try {
        r = await timeseries(await ctx.db(), { ...rest, ...(source_ids ? { sourceIds: source_ids } : {}) }, { now: ctx.now });
      } catch (e) {
        if (e instanceof TimeseriesInputError) throw new McpInputError(e.message);
        throw e;
      }
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
      "生物の出現記録（GBIF・iNaturalist。神奈川県・奄美大島）の集計を取る。kind='species_catalog' は種の一覧（件数の多い順、group で分類群を絞る）、" +
      "'species_years'/'species_months' は種ごとの年別・月別件数（binoms に学名）、'watershed_years' は流域ごとの年別件数。" +
      "出現記録は観察努力量に偏るため、件数の増減を生息数の増減と読まない。" +
      "source_ids で出典（gbif_kanagawa_occurrences・inaturalist_kanagawa・gbif_amami_occurrences・inaturalist_amami・kanagawa_edna・kanagawa_kuma_sightings）を絞れる（省略時は全出典の合算）。" +
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
    }).strict(),
    execute: async ({ kind, group, binoms, placeId, source_ids, limit }, ctx) => {
      const db = await ctx.db();
      const sourceIds = source_ids ?? [...OCCURRENCE_SOURCE_IDS]; // 未指定は全出典（絞り込みなし）
      const filter = source_ids ? { sourceIds: source_ids } : {};
      const query = { kind, group: group ?? null, binoms: binoms ?? null, placeId: placeId ?? null, source_ids: source_ids ?? null, limit: limit ?? null };
      let rows: unknown[];
      let coverage: { no_coordinate: { binom: string; year: number; source_id: string; n: number }[]; truncated: boolean } | undefined;
      let coverageTruncated = false;
      let extra: Record<string, unknown> = {};
      if (kind === "species_catalog") rows = await speciesCatalog(db, { group: group ?? null, limit: (limit ?? 100) + 1, withNames: true, ...filter });
      else if (kind === "watershed_years") rows = await watershedYears(db, { placeId, ...filter });
      else {
        if (!binoms?.length) throw new McpInputError(`kind='${kind}' には binoms（学名）が要る`);
        if (kind === "species_years") {
          // 1回の集計から両方を導く。n は座標の無い記録を含む。そのうち格子に置けなかった件数を出典別・年別に添える
          // （mesh_n は座標のある記録だけ）。coverage も rows と同じ上限・truncated を効かせる。
          const r = await speciesYearsWithCoverage(db, binoms, filter);
          rows = r.years;
          const nc = cap(r.noCoordinate, limit);
          coverageTruncated = nc.truncated;
          coverage = { no_coordinate: nc.rows.map((x) => ({ binom: x.binom, year: x.year, source_id: x.sourceId, n: x.n })), truncated: nc.truncated };
        } else {
          const months = await speciesMonths(db, binoms, filter);
          rows = months;
          // 行が空の種は、黙って空にせず理由（足切り・月セル無し・カタログ外）を返す。
          const s = await monthsEmptyReasons(db, binoms, months, sourceIds);
          if (s.suppressed.length || s.no_located_month_cells.length || s.not_in_catalog.length) extra = s;
        }
      }
      const c = cap(rows, limit);
      return buildDataEnvelope(query, { rows: c.rows, n_total: rows.length, ...(coverage ? { coverage } : {}), ...extra }, sourceIds, { now: ctx.now, truncated: c.truncated || coverageTruncated, caveats: occurrenceCaveats(sourceIds) });
    },
  }),

  defineTool({
    name: "get_edna",
    description: EDNA_DESCRIPTION,
    inputSchema: ednaInputSchema.strict(), // MCP だけ strict（AI 側は余計なキーで詰まらないよう既定のまま）
    execute: async (args, ctx) => {
      const result = await queryEdna(await ctx.db(), args);
      const c = cap(result.rows, args.limit);
      return buildDataEnvelope(
        { ...args },
        { mode: result.mode, rows: c.rows, offset: result.offset },
        [EDNA_SOURCE_ID],
        { now: ctx.now, truncated: c.truncated, caveats: occurrenceCaveats([EDNA_SOURCE_ID]) },
      );
    },
  }),

  defineTool({
    name: "export_dataset",
    description:
      "配布用データセット（dist/ の Parquet）の目録を返す。datapackage.json が指す各ファイルの相対パスと sha256 だけで、" +
      "ファイルそのものは返さない（配信は別）。配布物が未配備のときは available=false と理由を返す。",
    inputSchema: z.object({}).strict(),
    execute: async (_args, ctx) => {
      const pkg = await (ctx.datapackage ?? loadDatapackage)();
      if (pkg === null) {
        return buildDataEnvelope({}, { available: false, reason: "dist/datapackage.json が配備されていない（配信は未実施）" }, [], { now: ctx.now });
      }
      return buildDataEnvelope({}, { available: true, resources: datapackageResources(pkg) }, [], { now: ctx.now });
    },
  }),

  getRecordsTool(),
  findDatasetsTool(),
];

export { McpInputError };

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
