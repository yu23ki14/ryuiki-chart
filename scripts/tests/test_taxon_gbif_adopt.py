"""弱い一致の自動採用判定（scripts/taxon_gbif_adopt.py）と c26 の行組み立て（Issue #34 D2・D3）。
ネットワークは使わない（get_json は偽物を注入する）。"""
import c26_taxon_gbif_accepted as c26
from taxon_gbif_adopt import decide_weak_match, normalize_canonical, parse_query_name


def _match(**kw):
    base = {"usageKey": 1, "canonicalName": "Foo bar", "rank": "SPECIES", "matchType": "EXACT",
            "status": "ACCEPTED", "alternatives": []}
    base.update(kw)
    return base


def _decide(name, match):
    return decide_weak_match(parse_query_name(name), match)


def test_exact_canonical_species_single_candidate_is_adopted():
    assert _decide("Foo bar (Smith, 1900)", _match())["resolution"] == "adopted"


def test_fuzzy_spelling_is_not_adopted():
    d = _decide("Foo baar", _match(matchType="FUZZY"))
    assert (d["resolution"], d["reason"]) == ("unresolved", "fuzzy_spelling")


def test_infraspecific_collapsed_to_species_is_not_adopted():
    """亜種名で聞いて種に丸められた（正規形が違う）。HIGHERRANK/SPECIES の典型。"""
    d = _decide("Parus varius orii", _match(canonicalName="Parus varius", matchType="HIGHERRANK"))
    assert (d["resolution"], d["reason"]) == ("unresolved", "infraspecific_collapsed")
    # 著者名＋変種: 著者を読み飛ばしても var. 以下は正規形に残るので、種との一致を採用しない
    d = _decide("Chara globularis Thuill. var. hakonensis Kasaki",
                _match(canonicalName="Chara globularis", matchType="EXACT"))
    assert (d["resolution"], d["reason"]) == ("unresolved", "infraspecific_collapsed")


def test_infraspecific_exact_with_rank_marker_is_adopted():
    d = _decide("Chara globularis var. hakonensis",
                _match(canonicalName="Chara globularis var. hakonensis", rank="VARIETY"))
    assert d["resolution"] == "adopted"


def test_genus_level_and_annotated_names_are_not_queried():
    assert parse_query_name("Atrax spp.")["reason"] == "genus_or_higher"
    assert parse_query_name("Atrax")["reason"] == "genus_or_higher"
    assert parse_query_name("Rana catesbeiana（Lithobates catesbeianus)")["reason"] == "annotated_name"


def test_higher_rank_and_no_candidate_and_api_failure():
    assert _decide("Foo bar", _match(rank="GENUS", canonicalName="Foo"))["reason"] == "higher_rank"
    assert _decide("Foo bar", {"matchType": "NONE"})["reason"] == "no_candidate"
    assert _decide("Foo bar", None)["reason"] == "api_failed"


def test_two_candidates_with_same_canonical_name_are_ambiguous():
    d = _decide("Foo bar", _match(alternatives=[{"usageKey": 2, "canonicalName": "Foo bar", "rank": "SPECIES"}]))
    assert (d["resolution"], d["reason"]) == ("unresolved", "ambiguous")
    # 別名・上位ランクの候補は数えない
    d = _decide("Foo bar", _match(alternatives=[{"usageKey": 3, "canonicalName": "Foo", "rank": "GENUS"}]))
    assert d["resolution"] == "adopted"


def test_normalize_canonical_drops_rank_markers():
    assert normalize_canonical("Chara  globularis var. Hakonensis") == "chara globularis hakonensis"


# ---- c26.build_rows -------------------------------------------------------

def _cw(tid, name, key, match, status, **kw):
    return {"taxon_id": tid, "scientific_name": name, "taxon_key": key, "matchType": match, "status": status, **kw}


def test_build_rows_self_for_accepted_api_for_synonym_and_skips_none():
    calls = []

    def fake(url, params=None):
        calls.append(url)
        return {"acceptedKey": 777, "accepted": "Real name"}

    cw = [_cw("a", "Foo bar", "10", "EXACT", "ACCEPTED"),
          _cw("b", "Old name", "20", "EXACT", "SYNONYM"),
          _cw("c", "Nothing", "", "NONE", "")]
    rows, n = c26.build_rows(cw, {}, fake)
    by = {r["taxon_id"]: r for r in rows}
    assert set(by) == {"a", "b"} and n == 1 and calls == ["https://api.gbif.org/v1/species/20"]
    assert (by["a"]["accepted_key"], by["a"]["accepted_basis"]) == ("10", "self")
    assert (by["b"]["accepted_key"], by["b"]["accepted_basis"]) == ("777", "api")


def test_build_rows_synonym_without_accepted_key_stays_blank_and_failure_is_retried():
    cw = [_cw("b", "Old name", "20", "EXACT", "DOUBTFUL")]
    rows, _ = c26.build_rows(cw, {}, lambda url, params=None: {})
    assert (rows[0]["accepted_key"], rows[0]["accepted_basis"]) == ("", "api")

    def boom(url, params=None):
        raise RuntimeError("x")
    rows, _ = c26.build_rows(cw, {}, boom)
    assert rows[0]["accepted_basis"] == "api_failed"
    # 増分: api_failed は次回引き直す。成功済みは引き直さない
    rows2, n2 = c26.build_rows(cw, {"b": rows[0]}, lambda url, params=None: {"acceptedKey": 5})
    assert (rows2[0]["accepted_key"], n2) == ("5", 1)
    rows3, n3 = c26.build_rows(cw, {"b": rows2[0]}, boom)
    assert (rows3[0]["accepted_key"], n3) == ("5", 0)


def test_build_rows_weak_match_adopted_and_unresolved_with_reason():
    def fake(url, params=None):
        return _match(usageKey=99, canonicalName="Foo bar")

    cw = [_cw("w1", "Foo bar", "5", "HIGHERRANK", "ACCEPTED", rank="GENUS"),
          _cw("w2", "Atrax spp.", "6", "HIGHERRANK", "")]
    rows, n = c26.build_rows(cw, {}, fake)
    by = {r["taxon_id"]: r for r in rows}
    assert (by["w1"]["weak_resolution"], by["w1"]["weak_key"]) == ("adopted", "99")
    assert (by["w2"]["weak_resolution"], by["w2"]["weak_reason"]) == ("unresolved", "genus_or_higher")
    assert n == 1  # spp. は API を引かない
