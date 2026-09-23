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

`CREATE TABLE ... AS SELECT`（列を明示的に宣言してから `INSERT ... SELECT` する形ではなく、
v1 の SQL 文字列をそのまま再実行する形）にしたのは、v1 の計算列（`doc_series.label`/
`value`/`n_cells`/`unit`、`doc_series_meta` の集計列、`quality_monthly` の全列）が
**宣言型を持たない**ため（`PRAGMA table_info` で確認済み）。列を明示的に宣言する形に
変えると、この「宣言型が無い」という v1 の実際の形とわざと違えてしまう。実測: 候補側
（`v1_projection_documents.sqlite`）と v1 実物（`derived.sqlite`）の `PRAGMA table_info` は
3テーブルとも1バイトも違わず一致する（列名・列順・宣言型を全列・厳密な順序で突き合わせる
テスト `test_declared_columns_and_order_match_v1_baseline_exactly` で固定した。`b02` は
列を集合で比較するため、列順を守るのはこのテストの役目）。

ATTACH のエイリアス（`c`=cells.sqlite、`r`=ryuiki.sqlite）も v1 と同じにしてあるので、
SQL 文字列は `build-derived.mjs` の該当行からコピーしただけで一字一句変えていない。

**書き込み前後のガード（コードレビュー対応、3表の値・SQLは1ビットも変えない）**:

- **SQLite の版**: `doc_series` は `AVG()` を使うため、`scripts/migrate/common.py` の
  `require_sqlite_version()`（元は `b04_build_cube.py` だけに書かれていたヘルパを共通化した）
  をモジュール読み込み時点で呼ぶ。実測: この環境の `sqlite3` CLI（3.37.2）で `doc_series` を
  作ると10グループで最下位ビットがずれ、`b02` が不一致2・終了コード1になる——Python 同梱の
  `sqlite3`（3.49.1）なら起きない。ガードは古い版で**止める**だけで、値のずれた出力を作らない。
- **`fresh_sqlite` が原本を消せる事故の防止**: `--out` に `data/db/ryuiki.sqlite`/
  `cells.sqlite`/`derived.sqlite` そのもの（symlink 越しも含む。`os.path.realpath` で解決）
  を指すパスを渡すと、`fresh_sqlite` が既存ファイルを `unlink()` してから書き込みに失敗する
  ——100MB超で再生成できない原本が消える。`scripts/migrate/common.py` の `fresh_sqlite` 自体
  （b10 だけでなく b03〜b05 も使う共通関数）に拒否ロジックを入れた。
- **0行のまま黙って通らない**: 3表のどれかが0行になったら `MigrationError` で止める。
  `cells.sqlite`/`ryuiki.sqlite` のスキーマ・運用が変わって `WHERE` 句が1行も拾わなくなった
  とき、0行・終了コード0で黙って通るのを防ぐ。

## 3. v1 の癖として温存し、記録するもの

宣言済み差分ではない（同じ SQL で完全再現するので b02 の差分としては出ない）。
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
- **別年の値が1つの `fiscal_year` に潰れて平均される。** 仕組みは「`num` の `GROUP BY
  doc_id, table_id, row_key, fiscal_year` に `col_key` が入っていない」こと。`col_key` に
  複数年度が連結された出典（例 `col_key='H25 H26 H27 H28 H29 H30'`）が単一の `fiscal_year`
  （例 2013）に丸められている場合、`AVG(v)` が本来別々の年の値を平均する。実測: `n_cells > 1`
  の**344グループ**中**336グループ**で実際に値が異なる（`min(v) <> max(v)`）。
  `choju_higai_gaiyou_2019`/`p1_t4` の `row_key='その他獣類'`（`fiscal_year=2013`, 7セル、
  値 27018〜61514）で確認済み。テストは `col_key` を `GROUP BY` に足すと別々の行に分かれる
  ことを対照クエリで示す形にしてある（`test_doc_series_collapse_is_caused_by_col_key_absent_from_group_by`）。
- **`doc_series.page_no`/`unit` は `GROUP BY` に無い裸の列**（SQLite 拡張。「グループ内の
  任意の1行の値」が入る——標準SQLならエラーになる書き方）。実測: 1グループ内で `page_no`・
  `unit` が2値以上になる組み合わせは`data/db/cells.sqlite`実データで**0件**。**いま値が一意に
  決まって見えるのはデータの性質であって、SQL がそれを保証しているわけではない**（将来
  1グループに複数の `page_no`/`unit` が混在するデータが入れば、v1・この射影のどちらも
  「どの値が採用されるか」は sqlite の内部実装（走査順）に依存する）。

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
   コードレビュー対応（§2「書き込み前後のガード」）の前後で `content_hash`/`PRAGMA
   table_info` が3表とも1ビットも変わらないことを実測で確認した（対応前のビルド結果を
   一時ファイルに退避し、対応後のビルド結果と `scripts/reconcile/common.compute_fingerprint`
   で直接突き合わせた）。
   SQLite版ガードが実際に効くことも実測で確認した: 古い `sqlite3`（システムの `python3`、
   3.10.12/SQLite 3.37.2）で `b10` を実行すると、出力ファイルを一切作らずに終了コード1で
   止まる（`sqlite3（Python 同梱、バージョン 3.37.2）が古すぎる。` というメッセージのみ）。
   `.venv/bin/python3`（3.13.7/SQLite 3.49.1）では正常に完了する。
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
3. **pytest 全緑。** 実測: 262件全緑（`scripts/tests/test_b10_project_documents_v1.py` 13件、
   `scripts/tests/test_common.py` の `adr0011_destinations.yaml` 検証3件、
   `scripts/tests/test_migrate_common.py` の `fresh_sqlite` 原本保護2件を含む）。
   `documents_fixtures.py`（自作の小さな `cells`/`ryuiki` フィクスチャ sqlite）だけで完結し、
   原本を要さない——一時ディレクトリへの `git clone` でも同じ集合が緑になる（原本DB非依存の
   フィクスチャ方式は `scripts/tests/migrate_fixtures.py` と同じ考え方）。
   CI（`.github/workflows/ci.yml` の `reconcile` ジョブ、`pytest` を無条件に実行）が
   新しいテストをそのまま拾う。
4. **実行時間。** `b10_project_documents_v1.py`: 0.3秒（4,099行を書き出し）。
   `b02_derived_compare.py --tables doc_series,doc_series_meta,quality_monthly`: 1秒未満。
   参考: 同じワークツリーでの `r01_build_registry.py`（registry.sqlite 再構築、約20秒）→
   `b03_build_observation.py`（20.4秒）→ `b04_build_cube.py`（37.0秒）→
   `b05_project_v1.py`（38.3秒）。

## 5. 設計からの逸脱・未決

- 「明示的な列宣言 + `INSERT ... SELECT`」という形ではなく「`CREATE TABLE ... AS SELECT`」に
  した（§2 参照。理由: v1 の宣言型を完全再現するため）。どちらも「1つの SQL 文で書き込み、
  Python 側に行をバッファしない」という同じ原則を満たす。
- コードレビュー対応（SQLite版ガード・`fresh_sqlite`の原本保護・0行チェック）を追加したが、
  SQL 文字列・書き込む値はどれも変えていない（実測: コードレビュー前後で `v1_projection_documents.sqlite`
  の3表の `content_hash` が1バイトも変わらないことを確認済み——§4参照）。
- 未決事項は無い（`p3_brief.md` の決定1〜4をそのまま実装した）。
