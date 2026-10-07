"""build_taxon の補完 taxon（`registry/taxon/supplement_taxa.csv`。ADR-0019 2026-10-07 追記）。

小さな自作 sqlite（registry_fixtures）だけで完結する。クロスウォーク・GBIF 受理名は空に差し替える。
"""
import sqlite3

import pytest

import registry.build_taxon as bt
from registry import common
from registry.build_taxon import build as build_taxon

from .registry_fixtures import make_ryuiki_taxon_db, open_taxon_src

_ACCEPTED_HEADER = (
    "taxon_id,scientific_name,gbif_key,match_type,status,accepted_key,accepted_canonical_name,"
    "accepted_basis,weak_resolution,weak_reason,weak_key,weak_rank,weak_status,fetched_at"
)
_SUP_HEADER = ",".join(bt.SUPPLEMENT_COLUMNS)

_GBIF_SUP = {
    "taxon_id": "common:taxon:gbif.999001", "scientific_name": "Foo bar Linnaeus 1758",
    "canonical_binomial": "Foo bar", "rank": "species", "kingdom": "Animalia", "phylum": "Chordata",
    "class": "Actinopterygii", "vernacular_name_ja": "フーバー", "gbif_taxon_key": "999001",
    "basis": "gbif_match", "evidence": "GBIF match EXACT",
}
_NAME_SUP = {
    "taxon_id": f"common:taxon:kanagawa-edna.{common.slugify_local_key('カワゲラ類')}", "rank": "order", "kingdom": "Animalia",
    "phylum": "Arthropoda", "class": "Insecta", "order": "Plecoptera", "vernacular_name_ja": "カワゲラ類",
    "basis": "name_only", "evidence": "シートに和名のみ",
}


@pytest.fixture(autouse=True)
def _stubs(monkeypatch, tmp_path):
    cw = tmp_path / "taxon_crosswalk.csv"
    cw.write_text("taxon_id,rank\n", encoding="utf-8")
    monkeypatch.setattr(bt, "CROSSWALK_CSV", cw)
    acc = tmp_path / "taxon_gbif_accepted.csv"
    acc.write_text(_ACCEPTED_HEADER + "\n", encoding="utf-8")
    monkeypatch.setattr(bt, "GBIF_ACCEPTED_CSV", acc)


def _write_supplement(tmp_path, monkeypatch, rows):
    lines = [_SUP_HEADER] + [",".join(str(r.get(c, "")) for c in bt.SUPPLEMENT_COLUMNS) for r in rows]
    path = tmp_path / "supplement_taxa.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(bt, "SUPPLEMENT_TAXA_CSV", path)


_BASE_ROW = ("gbif_kanagawa_occurrences", "1001", "Base taxon", "species",
             "Animalia", "Arthropoda", "Insecta", None, None, "2020-01-01")


def _build(tmp_path, organism_records_rows=(_BASE_ROW,)):
    """organism_records が 0 行だと既存の診断出力が 0 除算するので、無関係な 1 行を既定で置く。"""
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    make_ryuiki_taxon_db(ryuiki_path, organism_records_rows, ())
    conn = common.create_registry_db(tmp_path / "registry.sqlite")
    conn.row_factory = sqlite3.Row
    src = open_taxon_src(ryuiki_path)
    try:
        counts = build_taxon(conn, src)
    finally:
        src["ryuiki"].close()
    return conn, counts


def _taxon(conn, taxon_id):
    row = conn.execute("SELECT * FROM taxon WHERE taxon_id = ?", (taxon_id,)).fetchone()
    assert row is not None
    return dict(row)


def test_shipped_supplement_loads_and_passes_validation():
    """同梱の CSV は期待どおりのヘッダで、中身は検査を通る（件数は固定しない）。"""
    header = bt.SUPPLEMENT_TAXA_CSV.read_text(encoding="utf-8").splitlines()[0]
    assert header == _SUP_HEADER
    bt._load_supplement_taxa()


def test_empty_supplement_adds_nothing(tmp_path, monkeypatch):
    _write_supplement(tmp_path, monkeypatch, [])
    _, counts = _build(tmp_path)
    assert counts["taxon"] == 1  # 基底の 1 行だけ


