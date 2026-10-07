"""c89_kanagawa_edna（xlsx → 長持ち CSV）のテスト。

CI に原本の xlsx は無いので、小さな合成 xlsx をその場で組み立てて確かめる。
「止まるべきときに止まる」（列ずれ・日付形式・未知ファイル・地点列の増減・不正な値）は、
正しいブックに変異を当てて確かめる（通ったことだけを見ない）。
実物の xlsx が手元にあれば（data/raw/kanagawa_edna/）、9 本が宣言どおりに読めることも確かめる。
"""
import dataclasses
import pathlib
import zipfile
from xml.sax.saxutils import escape

import pytest

import c89_kanagawa_edna as c89

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "kanagawa_edna"


# ---------------------------------------------------------------- 合成 xlsx
def make_xlsx(path, cells, formulas=(), errors=()):
    """cells: {'A1': 'text' | (本体, ふりがな) | 数値}。formulas: 数式セル（キャッシュ値つき）。"""
    strings, index = [], {}

    def sid(body, phon=""):
        k = (body, phon)
        if k not in index:
            index[k] = len(strings)
            strings.append(k)
        return index[k]

    def colnum(ref):
        letters = "".join(ch for ch in ref if ch.isalpha())
        return c89.col2n(letters), int("".join(ch for ch in ref if ch.isdigit()))

    rows = {}
    for ref, v in cells.items():
        col, row = colnum(ref)
        rows.setdefault(row, []).append((col, ref, v, "v"))
    for ref, v in formulas:
        col, row = colnum(ref)
        rows.setdefault(row, []).append((col, ref, v, "f"))
    for ref in errors:
        col, row = colnum(ref)
        rows.setdefault(row, []).append((col, ref, "#N/A", "e"))
    out = []
    for row in sorted(rows):
        cs = []
        for col, ref, v, kind in sorted(rows[row], key=lambda x: x[0]):
            if kind == "f":
                cs.append(f'<c r="{ref}"><f>SUM(A1:A2)</f><v>{v}</v></c>')
            elif kind == "e":
                cs.append(f'<c r="{ref}" t="e"><v>#N/A</v></c>')
            elif isinstance(v, (int, float)):
                cs.append(f'<c r="{ref}"><v>{v}</v></c>')
            else:
                body, phon = v if isinstance(v, tuple) else (v, "")
                cs.append(f'<c r="{ref}" t="s"><v>{sid(body, phon)}</v></c>')
        out.append(f'<row r="{row}">{"".join(cs)}</row>')
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sst = "".join(
        f"<si><t>{escape(b)}</t>" + (f"<rPh sb=\"0\" eb=\"1\"><t>{escape(p)}</t></rPh>" if p else "") + "</si>"
        for b, p in strings)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml",
                   f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   '<sheets><sheet name="本体" sheetId="1" r:id="rId1"/><sheet name="国RL" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">{sst}</sst>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(out)}</sheetData></worksheet>')
        z.writestr("xl/worksheets/sheet2.xml", f'<worksheet xmlns="{ns}"><sheetData/></worksheet>')


