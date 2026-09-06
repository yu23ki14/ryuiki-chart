import { DATA_CAVEATS, BIOTA_CAVEATS, MUNICIPALITY_LABEL } from "@/lib/domain";

/**
 * ツールが触れたテーブル名から、該当する注記を決定論的に引く。
 * モデルに注意書きを書かせない（書かせると省略されうる）のがこのファイルの存在理由なので、
 * ここのマッピングは domain.ts に実在するキーだけを使い、推測で文言を足さない。
 *
 * server-only にしていないのは意図的。ツール結果には注記の「キー」だけを載せ（本文は
 * システムプロンプトが持っているのでモデルは二重に受け取らなくてよい）、本文への引き直しは
 * 証跡カード（クライアント）が caveatText でやる。import 元は domain.ts だけなので両側で使える。
 */

export interface CaveatRef {
  key: string;
  text: string;
}

function pick(...pairs: [string, string][]): CaveatRef[] {
  return pairs.map(([key, text]) => ({ key, text }));
}

/** sites.municipality の注記。domain.ts の MUNICIPALITY_LABEL 定義に添えられたコメントの文言をそのまま使う。 */
const SITES_CAVEATS: CaveatRef[] = [
  ...pick(["zone", DATA_CAVEATS.zone]),
  {
    key: "municipality",
    text:
      "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、" +
      `それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「${MUNICIPALITY_LABEL}」と呼ぶ。`,
  },
];

const MEASURE_CAVEATS = pick(
  ["measuredOn", DATA_CAVEATS.measuredOn],
  ["censored", DATA_CAVEATS.censored],
  ["duplicates", DATA_CAVEATS.duplicates],
);

const ORGANISM_CAVEATS = pick(
  ["organismSite", DATA_CAVEATS.organismSite],
  ["effort", DATA_CAVEATS.effort],
  ["regimes", BIOTA_CAVEATS.regimes],
  ["gbifCutoff", BIOTA_CAVEATS.gbifCutoff],
  ["share", BIOTA_CAVEATS.share],
);

const MESH_CAVEATS = pick(["share", BIOTA_CAVEATS.share], ["effort", DATA_CAVEATS.effort]);

const IAS_CAVEATS = pick(["isAlien", BIOTA_CAVEATS.isAlien]);

const SYNTHETIC_CAVEATS = pick(["synthetic", DATA_CAVEATS.synthetic]);

const MEASURE_TABLES = new Set([
  "measurements",
  "meas_year",
  "meas_month",
  "meas_daily",
  "meas_clim",
  "zone_year",
  "zone_clim",
  "var_catalog",
  "site_var",
]);

const ORGANISM_TABLES = new Set([
  "organism_records",
  "org_norm",
  "org_group_year",
  "org_watershed",
  "org_watershed_year",
  "species2",
  "species_year2",
  "species_month",
  "effort_year",
]);

const MESH_TABLES_EXTRA = new Set(["species_mesh_year"]);

/**
 * 合成データ（デモ用に生成したもの）を含むテーブル。最優先で必ず注記する。
 * レッドリスト（redlist_assessments / redlist_change / redlist_map）は
 * domain.ts に対応する注記キーが無いため、ここでは何も付けない（推測で足さない）。
 */
const SYNTHETIC_TABLES = new Set([
  "observers",
  "interventions",
  "decisions",
  "quality_transitions",
  "quality_monthly",
  "event_observers",
]);

export function caveatsForTables(tables: readonly string[]): CaveatRef[] {
  const seen = new Map<string, CaveatRef>();
  const add = (list: CaveatRef[]) => {
    for (const c of list) if (!seen.has(c.key)) seen.set(c.key, c);
  };

  // synthetic は最優先。他のどれよりも先に足しておく（重複は add 側で弾かれる）。
  if (tables.some((t) => SYNTHETIC_TABLES.has(t))) add(SYNTHETIC_CAVEATS);

  for (const t of tables) {
    if (t === "sites") add(SITES_CAVEATS);
    if (MEASURE_TABLES.has(t)) add(MEASURE_CAVEATS);
    if (ORGANISM_TABLES.has(t)) add(ORGANISM_CAVEATS);
    if (t.startsWith("mesh_") || MESH_TABLES_EXTRA.has(t)) add(MESH_CAVEATS);
    if (t === "ias_species") add(IAS_CAVEATS);
  }

  return [...seen.values()];
}

/** 全注記のキー -> 本文。証跡カード（クライアント）とシステムプロンプトの両方が引く。 */
export const CAVEAT_TEXT: Record<string, string> = Object.fromEntries(
  [...SITES_CAVEATS, ...MEASURE_CAVEATS, ...ORGANISM_CAVEATS, ...MESH_CAVEATS, ...IAS_CAVEATS, ...SYNTHETIC_CAVEATS].map(
    (c) => [c.key, c.text],
  ),
);

export function caveatText(key: string): string {
  return CAVEAT_TEXT[key] ?? key;
}

/**
 * ツール結果に載せるのはキーだけ。本文はシステムプロンプトが `[key] 本文` の形で持っているので、
 * モデルはキーから引ける。生物系は注記が5件あり、全ツール結果に全文を載せると
 * 1回あたり約1KB・5ステップで5KBの純粋な重複になるため。
 */
export function caveatKeysForTables(tables: readonly string[]): string[] {
  return caveatsForTables(tables).map((c) => c.key);
}
