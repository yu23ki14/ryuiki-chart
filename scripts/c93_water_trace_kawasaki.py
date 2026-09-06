"""川崎市上下水道局 令和8年度水質検査計画 p11 図−7「水質検査地点概要図」→ 町丁目への系統割付

  .venv/bin/python scripts/c93_water_trace_kawasaki.py [--report-only]

出力: data/water/zone_assignment.csv に `TRACE_KWS:` 接頭辞の行を**追記**（既存行は触らない）

なぜラスタから読むのか
----------------------
川崎市は配水池ごとの給水区域を町丁目の粒度で公表していない。いちばん細かい公表物が
水質検査計画 p11 の図−7 で、これは市域を **7 つの「浄水場・配水系統」に塗り分けている**。
系統は市境・区境と一致しないので（麻生区は「企」と「長・企→生田」に割れ、
宮前区は「長」「高石」「宮崎」「鷺沼」に割れる）、区単位のルールでは表せない。
docs/add_utility.md §1 の「図しか無い → ラスタ読み取り（§3-b）」に該当する。

横浜市（scripts/c92_water_trace_yokohama.py）と同じやり方:
e-Stat の町丁目ポリゴンを図の画素に重ね、その中でいちばん多い色を読む。
位置合わせは外形の IoU 最大化。純度（ポリゴン内で最頻色が占める割合）を confidence に落とす。

横浜との違い
------------
1. 図が**べた塗り**（横浜は網点・斜線があったので 420dpi が要った）。それでも解像度は
   横浜と揃えて 420dpi にしてある。
2. 紙面に**同じ色の凡例表が 3 つ**あり、単純な行・列の刈り込みでは落とせない。
   色の付いた画素を連結成分に分け、**地図だけを含む矩形に完全に収まる成分**を残す
   （表は矩形からはみ出すので落ちる）。東扇島のように地図本体と繋がっていない島も
   この規則で拾える。
3. 図は「検査地点概要図」であって「給水区域図」ではないが、凡例の
   「浄水場・配水系統」列が塗り分けの意味そのもの。市域は隙間なく 7 色で塗られている。

読めなかったものは読めないままにする
------------------------------------
純度 0.5 未満の町丁目は行を作らない。0.5〜0.95 は low、0.95 以上でも medium 止まり
（図は配水系統の概略図で、町丁目単位の断定ではない）。high は付けない。
"""
import argparse
import collections
import csv
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import PROC, RAW, ROOT, register  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from shapely.geometry import shape  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

SID = "water_trace_kawasaki"
PDF = RAW / "water/kawasaki/kawasaki_r8_suishitsu_keikaku.pdf"
PNG_PREFIX = RAW / "water/kawasaki/kawasaki_r8_p11"
PNG = PNG_PREFIX.with_name(PNG_PREFIX.name + "-12.png")   # pdftoppm は -<ページ番号> を付ける
ZONES = PROC / "estat_shozaiki_kanagawa.geojson"
CACHE = PROC / f"{SID}_cls.npz"
OUT_CSV = ROOT / "data/water/zone_assignment.csv"
ID_PREFIX = "TRACE_KWS:"

PDF_PAGE = 12          # 紙面 p11 は PDF の 12 ページ目
DPI = 420
DOC_ID = "DOC_KWS_SUISHITSU_R8"
VALID_FROM = "2026-04-01"

PAGE_URL = "https://www.city.kawasaki.jp/800/page/0000083603.html"
LICENSE = ("川崎市ホームページの利用について（出典明示で利用可）"
           "https://www.city.kawasaki.jp/170/page/0000000440.html")

