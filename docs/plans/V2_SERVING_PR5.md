# Issue #48 PR-5「v1 の撤去と本番切り替えの手順書」実装設計

前提: ブランチ `feat/48-pr5`（main = PR-4 マージ済み、`d6af36c`）。調査は 2026-10-06 に grep と `mode=ro` の
sqlite3 だけで行った（重い処理は回していない）。上位文書: `docs/plans/V2_SERVING.md` §3.1・§4・§5 PR-5・§7、
`docs/adr/0029-v1-removal-and-verification-handoff.md`、`docs/plans/V2_SERVING_PR4.md`（FORBIDDEN_TABLES・申し送り）。
各担当は **§1（共通）＋自分の節**だけ読めば実装できる。

## 0. 要点

1. **PR-5 は値が動かない。** v1（派生33表を作る `build-*.mjs`・v1 射影 b05/b08/b10〜b12・突合 b01/b02・serving-diff の v1 側）を丸ごと消し、
   D1 から46表（派生33＋落とす原本11＋`instruments`/`protocols`）を DROP するマイグレーション `0010` を作る。
2. **消す前に移す。** b05/b08 に同居するキューブの自己不変条件を b04/b07/b09 へ移し、さらに b04 に「無作為抽出セルを `observation`
   から独立に再計算して一致を見る」検査を新設する（§2.2・§2.3）。v1 との比較部分は移さない。
3. **層2・層3の後継は serving-diff の executor を再利用して作る。** `web/scripts/lib/serving/adapters-v2.ts`・`normalize.ts`・
   `cube-db-singleton.ts`・`register-aliases.mjs`・`web/serving_queries.yaml`（v1 部分を剥がす）を残し、新しい
   `web/scripts/serving-snapshot.mts` が「スナップショット／指紋／before-after 表」を出す（§3）。v1 側（`adapters-v1`・`v1-queries`・
   `v1-compat`・`merge-v1`・`classify*`・`mutations*`・`report*`・`*-expect*`・`serving-diff.mts`・`v1-db-shim`）は削除。
4. **`derived.sqlite` は D1 シードの入力から消える**（33表すべてが派生表で、残す表は1つも無い。`build:derived` は
   水源マップ用の `build-water-geo.mjs` だけになり `build:water-geo` に改名）。
5. **`scripts/reconcile/common.py`・`datasource.py` は消さない。** v2 パイプラインが `migrate/common.py` 経由で import している
   （`compute_fingerprint`・`open_readonly`・`load_yaml`。v2 コード指紋の対象でもある）。消すのは v1 専用の YAML 4本と v1 専用関数だけ。
6. **`b09` は残る**（`occurrence` だけを読み `occurrence_place` を作るキューブ側。b07 が依存）。`b13` も残る。
7. 本番へは出さない。手順書（投入 → `0009` → コード → `0010` DROP）を `DEPLOYMENT.md` に書くだけ（§7）。

## 1. 共通

### 1.1 役割の境界（全担当の指示に必ず入れる）

- 実装担当は **スキル（/simplify・/code-review 等）やサブエージェントを起動しない**。重い処理（`b00`・`build:v2`・serving snapshot/fingerprint の
  全量・`pnpm build`・CI の clone 再現）を回さない。速い検証（該当テストだけ）まで。
- `web/drizzle/migrations/` を生成・コミットしない（`pnpm run db:generate` は統合者が1回）。`generated*.ts` の再生成は C だけが行う。
- worktree には原本を1ファイルずつ symlink（CLAUDE.md の手順）。`git add -A` を使わない。パスを明示して add。
- 担当間でファイルが衝突しない割り振りにしてある（§6 の表）。他担当のファイルを見つけたら触らずに申し送る。

### 1.2 V2_SERVING.md §5 PR-5 の列挙と実ファイルの突き合わせ（2026-10-06 実測）

| §5 の記述 | 実態 |
|---|---|
| `web/scripts/build-derived.mjs`/`build-biota.mjs`/`build-geo.mjs` | 3本とも実在。**削除**。`build-water-geo.mjs`・`copy-geo-assets.mjs`・`lib/csv.mjs`（`build-registry-ts.mjs` が使う）は残す |
| `scripts/b01_derived_baseline.py`・`b02_derived_compare.py`・`b02_run_all_gates.py` | 3本とも実在。**削除** |
| `b05_project_v1.py`・`b08_project_occurrence_v1.py`・`b10`・`b11`・`b12` | 5本とも実在。**削除**（不変条件の移設後） |
| `scripts/reconcile/` の `projection_manifest.yaml`・`adr0011_destinations.yaml`・`derived_keys.yaml`・`expected_diffs.yaml` | 4本とも実在。**削除**。**一覧に無い**が実在し残すもの: `reconcile/__init__.py`・`common.py`・`datasource.py`（§0-5） |
| `scripts/migrate/v1_projection_checks.py` | 実在。**削除**（§2.2 の移設後） |
| `scripts/migrate/occurrence_watershed_v1_declarations.yaml` | 実在。**削除** |
| `reports/derived_baseline.json`/`.md`、`data/sample/derived_baseline.json`/`.md` | 4本とも実在（tracked）。**削除**。**一覧に無い**: `data/sample/derived_keys.yaml`（tracked）も削除 |
| （一覧に無い）`scripts/migrate/unit_evidence_declarations_v1compat.yaml` | v1互換キューブ（`b00` の2本目 b03/b04）専用。**削除** |
| （一覧に無い）`scripts/s05_check_sample_gate_summary.py`・`scripts/tests/test_s05_*.py` | v1 ゲート出力のパーサ。**削除**（`b00` の `s05.parse_summary` 依存も外す） |
| （一覧に無い）`web/scripts/lib/v1-db-shim.ts`・`web/src/lib/cube/integration.test.ts`・`pr4-integration.test.ts` | 前者は serving-diff の v1 側。後二者は `derived.sqlite` と突合する実DB統合テスト（`skipIf(!hasRealDb)`）。**すべて削除**（残すと黙って skip され続ける） |
| `web/src/lib/queries.ts` に残る v1 部分 | **既に無い**（PR-4 で `v1-queries.ts` へ移動済み、309行・非 v1）。作業なし |
| `web/src/lib/table-meta.ts` の `TABLE_ORIGIN`・`SAMPLE_QUERIES` | **既に清掃済み**（PR-4。v2・registry の表だけ）。作業なし |
| `web/src/lib/ai/prompt.ts` の `SAMPLE_QUERIES` | 同上。**作業なし** |
| `reports/derived_reconciliation*.md` | `.gitignore` 済みで untracked。作業なし |
| 過去の `reports/serving_switch_diff*.md/.json` | **残す**（記録） |

### 1.3 DROP する表（46）と D1 の表数

`web/src/db/schema.ts` の export 名と照合済み。
- 派生33: `docSeries docSeriesMeta effortYear iasSpecies landuseChange landuseWatershed measClim measDaily measMonth measYear meshAll meshSpecies meshYear orgGroupYear orgNorm orgWatershed orgWatershedYear qualityMonthly rainDaily redlistChange redlistMap sensorDaily sensorHourMonth siteVar species2 speciesMeshYear speciesMonth speciesYear2 varCatalog watershedMeta watershedRollup zoneClim zoneYear`
- 落とす原本11: `measurements sensorTimeseries organismRecords taxa redlistAssessments decisions interventions qualityTransitions observers events eventObservers`
- D3（PR-4）: `instruments protocols`
- 残す（`schema.ts`）: `sites sourceRegistry cells documents notes extractionLog vocab×4 protectedAreas vegetationPolygons mammalMesh wildlifeSightings riverSegments water×8 _seed_state`（24）。`water_*`/`vocab_*`/`extraction_log` は PR-6。
- 表数: 87 − 46 = **41**（うち `_seed_state` を除く **40 表**がシード対象）。統合者が `0010` 適用後の `sqlite_master` で実測して CLAUDE.md を直す。
- FK: `schema.ts` の外部キーは `cells → documents` の1本だけ（どちらも残る）。DROP の順序問題は無い。

