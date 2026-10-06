"""系譜（pipeline_fingerprint.inputs）の自動生成（Issue #45）。`LineageTracker` が
実際の読み取りから `inputs` を作り、宣言外の JOIN を足せば系譜が自動で追従し、
検証していない上流を読めば止まることを、小さいフィクスチャ DB で固定する。
"""
from __future__ import annotations

import sqlite3

import pytest

from migrate import common

HINT = "上流を作り直すこと。"


def _make_up_tables(path, names=("up", "up2")):
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    for i, name in enumerate(names):
        conn.execute(f"CREATE TABLE {name} (k INTEGER, v INTEGER)")
        conn.execute(f"INSERT INTO {name} VALUES (1, {i})")
        common.record_stage_fingerprint(conn, name)
    conn.commit()
    return conn


def _build_down(conn, lineage, select_sql, table="down"):
    with common.staged_table(
        conn, table, "CREATE TABLE {table} (k INTEGER, v INTEGER)", lineage=lineage,
    ) as staging:
        conn.execute(f'INSERT INTO "{staging}" {select_sql}')


def test_inputs_are_generated_from_actual_reads_and_follow_a_new_join(tmp_path):
    """読み取りを1つ足すだけで（宣言は触らない）系譜が増える。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    up2_fp = common.read_recorded_fingerprint(conn, "up2")

    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT k, v FROM up")
    lin.release()
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}

    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    lin.verify("up2", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT up.k, up2.v FROM up JOIN up2 ON up2.k = up.k")
    lin.release()
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp, "up2": up2_fp}
    conn.close()


def test_downstream_is_stale_after_upstream_is_rewritten(tmp_path):
    """上流の出力を書き換えて再記録すると、再構築していない下流は古いと判定される。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT k, v FROM up")
    lin.release()
    common.assert_stage_fingerprint_fresh(conn, "down", rebuild_hint=HINT, upstream_schemas={})

    conn.execute("UPDATE up SET v = 99")
    common.record_stage_fingerprint(conn, "up")
    conn.commit()
    with pytest.raises(common.MigrationError, match="作り直された後"):
        common.assert_stage_fingerprint_fresh(conn, "down", rebuild_hint=HINT, upstream_schemas={})
    conn.close()


def test_unverified_join_stops_and_keeps_the_previous_table(tmp_path):
    """verify していない上流を JOIN すると止まり、前回の本番テーブル・指紋は残る
    （わざと壊すと止まることの固定）。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT k, v FROM up")
    lin.release()
    before = (conn.execute("SELECT * FROM down").fetchall(), common.read_recorded_inputs(conn, "down"))

    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)  # up2 は検証しない
    with pytest.raises(common.MigrationError, match=r"main\.up2"):
        _build_down(conn, lin, "SELECT up.k, up2.v + 100 FROM up JOIN up2 ON up2.k = up.k")
    assert (conn.execute("SELECT * FROM down").fetchall(), common.read_recorded_inputs(conn, "down")) == before
    assert "down__building" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()


def _make_registry_like(path):
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute("CREATE TABLE taxon (k INTEGER)")
    conn.execute("INSERT INTO taxon VALUES (1)")
    conn.execute("CREATE TABLE other (k INTEGER)")
    conn.commit()
    conn.close()


def test_attached_registry_reads_become_external_inputs_and_undeclared_attach_stops(tmp_path):
    conn = _make_up_tables(tmp_path / "v.sqlite")
    _make_registry_like(tmp_path / "reg.sqlite")
    common.attach_readonly(conn, tmp_path / "reg.sqlite", "registry")
    sql = "SELECT up.k, up.v FROM up JOIN registry.taxon t ON t.k = up.k"

    lin = common.LineageTracker(conn, external={"registry": "sha256:reg"})
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, sql)
    lin.release()
    inputs = common.read_recorded_inputs(conn, "down")
    assert inputs["ext:registry.taxon"] == "sha256:reg"
    # ext: の来歴は系譜の再帰検証（pipeline_fingerprint の行を探す）の対象外。
    common.assert_stage_fingerprint_fresh(conn, "down", rebuild_hint=HINT, upstream_schemas={})

    # 宣言の無い ATTACH 先を読めば止まる。
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    with pytest.raises(common.MigrationError, match=r"registry\.taxon"):
        _build_down(conn, lin, sql)

    # external が表ごとの dict のとき、宣言の無い表を読めば止まる。
    lin = common.LineageTracker(conn, external={"registry": {"taxon": "p1"}})
    lin.verify("up", rebuild_hint=HINT)
    with pytest.raises(common.MigrationError, match=r"registry\.other"):
        _build_down(conn, lin, "SELECT up.k, up.v FROM up JOIN registry.other o ON o.k = up.k")
    conn.close()


def test_lineage_is_per_output_table_after_reset(tmp_path):
    """同じ段で2つ作るとき、`reset()` で出力ごとに読んだものだけが入る。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    up2_fp = common.read_recorded_fingerprint(conn, "up2")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    lin.verify("up2", rebuild_hint=HINT)
    lin.reset()
    _build_down(conn, lin, "SELECT k, v FROM up", table="d1")
    lin.reset()
    _build_down(conn, lin, "SELECT k, v FROM up2", table="d2")
    lin.release()
    assert common.read_recorded_inputs(conn, "d1") == {"up": up_fp}
    assert common.read_recorded_inputs(conn, "d2") == {"up2": up2_fp}
    conn.close()


