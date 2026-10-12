"""m10_moni1000（モニ1000 5 出典の原本表への投入）のテスト。小さな CSV を tmp_path に作って通す。
本物の ryuiki.sqlite・data/processed には触らない。"""
import csv
import json
import sqlite3

import pytest

import m10_moni1000 as m10

SRC = "https://www.biodic.go.jp/moni1000/question/question.html"

BIRD = ["data_id", "survey_id", "site_id", "survey_year", "survey_month", "season_ja", "rep_no", "section_name_ja",
        "species_ja", "id_confidence_ja", "count", "plusminus", "id_visual", "id_song", "id_call", "age_class_ja",
        "breeding_behavior_ja", "out_of_range", "out_of_time", "source_id", "source_ref"]
BUTTERFLY = ["data_id", "survey_id", "site_id", "survey_year", "survey_month", "survey_day", "section_name_ja",
             "species_ja", "count", "out_of_range", "out_of_time", "source_id", "source_ref"]
FOREST = ["site_id", "site_type_ja", "habitat_ja", "lat", "lon", "prefecture_ja", "municipality_ja", "cycle_ja",
          "survey_period_ja", "point_ja", "rep_no", "survey_year", "survey_month", "survey_day", "start_hour",
          "start_min", "end_hour", "end_min", "weather_ja", "species_ja", "subspecies_ja", "scientific_name", "count",
          "id_type_ja", "survey_method_ja", "source_id", "source_ref"]
MAMMAL = ["data_id", "survey_id", "site_id", "photo_year", "photo_month", "photo_day", "photo_time", "species_ja",
          "count", "source_id", "source_ref"]
SHORE = ["survey_year_raw", "season_ja", "site_code", "site_name_ja", "site_name_romaji", "lat", "lon", "year", "month",
         "day", "start_time", "end_time", "species_ja", "species_en", "scientific_name", "count", "source_id",
         "source_ref"]
SITES = ["サイト名", "site_id", "site_name_ja", "prefecture", "住所（市町村区まで）", "lat", "lon", "緯度詳細", "経度詳細"]
MAMMAL_SITES = ["種別", "site_id", "site_name_ja", "prefecture", "住所（市町村区まで）", "lat", "lon"]


