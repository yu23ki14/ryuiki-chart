# Phase B 縦に薄い1本 — `measurements`/`sensor_timeseries` → `observation` → キューブ → v1形

対象: ADR-0016 の Phase B / 状態: **実データで一度緑になった（部分ゲート。33テーブル中11テーブル）**
作成: 2026-09-08 / 更新: 2026-09-25（Issue #37: 段階間の指紋・staged_table原子性の確認・
b05検証関数群の分割、/code-review 指摘2件の対応〔系譜の再帰化・b05のobservation
直接読み取りの検証漏れと指紋記録の原子性の根本対応〕、/simplify（4観点）反映
〔読み取りの機械監査Tier 1・b08の重複排除・b11の--cube-db検証・指紋計算の高速化ほか〕） /
関連: ADR-0007, 0008, 0009, 0010, 0011, 0016, 0021, 0022, 0023, 0024

このドキュメントは `docs/plans/PHASE_B_RECONCILIATION.md`（突合ゲートの仕組み）と対になる、
**縦に薄い1本の設計と実測**の記録。`b03_build_observation.py` / `b04_build_cube.py` /
`b05_project_v1.py` と `scripts/migrate/*` がここで説明する対象そのもの
（`PHASE_B_RECONCILIATION.md` はゲートの仕組みだけを説明し、この2つを実装するのは範囲外と
明記していた。本ドキュメントがその続き）。

**2026-09-15 追記**: `measurements` 由来の残り3テーブル（`meas_clim`/`site_var`/
`var_catalog`）を `b05_project_v1.py` の射影に追加し、対象を3テーブルから6テーブルに
広げた（`phase-b/meas-remainder`）。新しいファクト源は足していない
（`b03`/`b04` は無変更）。この3テーブルは ADR-0011 のキューブのセルにはせず、
射影（`b05`）でのみ計算する（§5「決定事項」D10・理由は §「なぜキューブのセルに
しないか」参照）。§6 に `meas_clim` が統計量の異なる系列を混ぜて平年値を作っている
件の実測を追記した。

続けて同日、`sensor_timeseries`（717,839行）を入力に追加し、対象を6テーブルから
**9テーブル**（`sensor_daily`/`rain_daily`/`sensor_hour_month`）に広げた
（`phase-b/sensor-slice`。新設 [ADR-0023](../adr/0023-unit-canonicalization.md)・
[ADR-0024](../adr/0024-local-time-and-time-labels.md)）。この縦線は `b03`/`b04` も
変更している（`observation` は出典ごとに1トランザクションでストリーム挿入する形に
書き換え、キューブは毎時・瞬時の観測を日次セルへ積み上げ、月次・年次の出典配布セルを
持つようになった）。設計・実測・決定（T1〜T6）は §9、キューブに織り込んだ意図的な
変更は §10 を参照。

**2026-09-22 追記**: `zone_year`/`zone_clim` を `b05_project_v1.py` の射影に追加し、
対象を9テーブルから**11テーブル**に広げた（`phase-b/zone-slice`）。新しいファクト源は
足していない（`b03`/`b04` は無変更。`meas_year`/`meas_month` という既に実体化済みの
v1形の一時テーブルから射影するだけ）。この2テーブルも ADR-0011 のキューブのセルには
せず、射影（`b05`）でのみ計算する（D10 の3例目・D11）。地点→ゾーンの対応は
ADR-0022 決定2で新設された `place_relation` から初めて引く。設計・実測・決定は §11 を参照。

## 1. なぜ縦に薄い1本なのか

ADR-0011 の対象は33テーブル。これを一度に全部揃えようとすると、v2 側の設計・実装が全部そろうまで
`scripts/b02_derived_compare.py` のゲートが一度も緑にならない。そこで最初の縦線として
`measurements`（323,164行）→ `observation` → キューブ → `meas_daily`/`meas_month`/`meas_year`
の3テーブルだけを先に通す。検閲値（定量下限未満）の0埋めの再現・日付書式の混在・`place` 解決の
失敗のような、このゲートが本来検出すべき食い違いは、どれもこの3テーブルの縦の流れの中で
一通り出る（`PHASE_B_RECONCILIATION.md` §4「`--tables` で対象を絞る」に同じ理由が書いてある）。

## 2. 着手判定（申し送り #5 / #4 / #2 はこの縦線を塞がないこと。根拠は実測）

`docs/plans/PHASE_B_INTAKE.md` の申し送り一覧のうち #5・#4・#2 が、この縦線に着手する前に
片付けないといけない宿題かどうかを実測で判定した。

- **#5（原表記スケール単位）**: `unit.ucum IS NULL` の12単位を実測すると、`variable_alias` での
  使用先は次のとおり（`data/db/registry.sqlite` を読み取り専用で確認）。

  | dataset | unit_id | 用途 |
  |---|---|---|
  | `measurements` | `common:unit:count`（可算） | 地盤沈下の水準点数など |
  | `measurements` | `common:unit:t_p_m` | 東京湾平均海面基準の標高（**スケールではなく基準面**） |
  | `sensor_timeseries` | `0_1ppm`/`0_01ppmc`/`0_1degc`/`0_1percent`/`0_1mm`/`0_1m_per_s`/`tenths`（**×10のスケール表記7件**） | 全部 `sensor_timeseries` 専用 |
  | `sensor_timeseries` | `days`（可算） | 現象のあった日数 |

  「×10ずれ」が起きうる単位は `dataset='sensor_timeseries'` のエイリアスにしか現れない。
  `dataset='measurements'` 側の `ucum=null` はスケールではない `t_p_m`（基準面）と `count`
  （可算）だけ。→ この縦線には原理的に×10ずれが起きず、**#5 が塞ぐのは `sensor_daily`/
  `sensor_hour_month` の縦線**（`measurements` ではなく `sensor_timeseries` を入力にする方）。
- **#4（`place.region_id` の意味）**: この縦線はロールアップしない。`b03`/`b04`/`b05` のどこにも
  `place_relation` への参照が無い（`meas_daily`/`meas_month`/`meas_year` は地点別のまま）。
  `place_relation` を要するのは `zone_year`/`zone_clim`/`org_watershed_*` 系で、この縦線には
  含まれない。→ **#4 が塞ぐのはロールアップ系の縦線**。（**2026-09-22 追記**: #4 は
  ADR-0022 で決着済み。`phase-b/zone-slice` で `zone_year`/`zone_clim` をこの縦線に加えた結果、
  `b05` だけが `place_relation` を読むようになったが、`meas_daily`/`meas_month`/`meas_year` 本体
  および `b03`/`b04` は今も地点別のまま・無関与。ロールアップと呼べるのは `zone_year`/`zone_clim`
  の2テーブルの射影だけで、しかもキューブのセルではなく v1形からの単純な非加重平均（§11）。
  ADR-0011 の `roll_up_to`（キューブのロールアップセル）はまだ作っていない）。
- **#2（`caveat_scope.scope_kind`）**: この縦線は caveat を一切消費しない（`b03`/`b04`/`b05` に
  caveat への参照が無い）。→ **#2 が塞ぐのは応答に caveat を同梱する経路**。

## 3. 構成

