"""m01（sites）・m05（植生）の地域対応（AMAMI_STEP1B §2.1）。一時ディレクトリの jsonl/geojson/csv と一時 sqlite だけで動く。

- jp-14 だけの入力は、変更前と同じ行（site_id・source_id・流域）になる。
- 奄美の入力は、奄美の W12 に入れば流域が付き、外は NULL になる。
"""
import json
import pathlib
import sqlite3

import pytest

pytest.importorskip("shapely")

import m01_sites  # noqa: E402
import m05_tier1  # noqa: E402

SCRIPTS = pathlib.Path(m01_sites.__file__).parent


def square(lon, lat, d=0.05):
    return {"type": "Polygon", "coordinates": [[[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                                                 [lon - d, lat + d], [lon - d, lat - d]]]}


def w12(path, wid, lon, lat):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"watershed_id": wid}, "geometry": square(lon, lat)}]}),
        encoding="utf-8")


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def jma(sid, name, lat, lon, ref):
    return {"station_id": sid, "station_name_ja": name, "station_name_en": None, "lat": lat, "lon": lon,
            "elevation_m": 5, "prefecture_ja": "X", "source_ref": ref}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "ryuiki.sqlite"
    con = sqlite3.connect(db)
    con.executescript((SCRIPTS / "schema_app.sql").read_text(encoding="utf-8")
                      + (SCRIPTS / "schema_tier1.sql").read_text(encoding="utf-8"))
    con.commit(); con.close()
    for mod in (m01_sites, m05_tier1):
        monkeypatch.setattr(mod, "PROC", tmp_path)
        monkeypatch.setattr(mod, "appdb", lambda: sqlite3.connect(db))
    monkeypatch.setattr(m01_sites, "ELEV_CACHE_PATH", tmp_path / "_elev.json")
    monkeypatch.setattr(m01_sites, "fetch_elevation", lambda *a, **k: None)
    return tmp_path, db


def sites(db):
    con = sqlite3.connect(db)
    return {r[0]: r[1:] for r in con.execute("SELECT site_id, watershed, source_id, lat, lon FROM sites")}


def test_jp14_only_input_gives_same_rows(env):
    proc, db = env
    w12(proc / "nlni_w12_watersheds.geojson", "K1", 139.3, 35.4)
    jl(proc / "jma_stations_kanagawa.jsonl", [jma("jma_1", "横浜", 35.4, 139.3, "r1")])
    m01_sites.main()
    assert sites(db) == {"jma_stations_kanagawa__jma_1": ("K1", "jma_stations_kanagawa", 35.4, 139.3)}


def test_amami_sites_get_watershed_inside_w12_and_null_outside(env):
    proc, db = env
    w12(proc / "nlni_w12_watersheds.geojson", "K1", 139.3, 35.4)
    w12(proc / "nlni_w12_watersheds_amami.geojson", "A1", 129.5, 28.4)
    jl(proc / "jma_stations_kanagawa.jsonl", [jma("jma_1", "横浜", 35.4, 139.3, "r1")])
    jl(proc / "jma_stations_amami.jsonl", [jma("jma_47909", "名瀬", 28.4, 129.5, "r2"),
                                           jma("jma_x", "W12の外", 28.6, 129.7, "r3")])
    m01_sites.main()
    got = sites(db)
    assert got["jma_stations_kanagawa__jma_1"][0] == "K1"            # 神奈川は変わらない
    assert got["jma_stations_amami__jma_47909"] == ("A1", "jma_stations_amami", 28.4, 129.5)
    assert got["jma_stations_amami__jma_x"][0] is None              # W12 が覆わない所は NULL


def test_amami_files_missing_is_skipped(env):
    proc, db = env
    w12(proc / "nlni_w12_watersheds.geojson", "K1", 139.3, 35.4)
    jl(proc / "jma_stations_kanagawa.jsonl", [jma("jma_1", "横浜", 35.4, 139.3, "r1")])
    m01_sites.main()                       # 奄美の W12 も jsonl も無い
    assert list(sites(db)) == ["jma_stations_kanagawa__jma_1"]


def test_m05_watersheds_concatenates_all_regions(env):
    proc, _ = env
    w12(proc / "nlni_w12_watersheds.geojson", "K1", 139.3, 35.4)
    w12(proc / "nlni_w12_watersheds_amami.geojson", "A1", 129.5, 28.4)
    ws = m05_tier1.Watersheds()
    assert ws.find(139.3, 35.4) == "K1" and ws.find(129.5, 28.4) == "A1" and ws.find(0.0, 0.0) is None


def veg_csv(path, source_id, ids):
    head = ("feature_id,legend_code,legend_name_ja,veg_division_ja,naturalness,naturalness_class_ja,survey_year,"
            "survey_year_raw,block_ja,area_m2,centroid_lat,centroid_lon,geometry_geojson,source_id,source_ref\n")
    path.write_text(head + "".join(f"{i},1,a,b,9,c,2009,2009,8,1.0,28.4,129.5,,{source_id},ref\n" for i in ids),
                    encoding="utf-8")


def test_vegetation_per_region_and_duplicate_feature_id_stops(env):
    proc, db = env
    w12(proc / "nlni_w12_watersheds.geojson", "K1", 139.3, 35.4)
    w12(proc / "nlni_w12_watersheds_amami.geojson", "A1", 129.5, 28.4)
    con = sqlite3.connect(db)
    ws = m05_tier1.Watersheds()
    veg_csv(proc / "biodic_veg2024_kanagawa.csv", "biodic_veg2024_kanagawa", [1, 2])
    veg_csv(proc / "biodic_veg2024_amami.csv", "biodic_veg2024_amami", [3, 4])
    assert "2 行" in m05_tier1.load_vegetation(con, ws, "jp-14")
    assert "2 行" in m05_tier1.load_vegetation(con, ws, "jp-46")
    m05_tier1.load_vegetation(con, ws, "jp-46")      # 再実行は冪等（自分の旧行は衝突に数えない）
    assert dict(con.execute("SELECT source_id, count(*) FROM vegetation_polygons GROUP BY 1")) == {
        "biodic_veg2024_kanagawa": 2, "biodic_veg2024_amami": 2}
    veg_csv(proc / "biodic_veg2024_amami.csv", "biodic_veg2024_amami", [2, 5])   # 神奈川の 2 と衝突
    with pytest.raises(SystemExit, match="衝突"):
        m05_tier1.load_vegetation(con, ws, "jp-46")
    con.rollback()
    veg_csv(proc / "biodic_veg2024_amami.csv", "biodic_veg2024_amami", [5, 5])   # 同じ出典内の重複は従来どおり吸収する
    assert "2 行" in m05_tier1.load_vegetation(con, ws, "jp-46")
    assert con.execute("SELECT count(*) FROM vegetation_polygons WHERE source_id='biodic_veg2024_amami'").fetchone()[0] == 1
    assert m05_tier1.load_vegetation(con, ws, "jp-14").startswith("vegetation_polygons[biodic_veg2024_kanagawa]")