### 1.4 用語

- 「自己不変条件」= v1 と比べず、キューブ・registry だけで成り立つべき検証。
- 「sample v2」= `scripts/s02_materialize_sample.py` で `data/sample/` から展開した原本（clone 内）に r01・b03〜b13 を回した `data/db/v2.sqlite`。
- 「executor」= `web/scripts/serving-snapshot.mts`（§3）。

---

## 2. 担当 A: Python パイプライン（不変条件の移設・v1 の削除・b00・s0x）

触るファイル: `scripts/**`（`scripts/tests/**` を含む）、`data/sample/**`、`reports/derived_baseline.*`、`reports/full_gate_proof.json`（削除）。
**触らない**: `registry/`・`scripts/registry/build_caveat.py`（C）、`.github/`・`web/`・`docs/`・ルートの文書（D、B）。
内部の順序: **§2.2→§2.3→§2.4（削除。`v1_projection_checks.py` の削除は最後）→§2.5**。

### 2.1 残すもの・消すものの確認（再掲）

消す: `b01_derived_baseline.py` `b02_derived_compare.py` `b02_run_all_gates.py` `b05_project_v1.py` `b08_project_occurrence_v1.py`
`b10_project_documents_v1.py` `b11_project_place_v1.py` `b12_project_taxon_v1.py` `s05_check_sample_gate_summary.py`、
`scripts/reconcile/{projection_manifest,adr0011_destinations,derived_keys,expected_diffs}.yaml`、
`scripts/migrate/{v1_projection_checks.py,occurrence_watershed_v1_declarations.yaml,unit_evidence_declarations_v1compat.yaml}`、
`data/sample/{derived_baseline.json,derived_baseline.md,derived_keys.yaml}`、`reports/derived_baseline.{json,md}`。
消すテスト: `test_b01_determinism` `test_b02_compare` `test_b02_run_all_gates` `test_b05_project_v1` `test_b08_ias_species`
`test_b08_occurrence_cube_projections` `test_b08_project_occurrence_v1` `test_b08_watershed_projections` `test_b10_project_documents_v1`
`test_b11_project_place_v1` `test_b12_project_taxon_v1` `test_s05_check_sample_gate_summary` `test_sample_aggregation_is_not_degenerate`
（`derived_baseline.json` を読む。後継は §3.5 の executor の空振り検査）。
直すテスト: `test_common`・`test_migrate_common`（v1 専用関数の検証を外す）、`test_sample_coverage`（`derived_keys`/`derived_baseline` の2ケースを外す）、
`test_s01_build_sample`・`test_r01_registry_atomic`・`test_b00_run_full_gate`・`test_s04_check_full_gate_proof`、`fixtures.py`・
`migrate_fixtures.py`・`occurrence_fixtures.py`・`registry_fixtures.py`・`conftest.py`（b05/b08/derived を前提にした部分。実際の参照は grep で洗う）。
残すテスト: `test_datasource`・`test_build_v2_script_order`・`test_check_v2_fresh`・b03/b04/b06/b07/b09/b13 系。

`scripts/reconcile/common.py` から消す v1 専用の部分: `load_key_overrides`・`load_destinations`・`load_projection_manifest`・
`flatten_projection_manifest`・`EXPECTED_DIFF_KINDS`/`REQUIRED_*`・`load_expected_diffs`・`validate_expected_diffs`・`derive_key`/`_search`/`_is_unique`・
`SCHEMA_VERSION`（b01/b02/b00/CI だけが使う。消す前に `grep` で v2 側の参照が無いことを確かめる）。**残す**: `open_readonly`・`table_info`/
`get_columns`/`get_column_types`/`get_pk_columns`/`numeric_columns_of`・`format_number`・`_canonicalize_scalar`・`canonical_row_bytes`・
`compute_fingerprint`・`load_yaml`、`datasource.py` 全体、`__init__.py`（docstring は更新）。
`scripts/s01_build_sample.py` から `build_derived_keys_yaml`・`DEFAULT_BASELINE_JSON`・`--baseline-json`・`derived_keys.yaml` の書き出しを外す。
`scripts/s03_verify_sample_artifacts.py` から `derived_keys`・`b01` 呼び出し・`--derived-db`/`--baseline-json` を外す（`declaration_counts.yaml`
の再生成検証だけ残す）。`scripts/m06_water.py` の最後の案内文（`build:derived`）を `build:water-geo` に直す。docstring・コメント内の
`derived.sqlite`/`b05` 言及は、実装に触れる箇所だけ直す（全文書き換えはしない）。

### 2.2 自己不変条件の移設（先にやる）

新モジュール `scripts/migrate/cube_invariants.py`（`v1_projection_checks.py` の後継。キューブ・registry の自己無矛盾だけを置く）。
呼ぶのは各ビルダー。**元の関数をコピーして直し、旧ファイルは §2.4 で消す**。v1 と比べる部分（`load_v1_keys`・`assert_v1_keys_are_unique`・
ゾーンの `fraction=1.0`・ゾーン番号の衝突・`_assert_place_relation_table_exists`・`b08` の `memo_moved_*`/`_assert_watershed_declarations_match`・
`org_watershed_year` の保存則の `moved` 項）は**移さない**（v1 射影固有。ゾーンの「地点は高々1本の within 辺」は r01 が既に保証している）。

