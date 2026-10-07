"""c89b_edna_site_coords（地点の推定座標台帳）のテスト。合成の河川線・町丁ポリゴンで、
手順 1〜7（設計 §5.2・§11）の各分岐を確かめる。実データの地図は使わない。"""
import csv

import pytest

pytest.importorskip("shapely")   # CI の requirements.txt に shapely は無い（開発用ツールのテスト）
from shapely.geometry import LineString, Polygon
from shapely.ops import transform

import c89b_edna_site_coords as c89b


def m(geom):
    """lon/lat の図形 → 平面メートル。"""
    return transform(c89b.to_m, geom)


# 経度 139.30〜139.40・緯度 35.40 付近（1km ≒ 0.011 度）に置いた合成の地図
TOWN_A = Polygon([(139.300, 35.400), (139.330, 35.400), (139.330, 35.420), (139.300, 35.420)])   # 約 2.7km 四方
TOWN_B = Polygon([(139.330, 35.400), (139.360, 35.400), (139.360, 35.420), (139.330, 35.420)])
# 中津川: A 町の中を東西に 2 km 通る（短い）
NAKATSU = LineString([(139.305, 35.410), (139.323, 35.410)])
# 長い本流: 町をまたいで 20 km 近く
LONG = LineString([(139.20, 35.41), (139.40, 35.41)])
# A 町から遠い同名の線（nearest 用）。A 町の東端から約 1.1 km
FAR = LineString([(139.342, 35.405), (139.350, 35.405)])


def make_ctx(**kw):
    lines = {("中津川", "酒匂川"): [m(NAKATSU)],
             ("相模川", "相模川"): [m(LONG)],
             ("遠川", "酒匂川"): [m(FAR)]}
    towns = {"厚木市": [m(TOWN_A)], "愛川町": [m(TOWN_B)], "横浜市中区": [m(TOWN_A)], "横浜市西区": [m(TOWN_B)]}
    w12 = [(Polygon([(139.28, 35.38), (139.40, 35.38), (139.40, 35.44), (139.28, 35.44)]), "酒匂川")]
    grid = {(3541, 13931), (3541, 13930)}
    return c89b.Context(kw.get("lines", lines), towns, w12, grid)


def site(water="酒匂川", trib="中津川", muni="厚木市", key="r3:K-1"):
    return {"site_key": key, "water_system_ja": water, "tributary_ja": trib, "municipality_ja": muni}


def test_norm_variants():
    assert c89b.norm("茅ケ崎市") == c89b.norm("茅ヶ崎市")
    assert c89b.norm("早淵川") == c89b.norm("早渕川")
    assert c89b.norm("森戸川（小田原）") == "森戸川"
    assert c89b.split_munis("平塚市、茅ケ崎市") == ["平塚市", "茅ケ崎市"]
    assert c89b.split_munis("松田町・開成町") == ["松田町", "開成町"]


def test_river_in_municipality():
    r = c89b.estimate(site(), make_ctx())
    assert r["coord_source"] == "estimated_from_name" and r["coord_method"] == "river_in_municipality"
    # 位置は中津川の線上（緯度 35.41・A 町の経度範囲）
    assert abs(r["lat"] - 35.41) < 1e-3 and 139.305 <= r["lon"] <= 139.323
    # 切り取った線は約 1.6km（広がり ≒ 0.8km）+ 300m → 100m 単位に切り上げ。下限 500m
    assert r["coordinate_uncertainty_m"] % 100 == 0 and 1000 <= r["coordinate_uncertainty_m"] <= 1500


def test_uncertainty_floor_and_rounding():
    ln = LineString([(139.310, 35.410), (139.3105, 35.410)])       # 約 40 m の短い線
    r = c89b.estimate(site(), make_ctx(lines={("中津川", "酒匂川"): [m(ln)]}))
    assert r["coordinate_uncertainty_m"] == 500                      # 下限


def test_multiple_municipalities_union_and_ward_union():
    # 2 市町村の和集合で切り取る（愛川町まで線が伸びる）
    ln = LineString([(139.305, 35.410), (139.345, 35.410)])
    r = c89b.estimate(site(muni="厚木市・愛川町"), make_ctx(lines={("中津川", "酒匂川"): [m(ln)]}))
    assert r["coord_source"] == "estimated_from_name" and r["coord_method"] == "river_in_municipality"
    # 政令市は区の和集合（横浜市 = 中区 + 西区）
    ctx = make_ctx(lines={("中津川", "酒匂川"): [m(ln)]})
    assert ctx.muni_geom("横浜市").area == pytest.approx(ctx.muni_geom("厚木市").area * 2, rel=0.01)
    r = c89b.estimate(site(muni="横浜市"), ctx)
    assert r["coord_source"] == "estimated_from_name"


