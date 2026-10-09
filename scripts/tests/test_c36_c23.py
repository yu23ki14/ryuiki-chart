"""c36（C23 海岸線）の絞り込みのテスト。小さな shapefile を作って読む（ネットワークに出ない）。"""
import pytest

pytest.importorskip("shapely")
pytest.importorskip("pyproj")
shapefile = pytest.importorskip("shapefile")

import c36_nlni_c23_coastline as c36  # noqa: E402

FIELDS = ["C23_001", "C23_002", "C23_003", "C23_004", "C23_005", "C23_006", "C23_007"]


def write_shp(path, lines):
    w = shapefile.Writer(str(path), shapeType=shapefile.POLYLINE, encoding="cp932")
    for f in FIELDS:
        w.field(f, "C", size=20)
    for code, pts in lines:
        w.line([pts])
        w.record(code, "6", "", "", "", "", "false")
    w.close()


LINES = [("46222", [(129.4, 28.3), (129.5, 28.4)]), ("46525", [(129.3, 28.1), (129.4, 28.2)]),
         ("46201", [(130.5, 31.5), (130.6, 31.6)]), ("46527", [(129.5, 28.4), (129.6, 28.45)])]


def test_select():
    assert c36.select("46222", c36.KAGOSHIMA_AMAMI_CODES)
    assert not c36.select("46201", c36.KAGOSHIMA_AMAMI_CODES)
    assert c36.select("14201", None)
    assert c36.PREF_CODES["14"] is None and c36.PREF_CODES["46"] == c36.KAGOSHIMA_AMAMI_CODES


def test_kagoshima_keeps_only_amami_municipalities(tmp_path):
    shp = tmp_path / "c.shp"
    write_shp(shp, LINES)
    feats, rows = c36.features_of("46", shp, c36.KAGOSHIMA_AMAMI_CODES)
    assert sorted(r["admin_code"] for r in rows) == ["46222", "46525", "46527"]
    assert len(feats) == 3
    f = feats[0]
    assert f["geometry"]["type"] in ("LineString", "MultiLineString")
    p = f["properties"]
    assert p["source_id"] == "nlni_c23_coastline" and p["prefecture_code"] == "46" and p["prefecture_name_ja"] == "鹿児島県"
    assert p["length_km"] > 0 and p["data_year"] == 2006


def test_kanagawa_keeps_all_lines(tmp_path):
    shp = tmp_path / "k.shp"
    write_shp(shp, [("14201", [(139.4, 35.3), (139.5, 35.35)]), ("14131", [(139.6, 35.4), (139.7, 35.5)])])
    feats, rows = c36.features_of("14", shp, None)
    assert len(rows) == 2 and {r["prefecture_code"] for r in rows} == {"14"}
