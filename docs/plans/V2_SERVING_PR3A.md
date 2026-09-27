# Issue #48 PR-3a「パイプライン（値は動かない）」実装設計

前提: main（PR-2 マージ済み、`02a04f4`）。実測は 2026-09-27 に main の `data/db/v2.sqlite`（`scripts/check_v2_fresh.py` → exit 0、11:04 に `build:v2` 完了直後）・`registry.sqlite`（同 11:04）・`ryuiki.sqlite`・`derived.sqlite` を `mode=ro` で読んだもの（§付録）。作業中に別 worktree の `build:v2` が同時に走っており（CLAUDE.md「同じ重いコマンドを並行で走らせない」の注意対象）、一部の測定は一時 `database is locked` になったので、完了を待って取り直した。

## 0. 要点（先に読む）

1. **`occurrence_agg` は「place_kind × grain 族」の行列にする。** 族は `year` 族＝`{year, survey_period}`（既存。日付あり全記録の分割）と `month` 族＝`{month}`（同一月に収まる記録だけの分割。ADR-0024 決定3を守るため `year`/区間の記録は入らない）。PR-3a で作るのは **grid01×year（既存 471,060）・watershed×year（395,735）・grid01×month（570,803）の3マス＝計 1,437,598 セル**（今の3.05倍）。watershed×month（507,789）は消費者が無いので作らない（コードは行列を宣言表で持ち、足すのは1行）。流域に解決できない記録（日付あり 83,515）は **`place_kind='watershed'`・`place_id NULL` のセルとして持つ**（ADR-0025 D2「データを落とさない」と同じ。流域族も L2 の完全な分割になり、保存則が「族ごとに Σn = 日付あり行数」の一本に揃う）。測度は `n`/`n_red_list` に **`n_alien`（`SUM(is_alien)`）を足す**（PR-3b の `/map`・`get_overview` が v1 `org_watershed.alien_n` を要る。`is_alien` は (source, taxon_key) ごとに一定〔実測: 混在0〕なので加法で正確）。
2. **b07 の検証は「族 × place_kind」ごとに同じ4本を回す形に一般化する**: (i) 系列 (place_kind, source_id, taxon_id) ごとの Σn/Σn_red_list/Σn_alien が **その族の母集団**（grid01: 日付あり行、watershed: 日付あり行 ⋈ `occurrence_place`、month 族: 同一月の行）と一致、(ii) staging の `SUM(n) GROUP BY place_kind, grain` が宣言値と一致、(iii) セルの形（年は暦年境界・leaf は年またぎ・**月は `YYYY-MM-01`〜月末**）、(iv) **月セルは年セルの部分和**（同じ (次元, 年) で Σ月セル ≤ 年セル n）。流域の保存則は「解決 733,341 ＋ NULL 83,515 ＝ 日付あり 816,856」を宣言2件で固定し、b09 の宣言（解決 737,407 ≥ 日付あり解決）とも突き合わせる。**b07 は `occurrence_place` を読むので実行順は b06 → b09 → b07 に固定**（「入れ替え可能」を CLAUDE.md から外す）。指紋は `occurrence_agg.inputs = {occurrence, occurrence_place}` にし、b13 は既存の再帰系譜検査でそのまま両方を見る。
3. **v1 は動かさない。** b08 の `species_month`（L2 から）・`org_watershed(_year)`（L2＋メモ式）は1バイトも変えない（PR-5 で消える）。b08 には (a) 年キー8表の SQL に `grain IN (year 族)` の絞り込みを足す（**足さないと月セルを二重に数える。`_assert_cube_is_current_l2_partition` が Σn 不一致で止めるので黙っては壊れない**）、(b) 新設の検証「キューブの流域セル（year 族・place_id NOT NULL）を (watershed_id, year) に畳んだ n/redlist_n/alien_n ＝ b08 自身の `org_watershed_year_exact`（記録自身の正確な解決で同じ式を集計し直したもの）」を足し、その `org_watershed_year_exact` を TEMP ではなく実表として `v1_projection_occurrence.sqlite` に残す。これで PR-3b の serving-diff は PR-2 の「説明の鎖」に **`v1 →(watershed_memo)→ exact →(=)→ v2`** の段を1つ足すだけで流域の1,091キーを説明できる（Sirosporium は `expected_diffs.yaml` の `species2` 1キー＝既存の `declared` 段）。`species_month` は「月セルに入らない記録」（同一年内で月をまたぐ区間 157 件、'Z' の月ずれ最大10件）で最大 838 キーが動く見込み（PR-3b の規則 `month_cell_membership`）。
4. **`taxon.vernacular_name_en` は `organism_records.vernacular_name` のうちラテン文字だけの値を (名前空間, taxon_key) ごとに最頻→同数なら値の昇順で1つ選ぶ**（build_taxon の代表選びと同じ母集団・同じタイブレーク流儀）。実測: gbif 566/21,234 taxon・inat 6,741/13,978 taxon に付く。複数候補は 93、同数は 5 だけ。**ただし決定2をそのまま適用すると PR-3b で上位種（n≥80、1,702種）の 1,402 種の表示名が変わり、うち 1,365 種は和名を失う**——v1 の `species2.en_name` は実は記録の和名（GBIF 側の日本語）を `MAX()` で拾っていた「英名」ではない列で、レジストリ `taxon.vernacular_name_ja` は gbif 2,371/21,234 にしか無いため。**記録由来の和名（非ラテン文字の最頻値）で NULL を埋める補完を同じ r01 で行うと 475/1,702 に減る**（残りは v1 の `MAX()` が中国語名等を拾っていた改善分と、RL 表由来の和名との食い違い 108 件）。→ 決めてほしいこと D4。
5. **summary の生物2表（`summary_taxon_catalog`・`summary_watershed_occurrence`）は PR-3a の b13 で作る。** 実測でキューブ直読みの種カタログ 1,837ms・流域ロールアップ相当 1,245ms（471k セル時点。1.44M セルでは 3〜4 秒）で、事前計算が要ることは確定。b13 の語彙拡張（`source: occurrence_agg`、`count_distinct` に `expr`）はパイプライン側の仕事で値は動かないので、PR-3b を web＋serving-diff だけにできる。
6. **D1**: `occurrence_agg` に `n_alien` 列と第3索引 `(place_kind, grain, period_start)` を足す（族が2つ・place_kind が2つになったので全消費者が両方で絞る。年の地図〔メッシュ／流域〕は既存2索引では全表走査になる）。`taxon` に `vernacular_name_en`（＋補完の根拠列）。summary 2表。**Drizzle の `db:generate` は統合時に1回だけ**（worktree ごとに走らせると `0007_*` が衝突する）。容量: 1.44M セル ≈ 380MB（＋第3索引 ≈ 45MB）、D1 全体は 500〜900MB → 800〜1,250MB の見込み。
7. **作業は5単位・4 worktree**（U1 b07＋宣言＋s01 / U2 b08 / U3 r01 taxon / U4 b13＋serving.yaml / U5 docs＝統合者）。速い検証は各ファイルの pytest（秒）＋実データ実行1回。重い検証（`build:v2`→`db:reset`→s01 再生成→`b00`→CI clone 再現）は統合後に1回。

