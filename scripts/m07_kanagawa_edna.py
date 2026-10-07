#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県 eDNA 調査結果を ryuiki.sqlite の原本表（edna_sites / edna_reads / edna_detections）に入れる。

設計: docs/plans/KANAGAWA_EDNA.md §2.2・§3.3・§5.1。DDL は scripts/schema_edna.sql。

入力:
  data/processed/kanagawa_edna_sites.csv / kanagawa_edna_reads.csv   （c89。0 を含む全セル）
  data/edna/kanagawa_edna_site_coords.csv                            （c89b。地点の推定座標台帳）
  registry/taxon/kanagawa_edna_name_map.csv                          （c89c。name_key → taxon_id）

方針:
- 冪等: 3 表を丸ごと wipe してから同じトランザクションで入れ直す（この3表はこの出典だけの表）。
- 台帳の site_key 集合と c89 の地点集合が**一致しなければ止まる**（ずれを黙って許さない）。
- name_map に無い name_key が 1 件でもあれば止まる（unmapped は 0 件が条件）。
- edna_detections の件数が edna_reads の is_detected=1 と一致しなければ止まる。
- 本物の data/db/ryuiki.sqlite に流すのはメインだけ。確認は一時コピーの DB に `--db` で。
"""
import sys, csv, json, sqlite3, argparse, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from c89c_edna_taxon_map import clean_core, has_cf, is_ambiguous, read_csv_rows, text  # noqa: E402  判定・読み出しは c89c と共有

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_ID = "kanagawa_edna"
SCHEMA = ROOT / "scripts" / "schema_edna.sql"
DEFAULT_SITES = ROOT / "data" / "processed" / "kanagawa_edna_sites.csv"
DEFAULT_READS = ROOT / "data" / "processed" / "kanagawa_edna_reads.csv"
DEFAULT_COORDS = ROOT / "data" / "edna" / "kanagawa_edna_site_coords.csv"
DEFAULT_NAME_MAP = ROOT / "registry" / "taxon" / "kanagawa_edna_name_map.csv"

COORD_SOURCES = ("map_image", "estimated_from_name", "none")
SPECIES_RANKS = ("species", "subspecies", "variety", "form")


class M07Error(RuntimeError):
    pass


def num(v):
    s = text(v)
    return None if s is None else float(s)


def build_coord_index(sites, coords):
    """台帳を site_key で引く。台帳と c89 の地点集合が一致しなければ止まる。"""
    by_key = {}
    for c in coords:
        k = c["site_key"]
        if k in by_key:
            raise M07Error(f"台帳に site_key の重複: {k}")
        by_key[k] = c
    site_keys = {s["site_key"] for s in sites}
    if len(site_keys) != len(sites):
        raise M07Error("c89 の地点に site_key の重複がある")
    only_sites = sorted(site_keys - by_key.keys())
    only_ledger = sorted(by_key.keys() - site_keys)
    if only_sites or only_ledger:
        raise M07Error(f"台帳と c89 の地点集合が一致しない（台帳に無い {len(only_sites)} 件 {only_sites[:5]} / "
                       f"c89 に無い {len(only_ledger)} 件 {only_ledger[:5]}）")
    site_by = {s["site_key"]: s for s in sites}
    for k, c in by_key.items():
        for col in ("water_system_ja", "tributary_ja", "municipality_ja"):
            if text(c.get(col)) != text(site_by[k].get(col)):
                raise M07Error(f"台帳 {k}: {col} が c89 の地点と違う（台帳 {c.get(col)!r} / c89 {site_by[k].get(col)!r}）。"
                               "c89 を作り直したら c89b を再実行して台帳を更新すること")
        src = text(c.get("coord_source"))
        if src not in COORD_SOURCES:
            raise M07Error(f"台帳 {k}: coord_source が不正 ({src!r})")
        lat, lon, unc = num(c.get("lat")), num(c.get("lon")), num(c.get("coordinate_uncertainty_m"))
        if src == "none":
            if lat is not None or lon is not None or unc is not None:
                raise M07Error(f"台帳 {k}: coord_source=none なのに座標・精度がある")
        elif lat is None or lon is None or unc is None:
            raise M07Error(f"台帳 {k}: 座標あり（{src}）なのに lat/lon/精度のどれかが空")
    return by_key


def build_name_index(name_map):
    idx = {}
    for r in name_map:
        k = r["name_key"]
        if k in idx:
            raise M07Error(f"name_map に name_key の重複: {k!r}")
        if not text(r.get("taxon_id")):
            raise M07Error(f"name_map の {k!r} に taxon_id が無い")
        idx[k] = r
    return idx


def rank_reduced(nm):
    """属止まり・併記で上位に寄せた（解決先が種より上、または tier T5）。"""
    rank = (text(nm.get("rank")) or "").lower()
    return bool(rank and rank not in SPECIES_RANKS) or text(nm.get("tier")) == "T5"


def vernacular_for(read, nm):
    """occurrence の vernacular_name。name_map に和名があればそれ。無ければ、種のままの行に限りシートの採用名
    （日本語のもの。括弧書きは除く）。上位 taxon に寄せた行には付けない（種名を上位 taxon の名前にしない）。"""
    v = text(nm.get("vernacular_name_ja"))
    if v or rank_reduced(nm):
        return v
    core = clean_core(read.get("name_adopted") or "")[0]
    return core if core and not core.isascii() else None


def build_attributes(site, read, nm, coord):
    """設計 §3.3 の attributes。dataset_filter は r7_kenmin だけ。"""
    adopted = text(read.get("name_adopted")) or ""
    attrs = {
        "dataset_file": site["dataset_file"], "program": site["program"], "assay": site["assay"],
        "fiscal_year": int(site["fiscal_year"]), "site_key": site["site_key"],
        "site_id_raw": site["site_id_raw"],
        "water_system": text(site.get("water_system_ja")), "tributary": text(site.get("tributary_ja")),
        "municipality": text(site.get("municipality_ja")),
        "reads": int(read["reads"]),
        "reliability": text(read.get("reliability")),
        "pident_qcov": num(read.get("pident_qcov")),
        "name_adopted": text(read.get("name_adopted")),
        "name_note": text(read.get("name_note")),
        "cf": any(has_cf(read.get(k) or "") for k in ("name_note", "name_adopted", "name_sci_raw")),
        "rank_reduced": rank_reduced(nm),
        "name_ambiguous": is_ambiguous(adopted),
        "coord_source": text(coord.get("coord_source")),
        "coord_method": text(coord.get("coord_method")),
        "alien_raw": text(read.get("alien_raw")),
        "national_rl_raw": text(read.get("national_rl_raw")),
        "pref_rl_raw": text(read.get("pref_rl_raw")),
    }
    if text(read.get("dataset_filter")):
        attrs["dataset_filter"] = read["dataset_filter"]     # r7_kenmin の「98.5%以上の一致のみ」
    return json.dumps(attrs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def load(con, sites, reads, coords, name_map):
    """3 表を wipe+reload する。呼び出し側が commit/rollback する（1 トランザクション）。"""
    coord_by = build_coord_index(sites, coords)
    name_by = build_name_index(name_map)
    site_by = {s["site_key"]: s for s in sites}

    missing = sorted({r["name_key"] for r in reads} - name_by.keys())
    if missing:
        raise M07Error(f"name_map に無い name_key が {len(missing)} 件ある（unmapped は 0 件が条件）: {missing[:10]}")
    orphan = sorted({r["site_key"] for r in reads} - site_by.keys())
    if orphan:
        raise M07Error(f"地点に無い site_key を持つ読みがある: {orphan[:5]}")

    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    # この3表はこの出典だけの表。FK の向きを守って子から消す
    for t in ("edna_detections", "edna_reads", "edna_sites"):
        con.execute(f"DELETE FROM {t}")

    site_rows = []
    for s in sites:
        c = coord_by[s["site_key"]]
        site_rows.append((
            s["site_key"], s["dataset_file"], s["program"], s["assay"], int(s["fiscal_year"]),
            s["site_id_raw"], text(s.get("water_system_raw")), text(s.get("water_system_ja")),
            text(s.get("tributary_raw")), text(s.get("tributary_ja")),
            text(s.get("municipality_raw")), text(s.get("municipality_ja")),
            text(s.get("collected_on")), text(s.get("collected_on_raw")),
            num(c.get("lat")), num(c.get("lon")), text(c["coord_source"]),
            num(c.get("coordinate_uncertainty_m")), text(c.get("coord_method")), text(c.get("evidence")),
            s["source_id"], s["source_ref"]))
    con.executemany("""INSERT INTO edna_sites
        (site_key,dataset_file,program,assay,fiscal_year,site_id_raw,water_system_raw,water_system_ja,
         tributary_raw,tributary_ja,municipality_raw,municipality_ja,collected_on,collected_on_raw,
         lat,lon,coord_source,coordinate_uncertainty_m,coord_method,coord_note,source_id,source_ref)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", site_rows)

    read_rows, det_rows = [], []
    for r in reads:
        nm = name_by[r["name_key"]]
        n = int(r["reads"])
        read_rows.append((
            r["read_id"], r["site_key"], text(r.get("class_ja")), text(r.get("order_ja")),
            text(r.get("family_ja")), text(r.get("genus_ja")), text(r.get("name_raw")),
            text(r.get("name_adopted")), text(r.get("name_sci_raw")), text(r.get("name_note")),
            n, int(n > 0), num(r.get("pident_qcov")), text(r.get("reliability")),
            text(r.get("national_rl_raw")), text(r.get("pref_rl_raw")), text(r.get("alien_raw")),
            r["name_key"], nm["taxon_id"].strip(), r["source_id"]))
        if n > 0:
            s, c = site_by[r["site_key"]], coord_by[r["site_key"]]
            det_rows.append((
                r["read_id"], nm["taxon_id"].strip(), text(nm.get("scientific_name")),
                vernacular_for(r, nm), text(nm.get("rank")),
                text(r.get("national_rl_raw")) or text(r.get("pref_rl_raw")),
                text(s.get("collected_on")), num(c.get("lat")), num(c.get("lon")),
                num(c.get("coordinate_uncertainty_m")), build_attributes(s, r, nm, c)))
    con.executemany("""INSERT INTO edna_reads
        (read_id,site_key,class_ja,order_ja,family_ja,genus_ja,name_raw,name_adopted,name_sci_raw,
         name_note,reads,is_detected,pident_qcov,reliability,national_rl_raw,pref_rl_raw,alien_raw,
         name_key,taxon_id,source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", read_rows)
    con.executemany("""INSERT INTO edna_detections
        (record_key,taxon_id,scientific_name,vernacular_name,taxon_rank,red_list_category,observed_on,
         lat,lon,coordinate_uncertainty_m,attributes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", det_rows)

    n_det = con.execute("SELECT COUNT(*) FROM edna_detections").fetchone()[0]
    n_flag = con.execute("SELECT COUNT(*) FROM edna_reads WHERE is_detected=1").fetchone()[0]
    if n_det != n_flag:
        raise M07Error(f"edna_detections {n_det} 件が edna_reads の is_detected=1 {n_flag} 件と一致しない")
    n_null = con.execute("SELECT COUNT(*) FROM edna_reads WHERE taxon_id IS NULL").fetchone()[0]
    if n_null:
        raise M07Error(f"edna_reads に taxon_id が NULL の行が {n_null} 件ある")
    return {"sites": len(site_rows), "reads": len(read_rows), "detections": len(det_rows)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="書き込み先の sqlite（既定: data/db/ryuiki.sqlite。確認は一時コピーで）")
    ap.add_argument("--sites", default=str(DEFAULT_SITES))
    ap.add_argument("--reads", default=str(DEFAULT_READS))
    ap.add_argument("--coords", default=str(DEFAULT_COORDS))
    ap.add_argument("--name-map", default=str(DEFAULT_NAME_MAP))
    args = ap.parse_args(argv)

    for label, p in (("c89 の地点 CSV", args.sites), ("c89 の読み CSV", args.reads),
                     ("座標台帳（c89b）", args.coords), ("name_map（c89c）", args.name_map)):
        if not pathlib.Path(p).exists():
            raise SystemExit(f"{label}が無い: {p}")
    if args.db:
        con = sqlite3.connect(args.db, timeout=30)
    else:
        from common import appdb
        con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    con.execute("PRAGMA foreign_keys = ON")
    try:
        res = load(con, read_csv_rows(args.sites), read_csv_rows(args.reads), read_csv_rows(args.coords),
                   read_csv_rows(args.name_map))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"edna_sites {res['sites']} / edna_reads {res['reads']} / edna_detections {res['detections']}")


if __name__ == "__main__":
    main()