| 元（v1 側） | 移し先 | 変更点 |
|---|---|---|
| `v1_projection_checks.verify_hourly_daily_rollup`（T6） | **b04** `build_cube()` の staged_table ブロック内、`_assert_value_zero_lod_invariants` の直後 | 入力の `label25_obs_keyed`（b05 の一時表）を b04 内で `observation` から直接作る（`value_grain IN ('hour','instant')`、`substr(period_raw,1,10)`＝ラベル日）。比較先は `staging`（`grain='day' AND input_grain='hour' AND stat='mean'`）。式は元のまま「キューブ日次 n ＝ ラベル日割りの n − 当日ラベル00時 + 翌日ラベル00時」と系列ごとの Σn・min・max。日付演算は Python（`date.fromisoformat`）。**SQLite の日時関数を使わない**（ADR-0024） |
| `assert_alias_is_function`（measurements 全 grain／sensor_timeseries は `grains=('day','hour','instant')`／土地利用の各年版）・`assert_alias_tuple_maps_to_single_dataset` | **b04**、`_assert_unit_evidence` の直後（`reg` を ATTACH 済み） | 対象 dataset は `reg.variable_alias` から導く（土地利用の版は `@` 前に正規化。`_discover_landuse_years` の考え方）。sensor の月次重複（積雪3変数の alias 揺れ）は既知の登録負債として**定数と理由つきの除外**にする（黙って grain を狭めない） |
| `assert_unit_raw_is_function` | **b04**、`_assert_unit_evidence` と同じ場所 | `cube.observation` → `observation`（接続先が b04 の `conn`）。v1 の `unit` 表記を引き戻すための前提だったが、「1系列は1つの単位表記」はキューブ自身の不変条件としても有効 |
| `b08._assert_cube_is_current_l2_partition`（grid01 の系列 Σn）・`_assert_watershed_cells_match_exact` | **移さない（b07 が既に持つ）** | b07 の `_assert_series_totals_match_population` が族×place_kind（grid01・watershed の両方）で系列ごとの Σn/Σn_red_list/Σn_alien を母集団と突合している。b08 側は同じものの v1 向け再掲 |
| `b08._assert_watershed_conservation`（保存則）の v1 に依らない核 | **b07** に新設 `_assert_place_year_totals_match_population` | 流域セル（`place_kind='watershed'`・year 族・`place_id IS NOT NULL`）を **(place_id, 年)** に畳んだ n/n_red_list/n_alien が、母集団（`occurrence`＋`occurrence_place` を直接 JOIN した `__pop_watershed`）を同じ粒度で畳んだものと一致する（b07 既存の系列粒度の検査を place×年へ細かくする）。さらに `Σ(place_id IS NOT NULL の流域セル n) + Σ(NULL の n) = 日付あり記録数` は既存の宣言検証（`watershed_dated_resolved_rows`/`..._unresolved_rows`）が担うので重ねない。grid01 は place 数が多いので、流域だけ（377 place）でよい |
| `b08._assert_place_watershed_lookup_is_function`・`_assert_all_watershed_places_resolve`・`_assert_all_places_resolve_to_mesh`・`_assert_place_mesh_lookup_is_function` | **b09**、`occurrence_place` を書く直前（`reg.place_source_ref` を既に読んでいる） | 「`occurrence_place.place_id` が `place_source_ref` で必ず引け、`place_id → external_key` が単射」。b09 の `_assert_watershed_external_key_unique` と並べる。mesh 側（`organism_records.lat_lon` の `grid01:` キー）も同じ種類の検査なので一緒に移す |

各移設に **変異テスト**を付ける（`scripts/tests/test_b04_build_cube.py`・`test_b07_*`・`test_b09_*` に追加）。小さなフィクスチャで
「正常は通り、1か所壊すと `common.MigrationError`」を確かめる（キューブの n を+1／alias を重複／`unit_raw` を2種／流域セルの n を欠落）。
移した関数の元のテスト（`test_b05_project_v1.py` 内）から該当ケースを**移植**してから元のファイルを消す。

### 2.3 b04 の新設検査: 無作為抽出セルの独立再計算

`b04_build_cube.py` に `_assert_sampled_cells_recompute_from_observation(conn, staging, observation_fingerprint, spec_version)` を足し、
staged_table ブロック内で `_assert_dimension_key_unique`・`_assert_value_zero_lod_invariants`・§2.2 の T6 の**後**に呼ぶ（失敗すれば本番名へ差し替えない）。

- **層別**: `(grain, input_grain, stat)` ごと（約8〜12層）。各層から `min(層の大きさ, 200)` セル（定数 `SAMPLE_CELLS_PER_STRATUM`）を `random.Random(seed).sample` で
  選ぶ（rowid の一覧から）。加えて各層で **n が最大のセル1つ**と **`n_censored > 0` のセルから最大50**（検閲の経路を必ず踏む）を足す。
- **seed**: `int(sha256(f"{observation_fingerprint}|{spec_version}").hexdigest()[:8], 16)`。入力が同じなら毎回同じ抽出（決定論）、入力が変われば
  抽出も変わる（固定 seed で同じセルだけを見続けない）。
- **再計算**: セルの次元キーと期間 `[period_start, period_end)` から、`observation` の該当行を取り（次元＝region・place・place_kind・variable・obs_stat・
  unit・value_grain、期間＝`period_start` の文字列比較。**`+09:00` 付き文字列に SQLite の日時関数を使わない**）、**Python の `math.fsum` で**
  n・n_censored・n_not_detected・mean・min・max・sum と `value_zero`/`value_lod`（below_lod は zero で 0／lod で `censoring_limit`、not_detected は両方で平均から除外。
  実装の根拠は ADR-0009 決定2・b04 docstring）を求める。日→月→年の積み上げセルは「日次平均の平均」で、b04 の `_month_from_day_sql`/`_year_from_day_*` の規則
  を読んで**SQL とは別の書き方（Python）で**組む。出典配布セル（`grain = input_grain`）は観測そのまま。**SQL の式を使い回さない**（同じ式の同じバグを見逃すため）。
- **比較**: n・n_censored・n_not_detected・min・max は完全一致。mean・sum・`value_zero`・`value_lod` は `math.isclose(rel_tol=1e-9, abs_tol=1e-12)`
  （`fsum` と SQLite の AVG の加算順の差）。NULL は NULL と一致。食い違えば最大20件を「次元キー・期待・実際」つきで `common.MigrationError`。
- **性能**: 抽出した次元キー・期間を一時表に入れ1回の JOIN で観測を引く（セルごとのクエリにしない）。全量で60秒以内を目安に、超えるなら
  `SAMPLE_CELLS_PER_STRATUM` を下げるか一時表に索引を張る（実測はメインが b00 のときに1回見る）。
- **テスト**: ① 正常なフィクスチャで通る。② 層の全セルが抽出される小さなフィクスチャで `staging` の1セルの `value_lod`/`n` を壊すと落ちる。
  ③ 同じ入力で抽出が同じ・指紋が違えば抽出が変わる。④ 検閲セルが必ず含まれる。

### 2.4 削除（§2.1 の一覧）と `b00` の付け替え

- `scripts/b00_run_full_gate.py`: `PIPELINE_FILE_GLOBS = ("scripts/b0*.py", "scripts/b1*.py")` はそのまま（残るのは b00/b03/b04/b06/b07/b09/b13）。
  `PIPELINE_EXPLICIT_FILES` から **`reports/derived_baseline.json`・`web/scripts/build-derived.mjs`・`build-biota.mjs`・`build-geo.mjs`** を落とす
  （`web/scripts/lib/csv.mjs` は `build-registry-ts.mjs` が使うので残すが、`build-geo.mjs` が消えて b00 の対象である理由は「registry の生成物の入力」に変わる。
  コメントを直す）。**足す**: `web/serving_queries.yaml`・`web/scripts/serving-snapshot.mts`・`web/scripts/lib/serving`（ディレクトリ。テストは次の除外で外す）・
  `web/src/lib/cube`（ディレクトリ。**`*.test.ts`・`__fixtures__` は除外**）。除外のために `PIPELINE_EXCLUDE_GLOBS = ("**/*.test.ts", "**/__fixtures__/**")` を
  `collect_pipeline_paths()` に足す（ディレクトリは配下のファイルに展開して個別の blob ハッシュを取る。`s04` も同じ関数を使う）。
  `PIPELINE_DIRS`（`scripts/registry`・`scripts/migrate`・`scripts/reconcile`・`registry`・`aggregations`）は変えない。
- `PIPELINE_STEPS` を **`web/package.json` の `build:v2` と同じ順の7段**にする: `r01 → b03 → b04 → b06 → b09 → b07 → b13`。v1互換キューブの5段・
  `_COPY_V2_FOR_V1COMPAT_BEFORE`・`b02_run_all_gates` 呼び出し・`default_candidate_files()`・`s05.parse_summary` を消す。`test_build_v2_script_order.py` が順序を守る。
- 続けて executor を **全量**で呼ぶ: `pnpm exec tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-snapshot.mts --mode fingerprint --out <一時ファイル>`
  （cwd=`web/`。`b00` は変換・検証のロジックを持たない薄いオーケストレータという原則は守る）。
