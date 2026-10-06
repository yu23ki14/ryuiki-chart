"""`scripts/ingest/manifest.py`（マニフェストの構造検証）と、update_mode の registry への流れ・v2 コード指紋への算入（Issue #40 Phase D）。"""
from __future__ import annotations

import pathlib
import shutil

import pytest

from ingest import manifest as manifest_lib
from migrate import common

from .manifest_fixtures import write_manifest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _ok_expected():
    return {
        "period_shapes": {"day": 1},
        "place": {"coord_resolved": 0, "coord_unresolved": 0},
        "cube": {k: 0 for k in manifest_lib.EXPECTED_CUBE_KEYS},
    }


def _adapter_dir(tmp_path, name="src_a"):
    d = tmp_path / "adapters"
    d.mkdir(exist_ok=True)
    (d / f"{name}.py").write_text("def rows(ctx):\n    return iter(())\n", encoding="utf-8")
    return d


# ---- 実ファイル -------------------------------------------------------------------------------

def test_real_manifests_are_valid_and_cover_the_builtin_families():
    manifests = manifest_lib.load_manifests()
    tables = {next(iter(m.input.values())) for m in manifests.values()}
    assert {
        "organism_records", "measurements", "sensor_timeseries", "data/processed/nlni_l03b_landuse_by_watershed.csv",
    } <= tables
    assert {m.region for m in manifests.values()} == {"jp-14"}


def test_update_mode_codes_match_registry_editions_yaml():
    from registry import build_source

    assert tuple(build_source.load_editions_yaml()["update_mode_codes"]) == manifest_lib.UPDATE_MODE_CODES


def test_real_manifest_regions_exist_in_region_yaml():
    from migrate import regions as region_vocab

    regions = region_vocab.load_regions()
    for m in manifest_lib.load_manifests().values():
        assert m.region in regions


# ---- 構造検証（わざと壊すと止まる）----------------------------------------------------------------

@pytest.mark.parametrize("missing", ["region", "target", "update_mode", "input", "adapter", "evidence"])
def test_missing_required_key_stops(tmp_path, missing):
    p = write_manifest(tmp_path / "m", "src_a", target="occurrence")
    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"{missing}:")]
    if missing == "input":  # input は子行を持つ
        lines = [ln for ln in lines if not ln.startswith("  table:")]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(common.MigrationError, match=missing):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


def test_unknown_key_stops(tmp_path):
    write_manifest(tmp_path / "m", "src_a", target="occurrence", extra={"map": {"x": 1}})
    with pytest.raises(common.MigrationError, match="未知のキー"):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


@pytest.mark.parametrize("target", ["feature", "place", "document"])
def test_target_outside_observation_occurrence_stops(tmp_path, target):
    write_manifest(tmp_path / "m", "src_a", target="occurrence")
    p = tmp_path / "m" / "src_a.yml"
    p.write_text(p.read_text(encoding="utf-8").replace("target: occurrence", f"target: {target}"), encoding="utf-8")
    with pytest.raises(common.MigrationError, match=target):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


def test_update_mode_outside_enum_stops(tmp_path):
    write_manifest(tmp_path / "m", "src_a", target="occurrence", update_mode="hourly")
    with pytest.raises(common.MigrationError, match="hourly"):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


def test_input_must_be_exactly_one_of_table_or_file(tmp_path):
    write_manifest(tmp_path / "m", "src_a", target="occurrence", input={"table": "t", "file": "f"})
    with pytest.raises(common.MigrationError, match="input"):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


def test_adapter_must_exist_and_match_source_name(tmp_path):
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="src_a", expected_row_count=1,
                   extra={"expected": _ok_expected()})
    with pytest.raises(common.MigrationError, match="が無い"):
        manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=tmp_path / "nope")
    manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=_adapter_dir(tmp_path))
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="other", expected_row_count=1,
                   extra={"expected": _ok_expected()})
    with pytest.raises(common.MigrationError, match="source と同じ名前"):
        manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=_adapter_dir(tmp_path))


def test_builtin_cannot_carry_checks_or_expected(tmp_path):
    write_manifest(tmp_path / "m", "src_a", target="occurrence", extra={"expected": _ok_expected()})
    with pytest.raises(common.MigrationError, match="builtin に expected"):
        manifest_lib.validate_manifests_shape(tmp_path / "m")
    write_manifest(tmp_path / "m", "src_a", target="occurrence", extra={"checks": [{"not_null": ["record_key"]}]})
    with pytest.raises(common.MigrationError, match="builtin に checks"):
        manifest_lib.validate_manifests_shape(tmp_path / "m")


def test_non_builtin_occurrence_requires_expected_and_row_count(tmp_path):
    ad = _adapter_dir(tmp_path)
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="src_a")
    with pytest.raises(common.MigrationError) as e:
        manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=ad)
    assert "expected_row_count が必須" in str(e.value) and "expected が必須" in str(e.value)


def test_expected_block_shape_is_validated(tmp_path):
    ad = _adapter_dir(tmp_path)
    bad = _ok_expected()
    bad["cube"]["dated_rows"] = -1
    del bad["place"]["coord_resolved"]
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="src_a", expected_row_count=1,
                   extra={"expected": bad})
    with pytest.raises(common.MigrationError) as e:
        manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=ad)
    assert "dated_rows" in str(e.value) and "place" in str(e.value)


