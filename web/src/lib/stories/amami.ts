/**
 * 奄美の物語ページ（`/stories/amami`、Issue #105 §3）の読み出し。
 *
 * 章の構造（どの文書のどの行を図にするか）は `AMAMI_STORY` に宣言として置く。**数値は持たない**——
 * 数値・日付・注記の文面はすべて DB（cells・notes・documents・観測セル・土砂災害区域）から引く。
 * 画面専用の SQL は書かない（ADR-0014）。読み手は `docSeriesPoints`・`timeseries`・`docNotes`・
 * `documentsList`・`readRecordSet`・`countRecordsBy` で、MCP / AI と同じ層。
 */
import type { CubeDb } from "@/lib/cube/db";
import { docSeriesPoints, type DocSeriesPoint } from "@/lib/cube/documents";
import { timeseries } from "@/lib/cube/timeseries";
import { docNotes, documentsList, type DocNote, type DocumentRow } from "@/lib/records";

/* ------------------------------------------------------------------ */
/* 宣言（章の構造。数値は持たない）                                        */
/* ------------------------------------------------------------------ */

export const AMAMI_STORY = {
  /** 物語は奄美の話なので、地域切替の外で固定。 */
  region: "jp-46",
  mongoose: {
    docId: "moe_mongoose_catch_h12r4",
    tableId: "p1_t1",
    totalRow: "総捕獲頭数",
    cpueRow: "わな捕獲|CPUE",
    /** 必ず出す注記（本文に含まれる語で選ぶ。無ければ例外を投げ、静かに欠けさせない）。 */
    requiredNotes: [
      { key: "unreleasedTables", match: "2023年度以降の数表" },
      { key: "year2000", match: "2000年度はわな日" },
      { key: "totalCpue", match: "0.616" },
      { key: "cpue2018", match: "0.0004" },
    ],
    declarationDocId: "moe_mongoose_eradication_declaration_2024",
    /** 根絶宣言の3つ（日付・確率・図の差し替え）を含む注記。 */
    declarationNotes: [
      { key: "declared", match: "根絶に達した" },
      { key: "probability", match: "HBM" },
      { key: "replaced", match: "図2" },
    ],
  },
  rain: {
    variableId: "common:variable:weather.precipitation",
    siteId: "jma_stations_amami__jma_47909",
    sourceId: "jma_daily_nase",
    from: "2010-10-10",
    to: "2010-10-31",
    /** 豪雨期間の帯（鹿大 表-2 の連続雨量の期間）。 */
    band: { from: "2010-10-18", to: "2010-10-21" },
    sumStat: "sum",
    hourStat: "max_1h",
    notes: {
      definitionChange: { docId: "kagoshima_univ_amami_gouu_2012", kind: "definition_change" },
      stationOwner: { docId: "kagoshima_univ_amami_gouu_2012", match: "鹿児島県の観測所" },
    },
    damage: {
      items: [
        { key: "death", label: "死者" },
        { key: "house", label: "全半壊の住家" },
        { key: "above", label: "床上浸水" },
        { key: "below", label: "床下浸水" },
      ],
      /** 出典ごとに別の列。合算せず、どれかに寄せない。`cells` は足し合わせるセル（全壊＋半壊のような内訳）。 */
      sources: [
        {
          key: "kyoto",
          docId: "dpri_amami_gouu_sokuho_2011",
          label: "京大 災害調査速報",
          cells: {
            death: [{ table: "p1_text_damage", row: "死者", col: "値" }],
            house: [{ table: "p1_text_damage", row: "全壊・半壊の住家", col: "値" }],
            above: [{ table: "p2_text_flood", row: "床上浸水", col: "値" }],
            below: [{ table: "p2_text_flood", row: "床下浸水", col: "値" }],
          },
          noteMatch: "全壊・半壊485棟",
        },
        {
          key: "kagoshimaPref",
          docId: "kagoshima_univ_amami_gouu_2012",
          label: "鹿大報告書 県の報告（p17）",
          cells: {
            death: [{ table: "p17_t1", row: "死者", col: "合計" }],
            house: [
              { table: "p17_t1", row: "住家全壊", col: "合計" },
              { table: "p17_t1", row: "住家半壊", col: "合計" },
            ],
            above: [{ table: "p17_t1", row: "床上浸水", col: "合計" }],
            below: [{ table: "p17_t1", row: "床下浸水", col: "合計" }],
          },
          noteMatch: "市町村の内訳は括弧書き",
        },
        {
          key: "kagoshimaLit",
          docId: "kagoshima_univ_amami_gouu_2012",
          label: "鹿大報告書 文献（p6）",
          cells: {
            death: [
              { table: "p6_text", row: "浸水による死者", col: "値" },
              { table: "p6_text", row: "崖崩れによる死者", col: "値" },
            ],
            house: [{ table: "p6_text", row: "全半壊の建物", col: "値" }],
            above: [{ table: "p6_text", row: "床上浸水", col: "値" }],
            below: [{ table: "p6_text", row: "床下浸水", col: "値" }],
          },
          noteMatch: "565棟",
        },
      ],
    },
    chisui: {
      docIds: ["bodik_460001_amami_ryuiki_chisui_2022", "kagoshima_amami_ryuiki_chisui_10p_2023"],
      cellsDocId: "kagoshima_amami_ryuiki_chisui_10p_2023",
      dams: ["大和ダム", "大川ダム"],
      /** 表に出す項目（割合の列は出さない）。 */
      cols: ["有効貯水容量", "洪水調節容量", "洪水調節可能容量", "水害対策に使える容量", "有効貯水量", "うち洪水調節可能容量"],
    },
  },
  hazard: {
    set: "hazard_zones",
    groupBy: ["municipality_ja", "phenomenon_ja", "zone_kind_ja"],
    /** 区分の表示順（この語を含む区分は後ろ）。 */
    specialKindMatch: "特別",
    rivers: {
      docId: "dpri_amami_gouu_sokuho_2011",
      table: "p2_text_flood",
      total: "二級河川の数（奄美大島）",
      flooded: "氾濫した二級河川",
    },
    /** 地図への導線（ページ内に1つ）。 */
    mapHref: "/map?region=jp-46&layers=hazard",
  },
  /** 各章末に出す出典の文書。 */
  docs: {
    mongoose: ["moe_mongoose_catch_h12r4", "moe_mongoose_eradication_declaration_2024"],
    rain: ["dpri_amami_gouu_sokuho_2011", "kagoshima_univ_amami_gouu_2012", "bodik_460001_amami_ryuiki_chisui_2022", "kagoshima_amami_ryuiki_chisui_10p_2023"],
    hazard: ["dpri_amami_gouu_sokuho_2011"],
  },
} as const;