# 420dpi・A3 横（6948×4912）での紙面の造り。地図と凡例表が同じ色を使うので、
# 「色が付いた画素」だけでは分けられない。次の 2 段で地図だけを取り出す。
#   1. TABLES の矩形（凡例表 3 つ・写真 2 枚・右端の見出し帯）を先に塗り潰す
#   2. 残りを連結成分に分け、MAP_BOX に収まり MIN_COMPONENT 以上のものを地図とする
# 矩形は 1 度だけ実測して書き写したもの。地図はどの矩形にも掛かっていない
# （掛かっていれば地図が欠けるので、実行時の成分一覧で分かる）。
EXPECTED_SIZE = (6948, 4912)
TABLES = [
    (4750, 6500,  700, 2450),   # 右「水質基準に係る検査の検査地点」表（記号の丸を含む）
    ( 600, 2100, 2650, 4600),   # 左下「毎日検査」表
    (2000, 3500, 3850, 4600),   # 中下の表
    (6600, 6948,    0, 4912),   # 右端の見出し帯
    ( 900, 1900,  400,  950),   # 左上の写真（採水作業）
    (5200, 6500, 3400, 4600),   # 右下の写真（水質自動測定装置）
]
MAP_BOX = (1100, 5700, 900, 3800)     # x0, x1, y0, y1
MIN_COMPONENT = 120                   # 1/8 解像度での画素数。凡例の▲印を落とし飛地の岡上は残す

# 7 系統の参照色。凡例表の色見本ではなく**地図本体の頻出色クラスタ**から取った実測値。
# facility_id の意味:
#   企のみ      → 企業団西長沢浄水場をそのまま（酒匂川 59.1% / 相模川 40.9%）
#   長のみ      → 川崎市長沢浄水場（相模川 100%）
#   長・企→○○ → 両者が混ざる配水池。混合比は非公表なので junction を作り basis=unknown
SYSTEMS = [
    ("kgd",      (189, 253, 226), "FAC_KGD_NISHINAGASAWA", "企業団西長沢浄水場のみ"),
    ("ikuta",    (253, 253,  57), "FAC_KWS_IKUTA",         "長沢・企業団西長沢 → 生田配水池"),
    ("takaishi", (217,  93, 201), "FAC_KWS_TAKAISHI",      "長沢・企業団西長沢 → 高石配水塔"),
    ("miyazaki", ( 97, 161, 217), "FAC_KWS_MIYAZAKI",      "長沢・企業団西長沢 → 宮崎配水塔"),
    ("nagasawa", (253, 177,  53), "FAC_KWS_NAGASAWA",      "長沢浄水場のみ"),
    ("saginuma", (149, 253, 109), "FAC_KWS_SAGINUMA",      "長沢・企業団西長沢 → 鷺沼配水池"),
    ("sueyoshi", (253, 189, 245), "FAC_KWS_SUEYOSHI",      "長沢・企業団西長沢 → 末吉配水池"),
]
NAMES = [s[0] for s in SYSTEMS]
REF = np.array([s[1] for s in SYSTEMS])
FACILITY = {s[0]: s[2] for s in SYSTEMS}
SYSNAME = {s[0]: s[3] for s in SYSTEMS}

# 参照色どうしのいちばん近い組は「生田の黄」と「長沢の橙」で距離 76。半分の 38 まで許せる
# 理屈だが、25 に絞ってある。図には
#   ・地点記号の純黄（253,253,0）— 生田の黄まで距離 57
#   ・施設名を載せた半透明の白い箱 — 高石の赤紫に白を混ぜると末吉の桃色に化ける
# という 2 種類の紛らわしい画素があり、どちらも 25 なら「どの色でもない」（-1）に落ちる。
# 面の内側は単色べた塗りなので、絞っても多数決に要る画素は十分残る。
COLOR_TOL = 25

