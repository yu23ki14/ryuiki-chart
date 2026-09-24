# Phase B P-1b: 土地利用（landuse_watershed / landuse_change）— observation の3本目の出典

対象: ADR-0016 の Phase B / 状態: **完了（`landuse_watershed`/`landuse_change` の2表。
`data/db/derived.sqlite` 残り1表〔`watershed_rollup`〕を残すのみ）**
作成: 2026-09-24 / 関連: ADR-0005（出典の版）、ADR-0007（observation）、ADR-0010（指標）、
ADR-0011（キューブ・行き先）、ADR-0021（キューブの鍵）、ADR-0022（region_id・
source_regions の consumer 分離）、`docs/plans/PHASE_B_FACT_SLICE.md`（縦線の土台）、
`docs/plans/PHASE_B_RECONCILIATION.md`（突合ゲート §11）

## 1. 設計判断（オーナー決定。Fable レビュー済み）

`docs/plans/remaining_tables_survey.md` は「landuse_watershed/landuse_change は
observation を経由しない静的な地理データの転記で、`place` の属性テーブルとして
置くのが実体に合う」と提案していた。**オーナーはこれを却下し、ADR-0011 の宣言
（`cube_observation`）どおり observation（ADR-0007 原則2「出典が既に集計値を
配っている場合は variable/grain/stat に分解する」）を採用した。** 理由: 年で
変わる量（土地利用は2006年版・2016年版の2時点しか無いが、将来の版が増えうる）を
`place` の属性にすると、ADR-0006/0007/0011 が既に禁じている「新しい年版が来たら
列が増える」形に戻ってしまうため。

決定の要点（`o2_p2_decisions.md`「P-1b（土地利用）」節・`p1b_brief.md` より）:

1. **主語 = watershed の place**（`place_kind='watershed'`。P-1a
   `scripts/registry/build_place.py` の watershed 節が既に登録済みの377件を
   `place_source_ref(source_id='watershed_meta.watershed_id')` で引く。新規には
   作らない）。
2. **指標は区分ごとに2つ**: 面積（km2）とセル数（`n_cells`、count）。
   `observation` に「n」（件数）の列が無いため、セル数を面積とは別の
   `variable` にした（「発明が少ない」というオーナーの表現どおり、新しい列を
   足すより既存のスキーマ〔1行1値〕に収まる形を選んだ）。
3. **期間は `period_grain='year'`**（2006年/2016年の暦年、`period_raw` は
   `'2006'`/`'2016'` の文字列そのまま）、**`obs_stat='sum'`**（出典が既に
   集計済みの値を配っているため、ADR-0007 原則2どおり `stat` として持つ。
   区分の面積・セル数のどちらも「格子を数え上げた総量」という意味で `sum`）。
4. **region は出典の宣言から決める**（ADR-0022 決定3の2つ目の実装。
   occurrence〔ADR-0025〕に続き、observation 側で初めて出典由来の region を
   使う）。watershed の place は `common` スコープなので `place.region_id` は
   常に `NULL`（ADR-0022 決定1）——place 経由では地域を決められないため。
5. **2006年版と2016年版でコード体系が違う**（§2実測）。`variable_alias.csv` の
   `dataset` を版付き（`nlni_l03b_landuse_by_watershed@2006`/`@2016`）にする
   ——ADR-0005「同じ出典に複数版が同居する」の実例。同じ日本語名を持つ区分
   （10区分）は年をまたいで同じ `variable_id` を共有させ、`9 幹線交通用地`
   （2006のみ）と `0901 道路`/`0902 鉄道`（2016のみ）は別の `variable_id` に
   する（§4）。
6. **`delta_km2` の合計は v1 でも厳密に0にならない**（実測 `sum=-0.000020`。
   `derived_baseline.json`）。`--tolerance` で吸収する想定だったが、実際には
   使わずに完全一致した（§6）。

## 2. 実測: 2006年版と2016年版のコード体系の違い

`data/processed/nlni_l03b_landuse_by_watershed.csv`（L1。`web/scripts/
build-geo.mjs:71-98` が読んでいるのと同じファイル、ヘッダ含め4,859行 =
データ4,858行）を実測。列は `source_id, source_ref, data_year, watershed_id,
water_system_code_old, water_system_name_ja_estimated, landuse_code_raw,
landuse_name_ja, n_cells, area_km2`。`source_id` は全行 `nlni_l03b_landuse_by_
watershed`（定数）、`source_ref` は年版ごとに異なる URL フラグメント
（`#L03-b-06`/`#L03-b-16`）。