/* ------------------------------------------------------------------ */
/* 共通                                                                 */
/* ------------------------------------------------------------------ */

export interface StoryDoc {
  docId: string;
  title: string | null;
  publisher: string | null;
  url: string | null;
  license: string | null;
}

function docMeta(all: readonly DocumentRow[], ids: readonly string[]): StoryDoc[] {
  const byId = new Map(all.map((d) => [d.doc_id, d]));
  return ids.map((id) => {
    const d = byId.get(id);
    if (!d) throw new Error(`物語の出典の文書が documents に無い: ${id}`);
    return { docId: d.doc_id, title: d.title, publisher: d.publisher, url: d.url, license: d.license };
  });
}

/** 注記の本文（`text`）から `match` を含むものを選ぶ。無い・空なら例外（静かに欠けさせない）。 */
export function pickNote(notes: readonly DocNote[], match: string, where: string): string {
  const n = notes.find((x) => (x.text ?? "").includes(match));
  const text = n?.text?.trim();
  if (!text) throw new Error(`必須の注記が無い（${where}: 「${match}」を含む注記）`);
  return text;
}

export interface DocCell {
  table_id: string | null;
  row_key: string | null;
  col_key: string | null;
  value: string | null;
  unit: string | null;
  page_no: number | null;
}

/**
 * 1 文書のセル（`superseded = 0`）。契約（§1.1）は `readRecordSet(db, "document_cells", { eq: doc_id })`。
 * 担当1の `document_cells` が入るまでの仮実装（同じ列・同じ条件を `cells` から直接読む）。
 */
