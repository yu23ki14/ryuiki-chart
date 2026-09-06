/**
 * 生成物。直接編集しない。サーバ専用（unit / variable / variable_alias の生テーブル）。
 *
 * 再生成: `cd web && npm run build:registry:ts`
 * 生成元: `web/scripts/build-registry-ts.mjs`（data/db/registry.sqlite から作る）。
 *
 * クライアントバンドルに含めないこと。ここを import してよいのは
 * `web/src/lib/registry/lookup.ts`（server-only ではないが、D1 から引く大きい
 * テーブルを持つためクライアントコンポーネントから import しない）だけ。
 * クライアント安全な語彙定数（VARIABLE_SHORT 等）・caveat は
 * `./generated-client.ts` を使う。
 *
 * docs/plans/PHASE_A.md §A-7 / code-review #4（クライアントバンドル+65KB問題）
 */

export interface GeneratedUnit {
  unitId: string;
  symbol: string | null;
  ucum: string | null;
  nameJa: string | null;
  quantityKind: string | null;
}

export interface GeneratedVariable {
  variableId: string;
  code: string | null;
  nameJa: string | null;
  nameEn: string | null;
  theme: string | null;
  unitId: string | null;
  valueType: string | null;
  defaultStat: string | null;
  higherIsWorse: boolean | null;
  descriptionJa: string | null;
  status: string | null;
}

export interface GeneratedVariableAlias {
  alias: string;
  sourceScope: string | null;
  variableId: string | null;
  unitId: string | null;
  stat: string | null;
  grain: string | null;
}

