"""奄美の水道統計（令和5年度、上水道・簡易水道）とダム容量（流域治水の10頁版）の PDF を data/raw/ に保存する（取得だけ。cells は作らない）。

設計: docs/plans/AMAMI_STEP3C.md §3.1・§4.1。c104b_amami_water_dam_cells.py が cells にする（c104b は FILES の sha256 と手元の PDF を突き合わせる）。

- 原本は再配布しない（data/raw は gitignore 済み）。使うものだけ取る。
- 保存済みで sha256 が同じなら取り直さない。違えば止める（資料が更新された。正解 csv を作り直す前に人が確認する）。
- User-Agent に個人名を入れない・取得の間隔は common.get が空ける。

使い方: python3 scripts/c104a_amami_water_dam_fetch.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
import doccells

SUIDO_DIR = common.RAW / "kagoshima_suido"
DAM_DIR = common.RAW / "kagoshima_dam_cap"
_SUIDO = "https://www.pref.kagoshima.jp/ae09/suidou/suidoutoukei/documents/"
_DAM = "https://www.pref.kagoshima.jp/aq09/documents/"

# 保存名 -> (保存先ディレクトリ, URL, 期待する sha256)
FILES = {
    "121966_20250627104846-1.pdf": (SUIDO_DIR, _SUIDO + "121966_20250627104846-1.pdf",
                                    "0df62e48bc107929ec2e15b44843d1ad71f0525f18bfb37480db6af770d1abee"),
    "121966_20250627105147-1.pdf": (SUIDO_DIR, _SUIDO + "121966_20250627105147-1.pdf",
                                    "2ca69e4023ebb08dd34541c3517e3c59ac9ebafa3f5f32072a7611d570dcab0c"),
    "88914_20230208131603-1.pdf": (DAM_DIR, _DAM + "88914_20230208131603-1.pdf",
                                   "cba99583e097182a64dce9aa0877944565256beb2e89a042c582e03e2a79a744"),
}


def main():
    for name, (d, url, want) in FILES.items():
        d.mkdir(parents=True, exist_ok=True)
        dest = d / name
        how = doccells.fetch_verified(url, dest, want)
        print(f"  [{how}] {dest.relative_to(common.ROOT)}  sha256={want[:12]}  <- {url}")


if __name__ == "__main__":
    main()
