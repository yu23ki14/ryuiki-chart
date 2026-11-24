"""c106_tatsugo_koho の HTML 解析（標準ライブラリ＋pytest だけで走る。ネットワークなし）。

町の HTML は転載せず、構造（h3 見出し → PDF リンク → ul の主な記事）だけ真似た合成 HTML を使う。
"""
import c106_tatsugo_koho as c

Y = "https://example.invalid/koho/koho2026.html"
OLD = "https://example.invalid/koho/kohotatsugo.html"


def link(text):
    return c.parse_link_text(text)


def test_seireki_link_with_size():
    r = link("2026年11月号（PDF：7,581KB）")
    assert (r["year"], r["month"], r["size_kb"]) == (2026, 11, 7581)
    assert not r["part"] and not r["merged"] and not r["annex"]


def test_reiwa_gannen_fiscal_year_january_is_next_calendar_year():
    assert (link("令和元年度広報たつごう12月号（PDF：1KB）")["year"]) == 2019
    r = link("令和元年度広報たつごう2月号（PDF：1KB）")
    assert (r["year"], r["month"], r["fiscal"]) == (2020, 2, True)


def test_heisei_fiscal_vs_calendar_year():
    assert link("平成30年度広報たつごう4月号（PDF：1KB）")["year"] == 2018
    assert link("平成30年度広報たつごう3月号（PDF：1KB）")["year"] == 2019
    r = link("平成25年広報たつごう8月号（PDF：1KB）")  # 「度」なし＝元号の暦年
    assert (r["year"], r["month"], r["fiscal"]) == (2013, 8, False)


def test_merged_issue():
    r = link("令和元年度広報たつごう4.5月合併号（PDF：8,521KB）")
    assert (r["year"], r["months"], r["merged"]) == (2019, [4, 5], True)


def test_split_issue_variants():
    assert link("平成30年度広報たつごう8月号前半（PDF：1KB）")["part"] == 1
    assert link("平成30年度広報たつごう8月号後半（PDF：1KB）")["part"] == 2
    assert link("2023年7月号1.（PDF：1KB）")["part"] == 1
    assert link("2023年7月号2.（PDF：1KB）")["part"] == 2
    assert link("2023年7月号（PDF：1KB）")["part"] is None


def test_annex():
    r = link("平成27年広報たつごう2月号別冊（PDF：1,583KB）")
    assert (r["year"], r["month"], r["annex"]) == (2015, 2, True)


def test_fullwidth_digits_and_no_year_uses_section():
    assert c.parse_link_text("１月号（PDF：1KB）") is None
    r = c.parse_link_text("1月号（PDF：1KB）", "令和元年度")
    assert (r["year"], r["month"]) == (2020, 1)


def test_unparseable_returns_none():
    assert link("お知らせ") is None


def test_issue_date_year_rolls_back_for_december_in_january_issue():
    assert c.parse_issue_date("1月号（12月22日発行）", 2021, 1) == "2020-12-22"
    assert c.parse_issue_date("11月号（10月28日発行）", 2026, 11) == "2026-10-28"
    assert c.parse_issue_date("4月号　3月31日発行", 2021, 4) == "2021-03-31"
    assert c.parse_issue_date("5月号　4月28発行", 2020, 5) == "2020-04-28"  # 「日」の欠け
    assert c.parse_issue_date("バックナンバー", 2020, 5) is None


YEAR_HTML = """
<h1>広報たつごう 令和8年度</h1>
<h3>11月号（10月28日発行）</h3>
<p><a href="/koho/documents/a.pdf" class="icon_pdf">2026年11月号（PDF：7,581KB）</a></p>
<ul><li>見出しA</li><li>見出しB　ほか</li></ul>
<h3>2月号（1月28日発行）</h3>
<p><a href="/koho/documents/b1.pdf" class="icon_pdf">2026年2月号前半（PDF：1KB）</a></p>
<p><a href="/koho/documents/b2.pdf" class="icon_pdf">2026年2月号後半（PDF：2KB）</a></p>
<ul><li>見出しC</li></ul>
"""


def test_parse_year_page():
    rows = c.parse_page(YEAR_HTML, Y)
    assert [r["issue"] for r in rows] == ["202611", "202602", "202602"]
    assert rows[0]["url"] == "https://example.invalid/koho/documents/a.pdf"
    assert rows[0]["headlines"] == ["見出しA", "見出しB　ほか"]
    assert rows[0]["issue_date"] == "2026-10-28"
    assert [r["part"] for r in rows[1:]] == [1, 2]
    # ul は最後の PDF（後半）に付く。分割号の見出しは号単位に寄せる実装は次の手順
    assert rows[2]["headlines"] == ["見出しC"]


OLD_HTML = """
<h3>令和元年度</h3>
<ul>
<li><a href="/koho/documents/x4.pdf" class="icon_pdf">令和元年度広報たつごう4月号（PDF：1KB）</a></li>
<li><a href="/koho/documents/x3.pdf" class="icon_pdf">令和元年度広報たつごう3月号（PDF：1KB）</a></li>
<li><a href="/koho/documents/x45.pdf" class="icon_pdf">令和元年度広報たつごう4.5月合併号（PDF：1KB）</a></li>
</ul>
<h3>平成30年度</h3>
<ul>
<li><a href="/koho/documents/y.pdf" class="icon_pdf">平成30年度広報たつごう3月号（PDF：1KB）</a></li>
</ul>
"""


def test_old_page_fiscal_april_at_top_is_next_year_and_li_not_headlines():
    rows = c.parse_page(OLD_HTML, OLD)
    assert [r["issue"] for r in rows] == ["202004", "202003", "201904", "201903"]
    assert all(r["headlines"] == [] for r in rows)


def test_summarize_counts_merged_split_annex():
    rows = c.parse_page(OLD_HTML, OLD) + c.parse_page(YEAR_HTML, Y)
    s = c.summarize(rows)
    assert s["pdf"] == 7
    assert s["issues"] == 6  # 202004,202003,201904,201903,202611,202602（分割は1冊）
    assert (s["split_pdfs"], s["merged_pdfs"], s["parse_errors"]) == (2, 1, 0)


def test_year_page_urls_from_index():
    idx = '<a href="/koho/koho2021.html">x</a><a href="koho2020.html">y</a><a href="/koho/koho2021.html">dup</a><a href="/z.html">z</a>'
    assert [u.rsplit("/", 1)[-1] for u in c.year_page_urls(idx)] == ["koho2020.html", "koho2021.html"]
