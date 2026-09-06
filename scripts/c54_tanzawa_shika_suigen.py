"""丹沢のシカ管理実績PDF・水源環境保全再生 最終評価報告書
- documents 登録
- 表の目次(ページ・見出し語)を data/processed/tanzawa_shika_suigen_index.csv に作成(中身の抽出はしない)
"""
import sys, pathlib, sqlite3, csv
sys.path.insert(0, "scripts")
from common import register, write_jsonl, sha256, now, RAW, PROC, DB

PUBLISHER = "神奈川県 環境農政局 自然環境保全課 / 水源環境保全・再生かながわ県民会議"
LICENSE = "政府標準利用規約(第2.0版)相当（要確認）"

DOCS = [
    ("tanzawa_shika_r6", "ニホンジカ管理捕獲等実績(令和6年度)",
     "https://www.pref.kanagawa.jp/documents/40200/shikajisseki_r6_2.pdf",
     RAW / "tanzawa_shika" / "shikajisseki_r6_2.pdf"),
    ("tanzawa_shika_r4", "ニホンジカ管理捕獲等実績(令和4年度)",
     "https://www.pref.kanagawa.jp/documents/40200/r4_shika_jisseki.pdf",
     RAW / "tanzawa_shika" / "r4_shika_jisseki.pdf"),
    ("tanzawa_shika_plan5", "神奈川県ニホンジカ保護管理計画(第5次)",
     "https://www.pref.kanagawa.jp/documents/40200/5shikakeikaku.pdf",
     RAW / "tanzawa_shika" / "5shikakeikaku.pdf"),
    ("suigen_hozen_final_eval", "水源環境保全・再生実行5か年計画 最終評価報告書",
     "https://www.pref.kanagawa.jp/documents/108565/document3-2.pdf",
     RAW / "suigen_hozen" / "document3-2.pdf"),
]

KEYWORDS = ["捕獲", "実績", "頭数", "生息密度", "個体数", "調整", "区域別", "年度別",
            "経年", "推移", "総括表", "一覧表", "植生", "衰退", "モニタリング", "指標",
            "評価結果", "施策評価", "指標調査結果"]


def main():
    import fitz
    cdb = sqlite3.connect(DB / "cells.sqlite")
    index_rows = []
    n_docs = 0
    for doc_id, title, url, dest in DOCS:
        if not dest.exists():
            print(f"  [MISSING FILE] {dest}")
            continue
        h = sha256(dest)
        doc = fitz.open(dest)
        n_pages = doc.page_count
        cdb.execute("""INSERT OR REPLACE INTO documents
            (doc_id, title, publisher, url, local_path, doc_sha256, n_pages, fiscal_year, license, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, title, PUBLISHER, url, str(dest.relative_to(pathlib.Path.cwd())),
             h, n_pages, None, LICENSE, now()))
        cdb.commit()
        n_docs += 1
        print(f"  [doc] {doc_id}: {n_pages} pages, sha256={h[:12]}...")

        for pno in range(n_pages):
            page = doc[pno]
            text = page.get_text()
            hits = [k for k in KEYWORDS if k in text]
            if not hits:
                continue
            if text.count("\n") < 5:
                continue
            caption_line = ""
            for line in text.split("\n"):
                if any(k in line for k in KEYWORDS):
                    caption_line = line.strip()
                    break
            index_rows.append({
                "doc_id": doc_id,
                "page_no": pno + 1,
                "table_caption": caption_line or "/".join(hits),
                "taxon_group": "shika" if "shika" in doc_id else "suigen_hozen",
                "source_ref": url,
            })
        doc.close()
    cdb.close()

    if index_rows:
        p = PROC / "tanzawa_shika_suigen_index.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["doc_id", "page_no", "table_caption", "taxon_group", "source_ref"])
            w.writeheader()
            for r in index_rows:
                w.writerow(r)
        write_jsonl("tanzawa_shika_suigen_index", index_rows)
        print(f"  [write] {p} ({len(index_rows)} rows)")

    register(
        source_id="tanzawa_shika_suigen_docs",
        name="丹沢 ニホンジカ管理実績・保護管理計画/水源環境保全再生 最終評価報告書",
        publisher=PUBLISHER,
        url="https://www.pref.kanagawa.jp/docs/f4y/03shinrin/e-tanzawa/siryousitu.html",
        category="丹沢(シカ管理・水源環境)",
        access_method="PDF個別ダウンロード",
        fmt="PDF",
        license_=LICENSE,
        redistributable=1,
        record_count=n_docs,
        notes=(
            "表抽出はせず、documents登録とtable_captionの目次作成のみ実施。"
            "令和4年度・令和6年度は捕獲実績年度が2年離れており(令和5年度分は本タスクのURLリストになし)、"
            "経年比較には令和5年度分の欠測を明記する必要がある。"
        ),
    )


if __name__ == "__main__":
    main()
