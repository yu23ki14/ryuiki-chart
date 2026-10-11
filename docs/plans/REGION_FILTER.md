# 地域で絞る切り替え（Issue #93）設計書

画面・集計・MCP/AI・provenance を「全体／神奈川県／奄美大島」で切り替える。担当ごとの節（§4〜）だけ読めば実装できるように書いてある。
計測は 2026-10-11 時点のローカル D1（`web/.wrangler/state/v3/d1/miniflare-D1DatabaseObject/*.sqlite`、シード済み）を読み取り専用で引いた値（SQLite のローカル実行。D1 本番は遅延が加わるので絶対値より比を見る）。

## §0 決定

### 決定済み（オーナー、2026-10-11）

- 切り替えは「全体／神奈川県（`jp-14`）／奄美大島（`jp-46`）」。**全体（合算）を残し、既定は全体**。
- URL に `?region=` を持たせる（`?region=jp-46` で奄美を直接開けるリンクを作れる）。
- 方式は単一 D1 + `region_id`（ADR-0002）。蒸し返さない。

### 決定（メイン、2026-10-11）: `summary_*` は事前集計（下表の推奨を採る）。§9 の未決1・2 は既定案で進める（出典の地域は別 Issue、jp-46 ではトップのハイライトを出さない）

| 方式 | 内容 | 結論 |
|---|---|---|
| **推奨: 事前集計（b13 で地域別の表を足す）** | 件数が加法でない4表（species / taxon / effort_year / variable_catalog）だけ `*_by_region` を新設。既存の summary 表と中身・読み手は変えない。 | 神奈川の種の一覧が 3,469 ms → 6 ms（§2）。D1 の読み取り行数も 1.4M 行 → 約 24k 行。 |
| 却下: 問い合わせ時に絞る | `occurrence_agg` を `region_id` で絞って都度 GROUP BY。 | 神奈川で 3.4〜3.5 s／要求、1 要求あたり 1.45M 行を読む（D1 の読み取り行数課金・無料枠の日次上限を数要求で使い切る）。奄美でも 0.86 s。 |

推奨の理由: ①画面は種の一覧・努力量・トップの件数を毎回引く。②`sourceIds` 絞りの既存経路（`speciesCatalogBySource`）が既に「全出典の一覧より重い」と明記されている重い経路で、その重さを地域切り替えの既定動作にしてしまう。③事前集計の増分は約 7.9 万行（既存の `occurrence_agg` 154 万行に対し 5%）。④既存の summary 表を触らないので「全体」が現状と完全に同一になり、serving snapshot が動かない。

### 設計判断（この設計での決め）

- 地域別の表は**既存の summary 表に `region_id='all'` の行を足す形にしない**。`run_sql`（AI）や `/api/sql` で `summary_species_catalog` を直接引く人が二重計上する危険があるため。新しい別表にする。
- 「どの place がどの地域か」は新表 `place_region(place_id, region_id)` に1箇所で持つ。`place.region_id` は site だけが持ち、流域（377+25）とグリッド（4,086+1,731）は共通スコープ（`common:place:...`）で NULL のまま（ADR-0022 決定1。覆さない）。
- 出典→地域は**マニフェストの `region`**（28件。観測・出現の出典はすべて持つ）。registry の `source.region_id` 列は今は全176件 NULL なので、r01 がマニフェストから埋める。マニフェストの無い148件（文書・台帳系。うち名前に `_amami` を含むもの34、`_kanagawa` を含むもの39）は地域未宣言のまま扱う（§9 未決1）。
- `get_records` / `/sources` / `/documents` / トップの「出典 N 件」は今回は地域で絞らない（未決1）。

## §1 現状（region を絞るべき読み手）

地域の情報の所在（実測）:

| 場所 | region の持ち方 |
|---|---|
| `observation_agg.region_id`（nullable）／`occurrence_agg.region_id`（NOT NULL） | 列がある。値は `jp-14`／`jp-46`。**同じ `place_id` が両地域にまたがる行は 0**（実測）。ただし**索引の先頭にはない**（絞りは残差条件）。 |
| `place.region_id` | `place_kind='site'` だけ（jp-14 495 / jp-46 45）。watershed 402・grid01 5,818・zone 5 は NULL。 |
| `sites`（v1 の測定地点、389） | region 列なし。`place_source_ref(key_space='site_id')` → `place.region_id` で引く（jp-14 352 / jp-46 37）。 |
| 出典 | マニフェスト `manifests/<source_id>.yml` の `region`（jp-14 15 / jp-46 13）。`registry.sqlite` の `source.region_id` は全件 NULL。 |
| 時刻帯 | `region` 表（`registry/region.yaml`）。`lookup-client.ts:146 regionTimeZone()`。 |
| 地図の範囲 | `web/src/lib/map/basemaps.ts:170 REGION_JUMPS`（神奈川・奄美の bounds）。 |
| レッドリスト | `generated-client.ts` の `ASSESSMENT_LIST[...].region`（`jp-14` 3版・`jp-46` kgrl2014・kgord・`jp` 環境省）。`assessment.ts:94` に「地域で絞るのは #93」の注記つきで `jp-14` 固定。 |

読み手（絞る対象）:

**A. トップ画面**（`web/src/app/page.tsx`、`force-dynamic`）: `overviewCounts`（`catalog.ts:1271`。`sites`/`source_registry`/`place` の COUNT と `summary_variable_catalog`）、`longitudinalHighlight`（`summarize(...,'place')`、水域名＝境川固定）、`landuseHighlight`（`catalog.ts:1450`）、`redlistSummary`（`assessment.ts:133`）、`effortYears`（`catalog.ts:1063`）、`occurrenceTotals`（`catalog.ts:1130`）。

**B. 地図**: `app/api/geo/watersheds`（`watershedRollup` `catalog.ts:1406`＝`watershedBases`+`site` 数+`watershedOccurrence`+`loadLanduse`）、`app/api/geo/sites`（`sites()` `catalog.ts:681`）、`app/api/geo/mesh`（`gridCatalog` `catalog.ts:1100`／`meshByYear` `occurrence.ts:314`）。`/geo/rivers.geojson` は静的（絞らない）。保護区・植生・河川区間の API（`api/geo/protected-areas|vegetation|river-segments`）は `records.ts` の `readRecordSet` で、地図 UI からは使われていない（今回は触らない）。初期表示・URL: `components/map/MapPage.tsx:27`（神奈川固定の `MapCanvas` 既定 `DEFAULT_CENTER`）、`:219` の `REGION_JUMPS` ボタン。URL 状態は無い（`useSearchParams` を使うのは Timeseries／Biota／Explorer だけ）。

