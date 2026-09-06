"""環境省 生態系被害防止外来種リスト（我が国の生態系等に被害を及ぼすおそれのある外来種リスト）

ページ HTML から xls リンクを正規表現で抽出 → list2.xls をパース。
出力: data/processed/moe_ias_list.{csv,jsonl}
"""
import sys, pathlib, re, csv, html, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get, download, register, write_jsonl, PROC, RAW

SID = "moe_ias_list"
PAGE = "https://www.env.go.jp/nature/intro/2outline/iaslist.html"
RAWD = RAW/SID; RAWD.mkdir(parents=True, exist_ok=True)

r = get(PAGE); r.encoding = r.apparent_encoding
(RAWD/"page.html").write_text(r.text, encoding="utf-8")
links = []
for m in re.finditer(r'<a[^>]+href="([^"]+\.(?:xlsx|xls|csv))"[^>]*>(.*?)</a>', r.text, re.S | re.I):
    href = m.group(1)
    url = href if href.startswith("http") else "https://www.env.go.jp/nature/intro/2outline/" + href.lstrip("./")
    links.append({"url": url, "label": html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()})
(RAWD/"file_links.json").write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding="utf-8")
print("  [links]", [l["url"] for l in links])

u_list = next((l["url"] for l in links if re.search(r"/list2?\.xls$", l["url"], re.I)), None)
assert u_list, "list.xls link not found"
p = download(u_list, RAWD/"list2.xls")

import xlrd
wb = xlrd.open_workbook(p)

# セクション見出し（カテゴリー階層）。原文のまま保持する。
TOP = {"定着を予防する外来種（定着予防外来種）", "総合的に対策が必要な外来種（総合対策外来種）",
       "適切な管理が必要な産業上重要な外来種（産業管理外来種）"}
SUB = {"侵入予防外来種", "その他の定着予防外来種", "緊急対策外来種", "重点対策外来種",
       "その他の総合対策外来種"}
ORIGIN_RE = re.compile(r"^【(.+)】$")

def s(c):
    v = c.value
    if isinstance(v, float) and v == int(v): return str(int(v))
    return str(v).strip()

rows = []
for sn in wb.sheet_names():          # '動物' / '植物'
    ws = wb.sheet_by_name(sn)
    # ヘッダ行を探す（'和名' を含む行）
    hdr_i = None
    for i in range(ws.nrows):
        vals = [s(c) for c in ws.row(i)]
        if any(v.startswith("和名") for v in vals) and any(v == "学名" for v in vals):
            hdr_i = i; break
    hdr = [s(c) for c in ws.row(hdr_i)]
    col = {}
    for j, h in enumerate(hdr):
        h2 = h.replace("\n", "").replace("　", "")
        if h2.startswith("和名"): col.setdefault("wamei", j)
        elif h2 == "学名": col.setdefault("sci", j)
        elif h2.startswith("分類群"): col.setdefault("group", j)
        elif h2 == "科名": col.setdefault("family", j)
        elif h2 == "定着段階": col.setdefault("stage", j)
        elif h2.startswith("選定理由"): col.setdefault("reason", j)
        elif h2.startswith("特に問題"): col.setdefault("area", j)
        elif h2 == "備考": col.setdefault("note", j)
    # 分類群列が2列(No./名称)に分かれるシートがあるので、名称側を採る
    if sn == "動物":
        col["group"] = 2

    origin, top, sub = None, None, None
    n = 0
    for i in range(ws.nrows):
        vals = [s(c) for c in ws.row(i)]
        nonempty = [v for v in vals if v]
        joined = "".join(vals).replace("\n", "")
        if nonempty:
            mm = ORIGIN_RE.match(nonempty[0].replace("　", ""))
            if mm: origin = mm.group(1); top = sub = None; continue
        if len(nonempty) <= 2 and nonempty:
            if joined in TOP or nonempty[0].replace("\n", "") in TOP:
                top = joined if joined in TOP else nonempty[0].replace("\n", ""); sub = None; continue
            if nonempty[0] in SUB: sub = nonempty[0]; continue
            continue
        sci = vals[col["sci"]] if "sci" in col and col["sci"] < len(vals) else ""
        wam = vals[col["wamei"]] if "wamei" in col and col["wamei"] < len(vals) else ""
        if not (sci or wam): continue
        if wam in ("和名", "") and sci in ("学名", ""): continue
        if sci == "学名": continue
        cat = sub or top
        if cat is None: continue
        rows.append({
            "category_ja": cat,
            "category_parent_ja": top,
            "origin_ja": origin,
            "kingdom_sheet_ja": sn,
            "taxon_group_ja": (vals[col["group"]] if "group" in col and col["group"] < len(vals) else None) or (
                "植物" if sn == "植物" else None),
            "family_ja": vals[col["family"]] if "family" in col and col["family"] < len(vals) else None,
            "scientific_name": re.sub(r"\s+", " ", sci).strip() or None,
            "vernacular_name_ja": wam or None,
            "establishment_stage_ja": vals[col["stage"]] if "stage" in col and col["stage"] < len(vals) else None,
            "selection_reason_ja": vals[col["reason"]] if "reason" in col and col["reason"] < len(vals) else None,
            "problem_area_ja": vals[col["area"]] if "area" in col and col["area"] < len(vals) else None,
            "ias_law_status_ja": vals[col["note"]] if "note" in col and col["note"] < len(vals) else None,
            "note_ja": None,
            "source_id": SID,
            "source_ref": f"{u_list}#{sn}!row={i+1}",
        })
        n += 1
    print(f"  [{sn}] {n} rows")

for r_ in rows:
    for k, v in list(r_.items()):
        if isinstance(v, str) and v.strip() == "": r_[k] = None

COLS = ["category_ja", "category_parent_ja", "origin_ja", "taxon_group_ja", "family_ja",
        "scientific_name", "vernacular_name_ja", "ias_law_status_ja",
        "establishment_stage_ja", "selection_reason_ja", "problem_area_ja",
        "kingdom_sheet_ja", "note_ja", "source_id", "source_ref"]
with open(PROC/f"{SID}.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
    for r_ in rows: w.writerow({c: r_.get(c) for c in COLS})
print(f"  [write] data/processed/{SID}.csv  {len(rows)} rows")
write_jsonl(SID, [{c: r_.get(c) for c in COLS} for r_ in rows])

register(SID, "生態系被害防止外来種リスト（我が国の生態系等に被害を及ぼすおそれのある外来種リスト）",
         "環境省 自然環境局", PAGE, "外来種", "HTMLからリンク抽出→XLS直取得", "XLS",
         "公共データ利用規約（第1.0版）PDL1.0（環境省ホームページコンテンツの利用について）: "
         "https://www.env.go.jp/mail.html", 1, len(rows),
         "list2.xls（2015.03.26版）の動物・植物シート。category_ja は掲載区分の原文見出し"
         "（侵入予防外来種/その他の定着予防外来種/緊急対策外来種/重点対策外来種/"
         "その他の総合対策外来種/産業管理外来種）。ias_law_status_ja は備考欄原文"
         "（特定外来/未判定/*=旧要注意外来生物 等）。")
print("done.")
