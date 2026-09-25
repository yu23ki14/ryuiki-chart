"""`scripts/migrate/period.py` の件数の宣言の上書き機構（Issue #29「縮小サンプル
＋実行証明」A-2）の単体テスト。原本DB・data/sample/ の実データは一切使わない
（自前の小さな辞書・tmp_path だけで完結する）。
"""
from __future__ import annotations

import pytest

from migrate import period


# ---------------------------------------------------------------------------
# apply_count_overlay
# ---------------------------------------------------------------------------


def test_apply_count_overlay_replaces_expected_row_count_only():
    entries = {"a": {"expected_row_count": 100, "reason": "x", "note": "keep me"}}
    out = period.apply_count_overlay(entries, {"a": 3})
    assert out == {"a": {"expected_row_count": 3, "reason": "x", "note": "keep me"}}
    # 元の dict は変更されない（コピーを返す）。
    assert entries["a"]["expected_row_count"] == 100


def test_apply_count_overlay_replaces_expected_count_only():
    entries = {"a": {"expected_count": 100, "note": "n"}}
    out = period.apply_count_overlay(entries, {"a": 7})
    assert out["a"]["expected_count"] == 7


def test_apply_count_overlay_replaces_breakdown_key():
    entries = {
        "moved": {
            "expected_count": 10,
            "breakdown": {"x": 3, "y": 7},
            "note": "n",
        }
    }
    out = period.apply_count_overlay(entries, {"moved": 5, "moved.x": 1, "moved.y": 4})
    assert out["moved"]["expected_count"] == 5
    assert out["moved"]["breakdown"] == {"x": 1, "y": 4}


def test_apply_count_overlay_unknown_entry_raises_keyerror():
    entries = {"a": {"expected_row_count": 1}}
    with pytest.raises(KeyError):
        period.apply_count_overlay(entries, {"b": 1})


def test_apply_count_overlay_unknown_breakdown_key_raises_keyerror():
    entries = {"a": {"expected_count": 1, "breakdown": {"x": 1}}}
    with pytest.raises(KeyError):
        period.apply_count_overlay(entries, {"a.y": 1})


def test_apply_count_overlay_entry_without_count_field_raises_keyerror():
    entries = {"a": {"note": "no count field here"}}
    with pytest.raises(KeyError):
        period.apply_count_overlay(entries, {"a": 1})


def test_apply_count_overlay_non_int_value_raises_typeerror():
    entries = {"a": {"expected_row_count": 1}}
    with pytest.raises(TypeError):
        period.apply_count_overlay(entries, {"a": 1.5})


def test_apply_count_overlay_bool_value_raises_typeerror():
    """`bool` は `int` のサブクラスなので明示的に弾く（True/False が1/0として
    紛れ込むのを防ぐ）。
    """
    entries = {"a": {"expected_row_count": 1}}
    with pytest.raises(TypeError):
        period.apply_count_overlay(entries, {"a": True})


def test_apply_count_overlay_empty_overlay_is_noop():
    entries = {"a": {"expected_row_count": 1}}
    out = period.apply_count_overlay(entries, {})
    assert out == entries


# ---------------------------------------------------------------------------
# load_count_overlay_file / resolve_count_overlay
# ---------------------------------------------------------------------------


def test_load_count_overlay_file_groups_by_filename(tmp_path):
    path = tmp_path / "declaration_counts.yaml"
    path.write_text(
        '"period_exceptions.yaml:atsugi_river_water_quality": 5\n'
        '"source_regions.yaml:gbif_kanagawa_occurrences": 12\n'
        '"occurrence_watershed_v1_declarations.yaml:memo_moved_records.ws_to_ws": 1\n',
        encoding="utf-8",
    )
    grouped = period.load_count_overlay_file(path)
    assert grouped == {
        "period_exceptions.yaml": {"atsugi_river_water_quality": 5},
        "source_regions.yaml": {"gbif_kanagawa_occurrences": 12},
        "occurrence_watershed_v1_declarations.yaml": {"memo_moved_records.ws_to_ws": 1},
    }


def test_load_count_overlay_file_key_without_colon_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text('"no_colon_here": 1\n', encoding="utf-8")
    with pytest.raises(Exception):
        period.load_count_overlay_file(path)


def test_load_count_overlay_file_not_a_mapping_raises(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(Exception):
        period.load_count_overlay_file(path)


def test_resolve_count_overlay_none_path_returns_none():
    assert period.resolve_count_overlay(None, "period_exceptions.yaml") is None


def test_resolve_count_overlay_returns_only_matching_file(tmp_path):
    path = tmp_path / "declaration_counts.yaml"
    path.write_text(
        '"period_exceptions.yaml:atsugi_river_water_quality": 5\n'
        '"time_label_conventions.yaml:sagamihara_taiki_hourly": 9\n',
        encoding="utf-8",
    )
    assert period.resolve_count_overlay(str(path), "period_exceptions.yaml") == {
        "atsugi_river_water_quality": 5
    }
    assert period.resolve_count_overlay(str(path), "time_label_conventions.yaml") == {
        "sagamihara_taiki_hourly": 9
    }
    # 宣言の無いファイル名は空 dict（KeyError にしない——ある正本ファイルに
    # サンプル側の上書きが1件も無いこと自体はエラーではない）。
    assert period.resolve_count_overlay(str(path), "occurrence_period_shapes.yaml") == {}


# ---------------------------------------------------------------------------
# 既定 None での既存 load_* の挙動が変わっていないこと（後方互換の確認）
# ---------------------------------------------------------------------------


def test_load_period_exceptions_without_overlay_is_unchanged(tmp_path):
    path = tmp_path / "period_exceptions.yaml"
    path.write_text(
        "atsugi_like:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 3840\n"
        "  reason: r\n"
        "  restoration_plan: p\n",
        encoding="utf-8",
    )
    exceptions = period.load_period_exceptions(path)
    assert exceptions["atsugi_like"].expected_row_count == 3840


def test_load_period_exceptions_with_overlay_replaces_expected_row_count(tmp_path):
    path = tmp_path / "period_exceptions.yaml"
    path.write_text(
        "atsugi_like:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 3840\n"
        "  reason: r\n"
        "  restoration_plan: p\n",
        encoding="utf-8",
    )
    exceptions = period.load_period_exceptions(path, count_overlay={"atsugi_like": 20})
    assert exceptions["atsugi_like"].expected_row_count == 20
    # 意味の情報（reason/restoration_plan/period_grain_override）は変わらない。
    assert exceptions["atsugi_like"].reason == "r"
    assert exceptions["atsugi_like"].period_grain_override == "fiscal_year"


def test_load_time_label_conventions_with_overlay(tmp_path):
    path = tmp_path / "time_label_conventions.yaml"
    path.write_text(
        "sagamihara_taiki_hourly:\n"
        "  convention: hour_ending\n"
        "  expected_row_count: 175344\n"
        "  evidence: e\n",
        encoding="utf-8",
    )
    conventions = period.load_time_label_conventions(path, count_overlay={"sagamihara_taiki_hourly": 10})
    assert conventions["sagamihara_taiki_hourly"].expected_row_count == 10
