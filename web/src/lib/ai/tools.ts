import "server-only";
import { z } from "zod";
import { tool } from "ai";
import { listTables, runUserSql, SqlError } from "@/lib/db";
import { TABLE_META, SCHEMA_META, TABLE_ORIGIN } from "@/lib/table-meta";
import { ZONE_INFO } from "@/lib/registry/generated-client";
import { getVariable, unitBasis, type UnitBasis } from "@/lib/registry/lookup";
import {
  d1CubeDb,
  representativeSeries,
  withTheme,
  summarize,
  unitLabel,
  variableCatalog,
  siteVariables,
  sites as cubeSites,
  site as cubeSite,
  waterBodies,
  taxonGroupYears,
  effortYears,
  occurrenceTotals,
  speciesShareTrend,
  speciesYears,
  speciesYearsNoCoordinate,
  speciesMonths,
  redlistBundle,
  overviewCounts,
  watershedRollup,
  type Scope,
} from "@/lib/cube";
import { facetsForSeries, facetsForOccurrence, facetsForTables, caveatKeysForFacets, variableTheme } from "@/lib/cube/caveats";
import { MEASUREMENTS_DATASET } from "@/lib/cube/series";
import { timeseries } from "@/lib/cube/timeseries";
import { EDNA_DESCRIPTION, EDNA_SOURCE_ID, ednaInputSchema, queryEdna } from "@/lib/edna";

/** 測定値系データセット固定（PR-2 のスコープは測定値系。design §1.1 と同じ前提）。registry の dataset キー。 */
const DATASET = MEASUREMENTS_DATASET;

/**
 * 意図レベルのツール9個。中身は queries.ts の合成で、新しい SQL はほぼ書かない
 * （唯一の例外が run_sql で、それも既存の runUserSql をラップするだけ）。
 *
 * 70関数を全部ツール化すると選択精度が落ちるので、意図（「時系列が見たい」「地点を調べたい」…）の
 * 単位でまとめている。戻り値の形は全ツール共通（ToolResult）にして、証跡カード側は
 * モデルの出力に関係なく機械的に描けるようにする。
 */

export interface ToolResult<T> {
  data: T;
  provenance: {
    tool: string;
    tables: string[];
    sql?: string;
    rowCount: number;
    elapsedMs: number;
  };
  /** 注記の「キー」だけ。本文はシステムプロンプトが持ち、表示は証跡カードが caveatText で引く。 */
  caveats: string[];
  truncated?: boolean;
  /** 間引きが起きたときだけ入る。モデルが truncated フラグを読み飛ばしても気づけるように文で書く。 */
  truncatedNote?: string;
}

/* ------------------------------------------------------------------ */
/* 24KB 切り詰めヘルパ（全ツール共通で通す）                               */
/* ------------------------------------------------------------------ */

/**
 * ツール結果1件あたりの上限。
 *
 * 8KB だと 5地点×11年（55点）程度の普通の時系列でも間引きが起きてしまい、
 * モデルが見る点が半分になる（実測: 55点 -> 28点）。Kimi K2.6 の文脈長は 262k あり、
 * 5ステップ分を足しても 24KB×5=120KB は十分収まる。
 * organism_records 系の暴走（数万トークン）を止めるという本来の目的はこの値でも果たせる。
 */
const BYTE_BUDGET = 24 * 1024;

function byteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

/** data の中に生えている配列（1階層ずつ掘って集める。深追いはしない）を集める。 */
function collectArrays(value: unknown, acc: unknown[][], depth: number): unknown[][] {
  if (depth > 4 || value === null || typeof value !== "object") return acc;
  if (Array.isArray(value)) {
    acc.push(value);
    return acc; // 配列の要素自体はオブジェクトでも掘らない。行を間引く対象は配列そのもの。
  }
  for (const v of Object.values(value as Record<string, unknown>)) collectArrays(v, acc, depth + 1);
  return acc;
}