def fish_cells(extra_site=False, shift=False, date_value=44442):
    """魚類型（r3 と同じ形）の 2 地点 × 3 種。"""
    cells = {}
    hdr = [("G1", "調査年度"), ("G2", "調査地点ID"), ("G3", "水系"), ("G4", "支川名"), ("G5", "関係市町村")]
    for ref, v in hdr:
        cells[ref] = (v, "チョウサ")          # ふりがな付き
    cells.update({"A6": "綱", "B6": "目", "C6": "科", "D6": "属", "E6": "種名", "F6": "国RL",
                  "G6": "↓県RDB　調査日→"})
    sites = [("H", "K-21-1", "相模川", "-", ("厚木市", "アツギシ"), date_value),
             ("I", "K-21-8,9", ("酒匂川", "サカワガワ"), ("川音川", "カワネガワ"), "厚木市アツギシ", None)]
    for col, sid, water, trib, muni, d in sites:
        cells[f"{col}1"] = "2021年度"
        cells[f"{col}2"] = sid
        cells[f"{col}3"] = water
        cells[f"{col}4"] = trib
        cells[f"{col}5"] = muni
        if d is not None:
            cells[f"{col}6"] = d
    if extra_site:
        cells["J2"] = "K-21-99"
    species = [("硬骨魚綱", "ウナギ目", "ウナギ科", "ウナギ属", "ニホンウナギ", 0, 98),
               ("硬骨魚綱", "コイ目", "コイ科", "コイ属", ("コイ（飼育型）", "シイクガタ"), 1367, 0),
               ("硬骨魚綱", "-", "-", "-", "ウグイ", 0, 0)]
    for i, (a, b, c_, d, e, h, i_) in enumerate(species):
        r = 7 + i
        cells.update({f"A{r}": a, f"B{r}": b, f"C{r}": c_, f"D{r}": d, f"E{r}": e, f"H{r}": h, f"I{r}": i_})
    cells["F7"] = "絶滅危惧IB類（EN）"
    cells["B50"] = "＜表の見方＞"        # データ範囲の下の凡例
    if shift:                              # A 列に 1 列ぶんの分類を足してずらす（r6_kenmin の形の事故）
        cells = {f"{c89.n2col(c89.col2n(''.join(ch for ch in k if ch.isalpha())) + 1)}{''.join(ch for ch in k if ch.isdigit())}": v
                 for k, v in cells.items()}
    return cells


FISH = dataclasses.replace(
    c89.LAYOUTS["r3_kenmin_gyorui.xlsx"], file="syn_fish.xlsx", site_last="I",
    expect_sites=2, expect_last_data_row=9, expect_detected=2, expect_cells=6)


def parse(tmp_path, cells, lay=FISH, **kw):
    p = tmp_path / lay.file
    make_xlsx(p, cells, **kw)
    return c89.parse_book(p, lay, c89.INDEX_URL)


# ---------------------------------------------------------------- 正しいブック
def test_parse_fish_book(tmp_path):
    sites, reads, st = parse(tmp_path, fish_cells())
    assert st["sites"] == 2 and st["cells"] == 6 and st["detected"] == 2 and st["blank_cells"] == 0
    s1, s2 = sites
    # キーは「ファイル×列」。ID は正規化しない（カンマ入りもそのまま）
    assert s1["site_key"] == "syn_fish:K-21-1" and s2["site_key"] == "syn_fish:K-21-8,9"
    # 日付はシリアル値 → ISO。空欄は NULL（補わない）
    assert (s1["collected_on"], s1["collected_on_raw"]) == ("2021-09-03", "44442")
    assert (s2["collected_on"], s2["collected_on_raw"]) == (None, None)
    # ふりがな: raw は連結した原文、ja は本体だけ。ふりがなが無いものは同じ
    assert (s1["municipality_raw"], s1["municipality_ja"]) == ("厚木市アツギシ", "厚木市")
    assert (s2["water_system_raw"], s2["water_system_ja"]) == ("酒匂川サカワガワ", "酒匂川")
    assert (s1["water_system_raw"], s1["water_system_ja"]) == ("相模川", "相模川")
    assert s1["tributary_ja"] == "-"
    assert s2["municipality_raw"] == "厚木市アツギシ" and s2["municipality_ja"] == "厚木市"  # 本体に直に連結 → 同ブックの既知名との前方一致で外す
    assert s1["source_ref"].endswith("#syn_fish.xlsx!H") and s1["fiscal_year"] == 2021
    r = {x["read_id"]: x for x in reads}
    assert set(r) == {f"{k}:{n}" for k in ("syn_fish:K-21-1", "syn_fish:K-21-8,9") for n in (7, 8, 9)}
    koi = r["syn_fish:K-21-1:8"]
    assert koi["reads"] == 1367 and koi["is_detected"] == 1 and koi["name_adopted"] == "コイ（飼育型）"
    assert koi["name_note"] == "（飼育型）" and koi["name_key"] == "コイ"       # 括弧書きは key から除く
    assert r["syn_fish:K-21-1:7"]["reads"] == 0 and r["syn_fish:K-21-1:7"]["is_detected"] == 0
    assert r["syn_fish:K-21-1:7"]["national_rl_raw"] == "絶滅危惧IB類（EN）"
    ugui = r["syn_fish:K-21-8,9:9"]
    assert ugui["order_ja"] is None and ugui["family_ja"] is None      # '-' は NULL
    assert ugui["pident_qcov"] is None and ugui["reliability"] is None  # 魚類に列は無い