```
年別行数: 2006年版 2,398行 / 2016年版 2,460行
watershed_id の distinct 数: 377（registry.place の watershed 件数と一致）
(watershed_id, landuse_code_raw, data_year) の重複: 0件
```

区分（`landuse_code_raw` → `landuse_name_ja`）:

| 2006（11区分） | 2016（12区分） |
|---|---|
| `1`=田 | `0100`=田 |
| `2`=その他の農用地 | `0200`=その他の農用地 |
| `5`=森林 | `0500`=森林 |
| `6`=荒地 | `0600`=荒地 |
| `7`=建物用地 | `0700`=建物用地 |
| `9`=幹線交通用地 | `0901`=道路 / `0902`=鉄道 |
| `A`=その他の用地 | `1000`=その他の用地 |
| `B`=河川地及び湖沼 | `1100`=河川地及び湖沼 |
| `E`=海浜 | `1400`=海浜 |
| `F`=海水域 | `1500`=海水域 |
| `G`=ゴルフ場 | `1600`=ゴルフ場 |

10区分は日本語名が完全一致（1文字も違わない）。`9 幹線交通用地` だけが
2016年版で `道路`/`鉄道` の2区分に分割されている（国土数値情報 L03-b の
区分定義そのものの変更で、収集・前処理の誤りではない）。

## 3. 作ったもの

### variable（`registry/variable.yaml`、theme=`landuse`）

区分13種（10共有＋`幹線交通用地`/`道路`/`鉄道`）× 2指標（面積・セル数）＝
**26変数**を新設した（`common:variable:landuse.<slug>` / `..._n_cells`）。
`name_ja` は CSV の `landuse_name_ja` を1文字も変えずに転記した（面積側。
`landuse_change` の `GROUP BY watershed_id, landuse_name` がこの文字列その
ものをキーにするため——1文字でも変えると v1 と違うグループ化になる）。
`unit_id` は面積=`common:unit:km2`、セル数=`common:unit:count`（どちらも
既存の unit を再利用。新設なし）。`default_stat="sum"`。`higher_is_worse`は
「土地利用の増減の良し悪し」が自明でないため `null`（推測で埋めない）。

### variable_alias（`registry/variable_alias.csv`）

区分13種 × 年版（10区分は2年分、3区分は1年分）× 指標2つ＝**46行**を追加
（11+12=23区分×年 × 2指標=46）。`alias` は `f"{landuse_code_raw}:area_km2"`/
`f"{landuse_code_raw}:n_cells"`（CSVの生コードに指標名の接尾辞を付けた文字列。
新しい命名規則だが、レジストリ内部のキーでしかなく他の画面・APIには出ない）。
`dataset` は `nlni_l03b_landuse_by_watershed@2006`/`@2016`。`source_id` は
CSV の `source_id` 列と同じ定数。`stat="sum"`, `grain="year"`。

### `scripts/migrate/source_regions.yaml` の `consumer` 分離

`sources:` の各エントリに `consumer`（`occurrence`|`observation`）を足した
（省略時の既定は `occurrence`。後方互換）。`nlni_l03b_landuse_by_watershed`
（region_id=jp-14, expected_row_count=4858, consumer=observation）を追加。
`scripts/migrate/source_regions.py` の `load_source_regions(path, consumer=...)`
がこの値で `sources`/`regions` を絞り込む——**この絞り込みが無いと、
`scripts/b06_build_occurrence.py`（occurrence 側の消費者）が「自分が使って
いない土地利用の宣言」を未使用宣言として誤検出して止まってしまう**
（P-1b オーナー決定3・`source_regions.py` モジュール docstring 参照）。
`b06_build_occurrence.py` の呼び出しは `consumer="occurrence"` を明示する
ように変更した（挙動は変わらない。実データで823,692行が変わらず通ることを
確認済み——§6）。

### `scripts/b03_build_observation.py` に `_ingest_landuse`（3本目の取り込み）

