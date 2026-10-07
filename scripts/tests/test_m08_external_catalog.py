"""m08_external_catalog（外部ポータルの目録の投入。docs/plans/MCP_EXTERNAL_CATALOG.md §1・§3）のテスト。

fixture の小さな jsonl・CSV で通す（本物の ryuiki.sqlite・data/processed には触らない）。
実データの件数・URL 規則の照合は、data/processed の jsonl があるときだけ（`needs_real`。CI では skip）。
"""
import json
import pathlib
import sqlite3

import pytest

import m08_external_catalog as m08

ROOT = pathlib.Path(__file__).resolve().parents[2]
REAL_PROC = ROOT / "data" / "processed"
needs_real = pytest.mark.skipif(
    not all((REAL_PROC / f).exists() for f in ("ckan_datasets.jsonl", "ckan_resources_yokohama.jsonl", "ckan_env_index.jsonl")),
    reason="data/processed の収穫物が無い（CI 等）",
)

FETCHED = {
    "ckan_kanagawa_pref": "2026-08-29T14:40:39", "ckan_sagamihara": "2026-08-29T14:40:39",
    "ckan_bodik_kanagawa": "2026-08-30T16:31:45", "ckan_yokohama": "2026-08-30T16:21:00",
    "estat_agri_census_kanagawa": "2026-08-29T15:29:20", "estat_census_population_kanagawa": "2026-08-29T15:31:49",
    "estat_shozaiki_kanagawa": "2026-09-05T16:54:15",
}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def ds(inst, did, name, **kw):
    base = {"instance": inst, "dataset_id": did, "name": name, "title": f"題 {name}", "notes": "", "organization": "組織",
            "license": "CC-BY", "license_url": "https://l/", "groups": "g1|g2", "tags": "t1|t2", "n_resources": 1,
            "metadata_modified": "2026-08-28T06:35:44.764330", "url": f"{m08.CKAN_INSTANCES[inst][1]}/dataset/{name}"}
    base.update(kw)
    return base


def res(inst, did, rid, **kw):
    base = {"instance": inst, "dataset_id": did, "dataset_title": "x", "resource_id": rid, "resource_name": f"資源 {rid}", "format": "CSV",
            "url": f"https://f/{rid}.csv", "size": 123, "last_modified": "2026-08-01T00:00:00"}
    base.update(kw)
    return base


def env(rid, inst, out, note="sheet=S1", needs_human="False", n_rows="10.0", n_cols="3.0"):
    return {"resource_id": rid, "instance": inst, "output_path": out, "note": note, "needs_human": needs_human,
            "n_rows": n_rows, "n_cols": n_cols, "source_id": "ckan_env_bulk"}


