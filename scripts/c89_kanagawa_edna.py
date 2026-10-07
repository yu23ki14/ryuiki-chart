#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県「環境DNAのページ」eDNA 調査結果（R3〜R7、xlsx 9本）を長持ちの CSV にする。

設計: docs/plans/KANAGAWA_EDNA.md §1・§2.1・§2.2。入口は
https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html 。xlsx のリンクは HTML から
動的に拾う（ファイル名は当てにしない。c81 と同じ流儀）。取得した raw は
data/raw/kanagawa_edna/ に置く（edna.html・xlsx・利用規約PDF）。

出力（data/processed/）:
  kanagawa_edna_sites.csv  … 地点（= ファイル × 調査地点列）。座標は持たない（台帳 data/edna/ が持つ）。
  kanagawa_edna_reads.csv  … 種 × 地点の全セル（リード数 0 の不検出も含む）。

--- 読み方 ---
- xlsx は openpyxl を使わず標準ライブラリ（zipfile + xml.etree）で読む。理由: ① CI の requirements.txt は
  PyYAML・pytest だけで、依存を増やさない。② 共有文字列のふりがな（<rPh>）を本体と分けて読む必要があり、
  openpyxl は rPh を捨てるので「原文（ふりがな連結）と本体」の両方を持てない。③ 数式・エラー・巨大セルを
  値として読まない制御が要る。入力は信頼しない:
  数式セル・エラーセル・外部参照は値として読まない（無視して件数を数える）、巨大セルは無視、
  解凍サイズに上限、シートは1枚目（種×地点の本体）だけ。
- 共有文字列のふりがな（<rPh>）は「同じ文字列がカタカナで連結」して見える元。本体の文字（<t>）と
  ふりがな（<rPh>/<t>）を分けて読み、`*_raw` は連結した原文、`*_ja` は本体だけにする。
  本体にそのまま連結されていた場合は、**同じブックの既知の名前との前方一致でだけ**外す
  （一致しなければ raw のまま。推測で切らない）。
- レイアウトはファイル名ごとの宣言表 LAYOUTS（ヘッダ行・列・地点列の範囲・日付形式・期待値）で持ち、
  ヘッダ文字列を突き合わせて食い違えば止まる（列の位置を黙って信じない）。リンクに未知の
  r<年度>_ で始まる .xlsx が増えたときも止まる（レイアウトを推測しない）。
- r6_kenmin_mtinsects_amphi は列が1つ右にずれる（A 列が分類「脊椎動物/無脊椎動物」）。
  r7_kenmin_kekka は「98.5%以上の一致のみ」の絞り込み版（LAYOUTS の dataset_filter。m07 が attributes に載せる）。
