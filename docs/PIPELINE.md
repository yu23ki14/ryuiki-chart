# データパイプライン（Phase B / Issue #48）の詳細

CLAUDE.md から移した詳細。作業に必要な節だけを読むこと（全エージェントが毎回読む CLAUDE.md を短く保つため、2026-10-05 に分離）。

- Phase B（ADR-0016）の縦に薄い1本は `scripts/b03_build_observation.py`（`measurements`・
  `sensor_timeseries`・土地利用CSV〔P-1b、`data/processed/nlni_l03b_landuse_by_watershed.csv`、
  `_ingest_landuse`〕の3出典→`observation`）/ `scripts/b04_build_cube.py`（`observation`→
  キューブ `observation_agg`。土地利用を足しても無変更）/ `scripts/b05_project_v1.py`
  （キューブ→v1形）の3本。出力は
  `data/db/v2.sqlite`（`observation`/`observation_agg`）と `data/db/v1_projection.sqlite`
  （13テーブル: `meas_daily`/`meas_month`/`meas_year`/`meas_clim`/`site_var`/`var_catalog`/
  `sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/`zone_clim`/
  `landuse_watershed`/`landuse_change`）で、どちらも
  `.gitignore` 済み・捨てて作り直せる。設計・実測は `docs/plans/PHASE_B_FACT_SLICE.md`
  （土地利用は `docs/plans/PHASE_B_LANDUSE.md`）。土地利用は区分ごとの面積・セル数を
  別々の variable にし、region は `scripts/migrate/source_regions.yaml`
  （`consumer='observation'`。occurrence 側〔下記〕と consumer で宣言を分ける）から決める。
  生物の出現（occurrence、O-1a/O-1b/O-2a/O-2b）は別の縦線。**実行順は
  b06 → b09 → b07 → b13 → b08 に固定**（b07 が `occurrence_place`〔b09の出力〕を
  読むため b09 が先。b13 は `occurrence_agg` を読むだけなので b07 の直後、
  b08 より前でよい。「b09/b07 は入れ替え可能」ではない）:
  `scripts/b06_build_occurrence.py`（`organism_records`→`occurrence`。
  `data/db/v2.sqlite` に `observation`/`observation_agg` と同居）/
  `scripts/b09_build_occurrence_place.py`（O-2a。`occurrence` の座標を
  `data/processed/nlni_w12_watersheds.geojson`〔W12流域、377面〕へ純 Python の
  点内包判定〔`scripts/migrate/point_in_polygon.py`〕で直接解決し、記録×place の
  サテライト `occurrence_place` を作る。同じ `data/db/v2.sqlite` に同居）/
  `scripts/b07_build_occurrence_cube.py`（`occurrence`+`occurrence_place`→
  キューブ `occurrence_agg`。Issue #48 PR-3a（O-2b）で「place_kind × grain 族」
  の行列にした——`grid01`×`year`・`grid01`×`month`・`watershed`×`year` の
  3マス（実測 1,437,598 セル。`watershed`×`month` は消費者が無いので作らない）。
  流域に解決できない日付あり記録も `place_kind='watershed', place_id NULL` の
  セルとして持つ（データを落とさない）。測度は `n`/`n_red_list` に
  `n_alien`（`SUM(is_alien)`）を足した。同じ `data/db/v2.sqlite` に同居）/
  `scripts/b13_build_summary.py`（`observation_agg`/`occurrence_agg` の
  宣言的集計〔`aggregations/serving.yaml`〕→ `data/db/v2.sqlite` 内の
  `summary_*` 表。生物側は `summary_taxon_catalog`/`summary_watershed_occurrence`
  を作る）/
  `scripts/b08_project_occurrence_v1.py`（`occurrence`/`occurrence_agg`/
  `occurrence_place`→v1形13テーブル: `org_norm`・`org_group_year`・
  `effort_year`・`species2`・`species_year2`・`species_month`・`mesh_year`・
  `mesh_all`・`mesh_species`・`species_mesh_year`・`org_watershed_year`・
  `org_watershed`〔後者2つは O-2a、`occurrence`+`occurrence_place` だけから
  ——`occurrence_agg` は経由しない〕・`ias_species`、出力
  `data/db/v1_projection_occurrence.sqlite`。`_assert_watershed_cells_match_
  exact` が「`occurrence_agg` の流域セル」＝「`occurrence`+`occurrence_place`
  の正確な再集計」を毎ビルド確かめ、その比較専用の実表
  `org_watershed_year_exact`/`org_watershed_exact`〔v1互換13テーブルには
  数えない〕を出力ファイルに残す）
  の5本。設計・実測は `docs/plans/PHASE_B_OCCURRENCE.md`・
  `docs/adr/0025-occurrence-fact-and-cube.md`・
  `docs/adr/0026-occurrence-place-watershed.md`・
  `docs/plans/V2_SERVING_PR3A.md`。
- watershed の属性（`watershed_meta`・`watershed_rollup`）は
  `scripts/b11_project_place_v1.py`（`watershed_rollup` は
  `v1_projection.sqlite`〔b05〕/`v1_projection_occurrence.sqlite`〔b08〕を
  ATTACH して結合するだけの D10型の射影。キューブのセルにはしない）。
  **b11 はこの縦線で初めて別系統（observation・occurrence）の出力を読むので、
  実行順は r01 の後、b05・b08 を先に済ませてから b11**（b05・b08 は互いに
  依存しないので入れ替え可能）。出力は `data/db/v1_projection_place.sqlite`
  （`.gitignore` 済み・捨てて作り直せる）。
  設計・実測は `docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`。
  別枠で `scripts/b10_project_documents_v1.py`（`cells.sqlite`/`ryuiki.sqlite` を直接
  ATTACH、`observation` は経由しない）が `data/db/v1_projection_documents.sqlite`
  （`doc_series`/`doc_series_meta`/`quality_monthly` の3テーブル、`.gitignore` 済み）を作る。
  設計・実測は `docs/plans/PHASE_B_DOCUMENTS.md`。
- Phase B の v1 派生33表**全て**の突合を1コマンドで確認するゲートは
  `scripts/b02_run_all_gates.py`（`scripts/reconcile/projection_manifest.yaml`
  の対応表を読んで5つの candidate ファイルを回す。`b02_derived_compare.py` 自体は無変更）。
  設計・実測は `docs/plans/PHASE_B_RECONCILIATION.md` §12。
- レッドリスト・外来種の評価（`taxon_assessment`、P-2）は
  `scripts/registry/build_taxon_assessment.py`（`ryuiki.redlist_assessments`
  〔3版〕と `data/processed/moe_ias_list.csv`〔外来種、`ryuiki.taxa` ではなく
  L1 を直読み〕→ `registry.sqlite` の `taxon_assessment`。Phase A/B 当初は
  D1 の消費者が無いとして見送っていたが、Issue #48（PR-0）で D1 に追加した
  （`web/src/db/schema-registry.ts` の `taxonAssessment`）。外来種の表示名
  〔`vernacular_name_ja_resolved`〕は `ryuiki.taxa` から
  ここで解決する——v1（`taxa`）は3出典〔`kanagawa_redlist.csv`→
  `moe_redlist.csv`→`moe_ias_list.csv`〕をまたいだ和名の畳み込みをしており、
  moe_ias_list.csv単体では再現できないため）が r01 の `taxon`（A-4）の直後に
  作る。**`taxon_assessment.in_scope`**（除外7種の宣言
  〔`registry/taxon/assessment_scope_exclusions.yaml`〕と二名法一致する行を
  0、他の全行〔redlist 3版を含む〕を1にした可視化列。Issue #48 PR-3a、D7。
  行そのものは1件も除外しない）と、**`taxon.vernacular_name_en`**
  （`organism_records.vernacular_name` のうちラテン文字だけの値。
  (名前空間, taxon_key) ごとに最頻→同数なら値の昇順で1つ選ぶ。「英名」では
  なく「ラテン文字の俗名」）・**記録由来の和名補完**（`vernacular_name_ja` が
  NULL の行にだけ非ラテン文字の最頻値を入れ、`vernacular_ja_basis`
  〔`override`/`taxa`/`records`〕に根拠を残す。既存の値は1件も変えない）も
  同じ r01（`build_taxon.py`）が作る（Issue #48 PR-3a、D4）。
  v1形への射影は2本に分かれ、**どちらも `registry.sqlite` だけを読み、
  `ryuiki.sqlite` には一切触れない**: `scripts/b12_project_taxon_v1.py`
  （`taxon_assessment` → `redlist_map`/`redlist_change`、出力
  `data/db/v1_projection_taxon.sqlite`）と、`scripts/b08_project_occurrence_v1.py`
  に足した `ias_species`（`org_norm` の binom と結合するため occurrence の
  縦線側に同居）。設計・実測は
  `docs/plans/PHASE_B_TAXON_ASSESSMENT.md`・`docs/plans/V2_SERVING_PR3A.md`。
- **`+09:00` 付きの時刻文字列に SQLite の日時関数（`date`/`datetime`/`strftime`）を使わない**
  （UTC に正規化されて日付が1日ずれる。`observation.period_start` は時刻帯なしのローカル時刻で
  持つ。詳細は `docs/adr/0024-local-time-and-time-labels.md`）。
- **キューブ（`observation_agg`/`occurrence_agg`）・v1形への射影・`doc_series`
  （`AVG()`/`SUM()`、または `occurrence_agg` 側は `FULL OUTER JOIN`
  〔`assert_grouped_totals_match`〕を使う）を作るのは SQLite 3.43 以降でなければ
  ならない**（`b04_build_cube.py`/`b05_project_v1.py`/`b07_build_occurrence_cube.py`/
  `b08_project_occurrence_v1.py`/`b10_project_documents_v1.py` それぞれの
  構築・射影関数の先頭（モジュール読み込み時点ではない）で `scripts/migrate/common.py` の
  `require_sqlite_version()` を呼んで検証する。加算アルゴリズムが3.43で変わり、
  それより前だと平均値が黙って変わる行がある（`FULL OUTER JOIN` は3.39未満だと
  そもそも使えない）。見るのは
  `sqlite3` CLI ではなく Python 同梱の `sqlite3` モジュールのバージョン。詳細は
  `docs/adr/0021-observation-grain-and-cube-key.md`）。
- **段階間の指紋**（`scripts/migrate/common.py` の `record_stage_fingerprint`/
  `assert_stage_fingerprint_fresh`/`track_reads`）: `b04`/`b05`/`b07`/`b09`/
  `b08`/`b11` は上流の段の出力が今も一致するか（(a)、系譜を再帰的に(b)）・
  実際に読んだ表を検証し忘れていないか（読み取りの機械監査）を読み込み時に
  確認し、崩れていれば止まる。設計・実測は `docs/plans/PHASE_B_FACT_SLICE.md` 参照。
- `b05_project_v1.py` の出典固有の検証関数群は
  `scripts/migrate/v1_projection_checks.py`（`v1_projection_checks.関数名(...)` で呼ぶ）。
- テスト・検証戦略は4層（フィクスチャ・縮小サンプル・全量の実行証明・段階間の指紋）。
  詳細は `docs/adr/0027-test-and-verification-strategy.md`。パイプラインのパス
  （`scripts/b0*.py`/`b1*.py`・`scripts/migrate/`・`scripts/reconcile/`・`scripts/registry/`
  等、`scripts/b00_run_full_gate.py` の `PIPELINE_*` 参照）を触ったら、原本のある手元で
  `.venv/bin/python3 scripts/b00_run_full_gate.py` を回して `reports/full_gate_proof.json`
  を更新し、一緒にコミットすること（CI の `full-gate-proof-check` が鮮度を検査する）。
  サンプルの展開スクリプト（`scripts/s02_materialize_sample.py`）は手元の本物の
  チェックアウト・worktree では絶対に実行しない（安全装置はあるが、CLAUDE.md
  「worktree の運用」に従い一時ディレクトリへの git clone で試すこと）。
