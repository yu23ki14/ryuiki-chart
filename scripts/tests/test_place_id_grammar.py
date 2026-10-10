"""place の ID 文法（ADR-0004 規約1 改定）・`parse_id()`・`registry/id_map/place.csv` の
検査のテスト（Issue #39 Phase C 担当 A）。

実データの検査（`data/db/registry.sqlite` が要るもの）は、無ければ skip する
（CI の `registry` ジョブは `--files-only` で place を持たないため）。
"""
import copy
import sqlite3

import pytest

from registry import common, id_map

# ---------------------------------------------------------------------------
# place_id() / parse_id()
# ---------------------------------------------------------------------------


def test_place_id_uses_dot_between_namespace_and_key():
    assert common.place_id("site", "env-pubwater", "0142", scope="jp-14") == "jp-14:place:site.env-pubwater.0142"
    assert common.place_id("watershed", "nlni", "83030-0001") == "common:place:watershed.nlni.83030-0001"
    assert common.place_id("zone", "r2r", "3", scope="jp-14") == "jp-14:place:zone.r2r.3"
    assert common.place_id("grid01", None, "3520_13900") == "common:place:grid01.3520_13900"


@pytest.mark.parametrize("ns", ["a.b", "a:b", "A", "", None])
def test_place_id_rejects_namespace_with_dot_or_colon_or_missing(ns):
    """ns に '.' を入れる・ns を省くと止まる（最初の '.' で切る規則が壊れるため）。"""
    with pytest.raises(ValueError):
        common.place_id("site", ns, "x", scope="jp-14")


def test_place_id_rejects_namespace_for_grid01():
    with pytest.raises(ValueError):
        common.place_id("grid01", "oops", "3520_13900")


@pytest.mark.parametrize(
    "pid,kind,ns,key",
    [
        ("jp-14:place:site.env-pubwater.0142", "site", "env-pubwater", "0142"),
        ("jp-14:place:site.atsugi-river.%E7%8E%89%E5%B7%9D", "site", "atsugi-river", "%E7%8E%89%E5%B7%9D"),
        ("common:place:watershed.nlni.83030-0001", "watershed", "nlni", "83030-0001"),
        ("jp-14:place:zone.r2r.3", "zone", "r2r", "3"),
        ("common:place:grid01.3520_13900", "grid01", None, "3520_13900"),
        # key が '.' を含んでも最初の '.' で切るので ns は変わらない
        ("jp-14:place:site.jma.a.b.c", "site", "jma", "a.b.c"),
    ],
)
def test_parse_id_place(pid, kind, ns, key):
    p = common.parse_id(pid)
    assert (p.entity, p.kind, p.ns, p.key) == ("place", kind, ns, key)
    assert p.scope == pid.split(":")[0]


def test_parse_id_non_place_entities_are_unchanged():
    p = common.parse_id("common:taxon:gbif.123")
    assert (p.scope, p.entity, p.ns, p.key) == ("common", "taxon", "gbif", "123")
    p = common.parse_id("common:taxon:ryuiki-taxa.abc")
    assert (p.ns, p.key) == ("ryuiki-taxa", "abc")
    p = common.parse_id("common:variable:water.bod")
    assert (p.ns, p.key) == ("water", "bod")


@pytest.mark.parametrize(
    "bad",
    [
        "jp-14:place:site.jma-jma_0387",  # 旧形式（'-' 区切り）は新文法では分解できない
        "common:place:watershed.nlni-83030-0001",
        "jp-14:place:zone.r2r-3",
        "no-colon",
        "a:b",
        "common:place:",
    ],
)
def test_parse_id_rejects_legacy_and_malformed(bad):
    """区切りを '-' に戻した ID を黙って誤分割しない（止まる）。"""
    with pytest.raises(ValueError):
        common.parse_id(bad)


# ---------------------------------------------------------------------------
# id_map の検査（わざと壊すと止まる）
# ---------------------------------------------------------------------------

_REASON = "r"
_SPEC = "s"


def _rows(*pairs):
    return [{"old_id": o, "new_id": n, "reason": _REASON, "spec_version": _SPEC} for o, n in pairs]


_GOOD_PAIRS = [
    ("common:place:watershed.nlni-83030-0001", "common:place:watershed.nlni.83030-0001"),
    ("jp-14:place:site.jma-jma_0387", "jp-14:place:site.jma.jma_0387"),
    ("jp-14:place:zone.r2r-3", "jp-14:place:zone.r2r.3"),
]
_PLACE_IDS = {n for _, n in _GOOD_PAIRS} | {"common:place:grid01.3520_13900"}


def test_verify_place_id_map_passes_for_consistent_declaration():
    id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), set(_PLACE_IDS))


