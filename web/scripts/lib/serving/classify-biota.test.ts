/**
 * 生物系の5規則（`classify.ts` の `classifyBiota`。Issue #48 PR-3b、`docs/plans/V2_SERVING_PR3B.md` §3.1）。
 *
 * どの規則も「v1 →(規則)→ 独立な中間点 →(=)→ v2」。中間点（`ctx.biota`）は手書きのフィクスチャ。
 * 確かめる点: (1) 中間点どおりなら説明できる (2) **v2 が中間点と食い違えば、規則が有効でも説明しない**
 * （規則が「何でも説明する穴」にならない） (3) 規則を無効化すれば説明しない。
 */
import { describe, expect, it } from "vitest";
import { rowsByKey, toNormRows, type CompareSpec } from "./normalize";
import {
  binomMonthKey,
  classifyDiff,
  compareRuns,
  labelCategory,
  watershedYearKey,
  type BiotaExpectations,
  type Classification,
  type ClassifyContext,
  type ExpectedDiffs,
  type KnownRule,
} from "./classify";

const WS_YEAR: CompareSpec = { key: ["watershed_id", "year"], numeric: ["n", "species_n", "alien_n", "redlist_n"], label: [] };
const WS_ALL: CompareSpec = { key: ["watershed_id"], numeric: ["org_n", "org_alien_n", "org_redlist_n"], label: [] };

function run(
  spec: CompareSpec,
  v1: Record<string, unknown>[],
  v2: Record<string, unknown>[],
  ctx: Partial<ClassifyContext>,
): Classification[] {
  const full: ClassifyContext = {
    expected: {},
    declared: { v1Table: null, builder: null },
    params: {},
    known: new Set<KnownRule>(),
    ...ctx,
  };
  const n1 = toNormRows(v1, spec.key, spec.numeric, spec.label);
  const n2 = toNormRows(v2, spec.key, spec.numeric, spec.label);
  return compareRuns(rowsByKey(n1), rowsByKey(n2)).map((d) => classifyDiff(d, full));
}

const ALL_BIOTA = new Set<KnownRule>(["watershed_memo", "species_n_definition", "month_cell_membership", "vernacular_label_rule", "undated_excluded"]);

function wsYearBiota(entries: [string, number, Partial<{ n: number; alienN: number; redlistN: number; speciesNameN: number; speciesTaxonN: number | null }>][]): BiotaExpectations {
  return {
    wsYear: new Map(
      entries.map(([ws, year, e]) => [
        watershedYearKey(ws, year),
        { n: 0, alienN: 0, redlistN: 0, speciesNameN: 0, speciesTaxonN: 0, ...e },
      ]),
    ),
  };
}