| ファイル | 役割 |
|---|---|
| `scripts/b03_build_observation.py` | `data/db/ryuiki.sqlite` の `measurements`・`sensor_timeseries`（読み取り専用、出典ごとに1トランザクションでストリーム挿入）を `data/db/v2.sqlite` の `observation`（ADR-0007）**テーブルだけ**を作り直して書く（`fresh_sqlite` から `migrate.common.staged_table`——検証が全部通ってから本番名に差し替える——に変更。§7「既知の負債」参照）。alias/place 解決、`value_grain`/`period_grain` の展開（センサーは ADR-0024 の時刻帯なしローカル時刻・hour_ending 変換を含む）、検閲分類（`measurements` のみ）を行い、`reports/phase_b_fact_slice.md` に出典ごとの節で要約を書く |
| `scripts/b04_build_cube.py` | `observation` から `observation_agg`（ADR-0011 のキューブ、ADR-0021 で拡張したキー）を作る。`imputation='zero'` の系列だけ。センサー分の拡張（毎時・瞬時の日次積み上げ、月次・年次の出典配布セル）は §9 T4 |
| `scripts/b05_project_v1.py` | `observation_agg` を v1 の派生テーブル形（`meas_daily`/`meas_month`/`meas_year`/`meas_clim`/`site_var`/`var_catalog`/`sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/`zone_clim`）に射影し、`data/db/v1_projection.sqlite` に書く。`meas_clim`/`site_var`/`var_catalog` はキューブのセルを直接使わず、既存の `_MEAS_DAILY_SQL`/`_MEAS_YEAR_SQL` を実体化した一時テーブルを再利用する（D10）。`sensor_daily`/`rain_daily`/`sensor_hour_month` の毎時分は同じ理由でキューブを経由せず L2（`observation`）から直接集計する（§9 T5）。`zone_year`/`zone_clim` も同じ理由で `meas_year`/`meas_month`（実体化済み一時テーブル）から射影し、地点→ゾーンは `place_relation` から引く（§11・D11）。`verify_hourly_daily_rollup`（§9 T6）による機械検証もここで行う |
| `scripts/migrate/censoring.py` | `value_raw` → `(censoring, censoring_limit)` の5分岐（ADR-0009。`measurements` のみ。センサーに検閲の概念は無い） |
| `scripts/migrate/period.py` | `measured_on`/`phenomenon_time` → `(period_grain, period_start, period_end)`。`period_exceptions.yaml` の宣言（4桁の食い違い）と `time_label_conventions.yaml` の宣言（25桁・`value_grain='hour'` の時刻ラベルの意味。ADR-0024 決定2）を例外的に許す |
| `scripts/migrate/period_exceptions.yaml` | `value_grain != period_grain` を許す宣言表（`atsugi_river_water_quality` の1件、3,840行） |
| `scripts/migrate/time_label_conventions.yaml` | `value_grain='hour'` の出典の時刻ラベルの意味（`convention`/`expected_row_count`/`evidence`）を宣言する（ADR-0024 決定2）。`sagamihara_taiki_hourly`・`soramame_hourly_kanagawa` の2件。CI が構造（必須キーの有無）を検証する |
| `scripts/migrate/common.py` | b03/b04/b05 共通の土台（`timed_step`/`fresh_sqlite`/`replace_table`/`attach_readonly`。読み取り専用オープンは `scripts/reconcile/common.open_readonly` を再利用） |
| `scripts/reconcile/expected_diffs.yaml` | 「v1 を再現できないが v1 側のバグだと確定しているもの」をキー単位で宣言する（`scripts/b02_derived_compare.py` が読む） |
| `scripts/b02_derived_compare.py --tables meas_daily,meas_month,meas_year,meas_clim,site_var,var_catalog,sensor_daily,sensor_hour_month,rain_daily,zone_year,zone_clim` | この11テーブルだけを対象にした部分ゲート |
| `scripts/tests/test_b03_*` / `test_b04_*` / `test_b05_*` / `test_migrate_*` | フィクスチャ sqlite だけで完結するテスト（原本を要さない） |

## 4. 実測した前提（すべて読み取り専用で確認済み）

| 事実 | 値 | 出典 |
|---|---|---|
| `measurements` 行数 | 323,164 | `reports/phase_b_fact_slice.md` |
| `observation` 行数（alias/place 解決率） | 323,164 / 323,164（全行解決） | 同上 |
| `length(measured_on)=10`（検体値。日付） | 217,710（`env_kousui_sample_kanagawa` 214,725 / `atsugi_river_water_quality` 720 / `source_id NULL` 2,265） | 実測（`data/db/ryuiki.sqlite`） |
| `length(measured_on)=4`（年度番号・暦年） | 105,454（`env_kousui_annual_kanagawa` 98,328 / `atsugi_river_water_quality` 3,840 / `kanagawa_jiban_chinka` 3,286） | 同上 |
| censoring 内訳 | `none` 246,370 / `below_lod` 75,701 / `not_detected` 1,067 / `above_lod` 26 / `unknown` 0 | `reports/phase_b_fact_slice.md` |
| `imputation='zero'` で0.0が入る行 | 76,768（`below_lod`+`not_detected`） | 同上 |
| `value_grain != period_grain` | 3,840行（すべて `atsugi_river_water_quality` の4桁日付行。宣言表の `expected_row_count` と一致） | 同上 |
| 日次グループサイズ（`site,variable,day`、value NOT NULL） | n=1: 70,046 / n=2: 60,816 / n=3: 8,668 | 実測 |
| 年次グループサイズ（`site,variable,year(4桁)`、value NOT NULL） | n=1: 98,295 / n=2: 1,625 / n=10: 3 / n=11: 4 / n=12: 313 | 実測 |
| `meas_year.kind` の内訳（v1・v2 とも一致） | `annual` 100,240 / `daily` 15,836（annual は daily の約6.3倍） | `data/db/derived.sqlite` と `data/db/v1_projection.sqlite` を実測、両者一致 |
| `value IS NULL` の内訳 | `ノニルフェノール`（`value_raw`='0.00006'等）69行 / `透明度`（`>`表記）26行 / `浮遊物質量 SS`（`未満`表記）12行 = 計107行 | 実測 |
| ベースライン行数 | `meas_daily` 139,530 / `meas_month` 127,491 / `meas_year` 116,076 / `meas_clim` 192 / `site_var` 8,140 / `var_catalog` 58 | `data/db/derived.sqlite` |
| 候補（v2射影）行数 | `meas_daily` 139,532 / `meas_month` 127,493 / `meas_year` 116,076 / `meas_clim` 192 / `site_var` 8,140 / `var_catalog` 58 | `data/db/v1_projection.sqlite`。行数は全テーブルでベースラインと一致（差は値だけ。宣言済み差分は§6参照） |
| dataset='measurements' で1 aliasに複数の `(variable_id, grain, stat, unit_id)` が対応する件数 | 12 alias（全58 alias中） | `data/db/registry.sqlite` の `variable_alias` を実測（2026-09-15） |
| うち `grain='day'` の系列を2つ以上持つ alias（`meas_clim` で実際に混ざる） | 5 alias（`pH`/`化学的酸素要求量 COD`/`浮遊物質量 SS`/`溶存酸素量 DO`/`生物化学的酸素要求量 BOD`） | 同上。詳細は §6 |
| `sensor_timeseries` 行数（alias/place 解決率） | 717,839 / 717,839（全行解決） | `reports/phase_b_fact_slice.md` |
| `observation` 総行数（`measurements`+`sensor_timeseries`） | 1,041,003（323,164 + 717,839） | 同上 |
| `observation_agg` 総行数（内訳） | 1,993,816（`day`=1,479,883 / `month`(day側)=139,176 / `month`(出典側)=23,022 / `year`(day側)=51,015 / `year`(出典側)=300,720） | `data/db/v2.sqlite` を実測（2026-09-15、`b04_build_cube.py` の標準出力） |
| v1形9テーブルの候補行数合計 | 749,300（`meas_daily` 139,532 / `meas_month` 127,493 / `meas_year` 116,076 / `meas_clim` 192 / `site_var` 8,140 / `var_catalog` 58 / `sensor_daily` 352,043 / `rain_daily` 3,654 / `sensor_hour_month` 2,112） | `data/db/v1_projection.sqlite` を実測（2026-09-15） |
| 突合ゲート（9テーブル対象） | 一致3（`sensor_daily`/`rain_daily`/`sensor_hour_month`、宣言済み差分0）・宣言済み差分のみ6（`meas_*`/`site_var`/`var_catalog`、既存の18キーのまま）・不一致0 | `reports/derived_reconciliation.md` |
| 既存6テーブルの射影の指紋（先頭16桁） | 1ビットも変わらず（`meas_daily=700094a0f8f2b979` 等、実装時の指定値と一致） | 実装コミット `000c393`（`phase-b/sensor-slice`）のコミットメッセージに記録 |
| パイプラインの所要時間（b03/b04/b05、単独実行） | 28.0s / 64.0s / 51.1s＋書き出し2.8s | 2026-09-15、`--out`/`--report`/`--cube-db` を一時ファイルに向けて再実行し実測（実行のたびに数秒変動する。実装時の申し送りは28.3s/60.3s/48.5s） |
| `place_relation`（地点→ゾーンの辺、`relation='within'`） | 290件。`fraction` は全行1.0、地点はすべて単一ゾーンにのみ属す（複数ゾーンにまたがる地点0件） | `data/db/registry.sqlite` を実測（2026-09-22） |
| `zone_year`/`zone_clim` 行数（v1・v2 とも一致） | `zone_year` 3,710 / `zone_clim` 619 | `data/db/derived.sqlite` と `data/db/v1_projection.sqlite` を実測（2026-09-22）、両者一致 |
| v1形11テーブルの候補行数合計 | 753,629（9テーブル分749,300 + `zone_year` 3,710 + `zone_clim` 619） | `data/db/v1_projection.sqlite` を実測（2026-09-22） |
| 突合ゲート（11テーブル対象） | 一致5（`sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/`zone_clim`、宣言済み差分0）・宣言済み差分のみ6（`meas_*`/`site_var`/`var_catalog`、既存の18キーのまま）・不一致0 | `reports/derived_reconciliation.md`（2026-09-22実測） |
| 既存9テーブルの射影の指紋（全列・全行を `ORDER BY` で正準化して sha256） | 1ビットも変わらず（`zone_year`/`zone_clim` の追加前後で完全一致。main の `data/db/v1_projection.sqlite` とも一致） | 2026-09-22実測（`phase-b/zone-slice`） |
| パイプラインの所要時間（b05、`zone_year`/`zone_clim` 追加後・単独実行） | 39.7s＋書き出し1.9s（追加前は36.6s＋2.7s） | 2026-09-22実測 |

