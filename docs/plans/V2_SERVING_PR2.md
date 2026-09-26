# Issue #48 PR-2「測定値系の切り替え（値が動く）」実装設計

## 0. 要点（先に読む）

1. **合成データの矛盾の推奨: (d) 「v1互換の診断キューブ」方式。** b03 は既定で `is_synthetic=1` を除く（ADR-0030 D4 どおり、wip ブランチ 282d346 の実装を採用）。b02 の突合ゲート（sample-gate・full-gate-proof）には、同じ b03/b04 を `--include-synthetic --out data/db/v2_v1compat.sqlite` で回した**診断専用の第2キューブ**を b05 に読ませる（`b05 --cube-db data/db/v2_v1compat.sqlite`）。b02 は無変更・宣言済み差分20件のまま緑。serving-diff も同じ第2キューブを `--v1compat-db` で開き、`synthetic_excluded` を「v1 == v2(合成込み) かつ v2(合成込み) ≠ v2(除外後)」の**差分の差分**で判定する（PR-1 で 309 件が unexplained になった合算問い合わせ〔zone/climatology/var_catalog/water_bodies〕もこれで説明できる）。使い捨てのコード量は b03 のフラグ＋ガード（約30行）・b00/CI の3行・serving-diff の第2接続（約80行）だけで、PR-5 で b02/b05 ごと消える。
2. **実測で PR-1 の前提が2つ崩れている**（数字は §付録。手元の `v2.sqlite`/`registry.sqlite` は `check_v2_fresh.py` で exit 10＝古い。worktree `.claude/worktrees/agent-a8b8fc0f16b5187e6/data/db/` の12列キー版と main の `registry.sqlite`(9/24) で測ったので参考値）:
   - **合成データは「合成専用の地点」ではなく実在地点に混ざっている**。`sites.is_synthetic` は352件すべて0。`measurements` の合成2,265行は環境省公共用水域18地点（相模湖・津久井湖・相模川系、実データもある）と moni1000 の6地点（合成のみ）に載る。80 の (site, variable) 組のうち54組は実データも持つ。日セルでは「純合成」7,037・「混在」21。→ PR-1 の `computeSyntheticPlaceIds`（地点の全系列が合成なら除外）と `--pretend-synthetic-excluded` は**除外の近似として不正確**。PR-2 で撤去する。
   - **合成データの5系列（tuple）は全部、実出典と同じ tuple を共有している**（DO/SS は atsugi の day/mean、pH/水温/気温は env_kousui_sample の day/point）。→ `series.isSynthetic()`（`sourceIds` に null を含む）と facet `dataset='synthetic'`（PR-1 D4 の規約）は、除外後も**実データの pH/水温/気温/SS/DO に「合成データ」注記を付けてしまう**。PR-2 で `isSynthetic`・`facetsForSeries` の synthetic push・`envelope.excluded.reasons: synthetic_included` を撤去する（`caveat_scope` の `dataset='synthetic'` 行は PR-4 で合成表と一緒に消す）。
3. **lod への切り替えは serving-diff を2回回す**（`--imputation zero`＝回帰、`--imputation lod`＝「値が動いた」の計数）。lod 実行では v2 アダプタが同じ問い合わせを zero でも引き、`lod_imputation` 規則＝「v1 == v2(zero) かつ v2(lod) ≠ v2(zero)」で説明する。キューブ自身の不変条件「`value_zero≠value_lod` ⇒ `n_censored>0 or n_not_detected>0`」は b04 が既に全セル検証しており（実測: 違反0、差のあるセル 244,264、`value_lod` NULL 3,201）、serving-diff 側は行単位の問い合わせで `n_censored>0` を再確認するだけでよい。
4. **alias→variable_id の束ね（`series_merge`）は「免除規則」ではなく「v1 側を束ねた新しい問い合わせ ID」で数える**（`*_by_variable`）。v1 アダプタが registry の alias→variable_id 対応と「代表統計量 (obs_stat ∈ {mean, point, NULL})」で v1 行を束ね、v2 は画面と同じ `lib/cube` 関数を呼ぶ。実測: 代表系列が同じ (地点, variable_id, grain, 年) に2つ以上同居することは**0件**（ピボットは安全）。束ねで変わるのは var_catalog 58→53行、`n_var` が変わる地点159件。**非代表の統計量（BOD/COD 75%値・大腸菌数 90%値・pH 最大/最小・最大沈下量）は variable_id に束ねると消える**ので、URL/UI に `stat` を持たせて選べるようにする（D4）。
5. **summary 2表は `aggregations/serving.yaml` → `scripts/b13_build_summary.py` → `v2.sqlite` 内の `summary_variable_catalog`/`summary_place_variable`**（キューブの再集計だけ。指紋機構・`check_v2_fresh`・`build:v2`・seed・Drizzle すべて既存の仕組みにそのまま乗る）。実測（Python sqlite3、コールドキャッシュ）: 指標カタログ 1,884ms・地点×指標 2,101ms・1地点の指標一覧 700ms——事前計算が要る。
6. **URL の指標キーは `variable`=variable_id、系列は `basis`（元データの粒度: `day`/`fiscal_year`/`year`）と `stat`（既定 `representative`）、表示粒度は `grain`（`year`=暦年/`fiscal_year`=年度/`month`/`day`）。** alias が来たらサーバ側 `page.tsx` で `redirect()`。AI（`links.ts`・`page-context.ts`・`tools.ts`）は同じ語彙に揃える（危険#8）。
7. **作業は5単位・4 worktree**（U1a パイプライン・U1b レジストリ／注記・U2 lib/cube＋Drizzle・U3 画面/API/AI・U4 serving-diff）。統合の最初に「検証が本番の経路を通っているか」のチェックリスト（§8.4）を通してから、重い検証（serving-diff zero/lod・b00）を各1回だけ回す。

## 決めてほしいこと（最小限）

