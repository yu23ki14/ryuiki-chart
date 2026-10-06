import fs from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { describe, expect, it } from "vitest";
import { basisOfCell, isSourceGrainCell, sourceGrainCellSql } from "@/lib/cube/cell-basis";

const GRAINS = ["hour", "instant", "day", "month", "year", "fiscal_year"];

describe("出典が配った粒度のセルの規則（1か所）", () => {
  it("TS 版と SQL 版が (grain, input_grain) の全組み合わせで一致する", () => {
    const db = new Database(":memory:");
    for (const grain of GRAINS) {
      for (const inputGrain of GRAINS) {
        const row = db
          .prepare(`SELECT ${sourceGrainCellSql("t")} AS ok FROM (SELECT ? AS grain, ? AS input_grain) t`)
          .get(grain, inputGrain) as { ok: number };
        expect(Boolean(row.ok), `${grain}/${inputGrain}`).toBe(isSourceGrainCell({ grain, inputGrain }));
      }
    }
    db.close();
  });

  it("月から年度へ積み上げたセル（厚木）は出典の粒度のセルで、basis は fiscal_year。暦年や日次の積み上げは違う", () => {
    expect(isSourceGrainCell({ grain: "fiscal_year", inputGrain: "month" })).toBe(true);
    expect(basisOfCell({ grain: "fiscal_year", inputGrain: "month" })).toBe("fiscal_year");
    expect(isSourceGrainCell({ grain: "fiscal_year", inputGrain: "fiscal_year" })).toBe(true);
    expect(isSourceGrainCell({ grain: "year", inputGrain: "month" })).toBe(false); // 暦年へは積み上げない（宣言外）
    expect(isSourceGrainCell({ grain: "year", inputGrain: "day" })).toBe(false);
    expect(basisOfCell({ grain: "year", inputGrain: "day" })).toBe("day");
  });

  it("basisOfCell と規則が食い違わない: 出典の粒度のセルの basis は grain どおり（year/fiscal_year）", () => {
    for (const grain of ["year", "fiscal_year"]) {
      for (const inputGrain of GRAINS) {
        const cell = { grain, inputGrain };
        if (isSourceGrainCell(cell)) expect(basisOfCell(cell)).toBe(grain);
      }
    }
  });

  it("serving_queries.yaml の WHERE は同じ式を使っている（YAML は関数を呼べないので文字列で突き合わせる）", () => {
    const yaml = fs.readFileSync(path.resolve(__dirname, "../../../serving_queries.yaml"), "utf-8");
    const expected = sourceGrainCellSql("spv");
    const occurrences = yaml.split(expected).length - 1;
    expect(occurrences).toBe(2); // variable_site_basis と variable_basis
  });
});
