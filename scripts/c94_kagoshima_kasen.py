"""鹿児島県 河川砂防情報システムデータ（BODIK, CC BY 4.0）のうち奄美大島の局を日別に集約して取り込む。

設計: docs/plans/AMAMI_STEP2B.md。

- データセット: 460001_suii（水位）／460001_choui（潮位）／460001_dam（ダム諸量）。年ごとの ZIP（URL に
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
- 集約: 水位は日最高・日最低だけ（危機管理型は通常6時間おきで水位上昇時に間隔が細かくなるので、平均は偏る）。
  潮位は日平均・日最高・日最低。ダムは貯水位（平均・最低）、全流入量・全放流量（平均・最高）、貯水量（平均）、
  貯水率（利水・治水。平均）。空容量は入れない。値は原表記の整数のまま（単位は header の表記）。
- 呼び出しの間は5秒以上空ける（続けて呼ぶと 403 になる）。最新の年の ZIP は月ごとに差し替わるので取り直す。

使い方: python3 scripts/c94_kagoshima_kasen.py [--kind suii choui dam] [--years 2008 2024] [--region jp-46]
出力: data/processed/kagoshima_kasen_{suii,choui,dam}_amami.{csv,jsonl}、kagoshima_kasen_stations_amami.{csv,jsonl}
"""
import sys, re, io, csv, json, zipfile, argparse, pathlib, time, statistics
from collections import defaultdict, Counter

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import regions

BASE = "https://data.bodik.jp"
PKG = {"suii": "460001_suii", "choui": "460001_choui", "dam": "460001_dam"}
PAGE = "https://www.pref.kagoshima.jp/ah08/infra/kasen-sabo/sabo/jyouhoushisutemu.html"
SYS = "https://www3.doboku-bousai.pref.kagoshima.jp/smart/js/datajs"
STATION_JS = {"suii": f"{SYS}/river_info.js", "choui": f"{SYS}/tide_info.js", "dam": f"{SYS}/dam_info.js"}
GSI_REV = "https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress"
SLEEP = 5.0  # BODIK の呼び出しの間（秒）

# 市町村コード -> 名称（regions.py の muni_codes と対応）
MUNI_NAME = {"46222": "奄美市", "46523": "大和村", "46524": "宇検村", "46525": "瀬戸内町", "46527": "龍郷町"}

# 危機管理型水位計（js に座標が無い）。ID: 局名。局名で奄美と確定できる3局だけ（ID は BODIK の列 ID）。
KIKI_AMAMI = {139: "第2屋仁橋", 144: "朝戸橋", 148: "古仁屋橋"}

# 逆ジオコーダが空を返す海上の局（潮位）。局名（旧名瀬市）から市町村を補う。note に必ず書く。
MUNI_FALLBACK = {"名瀬": ("46222", "奄美市")}

MISSING = {"***": "障害・欠測(***)", "---": "休止・該当なし(---)", "": "記録なし(空欄)"}

# 出力する系列: (BODIK の列名, 集約, variable)
# 危機管理型水位計（station_id が suii_kiki_*）と、県の通常の水位局（suii_<ID>。奄美は 181〜187）で variable を分ける
SUII_VARS = [("max", "水位_日最高_cm"), ("min", "水位_日最低_cm")]
SUII_VARS_NORMAL = [("max", "水位_日最高_cm"), ("min", "水位_日最低_cm")]
CHOUI_VARS = [("mean", "潮位_日平均"), ("max", "潮位_日最高"), ("min", "潮位_日最低")]
DAM_COLS = {  # 列名 -> [(集約, variable, unit)]
    "貯水位": [("mean", "貯水位_日平均"), ("min", "貯水位_日最低")],
    "全流入量": [("mean", "全流入量_日平均"), ("max", "全流入量_日最高")],
    "全放流量": [("mean", "全放流量_日平均"), ("max", "全放流量_日最高")],
    "貯水量": [("mean", "貯水量_日平均")],
    "貯水率（利水）": [("mean", "貯水率_利水_日平均")],
    "貯水率（治水）": [("mean", "貯水率_治水_日平均")],
}
# 単位（原表記の整数のまま。決定7）。貯水位の単位は ZIP の単位行の表記をそのまま持つ。
UNIT = {"suii": "cm", "choui": "cm", "全流入量": "10^-3 m3/s", "全放流量": "10^-3 m3/s",
        "貯水位": "cm", "貯水量": "10^3 m3", "貯水率（利水）": "0.1%", "貯水率（治水）": "0.1%"}
AGG = {"mean": lambda v: round(statistics.fmean(v), 3), "max": max, "min": min}


