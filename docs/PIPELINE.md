# データパイプライン（Phase B / Issue #48）の詳細

CLAUDE.md から移した詳細。作業に必要な節だけを読むこと（全エージェントが毎回読む CLAUDE.md を短く保つため、2026-10-05 に分離）。

**2026-10-06（Issue #48 PR-5）**: v1（派生33表を作る `web/scripts/build-*.mjs`・v1 射影 b05/b08/b10/b11/b12・突合 b01/b02・
serving-diff の v1 側）は撤去した。ここに残るのは v2（観測・出現・キューブ・summary）のパイプラインだけ。
撤去の経緯・削除物の一覧は `docs/plans/V2_SERVING_PR5.md` §1.2、ADR-0029 の 2026-10-06 追記。

## 実行順

`r01 → b03 → b04 → b06 → b09 → b07 → b13`（ここまでが `cd web && pnpm run build:v2`）。b07 は `occurrence_place`（b09 の出力）を
読むので b09 が先。「b09/b07 は入れ替え可能」ではない。出力は `data/db/registry.sqlite` と `data/db/v2.sqlite`
（どちらも `.gitignore` 済み・捨てて作り直せる）。

- `scripts/b03_build_observation.py`: `measurements`・`sensor_timeseries`・土地利用 CSV
  （P-1b、`data/processed/nlni_l03b_landuse_by_watershed.csv`、`_ingest_landuse`）の3出典 → `observation`。
  土地利用は区分ごとの面積・セル数を別々の variable にし、region は `scripts/migrate/source_regions.yaml`
  （`consumer='observation'`。occurrence 側と consumer で宣言を分ける）から決める。設計・実測は
  `docs/plans/PHASE_B_FACT_SLICE.md`・`docs/plans/PHASE_B_LANDUSE.md`。
  b03 は合成データ（`is_synthetic=1`）を常に除外する（`--include-synthetic` と v1互換キューブ専用の宣言は Issue #61 で撤去した）。
- `scripts/b04_build_cube.py`: `observation` → キューブ `observation_agg`（土地利用を足しても無変更）。
- `scripts/b06_build_occurrence.py`: `organism_records` → `occurrence`（`v2.sqlite` に同居）。
- `scripts/b09_build_occurrence_place.py`（O-2a）: `occurrence` の座標を `data/processed/nlni_w12_watersheds.geojson`
  （W12 流域、377 面）へ純 Python の点内包判定（`scripts/migrate/point_in_polygon.py`）で直接解決し、記録×place の
  サテライト `occurrence_place` を作る。
- `scripts/b07_build_occurrence_cube.py`: `occurrence`＋`occurrence_place` → キューブ `occurrence_agg`。
  PR-3a（O-2b）で「place_kind × grain 族」の行列にした——`grid01`×`year`・`grid01`×`month`・`watershed`×`year` の3マス
  （実測 1,437,598 セル。`watershed`×`month` は消費者が無いので作らない）。流域に解決できない日付あり記録も
  `place_kind='watershed', place_id NULL` のセルとして持つ（データを落とさない）。測度は `n`/`n_red_list`/`n_alien`。
- `scripts/b13_build_summary.py`: `observation_agg`/`occurrence_agg` の宣言的集計（`aggregations/serving.yaml`）→
  `v2.sqlite` 内の `summary_*` 表。

生物の設計・実測は `docs/plans/PHASE_B_OCCURRENCE.md`・`docs/adr/0025-occurrence-fact-and-cube.md`・
`docs/adr/0026-occurrence-place-watershed.md`・`docs/plans/V2_SERVING_PR3A.md`。

## 自己不変条件（v1 と比べない検証）

PR-5 で v1 射影（b05/b08）から移した。キューブ・registry だけで成り立つべき検証で、ビルダーの中で走り、崩れていれば止まる
（置き場は `scripts/migrate/cube_invariants.py`。移設表は `docs/plans/V2_SERVING_PR5.md` §2.2）。