# 検証用。図−7 の凡例表が「検査地点 → 浄水場・配水系統」を 33 か所ぶん名指ししている。
# そのうち**町丁目名が施設名から一意に決まるもの**だけを突合に使う（公園名から町名を
# 推測しない）。s_name は e-Stat の表記に合わせてある。
STATED_POINTS = [
    # (区, 町丁目名, 系統, 施設名)
    ("川崎市麻生区", "王禅寺",   "kgd",      "A 王禅寺けやき公園"),
    ("川崎市麻生区", "栗木台",   "kgd",      "K 栗木台けやき公園"),
    ("川崎市麻生区", "白鳥",     "kgd",      "1 白鳥諏訪公園"),
    ("川崎市麻生区", "虹ケ丘",   "kgd",      "9 虹ヶ丘南公園"),
    ("川崎市麻生区", "岡上",     "kgd",      "12 麻生市民館岡上分館"),
    ("川崎市麻生区", "金程",     "ikuta",    "C 金程夕木公園"),
    ("川崎市高津区", "下作延",   "ikuta",    "L 下作延身代り公園"),
    ("川崎市高津区", "久地",     "ikuta",    "8 久地の里公園前"),
    ("川崎市宮前区", "犬蔵",     "takaishi", "B 犬蔵さくらの丘公園 / 19 犬蔵くすのき公園"),
    ("川崎市麻生区", "百合丘",   "takaishi", "13 百合丘こども文化センター"),
    ("川崎市多摩区", "長尾",     "miyazaki", "J 長尾宮前公園 / 14 長尾加圧ポンプ所"),
    ("川崎市宮前区", "有馬",     "miyazaki", "M 有馬やまもも公園"),
    ("川崎市宮前区", "野川",     "nagasawa", "I 野川第5公園"),
    ("川崎市高津区", "久末",     "nagasawa", "2 久末ポンプ場"),
    ("川崎市中原区", "上小田中", "saginuma", "H 上小田中第5公園"),
    ("川崎市中原区", "等々力",   "saginuma", "7 等々力緑地"),
    ("川崎市幸区",   "古市場",   "sueyoshi", "E 古市場第2公園"),
    ("川崎市川崎区", "東扇島",   "sueyoshi", "F 東扇島西公園"),
    ("川崎市川崎区", "殿町",     "sueyoshi", "11 殿町いこいの家"),
    ("川崎市川崎区", "川中島",   "sueyoshi", "16 川中島公園"),
    ("川崎市川崎区", "京町",     "sueyoshi", "17 京町ポンプ場"),
]

PURITY_MEDIUM = 0.95
PURITY_MIN = 0.50
# 町丁目のポリゴンのうち、色が読めた画素が占める割合の下限。
# 図には施設名を載せた半透明の白い箱が 8 つあり、その下では色が白に寄って
# 「どの参照色でもない」に落ちる。小さい町丁目がまるごとその箱に隠れると、
# 箱からはみ出した数十画素だけで多数決することになり当てにならない。
# 図の上で小さい町丁目ほどこれに当たるので、下限を引いて行を作らないようにする。
MIN_COVER = 0.10


# ------------------------------------------------------------------ #
# 1. 画像化                                                            #
# ------------------------------------------------------------------ #

def render():
    if PNG.exists() and PNG.stat().st_size > 0:
        print(f"  [cache] {PNG.relative_to(ROOT)}")
        return PNG
    if not PDF.exists():
        sys.exit(f"! {PDF.relative_to(ROOT)} が無い。先に scripts/c91_water_docs.py を実行する。")
    PNG.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-f", str(PDF_PAGE), "-l", str(PDF_PAGE), "-r", str(DPI),
                    "-png", str(PDF), str(PNG_PREFIX)], check=True)
    print(f"  [render] {PNG.relative_to(ROOT)} {PNG.stat().st_size/1e6:.1f} MB")
    return PNG


# ------------------------------------------------------------------ #
# 2. 地図だけを切り出して色を分類                                       #
# ------------------------------------------------------------------ #

