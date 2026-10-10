"""m03 の赤リスト判定の地域別（県版 → 全国版）と red_list_source、c28 の鹿児島 load。
一時 sqlite だけ（docs/plans/AMAMI_STEP2A.md §3・§4）。"""
import collections
import csv
import json
import pathlib
import sqlite3

import pytest

import c28_redlist_assessments as c28
import m03_organisms as m03

SCRIPTS = pathlib.Path(m03.__file__).parent


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript((SCRIPTS / "schema_app.sql").read_text(encoding="utf-8"))
    c.executescript("""
      CREATE TABLE taxa (taxon_id TEXT PRIMARY KEY, scientific_name TEXT, redlist_kanagawa TEXT,
                         redlist_national TEXT, ias_category TEXT);
      CREATE TABLE redlist_assessments (assessment_id TEXT PRIMARY KEY, list_name TEXT, list_year INTEGER,
        scientific_name TEXT);
    """)
    c.executemany("INSERT INTO taxa VALUES (?,?,?,?,?)", [
        ("aaa bbb", "Aaa bbb", "絶滅危惧Ⅱ類（VU）", "絶滅危惧IB類（EN）", None),   # 神奈川・全国の両方
        ("ccc ddd", "Ccc ddd", None, "準絶滅危惧（NT）", None),                  # 全国だけ
        ("eee fff", "Eee fff", "情報不足（DD）", None, None),                    # 神奈川だけ
        ("ggg hhh", "Ggg hhh", None, "絶滅危惧IA類（CR）", None),                # 全国と鹿児島
        ("zzz", None, None, None, "重点対策外来種"),
    ])
    c.executemany("INSERT INTO redlist_assessments VALUES (?,?,?,?)", [
        ("rl2020_00001", "n", 2020, "Aaa  bbb"), ("rl2026_00001", "n", 2026, "Eee fff"),
    ])
    c.executescript(c28.PREF_LOOKUP_DDL)
    c.executemany("INSERT INTO pref_redlist_lookup VALUES ('jp-46',?,'kgrl2014',?,?)", [
        ("ggg hhh", "絶滅危惧Ⅰ類", "CR+EN"),
        ("iii jjj", "準絶滅危惧", "NT"),   # taxa に無い（鹿児島にだけ載る）種
    ])
    return c


def test_jp14_equals_rk_or_rn_and_source(conn):
    d = m03.taxa_lookup(conn, "jp-14")
    for tid, rk, rn, ias in conn.execute("select taxon_id, redlist_kanagawa, redlist_national, ias_category from taxa"):
        assert d[tid][0] == (rk or rn) and d[tid][1] == ias
    assert d["aaa bbb"][2] == "rl2020"       # 神奈川由来 -> その list
    assert d["eee fff"][2] == "rl2026"
    assert d["ccc ddd"][2] == "national"     # 全国版由来
    assert d["zzz"] == (None, "重点対策外来種", None)


def test_jp46_prefers_pref_then_national(conn):
    d = m03.taxa_lookup(conn, "jp-46")
    assert d["ggg hhh"] == ("絶滅危惧Ⅰ類（CR+EN）", None, "kgrl2014")
    assert d["iii jjj"] == ("準絶滅危惧（NT）", None, "kgrl2014")
    assert d["aaa bbb"] == ("絶滅危惧IB類（EN）", None, "national")   # 県版に無ければ全国版
    assert d["eee fff"][0] is None and d["eee fff"][2] is None         # 神奈川RLだけの種は付かない
    assert d["ccc ddd"] == ("準絶滅危惧（NT）", None, "national")