// TODO(#105): 担当1の document_cells をマージしたら readRecordSet に置き換える。
async function readDocCells(db: CubeDb, docId: string): Promise<DocCell[]> {
  return db.all<DocCell>(
    "SELECT table_id, row_key, col_key, value, unit, page_no FROM cells WHERE doc_id = ? AND superseded = 0 ORDER BY page_no, id",
    [docId],
  ) as Promise<DocCell[]>;
}

function num(v: string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
}

function cellValue(cells: readonly DocCell[], table: string, row: string, col: string): { value: number; unit: string | null } | null {
  const c = cells.find((x) => x.table_id === table && x.row_key === row && x.col_key === col);
  const v = num(c?.value);
  return c && v !== null ? { value: v, unit: c.unit } : null;
}

/* ------------------------------------------------------------------ */
/* 章1: マングース                                                        */
/* ------------------------------------------------------------------ */

export interface MongooseStory {
  total: DocSeriesPoint[];
  cpue: DocSeriesPoint[];
  notes: { key: string; text: string }[];
  declaration: { key: string; text: string }[];
  docs: StoryDoc[];
}

export async function loadMongoose(db: CubeDb): Promise<MongooseStory> {
  const c = AMAMI_STORY.mongoose;
  const [total, cpue, notes, declNotes, docs] = await Promise.all([
    docSeriesPoints(db, c.docId, c.tableId, c.totalRow),
    docSeriesPoints(db, c.docId, c.tableId, c.cpueRow),
    docNotes(db, c.docId),
    docNotes(db, c.declarationDocId),
    documentsList(db),
  ]);
  return {
    total,
    cpue,
    notes: c.requiredNotes.map((r) => ({ key: r.key, text: pickNote(notes, r.match, c.docId) })),
    declaration: c.declarationNotes.map((r) => ({ key: r.key, text: pickNote(declNotes, r.match, c.declarationDocId) })),
    docs: docMeta(docs, AMAMI_STORY.docs.mongoose),
  };
}

/* ------------------------------------------------------------------ */
/* 章2: 2010年奄美豪雨                                                    */
/* ------------------------------------------------------------------ */

export interface RainDay {
  date: string;
  /** 日合計（mm）。 */
  mm: number;
}

export interface DamageColumn {
  key: string;
  label: string;
  docId: string;
  /** 項目キー → 値（出典に無い・空欄は null）。 */
  values: Record<string, { value: number; unit: string | null } | null>;
  note: string;
}

export interface DamageTable {
  items: { key: string; label: string }[];
  columns: DamageColumn[];
  /** 全列で値が一致している項目（確定している数）。 */
  agreed: { key: string; label: string; value: number; unit: string | null }[];
}

export interface DamControl {
  dam: string;
  rows: { col: string; value: number; unit: string | null }[];
}

export interface RainStory {
  days: RainDay[];
  /** 日合計が最大の日と、その日の最大1時間雨量（引けなければ null）。 */
  peak: { date: string; mm: number; maxHourMm: number | null } | null;
  unit: string | null;
  band: { from: string; to: string };
  rainNotes: { definitionChange: string; stationOwner: string };
  damage: DamageTable;
  chisui: { docs: StoryDoc[]; dams: DamControl[] };
  docs: StoryDoc[];
}

