"""`scripts/b13_build_summary.py` の `occurrence_agg` 側
（`summary_taxon_catalog`/`summary_watershed_occurrence`、Issue #48 PR-3a §5）を
検証するための、手書きの `occurrence_agg` フィクスチャ。

`scripts/b07_build_occurrence_cube.py`（`occurrence_agg` を作る本体）は
Issue #48 PR-3a の別担当（U1）がこの worktree の外で並行して変更中——族
（`place_kind × grain` の year/month 族。PR-3a 設計書 §0/§1）・`n_alien` 列は
まだこの worktree の `scripts/b07_build_occurrence_cube.py` に反映されていない。
b13 は `occurrence_agg` を SQL の `SELECT` で読むだけで、`scripts/tests/
occurrence_fixtures.py`（b06/b08 用。U1 が触るので変更しない）が持つ
`organism_records`→`occurrence` の変換は経由しないため、ここでは
`occurrence_agg` 本体を「PR-3a が決めた将来の形」で直接作る——b07 の実装を
待たない・`occurrence_fixtures.py` にも触れない、という取り決めのための
新設ファイル（PR-3a 実装依頼メモ参照）。

次元キーの列名・列順は `scripts/b07_build_occurrence_cube.py` の
`DIM_COLUMNS`（8列。今回は変更対象外——b13 はこの定数を import して
`filter`/`group_by`/`indexes` の許容語彙に使う）と揃えてある。CREATE TABLE
自体はここで完結させ、b07 の `_CREATE_OCCURRENCE_AGG_SQL`（まだ `n_alien` を
持たない旧形）は再利用しない。
"""
from __future__ import annotations

import pathlib
import sqlite3

from migrate import common

# `region_id, source_id, place_id, place_kind, taxon_id, grain, period_start,
# period_end`（b07.DIM_COLUMNS と同じ8列）＋ 値3列（`n`/`n_red_list`/
# `n_alien`。PR-3a D3）＋ 来歴2列。
OCCURRENCE_AGG_COLUMNS = [
    "region_id", "source_id", "place_id", "place_kind", "taxon_id",
    "grain", "period_start", "period_end",
    "n", "n_red_list", "n_alien", "built_from", "spec_version",
]

_CREATE_OCCURRENCE_AGG_SQL = """
CREATE TABLE occurrence_agg (
  region_id     TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  place_id      TEXT,
  place_kind    TEXT,
  taxon_id      TEXT,
  grain         TEXT NOT NULL,
  period_start  TEXT NOT NULL,
  period_end    TEXT NOT NULL,
  n             INTEGER NOT NULL,
  n_red_list    INTEGER NOT NULL,
  n_alien       INTEGER NOT NULL,
  built_from    TEXT NOT NULL,
  spec_version  TEXT NOT NULL
)
"""


def make_occurrence_agg_fixture(tmp_path, rows, name: str = "v2.sqlite") -> pathlib.Path:
    """`occurrence_agg`（PR-3a の将来形。`OCCURRENCE_AGG_COLUMNS` の並び）だけを
    持つ `v2.sqlite` 風のフィクスチャを作り、`occurrence_agg` 自身の段階間指紋を
    記録してファイルパスで返す（`scripts/tests/test_b13_build_summary.py` が使う。
    `make_observation_agg_fixture`〔`scripts/tests/migrate_fixtures.py`〕と同じ形）。

    `rows` の各要素は `OCCURRENCE_AGG_COLUMNS` の順のタプル。

    `inputs={}`（空の系譜）で記録する——`scripts/b13_build_summary.py` の
    `assert_stage_fingerprint_fresh(conn, "occurrence_agg", upstream_schemas={})`
    は `inputs` が空なら (b) の再帰チェックが即座に終わるため、`occurrence`/
    `occurrence_place` 実表を別途用意しなくてよい（b13 を単体で検証するための
    簡略化。本番の b07 の出力は必ず `inputs={"occurrence": ..., "occurrence_place":
    ...}` を持つ）。`spec_version` は b13 の機械検証が値そのものを比較しない
    （`assert_stage_fingerprint_fresh` は内容の指紋一致だけを見る）ため、
    既存の `common.OCCURRENCE_SPEC_VERSION` をそのまま流用する——PR-3a が
    別途起こす `OCCURRENCE_AGG_SPEC_VERSION` 定数（U1 が追加）を、この
    フィクスチャは待たない。
    """
    db_path = tmp_path / name
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(_CREATE_OCCURRENCE_AGG_SQL)
    placeholders = ", ".join("?" for _ in OCCURRENCE_AGG_COLUMNS)
    conn.executemany(
        f'INSERT INTO occurrence_agg ({", ".join(OCCURRENCE_AGG_COLUMNS)}) VALUES ({placeholders})',
        rows,
    )
    common.record_stage_fingerprint(
        conn, "occurrence_agg", spec_version=common.OCCURRENCE_SPEC_VERSION, inputs={},
    )
    conn.commit()
    conn.close()
    return db_path