/**
 * 配列を等間隔に間引く。先頭と末尾は必ず残す。
 *
 * 末尾から削ってはいけない。queries.ts の系列はどれも日付の昇順に並んでいるので、
 * 末尾を落とすと「直近のデータだけが消えた系列」になり、モデルが古い期間だけを見て
 * 傾向を語る（例: 実際は悪化しているのに「改善傾向」と答える）。
 */
function subsample<T>(arr: T[], keep: number): T[] {
  if (keep >= arr.length) return arr;
  if (keep <= 1) return arr.length ? [arr[arr.length - 1]] : [];
  const step = (arr.length - 1) / (keep - 1);
  const out: T[] = [];
  for (let i = 0; i < keep; i++) out.push(arr[Math.round(i * step)]);
  return out;
}

/**
 * JSON化して24KBを超えたら、いちばん大きい配列を等間隔に間引いて縮める。
 * organism_records 系は素で数万トークンになりうるので、これを全ツールの出口に通す。
 *
 * 先にコピーを取ってから縮めるのは、ZONE_INFO のようなモジュールレベルの定数が
 * data に直接入ってくることがあるため。その場で縮めるとワーカープロセス全体で
 * その定数が壊れ、画面側（/timeseries のゾーン表示など）にまで波及する。
 */
function fitToBudget<T>(data: T): { data: T; truncated: boolean } {
  if (byteLength(data) <= BYTE_BUDGET) return { data, truncated: false };
  const copy = structuredClone(data);
  const arrays = collectArrays(copy, [], 0);
  if (arrays.length === 0) return { data: copy, truncated: true };

  let truncated = false;
  let guard = 0;
  while (byteLength(copy) > BYTE_BUDGET && guard++ < 40) {
    const target = arrays.filter((a) => a.length > 2).sort((a, b) => b.length - a.length)[0];
    if (!target) break;
    const next = subsample(target, Math.max(2, Math.ceil(target.length * 0.7)));
    target.length = 0;
    for (const v of next) target.push(v);
    truncated = true;
  }
  return { data: copy, truncated };
}

/**
 * ツール結果の共有辞書 `registry` の1エントリ。
 *
 * `variableId` は持たない（キーに出るので二重持ちしない）。`code` も持たない
 * （`variableId` は常に `"common:variable:" + code` の形なので、`code` は
 * `variableId` から機械的に取り出せる冗長な値。実測で registry/variable.yaml の
 * 85件全件がこの形を満たすことを確認済み。持たせても情報は増えないのに
 * `list_catalog(what='variables')` のように行ごとの variable が大半重複しない
 * 一覧では、辞書のキー自体（variableId 文字列）を持つコストが de-dup の効果を
 * 上回ってしまい、`code` を削らないと合計サイズがむしろ増える）。
 */
interface RegistryEntry {
  nameJa: string | null;
  unit: string | null;
  higherIsWorse: boolean | null;
  descriptionJa: string | null;
  /** 単位の根拠: 'source'=原本が報告 / 'registry'=原本に単位記載が無くレジストリが補った / 'mixed'。 */
  unitBasis: UnitBasis | null;
}

/**
 * `variableId`（正準の指標ID）から registry の1エントリを引く（Issue #48 PR-2）。
 * `lib/cube` の問い合わせは行に variableId を直接持つので、v1 の
 * `resolveVariableInfo`（出典表記→variableId の解決）はもう要らない——ここでは
 * `@/lib/registry/lookup` の `getVariable` で variable テーブルを直接引くだけ。
 * `unitId` を渡すと（系列固有の単位。alias 側の unit_id 上書きに相当）そちらを優先する。
 * 明示的な null は「単位不明」であり、variable の既定単位で埋めない（推測しない）。
 */
function registryEntryForVariable(variableId: string, unitId?: string | null): RegistryEntry | null {
  const v = getVariable(variableId);
  if (!v) return null;
  // 単位: 省略（undefined）なら variable の既定。明示的な null（単位不明の系列）は null のまま。
  const u = unitId === undefined ? v.unitId : unitId;
  return {
    nameJa: v.nameJa,
    unit: unitLabel(u),
    unitBasis: unitBasis(variableId, u),
    higherIsWorse: v.higherIsWorse,
    descriptionJa: v.descriptionJa,
  };
}

