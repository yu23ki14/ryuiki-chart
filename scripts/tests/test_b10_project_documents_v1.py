"""scripts/b10_project_documents_v1.py の統合テスト。

本物の `data/db/cells.sqlite`/`ryuiki.sqlite` を要さず、
`scripts/tests/documents_fixtures.py` の小さな自作 sqlite だけで完結する。

フィクスチャの設計（`_CELLS`/`_DOCUMENTS`/`_NOTES`/`_QUALITY_TRANSITIONS` 参照）:

- `docA`/`t1`/`rowA`: パイプ無し。2018/2019 は単一セル、2020 は `col_key` が
  違う2セル（値・単位も違う）。これは「別年の値が1つの fiscal_year に潰れて
  平均される」v1 の癖と**同じ仕組み**の実例（`num` の `GROUP BY doc_id,
  table_id, row_key, fiscal_year` に `col_key` が入っていないため、
  `col_key` が違っても同じグループに潰れる。実データでは複数年度を表す
  `col_key`（例 `'H25 H26 ...'`）が同じ潰れ方をする——
  `test_doc_series_collapse_is_caused_by_col_key_absent_from_group_by` で
  仕組みそのものを確認する）。ノイズ行（`is_total=1`/`superseded=1`/
  `value_type='text'`/`row_key IS NULL`/`row_key=''`/`fiscal_year IS NULL`）
  を混ぜて、`num` の `WHERE` の各述語がそれぞれ効いていることを確認する。
  n_years=3 → doc_series_meta に載る。
- `docA`/`t1`/`rowB`: 2018/2019 の2年度のみ（`value IS NULL` のノイズ行を
  混ぜる）。n_years=2 → `HAVING n_years >= 3` で doc_series_meta から落ちる
  （境界値）。
- `docB`/`t2`/`'山北町|三保|入猟者数'`: `|` が2個 → v1 の label バグの実例
  （`'保|入猟者数'` になる。実データの実例と同じ文字列）。
- `docB`/`t3`/`rowC`: 同じ `doc_id`（docB）の別 `row_key`。`notes` は
  `doc_id` だけで絞る相関サブクエリなので、`rowC` にも `山北町...` と
  同じ `n_warnings` が付く（doc 単位で重複する v1 の癖）。
- `docC`/`t4`/`'AAA|BBB'`: `|` が1個だけ → label は正しく `'BBB'`
  （バグは `|` が2個以上のときだけ起きることの対照例）。
"""
import json
import pathlib
import sqlite3

import pytest

import b10_project_documents_v1 as b10
from migrate import common as migrate_common

from .documents_fixtures import make_cells_db, make_ryuiki_db

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DERIVED_BASELINE_JSON = _REPO_ROOT / "reports" / "derived_baseline.json"

