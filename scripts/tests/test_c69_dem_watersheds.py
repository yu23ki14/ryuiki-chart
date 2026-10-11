"""c69（DEM からの集水域）と dem_watershed_lib の単体テスト（Issue #94）。合成の標高だけで動く（ネットワーク・原本・実タイルに出ない）。

CI の requirements.txt に numpy・Pillow・shapely・scipy・pyflwdir は無い（収集側ツールのテスト）。
numpy・shapely・Pillow の無い環境では全体を飛ばし、scipy・pyflwdir を要るテストだけをそれぞれ飛ばす
（dem_watershed_lib はトップで pyflwdir・numba・scipy を import しない。このファイルの import が通ることが、その確認になる）。
"""
import io
import json
import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("shapely")
Image = pytest.importorskip("PIL.Image")

import c69_gsi_dem_watersheds as c69  # noqa: E402
import dem_watershed_lib as L  # noqa: E402
import regions  # noqa: E402
import terrain_lib as T  # noqa: E402

Z = 14
CFG = {"method": "dem", "stem": "gsi_dem_watersheds_amami", "a_min_km2": 0.5, "min_island_km2": 0.01,
       "simplify_px": 2, "dem_zoom": 14, "w05_match_m": 500}
# 画素の面積は約 0.00007 km²。0.5 km² は約 7,000 画素
X0, Y0 = int((129.4 + 180) / 360 * 2 ** Z) // 1, int(T.lonlat_to_pixel(129.4, 28.3, Z)[1] // 256)
W05_SHA = "w05-test"


def synthetic_dem():
    """512x256 画素（2x1 タイル）。陸は外周 8 画素を海（NaN）にした長方形。谷が 2 本（北へ・南へ流れる）と、
    離れた小島（40x40）、岩礁（3x3）、谷の斜面の窪地（深さ 30m の穴）。"""
    h, w = 256, 512
    dem = np.full((h, w), np.nan, np.float32)
    rows, cols = np.mgrid[0:h, 0:w]
    # 左の谷（列 100）は北へ、右の谷（列 300）は南へ下る。谷の断面は V 字（斜面は谷底へ向かって下る）
    left = 20.0 + 0.3 * rows + 2.0 * np.abs(cols - 100)
    right = 20.0 + 0.3 * (h - 1 - rows) + 2.0 * np.abs(cols - 300)
    land = np.zeros((h, w), bool)
    land[40:216, 20:420] = True
    z = np.where(cols < 200, left, right).astype(np.float32)
    z[130:140, 150:160] -= 30.0  # 窪地
    dem[land] = z[land]
    dem[100:140, 450:490] = 5.0   # 小島
    dem[10:13, 440:443] = 5.0     # 岩礁
    return dem


def run(cfg=CFG, mouths=(), dem=None, want_upa=False):
    dem = synthetic_dem() if dem is None else dem
    return c69.compute(cfg, "jp-46", dem, (X0, Y0), L.mosaic_sha256(dem), W05_SHA, list(mouths), want_upa=want_upa)


@pytest.fixture(autouse=True)
def amami_cfg(monkeypatch):
    monkeypatch.setitem(regions.REGIONS["jp-46"], "watershed", CFG)


# ---------- 純関数（numpy・shapely だけ） ----------
def test_merge_prefers_big_neighbour_then_longest_edge():
    area = np.array([0, 1.0, 5.0, 0.2, 0.3, 0.1])
    # 3 は 1（共有辺 2）と 2（共有辺 9）に接する。2 は a_min 以上。4 は 3 にだけ接する。5 は孤立
    adj = {1: {3: 2}, 3: {1: 2, 2: 9, 4: 1}, 2: {3: 9}, 4: {3: 1}}
    root = L.merge_basins(adj, area, a_min=1.0)
    assert root[3] == 2            # 共有辺の最長（かつ a_min 以上の隣）
    assert root[4] == 2            # 3 が併合された先へ連なる（4 は小さい 3 でなく、併合後の面へ）
    assert root[1] == 1 and root[2] == 2 and root[5] == 5
    assert root[0] == 0


