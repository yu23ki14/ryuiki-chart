"""神奈川県・相模原市・BODIK(神奈川) の CKAN からデータセット目録を収穫"""
import sys, json, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *

INSTANCES = [
    ("kanagawa_pref", "神奈川県オープンデータカタログ", "神奈川県",
     "https://catalog.opendata.pref.kanagawa.jp", None),
    ("sagamihara",    "相模原市オープンデータカタログ", "相模原市",
     "https://opendata.city.sagamihara.kanagawa.jp", None),
    ("bodik_kanagawa","BODIK オープンデータカタログ 神奈川", "BODIK",
     "https://odcs.bodik.jp/kanagawa", None),
]

def harvest(base):
    out, start, rows = [], 0, 1000
    while True:
        j = get_json(f"{base}/api/3/action/package_search",
                     params={"rows": rows, "start": start})
        res = j["result"]; out += res["results"]
        start += rows
        if start >= res["count"] or not res["results"]: break
    return out

all_rows, all_res = [], []
for sid, name, pub, base, _ in INSTANCES:
    try:
        pkgs = harvest(base)
    except Exception as e:
        print(f"  [skip] {sid}: {e}"); continue
    for p in pkgs:
        ds = {
            "instance": sid, "dataset_id": p.get("id"), "name": p.get("name"),
            "title": p.get("title"), "notes": (p.get("notes") or "")[:800],
            "organization": (p.get("organization") or {}).get("title"),
            "license": p.get("license_title") or p.get("license_id"),
            "license_url": p.get("license_url"),
            "groups": "|".join(g.get("title","") for g in p.get("groups") or []),
            "tags": "|".join(t.get("display_name","") for t in p.get("tags") or []),
            "n_resources": len(p.get("resources") or []),
            "metadata_modified": p.get("metadata_modified"),
            "url": f"{base}/dataset/{p.get('name')}",
        }
        all_rows.append(ds)
        for r in p.get("resources") or []:
            all_res.append({
                "instance": sid, "dataset_id": p.get("id"), "dataset_title": p.get("title"),
                "resource_id": r.get("id"), "resource_name": r.get("name"),
                "format": (r.get("format") or "").upper(), "url": r.get("url"),
                "size": r.get("size"), "last_modified": r.get("last_modified"),
                "license": p.get("license_title") or p.get("license_id"),
                "organization": (p.get("organization") or {}).get("title"),
                "groups": "|".join(g.get("title","") for g in p.get("groups") or []),
            })
    print(f"  {sid}: {len(pkgs)} datasets")
    register(f"ckan_{sid}", name, pub, base, "オープンデータ目録", "CKAN API",
             "JSON", "各データセット個別（多くは CC BY 4.0 / 政府標準利用規約）",
             True, len(pkgs), "package_search 全件収穫")

write_jsonl("ckan_datasets", all_rows)
write_jsonl("ckan_resources", all_res)
import pandas as pd
pd.DataFrame(all_rows).to_csv(PROC/"ckan_datasets.csv", index=False)
pd.DataFrame(all_res).to_csv(PROC/"ckan_resources.csv", index=False)
print(f"\nTOTAL datasets={len(all_rows)} resources={len(all_res)}")
print("\n-- format breakdown --")
print(pd.DataFrame(all_res)["format"].value_counts().head(15).to_string())