# doc_id, table_id, page_no, row_key, col_key, value, value_type, unit, fiscal_year, is_total, superseded
_CELLS = [
    # docA / rowA（パイプ無し。2018/2019は単一セル。2020は col_key が違う2セル
    # （unit も違う: A_unit/B_unit）で、col_key が GROUP BY に無いため1行に潰れ、
    # value=(30+50)/2=40.0・unit=MAX('A_unit','B_unit')='B_unit' になる）。
    ("docA", "t1", 1, "rowA", "c1", "10", "int", "件", 2018, 0, 0),
    ("docA", "t1", 1, "rowA", "c1", "20", "int", "件", 2019, 0, 0),
    ("docA", "t1", 1, "rowA", "c1", "30", "int", "A_unit", 2020, 0, 0),
    ("docA", "t1", 1, "rowA", "c2", "50", "int", "B_unit", 2020, 0, 0),
    # ノイズ（フィルタで除外されるべき行。同じグループに混ぜて平均が動かないことを確認）
    ("docA", "t1", 1, "rowA", "cx", "999", "int", "件", 2018, 1, 0),  # is_total=1
    ("docA", "t1", 1, "rowA", "cx", "999", "int", "件", 2019, 0, 1),  # superseded=1
    ("docA", "t1", 1, "rowA", "cx", "999", "text", "件", 2020, 0, 0),  # value_type='text'
    ("docA", "t1", 1, "rowA", "cx", "999", "int", "件", None, 0, 0),  # fiscal_year IS NULL
    ("docA", "t1", 1, None, "cx", "999", "int", "件", 2018, 0, 0),  # row_key IS NULL
    ("docA", "t1", 1, "", "cx", "999", "int", "件", 2018, 0, 0),  # row_key = ''
    # docA / rowB（2年度のみ。HAVING n_years>=3 の境界）
    ("docA", "t1", 1, "rowB", "c1", "100", "int", "件", 2018, 0, 0),
    ("docA", "t1", 1, "rowB", "c1", "200", "int", "件", 2019, 0, 0),
    ("docA", "t1", 1, "rowB", "cx", None, "int", "件", 2018, 0, 0),  # value IS NULL
    # docB / '山北町|三保|入猟者数'（'|' が2個 → label バグ）
    ("docB", "t2", 1, "山北町|三保|入猟者数", "c1", "5", "int", "件", 2018, 0, 0),
    ("docB", "t2", 1, "山北町|三保|入猟者数", "c1", "6", "int", "件", 2019, 0, 0),
    ("docB", "t2", 1, "山北町|三保|入猟者数", "c1", "7", "int", "件", 2020, 0, 0),
    # docB / rowC（同じ doc_id の別 row_key。n_warnings の重複を見る）
    ("docB", "t3", 1, "rowC", "c1", "1000", "int", "件", 2018, 0, 0),
    ("docB", "t3", 1, "rowC", "c1", "1001", "int", "件", 2019, 0, 0),
    ("docB", "t3", 1, "rowC", "c1", "1002", "int", "件", 2020, 0, 0),
    # docC / 'AAA|BBB'（'|' が1個だけ → label は正しく 'BBB'）
    ("docC", "t4", 1, "AAA|BBB", "c1", "11", "int", "件", 2018, 0, 0),
    ("docC", "t4", 1, "AAA|BBB", "c1", "12", "int", "件", 2019, 0, 0),
    ("docC", "t4", 1, "AAA|BBB", "c1", "13", "int", "件", 2020, 0, 0),
]

_DOCUMENTS = [
    ("docA", "A文書", "A発行者", "https://example.org/a", "CC-BY"),
    ("docB", "B文書", "B発行者", "https://example.org/b", "CC-BY"),
    ("docC", "C文書", "C発行者", "https://example.org/c", "CC-BY"),
]

# docB にだけ blocks_timeseries=1 の注記を2件（+ 対象外1件）付ける。
_NOTES = [
    ("docB", 1),
    ("docB", 1),
    ("docB", 0),
]

# from_stage, to_stage, occurred_at
_QUALITY_TRANSITIONS = [
    (None, "暫定", "2024-01-05T09:00:00+09:00"),   # submitted
    (None, "暫定", "2024-01-06T09:00:00+09:00"),   # submitted
    ("暫定", "検証済", "2024-01-20T09:00:00+09:00"),  # verified
    ("検証済", "公開済", "2024-02-01T09:00:00+09:00"),  # published
    ("暫定", "暫定", "2024-02-02T09:00:00+09:00"),   # returned
    ("検証済", "検証済", "2024-02-03T09:00:00+09:00"),  # どの区分にも当たらない
]


def _setup(tmp_path, cells=None, documents=None, notes=None, quality_transitions=None, suffix=""):
    cells_db = tmp_path / f"cells{suffix}.sqlite"
    ryuiki_db = tmp_path / f"ryuiki{suffix}.sqlite"
    make_cells_db(
        cells_db,
        cells=cells if cells is not None else _CELLS,
        documents=documents if documents is not None else _DOCUMENTS,
        notes=notes if notes is not None else _NOTES,
    )
    make_ryuiki_db(
        ryuiki_db,
        quality_transitions=quality_transitions if quality_transitions is not None else _QUALITY_TRANSITIONS,
    )
    return cells_db, ryuiki_db