def _components(mask, k=8):
    """1/k に落として 4 近傍の連結成分を振る。scipy は入っていないので自前。"""
    H, W = mask.shape
    small = np.asarray(Image.fromarray((mask * 255).astype(np.uint8))
                       .resize((W // k, H // k), Image.BILINEAR)) > 127
    lab = np.zeros(small.shape, np.int32)
    hh, ww = small.shape
    cur, sizes = 0, {}
    for sy in range(hh):
        for sx in range(ww):
            if small[sy, sx] and lab[sy, sx] == 0:
                cur += 1
                n, stack = 0, [(sy, sx)]
                lab[sy, sx] = cur
                while stack:
                    y, x = stack.pop()
                    n += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        y2, x2 = y + dy, x + dx
                        if 0 <= y2 < hh and 0 <= x2 < ww and small[y2, x2] and lab[y2, x2] == 0:
                            lab[y2, x2] = cur
                            stack.append((y2, x2))
                sizes[cur] = n
    return lab, sizes, k


def map_mask(a):
    """紙面から「地図の面」だけを取り出す。

    色の付いた画素（彩度のある画素）を closing で面に戻し、連結成分に分けて、
    MAP_BOX に完全に収まり MIN_COMPONENT 以上のものだけを残す。
    凡例表は 3 つとも MAP_BOX からはみ出すので落ちる。
    """
    mx, mn = a.max(2), a.min(2)
    colored = ((mx - mn) > 40) & (mx > 90)
    for x0, x1, y0, y1 in TABLES:
        colored[y0:y1, x0:x1] = False
    im = Image.fromarray((colored * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.MinFilter(9))
    solid = np.asarray(im) > 127

    lab, sizes, k = _components(solid)
    x0, x1, y0, y1 = MAP_BOX
    keep = []
    for cid, n in sizes.items():
        if n < MIN_COMPONENT:
            continue
        ys, xs = np.nonzero(lab == cid)
        bx0, bx1, by0, by1 = xs.min() * k, xs.max() * k, ys.min() * k, ys.max() * k
        inside = (bx0 >= x0 and bx1 <= x1 and by0 >= y0 and by1 <= y1)
        print(f"  成分 {cid:>4}: {n*k*k:>10,}px  x {bx0}-{bx1} y {by0}-{by1}  "
              f"{'← 地図' if inside else '（表・写真として除外）'}")
        if inside:
            keep.append(cid)
    if not keep:
        sys.exit("! 地図の連結成分が見つからない。MAP_BOX を見直すこと")
    sel = np.isin(lab, keep)
    return np.asarray(Image.fromarray((sel * 255).astype(np.uint8))
                      .resize((a.shape[1], a.shape[0]), Image.NEAREST)) > 127


def classify(png):
    """(cls, mask) を返す。cls は 7 系統の番号、地図の外とどの色にも遠い画素は -1。"""
    if CACHE.exists() and CACHE.stat().st_mtime >= png.stat().st_mtime:
        z = np.load(CACHE)
        print(f"  [cache] {CACHE.relative_to(ROOT)}  地図マスク {z['mask'].sum():,}px")
        return z["cls"], z["mask"]

    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int32)
    if a.shape[1::-1] != EXPECTED_SIZE:
        print(f"  [warn] 紙面サイズが想定と違う {a.shape[1::-1]} != {EXPECTED_SIZE}。"
              f"MAP_BOX を見直すこと")
    mask = map_mask(a)

    best = np.full(a.shape[:2], 1 << 30, dtype=np.int32)
    cls = np.full(a.shape[:2], -1, dtype=np.int8)
    lim = COLOR_TOL * COLOR_TOL
    for i, ref in enumerate(REF):
        d = ((a - ref) ** 2).sum(2)
        hit = (d < best) & (d < lim) & mask
        best = np.where(hit, d, best)
        cls[hit] = i
    print(f"  地図マスク {mask.sum():,}px / 色が付いた画素 {(cls >= 0).sum():,}px")
    for i, n in enumerate(NAMES):
        print(f"    {n:<9} {(cls == i).sum():>10,}px")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, cls=cls, mask=mask)
    return cls, mask


# ------------------------------------------------------------------ #
# 3. 位置合わせ（c92 と同じ。図に目盛りが無いので外形の重なりで探す）    #
# ------------------------------------------------------------------ #

PARAM_NAMES = ("sx", "sy", "k1", "k2", "tx", "ty")


def make_raster(polys, lon0, lat1, anchor, shape_hw):
    H, W = shape_hw
    uc, vc = anchor
    rings = []
    for p in polys:
        c = np.asarray(p.exterior.coords)
        rings.append((c[:, 0] - lon0 - uc, (lat1 - c[:, 1]) - vc))

    def raster(sx, sy, k1, k2, cx, cy):
        img = Image.new("1", (W, H), 0)
        dr = ImageDraw.Draw(img)
        for du, dv in rings:
            x = sx * (du + k1 * dv) + cx
            y = sy * (dv + k2 * du) + cy
            dr.polygon(list(zip(x.tolist(), y.tolist())), fill=1)
        return np.asarray(img)

    return raster


def _search(score, p0, steps, floor, max_sweeps=200):
    best = list(p0)
    val = score(*best)
    for _ in range(max_sweeps):
        improved = False
        for i in range(len(best)):
            if steps[i] == 0:
                continue
            for sign in (1, -1):
                while True:
                    cand = list(best)
                    cand[i] = best[i] * (1 + sign * steps[i]) if i < 2 else best[i] + sign * steps[i]
                    v = score(*cand)
                    if v <= val + 1e-9:
                        break
                    best, val, improved = cand, v, True
        if not improved:
            steps = [s / 2 for s in steps]
            if all(s < f for s, f in zip(steps, floor)):
                break
    return val, best


def align(mask, polys, lon0, lat1, bbox, free_shear, k=4, p0=None):
    small = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(
        (mask.shape[1] // k, mask.shape[0] // k), Image.BILINEAR)) > 127
    union = unary_union(polys)
    lon_min, lat_min, lon_max, lat_max = union.bounds
    c = union.centroid
    anchor = (c.x - lon0, lat1 - c.y)
    raster = make_raster(polys, lon0, lat1, anchor, small.shape)

    def iou(sx, sy, k1, k2, cx, cy):
        r = raster(sx, sy, k1, k2, cx, cy)
        return np.logical_and(r, small).sum() / max(1, np.logical_or(r, small).sum())

    if p0 is None:
        xmin, xmax, ymin, ymax = [b / k for b in bbox]
        sx = (xmax - xmin) / (lon_max - lon_min)
        sy = (ymax - ymin) / (lat_max - lat_min)
        p0 = [sx, sy, 0.0, 0.0,
              xmin + sx * (c.x - lon_min), ymin + sy * (lat_max - c.y)]
    steps = [0.04, 0.04, 0.01, 0.01, 16.0, 16.0]
    floor = [0.0002, 0.0002, 0.0001, 0.0001, 0.25, 0.25]
    if not free_shear:
        steps[2] = steps[3] = 0.0
    val, best = _search(iou, p0, steps, floor)
    return val, best, anchor


def to_canonical(p, anchor, k):
    sx, sy, k1, k2, cx, cy = p
    sx, sy, cx, cy = sx * k, sy * k, cx * k, cy * k
    uc, vc = anchor
    return [sx, sy, k1, k2, cx - sx * (uc + k1 * vc), cy - sy * (vc + k2 * uc)]


# ------------------------------------------------------------------ #
# 4. 町丁目ごとの多数決                                                #
# ------------------------------------------------------------------ #

def sample(cls, params, lon0, lat1, feats):
    sx, sy, k1, k2, tx, ty = params
    H, W = cls.shape

    def px(lo, la):
        u, v = lo - lon0, lat1 - la
        return sx * (u + k1 * v) + tx, sy * (v + k2 * u) + ty

    out, tiny = {}, 0
    for f in feats:
        g = shape(f["geometry"])
        polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        xy = [[px(lo, la) for lo, la in p.exterior.coords] for p in polys]
        xs = [x for r in xy for x, _ in r]
        ys = [y for r in xy for _, y in r]
        x0, x1 = int(max(0, min(xs) - 1)), int(min(W, max(xs) + 2))
        y0, y1 = int(max(0, min(ys) - 1)), int(min(H, max(ys) + 2))
        if x1 <= x0 or y1 <= y0:
            continue
        img = Image.new("1", (x1 - x0, y1 - y0), 0)
        dr = ImageDraw.Draw(img)
        for r in xy:
            dr.polygon([(x - x0, y - y0) for x, y in r], fill=1)
        sub = cls[y0:y1, x0:x1]
        drawn = np.asarray(img)
        area = int(drawn.sum())
        vals = sub[drawn & (sub >= 0)]
        if vals.size < 5:
            cx, cy = px(*g.representative_point().coords[0])
            R = 10
            win = cls[max(0, int(cy) - R):int(cy) + R, max(0, int(cx) - R):int(cx) + R]
            vals = win[win >= 0]
            tiny += 1
        if vals.size == 0:
            continue
        b = np.bincount(vals, minlength=len(NAMES))
        out[f["properties"]["key_code"]] = {
            "sys": NAMES[int(b.argmax())],
            "purity": float(b.max() / b.sum()),
            "cover": float(vals.size / max(1, area)),
            "n": int(b.sum()),
            "ward": (f["properties"].get("city_name") or "").replace("川崎市", ""),
            "city": f["properties"].get("city_name"),
            "s_name": f["properties"].get("s_name"),
            "name": f["properties"].get("name"),
        }
    if tiny:
        print(f"  [note] 図の上で数画素しか無い町丁目 {tiny} 件は重心の周りで代用した")
    return out


# ------------------------------------------------------------------ #
# 5. 検証（凡例表が名指しした検査地点との突合）                          #
# ------------------------------------------------------------------ #

def cross_check(traced):
    """図−7 の凡例表が「この地点はこの系統」と書いている 21 の町丁目を読み取り結果と比べる。

    町丁目名は「○○一丁目」のように丁目に割れていることがあるので前方一致で拾い、
    拾えた町丁目すべてについて系統が一致するかを見る（多数決ではなく 1 件ずつ）。
    """
    by_key = traced
    rows, hit, miss = [], 0, 0
    for city, s_name, sys_name, label in STATED_POINTS:
        cands = [(k, v) for k, v in by_key.items()
                 if v["city"] == city and (v["s_name"] or "").startswith(s_name)]
        if not cands:
            rows.append((label, city, s_name, sys_name, None, "町丁目が見つからない"))
            continue
        got = collections.Counter(v["sys"] for _, v in cands)
        ok = sum(n for s, n in got.items() if s == sys_name)
        hit += ok
        miss += len(cands) - ok
        rows.append((label, city, s_name, sys_name,
                     dict(got.most_common()), "一致" if ok == len(cands)
                     else f"{ok}/{len(cands)} 一致"))
    rate = hit / (hit + miss) if (hit + miss) else 0.0
    # 代表一致率: 検査地点は町丁目 1 つの中の 1 点なので、同名の町丁目（「王禅寺東一丁目」〜
    # 「王禅寺西八丁目」の 16 件など）全部が一致することは求められない。
    # 最頻の系統が凡例と一致するかを地点ごとに 1 票として数えたもの。こちらを主に見る。
    modal_ok = sum(1 for r in rows if r[4] and max(r[4], key=r[4].get) == r[3])
    modal_n = sum(1 for r in rows if r[4])
    modal = modal_ok / modal_n if modal_n else 0.0
    return rows, hit, miss, rate, modal, modal_ok, modal_n


# ------------------------------------------------------------------ #

def write_csv(traced, iou, mode, rate):
    """既存の zone_assignment.csv を読み、TRACE_KWS: の行だけ入れ替えて書き戻す。

    c92（横浜）は CSV を丸ごと作り直すが、そのやり方だと後から足した県営水道の行を
    消してしまう。ここでは自分の接頭辞の行だけを差し替える（冪等）。
    """
    cols = ["assignment_id", "key_code", "facility_id", "share", "confidence",
            "valid_from", "valid_to", "source_doc_id", "note_ja"]
    existing = []
    if OUT_CSV.exists():
        with open(OUT_CSV, encoding="utf-8-sig", newline="") as f:
            existing = [r for r in csv.DictReader(f)
                        if not (r.get("assignment_id") or "").startswith(ID_PREFIX)]
    new, n_by_conf = [], collections.Counter()
    for key in sorted(traced):
        v = traced[key]
        if v["purity"] < PURITY_MIN or v["cover"] < MIN_COVER:
            continue
        conf = "medium" if v["purity"] >= PURITY_MEDIUM else "low"
        n_by_conf[conf] += 1
        note = (f"令和8年度水質検査計画 p11 図−7「水質検査地点概要図」の塗り分けからの"
                f"ラスタ読み取り。{SYSNAME[v['sys']]}。図は配水系統の概略で町丁目単位の"
                f"断定ではない。純度 {v['purity']*100:.0f}%（判定に使った画素 {v['n']}）。"
                f"位置合わせ IoU {iou:.3f}（{mode}）。凡例表が名指しした検査地点との"
                f"代表一致率 {rate*100:.0f}%")
        new.append({
            "assignment_id": f"{ID_PREFIX}{key}",
            "key_code": key,
            "facility_id": FACILITY[v["sys"]],
            "share": "1.0",
            "confidence": conf,
            "valid_from": VALID_FROM,
            "valid_to": "",
            "source_doc_id": DOC_ID,
            "note_ja": note,
        })
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, cols, lineterminator="\n")
        wr.writeheader()
        wr.writerows(existing)
        wr.writerows(new)
    print(f"  既存 {len(existing)} 行を残し {len(new)} 行を追記")
    return n_by_conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true", help="CSV を書かずに数字だけ出す")
    ap.add_argument("--k", type=int, default=4, help="位置合わせの縮小率（既定 1/4）")
    args = ap.parse_args()

    png = render()
    cls, mask = classify(png)
    ys, xs = np.nonzero(mask)
    bbox = (int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max()))

    if not ZONES.exists():
        sys.exit(f"! {ZONES.relative_to(ROOT)} が無い。先に scripts/c90_estat_shozaiki.py を実行する。")
    fc = json.load(open(ZONES, encoding="utf-8"))
    feats = [f for f in fc["features"]
             if (f["properties"].get("city_name") or "").startswith("川崎市")]
    geoms = [shape(f["geometry"]) for f in feats]
    kws = unary_union(geoms)
    polys = list(kws.geoms) if kws.geom_type == "MultiPolygon" else [kws]
    lon0, lat_min, lon_max, lat1 = kws.bounds
    print(f"  川崎市の町丁目 {len(feats)} 件 / 外形 {len(polys)} 片")

    print("\n位置合わせ")
    iou4, q4, anchor = align(mask, polys, lon0, lat1, bbox, free_shear=False, k=args.k)
    print(f"  4 パラメータ（拡大・平行移動）  IoU = {iou4:.4f}")
    iou6, q6, _ = align(mask, polys, lon0, lat1, bbox, free_shear=True, k=args.k, p0=q4)
    print(f"  6 パラメータ（＋回転・せん断）  IoU = {iou6:.4f}  k1={q6[2]:+.4f} k2={q6[3]:+.4f}")
    p4 = to_canonical(q4, anchor, args.k)
    p6 = to_canonical(q6, anchor, args.k)

    results = {}
    for mode, iou, params in (("4パラメータ", iou4, p4), ("6パラメータ", iou6, p6)):
        traced = sample(cls, params, lon0, lat1, feats)
        rows, hit, miss, rate, modal, mok, mn = cross_check(traced)
        results[mode] = (iou, params, traced, rows, modal, rate, mok, mn, hit, miss)
        print(f"  {mode}: 色が読めた町丁目 {len(traced)}/{len(feats)}  "
              f"名指し地点との代表一致率 {modal*100:.1f}%（{mok}/{mn}）"
              f" / 同名町丁目まで含めた一致率 {rate*100:.1f}%（{hit}/{hit+miss}）")

    # IoU が上がっても一致率が下がるなら採らない（横浜で同じことが起きた）
    best_mode = "4パラメータ"
    if results["6パラメータ"][0] > results["4パラメータ"][0] + 1e-4 and \
       results["6パラメータ"][4] >= results["4パラメータ"][4] - 1e-9:
        best_mode = "6パラメータ"
    iou, params, traced, rows, modal, rate, mok, mn, hit, miss = results[best_mode]
    print(f"\n採用: {best_mode}（IoU {iou:.4f} / 代表一致率 {modal*100:.1f}% "
          f"/ 町丁目ごとの一致率 {rate*100:.1f}%）")
    print("  " + "  ".join(f"{n}={v:.4f}" for n, v in zip(PARAM_NAMES, params)))

    print("\n凡例表が名指しした検査地点との突合")
    for label, city, s_name, want, got, verdict in rows:
        print(f"  {verdict:<14} {city}{s_name:<8} 図の凡例={want:<9} 読み取り={got}  ({label})")

    pur = np.array([v["purity"] for v in traced.values()])
    print(f"\n読み取り: {len(traced)} / {len(feats)} 町丁目（{len(traced)/len(feats)*100:.1f}%）")
    for t in (0.95, 0.9, 0.8, 0.7, 0.5):
        print(f"  純度 {int(t*100)}% 以上: {(pur >= t).sum():5d}（{(pur >= t).mean()*100:.1f}%）")
    cov = np.array([v["cover"] for v in traced.values()])
    print(f"  純度 50% 未満（行を作らない）: {(pur < PURITY_MIN).sum()}")
    print(f"  色が読めた画素がポリゴンの {int(MIN_COVER*100)}% 未満（行を作らない）: "
          f"{(cov < MIN_COVER).sum()}")
    print(f"  どちらかに掛かって行を作らない: {((pur < PURITY_MIN) | (cov < MIN_COVER)).sum()}")

    per = collections.defaultdict(collections.Counter)
    for v in traced.values():
        per[v["ward"]][v["sys"]] += 1
    print(f"\n{'区':<8}{'計':>5}  内訳")
    for ward in sorted(per, key=lambda w: -sum(per[w].values())):
        c = per[ward]
        print(f"{ward:<8}{sum(c.values()):>5}  " + "  ".join(f"{k}:{v}" for k, v in c.most_common()))
    tot = collections.Counter(v["sys"] for v in traced.values())
    print("系統別:", "  ".join(f"{k}={tot[k]}" for k in NAMES))

    if args.report_only:
        print("\n--report-only なので CSV は書かない。")
        return 0

    n_by_conf = write_csv(traced, iou, best_mode, modal)
    n = sum(n_by_conf.values())
    print(f"\n{OUT_CSV.relative_to(ROOT)} に {ID_PREFIX} の行 {n} 本  "
          f"medium={n_by_conf['medium']} low={n_by_conf['low']}"
          f"  （純度不足で見送り {len(traced)-n}・色が読めず {len(feats)-len(traced)}）")

    register(SID, "川崎市上下水道局 令和8年度水質検査計画 p11 図−7 の塗り分けのラスタ読み取り",
             "川崎市上下水道局", PAGE_URL, "water_supply", "pdf-raster", "csv", LICENSE,
             1, n,
             notes=(f"図−7「水質検査地点概要図」を {DPI}dpi で画像化し 7 系統の色に分類。"
                    f"凡例表と地図が同じ色を使うので、色の付いた連結成分のうち地図の矩形に"
                    f"完全に収まるものだけを地図とみなした。e-Stat 町丁目ポリゴンとの"
                    f"位置合わせは{best_mode}アフィンで IoU {iou:.3f}。純度 {PURITY_MEDIUM:.2f} 以上を"
                    f"medium・{PURITY_MIN:.2f} 以上を low とし、それ未満は行を作らない。"
                    f"凡例表が名指しした検査地点との代表一致率 {modal*100:.1f}%"
                    f"（町丁目ごとに数えると {rate*100:.1f}%）。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
