"""scripts/b03_build_observation.py の統合テスト。

本物の `data/db/ryuiki.sqlite`/`registry.sqlite`（828MB・52,215行）を要さず、
`scripts/tests/migrate_fixtures.py` の小さな自作 sqlite だけで完結する。
"""
import sqlite3

import pytest

import b03_build_observation as b03
from migrate import common
from reconcile import common as reconcile_common
from reconcile import datasource

from .migrate_fixtures import (
    DEFAULT_ALIASES,
    DEFAULT_SENSOR_ROWS,
    make_measurements_db,
    make_registry_db,
    make_time_label_conventions_yaml,
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

    all_stats = b03.build_and_write_observation(
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

    all_stats = b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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

    all_stats = b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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

    b03.build_and_write_observation(
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

    b03.build_and_write_observation(
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
    b03.build_and_write_observation(
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out1
    )
    b03.build_and_write_observation(
        measurements_db, registry_db, _no_exceptions_path(tmp_path), tmp_path / "conventions.yaml", out2
    )

    def fingerprint(path):
        conn = reconcile_common.open_readonly(path)
        src = datasource.SqliteSource(conn)
        columns = src.columns("observation")
        numeric = reconcile_common.numeric_columns_of(conn, "observation", columns)
        fp = reconcile_common.compute_fingerprint(
            src, "observation", columns, ["source_table", "source_row_id"], numeric
        )
        conn.close()
        return fp["content_hash"]

    assert fingerprint(out1) == fingerprint(out2)


# ---------------------------------------------------------------------------
# A-1: 検証が全部通ってから本番名に差し替える（受け入れ条件4）
# ---------------------------------------------------------------------------

def _observation_tables_and_rows(out_path):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
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

    b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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

    b03.build_and_write_observation(
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
        b03.build_and_write_observation(
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

    b03.build_and_write_observation(
        measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path), out
    )
    # 2回目も例外を投げず成功すること（索引名の衝突があればここで
    # sqlite3.OperationalError になる）。
    all_stats = b03.build_and_write_observation(
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
        b03.build_and_write_observation(
            measurements_db, registry_db, _no_exceptions_path(tmp_path), _no_conventions_path(tmp_path),
            tmp_path / "v2.sqlite",
        )
