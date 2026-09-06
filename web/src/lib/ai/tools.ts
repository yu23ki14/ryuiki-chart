import "server-only";
import { z } from "zod";
import { tool } from "ai";
import { caveatKeysForTables } from "./caveats";
import { listTables, runUserSql, SqlError } from "@/lib/db";
import { TABLE_META, SCHEMA_META, TABLE_ORIGIN } from "@/lib/table-meta";
import { ZONE_INFO } from "@/lib/domain";
import { resolveVariableInfo, type ResolvedVariableInfo } from "@/lib/registry/lookup";
import {
  listSites,
  getSite,
  siteVariables,
  listWaterBodies,
  sitesInWaterBody,
  waterBodiesForVariable,
  variableCatalog,
  yearSeries,
  monthSeries,
  daySeries,
  zoneSeries,
  zoneClimatology,
  climatology,
  watershedRollup,
  overviewStats,
  taxonGroupYears,
  effortYears,
  speciesShareTrend,
  speciesYears,
  speciesMonths,
  redlistFlows,
  redlistSpecies,
  redlistSummary,
  qualityTotals,
  qualityMonthly,
  interventions,
  decisions,
  observerStats,
} from "@/lib/queries";

/**
 * 意図レベルのツール10個。中身は queries.ts の合成で、新しい SQL はほぼ書かない
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
 * ツール結果に載せる registry の情報（variable_id / unit / higher_is_worse）。
 *
 * 出典表記（`variable` 引数・`variableCatalog()` の行の `variable` 列）は出典ごとに
 * 揺れる（ADR-0010: OX / Ox(ppm) / 光化学オキシダント_日平均 が同じ量）。ここで
 * レジストリの正準 `variableId` を引いて添えることで、モデルが名前の文字列一致ではなく
 * `variableId` の一致で「同じ指標か」を判断できるようにする（system prompt 側の説明と対）。
 * 未登録（レジストリにまだ無い出典表記）のときは null を返す（推測で埋めない）。
 */
function registryInfo(
  variable: string,
  sourceScope: "measurements" | "sensor_timeseries" = "measurements",
): ResolvedVariableInfo | null {
  return resolveVariableInfo(variable, sourceScope) ?? null;
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
}

function toRegistryEntry(info: ResolvedVariableInfo): RegistryEntry {
  return {
    nameJa: info.nameJa,
    unit: info.unit,
    higherIsWorse: info.higherIsWorse,
    descriptionJa: info.descriptionJa,
  };
}

/**
 * レジストリ情報を「行には variableId だけ」「本体は1つの共有辞書 registry」に分けて
 * 複数行にまとめて添える。
 *
 * レビュー指摘: 以前は行ごとに `registry: registryInfo(...)` をインライン展開しており、
 * `nameJa`/`descriptionJa`/`unit`/`code` が行の数だけ重複していた（実測:
 * list_catalog(what='variables') が 9,084 -> 20,333 バイトに膨張。BYTE_BUDGET
 * 24KB の85%を占め、`fitToBudget` の間引きが `var_catalog` の行から先に始まる
 * 状態だった）。variableId が同じなら registry の中身も同じなので、行ごとに
 * 持たせる必要が無い。
 */
function withRegistry<T>(
  rows: readonly T[],
  variableOf: (row: T) => string,
  sourceScope: "measurements" | "sensor_timeseries" = "measurements",
): { rows: (T & { variableId: string | null })[]; registry: Record<string, RegistryEntry> } {
  const registry: Record<string, RegistryEntry> = {};
  const withIds = rows.map((row) => {
    const info = registryInfo(variableOf(row), sourceScope);
    if (info) registry[info.variableId] = toRegistryEntry(info);
    return { ...row, variableId: info?.variableId ?? null };
  });
  return { rows: withIds, registry };
}

/**
 * `withRegistry` の単一 variable 版（get_timeseries / get_seasonality のように
 * 行の配列ではなく1つの variable だけを扱うツール用）。形を揃えることで、
 * モデル・システムプロンプトが「ツール結果の registry[variableId] を見る」という
 * 単一の説明で済むようにする。
 */
