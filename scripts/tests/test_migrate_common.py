"""scripts/migrate/common.py の単体テスト（`staged_table`）。

`scripts/tests/test_common.py` は `scripts/reconcile/common.py`（同名だが別モジュール）の
テストなので、`migrate/common.py` 用にこのファイルを分けている。
"""
import pathlib
import sqlite3
import subprocess
import sys

import pytest

from migrate import common

_ROOT = pathlib.Path(__file__).resolve().parents[2]


class _FailOnSQL:
    """`execute()` に渡す SQL 文字列が `trigger` を含んでいたら `exc` を投げる、
    `sqlite3.Connection` への薄いプロキシ。`execute` 以外は素通しする
    （`__getattr__` で実体の `commit`/`rollback` 等に委譲）——差し替えの
    途中（DROP の後・RENAME の前）で失敗させるテスト用。
    """

    def __init__(self, conn: sqlite3.Connection, trigger: str, exc: BaseException):
        self._conn = conn
        self._trigger = trigger
        self._exc = exc

    def execute(self, sql, *args, **kwargs):
        if self._trigger in sql:
            raise self._exc
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_staged_table_swaps_to_production_name_on_success(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,), (3,)])
    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == ["foo"]
    assert conn.execute("SELECT * FROM foo ORDER BY a").fetchall() == [(1,), (2,), (3,)]
    conn.close()


def test_staged_table_failure_inside_with_block_preserves_previous_table(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    before = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()

    with pytest.raises(ValueError, match="boom in with-block"):
        with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
            conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,)])
            raise ValueError("boom in with-block")

    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    assert tables == ["foo"], "作業用テーブルが残っている"
    assert conn.execute("SELECT * FROM foo ORDER BY a").fetchall() == before
    conn.close()


def test_staged_table_failure_between_drop_and_rename_preserves_previous_table(tmp_path):
    """コードレビュー指摘: 差し替え（DROP + RENAME）の途中で失敗しても、
    前回の本番テーブルがそのまま残る（明示の BEGIN〜COMMIT で1トランザクション
    にしたことの直接確認。実際のプロセスクラッシュの代わりに、DROP の後
    ALTER TABLE の直前で例外を起こす）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")

    # 1回目は正常に成功させ、「前回の本番テーブル」を作る。
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    before = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()

    # 2回目: DROP の後・RENAME の前で失敗させる。
    proxy = _FailOnSQL(conn, "ALTER TABLE", RuntimeError("boom mid-swap"))
    with pytest.raises(RuntimeError, match="boom mid-swap"):
        with common.staged_table(proxy, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
            conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,), (8,), (7,)])

    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    after = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()
    assert tables == ["foo"], "本番テーブルが消えたまま、あるいは作業用テーブルが残っている"
    assert after == before, "前回の本番テーブルが変わってしまった"
    conn.close()


def test_staged_table_fingerprint_inputs_is_committed_atomically_with_the_swap(tmp_path):
    """**/code-review 指摘の根本対応の直接確認**: `fingerprint_inputs` を渡すと、
    表の差し替え（DROP+RENAME）と指紋の記録が**同じ**明示トランザクションで
    コミットされる——差し替え後・指紋の記録の途中で失敗しても、差し替え
    ごと巻き戻り、前回の本番テーブルと前回の指紋がどちらもそのまま残る
    （「内容は新しいが指紋は古い」という中間状態が原理的に作れない）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")

    # 1回目: 正常に成功させ、「前回の本番テーブル＋前回の指紋」を作る。
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)", fingerprint_inputs={}) as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    before_rows = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()
    before_fp = common.read_recorded_fingerprint(conn, "foo")
    assert before_fp is not None

    # 2回目: 差し替え（DROP+RENAME）自体は成功させ、指紋の記録（INSERT INTO
    # pipeline_fingerprint）の途中で失敗させる——「差し替えは終わったが指紋の
    # 記録がまだ」という、直したかった穴そのものを再現する箇所。
    proxy = _FailOnSQL(conn, f"INSERT INTO {common.PIPELINE_FINGERPRINT_TABLE}", RuntimeError("boom mid-fingerprint"))
    with pytest.raises(RuntimeError, match="boom mid-fingerprint"):
        with common.staged_table(
            proxy, "foo", "CREATE TABLE {table} (a INTEGER)", fingerprint_inputs={},
        ) as staging:
            conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,), (8,), (7,)])

    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    after_rows = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()
    after_fp = common.read_recorded_fingerprint(conn, "foo")
    assert tables == ["foo", common.PIPELINE_FINGERPRINT_TABLE], "本番テーブルが消えたまま、あるいは作業用テーブルが残っている"
    assert after_rows == before_rows, "指紋の記録に失敗したのに本番テーブルの中身が変わってしまった（差し替えが巻き戻っていない）"
    assert after_fp == before_fp, "指紋の記録に失敗したのに指紋が更新されてしまった（『内容は新しいが指紋は古い』とは逆の中途半端な状態）"
    conn.close()