| # | 論点 | 推奨 |
|---|---|---|
| D1 | 合成データの矛盾: (d) 診断用 v1互換キューブ（`b03 --include-synthetic --out v2_v1compat.sqlite`）で b02 と serving-diff を賄い、PR-5 で b02/b05 と一緒に捨てる | 採用。(a)〔b02 に実行時の再計算判定〕は wip の 860 行を b02 に組み込む使い捨て、(c)〔層2/3 の前倒し〕は CI の大改修で PR-5 の仕事を二重にする（§1） |
| D2 | `--pretend-synthetic-excluded`・`computeSyntheticPlaceIds`・`isSynthetic`・facet `dataset='synthetic'` の v2 側利用を PR-2 で撤去（実測で近似が不正確、§0-2） | 採用（`caveat_scope` の synthetic 行自体は PR-4 まで残す） |
| D3 | 注記キー: `censored`（zero の本文）は v1 の table scope に残し、v2 facet `dataset=measurements` には新キー `censoredLod` を置く。`unitUnknown` は新設 scope kind `variable`（PR-1 で予約済み）に、`variable_alias.csv` の `unit_id` 空の行から機械的に導いた variable_id を付ける | 採用（ADR-0009 追記の「key ごと分ける」に一致） |
| D4 | 非代表統計量（p75/p90/max/min、6 alias）を `stat` パラメータで選べる系列として残す（既定 `representative`＝mean/point/NULL を variable_id で混ぜる） | 採用（落とすと v1 で見えていた「BOD 75%値」等が画面から消える） |
| D5 | `/api/timeseries?mode=rain`（読み手なし・実測 grep 0件）と `sensorHourMonth` は PR-2 で削る | 採用 |
| D6 | home の①「境川 BOD 2020年以降」は `value_lod` で値が動く。本文の固定文「5 倍近い差」はオーナーが lod の数字を見て文言を確定する（設計では「自動生成しない、数字を見て直す」） | PR 本文に before/after の表を貼るので、そこで判断 |

---

## 1. 合成データの矛盾: 選択肢の比較と推奨

前提（実測）: 除外すると v1 派生10表に差分（wip commit の表: meas_daily 2,182/21、meas_month 1,330/672、… sensor_daily 4,855 行）。縮小サンプルは合成行を全量含み非合成行は間引かれているため、**静的なキー列挙**では全量とサンプルで宣言が食い違う。

| 案 | 中身 | CI が緑か | 使い捨ての作業量 | 検証の強さ | オーナー決定との整合 |
|---|---|---|---|---|---|
| (a) b02 に実行時判定 | wip の `build_synthetic_expected_diffs.py`（860行、v1 の集計式を Python で再実装し derived とビット一致を検算）を「YAML に書く」から「実行時に b02 の宣言へ合流」に変える。サンプル・全量とも実行時に導出するので合う | 緑（s05 の「適用した宣言=20」を「＋合成由来 N」に分ける改修が要る） | 大（860行の組み込み＋b02/s05/b00 の要約形式変更＋テスト。全部 PR-5 で消える） | 強い（ビット一致検算付き）。ただし v1 の式の**再実装**を信じる形 | ○ b03 で除く |
| (b) 別の層で除く（seed／問い合わせ層） | キューブは合成込み、D1 投入時や `lib/cube` で除く | 緑（b02 無変更） | 小 | **成立しない**: 合成は実在地点・実セルに混在（混在日セル21、月/年/平年値/ゾーン集計は全部値が動く）し、キューブの鍵に `source_id` が無いので投入時・問い合わせ時に識別できない | × D4「ファクトで除く」「配信時フィルタ却下」「鍵に source_id を足さない」の3つに反する |
| (c) 層2/3 を serving-diff へ前倒し | b02 から10表を外し、sample-gate に serving-diff（サンプルの v1 vs v2）を足す | 緑にできるが CI に tsx/serving-diff の配線、s05 の定数、b00 の要約を全部変える | 大（PR-5 でまた変える）。`sensor_daily`/`sensor_hour_month` は web に読み手が無く serving-diff の対象外なので**検証の穴が開く** | 中（10表の突合が失われる） | △ ADR-0029 の予定を早めるだけで矛盾はしないが、PR-2 が「値が動く」以外の大改修を抱える |
| **(d) 診断用 v1互換キューブ** | b03 に `--include-synthetic`（既定 off）を足し、b00/CI で `b03 --include-synthetic --out data/db/v2_v1compat.sqlite` → `b04 --out …v1compat…` → `b05 --cube-db …v1compat…` を**追加で**回す。`v2.sqlite`（配信用）は合成なし。serving-diff は `--v1compat-db` で第2接続を開き差分の差分で判定 | **緑。b02・宣言・s05・サンプルすべて無変更** | 小（b03 フラグ＋「`--include-synthetic` は既定の `--out` を拒む」ガード、b00 `PIPELINE_STEPS` を (script, args) に、CI 3行、serving-diff 第2接続と規則1本、`.gitignore` は `data/*` で済） | 強い: v1 との一致は**同じ本物のパイプラインコード**で保証され続ける。serving-diff の synthetic 判定は再実装なしの等式 | ○ b03 で除く（D4）・鍵は不変・本番の v2.sqlite に合成は無い。`variable_alias.csv` の合成5行は v1互換ビルドの alias 解決に要るので PR-5 まで残す |

**推奨 (d)。** 追加コスト: b00 の全量で b03 28s＋b04 46s ≒ +75s（docs 実測値）、sample-gate は数秒。安全策: `seed-d1-local.mjs` は `v2.sqlite` しか読まない（`SOURCES` 固定）が、さらに b03 は `--include-synthetic` 時に `pipeline_input_fingerprint` へ `synthetic_included=1` を書き、`check_v2_fresh.py` はその印があれば exit 10（古い扱い）にする——誤って v1compat を配信用にシードできない。

(d) の serving-diff 規則 `synthetic_excluded`（`classify.ts`）: `ctx.v2CompatByKey`（同じ問い合わせを v1compat 接続で流した行）を持ち、
- `row_only_in_v1` → 説明可 iff そのキーが v2compat に存在し v1 行と一致（宣言済み差分で説明される場合も可）。
- `value_diff` → 説明可 iff v2compat 行が存在し v1 と一致し、かつ v2compat ≠ v2（本物）。
- `row_only_in_v2` は説明不可（合成除外で行が増えることは無い）。
既存の `SYNTHETIC_EXCLUDED_VALUE_COLUMNS`（列の絞り）はそのまま。`--pretend-synthetic-excluded`・`db-sqlite.ts` の `excludePlaceIds`・`computeSyntheticPlaceIds`・`siteIdsForPlaceIds` は削除。変異 `synthetic_rule_off`（規則を無効化→unexplained>0）を足す。