def estat_row(table_ja, sid, ind, unit, ref, notes=""):
    return {"source_id": sid, "table_ja": table_ja, "indicator_ja": ind, "unit_ja": unit,
            "source_ref": f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={ref}&fileKind=0 (statInfId={ref})", "notes": notes}


@pytest.fixture
def proc(tmp_path):
    p = tmp_path / "processed"
    p.mkdir()
    (p / "ckan_env").mkdir()
    write_jsonl(p / "ckan_datasets.jsonl", [
        ds("kanagawa_pref", "u-k1", "k1"), ds("kanagawa_pref", "u-k2", "k2", license="", notes="あ" * 800),
        ds("sagamihara", "u-s1", "s1", license=""),
    ])
    write_jsonl(p / "ckan_resources.jsonl", [
        res("kanagawa_pref", "u-k1", "r-k1a", format="XLSX"), res("kanagawa_pref", "u-k1", "r-k1b", format="SHP,CSV"),
        res("kanagawa_pref", "u-k2", "r-k2", url=""), res("sagamihara", "u-s1", "r-s1", format=""),
    ])
    write_jsonl(p / "ckan_datasets_bodik.jsonl", [ds("bodik_kanagawa", "u-b1", "b1")])
    write_jsonl(p / "ckan_resources_bodik.jsonl", [res("bodik_kanagawa", "u-b1", "r-b1")])
    write_jsonl(p / "ckan_datasets_yokohama.jsonl", [ds("yokohama", "u-y1", "y1")])
    write_jsonl(p / "ckan_resources_yokohama.jsonl", [res("yokohama", "u-y1", "r-y1")])
    (p / "ckan_env" / "good.csv").write_text("﻿地点,項目,値\n1,2,3\n", encoding="utf-8")
    (p / "ckan_env" / "bad.csv").write_text("col_0,col_1,col_2\n1,2,3\n", encoding="utf-8")
    (p / "ckan_env" / "multi.csv").write_text('"地点\nコード",名称,値\n', encoding="utf-8")
    write_jsonl(p / "ckan_env_index.jsonl", [
        env("r-k1a", "kanagawa_pref", "ckan_env/good.csv", note="sheet=シート1 encoding=utf-8"),
        env("r-k1a", "kanagawa_pref", "ckan_env/bad.csv", note="sheet=シート2"),
        env("r-k1b", "kanagawa_pref", "ckan_env/good.csv", needs_human="True"),
        env("r-s1", "sagamihara", "ckan_env/multi.csv", note="encoding=cp932"),
        env("web_abc", "kanagawa_pref_web", "ckan_env/good.csv"),            # CKAN 外
        env("r-k2", "kanagawa_pref", ""),                                     # 変換できなかった
    ])
    write_jsonl(p / "estat_agri_census_kanagawa.jsonl", [
        estat_row("農林業センサス 2015 表A", "estat_agri_census_kanagawa", "計", "経営体", "000031511885"),
        estat_row("農林業センサス 2015 表A", "estat_agri_census_kanagawa", "個人", "経営体", "000031511885"),
        estat_row("農林業センサス 2015 表A", "estat_agri_census_kanagawa", "計", "経営体", "000031511885"),
        estat_row("農林業センサス 2020 表B", "estat_agri_census_kanagawa", "総数", "ha", "000032153273"),
    ])
    write_jsonl(p / "estat_census_population_kanagawa.jsonl", [
        estat_row(None, "estat_census_population_kanagawa", "人口（総数）", "人", m08.CENSUS_POP_ID, "組替の注記"),
        estat_row(None, "estat_census_population_kanagawa", "世帯数", "世帯", m08.CENSUS_POP_ID, "組替の注記"),
    ])
    write_jsonl(p / "estat_shozaiki_kanagawa.jsonl", [{"key_code": "1"}])
    return p


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT, license TEXT, fetched_at TEXT)")
    for sid, f in FETCHED.items():
        c.execute("INSERT INTO source_registry VALUES (?,?,?,?,?,?)", (sid, f"名 {sid}", f"提供 {sid}", f"https://page/{sid}", "規約", f))
    return c


def q(con, sql, *a):
    return con.execute(sql, a).fetchall()


def test_counts_and_keys(con, proc):
    res_ = m08.load(con, proc, root=proc)
    # 4 インスタンス（神奈川県 2・相模原 1・BODIK 1・横浜 1）+ e-Stat（農林業 2 表・国勢調査 1・境界 1）
    assert (res_["datasets"], res_["resources"], res_["orphans"], res_["skipped"]) == (5 + 4, 6 + 4, 0, [])
    assert res_["by_source"] == {"ckan_bodik_kanagawa": 1, "ckan_kanagawa_pref": 2, "ckan_sagamihara": 1, "ckan_yokohama": 1,
                                 "estat_agri_census_kanagawa": 2, "estat_census_population_kanagawa": 1, "estat_shozaiki_kanagawa": 1}
    assert q(con, "SELECT count(DISTINCT dataset_key), count(*) FROM external_dataset") == [(9, 9)]
    assert q(con, "SELECT count(DISTINCT resource_key), count(*) FROM external_resource") == [(10, 10)]
    assert q(con, "SELECT count(*) FROM external_resource r WHERE NOT EXISTS (SELECT 1 FROM external_dataset d WHERE d.dataset_key = r.dataset_key)") == [(0,)]
    assert q(con, "SELECT dataset_key FROM external_dataset WHERE source_id='ckan_sagamihara'") == [("ckan_sagamihara:u-s1",)]


