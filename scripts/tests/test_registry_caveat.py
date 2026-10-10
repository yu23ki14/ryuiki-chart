"""registry/caveat.yaml・registry/caveat_scope.yaml の宣言の検査（Issue #35）。

正常系は実物の yaml を読む（手書きの正本。原本 DB は要らない）。異常系は実物を一時ディレクトリへ
コピーしてわざと壊し、`CaveatDeclarationError` で止まることを確かめる（検査が黙って無効に
ならないことの固定）。
"""
import shutil
import sqlite3

import pytest
import yaml

from registry import build_caveat
from registry import common

CAVEAT_VOCABULARY = {"variable", "place", "source_edition", "observation_set", "dataset", "taxon"}


@pytest.fixture
def decl(tmp_path, monkeypatch):
    """実物の宣言3ファイルを tmp にコピーして差し替える。戻り値: (caveat.yaml, caveat_scope.yaml) のパス。"""
    cav = tmp_path / "caveat.yaml"
    scope = tmp_path / "caveat_scope.yaml"
    shutil.copy(build_caveat.CAVEAT_YAML, cav)
    shutil.copy(build_caveat.CAVEAT_SCOPE_YAML, scope)
    monkeypatch.setattr(build_caveat, "CAVEAT_YAML", cav)
    monkeypatch.setattr(build_caveat, "CAVEAT_SCOPE_YAML", scope)
    return cav, scope


def _rewrite(path, mutate):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _build_rows():
    entries = build_caveat._load_caveat_yaml()
    return build_caveat._load_scope_declaration({e["key"] for e in entries})


def test_real_declaration_builds_and_uses_only_adr_vocabulary():
    rows = _build_rows()
    assert rows
    assert {r[1] for r in rows} <= CAVEAT_VOCABULARY
    # 旧語彙は残っていない
    assert not {r[1] for r in rows} & {"table", "table_prefix", "place_kind", "source_id", "variable_theme", "cell", "cell_table"}


def test_zone_caveat_body_contains_zone_yaml_note_ja():
    """zone.yaml の note_ja は caveat.yaml の zone の本文に手で複製してある。ずれたら止める。"""
    from registry import zone_rule
    note = zone_rule.load_zone_definition()["note_ja"].strip()
    body = {e["key"]: e["body_ja"] for e in build_caveat._load_caveat_yaml()}["zone"]
    assert note in body, "caveat.yaml の zone の body_ja が zone.yaml の note_ja を含まない（どちらかを直してそろえる）"


def test_every_caveat_has_a_complete_review_record():
    entries = build_caveat._load_caveat_yaml()
    assert len(entries) >= 18
    for e in entries:
        r = e["review"]
        assert r["reviewed_on"] in {"2026-10-06", "2026-10-07", "2026-10-10"}  # eDNA の注記4件は 10-07、zone は v2 で 10-10
        assert r["reviewer"] == "claude（オーナー委任）"
        assert r["owner_confirmed_on"] == "2026-10-07"
        assert r["reason"]


def test_sort_order_is_declaration_order_within_same_scope():
    by_scope = {}
    for cid, kind, ref, order, _prio in _build_rows():
        by_scope.setdefault((kind, ref), []).append((order, cid.rsplit(":", 1)[1]))
    assert sorted(by_scope[("place", "place_kind=site")]) == [(0, "zone"), (1, "municipality")]
    assert sorted(by_scope[("place", "place_kind=grid01")]) == [(0, "share")]  # effort は GBIF・iNat の source facet に移した（B, 2026-10-07）
    assert [k for _, k in sorted(by_scope[("dataset", "measurements")])] == ["measuredOn", "censoredLod", "duplicates"]
    # share は流域（dataset=organism_records）には掛からない
    assert "share" not in [k for _, k in by_scope.get(("dataset", "organism_records"), [])]


def test_priority_only_on_synthetic_scope():
    prio = {(r[1], r[2]): r[4] for r in _build_rows() if r[4] > 0}
    assert prio == {("observation_set", "is_synthetic=1"): 1}


def test_unit_unknown_refs_are_derived_not_hardcoded():
    refs = {r[2] for r in _build_rows() if r[0].endswith(":unitUnknown")}
    derived = {f"variable={v}&unit_id=null" for v in build_caveat._unit_unknown_variable_refs()}
    assert refs == derived and refs
    # 対象は variable_alias.csv の unit_id 空行からの導出だけで決まる（流量の扱いは #31 の alias 修正に従う）


def test_flow_and_transparency_are_variable_scopes():
    rows = {(r[0].rsplit(":", 1)[1], r[1], r[2]) for r in _build_rows()}
    assert ("flowTidalBackflow", "variable", "common:variable:hydro.flow") in rows
    assert ("aboveLod", "variable", "common:variable:water.transparency") in rows


def test_variable_yaml_no_longer_embeds_the_tidal_note():
    variables = yaml.safe_load(build_caveat.VARIABLE_YAML.read_text(encoding="utf-8"))["variables"]
    flow = next(v for v in variables if v["variable_id"] == "common:variable:hydro.flow")
    assert "逆流" not in flow["description_ja"]


# ---- わざと壊すと止まる ----

