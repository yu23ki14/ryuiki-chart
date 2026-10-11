"""2010年奄美豪雨の資料（京大防災研の速報・鹿大の報告書）を data/raw/amami_rain2010/ に保存する（取得だけ。cells は作らない）。

設計: docs/plans/AMAMI_STEP3B.md §1・§7。c102b_rain2010_cells.py が cells にする。

- 原本は再配布しない（data/raw は gitignore 済み）。sha256 は documents.doc_sha256 に入る。
- 保存済みで sha256 が同じなら取り直さない。違えば止める（資料が更新された。正解 csv を作り直す前に人が確認する）。
- 気象庁 etrn の突き合わせ用 HTML（jma_check/）は設計時に1回だけ取って保存済み。ここでは取り直さない。
- User-Agent に個人名を入れない（common.py）。呼び出しの間は 5 秒以上空ける。

使い方: python3 scripts/c102a_rain2010_fetch.py
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common

OUT = common.RAW / "amami_rain2010"
SLEEP = 5.0

# 保存名 -> (URL, 期待する sha256)
FILES = {
    "20110221.pdf": ("https://www.dpri.kyoto-u.ac.jp/web_j/contents/event_text/20110221.pdf",
                     "368608fc1b331590348408bff7db33f204f8d4d90d92d24d460d195003a7c120"),
    "2010_gouu.pdf": ("https://bousai.kagoshima-u.ac.jp/wpo/wp-content/uploads/2024/03/2010_gouu.pdf",
                      "22f51a5f7c7d779df9ffec9f86aebab0df1d46d549318480e92ba3520e40141e"),
    "2010Amami_contents.pdf": ("https://ir.kagoshima-u.ac.jp/record/11004/files/2010Amami_contents.pdf",
                               "7fbde73ac58b2dc89bd633d6e2e4edc720d9e398cab305bd8953a8be667c52db"),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    first = True
    for name, (url, want) in FILES.items():
        dest = OUT / name
        if dest.exists() and common.sha256(dest) == want:
            print(f"  [skip] {dest.relative_to(common.ROOT)}  sha256={want[:12]}")
            continue
        if not first:
            time.sleep(SLEEP)
        first = False
        r = common.get(url)
        tmp = dest.with_name(dest.name + ".part")   # 検査してから置き換える
        tmp.write_bytes(r.content)
        sha = common.sha256(tmp)
        if sha != want:
            tmp.unlink()
            raise SystemExit(f"{name}: sha256 が期待と違う（{sha}）。資料が更新された？ 正解 csv を作り直す前に人が確認する")
        tmp.replace(dest)
        print(f"  [save] {dest.relative_to(common.ROOT)}  {len(r.content)} bytes  sha256={sha[:12]}  <- {url}")


if __name__ == "__main__":
    main()
