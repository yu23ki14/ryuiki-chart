"""scripts/b03_build_observation.py の統合テスト。

本物の `data/db/ryuiki.sqlite`/`registry.sqlite`（828MB・52,215行）を要さず、
`scripts/tests/migrate_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import inspect
import sqlite3

import pytest

import b03_build_observation as b03
from migrate import common

from migrate import source_regions

from .migrate_fixtures import (
    DEFAULT_ALIASES,
    DEFAULT_LANDUSE_ALIASES,
    DEFAULT_LANDUSE_CSV_ROWS,
    DEFAULT_LANDUSE_VARIABLES,
    DEFAULT_PLACE_REFS,
    DEFAULT_PLACES,
    DEFAULT_SENSOR_ROWS,
    DEFAULT_WATERSHED_PLACE_REFS,
    DEFAULT_WATERSHED_PLACES,
    LANDUSE_SOURCE_ID,
    build_observation,
    make_landuse_csv,
    make_landuse_registry_db,
    make_landuse_source_regions_yaml,
    make_measurements_db,
    make_registry_db,
    make_time_label_conventions_yaml,
    table_content_hash,
)


def _no_exceptions_path(tmp_path):
    return tmp_path / "no_exceptions.yaml"


def _no_conventions_path(tmp_path):
    return tmp_path / "no_conventions.yaml"


def test_normal_case_resolves_all_rows_and_maps_censoring(tmp_path):
    """measurements だけのフィクスチャ（sensor_timeseries は空）で、censoring の
    分岐（D2）と place/region の解決を確認する（既存の回帰テスト）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    all_stats = build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )

    m_stats = all_stats["measurements"]
    assert m_stats["n_observation"] == 3
    assert m_stats["total"] == 3
    # censoring: m1='none'（1.2）, m2='below_lod'（<0.5）, m3='none'（12.3）
    assert m_stats["censoring_counts"] == {"none": 2, "below_lod": 1}
    assert m_stats["zero_imputed_count"] == 1
    assert m_stats["grain_mismatch_count"] == 0
    assert all_stats["sensor_timeseries"]["total"] == 0
    assert all_stats["sensor_timeseries"]["n_observation"] == 0

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = {
        r[0]: r
        for r in conn.execute(
            "SELECT source_row_id, region_id, place_kind, value_num, censoring, censoring_limit "
            "FROM observation WHERE source_table='measurements'"
        )
    }
    conn.close()
    # value_num は censoring='none' のときだけ運ぶ（D2）。below_lod は NULL。
    assert rows["m1"][3] == 1.2  # value_num
    assert rows["m2"][3] is None  # value_num (below_lod)
    assert rows["m2"][4] == "below_lod"  # censoring
    assert rows["m2"][5] == 0.5  # censoring_limit
    # region_id/place_kind はハードコードせず place 経由で解決している。
    assert rows["m1"][1] == "jp-14"  # region_id
    assert rows["m1"][2] == "site"  # place_kind


