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


def _build_down(conn, lineage, select_sql, table="down", before=None, begin=False):
    with lineage:
        if before is not None:
            before()
        lineage.begin_output() if begin else None
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
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}

    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    lin.verify("up2", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT up.k, up2.v FROM up JOIN up2 ON up2.k = up.k")
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp, "up2": up2_fp}
    conn.close()


def test_downstream_is_stale_after_upstream_is_rewritten(tmp_path):
    """上流の出力を書き換えて再記録すると、再構築していない下流は古いと判定される。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT k, v FROM up")
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

    lin = common.LineageTracker(conn, external={"registry": common.ExternalSource("registry", lambda _t: "sha256:reg")})
    lin.verify("up", rebuild_hint=HINT)
    _build_down(conn, lin, sql)
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
    lin = common.LineageTracker(conn, external={"registry": common.ExternalSource("registry", {"taxon": "p1"}.get)})
    lin.verify("up", rebuild_hint=HINT)
    with pytest.raises(common.MigrationError, match=r"registry\.other"):
        _build_down(conn, lin, "SELECT up.k, up.v FROM up JOIN registry.other o ON o.k = up.k")
    conn.close()


def test_lineage_is_per_output_table_when_the_same_tracker_is_reentered(tmp_path):
    """同じ段で2つ作るとき、同じ tracker に出力ごとに入り直せば、その出力が読んだものだけが入る。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    up2_fp = common.read_recorded_fingerprint(conn, "up2")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    lin.verify("up2", rebuild_hint=HINT)
    _build_down(conn, lin, "SELECT k, v FROM up", table="d1")
    _build_down(conn, lin, "SELECT k, v FROM up2", table="d2")
    assert common.read_recorded_inputs(conn, "d1") == {"up": up_fp}
    assert common.read_recorded_inputs(conn, "d2") == {"up2": up2_fp}
    conn.close()


