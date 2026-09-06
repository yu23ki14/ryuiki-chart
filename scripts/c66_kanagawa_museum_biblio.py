"""神奈川県立生命の星・地球博物館 刊行物目録: 神奈川自然誌資料 バックナンバー書誌データ収集

対象: https://nh.kanagawa-museum.jp/publications/nhr/ 配下の各号ページ (nhr-1.html 〜 nhr-47.html)
目的: 論文PDF本体はダウンロードせず、号・タイトル・著者・ページ・PDF直リンクの書誌目録(CSV/JSONL)を作る。

出力: data/processed/kanagawa_shizenshi_bibliography.csv / .jsonl
source_id: kanagawa_shizenshi_bibliography
"""
import re
import sys
import urllib.parse
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import get, register, write_jsonl, PROC, now

from bs4 import BeautifulSoup

BASE = "https://nh.kanagawa-museum.jp"
INDEX_URL = f"{BASE}/publications/nhr/index.html"
SOURCE_ID = "kanagawa_shizenshi_bibliography"

MAX_VOLUME_GUESS = 47  # index.htmlから抽出した最大号数(実測)。念のためindexページから動的に取得もする。

FRONT_MATTER_TITLES = {
    "表紙・目次", "奥付", "目次", "Cover and contents", "Imprint",
}

TAXON_RULES = [
    ("哺乳類", ["コウモリ", "アナグマ", "タヌキ", "イルカ", "クジラ", "鰭脚", "アザラシ",
               "シカ", "イノシシ", "哺乳類", "ハクジラ", "アシカ"]),
    ("鳥類", ["鳥類", "ウミガラス", "カモ", "ワシ", "タカ", "サギ", "留鳥", "渡り鳥"]),
    ("爬虫類・両生類", ["イモリ", "カメ", "トカゲ", "ヘビ", "カエル", "爬虫類", "両生類", "ウミガメ"]),
    ("魚類", ["魚類", "魚市場", "マサバ", "ゴマサバ", "ハタンポ", "ザメ", "エイ", "ウナギ", "ボラ",
             "メナダ", "マダイ", "クロダイ", "キダイ", "ドジョウ", "ハゼ", "ヨシノボリ", "カレイ",
             "フグ", "コバン", "テンハギ", "テングハギ", "シュモクザメ", "スズキ目", "軟骨魚",
             "硬骨魚"]),
    ("昆虫", ["昆虫", "チョウ", "トンボ", "ハチ", "アブ", "カミキリ", "セミ", "ブユ", "蛾",
             "ゴキブリ", "バッタ", "甲虫", "膜翅目", "鱗翅目", "双翅目"]),
    ("甲殻類・軟体動物等無脊椎動物", ["エビ", "カニ", "ヤドカリ", "ウミウシ", "貝", "ヨコエビ",
                          "等脚", "端脚", "十脚目", "軟体動物", "甲殻", "イガイ", "アサリ",
                          "ヤスデ", "多足類", "クモ"]),
    ("菌類・藻類・コケ", ["菌類", "キノコ", "糸状菌", "藻類", "海藻", "コケ植物", "ゼニゴケ",
                    "蘚苔類"]),
    ("植物（維管束植物）", ["植物", "スミレ", "ラン科", "タンポポ", "帰化植物", "シダ",
                   "カワラノギク", "腊葉標本", "植物相"]),
    ("地質・鉱物・化石", ["地質", "鉱物", "化石", "テフラ", "層群", "露頭", "地層",
                  "更新統", "貝化石"]),
]


def guess_taxon(title_ja):
    if not title_ja:
        return None
    for label, keywords in TAXON_RULES:
        for kw in keywords:
            if kw in title_ja:
                return label
    return None


def clean_text(s):
    if s is None:
        return None
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = s.strip(" 　\t\n")
    return s or None


def split_title_author(cell_text):
    """'原著論文：タイトル\n　著者1・著者2' のような1論文分のテキストブロックを
    (article_type_ja, title_ja, authors_ja) に分解する。"""
    text = cell_text.strip()
    # 著者行は全角スペース(　)で始まることが多いので、それを区切りに使う。
    # まず改行で分割し、最後の行を著者行とみなす（複数行タイトルに対応）。
    lines = [l for l in re.split(r"\n+", text) if l.strip() != ""]
    if not lines:
        return None, None, None
    if len(lines) == 1:
        # 著者行が分離できないケース：区切りが無い
        title_line = lines[0]
        author_line = None
    else:
        author_line = lines[-1]
        title_line = " ".join(l.strip() for l in lines[:-1])
    article_type = None
    m = re.match(r"^(総説|原著論文|報告|短報|資料)[：:]\s*(.*)$", title_line)
    if m:
        article_type, title_line = m.group(1), m.group(2)
    title_ja = clean_text(title_line)
    authors_ja = clean_text(author_line.lstrip("　 ")) if author_line else None
    return article_type, title_ja, authors_ja