**統合後 修正B（`classify.ts` の `classifyDeclaredWithSyntheticRemainder`）**: `declared`（`expected_diffs.yaml`）1つでは列を完全に覆えず、残りの列を `synthetic_excluded`（v1compat との差分の差分）で説明できる場合の組み合わせ判定。実測で `var_catalog`/`浮遊物質量 SS` 等、宣言済みバグ（below_lod 行の欠落）と合成データ除外の両方が同じ診断に重なるケースがあり、`findDeclared`（列を宣言が完全に覆う前提）・`classifySyntheticExcludedV1Compat`（全列で v1==compat を要求）のどちらか単体では説明できなかったため追加した。**これは ADR-0029 が言う「移行期間限定」の serving-diff 自身にすら重ねた一時的な特例であり、PR-5 で serving-diff・v1 比較が丸ごと消えるときに一緒に消える。** 新たな「宣言も規則も単体では説明できない重なり」が今後見つかっても、この関数に特例をもう1段積まない——`classify.ts` の判定優先順位（declared → rain_div10 → day_split → synthetic_excluded → 本関数 → lod_imputation → …）がこれ以上分岐すると「どの組み合わせがどの列を説明したか」を人が追えなくなる。その場合は `expected_diffs.yaml` の宣言粒度（列の絞り方）か `synthetic_excluded` 自体の判定式を見直す。

## 2. 対応表: v1 の呼び出し → `lib/cube`

方針: **画面・API・AI・serving-diff の v2 アダプタは同じ `lib/cube` の公開関数を呼ぶ。** PR-1 のアダプタが持っていた変換のうち画面にも要るもの（年セルのピボット、系列の代表化、v1 `kind`⇔grain/input_grain、単位ラベル）は `lib/cube` に移す。アダプタ固有で残すのは「v1 の列名への付け替え」と「alias 単位への合流（v1 比較専用）」だけ。

### 2.1 `lib/cube` に足す公開関数（U2）

| 関数 | 中身 | 出自 |
|---|---|---|
| `series.representativeSeries(variableId, dataset='measurements', stat: 'representative' \| ObsStat)` | `seriesForVariable` の薄い包み。`representative`＝obsStat ∈ {mean, point, NULL}、それ以外は指定 obsStat の系列だけ | 決定8/9。非代表統計量（D4）のため `stat` を受ける |
| `series.basisOf(series[])` → `{ basis: 'day'\|'fiscal_year'\|'year', grains: Grain[] }` | value_grain から「元データ」を決める。`day` → 表示 grain {year(暦年, inputGrain day), month, day}、`fiscal_year` → {fiscal_year}、`year` → {year(inputGrain 'same')} | v1 `kind` の後継（危険#8） |
| `observation.yearSeries(db, {variableId, stat, basis, scope, period?, imputation, limit?})` | `queryCells(grain=[year\|fiscal_year], stats mean/min/max)`＋**ピボット**（`adapters-v2.ts` の `pivotYearCells` を移設）。戻り `YearPoint{placeId, siteId, grain, periodStart, year(labelYear), n, nCensored, unitId, value/valueZero/valueLod{mean,min,max}}` | 画面・AI・API・serving-diff が共有 |
| `observation.monthSeries` / `daySeries` | `queryCells` の薄い包み（basis=day のみ許可、それ以外は例外） | 同上 |
| `catalog.variableCatalog(db, {dataset, source: 'summary'})` | `summary_variable_catalog` を読み、**variable_id 単位**に束ねた行（`n, nPlaces(=distinct place の和ではなく summary の place 集合から数える→§4)、yFrom, yTo, nByBasis{day,fiscal_year,year}, nCensored, stats[]（利用可能な obs_stat）, unitId`）を返す。`live` は残す（summary の正しさを比べる統合テスト用） | `/timeseries` page・`list_catalog`・`/api/timeseries` |
| `catalog.siteVariables(db, placeId, {source:'summary'})` | `summary_place_variable` から、variable_id×basis×stat 単位（avg は lod） | `/sites/[id]`・`get_sites(siteId)` |
| `catalog.sites(db, {source:'summary'})` / `sitesInWaterBody` / `waterBodies` | ロールアップを `summary_place_variable` から。**`water_system_name` を追加**（`sites.watershed` → `place_source_ref(source_id='watershed_meta.watershed_id')` → `place.name_ja`。実測で 377 流域すべて解決可） | `/sites`・`/api/geo/sites`・`get_sites`・`list_catalog(waters)` |
| `observation.rainDaily(db, {from,to})` / `rainMonthlyClim(db)` | `weather.precipitation` の hour→day `sum` セル（`series = seriesForAlias('sensor_timeseries','RAIN')` を `representativeSeries` で置換）。`/10` しない | `/api/timeseries mode=season` |
| `caveats.facetsForSeries(series, scope)` | synthetic push を撤去、`{kind:'variable', ref: variableId}` を各系列で push（`unitUnknown` 用）。`theme` は `variable` 表から解決する `lib/cube/series.ts` 側のヘルパ `withTheme()` を足す | §6 |
| `envelope.buildEnvelope` | `imputation:'both'` のとき `columns` に `value_zero`/`value_lod` を単位付きで両方、`coverage.imputation='both'`。`excluded.reasons` の `synthetic_included` を撤去 | AI ツール（決定3） |
| `unit.unitLabel(unitId)` | `unitSymbol(unitId) ?? null`。NULL は「単位不明」を呼び出し側が注記で表す（値は変えない） | 画面・AI |

### 2.2 画面・API・AI ごとの対応