describe("watershed_memo / species_n_definition（watershed_year）", () => {
  const base = { queryId: "watershed_year", known: ALL_BIOTA };

  it("v1 と v2 の n が違い、v2 が exact（b08）と一致する → watershed_memo", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, speciesNameN: 3, speciesTaxonN: 3 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 3, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 12, species_n: 3, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect([...c.rules]).toEqual(["watershed_memo"]);
  });

  it("v2 が exact と食い違う（v2 が壊れている）なら、規則が有効でも unexplained", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, speciesNameN: 3, speciesTaxonN: 3 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 3, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 13, species_n: 3, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect(c.rules.size).toBe(0);
  });

  it("規則を無効化（disabledRules）すれば説明しない（memo_rule_off）", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, speciesNameN: 3, speciesTaxonN: 3 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 3, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 12, species_n: 3, alien_n: 0, redlist_n: 0 }], { ...base, biota, disabledRules: new Set<KnownRule>(["watershed_memo"]) });
    expect(c.rules.size).toBe(0);
  });

  it("known に無ければ説明しない（v1 = v2 が期待の問い合わせで、規則を勝手に足さない）", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, speciesNameN: 3, speciesTaxonN: 3 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 3, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 12, species_n: 3, alien_n: 0, redlist_n: 0 }], { queryId: "watershed_year", known: new Set(), biota });
    expect(c.rules.size).toBe(0);
  });

  it("n/alien_n/redlist_n の複数列が動いても、全部 exact と一致すれば watershed_memo", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, alienN: 2, redlistN: 1, speciesNameN: 3, speciesTaxonN: 3 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 3, alien_n: 1, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 12, species_n: 3, alien_n: 2, redlist_n: 1 }], { ...base, biota });
    expect([...c.rules]).toEqual(["watershed_memo"]);
  });

  it("species_n だけが動く（v1 は exact と同じ学名 DISTINCT、v2 は taxon_id DISTINCT）→ species_n_definition だけ", () => {
    const biota = wsYearBiota([["A", 2020, { n: 10, speciesNameN: 5, speciesTaxonN: 7 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 5, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 10, species_n: 7, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect([...c.rules]).toEqual(["species_n_definition"]);
  });

  it("species_n_rule_off: 定義の違いは説明されず unexplained", () => {
    const biota = wsYearBiota([["A", 2020, { n: 10, speciesNameN: 5, speciesTaxonN: 7 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 5, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 10, species_n: 7, alien_n: 0, redlist_n: 0 }], { ...base, biota, disabledRules: new Set<KnownRule>(["species_n_definition"]) });
    expect(c.rules.size).toBe(0);
  });

  it("species_n: メモでも動き（v1≠exact）定義でも動く（学名≠taxon）→ 2規則とも", () => {
    const biota = wsYearBiota([["A", 2020, { n: 12, speciesNameN: 5, speciesTaxonN: 7 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 4, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 12, species_n: 7, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect(new Set(c.rules)).toEqual(new Set(["watershed_memo", "species_n_definition"]));
  });

  it("species_n: メモだけで動く（学名＝taxon、v1≠exact）→ watershed_memo だけ", () => {
    const biota = wsYearBiota([["A", 2020, { n: 10, speciesNameN: 6, speciesTaxonN: 6 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 4, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 10, species_n: 6, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect([...c.rules]).toEqual(["watershed_memo"]);
  });

  it("species_n: v2 が taxon_id の再計算（L2）と食い違えば unexplained", () => {
    const biota = wsYearBiota([["A", 2020, { n: 10, speciesNameN: 5, speciesTaxonN: 7 }]]);
    const [c] = run(WS_YEAR, [{ watershed_id: "A", year: 2020, n: 10, species_n: 5, alien_n: 0, redlist_n: 0 }], [{ watershed_id: "A", year: 2020, n: 10, species_n: 8, alien_n: 0, redlist_n: 0 }], { ...base, biota });
    expect(c.rules.size).toBe(0);
  });

  it("row_only_in_v1: exact にも無い行はメモが作った行 → watershed_memo。exact にあるのに v2 に無いなら unexplained", () => {
    const only = [{ watershed_id: "A", year: 1990, n: 1, species_n: 1, alien_n: 0, redlist_n: 0 }];
    const [c1] = run(WS_YEAR, only, [], { ...base, biota: wsYearBiota([]) });
    expect([...c1.rules]).toEqual(["watershed_memo"]);
    const [c2] = run(WS_YEAR, only, [], { ...base, biota: wsYearBiota([["A", 1990, { n: 1, speciesNameN: 1, speciesTaxonN: 1 }]]) });
    expect(c2.rules.size).toBe(0);
  });

  it("row_only_in_v2: exact にあり v2 の全列が中間点と一致するときだけ watershed_memo", () => {
    const row = { watershed_id: "A", year: 2020, n: 3, species_n: 2, alien_n: 1, redlist_n: 0 };
    const biota = wsYearBiota([["A", 2020, { n: 3, alienN: 1, redlistN: 0, speciesNameN: 2, speciesTaxonN: 2 }]]);
    const [ok] = run(WS_YEAR, [], [row], { ...base, biota });
    expect([...ok.rules]).toEqual(["watershed_memo"]);
    const [bad] = run(WS_YEAR, [], [{ ...row, n: 4 }], { ...base, biota });
    expect(bad.rules.size).toBe(0);
    const [absent] = run(WS_YEAR, [], [row], { ...base, biota: wsYearBiota([]) });
    expect(absent.rules.size).toBe(0);
  });
});

describe("watershed_memo（watershed_rollup）", () => {
  const base = { queryId: "watershed_rollup", known: ALL_BIOTA };
  const biota: BiotaExpectations = { wsAll: new Map([["A", { n: 20, alienN: 2, redlistN: 1 }]]) };

  it("org_n/org_alien_n/org_redlist_n が動き、v2 が org_watershed_exact と一致 → watershed_memo", () => {
    const [c] = run(WS_ALL, [{ watershed_id: "A", org_n: 18, org_alien_n: 2, org_redlist_n: 0 }], [{ watershed_id: "A", org_n: 20, org_alien_n: 2, org_redlist_n: 1 }], { ...base, biota });
    expect([...c.rules]).toEqual(["watershed_memo"]);
  });

  it("v2 が exact と食い違えば unexplained", () => {
    const [c] = run(WS_ALL, [{ watershed_id: "A", org_n: 18, org_alien_n: 2, org_redlist_n: 0 }], [{ watershed_id: "A", org_n: 21, org_alien_n: 2, org_redlist_n: 0 }], { ...base, biota });
    expect(c.rules.size).toBe(0);
  });

  it("v1 だけにある流域（exact に無い）は watershed_memo、v2 だけの流域（exact にあり一致）も watershed_memo", () => {
    const [c1] = run(WS_ALL, [{ watershed_id: "Z", org_n: 3, org_alien_n: 0, org_redlist_n: 0 }], [], { ...base, biota });
    expect([...c1.rules]).toEqual(["watershed_memo"]);
    const [c2] = run(WS_ALL, [], [{ watershed_id: "A", org_n: 20, org_alien_n: 2, org_redlist_n: 1 }], { ...base, biota });
    expect([...c2.rules]).toEqual(["watershed_memo"]);
  });
});

describe("month_cell_membership（species_months）", () => {
  const SPEC: CompareSpec = { key: ["month"], numeric: ["n"], label: [] };
  const biota: BiotaExpectations = {
    monthV1: new Map([[binomMonthKey("Fx a", 1), 10], [binomMonthKey("Fx a", 2), 7]]),
    monthV2: new Map([[binomMonthKey("Fx a", 1), 9], [binomMonthKey("Fx a", 3), 2]]),
  };
  const base = { queryId: "species_months", known: ALL_BIOTA, params: { binom: "Fx a" }, biota };

  it("v1 が v1 規則の件数・v2 が v2 規則の件数と一致する月は説明される", () => {
    const cs = run(SPEC, [{ month: 1, n: 10 }, { month: 2, n: 7 }], [{ month: 1, n: 9 }, { month: 3, n: 2 }], base);
    // month 1: value_diff、month 2: row_only_in_v1（v2 規則では 0 件）、month 3: row_only_in_v2（v1 規則では 0 件）
    expect(cs).toHaveLength(3);
    for (const c of cs) expect([...c.rules]).toEqual(["month_cell_membership"]);
  });

  it("v2 が v2 規則の件数と食い違えば unexplained（独立 SQL との一致が要る）", () => {
    const [c] = run(SPEC, [{ month: 1, n: 10 }], [{ month: 1, n: 8 }], base);
    expect(c.rules.size).toBe(0);
  });

  it("v1 規則と v2 規則の期待値が同じ月の差は説明しない（所属が原因ではない）", () => {
    const same: BiotaExpectations = { monthV1: new Map([[binomMonthKey("Fx a", 5), 4]]), monthV2: new Map([[binomMonthKey("Fx a", 5), 4]]) };
    const [c] = run(SPEC, [{ month: 5, n: 4 }], [{ month: 5, n: 3 }], { ...base, biota: same });
    expect(c.rules.size).toBe(0);
  });

  it("month_rule_off で説明されなくなる", () => {
    const [c] = run(SPEC, [{ month: 1, n: 10 }], [{ month: 1, n: 9 }], { ...base, disabledRules: new Set<KnownRule>(["month_cell_membership"]) });
    expect(c.rules.size).toBe(0);
  });
});

describe("vernacular_label_rule（species_labels / species_catalog / species_share_trend）", () => {
  const LABELS: CompareSpec = { key: ["binom"], numeric: [], label: ["label"] };
  const biota: BiotaExpectations = { labels: new Map([["Fx a", "アルファ"], ["Fx b", "Beta bird"], ["Fx c", "Fx c"]]) };
  const base = { queryId: "species_labels", known: ALL_BIOTA, biota };

  it("v2 の表示名が registry から再計算した期待ラベルと一致すれば説明し、文字種の遷移を数える", () => {
    const [c] = run(LABELS, [{ binom: "Fx a", label: "アルファ亜種" }], [{ binom: "Fx a", label: "アルファ" }], base);
    expect([...c.rules]).toEqual(["vernacular_label_rule"]);
    expect(c.labelMoves).toEqual(["日本語→日本語"]);
  });

  it("文字種のカテゴリ: 日本語→学名のみ・中国語等→日本語・英名等→英名等", () => {
    const biota2: BiotaExpectations = { labels: new Map([["Fx c", "Fx c"], ["Fx d", "ドクダミ"], ["Fx e", "Mallard"]]) };
    const cs = run(
      LABELS,
      [{ binom: "Fx c", label: "別種の和名" }, { binom: "Fx d", label: "药用蒲公英" }, { binom: "Fx e", label: "Northern Mallard" }],
      [{ binom: "Fx c", label: "Fx c" }, { binom: "Fx d", label: "ドクダミ" }, { binom: "Fx e", label: "Mallard" }],
      { ...base, biota: biota2 },
    );
    expect(cs.flatMap((c) => c.labelMoves ?? []).sort()).toEqual(["中国語等→日本語", "日本語→学名のみ", "英名等→英名等"].sort());
  });

  it("v2 のラベルが再計算と食い違えば、規則が有効でも unexplained（label_wrong の穴塞ぎ）", () => {
    const [c] = run(LABELS, [{ binom: "Fx a", label: "アルファ亜種" }], [{ binom: "Fx a", label: "違う名前" }], base);
    expect(c.rules.size).toBe(0);
  });

  it("期待ラベルが無い binom は説明しない", () => {
    const [c] = run(LABELS, [{ binom: "Fx zz", label: "x" }], [{ binom: "Fx zz", label: "y" }], base);
    expect(c.rules.size).toBe(0);
  });

  it("label_rule_off で説明されなくなる", () => {
    const [c] = run(LABELS, [{ binom: "Fx a", label: "アルファ亜種" }], [{ binom: "Fx a", label: "アルファ" }], { ...base, disabledRules: new Set<KnownRule>(["vernacular_label_rule"]) });
    expect(c.rules.size).toBe(0);
  });

  it("species_catalog: 宣言済み差分（Sirosporium の cls）は declared、label は vernacular_label_rule。同じ行で両方が要る場合も説明できる", () => {
    const CAT: CompareSpec = { key: ["binom"], numeric: ["n"], label: ["taxon_group", "cls", "family", "label"] };
    const expected: ExpectedDiffs = { species2: [{ key: ["Sirosporium celtidis"], kind: "value_diff", columns: ["cls"] }] };
    const ctx = {
      queryId: "species_catalog",
      known: new Set<KnownRule>(["declared", "vernacular_label_rule"]),
      expected,
      declared: { v1Table: "species2", builder: (_p: unknown, k: readonly (string | number)[]) => [k[0]] as (string | number)[] },
      biota: { labels: new Map([["Sirosporium celtidis", "Sirosporium celtidis"]]) },
    };
    const v1 = [{ binom: "Sirosporium celtidis", n: 5, taxon_group: "菌類", cls: "Sordariomycetes", family: "F", label: "Sirosporium celtidis" }];
    const v2 = [{ binom: "Sirosporium celtidis", n: 5, taxon_group: "菌類", cls: "Dothideomycetes", family: "F", label: "Sirosporium celtidis" }];
    const [c] = run(CAT, v1, v2, ctx);
    expect([...c.rules]).toEqual(["declared"]);
    expect(c.declaredMatches).toHaveLength(1);

    // 宣言に無い binom の cls 差は説明しない
    const [bad] = run(CAT, [{ ...v1[0], binom: "Other x" }], [{ ...v2[0], binom: "Other x" }], ctx);
    expect(bad.rules.size).toBe(0);

    // cls が宣言で、label も動く行 → 両方
    const biota = { labels: new Map([["Sirosporium celtidis", "新しい名前"]]) };
    const [both] = run(CAT, v1, [{ ...v2[0], label: "新しい名前" }], { ...ctx, biota });
    expect(new Set(both.rules)).toEqual(new Set(["declared", "vernacular_label_rule"]));
  });
});

describe("undated_excluded（biota_totals）", () => {
  const SPEC: CompareSpec = { key: [], numeric: ["records", "species", "mesh", "gbif", "inat"], label: [] };
  const base = { queryId: "biota_totals", known: ALL_BIOTA, biota: { undated: { records: 6836, gbif: 6592, inat: 244 } } as BiotaExpectations };
  const v1 = [{ records: 823692, species: 23618, mesh: 4083, gbif: 658360, inat: 165332 }];

  it("records・gbif・inat が日付の無い件数だけ v2 より多い → undated_excluded（1 行）", () => {
    const [c] = run(SPEC, v1, [{ records: 816856, species: 23618, mesh: 4083, gbif: 651768, inat: 165088 }], base);
    expect([...c.rules]).toEqual(["undated_excluded"]);
  });

  it("差が日付の無い件数と一致しなければ unexplained", () => {
    const [c] = run(SPEC, v1, [{ records: 816000, species: 23618, mesh: 4083, gbif: 651768, inat: 165088 }], base);
    expect(c.rules.size).toBe(0);
  });

  it("species・mesh は動かない（動いたら unexplained）", () => {
    const [c] = run(SPEC, v1, [{ records: 816856, species: 23600, mesh: 4083, gbif: 651768, inat: 165088 }], base);
    expect(c.rules.size).toBe(0);
  });

  it("undated_rule_off で説明されなくなる", () => {
    const [c] = run(SPEC, v1, [{ records: 816856, species: 23618, mesh: 4083, gbif: 651768, inat: 165088 }], { ...base, disabledRules: new Set<KnownRule>(["undated_excluded"]) });
    expect(c.rules.size).toBe(0);
  });
});

describe("labelCategory", () => {
  it("かなを含む＝日本語、binom そのもの＝学名のみ、漢字のみ＝中国語等、ラテン文字＝英名等", () => {
    expect(labelCategory("ドクダミ", "Houttuynia cordata")).toBe("日本語");
    expect(labelCategory("Houttuynia cordata", "Houttuynia cordata")).toBe("学名のみ");
    expect(labelCategory(null, "X y")).toBe("学名のみ");
    expect(labelCategory("药用蒲公英", "Taraxacum officinale")).toBe("中国語等");
    expect(labelCategory("Great Egret", "Ardea alba")).toBe("英名等");
  });
});
