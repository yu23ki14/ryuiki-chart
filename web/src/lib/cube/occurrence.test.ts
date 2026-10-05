import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { OCCURRENCE_AGG_INDEX as OCC_INDEX } from "@/db/schema-cube";
import { NAME_JA } from "@/lib/registry/generated-client";
import type { CubeDb, SqlParam } from "./db";
import { buildOccurrenceFixture, FXO, type OccurrenceFixture } from "./__fixtures__/occurrence-fixture";
import {
  meshByYear,
  pickLabel,
  speciesLabels,
  speciesMeshYears,
  speciesMonths,
  speciesShareTrend,
  speciesYears,
  USE_RECORD_VERNACULAR,
  watershedYears,
} from "./occurrence";
import { gridCatalog, iasSpecies, speciesCatalog } from "./catalog";

let fx: OccurrenceFixture;
beforeEach(() => {
  fx = buildOccurrenceFixture();
});
afterEach(() => {
  fx.db.close();
});

const { alpha, beta, gamma, delta, named } = FXO.binoms;

describe("speciesYears", () => {
  it("binom ごと・年ごとの n と mesh_n（既定窓 1990〜2026。1950 は窓外）", async () => {
    const rows = await speciesYears(fx.db, [alpha, beta]);
    expect(rows).toEqual([
      { binom: alpha, year: 2000, n: 50, meshN: 1 },
      { binom: beta, year: 2000, n: 55, meshN: 2 }, // 同じ binom の2 taxon（B1+B2）を束ねる
      { binom: alpha, year: 2005, n: 4, meshN: 1 }, // survey_period も年族
      { binom: alpha, year: 2010, n: 90, meshN: 2 },
      { binom: beta, year: 2010, n: 31, meshN: 2 },
      { binom: alpha, year: 2021, n: 90, meshN: 1 },
    ]);
  });

  it("窓を指定できる。重複した binom は1回だけ数える", async () => {
    const rows = await speciesYears(fx.db, [alpha, alpha], { from: 2005, to: 2010 });
    expect(rows.map((r) => [r.year, r.n])).toEqual([
      [2005, 4],
      [2010, 90],
    ]);
  });

  it("空の一覧・未知の binom は空", async () => {
    expect(await speciesYears(fx.db, [])).toEqual([]);
    expect(await speciesYears(fx.db, ["Nope nope"])).toEqual([]);
  });

  it("MAX_ID_LIST（1000）を超える一覧も複数回に分けて返す（バインドは常に1個）", async () => {
    const many = [alpha, ...Array.from({ length: 1500 }, (_, i) => `Pad x${i}`)];
    const rows = await speciesYears(fx.db, many);
    expect(rows.filter((r) => r.binom === alpha)).toHaveLength(4);
  });
});

describe("speciesMonths", () => {
  it("2018 年以降の月セルを月ごとに束ねる。n<80 の種（gamma）は足切り", async () => {
    const rows = await speciesMonths(fx.db, [alpha, beta, gamma]);
    expect(rows).toEqual([
      { binom: alpha, month: 3, n: 40 },
      { binom: alpha, month: 7, n: 65 },
    ]);
  });
});

describe("speciesMeshYears", () => {
  it("(year, mlat, mlon) ごと。n≥80 の種だけ。1970 年より前は除く（v1 `yr BETWEEN 1970 AND 2026`）", async () => {
    expect(await speciesMeshYears(fx.db, alpha)).toEqual([
      { year: 2000, mlat: 3520, mlon: 13900, n: 50 },
      { year: 2005, mlat: 3521, mlon: 13901, n: 4 },
      { year: 2010, mlat: 3520, mlon: 13900, n: 30 },
      { year: 2010, mlat: 3521, mlon: 13901, n: 60 },
      { year: 2021, mlat: 3520, mlon: 13900, n: 90 },
    ]);
    expect(await speciesMeshYears(fx.db, gamma)).toEqual([]);
  });
});

describe("speciesShareTrend", () => {
  it("期間 A/B の n を binom ごとに。total は足切り前の同じ group 全体", async () => {
    const rows = await speciesShareTrend(fx.db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2010, to: 2014 });
    expect(rows).toEqual([
      { binom: alpha, label: "アルファ", nA: 50, nB: 90, totalA: 105, totalB: 121 },
      { binom: beta, label: "ベータ", nA: 55, nB: 31, totalA: 105, totalB: 121 },
    ]);
  });

  it("n_a>=40 AND n_b>=20 で足切りし、total は足切りの影響を受けない", async () => {
    const rows = await speciesShareTrend(fx.db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2021, to: 2021 });
    expect(rows.map((r) => r.binom)).toEqual([alpha]);
    expect(rows[0]).toMatchObject({ totalA: 105, totalB: 90 });
  });

  it("records:false は taxa/override 由来の和名だけ使う（beta は records 由来なので英名に落ちる）", async () => {
    const rows = await speciesShareTrend(fx.db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2010, to: 2014 }, { records: false });
    expect(rows.map((r) => r.label)).toEqual(["アルファ", "Beta bird"]);
  });
});

