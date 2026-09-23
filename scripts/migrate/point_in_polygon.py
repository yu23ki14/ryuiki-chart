"""流域ポリゴン（W12、377面、`data/processed/nlni_w12_watersheds.geojson`）への
点内包判定の純 Python 実装（ADR-0006 規約2の改定、ADR-0026、O-2a）。

`web/scripts/build-geo.mjs:112-165` の移植——0.02度の bbox グリッドで候補ポリゴンを
絞り込み、外環の even-odd 判定→穴、MultiPolygon 対応。**shapely は使わない**
（実測: 224,282 distinct 座標で GEOS と不一致0、約9秒。CI は `requirements.txt`
〔PyYAML・pytest だけ〕しか入れないため、shapely への依存を持ち込まない）。

**v1 の 0.001度メモ化はここでは行わない。** v1（`web/scripts/build-geo.mjs:166-175`）は
座標を 0.001度に丸めたバケットで判定結果をメモ化し、「バケットに最初に来た記録の
実座標の判定結果」を同じバケットの全記録に配る——走査順（≒rowid順）に依存する近似
（`docs/plans/PHASE_B_OCCURRENCE.md` F3）。このモジュールが提供するのは**正確な**
点内包判定であり、v1 の癖の再現は射影側（`scripts/b08_project_occurrence_v1.py`）の
責務（ADR-0024/0025 と同じ「v1 の癖はキューブ/レジストリに焼き込まない」原則）。

各点について候補ポリゴン**全部**を判定し、実際に一致したポリゴンの id を全部返す
（v1 の `locate()` のように最初の1件で打ち切らない——複数面への帰属や境界上の
判定の際どさを検出するのがこのモジュールの仕事。呼び出し側〔`scripts/b09_build_occurrence_place.py`〕
が「ちょうど1つに一致」だけを解決とみなす）。

## 浮動小数点の曖昧さ（ADR-0026）

even-odd 判定はエッジの交差 x 座標 `x_cross` と点の x 座標を比較する
（`x < x_cross`）。`abs(x - x_cross)` が閾値（既定 `DEFAULT_NEAR_THRESHOLD=1e-9`）
未満のとき、その交差は浮動小数点の丸め誤差で結果が入れ替わりうる「際どい」交差として
扱う（`locate()` の戻り値 `near_boundary`）。際どいと判定された distinct 座標は、
呼び出し側が `locate_exact()`（`fractions.Fraction` による厳密有理数演算）で
やり直し、float 版の結果と一致するかを確認する——実測（`data/db/ryuiki.sqlite`
全 distinct 座標 224,282件、2026-09-23）では際どい交差自体が0件だった
（最短の余裕は 4.4e-9度）。
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass
from fractions import Fraction

# v1（`web/scripts/build-geo.mjs:117`）と同じグリッドセル幅。
CELL = 0.02

# `abs(x - x_cross) < DEFAULT_NEAR_THRESHOLD` を「際どい交差」とみなす閾値
# （ADR-0026「機械検証」節）。実測の最短余裕（4.4e-9度）より1桁近い値にして
# ある——閾値を実測の余裕ぎりぎりに置くと、次にデータが増えたときに際どい
# 交差が「たまたま」閾値のすぐ外側に来て検知漏れになりかねないため、余裕を
# 持たせて早めに拾う。
DEFAULT_NEAR_THRESHOLD = 1e-9

Point = tuple[float, float]
Ring = list[Point]
# 1つの Polygon（外環+穴）の座標配列。GeoJSON の Polygon.coordinates と同じ形
# （rings[0] が外環、rings[1:] が穴）。
PolygonCoordinates = list[Ring]


@dataclass(frozen=True)
class Polygon:
    """1 GeoJSON feature 分（単純な Polygon なら要素1つ、MultiPolygon なら
    複数要素の）`rings` を持つ。JS 版 `polys.push({id, rings, bbox})` の
    `rings`（`Polygon` なら `[geometry.coordinates]`、`MultiPolygon` なら
    `geometry.coordinates` の各要素を展開したもの）と同じ形。
    """

    id: str
    rings: list[PolygonCoordinates]
    bbox: tuple[float, float, float, float]


def _bbox_of(rings: list[PolygonCoordinates]) -> tuple[float, float, float, float]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for poly in rings:
        for ring in poly:
            for x, y in ring:
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    return minx, miny, maxx, maxy


def load_polygons(geojson_path, id_property: str = "watershed_id") -> list[Polygon]:
    """`geojson_path`（GeoJSON FeatureCollection）を読み、`Polygon` のリストにする。

    `web/scripts/build-geo.mjs:120-136` の移植。Polygon/MultiPolygon 以外の
    geometry type は v1 と同じく黙ってスキップする（実データには現れない
    ——実測: 377 feature 全件が Polygon）。
    """
    data = json.loads(pathlib.Path(geojson_path).read_text(encoding="utf-8"))
    polys: list[Polygon] = []
    for feat in data["features"]:
        geom = feat["geometry"]
        gtype = geom["type"]
        if gtype == "Polygon":
            rings = [geom["coordinates"]]
        elif gtype == "MultiPolygon":
            rings = list(geom["coordinates"])
        else:
            continue
        pid = feat["properties"][id_property]
        polys.append(Polygon(id=pid, rings=rings, bbox=_bbox_of(rings)))
    return polys


# (grid_x, grid_y) -> polys のインデックス列
Grid = dict[tuple[int, int], list[int]]


def build_grid(polys: list[Polygon], cell: float = CELL) -> Grid:
    """`web/scripts/build-geo.mjs:137-144` の移植: 各ポリゴンの bbox がかぶる
    0.02度セル全部に、そのポリゴンの `polys` 内 index を登録する。
    """
    grid: Grid = {}
    for pi, p in enumerate(polys):
        minx, miny, maxx, maxy = p.bbox
        gx0, gx1 = math.floor(minx / cell), math.floor(maxx / cell)
        gy0, gy1 = math.floor(miny / cell), math.floor(maxy / cell)
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                grid.setdefault((gx, gy), []).append(pi)
    return grid


def _point_in_ring(x: float, y: float, ring: Ring, threshold: float) -> tuple[bool, bool]:
    """`web/scripts/build-geo.mjs:147-154` の even-odd 判定の移植。

    戻り値: `(内側か, 際どい交差が1つでもあったか)`。
    """
    inside = False
    near = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if abs(x - x_cross) < threshold:
                near = True
            if x < x_cross:
                inside = not inside
        j = i
    return inside, near


def _point_in_ring_exact(x: Fraction, y: Fraction, ring: list[tuple[Fraction, Fraction]]) -> bool:
    """`_point_in_ring` と同じ式を `Fraction` の厳密演算で行う（丸め誤差なし）。"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def point_in_polygon(
    x: float, y: float, poly: Polygon, threshold: float = DEFAULT_NEAR_THRESHOLD
) -> tuple[bool, bool]:
    """`web/scripts/build-geo.mjs:155-165` の移植（穴あり）。

    戻り値: `(poly に含まれるか, 際どい交差が1つでもあったか)`。
    """
    minx, miny, maxx, maxy = poly.bbox
    if x < minx or x > maxx or y < miny or y > maxy:
        return False, False
    near_any = False
    for rings in poly.rings:
        outer = rings[0]
        in_outer, near = _point_in_ring(x, y, outer, threshold)
        near_any = near_any or near
        if not in_outer:
            continue
        in_hole = False
        for h in range(1, len(rings)):
            ih, nearh = _point_in_ring(x, y, rings[h], threshold)
            near_any = near_any or nearh
            if ih:
                in_hole = True
                break
        if not in_hole:
            return True, near_any
    return False, near_any