def test_recording_fingerprint_separately_from_the_swap_can_leave_it_stale(tmp_path):
    """**穴の再現（`fingerprint_inputs` を使わない、直した前の書き方）**:
    差し替え（`staged_table`）と指紋の記録（`record_stage_fingerprint`）を
    別々に呼ぶと、差し替えは確定したのに指紋の記録だけが失敗する窓が
    実際に生まれる——「内容は新しいが指紋は古い」状態を再現する。これが
    b03（Issue #37 のコードレビュー指摘）で実際に起きていた形。
    `fingerprint_inputs` を渡す新しい書き方（上のテスト）ではこの窓が
    無いことと対比する。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")

    # 1回目: 差し替えと指紋の記録を別々に呼ぶ（直す前の書き方）。
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(1,), (2,)])
    common.record_stage_fingerprint(conn, "foo")
    conn.commit()
    first_fp = common.read_recorded_fingerprint(conn, "foo")

    # 2回目: 差し替え自体は成功して確定する（staged_table 内の別トランザクション
    # で既にコミット済み）が、その**後**の指紋の記録が失敗する
    # （プロセスが落ちる代わりに例外で模す）。
    with common.staged_table(conn, "foo", "CREATE TABLE {table} (a INTEGER)") as staging:
        conn.executemany(f'INSERT INTO "{staging}" VALUES (?)', [(9,), (8,), (7,)])
    # ここまでで差し替えは既に確定済み（新しい内容が読める）。
    new_rows = conn.execute("SELECT * FROM foo ORDER BY a").fetchall()
    assert new_rows == [(7,), (8,), (9,)], "差し替え自体は確定しているはず"

    proxy = _FailOnSQL(conn, f"INSERT INTO {common.PIPELINE_FINGERPRINT_TABLE}", RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        common.record_stage_fingerprint(proxy, "foo")
        conn.commit()

    # 「内容は新しいが指紋は古い」状態が実際にできてしまっている——
    # これが直したかった穴そのもの。
    stale_fp = common.read_recorded_fingerprint(conn, "foo")
    assert stale_fp == first_fp, "指紋は前回（古い内容）のまま残っている"
    current_fp = common.compute_table_fingerprint(conn, "foo")
    assert current_fp != stale_fp, "内容は新しいのに、記録された指紋は古い内容のまま——これが穴"
    conn.close()


def test_fresh_sqlite_rejects_a_path_that_resolves_to_a_protected_source_db(tmp_path, monkeypatch):
    """コードレビュー指摘: `fresh_sqlite(path)` は既存ファイル・WAL/SHM側車を
    先に `unlink()` する。`--out` に読み取り専用の原本
    （`data/db/ryuiki.sqlite`/`cells.sqlite`/`derived.sqlite`）そのものを渡すと、
    100MB超で再生成できない原本を消してから書き込みに失敗する事故になる
    （worktree ではこれらは symlink なので、パス文字列ではなく
    `os.path.realpath` で解決した実体を比べる必要がある）。
    """
    monkeypatch.setattr(common, "ROOT", tmp_path)
    real_db_dir = tmp_path / "data" / "db"
    real_db_dir.mkdir(parents=True)
    protected = real_db_dir / "ryuiki.sqlite"
    protected.write_bytes(b"not a real sqlite file, just a stand-in")

    # worktree の運用どおり、symlink 越しに同じ実体を指す。
    link = tmp_path / "ryuiki_via_symlink.sqlite"
    link.symlink_to(protected)

    with pytest.raises(common.MigrationError, match="ryuiki.sqlite"):
        common.fresh_sqlite(link)

    assert protected.exists(), "原本が消されてしまった"
    assert protected.read_bytes() == b"not a real sqlite file, just a stand-in"


def test_fresh_sqlite_still_works_for_an_ordinary_output_path(tmp_path, monkeypatch):
    """通常の出力パス（原本と無関係）は今まで通り作り直せる（回帰）。"""
    monkeypatch.setattr(common, "ROOT", tmp_path)
    (tmp_path / "data" / "db").mkdir(parents=True)

    out = tmp_path / "data" / "db" / "v1_projection_documents.sqlite"
    conn = common.fresh_sqlite(out)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.commit()
    conn.close()
    assert out.exists()


def test_reject_protected_source_db_is_public_and_usable_standalone(tmp_path, monkeypatch):
    """`fresh_sqlite` を経由しないスクリプト（b03/b04 は `--out` を
    `sqlite3.connect` で直接開く）でも同じ検査を呼べるように、
    `reject_protected_source_db` は公開名で単体呼び出しできる
    （コードレビュー指摘: `fresh_sqlite` 経由だけでは b03/b04 の `--out` が
    保護されていなかった）。
    """
    monkeypatch.setattr(common, "ROOT", tmp_path)
    real_db_dir = tmp_path / "data" / "db"
    real_db_dir.mkdir(parents=True)
    protected = real_db_dir / "cells.sqlite"
    protected.write_bytes(b"stand-in")

    with pytest.raises(common.MigrationError, match="cells.sqlite"):
        common.reject_protected_source_db(protected)

    # 無関係な出力パスは通る（何も起きない）。
    common.reject_protected_source_db(tmp_path / "data" / "db" / "v2.sqlite")


def test_existing_tables_returns_table_names_read_only(tmp_path):
    """`common.existing_tables` が `scripts/b08_project_occurrence_v1.py`・
    `scripts/b11_project_place_v1.py` から集約した共通ヘルパであること
    （コードレビュー指摘）。読み取り専用で開くので書き込みはできない。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE a (x)")
        conn.execute("CREATE TABLE b (y)")
        conn.commit()
    finally:
        conn.close()

    assert common.existing_tables(db_path) == {"a", "b"}


