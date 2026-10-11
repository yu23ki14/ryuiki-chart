"""地理院 DEM10B から計算する集水域（奄美大島。Issue #94）の純関数。
c69_gsi_dem_watersheds.py から使う。設計: docs/plans/AMAMI_WATERSHED_DEM.md §2〜§4。

- トップの import は numpy・shapely まで。pyflwdir・numba・scipy は `flow_basins()` と
  `drop_small_components()` の中でだけ import する（CI の reconcile ジョブは収集の依存を持たない。
  依存は scripts/requirements-dem.txt）。
- ネットワークにも原本にも出ない。タイルの読み出しは loader(z, x, y) -> bytes | None で受ける。
- 座標系は Web メルカトルの全球画素（ズーム dem_zoom）。ラスタの (row, col) は全球画素から
  (y0*256, x0*256) を引いたもの（x0, y0 はモザイクの左上タイルの番号）。
"""
import hashlib
import json
import math
import pathlib

import numpy as np
import shapely
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union, polygonize

import terrain_lib as T

TILE = T.TILE
ALGO_VERSION = "dem-watershed/1"
TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem_png/{z}/{x}/{y}.png"
NODATA = -9999.0

KIND_BASIN = "basin"
KIND_COAST_GROUP = "coast_group"
KIND_ISLAND = "island"
CATEGORY_JA = {KIND_BASIN: "河口の流域", KIND_COAST_GROUP: "沿岸の小流域群", KIND_ISLAND: "小島"}

ROW_KEYS = ("source_id", "watershed_id", "water_system_code_old", "water_system_name_ja_estimated",
            "water_system_category_ja", "main_river_names_ja", "area_km2", "centroid_lat", "centroid_lon",
            "data_year", "source_ref", "unit_kind", "own_drainage_km2", "merged_share", "outlet_lat",
            "outlet_lon", "w05_mouth_distance_m", "dem_zoom", "params_digest")


# ---------- 陸とタイル ----------
def land_polygons(coast_geojson, pref_code, min_area_deg2=1e-6):
    """C23 の海岸線（prefecture_code == pref_code の線）→ 陸のポリゴンのリスト（面積の大きい順）。"""
    fc = json.loads(pathlib.Path(coast_geojson).read_text(encoding="utf-8"))
    lines = [shape(f["geometry"]) for f in fc["features"] if f["properties"]["prefecture_code"] == pref_code]
    polys = [p for p in polygonize(unary_union(lines)) if p.area > min_area_deg2]
    return sorted(polys, key=lambda p: (-p.area, p.bounds))


