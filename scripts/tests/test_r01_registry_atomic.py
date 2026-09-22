"""scripts/r01_build_registry.py の書き込みの原子性・`--check-fresh`・
`scripts/registry/common.py` の指紋計算（`compute_input_fingerprint`）のテスト
（phase-b/registry-atomic）。

原本 3 ファイル（ryuiki/cells/derived, 合計900MB超）は一切要らない: 原子性・
check-fresh は `--files-only` 経路（`registry/` 配下の手書きファイルだけで完結する）
で確認し、指紋計算は一時ディレクトリにコピーした入力で確認する（リポジトリの
ファイルは変えない）。
"""
import os
import sqlite3
import subprocess
import sys
import time

import pytest

import r01_build_registry as r01
from registry import common

from .registry_fixtures import make_derived_places_db


# ---------------------------------------------------------------------------
# 1. 原子性: チェック / ビルドが失敗しても前の正規ファイルはバイト単位で残り、
#    一時ファイルも残らない
# ---------------------------------------------------------------------------


def _run_files_only(monkeypatch, target) -> None:
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))
    r01.main()


def _boom_build_step(conn, _src):
    raise RuntimeError("ビルド中の例外（テスト用）")


def _boom_post_build_check(conn):
    raise AssertionError("チェック失敗（テスト用）")


@pytest.mark.parametrize(
    "attr, value, exc_type, match",
    [
        pytest.param(
            "FILES_ONLY_STEPS", [("boom", _boom_build_step)], RuntimeError, "ビルド中の例外",
            id="build_step_raises",
        ),
        pytest.param(
            "_assert_id_uniqueness", _boom_post_build_check, AssertionError, "チェック失敗",
            id="post_build_check_raises",
        ),
    ],
)
def test_atomic_failure_preserves_previous_registry(
    monkeypatch, tmp_path, attr, value, exc_type, match
):
    """ビルドステップそのものが例外を投げるケースと、ビルド後のチェック
    （_assert_id_uniqueness 等）が落ちるケースの両方で、前の正規ファイルがバイト単位で
    残り、一時ファイルも残らない。"""
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)  # 1回目: 正常終了して正規のレジストリができる
    assert target.exists()
    good_bytes = target.read_bytes()

    monkeypatch.setattr(r01, attr, value)
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))

    with pytest.raises(exc_type, match=match):
        r01.main()

    assert target.read_bytes() == good_bytes  # 前の正規ファイルがバイト単位で残る
    assert list(tmp_path.glob("registry.sqlite.tmp-*")) == []  # 一時ファイルも残らない


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


def test_check_fresh_returns_stale_when_file_missing(tmp_path):
    assert r01._check_fresh(tmp_path / "registry.sqlite", common.MODE_FULL) == r01.EXIT_STALE


def test_check_fresh_returns_stale_when_registry_build_table_missing(tmp_path):
    """registry_build を持たない古いレジストリ（本PR以前に作られたもの）。"""
    target = tmp_path / "registry.sqlite"
    conn = sqlite3.connect(target)
    conn.execute("CREATE TABLE unit (unit_id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    assert r01._check_fresh(target, common.MODE_FULL) == r01.EXIT_STALE


@pytest.mark.parametrize(
    "stored_mode, stored_fingerprint, computed_fingerprint, expected_exit",
    [
        pytest.param(
            common.MODE_FILES_ONLY, "fp-1", "fp-1", "EXIT_STALE", id="mode_differs",
        ),
        pytest.param(
            common.MODE_FULL, "fp-old", "fp-new", "EXIT_STALE", id="fingerprint_differs",
        ),
        pytest.param(
            common.MODE_FULL, "fp-1", "fp-1", "EXIT_FRESH", id="mode_and_fingerprint_match",
        ),
    ],
)
def test_check_fresh_mode_and_fingerprint_combinations(
    tmp_path, monkeypatch, stored_mode, stored_fingerprint, computed_fingerprint, expected_exit
):
    """`registry_build` に記録済みの mode/指紋と、今の入力（モック）の組み合わせで
    EXIT_FRESH/EXIT_STALE が正しく決まる。判定対象の mode は常に MODE_FULL
    （mode 不一致・指紋不一致・両方一致の3ケース）。"""
    target = tmp_path / "registry.sqlite"
    _make_registry_with_build_row(target, stored_fingerprint, stored_mode)

    monkeypatch.setattr(common, "compute_input_fingerprint", lambda *a, **k: computed_fingerprint)

    assert r01._check_fresh(target, common.MODE_FULL) == getattr(r01, expected_exit)


def test_check_fresh_end_to_end_after_files_only_build(monkeypatch, tmp_path):
    """モックを使わず、実際に --files-only でビルドした直後は --check-fresh が
    EXIT_FRESH を返す（main() 内で書いた registry_build と、_check_fresh() が計算する
    指紋が実際に一致することを確認する統合テスト）。"""
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)

    assert r01._check_fresh(target, common.MODE_FILES_ONLY) == r01.EXIT_FRESH
    assert r01._check_fresh(target, common.MODE_FULL) == r01.EXIT_STALE  # mode 不一致


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