| 呼び出し元 | v1（`queries.ts`） | v2（`lib/cube`） | 値が動く要因 |
|---|---|---|---|
| `/timeseries` page.tsx | `listWaterBodies`, `variableCatalog` | `catalog.waterBodies({dataset})`, `catalog.variableCatalog({dataset, source:'summary'})`；`searchParams.variable` が alias なら `resolveVariableInfo(alias).variableId` へ `redirect()` | series_merge、lod（catalog の avg 無し→n/期間のみ） |
| `/api/timeseries mode=waters` | `waterBodiesForVariable(alias)` | `catalog.waterBodies({series: representativeSeries(v, stat)})` | series_merge |
| `mode=water` | `sitesInWaterBody`, `yearSeries/monthSeries/daySeries` | `catalog.sitesInWaterBody`, `observation.yearSeries/monthSeries/daySeries(scope water, imputation lod)`；応答に `grain`・`basis`・`stat`・`unit`・`caveats: string[]` を含める | lod、series_merge、grain 明示 |
| `mode=site`（SiteDetail） | 同上 ×3 | 同上（scope site） | 同上 |
| `mode=zone` | `zoneSeries(alias, kind)` | `summarize(spec{series, scope all_sites, grain by basis, inputGrain}, 'zone')` | lod、series_merge |
| `mode=season` | `climatology`, `zoneClimatology`, `rainMonthlyClim` | `summarize(…,'month_of_year')`, `summarize(…,'zone_month_of_year')`, `observation.rainMonthlyClim` | lod、series_merge、rain `/10` 撤去・日割り退役 |
| `mode=rain` | `rainDaily`, `rainTopDays` | **削除**（読み手なし、D5） | — |
| `/sites` page, `/api/geo/sites` | `listSites` | `catalog.sites({source:'summary'})`（`nVariables` を `n_var` に） | series_merge（n_var 159地点） |
| `/sites/[id]` | `getSite`, `siteVariables` | `catalog.sites` の1件版 `catalog.site(db, siteId)`（新設、同じ SQL に `WHERE`）＋ `catalog.siteVariables({source:'summary'})` | lod（avg）、series_merge、basis/stat 表示 |
| home | `longitudinalHighlight` | `summarize(spec{series: representativeSeries(water.bod), scope water '境川（１）', grain 'year', inputGrain 'day', period from 2020-01-01, imputation 'lod'}, 'place')`（`sites` の name/elevation/zone は `catalog.sitesInWaterBody` で付ける） | lod（D6） |
| AI `list_catalog(variables)` | `variableCatalog` | `catalog.variableCatalog({source:'summary'})`；行キーは variableId、`registry` 辞書はそのまま | series_merge |
| `list_catalog(waters, variable)` | `waterBodiesForVariable` | `catalog.waterBodies({series})`（引数 `variableId`） | series_merge |
| `get_timeseries` | `resolveVariable`+`yearSeries`… | 入力 `{variableId, scope, grain: year\|fiscal_year\|month\|day, stat?, from?, to?}`；`basis` は grain から導く（`fiscal_year`→fiscal_year、`year`→day があれば day、無ければ year、`month/day`→day）。`imputation:'both'` で `buildEnvelope`。`data.points` に `value_lod`/`value_zero` 両方、`data.envelope`（coverage/provenance/columns）を同梱。`caveats` は `caveatKeysForFacets(facetsForSeries(series, scope))` | lod（両併記）、series_merge、grain 明示 |
| `get_seasonality` | `climatology`, `zoneClimatology` | `summarize` ×2（imputation は `lod` を主、`zero` を `overall_zero` として併記） | 同上 |
| `get_sites` | `listSites`/`getSite`+`siteVariables` | `catalog.sites`/`catalog.site`+`catalog.siteVariables({source:'summary'})` | series_merge |

`provenance.tables` は実際に読んだ表名（`observation_agg`、`summary_variable_catalog`、`sites`、`place_source_ref`）にする（`describe_schema`/`run_sql` 側の TABLE_META に summary 2表の説明を足す）。

## 3. 値が動く点の全列挙と serving-diff での数え方

| # | 動く点 | 影響範囲（実測・参考値） | serving-diff の数え方 |
|---|---|---|---|
| 1 | `zero`→`lod` | セル 244,264（day mean 12,492・month mean 12,416・year mean 3,786・fiscal_year mean 61,879 ほか min/max）、`value_lod` NULL 3,201（全 ND のセル） | `--imputation lod` 実行。v2 アダプタは `imputation` 引数（現状 `serving-diff.mts` が受けて捨てている）を `lib/cube` に渡し、同じ問い合わせを zero でも引く。新規則 `lod_imputation`: `value_diff` の数値列 ⊆ {avg,min,max,value} で、v2(zero) == v1（tolerance 内）かつ v2(lod) ≠ v2(zero)。行に `n_censored` 列があれば `>0` を要求（無い合算問い合わせは b04 の不変条件に依拠）。レポートに `lod_moved` 列（キー数）を出す |
| 2 | alias→variable_id（`series_merge`） | var_catalog 58→53、`n_var` が変わる地点159、meas_year で同 variable_id に複数 alias が並ぶ行 7,874/108,202（全部 p75/p90/max/min の非代表 alias） | 新問い合わせ ID を足す: `variable_catalog_by_variable`（key variable_id）・`site_variables_by_variable`（key variable_id,basis,stat）・`year_series_site_by_variable`/`month_…`/`day_…`（params variable_id×site_id×basis）・`zone_series_by_variable`・`climatology_by_variable`・`zone_climatology_by_variable`・`sites_list`（n_var→variable 数）・`water_bodies_for_variable_by_variable`。**v1 側**は alias 行を registry で束ねる（n は和、n_sites は `site_var` の (site,alias) から distinct、avg は Σ(avg·n)/Σn、min/max は min/max、zone/clim の avg は行数重み）——`series_merge` は規則ではなく「束ねた v1 行数」の情報列。tolerance は avg 1e-9。既存の alias 単位の問い合わせは残す（PR-1 の比較単位固定） |
| 3 | 合成データの除外 | measurements 2,265行（pH 693・気温 693・水温 691・SS 95・DO 93、24地点）、sensor 19,420行（soil_moisture 7,768・water_temperature 11,652、`synthetic_sensor`）。水域: 津久井湖(4地点)・相模川中流(4)・相模湖(5)・道志川(2)・鳩川(2) の集計が動く | §1 の `synthetic_excluded`（v1compat 接続との差分の差分）。全問い合わせに `known` として付ける |
| 4 | 雨量 `/10` 撤去 | v1 `rain_daily` 3,654行（最大 366.5）→ キューブ day sum 4,190セル（2015-04-01〜2026-08-28、最大 3,615）。画面の季節図の降水量が10倍・単位ラベル無し | 既存 `rain_div10` 規則をそのまま（v1 vs v2）。画面側は `unitUnknown` 注記 |
| 5 | 日割りの退役（#32-1） | rain 549日（PR-1 実測） | 既存 `day_split` 規則のまま |
| 6 | 単位ラベル | D3 後の残り NULL: 流量関連 1 alias・sensor 9 alias（RAIN 含む）。実測（D3 前の registry）で年セルの unit NULL 43,217/117,245 | 既存 `unit_label_registry`。NULL→「単位不明」注記は画面側 |
| 7 | 年キーの意味 | 年セル: fiscal_year/fiscal_year 98,579・year/day 16,933・year/year 1,661（＋hour 57・instant 15） | v1 `kind` との対応（daily⇔(year, input day)、annual⇔(fiscal_year \| year, input same)）はアダプタ内の `v1-compat.ts` に閉じる（PR-1 どおり） |

