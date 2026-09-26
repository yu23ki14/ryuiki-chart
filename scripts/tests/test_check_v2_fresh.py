"""scripts/check_v2_fresh.py（Issue #48 PR-0）のテスト。

`check_v2_cube_spec_fresh`/`check_v2_cube_fresh`・`compute_v2_input_fingerprint`/
`diff_v2_input_fingerprint` 自体（判定ロジック）の単体テストは
`scripts/tests/test_migrate_common.py`（`scripts/migrate/common.py` 用のファイル）。
ここでは CLI（`check_fresh()`・終了コード・`main()`）だけを見る。原本
（ryuiki/cells/registry/v2.sqlite）は一切要らない——すべて自作の小さな
フィクスチャ sqlite で完結する。
"""
import pathlib
import sqlite3

import check_v2_fresh as cvf
from migrate import common

from .conftest import run_python_cli_isolated
from .migrate_fixtures import make_fresh_v2_cube_db, make_v2_cube_tables

_ROOT = pathlib.Path(__file__).resolve().parents[2]

# `make_fresh_v2_cube_db()`/`cvf.check_fresh()` のどちらも、引数を省略すれば
# `compute_v2_input_fingerprint()` 自身の既定（リポジトリの既定パス、
# `registry_db` は `RYUIKI_REGISTRY_DB` 環境変数も考慮）を使う——原本が無い
# 環境（CI）では両方とも `absent` 系の値になるので、明示的に一致させる必要は
# 無い（記録時・確認時が同じ「今の入力」を見る限り一致する）。


def _make_fresh_v2(tmp_path) -> pathlib.Path:
    return make_fresh_v2_cube_db(tmp_path)


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
    `check_fresh` は spec_version・入力指紋だけを見る。列集合は
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
    conn = make_v2_cube_tables(tmp_path)
    common.record_stage_fingerprint(conn, "observation_agg", spec_version="phase-b-fact-slice/v1")  # 古い版のまま
    common.record_stage_fingerprint(conn, "occurrence_agg", spec_version=common.OCCURRENCE_SPEC_VERSION)
    common.record_v2_input_fingerprint(conn, common.compute_v2_input_fingerprint())
    conn.commit()
    conn.close()

    assert cvf.check_fresh(tmp_path / "v2.sqlite") == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_stale_for_corrupted_file(tmp_path):
    """SQLite ファイルとして壊れている（マジックヘッダすら無い）場合も
    「判定不能」ではなく「古い」（作り直せ）として扱う。"""
    db_path = tmp_path / "v2.sqlite"
    db_path.write_bytes(b"not a sqlite file")
    assert cvf.check_fresh(db_path) == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_stale_when_input_fingerprint_table_missing(tmp_path):
    """spec_version は新しいが、`pipeline_input_fingerprint`（この機構が入る前の
    v2.sqlite）が無いケース——mtime 走査を無くした後、これが原本・入力・コードの
    変化を唯一検出する経路になる。
    """
    conn = make_v2_cube_tables(tmp_path)
    common.record_stage_fingerprint(conn, "observation_agg", spec_version=common.OBSERVATION_AGG_SPEC_VERSION)
    common.record_stage_fingerprint(conn, "occurrence_agg", spec_version=common.OCCURRENCE_SPEC_VERSION)
    conn.commit()
    conn.close()

    assert cvf.check_fresh(tmp_path / "v2.sqlite") == common.V2_CHECK_EXIT_STALE


def test_check_fresh_returns_stale_when_recorded_code_fingerprint_differs(tmp_path):
    """入力・コードの指紋が「記録時と違う」ケース（原本・入力・コードのどれかが
    変わった後、v2.sqlite を作り直していない）を、記録済みの値を直接書き換える
    ことでシミュレートする（実物のコードを変える実演は手動確認で行う）。
    """
    target = _make_fresh_v2(tmp_path)
    conn = sqlite3.connect(f"file:{target}", uri=True)
    conn.execute(
        f"UPDATE {common.PIPELINE_INPUT_FINGERPRINT_TABLE} SET value = 'stale' WHERE component = 'code'"
    )
    conn.commit()
    conn.close()

    assert cvf.check_fresh(target) == common.V2_CHECK_EXIT_STALE


# ---------------------------------------------------------------------------
# CLI（サブプロセス）: 実際の終了コード・PyYAML 非依存
# ---------------------------------------------------------------------------


def _run_cli(extra_argv: list[str]):
    script = _ROOT / "scripts" / "check_v2_fresh.py"
    return run_python_cli_isolated(script, extra_argv)


def test_cli_returns_stale_exit_code_when_file_missing(tmp_path):
    target = tmp_path / "v2.sqlite"
    result = _run_cli(["--v2-db", str(target)])
    assert result.returncode == common.V2_CHECK_EXIT_STALE, (result.stdout, result.stderr)


def test_cli_returns_fresh_exit_code_for_up_to_date_fixture(tmp_path):
    # CLI は `--ryuiki-db`/`--registry-db`/`--processed-dir` を明示しない限り
    # リポジトリの既定パスを使うため、フィクスチャ側もリポジトリの既定
    # （root=_ROOT）で入力指紋を記録する——原本の有無に関わらず、記録時・
    # 確認時が同じ入力を見る限り一致する。
    target = make_fresh_v2_cube_db(tmp_path)
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