"""
import sys, re, csv, json, hashlib, zipfile, unicodedata, datetime, urllib.parse, collections
import pathlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).parent))
# name_key の正は c89c（二重実装しない。c89c は reads と突き合わせて食い違えば止まる）
from c89c_edna_taxon_map import name_key, write_csv  # noqa: E402

SOURCE_ID = "kanagawa_edna"
INDEX_URL = "https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html"
PUBLISHER = "神奈川県 環境農政局 環境部 水・大気環境課"
# registry/source/license.yaml の既存の raw と同じ文字列（license.yaml は触らない。設計 §0）
LICENSE = ("神奈川県サイトポリシー（出典記載により利用可／書籍転載等の二次的利用は所管所属へ事前問合せ）: "
           "https://www.pref.kanagawa.jp/master/sitepolicy.html")
ATTRIBUTION = ("神奈川県ホームページ『環境ＤＮＡのページ』"
               "（https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html）を加工して作成")

# 入力の上限（信頼しない入力への備え）
MAX_ZIP_MEMBER_BYTES = 200 * 1024 * 1024
MAX_CELL_CHARS = 1000
MAX_ROW = 5000
MAX_COL = 400

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

KATAKANA_RUN = re.compile(r"^[゠-ヿㇰ-ㇿ・ー]+$")
SITE_ID_ROW_LABEL = "調査地点ID"


class LayoutError(RuntimeError):
    """レイアウトが宣言と食い違った。黙って進まず止める。"""


# ---------------------------------------------------------------------------
# 1) xlsx を標準ライブラリだけで読む
# ---------------------------------------------------------------------------
def col2n(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def n2col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_member(z, name):
    info = z.getinfo(name)
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise LayoutError(f"{name}: 解凍サイズが上限超過 ({info.file_size})")
    return z.read(name)


@dataclass
class Sheet:
    """1枚目のシート。cells[(row, col_letter)] = str | int | float。
    str はふりがな（<rPh>）を除いた本体。phon[(row,col)] はふりがな。"""
    cells: dict = field(default_factory=dict)
    phon: dict = field(default_factory=dict)
    formula_cells: set = field(default_factory=set)   # 数式セル（値は読まない）
    error_cells: dict = field(default_factory=dict)   # '#N/A' 等（値は読まない）
    oversize_cells: set = field(default_factory=set)  # 巨大セル（無視）
    max_row: int = 0

    def get(self, row, col):
        return self.cells.get((row, col))

    def raw(self, row, col):
        """ふりがなを連結した原文（セルが見せていた文字列）。"""
        v = self.cells.get((row, col))
        if isinstance(v, str):
            return v + self.phon.get((row, col), "")
        return v


def _si_parts(si):
    """<si> から (本体, ふりがな) を返す。rPh の <t> は本体に混ぜない。"""
    base, phon = [], []
    for ch in si:
        tag = ch.tag
        if tag == NS + "t":
            base.append(ch.text or "")
        elif tag == NS + "r":
            for t in ch.findall(NS + "t"):
                base.append(t.text or "")
        elif tag == NS + "rPh":
            for t in ch.findall(NS + "t"):
                phon.append(t.text or "")
    return "".join(base), "".join(phon)


def _num(text):
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return float(text)


def load_xlsx(path):
    """xlsx の1枚目を Sheet にする。数式・エラー・巨大セルは値を読まない。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        # 1枚目のシートのパス（workbook.xml の先頭 sheet → rels）
        wb = ET.fromstring(_read_member(z, "xl/workbook.xml"))
        sheets = wb.find(NS + "sheets")
        if sheets is None or not len(sheets):
            raise LayoutError(f"{path}: シートが無い")
        rid = sheets[0].get(NS_REL + "id")
        rels = ET.fromstring(_read_member(z, "xl/_rels/workbook.xml.rels"))
        target = None
        for r in rels.findall(NS_PKG_REL + "Relationship"):
            if r.get("Id") == rid:
                target = r.get("Target")
        if not target or target.startswith("/") or ".." in target or "://" in target:
            raise LayoutError(f"{path}: 1枚目のシートの参照が読めない ({target!r})")
        sheet_path = "xl/" + target
        if sheet_path not in names:
            raise LayoutError(f"{path}: {sheet_path} が無い")

        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(_read_member(z, "xl/sharedStrings.xml")):
                shared.append(_si_parts(si))
        root = ET.fromstring(_read_member(z, sheet_path))

    sh = Sheet()
    for c in root.iter(NS + "c"):
        m = re.fullmatch(r"([A-Z]{1,3})(\d{1,7})", c.get("r") or "")
        if not m:
            raise LayoutError(f"{path}: 不正なセル参照 {c.get('r')!r}")
        col, row = m.group(1), int(m.group(2))
        if row > MAX_ROW or col2n(col) > MAX_COL:
            continue
        key = (row, col)
        sh.max_row = max(sh.max_row, row)
        if c.find(NS + "f") is not None:
            sh.formula_cells.add(key)           # 数式は読まない（キャッシュ値も使わない）
            continue
        t = c.get("t")
        v = c.find(NS + "v")
        if t == "inlineStr":
            is_ = c.find(NS + "is")
            if is_ is None:
                continue
            base, phon = _si_parts(is_)
        elif v is None or v.text is None:
            continue
        elif t == "s":
            base, phon = shared[int(v.text)]
        elif t == "e":
            sh.error_cells[key] = v.text
            continue
        elif t in ("str", "b"):
            base, phon = v.text, ""
        else:                                    # 数値（t 省略 / "n"）
            try:
                sh.cells[key] = _num(v.text)
            except ValueError:
                raise LayoutError(f"{path}: {c.get('r')} が数値として読めない ({v.text!r})")
            continue
        if len(base) + len(phon) > MAX_CELL_CHARS:
            sh.oversize_cells.add(key)
            continue
        if base != "":
            sh.cells[key] = base
            if phon:
                sh.phon[key] = phon
    return sh


