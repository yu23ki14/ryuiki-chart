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

export type CaveatScopeKind = "table" | "table_prefix";

/**
 * caveat の既知のキー14件の union（docs/plans/PHASE_B_INTAKE.md #6）。
 * 画面・`web/src/lib/ai/prompt.ts` が `caveatBody(key)`（lookup-client.ts）を直接
 * 呼ぶときの型で、存在しないキーはここでコンパイルエラーになる（旧 domain.ts の
 * mustCaveatBody() は実行時例外だった）。
 */
export type CaveatKey = "censored" | "duplicates" | "effort" | "fishClass" | "gbifCutoff" | "inatBackfill" | "isAlien" | "measuredOn" | "municipality" | "organismSite" | "regimes" | "share" | "synthetic" | "zone";

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
 * 和名54件（registry/taxon/vernacular_ja.csv、旧 domain.ts の NAME_JA をそのまま複製した台帳）。
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
};

/**
 * 注記14件（registry/caveat.yaml）。cells.notes 由来（207件）は含めない。
 * key は caveat_id から "common:caveat:" を外したもの
 * （web/src/lib/ai/caveats.ts が今返しているキー文字列と同じ）。
 */
export const GENERATED_CAVEATS: readonly GeneratedCaveat[] = [
  { key: "censored", severity: "blocking", kind: "censoring", bodyJa: "全体の約24%は定量下限未満（原表記が「<0.5」など）で、value 列には 0 が入っている。折れ線では中抜きの点で示し、平均には含めるが「0 が観測された」とは読まないこと。" },
  { key: "duplicates", severity: null, kind: null, bodyJa: "同一の地点・日・項目に複数行あるのは、原本が採水時刻を落としているため。ここでは日ごとに平均して1点にまとめている。" },
  { key: "effort", severity: "blocking", kind: null, bodyJa: "生物観察の件数は観察努力（記録した人の数）に強く影響される。件数の増加をそのまま「生物が増えた」と読んではいけない。" },
  { key: "fishClass", severity: null, kind: "definition_change", bodyJa: "魚類は class 列に現れない（Actinopterygii が入っておらず空になっている）。門が Chordata で綱が空のものを魚類として扱っている。" },
  { key: "gbifCutoff", severity: "blocking", kind: "coverage_gap", bodyJa: "GBIF 側の取り込みは 2024年12月で実質途切れている（2025年1月に月8,750件→399件）。鳥類の2025年以降の減少はデータの都合であり、生きものの減少ではない。" },
  { key: "inatBackfill", severity: null, kind: "method_change", bodyJa: "iNaturalist 由来の 165,332 件は分類階級が空だったため、学名の先頭2語をキーに GBIF 側の分類を引き当てて補完している（96%が解決）。" },
  { key: "isAlien", severity: "blocking", kind: "known_error", bodyJa: "原本の is_alien フラグは同一種の中で 1 と 0 が混在し、オオクチバスやウシガエルが 0 件になるなど信頼できない。外来種の判定には環境省の生態系被害防止外来種リスト（taxa.ias_category）を学名で結合した結果を使っている。" },
  { key: "measuredOn", severity: null, kind: null, bodyJa: "measurements.measured_on には「2015-04-08」形式（検体値・216,990行）と「2015」形式（年度集計値・98,328行）が混在する。年度集計値は日本の年度（4月〜翌3月）を指す。この画面では両者を kind で区別している。" },
  { key: "municipality", severity: null, kind: null, bodyJa: "sites.municipality は出典によって中身が違う。環境省 公共用水域の290地点では水域名（河川名・湖沼名）が入り、それ以外の62地点では市区町村名が入る。列名と中身が一致していないため、この画面では「水域・地域」と呼ぶ。" },
  { key: "organismSite", severity: null, kind: null, bodyJa: "生物レコードには site_id が無い（原本で全件 NULL）。流域への割り当ては緯度経度と国土数値情報 W12（1977年版）ポリゴンの点内包判定によるもので、原本の属性ではない。" },
  { key: "regimes", severity: "blocking", kind: "time_series_break", bodyJa: "記録の中身は年代で入れ替わっている。2013–2016 は標本由来の植物、2017–2024 は eBird 由来の鳥類、2025 以降は iNaturalist 由来の昆虫・植物・菌類が中心。分類群をまたいだ件数の比較はできない。" },
  { key: "share", severity: "blocking", kind: null, bodyJa: "件数そのものではなく、同じ分類群の中での割合（‰）で比べている。観察する人が増えれば件数は全種で一斉に増えるため、生の件数の増減には意味がない。" },
  { key: "synthetic", severity: "blocking", kind: "synthetic", bodyJa: "観測者・介入・意思決定・品質段階の遷移は合成データ（デモ用に生成したもの）。実在の公開データではない。" },
  { key: "zone", severity: null, kind: null, bodyJa: "ゾーンは標高と海岸線距離だけから機械的に付けた操作的定義であり、公式の区分ではない。zone 1（標高800m超）には水質データが無い。" },
];

/**
 * テーブル -> 注記キーのスコープ（caveat_scope の scope_kind in ('table','table_prefix')）。
 * cell/cell_table（cells.notes 由来）は含めない。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder。scope 同士（渡されたテーブル間）の並びは
 * 呼び出し側がテーブル名を渡す順序と priority（既定0。synthetic だけ1で最優先）に従う
 * （scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = [
  { scopeKind: "table", scopeRef: "decisions", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "organismSite", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "effort", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "regimes", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "gbifCutoff", sortOrder: 3, priority: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "share", sortOrder: 4, priority: 0 },
  { scopeKind: "table", scopeRef: "event_observers", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "ias_species", caveatKey: "isAlien", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "interventions", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "observers", caveatKey: "synthetic", sortOrder: 0, priority: 1 },
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
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "measuredOn", sortOrder: 0, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "censored", sortOrder: 1, priority: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "duplicates", sortOrder: 2, priority: 0 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "share", sortOrder: 0, priority: 0 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "effort", sortOrder: 1, priority: 0 },
];

/** Ridge to Reef ゾーン(1-5)の定義（registry/place/zone.yaml、旧 domain.ts の ZONE_INFO）。 */
export const ZONE_INFO: readonly GeneratedZone[] = [
  { zone: 1, label: "山地源流域", cond: "標高 800m 超" },
  { zone: 2, label: "山地渓流", cond: "標高 400–800m" },
  { zone: 3, label: "丘陵・扇状地", cond: "標高 100–400m" },
  { zone: 4, label: "平野・沖積低地", cond: "標高 100m 以下・海岸から 2km 超" },
  { zone: 5, label: "河口・沿岸", cond: "標高 100m 以下・海岸から 2km 以内" },
];
