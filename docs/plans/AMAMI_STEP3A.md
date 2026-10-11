# 奄美 Step 3a: マングースの捕獲数・わな日・CPUE を行政文書の時系列に載せる（Issue #89）

環境省のお知らせにある画像の表（2000〜2022年度）を OCR で取り、原本 `cells.sqlite` の documents・cells・notes に入れる。Step 2c のハブ OCR（§3d）の仕組みを共通化して使う。2026-10-11 に設計担当が原資料を取得して確かめた。

## 0. 実測で Issue の記述と変わった点

1. **取る表は 2020年度のページの表2ではなく、令和4年度のお知らせの表1にする。** 同じ表の拡張版で、2000〜2022年度の24行・5列が1枚の PNG に入る（2020年度の表2は 2001〜2020年度。CPUE の桁が3桁固定）。2000年度（3,884頭）も、2021・2022年度もこの1枚にある。別資料から2000年度を繋ぐ必要はない。
2. **CPUE の単位は全行 頭/1,000わな日で、2007年度だけ100わな日あたりという記述は誤り。** 表の見出しは全行「CPUE（頭/1,000TD）」。2007年度は 783 ÷ 1,380,751 × 1,000 = 0.567 で、1,000わな日で合う。単位の違いの扱いは要らない。
3. **2023・2024年度の数表は見つからない。** 評価シート（令和5年度）は図（折れ線・棒）だけで、数値の表は無い。令和5年度・6年度の「実施結果のお知らせ」は、報道発表の一覧（2024年4月〜2025年3月）にも検索にも出ない（沖縄島北部のものだけがある）。cells は 2000〜2022年度までにし、2023年度以降は文字の事実を notes に置く（§4）。環境省への問い合わせ候補にする。
4. **根絶確率「HBM 99.9%」の文字の出典は取れていない。** 公表ページ（2026年8月7日修正）の本文は HBM 99.7%・REA 98.9% のまま、図2だけが Fukasawa et al., 2026（プレプリント）の再計算結果に差し替わっている。図からは 99.9% と読み取れない（HBM は 2020年に約 0.99、2021年以降は 1.0 付近）。数値は入れず、訂正があった事実だけを notes に書く。
5. **3,884頭の内訳に疑問が残る。** 同じ事務所の棒グラフでは、2000年度の棒の下側に「有害鳥獣捕獲（鹿児島県等）」約1,070頭が積まれて見える（積み上げか重ね描きかが読み取れない）。表1の列見出しは「わな捕獲総計」。notes にはラベルどおりに書き、内訳の主張はしない（未決 4）。

## 1. 原資料（`data/raw/moe_mongoose/` に保存済み。再配布しない）

| ファイル | 内容 | URL |
|---|---|---|
| `r4_hyo1_000157229.png`（565×646、sha256 `8fd8a498…880d`） | **取る表**。表1 捕獲数・捕獲努力量・CPUE の経年推移（2000〜2022年度） | `https://kyushu.env.go.jp/okinawa/content/000157229.png` |
| `press_00065_r4.html` | 上の PNG が載るお知らせ「令和４年度奄美大島におけるマングース防除事業の実施結果について」（2023-09-04）。わな日・CPUE の定義の注記（*1・*2）もここ | `https://kyushu.env.go.jp/okinawa/press_00065.html` |
| `press_00006_r3.html`、`post_156.html` | 令和3年度・令和2年度のお知らせ。前者の表1 は PNG（`r3_*`）、後者の表2 は 2001〜2020年度（`r2_hyo2_R030901.png`。ベンチの正解 `I2_mongoose.csv` の元） | `…/press_00006.html`、`…/pre_2021/post_156.html` |
| `press_00099_declaration.html`、`20240903-1.pdf`（5ページ） | 根絶宣言の報道発表（2024-09-03）。前者が2026-08-07修正版（図2は `press_00099_zu2_000424490.png`）、後者は修正前の PDF | `…/press_00099.html`、`…/awcc/pdf/20240903-1.pdf` |
| `data/raw/amami_doc/mon_a-4-j.pdf` p.54 | 評価シート（令和4年度）の表1。**文字情報のある表**で、同じ 2000〜2022年度が pdfplumber で読める（CPUE は3桁）。独立の突き合わせ先 | Step 2d で登録済み（`moe_wh_monitoring_eval_r4`） |