def required_tiles(polys, z, margin_deg=0.002):
    """陸のポリゴンの bbox（margin_deg 広げる）と交わるタイル {(z, x, y)} をソートして返す。
    bbox 全体は取らない（島の周りの海のタイルを避ける）。"""
    n = 2 ** z
    tiles = set()
    for p in polys:
        x0, y0, x1, y1 = p.bounds
        px0, py0 = T.lonlat_to_pixel(x0 - margin_deg, y1 + margin_deg, z)
        px1, py1 = T.lonlat_to_pixel(x1 + margin_deg, y0 - margin_deg, z)
        for tx in range(max(int(px0 // TILE), 0), min(int(px1 // TILE), n - 1) + 1):
            for ty in range(max(int(py0 // TILE), 0), min(int(py1 // TILE), n - 1) + 1):
                west, north = T.pixel_to_lonlat(tx * TILE, ty * TILE, z)
                east, south = T.pixel_to_lonlat((tx + 1) * TILE, (ty + 1) * TILE, z)
                if p.intersects(box(west, south, east, north).buffer(margin_deg)):
                    tiles.add((z, tx, ty))
    return sorted(tiles)


def build_mosaic(tiles, loader):
    """tiles = [(z, x, y)]（同じ z）→ (dem, (x0, y0))。dem は float32 の (H, W)、無効・タイルの無い所は NaN。
    loader(z, x, y) は PNG のバイト列（404 は空）を返し、無ければ None（TileNotCached）。"""
    store = T.TileStore(loader)
    xs = [x for _, x, _ in tiles]
    ys = [y for _, _, y in tiles]
    x0, y0 = min(xs), min(ys)
    dem = np.full(((max(ys) - y0 + 1) * TILE, (max(xs) - x0 + 1) * TILE), np.nan, np.float32)
    for z, x, y in tiles:
        dem[(y - y0) * TILE:(y - y0 + 1) * TILE, (x - x0) * TILE:(x - x0 + 1) * TILE] = store.tile(z, x, y)
    return dem, (x0, y0)


def mosaic_sha256(dem):
    h = hashlib.sha256()
    h.update(json.dumps(dem.shape).encode())
    h.update(np.ascontiguousarray(dem).tobytes())
    return h.hexdigest()


def row_area_km2(y0, height, z):
    """モザイクの各行の 1 画素の面積 [km²]（行の中心の緯度）。形 (height,)。"""
    ys = (np.arange(height) + 0.5) + y0 * TILE
    n = TILE * 2 ** z
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * ys / n))))
    mpp = 40075016.686 * np.cos(np.radians(lat)) / n
    return (mpp ** 2) / 1e6


def drop_small_components(valid, row_area, min_km2):
    """有効画素（8近傍）の連結成分のうち面積 < min_km2（岩礁）を落とす。(新しい valid, 落とした面積 km², 落とした成分数)。"""
    from scipy import ndimage
    lab, n = ndimage.label(valid, structure=np.ones((3, 3)))
    area = np.bincount(lab.ravel(), weights=np.broadcast_to(row_area[:, None], valid.shape).ravel(),
                       minlength=n + 1)
    small = area < min_km2
    small[0] = False
    return valid & ~small[lab], float(area[small].sum()), int(small.sum())


# ---------- 流向（pyflwdir） ----------
def flow_version():
    import pyflwdir
    return pyflwdir.__version__


def flow_basins(dem, valid, row_area, want_upa=False):
    """窪地埋め → D8 → 海に接する画素ごとの流域。(lab, pits, upa|None, 版)。
    lab は int32 の (H, W)（0=無効、1..P=pits の順）。pits はラスタの平坦な添字の配列。"""
    import pyflwdir
    d = np.where(valid, dem, NODATA).astype(np.float32)
    flw = pyflwdir.from_dem(d, nodata=NODATA, outlets="edge")
    pits = np.asarray(flw.idxs_pit)
    lab = flw.basins(idxs=pits, ids=np.arange(1, len(pits) + 1, dtype=np.uint32)).astype(np.int32)
    upa = None
    if want_upa:
        areaw = np.where(valid, row_area[:, None], 0.0)
        upa = flw.accuflux(areaw)
    return lab, pits, upa, pyflwdir.__version__


# ---------- 併合 ----------
def basin_areas(lab, row_area, n_basins):
    """流域ごとの面積 [km²]（形 n_basins+1。0 番は未使用）。"""
    w = np.broadcast_to(row_area[:, None], lab.shape).ravel()
    return np.bincount(lab.ravel(), weights=w, minlength=n_basins + 1)


def basin_adjacency(lab, n_basins):
    """4近傍で接する流域の共有辺の画素数。{a: {b: 画素辺数}}（対称）。"""
    stride = n_basins + 1

    def pairs(a, b):
        m = (a != b) & (a > 0) & (b > 0)
        a, b = a[m].astype(np.int64), b[m].astype(np.int64)
        return np.minimum(a, b) * stride + np.maximum(a, b)

    keys = np.concatenate([pairs(lab[:, :-1], lab[:, 1:]), pairs(lab[:-1, :], lab[1:, :])])
    uniq, cnt = np.unique(keys, return_counts=True)
    adj = {}
    for k, c in zip(uniq.tolist(), cnt.tolist()):
        a, b = divmod(k, stride)
        adj.setdefault(a, {})[b] = c
        adj.setdefault(b, {})[a] = c
    return adj


def merge_basins(adj, area, a_min):
    """面積 < a_min の流域を、小さい順に、共有辺が最長の隣（a_min 以上の隣があればその中から。同長なら番号の小さい方）へ併合する。
    併合先の面積を更新して繰り返す。隣のない流域はそのまま。area は流域番号で引く配列（0 番は未使用）。
    戻り値: root_of（形 len(area)。併合後の代表の流域番号。0 番は 0）。"""
    import heapq
    adj = {k: dict(v) for k, v in adj.items()}
    cur = {i: float(area[i]) for i in range(1, len(area))}
    parent = {}
    heap = [(a, i) for i, a in cur.items() if a < a_min]
    heapq.heapify(heap)
    while heap:
        a, i = heapq.heappop(heap)
        if i in parent or abs(cur[i] - a) > 1e-12 or cur[i] >= a_min:
            continue
        nb = adj.get(i)
        if not nb:
            continue
        big = [k for k in nb if cur[k] >= a_min]
        j = min(big or list(nb), key=lambda k: (-nb[k], k))
        parent[i] = j
        cur[j] += cur[i]
        for k, w in nb.items():
            if k == j:
                continue
            adj[k].pop(i, None)
            adj[k][j] = adj[k].get(j, 0) + w
            adj[j][k] = adj[j].get(k, 0) + w
        adj[j].pop(i, None)
        del adj[i]
        if cur[j] < a_min:
            heapq.heappush(heap, (cur[j], j))
    root_of = np.zeros(len(area), np.int64)
    for i in range(1, len(area)):
        r = i
        while r in parent:
            r = parent[r]
        root_of[i] = r
    return root_of


def pit_lonlat(rows, cols, x0, y0, z):
    """ラスタの (row, col) 配列 → 画素中心の (lon, lat) 配列。"""
    return px_to_lonlat(np.asarray(cols, float) + 0.5 + x0 * TILE, np.asarray(rows, float) + 0.5 + y0 * TILE, z)


def px_to_lonlat(px, py, z):
    n = TILE * 2 ** z
    lon = np.asarray(px, float) / n * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * np.asarray(py, float) / n))))
    return lon, lat


