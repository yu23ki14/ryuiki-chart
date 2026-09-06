#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""保護区・緑地・樹木の指定状況（CSV行29・30・195・196）を1本にまとめる。

4ソースはすべて「区域や地点の指定台帳」なので、共通の列構成
(area_id, name_ja, category_ja, category_code, municipality_ja, area_ha, area_ha_raw,
 designated_on, designated_on_raw, lat, lon, note_ja, source_id, source_ref)
で出す。埋まらない列は null。

1. kanagawa_natural_parks (行29)
   https://www.pref.kanagawa.jp/docs/t4i/cnt/f5842/p16572.html
   HTML内に6公園の実表(<table>)。地種区分別面積(特別保護地区/第1〜3種特別地域/普通地域)は
   category_code='natural_park_zoning' の子レコードとして親公園とは別行で出す。
   既存の nlni_a10_natparks (国土数値情報 自然公園地域GISポリゴン) は OBJ_NAME が全件空で
   公園名称を持たないため、本ソースがその名称欠落を補う位置づけ (register() notes に明記)。

2. kanagawa_green_conservation (行30)
   https://www.pref.kanagawa.jp/docs/t4i/cnt/f10578/index.html から動的にPDFリンクを拾う
   (ファイル名は変わりうるため、リンクのラベル文言で判定する。tokuryoku2025.pdf/kinryoku2025.pdf
   のような命名が指す内容は取得のたびに変わりうることを実際に確認した)。
   - 歴史的風土保存地区の指定状況 (1ページ、2段組: 保存区域5件[概数=約] + 特別保存地区13件)
   - 特別緑地保全地区の指定状況 (複数ページ、市町村ごとに小計行があるテーブル。293地区)
   - 近郊緑地保全区域の指定状況 (1ページ、2段組: 保全区域7件 + 特別保全地区10件)
   - 風致地区の指定状況 (1ページ、市町名forward-fill。51地区)
   ページ内の各表の小計/合計行と個別行の面積合計を突合し一致を確認済み(取得時点)。
   ※「自然環境保全地域の指定状況」PDFは別タスク(CSV行27)の担当のためここでは取得しない。

3. hiratsuka_parks (行195) 平塚市オープンデータ 公園CSV(294列54列、実測290件・cp932)
   アメニティ等の共通列に無い原列は data/processed/hiratsuka_parks_full.csv に別途フル保存。

4. hadano_preserved_trees (行196) 秦野市 保存樹木一覧CSV(UTF-8 BOM付, 30件)
   緯度・経度列は原データ全行で空欄(位置情報なし)。指定年月日にあたる列も原データに無い
   (指定番号のみ)。数値を推測で埋めないため lat/lon/designated_on はすべて null。