/** `registryEntryForVariable` を複数の (variableId, unitId) 組に対して呼び、共有辞書にまとめる。 */
function registryFor(pairs: readonly { variableId: string; unitId?: string | null }[]): Record<string, RegistryEntry> {
  const registry: Record<string, RegistryEntry> = {};
  for (const { variableId, unitId } of pairs) {
    if (registry[variableId]) continue;
    const e = registryEntryForVariable(variableId, unitId);
    if (e) registry[variableId] = e;
  }
  return registry;
}

function makeResult<T>(opts: {
  tool: string;
  tables: string[];
  data: T;
  rowCount: number;
  elapsedMs: number;
  sql?: string;
  /** table 経由ではなく facet 経由で決めた注記キー（`lib/cube/caveats` の
   *  `facetsForSeries`/`caveatKeysForFacets` を使うツール用）。指定時はこちらを使う。 */
  caveats?: string[];
}): ToolResult<T> {
  const { data, truncated } = fitToBudget(opts.data);
  return {
    data,
    provenance: {
      tool: opts.tool,
      tables: opts.tables,
      sql: opts.sql,
      rowCount: opts.rowCount,
      elapsedMs: Math.round(opts.elapsedMs),
    },
    caveats: opts.caveats ?? caveatKeysForFacets(facetsForTables(opts.tables)),
    truncated: truncated || undefined,
    truncatedNote: truncated
      ? "応答が大きいため系列を等間隔に間引いてある（先頭と末尾は保持）。実際の件数は provenance.rowCount。" +
        "間引いた系列から「何件あった」「この期間に無かった」とは言えない。"
      : undefined,
  };
}

/* ------------------------------------------------------------------ */
/* 1. list_catalog                                                    */
/* ------------------------------------------------------------------ */

