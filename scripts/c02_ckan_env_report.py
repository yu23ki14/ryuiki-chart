# -*- coding: utf-8 -*-
"""ckan_env_index.csv の要約（報告用）"""
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import PROC, ROOT, to_fiscal_year
import pandas as pd

idx = pd.read_csv(PROC/"ckan_env_index.csv", dtype=str).fillna("")
idx["n_rows_i"] = pd.to_numeric(idx["n_rows"], errors="coerce").fillna(0).astype(int)
ok  = idx[(idx["error"] == "") & (idx["output_path"] != "")]
ng  = idx[idx["error"] != ""]

print(f"index rows        : {len(idx)}")
print(f"変換成功ファイル   : {len(ok)}")
print(f"対象リソース(成功) : {ok['resource_id'].nunique()}")
print(f"失敗/未処理        : {len(ng)}  (resource {ng['resource_id'].nunique()})")
print(f"needs_human=True   : {(ok['needs_human']=='True').sum()}")
print(f"総行数             : {ok['n_rows_i'].sum():,}")
print("\n-- 失敗理由 top --")
print(ng["error"].str.replace(r"[0-9a-f\-]{8,}", "…", regex=True).str[:90].value_counts().head(12).to_string())

def years(g):
    ys = set()
    for t in list(g["dataset_title"]) + list(g["resource_name"]):
        for m in re.findall(r"(19[7-9]\d|20[0-4]\d)", str(t)):
            ys.add(int(m))
        y = to_fiscal_year(str(t))
        if y and 1970 <= y <= 2030: ys.add(y)
    return f"{min(ys)}–{max(ys)}" if len(ys) > 1 else (str(min(ys)) if ys else "-")

g = ok.groupby("dataset_title").agg(files=("output_path", "count"),
                                    rows=("n_rows_i", "sum"),
                                    resources=("resource_id", "nunique"))
g["period"] = [years(ok[ok["dataset_title"] == t]) for t in g.index]
g = g.sort_values("rows", ascending=False)
pd.set_option("display.width", 200); pd.set_option("display.max_colwidth", 46)
print("\n-- 変換できたデータセット（行数順 上位20） --")
print(g.head(20).to_string())
