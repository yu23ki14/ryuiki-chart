# -*- coding: utf-8 -*-
"""CKAN目録から環境系リソースを選別 → 実データをダウンロードして機械判読CSV化

出力:
  data/processed/ckan_env_selection.csv   選別一覧
  data/raw/ckan/<instance>/<resource_id>.<ext>   生ファイル
  data/processed/ckan_env/<resource_id>__<sheet>.csv  変換後
  data/processed/ckan_env_index.csv / .jsonl      インデックス
"""
import sys, pathlib, re, os, io, zipfile, urllib.parse, traceback, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd

SRC = "ckan_env_bulk"
RAWD = RAW/"ckan"
OUTD = PROC/"ckan_env"
OUTD.mkdir(parents=True, exist_ok=True)
MAX_RESOURCES = int(os.environ.get("MAX_RES", "200"))
MAX_BYTES = 250 * 1024 * 1024

# ---------------------------------------------------------------- 選別
KEYWORDS = [
 "環境","水質","大気","河川","水源","森林","林業","緑地","公園","自然","生物","動物",
 "鳥獣","外来","農地","土地利用","気象","降水","降雨","温暖化","温室効果ガス","排出",
 "地盤","地下水","湧水","海岸","漂着","廃棄物","ごみ","リサイクル","農業","漁業","水産",
 "ダム","貯水","災害","浸水","ハザード","土砂","治水","下水","上水","水道","雨水",
 "植物","昆虫","魚","野鳥","希少","絶滅","保全","生態","流域","湖","沼","海","干潟",
 "騒音","振動","悪臭","ダイオキシン","放射線","放射能","PM2.5","光化学","公害",
 "みどり","樹木","樹林","里山","畜産","作物","収穫","栽培","漁獲","雪","気温","風",
 "土壌","地質","地形","標高","急傾斜","崖","液状化","津波","洪水","内水","避難",
]
GROUP_KEYWORDS = ["環境", "農林水産", "国土・気象"]

HIGH = re.compile(r"水質|大気|温室効果|温暖化|地盤沈下|漂着|森林|林業|農林業センサス|漁業センサス"
                  r"|鳥獣|公園|緑地|気象年報|土地利用|都市計画基礎調査|水源|自然|生物|河川|流域"
                  r"|土砂|浸水|洪水|津波|地下水|湧水|海岸|環境|みどり|里山|樹")
MID  = re.compile(r"廃棄物|ごみ|リサイクル|農業|漁業|水産|農地|畜産|作物|漁獲|土壌|地質|気温|降水")
LOW  = re.compile(r"災害|避難|ハザード|騒音|振動|悪臭|公害|放射|水道|下水")
NOISE= re.compile(r"交通事故統計|人口統計調査|決算財務書類|県民ニーズ調査|市町村要覧|経済センサス"
                  r"|市営住宅|医事|薬事|食品衛生|歯科|通知一覧|職員|給与|予算|入札|指定管理"
                  r"|ランキングかながわ|議会|選挙|補助金|窓口|施設一覧|事業所一覧|住宅|観光"
                  r"|年齢別人口|世帯数|港勢調査|文化施設|保健実態")

EXT_RE = re.compile(r"\.(csv|xlsx|xlsm|xls|zip|pdf|shp|txt|json|geojson)$", re.I)

def url_ext(u):
    p = urllib.parse.urlparse(str(u)).path
    m = EXT_RE.search(p)
    return m.group(1).lower() if m else ""

def norm_format(fmt, url):
    f = (str(fmt) or "").strip().upper()
    if f in ("", "NAN", "NONE"):
        e = url_ext(url)
        f = {"xlsx":"XLSX","xlsm":"XLSX","xls":"XLS","csv":"CSV","zip":"ZIP",
             "pdf":"PDF","txt":"TXT","json":"JSON","geojson":"GEOJSON","shp":"SHP"}.get(e, "")
    return f