**PR-2 の受け入れ表（2回＋1回）**:
1. `pnpm run serving:diff --imputation zero --v1compat-db data/db/v2_v1compat.sqlite`: 全問い合わせ（既存 17＋by_variable 9）で `unexplained=0`、rotten=0、`--mutate all`（`lod_instead_of_zero`/`drop_series`/`swap_kind`/`no_unit`/`month_off_by_one`/`include_watershed_cells`/`rain_no_div10_rule`/`day_split_rule_off`/`declared_rot`/**`synthetic_rule_off`**/**`merge_rule_off`**〔v1 側の束ねを止める〕）が全部 OK。
2. `… --imputation lod …`: `unexplained=0`、`lod_moved` 列を問い合わせごとに記録（これが「値が動いた」件数の記録）。`--mutate lod_rule_off` を追加。
3. `.venv/bin/python3 scripts/b00_run_full_gate.py`: 33表 一致25/宣言のみ8/不一致0/宣言20 のまま（v1compat 経由）。
レポート（`reports/serving_switch_diff.md`）は zero/lod 別ファイルにせず、ヘッダの imputation で区別し、両方を PR 本文に貼る（`--out reports/serving_switch_diff_lod.md` を推奨）。

## 4. summary 2表

### 4.1 `aggregations/serving.yaml`（リポジトリ直下、ADR-0011 の最初の宣言）
```yaml
version: 1
spec_version: serving-summary/v1          # 変換規則を変えたら上げる（scripts/migrate/common.py の SUMMARY_SPEC_VERSION と一致を検証）
summaries:
  summary_variable_catalog:
    source: observation_agg
    filter: { place_kind: site, grain: [year, fiscal_year], stat: mean }
    group_by: [variable_id, obs_stat, unit_id, value_grain, grain, input_grain]
    measures:
      n:              { fn: sum, col: n }
      n_places:       { fn: count_distinct, col: place_id }
      y_from:         { fn: min, expr: year_of_period_start }
      y_to:           { fn: max, expr: year_of_period_start }
      n_censored:     { fn: sum, col: n_censored }
      n_not_detected: { fn: sum, col: n_not_detected }
    key: [variable_id, obs_stat, unit_id, value_grain, grain, input_grain]
    indexes: [[variable_id]]
  summary_place_variable:
    source: observation_agg
    filter: { place_kind: site, grain: [year, fiscal_year], stat: mean }
    group_by: [place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain]
    measures:
      n: { fn: sum, col: n }
      y_from: { fn: min, expr: year_of_period_start }
      y_to:   { fn: max, expr: year_of_period_start }
      avg_zero: { fn: avg, col: value_zero }
      avg_lod:  { fn: avg, col: value_lod }
      n_censored: { fn: sum, col: n_censored }
      n_not_detected: { fn: sum, col: n_not_detected }
    key: [place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain]
    indexes: [[place_id], [variable_id]]
```
語彙は閉じる: `fn ∈ {sum, count_distinct, min, max, avg}`、`expr ∈ {year_of_period_start}`（`CAST(substr(period_start,1,4) AS INTEGER)`）、`filter` の列は次元キーのみ。**variable_id 単位への束ねや代表化は宣言に書かない**（それは問い合わせ層の仕事。summary は系列単位のまま持ち、`catalog.ts` が束ねる——`nPlaces` を alias/variable 単位に単純合算すると二重計上する PR-1 の知見どおり、束ねは `summary_place_variable` の place 集合から数える）。

### 4.2 `scripts/b13_build_summary.py`
- 入力 `--v2-db data/db/v2.sqlite`（読み書き。`observation_agg` は SELECT のみ）、`--yaml aggregations/serving.yaml`。`common.require_sqlite_version()`。
- `assert_stage_fingerprint_fresh(conn, "observation_agg", upstream_schemas={})`→戻り値を `inputs` に。各表を `common.staged_table(conn, name, create_sql, fingerprint_inputs={"observation_agg": fp}, fingerprint_spec_version=SUMMARY_SPEC_VERSION)` で作る（`built_from`/`spec_version` 列も持たせる）。`assert_dimension_key_unique`（`key`）。`create_indexes`。
- 機械検証: (1) YAML の語彙検証（未知の fn/expr/列で止まる）、(2) 保存則: 各 summary の `SUM(n)` が `filter` 付きキューブの `SUM(n)` と一致、(3) 無作為抽出（決定論的: `ORDER BY key LIMIT 50`）した群を生成 SQL と**独立の固定 SQL**（テストの `_REFERENCE_SQL`）で再計算し一致、(4) 行数>0。
- 指紋/鮮度: `scripts/migrate/common.py` に `SUMMARY_SPEC_VERSION="serving-summary/v1"` と `V2_SUMMARY_TABLES` を足し、`V2_CUBE_SPEC_VERSIONS` に2表を追加（`check_v2_cube_fresh` が spec_version を見る）。`V2_PIPELINE_STAGE_MODULES` に `b13_build_summary` を追加（コードの指紋に入る）。`aggregations/*.yaml` を `_v2_pipeline_code_fingerprint` の glob に追加（YAML を変えたら古い判定になる）。`b13` は `record_v2_input_fingerprint` を呼ばない（b03/b06/b09 が書いた値を上書きしない）。
- 配線: `web/package.json` `build:v2` の末尾に `scripts/run-python.sh scripts/b13_build_summary.py`；`b00.PIPELINE_STEPS` は `(script, args)` の組にして `… b07, b13, b08, …`（`test_build_v2_script_order.py` の `steps[-1]=="b07"` を b13 に、抽出関数を組対応に）；CI `sample-gate` の v2 構築ステップに b13 を追加；`b13` は `scripts/b1*.py` の glob で証明パスに自動的に入る。
- D1: `web/src/db/schema-cube.ts` に2表（列は b13 の CREATE と完全一致、索引を宣言）→ `pnpm run db:generate`（`0006_*.sql`）。`seed-d1-local.mjs` は owner map で自動的に v2 由来として投入し、`alias==="v2"` の列集合完全一致検査が効く。`export-d1-sql.mjs` 無変更。`cube-fixture.ts` は全マイグレーションを適用するので summary 行を手書きで足せる。

