"""scripts/migrate/source_regions.py の単体テスト（ADR-0022 決定3・O-1 設計 v2 D1）。

Issue #32-3: region の時刻帯は `registry/region.yaml`（`regions_path`）が正。
`source_regions.yaml` の `regions:` は撤去済みで、残っていれば止まる。
"""
import pytest

from migrate import period, regions as region_vocab, source_regions as sr


def _region_yaml(tmp_path, extra: str = ""):
    path = tmp_path / "region.yaml"
    path.write_text(
        "jp-14:\n"
        "  name_ja: 神奈川県\n"
        "  tz_name: Asia/Tokyo\n"
        "  utc_offset: \"+09:00\"\n"
        "  evidence: テスト\n" + extra,
        encoding="utf-8",
    )
    return path


def _extra_region(region_id: str, utc_offset: str, tz_name: str = "Asia/Tokyo") -> str:
    return (
        f"{region_id}:\n"
        "  name_ja: テスト\n"
        f"  tz_name: {tz_name}\n"
        f"  utc_offset: \"{utc_offset}\"\n"
        "  evidence: テスト\n"
    )


def _source(source_id="src_a", region_id="jp-14", consumer="occurrence", count=1):
    return (
        f"  {source_id}:\n"
        f"    region_id: {region_id}\n"
        f"    consumer: {consumer}\n"
        f"    expected_row_count: {count}\n"
        "    evidence: テスト\n"
    )


def _write_sources(tmp_path, *entries: str):
    path = tmp_path / "source_regions.yaml"
    path.write_text("sources:\n" + "".join(entries), encoding="utf-8")
    return path


def test_load_source_regions_from_yaml(tmp_path):
    yaml_path = _write_sources(tmp_path, _source(count=2))
    sources, regions = sr.load_source_regions(yaml_path, regions_path=_region_yaml(tmp_path))
    assert set(sources) == {"src_a"}
    assert sources["src_a"].region_id == "jp-14"
    assert sources["src_a"].consumer == "occurrence"
    assert sources["src_a"].expected_row_count == 2
    # region.yaml は語彙なので、参照されない region も載る（consumer 無指定のとき）。
    assert set(regions) == {"jp-14"}
    assert regions["jp-14"].utc_offset == "+09:00"
    assert regions["jp-14"].tz_name == "Asia/Tokyo"


def test_load_source_regions_missing_file_returns_empty_sources(tmp_path):
    sources, _regions = sr.load_source_regions(
        tmp_path / "does_not_exist.yaml", regions_path=_region_yaml(tmp_path)
    )
    assert sources == {}


def test_load_source_regions_source_with_undeclared_region_raises(tmp_path):
    """`sources` が参照する region_id が region.yaml に無い場合は、使う前
    （`load_source_regions` の時点）で止まる（黙って `KeyError` にしない）。"""
    yaml_path = _write_sources(tmp_path, _source(region_id="jp-99"))
    with pytest.raises(sr.MigrationError, match="jp-99"):
        sr.load_source_regions(yaml_path, regions_path=_region_yaml(tmp_path))


# ---------------------------------------------------------------------------
# 旧形式の `regions:`（Issue #32-3）: 残っていれば止める
# ---------------------------------------------------------------------------

def test_legacy_regions_key_in_source_regions_yaml_raises_on_load(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n" + _source() +
        "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="registry/region.yaml"):
        sr.load_source_regions(yaml_path, regions_path=_region_yaml(tmp_path))


def test_legacy_regions_key_in_source_regions_yaml_raises_on_shape_validation(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n" + _source() + "regions: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="registry/region.yaml"):
        sr.validate_source_regions_shape(yaml_path)


def test_real_source_regions_yaml_has_no_legacy_regions_key():
    sr.validate_source_regions_shape()  # 実ファイル。旧形式が復活すれば止まる


# ---------------------------------------------------------------------------
# utc_offset の厳密な検証（region.yaml 側）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "utc_offset",
    ["09:00", "+9:00", "+090:00", "+09:0", "+09-00", "+09:00:00", "", "JST"],
)
def test_load_regions_rejects_malformed_utc_offset(tmp_path, utc_offset):
    """符号無し（`'09:00'`）を読むと `_parse_utc_offset` の
    `sign = 1 if s[0]=='+' else -1` が黙って負に倒れる事故を防ぐ——読み込み時点
    で `^[+-][0-9]{2}:[0-9]{2}$` に一致しない値をすべて拒否する。"""
    path = tmp_path / "region.yaml"
    path.write_text(_extra_region("jp-14", utc_offset), encoding="utf-8")
    with pytest.raises(sr.MigrationError, match="utc_offset"):
        region_vocab.load_regions(path)


def test_load_regions_rejects_malformed_tz_name_and_missing_keys(tmp_path):
    path = tmp_path / "region.yaml"
    path.write_text(_extra_region("jp-14", "+09:00", tz_name="JST"), encoding="utf-8")
    with pytest.raises(sr.MigrationError, match="tz_name"):
        region_vocab.load_regions(path)
    path.write_text("jp-14:\n  utc_offset: \"+09:00\"\n", encoding="utf-8")
    with pytest.raises(sr.MigrationError, match="必須キー"):
        region_vocab.load_regions(path)


