#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""モニタリングサイト1000（モニ1000）神奈川県 5 出典を ryuiki.sqlite の原本表 moni1000_counts に入れる。

設計: docs/plans/MONI1000.md §2.1・§2.2・§3.2。DDL は scripts/schema_moni1000.sql。

入力:
  data/processed/moni1000_{satochi_bird_census,satochi_butterfly_census,forest_bird,satochi_mammal_photo,
                           coast_shorebird}_kanagawa.csv                 （5 出典の生の記録）
  data/processed/moni1000_{satochi_bird,satochi_butterfly,satochi_mammal}_sites_kanagawa.csv （里地の地点座標）
  registry/source/moni1000_site_map.csv   （地点対応表: 出典の地点キー → registry の place）
  registry/taxon/moni1000_name_map.csv    （名寄せ表: 出典の和名〔と学名〕→ taxon。作り方は m10_moni1000_name_map.py）

方針:
- 生の行は 1 行も落とさない。occurrence に流さない行は in_occurrence=0 と exclude_reason に理由を残す
  （zero_count / unresolved_taxon / non_wild / non_species。§3.2）。
- 座標は出典の値のまま持つ（丸め・補完・ぼかしをしない）。里地は sites CSV の「緯度詳細/経度詳細」が数値ならそれ、
  「非公開」なら 0.1 度丸めの lat/lon、それも無ければ NULL。
- 冪等: 自分の 5 出典の行だけを wipe してから同じトランザクションで入れ直す。
- 取り込み後の検査（ずれたら止まって rollback）: 行数が CSV と 5 出典それぞれ一致 / record_id 一意 /
  in_occurrence=1 で taxon_id が NULL でない / exclude_reason が語彙内 / observed_on が正規形。
- 隔離解除: source_registry の 5 行を redistributable=1 にし、notes に追認済みを追記する（組織の追認 2026-10-12、
  オーナー確認。新たな取得はしない）。
- 本物の data/db/ryuiki.sqlite に流すのは 1 回だけ（実行前に .backup を取る）。確認は --dry-run か、一時コピーへの --db で。
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import json
import pathlib
import re
import sqlite3
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scripts" / "schema_moni1000.sql"
DEFAULT_CSV_DIR = ROOT / "data" / "processed"
DEFAULT_SITE_MAP = ROOT / "registry" / "source" / "moni1000_site_map.csv"
DEFAULT_NAME_MAP = ROOT / "registry" / "taxon" / "moni1000_name_map.csv"

# 出典 → 入力 CSV と正規化の種類。順序は出力の順序でもある。
SOURCES = {
    "moni1000_satochi_bird": {"csv": "moni1000_satochi_bird_census_kanagawa.csv",
                              "sites": "moni1000_satochi_bird_sites_kanagawa.csv", "kind": "satochi_bird"},
    "moni1000_satochi_butterfly": {"csv": "moni1000_satochi_butterfly_census_kanagawa.csv",
                                   "sites": "moni1000_satochi_butterfly_sites_kanagawa.csv",
                                   "kind": "satochi_butterfly"},
    "moni1000_forest_bird": {"csv": "moni1000_forest_bird_kanagawa.csv", "sites": None, "kind": "forest_bird"},
    "moni1000_satochi_mammal": {"csv": "moni1000_satochi_mammal_photo_kanagawa.csv",
                                "sites": "moni1000_satochi_mammal_sites_kanagawa.csv", "kind": "satochi_mammal"},
    "moni1000_coast_shorebird": {"csv": "moni1000_coast_shorebird_kanagawa.csv", "sites": None,
                                 "kind": "coast_shorebird"},
}
# 学名列が行にある出典。名寄せのキーは「和名|学名」（同じ和名に学名の表記ゆれがあるため）
SCI_SOURCES = ("moni1000_forest_bird", "moni1000_coast_shorebird")

