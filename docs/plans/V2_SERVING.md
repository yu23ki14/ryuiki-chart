# v1 の撤去とキューブ直読みへの移行（PR-0〜PR-6）

対象: Issue #48（親: #27「Phase B のあと: 残りの作業」／対象: #28「本番の集計・D1 シードを
v2 につなぐ」＋ #41「v1 パイプラインの廃止計画を立てる」）
状態: **PR-0 進行中**（PR-1〜PR-6 は未着手）
作成: 2026-09-26 / 関連: ADR-0001, 0009, 0011, 0014, 0016, 0021, 0024, 0025, 0026, 0027,
0028, **ADR-0029（新設）**, **ADR-0030（新設）**

このドキュメントは、外部アドバイザー（Fable サブエージェント）による棚卸し・実測
（2026-09-26）とオーナーの決定を、セッションをまたいでも消えない形でリポジトリに残す
もの。`docs/plans/PHASE_B_OCCURRENCE.md` 等と同じ位置づけで、Issue #48 本文の転記ではなく、
設計・決定事項・受け入れ基準の正本として読めるように書き直してある。Issue #48 自体は
この文書の作成元として残る。

Phase B（ADR-0016）は「v1 の数値を再現できることを受け入れ基準にする」段階だった。本移行
（Issue #48）はその先——**再現できたキューブ・レジストリを配信の正にして、v1 の派生33表と
旧 JS パイプラインを撤去する**段階で、ADR-0016 の Phase A〜D のどれにも直接対応しない
（Phase C の ID 付け替え・Phase D のマニフェスト化とは別の軸）。位置づけの整理は
ADR-0029 に書く。

## 1. 背景

`docs/adr/README.md` §1(a) が指摘した「派生33テーブルは画面の形をしている」という診断
（ADR-0011）に対し、Phase B（`scripts/b03`〜`b12`）は v1 を再現するキューブ
（`observation_agg`/`occurrence_agg`）と v1 形への射影を両方生成する形で進めてきた。
射影経由で v1 の数値を再現できることは `scripts/b02_run_all_gates.py`（33表全数、
`docs/plans/PHASE_B_RECONCILIATION.md`）で確認済みだが、**画面・API・AI ツールは今も
v1 の派生表（`web/scripts/build-derived.mjs` が書く `derived.sqlite`）を読んでいる**。
キューブは「再現できることを確認しただけ」で配信には使われていない。

2026-09-26、アドバイザー（Fable）が次を実測した（詳細は §8「付録」）。

- 派生33表のうち固定経路で読まれているのは24表（残り9表は SQL 無し・呼び出しゼロ）。
- D1 に索引を張ったキューブの容量見積もり（`observation_agg` 約680MB・slim版約260MB、
  `occurrence_agg` 約140MB）。
- 代表的な問い合わせをキューブに直接投げた場合の応答時間（年系列25ms〜mesh1年分70ms）。
- 重い全表集計（指標カタログ371ms・地点×指標499ms・種カタログ786ms）だけは事前計算が要る。

これを受けてオーナーが「v1 のレガシーは一切残さない」方針で確定した（§2）。

## 2. オーナーの決定（2026-09-26）

1. **v1 のレガシーは一切残さない。アーキテクチャ的に一番きれいな状態にする。**
   #28 の案1（v1 形の射影を D1 に入れる）は採らず、案2（キューブ直読み）を最後までやる。
2. 画面の定量下限未満を含む値は **`value_lod`**（定量下限の値を代入した系列。
   `observation_agg.value_lod`、ADR-0009 決定4）を見せる。注記（`registry/caveat.yaml` の
   `censored`）も系列に合わせて書き換える。
3. **合成データ（`is_synthetic=1`）は本番に出さない。** v2 のファクトから除き、合成データ
   しか表示しない画面（品質・介入・意思決定・ペア測定のデモ）は撤去する。
