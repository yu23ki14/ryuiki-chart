"""scripts/b06_build_occurrence.py の統合テスト。

本物の `data/db/ryuiki.sqlite`/`registry.sqlite`（828MB・52,215行）を要さず、
`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import sqlite3

import pytest

import b06_build_occurrence as b06
from migrate import common, occurrence_period, source_regions

from .occurrence_fixtures import (
    DEFAULT_ORGANISM_RECORDS,
    make_occurrence_registry_db,
    make_organism_records_db,
    make_period_shapes_yaml,
    make_source_regions_yaml,
)


def _build(tmp_path, organism_rows=None, taxa=None, places=None, place_refs=None,
           source_regions_text=None, period_shapes_text=None, period_shapes_counts=None):
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    source_regions_yaml = tmp_path / "source_regions.yaml"
    period_shapes_yaml = tmp_path / "occurrence_period_shapes.yaml"
    out = tmp_path / "v2.sqlite"

    make_organism_records_db(ryuiki_db, organism_rows)
    make_occurrence_registry_db(registry_db, taxa, places, place_refs)
    make_source_regions_yaml(source_regions_yaml, source_regions_text)
    make_period_shapes_yaml(period_shapes_yaml, period_shapes_text, period_shapes_counts)

    stats = b06.build_and_write_occurrence(
        ryuiki_db, registry_db, source_regions_yaml, period_shapes_yaml, out
    )
    return stats, out


def test_normal_case_resolves_all_rows(tmp_path):
    stats, out = _build(tmp_path)
    assert stats["total"] == len(DEFAULT_ORGANISM_RECORDS)
    assert stats["n_dated"] == len(DEFAULT_ORGANISM_RECORDS)
    assert stats["taxon_null_count"] == 1  # inat__1 は taxon_key が空文字
    assert stats["unresolved_taxon_count"] == 0
    assert stats["unresolved_place_count"] == 0
    assert stats["no_coordinate_count"] == 0

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = {r[0]: r for r in conn.execute(
        "SELECT record_id, source_table, source_row_id, source_id, region_id, taxon_id, "
        "place_id, place_kind, period_grain, period_start, period_end, period_raw, "
        "scientific_name, is_alien "
        "FROM occurrence"
    )}
    conn.close()

    gbif_row = rows["gbif__1"]
    assert gbif_row[1] == "organism_records"  # source_table
    assert isinstance(gbif_row[2], int)  # source_row_id は INTEGER（コードレビュー指摘5）
    assert gbif_row[3] == "gbif_kanagawa_occurrences"
    assert gbif_row[4] == "jp-14"  # region_id
    assert gbif_row[5] == "common:taxon:gbif.1001"  # taxon_id
    assert gbif_row[6] == "common:place:grid01.3550_13900"
    assert gbif_row[7] == "grid01"
    assert (gbif_row[8], gbif_row[9], gbif_row[10], gbif_row[11]) == (
        "day", "2020-01-05", "2020-01-05", "2020-01-05",
    )
    assert gbif_row[12] == "Foo bar"
    assert gbif_row[13] == 0

    inat_row = rows["inat__1"]
    assert inat_row[5] is None  # taxon_id NULL（taxon_key が空文字）
    assert inat_row[6] == "common:place:grid01.3550_13900"
    # 'Z' 変換: 03:00Z + 9h -> 12:00（ローカル）。日は変わらない。
    assert (inat_row[8], inat_row[9], inat_row[10], inat_row[11]) == (
        "instant", "2020-02-01T12:00:00", "2020-02-01T12:00:00", "2020-02-01T03:00Z",
    )


def test_source_row_id_orders_numerically(tmp_path):
    """source_row_id が INTEGER で入り、rowid の昇順（＝ organism_records への
    INSERT 順）で単調増加することを確認する（TEXT のままだと '10' < '2' の
    ような辞書順になってしまう。コードレビュー指摘5）。"""
    _stats, out = _build(tmp_path)
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    ids = [r[0] for r in conn.execute("SELECT source_row_id FROM occurrence ORDER BY source_row_id")]
    conn.close()
    assert ids == sorted(ids)
    assert ids == list(range(1, len(DEFAULT_ORGANISM_RECORDS) + 1))


def test_row_without_coordinates_is_kept_with_null_place(tmp_path):
    """座標（lat/lon）が無い記録は落とさず、place_id/place_kind を NULL のまま
    持つ（ADR-0007 原則1。コードレビュー指摘14）。エラーにはならない。"""
    rows = list(DEFAULT_ORGANISM_RECORDS) + [
        (
            "gbif__no_coord", "gbif_kanagawa_occurrences", "2020-01-06", None, None, None,
            "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
        ),
    ]
    stats, out = _build(
        tmp_path, organism_rows=rows,
        source_regions_text=(
            "sources:\n"
            "  gbif_kanagawa_occurrences:\n"
            "    region_id: jp-14\n    expected_row_count: 12\n    evidence: テスト用\n"
            "  inaturalist_kanagawa:\n"
            "    region_id: jp-14\n    expected_row_count: 1\n    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
        period_shapes_counts={"day": 2},
    )
    assert stats["no_coordinate_count"] == 1
    assert stats["unresolved_place_count"] == 0

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    row = conn.execute(
        "SELECT place_id, place_kind, lat, lon FROM occurrence WHERE record_id='gbif__no_coord'"
    ).fetchone()
    conn.close()
    assert row == (None, None, None, None)


def test_unresolved_taxon_key_raises(tmp_path):
    """未解決の taxon_key を持つ行は `_problems_from_stats` が
    `period.declaration_problems`（宣言表の件数照合）より先に止めるため、
    宣言表の件数を追加行に合わせて厳密に揃える必要はない（既定のままでよい）。"""
    rows = list(DEFAULT_ORGANISM_RECORDS) + [
        (
            "gbif__ghost", "gbif_kanagawa_occurrences", "2020-01-06", 35.505, 139.005, 10.0,
            "Ghost sp.", "", "SPECIES", "9999", "", 0, "", "公開",
        ),
    ]
    with pytest.raises(common.MigrationError, match="registry.taxon"):
        _build(tmp_path, organism_rows=rows)


def test_unresolved_place_raises_only_when_coordinates_present(tmp_path):
    """座標が grid01 に登録されていない（place_source_ref に無い）場合は
    止まる（ADR-0006 規約4の改定: 機械グリッドには常に解決するはずなので、
    解決できなければ構築の異常として扱う）。メッセージは「座標はあるのに」と
    明記する（座標が無い行と区別する。コードレビュー指摘14）。"""
    rows = list(DEFAULT_ORGANISM_RECORDS) + [
        (
            "gbif__elsewhere", "gbif_kanagawa_occurrences", "2020-01-06", 10.0, 20.0, 10.0,
            "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
        ),
    ]
    with pytest.raises(common.MigrationError, match="座標はあるのに"):
        _build(tmp_path, organism_rows=rows)


def test_unknown_source_id_raises_before_ingest(tmp_path):
    """`taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE` に無い source_id は
    取り込みの途中ではなく最初のチェックで即座に止まる。`sorted()` が
    `None`/`str` 混在で `TypeError` にならないことも確認する
    （コードレビュー指摘11）。"""
    rows = [
        ("x__1", "totally_unknown_source", "2020-01-05", 35.505, 139.005, None, "", "", "", "", "", 0, "", ""),
        ("x__2", None, "2020-01-05", 35.505, 139.005, None, "", "", "", "", "", 0, "", ""),
    ]
    with pytest.raises(common.MigrationError, match="totally_unknown_source"):
        _build(tmp_path, organism_rows=rows)


def test_unknown_source_region_raises(tmp_path):
    """source_id は taxon_namespaces には知られているが、source_regions.yaml
    に宣言が無い場合は `UnknownSourceRegionError`。"""
    with pytest.raises(source_regions.UnknownSourceRegionError):
        _build(tmp_path, source_regions_text="sources: {}\nregions: {}\n")


def test_unused_source_region_declaration_raises(tmp_path):
    text = (
        "sources:\n"
        "  gbif_kanagawa_occurrences:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 11\n"
        "    evidence: テスト\n"
        "  inaturalist_kanagawa:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "  never_used_source:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n"
    )
    with pytest.raises(common.MigrationError, match="never_used_source"):
        _build(tmp_path, source_regions_text=text)


def test_source_region_expected_row_count_mismatch_raises(tmp_path):
    text = (
        "sources:\n"
        "  gbif_kanagawa_occurrences:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 5\n"
        "    evidence: テスト\n"
        "  inaturalist_kanagawa:\n"
        "    region_id: jp-14\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト\n"
    )
    with pytest.raises(common.MigrationError, match="expected_row_count"):
        _build(tmp_path, source_regions_text=text)


def test_b06_succeeds_when_source_regions_yaml_also_has_landuse_declarations(tmp_path):
    """P-1b コードレビュー指摘8: `source_regions.yaml` に土地利用
    （consumer='observation'）の宣言が同居していても、b06（consumer で
    'occurrence' だけに絞り込む）は「使っていない宣言」として誤検出せず
    成功する（`consumer` 省略時の既定が 'occurrence' の occurrence 側2件は
    そのまま検証され、observation 側の1件は無視される）。
    """
    text = (
        "sources:\n"
        "  gbif_kanagawa_occurrences:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 11\n"
        "    evidence: テスト用\n"
        "  inaturalist_kanagawa:\n"
        "    region_id: jp-14\n"
        "    consumer: occurrence\n"
        "    expected_row_count: 1\n"
        "    evidence: テスト用\n"
        "  nlni_l03b_landuse_by_watershed:\n"  # b06 は使わない（consumer=observation）
        "    region_id: jp-14\n"
        "    consumer: observation\n"
        "    expected_row_count: 4858\n"
        "    evidence: テスト用\n"
        "regions:\n"
        "  jp-14:\n"
        "    utc_offset: \"+09:00\"\n"
        "    evidence: テスト用\n"
    )
    stats, _out = _build(tmp_path, source_regions_text=text)  # 例外を投げなければ良い
    assert stats["total"] == len(DEFAULT_ORGANISM_RECORDS)


def test_period_shapes_yaml_missing_one_shape_raises(tmp_path):
    """コードレビュー指摘4: `occurrence_period_shapes.yaml` の形の名前が
    コードの12形と過不足なく一致しないと即座に止まる（データの中身を見る前）。"""
    with pytest.raises(common.MigrationError, match="year"):
        _build(tmp_path, period_shapes_text="day:\n  expected_row_count: 1\n  note: テスト\n")


def test_unused_period_shape_declaration_raises(tmp_path):
    """全12形を宣言しつつ、実際には使われない形（0件のはずが宣言だけ増やした）
    があれば「未使用宣言」で止まる。"""
    with pytest.raises(common.MigrationError, match="expected_row_count"):
        _build(tmp_path, period_shapes_counts={"day": 999})


def test_year_boundary_crossed_stops_build(tmp_path):
    """'Z' 変換で年が変わる行があると、構築全体が止まる（D3の前提）。"""
    rows = list(DEFAULT_ORGANISM_RECORDS) + [
        (
            "gbif__ny", "gbif_kanagawa_occurrences", "2020-12-31T16:30Z", 35.505, 139.005, 10.0,
            "Foo bar", "", "SPECIES", "1001", "", 0, "", "公開",
        ),
    ]
    with pytest.raises(occurrence_period.YearBoundaryCrossedError):
        _build(tmp_path, organism_rows=rows)


def test_v2_sqlite_only_occurrence_table_is_touched(tmp_path):
    """`observation`/`observation_agg` 等の他テーブルには一切触れない（b03/b04 と
    同じファイルに同居する設計。`migrate.common.staged_table` が保証する）。"""
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    source_regions_yaml = tmp_path / "source_regions.yaml"
    period_shapes_yaml = tmp_path / "occurrence_period_shapes.yaml"
    out = tmp_path / "v2.sqlite"
    make_organism_records_db(ryuiki_db)
    make_occurrence_registry_db(registry_db)
    make_source_regions_yaml(source_regions_yaml)
    make_period_shapes_yaml(period_shapes_yaml)

    # observation 相当のテーブルを先に作っておく。
    pre = sqlite3.connect(f"file:{out}", uri=True)
    pre.execute("CREATE TABLE observation (dummy TEXT)")
    pre.execute("INSERT INTO observation VALUES ('keep-me')")
    pre.commit()
    pre.close()

    b06.build_and_write_occurrence(
        ryuiki_db, registry_db, source_regions_yaml, period_shapes_yaml, out
    )

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    assert conn.execute("SELECT dummy FROM observation").fetchone() == ("keep-me",)
    n_occurrence = conn.execute("SELECT COUNT(*) FROM occurrence").fetchone()[0]
    conn.close()
    assert n_occurrence == len(DEFAULT_ORGANISM_RECORDS)
