"""scripts/r01_build_registry.py のビルド後チェック — region_id 不変条件
（ADR-0022 決定1）・place_relation の一意性 / 参照整合性のテスト。

いずれも「生成済みの registry.sqlite に対する検証」なので、本物の
`data/db/*.sqlite`（828MB/42MB/449MB）は要らない。`schema_registry.sql` から
空の registry.sqlite を作り、検証したい行だけを直接 INSERT して確かめる。
"""
import pytest

import r01_build_registry as r01
from registry import common


@pytest.fixture()
def empty_registry(tmp_path):
    conn = common.create_registry_db(tmp_path / "registry.sqlite")
    yield conn
    conn.close()


def _insert_place(conn, place_id, region_id):
    conn.execute(
        "INSERT INTO place (place_id, region_id, place_kind) VALUES (?, ?, 'site')",
        (place_id, region_id),
    )


def test_region_id_scope_invariant_passes_for_correct_rows(empty_registry):
    _insert_place(empty_registry, "common:place:watershed.x", None)
    _insert_place(empty_registry, "jp-14:place:site.y", "jp-14")
    empty_registry.commit()

    r01._assert_region_id_scope_invariant(empty_registry)  # 例外を投げなければOK


def test_region_id_scope_invariant_raises_for_common_scope_with_region(empty_registry):
    """common: スコープの place に region_id が入っている（旧実装の壊れ方。
    docs/plans/PHASE_B_INTAKE.md #4）行があれば止める。"""
    _insert_place(empty_registry, "common:place:watershed.x", "jp-14")
    empty_registry.commit()

    with pytest.raises(AssertionError, match="region_id が place_id のスコープと一致しない"):
        r01._assert_region_id_scope_invariant(empty_registry)


def test_region_id_scope_invariant_raises_for_region_scope_with_null(empty_registry):
    """地域スコープ（jp-14:等）なのに region_id が NULL の行も同様に止める。"""
    _insert_place(empty_registry, "jp-14:place:site.y", None)
    empty_registry.commit()

    with pytest.raises(AssertionError, match="region_id が place_id のスコープと一致しない"):
        r01._assert_region_id_scope_invariant(empty_registry)


def test_place_relation_uniqueness_passes_for_distinct_edges(empty_registry):
    empty_registry.executemany(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        [
            ("z1", "s1", "within", 1.0),
            ("z1", "s2", "within", 1.0),
        ],
    )
    empty_registry.commit()

    r01._assert_place_relation_uniqueness(empty_registry)  # 例外を投げなければOK


def test_place_relation_uniqueness_raises_for_duplicate_edge(empty_registry):
    empty_registry.executemany(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        [
            ("z1", "s1", "within", 1.0),
            ("z1", "s1", "within", 1.0),  # 完全な重複
        ],
    )
    empty_registry.commit()

    with pytest.raises(AssertionError, match="一意ではない"):
        r01._assert_place_relation_uniqueness(empty_registry)


def test_id_references_catches_dangling_place_relation_child(empty_registry):
    """place_relation.child_id -> place.place_id（本PRで r01.ID_REFERENCE_CHECKS に
    追加した2エントリのうちの1つ）。参照切れの辺を黙って通さない。"""
    _insert_place(empty_registry, "jp-14:place:zone.r2r-1", "jp-14")
    empty_registry.execute(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        ("jp-14:place:zone.r2r-1", "jp-14:place:site.missing", "within", 1.0),
    )
    empty_registry.commit()

    with pytest.raises(AssertionError, match="place_relation.child_id"):
        r01._assert_id_references(empty_registry)


def test_id_references_catches_dangling_place_relation_parent(empty_registry):
    """place_relation.parent_id -> place.place_id。"""
    _insert_place(empty_registry, "jp-14:place:site.s1", "jp-14")
    empty_registry.execute(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        ("jp-14:place:zone.missing", "jp-14:place:site.s1", "within", 1.0),
    )
    empty_registry.commit()

    with pytest.raises(AssertionError, match="place_relation.parent_id"):
        r01._assert_id_references(empty_registry)