# ---------------------------------------------------------------------------
# 2) レイアウトの宣言表
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Layout:
    file: str
    program: str            # 'kenmin' / 'project'
    assay: str              # 'fish_12S' / 'insects_16S' / 'insects_amphibians' / 'all_taxa'
    fiscal_year: int
    hdr_row: int            # 種の表の列見出しの行
    first_data_row: int
    site_first: str         # 地点列の範囲（両端を含む）
    site_last: str
    cols: dict              # field → 列。class/order/family/genus/name_raw/name_adopted/
                            #   name_sci/name_note/pident/reliability/national_rl/pref_rl/alien
    checks: tuple           # ((セル, 本体文字列の前方一致), ...)。ずれたら止める
    expect_sites: int
    expect_last_data_row: int
    expect_detected: int    # 検出セル数（リード数 > 0）
    expect_cells: int       # 全セル数（0 を含む）
    # 地点ヘッダの行（全ファイル共通。ずれるファイルが出たら個別に上書きする）
    rows: dict = field(default_factory=lambda: dict(year=1, id=2, water=3, trib=4, muni=5, date=6))
    date_kind: str = "serial"   # 'serial'（Excel シリアル値）/ 'yyyymmdd'
    dataset_filter: str = ""


def _fish(file, program, fy, last_site, sites, last_row, detected, cells):
    return Layout(
        file=file, program=program, assay="fish_12S", fiscal_year=fy, hdr_row=6, first_data_row=7,
        site_first="H", site_last=last_site,
        cols=dict(**{"class": "A", "order": "B", "family": "C", "genus": "D", "name_raw": "E",
                     "name_adopted": "E", "national_rl": "F", "pref_rl": "G"}),
        checks=(("A6", "綱"), ("B6", "目"), ("C6", "科"), ("D6", "属"), ("E6", "種名"), ("F6", "国RL"),
                ("G6", "↓県RDB"), ("G1", "調査年度"), ("G2", "調査地点ID"), ("G3", "水系"),
                ("G4", "支川名"), ("G5", "関係市町村")),
        expect_sites=sites, expect_last_data_row=last_row, expect_detected=detected, expect_cells=cells)


_COMMON_CHK_R5 = (("A6", "綱"), ("B6", "目"), ("C6", "科"), ("D6", "属"), ("E6", "参考"),
                  ("F6", "種名(手動精査結果)"), ("G6", "MAX(pident*qcovs)"), ("H6", "信頼度"),
                  ("I6", "国RL"), ("L6", "地方自治体RL"), ("M6", "特定外来種"), ("N6", "調査日"),
                  ("N1", "調査年度"), ("N2", "調査地点ID"), ("N3", "水系"), ("N4", "支川名"),
                  ("N5", "関係市町村"))