/** 名瀬の日雨量（合計）。`value` は検閲を考えない（降水量に定量下限は無い）ので lod/zero の同値を使う。 */
export async function loadRainDays(db: CubeDb): Promise<{ days: RainDay[]; maxHour: Map<string, number>; unit: string | null }> {
  const r = AMAMI_STORY.rain;
  const base = {
    variableId: r.variableId,
    scope: { type: "site" as const, siteId: r.siteId },
    grain: "day" as const,
    from: r.from,
    to: r.to,
    sourceIds: [r.sourceId],
    region: AMAMI_STORY.region,
  };
  const [sum, hour] = await Promise.all([
    timeseries(db, { ...base, stat: r.sumStat }),
    timeseries(db, { ...base, stat: r.hourStat }),
  ]);
  const toDays = (pts: unknown[]) =>
    (pts as { periodStart: string; value: number | null; valueLod: number | null; valueZero: number | null }[])
      .map((p) => ({ date: p.periodStart, mm: p.value ?? p.valueLod ?? p.valueZero }))
      .filter((p): p is RainDay => p.mm !== null && p.mm !== undefined);
  return {
    days: toDays(sum.points),
    maxHour: new Map(toDays(hour.points).map((d) => [d.date, d.mm])),
    unit: sum.unit,
  };
}

async function loadDamage(db: CubeDb): Promise<DamageTable> {
  const d = AMAMI_STORY.rain.damage;
  const byDoc = new Map<string, DocCell[]>();
  const notesByDoc = new Map<string, DocNote[]>();
  for (const id of new Set(d.sources.map((s) => s.docId))) {
    byDoc.set(id, await readDocCells(db, id));
    notesByDoc.set(id, await docNotes(db, id));
  }
  const columns: DamageColumn[] = d.sources.map((s) => {
    const cells = byDoc.get(s.docId)!;
    const values: DamageColumn["values"] = {};
    for (const it of d.items) {
      const parts = ((s.cells as Record<string, readonly { table: string; row: string; col: string }[]>)[it.key] ?? []).map((p) =>
        cellValue(cells, p.table, p.row, p.col),
      );
      // 内訳の足し算は、全部の部分が揃っているときだけ（欠けた部分を 0 とみなさない）。
      values[it.key] = parts.length > 0 && parts.every((p) => p !== null) ? { value: parts.reduce((a, p) => a + p!.value, 0), unit: parts[0]!.unit } : null;
    }
    return { key: s.key, label: s.label, docId: s.docId, values, note: pickNote(notesByDoc.get(s.docId)!, s.noteMatch, s.docId) };
  });
  const agreed = d.items.flatMap((it) => {
    const vs = columns.map((c) => c.values[it.key]);
    if (vs.some((v) => v === null)) return [];
    const first = vs[0]!.value;
    return vs.every((v) => v!.value === first) ? [{ key: it.key, label: it.label, value: first, unit: vs[0]!.unit }] : [];
  });
  return { items: [...d.items], columns, agreed };
}

async function loadChisui(db: CubeDb, docs: readonly DocumentRow[]): Promise<RainStory["chisui"]> {
  const c = AMAMI_STORY.rain.chisui;
  const cells = await readDocCells(db, c.cellsDocId);
  const dams = c.dams.map((dam) => ({
    dam: dam as string,
    rows: cells
      .filter((x) => x.row_key === dam && x.col_key !== null && (c.cols as readonly string[]).includes(x.col_key) && num(x.value) !== null)
      .map((x) => ({ col: x.col_key!, value: num(x.value)!, unit: x.unit })),
  }));
  return { docs: docMeta(docs, c.docIds), dams };
}

export async function loadRain(db: CubeDb): Promise<RainStory> {
  const r = AMAMI_STORY.rain;
  const [{ days, maxHour, unit }, damage, docs, defNotes, ownerNotes] = await Promise.all([
    loadRainDays(db),
    loadDamage(db),
    documentsList(db),
    docNotes(db, r.notes.definitionChange.docId),
    docNotes(db, r.notes.stationOwner.docId),
  ]);
  const top = days.reduce<RainDay | null>((a, d) => (a === null || d.mm > a.mm ? d : a), null);
  const defText = defNotes.find((n) => n.kind === r.notes.definitionChange.kind)?.text?.trim();
  if (!defText) throw new Error(`必須の注記が無い（${r.notes.definitionChange.docId}: kind=${r.notes.definitionChange.kind}）`);
  return {
    days,
    peak: top ? { date: top.date, mm: top.mm, maxHourMm: maxHour.get(top.date) ?? null } : null,
    unit,
    band: r.band,
    rainNotes: { definitionChange: defText, stationOwner: pickNote(ownerNotes, r.notes.stationOwner.match, r.notes.stationOwner.docId) },
    damage,
    chisui: await loadChisui(db, docs),
    docs: docMeta(docs, AMAMI_STORY.docs.rain),
  };
}

