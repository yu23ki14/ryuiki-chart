"""data/db/ryuiki.sqlite の taxa テーブルを構築（神奈川RL / 環境省RL / 外来種リストの統合）

taxon_id = 学名の正規化文字列（小文字・空白1つ）。
学名が無く和名しか無いレコードも捨てない（scientific_name=NULL, taxon_id='wamei:<和名>'）。
GBIF の分類階層は taxon_crosswalk.csv がある場合のみ付与し、matchType をそのまま残す。
"""
import sys, pathlib, re, csv
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import appdb, PROC

DDL = """
CREATE TABLE IF NOT EXISTS taxa (
  taxon_id TEXT PRIMARY KEY, scientific_name TEXT, vernacular_name_ja TEXT,
  taxon_group_ja TEXT, kingdom TEXT, phylum TEXT, class TEXT, "order" TEXT,
  family TEXT, genus TEXT, gbif_taxon_key TEXT, gbif_match_type TEXT,
  redlist_kanagawa TEXT, redlist_national TEXT, ias_category TEXT,
  source_id TEXT, source_ref TEXT
);
"""

def norm_id(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def rd(name):
    p = PROC/f"{name}.csv"
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []

kan = rd("kanagawa_redlist")
nat = rd("moe_redlist")
ias = rd("moe_ias_list")
xw = {r["taxon_id"]: r for r in rd("taxon_crosswalk")}
print(f"  in: kanagawa={len(kan)} national={len(nat)} ias={len(ias)} crosswalk={len(xw)}")

taxa = {}

def touch(sci, wam, group, sid, ref):
    sci = (sci or "").strip() or None
    wam = (wam or "").strip() or None
    tid = norm_id(sci) if sci else ("wamei:" + norm_id(wam) if wam else None)
    if not tid: return None
    t = taxa.setdefault(tid, {
        "taxon_id": tid, "scientific_name": sci, "vernacular_name_ja": wam,
        "taxon_group_ja": group or None,
        "redlist_kanagawa": None, "_kan_year": -1,
        "redlist_national": None, "_nat_year": -1,
        "ias_category": None, "source_id": [], "source_ref": [],
    })
    if not t["vernacular_name_ja"]: t["vernacular_name_ja"] = wam
    if not t["taxon_group_ja"]: t["taxon_group_ja"] = group or None
    if sid not in t["source_id"]: t["source_id"].append(sid)
    if len(t["source_ref"]) < 3 and ref: t["source_ref"].append(ref)
    return t

for r in kan:
    t = touch(r["scientific_name"], r["vernacular_name_ja"], r["taxon_group_ja"],
              r["source_id"], r["source_ref"])
    if t is None: continue
    y = int(r["list_year"] or 0)
    if y >= t["_kan_year"]:
        code = (r.get("category_code") or "").strip()
        t["redlist_kanagawa"] = f"{r['category_ja']}（{code}）" if code else r["category_ja"]
        t["_kan_year"] = y

for r in nat:
    t = touch(r["scientific_name"], r["vernacular_name_ja"],
              r.get("taxon_group_list_ja") or r.get("taxon_group_ja"),
              r["source_id"], r["source_ref"])
    if t is None: continue
    y = int(r["list_year"] or 0)
    if y >= t["_nat_year"]:
        code = (r.get("category_code") or "").strip()
        t["redlist_national"] = f"{r['category_ja']}（{code}）" if code else r["category_ja"]
        t["_nat_year"] = y

for r in ias:
    t = touch(r["scientific_name"], r["vernacular_name_ja"], r["taxon_group_ja"],
              r["source_id"], r["source_ref"])
    if t is None: continue
    t["ias_category"] = r["category_ja"]

rows = []
n_gbif = 0
for tid, t in taxa.items():
    g = xw.get(tid)
    if g and (g.get("matchType") or "") not in ("", None): n_gbif += 1
    rows.append((
        tid, t["scientific_name"], t["vernacular_name_ja"], t["taxon_group_ja"],
        (g or {}).get("kingdom") or None, (g or {}).get("phylum") or None,
        (g or {}).get("class") or None, (g or {}).get("order") or None,
        (g or {}).get("family") or None, (g or {}).get("genus") or None,
        (g or {}).get("taxon_key") or None, (g or {}).get("matchType") or None,
        t["redlist_kanagawa"], t["redlist_national"], t["ias_category"],
        "|".join(t["source_id"]), "|".join(t["source_ref"]),
    ))

c = appdb()
c.executescript(DDL)
c.execute("DELETE FROM taxa")
c.executemany("INSERT OR REPLACE INTO taxa VALUES (" + ",".join(["?"]*17) + ")", rows)
c.commit()
n = c.execute("SELECT COUNT(*) FROM taxa").fetchone()[0]
print(f"  [db] taxa rows = {n} (GBIF付与 {n_gbif} 件)")
for q, lbl in [("SELECT COUNT(*) FROM taxa WHERE redlist_kanagawa IS NOT NULL", "神奈川RLあり"),
               ("SELECT COUNT(*) FROM taxa WHERE redlist_national IS NOT NULL", "環境省RLあり"),
               ("SELECT COUNT(*) FROM taxa WHERE ias_category IS NOT NULL", "外来種リストあり"),
               ("SELECT COUNT(*) FROM taxa WHERE scientific_name IS NULL", "学名なし")]:
    print(f"    {lbl}: {c.execute(q).fetchone()[0]}")
print("    gbif_match_type:",
      dict(c.execute("SELECT COALESCE(gbif_match_type,'(未照合)'),COUNT(*) FROM taxa GROUP BY 1").fetchall()))
c.close()
print("done.")