**C. 種のカタログ・生物相**（`app/api/biota/route.ts`）: `speciesCatalog`（`catalog.ts:962`、`summary_species_catalog`／出典絞りは `occurrence_agg` を直接）、`taxonGroupYears`（`:1038`、`summary_group_year`）、`effortYears`、`occurrenceTotals`、`speciesShareTrend`／`speciesYears`／`speciesMonths`／`speciesMeshYears`（`occurrence.ts:271,198,223,245`、いずれも `occurrence_agg INDEXED BY taxon_period`）、`iasSpecies`（`catalog.ts:1211`）、`redlistBundle`（`assessment.ts:214`）、`watershedYears`（`occurrence.ts:336`）。

**D. 時系列・地点**（`app/api/timeseries/route.ts`、`app/timeseries/page.tsx`、`app/sites/*`）: `waterBodies`・`variableCatalog`・`sites`・`sitesInWaterBody`・`site`（`catalog.ts`）、`queryCells`／`summarize`／`yearSeries`／`monthSeries`／`daySeries`／`rainDaily`／`rainMonthlyClim`（`observation.ts`。スコープの組み立ては `sql.ts:109 buildScopeSql`）、`timeseries()`（`timeseries.ts:67`、MCP `get_observations` と AI `get_timeseries` が共有）。

**E. MCP／AI**: MCP は `lib/mcp/tools.ts`（`describe_catalog` `:126`、`search_registry` `:175`、`get_observations` `:219`、`get_occurrences` `:273`、ほか `get_edna`・`export_dataset`）と `tools-records.ts`（`get_records`）・`tools-find-datasets.ts`。AI は `lib/ai/tools.ts`（`list_catalog`・`get_timeseries`・`get_seasonality`・`get_sites`・`get_biota_trend`・`get_redlist`・`get_overview`・`describe_schema`・`run_sql`・`get_edna`・`get_records`・`find_datasets`）。**どちらも `lib/cube` の同じ関数を呼ぶ**（ADR-0014）ので、cube 層に `region` を足せば薄い配線で済む。AI の画面文脈は `lib/ai/page-context.ts`（`PageContext`）→ `prompt.ts:156`。ディープリンクは `lib/ai/links.ts`。

**F. provenance**（`cube/envelope.ts`）: `resolveProvenance`（`:144`。行の系列 → `seriesInfo(series).sourceRefs` を数え上げ）、`resolveSeriesSetProvenance`（`:167`、ゾーン集計）、`buildDataEnvelope`（`:371`。呼び出し側が渡した出典を並べるだけ。`get_occurrences` は `OCCURRENCE_SOURCE_IDS` 全部を渡している＝神奈川の問い合わせでも奄美の出典が並ぶ）。`freshnessFor`／`freshnessForSeries`（`source-meta.ts:173,179`）も同じ過大さを持ち、`/api/timeseries`・`/api/biota` の `freshness` に出る。
原因: 出典は `variable_alias`（系列キー＝指標・統計・単位・粒度ごと）に付き、**同じ系列キーを両地域の出典が共有**している。例: `common:variable:water.bod` の alias は `atsugi_river_water_quality`、`env_kousui_{annual,sample}_{kanagawa,amami}`（計 5 出典）。`CellRow` に region が無いので、神奈川の地点だけの結果でも 5 件並び、`n_rows` も加算される。

## §2 計測

ローカル D1（`occurrence_agg` 1,544,660 行／`observation_agg` 2,771,033 行）。中央値ではなく 1〜2 回の実測（差は大きく、判断は変わらない）。

### 2-1 summary 4表（件数が加法でない）— 問い合わせ時に絞る場合 vs 事前集計

| 読み手 | 現状（全体） | (a) 問い合わせ時 `region_id` で絞る | (b) 事前集計（`*_by_region`）の読み | 新表の行数（地域別のみ） |
|---|---|---|---|---|
| 種の一覧 `speciesCatalog`（`summary_species_catalog`、28,270行） | 7 ms | 神奈川 **3,469 ms**／奄美 **860 ms**（全体の出典無し絞りも 3,396 ms）。`occurrence_agg INDEXED BY kind_grain_period` を全走査（1.45M／97k 行）＋ `taxon` JOIN＋GROUP BY | 6 ms（神奈川）／1 ms（奄美、group 絞り） | 31,006（jp-14 24,151＋jp-46 6,855） |
| `summary_effort_year`（171行。`n_binom`＝DISTINCT） | 〜0 ms | 神奈川 3,473 ms／奄美 962 ms | 〜0 ms | 297（171＋126） |
| `summary_taxon_catalog`（38,103行） | — | （同系の全走査） | 〜ms | 41,290（32,581＋8,709） |
| `summary_variable_catalog`（134行） | 〜0 ms | 神奈川 728 ms／奄美 724 ms（`observation_agg` を `region_id` で GROUP BY） | 〜0 ms | 201（119＋82） |
| 合計（新表） | | | | **72,794**（`place_region` 約 6,760 を足して約 79.6k） |

`EXPLAIN QUERY PLAN`（(a) の種の一覧）: `SEARCH o USING INDEX ix_occurrence_agg_kind_grain_period (place_kind=? AND grain=?)` ＋ `region_id=?` は残差条件。索引で `region_id` に届かないので行数は減らない。`(region_id, place_kind, grain, period_start)` の索引を足せば 1.4M→地域分に減らせるが、ビルド・D1 の書き込みが重く（`occurrence_agg` 154万行に索引1本追加）、GROUP BY・DISTINCT・taxon JOIN の計算は残る。事前集計のほうが桁違いに速いので採らない。
(b) の `EXPLAIN`: `SEARCH sbr USING INDEX ix (region_id=?)` ＋ `USE TEMP B-TREE FOR ORDER BY`（神奈川 24k 行を `n DESC` で並べ替え、6 ms。今の 28k 行と同程度）。索引は `(region_id, binom)`、`(region_id, taxon_id)`、`(region_id, year)`、`(region_id, variable_id)`。

### 2-2 加法・出典単位のもの（事前集計は不要）

