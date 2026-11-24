"""m13（広報たつごう → cells.sqlite。docs/plans/TATSUGO_KOHO.md）のテスト。合成の目録（c106 の build_issue_tables を通す）/articles と、合成の cells.sqlite だけを使う。"""
import copy
import json
import sqlite3

import pytest
import yaml

import c106_tatsugo_koho as c106
import m13_tatsugo_koho as m13
from registry import common as rcommon
from registry.build_article_topic import TopicError, load_topics
from tests.test_doccells import SCHEMA

TOPICS = set(load_topics())


def cat(issue, *, part=None, merged=False, annex=False, n_pages=4, headlines=None, issue_date=None, name=None):
    y, mo = int(issue[:4]), int(issue[4:])
    return {
        "url": f"https://example.invalid/koho/{name or issue + ('p%s' % part if part else '') + ('a' if annex else '')}.pdf",
        "link_text": f"広報たつごう {y}年{mo}月号", "source_page": "https://example.invalid/koho/koho2020.html",
        "heading": f"{mo}月号（{issue_date}発行）" if issue_date else None, "headlines": headlines or [],
        "year": y, "month": mo, "months": [mo, mo + 1] if merged else [mo], "part": part, "merged": merged, "annex": annex,
        "issue_date": issue_date, "issue": issue, "sha256": "0" * 63 + str(n_pages % 10), "n_pages": n_pages,
        "fetched_at": "2026-11-25T00:00:00",
    }


def art(doc_id, p0, p1=None, title="見出し", body="本文です。", topics=("other",), **kw):
    a = {"doc_id": doc_id, "page_from": p0, "page_to": p1 or p0, "kind": "article", "title": title, "section": "お知らせ",
         "body_text": body, "extractor": "pymupdf+rule:v1", "confidence": 0.8,
         "topics": [{"topic_id": t, "extractor": "rule:v1", "confidence": 0.7} for t in topics], "places": []}
    a.update(kw)
    return a


def full_cover(doc_id, n_pages):
    """全ページを 1 ページ 1 記事で覆う。"""
    return [art(doc_id, p, title=f"{doc_id} p{p}") for p in range(1, n_pages + 1)]


@pytest.fixture
def catalog():
    return [
        cat("201502", n_pages=3),
        cat("201502", annex=True, n_pages=2, name="bessatsu"),
        cat("201808", part=2, n_pages=2, name="b"),
        cat("201808", part=1, n_pages=3, name="a"),
        cat("201904", merged=True, n_pages=2),
        cat("202611", n_pages=2, issue_date="2026-10-28", headlines=["相撲大会", "川の清掃"]),
    ]


def extract_rows(catalog, *, unfetched=()):
    """c106 の目録（cat の行）→ issues.jsonl / files.jsonl の行（c106.build_issue_tables。m13 の入力契約をそのまま通す）。"""
    log = {r["url"].rsplit("/", 1)[-1]: {"sha256": r["sha256"], "pages": r["n_pages"]} for r in catalog
           if r["url"].rsplit("/", 1)[-1] not in unfetched}
    return c106.build_issue_tables(catalog, log)


def files_of(catalog):
    return extract_rows(catalog)[1]


def arts_for(catalog):
    out = []
    for f in files_of(catalog):
        out += full_cover(f["doc_id"], f["n_pages"])
    return out


def build(catalog, arts=None, withdrawals=(), *, unfetched=(), **kw):
    kw.setdefault("allow_partial", True)
    arts = arts_for(catalog) if arts is None else arts
    # 見出し突合は個別テストで見る（既定の合成記事には含めない）
    kw.setdefault("headline_threshold", 0.0)
    issues, files = extract_rows(catalog, unfetched=unfetched)
    docs, iss, links, fl = m13.from_extract(issues, files, allow_partial=kw["allow_partial"])
    return m13.finish_model(docs, iss, links, fl, arts, TOPICS, list(withdrawals), **kw)


