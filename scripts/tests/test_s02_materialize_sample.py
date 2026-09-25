"""`scripts/s02_materialize_sample.py` の単体テスト。自前の小さなフィクスチャ
サンプル（`data/sample/` 相当の最小構成）だけで完結する——原本DB・
`data/sample/` の実データは使わない。
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import s02_materialize_sample as s02  # noqa: E402


def _make_fixture_sample_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    sample_dir = tmp_path / "sample"
    (sample_dir / "ryuiki").mkdir(parents=True)
    (sample_dir / "cells").mkdir(parents=True)
    (sample_dir / "processed").mkdir(parents=True)

    (sample_dir / "ryuiki_schema.sql").write_text(
        'CREATE TABLE "sites" (site_id TEXT PRIMARY KEY, name TEXT);\n', encoding="utf-8"
    )
    (sample_dir / "ryuiki" / "sites.sql").write_text(
        "INSERT INTO \"sites\" (site_id, name) VALUES\n('s1', 'Site One'),\n('s2', NULL);\n",
        encoding="utf-8",
    )
    (sample_dir / "cells_schema.sql").write_text(
        'CREATE TABLE "documents" (doc_id TEXT PRIMARY KEY);\n', encoding="utf-8"
    )
    (sample_dir / "cells" / "documents.sql").write_text(
        "INSERT INTO \"documents\" (doc_id) VALUES\n('d1');\n", encoding="utf-8"
    )
    (sample_dir / "processed" / "dummy.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    return sample_dir


def test_materialize_creates_expected_files(tmp_path):
    sample_dir = _make_fixture_sample_dir(tmp_path)
    data_db_dir = tmp_path / "out" / "data" / "db"
    processed_dir = tmp_path / "out" / "data" / "processed"

    written = s02.materialize(sample_dir, data_db_dir, processed_dir)

    assert (data_db_dir / "ryuiki.sqlite").exists()
    assert (data_db_dir / "cells.sqlite").exists()
    assert (processed_dir / "dummy.csv").read_text(encoding="utf-8") == "a,b\n1,2\n"
    assert set(written) == {
        data_db_dir / "ryuiki.sqlite", data_db_dir / "cells.sqlite", processed_dir / "dummy.csv",
    }

    conn = sqlite3.connect(f"file:{data_db_dir / 'ryuiki.sqlite'}?mode=ro", uri=True)
    rows = conn.execute("SELECT site_id, name FROM sites ORDER BY site_id").fetchall()
    conn.close()
    assert rows == [("s1", "Site One"), ("s2", None)]  # NULL と空文字が区別できている


def test_planned_targets_lists_sqlite_and_processed_files(tmp_path):
    sample_dir = _make_fixture_sample_dir(tmp_path)
    data_db_dir = tmp_path / "out" / "data" / "db"
    processed_dir = tmp_path / "out" / "data" / "processed"
    targets = s02.planned_targets(sample_dir, data_db_dir, processed_dir)
    assert data_db_dir / "ryuiki.sqlite" in targets
    assert data_db_dir / "cells.sqlite" in targets
    assert processed_dir / "dummy.csv" in targets


def test_main_refuses_when_targets_already_exist(tmp_path, monkeypatch, capsys):
    sample_dir = _make_fixture_sample_dir(tmp_path)
    data_db_dir = tmp_path / "out" / "data" / "db"
    processed_dir = tmp_path / "out" / "data" / "processed"
    data_db_dir.mkdir(parents=True)
    (data_db_dir / "ryuiki.sqlite").write_bytes(b"not really sqlite, just needs to exist")

    monkeypatch.setattr(
        sys, "argv",
        [
            "s02_materialize_sample.py",
            "--sample-dir", str(sample_dir),
            "--data-db-dir", str(data_db_dir),
            "--processed-dir", str(processed_dir),
            "--i-am-in-a-throwaway-clone",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        s02.main()
    assert exc_info.value.code != 0
    assert "すでにある" in str(exc_info.value)
    # cells.sqlite にはまだ触っていない（安全装置は書き込みの前に効く）。
    assert not (data_db_dir / "cells.sqlite").exists()


def test_main_refuses_without_flag_or_github_actions_env(tmp_path, monkeypatch):
    sample_dir = _make_fixture_sample_dir(tmp_path)
    data_db_dir = tmp_path / "out" / "data" / "db"
    processed_dir = tmp_path / "out" / "data" / "processed"

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        sys, "argv",
        [
            "s02_materialize_sample.py",
            "--sample-dir", str(sample_dir),
            "--data-db-dir", str(data_db_dir),
            "--processed-dir", str(processed_dir),
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        s02.main()
    assert exc_info.value.code != 0
    assert not data_db_dir.exists()


def test_main_succeeds_with_github_actions_env_set(tmp_path, monkeypatch):
    sample_dir = _make_fixture_sample_dir(tmp_path)
    data_db_dir = tmp_path / "out" / "data" / "db"
    processed_dir = tmp_path / "out" / "data" / "processed"

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(
        sys, "argv",
        [
            "s02_materialize_sample.py",
            "--sample-dir", str(sample_dir),
            "--data-db-dir", str(data_db_dir),
            "--processed-dir", str(processed_dir),
        ],
    )
    assert s02.main() == 0
    assert (data_db_dir / "ryuiki.sqlite").exists()
