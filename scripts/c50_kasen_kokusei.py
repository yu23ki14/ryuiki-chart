"""相模川 河川水辺の国勢調査 PDF収集 (京浜河川事務所)
- PDFをdata/raw/kasen_kokusei/に落とす
- cells.sqlite の documents に登録
- 表の目次(どのページに種リスト表があるか)を data/processed/kasen_kokusei_index.csv に出す
  (表の中身の抽出はしない)
"""
import sys, pathlib, sqlite3, re
sys.path.insert(0, "scripts")
from common import get, download, register, write_jsonl, sha256, now, RAW, PROC, DB

BASE = "https://www.ktr.mlit.go.jp/keihin/keihin_content_id/"  # placeholder unused
PDF_BASE = "https://www.ktr.mlit.go.jp/ktr_content/content/"
PAGE_URL = "https://www.ktr.mlit.go.jp/keihin/keihin00294.html"

DOCS = [
    ("000057870.pdf", "魚類調査（平成19年度）", "fish"),
    ("000057871.pdf", "底生動物調査（平成20年度）", "benthos"),
    ("000057873.pdf", "鳥類調査（平成21年度）", "birds"),
    ("000057872.pdf", "植物調査（平成17年度）", "plants"),
    ("000057875.pdf", "陸上昆虫類等調査（平成18年度）", "insects"),
    ("000057874.pdf", "両生類・爬虫類・哺乳類調査（平成16年度）", "herptile_mammal"),
]

PUBLISHER = "国土交通省 関東地方整備局 京浜河川事務所"
LICENSE = "政府標準利用規約(第2.0版)相当・国交省地方整備局サイトの二次利用ルールに準拠（要確認）"

def main():
    import fitz  # pymupdf
    out_dir = RAW / "kasen_kokusei"
    out_dir.mkdir(parents=True, exist_ok=True)

    cdb = sqlite3.connect(DB / "cells.sqlite")
    index_rows = []
    n_docs = 0
    for fname, title, group in DOCS:
        url = PDF_BASE + fname
        dest = out_dir / fname
        try:
            download(url, dest, headers={"Referer": PAGE_URL})
        except Exception as e:
            print(f"  [FAIL] {fname}: {e}")
            continue
        h = sha256(dest)
        doc = fitz.open(dest)
        n_pages = doc.page_count
        doc_id = f"kasen_kokusei_sagami_{group}"

        cdb.execute("""INSERT OR REPLACE INTO documents
            (doc_id, title, publisher, url, local_path, doc_sha256, n_pages, fiscal_year, license, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, f"相模川 河川水辺の国勢調査 {title}", PUBLISHER, url,
             str(dest.relative_to(pathlib.Path.cwd())), h, n_pages, None, LICENSE, now()))
        cdb.commit()
        n_docs += 1
        print(f"  [doc] {doc_id}: {n_pages} pages, sha256={h[:12]}...")

        # 目次作成: ページ内のテキストを見て「種リスト表」らしきページを拾う (中身は抽出しない)
        keywords = ["確認種", "確認された", "出現種", "種名", "種リスト", "調査結果一覧",
                    "確認状況", "総括表", "経年", "科名", "目名", "確認種類数"]
        for pno in range(n_pages):
            page = doc[pno]
            text = page.get_text()
            hits = [k for k in keywords if k in text]
            if not hits:
                continue
            # テーブルらしさの簡易判定: get_text("dict")のブロック数がある程度多い、
            # もしくは罫線的な行が多い
            n_lines = text.count("\n")
            if n_lines < 5:
                continue
            caption_line = ""
            for line in text.split("\n"):
                if any(k in line for k in keywords):
                    caption_line = line.strip()
                    break
            index_rows.append({
                "doc_id": doc_id,
                "page_no": pno + 1,
                "table_caption": caption_line or "/".join(hits),
                "taxon_group": group,
                "source_ref": url,
            })
        doc.close()

    cdb.close()

    if index_rows:
        import csv
        p = PROC / "kasen_kokusei_index.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["doc_id", "page_no", "table_caption", "taxon_group", "source_ref"])
            w.writeheader()
            for r in index_rows:
                w.writerow(r)
        write_jsonl("kasen_kokusei_index", index_rows)
        print(f"  [write] {p} ({len(index_rows)} rows)")

    register(
        source_id="kasen_kokusei_sagami",
        name="河川水辺の国勢調査（相模川）",
        publisher=PUBLISHER,
        url=PAGE_URL,
        category="生物調査(河川)",
        access_method="PDF個別ダウンロード(京浜河川事務所サイト掲載分)",
        fmt="PDF",
        license_=LICENSE,
        redistributable=1,
        record_count=n_docs,
        notes=(
            "河川環境データベース(旧www5.river.go.jp)はDNS解決不可・実質アクセス不能のため、"
            "京浜河川事務所サイト掲載のPDF一覧のみを収集。表抽出はせず、documents登録と"
            "table_captionの目次作成のみ実施。相模川の掲載年度は魚類H19,底生動物H20,鳥類H21,"
            "植物H17,陸上昆虫H18,両生類爬虫類哺乳類H16と分類群ごとに調査年度がバラバラであり、"
            "経年比較はできない点に注意。"
        ),
    )

if __name__ == "__main__":
    main()