| 読み手 | 絞り方 | 実測 |
|---|---|---|
| `summary_group_year`（2,727行。キーが `source_id` を含み、出典は地域に純粋） | `source_id IN (地域の出典)`。表は変えない | 〜ms |
| `summary_place_variable`（8,893行）・`summary_watershed_occurrence`（313）・`summary_grid_catalog`（5,817） | `place_region` と JOIN（place が地域に純粋なので加法） | 582行 JOIN 2 ms |
| 種ごとの問い合わせ（`speciesYears` 等、`INDEXED BY taxon_period`） | 既存の行（その種の全行）に `o.region_id=?` の残差条件を足すだけ | 変化なし（行数は種で決まる） |
| `speciesShareTrend`（鳥類 A/B 期間） | 同上 | 全体 257 ms／奄美 284 ms |
| `meshByYear`（2023年） | `o.region_id=?` を足す | 全体 103 ms／奄美 33 ms |
| 観測セル（`river_stage` 日次。最大系列 47万行） | `obs.region_id=?` を足す（`variable_id` 索引の範囲を引いてから残差で絞る） | 全体 129 ms／奄美 134 ms、月次 55 ms。**新索引は不要** |

### 2-3 結論

- 重いのは「`occurrence_agg` から種の単位に GROUP BY する」経路（種の一覧・努力量・taxon カタログ）と「`observation_agg` から系列単位に GROUP BY する」経路（`variable_catalog`）の2種類だけ。この4表を `*_by_region` にする。
- ほかの読み手は残差条件か JOIN で足り、新索引は要らない。
- D1 本番への影響: 新表の増分は約 7.9 万行（既存の `observation_agg`＋`occurrence_agg` 約 431万行の 1.8%）。**デプロイ順は D1 のデータが先、アプリが後**（新表は追加のみ。旧コードは新表を無視する）。

## §3 共通の型と約束（全担当が先に固定して読む）

### 3-1 地域の値

新規ファイル `web/src/lib/region.ts`（server-only を付けない。クライアントも使う。**担当 A1 が最初に作る**）:

```ts
import { REGION_TIME } from "@/lib/registry/generated-client";

/** 具体的な地域（registry/region.yaml の region_id）。 */
export type RegionId = (typeof REGION_TIME)[number]["regionId"]; // 生成物が string なら string 型でよい
/** 画面・URL・ツール引数の「絞り」。'all' = 合算（既定）。 */
export type RegionFilter = "all" | RegionId;

export interface RegionUi {
  id: RegionId;
  label: string;          // 切り替えの表示名: 神奈川県／奄美大島
  jumpLabel: string;      // 地図の移動ボタン: 神奈川県へ／奄美大島へ
  bounds: [[number, number], [number, number]]; // [[lon_min, lat_min], [lon_max, lat_max]]
}
export const REGIONS: readonly RegionUi[] = [...]; // jp-14, jp-46 の順
export const REGION_ALL = "all" as const;
export function parseRegion(raw: unknown): RegionFilter;     // 'all'|既知の RegionId 以外（空・不正・配列）は 'all'
export function regionOf(f: RegionFilter): RegionId | undefined; // 'all' → undefined（cube 層へはこの形で渡す）
export function regionLabel(f: RegionFilter): string;       // all → 全体
```

- `label` を registry の `region.name_ja` にしない（jp-46 は「鹿児島県」。UI の語は「奄美大島」）。`REGIONS` は UI の語彙を持つ唯一の場所で、`REGION_JUMPS`（`basemaps.ts`）は `REGIONS` から導く（直書きを散らさない）。
- 整合テスト `region.test.ts`: `REGIONS` の id 集合 = `REGION_TIME` の regionId 集合（registry に地域が増えて UI に足し忘れたら落ちる）。
- **cube 層は `region?: RegionId`**（`undefined` = 全体）を受ける。`'all'` は cube に入れない。API・ページ・ツールの入口で `regionOf(parseRegion(...))` に直す。
- 不正値（`?region=xx`）は全体にする（400 にしない。リンクが壊れても画面は出る）。MCP／AI のツール引数は zod の `enum`（`REGIONS` から作る）で不正値を入力エラーにする（URL の寛容さと別。モデルの入力ミスは返して直させる）。

### 3-2 cube 層の共通部品

新規ファイル `web/src/lib/cube/region.ts`（**担当 A1 が `region.ts` と同時に作る**。A2 は下のシグネチャで先に書き始めてよい）:

```ts
import type { RegionId } from "@/lib/region";
import type { SqlParam } from "./sql";

/** `<alias>.region_id = ?`。region が undefined なら空（条件なし）。 */
export function regionPred(alias: string, region: RegionId | undefined): { sql: string; params: SqlParam[] }; // sql は " AND ..." 形ではなく "alias.region_id = ?" 単体 or ""
/** place_region への INNER JOIN 断片（alias の place_id が region に属するものだけ）。region が undefined なら joins=[]。 */
export function placeRegionJoin(placeAlias: string, region: RegionId | undefined): { joins: string[]; params: SqlParam[] };
/** 出典の地域（マニフェスト由来の生成物 SOURCE_REGION）。未宣言は undefined。 */
export function sourceRegion(sourceId: string): RegionId | undefined;
/** その地域の出典 ID。region undefined は全部。地域未宣言の出典は「全地域に属する」扱いで常に含める（共通出典: moe_ias_list 等）。 */
export function sourcesOfRegion<T extends string>(ids: readonly T[], region: RegionId | undefined): T[];
```

- 生成物 `SOURCE_REGION: Readonly<Record<string, string>>` は `web/src/lib/registry/generated-source.ts` に出す（§7 D の r01／`build-registry-ts.mjs`）。生成物が出るまで、A1 は `generated-source.ts` に手で足さず、`cube/region.ts` から `SOURCE_REGION ?? {}` を import する形でスタブせず**D の成果をマージしてから**結合テストする（単体テストはフィクスチャで `sourceRegion` を差し替える）。
- テーブル名は新規 `place_region`、`summary_*_by_region`（§3-3）。`region` が undefined のときは**一切これらの表を引かない**（既存の SQL 文字列を変えない）。

### 3-3 新しい表（スキーマの正。`web/src/db/schema-cube.ts`、担当 D）

A2 のフィクスチャもこの DDL で作る。列は既存の同名表と同じ＋先頭に `region_id`。

