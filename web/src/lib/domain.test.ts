import { describe, expect, it } from "vitest";
import {
  VARIABLE_SHORT,
  VARIABLE_UNIT_FALLBACK,
  VARIABLE_NOTE,
  HIGHER_IS_WORSE,
  DATA_CAVEATS,
  NAME_JA,
  BIOTA_CAVEATS,
} from "@/lib/domain";

/**
 * domain.ts は §A-8 でレジストリ（generated.ts）から組み立てる薄い層に切り替わった。
 * ここに固定した値は、切り替え前の domain.ts に直書きされていた値をそのまま書き写したもの
 * （2026-09-06 時点、切り替え直前の git 履歴に対応する）。1文字・1件も変わらないことを保証する。
 */

it("VARIABLE_SHORT — 現行値の固定", () => {
  expect(VARIABLE_SHORT).toEqual({
    "生物化学的酸素要求量 BOD": "BOD",
    "化学的酸素要求量 COD": "COD",
    "溶存酸素量 DO": "DO",
    "浮遊物質量 SS": "SS",
    "直鎖アルキルベンゼンスルホン酸及びその塩 LAS": "LAS",
    ノルマルヘキサン抽出物質: "n-ヘキサン抽出物質",
    "流量関連（公式定義未確認のため原表記のまま）": "流量関連",
  });
});

it("VARIABLE_UNIT_FALLBACK — 現行値の固定", () => {
  expect(VARIABLE_UNIT_FALLBACK).toEqual({
    pH: "",
    "pH（最大値）": "",
    "pH（最小値）": "",
  });
});

it("VARIABLE_NOTE — 現行値の固定", () => {
  expect(VARIABLE_NOTE).toEqual({
    "生物化学的酸素要求量 BOD": "微生物が有機物を分解するのに使う酸素量。大きいほど有機汚濁が進んでいる",
    "化学的酸素要求量 COD": "酸化剤で有機物を分解したときの消費酸素量。湖沼・海域の指標として使われる",
    "溶存酸素量 DO": "水に溶けている酸素。小さいほど生き物が棲みにくい。水温が上がると下がる",
    "浮遊物質量 SS": "水に浮いている細かい粒子の量。降雨で土砂が入ると上がる",
    全亜鉛: "水生生物の保全に係る環境基準項目",
    大腸菌群数: "し尿等による汚染の指標。2022年度以降は「大腸菌数」に移行しつつある",
    水温: "採水時の水温",
    透明度: "湖沼・海域で円板が見えなくなる深さ",
  });
});

it("HIGHER_IS_WORSE — 現行値の固定", () => {
  expect(HIGHER_IS_WORSE).toEqual({
    "生物化学的酸素要求量 BOD": true,
    "化学的酸素要求量 COD": true,
    "浮遊物質量 SS": true,
    大腸菌群数: true,
    大腸菌数: true,
    全亜鉛: true,
    "全窒素 T-N": true,
    "全燐 T-P": true,
    "溶存酸素量 DO": false,
    透明度: false,
  });
});

it("DATA_CAVEATS — 現行値の固定（本文は caveats.test.ts と同じ文言）", () => {
  expect(DATA_CAVEATS).toEqual({
    measuredOn:
      "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
    censored:
      "全体の約24%は定量下限未満（原表記が「<0.5」など）で、value 列には 0 が入っている。折れ線では中抜きの点で示し、平均には含めるが「0 が観測された」とは読まないこと。",
    duplicates:
      "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
    zone: "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。",
    organismSite:
      "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。",
    effort:
      "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。",
    synthetic:
      "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。",
  });
});

it("BIOTA_CAVEATS — 現行値の固定", () => {
  expect(BIOTA_CAVEATS).toEqual({
    regimes:
      "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
    gbifCutoff:
      "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
    share:
      "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
    inatBackfill:
      "iNaturalist 由来の 165,332 件は分類階級が空だったため、学名の先頭2語をキーに GBIF 側の分類を引き当てて補完している（96%が解決）。",
    fishClass:
      "魚類は class 列に現れない（Actinopterygii が入っておらず空になっている）。門が Chordata で綱が空のものを魚類として扱っている。",
    isAlien:
      "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。",
  });
});

describe("NAME_JA — 現行値の固定（54件）", () => {
  it("件数", () => {
    expect(Object.keys(NAME_JA)).toHaveLength(54);
  });

  it("代表的な数件の値", () => {
    expect(NAME_JA["Hypsipetes amaurotis"]).toBe("ヒヨドリ");
    expect(NAME_JA["Plecoglossus altivelis"]).toBe("アユ");
    expect(NAME_JA["Micropterus salmoides"]).toBe("オオクチバス");
    expect(NAME_JA["Pomacea canaliculata"]).toBe("スクミリンゴガイ");
  });

  it("Plecoglossus altivelis に地域個体群の和名（リュウキュウアユ）が誤って付いていないこと", () => {
    expect(NAME_JA["Plecoglossus altivelis"]).not.toBe("リュウキュウアユ");
  });
});
