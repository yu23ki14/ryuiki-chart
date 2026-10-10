"""鹿児島県 河川砂防情報システムデータ（BODIK, CC BY 4.0）のうち奄美大島の局を日別に集約して取り込む。

設計: docs/plans/AMAMI_STEP2B.md。

- データセット: 460001_suii（水位。通常と危機管理型）／460001_choui（潮位）／460001_dam（ダム諸量）。年ごとの ZIP（URL に
  リソースの UUID が入るので毎回 package_show で引く）。ZIP の中は月ごとの CSV（CP932、ZIP 内のファイル名も
  CP932 だが UTF-8 フラグが無いので cp437 -> cp932 で戻す）、横持ち（ヘッダ3行、ダムは単位の4行目あり）。
- 局の表: 県の河川砂防情報システム（スマートフォン版）が地図に載せる観測所の定義 js
  （river_info.js・tide_info.js・dam_info.js。名称と緯度経度を持つ）から、regions.py の bbox に入る局を取る。
  所在（市町村）は国土地理院の逆ジオコーダ（LonLatToAddress）の市町村コードから決める。
  js の no は BODIK の列の ID と一致する（ZIP の中で名称も照合して確かめる）。ダムは js の no と BODIK の
  ID が別物なので、station_id は js の no を使う。
- 座標を持たない局（危機管理型水位計。js に無い）は、名称で奄美と確定できる局だけ KIKI_AMAMI に固定で持ち、
  座標・市町村は空のまま needs_review にする。
- 欠測などの記号: `***`=障害・欠測、`---`=休止・該当なし、空欄=記録なし。負の値は実在しうるので捨てない。
  数値にならない値は種類ごとに件数を数えて表示する（黙って捨てない）。
- 日の境界: 月ファイルの時刻は 00:10〜翌月1日 00:00 の 10 分刻み。00:00 の値は「その日の始まり」ではなく
  前日の 24:00（直前の 10 分間を締める観測）と読むのが自然なので、前日に入れる。これで月末日も 24 時間分そろい、
  最新の月ファイルの末尾（翌月1日 00:00 だけの日）が部分日として残らない。
- 出典は4つ: 水位（通常。suii_<ID>）／水位（危機管理型。suii_kiki_<ID>）／潮位／ダム。水位2つは同じ ZIP から出す。
  観測の性質が違う（危機管理型は観測間隔が水位で変わる）ので、出典を分けて注記を危機管理型だけに付ける。
- 集約: 水位は日最高・日最低だけ（危機管理型は通常6時間おきで水位上昇時に間隔が細かくなるので、平均は偏る）。
  潮位は日平均・日最高・日最低。ダムは貯水位（平均・最低）、全流入量・全放流量（平均・最高）、貯水量（平均）、
  貯水率（利水・治水。平均）。空容量は入れない。値は原表記の整数のまま（単位は header の表記）。
- 呼び出しの間は5秒以上空ける（続けて呼ぶと 403 になる）。最新の年の ZIP は月ごとに差し替わるので取り直す。

使い方: python3 scripts/c94_kagoshima_kasen.py [--kind suii choui dam] [--years 2008 2024] [--region jp-46]
出力: data/processed/kagoshima_kasen_{suii,suii_kiki,choui,dam}_amami.{csv,jsonl}、kagoshima_kasen_stations_amami.{csv,jsonl}
"""
import argparse
import csv
import datetime
import json
import re
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import regions

BASE = "https://data.bodik.jp"
PKG = {"suii": "460001_suii", "choui": "460001_choui", "dam": "460001_dam"}   # --kind（取得するデータセット）
PAGE = "https://www.pref.kagoshima.jp/ah08/infra/kasen-sabo/sabo/jyouhoushisutemu.html"
SYS = "https://www3.doboku-bousai.pref.kagoshima.jp/smart/js/datajs"
STATION_JS = {"suii": f"{SYS}/river_info.js", "choui": f"{SYS}/tide_info.js", "dam": f"{SYS}/dam_info.js"}
GSI_REV = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
STATIONS_LICENSE = "県サイトから局名・座標の事実を抽出（ライセンス表記なし）／市町村は国土地理院の逆ジオコーダ"
SLEEP = 5.0  # BODIK の呼び出しの間（秒）
STATIONS_SOURCE = "kagoshima_kasen_stations_amami"

