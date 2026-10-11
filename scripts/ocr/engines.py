"""OCR エンジンの呼び出しと JSON の書き出し（表の形に依らない部分）。**OCR の venv で動かす**。
import は選んだエンジンの分だけ遅延で行う（docling と paddle は別の venv）。

ハブ統計の c98_habu_ocr_run.py から移した（設計: docs/plans/AMAMI_STEP3A.md §5）。格子の取り方は表ごとに違うので
各 ocr_run スクリプトに置く。
"""
import hashlib
import json
import pathlib
import tempfile
import time

ENGINES = ("docling_rapid", "paddle")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def ocr_image(engine, img, scale=1.0):
    """画像を（scale 倍に拡大して）OCR にかける。-> (boxes〔座標は拡大前の画像のピクセル〕, 秒数, (W, H))"""
    from PIL import Image
    W, H = Image.open(img).size
    with tempfile.TemporaryDirectory() as td:
        feed = pathlib.Path(img)
        if scale != 1.0:
            feed = pathlib.Path(td) / "scaled.png"
            Image.open(img).resize((int(W * scale), int(H * scale)), Image.LANCZOS).save(feed)
        t0 = time.time()
        boxes = (run_docling_rapid if engine == "docling_rapid" else run_paddle)(feed, int(W * scale), int(H * scale))
        dt = time.time() - t0
    if scale != 1.0:
        for b in boxes:
            for k in ("x0", "y0", "x1", "y1"):
                b[k] /= scale
    return boxes, dt, (W, H)


def write_json(out, doc_id, engine, input_sha, image_sha, size, scale, grid, boxes, seconds):
    """JSON の形は c98 が書いてきたものと同じ（`pdf_sha256` のキーは入力が PNG のときも変えない。ハブの JSON を壊さない）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(dict(doc_id=doc_id, engine=engine, versions=versions(engine), pdf_sha256=input_sha,
                   image=dict(width=size[0], height=size[1], sha256=image_sha, scale=scale),
                   seconds=round(seconds, 1), grid=grid, boxes=boxes),
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
