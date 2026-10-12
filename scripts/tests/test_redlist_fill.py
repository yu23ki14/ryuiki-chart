"""scripts/migrate/redlist_fill.py（b06 が出典の付けなかった記録に赤リスト判定を補う）のテスト。

県版は registry の taxon_assessment、全国版は ryuiki.taxa を、小さな自作 sqlite で再現する。
"""
import sqlite3

import pytest

from migrate import redlist_fill
from migrate.redlist_fill import RedListResolver, bare_name

from .occurrence_fixtures import make_occurrence_registry_db

_COLS = ("assessment_id", "list_id", "list_year", "taxon_id", "scientific_name_raw", "vernacular_name_ja_raw",
         "vernacular_name_ja_resolved", "taxon_group_ja", "taxon_subgroup_ja", "family_ja", "category_raw", "category_code")


def _row(aid, list_id, year, name, cat, code):
    return (aid, list_id, year, None, name, None, None, None, None, None, cat, code)


ASSESSMENTS = [
    # 鹿児島 (jp-46): 亜種だけ載る種・種と亜種の両方が載る種・種だけ載る種・同じ種の亜種が2つ
    _row("kg_1", "kgrl2014", 2014, "Dendrocopos leucotos owstoni", "絶滅危惧Ⅰ類", "CR+EN"),
    _row("kg_2", "kgrl2014", 2014, "Columba janthina janthina", "準絶滅危惧", "NT"),
    _row("kg_3", "kgrl2014", 2014, "Garrulus lidthi", "絶滅危惧Ⅱ類", "VU"),
    _row("kg_4", "kgrl2014", 2014, "Both species", "準絶滅危惧", "NT"),
    _row("kg_5", "kgrl2014", 2014, "Both species bsub", "絶滅危惧Ⅰ類", "CR+EN"),
    _row("kg_6", "kgrl2014", 2014, "Two subs asub", "準絶滅危惧", "NT"),
    _row("kg_7", "kgrl2014", 2014, "Two subs zsub", "絶滅危惧Ⅱ類", "VU"),
    # 条例の指定種は赤リストではない
    _row("kgo_1", "kgord", 2026, "Ordinance only", "指定", None),
    # 神奈川 (jp-14)
    _row("kn_1", "rl2020", 2020, "Kanagawa plant var. vv", "絶滅危惧Ⅱ類", "VU"),
]
# 実際の taxon_assessment と同じく、亜種・変種の掲載名の先頭2語が種


def _build(tmp_path, national):
    reg = tmp_path / "registry.sqlite"
    make_occurrence_registry_db(reg, taxa=[], places=[], place_refs=[], taxon_assessments=ASSESSMENTS)
    src = tmp_path / "ryuiki.sqlite"
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE taxa (taxon_id TEXT PRIMARY KEY, redlist_national TEXT)")
    c.executemany("INSERT INTO taxa VALUES (?, ?)", national)
    c.commit()
    c.close()
    work = sqlite3.connect(":memory:")
    work.execute("ATTACH ? AS reg", (str(reg),))
    work.execute("ATTACH ? AS src", (str(src),))
    return RedListResolver(work)


@pytest.fixture
def resolver(tmp_path):
    return _build(tmp_path, [
        ("garrulus lidthi", "絶滅危惧Ⅱ類（VU）"),
        ("passer montanus", "準絶滅危惧（NT）"),
        ("dendrocopos leucotos owstoni", "絶滅危惧Ⅱ類（VU）"),   # 全国版の亜種掲載（種の記録は該当にしない）
        ("wamei:abc", "絶滅危惧Ⅰ類（CR+EN）"),
    ])


def test_species_exact_prefecture_hit(resolver):
    assert resolver.resolve("jp-46", "Garrulus lidthi") == ("絶滅危惧Ⅱ類（VU）", "kgrl2014", "pref_exact")


def test_prefecture_wins_over_national(tmp_path):
    r = _build(tmp_path, [("garrulus lidthi", "準絶滅危惧（NT）")])
    assert r.resolve("jp-46", "Garrulus lidthi")[:2] == ("絶滅危惧Ⅱ類（VU）", "kgrl2014")


def test_national_species_exact(resolver):
    assert resolver.resolve("jp-46", "Passer montanus") == ("準絶滅危惧（NT）", "national", "national_exact")
    assert resolver.resolve("jp-14", "Passer montanus")[1] == "national"


def test_subspecies_listed_in_same_region_makes_species_record_a_hit_with_marker(resolver):
    assert resolver.resolve("jp-46", "Dendrocopos leucotos") == (
        "絶滅危惧Ⅰ類（CR+EN）", "kgrl2014+subspecies:Dendrocopos leucotos owstoni", "subspecies")
    assert resolver.resolve("jp-46", "Columba janthina") == (
        "準絶滅危惧（NT）", "kgrl2014+subspecies:Columba janthina janthina", "subspecies")