- 形式: 表は PNG（OCR が要る）。お知らせは HTML。評価シートは PDF（文字情報あり）。
- ライセンス: 環境省ホームページのコンテンツ。ページ自体にライセンス表記は無く、ノネコ（`kagoshima_noneko_amami`）と同じく環境省サイトの PDL1.0 の扱い（`registry/source/license.yaml` の既存の原文 `LICENSE_MOE_PDL` に写る）。`redistributable=1`。
- 取得は `User-Agent` に個人名を入れず（`common.py`）、リクエストの間は5秒以上空ける。

## 2. 表の構造と検算（実測）

- 見出し: 年度 ／ わな捕獲総計（捕獲頭数・のべわな日・CPUE（頭/1,000TD））／ 探索犬の発見による捕獲（捕獲頭数）／ 総捕獲頭数。
- 行: 平成12年度(2000)〜令和4年度(2022) の23年度＋合計。見出し付きの年度ラベルは「平成12年度　(2000)」の形。
- 空欄:
  - 2000年度の のべわな日・CPUE（原表の注記「平成12年度はのべわな日の集計が不十分であったために、わな日として計上していない」）。
  - 探索犬の列の 2000〜2007年度（探索犬の導入は2008年度。`post_156.html`）。2008年度以降は 0 の印字がある。
- 桁: 整数は桁区切りカンマ付き。CPUE は 3桁（2018年度だけ 0.0004、0 は 0.0000 と印字）。
- 正解 csv（目で読んだもの）: scratchpad の `step3a/I2b_mongoose_r4.csv`（24行×5列）。**担当2が `scripts/tests/fixtures/mongoose/I2b_mongoose_r4.csv` にコピーして使う。** 作成時に次を通した。
  - 全年度で 総捕獲 = わな捕獲 + 探索犬。
  - 全年度で |CPUE − 捕獲 ÷ わな日 × 1000| ≤ 印字桁の半分（2001〜2022年度。全部通る）。
  - 列の和 = 合計（捕獲 23,129、わな日 37,525,484、探索犬 102、総捕獲 23,231）。
  - 合計の CPUE 0.616 = 23,129 ÷ 37,525,484 × 1000（原表の値は 2000年度の捕獲数を含めて計算）。
- 評価シート版との差は2点だけ（突き合わせの「宣言する差」。それ以外は全セル一致）。
  1. CPUE の桁が3桁（2018年度は PNG が 0.0004、シートが 0.000）。突き合わせは CPUE を3桁に丸めて比べる。
  2. 合計の CPUE は PNG が 0.616、シートが 0.513（シートは注記どおり 2001年度以降の捕獲数 19,245 頭で計算）。合計の行は `is_total=1` で系列に出ない。値は PNG の印字どおり入れ、notes に両方の値を書く。

## 3. cells への載せ方

- **doc_id**: `moe_mongoose_catch_h12r4`（1つ）。2000年度も同じ表にあるので繋ぎの別 doc_id は不要。
  - documents: title「奄美大島におけるマングース捕獲数・捕獲努力量・CPUE の経年推移（2000〜2022年度）」、publisher「環境省 沖縄奄美自然環境事務所」、url は `press_00065.html`、local_path は PNG、doc_sha256 は PNG の sha256、n_pages=1、fiscal_year=2022、license=`doccells.LICENSE_MOE_PDL`。