## 決めてほしいこと（最小限）

| # | 論点 | 推奨 |
|---|---|---|
| D1 | 流域に解決できない日付あり記録 83,515 件を `place_kind='watershed', place_id NULL` のセルとして持つか | **持つ**（族が L2 の分割になり保存則が1本で済む。画面は `place_id IS NOT NULL` で絞る。「流域外 10%」は AI の封筒の coverage に出せる情報） |
| D2 | watershed×month を作るか | **作らない**（消費者なし。+507,789 セル。行列の宣言に1行足せば後から作れる） |
| D3 | 測度 `n_alien` を足すか（列追加＝Drizzle 変更・spec 版上げ） | **足す**（v1 `org_watershed.alien_n`/`watershed_rollup.org_alien_n` の後継。JOIN で導くより加法で正確・速い） |
| D4 | `vernacular_name_ja` の記録由来補完（NULL 行だけ、最頻の非ラテン文字名。根拠列 `vernacular_ja_basis ∈ {override, taxa, records}`）を r01 で行うか | **行う**（行わないと PR-3b で上位種の 80% が和名を失う。既存の値は1件も変えない） |
| D5 | summary 生物2表を PR-3a で作るか | **作る**（§6。PR-3b で列を足すなら spec 版を上げるだけで b13 は数秒） |
| D6 | 第3索引 `(place_kind, grain, period_start)`（ADR-0030 D3 の追記） | **張る**（年の地図クエリが全表走査になるのを避ける。約 +45MB） |
| D7 | `taxon_assessment.in_scope`（除外7種、ADR-0030 D2）を PR-3a の U3 に含めるか | **含める**（r01 だけの小さな変更・値は動かない。PR-3b は読むだけになる） |

---

## 1. `occurrence_agg` に足すセル

### 1.1 行列（place_kind × grain 族）

| | year 族 `{year, survey_period}` | month 族 `{month}` |
|---|---|---|
| `grid01` | 既存 471,060（year 469,933・leaf 1,127） | **新 570,803**（NULL place 0） |
| `watershed` | **新 395,735**（year 394,609〔うち NULL place 33,232〕・leaf 1,126〔NULL 67〕） | 作らない（実測 507,789、NULL 49,381） |

- 鍵は ADR-0025 D2 のまま 8 列（`region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end`）。**スキーマ変更なしで着手できる**という #33 の前提どおり。`place_kind` は各族の INSERT でリテラル（`'grid01'`/`'watershed'`）を入れ、`occurrence.place_kind` から写さない（NULL place のセルでも族の識別子が必ず入る。b07 は起動時に `occurrence.place_kind` が日付あり全行で `'grid01'` であることを別途確かめる）。
- **流域の解決**: `occurrence o JOIN occurrence_place op ON op.record_id=o.record_id AND op.place_kind='watershed'`、`place_id := op.place_id`（既に `common:place:watershed.…` の registry ID。b09 が `place_source_ref` から引いて焼いてある）。日付あり全行が `occurrence_place` に必ず1行持つこと（b08 の `_assert_population_has_occurrence_place` と同型）を b07 でも確かめる（b09 の回し忘れ・別スナップショット混在を検出）。
- **month 族の所属**: `substr(period_start,1,7) = substr(period_end,1,7)`（`_SAME_YEAR_EXPR` と同じ流儀で `_SAME_MONTH_EXPR` を1箇所に）。実測: 同一月 812,974 / 同一年だが月をまたぐ 2,691 / 年をまたぐ 1,191（合計 816,856 ✓）。`period_grain='year'`（1,797）と区間（月をまたぐもの）は月セルに入らない。セルの `period_start='YYYY-MM-01'`、`period_end` は月末——**SQLite の日時関数は使わない**（b07 の既存方針）。出現する `YYYY-MM` を DISTINCT で取り、Python `calendar.monthrange` で月末を引いた一時表 `__month_bounds(ym, period_start, period_end)` を JOIN する。
- 測度: `n`、`n_red_list`（既存式）、**`n_alien = SUM(is_alien)`**（D3）。`n_distinct_taxon` は非加法なので持たない（既存決定）。
- `built_from` は `'occurrence+occurrence_place'`。`spec_version` は新定数 **`OCCURRENCE_AGG_SPEC_VERSION = "phase-b-fact-slice/v2"`**（`scripts/migrate/common.py`。`OCCURRENCE_SPEC_VERSION` v1 は `occurrence`/`occurrence_place`〔b09〕用に据え置く。`V2_CUBE_SPEC_VERSIONS["occurrence_agg"]` を新定数に）。列追加と族の追加で過去のセル集合と比較できなくなるので上げる。`check_v2_fresh.py` は自動的に PR-2 時点の v2.sqlite を exit 10 で拒む（seed の入力拒否もこれに乗る）。
- 見積もり: 現在 471,060 セルで表 79.8MB＋索引 45.0MB＝124.7MB（265 B/セル）。1,437,598 セル → 約 380MB、第3索引で約 +45MB。b07 の実行時間は今の 16〜24s から、流域の母集団一時表（816k 行）＋3族の GROUP BY で 60〜90s 程度を見込む（実測: 同等の DISTINCT クエリが 6〜15s/本）。

### 1.2 PR-3b がこのキューブで答える問い（設計の当たり）

| PR-3b の問い | セル | 索引 |
|---|---|---|
| `species_month`（binom の月別、2018 以降、n≥80） | grid01×month を `taxon_id IN (binom の taxon)` で引き `substr(period_start,6,2)` で畳む | `(taxon_id, period_start)` 既存 |
| `species_year2`/`species_mesh_year`/`mesh_year`（年） | grid01×year（既存） | 既存2本＋第3索引（年の地図） |
| `org_watershed(_year)`（流域×年） | watershed×year、`place_id IS NOT NULL` | `(place_id, period_start)` 既存／全流域は summary |
| 種カタログ・流域ロールアップ | summary 2表（§6） | summary の索引 |
| `species_n`（v1 は学名全文の DISTINCT） | `COUNT(DISTINCT taxon_id)`（族が分割なので粗いキーで再集計しても正確） | — |

`species_n` の定義差（学名全文 → taxon_id）は PR-3b の serving-diff で新しい既知系統として数える（PR-3a では触らない）。

## 2. b07 の構築と検証（族 × place_kind）