def test_load_records_store_source_and_category(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(m03, "PROC", tmp_path)
    (tmp_path / "gbif_kanagawa_occurrences.jsonl").write_text(
        json.dumps({"key": 1, "scientificName": "Aaa bbb", "eventDate": "2021-05-01"}) + "\n", encoding="utf-8")
    (tmp_path / "gbif_amami_occurrences.jsonl").write_text(
        "\n".join(json.dumps({"key": k, "scientificName": n, "eventDate": "2021-05-01"})
                  for k, n in ((1, "Aaa bbb"), (2, "Eee fff"), (3, "Ggg hhh"))) + "\n", encoding="utf-8")
    for rid in ("jp-14", "jp-46"):
        m03.load_gbif(conn, m03.taxa_lookup(conn, rid), collections.Counter(), rid)
    got = {r[0]: r[1:] for r in conn.execute(
        "select record_id, red_list_category, publication_scope, red_list_source from organism_records")}
    assert got["gbif_kanagawa_occurrences__1"] == ("絶滅危惧Ⅱ類（VU）", "限定共有", "rl2020")
    assert got["gbif_amami_occurrences__1"] == ("絶滅危惧IB類（EN）", "限定共有", "national")
    assert got["gbif_amami_occurrences__2"] == (None, "全公開", None)
    assert got["gbif_amami_occurrences__3"] == ("絶滅危惧Ⅰ類（CR+EN）", "限定共有", "kgrl2014")
    # 再投入で既存行の判定が更新される（奄美の判定が変わっても神奈川は同じ）
    conn.execute("UPDATE organism_records SET red_list_category=NULL, red_list_source=NULL")
    for rid in ("jp-14", "jp-46"):
        m03.load_gbif(conn, m03.taxa_lookup(conn, rid), collections.Counter(), rid)
    assert conn.execute("select red_list_source from organism_records where record_id='gbif_kanagawa_occurrences__1'"
                        ).fetchone()[0] == "rl2020"


def test_ensure_red_list_source_column_is_idempotent():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE organism_records (record_id TEXT PRIMARY KEY)")
    assert m03.ensure_red_list_source_column(c) is True
    assert m03.ensure_red_list_source_column(c) is False


def _write(path, rows):
    cols = ["taxon_group_ja", "scientific_name", "vernacular_name_ja", "category_code", "category_ja",
            "list_year", "source_id", "source_ref", "scientific_name_raw"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: "" for k in cols}, **r})


def test_c28_kagoshima_load(tmp_path, monkeypatch):
    monkeypatch.setattr(c28, "PROC", tmp_path)
    _write(tmp_path / "kagoshima_redlist.csv", [
        {"scientific_name": "Aaa bbb", "vernacular_name_ja": "ア", "category_code": "NT", "category_ja": "準絶滅危惧"},
        {"scientific_name": "Aaa bbb", "vernacular_name_ja": "ア2", "category_code": "CR+EN", "category_ja": "絶滅危惧Ⅰ類"},
        {"scientific_name": "", "vernacular_name_ja": "学名なし", "category_code": "DD", "category_ja": "情報不足"},
    ])
    _write(tmp_path / "kagoshima_ordinance_species.csv", [
        {"scientific_name": "Ccc ddd", "vernacular_name_ja": "ウ", "category_code": "", "category_ja": "－"},
    ])
    conn = sqlite3.connect(":memory:")
    conn.executescript(c28.DDL)
    c28.load_kagoshima_redlist(conn)
    c28.load_kagoshima_ordinance(conn)
    ids = [r[0] for r in conn.execute("select assessment_id from redlist_assessments order by 1")]
    assert ids == ["kgord_00001", "kgrl2014_00001", "kgrl2014_00002", "kgrl2014_00003"]
    # 同じ学名は厳しい方。学名の無い行は lookup に入らない。条例の種は lookup に入れない
    assert conn.execute("select taxon_id, category_ja, category_code, list_id from pref_redlist_lookup").fetchall() == [
        ("aaa bbb", "絶滅危惧Ⅰ類", "CR+EN", "kgrl2014")]
    c28.load_kagoshima_redlist(conn)   # 冪等
    assert conn.execute("select count(*) from pref_redlist_lookup").fetchone()[0] == 1