| 表 | 列 | 索引 |
|---|---|---|
| `place_region` | `place_id` text NOT NULL, `region_id` text NOT NULL, `built_from`, `spec_version` | `(place_id)`, `(region_id, place_id)` |
| `summary_species_catalog_by_region` | `region_id` text NOT NULL ＋ `summary_species_catalog` の全列（binom, taxon_group, class, family, n, n_located, n_red_list, n_alien, n_places, y_from, y_to, n_years, built_from, spec_version） | `(region_id, binom)` |
| `summary_taxon_catalog_by_region` | `region_id` ＋ `summary_taxon_catalog` の全列 | `(region_id, taxon_id)` |
| `summary_effort_year_by_region` | `region_id` ＋ `summary_effort_year` の全列 | `(region_id, year)` |
| `summary_variable_catalog_by_region` | `region_id` ＋ `summary_variable_catalog` の全列 | `(region_id, variable_id)` |

意味: 各 `*_by_region` の行 = 対応する既存表の定義（`aggregations/serving.yaml`）を、その地域の `occurrence_agg`／`observation_agg` の行だけに絞って作ったもの。`place_region` = 各 place が属する地域（観測・出現のキューブの `region_id` の和集合に、site の `place.region_id` を加えたもの。**1つの place が2地域に出たら b13 が止まる**）。

### 3-4 「全体」は現状と完全に同一

- `region` が undefined のとき、すべての問い合わせは**現在と同じ SQL 文字列・同じパラメータ**（新しい条件・JOIN を足さない）。テストで担保する（各担当の受け入れ: 既存のテストを一切変更せずに通る）。
- serving snapshot（`data/sample/serving_snapshot.json`、`pnpm run serving:snapshot -- --mode snapshot`）は**変わらない**ことを受け入れ基準にする。snapshot の問い合わせ定義（`web/scripts/lib/serving/`）に region 付きのものは足さない（凍結スナップショットを増やさない。地域つきはユニットテストで見る）。
- 例外: レッドリスト。現状は「画面は神奈川の3版のまま」（`assessment.ts:94`）。**全体は神奈川の3版のまま（現状維持）**、`jp-14` も同じ、`jp-46` は鹿児島県レッドリスト（kgrl2014、2,810 行。`prev_category_code` が全行 NULL なので版間比較は出せず、`flows` は空・件数の summary のみ）。

### 3-5 サーバへの渡し方

- ページ（server component、`force-dynamic`）: `searchParams.region` を `parseRegion` → `regionOf`。
- API ルート: `req.nextUrl.searchParams.get("region")`。クライアントの `useJson` の URL に `&region=...` を足す（全体のときは**付けない**。キャッシュキー・URL が現状と同じ）。
- 地図 API のような `Cache-Control: public, max-age=300` は URL（`?region=`）がキーになるのでそのまま。
- MCP／AI: ツール引数 `region`（省略 = 全体）。応答の `query` に `region`（省略時 null）を入れる。AI は画面文脈の地域を既定として使うようプロンプトに書く（§5）。

### 3-6 provenance の約束

- `CellRow` に `regionId: string | null` を足す（`observation_agg.region_id` を SELECT に加える）。
- `resolveProvenance`: 行の系列の `sourceRefs` のうち、**行の `regionId` と出典の地域が一致するもの**（出典の地域が未宣言なら残す）だけを数える。`n_rows` も同じ集合だけで加算。これは**全体でも効く**: 全体の結果でも神奈川の行は神奈川の出典だけ、奄美の行は奄美の出典だけ帰属する（今は全体のときも交差して過大）。→ §3-4 の「全体は同一」の**宣言済み差分**（provenance の行と `n_rows` だけ。§8 受け入れ 6 に具体値）。snapshot に provenance が入っていれば `--mode diff` の before/after を PR に貼る。入っていなければ（行の値のみなら）snapshot は変わらない。担当 A1 は最初に `serving-snapshot` の定義が provenance を含むかを確認する。
- `resolveSeriesSetProvenance`／`freshnessForSeries`／`freshnessFor`: `region` を受けて `sourcesOfRegion` で絞る（region undefined は現状どおり）。
- `buildDataEnvelope` の呼び出し側（MCP `get_occurrences`・`search_registry`・`describe_catalog`）は渡す出典を `sourcesOfRegion(..., region)` で絞る。
- 同じ地域内で複数出典が同じ系列を共有する場合（例: jp-14 の BOD の `atsugi_river_water_quality` と `env_kousui_*_kanagawa`）は、セルが出典を持たないので従来どおり並ぶ（`get_observations` の説明どおり）。**この近似は残る**とドキュメントに書く。
- 封筒の `time_zone.region_id` は時刻帯のための値（`EnvelopeOpt.regionId`、既定 `DEFAULT_REGION_ID='jp-14'`）。地域で絞る `region` とは別名で扱い、混ぜない。`region` が `jp-46` のときは `regionId: 'jp-46'` も渡す（両方 JST で見た目は変わらないが、`fetchedAtIso` が region.yaml のオフセットを引くので正しい地域を渡す）。

## §4 担当 A: 問い合わせ層（`web/src/lib/cube/`）— 2担当に分けて並行

ファイル所有が重ならないように A1／A2 に分ける。**A1 が先に `lib/region.ts` と `cube/region.ts`（§3-1・§3-2）をコミットし、A2 は同じシグネチャで並行して書く。結合は A1 → A2 の順にマージ。**

### A1: 観測系・provenance

触るファイル: `web/src/lib/region.ts`（新規）、`web/src/lib/cube/region.ts`（新規）、`cube/sql.ts`、`cube/observation.ts`、`cube/timeseries.ts`、`cube/envelope.ts`、`cube/source-meta.ts`、`cube/caveats.ts`、`cube/assessment.ts`、`cube/index.ts`（export 追加）、`cube/__fixtures__/cube-fixture.ts`、テスト。