- **`reports/serving_fingerprint.json` を `reports/full_gate_proof.json` の後継として書く（置き換え。併存しない）**。形:
  ```
  { "schema_version": 1, "created_at", "git_head", "pipeline_path_hashes", "source_hashes", "environment",
    "pipeline_fingerprint_rows": {"v2.sqlite": [...], "registry.sqlite": [...]},
    "queries": [ {"id", "n_domain", "runs": [{"params", "n_rows", "sums", "hash"}]} ],
    "changes_vs_previous": {"previous_git_head", "per_query": {id: {"same": n, "changed": n, "added": n, "removed": n}}} }
  ```
  ヘッダ部（`git_head`〜`environment`）は旧 proof と同じ作り（作業ツリーが対象パスで clean を要求、終了コード0のときだけ書く）。`queries` は executor の出力
  （§3.4）をそのまま入れる。`changes_vs_previous` は **書き換える前の** `reports/serving_fingerprint.json`（コミット済み）と run の `hash` を突き合わせた件数
  （前回が無ければ省略）。**自己不変条件の実行結果は記録しない**——b04/b07/b09 の終了コード0がその証拠で、変異テストが「止まる」ことを守る。
- `scripts/s04_check_full_gate_proof.py`（名前は残す。CI ジョブ名 `full-gate-proof-check` も残す）: 読むファイルを `reports/serving_fingerprint.json` にする。
  既存の2検査（パスのハッシュを HEAD で再計算／`data/sample/manifest.json` の原本 sha256 との一致）は変えない。**足す**: `queries[].id` の集合が
  HEAD の `web/serving_queries.yaml` の `id` の集合と一致すること（問い合わせを足したのに証明を作り直していない、を CI が落とす）。`schema_version` 検査。
  `reports/full_gate_proof.json` を `git rm`。
- `test_b00_run_full_gate.py`・`test_s04_check_full_gate_proof.py` を新しい形に直す（`PIPELINE_EXCLUDE_GLOBS`・7段・新キー）。

### 2.5 速い検証と完了条件

- 速い検証: `pytest scripts/tests/test_b04_build_cube.py scripts/tests/test_b07_build_occurrence_cube.py scripts/tests/test_b09_build_occurrence_place.py
  scripts/tests/test_b13_build_summary.py scripts/tests/test_migrate_common.py scripts/tests/test_common.py scripts/tests/test_datasource.py
  scripts/tests/test_b00_run_full_gate.py scripts/tests/test_s04_check_full_gate_proof.py scripts/tests/test_s01_build_sample.py scripts/tests/test_sample_coverage.py
  scripts/tests/test_build_v2_script_order.py scripts/tests/test_check_v2_fresh.py scripts/tests/test_r01_registry_atomic.py`、最後に `pytest -x -q`（原本不要。数分）。
- 完了条件: ① `grep -rEn "b05_project|b08_project|b10_project|b11_project|b12_project|v1_projection|derived_baseline|derived_keys|expected_diffs|projection_manifest" scripts data/sample`
  が、歴史的な言及を説明するコメント（設計の経緯）以外に残らない（import・パス・実行呼び出しはゼロ）。② §2.2・§2.3 の変異テストが緑。③ `scripts/migrate/v1_projection_checks.py` が無い。
  ④ `scripts/reconcile/` に `common.py`・`datasource.py`・`__init__.py` だけが残る。

---

## 3. 担当 B: serving の道具（スナップショット・指紋・before/after 表）

触るファイル: `web/scripts/serving-diff.mts`（削除）・新規 `web/scripts/serving-snapshot.mts`、`web/scripts/lib/serving/**`、`web/serving_queries.yaml`、
`web/vitest.config.ts`（コメント）、`web/package.json` の **`serving:diff` の1行だけ**（`serving:snapshot` に置換。他の行は D）、`data/sample/serving_snapshot.json`（新規。生成は統合者）。
**触らない**: `web/src/**`（C）、`scripts/**`（A）、`.github/`・文書（D）。

### 3.1 残す／消す（`web/scripts/lib/serving/`）

残す: `adapters-v2.ts`・`normalize.ts`・`cube-db-singleton.ts`・`register-aliases.mjs`・`adapters-v2.test.ts`（v1 比較のケースを外して縮める）・`normalize.test.ts`。
消す: `adapters-v1.ts`・`v1-queries.ts`・`v1-compat.ts`・`merge-v1.ts(.test)`・`classify.ts`・`classify.test.ts`・`classify-biota.test.ts`・`mutations.ts(.test)`・
`report.ts(.test)`・`biota-expect.ts(.test)`・`docs-expect.ts(.test)`・`../v1-db-shim.ts`・`../../serving-diff.mts`。過去の `reports/serving_switch_diff*.md/.json` は残す。
`adapters-v2.ts` は v1 の再現のための部品（`merge-v1` への言及・`expectedUnitSymbols*`・alias→kind の合流・`catalogSource`/v1compat の第2接続の説明）のうち、
**executor が使わなくなったものを削る**（`classify` 専用なら削除。使うなら残す。判断はテストと tsc が出す）。

### 3.2 `web/serving_queries.yaml` の再構成

- 残す: `version`・`queries[].id`・`params`・`compare`（`key`/`numeric`/`label`。`toNormRows` が使う）。
- 消す: `v1_table`・`only_existing`・`known`・`retired`・`tolerance`・コメントの v1 突合の説明。`domains` の `db: v1` はすべて作り直す。
- 追加: `max_runs`（問い合わせごとの上限。既定は snapshot 12／fingerprint 60）、`allow_empty: true`（空が正常な問い合わせだけ。理由つき）。
- **ドメインは v2 側から導く**。`db: v2|registry|ryuiki|cells` と `sql` を持ち、**複数列を1つのドメインにできる**（`columns: [variable_id, site_id]`。`only_existing` の後継で、
  「実在する組」だけを列挙して空走りを防ぐ）。例: `alias`/`variable_id` は `registry.variable_alias`（dataset='measurements'）、`site_id` は `v2.summary_place_variable`、
  `binom_n80` は `v2.summary_species_catalog`（n≥80）、`taxon_group` は `v2.summary_group_year`、`list_year`/`redlist_group` は `registry.taxon_assessment`（実装は §2 の画面・API が
  引く元と同じ列にする）。固定 `values:` の列は残す。
- **どの問い合わせを残すか**: 規則は「`adapters-v2` がその id で呼ぶ公開関数に、`web/src/app`・`web/src/components`・`web/src/lib/ai` の**テスト以外**の呼び出し元がある」。
  実測の手がかり: 画面・API・AI は `variable_id` 起点（`representativeSeries`）で、alias 起点の `variable_catalog`〜`water_bodies_for_variable`・`*_site`・`*_water`・`zone_series`・
  `climatology`・`zone_climatology`（`_by_variable` の付かない側）は v1 の oracle 専用の可能性が高い。残す側は `*_by_variable`・`sites_list`・`water_bodies`・`sites_in_water_body`・
  生物系・文書・概況・流域。**実際の呼び出し元を grep で確かめてから**落とす（落とした id と理由を PR 本文に列挙）。落とした分の `adapters-v2` の分岐も削る。

### 3.3 executor `web/scripts/serving-snapshot.mts`

