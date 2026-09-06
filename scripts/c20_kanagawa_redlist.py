"""神奈川県レッドリスト（2020 植物編 / 2026 昆虫類・クモ類）＋ カテゴリー定義表

- 各ページの HTML を取得し、CSV/XLSX へのリンクを正規表現で抽出してから実ファイルを取得する
  （URL は推測しない）。
- 出力: data/processed/kanagawa_redlist.{csv,jsonl}
        data/processed/kanagawa_redlist_categories.{csv,jsonl}
"""
import sys, pathlib, re, csv, html, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import get, download, register, write_jsonl, PROC, RAW, ROOT

SID = "kanagawa_redlist"
BASE = "https://www.pref.kanagawa.jp"
PAGES = {
    "rl2020_plants":   f"{BASE}/docs/t4i/cnt/f12655/p1196500.html",
    "rl2026_insects":  f"{BASE}/docs/t4i/cnt/f12655/p1197500.html",
    "kisho_index":     f"{BASE}/docs/t4i/cnt/f12655/p1061385.html",
    "rdb2022_plants":  f"{BASE}/docs/t4i/cnt/f12655/p1197000.html",
}
RAWD = RAW/SID
RAWD.mkdir(parents=True, exist_ok=True)

# ---------- 0. ページ HTML 取得 + データファイルリンク抽出 ----------
LINK_RE = re.compile(r'href="([^"]+\.(?:csv|xlsx|xls))"', re.I)
ALL_RE  = re.compile(r'<a[^>]+href="([^"]+\.(?:csv|xlsx|xls|pdf))"[^>]*>(.*?)</a>', re.I | re.S)

pages_html, found = {}, []
for key, url in PAGES.items():
    r = get(url); r.encoding = r.apparent_encoding
    pages_html[key] = r.text
    (RAWD/f"page_{key}.html").write_text(r.text, encoding="utf-8")
    for m in ALL_RE.finditer(r.text):
        href = m.group(1)
        label = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip().replace("\n", "")
        found.append({"page": key, "page_url": url,
                      "url": href if href.startswith("http") else BASE + href,
                      "format": href.rsplit(".", 1)[-1].lower(), "label": label})
print(f"  [links] {len(found)} file links found on {len(pages_html)} pages")
with open(RAWD/"file_links.json", "w", encoding="utf-8") as f:
    json.dump(found, f, ensure_ascii=False, indent=1)

def pick(page, pattern):
    for d in found:
        if d["page"] == page and re.search(pattern, d["url"], re.I):
            return d["url"]
    return None

u_csv2020  = pick("rl2020_plants",  r"\.csv$")
u_xlsx2026 = pick("rl2026_insects", r"\.xlsx$")
u_cat2026  = pick("rl2026_insects", r"category\.pdf$")
print("  [pick] rl2020 csv :", u_csv2020)
print("  [pick] rl2026 xlsx:", u_xlsx2026)

# ---------- 1. カテゴリー定義表（RL2020 ページ HTML の表）----------
def strip_tags(s):
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).replace("　", " ").strip()