def build_selection():
    res = pd.read_csv(PROC/"ckan_resources.csv", dtype=str).fillna("")
    ds  = pd.read_csv(PROC/"ckan_datasets.csv",  dtype=str).fillna("")
    tagmap = dict(zip(ds["dataset_id"], ds["tags"]))
    res["tags"] = res["dataset_id"].map(tagmap).fillna("")
    res["format_norm"] = [norm_format(f, u) for f, u in zip(res["format"], res["url"])]

    rows = []
    for _, r in res.iterrows():
        blob = f'{r["dataset_title"]} {r["resource_name"]} {r["tags"]}'
        kws = [k for k in KEYWORDS if k in blob]
        gk  = [g for g in GROUP_KEYWORDS if g in r["groups"]]
        if not kws and not gk:
            continue
        score = 0
        if HIGH.search(blob): score += 100
        if MID.search(blob):  score += 60
        if LOW.search(blob):  score += 30
        if gk:                score += 40
        if NOISE.search(blob): score -= 130
        score += min(len(kws), 5) * 3
        rows.append({
            "dataset_title": r["dataset_title"], "resource_name": r["resource_name"],
            "format": r["format_norm"], "url": r["url"], "license": r["license"],
            "instance": r["instance"], "dataset_id": r["dataset_id"],
            "resource_id": r["resource_id"], "organization": r["organization"],
            "groups": r["groups"], "tags": r["tags"], "size": r["size"],
            "format_raw_ja": r["format"],
            "matched_keywords_ja": "|".join(sorted(set(kws))),
            "matched_groups_ja": "|".join(gk), "score": score,
        })
    sel = pd.DataFrame(rows).sort_values(["score", "dataset_title"], ascending=[False, True])
    sel.to_csv(PROC/"ckan_env_selection.csv", index=False)
    print(f"[select] {len(sel)} resources -> data/processed/ckan_env_selection.csv")
    print(sel["format"].value_counts().to_string())
    return sel

# ------------------------------------------------- HTML着地ページの1段掘り
# CKAN上は format=HTML の「入口ページ」だが、実データ(Excel)は配下の年度別ページにある
CRAWL = [
 # (index_url, dataset_title, child_url_regex, 年の下限, license, instance, organization)
 ("https://www.pref.kanagawa.jp/docs/b4f/suisitu/sokuteikekkaichiran.html",
  "公共用水域及び地下水の水質測定結果", r"/docs/b4f/suisitu/(\d{4})sokuteikekka", 2010),
 ("https://www.pref.kanagawa.jp/docs/b4f/taikiosen/index.html",
  "神奈川の大気汚染", r"/docs/b4f/taikiosen/(\d{4})taiki", 2014),
 ("https://www.pref.kanagawa.jp/docs/pf7/cnt/f41044/p81475.html",
  "地盤沈下調査結果", None, None),
 ("https://www.pref.kanagawa.jp/docs/ap4/cnt/f417509/shinontaikeikaku.html",
  "神奈川県地球温暖化対策計画の数値目標と進捗状況", None, None),
]
DATA_RE = re.compile(r"\.(xlsx|xlsm|xls|csv)$", re.I)

def page_links(url):
    r = get(url); r.encoding = r.apparent_encoding or "utf-8"
    return [urllib.parse.urljoin(url, l.replace("&amp;", "&"))
            for l in re.findall(r'href="([^"]+)"', r.text)]

def crawl_extra():
    extra, seen = [], set()
    for idx_url, title, child_re, ymin in CRAWL:
        try:
            links = page_links(idx_url)
        except Exception as e:
            print(f"  [crawl-fail] {title}: {e}"); continue
        pages = [idx_url]
        if child_re:
            for l in links:
                m = re.search(child_re, l)
                if not m: continue
                if m.groups() and ymin and int(m.group(1)) < ymin: continue
                if l not in pages: pages.append(l)
        pages = pages[:25]
        n = 0
        for pg in pages:
            try:
                ls = page_links(pg) if pg != idx_url else links
            except Exception as e:
                print(f"    [page-fail] {pg}: {e}"); continue
            for l in ls:
                l = l.split("#")[0]
                if not DATA_RE.search(urllib.parse.urlparse(l).path): continue
                if l in seen: continue
                seen.add(l); n += 1
                rid = "web_" + sha_of(l)
                extra.append({
                    "dataset_title": title,
                    "resource_name": urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(l).path)),
                    "format": norm_format("", l), "url": l,
                    "license": "神奈川県ホームページ利用規約（CC BY 4.0 準拠）",
                    "instance": "kanagawa_pref_web", "dataset_id": "", "resource_id": rid,
                    "organization": "神奈川県", "groups": "環境", "tags": "",
                    "size": "", "format_raw_ja": "", "matched_keywords_ja": "",
                    "matched_groups_ja": "", "score": 999, "parent_page": pg,
                })
        print(f"  [crawl] {title}: pages={len(pages)} files={n}", flush=True)
    return extra