実行: `pnpm run serving:snapshot -- [--mode snapshot|fingerprint|diff] [--out <path>] [--only id,id] [--base <path>]`
（`tsx --import ./scripts/lib/serving/register-aliases.mjs ./scripts/serving-snapshot.mts`）。接続は `adapters-v2.openV2Db`（`sqliteCubeDb`。`RYUIKI_DB_DIR`・
`RYUIKI_REGISTRY_DB` を見る。`cells.sqlite` も渡す）。**`imputation` は `lod` 固定**（画面・API が `lod` だけを使う。`zero` の系列は b04 の不変条件が守る）。
`catalogSource` は既定の summary（画面・API・AI と同じ経路）。
**限界を書く**: 本番の D1 経路（`d1CubeDb`・100パラメータ・分割クエリ）は通らない。`sqliteCubeDb` と `d1CubeDb` の等価はテスト（`db-sqlite.test.ts`）側の責務。

- 展開: 問い合わせごとに、ドメインの値を**決定論的な全順序**（数値は数値順、文字列は UTF-16 コード単位順、複数列は列順の辞書式）で並べ、直積（複数列ドメインは1つの軸）の
  先頭・末尾を含む等間隔の `max_runs` 件を選ぶ。`n_domain`（直積の全件数）を必ず記録する（ドメインが縮んだことが見えるように）。
- 行の正規化: `NormRow`（`key`/`numeric`/`label`）。`key` の辞書式で整列。数値は `Number(x.toPrecision(12))`、`-0` は `0`、`NaN`/`Infinity` は例外（隠さない）。
  浮動小数の末尾差（SQLite の版・加算順）を吸収するための丸めで、整数はそのまま。
- `snapshot` モード: 全 run の全行を `data/sample/serving_snapshot.json` に書く。**日時・git head・SQLite の版・パスを入れない**（ノイズで diff が汚れる）。形:
  ```
  { "schema_version": 1, "imputation": "lod",
    "queries": [ {"id", "n_domain", "runs": [ {"params": {...キー昇順}, "rows": [ {"key":[..],"numeric":{..},"label":{..}} ]} ]} ] }
  ```
  整形は「最上位と run は改行、**1 row = 1 行**」（`git diff` で行単位に読める）。問い合わせは YAML の順、run は上の全順序。同じ入力で2回書いてバイト一致（テストで確かめる）。
- `fingerprint` モード: run ごとに `n_rows`・`sums`（`numeric` 列ごとの和を丸めたもの）・`hash`（正規化済み行の JSON の sha256）だけを出す（全量では行を書かない）。
  出力は §2.4 の `queries` 部分の JSON。
- `diff` モード: スナップショットをメモリで作り、`git show HEAD:data/sample/serving_snapshot.json`（`--base` で差し替え可）と比べて
  **問い合わせごとの markdown 表**（run 数の増減・行数の増減・変わった run 数・数値列の和の変化）を標準出力に出す。**スナップショット更新 PR はこの表を PR 本文に貼る**
  （ADR-0029・危険16 の「serving-diff の表を必須にする」の後継。serving-diff が無くなるので、表の出処はこのモードだけ）。終了コードは常に0。
- 空振り検査（旧 `s05`・`test_sample_aggregation_is_not_degenerate` の後継）: `snapshot`/`fingerprint` の最後に、(a) `allow_empty` でない問い合わせの run がすべて0行、
  (b) `numeric` に `n` を持つ問い合わせで、全 run の `n` の最大が1以下（1件をそのまま写しただけ）、のどれかなら**非0で終了**。
- テスト（vitest。`web/scripts/lib/serving/` 配下。DB 不要の純関数だけ）: 順序・丸め・等間隔選択・JSON 整形のバイト一致・空振り検査・diff 表。
  実 DB を使うテストは作らない（実 DB は統合者が CI 手順で1回）。

### 3.4 CI `sample-gate` の新しい手順（D が `ci.yml` に書く。B は仕様を渡す）

`.github/workflows/ci.yml` の `sample-gate` を、v1 構築・v1互換5段・33表ゲート・`s05` をすべて外して次にする（`timeout-minutes` は短縮可）:
1. checkout・Python・`pip install -r requirements.txt`・`python3 scripts/s02_materialize_sample.py`（`GITHUB_ACTIONS=true` が安全装置。**本物のチェックアウトでは実行しない**）。
2. pnpm・Node・`pnpm install --frozen-lockfile`・`pnpm rebuild better-sqlite3`。
3. `python3 scripts/r01_build_registry.py`（フルビルド）。
4. v2 を構築（`--count-overlay data/sample/declaration_counts.yaml` を b03・b06・b09・b07 に）: `b03 → b04 → b06 → b09 → b07 → b13`（`build:v2` と同じ順）。b04/b07/b09 の
   不変条件（§2.2・§2.3）はここで走る。
5. `python3 scripts/s03_verify_sample_artifacts.py` → `git diff --exit-code data/sample/declaration_counts.yaml`（サンプル成果物がコミットと一致）。
6. `cd web && pnpm run serving:snapshot -- --mode snapshot` → `git diff --exit-code data/sample/serving_snapshot.json`。差が出たら「意図した変更なら `--mode diff` の表を PR に貼って
   スナップショットを更新」と失敗メッセージに書く。**免除リストは持たない**（スナップショットの更新自体が宣言）。

### 3.5 速い検証と完了条件

- 速い検証: `cd web && pnpm exec vitest run scripts/lib/serving && pnpm exec tsc --noEmit && pnpm run lint`。
- 完了条件: ① `web/scripts` に v1 を指す import・パス・文字列（`derived.sqlite`・`v1_projection`・`adapters-v1`・`v1-queries`・`merge-v1`・`classify`）が無い。
  ② `serving_queries.yaml` に `db: v1`・`v1_table`・`only_existing` が無い。③ `--mode snapshot` が（DB が無い環境で）原因の分かるエラーで止まる。④ 上記テストが緑。
  サンプル v2 での実際の出力（`serving_snapshot.json` の生成）は統合者が回す。

---

## 4. 担当 C: web/src・D1 スキーマ・registry（caveat）

触るファイル: `web/src/**`、`registry/caveat.yaml`、`scripts/registry/build_caveat.py`、`web/src/lib/registry/generated*.ts`（再生成）。
**触らない**: `scripts/**`（上の `build_caveat.py` を除く）・`web/scripts/**`・`.github/`・文書・`web/drizzle/migrations/`（統合者）。

### 4.1 `web/src/db/schema.ts`

§1.3 の46表の export と、それだけが使う `index`/`uniqueIndex`・コメントを消す。残す24表は変えない。冒頭コメント（「3つの SQLite ファイル」「derived.sqlite」）を現状（残る原本は
`ryuiki`・`cells` 由来の表だけ）に直す。`web/src/lib/db.ts` の `TableInfo.schema` コメント（`d = derived`）・`features.ts`・`db-sqlite.ts` のコメントも同様に更新。
消した表を import している箇所があれば tsc が出す（`db.ts` は `import * as schema` だけ）。**`pnpm run db:generate` は統合者**。生成物の期待値: `0010` に `DROP TABLE` が **ちょうど46本**で、
他の文（`CREATE`/`ALTER`）が無いこと。

### 4.2 v1-references テスト（申し送り）

`web/src/lib/v1-references.test.ts`:
- 許可リストの **`src/db/schema.ts` 行を削除**（禁止表の定義が無くなるので、残すと「参照が無い（許可リストから消す）」で自分が落ちる）。
- **`src/lib/registry/generated-client.ts` は「消す」のではなく絞る**。`caveat_scope` の table スコープ行（派生表名）は消えるが、同じファイルに
  `scopeKind: "dataset"` の `scopeRef: "measurements"`/`"organism_records"`（facet の dataset キー。恒久）が残る。許可を `tables: ["measurements", "organism_records"]`・
  理由「dataset 型 scope の dataset キー」に変える。`generated.ts`・`series.ts`・`caveats.ts`・`occurrence.ts` の許可は変えない。
