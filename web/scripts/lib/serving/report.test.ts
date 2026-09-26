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
};

describe("addClassification", () => {
  it("既知の規則ならその列を増やす", () => {
    const s = emptyQueryStats("q1");
    addClassification(s, "declared");
    addClassification(s, "declared");
    addClassification(s, "rain_div10");
    expect(s.declared).toBe(2);
    expect(s.rain_div10).toBe(1);
    expect(s.unexplained).toBe(0);
  });

  it("unexplained は専用の列", () => {
    const s = emptyQueryStats("q1");
    addClassification(s, "unexplained");
    expect(s.unexplained).toBe(1);
  });
});

describe("buildReportMarkdown/buildReportJson", () => {
  it("ヘッダ・集計表・unexplainedサンプル・宣言の腐りを含む", () => {
    const s1 = emptyQueryStats("year_series_site");
    s1.runs = 10;
    s1.rowsV1 = 100;
    s1.rowsV2 = 100;
    s1.matched = 95;
    addClassification(s1, "declared");
    addClassification(s1, "unexplained");

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

  it("変異結果があれば表を足す", () => {
    const md = buildReportMarkdown({
      header,
      stats: [],
      unexplainedSamples: [],
      rottenDeclarations: [],
      mutationResults: [{ name: "rain_no_div10_rule", unexplained: 3105, caughtAsExpected: true }],
    });
    expect(md).toContain("変異テスト");
    expect(md).toContain("rain_no_div10_rule");
  });
});
