"""`scripts/s04_check_full_gate_proof.py` の、証明（`reports/serving_fingerprint.json`）の
`schema_version`・`queries[].id` を HEAD の `web/serving_queries.yaml` と突き合わせる部分
（Issue #48 PR-5）。コミット済みの証明・原本を要らない純関数のテストだけ置く
（実物の証明を使う検査は `test_s04_check_full_gate_proof.py`）。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402
import s04_check_full_gate_proof as s04  # noqa: E402

_YAML = """\
version: 1
domains:
  alias:
    sql: "SELECT 1"
    db: registry
queries:
  - id: sites_list   # コメント付き
    params: []
  - id: water_bodies
    params: [kind]
  # - id: commented_out
  - id: species_year
retired:
  - id: not_a_query
"""


def _proof(ids, schema_version=b00.SCHEMA_VERSION):
    return {"schema_version": schema_version, "queries": [{"id": i, "runs": []} for i in ids]}


def test_parse_query_ids_reads_only_the_queries_section():
    assert s04.parse_query_ids(_YAML) == {"sites_list", "water_bodies", "species_year"}


def test_matching_ids_and_schema_version_have_no_problems():
    assert s04.check_schema_and_query_ids(_proof(["sites_list", "water_bodies", "species_year"]), _YAML) == []


def test_a_query_added_to_the_yaml_but_missing_from_the_proof_is_reported():
    problems = s04.check_schema_and_query_ids(_proof(["sites_list", "water_bodies"]), _YAML)
    assert len(problems) == 1 and "species_year" in problems[0] and "HEAD にしか無い" in problems[0]


def test_a_query_left_in_the_proof_after_removal_is_reported():
    problems = s04.check_schema_and_query_ids(
        _proof(["sites_list", "water_bodies", "species_year", "gone"]), _YAML,
    )
    assert len(problems) == 1 and "gone" in problems[0] and "証明にしか無い" in problems[0]


def test_wrong_schema_version_is_reported():
    problems = s04.check_schema_and_query_ids(
        _proof(["sites_list", "water_bodies", "species_year"], schema_version=999), _YAML,
    )
    assert len(problems) == 1 and "schema_version" in problems[0]


def test_unreadable_yaml_is_a_problem_not_a_silent_pass():
    problems = s04.check_schema_and_query_ids(_proof([]), "version: 1\n")
    assert any("id を1つも読めない" in p for p in problems)