### 2.1 コードの形（`scripts/b07_build_occurrence_cube.py`）

```python
YEAR_GRAIN_FAMILY  = ("year", "survey_period")   # 日付あり全記録の分割
MONTH_GRAIN_FAMILY = ("month",)                  # 同一月に収まる記録の分割
GRAIN_VALUES = YEAR_GRAIN_FAMILY + MONTH_GRAIN_FAMILY   # b08 が語彙検査に import（既存名を維持）
PLACE_KINDS = ("grid01", "watershed")

# 族名は `"year"`（`YEAR_GRAIN_FAMILY`）か `"month"`（`MONTH_GRAIN_FAMILY`）。
CELL_FAMILIES: tuple[tuple[str, str], ...] = (("grid01", "year"), ("grid01", "month"), ("watershed", "year"))  # D2 で watershed×month を足すなら1行
```

- 族ごとの**母集団**を place_kind ごとに一時表 `__pop_grid01`/`__pop_watershed`（`record_id, region_id, source_id, place_id, taxon_id, period_start, period_end, red_list_category, is_alien`）として1回だけ作る（grid01: `occurrence` の日付あり行、watershed: 上の JOIN）。年セル／leaf セル／月セルの INSERT は母集団表名と place_kind リテラルだけが違う同じ SQL（`_YEAR_CELLS_SQL` 等を `{population}`/`{place_kind}` のテンプレートに）。
- **(i) 系列 Σ の突合**は族ごとに `common.assert_grouped_totals_match`（FULL OUTER JOIN）で `__pop_*`（族の述語で絞る）と staging（`place_kind` と `grain IN 族` で絞る）を (place_kind, source_id, taxon_id) で突き合わせる。値列は `n, n_red_list, n_alien`。母集団の GROUP BY は族×place_kind ごとに1回（3回、各 ~32k 系列）。
- **(ii) 宣言との突合**（`scripts/migrate/occurrence_cube_declarations.yaml`。既存の流儀 `name -> {expected_row_count, note}` のまま4件に）:

  ```yaml
  leaf_cell_source_rows: 1191            # 既存。year 族の全 place_kind で同じ値を要求する（記録の属性なので place_kind に依らない）
  month_cell_source_rows: 812974         # 同一月に収まる日付あり記録。month 族の全 place_kind で同じ値
  watershed_dated_resolved_rows: 733341  # 日付あり ∧ occurrence_place.place_id NOT NULL（ADR-0026 の保存則の右辺と同じ数）
  watershed_dated_unresolved_rows: 83515 # 日付あり ∧ NULL。resolved + unresolved = 日付あり行数 を検算
  ```
  検査: `place_kind='grid01'`: leaf Σn = 1,191、year Σn = 日付あり − 1,191、month Σn = 812,974。`place_kind='watershed'`: 同上に加え、year 族の Σn を `place_id IS NULL` で分けて 733,341 / 83,515。さらに b09 の宣言（`occurrence_place_declarations.yaml` の `resolved_count` 737,407）≥ 733,341 を確かめる（両宣言の整合）。`_LEAF_DECLARATION_NAME` のスカラー前提（ADR-0025 D2 の申し送り）は宣言名の集合に置き換える。
- **(iii) 形**: 既存2本に「`grain='month'` の全行が `period_start LIKE '____-__-01'`、`substr(period_end,1,7)=substr(period_start,1,7)`、`substr(period_end,9,2) IN ('28','29','30','31')`」を足す（`__month_bounds` を使い回さず独立に検査）。フィクスチャで閏年2月を固定。
- **(iv) 月セルは年セルの部分和**: staging 自身で `SELECT … FROM (月セルを (次元, substr(period_start,1,4)) で Σn) m JOIN 年セル y ON 次元一致 WHERE m.s > y.n` が 0 件。年セルの無い月セルも 0 件（月に収まる記録は必ず同一年）。
- 次元キー一意（既存 `assert_dimension_key_unique`、`grain` が族を区別）。
- **変異テスト**（既存 `test_mutation_*` に倣う）: 月セルの述語を年の述語に差し替える → (ii) 月の宣言で止まる／流域母集団から NULL 行を落とす → (ii) unresolved で止まる／`_OCC…watershed` の JOIN を `LEFT JOIN` にして `place_kind` を書き間違える → 母集団の完全性検査で止まる／`n_alien` の式を `n_red_list` にすり替える → (i) で止まる。
- `main()` の内訳出力は族×place_kind の表にする。

### 2.2 b08 の変更（`scripts/b08_project_occurrence_v1.py`。出力13表の値は不変）

1. `_CUBE_SERIES_TOTALS_SQL`・`_OCC_AGG_ENRICHED_SQL` に `AND c.grain IN (YEAR_GRAIN_FAMILY)` を足す（`b07.YEAR_GRAIN_FAMILY` を import。grain の語彙検査は `b07.GRAIN_VALUES` のまま）。メッセージの「この2つの grain だけ」を直す。
2. **新検証 `_assert_watershed_cells_match_exact`**（`_build_watershed` の末尾、`org_watershed_year_exact` を作った直後）: `cube.occurrence_agg`（`place_kind='watershed' AND grain IN year 族 AND place_id IS NOT NULL`）を `place_watershed_lookup` で `watershed_id` に戻し `(watershed_id, CAST(substr(period_start,1,4) AS INT))` で `SUM(n), SUM(n_red_list), SUM(n_alien)` → `org_watershed_year_exact` の `n, redlist_n, alien_n` と `assert_grouped_totals_match`。年の式は一致する（同一年の記録は同じ年、leaf は開始年＝`period_raw` の先頭4桁、'Z' 変換は年を変えない〔b06 が保証〕）。**流域セルの保存則が、L2 から独立に組んだ b08 の式と一致することを毎ビルド確かめる**——これが「b08 の分割検証を place_kind ごとに拡張」の実体。`build_watershed_projections`（単独経路）は `need_occurrence_agg=True` にし、`assert_all_reads_verified` の declared に `occurrence_agg` を足す（`_assert_cube_is_current_l2_partition` 相当の検証を経ることを明記）。
3. `org_watershed_year_exact`（と `org_watershed_exact`）を TEMP ではなく実表として出力ファイルに残す（PR-3b の serving-diff が「exact」の点として読む。`projection_manifest.yaml`・`table_counts`・b02 の対象には入れない〔b02 は候補ファイルの余分な表を注記扱いで許容する。実測: `_compare_one_candidate` が `extra_tables` として返し `render_markdown` に渡すだけ〕。`test_build_all_projections_writes_org_norm_and_eleven_more_tables` は `table_counts` を見るので影響なし）。
4. テスト: `test_grain_month_cell_stops_projection` は「未知の grain（例 `'week'`）で止まる」に書き換え、「月セルがあっても年キー8表の Σn が変わらない」「流域セルがあっても mesh 系が変わらない」「流域セルと exact の不一致で止まる」を足す。`_build_cube_via_b07` は b07 が `occurrence_place` を要求するので、先に `occurrence_fixtures.add_occurrence_place_table` を通す（フィクスチャの `_OCCURRENCE_AGG_COLUMNS` に `n_alien` を足すのは U1）。