/** measurements.unit 9種 + sensor_timeseries.unit 22種を正準化したもの（registry/unit.yaml）。 */
export const GENERATED_UNITS: readonly GeneratedUnit[] = [
  { unitId: "common:unit:0_01ppmc", symbol: "0.01ppmC", ucum: null, nameJa: "ppmC(炭素換算した百万分率)の1/100単位の原表記。実値は本値×0.01（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "volume_fraction" },
  { unitId: "common:unit:0_1degc", symbol: "0.1℃", ucum: null, nameJa: "セ氏度の1/10単位の原表記。実値は本値×0.1（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "temperature" },
  { unitId: "common:unit:0_1m_per_s", symbol: "0.1m/s", ucum: null, nameJa: "メートル毎秒の1/10単位の原表記。実値は本値×0.1（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "velocity" },
  { unitId: "common:unit:0_1mm", symbol: "0.1mm", ucum: null, nameJa: "ミリメートルの1/10単位の原表記。実値は本値×0.1（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "length" },
  { unitId: "common:unit:0_1percent", symbol: "0.1%", ucum: null, nameJa: "パーセントの1/10単位の原表記。実値は本値×0.1（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "fraction" },
  { unitId: "common:unit:0_1ppm", symbol: "0.1ppm", ucum: null, nameJa: "ppmの1/10単位の原表記。実値は本値×0.1（平塚市大気環境データ仕様書に基づく。換算はしていない）", quantityKind: "volume_fraction" },
  { unitId: "common:unit:cfu_per_100ml", symbol: "CFU/100mL", ucum: null, nameJa: "コロニー形成単位毎100ミリリットル（大腸菌数）", quantityKind: "microbial_density" },
  { unitId: "common:unit:cm", symbol: "cm", ucum: "cm", nameJa: "センチメートル", quantityKind: "length" },
  { unitId: "common:unit:count", symbol: "点", ucum: null, nameJa: "地点数（可算・地盤沈下観測の水準点数）", quantityKind: "count" },
  { unitId: "common:unit:days", symbol: "days", ucum: null, nameJa: "日数（可算・現象のあった日数）", quantityKind: "count" },
  { unitId: "common:unit:degc", symbol: "degC", ucum: "Cel", nameJa: "セ氏度", quantityKind: "temperature" },
  { unitId: "common:unit:dimensionless", symbol: null, ucum: "1", nameJa: "無次元（pH 等）", quantityKind: "dimensionless" },
  { unitId: "common:unit:h", symbol: "h", ucum: "h", nameJa: "時間", quantityKind: "time" },
  { unitId: "common:unit:hpa", symbol: "hPa", ucum: "hPa", nameJa: "ヘクトパスカル", quantityKind: "pressure" },
  { unitId: "common:unit:km2", symbol: "km2", ucum: "km2", nameJa: "平方キロメートル", quantityKind: "area" },
  { unitId: "common:unit:m", symbol: "m", ucum: "m", nameJa: "メートル", quantityKind: "length" },
  { unitId: "common:unit:m3_per_m3", symbol: "m3/m3", ucum: "m3/m3", nameJa: "立方メートル毎立方メートル（体積含水率）", quantityKind: "volume_fraction" },
  { unitId: "common:unit:m_per_s", symbol: "m/s", ucum: "m/s", nameJa: "メートル毎秒", quantityKind: "velocity" },
  { unitId: "common:unit:mg_per_l", symbol: "mg/L", ucum: "mg/L", nameJa: "ミリグラム毎リットル", quantityKind: "mass_concentration" },
  { unitId: "common:unit:mg_per_m3", symbol: "mg/m3", ucum: "mg/m3", nameJa: "ミリグラム毎立方メートル", quantityKind: "mass_concentration" },
  { unitId: "common:unit:mm", symbol: "mm", ucum: "mm", nameJa: "ミリメートル", quantityKind: "length" },
  { unitId: "common:unit:mpn_per_100ml", symbol: "MPN/100mL", ucum: null, nameJa: "最確数毎100ミリリットル（大腸菌群数）", quantityKind: "microbial_density" },
  { unitId: "common:unit:percent", symbol: "percent", ucum: "%", nameJa: "パーセント", quantityKind: "fraction" },
  { unitId: "common:unit:ppb", symbol: "ppb", ucum: "[ppb]", nameJa: "十億分率", quantityKind: "volume_fraction" },
  { unitId: "common:unit:ppm", symbol: "ppm", ucum: "[ppm]", nameJa: "百万分率", quantityKind: "volume_fraction" },
  { unitId: "common:unit:t_p_m", symbol: "T.P. m", ucum: null, nameJa: "東京湾平均海面(T.P.)基準の標高（メートル）", quantityKind: "elevation" },
  { unitId: "common:unit:tenths", symbol: "tenths", ucum: null, nameJa: "10分比（雲量の目視観測階級。0〜10）", quantityKind: "fraction" },
  { unitId: "common:unit:ug_per_m3", symbol: "ug/m3", ucum: "ug/m3", nameJa: "マイクログラム毎立方メートル", quantityKind: "mass_concentration" },
];

/** 正準の指標（registry/variable.yaml）。名前から単位・粒度・統計量を剥がした後の形。 */
export const GENERATED_VARIABLES: readonly GeneratedVariable[] = [
  { variableId: "common:variable:air.ch4", code: "air.ch4", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:0_01ppmc", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.co", code: "air.co", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:0_1ppm", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.nmhc", code: "air.nmhc", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:0_01ppmc", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.no", code: "air.no", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ppb", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.no2", code: "air.no2", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ppb", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.nox", code: "air.nox", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ppb", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.photochemical_oxidant", code: "air.photochemical_oxidant", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ppb", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.pm25", code: "air.pm25", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ug_per_m3", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.so2", code: "air.so2", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ppb", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.spm", code: "air.spm", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:ug_per_m3", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:air.thc", code: "air.thc", nameJa: null, nameEn: null, theme: "air", unitId: "common:unit:0_01ppmc", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:hydro.flow", code: "hydro.flow", nameJa: "流量関連", nameEn: null, theme: "hydro", unitId: null, valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "needs_review" },
  { variableId: "common:variable:hydro.groundwater_level", code: "hydro.groundwater_level", nameJa: null, nameEn: null, theme: "hydro", unitId: "common:unit:t_p_m", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:hydro.river_stage", code: "hydro.river_stage", nameJa: null, nameEn: null, theme: "hydro", unitId: "common:unit:m", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:hydro.soil_moisture", code: "hydro.soil_moisture", nameJa: null, nameEn: null, theme: "hydro", unitId: "common:unit:m3_per_m3", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.benchmark_count_settled_1_2cm", code: "land.benchmark_count_settled_1_2cm", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:count", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.benchmark_count_settled_2cm_plus", code: "land.benchmark_count_settled_2cm_plus", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:count", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.benchmark_count_valid", code: "land.benchmark_count_valid", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:count", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.max_subsidence", code: "land.max_subsidence", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:cm", valueType: "num", defaultStat: "max", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.subsidence_area_1_2cm", code: "land.subsidence_area_1_2cm", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:km2", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.subsidence_area_2cm_plus", code: "land.subsidence_area_2cm_plus", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:km2", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:land.survey_area", code: "land.survey_area", nameJa: null, nameEn: null, theme: "land", unitId: "common:unit:km2", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.111_trichloroethane", code: "water.111_trichloroethane", nameJa: "1,1,1-トリクロロエタン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.112_trichloroethane", code: "water.112_trichloroethane", nameJa: "1,1,2-トリクロロエタン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.11_dichloroethylene", code: "water.11_dichloroethylene", nameJa: "1,1-ジクロロエチレン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.12_dichloroethane", code: "water.12_dichloroethane", nameJa: "1,2-ジクロロエタン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.13_dichloropropene", code: "water.13_dichloropropene", nameJa: "1,3-ジクロロプロペン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.14_dioxane", code: "water.14_dioxane", nameJa: "1,4-ジオキサン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.alkyl_mercury", code: "water.alkyl_mercury", nameJa: "アルキル水銀", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.arsenic", code: "water.arsenic", nameJa: "砒素", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.benzene", code: "water.benzene", nameJa: "ベンゼン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.bod", code: "water.bod", nameJa: "BOD", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: "微生物が有機物を分解するのに使う酸素量。大きいほど有機汚濁が進んでいる", status: "ok" },
  { variableId: "common:variable:water.boron", code: "water.boron", nameJa: "ホウ素", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.cadmium", code: "water.cadmium", nameJa: "カドミウム", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.carbon_tetrachloride", code: "water.carbon_tetrachloride", nameJa: "四塩化炭素", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.cis12_dichloroethylene", code: "water.cis12_dichloroethylene", nameJa: "シス-1,2-ジクロロエチレン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.cod", code: "water.cod", nameJa: "COD", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: "酸化剤で有機物を分解したときの消費酸素量。湖沼・海域の指標として使われる", status: "ok" },
  { variableId: "common:variable:water.coliform_group", code: "water.coliform_group", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mpn_per_100ml", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: "し尿等による汚染の指標。2022年度以降は「大腸菌数」に移行しつつある", status: "ok" },
  { variableId: "common:variable:water.cyanide", code: "water.cyanide", nameJa: "全シアン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.dichloromethane", code: "water.dichloromethane", nameJa: "ジクロロメタン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.do", code: "water.do", nameJa: "DO", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: false, descriptionJa: "水に溶けている酸素。小さいほど生き物が棲みにくい。水温が上がると下がる", status: "ok" },
  { variableId: "common:variable:water.do_bottom", code: "water.do_bottom", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.ecoli", code: "water.ecoli", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:cfu_per_100ml", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.fluorine", code: "water.fluorine", nameJa: "ふっ素", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.hexavalent_chromium", code: "water.hexavalent_chromium", nameJa: "六価クロム", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.las", code: "water.las", nameJa: "LAS", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.lead", code: "water.lead", nameJa: "鉛", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.n_hexane_extract", code: "water.n_hexane_extract", nameJa: "n-ヘキサン抽出物質", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.nitrate_nitrite_n", code: "water.nitrate_nitrite_n", nameJa: "硝酸性窒素及び亜硝酸性窒素", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.nonylphenol", code: "water.nonylphenol", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.pcb", code: "water.pcb", nameJa: "PCB", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.ph", code: "water.ph", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:dimensionless", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.selenium", code: "water.selenium", nameJa: "セレン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.simazine", code: "water.simazine", nameJa: "シマジン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.ss", code: "water.ss", nameJa: "SS", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: "水に浮いている細かい粒子の量。降雨で土砂が入ると上がる", status: "ok" },
  { variableId: "common:variable:water.tetrachloroethylene", code: "water.tetrachloroethylene", nameJa: "テトラクロロエチレン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.thiobencarb", code: "water.thiobencarb", nameJa: "チオベンカルブ", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.thiuram", code: "water.thiuram", nameJa: "チウラム", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.tn", code: "water.tn", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.total_mercury", code: "water.total_mercury", nameJa: "総水銀", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.total_zinc", code: "water.total_zinc", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: "水生生物の保全に係る環境基準項目", status: "ok" },
  { variableId: "common:variable:water.tp", code: "water.tp", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: "mean", higherIsWorse: true, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.transparency", code: "water.transparency", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:m", valueType: "num", defaultStat: "mean", higherIsWorse: false, descriptionJa: "湖沼・海域で円板が見えなくなる深さ", status: "ok" },
  { variableId: "common:variable:water.trichloroethylene", code: "water.trichloroethylene", nameJa: "トリクロロエチレン", nameEn: null, theme: "water", unitId: "common:unit:mg_per_l", valueType: "num", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:water.water_temp", code: "water.water_temp", nameJa: null, nameEn: null, theme: "water", unitId: "common:unit:degc", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: "採水時の水温", status: "ok" },
  { variableId: "common:variable:weather.air_temp", code: "weather.air_temp", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:degc", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.cloud_cover_mean", code: "weather.cloud_cover_mean", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:tenths", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.days_with_fog", code: "weather.days_with_fog", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:days", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.days_with_snow", code: "weather.days_with_snow", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:days", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.days_with_thunder", code: "weather.days_with_thunder", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:days", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.humidity", code: "weather.humidity", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:percent", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.precipitation", code: "weather.precipitation", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:mm", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.pressure_sea_level", code: "weather.pressure_sea_level", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:hpa", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.pressure_station", code: "weather.pressure_station", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:hpa", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.snow_depth_max", code: "weather.snow_depth_max", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:cm", valueType: "num", defaultStat: "max", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.snowfall_depth_max_daily", code: "weather.snowfall_depth_max_daily", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:cm", valueType: "num", defaultStat: "max", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.snowfall_depth_total", code: "weather.snowfall_depth_total", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:cm", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.sunshine_duration", code: "weather.sunshine_duration", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:h", valueType: "num", defaultStat: "sum", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.weather_summary_day", code: "weather.weather_summary_day", nameJa: null, nameEn: null, theme: "weather", unitId: null, valueType: "category", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.weather_summary_night", code: "weather.weather_summary_night", nameJa: null, nameEn: null, theme: "weather", unitId: null, valueType: "category", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.wind_direction_at_gust", code: "weather.wind_direction_at_gust", nameJa: null, nameEn: null, theme: "weather", unitId: null, valueType: "category", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.wind_direction_at_max", code: "weather.wind_direction_at_max", nameJa: null, nameEn: null, theme: "weather", unitId: null, valueType: "category", defaultStat: null, higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.wind_gust_max", code: "weather.wind_gust_max", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:m_per_s", valueType: "num", defaultStat: "max", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.wind_speed_max", code: "weather.wind_speed_max", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:m_per_s", valueType: "num", defaultStat: "max", higherIsWorse: null, descriptionJa: null, status: "ok" },
  { variableId: "common:variable:weather.wind_speed_mean", code: "weather.wind_speed_mean", nameJa: null, nameEn: null, theme: "weather", unitId: "common:unit:m_per_s", valueType: "num", defaultStat: "mean", higherIsWorse: null, descriptionJa: null, status: "ok" },
];

/** 出典表記 -> 正準 variable の対応（registry/variable_alias.csv）。 */
export const GENERATED_VARIABLE_ALIASES: readonly GeneratedVariableAlias[] = [
  { alias: "生物化学的酸素要求量 BOD", sourceScope: "measurements", variableId: "common:variable:water.bod", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "BOD 75%値", sourceScope: "measurements", variableId: "common:variable:water.bod", unitId: null, stat: "p75", grain: "fiscal_year" },
  { alias: "化学的酸素要求量 COD", sourceScope: "measurements", variableId: "common:variable:water.cod", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "COD 75%値", sourceScope: "measurements", variableId: "common:variable:water.cod", unitId: null, stat: "p75", grain: "fiscal_year" },
  { alias: "溶存酸素量 DO", sourceScope: "measurements", variableId: "common:variable:water.do", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "底層溶存酸素量", sourceScope: "measurements", variableId: "common:variable:water.do_bottom", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "浮遊物質量 SS", sourceScope: "measurements", variableId: "common:variable:water.ss", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "全窒素 T-N", sourceScope: "measurements", variableId: "common:variable:water.tn", unitId: null, stat: null, grain: "fiscal_year" },
  { alias: "全燐 T-P", sourceScope: "measurements", variableId: "common:variable:water.tp", unitId: null, stat: null, grain: "fiscal_year" },
  { alias: "pH", sourceScope: "measurements", variableId: "common:variable:water.ph", unitId: "common:unit:dimensionless", stat: "point", grain: "mixed" },
  { alias: "pH（最大値）", sourceScope: "measurements", variableId: "common:variable:water.ph", unitId: "common:unit:dimensionless", stat: "max", grain: "fiscal_year" },
  { alias: "pH（最小値）", sourceScope: "measurements", variableId: "common:variable:water.ph", unitId: "common:unit:dimensionless", stat: "min", grain: "fiscal_year" },
  { alias: "大腸菌群数", sourceScope: "measurements", variableId: "common:variable:water.coliform_group", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "大腸菌数", sourceScope: "measurements", variableId: "common:variable:water.ecoli", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "大腸菌数 90%値", sourceScope: "measurements", variableId: "common:variable:water.ecoli", unitId: null, stat: "p90", grain: "fiscal_year" },
  { alias: "全亜鉛", sourceScope: "measurements", variableId: "common:variable:water.total_zinc", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "ノルマルヘキサン抽出物質", sourceScope: "measurements", variableId: "common:variable:water.n_hexane_extract", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "直鎖アルキルベンゼンスルホン酸及びその塩 LAS", sourceScope: "measurements", variableId: "common:variable:water.las", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "ノニルフェノール", sourceScope: "measurements", variableId: "common:variable:water.nonylphenol", unitId: null, stat: "mean", grain: "mixed" },
  { alias: "水温", sourceScope: "measurements", variableId: "common:variable:water.water_temp", unitId: null, stat: "point", grain: "day" },
  { alias: "透明度", sourceScope: "measurements", variableId: "common:variable:water.transparency", unitId: null, stat: "point", grain: "day" },
  { alias: "気温", sourceScope: "measurements", variableId: "common:variable:weather.air_temp", unitId: null, stat: "point", grain: "day" },
  { alias: "cd", sourceScope: "measurements", variableId: "common:variable:water.cadmium", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "cn", sourceScope: "measurements", variableId: "common:variable:water.cyanide", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "pb", sourceScope: "measurements", variableId: "common:variable:water.lead", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "cr6", sourceScope: "measurements", variableId: "common:variable:water.hexavalent_chromium", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "ass", sourceScope: "measurements", variableId: "common:variable:water.arsenic", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "thg", sourceScope: "measurements", variableId: "common:variable:water.total_mercury", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "srhg", sourceScope: "measurements", variableId: "common:variable:water.alkyl_mercury", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "pcb", sourceScope: "measurements", variableId: "common:variable:water.pcb", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "jikurorometan", sourceScope: "measurements", variableId: "common:variable:water.dichloromethane", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "sienkatanso", sourceScope: "measurements", variableId: "common:variable:water.carbon_tetrachloride", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "jikuroroetan12", sourceScope: "measurements", variableId: "common:variable:water.12_dichloroethane", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "jikuroroechiren11", sourceScope: "measurements", variableId: "common:variable:water.11_dichloroethylene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "s12jikuroroetiren", sourceScope: "measurements", variableId: "common:variable:water.cis12_dichloroethylene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "torikuroroetan111", sourceScope: "measurements", variableId: "common:variable:water.111_trichloroethane", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "torikuroroetan112", sourceScope: "measurements", variableId: "common:variable:water.112_trichloroethane", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "torikuroroechiren", sourceScope: "measurements", variableId: "common:variable:water.trichloroethylene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "tetorakuroroechiren", sourceScope: "measurements", variableId: "common:variable:water.tetrachloroethylene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "jikuroropuropen13", sourceScope: "measurements", variableId: "common:variable:water.13_dichloropropene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "chiraumu", sourceScope: "measurements", variableId: "common:variable:water.thiuram", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "shimajin", sourceScope: "measurements", variableId: "common:variable:water.simazine", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "chiobenkarubu", sourceScope: "measurements", variableId: "common:variable:water.thiobencarb", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "benzen", sourceScope: "measurements", variableId: "common:variable:water.benzene", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "seren", sourceScope: "measurements", variableId: "common:variable:water.selenium", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "nno3", sourceScope: "measurements", variableId: "common:variable:water.nitrate_nitrite_n", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "f", sourceScope: "measurements", variableId: "common:variable:water.fluorine", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "b", sourceScope: "measurements", variableId: "common:variable:water.boron", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "n14jiokisan", sourceScope: "measurements", variableId: "common:variable:water.14_dioxane", unitId: "common:unit:mg_per_l", stat: null, grain: "fiscal_year" },
  { alias: "流量関連（公式定義未確認のため原表記のまま）", sourceScope: "measurements", variableId: "common:variable:hydro.flow", unitId: null, stat: null, grain: "day" },
  { alias: "地下水位(年平均)", sourceScope: "measurements", variableId: "common:variable:hydro.groundwater_level", unitId: "common:unit:t_p_m", stat: "mean", grain: "year" },
  { alias: "最大沈下量(基準点)", sourceScope: "measurements", variableId: "common:variable:land.max_subsidence", unitId: "common:unit:cm", stat: "max", grain: "year" },
  { alias: "有効水準点数", sourceScope: "measurements", variableId: "common:variable:land.benchmark_count_valid", unitId: "common:unit:count", stat: null, grain: "year" },
  { alias: "沈下水準点数(1cm以上2cm未満)", sourceScope: "measurements", variableId: "common:variable:land.benchmark_count_settled_1_2cm", unitId: "common:unit:count", stat: null, grain: "year" },
  { alias: "沈下水準点数(2cm以上)", sourceScope: "measurements", variableId: "common:variable:land.benchmark_count_settled_2cm_plus", unitId: "common:unit:count", stat: null, grain: "year" },
  { alias: "沈下面積(1cm以上2cm未満)", sourceScope: "measurements", variableId: "common:variable:land.subsidence_area_1_2cm", unitId: "common:unit:km2", stat: null, grain: "year" },
  { alias: "沈下面積(2cm以上)", sourceScope: "measurements", variableId: "common:variable:land.subsidence_area_2cm_plus", unitId: "common:unit:km2", stat: null, grain: "year" },
  { alias: "調査面積", sourceScope: "measurements", variableId: "common:variable:land.survey_area", unitId: "common:unit:km2", stat: null, grain: "year" },
  { alias: "water_temperature", sourceScope: "sensor_timeseries", variableId: "common:variable:water.water_temp", unitId: null, stat: null, grain: "hour" },
  { alias: "河川水位_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:hydro.river_stage", unitId: "common:unit:m", stat: "mean", grain: "day" },
  { alias: "河川水位_日最高", sourceScope: "sensor_timeseries", variableId: "common:variable:hydro.river_stage", unitId: "common:unit:m", stat: "max", grain: "day" },
  { alias: "soil_moisture", sourceScope: "sensor_timeseries", variableId: "common:variable:hydro.soil_moisture", unitId: "common:unit:m3_per_m3", stat: null, grain: "hour" },
  { alias: "NO2(ppm)", sourceScope: "sensor_timeseries", variableId: "common:variable:air.no2", unitId: "common:unit:ppm", stat: null, grain: "hour" },
  { alias: "二酸化窒素（NO2）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.no2", unitId: "common:unit:ppb", stat: "mean", grain: "day" },
  { alias: "SO2(ppm)", sourceScope: "sensor_timeseries", variableId: "common:variable:air.so2", unitId: "common:unit:ppm", stat: null, grain: "hour" },
  { alias: "二酸化硫黄（SO2）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.so2", unitId: "common:unit:ppb", stat: "mean", grain: "day" },
  { alias: "一酸化窒素（NO）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.no", unitId: "common:unit:ppb", stat: "mean", grain: "day" },
  { alias: "窒素酸化物（NOx）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.nox", unitId: "common:unit:ppb", stat: "mean", grain: "day" },
  { alias: "OX", sourceScope: "sensor_timeseries", variableId: "common:variable:air.photochemical_oxidant", unitId: null, stat: null, grain: "hour" },
  { alias: "Ox(ppm)", sourceScope: "sensor_timeseries", variableId: "common:variable:air.photochemical_oxidant", unitId: "common:unit:ppm", stat: null, grain: "hour" },
  { alias: "光化学オキシダント（Ox）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.photochemical_oxidant", unitId: "common:unit:ppb", stat: "mean", grain: "day" },
  { alias: "SPM(mg/m3)", sourceScope: "sensor_timeseries", variableId: "common:variable:air.spm", unitId: "common:unit:mg_per_m3", stat: null, grain: "hour" },
  { alias: "浮遊粒子状物質（SPM）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.spm", unitId: "common:unit:ug_per_m3", stat: "mean", grain: "day" },
  { alias: "PM2.5(μg/m3)", sourceScope: "sensor_timeseries", variableId: "common:variable:air.pm25", unitId: "common:unit:ug_per_m3", stat: null, grain: "hour" },
  { alias: "微小粒子状物質（PM2.5）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.pm25", unitId: "common:unit:ug_per_m3", stat: "mean", grain: "day" },
  { alias: "一酸化炭素（CO）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.co", unitId: "common:unit:0_1ppm", stat: "mean", grain: "day" },
  { alias: "メタン（CH4）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.ch4", unitId: "common:unit:0_01ppmc", stat: "mean", grain: "day" },
  { alias: "非メタン炭化水素（NMHC）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.nmhc", unitId: "common:unit:0_01ppmc", stat: "mean", grain: "day" },
  { alias: "全炭化水素（THC）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:air.thc", unitId: "common:unit:0_01ppmc", stat: "mean", grain: "day" },
  { alias: "RAIN", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: null, stat: null, grain: "hour" },
  { alias: "気温_平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "mean", grain: "day" },
  { alias: "気温_平均_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "mean", grain: "month" },
  { alias: "気温_平均_日最低", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "mean_of_daily_min", grain: "month" },
  { alias: "気温_平均_日最高", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "mean_of_daily_max", grain: "month" },
  { alias: "気温_最低", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "min", grain: "mixed" },
  { alias: "気温_最高", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:degc", stat: "max", grain: "mixed" },
  { alias: "温度（TEMP）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.air_temp", unitId: "common:unit:0_1degc", stat: "mean", grain: "day" },
  { alias: "降水量_合計", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: "common:unit:mm", stat: "sum", grain: "mixed" },
  { alias: "降水量_最大_10分間", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: "common:unit:mm", stat: "max_10min", grain: "mixed" },
  { alias: "降水量_最大_1時間", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: "common:unit:mm", stat: "max_1h", grain: "mixed" },
  { alias: "降水量_最大_日", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: "common:unit:mm", stat: "max_daily", grain: "month" },
  { alias: "雨量（RAIN）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.precipitation", unitId: "common:unit:0_1mm", stat: "mean", grain: "day" },
  { alias: "湿度_平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.humidity", unitId: "common:unit:percent", stat: "mean", grain: "mixed" },
  { alias: "湿度_最小", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.humidity", unitId: "common:unit:percent", stat: "min", grain: "mixed" },
  { alias: "湿度（HUM）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.humidity", unitId: "common:unit:0_1percent", stat: "mean", grain: "day" },
  { alias: "気圧_現地_平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.pressure_station", unitId: "common:unit:hpa", stat: "mean", grain: "mixed" },
  { alias: "気圧_海面_平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.pressure_sea_level", unitId: "common:unit:hpa", stat: "mean", grain: "mixed" },
  { alias: "日照 時間", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.sunshine_duration", unitId: "common:unit:h", stat: "sum", grain: "mixed" },
  { alias: "風向・風速_平均 風速", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_speed_mean", unitId: "common:unit:m_per_s", stat: "mean", grain: "mixed" },
  { alias: "風速（WS）_日平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_speed_mean", unitId: "common:unit:0_1m_per_s", stat: "mean", grain: "day" },
  { alias: "風向・風速_最大風速_風速", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_speed_max", unitId: "common:unit:m_per_s", stat: "max", grain: "mixed" },
  { alias: "風向・風速_最大風速_風向", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_direction_at_max", unitId: null, stat: null, grain: "mixed" },
  { alias: "風向・風速_最大瞬間風速_風速", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_gust_max", unitId: "common:unit:m_per_s", stat: "max", grain: "mixed" },
  { alias: "風向・風速_最大瞬間風速_風向", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.wind_direction_at_gust", unitId: null, stat: null, grain: "mixed" },
  { alias: "雪_最深 積雪", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snow_depth_max", unitId: "common:unit:cm", stat: "max", grain: "month" },
  { alias: "雪_最深積雪", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snow_depth_max", unitId: "common:unit:cm", stat: "max", grain: "month" },
  { alias: "雪_最深積雪_値", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snow_depth_max", unitId: "common:unit:cm", stat: "max", grain: "day" },
  { alias: "雪_降雪_合計", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snowfall_depth_total", unitId: "common:unit:cm", stat: "sum", grain: "mixed" },
  { alias: "雪_降雪の深さ_合計", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snowfall_depth_total", unitId: "common:unit:cm", stat: "sum", grain: "month" },
  { alias: "雪_降雪_日合計の最大", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snowfall_depth_max_daily", unitId: "common:unit:cm", stat: "max_daily", grain: "month" },
  { alias: "雪_降雪の深さ_日合計の最大", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.snowfall_depth_max_daily", unitId: "common:unit:cm", stat: "max_daily", grain: "month" },
  { alias: "雲量_平均", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.cloud_cover_mean", unitId: "common:unit:tenths", stat: "mean", grain: "month" },
  { alias: "大気現象_雪日数", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.days_with_snow", unitId: "common:unit:days", stat: "sum", grain: "month" },
  { alias: "大気現象_霧日数", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.days_with_fog", unitId: "common:unit:days", stat: "sum", grain: "month" },
  { alias: "大気現象_雷日数", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.days_with_thunder", unitId: "common:unit:days", stat: "sum", grain: "month" },
  { alias: "天気概況_昼 (06:00-18:00)", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.weather_summary_day", unitId: null, stat: null, grain: "day" },
  { alias: "天気概況_夜 (18:00-翌日06:00)", sourceScope: "sensor_timeseries", variableId: "common:variable:weather.weather_summary_night", unitId: null, stat: null, grain: "day" },
];