- **向きは PNG の転置にする。** series の鍵は (doc_id, table_id, row_key) で点が fiscal_year ごとの1値なので、行＝指標、列＝年度にする（ノネコ・ハブと同じ）。
  - table_id=`p1_t1`、page_no=1。
  - row_key と unit（`DOC_SERIES_WHERE` を通る系列は5本）:
    - `わな捕獲|捕獲頭数` … 頭
    - `わな捕獲|のべわな日` … わな日
    - `わな捕獲|CPUE` … 頭/1000わな日
    - `探索犬|探索犬による捕獲頭数` … 頭
    - `総捕獲頭数` … 頭
  - col_key は西暦の年度（`2000`〜`2022`）と `合計`。fiscal_year=西暦、era_raw=原表の「平成12年度(2000)」の表記。
  - 合計の列（`合計`）は `is_total=1`、fiscal_year=NULL。年度の列の `is_total` は 0。
  - 値は value_type=int（CPUE は float）。value_raw は原表の表記（カンマ付き、CPUE は印字の桁のまま）。
  - source_bbox は格子のセルの座標（c98b と同じ）。
  - 空欄（2000年度のわな日・CPUE、2000〜2007年度の探索犬）は value=NULL・value_raw=NULL・`source_text="(空欄)"`。0 にしない。系列にも出ない。
- **単位の違いは無い**（§0.2）ので row_key を分けない。2007年度の注記も要らない。
- `/documents` の系列: 5本とも `DOC_SERIES_WHERE` の条件（`superseded=0 AND is_total=0 AND value_type IN ('int','float') AND value IS NOT NULL AND fiscal_year IS NOT NULL`）を満たす。`DOC_SERIES_WHERE` は変えない。点の数は 捕獲頭数 23・わな日 22・CPUE 22・探索犬 15（2008〜2022）・総捕獲 23。
- verified_by（既存の語彙に1つ足す）:
  - `auto:xocr+xtext`（confidence 1.0）: 2つの OCR が一致し、評価シートの文字情報から読んだ値とも一致した（2000〜2022年度の年度の列の全セル。CPUE は3桁に丸めて比べる）。
  - `auto:xocr+arith`（1.0）: 2つの OCR が一致し検算が通った。合計の列・行など、シートに無い値（探索犬の空欄は除く）。
  - `human:<名前>`（1.0）・AI の名前（0.9）・NULL（未採用）はハブと同じ。reviewer の扱い（`human:` を装わない）も同じ。
  - OCR が食い違うセルは、シートの値と検算の示す値を `unreadable_reason` に書くだけで**採用しない**（`auto:arith`・`auto:xtext` 単独は作らない）。reviewed.csv で確認する。
- extractor: `ocr:docling_rapid@…+paddle@…`（c98b と同じ形）。

## 4. notes（事実だけ。`blocks_timeseries` は全部 0）

doc `moe_mongoose_catch_h12r4`（table_ids=`["p1_t1"]`）:
1. survey_scope: 奄美大島。環境省の防除事業（わな捕獲＋探索犬）の年度（4月〜3月）ごとの値。表の列は「わな捕獲総計」「探索犬の発見による捕獲」「総捕獲頭数」。2000年度は環境庁（当時）と鹿児島県が開始した事業で、2001年度から環境省のみ（報道発表の記述）。
2. definition_change か footnote（definition）: わな日＝のべわな日数（わなの数×わな有効日数）、CPUE＝わなによるマングース捕獲数 ÷ 1,000わな日（お知らせの注記 *1・*2）。
3. comparability: 2000年度はわな日の集計が不十分でわな日・CPUE が無い（原表の注記）。探索犬の列は導入前の 2007年度以前は空欄。
4. footnote: 合計の CPUE は PNG が 0.616（2000年度の捕獲数を含めて計算）、評価シート（令和4年度）の同じ表は 0.513（2001年度以降の捕獲数で計算）。
5. footnote: 2018年度の CPUE は PNG が 0.0004（桁が違う印字）。評価シートでは 0.000。
6. footnote（事実）: 2018年4月に1頭を捕獲して以降、わなによる捕獲は 0（2019〜2022年度は表のとおり 0）。2023年度以降の数表は未取得。