# 市町村コード -> 名称。コードの集合は regions.py の jp-46 の muni_codes（muni_from_gsi が照合する）
MUNI_NAME = {"46222": "奄美市", "46523": "大和村", "46524": "宇検村", "46525": "瀬戸内町", "46527": "龍郷町"}

# 危機管理型水位計（js に座標が無い）。ID: 局名。局名で奄美と確定できる3局だけ（ID は BODIK の列 ID）。
KIKI_AMAMI = {139: "第2屋仁橋", 144: "朝戸橋", 148: "古仁屋橋"}

# 逆ジオコーダが空を返す海上の局（潮位）。局名（旧名瀬市）から市町村を補う。note に必ず書く。
MISSING_MUNI_FALLBACK = {"名瀬": ("46222", "奄美市")}

MISSING = {"***": "障害・欠測(***)", "---": "休止・該当なし(---)", "": "記録なし(空欄)"}

# 出力する系列: (集約, variable)。水位は通常も危機管理型も同じ量（河川の水位、cm）なので variable は同じで、
# 種類の違いは出典（source_id）と station_id で表す。
SUII_VARS = [("max", "水位_日最高_cm"), ("min", "水位_日最低_cm")]
CHOUI_VARS = [("mean", "潮位_日平均"), ("max", "潮位_日最高"), ("min", "潮位_日最低")]
DAM_COLS = {  # ZIP の列名 -> [(集約, variable)]。ここに無い列（空容量）は入れない
    "貯水位": [("mean", "貯水位_日平均"), ("min", "貯水位_日最低")],
    "全流入量": [("mean", "全流入量_日平均"), ("max", "全流入量_日最高")],
    "全放流量": [("mean", "全放流量_日平均"), ("max", "全放流量_日最高")],
    "貯水量": [("mean", "貯水量_日平均")],
    "貯水率（利水）": [("mean", "貯水率_利水_日平均")],
    "貯水率（治水）": [("mean", "貯水率_治水_日平均")],
}
# 出力の単位（原表記の整数のまま。決定7）。ダムの列は ZIP の単位行がこの下の DAM_ZIP_UNIT と一致することを確かめる。
UNIT = {"suii": "cm", "choui": "cm", "全流入量": "10^-3 m3/s", "全放流量": "10^-3 m3/s",
        "貯水位": "cm", "貯水量": "10^3 m3", "貯水率（利水）": "0.1%", "貯水率（治水）": "0.1%"}
# ZIP の単位行の期待値（正規化後。_norm_unit）。貯水位は [EL.10^2m]（値 3712 = EL 37.12 m = 3712 cm）。
DAM_ZIP_UNIT = {"貯水位": "EL.10^2m", "全流入量": "10^-3m3/s", "全放流量": "10^-3m3/s", "貯水量": "10^3m3",
                "貯水率（利水）": "10^-1%", "貯水率（治水）": "10^-1%"}
AGG = {"mean": lambda v: round(statistics.fmean(v), 3), "max": max, "min": min}

SERIES_SUFFIX = ("suii_kiki_", "suii_", "choui_", "dam_")   # station_id の接頭辞（長い順）-> 出典名の種別


def series_kind(station_id):
    """station_id -> 出典の種別（suii・suii_kiki・choui・dam）。"""
    for pre in SERIES_SUFFIX:
        if station_id.startswith(pre):
            return pre.rstrip("_")
    raise ValueError(station_id)


def source_of(station_id):
    return f"kagoshima_kasen_{series_kind(station_id)}_amami"


# ---------------------------------------------------------------- 局の表
def parse_station_js(text):
    """river_info.js / tide_info.js / dam_info.js -> [(no, name, lat, lon)]。
    RiverItem は (no,name,river_name,mainland,lat,lon,sites)、他は (no,name,lat,lon)。"""
    out = []
    for m in re.finditer(r"new (River|Tide|Dam)Item\(([^)]*)\)", text):
        args = re.findall(r"""["']([^"']*)["']""", m.group(2))
        try:
            if m.group(1) == "River":
                no, name, _river, _main, lat, lon = args[:6]
            else:
                no, name, lat, lon = args[:4]
            out.append((int(no), name, float(lat), float(lon)))
        except (ValueError, IndexError):
            continue
    return out


