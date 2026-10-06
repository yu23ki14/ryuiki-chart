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

export type CaveatScopeKind = "variable" | "place" | "source_edition" | "observation_set" | "dataset" | "taxon";

/**
 * caveat の既知のキー18件の union（docs/plans/PHASE_B_INTAKE.md #6）。
 * 画面・`web/src/lib/ai/prompt.ts` が `caveatBody(key)`（lookup-client.ts）を直接
 * 呼ぶときの型で、存在しないキーはここでコンパイルエラーになる（旧 domain.ts の
 * mustCaveatBody() は実行時例外だった）。
 */
export type CaveatKey = "aboveLod" | "censoredLod" | "duplicates" | "effort" | "fishClass" | "flowTidalBackflow" | "gbifCutoff" | "inatBackfill" | "isAlien" | "landuseDefinitionChange" | "measuredOn" | "municipality" | "organismSite" | "regimes" | "share" | "synthetic" | "unitUnknown" | "zone";

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

/** region（`jp-14` 等）の時刻帯（registry/region.yaml。Issue #32-3、ADR-0024）。 */
export interface GeneratedRegionTime {
  regionId: string;
  /** IANA 時刻帯名（例 `Asia/Tokyo`）。 */
  tzName: string;
  /** UTC オフセット（`+HH:MM`/`-HH:MM`）。 */
  utcOffset: string;
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
  "流量関連（公式定義未確認のため原表記のまま）": "河川の流量",
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
  "common:variable:hydro.flow": { short: "流量", note: "河川の流量", higherIsWorse: null },
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
  "Ursus thibetanus": "ツキノワグマ",
};

/**
 * 注記18件（registry/caveat.yaml）。cells.notes 由来（207件）は含めない。
 * key は caveat_id から "common:caveat:" を外したもの
 * （web/src/lib/ai/caveats.ts が今返しているキー文字列と同じ）。
 */
export const GENERATED_CAVEATS: readonly GeneratedCaveat[] = [
  { key: "aboveLod", severity: "blocking", kind: "censoring", bodyJa: "透明度の定量上限超え（原表記が「>1.4」〜「>28」など、26行）は、上限がどこまでか分からないという性質上、集計方法によらず値に含められない。件数（n）にも入らないため、他の期間・地点と単純に比較しないこと。" },
  { key: "censoredLod", severity: "blocking", kind: "censoring", bodyJa: "全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を定量下限値とみなして集計している（上限側の見積もり）。不検出（ND）は平均に含めない。折れ線では中抜きの点で示し、その定量下限値が実際に観測された値だとは読まないこと。" },
  { key: "duplicates", severity: "info", kind: null, bodyJa: "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。" },
  { key: "effort", severity: "blocking", kind: null, bodyJa: "生物観察の件数は観察努力（観察に参加した人や調査の回数）に強く影響される。記録者を特定する列は大半が空（GBIF の約89%、iNaturalist は全件）で、記録者数そのものは測れていない。件数の増加をそのまま「生物が増えた」と読んではいけない。" },
  { key: "fishClass", severity: "info", kind: null, bodyJa: "魚類は class 列に現れない（Actinopterygii が入っておらず空になっている）。門が Chordata で綱が空のものを魚類として扱っている。" },
  { key: "flowTidalBackflow", severity: "warning", kind: null, bodyJa: "河川の流量。感潮域（全83地点のうち14地点）では潮汐による逆流で負の値になる（4,668行のうち180行、最小 -8.5 m3/s）。負の値は欠測や誤りではなく逆流を表す実測値なので、除外したり絶対値にしたりして平均しないこと。" },
  { key: "gbifCutoff", severity: "blocking", kind: "coverage_gap", bodyJa: "GBIF 側の取り込みは 2024年12月で実質途切れている（月の件数が2024年12月の6,789件から2025年1月に399件へ。2024年の月平均は約6,400件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。" },
  { key: "inatBackfill", severity: "info", kind: null, bodyJa: "iNaturalist 由来の 165,332 件は分類階級が空だったため、学名の先頭2語をキーに GBIF 側の分類を引き当てて補完している（先頭2語の一致が約71%、属だけの一致が約15%、未解決が約14%）。" },
  { key: "isAlien", severity: "blocking", kind: "known_error", bodyJa: "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には、記録の学名（二名法）を環境省の生態系被害防止外来種リストに結合した結果を使っている。ただし国内由来のみの種（国内の別地域の個体群など。神奈川県では在来の可能性がある）は外来種に数えない。" },
  { key: "landuseDefinitionChange", severity: "blocking", kind: "definition_change", bodyJa: "土地利用の区分は2006年調査と2016年調査で定義が違う。2006年の「幹線交通用地」は2016年調査で「道路」「鉄道」に分割されており、同じ区分として比較できない。この2区分が2006年→2016年で全減・全増に見えるのは、実際の土地利用の変化ではなく調査区分の定義変更による見かけ上の増減である。" },
  { key: "measuredOn", severity: "info", kind: null, bodyJa: "measurements.measured_on には「2015-04-08」形式（検体値・215,445行）と「2015」形式（年度集計値・105,454行）が混在する（合成データを除く）。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。" },
  { key: "municipality", severity: "info", kind: null, bodyJa: "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。" },
  { key: "organismSite", severity: "warning", kind: null, bodyJa: "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。流域に割り当てられない記録（流域外・未解決）が、日付のある記録の約10%（83,515件/816,856件）ある。" },
  { key: "regimes", severity: "blocking", kind: "time_series_break", bodyJa: "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。" },
  { key: "share", severity: "warning", kind: null, bodyJa: "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。" },
  { key: "synthetic", severity: "blocking", kind: "synthetic", bodyJa: "合成データ（デモ用に生成したもの）。実在の公開データではない。" },
  { key: "unitUnknown", severity: "blocking", kind: "unit_change", bodyJa: "この指標のうち、原本に単位の記載が無い出典は、レジストリでも単位を確定できていない。該当する値は原本の数値のまま示しており、推測で換算していない（相模原市の1時間値 RAIN は0.1mm刻みの可能性があるが未確定のまま）。単位が判明している出典の値と混同しないこと。" },
  { key: "zone", severity: "info", kind: null, bodyJa: "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。" },
];

