"""GBIF Backbone による学名照合（taxon_crosswalk）

入力: data/processed/{kanagawa_redlist, moe_ias_list, moe_redlist}.csv の学名
出力: data/processed/taxon_crosswalk.{csv,jsonl}

- common.get が 1.5 秒/ホストでスロットルされるため、照合対象は上位 N 件（既定 1000）に絞る。
  絞り込みは (source_id, taxon_group) のラウンドロビンで、分類群の偏りが出ないようにする。
- matchType が NONE / FUZZY / HIGHERRANK でもそのまま残す。勝手に確定させない。
- 1回目（原文の学名そのまま）が NONE の場合のみ、著者名・年を落とした canonical 名で1回だけ再照合し、
  どちらのクエリで当たったかを query_variant に残す。
"""
import sys, pathlib, re, csv, json, os
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get_json, register, write_jsonl, PROC

LIMIT = int(os.environ.get("GBIF_LIMIT", "1000"))
# GBIF_SOURCES で対象ソースを絞れる（既定は3ソースすべて）。
# 既に taxon_crosswalk.csv にある taxon_id は再照合せず追記する（インクリメンタル）。
_ALL = {"kanagawa_redlist": "taxon_group_ja",
        "moe_ias_list": "taxon_group_ja",
        "moe_redlist": "taxon_group_list_ja"}
_want = os.environ.get("GBIF_SOURCES", "kanagawa_redlist,moe_ias_list,moe_redlist").split(",")
SOURCES = [(s_, _ALL[s_]) for s_ in _want if s_ in _ALL]

def norm_id(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

STOP = {"spp.", "sp.", "cf.", "aff.", "spp", "sp"}
def canonical(name):
    """著者名・年を落とした種階級までの名前（推測はせず、機械的なトークン規則のみ）"""
    toks = re.sub(r"\s+", " ", name).strip().split(" ")
    if not toks: return None
    out = [toks[0]]
    for t in toks[1:]:
        tl = t.strip(",")
        if tl.lower() in STOP: break
        if re.fullmatch(r"[a-z][a-z\-]+", tl): out.append(tl)
        else: break
    return " ".join(out) if len(out) >= 2 else None

# ---- 候補の収集 ----
buckets = {}
order = []
for sid, grpcol in SOURCES:
    p = PROC/f"{sid}.csv"
    if not p.exists(): continue
    for r in csv.DictReader(open(p, encoding="utf-8")):
        sci = (r.get("scientific_name") or "").strip()
        if not sci: continue
        key = (sid, (r.get(grpcol) or "").strip() or "(不明)")
        buckets.setdefault(key, [])
        if key not in order: order.append(key)
        buckets[key].append((norm_id(sci), sci, r.get("vernacular_name_ja")))

# (source_id, taxon_group) ごとにカーソルを持ち、1件ずつ順に取り出す（ラウンドロビン）
seen, queue = set(), []
cur = {k: 0 for k in order}
while True:
    progressed = False
    for key in order:
        lst = buckets[key]
        while cur[key] < len(lst):
            tid, sci, wam = lst[cur[key]]; cur[key] += 1
            if tid in seen: continue
            seen.add(tid); queue.append((tid, sci, wam, key[0])); progressed = True
            break
    if not progressed: break

# 既存の照合結果（あれば）を読み、未照合ぶんだけを対象にする
prev, PREVP = [], PROC/"taxon_crosswalk.csv"
if PREVP.exists():
    prev = list(csv.DictReader(open(PREVP, encoding="utf-8")))
done_ids = {r["taxon_id"] for r in prev}
total_distinct = len(queue)
queue = [q for q in queue if q[0] not in done_ids]
target = queue[:LIMIT]
print(f"  [crosswalk] already matched = {len(prev)}")
print(f"  [crosswalk] distinct scientific names = {total_distinct}, matching {len(target)}")

FIELDS = ["taxon_id", "scientific_name", "vernacular_name_ja", "source_id",
          "query_name", "query_variant", "taxon_key", "accepted_scientific_name",
          "kingdom", "phylum", "class", "order", "family", "genus",
          "rank", "matchType", "confidence", "status", "note"]

rows = list(prev)
for n, (tid, sci, wam, sid) in enumerate(target, 1):
    variant, j = "verbatim", None
    try:
        j = get_json("https://api.gbif.org/v1/species/match", params={"name": sci})
    except Exception as e:
        rows.append({"taxon_id": tid, "scientific_name": sci, "vernacular_name_ja": wam,
                     "source_id": sid, "query_name": sci, "query_variant": variant,
                     "matchType": None, "note": f"request failed: {e!r}"})
        continue
    if j.get("matchType") == "NONE":
        can = canonical(sci)
        if can and can != sci:
            try:
                j2 = get_json("https://api.gbif.org/v1/species/match", params={"name": can})
                if j2.get("matchType") != "NONE":
                    j, variant, sci_q = j2, "canonical", can
            except Exception:
                pass
    q = sci if variant == "verbatim" else canonical(sci)
    rows.append({
        "taxon_id": tid, "scientific_name": sci, "vernacular_name_ja": wam, "source_id": sid,
        "query_name": q, "query_variant": variant,
        "taxon_key": j.get("usageKey"), "accepted_scientific_name": j.get("scientificName"),
        "kingdom": j.get("kingdom"), "phylum": j.get("phylum"), "class": j.get("class"),
        "order": j.get("order"), "family": j.get("family"), "genus": j.get("genus"),
        "rank": j.get("rank"), "matchType": j.get("matchType"),
        "confidence": j.get("confidence"), "status": j.get("status"),
        "note": j.get("note"),
    })
    if n % 100 == 0: print(f"    ...{n}/{len(target)}")

with open(PROC/"taxon_crosswalk.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader()
    for r in rows: w.writerow({c: r.get(c) for c in FIELDS})
print(f"  [write] data/processed/taxon_crosswalk.csv  {len(rows)} rows")
write_jsonl("taxon_crosswalk", [{c: r.get(c) for c in FIELDS} for r in rows])

import collections
mt = collections.Counter(r.get("matchType") for r in rows)
print("  [matchType]", dict(mt))

register("gbif_species_match", "GBIF Backbone Taxonomy 学名照合（species/match API）",
         "Global Biodiversity Information Facility (GBIF)",
         "https://api.gbif.org/v1/species/match", "分類・名寄せ語彙", "REST API", "JSON",
         "GBIF Backbone Taxonomy は CC BY 4.0（https://doi.org/10.15468/39omei）", 1, len(rows),
         f"kanagawa_redlist / moe_ias_list / moe_redlist の学名 8364 件（distinct）のうち "
         f"レート制限（1.5秒/リクエスト）配慮のため {len(rows)} 件に絞って照合した"
         f"（(source_id, taxon_group) のラウンドロビンで抽出。神奈川県RLは全件、"
         f"環境省RL・外来種リストは一部）。matchType 内訳: {dict(mt)}。"
         "matchType が NONE/FUZZY/HIGHERRANK のものも値をそのまま保持している。")
print("done.")