4. **本番（Cloudflare D1・Workers）への反映は最後にまとめて1回。** 途中の PR は main に
   入れるだけで本番には出さない——**移行が終わるまで main を本番にデプロイしない**
   （途中の main は本番 D1 に無い新しい表を読むため）。最後の PR（PR-5）に本番切り替えの
   手順書を付け、オーナーが実行する。
5. 座標の一般化はしない（[ADR-0028](../adr/0028-no-coordinate-generalization.md)、既定どおり）。

## 3. 目標のアーキテクチャ

### 3.1 D1 に入れるもの・落とすもの

| 区分 | 表 | 状態 |
|---|---|---|
| キューブ | `observation_agg` / `occurrence_agg` | 入れる（配信の正） |
| レジストリ | `unit` / `variable` / `variable_alias` / `place` / `place_source_ref` / `taxon` / `caveat` / `caveat_scope`（既存 `web/src/db/schema-registry.ts`）＋ 新設4表（§3.2） | 入れる |
| summary（宣言的集計） | 指標カタログ・地点×指標・種カタログの3表（新設、§3.5） | 入れる |
| v2 に相当物の無い原本表 | `cells` / `notes` / `documents`（`web/src/db/schema.ts` 既存）・`sites`（同）・`source_registry`（同）・Tier 1 の5表（`protected_areas` / `vegetation_polygons` / `mammal_mesh` / `wildlife_sightings` / `river_segments`、同） | 入れる |
| L2 | `observation` / `occurrence` / `occurrence_place` | **入れない**（ADR-0001「D1 は L3 の配信キャッシュ」） |
| 派生33表 | `meas_*` / `zone_*` / `sensor_*` / `species*` / `org_*` / `mesh_*` / `redlist_*` / `doc_series*` / `quality_monthly` / `landuse_*` / `effort_year` / `ias_species` / `var_catalog` / `site_var` / `watershed_rollup` 等 | **落とす**（PR-5） |
| その他落とすもの | `measurements` / `sensor_timeseries` / `organism_records` / `taxa` / `redlist_assessments`（`web/src/db/schema.ts` 既存）・合成データ系表（`decisions` / `interventions` / `quality_transitions` / `observers` / `events` / `event_observers`） | **落とす** |
| PR-6 送り | `water_*`（6表）・`vocab_*`（4表）・`extraction_log` | PR-6（任意）で落とす |

容量見積もり（実測）: 今のローカル D1 1,295MB → 約500〜900MB。D1 の上限（10GB、込み容量
5GB）に余裕がある（§8）。

### 3.2 新たに D1 に要るレジストリ

- `place_relation`（ゾーン・流域の JOIN。ADR-0006）
- `place_watershed`（`occurrence_place` の watershed 解決結果を軽量に運ぶ、O-2b と対）
- `taxon_assessment`（RL・外来種。除外7種は r01 で `in_scope` 列にする。今は
  `registry.sqlite` にのみあり D1 には無い——`scripts/registry/build_taxon_assessment.py`）
- `taxon` の `canonical_binomial` / `class` / `family` / `taxon_group`（今は
  `registry.sqlite` の `taxon` にあるが `web/src/db/schema-registry.ts` の `taxon` には
  無い）＋ 新設 `vernacular_name_en`

いずれも `web/src/db/schema-registry.ts`（現状8テーブル、`unit`/`variable`/
`variableAlias`/`place`/`placeSourceRef`/`taxon`/`caveat`/`caveatScope`）への追加として
実装する。`web/src/db/schema-cube.ts`（キューブ2表＋索引）は新設。

### 3.3 索引

Drizzle の schema で宣言する。

- `observation_agg(variable_id, place_id, grain, stat, period_start)`
- `observation_agg(place_id, variable_id, grain)`
- `occurrence_agg(taxon_id, period_start)`
- `occurrence_agg(place_id, period_start)`

キューブの次元キー自体は既存の決定どおり（`observation_agg` は
`region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain,
period_start, period_end, grain, input_grain, stat` の12列、ADR-0021 の
2026-09-24追記〔ADR-0009 決定4を反映〕。`occurrence_agg` は `region_id, source_id,
place_id, place_kind, taxon_id, grain, period_start, period_end` の8列、
ADR-0025 D2）。索引はこの上に問い合わせパターンに合わせて張る。