def test_compute_input_fingerprint_changes_when_taxon_namespaces_changes(tmp_path):
    """scripts/taxon_namespaces.py（build_taxon.py が読む TAXON_KEY_SOURCE_NAMESPACE
    の正。scripts/registry/ の外にあるため *.py の glob には乗らない）を編集すると
    指紋も変わる（足し忘れると --check-fresh がこの対応表の変更を検知できず
    「新鮮」のまま固まる。scripts/common.py に置いていたときは requests 依存で
    CI が落ちたため移した経緯がある。docs/plans/PHASE_B_OCCURRENCE.md §8参照）。
    """
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "scripts" / "taxon_namespaces.py").write_text(
        "TAXON_KEY_SOURCE_NAMESPACE = {}\n", encoding="utf-8"
    )
    before = common.compute_input_fingerprint(root=root)

    (root / "scripts" / "taxon_namespaces.py").write_text(
        "TAXON_KEY_SOURCE_NAMESPACE = {'x': 'y'}\n", encoding="utf-8"
    )
    after = common.compute_input_fingerprint(root=root)

    assert before != after


def test_compute_input_fingerprint_ignores_files_outside_the_input_set(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    before = common.compute_input_fingerprint(root=root)

    (root / "scripts" / "unrelated.py").write_text("# noise\n", encoding="utf-8")
    after = common.compute_input_fingerprint(root=root)

    assert before == after


# ---------------------------------------------------------------------------
# 5. fix 1: --check-fresh は PyYAML の無い環境でも動く（プロセスを分けて確認する。
#    モジュール読み込み時に無条件で `import yaml` していた退行は、同一プロセス内で
#    r01 を呼ぶだけのテストでは再現できない——pytest 収集時に既に import 済みだから。
#    実際に別プロセスで `python3 -I -S`（PyYAML を含むサードパーティの
#    site-packages を一切見えなくする）から起動して確かめる）。
# ---------------------------------------------------------------------------


def _run_check_fresh_subprocess(extra_argv: list[str], env_overrides: dict) -> subprocess.CompletedProcess:
    script = str(common.ROOT / "scripts" / "r01_build_registry.py")
    cmd = [sys.executable, "-I", "-S", script, *extra_argv]
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(cmd, cwd=str(common.ROOT), env=env, capture_output=True, text=True)


def test_check_fresh_without_pyyaml_reports_stale_when_registry_missing(tmp_path):
    target = tmp_path / "registry.sqlite"  # 存在しない = 古い
    result = _run_check_fresh_subprocess(
        ["--check-fresh"], {"RYUIKI_REGISTRY_DB": str(target)}
    )
    assert result.returncode == r01.EXIT_STALE, (result.stdout, result.stderr)


def test_check_fresh_without_pyyaml_reports_fresh_after_files_only_build(monkeypatch, tmp_path):
    """ビルド自体は yaml が要るので、それは通常のテストプロセス（yaml あり）で行う。
    「判定」だけを、PyYAML が見えない別プロセスから --check-fresh で確認する。
    """
    target = tmp_path / "registry.sqlite"
    _run_files_only(monkeypatch, target)  # 通常プロセス（yaml あり）でビルド

    result = _run_check_fresh_subprocess(
        ["--files-only", "--check-fresh"], {"RYUIKI_REGISTRY_DB": str(target)}
    )
    assert result.returncode == r01.EXIT_FRESH, (result.stdout, result.stderr)


def test_check_fresh_without_pyyaml_does_not_import_yaml(tmp_path):
    """--check-fresh のプロセス自体が `ModuleNotFoundError: yaml` を出していないこと
    （古い実装はモジュール読み込み時に無条件で import しており、PyYAML が無い環境では
    ここでその場で落ちていた）。"""
    target = tmp_path / "registry.sqlite"
    result = _run_check_fresh_subprocess(
        ["--check-fresh"], {"RYUIKI_REGISTRY_DB": str(target)}
    )
    assert "yaml" not in result.stderr.lower(), result.stderr


# ---------------------------------------------------------------------------
# 6. fix 2: 指紋の入力 — taxon_crosswalk.csv / derived.sqlite の中身、
#    ryuiki/cells の除外、--files-only での derived/taxon_crosswalk 不使用。
#    どれもリポジトリ・原本には触れず、一時ディレクトリにコピーした入力で確認する。
# ---------------------------------------------------------------------------


def test_fingerprint_full_mode_changes_when_taxon_crosswalk_csv_changes(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "data" / "processed").mkdir(parents=True)
    csv_path = root / "data" / "processed" / "taxon_crosswalk.csv"
    csv_path.write_text("taxon_id,rank\nabc,species\n", encoding="utf-8")

    before = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)
    csv_path.write_text("taxon_id,rank\nabc,genus\n", encoding="utf-8")
    after = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    assert before != after


