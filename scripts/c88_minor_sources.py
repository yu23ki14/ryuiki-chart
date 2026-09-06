"""小規模ソース4件のまとめ収集(それぞれ独立に実行可能な4関数 + register())
1. kanagawa_rdb2006_errata : 神奈川県レッドデータ生物調査報告書2006 正誤表PDF(1ページ, 箇条書き)
2. tanzawa_visitor_centers : 丹沢情報発信基地ビジターセンター(秦野VC・西丹沢VCの2施設, 定型HTML)
3. satonavi_donkai          : 里なび「自然塾丹沢ドン会」(1団体1レコード, HTMLエンティティ難読化あり)
4. sagami_seibi_keikaku_mirror : 相模川・中津川河川整備計画ポータル(PDF2本, CSV行73の別ホストミラーと
   判定済みのため register() のみ・record_count=0。表抽出はTier2のため対象外)
"""
import sys, csv, re, pathlib
sys.path.insert(0, "scripts")
from common import get, download, register, write_jsonl, PROC, RAW

import pdfplumber
from bs4 import BeautifulSoup


# ============================================================
# 1. kanagawa_rdb2006_errata
# ============================================================
ERRATA_ENTRY_URL = "https://nh.kanagawa-museum.jp/publications/other/reddata.html"
ERRATA_SID = "kanagawa_rdb2006_errata"


def collect_rdb2006_errata():
    r = get(ERRATA_ENTRY_URL)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")
    pdf_href = None
    for a in soup.find_all("a", href=True):
        if "errata" in a["href"].lower():
            pdf_href = a["href"]
            break
    if pdf_href is None:
        register(ERRATA_SID, "神奈川県レッドデータ生物調査報告書2006 正誤表",
                  "神奈川県立生命の星・地球博物館", ERRATA_ENTRY_URL, "希少種・保全ランク",
                  "入口HTMLからPDFリンク検出", "PDF", "", 0, 0,
                  "入口HTMLに正誤表PDFへのリンクが見つからなかった(ページ構成が変わった可能性)。")
        return

    pdf_url = pdf_href if pdf_href.startswith("http") else "https://nh.kanagawa-museum.jp" + pdf_href
    dest = RAW / ERRATA_SID / "Kanagawa_Reddata_2006_errata.pdf"
    download(pdf_url, dest)
    print(f"  [download] {dest} ({dest.stat().st_size} bytes) <- {pdf_url}")

    with pdfplumber.open(dest) as pdf:
        n_pages = len(pdf.pages)
        text = pdf.pages[0].extract_text() or ""
        tables_found = sum(len(p.find_tables()) for p in pdf.pages)

    # 箇条書き記号(プライベート領域の bullet glyph、通常 )で分割。
    # 先頭のタイトル行(「神奈川県レッドデータ生物報告書 2006 正誤表」)は bullet を持たないので
    # 分割後の最初のチャンクに残る。実際の訂正項目は必ず「p.NN」形式のページ参照で始まるため、
    # それを持たないチャンク(タイトル行など)は箇条書き項目ではないとみなして除外する。
    chunks = re.split(r"\n?[•]\s*", text)
    chunks = [c.strip() for c in chunks if c.strip()]

    rows = []
    i = 0
    for chunk in chunks:
        first_line = chunk.split("\n")[0]
        m_page = re.match(r"^(p\.?\s*[\d]+(?:[\-–]\d+)?)", first_line)
        if not m_page:
            print(f"  [skip] 箇条書き項目ではないチャンクを除外: {chunk!r}")
            continue
        i += 1
        page_raw = m_page.group(1)
        text_ja = re.sub(r"\s+", " ", chunk).strip()

        before_ja = after_ja = None
        m_ba = re.search(r"誤[）\)]\s*(.+?)\s*→\s*正[）\)]\s*([^\n]+)", chunk)
        if m_ba:
            before_ja = m_ba.group(1).strip()
            after_ja = m_ba.group(2).strip()

        rows.append({
            "errata_id": f"{ERRATA_SID}_{i:02d}",
            "page_raw": page_raw,
            "before_ja": before_ja,
            "after_ja": after_ja,
            "text_ja": text_ja,
            "source_id": ERRATA_SID,
            "source_ref": pdf_url,
        })

    p = PROC / f"{ERRATA_SID}.csv"
    fields = ["errata_id", "page_raw", "before_ja", "after_ja", "text_ja", "source_id", "source_ref"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"  [write] {p}  {len(rows)} rows")
    write_jsonl(ERRATA_SID, rows)

    register(
        source_id=ERRATA_SID,
        name="神奈川県レッドデータ生物調査報告書2006 正誤表",
        publisher="神奈川県立生命の星・地球博物館",
        url=ERRATA_ENTRY_URL,
        category="希少種・保全ランク",
        access_method="入口HTMLからPDFリンクを検出しダウンロード、pdfplumberでテキスト抽出",
        fmt="PDF->CSV/JSONL",
        license_=("nh.kanagawa-museum.jp サイトポリシー https://nh.kanagawa-museum.jp/sitepolicy/ "
                   "「『引用』等の著作権法上認められている範囲において自由にご利用になれます。"
                   "コンテンツを利用する際には、出典を記載してください。」"
                   "(既存source_registryの kanagawa_rdb2006_animals と同一サイト・同一適用)"),
        redistributable=1,
        record_count=len(rows),
        notes=(
            f"{n_pages}ページ、テキストレイヤーあり、find_tables()による表構造は{tables_found}件"
            "(罫線なしの箇条書きのため表としては検出されない)。"
            "本冊「神奈川県レッドデータ生物調査報告書2006」(634ページ)自体はミュージアムショップでの"
            "販売のみでPDF配布はなく、本正誤表のみがオンラインで取得可能(既存source_registry "
            "kanagawa_rdb2006_animals の対象範囲外だった箇所)。"
            "before_ja/after_ja は原文中の『誤）X→正）Y』形式の行のみ機械的に抽出し、削除・追加指示など"
            "単純な置換で表現できない箇条書きは text_ja のみ埋めて before_ja/after_ja は null のままにした"
            "(無理な構造化はしない)。"
        ),
    )