def test_missing_review_stops(decl):
    cav, _ = decl
    _rewrite(cav, lambda d: d["caveats"][0].pop("review"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="review"):
        build_caveat._load_caveat_yaml()


def test_incomplete_review_stops(decl):
    cav, _ = decl
    _rewrite(cav, lambda d: d["caveats"][0]["review"].pop("reason"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="reason"):
        build_caveat._load_caveat_yaml()


def test_missing_owner_confirmation_stops(decl):
    cav, _ = decl
    _rewrite(cav, lambda d: d["caveats"][0]["review"].pop("owner_confirmed_on"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="owner_confirmed_on"):
        build_caveat._load_caveat_yaml()


def test_bad_review_changed_value_stops(decl):
    cav, _ = decl
    _rewrite(cav, lambda d: d["caveats"][0]["review"].update(changed=["nonsense"]))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="changed"):
        build_caveat._load_caveat_yaml()


def test_unknown_scope_kind_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"][0].update(kind="table"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="語彙"):
        _build_rows()


def test_unknown_caveat_key_in_scope_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"][0]["caveats"].append("noSuchCaveat"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="noSuchCaveat"):
        _build_rows()


def test_unknown_variable_ref_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append({"kind": "variable", "ref": "common:variable:no.such", "caveats": ["zone"]}))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="no.such"):
        _build_rows()


def test_unknown_theme_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append({"kind": "variable", "ref": "theme=nothing", "caveats": ["zone"]}))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="theme"):
        _build_rows()


def test_selector_key_not_allowed_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append({"kind": "place", "ref": "bogus=1", "caveats": ["zone"]}))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="許可外"):
        _build_rows()


def test_plain_ref_for_selector_only_kind_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append({"kind": "place", "ref": "site", "caveats": ["zone"]}))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="ID 参照"):
        _build_rows()


def test_duplicate_scope_row_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append(dict(d["scopes"][0])))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="重複"):
        _build_rows()


def test_source_id_selector_accepts_manifest_sources(decl):
    """taxon_assessment 由来の集合（moe_ias_list）に無くても、manifests/ のある出典（kanagawa_edna）は受け付ける。"""
    rows = _build_rows()
    assert any(r[1] == "source_edition" and r[2] == "source_id=kanagawa_edna" for r in rows)
    assert "kanagawa_edna" in build_caveat._manifest_source_ids()
    assert "kanagawa_edna" not in (yaml.safe_load(decl[1].read_text(encoding="utf-8"))["values"]["source_id"])


def test_unknown_deriver_stops(decl):
    _, scope = decl
    def mutate(d):
        e = next(s for s in d["scopes"] if "ref_from" in s)
        e["ref_from"] = "nope"
    _rewrite(scope, mutate)
    with pytest.raises(build_caveat.CaveatDeclarationError, match="導出器"):
        _build_rows()


def test_caveat_not_in_any_scope_stops(decl):
    cav, _ = decl
    def mutate(d):
        d["caveats"].append(dict(d["caveats"][0], key="orphanCaveat"))
    _rewrite(cav, mutate)
    with pytest.raises(build_caveat.CaveatDeclarationError, match="orphanCaveat"):
        _build_rows()


def test_unscoped_declared_keys_are_not_in_scope_rows():
    scoped = {r[0].rsplit(":", 1)[1] for r in _build_rows()}
    assert {"fishClass", "inatBackfill"}.isdisjoint(scoped)


def test_unscoped_and_scoped_at_once_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["unscoped"].append("zone"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="両方"):
        _build_rows()


@pytest.mark.parametrize(
    "kind,ref,match",
    [
        ("place", "place_kind=nowhere", "実在する値でない"),
        ("source_edition", "source_id=no_such_source", "実在する値でない"),
        ("observation_set", "variable=common:variable:no.such&unit_id=null", "実在する値でない"),
        ("observation_set", "is_synthetic=0", "実在する値でない"),
        ("observation_set", "variable=common:variable:water.bod&unit_id=known", "実在する値でない"),
        ("dataset", "no_such_dataset", "values.dataset"),
        ("taxon", "common:taxon:gbif.1", "ID 参照"),
    ],
)
def test_selector_values_must_exist(decl, kind, ref, match):
    _, scope = decl
    _rewrite(scope, lambda d: d["scopes"].append({"kind": kind, "ref": ref, "caveats": ["zone"]}))
    with pytest.raises(build_caveat.CaveatDeclarationError, match=match):
        _build_rows()


def test_derived_ref_with_nonexistent_variable_stops(decl, monkeypatch):
    monkeypatch.setitem(build_caveat.REF_DERIVERS, "unit_unknown_variables", lambda: ["common:variable:no.such"])
    with pytest.raises(build_caveat.CaveatDeclarationError, match="実在する値でない"):
        _build_rows()


def test_empty_derivation_does_not_silently_drop_the_caveat(decl, monkeypatch):
    # #31 で unit_id が全部埋まると導出が空になる。unitUnknown を黙って消さず、止まる。
    monkeypatch.setitem(build_caveat.REF_DERIVERS, "unit_unknown_variables", lambda: [])
    with pytest.raises(build_caveat.CaveatDeclarationError, match="unitUnknown"):
        _build_rows()


def test_empty_derivation_is_ok_once_explicitly_moved_to_unscoped(decl, monkeypatch):
    _, scope = decl
    monkeypatch.setitem(build_caveat.REF_DERIVERS, "unit_unknown_variables", lambda: [])
    _rewrite(scope, lambda d: d["unscoped"].append("unitUnknown"))
    rows = _build_rows()
    assert not any(r[0].endswith(":unitUnknown") for r in rows)


def test_unscoped_unknown_key_stops(decl):
    _, scope = decl
    _rewrite(scope, lambda d: d["unscoped"].append("noSuch"))
    with pytest.raises(build_caveat.CaveatDeclarationError, match="noSuch"):
        _build_rows()


def test_build_from_files_writes_declared_rows(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript(common.SCHEMA_SQL.read_text(encoding="utf-8"))
    counts = build_caveat.build_from_files(conn)
    assert counts["caveat"] >= 18
    kinds = {r[0] for r in conn.execute("SELECT DISTINCT scope_kind FROM caveat_scope")}
    assert kinds <= CAVEAT_VOCABULARY