### 4.3 `catalog.ts` の切り替え
`CatalogSource` を実際の分岐にする（`{kind:'summary'}` 既定、`{kind:'live'}` はテスト用）。`summary` 版は `summary_variable_catalog`/`summary_place_variable` に対する `GROUP BY variable_id`（束ね）と JOIN のみ。統合テスト（実 DB がある手元）: `variableCatalog({source:'summary'})` と `{source:'live'}` の一致（PR-1 の `integration.test.ts` の流儀）。**画面と serving-diff の両方が `summary` で呼ぶ**（§8.4 のチェック項目）。

## 5. URL と年キー

- `/timeseries?variable=<variable_id>&grain=year|fiscal_year|month|day&basis=day|fiscal_year|year&stat=representative|p75|…&mode=&water=`。`variable` が `common:variable:` で始まらなければ `resolveVariableInfo(value,'measurements')` で解決し `page.tsx`（サーバ）から `redirect()`（`kind=daily`→`basis=day&grain=year`、`kind=annual`→`basis=fiscal_year&grain=fiscal_year` も同時に書き換え。解決できなければ既定の BOD へ）。
- 表示名: `variable.name_ja`（実測: measurements 53 variable のうち19件が NULL〔地盤沈下8件ほか〕）→ `generated-client.ts` に variable_id キーの `VARIABLE_LABEL: {short, note, higherIsWorse}` を新設（`registry-codegen.mjs` の `pickPrimaryAlias` で NULL を代表 alias に落とす）。alias キーの `VARIABLE_SHORT`/`VARIABLE_NOTE`/`HIGHER_IS_WORSE` は PR-5 まで残す。
- UI 語彙: 「粒度」=年（暦年）/年度/月/日、「元データ」=検体値（`day`）/年度集計値（`fiscal_year`）/暦年値（`year`、地盤沈下のみ）、「統計量」（非代表があるときだけ表示）。年度の x 軸ラベルは `2015年度` と明記（`labelYear` は年度の始まりの年）。
- `page-context.ts`: `/timeseries` の `kind` → `basis`、`grain` に `fiscal_year` を許容、`variable` は variableId（`describePageContext` は `VARIABLE_LABEL` で表示名）。`/sites/[id]` は変更なし。
- `links.ts`: `timeseriesUrl({variableId, scope, grain, basis, stat})`。`grain==='day'` と site スコープは従来どおり null。
- `tools.ts`: `get_timeseries.grain` に `fiscal_year` を追加し `kind` を撤去、`stat?` を追加。`describe` 文に「`fiscal_year` は日本の年度（4月始まり）、`year` は暦年（検体値から集計）」を書く。`prompt.ts` の `variableVocabNote` に grain/basis の説明を追加、「集計は derived 系テーブルを使う」節を「意図ツール（キューブ・summary）を使う」に書き換え（run_sql の few-shot は PR-4/5 で掃除）。
- `SeriesChartCard.tsx`: `TimeseriesData.grain` に `fiscal_year`、`kind`→`basis`、y は `value_lod`（無ければ `avg_lod`）、x は `labelYear(period_start)`。

## 6. 注記

- `registry/caveat.yaml`: `censoredLod`（新設。本文例:「全体の約24%は定量下限未満（原表記が「<0.5」など）。この画面の値は定量下限未満を**定量下限値とみなして**集計している（上限側の見積もり）。不検出（ND）は平均に含めない。折れ線では中抜きの点で示す」）、`unitUnknown`（新設。「この項目は原本に単位の記載が無く、レジストリでも確定できていない。値は原本の数値のまま（換算していない）。相模原市の1時間値 RAIN は 0.1mm 刻みの可能性があるが推測で換算しない」）。`censored` の本文は不変（v1 table scope・run_sql 用）。
- `scripts/registry/build_caveat.py`: facet `dataset=measurements` の `MEASURE_CAVEATS` を `[measuredOn, censoredLod, duplicates]` に（table 側は `censored` のまま）。`unitUnknown` は `add_facet_group("variable", refs, ["unitUnknown"])`、refs は `registry/variable_alias.csv` の `unit_id` 空行の `variable_id`（機械導出、ハードコードしない。実測: 流量関連の1系列＋sensor の9行〔RAIN 含む〕）。`registry/README.md` の表を更新。
- `web/scripts/build-registry-ts.mjs`: 変更不要（`variable` kind は予約済み）。`generated-client.ts` 再生成（CI registry ジョブが一致を検査）。`CaveatKey` に2キーが増えるので `prompt.ts` の `CAVEAT_KEY_ORDER` に追加（`satisfies` で強制される）。
- `lib/cube/caveats.ts`: `facetsForSeries` から synthetic push を削除し `variable` facet を追加。`caveats.test.ts` の橋渡しテストは「measurements 系の表では facet 側が `censoredLod`、table 側が `censored`」を期待値に明示（意図した乖離をテストが記録する）。
- 画面: `caveatBody("censored")` → `caveatBody("censoredLod")`（TimeseriesExplorer・SiteDetail・home の一覧）、季節図の降水量の固定注記（"0.1mm 単位とみなして mm に換算"）を `caveatBody("unitUnknown")` に、ColumnChart の `unit="mm"` を `unit={null}`。API/AI は `caveatKeysForFacets(facetsForSeries(series, scope))` をそのまま返す（AI は `CAVEAT_TEXT` が `caveat_scope` の全キーから作られるので自動的に本文を持つ）。

## 7. D1 と本番

- マイグレーション `0006`（summary 2表＋索引）。`pnpm run db:setup` でシード（`_seed_state` の指紋は v2.sqlite の size/mtime なので b13 の追記で入れ直しが走る）。
- 本番には出さない（main を deploy しない前提は変わらず）。`export-d1-sql.mjs`・DEPLOYMENT.md は触らない。`v2_v1compat.sqlite` は `data/*` の `.gitignore` に含まれる。

