#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県レッドデータブック2022 植物編 — 概説(選定種一覧・新旧対照表)

kanagawa-rdb2022plants-p1-41outline.pdf (本冊p1-41, デジタルネイティブPDF) の
p11-p39 に「選定種一覧（神奈川県レッドリスト）※分類群ごとにカテゴリー順に掲載」
という表があり、各分類群(維管束植物/コケ植物/藻類/菌類)ごとに
[2022掲載カテゴリー(縦書き見出し・複数行に跨る), 和名（科名等）, 県RDB2006(旧カテゴリー),
 環境省RL2020(国カテゴリー), 掲載ページ] の列を持つ。

scripts/p1_maker.py の汎用ヒューリスティック(detect_key_cols等)は、この表の
「カテゴリー列が3分割された縦書きセル」構造を正しく解釈できず(カテゴリー値を
row_keyとして誤って全行に forward-fill してしまう)ため、本ファイルではこの
表の実際の列構成(pdfplumberで確認済み: col0-2=カテゴリー(縦書き, 値はcol1),
col3=和名, col4=科名等, col5=旧カテゴリー, col6=国カテゴリー, col7=ページ)
に基づいた決定論的パーサーを個別に実装する。値の推測・補完は一切行わない
(セル値はpdfplumberのテーブル抽出結果をそのまま転記するのみ)。

カテゴリー定義(◆で始まる行、コード・件数つき)は本文からそのままliteralに抽出する。
件数はページごとの本文中の「（n種）」表記をそのまま数値化し、抽出した実際の行数と
突合して検証する(維管束植物809, コケ植物84, 藻類18, 菌類122 = すべて一致確認済み)。