def test_sensor_rows_are_ingested_with_source_table_and_row_id(tmp_path):
    """`sensor_timeseries` 由来の行が `source_table='sensor_timeseries'` /
    `source_row_id=str(id)` で入り、censoring は常に 'none'・value_raw は
    常に NULL であることを確認する（design.md T3）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)
    make_time_label_conventions_yaml(tmp_path / "conventions.yaml")
    out = tmp_path / "v2.sqlite"

    all_stats = build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out
    )
    s_stats = all_stats["sensor_timeseries"]
    assert s_stats["total"] == len(DEFAULT_SENSOR_ROWS)
    assert s_stats["n_observation"] == len(DEFAULT_SENSOR_ROWS)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT source_table, source_row_id, censoring, value_raw, value_grain, period_grain, "
        "period_start, period_end, period_raw "
        "FROM observation WHERE source_table='sensor_timeseries' ORDER BY CAST(source_row_id AS INT)"
    ).fetchall()
    conn.close()
    assert len(rows) == len(DEFAULT_SENSOR_ROWS)
    for r in rows:
        assert r[0] == "sensor_timeseries"
        assert r[2] == "none"  # censoring は常に 'none'
        assert r[3] is None  # value_raw は常に NULL
    # 日次（TEMP_DAILY、10桁）: period_grain='day'、period_start=period_end=そのまま。
    day_row = rows[0]
    assert day_row[4:9] == ("day", "day", "2020-01-01", "2020-01-01", "2020-01-01")
    # 瞬時（WTEMP、25桁・instant）: 時刻帯を落として period_start=period_end。
    instant_row = [r for r in rows if r[8] == "2020-01-01T00:00:00+09:00"][0]
    assert instant_row[4:9] == (
        "instant", "instant", "2020-01-01T00:00:00", "2020-01-01T00:00:00", "2020-01-01T00:00:00+09:00",
    )
    # 毎時（RAIN、25桁・hour、hour_ending）: period_start=ラベル-1時間。
    hour_row = [r for r in rows if r[8] == "2020-01-01T01:00:00+09:00"][0]
    assert hour_row[4:9] == (
        "hour", "hour", "2020-01-01T00:00:00", "2020-01-01T01:00:00", "2020-01-01T01:00:00+09:00",
    )
    # 「24時」ラベル（2020-01-02T00:00:00+09:00）は前日23時始まりになる（T1の日またぎ）。
    midnight_row = [r for r in rows if r[8] == "2020-01-02T00:00:00+09:00"][0]
    assert midnight_row[4:9] == (
        "hour", "hour", "2020-01-01T23:00:00", "2020-01-02T00:00:00", "2020-01-02T00:00:00+09:00",
    )


def test_hour_grain_without_time_label_convention_raises(tmp_path):
    """value_grain='hour' の出典が time_label_conventions.yaml に宣言されて
    いないと、（PeriodMismatchError の per-row 集計を経由せず）即座に止まる
    （T2）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)
    # 宣言表が空（src_hourly の宣言が無い）。
    empty_conventions = tmp_path / "empty_conventions.yaml"
    empty_conventions.write_text("", encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), empty_conventions, tmp_path / "v2.sqlite"
        )
    from migrate import period as period_mod
    assert isinstance(excinfo.value, period_mod.UnknownTimeLabelConventionError)


def test_time_label_convention_unused_entry_raises(tmp_path):
    """time_label_conventions.yaml のエントリが1件も使われなければ止まる
    （period_exceptions.yaml と同じ流儀）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)  # sensor_timeseries は空
    make_registry_db(registry_db)
    conventions = tmp_path / "conventions.yaml"
    make_time_label_conventions_yaml(conventions)  # src_hourly を宣言するが該当行が無い

    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), conventions, tmp_path / "v2.sqlite"
        )


def test_time_label_convention_expected_row_count_mismatch_raises(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)
    conventions = tmp_path / "conventions.yaml"
    make_time_label_conventions_yaml(
        conventions,
        "src_hourly:\n  convention: hour_ending\n  expected_row_count: 999\n  evidence: テスト\n",
    )

    with pytest.raises(common.MigrationError, match="expected_row_count と実測件数が食い違う"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), conventions, tmp_path / "v2.sqlite"
        )


def test_unresolved_alias_raises_with_count_and_example(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    # "kion" だけを alias として残し、"BOD" を解決不能にする（sensor_timeseries は空）。
    make_measurements_db(measurements_db)
    make_registry_db(
        registry_db,
        aliases=[("measurements", "kion", "src_a", "common:variable:weather.air_temp", "common:unit:degc", None, "day")],
    )

    with pytest.raises(common.MigrationError, match="variable_alias で解決できない"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path),
            tmp_path / "v2.sqlite",
        )


def test_unresolved_place_raises(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(
        registry_db,
        place_refs=[("place_s1", "S1", "sites.site_id")],  # S2 の解決先が無い
    )

    with pytest.raises(common.MigrationError, match="place_source_ref で解決できない"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path),
            tmp_path / "v2.sqlite",
        )


def test_period_mismatch_without_declared_exception_raises(tmp_path):
    """value_grain='day' の alias なのに measured_on が4桁（年度番号）しか無い行は、
    period_exceptions.yaml に宣言が無ければ止まる（design.md D4）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)

    with pytest.raises(common.MigrationError, match="value_grain と period_grain が食い違い"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path),
            tmp_path / "v2.sqlite",
        )