# ---------------------------------------------------------------- doc_id・号・ページ
def test_doc_id_rules(catalog):
    files = {f["local_path"].rsplit("/", 1)[-1]: f for f in files_of(catalog)}
    assert files["201502.pdf"]["doc_id"] == "tatsugo_koho_201502"
    assert files["bessatsu.pdf"]["doc_id"] == files["bessatsu.pdf"]["issue_id"] == "tatsugo_koho_201502_sp1"
    assert files["a.pdf"]["doc_id"] == "tatsugo_koho_201808_p1" and files["b.pdf"]["doc_id"] == "tatsugo_koho_201808_p2"
    assert files["a.pdf"]["issue_id"] == files["b.pdf"]["issue_id"] == "tatsugo_koho_201808"
    assert files["201904.pdf"]["doc_id"] == "tatsugo_koho_201904"  # 合併号は若い月。2019-05 の ID は作らない
    assert files["202611.pdf"]["doc_id"] == "tatsugo_koho_202611"


def test_two_annexes_in_one_month_get_sp1_and_sp2():
    """同じ月の別冊は 1 ファイル＝1 号で、URL の順に _sp1・_sp2（c106 の採番と m13 の検査が同じ規則）。"""
    cats = [cat("201502", n_pages=3), cat("201502", annex=True, n_pages=2, name="b2"), cat("201502", annex=True, n_pages=2, name="b1")]
    issues, files = extract_rows(cats)
    assert {i["issue_id"] for i in issues} == {"tatsugo_koho_201502", "tatsugo_koho_201502_sp1", "tatsugo_koho_201502_sp2"}
    by_name = {f["local_path"].rsplit("/", 1)[-1]: f["doc_id"] for f in files}
    assert by_name["b1.pdf"] == "tatsugo_koho_201502_sp1" and by_name["b2.pdf"] == "tatsugo_koho_201502_sp2"
    m13.from_extract(issues, files)  # 規則どおりなので通る


def test_from_extract_rejects_rule_violations(catalog):
    issues, files = extract_rows(catalog)
    bad = [{**f, "doc_id": "tatsugo_koho_201808_p9"} if f["doc_id"] == "tatsugo_koho_201808_p2" else f for f in files]
    with pytest.raises(m13.M13Error, match="doc_id が規則"):
        m13.from_extract(issues, bad)
    bad = [{**f, "page_offset": 99} if f["doc_id"] == "tatsugo_koho_201808_p2" else f for f in files]
    with pytest.raises(m13.M13Error, match="page_offset"):
        m13.from_extract(issues, bad)
    with pytest.raises(m13.M13Error, match="part_no"):
        m13.from_extract(issues, [{**f, "part_no": 1} if f["doc_id"] == "tatsugo_koho_201808_p2" else f for f in files])


def test_unfetched_files_drop_the_issue_with_allow_partial_and_stop_otherwise(catalog):
    arts = [a for a in arts_for(catalog) if "201808" not in a["doc_id"]]  # 未取得の号の記事は無い
    m = build(catalog, arts, unfetched={"b.pdf"})  # 201808 の後半が未取得 → 号ごと除く
    assert "tatsugo_koho_201808" not in {i["issue_id"] for i in m["issues"]}
    assert len(m["issues"]) == 4
    issues, files = extract_rows(catalog, unfetched={"b.pdf"})
    assert [i["n_pages"] for i in issues if i["issue_id"] == "tatsugo_koho_201808"] == [None]
    with pytest.raises(m13.M13Error, match="未取得"):
        m13.from_extract(issues, files)  # allow_partial なし