LAYOUTS = {l.file: l for l in (
    _fish("r3_kenmin_gyorui.xlsx", "kenmin", 2021, "Q", 10, 47, 114, 410),
    _fish("r4_kenmin_gyorui.xlsx", "kenmin", 2022, "AD", 23, 59, 295, 1219),
    _fish("r5_kenmin_gyorui.xlsx", "kenmin", 2023, "AA", 20, 62, 236, 1120),
    _fish("r5_project_gyorui.xlsx", "project", 2023, "AN", 33, 79, 543, 2409),
    Layout(
        file="r5_kenmin_mtinsects-16s.xlsx", program="kenmin", assay="insects_16S", fiscal_year=2023,
        hdr_row=6, first_data_row=7, site_first="O", site_last="AG",
        cols={"class": "A", "order": "B", "family": "C", "genus": "D", "name_raw": "E",
              "name_adopted": "F", "pident": "G", "reliability": "H", "national_rl": "I",
              "pref_rl": "L", "alien": "M"},
        checks=_COMMON_CHK_R5, expect_sites=19, expect_last_data_row=621, expect_detected=1617, expect_cells=11685),
    Layout(
        # 列が1つ右にずれる（A 列が分類「脊椎動物/無脊椎動物」）。AB 列は数式の合計列（読まない）
        file="r6_kenmin_mtinsects_amphi.xlsx", program="kenmin", assay="insects_amphibians",
        fiscal_year=2024, hdr_row=6, first_data_row=7, site_first="P", site_last="AA",
        cols={"class": "B", "order": "C", "family": "D", "genus": "E", "name_raw": "F",
              "name_adopted": "G", "pident": "H", "reliability": "I", "national_rl": "J",
              "pref_rl": "M", "alien": "N"},
        checks=(("A1", "分類"), ("B6", "綱"), ("C6", "目"), ("D6", "科"), ("E6", "属"), ("F6", "参考"),
                ("G6", "種名(手動精査結果)"), ("H6", "MAX(pident*qcovs)"), ("I6", "信頼度"),
                ("J6", "国RL"), ("M6", "地方自治体RL"), ("N6", "特定外来種"), ("O6", "調査日"),
                ("O1", "調査年度"), ("O2", "調査地点ID"), ("O3", "水系"), ("O4", "支川名"),
                ("O5", "関係市町村")),
        expect_sites=12, expect_last_data_row=487, expect_detected=965, expect_cells=5772),
    Layout(
        # 地点ヘッダが縦5行。M 列にも別の見出し（調査ID/水系/支川名/調査日/調査時刻）があるが、
        # 値の行と対応するのは N 列（調査年度/調査地点ID/水系/支川名/関係市町村）の方
        file="r6_project_mtinsects-amphi.xlsx", program="project", assay="insects_amphibians",
        fiscal_year=2024, hdr_row=6, first_data_row=7, site_first="O", site_last="BM",
        cols={"class": "A", "order": "B", "family": "C", "genus": "D", "name_raw": "E",
              "name_adopted": "F", "pident": "G", "reliability": "H", "national_rl": "I",
              "pref_rl": "L", "alien": "M"},
        checks=(("A6", "綱"), ("B6", "目"), ("C6", "科"), ("D6", "属"), ("E6", "参考"),
                ("F6", "種名(手動精査結果)"), ("G6", "MAX(pident*qcovs)"), ("H1", "信頼度"),
                ("I1", "国RL"), ("L1", "神奈川県RL"), ("M6", "↓特定外来種"), ("N6", "調査日"),
                ("N1", "調査年度"), ("N2", "調査地点ID"), ("N3", "水系"), ("N4", "支川名"),
                ("N5", "関係市町村")),
        expect_sites=51, expect_last_data_row=818, expect_detected=4469, expect_cells=41412),
    Layout(
        # 「98.5%以上の一致のみ」の絞り込み版。信頼度・pident の列は無い。種和名＋学名
        file="r7_kenmin_kekka.xlsx", program="kenmin", assay="all_taxa", fiscal_year=2025,
        hdr_row=7, first_data_row=8, site_first="K", site_last="W",
        cols={"class": "A", "order": "B", "family": "C", "genus": "D", "name_raw": "E",
              "name_adopted": "F", "name_sci": "G", "national_rl": "H", "pref_rl": "I", "alien": "J"},
        checks=(("A7", "綱"), ("B7", "目"), ("C7", "科"), ("D7", "属"), ("E7", "(参考)種名"),
                ("F7", "種和名"), ("G7", "学名"), ("H7", "国RL"), ("I7", "地方自治体RL"),
                ("J7", "特定外来種"), ("J1", "調査年度"), ("J2", "調査地点ID"), ("J3", "水系"),
                ("J4", "支川名"), ("J5", "関係市町村"), ("J6", "調査日")),
        expect_sites=13, expect_last_data_row=349, expect_detected=625, expect_cells=4446,
        dataset_filter="match>=98.5%"),
    Layout(
        # 地点ヘッダは P 列のラベルに対する Q 列以降。調査日は YYYYMMDD
        file="r7_project_kekka.xlsx", program="project", assay="all_taxa", fiscal_year=2025,
        hdr_row=1, first_data_row=8, site_first="Q", site_last="DB",
        date_kind="yyyymmdd",
        cols={"class": "A", "order": "B", "family": "C", "genus": "D", "name_raw": "E",
              "name_adopted": "F", "name_sci": "G", "name_note": "H", "pident": "I",
              "reliability": "J", "national_rl": "K", "pref_rl": "N", "alien": "O"},
        checks=(("A1", "綱"), ("B1", "目"), ("C1", "科"), ("D1", "属"), ("E1", "種名(機械的な併記処理)"),
                ("F1", "種名(手動精査結果)"), ("G1", "学名"), ("H1", "注釈"), ("I1", "MAX(pident*qcovs)"),
                ("J1", "信頼度"), ("K1", "国RL"), ("N1", "地方自治体RL"), ("O1", "特定外来種"),
                ("P1", "調査年度"), ("P2", "調査ID"), ("P3", "水系名"), ("P4", "支川名"),
                ("P5", "関係市町村"), ("P6", "調査日")),
        expect_sites=90, expect_last_data_row=740, expect_detected=4399, expect_cells=65970),
)}

# 解析対象でないことが分かっている xlsx（サンプル情報。種×地点の表ではない）
KNOWN_IGNORED_XLSX = re.compile(r"^(insecta_|16s_28s_)")
TARGET_XLSX = re.compile(r"^r\d+_")