function singleRegistry(
  variable: string,
  sourceScope: "measurements" | "sensor_timeseries" = "measurements",
): { variableId: string | null; registry: Record<string, RegistryEntry> } {
  const info = registryInfo(variable, sourceScope);
  return {
    variableId: info?.variableId ?? null,
    registry: info ? { [info.variableId]: toRegistryEntry(info) } : {},
  };
}

function makeResult<T>(opts: {
  tool: string;
  tables: string[];
  data: T;
  rowCount: number;
  elapsedMs: number;
  sql?: string;
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
    caveats: caveatKeysForTables(opts.tables),
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
    variable: z
      .string()
      .optional()
      .describe("what='waters' のとき、この項目のデータを実際に持つ水域だけに絞り込む（項目名は variables の結果から取る）"),
  }),
  execute: async ({ what, variable }) => {
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
    if (what === "waters") {
      const rows = variable ? await waterBodiesForVariable(variable) : await listWaterBodies();
      return makeResult({
        tool: "list_catalog",
        tables: ["sites", "site_var"],
        data: { waters: rows },
        rowCount: rows.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const rows = await variableCatalog();
    const { rows: variables, registry } = withRegistry(rows, (r) => r.variable);
    return makeResult({
      tool: "list_catalog",
      tables: ["var_catalog"],
      data: { variables, registry },
      rowCount: variables.length,
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

/**
 * var_catalog を1回だけ引いて、kind と単位をまとめて決める。
 *
 * kind 未指定なら実在する方（daily 優先）を選ぶ。単位は meas_month / meas_daily の行には
 * 入っていない（monthSeries / daySeries が select していない）ので、ここで拾わないと
 * 月次・日次のグラフだけ縦軸の単位が消える。水質の図で mg/L が出ないのは読み手に厳しい。
 */
async function resolveVariable(
  variable: string,
  kind?: "daily" | "annual",
): Promise<{ kind: "daily" | "annual"; unit: string | null }> {
  const row = (await variableCatalog()).find((c) => c.variable === variable);
  const resolved = kind ?? (row && row.n_daily > 0 ? "daily" : row && row.n_annual > 0 ? "annual" : "daily");
  return { kind: resolved, unit: row?.unit ?? null };
}

const get_timeseries = tool({
  description:
    "ある測定項目の時系列を取る。scope で「水域の中の地点ごと」「1地点」「ゾーン平均」のどれで見るかを選ぶ。grain で年次/月次/日次を選ぶ。",
  inputSchema: z.object({
    variable: z.string().describe("測定項目名（list_catalog(what='variables') の variable の値そのまま）"),
    scope: scopeSchema,
    grain: z.enum(["year", "month", "day"]).describe("時間の粒度。zoneスコープはyearのみ意味を持つ"),
    kind: z
      .enum(["daily", "annual"])
      .optional()
      .describe("検体値由来(daily)か年度集計値由来(annual)か。省略時はデータが実在する方を自動選択する"),
    from: z
      .string()
      .optional()
      .describe("grain='day' のときの開始日 YYYY-MM-DD。日次は点が多く、範囲を絞らないと間引かれる"),
    to: z.string().optional().describe("grain='day' のときの終了日 YYYY-MM-DD"),
  }),
  execute: async ({ variable, scope, grain, kind, from, to }) => {
    const t0 = performance.now();
    const { kind: resolvedKind, unit } = await resolveVariable(variable, kind);
    const { variableId, registry } = singleRegistry(variable);
    const tables = new Set<string>(["var_catalog"]);

    if (scope.type === "zone") {
      const points = await zoneSeries(variable, resolvedKind);
      tables.add("zone_year");
      return makeResult({
        tool: "get_timeseries",
        tables: [...tables],
        data: { scope, grain: "year", kind: resolvedKind, unit, variableId, registry, points },
        rowCount: points.length,
        elapsedMs: performance.now() - t0,
      });
    }

    // site スコープは site_id 直指定で meas_* だけを引く（sites テーブルには触れない）。
    // water スコープだけ、対象地点を求めるのに sites/site_var を実際に引く。
    let sites;
    let siteIds: string[];
    if (scope.type === "site") {
      siteIds = [scope.siteId];
    } else {
      tables.add("sites");
      tables.add("site_var");
      sites = await sitesInWaterBody(scope.name);
      siteIds = sites.map((s) => s.site_id);
    }

    if (grain === "year") {
      const points = await yearSeries(variable, siteIds, resolvedKind);
      tables.add("meas_year");
      return makeResult({
        tool: "get_timeseries",
        tables: [...tables],
        data: { scope, sites, grain, kind: resolvedKind, unit, variableId, registry, points },
        rowCount: points.length,
        elapsedMs: performance.now() - t0,
      });
    }
    if (grain === "month") {
      const points = await monthSeries(variable, siteIds);
      tables.add("meas_month");
      return makeResult({
        tool: "get_timeseries",
        tables: [...tables],
        data: { scope, sites, grain, unit, variableId, registry, points },
        rowCount: points.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const points = await daySeries(variable, siteIds, from, to);
    tables.add("meas_daily");
    return makeResult({
      tool: "get_timeseries",
      tables: [...tables],
      data: { scope, sites, grain, from, to, unit, variableId, registry, points },
      rowCount: points.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 3. get_seasonality                                                 */
/* ------------------------------------------------------------------ */

const get_seasonality = tool({
  description: "ある測定項目の季節性（月ごとの平均）を、全体とゾーン別の両方で取る。",
  inputSchema: z.object({
    variable: z.string().describe("測定項目名"),
  }),
  execute: async ({ variable }) => {
    const t0 = performance.now();
    const [overall, byZone] = await Promise.all([climatology(variable), zoneClimatology(variable)]);
    const { variableId, registry } = singleRegistry(variable);
    return makeResult({
      tool: "get_seasonality",
      tables: ["meas_clim", "zone_clim"],
      data: { variable, variableId, registry, overall, byZone },
      rowCount: overall.length + byZone.length,
      elapsedMs: performance.now() - t0,
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
    if (siteId) {
      const [site, siteVars] = await Promise.all([getSite(siteId), siteVariables(siteId)]);
      const { rows: variables, registry } = withRegistry(siteVars, (v) => v.variable);
      return makeResult({
        tool: "get_sites",
        tables: ["sites", "watershed_meta", "site_var"],
        data: { site: site ?? null, variables, registry },
        rowCount: variables.length,
        elapsedMs: performance.now() - t0,
      });
    }
    let rows = await listSites();
    if (query) {
      const q = query.toLowerCase();
      rows = rows.filter((s) => (s.name ?? "").toLowerCase().includes(q));
    }
    if (zone != null) rows = rows.filter((s) => s.zone === zone);
    const matched = rows.length;
    const limited = rows.slice(0, limit ?? 20);
    return makeResult({
      tool: "get_sites",
      tables: ["sites", "watershed_meta", "site_var"],
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
      binoms: z.array(z.string()).min(1).describe("学名（2語、例: Plecoglossus altivelis）の配列"),
    }),
  ]),
  execute: async (input) => {
    const t0 = performance.now();
    if (input.mode === "groups") {
      const [groups, effort] = await Promise.all([taxonGroupYears(), effortYears()]);
      return makeResult({
        tool: "get_biota_trend",
        tables: ["org_group_year", "effort_year"],
        data: { mode: "groups", groups, effort },
        rowCount: groups.length + effort.length,
        elapsedMs: performance.now() - t0,
      });
    }
    if (input.mode === "share") {
      const { group, periodA, periodB } = input;
      const rows = await speciesShareTrend(group, periodA.from, periodA.to, periodB.from, periodB.to);
      return makeResult({
        tool: "get_biota_trend",
        tables: ["species_year2", "species2"],
        data: { mode: "share", group, periodA, periodB, rows },
        rowCount: rows.length,
        elapsedMs: performance.now() - t0,
      });
    }
    const { binoms } = input;
    const [years, months] = await Promise.all([speciesYears(binoms), speciesMonths(binoms)]);
    return makeResult({
      tool: "get_biota_trend",
      tables: ["species_year2", "species_month"],
      data: { mode: "species", binoms, years, months },
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
    const [summary, flows, species] = await Promise.all([
      redlistSummary(),
      redlistFlows(year, group),
      redlistSpecies(year, direction, group, 300),
    ]);
    return makeResult({
      tool: "get_redlist",
      tables: ["redlist_change"],
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
  description: "アプリ全体の概況（地点数・測定値数・生物記録数などの総数）と、流域ごとのロールアップ上位N件を取る。",
  inputSchema: z.object({
    limit: z.number().int().min(1).max(50).optional().describe("流域ロールアップの件数上限（既定10、生物記録数の多い順）"),
  }),
  execute: async ({ limit }) => {
    const t0 = performance.now();
    const [stats, rollupAll] = await Promise.all([overviewStats(), watershedRollup()]);
    const rollup = [...rollupAll].sort((a, b) => (b.org_n ?? 0) - (a.org_n ?? 0)).slice(0, limit ?? 10);
    return makeResult({
      tool: "get_overview",
      tables: [
        "sites",
        "measurements",
        "organism_records",
        "species2",
        "events",
        "sensor_timeseries",
        "source_registry",
        "watershed_meta",
        "var_catalog",
        "watershed_rollup",
      ],
      data: { stats, watersheds: rollup },
      rowCount: rollup.length + 1,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 8. get_quality_progress                                            */
/* ------------------------------------------------------------------ */

const get_quality_progress = tool({
  description:
    "データ品質パイプラインの進捗（暫定→検証済→公開済）、現場の観測体制、介入・意思決定の記録を見る。" +
    "これらはすべて合成データ（デモ用に生成したもの）であることに必ず注意する。",
  inputSchema: z.object({}),
  execute: async () => {
    const t0 = performance.now();
    const [totals, monthly, iv, dec, observers] = await Promise.all([
      qualityTotals(),
      qualityMonthly(),
      interventions(),
      decisions(),
      observerStats(),
    ]);
    return makeResult({
      tool: "get_quality_progress",
      tables: ["quality_transitions", "quality_monthly", "interventions", "decisions", "observers", "event_observers"],
      data: { totals, monthly, interventions: iv, decisions: dec, observers },
      rowCount: monthly.length + iv.length + dec.length + observers.length,
      elapsedMs: performance.now() - t0,
    });
  },
});

/* ------------------------------------------------------------------ */
/* 9. describe_schema                                                 */
/* ------------------------------------------------------------------ */

const describe_schema = tool({
  description:
    "D1に入っている全56テーブルの一覧（テーブル名と日本語説明。トークン節約のため列は返さない）、" +
    "または table を指定すると1テーブルの列定義を返す。run_sql を書く前にまずこれで構造を確認する。",
  inputSchema: z.object({
    table: z.string().optional().describe("列定義を見たいテーブル名"),
  }),
  execute: async ({ table }) => {
    const t0 = performance.now();
    const tables = await listTables();
    if (table) {
      const t = tables.find((x) => x.name === table);
      if (!t) {
        return makeResult({
          tool: "describe_schema",
          tables: [],
          data: { error: `テーブル ${table} は存在しない`, available: tables.map((x) => x.name) },
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
    const list = tables.map((t) => ({
      name: t.name,
      rowCount: t.rowCount,
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
    "（list_catalog/get_timeseries/get_seasonality/get_sites/get_biota_trend/get_redlist/get_overview/get_quality_progress）" +
    "で答えられないときだけ使う。行数は最大200・応答は最大24KBに切り詰められる。集計は可能な限り derived 系テーブルを使うこと。",
  inputSchema: z.object({
    sql: z.string().describe("SELECT/WITH/EXPLAINで始まる1文。セミコロンは末尾以外に書かない"),
  }),
  execute: async ({ sql }) => {
    const t0 = performance.now();
    const trimmed = sql.trim().replace(/;+\s*$/, "");
    const withLimit = /\blimit\s+\d+/i.test(trimmed) ? trimmed : `${trimmed} LIMIT 200`;
    try {
      const res = await runUserSql(withLimit, 200);
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

export const aiTools = {
  list_catalog,
  get_timeseries,
  get_seasonality,
  get_sites,
  get_biota_trend,
  get_redlist,
  get_overview,
  get_quality_progress,
  describe_schema,
  run_sql,
};
