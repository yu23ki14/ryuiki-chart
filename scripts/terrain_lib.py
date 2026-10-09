"""地形指標の純関数（標高タイルの復号・円窓・起伏量・最低点・海岸距離・最高峰の検査）。

c68_gsi_dem_terrain.py から使う。ネットワークにも原本にも出ない（テストは合成 PNG で動かす）。
設計: docs/plans/AMAMI_STEP0.md §1.2・§3・§6-A。

- 標高タイルは地理院 dem_png（DEM10B）。1画素の標高は x = 65536R + 256G + B を
  x < 2^23 なら 0.01x、x > 2^23 なら 0.01(x - 2^24) [m]。x == 2^23（R,G,B = 128,0,0）は無効（海・欠測）。
- 点の座標は Web メルカトルの全球画素座標に直し、座標を含む画素を「その点の標高」とする。
- 円窓は「画素の中心が点から半径 r [m] 以内」の画素（距離は画素中心と点の距離 × その緯度の1画素の長さ）。
"""
import io
import math

import numpy as np

TILE = 256
INVALID_RAW = 2 ** 23

class TileNotCached(FileNotFoundError):
    """窓に必要なタイルがキャッシュに無い（取得前に呼んだ）。"""


# ---------- 座標 ----------
def lonlat_to_pixel(lon, lat, z):
    """経緯度 → ズーム z の全球画素座標（小数。整数部が画素の番号）。"""
    n = 2 ** z * TILE
    px = (lon + 180.0) / 360.0 * n
    py = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return px, py


def pixel_to_lonlat(px, py, z):
    n = 2 ** z * TILE
    lon = px / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * py / n))))
    return lon, lat


def m_per_px(lat, z):
    """その緯度・ズームの 1 画素の長さ [m]。"""
    return 40075016.686 * math.cos(math.radians(lat)) / (TILE * 2 ** z)


def _bounds(lon, lat, r_m, z):
    px, py = lonlat_to_pixel(lon, lat, z)
    rp = r_m / m_per_px(lat, z)
    return px, py, int(math.floor(px - rp)), int(math.ceil(px + rp)), int(math.floor(py - rp)), int(math.ceil(py + rp))