### 3.4 問い合わせ層 `web/src/lib/cube/`（新設予定、`web/src/lib/queries.ts` の後継）

「画面の形の表」を作らない。「系列」を単位にする。

- `db.ts`: D1 と better-sqlite3 の2実装（テストと差分計測のため）。
- `series.ts`: 系列＝`(variable_id, obs_stat, unit_id, value_grain, input_grain)`。
- `observation.ts`: `queryCells(spec)` / `summarize(spec, by)`（月別平年値・ゾーン・
  流域の再集計）。
- `occurrence.ts`、`catalog.ts`（summary 表を読む）。
- `envelope.ts`: ADR-0014 の封筒（単位・coverage・imputation・provenance・caveats）。
- `caveats.ts`: v2 のキーで注記を引く（既存 `web/src/lib/ai/caveats.ts` とは別物。
  `caveat_scope` を v2 のキーで引く層。既存の `caveats.ts` はこの上に乗るかたちで
  再配線する）。
- `imputation` はクエリのパラメータ（画面は `lod` 固定、AI/API の封筒は
  `value_zero`/`value_lod` の両方を返す）。`IN (...)` はやめて JOIN にする——D1 の
  バインド100個の制限（`web/src/lib/db.ts` の `queryChunked`）は GROUP BY を伴う
  集計クエリには使えない（危険16件 #7）。

### 3.5 summary 表（宣言的集計、ADR-0011「単一キューブ＋宣言的集計定義」の最初の実装）

重い全表集計（指標カタログ・地点×指標・種カタログ）だけを事前計算する。ほかの問い合わせは
問い合わせ時に計算する（§8 実測: 15〜70ms）。

`aggregations/serving.yaml`（新設予定、宣言）→ `scripts/b13_build_summary.py`（新設予定）
→ `summary_variable_catalog` / `summary_place_variable` / `summary_taxon_catalog`
（表名は仮。b13 実装時に確定）の3表。**キューブの再集計だけ・L2 を読まない・指紋付き**
（`scripts/migrate/common.py` の `record_stage_fingerprint`/`assert_stage_fingerprint_fresh`
と同じ機構に乗せる）。

## 4. v1 が無くなったあとの検証（ADR-0027 の層2・層3を改定）

詳細設計は **[ADR-0029](../adr/0029-v1-removal-and-verification-handoff.md)** に書く。
要点だけここに記す。

1. **キューブの自己不変条件を残し、強める。** b05/b08 に同居しているキューブを守る検証
   （`verify_hourly_daily_rollup`・`assert_alias_is_function`/`assert_unit_raw_is_function`
   〔`scripts/migrate/v1_projection_checks.py`〕・流域の保存則〔b08〕）は、**射影を消す前に**
   b04/b07/b09 へ移す。無作為抽出したセルを `observation` から独立に再計算して一致を見る
   検査を b04 に足す。
2. **凍結スナップショット**（ADR-0027 層2の後継）: `web/serving_queries.yaml`（新設予定）に
   画面・AI が実際に投げる問い合わせを列挙する。縮小サンプル（`data/sample/`）で作った v2 に
   問い合わせ層を通して流し、`data/sample/serving_snapshot.json`（新設予定）をコミットする。
   CI の `sample-gate` ジョブは「v2 構築 → スナップショットの突合 →
   `git diff --exit-code`」に変わる。**免除リスト（expected_diffs）は持たない**——
   スナップショットの更新そのものを宣言として扱う。
3. **全量の実行証明**（ADR-0027 層3の後継）: `scripts/b00_run_full_gate.py` は、
   r01→b03…b13 → 自己不変条件 → `serving_queries.yaml` を全量で実行し、
   `reports/serving_fingerprint.json`（新設予定。問い合わせごとの行数・値の和・hash、
   前回との差分の分類）を書く形に付け替える。