def _read(out_path, table, columns, order_by):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    try:
        collist = ", ".join(columns)
        rows = conn.execute(f'SELECT {collist} FROM "{table}" ORDER BY {order_by}').fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()


def test_build_returns_row_counts_matching_v1_grouping(tmp_path):
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    counts = b10.build_documents_projection(cells_db, ryuiki_db, out)

    # rowA(3年) + rowB(2年) + 山北町...(3年) + rowC(3年) + AAA|BBB(3年) = 14
    assert counts["doc_series"] == 14
    # HAVING n_years>=3 で rowB(2年)だけ落ちる: rowA/山北町/rowC/AAA|BBB の4件
    assert counts["doc_series_meta"] == 4
    # 月2つ（2024-01, 2024-02）
    assert counts["quality_monthly"] == 2


def test_doc_series_filters_noise_rows_and_averages_correctly(tmp_path):
    """is_total=1 / superseded=1 / value_type='text' / value IS NULL の行は
    `num` CTE の WHERE で除外され、同じグループの平均値に影響しない。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = {
        (r["row_key"], r["fiscal_year"]): r
        for r in _read(
            out, "doc_series",
            ["row_key", "fiscal_year", "value", "n_cells", "unit", "page_no"],
            "doc_id, table_id, row_key, fiscal_year",
        )
        if r["row_key"] == "rowA"
    }
    assert rows[("rowA", 2018)]["value"] == 10.0
    assert rows[("rowA", 2018)]["n_cells"] == 1  # is_total=1 のノイズは除外
    assert rows[("rowA", 2019)]["value"] == 20.0
    assert rows[("rowA", 2019)]["n_cells"] == 1  # superseded=1 のノイズは除外
    assert rows[("rowA", 2020)]["value"] == 40.0  # (30+50)/2、value_type='text' のノイズは除外
    assert rows[("rowA", 2020)]["n_cells"] == 2
    assert rows[("rowA", 2020)]["unit"] == "B_unit"  # MAX('A_unit','B_unit')
    assert rows[("rowA", 2020)]["page_no"] == 1  # フィクスチャは全行 page_no=1

    rows_b = {
        r["fiscal_year"]: r
        for r in _read(
            out, "doc_series",
            ["row_key", "fiscal_year", "value", "n_cells"],
            "doc_id, table_id, row_key, fiscal_year",
        )
        if r["row_key"] == "rowB"
    }
    assert rows_b[2018]["value"] == 100.0
    assert rows_b[2018]["n_cells"] == 1  # value IS NULL の行は除外


def test_doc_series_where_excludes_null_fiscal_year_and_null_or_empty_row_key(tmp_path):
    """`num` CTE の `WHERE fiscal_year IS NOT NULL AND row_key IS NOT NULL AND
    row_key <> ''` の3つの述語をそれぞれ個別に踏むノイズ行（fixture の
    `fiscal_year IS NULL`/`row_key IS NULL`/`row_key = ''` 行）が実際に除外
    されていることを確認する。述語のどれか1つでも外れれば、ここで NULL/空
    文字キーの行が `doc_series` に現れる。
    """
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(out, "doc_series", ["row_key", "fiscal_year"], "doc_id, table_id, row_key, fiscal_year")
    assert not any(r["fiscal_year"] is None for r in rows)
    assert not any(r["row_key"] is None for r in rows)
    assert not any(r["row_key"] == "" for r in rows)
    assert len(rows) == 14  # ノイズ3行はどれも新しいグループを作らない（総数は変わらない）


def test_doc_series_collapse_is_caused_by_col_key_absent_from_group_by(tmp_path):
    """「別年の値が1つの fiscal_year に潰れて平均される」v1 の癖の仕組みを
    直接確認する: `num` の `GROUP BY` は `doc_id, table_id, row_key,
    fiscal_year` だけで `col_key` を含まない。そのため `rowA`/2020 の
    `col_key` が違う2セル（`c1`/`c2`）は1行に潰れる。`col_key` を
    `GROUP BY` に足した集計（v1 の SQL ではなく、この仕組みを確かめるためだけ
    の対照クエリ）だと2行に分かれることで、原因が `col_key` の欠落だと示す。
    """
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    # b10 の実際の出力: col_key が GROUP BY に無いので1行に潰れる。
    rows = _read(
        out, "doc_series", ["row_key", "fiscal_year", "n_cells"],
        "doc_id, table_id, row_key, fiscal_year",
    )
    collapsed = next(r for r in rows if r["row_key"] == "rowA" and r["fiscal_year"] == 2020)
    assert collapsed["n_cells"] == 2  # 2セルが1行に潰れている

    # 対照クエリ: col_key を GROUP BY に足すと2行に分かれる
    # （＝現状の SQL は col_key の違いを無視しているという仕組みの直接確認）。
    conn = sqlite3.connect(f"file:{cells_db}?mode=ro", uri=True)
    try:
        n_groups_with_col_key = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT doc_id, table_id, row_key, col_key, fiscal_year
              FROM cells
              WHERE superseded = 0 AND is_total = 0
                AND value_type IN ('int','float') AND value IS NOT NULL
                AND fiscal_year IS NOT NULL AND row_key IS NOT NULL AND row_key <> ''
                AND row_key = 'rowA' AND fiscal_year = 2020
              GROUP BY doc_id, table_id, row_key, col_key, fiscal_year
            )
            """
        ).fetchone()[0]
    finally:
        conn.close()
    assert n_groups_with_col_key == 2  # col_key を足せば本来の2行に分かれる


