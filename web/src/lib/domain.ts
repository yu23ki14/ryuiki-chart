/**
 * 領域知識。データ探索で分かった「原本の癖」をここに集約する。
 * 画面側で個別に補正を書かないための場所。
 */

/** 水質項目の短い表示名（原本の variable は長いものがある） */
export const VARIABLE_SHORT: Record<string, string> = {
  "生物化学的酸素要求量 BOD": "BOD",
  "化学的酸素要求量 COD": "COD",
  "溶存酸素量 DO": "DO",
  "浮遊物質量 SS": "SS",
  "直鎖アルキルベンゼンスルホン酸及びその塩 LAS": "LAS",
  "ノルマルヘキサン抽出物質": "n-ヘキサン抽出物質",
  "流量関連（公式定義未確認のため原表記のまま）": "流量関連",
};

/** 単位が原本で NULL の項目に、既知のものだけ補う（推測はしない） */
export const VARIABLE_UNIT_FALLBACK: Record<string, string> = {
  pH: "",
  "pH（最大値）": "",
  "pH（最小値）": "",
};

export function shortVariable(v: string): string {
  return VARIABLE_SHORT[v] ?? v;
}

/** 何を意味する指標か。ツールチップに出す。 */
export const VARIABLE_NOTE: Record<string, string> = {
  "生物化学的酸素要求量 BOD": "微生物が有機物を分解するのに使う酸素量。大きいほど有機汚濁が進んでいる",
  "化学的酸素要求量 COD": "酸化剤で有機物を分解したときの消費酸素量。湖沼・海域の指標として使われる",
  "溶存酸素量 DO": "水に溶けている酸素。小さいほど生き物が棲みにくい。水温が上がると下がる",
  "浮遊物質量 SS": "水に浮いている細かい粒子の量。降雨で土砂が入ると上がる",
  全亜鉛: "水生生物の保全に係る環境基準項目",
  大腸菌群数: "し尿等による汚染の指標。2022年度以降は「大腸菌数」に移行しつつある",
  水温: "採水時の水温",
  透明度: "湖沼・海域で円板が見えなくなる深さ",
};

/** 上流→下流でこの向きに動くのが「悪化」か。矢印の向きに使う。 */
export const HIGHER_IS_WORSE: Record<string, boolean> = {
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
};

export const ZONE_INFO = [
  { zone: 1, label: "山地源流域", cond: "標高 800m 超" },
  { zone: 2, label: "山地渓流", cond: "標高 400–800m" },
  { zone: 3, label: "丘陵・扇状地", cond: "標高 100–400m" },
  { zone: 4, label: "平野・沖積低地", cond: "標高 100m 以下・海岸から 2km 超" },
  { zone: 5, label: "河口・沿岸", cond: "標高 100m 以下・海岸から 2km 以内" },
] as const;

export const QUALITY_STAGES = ["暫定", "検証済", "公開済"] as const;
export type QualityStage = (typeof QUALITY_STAGES)[number];

/**
 * `sites.municipality` は出典によって中身が違う。
 * 環境省 公共用水域の 290 地点では水域名（河川名・湖沼名）が入り、
 * それ以外の 62 地点では市区町村名が入る。列名と中身が一致していないので、
 * 画面では「水域・地域」と呼ぶ。
 */
export const MUNICIPALITY_LABEL = "水域・地域";

/** 原本の癖。画面の注記に出して、読み手が誤解しないようにする。 */
export const DATA_CAVEATS = {
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
} as const;

/**
 * 和名の辞書（本デモで付与したもの）。
 *
 * organism_records に和名は入っておらず（vernacular_name は英名）、
 * taxa テーブルの和名を学名で機械結合すると別地域の個体群の名前が付いてしまう
 * （例: Plecoglossus altivelis に「リュウキュウアユ」）。
 * そのため、画面に出す代表種についてだけ人が確認した和名をここに持つ。
 * ここに無い種は学名と英名だけを表示し、和名を推測しない。
 */
export const NAME_JA: Record<string, string> = {
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

export function speciesLabel(binom: string, enName?: string | null): string {
  const ja = NAME_JA[binom];
  if (ja) return ja;
  return enName || binom;
}

/** 生物データの観察努力に関する事実（画面に必ず添える） */
export const BIOTA_CAVEATS = {
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
} as const;

/**
 * 行政文書から抽出した表の行キーは、表によって行見出しと列見出しが連結されている
 * （例: `湘南地域秦野市伊勢原市|清川村`）。信頼できるのは最後の `|` の後ろだけなので、
 * 表示名にはそこを使う。原文の行キーは別途そのまま見せる。
 */
export function rowKeyLabel(rowKey: string): string {
  if (!rowKey) return "";
  const i = rowKey.lastIndexOf("|");
  const tail = i >= 0 ? rowKey.slice(i + 1) : rowKey;
  return tail.trim() || rowKey;
}