別 doc `moe_mongoose_eradication_declaration_2024`（documents＋notes だけ、cells なし。Step 2d と同じ形。url は `press_00099.html`、local_path は `moe_mongoose/press_00099_declaration.html`、n_pages は NULL）:
7. survey_scope: 2024年9月3日、奄美大島フイリマングース防除事業検討会が根絶に達したと評価し、環境省が奄美大島からの根絶を宣言した。評価は 2023年度末までの防除作業の確定値による。
8. footnote: 宣言時の根絶確率は HBM 99.7%・REA 98.9%（報道発表の本文）。2026年8月7日に、環境省が公表ページの図2を再計算結果（Fukasawa et al., 2026, プレプリント）に差し替えた。本文の数値は修正されておらず、修正後の確率は図からは数値として読み取れない（推奨案。未決 3）。
9. 事業費の総額・延べ人年など、宣言のページにある表以外の数字は notes に広げない。

## 5. 共通化の設計（ハブの出力は変えない）

ハブの c98・c98b には2種類のコードが混ざっている。ハブ固有（SPECS・列の構成・死亡数の行・検算）は残し、**表の形に依らない部分**を `scripts/ocr/` に寄せる。`scripts/ocr/__init__.py` を足し、`from ocr import engines, cellmatch` で読む（`sys.path` は他のスクリプトと同じ）。

### scripts/ocr/engines.py（OCR の venv 側。import は遅延）
- `run_docling_rapid(img, W, H)`・`run_paddle(img, W, H)`・`versions(engine)`・`ENGINES`・`sha256`（c98 から移す）。
- `ocr_image(img, scale)`: 拡大して回し座標を元に戻す（c98 の `main` の中の処理）。
- `write_json(out, doc_id, engine, versions, input_sha, image_info, grid, boxes, seconds)`: JSON の形（`pdf_sha256` のキーは**そのまま**。PNG のときは入力ファイルの sha256 を入れる。ハブの既存 JSON を壊さない）。
- 格子の取り方（`ruled_grid`）は c98 に残す。PNG 用の `uniform_grid`（罫線が2本しかない表。下記）は c100 に置く。

### scripts/ocr/cellmatch.py（OCR のライブラリ不要。CI の pytest が使う）
c98b から移す。形に依らない関数にして、列ごとの差（書式・小数点の扱い）は引数で渡す。
- `norm(s)`、`CONF_*`・`KNOWN_AI`、`verified_by_for(reviewer)`、`load_reviewed(path, norm)`。
- `assign(data, ncol_fmt)`: 箱を格子に割り当てる（中心点・30% 重なり・収まらない箱の理由）。`lenient(j, s)` を引数で受ける。
- `decide(A, B, bad, fmt_ok, reviewed_by_cell)`: 一致・食い違い・書式不正・0 と空欄の区別を状態にする（c98b の `decide_state` から、spec 依存の部分を除く）。
- `load_engines(doc_id, ocr_dir, expect_rows, expect_cols, input_path, input_key)`: 2つの JSON の整合（doc_id・格子の数と位置・入力の sha256）。
- 検算の評価（`constraints`・`evaluate`・`arith_flag`）は表ごとに違うので、**ハブ側に残す**。呼び口だけ揃える（制約のリストを受けて、疑うセルの集合・ヒント・`touching` を返す形。ハブの `arith_flag` をそのまま包む）。

### ハブの出力が変わらないことの確かめ（担当1）
- **移す前に** `c98b.build()` の返り値（`rows`＝cells の行、`notes`、`stats`、`warnings`）を、咬傷・買上の両方で pickle に取る（`extracted_at` は比べない）。移した後に同じ形で取り直し、完全に一致すること。
- 既存の `scripts/tests/test_c98b_habu_cells.py`（全セル一致・未採用の集合・reviewed の3セル）が、そのまま通ること。テストの期待値は変えない。
- ハブの `data/ocr/habu/*/*.json` はコミット済みのまま。OCR は回し直さない。

### doccells.py に足すもの（担当2）
- 追加は無い。`LICENSE_MOE_PDL`・`put_document`・`put_notes`・`commit_doc`・`check_identity`（CPUE の検算）を使う。評価シートの表を読む処理は c100b の中に1箇所だけ置く（ほかの資料は使わない）。