def test_issues_merged_annex_split_and_offsets(catalog):
    m = build(catalog)
    issues = {i["issue_id"]: i for i in m["issues"]}
    assert len(issues) == 5 and len(m["docs"]) == len(m["links"]) == 6
    merged = issues["tatsugo_koho_201904"]
    assert (merged["year_month"], merged["year_month_to"], merged["kind"]) == ("2019-04", "2019-05", "monthly")
    assert merged["fiscal_year"] == 2019 and "合併号" in merged["note"]
    assert issues["tatsugo_koho_201502_sp1"]["kind"] == "supplement" and issues["tatsugo_koho_201502_sp1"]["fiscal_year"] == 2014
    split = issues["tatsugo_koho_201808"]
    assert (split["n_files"], split["n_pages"]) == (2, 5)
    links = {l["doc_id"]: l for l in m["links"]}
    assert (links["tatsugo_koho_201808_p1"]["page_offset"], links["tatsugo_koho_201808_p2"]["page_offset"]) == (0, 3)
    assert issues["tatsugo_koho_202611"]["issued_on"] == "2026-10-28"
    assert issues["tatsugo_koho_201904"]["issued_on"] is None  # 月初で補わない
    titles = {d["doc_id"]: d["title"] for d in m["docs"]}
    assert titles["tatsugo_koho_201808_p2"] == "広報たつごう 2018年8月号（その2）"
    assert titles["tatsugo_koho_201904"] == "広報たつごう 2019年4・5月合併号"
    assert all(d["license"] == m13.LICENSE_TEXT and d["publisher"] == "龍郷町" for d in m["docs"])


def test_issue_page_is_file_page_plus_offset(catalog):
    m = build(catalog)
    a = next(a for a in m["articles"] if a["doc_id"] == "tatsugo_koho_201808_p2" and a["page_from"] == 2)
    assert (a["issue_page_from"], a["issue_page_to"]) == (5, 5)
    for a in m["articles"]:
        assert a["issue_page_from"] - a["page_from"] == a["issue_page_to"] - a["page_to"]


def test_counts_and_continuity():
    with pytest.raises(m13.M13Error, match="件数"):
        build([cat("201808")], arts=full_cover("tatsugo_koho_201808", 4), allow_partial=False)
    base = [{"kind": "monthly", "year_month": ym, "year_month_to": None} for ym in ("2019-03", "2019-06")]
    with pytest.raises(m13.M13Error, match="2019-04"):
        m13.check_issue_continuity(base)
    base.insert(1, {"kind": "monthly", "year_month": "2019-04", "year_month_to": "2019-05"})
    m13.check_issue_continuity(base)  # 合併号の 2 か月目は埋まっている


# ---------------------------------------------------------------- 記事
def test_article_id_is_stable_for_same_file_page_title(catalog):
    a1 = build(catalog)["articles"]
    arts = arts_for(catalog)
    for a in arts:  # 本文・抽出器・分類・信頼度を変えても ID は同じ
        a["body_text"] = "別の本文"
        a["extractor"] = "pymupdf:next"
        a["topics"] = [{"topic_id": "tourism"}]
        a["confidence"] = 0.1
    a2 = build(catalog, arts)["articles"]
    assert [x["article_id"] for x in a1] == [x["article_id"] for x in a2]
    assert a1[0]["body_sha256"] != a2[0]["body_sha256"]  # 本文の変化は body_sha256 で分かる
    arts[0]["title"] = "見出しを変えた"
    assert build(catalog, arts)["articles"][0]["article_id"] != a1[0]["article_id"]  # 切り方が変われば ID が変わる
    assert a1[0]["article_id"].startswith(a1[0]["doc_id"] + ":001:")


def test_untitled_and_collision(catalog):
    d = files_of(catalog)[0]["doc_id"]
    arts = arts_for(catalog)
    arts.append(art(d, 1, title=None, body=None, unreadable_reason="ocr_low_confidence", topics=()))
    arts[-1]["kind"] = "unsegmented"
    ids = [a["article_id"] for a in build(catalog, arts)["articles"]]
    assert f"{d}:001:untitled1" in ids
    dup = arts_for(catalog) + [art(d, 1, title=f"{d} p1")]
    ids2 = [a["article_id"] for a in build(catalog, dup)["articles"]]
    assert len(ids2) == len(set(ids2)) and f"{d}:001:" in ids2[-1] and ids2[-1].endswith("x2")  # 同一記事の重複は通し番号で区別