/**
 * 注記キー -> 範囲（scope）。caveat_scope の scope_kind は ADR-0013 の語彙
 * ('variable', 'place', 'source_edition', 'observation_set', 'dataset', 'taxon')。scopeRef は ID か `キー=値` の選択式
 * （registry/caveat_scope.yaml が宣言。照合は文字列の完全一致）。cells.notes 由来は含めない。
 * 引くのは `lib/cube/caveats.ts` の `caveatsForFacets`。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder（宣言順）。scope 同士の並びは
 * 呼び出し側が渡す facet の順序と priority（既定0。synthetic だけ1で最優先）に従う
 * （scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = [
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "censoredLod", sortOrder: 1, priority: 0 },
  { scopeKind: "dataset", scopeRef: "measurements", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "dataset", scopeRef: "organism_records", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "dataset", scopeRef: "sites", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "dataset", scopeRef: "sites", caveatKey: "municipality", sortOrder: 1, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "is_synthetic=1", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:air.photochemical_oxidant&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:water.water_temp&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:weather.precipitation&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:weather.weather_summary_day&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:weather.weather_summary_night&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:weather.wind_direction_at_gust&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "observation_set", scopeRef: "variable=common:variable:weather.wind_direction_at_max&unit_id=null", caveatKey: "unitUnknown", sortOrder: 0, priority: 0 },
  { scopeKind: "place", scopeRef: "place_kind=grid01", caveatKey: "share", sortOrder: 0, priority: 0 },
  { scopeKind: "place", scopeRef: "place_kind=grid01", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "place", scopeRef: "place_kind=site", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "place", scopeRef: "place_kind=site", caveatKey: "municipality", sortOrder: 1, priority: 0 },
  { scopeKind: "place", scopeRef: "place_kind=zone", caveatKey: "zone", sortOrder: 0, priority: 0 },
  { scopeKind: "source_edition", scopeRef: "source_id=moe_ias_list", caveatKey: "isAlien", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:hydro.flow", caveatKey: "flowTidalBackflow", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "common:variable:water.transparency", caveatKey: "aboveLod", sortOrder: 0, priority: 0 },
  { scopeKind: "variable", scopeRef: "theme=landuse", caveatKey: "landuseDefinitionChange", sortOrder: 0, priority: 0 },
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

/** region の時刻帯（registry/region.yaml の語彙。`lookup-client.ts` の `regionTimeZone()` が引く）。 */
export const REGION_TIME: readonly GeneratedRegionTime[] = [
  { regionId: "jp-14", tzName: "Asia/Tokyo", utcOffset: "+09:00" },
];