| 置き場 | 検査 |
|---|---|
| b04 | 時間→日の積み上げ（T6）、月→年・年度の積み上げの保存則（`verify_month_year_rollup`。Issue #32-2。n・検閲件数の和と min/max が月セルと一致）、alias が関数であること（dataset ごと）、alias タプルが単一 dataset に写ること、1系列 1 単位表記 |
| b07 | 系列ごとの Σn/Σn_red_list/Σn_alien が母集団と一致（族×place_kind）、流域セルを (place, 年) に畳んだ保存則 |
| b09 | `occurrence_place.place_id` が `place_source_ref` で必ず引け、`place_id → external_key` が単射（流域・メッシュ） |

加えて **b04 の無作為抽出セルの独立再計算**（`_assert_sampled_cells_recompute_from_observation`。`docs/plans/V2_SERVING_PR5.md` §2.3）:
`(grain, input_grain, stat)` の層ごとに無作為（seed は入力の指紋と spec_version から決定論的に導く）＋最大 n のセル＋検閲のあるセルを抜き、
`observation` から **SQL とは別の書き方（Python の `math.fsum`）で**再計算して一致を見る。食い違えば `MigrationError`。

## 検証の2層（v1 との突合の後継）

- **層2: 凍結スナップショット** — `cd web && pnpm run serving:snapshot -- --mode snapshot` が、画面・API・AI と同じ問い合わせ層
  （`@/lib/cube`）の出力を、`web/serving_queries.yaml` の問い合わせ×ドメインの値で展開して `data/sample/serving_snapshot.json` に書く。
  CI の `sample-gate` が縮小サンプルで再現し、コミット済みと `git diff --exit-code` で比べる。出力が動く PR は
  `--mode diff` の before/after 表を PR 本文に貼り、スナップショットを更新してコミットする（更新自体が宣言。免除リストは持たない）。
- **層3: 全量の指紋** — `scripts/b00_run_full_gate.py` が `build:v2` と同じ7段を回し、続けて executor を `--mode fingerprint` で全量に当てて
  `reports/serving_fingerprint.json` を書く（`full_gate_proof.json` の置き換え）。CI の `full-gate-proof-check`
  （`scripts/s04_check_full_gate_proof.py`）が、パイプラインのパスのハッシュ・サンプル manifest の原本 sha256・
  `queries[].id` と `serving_queries.yaml` の一致を検査する。パスには `web/src/lib/cube`（テスト・fixture 除く）・
  `web/serving_queries.yaml`・`web/scripts/serving-snapshot.mts`・`web/scripts/lib/serving` が入っている。

## 取り込み・レジストリ

- レッドリスト・外来種の評価（`taxon_assessment`、P-2）は `scripts/registry/build_taxon_assessment.py`
  （`ryuiki.redlist_assessments`〔3版〕と `data/processed/moe_ias_list.csv`〔外来種〕→ `registry.sqlite` の `taxon_assessment`。
  Issue #48 PR-0 で D1 に追加。`web/src/db/schema-registry.ts` の `taxonAssessment`）。外来種の表示名
  （`vernacular_name_ja_resolved`）は `ryuiki.taxa` から解決する。r01 の `taxon`（A-4）の直後に作る。
  **`taxon_assessment.in_scope`**（除外7種の宣言〔`registry/taxon/assessment_scope_exclusions.yaml`〕と二名法一致する行を 0、
  他の全行を 1 にした可視化列。PR-3a、D7。行そのものは1件も除外しない）、**`taxon.vernacular_name_en`**
  （ラテン文字だけの俗名の最頻値）・**記録由来の和名補完**（`vernacular_ja_basis`〔`override`/`taxa`/`records`〕に根拠を残す。
  既存の値は変えない）も r01（`build_taxon.py`）が作る（PR-3a、D4）。
  設計・実測は `docs/plans/PHASE_B_TAXON_ASSESSMENT.md`・`docs/plans/V2_SERVING_PR3A.md`。
  **Issue #34**: `in_scope` の規則は出典の属性（`origin_ja`）に切り替えた（`assessment_scope_exclusions.yaml` の
  `rules:`＋固定宣言。`scope_reason` に理由）。b06 が `occurrence.is_alien_in_scope` を持ち、`n_alien` はそれを数える
  （定義・件数は ADR-0019「Issue #34 追記」）。`taxon.accepted_taxon_id` と弱い一致の採用は
  `scripts/c26_taxon_gbif_accepted.py` が書く `data/processed/taxon_gbif_accepted.csv`（GBIF API 収集物。
  `taxon_crosswalk.csv` と同じ扱いで指紋・サンプル `data/sample/processed/` に入る）を r01 が読む。