def amami_stations(text, bbox):
    return [s for s in parse_station_js(text) if regions.in_bbox(bbox, s[2], s[3])]


def muni_from_gsi(payload):
    """逆ジオコーダの応答 -> (muniCd, 市町村名)。regions の muni_codes に無いコードは名称 None。"""
    cd = str((payload.get("results") or {}).get("muniCd") or "")
    ok = cd in regions.get("jp-46")["muni_codes"]
    return cd, (MUNI_NAME.get(cd) if ok else None)


# ---------------------------------------------------------------- ZIP の解析
def zip_member_names(z):
    """(ZIP 内の名前, 正しい名前)。UTF-8 フラグ（0x800）の無いメンバー名は cp437 として読まれているので
    cp932 に戻す。フラグのあるメンバー（年によって混在する）はそのまま。"""
    out = []
    for zi in z.infolist():
        n = zi.filename
        out.append((n, n if zi.flag_bits & 0x800 else n.encode("cp437").decode("cp932")))
    return out


def parse_wide_csv(text, has_unit_row=False):
    """横持ちの月 CSV -> dict(label, ids, names, units, rows)。rows は (timestamp文字列, [セル…])。
    0行目=種別（ダムは局名）、1行目=列 ID、2行目=`観測時刻,局名…`、（ダムのみ3行目=単位。**2018年までのファイルには
    単位行が無い**ので、3行目の先頭セルが空のときだけ単位行とみなす〔空でなければ最初の観測行〕。units は無ければ None）。"""
    lines = text.splitlines()
    label = lines[0].split(",")[0].strip()
    ids = [x.strip() for x in lines[1].split(",")][1:]
    names = [x.strip() for x in lines[2].split(",")][1:]
    start = 3
    units = None
    if has_unit_row and lines[3].split(",")[0].strip() == "":
        units = [x.strip() for x in lines[3].split(",")][1:]
        start = 4
    rows = []
    for ln in lines[start:]:
        if not ln.strip():
            continue
        p = ln.split(",")
        rows.append((p[0].strip(), [x.strip() for x in p[1:]]))
    return {"label": label, "ids": ids, "names": names, "units": units, "rows": rows}


TS_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{2})$")


def norm_ts(ts):
    """`2025/3/1 0:10`（年によってゼロ埋め無し）も `2025/03/01 00:10` も同じ形にそろえる。不正なら None。"""
    m = TS_RE.match(ts)
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return f"{y:04d}/{mo:02d}/{d:02d} {h:02d}:{mi:02d}"


def obs_date(ts):
    """時刻 -> 日付（YYYY-MM-DD）。00:00 は前日の 24:00 として前日に入れる（モジュール docstring「日の境界」）。
    不正な時刻（形式違い・存在しない日付）は None。"""
    n = norm_ts(ts)
    if n is None:
        return None
    try:
        dt = datetime.datetime.strptime(n, "%Y/%m/%d %H:%M")
    except ValueError:
        return None
    if (dt.hour, dt.minute) == (0, 0):
        dt -= datetime.timedelta(days=1)
    return dt.date().isoformat()


def decode_text(b):
    """県サイトの js は UTF-8（BOM 付き）、BODIK の CSV は CP932。念のため両方を試す。"""
    try:
        return b.decode("utf-8-sig")
    except UnicodeDecodeError:
        return b.decode("cp932", errors="replace")


def classify(cell):
    """セル -> (float | None, 種別)。種別は 'ok' か欠測記号の説明か 'other:<原文>'。"""
    if cell in MISSING:
        return None, MISSING[cell]
    try:
        return float(cell), "ok"
    except ValueError:
        return None, f"other:{cell}"


@dataclass
class Acc:
    """集めたサンプル。vals のキーは (station_id, 列名, 日付)（水位・潮位の列名は ""、ダムは ZIP の列名）。"""
    vals: dict = field(default_factory=lambda: defaultdict(list))
    seen: set = field(default_factory=set)            # 同じ (局, 列, 時刻) は1度だけ数える（月境界の行が重なりうる）
    bad: Counter = field(default_factory=Counter)     # (局, 種別) -> 件数。欠測記号・数値にならない値
    mismatch: Counter = field(default_factory=Counter)   # (局, BODIK の列の局名) -> ファイル数。局の表の名前と違う列は取り込まない
    unchecked_units: int = 0                             # 単位行が無い・空欄でダムの列の単位を照合できなかった数（食い違いではない）


