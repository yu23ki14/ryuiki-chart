"""data/water/*.csv を検証して ryuiki.sqlite の water_* テーブルに入れる。

  .venv/bin/python scripts/m06_water.py [--as-of YYYY-MM-DD] [--dry-run]

設計図 docs/WATER_SOURCE_MAP.md の Phase 0 作業3。
CSV が正で、この DB は生成物。冪等（毎回 DELETE してから入れ直す）。

検証に 1 つでもエラーがあれば **何も書かずに終わる**（exit 1）。
「もっともらしい値で埋めない」（§6-3）を守るため、埋まらなかった町丁目は行を作らない。
UI 側はテーブルに行が無いことをもって「不明」と出す。

町丁目（water_zone）は data/processed/estat_shozaiki_kanagawa.csv から入れる。
無ければ scripts/c90_estat_shozaiki.py を先に実行する。
"""
import sys, pathlib, csv, argparse, datetime
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import appdb, PROC, ROOT
import water_lib as w

ZONE_CSV = PROC / "estat_shozaiki_kanagawa.csv"

# CSV の列 → DB の列（名前が違うものだけ）
RENAME = {
    "water_zone": {"jinko": "population", "setai": "households"},
}


def load_zones():
    if not ZONE_CSV.exists():
        print(f"! {ZONE_CSV.relative_to(ROOT)} が無い。"
              f"先に `.venv/bin/python scripts/c90_estat_shozaiki.py` を実行する。")
        return []
    with open(ZONE_CSV, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append({
            "key_code": r["key_code"],
            "muni_code": r["muni_code"],
            "city_name": r["city_name"],
            "s_name": r["s_name"],
            "name": r["name"],
            "parts": int(r["parts"]) if r.get("parts") else 1,
            "population": int(r["jinko"]) if (r.get("jinko") or "").strip() not in ("", "None") else None,
            "households": int(r["setai"]) if (r.get("setai") or "").strip() not in ("", "None") else None,
            "area_km2": float(r["area_km2"]) if r.get("area_km2") else None,
            "centroid_lat": float(r["centroid_lat"]) if r.get("centroid_lat") else None,
            "centroid_lon": float(r["centroid_lon"]) if r.get("centroid_lon") else None,
        })
    return out


def coverage(zones, covered, data):
    """割付の進み具合を、町丁目の数と**人口**の両方で出す。

    設計図の CP2 の完了条件が「県人口の 70% 以上をカバー」なので、
    町丁目の数だけでは判定できない。人口は e-Stat 2020年国勢調査の小地域集計。
    市区町村ごとの内訳も出す（どの事業体が終わっていないかが一目で分かるように）。
    """
    pop = {z["key_code"]: (z["population"] or 0) for z in zones}
    total_n, total_p = len(zones), sum(pop.values())
    cov_n = len(covered)
    cov_p = sum(pop.get(k, 0) for k in covered)
    print(f"  割付率  町丁目 {cov_n}/{total_n} = {cov_n/total_n*100:.1f}%"
          f"   /   人口 {cov_p:,}/{total_p:,} = {cov_p/total_p*100:.1f}%")
    print(f"  （未割付 {total_n-cov_n} 件・{total_p-cov_p:,} 人分は UI で「不明」と出す）")

    # 市区町村ごと。まだ手を付けていない自治体を見つけるため、割付率の低い順に出す。
    per = {}
    for z in zones:
        c = z["city_name"] or "（不明）"
        n, p_, cn, cp = per.get(c, (0, 0, 0, 0))
        hit = z["key_code"] in covered
        per[c] = (n+1, p_+(z["population"] or 0), cn+(1 if hit else 0),
                  cp+((z["population"] or 0) if hit else 0))
    done = [(c, v) for c, v in per.items() if v[2] == v[0]]
    part = [(c, v) for c, v in per.items() if 0 < v[2] < v[0]]
    none = [(c, v) for c, v in per.items() if v[2] == 0]
    print(f"  市区町村: 全部割付済み {len(done)} / 一部 {len(part)} / 未着手 {len(none)}")
    for label, group in (("一部", part), ("未着手", none)):
        if not group:
            continue
        group.sort(key=lambda x: -x[1][1])
        head = ", ".join(f"{c}({v[2]}/{v[0]})" if label == "一部" else f"{c}({v[1]:,}人)"
                         for c, v in group[:8])
        print(f"    {label}: {head}" + (f" ほか {len(group)-8}" if len(group) > 8 else ""))


def replace(con, table, cols, rows):
    con.execute(f"DELETE FROM {table}")
    if not rows:
        print(f"  {table:<24} 0 行")
        return
    ph = ",".join("?" for _ in cols)
    con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
                    [tuple(r.get(c) for c in cols) for r in rows])
    print(f"  {table:<24} {len(rows)} 行")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="この日時点で有効な行だけで合成する（既定: 今日）")
    ap.add_argument("--dry-run", action="store_true", help="検証と合成だけして DB に書かない")
    args = ap.parse_args()
    as_of = datetime.date.fromisoformat(args.as_of) if args.as_of else datetime.date.today()

    zones = load_zones()
    zone_keys = {z["key_code"] for z in zones}
    print(f"町丁目: {len(zones)} 件")

    data = w.load_all()
    print("CSV:", ", ".join(f"{k}={len(v)}" for k, v in data.items()))

    print("\n検証")
    problems = w.Problems()
    w.validate_rules(data, zones, problems)
    # 区・市町村単位のルールを町丁目に展開してから、通常の検証に掛ける
    expanded = w.expand_rules(data, zones)
    if expanded:
        print(f"  zone_rule {len(data['zone_rule'])} 件 → zone_assignment {len(expanded)} 行に展開")
    data["zone_assignment"] = data["zone_assignment"] + expanded
    problems, data = w.validate(data, zone_keys, problems)
    if not problems.report():
        print("\nエラーがあるので DB には何も書かない。data/water/*.csv を直して再実行する。")
        return 1

    print(f"\n合成（{as_of} 時点）")
    shares, unresolved = w.compose(data, as_of=as_of)
    covered = {r["key_code"] for r in shares}
    print(f"  水源比率 {len(shares)} 行 / 町丁目 {len(covered)} 件")
    if zones:
        coverage(zones, covered, data)
    if unresolved:
        print(f"  ! 上流が未入力で辿りきれなかった町丁目 {len(unresolved)} 件 "
              f"（例: {list(unresolved.items())[:3]}）")

    if args.dry_run:
        print("\n--dry-run なので書かない。")
        return 0

    con = appdb()
    con.executescript((ROOT / "scripts/schema_water.sql").read_text(encoding="utf-8"))
    replace(con, "water_utility", ["utility_id", "name", "kind", "note_ja"], data["utility"])
    replace(con, "water_source",
            ["source_id", "name", "type", "river_system", "parent_id", "river_name_ja",
             "lat", "lon", "note_ja", "source_doc_id"], data["water_source"])
    replace(con, "water_facility",
            ["facility_id", "utility_id", "name", "type", "lat", "lon", "note_ja", "source_doc_id"],
            data["facility"])
    replace(con, "water_source_doc",
            ["doc_id", "title", "publisher", "url", "published_at", "retrieved_at",
             "local_path", "sha256", "license_ja"], data["source_doc"])
    replace(con, "water_flow_edge",
            ["edge_id", "from_id", "to_id", "share", "basis", "valid_from", "valid_to",
             "source_doc_id", "note_ja"], data["flow_edge"])
    replace(con, "water_zone",
            ["key_code", "muni_code", "city_name", "s_name", "name", "parts",
             "population", "households", "area_km2", "centroid_lat", "centroid_lon"], zones)
    replace(con, "water_zone_assignment",
            ["assignment_id", "key_code", "facility_id", "share", "confidence",
             "valid_from", "valid_to", "source_doc_id", "note_ja"], data["zone_assignment"])
    replace(con, "water_zone_source_share",
            ["key_code", "source_id", "share", "confidence", "basis", "as_of"], shares)
    con.commit()
    con.close()
    print("\nryuiki.sqlite に書いた。次は `cd web && pnpm run build:derived` → `pnpm run db:seed`。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