# ============================================================
# 2. tanzawa_visitor_centers
# ============================================================
VC_URL = "https://www.pref.kanagawa.jp/docs/f4y/02yama/visitor.html"
VC_SID = "tanzawa_visitor_centers"


def collect_visitor_centers():
    r = get(VC_URL)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    main = soup.find(id="main") or soup

    h3s = main.find_all("h3")
    rows = []
    for i, h3 in enumerate(h3s):
        name = h3.get_text(strip=True)
        if "ビジターセンター" not in name:
            continue
        # h3 から 次の h3(またはセクション終端)までの兄弟要素を集める
        frag = []
        for sib in h3.find_next_siblings():
            if sib.name == "h3":
                break
            frag.append(sib)

        tel = address = url = None
        expect = None
        for el in frag:
            if el.name == "ul":
                label = el.get_text(strip=True)
                if "電話番号" in label:
                    expect = "tel"
                elif "所在地" in label:
                    expect = "address"
                elif "ホームページ" in label:
                    expect = "url"
                continue
            if el.name == "div" and "section" in (el.get("class") or []):
                text = re.sub(r"\s+", "", el.get_text())
                if not text:
                    continue
                if expect == "tel" and tel is None:
                    tel = text
                elif expect == "address" and address is None:
                    address = el.get_text(strip=True)
                elif expect == "url" and url is None:
                    a = el.find("a", href=True)
                    url = a["href"] if a else text

        rows.append({
            "facility_id": f"{VC_SID}_{i+1:02d}",
            "name_ja": name,
            "tel": tel,
            "address_ja": address,
            "url": url,
            "source_id": VC_SID,
            "source_ref": VC_URL,
        })

    p = PROC / f"{VC_SID}.csv"
    fields = ["facility_id", "name_ja", "tel", "address_ja", "url", "source_id", "source_ref"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"  [write] {p}  {len(rows)} rows")
    write_jsonl(VC_SID, rows)

    register(
        source_id=VC_SID,
        name="丹沢情報発信基地ビジターセンター(秦野VC・西丹沢VC)",
        publisher="神奈川県 環境農政局 環境部 自然環境保全センター",
        url=VC_URL,
        category="visitor_facility",
        access_method="HTML静的ページをBeautifulSoupでパース",
        fmt="HTML->CSV/JSONL",
        license_="神奈川県サイトポリシー(出典明示で利用可)",
        redistributable=1,
        record_count=len(rows),
        notes=(
            "秦野ビジターセンター・西丹沢ビジターセンターの2施設のみ掲載。緯度経度は原ページに記載が"
            "なくジオコーディングによる補完もしていないため出力に含めない(列自体を持たない)。"
            "2施設とも「ホームページ」欄は同一URL(http://www.kanagawa-park.or.jp/tanzawavc/)を指しており"
            "誤記ではなく原文どおり。"
        ),
    )


# ============================================================
# 3. satonavi_donkai
# ============================================================
SATONAVI_URL = "https://www.env.go.jp/nature/satoyama/satonavi/group/12.html"
SATONAVI_SID = "satonavi_donkai"