/* ------------------------------------------------------------------ */
/* 章3: 島の川と土砂災害                                                  */
/* ------------------------------------------------------------------ */

export interface HazardKindPanel {
  kind: string;
  special: boolean;
  /** 市町村（合計の多い順）× 現象。 */
  municipalities: { name: string; byPhenomenon: Record<string, number>; total: number }[];
  phenomena: string[];
  total: number;
}

export interface HazardStory {
  panels: HazardKindPanel[];
  /** 区分をまたいだ総数は棒にしない。見出しの事実としてだけ返す。 */
  total: number;
  rivers: { total: { value: number; unit: string | null } | null; flooded: { value: number; unit: string | null } | null };
  docs: StoryDoc[];
  mapHref: string;
}

type CountRow = { municipality_ja: string | null; phenomenon_ja: string | null; zone_kind_ja: string | null; n: number };

/**
 * 市町村 × 現象 × 区分の件数。契約（§1.1）は `countRecordsBy(db, "hazard_zones", groupBy)`。
 * 担当1の関数が入るまでの仮実装（同じ許可リストの列で、件数のみ）。
 */
// TODO(#105): 担当1の countRecordsBy をマージしたら置き換える。
async function countHazard(db: CubeDb): Promise<CountRow[]> {
  return db.all<CountRow>(
    "SELECT municipality_ja, phenomenon_ja, zone_kind_ja, COUNT(*) AS n FROM hazard_zones GROUP BY municipality_ja, phenomenon_ja, zone_kind_ja",
    [],
  ) as Promise<CountRow[]>;
}

export function buildHazardPanels(rows: readonly CountRow[], specialMatch: string): HazardKindPanel[] {
  const kinds = [...new Set(rows.map((r) => r.zone_kind_ja ?? ""))];
  const panels = kinds.map((kind) => {
    const mine = rows.filter((r) => (r.zone_kind_ja ?? "") === kind);
    const phenomena = [...new Set(mine.map((r) => r.phenomenon_ja ?? ""))];
    const muni = new Map<string, Record<string, number>>();
    for (const r of mine) {
      const m = muni.get(r.municipality_ja ?? "") ?? {};
      m[r.phenomenon_ja ?? ""] = (m[r.phenomenon_ja ?? ""] ?? 0) + r.n;
      muni.set(r.municipality_ja ?? "", m);
    }
    const municipalities = [...muni.entries()]
      .map(([name, byPhenomenon]) => ({ name, byPhenomenon, total: Object.values(byPhenomenon).reduce((a, b) => a + b, 0) }))
      .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name, "ja"));
    return { kind, special: kind.includes(specialMatch), municipalities, phenomena, total: municipalities.reduce((a, m) => a + m.total, 0) };
  });
  return panels.sort((a, b) => Number(a.special) - Number(b.special));
}

export async function loadHazard(db: CubeDb): Promise<HazardStory> {
  const h = AMAMI_STORY.hazard;
  const [rows, riverCells, docs] = await Promise.all([countHazard(db), readDocCells(db, h.rivers.docId), documentsList(db)]);
  const panels = buildHazardPanels(rows, h.specialKindMatch);
  return {
    panels,
    total: rows.reduce((a, r) => a + r.n, 0),
    rivers: {
      total: cellValue(riverCells, h.rivers.table, h.rivers.total, "値"),
      flooded: cellValue(riverCells, h.rivers.table, h.rivers.flooded, "値"),
    },
    docs: docMeta(docs, AMAMI_STORY.docs.hazard),
    mapHref: h.mapHref,
  };
}
