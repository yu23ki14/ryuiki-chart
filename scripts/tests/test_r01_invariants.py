"""scripts/r01_build_registry.py のビルド後チェック — region_id 不変条件
（ADR-0022 決定1）・place_relation の一意性 / 参照整合性・ゾーン関連の不変条件
（地点→ゾーンの辺の単射性・ゾーン番号の数値形式・`place_source_ref(place_id,
source_id)` の一意性。Phase B `phase-b/zone-slice` のコードレビュー対応で
`b05_project_v1.py` から移設）のテスト。

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


def test_region_id_scope_invariant_raises_for_malformed_place_id(empty_registry):
    """place_id に ':' が無い壊れた行は common.scope_of() が ValueError を投げる
    （common.region_id_for_scoped_id() をそのまま使うようになったので、以前のように
    ID 全体をスコープ扱いして黙って通すことはない）。"""
    _insert_place(empty_registry, "malformed-place-id-without-colon", None)
    empty_registry.commit()

    with pytest.raises(ValueError, match="scoped_id の形が想定外"):
        r01._assert_region_id_scope_invariant(empty_registry)


def test_place_relation_uniqueness_passes_for_distinct_edges(empty_registry):
    """place_relation の複合キー一意性は ID_UNIQUENESS_CHECKS / _assert_id_uniqueness
    に統合済み（専用関数 _assert_place_relation_uniqueness は無い）。他のテーブルは
    空のままなので distinct と total が両方 0 で一致し、trivially に通る。"""
    empty_registry.executemany(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        [
            ("z1", "s1", "within", 1.0),
            ("z1", "s2", "within", 1.0),
        ],
    )
    empty_registry.commit()

    r01._assert_id_uniqueness(empty_registry)  # 例外を投げなければOK


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
        r01._assert_id_uniqueness(empty_registry)


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


# ---------------------------------------------------------------------------
# ゾーン関連の不変条件（phase-b/zone-slice のコードレビュー対応。b05 から移設）
# ---------------------------------------------------------------------------

def _insert_place_source_ref(conn, place_id, external_key, source_id):
    conn.execute(
        "INSERT INTO place_source_ref (place_id, external_key, source_id) VALUES (?, ?, ?)",
        (place_id, external_key, source_id),
    )


def _insert_place_relation(conn, parent_id, child_id, relation="within", fraction=1.0):
    conn.execute(
        "INSERT INTO place_relation (parent_id, child_id, relation, fraction) VALUES (?,?,?,?)",
        (parent_id, child_id, relation, fraction),
    )


def test_zone_relation_child_is_single_valued_passes_for_single_zone_edge(empty_registry):
    _insert_place_source_ref(empty_registry, "zone1", "1", "sites.zone")
    _insert_place_relation(empty_registry, "zone1", "s1")
    empty_registry.commit()

    r01._assert_zone_relation_child_is_single_valued(empty_registry)  # 例外を投げなければOK


def test_zone_relation_child_is_single_valued_raises_for_two_zone_edges(empty_registry):
    """同じ地点(child_id)が2つのゾーン(parent_id)への 'within' 辺を持っていれば
    止める（v1 の sites.zone は単一列なので、地点は必ず1つのゾーンにしか属さない）。
    """
    _insert_place_source_ref(empty_registry, "zone1", "1", "sites.zone")
    _insert_place_source_ref(empty_registry, "zone2", "2", "sites.zone")
    _insert_place_relation(empty_registry, "zone1", "s1")
    _insert_place_relation(empty_registry, "zone2", "s1")  # 同じ地点が2つ目のゾーンにも
    empty_registry.commit()

    with pytest.raises(AssertionError, match="複数持っている"):
        r01._assert_zone_relation_child_is_single_valued(empty_registry)


def test_zone_relation_child_is_single_valued_ignores_non_zone_within_edges(empty_registry):
    """ゾーン以外の 'within' 辺（parent が sites.zone の place_source_ref を
    持たない。例: 地点→流域）は対象外——地点がゾーンへの辺1本と、それ以外への
    辺を両方持っていても、ゾーンの辺自体が1本なら通る。
    """
    _insert_place_source_ref(empty_registry, "zone1", "1", "sites.zone")
    _insert_place_relation(empty_registry, "zone1", "s1")
    _insert_place_relation(empty_registry, "watershed1", "s1")  # ゾーンではない
    empty_registry.commit()

    r01._assert_zone_relation_child_is_single_valued(empty_registry)  # 例外を投げなければOK


def test_zone_external_key_is_numeric_passes_for_digit_strings(empty_registry):
    _insert_place_source_ref(empty_registry, "zone1", "1", "sites.zone")
    _insert_place_source_ref(empty_registry, "zone2", "12", "sites.zone")
    empty_registry.commit()

    r01._assert_zone_external_key_is_numeric(empty_registry)  # 例外を投げなければOK


def test_zone_external_key_is_numeric_raises_for_non_digit_string(empty_registry):
    """`CAST(... AS INT)`（b05_project_v1.py）が非数値文字列を黙って0にするのを
    防ぐための検証。"""
    _insert_place_source_ref(empty_registry, "zone1", "z1", "sites.zone")
    empty_registry.commit()

    with pytest.raises(AssertionError, match="数字だけの文字列でない"):
        r01._assert_zone_external_key_is_numeric(empty_registry)


def test_place_source_ref_uniqueness_passes_for_distinct_place_source_pairs(empty_registry):
    """ID_UNIQUENESS_CHECKS に追加した (place_id, source_id) の一意性。同じ
    place_id でも source_id が違えば別の対応（例: 地点は sites.site_id・
    sites.zone の両方の出典に現れうる）なので重複ではない。"""
    _insert_place_source_ref(empty_registry, "s1", "S1", "sites.site_id")
    _insert_place_source_ref(empty_registry, "s1", "1", "sites.zone")
    empty_registry.commit()

    r01._assert_id_uniqueness(empty_registry)  # 例外を投げなければOK


def test_place_source_ref_uniqueness_raises_for_duplicate_place_source_pair(empty_registry):
    _insert_place_source_ref(empty_registry, "s1", "S1", "sites.site_id")
    _insert_place_source_ref(empty_registry, "s1", "S1_dup", "sites.site_id")  # 同じ (place_id, source_id)
    empty_registry.commit()

    with pytest.raises(AssertionError, match="一意ではない"):
        r01._assert_id_uniqueness(empty_registry)
