# PR-1「問い合わせ層＋差分の道具（値は動かない）」実装設計

## 0. 要点（先に読む）

1. **PR-1 の範囲は「測定値系（PR-2 が使うもの）を完成させる」に絞る**。生物（`occurrence.ts`）は PR-3a/3b、文書・概況は PR-4 で足す。PR-1 で作る `lib/cube` は `db.ts` / `series.ts` / `observation.ts`（`queryCells`・`summarize`）/ `catalog.ts`（PR-1 は問い合わせ時計算、PR-2 で summary 表に差し替え）/ `envelope.ts` / `caveats.ts`。
2. **v1 と v2 の比較単位は「系列（variable_id, obs_stat, unit_id, value_grain, input_grain）」＝ v1 の alias 相当**にする。alias→variable_id の束ね（`water.bod` に 2 alias、`water.ph` に 3 alias 等）は PR-2 の「値が動く」変更であり、PR-1 で variable_id 単位に比べると 159 地点の n_var と var_catalog 58→53 行がいきなり差分になる。`summarize()` は「系列の集合を明示して受け取り、それを1グループに混ぜる」設計にし、PR-1 のアダプタは alias と同値な系列集合を、PR-2 の画面は「代表系列（obs_stat ∈ {mean, point}）」を渡す。
3. **serving-diff はローカル D1 ではなく sqlite ファイル直読み**（`derived.sqlite`＝v1、`v2.sqlite`＋`registry.sqlite`＋`ryuiki.sqlite`（`sites`/`source_registry`）＝v2）で回す。理由: (a) 日割り・合成データの分類に L2（`observation`）が要り D1 には無い、(b) 1.3GB のシードが不要で再現性が高い、(c) SQL 文は D1 と同じ非修飾テーブル名で書き ATTACH で解決するので、同じ SQL 文字列が D1 でもそのまま動く（`assertD1Compatible` で 100 パラメータ・LIKE 50 バイトを静的検査）。
4. **既知の系統の判定規則は「L2 から両方の流儀で再計算して等式で確かめる」**（宣言済み差分だけは `expected_diffs.yaml` のキー一致）。実測: 雨量は cube 3,653 日 vs v1 3,654 日、`/10` で 3,105 日一致、残り 548 日＋v1 のみ 1 日＝549 日が全て日割りで説明できる（L2 で検算済み）。`sensor_daily`（9,424 行）は **web に読み手が無い**ので serving-diff の対象外。流域メモ化（1,091 キー）・Sirosporium・合成データ除外は PR-1 の対象クエリには現れない（流域は `watershed_rollup` 経由で PR-3b。実測: v1 メモ化と正確な PIP で `org_watershed.n` が違う流域は 287 面中 185 面）。
5. **`caveat_scope` は v2 キー（`dataset` / `variable_theme` / `place_kind` / `source_id`）を既存の table キーと並存させる**（撤去は PR-5）。`caveatsForTables` は kind ∈ {table, table_prefix} だけを見る現行コードのままなので v1 の注記は1文字も変わらない（`caveats.test.ts` 34 ケース＋`generated.test.ts` の再生成一致で機械保証）。v2 側は `caveatsForFacets()` を新設し、「v1 表→facet」の橋渡し表で同じキー集合が出ることをテストする。
6. **単位（危険#5）の実測結果**: `unit_id NULL` のセルは alias 行の `unit_id` が空なのが原因で、`measurements` の alias 39 行中 38 行は原本が単位文字列（`mg/L` 等）を持ち、`variable.unit_id` の symbol と **全件一致（不一致 0）**。残り 1 行（`流量関連（公式定義未確認…）`）だけ原本にも単位が無い。よって「`variable_alias.unit_id ?? variable.unit_id`」の機械的フォールバックは流量で推測値 `m3/s` を出してしまう。**推奨: `registry/variable_alias.csv` の 38 行に unit_id を埋め（データ修正・値は動かない・キューブのキーだけ変わる）、serving 層はセルの `unit_id` だけを使い、NULL は「単位不明」として出す**。加えて v1 が unit NULL で v2 がレジストリ由来の単位を出す行（重金属系 `cd`/`pb` 等、104,410 観測行）が「ラベルだけの差分」として出るので、既知の系統に「単位ラベルのレジストリ補完（値は不変）」を1つ足す必要がある。
7. **手元の `data/db/v2.sqlite` と `registry.sqlite` は古い**（`check_v2_fresh.py` → exit 10、13 列キー・`pipeline_fingerprint` 無し。registry は `aboveLod` の scope 行が無い）。以下の実測はその古い v2 で取った（セル数は ADR-0009 追記どおり不変、`value`＝`value_zero`）。実装前に `cd web && pnpm run build:v2` で作り直すこと。

## 決めてほしいこと（最小限）

| # | 論点 | 推奨 |
|---|---|---|
| D1 | serving-diff の実行基盤を sqlite ファイル直読み（better-sqlite3）にする。D1 実装の実行は PR-2 の画面切り替え時のスモークで担保 | 採用 |
| D2 | 既知の系統に **(a)「単位ラベルのレジストリ補完（値は不変）」**（PR-1 から）と **(b)「系列の統合（alias→variable_id）」**（PR-2 から）を追加する。`sensor_daily 9,424 行` は読み手が無く serving-diff の対象外と明記 | 採用 |
| D3 | `registry/variable_alias.csv` の `measurements` alias 38 行に `unit_id` を埋める（値は動かない。キューブ再構築＋b00 証明更新が要るが PR-1b で registry を触るのでまとめて1回） | 採用（却下なら serving 層は `variable.unit_id` へフォールバックし、流量 1 alias の `m3/s` を既知差分に登録） |
| D4 | 合成データの v2 キー: `dataset='synthetic'` を「alias.source_id が NULL の系列」の規約で表す（PR-2 で合成を除いた後は自然に消える） | 採用 |
| D5 | PR-1 を worktree 3 本（1a 問い合わせ層 / 1b caveat＋registry / 1c serving-diff）で並行し、PR-0 と同じく1つの feature ブランチにまとめて1 PR にする | 採用 |

---

## 1. 棚卸し（web が今投げている問い合わせ）

凡例: PR-1 列は「PR-1 で `lib/cube` に実装するか」。✓＝実装、△＝インタフェースだけ、—＝後回し。

### 1.1 測定値系（PR-2 で切り替え）

