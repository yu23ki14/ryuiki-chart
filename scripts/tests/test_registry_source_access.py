"""source_access（MCP の出典アクセス。docs/plans/MCP_SOURCE_ACCESS.md §1）。

1. 宣言の検査（偽の source_registry 行・偽の件数で宣言を壊し、止まることを固定する。原本は要らない）
2. 実データ（`data/db/ryuiki.sqlite` があるときだけ）: 実際の access.yaml が全出典を過不足なく覆い、
   宣言を壊す変異（行の無い表を records に足す・行のある出典に reason を付ける・出典を 1 つ消す）で止まる
"""
import copy
import hashlib
import json
import sqlite3

import pytest

from registry import build_source_access as bsa
from registry import common

RYUIKI = common.DB_DIR / "ryuiki.sqlite"
needs_ryuiki = pytest.mark.skipif(not RYUIKI.exists(), reason="原本 ryuiki.sqlite が無い（CI 等）")


def _reg(*ids):
    return [{"source_id": i, "record_count": 10, "fetched_at": "2026-10-01T00:00:00"} for i in ids]


def _doc(**sources):
    return {
        "reasons": {"cube_only": {"ja": "c"}, "file_only": {"ja": "f"}, "synthetic": {"ja": "s"}, "not_in_d1": {"ja": "n"}, "superseded": {"ja": "u"}},
        "record_sets": {"sites": "sites", "protected_areas": "protected_areas", "sightings": "wildlife_sightings"},
        "sources": sources,
        "extra_tools": {},
    }


def _counts(**by_table):
    return {"by_source": by_table}


def _build(reg, targets, doc, counts, sup=None):
    return bsa.assemble(reg, targets, doc, counts, superseded_by=sup)


def test_states_and_counts():
    doc = _doc(a={"records": ["sites"]}, b={"reason": "file_only", "basis": "x"})
    rows = _build(_reg("a", "b", "m"), {"m": "observation"}, doc, _counts(sites={"a": 3}, measurements={"m": 7}))
    by = {r[0]: dict(zip(bsa.COLUMNS, r)) for r in rows}
    assert by["a"]["state"] == "queryable" and by["a"]["queryable_via"] == '["get_records"]' and by["a"]["n_source_rows"] == 3
    assert by["m"]["queryable_via"] == '["get_observations"]' and by["m"]["n_source_rows"] == 7
    assert by["b"]["state"] == "not_queryable" and by["b"]["n_source_rows"] is None and by["b"]["n_source_rows_basis"] == "none"
    assert by["b"]["reason"] == "file_only" and by["b"]["reason_ja"] == "f"


def test_cube_only_drops_the_tool_but_stays_a_declared_reason():
    doc = _doc(m={"reason": "cube_only", "basis": "x"})
    rows = _build(_reg("m"), {"m": "observation"}, doc, _counts(sensor_timeseries={"m": 5}))
    r = dict(zip(bsa.COLUMNS, rows[0]))
    assert (r["state"], r["queryable_via"], r["reason"], r["n_source_rows"]) == ("not_queryable", "[]", "cube_only", None)


def test_manifest_source_without_rows_uses_registry_record_count():
    rows = _build(_reg("m"), {"m": "observation"}, _doc(), _counts())
    r = dict(zip(bsa.COLUMNS, rows[0]))
    assert (r["n_source_rows"], r["n_source_rows_basis"]) == (10, "registry_record_count")


def test_manifest_source_can_add_records_and_extra_tools():
    doc = _doc(k={"records": ["sightings"]})
    doc["extra_tools"] = {"k": ["get_edna"]}
    rows = _build(_reg("k"), {"k": "occurrence"}, doc, _counts(organism_records={"k": 5}, wildlife_sightings={"k": 2}))
    assert dict(zip(bsa.COLUMNS, rows[0]))["queryable_via"] == '["get_occurrences", "get_edna", "get_records"]'


