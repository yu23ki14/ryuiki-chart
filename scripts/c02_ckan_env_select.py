"""CKAN目録から環境・生物多様性・水・気象・森林・土地利用・災害系リソースを選別"""
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd

KEYWORDS = [
 "環境","水質","大気","河川","水源","森林","林業","緑地","公園","自然","生物","動物",
 "鳥獣","外来","農地","土地利用","気象","降水","降雨","温暖化","温室効果ガス","排出",
 "地盤","地下水","湧水","海岸","漂着","廃棄物","ごみ","リサイクル","農業","漁業","水産",
 "ダム","貯水","災害","浸水","ハザード","土砂","治水","下水","上水","水道","雨水",
 "植物","昆虫","魚","野鳥","希少","絶滅","保全","生態","流域","湖","沼","海","干潟",
 "騒音","振動","悪臭","ダイオキシン","放射線","放射能","PM2.5","光化学","公害",
 "みどり","樹木","樹林","里山","畜産","作物","収穫","栽培","漁獲","雪","気温","風",
 "土壌","地質","地形","標高","急傾斜","崖","液状化","津波","洪水","内水","避難",
]
# groups（分野）でも拾う
GROUP_KEYWORDS = ["環境","農林水産","国土・気象","安全"]

NEG = [  # 明らかに無関係だが「環境」等を含みうる語（除外はしない・記録のみ）
]

def hit(text):
    t = str(text or "")
    return [k for k in KEYWORDS if k in t]

def main():
    res = pd.read_csv(PROC/"ckan_resources.csv", dtype=str)
    ds  = pd.read_csv(PROC/"ckan_datasets.csv", dtype=str)
    tagmap = dict(zip(ds["dataset_id"], ds["tags"].fillna("")))
    notemap = dict(zip(ds["dataset_id"], ds["title"].fillna("")))
    res["tags"] = res["dataset_id"].map(tagmap).fillna("")

    rows = []
    for _, r in res.iterrows():
        blob = " ".join([str(r.get("dataset_title") or ""), str(r.get("resource_name") or ""),
                         str(r.get("tags") or "")])
        kws = hit(blob)
        grp = str(r.get("groups") or "")
        gkws = [g for g in GROUP_KEYWORDS if g in grp]
        if not kws and not gkws:
            continue
        rows.append({
            "instance": r["instance"],
            "dataset_id": r["dataset_id"],
            "dataset_title": r["dataset_title"],
            "resource_id": r["resource_id"],
            "resource_name": r["resource_name"],
            "format": r["format"],
            "url": r["url"],
            "license": r["license"],
            "organization": r.get("organization"),
            "groups": grp,
            "tags": r["tags"],
            "size": r.get("size"),
            "matched_keywords": "|".join(sorted(set(kws))),
            "matched_groups": "|".join(gkws),
        })
    sel = pd.DataFrame(rows)
    out = PROC/"ckan_env_selection.csv"
    sel[["dataset_title","resource_name","format","url","license",
         "instance","dataset_id","resource_id","organization","groups","tags",
         "size","matched_keywords","matched_groups"]].to_csv(out, index=False)
    print(f"selected={len(sel)}  -> {out}")
    print(sel["format"].value_counts().to_string())
    print("\n-- instance --"); print(sel["instance"].value_counts().to_string())
    print("\n-- license --"); print(sel["license"].value_counts().to_string())

main()