def test_verify_place_id_map_halts_when_a_declaration_row_is_removed():
    with pytest.raises(AssertionError, match="宣言されていない"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS[:-1]), set(_PLACE_IDS))


def test_verify_place_id_map_halts_when_old_id_is_reused_as_a_live_id():
    """旧 ID を現行の別の place の ID として発行すると止まる（再利用しない）。"""
    live = set(_PLACE_IDS) | {_GOOD_PAIRS[0][0]}
    with pytest.raises(AssertionError, match="再利用しない"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), live)


def test_verify_place_id_map_halts_on_duplicate_old_id():
    dup_old = _GOOD_PAIRS + [(_GOOD_PAIRS[0][0], "common:place:watershed.nlni.99999-0001")]
    with pytest.raises(AssertionError, match="old_id が重複"):
        id_map.verify_place_id_map(_rows(*dup_old), _PLACE_IDS | {"common:place:watershed.nlni.99999-0001"})


def test_verify_place_id_map_allows_declared_places_absent_from_a_reduced_sample():
    """縮小サンプルのように現行の place が宣言より少なくても、宣言の new_id が規則から導ければ通る
    （CI の sample-gate。現行の place は全部宣言されている必要があるが、逆は要求しない）。"""
    id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), _PLACE_IDS - {_GOOD_PAIRS[0][1]})


def test_verify_place_id_map_halts_when_a_live_renamed_place_is_not_declared():
    with pytest.raises(AssertionError, match="宣言されていない"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS[1:]), set(_PLACE_IDS))


def test_verify_place_id_map_halts_when_new_id_is_not_derivable_even_if_absent_from_places():
    with pytest.raises(AssertionError, match="分解できない"):
        id_map.verify_place_id_map(_rows(("jp-14:place:site.x-1", "jp-14:place:site.x-1")), set(_PLACE_IDS))


def test_verify_place_id_map_halts_when_old_id_drifts_from_the_rule():
    pairs = copy.deepcopy(_GOOD_PAIRS)
    pairs[1] = ("jp-14:place:site.jma_jma_0387", pairs[1][1])  # 規則から外れた旧 ID
    with pytest.raises(AssertionError, match="規則"):
        id_map.verify_place_id_map(_rows(*pairs), set(_PLACE_IDS))


# ---------------------------------------------------------------------------
# 実データ（registry.sqlite があるときだけ）
# ---------------------------------------------------------------------------


def _real_registry():
    path = common.REGISTRY_DB
    if not path.exists():
        pytest.skip("data/db/registry.sqlite が無い")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='id_map'").fetchone():
        pytest.skip("registry.sqlite が古い（id_map 表が無い。r01 を回す）")
    return conn


def test_real_place_ids_round_trip_through_parse_id():
    """全 place（4,964件）が parse_id() で分解でき、place_id() で同じ ID に戻る。"""
    conn = _real_registry()
    try:
        ids = [r[0] for r in conn.execute("SELECT place_id FROM place")]
    finally:
        conn.close()
    assert len(ids) > 4000
    for pid in ids:
        p = common.parse_id(pid)
        assert p.entity == "place"
        rebuilt = common.scoped_id("place", f"{p.kind}.{p.ns + '.' if p.ns else ''}{p.key}", p.scope)
        assert rebuilt == pid


def test_real_id_map_resolves_every_legacy_place_id_to_exactly_one_current_id():
    conn = _real_registry()
    try:
        ids = {r[0] for r in conn.execute("SELECT place_id FROM place")}
        m = conn.execute("SELECT old_id, new_id FROM id_map WHERE entity='place'").fetchall()
    finally:
        conn.close()
    assert len(m) == 882  # site 495 + watershed 377 + zone 5 + zone の昇格前 ID 5（AMAMI_STEP0 §2）
    assert len({o for o, _ in m}) == len(m)
    assert all(n in ids and o not in ids for o, n in m)


# ---------------------------------------------------------------------------
# zone の common 昇格（AMAMI_STEP0 §2、ADR-0004 追記）
# ---------------------------------------------------------------------------

_ZONE_NEW = "common:place:zone.r2r.3"
_PROMOTED_PAIRS = [
    ("jp-14:place:zone.r2r-3", _ZONE_NEW),   # 区切り改定前の旧 ID
    ("jp-14:place:zone.r2r.3", _ZONE_NEW),   # 改定後・昇格前の ID
]


def test_verify_place_id_map_accepts_zone_promoted_to_common_with_two_old_ids():
    id_map.verify_place_id_map(_rows(*_PROMOTED_PAIRS), {_ZONE_NEW})