@pytest.mark.parametrize(
    "mutate, msg",
    [
        (lambda d: d["sources"].pop("b"), "状態の無い出典"),  # 出典を 1 つ消す
        (lambda d: d["sources"].update(a={"records": ["sites"], "reason": "file_only", "basis": "x"}), "どちらか一方"),
        (lambda d: d["sources"].update(a={}), "どちらか一方"),
        (lambda d: d["sources"].update(b={"reason": "nope", "basis": "x"}), "語彙"),
        (lambda d: d["sources"].update(b={"reason": "file_only"}), "basis"),
        (lambda d: d["sources"].update(a={"records": ["taxa"]}), "record_sets に無い"),  # D1 に無い表
        (lambda d: d["sources"].update(a={"records": ["water_zone"]}), "record_sets に無い"),
        (lambda d: d["record_sets"].update(x="taxa"), "許可リスト"),
        (lambda d: d["sources"].update(a={"records": ["sites", "sites"]}), "重複"),
        (lambda d: d["sources"].update(m={"reason": "file_only", "basis": "x"}), "合わない"),
        (lambda d: d["sources"].update(a={"reason": "cube_only", "basis": "x"}), "合わない"),
        (lambda d: d["sources"].update(zzz={"reason": "file_only", "basis": "x"}), "source_registry に無い"),
        (lambda d: d.__setitem__("extra_tools", {"a": ["get_edna"]}), "マニフェストの出典ではない"),
        (lambda d: d.__setitem__("extra_tools", {"m": ["get_sql"]}), "未対応"),
        (lambda d: d["sources"].update(b={"reason": "superseded", "basis": "x"}), "superseded_by"),
    ],
)
def test_static_mutations_stop(mutate, msg):
    doc = _doc(a={"records": ["sites"]}, b={"reason": "file_only", "basis": "x"})
    mutate(doc)
    with pytest.raises(bsa.AccessError, match=msg):
        _build(_reg("a", "b", "m"), {"m": "observation"}, doc, _counts(sites={"a": 3}, measurements={"m": 1}))


def test_records_table_without_rows_stops():
    doc = _doc(a={"records": ["sites", "protected_areas"]})
    with pytest.raises(bsa.AccessError, match="1 つも無い"):
        _build(_reg("a"), {}, doc, _counts(sites={"a": 3}))


def test_reason_source_with_rows_stops_but_row_reasons_need_rows():
    doc = _doc(b={"reason": "file_only", "basis": "x"})
    with pytest.raises(bsa.AccessError, match="原本に行がある"):
        _build(_reg("b"), {}, doc, _counts(sites={"b": 1}))
    for code in ("synthetic", "not_in_d1"):
        doc = _doc(b={"reason": code, "basis": "x"})
        _build(_reg("b"), {}, doc, _counts(sites={"b": 1}))  # 行があって通る
        with pytest.raises(bsa.AccessError, match="原本に行が無い"):
            _build(_reg("b"), {}, doc, _counts())


def test_superseded_must_match_registry():
    doc = _doc(b={"reason": "superseded", "basis": "x"})
    _build(_reg("b"), {}, doc, _counts(), sup={"b": "c"})
    with pytest.raises(bsa.AccessError, match="食い違う"):
        _build(_reg("b"), {}, _doc(b={"reason": "file_only", "basis": "x"}), _counts(), sup={"b": "c"})


def test_static_check_alone_does_not_need_counts():
    doc = _doc(a={"records": ["sites"]})
    assert _build(_reg("a"), {}, doc, None) == []


# ---------------------------------------------------------------------------
# 実データ
# ---------------------------------------------------------------------------

def _real():
    ryuiki = sqlite3.connect(f"file:{RYUIKI}?mode=ro", uri=True)
    reg_rows = [
        dict(zip(("source_id", "record_count", "fetched_at"), r))
        for r in ryuiki.execute("SELECT source_id, record_count, fetched_at FROM source_registry ORDER BY source_id")
    ]
    registry = sqlite3.connect(":memory:")
    registry.execute("CREATE TABLE taxon_assessment (source_id TEXT)")
    # taxon_assessment は registry.sqlite 由来（実物があれば読む）
    if common.REGISTRY_DB.exists():
        src = sqlite3.connect(f"file:{common.REGISTRY_DB}?mode=ro", uri=True)
        registry.executemany("INSERT INTO taxon_assessment VALUES (?)", src.execute("SELECT source_id FROM taxon_assessment").fetchall())
        sup = dict(src.execute("SELECT source_id, superseded_by FROM source").fetchall())
    else:
        pytest.skip("registry.sqlite が無い")
    doc = bsa.load_access_yaml()
    targets = bsa._manifest_targets()
    counts = bsa.gather_counts(ryuiki, registry)
    return reg_rows, targets, doc, counts, sup


@needs_ryuiki
def test_real_declaration_covers_every_source_and_matches_data():
    reg, targets, doc, counts, sup = _real()
    rows = bsa.assemble(reg, targets, doc, counts, superseded_by=sup)
    assert len(rows) == len(reg) == 125
    by = {r[0]: dict(zip(bsa.COLUMNS, r)) for r in rows}
    assert sum(1 for r in by.values() if r["state"] == "queryable") == 15 - 4 + 15  # manifests 15（うち cube_only 4）+ records のうち manifests 外の 15
    for sid, r in by.items():
        if r["state"] == "not_queryable":
            assert r["reason"] and r["reason_ja"], sid
        else:
            assert r["n_source_rows"] and r["n_source_rows"] > 0, sid
    assert {sid for sid, r in by.items() if r["tables"] != "[]"} == {
        sid for sid, e in doc["sources"].items() if "records" in e
    }