def test_formula_and_error_cells_are_not_read(tmp_path):
    # 地点列の外の数式（合計列）・名前列のエラーセルは値として読まない（無視して数える）
    cells = fish_cells()
    sites, reads, st = parse(tmp_path, cells, formulas=[("J7", 99), ("J8", 99)], errors=["F8"])
    assert st["cells"] == 6 and st["ignored_formula_cells"] == 2 and st["ignored_error_cells"] == 1


def test_name_key():
    assert c89.name_key("コイ（飼育型）") == "コイ"
    assert c89.name_key("Stenostomum  Leucops（注）") == "stenostomumleucops"
    assert c89.name_key("ｳｸﾞｲ") == "ウグイ"          # NFKC


def test_split_furigana_prefix_match_only():
    known = {"中津川", "厚木市・海老名市"}
    assert c89.split_furigana("中津川ナカツガワ", "", known) == ("中津川ナカツガワ", "中津川", True)
    # 既知名と前方一致しなければ raw のまま（推測で切らない）
    assert c89.split_furigana("謎川ナゾガワ", "", known) == ("謎川ナゾガワ", "謎川ナゾガワ", False)
    # 前方一致でも残りがカタカナだけでなければ切らない
    assert c89.split_furigana("中津川上流", "", known)[1] == "中津川上流"
    # <rPh> で分けて読めたものはそのまま
    assert c89.split_furigana("鳩川", "ハトガワ", known) == ("鳩川ハトガワ", "鳩川", False)


def test_parse_date():
    assert c89.parse_date(44442, "serial") == ("2021-09-03", "44442")
    assert c89.parse_date("20250721", "yyyymmdd") == ("2025-07-21", "20250721")
    assert c89.parse_date(20250721, "yyyymmdd") == ("2025-07-21", "20250721")
    assert c89.parse_date(None, "serial") == (None, None)
    assert c89.parse_date("", "yyyymmdd") == (None, None)


# ---------------------------------------------------------------- 止まる（変異）
def test_stops_when_columns_shift(tmp_path):
    # 列が 1 つ右にずれたブックを、ずれる前のレイアウトで読ませる → ヘッダの突き合わせで止まる
    with pytest.raises(c89.LayoutError, match="ヘッダ"):
        parse(tmp_path, fish_cells(shift=True))


def test_stops_on_date_format_mismatch(tmp_path):
    with pytest.raises(c89.LayoutError, match="シリアル値"):
        parse(tmp_path, fish_cells(date_value=20210903))          # serial 宣言なのに YYYYMMDD
    lay = dataclasses.replace(FISH, date_kind="yyyymmdd")
    with pytest.raises(c89.LayoutError, match="YYYYMMDD"):
        parse(tmp_path, fish_cells(date_value=44442), lay=lay)     # yyyymmdd 宣言なのにシリアル値


def test_stops_when_a_site_column_is_added(tmp_path):
    with pytest.raises(c89.LayoutError, match="地点列が増えた"):
        parse(tmp_path, fish_cells(extra_site=True))