def test_verify_place_id_map_halts_when_old_scope_is_not_a_declared_promotion():
    """scope が違うのは PROMOTED_FROM に宣言した（kind, 旧 scope）だけ。jp-46 の zone は昇格前に存在しない。"""
    pairs = _PROMOTED_PAIRS + [("jp-46:place:zone.r2r.3", _ZONE_NEW)]
    with pytest.raises(AssertionError, match="昇格前の scope"):
        id_map.verify_place_id_map(_rows(*pairs), {_ZONE_NEW})
    with pytest.raises(AssertionError, match="昇格前の scope"):   # kind が違えば jp-14 → common でも通さない
        id_map.verify_place_id_map(_rows(("jp-14:place:site.jma-s1", "common:place:site.jma.s1")), set())


def test_verify_place_id_map_halts_when_promoted_zone_old_id_drifts():
    pairs = [("jp-14:place:zone.r2r_3", _ZONE_NEW)]
    with pytest.raises(AssertionError, match="規則"):
        id_map.verify_place_id_map(_rows(*pairs), {_ZONE_NEW})


def test_verify_place_id_map_halts_when_a_row_is_not_a_rename():
    new = "jp-14:place:site.jma.s1"
    with pytest.raises(AssertionError, match="改称になっていない"):
        id_map.verify_place_id_map(_rows((new, new)), {new})


def test_verify_place_id_map_allows_many_old_ids_for_one_new_id():
    """new_id の重複は上限なし（old_id の一意性だけを守る）。"""
    pairs = _PROMOTED_PAIRS + [("jp-14:place:zone.r2r3", _ZONE_NEW)]
    id_map.verify_place_id_map(_rows(*pairs), {_ZONE_NEW})


def test_real_place_csv_resolves_both_old_zone_ids_to_common():
    rows = id_map.load_csv("place")
    got = {r["old_id"]: r["new_id"] for r in rows if ":zone." in r["old_id"]}
    for n in range(1, 6):
        assert got[f"jp-14:place:zone.r2r-{n}"] == f"common:place:zone.r2r.{n}"
        assert got[f"jp-14:place:zone.r2r.{n}"] == f"common:place:zone.r2r.{n}"
    assert len(got) == 10


# 網羅の検査は「改定時に存在した出典」の place だけ。出典は new_id が指す place の出典から導く。
_SRC = {
    "common:place:watershed.nlni.83030-0001": {"nlni_w12_watersheds"},
    "jp-14:place:site.jma.jma_0387": {"jma_stations_kanagawa"},
}
_NEW_SITE = "jp-46:place:site.jma.amami_1"


def test_verify_place_id_map_ignores_undeclared_place_of_a_source_born_after_the_rename():
    src = {**_SRC, _NEW_SITE: {"jma_stations_amami"}}
    id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), _PLACE_IDS | {_NEW_SITE}, src)


def test_verify_place_id_map_halts_on_undeclared_place_of_a_source_that_existed_at_the_rename():
    src = {**_SRC, _NEW_SITE: {"jma_stations_kanagawa"}}   # 改定時の出典から出た place の宣言漏れ
    with pytest.raises(AssertionError, match="宣言されていない"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), _PLACE_IDS | {_NEW_SITE}, src)


def test_verify_place_id_map_still_requires_declaration_when_source_is_unknown():
    with pytest.raises(AssertionError, match="宣言されていない"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), _PLACE_IDS | {_NEW_SITE}, _SRC)


def test_sources_at_rename_is_a_fixed_declaration_not_derived_from_id_map():
    """改定時の出典は定数。place.csv の行を消しても免除は広がらない（自己依存の排除）。"""
    assert "jma_stations_kanagawa" in id_map.SOURCES_AT_RENAME
    assert not any("amami" in s for s in id_map.SOURCES_AT_RENAME)


def test_verify_place_id_map_halts_when_all_rows_of_a_source_at_rename_are_removed():
    """変異: 改定時の出典（jma_stations_kanagawa）の行を全部消すと、その place の宣言漏れで止まる
    （id_map から出典を導いていた頃は、行を消すと免除が広がって通ってしまった）。"""
    rows = [p for p in _GOOD_PAIRS if "jma" not in p[1]]
    with pytest.raises(AssertionError, match="宣言されていない"):
        id_map.verify_place_id_map(_rows(*rows), set(_PLACE_IDS), _SRC)


def test_verify_place_id_map_halts_when_place_csv_declares_a_source_born_after_the_rename():
    src = {**_SRC, "jp-14:place:site.jma.jma_0387": {"jma_stations_kanagawa", "jma_stations_amami"}}
    with pytest.raises(AssertionError, match="改定後にできた出典"):
        id_map.verify_place_id_map(_rows(*_GOOD_PAIRS), set(_PLACE_IDS), src)
