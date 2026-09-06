"""iNaturalist: 神奈川県(place_id=10918) の観察記録。casual grade 含む市民科学データ"""
import sys, json, time, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent))
import common
from common import *
common.MIN_INTERVAL = 1.1   # iNat は 60 req/min 推奨

B = "https://api.inaturalist.org/v1/observations"
PLACE = 10918

def flat(o):
    t = o.get("taxon") or {}
    anc = {r: None for r in ("kingdom","phylum","class","order","family","genus")}
    for a in (t.get("ancestors") or []):
        if a.get("rank") in anc: anc[a["rank"]] = a.get("name")
    loc = (o.get("location") or ",").split(",")
    return {
      "id": o.get("id"), "uuid": o.get("uuid"),
      "observed_on": o.get("observed_on"), "time_observed_at": o.get("time_observed_at"),
      "created_at": o.get("created_at"),
      "quality_grade": o.get("quality_grade"),
      "scientific_name": t.get("name"), "taxon_id": t.get("id"), "rank": t.get("rank"),
      "vernacular_name_ja": t.get("preferred_common_name"),
      "kingdom": anc["kingdom"], "phylum": anc["phylum"], "class": anc["class"],
      "order": anc["order"], "family": anc["family"], "genus": anc["genus"],
      "threatened": t.get("threatened"), "introduced": t.get("introduced"),
      "endemic": t.get("endemic"), "native": t.get("native"),
      "lat": float(loc[0]) if loc[0] else None,
      "lon": float(loc[1]) if len(loc)>1 and loc[1] else None,
      "positional_accuracy_m": o.get("positional_accuracy"),
      "geoprivacy": o.get("geoprivacy"), "obscured": o.get("obscured"),
      "place_guess": o.get("place_guess"),
      "identifications_count": o.get("identifications_count"),
      "num_identification_agreements": o.get("num_identification_agreements"),
      "num_identification_disagreements": o.get("num_identification_disagreements"),
      "photos_count": len(o.get("photos") or []),
      "license_code": o.get("license_code"),
      "user_login": (o.get("user") or {}).get("login"),
      "captive": o.get("captive"),
      "source_id": "inaturalist_kanagawa",
      "source_ref": f"https://www.inaturalist.org/observations/{o.get('id')}",
    }

# id_above 方式でページング（per_page*page の1万件上限を回避）
out, above, n = PROC/"inaturalist_kanagawa.jsonl", 0, 0
t0 = time.time()
with open(out, "w", encoding="utf-8") as f:
    while True:
        j = get_json(B, params={"place_id": PLACE, "per_page": 200,
                                "order_by": "id", "order": "asc", "id_above": above})
        res = j.get("results", [])
        if not res: break
        for o in res:
            f.write(json.dumps(flat(o), ensure_ascii=False)+"\n"); n += 1
        above = res[-1]["id"]
        if n % 4000 == 0:
            print(f"  {n} obs (id_above={above}, {time.time()-t0:.0f}s)", flush=True)
        if n >= 400000: print("  safety cap"); break
print(f"wrote {n} observations")
register("inaturalist_kanagawa", "iNaturalist 観察記録 — 神奈川県 (place 10918)",
         "iNaturalist", f"https://www.inaturalist.org/observations?place_id={PLACE}",
         "市民科学 生物観察", "REST API v1", "JSONL",
         "観察ごとに個別 (CC0/CC BY/CC BY-NC/全権利留保。license_code列に保持)",
         True, n, "casual+needs_id+research 全grade。obscured/geoprivacy 列あり")