def point_in_polygon_exact(x: Fraction, y: Fraction, poly: Polygon) -> bool:
    """`point_in_polygon` と同じ判定を `Fraction` の厳密演算でやり直す。

    `locate()` が `near_boundary=True` を返した distinct 座標だけに使う想定
    （bbox は事前にグリッドで絞り込み済みの候補に対して呼ばれるため、
    ここでは bbox の再チェックをしない）。
    """
    for rings in poly.rings:
        outer = [(Fraction(px), Fraction(py)) for px, py in rings[0]]
        if not _point_in_ring_exact(x, y, outer):
            continue
        in_hole = False
        for h in range(1, len(rings)):
            hole = [(Fraction(px), Fraction(py)) for px, py in rings[h]]
            if _point_in_ring_exact(x, y, hole):
                in_hole = True
                break
        if not in_hole:
            return True
    return False


def candidates_for(x: float, y: float, grid: Grid, cell: float = CELL) -> list[int]:
    """`(x, y)` が属する 0.02度セルに登録済みのポリゴン index 列を返す
    （無ければ空リスト）。`locate()`/`locate_exact()` が共有する。
    """
    gx, gy = math.floor(x / cell), math.floor(y / cell)
    return list(grid.get((gx, gy), ()))


def locate(
    x: float,
    y: float,
    polys: list[Polygon],
    grid: Grid,
    cell: float = CELL,
    threshold: float = DEFAULT_NEAR_THRESHOLD,
) -> tuple[list[str], bool]:
    """点 `(x, y)`（= lon, lat）を含む全ポリゴンの id を返す。

    v1 の `locate()` と違い最初の1件で打ち切らない——複数面への帰属を
    呼び出し側が検出できるようにするため。戻り値: `(matched_ids, near_boundary)`。
    """
    matched: list[str] = []
    near_any = False
    for pi in candidates_for(x, y, grid, cell):
        p = polys[pi]
        hit, near = point_in_polygon(x, y, p, threshold)
        near_any = near_any or near
        if hit:
            matched.append(p.id)
    return matched, near_any


def locate_exact(x: float, y: float, polys: list[Polygon], grid: Grid, cell: float = CELL) -> list[str]:
    """`locate()` が `near_boundary=True` を返した点だけに使う、厳密再判定。

    候補ポリゴンの集合は `locate()` と同じグリッド（float の bbox 由来）を使う
    ——グリッドのセル境界自体は候補の絞り込みにすぎず判定の対象ではないため、
    厳密演算でも同じ候補集合を使ってよい。
    """
    fx, fy = Fraction(x), Fraction(y)
    matched: list[str] = []
    for pi in candidates_for(x, y, grid, cell):
        p = polys[pi]
        if point_in_polygon_exact(fx, fy, p):
            matched.append(p.id)
    return matched
