# Phase B 縦に薄い1本 — `measurements` → `observation` → キューブ → v1形

対象: ADR-0016 の Phase B / 状態: **実データで一度緑になった（部分ゲート。33テーブル中3テーブル）**
作成: 2026-09-08 / 関連: ADR-0007, 0008, 0009, 0010, 0011, 0016, 0021

このドキュメントは `docs/plans/PHASE_B_RECONCILIATION.md`（突合ゲートの仕組み）と対になる、
**縦に薄い1本の設計と実測**の記録。`b03_build_observation.py` / `b04_build_cube.py` /
`b05_project_v1.py` と `scripts/migrate/*` がここで説明する対象そのもの
（`PHASE_B_RECONCILIATION.md` はゲートの仕組みだけを説明し、この2つを実装するのは範囲外と
明記していた。本ドキュメントがその続き）。

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
  含まれない。→ **#4 が塞ぐのはロールアップ系の縦線**。
- **#2（`caveat_scope.scope_kind`）**: この縦線は caveat を一切消費しない（`b03`/`b04`/`b05` に
  caveat への参照が無い）。→ **#2 が塞ぐのは応答に caveat を同梱する経路**。

## 3. 構成

| ファイル | 役割 |
|---|---|
| `scripts/b03_build_observation.py` | `data/db/ryuiki.sqlite` の `measurements`（読み取り専用）を `data/db/v2.sqlite` の `observation`（ADR-0007）にする。alias/place 解決、`value_grain`/`period_grain` の展開、検閲分類を行い、`reports/phase_b_fact_slice.md` に要約を書く |
| `scripts/b04_build_cube.py` | `observation` から `observation_agg`（ADR-0011 のキューブ、ADR-0021 で拡張したキー）を作る。`imputation='zero'` の系列だけ |
| `scripts/b05_project_v1.py` | `observation_agg` を v1 の派生テーブル形（`meas_daily`/`meas_month`/`meas_year`）に射影し、`data/db/v1_projection.sqlite` に書く |
| `scripts/migrate/censoring.py` | `value_raw` → `(censoring, censoring_limit)` の5分岐（ADR-0009） |
| `scripts/migrate/period.py` | `measured_on` → `(period_grain, period_start, period_end)`。`period_exceptions.yaml` の宣言だけを例外的に許す |
| `scripts/migrate/period_exceptions.yaml` | `value_grain != period_grain` を許す唯一の宣言表（現状 `atsugi_river_water_quality` の1件のみ） |
| `scripts/migrate/common.py` | b03/b04/b05 共通の土台（`timed_step`/`fresh_sqlite`/`replace_table`/`attach_readonly`。読み取り専用オープンは `scripts/reconcile/common.open_readonly` を再利用） |
| `scripts/reconcile/expected_diffs.yaml` | 「v1 を再現できないが v1 側のバグだと確定しているもの」をキー単位で宣言する（`scripts/b02_derived_compare.py` が読む） |
| `scripts/b02_derived_compare.py --tables meas_daily,meas_month,meas_year` | この3テーブルだけを対象にした部分ゲート |
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
| ベースライン行数 | `meas_daily` 139,530 / `meas_month` 127,491 / `meas_year` 116,076 | `data/db/derived.sqlite` |
| 候補（v2射影）行数 | `meas_daily` 139,532 / `meas_month` 127,493 / `meas_year` 116,076 | `data/db/v1_projection.sqlite`。差は宣言済み差分（§6参照） |

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

## 7. やっていないこと

- 残り30テーブル（`meas_clim`/`zone_year`/`zone_clim`/`sensor_daily`/…、ADR-0011 §「33テーブルの
  行き先」参照）
- `sensor_timeseries` を入力にする縦線（`sensor_daily`/`sensor_hour_month`。申し送り #5 が
  ここで初めて塞ぐ）
- `occurrence` を入力にする縦線（生物系11テーブル）
- `imputation='lod'` 併記（ADR-0009 決定4。今回は `zero` のみ）
- Parquet 化（ADR-0001。D8 参照）
- 公開 ID（`observation_id`）の発行（ADR-0016 Phase C の仕事）
- **既知の負債**: `scripts/b03_build_observation.py` の `write_observation` は
  `common.fresh_sqlite`（ファイル全体を作り直す）で `observation` を書いており、
  「`observation` はこのスクリプトの単独所有」を前提にしている。ADR-0007 は
  `measurements` と `sensor_timeseries` を**同じ** `observation` に統合すると
  明言しているため、`sensor_timeseries` を入力にする次の縦線では
  `write_observation` をファイル全体作り直しから `observation` テーブル単位の
  作り直しに変える必要がある——b04 が `observation_agg` に対して既に採っている
  パターン（`common.replace_table`）と同じ形。今回はコードを変えない。

## 8. 次の一手（オーナーの方針）

- (a) `◯未満` の下限反映で動いた13セル（`expected_diffs.yaml` に宣言した12行由来。
  `meas_daily` 2件・`meas_month` 2件・`meas_year` 9件の差分として波及）は、**zero→lod 切替の
  前に**単独で確認できる状態にしてある（`scripts/reconcile/expected_diffs.yaml` に理由・実測値
  つきで記録済み）。
- (b) 次の縦線は `sensor_timeseries` 系（`sensor_daily`/`sensor_hour_month`）。そこで初めて
  申し送り #5（原表記スケール単位。×10スケールの7単位）が着手判定を塞ぐ。