変更:
1. `CellSpec`（`observation.ts:33`）に `region?: RegionId` を足す。`commonFilterSql`／`buildScopeSql` 経由で `${alias}.region_id = ?` を WHERE に足す（`whereParams` に積む。JOIN 節・WHERE 節のパラメータ順の規約に従う）。`queryCells`／`summarize`／`yearSeries`／`monthSeries`／`daySeries`／`rainDaily`／`rainMonthlyClim` が通す。
2. `RawCellRow`／`CellRow` に `region_id` を足す（SELECT に追加。`region` 未指定でも常に SELECT する — 列が1本増えるだけで WHERE は変わらない。§3-4 の「同一」は WHERE／結果の意味で見る）。
3. `TimeseriesInput`（`timeseries.ts:50`）に `region?: RegionId`。`sitesInWaterBody`（A2 の関数）に `region` を渡す。`envelopeOpt.regionId` に地域を渡す。
4. provenance: §3-6 のとおり `resolveProvenance`／`resolveSeriesSetProvenance`／`buildDataEnvelope` の呼び出し側向けの絞り、`freshnessFor`／`freshnessForSeries` に `region` 引数。
5. `assessment.ts`: `REDLIST_REGION` 固定をやめ、`redlistSummary`／`redlistFlows`／`redlistSpecies`／`redlistBundle` に `region?: RegionId` を足す。undefined と `jp-14` は現状の `jp-14` 3版、`jp-46` は `ASSESSMENT_LIST` の `region==='jp-46' && kind==='red_list'`（3-4 例外）。
6. `caveats.ts`: `facetsForOccurrence` の `sourceIds` 既定が `OCCURRENCE_SOURCE_IDS` 全部の箇所に、地域の出典で絞る口を足す（B が呼ぶ）。
7. `cube/index.ts`: `regionPred` 等と `RegionId` を export。

速い検証: `cd web && pnpm vitest run src/lib/region.test.ts src/lib/cube/sql.test.ts src/lib/cube/observation.test.ts src/lib/cube/envelope.test.ts src/lib/cube/timeseries-sources.test.ts src/lib/cube/source-meta.test.ts src/lib/cube/assessment.test.ts`。新規テスト: ①`region` 未指定で既存 SQL 文字列が不変（スナップショット）、②フィクスチャに jp-14／jp-46 両地域の行を入れ、`region='jp-46'` で jp-14 の行が 0・件数が一致、③provenance（BOD 相当の2地域共有系列で、jp-14 の行だけなら奄美の出典が出ない）。

### A2: 出現系・カタログ・サマリ

触るファイル: `cube/catalog.ts`、`cube/occurrence.ts`、`cube/__fixtures__/occurrence-fixture.ts`（`rollup-fixture.ts`）、テスト（`catalog*.test.ts`、`occurrence.test.ts`）。`cube/index.ts` は A1 が export を担当するので、A2 は export が要るものを A1 に伝える（衝突回避）か、`catalog.ts`／`occurrence.ts` 内の export の追加だけにとどめる（`index.ts` の既存の `export *` に載る形なら触らない）。

変更（すべて `region?: RegionId` を最後のオプションに足す。undefined は現在の SQL をそのまま使う）:
1. **事前集計表を読む4関数**: `speciesCatalog`（`SpeciesCatalogOpt.region`）、`effortYears`、`occurrenceTotals`（`records`＝`summary_effort_year_by_region.n` の合計、`species`＝`summary_species_catalog_by_region` の行数、`grids`＝`summary_grid_catalog` JOIN `place_region`、`gbif`/`inat`＝`summary_group_year` を `sourcesOfRegion` で絞る）、`variableCatalog`（`summary_variable_catalog_by_region`。`summaryCatalogCells` の `summary_place_variable` は `placeRegionJoin` で絞る）。`speciesCatalogBySource` は `occurrence_agg` を直接引く経路で、`o.region_id = ?` を足す（出典指定と地域指定の併用を可）。
2. `taxonGroupYears`（`summary_group_year`）: `source_id IN (sourcesOfRegion(...))`。`gridCatalog`／`watershedOccurrence`／`watershedRollup`／`landuseHighlight`／`watershedBases`／`loadLanduse`: `placeRegionJoin`（流域・グリッドは `place_region` で絞る）。`loadLanduse` の `landuseYears` は地域の流域だけで計算する。
3. `overviewCounts`: `sites`＝`sites` JOIN `place_source_ref` JOIN `place_region`、`watersheds`＝`place` JOIN `place_region`（kind='watershed'）、`variables`／`y_from`／`y_to`＝`summary_variable_catalog_by_region`。`sources`（出典の件数）は絞らない（未決1。画面側で「全地域共通」と添える）。
4. `sites()`／`site()`／`sitesInWaterBody()`／`waterBodies()`／`siteRollupSql`: `place_region` で絞る（`site(siteId)` は単一地点なので絞らない）。
5. `occurrence.ts` の `speciesYears`／`speciesYearsWithCoverage`／`speciesCatalogCounts`／`speciesMonths`／`speciesMeshYears`／`speciesShareTrend`／`meshByYear`／`watershedYears`: `AND o.region_id = ?` を足す（`SourceFilterOpt` と同じ流儀で `RegionFilterOpt { region?: RegionId }`。`INDEXED BY` はそのまま）。`speciesShareTrend` の `summary_species_catalog` は taxon_group の引き当てにだけ使う（地域別でなく既存表のままでよい）。`iasSpecies`（`taxon_assessment`＋`summary_species_catalog` JOIN）は地域別表を使うか `occurrence_agg` の `region_id` で絞る（件数が地域で変わる）。
6. **`summary_species_catalog` を直接読む箇所を洗い出して一覧にする**（`catalog.ts:980,1133,1217`、`occurrence.ts:233` 付近ほか）。`region` 指定時にどれも既存表を読まないこと。

速い検証: `cd web && pnpm vitest run src/lib/cube/catalog.test.ts src/lib/cube/catalog-occurrence.test.ts src/lib/cube/catalog-rollup.test.ts src/lib/cube/occurrence.test.ts`。新規テスト: ①`region` 未指定で既存テストを一切変更せず通る、②2地域フィクスチャで `speciesCatalog({region})` の行・`occurrenceTotals` が各地域の合計で、和が全体に一致（加法の表）、③`place_region` が無い地域・空の地域は0行（例外にしない）、④`summary_species_catalog_by_region` の行を `region` 別に持つフィクスチャ。

担当間の依存: A2 は A1 の `region.ts`／`cube/region.ts` のシグネチャ（§3）にだけ依存。A1 の `CellSpec.region` を A2 の `sitesInWaterBody` は使わない。D の表の DDL（§3-3）はフィクスチャが自前で `CREATE TABLE` するので D のマージを待たない。

## §5 担当 B: MCP／AI ツール

