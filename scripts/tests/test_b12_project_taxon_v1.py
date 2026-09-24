"""scripts/b12_project_taxon_v1.py（P-2）のテスト。

本物の `data/db/registry.sqlite` を要さず、`common.create_registry_db()` で
作った空の registry.sqlite に最小限の `taxon_assessment` 行を差し込むだけで
完結する。`registry/taxon/redlist_category.yaml`・`redlist_category_alias.csv`・
`assessment_list.yaml` は実物を読む（手書きの正本・Git管理下）。
"""
import sqlite3

import pytest

import b12_project_taxon_v1 as b12
from registry import common as registry_common

from .occurrence_fixtures import TAXON_ASSESSMENT_COLUMNS


def _ta_row(
    assessment_id, list_id="rl2020", list_year=2020, category_code="EX",
    prev_category_code=None, category_raw="絶滅", prev_category_raw=None,
):
    return (
        assessment_id, list_id, list_year, None,
        "Foo bar", "テスト和名", None,  # vernacular_name_ja_resolved（redlist側は常にNULL）
        "維管束植物", "シダ植物", "テスト科",
        category_raw, category_code,
        prev_category_raw, prev_category_code,
        None, None, "kanagawa_redlist",
    )


def _build_registry(tmp_path, rows):
    registry_db = tmp_path / "registry.sqlite"
    conn = registry_common.create_registry_db(registry_db)
    placeholders = ",".join("?" for _ in TAXON_ASSESSMENT_COLUMNS)
    conn.executemany(f"INSERT INTO taxon_assessment VALUES ({placeholders})", rows)
    conn.commit()
    conn.close()
    return registry_db


def _redlist_change(out_path, assessment_id):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT prev_label, prev_code, prev_rank, cur_label, cur_code, cur_rank, direction "
            "FROM redlist_change WHERE assessment_id = ?",
            (assessment_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return row


def test_redlist_map_has_44_rows_and_excludes_not_listed(tmp_path):
    """redlist_map は taxon_assessment を経由せず、redlist_category_alias.csv
    （44行、`not_listed` を除く）からそのまま作られる。"""
    registry_db = _build_registry(tmp_path, [_ta_row("rl2020_00001")])
    out = tmp_path / "out.sqlite"
    counts = b12.build_projections(registry_db, out)
    assert counts["redlist_map"] == 44

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        codes = {r[0] for r in conn.execute("SELECT code FROM redlist_map")}
    finally:
        conn.close()
    assert "not_listed" not in codes


def test_direction_worse_better_flat_and_not_listed(tmp_path):
    """direction の CASE（v1 の悪化/改善/横ばい/前回記載なし）を再現する。"""
    rows = [
        # 悪化: 現在の rank(EX=70) > 前回の rank(VU=40)
        _ta_row("rl2020_00001", category_code="EX", category_raw="絶滅",
                prev_category_code="VU", prev_category_raw="絶滅危惧II類"),
        # 改善: 現在の rank(NT=30) < 前回の rank(EX=70)
        _ta_row("rl2020_00002", category_code="NT", category_raw="準絶滅危惧",
                prev_category_code="EX", prev_category_raw="絶滅"),
        # 横ばい: 同じ rank
        _ta_row("rl2020_00003", category_code="EX", category_raw="絶滅",
                prev_category_code="EX", prev_category_raw="絶滅"),
        # 前回記載なし: prev が NULL（category_prev_ja が原本にも無い）
        _ta_row("rl2020_00004", category_code="EX", category_raw="絶滅",
                prev_category_code=None, prev_category_raw=None),
        # 前回記載なし（'―' 由来）: not_listed は v1互換で NULL に戻る
        _ta_row("rl2020_00005", category_code="EX", category_raw="絶滅",
                prev_category_code="not_listed", prev_category_raw="―"),
    ]
    registry_db = _build_registry(tmp_path, rows)
    out = tmp_path / "out.sqlite"
    b12.build_projections(registry_db, out)

    assert _redlist_change(out, "rl2020_00001")[6] == "悪化"
    assert _redlist_change(out, "rl2020_00002")[6] == "改善"
    assert _redlist_change(out, "rl2020_00003")[6] == "横ばい"
    assert _redlist_change(out, "rl2020_00004")[6] == "前回記載なし"

    row5 = _redlist_change(out, "rl2020_00005")
    prev_label, prev_code, prev_rank, cur_label, cur_code, cur_rank, direction = row5
    assert direction == "前回記載なし"
    # v1 互換: not_listed（v1 に無かったコード）は NULL に戻す。
    assert prev_label is None
    assert prev_code is None
    assert prev_rank is None


def test_cur_side_null_falls_back_to_flat(tmp_path):
    """v1 の SQL は `cm.rank`（今回）が NULL のとき `NULL > x`/`NULL < x` が
    どちらも偽になり `'横ばい'` に落ちる（3値論理）。Python 版が
    `cur_rank is None` を見落とすと `TypeError` になる（/code-review
    指摘1b）。"""
    row = _ta_row(
        "rl2020_00001", category_code=None, category_raw=None,
        prev_category_code="EX", prev_category_raw="絶滅",
    )
    registry_db = _build_registry(tmp_path, [row])
    out = tmp_path / "out.sqlite"
    b12.build_projections(registry_db, out)
    result = _redlist_change(out, "rl2020_00001")
    prev_label, prev_code, prev_rank, cur_label, cur_code, cur_rank, direction = result
    assert direction == "横ばい"
    assert cur_label is None and cur_code is None and cur_rank is None


def test_cur_side_not_listed_resets_symmetrically_with_prev_side(tmp_path):
    """`not_listed`（v1 に無かったコード）を NULL に戻す変換は、prev側だけで
    なく cur側にも対称に適用される（/code-review 指摘2: 以前は出力行の
    組み立てで `prev_code` だけ個別にガードし、`cur_code` は
    `category_code` を素通ししていた）。"""
    row = _ta_row(
        "rl2020_00001", category_code="not_listed", category_raw="―",
        prev_category_code="EX", prev_category_raw="絶滅",
    )
    registry_db = _build_registry(tmp_path, [row])
    out = tmp_path / "out.sqlite"
    b12.build_projections(registry_db, out)
    result = _redlist_change(out, "rl2020_00001")
    prev_label, prev_code, prev_rank, cur_label, cur_code, cur_rank, direction = result
    assert cur_label is None and cur_code is None and cur_rank is None
    assert direction == "横ばい"  # prev は非NULL・cur が NULL のケース


def test_list_name_and_year_come_from_assessment_list_yaml(tmp_path):
    registry_db = _build_registry(tmp_path, [_ta_row("rl2020_00001", list_id="rl2020", list_year=2020)])
    out = tmp_path / "out.sqlite"
    b12.build_projections(registry_db, out)
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        list_name, list_year = conn.execute(
            "SELECT list_name, list_year FROM redlist_change WHERE assessment_id = ?",
            ("rl2020_00001",),
        ).fetchone()
    finally:
        conn.close()
    assert list_name == "神奈川県レッドリスト2020（植物編CSV）"
    assert list_year == 2020


def test_missing_taxon_assessment_table_raises(tmp_path):
    registry_db = tmp_path / "old_registry.sqlite"
    conn = sqlite3.connect(str(registry_db))
    conn.execute("CREATE TABLE dummy (x INTEGER)")
    conn.commit()
    conn.close()
    out = tmp_path / "out.sqlite"
    from migrate import common as migrate_common

    with pytest.raises(migrate_common.MigrationError, match="taxon_assessment"):
        b12.build_projections(registry_db, out)