describe("meshByYear", () => {
  it("年内の (mlat, mlon) ごと。species_n は binom の DISTINCT（taxon_id NULL は数えない）", async () => {
    expect(await meshByYear(fx.db, 2022)).toEqual([
      { mlat: 3520, mlon: 13900, n: 20, speciesN: 2, rlN: 0 },
      { mlat: 3521, mlon: 13901, n: 20, speciesN: 1, rlN: 0 },
    ]);
    expect(await meshByYear(fx.db, 2000)).toEqual([
      { mlat: 3520, mlon: 13900, n: 55, speciesN: 2, rlN: 0 },
      { mlat: 3521, mlon: 13901, n: 50, speciesN: 1, rlN: 0 },
    ]);
  });

  it("survey_period（2005）も年族。レッドリスト件数は n_red_list の SUM", async () => {
    expect(await meshByYear(fx.db, 2005)).toEqual([{ mlat: 3521, mlon: 13901, n: 4, speciesN: 1, rlN: 0 }]);
    expect((await meshByYear(fx.db, 2010)).find((r) => r.mlat === 3521)?.rlN).toBe(60);
  });
});

describe("watershedYears", () => {
  it("(place_id, year)。species_n は taxon_id の DISTINCT。place_id NULL は含めない", async () => {
    const rows = await watershedYears(fx.db);
    expect(rows).toEqual([
      { placeId: FXO.places.ws1, year: 2020, n: 30, nAlien: 20, nRedList: 0, speciesN: 2 },
      { placeId: FXO.places.ws1, year: 2021, n: 5, nAlien: 0, nRedList: 5, speciesN: 1 },
    ]);
    expect(await watershedYears(fx.db, { placeId: FXO.places.ws1 })).toEqual(rows);
    expect(await watershedYears(fx.db, { placeId: "common:place:watershed.nlni-none" })).toEqual([]);
  });
});

describe("speciesLabels（表示名。§2.3）", () => {
  it("NAME_JA が最優先、次に代表 taxon の和名、英名、binom の順", async () => {
    const out = await speciesLabels(fx.db, [alpha, beta, gamma, delta, named, "Nope nope"]);
    const m = new Map(out.map((l) => [l.binom, l.label]));
    expect(m.get(alpha)).toBe("アルファ");
    expect(m.get(beta)).toBe("ベータ"); // 代表は件数最大の B2（B1 は和名なし）
    expect(m.get(gamma)).toBe(gamma);
    expect(m.get(delta)).toBe("デルタ");
    expect(m.get(named)).toBe(NAME_JA[named]);
    expect(m.get("Nope nope")).toBe("Nope nope");
  });

  it("USE_RECORD_VERNACULAR は D4 の決定どおり true。records:false で records 由来の和名を外す", async () => {
    expect(USE_RECORD_VERNACULAR).toBe(true);
    const off = new Map((await speciesLabels(fx.db, [alpha, beta, delta], { records: false })).map((l) => [l.binom, l.label]));
    expect(off.get(alpha)).toBe("アルファ");
    expect(off.get(beta)).toBe("Beta bird");
    expect(off.get(delta)).toBe("デルタ");
  });

  it("pickLabel は NAME_JA > ja > en > binom", () => {
    expect(pickLabel("x y", { ja: null, jaBasis: null, en: "E" }, true)).toBe("E");
    expect(pickLabel("x y", undefined, true)).toBe("x y");
    expect(pickLabel(named, { ja: "別", jaBasis: "override", en: null }, true)).toBe(NAME_JA[named]);
  });
});

describe("speciesCatalog / gridCatalog / iasSpecies は表示名を同じ規則で付ける", () => {
  it("speciesCatalog(withNames)", async () => {
    const rows = await speciesCatalog(fx.db, { withNames: true });
    expect(rows.map((r) => [r.binom, r.label])).toContainEqual([beta, "ベータ"]);
    expect((await speciesCatalog(fx.db)).every((r) => r.label === undefined)).toBe(true);
  });
  it("iasSpecies の label", async () => {
    expect((await iasSpecies(fx.db))[0]!.label).toBe("デルタ");
  });
  it("gridCatalog は place_id → (mlat, mlon)", async () => {
    expect((await gridCatalog(fx.db)).map((r) => [r.mlat, r.mlon])).toEqual([
      [3520, 13900],
      [3521, 13901],
    ]);
  });
});

