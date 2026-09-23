"""scripts/b10_project_documents_v1.py の統合テスト。

本物の `data/db/cells.sqlite`/`ryuiki.sqlite` を要さず、
`scripts/tests/documents_fixtures.py` の小さな自作 sqlite だけで完結する。

フィクスチャの設計（`_CELLS`/`_DOCUMENTS`/`_NOTES`/`_QUALITY_TRANSITIONS` 参照）:

- `docA`/`t1`/`rowA`: パイプ無し。2018/2019 は単一セル、2020 は2セル
  （値が異なる＝「別年の値が1つの fiscal_year に潰れて平均される」の縮図で
  はなく、同じ年度内に複数セルがある正常な集約。ノイズ行（`is_total=1`/
  `superseded=1`/`value_type='text'`）を同じグループに混ぜて、フィルタが
  効いて平均値に影響しないことを確認する）。n_years=3 → doc_series_meta に載る。
- `docA`/`t1`/`rowB`: 2018/2019 の2年度のみ（NULL値のノイズ行を混ぜる）。
  n_years=2 → `HAVING n_years >= 3` で doc_series_meta から落ちる（境界値）。
- `docB`/`t2`/`'山北町|三保|入猟者数'`: `|` が2個 → v1 の label バグの実例
  （`'保|入猟者数'` になる。実データの実例と同じ文字列）。
- `docB`/`t3`/`rowC`: 同じ `doc_id`（docB）の別 `row_key`。`notes` は
  `doc_id` だけで絞る相関サブクエリなので、`rowC` にも `山北町...` と
  同じ `n_warnings` が付く（doc 単位で重複する v1 の癖）。
- `docC`/`t4`/`'AAA|BBB'`: `|` が1個だけ → label は正しく `'BBB'`
  （バグは `|` が2個以上のときだけ起きることの対照例）。
"""
import sqlite3

import b10_project_documents_v1 as b10

from .documents_fixtures import make_cells_db, make_ryuiki_db

# doc_id, table_id, page_no, row_key, col_key, value, value_type, unit, fiscal_year, is_total, superseded
_CELLS = [
    # docA / rowA（パイプ無し。2020は2セルで平均10.0/20.0/40.0）
    ("docA", "t1", 1, "rowA", "c1", "10", "int", "件", 2018, 0, 0),
    ("docA", "t1", 1, "rowA", "c1", "20", "int", "件", 2019, 0, 0),
    ("docA", "t1", 1, "rowA", "c1", "30", "int", "件", 2020, 0, 0),
    ("docA", "t1", 1, "rowA", "c2", "50", "int", "件", 2020, 0, 0),
    # ノイズ（フィルタで除外されるべき行。同じグループに混ぜて平均が動かないことを確認）
    ("docA", "t1", 1, "rowA", "cx", "999", "int", "件", 2018, 1, 0),  # is_total=1
    ("docA", "t1", 1, "rowA", "cx", "999", "int", "件", 2019, 0, 1),  # superseded=1
    ("docA", "t1", 1, "rowA", "cx", "999", "text", "件", 2020, 0, 0),  # value_type='text'
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
            ["row_key", "fiscal_year", "value", "n_cells", "unit"],
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


def test_declared_types_match_v1_create_table_as_select(tmp_path):
    """`CREATE TABLE ... AS SELECT` をそのまま使っているので、v1 と同様に
    計算列（label/value/n_cells/unit 等）は宣言型を持たない
    （`PRAGMA table_info` の type が空文字になる）。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        doc_series_types = {r[1]: r[2] for r in conn.execute('PRAGMA table_info("doc_series")')}
        assert doc_series_types["doc_id"] == "TEXT"
        assert doc_series_types["label"] == ""
        assert doc_series_types["value"] == ""
        assert doc_series_types["n_cells"] == ""
        assert doc_series_types["unit"] == ""

        quality_monthly_types = {
            r[1]: r[2] for r in conn.execute('PRAGMA table_info("quality_monthly")')
        }
        assert quality_monthly_types["ym"] == ""
        assert quality_monthly_types["submitted"] == ""
    finally:
        conn.close()


def test_rebuilds_from_scratch_each_run(tmp_path):
    """`fresh_sqlite` で毎回作り直すので、前回実行の内容を引きずらない。"""
    cells_db, ryuiki_db = _setup(tmp_path)
    out = tmp_path / "v1_projection_documents.sqlite"
    b10.build_documents_projection(cells_db, ryuiki_db, out)

    # 入力を大きく減らして再実行 → 前回の行が残らないことを確認する。
    cells_db2, ryuiki_db2 = _setup(
        tmp_path,
        cells=[("docA", "t1", 1, "rowA", "c1", "1", "int", None, 2018, 0, 0)],
        documents=[("docA", "A文書", "A発行者", "https://example.org/a", "CC-BY")],
        notes=[],
        quality_transitions=[],
        suffix="2",
    )
    counts = b10.build_documents_projection(cells_db2, ryuiki_db2, out)
    assert counts["doc_series"] == 1
    assert counts["doc_series_meta"] == 0  # n_years=1 < 3
    assert counts["quality_monthly"] == 0
