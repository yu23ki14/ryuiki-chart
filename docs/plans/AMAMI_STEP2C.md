# 奄美 Step 2c: 年次の表を行政文書の時系列に載せる（Issue #89）

ウミガメ・ノネコ・観光入込・ハブの4つの資料を、原本 `cells.sqlite` の documents・cells・notes に入れる。serving の `doc_series_meta`・`doc_series_points` には、`web/src/lib/cube/documents.ts` を通して出る。2026-10-10 に設計担当が4資料を取得して確かめた。

## 0. 決定（2026-10-10、オーナー承認）

1. **合計の行は慣例どおり `is_total=1` にする**。ハブの「名瀬計」も含む。`DOC_SERIES_WHERE` が外すので `/documents` の系列には出ないが、cells・`run_sql`・AI からは読める。`DOC_SERIES_WHERE` は変えない。
2. **観光入込は奄美群島の値として入れる**。BODIK 版は群島全体の値なので、注記で「奄美大島の値ではない」と書く。Issue の「島単位」という記述は誤りだった。
3. **ウミガメは県の39市町村をすべて入れる**。合計の検算に全部の行が要る。
4. **OCR は別の venv で回し、結果の JSON を `data/ocr/` にコミットする**。版は `scripts/ocr/requirements-*.txt` に固定する。
5. **cells・documents に region の列は足さない**。doc_id の接頭辞 `kagoshima_`・`bodik_460001_` で区別する。`/documents` には神奈川と鹿児島の系列が並ぶが、地域で絞るのは #93 で扱う。
6. **ノネコは 2023年4月版（`wildcat230417.pdf`、2018〜2022年度）で進める**。現行版の URL が見つかれば、そちらを使う。
7. **ハブの月次 PDF は今の1件を保存するだけ**。`data/raw/kagoshima_doc/` に置き、cells は作らない。
8. 県のサイトからは、事実（数値）だけを抜き出して出典を明記する（Step 0 の決定）。原本の PDF・XLSX は `data/raw/`（gitignore 済み）に置き、再配布しない。

## 1. 神奈川の仕組み（実測）

- **書く側**: documents は c スクリプトが登録し、cells は p1_maker などが入れている。
  - 手で転記した前例は `c26`（`extractor="vision:…"`、`verified_by="claude(vision)"`）。
  - DDL は `scripts/schema_cells.sql`。実物の cells には `superseded INTEGER DEFAULT 0` も付いている。
- **cells の列**
  - `row_key`: 階層を `|` でつなぐ。表示名は最後の `|` の後ろ。
  - `value`: JSON の文字列。
  - `is_total`: 合計・小計なら 1。
  - `unreadable_reason`: 読めなかった理由。このときは `value_raw` を NULL にして、推測しない。
  - `confidence`、`extractor`、`verified_by` も持つ。
- **検算**: `p2_checker.py` の C1〜C6 が検算し、結果は `extraction_log` に入る。
- **配信**: 条件は `DOC_SERIES_WHERE` = `superseded=0 AND is_total=0 AND value_type IN ('int','float') AND value IS NOT NULL AND fiscal_year IS NOT NULL AND row_key<>''`。
  - 系列の鍵は (doc_id, table_id, row_key) で、点は fiscal_year ごとの1値。
  - 1年に複数の値がある列（月次など）は、`fiscal_year=NULL` にする。
- **notes**: `build_caveat` が caveat（`common:caveat:cells.<note_id>`）にする。
  - `blocks_timeseries=1` は、系列を本当に止める注記にだけ付ける。

## 2. 共通の部品 `scripts/doccells.py`（担当1が最初に入れる）

- `put_document(doc_id, …)`: documents を doc_id で入れ替える。
- `replace_doc_cells(doc_id, rows)`: `DELETE FROM cells WHERE doc_id=?` で消してから入れる。**ほかの doc_id には触れない**。表全体の削除や、extractor を条件にした削除はしない。
- `put_notes(doc_id, notes)`: `note_id = f"{doc_id}_n{連番}"` にする。`DELETE FROM notes WHERE doc_id=?` で消してから入れる。
- `log_check(...)`: `extraction_log` に追記だけする。
- `parse_count(s)`
  - 「5(1)」は (5, 1) を返す。`common.to_number` は「5(1)」を 51 と読むので使わない。
  - 全角、空欄・「-」「－」は None を返す。0 とは区別する。
