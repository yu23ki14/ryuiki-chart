/**
 * 生成物。直接編集しない。クライアント安全（'server-only' は付けない。
 * 証跡カードなどクライアントコンポーネントからも import される）。
 *
 * 再生成: `cd web && npm run build:registry:ts`
 * 生成元: `web/scripts/build-registry-ts.mjs`（data/db/registry.sqlite と
 * registry/taxon/vernacular_ja.csv・registry/place/zone.yaml から作る。派生値の組み立ては
 * `web/scripts/lib/registry-codegen.mjs`）。
 *
 * VARIABLE_SHORT 等は、生の variable(85件)/variable_alias(117件) テーブルから
 * 「代表エイリアス」を選んで再構成した派生値であり、生テーブルそのものではない
 * （レビュー指摘・code-review #4: 以前は旧 domain.ts が実行時にこの再構成を
 * 行っており、その結果クライアントバンドルに生テーブル全体が乗っていた）。生テーブルが
 * 要る場合は `./generated.ts`（サーバ専用）を使う。
 *
 * D1 から動的に引く必要があるもの（taxon 全体・place・cells.notes 由来の caveat）は
 * ここには無い。読み出しは `web/src/lib/registry/index.ts`（server-only）を使う。
 *
 * docs/plans/PHASE_A.md §A-7 / code-review #4 / docs/plans/PHASE_B_INTAKE.md #6
 */

export interface GeneratedVernacular {
  scientificName: string;
  vernacularNameJa: string;
}

export type CaveatScopeKind = "table" | "table_prefix" | "dataset" | "place_kind" | "source_id" | "variable_theme" | "variable";

/**
 * caveat の既知のキー18件の union（docs/plans/PHASE_B_INTAKE.md #6）。
 * 画面・`web/src/lib/ai/prompt.ts` が `caveatBody(key)`（lookup-client.ts）を直接
 * 呼ぶときの型で、存在しないキーはここでコンパイルエラーになる（旧 domain.ts の
 * mustCaveatBody() は実行時例外だった）。
 */
export type CaveatKey = "aboveLod" | "censored" | "censoredLod" | "duplicates" | "effort" | "fishClass" | "gbifCutoff" | "inatBackfill" | "isAlien" | "landuseDefinitionChange" | "measuredOn" | "municipality" | "organismSite" | "regimes" | "share" | "synthetic" | "unitUnknown" | "zone";

export interface GeneratedCaveat {
  key: string;
  severity: string | null;
  kind: string | null;
  bodyJa: string;
}

export interface GeneratedCaveatScope {
  scopeKind: CaveatScopeKind;
  scopeRef: string;
  caveatKey: string;
  sortOrder: number;
  /** 優先度（既定0・大きいほど優先）。synthetic 由来の scope 行だけ1。
   * scope_kind ではなくこの列が「先頭に出すべきか」を表す（docs/plans/PHASE_A.md §A-7、
   * scripts/registry/build_caveat.py の docstring）。 */
  priority: number;
}

/** Ridge to Reef ゾーン(1-5)。registry/place/zone.yaml から作る（旧 domain.ts の ZONE_INFO）。 */
export interface GeneratedZone {
  zone: number;
  label: string;
  cond: string;
}

/** `REDLIST_CATEGORY` の1エントリ（Issue #48 PR-3b §2.4）。rank が null は「前回記載なし」。 */
export interface GeneratedRedlistCategory {
  labelJa: string;
  rank: number | null;
  scope: string;
}

/** `ASSESSMENT_LIST` の1エントリ（Issue #48 PR-3b §2.4）。 */
export interface GeneratedAssessmentList {
  name: string;
  year: number;
  kind: string;
  region: string;
  codelist: string | null;
}

/** `VARIABLE_LABEL` の1エントリ（Issue #48 PR-2、docs/plans/V2_SERVING_PR2.md §5）。 */
export interface GeneratedVariableLabel {
  short: string;
  note: string | null;
  higherIsWorse: boolean | null;
}

/**
 * 水質項目の短い表示名（旧 domain.ts の VARIABLE_SHORT）。
 * variable(85件)・variable_alias(117件)から「代表エイリアス」を選んで再構成した派生値。
 */