- 「`schema*.ts` を読んで全表が分類済み」のテストの `expect(defined.length).toBeGreaterThan(80)` は表数が減るので下げる（実測の下限、例: 35）。
  **足す**: `schema*.ts` の表が `FORBIDDEN_TABLES` と交わらない（DROP の退行防止）。
- ファイル冒頭コメントの「PR-5 で…」を現状に直す。

### 4.3 registry の table スコープと `censored`

- `scripts/registry/build_caveat.py`: `_build_table_scope_rows()` が作る **v1 の `'table'`/`'table_prefix'` 行のうち、DROP される表名のもの**を作らなくする
  （`MEASURE_TABLES`・`ORGANISM_TABLES`・`MESH_TABLE_PREFIX`/`MESH_TABLES_EXTRA`・`IAS_TABLE`・`LANDUSE_TABLES`・`SYNTHETIC_TABLES` とそれらの `add_table_group` 呼び出し）。
  **`sites` の table スコープ（`SITES_CAVEATS`: zone/municipality）は残す**（`sites` は D1 に残り、`ai/tools.ts` が `caveatKeysForTables(["sites","source_registry"])` で引く）。
  dataset/variable/place_kind/source の facet 行（v2）は変えない。モジュール docstring の `'table'` 説明を更新。
- **`censored`（zero 系列を名指しする旧キー）**: v1 の table 行が無くなると、参照されるのは **`web/src/app/page.tsx:191` の `caveatBody("censored")` だけ**になり、ホームの
  注記が画面の実際の値（lod）と食い違う。**推奨（要決定 D-1）: `censored` キーを `registry/caveat.yaml` から削除し、`page.tsx` を `caveatBody("censoredLod")` にする**
  （同じ意味の2キーを残すと再発する）。`MEASURE_CAVEATS`（v1 用の複製リスト）も消す。`web/src/lib/ai/caveats.test.ts`（スナップショット・34ケース）・`cube/caveats.test.ts`
  の `withCensoredLod`（v1 のキー `censored` を差し替える関数）・`registry/generated.test.ts:103`（「v1 は v2 facet を足しても1行も減らない」）を実態に合わせて直す。
  `caveat.yaml` 冒頭の長い v1 説明コメントも、事実（v1 の table 行は撤去済み）に縮める。ADR-0009 の2026-09-24追記が残した申し送り（`censoredZero/Lod` に key を分ける）は
  「`censored` を撤去して `censoredLod` に一本化した」と D が追記する。
- 再生成: `RYUIKI_REGISTRY_DB=<絶対パス> python3 scripts/r01_build_registry.py --files-only` → `cd web && node scripts/build-registry-ts.mjs`（CI の `registry` ジョブと同じ手順。
  原本不要）。`generated.ts`/`generated-client.ts` の差分は table スコープ行の消滅と `censored` の消滅だけのはず。**フルビルド（`r01`）の検証は b00 で統合者が行う**。

### 4.4 そのほか（web/src）

- `web/src/lib/cube/integration.test.ts`・`pr4-integration.test.ts` を削除（§1.2）。他の `cube/*.test.ts` に残る `derived.sqlite`/`v1_projection` の言及は、実 DB を読むものが無いことを確かめてコメントだけ直す。
- `features.ts` のコメント: 「PR-5 で v1 の表を DROP するまで true に戻さない」→「v1 の表は DROP 済み。`EXPLORE_ENABLED` を戻すかは別の判断（任意 SQL と全表スキャンが公開 URL に出る問題は残る。範囲外）」。
  `/api/schema`・`/api/sql`・`/api/table` は**閉じたまま**。`db.ts` の `assertCatalogOnly` のコメント（「PR-5 で集合が空になり無害」）も現状に直す（内部表の除外として残る）。
- `table-meta.ts`・`ai/prompt.ts`・`queries.ts` は作業なし（§1.2）。ただし `TABLE_ORIGIN` に残る表が schema の残る24表＋cube・registry と過不足ないことは v1-references のテストが見る。

### 4.5 速い検証と完了条件

- 速い検証: `cd web && pnpm exec vitest run src/lib/v1-references.test.ts src/lib/registry src/lib/ai src/lib/cube && pnpm exec tsc --noEmit && pnpm run lint`
  （`registry/generated.test.ts` は `registry.sqlite` を要る。`--files-only` で作ったものを `RYUIKI_REGISTRY_DB` に渡す）。
- 完了条件: ① `FORBIDDEN_TABLES` のどの語も `web/src` の許可リスト外に出ず、許可リストは generated.ts/-client.ts（dataset キー）・series.ts・caveats.ts・occurrence.ts の5項目だけ。
  ② `schema*.ts` に禁止表が無い。③ `generated-client.ts` の `scopeKind: "table"` 行が `sites` だけ。④ ホームの注記が `censoredLod`。⑤ 上記テストが緑。

---

## 5. 担当 D: インフラ・シード・CI・文書

触るファイル: `web/scripts/{build-derived,build-biota,build-geo}.mjs`（削除）・`seed-d1-local.mjs`・`export-d1-sql.mjs`・`verify-d1-remote.mjs`・`docker-entrypoint.sh`・`ensure-*.sh`・
`web/package.json`（**`build:derived` の行ほか。`serving:diff` の行は B**）、`web/Dockerfile`、`docker-compose.yml`、`.github/workflows/ci.yml`、`DEPLOYMENT.md`、`CLAUDE.md`、
`web/README.md`、`docs/**`、`.gitignore`・`pytest.ini`・`requirements.txt` のコメント。
**触らない**: `scripts/**`（A）、`web/src/**`（C）、`web/scripts/lib/serving/**`（B）。

### 5.1 web/scripts と package.json

- `build-derived.mjs`・`build-geo.mjs`・`build-biota.mjs` を削除。`web/package.json`: `build:derived` を **`build:water-geo`（= `node scripts/build-water-geo.mjs`）に改名**。
  `build-water-geo.mjs` は `ryuiki.sqlite` と `data/processed` だけを読み `derived.sqlite` に依存しない（確認済み）。`predb:setup`・`build:v2`・`prepare:*` は変えない。
- `seed-d1-local.mjs`: `SOURCES` から **`derived` を外す**。残り `ryuiki`/`cells`/`registry`/`v2` の4つ。D1 側に無い表名は targets に出ない仕組み（`owner map`）なので、他の変更は要らないはず。
  **確かめる**: シード対象が §1.3 の40表になること（実 D1 での確認は統合者）。冒頭コメント・`hint`・「原本 3 ファイル」の記述を直す。原本の指紋（`_seed_state`）が変わるので、
  初回は全入れ直しになる（想定内。コメントに書く）。
- `export-d1-sql.mjs`・`verify-d1-remote.mjs`: 表の個別指定は無く D1 の表一覧から導くので変更は最小（コメントの `derived` 言及・`FIRST = ["documents"]` は残る24＋のままで正しい）。
  `--table` 指定の例を DEPLOYMENT.md 用に確認する（§7）。
- `docker-entrypoint.sh`: 手順1「集計 DB」を **「水源マップの GeoJSON（`data/processed/water_zones.geojson`）が無ければ `pnpm run build:water-geo`」** に置き換える（derived.sqlite は作らない・
  検査しない）。`ensure-registry.sh`・`ensure-v2.sh` はコメントの言及だけ。`docker-compose.yml` と `Dockerfile` のコメント（`derived.sqlite` を書く）を直す。