### 2.3 v1 との関係の結論

- `species_month`・`org_watershed(_year)` は **今のまま L2 から**（射影を新セルに付け替えない）。理由: (a) 値が動く（同一年内で月をまたぐ区間 157 件、'Z' の月ずれ ≤10 件、`species_n` の定義差）ので b02（33表・宣言20）が赤になる、(b) b08 は PR-5 で消える、(c) 代わりに 2.2-2 の検証で新セルと L2 の式の一致を保証できる。
- **PR-3b の説明の鎖への乗せ方**: 流域は `v1(org_watershed_year) →(watershed_memo: v1 と exact の差はメモ化の癖〔記録単位の宣言 11,306 件で機械検証済み〕)→ exact(org_watershed_year_exact) →(等しい)→ v2(キューブ)` ——`classify.ts` の `KnownRule` に `watershed_memo` を1つ足し、`ctx` に exact 行（`v1_projection_occurrence.sqlite` を第2接続で開く。PR-2 の `--v1compat-db` と同じ形）を持たせるだけ。`species_n` は列ごとの規則 `species_n_definition`（exact 側も学名 DISTINCT なので、この列は exact→v2 の段で説明）。Sirosporium は `expected_diffs.yaml` の `species2.cls` 1キー＝既存 `declared` 段。`species_month` は `month_cell_membership`（v1 行の記録に月セル非該当が含まれるか＝L2 を見る規則。上限 838 キー）。**PR-3a では `classify.ts` は触らない**（serving_queries に生物系の問い合わせがまだ無い）。

## 3. 指紋・実行順・鮮度

- b07: `place_fp = common.assert_stage_fingerprint_fresh(conn, "occurrence_place", upstream_schemas={}, rebuild_hint="scripts/b09_build_occurrence_place.py を再実行すること。")` を `assert_occurrence_fingerprint_fresh` の次に呼び、`staged_table(..., fingerprint_inputs={"occurrence": occ_fp, "occurrence_place": place_fp}, fingerprint_spec_version=OCCURRENCE_AGG_SPEC_VERSION)`。`record_v2_input_fingerprint` は呼ばない（b13 と同じ理由）。
- 実行順 **b06 → b09 → b07 → b13 → b08** に固定。`b00.PIPELINE_STEPS`・`web/package.json build:v2`・CI `sample-gate` は既にこの順（変更不要）。CLAUDE.md の「b09/b07 は互いに依存しないので入れ替え可能」を削り、`occurrence_agg` の説明（族×place_kind、`n_alien`）と `taxon.vernacular_name_en` を追記。
- b13 の `assert_stage_fingerprint_fresh(conn, "occurrence_agg", upstream_schemas={})` は系譜を再帰で辿るので `occurrence`/`occurrence_place` の古さも自動で検出する。
- `V2_PIPELINE_STAGE_MODULES` は変更不要（b07/b13 とも入っている。`scripts/migrate/*.yaml`・`aggregations/*.yaml` も指紋対象）。r01 の変更は `registry_build.input_fingerprint`（`scripts/registry/*.py`・`schema_registry.sql` を含む）が変わるので `ensure-registry.sh` → `ensure-v2.sh` の順に自動で作り直しになる。

## 4. `taxon.vernacular_name_en`（U3、`scripts/registry/build_taxon.py`）

- **出典**: `organism_records.vernacular_name`（原本 `ryuiki.sqlite`。iNat 行は iNat API の英語 common name〔116,705/116,711 行がラテン文字〕、GBIF 行はデータセット付属の俗名〔大半が日本語、566 taxon_key にラテン文字名〕）。`taxa` には和名しか無い（ラテン文字 0 件）。`taxon_crosswalk.csv` にも英名は無い。
- **決定論的な選び方**: `_load_occurrence_representatives` と同じ母集団（`taxon_key IS NOT NULL AND taxon_key<>''`、日付の有無を問わない）を `(名前空間, taxon_key, vernacular_name) → COUNT(*)` で1回集計し、Python 側で
  - ラテン文字判定: 文字がすべて `[\x20-\x7E]` ∪ U+00C0–U+024F（Latin-1/Extended の字母）∪ `’` の範囲（SQLite に正規表現が無いので Python で。`is_latin_script()` を `registry/common.py` に置きテストする）
  - 候補のうち `(-count, value)` の昇順の先頭（同数は値の昇順。実測: 複数候補 93 taxon、同数 5）
  - 候補が無ければ NULL（gbif の 95%、`ryuiki-taxa` 名前空間の全行）
  を選ぶ。`Amara sp.`（属の仮名）・`Kawa-Semi`（ローマ字）のような値も入る——「英名」ではなく「ラテン文字の俗名」であることを README に明記する。
- **和名の補完（D4）**: 同じ集計から非ラテン文字（ひらがな・カタカナ・CJK を含む）の最頻値を `vernacular_name_ja` が NULL の行にだけ入れ、`vernacular_ja_basis` に `override`（`vernacular_ja.csv` 54件）/ `taxa`（EXACT の `taxa` 行）/ `records` を記録する。優先順は override > taxa > records（既存の値は1件も変えない）。実測: gbif 14,003 taxon_key に記録由来の日本語名があり、うち 13,431 は今 NULL。GBIF の中国語データセット由来の名（例 `鹅耳枥叶枫`）は最頻値なら実用上ほぼ日本語に負ける（v1 の `MAX()` はこれを拾っていた——改善側の差分として PR-3b で数える）。
- **名前が変わる種数の見積もり（#48 決定2）**: v1 の表示 = `NAME_JA[binom] ?? species2.en_name ?? binom`。新表示を `NAME_JA ?? taxon.vernacular_name_ja ?? vernacular_name_en ?? binom` とすると全 23,618 種中 11,732、n≥80 の 1,702 種中 **1,402（うち和名→英名/学名 1,365）**。D4 の補完込みなら **1,698 / 475**。正式な数は PR-3b の差分表で確定する（この見積もりは binom 単位で `MIN(vernacular_name_ja)` を取った近似）。
- 変更ファイル: `scripts/schema_registry.sql`（`vernacular_name_en TEXT`, `vernacular_ja_basis TEXT`）、`build_taxon.py`（`TAXON_COLUMNS`・`_build_taxon_row`・新 `_load_vernacular_candidates`）、`scripts/tests/test_registry_taxon.py`（混在・同数・空文字・ローマ字・補完の優先順）、`registry/README.md`、`web/src/db/schema-registry.ts`（`vernacularNameEn`, `vernacularJaBasis`。コメントの「まだ無い（PR-3a）」を更新）。D7 を採るなら `build_taxon_assessment.py` に `in_scope INTEGER`（`assessment_scope_exclusions.yaml` の7種を 0）を同じ単位で。`web/scripts/build-registry-ts.mjs`（`generated*.ts`）は `taxon` を読まないので無変更。seed は registry 表を列の共通部分で入れるので、D1 側だけ列が増えても壊れない。

