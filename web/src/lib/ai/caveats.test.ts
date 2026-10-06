import { expect, it } from "vitest";
import { CAVEAT_TEXT, caveatKeysForTables, caveatsForTables, caveatText } from "@/lib/ai/caveats";

/**
 * `caveatsForTables`（テーブル名 → 注記）のスナップショット。
 *
 * Issue #48 PR-5 で v1 の派生表・原本表が D1 から DROP されたため、テーブル名で引ける注記は
 * `sites`（zone/municipality）だけになった（`registry/caveat.yaml` の caveat_scope の
 * 'table' 行）。v2 の注記は facet で引く（`lib/cube/caveats.test.ts`）。
 * `CAVEAT_TEXT` は全キー・全本文の固定（`censored` は撤去して `censoredLod` に一本化済み）。
 */

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

it("caveatsForTables — 撤去済みの表名・未知の表名は注記を返さない", () => {
  expect(caveatsForTables(["measurements", "meas_year", "mesh_all", "ias_species", "observers", "no_such_table"])).toEqual([]);
});

it("caveatsForTables — 重複・順序: 渡した表の順に並び、同じキーは1回だけ", () => {
  expect(caveatKeysForTables(["sites", "sites", "source_registry"])).toEqual(["zone", "municipality"]);
});

it("caveatKeysForTables — キーだけを取り出す", () => {
  expect(caveatKeysForTables(["sites"])).toMatchInlineSnapshot(`
    [
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
      "aboveLod": "透明度の定量上限超え（原表記が「>1.4」〜「>28」など、26行）は、上限がどこまでか分からないという性質上、集計方法によらず値に含められない。件数（n）にも入らないため、他の期間・地点と単純に比較しないこと。",
      "censoredLod": "全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を定量下限値とみなして集計している（上限側の見積もり）。不検出（ND）は平均に含めない。折れ線では中抜きの点で示し、その定量下限値が実際に観測された値だとは読まないこと。",
      "duplicates": "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
      "effort": "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
      "gbifCutoff": "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
      "isAlien": "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。",
      "landuseDefinitionChange": "土地利用の区分は2006年調査と2016年調査で定義が違う。2006年の「幹線交通用地」は2016年調査で「道路」「鉄道」に分割されており、同じ区分として比較できない。この2区分が2006年→2016年で全減・全増に見えるのは、実際の土地利用の変化ではなく調査区分の定義変更による見かけ上の増減である。",
      "measuredOn": "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
      "municipality": "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。",
      "organismSite": "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。",
      "regimes": "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
      "share": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
      "synthetic": "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。",
      "unitUnknown": "この指標のうち、原本に単位の記載が無い出典は、レジストリでも単位を確定できていない。該当する値は原本の数値のまま示しており、推測で換算していない（相模原市の1時間値 RAIN は0.1mm刻みの可能性があるが未確定のまま）。単位が判明している出典の値と混同しないこと。",
      "zone": "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。",
    }
  `);
});