# ---------------------------------------------------------------------------
# 3) 値の整形
# ---------------------------------------------------------------------------
def clean(v):
    """前後空白（全角含む）を除く。空は None。"""
    if v is None:
        return None
    s = str(v).replace("　", " ").strip()
    return s or None


def dash_none(v):
    """階級列の '-' は NULL。"""
    s = clean(v)
    return None if s in (None, "-", "－", "―") else s


def excel_serial_to_iso(n):
    return (datetime.date(1899, 12, 30) + datetime.timedelta(days=int(n))).isoformat()


def parse_date(value, kind):
    """(iso | None, raw | None)。空は (None, None)。形式が宣言と違えば止める（補わない）。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if kind == "serial":
        if isinstance(value, float) and value == int(value):
            value = int(value)
        if not isinstance(value, int) or not (40000 <= value <= 50000):
            raise LayoutError(f"採水日がシリアル値でない: {value!r}")
        return excel_serial_to_iso(value), str(value)
    if kind == "yyyymmdd":
        s = str(int(value)) if isinstance(value, (int, float)) else str(value).strip()
        if not re.fullmatch(r"\d{8}", s):
            raise LayoutError(f"採水日が YYYYMMDD でない: {value!r}")
        try:
            d = datetime.date(int(s[:4]), int(s[4:6]), int(s[6:]))
        except ValueError:
            raise LayoutError(f"採水日が暦にない日付: {value!r}")
        return d.isoformat(), s
    raise LayoutError(f"未知の date_kind {kind}")


BRACKET = re.compile(r"[（(][^（）()]*[）)]")


def bracket_notes(s):
    """括弧書き（全角・半角）を原文のまま取り出す。"""
    return BRACKET.findall(s or "")


def build_known_names(sheet, row_ids):
    """同じブックの「ふりがな付きだった地点ヘッダ」の本体 = 既知の名前。"""
    known = set()
    for (r, c), p in sheet.phon.items():
        if r in row_ids:
            known.add(sheet.cells[(r, c)])
    return known


def split_furigana(body, phon, known):
    """(raw, ja, 本体に連結されていたのを外したか)。
    raw = セルが見せていた原文（本体 + ふりがな）。
    ja  = ふりがなを外した値。<rPh> で分けて読めたものはそのまま本体。
          本体にカタカナが直に連結されていた場合だけ、既知名との前方一致で外す。
          一致しなければ raw のまま（推測で切らない）。"""
    if body is None:
        return None, None, False
    raw = body + (phon or "")
    if phon:
        return raw, body, False
    if body in known:
        return raw, body, False
    for k in sorted(known, key=len, reverse=True):
        if body.startswith(k) and len(body) > len(k) and KATAKANA_RUN.match(body[len(k):]):
            return raw, k, True
    return raw, body, False


# ---------------------------------------------------------------------------
# 4) 1ブックを読む
# ---------------------------------------------------------------------------
def check_headers(sheet, lay):
    for ref, prefix in lay.checks:
        m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
        got = sheet.get(int(m.group(2)), m.group(1))
        got = unicodedata.normalize("NFKC", got).replace(" ", "") if isinstance(got, str) else got
        want = unicodedata.normalize("NFKC", prefix).replace(" ", "")
        if not (isinstance(got, str) and got.startswith(want)):
            raise LayoutError(f"{lay.file}: ヘッダ {ref} が宣言と違う（期待 {prefix!r} で始まる / 実際 {got!r}）。"
                              f"列の位置が変わった可能性がある。LAYOUTS を確かめる")


def check_site_columns(sh, lay):
    """地点列の範囲の外に地点が増えていないこと・範囲の内側が全部地点であること。(地点列のリスト) を返す。"""
    first, last = col2n(lay.site_first), col2n(lay.site_last)
    R = lay.rows
    for extra in (n2col(last + 1), n2col(last + 2)):
        for key in ("id", "water", "trib", "muni", "year"):
            if sh.get(R[key], extra) is not None:
                raise LayoutError(f"{lay.file}: 宣言した地点列の範囲（{lay.site_first}〜{lay.site_last}）の"
                                  f"右 {extra}{R[key]} に値がある。地点列が増えた可能性がある")
    cols = [n2col(i) for i in range(first, last + 1)]
    for c in cols:
        if sh.get(R["id"], c) is None:
            raise LayoutError(f"{lay.file}: 地点列 {c}{R['id']} に地点IDが無い")
    return cols


def find_data_rows(sh, lay):
    """データ行 = first_data_row から名前列が空になる直前まで（その下は凡例・集計）。検査も行う。"""
    name_col = lay.cols["name_adopted"]
    rows = []
    r = lay.first_data_row
    while sh.get(r, name_col) is not None and r <= MAX_ROW:
        rows.append(r)
        r += 1
    if not rows:
        raise LayoutError(f"{lay.file}: データ行が無い")
    if lay.expect_last_data_row and rows[-1] != lay.expect_last_data_row:
        raise LayoutError(f"{lay.file}: データ末尾行が宣言と違う（期待 {lay.expect_last_data_row} / 実際 {rows[-1]}）")
    for r in rows:      # レイアウトの綱列そのものを見る（凡例が紛れる・列がずれると空になる）
        if sh.get(r, lay.cols["class"]) is None:
            raise LayoutError(f"{lay.file}: {r} 行の綱（{lay.cols['class']} 列）が空")
    return rows


def check_no_unreadable_cells(sh, lay, data_rows):
    """地点のヘッダ・本体に数式/エラー/巨大セル（値を読まない種類）があれば止める。"""
    first, last = col2n(lay.site_first), col2n(lay.site_last)
    header_rows = set(lay.rows.values()) | {lay.hdr_row}
    bad = [k for k in sh.formula_cells | set(sh.error_cells) | sh.oversize_cells
           if (k[0] in header_rows or lay.first_data_row <= k[0] <= data_rows[-1]) and first <= col2n(k[1]) <= last]
    if bad:
        raise LayoutError(f"{lay.file}: 地点のヘッダ・本体に数式/エラー/巨大セルがある: {sorted(bad)[:5]}")


def parse_sites(sh, lay, site_cols, source_ref_base):
    """(地点の行のリスト, ふりがなを fallback で外した件数)。"""
    R = lay.rows
    stem = pathlib.Path(lay.file).stem
    known = build_known_names(sh, {R["water"], R["trib"], R["muni"]})
    fallback, sites, seen = 0, [], set()
    for c in site_cols:
        yr = sh.get(R["year"], c)
        m = re.match(r"(\d{4})年度", yr) if isinstance(yr, str) else None
        if not m or int(m.group(1)) != lay.fiscal_year:
            raise LayoutError(f"{lay.file}: {c}{R['year']} の年度が {lay.fiscal_year} でない ({yr!r})")
        sid = clean(sh.get(R["id"], c))
        if sid is None:
            raise LayoutError(f"{lay.file}: {c}{R['id']} の地点IDが空")
        site_key = f"{stem}:{sid}"
        if site_key in seen:
            raise LayoutError(f"{lay.file}: 地点IDが重複 {site_key}")
        seen.add(site_key)
        rec = {"site_key": site_key, "dataset_file": lay.file, "program": lay.program,
               "assay": lay.assay, "fiscal_year": lay.fiscal_year, "site_id_raw": sid}
        for k, key in (("water_system", "water"), ("tributary", "trib"), ("municipality", "muni")):
            body = clean(sh.get(R[key], c))
            phon = sh.phon.get((R[key], c), "") if body is not None else ""
            raw, ja, fb = split_furigana(body, phon, known)
            fallback += fb
            rec[f"{k}_raw"], rec[f"{k}_ja"] = raw, ja
        rec["collected_on"], rec["collected_on_raw"] = parse_date(sh.get(R["date"], c), lay.date_kind)
        rec["source_id"] = SOURCE_ID
        rec["source_ref"] = f"{source_ref_base}#{lay.file}!{c}"
        sites.append(rec)
    if lay.expect_sites and len(sites) != lay.expect_sites:
        raise LayoutError(f"{lay.file}: 地点数が宣言と違う（期待 {lay.expect_sites} / 実際 {len(sites)}）")
    return sites, fallback


RELIABILITY = {"高", "中", "低"}


def parse_row_meta(sh, lay, r):
    """1 行（種）の、地点に依らない列。"""
    rc = lay.cols

    def tx(field_):
        col = rc.get(field_)
        return clean(sh.get(r, col)) if col else None
    name_adopted, name_raw = tx("name_adopted"), tx("name_raw")
    notes = bracket_notes(name_adopted)
    if tx("name_note"):
        notes.append(tx("name_note"))
    pident = None
    if rc.get("pident"):
        pv = sh.get(r, rc["pident"])
        if pv is not None:
            if isinstance(pv, str) or not (0 <= pv <= 1):
                raise LayoutError(f"{lay.file}: {r} 行の pident×qcov が 0〜1 の数でない ({pv!r})")
            pident = float(pv)
    rel = tx("reliability")
    if rel is not None and rel not in RELIABILITY:
        raise LayoutError(f"{lay.file}: {r} 行の信頼度が 高/中/低 でない ({rel!r})")
    meta = {
        "class_ja": dash_none(sh.get(r, rc["class"])), "order_ja": dash_none(sh.get(r, rc["order"])),
        "family_ja": dash_none(sh.get(r, rc["family"])), "genus_ja": dash_none(sh.get(r, rc["genus"])),
        "name_raw": name_raw, "name_adopted": name_adopted,
        "name_sci_raw": tx("name_sci"), "name_note": "; ".join(notes) or None,
        "pident_qcov": pident, "reliability": rel,
        "national_rl_raw": tx("national_rl"), "pref_rl_raw": tx("pref_rl"), "alien_raw": tx("alien"),
        "name_key": name_key(name_adopted or name_raw or ""),
        "dataset_filter": lay.dataset_filter or None,
        "source_id": SOURCE_ID,
    }
    if not meta["name_key"]:
        raise LayoutError(f"{lay.file}: {r} 行の名前の正規化キーが空 ({name_adopted!r})")
    return meta


def parse_reads(sh, lay, data_rows, site_cols, sites):
    """(読みの行のリスト, 検出セル数, 空セル数)。空セルは不検出とも検出とも言えないので行にしない。"""
    reads, detected, blank = [], 0, 0
    for r in data_rows:
        meta = parse_row_meta(sh, lay, r)
        for c, rec in zip(site_cols, sites):
            v = sh.get(r, c)
            if v is None:
                blank += 1
                continue
            if isinstance(v, float) and v == int(v):
                v = int(v)
            if isinstance(v, str) or not isinstance(v, int) or v < 0:
                raise LayoutError(f"{lay.file}: {c}{r} がリード数（非負の整数）でない ({v!r})")
            detected += v > 0
            reads.append({"read_id": f"{rec['site_key']}:{r}", "site_key": rec["site_key"], **meta,
                          "reads": v, "is_detected": int(v > 0)})
    return reads, detected, blank


def parse_book(path, lay, source_ref_base):
    """(sites, reads, stats)。sites/reads は CSV の行 dict。宣言と食い違えば LayoutError。"""
    sh = load_xlsx(path)
    check_headers(sh, lay)
    site_cols = check_site_columns(sh, lay)
    data_rows = find_data_rows(sh, lay)
    check_no_unreadable_cells(sh, lay, data_rows)
    sites, fallback = parse_sites(sh, lay, site_cols, source_ref_base)
    reads, detected, blank = parse_reads(sh, lay, data_rows, site_cols, sites)
    stats = {"file": lay.file, "sites": len(sites), "data_rows": len(data_rows), "last_data_row": data_rows[-1],
             "cells": len(reads), "detected": detected, "blank_cells": blank,
             "no_date_sites": sum(1 for x in sites if x["collected_on"] is None),
             "furigana_fallback": fallback,
             "ignored_formula_cells": len(sh.formula_cells), "ignored_error_cells": len(sh.error_cells),
             "ignored_oversize_cells": len(sh.oversize_cells)}
    return sites, reads, stats


# ---------------------------------------------------------------------------
# 5) 入口 HTML からリンクを拾う・取得
# ---------------------------------------------------------------------------
def discover_xlsx_links(html):
    """edna.html から xlsx リンクを拾い、解析対象 [(ファイル名, URL)] を返す。
    未知の r<年度>_ 系・どの規則にも当たらない .xlsx が増えたら止める。"""
    found = re.findall(r'href="([^"]+\.xlsx)"', html)
    targets, seen = [], set()
    for href in found:
        url = urllib.parse.urljoin(INDEX_URL, href)
        name = pathlib.PurePosixPath(urllib.parse.urlparse(url).path).name
        if name in seen:
            continue
        seen.add(name)
        if TARGET_XLSX.match(name):
            if name not in LAYOUTS:
                raise LayoutError(f"未知の調査結果ファイル {name} がリンクに増えた。LAYOUTS に追加するまで進めない"
                                  "（レイアウトを推測しない）")
            targets.append((name, url))
        elif not KNOWN_IGNORED_XLSX.match(name):
            raise LayoutError(f"どの規則にも当たらない .xlsx {name} がリンクに増えた。確認してから進める")
    missing = sorted(set(LAYOUTS) - {n for n, _ in targets})
    if missing:
        raise LayoutError(f"宣言済みのファイルがリンクから消えた: {missing}")
    return targets


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--offline", action="store_true", help="取得済みの raw（data/raw/kanagawa_edna/）だけを使う")
    ap.add_argument("--no-register", action="store_true",
                    help="source_registry に書かない（開発・検証用。ryuiki.sqlite に触れない）")
    args = ap.parse_args(argv)

    from common import get, register, sha256, PROC, RAW
    raw_dir = RAW / "kanagawa_edna"
    raw_dir.mkdir(parents=True, exist_ok=True)
    html_path = raw_dir / "edna.html"
    if args.offline:
        if not html_path.exists():
            raise SystemExit(f"--offline だが {html_path} が無い")
    else:
        r = get(INDEX_URL)
        html_path.write_bytes(r.content)
    html = html_path.read_bytes().decode("utf-8", errors="replace")
    targets = discover_xlsx_links(html)

    all_sites, all_reads, all_stats, hashes, changed = [], [], [], {}, []
    for name, url in targets:
        dest = raw_dir / name
        if not args.offline:
            # オンラインのときは常に取り直す（差し替えられた xlsx を古いまま読まない）。sha256 が変われば出す
            old = sha256(dest) if dest.exists() else None
            dest.write_bytes(get(url, headers={"Referer": INDEX_URL}).content)
            if old is not None and old != sha256(dest):
                changed.append(name)
                print(f"  [changed] {name}: sha256 {old[:12]} -> {sha256(dest)[:12]}")
        elif not dest.exists():
            raise SystemExit(f"--offline だが {dest} が無い")
        hashes[name] = sha256(dest)
        sites, reads, stats = parse_book(dest, LAYOUTS[name], INDEX_URL)
        lay = LAYOUTS[name]
        for label, got, want in (("地点数", stats["sites"], lay.expect_sites),
                                 ("検出セル数", stats["detected"], lay.expect_detected),
                                 ("全セル数", stats["cells"], lay.expect_cells)):
            if want and got != want:
                raise LayoutError(f"{name}: {label}が宣言と違う（期待 {want} / 実際 {got}）")
        all_sites += sites
        all_reads += reads
        all_stats.append(stats)
        print(f"  {name}: 地点 {stats['sites']} / 検出 {stats['detected']} / 全セル {stats['cells']}"
              f" / 日付なし {stats['no_date_sites']} / 空セル {stats['blank_cells']}")

    site_cols = ["site_key", "dataset_file", "program", "assay", "fiscal_year", "site_id_raw",
                 "water_system_raw", "water_system_ja", "tributary_raw", "tributary_ja",
                 "municipality_raw", "municipality_ja", "collected_on", "collected_on_raw",
                 "source_id", "source_ref"]
    read_cols = ["read_id", "site_key", "class_ja", "order_ja", "family_ja", "genus_ja", "name_raw",
                 "name_adopted", "name_sci_raw", "name_note", "reads", "is_detected", "pident_qcov",
                 "reliability", "national_rl_raw", "pref_rl_raw", "alien_raw", "name_key", "dataset_filter",
                 "source_id"]
    for name, cols, rows in (("sites", site_cols, all_sites), ("reads", read_cols, all_reads)):
        write_csv(PROC / f"kanagawa_edna_{name}.csv", cols, rows)
        print(f"  [write] kanagawa_edna_{name}.csv  {len(rows)} rows")

    det = sum(s["detected"] for s in all_stats)
    print(f"  合計: 地点 {len(all_sites)} / 全セル {len(all_reads)} / 検出 {det}")
    notes = (f"xlsx {len(targets)} 本（R3〜R7）。地点 {len(all_sites)}・全セル {len(all_reads)}（0 を含む）・"
             f"検出セル {det}。値はリード数（個体数ではない）。座標は公開データに無い"
             f"（推定は data/edna/kanagawa_edna_site_coords.csv）。出典表記: {ATTRIBUTION}。" +
             (f" 前回から変わったファイル: {changed}。" if changed else "") +
             f" sha256: " + ", ".join(f"{k}={v[:12]}" for k, v in sorted(hashes.items())))
    if args.no_register:
        return
    register(source_id=SOURCE_ID, name="神奈川県 環境DNA調査結果（県民協働・プロジェクト）",
             publisher=PUBLISHER, url=INDEX_URL, category="環境DNA調査（生物相）",
             access_method="HTML内xlsxリンク動的取得+標準ライブラリでxlsx解析", fmt="XLSX",
             license_=LICENSE, redistributable=1, record_count=len(all_reads), notes=notes)


if __name__ == "__main__":
    main()