| 呼び出し元 | v1 関数（`queries.ts`） | v1 表 | v2 の答え方 | PR-1 |
|---|---|---|---|---|
| `/timeseries` page, `list_catalog`, `/api/timeseries` | `variableCatalog()` | var_catalog | `catalog.variableCatalog()`＝年セル（stat=mean, place_kind=site, dataset=measurements）を系列で GROUP BY（PR-2 で `summary_variable_catalog` に差し替え） | ✓ |
| `/timeseries` page, `list_catalog(waters)` | `listWaterBodies()` / `waterBodiesForVariable(v)` | site_var+sites | `catalog.waterBodies({series?})`＝年セルを place→`sites.municipality` で GROUP BY | ✓ |
| `/api/timeseries mode=water`, `get_timeseries` | `sitesInWaterBody(name)` | sites+site_var | `catalog.sitesInWaterBody(name)`＝`sites` JOIN 年セル集計 | ✓ |
| `/api/timeseries`, `get_timeseries`, SiteDetail | `yearSeries(v, ids, kind)` | meas_year | `queryCells({grain:['year','fiscal_year'], stats:[mean,min,max]})` を JS でピボット | ✓ |
| 同上 | `monthSeries(v, ids)` | meas_month | `queryCells({grain:'month', stats:[mean]})` | ✓ |
| 同上 | `daySeries(v, ids, from, to)` | meas_daily | `queryCells({grain:'day', stats:[mean], period})` | ✓ |
| `/api/timeseries mode=zone`, `get_timeseries(zone)` | `zoneSeries(v, kind)` | zone_year | `summarize(spec年, by:'zone')` | ✓ |
| `mode=season`, `get_seasonality` | `climatology(v)` / `zoneClimatology(v)` | meas_clim / zone_clim | `summarize(spec日, by:'month_of_year')` / `summarize(spec月, by:'zone_month_of_year')` | ✓ |
| `mode=season`/`mode=rain` | `rainMonthlyClim()` / `rainDaily(from,to)` / `rainTopDays(n)` | rain_daily | `queryCells({variable: weather.precipitation, series: RAIN(sagamihara), grain:'day', stats:[sum]})`（`/10` しない・単位 NULL＋注記） | ✓ |
| `/sites`, `/api/geo/sites`, `get_sites` | `listSites()` / `getSite(id)` / `siteVariables(id)` | sites+watershed_meta+site_var | `catalog.sites()`（`sites` JOIN `place_source_ref` JOIN 年セル集計）、`catalog.siteVariables(placeId)`（索引 `(place_id, variable_id, grain)`） | ✓ |
| home | `longitudinalHighlight(water, v)` | meas_year+sites | `summarize(spec年{kind daily, from 2020}, by:'place', scope water)` | ✓ |
| （呼び出しゼロ） | `sensorHourMonth()` | sensor_hour_month | 廃止（PR-5） | — |
| （読み手なし） | — | sensor_daily | 対象外 | — |

### 1.2 生物系（PR-3b。PR-3a で流域セル・月セルが要る）
`taxonGroupYears` / `effortYears` / `speciesShareTrend` / `speciesYears` / `speciesMonths` / `speciesMeshYears` / `speciesList` / `iasSpecies` / `meshAll` / `meshByYear` / `redlist*` / `watershedRollup` / `landuseChange`（呼び出しゼロ） / `landuseHighlight` / `biotaTotals` → `occurrence.ts`・`summary_taxon_catalog`・`taxon_assessment`。**PR-1 では作らない**（`occurrence.ts` のファイルも作らない。空ファイルは「ある」と誤解を生む）。

### 1.3 文書・概況・合成（PR-4）
`docSeriesList` / `docSeriesPoints` / `docNotes` / `documentsList` / `blockingNotes` / `overviewStats` / `sourceRegistry` / quality 系 / `pairedMeasurements` / `interventions` / `decisions` / `observerStats` / `instrument*` / `protocolList`。`overviewStats.n_meas`（`COUNT(*) measurements`＝323,164、above_lod・パース失敗行を含む）はキューブから完全再現できないので PR-4 で「設計上の変更」として扱う。

### 1.4 触らないもの
Tier 1（`/api/nature`, `/api/geo/{protected-areas,vegetation,river-segments}`）と `sites`/`source_registry`/`cells`/`notes`/`documents` は D1 に残る原本表。`run_sql`/`describe_schema` は PR-4。

## 2. PR-1 の実装範囲（確定案）

- `web/src/lib/cube/{db.ts, db-d1.ts, db-sqlite.ts, series.ts, observation.ts, catalog.ts, envelope.ts, caveats.ts, sql.ts(共通断片), index.ts}` ＋ `__fixtures__/` ＋ `*.test.ts`
- `web/serving_queries.yaml`、`web/scripts/serving-diff.mts`、`web/scripts/lib/serving/{adapters-v1.ts, adapters-v2.ts, normalize.ts, classify.ts, report.ts, mutations.ts}`、`web/scripts/lib/v1-db-shim.ts`、`web/tsconfig.serving-diff.json`
- `web/vitest.config.ts`（`server-only` alias）、`web/package.json`（`tsx` devDep、`serving:diff` スクリプト）
- `scripts/registry/build_caveat.py`（v2 scope 行）、`web/scripts/build-registry-ts.mjs`（scope kind の拡張）、`web/src/lib/registry/generated-client.ts`（再生成）、`registry/README.md`、`registry/variable_alias.csv`（D3 採用時）、`reports/full_gate_proof.json`（b00 再実行）
- `reports/serving_switch_diff.md`（＋`.json`）
- 既存の読み取り経路（`queries.ts`・`tools.ts`・画面・API）は **無変更**。`docs/plans/V2_SERVING.md` PR-1 節の状態更新のみ。

## 3. `lib/cube` の API