触るファイル: `web/src/lib/mcp/tools.ts`、`mcp/tools-records.ts`（変更なし、確認のみ）、`web/src/lib/ai/tools.ts`、`ai/prompt.ts`、`ai/page-context.ts`、`ai/links.ts`、`web/src/lib/table-meta.ts`（新表の説明。D と衝突するので D が担当、B は `TABLE_META` を触らない）、テスト（`mcp/*.test.ts`、`ai/*.test.ts`、`api/mcp/route.test.ts`）。
依存: A1／A2 のシグネチャ（§3、§4）。**B は §3-1 の `REGIONS`・`parseRegion` を A1 から待たずに使える形で（import 先は固定）並行して書き、結合は A1・A2 のマージ後。**

変更:
1. 共通の zod 部品 `regionSchema`（`z.enum(REGIONS.map(r=>r.id))` を optional で、`.describe("地域で絞る。省略は全体（神奈川・奄美の合算）。")`）を MCP と AI で共有する場所に1つ作る（`lib/mcp/tools.ts` から export し AI が import、または `lib/region.ts` と同階層）。z.tuple は使わない（Workers AI が 400 になる。メモリ参照）。
2. MCP: `get_observations`／`get_occurrences`／`search_registry`（kind=species）／`describe_catalog`（what=variables|waters）に `region` を足し、cube 層に配線。応答の `query.region`、`provenance` は `sourcesOfRegion` で絞った出典（`get_occurrences` の `OCCURRENCE_SOURCE_IDS` 全部渡しをやめる）、`occurrenceCaveats(sourceIds)` も同じ絞り。`describe_catalog what='sources'`／`zones` は絞らない。`get_edna`（神奈川のみ）・`get_records`・`find_datasets`・`export_dataset` は変えない（description に「地域では絞らない」と1行）。ツールの `description` に「`region` を省略すると全体（神奈川・奄美の合算）。地域で件数や出典が変わる」を足し、`READING_RULES` に1文。
3. AI: `list_catalog`・`get_timeseries`・`get_seasonality`・`get_sites`・`get_biota_trend`・`get_redlist`・`get_overview` に `region`。`get_overview` は `overviewCounts`＋`watershedRollup` を `region` で。`describe_schema`／`run_sql` は変えないが、`describe_schema` が返す `TABLE_META`（D が更新）に地域別表の使い方を載せ、プロンプトに「`summary_*` は全地域の合算。地域で絞るなら `*_by_region` を使う」を1行。
4. `PageContext` に `region: RegionFilter`（全 route 共通のフィールド）を足し、`describePageContext` に「地域=奄美大島」を足す。`AssistantPanel`（C が所有）が URL の region を `pageContext` に乗せる。`prompt.ts` に「画面の地域が all 以外のときはツールの `region` にそれを渡す。利用者が別の地域を明示したらそちらに従う。省略した答えは合算であることを答えに書く」。**注意書きはサーバが機械的に付ける方針**（メモリ参照）なので、応答の `query.region` を機械的にカード側が出す。モデル任意のツールにしない。
5. `ai/links.ts`: `timeseriesUrl` 等のディープリンクに `region` を足す（'all' は付けない）。`set_view` は作らない（メモリ参照）。

速い検証: `cd web && pnpm vitest run src/lib/mcp src/lib/ai src/app/api/mcp`。新規テスト: ①引数なしの呼び出しの出力が現状と一致（既存の `__snapshots__` を変更しない。provenance の差は A1 の宣言済み差分として snapshot に出るなら、更新する前に差分が §3-6 の範囲か確認）、②`region='jp-46'` で出典に jp-14 のものが出ない、③不正な `region` は入力エラー、④`strict()` スキーマに `region` が入っても未知のキーは弾かれる。

## §6 担当 C: 画面（切り替え UI・URL・地図・各ページ）

触るファイル: `web/src/components/SiteNav.tsx`、`web/src/components/RegionSwitcher.tsx`（新規）、`web/src/components/useRegion.ts`（新規）、`web/src/app/layout.tsx`、`app/page.tsx`、`app/sites/page.tsx`、`app/timeseries/page.tsx`、`app/api/geo/{watersheds,sites,mesh}/route.ts`、`app/api/biota/route.ts`、`app/api/timeseries/route.ts`、`components/map/MapPage.tsx`、`components/map/MapCanvas.tsx`（props のみ）、`components/biota/BiotaExplorer.tsx`、`components/timeseries/TimeseriesExplorer.tsx`、`components/sites/SiteList.tsx`、`components/HomeHighlights.tsx`（地域名の見出し）、`components/assistant/AssistantPanel.tsx`・`PageContextProvider.tsx`（`pageContext.region`）、`lib/map/basemaps.ts`（`REGION_JUMPS` を `REGIONS` から導く）。
依存: A1 の `lib/region.ts`（§3-1）と A2 のシグネチャ。

変更:
1. **切り替え UI**: `SiteNav` に3択（全体／神奈川県／奄美大島）のセグメントを置く（`RegionSwitcher`、`REGIONS` から作る）。選ぶと現在の URL の `region` クエリだけを差し替える（`router.replace`、他のクエリは保つ。'all' は `region` を**消す**）。`useSearchParams` を使うので `layout.tsx` で Suspense に包む。
2. **URL が正**: `useRegion()` が `useSearchParams` → `parseRegion`。ナビのリンク（`NAV`）にも現在の region を引き継ぐ（'all' のときは付けない＝現状と同じ URL）。クッキー・localStorage は使わない（リンクで共有できる性質を保つ）。
3. **サーバ側ページ**: `app/page.tsx`・`app/sites/page.tsx`・`app/timeseries/page.tsx` は `searchParams.region` を受け、cube に渡す（トップは `overviewCounts`・`longitudinalHighlight`・`landuseHighlight`・`redlistSummary`・`effortYears`・`occurrenceTotals`）。**トップの見出しの件数（観測地点・指標・生物レコード・単位流域・出典）は地域つきで変わる。「出典」は絞らない旨を注記**（未決1）。`longitudinalHighlight`（境川固定）は jp-46 のとき既定の水域が無いので、`waterBodies` の最初の水域に落とすか、そのハイライトを出さない（実装時に jp-46 の水域名を確認して決める。境川の数字・固定文言は全体と jp-14 で変えない）。
4. **API ルート**: 上記ルートが `region` クエリを読んで cube へ渡す。`/api/timeseries` の `freshness`、`/api/biota` の `freshness` も `region` で絞る。クライアントの `useJson` の URL に `&region=` を足す（全体は付けない）。
5. **地図**: `MapPage` が `useRegion()` を読む。初期表示は `region` が `all` なら現状（`MapCanvas` 既定の神奈川中心）、`jp-14`／`jp-46` ならその `bounds` へ `fitBounds`（初回マウント時に `jump` を `{bounds, nonce}` で1回セット）。切り替え時も同じ。`REGION_JUMPS` のボタンは**全体のときだけ**残す（地域を絞っているときは切り替えと二重になるので隠す）。`/api/geo/*` に `region` を渡す。流域の色の分位（`quantileBreaks`）が地域内の値だけで再計算されるのは意図どおり（注記に書く）。
6. 生物相（`BiotaExplorer`）・時系列（`TimeseriesExplorer`）: 初期値を `searchParams` から読む既存の仕組みに乗せ、`region` は `useRegion()` から全リクエストに付ける。水域の選択肢（`mode=waters`）は地域の水域だけになる。地域を切り替えて選択中の水域が無くなったら、既存の自動補正（実効値の水域）に任せる。
7. **AI パネル**: `pageContext.region` を `useRegion()` から付ける（B が型とプロンプトを持つ）。
8. `/water`（水源マップ）・`/documents`・`/sources`・`/explore` は絞らない。`/water` は神奈川県だけの画面なので、地域が `jp-46` のときは「神奈川県のみ」と1行出す（任意。最小実装では何もしない）。

