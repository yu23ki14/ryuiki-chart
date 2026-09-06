/**
 * 生成物。直接編集しない。
 *
 * 再生成: `cd web && npm run build:registry:ts`
 * 生成元: `web/scripts/build-registry-ts.mjs`（data/db/registry.sqlite と
 * registry/taxon/vernacular_ja.csv から作る）。
 *
 * クライアント安全（'server-only' は付けない。証跡カードなどクライアント
 * コンポーネントからも import される）。D1 から動的に引く必要があるもの
 * （taxon 全体・place・cells.notes 由来の caveat）はここには無い。
 * 読み出しは `web/src/lib/registry/index.ts`（server-only）を使う。
 *
 * docs/plans/PHASE_A.md §A-7
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

export type CaveatScopeKind = "table" | "table_prefix" | "table_synthetic";

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
}

export interface GeneratedVernacular {
  scientificName: string;
  vernacularNameJa: string;
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
 * テーブル -> 注記キーのスコープ（caveat_scope の scope_kind in
 * ('table','table_prefix','table_synthetic')）。cell/cell_table（cells.notes 由来）は含めない。
 * 同じ (scopeKind, scopeRef) の中の並びは sortOrder。scope 同士（渡されたテーブル間）の並びは
 * 呼び出し側がテーブル名を渡す順序に従う（scripts/registry/build_caveat.py の docstring参照）。
 */
export const GENERATED_CAVEAT_SCOPE: readonly GeneratedCaveatScope[] = [
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "effort_year", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "ias_species", caveatKey: "isAlien", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "meas_clim", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "meas_daily", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "meas_month", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "meas_year", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "measurements", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "org_group_year", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "org_norm", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "org_watershed", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "org_watershed_year", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "organism_records", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "site_var", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "sites", caveatKey: "zone", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "sites", caveatKey: "municipality", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "species2", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "species_mesh_year", caveatKey: "share", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "species_mesh_year", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "species_month", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "organismSite", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "regimes", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "gbifCutoff", sortOrder: 3 },
  { scopeKind: "table", scopeRef: "species_year2", caveatKey: "share", sortOrder: 4 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "var_catalog", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "zone_clim", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "measuredOn", sortOrder: 0 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "censored", sortOrder: 1 },
  { scopeKind: "table", scopeRef: "zone_year", caveatKey: "duplicates", sortOrder: 2 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "share", sortOrder: 0 },
  { scopeKind: "table_prefix", scopeRef: "mesh_", caveatKey: "effort", sortOrder: 1 },
  { scopeKind: "table_synthetic", scopeRef: "decisions", caveatKey: "synthetic", sortOrder: 0 },
  { scopeKind: "table_synthetic", scopeRef: "event_observers", caveatKey: "synthetic", sortOrder: 0 },
  { scopeKind: "table_synthetic", scopeRef: "interventions", caveatKey: "synthetic", sortOrder: 0 },
  { scopeKind: "table_synthetic", scopeRef: "observers", caveatKey: "synthetic", sortOrder: 0 },
  { scopeKind: "table_synthetic", scopeRef: "quality_monthly", caveatKey: "synthetic", sortOrder: 0 },
  { scopeKind: "table_synthetic", scopeRef: "quality_transitions", caveatKey: "synthetic", sortOrder: 0 },
];

/**
 * 和名54件（registry/taxon/vernacular_ja.csv、domain.ts の NAME_JA をそのまま複製した台帳）。
 * taxon テーブル全体の vernacular_name_ja（8,324件、taxa 由来の別の母集団）とは別物。
 */
