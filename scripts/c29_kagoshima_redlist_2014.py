#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鹿児島県レッドリスト（平成26年改訂。動物・植物の掲載ページは平成27年度改訂）

県サイトの 2 本の PDF（動物 24 ページ・植物藻類 57 ページ）を pdfplumber の extract_text() で
行ごとに読み、種名とカテゴリーという事実だけを CSV に起こす（PDF は data/raw に置き、再配布しない）。
罫線が無く、1 行 1 種の「和名学名」（動物は間に空白が無い／植物は空白あり＋著者名）。

読み取りの規則（件数の検算で止まるので、合わなければ規則を直す。手で直さない）:
- 見出し「分類群名」→「カテゴリー（n）」→ 種の行。カテゴリー見出しの n と読んだ行数が一致しなければ assert。
- 行の折り返し（和名・学名・括弧書きが次の行にはみ出す）は、次の行が「日本語で始まらない」「全角括弧で始まる」
  「閉じ括弧が余る」のいずれかなら前の行に連結する。植物で見出しより 2 行多かった原因はこれ
  （ホソバケラマツツジ〔Type＝Rheophyte） の折り返しと、ナガバハグマ〔nov.〕 の折り返し）。
- 学名は属・種小名・（種内の階級語＋小名）のラテン語トークンだけ。亜属の括弧・著者名・nom. nud. 等は
  scientific_name_raw にだけ残す。sp. / sp.B のように種が決まらないものは学名を空にする。
