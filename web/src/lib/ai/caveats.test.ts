import { describe, expect, it } from "vitest";
import { CAVEAT_TEXT, caveatKeysForTables, caveatsForTables, caveatText } from "@/lib/ai/caveats";

/**
 * 現行実装（domain.ts に手書きされた注記をテーブル名から決定論的に引くもの）の
 * スナップショット。docs/plans/PHASE_A.md §A-1・A-7 の回帰テストの土台。
 *
 * ここで固定した「キーの順序」と「本文文字列」は、後で A-7 が caveats.ts の中身を
 * レジストリ（registry/caveat.yaml → data/db/registry.sqlite の caveat テーブル）参照に
 * 差し替えたときも1文字も変わらず通ることが Phase A の受け入れ条件。
 * このテストが赤くなったら、レジストリ側の文言が現行実装からズレている（＝許されない変更）。
 *
 * 対象テーブルは caveats.ts に実在するテーブル名だけを使う（推測で足さない）:
 * MEASURE_TABLES / ORGANISM_TABLES / SYNTHETIC_TABLES の全要素、"sites"、
 * "ias_species"、"mesh_" 接頭辞のもの（mesh_all / mesh_species / mesh_year）、
 * MESH_TABLES_EXTRA の "species_mesh_year"、および複数テーブルを混ぜたケース。
 */

const MEASURE_TABLES = [
  "measurements",
  "meas_year",
  "meas_month",
  "meas_daily",
  "meas_clim",
  "zone_year",
  "zone_clim",
  "var_catalog",
  "site_var",
] as const;

const ORGANISM_TABLES = [
  "organism_records",
  "org_norm",
  "org_group_year",
  "org_watershed",
  "org_watershed_year",
  "species2",
  "species_year2",
  "species_month",
  "effort_year",
] as const;

const SYNTHETIC_TABLES = [
  "observers",
  "interventions",
  "decisions",
  "quality_transitions",
  "quality_monthly",
  "event_observers",
] as const;

const MESH_TABLES = ["mesh_all", "mesh_species", "mesh_year", "species_mesh_year"] as const;

describe("caveatsForTables — measure tables", () => {
  for (const table of MEASURE_TABLES) {
    it(table, () => {
      expect(caveatsForTables([table])).toMatchInlineSnapshot(`
        [
          {
            "key": "measuredOn",
            "text": "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
          },
          {
            "key": "censored",
            "text": "全体の約24%は定量下限未満（原表記が「<0.5」など）で、value 列には 0 が入っている。折れ線では中抜きの点で示し、平均には含めるが「0 が観測された」とは読まないこと。",
          },
          {
            "key": "duplicates",
            "text": "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
          },
        ]
      `);
    });
  }
});

describe("caveatsForTables — organism tables", () => {
  for (const table of ORGANISM_TABLES) {
    it(table, () => {
      expect(caveatsForTables([table])).toMatchInlineSnapshot(`
        [
          {
            "key": "organismSite",
            "text": "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。",
          },
          {
            "key": "effort",
            "text": "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
          },
          {
            "key": "regimes",
            "text": "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
          },
          {
            "key": "gbifCutoff",
            "text": "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
          },
          {
            "key": "share",
            "text": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
          },
        ]
      `);
    });
  }
});

describe("caveatsForTables — synthetic tables", () => {
  for (const table of SYNTHETIC_TABLES) {
    it(table, () => {
      expect(caveatsForTables([table])).toMatchInlineSnapshot(`
        [
          {
            "key": "synthetic",
            "text": "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。",
          },
        ]
      `);
    });
  }
});

describe("caveatsForTables — mesh tables", () => {
  for (const table of MESH_TABLES) {
    it(table, () => {
      expect(caveatsForTables([table])).toMatchInlineSnapshot(`
        [
          {
            "key": "share",
            "text": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
          },
          {
            "key": "effort",
            "text": "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
          },
        ]
      `);
    });
  }
});

it("caveatsForTables — sites", () => {
  expect(caveatsForTables(["sites"])).toMatchInlineSnapshot(`
    [
      {
        "key": "zone",
        "text": "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。",
      },
      {
        "key": "municipality",
        "text": "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。",
      },
    ]
  `);
});

it("caveatsForTables — ias_species", () => {
  expect(caveatsForTables(["ias_species"])).toMatchInlineSnapshot(`
    [
      {
        "key": "isAlien",
        "text": "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。",
      },
    ]
  `);
});

it("caveatsForTables — 複数テーブルを混ぜたケース（synthetic が最優先で先頭に来る）", () => {
  expect(
    caveatsForTables(["measurements", "sites", "organism_records", "observers", "mesh_all", "ias_species"]),
  ).toMatchInlineSnapshot(`
    [
      {
        "key": "synthetic",
        "text": "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。",
      },
      {
        "key": "measuredOn",
        "text": "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
      },
      {
        "key": "censored",
        "text": "全体の約24%は定量下限未満（原表記が「<0.5」など）で、value 列には 0 が入っている。折れ線では中抜きの点で示し、平均には含めるが「0 が観測された」とは読まないこと。",
      },
      {
        "key": "duplicates",
        "text": "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
      },
      {
        "key": "zone",
        "text": "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。",
      },
      {
        "key": "municipality",
        "text": "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。",
      },
      {
        "key": "organismSite",
        "text": "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。",
      },
      {
        "key": "effort",
        "text": "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
      },
      {
        "key": "regimes",
        "text": "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
      },
      {
        "key": "gbifCutoff",
        "text": "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
      },
      {
        "key": "share",
        "text": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
      },
      {
        "key": "isAlien",
        "text": "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。",
      },
    ]
  `);
});

it("caveatKeysForTables — キーだけを取り出す", () => {
  expect(caveatKeysForTables(["measurements", "sites"])).toMatchInlineSnapshot(`
    [
      "measuredOn",
      "censored",
      "duplicates",
      "zone",
      "municipality",
    ]
  `);
});

it("caveatText — 個別引き", () => {
  expect(caveatText("synthetic")).toMatchInlineSnapshot(
    `"観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。"`,
  );
  expect(caveatText("no-such-key")).toBe("no-such-key");
});

it("CAVEAT_TEXT — 全キー・全本文を固定する", () => {
  expect(CAVEAT_TEXT).toMatchInlineSnapshot(`
    {
      "censored": "全体の約24%は定量下限未満（原表記が「<0.5」など）で、value 列には 0 が入っている。折れ線では中抜きの点で示し、平均には含めるが「0 が観測された」とは読まないこと。",
      "duplicates": "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
      "effort": "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
      "gbifCutoff": "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
      "isAlien": "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。",
      "measuredOn": "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
      "municipality": "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。",
      "organismSite": "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。",
      "regimes": "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
      "share": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
      "synthetic": "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。",
      "zone": "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。",
    }
  `);
});
