# Phase B P-3 — 文書の証跡層と品質ワークフローの射影（`doc_series`/`doc_series_meta`/`quality_monthly`）

対象: ADR-0016 の Phase B / 状態: **実データで一度緑になった（部分ゲート。33テーブル中3テーブル。
`observation`/`occurrence` を経由しない別枠）**
作成: 2026-09-22 / 関連: ADR-0007, 0011, 0017, ADR README §4

このドキュメントは `docs/plans/PHASE_B_RECONCILIATION.md`（突合ゲートの仕組み）と対になる、
P-3（残り12表のうち文書・品質ワークフロー系統）の設計と実測の記録。
`scripts/b10_project_documents_v1.py` がここで説明する対象そのもの。

**このゲートは v1 表の持ち越しを確かめるだけで、v2 の変換の正しさを確かめるものではない。**
`b03`（`observation`）〜`b05`（v1形への射影）の縦線とは別枠で、`cells.sqlite`/`ryuiki.sqlite`
を直接読み取り専用で ATTACH し、v1（`web/scripts/build-derived.mjs`）と一字一句同じ SQL を
再実行するだけ（理由は下記「1. 決定」）。

## 1. 決定（オーナー決定、2026-09-22）

`docs/adr/0011-aggregation-cube.md`「33テーブルの行き先」表は当初 `doc_series`/
`quality_monthly` を「キューブ（入力 `observation`）」に分類していたが、これは誤りだった。

1. **`doc_series`/`doc_series_meta` は `observation` に入れない。** 入力は `cells.sqlite`
   （ADR README §4 のコアエンティティ `document`/`cell`。行政文書の証跡層。cell → observation
   の昇格経路）。`doc_series` は `(doc_id, table_id, row_key, fiscal_year) → AVG(value)` で、
   主語が place ではなく（文書の表）、指標が `row_key` の生文字列（variable 未解決）なので
   [ADR-0007](../adr/0007-observation-fact.md) の observation の判定基準（主語が place、
   値が指標レジストリに登録済みの量であること）を満たさない。
   実測: `choju_higai_gaiyou_2019`/`p1_t4` は別年の値の7セル（`col_key='H25 H26 H27 H28 H29
   H30'`）が全部 `fiscal_year=2013` に潰れて平均されている（`n_cells>1` の344グループのうち
   336グループが値の異なるセルの平均——§3参照）＝観測値ではなく抽出の証跡。
   cell→observation の昇格は ADR-0012 のマニフェスト（`target: observation`）で行う
   **意図的な変更**で Phase D。
   → 行き先は「**`document`/`cell` の証跡層からの射影**」（旧 `doc_meta` を吸収）。
   `cells.sqlite` は v1 の表のまま持ち越し、新しい L2 実体は作らない。
2. **`quality_monthly` は [ADR-0017](../adr/0017-write-path-scope.md) の書き込み系ログの
   射影。** `quality_transitions` は3,372行すべて合成（`target_id LIKE 'SYN-MEAS-%'`）で、
   ADR-0017 が「現場入力・品質遷移・介入・意思決定」を読み取り基盤の対象外とし、原則4で
   「デモの合成分は当面 L2 の一部として扱い caveat で明示」としている。place も variable も
   無い。→ 行き先は「**ADR-0017 書き込み系（v1 表を持ち越し）の射影**」。
3. **`watershed_rollup` の宣言は動かさない。** 「D10型の結合射影（キューブのセルにしない）」
   という性格の注記だけ `place_attribute` カテゴリに添えた（[ADR-0011](../adr/0011-aggregation-cube.md)
   本文・`scripts/reconcile/adr0011_destinations.yaml` 参照）。
