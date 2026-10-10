"""c68（地形指標）と terrain_lib の単体テスト。合成 PNG だけで動く（ネットワーク・原本・実タイルに出ない）。
CI の requirements.txt に numpy・Pillow・shapely は無い（収集側ツールのテスト）ので、無ければ飛ばす。"""
import io
import json
import math
import sqlite3

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
pytest.importorskip("shapely")

import c68_gsi_dem_terrain as c68  # noqa: E402
import terrain_lib as T  # noqa: E402
from registry import zone_rule  # noqa: E402

TERRAIN = {"dem_tile_zoom": 14, "floor_dem_tile_zoom": 12, "relief_wide_radius_m": 1000,
           "relief_near_radius_m": 250, "lowland_floor_radius_m": 2000}
LON, LAT = 139.0, 35.0


# ---------- 合成タイル ----------
def encode_raw(h):
    """標高 [m]（None は無効）→ (R, G, B)。"""
    if h is None:
        return 128, 0, 0
    v = round(h * 100)
    if v < 0:
        v += 2 ** 24
    return v >> 16, (v >> 8) & 255, v & 255


def png_bytes(base, special, z, tx, ty):
    """base 一面の 256x256 タイル。special = {(z, 全球x, 全球y): 標高 or None} のうちこのタイルの分を上書き。"""
    arr = np.zeros((256, 256, 3), np.uint8)
    arr[:, :] = encode_raw(base)
    for (sz, ix, iy), h in special.items():
        if sz == z and ix // 256 == tx and iy // 256 == ty:
            arr[iy % 256, ix % 256] = encode_raw(h)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def make_store(base14=50.0, base12=40.0, special=None, requested=None):
    special = special or {}

    def loader(z, x, y):
        if requested is not None:
            requested.add((z, x, y))
        return png_bytes(base14 if z == 14 else base12, special, z, x, y)
    return T.TileStore(loader)


def px(lon, lat, z):
    a, b = T.lonlat_to_pixel(lon, lat, z)
    return int(math.floor(a)), int(math.floor(b))


# ---------- terrain_lib ----------
def test_decode_positive_negative_invalid_and_empty():
    arr = np.zeros((256, 256, 3), np.uint8)
    arr[0, 0] = encode_raw(1672.34)
    arr[0, 1] = encode_raw(-5.0)
    arr[0, 2] = (128, 0, 0)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="PNG")
    h = T.decode_dem_png(buf.getvalue())
    assert h[0, 0] == pytest.approx(1672.34, abs=0.005)
    assert h[0, 1] == pytest.approx(-5.0, abs=0.005)
    assert np.isnan(h[0, 2])
    assert h[1, 1] == 0.0
    assert np.isnan(T.decode_dem_png(b"")).all()   # 404 の空ファイル


def test_m_per_px_and_pixel_roundtrip():
    assert T.m_per_px(0.0, 0) == pytest.approx(40075016.686 / 256)
    assert T.m_per_px(60.0, 10) == pytest.approx(T.m_per_px(0.0, 10) / 2)
    p = T.lonlat_to_pixel(LON, LAT, 14)
    lon, lat = T.pixel_to_lonlat(p[0], p[1], 14)
    assert (lon, lat) == pytest.approx((LON, LAT), abs=1e-9)


def test_elevation_is_the_containing_pixel_and_invalid_is_none():
    ix, iy = px(LON, LAT, 14)
    store = make_store(special={(14, ix, iy): 123.45, (14, ix + 1, iy): None})
    assert T.elevation_at(store, LON, LAT, 14) == pytest.approx(123.45, abs=0.005)
    lon2, lat2 = T.pixel_to_lonlat(ix + 1.5, iy + 0.5, 14)
    assert T.elevation_at(store, lon2, lat2, 14) is None


def test_relief_windows_and_invalid_pixels_are_excluded():
    ix, iy = px(LON, LAT, 14)
    mpp = T.m_per_px(LAT, 14)
    near_dx = int(100 / mpp)   # 約100m（250m窓の内側）
    far_dx = int(600 / mpp)    # 約600m（250m窓の外、1km窓の内側）
    special = {(14, ix + near_dx, iy): 80.0, (14, ix - far_dx, iy): 400.0, (14, ix, iy + 3): None}
    store = make_store(special=special)
    e, wide, near, _ = T.point_metrics(store, LON, LAT, TERRAIN)
    assert e == 50.0
    assert wide == pytest.approx(400.0 - 50.0, abs=0.01)   # 無効画素（NaN）は最低にならない
    assert near == pytest.approx(80.0 - 50.0, abs=0.01)