def test_fingerprint_full_mode_changes_when_derived_tables_change(tmp_path):
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "data" / "db").mkdir(parents=True)
    derived_path = root / "data" / "db" / "derived.sqlite"
    # watershed_meta は build_place.py が実際に SELECT する列を持つ（残りは None で埋める。
    # scripts/tests/registry_fixtures.py の共通フィクスチャ）。
    make_derived_places_db(derived_path, [("w1", "川1", None, None, None, None)])

    before = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    conn = sqlite3.connect(derived_path)
    conn.execute(
        "UPDATE watershed_meta SET water_system_name = ? WHERE watershed_id = ?",
        ("川2", "w1"),
    )
    conn.commit()
    conn.close()
    after = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    assert before != after


def test_fingerprint_full_mode_ignores_cells_and_most_of_ryuiki(tmp_path):
    """cells.sqlite が変わっても指紋は変わらない（意図的に対象外）。ryuiki.sqlite も
    `organism_records` の行数・最大rowid 以外（他のテーブル、既存行の値の書き換え）は
    無視する（理由は compute_input_fingerprint() の docstring）。
    """
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "data" / "db").mkdir(parents=True)
    ryuiki_path = root / "data" / "db" / "ryuiki.sqlite"
    conn = sqlite3.connect(ryuiki_path)
    conn.execute("CREATE TABLE organism_records (a)")
    conn.execute("CREATE TABLE other_table (b)")
    conn.execute("INSERT INTO organism_records VALUES (1)")
    conn.commit()
    conn.close()

    before = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    # 行数・最大rowidが変わらない書き換え（既存行の値をUPDATE、別テーブルへのINSERT）
    # は検知できない既知の限界（軽い代理指標のため。docstring参照）。
    conn = sqlite3.connect(ryuiki_path)
    conn.execute("UPDATE organism_records SET a = 999")
    conn.execute("INSERT INTO other_table VALUES (1)")
    conn.commit()
    conn.close()
    after = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    assert before == after


def test_fingerprint_full_mode_detects_organism_records_row_count_change(tmp_path):
    """`organism_records` の行数（≒最大rowid）が変わると指紋も変わる
    （/code-review 指摘7。grid01 の入力が derived.mesh_all から organism_records に
    変わったことで抜けた鮮度検知を塞ぐ）。"""
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "data" / "db").mkdir(parents=True)
    ryuiki_path = root / "data" / "db" / "ryuiki.sqlite"
    conn = sqlite3.connect(ryuiki_path)
    conn.execute("CREATE TABLE organism_records (a)")
    conn.execute("INSERT INTO organism_records VALUES (1)")
    conn.commit()
    conn.close()

    before = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    conn = sqlite3.connect(ryuiki_path)
    conn.execute("INSERT INTO organism_records VALUES (2)")
    conn.commit()
    conn.close()
    after = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    assert before != after


