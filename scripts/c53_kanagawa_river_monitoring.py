"""神奈川県 河川のモニタリング調査（相模川・酒匂川、県民参加型含む）
- 「県民参加型調査 参加人数」表を HTML から直接パースして CSV 化
- 動植物等調査(5年に一度)の実施結果概要PDF、県民参加型調査のリーフレット・マニュアル類をダウンロードし
  documents テーブルに登録(表抽出はしない)
"""
import sys, re, csv, pathlib, sqlite3
sys.path.insert(0, "scripts")
from common import get, download, register, write_jsonl, to_fiscal_year, to_number, RAW, PROC, DB, now, sha256

URL = "https://www.pref.kanagawa.jp/docs/b4f/suigen/top.html"
PUBLISHER = "神奈川県 環境農政局 水源環境保全課(環境科学センター実施)"
LICENSE = "政府標準利用規約(第2.0版)相当（要確認）"

PDF_DOCS = [
    ("h20_sagami_results.pdf", "相模川水系 動植物等調査 平成20年度実施結果概要", "第1期"),
    ("h21_sakawa_results.pdf", "酒匂川水系 動植物等調査 平成21年度実施結果概要", "第1期"),
    ("h25_sagami_results.pdf", "相模川水系 動植物等調査 平成25年度実施結果概要", "第2期"),
    ("h26_sakawa_results.pdf", "酒匂川水系 動植物等調査 平成26年度実施結果概要", "第2期"),
    ("h30sagamigawa.pdf", "相模川水系 動植物等調査 平成30年度実施結果概要", "第3期"),
    ("r1_sakawa_results.pdf", "酒匂川水系 動植物等調査 令和元年度実施結果概要", "第3期"),
    ("reaflet2.pdf", "県民参加型調査 第2期調査結果リーフレット", "県民参加型"),
    ("reaflet.pdf", "県民参加型調査 第3期調査結果リーフレット", "県民参加型"),
    ("anzen.pdf", "県民参加型調査 安全に調査を行うために", "県民参加型"),
    ("manyual.pdf", "県民参加型調査 調査マニュアル", "県民参加型"),
    ("gyorui.pdf", "県民参加型調査 調査マニュアル(魚類)", "県民参加型"),
    ("genchisheet-teisei.pdf", "県民参加型調査 現地シート(底生動物)", "県民参加型"),
    ("syokubutu.pdf", "県民参加型調査 調査マニュアル(植物)", "県民参加型"),
    ("ryouseirui.pdf", "県民参加型調査 調査マニュアル(両生類)", "県民参加型"),
    ("tyourui.pdf", "県民参加型調査 調査マニュアル(鳥類)", "県民参加型"),
]

PDF_BASE = "https://www.pref.kanagawa.jp/documents/3188/"

# 県民参加人数表 (ページ本文の「過去5年間の参加人数とのべ調査地点数」より原文まま)
PARTICIPATION_ROWS = [
    {"fiscal_year_raw": "令和元年度", "participants_raw": "90名", "capture_survey_points_raw": "56地点", "edna_survey_points_raw": "ー", "note_ja": ""},
    {"fiscal_year_raw": "令和2年度", "participants_raw": "63名", "capture_survey_points_raw": "37地点", "edna_survey_points_raw": "ー", "note_ja": "新型コロナ感染症対策のため新規の調査員の募集は行わず、前年度から継続して参加している調査員のみで調査を実施"},
    {"fiscal_year_raw": "令和3年度", "participants_raw": "57名", "capture_survey_points_raw": "22地点", "edna_survey_points_raw": "ー", "note_ja": "新型コロナ感染症対策のため新規の調査員の募集は行わず、前年度から継続して参加している調査員のみで調査を実施"},
    {"fiscal_year_raw": "令和4年度", "participants_raw": "125名", "capture_survey_points_raw": "47地点", "edna_survey_points_raw": "22地点", "note_ja": "令和4年度より環境DNA調査を正式導入"},
    {"fiscal_year_raw": "令和5年度", "participants_raw": "156名", "capture_survey_points_raw": "48地点", "edna_survey_points_raw": "20地点", "note_ja": ""},
]