@pytest.mark.parametrize(
    "check",
    [{"in_codelist": "x"}, {"not_null": ["nope"]}, {"row_count_between": [5, 1]}, {"in_registry": "variable"},
     {"date_between": ["2020", "2021"]}, {"not_null": ["record_key"], "unique": ["record_key"]}],
)
def test_check_vocabulary_is_closed(tmp_path, check):
    ad = _adapter_dir(tmp_path)
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="src_a", expected_row_count=1,
                   extra={"expected": _ok_expected(), "checks": [check]})
    with pytest.raises(common.MigrationError, match="checks"):
        manifest_lib.validate_manifests_shape(tmp_path / "m", adapters_dir=ad)


def test_expected_sums_adds_only_non_builtin_manifests(tmp_path):
    ad = _adapter_dir(tmp_path)
    write_manifest(tmp_path / "m", "gbif_x", target="occurrence")  # builtin（宣言は yaml 側）
    e = _ok_expected()
    e["cube"]["dated_rows"] = 7
    write_manifest(tmp_path / "m", "src_a", target="occurrence", adapter="src_a", expected_row_count=1,
                   extra={"expected": e})
    sums = manifest_lib.expected_sums(manifest_lib.load_manifests(tmp_path / "m", adapters_dir=ad))
    assert sums.cube["dated_rows"] == 7 and sums.sources == ("src_a",) and sums.period_shapes == {"day": 1}


# ---- registry（source_edition.update_mode）への流れ ----------------------------------------------

def _src_row(sid):
    return {
        "source_id": sid, "name": sid, "publisher": "p", "url": "u", "category": "c", "access_method": "a",
        "format": "f", "license": "L1", "redistributable": 1, "fetched_at": "2026-09-01T00:00:00",
        "record_count": 1, "notes": None,
    }


def _assemble(manifest_modes, editions_extra=None):
    from registry import build_source

    lic_entry = {"license_class": "open", "name_ja": "x", "spdx_or_url": None, "attribution_text": None, "notes": None}
    lic = {
        "license_classes": {"open": {"commercial_ok": 1}},
        "licenses": [{"license_id": "L1", **lic_entry}, {"license_id": "unknown", **lic_entry}],
        "mappings": [{"raw": "L1", "license_id": "L1"}],
    }
    ed = {"update_mode_codes": list(manifest_lib.UPDATE_MODE_CODES), "declared_editions": [],
          "source_declarations": editions_extra or {}}
    return build_source.assemble([_src_row("a"), _src_row("b")], lic, ed, manifest_modes=manifest_modes)


def test_manifest_update_mode_reaches_source_edition():
    from registry import build_source

    _lic, _src, editions, _un = _assemble({"a": "append"})
    sid_i = build_source._EDITION_COLUMNS.index("source_id")
    um_i = build_source._EDITION_COLUMNS.index("update_mode")
    by_source = {e[sid_i]: e[um_i] for e in editions}
    assert by_source["a"] == "append"
    assert by_source["b"] is None  # マニフェストの無い出典は従来どおり NULL（推測で埋めない）


def test_update_mode_conflict_between_manifest_and_editions_yaml_stops():
    with pytest.raises(AssertionError, match="update_mode が食い違う"):
        _assemble({"a": "append"}, editions_extra={"a": {"update_mode": "snapshot"}})


def test_manifest_source_missing_from_source_registry_stops():
    with pytest.raises(AssertionError, match="source_registry に無い"):
        _assemble({"ghost": "append"})


# ---- v2 のコード指紋（manifests・adapters を入れる）-----------------------------------------------

@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    dst = tmp_path_factory.mktemp("repo_copy")
    shutil.copytree(ROOT / "scripts", dst / "scripts", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    shutil.copytree(ROOT / "aggregations", dst / "aggregations")
    shutil.copytree(ROOT / "manifests", dst / "manifests")
    return dst


def test_changing_a_manifest_or_an_adapter_changes_the_v2_code_fingerprint(repo_copy):
    base = common._v2_pipeline_code_fingerprint(repo_copy)
    manifest_file = next((repo_copy / "manifests").glob("*.yml"))
    original = manifest_file.read_text(encoding="utf-8")
    manifest_file.write_text(original + "# 1 文字違い\n", encoding="utf-8")
    try:
        assert common._v2_pipeline_code_fingerprint(repo_copy) != base
    finally:
        manifest_file.write_text(original, encoding="utf-8")
    assert common._v2_pipeline_code_fingerprint(repo_copy) == base

    adapter = repo_copy / "scripts" / "adapters" / "zz_new_adapter.py"
    adapter.write_text("def rows(ctx):\n    return iter(())\n", encoding="utf-8")
    try:
        with_adapter = common._v2_pipeline_code_fingerprint(repo_copy)
        assert with_adapter != base
        adapter.write_text("def rows(ctx):\n    return iter(())  \n", encoding="utf-8")
        assert common._v2_pipeline_code_fingerprint(repo_copy) != with_adapter
    finally:
        adapter.unlink()


def test_non_builtin_manifest_inputs_are_part_of_the_v2_input_fingerprint(tmp_path):
    write_manifest(tmp_path / "manifests", "src_a", target="occurrence", adapter="src_a", input={"table": "wildlife_sightings"})
    write_manifest(tmp_path / "manifests", "src_b", target="occurrence", adapter="src_b", input={"file": "data/x.csv"})
    write_manifest(tmp_path / "manifests", "gbif_x", target="occurrence")  # builtin は対象外
    assert common.manifest_inputs(tmp_path / "manifests") == (("wildlife_sightings",), ("data/x.csv",))