EXCLUDE_REASONS = ("zero_count", "unresolved_taxon", "non_wild", "non_species")
RESOLUTIONS = ("map_sci", "map_ja", "unresolved", "non_taxon")
BASIS_RESOLUTION = {"sci": "map_sci", "ja_unique": "map_ja", "ja_paired_sci": "map_ja", "curated": "map_ja"}
UNRESOLVED_NAME = "(空)"
REGISTRY_NOTE_MARK = "【隔離解除 2026-10-12】"
REGISTRY_NOTE = (REGISTRY_NOTE_MARK + "組織の追認済み（2026-10-12、オーナー確認）。redistributable=1 に戻し、D1・MCP に載せる。"
                 "新たな取得（フォーム送信・再ダウンロード）はしない。")

COLUMNS = (
    "record_id", "source_id", "source_ref", "survey_id", "site_key", "site_name_ja", "place_id", "lat", "lon",
    "lat_lon_basis", "coord_decimals", "observed_on", "survey_year", "survey_month", "survey_day", "start_time",
    "end_time", "season_ja", "survey_round", "section_ja", "species_ja", "scientific_name", "individual_count",
    "individual_count_raw", "count_qualifier", "id_note_ja", "out_of_range", "out_of_time", "taxon_id",
    "taxon_resolution", "in_occurrence", "exclude_reason", "extra_json")


class M10Error(RuntimeError):
    pass


# ── 値の整形 ─────────────────────────────────────────────

def text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_int(v):
    """'2005.0' / '9' → int。空・非数値は None。"""
    s = text(v)
    if s is None:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else None


