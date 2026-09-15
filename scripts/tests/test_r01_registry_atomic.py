"""scripts/r01_build_registry.py の書き込みの原子性・`--check-fresh`・
`scripts/registry/common.py` の指紋計算（`compute_input_fingerprint`）のテスト
（phase-b/registry-atomic）。

原本 3 ファイル（ryuiki/cells/derived, 合計900MB超）は一切要らない: 原子性・
check-fresh は `--files-only` 経路（`registry/` 配下の手書きファイルだけで完結する）
で確認し、指紋計算は一時ディレクトリにコピーした入力で確認する（リポジトリの
ファイルは変えない）。
"""
import sqlite3
import sys

import pytest

import r01_build_registry as r01
from registry import common


# ---------------------------------------------------------------------------
# 1. 原子性: チェック / ビルドが失敗しても前の正規ファイルはバイト単位で残り、
#    一時ファイルも残らない
# ---------------------------------------------------------------------------


def _run_files_only(monkeypatch, target) -> None:
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))
    r01.main()


def test_atomic_build_failure_preserves_previous_registry(monkeypatch, tmp_path):
    """ビルドステップそのものが例外を投げるケース。"""
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)  # 1回目: 正常終了して正規のレジストリができる
    assert target.exists()
    good_bytes = target.read_bytes()

    def _boom(conn, _src):
        raise RuntimeError("ビルド中の例外（テスト用）")

    monkeypatch.setattr(r01, "FILES_ONLY_STEPS", [("boom", _boom)])
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))

    with pytest.raises(RuntimeError, match="ビルド中の例外"):
        r01.main()

    assert target.read_bytes() == good_bytes  # 前の正規ファイルがバイト単位で残る
    assert list(tmp_path.glob("registry.sqlite.tmp-*")) == []  # 一時ファイルも残らない


def test_atomic_check_failure_preserves_previous_registry(monkeypatch, tmp_path):
    """ビルド後のチェック（_assert_id_uniqueness 等）が落ちるケース。"""
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)
    good_bytes = target.read_bytes()

    def _boom(conn):
        raise AssertionError("チェック失敗（テスト用）")

    monkeypatch.setattr(r01, "_assert_id_uniqueness", _boom)
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))

    with pytest.raises(AssertionError, match="チェック失敗"):
        r01.main()

    assert target.read_bytes() == good_bytes
    assert list(tmp_path.glob("registry.sqlite.tmp-*")) == []


# ---------------------------------------------------------------------------
# 2. 決定論: --files-only を2回走らせても9テーブル＋registry_build の中身が一致する
#    （フルビルドでの2回一致は受け入れ基準3で手動確認する。828MBの原本が要るため
#    pytest では回さない）
# ---------------------------------------------------------------------------

_ALL_TABLES = (
    "unit", "variable", "variable_alias", "place", "place_source_ref",
    "place_relation", "taxon", "caveat", "caveat_scope", "registry_build",
)


def test_files_only_build_is_deterministic_across_two_runs(monkeypatch, tmp_path):
    target_a = tmp_path / "a" / "registry.sqlite"
    target_b = tmp_path / "b" / "registry.sqlite"

    _run_files_only(monkeypatch, target_a)
    _run_files_only(monkeypatch, target_b)

    conn_a = sqlite3.connect(target_a)
    conn_b = sqlite3.connect(target_b)
    try:
        for table in _ALL_TABLES:
            rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            assert rows_a == rows_b, f"{table} が2回のビルドで一致しない"
    finally:
        conn_a.close()
        conn_b.close()


# ---------------------------------------------------------------------------
# 3. --check-fresh: registry_build の有無・mode・指紋の一致を判定する
# ---------------------------------------------------------------------------


def _make_registry_with_build_row(path, fingerprint: str, mode: str):
    conn = common.create_registry_db(path)
    conn.execute(
        "INSERT INTO registry_build (input_fingerprint, mode) VALUES (?, ?)",
        (fingerprint, mode),
    )
    conn.commit()
    conn.close()