export const VARIABLE_SHORT: Readonly<Record<string, string>> = {
  "流量関連（公式定義未確認のため原表記のまま）": "流量",
  "生物化学的酸素要求量 BOD": "BOD",
  "化学的酸素要求量 COD": "COD",
  "溶存酸素量 DO": "DO",
  "直鎖アルキルベンゼンスルホン酸及びその塩 LAS": "LAS",
  "ノルマルヘキサン抽出物質": "n-ヘキサン抽出物質",
  "浮遊物質量 SS": "SS",
};

/** 何を意味する指標か（旧 domain.ts の VARIABLE_NOTE）。ツールチップに出す。 */
export const VARIABLE_NOTE: Readonly<Record<string, string>> = {
  "流量関連（公式定義未確認のため原表記のまま）": "河川の流量。感潮域では潮汐による逆流で負の値になる",
  "生物化学的酸素要求量 BOD": "微生物が有機物を分解するのに使う酸素量。大きいほど有機汚濁が進んでいる",
  "化学的酸素要求量 COD": "酸化剤で有機物を分解したときの消費酸素量。湖沼・海域の指標として使われる",
  "大腸菌群数": "し尿等による汚染の指標。2022年度以降は「大腸菌数」に移行しつつある",
  "溶存酸素量 DO": "水に溶けている酸素。小さいほど生き物が棲みにくい。水温が上がると下がる",
  "浮遊物質量 SS": "水に浮いている細かい粒子の量。降雨で土砂が入ると上がる",
  "全亜鉛": "水生生物の保全に係る環境基準項目",
  "透明度": "湖沼・海域で円板が見えなくなる深さ",
  "水温": "採水時の水温",
};

/** 上流→下流でこの向きに動くのが「悪化」か（旧 domain.ts の HIGHER_IS_WORSE）。 */
export const HIGHER_IS_WORSE: Readonly<Record<string, boolean>> = {
  "生物化学的酸素要求量 BOD": true,
  "化学的酸素要求量 COD": true,
  "大腸菌群数": true,
  "溶存酸素量 DO": false,
  "大腸菌数": true,
  "浮遊物質量 SS": true,
  "全窒素 T-N": true,
  "全亜鉛": true,
  "全燐 T-P": true,
  "透明度": false,
};

/** 単位が原本で NULL の項目に既知のものだけ補う（旧 domain.ts の VARIABLE_UNIT_FALLBACK）。 */
export const VARIABLE_UNIT_FALLBACK: Readonly<Record<string, string>> = {
  "pH": "",
  "pH（最大値）": "",
  "pH（最小値）": "",
};

/**
 * `variable_id` キーの表示ラベル（Issue #48 PR-2、docs/plans/V2_SERVING_PR2.md §5）。
 * `name_ja` が NULL の variable も代表エイリアスの表記へ落として必ず持つ
 * （上の VARIABLE_SHORT 等——alias キー版——とは選定規則が違う。
 * `web/scripts/lib/registry-codegen.mjs` の `buildVariableLabelMap()` docstring参照）。
 * 対象は dataset='measurements' の alias を1つ以上持つ variable のみ。
 */
