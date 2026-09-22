"""scripts/registry/build_taxon.py の F1（taxon_id の名前空間分割）・F2（分類補完と
taxon_group）のテスト（phase-b/occurrence-registry）。

本物の `data/db/*.sqlite`（828MB/42MB/449MB）を要さず、
scripts/tests/registry_fixtures.py の小さな自作 sqlite だけで完結する。
`registry/taxon/vernacular_ja.csv` と `registry/taxon/taxon_group.yaml` だけは実物を読む
（build_taxon.py が常にリポジトリのこのファイルを読む設計のため。どちらも手書きの正本であり
Git 管理下にあるので、`CLAUDE.md` の原本使用禁止の対象外）。`data/processed/taxon_crosswalk.csv`
は Git 管理外（.gitignore の `data/*`）なので、`build_taxon.CROSSWALK_CSV` を tmp_path の
空クロスウォークに差し替える（`monkeypatch`）。
"""
import sqlite3

import pytest

from registry import common
from registry.build_taxon import build as build_taxon
import registry.build_taxon as build_taxon_module

from .registry_fixtures import make_ryuiki_taxon_db, open_taxon_src


@pytest.fixture(autouse=True)
def _empty_crosswalk(monkeypatch, tmp_path):
    """CROSSWALK_CSV（Git管理外）を空のクロスウォークに差し替える。
    どのテストも `gbif_match_type='EXACT'` な taxa 行の `rank` は使わない
    （crosswalk_rank に無いキーは `_load_crosswalk_rank().get()` が None を返すだけで
    落ちない設計）ので、ヘッダ行だけのファイルで十分。
    """
    csv_path = tmp_path / "taxon_crosswalk.csv"
    csv_path.write_text("taxon_id,rank\n", encoding="utf-8")
    monkeypatch.setattr(build_taxon_module, "CROSSWALK_CSV", csv_path)


def _build(tmp_path, organism_records_rows=(), taxa_rows=()):
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    make_ryuiki_taxon_db(ryuiki_path, organism_records_rows, taxa_rows)

    registry_conn = common.create_registry_db(tmp_path / "registry.sqlite")
    registry_conn.row_factory = sqlite3.Row
    src = open_taxon_src(ryuiki_path)
    try:
        counts = build_taxon(registry_conn, src)
    finally:
        src["ryuiki"].close()
    return registry_conn, counts


def _taxon(conn, taxon_id):
    row = conn.execute("SELECT * FROM taxon WHERE taxon_id = ?", (taxon_id,)).fetchone()
    assert row is not None, f"{taxon_id} が taxon に無い"
    return dict(row)


# ---------------------------------------------------------------------------
# F1: taxon_id の名前空間分割
# ---------------------------------------------------------------------------


def test_gbif_and_inat_with_same_numeric_key_do_not_collide(tmp_path):
    """GBIF の taxonKey と iNaturalist の taxon.id がたまたま同じ数値でも、
    別の taxon_id（別の実体）として登録される（実データの9件衝突の回帰テスト）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "8026", "Axiidae", "FAMILY",
         "Animalia", "Arthropoda", "Malacostraca", None, "Axiidae", "2020-01-01"),
        ("inaturalist_kanagawa", "8026", "Corvus macrorhynchos", "species",
         None, None, None, None, None, "2020-01-02"),
    ]
    conn, counts = _build(tmp_path, organism_records_rows=rows)

    assert counts["taxon"] == 2
    gbif_row = _taxon(conn, "common:taxon:gbif.8026")
    inat_row = _taxon(conn, "common:taxon:inat.8026")
    assert gbif_row["scientific_name"] == "Axiidae"
    assert gbif_row["gbif_taxon_key"] == "8026"
    assert inat_row["scientific_name"] == "Corvus macrorhynchos"
    # iNat 由来行の gbif_taxon_key は常に NULL（本物の GBIF taxonKey ではないため）。
    assert inat_row["gbif_taxon_key"] is None


def test_unknown_source_id_raises(tmp_path):
    """SOURCE_NAMESPACE に無い source_id は黙って混ぜず例外で止める（F1）。"""
    rows = [
        ("some_new_source", "1", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
    ]
    with pytest.raises(ValueError, match="名前空間が未定義"):
        _build(tmp_path, organism_records_rows=rows)


def test_taxon_key_to_binomial_must_be_a_function(tmp_path):
    """出典内で同じ taxon_key に異なる二名法キー(binom)が付くと機械検証で止まる
    （F1機械検証。同じ数値キーが実は複数の実体を指している異常を示す）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "999", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "999", "Baz qux", "species", None, None, None, None, None, "2020-01-02"),
    ]
    with pytest.raises(AssertionError, match="二名法キーが関数でない"):
        _build(tmp_path, organism_records_rows=rows)


