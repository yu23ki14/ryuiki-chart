"""奄美大島のマングース捕獲数・わな日・CPUE の表（PNG 1枚）を OCR にかけ、セルの文字・座標・信頼度を JSON に書く。
**OCR の venv で動かす**。設計: docs/plans/AMAMI_STEP3A.md §5・§6。環境の作り方は scripts/ocr/README.md。

  Docling＋RapidOCR: <venv-docling>/bin/python scripts/c100_mongoose_ocr_run.py --engine docling_rapid
  PaddleOCR:         <venv-paddle>/bin/python  scripts/c100_mongoose_ocr_run.py --engine paddle

- 入力: data/raw/moe_mongoose/r4_hyo1_000157229.png（c100a_mongoose_fetch.py が保存。565×646 と小さいので --scale 3 が既定）。
- 格子（uniform_grid）: この表は罫線が少なく、横の全幅の罫線は「見出しの下」と「合計の上」の2本だけで、縦の罫線は無い。
  2本の罫線（morphology）の間を 23 等分して年度の行の帯にし、合計の行の帯はその下（同じ高さ）。
  列は右揃えの数字の右端で決めた5列の x（COLS。画像の sha256 が固定なので固定値）。年度のラベルの列は格子の外
  （labelcol。検査にだけ使う）。行は 24（23 年度＋合計）・列は 5 でなければ止める。
- OCR は「文字と座標」だけを担当し、どのセルに入るかの割り当ては c100b が ocr/cellmatch.py で JSON から行う。
- 出力: data/ocr/mongoose/<doc_id>/<engine>.json（ハブと同じ形。`pdf_sha256` のキーには PNG の sha256 が入る）。
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ocr import engines
import common   # 標準ライブラリだけで import できる ので、OCR の venv でも使える

ROOT = common.ROOT
PNG = common.RAW / "moe_mongoose" / "r4_hyo1_000157229.png"
OUT = ROOT / "data/ocr/mongoose"
DOC_ID = "moe_mongoose_catch_h12r4"
PNG_SHA256 = "8fd8a498"   # 先頭8桁（実体の全桁は JSON と c100b が照合する）
NROW, NCOL = 24, 5
N_YEAR_ROWS = 23
# 列の x 範囲 [x0, x1]（画像のピクセル）。わな捕獲の捕獲頭数・のべわな日・CPUE・探索犬・総捕獲頭数。
COLS = [[140, 250], [250, 345], [345, 440], [440, 505], [505, 566]]
LABELCOL = [0, 140]


def uniform_grid(path, n_year_rows=N_YEAR_ROWS, cols=COLS):
    """画像の全幅の横罫線のうち、見出しの下・合計の上の2本を見つけ、その間を n_year_rows 等分する。
    -> dict(rows=[[y0,y1]…]〔年度の行 n_year_rows＋合計の行 1〕, cols=…, labelcol=…, groupcol=…)"""
    import cv2
    import numpy as np
    im = cv2.imread(str(path), 0)
    h, w = im.shape
    bw = (im < 128).astype(np.uint8)
    hk = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 2, 1)))
    # 画像の縁（枠）と、表の下の注記の枠は除く: 高さの 3%〜93% の範囲の罫線だけを見る
    ys = [float(np.mean(g)) for g in engines.groups(np.where(hk.sum(1) > w * 0.9)[0])
          if h * 0.03 < np.mean(g) < h * 0.93]
    if len(ys) != 2:
        raise SystemExit(f"全幅の横罫線が2本ではない: {ys}（見出しの下と合計の上を期待）。罫線の検出を確かめる")
    top, bot = ys
    pitch = (bot - top) / n_year_rows
    rows = [[top + i * pitch, top + (i + 1) * pitch] for i in range(n_year_rows + 1)]
    return dict(rows=rows, cols=[list(map(float, c)) for c in cols], labelcol=[float(v) for v in LABELCOL],
                groupcol=[float(v) for v in LABELCOL])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=engines.ENGINES)
    ap.add_argument("--scale", type=float, default=3.0, help="OCR に渡す前の拡大倍率（小さい画像なので既定 3。座標は拡大前に戻して書く）")
    a = ap.parse_args()
    if not PNG.exists():
        raise SystemExit(f"{PNG} が無い。先に scripts/c100a_mongoose_fetch.py")
    sha = common.sha256(PNG)
    if not sha.startswith(PNG_SHA256):
        raise SystemExit(f"PNG の sha256 が想定と違う（{sha}）。列の x を決め直す必要がある")
    grid = uniform_grid(PNG)
    if len(grid["rows"]) != NROW or len(grid["cols"]) != NCOL:
        raise SystemExit(f"格子が {len(grid['rows'])}行×{len(grid['cols'])}列（期待 {NROW}×{NCOL}）")
    boxes, dt, size = engines.ocr_image(a.engine, PNG, a.scale)
    out = OUT / DOC_ID / f"{a.engine}.json"
    engines.write_json(out, DOC_ID, a.engine, sha, sha, size, a.scale, grid, boxes, dt)
    print(f"{DOC_ID} {a.engine}: {len(boxes)} boxes  {dt:.0f}s -> {out.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