def test_fingerprint_files_only_mode_ignores_ryuiki(tmp_path):
    """--files-only は ryuiki.sqlite を一切開かないので、organism_records の行数が
    変わっても files_only モードの指紋には影響しない（CI に原本が無くても動く要件）。
    """
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)
    (root / "data" / "db").mkdir(parents=True)
    ryuiki_path = root / "data" / "db" / "ryuiki.sqlite"
    conn = sqlite3.connect(ryuiki_path)
    conn.execute("CREATE TABLE organism_records (a)")
    conn.commit()
    conn.close()

    before = common.compute_input_fingerprint(root=root, mode=common.MODE_FILES_ONLY)

    conn = sqlite3.connect(ryuiki_path)
    conn.execute("INSERT INTO organism_records VALUES (1)")
    conn.commit()
    conn.close()
    after = common.compute_input_fingerprint(root=root, mode=common.MODE_FILES_ONLY)

    assert before == after


def test_fingerprint_files_only_mode_never_touches_derived_or_taxon_crosswalk(tmp_path):
    """--files-only は build_place.py/build_taxon.py を呼ばないので、指紋計算も
    derived.sqlite / taxon_crosswalk.csv を一切開かない（CI に原本が無くても
    --files-only が動く要件。置いても置かなくても files_only の指紋は変わらない）。"""
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)

    fp_without = common.compute_input_fingerprint(root=root, mode=common.MODE_FILES_ONLY)

    (root / "data" / "processed").mkdir(parents=True)
    (root / "data" / "processed" / "taxon_crosswalk.csv").write_text("x\n", encoding="utf-8")
    (root / "data" / "db").mkdir(parents=True)
    make_derived_places_db(
        root / "data" / "db" / "derived.sqlite", [("w1", "川1", None, None, None, None)]
    )

    fp_with = common.compute_input_fingerprint(root=root, mode=common.MODE_FILES_ONLY)

    assert fp_without == fp_with


def test_fingerprint_full_mode_handles_missing_derived_without_crashing(tmp_path):
    """derived.sqlite が無い環境（full モードだが build:derived をまだ実行していない）
    でも compute_input_fingerprint() は例外を投げない。derived が現れると指紋も変わる
    （「無い」は「古い」として検知される。フル環境で derived が要ることに変わりは無いので、
    実際のビルドは既存の分かりやすいエラー — pnpm run build:derived を促す — で止まる）。"""
    root = tmp_path / "repo"
    _make_fingerprint_input_tree(root)

    fp_missing = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)
    assert fp_missing  # 例外にならない

    (root / "data" / "db").mkdir(parents=True)
    make_derived_places_db(root / "data" / "db" / "derived.sqlite", [])
    fp_present = common.compute_input_fingerprint(root=root, mode=common.MODE_FULL)

    assert fp_missing != fp_present


# ---------------------------------------------------------------------------
# 7. fix 3: 指紋は最初のステップより前に1回だけ計算される
# ---------------------------------------------------------------------------


def test_fingerprint_is_computed_once_before_any_build_step(monkeypatch, tmp_path):
    """ステップの途中で「入力」が変わっても、記録される指紋は変更前の値のまま
    （＝最初のステップより前に既に確定している）ことを、compute_input_fingerprint の
    戻り値を差し替えて確認する。実ファイルは一切変えない。"""
    target = tmp_path / "registry.sqlite"
    calls: list[str] = []
    state = {"value": "before"}

    def fake_compute(*args, **kwargs):
        calls.append(state["value"])
        return state["value"]

    monkeypatch.setattr(common, "compute_input_fingerprint", fake_compute)

    from registry.build_caveat import build_from_files as build_caveat_from_files
    from registry.build_unit_variable import build as build_unit_variable

    def _mutating_step(conn, _src):
        # 「ステップの途中で入力が書き換わった」を模倣する。
        state["value"] = "after"
        return build_unit_variable(conn, _src)

    monkeypatch.setattr(
        r01,
        "FILES_ONLY_STEPS",
        [
            ("mutating", _mutating_step),
            ("caveat", lambda conn, _src: build_caveat_from_files(conn)),
        ],
    )
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))

    r01.main()

    conn = sqlite3.connect(target)
    stored = conn.execute("SELECT input_fingerprint FROM registry_build").fetchone()[0]
    conn.close()

    assert stored == "before"
    assert calls == ["before"]  # 1回だけ・最初のステップより前に呼ばれた


# ---------------------------------------------------------------------------
# 8. fix 4: 一時ファイルの残骸
# ---------------------------------------------------------------------------