## 5. 決定事項（実装された最終形。ADR-0009 決定3 の適用範囲修正を反映）

### D1. 移行は値を作らない

`observation.value_num` ← `measurements.value` をそのまま運ぶ。`value_raw` から数値を作り直さない
（ADR-0016「移行の誤りと意図的な変更を分離する」）。帰結: `ノニルフェノール` の 69行
（`value_raw='0.00006'` 等、`measurements.value` が既に `NULL`）は v2 でも `value_num=NULL` の
まま運び、集計に入らない（v1 と一致）。§6 参照。

### D2. 検閲マッピング（`scripts/migrate/censoring.py`、実装が最終形）

| `value_raw` の形 | `censoring` | `censoring_limit` | 実測件数 |
|---|---|---|---:|
| `<...`（ASCII） | `below_lod` | `<` を除いた数値部分 | 75,689 |
| `ND` | `not_detected` | `NULL` | 1,067 |
| `>...` | `above_lod` | `>` を除いた数値部分 | 26 |
| `...未満`（日本語） | `below_lod` | `未満` を除いた数値部分 | 12 |
| それ以外 | `none` | `NULL` | 246,370 |

`◯未満` は当初 `unknown` にする案だったが、`censoring.py` の docstring にあるとおりオーナーが
撤回した。ADR-0009 決定3が禁じるのは「**意味が不明**な `detection_flag` コードの推測マッピング」
であり、`◯未満` は `<` と同じ「定量下限未満」を日本語で書いただけの**意味が読める**表記なので、
これを `unknown` にするのは決定3の趣旨から外れる、というのがオーナーの指摘（§「ADR-0009 決定3の
適用範囲の訂正」は `PHASE_B_INTAKE.md` に転記済み）。この変更の結果、`unknown` が実データに
対して1件も出ない（実測: 0件）。

`imputation='zero'` は `below_lod`/`not_detected` にだけ 0.0 を代入する。`above_lod` に 0 を
入れない（0 は上限ではない。`>3.2` の 3.2 は「これより大きい」という下限情報であり、逆転する）。
`n_censored`（キューブ）は `below_lod` の数、`n_not_detected` は別に数える（ADR-0009 決定2）。

### D3. observation は原表記を残す

ADR-0007 の列に加えて `unit_raw`（`measurements.unit` そのもの）と `period_raw`
（`measured_on` そのもの）を持つ。原本 `unit` が空でもレジストリ側で単位が解決する行が多数あり
（ADR-0010 背景の実測: 109,078行・34%が空、その一部はレジストリで解決）、v1 の `MAX(unit)` は
**原表記**を読む。単位の正準化は Phase B の範囲外（意図的な変更）。

### D4. 「値の粒度」と「日付の精度」を2軸に分ける（ADR-0021）

`value_grain`（alias が言う粒度。`measured_on` の桁数から再導出しない）と `period_grain`/
`period_start`/`period_end`（日付から作れる区間）を分ける。通常は一致する。食い違いは
`scripts/migrate/period_exceptions.yaml` の宣言（現状 `atsugi_river_water_quality` 1件、
3,840行）だけを許し、宣言に無い食い違い・使われなかった宣言・実測件数の食い違いはすべて
`scripts/b03_build_observation.py` を止める。詳細は ADR-0021。

### D5. キューブのキーに `obs_stat`・`value_grain`・`input_grain` を足す（ADR-0021）

キューブの次元キー: `region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
period_start, period_end, grain, input_grain, stat, imputation`。`obs_stat`（入力側の統計量）が
無いと `pH（最大値）`/`pH（最小値）`（`variable_id` も `grain` も同じ）が同じ格に混ざる。詳細は
ADR-0021。

### D6. キューブの積み上げは v1 と同じ経路にする

`meas_month`/`meas_year(kind='daily')` は日次セルから作る（生の観測から作り直さない。
ADR-0011「粒度をまたぐ再集計をしない」）。月・年セルの `n` は寄与した下位セルの数、
`n_censored` は下位セルの `n_censored` の和。`stat` は行ごとに1つ（ADR-0011）で、`meas_year` の
`avg`/`min`/`max` は `stat ∈ {mean, min, max}` の3行を射影側（`b05`）でピボットして1行にする。

### D7. 決定論性は SQLite の版に依存する（当初の想定から修正。ADR-0021）

当初の設計（走査順を変えても `AVG()` は1ビットも動かない、という実測）自体は誤りではない
（日次グループは最大3行で、この範囲では加算アルゴリズムの違いが顕在化しない）。しかし
アドバイザーの指摘で、**同じ SQLite の `AVG()` でも、libsqlite3 のバージョンが 3.43 未満だと
別の（素朴な）加算アルゴリズムに落ちる**ことが判明した。`meas_year(kind='daily')` のように
グループサイズが大きい（最大366）集計では、この違いが実際に20%のグループで表面化する
（3,176/15,836グループ。詳細は ADR-0021 決定3）。したがって「守るのは1点だけ:
平均は SQLite の `AVG()` で計算し、Python 側で計算し直さない」だけでは不十分で、
**SQLite のバージョンそのものを実行時に検証する**必要がある、というのが最終的な決定
（`scripts/b04_build_cube.py` の起動時のガード。`python -O` で消える `assert` ではなく
`raise SystemExit` にしてある）。

### D8. 置き場所と形式

`data/db/v2.sqlite`（`.gitignore` 済み、捨てて作り直せる）に `observation` と `observation_agg`
を作る。Parquet 化（ADR-0001）は L2/L3 の物理設計の決定であり、この縦線に pyarrow/duckdb を
持ち込む理由にはならない（`b02` は sqlite/JSON を読む）。Parquet 化は別フェーズの作業。

### D9. `b02_derived_compare.py` に `--tables` を足す

候補が33テーブルのうち3つしか持たない間、残り30は `missing_in_candidate` になり必ず非0で
終わる。`--tables meas_daily,meas_month,meas_year` で対象を絞れるようにし、レポート冒頭と
標準出力に「部分ゲート」である旨を明記する（実装済み。`reports/derived_reconciliation.md` で
確認）。指定されたテーブルがベースラインに無ければ例外で止める。

### D10. `meas_clim`/`site_var`/`var_catalog` はキューブのセルにせず、射影（`b05`）でのみ計算する（オーナー決定）

**このタスク（`phase-b/meas-remainder`）で追加した3テーブルは `b04_build_cube.py`
（`observation_agg`）を一切変更しない。** 理由は2つ、どちらも ADR-0011/ADR-0021 の
既存の決定と矛盾しないための線引き:

1. **ADR-0011 の事前計算の範囲外**: 事前計算するのは `place_kind ∈ {site, watershed,
   mesh3}` × `grain ∈ {day, month, year, fiscal_year}`。`meas_clim` の月別平年値
   （`month` 1〜12、年をまたいで積む）と `site_var`/`var_catalog` の全期間・地点別
   要約は、どちらもこの `grain` の語彙に無い集計軸——`observation_agg` の1行
   （1セル）として表せない。
2. **`meas_clim` は ADR-0021 決定2が禁じる `obs_stat` の混合をそのまま行う**:
   v1 の `meas_clim`（`web/scripts/build-derived.mjs`）は `GROUP BY variable, month`
   （v1 の変数文字列＝alias ごと）で、`site_id` も `obs_stat` も見ない。同じ alias
   文字列を異なる `obs_stat`/`unit_id` の系列が名乗っていれば、`meas_clim` はそれらを
   区別せず1つの平均に混ぜる（実測は §6）。ADR-0021 決定2は「キューブの1セルで
   `obs_stat` を混ぜない」と決めているので、この挙動を持つテーブルは原理的に
   キューブのセルになれない——**v1 のバグではなく v1 の元々の集計仕様**なので、
   直さずそのまま再現する対象。

