"""scripts/migrate/source_regions.py の単体テスト（ADR-0022 決定3・O-1 設計 v2 D1）。"""
import pytest

from migrate import source_regions as sr


def test_load_source_regions_from_yaml(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 2\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    sources, regions = sr.load_source_regions(yaml_path)
    assert set(sources) == {"src_a"}
    assert sources["src_a"].region_id == "jp-14"
    assert sources["src_a"].expected_row_count == 2
    assert set(regions) == {"jp-14"}
    assert regions["jp-14"].utc_offset == "+09:00"


def test_load_source_regions_missing_file_returns_empty(tmp_path):
    sources, regions = sr.load_source_regions(tmp_path / "does_not_exist.yaml")
    assert sources == {}
    assert regions == {}


def test_load_source_regions_source_with_undeclared_region_raises(tmp_path):
    """`sources` が参照する region_id が `regions` に無い場合は、使う前
    （`load_source_regions` の時点）で止まる（黙って `KeyError` にしない）。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-99\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="jp-99"):
        sr.load_source_regions(yaml_path)


# ---------------------------------------------------------------------------
# utc_offset の厳密な検証（コードレビュー指摘1）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "utc_offset",
    ["09:00", "+9:00", "+090:00", "+09:0", "+09-00", "+09:00:00", "", "JST"],
)
def test_load_source_regions_rejects_malformed_utc_offset(tmp_path, utc_offset):
    """符号無し（`'09:00'`）を読むと `_parse_utc_offset` の
    `sign = 1 if s[0]=='+' else -1` が黙って負に倒れる事故を防ぐ——読み込み時点
    で `^[+-][0-9]{2}:[0-9]{2}$` に一致しない値をすべて拒否する。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        f"    utc_offset: \"{utc_offset}\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="utc_offset"):
        sr.load_source_regions(yaml_path)


def test_load_source_regions_accepts_negative_utc_offset(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: us-west\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  us-west:\n"
        "    utc_offset: \"-08:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    _sources, regions = sr.load_source_regions(yaml_path)
    assert regions["us-west"].utc_offset == "-08:00"


def test_utc_offset_pattern_matches_examples():
    assert sr.UTC_OFFSET_PATTERN.fullmatch("+09:00")
    assert sr.UTC_OFFSET_PATTERN.fullmatch("-05:30")
    assert not sr.UTC_OFFSET_PATTERN.fullmatch("09:00")
    assert not sr.UTC_OFFSET_PATTERN.fullmatch("+9:00")


# ---------------------------------------------------------------------------
# validate_source_regions_shape（CI の構造検証。原本DBを必要としない）
# ---------------------------------------------------------------------------

def test_validate_source_regions_shape_accepts_complete_entries(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    sr.validate_source_regions_shape(yaml_path)  # 例外を投げなければ良い


def test_validate_source_regions_shape_rejects_missing_source_key(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n"
        "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="src_a"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_missing_region_key(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n    expected_row_count: 1\n    evidence: テスト\n"
        "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="jp-14"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_non_integer_expected_row_count(tmp_path):
    """コードレビュー指摘6: expected_row_count は整数必須。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n    expected_row_count: \"1\"\n    evidence: テスト\n"
        "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="整数"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_malformed_utc_offset(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n    expected_row_count: 1\n    evidence: テスト\n"
        "regions:\n  jp-14:\n    utc_offset: \"09:00\"\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="utc_offset"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_missing_file_is_allowed(tmp_path):
    sr.validate_source_regions_shape(tmp_path / "does_not_exist.yaml")  # 空表は許す


# ---------------------------------------------------------------------------
# SourceRegionUsage / RegionUsage（未使用宣言・件数不一致の検出）
# ---------------------------------------------------------------------------

def test_source_region_usage_reports_unused_and_mismatched():
    src = sr.SourceRegion(source_id="src_a", region_id="jp-14", expected_row_count=3, evidence="テスト")
    usage = sr.SourceRegionUsage({"src_a": src})
    assert usage.unused_entries() == ["src_a"]
    usage.mark_used("src_a")
    usage.mark_used("src_a")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {"src_a": (3, 2)}


def test_region_usage_reports_unused_without_expected_count():
    """regions には expected_row_count が無い（常に None）ので、未使用の検出
    だけが働き、件数不一致は検出されない。"""
    region = sr.Region(region_id="jp-14", utc_offset="+09:00", evidence="テスト")
    usage = sr.RegionUsage({"jp-14": region})
    assert usage.unused_entries() == ["jp-14"]
    usage.mark_used("jp-14")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {}


def test_unknown_source_region_error_message_mentions_source_id():
    with pytest.raises(sr.UnknownSourceRegionError, match="unknown_source"):
        raise sr.UnknownSourceRegionError("unknown_source")