export const GENERATED_VERNACULAR_JA: readonly GeneratedVernacular[] = [
  { scientificName: "Hypsipetes amaurotis", vernacularNameJa: "ヒヨドリ" },
  { scientificName: "Passer montanus", vernacularNameJa: "スズメ" },
  { scientificName: "Corvus corone", vernacularNameJa: "ハシボソガラス" },
  { scientificName: "Corvus macrorhynchos", vernacularNameJa: "ハシブトガラス" },
  { scientificName: "Egretta garzetta", vernacularNameJa: "コサギ" },
  { scientificName: "Ardea intermedia", vernacularNameJa: "チュウサギ" },
  { scientificName: "Ardea cinerea", vernacularNameJa: "アオサギ" },
  { scientificName: "Fulica atra", vernacularNameJa: "オオバン" },
  { scientificName: "Alcedo atthis", vernacularNameJa: "カワセミ" },
  { scientificName: "Garrulax canorus", vernacularNameJa: "ガビチョウ" },
  { scientificName: "Leiothrix lutea", vernacularNameJa: "ソウシチョウ" },
  { scientificName: "Aythya fuligula", vernacularNameJa: "キンクロハジロ" },
  { scientificName: "Aythya ferina", vernacularNameJa: "ホシハジロ" },
  { scientificName: "Anas acuta", vernacularNameJa: "オナガガモ" },
  { scientificName: "Mareca penelope", vernacularNameJa: "ヒドリガモ" },
  { scientificName: "Mareca strepera", vernacularNameJa: "オカヨシガモ" },
  { scientificName: "Zosterops japonicus", vernacularNameJa: "メジロ" },
  { scientificName: "Cyanopica cyanus", vernacularNameJa: "オナガ" },
  { scientificName: "Motacilla cinerea", vernacularNameJa: "キセキレイ" },
  { scientificName: "Alauda arvensis", vernacularNameJa: "ヒバリ" },
  { scientificName: "Phasianus versicolor", vernacularNameJa: "キジ" },
  { scientificName: "Podiceps cristatus", vernacularNameJa: "カンムリカイツブリ" },
  { scientificName: "Psittacula krameri", vernacularNameJa: "ワカケホンセイインコ" },
  { scientificName: "Delichon dasypus", vernacularNameJa: "イワツバメ" },
  { scientificName: "Apus nipalensis", vernacularNameJa: "ヒメアマツバメ" },
  { scientificName: "Columba livia", vernacularNameJa: "カワラバト（ドバト）" },
  { scientificName: "Coccothraustes coccothraustes", vernacularNameJa: "シメ" },
  { scientificName: "Emberiza rustica", vernacularNameJa: "カシラダカ" },
  { scientificName: "Trichonephila clavata", vernacularNameJa: "ジョロウグモ" },
  { scientificName: "Harmonia axyridis", vernacularNameJa: "ナミテントウ" },
  { scientificName: "Hestina assimilis", vernacularNameJa: "アカボシゴマダラ" },
  { scientificName: "Callosciurus erythraeus", vernacularNameJa: "タイワンリス" },
  { scientificName: "Solidago altissima", vernacularNameJa: "セイタカアワダチソウ" },
  { scientificName: "Trachemys scripta", vernacularNameJa: "アカミミガメ" },
  { scientificName: "Coreopsis lanceolata", vernacularNameJa: "オオキンケイギク" },
  { scientificName: "Procambarus clarkii", vernacularNameJa: "アメリカザリガニ" },
  { scientificName: "Lithobates catesbeianus", vernacularNameJa: "ウシガエル" },
  { scientificName: "Procyon lotor", vernacularNameJa: "アライグマ" },
  { scientificName: "Paguma larvata", vernacularNameJa: "ハクビシン" },
  { scientificName: "Nipponoluciola cruciata", vernacularNameJa: "ゲンジボタル" },
  { scientificName: "Plecoglossus altivelis", vernacularNameJa: "アユ" },
  { scientificName: "Cyprinus carpio", vernacularNameJa: "コイ" },
  { scientificName: "Zacco platypus", vernacularNameJa: "オイカワ" },
  { scientificName: "Pseudorasbora parva", vernacularNameJa: "モツゴ" },
  { scientificName: "Lepomis macrochirus", vernacularNameJa: "ブルーギル" },
  { scientificName: "Micropterus salmoides", vernacularNameJa: "オオクチバス" },
  { scientificName: "Cobitis biwae", vernacularNameJa: "シマドジョウ" },
  { scientificName: "Anguilla japonica", vernacularNameJa: "ニホンウナギ" },
  { scientificName: "Cervus nippon", vernacularNameJa: "ニホンジカ" },
  { scientificName: "Bidens pilosa", vernacularNameJa: "オオバナセンダングサ" },
  { scientificName: "Persicaria capitata", vernacularNameJa: "ヒメツルソバ" },
  { scientificName: "Oenothera laciniata", vernacularNameJa: "コマツヨイグサ" },
  { scientificName: "Robinia pseudoacacia", vernacularNameJa: "ハリエンジュ" },
  { scientificName: "Pomacea canaliculata", vernacularNameJa: "スクミリンゴガイ" },
];
