"""環境省レッドリスト（国版・分類群ごとの最新版）

env.go.jp のレッドリスト総合ページ → いきものログ(生物多様性センター)の RL/RDB 一覧ページ
から CSV リンクを正規表現で抽出して取得する（URL は推測しない）。
分類群ごとの「最新版」は同ページ本文の記述に従う:
  植物・菌類 = 第5次(2025) / 鳥類・爬虫類・両生類 = 第5次(2026) /
  残る陸域動物 = レッドリスト2020 / 海洋生物 = 海洋生物レッドリスト2017
出力: data/processed/moe_redlist.{csv,jsonl}, moe_redlist_categories.{csv,jsonl}
"""
import sys, pathlib, re, csv, html, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get, download, register, write_jsonl, PROC, RAW

SID = "moe_redlist"
TOP = "https://www.env.go.jp/nature/kisho/hozen/redlist/"
IKI = "https://ikilog.biodic.go.jp/Rdb/booklist"
RAWD = RAW/SID; RAWD.mkdir(parents=True, exist_ok=True)

r = get(TOP); r.encoding = r.apparent_encoding
(RAWD/"page_env_redlist.html").write_text(r.text, encoding="utf-8")
assert IKI.split("//")[1] in r.text or "ikilog.biodic.go.jp/Rdb/booklist" in r.text, \
    "いきものログ RL/RDB 一覧へのリンクが見つからない"

r2 = get(IKI); r2.encoding = r2.apparent_encoding
(RAWD/"page_ikilog_booklist.html").write_text(r2.text, encoding="utf-8")
csv_links = sorted({("https://ikilog.biodic.go.jp" + m) if m.startswith("/") else m
                    for m in re.findall(r'href="([^"]+\.csv)"', r2.text)})