def test_load_source_regions_accepts_negative_utc_offset(tmp_path):
    yaml_path = _write_sources(tmp_path, _source(region_id="us-west"))
    regions_path = _region_yaml(tmp_path, _extra_region("us-west", "-08:00", tz_name="America/Los_Angeles"))
    _sources, regions = sr.load_source_regions(yaml_path, regions_path=regions_path)
    assert regions["us-west"].utc_offset == "-08:00"


def test_real_region_yaml_declares_jp14_jst():
    regions = region_vocab.load_regions()
    assert regions["jp-14"].tz_name == "Asia/Tokyo"
    assert regions["jp-14"].utc_offset == "+09:00"


def test_utc_offset_pattern_matches_examples():
    assert region_vocab.UTC_OFFSET_PATTERN.fullmatch("+09:00")
    assert region_vocab.UTC_OFFSET_PATTERN.fullmatch("-05:30")
    assert not region_vocab.UTC_OFFSET_PATTERN.fullmatch("09:00")
    assert not region_vocab.UTC_OFFSET_PATTERN.fullmatch("+9:00")


# ---------------------------------------------------------------------------
# consumer による絞り込み（P-1b）
# ---------------------------------------------------------------------------

def _consumer_split(tmp_path):
    yaml_path = _write_sources(
        tmp_path,
        _source("occ_src", "jp-14", "occurrence"),
        _source("landuse_src", "jp-99", "observation"),
    )
    regions_path = _region_yaml(tmp_path, _extra_region("jp-99", "+09:00"))
    return yaml_path, regions_path


def test_consumer_none_returns_everything_unfiltered(tmp_path):
    yaml_path, regions_path = _consumer_split(tmp_path)
    sources, regions = sr.load_source_regions(yaml_path, regions_path=regions_path)
    assert set(sources) == {"occ_src", "landuse_src"}
    assert set(regions) == {"jp-14", "jp-99"}


def test_consumer_observation_excludes_occurrence_entries(tmp_path):
    yaml_path, regions_path = _consumer_split(tmp_path)
    sources, regions = sr.load_source_regions(yaml_path, consumer="observation", regions_path=regions_path)
    assert set(sources) == {"landuse_src"}
    assert set(regions) == {"jp-99"}


def test_validate_source_regions_shape_rejects_unknown_consumer(tmp_path):
    """`consumer` に `CONSUMER_CODES` 外の値があれば構造検証で落ちる
    （コードレビュー指摘8）。"""
    yaml_path = _write_sources(tmp_path, _source(consumer="bogus"))
    with pytest.raises(sr.MigrationError, match="bogus"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_missing_consumer_key(tmp_path):
    """`consumer` は必須キー（オーナー決定。省略時に既定値へ黙って落ちる
    設計は採らない）。他の必須キーが揃っていても `consumer` だけが無ければ
    構造検証で止まる（過去に存在した `_DEFAULT_CONSUMER` は撤回した）。
    """
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n    expected_row_count: 1\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="src_a"):
        sr.validate_source_regions_shape(yaml_path)


# ---------------------------------------------------------------------------
# validate_source_regions_shape（CI の構造検証。原本DBを必要としない）
# ---------------------------------------------------------------------------

def test_validate_source_regions_shape_accepts_complete_entries(tmp_path):
    sr.validate_source_regions_shape(_write_sources(tmp_path, _source()))  # 例外を投げなければ良い


def test_validate_source_regions_shape_rejects_missing_source_key(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text("sources:\n  src_a:\n    region_id: jp-14\n", encoding="utf-8")
    with pytest.raises(sr.MigrationError, match="src_a"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_non_integer_expected_row_count(tmp_path):
    """コードレビュー指摘6: expected_row_count は整数必須。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n  src_a:\n    region_id: jp-14\n    consumer: occurrence\n"
        "    expected_row_count: \"1\"\n    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="整数"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_missing_file_is_allowed(tmp_path):
    sr.validate_source_regions_shape(tmp_path / "does_not_exist.yaml")  # 空表は許す


# ---------------------------------------------------------------------------
# period.EntryUsage（未使用宣言・件数不一致の検出。専用の別名は持たない
# ——/simplify 指摘10）
# ---------------------------------------------------------------------------

def test_source_region_usage_reports_unused_and_mismatched():
    src = sr.SourceRegion(
        source_id="src_a", region_id="jp-14", consumer="occurrence",
        expected_row_count=3, evidence="テスト",
    )
    usage = period.EntryUsage({"src_a": src})
    assert usage.unused_entries() == ["src_a"]
    usage.mark_used("src_a")
    usage.mark_used("src_a")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {"src_a": (3, 2)}


def test_region_usage_reports_unused_without_expected_count():
    """regions には expected_row_count が無い（常に None）ので、未使用の検出
    だけが働き、件数不一致は検出されない。"""
    region = region_vocab.RegionTime(
        region_id="jp-14", name_ja="神奈川県", tz_name="Asia/Tokyo", utc_offset="+09:00", evidence="テスト"
    )
    usage = period.EntryUsage({"jp-14": region})
    assert usage.unused_entries() == ["jp-14"]
    usage.mark_used("jp-14")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {}


def test_unknown_source_region_error_message_mentions_source_id():
    with pytest.raises(sr.UnknownSourceRegionError, match="unknown_source"):
        raise sr.UnknownSourceRegionError("unknown_source")