def test_river_nearest_municipality_adds_distance():
    r = c89b.estimate(site(trib="遠川", muni="厚木市"), make_ctx())
    assert r["coord_method"] == "river_nearest_municipality" and r["coord_source"] == "estimated_from_name"
    # A 町の東端（139.330）から線の西端（139.342）まで約 1km → 精度は距離 + 300m 以上
    assert 1300 <= r["coordinate_uncertainty_m"] <= 1700
    assert 139.340 <= r["lon"] <= 139.351


def test_tributary_blank_or_dash_uses_water_system():
    ctx = make_ctx()
    r = c89b.estimate(site(water="相模川", trib="-", muni="厚木市"), ctx)
    assert r["coord_method"] in ("river_in_municipality", "none_uncertainty_over_limit")
    # 長い本流を A 町（約 2.7km）で切り取ると 10km 以内・流域 1 つに収まる → 座標あり
    assert r["coord_source"] == "estimated_from_name" and r["coordinate_uncertainty_m"] <= 10000
    assert c89b.estimate(site(water="相模川", trib="", muni="厚木市"), ctx)["lat"] == r["lat"]


def test_none_when_uncertainty_over_limit():
    # 約 51km の本流を、それを覆う広い町で切ると広がり 25km → 10,000m 超で none（lat/lon/精度が全部 NULL）
    big = Polygon([(139.0, 35.3), (139.6, 35.3), (139.6, 35.5), (139.0, 35.5)])
    ctx = make_ctx(lines={("相模川", "相模川"): [m(LineString([(139.0, 35.41), (139.6, 35.41)]))]})
    ctx.towns["厚木市"] = [m(big)]
    ctx._muni_cache.clear()
    r = c89b.estimate(site(water="相模川", trib="-", muni="厚木市"), ctx)
    assert r["coord_source"] == "none" and r["coord_method"] == "none_uncertainty_over_limit"
    assert r["lat"] is None and r["lon"] is None and r["coordinate_uncertainty_m"] is None


def ctx_with_watersheds(polys):
    base = make_ctx()
    return c89b.Context(base.lines, base.towns, [(p, "酒匂川") for p in polys], base.grid01)


def test_multi_watershed_is_none():
    # 中津川（139.305〜139.323）が 2 つの流域に半分ずつ → 98% 未満 → none
    west = Polygon([(139.28, 35.38), (139.314, 35.38), (139.314, 35.44), (139.28, 35.44)])
    east = Polygon([(139.314, 35.38), (139.40, 35.38), (139.40, 35.44), (139.314, 35.44)])
    r = c89b.estimate(site(), ctx_with_watersheds([west, east]))
    assert r["coord_source"] == "none" and r["coord_method"] == "none_multi_watershed"
    assert "multi_watershed" in r["evidence"] and r["lat"] is None


def test_single_watershed_ok_and_share_threshold():
    one = Polygon([(139.28, 35.38), (139.40, 35.38), (139.40, 35.44), (139.28, 35.44)])
    r = c89b.estimate(site(), ctx_with_watersheds([one]))
    assert r["coord_source"] == "estimated_from_name" and "流域" in r["evidence"]
    # 線の約 99% が 1 流域、残り 1% が隣 → 98% 以上なので座標あり
    a = Polygon([(139.28, 35.38), (139.3229, 35.38), (139.3229, 35.44), (139.28, 35.44)])
    b = Polygon([(139.3229, 35.38), (139.40, 35.38), (139.40, 35.44), (139.3229, 35.44)])
    assert c89b.estimate(site(), ctx_with_watersheds([a, b]))["coord_source"] == "estimated_from_name"
    # 流域が無い（W12 の外）なら判定できず none
    far = Polygon([(140.0, 36.0), (140.1, 36.0), (140.1, 36.1), (140.0, 36.1)])
    assert c89b.estimate(site(), ctx_with_watersheds([far]))["coord_method"] == "none_multi_watershed"


