# -*- coding: utf-8 -*-
"""c02_ckan_env の変換失敗のうち、原因が特定できたものだけ再変換して index を更新する
 - shapefile の dbf 文字コード (.cpg が shift_jis/utf_8 のもの)
 - zip の中身が実は xlsx / 入れ子 zip
 - 拡張子 xlsx だが中身が CSV
"""
import sys, pathlib, zipfile, io, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import *
import pandas as pd
import c02_ckan_env as M

import os
TARGETS = [x for x in (os.environ.get("FIX_IDS") or "").split(",") if x]

def shp_encodings(zf, base, names):
    encs = []
    if base + ".cpg" in names:
        try: encs.append(zf.read(base + ".cpg").decode("ascii").strip().lower())
        except Exception: pass
    return [e for e in encs + ["cp932", "shift_jis", "utf-8", "latin-1"] if e]

def convert_shp_zip(path, rid, results):
    import shapefile
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        # 入れ子 zip
        inner = [n for n in names if n.lower().endswith(".zip")]
        if inner and not any(n.lower().endswith((".shp", ".csv")) for n in names):
            ex = RAW/"ckan/_unzip"/rid
            for n in inner: z.extract(n, ex)
            for n in inner:
                convert_shp_zip(ex/n, rid + "__" + M.safe(pathlib.PurePath(n).stem), results)
            return
        shps = [n for n in names if n.lower().endswith(".shp")]
        ex = RAW/"ckan/_unzip"/rid
        for n in shps:
            base = n[:-4]
            for e in (".shp", ".dbf", ".shx", ".prj", ".cpg"):
                if base + e in names: z.extract(base + e, ex)
            used, r = None, None
            for enc in shp_encodings(z, base, names):
                try:
                    # ファイル名にドットが含まれる場合 pyshp が拡張子を誤認するため明示的に開く
                    r = shapefile.Reader(shp=open(ex/(base+".shp"), "rb"),
                                         dbf=open(ex/(base+".dbf"), "rb"),
                                         shx=open(ex/(base+".shx"), "rb") if (ex/(base+".shx")).exists() else None,
                                         encoding=enc)
                    flds = [f[0] for f in r.fields[1:]]
                    if len(r): r.record(0)
                    used = enc; break
                except Exception:
                    continue
            if used is None:
                raise RuntimeError(f"shapefile decode failed: {n}")
            recs = []
            for sr in r.iterShapeRecords():
                d = dict(zip(flds, list(sr.record)))
                try:
                    bb = sr.shape.bbox
                    d["_bbox_minx"], d["_bbox_miny"], d["_bbox_maxx"], d["_bbox_maxy"] = bb
                    d["_centroid_x"], d["_centroid_y"] = (bb[0]+bb[2])/2, (bb[1]+bb[3])/2
                except Exception: pass
                recs.append(d)
            df = pd.DataFrame(recs)
            out = M.OUTD/f"{rid}__{M.safe(pathlib.PurePath(n).stem)}__shp.csv"
            df.to_csv(out, index=False, encoding="utf-8-sig")
            results.append((out, len(df), df.shape[1], 0, False,
                            f"shapefile:{n} dbf_encoding={used} (geometry除外/bbox付与)"))

def main():
    idx = pd.read_csv(PROC/"ckan_env_index.csv", dtype=str).fillna("")
    fixed = {}
    for rid in TARGETS:
        rows = idx[idx["resource_id"] == rid]
        if rows.empty: continue
        r0 = rows.iloc[0]
        cand = list((RAW/"ckan").rglob(f"{rid}.*"))
        cand = [c for c in cand if c.is_file() and "_unzip" not in str(c)]
        if not cand:
            print(f"  [skip] {rid}: raw file not found"); continue
        p = cand[0]
        results = []
        try:
            head = open(p, "rb").read(8)
            if head[:2] == b"PK":
                with zipfile.ZipFile(p) as z:
                    names = z.namelist()
                if "[Content_Types].xml" in names:      # 実体は xlsx
                    M.convert(p, "XLSX", rid, results, {})
                elif any(n.lower().endswith(".csv") for n in names):
                    M.convert(p, "ZIP", rid, results, {})
                else:
                    convert_shp_zip(p, rid, results)
            elif head[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":   # 実体は xls
                M.convert(p, "XLS", rid, results, {})
            else:                                       # 実体は CSV/テキスト
                M.convert(p, "CSV", rid, results, {})
        except Exception as e:
            print(f"  [still-fail] {rid}: {e}"); continue
        if results:
            fixed[rid] = results
            print(f"  [fixed] {rid}: {len(results)} files, "
                  f"{sum(x[1] for x in results)} rows")

    if not fixed:
        print("no fixes"); return
    keep = idx[~idx["resource_id"].isin(fixed)].copy()
    add = []
    for rid, results in fixed.items():
        base = idx[idx["resource_id"] == rid].iloc[0].to_dict()
        for out, nr, nc, hr, nh, note in results:
            row = dict(base)
            row.update({"output_path": str(out.relative_to(ROOT)), "n_rows": nr, "n_cols": nc,
                        "header_row_detected": hr, "needs_human": bool(nh),
                        "error": "", "note": note})
            add.append(row)
    new = pd.concat([keep, pd.DataFrame(add)], ignore_index=True)
    new.to_csv(PROC/"ckan_env_index.csv", index=False)
    write_jsonl("ckan_env_index", new.where(pd.notna(new), None).to_dict("records"))
    ok = new[(new["error"] == "") & (new["output_path"] != "")]
    print(f"[done] index rows={len(new)} converted_files={len(ok)}")
    register("ckan_env_bulk", "CKAN 環境系リソース一括CSV化（神奈川県/相模原市）",
             "神奈川県・相模原市", "https://catalog.opendata.pref.kanagawa.jp",
             "環境・生物多様性・水・森林・土地利用・災害", "CKAN目録+HTTP取得", "CSV",
             "CC BY 4.0 / CC BY-NC 4.0（データセット個別）", 1, int(len(ok)),
             f"選別1440件中232リソースを処理。変換成功ファイル{len(ok)}。"
             f"index: data/processed/ckan_env_index.csv")

main()