def test_floor_min_uses_the_zoom12_window_within_radius():
    ix, iy = px(LON, LAT, 12)
    mpp = T.m_per_px(LAT, 12)
    inside = int(1500 / mpp)
    outside = int(2600 / mpp)
    store = make_store(special={(12, ix + inside, iy): 12.0, (12, ix - outside, iy): -3.0})
    _, _, _, floor = T.point_metrics(store, LON, LAT, TERRAIN)
    assert floor == pytest.approx(12.0, abs=0.01)


def test_point_on_invalid_pixel_has_no_metrics():
    ix, iy = px(LON, LAT, 14)
    store = make_store(special={(14, ix, iy): None})
    assert T.point_metrics(store, LON, LAT, TERRAIN) == (None, None, None, None)


def test_missing_tile_raises_not_cached():
    store = T.TileStore(lambda z, x, y: None)
    with pytest.raises(T.TileNotCached):
        T.elevation_at(store, LON, LAT, 14)


def test_required_tiles_are_exactly_the_tiles_read():
    requested = set()
    store = make_store(requested=requested)
    T.point_metrics(store, LON, LAT, TERRAIN)
    assert requested == T.required_tiles(LON, LAT, TERRAIN)
    assert {z for z, _, _ in requested} == {12, 14}


def test_coast_distance_local_plane():
    from shapely.geometry import LineString
    line = LineString([(138.9, 35.0), (139.1, 35.0)])
    cd = T.CoastDistance([line])
    assert cd.query(139.0, 35.01) == pytest.approx(0.01 * 110540.0, abs=0.5)
    # 端点の外側では端点までの距離（東西は cos(lat0) で縮む）
    d = cd.query(139.2, 35.0)
    assert d == pytest.approx(0.1 * math.cos(math.radians(35.0)) * 111320.0, rel=0.002)
    with pytest.raises(ValueError):
        T.CoastDistance([])


@pytest.mark.parametrize("declared, ok", [(1673, True), (1692.9, True), (1693.5, False), (1650, False), (1654.0, True)])
def test_summit_check_tolerance(declared, ok):
    ix, iy = px(LON, LAT, 14)
    store = make_store(special={(14, ix + 3, iy): 1673.0})
    summit = {"lat": LAT, "lon": LON, "elevation_m": declared}
    got_ok, hi = T.check_summit(store, summit, 14)
    assert hi == pytest.approx(1673.0, abs=0.005)
    assert got_ok is ok


def test_summit_check_ignores_peak_outside_radius_and_invalid():
    ix, iy = px(LON, LAT, 14)
    far = int(700 / T.m_per_px(LAT, 14))
    store = make_store(special={(14, ix + far, iy): 1673.0})
    ok, hi = T.check_summit(store, {"lat": LAT, "lon": LON, "elevation_m": 1673}, 14)
    assert not ok and hi == pytest.approx(50.0, abs=0.005)


def test_params_digest_is_stable_and_sensitive():
    d = zone_rule.terrain_params_digest(TERRAIN)
    assert len(d) == 12 and int(d, 16) >= 0
    assert d == zone_rule.terrain_params_digest(dict(reversed(list(TERRAIN.items()))))
    changed = dict(TERRAIN, relief_wide_radius_m=500)
    assert zone_rule.terrain_params_digest(changed) != d


def test_check_terrain_rejects_bad_blocks():
    assert zone_rule.check_terrain(dict(TERRAIN)) == TERRAIN
    with pytest.raises(ValueError):
        zone_rule.check_terrain(None)
    bad = dict(TERRAIN)
    del bad["lowland_floor_radius_m"]
    with pytest.raises(ValueError):
        zone_rule.check_terrain(bad)
    with pytest.raises(ValueError):
        zone_rule.check_terrain(dict(TERRAIN, relief_near_radius_m=0))