## 5. summary 生物2表（U4、`aggregations/serving.yaml` → `scripts/b13_build_summary.py`）

```yaml
spec_version: serving-summary/v2          # common.SUMMARY_SPEC_VERSION と一緒に上げる
summaries:
  summary_taxon_catalog:                  # v1 species2 の後継（binom 束ね・名前・RL は catalog.ts/taxon/taxon_assessment 側）
    source: occurrence_agg
    filter: { place_kind: grid01, grain: [year, survey_period] }
    group_by: [taxon_id]                  # taxon_id NULL も1行（落とさない）
    measures:
      n: {fn: sum, col: n}
      n_red_list: {fn: sum, col: n_red_list}
      n_alien: {fn: sum, col: n_alien}
      n_places: {fn: count_distinct, col: place_id}            # v1 mesh_n
      y_from: {fn: min, expr: year_of_period_start}
      y_to: {fn: max, expr: year_of_period_start}
      n_years: {fn: count_distinct, expr: year_of_period_start} # 語彙拡張: count_distinct に expr
    key: [taxon_id]
    indexes: [[taxon_id]]
  summary_watershed_occurrence:           # v1 org_watershed の後継（流域外 NULL も1行）
    source: occurrence_agg
    filter: { place_kind: watershed, grain: [year, survey_period] }
    group_by: [place_id]
    measures: { n: …, n_red_list: …, n_alien: …, n_taxa: {fn: count_distinct, col: taxon_id}, y_from: …, y_to: … }
    key: [place_id]
    indexes: [[place_id]]
```

- b13: `_ALLOWED_SOURCES` を `{observation_agg, occurrence_agg}` にし、次元キー・測度列の許容集合を source ごとに持つ（`b04.DIM_COLUMNS`/`b07.DIM_COLUMNS`、測度型 `n/n_red_list/n_alien: INTEGER`）。`count_distinct` の `expr` を許す。系譜は source ごとに `assert_stage_fingerprint_fresh(conn, source, upstream_schemas={})`。保存則（`SUM(n)` 一致）・一意性・行数>0 は既存のまま汎用。`V2_SUMMARY_TABLES` を4表に（`_validate_manifest_shape` の集合検査が守る）。`test_b13_build_summary.py` の `_REFERENCE_SQL` に2表分の独立 SQL とフィクスチャ `make_occurrence_agg_fixture`。docstring の「2表」を「4表」に。`web/src/db/schema-cube.ts` に2表（列は b13 の CREATE と完全一致。seed の完全一致検査が効く）。
- `catalog.ts`/`occurrence.ts` は PR-3b。

## 6. D1: Drizzle・索引・容量

- `web/src/db/schema-cube.ts`: `occurrenceAgg` に `nAlien: integer("n_alien").notNull()`、索引 `ix_occurrence_agg_kind_grain_period (place_kind, grain, period_start)`（D6）。`b07.OCCURRENCE_AGG_INDEXES` に同じ組を足す（`scripts/tests/test_cube_index_parity.py` が一致を強制）。summary 2表を追加。
- `web/src/db/schema-registry.ts`: `taxon` に2列（D7 なら `taxonAssessment.inScope`）。
- **`pnpm run db:generate` は統合者が1回**（`0007_*.sql`＋`meta`）。各 worktree は schema ファイルだけ編集し、`drizzle/migrations` を触らない。
- 容量（実測ベース）: `occurrence_agg` 125MB → 約 425MB（SQLite）。D1 での見積もり（PR-0 時 140MB）も ≈3.4 倍で 450〜480MB。D1 全体 500〜900MB → 800〜1,250MB（上限 10GB に余裕）。rows written は `db:reset` 1回あたり +100 万行程度増える（本番投入は PR-5 まで無い）。

## 7. サンプル・CI・b00

- `data/sample/declaration_counts.yaml` は **手で編集しない**。`scripts/s01_build_sample.py build_declaration_counts` に3キー（`occurrence_cube_declarations.yaml:month_cell_source_rows` / `:watershed_dated_resolved_rows` / `:watershed_dated_unresolved_rows`）を足す。月の判定は `observed_on` の桁数で近似せず、b06 が使う `migrate.occurrence_period` の展開（'Z' の region `utc_offset` 変換込み）を s01 から呼んで `period_start/end` を得てから同一月を数える（`compute_leaf_cell_source_rows` は年境界を 'Z' が越えない保証で近似が厳密だったが、月は 10 件ずれる）。流域2件は既存の `compute_occurrence_place_and_watershed_stats` の `exact_watershed` と `observed_on` から数える。統合時に main の checkout で `s01` を再実行し、`git diff` が `declaration_counts.yaml` の3行追加だけであることを確認する（`test_sample_coverage.py::test_declaration_counts_keys_match_declared_entries_exactly` が集合一致を強制）。
- CI `sample-gate`: 順序・引数とも変更不要（b07 は `--count-overlay` を受け取り済み）。「宣言ファイルの構造検証」ステップは `b07.validate_cube_declarations_shape` が4件の集合に変わるだけ。`s05` の期待宣言数 20 は不変（宣言済み差分は増えない）。
- `b00`: `PIPELINE_STEPS` 不変。証明対象パス（`scripts/b0*.py`・`scripts/registry`・`scripts/migrate`・`aggregations`・`scripts/schema_registry.sql`・`web/package.json`）を触るので `reports/full_gate_proof.json` の再生成が必須。

## 8. 作業の分け方

### 8.1 並行単位（worktree、ファイル衝突なし）