def test_doc_series_label_bug_for_two_or_more_pipes(tmp_path):
    """v1 の label バグ（`|` が2個以上だと「最後のトークン」ではなく
    ずれた部分文字列になる）をそのまま再現する。ここで直さない。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "doc_series", ["row_key", "label", "fiscal_year"],
        "doc_id, table_id, row_key, fiscal_year",
    )
    by_key = {(r["row_key"], r["fiscal_year"]): r["label"] for r in rows}

    # '|' が2個 → バグった label（実データの実例と同じ）
    assert by_key[("山北町|三保|入猟者数", 2018)] == "保|入猟者数"


def test_doc_series_label_is_correct_for_a_single_pipe(tmp_path):
    """対照例: `|` が1個だけなら label は正しく最後のトークンになる。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "doc_series", ["row_key", "label", "fiscal_year"],
        "doc_id, table_id, row_key, fiscal_year",
    )
    by_key = {(r["row_key"], r["fiscal_year"]): r["label"] for r in rows}
    assert by_key[("AAA|BBB", 2018)] == "BBB"


def test_doc_series_meta_having_boundary_excludes_two_year_series(tmp_path):
    """`HAVING n_years >= 3` の境界: 2年度(rowB)は落ち、3年度(rowA等)は残る。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "doc_series_meta", ["doc_id", "row_key", "n_years"],
        "doc_id, table_id, row_key",
    )
    keys = {(r["doc_id"], r["row_key"]) for r in rows}
    assert ("docA", "rowB") not in keys  # n_years=2 → 落ちる
    assert ("docA", "rowA") in keys  # n_years=3 → 残る
    n_years_by_key = {(r["doc_id"], r["row_key"]): r["n_years"] for r in rows}
    assert n_years_by_key[("docA", "rowA")] == 3


def test_doc_series_meta_n_warnings_is_duplicated_at_doc_level(tmp_path):
    """`n_warnings` の相関サブクエリは `doc_id` だけで絞り `table_id`/`row_key`
    で絞らないため、同じ doc の全 row_key に同じ件数が重複して入る
    （v1 の癖。ここで直さない）。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "doc_series_meta", ["doc_id", "row_key", "n_warnings"],
        "doc_id, table_id, row_key",
    )
    by_key = {(r["doc_id"], r["row_key"]): r["n_warnings"] for r in rows}

    # docB の notes は blocks_timeseries=1 が2件（doc単位）。
    # 山北町... と rowC の両方に同じ2件が付く（table_id/row_keyで絞られない）。
    assert by_key[("docB", "山北町|三保|入猟者数")] == 2
    assert by_key[("docB", "rowC")] == 2
    # docA/docC には notes が無いので0。
    assert by_key[("docA", "rowA")] == 0
    assert by_key[("docC", "AAA|BBB")] == 0