def write(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def bird(i, sp, count="1.0", **kw):
    return {"data_id": str(i), "survey_id": "Bi1", "site_id": "S064", "survey_year": "2009", "survey_month": "2",
            "season_ja": "越冬期", "rep_no": "5", "section_name_ja": "A", "species_ja": sp, "count": count,
            "id_visual": "○", "source_id": "moni1000_satochi_bird", "source_ref": SRC + " (SAT02)", **kw}


@pytest.fixture
def inputs(tmp_path):
    d = tmp_path / "csv"
    d.mkdir()
    write(d / "moni1000_satochi_bird_census_kanagawa.csv", BIRD, [
        bird(10, "ヒヨドリ", count="3.0", plusminus="+", out_of_range="範囲外"),
        bird(11, "スズメ", count="0.0"),                     # 個体数 0 → zero_count
        bird(12, "カラス科"),                                # 科 → non_species
        bird(13, "ウコッケイ"),                              # non_wild
        bird(14, "ツミ"),                                    # registry に無い → unresolved_taxon
        bird(15, "メジロ", id_confidence_ja="sp."),          # sp. でも名寄せできれば入れる
    ])
    write(d / "moni1000_satochi_bird_sites_kanagawa.csv", SITES, [
        {"site_id": "S064", "site_name_ja": "瀬上の森", "lat": "35.4", "lon": "139.6", "緯度詳細": "非公開", "経度詳細": "非公開"},
        {"site_id": "S065", "site_name_ja": "横浜自然観察の森", "lat": "35.3", "lon": "139.6", "緯度詳細": "35.3445", "経度詳細": "139.5869"}])
    write(d / "moni1000_satochi_butterfly_census_kanagawa.csv", BUTTERFLY, [
        {"data_id": "20", "survey_id": "Bt1", "site_id": "S065", "survey_year": "2008", "survey_month": "9",
         "survey_day": "6", "section_name_ja": "A", "species_ja": "ヤマトシジミ", "count": "2", "out_of_time": "時間外",
         "source_id": "moni1000_satochi_butterfly", "source_ref": SRC + " (SAT07)"}])
    write(d / "moni1000_satochi_butterfly_sites_kanagawa.csv", SITES, [
        {"site_id": "S065", "site_name_ja": "横浜自然観察の森", "lat": "35.3", "lon": "139.6", "緯度詳細": "非公開", "経度詳細": "非公開"}])
    write(d / "moni1000_forest_bird_kanagawa.csv", FOREST, [
        {"site_id": "100246", "site_type_ja": "一般サイト", "habitat_ja": "森林", "lat": "35.3", "lon": "139.6",
         "prefecture_ja": "神奈川県", "municipality_ja": "横浜市", "survey_period_ja": "2005年度繁殖期", "rep_no": "1.0",
         "survey_year": "2005.0", "survey_month": "5.0", "survey_day": "24.0", "start_hour": "6.0", "start_min": "20.0",
         "end_hour": "6.0", "end_min": "47.0", "species_ja": "スズメ", "scientific_name": "Passer montanus",
         "count": "2", "id_type_ja": "S", "source_id": "moni1000_forest_bird", "source_ref": SRC + " (SIN04)"},
        {"site_id": "100246", "lat": "35.3", "lon": "139.6", "survey_year": "2005.0", "survey_month": "5.0",
         "survey_day": "24.0", "species_ja": "ウグイス", "scientific_name": "Cettia diphone", "count": "－",
         "source_id": "moni1000_forest_bird", "source_ref": SRC + " (SIN04)"},
        {"site_id": "100246", "lat": "35.3", "lon": "139.6", "survey_year": "2005.0", "survey_month": "5.0",
         "survey_day": "24.0", "species_ja": "フクロウ？", "scientific_name": "Strix uralensis", "count": "",
         "source_id": "moni1000_forest_bird", "source_ref": SRC + " (SIN04)"}])
    write(d / "moni1000_satochi_mammal_photo_kanagawa.csv", MAMMAL, [
        {"data_id": "30", "survey_id": "Ma1", "site_id": "S067", "photo_year": "2008", "photo_month": "9.0",
         "photo_day": "12.0", "photo_time": "19:26", "species_ja": "ハクビシン", "count": "1",
         "source_id": "moni1000_satochi_mammal", "source_ref": SRC + " (SAT03)"},
        {"data_id": "31", "survey_id": "Ma1", "site_id": "S067", "photo_year": "2008", "photo_month": "9.0",
         "photo_day": "", "species_ja": "ハクビシン", "count": "1",
         "source_id": "moni1000_satochi_mammal", "source_ref": SRC + " (SAT03)"},
        {"data_id": "32", "survey_id": "Ma1", "site_id": "S067", "photo_year": "2008", "photo_month": "",
         "photo_day": "", "species_ja": "ハクビシン", "count": "1",
         "source_id": "moni1000_satochi_mammal", "source_ref": SRC + " (SAT03)"}])
    write(d / "moni1000_satochi_mammal_sites_kanagawa.csv", MAMMAL_SITES, [
        {"site_id": "S067", "site_name_ja": "生田緑地", "lat": "35.6104", "lon": "139.5577"}])
    write(d / "moni1000_coast_shorebird_kanagawa.csv", SHORE, [
        {"survey_year_raw": "2004/05", "season_ja": "Spring(Apr-May)", "site_code": "130700", "site_name_ja": "多摩川河口",
         "lat": "35.5391", "lon": "139.76800000000003", "year": "2004", "month": "4", "day": "24", "start_time": "13:15",
         "end_time": "14:20", "species_ja": "ダイゼン", "species_en": "Grey Plover",
         "scientific_name": "Pluvialis squatarola", "count": "1", "source_id": "moni1000_coast_shorebird",
         "source_ref": SRC + " (SIG02)"}])

    site_map = tmp_path / "site_map.csv"
    write(site_map, ["source_id", "site_key", "site_name_ja", "place_id", "basis"], [
        {"source_id": "moni1000_satochi_bird", "site_key": "S064", "site_name_ja": "瀬上の森",
         "place_id": "jp-14:place:site.moni1000.kn353613958", "basis": "name"},
        {"source_id": "moni1000_satochi_butterfly", "site_key": "S065", "site_name_ja": "横浜自然観察の森",
         "place_id": "jp-14:place:site.moni1000.kn353413959", "basis": "name"},
        {"source_id": "moni1000_forest_bird", "site_key": "100246", "site_name_ja": "横浜市（サイト100246）",
         "place_id": "", "basis": "none"},
        {"source_id": "moni1000_satochi_mammal", "site_key": "S067", "site_name_ja": "生田緑地", "place_id": "",
         "basis": "none"},
        {"source_id": "moni1000_coast_shorebird", "site_key": "130700", "site_name_ja": "多摩川河口",
         "place_id": "jp-14:place:site.moni1000.kn355413976", "basis": "name"}])

    def nm(src, key, ja, sci, tid, basis):
        return {"source_id": src, "name_key": key, "species_ja": ja, "scientific_name": sci, "taxon_id": tid,
                "basis": basis, "note": ""}
    name_map = tmp_path / "name_map.csv"
    b, bt, f, ma, sh = ("moni1000_satochi_bird", "moni1000_satochi_butterfly", "moni1000_forest_bird",
                        "moni1000_satochi_mammal", "moni1000_coast_shorebird")
    write(name_map, ["source_id", "name_key", "species_ja", "scientific_name", "taxon_id", "basis", "note"], [
        nm(b, "ヒヨドリ", "ヒヨドリ", "", "T:hiyodori", "ja_unique"), nm(b, "スズメ", "スズメ", "", "T:suzume", "ja_unique"),
        nm(b, "カラス科", "カラス科", "", "", "exclude:non_species"), nm(b, "ウコッケイ", "ウコッケイ", "", "", "exclude:non_wild"),
        nm(b, "ツミ", "ツミ", "", "", "exclude:unresolved_taxon"), nm(b, "メジロ", "メジロ", "", "T:mejiro", "ja_unique"),
        nm(bt, "ヤマトシジミ", "ヤマトシジミ", "", "T:yamato", "curated"),
        nm(f, "スズメ|Passer montanus", "スズメ", "Passer montanus", "T:suzume", "sci"),
        nm(f, "ウグイス|Cettia diphone", "ウグイス", "Cettia diphone", "T:uguisu", "sci"),
        nm(f, "フクロウ?|Strix uralensis", "フクロウ？", "Strix uralensis", "T:fukuro", "sci"),
        nm(ma, "ハクビシン", "ハクビシン", "", "T:hakubishin", "ja_unique"),
        nm(sh, "ダイゼン|Pluvialis squatarola", "ダイゼン", "Pluvialis squatarola", "T:daizen", "sci")])
    return d, site_map, name_map


def build(inputs):
    d, site_map, name_map = inputs
    by = m10.normalize_all(d)
    counts = {k: len(v) for k, v in by.items()}
    recs = m10.resolve([r for v in by.values() for r in v], m10.load_name_map(name_map), m10.load_site_map(site_map))
    return recs, counts


def by_id(recs, rid):
    return next(r for r in recs if r["record_id"] == rid)


def test_row_counts_and_ids(inputs):
    recs, counts = build(inputs)
    assert counts == {"moni1000_satochi_bird": 6, "moni1000_satochi_butterfly": 1, "moni1000_forest_bird": 3,
                      "moni1000_satochi_mammal": 3, "moni1000_coast_shorebird": 1}
    assert by_id(recs, "moni1000_satochi_bird:10")
    assert by_id(recs, "moni1000_forest_bird:r000002")          # data_id の無い出典は CSV の行順
    assert by_id(recs, "moni1000_coast_shorebird:r000001")


def test_exclusions_never_drop_rows(inputs):
    recs, _ = build(inputs)
    reasons = {r["record_id"]: r["exclude_reason"] for r in recs if r["source_id"] == "moni1000_satochi_bird"}
    assert reasons == {"moni1000_satochi_bird:10": None, "moni1000_satochi_bird:11": "zero_count",
                       "moni1000_satochi_bird:12": "non_species", "moni1000_satochi_bird:13": "non_wild",
                       "moni1000_satochi_bird:14": "unresolved_taxon", "moni1000_satochi_bird:15": None}
    sp = by_id(recs, "moni1000_satochi_bird:11")
    assert sp["taxon_id"] == "T:suzume" and sp["in_occurrence"] == 0       # 0 でも名寄せの結果は残す
    assert by_id(recs, "moni1000_satochi_bird:12")["taxon_resolution"] == "non_taxon"
    assert by_id(recs, "moni1000_satochi_bird:14")["taxon_resolution"] == "unresolved"
    assert by_id(recs, "moni1000_satochi_bird:15")["id_note_ja"] == "sp."   # sp. でも入れる。注記は残る


def test_bird_fields(inputs):
    r = by_id(build(inputs)[0], "moni1000_satochi_bird:10")
    assert (r["observed_on"], r["survey_year"], r["survey_month"], r["survey_day"]) == ("2009-02", 2009, 2, None)
    assert (r["individual_count"], r["individual_count_raw"], r["count_qualifier"]) == (3.0, "3.0", "+")
    assert (r["out_of_range"], r["out_of_time"]) == (1, 0)
    assert (r["survey_round"], r["section_ja"], r["season_ja"]) == ("5", "A", "越冬期")
    assert json.loads(r["extra_json"]) == {"id_visual": "○"}
    assert r["place_id"] == "jp-14:place:site.moni1000.kn353613958" and r["site_name_ja"] == "瀬上の森"
    # 詳細座標が非公開の地点は 0.1 度丸めの値を、そのまま（補完・ぼかしをせず）持つ
    assert (r["lat"], r["lon"], r["lat_lon_basis"], r["coord_decimals"]) == (35.4, 139.6, "site_table", 1)


def test_butterfly_and_site_detail_coord(inputs):
    r = by_id(build(inputs)[0], "moni1000_satochi_butterfly:20")
    assert r["observed_on"] == "2008-09-06" and (r["out_of_range"], r["out_of_time"]) == (0, 1)
    assert (r["lat"], r["lon"], r["coord_decimals"]) == (35.3, 139.6, 1)    # 蝶の S065 は詳細が非公開


def test_forest_fields(inputs):
    recs, _ = build(inputs)
    r = by_id(recs, "moni1000_forest_bird:r000001")
    assert r["observed_on"] == "2005-05-24" and (r["start_time"], r["end_time"]) == ("06:20", "06:47")
    assert r["survey_round"] == "1" and r["lat_lon_basis"] == "row" and r["place_id"] is None
    assert json.loads(r["extra_json"])["site_type_ja"] == "一般サイト"
    # 個体数が '－' の行は入れる。数は NULL、原文は残る
    u = by_id(recs, "moni1000_forest_bird:r000002")
    assert (u["individual_count"], u["individual_count_raw"], u["in_occurrence"]) == (None, "－", 1)
    # 末尾の ？ は id_note_ja に '?' として残る
    f = by_id(recs, "moni1000_forest_bird:r000003")
    assert f["id_note_ja"] == "?" and f["individual_count_raw"] is None and f["taxon_id"] == "T:fukuro"


def test_mammal_partial_dates_not_filled(inputs):
    recs, _ = build(inputs)
    assert by_id(recs, "moni1000_satochi_mammal:30")["observed_on"] == "2008-09-12"
    assert by_id(recs, "moni1000_satochi_mammal:30")["start_time"] == "19:26"
    assert by_id(recs, "moni1000_satochi_mammal:31")["observed_on"] == "2008-09"
    assert by_id(recs, "moni1000_satochi_mammal:32")["observed_on"] == "2008"
    assert by_id(recs, "moni1000_satochi_mammal:30")["lat"] == 35.6104


def test_shorebird_float_artifact_coordinate(inputs):
    r = by_id(build(inputs)[0], "moni1000_coast_shorebird:r000001")
    assert (r["lat"], r["lon"], r["coord_decimals"]) == (35.5391, 139.768, 3)
    assert (r["start_time"], r["end_time"]) == ("13:15", "14:20")
    assert json.loads(r["extra_json"])["survey_year_raw"] == "2004/05"


def test_unmapped_name_or_site_stops(inputs, tmp_path):
    d, site_map, name_map = inputs
    rows = [r for r in csv.DictReader(open(name_map, encoding="utf-8")) if r["name_key"] != "ヒヨドリ"]
    short = tmp_path / "short.csv"
    write(short, list(rows[0]), rows)
    by = m10.normalize_all(d)
    allr = [r for v in by.values() for r in v]
    with pytest.raises(m10.M10Error, match="名寄せ表に無い語"):
        m10.resolve(allr, m10.load_name_map(short), m10.load_site_map(site_map))
    rows = [r for r in csv.DictReader(open(site_map, encoding="utf-8")) if r["site_key"] != "S064"]
    short2 = tmp_path / "short2.csv"
    write(short2, list(rows[0]), rows)
    with pytest.raises(m10.M10Error, match="地点対応表に無い地点"):
        m10.resolve(allr, m10.load_name_map(name_map), m10.load_site_map(short2))


def registry_db(tmp_path):
    db = tmp_path / "ryuiki.sqlite"
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT,
        category TEXT, access_method TEXT, format TEXT, license TEXT, redistributable INTEGER, fetched_at TEXT,
        record_count INTEGER, notes TEXT)""")
    con.execute("CREATE TABLE other_table (x INTEGER)")
    con.execute("INSERT INTO other_table VALUES (1)")
    for sid in m10.SOURCES:
        con.execute("INSERT INTO source_registry (source_id, redistributable, notes) VALUES (?,0,'【隔離 2026-08-29】x')", (sid,))
    con.commit()
    return con


def test_load_is_idempotent_and_releases_quarantine(inputs, tmp_path):
    recs, counts = build(inputs)
    con = registry_db(tmp_path)
    assert m10.load(con, recs, counts) == {"rows": 14, "released": 5}
    m10.load(con, recs, counts)                                   # 2 回目も同じ（二重にならない）
    assert con.execute("SELECT COUNT(*) FROM moni1000_counts").fetchone()[0] == 14
    assert con.execute("SELECT COUNT(*) FROM moni1000_counts WHERE in_occurrence=1").fetchone()[0] == 10
    assert con.execute("SELECT COUNT(*) FROM other_table").fetchone()[0] == 1          # 他の表に触らない
    rows = con.execute("SELECT redistributable, notes FROM source_registry").fetchall()
    assert all(r[0] == 1 for r in rows)
    assert all(r[1].startswith("【隔離 2026-08-29】x") and r[1].count(m10.REGISTRY_NOTE_MARK) == 1 for r in rows)


def test_load_wipes_only_own_sources(inputs, tmp_path):
    recs, counts = build(inputs)
    con = registry_db(tmp_path)
    m10.load(con, recs, counts)
    con.execute("INSERT INTO moni1000_counts (record_id, source_id, site_key, in_occurrence) VALUES ('x:1','other',"
                "'k',1)")
    m10.load(con, recs, counts)
    assert con.execute("SELECT COUNT(*) FROM moni1000_counts WHERE source_id='other'").fetchone()[0] == 1


def test_checks_stop_on_inconsistency(inputs, tmp_path):
    recs, counts = build(inputs)
    con = registry_db(tmp_path)
    bad = [dict(r) for r in recs]
    bad[0]["taxon_id"] = None                                      # in_occurrence=1 で taxon_id が無い
    with pytest.raises(m10.M10Error, match="taxon_id が NULL"):
        m10.load(con, bad, counts)
    bad = [dict(r) for r in recs]
    bad[1]["exclude_reason"] = "bogus"
    with pytest.raises(m10.M10Error, match="exclude_reason"):
        m10.load(con, bad, counts)
    with pytest.raises(m10.M10Error, match="行数が CSV と違う"):
        m10.load(con, recs[:-1], counts)
    bad = [dict(r) for r in recs]
    bad[0]["observed_on"] = "2009/02"
    with pytest.raises(m10.M10Error, match="正規形"):
        m10.load(con, bad, counts)


def test_summarize(inputs):
    s = m10.summarize(build(inputs)[0])
    b = s["moni1000_satochi_bird"]
    assert b["input_rows"] == 6 and b["in_occurrence_1"] == 2
    assert b["exclude_reason"] == {"zero_count": 1, "non_species": 1, "non_wild": 1, "unresolved_taxon": 1}
    assert s["moni1000_satochi_mammal"]["observed_on_shape"] == {"day": 1, "month": 1, "year": 1}


def test_dry_run_does_not_touch_db(inputs, capsys):
    d, site_map, name_map = inputs
    m10.main(["--dry-run", "--csv-dir", str(d), "--site-map", str(site_map), "--name-map", str(name_map)])
    assert "TOTAL 14" in capsys.readouterr().out
