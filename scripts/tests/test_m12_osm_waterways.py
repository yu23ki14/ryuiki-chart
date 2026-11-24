"""OSM の河川線・ダム・堰: 固定の小さな Overpass 応答でパース・長さ・region 割り当て・投入を検証する（ネットワーク不要）。"""
import json
import sqlite3

import pytest

import m12_osm_waterways as m12

AMAMI = {
    "_region_id": "jp-46",
    "elements": [{"type": "way", "id": 2, "tags": {"name": "住用川", "waterway": "stream"},
                  "geometry": [{"lat": 28.3, "lon": 129.4}, {"lat": 28.31, "lon": 129.4}]}],
}
RIVERS = {
    "_region_id": "jp-14",
    "elements": [
        {"type": "way", "id": 1, "tags": {"name": "相模川", "waterway": "river"},
         "geometry": [{"lat": 35.0, "lon": 139.0}, {"lat": 35.0, "lon": 139.001}, {"lat": 35.001, "lon": 139.001}]},
        # 取得範囲の外（県外の上流）でも、取得範囲の region のまま
        {"type": "way", "id": 3, "tags": {"name": "桂川", "waterway": "river"},
         "geometry": [{"lat": 35.5, "lon": 138.8}, {"lat": 35.51, "lon": 138.8}]},
        {"type": "way", "id": 4, "tags": {"waterway": "river"}, "geometry": [{"lat": 35.3, "lon": 139.0}, {"lat": 35.31, "lon": 139.0}]},
        {"type": "way", "id": 5, "tags": {"name": "点だけ", "waterway": "river"}, "geometry": [{"lat": 35.3, "lon": 139.0}]},
        {"type": "relation", "id": 900, "members": [{"type": "way", "ref": 3, "role": ""}, {"type": "node", "ref": 7, "role": ""}]},
        {"type": "relation", "id": 800, "members": [{"type": "way", "ref": 3, "role": ""}]},
    ],
}
STRUCTS = {
    "_region_id": "jp-14",
    "elements": [
        {"type": "node", "id": 10, "lat": 35.6, "lon": 139.3, "tags": {"waterway": "dam", "name": "城山ダム"}},
        {"type": "way", "id": 11, "center": {"lat": 35.2, "lon": 139.2}, "tags": {"waterway": "weir"}},
        {"type": "relation", "id": 12, "tags": {"waterway": "weir", "name": "座標なし"}},
    ],
}


def by_id(rows, key="way_id"):
    return {r[key]: r for r in rows}


def test_parse_rivers_filters_and_fields():
    rows = by_id(m12.parse_rivers(RIVERS))
    assert set(rows) == {1, 3}  # 名前なし・1点だけは落ちる
    r = rows[1]
    assert (r["name_ja"], r["waterway"], r["source_ref"]) == ("相模川", "river", "osm:way/1")
    assert (r["start_lat"], r["start_lon"], r["end_lat"], r["end_lon"]) == (35.0, 139.0, 35.001, 139.001)
    g = json.loads(r["geometry_geojson"])
    assert g["type"] == "LineString" and g["coordinates"] == [[139.0, 35.0], [139.001, 35.0], [139.001, 35.001]]  # 丸めない・間引かない


def test_length_is_spherical_approx():
    # 緯度 0.01 度 ≒ 1111.95 m（R=6371008.8）
    assert m12.length_m([[129.4, 28.3], [129.4, 28.31]]) == pytest.approx(1111.95, abs=0.5)
    assert m12.length_m([[129.4, 28.3]]) == 0
    r = by_id(m12.parse_rivers(RIVERS))[1]
    assert r["length_m"] == pytest.approx(m12.length_m([[139.0, 35.0], [139.001, 35.0], [139.001, 35.001]]))


def test_region_is_the_fetched_area_region():
    rows = by_id(m12.parse_rivers(RIVERS))
    assert rows[1]["region_id"] == "jp-14"
    assert rows[3]["region_id"] == "jp-14"   # 山梨側（県の bbox の外）も取得範囲の region のまま
    assert by_id(m12.parse_rivers(AMAMI))[2]["region_id"] == "jp-46"
    # 奄美の bbox 内の座標でも、取得範囲が jp-14 なら jp-14（座標では決めない）
    odd = {"_region_id": "jp-14", "elements": AMAMI["elements"]}
    assert by_id(m12.parse_rivers(odd))[2]["region_id"] == "jp-14"


