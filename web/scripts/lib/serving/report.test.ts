import { describe, expect, it } from "vitest";
import {
  addClassification,
  buildReportJson,
  buildReportMarkdown,
  emptyQueryStats,
  type ReportHeader,
} from "./report";

const header: ReportHeader = {
  gitHead: "abc123",
  v2PipelineFingerprint: "fp-1",
  registryInputFingerprint: "fp-2",
  sqliteVersion: "3.53.4",
  imputation: "zero",
  expand: "all",
  v1Source: "derived",
  generatedAt: "2026-09-26T00:00:00.000Z",
  elapsedMs: 12345,
};

describe("addClassification", () => {
  it("既知の規則ならその列を増やす", () => {
    const s = emptyQueryStats("q1");
    addClassification(s, new Set(["declared"]));
    addClassification(s, new Set(["declared"]));
    addClassification(s, new Set(["day_split"]));
    expect(s.declared).toBe(2);
    expect(s.day_split).toBe(1);
    expect(s.unexplained).toBe(0);
  });

  it("unexplained は空集合", () => {
    const s = emptyQueryStats("q1");
    addClassification(s, new Set());
    expect(s.unexplained).toBe(1);
  });

  it("1つの diff が複数の系統にまたがるときは、それぞれの列を1回ずつ増やす（説明の鎖、design §1・§3）", () => {
    const s = emptyQueryStats("q1");
    addClassification(s, new Set(["declared", "synthetic_excluded", "lod_imputation"]));
    expect(s.declared).toBe(1);
    expect(s.synthetic_excluded).toBe(1);
    expect(s.lod_imputation).toBe(1);
    expect(s.unexplained).toBe(0);
  });
});

describe("buildReportMarkdown/buildReportJson", () => {
  it("ヘッダ・集計表・unexplainedサンプル・宣言の腐りを含む", () => {
    const s1 = emptyQueryStats("year_series_site");
    s1.runs = 10;
    s1.rowsV1 = 100;
    s1.rowsV2 = 100;
    s1.matched = 95;
    addClassification(s1, new Set(["declared"]));
    addClassification(s1, new Set());

    const input = {
      header,
      stats: [s1],
      unexplainedSamples: [{ queryId: "year_series_site", params: { alias: "x" }, kind: "value_diff", key: [2020], columns: ["avg"] }],
      rottenDeclarations: [{ table: "meas_year", key: ["a", "x", 2003, "daily"], kind: "row_only_in_candidate" }],
    };

    const md = buildReportMarkdown(input);
    expect(md).toContain("abc123");
    expect(md).toContain("fp-1");
    expect(md).toContain("year_series_site");
    expect(md).toContain("meas_year");
    expect(md).toContain("row_only_in_candidate");

    const json = buildReportJson(input) as { totals: { runs: number; unexplained: number } };
    expect(json.totals.runs).toBe(10);
    expect(json.totals.unexplained).toBe(1);
  });

  it("宣言の腐りが無ければその旨を書く", () => {
    const md = buildReportMarkdown({ header, stats: [], unexplainedSamples: [], rottenDeclarations: [] });
    expect(md).toContain("無し");
  });

  it("imputation=lod のときだけ lod_moved の合計行を出す（design §3 の集計）", () => {
    const s1 = emptyQueryStats("year_series_site_by_variable");
    addClassification(s1, new Set(["lod_imputation"]));
    addClassification(s1, new Set(["lod_imputation"]));

    const lodHeader: ReportHeader = { ...header, imputation: "lod" };
    const mdLod = buildReportMarkdown({ header: lodHeader, stats: [s1], unexplainedSamples: [], rottenDeclarations: [] });
    expect(mdLod).toContain("lod_moved");
    expect(mdLod).toContain("2");

    const mdZero = buildReportMarkdown({ header, stats: [s1], unexplainedSamples: [], rottenDeclarations: [] });
    expect(mdZero).not.toContain("lod_moved");
  });

  it("変異結果があれば表を足す", () => {
    const md = buildReportMarkdown({
      header,
      stats: [],
      unexplainedSamples: [],
      rottenDeclarations: [],
      mutationResults: [{ name: "day_split_rule_off", unexplained: 3105, caughtAsExpected: true }],
    });
    expect(md).toContain("変異テスト");
    expect(md).toContain("day_split_rule_off");
  });

  it("生物系5規則の moved（キー数）と label_moved のカテゴリ別件数を出す（PR-3b §3.4-2）", () => {
    const s1 = emptyQueryStats("watershed_year");
    addClassification(s1, new Set(["watershed_memo", "species_n_definition"]));
    addClassification(s1, new Set(["watershed_memo"]));
    const s2 = emptyQueryStats("species_labels");
    addClassification(s2, new Set(["vernacular_label_rule"]));
    const input = {
      header,
      stats: [s1, s2],
      unexplainedSamples: [],
      rottenDeclarations: [],
      labelMoved: { species_labels: { "日本語→日本語": 218, "日本語→学名のみ": 17 } },
    };
    const md = buildReportMarkdown(input);
    expect(md).toContain("| watershed_memo | watershed_year | 2 |");
    expect(md).toContain("| species_n_definition | watershed_year | 1 |");
    expect(md).toContain("| vernacular_label_rule | species_labels | 1 |");
    expect(md).toContain("| species_labels | 日本語→日本語 | 218 |");
    const json = buildReportJson(input) as { totals: { watershed_memo: number }; labelMoved: Record<string, Record<string, number>> };
    expect(json.totals.watershed_memo).toBe(2);
    expect(json.labelMoved.species_labels["日本語→学名のみ"]).toBe(17);
  });

  it("生物系の規則が1件も無ければ（無し）と書く", () => {
    const md = buildReportMarkdown({ header, stats: [emptyQueryStats("q")], unexplainedSamples: [], rottenDeclarations: [] });
    expect(md).toContain("生物系の規則ごとの moved");
  });
});