`data/processed/nlni_l03b_landuse_by_watershed.csv` を Python の `csv`
モジュールで直読みする（`measurements`/`sensor_timeseries` と違い SQL
テーブルではないため、`ryuiki.sqlite` の ATTACH は使わない。`registry.sqlite`
だけを `reg` として ATTACH し、`place_source_ref`/`variable_alias` を
Python の辞書に一括プリロードしてから CSV を1行ずつ処理する）。CSVの1行
から2つの `observation` 行（面積・セル数）を作る。`source_table`は
`"nlni_l03b_landuse_by_watershed"`（CSVの`source_id`列と実データでは同じ
文字列になるが、コード上は独立——CSVの`source_id`はalias/regionの解決キー
としてだけ使う。テストがこの2つを混同していないことを確認している）。
`source_row_id` は `f"{CSVの行番号}:area_km2"`/`f"{...}:n_cells"`
（CSVの行番号を基本形にしつつ、1つのCSV行から2つのobservation行を作る
ため指標名を接尾辞にした——ブリーフの「source_row_idはCSVの行番号」を
文字どおり守りつつ一意性制約〔`(source_table, source_row_id)`〕を満たす
ための実装上の必然）。`censoring`は常に`'none'`、`is_synthetic=0`
（実在の政府統計であり合成データではない）。

未知の `source_id`（source_regions.yaml に無い）は即座に
`UnknownSourceRegionError`で止まる（`b06`の`_ingest`と同じ判断）。
watershed_idが解決できない行・alias（面積/セル数のどちらか）が解決できない
行は、件数と実例を集めてから`MigrationError`で止まる（黙って捨てない）。

**b04（キューブ）は無変更。** `place_kind='watershed'`はADR-0011の事前計算
の範囲（`{site, watershed, mesh3}`）に含まれ、`period_grain='year'`の
observation は既存の出典配布年次セル経路（`_year_source_stats_sql`/
`_year_source_expand_sql`）をそのまま通る。実測で確認済み（§5）。

### `scripts/b05_project_v1.py` に `landuse_watershed`/`landuse_change`

`watershed_place_lookup`（`place_id -> watershed_id`。`place_lookup`の
watershed版）と、年版ごとの`landuse_alias_lookup_{year}`（`_alias_lookup_sql`
を既存のまま再利用。datasetが違うだけ）を作る。`landuse_watershed`は
面積のキューブセルと同じ`(place_id, period_start, grain, stat)`を持つ
セル数のキューブセルを`JOIN`し、`alias`文字列から`landuse_code`を復元
（`substr(alias, 1, instr(alias, ':') - 1)`）、`reg.variable.name_ja`から
`landuse_name`を引く。**`area.period_start = '{year}-01-01'`の絞り込みが
必須**——これが無いと、年をまたいで共有する`variable_id`（10区分）が
2006年版のalias表を2016年のセルにも誤って一致させてしまう（akeyは
`variable_id|grain|stat|unit_id`だけで年を含まないため）。`landuse_change`
はv1と同じSQL（`SUM(CASE WHEN year=... THEN area_km2 ELSE 0 END)`を
`watershed_id, landuse_name`でグループ化）を`landuse_watershed`の
一時テーブルに対して実行する。

`assert_alias_tuple_maps_to_single_dataset`（既存の検証。同じ
`(variable_id, grain, stat, unit_id)`が`measurements`と`sensor_timeseries`
の両方のaliasに対応していないことを確認する）は、土地利用の版付きdataset
を**意図的に除外**するオプション（`dataset_exclude_prefix`）を足した——
土地利用は同じtupleを2006/2016の2つのdatasetにまたがって**意図的に**
再利用する設計（区分の共有）であり、この検証が守るべき不変条件ではない
ため。除外しても、この検証の本来の目的（measurements/sensor_timeseries
間の排他）は変わらず働く。

### `registry/caveat.yaml` に definition_change を1件（Phase A 以降初めての新規注記）

`landuseDefinitionChange`（`kind=definition_change`）を追加し、
`landuse_watershed`/`landuse_change`の2表にスコープした
（`scripts/registry/build_caveat.py`の`LANDUSE_TABLES`/`LANDUSE_CAVEATS`）。
`registry/caveat.yaml`冒頭のコメントに「Phase A以降ここだけが新規」と明記
した（既存14件はPhase Aの移設のみで新規に足していない、という既存の方針
に対する唯一の例外であることを明示するため）。

## 4. なぜ n_cells を「別の変数」にしたか（却下した代替案）

**代替案A**: 面積と同じ`variable_id`のまま、`obs_stat`だけ`'count'`に
変えた別のobservation行にする（ADR-0021が既に`obs_stat`をキーの一部に
しているので、同じ`variable_id`のまま複数の`obs_stat`を持てる設計は
既存の仕組みに乗る）。
**却下理由**: オーナー決定が明示的に「別の変数にする」と指定している
（`o2_p2_decisions.md`）。面積とセル数は単位が違う量（km2 vs count）で
あり、同じ`variable_id`に2つの物理量を持たせるのは`variable`レジストリ
の「1 variable = 1 quantity_kind」という前提（`registry/unit.yaml`の
`quantity_kind`列）から外れる。区分ごとに2つの独立したvariableを作る方が、
`variable`テーブルを見ただけで「これは面積」「これはセル数」と分かる
（`obs_stat`まで見ないと物理量が分からない設計より読みやすい）。