そこで `b05_project_v1.py` は、`meas_clim`/`var_catalog`/`site_var` の v1 SQL
（それぞれ `meas_daily`/`meas_year` を `FROM` に取るだけの単純な再集計）と同じ形を
採る: 新しい逆引きを書かず、既存の `_MEAS_DAILY_SQL`/`_MEAS_YEAR_SQL`（`alias_lookup`/
`unit_lookup`/`place_lookup`/`year_keyed` を使う、既に一意性を検証済みの SELECT 文）を
`_materialize_lookup_tables` の直後（`_materialize_projection_tables`）で**一時テーブル
`meas_daily`/`meas_year` にそれぞれ1回だけ実体化**し、3つの再集計はそこから読む
（テキストのままサブクエリに埋め込むと、`meas_daily` の結合が2回・`meas_year` の
結合＋ピボットが3回計算し直しになるため。`alias_lookup`/`unit_lookup`/`year_keyed`
を実体化しているのと同じ理由・同じ手法）。`_materialize_lookup_tables` や
`assert_alias_is_function` 等を2つ目書かない、という原則も守っている。
`var_catalog` の ADR-0011 上の行き先は `variable` レジストリだが、レジストリへの
移設はこのタスクの範囲外（ゲートのために射影で再現するだけ）。

### D11. `zone_year`/`zone_clim` もキューブのセルにせず、射影（`b05`）でのみ計算する（オーナー決定。D10 の3例目）

`phase-b/zone-slice` で追加した `zone_year`/`zone_clim` も `b04_build_cube.py`
（`observation_agg`）を一切変更しない。理由は D10 と同じ2点:

1. **ADR-0011 の事前計算の範囲外**: 事前計算するのは `place_kind ∈ {site, watershed,
   mesh3}`。`zone` はこの語彙に無い。
2. **v1 の `zone_year`/`zone_clim`（`web/scripts/build-derived.mjs`）は
   `AVG(y.avg)`/`AVG(m.avg)`——ゾーン内の地点別平均を非加重で平均する**（`n` でも
   `place_relation.fraction` でも重み付けしない）。ADR-0011「`fraction` があるものは
   加重する」を素直に読めばキューブのロールアップセルは `SUM(value*fraction)/
   SUM(fraction)`（またはそれに準じた加重）になるはずだが、v1 はそうなっていない
   ——**v1 のバグではなく v1 の元々の集計仕様**なので、直さずそのまま再現する対象
   （D10 理由2と同型）。

そこで `b05_project_v1.py` は、`zone_year`/`zone_clim` の v1 SQL（`meas_year`/
`meas_month` を `FROM` に取るだけの単純な再集計）と同じ形を採る: D10 の3テーブルと
同じく、既に実体化している一時テーブル `meas_year`/`meas_month`
（`_materialize_projection_tables`）から読む（`meas_month` はこのタスクで新たに
一時テーブル化した——以前は `meas_month` 自体の出力 SQL がそのまま `_TABLE_SQL` に
入っていたが、`zone_clim` も同じ集計を読む必要があるため、`meas_daily`/`meas_year`
と同様に1回だけ実体化する形に揃えた）。

地点→ゾーンの対応は、`sites.zone` を直接読まず、レジストリの `place_relation`
（`relation='within'`。ADR-0022 決定2）から引く——`place_relation` の最初の消費者
（`place_lookup` の site_id 側と `place_source_ref(source_id='sites.zone')` の
ゾーン番号側を辺で繋いだ `site_zone_lookup` を作る）。この JOIN 自体がゾーンの
辺だけへの絞り込みになる（`place_relation` に将来ゾーン以外の `'within'` 辺が
増えても影響しない）。

**検証は「レジストリの不変条件」と「射影（b05）固有の前提」を分ける**
（コードレビュー対応。当初は4条件すべてを `b05` が `site_zone_lookup` の上で
検証していたが、うち3つはレジストリの書き手 `scripts/registry/build_place.py`
の出力そのものが満たすべき不変条件であり、消費者（`b05`）ではなく書き手側で
1回だけ保証する方が正しい深さ、との指摘で分けた）:

- **`scripts/r01_build_registry.py`（レジストリの不変条件。既存の
  `ID_UNIQUENESS_CHECKS`/`_assert_region_id_scope_invariant` と同じ置き場）**:
  (i) 地点がゾーンへの `'within'` 辺を高々1本しか持たない
  （当時は `_assert_zone_relation_child_is_single_valued`。`phase-b/place-attributes`
  で流域版と統合し `_assert_relation_child_is_single_valued` に改名済み）、
  (ii) `sites.zone` の
  `external_key` が数字だけの文字列（`_assert_zone_external_key_is_numeric`）、
  (iii) `place_source_ref(place_id, source_id)` の一意性（実データで全
  `source_id` について重複0件を確認したため `ID_UNIQUENESS_CHECKS` に汎用に
  追加）。テストは `scripts/tests/test_r01_invariants.py`。
- **`b05_project_v1.py`（射影固有の前提。レジストリ全体の不変条件ではない）**:
  `fraction` が全行1.0（v1 を非加重で再現するという `b05` の設計判断であり、
  `place_relation` 全体が守るべき制約ではない）、異なるゾーンの place が同じ
  ゾーン番号に解決されていないこと（`b05` が place_id ではなく番号だけで
  ゾーンを区別することから生じる、射影固有の懸念）、`site_zone_lookup` の
  `site_id` 一意（結合そのものの安全性——r01 が保証済みだが `b05` 側の防御と
  しても残す）、`reg.place_relation` テーブルが無い古い registry の検出。
  テストは `scripts/tests/test_b05_project_v1.py`（すべて `build_projections`
  経由——検証の呼び出しを消したらテストが落ちる形）。

どちらも崩れていれば `MigrationError`（またはr01では `AssertionError`）で
止まる（実データでは290辺すべて全条件を満たす。実測は §11・§4）。

キューブのゾーンのロールアップセル（ADR-0011 の `roll_up_to`）はまだ作らない。
使う側が現れたら作る。作るなら系列ごと・`n_places` 付き。

`sites.zone` の番号は region でスコープされていない（2地域目でゾーンを定義
すると番号が衝突しうる）。根本は ADR-0022 の place のキー設計側の課題として
`docs/add_area.md` に申し送った（本書では対応しない）。

## 6. 移行で温存した v1 の癖（ゲートが緑のうちは直さない）

- **`ノニルフェノール` の `value_raw='0.00006'` 等 69行**が v1 で `value IS NULL`（パース失敗＝
  v1 のバグ）。内訳は `0.00006`（37行）/ `0.00007`（16行）/ `0.00008`（9行）/ `0.00009`（7行）。
  v2 も `censoring='none'` かつ `value_num=NULL` の穴として温存した（D1）。
- **`>` 表記 26行**（すべて `透明度`、すべて `value IS NULL`）。`censoring='above_lod'` で
  `above_lod` に 0 を代入しないので集計に入らない＝v1 と一致。集計上の扱いは未決
  （`lod` 併記に切り替えるときに決める）。
- **`atsugi_river_water_quality` の年度番号だけの日付 3,840行**（`source_ref` に月ラベルが
  残っており復元可能。`scripts/migrate/period_exceptions.yaml` に記録済み）。
- **v1 の派生集計に合成データ（`is_synthetic=1`）2,265行が混入している。**
  `measurements.source_id IS NULL` の行は全部 `is_synthetic=1` で、全行 `length(measured_on)=10`
  かつ `value IS NOT NULL`（実測）なので、そのまま `meas_daily`（延いては `meas_month`/`meas_year`）
  に流れ込む。v2 もそのまま含めて再現した（ゲート緑後に外すのは意図的な変更）。
- **`measurements.value` は `below_lod`（ASCII `<`）/ `not_detected`（`ND`）行で採取段階から
  0.0 が入っている**（実測: `value_raw LIKE '<%'` の75,689行・`value_raw='ND'` の1,067行は
  すべて `value=0.0`。集計スクリプトの問題ではなくファクトテーブル自体の慣習）。**ただし
  日本語表記の `未満`（12行）は `value` が既に `NULL`**（0.0 ではない）で、この点だけ
  ASCII 表記と扱いが違う（v1 の `value_raw LIKE '<%'` が `未満` を拾わず、かつ `value` も
  `NULL` なので `AVG(value)` から自然に除外されていた＝v1 が「たまたま」正しく除外していた
  ケース）。