def _td_lines(td):
    """<br>を改行として扱い、行ごとのテキストリストを返す(&#nn;等のエンティティはBSが自動デコード済み)"""
    td = BeautifulSoup(str(td), "html.parser")
    for br in td.find_all("br"):
        br.replace_with("\n")
    text = td.get_text().replace("\xa0", " ")
    return [re.sub(r"[ 　]+", " ", ln).strip() for ln in text.split("\n") if ln.strip()]


def collect_satonavi_donkai():
    r = get(SATONAVI_URL)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")

    def table_dict(table):
        out = {}
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            label = tds[0].get_text(strip=True)
            out[label] = tds[1]
        return out

    t1 = soup.find("table", class_="group_detail_1")
    t2 = soup.find("table", class_="group_detail_2")
    d1 = table_dict(t1) if t1 else {}
    d2 = table_dict(t2) if t2 else {}

    def plain(td):
        if td is None:
            return None
        v = " ".join(_td_lines(td))
        return v if v else None

    def joined(td):
        if td is None:
            return None
        lines = _td_lines(td)
        return "\n".join(lines) if lines else None

    # 連絡先: 住所行(電話/FAX/E-mailの前まで)・電話・FAXを分離。E-mailは出力しない。
    # 元HTMLでは「電話」等のラベルと値が<br>を挟まない同一テキストノード内の別行
    # (ラベル行の直後に値だけの行が続く)になっているため、ラベル単独行を見たら
    # 次の行を値として拾う状態機械にする。
    address_lines, tel, fax = [], None, None
    expect = None  # 'tel' | 'fax' | 'skip'(E-mail) | None
    contact_td = d1.get("連絡先")
    if contact_td is not None:
        for ln in _td_lines(contact_td):
            m = re.match(r"^(電話|FAX|E-mail)\s*(.*)$", ln, re.I)
            if m:
                label, rest = m.group(1), m.group(2).strip()
                if label == "電話":
                    tel, expect = (rest or None), (None if rest else "tel")
                elif label.upper() == "FAX":
                    fax, expect = (rest or None), (None if rest else "fax")
                else:  # E-mail: 個人・団体のメールアドレスは出力しない
                    expect = None if rest else "skip"
                continue
            if expect == "tel":
                tel, expect = ln, None
            elif expect == "fax":
                fax, expect = ln, None
            elif expect == "skip":
                expect = None  # メールアドレスの値行を読み捨てる
            else:
                address_lines.append(ln)
    address_ja = "\n".join(address_lines) if address_lines else None

    url = None
    hp_td = d1.get("ホームページ")
    if hp_td is not None:
        a = hp_td.find("a", href=True)
        url = a["href"] if a else None

    row = {
        "group_id": "12",
        "name_ja": plain(d1.get("団体名称")),
        "name_kana": plain(d1.get("団体名称かな")),
        "representative_ja": plain(d1.get("代表者")),
        "address_ja": address_ja,
        "tel": tel,
        "fax": fax,
        "url": url,
        "members_raw": plain(d1.get("会員数")),
        "activity_start_raw": plain(d1.get("活動開始日")),
        "established_raw": plain(d1.get("法人設立日")),
        "features_ja": joined(d1.get("団体の特徴")),
        "message_ja": joined(d1.get("団体からの\nメッセージ")) or joined(d1.get("団体からのメッセージ")),
        "note_ja": plain(d1.get("備考")),
        "access_ja": " / ".join(x for x in [
            f"最寄駅（鉄道等）: {plain(d2.get('最寄駅（鉄道等）'))}" if d2.get("最寄駅（鉄道等）") else None,
            f"最寄バス停: {plain(d2.get('最寄バス停'))}" if d2.get("最寄バス停") else None,
            f"上記最寄からの距離: {plain(d2.get('上記最寄からの距離'))}" if d2.get("上記最寄からの距離") else None,
        ] if x) or None,
        "area_ja": plain(d2.get("保全活動エリア")),
        "source_id": SATONAVI_SID,
        "source_ref": SATONAVI_URL,
    }

    # メッセージ欄のラベルは <br> を挟んだ2行("団体からの"+"メッセージ")になっているため両対応
    if row["message_ja"] is None:
        for k, v in d1.items():
            if "メッセージ" in k:
                row["message_ja"] = joined(v)
                break

    fields = ["group_id", "name_ja", "name_kana", "representative_ja", "address_ja", "tel", "fax",
              "url", "members_raw", "activity_start_raw", "established_raw", "features_ja",
              "message_ja", "note_ja", "access_ja", "area_ja", "source_id", "source_ref"]
    p = PROC / f"{SATONAVI_SID}.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(row)
    print(f"  [write] {p}  1 rows")
    write_jsonl(SATONAVI_SID, [row])

    register(
        source_id=SATONAVI_SID,
        name="里なび 保全活動団体・エリア検索「自然塾丹沢ドン会」",
        publisher="環境省 自然環境局 自然環境計画課",
        url=SATONAVI_URL,
        category="市民活動団体",
        access_method="HTML(table.group_detail_1/2)をBeautifulSoupでパース",
        fmt="HTML->CSV/JSONL",
        license_="環境省ウェブサイト著作権・リンクについて(要確認、既存 moe_satoyama_kanagawa と同じ扱い)",
        redistributable=1,
        record_count=1,
        notes=(
            "id=12(自然塾丹沢ドン会)の1団体1レコードのみ。既存 moe_satoyama_kanagawa "
            "(env.go.jp/nature/satoyama/14_kanagawa/kanagawa.html, 28行, 環境省の別データベース"
            "「里地里山情報 選定地一覧」)とはURLパス・データベースが異なり重複しない。"
            "連絡先のE-mailはHTML上は数値文字参照(&#nn;)で難読化されていたが、BeautifulSoupの"
            "パース時点で自動的にデコードされる程度の弱い難読化だった。電話・FAXは公開情報として"
            "出力したが、個人・団体のメールアドレスは指示により出力に含めていない。"
            "「里なび」全体を group/1, group/2, ... と連番で横断収集すれば別のTier1ソースになり得るが、"
            "本スクリプトはCSV行70で指定された本団体1件のみを対象とする。"
        ),
    )