def test_doc_series_meta_min_max_and_years(tmp_path):
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "doc_series_meta",
        ["doc_id", "row_key", "y_from", "y_to", "v_min", "v_max", "doc_title", "publisher"],
        "doc_id, table_id, row_key",
    )
    row_a = next(r for r in rows if r["row_key"] == "rowA")
    assert row_a["y_from"] == 2018
    assert row_a["y_to"] == 2020
    assert row_a["v_min"] == 10.0
    assert row_a["v_max"] == 40.0
    assert row_a["doc_title"] == "A文書"
    assert row_a["publisher"] == "A発行者"


def test_quality_monthly_counts_each_transition_kind_by_month(tmp_path):
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    rows = _read(
        out, "quality_monthly", ["ym", "submitted", "verified", "published", "returned"], "ym"
    )
    by_month = {r["ym"]: r for r in rows}

    assert by_month["2024-01"]["submitted"] == 2
    assert by_month["2024-01"]["verified"] == 1
    assert by_month["2024-01"]["published"] == 0
    assert by_month["2024-01"]["returned"] == 0

    assert by_month["2024-02"]["submitted"] == 0
    assert by_month["2024-02"]["verified"] == 0
    assert by_month["2024-02"]["published"] == 1
    assert by_month["2024-02"]["returned"] == 1
    # 検証済→検証済 はどの区分にも当たらないので4列とも増えない


# フォールバック期待値（`reports/derived_baseline.json` が読めない環境用）。
# 実データの `derived.sqlite` に対する `PRAGMA table_info` の実測そのもの
# （`.venv/bin/python3` で `data/db/derived.sqlite`（mode=ro）を読んで確認済み）。
# `reports/derived_baseline.json` はコミット済みなので、通常はそちらを正として使う
# （`b01_derived_baseline.py` が同じ実測から機械的に作ったもので、二重管理を避けたい
# が、そのファイル自体が万一読めない場合に備えて明示しておく）。
_FALLBACK_EXPECTED_COLUMNS = {
    "doc_series": [
        ("doc_id", "TEXT"), ("table_id", "TEXT"), ("page_no", "INT"), ("row_key", "TEXT"),
        ("label", ""), ("fiscal_year", "INT"), ("value", ""), ("n_cells", ""), ("unit", ""),
    ],
    "doc_series_meta": [
        ("doc_id", "TEXT"), ("table_id", "TEXT"), ("row_key", "TEXT"), ("label", ""),
        ("page_no", ""), ("n_years", ""), ("y_from", ""), ("y_to", ""), ("unit", ""),
        ("v_min", ""), ("v_max", ""), ("doc_title", "TEXT"), ("publisher", "TEXT"),
        ("url", "TEXT"), ("license", "TEXT"), ("n_warnings", ""),
    ],
    "quality_monthly": [
        ("ym", ""), ("submitted", ""), ("verified", ""), ("published", ""), ("returned", ""),
    ],
}