def test_create_registry_db_failure_leaves_no_tmp_file(monkeypatch, tmp_path):
    """create_registry_db() 自体が例外を投げても（スキーマが壊れている等）、
    一時ファイルが残らない。以前はこの呼び出しが try の外にあり、ここで例外が出ると
    一時ファイルの掃除にも src コネクションの close にも到達しなかった。"""
    target = tmp_path / "registry.sqlite"

    def _broken_create_registry_db(path=None):
        raise RuntimeError("schema_registry.sql が壊れている（テスト用）")

    monkeypatch.setattr(common, "create_registry_db", _broken_create_registry_db)
    monkeypatch.setattr(sys, "argv", ["r01_build_registry.py", "--files-only"])
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(target))

    with pytest.raises(RuntimeError, match="schema_registry.sql"):
        r01.main()

    assert not target.exists()
    assert list(tmp_path.glob("registry.sqlite.tmp-*")) == []


def test_cleanup_stale_tmp_files_removes_old_but_not_new(tmp_path):
    target = tmp_path / "registry.sqlite"
    old_tmp = tmp_path / "registry.sqlite.tmp-11111"
    new_tmp = tmp_path / "registry.sqlite.tmp-22222"
    old_tmp.write_text("old", encoding="utf-8")
    new_tmp.write_text("new", encoding="utf-8")
    old_wal = tmp_path / "registry.sqlite.tmp-11111-wal"
    old_wal.write_text("old-wal", encoding="utf-8")

    old_time = time.time() - 7200  # 2時間前
    os.utime(old_tmp, (old_time, old_time))
    os.utime(old_wal, (old_time, old_time))
    # new_tmp は今の mtime のまま

    common.cleanup_stale_tmp_files(target, max_age_seconds=3600)

    assert not old_tmp.exists()
    assert not old_wal.exists()
    assert new_tmp.exists()


def test_cleanup_stale_tmp_files_ignores_different_target_name(tmp_path):
    """同じディレクトリでも、別の正規パス名の一時ファイルには触らない
    （full と files_only が同じ data/db/ に別名で書く運用を想定）。"""
    target = tmp_path / "registry.sqlite"
    other_old_tmp = tmp_path / "registry_files_only.sqlite.tmp-33333"
    other_old_tmp.write_text("other", encoding="utf-8")
    old_time = time.time() - 7200
    os.utime(other_old_tmp, (old_time, old_time))

    common.cleanup_stale_tmp_files(target, max_age_seconds=3600)

    assert other_old_tmp.exists()


# ---------------------------------------------------------------------------
# 9. _hash_labeled: _hash_optional_file / _hash_derived_tables の「無い」分岐が
#    共有する下請けへの整理前後で、同じ入力に対して同じバイト整形になること
#    （指紋そのものの値は入力にビルドコード自身も含むため、整理前後で一致しない
#    のが正しい——ここでは「整形のバイト列」だけを、旧実装をその場に書き下して比較する）
# ---------------------------------------------------------------------------


def test_hash_labeled_matches_previous_inline_byte_layout():
    """`_hash_labeled()` が組み立てるバイト列が、整理前に `_hash_optional_file` /
    `_hash_derived_tables` がそれぞれ別々にインライン実装していた
    「ラベル + \\0 + (中身 or _ABSENT_MARKER) + \\0」と一致することを確認する。"""
    import hashlib

    for label, data in (("label", b"content"), ("label", None)):
        got = hashlib.sha256()
        common._hash_labeled(got, label, data)

        want = hashlib.sha256()
        want.update(label.encode("utf-8"))
        want.update(b"\0")
        want.update(data if data is not None else common._ABSENT_MARKER)
        want.update(b"\0")

        assert got.hexdigest() == want.hexdigest()


def test_hash_optional_file_still_uses_hash_labeled_byte_layout(tmp_path):
    """`_hash_optional_file()` を通した結果も、`_hash_labeled()` を直接呼んだ結果と
    一致する（統合窓口として使われていることの確認）。"""
    import hashlib

    present = tmp_path / "present.txt"
    present.write_bytes(b"hello")
    missing = tmp_path / "missing.txt"

    for path, label in ((present, "present.txt"), (missing, "missing.txt")):
        via_file = hashlib.sha256()
        common._hash_optional_file(via_file, label, path)

        via_labeled = hashlib.sha256()
        common._hash_labeled(via_labeled, label, path.read_bytes() if path.exists() else None)

        assert via_file.hexdigest() == via_labeled.hexdigest()