# ============================================================
# 4. sagami_seibi_keikaku_mirror (register() のみ、record_count=0)
# ============================================================
KTR_PORTAL_URL = "https://www.ktr.mlit.go.jp/keihin/keihin_index056.html"
MIRROR_SID = "sagami_seibi_keikaku_mirror"
KTR_PDFS = [
    ("000707103.pdf", "相模川水系相模川・中津川河川整備計画(本文)"),
    ("000707104.pdf", "相模川水系相模川・中津川河川整備計画の概要"),
]


def collect_seibi_keikaku_mirror():
    r = get(KTR_PORTAL_URL)
    r.encoding = r.apparent_encoding
    soup = BeautifulSoup(r.text, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for fname, _ in KTR_PDFS:
            if fname in href:
                found[fname] = href

    dl_notes = []
    for fname, desc in KTR_PDFS:
        url = found.get(fname)
        if not url:
            dl_notes.append(f"{fname}: 入口ページにリンクが見つからなかった")
            continue
        dest = RAW / MIRROR_SID / fname
        download(url, dest)
        size = dest.stat().st_size
        print(f"  [download] {dest} ({size} bytes) <- {url}")
        dl_notes.append(f"{fname}({desc}, {size}bytes, {url})")

    register(
        source_id=MIRROR_SID,
        name="相模川・中津川河川整備計画(京浜河川事務所ポータル)",
        publisher="国土交通省 関東地方整備局 京浜河川事務所 / 神奈川県",
        url=KTR_PORTAL_URL,
        category="河川整備計画",
        access_method="register()のみ(表抽出は未実施)",
        fmt="PDF (未パース)",
        license_=("ktr.mlit.go.jp/guide/copyright.html を確認。原文『関東地方整備局ウェブサイトで"
                   "掲載・発信している情報...の著作権は...「公共データ利用規約(第1.0版)」(PDL1.0)に"
                   "準拠...利用することができます』"),
        redistributable=1,
        record_count=0,
        notes=(
            "本文『相模川水系相模川・中津川河川整備計画』[PDF:3573KB]と『概要』[PDF:4645KB]への"
            "直リンクを掲載するポータルページ。CSV行73(pref.kanagawa.jp版, "
            "https://www.pref.kanagawa.jp/documents/10592/sagaminakatsuseibikeikaku_1.pdf, "
            "3,665,831バイト)と実質同一文書の別ホストミラーと判定済み"
            "(本文PDFのサイズが本文記載の3573KB≒3,658,752バイトとpref.kanagawa.jp版の"
            "3,665,831バイトがほぼ一致)。行73側での表抽出はTier 2(テキストレイヤーはあるが"
            "非定型の多段見出し表・記述量が多い)のため今回のTier 1収集の対象外であり、"
            "本ソースは register() のみでrecord_count=0とする(表抽出は未実施)。"
            "PDF本体は data/raw/sagami_seibi_keikaku_mirror/ に保存済み(後段で使えるように): "
            + "; ".join(dl_notes)
        ),
    )


def main():
    print("=== 1. kanagawa_rdb2006_errata ===")
    collect_rdb2006_errata()
    print("=== 2. tanzawa_visitor_centers ===")
    collect_visitor_centers()
    print("=== 3. satonavi_donkai ===")
    collect_satonavi_donkai()
    print("=== 4. sagami_seibi_keikaku_mirror ===")
    collect_seibi_keikaku_mirror()


if __name__ == "__main__":
    main()