## 6. 実装担当ごとの節

### 担当1: 共通化と OCR の実行（OCR の venv が要る）
ファイル: `scripts/ocr/{__init__,engines,cellmatch}.py`、`scripts/c98_habu_ocr_run.py`・`scripts/c98b_habu_cells.py`（共通部分を import に置き換えるだけ）、`scripts/c100_mongoose_ocr_run.py`、`scripts/ocr/README.md`、`data/ocr/mongoose/moe_mongoose_catch_h12r4/{docling_rapid,paddle}.json`、`.gitignore`（`data/ocr/` は既に例外。変更は不要なら触らない）。
1. 最初に `cellmatch.py` の API（§5）を入れて commit する（担当2が受け取る）。
2. ハブの出力が変わらないことを §5 の手順で確かめる。
3. `c100_mongoose_ocr_run.py`: 入力は PNG（`data/raw/moe_mongoose/r4_hyo1_000157229.png`）。
   - 画像が 565×646 と小さいので `--scale 3` を既定にする（ベンチの結論）。
   - 格子は PNG の罫線から取る。縦罫線も行の罫線も無い表（水平の罫線は見出しの下と合計の上の2本だけ）なので、`uniform_grid`: 見出しの下の罫線と合計の上の罫線を morphology で見つけ、その間を 23 等分して行の帯にする。合計の行の帯はその下。列の境界は、右揃えの数字の右端で決めた5列の x を spec に持つ（画像の sha256 が固定なので値を固定してよい）。年度のラベルの列は格子の外に置き、ラベルは検査にだけ使う（`label_report`）。
   - 行・列の数が期待（24行・5列）と違えば止める。OCR の箱が2つの列にまたがれば止めず、近いセルを未採用にする（ハブと同じ）。
   - 出力は `data/ocr/mongoose/<doc_id>/<engine>.json`。
4. OCR を2エンジンで1回ずつ回す（それぞれ数分。ベンチの venv は `…/scratchpad/pdfbench/image/venv-docling`・`venv-paddle` にあれば使う。無ければ README の手順で作る）。OCR の食い違いセルの一覧を報告に書く。
5. `scripts/ocr/README.md` に「マングースの回し方」を足し、`requirements-*.txt` は版が変わらなければ触らない。

担当1は `c100b`・登録・tests/mongoose に触れない。

### 担当2: cells・notes・登録・テスト
ファイル: `scripts/c100a_mongoose_fetch.py`、`scripts/c100b_mongoose_cells.py`、`scripts/c101_mongoose_declaration.py`、`scripts/tests/test_c100b_mongoose_cells.py`、`scripts/tests/fixtures/mongoose/I2b_mongoose_r4.csv`、`registry/source/access.yaml`、`registry/source/license.yaml`、`docs/LICENSE_MATRIX.md`、`data/sample/coverage.yaml`、`scripts/tests/test_registry_source.py`（ほか件数を直書きしたテスト）。
1. `c100a_mongoose_fetch.py`（c98a の形）: §1 の PNG・HTML・宣言ページを `data/raw/moe_mongoose/` に保存し、sha256 を出力する。5秒以上の間隔。既に保存済みのファイルは sha が同じなら取り直さない。
2. `c100b_mongoose_cells.py`（OCR のライブラリを使わない）:
   - SPEC（行＝指標・列＝年度の対応、unit、列の x、CPUE の桁）と、`cellmatch` による2つの OCR の突き合わせ・書式検査（整数の列は `\d+`、CPUE は `\d+\.\d{3,4}`。**整数の列の「.」は桁区切りの誤読として除く**。CPUE の列は除かない）。
   - 検算: 総捕獲 = わな捕獲 + 探索犬（空欄は 0）、CPUE ≒ 捕獲 ÷ わな日 × 1000（印字桁の半分以内）、列の和 = 合計。ほかに年度の行の並び（2000→2022 の連番）と、年度ラベルの括弧内の西暦。
   - 評価シートの突き合わせ: `data/raw/amami_doc/mon_a-4-j.pdf` の p.54 を pdfplumber で読む（無ければ警告して `auto:xocr+arith` に落とす。CI の最小環境では PDF が無い）。CPUE は3桁に丸めて比べる。合計の CPUE の差は §2 の宣言する差として列挙し、過不足なく一致しなければ止める。
   - reviewed.csv: `data/ocr/mongoose/<doc_id>/reviewed.csv`（行は row_key、列は col_key。ハブと同じ列）。reviewer の検査は `cellmatch.verified_by_for`。
   - cells の行は §3、notes は §4（1〜6）。`doccells.commit_doc` で書く。register は `source` に渡す（`SOURCE_ID="moe_mongoose_amami"`、PDF ではなく「PNG → OCR 2種＋検算 → cells.sqlite」。record_count は cells の行数）。
   - `--dry-run`（DB に書かない）を持つ。