def test_reads_through_temp_tables_and_views_are_attributed_to_real_tables(tmp_path):
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    conn.execute("CREATE TEMP TABLE snap AS SELECT k, v FROM up")
    conn.execute("CREATE TEMP VIEW vw AS SELECT k, v FROM snap")
    _build_down(conn, lin, "SELECT k, v FROM vw")
    lin.release()
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}
    conn.close()

    # 検証していない表を TEMP TABLE 経由で読んでも止まる。
    conn = sqlite3.connect(f"file:{tmp_path / 'v.sqlite'}", uri=True)
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    conn.execute("CREATE TEMP TABLE snap2 AS SELECT k, v FROM up2")
    with pytest.raises(common.MigrationError, match=r"main\.up2"):
        _build_down(conn, lin, "SELECT k, v FROM snap2")
    conn.close()


def test_watched_work_connection_reads_are_merged_and_must_be_declared(tmp_path):
    """b03/b06 のように別の作業用接続が原本・registry を読む場合。"""
    conn = sqlite3.connect(f"file:{tmp_path / 'out.sqlite'}", uri=True)
    _make_registry_like(tmp_path / "reg.sqlite")
    lin = common.LineageTracker(conn)
    work = sqlite3.connect(":memory:", uri=True)
    common.attach_readonly(work, tmp_path / "reg.sqlite", "reg")
    lin.watch(work, external={"reg": "sha256:reg"})
    work.execute("SELECT * FROM reg.taxon").fetchall()
    _build_down(conn, lin, "SELECT 1, 2")
    assert common.read_recorded_inputs(conn, "down") == {"ext:reg.taxon": "sha256:reg"}

    common.attach_readonly(work, tmp_path / "reg.sqlite", "stray")
    lin2 = common.LineageTracker(conn)
    lin2.watch(work, external={"reg": "sha256:reg"})
    work.execute("SELECT * FROM stray.taxon").fetchall()
    with pytest.raises(common.MigrationError, match=r"stray\.taxon"):
        _build_down(conn, lin2, "SELECT 1, 2")
    work.close()
    conn.close()


def test_base_table_without_upstream_reads_gets_empty_lineage(tmp_path):
    conn = sqlite3.connect(f"file:{tmp_path / 'out.sqlite'}", uri=True)
    lin = common.LineageTracker(conn)
    _build_down(conn, lin, "SELECT 1, 2")
    lin.release()
    assert common.read_recorded_inputs(conn, "down") == {}
    conn.close()