| 単位 | 触るファイル | 依存 |
|---|---|---|
| **U1 b07＋宣言＋s01** | `scripts/b07_build_occurrence_cube.py`、`scripts/migrate/occurrence_cube_declarations.yaml`、`scripts/migrate/common.py`（`OCCURRENCE_AGG_SPEC_VERSION`・`V2_CUBE_SPEC_VERSIONS`）、`scripts/s01_build_sample.py`、`scripts/tests/occurrence_fixtures.py`（`_OCCURRENCE_AGG_COLUMNS` に `n_alien`、`make_v2_db_with_occurrence_and_agg` が `occurrence_place` も作れるように）、`scripts/tests/test_b07_*.py`、`test_s01_build_sample.py`、`test_check_v2_fresh.py`/`test_migrate_common.py`（`occurrence_agg` の spec 定数差し替え） | なし。**最初のコミットで `YEAR_GRAIN_FAMILY`/`GRAIN_VALUES`/`CELL_FAMILIES`/`n_alien` の名前を出す**（U2/U4 が参照） |
| **U2 b08** | `scripts/b08_project_occurrence_v1.py`、`scripts/tests/test_b08_occurrence_cube_projections.py`、`test_b08_watershed_projections.py` | U1 の定数名・列名（合意済み）。実データの検証は統合後 |
| **U3 r01 taxon** | `scripts/registry/build_taxon.py`（D7 なら `build_taxon_assessment.py`）、`scripts/registry/common.py`（`is_latin_script`）、`scripts/schema_registry.sql`、`registry/README.md`、`scripts/tests/test_registry_taxon.py`、`web/src/db/schema-registry.ts` | なし |
| **U4 b13＋serving.yaml** | `scripts/b13_build_summary.py`、`aggregations/serving.yaml`、`scripts/migrate/common.py` の `SUMMARY_SPEC_VERSION`/`V2_SUMMARY_TABLES`（**U1 と同じファイル**——定数ブロックが別なので統合時の衝突は機械的に解ける。心配なら U1 の最初のコミットを取り込んでから着手）、`scripts/tests/test_b13_build_summary.py`、`web/src/db/schema-cube.ts`（summary 2表・`n_alien`・第3索引は U4 がまとめて書く） | U1 の `n_alien` 名 |
| **U5 docs（統合者）** | `docs/plans/V2_SERVING_PR3A.md`（本設計）、`docs/plans/V2_SERVING.md` PR-3a 節の状態、`docs/plans/PHASE_B_OCCURRENCE.md` §18（O-2b 実測）、`CLAUDE.md`、ADR-0025（状態→D4 実装済み、D2 に month/`n_alien` 追記）・ADR-0026（D4 追記）・ADR-0030（D2 の `place_watershed` の記述訂正〔O-2b に per-record 表は不要、流域セルは `place`/`place_watershed` に JOIN するだけ〕・D3 に第3索引）・ADR-0011（状態を「実装済み（observation/occurrence 両入力の宣言的集計）」に更新するかは統合者判断）、`web/drizzle/migrations/0007_*`（`db:generate` 1回）、`reports/full_gate_proof.json`、`data/sample/declaration_counts.yaml` | 全部のあと |

全担当共通の指示: スキル（/simplify・/code-review 等）やサブエージェントを起動しない。重い検証（`build:v2` の再実行を伴うもの・b00・CI 再現）は各担当では回さない。worktree には CLAUDE.md の手順で原本だけを symlink し、生成物は worktree 内に書く。`drizzle/migrations` を生成・コミットしない。

### 8.2 各単位の速い検証（秒〜1分）

- U1: `.venv/bin/python3 -m pytest scripts/tests/test_b07_build_occurrence_cube.py scripts/tests/test_s01_build_sample.py scripts/tests/test_migrate_common.py scripts/tests/test_check_v2_fresh.py -q`。実データは worktree で `b06 → b09 → b07` を**1回**（b09 約23s、b07 は新形で 60〜90s 見込み）、内訳が §付録の数字（1,437,598 セル、族×place_kind の Σn）と一致することを目視。
- U2: `pytest scripts/tests/test_b08_*.py -q`（`.venv`＝SQLite 3.43 以上）。
- U3: `pytest scripts/tests/test_registry_taxon.py scripts/tests/test_r01_invariants.py scripts/tests/test_r01_registry_atomic.py -q`、`r01_build_registry.py` を worktree で1回（診断出力に「vernacular_name_en が付いた行 = gbif 566 / inat 6,741」「和名補完 = 13,4xx」）、`--check-fresh` が 0。
- U4: `pytest scripts/tests/test_b13_build_summary.py -q`。
- 統合直後（重い検証の前、数分）: `pnpm run db:generate` → `pytest scripts/tests -q` 全件 → `test_cube_index_parity` 緑 → `cd web && pnpm run build:v2`（1回）→ `check_v2_fresh.py` = 0 → `pnpm run db:reset`（seed の列集合完全一致検査を通す）→ `pnpm vitest run`。

### 8.3 統合の最初のチェック「検証が本番の経路を通っているか」

1. b07 の新検証 (ii)(iii)(iv) が **staging（作ったキューブ）** を読んでいて、L2 の述語を数え直すだけになっていない（コードレビュー指摘1の再発防止。変異テスト4本が緑）。
2. b08 の `_CUBE_SERIES_TOTALS_SQL`/`_OCC_AGG_ENRICHED_SQL` に `grain IN YEAR_GRAIN_FAMILY` があり、統合後の b08 実行で `b02_run_all_gates` が「一致25／宣言のみ8／不一致0／宣言20」のまま（値が動いていない機械的な証拠）。
3. `seed-d1-local.mjs` が `occurrence_agg`・summary 2表の列集合完全一致で通る（Drizzle ↔ b07/b13 の CREATE の対応）。`test_cube_index_parity` 緑。
4. PR-2 時点の古い `v2.sqlite`（作業前にコピーしておく）に `check_v2_fresh.py` が exit 10 を返す（spec 版上げの効き目、手で1回）。
5. `data/sample/declaration_counts.yaml` の差分が s01 再実行由来の3行だけ。
6. b07/b13 が `record_v2_input_fingerprint` を呼んでいない（b09 の記録を上書きしない）。
7. `_assert_watershed_cells_match_exact` が実データで通る（キューブの流域セル＝L2 の正確な集計）。

### 8.4 PR 直前に1回だけ回す重い検証

1. `.venv/bin/python3 scripts/b00_run_full_gate.py`（v1 互換5段込み。PR-2 実測＋b07 の増分で 15〜20 分見込み）→ `reports/full_gate_proof.json` をコミット。
2. 「原本の無い環境」の再現: 一時ディレクトリへ `git clone` し、CI `sample-gate` の手順（pytest 全件 → r01 → b03…b13 with `--count-overlay` → b08…b12 → b02 → s05）を通す。
3. `pnpm run serving:diff --imputation zero --v1compat-db data/db/v2_v1compat.sqlite`（変異なし）を1回——測定値系の問い合わせは `occurrence_agg` を読まないので差は出ないはずだが、seed・Drizzle・common.py を触った PR の回帰証拠として PR 本文に貼る。
4. /code-review と /simplify を同時に → まとめて1回直す → 1〜2 を再実行。

## 9. 危険・未決事項

