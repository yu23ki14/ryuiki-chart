"""流域ポリゴン（W12、377面、`data/processed/nlni_w12_watersheds.geojson`）への
点内包判定の純 Python 実装（ADR-0006 規約2の改定、ADR-0026、O-2a）。

`web/scripts/build-geo.mjs:112-165` の移植——0.02度の bbox グリッドで候補ポリゴンを
絞り込み、外環の even-odd 判定→穴、MultiPolygon 対応。**shapely は使わない**
（実測: 224,282 distinct 座標で GEOS と不一致0、約9秒。CI は `requirements.txt`
〔PyYAML・pytest だけ〕しか入れないため、shapely への依存を持ち込まない）。

**v1 の 0.001度メモ化はここでは行わない。** このモジュールが提供するのは**正確な**
点内包判定であり、v1 の癖（走査順依存のメモ化）の再現は射影側
（`scripts/b08_project_occurrence_v1.py`）の責務（ADR-0024/0025 と同じ「v1 の癖は
キューブ/レジストリに焼き込まない」原則。経緯・実測は
`docs/plans/PHASE_B_OCCURRENCE.md` F3・§15・§16）。

各点について候補ポリゴン**全部**を判定し、実際に一致したポリゴンの id を全部返す
（v1 の `locate()` のように最初の1件で打ち切らない——複数面への帰属や境界上の
判定の際どさを検出するのがこのモジュールの仕事。呼び出し側〔`scripts/b09_build_occurrence_place.py`〕
が「ちょうど1つに一致」だけを解決とみなす）。

## 際どい判定と境界上の点（ADR-0026 D1）

`near`（際どい判定）は**点から候補ポリゴンの辺（外環・穴のどの辺も、頂点上を含む）
までの距離**が閾値（既定 `DEFAULT_NEAR_THRESHOLD=1e-9`）未満かどうかで、even-odd の
交差判定とは独立に全ての辺について行う（`_point_in_ring`。この形にした理由・
以前の実装の穴は `docs/plans/PHASE_B_OCCURRENCE.md` §16 参照——ここでは繰り返さない）。

`near=True` の distinct 座標は、呼び出し側が2段階で確認する:

1. **厳密な境界判定**（`polygon_boundary_contains_exact()`/`on_boundary()`。
   `fractions.Fraction` で「点が辺〔頂点を含む〕の上に厳密に乗っているか」を判定）。
   乗っていれば ADR-0026 D1 の「境界上」に該当し、呼び出し側は無条件に止める
   （推測で割り当てない）。
2. 厳密には乗っていない（float の近さだけだった）場合は `locate_exact()`
   （厳密有理数演算によるフルの点内包判定）で float 版の結果と一致するかを確認する
   （食い違えば呼び出し側が止める）。

実測（`data/db/ryuiki.sqlite` 全 distinct 座標 224,282件、2026-09-23）では
際どい判定・境界上の点のどちらも0件だった（最短の余裕は 4.4e-9度。この0件が
今回のデータ〔流域どうしの隣接が疎〕に固有であることは ADR-0026「影響」節参照）。

## 辺の bbox は `Polygon` 構築時に1回だけ前計算する

`Polygon.ring_edges`（`__post_init__` で `rings` から自動的に作る）が、辺ごとの
`(xi, yi, xj, yj, 辺のbbox)` を持つ。`_point_in_ring` はこれを読むだけで、
点ごとに `min()`/`max()` を計算し直さない（効率。distinct 座標224,282件に対する
実測で約52%短縮——`docs/plans/PHASE_B_OCCURRENCE.md` §17）。even-odd・`Fraction`・
境界判定のロジック自体はこの前計算の前後で変えていない。
"""
from __future__ import annotations

import json
import math
import pathlib
from dataclasses import dataclass, field
from fractions import Fraction

# v1（`web/scripts/build-geo.mjs:117`）と同じグリッドセル幅。
CELL = 0.02

# 点から辺までの距離がこの閾値未満なら「際どい」とみなす（モジュール docstring
# 「際どい判定と境界上の点」参照）。実測の最短余裕（4.4e-9度）より1桁
# 近い値にしてある——閾値を実測の余裕ぎりぎりに置くと、次にデータが増えたときに
# 際どい判定が「たまたま」閾値のすぐ外側に来て検知漏れになりかねないため、
# 余裕を持たせて早めに拾う。
DEFAULT_NEAR_THRESHOLD = 1e-9