def collect_samples(parsed, cols, acc, tag):
    """cols = {列 ID(str): (station_id, 列名)}。"""
    idx = [(i, cols[c]) for i, c in enumerate(parsed["ids"]) if c in cols]
    for ts, cells in parsed["rows"]:
        d = obs_date(ts)
        if d is None:
            acc.bad[(tag, "時刻の形式不正")] += 1
            continue
        for i, (sid, col) in idx:
            v, kind = classify(cells[i] if i < len(cells) else "")
            if kind != "ok":
                acc.bad[(sid, kind)] += 1
                continue
            k = (sid, col, norm_ts(ts))
            if k in acc.seen:
                continue
            acc.seen.add(k)
            acc.vals[(sid, col, d)].append(v)


def _pick_by_id(parsed, table, acc):
    """列 ID が table（{BODIK の ID: (station_id, 局名)}）にあり、局名も一致する列だけ取る。名前が違う列は取り込まず数える。"""
    cols = {}
    for c, nm in zip(parsed["ids"], parsed["names"]):
        if c.isdigit() and int(c) in table:
            sid, exp_name = table[int(c)]
            if nm != exp_name:
                acc.mismatch[(sid, nm)] += 1
                continue
            cols[c] = (sid, "")
    return cols


def _norm_unit(u):
    """ZIP の単位行 `[10＾-3m3/s]` -> `10^-3m3/s`（括弧・空白を除き、全角の ＾ を ^ に）。"""
    return re.sub(r"[\[\]［］\s]", "", u).replace("＾", "^")


def collect_zip(src, kind, wanted, acc):
    """1つの年 ZIP（パスまたはファイルオブジェクト）から奄美の局のサンプルを集める。
    wanted: suii={True(危機管理型): {ID: (station_id, 局名)}, False: {…}}／choui={ID: (station_id, 局名)}／dam={ダム名: station_id}。
    ダムの単位行が DAM_ZIP_UNIT と違えば ValueError（どのメンバー・列かを示す）。"""
    with zipfile.ZipFile(src) as z:
        for raw, name in zip_member_names(z):
            if not name.lower().endswith(".csv"):
                continue
            text = z.read(raw).decode("cp932", errors="replace")
            if kind == "suii":
                parsed = parse_wide_csv(text)
                cols = _pick_by_id(parsed, wanted["危機管理型" in name], acc)
            elif kind == "choui":
                parsed = parse_wide_csv(text)
                cols = _pick_by_id(parsed, wanted, acc)
            else:
                parsed = parse_wide_csv(text, has_unit_row=True)
                if parsed["label"] not in wanted:
                    continue
                sid = wanted[parsed["label"]]
                cols = {}
                for c, nm, u in zip(parsed["ids"], parsed["names"], parsed["units"] or [""] * len(parsed["ids"])):
                    if nm in DAM_COLS:
                        acc.unchecked_units += not u   # 単位行が無い・空欄: 照合できない（食い違いではない）
                        if u and _norm_unit(u) != DAM_ZIP_UNIT[nm]:
                            raise ValueError(f"{name}: {parsed['label']} の列 {nm!r} の単位 {u!r} が期待 "
                                             f"{DAM_ZIP_UNIT[nm]!r} と違う（単位が変わった。UNIT を見直す）")
                        cols[c] = (sid, nm)
            collect_samples(parsed, cols, acc, name)


