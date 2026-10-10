# OCR の環境（ハブ統計）

`scripts/c98_habu_ocr_run.py` を回すための環境。**OCR は手元で1回回して、結果の JSON を `data/ocr/habu/` にコミットする**。
CI・通常の開発では OCR を回さない（`scripts/c98b_habu_cells.py` が JSON だけを読む。OCR のライブラリは要らない）。
設計は `docs/plans/AMAMI_STEP2C.md` §3d。

## 2つの venv（別々に作る）

Docling（torch）と PaddleOCR（paddle）は同じ環境に入れると衝突するので、別の venv にする。どちらも Python 3.10。
版は `requirements-docling.txt`・`requirements-paddle.txt`（`uv pip freeze` の出力）で固定している。

```
uv venv --python 3.10 $HOME/.venvs/ocr-docling
uv pip install -p $HOME/.venvs/ocr-docling/bin/python -r scripts/ocr/requirements-docling.txt   # torch は CPU 版（ファイル内の extra-index-url）
uv venv --python 3.10 $HOME/.venvs/ocr-paddle
uv pip install -p $HOME/.venvs/ocr-paddle/bin/python -r scripts/ocr/requirements-paddle.txt
```

- 画像の取り出しに poppler（`pdfimages`・`pdftoppm`）が要る（`apt install poppler-utils`）。
- モデルは初回に自動で落ちる。RapidOCR のモデルは venv の `site-packages/rapidocr/models/`、PaddleOCR は `~/.paddlex/official_models/`
  （PP-OCRv5 の server 版 det・rec）。ネットワークが要る。
- venv は **リポジトリの外**に作る（上の例は `$HOME/.venvs/`）。コミットしない。

## 回し方

```
python3 scripts/c98a_habu_fetch.py                    # PDF を data/raw/kagoshima_doc/ に保存（通常の venv。requests が要る）
$HOME/.venvs/ocr-docling/bin/python scripts/c98_habu_ocr_run.py --engine docling_rapid    # 約1〜2分/資料（CPU）
$HOME/.venvs/ocr-paddle/bin/python  scripts/c98_habu_ocr_run.py --engine paddle           # 約2〜3分/資料（CPU）
python3 scripts/c98b_habu_cells.py --dry-run          # OCR 依存なし。JSON -> 格子 -> 検算 -> 突き合わせ
python3 scripts/c98b_habu_cells.py                    # cells・documents・notes に書く（自分の doc_id の行だけを入れ替える）
```

`c98_habu_ocr_run.py` は、PDF（300dpi の JPEG が1枚）から画像を取り出し、罫線から格子（行帯・列帯）を取って、
OCR の文字・座標・信頼度とともに `data/ocr/habu/<doc_id>/<engine>.json` に書く。JSON には版と入力の sha256 も入る。

## 人の確認（reviewed.csv）

2つの OCR が食い違ったセル、検算が交点で特定したセル、0 と空欄の区別がつかないセルは、`c98b` が
`unreadable_reason="ocr_disagree: …"`、`value_raw=NULL` で入れ、**値を採用しない**。`c98b --dry-run` の出力と
cells の `unreadable_reason` に、2つの OCR の読みと検算の示す値（手がかり）が出る。画像の該当セルを見て、
`data/ocr/habu/<doc_id>/reviewed.csv` に1行足す。

```
row,col,value,reviewer,note
名瀬保健所|奄美市住用町,H29,995,<名前>,<根拠>
```

- `row` は row_key、`col` は col_key（`H28`〜`R7`・`合計(3月末)`・`構成比`）、`value` は原表の表記（カンマ・括弧・% も可。空欄は空）。
- 採用されたセルは `verified_by="human:<名前>"`・confidence 1.0（reviewer が `claude(vision)` など AI のときは `claude(vision)` のまま。人の確認を装わない）。人が入れた値も検算にかけ、合わなければ警告が出る。
- `reviewer` は確認した人の名前。画像を見たのが Claude のときは `claude(vision)`（`data/cells` の前例 c26 と同じ流儀）。
  **人が見直すときは名前を書き換える**。現在の reviewed.csv の3セル（買上の `名瀬保健所|奄美市住用町` H29、`名瀬保健所|名瀬計` R5、`業者|名瀬管内` R2）は
  **人の見直しが済んでいない**（claude(vision) が画像で確認し、検算も合っている）。

## verified_by と confidence

| verified_by | confidence | 意味 |
|---|---|---|
| `auto:xocr+arith` | 1.0 | 2つの OCR が一致し、書式が正しく、そのセルが入る検算が通った |
| `human:<名前>` | 1.0 | reviewed.csv の人の確認 |
| `claude(vision)` | 1.0 | reviewed.csv の AI（画像を見た Claude）の確認。人の見直しは未済 |
| `auto:xocr` | 0.8 | 一致したが、検算で確かめられない（そのセルが入る検算が1つも評価できない。未確定のセルが相手のとき、または構成比が空欄のとき） |
| NULL | NULL | 未採用（`unreadable_reason` に理由） |

`auto:arith`（OCR が食い違うのに検算だけで決める）は作らない。検算が示す値は手がかりとして理由に書くだけで、採用しない。

## ベンチ（2026-10-10、設計担当）

Docling＋RapidOCR と PaddleOCR（PP-OCRv5）は、300dpi のままの画像でハブの2表（咬傷 153 数値セル・買上 200）を
それぞれ 100%・98.5%（Docling、買上で3セルの桁の誤り）／100%・100%（Paddle）で読んだ。整数の列の「.」を桁区切りの誤読として
除く後処理は c98b に入っている。ほかのエンジン（EasyOCR・YomiToku・NDLOCR-Lite）とも比べ、この2つの組み合わせを採った。