Point = tuple[float, float]
Ring = list[Point]
# 1つの Polygon（外環+穴）の座標配列。GeoJSON の Polygon.coordinates と同じ形
# （rings[0] が外環、rings[1:] が穴）。
PolygonCoordinates = list[Ring]

# 辺1本の前計算済みデータ: (xi, yi, xj, yj, 辺のbboxのmin_x, max_x, min_y, max_y)。
# `_point_in_ring` が呼び出しのたびに `min()`/`max()` を計算し直さないためのキャッシュ
# （モジュール docstring「辺の bbox は Polygon 構築時に1回だけ前計算する」参照）。
Edge = tuple[float, float, float, float, float, float, float, float]
RingEdges = list[Edge]


def _edges_of_ring(ring: Ring) -> RingEdges:
    edges: RingEdges = []
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        edges.append((
            xi, yi, xj, yj,
            xi if xi < xj else xj, xi if xi > xj else xj,
            yi if yi < yj else yj, yi if yi > yj else yj,
        ))
        j = i
    return edges


@dataclass(frozen=True)
class Polygon:
    """1 GeoJSON feature 分（単純な Polygon なら要素1つ、MultiPolygon なら
    複数要素の）`rings` を持つ。JS 版 `polys.push({id, rings, bbox})` の
    `rings`（`Polygon` なら `[geometry.coordinates]`、`MultiPolygon` なら
    `geometry.coordinates` の各要素を展開したもの）と同じ形。

    `ring_edges` は `rings` と同じ入れ子構造で、辺ごとの前計算済みデータ
    （`Edge`）を持つ——`__post_init__` が `rings` から自動的に作るので、
    呼び出し側（`load_polygons()`・テスト）は `rings`/`bbox` だけ渡せばよい。
    """

    id: str
    rings: list[PolygonCoordinates]
    bbox: tuple[float, float, float, float]
    ring_edges: list[list[RingEdges]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ring_edges",
            [[_edges_of_ring(ring) for ring in poly] for poly in self.rings],
        )


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


def _as_xy(coord) -> Point:
    """GeoJSON の1点（`[x, y]` または `[x, y, z]`）から `(x, y)` を取り出す
    （v1〔JS の分割代入 `[x, y]`〕と同じく3要素目〔標高等〕があっても無視する）。
    """
    return (coord[0], coord[1])


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
            raw_rings = [geom["coordinates"]]
        elif gtype == "MultiPolygon":
            raw_rings = list(geom["coordinates"])
        else:
            continue
        rings: list[PolygonCoordinates] = [
            [[_as_xy(pt) for pt in ring] for ring in poly] for poly in raw_rings
        ]
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


def _dist_sq_point_to_segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """点 `(x, y)` から線分 `(x1,y1)-(x2,y2)` までの最短距離の2乗（float）。"""
    dx, dy = x2 - x1, y2 - y1
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0.0:
        ex, ey = x - x1, y - y1
        return ex * ex + ey * ey
    t = ((x - x1) * dx + (y - y1) * dy) / seg_len2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cx, cy = x1 + t * dx, y1 + t * dy
    ex, ey = x - cx, y - cy
    return ex * ex + ey * ey


def _point_in_ring(x: float, y: float, edges: RingEdges, threshold: float) -> tuple[bool, bool]:
    """`web/scripts/build-geo.mjs:147-154` の even-odd 判定の移植
    （`inside` の計算はそのまま）＋ 辺までの距離による `near` 判定（モジュール
    docstring 参照。even-odd の交差判定とは独立に、全ての辺で行う）。

    `edges` は `Polygon.ring_edges` の1環ぶん（辺の bbox を前計算済み）。

    戻り値: `(内側か, 辺までの距離が閾値未満の辺が1つでもあったか)`。
    """
    inside = False
    near = False
    thr2 = threshold * threshold
    for xi, yi, xj, yj, lo_x, hi_x, lo_y, hi_y in edges:
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        if not near and not (
            x < lo_x - threshold or x > hi_x + threshold or y < lo_y - threshold or y > hi_y + threshold
        ):
            if _dist_sq_point_to_segment(x, y, xi, yi, xj, yj) < thr2:
                near = True
    return inside, near