4. **カテゴリの内訳が33に一致することを機械検証する。** 改訂後: `cube_observation 12`
   （−`doc_series` −`quality_monthly`）/ `cube_occurrence 11` / `variable_registry 1` /
   `place_attribute 2`（`watershed_rollup` に注記）/ `taxon_registry 3` / `fact_body 1`
   （`org_norm`）/ 新設 `document_provenance 2`（`doc_series`/`doc_series_meta`）/ 新設
   `quality_workflow_log 1`（`quality_monthly`）＝ 12+11+1+2+3+1+2+1 = **33**。
   改訂前はこの合計を確かめる自動テストが無かった（`scripts/reconcile/adr0011_destinations.yaml`
   のヘッダコメントは「`scripts/tests` で検証済み」と書いていたが、実際にはそのテストが
   存在しなかった）。`scripts/tests/test_common.py::test_load_destinations_covers_exactly_33_tables_with_no_duplicates`
   を新設し、以後この宣言が壊れれば自動で落ちるようにした。

## 2. `scripts/b10_project_documents_v1.py`

`cells.sqlite`・`ryuiki.sqlite` を読み取り専用で ATTACH し、v1
（`web/scripts/build-derived.mjs:272-323`）と**一字一句同じ SQL**で
`doc_series`/`doc_series_meta`/`quality_monthly` を作る。出力は
`data/db/v1_projection_documents.sqlite`（毎回ゼロから作り直す、`.gitignore` 済み）。

`CREATE TABLE ... AS SELECT`（列を明示的に宣言する `scripts/b08_project_occurrence_v1.py`
の流儀ではなく、v1 の SQL 文字列をそのまま再実行する形）にしたのは、v1 の計算列
（`doc_series.label`/`value`/`n_cells`/`unit`、`doc_series_meta` の集計列、`quality_monthly`
の全列）が**宣言型を持たない**ため（`PRAGMA table_info` で確認済み）。列を明示的に宣言する
形に変えると、この「宣言型が無い」という v1 の実際の形とわざと違えてしまう。実測: 候補側
（`v1_projection_documents.sqlite`）と v1 実物（`derived.sqlite`）の `PRAGMA table_info` は
3テーブルとも1バイトも違わず一致する。

ATTACH のエイリアス（`c`=cells.sqlite、`r`=ryuiki.sqlite）も v1 と同じにしてあるので、
SQL 文字列は `build-derived.mjs` の該当行からコピーしただけで一字一句変えていない。

## 3. v1 の癖として温存し、記録するもの（宣言済み差分ではない。同じ SQL で
完全再現するので b02 の差分としては出ない）

実測（`.venv/bin/python3` で `cells.sqlite`/`derived.sqlite` に対し読み取り専用で実行）:

- **`row_key` に `|` が2個以上あると `label` が誤る。** `label` の式は「最初の `|` より
  後ろから、末尾の `|` の直後までの部分文字列」を切り出すバグを持つ（意図は「最後の `|`
  より後ろ（末尾トークン）」だが実装が違う）。例: `'山北町|三保|入猟者数'` → `'保|入猟者数'`
  （`'三保'` の頭の `'三'` が欠ける）。`|` が1個だけなら（例: `'AAA|BBB'` → `'BBB'`）正しく
  最後のトークンになる——バグは2個以上のときだけ。
  実測件数: `cells`（集約前、`num` CTE を通過した行）で**328行**、`doc_series`（集約後、
  `GROUP BY doc_id, table_id, row_key, fiscal_year` の後）で**289行**が該当し、うち**7行**
  は `label` が `|` で始まる。
- **`doc_series_meta.n_warnings` は doc 単位の相関サブクエリ。** `(SELECT COUNT(*) FROM
  c.notes n WHERE n.doc_id = s.doc_id AND n.blocks_timeseries = 1)` は `table_id`/`row_key`
  で絞らないため、同じ `doc_id` の全 `doc_series_meta` 行に、その文書全体の
  `notes.blocks_timeseries=1` 件数がそのまま重複して入る。実測: 13文書・**378行**
  （`doc_series_meta` 470行中）が対象。最大例: `tanzawa_shika_r6`（89行、全行 `n_warnings=9`）。
- **`doc_series_meta` の `HAVING n_years >= 3`。** 画面側（`web/src/lib/queries.ts` の
  `docSeriesList(minYears = 4)`）は既定 `minYears=4` で読むため、`n_years==3` の行
  （実測**36行**、`doc_series_meta` 470行中）はテーブルには残るが既定表示では見えない。