### 3.1 `db.ts`（接続の抽象）
```ts
export type SqlParam = string | number | null;
export type Row = Record<string, string | number | null>;
export interface CubeDb {
  readonly kind: "d1" | "sqlite";
  all<T = Row>(sql: string, params?: readonly SqlParam[]): Promise<T[]>;
}
/** D1 の制約を実装によらず静的に検査する（両実装が all() の先頭で呼ぶ）。
 *  - params.length <= 100（既存 D1_MAX_BOUND_PARAMS を import）
 *  - SQL 中の LIKE のリテラル/バインド文字列が 50 バイト以下
 *  - "ATTACH" / "d." / "c." 接頭辞を含まない（D1 は単一 DB）
 *  - `IN (` の直後に `?` が 8 個以上並ばない（一覧は json_each で渡す規約） */
export function assertD1Compatible(sql: string, params: readonly SqlParam[]): void;
```
- `db-d1.ts`（`import "server-only"`）: `export async function d1CubeDb(): Promise<CubeDb>`。既存 `@/lib/db` の `getD1()` を使う。`@/lib/db` との関係: **置き換えない**。`queries.ts` は PR-5 まで既存 `db.ts` のまま。`lib/cube` は `getD1` だけを借りる。
- `db-sqlite.ts`（Node 専用、アプリからは import しない。テストと `serving-diff` が使う）: `export function sqliteCubeDb(paths: { v2: string; registry: string; ryuiki: string }): CubeDb & { close(): void }`。`better-sqlite3` で `v2` を `readonly` で開き `ATTACH 'file:…?mode=ro' AS reg` / `AS r` を **URI モード**で行う（原本は読み取り専用の規約）。SQL は非修飾テーブル名で書く（`observation_agg`→main、`place_source_ref`→reg、`sites`→r。名前が一意なので SQLite が解決する。D1 と同じ文字列が動く）。
- `IN (...)` を使わない方針: 意味のある集合（水域・ゾーン）は **レジストリ/`sites` との JOIN**、呼び出し側が持つ任意の ID 一覧（地点 ID 配列等）は **`JOIN json_each(?)`（JSON 配列文字列を 1 パラメータで渡す）**。D1 は JSON1 内蔵。`queryChunked` は GROUP BY を跨げないので `lib/cube` では使わない。上限は `MAX_ID_LIST = 1000`（超えたら例外。画面は最大でも水域内地点数≦数十）。

### 3.2 `series.ts`（系列＝v1 の alias 相当。DB を読まない。`generated.ts` だけを見る）
```ts
export interface SeriesKey { variableId: string; obsStat: string | null; unitId: string | null; valueGrain: string; }
/** b05 の _AKEY_EXPR と同じ連結順（variable_id|value_grain|obs_stat|unit_id、NULL は ''）。
 *  SQL 側の式 SERIES_KEY_SQL と 1:1。テストで b05 と同じ文字列になることを固定する */
export function seriesKeyString(k: SeriesKey): string;
export const SERIES_KEY_SQL = "c.variable_id || '|' || COALESCE(c.value_grain,'') || '|' || COALESCE(c.obs_stat,'') || '|' || COALESCE(c.unit_id,'')";
export interface SeriesInfo extends SeriesKey { dataset: string; sourceIds: (string | null)[]; aliases: string[]; unitId: string | null; }
export function seriesForAlias(dataset: string, alias: string): SeriesInfo[];        // v1 互換（アダプタ用）
export function seriesForVariable(variableId: string, opt?: { dataset?: string; obsStats?: "representative" | "all" | string[] }): SeriesInfo[];  // representative = {mean, point, NULL}
export function seriesInfo(k: SeriesKey): SeriesInfo | undefined;                    // 逆引き（tuple→dataset は一意: assert_alias_tuple_maps_to_single_dataset）
export function isSynthetic(s: SeriesInfo): boolean;                                  // sourceIds に null を含む
export type Grain = "day" | "month" | "year" | "fiscal_year";
export function labelYear(periodStart: string): number;                              // substr(1,4)。fiscal_year は年度の始まりの年（v1 と同じ）
```
- 単位: `unitFor(cell.unitId)` は **セルの `unit_id` のみ**（D3 採用時）。`unit_id NULL` は `null` を返し、PR-2 で `unitUnknown` 注記を付ける。D3 却下時は `unitId ?? variable.unitId` にし、流量 alias を既知差分に登録する。
- 年キー: `grain` を常に返す（`year`＝暦年、`fiscal_year`＝年度、`period_start`＝`YYYY-01-01`/`YYYY-04-01`）。v1 の `kind` は **アダプタ側**（`web/scripts/lib/serving/v1-compat.ts`）で `daily ⇔ input_grain='day'`、`annual ⇔ input_grain = grain`（`fiscal_year/fiscal_year` 98,579 セル＋`year/year` 11,377 セル〔うち measurements は地盤沈下 8 alias〕）。`lib/cube` に daily/annual という語を入れない。

### 3.3 `observation.ts`
```ts
export interface CellSpec {
  variableId?: string;                 // 索引1 (variable_id, place_id, grain, stat, period_start) を使う主経路
  series?: SeriesKey[];                // 省略時は variableId の全系列。json_each(?) で SERIES_KEY_SQL と等値 JOIN
  scope:
    | { kind: "places"; placeIds: string[] }          // json_each
    | { kind: "site"; siteId: string }                // place_source_ref(source_id='sites.site_id') JOIN
    | { kind: "water"; municipality: string }         // sites.municipality JOIN
    | { kind: "zone"; zone?: number }                 // place_relation(within) JOIN place_source_ref(source_id='sites.zone')
    | { kind: "all_sites" };                          // place_kind='site'
  grain: Grain | Grain[];
  stats?: ("mean" | "min" | "max" | "sum")[];        // 既定 ['mean']
  inputGrain?: "day" | "hour" | "instant" | "same";  // 'same' = 出典配布セル（input_grain = grain）
  period?: { from?: string; to?: string };           // period_start の範囲（文字列比較。日時関数は使わない: ADR-0024）
  imputation: "zero" | "lod" | "both";
}
export interface CellRow { placeId: string; siteId: string | null; series: SeriesKey; inputGrain: string; grain: Grain; periodStart: string; periodEnd: string; stat: string; value: number | null; valueZero?: number | null; valueLod?: number | null; n: number; nCensored: number; nNotDetected: number; nPlaces: number; }
export async function queryCells(db: CubeDb, spec: CellSpec): Promise<CellRow[]>;
export type SummarizeBy = "place" | "zone" | "month_of_year" | "zone_month_of_year" | "series";
export interface SummarizeOpt { measure?: "avg" | "sum_per_year" }   // sum_per_year = SUM(v)/COUNT(DISTINCT 年)（雨量の月別平年）
export async function summarize(db: CubeDb, spec: CellSpec, by: SummarizeBy, opt?: SummarizeOpt): Promise<SummaryRow[]>;
```
- SQL の骨格（`queryCells`、site スコープ・年）:
```sql
SELECT c.place_id, psr.external_key AS site_id, c.variable_id, c.obs_stat, c.unit_id, c.value_grain, c.input_grain,
       c.grain, c.period_start, c.period_end, c.stat, c.value_zero, c.value_lod, c.n, c.n_censored, c.n_not_detected, c.n_places
FROM observation_agg c
JOIN json_each(?) sk ON sk.value = <SERIES_KEY_SQL>            -- series 指定時のみ
JOIN place_source_ref psr ON psr.place_id = c.place_id AND psr.source_id = 'sites.site_id'
-- water: JOIN sites s ON s.site_id = psr.external_key AND s.municipality = ?
-- zone : JOIN place_relation pr ON pr.child_id = c.place_id AND pr.relation = 'within'
--        JOIN place_source_ref zref ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
WHERE c.variable_id = ? AND c.place_kind = 'site'
  AND c.grain IN ('year','fiscal_year') AND c.stat IN ('mean','min','max')
  -- inputGrain='day' → AND c.input_grain = 'day' ／ 'same' → AND c.input_grain = c.grain
  -- period → AND c.period_start >= ? AND c.period_start <= ?
ORDER BY c.place_id, c.period_start, c.stat
```
  `psr` は LEFT JOIN にしない（`sites.site_id` の逆引きが無い place は v1 でも site_id が無い）。ただし `all_sites` スコープ（meas_clim・var_catalog）は `psr` を **付けない**（厚木 4 地点・地盤沈下等、`sites` に無い 78 地点も v1 の集計に入っている。`sites` JOIN は水域・ゾーン・地点一覧のときだけ）。
- mean/min/max のピボットは JS（`(place, series, period_start)` でまとめる）。b05 の自己 JOIN は使わない。
- `summarize` の集計式は **b05 の SQL を正**にする（これが v1 との一致仕様）:
  - `month_of_year`（日セル）: `COUNT(*) n, AVG(v) avg, MIN(v) min, MAX(v) max`、`GROUP BY CAST(substr(period_start,6,2) AS INT)`（= meas_clim）
  - `zone`（年セル）: `COUNT(DISTINCT c.place_id) n_sites, SUM(c.n) n, AVG(v) avg`、`GROUP BY zone, grain, input_grain, substr(period_start,1,4)`（= zone_year。grain は分けて返し、v1 の kind 合流はアダプタが行う。alias→grain は 1:1 なので衝突しない。衝突したらアダプタは例外）
  - `zone_month_of_year`（月セル）: `COUNT(DISTINCT place_id), SUM(n), AVG(v)`、`GROUP BY zone, month`（= zone_clim）
  - `place`（年セル）: `SUM(n), MIN(substr(period_start,1,4)), MAX(...), AVG(v)`、`GROUP BY place_id, grain, input_grain`（= site_var・longitudinal）
  - `series`（年セル）: `SUM(n), COUNT(DISTINCT place_id), MIN/MAX 年, SUM(CASE WHEN input_grain='day' THEN n END), SUM(CASE WHEN input_grain=grain THEN n END), SUM(n_censored)`、`GROUP BY <SERIES_KEY_SQL>, input_grain`（= var_catalog の系列版）
  - `v` は `imputation` で `value_zero`/`value_lod` を選ぶ（`both` は summarize では不可→例外）。
- **系列の混ぜ方**: `spec.series` に複数系列を渡すと1グループに混ざる（v1 の alias 単位の集計と同じ）。実測で必要: zone 3 の `浮遊物質量 SS`/`溶存酸素量 DO`（daily, 2023–2025）は合成データ（mean, atsugi と同じ tuple）と env_kousui（point）の 2 系列が同じ alias で混ざっており、系列ごとに分けると v1 と一致しない。
- `imputation`: 画面は PR-2 で `lod`、serving-diff は `zero`、封筒は `both`。`half_lod` は返さない（ADR-0030 D5）。

### 3.4 `catalog.ts`（PR-1 は問い合わせ時計算。PR-2 で `summary_*` に差し替える口を切る）
```ts
export interface CatalogSource { kind: "live" } | { kind: "summary" }   // PR-2 で summary を追加
export async function variableCatalog(db, opt?: { dataset?: string }): Promise<SeriesCatalogRow[]>;  // series 単位（alias/variable_id どちらにも束ねられる）
export async function siteVariables(db, placeId: string): Promise<SiteSeriesRow[]>;                    // 索引2 (place_id, variable_id, grain)
export async function sites(db): Promise<SiteRow2[]>;                                                  // sites JOIN psr JOIN 年セル集計（n_meas, n_var は series 数と variable 数を両方返す）
export async function waterBodies(db, opt?: { series?: SeriesKey[] }): Promise<WaterBodyRow[]>;
export async function sitesInWaterBody(db, municipality: string): Promise<SiteRow2[]>;
```
`dataset` の絞り込みは `variable_alias` との JOIN で行う（`SELECT DISTINCT variable_id, COALESCE(grain,''), COALESCE(stat,''), COALESCE(unit_id,'') FROM variable_alias WHERE dataset = ?` を派生表にして `SERIES_KEY_SQL` と等値 JOIN。b05 の `alias_lookup` と同じ形。`IN` 不要）。

### 3.5 `envelope.ts`（ADR-0014）
```ts
export interface Envelope<R> { query: Record<string, unknown>; columns: { name: string; type: "number"|"string"; unit?: string|null; ucum?: string|null }[]; rows: R[]; coverage: { n_rows: number; n_places: number; n_censored: number; n_not_detected: number; period: { start: string|null; end: string|null; grain: string }; imputation: "zero"|"lod"|"both" }; provenance: { source_id: string|null; name?: string; license?: string; n_rows: number }[]; excluded: { by_license: number; by_embargo: number; reasons: string[] }; caveats: CaveatRef[]; truncated: boolean; spec_version: string; }
export async function buildEnvelope<R extends CellRow>(db, spec: CellSpec, rows: R[]): Promise<Envelope<R>>;
```
`provenance` は系列→alias→`source_id` を `source_registry`（D1 に残る）で解決。`both` のときは `columns` に `value_zero`/`value_lod` を単位付きで両方出す。消費者は PR-2（AI ツール）。PR-1 はテストのみ。

### 3.6 `caveats.ts`（v2 キーで注記を引く。クライアント安全＝`generated-client.ts` だけに依存）
```ts
export interface CaveatFacets { datasets?: string[]; themes?: string[]; placeKinds?: string[]; sourceIds?: string[]; tables?: string[] }
export function caveatsForFacets(f: CaveatFacets): CaveatRef[];   // 並び: priority 降順 → facet の出現順（datasets, themes, placeKinds, sourceIds, tables の順に平坦化）→ sort_order → key で先勝ち重複排除
export function facetsForSeries(series: SeriesInfo[], scope: CellSpec["scope"]): CaveatFacets;  // datasets ∪ {'synthetic' if isSynthetic}, themes = variable.theme, placeKinds = scope に応じて ['site'] / ['zone'] / ['site'], sourceIds
```

### 3.7 単位の不変条件（危険#5）の検査の置き場
- **データ側（PR-1b、Python）**: `scripts/r01_build_registry.py` に `_assert_alias_unit_is_evidenced` は置けない（原本 `unit_raw` は r01 が読まない）ので、`scripts/b03_build_observation.py` の T1 不変条件に **「`unit_id IS NULL` の観測は `unit_raw IS NULL`、または alias 行に単位が無いことを `registry/variable_alias.csv` の `note` で宣言している」** を足す…のは重い。PR-1 では `scripts/tests/test_r01_invariants.py` 相当ではなく、**b04 に「`unit_id NOT NULL` のセルの unit_raw が symbol と一致（不一致 0 件）・`unit_id NULL` かつ `unit_raw NOT NULL` の系列数を数えて宣言（`scripts/migrate/unit_evidence_declarations.yaml`、期待 0 系列）と突き合わせる検査**を足す（D3 採用時）。
- **web 側（PR-1a、vitest）**: フィクスチャで「`unit_id NULL` のセルは `unit=null` を返し、フォールバックしない」を固定。実 DB があれば skipIf 統合テストで `derived.meas_year.unit`（unit_raw）と `symbol(cell.unit_id)` を全系列で突合（不一致 0、v1 NULL→v2 非 NULL は件数だけ報告）。

## 4. `serving_queries.yaml` と共通の行形

### 4.1 スキーマ
```yaml
version: 1
domains:                                   # パラメータ集合。v1 表から機械的に列挙（列挙元も宣言する）
  alias:     { sql: "SELECT variable FROM var_catalog ORDER BY variable", db: v1 }        # 58
  site_id:   { sql: "SELECT DISTINCT site_id FROM site_var ORDER BY site_id", db: v1 }     # 250（sites に無い 78 地点を含む）
  water:     { sql: "<listWaterBodies の name>", db: v1 }                                   # 26
  kind:      [daily, annual]
  zone:      [1,2,3,4,5]
queries:
  - id: year_series_site
    v1_table: meas_year                      # 宣言済み差分の照合先（無ければ null）
    params: { alias: {domain: alias}, site_id: {domain: site_id}, kind: {domain: kind} }
    only_existing: "SELECT site_id, variable AS alias, kind FROM site_var"   # 組の絞り込み（8,140 組）
    snapshot_subset: { site_id: { every: 10, plus: ["atsugi_river_water_quality__中津川", "env_kousui_stations_kanagawa__kousui_1410010"] } }
    compare: { key: [site_id, year], numeric: [n, avg, min, max, n_censored], label: [unit] }
    exact: [n, avg, min, max, n_censored]    # 通過列は完全一致。再集計列は tolerance を許す
    known: [declared, unit_label_registry]
  - id: month_series_site  … (meas_month; key [site_id, ym]; numeric [n, avg])
  - id: day_series_site    … (meas_daily; key [site_id, d]; numeric [value, n_censored])
  - id: year_series_water  … (params alias×water×kind; key [site_id, year])
  - id: zone_series        … (zone_year; params alias×kind; key [zone, year]; numeric [n_sites, n, avg]; tolerance: {avg: 1e-9})
  - id: climatology        … (meas_clim; params alias; key [month]; numeric [n, avg, min, max]; tolerance: {avg: 1e-9})
  - id: zone_climatology   … (zone_clim; key [zone, month])
  - id: variable_catalog   … (var_catalog; key [alias]; numeric [n, n_sites, y_from, y_to, n_daily, n_annual, n_censored])
  - id: site_variables     … (site_var; params site_id; key [alias, kind]; numeric [n, y_from, y_to, avg])
  - id: sites_list         … (sites+site_var; key [site_id]; numeric [n_meas, n_var])
  - id: water_bodies       … / water_bodies_for_variable … / sites_in_water_body …
  - id: rain_daily         … (rain_daily; key [d]; numeric [mm]; known: [rain_div10, day_split])
  - id: rain_monthly_clim  … (key [month]; numeric [mm]; known: [rain_div10, day_split])
  - id: rain_top_days      … (key [rank]; numeric [mm]; label [d]; known: [rain_div10, day_split])
  - id: longitudinal_highlight … (params water×alias 既定1組＋代表; key [site_id]; numeric [avg, n])
```
- **列挙は「全 site_var の組（8,140）を全部回す」**（`--expand all`、serving-diff の既定）。1 問い合わせ 2〜5 ms（better-sqlite3）で 2〜3 万問い合わせ、数分で終わる。スナップショット（PR-5、CI）は `snapshot_subset` の決定論的な部分集合（`every: k` は site_id を並べて k 個おき＋名指し）。両方が同じ YAML から出るので宣言漏れが二重にならない。
- YAML には SQL を書かない（`domains` の列挙 SQL だけ例外）。問い合わせ本体は **アダプタ（コード）** が `id` ごとに持つ。

### 4.2 共通の行形（正規化）
```ts
interface NormRow { key: (string|number)[]; numeric: Record<string, number|null>; label: Record<string, string|null> }
interface QueryRun { id: string; params: Record<string, string|number>; rows: NormRow[] }
```
- **v1 アダプタ** = `queries.ts` の関数を **そのまま** 呼ぶ（v1 経路＝今の `queries.ts` そのもの）。`@/lib/db` を better-sqlite3 のシム（`web/scripts/lib/v1-db-shim.ts`: `query/queryOne/queryChunked/ph` を同じシグネチャで実装、`ryuiki`+`cells`+`derived` を ATTACH）に差し替えて実行する。差し替えは `web/tsconfig.serving-diff.json` の `paths`（`"@/lib/db": ["./scripts/lib/v1-db-shim.ts"]`, `"server-only": ["./scripts/lib/server-only-empty.ts"]`、`"@/*"` はそのまま）＋ `tsx --tsconfig`。tsx が bare specifier の paths を解決しない場合の代替は `node --import ./scripts/lib/register-aliases.mjs`（`module.register` のカスタムローダ 20 行）。
- **v2 アダプタ** = `lib/cube` を `sqliteCubeDb()` で呼び、v1 の列名に付け替える（`year=labelYear(period_start)`、`kind=input_grain==='day'?'daily':'annual'`、`unit=symbol(unit_id)`、alias＝`seriesForAlias(dataset, alias)` で系列集合を渡す）。**PR-2 で画面が variable_id 単位に変わっても、serving-diff の v2 アダプタは alias 単位のまま**（比較単位を固定するため）。PR-2 は「代表系列」の差分を別の問い合わせ ID（例 `year_series_site_by_variable`）として足す。
- 比較: キーで突き合わせ → `row_only_in_v1` / `row_only_in_v2` / `value_diff(columns)` / `label_diff(columns)`。`exact` 列は完全一致、それ以外は `tolerance`（既定 0。再集計列だけ YAML で 1e-9 相対を許し、件数を「浮動小数の丸め」として報告する）。

## 5. `serving-diff.mts`

### 5.1 入出力
```
pnpm run serving:diff [--imputation zero|lod] [--expand all|snapshot] [--only <id,...>] [--mutate <name>] [--v1-source derived|v1_projection] [--out reports/serving_switch_diff.md]
```
- 入力: `data/db/derived.sqlite`（v1）、`data/db/v2.sqlite`（`check_v2_fresh.py` が 0 でなければ**起動時に拒否**）、`registry.sqlite`、`ryuiki.sqlite`（`sites`/`source_registry`/`measurements` は読まない）。全部 `mode=ro`。
- `--v1-source v1_projection`（`data/db/v1_projection.sqlite`、b05 の射影）は **診断用**: これで比較すると宣言済み差分の系統は 0 件になるはずで（b05 が既に v2 の意味で射影している）、残るのは雨量 `/10` と日割りだけ。`lib/cube` のバグ切り分けに使う。
- 出力: `reports/serving_switch_diff.md`（人向け）＋ `reports/serving_switch_diff.json`（機械可読。PR-2 以降で前回との差分に使う）。ヘッダに: git HEAD、`v2.sqlite` の `pipeline_fingerprint`、`registry_build.input_fingerprint`、better-sqlite3 の SQLite 版（3.53.4）、imputation、expand。表: 問い合わせ ID ごとに `runs / rows_v1 / rows_v2 / matched / declared / rain_div10 / day_split / synthetic_excluded / unit_label_registry / float_rounding / unexplained`。末尾に unexplained の先頭 20 件と、変異テストの結果表（実行時）。
- 終了コード: `unexplained > 0` または問い合わせ例外 → 1。宣言済み差分の**腐り**（`expected_diffs.yaml` の測定値系 18 キーのうち serving-diff の対象問い合わせで1件も差分にならないもの）→ 2（b02 と同じ思想: 免除が残り続けて退行を隠さない）。

### 5.2 既知の系統の判定規則（`classify.ts`）
| 系統 | 判定規則 | 再利用 | PR-1 での期待件数 |
|---|---|---|---|
| `declared`（宣言済み差分 20 件） | 問い合わせの `v1_table` と行キーを v1 のキー列（`reports/derived_baseline.json` の `tables[t].key`）に写し、`scripts/reconcile/expected_diffs.yaml` の `(table, key, kind)` と一致、`value_diff` は食い違った列 ⊆ `columns` | `expected_diffs.yaml` をそのまま読む（`js-yaml`）。構造検証は Python 側 `validate_expected_diffs` が CI で済ませているので TS 側は照合だけ | 18（org_norm/species2 の 2 件は PR-3b）。中津川は `sites` に無いので水域・ゾーン・地点一覧には波及しない（実測）。伝播規則は不要——出たら unexplained として落とす |
| `rain_div10` | `round(v2/10, 2) == v1`（雨量系 3 問い合わせのみ。`known` に列挙された問い合わせだけに適用） | — | rain_daily 3,105 日 |
| `day_split` | L2 から両流儀で再計算して等式: v1 側 = `Σ value_num GROUP BY substr(period_raw,1,10)`（ラベル日割り、`/10` 後）、v2 側 = `Σ … GROUP BY substr(period_start,1,10)`。月別・上位 N も同じ再計算を通した値で一致するか | `observation`（L2、v2.sqlite）を直接読む | 548 ＋ v1 のみ 1 日 = 549（実測、全件説明可） |
| `synthetic_excluded`（PR-2 から） | v1 側 = L2 を `is_synthetic` 込みで再集計、v2 側 = 除いて再集計、それぞれ一致 | L2 | PR-1 は 0（v2 に合成行 21,685 行がまだある。24 合成地点は全部 `sites` にゾーン付きで存在） |
| `unit_label_registry` | `label_diff` のみで、`v1.unit IS NULL AND v2.unit IS NOT NULL` かつ数値列は一致 | — | 重金属系 alias 等（観測 104,410 行分の系列） |
| `float_rounding` | 再集計列で相対 1e-9 以内 | — | 0 が期待。出ても許容し件数を出す |
| `series_merge`（PR-2 から） | variable_id 単位の問い合わせで v1 の複数 alias 行の和/平均と一致 | — | PR-1 は問い合わせ自体が無い |
| `watershed_memo` / `sirosporium` | PR-3b で追加（`occurrence_watershed_v1_declarations.yaml` の再計算式・`expected_diffs.yaml` の 2 キー） | — | PR-1 対象外 |

### 5.3 変異テスト（「変異で拾う」の実証）
`--mutate <name>` で v2 アダプタ／分類器に既知の誤りを注入し、**必ず unexplained > 0 で落ちる**ことを `web/scripts/lib/serving/mutations.test.ts`（フィクスチャ DB）と、実 DB がある手元では `pnpm run serving:diff --mutate all`（レポート末尾の表）で確認する:
`lod_instead_of_zero`（value_lod を返す。検閲セル 243,686 で差が出る）／`drop_series`（alias の系列集合から 1 つ落とす: pH の point 等）／`swap_kind`（daily/annual を逆に）／`no_unit`（unit を常に null）／`month_off_by_one`／`include_watershed_cells`（`place_kind='site'` を外す）／`rain_no_div10_rule`（分類器の `/10` 規則を無効化→3,105 件が unexplained）／`declared_rot`（宣言 1 件を無視→終了コード 2）／`day_split_rule_off`（→548 件 unexplained）。

## 6. `caveat_scope` の付け替え

### 6.1 対応表（`build_caveat.py` に `add_facet_group(kind, refs, keys, priority)` を足して v1 の table 行の**隣に**生成する）
| caveat | v1 の scope（現状、全件） | v2 の scope（新設） |
|---|---|---|
| measuredOn / censored / duplicates / aboveLod | `table` × {measurements, meas_year, meas_month, meas_daily, meas_clim, zone_year, zone_clim, var_catalog, site_var} | `dataset=measurements` |
| zone | `table sites` | `place_kind=site`, `place_kind=zone` |
| municipality | `table sites` | `place_kind=site` |
| organismSite / effort / regimes / gbifCutoff / share | `table` × {organism_records, org_norm, org_group_year, org_watershed, org_watershed_year, species2, species_year2, species_month, effort_year}；organismSite は `table occurrence_place` も | `dataset=organism_records` |
| share / effort | `table_prefix mesh_`, `table species_mesh_year` | `place_kind=grid01` |
| isAlien | `table ias_species` | `source_id=moe_ias_list`（`taxon_assessment.source_id`） |
| landuseDefinitionChange | `table` × {landuse_watershed, landuse_change} | `variable_theme=landuse` |
| synthetic（priority 1） | `table` × {observers, interventions, decisions, quality_transitions, quality_monthly, event_observers} | `dataset=synthetic`（priority 1。規約: alias.source_id が NULL の系列） |
| cells 由来（cell / cell_table、277 行） | 変更なし | 変更なし |
| （PR-2 で新設）unitUnknown / censoredLod | — | `variable` キー（`weather.precipitation` の RAIN 系列等）。PR-1 では kind の語彙に `variable` を**予約だけ**する |

scope_kind の語彙: `table` / `table_prefix` / `cell` / `cell_table`（既存）＋ `dataset` / `variable_theme` / `variable` / `place_kind` / `source_id`（新設）。`sort_order` は同じ `(scope_kind, scope_ref)` 内の並び（v1 と同じ順序を写す）。

### 6.2 並存と「v1 の注記が変わらない」保証
- `caveatsForTables()`（`lookup-client.ts`）は `scopeKind === "table" | "table_prefix"` でフィルタしているので、新 kind の行を足しても結果は不変。**`caveats.test.ts`（34 ケース、インラインスナップショット）を触らずに緑**であることが保証。
- `web/scripts/build-registry-ts.mjs`: 166 行目の `WHERE scope_kind IN ('table','table_prefix')` を新 kind を含む定数配列 `CAVEAT_SCOPE_KINDS` にし、371 行目の `export type CaveatScopeKind = …` を同じ配列から生成する（手書きをやめる）。`generated-client.ts` を再生成してコミット（CI `registry` ジョブが `--files-only` で再生成し `git diff --exit-code`）。
- `CAVEAT_TEXT`（`ai/caveats.ts`）は scope の key 集合から作るので、新 kind でも key 集合は同じ → `prompt.test.ts` のスナップショットも不変。
- 新設テスト `web/src/lib/cube/caveats.test.ts`: 橋渡し表（v1 表名 → facets、例 `meas_year → {datasets:['measurements']}`、`sites → {placeKinds:['site']}`、`mesh_all → {placeKinds:['grid01']}`、`decisions → {datasets:['synthetic']}`）で `caveatsForFacets(bridge(t)).map(key)` が `caveatKeysForTables([t])` と**順序まで一致**することを 24 表全部で確認。`tools.ts` が渡している複合（例 `["var_catalog","zone_year"]`、`["sites","site_var","meas_year"]`）も同様。
- 期間: v1 の table 行は PR-5 で消す（`build_caveat.py` の v1 定数ごと）。それまで両方持つ。
- パイプラインのパス: `scripts/registry/` は `PIPELINE_DIRS` → `scripts/b00_run_full_gate.py` を回して `reports/full_gate_proof.json` を更新（D3 を採用すれば `registry/variable_alias.csv` の変更も同じ 1 回に乗る）。`scripts/tests/test_r01_registry_atomic.py` 等に scope kind を固定するテストは無い（grep で確認）。`registry/README.md` に kind の語彙を追記。

## 7. vitest

- `web/vitest.config.ts` に `resolve.alias: { "server-only": path.resolve(__dirname, "node_modules/server-only/empty.js") }` を足す（パッケージが `react-server` 条件用の `empty.js` を同梱している。実在を確認済み）。これで `@/lib/db` を import する既存モジュールも読み込めるが、`getD1()` は実行時に落ちるので `lib/cube` は **`CubeDb` を引数で受ける**設計にし、テストは `sqliteCubeDb`/インメモリだけで動く。
- フィクスチャ（`web/src/lib/cube/__fixtures__/cube-fixture.ts`）: `better-sqlite3(":memory:")` に `web/drizzle/migrations/*.sql` を `--> statement-breakpoint` で分割して順に適用（＝D1 と同じ DDL・索引）し、手書きの行を入れる: 地点 3（ゾーン 3・水域「境川（１）」の 2 地点、`sites` に無い厚木型 1 地点）、`water.ss` に 2 系列（mean/atsugi 型と point/env 型、alias は同じ）、日セル（検閲あり: `value_zero ≠ value_lod`、`n_not_detected>0` で `value_lod NULL`）、月・年（暦年 input=day）・年度（fiscal_year）セル、`weather.precipitation` の hour→day `sum` セル、`unit_id NULL` のセル、レジストリ 8 表の必要行（`place_source_ref` の `sites.site_id`/`sites.zone`、`place_relation within`、`variable_alias` の source_id NULL 行＝合成）、`caveat`/`caveat_scope`（table 行と facet 行の両方）。
- テスト: `queryCells`（スコープ 5 種・grain・stats・period・imputation 3 値）、`summarize` 5 種の式が b05 の SQL と同じ結果になること（フィクスチャの期待値は手計算で固定）、`series.ts`（`seriesKeyString` が b05 の `_AKEY_EXPR` と同じ文字列、alias↔系列の往復、`isSynthetic`）、`assertD1Compatible`（101 パラメータ・51 バイトの LIKE・`ATTACH` で例外）、`envelope`、`caveats` 橋渡し、`classify.ts` の各規則（L2 を持つミニ `observation` 表で日割り・`/10`・合成の等式を実際に通す）、`mutations`（各変異で unexplained > 0）。
- 実 DB がある環境だけ動く統合テスト（`describe.skipIf(!fs.existsSync(data/db/v2.sqlite))`、`generated.test.ts` と同じ流儀）: 代表 3 問い合わせを v1/v2 両アダプタで流し unexplained 0 を確認。`data/sample`（縮小サンプル: meas_daily 18,823 行・rain_daily 63 行等）から v2 を作るには Python パイプラインが要るので vitest では使わない。CI の `sample-gate` へ serving スナップショットを繋ぐのは PR-5。

## 8. 分割と並行

| 単位 | 中身 | 触るファイル（衝突しない） | 依存 |
|---|---|---|---|
| **1a 問い合わせ層** | `lib/cube/{db,db-d1,db-sqlite,series,observation,catalog,envelope,sql,index}.ts`＋テスト＋フィクスチャ、`vitest.config.ts`、`package.json`（tsx devDep・`serving:diff`）、`pnpm-lock.yaml` | `web/src/lib/cube/**`（`caveats.ts` を除く）、`web/vitest.config.ts`、`web/package.json` | `CaveatFacets` 型だけ 1b と先に合意（1b が `caveats.ts` の骨だけ最初にコミット） |
| **1b caveat＋registry** | `build_caveat.py` の facet 行、`build-registry-ts.mjs`、`generated-client.ts` 再生成、`lib/cube/caveats.ts`＋橋渡しテスト、`registry/README.md`、（D3）`variable_alias.csv`＋b04 の単位証拠検査、**b00 証明の再生成**（原本のある手元でメインが直列に実行） | `scripts/registry/build_caveat.py`、`web/scripts/build-registry-ts.mjs`、`web/src/lib/registry/generated-client.ts`、`web/src/lib/cube/caveats.ts`、`registry/*`、`reports/full_gate_proof.json` | なし（先に着手可） |
| **1c serving-diff** | `serving_queries.yaml`、`serving-diff.mts`、`scripts/lib/serving/*`、`v1-db-shim.ts`、`tsconfig.serving-diff.json`、`reports/serving_switch_diff.*` | `web/serving_queries.yaml`、`web/scripts/**`、`web/tsconfig.serving-diff.json`、`reports/serving_switch_diff.*` | v1 側・分類器・レポート・変異は先に作れる（v2 アダプタは 1a の `index.ts` を待つ） |

マージ順: 1b → 1a → 1c（1a‖1b は同時進行可）。PR-0 と同様に feature ブランチへ順に取り込み、最後に `pnpm run serving:diff` を全量で回して表を PR 本文に貼る。

## 9. 危険・未決事項

1. **v2.sqlite/registry.sqlite が古い**（上記 0-7）。`build:v2` は `ensure-registry.sh` から r01 を呼ぶので registry も直る。
2. **tsx の `paths` で bare specifier（`server-only`・`@/lib/db`）を差し替えられるか**は未検証。落ちたら `node --import` のローダで代替（設計に明記済み）。`tsx` は drizzle-kit の推移依存で `.bin` にあるが、pnpm では明示 devDep にする。
3. **v1 の `kind='annual'` に暦年と年度が混ざる**（地盤沈下 8 alias は `year/year`、他は `fiscal_year`）。alias→grain は 1:1 なので v1 の 1 行は必ず 1 grain に写るが、アダプタは衝突時に例外にする。
4. **合成データが v1 の集計に混ざっている**（SS/DO/pH/水温/気温、24 地点、ゾーン付き）。PR-1 では両経路とも含むので差分ゼロ。PR-2 で `synthetic_excluded` 規則が実際に働くかは、そのときに `--mutate` と同じ要領で「v2 から合成を除いた仮想実行」で先に確かめられる（`--pretend-synthetic-excluded` を 1c で用意しておくと PR-2 が楽）。
5. **単位の symbol ゆれ**（sensor: `ug/m3` vs `μg/m3`、`0.1%` vs `0.1％`）は PR-2 の測定値系には出ないが、`unit.yaml` に原表記の別名を持たせる論点として残す。
6. **`overviewStats.n_meas`・`biotaTotals` はキューブから再現不能**（above_lod 26 行・パース失敗 69 行・合成）。PR-4 で「設計上の変更」として数える。
7. **`caveat_scope` の `variable` kind を PR-1 で予約するか**（unitUnknown/censoredLod を PR-2 で precise に付けるため）。予約だけなら害は無い。
8. **b00 の所要時間**と、1b の証明更新が `variable_alias.csv` 変更（D3）と同じ 1 回で済むように 1b を先にまとめること。

## Critical Files for Implementation
- /home/yu23ki14/cfj/ryuiki-demo/scripts/b05_project_v1.py（v2→v1 形の SQL＝`observation.ts`/`summarize` の一致仕様の正。`_AKEY_EXPR`・`_MEAS_*_SQL`・`_ZONE_*_SQL`・`_RAIN_DAILY_SQL`）
- /home/yu23ki14/cfj/ryuiki-demo/web/src/lib/queries.ts（v1 経路そのもの。serving-diff の v1 アダプタが無変更で呼ぶ）
- /home/yu23ki14/cfj/ryuiki-demo/scripts/registry/build_caveat.py（caveat_scope の v2 キー行を足す場所）
- /home/yu23ki14/cfj/ryuiki-demo/web/src/lib/registry/lookup-client.ts（`caveatsForTables` の並び規則。`caveatsForFacets` はこれを写す）
- /home/yu23ki14/cfj/ryuiki-demo/scripts/reconcile/expected_diffs.yaml（宣言済み差分 20 件。serving-diff の `declared` 判定が直接読む）
- /home/yu23ki14/cfj/ryuiki-demo/web/src/lib/db.ts（`getD1`・`D1_MAX_BOUND_PARAMS`。`lib/cube/db-d1.ts` と `assertD1Compatible` が参照）
- /home/yu23ki14/cfj/ryuiki-demo/web/scripts/build-registry-ts.mjs（scope kind の列挙と `CaveatScopeKind` 型の生成元）
---
## オーナー側（設計責任者）の決定（2026-09-26）
- D1〜D5 すべて採用。
- D3 の受け入れ条件: `registry/variable_alias.csv` に埋める unit_id は「原本 unit_raw とレジストリ symbol が一致した38行」だけ（推測で埋めない。流量の1行は NULL のまま）。b00 の全量ゲートが 33表中 一致25/宣言済み差分のみ8/不一致0/宣言20件 のまま（増えたら埋め方を見直す、宣言を足して逃げない）。
- `caveat_scope` の `variable` kind は予約だけ入れる（§9-7）。
- `--pretend-synthetic-excluded` は 1c で用意する（§9-4）。
- 設計書はリポジトリに `docs/plans/V2_SERVING_PR1.md` としてコミットする（1b が担当）。