def assemble_units(lab, root_of, basin_area, pits_rc, row_area, a_min, min_island_km2, x0, y0, z, id_prefix):
    """併合結果から面（unit）を組み立てる。
    戻り値: (lab_final, units, dropped)
      lab_final: int32。面の番号（1..N）。落とした面は 0。
      units: [{id, watershed_id（`<id_prefix>-NNN`）, root, area_km2, own_drainage_km2, merged_share, unit_kind, outlet_row, outlet_col,
               outlet_lon, outlet_lat, n_basins}]（id の順）。
      dropped: {"n": 落とした面の数, "area_km2": その面積}
    面の番号: 出口の緯度の大きい順、同じなら経度の小さい順（小数6桁に丸めて比べる。さらに同じなら代表の流域番号）。
    出口 = 面を作る流域のうち自前の集水面積が最大のもの（同じなら番号の小さい方）の pit。
    unit_kind: 自前の集水面積 >= a_min の出口を持てば basin、持たずに面積 >= a_min なら coast_group、
    面積 < a_min（併合しても届かない＝隣が無い）なら island。"""
    lab_root = root_of[lab]
    unit_area = basin_area_by(lab_root, row_area, len(root_of))
    roots = [int(r) for r in np.unique(root_of[1:]) if unit_area[r] >= min_island_km2]
    dropped_roots = [int(r) for r in np.unique(root_of[1:]) if unit_area[r] < min_island_km2]
    dropped = {"n": len(dropped_roots), "area_km2": float(sum(unit_area[r] for r in dropped_roots))}

    best = {}
    n_members = {}
    for i in range(1, len(root_of)):
        r = int(root_of[i])
        n_members[r] = n_members.get(r, 0) + 1
        if r not in best or basin_area[i] > basin_area[best[r]]:
            best[r] = i
    units = []
    for r in roots:
        i = best[r]
        row, col = pits_rc[i - 1]
        own = float(basin_area[i])
        area = float(unit_area[r])
        if own >= a_min:
            kind = KIND_BASIN
        elif area >= a_min:
            kind = KIND_COAST_GROUP
        else:
            kind = KIND_ISLAND
        units.append({"root": r, "area_km2": area, "own_drainage_km2": own,
                      "merged_share": max(0.0, 1.0 - own / area), "unit_kind": kind,
                      "outlet_row": int(row), "outlet_col": int(col), "n_basins": n_members[r]})
    rows = np.array([u["outlet_row"] for u in units])
    cols = np.array([u["outlet_col"] for u in units])
    lon, lat = pit_lonlat(rows, cols, x0, y0, z)
    for u, lo, la in zip(units, lon, lat):
        u["outlet_lon"], u["outlet_lat"] = round(float(lo), 6), round(float(la), 6)
    units.sort(key=lambda u: (-u["outlet_lat"], u["outlet_lon"], u["root"]))
    remap = np.zeros(len(root_of), np.int32)
    for k, u in enumerate(units, 1):
        u["id"] = k
        u["watershed_id"] = f"{id_prefix}-{k:03d}"
        remap[u["root"]] = k
    lab_final = np.where(lab > 0, remap[root_of[lab]], 0).astype(np.int32)
    return lab_final, units, dropped


