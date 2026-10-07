"""m03_organisms: organism_records.occurrence_status（GBIF の occurrenceStatus。不在記録の旗）。

load_gbif が GBIF の値をそのまま入れること、既存DBへの backfill が冪等なこと
（列が無い古い DB にも足せること）を確かめる。
"""
import collections
import json
import pathlib
import sqlite3

import pytest

import m03_organisms as m03

SCHEMA_APP = pathlib.Path(m03.__file__).parent / "schema_app.sql"


def _gbif_line(key, status):
    return json.dumps({
        "key": key, "scientificName": "Poecilia reticulata", "occurrenceStatus": status,
        "eventDate": "2021-05-01", "decimalLatitude": 35.5, "decimalLongitude": 139.5,
        "license": "http://creativecommons.org/licenses/by/4.0/legalcode",
    })


@pytest.fixture
def proc_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(m03, "PROC", tmp_path)
    (tmp_path / "gbif_kanagawa_occurrences.jsonl").write_text(
        "\n".join([_gbif_line(1, "PRESENT"), _gbif_line(2, "ABSENT"), _gbif_line(3, "ABSENT")]) + "\n",
        encoding="utf-8",
    )
    return tmp_path


def _statuses(conn):
    return dict(conn.execute("SELECT record_id, occurrence_status FROM organism_records"))


def test_load_gbif_stores_occurrence_status_verbatim(proc_dir):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_APP.read_text(encoding="utf-8"))
    assert "occurrence_status" in [r[1] for r in conn.execute("PRAGMA table_info(organism_records)")]
    m03.load_gbif(conn, {}, collections.Counter())
    assert _statuses(conn) == {
        "gbif_kanagawa_occurrences__1": "PRESENT",
        "gbif_kanagawa_occurrences__2": "ABSENT",
        "gbif_kanagawa_occurrences__3": "ABSENT",
    }


def test_backfill_adds_column_and_is_idempotent(proc_dir):
    # 列が無い古い DB（原本の今の姿）。iNaturalist の行も1つ入れておく
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE organism_records (record_id TEXT PRIMARY KEY, source_id TEXT)")
    conn.executemany("INSERT INTO organism_records VALUES (?,?)", [
        ("gbif_kanagawa_occurrences__1", "gbif_kanagawa_occurrences"),
        ("gbif_kanagawa_occurrences__2", "gbif_kanagawa_occurrences"),
        ("gbif_kanagawa_occurrences__3", "gbif_kanagawa_occurrences"),
        ("inaturalist_kanagawa__9", "inaturalist_kanagawa"),
    ])
    added, n, changed, counts = m03.backfill_occurrence_status(conn)
    assert (added, n, changed) == (True, 3, 3)
    assert dict(counts) == {"PRESENT": 1, "ABSENT": 2}
    first = _statuses(conn)
    assert first["gbif_kanagawa_occurrences__2"] == "ABSENT"
    assert first["inaturalist_kanagawa__9"] is None  # GBIF 以外は触らない

    added, n, changed, _ = m03.backfill_occurrence_status(conn)  # 2回目: 何も変わらない
    assert (added, n, changed) == (False, 3, 0)
    assert _statuses(conn) == first