const list_catalog = tool({
  description:
    "流域カルテにどんな測定項目・水域（地点をまとめた単位）・ゾーンがあるかを一覧する。具体的な数値を見る前に、まず全体像を掴むときに使う。",
  inputSchema: z.object({
    what: z
      .enum(["variables", "waters", "zones"])
      .describe("variables=水質などの測定項目一覧, waters=水域・地域一覧, zones=Ridge to Reefのゾーン(1-5)の定義"),
    variableId: z
      .string()
      .optional()
      .describe("what='waters' のとき、この項目のデータを実際に持つ水域だけに絞り込む（正準の指標ID。variables の結果の variableId をそのまま渡す）"),
  }),
  execute: async ({ what, variableId }) => {
    const t0 = performance.now();
    if (what === "zones") {
      return makeResult({
        tool: "list_catalog",
        tables: [],
        data: { zones: [...ZONE_INFO] },
        rowCount: ZONE_INFO.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const db = await d1CubeDb();
    if (what === "waters") {
      const rows = variableId
        ? await waterBodies(db, { series: representativeSeries(variableId, DATASET) })
        : await waterBodies(db, { dataset: DATASET });
      return makeResult({
        tool: "list_catalog",
        tables: ["sites", "summary_place_variable"],
        data: { waters: rows },
        rowCount: rows.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const rows = await variableCatalog(db, { dataset: DATASET });
    const registry = registryFor(rows.map((r) => ({ variableId: r.variableId, unitId: r.unitId })));
    return makeResult({
      tool: "list_catalog",
      tables: ["summary_variable_catalog"],
      data: { variables: rows, registry },
      rowCount: rows.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 2. get_timeseries                                                  */
/* ------------------------------------------------------------------ */

const scopeSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("water"), name: z.string().describe("水域・地域名（list_catalog の waters で取れる名前）") }),
  z.object({ type: z.literal("site"), siteId: z.string().describe("地点ID") }),
  z.object({ type: z.literal("zone") }),
]);

const get_timeseries = tool({
  description:
    "ある測定項目の時系列を取る。scope で「水域の中の地点ごと」「1地点」「ゾーン平均」のどれで見るかを選ぶ。grain で粒度を選ぶ。",
  inputSchema: z.object({
    variableId: z.string().describe("正準の指標ID（list_catalog(what='variables') の行の variableId をそのまま渡す）"),
    scope: scopeSchema,
    grain: z
      .enum(["year", "fiscal_year", "month", "day"])
      .describe(
        "時間の粒度。year=暦年（検体値から積み上げた年別平均。無ければ暦年値そのもの）、" +
          "fiscal_year=日本の年度（4月始まり。原本が年度集計値の項目はこちら）、month=月別平均、day=日次。" +
          "zoneスコープは year/fiscal_year のみ意味を持つ",
      ),
    stat: z
      .string()
      .optional()
      .describe("非代表の統計量（例: p75/p90/max/min）を明示したいときだけ指定する。省略時は代表系列（平均相当）"),
    from: z
      .string()
      .optional()
      .describe("grain='day' のときの開始日 YYYY-MM-DD。日次は点が多く、範囲を絞らないと間引かれる"),
    to: z.string().optional().describe("grain='day' のときの終了日 YYYY-MM-DD"),
  }),
  execute: async ({ variableId, scope, grain, stat, from, to }) => {
    const t0 = performance.now();
    const db = await d1CubeDb();
    // 本体は lib/cube/timeseries.ts（MCP の get_observations と同じ関数。封筒・注記もそこで付く）。
    const r = await timeseries(db, { variableId, scope, grain, stat, from, to });
    const registry = registryFor(r.series.map((s) => ({ variableId: s.variableId, unitId: s.unitId })));
    const base = { scope, grain, basis: r.basis, stat: stat ?? "representative", variableId, unit: r.unit, registry, points: r.points };
    if (r.series.length === 0) {
      return makeResult({
        tool: "get_timeseries",
        tables: [],
        data: { ...base, envelope: null },
        rowCount: 0,
        elapsedMs: performance.now() - t0,
      });
    }
    return makeResult({
      tool: "get_timeseries",
      tables: ["observation_agg"],
      data: { ...base, sites: r.sites, envelope: r.envelope },
      rowCount: r.points.length,
      elapsedMs: performance.now() - t0,
      caveats: r.envelope?.caveats.map((c) => c.key) ?? [],
    });
  },
});

/* ------------------------------------------------------------------ */
/* 3. get_seasonality                                                 */
/* ------------------------------------------------------------------ */

const get_seasonality = tool({
  description: "ある測定項目の季節性（月ごとの平均）を、全体とゾーン別の両方で取る。検体値（basis=day）の項目だけ意味を持つ。",
  inputSchema: z.object({
    variableId: z.string().describe("正準の指標ID（list_catalog(what='variables') の行の variableId をそのまま渡す）"),
  }),
  execute: async ({ variableId }) => {
    const t0 = performance.now();
    // 月別集計は検体値（basis=day）からの積み上げだけが意味を持つ（v1 meas_clim/zone_clim と同じ前提）。
    // series は value_grain で絞り込まない——`grain: "day"`/`"month"` のセル自体が
    // day-input の系列にしか存在しないため、grain 指定だけで自然に絞り込まれる
    // （Issue #48 PR-2 統合後修正A #1。basis はセルの性質であって系列の登録ではない）。
    const series = representativeSeries(variableId, DATASET);
    const registry = registryFor(series.map((s) => ({ variableId: s.variableId, unitId: s.unitId })));

    if (series.length === 0) {
      return makeResult({
        tool: "get_seasonality",
        tables: [],
        data: { variableId, registry, overall: [], byZone: [] },
        rowCount: 0,
        elapsedMs: performance.now() - t0,
      });
    }

    const db = await d1CubeDb();
    const overallScope: Scope = { kind: "all_sites" };
    // zero/lod を1回の SQL で両方計算する（`summarizeZone` と同じ `imputation:'both'`
    // 形。Issue #48 PR-2 /simplify #11）——以前は `imputation:'zero'`/`'lod'` を
    // 2回ずつ叩いて JS 側でキーを合わせていた（4回→2回）。
    const [overall_, zone_] = await Promise.all([
      summarize(db, { series, scope: overallScope, grain: "day", imputation: "both" }, "month_of_year"),
      summarize(db, { series, scope: overallScope, grain: "month", imputation: "both" }, "zone_month_of_year"),
    ]);
    const overall = overall_.rows.map((r) => ({
      month: r.month,
      n: r.n,
      min: r.min,
      max: r.max,
      valueLod: r.avgLod ?? null,
      valueZero: r.avgZero ?? null,
    }));
    const byZone = zone_.rows.map((r) => ({
      zone: r.zone,
      month: r.month,
      nSites: r.nSites,
      n: r.n,
      valueLod: r.avgLod ?? null,
      valueZero: r.avgZero ?? null,
    }));
    const facets = facetsForSeries(series.map((s) => withTheme(s)), overallScope);

    return makeResult({
      tool: "get_seasonality",
      tables: ["observation_agg"],
      data: { variableId, registry, overall, byZone },
      rowCount: overall.length + byZone.length,
      elapsedMs: performance.now() - t0,
      caveats: caveatKeysForFacets(facets),
    });
  },
});

/* ------------------------------------------------------------------ */
/* 4. get_sites                                                       */
/* ------------------------------------------------------------------ */

const get_sites = tool({
  description:
    "観測地点を調べる。site_id が分かっていれば個票（保有する測定項目の内訳つき）を返し、分からなければ名前やゾーンで絞った一覧を返す。",
  inputSchema: z.object({
    siteId: z.string().optional().describe("地点ID。指定すると個票が返る（他の引数は無視される）"),
    query: z.string().optional().describe("地点名の部分一致で絞り込む"),
    zone: z.number().int().min(1).max(5).optional().describe("Ridge to Reefのゾーン(1-5)で絞り込む"),
    limit: z.number().int().min(1).max(100).optional().describe("一覧のとき返す件数の上限（既定20）"),
  }),
  execute: async ({ siteId, query, zone, limit }) => {
    const t0 = performance.now();
    const db = await d1CubeDb();
    if (siteId) {
      // `catalog.siteVariables()` は `site()` と同じ site_id を受ける（Issue #48
      // PR-2 統合後修正A #2。内部の place_id への解決は `lib/cube` 側に集約した）。
      const [site, siteVars] = await Promise.all([
        cubeSite(db, siteId, { dataset: DATASET }),
        siteVariables(db, siteId, { imputation: "lod", dataset: DATASET }),
      ]);
      const registry = registryFor(siteVars.map((v) => ({ variableId: v.series.variableId, unitId: v.series.unitId })));
      return makeResult({
        tool: "get_sites",
        tables: ["sites", "summary_place_variable"],
        data: { site: site ?? null, variables: siteVars, registry },
        rowCount: siteVars.length,
        elapsedMs: performance.now() - t0,
      });
    }
    let rows = await cubeSites(db, { dataset: DATASET });
    if (query) {
      const q = query.toLowerCase();
      rows = rows.filter((s) => (s.name ?? "").toLowerCase().includes(q));
    }
    if (zone != null) rows = rows.filter((s) => s.zone === zone);
    const matched = rows.length;
    const limited = rows.slice(0, limit ?? 20);
    return makeResult({
      tool: "get_sites",
      tables: ["sites", "summary_place_variable"],
      data: { sites: limited, matched },
      rowCount: limited.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 5. get_biota_trend                                                 */
/* ------------------------------------------------------------------ */

/**
 * 期間は [開始年, 終了年] のタプルにしない。
 * z.tuple は JSON Schema の draft-07 形式（items が配列）に変換されるが、Workers AI 側の
 * 検証は draft 2020-12（タプルは prefixItems、items は単一スキーマ）なので 400 で弾かれる。
 * オブジェクトなら両方の draft で同じ形になる。
 */
const yearRange = z.object({
  from: z.number().describe("開始年（西暦）"),
  to: z.number().describe("終了年（西暦）"),
});

// 生物の注記は v1 表名ではなく facet（出典の source_id=<id>・place_kind=grid01）で決める。
const BIOTA_CAVEATS = caveatKeysForFacets(facetsForOccurrence({ places: ["grid01"] }));

const get_biota_trend = tool({
  description:
    "生物観察の推移を見る。mode='groups' で分類群別の年次件数と観察努力、mode='share' で分類群内シェアの前後比較、" +
    "mode='species' で個別の種の年次・月次推移を取る。",
  inputSchema: z.discriminatedUnion("mode", [
    z.object({ mode: z.literal("groups") }),
    z.object({
      mode: z.literal("share"),
      group: z.string().describe("分類群名（例: 鳥類）"),
      periodA: yearRange.describe("前期間"),
      periodB: yearRange.describe("後期間"),
    }),
    z.object({
      mode: z.literal("species"),
      binoms: z.array(z.string()).min(1).max(100).describe("学名（2語、例: Plecoglossus altivelis）の配列"),
    }),
  ]),
  execute: async (input) => {
    const t0 = performance.now();
    const db = await d1CubeDb();
    const caveats = BIOTA_CAVEATS;
    if (input.mode === "groups") {
      const [groups, effort] = await Promise.all([taxonGroupYears(db), effortYears(db)]);
      return makeResult({
        tool: "get_biota_trend",
        tables: ["summary_group_year", "summary_effort_year"],
        caveats,
        data: { mode: "groups", groups, effort },
        rowCount: groups.length + effort.length,
        elapsedMs: performance.now() - t0,
      });
    }
    if (input.mode === "share") {
      const { group, periodA, periodB } = input;
      const rows = await speciesShareTrend(db, group, periodA, periodB);
      return makeResult({
        tool: "get_biota_trend",
        tables: ["occurrence_agg", "summary_species_catalog"],
        caveats,
        data: { mode: "share", group, periodA, periodB, rows },
        rowCount: rows.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const { binoms } = input;
    const [years, months, noCoordinate] = await Promise.all([speciesYears(db, binoms), speciesMonths(db, binoms), speciesYearsNoCoordinate(db, binoms)]);
    // years[].n は座標の無い記録を含み、mesh_n は座標のある記録だけ。格子に置けなかった件数を出典別・年別に添える。
    const coverage = { no_coordinate: noCoordinate.map((r) => ({ binom: r.binom, year: r.year, source_id: r.sourceId, n: r.n })) };
    return makeResult({
      tool: "get_biota_trend",
      tables: ["occurrence_agg", "summary_species_catalog"],
      caveats,
      data: { mode: "species", binoms, years, months, coverage },
      rowCount: years.length + months.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 6. get_redlist                                                     */
/* ------------------------------------------------------------------ */

const get_redlist = tool({
  description: "レッドリストの版間比較を見る。まず summary で版・分類群ごとの増減件数を俯瞰し、年を指定すると内訳（flows/species）が付く。",
  inputSchema: z.object({
    year: z.number().int().describe("見たい版の年（例: 2022）。summary の一覧から選ぶとよい"),
    group: z.string().optional().describe("分類群（和名、例: 鳥類）で絞り込む"),
    direction: z
      .string()
      .optional()
      .describe("前版からの変化方向で絞り込む。値は summary/flows の結果に出てくる direction をそのまま渡す（推測で決め打ちしない）"),
  }),
  execute: async ({ year, group, direction }) => {
    const t0 = performance.now();
    const db = await d1CubeDb();
    const { summary, flows, species } = await redlistBundle(db, year, { group, direction, limit: 300 });
    return makeResult({
      tool: "get_redlist",
      tables: ["taxon_assessment"],
      data: { year, group, direction, summary, flows, species },
      rowCount: summary.length + flows.length + species.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 7. get_overview                                                    */
/* ------------------------------------------------------------------ */

const get_overview = tool({
  description: "アプリ全体の概況（地点数・観測指標数・生物記録数などの総数）と、流域ごとのロールアップ上位N件を取る。",
  inputSchema: z.object({
    limit: z.number().int().min(1).max(50).optional().describe("流域ロールアップの件数上限（既定10、生物記録数の多い順）"),
  }),
  execute: async ({ limit }) => {
    const t0 = performance.now();
    const db = await d1CubeDb();
    const [counts, rollupAll, occ] = await Promise.all([
      overviewCounts(db),
      watershedRollup(db),
      occurrenceTotals(db),
    ]);
    // 生物の件数・種数は cube（日付のある記録だけ）。それ以外の総数は overviewCounts。
    const stats = {
      n_sites: counts.sites,
      n_variables: counts.variables,
      n_org: occ.records,
      n_species: occ.species,
      n_sources: counts.sources,
      n_watersheds: counts.watersheds,
      y_from: counts.yFrom,
      y_to: counts.yTo,
    };
    // watershedRollup は生物の列まで含めて全流域を返す。AI には v1 形（snake_case）で渡す。
    const rollup = rollupAll.watersheds
      .map((r) => ({
        watershed_id: r.watershedId,
        water_system_name: r.waterSystemName,
        area_km2: r.areaKm2,
        centroid_lat: r.centroidLat,
        centroid_lon: r.centroidLon,
        site_n: r.siteN,
        org_n: r.orgN,
        org_alien_n: r.orgAlienN,
        org_redlist_n: r.orgRedlistN,
        built_km2_2006: r.built.from,
        built_km2_2016: r.built.to,
        forest_km2_2006: r.forest.from,
        forest_km2_2016: r.forest.to,
        paddy_km2_2006: r.paddy.from,
        paddy_km2_2016: r.paddy.to,
      }))
      .sort((a, b) => b.org_n - a.org_n)
      .slice(0, limit ?? 10);
    // 実際に読む表。測定値は返さないので、測定値の注記（measuredOn 等）は付かない。
    // 土地利用の列は定義変更をまたぐので landuseDefinitionChange を facet で付ける。
    const tables = [
      "sites",
      "source_registry",
      "place",
      "place_relation",
      "observation_agg",
      "summary_variable_catalog",
      "summary_effort_year",
      "summary_species_catalog",
      "summary_watershed_occurrence",
    ];
    const caveats = [
      ...new Set([
        ...caveatKeysForFacets(facetsForTables(["sites"])),
        // 生物の件数は流域のロールアップだけ（割合は出さない）なので watershed のみ。share は付かない。
        ...caveatKeysForFacets(facetsForOccurrence({ places: ["watershed"] })),
        ...caveatKeysForFacets([variableTheme("landuse")]),
      ]),
    ];
    return makeResult({
      tool: "get_overview",
      tables,
      caveats,
      data: {
        stats,
        landuse_years: rollupAll.landuseYears,
        watersheds: rollup,
        outside_watershed_n: rollupAll.outsideWatershed?.n ?? 0,
      },
      rowCount: rollup.length + 1,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 9. describe_schema                                                 */
/* ------------------------------------------------------------------ */

const describe_schema = tool({
  description:
    "AI が読めるテーブル（カタログ）の一覧（テーブル名と日本語説明。トークン節約のため列と件数は返さない）、" +
    "または table を指定すると1テーブルの列定義を返す。run_sql を書く前にまずこれで構造を確認する。" +
    "件数が要るときは run_sql の count(*) を使う。",
  inputSchema: z.object({
    table: z.string().optional().describe("列定義を見たいテーブル名"),
  }),
  execute: async ({ table }) => {
    const t0 = performance.now();
    if (table) {
      const [t] = await listTables({ catalogOnly: true, only: table });
      if (!t) {
        const all = await listTables({ catalogOnly: true, counts: false });
        return makeResult({
          tool: "describe_schema",
          tables: [],
          data: { error: `テーブル ${table} は存在しない（または AI からは読めない）`, available: all.map((x) => x.name) },
          rowCount: 0,
          elapsedMs: performance.now() - t0,
        });
      }
      return makeResult({
        tool: "describe_schema",
        tables: [table],
        data: {
          table: t.name,
          origin: SCHEMA_META[TABLE_ORIGIN[t.name] ?? "main"],
          rowCount: t.rowCount,
          description: TABLE_META[t.name],
          columns: t.columns,
        },
        rowCount: t.columns.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const tables = await listTables({ catalogOnly: true, counts: false });
    const list = tables.map((t) => ({
      name: t.name,
      origin: TABLE_ORIGIN[t.name] ?? "main",
      description: TABLE_META[t.name] ?? "",
    }));
    return makeResult({
      tool: "describe_schema",
      tables: [],
      data: { tables: list },
      rowCount: list.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 10. run_sql（第2層のフォールバック）                                  */
/* ------------------------------------------------------------------ */

const KNOWN_TABLES = new Set(Object.keys(TABLE_ORIGIN));

/**
 * SQL文に出てくる既知のテーブル名を拾う。
 *
 * FROM/JOIN の直後だけを見ると `FROM measurements m, sites s` のようなカンマ結合で
 * sites を取りこぼし、その注記（zone / municipality）が落ちる。注記の取りこぼしは
 * この設計が防ごうとしている当のものなので、識別子として出てくる既知テーブル名は
 * 位置を問わず全部拾う。多めに拾って注記が1つ余分に出るのは害が無く、
 * 落とす方だけが危ない、という非対称性に合わせている。
 */
function extractTableNames(sql: string): string[] {
  const found = new Set<string>();
  const re = /[a-zA-Z_][a-zA-Z0-9_]*/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(sql))) {
    if (KNOWN_TABLES.has(m[0])) found.add(m[0]);
  }
  return [...found];
}

const run_sql = tool({
  description:
    "任意の SELECT/WITH/EXPLAIN 文を D1 に対して実行する。第2層のフォールバックであり、意図ツール" +
    "（list_catalog/get_timeseries/get_seasonality/get_sites/get_biota_trend/get_redlist/get_overview）" +
    "で答えられないときだけ使う。行数は最大200・応答は最大24KBに切り詰められる。カタログ外のテーブルは読めない。" +
    "集計は可能な限り summary_*・registry 表を使うこと。",
  inputSchema: z.object({
    sql: z.string().describe("SELECT/WITH/EXPLAINで始まる1文。セミコロンは末尾以外に書かない"),
  }),
  execute: async ({ sql }) => {
    const t0 = performance.now();
    const trimmed = sql.trim().replace(/;+\s*$/, "");
    const withLimit = /\blimit\s+\d+/i.test(trimmed) ? trimmed : `${trimmed} LIMIT 200`;
    try {
      const res = await runUserSql(withLimit, 200, { catalogOnly: true });
      return makeResult({
        tool: "run_sql",
        tables: extractTableNames(withLimit),
        sql: withLimit,
        data: { columns: res.columns, rows: res.rows },
        rowCount: res.rowCount,
        elapsedMs: res.elapsedMs,
      });
    } catch (e) {
      const message = e instanceof SqlError ? e.message : e instanceof Error ? e.message : String(e);
      return makeResult({
        tool: "run_sql",
        tables: extractTableNames(withLimit),
        sql: withLimit,
        data: { error: message },
        rowCount: 0,
        elapsedMs: performance.now() - t0,
      });
    }
  },
});

/* ------------------------------------------------------------------ */
/* get_edna                                                           */
/* ------------------------------------------------------------------ */

const get_edna = tool({
  description: EDNA_DESCRIPTION,
  inputSchema: ednaInputSchema,
  execute: async (input) => {
    const t0 = performance.now();
    const result = await queryEdna(await d1CubeDb(), input);
    const more = result.rows.length > result.limit;
    const rows = result.rows.slice(0, result.limit);
    const out = makeResult({
      tool: "get_edna",
      tables: ["edna_sites", "edna_reads"],
      caveats: caveatKeysForFacets(facetsForOccurrence({ places: ["grid01"], sourceIds: [EDNA_SOURCE_ID] })),
      data: { mode: result.mode, offset: result.offset, rows },
      rowCount: rows.length,
      elapsedMs: performance.now() - t0,
    });
    if (!more) return out;
    return {
      ...out,
      truncated: true,
      truncatedNote: `limit（${result.limit}）を超える行がある。offset を ${result.offset + result.limit} にして続きを取れる。${out.truncatedNote ?? ""}`,
    };
  },
});

export const aiTools = {
  list_catalog,
  get_timeseries,
  get_seasonality,
  get_sites,
  get_biota_trend,
  get_edna,
  get_redlist,
  get_overview,
  describe_schema,
  run_sql,
};