def test_merge_big_neighbour_wins_over_longer_edge_and_ties_pick_lower_id():
    area = np.array([0, 5.0, 0.2, 0.3, 4.0])
    adj = {2: {1: 1, 3: 8}, 3: {2: 8, 4: 2}, 1: {2: 1}, 4: {3: 2}}
    root = L.merge_basins(adj, area, a_min=1.0)
    assert root[2] == 1            # 3 は小さいので、辺が短くても a_min 以上の 1 を選ぶ
    assert root[3] == 1            # 2 が 1 に併合されて辺が 8 に。a_min 以上の 1（8）と 4（2）では長い方
    tie = L.merge_basins({1: {2: 3, 3: 3}, 2: {1: 3}, 3: {1: 3}}, np.array([0, 0.1, 5.0, 5.0]), a_min=1.0)
    assert tie[1] == 2             # 同じ長さなら番号の小さい方


def test_basin_adjacency_counts_shared_edges():
    lab = np.array([[1, 1, 2], [1, 3, 2], [0, 3, 2]])
    adj = L.basin_adjacency(lab, 3)
    assert adj[1] == {2: 1, 3: 2} and adj[2] == {1: 1, 3: 2} and adj[3] == {1: 2, 2: 2}


def test_label_runs_and_polygons_do_not_overlap():
    lab = np.zeros((10, 12), np.int32)
    lab[1:9, 1:6] = 1
    lab[1:9, 6:11] = 2
    lab[4:6, 3:8] = 3
    polys = L.labels_to_polygons(lab, X0, Y0, Z, simplify_px=1)
    assert sorted(polys) == [1, 2, 3]
    gs = [polys[k] for k in sorted(polys)]
    for i in range(3):
        for j in range(i + 1, 3):
            assert gs[i].intersection(gs[j]).area < 1e-10
    runs = L.label_runs(lab)
    assert runs[1].shape[1] == 4 and len(runs[1]) == 8 + 0 and len(runs[3]) == 2   # 行ごとの run（3 は 2 行ぶん）


def test_assemble_units_kinds_and_id_order():
    # 流域 1（大）・2（小。1 へ併合）・3〜5（小が連なって coast_group）・6（孤立した小＝island）
    lab = np.zeros((8, 24), np.int32)
    for k, (c0, c1) in enumerate([(0, 8), (8, 10), (14, 16), (16, 18), (18, 20), (22, 24)], 1):
        lab[:, c0:c1] = k
    row_area = np.full(8, 0.01)
    area = L.basin_areas(lab, L.pixel_weights(row_area, lab.shape), 6)
    root = L.merge_basins(L.basin_adjacency(lab, 6), area, a_min=0.4)
    pits_rc = np.array([[7, 3], [7, 8], [0, 14], [1, 16], [2, 18], [5, 22]])
    lab_f, units, dropped = L.assemble_units(lab, root, area, pits_rc, 0.4, 0.05, X0, Y0, Z, "dem-x")
    assert [u["watershed_id"] for u in units] == ["dem-x-001", "dem-x-002", "dem-x-003"]
    assert {u["unit_kind"] for u in units} == {L.KIND_BASIN, L.KIND_COAST_GROUP, L.KIND_ISLAND}
    basin = next(u for u in units if u["unit_kind"] == L.KIND_BASIN)
    assert basin["n_basins"] == 2 and basin["own_drainage_km2"] == pytest.approx(0.64)
    assert basin["area_km2"] == pytest.approx(0.8) and basin["merged_share"] == pytest.approx(0.2)
    group = next(u for u in units if u["unit_kind"] == L.KIND_COAST_GROUP)
    assert group["n_basins"] == 3 and group["own_drainage_km2"] == pytest.approx(0.16) and group["area_km2"] == pytest.approx(0.48)
    assert dropped == {"n": 0, "area_km2": 0.0}
    # 番号は出口の緯度の大きい順（行 0 が北）、同じ緯度なら経度の小さい順
    keys = [(-u["outlet_lat"], u["outlet_lon"]) for u in units]
    assert keys == sorted(keys)
    assert set(np.unique(lab_f)) == {0, 1, 2, 3}


