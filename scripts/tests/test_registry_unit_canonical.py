"""正準単位（ADR-0023、Issue #31）の宣言検査のテスト。

本物の registry/unit.yaml・variable_alias.csv が検査を通ること、および
「わざと壊すと止まる」ことを固定する。
"""
import copy

import pytest

from registry import build_unit_variable as bu


def _units():
    return copy.deepcopy(bu._load_unit_yaml())


def test_real_unit_yaml_passes_and_every_row_declares_canonical():
    units = _units()
    assert all(u["canonical_unit_id"] and u["scale_to_canonical"] for u in units)
    by_id = {u["unit_id"]: u for u in units}
    # ADR-0023 の8変数の組が、規則どおり1つの正準に寄る
    assert by_id["common:unit:0_1degc"]["canonical_unit_id"] == "common:unit:degc"
    assert by_id["common:unit:ppb"]["canonical_unit_id"] == "common:unit:ppm"
    assert by_id["common:unit:ug_per_m3"]["canonical_unit_id"] == "common:unit:mg_per_m3"
    assert by_id["common:unit:0_1mm"]["scale_to_canonical"] == pytest.approx(0.0001)
    # 水の mg/L と大気の mg/m3 は別扱い、ppmC は ppm に寄せない
    assert by_id["common:unit:mg_per_l"]["canonical_unit_id"] == "common:unit:mg_per_l"
    assert by_id["common:unit:0_01ppmc"]["canonical_unit_id"] == "common:unit:0_01ppmc"


def test_real_variable_units_share_a_canonical():
    bu.assert_variable_units_share_canonical(
        bu._load_variable_alias_csv(), bu._load_variable_yaml(), _units()
    )


def _unit(units, uid):
    return next(u for u in units if u["unit_id"] == uid)


def test_missing_canonical_key_halts():
    units = _units()
    del _unit(units, "common:unit:ppb")["canonical_unit_id"]
    with pytest.raises(AssertionError, match="canonical_unit_id が無い"):
        bu.assert_canonical_units(units)


def test_missing_scale_halts():
    units = _units()
    del _unit(units, "common:unit:ppb")["scale_to_canonical"]
    with pytest.raises(AssertionError, match="scale_to_canonical が無い"):
        bu.assert_canonical_units(units)


def test_unknown_canonical_halts():
    units = _units()
    _unit(units, "common:unit:ppb")["canonical_unit_id"] = "common:unit:nope"
    with pytest.raises(AssertionError, match="unit に無い"):
        bu.assert_canonical_units(units)


@pytest.mark.parametrize("scale", [0, -0.001, float("inf"), "0.001", True])
def test_bad_scale_halts(scale):
    units = _units()
    _unit(units, "common:unit:ppb")["scale_to_canonical"] = scale
    with pytest.raises(AssertionError, match="正の有限数"):
        bu.assert_canonical_units(units)


def test_canonical_across_quantity_kind_halts():
    units = _units()
    _unit(units, "common:unit:ppb")["canonical_unit_id"] = "common:unit:m"
    with pytest.raises(AssertionError, match="quantity_kind が違う"):
        bu.assert_canonical_units(units)


def test_self_canonical_with_scale_not_one_halts():
    units = _units()
    _unit(units, "common:unit:ppm")["scale_to_canonical"] = 2
    with pytest.raises(AssertionError, match="自分自身が正準"):
        bu.assert_canonical_units(units)


def test_chained_canonical_halts():
    units = _units()
    # ppm 自身が別の単位を正準にすると、ppb→ppm→? と連鎖する
    _unit(units, "common:unit:ppm")["canonical_unit_id"] = "common:unit:0_01ppmc"
    with pytest.raises(AssertionError, match="連鎖は不可"):
        bu.assert_canonical_units(units)


def test_variable_with_split_canonical_halts():
    units = _units()
    # 気温の alias が使う 0.1℃ を正準 degc から切り離すと、weather.air_temp の正準が割れる
    u = _unit(units, "common:unit:0_1degc")
    u["canonical_unit_id"] = "common:unit:0_1degc"
    u["scale_to_canonical"] = 1
    with pytest.raises(AssertionError, match="正準単位が割れている"):
        bu.assert_variable_units_share_canonical(
            bu._load_variable_alias_csv(), bu._load_variable_yaml(), units
        )


def test_unit_basis_missing_halts():
    rows = [{"alias": "a", "dataset": "d", "source_id": "s", "unit_id": "common:unit:mg_per_l", "unit_basis": ""}]
    with pytest.raises(AssertionError, match="unit_basis"):
        bu._assert_unit_basis(rows)


def test_unit_basis_without_unit_halts():
    rows = [{"alias": "a", "dataset": "d", "source_id": "s", "unit_id": "", "unit_basis": "source"}]
    with pytest.raises(AssertionError, match="unit_id が空なのに"):
        bu._assert_unit_basis(rows)


def test_unit_basis_ok():
    bu._assert_unit_basis([
        {"alias": "a", "dataset": "d", "source_id": "s", "unit_id": "common:unit:mg_per_l", "unit_basis": "registry"},
        {"alias": "b", "dataset": "d", "source_id": "s", "unit_id": "", "unit_basis": ""},
    ])