4. **差分カウントの道具**（#28 の閉じる条件）: `web/scripts/serving-diff.mts`（新設予定）。
   同じ `serving_queries.yaml` を v1 経路（今の `web/src/lib/queries.ts`）と v2 経路
   （`web/src/lib/cube/`）の両方で、旧表と新表が同居するローカル D1 に流し、問い合わせごとの
   差を `reports/serving_switch_diff.md`（新設予定）に書く。既知の差分に分類される6系統
   （宣言済み差分20件・日割り・流域のメモ化の癖・Sirosporium・合成データの除外・雨量の
   `/10`）は §6「決定事項」6・10、§8 付録参照。それ以外の差分が出たら問い合わせ層のバグ。
5. ADR-0027・0016・0009・0024・0026・0011 には、この PR（PR-0）では本文の追記をしない。
   各 PR で実際に値が動く／検証の分担が変わるときに書く。ただし ADR-0029/0030 を参照する
   一行ポインタは、既存の「追記」の書式に合わせて6本とも足した（本 PR）。

## 5. 移行計画（PR の積み上げ。本番には最後まで出さない）

各節の「状態」は PR ごとの進捗（未着手／進行中／レビュー中／マージ済み）を表す。

### PR-0 前提整備（値は動かない）

状態: **進行中**（本ドキュメント・ADR-0029/0030 の起票が対象。スキーマ・パイプラインの
コード変更は未着手）

- `web/src/db/schema-cube.ts`（新設予定。キューブ＋索引）。`web/src/db/schema-registry.ts`
  （既存）に §3.2 のレジストリ表・列を追加し、`pnpm run db:generate`。
- `web/package.json`（既存）に `build:v2`（新設予定のスクリプト。r01→b03→b04→b06→b09→b07）
  を足す。`web/scripts/seed-d1-local.mjs`（既存。今の `SOURCES` は
  `ryuiki`/`cells`/`derived`/`registry` の4本）の入力に `v2.sqlite` を足し、
  **`pipeline_fingerprint`・列集合で古い `v2.sqlite` を拒否する**
  （`scripts/migrate/common.py` の `pipeline_fingerprint` 機構、既存）。
  `web/scripts/docker-entrypoint.sh`（既存）の判定を「v2 の指紋が新鮮か」に変える。
- **Docker の Python の SQLite を 3.43 以上にする**（`web/Dockerfile` は
  `node:22-bookworm-slim` ベースで `python3`/`python3-yaml` を apt から入れており、
  bookworm の python3 に同梱される SQLite は 3.40 系——推測・高確度。3.43 未満だと
  b04/b07 が `require_sqlite_version()` で止まる、ADR-0021 D7）。
- **`scripts/b03_build_observation.py`/`scripts/b06_build_occurrence.py`（既存）で
  `is_synthetic=1` を除く**（合成データを出さない決定3）。
- ADR-0029/0030 の草稿と、この設計の repo 内の文書（本ファイル）。

### PR-1 問い合わせ層＋差分の道具（値は動かない）

状態: 未着手

- `web/src/lib/cube/*`（新設予定）、`web/serving_queries.yaml`（新設予定）、
  `web/scripts/serving-diff.mts`（新設予定）、vitest（`server-only` を alias で無効化）。
- **`caveat_scope` を v1 のテーブル名のキーから v2 のキー（dataset・variable theme・
  place_kind・source_id）へ付け替える**（`scripts/registry/build_caveat.py` 既存。今は
  `scope_kind='table'`/`scope_ref='measurements'` のような v1 表名で引いている
  ——`web/src/lib/ai/caveats.ts`・`web/src/lib/registry/generated-client.ts` の
  `GENERATED_CAVEAT_SCOPE` が消費側）。やらないと、切り替えた瞬間に AI の注記が黙って消える
  （危険16件 #1）。
- 受け入れ: serving-diff（`imputation=zero`）の差分が既知の系統だけになる表を貼る。変異で
  拾うことを確かめる。

### PR-2 測定値系の切り替え（値が動く）