## 5. 実測: b03/b04/b05の実行時間・行数（土地利用を足す前後）

`.venv/bin/python3`単独実行、2026-09-24実測（実行のたびに数秒変動する）:

| 段 | 足す前 | 足した後 | 差分 |
|---|---:|---:|---:|
| `observation`総行数 | 1,041,003 | 1,050,719 | +9,716（4,858行×2指標） |
| `observation_agg`総行数 | 1,993,816 | 2,022,964 | +29,148（9,716セル×3統計量〔mean/min/max〕。出典配布年次セルは`_year_source_expand_sql`がstat3種を展開するため） |
| b03実行時間 | 27.5s | 23.3s | ほぼ同等（実行ごとの変動の範囲内） |
| b04実行時間 | 41.4s | 39.3s | 同上 |
| b05実行時間 | 44.5s | 44.3s | 同上 |
| v1形テーブル数 | 11 | 13 | +2 |
| v1形テーブル行数合計 | 753,629 | 761,391 | +7,762（`landuse_watershed`4,858 + `landuse_change`2,904） |

## 6. 受け入れ結果（実測。/code-review 12件の反映後に5系統のゲートを再実行）

1. **observation系13表**: `b02_derived_compare.py --candidate
   data/db/v1_projection.sqlite --tables meas_daily,meas_month,meas_year,
   meas_clim,site_var,var_catalog,sensor_daily,sensor_hour_month,rain_daily,
   zone_year,zone_clim,landuse_watershed,landuse_change` →
   **b02自身の終了コード0**（パイプを経由せず直接確認）、**一致7 / 宣言済み
   差分のみ6 / 不一致0**（宣言済み差分は既存の18キーのまま、増減0）。
2. **occurrence系13表**: `b08`（`b06→b09→b07→b08`の順で実データを再実行）
   → `--candidate data/db/v1_projection_occurrence.sqlite --tables
   org_norm,org_group_year,effort_year,species2,species_year2,species_month,
   mesh_year,mesh_all,mesh_species,species_mesh_year,org_watershed,
   org_watershed_year,ias_species` → **終了コード0、一致11 / 宣言済み差分
   のみ2 / 不一致0**（既存の宣言のまま）。
3. **文書3表**: `b10` → `--candidate data/db/v1_projection_documents.sqlite
   --tables doc_series,doc_series_meta,quality_monthly` →
   **終了コード0、一致3**。
4. **watershed_meta**: `b11` → `--candidate data/db/v1_projection_place.sqlite
   --tables watershed_meta` → **終了コード0、一致1**。
5. **レッドリスト2表**: `b12` → `--candidate data/db/v1_projection_taxon.sqlite
   --tables redlist_map,redlist_change` → **終了コード0、一致2**。
6. **`landuse_watershed`/`landuse_change`は値もstorage classもv1と完全一致**:
   `PRAGMA table_info`の宣言型は両テーブルとも v1 と1列ずつ完全一致（`landuse_
   change`の`km2_2006`/`km2_2016`/`delta_km2`は**型を宣言しない**——v1が
   `CREATE TABLE ... AS SELECT`〔型無し宣言〕で作っているため。REALと宣言
   すると INSERT 時に強制変換され、storage classがv1とずれる、というのが
   `/code-review` 指摘5。`scripts/b05_project_v1.py`の`_CREATE_SQL
   ["landuse_change"]`のコメント参照）。**値の一致**
   （b02が見る数値比較。`typeof()`の違いは吸収して比較する）と**storage
   classの一致**は別の検証で、後者は`typeof()`を直接比較した:
   `km2_2006`（v1: integer 506 / real 2398、候補: 同じ）・`km2_2016`
   （v1: integer 444 / real 2460、候補: 同じ）・`delta_km2`（v1/候補とも
   real 2904）——**2,904行全件で`typeof()`が一致**（JOINして直接比較、
   不一致0件）。`km2_2006`/`km2_2016`のinteger行は「その年に該当区分の
   行が1件も無いため`SUM(CASE...ELSE 0)`が整数リテラルの0だけを合計する」
   ケース（§1決定6・§2）。`--tolerance`は使わず、数値・storage classとも
   完全一致した。
