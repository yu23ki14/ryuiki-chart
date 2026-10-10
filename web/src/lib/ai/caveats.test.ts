import { expect, it } from "vitest";
import { CAVEAT_TEXT, caveatText } from "@/lib/ai/caveats";
import { caveatKeysForFacets, caveatsForFacets, facetsForTables } from "@/lib/cube/caveats";

const caveatsForTables = (t: string[]) => caveatsForFacets(facetsForTables(t));
const caveatKeysForTables = (t: string[]) => caveatKeysForFacets(facetsForTables(t));

/**
 * 配信表名 → 注記（`facetsForTables` → `caveatsForFacets`）のスナップショット。
 *
 * Issue #48 PR-5 で v1 の派生表・原本表が D1 から DROP されたため、テーブル名で引ける注記は
 * `sites`（zone/municipality）だけになった（`registry/caveat_scope.yaml` の
 * `dataset: sites`）。v2 の注記は facet で引く（`lib/cube/caveats.test.ts`）。
 * `CAVEAT_TEXT` は全キー・全本文の固定（`censored` は撤去して `censoredLod` に一本化済み）。
 */

it("caveatsForTables — sites", () => {
  expect(caveatsForTables(["sites"])).toMatchInlineSnapshot(`
    [
      {
        "key": "zone",
        "text": "zone は地形から機械的に付けた操作的区分で、公式の区分ではない。標高の低い島（奄美大島など）では山地（zone 2）が陸の大半を占め、低地（zone 4）はほとんど現れない。これは定義の結果で、凡例・名称は地域によらず共通である。zone 1（山地で、標高が地域の最高峰の半分以上）には水質データが無い。",
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
    `"合成データ（デモ用に生成したもの）。実在の公開データではない。"`,
  );
  expect(caveatText("no-such-key")).toBe("no-such-key");
});

it("CAVEAT_TEXT — 全キー・全本文を固定する", () => {
  expect(CAVEAT_TEXT).toMatchInlineSnapshot(`
    {
      "aboveLod": "透明度の定量上限超え（原表記が「>1.4」〜「>28」など、26行）は、上限がどこまでか分からないという性質上、集計方法によらず値に含められない。件数（n）にも入らないため、他の期間・地点と単純に比較しないこと。",
      "amamiRedList": "奄美大島の赤リスト（絶滅危惧の区分）は、環境省の全国版だけを参照している。神奈川県の区分は県のレッドリストを含むが、鹿児島県のレッドリストはまだ収集していないため、同じ種でも県の評価は出ない。神奈川県の区分と並べて危険度を比べない。",
      "amamiWatershedGap": "奄美大島の流域は、国土数値情報 W12（1977年版）のポリゴンで決めている。W12 が覆わない部分（島の海岸部など）の記録は流域が空になり、流域ごとの集計には出ない。島全体の件数と流域別の合計は一致しない。",
      "censoredLod": "全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を定量下限値とみなして集計している（上限側の見積もり）。不検出（ND）は平均に含めない。折れ線では中抜きの点で示し、その定量下限値が実際に観測された値だとは読まないこと。",
      "duplicates": "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。",
      "ednaCoords": "eDNA の地点の座標は推定。公開データに座標が無いため、支川名と市町村から河川線の上に推定した（誤差は最大 10 km、地点ごとの誤差は coordinate_uncertainty_m）。座標の無い地点もある。",
      "ednaNonDetect": "eDNA の不検出は「その採水でその DNA が検出されなかった」ことを示すだけで、その種がいないことは示さない。不在の根拠にしないこと。",
      "ednaReads": "eDNA の値はリード数（DNA の配列が読まれた数）で、個体数・生物量を表さない。地点・年度の間でリード数の大小を比べて、多い少ないを読まないこと。",
      "ednaWatershed": "流域は、採水地点の推定座標が流域ポリゴンに入るかで決めている。座標の無い地点はどの流域にも入らない。推定の誤差は最大 10 km なので、流域の境界近くの地点は隣の流域に数えられていることがある。",
      "ednaYearBasis": "eDNA は年度・ファイルごとに解析方法・参照データベース・収録基準が違う（例: R7 の県民調査は一致率 98.5% 以上の結果のみ）。件数を年度で並べると見かけの増減が出る。",
      "effort": "生物観察の件数は観察努力（観察に参加した人や調査の回数）に強く影響される。記録者を特定する列は大半が空（GBIF の約89%、iNaturalist は全件）で、記録者数そのものは測れていない。件数の増加をそのまま「生物が増えた」と読んではいけない。",
      "effortSurvey": "検出数・目撃数は、年ごとの調査・報告の回数と範囲に左右される。件数の増減を生息数の増減と読まない。",
      "flowTidalBackflow": "河川の流量。感潮域（全83地点のうち14地点）では潮汐による逆流で負の値になる（4,668行のうち180行、最小 -8.5 m3/s）。負の値は欠測や誤りではなく逆流を表す実測値なので、除外したり絶対値にしたりして平均しないこと。",
      "gbifCutoff": "GBIF 側の取り込みは 2024年12月で実質途切れている（月の件数が2024年12月の6,789件から2025年1月に399件へ。2024年の月平均は約6,400件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。",
      "isAlien": "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には、記録の学名（二名法）を環境省の生態系被害防止外来種リストに結合した結果を使っている。ただし国内由来のみの種（国内の別地域の個体群など。神奈川県では在来の可能性がある）は外来種に数えない。",
      "landuseDefinitionChange": "土地利用の区分は2006年調査と2016年調査で定義が違う。2006年の「幹線交通用地」は2016年調査で「道路」「鉄道」に分割されており、同じ区分として比較できない。この2区分が2006年→2016年で全減・全増に見えるのは、実際の土地利用の変化ではなく調査区分の定義変更による見かけ上の増減である。",
      "measuredOn": "measurements.measured_on には「2015-04-08」形式（検体値・215,445行）と「2015」形式（年度集計値・105,454行）が混在する（合成データを除く）。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。",
      "municipality": "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。",
      "organismSite": "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。流域に割り当てられない記録（流域外・未解決）が、日付のある記録の約10%（83,515件/816,856件）ある。",
      "regimes": "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。",
      "share": "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。",
      "synthetic": "合成データ（デモ用に生成したもの）。実在の公開データではない。",
      "unitUnknown": "この指標のうち、原本に単位の記載が無い出典は、レジストリでも単位を確定できていない。該当する値は原本の数値のまま示しており、推測で換算していない（相模原市の1時間値 RAIN は0.1mm刻みの可能性があるが未確定のまま）。単位が判明している出典の値と混同しないこと。",
      "zone": "zone は地形から機械的に付けた操作的区分で、公式の区分ではない。標高の低い島（奄美大島など）では山地（zone 2）が陸の大半を占め、低地（zone 4）はほとんど現れない。これは定義の結果で、凡例・名称は地域によらず共通である。zone 1（山地で、標高が地域の最高峰の半分以上）には水質データが無い。",
    }
  `);
});
