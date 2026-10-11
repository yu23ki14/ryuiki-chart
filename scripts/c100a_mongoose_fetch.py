"""奄美大島のマングース防除の資料を data/raw/moe_mongoose/ に保存する（取得だけ。cells は作らない）。

設計: docs/plans/AMAMI_STEP3A.md §1。

- 取る表: 令和4年度のお知らせ（press_00065）の表1（PNG、2000〜2022年度）。c100_mongoose_ocr_run.py が OCR にかけ、
  c100b_mongoose_cells.py が cells にする。
- お知らせの HTML（わな日・CPUE の定義の注記を含む）と、根絶宣言の報道発表ページ（c101 が documents に載せる）。
- 原本は再配布しない（data/raw は gitignore 済み）。sha256 は documents.doc_sha256 に入る。
- 既に保存済みで sha256 が同じなら取り直さない（EXPECTED_SHA256 のあるものは、違えば止める）。
- User-Agent に個人名を入れない（common.py）。呼び出しの間は 5 秒以上空ける。

使い方: python3 scripts/c100a_mongoose_fetch.py
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common

BASE = "https://kyushu.env.go.jp/okinawa"
OUT = common.RAW / "moe_mongoose"
SLEEP = 5.0

# 保存名 -> (URL, 期待する sha256 または None〔HTML はページの更新で変わるので固定しない〕)
FILES = {
    "r4_hyo1_000157229.png": (f"{BASE}/content/000157229.png",
                              "8fd8a498cd1316ce2fc258e75b2ae2723ffbf38b417de9bc75aaadc46b40880d"),
    "press_00065_r4.html": (f"{BASE}/press_00065.html", None),
    "press_00099_declaration.html": (f"{BASE}/press_00099.html", None),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    first = True
    for name, (url, want) in FILES.items():
        dest = OUT / name
        if dest.exists() and (want is None or common.sha256(dest) == want):
            print(f"  [skip] {dest.relative_to(common.ROOT)}  sha256={common.sha256(dest)[:12]}")
            continue
        if not first:
            time.sleep(SLEEP)
        first = False
        r = common.get(url)
        tmp = dest.with_name(dest.name + ".part")   # 検査してから置き換える（不一致で既存の良いコピーを壊さない）
        tmp.write_bytes(r.content)
        sha = common.sha256(tmp)
        if want and sha != want:
            tmp.unlink()
            raise SystemExit(f"{name}: sha256 が期待と違う（{sha}）。表が更新された？ OCR・正解 csv を作り直す前に人が確認する")
        tmp.replace(dest)
        print(f"  [save] {dest.relative_to(common.ROOT)}  {len(r.content)} bytes  sha256={sha[:12]}  <- {url}")


if __name__ == "__main__":
    main()