- `.gitignore`・`pytest.ini`・`requirements.txt` のコメントから b01/b02/derived_baseline の説明を落とす（`reports/derived_reconciliation*.md` の ignore 行は、生成元が消えるので削除）。

### 5.2 CI（`.github/workflows/ci.yml`）

- ファイル冒頭の長い説明を現状に縮める。
- `registry`・`web` ジョブは変更なし。
- `reconcile` ジョブ: `pytest`（A が v1 のテストを消した後の全体）、**`derived_baseline.json` の存在確認ステップを削除**、宣言ファイルの構造検証ステップから
  `expected_diffs`・`occurrence_watershed_v1_declarations.yaml`・`b08` の import・`baseline` の読み込みを外す（`period_exceptions`・`time_label_conventions`・`source_regions`・
  `occurrence_period_shapes`・`occurrence_cube_declarations`・`occurrence_place_declarations` は残す）、`taxon_assessment` の語彙検証は残す。ジョブ名・コメントの「b01〜b05」を直す。
- `sample-gate`: §3.4 のとおり。ジョブ名を `sample-gate (v2 pipeline invariants + frozen serving snapshot on the reduced sample)` に。
- `full-gate-proof-check`: `test -f reports/serving_fingerprint.json` と `python3 scripts/s04_check_full_gate_proof.py`（引数変更なし）。説明の「full_gate_proof」→「serving_fingerprint」。
- 追加のジョブは作らない。`web` ジョブの vitest は `scripts/**/*.test.ts` も走らせる（B の残すテストが載る）。

### 5.3 文書

- **`CLAUDE.md`**: 「87 テーブル」→ 実測値（見積もり41・シード40。統合者が確定値を渡す）。`derived.sqlite`／`build:derived` の記述（冒頭の開発環境・D1 シード入力・原本の段）を、
  「`derived.sqlite` は無い。シード入力は `ryuiki`/`cells`/`registry`/`v2` の4つ。`build:derived` は `build:water-geo`」に直す。「集計は `data/db/derived.sqlite` に分けて書く」の項を削除。
  実行順の要点（`r01 → b03 → … → b13（ここまでが build:v2）→ b05・b08 → b10・b11・b12 → b02`）を `… → b13` までに。「v1 との突合ゲート `b02`／`serving:diff`」の項を
  「層2＝`pnpm run serving:snapshot -- --mode snapshot`、層3＝b00 が書く `reports/serving_fingerprint.json`、スナップショット更新 PR は `--mode diff` の表を貼る」に。
  パイプラインのパスの規約の `reports/full_gate_proof.json` → `reports/serving_fingerprint.json`。`s02_materialize_sample.py` の規則は残す。ほかの段落は触らない。
- **`web/README.md`**: 表（`build-derived.mjs` 等）・図（`derived.sqlite ─┘`）・`build:derived` の記述を直す。
- **`docs/PIPELINE.md`**: v1 射影・b01/b02/b05/b08/b10〜b12・33表ゲートの節を撤去または「PR-5 で撤去」に。自己不変条件の置き場所（§2.2 の表）と §2.3 の検査、層2・層3の後継（§3・§2.4）を足す。
  `docs/plans/V2_SERVING.md` の PR-5 の「状態」を更新し、§5 の列挙の不足（§1.2 の「一覧に無い」）を補記。
- **ADR-0029**: 「差分カウントの道具」節の「**削除はしないが…CI では呼ばない**」を、**2026-10-06 追記**として上書きする: serving-diff は v1 側ごと削除（理由: v1 の oracle が消え、classify の特例が負債になる／過去の
  `reports/serving_switch_diff*.md` は記録として残す）。再利用したもの（`adapters-v2`・`serving_queries.yaml`）と新設の `serving-snapshot.mts`・`--mode diff`（更新 PR の表）・
  `serving_fingerprint.json` が `full_gate_proof.json` の置き換えであること・**b00 のパスに `web/src/lib/cube`（テスト除外）を足した**ことを書く。ADR-0027（層2・層3）・0009（`censored` 撤去）にも、
  既存の「追記」の書式で1行ポインタ。
- 本番切り替えの手順書は §7 を `DEPLOYMENT.md` に書く（既存の「更新するとき」の前に新しい節「v1 撤去後の本番切り替え（PR-5）」）。**デプロイはしない**。
  既存の手順の `pnpm run build:derived`（117行・221行）を直し、「データ: 61 テーブル」の現状表に「v1 撤去前」と注記する。

### 5.4 速い検証と完了条件

- 速い検証: `cd web && pnpm run lint && pnpm exec tsc --noEmit`、`node --check scripts/seed-d1-local.mjs scripts/export-d1-sql.mjs`、`sh -n scripts/docker-entrypoint.sh`、
  `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`。CI の各ステップのコマンドは実在するスクリプト・引数だけを呼ぶ（A・B の CLI は §2.4・§3.3 の通り）。
- 完了条件: ① `grep -rn "build:derived\|derived.sqlite" web/package.json web/scripts docker-compose.yml web/Dockerfile .github CLAUDE.md web/README.md DEPLOYMENT.md` が、
  「無くなった」という説明以外に残らない。② ci.yml に v1 の構築・33表ゲート・`derived_baseline`・`s05` が無い。③ ADR-0029 に追記がある。

---

## 6. 統合・受け入れ

### 6.1 担当の衝突表と統合順

| 担当 | 独占するパス |
|---|---|
| A | `scripts/**`、`data/sample/**`、`reports/derived_baseline.*`・`full_gate_proof.json` |
| B | `web/scripts/serving-*.mts`、`web/scripts/lib/serving/**`、`web/serving_queries.yaml`、`web/package.json` の `serving:*` 1行 |
| C | `web/src/**`、`registry/caveat.yaml`、`scripts/registry/build_caveat.py`、`generated*.ts` |
| D | その他の `web/scripts/*`、`web/package.json`（上記1行以外）、`.github/`、`docker-compose.yml`、`Dockerfile`、文書、ルート設定 |

例外: `scripts/registry/build_caveat.py` は A の `scripts/**` に入るが **C が持つ**（A は触らない）。統合順: **A → C → B → D**（A が `scripts/` を整理し、C が registry を直し、
B が executor、D が最後に CI・文書を実態に合わせる）。A・C は互いに独立なので並行でよいが、`build_caveat.py` の変更は b00 のパス（`scripts/registry`）を動かす点だけ A に申し送る。

### 6.2 統合者（メイン）の作業

1. 4つをマージ。`cd web && pnpm run db:generate` を1回 → `0010_*.sql` の中身が `DROP TABLE` 46本だけ（§4.1）。`meta/` は生成物。
2. 速い検証を一通り（vitest・tsc・lint・pytest）。**検証が本番の経路を通っているか**を先に見る: executor が呼ぶのが画面・API・AI と同じ `@/lib/cube` の公開関数
   （`adapters-v2` の対応表）か。
3. ローカル D1 に `0010` を当てる: seed 済みの D1 に `pnpm run db:migrate` → 表数が41・`pnpm run db:seed` が通り40表・`describe_schema`/画面（`/`・`/sites`・`/timeseries`・`/biota`・`/documents`・`/map`・`/water`）が200。
4. **重い処理は最後に1回**: ① `.venv/bin/python3 scripts/b00_run_full_gate.py`（原本のある手元。`reports/serving_fingerprint.json` を書き、コミット）。
   ② サンプル: 一時ディレクトリへ `git clone` し CI と同じ手順（§3.4）で `serving_snapshot.json` を生成 → コミット → 再実行して差が無いこと。③ 同じ clone で pytest・vitest。
   `s02_materialize_sample.py` は clone の中でだけ（本物のチェックアウトで実行しない）。