def test_stops_when_declared_counts_differ(tmp_path):
    with pytest.raises(c89.LayoutError, match="地点数"):
        parse(tmp_path, fish_cells(), lay=dataclasses.replace(FISH, expect_sites=3))
    with pytest.raises(c89.LayoutError, match="データ末尾行"):
        parse(tmp_path, fish_cells(), lay=dataclasses.replace(FISH, expect_last_data_row=10))


def test_stops_on_wrong_fiscal_year(tmp_path):
    with pytest.raises(c89.LayoutError, match="年度"):
        parse(tmp_path, fish_cells(), lay=dataclasses.replace(FISH, fiscal_year=2022))


def test_stops_on_duplicate_site_id(tmp_path):
    cells = fish_cells()
    cells["I2"] = "K-21-1"
    with pytest.raises(c89.LayoutError, match="重複"):
        parse(tmp_path, cells)


@pytest.mark.parametrize("bad", [-1, 1.5, "abc"])
def test_stops_on_bad_read_count(tmp_path, bad):
    cells = fish_cells()
    cells["H8"] = bad
    with pytest.raises(c89.LayoutError, match="リード数"):
        parse(tmp_path, cells)


def test_stops_when_class_column_is_empty_even_if_column_a_has_a_value(tmp_path):
    # 綱の空欄検査はレイアウトの綱列そのもの（A 列に値があっても素通りさせない）
    lay = dataclasses.replace(FISH, cols=dict(FISH.cols, **{"class": "B"}))
    cells = fish_cells()
    cells["B8"] = None
    del cells["B8"]
    with pytest.raises(c89.LayoutError, match="綱"):
        parse(tmp_path, cells, lay=lay)


def test_dataset_filter_is_a_reads_column(tmp_path):
    sites, reads, _ = parse(tmp_path, fish_cells(), lay=dataclasses.replace(FISH, dataset_filter="match>=98.5%"))
    assert {r["dataset_filter"] for r in reads} == {"match>=98.5%"}
    sites, reads, _ = parse(tmp_path, fish_cells())
    assert {r["dataset_filter"] for r in reads} == {None}


def test_stops_on_formula_in_site_body(tmp_path):
    with pytest.raises(c89.LayoutError, match="数式"):
        parse(tmp_path, fish_cells(), formulas=[("H8", 5)])


def test_stops_on_bad_reliability(tmp_path):
    lay = dataclasses.replace(
        c89.LAYOUTS["r5_kenmin_mtinsects-16s.xlsx"], file="syn_ins.xlsx", site_first="O", site_last="O",
        expect_sites=1, expect_last_data_row=7, expect_detected=1, expect_cells=1)
    cells = {"N1": "調査年度", "N2": "調査地点ID", "N3": "水系", "N4": "支川名", "N5": "関係市町村",
             "A6": "綱", "B6": "目", "C6": "科", "D6": "属", "E6": "参考種名", "F6": "種名(手動精査結果)",
             "G6": "MAX(pident*qcovs)", "H6": "信頼度", "I6": "国RL", "L6": "地方自治体RL", "M6": "特定外来種",
             "N6": "調査日→", "O1": "2023年度", "O2": "K-23-1", "O3": "相模川", "O4": "-", "O5": "愛川町",
             "O6": 45037, "A7": "昆虫綱", "B7": "-", "C7": "X科", "D7": "Y属", "E7": "Aus bus", "F7": "Aus bus（注）",
             "G7": 0.99, "H7": "高", "O7": 12}
    sites, reads, st = parse(tmp_path, cells, lay=lay)
    assert reads[0]["reliability"] == "高" and reads[0]["pident_qcov"] == 0.99 and reads[0]["name_note"] == "（注）"
    cells["H7"] = "極高"
    with pytest.raises(c89.LayoutError, match="信頼度"):
        parse(tmp_path, cells, lay=lay)
    cells["H7"], cells["G7"] = "高", 1.5
    with pytest.raises(c89.LayoutError, match="pident"):
        parse(tmp_path, cells, lay=lay)


