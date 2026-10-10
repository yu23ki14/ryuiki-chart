"""奄美 Step 1 PR-B の計測（docs/plans/AMAMI_STEP1B.md §4）。原本は読み取り専用で開く。
出力は reports/add_area_kagoshima.md の「Step 1 PR-B 取り込みと計測」節に貼る表の元。
実行: .venv/bin/python3 scripts/measure_amami_step1b.py"""
import collections
import csv
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from migrate import point_in_polygon as pip  # noqa: E402

PROC = ROOT / "data" / "processed"
SRCS = ("gbif_amami_occurrences", "inaturalist_amami")


def main():
    polys = pip.load_polygons(PROC / "nlni_w12_watersheds_amami.geojson")
    grid = pip.build_grid(polys)
    land = pip.load_polygons(PROC / "nlni_l03b_landuse_2016_amami.geojson", id_property="landuse_code_raw")
    land_grid = pip.build_grid(land)

    # 丸め・秘匿の印（原本の列に無いので出典ファイルから引く）
    rounded = set()
    for line in open(PROC / "inaturalist_amami.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d.get("obscured") or d.get("geoprivacy"):
            rounded.add(f"inaturalist_amami__{d['id']}")
    for r in csv.DictReader(open(PROC / "gbif_amami_occurrences.csv", encoding="utf-8")):
        if "COORDINATE_ROUNDED" in (r.get("issues") or ""):
            rounded.add(f"gbif_amami_occurrences__{r['key']}")

    db = sqlite3.connect(f"file:{ROOT / 'data/db/ryuiki.sqlite'}?mode=ro", uri=True)
    cache, lcache = {}, {}
    tally = collections.Counter()
    for rid, sid, lat, lon, day in db.execute(
        "SELECT record_id, source_id, lat, lon, observed_on FROM organism_records WHERE source_id IN (?,?)", SRCS):
        has_day = "日付あり" if day else "日付なし"
        rnd = "丸め/秘匿" if rid in rounded else "通常"
        if lat is None or lon is None:
            cls = "座標なし"
        else:
            k = (lon, lat)
            if k not in cache:
                cache[k] = len(pip.locate(lon, lat, polys, grid)[0])
            n = cache[k]
            if n == 1:
                cls = "1面に解決"
            elif n > 1:
                cls = "複数面"
            else:
                if k not in lcache:
                    lcache[k] = bool(pip.locate(lon, lat, land, land_grid)[0])
                cls = "0面・陸セル内" if lcache[k] else "0面・陸セル外(海ほか)"
        tally[(sid, cls, has_day, rnd)] += 1
    print("## organism W12")
    for k, v in sorted(tally.items()):
        print(*k, v, sep="\t")

    print("## sites")
    for sid, n, w in db.execute(
        "SELECT source_id, count(*), sum(watershed IS NOT NULL) FROM sites WHERE source_id LIKE '%amami' GROUP BY 1"):
        print(sid, n, w, sep="\t")

    print("## taxon")
    known = set()
    for r in csv.DictReader(open(PROC / "taxon_gbif_accepted.csv", encoding="utf-8")):
        known.update(k for k in (r["gbif_key"], r["accepted_key"]) if k)
    cnt, dis = collections.Counter(), collections.defaultdict(set)
    tot = collections.Counter()
    for sid, tk in db.execute("SELECT source_id, taxon_key FROM organism_records WHERE source_id IN (?,?)", SRCS):
        tot[sid] += 1
        if tk is None or tk == "":
            cnt[(sid, "taxon_key なし")] += 1
        elif str(tk) not in known:
            cnt[(sid, "未名寄せ")] += 1
            dis[sid].add(tk)
    for sid in SRCS:
        print(sid, "records", tot[sid], "no_key", cnt[(sid, "taxon_key なし")],
              "unmatched_records", cnt[(sid, "未名寄せ")], "unmatched_distinct", len(dis[sid]), sep="\t")


if __name__ == "__main__":
    main()