- **`kanagawa_jiban_chinka` の年次 `n=2` グループ 1,625件がすべて同値ペア（`min=max`、
  `value_raw` も完全一致）。二重投入の疑いを実測で確認した。** 例:
  `地下水位(年平均)` の `site_id='kanagawa_jiban_chinka__1'`・`measured_on='1980'` は
  `-2.17` が2件あり、`source_ref` を見ると一方は `r5table.xlsx`（令和5年度版報告書）、
  もう一方は `r6table.xlsx`（令和6年度版報告書）から来ている——**同じ1980年の値が、
  異なる年度の報告書（過去分を再掲する仕様）から重複して収集されている。**
  データ収集（`scripts/c8*` 系）側の課題であり、この縦線（`b03`〜`b05`）の実装の問題ではない。
- **`meas_year` は `kind='annual'` が `kind='daily'` の約6.3倍**（実測: `annual` 100,240行 /
  `daily` 15,836行。`data/db/derived.sqlite` と `data/db/v1_projection.sqlite` の両方で一致）。
- **`meas_clim`（月別平年値）は、同じ alias 文字列を持つ `obs_stat`（入力側の統計量）の
  異なる別系列を区別せず、1つの平均に混ぜている（D10 の理由2。v1 のバグではなく元々の
  集計仕様として温存）。** `data/db/registry.sqlite` の `variable_alias`（`dataset=
  'measurements'`）を実測すると、1つの alias 文字列に複数の `(variable_id, grain, stat,
  unit_id)` が対応する alias が**12件**（全58 alias中）ある。このうち `meas_clim` が
  実際に混ぜるのは、複数の系列がどちらも `grain='day'`（`meas_daily` を経由して
  `meas_clim` に入る）を持つ**5 alias**だけ（残り7 alias は `fiscal_year` 側の系列しか
  重複がなく、`meas_clim` の入力である `meas_daily` に現れない）:

  | alias | 混ざる系列（`obs_stat`／出典） | day セル数（内訳） | 合成データ混入 |
  |---|---|---:|---|
  | `pH` | `mean`／`atsugi_river_water_quality` と `point`／`env_kousui_sample_kanagawa` | 144 + 19,076 = 19,220 | `point` 側に673セル（`source_id IS NULL` の合成データが `env_kousui_sample_kanagawa` と同じ tuple に解決されるため） |
  | `化学的酸素要求量 COD` | `mean`／`atsugi_river_water_quality` と `point`／`env_kousui_sample_kanagawa` | 144 + 18,399 = 18,543 | 無し |
  | `浮遊物質量 SS` | `mean`／`atsugi_river_water_quality`（+合成データ） と `point`／`env_kousui_sample_kanagawa` | 236 + 12,928 = 13,164 | `mean` 側に92セル |
  | `溶存酸素量 DO` | `mean`／`atsugi_river_water_quality`（+合成データ） と `point`／`env_kousui_sample_kanagawa` | 236 + 18,410 = 18,646 | `mean` 側に92セル |
  | `生物化学的酸素要求量 BOD` | `mean`／`atsugi_river_water_quality` と `point`／`env_kousui_sample_kanagawa` | 144 + 14,045 = 14,189 | 無し |

  （2026-09-15実測。「day セル数」は `data/db/v2.sqlite` の `observation_agg`
  （`grain='day'`）を `variable_alias` で alias 引き戻ししたセル数で、`meas_clim` の
  `SUM(n)`（全12ヶ月合計）と一致することを確認済み。合成データ列は、`source_id IS NULL`
  ＝`is_synthetic=1` の観測が寄与しているセル数。`浮遊物質量 SS`/`溶存酸素量 DO` は
  `source_id IS NULL` の tuple が `atsugi_river_water_quality` と同じ
  `(variable_id, grain='day', stat='mean', unit_id)` に解決されるため `mean` 側に混じり、
  `pH` は `source_id IS NULL` の tuple が `env_kousui_sample_kanagawa` と同じ tuple に
  解決されるため `point` 側に混じる——どちらに混じるかは alias の定義（レジストリ）
  次第で、規則性は無い）。`site_var`/`var_catalog` は `meas_year`（`site_id` を保つ）を
  経由するが、次の2つは挙動が異なる（混ざるのではなく止まる場合と、無防備に混ざる
  場合がある。実測は下記）:
  - **同じ地点・同じ年に同じ alias・同じ kind の2系列がある場合**: `meas_year` の
    キー（`site_id, variable, year, kind`）が重複し、`assert_v1_keys_are_unique` が
    検出して `MigrationError` で**止まる**（混ざらない）。
  - **黙って混ざるのは別の年の場合**: 同じ地点が、ある年に系列A、別の年に系列B
    （同じ alias・同じ kind だが `(variable_id, value_grain, obs_stat, unit_id)` は
    別）を持つと、`meas_year` のキーは年が違うので衝突せず2行のまま残る。`site_var`
    は `site_id, variable, kind` で `AVG(avg)` するため、この2系列を区別せず平均に
    混ぜる——`assert_v1_keys_are_unique`（出力キーの一意性しか見ない）では捕まらない。
  - `var_catalog` は `variable` だけで集計するので、そもそも常に地点・系列をまたいで
    `n` を合計し `MAX(unit)` を取る（1系列に限定する仕組みが無い）。
  - いずれも v1（`web/scripts/build-derived.mjs`）と同じ挙動なので、この2つの
    ゲートは正しい。「別の年に同じ地点・alias・kind の別系列がある」件数を
    `data/db/v2.sqlite`（読み取り専用）で実測すると**0件**（2026-09-15実測。
    year_keyed を `site_id, variable(alias), kind` でグルーピングし、複数の
    `(variable_id, value_grain, obs_stat, unit_id)` にまたがるグループが無いことを
    確認した）。

- **`sensor_daily`/`rain_daily`/`sensor_hour_month` の毎時分（sagamihara/soramame）は
  v1 のラベル日割り（`substr(phenomenon_time,1,10)`）をそのまま再現している。**
  hour_ending のラベルは区間の終わりなので、23時〜24時の値がラベルの日（＝翌日）に
  入るという、区間の境界をはみ出す集計になっている（v1 の癖。ADR-0024 決定3・§9 T5）。
  「ラベルが00:00:00（日をまたぐ24時ラベル）」の件数は数え方が2通りある（実測。
  `value_grain='hour'` の行を `sensor_timeseries.source_id` で引き戻して集計）:
  全行（`result IS NULL` も含む）では sagamihara 7,306 / soramame 7,020（計14,326）、
  `value_num IS NOT NULL` に絞ると sagamihara 7,263 / soramame 6,498（計13,761）。
  `b05` の `verify_hourly_daily_rollup`（T6）が実際に使うのは後者（キューブ側の
  `WHERE v IS NOT NULL` と揃えるため）。
- **`rain_daily` は単位不明の相模原 `RAIN`（`sagamihara_taiki_hourly`、`unit_id=NULL`）
  を `/10` で推測換算している**（v1 のコメント「0.1mm 単位（原本に unit の記載が
  ないので mm に直した）」をそのまま再現するためだけの処理。レジストリは `RAIN` の
  単位を推測せず `unit_id=NULL` のまま持つ。ADR-0023 が扱う「単位は分かっているが
  出典間でスケールが違う」8変数とは別の問題）。
- **`jma_monthly_kanagawa` の積雪3変数に、月次限定の alias 表記ゆれがある**（実測。
  `variable_alias` の `source_id='jma_monthly_kanagawa'` を確認すると、
  `weather.snow_depth_max`（`雪_最深 積雪`〔全角スペースあり〕/`雪_最深積雪`）・
  `weather.snowfall_depth_total`（`雪_降雪_合計`/`雪_降雪の深さ_合計`）・
  `weather.snowfall_depth_max_daily`（`雪_降雪_日合計の最大`/`雪_降雪の深さ_日合計の最大`）
  の3変数が、それぞれ2つの alias 文字列から同じ `(variable_id, unit_id, stat, grain)`
  に解決される）。`jma_monthly` は月次出典配布セルであり v1 の11テーブルには射影しない
  ため実害は無いが、`assert_alias_is_function` の sensor 側検証は b05 が実際に消費する
  grain（day/hour/instant）だけに絞ってこの重複を意図的に見逃している（§9 T5「逆引きの
  検証」）。
- **`jma_daily_yokohama` の文字列系4系列は `result` が全行 `NULL`**（実測。
  `天気概況_昼`/`天気概況_夜`/`風向・風速_最大瞬間風速_風向`/`風向・風速_最大風速_風向`
  の4系列、各971行、全行 `result IS NULL`）。`value_text` は上流の `m02` で既に消えて
  いるため、このセンサーの縦線では文字列値を持つ観測が無い（§9 T3）。負債として記録
  のみ、この縦線では対応しない。