1. **セル数 3.05 倍**（471k → 1.44M）: b07 の時間・`db:reset` の rows written・D1 容量（§6）。watershed×month を足すと 1.95M。
2. **b08 の絞り込み忘れは検出されるが、b13 の `filter` に `grain` を書き忘れると summary が月セルを二重に数える**——保存則は「同じ filter のキューブ Σn」との比較なので気づけない。`test_b13` の `_REFERENCE_SQL` に族の絞り込みを独立に書き、YAML の検証で「`source: occurrence_agg` の summary は `filter.grain` を必須」にする。
3. **Drizzle 生成の衝突**（複数 worktree で `db:generate`）→ 統合者だけが1回。
4. **`s01` の再実行が他ファイルを動かす可能性**（`coverage.yaml`/`derived_keys.yaml`/`manifest.json`）。決定論テストがあるので同じ原本なら不変のはずだが、`git diff --stat data/sample` で確認する。
5. **ラテン文字判定の癖**: ローマ字（`Kawa-Semi`）・属の仮名（`Amara sp.`）・`Identity unknown` が `vernacular_name_en` に入りうる。最頻値で概ね英名が勝つ（`Common Kingfisher` vs `Kawa-Semi` の例）が、PR-3b の表示は `NAME_JA > ja > en > binom` の順なので露出は小さい。
6. **RL 表由来の和名と記録由来の和名の食い違い**（n≥80 で 108 件、例 `ニワウルシ（シンジュ）` vs `ニワウルシ`）: D4 の優先順（既存値を守る）で保留。PR-3b の差分表で見て決める。
7. **同時実行**: 今日も別 worktree の `build:v2` と重なって `database is locked` が出た。統合の `build:v2`・b00 は単独で走らせる。
8. **ADR-0030 D2 の `place_watershed` の記述**が O-2b の設計と食い違っている（per-record の解決結果ではなく流域属性サテライト）。U5 で訂正の追記。
9. **PR-3b への申し送り**: 既知系統の追加は `watershed_memo`・`species_n_definition`・`month_cell_membership`・`vernacular_label_rule`（表示名）の4つ。`serving_queries.yaml` の生物系 ID と v1 側の束ね（binom 単位）は PR-3b 設計で決める。

## 付録: 実測（2026-09-27、main、読み取り専用）

```
occurrence（日付あり）816,856: day 740,323 / instant 68,576 / month 1,320 / survey_period 4,840 / year 1,797
  同一月 812,974 / 同一年で月をまたぐ 2,691 / 年をまたぐ 1,191
  流域: 日付あり解決 733,341 / NULL 83,515（b09 宣言: 解決 737,407 / NULL 86,285、母集団 823,692）
occurrence_agg（現状）471,060（year 469,933・leaf 1,127）: 表 79.8MB + 索引 23.8MB + 21.2MB
新セル: watershed×year 394,609（NULL place 33,232）+ leaf 1,126（NULL 67）／grid01×month 570,803／watershed×month 507,789（NULL 49,381、作らない）
性能（Python sqlite3）: taxon の年系列（索引）9ms／place 全表ロールアップ 1,245ms／種カタログ全表 1,837ms（471k セル時点）
俗名: 記録 685,424 件に俗名。gbif 568,713（ラテン 271,743／非ラテン 296,970）、inat 116,711（ラテン 116,705）
  ラテン文字名を持つ taxon_key: gbif 566/19,635、inat 6,741/13,978。複数候補 93、最頻同数 5
  registry taxon 和名: gbif 2,371/21,234、inat 11/13,978、ryuiki-taxa 6,242/6,242
  記録に日本語名のある gbif key 14,003、うち registry が和名 NULL 13,431
  v1 species2.en_name（23,618）: 空 7,239 / ラテン 4,512 / 非ラテン 11,867（n≥80 の 1,702: 54/219/1,429）
  表示名の変化見積もり: en のみ → 11,732（n≥80: 1,402、和名喪失 1,365）／和名補完込み → 1,698（n≥80: 475）
species_month（v1 9,997 行）: 月セル非該当の寄与 157 記録（21桁の日区間）、'Z' 記録 1,336（月ずれは全データで 10）、触れるキー上限 838
is_alien: (source, taxon_key) ごとに一定（混在 0）。red_list_category も同様
```

---
## 設計責任者の決定（2026-09-27）
- D1〜D7 すべて採用。D4（記録由来の和名補完）は PR 本文でオーナーに確認を求める点として明記する。
- 設計書はリポジトリに `docs/plans/V2_SERVING_PR3A.md` としてコミットする（統合者）。
- 並行: U1〜U4 を別 worktree で同時に。U5（docs・`db:generate`・証明・サンプル再生成）は統合者。
- 全担当共通: スキル（/simplify・/code-review 等）やサブエージェントを起動しない。重い検証（b00・CI 再現・serving-diff）は回さない。`drizzle/migrations` を生成・コミットしない。worktree には原本だけを1ファイルずつ symlink し、生成物は worktree 内に書く。**同じ重い処理（build:v2 等）を他の worktree と同時に走らせると `database is locked` になりうるので、元チェックアウトの data/db は読まない**（symlink は原本だけ）。

## 実測の記録（統合後、2026-09-27）

U1〜U4 の worktree を `feat/48-pr3a` に統合し、実データで検証した結果を記録する（詳細な数字・チェック表は PR 本文参照）。

- `build:v2`（registry → observation/observation_agg → occurrence/occurrence_place → occurrence_agg → summary）を実データで1回通し、`occurrence_agg` が設計どおり 1,437,598 セル（grid01×year 469,933+leaf 1,127・grid01×month 570,803・watershed×year 394,609〔解決 733,341/未解決 83,515〕+leaf 1,126）になることを確認した。
- `b08_project_occurrence_v1.py` を実データで1回通し、`_assert_watershed_cells_match_exact` が例外なく通った（キューブの流域セル＝ `occurrence`+`occurrence_place` から独立に組んだ集計と完全一致）。`org_watershed` 系のメモ化差分（`memo_moved_records=11,306`・`memo_mixed_buckets=741`・`org_watershed_year_keys_changed_vs_exact=1,091`）は §付録の見積もりと一致した。
- `scripts/b02_run_all_gates.py`（v1 互換の診断キューブ経由）で 33表中 一致25／宣言のみ8／不一致0／宣言済み差分20件——PR-3a 前と同じ結果（値が動いていないことの機械的な証拠）。
- `scripts/check_v2_fresh.py` は新しい `v2.sqlite` に対して exit 0、PR-2 時点の古い `v2.sqlite`（`occurrence_agg.spec_version='phase-b-fact-slice/v1'` 等）に対して exit 10 を返すことを確認した。
- `pnpm run db:generate` を統合時に1回だけ実行し、`web/drizzle/migrations/0007_awesome_cobalt_man.sql`（`occurrence_agg.n_alien`＋第3索引、`taxon.vernacular_name_en`/`vernacular_ja_basis`、`taxon_assessment.in_scope`、`summary_taxon_catalog`/`summary_watershed_occurrence` の2表）を作った。`n_alien` はデータの入った既存 D1 で `ALTER TABLE ADD COLUMN ... NOT NULL` が既定値なしでは失敗するため（`web/src/db/schema-cube.ts` の `nAlien` に `.default(0)`）、統合後の /code-review で `0007_past_siren.sql` を作り直したもの（ファイル名は `db:generate` が乱数で振る）。
- `scripts/s01_build_sample.py` を再実行し、`data/sample/declaration_counts.yaml` に新3キーが追加されたことを確認した（他のサンプルファイルは `manifest.json` の `generated_at` 以外変化なし）。
- `pnpm run db:migrate && node scripts/seed-d1-local.mjs` で列集合完全一致のままシードが通り（87テーブル、うち86が seed 対象。`occurrence_agg` 1,437,598行・`summary_taxon_catalog` 32,186行・`summary_watershed_occurrence` 288行を含む）、`pnpm test`・`npx tsc --noEmit`・`pnpm lint`・`pytest scripts/tests -q`（`test_s04_*` の証明鮮度検査だけが想定内の失敗）がいずれも緑だった。