def test_validation_errors(catalog):
    base = arts_for(catalog)
    d = base[0]["doc_id"]
    with pytest.raises(m13.M13Error, match="files.jsonl に無い"):
        build(catalog, base + [art("tatsugo_koho_209912", 1)])
    with pytest.raises(m13.M13Error, match="ページ範囲"):
        build(catalog, base + [art(d, 3, 99, title="x")])
    with pytest.raises(m13.M13Error, match="語彙"):
        build(catalog, base + [art(d, 1, title="y", topics=("nonsense",))])
    with pytest.raises(m13.M13Error, match="話題が 0 件"):
        build(catalog, base + [art(d, 1, title="z", topics=())])
    with pytest.raises(m13.M13Error, match="unreadable_reason"):
        build(catalog, base + [art(d, 1, title="w", body=None)])
    with pytest.raises(m13.M13Error, match="バイト"):
        build(catalog, base + [art(d, 1, title="big", body="あ" * 30000)])
    with pytest.raises(m13.M13Error, match="exact_name"):
        build(catalog, base + [art(d, 1, title="p", places=[{"place_raw": "秋名", "place_id": "p1", "match_method": None}])])
    with pytest.raises(m13.M13Error, match="place 表に無い"):
        build(catalog, base + [art(d, 1, title="q", places=[{"place_raw": "龍郷湾", "place_id": "nope", "match_method": "exact_name"}])],
              place_ids={"p1"})
    ok = build(catalog, base + [art(d, 1, title="r", places=[{"place_raw": "秋名", "place_type": "settlement"}])])
    assert ok["places"][0]["place_id"] is None and ok["places"][0]["place_raw"] == "秋名"


def test_coverage_requires_every_page(catalog):
    arts = [a for a in arts_for(catalog) if not (a["doc_id"] == "tatsugo_koho_201808_p1" and a["page_from"] == 2)]
    with pytest.raises(m13.M13Error, match="tatsugo_koho_201808_p1 \\[2\\]"):
        build(catalog, arts)
    # 範囲で覆ってもよい
    fixed = [a for a in arts_for(catalog) if a["doc_id"] != "tatsugo_koho_201808_p1"] + [
        art("tatsugo_koho_201808_p1", 1, 3, title="まとめ")]
    build(catalog, fixed)


def test_headline_check_uses_text_anywhere_and_excludes_unreadable_misses(catalog):
    arts = arts_for(catalog)
    arts.append(art("tatsugo_koho_202611", 1, title="相撲大会", topics=("tourism",)))
    kw = dict(headline_threshold=m13.HEADLINE_THRESHOLD)
    with pytest.raises(m13.M13Error, match="閾値"):
        build(catalog, arts, **kw)  # 川の清掃 がどこにも無い（1/2）
    m = build(catalog, arts, headline_threshold=0.0)
    hc = m["headline_check"]
    assert (hc["found"], hc["total"], hc["title_matched"]) == (1, 2, 1)
    assert hc["missing"] == [("tatsugo_koho_202611", "川の清掃", "missed")]
    # 題が無くても本文のどこかに見出しの文字列があれば見つかった扱い（題の一致率ではなく本文での発見率で止める）
    arts.append(art("tatsugo_koho_202611", 2, title="別の題", body="先日、川の清掃が行われました。", topics=("conservation_clean",)))
    hc = build(catalog, arts, **kw)["headline_check"]
    assert (hc["found"], hc["total"], hc["title_matched"]) == (2, 2, 1)
    # 読めないページのある号で見つからない見出しは分母から除く（OCR で読める可能性。止めない）
    arts2 = [a for a in arts_for(catalog) if a["doc_id"] != "tatsugo_koho_202611"] + [
        art("tatsugo_koho_202611", 1, 2, title=None, body=None, unreadable_reason="scanned_no_ocr", kind="unsegmented")]
    hc = build(catalog, arts2, **kw)["headline_check"]
    assert hc["total"] == 0 and hc["classes"]["missed_unreadable"] == 2 and hc["missing"] == []


