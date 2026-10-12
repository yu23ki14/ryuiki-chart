"""モニ1000 サンゴ礁調査（奄美）: 抽出（process_moni1000_coral）と表への投入（m11_moni1000_coral）のテスト。小さな合成行で通す。"""
import datetime
import sqlite3

import pytest

import m11_moni1000_coral as m11
import process_moni1000_coral as pc

BASE_HEAD = ["中ブロック", "サイトNo.", "サイト名", "県名", "調査地(spot)No.", "地名", "北緯(度）", "北緯(分）", "北緯(秒）",
             "東経（度)", "東経(分）", "東経(秒）", "地形", "底質", "観察範囲(m)", "水深範囲(m）"]


def base(block, site, spot, lat, lon, name="地点"):
    return [block, site, "サイト", "鹿児島県", spot, name, *lat, *lon, "礁原", "サンゴ岩", "50×50", "1～3"]


def result(block, site, spot, year, over=None):
    r = [None] * 33
    r[0], r[1], r[2], r[3], r[4], r[5] = year, block, site, "サイト", spot, "地点"
    r[6], r[7], r[8], r[9] = datetime.datetime(year, 12, 1), "興　克樹 ", "Skin", 15
    r[10], r[11], r[12], r[17], r[19], r[21], r[28], r[31], r[32] = "<5", 0, "<5", 3, 0, "20-30", "-", "有", "メモ"
    for k, v in (over or {}).items():
        r[k] = v
    return r


AMAMI = (["28", "28", 15.9], ["129", "38", 53.3])
TOKUNO = (["27", "50", 0], ["128", "55", 0])


def build():
    b = [base("奄美群島", 3, 1, *AMAMI), base("奄美群島", 3, 2, *AMAMI), base("奄美群島", 4, 1, *TOKUNO),
         base("沖縄島西岸", 1, 1, *AMAMI)]
    r = [result("奄美群島", 3, 1, 2004), result("奄美群島", 3, 1, 2005, {10: 20}), result("奄美群島", 3, 2, 2004),
         result("奄美群島", 4, 1, 2004), result("沖縄島西岸", 1, 1, 2004)]
    return pc.build_rows(b, r)


def test_dms_to_decimal_degrees():
    assert pc.dms_to_deg(28, 28, 15.9) == pytest.approx(28.4710833, abs=1e-7)
    assert pc.dms_to_deg(129, 38, 53.3) == pytest.approx(129.6481389, abs=1e-7)
    assert pc.dms_to_deg(None, 1, 1) is None
    with pytest.raises(pc.CoralError):
        pc.dms_to_deg(28, 61, 0)
    assert pc.dms_text(28, 28, 15.9) == "28°28′15.9″"


def test_numbers_are_only_converted_when_plain():
    assert pc.to_number("20") == 20.0 and pc.to_number("0.5") == 0.5
    for raw in ("<5", "<1", "-", "20-30", "20<", "30>", None, "有"):
        assert pc.to_number(raw) is None


def test_only_amami_island_spots_are_kept_and_the_rest_reported():
    rows, dropped = build()
    assert len(rows) == 3                                  # 奄美群島の他ブロック・他ブロックの行は読まない。徳之島は範囲外
    assert len(dropped) == 1 and "サイト4" in dropped[0]
    assert {r["spot_no"] for r in rows} == {1, 2}


def test_primary_key_unique_and_values_kept_raw():
    rows, _ = build()
    ids = [r["record_id"] for r in rows]
    assert len(set(ids)) == len(ids) and ids[0] == "moni1000_coral_amami:2004:3:1"
    r = rows[0]
    assert (r["cover_pct_raw"], r["cover_pct"]) == ("<5", None)
    assert (rows[1]["cover_pct_raw"], rows[1]["cover_pct"]) == ("20", 20.0)
    assert (r["cots_dominant_size_cm_raw"], r["cots_dominant_size_cm"]) == ("20-30", None)
    assert (r["grouper_n_raw"], r["grouper_n"]) == ("-", None)
    assert (r["bleach_all_pct_raw"], r["bleach_all_pct"]) == ("0", 0.0)
    assert r["observed_on"] == "2004-12-01" and r["investigator_ja"] == "興　克樹"
    assert r["disease"] == "有" and r["lat_dms_raw"] == "28°28′15.9″"


def test_duplicate_key_and_missing_base_stop():
    b = [base("奄美群島", 3, 1, *AMAMI)]
    with pytest.raises(pc.CoralError, match="重複"):
        pc.build_rows(b, [result("奄美群島", 3, 1, 2004), result("奄美群島", 3, 1, 2004)])
    with pytest.raises(pc.CoralError, match="基礎情報に無い"):
        pc.build_rows(b, [result("奄美群島", 3, 9, 2004)])


def db(tmp_path):
    con = sqlite3.connect(tmp_path / "x.sqlite")
    con.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY)")
    con.execute("INSERT INTO source_registry VALUES ('moni1000_coral_amami')")
    con.execute("CREATE TABLE other (x INTEGER)")
    con.commit()
    return con


def test_load_preserves_row_count_and_is_idempotent(tmp_path):
    rows, _ = build()
    con = db(tmp_path)
    assert m11.load(con, rows) == {"rows": 3}
    m11.load(con, rows)
    assert con.execute("SELECT COUNT(*) FROM moni1000_coral_spots").fetchone()[0] == 3
    assert con.execute("SELECT cover_pct_raw, cover_pct FROM moni1000_coral_spots ORDER BY record_id").fetchall()[0] == ("<5", None)


def test_load_stops_on_inconsistency(tmp_path):
    rows, _ = build()
    con = db(tmp_path)
    dup = [dict(r) for r in rows] + [dict(rows[0])]
    with pytest.raises(m11.M11Error, match="一意"):
        m11.load(con, dup)
    bad = [dict(r) for r in rows]
    bad[0].pop("note_ja")
    with pytest.raises(m11.M11Error, match="列が DDL と合わない"):
        m11.load(con, bad)
    con2 = sqlite3.connect(tmp_path / "y.sqlite")
    con2.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY)")
    with pytest.raises(m11.M11Error, match="source_registry"):
        m11.load(con2, rows)


def test_csv_columns_match_ddl():
    ddl_cols = [l.split()[0] for l in m11.SCHEMA.read_text(encoding="utf-8").splitlines() if l.startswith("  ")]
    assert ddl_cols == pc.FIELDS
