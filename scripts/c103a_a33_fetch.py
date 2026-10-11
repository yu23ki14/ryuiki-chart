"""鹿児島県「土砂災害警戒区域データ等」（BODIK 460001_kgod016, CC BY 4.0）の最新 ZIP を data/raw/bodik_a33/ に保存する。

設計: docs/plans/AMAMI_STEP3C.md §1.1・§8 担当1。c103b_a33_hazard_zones.py が変換する。

- リソースは時点ごとの別 ZIP が積み上がる。**最新（20260210_shape.zip）** を package_show で引く（URL に UUID が入るため）。
- 保存済みで sha256 が同じなら取り直さない。違えば止める（資料が更新された。c103b の正解 csv を作り直す前に人が確かめる）。
- 展開先 x/ は作業用（data/* は gitignore 済み）。BODIK の呼び出しの間は 5 秒以上空ける（続けると 403）。
- User-Agent に個人名を入れない（common.UA）。

使い方: python3 scripts/c103a_a33_fetch.py
"""
import pathlib
import sys
import time
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common

PKG = "460001_kgod016"
BASE = "https://data.bodik.jp"
SLEEP = 5.0
RAW = common.RAW / "bodik_a33"
ZIP_NAME = "20260210_shape.zip"
ZIP_SHA256 = "aa2227a89a53d794d159371571793a40d3b923792f436409b8006d190f608492"
ZIP_BYTES = 37_223_945


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / ZIP_NAME
    how = "skip"
    if not (dest.exists() and common.sha256(dest) == ZIP_SHA256):
        time.sleep(SLEEP)
        pkg = common.get_json(f"{BASE}/api/3/action/package_show", params={"id": PKG})["result"]
        urls = [r["url"] for r in pkg["resources"] if r["url"].rsplit("/", 1)[-1] == ZIP_NAME]
        if len(urls) != 1:
            raise SystemExit(f"package_show に {ZIP_NAME} が1本だけ無い: {urls}")
        tmp = dest.with_name(dest.name + ".part")
        tmp.unlink(missing_ok=True)
        time.sleep(SLEEP)
        common.download(urls[0], tmp)
        sha = common.sha256(tmp)
        if sha != ZIP_SHA256:
            tmp.unlink()
            raise SystemExit(f"{ZIP_NAME}: sha256 が期待と違う（{sha}）。資料が更新された？ 正解 csv を作り直す前に人が確認する")
        tmp.replace(dest)
        how = "save"
    print(f"  [{how}] {dest.relative_to(common.ROOT)}  sha256={ZIP_SHA256[:12]}  {dest.stat().st_size:,} B")
    out = RAW / "x"
    if not any(out.rglob("*.shp")):
        with zipfile.ZipFile(dest) as z:
            z.extractall(out)
        print(f"  [extract] {out.relative_to(common.ROOT)}")


if __name__ == "__main__":
    main()