def test_require_sqlite_version_passes_when_version_is_new_enough():
    """`min_version` を実行環境の実際の SQLite より確実に低くすれば、
    ホストの SQLite バージョンに関係なく必ず通る（環境依存にしない）。"""
    common.require_sqlite_version(min_version=(0, 0, 0))  # 例外を投げなければ良い


def test_require_sqlite_version_raises_when_too_old(monkeypatch):
    monkeypatch.setattr(common.sqlite3, "sqlite_version_info", (3, 42, 0))
    monkeypatch.setattr(common.sqlite3, "sqlite_version", "3.42.0")
    with pytest.raises(SystemExit, match="古すぎる"):
        common.require_sqlite_version()


def test_require_sqlite_version_raises_systemexit_even_under_dash_o():
    """`assert` ではなく明示的な `SystemExit` であることを、`python -O`
    （`assert` を丸ごと消すモード）下でも実際に止まることで確認する。
    `assert` のままなら `-O` で消え、古い SQLite（`AVG()`/`SUM()` の加算
    アルゴリズムが変わり平均値が黙って変わる版）を検出できなくなる
    （コードレビュー指摘: 以前は `import` 時点でこの確認をしていたが、それだと
    古い環境で `import` した瞬間に `pytest` の収集自体が止まる事故になるため、
    ここでは `common.require_sqlite_version()` の**呼び出し**だけを `-O` 下で
    確認する——`import migrate.common` 自体は版を問わず常に安全）。
    """
    script = (
        "import sys\n"
        "sys.path.insert(0, 'scripts')\n"
        "import sqlite3\n"
        "sqlite3.sqlite_version_info = (3, 42, 0)\n"
        "sqlite3.sqlite_version = '3.42.0'\n"
        "from migrate import common\n"
        "common.require_sqlite_version()\n"
        "print('UNREACHABLE')\n"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", script],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    assert result.returncode != 0
    assert "UNREACHABLE" not in result.stdout
    assert "古すぎる" in result.stderr


# ---------------------------------------------------------------------------
# 段階間の指紋（Issue #37 #1）: compute_table_fingerprint/
# record_stage_fingerprint/assert_stage_fingerprint_fresh
# ---------------------------------------------------------------------------

def _make_t_db(path, rows=((1, "a"),)):
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", rows)
    conn.commit()
    return conn


def test_compute_table_fingerprint_is_deterministic_across_two_connections(tmp_path):
    """同じ内容を2つの別接続で読んでも同じ指紋になる（決定論）。"""
    db_path = tmp_path / "t.sqlite"
    conn1 = _make_t_db(db_path)
    fp1 = common.compute_table_fingerprint(conn1, "t")
    conn1.close()

    conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    fp2 = common.compute_table_fingerprint(conn2, "t")
    conn2.close()
    assert fp1 == fp2


def test_compute_table_fingerprint_changes_when_a_single_value_changes(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    before = common.compute_table_fingerprint(conn, "t")

    conn.execute("UPDATE t SET b = 'changed' WHERE a = 1")
    conn.commit()
    after = common.compute_table_fingerprint(conn, "t")
    conn.close()
    assert before != after


def test_compute_table_fingerprint_changes_when_a_row_is_added(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    before = common.compute_table_fingerprint(conn, "t")

    conn.execute("INSERT INTO t VALUES (2, 'b')")
    conn.commit()
    after = common.compute_table_fingerprint(conn, "t")
    conn.close()
    assert before != after


def test_compute_table_fingerprint_reads_through_an_attached_schema(tmp_path):
    """`schema` を渡すと ATTACH 済みの別名越しに読める（b05/b08/b11 が
    ATTACH した相手側のテーブルを検証するのに使う経路）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    direct = common.compute_table_fingerprint(conn, "t")
    conn.close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, db_path, "other")
        via_attach = common.compute_table_fingerprint(work, "t", schema="other")
    finally:
        work.close()
    assert direct == via_attach


def test_record_and_assert_stage_fingerprint_fresh_round_trip(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    common.record_stage_fingerprint(conn, "t")
    conn.commit()
    # 記録した直後は、同じ内容に対する検証が例外を投げない。
    common.assert_stage_fingerprint_fresh(conn, "t", rebuild_hint="再実行すること。")
    conn.close()


def test_assert_stage_fingerprint_fresh_raises_when_no_meta_table_exists(tmp_path):
    """`pipeline_fingerprint` メタ表自体が無い（この機構より前に作られた出力）
    場合、`rebuild_hint` を含む `MigrationError` で止まる。
    """
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    conn.commit()
    with pytest.raises(common.MigrationError, match="指紋が記録されていない"):
        common.assert_stage_fingerprint_fresh(conn, "t", rebuild_hint="scripts/b03_build_observation.py を再実行すること。")


def test_assert_stage_fingerprint_fresh_raises_when_table_row_missing(tmp_path):
    """メタ表はあるが、対象テーブルの行が記録されていない場合も止まる。"""
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    conn.execute(common._CREATE_PIPELINE_FINGERPRINT_SQL)
    conn.commit()
    with pytest.raises(common.MigrationError, match="指紋が記録されていない"):
        common.assert_stage_fingerprint_fresh(conn, "t", rebuild_hint="再実行すること。")


def test_assert_stage_fingerprint_fresh_raises_when_content_changed_since_recording(tmp_path):
    """**壊れた/古い上流出力で止まることの実測**（Issue #37 受け入れ基準）:
    `t` の指紋を記録した後、内容だけを直接書き換える（=次の段を再実行し
    忘れた状態を模す）と、`rebuild_hint` を含む `MigrationError` で止まる。
    """
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    common.record_stage_fingerprint(conn, "t")
    conn.commit()

    conn.execute("UPDATE t SET b = 'tampered' WHERE a = 1")
    conn.commit()

    with pytest.raises(common.MigrationError, match="scripts/b99_example.py を再実行すること"):
        common.assert_stage_fingerprint_fresh(conn, "t", rebuild_hint="scripts/b99_example.py を再実行すること。")
    conn.close()


def test_record_stage_fingerprint_upserts_on_rerecording(tmp_path):
    """同じテーブルに対して2回記録しても（`table_name` が主キーの）1行のまま
    最新の指紋に更新される。
    """
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    fp1 = common.record_stage_fingerprint(conn, "t")
    conn.execute("INSERT INTO t VALUES (2, 'b')")
    fp2 = common.record_stage_fingerprint(conn, "t")
    conn.commit()
    assert fp1 != fp2
    rows = conn.execute(
        f"SELECT fingerprint FROM {common.PIPELINE_FINGERPRINT_TABLE} WHERE table_name = 't'"
    ).fetchall()
    assert rows == [(fp2,)]
    conn.close()


# ---------------------------------------------------------------------------
# 系譜（(b)）: コードレビュー指摘の穴埋め——「table 自身は無傷だが、記録した
# 系譜（inputs）の上流が作り直された後、table の再構築が行われていない」
# （下流が古い上流から作られたまま）を検出する。
# ---------------------------------------------------------------------------

def _make_upstream_and_downstream(tmp_path):
    """`up`（上流。基底テーブル、系譜を持たない）と `down`（`up` を消費した
    体で `inputs={"up": <upの指紋>}` を持つ）の両方を同じ sqlite に作る。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("CREATE TABLE up (a INTEGER)")
    conn.executemany("INSERT INTO up VALUES (?)", [(1,), (2,)])
    up_fp = common.record_stage_fingerprint(conn, "up")
    conn.execute("CREATE TABLE down (a INTEGER)")
    conn.executemany("INSERT INTO down VALUES (?)", [(10,)])
    common.record_stage_fingerprint(conn, "down", inputs={"up": up_fp})
    conn.commit()
    return conn, up_fp


def test_lineage_check_passes_when_upstream_unchanged(tmp_path):
    conn, _ = _make_upstream_and_downstream(tmp_path)
    # (a)+(b) とも問題無し——例外を投げなければ良い。
    common.assert_stage_fingerprint_fresh(
        conn, "down", rebuild_hint="再実行すること。", upstream_schemas={},
    )
    conn.close()


def test_lineage_check_detects_upstream_rebuilt_without_downstream_rerun(tmp_path):
    """**コードレビュー指摘が指した穴そのものの再現**: `down` 自身の内容は
    無傷（(a) は通る）だが、上流 `up` が「別内容で作り直された」（`up` 自身の
    自己指紋が更新された）のに `down` が再構築されていない——`down` の系譜に
    残る古い `up` の指紋と、`up` の今の自己指紋が食い違うことで (b) が検出する。

    b03（`observation`）だけ作り直して b04（`observation_agg`）を忘れ、
    b05 を実行する具体例と同じ形。
    """
    conn, _ = _make_upstream_and_downstream(tmp_path)
    # up を「別内容で作り直す」（b03 の再実行を模す）。down には一切触れない。
    conn.execute("DELETE FROM up")
    conn.executemany("INSERT INTO up VALUES (?)", [(1,), (2,), (3,)])
    common.record_stage_fingerprint(conn, "up")  # up 自身は正しく指紋を更新する
    conn.commit()

    with pytest.raises(common.MigrationError, match="上流 up の指紋"):
        common.assert_stage_fingerprint_fresh(
            conn, "down", rebuild_hint="down を再実行すること。", upstream_schemas={},
        )
    conn.close()


def test_lineage_check_recurses_two_hops_up(tmp_path):
    """**/code-review 指摘の穴そのものの再現**: `top`→`mid`→`base` の3段の
    系譜で、`base` だけを別内容で作り直し（`mid` は一切触れない——`mid` 自身の
    内容も、`mid` が記録した「消費時点の `base` 指紋」も古いまま）、`top` を
    検証すると、1段目（`top`↔`mid`）は一致するが**2段目（`mid`↔`base`）で
    食い違う**ことを検出する。b03 だけ作り直し、b04・b05 を忘れて b11 を
    実行する具体例（`site_var`→`observation_agg`→`observation`）と同じ形。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("CREATE TABLE base (a INTEGER)")
    conn.executemany("INSERT INTO base VALUES (?)", [(1,), (2,)])
    base_fp = common.record_stage_fingerprint(conn, "base")
    conn.execute("CREATE TABLE mid (a INTEGER)")
    conn.executemany("INSERT INTO mid VALUES (?)", [(10,)])
    mid_fp = common.record_stage_fingerprint(conn, "mid", inputs={"base": base_fp})
    conn.execute("CREATE TABLE top (a INTEGER)")
    conn.executemany("INSERT INTO top VALUES (?)", [(100,)])
    common.record_stage_fingerprint(conn, "top", inputs={"mid": mid_fp})
    conn.commit()

    # 1段目（top↔mid）は無傷のまま通ることを先に確認する（回帰: 再帰導入で
    # 1段目のチェック自体が壊れていないか）。
    common.assert_stage_fingerprint_fresh(conn, "top", rebuild_hint="再実行すること。", upstream_schemas={})

    # base だけを「別内容で作り直す」（b03 の再実行を模す）。mid には一切触れない
    # ——mid 自身の内容も、mid が記録した「消費時点の base 指紋」も古いまま。
    conn.execute("DELETE FROM base")
    conn.executemany("INSERT INTO base VALUES (?)", [(1,), (2,), (3,)])
    common.record_stage_fingerprint(conn, "base")
    conn.commit()

    # 1段しか遡らない実装なら、top の系譜（mid の指紋）は mid 自身の自己申告と
    # まだ一致する（mid は変わっていない）ため、ここで例外が飛ばないと壊れて
    # いる。2段目（mid↔base）まで辿って初めて食い違いを検出できるはず。
    with pytest.raises(common.MigrationError, match=r"mid は上流 base の指紋"):
        common.assert_stage_fingerprint_fresh(
            conn, "top", rebuild_hint="mid の後に top を再実行すること。", upstream_schemas={},
        )
    conn.close()


def test_lineage_check_is_skipped_when_upstream_schemas_is_none(tmp_path):
    """`upstream_schemas=None`（既定）なら (b) を行わない——呼び出し側が
    上流ファイルを開いていない等の理由で検証範囲外にした場合の明示的な
    opt-out。`down` 自身は無傷なので (a) は通り、例外を投げない。
    """
    conn, _ = _make_upstream_and_downstream(tmp_path)
    conn.execute("DELETE FROM up")
    conn.executemany("INSERT INTO up VALUES (?)", [(1,), (2,), (3,)])
    common.record_stage_fingerprint(conn, "up")
    conn.commit()

    common.assert_stage_fingerprint_fresh(conn, "down", rebuild_hint="再実行すること。")
    conn.close()


def test_lineage_check_resolves_upstream_via_attached_schema(tmp_path):
    """`up` が `down` と**別ファイル**にある場合、`upstream_schemas` で
    ATTACH 済みの別名を指定すれば、上流の生データを読まずに自己指紋だけを
    参照できる（b11 が v2.sqlite を ATTACH して observation_agg/occurrence の
    自己指紋を読む経路と同じ形）。
    """
    up_path = tmp_path / "up.sqlite"
    up_conn = sqlite3.connect(f"file:{up_path}", uri=True)
    up_conn.execute("CREATE TABLE up (a INTEGER)")
    up_conn.executemany("INSERT INTO up VALUES (?)", [(1,), (2,)])
    up_fp = common.record_stage_fingerprint(up_conn, "up")
    up_conn.commit()
    up_conn.close()

    down_path = tmp_path / "down.sqlite"
    down_conn = sqlite3.connect(f"file:{down_path}", uri=True)
    down_conn.execute("CREATE TABLE down (a INTEGER)")
    down_conn.executemany("INSERT INTO down VALUES (?)", [(10,)])
    common.record_stage_fingerprint(down_conn, "down", inputs={"up": up_fp})
    down_conn.commit()
    down_conn.close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, down_path, "d")
        common.attach_readonly(work, up_path, "u")
        # 一致するケース: 例外を投げない。
        common.assert_stage_fingerprint_fresh(
            work, "down", schema="d", rebuild_hint="再実行すること。",
            upstream_schemas={"up": "u"},
        )
    finally:
        work.close()

    # up を作り直す（別接続で）。
    up_conn2 = sqlite3.connect(f"file:{up_path}", uri=True)
    up_conn2.execute("DELETE FROM up")
    up_conn2.executemany("INSERT INTO up VALUES (?)", [(1,), (2,), (3,)])
    common.record_stage_fingerprint(up_conn2, "up")
    up_conn2.commit()
    up_conn2.close()

    work2 = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work2, down_path, "d")
        common.attach_readonly(work2, up_path, "u")
        with pytest.raises(common.MigrationError, match=r"上流 u\.up の指紋"):
            common.assert_stage_fingerprint_fresh(
                work2, "down", schema="d", rebuild_hint="down を再実行すること。",
                upstream_schemas={"up": "u"},
            )
    finally:
        work2.close()


def test_lineage_check_raises_when_upstream_schema_not_attached(tmp_path):
    """`upstream_schemas` に別名を指定したのに、その別名が ATTACH されて
    いない（呼び出し側のバグ、または `cube_db` が渡されなかったのに
    `upstream_schemas` を有効にしてしまった等）場合、素の
    `sqlite3.OperationalError` ではなく `MigrationError` になる。
    """
    conn, _ = _make_upstream_and_downstream(tmp_path)
    with pytest.raises(common.MigrationError, match=r"上流 not_attached\.up.*指紋が見つからない"):
        common.assert_stage_fingerprint_fresh(
            conn, "down", rebuild_hint="再実行すること。",
            upstream_schemas={"up": "not_attached"},
        )
    conn.close()


def test_read_recorded_inputs_returns_empty_dict_when_nothing_recorded(tmp_path):
    db_path = tmp_path / "t.sqlite"
    conn = _make_t_db(db_path)
    assert common.read_recorded_inputs(conn, "t") == {}
    conn.close()


def test_read_recorded_inputs_round_trips(tmp_path):
    conn, up_fp = _make_upstream_and_downstream(tmp_path)
    assert common.read_recorded_inputs(conn, "down") == {"up": up_fp}
    conn.close()


# ---------------------------------------------------------------------------
# 読み取りの機械監査（Issue #37 #1、Tier 1。/simplify 指摘A）: `track_reads`/
# `assert_all_reads_verified`。b05 が `cube.observation` を検証せずに読んで
# いたコードレビュー指摘（新しい JOIN を足したのに検証を足し忘れる）を、
# 機械的に検出できることを確かめる。
# ---------------------------------------------------------------------------

def _make_tracked_db_with_two_tables(path):
    """`pipeline_fingerprint` を持つ（=指紋機構の対象）ファイルに、`t`・`u`
    の2表を作る。`u` だけ指紋を記録する（`t` は「検証していない表」役）。
    """
    conn = sqlite3.connect(f"file:{path}", uri=True)
    conn.execute("CREATE TABLE t (a INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.execute("CREATE TABLE u (b INTEGER)")
    conn.execute("INSERT INTO u VALUES (2)")
    common.record_stage_fingerprint(conn, "u")
    conn.commit()
    return conn


def test_track_reads_collects_attached_table_reads(tmp_path):
    """ATTACH 済みの別名越しに読んだ実表が `(schema, table)` で集まる。
    一時テーブルを介した間接的な読み取り（`CREATE TEMP TABLE ... AS SELECT
    ... FROM other.t`）も、その元になった実表として拾える（この機構の要）。
    """
    db_path = tmp_path / "other.sqlite"
    _make_tracked_db_with_two_tables(db_path).close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, db_path, "other")
        with common.track_reads(work) as reads:
            work.execute("CREATE TEMP TABLE snapshot AS SELECT * FROM other.t")
        assert ("other", "t") in reads
    finally:
        work.close()


def test_assert_all_reads_verified_passes_when_all_reads_declared(tmp_path):
    db_path = tmp_path / "other.sqlite"
    _make_tracked_db_with_two_tables(db_path).close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, db_path, "other")
        with common.track_reads(work) as reads:
            work.execute("SELECT * FROM other.u").fetchall()
        common.assert_all_reads_verified(work, reads, {"u"}, context="test")
    finally:
        work.close()


def test_assert_all_reads_verified_raises_on_undeclared_join(tmp_path):
    """`u` だけを検証・宣言したのに、SQL が `t` も JOIN で読んでいれば
    `MigrationError` で止まる——「新しい JOIN を足したのに検証を足し忘れる」
    見落とし（b05 が `cube.observation` を検証せずに読んでいたのと同じ形）を
    機械的に検出できることの確認（/simplify 指摘Aで要求されたテスト）。
    """
    db_path = tmp_path / "other.sqlite"
    _make_tracked_db_with_two_tables(db_path).close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, db_path, "other")
        with common.track_reads(work) as reads:
            # u だけ検証したつもりが、SQL は t も JOIN している
            # （検証を足し忘れた新しい JOIN の再現）。
            work.execute("SELECT u.b FROM other.u JOIN other.t ON t.a = u.b").fetchall()
        with pytest.raises(common.MigrationError, match=r"other\.t"):
            common.assert_all_reads_verified(work, reads, {"u"}, context="test_stage")
    finally:
        work.close()


def test_assert_all_reads_verified_ignores_files_without_pipeline_fingerprint(tmp_path):
    """`pipeline_fingerprint` を持たないファイル（原本・registry.sqlite 相当）
    からの読み取りは、`declared` に無くても自動的に対象外になる——ハード
    コードした除外リストを個別に持たなくてよい設計の確認。
    """
    db_path = tmp_path / "raw_source.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("CREATE TABLE raw (a INTEGER)")
    conn.execute("INSERT INTO raw VALUES (1)")
    conn.commit()
    conn.close()

    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, db_path, "src")
        with common.track_reads(work) as reads:
            work.execute("SELECT * FROM src.raw").fetchall()
        # declared が空でも、src に pipeline_fingerprint が無いので落ちない。
        common.assert_all_reads_verified(work, reads, set(), context="test")
    finally:
        work.close()


def test_assert_all_reads_verified_ignores_own_main_schema(tmp_path):
    """自分自身の出力ファイル（`main` スキーマ）への読み取りは対象外
    ——一時テーブルや、書いた直後に読み返す行は検証の対象ではない。
    """
    work = sqlite3.connect(":memory:", uri=True)
    try:
        work.execute("CREATE TABLE own (a INTEGER)")
        work.execute("INSERT INTO own VALUES (1)")
        with common.track_reads(work) as reads:
            work.execute("SELECT * FROM own").fetchall()
        common.assert_all_reads_verified(work, reads, set(), context="test")
    finally:
        work.close()
