"""zone（Ridge to Reef 1-5）v2 の判定規則（docs/plans/AMAMI_STEP0.md §1・§3、ADR-0031）。

標高・起伏量・周囲2kmの最低点・海岸距離は収集段階（scripts/c68_gsi_dem_terrain.py）が
`data/processed/terrain_points.csv` に計算して置く。ここは、その数字を `registry/place/zone.yaml` の
`rule:` の閾値と比べるだけの**純関数**（標高タイルも海岸線ポリゴンも W12 も読まない。ネットワークに
出ない）。`m09_site_zone.py`・`build_place.py`・テストが同じ `classify()` を使う。

- `load_zone_definition()`   zone.yaml の読み込みと形の検証
- `terrain_params_digest()`  `terrain:` ブロックの指紋（csv の `params_digest` 列と照合する。c68 も同じ関数を使うこと）
- `load_region_summits()`    region.yaml の `terrain.summit.elevation_m`
- `load_terrain_points()`     terrain_points.csv を座標の組で引ける辞書に読む（指紋・最高峰の照合込み）
- `classify()`               §1.1 の規則
- `classify_sites()`         台帳の地点の集合に classify を当てる（csv に無い座標は列挙して止める）
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from dataclasses import dataclass

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ZONE_YAML = ROOT / "registry" / "place" / "zone.yaml"
REGION_YAML = ROOT / "registry" / "region.yaml"
TERRAIN_POINTS_CSV = ROOT / "data" / "processed" / "terrain_points.csv"

DEFINITION_VERSION = 2

TERRAIN_KEYS = (
    "dem_tile_zoom", "floor_dem_tile_zoom", "relief_wide_radius_m",
    "relief_near_radius_m", "lowland_floor_radius_m",
)
RULE_KEYS = (
    "coast_dist_max_m", "coast_elev_max_m", "mountain_relief_min_m", "summit_ratio_min",
    "lowland_elev_max_m", "lowland_relief_max_m", "lowland_above_floor_max_m",
)
ZONE_ITEM_KEYS = ("zone", "name_ja", "condition_ja", "ui_condition_ja")
TERRAIN_CSV_COLUMNS = (
    "lat", "lon", "region_id", "summit_m", "elevation_m", "relief_wide_m", "relief_near_m",
    "floor_min_m", "coast_dist_m", "params_digest",
)


class ZoneRuleError(Exception):
    """zone 定義・入力の不整合。黙って進めず、呼び出し側で止める。"""


@dataclass(frozen=True)
class TerrainPoint:
    lat: str
    lon: str
    region_id: str
    summit_m: float
    elevation_m: float | None
    relief_wide_m: float | None
    relief_near_m: float | None
    floor_min_m: float | None
    coast_dist_m: float | None


def coord_key(lat, lon) -> tuple[str, str]:
    """座標の組のキー（小数6桁に丸めた文字列）。"""
    return (f"{round(float(lat), 6):.6f}", f"{round(float(lon), 6):.6f}")


def terrain_params_digest(terrain: dict) -> str:
    """`terrain:` ブロックの sha256 先頭12桁（キー順・空白に依らない正規化 JSON から）。"""
    canon = json.dumps(terrain, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]


def load_zone_definition(path=ZONE_YAML) -> dict:
    """zone.yaml を読んで形を検証し、dict（definition_version/note_ja/terrain/rule/zones）を返す。"""
    with pathlib.Path(path).open(encoding="utf-8") as f:
        d = yaml.safe_load(f)
    if not isinstance(d, dict):
        raise ZoneRuleError(f"{path}: マッピングになっていない（v2 の構造: definition_version/note_ja/terrain/rule/zones）")
    if d.get("definition_version") != DEFINITION_VERSION:
        raise ZoneRuleError(f"{path}: definition_version が {DEFINITION_VERSION} でない: {d.get('definition_version')!r}")
    if not isinstance(d.get("note_ja"), str) or not d["note_ja"].strip():
        raise ZoneRuleError(f"{path}: note_ja が無い/空")
    for block, keys in (("terrain", TERRAIN_KEYS), ("rule", RULE_KEYS)):
        b = d.get(block)
        if not isinstance(b, dict):
            raise ZoneRuleError(f"{path}: {block}: がマッピングになっていない")
        missing = [k for k in keys if k not in b]
        extra = [k for k in b if k not in keys]
        if missing or extra:
            raise ZoneRuleError(f"{path}: {block}: のキーが違う（不足 {missing} / 余分 {extra}）")
        bad = [k for k in keys if isinstance(b[k], bool) or not isinstance(b[k], (int, float))]
        if bad:
            raise ZoneRuleError(f"{path}: {block}: が数値でない: {bad}")
    zones = d.get("zones")
    if not isinstance(zones, list) or [z.get("zone") for z in zones if isinstance(z, dict)] != [1, 2, 3, 4, 5]:
        raise ZoneRuleError(f"{path}: zones: は zone 1..5 の5件を順に持つこと")
    for z in zones:
        miss = [k for k in ZONE_ITEM_KEYS if not z.get(k)]
        if miss:
            raise ZoneRuleError(f"{path}: zone {z.get('zone')}: 必須キーが無い/空: {miss}")
    return d


def load_region_summits(path=REGION_YAML) -> dict[str, float]:
    """region.yaml の `terrain.summit.elevation_m` を `{region_id: m}` で返す（宣言の無い region は含まない）。"""
    with pathlib.Path(path).open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: dict[str, float] = {}
    for region_id, spec in raw.items():
        summit = ((spec or {}).get("terrain") or {}).get("summit")
        if summit is None:
            continue
        try:
            out[region_id] = float(summit["elevation_m"])
        except (KeyError, TypeError, ValueError) as e:
            raise ZoneRuleError(f"{path}: {region_id}: terrain.summit.elevation_m が読めない: {e}") from e
    return out


def _num(v):
    v = (v or "").strip() if isinstance(v, str) else v
    return None if v in (None, "") else float(v)


def load_terrain_points(path, terrain: dict, region_summits: dict[str, float]) -> dict[tuple[str, str], TerrainPoint]:
    """terrain_points.csv を `{(lat, lon): TerrainPoint}` に読む。

    止まる条件: 列が違う／`params_digest` が zone.yaml の現在の `terrain:` と違う（c68 を回し直す）／
    行の `summit_m` が region.yaml の宣言と違う（c68 を回し直す）／region.yaml に宣言の無い region／座標の重複。
    """
    path = pathlib.Path(path)
    if not path.exists():
        raise ZoneRuleError(f"{path} が無い。scripts/c68_gsi_dem_terrain.py を回して作ること")
    want_digest = terrain_params_digest(terrain)
    points: dict[tuple[str, str], TerrainPoint] = {}
    stale_digest: set[str] = set()
    bad_summit: list[str] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in TERRAIN_CSV_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise ZoneRuleError(f"{path}: 列が足りない: {missing}")
        for i, r in enumerate(reader, start=2):
            key = coord_key(r["lat"], r["lon"])
            if key in points:
                raise ZoneRuleError(f"{path}: {i} 行目: 座標が重複: {key}")
            if r["params_digest"] != want_digest:
                stale_digest.add(r["params_digest"])
            rid = r["region_id"]
            if rid not in region_summits:
                raise ZoneRuleError(
                    f"{path}: {i} 行目: region {rid!r} に registry/region.yaml の terrain.summit の宣言が無い")
            summit = float(r["summit_m"])
            if abs(summit - region_summits[rid]) > 1e-6:
                bad_summit.append(f"{rid}: csv {summit} / region.yaml {region_summits[rid]}")
            points[key] = TerrainPoint(
                lat=key[0], lon=key[1], region_id=rid, summit_m=summit,
                elevation_m=_num(r["elevation_m"]), relief_wide_m=_num(r["relief_wide_m"]),
                relief_near_m=_num(r["relief_near_m"]), floor_min_m=_num(r["floor_min_m"]),
                coast_dist_m=_num(r["coast_dist_m"]),
            )
    if stale_digest:
        raise ZoneRuleError(
            f"{path}: params_digest が registry/place/zone.yaml の terrain: の現在値（{want_digest}）と違う"
            f"（csv 側 {sorted(stale_digest)}）。指標の定義を変えたのに c68 を回し直していない。"
            "scripts/c68_gsi_dem_terrain.py を回して terrain_points.csv を作り直すこと")
    if bad_summit:
        raise ZoneRuleError(
            f"{path}: summit_m が registry/region.yaml の terrain.summit.elevation_m と違う"
            f"（{sorted(set(bad_summit))}）。最高峰の宣言を変えたら c68 を回し直すこと")
    return points


def classify(m: TerrainPoint, rule: dict) -> int | None:
    """§1.1 の規則。標高なし・山地判定に要る起伏量なしは None（zone を付けない。推測しない）。"""
    e = m.elevation_m
    if e is None:
        return None
    # 5: 河口・沿岸（地形の種類より先に見る）
    if (m.coast_dist_m is not None and m.coast_dist_m <= rule["coast_dist_max_m"]
            and e <= rule["coast_elev_max_m"]):
        return 5
    if m.relief_wide_m is None:
        return None
    # 1/2: 山地。標高が地域の最高峰の summit_ratio_min 倍以上なら 1
    if m.relief_wide_m >= rule["mountain_relief_min_m"]:
        return 1 if e >= rule["summit_ratio_min"] * m.summit_m else 2
    # 3/4: 低地の3条件を全て満たせば 4、そうでなければ 3
    if m.floor_min_m is None or m.relief_near_m is None:
        return 3
    if (e <= rule["lowland_elev_max_m"] and m.relief_near_m <= rule["lowland_relief_max_m"]
            and round(e - m.floor_min_m, 6) <= rule["lowland_above_floor_max_m"]):
        return 4
    return 3


def classify_sites(sites, points: dict[tuple[str, str], TerrainPoint], rule: dict):
    """`sites`: (site_id, lat, lon, elevation_m) の列。elevation_m IS NOT NULL の行が zone の対象。

    戻り値: `{site_id: (zone または None, TerrainPoint または None)}`（対象外の地点は (None, None)）。
    対象の座標が `points` に無ければ、黙って捨てず地点を列挙して止める。
    """
    out: dict = {}
    missing: list[str] = []
    for site_id, lat, lon, elevation_m in sites:
        if elevation_m is None or lat is None or lon is None:
            out[site_id] = (None, None)
            continue
        p = points.get(coord_key(lat, lon))
        if p is None:
            missing.append(f"{site_id}({lat},{lon})")
            continue
        out[site_id] = (classify(p, rule), p)
    if missing:
        raise ZoneRuleError(
            f"terrain_points.csv に無い座標の地点が {len(missing)} 件ある（c68 を回して）: "
            + ", ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))
    return out
