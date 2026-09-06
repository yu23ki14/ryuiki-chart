"""横浜市水道局 令和8年度水質検査計画 p11「各水源の主な給水区域」図 → 町丁目への系統割付

  .venv/bin/python scripts/c92_water_trace_yokohama.py [--report-only]

出力: data/water/zone_assignment.csv（既存を置き換える）/ reports/trace_yokohama.md の数字

なぜラスタから読むのか
----------------------
浄水場（配水系統）ごとの給水区域は、町丁目の粒度ではどこにも公表されていない
（`reports/yokohama.md` / `reports/inquiry_yokohama.md`）。いちばん細かい公表物が
水質検査計画 p11 の塗り分け図で、これは**区より細かい境界**で 5 系統を分けている。
設計図 docs/WATER_SOURCE_MAP.md §3 は当初「トレースはしない」と決めていたが、
§7b の実測（区単位だと割付率 42.0%）を受けて 2026-09-05 に司令塔がこの件に限り解除した。

やっていることは「図をなぞってポリゴンを起こす」ではなく、
**e-Stat の町丁目ポリゴンを図の画素に重ね、その中でいちばん多い色を読む**。
境界線を人の目で引き直すより、どこがどれだけ曖昧かを数字（純度）で残せる。

読めなかったものは読めないままにする
------------------------------------
純度（ポリゴン内で最頻色が占める割合）が 0.5 未満の町丁目は**行を作らない**。
0.5〜0.95 は `low`、0.95 以上でも `medium` 止まりにする。図の表題が「**主な**給水区域」で
あって町丁目単位の断定ではないため、この読み取りだけで `high` が付くことは無い。

西長沢と相模原が同じ色である件
------------------------------
図は「企業団酒匂川系統（西長沢浄水場系・相模原浄水場系）」を 1 色で塗っている。
2 つの浄水場は原水構成が違う（`reports/kigyodan.md`）が、図からは区別できない。
色を勝手に 2 つに割らず、供給水量の大きい西長沢に寄せて note_ja にその旨を必ず書く。
「寄せた」のは読み取りの結果ではなくこちらの選択なので、行ごとに残しておかないと後から分からない。
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

SID = "water_trace_yokohama"
PDF = RAW / "water/yokohama/yokohama_R8_suishitsu_keikaku.pdf"
PNG_PREFIX = RAW / "water/yokohama/suishitsu_r8_p11"
PNG = PNG_PREFIX.with_name(PNG_PREFIX.name + "-12.png")   # pdftoppm は -<ページ番号> を付ける
ZONES = PROC / "estat_shozaiki_kanagawa.geojson"
CACHE = PROC / f"{SID}_cls.npz"          # 色分類の中間結果（PNG より新しければ使い回す）
OUT_CSV = ROOT / "data/water/zone_assignment.csv"

PDF_PAGE = 12          # p11 の紙面は PDF の 12 ページ目（表紙で 1 ずれる）
DPI = 420              # 斜線・点パターンの網点が潰れない最小の解像度として実測で選んだ
DOC_ID = "DOC_YOK_SUISHITSU_R8"
VALID_FROM = "2026-04-01"   # 令和8年度の始まり。zone_rule.csv の既存行と同じ基準に揃える

PAGE_URL = ("https://www.city.yokohama.lg.jp/kurashi/sumai-kurashi/suido-gesui/suido/"
            "suishitsu/suidosui/suishitsu-keikaku.html")
LICENSE = ("横浜市サイトの利用について（出典明示で利用可）"
           "https://www.city.yokohama.lg.jp/site/copyright.html")

# 図の本体だけを切り出す上下端（420dpi・4912px の紙面での画素位置）。
# 上は見出し「各水源の主な給水区域」の下、下は凡例の上。凡例の色見本を混ぜると
# 位置合わせが凡例の四角に引っ張られるので必ず落とす。
CROP_Y0, CROP_Y1 = 150, 3740
EXPECTED_SIZE = (3473, 4912)

# 5 系統の参照色。凡例の色見本ではなく**地図本体の頻出色クラスタ**から取った実測値。
# 凡例の見本は縁取りとアンチエイリアスで平均が寄っていて、本体の面の色とは数値が違う。
SYSTEMS = [
    ("kawai",      (252, 199, 119), "FAC_YOK_KAWAI",         "道志川系統（川井浄水場系）"),
    ("nishiya",    (242, 147, 129), "FAC_YOK_NISHIYA",       "相模川系統（西谷浄水場系）"),
    ("kosuzume",   (152, 164, 204), "FAC_YOK_KOSUZUME",      "馬入川系統（小雀浄水場系）"),
    ("kgd_sakawa", (163, 204, 144), "FAC_KGD_NISHINAGASAWA", "企業団酒匂川系統（西長沢・相模原浄水場系）"),
    ("kgd_ayase",  (244, 169, 199), "FAC_KGD_AYASE",         "企業団相模川系統（綾瀬浄水場系）"),
]
NAMES = [s[0] for s in SYSTEMS]
REF = np.array([s[1] for s in SYSTEMS])
FACILITY = {s[0]: s[2] for s in SYSTEMS}
SYSNAME = {s[0]: s[3] for s in SYSTEMS}

# 参照色からの距離のしきい値。5 色は互いに 60 以上離れているので、55 なら
# アンチエイリアスの縁を拾いすぎず、かつ網点の地の色を落としすぎない。
COLOR_TOL = 55

# 検証用。各浄水場の施設概要ページが本文で挙げている区（企業団系は各ページが触れていない）。
STATED = {
    "kawai":    {"旭区", "緑区", "青葉区", "泉区", "瀬谷区"},
    "nishiya":  {"鶴見区", "神奈川区", "西区", "中区", "南区", "保土ケ谷区"},
    "kosuzume": {"港南区", "旭区", "磯子区", "金沢区", "港北区", "戸塚区", "栄区", "泉区"},
}

# confidence の段階。純度（ポリゴン内で最頻色が占める割合）で決める。
PURITY_MEDIUM = 0.95
PURITY_MIN = 0.50


# ------------------------------------------------------------------ #
# 1. 画像化                                                            #
# ------------------------------------------------------------------ #

def render():
    """p11 を pdftoppm で PNG にする。既にあれば作り直さない（冪等）。"""
    if PNG.exists() and PNG.stat().st_size > 0:
        print(f"  [cache] {PNG.relative_to(ROOT)}")
        return PNG
    if not PDF.exists():
        sys.exit(f"! {PDF.relative_to(ROOT)} が無い。先に scripts/c91_water_docs.py を実行する。")
    PNG.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-f", str(PDF_PAGE), "-l", str(PDF_PAGE), "-r", str(DPI), "-png",
         str(PDF), str(PNG_PREFIX)],
        check=True)
    print(f"  [render] {PNG.relative_to(ROOT)} {PNG.stat().st_size/1e6:.1f} MB")
    return PNG


# ------------------------------------------------------------------ #
# 2. 色の分類                                                          #
# ------------------------------------------------------------------ #

def classify(png):
    """画素を 5 系統に分類する。戻り値 (cls, mask, bbox)。

    cls  : 図の本体を切り出した領域の系統番号。どの参照色からも遠い画素は -1。
    mask : 位置合わせに使う「塗られている範囲」。斜線・点パターンは画素単位では
           穴だらけなので closing（膨張→収縮）で面に戻す。地図の外に散っている
           文字の色かぶりは、行・列の画素数で外側を刈って落とす。

    結果は npz に残す。分類は 2 分ほど掛かるが決定的なので、位置合わせを試し直すたびに
    やり直す理由が無い（PNG を作り直したら消えるように PNG の更新時刻で無効化する）。
    """
    if CACHE.exists() and CACHE.stat().st_mtime >= png.stat().st_mtime:
        z = np.load(CACHE)
        cls, mask = z["cls"], z["mask"]
        bbox = tuple(int(v) for v in z["bbox"])
        print(f"  [cache] {CACHE.relative_to(ROOT)}  地図マスク {mask.sum():,}px")
        return cls, mask, bbox

    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int32)
    if a.shape[1::-1] != EXPECTED_SIZE:
        print(f"  [warn] 紙面サイズが想定と違う {a.shape[1::-1]} != {EXPECTED_SIZE}。"
              f"CROP_Y0/CROP_Y1 を見直すこと")
    body = a[CROP_Y0:CROP_Y1]
    # 参照色ごとに二乗距離を順に取る。5 色ぶんを一度に配列にすると 1.5GB 使うので回す。
    best = np.full(body.shape[:2], 1 << 30, dtype=np.int32)
    cls = np.full(body.shape[:2], -1, dtype=np.int8)
    lim = COLOR_TOL * COLOR_TOL
    for i, ref in enumerate(REF):
        d = ((body - ref) ** 2).sum(2)
        hit = (d < best) & (d < lim)
        best = np.where(hit, d, best)
        cls[hit] = i

    im = Image.fromarray(((cls >= 0) * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MaxFilter(15)).filter(ImageFilter.MinFilter(9))
    mask = np.asarray(im) > 127
    rows, cols = mask.sum(1), mask.sum(0)
    ry, rx = np.nonzero(rows > 60)[0], np.nonzero(cols > 60)[0]
    mask[:ry.min()] = False
    mask[ry.max() + 1:] = False
    mask[:, :rx.min()] = False
    mask[:, rx.max() + 1:] = False
    bbox = (int(rx.min()), int(rx.max()), int(ry.min()), int(ry.max()))
    print(f"  地図マスク {mask.sum():,}px  bbox x{bbox[0]}-{bbox[1]} y{bbox[2]}-{bbox[3]}"
          f"  crop={mask.shape}")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, cls=cls, mask=mask, bbox=np.array(bbox))
    return cls, mask, bbox


# ------------------------------------------------------------------ #
# 3. 位置合わせ                                                        #
# ------------------------------------------------------------------ #
# 図には緯度経度の目盛りも既知の基準点も無いので、外形が最も重なる変換を探すしかない。
# 4 パラメータ（拡大 sx,sy + 平行移動 tx,ty）に加えて、せん断 k1,k2 を入れた 6 パラメータ
# （＝一般のアフィン。回転はせん断の組み合わせとして表現される）も試し、IoU の良い方を採る。
#
#   u = lon - lon0 ,  v = lat1 - lat
#   x = sx * (u + k1 * v) + tx
#   y = sy * (v + k2 * u) + ty
#
# k1 = -k2 が純粋な回転にあたる。k1,k2 を独立に動かすので回転＋せん断の 6 自由度を張る。
#
# 探索は「アンカー中心」で持つ。tx,ty をそのまま動かすと拡大と平行移動が強く相関して
# （sx を上げながら tx を下げると絵はほとんど動かない）軸ごとの探索が斜めの尾根で止まる。
# 横浜市の重心を画像上のどこに置くか (cx, cy) に置き換えると、この相関がほぼ消える。

PARAM_NAMES = ("sx", "sy", "k1", "k2", "tx", "ty")


def make_raster(polys, lon0, lat1, anchor, shape_hw):
    """(u, v) をあらかじめ配列にしておき、評価ごとにアフィンを掛けるだけにする。

    外輪郭だけを塗り、内輪郭（穴）は無視する。横浜市の外形に本物の飛び地・湖は無く、
    ここに出る穴 4,179 個は e-Stat ポリゴンを 5.5m で簡略化したときに隣接町丁目の
    共有辺が別々に間引かれてできた隙間（合計面積は市域の 0.12%）。ところが 1/4 解像度で
    塗ると 1 画素未満の隙間も 1 画素幅の線として抜けるので、そのまま穴として扱うと
    ラスタが櫛状に欠けて IoU が 0.86 → 0.82 まで落ちる。実体の無い穴なので塗り潰す。
    """
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
    """各軸に ± を試し、効いている向きには続けて進む。改善が無くなったら刻みを半分にする。

    scipy が無いので最適化は自前。IoU は微分できず画素の離散化で階段状なので、
    勾配法より素朴なパターンサーチの方が素直に動く。
    """
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
    """1/k 解像度で位置合わせする。戻り値 (iou, [sx, sy, k1, k2, tx, ty])（原寸の画素単位）。

    p0 は「アンカー中心」の初期値（粗い解像度で得た解を細かい解像度に渡すのに使う）。
    """
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
        # 初期値は「図の塗り範囲の bbox」と「横浜市の bbox」を合わせたもの
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
    """アンカー中心の解 → sample() が使う (sx, sy, k1, k2, tx, ty)（原寸の画素単位）。"""
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

    out = {}
    tiny = 0
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
        vals = sub[np.asarray(img) & (sub >= 0)]
        if vals.size < 5:
            # 図の上で数画素しか無い町丁目。ポリゴンでは色を拾えないので重心の周りで代用する。
            # 窓はポリゴン外にはみ出すが、この大きさの町丁目は隣とまとめて塗られているので実害は小さい。
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
            "n": int(b.sum()),
            "ward": (f["properties"].get("city_name") or "").replace("横浜市", ""),
            "name": f["properties"].get("name"),
        }
    if tiny:
        print(f"  [note] 図の上で数画素しか無い町丁目 {tiny} 件は重心の周りで代用した")
    return out


# ------------------------------------------------------------------ #
# 5. 検証（公表文章との突合）                                          #
# ------------------------------------------------------------------ #

def cross_check(traced):
    """各浄水場ページの本文が挙げている区と突き合わせる。

    企業団系（kgd_*）は各浄水場ページがそもそも触れていない系統なので、
    「不一致」に数えず別立てで出す。数えてしまうと文章の側の欠落を図の誤りに見せかけることになる。
    """
    per = collections.defaultdict(collections.Counter)
    for v in traced.values():
        per[v["ward"]][v["sys"]] += 1
    rows, agree, disagree = [], 0, 0
    for ward in sorted(per, key=lambda w: -sum(per[w].values())):
        c = per[ward]
        tot = sum(c.values())
        stated = {s for s, wards in STATED.items() if ward in wards}
        hit = sum(n for s, n in c.items() if s in stated)
        kgd = sum(n for s, n in c.items() if s.startswith("kgd"))
        if stated:
            agree += hit
            disagree += tot - hit - kgd
        rows.append({"ward": ward, "total": tot, "counts": dict(c.most_common()),
                     "stated": bool(stated),
                     "hit": hit / tot if stated else None,
                     "kgd": kgd / tot})
    rate = agree / (agree + disagree) if (agree + disagree) else 0.0
    return rows, agree, disagree, rate


# ------------------------------------------------------------------ #

def write_csv(traced, iou, mode):
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["assignment_id", "key_code", "facility_id", "share", "confidence",
            "valid_from", "valid_to", "source_doc_id", "note_ja"]
    n_by_conf = collections.Counter()
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, cols, lineterminator="\n")
        wr.writeheader()
        for key in sorted(traced):
            v = traced[key]
            if v["purity"] < PURITY_MIN:
                continue     # 読めなかったものは「不明」のまま残す（設計図 §6-3）
            conf = "medium" if v["purity"] >= PURITY_MEDIUM else "low"
            n_by_conf[conf] += 1
            # note_ja に ASCII のカンマを入れない（CSV を壊さないため。読点は全角を使う）
            note = (f"令和8年度水質検査計画 p11「各水源の主な給水区域」図からのラスタ読み取り。"
                    f"{SYSNAME[v['sys']]}。図は「主な給水区域」であり町丁目単位の断定ではない。"
                    f"純度 {v['purity']*100:.0f}%（判定に使った画素 {v['n']}）。"
                    f"位置合わせ IoU {iou:.3f}（{mode}）")
            if v["sys"] == "kgd_sakawa":
                note += ("。図では西長沢浄水場系と相模原浄水場系が同じ色で区別できないため"
                         "供給水量の大きい西長沢に寄せている"
                         "（企業団の1日平均供給水量 R7年度 西長沢 467486 ㎥ / 相模原 248448 ㎥）")
            wr.writerow({
                "assignment_id": f"TRACE_YOK:{key}",
                "key_code": key,
                "facility_id": FACILITY[v["sys"]],
                "share": "1.0",
                "confidence": conf,
                "valid_from": VALID_FROM,
                "valid_to": "",
                "source_doc_id": DOC_ID,
                "note_ja": note,
            })
    return n_by_conf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-only", action="store_true", help="CSV を書かずに数字だけ出す")
    ap.add_argument("--k", type=int, default=4, help="位置合わせの縮小率（既定 1/4）")
    args = ap.parse_args()

    png = render()
    cls, mask, bbox = classify(png)

    if not ZONES.exists():
        sys.exit(f"! {ZONES.relative_to(ROOT)} が無い。先に scripts/c90_estat_shozaiki.py を実行する。")
    fc = json.load(open(ZONES, encoding="utf-8"))
    feats = [f for f in fc["features"]
             if (f["properties"].get("city_name") or "").startswith("横浜市")]
    geoms = [shape(f["geometry"]) for f in feats]
    yok = unary_union(geoms)
    polys = list(yok.geoms) if yok.geom_type == "MultiPolygon" else [yok]
    lon0, lat_min, lon_max, lat1 = yok.bounds
    print(f"  横浜市の町丁目 {len(feats)} 件 / 外形 {len(polys)} 片")

    print("\n位置合わせ")
    # 4 パラメータの解を 6 パラメータの初期値にする。せん断だけを足したときに
    # 本当に良くなるのかを見たいので、両者は同じ谷から出発させる。
    iou4, q4, anchor = align(mask, polys, lon0, lat1, bbox, free_shear=False, k=args.k)
    print(f"  4 パラメータ（拡大・平行移動）  IoU = {iou4:.4f}")
    iou6, q6, _ = align(mask, polys, lon0, lat1, bbox, free_shear=True, k=args.k, p0=q4)
    print(f"  6 パラメータ（＋回転・せん断）  IoU = {iou6:.4f}  "
          f"k1={q6[2]:+.4f} k2={q6[3]:+.4f}")
    p4 = to_canonical(q4, anchor, args.k)
    p6 = to_canonical(q6, anchor, args.k)

    results = {}
    for mode, iou, params in (("4パラメータ", iou4, p4), ("6パラメータ", iou6, p6)):
        traced = sample(cls, params, lon0, lat1, feats)
        rows, agree, disagree, rate = cross_check(traced)
        results[mode] = (iou, params, traced, rows, rate)
        print(f"  {mode}: 色が読めた町丁目 {len(traced)}/{len(feats)}  "
              f"公表文章との一致率 {rate*100:.1f}%")

    # 採否は IoU と一致率の**両方**で決める。IoU だけ上がって一致率が落ちるなら、
    # 外形に合わせにいって中身の割付を壊しているということなので採らない。
    best_mode = "4パラメータ"
    if results["6パラメータ"][0] > results["4パラメータ"][0] + 1e-4 and \
       results["6パラメータ"][4] >= results["4パラメータ"][4] - 1e-9:
        best_mode = "6パラメータ"
    iou, params, traced, wardrows, rate = results[best_mode]
    print(f"\n採用: {best_mode}（IoU {iou:.4f} / 一致率 {rate*100:.1f}%）")
    print("  " + "  ".join(f"{n}={v:.4f}" for n, v in zip(PARAM_NAMES, params)))

    # せん断を入れて区ごとにどう動いたか。全体の一致率が下がっていても、
    # どの区が良くなりどの区が悪くなったかは残しておく（残差の在り処が分かるのはここだけ）。
    h4 = {r["ward"]: r["hit"] for r in results["4パラメータ"][3]}
    h6 = {r["ward"]: r["hit"] for r in results["6パラメータ"][3]}
    print(f"\n{'区':<10}{'4param':>8}{'6param':>8}{'差':>8}")
    for ward in sorted(h4, key=lambda w: (h6.get(w) or 0) - (h4.get(w) or 0)):
        if h4.get(ward) is None or h6.get(ward) is None:
            continue
        print(f"{ward:<10}{h4[ward]*100:7.0f}%{h6[ward]*100:7.0f}%{(h6[ward]-h4[ward])*100:+7.0f}pt")

    pur = np.array([v["purity"] for v in traced.values()])
    print(f"\n読み取り: {len(traced)} / {len(feats)} 町丁目（{len(traced)/len(feats)*100:.1f}%）")
    for t in (0.95, 0.9, 0.8, 0.7, 0.5):
        print(f"  純度 {int(t*100)}% 以上: {(pur >= t).sum():5d}（{(pur >= t).mean()*100:.1f}%）")
    print(f"  純度 50% 未満（行を作らない）: {(pur < PURITY_MIN).sum()}")

    print(f"\n{'区':<10}{'計':>5}  内訳{' '*34}文章との整合")
    for r in wardrows:
        c = "  ".join(f"{k}:{v}" for k, v in r["counts"].items())
        j = "文章なし" if not r["stated"] else \
            f"一致 {r['hit']*100:4.0f}%  企業団系 {r['kgd']*100:3.0f}%"
        print(f"{r['ward']:<10}{r['total']:>5}  {c:<38}{j}")
    print(f"\n公表文章のある区: 一致率 {rate*100:.1f}%")
    tot = collections.Counter(v["sys"] for v in traced.values())
    print("系統別:", "  ".join(f"{k}={tot[k]}" for k in NAMES))

    if args.report_only:
        print("\n--report-only なので CSV は書かない。")
        return 0

    n_by_conf = write_csv(traced, iou, best_mode)
    n = sum(n_by_conf.values())
    print(f"\n{OUT_CSV.relative_to(ROOT)} に {n} 行  "
          f"medium={n_by_conf['medium']} low={n_by_conf['low']}"
          f"  （純度不足で見送り {len(traced)-n}・色が読めず {len(feats)-len(traced)}）")

    register(SID, "横浜市水道局 令和8年度水質検査計画 p11 給水区域図のラスタ読み取り",
             "横浜市水道局", PAGE_URL, "water_supply", "pdf-raster", "csv", LICENSE,
             1, n,
             notes=(f"p11「各水源の主な給水区域」図を {DPI}dpi で画像化し 5 系統の色に分類。"
                    f"e-Stat 町丁目ポリゴンとの位置合わせは{best_mode}アフィンで IoU {iou:.3f}。"
                    f"純度 {PURITY_MEDIUM:.2f} 以上を medium・{PURITY_MIN:.2f} 以上を low とし"
                    f"それ未満は行を作らない。公表文章との一致率 {rate*100:.1f}%。"
                    f"図は西長沢浄水場系と相模原浄水場系を同色で塗っており区別できない。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