def test_period_mismatch_covered_by_exception_succeeds(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "src_a:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 1\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    all_stats = build_observation(
        tmp_path,
        measurements_db, registry_db, exceptions_yaml, _no_conventions_path(tmp_path), tmp_path / "v2.sqlite"
    )
    m_stats = all_stats["measurements"]
    assert m_stats["n_observation"] == 1
    assert m_stats["grain_mismatch_count"] == 1


def test_exception_entry_never_matched_raises(tmp_path):
    """例外表のエントリが1件も当たらなかったら止まる（腐った例外を放置しない）。"""
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)  # value_grain==period_grain の行しかない
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "never_appears:\n"
        "  period_grain_override: fiscal_year\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, exceptions_yaml, _no_conventions_path(tmp_path), tmp_path / "v2.sqlite"
        )


def test_expected_row_count_mismatch_raises(tmp_path):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(
        measurements_db,
        rows=[("m1", "S1", "2020", "BOD", "src_a", 1.2, "1.2", "mg/L", "公開済", 0, "ref1", "ev1")],
    )
    make_registry_db(registry_db)
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "src_a:\n"
        "  period_grain_override: fiscal_year\n"
        "  expected_row_count: 999\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )

    with pytest.raises(common.MigrationError, match="expected_row_count と実測件数が食い違う"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, exceptions_yaml, _no_conventions_path(tmp_path), tmp_path / "v2.sqlite"
        )


def test_t1_invariant_holds_for_all_grains(tmp_path):
    """T1 不変条件（時刻帯を持たない・date(period_start)が日付部分と一致）が
    書き出した observation の全行（measurements+sensor_timeseries、day/hour/
    instant/year を横断）で成り立つことを確認する。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)
    make_time_label_conventions_yaml(tmp_path / "conventions.yaml")
    out = tmp_path / "v2.sqlite"

    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out
    )
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM observation
        WHERE period_start LIKE '%+%' OR period_start LIKE '%Z%'
           OR period_end LIKE '%+%' OR period_end LIKE '%Z%'
           OR date(period_start) <> substr(period_start, 1, 10)
        """
    ).fetchone()[0]
    conn.close()
    assert bad == 0


def test_below_lod_without_censoring_limit_raises(tmp_path, monkeypatch):
    """/simplify 指摘2: `censoring='below_lod'` なのに `censoring_limit` が
    NULL の行があると、observation の不変条件検証（T1 と同じ場所）で b03 が
    `MigrationError` で止まる——この検証は `observation_agg`（b04）ではなく
    `observation` の書き手（b03）が1回だけ保証する（モジュール docstring
    「T1 不変条件」節参照）。実データでは `censoring.py` の `_parse_limit` が
    below_lod の `censoring_limit` を必ず埋めるため起きないが、将来・別出典の
    取り込み経路がこの前提を破る可能性を想定し、`classify_censoring` を
    モンキーパッチして below_lod の `censoring_limit` を欠落させる
    （`DEFAULT_MEASUREMENTS` の `m2` が `<0.5` の below_lod 行）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    orig_classify_censoring = b03.censoring.classify_censoring

    def broken_classify_censoring(value_raw):
        cens, limit = orig_classify_censoring(value_raw)
        if cens == b03.censoring.CENSORING_BELOW_LOD:
            return cens, None
        return cens, limit

    monkeypatch.setattr(b03.censoring, "classify_censoring", broken_classify_censoring)

    with pytest.raises(common.MigrationError, match="censoring_limit が NULL"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
        )


def test_replace_table_does_not_touch_other_tables(tmp_path):
    """`observation` の作り直しはテーブル単位（`replace_table`）で行われ、
    同じ `v2.sqlite` に既にある別テーブル（将来の `occurrence` 相当）を
    消さない（design.md T3「ファイルごと作り直さない」の直接確認）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    # 先に無関係なテーブルを作っておく。
    pre = sqlite3.connect(str(out))
    pre.execute("CREATE TABLE occurrence_stub (id INTEGER PRIMARY KEY)")
    pre.execute("INSERT INTO occurrence_stub VALUES (1)")
    pre.commit()
    pre.close()

    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM occurrence_stub").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 3
    conn.close()


