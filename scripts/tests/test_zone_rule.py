"""zone v2 の判定規則（scripts/registry/zone_rule.py）と build_place の zone 節のテスト
（docs/plans/AMAMI_STEP0.md §1・§3・§6-B）。標高タイルも原本も使わず、手書きの小さな入力だけで完結する。
"""
import csv
import pathlib
import re
import socket

import pytest
import yaml

from registry import zone_rule
from registry.zone_rule import TerrainPoint, ZoneRuleError
from registry.zone_rule import classify as classify_with_reason

from .test_registry_place import _build as build_place_with_fixtures
from .zone_fixtures import SUMMIT_M, real_terrain, write_region_yaml, write_terrain_csv, zone_row

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = pathlib.Path(__file__).parent / "fixtures"
RULE = zone_rule.load_zone_definition()["rule"]


def classify(m, rule, ledger_elevation_m=None):
    """zone だけ（理由は別のテストで見る）。"""
    return classify_with_reason(m, rule, ledger_elevation_m)[0]


def _pt(e, rw=0.0, rn=0.0, floor=0.0, coast=None, summit=1000.0):
    return TerrainPoint("0", "0", "jp-x", summit, e, rw, rn, floor, coast)


# ---------------------------------------------------------------------------
# classify() の境界値（受け入れ基準 1）
# ---------------------------------------------------------------------------

def test_ledger_elevation_is_used_when_dem_is_invalid():
    """DEM が無効（海の画素）でも、台帳の標高があれば海岸距離と標高だけで zone 5 が付く（起伏量が無くても）。"""
    sea = _pt(None, rw=None, rn=None, floor=None, coast=661.0)
    assert classify_with_reason(sea, RULE, 5.0) == (5, "coast_c23_within_2km")
    assert classify_with_reason(sea, RULE, None) == (None, "elevation_invalid")
    # 5 に当たらず起伏量も無いときだけ None
    assert classify_with_reason(sea, RULE, 50.0) == (None, "relief_unavailable")
    # DEM の値があれば台帳の標高より DEM を使う
    assert classify(_pt(300.0, rw=10.0, coast=100.0), RULE, 5.0) != 5


@pytest.mark.parametrize("pt,reason", [
    (_pt(500.0, rw=300.0, summit=1000.0), "mountain_relief_ge_200"),
    (_pt(60.0, rw=10.0, rn=40.0, floor=0.0), "lowland_relief_near_gt_30"),
    (_pt(150.0, rw=10.0, rn=5.0, floor=0.0), "lowland_elev_gt_100"),
    (_pt(60.0, rw=10.0, rn=5.0, floor=0.0), "lowland_above_floor_gt_15"),
    (_pt(10.0, rw=10.0, rn=5.0, floor=5.0, coast=5000.0), "lowland_criteria_met"),
    (_pt(60.0, rw=10.0, rn=None, floor=None), "lowland_floor_unavailable"),
    (_pt(50.0, rw=None), "relief_unavailable"),
])
def test_classify_returns_the_last_effective_condition_as_reason(pt, reason):
    assert classify_with_reason(pt, RULE)[1] == reason


def test_no_elevation_gives_none():
    assert classify(_pt(None, coast=0.0), RULE) is None


def test_coast_boundaries_2000m_and_10m_are_inclusive():
    assert classify(_pt(10.0, rw=500, coast=2000.0), RULE) == 5      # ちょうど 2000m・10m は 5
    assert classify(_pt(10.0, rw=500, coast=2000.1), RULE) != 5
    assert classify(_pt(10.1, rw=500, coast=100.0), RULE) != 5
    assert classify(_pt(5.0, rw=500, coast=None), RULE) != 5         # C23 が無い地域は海岸判定をしない


def test_coast_is_checked_before_mountain_even_with_large_relief():
    assert classify(_pt(5.0, rw=400, coast=100.0), RULE) == 5


def test_mountain_relief_200_is_inclusive_and_summit_ratio_half_is_inclusive():
    assert classify(_pt(500.0, rw=200.0, summit=1000.0), RULE) == 1   # 最高峰の半分ちょうど
    assert classify(_pt(499.9, rw=200.0, summit=1000.0), RULE) == 2
    assert classify(_pt(500.0, rw=199.9, summit=1000.0, rn=100.0, floor=0.0), RULE) == 3  # 山地でない