速い検証: `cd web && pnpm vitest run src/components src/lib/region.test.ts`（`useRegion`／`parseRegion`／ナビのリンク生成の単体テスト）。画面の動作は「実機確認」として、`pnpm run dev` で `/?region=jp-46`・`/map?region=jp-46`・`/biota?region=jp-46`・`/timeseries?region=jp-46` が開き、切り替えで URL が変わり、'all' で `region` が消えることを1回確かめる（ブラウザ。メインかこの担当）。

## §7 担当 D: パイプライン・スキーマ・生成物（事前集計を採るときのみ）

触るファイル: `aggregations/serving.yaml`、`scripts/b13_build_summary.py`、`scripts/tests/test_b13_build_summary.py`、`web/src/db/schema-cube.ts`（§3-3 の5表）、`web/drizzle/migrations/`（`pnpm run db:generate` で生成。手で書かない）、`web/src/lib/table-meta.ts`（`TABLE_ORIGIN`・`TABLE_META` に5表）、`scripts/r01_build_registry.py` ほか registry の出典メタ（`source.region_id` をマニフェストの `region` から埋める）、`web/scripts/build-registry-ts.mjs`（`SOURCE_REGION` を `generated-source.ts` に出す）、`web/src/lib/registry/generated-source.ts`（再生成物）、`web/scripts/seed-d1-local.mjs`／`export-d1-sql.mjs`（表の列挙が手書きなら5表を足す。自動なら確認のみ）、`scripts/tests/test_cube_index_parity.py`（索引名の整合に新表が含まれるなら）。
依存: なし（A・B・C より先、または並行。A2 のフィクスチャは §3-3 の DDL で自前に作る）。

変更:
1. `serving.yaml`: 4つの spec（`summary_species_catalog`／`summary_taxon_catalog`／`summary_effort_year`／`summary_variable_catalog`）に宣言 `by_region: true` を足す。b13 は `by_region` の spec について**同じ定義で `region_id` を group_by・key の先頭に足した表** `<name>_by_region` を作る（`filter`・`measures`・`join` は同じ）。YAML バリデータ（`_validate_summary_spec`）に `by_region` を許可する。`spec_version` を `serving-summary/v6` → `v7` に上げる（→ `check_v2_fresh.py` が古いと判定し、全員が v2 を作り直す。PR 本文に書く）。
2. `place_region`: b13 の後処理（宣言的でなく関数）。`SELECT DISTINCT place_id, region_id FROM observation_agg WHERE place_id IS NOT NULL UNION occurrence_agg ...` に、`place`（registry）の site の `region_id` を足す。**1つの place が2つ以上の地域に出たら例外で止まる**（今は 0 件であることを実測済み）。`region_id IS NULL` の行は入れない（観測のキューブの `region_id` は nullable）。
3. 保存則の自己検査（b13 の既存の `_conservation_totals` の流儀）: 各 `*_by_region` について、加法の測度（`n`・`n_red_list`・`n_alien`・`n_located`・`n_places`〔場所が地域に純粋なので和が一致〕）の地域和が既存の全体の表の同じ測度に一致。`y_from`＝地域の最小の最小、`y_to`＝最大の最大。`n_years`・`n_binom`・`n_taxa` は加法でないので検査しない（地域別が全体以下であることだけ）。
4. registry: `source.region_id` を、マニフェストのある出典についてその `region` で埋める（`scripts/migrate/source_regions.py` の `load_source_regions()` を使う。マニフェストの無い出典は NULL のまま）。`build-registry-ts.mjs` が `SOURCE_REGION` を出す。`r01 --check-fresh` の鮮度判定に影響するので、registry を作り直す。
5. 数値の確認（PR 本文に貼る）: 各 `*_by_region` の行数（本設計書 §2-1 の 31,006／41,290／297／201 と一致）、`place_region` の行数と地域別内訳、保存則 OK。

速い検証（重い全量は回さない）: `cd /home/yu23ki14/cfj/ryuiki-demo && .venv/bin/python3 -m pytest scripts/tests/test_b13_build_summary.py scripts/tests/test_cube_index_parity.py`。b13 全量・`build:v2`・b00 ゲート（`reports/serving_fingerprint.json`）はメインが PR 直前に1回だけ裏で回す（パイプラインのパスを触るので b00 を回してフィンガープリントも一緒にコミットする）。

## §8 受け入れ基準

実測値はローカル D1（2026-10-11）。数字が合わなければ、まず実データの変化かを疑う。