def test_everything_read_after_the_stage_head_is_in_lineage_even_before_staged_table(tmp_path):
    """`with lineage:`（段の先頭）以降の読み取りは、staged_table の前のものも全部載る。
    `begin_output()` を呼べば、そこまでの読み取りは別の出力のものとして切り離される。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    up2_fp = common.read_recorded_fingerprint(conn, "up2")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    lin.verify("up2", rebuild_hint=HINT)
    _build_down(
        conn, lin, "SELECT k, v FROM up", before=lambda: conn.execute("SELECT * FROM up2").fetchall(),
    )
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp, "up2": up2_fp}
    _build_down(
        conn, lin, "SELECT k, v FROM up", table="d2", begin=True,
        before=lambda: conn.execute("SELECT * FROM up2").fetchall(),
    )
    assert common.read_recorded_inputs(conn, "d2") == {"up": up_fp}
    conn.close()


def test_verify_is_idempotent(tmp_path):
    conn = _make_up_tables(tmp_path / "v.sqlite")
    lin = common.LineageTracker(conn)
    first = lin.verify("up", rebuild_hint=HINT)
    conn.execute("UPDATE up SET v = 99")  # 2回目は再検証せず覚えた値を返す
    assert lin.verify("up", rebuild_hint=HINT) == first
    conn.close()


def test_reads_through_temp_tables_and_views_are_attributed_to_real_tables(tmp_path):
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)

    def make_temp():
        conn.execute("CREATE TEMP TABLE snap AS SELECT k, v FROM up")
        conn.execute("CREATE TEMP VIEW vw AS SELECT k, v FROM snap")

    _build_down(conn, lin, "SELECT k, v FROM vw", before=make_temp)
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}
    conn.close()

    # 検証していない表を TEMP TABLE 経由で読んでも止まる。
    conn = sqlite3.connect(f"file:{tmp_path / 'v.sqlite'}", uri=True)
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    with pytest.raises(common.MigrationError, match=r"main\.up2"):
        _build_down(
            conn, lin, "SELECT k, v FROM snap2",
            before=lambda: conn.execute("CREATE TEMP TABLE snap2 AS SELECT k, v FROM up2"),
        )
    conn.close()


def test_unverified_read_is_not_hidden_by_drop_rename_or_count_only_read(tmp_path):
    """読んでから DROP/RENAME しても、列を読まない読み取り（COUNT(*)）でも、
    宣言漏れの読み取りは素通りしない（resolve は表の実在を見ない）。"""
    cases = {
        "drop": lambda c: (c.execute("CREATE TABLE scratch AS SELECT k, v FROM up2"), c.execute("DROP TABLE scratch")),
        "rename": lambda c: (
            c.execute("CREATE TABLE scratch AS SELECT k, v FROM up2"), c.execute("ALTER TABLE scratch RENAME TO scratch2"),
        ),
        "count_only": lambda c: c.execute("SELECT COUNT(*) FROM up2").fetchall(),
    }
    for name, action in cases.items():
        conn = _make_up_tables(tmp_path / f"{name}.sqlite")
        lin = common.LineageTracker(conn)
        lin.verify("up", rebuild_hint=HINT)
        with pytest.raises(common.MigrationError, match=r"main\.up2"):
            _build_down(conn, lin, "SELECT k, v FROM up", before=lambda c=conn, a=action: a(c))
        conn.close()


def test_temp_table_created_in_the_stage_and_read_by_count_only_is_ignored(tmp_path):
    """段の中で作った TEMP 表を COUNT(*) だけで読んでも（db_name が None で報告される）入力扱いにならない。"""
    conn = _make_up_tables(tmp_path / "v.sqlite")
    up_fp = common.read_recorded_fingerprint(conn, "up")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)

    def before():
        conn.execute("CREATE TEMP TABLE ids (cid INTEGER PRIMARY KEY)")
        conn.execute("SELECT COUNT(*) FROM ids").fetchall()
        conn.execute("DROP TABLE ids")

    _build_down(conn, lin, "SELECT k, v FROM up", before=before)
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}
    conn.close()


def test_authorizer_is_released_even_when_the_block_raises(tmp_path):
    conn = _make_up_tables(tmp_path / "v.sqlite")
    lin = common.LineageTracker(conn)
    lin.verify("up", rebuild_hint=HINT)
    with pytest.raises(RuntimeError):
        with lin:
            raise RuntimeError("boom")
    conn.execute("SELECT * FROM up2").fetchall()  # authorizer が残っていても許可されるだけだが、解除後も動く
    assert lin._sources[0].conn is conn and not lin._entered
    conn.close()


def test_lineage_key_does_not_depend_on_the_attach_alias(tmp_path):
    """registry を別の別名で ATTACH しても、系譜のキーは論理名（ext:registry.taxon）のまま。"""
    _make_registry_like(tmp_path / "reg.sqlite")
    keys = []
    for alias in ("registry", "reg"):
        conn = _make_up_tables(tmp_path / f"v_{alias}.sqlite")
        common.attach_readonly(conn, tmp_path / "reg.sqlite", alias)
        lin = common.LineageTracker(
            conn, external={alias: common.ExternalSource("registry", lambda _t: "sha256:reg")},
        )
        lin.verify("up", rebuild_hint=HINT)
        _build_down(conn, lin, f"SELECT up.k, up.v FROM up JOIN {alias}.taxon t ON t.k = up.k")
        keys.append(set(common.read_recorded_inputs(conn, "down")))
        conn.close()
    assert keys[0] == keys[1] == {"up", "ext:registry.taxon"}


def test_watched_work_connection_reads_are_merged_and_must_be_declared(tmp_path):
    """b03/b06 のように別の作業用接続が原本・registry を読む場合。宣言の無い ATTACH は必ず止まる
    （primary の verified に同名の表があっても落ちない）。"""
    conn = sqlite3.connect(f"file:{tmp_path / 'out.sqlite'}", uri=True)
    _make_registry_like(tmp_path / "reg.sqlite")
    work = sqlite3.connect(":memory:", uri=True)
    common.attach_readonly(work, tmp_path / "reg.sqlite", "reg")
    common.attach_readonly(work, tmp_path / "reg.sqlite", "stray")
    declared = {"reg": common.ExternalSource("registry", lambda _t: "sha256:reg")}

    lin = common.LineageTracker(conn)

    def read_declared():
        lin.watch(work, external=declared)
        work.execute("SELECT * FROM reg.taxon").fetchall()

    _build_down(conn, lin, "SELECT 1, 2", before=read_declared)
    assert common.read_recorded_inputs(conn, "down") == {"ext:registry.taxon": "sha256:reg"}

    def read_stray():
        lin.watch(work, external=declared)
        work.execute("SELECT * FROM stray.taxon").fetchall()

    with pytest.raises(common.MigrationError, match=r"stray\.taxon"):
        _build_down(conn, lin, "SELECT 1, 2", before=read_stray)

    # primary 側で同名の表を verify していても、作業用接続の宣言外 ATTACH は通らない。
    up = _make_up_tables(tmp_path / "v.sqlite", names=("taxon",))
    lin3 = common.LineageTracker(up)
    lin3.verify("taxon", rebuild_hint=HINT)

    def read_stray_again():
        lin3.watch(work, external=declared)
        work.execute("SELECT * FROM stray.taxon").fetchall()

    with pytest.raises(common.MigrationError, match=r"stray\.taxon"):
        _build_down(up, lin3, "SELECT 1, 2", before=read_stray_again)
    work.close()
    conn.close()
    up.close()


def test_ryuiki_external_proxies_only_the_tables_that_were_read_and_rejects_undeclared(tmp_path):
    db = tmp_path / "ryuiki.sqlite"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE sites (a)")
    c.execute("INSERT INTO sites VALUES (1)")
    c.execute("CREATE TABLE other (a)")
    c.commit()
    c.close()
    ext = common.ryuiki_external(db)
    assert ext.label == "ryuiki"
    assert ext.resolve("sites") == "count=1;max_rowid=1"
    assert ext.resolve("measurements") == "absent"  # 宣言済みだが無い表
    assert ext.resolve("other") is None  # 宣言外
    assert common.registry_external(tmp_path / "no.sqlite").resolve("taxon") == "absent"


def test_base_table_without_upstream_reads_gets_empty_lineage(tmp_path):
    conn = sqlite3.connect(f"file:{tmp_path / 'out.sqlite'}", uri=True)
    lin = common.LineageTracker(conn)
    _build_down(conn, lin, "SELECT 1, 2")
    assert common.read_recorded_inputs(conn, "down") == {}
    conn.close()
