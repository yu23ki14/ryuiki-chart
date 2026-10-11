"""2010年奄美豪雨の資料（京大防災研の速報・鹿大の報告書）を data/raw/amami_rain2010/ に保存する（取得だけ。cells は作らない）。

設計: docs/plans/AMAMI_STEP3B.md §1・§7。c102b_rain2010_cells.py が cells にする（c102b は FILES の sha256 と手元の PDF を突き合わせる）。

- 原本は再配布しない（data/raw は gitignore 済み）。使うものだけ取る。
- 保存済みで sha256 が同じなら取り直さない。違えば止める（資料が更新された。正解 csv を作り直す前に人が確認する）。
- 気象庁 etrn の突き合わせ用 HTML（jma_check/）は設計時に1回だけ取って保存済み。ここでは取り直さない。
- User-Agent に個人名を入れない・取得の間隔は common.get が空ける。

使い方: python3 scripts/c102a_rain2010_fetch.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells

OUT = common.RAW / "amami_rain2010"

# 保存名 -> (URL, 期待する sha256)
FILES = {
    "20110221.pdf": ("https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf",
                     "368608fc1b331590348408bff7db33f204f8d4d90d92d24d460d195003a7c120"),
    "2010_gouu.pdf": ("https://bousai.kagoshima-u.ac.jp/wpo/wp-content/uploads/2024/03/2010_gouu.pdf",
                      "22f51a5f7c7d779df9ffec9f86aebab0df1d46d549318480e92ba3520e40141e"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (url, want) in FILES.items():
        dest = OUT / name
        how = doccells.fetch_verified(url, dest, want)
        print(f"  [{how}] {dest.relative_to(common.ROOT)}  sha256={want[:12]}  <- {url}")


if __name__ == "__main__":
    main()