def test_rows_added_with_status_and_basis(tmp_path, monkeypatch):
    _write_supplement(tmp_path, monkeypatch, [_GBIF_SUP, _NAME_SUP])
    conn, counts = _build(tmp_path)
    assert counts["taxon"] == 3  # 基底 1 + 補完 2
    g = _taxon(conn, "common:taxon:gbif.999001")
    assert g["status"] == "accepted" and g["gbif_taxon_key"] == "999001"
    assert g["vernacular_ja_basis"] == "supplement" and g["classification_basis"] == "supplement"
    assert g["canonical_binomial"] == "Foo bar" and g["class"] == "Actinopterygii"
    n = _taxon(conn, _NAME_SUP["taxon_id"])
    assert n["status"] == "unresolved" and n["scientific_name"] is None and n["gbif_taxon_key"] is None
    assert n["vernacular_name_ja"] == "カワゲラ類" and n["order"] == "Plecoptera"


_EXISTING_ROW = ("gbif_kanagawa_occurrences", "999001", "Foo bar", "species",
                 "Animalia", "Chordata", "Actinopterygii", None, None, "2020-01-01")


def test_gbif_match_duplicate_of_existing_taxon_is_dropped(tmp_path, monkeypatch):
    """記録側に同じ GBIF キーが現れても落ちない。既存の行が勝ち、補完は捨てる。"""
    _write_supplement(tmp_path, monkeypatch, [_GBIF_SUP])
    conn, counts = _build(tmp_path, organism_records_rows=(_BASE_ROW, _EXISTING_ROW))
    assert counts["taxon"] == 2
    assert _taxon(conn, "common:taxon:gbif.999001")["vernacular_ja_basis"] != "supplement"


def test_name_only_collision_with_existing_taxon_stops(tmp_path, monkeypatch):
    # gbif 側に同じ ID は作れないので、既存 taxa 由来の ryuiki-taxa と同じ slug を別の名前空間で…は衝突しない。
    # name_only 同士は assert_unique が止める（上の重複テスト）。ここでは名前空間の予約を確かめる。
    _write_supplement(tmp_path, monkeypatch, [{**_NAME_SUP, "taxon_id": "common:taxon:gbif.abc"}])
    with pytest.raises(ValueError, match="名前空間"):
        _build(tmp_path)


@pytest.mark.parametrize("patch", [
    {"taxon_id": "common:taxon:other.1"},   # 不正な ID
    {"basis": "guess"},                      # 未知の basis
    {"gbif_taxon_key": "999002"},            # ID と gbif_taxon_key の不一致
    {"rank": ""},
    {"evidence": ""},
    {"canonical_binomial": "Other name"},    # scientific_name の二名法と食い違う
])
def test_invalid_gbif_match_row_stops(tmp_path, monkeypatch, patch):
    _write_supplement(tmp_path, monkeypatch, [{**_GBIF_SUP, **patch}])
    with pytest.raises(ValueError):
        _build(tmp_path)


@pytest.mark.parametrize("patch", [
    {"scientific_name": "Plecoptera sp."},                 # 学名の捏造
    {"gbif_taxon_key": "1"},
    {"taxon_id": "common:taxon:kanagawa-edna.a b"},        # slug を通していない（空白入り）
    {"taxon_id": "common:taxon:kanagawa-edna.カワゲラ類"},   # slug を通していない（生の日本語）
    {"taxon_id": "common:taxon:Bad_NS.x"},                 # 名前空間が不正
    {"vernacular_name_ja": ""},
])
def test_invalid_name_only_row_stops(tmp_path, monkeypatch, patch):
    _write_supplement(tmp_path, monkeypatch, [{**_NAME_SUP, **patch}])
    with pytest.raises(ValueError):
        _build(tmp_path)


def test_duplicate_id_stops(tmp_path, monkeypatch):
    _write_supplement(tmp_path, monkeypatch, [_NAME_SUP, _NAME_SUP])
    with pytest.raises(AssertionError, match="重複"):
        _build(tmp_path)


def test_bad_header_stops(tmp_path, monkeypatch):
    bad = tmp_path / "bad.csv"
    bad.write_text("taxon_id,x\n", encoding="utf-8")
    monkeypatch.setattr(bt, "SUPPLEMENT_TAXA_CSV", bad)
    with pytest.raises(ValueError):
        _build(tmp_path)
