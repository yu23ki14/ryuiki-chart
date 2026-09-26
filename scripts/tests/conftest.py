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

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


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