# ---------------------------------------------------------------- 取り下げ
def test_withdraw_issue_and_article(catalog):
    full = build(catalog)
    one = next(a for a in full["articles"] if a["doc_id"] == "tatsugo_koho_201904")["article_id"]
    w = [{"scope": "issue", "id": "tatsugo_koho_201808", "withdrawn_on": "2026-12-01"},
         {"scope": "article", "id": one, "withdrawn_on": "2026-12-01"}]
    m = build(catalog, withdrawals=w)
    assert "tatsugo_koho_201808" not in {i["issue_id"] for i in m["issues"]}
    assert not [d for d in m["docs"] if d["doc_id"].startswith("tatsugo_koho_201808")]
    assert not [a for a in m["articles"] if a["issue_id"] == "tatsugo_koho_201808" or a["article_id"] == one]
    assert not [l for l in m["links"] if l["issue_id"] == "tatsugo_koho_201808"]
    assert m["withdrawn"]["docs"] == ["tatsugo_koho_201808_p1", "tatsugo_koho_201808_p2"]
    assert {t["article_id"] for t in m["topics"]} == {a["article_id"] for a in m["articles"]}
    with pytest.raises(m13.M13Error, match="入力に無い"):
        build(catalog, withdrawals=[{"scope": "issue", "id": "tatsugo_koho_209912", "withdrawn_on": "2026-12-01"}])


def test_load_withdrawn(tmp_path):
    p = tmp_path / "w.yaml"
    assert m13.load_withdrawn(p) == []
    p.write_text(yaml.safe_dump({"withdrawals": [{"scope": "issue", "id": "x"}]}), encoding="utf-8")
    with pytest.raises(m13.M13Error):
        m13.load_withdrawn(p)
    assert m13.load_withdrawn(m13.DEFAULT_WITHDRAWN) == []  # リポジトリの除外リスト（空）が読める


# ---------------------------------------------------------------- 書き込み
@pytest.fixture
def cells(tmp_path):
    p = tmp_path / "cells.sqlite"
    c = sqlite3.connect(p)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO documents (doc_id, title) VALUES ('other_doc', '別の文書')")
    c.execute("INSERT INTO cells (doc_id, row_key, col_key, value) VALUES ('other_doc', 'r', 'c', '1')")
    c.execute("INSERT INTO notes (note_id, doc_id, kind, text) VALUES ('other_doc_n001', 'other_doc', 'footnote', 't')")
    c.commit()
    yield c
    c.close()


def test_write_is_idempotent_and_touches_only_tatsugo(cells, catalog):
    m = build(catalog)
    diff1 = m13.write(cells, m)
    assert len(diff1["added"]) == len(m["articles"]) and not diff1["removed"]
    counts = {t: cells.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
              ("documents", "notes", "periodical_issues", "periodical_issue_files", "document_articles", "document_article_topics")}
    assert counts == {"documents": 7, "notes": 7, "periodical_issues": 5, "periodical_issue_files": 6,
                      "document_articles": len(m["articles"]), "document_article_topics": len(m["topics"])}
    assert cells.execute("SELECT count(*) FROM cells").fetchone()[0] == 1  # 他の文書のセルに触れない
    assert cells.execute("SELECT title FROM documents WHERE doc_id='other_doc'").fetchone() == ("別の文書",)
    assert cells.execute("SELECT count(*) FROM periodical_series").fetchone()[0] == 1
    dump = lambda: [cells.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()
                    for t in ("documents", "periodical_issues", "document_articles", "document_article_topics")]
    before = dump()
    diff2 = m13.write(cells, m)
    assert dump() == before and diff2 == {"removed": [], "added": [], "changed": []}
    assert cells.execute("PRAGMA foreign_key_check").fetchall() == []


