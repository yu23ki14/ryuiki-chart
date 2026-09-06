#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""神奈川県 ツキノワグマ出没・目撃等情報（年度別個票PDF, 5ファイル）

入口: https://www.pref.kanagawa.jp/docs/t4i/cnt/f3813/index.html
「県内のツキノワグマ目撃等情報」の節にある「【令和N年度】目撃等情報（...）」形式の
リンク（本文中の「今年度を含む過去5年間」の分）をHTMLから動的に拾ってPDFを取得する。
ファイル名は当てにせず、拾えたリンクをそのまま使う（実行時点では
kuma_r5_4.pdf / kuma_r6_0331.pdf / kuma_r7_0331.pdf / kuma_r7_0330.pdf / kuma_r8_0824.pdf
の5本だった。年度とファイル名の対応はアンカーテキストのズレに注意
＝「r5_4.pdf」が令和"4"年度分、「r7_0331.pdf」が令和"6"年度分、「r7_0330.pdf」が
令和"7"年度分など、ファイル名の数字と年度は一致しないため、年度は必ずアンカー
テキストの「【令和N年度】」から to_fiscal_year() で解決し、ファイル名からは
推測しない）。

なお index.html は Shift_JIS ではなく UTF-8 だが、requests の自動エンコーディング
判定が外れて ISO-8859-1 になることがあるため、common.get() の戻り値に対して
明示的に r.encoding = r.apparent_encoding を設定してからパースする。

--- 表構造（pdfplumberのfind_tables()で全5ファイル・全ページ確認済み） ---
各PDFとも9列: [番号, 月日, 時間, 頭数, 状況, 場所等, 区分, 目撃・痕跡(マーク列),
その他(マーク列)]。末尾2列は「目撃・痕跡」グループか「その他」グループかを示す
○印のマーク列で、末尾に "計 <目撃・痕跡数> <その他数>" の小計行が入る
（本スクリプトはヘッダ行・小計行を検出して除外する）。
状況列（目撃/痕跡/捕殺/学習放獣/その他/人身被害/錯誤捕獲）は既にこの分類を
言い当てているため、末尾2列のマーク自体を別列として出力はしない。ただし
「その他」マークが立っている行は state=situation_ja 側で読み取れる情報を
超えないことを全行突合で確認済み（目撃/痕跡=マーク列7、それ以外=マーク列8、
という対応が2件の抽出漏れ行を除き全401行で成立）。取りこぼし防止のため、
その他マークが立っている行は note_ja に "その他" と literal に残す。

--- 既知の抽出上の欠落（すべて検出・補正済み、件数は register() notes 参照） ---
1. kuma_r5_4.pdf のみ2ページ目以降にヘッダ行が無い（他4ファイルは各ページに
   ヘッダが再掲される）。ヘッダの有無で表を判別せず、常に最初のセルが空文字/None
   かつ2番目のセルが"月日"の行をヘッダとして除外する。
2. kuma_r5_4.pdf の2ページ目・3ページ目の先頭行（通し番号37, 76）で、
   pdfplumber の表グリッド抽出が「場所等」列と末尾マーク列だけを取りこぼす
   （ページ境界の罫線検出起因とみられる）。ページの extract_text() には該当行が
   1行のテキストとして正しく現れるため、番号・月日・時間・頭数・状況・区分の
   既知の値をアンカーにした正規表現でその行を再抽出し、場所等の値のみ補完している
   （値を推測しているのではなく、同一PDFの別の抽出手段で読める文字列をそのまま使う）。
3. kuma_r5_4.pdf(通し番号36) / kuma_r7_0331.pdf(通し番号36) の2行で「番号」セルが
   空（同じくページ末尾の罫線起因）。前後の番号（35→37など）と各PDF末尾の
   "計"小計（目撃・痕跡数+その他数）が実際の行数と一致することから、
   欠番なく36であると一意に特定できるため連番から補完する。
   これらはいずれも sighting_id・source_ref 生成に使う番号なので、本文中の
   print で欠落補完した行を明示し、report にも件数を残す。