# ---------- c68 ----------
def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sites (site_id TEXT, lat REAL, lon REAL, elevation_m REAL, source_id TEXT)")
    con.executemany("INSERT INTO sites VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_sites_points_dedupes_filters_and_reads_manifest_region(tmp_path):
    db = tmp_path / "r.sqlite"
    make_db(db, [("a", 35.1, 139.1, 10.0, "s_kanagawa"), ("b", 35.1, 139.1, 11.0, "s_kanagawa"),
                 ("c", 28.3, 129.4, 5.0, "s_amami"), ("d", 35.2, 139.2, None, "s_kanagawa")])
    man = tmp_path / "manifests"
    man.mkdir()
    (man / "s_amami.yml").write_text("region: jp-46\n", encoding="utf-8")
    pts = c68.sites_points(db, "jp-14", man)
    assert sorted((p["lat"], p["lon"], p["region_id"]) for p in pts) == [(28.3, 129.4, "jp-46"), (35.1, 139.1, "jp-14")]
    make_db(tmp_path / "r2.sqlite", [("a", 35.1, 139.1, 1.0, "s_kanagawa"), ("b", 35.1, 139.1, 1.0, "s_amami")])
    with pytest.raises(SystemExit):
        c68.sites_points(tmp_path / "r2.sqlite", "jp-14", man)


def test_sites_points_opens_the_db_read_only(tmp_path):
    db = tmp_path / "r.sqlite"
    make_db(db, [("a", 35.1, 139.1, 10.0, "s")])
    before = db.read_bytes()
    c68.sites_points(db, "jp-14", tmp_path)
    assert db.read_bytes() == before


def write_world(tmp_path, summit_elev=1673.0, declared=1673.0, with_coast=True):
    """合成の標高キャッシュ（必要なタイルを全て書く）と zone/region/coast の入力を用意する。"""
    ix, iy = px(LON, LAT, 14)
    special = {(14, ix + 40, iy + 40): summit_elev}
    cache = tmp_path / "tiles"
    pts = [{"lat": LAT, "lon": LON, "region_id": "jp-14"}]
    summit = {"lat": T.pixel_to_lonlat(ix + 40.5, iy + 40.5, 14)[1], "lon": T.pixel_to_lonlat(ix + 40.5, iy + 40.5, 14)[0],
              "elevation_m": declared, "name_ja": "合成峰"}
    need = T.required_tiles(LON, LAT, TERRAIN) | T.summit_tiles(summit, 14)
    for z, x, y in need:
        p = c68.tile_path(cache, z, x, y)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(png_bytes(50.0 if z == 14 else 40.0, special, z, x, y))
    (tmp_path / "zone.yaml").write_text("terrain:\n" + "".join(f"  {k}: {v}\n" for k, v in TERRAIN.items()), encoding="utf-8")
    (tmp_path / "region.yaml").write_text(
        "jp-14:\n  name_ja: x\n  tz_name: Asia/Tokyo\n  utc_offset: '+09:00'\n  evidence: fixture\n"
        "  terrain:\n    summit: {name_ja: 合成峰, lat: %r, lon: %r, elevation_m: %r}\n"
        % (summit["lat"], summit["lon"], declared), encoding="utf-8")
    coast = tmp_path / "coast.geojson"
    if with_coast:
        coast.write_text(json.dumps({"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "LineString", "coordinates": [[LON - 0.1, LAT - 0.01], [LON + 0.1, LAT - 0.01]]},
            "properties": {"prefecture_code": "14"}}]}), encoding="utf-8")
    db = tmp_path / "r.sqlite"
    make_db(db, [("a", LAT, LON, 50.0, "s")])
    return cache, db


def run_main(tmp_path, cache, db, out, *extra):
    c68.main(["--zone-yaml", str(tmp_path / "zone.yaml"), "--region-yaml", str(tmp_path / "region.yaml"),
              "--coast", str(tmp_path / "coast.geojson"), "--cache", str(cache), "--db", str(db),
              "--out", str(out), "--no-fetch", *extra])


def test_main_writes_deterministic_csv(tmp_path, capsys):
    cache, db = write_world(tmp_path)
    out1, out2 = tmp_path / "o1.csv", tmp_path / "o2.csv"
    run_main(tmp_path, cache, db, out1)
    run_main(tmp_path, cache, db, out2)
    assert out1.read_bytes() == out2.read_bytes()
    lines = out1.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(c68.COLUMNS)
    row = dict(zip(c68.COLUMNS, lines[1].split(",")))
    assert len(lines) == 2
    assert (row["lat"], row["lon"], row["region_id"]) == ("35.000000", "139.000000", "jp-14")
    assert float(row["summit_m"]) == 1673.0
    assert float(row["elevation_m"]) == 50.0
    assert float(row["relief_near_m"]) == 0.0
    assert float(row["coast_dist_m"]) == pytest.approx(0.01 * 110540.0, abs=0.5)
    assert row["params_digest"] == zone_rule.terrain_params_digest(TERRAIN)