7. **既存11表・occurrence13表・文書3表・watershed_meta・レッドリスト2表の
   値は正準化sha256で完全一致**: 観測系11表は
   `reconcile.common.compute_fingerprint`で「土地利用なし」候補（`--source-
   regions-yaml`/`--landuse-csv`を空フィクスチャにして再実行）と「土地利用
   あり」候補を突き合わせ、**全11表で完全一致**（`meas_daily=
   700094a0f8f2b...`等、`phase-b/sensor-slice`以来の値とも一致）。
   occurrence13表・文書3表・watershed_meta・レッドリスト2表は、
   `/code-review`対応で`scripts/b06_build_occurrence.py`の`consumer=
   "occurrence"`明示以外のコード変更が無いこと（`b07`/`b08`/`b09`/`b10`/
   `b11`/`b12`は無変更）を確認したうえで、上記1〜5の各ゲートが**v1
   （`derived.sqlite`）と行レベルで完全一致**することを実データで確認した
   ——b02の「一致」判定自体が正準化sha256での行レベル比較であり、v1と
   一致していれば「変更前のこのタスクの状態」とも一致している。
8. **r01のfull buildと`--check-fresh`**: 実データで実行し、どちらも成功
   （`registry: 111 variables / 200 variable_alias / 222 caveat`。
   `--files-only`でも同じ111/200/15〔cells.notes分を除く〕）。
   `web/scripts/build-registry-ts.mjs`で`generated.ts`/`generated-client.ts`
   を再生成し、diffが意図どおり（26変数・46 alias・1 caveat・2
   caveat_scopeの追加のみ、既存行は1行も変わらず）であることを確認した。
   `web/src/lib/registry/generated.test.ts`のハードコード件数
   （`caveat`14→15）・`web/src/lib/ai/caveats.test.ts`のインライン
   スナップショット・`web/src/lib/ai/prompt.ts`の`CaveatKey`網羅チェック
   （`satisfies Record<CaveatKey, true>`、新規caveatキーの追加漏れを
   コンパイル時に検出——実際にここで検出して直した）を更新し、
   `pnpm test`（71件）・`pnpm exec tsc --noEmit`・`pnpm run lint`
   （既存の無関係な警告3件のみ、エラー0）で確認した。
9. **pytest全緑**: `.venv/bin/python3 -m pytest scripts/tests`で
   **499件全緑**（既存475件＋本タスクで足した24件）。
10. **古いSQLite・原本の無い環境**: `git clone`で一時ディレクトリに複製し、
    Python 3.10.12（本機に3.13が無かったため。SQLite同梱バージョンは
    3.37.2で`MIN_SQLITE_VERSION`〔3.43〕未満——「古いSQLite」と「原本
    無し」を同時に検証できた）のフレッシュvenv（`requirements.txt`のみ）で
    実行し、**384件pass・101件skip（バージョンゲートの対象）・失敗0**、
    `r01 --files-only`成功、CI相当の宣言ファイル構造検証（`source_regions.
    yaml`含む）すべてOK、`generated.ts`の`git diff --exit-code`も0。
11. **b03/b04/b05の実行時間**: §5参照（`/code-review`対応後も有意差なし）。

## 7. 既知の負債・未決

- **`n_cells`/面積の`variable`命名**（`landuse.<slug>`/`landuse.<slug>
  _n_cells`という接尾辞規則、`alias`の`"<code>:area_km2"`/`"<code>:n_cells"`
  という区切り文字規則）は、この実装で新規に決めた命名規則であり、
  ブリーフに明示されていない実装細部。オーナー未確認。
- **variable_alias.csvの`dataset`が版付き（`<source>@<year>`）になる
  パターンは、`docs/plans/PHASE_B_INTAKE.md`に暫定の接続点として記録
  した**（ADR-0005が「同じ出典に複数版が同居する」ケースの正式な設計を
  Phase C まで持ち越しているため、恒久的な設計ではない）。
- **`source_regions.yaml`の`consumer`は必須キーにしていない**（省略時は
  後方互換のため`occurrence`扱い。`validate_source_regions_shape`は
  書かれている場合だけ`CONSUMER_CODES`の値を強制する）。3つ目の消費者を
  足す人が`consumer`を書き忘れると、既定の`occurrence`に紛れ込む——
  YAMLのヘッダで明示的に警告しているが、機械的には強制していない。
