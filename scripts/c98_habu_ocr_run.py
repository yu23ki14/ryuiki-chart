"""ハブ統計（画像1枚の PDF）を OCR にかけ、セルの文字・座標・信頼度を JSON に書く。**OCR の venv で動かす**。

設計: docs/plans/AMAMI_STEP2C.md §3d。環境の作り方は scripts/ocr/README.md。

  Docling＋RapidOCR（日本語）:  <venv-docling>/bin/python scripts/c98_habu_ocr_run.py --engine docling_rapid
  PaddleOCR（PP-OCRv5 日本語）: <venv-paddle>/bin/python  scripts/c98_habu_ocr_run.py --engine paddle
（2つは torch と paddle が衝突するので別の venv。このスクリプトの import は、選んだエンジンの分だけ遅延で行う）

- 入力: data/raw/kagoshima_doc/habu_{bite,kaiage}_h28r7.pdf（c98a_habu_fetch.py が保存）。PDF は 300dpi の JPEG 1枚なので、
  `pdfimages -j` で画像をそのまま取り出す（再圧縮しない。1枚で 300dpi 未満のときは `pdftoppm -r 300`）。
  画像が小さい資料のために `--scale`（拡大倍率。既定 1.0。ベンチでは 300dpi の画像はそのままが最良だった）を持つ。
- 格子（行帯・列帯）は画像の罫線から取る（OpenCV。OCR に依存しない）。行・列の数が期待と違えば止める。
  OCR は「文字と座標」だけを担当し、どのセルに入るかの割り当ては c98b_habu_cells.py が JSON から行う。
- 出力: data/ocr/habu/<doc_id>/<engine>.json。座標は画像の（拡大前の）ピクセル。信頼度は PaddleOCR のみ（Docling は null）。
  版（ライブラリ・モデル）と入力の sha256 も書く。結果の JSON はコミットする（CI では OCR を回さない）。
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common   # 標準ライブラリだけで import できる（requests は遅延 import）ので、OCR の venv でも使える

ROOT = common.ROOT
RAW = common.RAW / "kagoshima_doc"
OUT = ROOT / "data/ocr/habu"
sha256 = common.sha256
DOCS = {   # doc_id -> (PDF, 行数〔見出しを除く〕, 列数〔管内・市町村名の2列を除く: 10年度＋合計＋構成比〕)
    "kagoshima_habu_bite_h28r7": ("habu_bite_h28r7.pdf", 13, 12),
    "kagoshima_habu_kaiage_h28r7": ("habu_kaiage_h28r7.pdf", 17, 12),
}
ENGINES = ("docling_rapid", "paddle")


def extract_image(pdf, tmp):
    """PDF（1ページ・画像1枚）-> 300dpi 以上の JPEG のパス"""
    subprocess.run(["pdfimages", "-j", str(pdf), str(tmp / "img")], check=True)
    imgs = sorted(tmp.glob("img-*.jpg"))
    if len(imgs) == 1:
        from PIL import Image
        if Image.open(imgs[0]).size[0] >= 3000:
            return imgs[0]
    subprocess.run(["pdftoppm", "-r", "300", "-jpeg", "-singlefile", str(pdf), str(tmp / "page")], check=True)
    return tmp / "page.jpg"


def _groups(idx, mingap=1):
    g = []
    for i in idx:
        if g and i - g[-1][-1] <= mingap:
            g[-1].append(i)
        else:
            g.append([i])
    return g


def ruled_grid(path, nrow, ncol):
    """画像の罫線から格子を取る。-> dict(rows=[[y0,y1]…], cols=[[x0,x1]…], labelcol=[x0,x1], groupcol=[x0,x1])
    rows は見出しの帯を除く本体の行、cols は年度・合計・構成比の列（管内・市町村名の列は含まない）。"""
    import cv2
    import numpy as np
    im = cv2.imread(str(path), 0)
    h, w = im.shape
    bw = (im < 128).astype(np.uint8)
    hk = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 6, 1)))
    vk = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 12)))
    ys = [float(np.mean(g)) for g in _groups(np.where(hk.sum(1) > w * 0.4)[0])]
    xs = [float(np.mean(g)) for g in _groups(np.where(vk.sum(0) > h * 0.25)[0])]
    rows = [[ys[i], ys[i + 1]] for i in range(len(ys) - 1)][1:]
    cols = [[xs[i], xs[i + 1]] for i in range(len(xs) - 1)]
    if len(rows) != nrow or len(cols) != ncol + 2:
        raise SystemExit(f"格子が期待と違う: 行 {len(rows)}（期待 {nrow}）、列 {len(cols)}（期待 {ncol + 2}）。罫線の検出を確かめる")
    return dict(rows=rows, cols=cols[2:], labelcol=cols[1], groupcol=cols[0])


def run_docling_rapid(img, W, H):
    from docling.document_converter import DocumentConverter, ImageFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, TableFormerMode
    po = PdfPipelineOptions()
    po.do_ocr = True
    po.do_table_structure = True
    po.table_structure_options.mode = TableFormerMode.ACCURATE
    po.table_structure_options.do_cell_matching = True
    po.ocr_options = RapidOcrOptions(lang=["iso:ja"], force_full_page_ocr=True)
    conv = DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=po)})
    r = conv.convert(str(img))
    pw, ph = r.pages[0].size.width, r.pages[0].size.height
    k = W / pw   # docling の座標 -> 画像のピクセル
    boxes = []
    for tb in r.document.tables:
        for c in tb.data.table_cells:
            if not c.text.strip():
                continue
            bb = c.bbox.to_top_left_origin(ph)
            boxes.append(dict(text=c.text, x0=bb.l * k, y0=bb.t * k, x1=bb.r * k, y1=bb.b * k, conf=None))
    return boxes


def run_paddle(img, W, H):
    import os
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR
    o = PaddleOCR(lang="japan", ocr_version="PP-OCRv5", use_doc_orientation_classify=False, use_doc_unwarping=False,
                  use_textline_orientation=False, enable_mkldnn=False, text_det_limit_side_len=1600,
                  text_det_limit_type="max")
    r = o.predict(str(img))[0]
    boxes = []
    for poly, txt, conf in zip(r["rec_polys"], r["rec_texts"], r["rec_scores"]):
        xs = [q[0] for q in poly]
        ys = [q[1] for q in poly]
        boxes.append(dict(text=txt, x0=float(min(xs)), y0=float(min(ys)), x1=float(max(xs)), y1=float(max(ys)),
                          conf=float(conf)))
    return boxes


def versions(engine):
    from importlib import metadata
    names = {"docling_rapid": ["docling", "rapidocr", "onnxruntime"], "paddle": ["paddleocr", "paddlepaddle", "paddlex"]}[engine]
    out = {}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=ENGINES)
    ap.add_argument("--doc", choices=sorted(DOCS), help="省略すると全部")
    ap.add_argument("--scale", type=float, default=1.0, help="OCR に渡す前の拡大倍率（座標は拡大前に戻して書く）")
    a = ap.parse_args()
    from PIL import Image
    for doc_id, (pdf_name, nrow, ncol) in DOCS.items():
        if a.doc and a.doc != doc_id:
            continue
        pdf = RAW / pdf_name
        if not pdf.exists():
            raise SystemExit(f"{pdf} が無い。先に scripts/c98a_habu_fetch.py")
        with tempfile.TemporaryDirectory() as td:
            td = pathlib.Path(td)
            img = extract_image(pdf, td)
            W, H = Image.open(img).size
            grid = ruled_grid(img, nrow, ncol)
            feed = img
            if a.scale != 1.0:
                feed = td / "scaled.png"
                Image.open(img).resize((int(W * a.scale), int(H * a.scale)), Image.LANCZOS).save(feed)
            t0 = time.time()
            boxes = (run_docling_rapid if a.engine == "docling_rapid" else run_paddle)(feed, int(W * a.scale), int(H * a.scale))
            dt = time.time() - t0
            if a.scale != 1.0:
                for b in boxes:
                    for k in ("x0", "y0", "x1", "y1"):
                        b[k] /= a.scale
            out = OUT / doc_id / f"{a.engine}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            json.dump(dict(doc_id=doc_id, engine=a.engine, versions=versions(a.engine), pdf_sha256=sha256(pdf),
                           image=dict(width=W, height=H, sha256=sha256(img), scale=a.scale),
                           seconds=round(dt, 1), grid=grid, boxes=boxes),
                      open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
            print(f"{doc_id} {a.engine}: {len(boxes)} boxes  {dt:.0f}s -> {out.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