"""
import sys, pathlib, re, csv, collections
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get, download, register, write_jsonl, to_number, PROC, RAW, ROOT, now
from bs4 import BeautifulSoup
import pdfplumber

COMMON_COLS = [
    "area_id", "name_ja", "category_ja", "category_code", "municipality_ja",
    "area_ha", "area_ha_raw", "designated_on", "designated_on_raw", "lat", "lon",
    "note_ja", "source_id", "source_ref",
]


def rec(**kw):
    r = {k: kw.get(k) for k in COMMON_COLS}
    extra = {k: v for k, v in kw.items() if k not in COMMON_COLS}
    r.update(extra)
    return r


def num(text):
    """テキスト中の最初の数値(カンマ区切り可)を to_number() 経由で取り出す。単位文字等は無視。"""
    if text is None:
        return None
    m = re.search(r"-?[\d,]+(?:\.\d+)?", str(text))
    if not m:
        return None
    v, _ = to_number(m.group(0))
    return v if isinstance(v, (int, float)) else None


def fetch_soup(url):
    r = get(url)
    html = r.content.decode("utf-8")  # r.encoding が ISO-8859-1 に誤検出されるサイトがあるため明示 decode
    return BeautifulSoup(html, "html.parser"), html


# ---- 和暦日付 ----
ERA_BASE = {"S": 1925, "H": 1988, "R": 2018, "T": 1911}
DATE_RE = re.compile(
    r"([SHRT])[\s　]*(元|\d{1,2})[\s　]*[.．][\s　]*(\d{1,2})"
    r"(?:[\s　]*[.．][\s　]*(\d{1,2}))?"
)


def parse_wareki_dates(text):
    """テキスト中の全ての和暦日付(S/H/R/T)を抽出。日が無ければ年月まで。"""
    if not text:
        return []
    out = []
    for m in DATE_RE.finditer(text):
        era, y, mo, d = m.groups()
        y = 1 if y == "元" else int(y)
        year = ERA_BASE[era] + y
        mo = int(mo)
        if d:
            out.append((f"{year:04d}-{mo:02d}-{int(d):02d}", (year, mo, int(d))))
        else:
            out.append((f"{year:04d}-{mo:02d}", (year, mo, 0)))
    return out


def earliest_date(text):
    """複数の指定・変更年月日が並ぶ原文から、最も古い(=当初指定)日付を選ぶ。
    PDFのセル内で行の並び順が指定順と一致しない例(例:湯河原「拡大H5.7.2\\nS15.7.31\\n変更H17.4.1」)
    があるため、文字列順ではなく実際の年月日の大小で判定する。"""
    ds = parse_wareki_dates(text)
    if not ds:
        return None
    ds.sort(key=lambda x: x[1])
    return ds[0][0]


def join_segments(parts, sep="・"):
    """<br>等で分割された市区町村名の断片を再結合する。「〜町の」のような送り仮名で
    次の断片へ続く場合は区切り文字を入れない(例:「箱根町」「小田原市」「湯河原町の」「各一部」
    → 「箱根町・小田原市・湯河原町の各一部」)。"""
    out = ""
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if out and not out.endswith(("の", "、", "及び", "・")):
            out += sep
        out += p
    return out


# ======================================================================
# 1. kanagawa_natural_parks
# ======================================================================
SID1 = "kanagawa_natural_parks"
URL1 = "https://www.pref.kanagawa.jp/docs/t4i/cnt/f5842/p16572.html"

PARK_SLUG = {
    "富士箱根伊豆国立公園（箱根地域）": ("fujihakoneizu_hakone", "national_park", "国立公園"),
    "丹沢大山国定公園": ("tanzawaoyama_kokutei", "quasi_national_park", "国定公園"),
    "県立丹沢大山自然公園": ("pref_tanzawaoyama", "pref_natural_park", "県立自然公園"),
    "県立真鶴半島自然公園": ("pref_manazuruhanto", "pref_natural_park", "県立自然公園"),
    "県立奥湯河原自然公園": ("pref_okuyugawara", "pref_natural_park", "県立自然公園"),
    "県立陣馬相模湖自然公園": ("pref_jinbasagamiko", "pref_natural_park", "県立自然公園"),
}
ZONE_RE = re.compile(r"(特別保護地区|第[1-3]種特別地域|特別地域|普通地域)[\s　]*([\d,]+(?:\.\d+)?)[\s　]*ha")
SUB_RE = re.compile(r"（うち([^）]*?)[\s　]*([\d,]+(?:\.\d+)?)[\s　]*ha）")


def build_natural_parks():
    soup, _ = fetch_soup(URL1)
    tables = soup.find_all("table")
    rows_out = []
    n_parks = 0
    for t in tables:
        trs = t.find_all("tr")
        grid = [[c.get_text("|", strip=True) for c in tr.find_all(["td", "th"])] for tr in trs]
        header, *data = grid
        for r in data:
            if len(r) < 5:
                continue
            name_raw, muni_raw, area_raw, date_raw, note_raw = r[0], r[1], r[2], r[3], r[4]
            name = name_raw.replace("|", "")
            if name not in PARK_SLUG:
                continue  # 「箱根地域以外」「全面積」等の内訳行はスキップ(公園そのものの行ではない)
            slug, ccode, cja = PARK_SLUG[name]
            n_parks += 1
            muni = join_segments(muni_raw.split("|"))
            area_ha = num(area_raw)
            note_flat = note_raw.replace("|", "")
            zones = ZONE_RE.findall(note_flat)
            subs = SUB_RE.findall(note_flat)
            zone_note = ""
            if zones and any(z[0] == "特別地域" for z in zones) and subs:
                zone_note = ("特別地域の面積には地種区分の内訳(第1種・第2種・第3種特別地域や"
                             "「地種区分なし」)を含む場合があり、単純に地種区分ごとの面積を合計すると"
                             "二重計上になることがある(原文の備考欄をそのまま転記、内訳の調整はしていない)。")
            rows_out.append(rec(
                area_id=f"{SID1}_{slug}",
                name_ja=name, category_ja=cja, category_code=ccode,
                municipality_ja=muni, area_ha=area_ha, area_ha_raw=area_raw,
                designated_on=earliest_date(date_raw.replace("|", " ")),
                designated_on_raw=date_raw.replace("|", " "),
                lat=None, lon=None,
                note_ja=(f"指定・変更年月日(原文): {date_raw.replace('|', ' ')}。" + zone_note).strip(),
                source_id=SID1, source_ref=f"{URL1}#{slug}",
            ))
            for zname, zval in zones:
                zv = num(zval)
                rows_out.append(rec(
                    area_id=f"{SID1}_{slug}_zone_{zname}",
                    name_ja=f"{name} / {zname}", category_ja=zname,
                    category_code="natural_park_zoning", municipality_ja=muni,
                    area_ha=zv, area_ha_raw=f"{zval}ha",
                    designated_on=None, designated_on_raw=None, lat=None, lon=None,
                    note_ja=f"親公園: {name}（地種区分別面積の内訳。原文備考欄: {note_flat}）",
                    source_id=SID1, source_ref=f"{URL1}#{slug}:zone:{zname}",
                ))
            for sub_label, sub_val in subs:
                sv = num(sub_val)
                rows_out.append(rec(
                    area_id=f"{SID1}_{slug}_zone_sub_{sub_label}",
                    name_ja=f"{name} / 特別地域（うち{sub_label}）", category_ja=f"特別地域（うち{sub_label}）",
                    category_code="natural_park_zoning", municipality_ja=muni,
                    area_ha=sv, area_ha_raw=f"{sub_val}ha",
                    designated_on=None, designated_on_raw=None, lat=None, lon=None,
                    note_ja=f"親公園: {name}。特別地域の内数（地種区分が細分されていない部分）。",
                    source_id=SID1, source_ref=f"{URL1}#{slug}:zone_sub:{sub_label}",
                ))
    assert n_parks == 6, f"6公園のはずが{n_parks}件しか一致しなかった"
    write_csv_jsonl(SID1, rows_out)
    register(SID1, "県内の自然公園（指定状況一覧）", "神奈川県環境農政局",
             URL1, "protected_area", "http_html_table", "csv+jsonl",
             "神奈川県ホームページ利用規約(要確認、政府標準利用規約(CC-BY相当)準拠を想定)", 1, len(rows_out),
             "富士箱根伊豆国立公園・丹沢大山国定公園・県立自然公園4園、計6公園の名称・区域(市町村)・面積・"
             "指定/変更年月日・地種区分別面積(特別保護地区/第1〜3種特別地域/普通地域)をHTML本文の実表から抽出。"
             "既存の nlni_a10_natparks (国土数値情報A10自然公園地域、神奈川県、GISポリゴン21件) は "
             "OBJ_NAME 属性が全件空で公園名称を持たない(c32_nlni_a10.py 実装時に確認済み)。"
             "本ソースはその名称欠落を補完する位置づけとして取得した(ポリゴンとの空間結合はしていない)。"
             "地種区分別面積は親公園1行に収まらないため category_code='natural_park_zoning' の子レコードとして"
             "別行で出力(name_ja に親公園名を含める)。"
             "県立丹沢大山自然公園は「特別地域8,157ha」の内訳として「地種区分なし6,230ha」を含み、"
             "単純に地種区分ごとに合算すると二重計上になる注記あり(原文どおり転記、調整はしていない)。")
    return rows_out


# ======================================================================
# 2. kanagawa_green_conservation
# ======================================================================
SID2 = "kanagawa_green_conservation"
URL2 = "https://www.pref.kanagawa.jp/docs/t4i/cnt/f10578/index.html"

LINK_LABELS = {
    "rekishi": "歴史的風土保存地区の指定状況",
    "tokuryoku": "特別緑地保全地区の指定状況",
    "kinkou": "近郊緑地保全区域の指定状況",
    "fuuchi": "風致地区の指定状況",
}
EXCLUDE_LABEL = "自然環境保全地域の指定状況"  # CSV行27の担当。ここでは取得しない。

FUUCHI_SUFFIX = {"横浜": "市", "川崎": "市", "横須賀": "市", "平塚": "市", "鎌倉": "市", "藤沢": "市",
                 "小田原": "市", "逗子": "市", "三浦": "市",
                 "葉山": "町", "愛川": "町", "二宮": "町", "湯河原": "町", "大磯": "町"}

SUBTOTAL_RE = re.compile(r"^(?P<name>[^（(]+?)[\s　]*[（(](?P<count>[0-9０-９]+)\s*地区[）)]$")


def normalize_spaces(s):
    return re.sub(r"[\s　]+", "", s or "")


def discover_green_conservation_links():
    soup, _ = fetch_soup(URL2)
    found = {}
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        if EXCLUDE_LABEL in txt:
            continue
        for key, label in LINK_LABELS.items():
            if label in txt:
                href = a["href"]
                if href.startswith("/"):
                    href = "https://www.pref.kanagawa.jp" + href
                found[key] = (href, txt)
    missing = set(LINK_LABELS) - set(found)
    if missing:
        raise RuntimeError(f"入口HTMLからリンクを検出できなかった: {missing}")
    return found


def dl_pdf(key, url):
    dest = RAW / SID2 / pathlib.Path(url.rsplit("/", 1)[-1]).name
    download(url, dest)
    return dest


def build_rekishi(pdf_path, url):
    """歴史的風土保存区域(概数=約) + 歴史的風土特別保存地区。2段組の実表を1ページから抽出。"""
    with pdfplumber.open(str(pdf_path)) as pdf:
        rows = pdf.pages[0].find_tables()[0].extract()
    data = rows[2:]  # 先頭2行は見出し(カテゴリ大見出し + 列見出し)
    out = []
    cur_area = None
    n_area = n_dist = 0
    for r in data:
        city, area_name, area_size, area_date, dist_name, dist_size, dist_date = (r + [None] * 7)[:7]
        is_area_total = bool(area_name and area_name.strip().startswith("計"))
        is_dist_total = bool(dist_name and dist_name.strip().startswith("計"))
        if area_name and not is_area_total:
            n_area += 1
            city_ja = (city or "").replace("\n", "")
            area_date_flat = (area_date or "").replace("\n", " ")
            cur_area = {"name": area_name.replace("\n", ""), "city": city_ja}
            out.append(rec(
                area_id=f"{SID2}_rekishi_area_{n_area}",
                name_ja=cur_area["name"], category_ja="歴史的風土保存区域",
                category_code="historic_landscape", municipality_ja=city_ja,
                area_ha=num(area_size), area_ha_raw=area_size,
                designated_on=earliest_date(area_date_flat), designated_on_raw=area_date_flat,
                lat=None, lon=None,
                note_ja="面積は「約」を含む概数(原文表記のまま)。" + (
                    f"指定・変更年月日(原文): {area_date_flat}。" if area_date_flat else ""),
                source_id=SID2, source_ref=f"{url}#rekishi:area:{n_area}",
            ))
        if dist_name and not is_dist_total:
            n_dist += 1
            dist_date_flat = (dist_date or "").replace("\n", " ")
            parent = cur_area["name"] if cur_area else None
            parent_city = cur_area["city"] if cur_area else None
            out.append(rec(
                area_id=f"{SID2}_rekishi_district_{n_dist}",
                name_ja=dist_name.replace("\n", ""), category_ja="歴史的風土特別保存地区",
                category_code="historic_landscape_district", municipality_ja=parent_city,
                area_ha=num(dist_size), area_ha_raw=dist_size,
                designated_on=earliest_date(dist_date_flat), designated_on_raw=dist_date_flat,
                lat=None, lon=None,
                note_ja=f"親区域(歴史的風土保存区域): {parent}。指定・変更年月日(原文): {dist_date_flat}。",
                source_id=SID2, source_ref=f"{url}#rekishi:district:{n_dist}",
            ))
    return out


def build_tokuryoku(pdf_path, url):
    """特別緑地保全地区。複数ページ、市町村ごとの小計行(「鎌 倉 市 （11地区） 49.4」等)で
    区切られた個別地区の一覧。小計行と個別行の面積合計が一致することを確認済み(293地区/850.8ha)。"""
    all_rows = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pg in pdf.pages:
            for t in pg.find_tables():
                all_rows.extend(t.extract())
    group, records = [], []
    n = 0
    for r in all_rows:
        c0 = (r[0] or "").strip()
        if c0 == "地 区 名":
            continue
        if all((x is None or str(x).strip() == "") for x in r):
            continue
        if c0.startswith("合計"):
            continue
        m = SUBTOTAL_RE.match(c0)
        if m:
            muni = normalize_spaces(m.group("name"))
            for g in group:
                g["municipality_ja"] = muni
            records.extend(group)
            group = []
            continue
        name, area, desc, date = (r + [None] * 4)[:4]
        if not name:
            continue
        group.append({"name": name.replace("\n", ""), "area_raw": area,
                       "desc": (desc or "").replace("\n", ""), "date_raw": (date or "").replace("\n", " ")})
    out = []
    for g in records:
        n += 1
        out.append(rec(
            area_id=f"{SID2}_tokuryoku_{n}",
            name_ja=g["name"], category_ja="特別緑地保全地区", category_code="special_green",
            municipality_ja=g.get("municipality_ja"),
            area_ha=num(g["area_raw"]), area_ha_raw=g["area_raw"],
            designated_on=earliest_date(g["date_raw"]), designated_on_raw=g["date_raw"],
            lat=None, lon=None,
            note_ja=f"区域: {g['desc']}。指定・変更年月日(原文): {g['date_raw']}。",
            source_id=SID2, source_ref=f"{url}#tokuryoku:{n}",
        ))
    return out


def build_kinkou(pdf_path, url):
    """近郊緑地保全区域(7件・親) + 近郊緑地特別保全地区(10件・子)。2段組の実表。
    合計行「計７区域 4,800」「計１０地区 856.9」と個別行合計の一致を確認済み。"""
    with pdfplumber.open(str(pdf_path)) as pdf:
        rows = pdf.pages[0].find_tables()[0].extract()
    header1, header2, *data = rows
    out = []
    cur_parent = None
    n_area = n_dist = 0
    for r in data:
        name_l, area_l, muni_l, date_l, name_r, area_r, desc_r, date_r = (r + [None] * 8)[:8]
        if name_l and not name_l.strip().startswith("計"):
            n_area += 1
            muni = (muni_l or "").replace("\n", "・")
            date_flat = (date_l or "").replace("\n", " ")
            area_raw = (area_l or "").replace("\n", " / ")
            cur_parent = name_l.replace("\n", "")
            out.append(rec(
                area_id=f"{SID2}_kinkou_area_{n_area}",
                name_ja=cur_parent, category_ja="近郊緑地保全区域", category_code="suburban_green",
                municipality_ja=muni, area_ha=num(area_l), area_ha_raw=area_raw,
                designated_on=earliest_date(date_flat), designated_on_raw=date_flat,
                lat=None, lon=None,
                note_ja=(f"面積の原文に市町村別内訳の括弧書きがある場合は area_ha_raw に含む。"
                          f"指定・変更年月日(原文): {date_flat}。"),
                source_id=SID2, source_ref=f"{url}#kinkou:area:{n_area}",
            ))
        if name_r and not name_r.strip().startswith("計"):
            n_dist += 1
            date_flat = (date_r or "").replace("\n", " ")
            out.append(rec(
                area_id=f"{SID2}_kinkou_district_{n_dist}",
                name_ja=name_r.replace("\n", ""), category_ja="近郊緑地特別保全地区",
                category_code="suburban_green_district", municipality_ja=None,
                area_ha=num(area_r), area_ha_raw=area_r,
                designated_on=earliest_date(date_flat), designated_on_raw=date_flat,
                lat=None, lon=None,
                note_ja=(f"親区域(近郊緑地保全区域): {cur_parent}。区域: {(desc_r or '').replace(chr(10), '')}。"
                          f"指定・変更年月日(原文): {date_flat}。"),
                source_id=SID2, source_ref=f"{url}#kinkou:district:{n_dist}",
            ))
    return out


def build_fuuchi(pdf_path, url):
    """風致地区。市町名は forward-fill (同一市町の2件目以降は空欄になる表組み)。
    「県全体9市5町(51地区) 14,977.5」と個別行合計の一致を確認済み。"""
    with pdfplumber.open(str(pdf_path)) as pdf:
        rows = pdf.pages[0].find_tables()[0].extract()
    header, *data = rows
    out = []
    cur_muni = None
    n = 0
    for r in data:
        muni, name, area, desc, date = (r + [None] * 5)[:5]
        if muni:
            cur_muni = muni.strip()
        if cur_muni and cur_muni.startswith("県全体"):
            continue  # 合計行
        if not name or name.strip().startswith("（"):
            continue  # 市町ごとの小計行(「（１６地区） 3,710.0 〔第1種...〕」)
        n += 1
        muni_ja = cur_muni + FUUCHI_SUFFIX.get(cur_muni, "") if cur_muni else None
        date_flat = (date or "").replace("\n", " ")
        out.append(rec(
            area_id=f"{SID2}_fuuchi_{n}",
            name_ja=name.strip(), category_ja="風致地区", category_code="scenic_district",
            municipality_ja=muni_ja, area_ha=num(area), area_ha_raw=area,
            designated_on=earliest_date(date_flat), designated_on_raw=date_flat,
            lat=None, lon=None,
            note_ja=f"区域: {(desc or '').replace(chr(10), '')}。指定・変更年月日(原文): {date_flat}。"
                     "第1種〜第4種の種別区分は平成11年4月1日施行の条例改正による(市町単位の内訳は原PDF参照、"
                     "地区単位には配分されていないため本レコードには含めていない)。",
            source_id=SID2, source_ref=f"{url}#fuuchi:{n}",
        ))
    return out


def build_green_conservation():
    links = discover_green_conservation_links()
    for key, (url, label) in links.items():
        print(f"  [{SID2}] {key}: {label!r} -> {url}")
    paths = {key: dl_pdf(key, url) for key, (url, _) in links.items()}

    rows_out = []
    rows_out += build_rekishi(paths["rekishi"], links["rekishi"][0])
    rows_out += build_tokuryoku(paths["tokuryoku"], links["tokuryoku"][0])
    rows_out += build_kinkou(paths["kinkou"], links["kinkou"][0])
    rows_out += build_fuuchi(paths["fuuchi"], links["fuuchi"][0])

    write_csv_jsonl(SID2, rows_out)
    by_cat = collections.Counter(r["category_code"] for r in rows_out)
    cat_summary = " / ".join(f"{k}:{v}件" for k, v in by_cat.items())
    register(SID2, "かながわのみどりの保全（指定状況PDF4種）", "神奈川県環境農政局",
             URL2, "protected_area", "http_html_pdf_table", "csv+jsonl",
             "神奈川県ホームページ利用規約(要確認、政府標準利用規約(CC-BY相当)準拠を想定)", 1, len(rows_out),
             f"入口HTML({URL2})から歴史的風土保存地区/特別緑地保全地区/近郊緑地保全区域/風致地区の4指定状況PDFの"
             "リンクをラベル文言で動的に取得(ファイル名は変わりうるため。実際に "
             "tokuryoku2025.pdf は「特別緑地保全地区」9ページ380KB、kinryoku2025.pdf は「近郊緑地保全区域」"
             "1ページ91KBを指しており、ソース依頼メモに書かれていたファイル名と指す内容が入れ替わっていることを"
             "確認した。ラベル文言のみで判定し、ファイル名は判定に使っていない)。"
             "各表の市町村・市町別の小計/合計行と個別行の面積合計が一致することを確認済み"
             "(歴史的風土特別保存地区13地区573.6ha、特別緑地保全地区293地区850.8ha、"
             "近郊緑地保全区域7区域4,800ha、近郊緑地特別保全地区10地区856.9ha、風致地区51地区14,977.5ha)。"
             "「自然環境保全地域の指定状況」PDFは別タスク(CSV行27)の担当のため取得していない。"
             f"内訳: {cat_summary}。"
             "※風致地区PDF原文注記: 「第１種～第４種の種別は条例改正（平成１１年４月１日施行）による」"
             "「※変更は直近のもの」(=変更年月日列は最新の変更のみを示し、過去の変更履歴は列挙されていない回がある。"
             "時系列比較の際は「変更年月日=最新の1件のみ」である点に注意)。")
    return rows_out


# ======================================================================
# 3. hiratsuka_parks
# ======================================================================
SID3 = "hiratsuka_parks"
URL3 = "https://www.city.hiratsuka.kanagawa.jp/common/200204844.csv"


def read_csv_autodetect(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(enc)
            rows = list(csv.reader(text.splitlines()))
            if rows and len(rows[0]) > 3:
                return rows, enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"encoding detection failed for {path}")


def build_hiratsuka_parks():
    dest = RAW / SID3 / "200204844.csv"
    download(URL3, dest)
    rows, enc = read_csv_autodetect(dest)
    header, *data = rows
    print(f"  [{SID3}] encoding={enc} n_cols={len(header)} n_rows={len(data)}")

    # 原データの全列をそのまま別ファイルでも保存(アメニティ列等は共通列に無いため)
    full_path = PROC / "hiratsuka_parks_full.csv"
    with open(full_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print(f"  [write] {full_path.relative_to(ROOT)}  {len(data)} rows (全{len(header)}列そのまま保存)")

    idx = {name: i for i, name in enumerate(header)}
    out = []
    for row in data:
        park_no = row[0].strip()
        lon = num(row[idx["経度"]])
        lat = num(row[idx["緯度"]])
        name = row[idx["公園名"]].strip()
        addr = row[idx["所在地"]].strip()
        start_year = row[idx["提供開始年"]].strip()
        area_m2_raw = row[idx["面積（平方m）"]].strip()
        park_type = row[idx["公園種別"]].strip()
        area_m2 = num(area_m2_raw)
        area_ha = round(area_m2 / 10000, 4) if area_m2 is not None else None
        out.append(rec(
            area_id=f"{SID3}_{park_no}",
            name_ja=name, category_ja=park_type, category_code="city_park",
            municipality_ja="平塚市",
            area_ha=area_ha, area_ha_raw=f"{area_m2_raw}㎡",
            designated_on=None, designated_on_raw=start_year,
            lat=lat, lon=lon,
            note_ja=(f"面積は原データの㎡表記からhaに換算(÷10000)。所在地: {addr}。"
                     f"「提供開始年」({start_year}年)は原データの列名どおりで、都市計画法等に基づく"
                     "法的な指定年月日ではない可能性があるため designated_on は null にし、"
                     "designated_on_raw に原値のみ残した。アメニティ等の原列(トイレ有無など)は "
                     "data/processed/hiratsuka_parks_full.csv に全列そのまま保存。"),
            source_id=SID3, source_ref=f"{URL3}#row={park_no}",
        ))
    write_csv_jsonl(SID3, out)
    register(SID3, "平塚市オープンデータ 公園一覧", "平塚市",
             URL3, "city_facility", "http_csv", "csv+jsonl",
             "平塚市オープンデータ利用規約(要確認、CC-BY相当を想定)", 1, len(out),
             f"原CSVは54列・実測{len(data)}件({enc})。文字コードはUTF-8/Shift-JISが不定のため自動判定。"
             "経度・緯度・公園名・所在地・提供開始年・面積(㎡)・公園種別に加え、トイレ等アメニティ列多数を持つが、"
             "共通列に載らない原列は data/processed/hiratsuka_parks_full.csv に全列そのまま別保存した。"
             "面積は㎡からhaに換算(÷10000)。")
    return out


# ======================================================================
# 4. hadano_preserved_trees
# ======================================================================
SID4 = "hadano_preserved_trees"
URL4 = "https://www.city.hadano.kanagawa.jp/material/files/group/6/142115_preserve_tree.csv"


def build_hadano_trees():
    dest = RAW / SID4 / "142115_preserve_tree.csv"
    download(URL4, dest)
    with open(dest, encoding="utf-8-sig", newline="") as f:
        data = list(csv.DictReader(f))
    print(f"  [{SID4}] n_rows={len(data)}")

    n_latlon = sum(1 for row in data if row["緯度"].strip() or row["経度"].strip())
    out = []
    for row in data:
        no = row["NO"].strip()
        species = row["樹種"].strip()
        desig_no = row["指定番号"].strip()
        addr = row["住所"].strip()
        katagaki = row["方書"].strip()
        bikou = row["備考"].strip()
        lat = num(row["緯度"]) if row["緯度"].strip() else None
        lon = num(row["経度"]) if row["経度"].strip() else None
        addr_full = addr + (f"（{katagaki}）" if katagaki else "")
        note = bikou if bikou else addr_full  # 備考が空のため住所を代わりに保持(樹種名は入れない)
        out.append(rec(
            area_id=f"{SID4}_{no}",
            name_ja=f"{species}（指定{desig_no}号）", category_ja="保存樹木",
            category_code="preserved_tree", municipality_ja=row["市区町村名"].strip(),
            area_ha=None, area_ha_raw=None,
            designated_on=None, designated_on_raw=None,
            lat=lat, lon=lon,
            note_ja=note,
            source_id=SID4, source_ref=f"{URL4}#NO={no}",
        ))
    write_csv_jsonl(SID4, out)
    register(SID4, "秦野市 保存樹木一覧", "秦野市",
             URL4, "biodiversity_designation", "http_csv", "csv+jsonl",
             "秦野市オープンデータ利用規約(要確認、CC-BY相当を想定)", 1, len(out),
             f"UTF-8(BOM付)・実測{len(out)}件。列=市区町村コード/NO/都道府県名/市区町村名/樹種/住所/方書/"
             "緯度/経度/指定番号/備考。"
             f"緯度・経度列は全{len(out)}行とも空欄({n_latlon}行のみ値あり)で、位置情報が無い。"
             "指定年月日にあたる列も原データに存在しない(指定番号[1件の指定に複数樹木が対応することがある"
             "グループ番号]のみ)。数値を推測で埋めないため、lat/lon/designated_on はすべて null とした。"
             "備考列は全行空欄だったため、note_ja には代わりに住所(+方書)を入れた(樹種はname_ja側)。")
    return out


# ======================================================================
# 出力ヘルパ・結合ファイル
# ======================================================================
def write_csv_jsonl(source_id, rows):
    write_jsonl(source_id, rows)
    p = PROC / f"{source_id}.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else COMMON_COLS)
        w.writeheader()
        w.writerows(rows)
    print(f"  [write] {p.relative_to(ROOT)}  {len(rows)} rows")


def write_combined(all_rows):
    """4ソース縦結合。列は共通列のみ(ソース固有の追加列は落とす)。"""
    combined = [{k: r.get(k) for k in COMMON_COLS} for r in all_rows]
    write_jsonl("green_areas_all", combined)
    p = PROC / "green_areas_all.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COMMON_COLS)
        w.writeheader()
        w.writerows(combined)
    print(f"  [write] {p.relative_to(ROOT)}  {len(combined)} rows")


if __name__ == "__main__":
    all_rows = []
    print(f"=== {SID1} ===")
    all_rows += build_natural_parks()
    print(f"=== {SID2} ===")
    all_rows += build_green_conservation()
    print(f"=== {SID3} ===")
    all_rows += build_hiratsuka_parks()
    print(f"=== {SID4} ===")
    all_rows += build_hadano_trees()

    print("=== combined ===")
    write_combined(all_rows)

    by_source = collections.Counter(r["source_id"] for r in all_rows)
    print(f"\nTOTAL {len(all_rows)} rows")
    for sid, n in by_source.items():
        print(f"  {sid}: {n}")