def test_check_fresh_returns_1_when_file_missing(tmp_path):
    assert r01._check_fresh(tmp_path / "registry.sqlite", common.MODE_FULL) == 1


def test_check_fresh_returns_1_when_registry_build_table_missing(tmp_path):
    """registry_build を持たない古いレジストリ（本PR以前に作られたもの）。"""
    target = tmp_path / "registry.sqlite"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE unit (unit_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    assert r01._check_fresh(target, common.MODE_FULL) == 1


def test_check_fresh_returns_1_when_mode_differs(tmp_path, monkeypatch):
    target = tmp_path / "registry.sqlite"
    _make_registry_with_build_row(target, "fp-1", common.MODE_FILES_ONLY)

    monkeypatch.setattr(common, "compute_input_fingerprint", lambda *a, **k: "fp-1")

    assert r01._check_fresh(target, common.MODE_FULL) == 1


def test_check_fresh_returns_1_when_fingerprint_differs(tmp_path, monkeypatch):
    target = tmp_path / "registry.sqlite"
    _make_registry_with_build_row(target, "fp-old", common.MODE_FULL)

    monkeypatch.setattr(common, "compute_input_fingerprint", lambda *a, **k: "fp-new")

    assert r01._check_fresh(target, common.MODE_FULL) == 1


def test_check_fresh_returns_0_when_mode_and_fingerprint_match(tmp_path, monkeypatch):
    target = tmp_path / "registry.sqlite"
    _make_registry_with_build_row(target, "fp-1", common.MODE_FULL)

    monkeypatch.setattr(common, "compute_input_fingerprint", lambda *a, **k: "fp-1")

    assert r01._check_fresh(target, common.MODE_FULL) == 0


def test_check_fresh_end_to_end_after_files_only_build(monkeypatch, tmp_path):
    """モックを使わず、実際に --files-only でビルドした直後は --check-fresh が0を返す
    （main() 内で書いた registry_build と、_check_fresh() が計算する指紋が実際に一致する
    ことを確認する統合テスト）。"""
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)

    assert r01._check_fresh(target, common.MODE_FILES_ONLY) == 0
    assert r01._check_fresh(target, common.MODE_FULL) == 1  # mode 不一致


# ---------------------------------------------------------------------------
# 4. compute_input_fingerprint: 決定論・1バイトの変更を検知する
#    （一時ディレクトリにコピーした入力を使う。リポジトリのファイルは変えない）
# ---------------------------------------------------------------------------


def _make_fingerprint_input_tree(root):
    (root / "scripts" / "registry").mkdir(parents=True)
    (root / "registry").mkdir(parents=True)
    (root / "scripts" / "schema_registry.sql").write_text("CREATE TABLE t(a);\n", encoding="utf-8")
    (root / "scripts" / "r01_build_registry.py").write_text("# stub\n", encoding="utf-8")
    (root / "scripts" / "registry" / "common.py").write_text("# stub\n", encoding="utf-8")
    (root / "registry" / "unit.yaml").write_text("unit_id: x\n", encoding="utf-8")


def test_compute_input_fingerprint_is_deterministic(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)

    fp1 = common.compute_input_fingerprint(root=root)
    fp2 = common.compute_input_fingerprint(root=root)

    assert fp1 == fp2


def test_compute_input_fingerprint_changes_when_registry_file_changes(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    before = common.compute_input_fingerprint(root=root)

    (root / "registry" / "unit.yaml").write_text("unit_id: y\n", encoding="utf-8")
    after = common.compute_input_fingerprint(root=root)

    assert before != after


def test_compute_input_fingerprint_changes_when_build_code_changes(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    before = common.compute_input_fingerprint(root=root)

    (root / "scripts" / "registry" / "common.py").write_text("# stub changed\n", encoding="utf-8")
    after = common.compute_input_fingerprint(root=root)

    assert before != after


def test_compute_input_fingerprint_ignores_files_outside_the_input_set(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    before = common.compute_input_fingerprint(root=root)

    (root / "scripts" / "unrelated.py").write_text("# noise\n", encoding="utf-8")
    after = common.compute_input_fingerprint(root=root)

    assert before == after