def test_running_twice_yields_identical_content_hash(tmp_path):
    """決定論: 同じ入力に対して b03 を2回実行すると observation の content_hash が
    バイト一致する（受け入れ条件5の単体テスト版）。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db)
    make_time_label_conventions_yaml(tmp_path / "conventions.yaml")

    out1 = tmp_path / "v2_1.sqlite"
    out2 = tmp_path / "v2_2.sqlite"
    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out1
    )
    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out2
    )

    def fingerprint(path):
        return table_content_hash(path, "observation", ["source_table", "source_row_id"])

    assert fingerprint(out1) == fingerprint(out2)


# ---------------------------------------------------------------------------
# A-1: 検証が全部通ってから本番名に差し替える（受け入れ条件4）
# ---------------------------------------------------------------------------

def _observation_tables_and_rows(out_path):
    """`observation`（本番テーブル）以外に、作業用テーブル（`__building`）が
    残っていないことを見るためのヘルパ。`pipeline_fingerprint`（Issue #37 #1、
    段階間の指紋のメタ表）・`pipeline_input_fingerprint`（Issue #48 PR-0、
    v2 パイプラインの入力＋コードの指紋のメタ表）は本番/作業用の区別とは
    無関係な実装詳細なので除外する（このヘルパの関心事は「本番に正しく
    差し替わったか」だけ）。
    """
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    tables = sorted(
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if r[0] not in (common.PIPELINE_FINGERPRINT_TABLE, common.PIPELINE_INPUT_FINGERPRINT_TABLE)
    )
    rows = conn.execute("SELECT source_row_id FROM observation ORDER BY source_row_id").fetchall()
    conn.close()
    return tables, rows


def test_a1_declaration_failure_preserves_previous_observation(tmp_path):
    """A-1: 1回目を成功させたあと、2回目を宣言表（period_exceptions.yaml）の
    未使用エントリで失敗させる。前回の observation がそのまま残り、作業用
    テーブル（observation__building）も残らない。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )
    before_tables, before_rows = _observation_tables_and_rows(out)
    assert before_tables == ["observation"]

    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        "never_appears:\n"
        "  period_grain_override: fiscal_year\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )
    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, exceptions_yaml, _no_conventions_path(tmp_path), out
        )

    after_tables, after_rows = _observation_tables_and_rows(out)
    assert after_tables == ["observation"], "作業用テーブルが残っている"
    assert after_rows == before_rows, "前回の observation が変わってしまった"


def test_a1_t1_invariant_failure_preserves_previous_observation(tmp_path, monkeypatch):
    """A-1: 1回目を成功させたあと、2回目を T1 不変条件（時刻帯を持たない）
    違反で失敗させる（`period.compute_period` をモンキーパッチして時刻帯
    付きの period_start/period_end を混入させる）。前回の observation が
    そのまま残り、作業用テーブルも残らない。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )
    before_tables, before_rows = _observation_tables_and_rows(out)

    from migrate import period as period_mod

    orig_compute_period = period_mod.compute_period

    def broken_compute_period(*args, **kwargs):
        grain, start, end = orig_compute_period(*args, **kwargs)
        return grain, start + "+09:00", end + "+09:00"

    monkeypatch.setattr(b03.period, "compute_period", broken_compute_period)

    with pytest.raises(common.MigrationError, match="T1"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
        )

    after_tables, after_rows = _observation_tables_and_rows(out)
    assert after_tables == ["observation"], "作業用テーブルが残っている"
    assert after_rows == before_rows, "前回の observation が変わってしまった"


def test_a1_running_twice_successfully_does_not_collide_on_index_name(tmp_path):
    """C-5 の検証用一意インデックスは使い捨て（張った直後に DROP する）。
    固定名の索引を本番テーブルまで残すと2回目の実行が名前衝突で壊れるはず
    ——2回連続で成功することを確認して、そうなっていないことを示す。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    make_registry_db(registry_db)
    out = tmp_path / "v2.sqlite"

    build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )
    # 2回目も例外を投げず成功すること（索引名の衝突があればここで
    # sqlite3.OperationalError になる）。
    all_stats = build_observation(
        tmp_path,
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )
    assert all_stats["measurements"]["n_observation"] == 3
    tables, _ = _observation_tables_and_rows(out)
    assert tables == ["observation"]


# ---------------------------------------------------------------------------
# A-2: 重複行は IntegrityError ではなく MigrationError（件数・実例つき）
# ---------------------------------------------------------------------------

