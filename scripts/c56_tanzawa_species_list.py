"""丹沢のビジターセンター「生き物リスト」(哺乳類/鳥類/は虫類/両生類/昆虫) -> tanzawa_species_list_1997.csv

重要な注意(厳守: 原文引用のまま残す):
このリストは単純に「1997年時点の確認種リスト」ではない。ページごとに引用元・時点が異なる:
  - 哺乳類: 「丹沢大山自然環境総合調査報告書（2007）及び、「神奈川自然誌資料(30)」（2009）、
            「神奈川自然誌資料(32)」（2011）より引用」 (1997年報告書ではなく2007-2011年の資料)
  - 鳥類:   「丹沢大山自然環境総合調査報告書（神奈川県環境部,1997）によれば、丹沢全体で158種が
            確認されている。その後、宮ヶ瀬湖の出現により新たに数種類が確認されている。
            ※渡り区分は、丹沢大山総合調査動植物目録(2007）及び 神奈川県の鳥2011-2015
            神奈川県鳥類目録７（2020）を参考とした。※亜種までの分類はしていない。」
  - は虫類/両生類: 「丹沢大山自然環境総合調査報告書（神奈川県環境部、1997）より引用及び
                  1997年以降に丹沢で確認された種を含む」
  - 昆虫:   「丹沢大山自然環境総合調査報告書（神奈川県環境部,1997）によれば、丹沢全体で5,727種の
            昆虫が確認されている。その中でコウチュウ目が2,555種で全体の45％を占め、
            チョウ目1,663種、ハエ目365種、カメムシ目357種と続く。」
現在の分布状況ではなく、上記のように出典・時点が分類群ごとに異なる混成リストである点に注意。
"""
import sys, re, csv
sys.path.insert(0, "scripts")
from common import get, register, write_jsonl, PROC
import pandas as pd
import io

BASE = "https://www.kanagawa-park.or.jp/tanzawavc/"
PUBLISHER = "神奈川県立 秦野ビジターセンター・西丹沢ビジターセンター(公益財団法人神奈川県公園協会)"

PAGES = [
    ("ikimono1.html", "哺乳類", 3,
     "※丹沢大山自然環境総合調査報告書（2007）及び、「神奈川自然誌資料(30)」（2009）、"
     "「神奈川自然誌資料(32)」（2011）より引用"),
    ("ikimono2.html", "鳥類", 3,
     "※丹沢大山自然環境総合調査報告書（神奈川県環境部,1997）によれば、丹沢全体で158種が確認されている。"
     "その後、宮ヶ瀬湖の出現により新たに数種類が確認されている。"
     "※渡り区分は、丹沢大山総合調査動植物目録(2007）及び 神奈川県の鳥2011-2015 "
     "神奈川県鳥類目録７（2020）を参考とした。※亜種までの分類はしていない。"),
    ("ikimono3.html", "は虫類", 3,
     "※丹沢大山自然環境総合調査報告書（神奈川県環境部、1997）より引用及び1997年以降に丹沢で確認された種を含む"),
    ("ikimono4.html", "両生類", 3,
     "※丹沢大山自然環境総合調査報告書（神奈川県環境部、1997）より引用及び1997年以降に丹沢で確認された種を含む"),
    ("ikimono5.html", "昆虫", 2,
     "※丹沢大山自然環境総合調査報告書（神奈川県環境部,1997）によれば、丹沢全体で5,727種の昆虫が確認されている。"
     "その中でコウチュウ目が2,555種で全体の45％を占め、チョウ目1,663種、ハエ目365種、カメムシ目357種と続く。"),
]

SPLIT_RE = re.compile(r"[\s　]+")


MARKER_RE = re.compile(r"^[（(]\s*(×|外来種)\s*[）)]$")


def split_species(cell):
    """空白区切りのトークン列から種名リストを作る。
    "オオカミ　(×)" のように種名と別トークンになったマーカーは直前の種名に統合する。"""
    if not isinstance(cell, str):
        return []
    cell = cell.strip()
    if not cell:
        return []
    tokens = [s for s in SPLIT_RE.split(cell) if s]
    merged = []
    for tok in tokens:
        if MARKER_RE.match(tok) and merged:
            merged[-1] = merged[-1] + tok
        else:
            merged.append(tok)
    return merged


def extract_note(name):
    """種名末尾の (×) 絶滅種 / （外来種） 等の注記を分離する"""
    note_parts = []
    m = re.search(r"[（(]\s*×\s*[）)]", name)
    if m:
        note_parts.append("絶滅種(人間の影響により絶滅した種類, ×マーク)")
        name = name[:m.start()].strip()
    m2 = re.search(r"[（(]\s*外来種\s*[）)]", name)
    if m2:
        note_parts.append("外来種(ページ内表記)")
        name = name[:m2.start()].strip()
    return name.strip(), "; ".join(note_parts)


def main():
    all_rows = []
    for fname, group_ja, ncols, footnote in PAGES:
        url = BASE + fname
        r = get(url)
        r.encoding = r.apparent_encoding
        tables = pd.read_html(io.StringIO(r.text), flavor="lxml")
        t = tables[0]
        for _, row in t.iterrows():
            if ncols == 3:
                order_ja, family_ja, species_cell = row[0], row[1], row[2]
            else:
                order_ja, species_cell = row[0], row[1]
                family_ja = ""
            order_ja = "" if pd.isna(order_ja) else str(order_ja).strip()
            family_ja = "" if pd.isna(family_ja) else str(family_ja).strip()
            for raw_name in split_species(species_cell if isinstance(species_cell, str) else ""):
                name, sp_note = extract_note(raw_name)
                if not name:
                    continue
                taxon_group_ja = "/".join([p for p in [group_ja, order_ja, family_ja] if p])
                note_ja = footnote if not sp_note else f"{sp_note} | {footnote}"
                all_rows.append({
                    "taxon_group_ja": taxon_group_ja,
                    "vernacular_name_ja": name,
                    "scientific_name": None,
                    "note_ja": note_ja,
                    "source_ref": url,
                })

    p = PROC / "tanzawa_species_list_1997.csv"
    fields = ["taxon_group_ja", "vernacular_name_ja", "scientific_name", "note_ja", "source_ref"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in all_rows:
            w.writerow(row)
    write_jsonl("tanzawa_species_list_1997", all_rows)
    print(f"  [write] {p} ({len(all_rows)} rows)")

    register(
        source_id="tanzawa_species_list_1997",
        name="丹沢のビジターセンター 生き物リスト(哺乳類/鳥類/は虫類/両生類/昆虫)",
        publisher=PUBLISHER,
        url=BASE + "ikimono1.html",
        category="丹沢(生物相・確認種リスト)",
        access_method="HTML表(pandas.read_html)を5ページ分パース",
        fmt="HTML",
        license_="要確認(ビジターセンター運営元への利用許諾確認が必要)",
        redistributable=0,
        record_count=len(all_rows),
        notes=(
            "【重要】このリストは単純に『1997年の丹沢大山自然環境総合調査に基づく確認種リスト』ではなく、"
            "分類群ごとに引用元・時点が異なる混成データである。原文の注記(※)をそのまま引用する: "
            + " || ".join(f"[{g}] {fn}" for _, g, _, fn in PAGES)
            + " 。したがって『現在の分布』ではなく、かつ分類群間で調査時点が異なるため単純比較・"
            "合算(例:総種数の算出)はできない。学名(scientific_name)はサイト上に記載がないため全行null。"
        ),
    )


if __name__ == "__main__":
    main()