def test_declared_columns_and_order_match_v1_baseline_exactly(tmp_path):
    """`CREATE TABLE ... AS SELECT` をそのまま使っているので、v1 と同様に
    計算列（label/value/n_cells/unit 等）は宣言型を持たない
    （`PRAGMA table_info` の type が空文字になる）。列順・列名も v1 と完全に
    一致するはずなので、`reports/derived_baseline.json`（`b01_derived_baseline.py`
    が実データの `derived.sqlite` から作った記録。コミット済みなので原本DBが
    無い環境でも読める）の列名・列順・宣言型とそのまま突き合わせる
    （読めない場合だけ `_FALLBACK_EXPECTED_COLUMNS` を使う）。

    `scripts/b02_derived_compare.py` は列を**集合**で比較する
    （`candidate_columns = set(...)`）ため、列順が壊れてもb02は検出できない
    ——列順を守るのはこのテストの役目。
    """
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    if _DERIVED_BASELINE_JSON.exists():
        baseline = json.loads(_DERIVED_BASELINE_JSON.read_text(encoding="utf-8"))
        expected_by_table = {
            table: [(c["name"], c["type"]) for c in baseline["tables"][table]["columns"]]
            for table in _FALLBACK_EXPECTED_COLUMNS
        }
    else:
        expected_by_table = _FALLBACK_EXPECTED_COLUMNS

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        for table, expected in expected_by_table.items():
            actual = [(r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{table}")')]
            assert actual == expected, f"{table}: 列名・列順・宣言型がずれている"
    finally:
        conn.close()


def test_rebuilds_from_scratch_each_run(tmp_path):
    """`fresh_sqlite` で毎回作り直すので、前回実行の内容を引きずらない。

    2回目の入力は3表とも0行にならない最小限の形にする（0行チェック
    （`test_build_raises_when_a_table_ends_up_empty`）と両立させるため）。
    """
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    # 入力を docA/docB/docC から docX 1件だけに差し替えて再実行
    # → 前回の doc_id が残らないことを確認する。
    cells_db2, ryuiki_db2 = _setup(
        tmp_path,
        cells=[
            ("docX", "t1", 1, "rowX", "c1", "1", "int", None, 2018, 0, 0),
            ("docX", "t1", 1, "rowX", "c1", "2", "int", None, 2019, 0, 0),
            ("docX", "t1", 1, "rowX", "c1", "3", "int", None, 2020, 0, 0),
        ],
        documents=[("docX", "X文書", "X発行者", "https://example.org/x", "CC-BY")],
        notes=[],
        quality_transitions=[(None, "暫定", "2024-03-01T09:00:00+09:00")],
        suffix="2",
    )
    counts = b10.build_documents_projection(cells_db2, ryuiki_db2, out)
    assert counts == {"doc_series": 3, "doc_series_meta": 1, "quality_monthly": 1}

    doc_series_rows = _read(out, "doc_series", ["doc_id"], "doc_id")
    assert {r["doc_id"] for r in doc_series_rows} == {"docX"}  # docA/docB/docC は残っていない


def test_build_raises_when_a_table_ends_up_empty(tmp_path):
    """入力のスキーマ・運用が変わって `WHERE` 句が1行も拾わなくなったとき、
    0行・例外無しで黙って通らないことを確認する（コードレビュー指摘）。
    """
    cells_db, ryuiki_db = _setup(
        tmp_path,
        cells=[("docA", "t1", 1, "rowA", "c1", "10", "int", "件", 2018, 0, 0)],
        documents=[("docA", "A文書", "A発行者", "https://example.org/a", "CC-BY")],
        notes=[],
        quality_transitions=[],  # quality_monthly が0行になる
    )
    out = tmp_path / "v1_projection_documents.sqlite"
    with pytest.raises(migrate_common.MigrationError, match="quality_monthly"):
        b10.build_documents_projection(cells_db, ryuiki_db, out)