def test_ckan_urls_follow_the_rule_for_each_instance(con, proc):
    m08.load(con, proc, root=proc)
    cases = {"ckan_kanagawa_pref": ("u-k1", "k1"), "ckan_sagamihara": ("u-s1", "s1"), "ckan_bodik_kanagawa": ("u-b1", "b1"), "ckan_yokohama": ("u-y1", "y1")}
    bases = {"ckan_kanagawa_pref": "https://catalog.opendata.pref.kanagawa.jp", "ckan_sagamihara": "https://opendata.city.sagamihara.kanagawa.jp",
             "ckan_bodik_kanagawa": "https://data.bodik.jp", "ckan_yokohama": "https://data.city.yokohama.lg.jp"}
    assert bases == {sid: base for sid, base in m08.CKAN_INSTANCES.values()}  # BODIK は c01 の誤った base（odcs.bodik.jp）ではない
    for sid, (did, name) in cases.items():
        page, api, fetched = q(con, "SELECT page_url, api_url, fetched_at FROM external_dataset WHERE dataset_key = ?", f"{sid}:{did}")[0]
        assert page == f"{bases[sid]}/dataset/{name}"
        assert api == f"{bases[sid]}/api/3/action/package_show?id={did}"  # name ではなく UUID
        assert fetched == FETCHED[sid]
    rid = {"ckan_kanagawa_pref": "r-k1a", "ckan_sagamihara": "r-s1", "ckan_bodik_kanagawa": "r-b1", "ckan_yokohama": "r-y1"}
    for sid, r in rid.items():
        (page,) = q(con, "SELECT page_url FROM external_resource WHERE resource_key = ?", f"{sid}:{r}")[0]
        assert page == f"{bases[sid]}/dataset/{cases[sid][0]}/resource/{r}"


def test_empty_license_is_null_not_dropped_and_empty_url_is_null(con, proc):
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT license FROM external_dataset WHERE dataset_key='ckan_kanagawa_pref:u-k2'") == [(None,)]
    assert q(con, "SELECT license FROM external_dataset WHERE dataset_key='ckan_sagamihara:u-s1'") == [(None,)]
    assert q(con, "SELECT direct_url FROM external_resource WHERE resource_key='ckan_kanagawa_pref:r-k2'") == [(None,)]
    assert q(con, "SELECT format FROM external_resource WHERE resource_key='ckan_sagamihara:r-s1'") == [(None,)]
    assert q(con, "SELECT description_truncated FROM external_dataset WHERE dataset_key LIKE 'ckan_kanagawa_pref:%' ORDER BY dataset_key") == [(0,), (1,)]


def test_header_only_for_reliable_sheets(con, proc):
    m08.load(con, proc, root=proc)
    sheets = json.loads(q(con, "SELECT sheets_json FROM external_resource WHERE resource_key='ckan_kanagawa_pref:r-k1a'")[0][0])
    assert sheets == [
        {"sheet": "シート1", "n_rows": 10, "n_cols": 3, "header": ["地点", "項目", "値"], "header_basis": "converted_csv_first_row"},
        {"sheet": "シート2", "n_rows": 10, "n_cols": 3, "header": None},  # col_N は見出しではない（推測しない）
    ]
    # needs_human=True は見出しとしない。CKAN 外（web_）・変換できなかった行は入らない
    s = json.loads(q(con, "SELECT sheets_json FROM external_resource WHERE resource_key='ckan_kanagawa_pref:r-k1b'")[0][0])
    assert s[0]["header"] is None and s[0]["n_rows"] == 10
    assert q(con, "SELECT sheets_json FROM external_resource WHERE resource_key='ckan_kanagawa_pref:r-k2'") == [(None,)]
    # 改行を含むセルは空白 1 つにそろえる。note が sheet= でなければ sheet は null
    s = json.loads(q(con, "SELECT sheets_json FROM external_resource WHERE resource_key='ckan_sagamihara:r-s1'")[0][0])
    assert s[0]["sheet"] is None and s[0]["header"] == ["地点 コード", "名称", "値"]


@pytest.mark.parametrize(
    "cells, needs_human, ok",
    [
        (["地点", "項目", "値"], False, True),
        (["地点", "項目", "値"], True, False),              # needs_human
        (["col_0", "col_1", "col_2"], False, False),
        (["field_1", "field_2", "x"], False, False),
        (["2020", "2021", "年"], False, False),              # 数値の見出し
        (["地点", "", ""], False, False),                    # 空が多い
        (["地点", "項目", "col_2"], False, True),            # ちょうど 3 分の 2
        (["地点", "col_1", "col_2"], False, False),
        ([], False, False),
    ],
)
def test_header_is_reliable_criterion(cells, needs_human, ok):
    assert m08.header_is_reliable(cells, needs_human) is ok