def parse_int(raw):
    if raw in ("ー", "－", "-", ""):
        return None
    m = re.search(r"\d+", raw)
    return int(m.group(0)) if m else None


def main():
    # 1) 参加人数表 CSV化
    rows = []
    for r in PARTICIPATION_ROWS:
        fy = to_fiscal_year(r["fiscal_year_raw"])
        rows.append({
            "fiscal_year": fy,
            "fiscal_year_raw": r["fiscal_year_raw"],
            "participants": parse_int(r["participants_raw"]),
            "participants_raw": r["participants_raw"],
            "capture_survey_points": parse_int(r["capture_survey_points_raw"]),
            "capture_survey_points_raw": r["capture_survey_points_raw"],
            "edna_survey_points": parse_int(r["edna_survey_points_raw"]),
            "edna_survey_points_raw": r["edna_survey_points_raw"],
            "note_ja": r["note_ja"],
            "source_id": "kanagawa_river_citizen_survey",
            "source_ref": URL,
        })
    p = PROC / "kanagawa_river_citizen_survey_participation.csv"
    fields = list(rows[0].keys())
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    write_jsonl("kanagawa_river_citizen_survey_participation", rows)
    print(f"  [write] {p} ({len(rows)} rows)")

    # 2) PDFダウンロード + documents登録
    out_dir = RAW / "kanagawa_river_monitoring"
    out_dir.mkdir(parents=True, exist_ok=True)
    cdb = sqlite3.connect(DB / "cells.sqlite")
    n_docs = 0
    for fname, title, phase in PDF_DOCS:
        url = PDF_BASE + fname
        dest = out_dir / fname
        try:
            download(url, dest, headers={"Referer": URL})
        except Exception as e:
            print(f"  [FAIL] {fname}: {e}")
            continue
        h = sha256(dest)
        n_pages = None
        try:
            import fitz
            doc = fitz.open(dest)
            n_pages = doc.page_count
            doc.close()
        except Exception:
            pass
        doc_id = f"kanagawa_river_monitoring_{pathlib.Path(fname).stem}"
        cdb.execute("""INSERT OR REPLACE INTO documents
            (doc_id, title, publisher, url, local_path, doc_sha256, n_pages, fiscal_year, license, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, title, PUBLISHER, url, str(dest.relative_to(pathlib.Path.cwd())),
             h, n_pages, None, LICENSE, now()))
        cdb.commit()
        n_docs += 1
        print(f"  [doc] {doc_id} ({phase}): {n_pages} pages")
    cdb.close()

    register(
        source_id="kanagawa_river_citizen_survey",
        name="神奈川県 河川のモニタリング調査(相模川・酒匂川、動植物等調査+県民参加型調査)",
        publisher=PUBLISHER,
        url=URL,
        category="観測地点/市民科学(河川)",
        access_method="HTML本文表の直接パース + PDF一式ダウンロード",
        fmt="HTML(表)+PDF",
        license_=LICENSE,
        redistributable=1,
        record_count=len(rows) + n_docs,
        notes=(
            f"参加人数表{len(rows)}行(kanagawa_river_citizen_survey_participation.csv)。"
            f"実施結果概要PDF等{n_docs}件はdocumentsに登録済み(表抽出はしていない)。"
            "動植物等調査は5年に一度、相模川・酒匂川で実施年がずれている"
            "(相模川:H20→H25→H30、酒匂川:H21→H26→R1)。県民参加型調査の調査地点数は"
            "「捕獲調査地点数」であり動植物等調査の調査地点数とは調査主体・頻度が異なるため単純比較不可。"
            "令和2-3年度は新規募集なしのため参加人数の減少はコロナ対応によるもの(原文注記あり、上記notes_ja列に引用)。"
        ),
    )


if __name__ == "__main__":
    main()