def test_main_stops_without_coast_geojson(tmp_path):
    cache, db = write_world(tmp_path, with_coast=False)
    with pytest.raises(SystemExit, match="c36"):
        run_main(tmp_path, cache, db, tmp_path / "o.csv")
    assert not (tmp_path / "o.csv").exists()


def test_main_stops_when_a_region_has_no_coastline(tmp_path):
    """地点のある region（jp-14）に海岸線が1本も無い（別の県の線だけ）と、coast_dist_m が全て空になるので止める。"""
    cache, db = write_world(tmp_path)
    (tmp_path / "coast.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {"type": "LineString", "coordinates": [[129.0, 28.0], [129.1, 28.0]]},
        "properties": {"prefecture_code": "46"}}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="jp-14"):
        run_main(tmp_path, cache, db, tmp_path / "o.csv")
    assert not (tmp_path / "o.csv").exists()


def test_main_stops_when_summit_declaration_is_off(tmp_path):
    cache, db = write_world(tmp_path, summit_elev=1673.0, declared=1700.0)
    with pytest.raises(SystemExit, match="最高峰"):
        run_main(tmp_path, cache, db, tmp_path / "o.csv")
    assert not (tmp_path / "o.csv").exists()


def test_main_stops_when_region_has_no_summit(tmp_path):
    cache, db = write_world(tmp_path)
    (tmp_path / "region.yaml").write_text("jp-14:\n  name_ja: x\n  tz_name: Asia/Tokyo\n  utc_offset: '+09:00'\n  evidence: fixture\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="terrain.summit"):
        run_main(tmp_path, cache, db, tmp_path / "o.csv")


def test_main_stops_on_missing_tiles_without_network(tmp_path, monkeypatch):
    cache, db = write_world(tmp_path)
    some = next(iter(sorted(cache.rglob("*.png"))))
    some.unlink()
    import common
    monkeypatch.setattr(common, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    with pytest.raises(SystemExit, match="足りない"):
        run_main(tmp_path, cache, db, tmp_path / "o.csv")
    run_main(tmp_path, cache, db, tmp_path / "o.csv", "--plan")   # --plan は数えるだけで書かない
    assert not (tmp_path / "o.csv").exists()


def test_fetch_tiles_caches_and_records_404_as_empty(tmp_path, monkeypatch):
    import common
    calls = []

    class R:
        content = b"PNGDATA"

    def fake_get(url, **kw):
        calls.append(url)
        if url.endswith("/2.png"):
            raise RuntimeError(f"GET failed {url}: HTTP 404")
        if url.endswith("/3.png"):
            raise RuntimeError(f"GET failed {url}: HTTP 500")
        return R()
    monkeypatch.setattr(common, "get", fake_get)
    c68.fetch_tiles([(14, 1, 1), (14, 1, 2)], tmp_path)
    assert c68.tile_path(tmp_path, 14, 1, 1).read_bytes() == b"PNGDATA"
    assert c68.tile_path(tmp_path, 14, 1, 2).read_bytes() == b""
    assert c68.missing_tiles({(14, 1, 1), (14, 1, 2), (14, 1, 9)}, tmp_path) == [(14, 1, 9)]
    with pytest.raises(RuntimeError):
        c68.fetch_tiles([(14, 1, 3)], tmp_path)
    assert not c68.tile_path(tmp_path, 14, 1, 3).exists()


def test_checkpoints_yaml_fixture_shape():
    import pathlib
    p = pathlib.Path(__file__).parent / "fixtures" / "zone_checkpoints.yaml"
    pts = c68.checkpoint_points(p)
    assert len(pts) == 43
    assert sum(1 for q in pts if q["region_id"] == "jp-14") == 30 and sum(1 for q in pts if q["region_id"] == "jp-46") == 13
    assert [q["name"] for q in pts if q["known_miss"]] == ["平塚 馬入(河口)"]
    assert all(q["expect"] for q in pts)