def test_estat_rows(con, proc):
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT dataset_key, title, page_url, api_url, organization, license, fetched_at FROM external_dataset WHERE dataset_key = 'estat_agri_census_kanagawa:000031511885'") == [
        ("estat_agri_census_kanagawa:000031511885", "農林業センサス 2015 表A", "https://www.e-stat.go.jp/stat-search/files?stat_infid=000031511885", None,
         "提供 estat_agri_census_kanagawa", "規約", "2026-08-29T15:29:20")]
    d, sheets = q(con, "SELECT direct_url, sheets_json FROM external_resource WHERE dataset_key = 'estat_agri_census_kanagawa:000031511885'")[0]
    assert d == "https://www.e-stat.go.jp/stat-search/file-download?statInfId=000031511885&fileKind=0"
    sh = json.loads(sheets)[0]
    assert sh["header"] == ["計", "個人"] and sh["units"] == ["経営体"] and sh["header_basis"] == "harvested_indicators"  # 出現順・重複なし・値は持たない
    pop = q(con, "SELECT dataset_id, title, description FROM external_dataset WHERE source_id='estat_census_population_kanagawa'")[0]
    assert pop == (m08.CENSUS_POP_ID, m08.CENSUS_POP_TITLE, "組替の注記")
    geo = q(con, "SELECT dataset_key, page_url FROM external_dataset WHERE source_id='estat_shozaiki_kanagawa'")[0]
    assert geo == (f"estat_shozaiki_kanagawa:{m08.SHOZAIKI_DLSURVEY}", "https://page/estat_shozaiki_kanagawa")
    (du, js) = q(con, "SELECT direct_url, sheets_json FROM external_resource WHERE dataset_key LIKE 'estat_shozaiki%'")[0]
    assert du == m08.SHOZAIKI_DATA and json.loads(js)[0]["header"] is None


def test_estat_indicators_are_capped(con, proc):
    rows = [estat_row("表", "estat_agri_census_kanagawa", f"指標{i}", "x", "000031511885") for i in range(25)]
    write_jsonl(proc / "estat_agri_census_kanagawa.jsonl", rows)
    m08.load(con, proc, root=proc)
    sh = json.loads(q(con, "SELECT sheets_json FROM external_resource WHERE dataset_key = 'estat_agri_census_kanagawa:000031511885'")[0][0])[0]
    assert len(sh["header"]) == m08.ESTAT_INDICATOR_MAX and sh["header_truncated"] is True


def test_idempotent_and_only_touches_own_sources(con, proc):
    first = m08.load(con, proc, root=proc)
    again = m08.load(con, proc, root=proc)
    assert (first["datasets"], first["resources"]) == (again["datasets"], again["resources"])
    snap = q(con, "SELECT * FROM external_resource ORDER BY resource_key")
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT * FROM external_resource ORDER BY resource_key") == snap


def test_missing_inputs_are_skipped_and_existing_rows_kept(con, proc):
    m08.load(con, proc, root=proc)
    (proc / "ckan_datasets_yokohama.jsonl").unlink()
    (proc / "estat_shozaiki_kanagawa.jsonl").unlink()
    res_ = m08.load(con, proc, root=proc)
    assert sorted(res_["skipped"]) == ["ckan_yokohama", "estat_shozaiki_kanagawa"]
    assert res_["datasets"] == 9 and res_["resources"] == 10  # 入力の無い出典の既存行は触らない


def test_duplicate_or_orphan_inputs_stop(con, proc):
    write_jsonl(proc / "ckan_resources_yokohama.jsonl", [res("yokohama", "u-NOPE", "r-y1")])
    with pytest.raises(m08.M08Error, match="目録に無い"):
        m08.load(con, proc, root=proc)
    write_jsonl(proc / "ckan_resources_yokohama.jsonl", [res("yokohama", "u-y1", "r-y1"), res("yokohama", "u-y1", "r-y1")])
    with pytest.raises(m08.M08Error, match="重複"):
        m08.load(con, proc, root=proc)
    write_jsonl(proc / "ckan_resources_yokohama.jsonl", [res("yokohama", "u-y1", "r-y1")])
    write_jsonl(proc / "ckan_datasets_yokohama.jsonl", [ds("yokohama", "u-y1", "y1", url="https://elsewhere/dataset/y1")])
    with pytest.raises(m08.M08Error, match="規則から外れている"):
        m08.load(con, proc, root=proc)


def test_unregistered_source_stops(proc):
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT, license TEXT, fetched_at TEXT)")
    with pytest.raises(m08.M08Error, match="source_registry"):
        m08.load(c, proc, root=proc)