- **`soramame_hourly_kanagawa` の hour_ending という前提は一次資料未確認**（ADR-0024
  T2）。収集スクリプトの記載（`scripts/c11_soramame.py`・`scripts/c13_sagamihara_taiki.py`
  の「そらまめ君同様」という伝聞）のみを根拠に採用している。環境省の一次資料を
  Web 検索で探したが確認できなかった（2026-09-15）。

## 7. やっていないこと

- 残り22テーブル（ADR-0011 §「33テーブルの行き先」参照。`meas_clim`/`site_var`/
  `var_catalog`/`sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/
  `zone_clim` の8テーブルは本タスク・前タスクで済んだ）
- `occurrence` を入力にする縦線（生物系11テーブル）
- キューブのゾーンのロールアップセル（ADR-0011 の `roll_up_to`。D11参照。使う側が
  現れたら作る。作るなら系列ごと・`n_places` 付き）
- `imputation='lod'` 併記（ADR-0009 決定4。今回は `zero` のみ）
- 正準単位の併記（ADR-0023。方針は決定済みだが未実装）
- 時刻帯の実データ結線（ADR-0024。`region_id` から実際のUTCオフセットを引く仕組みは
  未実装。応答封筒〔ADR-0014〕の実装より前に要る）
- Parquet 化（ADR-0001。D8 参照）
- 公開 ID（`observation_id`）の発行（ADR-0016 Phase C の仕事）
- **既知の負債（D-3: 「`b03` の負債は解消」の記述を実態に合わせて更新）**:
  `scripts/b03_build_observation.py` の `observation` 書き込みは、`sensor_timeseries` を
  入力に追加したこのタスクで `common.fresh_sqlite`（ファイル全体を作り直す）から
  `common.replace_table`（`observation` テーブルだけを作り直す）に変更した（§3参照）。
  ADR-0007 が `measurements` と `sensor_timeseries` を**同じ** `observation` に統合すると
  明言しているため、将来 `occurrence`（ADR-0007 決定3）が同じ `v2.sqlite` に増えても
  `b03` の実行がそれを消さなくなった。**その後（センサーの縦線の整理、A-1）**:
  `b03`/`b04` は両方とも `common.staged_table`（作業用テーブルに作る→全検証（取り込み・
  宣言表・T1不変条件／次元キーの一意性）を通す→本番名に差し替える）へ変わり、検証に
  1つでも失敗すれば前回のテーブルがそのまま残るようになった（`replace_table` の
  「先に消してから作る」非原子は `observation`/`observation_agg` については解消済み）。
  `b05_project_v1.py`（`v1_projection.sqlite` を `fresh_sqlite` でファイルごと作り直す）は
  元々「メモリ上で全検証→書き出し」の設計のため対象外（変更なし）。
  **以下2点は Issue #37（親 #27）で解決済み**:
  1. **段階間の指紋**（`scripts/migrate/common.py` の `record_stage_fingerprint`/
     `assert_stage_fingerprint_fresh`/`compute_table_fingerprint`/
     `read_recorded_fingerprint`/`read_recorded_inputs`/`track_reads`/
     `assert_all_reads_verified`）。**設計の正は `scripts/migrate/common.py`
     の該当関数群の直前のモジュールコメント**（指紋の中身・保存場所・
     (a)/(b) の別・(b) の再帰・読み取りの機械監査〔Tier 1〕の設計判断は
     すべてそこに書いてある。ここでは繰り返さない）。以下はこの文書に残す
     測定値・受け入れ基準・段ごとの対応表だけ。
     - **段ごとの読み取り→検証の対応表**（各段の SQL が ATTACH 先のどの表を
       読んでいるかを grep で確認した結果。`declared` は `track_reads`/
       `assert_all_reads_verified`〔Tier 1、段単位の粗さ——per-table 精度の
       自動導出は Tier 2 として別 Issue に切り出す。下記「次の一手」参照〕に
       渡す宣言集合）:

       | 段 | ATTACH 先で読む表 | (a) 自己一致チェック | (b)/系譜 | Tier 1 機械監査 |
       |---|---|---|---|---|
       | b04 | 自ファイルの `observation` | 済 | `observation_agg.inputs={"observation":...}` | 未適用（同一ファイル・単純） |
       | b05 | `cube.observation`・`cube.observation_agg` | 両方済 | 11/13表に `observation`+`observation_agg`、`landuse_*` 2表は `observation_agg` のみ（`_TABLES_WITHOUT_OBSERVATION_DEPENDENCY`。per-table 精度は Tier 1 の段単位の粗さでは代替できないため手書きのまま維持） | `declared={"observation","observation_agg"}` |
       | b07 | 自ファイルの `occurrence` | 済 | `occurrence_agg.inputs={"occurrence":...}` | 未適用 |
       | b08 | `cube.occurrence`（3経路）・`cube.occurrence_agg`（`_assert_cube_is_current_l2_partition` が直接突合）・`cube.occurrence_place` | `occurrence`: 済／`occurrence_agg`: 集計突合が代替／`occurrence_place`: 済 | `org_norm`/`org_watershed*` に系譜を記録。年キー8表・`species_month`・`ias_species` は消費側が無いため `inputs={}` | 5エントリポイントそれぞれに `declared`（`occurrence`・`occurrence_agg`・`occurrence_place` の要る組み合わせ。`occurrence_agg` は L2 突合で検証済み扱い） |
       | b09 | 自ファイルの `occurrence`・`ryuiki.sites`（原本、対象外） | 済 | `occurrence_place.inputs={"occurrence":...}` | 未適用 |
       | b11 | `proj.site_var`・`proj.landuse_watershed`・`occ.org_watershed`／`cube_v2.*` は系譜チェック専用 | 3表とも済 | 再帰で `observation`/`observation_agg`/`occurrence`/`occurrence_place` まで到達 | `declared=set(verified_fingerprints)`（site_var/landuse_watershed/org_watershed） |
       | b03/b06 | `src.*`（`ryuiki.sqlite`、原本） | 対象外 | 出力は基底テーブルとして `inputs={}` | 対象外（原本は `pipeline_fingerprint` を持たないため自動除外） |
       | b10 | `ryuiki.*`/`cells.*`（原本） | 対象外 | Phase B の上流出力を経由しない | 対象外 |
       | b12 | `registry.sqlite`（別系統） | 対象外 | r01 自身の `registry_build` 指紋で管理済み | 対象外（`registry.sqlite` は `pipeline_fingerprint` を持たないため自動除外） |
     - **次の一手（Tier 2、別 Issue）**: 今回（Tier 1）は段単位の粗さ
       （`declared` を呼び出し側が手で列挙する）に留めた。出力テーブルごとに
       正確な入力集合を自動導出する（per-table 精度、`declared` の手書きを
       無くす）には、1接続・1回の走査で複数出力を作る現状の構造を
       テーブルごとに分ける設計変更が要る——着手しない。
     - **壊れた/古い上流出力で実際に止まることの実測**（受け入れ基準。単体
       テストに加え、worktree 内の実データ〔`/tmp` のスクラッチコピー、
       元チェックアウトの `data/db` は無傷〕でも確認した）:
       - b03→b04→b05: b03 だけ作り直し b04 を忘れて b05 を実行 →
         「`observation_agg` は上流 observation の指紋...を消費した状態の
         ままだが、observation は現在...を自己申告している」で b05 が停止
         （`scripts/b04_build_cube.py を再実行すること`）。単体テストは
         `test_migrate_common.py`（`test_lineage_check_detects_upstream_
         rebuilt_without_downstream_rerun` 等）・`test_b05_project_v1.py`
         （`test_build_projections_halts_when_observation_rebuilt_without_
         rerunning_b04`）。
       - b03→b05（`observation` を直接改変・自己指紋は更新しない）:
         `observation_agg` の系譜チェックでは検出できない改変
         （`observation` の自己申告自体は変えていないため）でも、`observation`
         自身への独立した (a) が検出して b05 が停止する
         （`scripts/b03_build_observation.py を再実行すること`）。単体テストは
         `test_b05_project_v1.py::
         test_build_projections_halts_when_observation_tampered_without_
         updating_its_own_fingerprint`。
       - b06→b07→b08: b06 だけ作り直し（occurrence に1行追加）b07 を忘れて
         b08 を実行 → 既存の `_assert_cube_is_current_l2_partition`
         （このタスクでは変更していない）が「occurrence_agg が『今の
         occurrence の分割』になっていない」で停止（`scripts/
         b07_build_occurrence_cube.py を再実行すること`）——この経路は
         集計突合という別の（より強い）機構が既に塞いでいたことを実データで
         再確認した。既存の単体テストは
         `test_b08_occurrence_cube_projections.py::
         test_l2_cube_mismatch_stops_projection`。
       - b03（**だけ**）・b11: b03 だけ別内容で作り直し、b04・b05 は一切
         実行しない（`observation_agg` は無傷のまま）→ **再帰で2段たどって
         初めて**「`site_var` は上流 observation の指紋...を消費した状態の
         ままだが、observation は現在...を自己申告している」で b11 が停止
         （`scripts/b05_project_v1.py を再実行すること`。これが1段しか
         遡らない実装で通ってしまっていた、今回の穴そのもの）。単体テストは
         `test_b11_project_place_v1.py::
         test_build_projections_halts_when_observation_rebuilt_two_hops_away_*`
         （2本——`site_var` が `observation` を直接持つ本物の b05 と同じ
         経路の版と、`observation_agg` だけを持つ最小限のフィクスチャで
         純粋に再帰能力だけを確かめる版）。
       - b05・b11（`observation_agg` だけ作り直し）: b03/b04 を作り直し
         （`observation_agg` が新しい自己指紋を持つ）b05 を忘れて b11 を
         実行 → 「`site_var` は上流 observation_agg の指紋...を消費した
         状態のままだが、observation_agg は現在...を自己申告している」で
         b11 が停止（`scripts/b05_project_v1.py を再実行すること`）。単体
         テストは `test_b11_project_place_v1.py::
         test_build_projections_halts_when_observation_agg_rebuilt_without_
         rerunning_b05`。
       - 指紋の記録の原子性: `staged_table` の差し替えと指紋の記録の間に
         人為的に例外を起こすと、差し替えごと（指紋も含めて）巻き戻り、
         前回の本番テーブルと前回の指紋がどちらもそのまま残ることを確認した
         （`test_migrate_common.py::
         test_staged_table_fingerprint_inputs_is_committed_atomically_with_the_swap`）。
         対比として、差し替えと指紋の記録を**別々に**呼ぶ（直す前の書き方）
         と実際に「内容は新しいが指紋は古い」状態が作れてしまうことも
         再現した（`test_migrate_common.py::
         test_recording_fingerprint_separately_from_the_swap_can_leave_it_stale`）。
       - 読み取りの機械監査（Tier 1）: `declared` に無い表を JOIN で読むと
         `assert_all_reads_verified` が止まることを確認した
         （`test_migrate_common.py::
         test_assert_all_reads_verified_raises_on_undeclared_join`——
         これが b05 の `cube.observation` 検証漏れと同じ形の見落としを
         機械的に検出できることの確認）。
  2. **`staged_table` の差し替え（`DROP TABLE`→`ALTER TABLE RENAME`）の原子性**は、
     実装を確認したところ**既に解決済みだった**（コミット `45181b2`
     「staged_table: 差し替え（DROP+RENAME）を明示トランザクションで原子化」——この
     文書のこの節が古いままだった）。`scripts/migrate/common.py` の `staged_table`
     は差し替えの2文を明示の `BEGIN`〜`COMMIT` で1トランザクションに包んでおり
     （`conn.commit()` の直後は開いているトランザクションが無いため、裸の DDL のまま
     では `DROP` が確定した直後にプロセスが死ぬと本番テーブルが消えたまま戻らない
     ——明示トランザクションに包めば未コミットのまま自動的に巻き戻る）、途中で
     例外が起きても本番テーブルを元に戻し作業用テーブルも残さない。**判断: 直す
     （既に直っている）**。`scripts/tests/test_migrate_common.py` の
     `test_staged_table_failure_between_drop_and_rename_preserves_previous_table`
     （`ALTER TABLE` の直前で例外を起こすプロキシで再現）が既にこれを確認している。
     **その後（2回目の /code-review 指摘）**: DDL の差し替え自体は atomic
     でも、指紋の記録（`record_stage_fingerprint`）が**別コミット**のままでは
     「内容は新しいが指紋は古い」状態が原理上残ることが分かり、上の系譜の
     項目にまとめたとおり `fingerprint_inputs` 引数で同じトランザクションに
     統合した。
  **もう1つ、既知の判断として**: `scripts/b05_project_v1.py` は v1 互換の射影の置き場
  として線形に増え続けている（現在13テーブル）。次に T6 級（出典固有の Python 検証関数）
  を足す時点で、検証関数群を別モジュールに分けること——**これも Issue #37（#3）で実施
  済み**。`assert_alias_is_function`/`assert_alias_tuple_maps_to_single_dataset`/
  `assert_unit_raw_is_function`/`assert_v1_keys_are_unique`/`verify_hourly_daily_rollup`・
  D11のゾーン固有の4検証関数を `scripts/migrate/v1_projection_checks.py` に移した
  （振る舞いは変えない純粋な移動——`scripts/b05_project_v1.py` は同名のモジュール変数
  として再エクスポートするため、内部の呼び出し・既存テスト〔`b05.assert_alias_is_function(...)`
  等〕は1つも変えていない。実測: 移動前後で `test_b05_project_v1.py` の37件がそのまま
  変わらず成功）。

## 8. 次の一手（オーナーの方針）

- (a) `◯未満` の下限反映で動いた18キー（`expected_diffs.yaml` に宣言した同じ12行由来。
  `meas_daily` 2件・`meas_month` 2件・`meas_year` 9件・`meas_clim` 2件・`site_var` 2件・
  `var_catalog` 1件の差分として波及。後半3テーブルの波及は2026-09-15実測）は、
  **zero→lod 切替の前に**単独で確認できる状態にしてある（`scripts/reconcile/expected_diffs.yaml`
  に理由・実測値つきで記録済み）。
- (b) 次の縦線は `sensor_timeseries` 系（`sensor_daily`/`sensor_hour_month`）。そこで初めて
  申し送り #5（原表記スケール単位。×10スケールの7単位）が着手判定を塞ぐ。
  **→ `phase-b/sensor-slice` で実施済み（§9・§10）。**

## 9. センサーの縦線（`sensor_timeseries` → `observation` → キューブ → `sensor_daily`/`rain_daily`/`sensor_hour_month`）

対象: `sensor_timeseries`（717,839行。`sagamihara_taiki_hourly`/`soramame_hourly_kanagawa`/
`hiratsuka_taiki`/`jma_daily_yokohama`/`jma_monthly_kanagawa`/`yokohama_river_waterlevel`/
`synthetic_sensor` の7出典）を入力に追加し、`sensor_daily`/`rain_daily`/`sensor_hour_month`
の3テーブルを通した（`phase-b/sensor-slice`）。設計は `sensor_design_v2.md`（オーナー決定、
アドバイザーのレビュー反映済み）。決定は ADR-0023（単位）・ADR-0024（時刻帯・時刻ラベル）に
切り出した。ここでは実装された最終形（T1〜T6）を記録する。

### T1. 時刻帯なしのローカル時刻（ADR-0024 決定1）

`period_start`/`period_end` は時刻帯なしのローカル時刻。原表記（`+09:00` 付き）は
`period_raw` に残す。`scripts/migrate/period.py` の `_strip_tz` が25桁ラベルから時刻帯を
落とす。`b03` が全行で不変条件（`+`/`Z` を含まない・`date(period_start)` が日付部分と
一致）を検証する。

### T2. 時刻ラベルの意味の宣言（ADR-0024 決定2）

`scripts/migrate/time_label_conventions.yaml` に `sagamihara_taiki_hourly`
（`expected_row_count=175,344`）・`soramame_hourly_kanagawa`（`expected_row_count=168,793`）
の2件を `hour_ending` として宣言した。CI（`79da0fc`）が構造（`convention`/
`expected_row_count`/`evidence` の必須キー）を、`b03` が実行時に使用件数・件数一致を検証する。

### T3. `b03` が `measurements` と `sensor_timeseries` を1本の `observation` に統合

出典ごとの取り込み関数（`_ingest_measurements`/`_ingest_sensor_timeseries`）に分け、
alias/place 解決・grain の食い違い検証・時刻の不変条件は共有する。`observation` の書き込みを
`fresh_sqlite`（ファイル全体作り直し）から `replace_table`（`observation` テーブルだけ作り
直し）に変更し、出典ごとに1トランザクションでストリーム挿入する（全行をリストに溜めない）。
`source_measurement_id` を `source_table`+`source_row_id` に一般化した。センサーは
`censoring='none'`・`value_raw=NULL` 固定、単位は出典のまま（ADR-0023 決定1）。

### T4. キューブ（`b04`）が毎時・瞬時・月次出典配布セルを持つ

`period_grain IN ('hour','instant')` の観測も日次セルに積み上げる（日付は
`substr(period_start,1,10)`＝区間の始まりの日付。正しい日割り。ADR-0024 決定3）。日次セルは
全変数で `stat ∈ {mean, min, max}` を作り、`default_stat='sum'` かつ `obs_stat` が `NULL`/
`'sum'` の系列だけ `stat='sum'` も足す。`period_grain='month'`（`jma_monthly`）は日次セルを
経由しない出典配布の月次セル（年次の出典配布セルと対称）にした。出典配布の年次セルは
`period_grain IN ('year','fiscal_year')` に閉じた（以前の `period_grain <> 'day'` は
月次・毎時まで吸い込んでいた）。月次・年次（日次セルから積み上げる側）の `input_grain` は
`cube_day` から引き継ぐ（`'day'` 直書きをやめた）。詳細は ADR-0021 の2026-09-15追記。

### T5. 射影（`b05`）— v1 の癖は射影にだけ置く

- `sensor_daily`: `value_grain ∈ {day, instant}` の出典（hiratsuka/jma_daily/yokohama/
  合成）はキューブの日次セルから（mean/min/max をピボット）。`value_grain='hour'` の出典
  （sagamihara/soramame）は `observation`（L2）から `substr(period_raw,1,10)`（v1 の
  ラベル日割り）で直接集計し `UNION ALL`（キューブを経由しない。ADR-0024 決定3）。
- `rain_daily`: 同じく L2 から。`ROUND(SUM(value_num)/10.0, 2)`（v1 の推測換算の再現。§6）。
- `sensor_hour_month`: 月・時刻は `period_raw` から取る（`period_start` だと hour_ending で
  1時間ずれる）。地点をまたいで混ぜる（v1 と同じ）。
- 逆引きの検証: `(variable_id, value_grain, obs_stat, unit_id) → alias` の関数性は、射影する
  セル・行に現れる tuple に限って assert する（`jma_monthly` の積雪3変数の alias 重複は
  月次で射影しないため対象外。§6）。**tuple → dataset の一意性**も新たに assert する
  （同じセルが `meas_*` と `sensor_*` の両方に二重に出ないように。実測では衝突0件）。

### T6. キューブの毎時→日次の正しさを機械で確かめる

`verify_hourly_daily_rollup` が、`value_grain='hour'` の各系列・各日について、キューブの日次
セルの件数が v1形のラベル日割りから機械的に導ける期待値と一致すること、系列ごとの全期間の
Σn・min・max が L2 とキューブで一致することを検証する（崩れれば `MigrationError`）。実データで
通過を確認済み。**検証式は `scripts/b05_project_v1.py` の `verify_hourly_daily_rollup` の
docstring が正**（D-1）。決定の経緯は ADR-0024 決定4。

## 10. キューブに既に織り込んだ意図的な変更

キューブ（`observation_agg`）の日次セルは、hour_ending の毎時値を**正しい日割り**（区間の
始まりの日付）で積み上げている。v1（および v1 互換の射影 `sensor_daily`/`rain_daily`/
`sensor_hour_month`）は**ラベルの日付**で日割りしており、この2つは食い違う。以下は
「v1 のラベル日割り」と「キューブの正しい日割り」を直接比較した実測（2026-09-15、
`value_num IS NOT NULL` の観測のみ対象。n/avg/min/max のいずれかが変われば「値が変わる」に
数える）:

| 対象 | 値が変わる | 消える（v1にあってキューブに無い） | 現れる |
|---|---:|---:|---:|
| `sensor_daily`（hour-grain系列のみ。v1側13,831 (系列,日) 組） | 9,424 | 2 | 0 |
| `rain_daily`（v1側3,654 (日) 組） | 549 | 1 | 0 |
| `sensor_hour_month`（月×時刻のバケツ替え。2,112行中） | 1,992 | 0 | 0 |

**この変更量は今すぐ表に出ない。** `sensor_daily`/`rain_daily`/`sensor_hour_month` は
（T5 のとおり）キューブを経由せず L2 から v1 のラベル日割りで直接計算されるため、
`b02_derived_compare.py` の突合ゲートは v1 と完全一致し続ける（§4「突合ゲート（9テーブル対象）」
の行・`docs/plans/PHASE_B_RECONCILIATION.md` §6参照）。
**切り替えは「v1 互換の射影（L2 直接集計の分岐）を退役させ、キューブの日次セルだけを使う」
だけで起き、その時点で `sensor_daily` の9,424行・`rain_daily` の549行・`sensor_hour_month`
の1,992行が一度に動く。それまでは `observation`/`observation_agg`（v2）は1行も動かない。**
この量を宣言済み差分（`expected_diffs.yaml`）で1件ずつ吸収するのは非現実的な規模なので、
退役の判断自体をこのドキュメントと ADR-0024 に残す。

## 11. ゾーンの縦線（`meas_year`/`meas_month` → `zone_year`/`zone_clim`。`place_relation` の最初の消費者）

対象: `sites.zone` を持つ290地点（`meas_year`/`meas_month` を経由）を `zone_year`/
`zone_clim` の2テーブルに束ねた（`phase-b/zone-slice`）。設計・決定・検証条件・
`sites.zone` ではなく `place_relation` から引く理由・レジストリ（r01）と射影
（b05）の分担は**すべて D11（§5）を正とする**（ここでは繰り返さない）。
`b03`/`b04` は無変更——新しいファクト源を足していない。入力は既に実体化済みの
v1形の一時テーブル（`meas_year`/`meas_month`）で、`observation_agg` は一切読まない。

### レビュー対応の経緯

1回目のコードレビューで、検証の対象が `reg.place_relation` テーブル全体
（ゾーン以外の `'within'` 辺を含みうる）になっており、`site_zone_lookup`
（ゾーンの辺だけに絞った一時テーブル）に絞るべきと指摘され、検証をそちらに
移した（併せてゾーン番号の形式・place をまたぐゾーン番号衝突の2条件を追加）。

2回目の `/simplify` で、その4条件のうち3つ（地点→ゾーンの辺の単射性・
ゾーン番号の数値形式・`place_source_ref` の一意性）は「射影（b05）の前提」
ではなく「レジストリの不変条件」であり、書き手 `scripts/r01_build_registry.py`
側で1回だけ保証する方が正しい深さ、との指摘で `r01` に移設した（D11 参照）。
`b05` に残したのは、射影固有の前提（`fraction=1.0`・ゾーン番号の place を
またいだ衝突）と、結合そのものの安全性（`site_zone_lookup` の site_id 一意）
だけ。あわせて、重複検査の同型のコード（`GROUP BY ... HAVING ... > 1` →
先頭5件を例示 → `MigrationError`）を `_raise_on_group_by_duplicates` の
1関数に統合した（既存の `assert_alias_is_function` 等も含む）。

### 実測結果

`zone_year`（3,710行）・`zone_clim`（619行）とも v1（`data/db/derived.sqlite`）と
**完全一致**（宣言済み差分0。`reports/derived_reconciliation.md` の該当節。§4）。
差分が出るはずの唯一の既知経路（§6「移行で温存した v1 の癖」の`atsugi_river_
water_quality__中津川`の`未満`表記12行）は、この site_id が `sites` テーブル本体に
存在しない（`site_supplement.csv` 側の補完地点）ため `sites.zone` を持たず、
`place_relation` にも辺が無い——`zone_year`/`zone_clim` には波及しない（実測で
確認。中津川はもともと `sites` に登録が無い出典側の地点）。

既存9テーブルの射影の指紋（全列・全行を `ORDER BY` で正準化した sha256）は
`zone_year`/`zone_clim` の追加前後で1ビットも変わらない（`meas_month` の
出力元を「直接 SELECT」から「実体化した一時テーブルから SELECT」に変えたが、
SQL の計算結果自体は同じため。§4実測）。

`r01` に移設した不変条件も実データで確認済み（`scripts/r01_build_registry.py`
の標準出力）: 地点→ゾーンの辺は単射290件、`sites.zone` の external_key
数値形式OK 5件、`place_source_ref(place_id, source_id)` 一意性OK 4,964件
（全4種の `source_id`——`sites.site_id`/`sites.zone`/
`watershed_meta.watershed_id`/`organism_records.lat_lon`——で重複0件）。