(RAWD/"file_links.json").write_text(json.dumps(csv_links, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"  [links] {len(csv_links)} csv links on ikilog booklist")

# 分類群ごとの最新版（同ページ本文の記述にもとづく）
# GROUP は いきものログ RL/RDB 一覧ページの表に書かれた分類群見出し（原文）
LATEST = [
    # (ファイル名の一部, list_year, 版名, ページ上の分類群見出し)
    ("redlist2026/redlist2026_birds.csv",        2026, "第5次レッドリスト（2026）", "鳥類"),
    ("redlist2026/redlist2026_reptiles.csv",     2026, "第5次レッドリスト（2026）", "爬虫類"),
    ("redlist2026/redlist2026_amphibian.csv",    2026, "第5次レッドリスト（2026）", "両生類"),
    ("redlist2025/redlist2025_ikansoku.csv",     2025, "第5次レッドリスト（2025）", "維管束植物"),
    ("redlist2025/redlist2025_sentairui.csv",    2025, "第5次レッドリスト（2025）", "蘚苔類"),
    ("redlist2025/redlist2025_sorui.csv",        2025, "第5次レッドリスト（2025）", "藻類"),
    ("redlist2025/redlist2025_chiirui.csv",      2025, "第5次レッドリスト（2025）", "地衣類"),
    ("redlist2025/redlist2025_kinrui.csv",       2025, "第5次レッドリスト（2025）", "菌類"),
    ("redlist2020/redlist2020_honyurui.csv",     2020, "レッドリスト2020", "哺乳類"),
    ("redlist2020/redlist2020_tansuigyorui.csv", 2020, "レッドリスト2020", "汽水・淡水魚類"),
    ("redlist2020/redlist2020_kontyurui.csv",    2020, "レッドリスト2020", "昆虫類"),
    ("redlist2020/redlist2020_kairui.csv",       2020, "レッドリスト2020", "貝類"),
    ("redlist2020/redlist2020_invertebrate.csv", 2020, "レッドリスト2020", "その他無脊椎動物"),
    ("redlist2017/kaiyo/redlist2017kaiyo_gyorui.csv",            2017, "海洋生物レッドリスト2017", "魚類（海洋生物）"),
    ("redlist2017/kaiyo/redlist2017kaiyo_sangorui.csv",          2017, "海洋生物レッドリスト2017", "サンゴ類（海洋生物）"),
    ("redlist2017/kaiyo/redlist2017kaiyo_koukakurui.csv",        2017, "海洋生物レッドリスト2017", "甲殻類（海洋生物）"),
    ("redlist2017/kaiyo/redlist2017kaiyo_nantai.csv",            2017, "海洋生物レッドリスト2017", "軟体動物（頭足類）（海洋生物）"),
    ("redlist2017/kaiyo/redlist2017kaiyo_sonotamusekitsui.csv",  2017, "海洋生物レッドリスト2017", "その他無脊椎動物（海洋生物）"),
]

def decode(b):
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try: return b.decode(enc)
        except UnicodeDecodeError: continue
    return b.decode("utf-8", "replace")

def blank(v):
    v = (v or "").strip().replace("　", " ").strip()
    return None if v in ("", "―", "-", "‐", "－") else v

CAT_RE = re.compile(r"[（(]([A-Za-z+ ]+)[）)]\s*$")

rows, missing = [], []
for frag, year, edition, grp in LATEST:
    url = next((u for u in csv_links if u.endswith("/" + frag) or frag in u), None)
    if not url:
        missing.append(frag); print("  [miss]", frag); continue
    p = download(url, RAWD/pathlib.Path(frag).name)
    txt = decode(p.read_bytes())
    lines = txt.splitlines()
    rdr = list(csv.reader(lines))
    # 第5次(2026) は3行ヘッダの横長形式、それ以外は「カテゴリー,分類群,和名,学名」
    if rdr and rdr[0] and rdr[0][0].strip().lstrip("﻿") == "1":
        hdr = rdr[2]
        ix = {h.strip(): i for i, h in enumerate(hdr)}
        c_cat, c_eng = ix.get("カテゴリーJPN"), ix.get("カテゴリーENG")
        c_ord, c_fam = ix.get("目名"), ix.get("科名")
        c_wam, c_sci = ix.get("和名"), ix.get("学名")
        c_grp, c_no = ix.get("分科会名"), ix.get("掲載No.")
        c_crit = ix.get("判定基準")
        body = rdr[3:]
        for i, rr in enumerate(body, start=4):
            if not rr or not blank(rr[c_wam] if c_wam is not None else ""):
                if not (c_sci is not None and blank(rr[c_sci] if len(rr) > c_sci else "")): continue
            cat = blank(rr[c_cat]) if c_cat is not None and len(rr) > c_cat else None
            code = blank(rr[c_eng]) if c_eng is not None and len(rr) > c_eng else None
            rows.append({
                "taxon_group_ja": blank(rr[c_grp]) if c_grp is not None and len(rr) > c_grp else None,
                "order_ja": blank(rr[c_ord]) if c_ord is not None and len(rr) > c_ord else None,
                "family_ja": blank(rr[c_fam]) if c_fam is not None and len(rr) > c_fam else None,
                "scientific_name": blank(rr[c_sci]) if c_sci is not None and len(rr) > c_sci else None,
                "vernacular_name_ja": blank(rr[c_wam]) if c_wam is not None and len(rr) > c_wam else None,
                "category_code": code,
                "category_ja": cat,
                "category_prev_ja": None,
                "national_category_ja": cat,
                "note_ja": ("判定基準: " + blank(rr[c_crit])) if c_crit is not None and len(rr) > c_crit
                           and blank(rr[c_crit]) else None,
                "taxon_group_list_ja": grp,
                "list_year": year, "edition_ja": edition, "scope": "national",
                "source_id": SID,
                "source_ref": f"{url}#{blank(rr[c_no]) if c_no is not None and len(rr)>c_no else 'row='+str(i)}",
            })
    else:
        rdr2 = list(csv.DictReader(lines[0:]))
        # BOM 対策
        if rdr2 and "カテゴリー" not in rdr2[0]:
            fixed = {k.lstrip("﻿"): k for k in rdr2[0]}
            rdr2 = [{k.lstrip("﻿"): v for k, v in d.items()} for d in rdr2]
        for i, d in enumerate(rdr2, start=2):
            cat = blank(d.get("カテゴリー"))
            if not cat and not blank(d.get("和名")): continue
            m = CAT_RE.search(cat or "")
            code = m.group(1).replace(" ", "") if m else None
            rows.append({
                "taxon_group_ja": blank(d.get("分類群")),
                "order_ja": None, "family_ja": None,
                "scientific_name": blank(d.get("学名")),
                "vernacular_name_ja": blank(d.get("和名")),
                "category_code": code,
                "category_ja": re.sub(r"\s*[（(][A-Za-z+ ]+[）)]\s*$", "", cat) if cat else None,
                "category_prev_ja": None,
                "national_category_ja": cat,
                "note_ja": None,
                "taxon_group_list_ja": grp,
                "list_year": year, "edition_ja": edition, "scope": "national",
                "source_id": SID, "source_ref": f"{url}#row={i}",
            })
    print(f"  [{pathlib.Path(frag).name}] total now {len(rows)}")

COLS = ["taxon_group_list_ja", "taxon_group_ja", "order_ja", "family_ja", "scientific_name", "vernacular_name_ja",
        "category_code", "category_ja", "category_prev_ja", "national_category_ja",
        "note_ja", "list_year", "edition_ja", "scope", "source_id", "source_ref"]
with open(PROC/f"{SID}.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
    for r_ in rows: w.writerow({c: r_.get(c) for c in COLS})
print(f"  [write] data/processed/{SID}.csv  {len(rows)} rows")
write_jsonl(SID, [{c: r_.get(c) for c in COLS} for r_ in rows])

# カテゴリー記号の一覧（データ中に出現した 名称→記号 の実対応をそのまま出す）
seen = {}
for r_ in rows:
    k = (r_["category_ja"], r_["category_code"], r_["list_year"])
    seen[k] = seen.get(k, 0) + 1
cat_rows = [{"category_ja": k[0], "category_code": k[1], "list_year": k[2], "record_count": v,
             "source_id": SID, "source_ref": TOP} for k, v in sorted(seen.items(), key=lambda x: str(x[0]))]
with open(PROC/f"{SID}_categories.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["category_ja", "category_code", "list_year",
                                      "record_count", "source_id", "source_ref"])
    w.writeheader(); w.writerows(cat_rows)
write_jsonl(f"{SID}_categories", cat_rows)
print(f"  [write] data/processed/{SID}_categories.csv  {len(cat_rows)} rows")

register(SID, "環境省レッドリスト（分類群ごとの最新版）", "環境省／生物多様性センター いきものログ",
         TOP, "希少種・保全ランク", "HTMLからCSVリンク抽出→CSV直取得", "CSV",
         "第5次RL(CSV)はCC BY 4.0（いきものログ記載）。環境省サイトは公共データ利用規約(第1.0版)PDL1.0。",
         1, len(rows),
         "分類群ごとの最新版のみ収録: 鳥類・爬虫類・両生類=第5次(2026), "
         "維管束植物/蘚苔類/藻類/地衣類/菌類=第5次(2025), "
         "哺乳類/汽水・淡水魚類/昆虫類/貝類/その他無脊椎動物=レッドリスト2020, "
         "海洋生物5分類群=海洋生物レッドリスト2017。"
         + (f" 取得できなかったファイル: {missing}" if missing else ""))
print("done.")