/**
 * EXPLAIN の固定（§5.2・§6-1）。`ix_occurrence_agg_kind_grain_period`（PR-3a が足した第3索引）が
 * taxon 引きの計画を壊す罠があるため、occurrence_agg に触る SQL は全部 `INDEXED BY` を持ち、
 * 実際の計画がその索引を使うことを、関数が本当に投げた SQL を捕まえて確かめる。
 * （フィクスチャは小さいが、D1 と同じく ANALYZE 無し。`INDEXED BY` が使えない形なら実行時エラーになる。）
 */
describe("EXPLAIN QUERY PLAN の固定（occurrence_agg の索引）", () => {
  interface Captured {
    sql: string;
    params: readonly SqlParam[];
  }
  function capture(): { db: CubeDb; seen: Captured[] } {
    const seen: Captured[] = [];
    const db: CubeDb = {
      kind: "sqlite",
      async all(sql, params = []) {
        seen.push({ sql, params });
        return fx.db.all(sql, params);
      },
    };
    return { db, seen };
  }
  function plan(c: Captured): string[] {
    const rows = fx.raw.prepare(`EXPLAIN QUERY PLAN ${c.sql}`).all(...(c.params as unknown[])) as { detail: string }[];
    return rows.map((r) => r.detail);
  }
  function occDetails(c: Captured): string[] {
    return plan(c).filter((d) => /occurrence_agg/.test(d));
  }
  async function run(fn: (db: CubeDb) => Promise<unknown>): Promise<Captured[]> {
    const { db, seen } = capture();
    await fn(db);
    return seen.filter((c) => /occurrence_agg/.test(c.sql));
  }

  const taxonPeriod = new RegExp(`USING INDEX ${OCC_INDEX.taxonPeriod}`);

  const cases: [string, (db: CubeDb) => Promise<unknown>, RegExp][] = [
    ["speciesYears", (db) => speciesYears(db, [alpha, beta]), taxonPeriod],
    ["speciesMonths", (db) => speciesMonths(db, [alpha]), taxonPeriod],
    ["speciesMeshYears", (db) => speciesMeshYears(db, alpha), taxonPeriod],
    ["speciesShareTrend", (db) => speciesShareTrend(db, FXO.groups.bird, { from: 2000, to: 2004 }, { from: 2010, to: 2014 }), taxonPeriod],
    ["iasSpecies（n_since_2020）", (db) => iasSpecies(db), taxonPeriod],
    ["meshByYear", (db) => meshByYear(db, 2022), new RegExp(`USING (COVERING )?INDEX ${OCC_INDEX.kindGrainPeriod}`)],
    ["watershedYears（全体）", (db) => watershedYears(db), new RegExp(`USING (COVERING )?INDEX ${OCC_INDEX.kindGrainPeriod}`)],
    ["watershedYears（place 引き）", (db) => watershedYears(db, { placeId: FXO.places.ws1 }), new RegExp(`USING (COVERING )?INDEX ${OCC_INDEX.placePeriod}`)],
  ];

  for (const [name, fn, expected] of cases) {
    it(`${name}: occurrence_agg は INDEXED BY で期待の索引を使い、全走査しない`, async () => {
      const queries = await run(fn);
      expect(queries.length).toBeGreaterThan(0);
      for (const q of queries) {
        expect(q.sql).toMatch(/INDEXED BY ix_occurrence_agg_/);
        const details = occDetails(q);
        expect(details.some((d) => expected.test(d))).toBe(true);
        expect(details.some((d) => /^SCAN .*occurrence_agg/.test(d) || /SCAN o\b/.test(d))).toBe(false);
      }
    });
  }

  it("occurrence.ts/catalog.ts の occurrence_agg を引く SQL は全部 INDEXED BY を持つ（上のケースの網羅性の検査）", async () => {
    const { readFileSync } = await import("node:fs");
    for (const f of ["occurrence.ts", "catalog.ts"]) {
      const src = readFileSync(new URL(`./${f}`, import.meta.url), "utf-8");
      const fromJoins = src.match(/(FROM|JOIN)\s+occurrence_agg\b[^\n]*/g) ?? [];
      for (const line of fromJoins) expect(line).toMatch(/INDEXED BY/);
    }
  });
});