def test_stale_input_warning(proc):
    import time
    old = time.time() - 40 * 86400
    import os
    os.utime(proc / "ckan_datasets.jsonl", (old, old))
    w = m08.stale_warnings(proc)
    assert len(w) == 1 and "ckan_datasets.jsonl" in w[0]


def test_estat_urls_match_the_collectors_constants():
    """c64/c90 を import せず（requests・shapely が要る）、収集スクリプトの文字列と一致していることを固定する。"""
    c64 = (ROOT / "scripts" / "c64_estat_kanagawa.py").read_text(encoding="utf-8")
    c90 = (ROOT / "scripts" / "c90_estat_shozaiki.py").read_text(encoding="utf-8")
    assert "https://www.e-stat.go.jp/stat-search/file-download?statInfId={f['stat_inf_id']}&fileKind=0" in c64
    assert f'CENSUS_POP_STAT_INF_ID = "{m08.CENSUS_POP_ID}"' in c64
    assert m08.ESTAT_FILE.format(id="X") == "https://www.e-stat.go.jp/stat-search/file-download?statInfId=X&fileKind=0"
    query = m08.SHOZAIKI_DATA.split("/data", 1)[1]
    assert query == f"?dlserveyId={m08.SHOZAIKI_DLSURVEY}&code=14&coordSys=1&format=shape&downloadType=5"
    assert f'"{query}"' in c90 and '"https://www.e-stat.go.jp/gis/statmap-search/data"' in c90
    # CKAN の base: c86 の BODIK・横浜、c01 の県・相模原（BODIK は c86 の注記どおり data.bodik.jp）
    c86 = (ROOT / "scripts" / "c86_ckan_bodik_yokohama.py").read_text(encoding="utf-8")
    c01 = (ROOT / "scripts" / "c01_ckan.py").read_text(encoding="utf-8")
    assert f'BODIK_BASE = "{m08.CKAN_INSTANCES["bodik_kanagawa"][1]}"' in c86
    assert f'YOKOHAMA_BASE = "{m08.CKAN_INSTANCES["yokohama"][1]}"' in c86
    assert m08.CKAN_INSTANCES["kanagawa_pref"][1] in c01 and m08.CKAN_INSTANCES["sagamihara"][1] in c01


@needs_real
def test_real_inputs_row_counts_and_url_rule(tmp_path):
    """実データの jsonl（読むだけ）から、設計の見込み（dataset 2,266・resource 23,251）と URL 規則を照合する。"""
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT, license TEXT, fetched_at TEXT)")
    for sid, f in FETCHED.items():
        c.execute("INSERT INTO source_registry VALUES (?,?,?,?,?,?)", (sid, f"名 {sid}", "p", "https://page", "l", f))
    res_ = m08.load(c, REAL_PROC, root=ROOT)
    assert (res_["datasets"], res_["resources"], res_["orphans"]) == (2266, 23251, 0)
    assert res_["by_source"] == {"ckan_bodik_kanagawa": 680, "ckan_kanagawa_pref": 811, "ckan_sagamihara": 114, "ckan_yokohama": 654,
                                 "estat_agri_census_kanagawa": 5, "estat_census_population_kanagawa": 1, "estat_shozaiki_kanagawa": 1}
    assert c.execute("SELECT count(*) FROM external_resource WHERE direct_url IS NULL").fetchone()[0] == 3
    assert res_["sheets_unmatched"] == 0
    assert c.execute("SELECT count(*) FROM external_resource WHERE sheets_json LIKE '%\"header_basis\": \"converted_csv_first_row\"%'").fetchone()[0] > 100


@pytest.mark.parametrize("raw,expected", [
    ("CSV", ["CSV"]), (" .csv ", ["CSV"]), (".CSV", ["CSV"]), ("XLSK", ["XLSX"]), ("SHP,CSV", ["SHP", "CSV"]),
    ("shp, .csv ,CSV", ["SHP", "CSV"]), ("jpg", ["JPEG"]), ("", ["unspecified"]), (None, ["unspecified"]), (" , ", ["unspecified"]),
])
def test_normalize_formats(raw, expected):
    assert m08.normalize_formats(raw) == expected