def test_subspecies_listing_in_another_region_is_not_a_hit(resolver):
    assert resolver.resolve("jp-14", "Dendrocopos leucotos") is None
    assert resolver.resolve("jp-14", "Columba janthina") is None


def test_national_subspecies_listing_does_not_make_species_record_a_hit(resolver):
    # 全国版に owstoni があっても、地域が決められないので種の記録は該当にしない（jp-14 でも jp-46 の県版でない地域）
    assert resolver.resolve("jp-14", "Dendrocopos leucotos") is None


def test_subspecies_record_matches_its_own_listing_exactly(resolver):
    assert resolver.resolve("jp-46", "Dendrocopos leucotos owstoni") == ("絶滅危惧Ⅰ類（CR+EN）", "kgrl2014", "pref_exact")
    # 掲載のない別の亜種の記録は、種の掲載を借りない
    assert resolver.resolve("jp-46", "Dendrocopos leucotos other") is None


def test_species_level_listing_wins_over_subspecies(resolver):
    assert resolver.resolve("jp-46", "Both species") == ("準絶滅危惧（NT）", "kgrl2014", "pref_exact")


def test_several_subspecies_pick_the_most_severe_deterministically(resolver):
    assert resolver.resolve("jp-46", "Two subs") == (
        "絶滅危惧Ⅱ類（VU）", "kgrl2014+subspecies:Two subs zsub", "subspecies")


def test_designated_ordinance_list_is_not_a_red_list(resolver):
    assert resolver.resolve("jp-46", "Ordinance only") is None


def test_variety_in_kanagawa_list(resolver):
    assert resolver.resolve("jp-14", "Kanagawa plant") == (
        "絶滅危惧Ⅱ類（VU）", "rl2020+subspecies:Kanagawa plant var. vv", "subspecies")
    assert resolver.resolve("jp-46", "Kanagawa plant") is None


def test_authorship_is_stripped_and_missing_name_falls_back_to_taxon(resolver, tmp_path):
    assert resolver.resolve("jp-46", "Garrulus lidthi Bonaparte, 1850")[1] == "kgrl2014"
    assert resolver.resolve("jp-46", "Passer montanus (Linnaeus, 1758)")[1] == "national"
    assert resolver.resolve("jp-46", None) is None
    assert resolver.resolve("jp-46", "") is None


def test_bare_name():
    assert bare_name("Columba janthina janthina (Temminck, 1830)") == "Columba janthina janthina"
    assert bare_name("Columba livia var. domestica J.F.Gmelin, 1789") == "Columba livia var. domestica"
    assert bare_name("Aster miyagii Koidz.") == "Aster miyagii"
    assert bare_name("Garrulus") == "Garrulus"
    assert bare_name(None) == ""


def test_taxon_id_fallback_when_scientific_name_is_missing(tmp_path):
    reg = tmp_path / "registry.sqlite"
    make_occurrence_registry_db(reg, taxa=[], places=[], place_refs=[], taxon_assessments=ASSESSMENTS)
    c = sqlite3.connect(reg)
    c.execute("INSERT INTO taxon (taxon_id, canonical_binomial, scientific_name) VALUES (?, ?, ?)",
              ("common:taxon:gbif.1", "Garrulus lidthi", "Garrulus lidthi Bonaparte, 1850"))
    c.commit()
    c.close()
    src = tmp_path / "ryuiki.sqlite"
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE taxa (taxon_id TEXT PRIMARY KEY, redlist_national TEXT)")
    c.commit()
    c.close()
    work = sqlite3.connect(":memory:")
    work.execute("ATTACH ? AS reg", (str(reg),))
    work.execute("ATTACH ? AS src", (str(src),))
    r = RedListResolver(work)
    assert r.resolve("jp-46", None, "common:taxon:gbif.1")[1] == "kgrl2014"


def test_fill_keeps_source_provided_values():
    import b06_build_occurrence as b06

    class Boom:
        def resolve(self, *a):
            raise AssertionError("出典が付けた値の記録は引かない")

    stats = b06._empty_stats()
    assert b06._fill_red_list(Boom(), stats, "s", "jp-46", "Garrulus lidthi", None, "既存", "kanagawa") == ("既存", "kanagawa")
    assert b06._fill_red_list(None, stats, "s", "jp-46", "x", None, None, None) == (None, None)
    assert stats["red_list_filled"] == {}


def test_constants():
    assert redlist_fill.NATIONAL_SOURCE == "national"
