"""tatsugo_segment（紙面→記事の切り分け）と c106 の extract 周りのテスト。合成ブロックだけ。標準ライブラリ＋pytest。"""
import c106_tatsugo_koho as c
import tatsugo_segment as s


def blk(text, x0, y0, x1, y1, size=11.0, bold=False, vertical=False):
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "text": text, "vertical": vertical, "size": size,
            "bold": bold, "font": ""}


def page(no, blocks, w=500, h=700, img=0.0):
    return {"page": no, "w": w, "h": h, "blocks": blocks, "image_cover": img}


def test_heading_by_size_bold_and_mark():
    assert s.is_heading(blk("相撲大会の結果", 0, 0, 10, 10, size=15), 11)
    assert s.is_heading(blk("健康づくり通信", 0, 0, 10, 10, size=11, bold=True), 11)
    assert s.is_heading(blk("■お知らせ", 0, 0, 10, 10, size=11), 11)
    assert not s.is_heading(blk("本文です。" * 3, 0, 0, 10, 10, size=11), 11)
    assert not s.is_heading(blk("1,000円", 0, 0, 10, 10, size=15, bold=True), 11)  # 数字だけ
    assert not s.is_heading(blk("日時：9月20日", 0, 0, 10, 10, size=11, bold=True), 11)


def test_footer_and_tab_dropped():
    assert s.is_footer(blk("2026.11", 10, 690, 40, 699), 500, 700)
    assert s.is_footer(blk("-5- Tatsugo", 10, 690, 40, 699), 500, 700)
    assert s.is_footer(blk("レポート", 480, 300, 495, 340, vertical=True), 500, 700)
    assert not s.is_footer(blk("本文" * 20, 10, 300, 200, 340), 500, 700)


def test_vertical_columns_read_right_to_left():
    cols = [blk("あ", 300, 100, 312, 200, vertical=True), blk("い", 400, 100, 412, 200, vertical=True),
            blk("う", 350, 100, 362, 200, vertical=True)]
    assert [b["text"] for b in s.reading_order(cols)] == ["い", "う", "あ"]


def test_horizontal_columns_top_to_bottom_per_column():
    bl = [blk("右下", 260, 300, 400, 340), blk("左下", 20, 300, 200, 340), blk("左上", 20, 100, 200, 140),
          blk("右上", 260, 100, 400, 140)]
    assert [b["text"] for b in s.reading_order(bl)] == ["左上", "左下", "右上", "右下"]


def test_blocks_from_pymupdf_joins_vertical_chars():
    d = {"blocks": [{"type": 0, "bbox": [0, 0, 12, 60], "lines": [
        {"dir": [0, 1], "spans": [{"text": t, "size": 10.0, "flags": 0, "font": "Mincho"}]} for t in "避難所"]}]}
    b = s.blocks_from_pymupdf(d)[0]
    assert (b["text"], b["vertical"]) == ("避難所", True)


def test_segment_two_articles_continuation_and_empty_page():
    p1 = page(2, [blk("見出しA", 20, 50, 200, 70, size=16, bold=True), blk("本文A" * 20, 20, 80, 200, 300),
                  blk("見出しB", 260, 50, 440, 70, size=16, bold=True), blk("本文B" * 20, 260, 80, 440, 300)])
    p2 = page(3, [blk("つづき" * 10, 20, 50, 200, 300)])  # 見出しの無いページ → 直前の記事の続き
    p3 = page(4, [], img=0.8)
    arts = s.segment_file([p1, p2, p3], 11.0)
    assert [a["title"] for a in arts] == ["見出しA", "見出しB", None]
    last_article = arts[1]
    assert last_article["page_to"] == 3 and "つづき" in last_article["body_text"]
    assert arts[2]["kind"] == "unsegmented" and arts[2]["unreadable_reason"] == "scanned_no_ocr"
    assert arts[2]["body_text"] is None