# ---------------------------------------------------------------- 日別の集約
def daily_rows(acc, years, station_names):
    """Acc -> 縦持ちの行（source_id は局の種別から決める）。years は (開始, 終了) の整数で、範囲外の日付は捨てる。"""
    rows = []
    for (sid, col, d) in sorted(acc.vals):
        vals = acc.vals[(sid, col, d)]
        if not (years[0] <= int(d[:4]) <= years[1]) or not vals:
            continue
        kind = series_kind(sid)
        if kind == "dam":
            specs = [(a, v, UNIT[col]) for a, v in DAM_COLS[col]]
        else:
            specs = [(a, v, UNIT["choui" if kind == "choui" else "suii"])
                     for a, v in (CHOUI_VARS if kind == "choui" else SUII_VARS)]
        for agg, var, unit in specs:
            rows.append({
                "station_id": sid, "station_name_ja": station_names.get(sid, ""),
                "datetime": d, "variable": var, "variable_ja": var,
                "value": AGG[agg](vals), "unit": unit, "n_obs": len(vals),
                "source_id": source_of(sid), "source_ref": f"{BASE}/dataset/{PKG['suii' if kind == 'suii_kiki' else kind]}",
            })
    return rows


# ---------------------------------------------------------------- 取得・出力
def package_resources(kind):
    from common import get_json
    j = get_json(f"{BASE}/api/3/action/package_show", params={"id": PKG[kind]})
    out = {}
    for r in j["result"]["resources"]:
        m = re.search(r"/download/(?:suii|choui|dam)(\d{4})_[^/]*\.zip$", r.get("url") or "")
        if m:
            out[int(m.group(1))] = r["url"]
    return out


def fetch_station_tables(rid, raw):
    """県サイトの局の定義 js を取り、bbox に入る局の表を作る。戻り値は stations(list of dict)。"""
    from common import get, get_json
    bbox = regions.get(rid)["bbox"]
    rows = []
    for kind, url in STATION_JS.items():
        r = get(url)
        text = decode_text(r.content)
        (raw / "stations").mkdir(parents=True, exist_ok=True)
        (raw / "stations" / url.rsplit("/", 1)[1]).write_bytes(r.content)
        time.sleep(SLEEP)
        for no, name, lat, lon in amami_stations(text, bbox):
            cache = raw / "stations" / f"gsi_{lat:.6f}_{lon:.6f}.json"
            if cache.exists():
                payload = json.loads(cache.read_text())
            else:
                payload = get_json(GSI_REV, params={"lat": lat, "lon": lon})
                cache.write_text(json.dumps(payload, ensure_ascii=False))
            cd, muni = muni_from_gsi(payload)
            note = ""
            if not muni and name in MISSING_MUNI_FALLBACK:
                cd, muni = MISSING_MUNI_FALLBACK[name]
                note = "逆ジオコーダが空（海上）。市町村は局名（名瀬）から補った"
            rows.append({"kind": kind, "bodik_id": no, "name": name, "municipality": muni or "",
                         "muni_code": cd, "lat": lat, "lon": lon,
                         "source_url": url, "note": note})
    for i, nm in KIKI_AMAMI.items():
        rows.append({"kind": "suii_kiki", "bodik_id": i, "name": nm, "municipality": "", "muni_code": "",
                     "lat": "", "lon": "", "source_url": f"{BASE}/dataset/{PKG['suii']}",
                     "note": "needs_review: 座標・所在は公開ページに無い。局名で奄美と確定"})
    return rows


def station_id_of(row):
    return f"{row['kind']}_{row['bodik_id']}"


LABEL = {"suii": "水位（通常）", "suii_kiki": "水位（危機管理型）", "choui": "潮位", "dam": "ダム諸量"}