- 亜種・変種は三名法のまま持つ（二名法に縮約しない）。
"""
import sys, pathlib, re, csv, collections
sys.path.insert(0, str(pathlib.Path(__file__).parent))

SID = "kagoshima_redlist"
LIST_YEAR = 2014
EDITION = "鹿児島県レッドリスト（平成26年改訂。動物・植物の掲載ページは平成27年度改訂）"
FETCHED_PDF_UPDATED = "2021-11-02"  # PDF の更新日（取得の記録）
BASE = "http://www.pref.kagoshima.jp"
SRC = {
    "animals": {"page": BASE + "/ad04/kurashi-kankyo/kankyo/yasei/reddata/plant-list4.html",
                "pdf": BASE + "/ad04/kurashi-kankyo/kankyo/yasei/reddata/documents/53565_20211029173904-1.pdf",
                "file": "animals.pdf", "rank_required": False},
    "plants": {"page": BASE + "/ad04/kurashi-kankyo/kankyo/yasei/reddata/plant-list3.html",
               "pdf": BASE + "/ad04/kurashi-kankyo/kankyo/yasei/reddata/documents/53564_20211029183322-1.pdf",
               "file": "plants.pdf", "rank_required": True},
}
LIC = "鹿児島県ホームページ（無断転載・改変不可）。事実（種名・カテゴリー）のみ抽出し出典を明記"

COLS = ["taxon_group_ja", "taxon_subgroup_ja", "order_ja", "family_ja",
        "scientific_name", "vernacular_name_ja",
        "category_code", "category_ja", "category_prev_ja", "category_1995_ja",
        "national_category_ja", "change_from_prev_ja", "note_ja",
        "list_year", "scope", "source_id", "source_ref", "scientific_name_raw"]

# 見出しの件数（PDF 冒頭の見出し行）。読んだ行数と一致するまで止める。
# 動物 802 = 184 + 191 + 352 + 75。植物は維管束植物と藻類の見出しを足した値（612/448/806/142）。
EXPECTED = {
    "animals": {"CR+EN": 184, "VU": 191, "NT": 352, "DD": 75},
    "plants": {"CR+EN": 612, "VU": 448, "NT": 806, "DD": 142},
}

CATEGORY_CODE = {"絶滅危惧Ⅰ類": "CR+EN", "絶滅危惧Ⅱ類": "VU", "準絶滅危惧": "NT", "情報不足": "DD"}
HEAD_RE = re.compile(r"^(絶滅危惧\s*[IVⅠⅡ]+\s*類|準絶滅危惧|情報不足)\s*（(\d+)）$")
RANKS = {"subsp.", "ssp.", "var.", "f.", "forma", "subvar.", "fo."}
# 階級語なしの三名法（動物）で、種小名の次の小文字語を亜種小名に取らないための語。著者名の小辞（Uca lactea de Haan の de 等）や
# 修飾語。取るのは「この語以外の小文字のラテン語らしい語で、後に著者名（大文字始まりか括弧）か行末が続く」ときだけ。
NOT_INFRASPECIFIC = {"de", "von", "van", "der", "den", "du", "la", "le", "del", "di", "da", "dos", "ten", "ter",
                     "et", "and", "ex", "in", "non", "complex", "group", "sensu", "auct", "nom", "nud", "cf", "aff",
                     "sp", "spp"}
# PDF のフォントで潰れた字（㉀ は fi〔Moellendorffia〕、㉁ は fl〔fluviatilis・flavus・flectosiphonata〕）
GLYPH_FIX = {"㉀": "fi", "㉁": "fl"}


def norm_category(s):
    """'絶滅危惧I 類' / 'II 類' のラテン文字の I を、ローマ数字の Ⅰ・Ⅱ に直す。"""
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^絶滅危惧([IVⅠⅡ]+)類$", s)
    if m:
        r = m.group(1).replace("II", "Ⅱ").replace("I", "Ⅰ")
        return f"絶滅危惧{r}類"
    return s


def is_japanese(ch):
    return ("぀" <= ch <= "ヿ") or ("一" <= ch <= "鿿") or ch in "々"


def is_continuation(line, prev):
    """行の折り返し（前の行の続き）か。"""
    if not prev:
        return False
    if not line or not is_japanese(line[0]) or line[0] in "（(":
        return True
    # 「個体群）」のように閉じ括弧だけ余る行
    return line.count("）") + line.count(")") > line.count("（") + line.count("(")


def clean_latin(s):
    for a, b in GLYPH_FIX.items():
        s = s.replace(a, b)
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    s = re.sub(r"\b(var|subsp|ssp|f|subvar)\.(?=[A-Za-z])", r"\1. ", s)  # var.hyugana
    return re.sub(r"\s+", " ", s).strip()


def parse_scientific(latin, *, rank_required):
    """著者付きのラテン語から、属・種小名・（階級語＋）種内小名だけを取り出す。取れなければ ''。

    rank_required: True なら、種内小名は階級語（var. 等）の直後だけ（植物。著者の前置詞 de 等を拾わない）。
    False なら階級語なしの三名法（動物の Pteropus dasymallus dasymallus）も取る。"""
    s = clean_latin(latin)
    # 小名のあとに「(i Bedd.)」のように 1 字だけ括弧にはみ出す崩れ（hendersoni(i → hendersonii）。raw は直さない
    s = re.sub(r"^([A-Z][a-z]+)\(([a-z]) (?=[A-Z][a-z]+\))", r"\1\2 (", s)  # Melampu(s Melampus) → Melampus (Melampus)
    s = re.sub(r"(?<![A-Za-z])([a-z][a-z-]*)\(([a-z])(?= )", r"\1\2", s)
    if not re.match(r"[A-Z][a-z]+\b", s):  # 先頭に崩れた字がある（a_s_t_a_tCitrus depressa）
        m = re.search(r"[A-Z][a-z]+ [a-z]", s)
        s = s[m.start():] if m else s
    toks = re.findall(r"\(|\)|[^\s()]+", s)
    if not toks or not re.fullmatch(r"[A-Z][a-z]+", toks[0]):
        return ""
    i = 1
    if i < len(toks) and toks[i] == "(":  # 亜属 Satsuma (Luchuhadra) adelinae
        while i < len(toks) and toks[i] != ")":
            i += 1
        i += 1
    if i >= len(toks) or not re.fullmatch(r"[a-z][a-z-]+", toks[i]):
        return ""  # sp. / sp.B / 小名なし
    parts = [toks[0], toks[i]]
    i += 1
    while i < len(toks):
        t = toks[i]
        if t in RANKS and i + 1 < len(toks) and re.fullmatch(r"[a-z][a-z-]+", toks[i + 1]):
            parts += [t, toks[i + 1]]
            i += 2
        elif (not rank_required and not any(p in RANKS for p in parts) and re.fullmatch(r"[a-z][a-z-]+", t)
              and t not in NOT_INFRASPECIFIC
              and (i + 1 == len(toks) or toks[i + 1] == "(" or toks[i + 1][0].isupper())):
            parts.append(t)
            i += 1
        else:
            break
    return " ".join(parts)


def split_vernacular(line):
    """'和名学名...' を (和名, ラテン語部分) に分ける。最初の ASCII 英字から先がラテン語。"""
    m = re.search(r"[A-Za-z]", line)
    if not m:
        return line.strip(), ""
    return line[:m.start()].strip(" _\t"), line[m.start():].strip()


def parse_pdf_lines(rank_required, lines, groups_known):
    """lines: [(page_no, text)]。戻り値: (rows, counts, declared)。rows は dict の並び。
    rank_required: parse_scientific に渡す（植物 True・動物 False）。"""
    rows, counts = [], collections.Counter()
    group = cat = None
    declared = {}
    # 見出し行を先に確定させてから連結する（見出しの直後の行を連結に巻き込まない）
    merged = []
    for pg, t in lines:
        t = t.strip()
        if not t:
            continue
        if HEAD_RE.match(t) or t in groups_known:
            merged.append([pg, t, "head"])
        elif merged and merged[-1][2] == "row" and is_continuation(t, merged[-1][1]):
            merged[-1][1] += " " + t
        else:
            merged.append([pg, t, "row"])
    for pg, t, kind_ in merged:
        if kind_ == "head":
            m = HEAD_RE.match(t)
            if m:
                cat = norm_category(m.group(1))
                declared[(group, cat)] = int(m.group(2))
            else:
                group, cat = t, None
            continue
        assert group and cat, f"見出しの前に行がある: p{pg} {t!r}"
        verna, latin = split_vernacular(t)
        rows.append({"taxon_group_ja": group, "category_ja": cat, "category_code": CATEGORY_CODE[cat],
                     "vernacular_name_ja": verna,
                     "scientific_name": parse_scientific(latin, rank_required=rank_required),
                     "scientific_name_raw": clean_latin(latin), "page": pg})
        counts[(group, cat)] += 1
    return rows, counts, declared


def make_row(*, group, family="", verna, sci, raw, cat, ref, year, sid, moe):
    """CSV の 1 行（c29・c29b 共通。列は COLS）。cat は category_ja（空なら category_code も空）。"""
    return {
        "taxon_group_ja": group, "taxon_subgroup_ja": "", "order_ja": "", "family_ja": family,
        "scientific_name": sci, "vernacular_name_ja": verna,
        "category_code": CATEGORY_CODE.get(cat, ""), "category_ja": cat,
        "category_prev_ja": "", "category_1995_ja": "",
        "national_category_ja": moe.get(sci, "") if sci else "",
        "change_from_prev_ja": "", "note_ja": "",
        "list_year": year, "scope": "kagoshima", "source_id": sid,
        "source_ref": ref, "scientific_name_raw": raw,
    }


def assert_list_matches_registry(list_id, year, name=None):
    """list_year（と名前）が registry/taxon/assessment_list.yaml と一致すること（c28 は yaml を正に読む）。"""
    from registry.build_taxon_assessment import load_assessment_lists
    e = load_assessment_lists()[list_id]
    assert e["year"] == year, f"{list_id}: yaml の year {e['year']} と {year} が違う"
    assert name is None or e["name"] == name, f"{list_id}: yaml の name {e['name']!r} と {name!r} が違う"


def read_pdf_lines(path):
    import pdfplumber
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for i, p in enumerate(pdf.pages, start=1):
            for l in (p.extract_text() or "").split("\n"):
                out.append((i, l))
    return out


def load_moe_names(path):
    """学名 → 環境省カテゴリー（学名が完全一致し、カテゴリーが 1 通りに決まるものだけ）。"""
    names = collections.defaultdict(set)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["scientific_name"]:
                names[r["scientific_name"].strip()].add(r["category_ja"])
    return {k: next(iter(v)) for k, v in names.items() if len(v) == 1}


def main():
    from common import download, register, PROC, RAW
    assert_list_matches_registry("kgrl2014", LIST_YEAR, EDITION)
    rawd = RAW / "kagoshima_redlist_2014"
    moe = load_moe_names(PROC / "moe_redlist.csv")
    out, total_by_kind = [], {}
    for kind, s in SRC.items():
        p = download(s["pdf"], rawd / s["file"])
        lines = read_pdf_lines(p)
        rows, counts, declared = parse_pdf_lines(s["rank_required"], lines, _group_names(lines))
        # 検算: カテゴリー見出しの件数（植物は維管束植物＋藻類）と読んだ行数。分類群×カテゴリーごと、合計は想定値
        want = collections.Counter()
        for (g, c), n in declared.items():
            assert counts[(g, c)] == n, f"{kind} {g} {c}: 見出し {n} と読んだ {counts[(g, c)]}"
            want[CATEGORY_CODE[c]] += n
        assert dict(want) == EXPECTED[kind], f"{kind}: 想定の件数と違う {dict(want)}"
        total_by_kind[kind] = len(rows)
        out += [make_row(group=r["taxon_group_ja"], verna=r["vernacular_name_ja"], sci=r["scientific_name"],
                         raw=r["scientific_name_raw"], cat=r["category_ja"],
                         ref=f"{s['pdf']}#page={r['page']}", year=LIST_YEAR, sid=SID, moe=moe) for r in rows]
    # 同じ (和名, 学名, カテゴリー) の重複は 1 行にする
    seen, dedup = set(), []
    for r in out:
        k = (r["vernacular_name_ja"], r["scientific_name"], r["category_ja"])
        if k not in seen:
            seen.add(k)
            dedup.append(r)
    print(f"  [rows] {len(out)} 行 → 重複除去後 {len(dedup)}（動物 {total_by_kind['animals']}／植物 {total_by_kind['plants']}）")
    dest = PROC / "kagoshima_redlist.csv"
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(dedup)
    register(SID, EDITION, "鹿児島県 環境林務部 自然保護課",
             SRC["animals"]["page"], "希少種・保全ランク", "PDF（pdfplumber）", "PDF", LIC, 0, len(dedup),
             f"動物PDF {total_by_kind['animals']}行・植物藻類PDF {total_by_kind['plants']}行。PDFの更新日 {FETCHED_PDF_UPDATED}。"
             "カテゴリー見出しの件数と一致を確認。PDFは data/raw に置き再配布しない。")
    print("done.")


def _group_names(lines):
    """分類群名の行: 日本語だけの短い行で、直後がカテゴリー見出し（折り返しの断片は除く）。"""
    texts = [t.strip() for _, t in lines if t.strip()]
    return {texts[i] for i in range(len(texts) - 1)
            if HEAD_RE.match(texts[i + 1]) and not HEAD_RE.match(texts[i])
            and not re.search(r"[A-Za-z]", texts[i])}


if __name__ == "__main__":
    main()
