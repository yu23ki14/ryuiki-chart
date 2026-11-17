#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSM の河川線とダム・堰（c105_osm_waterways.py が data/raw/osm_waterways に保存した Overpass の生の応答）を
ryuiki.sqlite の原本表 osm_waterways / osm_water_structures に入れる。DDL は scripts/schema_osm_water.sql。

- 座標は Overpass の生の geometry のまま（丸め・間引きをしない）。長さは haversine の総和（球面近似）。
- 名前は OSM の `name`（`name:ja` は優先しない）を name_ja に入れる。
- region_id: c105 が raw に保存した取得範囲の region_id（`_region_id`）。県外の上流（桂川など）も取得範囲の region のまま。
- relation_id: way を含む waterway リレーション。複数なら、重なる範囲の全ファイルを通した最小の id（ファイル順に依存しない）。
- 冪等: 自分の出典（osm_waterways / osm_water_structures）の行を wipe してから同じトランザクションで入れ直す。
- source_registry の出典 2 行もここで登録する（record_count は投入した最終行数。表の COUNT(*) と一致）。
- 検査（ずれたら止まって rollback）: 主キー・source_ref 一意 / 行数が入力と一致。waterway・kind の語彙は parse が絞る。
- 本物の data/db/ryuiki.sqlite に流すのは 1 回だけ（実行前に .backup を取る）。確認は --dry-run か、一時コピーへの --db で。
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from m10_moni1000 import split_ddl  # noqa: E402  （DDL を 1 文ずつに分ける共有の関数）

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scripts" / "schema_osm_water.sql"
DEFAULT_RAW = ROOT / "data" / "raw" / "osm_waterways"
SRC_WAYS, SRC_STRUCT = "osm_waterways", "osm_water_structures"
WATERWAYS = ("river", "stream")
KINDS = ("dam", "weir")
EARTH_R_M = 6371008.8
ODBL_LICENSE = "ODbL 1.0（Share-Alike/帰属表示の継承条件あり、詳細: https://www.openstreetmap.org/copyright）"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SOURCES = {
    SRC_WAYS: "OpenStreetMap 河川線（waterway=river/stream、名前つき）",
    SRC_STRUCT: "OpenStreetMap ダム・堰（waterway=dam/weir）",
}


class M12Error(RuntimeError):
    pass


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def length_m(coords):
    """[[lon, lat], ...] の折れ線の長さ（m、球面近似）。"""
    return sum(haversine_m(a[1], a[0], b[1], b[0]) for a, b in zip(coords, coords[1:]))


def parse_rivers(body):
    """rivers の応答 → osm_waterways の行（dict）のリスト。名前も geometry も無い way は落とす（クエリは名前つきだけ）。"""
    rel = collections.defaultdict(list)
    for el in body.get("elements", []):
        if el.get("type") == "relation":
            for m in el.get("members", []):
                if m.get("type") == "way":
                    rel[m["ref"]].append(el["id"])
    region = body["_region_id"]
    rows = []
    for el in body.get("elements", []):
        tags = el.get("tags") or {}
        if el.get("type") != "way" or not tags.get("name") or not el.get("geometry") or tags.get("waterway") not in WATERWAYS:
            continue
        coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
        if len(coords) < 2:
            continue
        rows.append({
            "way_id": el["id"], "name_ja": tags["name"], "waterway": tags["waterway"],
            "relation_id": min(rel[el["id"]]) if rel.get(el["id"]) else None,
            "region_id": region,
            "length_m": length_m(coords),
            "geometry_geojson": json.dumps({"type": "LineString", "coordinates": coords}, ensure_ascii=False, separators=(",", ":")),
            "start_lat": coords[0][1], "start_lon": coords[0][0], "end_lat": coords[-1][1], "end_lon": coords[-1][0],
            "source_id": SRC_WAYS, "source_ref": f"osm:way/{el['id']}",
        })
    return rows


def parse_structures(body):
    """structures の応答 → osm_water_structures の行。座標が取れないものは落とす。"""
    region = body["_region_id"]
    rows = []
    for el in body.get("elements", []):
        tags = el.get("tags") or {}
        c = el.get("center") or el
        lat, lon = c.get("lat"), c.get("lon")
        if tags.get("waterway") not in KINDS or lat is None or lon is None:
            continue
        rows.append({
            "osm_type": el["type"], "osm_id": el["id"], "kind": tags["waterway"], "name_ja": tags.get("name"),
            "region_id": region, "lat": lat, "lon": lon,
            "source_id": SRC_STRUCT, "source_ref": f"osm:{el['type']}/{el['id']}",
        })
    return rows