import hashlib
def sha_of(s): return hashlib.sha256(s.encode()).hexdigest()[:24]

# ---------------------------------------------------------------- 変換
def read_csv_bytes(p):
    """CP932/UTF-8/UTF-8-BOM を順に試す。文字化けは許さない。"""
    b = open(p, "rb").read()
    encs = ["utf-8-sig", "utf-8", "cp932", "euc_jp"]
    if b[:3] == b"\xef\xbb\xbf": encs = ["utf-8-sig", "cp932", "utf-8", "euc_jp"]
    last = None
    for e in encs:
        try:
            t = b.decode(e)
        except Exception as ex:
            last = f"{e}: {ex}"; continue
        if "�" in t: last = f"{e}: replacement char"; continue
        return t, e
    raise RuntimeError(f"decode failed ({last})")

def read_ragged(text, sep=","):
    """行ごとに列数が違う行政CSVでも行を捨てない。最大列数に合わせて names を与える。"""
    import csv as _csv
    n = 0
    for row in _csv.reader(io.StringIO(text), delimiter=sep):
        n = max(n, len(row))
    if n == 0: return pd.DataFrame()
    return pd.read_csv(io.StringIO(text), header=None, dtype=str, sep=sep,
                       engine="python", names=list(range(n)), on_bad_lines="skip")

def detect_header(df, scan=40):
    """最初に非空セルが3つ以上『連続』する行。タイトル行を避けるため密度も見る."""
    n = min(scan, len(df))
    counts = []
    for i in range(n):
        vals = ["" if pd.isna(v) else str(v).strip() for v in df.iloc[i].tolist()]
        counts.append(sum(1 for v in vals if v != ""))
    if not counts or max(counts) == 0: return -1
    mx = max(counts)
    for i in range(n):
        vals = ["" if pd.isna(v) else str(v).strip() for v in df.iloc[i].tolist()]
        run = best = 0
        for v in vals:
            run = run + 1 if v != "" else 0
            best = max(best, run)
        if best >= 3 and counts[i] >= max(3, mx * 0.6):
            return i
    return -1

def safe(s):
    # 全角英数字(ＡＺ０９)も残す。落とすと「表１」「表２」が同名になり上書きされる
    s = re.sub(r"[^0-9A-Za-z\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A぀-ヿ一-鿿]+", "_", str(s)).strip("_")
    return (s or "sheet")[:60]

def uniq_out(rid, stem, results):
    """同一リソース内でファイル名が衝突したら連番を付けて上書きを防ぐ"""
    used = {str(r[0]) for r in results}
    out = OUTD/f"{rid}__{stem}.csv"
    k = 2
    while str(out) in used:
        out = OUTD/f"{rid}__{stem}_{k}.csv"; k += 1
    return out