状態: 未着手

- `/timeseries` / `/sites` / `/sites/[id]` / home、AI の `list_catalog` / `get_timeseries`
  / `get_seasonality` / `get_sites`（`web/src/lib/ai/tools.ts` 既存）を切り替える。
- 既定を `lod` にし、注記は `censoredLod`（`registry/caveat.yaml` の `censored` エントリを
  書き換える、危険16件 #13）。URL の指標キーを `variable_id` にする（alias からリダイレクト）。
  系列の年は `grain`（暦年と年度）を明示する。
- summary の2表（指標カタログ・地点×指標）を b13 で作る。#32-1（ラベル日割りの退役）は
  ここで実現する。

### PR-3a パイプライン（値は動かない）

状態: 未着手

- O-2b（#33、`occurrence_agg` に流域のセル）と、occurrence の月のセルを足す
  （ADR-0025 D2「O-2 への申し送り」、ADR-0026 D4 の後続）。b07/b08 の分割検証を
  grain 族・place_kind ごとに拡張する。
- `taxon.vernacular_name_en` を足す。

### PR-3b 生物系の切り替え（値が動く）

状態: 未着手

- `/biota` / `/map`（mesh・watersheds）/ home、AI の `get_biota_trend` / `get_redlist` /
  `get_overview` を切り替える。
- summary の種カタログを作る。流域のメモ化の癖（ADR-0026）は退役する。

### PR-4 文書・概況の切り替えと、合成デモの撤去

状態: 未着手

- `doc_series*` を `cells`/`notes`（既存、`web/src/db/schema.ts`）からの問い合わせ時の SQL
  にする（v1 のバグ4件は直す、§6 決定事項10）。`overviewStats`/`biotaTotals` を
  summary・キューブにする。
- 品質・介入・意思決定・ペア測定の画面と API（合成データのみ）を撤去する。
  `describe_schema`（`web/src/lib/ai/tools.ts` 既存）はカタログだけにし、
  `web/src/app/api/column`（既存。`EXPLORE_ENABLED` のゲート外、危険16件 #12）にゲートを付ける。
- ここで、web から派生33表と落とす原本表への参照がゼロになる（grep で機械的に確かめる）。

### PR-5 v1 の撤去（値は動かない）

状態: 未着手

- 削除するもの:
  - `web/scripts/build-derived.mjs` / `build-biota.mjs` / `build-geo.mjs`（既存。
    `build-water-geo.mjs`・`copy-geo-assets.mjs` は残す）
  - `scripts/b01_derived_baseline.py` / `b02_derived_compare.py`（`scripts/b02_run_all_gates.py`
    も含む v1 用ゲート） / `b05_project_v1.py` / `b08_project_occurrence_v1.py` /
    `b10_project_documents_v1.py` / `b11_project_place_v1.py` / `b12_project_taxon_v1.py`、
    `scripts/reconcile/` の v1 用の宣言（`projection_manifest.yaml`・
    `adr0011_destinations.yaml`・`derived_keys.yaml`・`expected_diffs.yaml`）、
    `scripts/migrate/v1_projection_checks.py`（検証を§4-1でb04/b07/b09へ移したあと）
  - `scripts/migrate/occurrence_watershed_v1_declarations.yaml`、
    `reports/derived_baseline.json`/`.md`、`data/sample/derived_baseline.json`/`.md`
  - 関連するテスト
- `web/src/db/schema.ts`（既存）から落とす表を消して、DROP のマイグレーションを作る。
  `web/src/lib/table-meta.ts`（既存の `TABLE_ORIGIN`）・`web/src/lib/ai/prompt.ts`
  （既存の `SAMPLE_QUERIES`）・`registry/caveat.yaml`（既存）を掃除する。
- CI（`.github/workflows/ci.yml` 既存）: `sample-gate` をスナップショットに、
  `full-gate-proof-check` を `serving_fingerprint` に変える。`scripts/b00_run_full_gate.py`
  の `PIPELINE_EXPLICIT_FILES`（既存。今も `web/scripts/build-derived.mjs` 等を明示的に
  列挙している）から v1 用パスを落とす——**証明の付け替えと同じ PR で行う**
  （危険16件 #9）。