def _linebreak_to_newline(tag):
    """<br> をNavigableStringの改行に置き換えてからテキスト化する。
    (get_text(separator=...)は<em>/<span>等インラインタグの境界にも区切り文字を
    挿入してしまい、学名の斜体表記などが分断されるため、<br>だけを明示的に改行化する)"""
    tag = BeautifulSoup(str(tag), "html.parser")
    for br in tag.find_all("br"):
        br.replace_with("\n")
    return tag.get_text("")


def cell_to_lines(td):
    """<td> 内の <p> 区切り、無ければ <br> 区切りでテキストブロックのリストを返す。"""
    ps = td.find_all("p", recursive=False)
    blocks = []
    if ps:
        for p in ps:
            blocks.append(_linebreak_to_newline(p))
    else:
        # <br>区切りの1ブロックとして扱う
        blocks.append(_linebreak_to_newline(td))
    return blocks


def is_japanese_block(block):
    return bool(re.search(r"[ぁ-んァ-ヶ一-龠]", block))


def extract_year(page_text):
    """号ページ冒頭の発行日表記から西暦年を取り出す。
    印刷物発行日があればそれを優先、無ければ公開日を使う。"""
    print_m = re.search(r"((?:19|20)\d{2})年\d{1,2}月\d{1,2}日\s*印刷物発行", page_text)
    if print_m:
        return int(print_m.group(1)), print_m.group(0)
    pub_m = re.search(r"((?:19|20)\d{2})年\d{1,2}月\d{1,2}日\s*(?:公開|オンライン版公開)", page_text)
    if pub_m:
        return int(pub_m.group(1)), pub_m.group(0)
    any_m = re.search(r"(?:19|20)\d{2}", page_text)
    if any_m:
        return int(any_m.group(0)), any_m.group(0)
    return None, None


def parse_volume(vol, url):
    r = get(url)
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.find(id="main")
    if main is None:
        return [], None, "id=main が見つからない"

    body_text = main.get_text("\n", strip=True)
    year, year_raw = extract_year(body_text[:800])

    table = main.find("table")
    if table is None:
        return [], year, "table が見つからない"

    rows = table.find_all("tr")
    records = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue  # thead行 (th のみ) はスキップ
        if len(tds) == 3:
            title_td, page_td, link_td = tds
            page_text_raw = page_td.get_text(strip=True)
            link_a = link_td.find("a", href=True)
        elif len(tds) == 2:
            title_td, combo_td = tds
            link_a = combo_td.find("a", href=True)
            # ページ表記は combo_td から <a>(ダウンロードリンク)を取り除いた残りのテキスト
            combo_clone = BeautifulSoup(str(combo_td), "html.parser")
            for a in combo_clone.find_all("a"):
                a.decompose()
            for br in combo_clone.find_all("br"):
                br.replace_with("\n")
            page_text_raw = clean_text(combo_clone.get_text(""))
        else:
            continue

        blocks = cell_to_lines(title_td)
        ja_blocks = [b for b in blocks if is_japanese_block(b)]
        first_block = clean_text(blocks[0]) if blocks else None
        if first_block in FRONT_MATTER_TITLES:
            continue  # 表紙・目次・奥付など、論文でない行はスキップ
        if not page_text_raw:
            continue  # ページ番号が無い(=目次PDFなど)行はスキップ
        if not ja_blocks:
            continue

        combined_ja = "\n".join(ja_blocks)
        article_type_ja, title_ja, authors_ja = split_title_author(combined_ja)
        if not title_ja:
            continue

        pdf_url = urllib.parse.urljoin(url, link_a["href"]) if link_a is not None else None

        records.append({
            "source_id": SOURCE_ID,
            "source_ref": pdf_url or f"{url}#row",
            "volume": vol,
            "year": year,
            "year_raw": year_raw,
            "article_type_ja": article_type_ja,
            "title_ja": title_ja,
            "authors_ja": authors_ja,
            "pages_raw": clean_text(page_text_raw),
            "pdf_url": pdf_url,
            "taxon_group_guess": guess_taxon(title_ja),
            "issue_page_url": url,
            "fetched_at": now(),
        })
    return records, year, None