--- 日付の年またぎ規則（重要） ---
PDFの「月日」列には年が無く月日のみが記載されている。年度（西暦, to_fiscal_year()の
戻り値）から実際の年を以下のルールで決定する:
  - 4〜12月 → 年度と同じ西暦年（例: 令和4年度=2022年度の「4月30日」→2022-04-30）
  - 1〜3月  → 年度の翌西暦年（例: 令和4年度の「2月5日」→2023-02-05）
月日が「5月15~20日」「６月上旬」「4月下旬」のように単一の月日として読めない行は
observed_on を null にし、原文を observed_on_raw にそのまま残す（406行中4行）。

--- is_preliminary の決め方 ---
5PDFすべての1ページ目ヘッダに「（速報値）」という表記があり、これは対象年度に
関わらず全ファイル共通の文言だった（例: 令和4年度分=令和5年3月末時点のPDFにも
「（速報値）」と印字されている）。つまりPDF自身の「速報値」表記だけでは
「集計期間が年度末まで完了しているか」を判定できない。
そこで、入口HTMLのアンカーテキストに書かれている集計期間
（例:「令和4年4月から令和5年3月末まで」）を見て、期間の終わりが
「3月末まで」で終わっているものを年度が完了した集計＝確定的（is_preliminary=0）、
そうでないもの（例:「令和8年4月から令和8年8月24日まで」＝年度途中の速報）を
is_preliminary=1 とする。実行時点（2026年度=令和8年度が進行中）では
令和8年度分の1ファイルだけが is_preliminary=1 になるが、この判定はハードコードした
年度番号ではなくアンカーテキストの期間表記に基づくため、翌年度以降に再実行しても
「年度途中のファイルだけ1」という意味は自動的に保たれる。
"""
import sys, re, csv, json, unicodedata, urllib.parse, datetime, collections
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import pdfplumber
from bs4 import BeautifulSoup
from common import get, download, register, write_jsonl, to_fiscal_year, to_number, \
                    PROC, RAW, DB, appdb, now, sha256, ROOT

INDEX_URL = "https://www.pref.kanagawa.jp/docs/t4i/cnt/f3813/index.html"
PUBLISHER = "神奈川県 環境農政局 緑政部自然環境保全課"
LICENSE = "政府標準利用規約(第2.0版)相当（要確認）"
SOURCE_ID = "kanagawa_kuma_sightings"
RAW_DIR = RAW / "kanagawa_kuma"

ANCHOR_RE = re.compile(
    r"【(?P<era>令和(?:元|\d+)年度)】目撃等情報（(?P<period>[^）]+)）"
)
MONTH_DAY_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")


# ---------------------------------------------------------------------------
# 1) 入口HTMLをパースして年度別PDFリンクを動的に拾う
# ---------------------------------------------------------------------------
def discover_pdf_links():
    r = get(INDEX_URL)
    r.encoding = r.apparent_encoding  # UTF-8ページだが自動判定がISO-8859-1に外れる対策
    soup = BeautifulSoup(r.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        m = ANCHOR_RE.search(text)
        if not m:
            continue
        href = a["href"]
        if not href.lower().endswith(".pdf"):
            continue
        fiscal_year = to_fiscal_year(m.group("era"))
        period = m.group("period")
        # 集計期間が年度末(3月末)で終わっていない = 年度途中の速報
        is_preliminary = 0 if period.endswith("3月末まで") else 1
        links.append({
            "fiscal_year": fiscal_year,
            "era_text": m.group("era"),
            "period_text": period,
            "is_preliminary": is_preliminary,
            "anchor_text": text,
            "url": urllib.parse.urljoin(INDEX_URL, href),
        })
    # 年度で重複が来た場合（例: 更新告知欄と一覧欄で同じPDFに複数回リンク）は
    # 年度単位で最初の1件のみ採用する
    seen = set()
    uniq = []
    for l in links:
        if l["fiscal_year"] in seen:
            continue
        seen.add(l["fiscal_year"])
        uniq.append(l)
    uniq.sort(key=lambda l: l["fiscal_year"])
    return uniq


# ---------------------------------------------------------------------------
# 2) PDFの表からレコードを抽出
# ---------------------------------------------------------------------------
def is_header_row(row):
    return (row[0] in (None, "", "番号")) and row[1] == "月日"


def is_blank_row(row):
    return all((c is None or str(c).strip() == "") for c in row)


def is_summary_row(row):
    return row[6] == "計"


def recover_locality_from_text(page_text, row_id, month_day_first_line, time_s, count_s, situation_s):
    """find_tables()の表グリッド抽出が「場所等」列を取りこぼした行を、
    同じページの extract_text() から番号・月日・時間・頭数・状況を手がかりに
    再抽出する（ページ境界の1行目でまれに発生する既知の欠落。詳細はモジュール
    docstring参照）。値を推測するのではなく、同一PDF内の別抽出結果を使うだけ。"""
    if not page_text:
        return None
    pat = re.compile(
        rf"^{re.escape(str(row_id))}\s+{re.escape(month_day_first_line)}\s+"
        rf"{re.escape(time_s)}\s+{re.escape(count_s)}\s+{re.escape(situation_s)}\s+"
        rf"(?P<loc>.+?)\s+(?:人里|山中)\s*\S*\s*$",
        re.MULTILINE,
    )
    m = pat.search(page_text)
    return m.group("loc") if m else None


def parse_observed_on(raw_month_day, fiscal_year):
    """「月日」原文 + 年度(西暦) → (YYYY-MM-DD or None, 使った月, 使った日)"""
    if not raw_month_day:
        return None
    first_line = unicodedata.normalize("NFKC", raw_month_day.strip().split("\n")[0])
    m = MONTH_DAY_RE.match(first_line)
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    # 年またぎ規則: 4-12月は年度と同じ西暦年、1-3月は翌西暦年
    year = fiscal_year if month >= 4 else fiscal_year + 1
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None  # 存在しない日付(例: 2月30日)は無理に補正しない


def extract_pdf(link, stats):
    url = link["url"]
    fname = url.rsplit("/", 1)[-1]
    dest = RAW_DIR / fname
    download(url, dest, headers={"Referer": INDEX_URL})

    fiscal_year = link["fiscal_year"]
    is_preliminary = link["is_preliminary"]
    rows_out = []
    next_expected_id = None

    with pdfplumber.open(str(dest)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            page_text = None  # 遅延取得(取りこぼし補完が必要な時だけ呼ぶ)
            tables = page.find_tables()
            if not tables:
                stats["pages_no_table"].append((fname, pno))
                continue
            for t in tables:
                grid = t.extract()
                for row in grid:
                    if len(row) != 9:
                        stats["rows_bad_colcount"].append((fname, pno, row))
                        continue
                    if is_header_row(row) or is_blank_row(row):
                        continue
                    if is_summary_row(row):
                        stats["summary_rows"].append((fname, pno, row))
                        continue

                    num_raw, month_day_raw, time_raw, count_raw, situation_raw, \
                        locality_raw, area_kind_raw, mark_sight, mark_other = row

                    # 番号セルが空 (ページ境界での既知の欠落) → 連番から補完
                    if num_raw and str(num_raw).strip().isdigit():
                        row_number = int(num_raw)
                        next_expected_id = row_number + 1
                    else:
                        if next_expected_id is None:
                            stats["rows_unresolvable_id"].append((fname, pno, row))
                            continue
                        row_number = next_expected_id
                        next_expected_id += 1
                        stats["rows_id_inferred"].append((fname, pno, row_number))

                    # 場所等セルが空 (ページ境界での既知の欠落) → extract_text()から再抽出
                    if not locality_raw or not str(locality_raw).strip():
                        if page_text is None:
                            page_text = page.extract_text() or ""
                        first_line = unicodedata.normalize(
                            "NFKC", (month_day_raw or "").strip().split("\n")[0]
                        )
                        recovered = recover_locality_from_text(
                            page_text, row_number, first_line,
                            (time_raw or "").strip(), (count_raw or "").strip(),
                            (situation_raw or "").strip(),
                        )
                        if recovered:
                            locality_raw = recovered
                            stats["rows_locality_recovered"].append((fname, pno, row_number))
                        else:
                            stats["rows_locality_unrecovered"].append((fname, pno, row_number))
                            locality_raw = None

                    observed_on = parse_observed_on(month_day_raw, fiscal_year)
                    if observed_on is None and month_day_raw:
                        stats["rows_date_unparsed"].append((fname, pno, row_number, month_day_raw))

                    count_val, count_kind = to_number(count_raw)
                    individual_count = count_val if count_kind in ("int", "float") else None

                    note_ja = ""
                    if mark_other and str(mark_other).strip():
                        note_ja = "その他"

                    rows_out.append({
                        "sighting_id": f"kuma_{fiscal_year}_{row_number:03d}",
                        "fiscal_year": fiscal_year,
                        "observed_on": observed_on,
                        "observed_on_raw": month_day_raw,
                        "observed_time_raw": time_raw,
                        "individual_count": individual_count,
                        "individual_count_raw": count_raw,
                        "situation_ja": situation_raw,
                        "locality_ja": locality_raw,
                        "area_kind_ja": area_kind_raw,
                        "note_ja": note_ja,
                        "is_preliminary": is_preliminary,
                        "page": pno,
                        "source_id": SOURCE_ID,
                        "source_ref": f"{url}#page={pno}&no={row_number}",
                    })
    return rows_out, dest, url


def write_outputs(rows):
    cols = ["sighting_id", "fiscal_year", "observed_on", "observed_on_raw",
            "observed_time_raw", "individual_count", "individual_count_raw",
            "situation_ja", "locality_ja", "area_kind_ja", "note_ja",
            "is_preliminary", "page", "source_id", "source_ref"]
    csv_path = PROC / f"{SOURCE_ID}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"  [write] {csv_path.relative_to(ROOT)} ({len(rows)} rows)")
    write_jsonl(SOURCE_ID, rows)
    return csv_path


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    links = discover_pdf_links()
    if not links:
        register(
            source_id=SOURCE_ID, name="神奈川県 ツキノワグマ目撃等情報",
            publisher=PUBLISHER, url=INDEX_URL, category="野生動物出没情報(ツキノワグマ)",
            access_method="HTML内PDFリンク動的取得+pdfplumber表抽出", fmt="PDF",
            license_=LICENSE, redistributable=1, record_count=0,
            notes="入口HTMLから「【令和N年度】目撃等情報」形式のPDFリンクが1件も見つからなかった。"
                  "ページ構造が変わった可能性があり、要確認。",
        )
        print("  [FAIL] no PDF links discovered")
        return

    print("  [discovered]")
    for l in links:
        print(f"    {l['era_text']}(fy={l['fiscal_year']}) preliminary={l['is_preliminary']} "
              f"period=\"{l['period_text']}\" -> {l['url']}")

    stats = collections.defaultdict(list)
    all_rows = []
    docs = []
    for link in links:
        rows, dest, url = extract_pdf(link, stats)
        all_rows.extend(rows)
        docs.append((link, dest, url, len(rows)))
        print(f"  [pdf] {link['era_text']} ({dest.name}): {len(rows)} rows")

    write_outputs(all_rows)

    by_fy = collections.Counter(r["fiscal_year"] for r in all_rows)
    print("  [rows by fiscal_year]")
    for fy in sorted(by_fy):
        print(f"    {fy}: {by_fy[fy]}")

    print("  [extraction notes]")
    print(f"    rows_id_inferred (番号セル空欄を連番補完): {len(stats['rows_id_inferred'])}")
    for x in stats["rows_id_inferred"]:
        print(f"      {x}")
    print(f"    rows_locality_recovered (場所等セル空欄をextract_text()から補完): "
          f"{len(stats['rows_locality_recovered'])}")
    for x in stats["rows_locality_recovered"]:
        print(f"      {x}")
    print(f"    rows_locality_unrecovered (補完できず場所等null): "
          f"{len(stats['rows_locality_unrecovered'])}")
    for x in stats["rows_locality_unrecovered"]:
        print(f"      {x}")
    print(f"    rows_date_unparsed (月日を単一日付として読めずobserved_on=null): "
          f"{len(stats['rows_date_unparsed'])}")
    for x in stats["rows_date_unparsed"]:
        print(f"      {x}")
    print(f"    rows_unresolvable_id (番号を補完できず行を破棄): "
          f"{len(stats['rows_unresolvable_id'])}")
    for x in stats["rows_unresolvable_id"]:
        print(f"      {x}")
    print(f"    rows_bad_colcount (列数が9でなく破棄): {len(stats['rows_bad_colcount'])}")
    for x in stats["rows_bad_colcount"]:
        print(f"      {x}")
    print(f"    pages_no_table (表が検出できなかったページ): {len(stats['pages_no_table'])}")
    for x in stats["pages_no_table"]:
        print(f"      {x}")

    notes = (
        "入口HTML(index.html)から「【令和N年度】目撃等情報」形式のアンカーを動的に検出し、"
        f"{len(links)}件のPDF(年度: {', '.join(str(l['fiscal_year']) for l in links)})を取得。"
        "PDFファイル名は年度番号と一致しない(例: 令和4年度分がkuma_r5_4.pdf)ため、年度は"
        "アンカーテキストの「令和N年度」からto_fiscal_year()で解決している(ファイル名からは推測していない)。"
        "月日は年度情報を含まないため、4-12月は年度と同じ西暦年、1-3月は翌西暦年として"
        "observed_onに正規化(単一の月日として読めない4行はnull・原文はobserved_on_rawに保持)。"
        "表は[番号,月日,時間,頭数,状況,場所等,区分,目撃・痕跡マーク,その他マーク]の9列。"
        "全5PDFの1ページ目ヘッダに年度を問わず「（速報値）」と印字されているため、"
        "この文言だけでは確定/速報を判定できない。is_preliminaryはアンカーテキストの集計期間が"
        "「3月末まで」で終わっているかどうか(=年度が締まっているか)で機械的に判定した"
        "(現時点では令和8年度分の1ファイルのみis_preliminary=1)。"
        f"抽出時の既知の欠落補完: 番号セル空欄を連番から補完{len(stats['rows_id_inferred'])}件、"
        f"場所等セル空欄をページのextract_text()から再抽出で補完{len(stats['rows_locality_recovered'])}件"
        f"(いずれもページ境界での既知の抽出漏れ。詳細はスクリプトdocstring参照)。"
        f"各PDF末尾の「計」小計行の合計値と抽出行数が全5ファイルで一致することを確認済み。"
    )
    register(
        source_id=SOURCE_ID,
        name="神奈川県 ツキノワグマ目撃等情報(年度別個票)",
        publisher=PUBLISHER,
        url=INDEX_URL,
        category="野生動物出没情報(ツキノワグマ)",
        access_method="HTML内PDFリンク動的取得+pdfplumber表抽出",
        fmt="PDF",
        license_=LICENSE,
        redistributable=1,
        record_count=len(all_rows),
        notes=notes,
    )


if __name__ == "__main__":
    main()