def basin_area_by(label_img, row_area, size):
    w = np.broadcast_to(row_area[:, None], label_img.shape).ravel()
    return np.bincount(label_img.ravel(), weights=w, minlength=size)


# ---------- ポリゴン化 ----------
def label_runs(lab):
    """行ごとの同じ番号の連続（run）→ {label: (n, 4) の [x0, y0, x1, y1]（画素の辺。右・下は開）}。0 は含めない。"""
    h = lab.shape[0]
    padded = np.concatenate([np.zeros((h, 1), lab.dtype), lab, np.zeros((h, 1), lab.dtype)], axis=1)
    r, c = np.nonzero(padded[:, 1:] != padded[:, :-1])  # c: 画素 c の左の辺（行→列の順）
    same = np.nonzero(r[1:] == r[:-1])[0]
    rows, c0, c1 = r[same], c[same], c[same + 1]
    labels = padded[rows, c0 + 1]
    keep = labels > 0
    rows, c0, c1, labels = rows[keep], c0[keep], c1[keep], labels[keep]
    order = np.argsort(labels, kind="stable")
    rows, c0, c1, labels = rows[order], c0[order], c1[order], labels[order]
    out = {}
    for lbl in np.unique(labels):
        m = labels == lbl
        out[int(lbl)] = np.stack([c0[m], rows[m], c1[m], rows[m] + 1], axis=1).astype(float)
    return out


def labels_to_polygons(lab, x0, y0, z, simplify_px):
    """面の番号の画像 → {番号: 経緯度のジオメトリ}。
    runs を長方形にして union → shapely.coverage_simplify（許容 simplify_px 画素。隣り合う面の共有境界を一緒に
    簡略化するので重なり・隙間が出ない）→ 経緯度に戻して小数6桁に丸める。"""
    runs = label_runs(lab)
    ids = sorted(runs)
    geoms = np.array([shapely.union_all(shapely.box(a[:, 0], a[:, 1], a[:, 2], a[:, 3])) for a in
                      (runs[i] for i in ids)], dtype=object)
    if simplify_px:
        geoms = shapely.coverage_simplify(geoms, float(simplify_px))

    def to_lonlat(xy):
        lon, lat = px_to_lonlat(xy[:, 0] + x0 * TILE, xy[:, 1] + y0 * TILE, z)
        return np.stack([lon, lat], axis=1)

    out = {}
    for i, g in zip(ids, geoms):
        out[i] = shapely.set_precision(shapely.transform(g, to_lonlat), 1e-6)
    return out


