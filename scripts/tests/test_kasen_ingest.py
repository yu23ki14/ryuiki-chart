"""鹿児島県 河川砂防情報システム（奄美 Step 2b）の取り込み側（regions・m02・build_place の名前空間・r03）。一時ディレクトリだけ。"""
import json
import pathlib
import sqlite3

import pytest

import m02_measurements as m02
import regions
import r03_site_supplement as r03
from registry import build_place

SCRIPTS = pathlib.Path(m02.__file__).parent
SRC = "kagoshima_kasen_stations_amami"


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def row(station_id, source_id, variable_ja, **kw):
    r = {"station_id": station_id, "datetime": "2024-01-02", "variable": "v", "variable_ja": variable_ja,
         "value": 12, "unit": "cm", "source_id": source_id, "source_ref": "u"}
    r.update(kw)
    return r


def test_regions_declarations():
    r = regions.get("jp-46")
    assert r["station_tables"] == (SRC,)
    assert r["station_series"] == tuple(f"kagoshima_kasen_{k}_amami" for k in ("suii", "suii_kiki", "choui", "dam"))
    assert "station_tables" not in regions.get("jp-14")
    assert regions.site_scope(SRC) == "jp-46"
    assert regions.region_of_source_id("kagoshima_kasen_dam_amami") == "jp-46"


def test_m02_sources_and_missing_files_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(m02, "PROC", tmp_path)
    got = {n: (s, opt) for n, s, opt in m02._sensor_sources()}
    for n in regions.get("jp-46")["station_series"]:
        assert got[n] == (SRC, True)          # 局の表と同じ接頭辞・欠けても飛ばす

    for n in ("jma_daily_yokohama", "jma_monthly_kanagawa", "soramame_hourly_kanagawa", "sagamihara_taiki_hourly"):
        jl(tmp_path / f"{n}.jsonl", [])
    jl(tmp_path / "kagoshima_kasen_suii_amami.jsonl",
       [row("suii_kiki_139", "kagoshima_kasen_suii_amami", "水位_日最高_cm")])
    jl(tmp_path / "kagoshima_kasen_choui_amami.jsonl",
       [row("choui_4", "kagoshima_kasen_choui_amami", "潮位_日平均")])
    # dam の jsonl は無い -> 飛ばす
    conn = sqlite3.connect(":memory:")
    conn.executescript((SCRIPTS / "schema_app.sql").read_text(encoding="utf-8"))
    m02.load_sensor_timeseries(conn)
    assert sorted(conn.execute("SELECT site_id, datastream, source_id FROM sensor_timeseries")) == [
        (f"{SRC}__choui_4", "潮位_日平均", "kagoshima_kasen_choui_amami"),
        (f"{SRC}__suii_kiki_139", "水位_日最高_cm", "kagoshima_kasen_suii_amami"),
    ]


def test_place_id_for_kasen_site():
    assert build_place._site_place_id(f"{SRC}__suii_kiki_139") == "jp-46:place:site.kasen.suii_kiki_139"


STATIONS = [
    {"station_id": "suii_kiki_139", "station_name_ja": "第2屋仁橋", "lat": 28.4, "lon": 129.5, "source_ref": "https://x/a"},
    {"station_id": "suii_kiki_144", "station_name_ja": "朝戸橋", "lat": None, "lon": None, "source_ref": "https://x/a"},
    {"station_id": "choui_4", "station_name_ja": "名瀬", "source_ref": ""},
]


def test_supplement_lines_only_for_stations_without_coordinates():
    lines = r03.supplement_lines(SRC, STATIONS)
    assert [l.split(",")[0] for l in lines] == [f"{SRC}__suii_kiki_144", f"{SRC}__choui_4"]
    assert all(",,," in l or l.endswith(",") for l in lines)   # lat/lon は空のまま（推測しない）


def test_supplement_merge_is_idempotent_and_keeps_crlf_and_other_rows():
    text = "site_id,name_ja,lat,lon,definition_ref,place_local\r\nother__1,a,,,ref,\r\n"
    once = r03.merge(text, SRC, r03.supplement_lines(SRC, STATIONS))
    twice = r03.merge(once, SRC, r03.supplement_lines(SRC, STATIONS))
    assert once == twice
    assert "\r\n" in once and "\n" not in once.replace("\r\n", "")
    assert once.startswith(text)
    # 局が減れば、その出典の古い行は消える
    assert SRC not in r03.merge(once, SRC, [])


def test_r03_cli_writes_and_checks(tmp_path):
    jl(tmp_path / f"{SRC}.jsonl", STATIONS)
    csvp = tmp_path / "s.csv"
    csvp.write_text("site_id,name_ja,lat,lon,definition_ref,place_local\n", encoding="utf-8")
    args = ["--source", SRC, "--proc", str(tmp_path), "--csv", str(csvp)]
    assert r03.main(args + ["--check"]) == 1
    assert r03.main(args) == 0
    assert r03.main(args + ["--check"]) == 0
    assert csvp.read_text(encoding="utf-8").count(f"{SRC}__") == 2
    # 局の表が無ければ何もしない
    assert r03.main(["--source", SRC, "--proc", str(tmp_path / "none"), "--csv", str(csvp)]) == 0