## 8. 作業の分け方

### 8.1 並行単位（worktree、ファイル衝突なし）

| 単位 | 触るファイル | 依存 |
|---|---|---|
| **U1a パイプライン** | `scripts/b03_build_observation.py`（`--include-synthetic`＋ガード＋印）、`scripts/b06_build_occurrence.py`（wip 流用）、`scripts/b13_build_summary.py`（新）、`aggregations/serving.yaml`（新）、`scripts/migrate/common.py`（SUMMARY_SPEC_VERSION 等）、`scripts/check_v2_fresh.py`（印の拒否）、`scripts/b00_run_full_gate.py`（steps with args＋v1compat 段）、`.github/workflows/ci.yml`（sample-gate 3行＋b13）、`web/package.json`（build:v2）、`scripts/tests/test_b03_*`, `test_b13_*`(新), `test_build_v2_script_order.py`, `test_check_v2_fresh.py` | なし |
| **U1b レジストリ／注記／語彙** | `registry/caveat.yaml`, `registry/README.md`, `scripts/registry/build_caveat.py`, `web/scripts/lib/registry-codegen.mjs`（`VARIABLE_LABEL`）, `web/scripts/build-registry-ts.mjs`, `web/src/lib/registry/generated-client.ts`・`generated.ts`（再生成）, `web/src/lib/ai/prompt.ts` の `CAVEAT_KEY_ORDER`, `web/src/lib/registry/*.test.ts` | なし |
| **U2 lib/cube＋Drizzle** | `web/src/lib/cube/**`（`series.ts`/`observation.ts`/`catalog.ts`/`caveats.ts`/`envelope.ts`/`db-sqlite.ts`/`index.ts`/fixture/tests）、`web/src/db/schema-cube.ts`、`web/drizzle/migrations/0006*`＋`meta` | U1a の YAML 列名（先に §4.1 で合意済み） |
| **U3 画面/API/AI** | `web/src/app/{timeseries,sites,page.tsx}`, `web/src/app/api/timeseries/route.ts`, `api/geo/sites/route.ts`, `web/src/components/{timeseries,sites,HomeHighlights,assistant/tool-ui}/**`, `web/src/lib/ai/{tools,links,page-context}.ts`(+tests), `web/src/lib/table-meta.ts`（summary の説明） | U2 の `index.ts` シグネチャ（U2 が最初のコミットで型だけ出す） |
| **U4 serving-diff** | `web/scripts/serving-diff.mts`, `web/scripts/lib/serving/*`（`adapters-v1/v2`, `classify`, `mutations`, `report`, 新 `v1-compat.ts`/`merge-v1.ts`）, `web/serving_queries.yaml`, `reports/serving_switch_diff*.md/json` | U2 の公開関数（`representativeSeries`/`yearSeries`/summary source） |

統合順: U1a → U1b（どちらも先行可・独立） → `cd web && pnpm run build:v2` を**1回**（registry・v2・summary が新鮮に）＋ `b03 --include-synthetic --out data/db/v2_v1compat.sqlite && b04 --out … && b05 --cube-db …` を1回 → U2 → U3 ‖ U4 → §8.4 のチェック → 重い検証。

### 8.2 各単位の「速い検証」
- U1a: `pytest scripts/tests/test_b03_build_observation.py scripts/tests/test_b13_build_summary.py scripts/tests/test_check_v2_fresh.py scripts/tests/test_build_v2_script_order.py`（フィクスチャのみ、秒）。b13 の実データ実行は1回（`--v2-db` に worktree の実ファイル）で行数と保存則の出力を目視。
- U1b: `python3 scripts/r01_build_registry.py --files-only && node web/scripts/build-registry-ts.mjs && git diff --stat` ＋ `pnpm vitest run src/lib/registry src/lib/ai/prompt.test.ts src/lib/ai/caveats.test.ts`。
- U2: `pnpm vitest run src/lib/cube`（フィクスチャ）。実 DB があれば `integration.test.ts` の summary=live 1件だけ。
- U3: `pnpm exec tsc --noEmit` ＋ `pnpm vitest run src/lib/ai` ＋ `pnpm run dev` で `/timeseries?variable=生物化学的酸素要求量 BOD&kind=annual`（リダイレクト確認）・`/sites/[id]`・home を目視。
- U4: `pnpm vitest run scripts/lib/serving` ＋ `pnpm run serving:diff --only year_series_site_by_variable,climatology --v1compat-db … --imputation lod`（数十秒）。

### 8.3 PR 直前に1回だけ回す重い検証
1. `pnpm run serving:diff --imputation zero --v1compat-db data/db/v2_v1compat.sqlite --mutate all`（PR-1 実測 573s の約2倍を見込む）。
2. 同 `--imputation lod --out reports/serving_switch_diff_lod.md`。
3. `.venv/bin/python3 scripts/b00_run_full_gate.py`（＋75s）→ `reports/full_gate_proof.json` をコミット。
4. `pnpm run db:reset`（summary を含むシード）→ 画面4本と AI ツール4本のスモーク。
5. /code-review と /simplify を同時に → 指摘をまとめて1回で直す → 1〜3 を再実行。

### 8.4 統合の最初のチェックポイント「検証が本番の経路を通っているか」
自動1件＋レビュー6項目。
- 自動: `web/scripts/lib/serving/adapters-v2.test.ts` に「`adapters-v2.ts` のソースに `observation_agg`/`summary_` の文字列が無い（生 SQL を持たない）」テストを足す。
- レビュー: (1) `adapters-v2.ts` の全 `case` が `@/lib/cube` の公開関数（`representativeSeries`/`yearSeries`/`summarize`/`catalog.*({source:'summary'})`）だけを呼び、画面・API・AI の該当箇所と**同じ関数・同じオプション**（imputation は引数、`source:'summary'`、`stat:'representative'`）で呼んでいる対応表を PR 本文に貼る。(2) `catalog.variableCatalog` の既定が `summary` で、`/timeseries` page と `list_catalog` と `variable_catalog_by_variable` が3つとも既定で呼んでいる。(3) 年セルのピボットが `lib/cube` に1つだけあり、`adapters-v2.ts`・`/api/timeseries`・`tools.ts` に複製が無い（grep `stat === "mean"`）。(4) v1 側の束ね（`merge-v1.ts`）が `lib/cube` を import していない（v1 の正解を v2 で作らない）。(5) `check_v2_fresh.py` が `v2_v1compat.sqlite` を exit 10 にする（手で1回）。(6) `seed-d1-local.mjs` の `SOURCES` に v1compat が無い。