def test_format_table_keeps_raw_and_matches_by_equality(con, proc):
    write_jsonl(proc / "ckan_resources.jsonl", [
        res("kanagawa_pref", "u-k1", "r-k1a", format="XLSK"), res("kanagawa_pref", "u-k1", "r-k1b", format="SHP,CSV"),
        res("kanagawa_pref", "u-k2", "r-k2", format=".CSV"), res("sagamihara", "u-s1", "r-s1", format=""),
    ])
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT format FROM external_resource WHERE resource_key='ckan_kanagawa_pref:r-k1a'") == [("XLSK",)]  # 原文は残す
    got = q(con, "SELECT dataset_key, format_norm FROM external_resource_format WHERE dataset_key LIKE 'ckan_%' ORDER BY 1, 2")
    assert sorted(got) == [
        ("ckan_bodik_kanagawa:u-b1", "CSV"), ("ckan_kanagawa_pref:u-k1", "CSV"), ("ckan_kanagawa_pref:u-k1", "SHP"),
        ("ckan_kanagawa_pref:u-k1", "XLSX"), ("ckan_kanagawa_pref:u-k2", "CSV"), ("ckan_sagamihara:u-s1", "unspecified"),
        ("ckan_yokohama:u-y1", "CSV")]
    n = q(con, "SELECT count(*) FROM external_resource_format")[0][0]
    m08.load(con, proc, root=proc)  # 冪等
    assert q(con, "SELECT count(*) FROM external_resource_format") == [(n,)]


def test_n_with_header_is_a_dataset_column(con, proc):
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT n_with_header FROM external_dataset WHERE dataset_key='ckan_kanagawa_pref:u-k1'") == [(1,)]
    assert q(con, "SELECT n_with_header FROM external_dataset WHERE dataset_key='ckan_kanagawa_pref:u-k2'") == [(0,)]
    assert q(con, "SELECT n_with_header FROM external_dataset WHERE source_id='estat_shozaiki_kanagawa'") == [(0,)]
    assert q(con, "SELECT min(n_with_header) FROM external_dataset WHERE source_id='estat_census_population_kanagawa'") == [(1,)]


def test_old_schema_without_n_with_header_is_upgraded(con, proc):
    m08.load(con, proc, root=proc)
    con.execute("ALTER TABLE external_dataset DROP COLUMN n_with_header")
    m08.load(con, proc, root=proc)
    assert q(con, "SELECT n_with_header FROM external_dataset WHERE dataset_key='ckan_kanagawa_pref:u-k1'") == [(1,)]


def test_page_url_falls_back_to_dataset_id_when_name_is_empty(con, proc):
    write_jsonl(proc / "ckan_datasets.jsonl", [ds("kanagawa_pref", "u-k1", "", url=""), ds("kanagawa_pref", "u-k2", None, url=""),
                                               ds("sagamihara", "u-s1", "s1")])
    write_jsonl(proc / "ckan_resources.jsonl", [res("kanagawa_pref", "u-k1", "r1"), res("kanagawa_pref", "u-k2", "r2"), res("sagamihara", "u-s1", "r3")])
    m08.load(con, proc, root=proc)
    base = m08.CKAN_INSTANCES["kanagawa_pref"][1]
    assert q(con, "SELECT page_url, name FROM external_dataset WHERE dataset_key IN ('ckan_kanagawa_pref:u-k1','ckan_kanagawa_pref:u-k2') ORDER BY dataset_key") == [
        (f"{base}/dataset/u-k1", None), (f"{base}/dataset/u-k2", None)]


def test_estat_sheet_has_no_basis_without_indicators():
    s = m08.estat_sheet([{"indicator_ja": None, "unit_ja": None}])
    assert s["header"] is None and "header_basis" not in s


def test_if_empty_mode(tmp_path, proc, capsys):
    db = tmp_path / "r.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT, license TEXT, fetched_at TEXT)")
    for sid, f in FETCHED.items():
        c.execute("INSERT INTO source_registry VALUES (?,?,?,?,?,?)", (sid, f"名 {sid}", f"提供 {sid}", f"https://page/{sid}", "規約", f))
    c.commit()
    c.close()
    assert not m08.catalog_populated(str(db))
    # 入力が無い → 直し方を書いて止まる
    with pytest.raises(SystemExit):
        m08.main(["--db", str(db), "--processed", str(tmp_path / "none"), "--if-empty"])
    assert "m08_external_catalog.py" in capsys.readouterr().err
    # 入力がある → 作る。次は何もしない
    m08.main(["--db", str(db), "--processed", str(proc), "--if-empty"])
    assert m08.catalog_populated(str(db))
    capsys.readouterr()
    m08.main(["--db", str(db), "--processed", str(tmp_path / "none"), "--if-empty"])
    assert "投入済み" in capsys.readouterr().out