## 規約

- **`+09:00` 付きの時刻文字列に SQLite の日時関数（`date`/`datetime`/`strftime`）を使わない**
  （UTC に正規化されて日付が1日ずれる。`observation.period_start` は時刻帯なしのローカル時刻で
  持つ。詳細は `docs/adr/0024-local-time-and-time-labels.md`）。
- **キューブ（`observation_agg`/`occurrence_agg`）を作るのは SQLite 3.43 以降でなければならない**
  （`FULL OUTER JOIN`〔`assert_grouped_totals_match`〕・`AVG()`/`SUM()`。`b04_build_cube.py`/`b07_build_occurrence_cube.py`
  それぞれの構築関数の先頭〔モジュール読み込み時点ではない〕で `scripts/migrate/common.py` の `require_sqlite_version()` を呼んで検証する。
  加算アルゴリズムが3.43で変わり、それより前だと平均値が黙って変わる行がある。`FULL OUTER JOIN` は3.39未満だとそもそも使えない）。
  見るのは `sqlite3` CLI ではなく Python 同梱の `sqlite3` モジュールのバージョン。詳細は `docs/adr/0021-observation-grain-and-cube-key.md`。
- **段階間の指紋**（`scripts/migrate/common.py` の `record_stage_fingerprint`/`assert_stage_fingerprint_fresh`/`LineageTracker`）:
  `b04`/`b07`/`b09`/`b13` は上流の段の出力が今も一致するか（(a)、系譜を再帰的に(b)）を読み込み時に確認し、崩れていれば止まる。
  **系譜（`pipeline_fingerprint.inputs`）は手で書かない**（Issue #45）: 各段は `LineageTracker(conn, external=...)` を張り、
  上流は `lineage.verify(...)`、出力は `staged_table(..., lineage=lineage)`。差し替え時に、実際に読んだ表（`sqlite3.set_authorizer`
  の `SQLITE_READ`）から出力表ごとに `inputs` を自動生成する。検証していない上流を読めば止まり、宣言の無い ATTACH 先も止まる。
  registry・原本は `ext:<schema>.<table>` として来歴に載る（鮮度の正は `pipeline_input_fingerprint`）。b03/b06 は別接続
  （原本・registry を読む作業用接続）を `lineage.watch(work, external=...)` で合算する。b13 は表ごとに `reset()`。
  設計は `docs/plans/ISSUE45_AUTO_LINEAGE.md`・`docs/plans/PHASE_B_FACT_SLICE.md`。
- テスト・検証戦略は4層（フィクスチャ・縮小サンプル・全量の実行証明・段階間の指紋）。
  詳細は `docs/adr/0027-test-and-verification-strategy.md`。パイプラインのパス
  （`scripts/b0*.py`/`b1*.py`・`scripts/migrate/`・`scripts/reconcile/`・`scripts/registry/`・`web/src/lib/cube` 等、
  `scripts/b00_run_full_gate.py` の `PIPELINE_*` 参照）を触ったら、原本のある手元で
  `.venv/bin/python3 scripts/b00_run_full_gate.py` を回して `reports/serving_fingerprint.json`
  を更新し、一緒にコミットすること（CI の `full-gate-proof-check` が鮮度を検査する）。
  サンプルの展開スクリプト（`scripts/s02_materialize_sample.py`）は手元の本物の
  チェックアウト・worktree では絶対に実行しない（安全装置はあるが、CLAUDE.md
  「worktree の運用」に従い一時ディレクトリへの clone で試すこと）。
- `scripts/reconcile/common.py`・`datasource.py` は v2 パイプラインが `migrate/common.py` 経由で import している
  （`compute_fingerprint`・`open_readonly`・`load_yaml`。v2 コード指紋の対象でもある）ので消さない。
