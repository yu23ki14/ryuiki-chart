"""気象庁「日本沿岸域の海面水温情報」の海域別・日別の海域平均海面水温（1982年〜前日）。

- データ: https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan/txt/area<海域番号>.txt
  （`yyyy,mm,dd,areaNo.,flag,Temp.` の CSV）。海域番号は regions.py の `jma_sst_areas`（空なら何もしない）。
- 海域名は一覧ページ engan_KG.html（九州南部・奄美沿岸域）の表記。
- flag: 'R' / 'P' が現れる。海域ページ(engan<番号>.html)に「直近の値は速報値。後日、再解析値に更新される」とあり、
  末尾に P が連なることから P=速報値・R=再解析値と読めるが、フラグの定義そのものは明記されていないので
  value_raw と同じく quality_flag にそのまま保持し、解釈は notes に書くだけにする。
- 平年差の列は txt に無い（平年値は別ファイル「平年値、過去5年統計値」）。この出力には含めない。
出力: data/processed/jma_sst_<slug>.{csv,jsonl}（縦持ち long。1海域1日=1行）
"""
import sys, csv, argparse, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import regions

BASE = "https://www.data.jma.go.jp/kaiyou/data/db/kaikyo/series/engan"
LICENSE = ("気象庁ホームページ利用規約（政府標準利用規約 2.0 準拠）／公共データ利用規約 第1.0版（PDL1.0）"
           " https://www.jma.go.jp/jma/kishou/info/coment.html")


def parse_area(text, area, sid, url, area_names):
    """area<番号>.txt の本文 -> 縦持ちの行。欠測（空・非数）は出さない。"""
    out = []
    for ln in text.splitlines()[1:]:
        p = [x.strip() for x in ln.split(",")]
        if len(p) < 6 or not p[0].isdigit():
            continue
        v, kind = to_number(p[5])
        if kind not in ("int", "float"):
            continue
        out.append({
            "area_code": area, "area_name_ja": area_names.get(area),
            "datetime": f"{p[0]}-{p[1]}-{p[2]}", "period": "day",
            "variable": "sea_surface_temperature", "variable_ja": "海域平均海面水温",
            "value": float(v), "value_raw": p[5], "unit": "degC",
            "quality_flag": p[4] or None,
            "source_id": sid, "source_ref": url,
        })
    return out


def main():
    ap = argparse.ArgumentParser(); regions.add_region_arg(ap)
    rid = ap.parse_args().region
    cfg = regions.get(rid)
    areas = cfg["jma_sst_areas"]
    if not areas:
        print(f"  {rid}: jma_sst_areas が空（海面水温は範囲外）。何もしない"); return
    sid = regions.name("jma_sst_kanagawa", rid)
    area_names = dict(cfg["jma_sst_area_names"])
    rows = []
    for a in areas:
        url = f"{BASE}/txt/area{a}.txt"
        r = get(url); r.encoding = "utf-8"
        got = parse_area(r.text, a, sid, url, area_names)
        if not got:
            raise SystemExit(f"[abort] 海域{a}（{area_names.get(a)}）: {url} から行が取れない"
                             "（空のファイル、または形式が違う）。海面水温は出さない")
        print(f"  area{a}: {len(got)} rows  {got[0]['datetime']}〜{got[-1]['datetime']}")
        rows += got
    with open(PROC/f"{sid}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    write_jsonl(sid, rows)
    register(sid, f"気象庁 沿岸の海面水温（{cfg['jma_sst_label']} 海域{areas[0]}〜{areas[-1]}）",
             "気象庁", f"{BASE}/engan_KG.html", "海洋", "HTTP GET (CSV)", "CSV/JSONL",
             LICENSE, True, len(rows),
             f"海域={'/'.join(f'{a}:{area_names.get(a)}' for a in areas)} / 日別の海域平均海面水温 "
             f"{rows[0]['datetime']}〜 / quality_flag は原文の R・P（P=速報値・R=再解析値と読めるが定義の明記は無い）。"
             "平年差は txt に無いので含めない。")


if __name__ == "__main__":
    main()
