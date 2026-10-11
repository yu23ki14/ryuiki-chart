import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { applyMigrations, wrapSqlite } from "@/lib/cube/__fixtures__/cube-fixture";
import type { CubeDb } from "@/lib/cube/db";
import { sqliteCubeDb } from "@/lib/cube/db-sqlite";
import { AMAMI_STORY, buildHazardPanels, loadHazard, loadMongoose, loadRain, loadRainDays, pickNote } from "./amami";

const REPO = path.resolve(__dirname, "../../../..");
const P = {
  v2: path.join(REPO, "data/db/v2.sqlite"),
  registry: path.join(REPO, "data/db/registry.sqlite"),
  ryuiki: path.join(REPO, "data/db/ryuiki.sqlite"),
  cells: path.join(REPO, "data/db/cells.sqlite"),
};
const haveReal = Object.values(P).every((p) => fs.existsSync(p));

describe.skipIf(!haveReal)("実データ（読み取り専用）: 受け入れの数", () => {
  let db: CubeDb & { close(): void };
  beforeAll(() => {
    db = sqliteCubeDb(P);
  });
  afterAll(() => db.close());

  it("マングース: CPUE 22 点・総捕獲 23 点。必須の注記が全部ある", async () => {
    const m = await loadMongoose(db);
    expect(m.cpue).toHaveLength(22);
    expect(m.total).toHaveLength(23);
    expect(m.notes.map((n) => n.key)).toEqual(AMAMI_STORY.mongoose.requiredNotes.map((n) => n.key));
    expect(m.declaration).toHaveLength(AMAMI_STORY.mongoose.declarationNotes.length);
    expect(m.docs.map((d) => d.url).every(Boolean)).toBe(true);
  });

  it("豪雨: 名瀬の日合計の最大は 622.0 mm、その日の最大1時間は 78.5 mm", async () => {
    const r = await loadRainDays(db);
    expect(r.days.find((d) => d.date === "2010-10-20")?.mm).toBe(622);
    expect(r.maxHour.get("2010-10-20")).toBe(78.5);
    const story = await loadRain(db);
    expect(story.peak).toEqual({ date: "2010-10-20", mm: 622, maxHourMm: 78.5 });
  });

  it("被害表: 死者は3出典とも 3。確定は死者だけ", async () => {
    const { damage, chisui } = await loadRain(db);
    expect(damage.columns).toHaveLength(3);
    for (const c of damage.columns) expect(c.values.death?.value).toBe(3);
    expect(damage.agreed.map((a) => [a.key, a.value])).toEqual([["death", 3]]);
    // 食い違う項目は、列ごとに別の値のまま（寄せない）
    expect(new Set(damage.columns.map((c) => c.values.house?.value)).size).toBe(3);
    expect(chisui.dams.map((d) => d.dam)).toEqual([...AMAMI_STORY.rain.chisui.dams]);
    expect(chisui.dams.every((d) => d.rows.length > 0)).toBe(true);
  });

  it("土砂災害: 警戒・特別警戒の2面、河川の数が引ける", async () => {
    const h = await loadHazard(db);
    expect(h.panels).toHaveLength(2);
    expect(h.panels[0].special).toBe(false);
    expect(h.panels[1].special).toBe(true);
    expect(h.panels.reduce((a, p) => a + p.total, 0)).toBe(h.total);
    expect(h.rivers.total?.value).toBeGreaterThan(0);
    expect(h.rivers.flooded?.value).toBeGreaterThan(0);
  });
});

describe("必須の注記が無いときは静かに欠けず例外を投げる", () => {
  let raw: Database.Database;
  let db: CubeDb & { close(): void };
  beforeAll(() => {
    raw = new Database(":memory:");
    applyMigrations(raw);
    // 文書だけ入れ、注記もセルも無い
    const ins = raw.prepare("INSERT INTO documents (doc_id, title) VALUES (?, ?)");
    ins.run(AMAMI_STORY.mongoose.docId, "文書");
    ins.run(AMAMI_STORY.mongoose.declarationDocId, "宣言");
    db = wrapSqlite(raw);
  });
  afterAll(() => raw.close());

  it("loadMongoose は注記が無ければ例外", async () => {
    await expect(loadMongoose(db)).rejects.toThrow("必須の注記が無い");
  });

  it("pickNote: 一致する本文があれば返し、空文字・無いときは例外", () => {
    const notes = [{ note_id: "a", kind: "footnote", text: "あいう", page: 1, blocks_timeseries: 0, reason: null }];
    expect(pickNote(notes, "い", "x")).toBe("あいう");
    expect(() => pickNote(notes, "ぬ", "x")).toThrow();
    expect(() => pickNote([{ ...notes[0], text: "" }], "", "x")).toThrow();
  });
});

describe("buildHazardPanels", () => {
  const rows = [
    { municipality_ja: "A市", phenomenon_ja: "土石流", zone_kind_ja: "特別警戒区域", n: 3 },
    { municipality_ja: "A市", phenomenon_ja: "土石流", zone_kind_ja: "警戒区域", n: 5 },
    { municipality_ja: "B町", phenomenon_ja: "地滑り", zone_kind_ja: "警戒区域", n: 7 },
    { municipality_ja: "B町", phenomenon_ja: "土石流", zone_kind_ja: "警戒区域", n: 1 },
  ];
  it("区分ごとの面。警戒が先、市町村は合計の多い順。区分をまたいで足さない", () => {
    const p = buildHazardPanels(rows, AMAMI_STORY.hazard.specialKindMatch);
    expect(p.map((x) => [x.kind, x.special, x.total])).toEqual([
      ["警戒区域", false, 13],
      ["特別警戒区域", true, 3],
    ]);
    expect(p[0].municipalities.map((m) => [m.name, m.total])).toEqual([["B町", 8], ["A市", 5]]);
    expect(new Set(p[0].phenomena)).toEqual(new Set(["地滑り", "土石流"]));
  });
});

describe("ページの JSX に数字のリテラルが無い", () => {
  const files = [
    "src/app/stories/amami/page.tsx",
    ...fs.readdirSync(path.resolve(__dirname, "../../components/stories")).filter((f) => f.endsWith(".tsx")).map((f) => `src/components/stories/${f}`),
  ];
  it.each(files)("%s", (f) => {
    const src = fs.readFileSync(path.resolve(__dirname, "../../..", f), "utf8");
    // JSX の本文（> と < のあいだ）に半角数字を直接書かない。{式} の中は対象外。
    const bad = [...src.matchAll(/>([^<>{}]*\d[^<>{}]*)</g)].map((m) => m[1].trim()).filter(Boolean);
    expect(bad).toEqual([]);
  });
});