def test_summit_comes_from_the_point_not_a_global_constant():
    assert classify(_pt(400.0, rw=300.0, summit=694.0), RULE) == 1    # 奄美: 347m 以上が 1
    assert classify(_pt(400.0, rw=300.0, summit=1673.0), RULE) == 2   # 神奈川: 約837m 以上が 1


def test_missing_wide_relief_gives_none_but_missing_floor_gives_3():
    assert classify(_pt(50.0, rw=None), RULE) is None
    assert classify(_pt(50.0, rw=10.0, rn=5.0, floor=None), RULE) == 3


def test_lowland_boundaries_are_inclusive():
    base = dict(rw=10.0)
    assert classify(_pt(100.0, rn=30.0, floor=85.0, **base), RULE) == 4   # 標高100・起伏30・比高15 ちょうど
    assert classify(_pt(100.1, rn=30.0, floor=85.1, **base), RULE) == 3   # 標高 100 超
    assert classify(_pt(100.0, rn=30.1, floor=85.0, **base), RULE) == 3   # 250m 窓の起伏 30 超
    assert classify(_pt(100.0, rn=30.0, floor=84.9, **base), RULE) == 3   # 最低点からの比高 15 超


def test_float_noise_in_height_above_floor_does_not_flip_the_boundary():
    # 標高 16.1 - 最低点 1.1 は浮動小数で 15.000000000000002 になるが、比高 15 ちょうどとして 4 のまま
    assert 16.1 - 1.1 != 15.0
    assert classify(_pt(16.1, rn=1.0, floor=1.1, rw=1.0), RULE) == 4


# ---------------------------------------------------------------------------
# 確認地点（§1.4-d/e。期待は設計担当の地理知識。known_miss は 1 件だけ許す）
# (名前, region, 標高, 起伏1km, 起伏250m, 海岸距離, 2km窓の最低点からの比高, 表の zone, 期待の集合)
# ---------------------------------------------------------------------------

SUMMITS = {"jp-14": 1673.0, "jp-46": 694.0}
CHECKPOINTS = [
    ("丹沢山頂", "jp-14", 1672, 628, 188, 23635, 898, 1, {1}),
    ("大山山頂付近", "jp-14", 1252, 594, 191, 16230, 874, 1, {1, 2}),
    ("神山(箱根)", "jp-14", 1437, 451, 159, 11026, 731, 1, {1}),
    ("芦ノ湖畔", "jp-14", 724, 211, 22, 10205, 26, 2, {2, 3}),
    ("相模湖", "jp-14", 183, 275, 40, 35490, 54, 2, {2, 3}),
    ("宮ヶ瀬湖", "jp-14", 303, 228, 56, 24657, 18, 2, {2, 3}),
    ("大和市", "jp-14", 61, 21, 4, 15632, 17, 3, {3}),
    ("相模大野", "jp-14", 90, 22, 7, 19033, 27, 3, {3}),
    ("鶴見", "jp-14", 41, 39, 17, 3229, 39, 3, {3}),
    ("武山", "jp-14", 76, 184, 151, 2242, 67, 3, {3}),
    ("寒川", "jp-14", 16, 26, 8, 6253, 13, 4, {4}),
    ("厚木", "jp-14", 20, 16, 1, 13566, 10, 4, {3, 4}),
    ("開成", "jp-14", 40, 47, 5, 9008, 18, 3, {3, 4}),
    ("小田原飯泉", "jp-14", 16, 30, 1, 3713, 8, 4, {3, 4}),
    ("平塚馬入", "jp-14", 7, 8, 3, 2143, 5, 4, {5}),  # known_miss
    ("山下公園", "jp-14", 3, 42, 12, 215, 3, 5, {5}),
    ("相模原台地", "jp-14", 125, 12, 3, 26089, 35, 3, {3}),
    ("座間", "jp-14", 42, 28, 13, 13100, 24, 3, {3}),
    ("湘南台", "jp-14", 34, 22, 6, 8496, 22, 3, {3}),
    ("日吉", "jp-14", 22, 33, 20, 7543, 18, 3, {3}),
    ("衣笠", "jp-14", 47, 84, 49, 2231, 41, 3, {3}),
    ("初声", "jp-14", 36, 58, 27, 796, 36, 3, {3}),
    ("麻生", "jp-14", 50, 56, 33, 18420, 20, 3, {3}),
    ("新横浜", "jp-14", 9, 38, 25, 3646, 4, 4, {4}),
    ("酒匂", "jp-14", 9, 10, 3, 1453, 9, 5, {4, 5}),
    ("茅ヶ崎柳島", "jp-14", 4, 11, 7, 490, 4, 5, {4, 5}),
    ("溝の口", "jp-14", 19, 33, 20, 13319, 10, 4, {4}),
    ("藤沢境川", "jp-14", 10, 48, 10, 2923, 6, 4, {4}),
    ("山北", "jp-14", 113, 250, 39, 14353, 40, 2, {2, 3}),
    ("津久井", "jp-14", 201, 147, 69, 33328, 76, 3, {2, 3}),
    ("湯湾岳山頂", "jp-46", 692, 430, 108, 2960, 572, 1, {1}),
    ("金作原", "jp-46", 213, 338, 169, 4172, 200, 2, {1, 2}),
    ("住用中腹", "jp-46", 360, 446, 177, 1022, 360, 1, {1, 2}),
    ("住用マングローブ", "jp-46", 6, 342, 131, 97, 6, 5, {5}),
    ("名瀬市街", "jp-46", 8, 236, 55, 478, 8, 5, {5}),
    ("新川河口", "jp-46", 5, 228, 9, 315, 5, 5, {5}),
    ("龍郷湾岸", "jp-46", 6, 230, 96, 152, 6, 5, {5}),
    ("大和浜", "jp-46", 6, 358, 131, 360, 6, 5, {5}),
    ("古仁屋", "jp-46", 3, 226, 82, 59, 3, 5, {5}),
    ("宇検村湯湾", "jp-46", 6, 270, 57, 125, 6, 5, {5}),
    ("笠利空港", "jp-46", 4, 25, 4, 152, 4, 5, {3, 4, 5}),
    ("大川ダム", "jp-46", 325, 343, 136, 2741, 306, 2, {2, 3}),
    ("笠利丘陵", "jp-46", 121, 171, 95, 1509, 121, 3, {3}),
]
KNOWN_MISS = {"平塚馬入"}