## 9. 危険・未決事項・オーナーに聞くこと

1. **手元の生成物が古い**（`check_v2_fresh.py` exit 10、`registry.sqlite` は 9/24 で PR-1 の facet 行・D3 の unit_id 埋めが無い）。統合前に `build:v2` を1回。本文の数字は参考値。
2. **`isSynthetic`/facet `synthetic` の誤爆**（§0-2）: 撤去しないと切り替えた瞬間、実データの pH/水温/気温/SS/DO に「合成データ」の警告が付く。`envelope.test.ts`・`caveats.test.ts`・`series.test.ts` の該当ケースを消す。
3. **非代表統計量の扱い（D4）**: `stat=representative` 既定で `land.max_subsidence`（唯一の alias が `max`）が空にならないよう、`representativeSeries` は代表が無い variable では全系列にフォールバックする（テストで固定）。
4. **home の固定文（D6）**、`/sites/[id]` の「平均 …」が lod になる旨の注記。
5. **`v2_v1compat.sqlite` の誤用**: 印＋`check_v2_fresh` の拒否＋`SOURCES` 固定で塞ぐ。PR-5 で `--include-synthetic` ごと消す（PR-5 の削除リストに追記）。
6. **serving-diff の実行時間**が約2倍（v2 を2回引く）。`--only` で回し、全量は PR 直前の2回だけ。
7. **`variable_alias.csv` の合成5行**は v1compat の alias 解決に要るので PR-5 まで残す（`note` に「PR-5 で削除」）。
8. `/api/geo/sites`（map）は `catalog.sites()` に載せ替わるが `/map` 自体は PR-3b——`water_system_name` の付与で map のポップアップは変わらない。
9. ADR 追記: ADR-0009（censoredLod の本文と「最初の消費者」）・ADR-0024（日割り退役）・ADR-0030（D4 に v1compat の但し書き、`isSynthetic` 規約の撤回）・ADR-0011（状態を「実装済み（summary 2表）」に更新）・ADR-0029（差分の差分の規則、by_variable 問い合わせ）。`docs/plans/V2_SERVING.md` PR-2 節の状態と、この設計を `docs/plans/V2_SERVING_PR2.md` に置く（U1b が担当）。

## 付録: 実測（2026-09-26、読み取り専用。worktree v2〔12列キー・指紋なし〕＋main registry〔9/24〕＋ryuiki/derived）
- 合成: measurements 2,265行（pH 693・気温 693・水温 691・SS 95・DO 93）/24地点（env_kousui 18地点は実データ併存、moni1000 6地点は合成のみ）、sensor 19,420行（synthetic_sensor、2〜3地点）、`sites.is_synthetic` 全0、`observation.is_synthetic=1` 21,685行/24 place（18 place は混在）、(site,variable) 80組中54組に実データ、日セル 純合成 7,037・混在 21、合成 tuple 5件は全て実出典と共有。
- lod: `value_zero≠value_lod` 244,264（n_censored>0 は 243,686、非検閲で差あり 0、`value_lod` NULL 3,201、検閲ありでも一致 2,623）。
- 束ね: 58 alias→53 variable_id、複数 alias は bod/cod/ecoli(2)・ph(3)、非代表 stat 6 alias、(site,variable_id,kind) 複数 alias 567組/159地点、代表系列の同居 0。
- 粒度: alias day 26・fiscal_year 45・year 8（地盤沈下）、年セル fiscal_year 98,579・year/day 16,933・year/year 1,661。
- 単位: 年セル unit NULL 43,217/117,245（D3 前）、RAIN alias unit NULL・variable は mm、RAIN day sum 4,190 セル（最大 3,615 vs v1 366.5）。
- 性能: 指標カタログ 1,884ms・地点×指標 2,101ms・1地点 700ms（Python sqlite3、コールド）。b03 28s・b04 46s・b05 44s（docs）、serving-diff 全量 573s（PR-1）。
- `variable.name_ja` NULL: measurements 53 variable 中 19。

### Critical Files for Implementation
- /home/yu23ki14/cfj/ryuiki-demo/web/src/lib/cube/catalog.ts（summary 切り替え・variable_id 束ね・`water_system_name`）
- /home/yu23ki14/cfj/ryuiki-demo/web/scripts/lib/serving/adapters-v2.ts（ピボット等を `lib/cube` へ移し、`imputation` を配線、pretend 系を撤去）
- /home/yu23ki14/cfj/ryuiki-demo/scripts/b03_build_observation.py（`is_synthetic` 除外＋`--include-synthetic` 診断フラグ）
- /home/yu23ki14/cfj/ryuiki-demo/web/scripts/lib/serving/classify.ts（`synthetic_excluded` の差分の差分・`lod_imputation`）
- /home/yu23ki14/cfj/ryuiki-demo/web/src/lib/ai/tools.ts（4ツールの切り替え・封筒・grain/basis 語彙）
- /home/yu23ki14/cfj/ryuiki-demo/scripts/registry/build_caveat.py（`censoredLod`/`unitUnknown` の facet）
- /home/yu23ki14/cfj/ryuiki-demo/scripts/b04_build_cube.py（b13 が倣う `staged_table`/指紋/索引の型）

---
## 設計責任者の決定（2026-09-26）
- D1〜D5 採用。D6（home の固定文）は PR 本文に before/after を貼り、オーナーが文言を決める（実装側は数字を自動生成せず、固定文は現状のまま触らない）。
- 設計書はリポジトリに `docs/plans/V2_SERVING_PR2.md` としてコミットする（U1b が担当）。
- 並行: U1a・U1b・U2 を先に並行、U2 完了後に統合して U3・U4 を並行。
- 全担当共通: スキル（/simplify・/code-review 等）やサブエージェントを起動しない。重い検証（serving-diff 全量・b00）は各担当では回さない（統合後に1回だけ）。速い検証は §8.2。
