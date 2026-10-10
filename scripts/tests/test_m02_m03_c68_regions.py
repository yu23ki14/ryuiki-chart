"""m02（時系列・水質）・m03（出現）・c68（地点の地域）の地域対応（AMAMI_STEP1B §2.1）。一時ディレクトリ・一時 sqlite だけ。"""
import collections
import json
import pathlib
import sqlite3

import pytest

import m02_measurements as m02
import m03_organisms as m03

SCRIPTS = pathlib.Path(m02.__file__).parent


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def proc(tmp_path, monkeypatch):
    monkeypatch.setattr(m02, "PROC", tmp_path)
    monkeypatch.setattr(m03, "PROC", tmp_path)
    return tmp_path


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript((SCRIPTS / "schema_app.sql").read_text(encoding="utf-8"))
    return c


def ts_row(**kw):
    r = {"datetime": "2024-01", "variable": "v", "value": 1.0, "unit": "u"}
    r.update(kw)
    return r


def test_sensor_site_ids_station_and_sea_area(proc, conn):
    jl(proc / "jma_daily_yokohama.jsonl", [ts_row(station_id="jma_46106", source_id="jma_daily_yokohama")])
    jl(proc / "jma_daily_nase.jsonl", [ts_row(station_id="jma_47909", source_id="jma_daily_nase")])
    jl(proc / "jma_sst_amami.jsonl", [ts_row(area_code=617, variable_ja="海域平均海面水温", source_id="jma_sst_amami")])
    for n in ("jma_monthly_kanagawa", "soramame_hourly_kanagawa", "sagamihara_taiki_hourly"):
        jl(proc / f"{n}.jsonl", [])
    m02.load_sensor_timeseries(conn)    # 奄美の月別・そらまめ君の jsonl は無い -> 飛ばす
    got = {r[0]: r[1:] for r in conn.execute("SELECT site_id, datastream, source_id FROM sensor_timeseries")}
    assert got == {
        "jma_stations_kanagawa__jma_46106": ("v", "jma_daily_yokohama"),       # 神奈川は変わらない
        "jma_stations_amami__jma_47909": ("v", "jma_daily_nase"),
        "jma_sst_amami__617": ("海域平均海面水温", "jma_sst_amami"),
    }


def test_kanagawa_sensor_file_missing_still_stops(proc, conn):
    with pytest.raises(FileNotFoundError):
        m02.load_sensor_timeseries(conn)


def kousui_annual(station, src, year=2020):
    return {"station_id": station, "fiscal_year": year, "variable": "ph", "variable_ja": "pH", "value": 7.0,
            "value_raw": "7.0", "unit": None, "quality_flag": None, "source_ref": "ref", "source_id": src}


def kousui_sample(station, src):
    return {"station_id": station, "datetime": "2020-05-01T10:00:00", "variable": "water_temp", "variable_ja": "水温",
            "value": 20.0, "value_raw": "20", "unit": "℃", "quality_flag": None, "source_ref": "ref"}


def test_kousui_delete_is_per_region(proc, conn):
    jl(proc / "env_kousui_annual_kanagawa.jsonl", [kousui_annual("kousui_1400001", "env_kousui_annual_kanagawa")])
    jl(proc / "env_kousui_annual_amami.jsonl", [kousui_annual("kousui_4600001", "env_kousui_annual_amami")])
    jl(proc / "env_kousui_sample_kanagawa.jsonl", [kousui_sample("kousui_1400001", None)])
    jl(proc / "env_kousui_sample_amami.jsonl", [kousui_sample("kousui_4600001", None)])
    for rid in ("jp-14", "jp-46"):
        m02.load_env_kousui_annual(conn, rid)
        m02.load_env_kousui_sample(conn, rid)
    q = "SELECT source_id, site_id, count(*) FROM measurements GROUP BY 1, 2 ORDER BY 1"
    assert conn.execute(q).fetchall() == [
        ("env_kousui_annual_amami", "env_kousui_stations_amami__kousui_4600001", 1),
        ("env_kousui_annual_kanagawa", "env_kousui_stations_kanagawa__kousui_1400001", 1),
        ("env_kousui_sample_amami", "env_kousui_stations_amami__kousui_4600001", 1),
        ("env_kousui_sample_kanagawa", "env_kousui_stations_kanagawa__kousui_1400001", 1),
    ]
    # 奄美だけ入れ直しても神奈川の行は消えない。奄美の旧行は置き換わる
    jl(proc / "env_kousui_annual_amami.jsonl", [kousui_annual("kousui_4600002", "env_kousui_annual_amami")])
    m02.load_env_kousui_annual(conn, "jp-46")
    assert dict(conn.execute("SELECT source_id, count(*) FROM measurements GROUP BY 1"))["env_kousui_annual_kanagawa"] == 1
    assert [r[0] for r in conn.execute(
        "SELECT site_id FROM measurements WHERE source_id='env_kousui_annual_amami'")] == [
        "env_kousui_stations_amami__kousui_4600002"]
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_m03_record_id_prefix_per_region(proc, conn):
    jl(proc / "inaturalist_kanagawa.jsonl", [{"id": 1, "scientific_name": "A a", "lat": 35.4, "lon": 139.3}])
    jl(proc / "inaturalist_amami.jsonl", [{"id": 2, "scientific_name": "B b", "lat": 28.4, "lon": 129.5}])
    jl(proc / "gbif_kanagawa_occurrences.jsonl", [{"key": 3, "scientificName": "A a", "occurrenceStatus": "PRESENT"}])
    jl(proc / "gbif_amami_occurrences.jsonl", [{"key": 4, "scientificName": "B b", "occurrenceStatus": "ABSENT"}])
    counter = collections.Counter()
    for rid in ("jp-14", "jp-46"):
        m03.load_inaturalist(conn, {}, counter, rid)
        m03.load_gbif(conn, {}, counter, rid)
    assert dict(conn.execute("SELECT record_id, source_id FROM organism_records")) == {
        "inaturalist_kanagawa__1": "inaturalist_kanagawa",
        "inaturalist_amami__2": "inaturalist_amami",
        "gbif_kanagawa_occurrences__3": "gbif_kanagawa_occurrences",
        "gbif_amami_occurrences__4": "gbif_amami_occurrences",
    }
    # backfill も地域ごと
    conn.execute("UPDATE organism_records SET occurrence_status=NULL")
    _, n, changed, _ = m03.backfill_occurrence_status(conn, rid="jp-46")
    assert (n, changed) == (1, 1)
    assert dict(conn.execute("SELECT record_id, occurrence_status FROM organism_records WHERE occurrence_status IS NOT NULL")) \
        == {"gbif_amami_occurrences__4": "ABSENT"}


def test_c68_region_of_source_without_manifest(tmp_path):
    pytest.importorskip("numpy")
    pytest.importorskip("PIL.Image")
    pytest.importorskip("shapely")
    import c68_gsi_dem_terrain as c68
    (tmp_path / "jma_stations_amami.yml").write_text("region: jp-14\n", encoding="utf-8")   # マニフェストが優先
    assert c68.region_of_source("jma_stations_amami", "jp-14", tmp_path) == "jp-14"
    assert c68.region_of_source("env_kousui_stations_amami", "jp-14", tmp_path) == "jp-46"
    assert c68.region_of_source("env_kousui_stations_kanagawa", "jp-14", tmp_path) == "jp-14"
    assert c68.region_of_source("moni1000_sites", "jp-14", tmp_path) == "jp-14"            # 引けなければ既定