@pytest.mark.parametrize("cp", CHECKPOINTS, ids=[c[0] for c in CHECKPOINTS])
def test_inline_checkpoint_table_matches_design_doc(cp):
    name, region, e, rw, rn, coast, above, table_zone, expected = cp
    p = TerrainPoint("0", "0", region, SUMMITS[region], float(e), float(rw), float(rn), float(e - above), float(coast))
    z = classify(p, RULE)
    assert z == table_zone
    if name in KNOWN_MISS:
        assert z not in expected  # known_miss: 規則の境の問題として明示する（黙って期待に合わせない）
    else:
        assert z in expected


def test_exactly_one_known_miss_in_the_checkpoint_table():
    misses = [c[0] for c in CHECKPOINTS if c[7] not in c[8]]
    assert misses == sorted(KNOWN_MISS)


def test_checkpoint_metrics_from_c68_match_expectations_if_present():
    """担当A の c68 --checkpoints が出す実データ（zone_checkpoints_metrics.csv。列に name・expect
    〔"1|2" の集合〕・known_miss を含む）。ファイルが無い間（統合前）は skip。
    known_miss 以外の全地点が期待の集合に入る。"""
    csv_path = FIXTURES / "zone_checkpoints_metrics.csv"
    if not csv_path.exists():
        pytest.skip("担当A の zone_checkpoints_metrics.csv がまだ無い")
    defn = zone_rule.load_zone_definition()
    points = zone_rule.load_terrain_points(csv_path, defn["terrain"], zone_rule.load_region_summits())
    with csv_path.open(encoding="utf-8", newline="") as f:
        items = list(csv.DictReader(f))
    assert len(items) == 43
    bad, misses = [], 0
    for it in items:
        z = classify(points[zone_rule.coord_key(it["lat"], it["lon"])], defn["rule"])
        expected = {int(x) for x in it["expect"].split("|") if x}
        if it["known_miss"] == "1":
            misses += 1
            assert z not in expected, f"{it['name']}: known_miss なのに期待に入っている（宣言を外す）"
        elif z not in expected:
            bad.append((it["name"], z, sorted(expected)))
    assert misses == 1
    assert bad == []


# ---------------------------------------------------------------------------
# zone.yaml の形・文言と rule: の整合
# ---------------------------------------------------------------------------

def test_real_zone_yaml_loads_with_v2_structure():
    d = zone_rule.load_zone_definition()
    assert zone_rule.terrain_params_digest(d["terrain"]) == "133bfa3b51f6"  # 担当A の c68 と合意した値
    assert d["definition_version"] == 2
    assert [z["zone"] for z in d["zones"]] == [1, 2, 3, 4, 5]
    assert d["zones"][2]["name_ja"] == "丘陵・台地・扇状地"
    assert "highland_basis" not in d and "highland_basis" not in d["rule"]
    assert "標高の低い島" in d["note_ja"]