export const VARIABLE_LABEL: Readonly<Record<string, GeneratedVariableLabel>> = {
  "common:variable:hydro.flow": { short: "流量", note: "河川の流量。感潮域では潮汐による逆流で負の値になる", higherIsWorse: null },
  "common:variable:hydro.groundwater_level": { short: "地下水位(年平均)", note: null, higherIsWorse: null },
  "common:variable:land.benchmark_count_settled_1_2cm": { short: "沈下水準点数(1cm以上2cm未満)", note: null, higherIsWorse: null },
  "common:variable:land.benchmark_count_settled_2cm_plus": { short: "沈下水準点数(2cm以上)", note: null, higherIsWorse: null },
  "common:variable:land.benchmark_count_valid": { short: "有効水準点数", note: null, higherIsWorse: null },
  "common:variable:land.max_subsidence": { short: "最大沈下量(基準点)", note: null, higherIsWorse: null },
  "common:variable:land.subsidence_area_1_2cm": { short: "沈下面積(1cm以上2cm未満)", note: null, higherIsWorse: null },
  "common:variable:land.subsidence_area_2cm_plus": { short: "沈下面積(2cm以上)", note: null, higherIsWorse: null },
  "common:variable:land.survey_area": { short: "調査面積", note: null, higherIsWorse: null },
  "common:variable:water.111_trichloroethane": { short: "1,1,1-トリクロロエタン", note: null, higherIsWorse: null },
  "common:variable:water.112_trichloroethane": { short: "1,1,2-トリクロロエタン", note: null, higherIsWorse: null },
  "common:variable:water.11_dichloroethylene": { short: "1,1-ジクロロエチレン", note: null, higherIsWorse: null },
  "common:variable:water.12_dichloroethane": { short: "1,2-ジクロロエタン", note: null, higherIsWorse: null },
  "common:variable:water.13_dichloropropene": { short: "1,3-ジクロロプロペン", note: null, higherIsWorse: null },
  "common:variable:water.14_dioxane": { short: "1,4-ジオキサン", note: null, higherIsWorse: null },
  "common:variable:water.alkyl_mercury": { short: "アルキル水銀", note: null, higherIsWorse: null },
  "common:variable:water.arsenic": { short: "砒素", note: null, higherIsWorse: null },
  "common:variable:water.benzene": { short: "ベンゼン", note: null, higherIsWorse: null },
  "common:variable:water.bod": { short: "BOD", note: "微生物が有機物を分解するのに使う酸素量。大きいほど有機汚濁が進んでいる", higherIsWorse: true },
  "common:variable:water.boron": { short: "ホウ素", note: null, higherIsWorse: null },
  "common:variable:water.cadmium": { short: "カドミウム", note: null, higherIsWorse: null },
  "common:variable:water.carbon_tetrachloride": { short: "四塩化炭素", note: null, higherIsWorse: null },
  "common:variable:water.cis12_dichloroethylene": { short: "シス-1,2-ジクロロエチレン", note: null, higherIsWorse: null },
  "common:variable:water.cod": { short: "COD", note: "酸化剤で有機物を分解したときの消費酸素量。湖沼・海域の指標として使われる", higherIsWorse: true },
  "common:variable:water.coliform_group": { short: "大腸菌群数", note: "し尿等による汚染の指標。2022年度以降は「大腸菌数」に移行しつつある", higherIsWorse: true },
  "common:variable:water.cyanide": { short: "全シアン", note: null, higherIsWorse: null },
  "common:variable:water.dichloromethane": { short: "ジクロロメタン", note: null, higherIsWorse: null },
  "common:variable:water.do": { short: "DO", note: "水に溶けている酸素。小さいほど生き物が棲みにくい。水温が上がると下がる", higherIsWorse: false },
  "common:variable:water.do_bottom": { short: "底層溶存酸素量", note: null, higherIsWorse: null },
  "common:variable:water.ecoli": { short: "大腸菌数", note: null, higherIsWorse: true },
  "common:variable:water.fluorine": { short: "ふっ素", note: null, higherIsWorse: null },
  "common:variable:water.hexavalent_chromium": { short: "六価クロム", note: null, higherIsWorse: null },
  "common:variable:water.las": { short: "LAS", note: null, higherIsWorse: null },
  "common:variable:water.lead": { short: "鉛", note: null, higherIsWorse: null },
  "common:variable:water.n_hexane_extract": { short: "n-ヘキサン抽出物質", note: null, higherIsWorse: null },
  "common:variable:water.nitrate_nitrite_n": { short: "硝酸性窒素及び亜硝酸性窒素", note: null, higherIsWorse: null },
  "common:variable:water.nonylphenol": { short: "ノニルフェノール", note: null, higherIsWorse: null },
  "common:variable:water.pcb": { short: "PCB", note: null, higherIsWorse: null },
  "common:variable:water.ph": { short: "pH", note: null, higherIsWorse: null },
  "common:variable:water.selenium": { short: "セレン", note: null, higherIsWorse: null },
  "common:variable:water.simazine": { short: "シマジン", note: null, higherIsWorse: null },
  "common:variable:water.ss": { short: "SS", note: "水に浮いている細かい粒子の量。降雨で土砂が入ると上がる", higherIsWorse: true },
  "common:variable:water.tetrachloroethylene": { short: "テトラクロロエチレン", note: null, higherIsWorse: null },
  "common:variable:water.thiobencarb": { short: "チオベンカルブ", note: null, higherIsWorse: null },
  "common:variable:water.thiuram": { short: "チウラム", note: null, higherIsWorse: null },
  "common:variable:water.tn": { short: "全窒素 T-N", note: null, higherIsWorse: true },
  "common:variable:water.total_mercury": { short: "総水銀", note: null, higherIsWorse: null },
  "common:variable:water.total_zinc": { short: "全亜鉛", note: "水生生物の保全に係る環境基準項目", higherIsWorse: true },
  "common:variable:water.tp": { short: "全燐 T-P", note: null, higherIsWorse: true },
  "common:variable:water.transparency": { short: "透明度", note: "湖沼・海域で円板が見えなくなる深さ", higherIsWorse: false },
  "common:variable:water.trichloroethylene": { short: "トリクロロエチレン", note: null, higherIsWorse: null },
  "common:variable:water.water_temp": { short: "水温", note: "採水時の水温", higherIsWorse: null },
  "common:variable:weather.air_temp": { short: "気温", note: null, higherIsWorse: null },
};