- **本番切り替えの手順書**（投入 → コードのデプロイ → DROP の順）を `DEPLOYMENT.md`
  （既存）に書く。**DROP のマイグレーションをコードより先に当てると全画面が落ちる**
  （危険16件 #11）ので、その順序をここに明記する。
- #28・#41 を閉じる。

### PR-6（任意）

状態: 未着手

- `water_*`（`waterUtility`/`waterSource`/`waterFacility`/`waterSourceDoc`/`waterFlowEdge`/
  `waterZone`/`waterZoneAssignment`/`waterZoneSourceShare`）/ `vocab_*`
  （`vocabAreas`/`vocabEras`/`vocabIndicators`/`vocabUnits`）/ `extractionLog`
  （すべて `web/src/db/schema.ts` 既存）を D1 から落とす。
- `not_detected` の `value_zero` 例外（ADR-0009 決定4「v1 再現のための時限的な例外」）を
  撤去する。
- `web/src/app/api/nature`（既存、`kind=` クエリ）系を整理する。

## 6. 決定事項（アドバイザーの14件への回答。オーナーの方針に沿って確定）

| # | 論点 | 決定 |
|---|---|---|
| 1 | D1 に L2 を入れるか | 入れない（A案）。`run_sql`（`web/src/lib/ai/tools.ts` 既存）はキューブ・レジストリ・残す原本表に限る |
| 2 | 種の英名・レッドリストの解決 | 種の英名は `taxon.vernacular_name_en`（r01 で決定論的に）。RL は `taxon_assessment`。名前が変わる種数は PR-3b の差分表で数える |
| 3 | 画面・AI/API の代入方式 | 画面は `lod` のみ（注記付き）。AI/API の封筒は `value_zero`/`value_lod` の両方。`half_lod` は出さない（ADR-0009 決定4） |
| 4 | `not_detected` の `value_zero` 例外 | PR-5 の後（PR-6）で撤去する |
| 5 | `above_lod`（透明度26行） | 現状維持（非メンバー＋`aboveLod` 注記） |
| 6 | 雨量の単位不明の推測換算 | **`/10`（v1 の単位不明の推測換算）をやめ、原値に「単位不明」の注記を付ける**（推測で埋めない）。3,654行の表示値が10倍になる |
| 7 | 合成データ | 出さない（オーナー決定、§2-3）。キューブの鍵に `source_id` を足す案は採らない |
| 8 | 画面の指標キー | `variable_id`（alias からリダイレクト）。系列は `(variable_id, obs_stat, value_grain)`。年は `grain`（暦年・年度）を明示する |
| 9 | 月別平年値の系列の混在 | `mean`/`point` の系列を `variable_id` で混ぜる。AI の封筒には系列の内訳を付ける |
| 10 | `doc_series` の v1 のバグ4件 | 直す（label の `\|` 切り出し・`n_warnings`・`col_key` 潰れ・裸列、`docs/plans/PHASE_B_DOCUMENTS.md` §3）。差分は serving-diff で数える |
| 11 | ペア測定（合成） | 画面ごと撤去する（決定7に従う） |
| 12 | `water_*`/`vocab_*`/`extraction_log` | D1 から落とす（PR-6） |
| 13 | summary 表 | 3表を持つ（YAML 宣言、b13） |
| 14 | `describe_schema`/`run_sql`/`/api/column` | `describe_schema` はカタログの表だけ。`run_sql` は残し、対象を更新する。`/api/column` にゲートを付ける |

## 7. 見落としそうな危険（アドバイザーの指摘。実装時に踏みやすい順ではなく指摘順のまま残す）

1. `caveat_scope` のキーが v1 のテーブル名（`web/src/lib/registry/generated-client.ts` の
   `GENERATED_CAVEAT_SCOPE`）。再キーしないと、切り替えた瞬間に AI の注記が黙って空になる
   （PR-1）。