1. **全体で現状と同一**: `region` なしのテストが既存の期待値のまま通る（既存テストのファイルは変更しない）。`cd web && pnpm run serving:snapshot -- --mode snapshot` が通る。provenance の差は §3-6 の宣言済み差分のみで、snapshot に載る場合は `--mode diff` の before/after を PR に貼る。
2. **件数・種数が地域で絞られる**（`occurrenceTotals`／`speciesCatalog`／`effortYears`）:
   - 生物レコード（`records`、日付のある記録）: 全体 887,565／jp-14 827,725／jp-46 59,840（和が一致）。
   - 種数: 全体 28,270／jp-14 24,151／jp-46 6,855（重複 2,736 種があるので和は全体より大きい）。
   - 種の一覧の応答: `region=jp-46` が 1 秒未満（今の全体は 7 ms。問い合わせ時絞りの 3.5 s にならない）。
3. **トップの件数**: 観測地点 全体 389／jp-14 352／jp-46 37。観測指標（地点年平均の variable）全体 83／jp-14 75／jp-46 58。単位流域 全体 402／jp-14 377／jp-46 25（今の全体の表示は 402 面。画面の文言「377 面」は固定文言なので地域つきの値に直すか確認）。
4. **地図**: `/api/geo/watersheds?region=jp-46` が 25 フィーチャ、`/api/geo/sites?region=jp-46` が 37（`n_meas>0` の地点のみ）、`/api/geo/mesh?region=jp-46` が 1,731 グリッド（`year` 未指定）。`/map?region=jp-46` で開くと奄美の範囲へ移動して始まる。
5. **時系列**: `/api/timeseries?mode=waters&variable=common:variable:water.bod&region=jp-46` の水域に神奈川の水域が出ない。`waterBodies` の地点数の和が全体に一致。
6. **provenance**: `get_observations`（`variableId=common:variable:water.bod`、region=jp-14）の provenance に `env_kousui_annual_amami`／`env_kousui_sample_amami` が出ない（出典は `atsugi_river_water_quality`・`env_kousui_annual_kanagawa`・`env_kousui_sample_kanagawa` の3件、今は5件）。region=jp-46 は `env_kousui_annual_amami`・`env_kousui_sample_amami` の2件。`get_occurrences`（region=jp-14）に `gbif_amami_occurrences`／`inaturalist_amami` が出ない。`jma_monthly_amami` が jp-14 の気温の結果に出ない（気温は `weather.air_temp`、region=jp-14 で）。`n_rows` の和が行数に一致。
7. **`?region=jp-46` で奄美が開く**: `/`・`/map`・`/biota`・`/timeseries`・`/sites` のどれも。`?region=xx` は全体として開く（エラーにしない）。
8. **MCP／AI が region を受け取る**: 上記ツールのスキーマに `region`（enum: jp-14／jp-46、省略可）。不正値は入力エラー。応答の `query.region` が入る。
9. **レッドリスト**: 全体と jp-14 は現状と同じ（神奈川の3版）。jp-46 は kgrl2014 の件数が出て、版間比較（flows）は空。
10. 新表の行数が §2-1 と一致（31,006／41,290／297／201）、保存則の自己検査が通る。
11. 新表の `TABLE_META`／`TABLE_ORIGIN` が登録されている（`table-meta` の整合テストが通る）。

## §9 未決・リスク

### オーナーに聞く（無理に作らない）

1. **出典の地域**: 148件の出典（文書・台帳・計画書など）に地域の宣言が無い（名前に `_amami` を含む34、`_kanagawa` を含む39、その他約75は不明）。今回は `/sources`・`/documents`・トップの「出典 N 件」・`describe_catalog what='sources'`・`get_records` を**絞らない**（全地域共通の一覧）。絞りたければ `registry/source/region.yaml`（出典ごとに jp-14／jp-46／共通を宣言し、全件の宣言漏れを CI で止める）を別 Issue で作る。聞きたい: 「今回は絞らず別 Issue でよいか」。既定は別 Issue。
2. **トップのハイライト**: `longitudinalHighlight`（境川固定）と `HomeHighlights.tsx` の固定文言（「5倍近い差」等）は神奈川の数字。奄美・全体のときにどう見せるか（出さない／奄美に相当する川を選ぶ）。既定は全体と jp-14 は現状のまま、jp-46 は出さない（見出しだけ）。

### リスク

- **summary 表の直接参照**: `summary_species_catalog` 等を `run_sql`／`/api/sql`／`describe_schema` で直接引く人は地域を絞れない（既存表は全体のまま）。`TABLE_META` とプロンプトで `*_by_region` を案内する。
- **v2 の作り直し**: `spec_version` を上げるので全員の `build:v2` が走る。CI の sample-gate（`data/sample`）が `*_by_region` と `place_region` を作れるか（サンプルに両地域が含まれるか）を D が確認する。含まれない地域は0行でよい。
- **デプロイ順**: D1 の新表のデータ投入（`db:export` → `wrangler d1 execute --remote`）を先に、アプリを後に。逆だとアプリが存在しない表を引いて落ちる（`region` 指定時のみ。全体は旧表のまま動く）。
- **provenance の近似が残る**: 同じ地域内で複数の出典が同じ系列を共有するとき、セルが出典を持たないので並びは従来どおり。書き出す側（`cite_as`）に「地域内の複数出典が寄与しうる」を添える。
- **大きい母集団の GROUP BY が残る箇所**: `iasSpecies`（地域で絞る場合）と `speciesCatalogBySource` の `region`＋`source_ids` 併用は `occurrence_agg` を直接引く。`taxon_period` 索引経路（種ごと）は小さいが、`kind_grain_period` 経路は全走査（神奈川 3.4 s）。この2つは「出典または種を絞ったとき」だけで、地域単独の一覧は事前集計表を使うので画面の既定経路にはならない。
- **`place.region_id` の NULL**: 流域・グリッドの NULL は ADR-0022 の決定。`place_region` で補う（ADR は覆さない）。
- **「奄美大島」と `region.name_ja`「鹿児島県」**: UI の語は `REGIONS` に持つ。registry の `name_ja` を画面に出す箇所があれば揃える。

## §10 作業の進め方（推奨）

並行: **D（スキーマ・b13・registry）** と **A1（region.ts・観測・provenance）** を同時に起動し、A1 が `region.ts` を出したら **A2・B・C** を起動（または最初から A2・B・C も §3 のシグネチャで並行）。統合順は D → A1 → A2 → B → C。メインが PR 直前に1回だけ重い検証（`build:v2`・b00 全量ゲート・snapshot 全量）を裏で回す。レビューは /code-review（medium）と /simplify（1本）を同時に、生成物（`web/drizzle/migrations/meta`・`reports/`・`generated*.ts`）を対象から外す。