## /code-review・/simplify 指摘の修正（統合後、2026-09-27）

1. **D4（和名の記録由来補完）の誤補完を修正**（`scripts/registry/build_taxon.py`・`scripts/registry/common.py`）。実データで r01 を1回回した結果: 和名の記録由来補完(D4) = 12,024件（種・種内分類群〔species/subspecies/variety/form〕のみ、内訳 species 10,121／variety 1,068／subspecies 547／form 288）。rank が種以下と確認できず見送り = 1,343件（内訳 genus 1,153／family 168／order 9／class 8／kingdom 3／phylum 2）——修正前にバグで実際に誤補完されていた「属以上で1,397行」（`is_latin_script` の否定を和名判定に使っていた旧ロジックでの集計）とは母集団が異なる（本修正で `is_japanese_name()` も同時に直したため、キリル文字・ハングルの俗名がそもそも候補から除外され、見送り件数もそれに応じて変わる）ので数は一致しないが、実データの既知の事故3件（`gbif.6`→kingdom Plantae／`gbif.5`→kingdom Fungi／`gbif.1`→kingdom Animalia）はいずれも `vernacular_name_ja IS NULL` に戻ったことを直接確認した。`vernacular_name_en` 候補（ラテン文字）= 7,308 (namespace, taxon_key)。ロシア語（`gbif.7678610`）・韓国語（`gbif.5069632`）の実例も `vernacular_name_ja IS NULL`（候補にならない）のままであることを確認した。`vernacular_ja_basis` の内訳は `override` 54／`records` 12,024／`taxa` 8,570／`NULL` 20,806（`override`=54 は NAME_JA 適用件数と一致——既存の和名の由来〔taxa/override〕はどちらもこの修正で触っていないコード経路なので変わらない）。`is_japanese_name()`（ひらがな・カタカナを1文字以上含む、の肯定判定）を `common.py` に新設し、`is_latin_script` の否定を代用しない。
2. **D1 マイグレーション**: `web/src/db/schema-cube.ts` の `occurrenceAgg.nAlien` に `.default(0)` を付け、`web/drizzle/migrations/0007_past_siren.sql` を作り直した（`0007_awesome_cobalt_man.sql`。0007 の SQL・meta の snapshot/journal を消してから `db:generate` をやり直す手順）。実データで確認: (a) `ALTER TABLE occurrence_agg ADD n_alien integer NOT NULL`（既定値なし）は非空テーブルに対して `Cannot add a NOT NULL column with default value NULL` で失敗し、`DEFAULT 0` を付けると同じ非空テーブルで成功して既存行が `n_alien=0` にバックフィルされることを、独立の一時 sqlite で機械的に再現した。(b) 空の D1 に `db:migrate`（0000〜0006）→ `db:seed`（`occurrence_agg` 1,437,598行、`n_alien` 込み）→ `db:migrate`（0007、`n_alien` 追加＋第3索引）を通し、全経路が緑であることを確認した（`pnpm test`・`npx tsc --noEmit`・`pnpm lint` も緑）。
3. **b08 の性能後退（100秒→745秒）を修正**: `_PLACE_MESH_LOOKUP_SQL`/`_PLACE_WATERSHED_LOOKUP_SQL` で作る TEMP 表に、作成直後（本体クエリで JOIN する前）に `place_id` の索引を張った（`ix_place_mesh_lookup`/`ix_place_watershed_lookup`。`ix_owy_exact` と同じ流儀）。実データで b08 を1回回した結果、**115.3秒**（目標 ~100秒に近い水準まで回復。修正前の745秒から約6.5倍高速化）。`_assert_watershed_cells_match_exact` は例外なく通り、`memo_moved_records=11,306`・`memo_mixed_buckets=741`・`org_watershed_year_keys_changed_vs_exact=1,091` は上の「実測の記録」節と完全一致——値は1つも変わっていない。
4. **b07 の検査順序を修正**: `_assert_consistent_with_place_declarations`（宣言 YAML 2つだけを読み、`conn`/`occurrence_agg` に一切依存しない検査）を、`occurrence_agg` の差し替え・索引作成の**後**から、`declarations` を読み込んだ直後（`staged_table` に入る前）に移した。「全検査が通ってから差し替え」を守る。回帰テストとして、この検査が失敗したとき `occurrence_agg` テーブル自体がまだ作られていないことを確認するアサーションを追加した（`scripts/tests/test_b07_build_occurrence_cube.py`）。
5. **b13 の `filter.grain` 値検証を追加**: `source: occurrence_agg` の summary は、`filter.grain` 列の**有無**だけでなく**値**も検証するようにした（`_ALLOWED_GRAIN_FAMILIES_BY_SOURCE`）——値が `b07.YEAR_GRAIN_FAMILY`（`{year, survey_period}`）か `b07.MONTH_GRAIN_FAMILY`（`{month}`）のどちらか1つの族にちょうど収まっていなければ止める。`[year, month]` のように族を跨ぐ値・未知の値（例 `week`）のどちらも拒否するテストを追加した。

確認: `pytest scripts/tests -q` は812件緑（`test_s04_*` の3件は証明鮮度検査で想定内——`reports/full_gate_proof.json` は本 PR でコミットしない）。実データでの r01（項目1）・b08（項目3）は上記のとおり各1回実行済み。b07/b13（項目2・4・5）は触った箇所の pytest に加え、上の build:v2 全量実行にも含まれて確認済み。`cd web && pnpm test && npx tsc --noEmit && pnpm lint` は全て緑。