def tiles_for_circle(lon, lat, r_m, z):
    """半径 r_m の円窓に要るタイルの集合 {(z, x, y)}。circle_values と同じ範囲の計算を使う。"""
    _, _, x0, x1, y0, y1 = _bounds(lon, lat, r_m, z)
    return {(z, tx, ty) for tx in range(x0 // TILE, x1 // TILE + 1) for ty in range(y0 // TILE, y1 // TILE + 1)}


# ---------- 復号 ----------
def decode_dem_png(data):
    """dem_png の PNG（バイト列）→ 256x256 の標高 [m]（float32。無効は NaN）。空のバイト列（404）は全て NaN。"""
    if not data:
        return np.full((TILE, TILE), np.nan, np.float32)
    from PIL import Image
    im = np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).astype(np.int64)
    x = im[..., 0] * 65536 + im[..., 1] * 256 + im[..., 2]
    h = np.where(x < INVALID_RAW, x * 0.01, (x - 2 ** 24) * 0.01).astype(np.float32)
    h[x == INVALID_RAW] = np.nan
    return h


class TileStore:
    """タイルの読み出し。loader(z, x, y) はバイト列（空は 404）を返し、キャッシュに無ければ None を返す。"""

    def __init__(self, loader):
        self._loader = loader
        self._cache = {}

    def tile(self, z, x, y):
        k = (z, x, y)
        if k not in self._cache:
            data = self._loader(z, x, y)
            if data is None:
                raise TileNotCached(f"dem_png/{z}/{x}/{y}.png")
            self._cache[k] = decode_dem_png(data)
        return self._cache[k]


# ---------- 窓 ----------
def circle_values(store, lon, lat, r_m, z):
    """点を中心とする半径 r_m の円窓の標高の2次元配列（円の外・無効は NaN）。"""
    px, py, x0, x1, y0, y1 = _bounds(lon, lat, r_m, z)
    out = np.full((y1 - y0 + 1, x1 - x0 + 1), np.nan, np.float32)
    for tx in range(x0 // TILE, x1 // TILE + 1):
        for ty in range(y0 // TILE, y1 // TILE + 1):
            t = store.tile(z, tx, ty)
            xs, xe = max(x0, tx * TILE), min(x1 + 1, tx * TILE + TILE)
            ys, ye = max(y0, ty * TILE), min(y1 + 1, ty * TILE + TILE)
            out[ys - y0:ye - y0, xs - x0:xe - x0] = t[ys - ty * TILE:ye - ty * TILE, xs - tx * TILE:xe - tx * TILE]
    yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    dist = np.hypot(xx + 0.5 - px, yy + 0.5 - py) * m_per_px(lat, z)
    return np.where(dist <= r_m, out, np.float32(np.nan))


def circle_min_max(store, lon, lat, r_m, z):
    """円窓の有効画素の (最低, 最高)。有効画素が無ければ (None, None)。"""
    v = circle_values(store, lon, lat, r_m, z)
    if np.isnan(v).all():
        return None, None
    return float(np.nanmin(v)), float(np.nanmax(v))


def elevation_at(store, lon, lat, z):
    """座標を含む画素の標高 [m]。無効（海・欠測）なら None。"""
    px, py = lonlat_to_pixel(lon, lat, z)
    ix, iy = int(math.floor(px)), int(math.floor(py))
    v = store.tile(z, ix // TILE, iy // TILE)[iy % TILE, ix % TILE]
    return None if np.isnan(v) else float(v)


def point_metrics(store, lon, lat, terrain):
    """1 地点の (elevation_m, relief_wide_m, relief_near_m, floor_min_m)。標高が取れなければ全て None。"""
    z = terrain["dem_tile_zoom"]
    e = elevation_at(store, lon, lat, z)
    if e is None:
        return None, None, None, None
    lo, hi = circle_min_max(store, lon, lat, terrain["relief_wide_radius_m"], z)
    relief_wide = None if lo is None else hi - lo
    lo, hi = circle_min_max(store, lon, lat, terrain["relief_near_radius_m"], z)
    relief_near = None if lo is None else hi - lo
    floor_min, _ = circle_min_max(store, lon, lat, terrain["lowland_floor_radius_m"], terrain["floor_dem_tile_zoom"])
    return e, relief_wide, relief_near, floor_min


def required_tiles(lon, lat, terrain):
    """1 地点の指標に要るタイル（標高と起伏量は dem_tile_zoom、最低点は floor_dem_tile_zoom）。"""
    z = terrain["dem_tile_zoom"]
    r = max(terrain["relief_wide_radius_m"], terrain["relief_near_radius_m"])
    return (tiles_for_circle(lon, lat, r, z)
            | tiles_for_circle(lon, lat, terrain["lowland_floor_radius_m"], terrain["floor_dem_tile_zoom"]))


# ---------- 最高峰の検査 ----------
def check_summit(store, summit, z, radius_m=500.0, tol_m=20.0):
    """宣言した最高峰の座標の周辺 radius_m の DEM 最大が、宣言値 ±tol_m に収まるか。
    -> (ok, dem_max)。窓に有効画素が無ければ (False, None)。"""
    _, hi = circle_min_max(store, summit["lon"], summit["lat"], radius_m, z)
    if hi is None:
        return False, None
    return abs(hi - float(summit["elevation_m"])) <= tol_m, hi


def summit_tiles(summit, z, radius_m=500.0):
    return tiles_for_circle(summit["lon"], summit["lat"], radius_m, z)


# ---------- 海岸距離 ----------
class CoastDistance:
    """海岸線（GeoJSON の線）までの最短距離 [m]。緯度の cos で経度を縮めた局所平面で測る。"""

    def __init__(self, geometries, lat0=None):
        import shapely
        from shapely import STRtree
        geoms = list(geometries)
        if not geoms:
            raise ValueError("海岸線が空")
        if lat0 is None:
            b = shapely.total_bounds(geoms)
            lat0 = (b[1] + b[3]) / 2.0
        self.lat0 = lat0
        self._kx = math.cos(math.radians(lat0)) * 111320.0
        kx = self._kx
        self._geoms = [shapely.transform(g, lambda a: np.column_stack((a[:, 0] * kx, a[:, 1] * 110540.0))) for g in geoms]
        self._tree = STRtree(self._geoms)

    def query(self, lon, lat):
        from shapely.geometry import Point
        p = Point(lon * self._kx, lat * 110540.0)
        i = self._tree.nearest(p)
        return float(self._geoms[i].distance(p))