3. `c101_mongoose_declaration.py`: 宣言のページを documents に1行、notes に §4 の 7〜9 だけ入れる（cells なし。`doccells.put_document`・`put_notes`）。sha256 は HTML の保存ファイルから。
4. テスト（OCR の JSON のフィクスチャと、`scripts/tests/fixtures/mongoose/I2b_mongoose_r4.csv`。OCR のライブラリも DB も要らない。`test_c98b_habu_cells.py` の形に合わせる）:
   - **受け入れ基準: 正解 csv と全部のセル（24行×5列）が一致する。** 未採用になったセルは、その集合を明示して許す（`reviewed.csv` で埋めた後は未採用 0 になること）。
   - 変異: JSON の1セルを書き換えると未採用になる（一致のまま黙って通らない）。検算が疑うセルと一致すること。
   - cells の形: 5本の row_key、`fiscal_year` が 2000〜2022、合計の列と行が `is_total=1`、空欄が value=NULL、CPUE の value_raw の桁が原表のまま。
   - `DOC_SERIES_WHERE` を通る件数（§3 の点の数）。
   - 評価シートとの突き合わせ（PDF が無いときは skip）。
   - 書き込み: 一時 DB で、自分の doc_id 以外の行が変わらない（`test_doccells.py` の前例）。
5. 登録と件数:
   - source_id `moe_mongoose_amami`、出典「環境省 沖縄奄美自然環境事務所」、ライセンス PDL1.0（既存の原文を使う。`license.yaml` の mappings は増やさない見込み。足りなければ足す）。
   - `access.yaml`: `{reason: document_cells, basis: "doc_id=moe_mongoose_catch_h12r4（PNG の表を OCR 2種＋検算＋評価シート突き合わせ、2000〜2022年度）・moe_mongoose_eradication_declaration_2024（documents と notes だけ）。cells に入れた"}`。
   - `LICENSE_MATRIX.md`: 一覧の表に1行と、Step 2c/2d の節の続きに数行（奄美大島の値。2023年度以降は数表が無い）。
   - `data/sample/coverage.yaml` の `document_closure.doc_ids` に2つの doc_id を足す。
   - 件数: `test_registry_source.py` の `source` 170→171・`source_edition` 172→173。Step 2c の前例（`58c60dc`）にあるとおり、ほかに件数や出典の一覧を直書きしたテスト・スナップショット（`web/src/lib/mcp/__snapshots__/tools.test.ts.snap`・`web/src/lib/ai/__snapshots__/prompt.test.ts.snap` など）を grep で洗い出して直す（生成物の `web/src/lib/registry/generated*.ts` は `build:registry:ts` で作り直す。手で書かない）。

担当2は `scripts/ocr/*`・c98・c98b・`data/ocr/` に触れない。`cellmatch` が届くまでは、spec・検算・notes・登録・テストの骨組みを先に書き、届いたら繋ぐ。