def test_sub_headings_stay_in_body_and_masthead_becomes_section():
    big = blk("龍郷町相撲大会", 20, 20, 300, 80, size=46)
    sub = blk("個人戦結果", 20, 200, 200, 215, size=13, bold=True)
    body = blk("本文" * 30, 20, 100, 300, 190)
    arts = s.segment_file([page(2, [big, sub, body, blk("続き" * 10, 20, 220, 300, 300)])], 11.0)
    assert len(arts) == 1 and arts[0]["title"] == "龍郷町相撲大会" and "個人戦結果" in arts[0]["body_text"]
    m = blk("龍郷町TOWN TOPICS", 20, 10, 400, 60, size=46)
    h1 = blk("記事その一", 20, 100, 200, 120, size=15, bold=True)
    h2 = blk("記事その二", 260, 100, 440, 120, size=15, bold=True)
    heads, section = s.select_article_heads(s.merge_headings([m, h1, h2]))
    assert section == "龍郷町TOWN TOPICS" and [h["text"] for h in heads] == ["記事その一", "記事その二"]


def test_garbled_body_is_unreadable_not_guessed():
    g = "ᓥໟᣓⓗࣉࣟࢪ" * 10 + "性教育"
    assert s.garbled(g) and not s.garbled("ふつうの日本語の本文です。")
    arts = s.segment_file([page(2, [blk("見出し", 20, 50, 200, 70, size=16, bold=True), blk(g, 20, 80, 200, 300)])], 11.0)
    assert arts[0]["body_text"] is None and arts[0]["unreadable_reason"] == "garbled_font_encoding"


def test_clean_title_strips_date_badge():
    assert s._clean_title("9 19 国指定重要") == "国指定重要"
    assert s._clean_title("924秋の運動") == "秋の運動"
    assert s._clean_title("令和７年度 納税") == "令和７年度 納税"


def test_classify_places_dates():
    t = s.classify("清掃活動のお知らせ", "龍郷湾の海岸で実施")
    assert "conservation_clean" in {x["topic_id"] for x in t}
    assert s.classify("お知らせ", "特になし")[0]["topic_id"] == "other"
    pl = {p["place_raw"]: p["place_type"] for p in s.extract_places("秋名の行事", "円集落と大勝で。龍郷湾と赤徳川")}
    assert pl["秋名"] == "settlement" and pl["円"] == "settlement" and pl["龍郷湾"] == "coast" and pl["赤徳川"] == "river"
    assert "浦" not in {p["place_raw"] for p in s.extract_places("", "浦島太郎")}
    ds = s.extract_dates("9月20日に開催。令和８年10月1日から。", 2026, 11)
    assert ds[0] == {"raw": "9月20日", "iso": "2026-09-20"} and ds[1]["iso"] == "2026-10-01"
    assert s.extract_dates("1月5日", 2026, 11)[0]["iso"] == "2027-01-05"


def test_reconcile_counts_matched_in_text_missed_extra():
    arts = [{"kind": "article", "title": "ふるさと納税 実績報告", "body_text": "x"},
            {"kind": "article", "title": "無関係の記事", "body_text": "第61回駅伝競走大会の結果は…"}]
    r = s.reconcile_issue(["令和7年度 ふるさと納税 実績報告", "第61回 駅伝競走大会　ほか", "存在しない記事"], arts)
    assert len(r["matched"]) == 1 and len(r["in_text_only"]) == 1 and len(r["missed"]) == 1
    assert r["extra"] == ["無関係の記事"]


def test_build_issue_tables_part_order_offsets_and_ids():
    rows = c.parse_page('''<h3>平成30年度</h3>
<ul><li><a href="/a/b2.pdf">平成30年度広報たつごう8月号後半（PDF：1KB）</a></li>
<li><a href="/a/b1.pdf">平成30年度広報たつごう8月号前半（PDF：1KB）</a></li>
<li><a href="/a/x.pdf">平成27年広報たつごう2月号別冊（PDF：1KB）</a></li></ul>''', "https://e.invalid/koho/kohotatsugo.html")
    log = {"b1.pdf": {"pages": 10, "sha256": "a"}, "b2.pdf": {"pages": 6, "sha256": "b"}}
    issues, files = c.build_issue_tables(rows, log)
    by = {f["doc_id"]: f for f in files}
    assert by["tatsugo_koho_201808_p1"]["page_offset"] == 0 and by["tatsugo_koho_201808_p2"]["page_offset"] == 10
    assert "tatsugo_koho_201502_sp1" in by
    i = {x["issue_id"]: x for x in issues}
    assert i["tatsugo_koho_201808"]["n_pages"] == 16 and i["tatsugo_koho_201502_sp1"]["kind"] == "supplement"
    assert i["tatsugo_koho_201808"]["fiscal_year"] == 2018


