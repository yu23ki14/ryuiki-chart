"""Phase B 突合ハーネス（scripts/b01_derived_baseline.py / scripts/b02_derived_compare.py）の
テスト共通設定。

CI に `data/db/*.sqlite`（14GB、読み取り専用の原本）は無いので、このテストは
すべて自前で作る小さなフィクスチャ sqlite だけで完結する（本物の derived.sqlite には
一切触らない）。
"""
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import b04_build_cube as b04  # noqa: E402  (sys.path 追加後)


@pytest.fixture(autouse=True)
def _skip_unit_evidence_declared_gap_check_by_default(monkeypatch):
    """Issue #48 PR-1 §4: `scripts/tests/migrate_fixtures.make_registry_db()` が
    既定で `unit` 表を持つようになった（`b04_build_cube._assert_unit_evidence()`
    はもう `reg.unit` の有無で素通りしない）ため、`b04.build_cube()` を呼ぶだけの
    一般テスト（単位の証拠そのものを検証する意図が無い大半のテスト。
    `test_b04_build_cube.py`・`test_b05_project_v1.py` 等）が、本物の
    `scripts/migrate/unit_evidence_declarations.yaml`（production の実データ
    全体が前提の宣言）と、テストごとに違う小さな合成フィクスチャの中身を
    突き合わせて「宣言されていない」/「宣言が腐っている」で落ちてしまうのを
    防ぐ——**全テスト共通**で検証2（宣言の過不足チェック）だけをスキップする
    （`b04.UNIT_EVIDENCE_DECLARATIONS_YAML` を `None` に monkeypatch。検証1
    〔symbol 不一致〕は `declarations_path` に関わらず常に動くので、この
    monkeypatch の影響を受けない）。

    `declarations_path=None` は「検証2をスキップする」という意味を
    `_assert_unit_evidence()` 自身が解釈する（空の宣言＝「actual と declared が
    どちらも空でなければならない」ではなく、丸ごとスキップ）ため、フィクスチャ
    ごとに「本物の宣言と一致するかどうか」がまちまちでも（`test_b05_project_v1.py`
    は `DEFAULT_SENSOR_ROWS`/`DEFAULT_SENSOR_ALIASES` を経由する一部のテストで
    実際にこの宣言どおりの欠落を再現するが、それ以外の大半のテストは何も
    再現しない）、どちらも等しく安全に通る。

    `b04.build_cube()` はこの属性を呼び出し時にモジュールグローバルとして
    読むので monkeypatch が効く（`_assert_unit_evidence()` 自身のデフォルト
    引数は定義時に束縛されるため、あちらを直接 monkeypatch しても効かない
    ——`scripts/b04_build_cube.py` の `build_cube()` 内のコメント参照）。

    単位の証拠を明示的に検証するテスト（`test_b04_build_cube.py` の
    「単位の証拠検査」節）は `_assert_unit_evidence()` を直接呼び、常に自分の
    `declarations_path`（実在するファイル）を渡すので、この既定値には
    影響されない。
    """
    monkeypatch.setattr(b04, "UNIT_EVIDENCE_DECLARATIONS_YAML", None)


def run_python_cli_isolated(
    script: pathlib.Path, argv: list[str], *, env_overrides: dict | None = None, cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess:
    """`script` を `-I -S`（ユーザーサイト・グローバルサイトを両方隠す、PyYAML 等
    サイトパッケージが無い環境を模す）の子プロセスで実行する。

    `scripts/r01_build_registry.py --check-fresh` と `scripts/check_v2_fresh.py`
    のテストが同じ「PyYAML の無い環境でも動くこと」を確かめるのに、一字一句
    同じサブプロセス起動を別々に持っていたもの（`test_r01_registry_atomic.py` の
    `_run_check_fresh_subprocess`・`test_check_v2_fresh.py` の `_run_cli`）を
    1箇所に集約した（/simplify 指摘4）。
    """
    cmd = [sys.executable, "-I", "-S", str(script), *argv]
    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, capture_output=True, text=True)