# ---------- W05 河口 ----------
def _ref(s):
    return s.lstrip("#") if s else None


def w05_mouths(rivers, nodes):
    """W05 の流路の終点で、どの流路の始点でもないノード → 河口のリスト（node_id の順）。
    rivers: nlni_w05_rivers_*.jsonl の行、nodes: nlni_w05_river_nodes_*.jsonl の行。
    戻り値: [{node_id, lon, lat, elevation_m, river_names (tuple)、water_system_names (tuple)}]。"""
    by_id = {n["node_id"]: n for n in nodes}
    starts = {_ref(r.get("stream_start_node_ref")) for r in rivers}
    acc = {}
    for r in rivers:
        e = _ref(r.get("stream_end_node_ref"))
        if e is None or e in starts or e not in by_id:
            continue
        a = acc.setdefault(e, {"rivers": set(), "systems": set()})
        nm = r.get("river_name_ja") or r.get("river_code_name_ja")
        if nm:
            a["rivers"].add(nm)
        if r.get("water_system_name_ja"):
            a["systems"].add(r["water_system_name_ja"])
    out = []
    for nid in sorted(acc):
        n = by_id[nid]
        out.append({"node_id": nid, "lon": n["lon"], "lat": n["lat"], "elevation_m": n.get("elevation_m"),
                    "river_names": tuple(sorted(acc[nid]["rivers"])),
                    "water_system_names": tuple(sorted(acc[nid]["systems"]))})
    return out


def dist_m(lon1, lat1, lon2, lat2):
    """近距離の2点間の距離 [m]（等距円筒）。"""
    k = math.cos(math.radians((lat1 + lat2) / 2.0))
    return math.hypot((lon1 - lon2) * 111320.0 * k, (lat1 - lat2) * 110574.0)


def nearest_mouths(lon, lat, mouths):
    """(距離 m, 河口) の昇順リスト。"""
    return sorted(((dist_m(lon, lat, m["lon"], m["lat"]), m["node_id"], m) for m in mouths),
                  key=lambda t: (t[0], t[1]))


def attach_w05(units, mouths, match_m):
    """basin の面に最寄りの W05 河口までの距離と水系名・河川名を付ける（match_m 以内の河口だけ名前に使う）。
    basin 以外は距離も名前も付けない（河口が無い面）。units を書き換える。"""
    for u in units:
        u["w05_mouth_distance_m"] = None
        u["water_system_name_ja_estimated"] = None
        u["main_river_names_ja"] = ""
        if u["unit_kind"] != KIND_BASIN or not mouths:
            continue
        near = nearest_mouths(u["outlet_lon"], u["outlet_lat"], mouths)
        u["w05_mouth_distance_m"] = round(near[0][0], 1)
        within = [m for d, _, m in near if d <= match_m]
        if within:
            systems = within[0]["water_system_names"]
            u["water_system_name_ja_estimated"] = systems[0] if systems else None
            names = []
            for m in within:
                for nm in m["river_names"]:
                    if nm not in names:
                        names.append(nm)
            u["main_river_names_ja"] = "|".join(names)