@needs_ryuiki
def test_real_declaration_mutations_stop():
    reg, targets, doc, counts, sup = _real()
    # (1) 行の無い表を records に足す
    d = copy.deepcopy(doc)
    d["sources"]["dams_kanagawa"]["records"] = ["sites", "protected_areas"]
    with pytest.raises(bsa.AccessError, match="1 つも無い"):
        bsa.assemble(reg, targets, d, counts, superseded_by=sup)
    # (2) 行のある出典に reason を付ける
    d = copy.deepcopy(doc)
    d["sources"]["dams_kanagawa"] = {"reason": "file_only", "basis": "x"}
    with pytest.raises(bsa.AccessError, match="原本に行がある"):
        bsa.assemble(reg, targets, d, counts, superseded_by=sup)
    # (3) 出典を 1 つ消す
    d = copy.deepcopy(doc)
    d["sources"].pop("ylist")
    with pytest.raises(bsa.AccessError, match="状態の無い出典"):
        bsa.assemble(reg, targets, d, counts, superseded_by=sup)
    # (4) 行が無いはずの not_in_d1 / 古い synthetic の宣言
    d = copy.deepcopy(doc)
    d["sources"]["ylist"] = {"reason": "not_in_d1", "basis": "x"}
    with pytest.raises(bsa.AccessError, match="原本に行が無い"):
        bsa.assemble(reg, targets, d, counts, superseded_by=sup)


def test_check_static_runs_without_ryuiki():
    bsa.check_static()  # 実際の access.yaml と manifests/ の静的検査（原本不要。--files-only が呼ぶ）


def test_record_tables_are_in_d1_schema():
    import re

    web_db = common.ROOT / "web" / "src" / "db"
    defined = set()
    for f in ("schema.ts", "schema-registry.ts"):
        defined |= set(re.findall(r'sqliteTable\(\s*"([a-z_0-9]+)"', (web_db / f).read_text(encoding="utf-8")))
    assert bsa.D1_RECORD_TABLES <= defined, sorted(bsa.D1_RECORD_TABLES - defined)
    assert set(bsa.load_access_yaml()["record_sets"].values()) <= bsa.D1_RECORD_TABLES


def test_record_set_rows_counts_only_that_record_set_table():
    """get_records の n_total は record_set の表の行数（その出典の分）。manifest の出現の表の合計を使わない。"""
    doc = _doc(a={"records": ["sites"]})
    rows = _build(_reg("a"), {}, doc, _counts(sites={"a": 3}, wildlife_sightings={"a": 99}))
    row = dict(zip(bsa.COLUMNS, rows[0]))
    assert json.loads(row["record_set_rows"]) == {"sites": 3}
    # 出現の表（manifest 側）と record_set の表が両方ある出典でも、record_set の分だけ
    doc = _doc(k={"records": ["sightings"]})
    rows = _build(_reg("k"), {"k": "occurrence"}, doc, _counts(wildlife_sightings={"k": 400}, organism_records={"k": 5}, edna_reads={"k": 7}))
    assert json.loads(dict(zip(bsa.COLUMNS, rows[0]))["record_set_rows"]) == {"sightings": 400}


def test_source_counts_fingerprint_detects_value_moving_between_sources(tmp_path, monkeypatch):
    """総数が同じでも、出典の値が移れば指紋が変わる（小さい表は出典別の件数、大きい表は行数・最大 rowid）。"""
    db = tmp_path / "ryuiki.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sites (site_id TEXT PRIMARY KEY, source_id TEXT)")
    conn.executemany("INSERT INTO sites VALUES (?, ?)", [("1", "a"), ("2", "a"), ("3", "b")])
    conn.commit()

    def fp():
        h = hashlib.sha256()
        common._hash_source_access_counts(h, db)
        return h.hexdigest()

    before = fp()
    conn.execute("UPDATE sites SET source_id='b' WHERE site_id='2'")
    conn.commit()
    assert fp() != before
    # 大きい表（しきい値超）は代理指標（行数・最大 rowid）。行の追加は拾う
    conn.execute("CREATE TABLE big (k INTEGER PRIMARY KEY, source_id TEXT)")
    conn.executemany("INSERT INTO big (source_id) VALUES (?)", [("a",)] * 5)
    conn.commit()
    monkeypatch.setattr(common, "_SOURCE_COUNTS_EXACT_MAX_ROWS", 2)
    b1 = fp()
    conn.execute("INSERT INTO big (source_id) VALUES ('a')")
    conn.commit()
    assert fp() != b1
    conn.close()
