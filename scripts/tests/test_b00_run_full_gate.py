"""`scripts/b00_run_full_gate.py` のうち、原本や実行時間を必要としない部分
（パイプラインのパス集合の計算・git 由来のヘルパ）だけを検証する。実際に
パイプライン全体を回す統合テストは原本が要るためここには無い（手元で
`.venv/bin/python3 scripts/b00_run_full_gate.py` を実行して確認する。
受け入れ基準4）。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402


def test_collect_pipeline_paths_includes_known_files():
    paths = b00.collect_pipeline_paths()
    assert "scripts/b03_build_observation.py" in paths
    assert "scripts/b10_project_documents_v1.py" in paths
    assert "scripts/r01_build_registry.py" in paths
    assert "scripts/registry" in paths
    assert "scripts/migrate" in paths
    assert "scripts/reconcile" in paths
    assert "registry" in paths
    assert "reports/derived_baseline.json" in paths
    assert "web/scripts/build-derived.mjs" in paths
    assert "web/scripts/build-geo.mjs" in paths
    assert "web/scripts/build-biota.mjs" in paths
    assert "requirements.txt" in paths
    assert "web/package.json" in paths
    assert "web/pnpm-lock.yaml" in paths
    # b00 自身も scripts/b0*.py にマッチする（自己参照。b00 が変わっても
    # 証明が無効になるべきなので、これは意図的）。
    assert "scripts/b00_run_full_gate.py" in paths


def test_collect_pipeline_paths_excludes_tests_and_docs():
    paths = b00.collect_pipeline_paths()
    assert not any(p.startswith("scripts/tests/") for p in paths)
    assert not any(p.startswith("docs/") for p in paths)
    assert not any(p.startswith("web/src/") for p in paths)
    assert not any(p.startswith("data/sample/") for p in paths)


def test_collect_pipeline_paths_is_sorted_and_deduplicated():
    paths = b00.collect_pipeline_paths()
    assert paths == sorted(set(paths))


def test_collect_pipeline_paths_is_deterministic():
    assert b00.collect_pipeline_paths() == b00.collect_pipeline_paths()