def dump_table(raw_df, out_path):
    """ヘッダ行を検出して整形。検出できなければ header=None のまま出す."""
    hr = detect_header(raw_df)
    if hr < 0:
        raw_df.to_csv(out_path, index=False, header=False, encoding="utf-8-sig")
        return len(raw_df), raw_df.shape[1], -1, True
    hdr = ["" if pd.isna(v) else str(v).strip() for v in raw_df.iloc[hr].tolist()]
    body = raw_df.iloc[hr+1:].reset_index(drop=True)
    cols, seen = [], {}
    blank = 0
    for j, h in enumerate(hdr):
        if h == "":
            h = f"col_{j}"; blank += 1
        if h in seen:
            seen[h] += 1; h = f"{h}_{seen[h]}"
        else:
            seen[h] = 0
        cols.append(h)
    body.columns = cols
    body = body.dropna(how="all").dropna(axis=1, how="all")
    body.to_csv(out_path, index=False, encoding="utf-8-sig")
    needs_human = blank > max(1, len(cols) * 0.3) or len(body) == 0
    return len(body), body.shape[1], hr, needs_human

def convert(path, fmt, rid, results, meta):
    """1リソース -> 1..N の CSV。results に (out_path,n_rows,n_cols,hr,needs_human) を積む."""
    fmt = fmt.upper()
    if fmt in ("CSV", "TXT"):
        t, enc = read_csv_bytes(path)
        sep = "\t" if (fmt == "TXT" or path.suffix.lower() == ".tsv") else ","
        raw = read_ragged(t, sep)
        out = OUTD/f"{rid}.csv"
        results.append((out,) + dump_table(raw, out) + (f"encoding={enc}",))
        return
    if fmt in ("XLSX", "XLS", "XLSM", "XLSK"):
        engine = "xlrd" if fmt == "XLS" else "openpyxl"
        try:
            book = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine=engine)
        except Exception:
            other = "openpyxl" if engine == "xlrd" else "xlrd"
            book = pd.read_excel(path, sheet_name=None, header=None, dtype=str, engine=other)
        if not book: raise RuntimeError("no sheets")
        for sh, raw in book.items():
            if raw.empty: continue
            out = uniq_out(rid, safe(sh), results)
            results.append((out,) + dump_table(raw, out) + (f"sheet={sh}",))
        if not results: raise RuntimeError("all sheets empty")
        return
    if fmt in ("ZIP", "SHP", "SHP,CSV"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            csvs = [n for n in names if n.lower().endswith(".csv")]
            shps = [n for n in names if n.lower().endswith(".shp")]
            xls  = [n for n in names if re.search(r"\.xlsx?$", n, re.I)]
            ex = RAWD/"_unzip"/rid
            for n in csvs + xls:
                z.extract(n, ex)
            for n in csvs:
                p = ex/n
                t, enc = read_csv_bytes(p)
                raw = read_ragged(t, ",")
                out = uniq_out(rid, safe(pathlib.PurePath(n).stem), results)
                results.append((out,) + dump_table(raw, out) + (f"zip:{n} encoding={enc}",))
            for n in xls:
                p = ex/n
                eng = "xlrd" if n.lower().endswith(".xls") else "openpyxl"
                try: book = pd.read_excel(p, sheet_name=None, header=None, dtype=str, engine=eng)
                except Exception: book = pd.read_excel(p, sheet_name=None, header=None, dtype=str)
                for sh, raw in book.items():
                    if raw.empty: continue
                    out = uniq_out(rid, f"{safe(pathlib.PurePath(n).stem)}__{safe(sh)}", results)
                    results.append((out,) + dump_table(raw, out) + (f"zip:{n} sheet={sh}",))
            for n in shps:
                base = n[:-4]
                need = [base+e for e in (".shp", ".dbf", ".shx")]
                if not all(x in names for x in need[:2]): continue
                for e in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
                    if base+e in names: z.extract(base+e, ex)
                import shapefile
                enc_used = None
                for enc in ("cp932", "utf-8"):
                    try:
                        r = shapefile.Reader(str(ex/(base)), encoding=enc)
                        flds = [f[0] for f in r.fields[1:]]
                        _ = r.record(0) if len(r) else None
                        enc_used = enc; break
                    except Exception:
                        continue
                if enc_used is None: raise RuntimeError(f"shapefile decode failed: {n}")
                recs = []
                for sr in r.iterShapeRecords():
                    d = dict(zip(flds, list(sr.record)))
                    try:
                        bb = sr.shape.bbox
                        d["_bbox_minx"], d["_bbox_miny"] = bb[0], bb[1]
                        d["_bbox_maxx"], d["_bbox_maxy"] = bb[2], bb[3]
                        d["_centroid_x"] = (bb[0]+bb[2])/2; d["_centroid_y"] = (bb[1]+bb[3])/2
                    except Exception: pass
                    recs.append(d)
                df = pd.DataFrame(recs)
                # 同一 zip 内に同名の .csv があると衝突するので __shp を付ける
                out = uniq_out(rid, f"{safe(pathlib.PurePath(n).stem)}__shp", results)
                df.to_csv(out, index=False, encoding="utf-8-sig")
                results.append((out, len(df), df.shape[1], 0, False,
                                f"shapefile:{n} dbf_encoding={enc_used} (geometry除外/bbox付与)"))
            if not results:
                raise RuntimeError(f"zip に表データなし: {names[:8]}")
        return
    raise RuntimeError(f"未対応フォーマット: {fmt}")

# ---------------------------------------------------------------- main
DL_FMT = {"CSV", "XLSX", "XLS", "XLSM", "XLSK", "SHP", "SHP,CSV", "ZIP", "TXT"}
DL_CAP = 120 * 1024 * 1024   # 1ファイル上限。超過分は諦めて次へ

def download_capped(url, dest, cap=DL_CAP):
    """common.get(stream=True) を使い、cap を超えたら中断して記録に残す"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    r = get(url, stream=True)
    n = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            n += len(chunk)
            if n > cap:
                f.close(); tmp.unlink(missing_ok=True)
                raise RuntimeError(f"サイズ超過: >{cap} bytes")
            f.write(chunk)
    tmp.rename(dest)
    return dest
BAD_LICENSE = re.compile(r"再配布不可|要申請|転載禁止|複製禁止")

def main():
    sel = build_selection()
    extra = crawl_extra()
    ex_df = pd.DataFrame(extra)

    cand = sel[sel["format"].isin(DL_FMT) & (sel["score"] > 0)].copy()
    # ZIP は SHP,CSV 由来のもの(=GISデータ)のみ拾う
    cand["_sz"] = pd.to_numeric(cand["size"], errors="coerce").fillna(0)
    cand = cand.sort_values(["score", "_sz"], ascending=[False, True])
    cand = cand.head(max(0, MAX_RESOURCES))
    todo = pd.concat([ex_df, cand], ignore_index=True) if len(ex_df) else cand
    print(f"[plan] crawl={len(ex_df)} ckan={len(cand)} total={len(todo)}")

    index = []
    for i, r in todo.reset_index(drop=True).iterrows():
        rid, fmt, url = r["resource_id"], (r["format"] or "").upper(), r["url"]
        base = {"resource_id": rid, "dataset_title": r["dataset_title"],
                "resource_name": r["resource_name"], "format": fmt,
                "source_url": url, "license": r["license"],
                "instance": r["instance"], "source_id": SRC, "source_ref": url,
                "output_path": "", "n_rows": None, "n_cols": None,
                "header_row_detected": None, "needs_human": False, "error": "", "note": ""}
        if BAD_LICENSE.search(str(r["license"])):
            base["error"] = f"再配布不可/要申請のためダウンロードせず: {r['license']}"
            index.append(base); continue
        try:
            sz = float(r.get("size") or 0)
        except Exception:
            sz = 0
        if sz and sz > MAX_BYTES:
            base["error"] = f"サイズ超過({int(sz)} bytes > {MAX_BYTES})のためスキップ"
            index.append(base); continue
        ext = url_ext(url) or {"XLSX":"xlsx","XLS":"xls","CSV":"csv","ZIP":"zip",
                               "SHP,CSV":"zip","SHP":"zip","TXT":"txt"}.get(fmt, "bin")
        dest = RAWD/str(r["instance"])/f"{rid}.{ext}"
        try:
            download_capped(url, dest)
        except Exception as e:
            base["error"] = f"download失敗: {e}"[:300]
            index.append(base); print(f"  [{i+1}/{len(todo)}] DL-FAIL {rid} {e}"); continue
        if dest.stat().st_size == 0:
            base["error"] = "download結果が0バイト"; index.append(base); continue
        # 拡張子と中身の不一致を吸収
        head = open(dest, "rb").read(8)
        real = fmt
        if head[:2] == b"PK": real = "XLSX" if fmt in ("XLS","XLSX","XLSM","XLSK") else fmt
        elif head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": real = "XLS"
        elif head[:5] in (b"<html", b"<!DOC") and fmt not in ("CSV","TXT"):
            base["error"] = "実体がHTML（ファイルではない）"; index.append(base); continue
        results = []
        try:
            convert(dest, real, rid, results, base)
        except Exception as e:
            base["error"] = f"変換失敗({real}): {e}"[:300]
            index.append(base); print(f"  [{i+1}/{len(todo)}] CONV-FAIL {rid} {e}"); continue
        for out, nr, nc, hr, nh, note in results:
            row = dict(base)
            row.update({"output_path": str(out.relative_to(ROOT)), "n_rows": nr,
                        "n_cols": nc, "header_row_detected": hr,
                        "needs_human": bool(nh), "note": note})
            index.append(row)
        if (i+1) % 10 == 0: print(f"  [{i+1}/{len(todo)}] ok ({len(index)} index rows)", flush=True)

    # 優先度の高いテーマだが PDF/HTML しか無い = 本バッチの対象外、を記録に残す
    PRI = re.compile(r"水質|大気|温室効果|温暖化|地盤沈下|漂着|森林|林業|鳥獣|水源|自然環境"
                     r"|河川|流域|土砂|浸水|洪水|津波|地下水|湧水|海岸|海況|農業技術|水産技術")
    done = {r["resource_id"] for r in index}
    for _, r in sel.iterrows():
        if r["resource_id"] in done: continue
        if r["format"] in DL_FMT: continue
        if not PRI.search(f'{r["dataset_title"]} {r["resource_name"]}'): continue
        index.append({"resource_id": r["resource_id"], "dataset_title": r["dataset_title"],
                      "resource_name": r["resource_name"], "format": r["format"],
                      "source_url": r["url"], "license": r["license"], "instance": r["instance"],
                      "source_id": SRC, "source_ref": r["url"], "output_path": "",
                      "n_rows": None, "n_cols": None, "header_row_detected": None,
                      "needs_human": True,
                      "error": f'未処理: format={r["format"] or "(不明)"} は本バッチの対象外（CSV/XLSX/XLS/SHP のみ変換）',
                      "note": "優先テーマだが機械判読形式なし。PDF抽出またはページ掘り下げが必要"})

    idx = pd.DataFrame(index)
    cols = ["resource_id","dataset_title","resource_name","format","source_url","license",
            "output_path","n_rows","n_cols","header_row_detected","needs_human","error",
            "note","instance","source_id","source_ref"]
    idx = idx[cols]
    idx.to_csv(PROC/"ckan_env_index.csv", index=False)
    write_jsonl("ckan_env_index", idx.where(pd.notna(idx), None).to_dict("records"))

    ok = idx[(idx["error"] == "") & (idx["output_path"] != "")]
    print(f"\n[done] index rows={len(idx)} converted_files={len(ok)} "
          f"failed_resources={idx[idx['error']!=''].shape[0]} "
          f"needs_human={int(ok['needs_human'].sum())}")
    register(SRC, "CKAN 環境系リソース一括CSV化（神奈川県/相模原市）",
             "神奈川県・相模原市", "https://catalog.opendata.pref.kanagawa.jp",
             "環境・生物多様性・水・森林・土地利用・災害", "CKAN目録+HTTP取得",
             "CSV", "CC BY 4.0 / CC BY-NC 4.0（データセット個別）", 1, int(len(ok)),
             f"選別{len(sel)}件中 {len(todo)}リソースを処理。変換成功ファイル{len(ok)}、"
             f"要人手確認{int(ok['needs_human'].sum())}。index: data/processed/ckan_env_index.csv")
    return idx

if __name__ == "__main__":
    main()