# ---------------------------------------------------------------------------
# F2: 分類補完(kingdom/phylum/class/taxon_group)
# ---------------------------------------------------------------------------


def test_own_classification_wins_over_majority(tmp_path):
    """出典自身が分類を持っていれば、それをそのまま使う（basis='source'）。"""
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Corvus corone", "species",
         "Animalia", "Chordata", "Aves", "Passeriformes", "Corvidae", "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["kingdom"] == "Animalia"
    assert t["phylum"] == "Chordata"
    assert t["class"] == "Aves"
    assert t["order"] == "Passeriformes"
    assert t["family"] == "Corvidae"
    assert t["classification_basis"] == "source"
    assert t["canonical_binomial"] == "Corvus corone"
    assert t["taxon_group"] == "鳥類"
    assert t["status"] == "accepted"


def test_binomial_majority_fills_missing_own_classification(tmp_path):
    """own class が無い記録(iNat 想定)は、同じ二名法キーの他記録の多数決で埋まる
    （basis='binomial_match'）。"""
    rows = [
        # GBIF側: 同じ binom で class を持つ記録（多数決の材料）。
        ("gbif_kanagawa_occurrences", "2", "Milvus migrans", "species",
         "Animalia", "Chordata", "Aves", "Accipitriformes", "Accipitridae", "2020-01-01"),
        # iNat側: 同じ binom・own class 無し（対象）。
        ("inaturalist_kanagawa", "500", "Milvus migrans", "species",
         None, None, None, None, None, "2020-02-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:inat.500")
    assert t["class"] == "Aves"
    assert t["kingdom"] == "Animalia"
    assert t["classification_basis"] == "binomial_match"
    assert t["status"] == "accepted"
    # order/family は多数決で補完しない(v1 も補完していない)。
    assert t["order"] is None
    assert t["family"] is None


def test_genus_majority_tie_marks_needs_review(tmp_path):
    """属単位の多数決が同数のとき、明示規則(件数降順、同数ならclass昇順)で
    決定論的に決め、その taxon を status='needs_review' にする。"""
    rows = [
        # 同じ属 Testgenus 内で class が1対1に割れる(tie)。
        ("gbif_kanagawa_occurrences", "10", "Testgenus aaa", "species",
         "Kingdom1", "PhylumX", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "11", "Testgenus bbb", "species",
         "Kingdom2", "PhylumY", "ClassB", None, None, "2020-01-02"),
        # 対象: own class 無し・binom 単位の多数決も無い(このbinomでclassを持つ記録が無い)。
        ("gbif_kanagawa_occurrences", "12", "Testgenus ccc", "species",
         None, None, None, None, None, "2020-01-03"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.12")
    assert t["classification_basis"] == "genus_match"
    assert t["class"] == "ClassA"  # 件数同数(1件ずつ)なので class 昇順で ClassA が勝つ
    assert t["status"] == "needs_review"

    # 明示的に own class を持つ taxon 自身は tie の影響を受けない。
    a = _taxon(conn, "common:taxon:gbif.10")
    assert a["classification_basis"] == "source"
    assert a["status"] == "accepted"


def test_unresolved_status_is_not_overridden_by_needs_review(tmp_path):
    """taxa 由来 unresolved (GBIF 未照合) 行は、分類の多数決が同数でも
    status='unresolved' のまま(needs_review に上書きしない。既存の意味を壊さないため)。
    """
    taxa_rows = [
        ("wamei:てすと", "Testgenus ddd", None, None, None,
         None, None, None, None, None),
    ]
    organism_rows = [
        ("gbif_kanagawa_occurrences", "10", "Testgenus aaa", "species",
         "Kingdom1", "PhylumX", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "11", "Testgenus bbb", "species",
         "Kingdom2", "PhylumY", "ClassB", None, None, "2020-01-02"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=organism_rows, taxa_rows=taxa_rows)
    t = _taxon(conn, "common:taxon:ryuiki-taxa.wamei.%E3%81%A6%E3%81%99%E3%81%A8")
    assert t["status"] == "unresolved"
    assert t["classification_basis"] == "genus_match"


def test_taxon_group_default_is_unclassified(tmp_path):
    """taxon_group.yaml のどのルールにも一致しない場合は default_label_ja('未判定')。"""
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Mysterium unknownii", "species",
         "Chromista", "Foraminifera", "Foraminiferea", None, None, "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["taxon_group"] == "未判定"


def test_taxon_group_first_match_wins_over_later_rule(tmp_path):
    """class='Aves' は kingdom='Animalia' のルール(その他無脊椎動物)より先に
    一致するので、先勝ちで「鳥類」になる(taxon_group.yaml の順序を保つことの回帰)。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Corvus corone", "species",
         "Animalia", "Chordata", "Aves", None, None, "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["taxon_group"] == "鳥類"