def _metres(text):
    out = set()
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)(km|m)", text):
        v = float(num) * (1000 if unit == "km" else 1)
        out.add(v)
    return out


def test_condition_texts_state_the_same_numbers_as_rule_and_terrain():
    """condition_ja / ui_condition_ja の数値（m・km）が rule: / terrain: と一致する
    （閾値を直したのに文言を直し忘れた状態を落とす）。"""
    d = zone_rule.load_zone_definition()
    r, t = d["rule"], d["terrain"]
    expected = {
        1: {t["relief_wide_radius_m"], r["mountain_relief_min_m"]},
        2: {t["relief_wide_radius_m"], r["mountain_relief_min_m"]},
        3: set(),
        4: {r["lowland_elev_max_m"], t["relief_near_radius_m"], r["lowland_relief_max_m"],
            t["lowland_floor_radius_m"], r["lowland_above_floor_max_m"]},
        5: {r["coast_dist_max_m"], r["coast_elev_max_m"]},
    }
    for z in d["zones"]:
        for key in ("condition_ja", "ui_condition_ja"):
            got = _metres(z[key])
            assert got == {float(x) for x in expected[z["zone"]]}, (z["zone"], key, z[key])
    assert r["summit_ratio_min"] == 0.5
    for z in d["zones"][:2]:
        assert "半分" in z["condition_ja"] and "半分" in z["ui_condition_ja"]


def test_zone_definition_rejects_malformed_yaml(tmp_path):
    d = yaml.safe_load(zone_rule.ZONE_YAML.read_text(encoding="utf-8"))

    def write(mutate):
        dd = yaml.safe_load(yaml.safe_dump(d))
        mutate(dd)
        p = tmp_path / "z.yaml"
        p.write_text(yaml.safe_dump(dd, allow_unicode=True), encoding="utf-8")
        return p

    with pytest.raises(ZoneRuleError, match="definition_version"):
        zone_rule.load_zone_definition(write(lambda x: x.update(definition_version=1)))
    with pytest.raises(ZoneRuleError, match="rule"):
        zone_rule.load_zone_definition(write(lambda x: x["rule"].pop("coast_dist_max_m")))
    with pytest.raises(ZoneRuleError, match="余分"):
        zone_rule.load_zone_definition(write(lambda x: x["rule"].update(highland_basis=800)))
    with pytest.raises(ZoneRuleError, match="zones"):
        zone_rule.load_zone_definition(write(lambda x: x["zones"].pop()))


def test_params_digest_depends_on_terrain_values_not_key_order():
    t = real_terrain()
    assert zone_rule.terrain_params_digest(t) == zone_rule.terrain_params_digest(dict(reversed(list(t.items()))))
    t2 = dict(t, relief_wide_radius_m=500)
    assert zone_rule.terrain_params_digest(t2) != zone_rule.terrain_params_digest(t)
    assert len(zone_rule.terrain_params_digest(t)) == 12


def test_real_region_yaml_declares_summits_if_present():
    summits = zone_rule.load_region_summits()
    if not summits:
        pytest.skip("region.yaml の terrain.summit は担当C が書く（統合前）")
    assert summits.get("jp-14") == 1673 and summits.get("jp-46") == 694


# ---------------------------------------------------------------------------
# load_terrain_points / build_place が止まる条件（受け入れ基準 3）
# ---------------------------------------------------------------------------

SITES = [
    ("jma_stations_kanagawa__s1", "地点1", 35.0, 139.0, 10.0, "src", "ref", 1, None),
    ("jma_stations_kanagawa__s2", "地点2", 35.1, 139.1, 20.0, "src", "ref", 3, None),
]