# ---------------------------------------------------------------- 局の表
def parse_station_js(text):
    """river_info.js / tide_info.js / dam_info.js -> [(no, name, lat, lon)]。
    RiverItem は (no,name,river_name,mainland,lat,lon,sites)、他は (no,name,lat,lon)。"""
    out = []
    for m in re.finditer(r"new (River|Tide|Dam)Item\(([^)]*)\)", text):
        kind = m.group(1)
        if kind == "River" and "function" in m.group(0):
            continue
        args = re.findall(r"""["']([^"']*)["']""", m.group(2))
        try:
            if kind == "River":
                no, name, _river, _main, lat, lon = args[:6]
            else:
                no, name, lat, lon = args[:4]
            out.append((int(no), name, float(lat), float(lon)))
        except (ValueError, IndexError):
            continue
    return out


def amami_stations(kind, text, bbox):
    return [s for s in parse_station_js(text) if regions.in_bbox(bbox, s[2], s[3])]


def muni_from_gsi(payload):
    """逆ジオコーダの応答 -> (muniCd, 市町村名)。未知の市町村コードは名称 None。"""
    cd = str((payload.get("results") or {}).get("muniCd") or "")
    return cd, MUNI_NAME.get(cd)


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
    0行目=種別（ダムは局名）、1行目=列 ID、2行目=`観測時刻,局名…`、（ダムのみ3行目=単位）。"""
    lines = text.splitlines()
    label = lines[0].split(",")[0].strip()
    ids = [x.strip() for x in lines[1].split(",")][1:]
    names = [x.strip() for x in lines[2].split(",")][1:]
    start = 3
    units = None
    if has_unit_row:
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


def ts_date(ts):
    n = norm_ts(ts)
    return n[:10].replace("/", "-") if n else None


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


def collect_samples(parsed, wanted, samples, bad, tag):
    """wanted = {列 ID(str): station_id}。samples[(station_id, 日付)] へ値、bad へ種別の件数を足す。
    同じ (局, 時刻) は1度だけ数える（月末の翌月1日 00:00 の行が重なりうる）。"""
    idx = [(i, wanted[c]) for i, c in enumerate(parsed["ids"]) if c in wanted]
    seen = samples.setdefault("__seen__", set())
    midnight = samples.setdefault("__month_start__", set())   # 月初 00:00 の観測（月のファイルの最後の行〔翌月1日 00:00〕）
    for ts, cells in parsed["rows"]:
        d = ts_date(ts)
        if d is None:
            bad[(tag, "時刻の形式不正")] += 1
            continue
        for i, sid in idx:
            cell = cells[i] if i < len(cells) else ""
            v, kind = classify(cell)
            if kind != "ok":
                bad[(sid, kind)] += 1
                continue
            k = (sid, norm_ts(ts))
            if k in seen:
                continue
            seen.add(k)
            samples[(sid, d)].append(v)
            if k[1].endswith("/01 00:00"):
                midnight.add((sid, d, v))


def collect_zip(blob, kind, wanted_suii, wanted_dam, samples, bad, name_warn):
    """1つの年 ZIP から奄美の局のサンプルを集める。列名が期待と違えば name_warn に積む。"""
    z = zipfile.ZipFile(io.BytesIO(blob))
    for raw, name in zip_member_names(z):
        if not name.lower().endswith(".csv"):
            continue
        text = z.read(raw).decode("cp932", errors="replace")
        if kind == "suii":
            kiki = "危機管理型" in name
            parsed = parse_wide_csv(text)
            wanted = {}
            for c, nm in zip(parsed["ids"], parsed["names"]):
                if c.isdigit() and int(c) in wanted_suii.get(kiki, {}):
                    exp_id, exp_name = wanted_suii[kiki][int(c)]
                    wanted[c] = exp_id
                    if nm != exp_name:
                        name_warn.add((exp_id, nm, exp_name))
            collect_samples(parsed, wanted, samples, bad, name)
        elif kind == "choui":
            parsed = parse_wide_csv(text)
            wanted = {}
            for c, nm in zip(parsed["ids"], parsed["names"]):
                if c.isdigit() and int(c) in wanted_suii:
                    exp_id, exp_name = wanted_suii[int(c)]
                    wanted[c] = exp_id
                    if nm != exp_name:
                        name_warn.add((exp_id, nm, exp_name))
            collect_samples(parsed, wanted, samples, bad, name)
        else:
            parsed = parse_wide_csv(text, has_unit_row=True)
            dam_name = parsed["label"]
            if dam_name not in wanted_dam:
                continue
            sid = wanted_dam[dam_name]
            cols = {}
            for c, nm, u in zip(parsed["ids"], parsed["names"], parsed["units"]):
                if nm in DAM_COLS:
                    cols[c] = (f"{sid}|{nm}", u)
                    samples.setdefault("__dam_units__", {})[nm] = u
            collect_samples(parsed, {c: v[0] for c, v in cols.items()}, samples, bad, name)


# ---------------------------------------------------------------- 日別の集約
def daily_rows(samples, kind, sid_base, years, station_names):
    """samples -> 縦持ちの行。years は (開始, 終了) の整数で、範囲外の日付は捨てる。"""
    rows = []
    units = samples.get("__dam_units__", {})
    for key in sorted(k for k in samples if isinstance(k, tuple)):
        sid, d = key
        vals = samples[key]
        if not (years[0] <= int(d[:4]) <= years[1]) or not vals:
            continue
        # その日の観測が月初 00:00 の1行だけ（最終月のファイルの末尾）は部分日。日最高・日最低が意味を持たないので出さない
        if len(vals) == 1 and (sid, d, vals[0]) in samples.get("__month_start__", ()):
            continue
        if kind == "dam":
            station, col = sid.split("|")
            specs = [(a, v, UNIT.get(col) or units.get(col, "")) for a, v in DAM_COLS[col]]
        else:
            station = sid
            vars_ = CHOUI_VARS if kind == "choui" else (SUII_VARS if station.startswith("suii_kiki_") else SUII_VARS_NORMAL)
            specs = [(a, v, UNIT[kind]) for a, v in vars_]
        for agg, var, unit in specs:
            rows.append({
                "station_id": station, "station_name_ja": station_names.get(station, ""),
                "datetime": d, "variable": var, "variable_ja": var,
                "value": AGG[agg](vals), "unit": unit, "n_obs": len(vals),
                "source_id": sid_base, "source_ref": f"{BASE}/dataset/{PKG[kind]}",
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
        for no, name, lat, lon in amami_stations(kind, text, bbox):
            cache = raw / "stations" / f"gsi_{lat:.6f}_{lon:.6f}.json"
            if cache.exists():
                payload = json.loads(cache.read_text())
            else:
                payload = get_json(GSI_REV, params={"lat": lat, "lon": lon})
                cache.write_text(json.dumps(payload, ensure_ascii=False))
            cd, muni = muni_from_gsi(payload)
            note = ""
            if not muni and name in MUNI_FALLBACK:
                cd, muni = MUNI_FALLBACK[name]
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


def main():
    from common import PROC, RAW, get, download, register, write_jsonl
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
              "note": s["note"], "source_id": "kagoshima_kasen_stations_amami", "source_ref": s["source_url"]}
             for s in stations]
    with open(PROC / "kagoshima_kasen_stations_amami.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(srows[0].keys())); w.writeheader(); w.writerows(srows)
    write_jsonl("kagoshima_kasen_stations_amami", srows)
    register("kagoshima_kasen_stations_amami", "鹿児島県 河川砂防情報システム 観測所（奄美大島）",
             "鹿児島県 土木部河川課", PAGE, "水文", "HTTP GET (js)", "CSV/JSONL",
             "CC BY 4.0",
             True, len(srows),
             "局の定義は県の河川砂防情報システム（スマートフォン版）の river_info.js・tide_info.js・dam_info.js。"
             "市町村は国土地理院 逆ジオコーダの市町村コードから決めた。危機管理型水位計の3局は座標なし（needs_review）。")

    sid_base = {k: f"kagoshima_kasen_{k}_amami" for k in PKG}
    for kind in args.kind:
        res = package_resources(kind)
        time.sleep(SLEEP)
        latest = max(res)
        samples, bad, warn = {}, Counter(), set()
        samples = defaultdict(list)
        if kind == "suii":
            wanted = {True: {s["bodik_id"]: (station_id_of(s), s["name"]) for s in stations if s["kind"] == "suii_kiki"},
                      False: {s["bodik_id"]: (station_id_of(s), s["name"]) for s in stations if s["kind"] == "suii"}}
            wanted_dam = None
        elif kind == "choui":
            wanted = {s["bodik_id"]: (station_id_of(s), s["name"]) for s in stations if s["kind"] == "choui"}
            wanted_dam = None
        else:
            wanted = None
            wanted_dam = {s["name"]: station_id_of(s) for s in stations if s["kind"] == "dam"}
            if not wanted_dam:
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
            collect_zip(dest.read_bytes(), kind, wanted, wanted_dam, samples, bad, warn)
            print(f"  {kind} {y}: {dest.name}")
        for w_ in sorted(warn):
            print(f"  [warn] 列名の不一致 {w_}")
        for (s, k), n in sorted(bad.items()):
            print(f"  [missing] {kind} {s} {k}: {n}")
        rows = daily_rows(samples, kind, sid_base[kind], tuple(args.years), names)
        if not rows:
            print(f"  {kind}: 行が取れない"); continue
        name = sid_base[kind]
        with open(PROC / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
        write_jsonl(name, rows)
        ds = sorted({r["datetime"] for r in rows})
        label = {"suii": "水位", "choui": "潮位", "dam": "ダム諸量"}[kind]
        register(name, f"鹿児島県 河川砂防情報システムデータ（{label}・奄美大島・日別）",
                 "鹿児島県 土木部河川課（BODIK）", f"{BASE}/dataset/{PKG[kind]}", "水文",
                 "HTTP GET (CKAN package_show -> ZIP/CSV)", "CSV/JSONL", "CC BY 4.0", True, len(rows),
                 f"10分値等を日別に集約（{ds[0]}〜{ds[-1]}）。水位は日最高・日最低のみ。単位は原表記の整数。"
                 "速報値で検定されていない可能性がある。")


if __name__ == "__main__":
    main()
