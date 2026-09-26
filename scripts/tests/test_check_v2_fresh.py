"""scripts/check_v2_fresh.py（Issue #48 PR-0）のテスト。

`check_v2_cube_spec_fresh`/`check_v2_cube_fresh` 自体（判定ロジック）の単体テストは
`scripts/tests/test_migrate_common.py`（`scripts/migrate/common.py` 用のファイル）。
ここでは CLI（`check_fresh()`・終了コード・`main()`）だけを見る。原本
（ryuiki/cells/registry/v2.sqlite）は一切要らない——すべて自作の小さな
フィクスチャ sqlite で完結する。
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

import check_v2_fresh as cvf
from migrate import common

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _make_fresh_v2(tmp_path) -> pathlib.Path:
    """`observation_agg`/`occurrence_agg` とも今の spec_version で記録済みの、
    「新鮮」な v2.sqlite 風フィクスチャを作る。
    """
    db_path = tmp_path / "v2.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("CREATE TABLE observation_agg (region_id TEXT, n INTEGER)")
    conn.execute("CREATE TABLE occurrence_agg (region_id TEXT, n INTEGER)")
    common.record_stage_fingerprint(conn, "observation_agg", spec_version=common.OBSERVATION_AGG_SPEC_VERSION)
    common.record_stage_fingerprint(conn, "occurrence_agg", spec_version=common.OCCURRENCE_SPEC_VERSION)
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# check_fresh()（関数レベル）
# ---------------------------------------------------------------------------


def test_check_fresh_returns_stale_when_file_missing(tmp_path):
    assert cvf.check_fresh(tmp_path / "v2.sqlite") == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_fresh_for_up_to_date_fixture(tmp_path):
    target = _make_fresh_v2(tmp_path)
    assert cvf.check_fresh(target) == common.V2_CHECK_EXIT_FRESH


def test_check_fresh_returns_stale_for_legacy_13_column_style_db(tmp_path):
    """PR #26 以前の実物と同じ形——`pipeline_fingerprint` 表そのものが無い
    （`imputation`/`value` 列を持つ旧キー。列そのものはここでは見ない——
    `check_fresh` は spec_version だけを見る。列集合は
    `web/scripts/seed-d1-local.mjs` が D1 自身と比べる）。
    """
    db_path = tmp_path / "v2.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(
        "CREATE TABLE observation_agg (region_id TEXT, imputation TEXT, value REAL, n INTEGER NOT NULL)"
    )
    conn.execute("CREATE TABLE occurrence_agg (region_id TEXT, n INTEGER)")
    conn.commit()
    conn.close()

    assert cvf.check_fresh(db_path) == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_stale_when_spec_version_stale(tmp_path):
    db_path = tmp_path / "v2.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute("CREATE TABLE observation_agg (region_id TEXT, n INTEGER)")
    conn.execute("CREATE TABLE occurrence_agg (region_id TEXT, n INTEGER)")
    common.record_stage_fingerprint(conn, "observation_agg", spec_version="phase-b-fact-slice/v1")  # 古い版のまま
    common.record_stage_fingerprint(conn, "occurrence_agg", spec_version=common.OCCURRENCE_SPEC_VERSION)
    conn.commit()
    conn.close()

    assert cvf.check_fresh(db_path) == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_stale_for_corrupted_file(tmp_path):
    """SQLite ファイルとして壊れている（マジックヘッダすら無い）場合も
    「判定不能」ではなく「古い」（作り直せ）として扱う。"""
    db_path = tmp_path / "v2.sqlite"
    db_path.write_bytes(b"not a sqlite file")
    assert cvf.check_fresh(db_path) == common.V2_CHECK_EXIT_STALE


# ---------------------------------------------------------------------------
# CLI（サブプロセス）: 実際の終了コード・PyYAML 非依存
# ---------------------------------------------------------------------------


def _run_cli(extra_argv: list[str]) -> subprocess.CompletedProcess:
    script = str(_ROOT / "scripts" / "check_v2_fresh.py")
    # r01_build_registry.py の --check-fresh テストと同じ流儀（-I -S で
    # サイトパッケージを隠す）。migrate.common は PyYAML が無くても import
    # できる設計（reconcile.common が遅延させる）ことを一緒に確かめる。
    cmd = [sys.executable, "-I", "-S", script, *extra_argv]
    return subprocess.run(cmd, cwd=str(_ROOT), env=dict(os.environ), capture_output=True, text=True)


def test_cli_returns_stale_exit_code_when_file_missing(tmp_path):
    target = tmp_path / "v2.sqlite"
    result = _run_cli(["--v2-db", str(target)])
    assert result.returncode == common.V2_CHECK_EXIT_STALE, (result.stdout, result.stderr)


def test_cli_returns_fresh_exit_code_for_up_to_date_fixture(tmp_path):
    target = _make_fresh_v2(tmp_path)
    result = _run_cli(["--v2-db", str(target)])
    assert result.returncode == common.V2_CHECK_EXIT_FRESH, (result.stdout, result.stderr)
    assert "新鮮" in result.stdout


def test_cli_does_not_import_yaml(tmp_path):
    # tmp_path はテスト関数名からディレクトリ名を作る（pytest の既定）ため、
    # `target` のパス自体に "yaml" という文字列が混ざる（このテスト名由来）。
    # パスを含まない固定名のファイルにして、その偶然の一致を避ける。
    target = tmp_path / "no-such-v2.sqlite"
    result = _run_cli(["--v2-db", str(target)])
    assert "no module named 'yaml'" not in result.stderr.lower(), result.stderr
    assert "modulenotfounderror" not in result.stderr.lower(), result.stderr
