"""`scripts/pipeline_inputs.py`（原本・入力ファイルのキーの付け方を1箇所に
まとめたモジュール）の単体テスト。原本DBは使わない——自前の小さなダミー
ファイルだけで完結する。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "sample"
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402
from reconcile.common import load_yaml  # noqa: E402


def _touch_all_source_files(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    cells_db = tmp_path / "cells.sqlite"
    processed_dir = tmp_path / "processed"
    processed_dir.mkdir()
    ryuiki_db.write_bytes(b"ryuiki")
    cells_db.write_bytes(b"cells")
    for key in pipeline_inputs.SOURCE_FILE_KEYS:
        if key.startswith("data/processed/"):
            name = key.rsplit("/", 1)[-1]
            (processed_dir / name).write_bytes(name.encode("utf-8"))
    return ryuiki_db, cells_db, processed_dir


def test_source_file_keys_match_coverage_yaml_wholesale_processed_files():
    """`SOURCE_FILE_KEYS` の processed 部分が `data/sample/coverage.yaml` の
    `wholesale_processed_files` と過不足なく一致すること
    （定数を2箇所で別々に持つ代わりに、一致することをテストで保証する）。
    """
    coverage = load_yaml(SAMPLE_DIR / "coverage.yaml")
    declared = set(coverage["wholesale_processed_files"])
    from_constant = {
        key.rsplit("/", 1)[-1] for key in pipeline_inputs.SOURCE_FILE_KEYS if key.startswith("data/processed/")
    }
    assert from_constant == declared


def test_resolve_source_paths_maps_canonical_keys_to_actual_paths(tmp_path):
    ryuiki_db, cells_db, processed_dir = _touch_all_source_files(tmp_path)
    paths = pipeline_inputs.resolve_source_paths(ryuiki_db, cells_db, processed_dir)
    assert paths["data/db/ryuiki.sqlite"] == ryuiki_db
    assert paths["data/db/cells.sqlite"] == cells_db
    assert paths["data/processed/taxon_crosswalk.csv"] == processed_dir / "taxon_crosswalk.csv"
    assert set(paths) == set(pipeline_inputs.SOURCE_FILE_KEYS)


def test_compute_source_hashes_uses_canonical_keys(tmp_path):
    ryuiki_db, cells_db, processed_dir = _touch_all_source_files(tmp_path)
    hashes = pipeline_inputs.compute_source_hashes(ryuiki_db, cells_db, processed_dir)
    assert set(hashes) == set(pipeline_inputs.SOURCE_FILE_KEYS)
    for digest in hashes.values():
        assert len(digest) == 64


def test_compute_source_hashes_is_deterministic(tmp_path):
    ryuiki_db, cells_db, processed_dir = _touch_all_source_files(tmp_path)
    h1 = pipeline_inputs.compute_source_hashes(ryuiki_db, cells_db, processed_dir)
    h2 = pipeline_inputs.compute_source_hashes(ryuiki_db, cells_db, processed_dir)
    assert h1 == h2


def test_compute_source_hashes_missing_file_raises_clear_error(tmp_path):
    ryuiki_db, cells_db, processed_dir = _touch_all_source_files(tmp_path)
    (processed_dir / "taxon_crosswalk.csv").unlink()
    with pytest.raises(FileNotFoundError, match="taxon_crosswalk.csv"):
        pipeline_inputs.compute_source_hashes(ryuiki_db, cells_db, processed_dir)