- `era_to_year(s)`: NFKC で正規化してから `to_fiscal_year` に渡す（`Ｒ１` は全角のままだと None になるため）。
- `check_identity(...)`: 和の検算をし、宣言した例外（原本の誤り）と食い違いが過不足なく一致しなければ止める。
- 検算を先に済ませ、通ってから1つのトランザクションで書く。

## 3. 4つの資料

### a. ウミガメ（`c95_kagoshima_umigame.py`、doc_id `kagoshima_umigame_r7`）
- **取得元**: 県の PDF `…/umigame/documents/2666_20260213091539-1.pdf`（R7年度版）。
- **読み方**: pdfplumber の罫線で読む。
  - p1 は上陸で、H23〜R7 の15年。
  - p2 は産卵で、H22〜R7 の16年。
  - どちらも39市町村で、「市町村数」と「合計」の行が付く。
- **cells への載せ方**
  - table_id は `p1_t1`・`p2_t1`。row_key は市町村名。unit は「回」。
  - 「市町村数」と「合計」は `is_total=1`。
- **検算**
  - 全部の列で、39行の和が合計に一致すること。
  - 値が正の行の数が、市町村数に一致すること。
  - **宣言する例外**は H27 の2つだけ。上陸は表の合計 7,179 に対して和 3,511、産卵は 4,313 に対して 2,151。
  - 誤りの値は印字のまま入れ、notes の footnote に事実を書く。
- **notes**
  - 「総数ではない」（survey_scope）。
  - 「-」と「－」の意味は原本に説明が無いこと。

### b. ノネコ（`c96_kagoshima_noneko.py`、出典 環境省 奄美野生生物保護センター、PDL1.0）
- **表の作り**: 1ページに、月次の表（2022年度）と年度別の表（2018年度（7〜3月）・2019〜2022年度・合計）がある。
  - 行は「捕獲頭数・うち譲渡・うち安楽死・その他」。
- **cells への載せ方**
  - 月次の cells は `fiscal_year=NULL`（系列にしない）。年度別の「合計」の列は `is_total=1`。
- **検算**
  - 行の和が合計に一致すること。
  - 捕獲が「譲渡＋安楽死＋その他」に一致すること。
  - 月次の合計が、年度別の2022年度に一致すること。
  - **宣言する例外**: 2022年度と、月次の3月で、2頭の差がある。
- **notes**: 2018年度は9か月分なので、comparability で `blocks_timeseries=1`、`table_ids=["p1_t2"]` にする。

### c. 観光入込（`c97_kagoshima_irikomi.py`、doc_id `bodik_460001_guntou_irikomi_2024`、CC BY 4.0）
- **取得**: BODIK `460001_guntou_irikomi_nyuiki` の `package_show` から XLSX を落とす。呼び出しの間は5秒以上空ける。
- **使う版**: 2024年版（暦年 2005〜2024）を入れる。2022年版は、重なる年の一致を確かめるのに使う。
- **読み方**: openpyxl で読む。シートは「入込客」（`x1`）と「入域客」（`x2`）、列は海路・空路。
- **cells への載せ方**
  - row_key は `奄美群島|海路` の形。unit は「人」。fiscal_year には暦年を入れる。
  - `source_bbox` は `Sheet!B2` の形にする。
- **notes**: 「暦年である」「奄美大島だけの値ではない」「入込・入域の定義」の3つ。
- 海路と空路の合計は原本に無いので作らない。

### d. ハブ（OCR。doc_id `kagoshima_habu_bite_h28r7`・`kagoshima_habu_kaiage_h28r7`）
- **取得元**: 県薬務課の PDF（咬傷 `…/habu/documents/4348_20260420093052-1.pdf`、買上 `4349_20260420093702-1.pdf`）。画像の1ページで、H28〜R7 の10年度分。
- **表の作り**
  - 咬傷は13行（名瀬保健所の7市町村と計、徳之島保健所の3町と計、合計）。
  - 買上は17行（咬傷の行に、保健所計・業者の名瀬管内・業者の徳之島管内・業者計・全体計が加わる）。