def test_assemble_units_drops_tiny_units():
    lab = np.zeros((4, 4), np.int32)
    lab[:, :2] = 1
    lab[0, 3] = 2
    row_area = np.full(4, 0.001)
    area = L.basin_areas(lab, L.pixel_weights(row_area, lab.shape), 2)
    root = L.merge_basins(L.basin_adjacency(lab, 2), area, a_min=1.0)
    lab_f, units, dropped = L.assemble_units(lab, root, area, np.array([[3, 0], [0, 3]]), 1.0, 0.005, X0, Y0, Z, "d")
    assert len(units) == 1 and dropped["n"] == 1 and dropped["area_km2"] == pytest.approx(0.001)
    assert lab_f[0, 3] == 0


def test_w05_mouths_ends_not_starts_and_attach():
    nodes = [{"node_id": n, "lon": lo, "lat": 28.3, "elevation_m": e}
             for n, lo, e in (("a", 129.4000, 60.0), ("b", 129.4100, 3.0), ("c", 129.5, 1.0))]
    rivers = [
        {"stream_start_node_ref": "#a", "stream_end_node_ref": "#b", "river_name_ja": "甲川", "water_system_name_ja": "甲水系"},
        {"stream_start_node_ref": "#c", "stream_end_node_ref": "#a", "river_name_ja": "乙川", "water_system_name_ja": "甲水系"},
        {"stream_start_node_ref": "#a", "stream_end_node_ref": "#b", "river_name_ja": "丙川", "water_system_name_ja": "甲水系"},
    ]
    mouths = L.w05_mouths(rivers, nodes)
    assert [m["node_id"] for m in mouths] == ["b"]       # a は流路の始点でもある。c は終点でない
    assert mouths[0]["river_names"] == ("丙川", "甲川") or mouths[0]["river_names"] == tuple(sorted(("甲川", "丙川")))
    units = [
        {"unit_kind": L.KIND_BASIN, "outlet_lon": 129.4101, "outlet_lat": 28.3},
        {"unit_kind": L.KIND_BASIN, "outlet_lon": 129.45, "outlet_lat": 28.3},
        {"unit_kind": L.KIND_COAST_GROUP, "outlet_lon": 129.4101, "outlet_lat": 28.3},
    ]
    L.attach_w05(units, mouths, 500)
    assert units[0]["water_system_name_ja_estimated"] == "甲水系" and set(units[0]["main_river_names_ja"].split("|")) == {"甲川", "丙川"}
    assert units[0]["w05_mouth_distance_m"] < 20
    assert units[1]["water_system_name_ja_estimated"] is None and units[1]["main_river_names_ja"] == ""
    assert units[1]["w05_mouth_distance_m"] > 500             # 距離は残す（検査が外れとして見る）
    assert units[2]["w05_mouth_distance_m"] is None           # basin 以外は河口を引かない


def test_attach_w05_multiple_systems_at_one_mouth_are_all_listed():
    mouth = {"node_id": "b", "lon": 129.41, "lat": 28.3, "elevation_m": 1.0, "river_names": ("甲川",),
             "water_system_names": ("乙水系", "甲水系")}
    units = [{"unit_kind": L.KIND_BASIN, "outlet_lon": 129.41, "outlet_lat": 28.3}]
    L.attach_w05(units, [mouth], 500)
    assert units[0]["water_system_name_ja_estimated"] == "乙水系|甲水系"   # 文字列順の先頭を黙って選ばない


def test_params_digest_depends_on_w05_input():
    base = L.params_digest(CFG, "1.0", "m", "w05a")
    assert L.params_digest(CFG, "1.0", "m", "w05b") != base