2. b05/b08 の中にキューブを守る検証がある。射影を消す前に移す（§4-1）。
3. Docker の SQLite の版（3.40 と推測）。3.43 未満では b04/b07 が止まる（PR-0）。
4. 手元の `data/db/v2.sqlite` は PR #26 より前の13列キー（`imputation`/`value`）のまま
   古い可能性がある。seed の入力にする前に、指紋で拒否する（PR-0）。
5. 単位の落ち方: day セルの27%・month セルの68% が `unit_id` NULL。v1 は `unit_raw` を
   引き戻して表示していた。`variable_alias.unit_id ?? variable.unit_id` へのフォールバックが
   v1 の表示と一致することを、不変条件にしてから切り替える。
6. `species_month` と流域のセルは v2 にまだ無い → PR-3a を PR-3b より先に。
7. `IN (...)` と100パラメータ: GROUP BY には `queryChunked`（`web/src/lib/db.ts` 既存）が
   使えない → JOIN 前提で書く（§3.4）。
8. 年キーの意味の変更: `web/src/lib/ai/page-context.ts`・`web/src/lib/ai/links.ts`・
   `web/src/lib/ai/tools.ts`（いずれも既存）が `daily`/`annual` を前提にしている。
   切り替え漏れは「画面に無いものを AI が語る」につながる。
9. `scripts/b00_run_full_gate.py` の `PIPELINE_EXPLICIT_FILES`（既存）に `build-*.mjs` が
   入っている。消すときは、証明の付け替えと同じ PR で行う（PR-5）。
10. `web/scripts/export-d1-sql.mjs --db`（既存）は、列が本番のマイグレーション後の状態と
    一致している前提（`imputation` 列を残さない）。
11. 本番の切り替えでは順序を守る（DROP のマイグレーションをコードより先に当てると全画面が
    落ちる、PR-5）。
12. `web/src/app/api/column`（既存）がゲートの外、`describe_schema` が全表 `count(*)`、
    `run_sql` がフラグ（`web/src/lib/features.ts` の `EXPLORE_ENABLED`）の外。
13. 注記 `censored`（`registry/caveat.yaml:79-84` 既存）の本文が「0 とみなして集計」と
    系列を名指ししている。lod への切り替えと同じ PR（PR-2）で書き換える。
14. D1 の `LIKE` パターンは50バイトまで。alias を `LIKE` に入れない（`=` と JOIN）。
15. rows written（5,000万行/月まで込み）。投入のやり直しの回数を数える。
16. **スナップショットの更新 PR には serving-diff の表を必須にする（黙って更新させない）
    運用ルールを書く**（本ドキュメント §4-2・ADR-0029 で明文化する）。

## 8. 付録: 実測の要点（2026-09-26、アドバイザーによる実測）

```
observation_agg  2,022,964セル（day 1,479,883・fiscal_year 295,737・
                 month 162,198・year 85,146）、n_censored>0 のセル 243,686
occurrence_agg     471,060（grid01 のみ）
occurrence_place の流域解決  737,407・NULL 86,285

D1 索引つき見積もり: observation_agg 約680MB（slim版 約260MB）、
                     occurrence_agg 約140MB

代表的な問い合わせ（Python sqlite3）:
  年系列 25ms／日系列 16ms／月別平年値 18ms／ゾーン年次 15ms／mesh の1年分 70ms

派生33表のうち固定経路で読まれているのは24表
（landuse_watershed・org_norm・org_watershed(_year)・sensor_daily は SQL 無し、
 sensor_hour_month・redlist_map・landuse_change は呼び出しゼロ）
```

## 9. 閉じる条件

- PR-0〜PR-5 がマージされ、本番切り替えの手順書（`DEPLOYMENT.md`）がある。
- 各段の serving-diff の表（`reports/serving_switch_diff.md`）が記録されている。
- ADR-0029/0030 が承認済み（状態が「提案中」→「承認済」）。
- #28・#41 が閉じている。