- **cells への載せ方**
  - row_key は `名瀬保健所|奄美市名瀬` の形。
  - 計の行と「合計（3月末）」の列は `is_total=1`。構成比の列は float・%・`fiscal_year=NULL`。
  - 「5(1)」は value=5 にし、死亡数は `…（うち死亡）` という別の行のセルにする。
  - 空欄は value=NULL。検算のときは0として扱い、注記に書く。
- **OCR は2段に分ける**
  - `c98_habu_ocr_run.py`（OCR の venv で動く）
    - PDF を 300dpi にし、画像を3倍に拡大する。
    - Docling＋RapidOCR（日本語）を主に、PaddleOCR を2つ目に回す。
    - 結果は `data/ocr/habu/<doc_id>/{docling_rapid,paddle}.json`（セルの文字・座標・信頼度）に書く。
  - `c98b_habu_cells.py`（OCR のライブラリを使わない。CI の pytest で JSON のフィクスチャから回せる）
    - 格子に戻し、整数の列の小数点を桁区切りの誤読として除き、書式を検査する。
    - 検算する（行の和＝合計、市町村の和＝保健所の計、2つの計の和＝保健所計、構成比）。
    - 2つの OCR を突き合わせる。
  - **人が見る印**: 2つの OCR が食い違ったセル、検算が交点で特定したセル、0 と空欄の区別がつかないセルには、`unreadable_reason="ocr_disagree: …"`、`value_raw=NULL` を付けて採用しない。
  - 人の確認は `data/ocr/habu/<doc_id>/reviewed.csv` に書き、`verified_by="human:<名前>"` にする。
  - `verified_by` は `auto:xocr+arith`、`auto:arith`、`human:*` のどれか。`confidence` は 1.0・0.8・NULL。
- **受け入れ基準**: ベンチの正解（scratchpad の `pdfbench/image/gt/I1_bite.csv`・`I1_kaiage.csv`）と全部のセルが一致すること。正解のファイルはテストのフィクスチャとしてリポジトリに入れる。
- **依存**
  - `scripts/ocr/requirements-docling.txt` と `requirements-paddle.txt` は別の venv にする（torch と paddle が衝突するため）。手順は `scripts/ocr/README.md` に書く。
  - ベンチの venv は scratchpad の `pdfbench/image/venv-docling`・`venv-paddle`（Python 3.10）にある。

## 4. 登録

| 資料 | source_id | 出典 | ライセンス |
|---|---|---|---|
| ウミガメ | `kagoshima_umigame_amami` | 鹿児島県 環境林務部自然保護課 | 県のサイト（事実だけ抜き出し、出典を明記） |
| ハブ | `kagoshima_habu_amami` | 鹿児島県 保健福祉部薬務課 | 同上 |
| ノネコ | `kagoshima_noneko_amami` | 環境省 奄美野生生物保護センター | PDL1.0 |
| 観光入込 | `kagoshima_irikomi_amami` | 鹿児島県 大島支庁総務企画課（BODIK） | CC BY 4.0 |

- `access.yaml`・`license.yaml` の mappings・`LICENSE_MATRIX.md`・`coverage.yaml`（`document_closure.doc_ids`）を直す。
- 件数を直書きしたテスト（source・edition・caveat）を直す。

## 5. 担当と順序

1. **担当1**: `doccells.py`（最初に入れる）、c95、c96、テスト。
2. **担当2**: c97、c98、c98b、`scripts/ocr/*`、`data/ocr/habu/*`、`.gitignore` の例外、テスト。`doccells.py` は §2 の仕様どおりに使う。
3. **統合（メインと担当1）**
   1. c95 → c96 → c97 → c98b を原本に書く。
   2. 書く前に `.backup` を取る。書いた後は、自分の doc_id 以外の行について、全部の表を EXCEPT で突き合わせて差が0であることを確かめる。
   3. r01 → `build:registry:ts` → `build:v2`
   4. サンプル → 一時 clone での CI 再現 → b00。
4. p1_maker・p1_maker_v2・p3_fixer・c25・c26 は回さない。どれもほかの書き手の行を消すため（AMAMI_STEP2A の教訓）。