/**
 * 和名63件（registry/taxon/vernacular_ja.csv、旧 domain.ts の NAME_JA をそのまま複製した台帳）。
 * taxon テーブル全体の vernacular_name_ja（8,324件、taxa 由来の別の母集団）とは別物。
 */
export const NAME_JA: Readonly<Record<string, string>> = {
  "Hypsipetes amaurotis": "ヒヨドリ",
  "Passer montanus": "スズメ",
  "Corvus corone": "ハシボソガラス",
  "Corvus macrorhynchos": "ハシブトガラス",
  "Egretta garzetta": "コサギ",
  "Ardea intermedia": "チュウサギ",
  "Ardea cinerea": "アオサギ",
  "Fulica atra": "オオバン",
  "Alcedo atthis": "カワセミ",
  "Garrulax canorus": "ガビチョウ",
  "Leiothrix lutea": "ソウシチョウ",
  "Aythya fuligula": "キンクロハジロ",
  "Aythya ferina": "ホシハジロ",
  "Anas acuta": "オナガガモ",
  "Mareca penelope": "ヒドリガモ",
  "Mareca strepera": "オカヨシガモ",
  "Zosterops japonicus": "メジロ",
  "Cyanopica cyanus": "オナガ",
  "Motacilla cinerea": "キセキレイ",
  "Alauda arvensis": "ヒバリ",
  "Phasianus versicolor": "キジ",
  "Podiceps cristatus": "カンムリカイツブリ",
  "Psittacula krameri": "ワカケホンセイインコ",
  "Delichon dasypus": "イワツバメ",
  "Apus nipalensis": "ヒメアマツバメ",
  "Columba livia": "カワラバト（ドバト）",
  "Coccothraustes coccothraustes": "シメ",
  "Emberiza rustica": "カシラダカ",
  "Trichonephila clavata": "ジョロウグモ",
  "Harmonia axyridis": "ナミテントウ",
  "Hestina assimilis": "アカボシゴマダラ",
  "Callosciurus erythraeus": "タイワンリス",
  "Solidago altissima": "セイタカアワダチソウ",
  "Trachemys scripta": "アカミミガメ",
  "Coreopsis lanceolata": "オオキンケイギク",
  "Procambarus clarkii": "アメリカザリガニ",
  "Lithobates catesbeianus": "ウシガエル",
  "Procyon lotor": "アライグマ",
  "Paguma larvata": "ハクビシン",
  "Nipponoluciola cruciata": "ゲンジボタル",
  "Plecoglossus altivelis": "アユ",
  "Cyprinus carpio": "コイ",
  "Zacco platypus": "オイカワ",
  "Pseudorasbora parva": "モツゴ",
  "Lepomis macrochirus": "ブルーギル",
  "Micropterus salmoides": "オオクチバス",
  "Cobitis biwae": "シマドジョウ",
  "Anguilla japonica": "ニホンウナギ",
  "Cervus nippon": "ニホンジカ",
  "Bidens pilosa": "オオバナセンダングサ",
  "Persicaria capitata": "ヒメツルソバ",
  "Oenothera laciniata": "コマツヨイグサ",
  "Robinia pseudoacacia": "ハリエンジュ",
  "Pomacea canaliculata": "スクミリンゴガイ",
  "Nyctereutes procyonoides": "ホンドタヌキ",
  "Trypoxylus dichotomus": "カブトムシ",
  "Plestiodon japonicus": "ニホントカゲ",
  "Bufo japonicus": "アズマヒキガエル",
  "Protaetia brevitarsis": "シラホシハナムグリ",
  "Sus scrofa": "ニホンイノシシ",
  "Fejervarya kawamurai": "ヌマガエル",
  "Mustela itatsi": "ニホンイタチ",
  "Martes melampus": "ホンドテン",
};

/**
 * 注記18件（registry/caveat.yaml）。cells.notes 由来（207件）は含めない。
 * key は caveat_id から "common:caveat:" を外したもの
 * （web/src/lib/ai/caveats.ts が今返しているキー文字列と同じ）。
 */