- **別年の値が1つの `fiscal_year` に潰れて平均される。** `col_key` に複数年度が連結された
  出典（例 `col_key='H25 H26 H27 H28 H29 H30'`）が単一の `fiscal_year`（例 2013）に丸められて
  いるため、`AVG(v)` が本来別々の年の値を平均する。実測: `n_cells > 1` の**344グループ**中
  **336グループ**で実際に値が異なる（`min(v) <> max(v)`）。`choju_higai_gaiyou_2019`/`p1_t4`
  の `row_key='その他獣類'`（`fiscal_year=2013`, 7セル、値 27018〜61514）で確認済み。

3値の語彙（暫定/検証済/公開済）の正は `web/src/lib/quality.ts` の `QUALITY_STAGES`
（`quality_monthly` の CASE 式が参照する。ここに新しい宣言ファイルは作らない）。

## 4. 受け入れ

1. **b02（`--candidate data/db/v1_projection_documents.sqlite --tables
   doc_series,doc_series_meta,quality_monthly`）の終了コードそのものが 0、一致3。**
   実測（2026-09-22、実データ）:
   ```
   一致: 3 / 宣言済み差分のみ: 0 / 不一致: 0
   EXIT_CODE=0
   ```
   `--no-expected-diffs`（宣言を一切読まない）でも同じ結果——v1 と同じ SQL をそのまま
   再実行しているので、そもそも宣言する差分が無い。
2. **既存のゲートが変わらない。** main の `b03`→`b05`（`scripts/r01_build_registry.py` →
   `b03_build_observation.py` → `b04_build_cube.py` → `b05_project_v1.py`、11テーブル）を
   このブランチのワークツリーで再実行し、b02 で突合した:
   ```
   一致: 5 / 宣言済み差分のみ: 6 / 不一致: 0
   適用した宣言済み差分: 18件
   EXIT_CODE=0
   ```
   `phase-b/zone-slice`（main）時点の実測と同じ内訳（一致5・宣言済み差分のみ6）。
   `b10` は `b03`/`b04`/`b05`/`scripts/reconcile/expected_diffs.yaml` のどれにも触れていない。
3. **pytest 全緑。** 実測: 256件全緑（新設 `scripts/tests/test_b10_project_documents_v1.py`
   10件、`scripts/tests/test_common.py` の `adr0011_destinations.yaml` 検証2件を含む）。
   `documents_fixtures.py`（自作の小さな `cells`/`ryuiki` フィクスチャ sqlite）だけで完結し、
   原本を要さない——一時ディレクトリへの `git clone` でも同じ集合が緑になる（原本DB非依存の
   フィクスチャ方式は `occurrence_fixtures.py` と同じ）。CI（`.github/workflows/ci.yml` の
   `reconcile` ジョブ、`pytest` を無条件に実行）が新しいテストをそのまま拾う。
4. **実行時間。** `b10_project_documents_v1.py`: 0.3秒（4,099行を書き出し）。
   `b02_derived_compare.py --tables doc_series,doc_series_meta,quality_monthly`: 1秒未満。
   参考: 同じワークツリーでの `r01_build_registry.py`（registry.sqlite 再構築、約20秒）→
   `b03_build_observation.py`（20.4秒）→ `b04_build_cube.py`（37.0秒）→
   `b05_project_v1.py`（38.3秒）。

## 5. 設計からの逸脱・未決

- `scripts/b08_project_occurrence_v1.py` の「明示的な列宣言 + `INSERT ... SELECT`」という
  形ではなく「`CREATE TABLE ... AS SELECT`」にした（§2 参照。理由: v1 の宣言型を完全再現する
  ため）。どちらも「1つの SQL 文で書き込み、Python 側に行をバッファしない」という同じ原則を
  満たす。
- 未決事項は無い（`p3_brief.md` の決定1〜4をそのまま実装した）。