def read_raw(raw_dir=DEFAULT_RAW):
    """保存済みの生の応答を全部読む。重なる範囲で同じ要素が複数ファイルに出たら 1 行にする
    （region_id・座標は先に読んだ方、relation_id は全ファイルを通した最小値）。
    返り値は (ways, structures, meta)。meta は出典の登録に使う取得日時と OSM データの時点。"""
    ways, structs = {}, {}
    fetched, base = [], []
    files = sorted(pathlib.Path(raw_dir).glob("*_rivers.json")) + sorted(pathlib.Path(raw_dir).glob("*_structures.json"))
    if not files:
        raise M12Error(f"生の応答が無い: {raw_dir}（c105_osm_waterways.py が先）")
    for f in files:
        body = json.loads(f.read_text(encoding="utf-8"))
        fetched.append(body.get("_fetched_at") or "")
        if (body.get("osm3s") or {}).get("timestamp_osm_base"):
            base.append(body["osm3s"]["timestamp_osm_base"])
        if f.name.endswith("_rivers.json"):
            for r in parse_rivers(body):
                old = ways.setdefault(r["way_id"], r)
                if old is not r and r["relation_id"] is not None:
                    old["relation_id"] = r["relation_id"] if old["relation_id"] is None else min(old["relation_id"], r["relation_id"])
        else:
            for r in parse_structures(body):
                structs.setdefault((r["osm_type"], r["osm_id"]), r)
    meta = {"fetched_at": max(fetched), "osm_base": max(base) if base else "不明"}
    return list(ways.values()), list(structs.values()), meta


def register_sources(con, counts, meta):
    """出典 2 行を source_registry に登録する（record_count は投入した最終行数）。"""
    note = (f"Overpass API（{OVERPASS_URL}）で scripts/c105_osm_waterways.py が取得。OSM データの時点（osm_base）: {meta['osm_base']}。"
            "重なる範囲の重複は way/要素の id で除いた最終行数。帰属表示「© OpenStreetMap contributors」が要る。座標は丸め・間引きなし。")
    for sid, name in SOURCES.items():
        con.execute(
            """INSERT OR REPLACE INTO source_registry
               (source_id,name,publisher,url,category,access_method,format,license,redistributable,fetched_at,record_count,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, name, "OpenStreetMap contributors", OVERPASS_URL, "osm", "Overpass API", "json", ODBL_LICENSE, 1,
             meta["fetched_at"], counts[sid], note))


def load(con, ways, structs, meta):
    """表を作り（無ければ）、自分の出典の行を wipe → 入れ直し、出典を登録する。呼び出し側が commit/rollback。"""
    if not con.in_transaction:
        con.execute("BEGIN")
    for stmt in split_ddl(SCHEMA.read_text(encoding="utf-8")):
        con.execute(stmt)
    plan = (("osm_waterways", SRC_WAYS, ways), ("osm_water_structures", SRC_STRUCT, structs))
    counts = {}
    for table, src, rows in plan:
        con.execute(f"DELETE FROM {table} WHERE source_id=?", (src,))
        if rows:
            cols = list(rows[0])
            con.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                            [tuple(r[c] for c in cols) for r in rows])
        n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE source_id=?", (src,)).fetchone()[0]
        if n != len(rows):
            raise M12Error(f"{table}: 投入後の行数が合わない（{n} / {len(rows)}）")
        counts[src] = n
    register_sources(con, counts, meta)
    return {"osm_waterways": counts[SRC_WAYS], "osm_water_structures": counts[SRC_STRUCT]}


def summary(ways, structs):
    by_region = collections.Counter((r["region_id"], r["waterway"]) for r in ways)
    st = collections.Counter((r["region_id"], r["kind"]) for r in structs)
    km = collections.defaultdict(float)
    for r in ways:
        km[r["region_id"]] += r["length_m"] / 1000
    lines = ["osm_waterways: %d 行（relation あり %d）" % (len(ways), sum(1 for r in ways if r["relation_id"]))]
    lines += [f"  {rid} {kind}: {n} 本" for (rid, kind), n in sorted(by_region.items(), key=str)]
    lines += [f"  {rid} 総延長 {v:,.0f} km" for rid, v in sorted(km.items(), key=str)]
    lines.append("osm_water_structures: %d 行" % len(structs))
    lines += [f"  {rid} {kind}: {n}" for (rid, kind), n in sorted(st.items(), key=str)]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="OSM の河川線・ダム・堰を osm_waterways / osm_water_structures に入れる")
    ap.add_argument("--dry-run", action="store_true", help="DB に触らず件数だけ出す")
    ap.add_argument("--db", help="書き込み先の sqlite（既定: data/db/ryuiki.sqlite。確認は一時コピーで）")
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    args = ap.parse_args(argv)
    ways, structs, meta = read_raw(args.raw_dir)
    print(summary(ways, structs))
    if args.dry_run:
        return
    if args.db:
        con = sqlite3.connect(args.db, timeout=30)
    else:
        from common import appdb
        con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        res = load(con, ways, structs, meta)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(res)


if __name__ == "__main__":
    main()
