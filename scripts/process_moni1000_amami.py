"""モニタリングサイト1000: 奄美（region jp-46）の 2 出典を、手元の展開済みファイルから抽出する。

- moni1000_forest_bird_amami      SIN04 の BirdData*.csv から、都道府県＝鹿児島県で市町村が奄美市・大島郡宇検村の行
                                  （サイト 200029・100474）。
- moni1000_coast_shorebird_amami  SIG02 の「一斉調査日個体数リスト表」から、地点 460800（奄美大島大瀬海岸）。
                                  神奈川の moni1000_coast_shorebird と同じファイル・同じ列の対応。

追認済み（2026-10-12、オーナー確認）。**新たな取得（フォーム送信・ダウンロード）はしない**。入力は
data/raw/moni1000/extracted/（全国分の既取得 ZIP を展開したもの）だけ。ネットワークには出ない。
列の対応は process_moni1000_forest_coast.py の SIN04_COLMAP / SIG02_COLMAP を共有する。
docs/plans/MONI1000.md「奄美の追加」。
"""
import sys, glob
sys.path.insert(0, "scripts")
import pandas as pd
from common import PROC, register, write_jsonl
from process_moni1000_forest_coast import EXT, SIN04_COLMAP, SIG02_COLMAP, read_any

AMAMI_MUNICIPALITIES = ("奄美市", "大島郡宇検村")
COAST_SITE_CODE = "460800"
NOTE_COMMON = ("追認済み（2026-10-12、オーナー確認）。新規取得はしない。全国分の既取得 ZIP を展開した "
               "data/raw/moni1000/extracted/ から奄美分を抽出。")


def extract_sin04():
    frames = []
    for f in sorted(glob.glob(str(EXT / "SIN04/BirdData*.csv"))):
        df = read_any(f)
        m = (df["都道府県"].astype(str).str.contains("鹿児島", na=False)
             & df["市町村"].astype(str).str.strip().isin(AMAMI_MUNICIPALITIES))
        if m.any():
            frames.append(df[m])
    out = pd.concat(frames, ignore_index=True).rename(columns=SIN04_COLMAP)
    out["source_id"] = "moni1000_forest_bird_amami"
    out["source_ref"] = "https://www.biodic.go.jp/moni1000/question/question.html (SIN04)"
    return out


def extract_sig02():
    df = read_any(EXT / "SIG02/一斉調査日個体数リスト表(2004-05以降).csv")
    out = df[df["Site Code"].astype(str).str.strip() == COAST_SITE_CODE].rename(columns=SIG02_COLMAP).copy()
    out["source_id"] = "moni1000_coast_shorebird_amami"
    out["source_ref"] = "https://www.biodic.go.jp/moni1000/question/question.html (SIG02)"
    return out


def process_forest_bird():
    df = extract_sin04()
    df.to_csv(PROC / "moni1000_forest_bird_amami.csv", index=False, encoding="utf-8")
    write_jsonl("moni1000_forest_bird_amami", df.to_dict(orient="records"))
    sites = ",".join(sorted(df["site_id"].astype(str).unique()))
    register(
        source_id="moni1000_forest_bird_amami",
        name="モニタリングサイト1000 森林・草原調査 陸生鳥類調査（奄美のサイトのみ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/moni1000/forest.html",
        category="生態系モニタリング(森林・草原)",
        access_method="既取得の全国分zip(SIN04)を展開した年度別CSVを、都道府県=鹿児島県かつ市町村=奄美市・大島郡宇検村で抽出",
        fmt="CSV(UTF-8-sig/Shift_JIS混在)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
        redistributable=1,
        record_count=len(df),
        notes=NOTE_COMMON + f"サイトID {sites}（200029=奄美市、100474=大島郡宇検村）。年度別ファイル(繁殖期B/越冬期W)を結合。",
    )


def process_coast_shorebird():
    df = extract_sig02()
    df.to_csv(PROC / "moni1000_coast_shorebird_amami.csv", index=False, encoding="utf-8")
    write_jsonl("moni1000_coast_shorebird_amami", df.to_dict(orient="records"))
    register(
        source_id="moni1000_coast_shorebird_amami",
        name="モニタリングサイト1000 沿岸域(シギ・チドリ類)調査（奄美のサイトのみ抽出）",
        publisher="環境省生物多様性センター",
        url="https://www.biodic.go.jp/moni1000/coast.html",
        category="生態系モニタリング(沿岸域)",
        access_method="既取得の全国分zip(SIG02)を展開した一斉調査日個体数リスト表から、地点コード460800(奄美大島大瀬海岸)を抽出",
        fmt="CSV(Shift_JIS)->CSV/JSONL(UTF-8)",
        license_="生物多様性センターウェブサイト利用規約(要事前アンケート回答)",
        redistributable=1,
        record_count=len(df),
        notes=NOTE_COMMON + "神奈川の moni1000_coast_shorebird と同じ「一斉調査日個体数リスト表」を使う。",
    )


if __name__ == "__main__":
    process_forest_bird()
    process_coast_shorebird()