def test_build_place_runs_with_hand_written_fixture_and_without_network(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("ネットワークに出てはいけない")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    conn, counts = build_place_with_fixtures(tmp_path, monkeypatch, SITES)
    zones = conn.execute(
        "SELECT place_id, region_id FROM place WHERE place_kind='zone' ORDER BY place_id").fetchall()
    assert [z["place_id"] for z in zones] == [f"common:place:zone.r2r.{n}" for n in range(1, 6)]
    assert all(z["region_id"] is None for z in zones)
    assert counts["place_relation"] == 2   # 対象（zone が付く）地点数
    refs = conn.execute("SELECT external_key FROM place_source_ref WHERE key_space='zone' ORDER BY 1").fetchall()
    assert [r[0] for r in refs] == ["1", "2", "3", "4", "5"]
    ref = conn.execute("SELECT definition_ref FROM place WHERE place_id='common:place:zone.r2r.3'").fetchone()[0]
    assert "definition_version: 2" in ref and "標高の低い島" in ref
    basis = conn.execute("SELECT DISTINCT basis FROM place_relation WHERE parent_id LIKE '%zone.r2r%'").fetchall()
    assert len(basis) == 1 and "zone.yaml v2" in basis[0][0]
    assert zone_rule.terrain_params_digest(real_terrain()) in basis[0][0]


def test_build_place_halts_on_params_digest_mismatch(tmp_path, monkeypatch):
    rows = [zone_row(r[2], r[3], r[7], digest="deadbeef0000") for r in SITES]
    with pytest.raises(ZoneRuleError, match="params_digest"):
        build_place_with_fixtures(tmp_path, monkeypatch, SITES, terrain_rows=rows)


def test_build_place_halts_on_summit_mismatch_with_region_yaml(tmp_path, monkeypatch):
    rows = [zone_row(r[2], r[3], r[7], summit_m=SUMMIT_M + 10) for r in SITES]
    with pytest.raises(ZoneRuleError, match="summit_m"):
        build_place_with_fixtures(tmp_path, monkeypatch, SITES, terrain_rows=rows)


def test_build_place_halts_and_lists_sites_whose_coordinates_are_missing(tmp_path, monkeypatch):
    rows = [zone_row(SITES[0][2], SITES[0][3], 1)]   # 地点2の座標が無い
    with pytest.raises(AssertionError, match="c68.*jma_stations_kanagawa__s2"):
        build_place_with_fixtures(tmp_path, monkeypatch, SITES, terrain_rows=rows)


def test_build_place_halts_when_ledger_zone_differs_from_classify(tmp_path, monkeypatch):
    rows = [zone_row(SITES[0][2], SITES[0][3], 1), zone_row(SITES[1][2], SITES[1][3], 4)]  # 台帳は 3
    with pytest.raises(AssertionError, match="m09_site_zone"):
        build_place_with_fixtures(tmp_path, monkeypatch, SITES, terrain_rows=rows)


def test_build_place_halts_when_region_has_no_summit_declaration(tmp_path, monkeypatch):
    rows = [zone_row(r[2], r[3], r[7], region_id="jp-99") for r in SITES]
    with pytest.raises(ZoneRuleError, match="terrain.summit の宣言が無い"):
        build_place_with_fixtures(tmp_path, monkeypatch, SITES, terrain_rows=rows)


def test_load_terrain_points_rejects_duplicate_coordinates_and_missing_columns(tmp_path):
    t = real_terrain()
    region = tmp_path / "region.yaml"
    write_region_yaml(region)
    sums = zone_rule.load_region_summits(region)
    dup = tmp_path / "dup.csv"
    write_terrain_csv(dup, [zone_row(35.0, 139.0, 1), zone_row(35.0, 139.0, 2)])
    with pytest.raises(ZoneRuleError, match="重複"):
        zone_rule.load_terrain_points(dup, t, sums)
    short = tmp_path / "short.csv"
    short.write_text("lat,lon\n35,139\n", encoding="utf-8")
    with pytest.raises(ZoneRuleError, match="列が足りない"):
        zone_rule.load_terrain_points(short, t, sums)
    with pytest.raises(ZoneRuleError, match="c68"):
        zone_rule.load_terrain_points(tmp_path / "none.csv", t, sums)


def test_zone_fingerprint_includes_terrain_points_in_full_mode_only(tmp_path):
    from registry import common
    for sub in ("scripts/registry", "registry", "data/processed"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "registry/x.yaml").write_text("a: 1\n", encoding="utf-8")
    full0 = common.compute_input_fingerprint(tmp_path, common.MODE_FULL)
    files0 = common.compute_input_fingerprint(tmp_path, common.MODE_FILES_ONLY)
    (tmp_path / "data/processed/terrain_points.csv").write_text("lat,lon\n", encoding="utf-8")
    assert common.compute_input_fingerprint(tmp_path, common.MODE_FULL) != full0
    assert common.compute_input_fingerprint(tmp_path, common.MODE_FILES_ONLY) == files0
