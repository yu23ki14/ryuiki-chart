"""c95（ウミガメ）・c96（ノネコ）の読み取り・検算・cells 組み立てのテスト。合成の行だけで PDF には頼らない。"""
import copy
import sqlite3

import pytest

import c95_kagoshima_umigame as c95
import c96_kagoshima_noneko as c96
import doccells as dc
from tests.test_doccells import SCHEMA


def umigame_rows(h27_total="3,511"):
    rows = [["区分", "H26", "H27", "R元"]]
    for i in range(c95.N_MUNICIPALITIES):
        rows.append([f"市町村{i}", "1" if i < 5 else "-", "0" if i == 0 else ("１" if i < 3 else "－"), "2" if i < 4 else "0"])
    rows.append(["上陸市町村数", "5", "2", "4"])
    rows.append(["合 計", "5", "3,511" if False else h27_total, "8"])
    rows.append([None] * 4)
    return rows


def test_c95_parse_and_verify_declared_exception(monkeypatch):
    # 合成表は宣言と無関係なので、宣言を合成表に合わせて差し替える
    t = c95.parse_table(umigame_rows("3,511"), "上陸市町村数")
    assert t["years"] == [2014, 2015, 2019]
    assert len(t["munis"]) == 39
    monkeypatch.setitem(c95.EXPECTED_SUM_EXCEPTIONS, "p1_t1", {"H27": (3511, 2)})
    monkeypatch.setitem(c95.EXPECTED_COUNT_EXCEPTIONS, "p1_t1", {})
    sums, counts = c95.verify("p1_t1", t)
    assert sums == {"H27": (3511, 2)} and counts == {}
    # 合計が和と一致してしまえば、宣言した例外が食い違っていないので止まる
    t2 = c95.parse_table(umigame_rows("2"), "上陸市町村数")
    with pytest.raises(dc.IdentityError):
        c95.verify("p1_t1", t2)
    # 宣言を外せば宣言にない食い違いで止まる
    monkeypatch.setitem(c95.EXPECTED_SUM_EXCEPTIONS, "p1_t1", {})
    with pytest.raises(dc.IdentityError):
        c95.verify("p1_t1", t)


def test_c95_cells_dash_is_null_and_totals_flagged():
    t = c95.parse_table(umigame_rows(), "上陸市町村数")
    cells = c95.build_cells(1, "p1_t1", t, "上陸市町村数", "sha")
    assert len(cells) == 41 * 3
    dash = [c for c in cells if c["row_key"] == "市町村10" and c["col_key"] == "H27"][0]
    assert dash["value"] is None and dash["value_raw"] == "－"
    zero = [c for c in cells if c["row_key"] == "市町村0" and c["col_key"] == "H27"][0]
    assert zero["value"] == "0"
    fw = [c for c in cells if c["row_key"] == "市町村1" and c["col_key"] == "H27"][0]
    assert fw["value"] == "1"
    assert {c["row_key"] for c in cells if c["is_total"]} == {"上陸市町村数", "合計"}
    assert all(c["fiscal_year"] for c in cells)


def noneko_tables():
    monthly = {"cols": ["4月", "3月", "合計"],
               "rows": {"捕獲頭数": ["6", "13", "19"], "うち譲渡頭数": ["6", "11", "17"],
                        "うち安楽死頭数": ["0", "0", "0"], "その他": ["0", "0", "0"]}}
    annual = {"cols": ["2018年度（7月～3月）", "2019年度", "2022年度", "合計"],
              "rows": {"捕獲頭数": ["43", "125", "19", "187"], "うち譲渡頭数": ["43", "123", "17", "183"],
                       "うち安楽死頭数": ["0", "0", "0", "0"], "その他": ["0", "2", "0", "2"]}}
    return monthly, annual


def test_c96_parse_normalises_labels():
    rows = [["", "2018年度\n（7月～3月）", "合計"], ["捕獲頭数（合計）", "43", "43"], ["うち譲渡頭数（合計）", "43", "43"],
            ["うち安楽死頭数（合計）", "0", "0"], ["その他（合計）", "0", "0"]]
    t = c96.parse_table(rows)
    assert t["cols"] == ["2018年度（7月～3月）", "合計"] and list(t["rows"]) == list(c96.ROW_NAMES.values())


def test_c96_verify_exceptions_and_cells(monkeypatch):
    monthly, annual = noneko_tables()
    monkeypatch.setitem(c96.EXPECTED_SPLIT_EXCEPTIONS, "p1_t1", {"3月": (13, 11), "合計": (19, 17)})
    monkeypatch.setitem(c96.EXPECTED_SPLIT_EXCEPTIONS, "p1_t2", {"2022年度": (19, 17), "合計": (187, 185)})
    # 合成表の年度別 合計は 183+2=185 で捕獲 187（宣言どおり）
    c96.verify(monthly, annual)
    bad = copy.deepcopy(annual)
    bad["rows"]["捕獲頭数"][1] = "126"   # 2019年度に宣言外の食い違い
    bad["rows"]["捕獲頭数"][3] = "188"
    with pytest.raises(dc.IdentityError):
        c96.verify(monthly, bad)
    cells = c96.build_cells(monthly, annual, "sha")
    monthly_cells = [c for c in cells if c["table_id"] == "p1_t1"]
    assert all(c["fiscal_year"] is None for c in monthly_cells)
    annual_cells = [c for c in cells if c["table_id"] == "p1_t2"]
    assert {c["fiscal_year"] for c in annual_cells if not c["is_total"]} == {2018, 2019, 2022}
    assert all(c["is_total"] for c in annual_cells if c["col_key"] == "合計")


def test_c96_monthly_total_must_equal_annual_2022(monkeypatch):
    monthly, annual = noneko_tables()
    monkeypatch.setitem(c96.EXPECTED_SPLIT_EXCEPTIONS, "p1_t1", {"3月": (13, 11), "合計": (19, 17)})
    monkeypatch.setitem(c96.EXPECTED_SPLIT_EXCEPTIONS, "p1_t2", {"2022年度": (19, 17), "合計": (187, 185)})
    annual["rows"]["うち譲渡頭数"][2] = "16"
    with pytest.raises(dc.IdentityError):
        c96.verify(monthly, annual)


def test_notes_block_only_2018_partial_year():
    notes = c96.build_notes()
    blocking = [n for n in notes if n["blocks_timeseries"]]
    assert len(blocking) == 1 and blocking[0]["table_ids"] == ["p1_t2"] and blocking[0]["kind"] == "comparability"
    assert all(n["blocks_timeseries"] == 0 for n in c95.build_notes())


def test_write_doc_end_to_end_keeps_other_docs():
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    dc.replace_doc_cells(con, "other", [{"table_id": "t", "row_key": "r", "value": "1", "value_type": "int"}])
    con.commit()
    monthly, annual = noneko_tables()
    cells = c96.build_cells(monthly, annual, "sha")
    n = dc.write_doc(con, c96.DOC_ID, {"title": "t"}, cells, c96.build_notes())
    assert n == len(cells)
    assert con.execute("SELECT count(*) FROM cells WHERE doc_id='other'").fetchone() == (1,)
    assert con.execute("SELECT note_id FROM notes ORDER BY 1").fetchone() == (f"{c96.DOC_ID}_n001",)