def test_a2_duplicate_rows_raise_migration_error_with_count_and_examples(tmp_path):
    """A-2: `source_row_id` が複数行にマッチする（alias の解決が「関数」で
    なくなっている）と、`sqlite3.IntegrityError`（以前は数えた後も挿入を
    試みて主キー違反で落ちていた）ではなく、件数と実例を含む
    `common.MigrationError` になる。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db)
    # BOD/src_a に2つ目の alias を足し、m1/m2（どちらも BOD/src_a）を
    # JOIN で2行にファンアウトさせる（本物の重複行ではなく、alias の解決が
    # 「関数」でなくなるケース。b03 のモジュール docstring 参照）。
    aliases = list(DEFAULT_ALIASES) + [
        ("measurements", "BOD", "src_a", "common:variable:water.bod2", "common:unit:mg_per_l", None, "day"),
    ]
    make_registry_db(registry_db, aliases=aliases)

    with pytest.raises(common.MigrationError, match=r"source_row_id が複数行にマッチした.*2件.*m1.*m2"):
        build_observation(
            tmp_path,
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path),
            tmp_path / "v2.sqlite",
        )


# ---------------------------------------------------------------------------
# P-1b: 土地利用（`_ingest_landuse`）
# ---------------------------------------------------------------------------

def test_build_and_write_observation_default_landuse_args_point_at_module_constants():
    """コードレビュー指摘10: `source_regions_yaml`/`landuse_csv` を省略した
    ときに使われる既定値が、`main()` が明示的に渡す値と同じ
    `DEFAULT_SOURCE_REGIONS_YAML`/`DEFAULT_LANDUSE_CSV`（モジュール定数）で
    あることを確認する。`None` 番兵＋関数内で解決する設計をやめ、他の3引数
    （`exceptions_yaml` 等）と同じ素のデフォルト引数に戻した結果、この
    「引数を省略したときの経路」自体はシグネチャの既定値を見るだけで検証
    できる（本物の CSV/YAML を実際に読みに行く必要は無い——原本の無い
    環境でも実行できる）。
    """
    sig = inspect.signature(b03.build_and_write_observation)
    assert sig.parameters["source_regions_yaml"].default == b03.DEFAULT_SOURCE_REGIONS_YAML
    assert sig.parameters["landuse_csv"].default == b03.DEFAULT_LANDUSE_CSV


def _build_landuse(tmp_path, registry_db, landuse_csv=None, source_regions_yaml=None):
    """土地利用を実際に検証するテスト用。`landuse_csv`/`source_regions_yaml`
    （書き込み済みのパス）を明示的に渡す——`build_observation`（行/テキストから
    その場でフィクスチャを作る、既定は「0行」の共通ヘルパ）とは違うインター
    フェースなので、ここでは `b03.build_and_write_observation` を直接呼ぶ。
    """
    measurements_db = tmp_path / "ryuiki.sqlite"
    make_measurements_db(measurements_db, rows=[])
    if landuse_csv is None:
        landuse_csv = tmp_path / "landuse.csv"
        make_landuse_csv(landuse_csv)
    if source_regions_yaml is None:
        source_regions_yaml = tmp_path / "source_regions.yaml"
        make_landuse_source_regions_yaml(source_regions_yaml)
    out = tmp_path / "v2.sqlite"
    all_stats = b03.build_and_write_observation(
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out,
        source_regions_yaml, landuse_csv,
    )
    return out, all_stats


def test_landuse_row_makes_two_observation_rows_area_and_n_cells(tmp_path):
    """P-1b オーナー決定1: CSVの1行（watershed×year×landuse_code）から、
    区分の面積（area_km2）とセル数（n_cells）という2つの observation 行が
    作られる。region は source_regions.yaml（consumer='observation'）から、
    place は watershed の place_source_ref から解決する（ハードコードしない）。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    out, all_stats = _build_landuse(tmp_path, registry_db)

    # `all_stats`/`observation.source_table` のキーは b03 側の固定ラベル
    # `b03.LANDUSE_SOURCE_ID`（実データでは CSV の `source_id` 列と同じ文字列に
    # なるが、コード上は別物——CSV の `source_id`（`LANDUSE_SOURCE_ID`、
    # このフィクスチャではあえて違う値にしてある）は alias/region の解決キー
    # としてだけ使われる。混同していないことをこのテスト自体が示す）。
    stats = all_stats[b03.LANDUSE_SOURCE_ID]
    assert stats["total"] == len(DEFAULT_LANDUSE_CSV_ROWS)
    assert stats["n_observation"] == len(DEFAULT_LANDUSE_CSV_ROWS) * 2

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = {
        r[0]: r
        for r in conn.execute(
            "SELECT source_row_id, region_id, place_id, place_kind, variable_id, obs_stat, unit_id, "
            "value_grain, period_grain, period_start, period_end, period_raw, value_num, censoring, "
            "unit_raw, value_raw, source_ref "
            f"FROM observation WHERE source_table='{b03.LANDUSE_SOURCE_ID}'"
        )
    }
    conn.close()
    assert len(rows) == 10

    # CSV 1行目: W1, 2006年版, code='1'（田）, area_km2=1.5, n_cells=10。
    area = rows["1:area_km2"]
    (
        _sid, region_id, place_id, place_kind, variable_id, obs_stat, unit_id,
        value_grain, period_grain, period_start, period_end, period_raw, value_num,
        censoring_value, unit_raw, value_raw, source_ref,
    ) = area
    assert region_id == "jp-14"  # place.region_id 経由ではなく source_regions.yaml から
    assert place_id == "place_w1"
    assert place_kind == "watershed"
    assert variable_id == "common:variable:landuse.paddy"
    assert obs_stat == "sum"
    assert unit_id == "common:unit:km2"
    assert value_grain == "year"
    assert period_grain == "year"
    assert (period_start, period_end) == ("2006-01-01", "2006-12-31")
    assert period_raw == "2006"
    assert value_num == 1.5
    assert censoring_value == "none"
    assert unit_raw is None
    assert value_raw is None
    assert source_ref == "ref2006"

    n_cells = rows["1:n_cells"]
    assert n_cells[4] == "common:variable:landuse.paddy_n_cells"
    assert n_cells[6] == "common:unit:count"
    assert n_cells[12] == 10.0

    # 5行目: W2, 2016年版, code='0100'（田。2006の code='1' と同じ variable_id
    # を共有する——landuse_change が年をまたいで同一区分として比較できるように
    # するため。P-1b オーナー決定2）。
    area_2016 = rows["5:area_km2"]
    assert area_2016[4] == "common:variable:landuse.paddy"
    assert area_2016[9:12] == ("2016-01-01", "2016-12-31", "2016")