# ---------- 出力 ----------
def params_digest(cfg, flow_version, mosaic_sha):
    """定義パラメータとモザイクの中身から作る指紋（16桁）。jsonl の全行に入れる。"""
    payload = {"algo": ALGO_VERSION, "a_min_km2": cfg["a_min_km2"], "min_island_km2": cfg["min_island_km2"],
               "simplify_px": cfg["simplify_px"], "dem_zoom": cfg["dem_zoom"], "w05_match_m": cfg["w05_match_m"],
               "pyflwdir": flow_version, "mosaic_sha256": mosaic_sha}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def unit_rows(units, polys, cfg, digest):
    """面 → (jsonl の行, GeoJSON の Feature) のリスト。"""
    out = []
    for u in units:
        g = polys[u["id"]]
        c = g.centroid
        row = {
            "source_id": cfg["stem"],
            "watershed_id": u["watershed_id"],
            "water_system_code_old": None,
            "water_system_name_ja_estimated": u["water_system_name_ja_estimated"],
            "water_system_category_ja": CATEGORY_JA[u["unit_kind"]],
            "main_river_names_ja": u["main_river_names_ja"],
            "area_km2": round(u["area_km2"], 6),
            "centroid_lat": round(c.y, 6),
            "centroid_lon": round(c.x, 6),
            "data_year": None,
            "source_ref": TILE_URL + f"#params_digest={digest}",
            "unit_kind": u["unit_kind"],
            "own_drainage_km2": round(u["own_drainage_km2"], 6),
            "merged_share": round(u["merged_share"], 4),
            "outlet_lat": u["outlet_lat"],
            "outlet_lon": u["outlet_lon"],
            "w05_mouth_distance_m": u["w05_mouth_distance_m"],
            "dem_zoom": cfg["dem_zoom"],
            "params_digest": digest,
        }
        assert tuple(row) == ROW_KEYS
        feat = {"type": "Feature", "properties": row, "geometry": mapping(g)}
        out.append((row, feat))
    return out


def dump_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def dump_geojson(feats):
    return json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False,
                      separators=(",", ":")) + "\n"


# ---------- 宣言と検査 ----------
CHECK_NAMES = ("w05_outlet_to_mouth", "w05_mouth_to_outlet", "land_coverage", "overlap_pairs",
               "w12_containment", "outlet_on_coast", "dropped_area_km2", "determinism",
               "largest_unit_outlet", "unit_count")


def load_declarations(path):
    """scripts/migrate/dem_watershed_declarations.yaml。形（name -> {expected, tolerance?, exceptions: [{id, reason}], note}）を検査する。"""
    import yaml
    raw = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    problems = []
    if set(raw) != set(CHECK_NAMES):
        problems.append(f"宣言の名前が検査と合わない: 余り={sorted(set(raw) - set(CHECK_NAMES))} "
                        f"不足={sorted(set(CHECK_NAMES) - set(raw))}")
    for name in sorted(set(raw) & set(CHECK_NAMES)):
        spec = raw[name]
        if not isinstance(spec, dict) or "expected" not in spec:
            problems.append(f"{name}: expected が無い")
            continue
        for ex in spec.get("exceptions") or []:
            if not isinstance(ex, dict) or not ex.get("id") or not str(ex.get("reason") or "").strip():
                problems.append(f"{name}: exceptions の各行に id と reason が要る: {ex!r}")
    if problems:
        raise ValueError(f"{path}: " + " / ".join(problems))
    return raw


def _settle(name, decl, failing_ids):
    """外れた ID と宣言済みの例外を突き合わせる。(宣言の無い外れ, 使われた例外, 使われなかった例外)。"""
    declared = {str(e["id"]) for e in (decl[name].get("exceptions") or [])}
    failing = {str(i) for i in failing_ids}
    return sorted(failing - declared), sorted(failing & declared), sorted(declared - failing)


def _result(name, decl, measured, ok, failing_ids=(), extra=None):
    unexplained, used, stale = _settle(name, decl, failing_ids)
    res = {"expected": decl[name]["expected"], "measured": measured, "undeclared_failures": unexplained,
           "declared_exceptions_used": used, "declared_exceptions_unused": stale,
           "passed": bool(ok) and not unexplained and not stale}
    if extra:
        res.update(extra)
    return res