def get_volume_list():
    r = get(f"{BASE}/publications/nhr/")
    soup = BeautifulSoup(r.text, "html.parser")
    vols = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"/publications/nhr/nhr-(\d+)\.html", a["href"])
        if m:
            vols[int(m.group(1))] = urllib.parse.urljoin(BASE, a["href"])
    return vols


def main():
    vol_urls = get_volume_list()
    if not vol_urls:
        register(SOURCE_ID, "神奈川自然誌資料 バックナンバー書誌目録",
                  "神奈川県立生命の星・地球博物館", INDEX_URL, "publication_bibliography",
                  "html_scrape", "csv/jsonl", "著作権:神奈川県立生命の星・地球博物館(要出典表記)",
                  1, 0, notes="一覧ページから号一覧を取得できなかった。人間の確認が必要。")
        print("号一覧が取得できませんでした")
        return

    all_records = []
    failed_vols = []
    vols_sorted = sorted(vol_urls)
    for vol in vols_sorted:
        url = vol_urls[vol]
        try:
            recs, year, err = parse_volume(vol, url)
            if err:
                failed_vols.append((vol, err))
                print(f"  [warn] 第{vol}号: {err}")
                continue
            all_records.extend(recs)
            print(f"  第{vol}号 ({year}): {len(recs)} 論文")
        except Exception as e:
            failed_vols.append((vol, repr(e)))
            print(f"  [error] 第{vol}号: {e!r}")

    # CSV/JSONL 出力
    import csv
    cols = ["source_id", "source_ref", "volume", "year", "year_raw", "article_type_ja",
            "title_ja", "authors_ja", "pages_raw", "pdf_url", "taxon_group_guess",
            "issue_page_url", "fetched_at"]
    csv_path = PROC / f"{SOURCE_ID}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in all_records:
            w.writerow(r)
    print(f"  [write] {csv_path} {len(all_records)} rows")
    write_jsonl(SOURCE_ID, all_records)

    got_min = min(vols_sorted) if vols_sorted else None
    got_max = max(vols_sorted) if vols_sorted else None
    ok_vols = sorted(set(vols_sorted) - {v for v, _ in failed_vols})
    notes = (
        f"取得号範囲: 第{min(ok_vols) if ok_vols else '-'}号〜第{max(ok_vols) if ok_vols else '-'}号"
        f"（サイト掲載全{len(vols_sorted)}号のうち{len(ok_vols)}号を取得）。"
        f"失敗号: {failed_vols if failed_vols else 'なし'}。"
        "PDF本体はダウンロードせず、書誌メタデータ(号・タイトル・著者・ページ・PDF直リンク)のみを"
        "目録化したもの。論文タイトル・著者名は当館サイト掲載の原表記の引用であり、これらの短い書誌情報の"
        "転記は著作権法上の『引用』の範囲内と考えられるが、PDF本体（論文の本文・図版）自体はこのリポジトリに"
        "含めていない。taxon_group_guessはタイトル文字列からのキーワードによる自動推測であり、"
        "分類群の正式な同定ではない（原著者による分類学的判断ではない）。"
        "年(year)は号ページ冒頭の発行日表記（印刷物発行日を優先、無ければオンライン公開日）から抽出。"
        "本誌は41号よりオンライン版のみの発行となり、印刷物発行日の記載が無くなっている号がある"
        "（該当号はオンライン公開日をyearとして使用）。"
    )
    register(
        SOURCE_ID,
        "神奈川自然誌資料 バックナンバー書誌目録（論文タイトル・著者・ページ・PDFリンク）",
        "神奈川県立生命の星・地球博物館",
        INDEX_URL,
        "publication_bibliography",
        "html_scrape",
        "csv/jsonl",
        "サイト著作権表記: 『当サイトに掲載されているコンテンツ（文章、イラスト、写真、動画など）は、"
        "著作権の対象となっています。「引用」等の著作権法上認められている範囲において自由にご利用になれます。"
        "コンテンツを利用する際には、出典を記載してください。』(© Kanagawa Prefectural Museum of "
        "Natural History, https://nh.kanagawa-museum.jp/sitepolicy/)。"
        "本データセットはPDF本体を含まず書誌情報(目録)のみ。",
        1,
        len(all_records),
        notes=notes,
    )


if __name__ == "__main__":
    main()
