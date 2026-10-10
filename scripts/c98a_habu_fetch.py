"""鹿児島県のハブ統計 PDF を data/raw/kagoshima_doc/ に保存する（取得だけ。cells は作らない）。

設計: docs/plans/AMAMI_STEP2C.md §3d・§0 決定7。

- 年度別の2表（咬傷者・買上）: 県薬務課のページ（habusiryo2_27841・habusiryo_27840）の PDF。画像1枚の PDF で、
  c98_habu_ocr_run.py が OCR にかけ、c98b_habu_cells.py が cells にする。
- 月次: 大島支庁のハブ情報ページ（habu-joho.html）の「ハブ月報」欄にある、今の1件分（ハブ情報・市町村別月毎咬傷者数・
  市町村別月毎ハブ買上数）。**保存するだけ**で、cells にはしない（決定7）。
- 原本の PDF は再配布しない（data/raw は gitignore 済み）。sha256 は documents.doc_sha256 に入る。
- 呼び出しの間は 5 秒以上空ける。

使い方: python3 scripts/c98a_habu_fetch.py [--only annual|monthly]
"""
import argparse
import re
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common

BASE = "https://www.pref.kagoshima.jp"
OUT = common.RAW / "kagoshima_doc"
SLEEP = 5.0

# 年度別（doc_id の接尾辞 -> (ページ, ファイル名, 保存名)）。PDF の URL はページから引く（番号・日時が更新で変わる）
ANNUAL = {
    "bite": (f"{BASE}/ae10/kenko-fukushi/yakuji-eisei/habu/habusiryo2_27841.html", "habu_bite_h28r7.pdf"),
    "kaiage": (f"{BASE}/ae10/kenko-fukushi/yakuji-eisei/habu/habusiryo_27840.html", "habu_kaiage_h28r7.pdf"),
}
MONTHLY_PAGE = f"{BASE}/aq04/chiiki/oshima/kurashi/habu-joho.html"
MONTHLY_KINDS = {"ハブ情報": "monthly_info", "市町村別月毎咬傷者数": "monthly_bite", "市町村別月毎ハブ買上数": "monthly_kaiage"}


def pdf_links(html):
    """ページの HTML -> [(リンク文字列, PDF の絶対 URL)]"""
    out = []
    for m in re.finditer(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        out.append((text, href if href.startswith("http") else BASE + href))
    return out


def page_html(url):
    time.sleep(SLEEP)
    return common.get(url).content.decode("utf-8", errors="replace")   # 県のページは charset 指定が弱く requests が ISO-8859-1 と推測する


def save(url, name):
    dest = OUT / name
    time.sleep(SLEEP)
    r = common.get(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    print(f"  [save] {dest.relative_to(common.ROOT)}  {len(r.content)} bytes  sha256={common.sha256(dest)[:12]}  <- {url}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["annual", "monthly"])
    a = ap.parse_args()
    if a.only != "monthly":
        for kind, (page, name) in ANNUAL.items():
            links = pdf_links(page_html(page))
            if len(links) != 1:
                raise SystemExit(f"{page}: PDF のリンクが {len(links)} 件（1件のはず）: {links}")
            save(links[0][1], name)
    if a.only != "annual":
        links = pdf_links(page_html(MONTHLY_PAGE))
        for label, kind in MONTHLY_KINDS.items():
            hit = [(t, u) for t, u in links if t.startswith(label)]
            if len(hit) != 1:   # 月報欄には今月分の1件だけがあるはず。複数あれば止めて人が選ぶ
                raise SystemExit(f"{label}: 月報のリンクが {len(hit)} 件: {hit}")
            m = re.search(r"（(令和\d+年\d+月)", hit[0][0])
            if not m:
                raise SystemExit(f"月が読めない: {hit[0][0]}")
            ym = common.to_fiscal_year(m.group(1))
            mon = re.search(r"年(\d+)月", m.group(1)).group(1)
            save(hit[0][1], f"habu_{kind}_{ym}{int(mon):02d}.pdf")


if __name__ == "__main__":
    main()