### どちらも
- スキル（/simplify・/code-review 等）やサブエージェントを起動しない。`git add` はパスを明示する。
- `build:v2`・b00・全量ゲート・サンプルの再生成・clone での CI 再現は回さない（メインが回す）。速い検証（該当のテストファイルだけ）で確かめる。
- `p1_maker`・`p1_maker_v2`・`p3_fixer`・`c25`・`c26` は回さない（他の書き手の行を消す）。
- 原本 `data/db/*.sqlite` は書き込み前に `.backup` を取る。担当2の c100b・c101 の書き込みは、検算が通った後にメインが回す（下の統合 1）。

## 7. 統合（メインと担当2）

1. 書く前に `cells.sqlite` を `.backup`。c100b → c101 の順に原本に書く。
2. **自分の doc_id（`moe_mongoose_catch_h12r4`・`moe_mongoose_eradication_declaration_2024`）以外の行について、cells・documents・notes・extraction_log・source_registry の全部を EXCEPT で突き合わせ、差が0**であることを確かめる（書く前の `.backup` との比較）。
3. 書く前に、検証が本番の経路を通っているかを確かめる: `/documents` の系列（`doc_series_meta`・`doc_series_points`）を作る `web/src/lib/cube/documents.ts` を通した問い合わせで、5本の系列が出ること。
4. r01 → `build:registry:ts` → `build:v2`（ここまでが `pnpm run build:v2` の経路）。
5. サンプル（`scripts/s01_build_sample.py`。`s02` は本物のチェックアウトで回さない）→ 一時ディレクトリへの clone での CI 再現 → b00（`reports/serving_fingerprint.json` を一緒にコミット）。
6. serving スナップショットを更新する PR なので、`serving:snapshot --mode diff` の before/after 表を PR に貼る。差は `moe_mongoose_*` の2文書の系列・出典の増分だけであること。
7. 重い処理（4〜6）はメインが裏で1回だけ回す。

## 8. 未決（オーナーに聞くこと。推奨案つき）

1. **主たる取得経路: OCR のままにするか、評価シートの文字情報を主にするか。** 同じ値が評価シートの PDF に文字で入っている（2000〜2022年度）。推奨: **OCR を主（元資料は PNG。決定済みの経路）にし、評価シートの文字情報は突き合わせ（`auto:xocr+xtext`）に使う。** OCR が外れても検算とシートで見つかる。シートを主にすると OCR の共通化が要らなくなるが、「画像の表も機械で取る」という Step 2c の方針の実証が1表で終わる。
2. **2023・2024年度の数表が無い。** 推奨: **cells に入れず、事実だけ notes に置き**（§4 の6）、環境省（沖縄奄美自然環境事務所）への問い合わせ候補に「令和5・6年度のわな日・CPUE」を足す。図からの画素読みの推定値は、系列の最後の点（0頭）に推定の印を付けることになるので入れない。
3. **根絶確率の訂正後の数値（Issue の HBM 99.9%）の文字の出典。** 推奨: **文字の出典が確認できるまで数値は入れない**（訂正があった事実だけ。§4 の8）。オーナーが出典（プレプリントの URL など）を知っていれば教えてもらい、その文書を documents に足して数値を notes に入れる。
4. **2000〜2002年度の捕獲数に有害鳥獣捕獲分が含まれるか。** 棒グラフでは積み上げの下側に有害鳥獣捕獲が見える。推奨: **ラベルどおり（「わな捕獲総計」）に書き、内訳は断定しない。** 気になれば問い合わせに足す。
5. **2000年度の comparability に `blocks_timeseries=1` を付けるか。** 推奨: **付けない。** 2000年度は捕獲頭数の1点だけで、CPUE・わな日は空欄のため元から系列に出ない。付けると捕獲頭数の系列まで止める。
6. **月別の表（令和4年度のお知らせの表2）も入れるか。** 推奨: **入れない**（物語1には年度の系列で足りる。入れるなら `fiscal_year=NULL` の別 table_id）。
7. **根絶宣言のページを別の documents 行にするか。** 推奨: **別行にする**（出典を取り違えず、2026年8月の修正も文書の更新として書ける）。担当2の c101 が1本増えるだけ。