def check_outlet_to_mouth(units, mouths, decl):
    """basin の面の出口から最寄りの W05 河口まで <= expected [m]。"""
    lim = float(decl["w05_outlet_to_mouth"]["expected"])
    basin = [u for u in units if u["unit_kind"] == KIND_BASIN]
    ds = []
    fails = []
    for u in basin:
        d = nearest_mouths(u["outlet_lon"], u["outlet_lat"], mouths)[0][0] if mouths else math.inf
        ds.append(d)
        if d > lim:
            fails.append(u["watershed_id"])
    m = {"n": len(basin), "median_m": round(float(np.median(ds)), 1) if ds else None,
         "max_m": round(max(ds), 1) if ds else None, "n_over": len(fails)}
    return _result("w05_outlet_to_mouth", decl, m, True, fails)


def mouths_with_catchment(mouths, upa, x0, y0, z, a_min, radius_m=300.0, max_elev_m=10.0):
    """標高 max_elev_m 以下の W05 河口のうち、周囲 radius_m に集水面積 >= a_min の画素があるもの。"""
    h, w = upa.shape
    out = []
    for m in mouths:
        if (m["elevation_m"] or 0) > max_elev_m:
            continue
        px, py = T.lonlat_to_pixel(m["lon"], m["lat"], z)
        r, c = int(py - y0 * TILE), int(px - x0 * TILE)
        k = max(1, int(radius_m / T.m_per_px(m["lat"], z)))
        sub = upa[max(0, r - k):r + k + 1, max(0, c - k):c + k + 1]
        if sub.size and np.nanmax(sub) >= a_min:
            out.append(m)
    return out


def check_mouth_to_outlet(cands, units, decl):
    """河口側: cands の各河口から最寄りの出口（basin の面）まで <= expected [m]。範囲内の割合 >= 1 - tolerance。"""
    spec = decl["w05_mouth_to_outlet"]
    lim = float(spec["expected"])
    tol = float(spec.get("tolerance", 0.0))
    outs = [(u["outlet_lon"], u["outlet_lat"]) for u in units if u["unit_kind"] == KIND_BASIN]
    ds, fails = [], []
    for m in cands:
        d = min((dist_m(m["lon"], m["lat"], lo, la) for lo, la in outs), default=math.inf)
        ds.append(d)
        if d > lim:
            fails.append(m["node_id"])
    share = 1.0 - len(fails) / len(cands) if cands else 1.0
    meas = {"n": len(cands), "within_share": round(share, 4), "median_m": round(float(np.median(ds)), 1) if ds else None,
            "n_over": len(fails)}
    return _result("w05_mouth_to_outlet", decl, meas, share >= 1.0 - tol, fails)


def check_land_coverage(land_polys, unit_geoms, decl):
    """陸（C23）のうち面に入る面積の割合 >= expected。面積は等積の近似（測地線）。"""
    import pyproj
    geod = pyproj.Geod(ellps="WGS84")

    def area(g):
        return abs(geod.geometry_area_perimeter(g)[0]) / 1e6

    land = unary_union(land_polys)
    cover = unary_union([shapely.make_valid(g) for g in unit_geoms])
    a_land, a_in = area(land), area(land.intersection(cover))
    meas = {"land_km2": round(a_land, 3), "covered_km2": round(a_in, 3), "share": round(a_in / a_land, 5),
            "uncovered_km2": round(a_land - a_in, 3)}
    return _result("land_coverage", decl, meas, a_in / a_land >= float(decl["land_coverage"]["expected"]))


def check_overlap_pairs(unit_geoms, ids, decl, eps_deg2=1e-10):
    """面同士の重なり（面積 > eps_deg2）の組の数 == expected。"""
    from shapely.strtree import STRtree
    gs = [shapely.make_valid(g) for g in unit_geoms]
    tree = STRtree(gs)
    pairs = []
    for i, g in enumerate(gs):
        for j in tree.query(g):
            if j > i and g.intersection(gs[j]).area > eps_deg2:
                pairs.append(f"{ids[i]}~{ids[j]}")
    return _result("overlap_pairs", decl, {"n_pairs": len(pairs), "pairs": pairs[:10]},
                   len(pairs) == int(decl["overlap_pairs"]["expected"]))