def test_write_reports_diff_and_removes_withdrawn(cells, catalog):
    m13.write(cells, build(catalog))
    arts = arts_for(catalog)
    arts[0]["body_text"] = "直した本文"
    arts[1]["title"] = "見出しが変わった"
    w = [{"scope": "issue", "id": "tatsugo_koho_201808", "withdrawn_on": "2026-12-01"}]
    diff = m13.write(cells, build(catalog, arts, withdrawals=w))
    assert len(diff["changed"]) == 1 and len(diff["added"]) == 1
    assert len(diff["removed"]) == 1 + 5  # 見出しの変わった 1 件＋取り下げた号の 5 ページ
    assert cells.execute("SELECT count(*) FROM documents WHERE doc_id GLOB 'tatsugo_koho_201808*'").fetchone()[0] == 0
    assert cells.execute("SELECT count(*) FROM notes WHERE doc_id GLOB 'tatsugo_koho_201808*'").fetchone()[0] == 0
    assert cells.execute("SELECT count(*) FROM documents").fetchone()[0] == 1 + 4


def test_write_refuses_when_tatsugo_doc_has_cells(cells, catalog):
    cells.execute("INSERT INTO cells (doc_id, row_key, col_key, value) VALUES ('tatsugo_koho_201502', 'r', 'c', '1')")
    cells.commit()
    with pytest.raises(m13.M13Error, match="cells"):
        m13.write(cells, build(catalog))


def test_main_end_to_end_on_a_copy(tmp_path, cells, catalog, capsys):
    proc = tmp_path / "proc"
    proc.mkdir()
    catalog = [{**r, "headlines": []} for r in catalog]  # 見出しの突合は専用のテストで見る
    issues, files = extract_rows(catalog)
    c106.write_jsonl(proc / "issues.jsonl", issues)
    c106.write_jsonl(proc / "files.jsonl", files)
    c106.write_jsonl(proc / "articles.jsonl", arts_for(catalog))
    path = cells.execute("PRAGMA database_list").fetchone()[2]
    cells.close()
    m13.main(["--raw-dir", str(proc), "--cells", path, "--allow-partial"])
    out = capsys.readouterr().out
    assert "号 5（月刊 4・別冊 1）・ファイル 6" in out
    c = sqlite3.connect(path)
    assert c.execute("SELECT count(*) FROM document_articles WHERE source_id = ?", (m13.SOURCE_ID,)).fetchone()[0] == 14
    c.close()
    m13.main(["--raw-dir", str(proc), "--dry-run", "--allow-partial"])


# ---------------------------------------------------------------- 語彙・DDL
def test_topic_vocabulary_file(tmp_path):
    assert set(load_topics()) == {"river_water", "wildlife_alien", "disaster", "conservation_clean", "agri_fishery", "tourism", "other"}
    p = tmp_path / "t.yaml"
    p.write_text("topics:\n  river: {ja: 川}\n", encoding="utf-8")
    with pytest.raises(TopicError, match="other"):
        load_topics(p)


def test_ddl_matches_documented_columns():
    c = sqlite3.connect(":memory:")
    c.executescript(SCHEMA)
    c.executescript(m13.DDL_PATH.read_text(encoding="utf-8"))
    cols = lambda t: [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    assert cols("document_articles")[:5] == ["article_id", "issue_id", "doc_id", "source_id", "region_id"]
    for t in ("periodical_issues", "document_articles"):
        assert "source_id" in cols(t)  # get_records の既定の絞り列
    assert {t for t in rcommon.source_id_tables(c)} == {"periodical_series", "periodical_issues", "document_articles"}


def test_get_records_description_lists_every_topic_id():
    """get_records の topic 入力の説明（web/src/lib/records.ts）は語彙を直書きする（describe_catalog に topics は無い）。語彙の追加で食い違わない。"""
    src = (m13.ROOT / "web" / "src" / "lib" / "records.ts").read_text(encoding="utf-8")
    missing = [t for t in TOPICS if t not in src]
    assert not missing, missing