def main():
    from common import PROC, RAW, download, register, write_jsonl
    ap = argparse.ArgumentParser(); regions.add_region_arg(ap)
    ap.add_argument("--kind", nargs="+", choices=list(PKG), default=list(PKG))
    ap.add_argument("--years", nargs=2, type=int, metavar=("FROM", "TO"), default=[2007, 2100])
    args = ap.parse_args()
    rid = args.region
    if rid != "jp-46":
        print(f"  {rid}: 鹿児島県の河川砂防情報システムは jp-46 のみ。何もしない"); return
    raw = RAW / "kagoshima_kasen"
    stations = fetch_station_tables(rid, raw)
    names = {station_id_of(s): s["name"] for s in stations}
    srows = [{"station_id": station_id_of(s), "station_name_ja": s["name"], "kind": s["kind"],
              "bodik_id": s["bodik_id"], "municipality": s["municipality"], "muni_code": s["muni_code"],
              "lat": None if s["lat"] == "" else s["lat"], "lon": None if s["lon"] == "" else s["lon"],
              "note": s["note"], "source_id": STATIONS_SOURCE, "source_ref": s["source_url"]}
             for s in stations]
    with open(PROC / f"{STATIONS_SOURCE}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(srows[0].keys())); w.writeheader(); w.writerows(srows)
    write_jsonl(STATIONS_SOURCE, srows)
    register(STATIONS_SOURCE, "鹿児島県 河川砂防情報システム 観測所（奄美大島）",
             "鹿児島県 土木部河川課", PAGE, "水文", "HTTP GET (js)", "CSV/JSONL",
             STATIONS_LICENSE, True, len(srows),
             "局の定義は県の河川砂防情報システム（スマートフォン版）の river_info.js・tide_info.js・dam_info.js から"
             "局名・座標の事実を抽出した（ライセンス表記なし）。市町村は国土地理院 逆ジオコーダの市町村コードから決めた。"
             "危機管理型水位計の3局は座標なし（needs_review）。")

    for kind in args.kind:
        res = package_resources(kind)
        time.sleep(SLEEP)
        latest = max(res)
        acc = Acc()
        if kind == "suii":
            wanted = {k: {s["bodik_id"]: (station_id_of(s), s["name"]) for s in stations if s["kind"] == kk}
                      for k, kk in ((True, "suii_kiki"), (False, "suii"))}
        elif kind == "choui":
            wanted = {s["bodik_id"]: (station_id_of(s), s["name"]) for s in stations if s["kind"] == "choui"}
        else:
            wanted = {s["name"]: station_id_of(s) for s in stations if s["kind"] == "dam"}
            if not wanted:
                print("  dam: 奄美のダムが確認できない。出力しない"); continue
        for y in sorted(res):
            if not (args.years[0] <= y <= args.years[1]) and not (args.years[0] <= y + 1 <= args.years[1]):
                continue
            dest = raw / kind / res[y].rsplit("/", 1)[1]
            if y == latest and dest.exists():
                dest.unlink()  # 最新の年は月ごとに差し替わる
            fresh = not dest.exists()
            download(res[y], dest)
            if fresh:
                time.sleep(SLEEP)
            collect_zip(dest, kind, wanted, acc)
            print(f"  {kind} {y}: {dest.name}")
        report(acc, kind)
        write_outputs(daily_rows(acc, tuple(args.years), names), kind, PROC, write_jsonl, register)


def report(acc, kind):
    if acc.unchecked_units:
        print(f"  [unit] {kind}: 単位行が無い・空欄で照合できなかった列が {acc.unchecked_units} 個（2018年までのファイル等。食い違いではない）")
    for (s, k), n in sorted(acc.bad.items()):
        print(f"  [missing] {kind} {s} {k}: {n}")
    for (sid, nm), n in sorted(acc.mismatch.items()):
        print(f"  [name-mismatch] {sid}: BODIK の列の局名 {nm!r} が局の表と違うので取り込まない（{n} ファイル）")


def write_outputs(rows, kind, proc, write_jsonl, register):
    """出典（source_id）ごとにファイルへ書いて register する。水位は通常と危機管理型の2出典に分かれる。"""
    by_src = defaultdict(list)
    for r in rows:
        by_src[r["source_id"]].append(r)
    if not by_src:
        print(f"  {kind}: 行が取れない"); return
    for name, rs in sorted(by_src.items()):
        with open(proc / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(rs[0].keys())); w.writeheader(); w.writerows(rs)
        write_jsonl(name, rs)
        ds = sorted({r["datetime"] for r in rs})
        label = LABEL[series_kind(rs[0]["station_id"])]
        register(name, f"鹿児島県 河川砂防情報システムデータ（{label}・奄美大島・日別）",
                 "鹿児島県 土木部河川課（BODIK）", f"{BASE}/dataset/{PKG[kind]}", "水文",
                 "HTTP GET (CKAN package_show -> ZIP/CSV)", "CSV/JSONL", "CC BY 4.0", True, len(rs),
                 f"10分値等を日別に集約（{ds[0]}〜{ds[-1]}。00:00 は前日の 24:00 として前日に入れる）。"
                 "水位は日最高・日最低のみ。単位は原表記の整数。速報値で検定されていない可能性がある。")


if __name__ == "__main__":
    main()
