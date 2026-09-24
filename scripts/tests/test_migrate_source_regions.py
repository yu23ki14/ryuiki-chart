"""scripts/migrate/source_regions.py の単体テスト（ADR-0022 決定3・O-1 設計 v2 D1）。"""
import pytest

from migrate import period, source_regions as sr


def test_load_source_regions_from_yaml(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
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
    assert sources["src_a"].consumer == "occurrence"
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
        "    consumer: occurrence\n"
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
        "    consumer: occurrence\n"
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
# 孤児の region（コードレビュー指摘3）: 消費者で絞っても検査は全体に効くこと
# ---------------------------------------------------------------------------

def test_orphan_region_raises_without_consumer(tmp_path):
    """どの sources からも参照されない region は `consumer` を渡さない
    呼び出しでも検出される。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n"
        "  jp-99:\n"  # どの source からも参照されない孤児
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="jp-99"):
        sr.load_source_regions(yaml_path)


def test_orphan_region_raises_even_when_consumer_filters_sources(tmp_path):
    """`consumer` で sources を絞り込んでも、孤児 region の検査は絞り込み前の
    全 sources に対して行われる——ある consumer には無関係な孤児でも検出する
    （P-1b コードレビュー指摘3: 消費者ごとに regions まで絞ると、どの
    consumer からも孤児が見えなくなって検査が空振りする、という回帰）。
    """
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  occ_src:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n"
        "  jp-99:\n"  # occurrence からは無関係で、observation の sources も無い孤児
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    # consumer="occurrence" で呼んでも、consumer="observation" で呼んでも、
    # consumer 無指定で呼んでも、同じ孤児が検出される。
    for consumer in (None, "occurrence", "observation"):
        with pytest.raises(sr.MigrationError, match="jp-99"):
            sr.load_source_regions(yaml_path, consumer=consumer)


def test_no_orphan_region_when_all_referenced_across_consumers(tmp_path):
    """複数の consumer にまたがれば region が「参照されている」と判定される
    （孤児ではない）ことの正常系。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  occ_src:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "  obs_src:\n"
        "    region_id: jp-99\n"
        "    consumer: observation\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n"
        "  jp-99:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    sources, regions = sr.load_source_regions(yaml_path)  # 例外を投げなければ良い
    assert set(sources) == {"occ_src", "obs_src"}
    assert set(regions) == {"jp-14", "jp-99"}


# ---------------------------------------------------------------------------
# consumer による絞り込み（P-1b）
# ---------------------------------------------------------------------------

_CONSUMER_SPLIT_YAML_TEXT = (
    "sources:\n"
    "  occ_src:\n"
    "    region_id: jp-14\n"
    "    consumer: occurrence\n"
    "    expected_row_count: 1\n"
    "    evidence: テスト\n"
    "  landuse_src:\n"
    "    region_id: jp-99\n"
    "    consumer: observation\n"
    "    expected_row_count: 1\n"
    "    evidence: テスト\n"
    "regions:\n"
    "  jp-14:\n"
    "    utc_offset: \"+09:00\"\n"
    "    evidence: テスト\n"
    "  jp-99:\n"
    "    utc_offset: \"+09:00\"\n"
    "    evidence: テスト\n"
)


def test_consumer_none_returns_everything_unfiltered(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(_CONSUMER_SPLIT_YAML_TEXT, encoding="utf-8")
    sources, regions = sr.load_source_regions(yaml_path)
    assert set(sources) == {"occ_src", "landuse_src"}
    assert set(regions) == {"jp-14", "jp-99"}


def test_consumer_observation_excludes_occurrence_entries(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(_CONSUMER_SPLIT_YAML_TEXT, encoding="utf-8")
    sources, regions = sr.load_source_regions(yaml_path, consumer="observation")
    assert set(sources) == {"landuse_src"}
    assert set(regions) == {"jp-99"}


def test_validate_source_regions_shape_rejects_unknown_consumer(tmp_path):
    """`consumer` に `CONSUMER_CODES` 外の値があれば構造検証で落ちる
    （コードレビュー指摘8）。"""
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    consumer: bogus\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(sr.MigrationError, match="bogus"):
        sr.validate_source_regions_shape(yaml_path)


def test_validate_source_regions_shape_rejects_missing_consumer_key(tmp_path):
    """`consumer` は必須キー（オーナー決定。省略時に既定値へ黙って落ちる
    設計は採らない）。他の必須キーが揃っていても `consumer` だけが無ければ
    構造検証で止まる——`CONSUMER_CODES` 外の値で止まるのと同じ扱い
    （過去に存在した `_DEFAULT_CONSUMER` という後方互換の既定値は撤回した）。
    """
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
    with pytest.raises(sr.MigrationError, match="src_a"):
        sr.validate_source_regions_shape(yaml_path)


# ---------------------------------------------------------------------------
# validate_source_regions_shape（CI の構造検証。原本DBを必要としない）
# ---------------------------------------------------------------------------

def test_validate_source_regions_shape_accepts_complete_entries(tmp_path):
    yaml_path = tmp_path / "source_regions.yaml"
    yaml_path.write_text(
        "sources:\n"
        "  src_a:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
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
        "sources:\n  src_a:\n    region_id: jp-14\n    consumer: occurrence\n"
        "    expected_row_count: \"1\"\n    evidence: テスト\n"
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
    region = sr.Region(region_id="jp-14", utc_offset="+09:00", evidence="テスト")
    usage = period.EntryUsage({"jp-14": region})
    assert usage.unused_entries() == ["jp-14"]
    usage.mark_used("jp-14")
    assert usage.unused_entries() == []
    assert usage.mismatched_expected_counts() == {}


def test_unknown_source_region_error_message_mentions_source_id():
    with pytest.raises(sr.UnknownSourceRegionError, match="unknown_source"):
        raise sr.UnknownSourceRegionError("unknown_source")