@pytest.mark.parametrize("trib,method", [
    ("小水路", "none_generic_tributary"), ("不明", "none_generic_tributary"), ("本流", "none_generic_tributary"),
    ("湧水", "none_generic_tributary"), ("用水", "none_generic_tributary"), ("厚木市内小河川", "none_generic_tributary"),
    ("二ヶ領用水", "none_river_not_in_w05"), ("存在しない川", "none_river_not_in_w05"),
])
def test_none_for_generic_or_unknown_names(trib, method):
    r = c89b.estimate(site(trib=trib), make_ctx())
    assert r["coord_source"] == "none" and r["coord_method"] == method and r["lat"] is None


def test_none_when_water_system_differs():
    # 同名の川でも水系が違えば候補にしない（中津川は県内に複数ある）
    r = c89b.estimate(site(water="相模川", trib="中津川"), make_ctx())
    assert r["coord_method"] == "none_river_not_in_w05"


def test_none_when_municipality_unmatched():
    r = c89b.estimate(site(muni="不明"), make_ctx())
    assert r["coord_method"] == "none_municipality_unmatched" and r["coord_source"] == "none"
    # 一部だけ引ければ、引けた市町村で推定し、引けなかったものを evidence に残す
    r = c89b.estimate(site(muni="厚木市・不明"), make_ctx())
    assert r["coord_source"] == "estimated_from_name" and "不明" in r["evidence"]


def test_watershed_check_warns_on_mismatch_and_outside():
    ctx = make_ctx()
    r = c89b.estimate(site(), ctx)
    assert c89b.check_watershed(r, site(), ctx) is None
    assert c89b.check_watershed(r, site(water="相模川"), ctx).startswith("WARN:")      # 水系の食い違い
    out = dict(r, lat=36.5, lon=140.0)
    assert c89b.check_watershed(out, site(), ctx) == "WARN:W12 流域の外"
    none = c89b.estimate(site(trib="小水路"), ctx)
    assert c89b.check_watershed(none, site(), ctx) is None                            # 座標なしは検算しない


def test_grid01_ok():
    ctx = make_ctx()
    ok = {"lat": 35.4105, "lon": 139.3105}
    assert c89b.grid01_ok(ok, ctx) == 1                                               # 3541,13931
    assert c89b.grid01_ok({"lat": 35.5, "lon": 139.5}, ctx) == 0                      # registry に無い格子
    assert c89b.grid01_ok({"lat": None, "lon": None}, ctx) == ""


def test_build_ledger_columns_and_reviewed_rows_are_kept():
    ctx = make_ctx()
    sites = [site(key="b:2", trib="小水路"), site(key="a:1")]
    led = c89b.build_ledger(sites, ctx)
    assert [r["site_key"] for r in led] == ["a:1", "b:2"]                # 決定的（site_key 順）
    assert list(led[0]) == c89b.LEDGER_COLS
    assert led[0]["coord_source"] == "estimated_from_name" and led[0]["reviewed"] == 0
    assert led[1]["coord_source"] == "none" and led[1]["lat"] == "" and led[1]["coordinate_uncertainty_m"] == ""
    # 人が読み取った reviewed=1 の行は再実行で上書きしない
    manual = {c: "" for c in c89b.LEDGER_COLS}
    manual.update(site_key="a:1", lat="35.5", lon="139.5", coord_source="map_image",
                  coordinate_uncertainty_m="1500", coord_method="georeferenced_fig1", evidence="残差 400m", reviewed="1")
    led2 = c89b.build_ledger(sites, ctx, existing=[manual])
    assert led2[0]["coord_source"] == "map_image" and led2[0]["lat"] == "35.5"
    assert led2[1]["coord_source"] == "none"


def test_summarize_reports_distributions():
    ctx = make_ctx()
    sites = [site(key="a:1"), site(key="b:2", trib="小水路")]
    led = c89b.build_ledger(sites, ctx)
    text = c89b.summarize(led, {"a:1": 10, "b:2": 5})
    assert "estimated_from_name: 1 / 10" in text and "none: 1 / 5" in text
    assert "精度(m)の分布" in text and "grid01_ok=0" in text and "警告" in text


def test_write_ledger_roundtrip(tmp_path):
    led = c89b.build_ledger([site()], make_ctx())
    p = tmp_path / "sub" / "ledger.csv"
    c89b.write_ledger(p, led)
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    assert rows[0]["site_key"] == "r3:K-1" and list(rows[0]) == c89b.LEDGER_COLS