def test_landuse_unresolved_watershed_raises(tmp_path):
    """CSV の watershed_id が place_source_ref に無ければ、黙って捨てず
    MigrationError で止まる（unresolved_place_count）。"""
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "UNKNOWN_WS", "OLD9", "水系9", "1", "田", 1, 0.1),
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 1\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    with pytest.raises(common.MigrationError, match="place_source_ref で解決できない"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_unresolved_alias_raises(tmp_path):
    """CSV の landuse_code_raw に対応する variable_alias が無ければ
    MigrationError で止まる（unresolved_alias_count）。"""
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        # code='9'（幹線交通用地相当）は _make_landuse_registry_db が登録していない。
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "9", "幹線交通用地", 1, 0.1),
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 1\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    with pytest.raises(common.MigrationError, match="variable_alias で解決できない"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_duplicate_business_key_raises(tmp_path):
    """P-1b コードレビュー指摘2: `source_row_id`（CSV の行番号由来）は行ごとに
    必ず一意なので、それを鍵にした重複検査は発火しない。本当に検出すべきは
    `(watershed_id, data_year, landuse_code, 種別)` という業務キーの重複——
    同じ組が2行あると、キューブが黙って平均してしまう（`n_cells` は
    切り捨てまで起きる）。ここでは W1/2006/code='1' を2行にして検出させる。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 10, 1.5),
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 20, 2.5),  # 重複
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 2\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    with pytest.raises(common.MigrationError, match="複数行にマッチした"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_value_grain_mismatch_raises(tmp_path):
    """P-1b コードレビュー指摘6: `compute_period` に固定文字列 `"year"` では
    なく alias の `value_grain` をそのまま渡すため、4桁の年（`data_year`）に
    対して `value_grain` が `'year'`/`'fiscal_year'` 以外（かつ
    `period_exceptions.yaml` に宣言も無い）だと、他の2出典と同じように
    `PeriodMismatchError` 経由で止まる。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(
        registry_db,
        aliases=DEFAULT_ALIASES + [
            ("nlni_l03b_landuse_by_watershed@2006", "1:area_km2", LANDUSE_SOURCE_ID,
             "common:variable:landuse.paddy", "common:unit:km2", "sum", "day"),  # year/fiscal_year 以外
            ("nlni_l03b_landuse_by_watershed@2006", "1:n_cells", LANDUSE_SOURCE_ID,
             "common:variable:landuse.paddy_n_cells", "common:unit:count", "sum", "day"),
        ],
        places=DEFAULT_PLACES + DEFAULT_WATERSHED_PLACES,
        place_refs=DEFAULT_PLACE_REFS + DEFAULT_WATERSHED_PLACE_REFS,
        variables=DEFAULT_LANDUSE_VARIABLES,
    )
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 10, 1.5),
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 1\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    with pytest.raises(common.MigrationError, match="value_grain"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_declared_grain_mismatch_is_counted(tmp_path):
    """/code-review「_process_row を分割」指摘1: `_ingest_landuse` は
    `_process_row` を経由しないため、以前は `grain_mismatch_count` の計上
    だけが構造的に欠けていた（レポートは3出典共通で出すのに、土地利用だけ
    常に0になっていた）。`_resolve_and_compute_period`（3出典で共有）経由に
    なったいま、`period_exceptions.yaml` でカバーされた grain の食い違いが
    土地利用でもちゃんと計上され、かつ（宣言があるので）例外にはならない
    ことを確認する（`test_landuse_value_grain_mismatch_raises`——宣言が無い
    場合——と対、`test_period_mismatch_covered_by_exception_succeeds`——
    measurements 版——とも対）。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(
        registry_db,
        aliases=DEFAULT_ALIASES + [
            ("nlni_l03b_landuse_by_watershed@2006", "1:area_km2", LANDUSE_SOURCE_ID,
             "common:variable:landuse.paddy", "common:unit:km2", "sum", "day"),  # year/fiscal_year 以外
            ("nlni_l03b_landuse_by_watershed@2006", "1:n_cells", LANDUSE_SOURCE_ID,
             "common:variable:landuse.paddy_n_cells", "common:unit:count", "sum", "day"),
        ],
        places=DEFAULT_PLACES + DEFAULT_WATERSHED_PLACES,
        place_refs=DEFAULT_PLACE_REFS + DEFAULT_WATERSHED_PLACE_REFS,
        variables=DEFAULT_LANDUSE_VARIABLES,
    )
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        (LANDUSE_SOURCE_ID, "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 10, 1.5),
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 1\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    # value_grain='day' に対する宣言を足す（period_grain_override='year'）。
    # area_km2/n_cells の2候補がどちらもこの1エントリを使うため
    # expected_row_count=2。
    exceptions_yaml = tmp_path / "exceptions.yaml"
    exceptions_yaml.write_text(
        f"{LANDUSE_SOURCE_ID}:\n"
        "  period_grain_override: year\n"
        "  expected_row_count: 2\n"
        "  reason: テスト\n"
        "  restoration_plan: テスト\n",
        encoding="utf-8",
    )
    measurements_db = tmp_path / "ryuiki.sqlite"
    make_measurements_db(measurements_db, rows=[])
    out = tmp_path / "v2.sqlite"

    all_stats = b03.build_and_write_observation(
        measurements_db, registry_db, exceptions_yaml, _no_conventions_path(tmp_path), out,
        yaml_path, csv_path,
    )

    stats = all_stats[b03.LANDUSE_SOURCE_ID]
    assert stats["n_observation"] == 2  # area_km2 + n_cells とも例外でカバーされ成功
    # 修正前はここが常に 0 だった（_ingest_landuse が _process_row を経由せず、
    # grain_mismatch_count を計上する経路自体が無かったため）。
    assert stats["grain_mismatch_count"] == 2

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    rows = conn.execute(
        f"SELECT value_grain, period_grain FROM observation "
        f"WHERE source_table='{b03.LANDUSE_SOURCE_ID}'"
    ).fetchall()
    conn.close()
    assert len(rows) == 2
    for value_grain, period_grain in rows:
        assert value_grain == "day"
        assert period_grain == "year"


def test_landuse_unknown_source_id_raises_immediately(tmp_path):
    """CSV の source_id が source_regions.yaml に無ければ、per-row の集計を
    経由せず即座に `UnknownSourceRegionError` で止まる
    （`scripts/b06_build_occurrence.py` の `_ingest` と同じ判断）。"""
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[
        ("unknown_source", "ref2006", 2006, "W1", "OLD1", "水系1", "1", "田", 10, 1.5),
    ])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(yaml_path, text="sources: {}\nregions: {}\n")
    with pytest.raises(source_regions.UnknownSourceRegionError, match="unknown_source"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_unused_source_declaration_raises(tmp_path):
    """source_regions.yaml（consumer='observation'）に宣言されているのに
    CSV に1行も現れない source_id は「未使用宣言」として止まる
    （period.declaration_problems 経由。scripts/migrate/period_exceptions.yaml
    と同じ流儀）。"""
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    csv_path = tmp_path / "landuse.csv"
    make_landuse_csv(csv_path, rows=[])
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(yaml_path)  # LANDUSE_SOURCE_ID を宣言するが、CSV は空
    with pytest.raises(common.MigrationError, match="1件も該当しなかった"):
        _build_landuse(tmp_path, registry_db, landuse_csv=csv_path, source_regions_yaml=yaml_path)


def test_landuse_expected_row_count_mismatch_raises(tmp_path):
    """source_regions.yaml の expected_row_count と実測件数が食い違えば止まる。"""
    registry_db = tmp_path / "registry.sqlite"
    make_landuse_registry_db(registry_db)
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(
        yaml_path,
        text=(
            "sources:\n"
            f"  {LANDUSE_SOURCE_ID}:\n"
            "    region_id: jp-14\n"
            "    consumer: observation\n"
            "    expected_row_count: 999\n"
            "    evidence: テスト用\n"
            "regions:\n  jp-14:\n    utc_offset: \"+09:00\"\n    evidence: テスト用\n"
        ),
    )
    with pytest.raises(common.MigrationError, match="expected_row_count と実測件数が食い違う"):
        _build_landuse(tmp_path, registry_db, source_regions_yaml=yaml_path)


def test_landuse_does_not_affect_measurements_rows(tmp_path):
    """土地利用の取り込みが既存の measurements/sensor_timeseries 由来の行を
    一切変えないことを確認する（P-1b 受け入れ基準2）。"""
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(
        registry_db,
        aliases=DEFAULT_ALIASES + DEFAULT_LANDUSE_ALIASES,
        places=DEFAULT_PLACES + DEFAULT_WATERSHED_PLACES,
        place_refs=DEFAULT_PLACE_REFS + DEFAULT_WATERSHED_PLACE_REFS,
        variables=DEFAULT_LANDUSE_VARIABLES,
    )
    measurements_db = tmp_path / "ryuiki.sqlite"
    make_measurements_db(measurements_db)  # 既定の measurements 3行を使う
    landuse_csv = tmp_path / "landuse.csv"
    make_landuse_csv(landuse_csv)
    yaml_path = tmp_path / "source_regions.yaml"
    make_landuse_source_regions_yaml(yaml_path)
    out = tmp_path / "v2.sqlite"

    all_stats = b03.build_and_write_observation(
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out,
        yaml_path, landuse_csv,
    )
    assert all_stats["measurements"]["n_observation"] == 3
    assert all_stats[b03.LANDUSE_SOURCE_ID]["n_observation"] == len(DEFAULT_LANDUSE_CSV_ROWS) * 2

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    n_measurements = conn.execute(
        "SELECT COUNT(*) FROM observation WHERE source_table='measurements'"
    ).fetchone()[0]
    n_landuse = conn.execute(
        f"SELECT COUNT(*) FROM observation WHERE source_table='{b03.LANDUSE_SOURCE_ID}'"
    ).fetchone()[0]
    conn.close()
    assert n_measurements == 3
    assert n_landuse == len(DEFAULT_LANDUSE_CSV_ROWS) * 2