def test_heading_only_articles_are_absorbed_into_neighbours():
    p = page(2, [blk("見出しA", 20, 50, 200, 70, size=16, bold=True), blk("本文A" * 20, 20, 80, 200, 200),
                 blk("箱の見出し", 20, 400, 200, 420, size=16, bold=True)])  # 本文の無い見出し
    arts = s.segment_file([p], 11.0)
    assert len(arts) == 1 and "箱の見出し" in arts[0]["body_text"]
    p = page(2, [blk("先頭の見出し", 20, 20, 200, 40, size=16, bold=True),
                 blk("記事B", 260, 100, 440, 120, size=16, bold=True), blk("本文B" * 20, 260, 130, 440, 300)])
    arts = s.segment_file([p], 11.0)
    assert [a["title"] for a in arts] == ["記事B"] and arts[0]["body_text"].startswith("先頭の見出し")


def test_reconcile_paraphrase_unreadable_and_hyoshi_prefix():
    arts = [{"kind": "article", "title": "別の記事", "body_text": "本場奄美大島紬購入費等助成制度について"}]
    r = s.reconcile_issue(["本場奄美大島紬購入費助成制度", "［表紙］存在しない大会の結果ほか", "画像の中の記事"], arts, unreadable_pages=0)
    assert r["paraphrase"] == ["本場奄美大島紬購入費助成制度"] and len(r["missed"]) == 2
    r = s.reconcile_issue(["画像の中の記事"], arts, unreadable_pages=3)
    assert r["missed_unreadable"] == ["画像の中の記事"] and not r["missed"]
    assert s.clean_headline("［表紙］第66回 大会　ほか") == "第66回 大会"


def test_footer_list_after_last_pdf_is_not_headlines():
    rows = c.parse_page('''<div><h3>11月号（10月28日発行）</h3>
<p><a href="/a/a.pdf">2026年11月号（PDF：1KB）</a></p><ul><li>記事一</li></ul></div>
<div><ul><li>このサイトについて</li><li>携帯サイト</li></ul></div>''', "https://e.invalid/koho/koho2026.html")
    assert rows[0]["headlines"] == ["記事一"]
    rows = c.parse_page('''<h3>10月号（9月30日発行）</h3><p><a href="/a/b.pdf">2026年10月号（PDF：1KB）</a></p>
<div><ul><li>このサイトについて</li></ul></div>''', "https://e.invalid/koho/koho2026.html")
    assert rows[0]["headlines"] == []


def test_parse_page_survives_div_inside_li():
    """主な記事の li の中に div があると、_last が外れて以前は TypeError で落ちた（Issue #131 レビュー）。"""
    html = ('<h3>11月号（10月28日発行）</h3><a href="a.pdf">2026年11月号（PDF：1KB）</a>'
            '<ul><li>相撲大会</li><li><div>リンク集</div></li><li>駅伝</li></ul>')
    rows = c.parse_page(html, "https://x.invalid/koho2026.html")
    assert len(rows) == 1 and rows[0]["headlines"][0] == "相撲大会"


def test_is_footer_keeps_vertical_heading_column_at_the_right_edge():
    """右端の短いブロックは、本文以下の大きさの細い帯（柱・タブ）だけ落とす。大きい縦書きの見出し列は残す。"""
    tab = blk("レポート", 480, 300, 495, 340, size=9, vertical=True)
    head = blk("相撲大会", 470, 100, 495, 160, size=16, vertical=True)
    assert s.is_footer(tab, 500, 700, 11.0)
    assert not s.is_footer(head, 500, 700, 11.0)


def test_reconcile_does_not_count_headlines_that_normalize_to_empty():
    r = s.reconcile_issue(["［表紙］", "相撲大会"], [{"kind": "article", "title": "相撲大会", "body_text": "本文"}])
    assert r["headlines"] == 1 and r["matched"] == ["相撲大会"]
