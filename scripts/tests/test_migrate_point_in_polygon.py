"""`scripts/migrate/point_in_polygon.py` の単体テスト（ADR-0026、O-2a）。

`web/scripts/build-geo.mjs:112-165` の移植を、GeoJSON ファイルを介さず
`Polygon`/`Grid` を直接組み立てて検証する（フィクスチャ sqlite・原本DB不要）。
"""
import json

from migrate import point_in_polygon as pip


def _square(id_, x0, y0, x1, y1, holes=()):
    """`(x0,y0)`〜`(x1,y1)` の矩形1つを持つ `Polygon`（穴は `holes` に矩形の
    `(x0,y0,x1,y1)` タプルで渡す）。"""
    outer = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    rings = [outer]
    for hx0, hy0, hx1, hy1 in holes:
        rings.append([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1), (hx0, hy0)])
    bbox = pip._bbox_of([rings])
    return pip.Polygon(id=id_, rings=[rings], bbox=bbox)


def test_simple_square_inside_and_outside():
    poly = _square("A", 0.0, 0.0, 1.0, 1.0)
    grid = pip.build_grid([poly])

    matched, near = pip.locate(0.5, 0.5, [poly], grid)
    assert matched == ["A"]
    assert near is False

    matched, near = pip.locate(2.0, 2.0, [poly], grid)
    assert matched == []


def test_hole_excludes_interior_point():
    poly = _square("A", 0.0, 0.0, 10.0, 10.0, holes=[(4.0, 4.0, 6.0, 6.0)])
    grid = pip.build_grid([poly])

    # 穴の外・本体の中
    matched, _ = pip.locate(1.0, 1.0, [poly], grid)
    assert matched == ["A"]

    # 穴の中
    matched, _ = pip.locate(5.0, 5.0, [poly], grid)
    assert matched == []


def test_multipolygon_matches_either_part():
    poly = pip.Polygon(
        id="A",
        rings=[
            [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]],
            [[(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0), (10.0, 10.0)]],
        ],
        bbox=(0.0, 0.0, 11.0, 11.0),
    )
    grid = pip.build_grid([poly])

    matched, _ = pip.locate(0.5, 0.5, [poly], grid)
    assert matched == ["A"]
    matched, _ = pip.locate(10.5, 10.5, [poly], grid)
    assert matched == ["A"]
    matched, _ = pip.locate(5.0, 5.0, [poly], grid)
    assert matched == []


def test_point_in_two_overlapping_polygons_reports_both():
    a = _square("A", 0.0, 0.0, 2.0, 2.0)
    b = _square("B", 1.0, 1.0, 3.0, 3.0)
    grid = pip.build_grid([a, b])

    matched, _ = pip.locate(1.5, 1.5, [a, b], grid)
    assert sorted(matched) == ["A", "B"]


def test_load_polygons_handles_polygon_and_multipolygon_and_skips_other_types(tmp_path):
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"watershed_id": "P1"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
                },
            },
            {
                "type": "Feature",
                "properties": {"watershed_id": "P2"},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[10.0, 10.0], [11.0, 10.0], [11.0, 11.0], [10.0, 11.0], [10.0, 10.0]]],
                        [[[20.0, 20.0], [21.0, 20.0], [21.0, 21.0], [20.0, 21.0], [20.0, 20.0]]],
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"watershed_id": "P3"},
                "geometry": {"type": "Point", "coordinates": [5.0, 5.0]},
            },
        ],
    }
    path = tmp_path / "test.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")

    polys = pip.load_polygons(path)
    assert [p.id for p in polys] == ["P1", "P2"]


def test_exact_recheck_matches_float_for_ordinary_points():
    """際どくない普通の点では `point_in_polygon_exact` と `point_in_polygon`
    （float）が一致する（Fraction 側の実装自体の健全性を確認する）。
    """
    poly = _square("A", 0.0, 0.0, 1.0, 1.0)
    grid = pip.build_grid([poly])

    for x, y in [(0.5, 0.5), (0.25, 0.75), (1.5, 1.5)]:
        matched, _ = pip.locate(x, y, [poly], grid)
        exact = pip.locate_exact(x, y, [poly], grid)
        assert sorted(matched) == sorted(exact)


def test_near_threshold_crossing_is_flagged_and_exact_recheck_agrees():
    """辺の x 座標ぎりぎり（`DEFAULT_NEAR_THRESHOLD` 未満の差）にある点は
    `near_boundary=True` になり、`locate_exact()` でも同じ結果が出ることを
    確認する（ADR-0026 の機械検証2の健全性チェック）。
    """
    poly = _square("A", 0.0, 0.0, 1.0, 1.0)
    grid = pip.build_grid([poly])

    # 辺 x=1.0 の内側ぎりぎり（1e-9 未満の差）。
    x = 1.0 - 1e-10
    y = 0.5
    matched, near = pip.locate(x, y, [poly], grid)
    assert near is True
    exact = pip.locate_exact(x, y, [poly], grid)
    assert sorted(matched) == sorted(exact)


def test_far_from_boundary_is_not_flagged_near():
    poly = _square("A", 0.0, 0.0, 1.0, 1.0)
    grid = pip.build_grid([poly])
    _matched, near = pip.locate(0.5, 0.5, [poly], grid)
    assert near is False