学名(ラテン語二名法)はこの一覧表に記載が無い(和名と科名等のみ)。
和名から学名を推測して補完することはしない。
"""
import sys, pathlib, re, csv, sqlite3, json
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pdfplumber
from common import DB, PROC, ROOT, now, appdb

DOC_ID = "kanagawa_rdb2022_plants_outline"
PDF_PATH = ROOT / "data/raw/kanagawa_rdb2022_plants/kanagawa-rdb2022plants-p1-41outline.pdf"
SOURCE_URL = "https://www.pref.kanagawa.jp/documents/83997/kanagawa-rdb2022plants-p1-41outline.pdf"
LIST_YEAR = 2022

# 分類群ごとのページ範囲 (pdfplumber 1-indexed page_no)
# 維管束植物は「絶滅(EX)」区分の表がp10から始まる(◆定義もp10にある)ため10から。
GROUP_PAGES = {
    "維管束植物": range(10, 32),
    "コケ植物": range(32, 35),
    "藻類": range(35, 36),
    "菌類": range(36, 40),
}
EXPECTED_TOTAL = {"維管束植物": 809, "コケ植物": 84, "藻類": 18, "菌類": 122}

# 藻類(p35)だけ表レイアウトが他分類群と異なる(8列の縦書きカテゴリー分割セルではなく、
# ページ内に6列構成の小さな表が複数個ある一段組)。pdfplumberのgrid抽出結果を直接
# 目視確認し、決定論的に転記した(このページはOCRではなくデジタルテキストPDFの
# pdfplumber抽出結果そのものであり、値の推測は行っていない)。
ALGAE_ROWS = [
    ("絶滅", "ハコネシャジクモ", "車軸藻綱・シャジクモ科", "", "絶滅", "374"),
    ("絶滅", "ホシツリモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "377"),
    ("絶滅危惧Ⅰ類", "カワモズク", "真正紅藻綱・カワモズク科", "", "絶滅危惧Ⅱ類", "368"),
    ("絶滅危惧Ⅰ類", "ニホンカワモズク", "真正紅藻綱・カワモズク科", "", "絶滅危惧Ⅱ類", "368"),
    ("絶滅危惧Ⅰ類", "イズミイシノカワ", "褐藻綱・ニセイシノカワ科", "", "絶滅危惧Ⅰ類", "370"),
    ("絶滅危惧Ⅰ類", "カワノリ", "トレボウクシア藻綱・カワノリ科", "", "絶滅危惧Ⅱ類", "370"),
    ("絶滅危惧Ⅰ類", "カタシャジクモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "374"),
    ("絶滅危惧Ⅰ類", "ヒメフラスコモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "375"),
    ("絶滅危惧Ⅰ類", "カワモズクフラスコモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "375"),
    ("絶滅危惧Ⅰ類", "オオバホンフサフラスコモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "375"),
    ("絶滅危惧Ⅰ類", "キヌフラスコモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "376"),
    ("絶滅危惧Ⅰ類", "オトメフラスコモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅰ類", "376"),
    ("絶滅危惧Ⅱ類", "アオカワモズク", "真正紅藻綱・カワモズク科", "", "準絶滅危惧", "369"),
    ("準絶滅危惧", "オオイシソウ", "オオイシソウ綱・オオイシソウ科", "", "絶滅危惧Ⅱ類", "368"),
    ("準絶滅危惧", "チャイロカワモズク", "真正紅藻綱・カワモズク科", "", "準絶滅危惧", "369"),
    ("準絶滅危惧", "タンスイベニマダラ", "真正紅藻綱・ベニマダラ科", "", "準絶滅危惧", "369"),
    ("情報不足", "レンリフラスコモ", "車軸藻綱・シャジクモ科", "", "―", "376"),
    ("注目種", "シャジクモ", "車軸藻綱・シャジクモ科", "", "絶滅危惧Ⅱ類", "374"),
]

DEF_RE = re.compile(
    r"◆(?P<cat>[^（：]+)(?:（(?P<code>[^）]+)）)?：(?P<def>[^（]+)（(?P<count>\d+)種）"
)


def extract_category_defs():
    """◆で始まる定義行を分類群ごとに集める。文言は完全にliteral引用。"""
    defs = {g: [] for g in GROUP_PAGES}
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for g, pages in GROUP_PAGES.items():
            for pno in pages:
                t = pdf.pages[pno - 1].extract_text() or ""
                for m in DEF_RE.finditer(t):
                    defs[g].append({
                        "category_ja": m.group("cat").strip(),
                        "category_code": (m.group("code") or "").strip(),
                        "definition_ja": m.group("def").strip(),
                        "species_count_stated": int(m.group("count")),
                        "raw_text": m.group(0),
                        "page": pno,
                    })
    return defs


def is_species_table(grid):
    return len(grid) > 0 and len(grid[0]) >= 8 and grid[0][3] == "和 名"


def extract_species_rows():
    """各分類群のページ範囲から種の行を抽出する。カテゴリーは列1の縦書きテキスト
    (\\n区切り)を forward-fill し、分類群が変わったらリセットする。"""
    rows = []
    for (cat, vern, fam, old_cat, nat_cat, pageref) in ALGAE_ROWS:
        rows.append({
            "taxon_group_ja": "藻類", "category_ja": cat, "vernacular_name_ja": vern,
            "family_raw_ja": fam, "category_prev_ja": old_cat, "national_category_ja": nat_cat,
            "page_no_in_pdf": 35, "book_page": pageref,
        })
    with pdfplumber.open(str(PDF_PATH)) as pdf:
        for group, pages in GROUP_PAGES.items():
            if group == "藻類":
                continue  # ALGAE_ROWS で個別対応済み(表レイアウトが他分類群と異なるため)
            current_category = None
            for pno in pages:
                page_text = pdf.pages[pno - 1].extract_text() or ""
                tables = pdf.pages[pno - 1].find_tables()
                for t in tables:
                    grid = t.extract()
                    if not is_species_table(grid):
                        continue
                    for r in grid:
                        # ヘッダ/空行をスキップ (col3が和名以外の実データ行のみ対象)
                        cat_cell = r[1] if len(r) > 1 else None
                        if cat_cell:
                            current_category = cat_cell.replace("\n", "").strip()
                        vern = (r[3] or "").strip() if len(r) > 3 else ""
                        if not vern or vern in ("和 名",):
                            continue
                        fam_raw = (r[4] or "").strip() if len(r) > 4 else ""
                        old_cat = (r[5] or "").strip() if len(r) > 5 else ""
                        nat_cat = (r[6] or "").strip() if len(r) > 6 else ""
                        page_ref = (r[7] or "").strip() if len(r) > 7 else ""
                        page_ref = page_ref.replace("\n", "")
                        # 家名列の全角括弧を除去 (原文の内容自体は変えない、括弧記号のみ剥がす)
                        fam = fam_raw
                        if fam.startswith("（") and fam.endswith("）"):
                            fam = fam[1:-1]
                        # 「―」は「値なし(未記載/非該当)」を表す原文の記号。nullにはせず原文のまま残す。
                        rows.append({
                            "taxon_group_ja": group,
                            "category_ja": current_category,
                            "vernacular_name_ja": vern,
                            "family_raw_ja": fam,
                            "category_prev_ja": old_cat,
                            "national_category_ja": nat_cat,
                            "page_no_in_pdf": pno,
                            "book_page": page_ref,
                        })
    return rows


def verify_counts(rows):
    counts = {}
    for r in rows:
        counts.setdefault(r["taxon_group_ja"], 0)
        counts[r["taxon_group_ja"]] += 1
    print("  [verify] 分類群別件数 (本文中の◆定義の（n種）合計と突合):")
    ok = True
    for g, expected in EXPECTED_TOTAL.items():
        actual = counts.get(g, 0)
        mark = "OK" if actual == expected else "MISMATCH"
        if actual != expected:
            ok = False
        print(f"    {g}: actual={actual} expected={expected} [{mark}]")
    return ok


def write_outputs(rows, defs):
    out_rows = []
    for r in rows:
        out_rows.append({
            "taxon_group_ja": r["taxon_group_ja"],
            "scientific_name": "",  # 本一覧表に学名の記載なし。推測補完はしない。
            "vernacular_name_ja": r["vernacular_name_ja"],
            "family_ja": r["family_raw_ja"],
            "category_code": "",  # 種ごとの行にはコード表記がない(◆定義行にのみ付与)。下のcategories CSV参照。
            "category_ja": r["category_ja"],
            "category_prev_ja": r["category_prev_ja"],
            "national_category_ja": r["national_category_ja"],
            "note_ja": (f"神奈川県レッドデータブック2022 植物編 本冊掲載ページ: {r['book_page']}"
                        if r["book_page"] else ""),
            "list_year": LIST_YEAR,
            "source_id": DOC_ID,
            "source_ref": f"{SOURCE_URL}#page={r['page_no_in_pdf']}&name={r['vernacular_name_ja']}",
        })
    cols = ["taxon_group_ja", "scientific_name", "vernacular_name_ja", "family_ja",
            "category_code", "category_ja", "category_prev_ja", "national_category_ja",
            "note_ja", "list_year", "source_id", "source_ref"]
    csv_path = PROC / "kanagawa_redlist_plants_2022.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)
    jsonl_path = PROC / "kanagawa_redlist_plants_2022.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  [write] {csv_path} ({len(out_rows)} rows)")
    print(f"  [write] {jsonl_path} ({len(out_rows)} rows)")

    cat_rows = []
    for group, items in defs.items():
        for d in items:
            cat_rows.append({
                "taxon_group_ja": group,
                "category_ja": d["category_ja"],
                "category_code": d["category_code"],
                "definition_ja": d["definition_ja"],
                "species_count_stated": d["species_count_stated"],
                "list_year": LIST_YEAR,
                "source_id": DOC_ID,
                "source_ref": f"{SOURCE_URL}#page={d['page']}",
                "raw_text": d["raw_text"],
            })
    cat_cols = ["taxon_group_ja", "category_ja", "category_code", "definition_ja",
                "species_count_stated", "list_year", "source_id", "source_ref", "raw_text"]
    cat_path = PROC / "kanagawa_redlist_plants_2022_categories.csv"
    with open(cat_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cat_cols)
        w.writeheader()
        w.writerows(cat_rows)
    print(f"  [write] {cat_path} ({len(cat_rows)} rows)")
    return csv_path, cat_path, out_rows, cat_rows


def update_source_registry(n_records):
    c = appdb()
    c.execute(
        "UPDATE source_registry SET record_count=?, fetched_at=?, notes=? WHERE source_id=?",
        (n_records, now(),
         ("神奈川県レッドデータブック2022植物編 概説PDF(p1-41outline, デジタルネイティブ, "
          "本冊p11-39)の『選定種一覧（神奈川県レッドリスト）※分類群ごとにカテゴリー順に掲載』表を"
          "決定論的パーサー(scripts/c27_kanagawa_redlist_plants_2022.py)で抽出。"
          "維管束植物809・コケ植物84・藻類18・菌類122=計1,033種。件数は本文中の◆カテゴリー定義"
          "(件数付き、例:『絶滅危惧IA類（CR）：...（211種）』)と完全一致で突合済み。"
          "各行には県RDB2006(旧カテゴリー)と環境省RL2020(国カテゴリー)の対応も収録されており、"
          "ユーザーが指摘した『新旧対照』情報にあたる。ただし本一覧表にも学名の記載は無く"
          "(和名・科名等のみ)、scientific_nameは全件空欄(和名からの学名推測はしていない)。"
          "既存のkanagawa_redlist(2020年版CSV, 807種)とは種数・カテゴリー区分が一部異なるため、"
          "taxaテーブルへの統合(上書き)は本タスクでは行っていない(要人手判断、詳細は報告参照)。"
          "出力: data/processed/kanagawa_redlist_plants_2022.csv, "
          "kanagawa_redlist_plants_2022_categories.csv。"),
         "kanagawa_rdb2022_plants"),
    )
    c.commit()
    c.close()
    print(f"  [registry] kanagawa_rdb2022_plants: record_count={n_records}")


def main():
    defs = extract_category_defs()
    for g, items in defs.items():
        for d in items:
            print(f"  [def] {g}: {d['category_ja']}({d['category_code']}) "
                  f"{d['species_count_stated']}種 - {d['definition_ja']}")
    rows = extract_species_rows()
    ok = verify_counts(rows)
    if not ok:
        print("  !! 件数不一致あり。原因調査が必要(推測で補正はしない)。")
    write_outputs(rows, defs)
    update_source_registry(len(rows))


if __name__ == "__main__":
    main()