def test_files_sha256_tracks_content(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    h = L.files_sha256([a, b])
    b.write_bytes(b"z")
    assert L.files_sha256([a, b]) != h


def test_check_fresh_is_unknown_when_inputs_are_missing(tmp_path, capsys):
    """海岸線ファイルが無いとき exit 1（例外）ではなく契約どおり 3（判定不能）。"""
    rc = c69.check_fresh("jp-46", tmp_path / "no_coast.geojson", tmp_path, tmp_path / "x.jsonl")
    assert rc == c69.EXIT_UNKNOWN


def test_required_tiles_follow_land_not_bbox():
    from shapely.geometry import Polygon
    west, north = T.pixel_to_lonlat((X0 + 0.1) * 256, (Y0 + 0.1) * 256, Z)
    east, south = T.pixel_to_lonlat((X0 + 0.9) * 256, (Y0 + 0.9) * 256, Z)
    far_w, far_n = T.pixel_to_lonlat((X0 + 5.2) * 256, (Y0 + 5.2) * 256, Z)
    far_e, far_s = T.pixel_to_lonlat((X0 + 5.8) * 256, (Y0 + 5.8) * 256, Z)
    land = [Polygon([(west, south), (east, south), (east, north), (west, north)]),
            Polygon([(far_w, far_s), (far_e, far_s), (far_e, far_n), (far_w, far_n)])]
    assert L.required_tiles(land, Z, margin_deg=0.0) == [(Z, X0, Y0), (Z, X0 + 5, Y0 + 5)]


def test_build_mosaic_places_tiles_and_marks_gaps_nan():
    def png(v):
        raw = round(v * 100)
        a = np.zeros((256, 256, 3), np.uint8)
        a[..., 0], a[..., 1], a[..., 2] = raw >> 16, (raw >> 8) & 255, raw & 255
        b = io.BytesIO()
        Image.fromarray(a, "RGB").save(b, format="PNG")
        return b.getvalue()

    data = {(Z, 10, 20): png(5.0), (Z, 12, 21): png(7.5), (Z, 12, 20): b""}
    dem, origin = L.build_mosaic(sorted(data), lambda z, x, y: data[(z, x, y)])
    assert origin == (10, 20) and dem.shape == (512, 768)
    assert dem[0, 0] == pytest.approx(5.0) and dem[300, 600] == pytest.approx(7.5)
    assert np.isnan(dem[0, 600]) and np.isnan(dem[300, 0])       # 404（空）・タイルの無い所は NaN
    assert L.mosaic_sha256(dem) == L.mosaic_sha256(dem.copy())
    with pytest.raises(T.TileNotCached):
        L.build_mosaic([(Z, 1, 1)], lambda z, x, y: None)


def test_declarations_file_shape():
    decl = L.load_declarations(c69.DECLARATIONS)
    assert set(decl) == set(L.CHECK_NAMES)
    assert decl["w05_outlet_to_mouth"]["expected"] == 500 and decl["land_coverage"]["expected"] == 0.995


def test_declarations_reject_exception_without_reason(tmp_path):
    p = tmp_path / "d.yaml"
    body = {n: {"expected": 1, "exceptions": []} for n in L.CHECK_NAMES}
    body["overlap_pairs"]["exceptions"] = [{"id": "x"}]
    import yaml
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        L.load_declarations(p)
    del body["unit_count"]
    body["overlap_pairs"]["exceptions"] = []
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    with pytest.raises(ValueError, match="不足"):
        L.load_declarations(p)


def test_exceptions_must_be_declared_and_not_stale():
    decl = {n: {"expected": 500, "exceptions": []} for n in L.CHECK_NAMES}
    units = [{"unit_kind": L.KIND_BASIN, "outlet_lon": 129.5, "outlet_lat": 28.3, "watershed_id": "dem-amami-001"}]
    far = [{"node_id": "m", "lon": 129.6, "lat": 28.3, "elevation_m": 1, "river_names": (), "water_system_names": ()}]
    r = L.check_outlet_to_mouth(units, far, decl)
    assert not r["passed"] and r["undeclared_failures"] == ["dem-amami-001"]
    decl["w05_outlet_to_mouth"]["exceptions"] = [{"id": "dem-amami-001", "reason": "海上の河口"}]
    r = L.check_outlet_to_mouth(units, far, decl)
    assert r["passed"] and r["declared_exceptions_used"] == ["dem-amami-001"]
    near = [dict(far[0], lon=129.5001)]
    r = L.check_outlet_to_mouth(units, near, decl)
    assert not r["passed"] and r["declared_exceptions_unused"] == ["dem-amami-001"]    # 使われなかった例外は失敗


def test_check_determinism_flags_byte_difference():
    decl = {n: {"expected": 1, "exceptions": []} for n in L.CHECK_NAMES}
    assert L.check_determinism({"jsonl": "a\n"}, {"jsonl": b"a\n"}, decl)["passed"]
    r = L.check_determinism({"jsonl": "a\n"}, {"jsonl": b"b\n"}, decl)
    assert not r["passed"] and r["measured"]["differs"] == ["jsonl"]
    assert not L.check_determinism({"jsonl": "a\n"}, {"jsonl": None}, decl)["passed"]


def test_declared_regions_contract():
    """regions.py の宣言（担当 B が足す）は c69 が読む形: method=dem の地域は stem と必須キーを持つ。"""
    cfg = c69.watershed_cfg("jp-46")
    for k in ("stem", "a_min_km2", "min_island_km2", "simplify_px", "dem_zoom", "w05_match_m"):
        assert k in cfg


# ---------- 計算（scipy・pyflwdir を要る） ----------
@pytest.fixture(scope="module")
def solved():
    pytest.importorskip("scipy")
    pytest.importorskip("pyflwdir")
    pytest.importorskip("numba")
    return None


def test_pipeline_two_valleys_island_rock_and_pit(solved, monkeypatch):
    monkeypatch.setitem(regions.REGIONS["jp-46"], "watershed", CFG)
    res = run(want_upa=True)
    units = res["units"]
    by_kind = {k: [u for u in units if u["unit_kind"] == k] for k in L.KINDS}
    assert len(by_kind[L.KIND_BASIN]) == 2                       # 谷が 2 本（窪地は出口にならない）
    assert len(by_kind[L.KIND_ISLAND]) == 1 and by_kind[L.KIND_ISLAND][0]["area_km2"] == pytest.approx(
        40 * 40 * T.m_per_px(28.3, Z) ** 2 / 1e6, rel=0.05)
    assert res["dropped_components"]["n"] == 1                   # 岩礁（3x3）は落ちる
    assert res["dropped_components"]["area_km2"] < 0.01
    # 窪地（斜面の穴）は流域の途中に埋まる: どの出口も海に接している
    assert L.outlet_on_coast(res["valid"], units) == []
    # 番号は出口の緯度の大きい順（北へ流れる谷が先）。ID は 3 桁連番
    assert [u["id"] for u in units] == list(range(1, len(units) + 1))
    lats = [(-u["outlet_lat"], u["outlet_lon"]) for u in units]
    assert lats == sorted(lats)
    assert units[0]["watershed_id"] == "dem-amami-001"
    # 陸の面積が保存される（落とした分を除く）
    total = sum(u["area_km2"] for u in units) + res["dropped_units"]["area_km2"]
    row_area = L.row_area_km2(Y0, 256, Z)
    land = np.broadcast_to(row_area[:, None], res["valid"].shape)[res["valid"]].sum()
    assert total == pytest.approx(land, rel=1e-9)
    # basin の自前の集水面積は a_min 以上、coast_group は併合で a_min に届いた面
    assert all(u["own_drainage_km2"] >= CFG["a_min_km2"] for u in by_kind[L.KIND_BASIN])
    assert all(u["area_km2"] >= CFG["a_min_km2"] and u["own_drainage_km2"] < CFG["a_min_km2"] for u in by_kind[L.KIND_COAST_GROUP])
    assert all(0.0 <= u["merged_share"] < 1.0 for u in units)
    # 面同士は重ならない
    decl = L.load_declarations(c69.DECLARATIONS)
    geoms = [res["polys"][u["id"]] for u in units]
    assert L.check_overlap_pairs(geoms, [u["watershed_id"] for u in units], decl)["passed"]
    # jsonl の列は ROW_KEYS の順で、全行に同じ params_digest
    rows = [json.loads(line) for line in res["jsonl"].splitlines()]
    assert all(tuple(r) == L.ROW_KEYS and r["params_digest"] == res["digest"] for r in rows)
    feats = json.loads(res["geojson"])["features"]
    assert [f["properties"] for f in feats] == rows


def test_pipeline_is_deterministic(solved):
    a, b = run(), run()
    assert a["jsonl"] == b["jsonl"] and a["geojson"] == b["geojson"] and a["digest"] == b["digest"]


def test_digest_changes_with_parameters_and_mosaic(solved):
    base = run()["digest"]
    assert run(cfg=dict(CFG, a_min_km2=1.0))["digest"] != base
    dem = synthetic_dem()
    dem[60, 60] += 0.01
    assert run(dem=dem)["digest"] != base


def test_a_min_controls_merging(solved):
    n_small = len(run(cfg=dict(CFG, a_min_km2=0.001))["units"])
    n_big = len(run(cfg=dict(CFG, a_min_km2=3.0))["units"])
    assert n_small == 3 and n_big == 2        # 谷が 2.4 km² ずつ。a_min=3 では 2 本が 1 面に併合される


def test_w05_names_flow_into_rows(solved):
    first = run()["units"][0]
    mouth = {"node_id": "m1", "lon": first["outlet_lon"], "lat": first["outlet_lat"], "elevation_m": 1.0,
             "river_names": ("試験川",), "water_system_names": ("試験水系",)}
    res = run(mouths=[mouth])
    row = json.loads(res["jsonl"].splitlines()[0])
    assert row["main_river_names_ja"] == "試験川" and row["water_system_name_ja_estimated"] == "試験水系"
    assert row["water_system_category_ja"] is None            # W12 の水系区分の列には DEM の種別を混ぜない（unit_kind が持つ）
    assert row["w05_mouth_distance_m"] == 0.0


def test_mouth_catchment_candidates(solved):
    res = run(want_upa=True)
    u = max(res["units"], key=lambda u: u["area_km2"])
    mouth = {"node_id": "m1", "lon": u["outlet_lon"], "lat": u["outlet_lat"], "elevation_m": 2.0,
             "river_names": (), "water_system_names": ()}
    high = dict(mouth, node_id="m2", elevation_m=50.0)
    nowhere = dict(mouth, node_id="m3", lon=129.45, lat=28.35)
    cands = L.mouths_with_catchment([mouth, high, nowhere], res["upa"], X0, Y0, Z, CFG["a_min_km2"])
    assert [m["node_id"] for m in cands] == ["m1"]


def test_outlet_on_coast_accepts_diagonal_only_sea_contact():
    """D8 の出口は斜めにだけ海に接していてもよい（dem-amami-028・037 の実例）。内陸の出口は NG。"""
    valid = np.ones((7, 7), dtype=bool)
    valid[4, 4] = False                       # (3,3) の右下の斜めだけが海
    unit = {"watershed_id": "x", "outlet_row": 3, "outlet_col": 3}
    assert L.outlet_on_coast(valid, [unit]) == []
    assert L.outlet_on_coast(valid, [{"watershed_id": "y", "outlet_row": 1, "outlet_col": 1}]) == ["y"]
    valid[3, 3] = False                       # 出口が無効画素なら NG
    assert L.outlet_on_coast(valid, [unit]) == ["x"]