def test_relation_id_is_smallest_and_nullable():
    rows = by_id(m12.parse_rivers(RIVERS))
    assert rows[3]["relation_id"] == 800  # 同じファイル内の複数リレーションは最小
    assert rows[1]["relation_id"] is None


def test_parse_structures_center_and_kind():
    rows = by_id(m12.parse_structures(STRUCTS), "osm_id")
    assert set(rows) == {10, 11}  # 座標の取れない relation は落ちる
    assert (rows[10]["kind"], rows[10]["name_ja"], rows[10]["lat"], rows[10]["source_ref"]) == ("dam", "城山ダム", 35.6, "osm:node/10")
    assert (rows[11]["kind"], rows[11]["name_ja"], rows[11]["lon"], rows[11]["osm_type"]) == ("weir", None, 139.2, "way")


def make_db():
    con = sqlite3.connect(":memory:")
    con.execute("""CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name, publisher, url, category, access_method, format,
                   license, redistributable, fetched_at, record_count, notes)""")
    return con


def write(tmp_path, name, body):
    (tmp_path / name).write_text(json.dumps(body), encoding="utf-8")


def test_load_is_idempotent_dedupes_and_registers(tmp_path):
    write(tmp_path, "a_rivers.json", RIVERS)
    write(tmp_path, "b_rivers.json", RIVERS)  # 境界をまたぐ重複
    write(tmp_path, "z_amami_rivers.json", AMAMI)
    write(tmp_path, "a_structures.json", STRUCTS)
    ways, structs, meta = m12.read_raw(tmp_path)
    assert (len(ways), len(structs)) == (3, 2)
    con = make_db()
    for _ in range(2):
        res = m12.load(con, ways, structs, meta)
        con.commit()
    assert res == {"osm_waterways": 3, "osm_water_structures": 2}
    assert con.execute("SELECT region_id, COUNT(*) FROM osm_waterways GROUP BY 1 ORDER BY 1").fetchall() == [("jp-14", 2), ("jp-46", 1)]
    # source_registry の件数は表の COUNT(*) と一致する
    assert dict(con.execute("SELECT source_id, record_count FROM source_registry")) == {"osm_waterways": 3, "osm_water_structures": 2}


def test_relation_id_is_min_across_files_regardless_of_order(tmp_path):
    def body(rel):
        return {"_region_id": "jp-14", "elements": [
            {"type": "way", "id": 1, "tags": {"name": "A", "waterway": "river"}, "geometry": [{"lat": 35, "lon": 139}, {"lat": 35.1, "lon": 139}]},
            *([{"type": "relation", "id": rel, "members": [{"type": "way", "ref": 1, "role": ""}]}] if rel else [])]}
    for order in ((500, 300, None), (None, 300, 500), (300, 500, None)):
        d = tmp_path / "-".join(str(o) for o in order)
        d.mkdir()
        for i, rel in enumerate(order):
            write(d, f"f{i}_rivers.json", body(rel))
        ways, _, _ = m12.read_raw(d)
        assert ways[0]["relation_id"] == 300


def test_overpass_retry_policy(monkeypatch):
    import c105_osm_waterways as c105
    monkeypatch.setattr(c105.time, "sleep", lambda s: None)

    class R:
        def __init__(self, code, body=None):
            self.status_code, self._b, self.text = code, body, "x"

        def json(self):
            return self._b

    calls = []

    def post_400(url, **kw):
        calls.append(url)
        return R(400)
    with pytest.raises(RuntimeError, match="400"):
        c105.overpass("q", post=post_400)
    assert len(calls) == 1  # 恒久的な 4xx は取り直さない

    seq = iter([R(502), R(429), R(200, {"elements": [], "remark": "runtime error: timeout"}), R(200, {"elements": [1]})])
    assert c105.overpass("q", post=lambda url, **kw: next(seq))["elements"] == [1]  # 5xx・429・remark の error は取り直す


def test_cache_is_current_checks_query_hash(tmp_path):
    import c105_osm_waterways as c105
    bbox = (1, 2, 3, 4)
    p = tmp_path / "x.json"
    assert not c105.cache_is_current(p, bbox, "q")
    p.write_text(json.dumps({"_query_hash": c105.query_hash(bbox, "q")}), encoding="utf-8")
    assert c105.cache_is_current(p, bbox, "q")
    assert not c105.cache_is_current(p, bbox, "q2") and not c105.cache_is_current(p, (1, 2, 3, 5), "q")