5. PR 本文: 削除物の一覧（§1.2）、落とした問い合わせ id と理由（§3.2）、b00 の実測（再計算検査の所要時間・`changes_vs_previous`）、手順書の要約。**スナップショットの初回生成なので `--mode diff` の表は不要**（以後の PR で必須）。

### 6.3 受け入れ基準（メインが最後に確かめる）

1. `v1-references.test.ts` の許可リストが5項目（generated.ts・generated-client.ts〔dataset キー〕・series.ts・caveats.ts・occurrence.ts）だけ。`schema.ts` と table スコープ行の許可が無い。
2. `FORBIDDEN_TABLES` の46表が、`web/src`（許可外）・`scripts/`（歴史的コメント以外）・`web/scripts`・**`0010` 適用後のスキーマ（`sqlite_master`）**のどこにも無い。残る表が §1.3 の24＋cube・registry・summary。
3. b00 が7段＋executor で通り、`reports/serving_fingerprint.json` が新しい形・全 `serving_queries.yaml` の id を含み、`s04_check_full_gate_proof.py` が通る。`full_gate_proof.json` が無い。
4. サンプルスナップショットが CI 手順（§3.4）で再現し、`git diff --exit-code` が通る。空振り検査が通る。
5. §2.2 の移設が実在する変異テストで止まる。§2.3 の検査を、メインが **変異を当てて**（例: 実 v2 の `observation_agg` の1セルを手で書き換えた複製に対して）止まることまで見る（担当の「通りました」を信じない）。
6. `pytest`・`vitest`・`tsc --noEmit`・`pnpm run lint` が緑。`pnpm run test` で `generated.test.ts` が skip されない。
7. `grep` で `build:derived`・`derived.sqlite`・`b05_project`・`serving-diff` が、経緯の説明以外に出ない。CLAUDE.md の表数・手順が実測と一致。
8. `DEPLOYMENT.md` に §7 の手順書がある。**本番へは何も出していない**（`wrangler ... --remote` を実行していない）。

---

## 7. `DEPLOYMENT.md` に足す節の骨子（D が書く）

題: 「v1 撤去後の本番切り替え（PR-5）」。冒頭に **「DROP のマイグレーション `0010` をコードのデプロイより先に当てると、旧コードが読む表が消えて全画面が落ちる。順序を守る」**。
本番 D1 は v1 撤去前のスキーマ（`0000`〜）で動いている。**`pnpm run db:migrate:remote` は未適用を全部（`0010` を含めて）当ててしまう**ので、手順 A では `0010` が無いツリーから当てる。

1. **事前**: `git tag pre-v1-removal d6af36c`（PR-4 マージ時点。`0009` までを含み `0010` を含まない）。`pnpm wrangler d1 migrations list ryuiki --remote` で本番の適用済みを確認。
   Time Travel の戻し先（直前の時刻）を控える（過去30日）。rows written の予算（5,000万行/月まで込み）に対し、投入のやり直しの回数を数える。
2. **A. 加えるだけのマイグレーションと新データの投入（旧コードのまま。画面は落ちない）**
   - `pre-v1-removal` を別ディレクトリに `git worktree` で出し、そこで `pnpm run db:migrate:remote`（`0001`〜`0009` が当たる。`0009` は `cells` の部分索引で、**投入の後・コードの前でよい**＝この段で当てて構わない）。
   - 新しい表だけを書き出して流す: `pnpm run db:export -- --table observation_agg,occurrence_agg,summary_variable_catalog,summary_place_variable,summary_taxon_catalog,summary_watershed_occurrence,summary_species_catalog,summary_group_year,summary_effort_year,summary_grid_catalog,unit,variable,variable_alias,place,place_source_ref,place_relation,place_watershed,taxon,taxon_assessment,caveat,caveat_scope`
     （表名は `table-meta.ts` の v2・reg の一覧と照合してから。既存の「3. データを入れる」のファイル単位の再試行ループをそのまま使う）。**入れる前に `v2.sqlite` の鮮度（`check_v2_fresh.py`）と `serving_fingerprint.json` の `git_head` が今のコードであること**を確かめる。
   - 行数検証: `pnpm run db:verify:remote`（新表の行数がローカル D1 と一致。旧表は変わっていない）。
3. **B. コードをデプロイ**: `feat/48-pr5`（マージ後の main）で `pnpm run deploy`。この時点では v1 の表がまだ残っているが、新コードは読まない。デプロイ後の動作確認（既存「6. 動作確認」に加え、`/`・`/sites`・`/timeseries`・`/biota`・`/documents`・`/map` が200で、値が
   `reports/serving_fingerprint.json`／サンプルの代表値と矛盾しないこと、AI の注記が出ること）。**ここで問題が出たら、旧コードへ `wrangler rollback` するだけで戻れる**（DROP はまだ）。
4. **C. DROP**: 十分に様子を見てから main のツリーで `pnpm run db:migrate:remote`（`0010`。46表が消える。**戻すには Time Travel**）。`pnpm wrangler d1 info ryuiki` でサイズ（約1.3GB → 500〜900MB の見込み）と表数（41）を確認。もう一度 §B の動作確認。
5. **ロールバック表**: A の失敗 = 新表を `DELETE`/`DROP` して再投入（旧画面に影響なし）。B の失敗 = `wrangler rollback`。C の失敗 = Time Travel（`0010` の直前）＋旧コードの再デプロイ。
6. **やらないこと**: `wrangler d1 export` は大きい表で OOM するので使わない。`0010` を A より先に当てない。サイズ見積もりの根拠は `V2_SERVING.md` §8。
7. 本番切り替えは「v1 撤去が終わるまで本番にデプロイしない」方針により、この PR のマージ**後**に別途判断する。

---

## 8. 要決定（推奨つき）

| # | 論点 | 推奨 |
|---|---|---|
| **D-1** | `registry/caveat.yaml` の `censored`（「0 とみなして集計」）。**書き換えるより削除して `censoredLod` に一本化する**（v1 の table 行が消えると読み手はホームの `page.tsx:191` だけで、同じ意味の2キーが残ると再発する）。 | 削除＋`page.tsx` を `censoredLod` へ（§4.3）。オーナー指示の「本文を直す」は「画面が lod になるよう直す」と解釈。 |
| **D-2** | b00 の証明のパスに `web/src/lib/cube`（テスト・fixture 除く）を入れる。cube の非テストコードを触るたびに原本のある手元で b00 の再実行が要る（摩擦）。入れないと「全量で通った指紋」が今の問い合わせ層に対応する保証を失う。 | 入れる（摩擦は受け入れる。fingerprint が cube の出力そのものなので）。 |
| **D-3** | `full_gate_proof.json` と `serving_fingerprint.json` は併存せず置き換え（併存させると v1 前提の証明が古いまま残る）。 | 置き換え（§2.4）。 |
| D-4 | b03 の `--include-synthetic` と合成データ除外の宣言は v1互換キューブ専用だが、PR-5 では**残す**（b03 本体を触るとパイプラインの挙動の確認が増える）。撤去は PR-6 の整理に回す。 | 残す。 |

要決定は D-1〜D-3（いずれも推奨で進めてよい。D-4 は範囲の線引き）。

**決定（2026-10-06、メイン）**: D-1〜D-4 はすべて推奨どおり。serving-diff は v1 側ごと削除・PR-5 は1本（オーナー決定）。