def _point_in_ring_exact(x: Fraction, y: Fraction, ring: list[tuple[Fraction, Fraction]]) -> bool:
    """`_point_in_ring` の `inside` と同じ式を `Fraction` の厳密演算で行う
    （丸め誤差なし）。"""
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
    """`web/scripts/build-geo.mjs:155-165` の移植（穴あり、MultiPolygon 対応）。

    **全ての部分ポリゴン・全ての穴を見てから返す**（早期 return/break すると
    残りの環の `near` 情報を取りこぼす。経緯は
    `docs/plans/PHASE_B_OCCURRENCE.md` §16）。

    戻り値: `(poly に含まれるか, 際どい辺が1つでもあったか)`。
    """
    minx, miny, maxx, maxy = poly.bbox
    if x < minx - threshold or x > maxx + threshold or y < miny - threshold or y > maxy + threshold:
        return False, False
    near_any = False
    inside_any = False
    for edges_per_ring in poly.ring_edges:
        in_outer, near = _point_in_ring(x, y, edges_per_ring[0], threshold)
        near_any = near_any or near
        in_hole = False
        for h in range(1, len(edges_per_ring)):
            ih, nearh = _point_in_ring(x, y, edges_per_ring[h], threshold)
            near_any = near_any or nearh
            in_hole = in_hole or ih
        if in_outer and not in_hole:
            inside_any = True
    return inside_any, near_any


def point_in_polygon_exact(x: Fraction, y: Fraction, poly: Polygon) -> bool:
    """`point_in_polygon` の `inside` と同じ判定を `Fraction` の厳密演算で
    やり直す（`near` は扱わない——`locate_exact()` 専用のフル判定）。

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


def _point_on_segment_exact(
    px: Fraction, py: Fraction, x1: Fraction, y1: Fraction, x2: Fraction, y2: Fraction
) -> bool:
    """点 `(px, py)` が線分 `(x1,y1)-(x2,y2)`（端点＝頂点を含む）の上に厳密に
    乗っているかを判定する（`Fraction`。外積で共線性、内積で線分範囲内かを見る）。
    """
    cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
    if cross != 0:
        return False
    dot = (px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)
    if dot < 0:
        return False
    seg_len2 = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)
    if dot > seg_len2:
        return False
    return True


def _ring_boundary_contains_exact(px: Fraction, py: Fraction, ring: Ring) -> bool:
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = Fraction(ring[i][0]), Fraction(ring[i][1])
        xj, yj = Fraction(ring[j][0]), Fraction(ring[j][1])
        if _point_on_segment_exact(px, py, xi, yi, xj, yj):
            return True
        j = i
    return False


def polygon_boundary_contains_exact(x: float, y: float, poly: Polygon) -> bool:
    """点 `(x, y)` が `poly` の境界（外環・穴のどの辺上、頂点上を含む）に
    厳密に乗っているかを `Fraction` の厳密演算で判定する（ADR-0026 D1
    「2つ以上・境界上は止める」の「境界上」の実体）。

    全ての環（外環・穴）を見る（`point_in_polygon_exact` と違い、1つ見つかれば
    即座に返してよい——「境界上かどうか」は1件見つかった時点で確定する単純な
    真偽値で、`inside`/`near` のような情報を積み上げる必要が無いため）。
    """
    fx, fy = Fraction(x), Fraction(y)
    for rings in poly.rings:
        for ring in rings:
            if _ring_boundary_contains_exact(fx, fy, ring):
                return True
    return False


def candidates_for(x: float, y: float, grid: Grid, cell: float = CELL) -> list[int]:
    """`(x, y)` が属する 0.02度セルに登録済みのポリゴン index 列を返す
    （無ければ空リスト）。`locate()`/`locate_exact()`/`on_boundary()` が共有する。
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


def on_boundary(x: float, y: float, polys: list[Polygon], grid: Grid, cell: float = CELL) -> bool:
    """`(x, y)` が候補ポリゴン（`locate()` と同じグリッドで絞り込む）いずれかの
    境界（頂点・辺上を含む）に厳密に乗っているか。`locate()` が
    `near_boundary=True` を返した点だけに使う想定（軽い float 判定で絞り込んで
    から、ここで `Fraction` の厳密判定をする）。
    """
    for pi in candidates_for(x, y, grid, cell):
        if polygon_boundary_contains_exact(x, y, polys[pi]):
            return True
    return False