export const GENERATED_CAVEATS: readonly GeneratedCaveat[] = [
  { key: "aboveLod", severity: "blocking", kind: "censoring", bodyJa: "透明度の定量上限超え（原表記が「>1.4」〜「>28」など、26行）は、上限がどこまでか分からないという性質上、集計方法によらず値に含められない。件数（n）にも入らないため、他の期間・地点と単純に比較しないこと。" },
  { key: "censored", severity: "blocking", kind: "censoring", bodyJa: "全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を 0 とみなして集計している。折れ線では中抜きの点で示し、「0 が観測された」とは読まないこと。" },
  { key: "censoredLod", severity: "blocking", kind: "censoring", bodyJa: "全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を定量下限値とみなして集計している（上限側の見積もり）。不検出（ND）は平均に含めない。折れ線では中抜きの点で示し、その定量下限値が実際に観測された値だとは読まないこと。" },
  { key: "duplicates", severity: null, kind: null, bodyJa: "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。" },
  { key: "effort", severity: "blocking", kind: null, bodyJa: "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。" },
  { key: "fishClass", severity: null, kind: "definition_change", bodyJa: "魚類は class 列に現れない（Actinopterygii が入っておらず空になっている）。門が Chordata で綱が空のものを魚類として扱っている。" },
  { key: "gbifCutoff", severity: "blocking", kind: "coverage_gap", bodyJa: "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。" },
  { key: "inatBackfill", severity: null, kind: "method_change", bodyJa: "iNaturalist 由来の 165,332 件は分類階級が空だったため、学名の先頭2語をキーに GBIF 側の分類を引き当てて補完している（96%が解決）。" },
  { key: "isAlien", severity: "blocking", kind: "known_error", bodyJa: "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。" },
  { key: "landuseDefinitionChange", severity: null, kind: "definition_change", bodyJa: "土地利用の区分は2006年調査と2016年調査で定義が違う。2006年の「幹線交通用地」は2016年調査で「道路」「鉄道」に分割されており、同じ区分として比較できない。この2区分が2006年→2016年で全減・全増に見えるのは、実際の土地利用の変化ではなく調査区分の定義変更による見かけ上の増減である。" },
  { key: "measuredOn", severity: null, kind: null, bodyJa: "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。" },
  { key: "municipality", severity: null, kind: null, bodyJa: "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。" },
  { key: "organismSite", severity: null, kind: null, bodyJa: "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。" },
  { key: "regimes", severity: "blocking", kind: "time_series_break", bodyJa: "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。" },
  { key: "share", severity: "blocking", kind: null, bodyJa: "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。" },
  { key: "synthetic", severity: "blocking", kind: "synthetic", bodyJa: "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。" },
  { key: "unitUnknown", severity: "blocking", kind: null, bodyJa: "この指標のうち、原本に単位の記載が無い出典は、レジストリでも単位を確定できていない。該当する値は原本の数値のまま示しており、推測で換算していない（相模原市の1時間値 RAIN は0.1mm刻みの可能性があるが未確定のまま）。単位が判明している出典の値と混同しないこと。" },
  { key: "zone", severity: null, kind: null, bodyJa: "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。" },
];