def check_w12_containment(w12_features, unit_geoms, decl):
    """W12 の各面について、いちばん重なる DEM の面が W12 の面積に占める割合 >= expected。
    w12_features: [(watershed_id, 経緯度ジオメトリ)]。"""
    from shapely.strtree import STRtree
    lim = float(decl["w12_containment"]["expected"])
    gs = [shapely.make_valid(g) for g in unit_geoms]
    tree = STRtree(gs)
    shares, fails = {}, []
    for wid, w in w12_features:
        w = shapely.make_valid(w)
        best = max((w.intersection(gs[i]).area for i in tree.query(w)), default=0.0)
        shares[wid] = best / w.area if w.area else 0.0
        if shares[wid] < lim:
            fails.append(wid)
    vals = sorted(shares.values())
    meas = {"n": len(vals), "min": round(vals[0], 4) if vals else None, "n_below": len(fails)}
    return _result("w12_containment", decl, meas, True, fails)


def outlet_on_coast(valid, units):
    """出口の画素が有効で、8近傍のどれかが無効（海）・モザイクの外である条件を満たさない面の ID を返す。
    D8 の流向は斜めにも流れるので、海との接し方も斜めを含める（4近傍だと斜めにだけ海に接す出口を誤って落とす）。"""
    h, w = valid.shape
    bad = []
    for u in units:
        r, c = u["outlet_row"], u["outlet_col"]
        ok = bool(valid[r, c])
        sea = False
        for dr, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            rr, cc = r + dr, c + dc
            if not (0 <= rr < h and 0 <= cc < w) or not valid[rr, cc]:
                sea = True
        if not (ok and sea):
            bad.append(u["watershed_id"])
    return bad


def check_outlet_on_coast(valid, units, decl):
    bad = outlet_on_coast(valid, units)
    return _result("outlet_on_coast", decl, {"n": len(units), "n_bad": len(bad)}, True, bad)


def check_dropped_area(dropped_component_km2, dropped_units, decl):
    """捨てた面積（岩礁の成分＋小さすぎて残らなかった面）の合計 <= expected [km²]。"""
    total = dropped_component_km2 + dropped_units["area_km2"]
    meas = {"components_km2": round(dropped_component_km2, 4), "units_n": dropped_units["n"],
            "units_km2": round(dropped_units["area_km2"], 4), "total_km2": round(total, 4)}
    return _result("dropped_area_km2", decl, meas, total <= float(decl["dropped_area_km2"]["expected"]))


def check_determinism(computed: dict, on_disk: dict, decl):
    """計算し直した出力（名前→文字列）とディスクのファイルがバイト一致。"""
    diff = sorted(k for k in computed if computed[k].encode("utf-8") != on_disk.get(k))
    return _result("determinism", decl, {"files": sorted(computed), "differs": diff}, not diff, diff)


def check_largest_unit_outlet(units, decl):
    """面積最大の面の出口が宣言した座標（expected: {lat, lon}、tolerance: 度）にある。"""
    spec = decl["largest_unit_outlet"]
    u = max(units, key=lambda u: (u["area_km2"], -u["id"]))
    tol = float(spec.get("tolerance", 0.0))
    ok = abs(u["outlet_lat"] - spec["expected"]["lat"]) <= tol and abs(u["outlet_lon"] - spec["expected"]["lon"]) <= tol
    return _result("largest_unit_outlet", decl, {"watershed_id": u["watershed_id"], "area_km2": round(u["area_km2"], 2),
                                                 "outlet_lat": u["outlet_lat"], "outlet_lon": u["outlet_lon"]}, ok)


def check_unit_count(units, decl):
    spec = decl["unit_count"]
    ok = abs(len(units) - int(spec["expected"])) <= int(spec.get("tolerance", 0))
    kinds = {k: sum(1 for u in units if u["unit_kind"] == k) for k in CATEGORY_JA}
    return _result("unit_count", decl, {"n": len(units), "by_kind": kinds}, ok)