# ---------------------------------------------------------------- リンク探索
def _html(names):
    return "".join(f'<a href="/documents/97797/{n}">x</a>' for n in names)


def test_discover_links_ok_and_ignores_sample_info():
    names = list(c89.LAYOUTS) + ["insecta_v1_0.xlsx", "16s_28s_ver2_0.xlsx"]
    got = c89.discover_xlsx_links(_html(names))
    assert [n for n, _ in got] == list(c89.LAYOUTS)
    assert got[0][1] == "https://www.pref.kanagawa.jp/documents/97797/r3_kenmin_gyorui.xlsx"


def test_discover_stops_on_unknown_or_missing():
    base = list(c89.LAYOUTS)
    with pytest.raises(c89.LayoutError, match="未知の調査結果ファイル"):
        c89.discover_xlsx_links(_html(base + ["r8_kenmin_kekka.xlsx"]))
    with pytest.raises(c89.LayoutError, match="どの規則にも"):
        c89.discover_xlsx_links(_html(base + ["something_else.xlsx"]))
    with pytest.raises(c89.LayoutError, match="消えた"):
        c89.discover_xlsx_links(_html(base[:-1]))


def test_user_agent_is_not_defined_here():
    # UA は scripts/common.py のもの（個人名・個人アドレスを入れない）。ここで独自に名乗らない
    src = pathlib.Path(c89.__file__).read_text(encoding="utf-8")
    assert "User-Agent" not in src and "@" not in src.replace("@dataclass", "")


# ---------------------------------------------------------------- 実物（手元にあるときだけ）
needs_raw = pytest.mark.skipif(not (RAW / "r3_kenmin_gyorui.xlsx").exists(), reason="原本の xlsx が無い")


@needs_raw
@pytest.mark.parametrize("name", list(c89.LAYOUTS))
def test_real_books_match_declared_layout(name):
    lay = c89.LAYOUTS[name]
    sites, reads, st = c89.parse_book(RAW / name, lay, c89.INDEX_URL)
    assert st["sites"] == lay.expect_sites and st["detected"] == lay.expect_detected
    assert st["cells"] == lay.expect_cells == len(reads) and st["last_data_row"] == lay.expect_last_data_row


@needs_raw
def test_real_quirks():
    # r6_kenmin: 列が 1 つ右にずれる（綱は B 列）・AB 列の合計（数式）は読まない
    sites, reads, st = c89.parse_book(RAW / "r6_kenmin_mtinsects_amphi.xlsx", c89.LAYOUTS["r6_kenmin_mtinsects_amphi.xlsx"], c89.INDEX_URL)
    assert reads[0]["class_ja"] == "哺乳綱" and st["ignored_formula_cells"] > 0
    assert any(r["reliability"] == "低" for r in reads)
    # r7_project: YYYYMMDD の採水日
    sites, _, _ = c89.parse_book(RAW / "r7_project_kekka.xlsx", c89.LAYOUTS["r7_project_kekka.xlsx"], c89.INDEX_URL)
    assert sites[0]["collected_on"] == "2025-07-21" and sites[0]["collected_on_raw"] == "20250721"
    # r7_kenmin: 小文字の地点 ID・絞り込み版の宣言
    sites, _, _ = c89.parse_book(RAW / "r7_kenmin_kekka.xlsx", c89.LAYOUTS["r7_kenmin_kekka.xlsx"], c89.INDEX_URL)
    assert "r7_kenmin_kekka:k-25-04" in {s["site_key"] for s in sites}
    # r3: K-21-8,9（2 地点の合算）はそのまま 1 地点
    sites, _, _ = c89.parse_book(RAW / "r3_kenmin_gyorui.xlsx", c89.LAYOUTS["r3_kenmin_gyorui.xlsx"], c89.INDEX_URL)
    assert "r3_kenmin_gyorui:K-21-8,9" in {s["site_key"] for s in sites}