/**
 * テーブル/v2 facet -> 注記キーのスコープ（caveat_scope の scope_kind in
 * ('table', 'table_prefix', 'dataset', 'place_kind', 'source_id', 'variable_theme', 'variable')）。
 * cell/cell_table（cells.notes 由来）は含めない。'table'/'table_prefix' は v1
 * （`caveatsForTables`、テーブル名で引く）、'dataset'/'place_kind'/'source_id'/
 * 'variable_theme'/'variable' は v2（`lib/cube/caveats.ts` の `caveatsForFacets`、
 * キューブのセルから直接引く。Issue #48 PR-1b。'variable' の行は PR-2 で足した
 * `unitUnknown` の scope_ref=variable_id）。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder。scope 同士（渡されたテーブル間）の並びは
 * 呼び出し側がテーブル名を渡す順序と priority（既定0。synthetic だけ1で最優先）に従う
 * （scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = [
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "censoredLod", sortOrder: 1, priority: 0 },
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "dataset", scopeRef: "synthetic", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "place_kind", scopeRef: "grid01", caveatKey: "share", sortOrder: 0, priority: 0 },
  { scopeKind: "place_kind", scopeRef: "grid01", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "place_kind", scopeRef: "site", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "place_kind", scopeRef: "site", caveatKey: "municipality", sortOrder: 1, priority: 0 },
  { scopeKind: "place_kind", scopeRef: "zone", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "source_id", scopeRef: "moe_ias_list", caveatKey: "isAlien", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "decisions", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "event_observers", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "ias_species", caveatKey: "isAlien", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "interventions", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "landuse_change", caveatKey: "landuseDefinitionChange", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "landuse_watershed", caveatKey: "landuseDefinitionChange", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "observers", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "occurrence_place", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "quality_monthly", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "quality_transitions", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "sites", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "sites", caveatKey: "municipality", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "species_mesh_year", caveatKey: "share", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "species_mesh_year", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "aboveLod", sortOrder: 3, priority: 0 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "share", sortOrder: 0, priority: 0 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:air.photochemical_oxidant", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:hydro.flow", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:water.water_temp", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:weather.precipitation", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:weather.weather_summary_day", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:weather.weather_summary_night", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:weather.wind_direction_at_gust", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:weather.wind_direction_at_max", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "variable_theme", scopeRef: "landuse", caveatKey: "landuseDefinitionChange", sortOrder: 0, priority: 0 },
];

/**
 * レッドリストのカテゴリー（registry/taxon/redlist_category.yaml。Issue #48 PR-3b §2.4）。
 * キーは `taxon_assessment.category_code`/`prev_category_code`。`rank` は悪化/改善を比べる順序
 * （大きいほど深刻）で、`not_listed` だけ null（v1 の「前回記載なし」。direction の判定では順位なし）。
 */
export const REDLIST_CATEGORY: Readonly<Record<string, GeneratedRedlistCategory>> = {
  "EX": { labelJa: "絶滅", rank: 70, scope: "common" },
  "EW": { labelJa: "野生絶滅", rank: 65, scope: "common" },
  "CR": { labelJa: "絶滅危惧IA類", rank: 60, scope: "common" },
  "CR+EN": { labelJa: "絶滅危惧I類", rank: 55, scope: "common" },
  "EN": { labelJa: "絶滅危惧IB類", rank: 50, scope: "common" },
  "VU": { labelJa: "絶滅危惧II類", rank: 40, scope: "common" },
  "LP": { labelJa: "地域個体群", rank: 35, scope: "common" },
  "NT": { labelJa: "準絶滅危惧", rank: 30, scope: "common" },
  "RA": { labelJa: "希少種（2006年版）", rank: 25, scope: "jp-14" },
  "AT": { labelJa: "注目種", rank: 20, scope: "jp-14" },
  "DD": { labelJa: "情報不足", rank: 10, scope: "common" },
  "not_listed": { labelJa: "前回記載なし", rank: null, scope: "common" },
};

/**
 * 評価リストの台帳（registry/taxon/assessment_list.yaml。Issue #48 PR-3b §2.4）。
 * キーは `taxon_assessment.list_id`。`kind='red_list'` が県レッドリスト3版、`'invasive'` が外来種。
 */
export const ASSESSMENT_LIST: Readonly<Record<string, GeneratedAssessmentList>> = {
  "rl2020": { name: "神奈川県レッドリスト2020（植物編CSV）", year: 2020, kind: "red_list", region: "jp-14", codelist: "redlist_category" },
  "rdb2022p": { name: "神奈川県レッドデータブック2022（植物編）", year: 2022, kind: "red_list", region: "jp-14", codelist: "redlist_category" },
  "rl2026": { name: "神奈川県レッドリスト2026（昆虫類・クモ類）", year: 2026, kind: "red_list", region: "jp-14", codelist: "redlist_category" },
  "moe_ias_2015": { name: "環境省 生態系被害防止外来種リスト", year: 2015, kind: "invasive", region: "jp", codelist: null },
};

/** Ridge to Reef ゾーン(1-5)の定義（registry/place/zone.yaml、旧 domain.ts の ZONE_INFO）。 */
export const ZONE_INFO: readonly GeneratedZone[] = [
  { zone: 1, label: "山地源流域", cond: "標高 800m 超" },
  { zone: 2, label: "山地渓流", cond: "標高 400–800m" },
  { zone: 3, label: "丘陵・扇状地", cond: "標高 100–400m" },
  { zone: 4, label: "平野・沖積低地", cond: "標高 100m 以下・海岸から 2km 超" },
  { zone: 5, label: "河口・沿岸", cond: "標高 100m 以下・海岸から 2km 以内" },
];