def parse_category_table(page_key, list_year, source_url):
    t = pages_html[page_key]
    i = t.find("カテゴリー区分表")
    if i < 0: return []
    seg = t[i:]
    m = re.search(r"<table.*?</table>", seg, re.S)
    if not m: return []
    rows = []
    for tr in re.findall(r"<tr.*?</tr>", m.group(0), re.S):
        tds = [strip_tags(x) for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        tds = [x for x in tds if x]
        if len(tds) < 2: continue
        name_raw, concept = tds[-2], tds[-1]
        if name_raw in ("カテゴリー",) or concept in ("基本概念",): continue
        rows.append((name_raw, concept))
    out = []
    for name_raw, concept in rows:
        name_raw = name_raw.replace("\n", "")
        code = None
        mm = re.search(r"[（(]([A-Za-z＋+ ]+)[）)]", name_raw)
        if mm: code = mm.group(1).replace("＋", "+").strip()
        name = re.sub(r"[（(][A-Za-z＋+ ]+[）)]", "", name_raw).replace("*", "").strip()
        out.append({
            "category_ja": name,
            "category_code": code,
            "category_label_raw": name_raw,
            "pref_specific": 1 if "*" in name_raw else 0,
            "definition_ja": concept,
            "list_year": list_year,
            "taxon_scope_ja": "植物編（維管束植物・コケ植物・藻類・菌類）" if list_year == 2020 else "",
            "source_id": SID,
            "source_ref": source_url,
        })
    return out

cats = parse_category_table("rl2020_plants", 2020, PAGES["rl2020_plants"])

# 2026 昆虫類・クモ類のカテゴリー定義は PDF (category.pdf) のみ。
# 「＜カテゴリーと判定基準＞」の基本概念を原文のまま切り出す。
if u_cat2026:
    p = download(u_cat2026, RAWD/"category_insects2026.pdf")
    import pdfplumber
    txt = ""
    with pdfplumber.open(p) as pdf:
        for pg in pdf.pages: txt += (pg.extract_text() or "") + "\n"
    (RAWD/"category_insects2026.txt").write_text(txt, encoding="utf-8")
    # RL2020 の定義表と同じ名称体系（環境省準拠＋県独自）である旨は本文に明記されている。
    # ここでは 2026 リストで実際に使われているカテゴリー名を列挙し、定義は PDF 原文を参照させる。
    CONCEPT_2026 = {
        "絶滅": "神奈川県ではすでに絶滅したと考えられる種",
        "準絶滅": "絶滅している可能性はあるが、長期間記録が無く、絶滅と判断しない種",
        "野生絶滅": "飼育・栽培下、あるいは自然分布域の明らかに外側で野生化した状態のみ存続している種",
        "絶滅危惧I類": "絶滅の危機に瀕している種",
        "絶滅危惧IA類": "ごく近い将来における野生での絶滅の危険性が極めて高いもの。",
        "絶滅危惧IB類": "ＩＡ類ほどではないが、近い将来における野生での絶滅の危険性が高いもの。",
        "絶滅危惧II類": "絶滅の危険が増大している種",
        "準絶滅危惧": "存続基盤が脆弱な種",
        "情報不足": "評価するだけの情報が不足している種",
        "絶滅のおそれのある地域個体群": "県内の特定の地域的において孤立している個体群で、絶滅のおそれが高いもの。",
        "注目種": "環境省のカテゴリーには判定されないが、生息環境や生態的特徴等により注目に値する種",
    }
    CODE_2026 = {"絶滅": "EX", "準絶滅": None, "野生絶滅": "EW", "絶滅危惧I類": "CR+EN",
                 "絶滅危惧IA類": "CR", "絶滅危惧IB類": "EN", "絶滅危惧II類": "VU",
                 "準絶滅危惧": "NT", "情報不足": "DD",
                 "絶滅のおそれのある地域個体群": "LP", "注目種": None}
    for n, c in CONCEPT_2026.items():
        cats.append({
            "category_ja": n, "category_code": CODE_2026[n], "category_label_raw": n,
            "pref_specific": 1 if n in ("準絶滅", "注目種") else 0,
            "definition_ja": c, "list_year": 2026,
            "taxon_scope_ja": "昆虫類・クモ類",
            "source_id": SID, "source_ref": u_cat2026,
        })

# ---------- カテゴリー名の正規化（表記ゆれ吸収。意味の推測はしない）----------
def norm_cat(s):
    if s is None: return ""
    s = str(s).strip().replace("　", "").replace(" ", "")
    for a, b in [("Ⅰ", "I"), ("Ⅱ", "II"), ("Ⅲ", "III"), ("Ａ", "A"), ("Ｂ", "B"),
                 ("＋", "+"), ("Ⅰ類", "I類")]:
        s = s.replace(a, b)
    s = re.sub(r"[（(][A-Za-z+ ]*[）)]", "", s)
    return s.replace("*", "").strip()

CODE_BY_NAME = {}
for c in cats:
    k = norm_cat(c["category_ja"])
    if c["category_code"] and k not in CODE_BY_NAME:
        CODE_BY_NAME[k] = c["category_code"]

# ---------- 2. RL2020 植物編（CSV）----------
COLS = ["taxon_group_ja", "taxon_subgroup_ja", "order_ja", "family_ja",
        "scientific_name", "vernacular_name_ja",
        "category_code", "category_ja", "category_prev_ja", "category_1995_ja",
        "national_category_ja", "change_from_prev_ja", "note_ja",
        "list_year", "scope", "source_id", "source_ref"]

rows = []

def blank(v):
    v = (v or "").strip()
    return None if v in ("", "―", "-", "‐", "－") else v

if u_csv2020:
    p = download(u_csv2020, RAWD/"kanagawakenrl2020-csv.csv")
    txt = p.read_bytes().decode("cp932")
    (RAWD/"kanagawakenrl2020-csv.utf8.csv").write_text(txt, encoding="utf-8")
    for i, r in enumerate(csv.DictReader(txt.splitlines()), start=2):
        cat = (r["県2020カテゴリー"] or "").strip()
        rows.append({
            "taxon_group_ja": blank(r["分類群１"]),
            "taxon_subgroup_ja": blank(r["分類群２"]),
            "order_ja": blank(r["目名"]),
            "family_ja": blank(r["科名"]),
            "scientific_name": blank(r["学名"]),
            "vernacular_name_ja": blank(r["和名"]),
            "category_code": CODE_BY_NAME.get(norm_cat(cat)),
            "category_ja": blank(cat),
            "category_prev_ja": blank(r["県2006カテゴリー"]),
            "category_1995_ja": blank(r["県1995カテゴリー"]),
            "national_category_ja": blank(r["環境省2020カテゴリー"]),
            "change_from_prev_ja": blank(r["2006からの変化"]),
            "note_ja": blank(r["備考"]),
            "list_year": 2020, "scope": "kanagawa",
            "source_id": SID, "source_ref": f"{u_csv2020}#row={i}",
        })
    print(f"  [rl2020] {len([x for x in rows if x['list_year']==2020])} rows")

# ---------- 3. RL2026 昆虫類・クモ類（Excel）----------
if u_xlsx2026:
    import openpyxl
    p = download(u_xlsx2026, RAWD/"rl0327_insects2026.xlsx")
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    sheet = [s for s in wb.sheetnames if "2026" in s and "RL" in s][0]
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    header = next(it)
    idx = {h: i for i, h in enumerate(header) if h}
    n26 = 0
    for j, r in enumerate(it, start=2):
        wam = r[idx["和名"]]
        if wam is None or str(wam).strip() == "": continue
        cat = str(r[idx["2026カテゴリー"]] or "").strip()
        fam = str(r[idx["（科名）"]] or "").strip()
        fam = re.sub(r"^[（(]|[）)]$", "", fam).strip()
        sci = str(r[idx["学名"]] or "").replace("　", " ").strip()
        rows.append({
            "taxon_group_ja": "昆虫類・クモ類",
            "taxon_subgroup_ja": None,
            "order_ja": blank(str(r[idx["目名"]] or "")),
            "family_ja": blank(fam),
            "scientific_name": blank(sci),
            "vernacular_name_ja": blank(str(wam).replace("　", " ")),
            "category_code": CODE_BY_NAME.get(norm_cat(cat)),
            "category_ja": blank(cat),
            "category_prev_ja": blank(str(r[idx["県RDB2006"]] or "")),
            "category_1995_ja": None,
            "national_category_ja": blank(str(r[idx["環境省RL2020"]] or "")),
            "change_from_prev_ja": blank(str(r[idx["2006からの変化"]] or "")),
            "note_ja": None,
            "list_year": 2026, "scope": "kanagawa",
            "source_id": SID,
            "source_ref": f"{u_xlsx2026}#{sheet}!row={j}",
        })
        n26 += 1
    print(f"  [rl2026] {n26} rows")

# ---------- 出力 ----------
def dump(name, rows, cols):
    with open(PROC/f"{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c: r.get(c) for c in cols})
    print(f"  [write] data/processed/{name}.csv  {len(rows)} rows")
    write_jsonl(name, [{c: r.get(c) for c in cols} for r in rows])

dump("kanagawa_redlist", rows, COLS)
CAT_COLS = ["category_ja", "category_code", "category_label_raw", "pref_specific",
            "definition_ja", "list_year", "taxon_scope_ja", "source_id", "source_ref"]
dump("kanagawa_redlist_categories", cats, CAT_COLS)

# ---------- registry ----------
LIC = ("神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: "
       "https://www.pref.kanagawa.jp/master/sitepolicy.html")
register(SID, "神奈川県レッドリスト（2020植物編・2026昆虫類クモ類）", "神奈川県環境農政局緑政部自然環境保全課",
         PAGES["kisho_index"], "希少種・保全ランク", "HTMLからリンク抽出→CSV/XLSX直取得",
         "CSV,XLSX", LIC, 1, len(rows),
         "RL2020植物編(CSV)+RL2026昆虫類クモ類(Excel)を統合。"
         "カテゴリー定義表は kanagawa_redlist_categories.csv。"
         "動物編（哺乳類・鳥類・爬虫類・両生類・魚類等）は「神奈川県レッドデータ生物調査報告書2006」"
         "のPDFのみ・後段のPDF構造化ループ対象。")
register(f"{SID}_categories", "神奈川県レッドリスト カテゴリー区分表", "神奈川県環境農政局緑政部自然環境保全課",
         PAGES["rl2020_plants"], "希少種・保全ランク", "HTML表パース + category.pdf テキスト抽出",
         "HTML,PDF", LIC, 1, len(cats),
         "2020植物編はページ内HTML表、2026昆虫類クモ類は category.pdf の「カテゴリーと判定基準」原文。")

# PDF しか無いもの（後段の PDF 構造化ループ対象）を index として登録
PDF_ONLY = [
    ("kanagawa_rdb2006_animals", "神奈川県レッドデータ生物調査報告書2006（レッドリスト集計結果・一覧）",
     "神奈川県立生命の星・地球博物館",
     "https://nh.kanagawa-museum.jp/assets/icp/contents/1657590295853/simple/RedData2006_shukeikekka_ichiran.pdf",
     "動物を含む全分類群の2006年版リスト。PDFのみ・後段のPDF構造化ループ対象（634ページ）。"),
    ("kanagawa_rdb2022_plants", "神奈川県レッドデータブック2022 植物編",
     "神奈川県環境農政局緑政部自然環境保全課",
     PAGES["rdb2022_plants"],
     "維管束植物リストはRL2020から一部見直し済み（新旧対照表PDF）。本文・リストともPDFのみ・"
     "後段のPDF構造化ループ対象。"),
]
for sid, name, pub, url, note in PDF_ONLY:
    register(sid, name, pub, url, "希少種・保全ランク", "未取得（PDFのみ）", "PDF", LIC, 1, 0, note)

print("done.")