def to_num(v):
    s = text(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def observed_on(y, m, d):
    """欠けた分は補わない: 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY' / None。月が無ければ日は使わない。"""
    if y is None:
        return None
    if m is None:
        return f"{y:04d}"
    if d is None:
        datetime.date(y, m, 1)
        return f"{y:04d}-{m:02d}"
    datetime.date(y, m, d)           # 暦にない日付は ValueError で止める
    return f"{y:04d}-{m:02d}-{d:02d}"


def hhmm(h, mi):
    h, mi = to_int(h), to_int(mi)
    if h is None or mi is None:
        return None
    return f"{h:02d}:{mi:02d}"


def norm_time(v):
    """'13:15' / '9:05:00' / '1305' 等 → 'HH:MM'。解釈できなければ None。"""
    s = text(v)
    if s is None:
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def parse_coord(v):
    """座標の文字列 → (float, 小数桁数)。float の表記ゆれ（139.76800000000003）は 7 桁に丸めてから数える。"""
    s = text(v)
    if s is None:
        return None, None
    try:
        f = float(s)
    except ValueError:
        return None, None       # '非公開' など
    frac = s.split(".", 1)[1] if "." in s else ""
    if len(frac) > 8:
        f = round(f, 7)
        frac = repr(f).split(".", 1)[1] if "." in repr(f) else ""
    return f, len(frac)


def dump_extra(d):
    d = {k: v for k, v in d.items() if text(v) is not None}
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if d else None


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def clean_sci(v):
    s = text(v)
    return None if s is None or s in ("－", "-") else s


def name_key(source_id, species_ja, scientific_name):
    """名寄せ表のキー。和名は NFKC・前後空白除去。学名のある出典は「和名|学名」。"""
    ja = unicodedata.normalize("NFKC", text(species_ja) or "") or UNRESOLVED_NAME
    if source_id in SCI_SOURCES:
        return f"{ja}|{clean_sci(scientific_name) or ''}"
    return ja


# ── 地点（里地の sites CSV） ─────────────────────────────

def load_site_coords(csv_dir, sites_csv):
    """sites CSV → {site_id: (lat, lon, decimals)}。詳細座標が数値ならそれ、無ければ丸めの lat/lon、無ければ None。"""
    out = {}
    if not sites_csv:
        return out
    for r in read_csv(pathlib.Path(csv_dir) / sites_csv):
        lat, dec_lat = parse_coord(r.get("緯度詳細"))
        lon, dec_lon = parse_coord(r.get("経度詳細"))
        if lat is None or lon is None:
            lat, dec_lat = parse_coord(r.get("lat"))
            lon, dec_lon = parse_coord(r.get("lon"))
        if lat is None or lon is None:
            out[r["site_id"]] = (None, None, None)
        else:
            out[r["site_id"]] = (lat, lon, min(dec_lat, dec_lon))
    return out


# ── 出典ごとの正規化 ─────────────────────────────────────

def base_record(source_id, row, record_id):
    return {c: None for c in COLUMNS} | {
        "record_id": record_id, "source_id": source_id, "source_ref": text(row.get("source_ref"))}


def fill_count(rec, raw):
    rec["individual_count_raw"] = text(raw)
    rec["individual_count"] = to_num(raw)


def flag(v):
    return 1 if text(v) else 0


def norm_satochi_bird(row, rec, site_coords):
    rec["survey_id"] = text(row["survey_id"])
    rec["site_key"] = row["site_id"].strip()
    y, m = to_int(row["survey_year"]), to_int(row["survey_month"])
    rec.update(survey_year=y, survey_month=m, observed_on=observed_on(y, m, None),
               season_ja=text(row["season_ja"]), survey_round=text(row["rep_no"]),
               section_ja=text(row["section_name_ja"]), species_ja=text(row["species_ja"]),
               count_qualifier=text(row["plusminus"]), id_note_ja=text(row["id_confidence_ja"]),
               out_of_range=flag(row["out_of_range"]), out_of_time=flag(row["out_of_time"]))
    fill_count(rec, row["count"])
    rec["extra_json"] = dump_extra({
        "id_visual": row["id_visual"], "id_song": row["id_song"], "id_call": row["id_call"],
        "age_class_ja": row["age_class_ja"], "breeding_behavior_ja": row["breeding_behavior_ja"]})
    site_coord(rec, site_coords)


def norm_satochi_butterfly(row, rec, site_coords):
    rec["survey_id"] = text(row["survey_id"])
    rec["site_key"] = row["site_id"].strip()
    y, m, d = to_int(row["survey_year"]), to_int(row["survey_month"]), to_int(row["survey_day"])
    rec.update(survey_year=y, survey_month=m, survey_day=d, observed_on=observed_on(y, m, d),
               section_ja=text(row["section_name_ja"]), species_ja=text(row["species_ja"]),
               out_of_range=flag(row["out_of_range"]), out_of_time=flag(row["out_of_time"]))
    fill_count(rec, row["count"])
    site_coord(rec, site_coords)


def norm_satochi_mammal(row, rec, site_coords):
    rec["survey_id"] = text(row["survey_id"])
    rec["site_key"] = row["site_id"].strip()
    y, m, d = to_int(row["photo_year"]), to_int(row["photo_month"]), to_int(row["photo_day"])
    rec.update(survey_year=y, survey_month=m, survey_day=d, observed_on=observed_on(y, m, d),
               start_time=norm_time(row["photo_time"]), species_ja=text(row["species_ja"]))
    fill_count(rec, row["count"])
    site_coord(rec, site_coords)


def norm_forest_bird(row, rec, site_coords):
    rec["site_key"] = row["site_id"].strip()
    y, m, d = to_int(row["survey_year"]), to_int(row["survey_month"]), to_int(row["survey_day"])
    lat, dec_lat = parse_coord(row["lat"])
    lon, dec_lon = parse_coord(row["lon"])
    rec.update(survey_year=y, survey_month=m, survey_day=d, observed_on=observed_on(y, m, d),
               start_time=hhmm(row["start_hour"], row["start_min"]), end_time=hhmm(row["end_hour"], row["end_min"]),
               season_ja=text(row["survey_period_ja"]), survey_round=None if to_int(row["rep_no"]) is None
               else str(to_int(row["rep_no"])), section_ja=text(row["point_ja"]),
               species_ja=text(row["species_ja"]), scientific_name=text(row["scientific_name"]),
               id_note_ja=text(row["id_type_ja"]))
    if lat is not None and lon is not None:
        rec.update(lat=lat, lon=lon, lat_lon_basis="row", coord_decimals=min(dec_lat, dec_lon))
    fill_count(rec, row["count"])
    rec["extra_json"] = dump_extra({
        "site_type_ja": row["site_type_ja"], "habitat_ja": row["habitat_ja"], "prefecture_ja": row["prefecture_ja"],
        "municipality_ja": row["municipality_ja"], "cycle_ja": row["cycle_ja"], "weather_ja": row["weather_ja"],
        "subspecies_ja": row["subspecies_ja"], "survey_method_ja": row["survey_method_ja"]})


def norm_coast_shorebird(row, rec, site_coords):
    rec["site_key"] = row["site_code"].strip()
    y, m, d = to_int(row["year"]), to_int(row["month"]), to_int(row["day"])
    lat, dec_lat = parse_coord(row["lat"])
    lon, dec_lon = parse_coord(row["lon"])
    rec.update(survey_year=y, survey_month=m, survey_day=d, observed_on=observed_on(y, m, d),
               start_time=norm_time(row["start_time"]), end_time=norm_time(row["end_time"]),
               season_ja=text(row["season_ja"]), species_ja=text(row["species_ja"]),
               scientific_name=text(row["scientific_name"]))
    if lat is not None and lon is not None:
        rec.update(lat=lat, lon=lon, lat_lon_basis="row", coord_decimals=min(dec_lat, dec_lon))
    fill_count(rec, row["count"])
    rec["extra_json"] = dump_extra({
        "species_en": row["species_en"], "survey_year_raw": row["survey_year_raw"],
        "site_name_raw_ja": row["site_name_ja"], "site_name_romaji": row["site_name_romaji"]})


def site_coord(rec, site_coords):
    c = site_coords.get(rec["site_key"])
    if c and c[0] is not None:
        rec.update(lat=c[0], lon=c[1], lat_lon_basis="site_table", coord_decimals=c[2])


NORMALIZERS = {"satochi_bird": norm_satochi_bird, "satochi_butterfly": norm_satochi_butterfly,
               "satochi_mammal": norm_satochi_mammal, "forest_bird": norm_forest_bird,
               "coast_shorebird": norm_coast_shorebird}
# 行に data_id がある出典（record_id = '{source_id}:{data_id}'）。他は CSV の行順で r{6桁}
DATA_ID_KINDS = ("satochi_bird", "satochi_butterfly", "satochi_mammal")


def normalize_source(source_id, csv_dir=DEFAULT_CSV_DIR):
    """1 出典の CSV → 正規化済みの記録（名寄せ・地点対応・除外の前）。name_key を '_name_key' に持つ。"""
    cfg = SOURCES[source_id]
    rows = read_csv(pathlib.Path(csv_dir) / cfg["csv"])
    site_coords = load_site_coords(csv_dir, cfg["sites"])
    fn = NORMALIZERS[cfg["kind"]]
    out = []
    for i, row in enumerate(rows, 1):
        rid = f"{source_id}:{row['data_id'].strip()}" if cfg["kind"] in DATA_ID_KINDS else f"{source_id}:r{i:06d}"
        rec = base_record(source_id, row, rid)
        fn(row, rec, site_coords)
        rec["_name_key"] = name_key(source_id, rec["species_ja"], rec["scientific_name"])
        out.append(rec)
    return out


def normalize_all(csv_dir=DEFAULT_CSV_DIR):
    return {sid: normalize_source(sid, csv_dir) for sid in SOURCES}


# ── 地点対応表・名寄せ表 ─────────────────────────────────

def load_site_map(path=DEFAULT_SITE_MAP):
    idx = {}
    for r in read_csv(path):
        k = (r["source_id"], r["site_key"])
        if k in idx:
            raise M10Error(f"地点対応表に重複: {k}")
        idx[k] = r
    return idx


def load_name_map(path=DEFAULT_NAME_MAP):
    idx = {}
    for r in read_csv(path):
        k = (r["source_id"], r["name_key"])
        if k in idx:
            raise M10Error(f"名寄せ表に重複: {k}")
        idx[k] = r
    return idx


def resolve(records, name_map, site_map):
    """名寄せ・地点対応・除外理由を付ける。表に無い語・地点は止める（黙って未解決にしない）。"""
    for rec in records:
        sm = site_map.get((rec["source_id"], rec["site_key"]))
        if sm is None:
            raise M10Error(f"地点対応表に無い地点: {rec['source_id']} {rec['site_key']}")
        rec["site_name_ja"] = text(sm.get("site_name_ja"))
        rec["place_id"] = text(sm.get("place_id"))

        nm = name_map.get((rec["source_id"], rec["_name_key"]))
        if nm is None:
            raise M10Error(f"名寄せ表に無い語: {rec['source_id']} {rec['_name_key']!r}（m10_moni1000_name_map.py で作り直す）")
        basis = nm["basis"]
        reason = None
        if basis in BASIS_RESOLUTION:
            rec["taxon_id"] = text(nm.get("taxon_id"))
            if not rec["taxon_id"]:
                raise M10Error(f"名寄せ表の {rec['_name_key']!r}（{basis}）に taxon_id が無い")
            rec["taxon_resolution"] = BASIS_RESOLUTION[basis]
        elif basis.startswith("exclude:"):
            reason = basis.split(":", 1)[1]
            if reason not in ("non_wild", "non_species", "unresolved_taxon"):
                raise M10Error(f"名寄せ表の basis が不正: {basis!r}")
            rec["taxon_resolution"] = "unresolved" if reason == "unresolved_taxon" else "non_taxon"
        elif basis.startswith("pending:"):
            reason = "unresolved_taxon"          # 人の判断待ち。決まるまでは occurrence に流さない
            rec["taxon_resolution"] = "unresolved"
        else:
            raise M10Error(f"名寄せ表の basis が不正: {basis!r}")
        if rec["species_ja"] and rec["species_ja"].endswith(("？", "?")) and rec["id_note_ja"] is None:
            rec["id_note_ja"] = "?"
        # 個体数 0 は不在記録。名前の理由より先に見る（0 の行は種名が何であれ出現にしない）
        if rec["individual_count"] == 0:
            reason = "zero_count"
        rec["in_occurrence"] = 0 if reason else 1
        rec["exclude_reason"] = reason
    return records


# ── 内訳（dry-run・実行後のレポート） ─────────────────────

def obs_shape(v):
    if v is None:
        return "NULL"
    return {10: "day", 7: "month", 4: "year"}[len(v)]


def summarize(records):
    by = collections.defaultdict(list)
    for r in records:
        by[r["source_id"]].append(r)
    out = {}
    for sid, rs in by.items():
        out[sid] = {
            "input_rows": len(rs),
            "in_occurrence_1": sum(r["in_occurrence"] for r in rs),
            "exclude_reason": dict(collections.Counter(r["exclude_reason"] for r in rs if r["exclude_reason"])),
            "observed_on_shape": dict(collections.Counter(obs_shape(r["observed_on"]) for r in rs)),
            "with_coord": sum(1 for r in rs if r["lat"] is not None),
            "with_place_id": sum(1 for r in rs if r["place_id"]),
            "taxon_resolution": dict(collections.Counter(r["taxon_resolution"] for r in rs)),
        }
    return out


def print_summary(records):
    s = summarize(records)
    for sid in SOURCES:
        if sid in s:
            print(sid, json.dumps(s[sid], ensure_ascii=False, sort_keys=True))
    print("TOTAL", sum(v["input_rows"] for v in s.values()), "in_occurrence=1:",
          sum(v["in_occurrence_1"] for v in s.values()))


# ── DB への書き込み ──────────────────────────────────────

def check_records(records, csv_counts):
    ids = [r["record_id"] for r in records]
    if len(set(ids)) != len(ids):
        dup = [k for k, v in collections.Counter(ids).items() if v > 1][:3]
        raise M10Error(f"record_id が一意でない: {dup}")
    for sid, n in csv_counts.items():
        got = sum(1 for r in records if r["source_id"] == sid)
        if got != n:
            raise M10Error(f"{sid}: 行数が CSV と違う（CSV {n} / 投入 {got}）")
    for r in records:
        if r["in_occurrence"] == 1 and not r["taxon_id"]:
            raise M10Error(f"in_occurrence=1 で taxon_id が NULL: {r['record_id']}")
        if (r["in_occurrence"] == 0) != (r["exclude_reason"] is not None) or (
                r["exclude_reason"] is not None and r["exclude_reason"] not in EXCLUDE_REASONS):
            raise M10Error(f"in_occurrence と exclude_reason が不整合: {r['record_id']} {r['exclude_reason']!r}")
        o = r["observed_on"]
        if o is not None and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", o):
            raise M10Error(f"observed_on が正規形でない: {r['record_id']} {o!r}")


def load(con, records, csv_counts):
    """moni1000_counts を自分の 5 出典分だけ wipe → 入れ直し、source_registry の隔離を解く。呼び出し側が commit/rollback。"""
    check_records(records, csv_counts)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    marks = ",".join("?" for _ in SOURCES)
    con.execute(f"DELETE FROM moni1000_counts WHERE source_id IN ({marks})", tuple(SOURCES))
    con.executemany(
        f"INSERT INTO moni1000_counts ({','.join(COLUMNS)}) VALUES ({','.join('?' for _ in COLUMNS)})",
        [tuple(r[c] for c in COLUMNS) for r in records])
    n = con.execute(f"SELECT COUNT(*) FROM moni1000_counts WHERE source_id IN ({marks})", tuple(SOURCES)).fetchone()[0]
    if n != len(records):
        raise M10Error(f"投入後の行数が合わない（{n} / {len(records)}）")
    released = 0
    has_registry = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_registry'").fetchone()
    if has_registry:
        for sid in SOURCES:
            row = con.execute("SELECT notes FROM source_registry WHERE source_id=?", (sid,)).fetchone()
            if row is None:
                raise M10Error(f"source_registry に {sid} の行が無い")
            notes = row[0] or ""
            if REGISTRY_NOTE_MARK not in notes:
                notes = (notes + " || " if notes else "") + REGISTRY_NOTE
            con.execute("UPDATE source_registry SET redistributable=1, notes=? WHERE source_id=?", (notes, sid))
            released += 1
    return {"rows": n, "released": released}


def main(argv=None):
    ap = argparse.ArgumentParser(description="モニ1000 神奈川県 5 出典を moni1000_counts に入れる（--dry-run は件数だけ出す）")
    ap.add_argument("--dry-run", action="store_true", help="DB に触らず、5 出典の内訳だけ出す")
    ap.add_argument("--db", help="書き込み先の sqlite（既定: data/db/ryuiki.sqlite。確認は一時コピーで）")
    ap.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR))
    ap.add_argument("--site-map", default=str(DEFAULT_SITE_MAP))
    ap.add_argument("--name-map", default=str(DEFAULT_NAME_MAP))
    args = ap.parse_args(argv)

    by_source = normalize_all(args.csv_dir)
    csv_counts = {sid: len(rs) for sid, rs in by_source.items()}
    records = resolve([r for rs in by_source.values() for r in rs],
                      load_name_map(args.name_map), load_site_map(args.site_map))
    print_summary(records)
    if args.dry_run:
        return
    if args.db:
        con = sqlite3.connect(args.db, timeout=30)
    else:
        from common import appdb
        con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        res = load(con, records, csv_counts)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"moni1000_counts {res['rows']} 行 / source_registry 隔離解除 {res['released']} 行")


if __name__ == "__main__":
    main()
