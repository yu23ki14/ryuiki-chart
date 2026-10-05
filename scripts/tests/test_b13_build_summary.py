"""scripts/b13_build_summary.py の統合テスト。

本物の `data/db/v2.sqlite`（原本由来）を要さず、`scripts/tests/migrate_fixtures.py`
の `make_observation_agg_fixture`（observation_agg）・`scripts/tests/
occurrence_fixtures.py` の `make_occurrence_agg_fixture`（occurrence_agg。
PR-3a §5。`occurrence_agg` だけを持つ最小限のフィクスチャ——b13 は
`occurrence_agg` を `SELECT` で読むだけなので、b06/b09 が作る `occurrence`/
`occurrence_place` は要らない）が作る小さなキューブだけで完結する。
"""
from __future__ import annotations

import pathlib
import sqlite3

import pytest
import yaml

import b04_build_cube as b04
import b13_build_summary as b13
from migrate import common

from .migrate_fixtures import make_observation_agg_fixture
from .occurrence_fixtures import make_occurrence_agg_fixture

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_YAML = ROOT / "aggregations" / "serving.yaml"

# `b04.DIM_COLUMNS` の並び: region_id, place_id, place_kind, variable_id,
# obs_stat, unit_id, value_grain, period_start, period_end, grain, input_grain, stat
# に続けて value_zero, value_lod, n, n_censored, n_not_detected, n_places,
# built_from, spec_version。

_ROWS = [
    # p1・2020年・n=10・censored=1
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 1.0, 1.1, 10, 1, 0, 1, "obs", "v2"),
    # p1・2021年・n=5・censored=0
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2021-01-01", "2021-12-31",
     "year", "day", "mean", 3.0, 3.1, 5, 0, 0, 1, "obs", "v2"),
    # p2・2020年・n=7・censored=2
    ("r1", "p2", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 5.0, 5.2, 7, 2, 0, 1, "obs", "v2"),
    # filter 対象外: place_kind='watershed'（site ではない）
    ("r1", "w1", "watershed", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "mean", 9.0, 9.0, 999, 0, 0, 1, "obs", "v2"),
    # filter 対象外: stat='min'（非代表統計量。mean のみを対象にする）
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-12-31",
     "year", "day", "min", 8.0, 8.0, 888, 0, 0, 1, "obs", "v2"),
    # filter 対象外: grain='month'（year/fiscal_year のみを対象にする）
    ("r1", "p1", "site", "v.bod", "mean", "unit.mgl", "day", "2020-01-01", "2020-01-31",
     "month", "day", "mean", 7.0, 7.0, 777, 0, 0, 1, "obs", "v2"),
]

# `scripts/tests/occurrence_fixtures.py` の `_OCCURRENCE_AGG_COLUMNS` の並び:
# region_id, source_id, place_id, place_kind, taxon_id, grain, period_start,
# period_end, n, n_red_list, n_alien, built_from, spec_version。
#
# summary_taxon_catalog（filter: place_kind=grid01, grain IN (year, survey_period)）
# が拾うのは grid01×year 族（インデックス0〜4）だけ——grid01×month（5）と
# watershed 側（6〜9）は対象外。summary_watershed_occurrence（filter:
# place_kind=watershed, grain IN (year, survey_period)）が拾うのは
# watershed×year 族（6〜8）だけ——grid01 側（0〜5）と watershed×month（9）は
# 対象外。同じ1つのフィクスチャで両方の filter が正しく族を分けることを
# 検証する（filter.grain を忘れると month 族まで二重に数える、という
# PR-3a §9-2 の事故をここで踏めるように、month 族には突飛な値を入れてある）。
_OCC_ROWS = [
    # 0: t1 @ g1, year 2020
    ("jp-14", "gbif", "g1", "grid01", "t1", "year", "2020-01-01", "2020-12-31", 10, 2, 1, "occ", "v"),
    # 1: t1 @ g2, year 2021
    ("jp-14", "gbif", "g2", "grid01", "t1", "year", "2021-01-01", "2021-12-31", 5, 0, 0, "occ", "v"),
    # 2: t2 @ g1, year 2020
    ("jp-14", "gbif", "g1", "grid01", "t2", "year", "2020-01-01", "2020-12-31", 7, 1, 0, "occ", "v"),
    # 3: taxon_id NULL（未解決）@ g3, year 2020
    ("jp-14", "gbif", "g3", "grid01", None, "year", "2020-01-01", "2020-12-31", 3, 0, 0, "occ", "v"),
    # 4: t1 @ g1, survey_period（年をまたぐ leaf。2020年に属する扱い）
    ("jp-14", "gbif", "g1", "grid01", "t1", "survey_period", "2020-11-01", "2021-02-28", 4, 0, 1, "occ", "v"),
    # 5: filter 対象外（grid01×month）。含まれれば SUM(n) が大きくずれる値にしてある。
    ("jp-14", "gbif", "g1", "grid01", "t1", "month", "2020-06-01", "2020-06-30", 999, 999, 999, "occ", "v"),
    # 6: t1 @ w1（流域解決済み）, year 2020
    ("jp-14", "gbif", "w1", "watershed", "t1", "year", "2020-01-01", "2020-12-31", 6, 1, 0, "occ", "v"),
    # 7: place_id NULL（流域に解決できない日付あり記録。ADR-0025/0026 D1）, year 2020
    ("jp-14", "gbif", None, "watershed", "t1", "year", "2020-01-01", "2020-12-31", 2, 0, 0, "occ", "v"),
    # 8: t2 @ w2, year 2021
    ("jp-14", "gbif", "w2", "watershed", "t2", "year", "2021-01-01", "2021-12-31", 9, 3, 2, "occ", "v"),
    # 9: filter 対象外（watershed×month）。含まれれば SUM(n) が大きくずれる値にしてある。
    ("jp-14", "gbif", "w1", "watershed", "t1", "month", "2020-06-01", "2020-06-30", 888, 888, 888, "occ", "v"),
]


def _make_combined_fixture(tmp_path, obs_rows=_ROWS, occ_rows=_OCC_ROWS, name: str = "v2.sqlite") -> pathlib.Path:
    """`observation_agg`（`_ROWS`）と `occurrence_agg`（`_OCC_ROWS`）の両方を
    同じ v2.sqlite 風フィクスチャに持たせる。summary 4表のうち2表ずつが別々の
    `source` を使うため、`build_summary` を実際に完走させるテストは両方が
    要る（YAML の語彙検証だけで止まる失敗系のテストは、どちらか一方の
    フィクスチャだけで足りる——各テストの docstring/コメント参照）。
    """
    make_observation_agg_fixture(tmp_path, obs_rows, name=name)
    return make_occurrence_agg_fixture(tmp_path, occ_rows, name=name)

# registry.sqlite 風フィクスチャ（`taxon` だけ。D1: b13 が `ATTACH ... mode=ro` して結合する）。
# t1 と t3 は同じ binom（`Aus bus`）——taxon_id 単位ではなく binom 単位に束ねる
# ことの検証用（v1 の「二名法キーの DISTINCT」）。t4 は binom が取れない taxon
# （canonical_binomial NULL）。
_TAXON_ROWS = [
    # taxon_id, canonical_binomial, taxon_group, class, family
    ("t1", "Aus bus", "鳥類", "Aves", "Fam1"),
    ("t2", "Cus dus", "昆虫", "Insecta", "Fam2"),
    ("t3", "Aus bus", "哺乳類", "Mammalia", "Fam3"),   # t1 と同じ binom・別の taxon_group
    ("t4", None, "植物", "Mag", "Fam4"),
]


def _make_registry_fixture(tmp_path, taxon_rows=_TAXON_ROWS, name: str = "registry.sqlite",
                           *, primary_key: bool = True) -> pathlib.Path:
    path = tmp_path / name
    conn = sqlite3.connect(path)
    try:
        pk = "PRIMARY KEY" if primary_key else ""
        conn.execute(
            f"CREATE TABLE taxon (taxon_id TEXT {pk}, canonical_binomial TEXT, taxon_group TEXT, "
            "class TEXT, family TEXT)"
        )
        conn.executemany("INSERT INTO taxon VALUES (?, ?, ?, ?, ?)", taxon_rows)
        conn.commit()
    finally:
        conn.close()
    return path


# `_OCC_ROWS` に足す、binom 単位の4表の検証用の行（grid01×year 族）。
_OCC_ROWS_BINOM_EXTRA = [
    # 10: t3（binom は t1 と同じ）@ g1, 2020。g1 の binom は t1・t3 で 1 つに束ねられる。
    ("jp-14", "inat", "g1", "grid01", "t3", "year", "2020-01-01", "2020-12-31", 20, 5, 0, "occ", "v"),
    # 11: t4（binom 無し・taxon_group='植物'）@ g1, 2020。species_catalog には出ない。
    ("jp-14", "gbif", "g1", "grid01", "t4", "year", "2020-01-01", "2020-12-31", 11, 0, 0, "occ", "v"),
    # 12: 窓外（1950 年）。t2 @ g4。grid_catalog では n=0 だが n_binom には数える。
    ("jp-14", "gbif", "g4", "grid01", "t2", "year", "1950-01-01", "1950-12-31", 100, 40, 0, "occ", "v"),
]


# 機械検証3（無作為抽出した群を、b13 の生成 SQL とは独立の固定 SQL で再計算して
# 一致を確認する）用の、宣言をなぞらない別実装。`aggregations/serving.yaml` の
# 内容が変わったら、この定数もオーナーが手で追随させること（自動生成しない
# ——それでは「独立」でなくなる）。
_REFERENCE_SQL = {
    "summary_variable_catalog": """
        SELECT variable_id, obs_stat, unit_id, value_grain, grain, input_grain,
               SUM(n), COUNT(DISTINCT place_id),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER)),
               SUM(n_censored), SUM(n_not_detected)
        FROM observation_agg
        WHERE place_kind = 'site' AND grain IN ('year', 'fiscal_year') AND stat = 'mean'
        GROUP BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain
        ORDER BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain
    """,
    "summary_place_variable": """
        SELECT place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain,
               SUM(n),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER)),
               AVG(value_zero), AVG(value_lod),
               SUM(n_censored), SUM(n_not_detected)
        FROM observation_agg
        WHERE place_kind = 'site' AND grain IN ('year', 'fiscal_year') AND stat = 'mean'
        GROUP BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain
        ORDER BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain
    """,
    # occurrence_agg 由来の2表（PR-3a §5）。filter の grain 族の絞り込みを
    # 生成側（b13）と共有せず、ここで独立に `IN ('year', 'survey_period')` と
    # 書く——filter.grain を書き忘れる事故（month 族の二重計上）を、生成側の
    # コピーではなくこの独立実装で検出する（モジュール docstring 参照）。
    "summary_taxon_catalog": """
        SELECT taxon_id,
               SUM(n), SUM(n_red_list), SUM(n_alien),
               COUNT(DISTINCT place_id),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER)),
               COUNT(DISTINCT CAST(substr(period_start, 1, 4) AS INTEGER))
        FROM occurrence_agg
        WHERE place_kind = 'grid01' AND grain IN ('year', 'survey_period')
        GROUP BY taxon_id
        ORDER BY taxon_id
    """,
    "summary_watershed_occurrence": """
        SELECT place_id,
               SUM(n), SUM(n_red_list), SUM(n_alien),
               COUNT(DISTINCT taxon_id),
               MIN(CAST(substr(period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(period_start, 1, 4) AS INTEGER))
        FROM occurrence_agg
        WHERE place_kind = 'watershed' AND grain IN ('year', 'survey_period')
        GROUP BY place_id
        ORDER BY place_id
    """,
    # PR-3b の binom 単位の4表。registry を `registry` として ATTACH した接続で実行する
    # （`_attach_registry_for_reference`）。結合・`binom`・`'未判定'`・年の窓は生成側と
    # 共有せず、ここで独立に書く。
    "summary_species_catalog": """
        SELECT t.canonical_binomial,
               MAX(t.taxon_group), MAX(t.class), MAX(t.family),
               SUM(o.n), SUM(o.n_red_list), SUM(o.n_alien),
               COUNT(DISTINCT o.place_id),
               MIN(CAST(substr(o.period_start, 1, 4) AS INTEGER)),
               MAX(CAST(substr(o.period_start, 1, 4) AS INTEGER)),
               COUNT(DISTINCT CAST(substr(o.period_start, 1, 4) AS INTEGER))
        FROM occurrence_agg o JOIN registry.taxon t ON t.taxon_id = o.taxon_id
        WHERE o.place_kind = 'grid01' AND o.grain IN ('year', 'survey_period')
          AND t.canonical_binomial IS NOT NULL
        GROUP BY t.canonical_binomial
        ORDER BY t.canonical_binomial
    """,
    "summary_group_year": """
        SELECT CAST(substr(o.period_start, 1, 4) AS INTEGER) AS y,
               COALESCE(t.taxon_group, '未判定') AS g, o.source_id,
               SUM(o.n), COUNT(DISTINCT t.canonical_binomial), COUNT(DISTINCT o.place_id)
        FROM occurrence_agg o LEFT JOIN registry.taxon t ON t.taxon_id = o.taxon_id
        WHERE o.place_kind = 'grid01' AND o.grain IN ('year', 'survey_period')
        GROUP BY y, g, o.source_id
        ORDER BY y, g, o.source_id
    """,
    "summary_effort_year": """
        SELECT CAST(substr(o.period_start, 1, 4) AS INTEGER) AS y,
               SUM(o.n), COUNT(DISTINCT t.canonical_binomial), COUNT(DISTINCT o.place_id)
        FROM occurrence_agg o LEFT JOIN registry.taxon t ON t.taxon_id = o.taxon_id
        WHERE o.place_kind = 'grid01' AND o.grain IN ('year', 'survey_period')
        GROUP BY y
        ORDER BY y
    """,
    "summary_grid_catalog": """
        SELECT o.place_id,
               COALESCE(SUM(CASE WHEN CAST(substr(o.period_start, 1, 4) AS INTEGER) BETWEEN 1970 AND 2026
                                 THEN o.n ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN CAST(substr(o.period_start, 1, 4) AS INTEGER) BETWEEN 1970 AND 2026
                                 THEN o.n_red_list ELSE 0 END), 0),
               COUNT(DISTINCT t.canonical_binomial),
               COUNT(DISTINCT CASE WHEN o.n_red_list > 0 THEN t.canonical_binomial END)
        FROM occurrence_agg o LEFT JOIN registry.taxon t ON t.taxon_id = o.taxon_id
        WHERE o.place_kind = 'grid01' AND o.grain IN ('year', 'survey_period')
        GROUP BY o.place_id
        ORDER BY o.place_id
    """,
}

_SELECT_ORDER = {
    "summary_variable_catalog": (
        "SELECT variable_id, obs_stat, unit_id, value_grain, grain, input_grain, "
        "n, n_places, y_from, y_to, n_censored, n_not_detected FROM summary_variable_catalog "
        "ORDER BY variable_id, obs_stat, unit_id, value_grain, grain, input_grain"
    ),
    "summary_place_variable": (
        "SELECT place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain, "
        "n, y_from, y_to, avg_zero, avg_lod, n_censored, n_not_detected FROM summary_place_variable "
        "ORDER BY place_id, variable_id, obs_stat, unit_id, value_grain, grain, input_grain"
    ),
    "summary_taxon_catalog": (
        "SELECT taxon_id, n, n_red_list, n_alien, n_places, y_from, y_to, n_years "
        "FROM summary_taxon_catalog ORDER BY taxon_id"
    ),
    "summary_watershed_occurrence": (
        "SELECT place_id, n, n_red_list, n_alien, n_taxa, y_from, y_to "
        "FROM summary_watershed_occurrence ORDER BY place_id"
    ),
    "summary_species_catalog": (
        "SELECT binom, taxon_group, class, family, n, n_red_list, n_alien, n_places, y_from, y_to, n_years "
        "FROM summary_species_catalog ORDER BY binom"
    ),
    "summary_group_year": (
        "SELECT year, taxon_group, source_id, n, n_binom, n_places "
        "FROM summary_group_year ORDER BY year, taxon_group, source_id"
    ),
    "summary_effort_year": "SELECT year, n, n_binom, n_places FROM summary_effort_year ORDER BY year",
    "summary_grid_catalog": (
        "SELECT place_id, n, n_red_list, n_binom, n_red_binom FROM summary_grid_catalog ORDER BY place_id"
    ),
}


@pytest.fixture(autouse=True)
def _registry_env(tmp_path, monkeypatch):
    """既定の registry（`taxon` だけ）を `RYUIKI_REGISTRY_DB` で指す。`join:` を宣言した
    summary が毎回 ATTACH するため、`registry_db` を渡さないテストにも要る。"""
    path = _make_registry_fixture(tmp_path)
    monkeypatch.setenv("RYUIKI_REGISTRY_DB", str(path))
    return path


def _attach_registry_for_reference(conn: sqlite3.Connection, registry_path) -> None:
    conn.execute("ATTACH DATABASE ? AS registry", (f"file:{registry_path}?mode=ro",))


def _write_yaml(tmp_path, data: dict, name: str = "serving.yaml") -> pathlib.Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _load_real_yaml() -> dict:
    return yaml.safe_load(DEFAULT_YAML.read_text(encoding="utf-8"))


def test_build_summary_creates_both_tables_and_conservation_holds(tmp_path):
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        stats = b13.build_summary(conn, DEFAULT_YAML)

        assert set(stats) == set(common.V2_SUMMARY_TABLES)
        # 機械検証4: 行数 > 0。
        assert stats["summary_variable_catalog"]["n_rows"] == 1  # 1 variable × 1 obs_stat/unit/grain 組
        assert stats["summary_place_variable"]["n_rows"] == 2  # p1・p2
        assert stats["summary_taxon_catalog"]["n_rows"] == 3  # t1・t2・taxon_id=NULL
        assert stats["summary_watershed_occurrence"]["n_rows"] == 3  # w1・w2・place_id=NULL
        assert stats["summary_species_catalog"]["n_rows"] == 2  # Aus bus・Cus dus（taxon_id NULL は含まない）
        assert stats["summary_effort_year"]["n_rows"] == 2  # 2020・2021

        # 機械検証3の裏付け: filter 対象外の3行（watershed/非mean/month、
        # n=999/888/777）は一切含まれない——含まれていれば SUM(n) が
        # 22（=10+5+7）から大きくずれる。
        cat_total = conn.execute("SELECT SUM(n) FROM summary_variable_catalog").fetchone()[0]
        place_total = conn.execute("SELECT SUM(n) FROM summary_place_variable").fetchone()[0]
        assert cat_total == 22
        assert place_total == 22
        assert stats["summary_variable_catalog"]["sum_n"] == 22
        assert stats["summary_place_variable"]["sum_n"] == 22

        cat_row = conn.execute(
            "SELECT n, n_places, y_from, y_to, n_censored, n_not_detected FROM summary_variable_catalog"
        ).fetchone()
        assert cat_row == (22, 2, 2020, 2021, 3, 0)  # n_places は distinct place_id（p1, p2）

        place_rows = {
            r[0]: r for r in conn.execute(
                "SELECT place_id, n, y_from, y_to, avg_zero, avg_lod, n_censored "
                "FROM summary_place_variable"
            )
        }
        assert place_rows["p1"] == ("p1", 15, 2020, 2021, 2.0, 2.1, 1)
        assert place_rows["p2"] == ("p2", 7, 2020, 2020, 5.0, 5.2, 2)

        # 機械検証3の裏付け（occurrence_agg 側）: grid01×month（n=999）・
        # watershed×month（n=888）は一切含まれない——含まれていれば SUM(n) が
        # 大きくずれる。summary_taxon_catalog は 29（=10+5+7+3+4）、
        # summary_watershed_occurrence は 17（=6+2+9）。
        taxon_total = conn.execute("SELECT SUM(n) FROM summary_taxon_catalog").fetchone()[0]
        watershed_total = conn.execute("SELECT SUM(n) FROM summary_watershed_occurrence").fetchone()[0]
        assert taxon_total == 29
        assert watershed_total == 17
        assert stats["summary_taxon_catalog"]["sum_n"] == 29
        assert stats["summary_watershed_occurrence"]["sum_n"] == 17

        taxon_rows = {
            r[0]: r for r in conn.execute(
                "SELECT taxon_id, n, n_red_list, n_alien, n_places, y_from, y_to, n_years "
                "FROM summary_taxon_catalog"
            )
        }
        # t1: year(g1,10,2,1) + year(g2,5,0,0) + survey_period(g1,4,0,1)。
        # n_places は distinct place_id（g1, g2）＝2、n_years は distinct
        # 開始年（2020, 2021, 2020）＝2。
        assert taxon_rows["t1"] == ("t1", 19, 2, 2, 2, 2020, 2021, 2)
        assert taxon_rows["t2"] == ("t2", 7, 1, 0, 1, 2020, 2020, 1)
        assert taxon_rows[None] == (None, 3, 0, 0, 1, 2020, 2020, 1)  # taxon_id 未解決

        watershed_rows = {
            r[0]: r for r in conn.execute(
                "SELECT place_id, n, n_red_list, n_alien, n_taxa, y_from, y_to "
                "FROM summary_watershed_occurrence"
            )
        }
        assert watershed_rows["w1"] == ("w1", 6, 1, 0, 1, 2020, 2020)
        assert watershed_rows["w2"] == ("w2", 9, 3, 2, 1, 2021, 2021)
        assert watershed_rows[None] == (None, 2, 0, 0, 1, 2020, 2020)  # 流域に解決できない記録
    finally:
        conn.close()


def test_build_summary_matches_independent_reference_sql(tmp_path, _registry_env):
    """機械検証3の裏付け: b13 が生成した SQL とは別に手書きした `_REFERENCE_SQL`
    でキューブ（observation_agg/occurrence_agg）を直接再集計し、実際に
    作られた summary 表の内容と一致することを確認する（宣言〔YAML〕を読む
    コード自身のバグを、宣言を経由しない別実装で検出する）。
    """
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        b13.build_summary(conn, DEFAULT_YAML)
        _attach_registry_for_reference(conn, _registry_env)
        for table_name, reference_sql in _REFERENCE_SQL.items():
            expected = conn.execute(reference_sql).fetchall()
            actual = conn.execute(_SELECT_ORDER[table_name]).fetchall()
            assert actual == expected, table_name
    finally:
        conn.close()


def test_build_summary_raises_when_observation_agg_is_stale(tmp_path):
    """段階間の指紋（`assert_stage_fingerprint_fresh`）: observation_agg の
    中身を、指紋を記録し直さずに変えると（b04 未実行のまま再実行、を模す）
    `common.MigrationError` で止まる。`common.V2_SUMMARY_TABLES` の先頭2表は
    observation_agg 由来なので、occurrence_agg フィクスチャが無くてもこの
    表構築ループの1周目（`summary_variable_catalog`）で止まる——
    occurrence_agg の指紋確認まで到達しない（`build_summary` の「source ごと
    の指紋確認は初めてその source を使う表に出会った時点で行う」docstring
    参照）。
    """
    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        conn.execute(
            "UPDATE observation_agg SET n = 12345 WHERE place_id = 'p1' AND period_start = '2020-01-01'"
        )
        conn.commit()
        with pytest.raises(common.MigrationError, match="scripts/b04_build_cube.py"):
            b13.build_summary(conn, DEFAULT_YAML)
    finally:
        conn.close()


def test_build_summary_raises_when_occurrence_agg_is_stale(tmp_path):
    """段階間の指紋: occurrence_agg の中身を、指紋を記録し直さずに変えると
    （b07 未実行のまま再実行、を模す）`common.MigrationError` で止まる。
    観測側（observation_agg）は正常なので、先頭2表（summary_variable_catalog/
    summary_place_variable）は問題なく通り、3表目の summary_taxon_catalog に
    到達して初めて止まる。
    """
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        conn.execute(
            "UPDATE occurrence_agg SET n = 12345 WHERE place_id = 'g1' AND grain = 'year'"
        )
        conn.commit()
        with pytest.raises(common.MigrationError, match="scripts/b07_build_occurrence_cube.py"):
            b13.build_summary(conn, DEFAULT_YAML)
    finally:
        conn.close()


def test_build_summary_raises_when_filter_matches_no_rows(tmp_path):
    """機械検証4（行数 > 0）: filter が絞りすぎて0行になれば止まる。
    `_ROWS` に `grain='fiscal_year'` の行は無いので、filter をそちらだけに
    絞ったYAMLを使えば必ず0行になる。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["filter"]["grain"] = ["fiscal_year"]
    raw["summaries"]["summary_place_variable"]["filter"]["grain"] = ["fiscal_year"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="0行"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_fn(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["measures"]["n"]["fn"] = "median"  # 未知
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="fn が未知"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_measure_column(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["measures"]["n"]["col"] = "not_a_real_column"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="col が未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_unknown_filter_column(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["filter"]["n"] = 1  # n は次元キーではない
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match=r"filter\..* が未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_when_occurrence_agg_summary_missing_grain_filter(tmp_path):
    """`source: occurrence_agg` の summary は `filter.grain` が必須（PR-3a §9-2）。
    書き忘れると、月族の二重計上を保存則（同じ〔絞り込み忘れの〕filter どうし
    の比較）が検出できないため、YAML の語彙検証（機械検証1）の段階で止める。
    """
    raw = _load_real_yaml()
    del raw["summaries"]["summary_taxon_catalog"]["filter"]["grain"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)  # occurrence_agg は不要（DB に触る前に止まる）
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="filter に必須の列が無い"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_when_occurrence_agg_grain_filter_spans_families(tmp_path):
    """`filter.grain` は列があるだけでは不十分——値が `b07.YEAR_GRAIN_FAMILY`
    （`year`/`survey_period`）か `b07.MONTH_GRAIN_FAMILY`（`month`）のどちらか
    1つの族にちょうど収まっていなければ止める。`[year, month]` のように族を
    跨ぐ値は月族を二重に数える事故を招くため、有無だけのチェックでは検出
    できなかった（/code-review 指摘5の回帰）。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_taxon_catalog"]["filter"]["grain"] = ["year", "month"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)  # occurrence_agg は不要（DB に触る前に止まる）
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="filter.grain が族に収まっていない"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_when_occurrence_agg_grain_filter_is_unknown_value(tmp_path):
    """族に属さない値（例: 未知の grain `'week'`）も同じ検証で止める。"""
    raw = _load_real_yaml()
    raw["summaries"]["summary_watershed_occurrence"]["filter"]["grain"] = ["week"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="filter.grain が族に収まっていない"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_cross_source_filter_column(tmp_path):
    """source をまたいだ列名の流用は許さない: `summary_taxon_catalog`
    （source: occurrence_agg）の filter に observation_agg にしかない次元キー
    （`obs_stat`）を書くと止まる。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_taxon_catalog"]["filter"]["obs_stat"] = "mean"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match=r"filter\..* が未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_cross_source_group_by_column(tmp_path):
    """source をまたいだ列名の流用は許さない: `summary_taxon_catalog`
    （source: occurrence_agg）の group_by に observation_agg にしかない次元キー
    （`variable_id`）を足すと止まる。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_taxon_catalog"]["group_by"].append("variable_id")
    raw["summaries"]["summary_taxon_catalog"]["key"].append("variable_id")
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="group_by に未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_cross_source_measure_column(tmp_path):
    """source をまたいだ列名の流用は許さない: `summary_taxon_catalog`
    （source: occurrence_agg）の測度に observation_agg にしかない値列
    （`value_zero`）を書くと止まる。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_taxon_catalog"]["measures"]["n"]["col"] = "value_zero"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="col が未知の列"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_key_not_matching_group_by(tmp_path):
    raw = _load_real_yaml()
    raw["summaries"]["summary_variable_catalog"]["key"] = ["variable_id"]  # group_by と不一致
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="key は group_by と同じ集合"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_on_spec_version_mismatch(tmp_path):
    raw = _load_real_yaml()
    raw["spec_version"] = "serving-summary/v999"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="SUMMARY_SPEC_VERSION"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_raises_when_summaries_table_set_does_not_match(tmp_path):
    raw = _load_real_yaml()
    del raw["summaries"]["summary_place_variable"]
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="V2_SUMMARY_TABLES"):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()


def test_build_summary_validates_all_tables_before_writing_any_sql(tmp_path):
    """機械検証1は summary 2表**両方**を、SQL を1つも投げる前に検証する
    （`build_summary` docstring 参照）——1表目（`summary_variable_catalog`）は
    正しいが2表目（`summary_place_variable`）の宣言が壊れているとき、1表目も
    作られない（作られてしまうと、次回失敗時に1表目だけ新しく2表目だけ
    古いという食い違った状態が残る）。
    """
    raw = _load_real_yaml()
    raw["summaries"]["summary_place_variable"]["measures"]["n"]["fn"] = "median"
    yaml_path = _write_yaml(tmp_path, raw)

    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="fn が未知"):
            b13.build_summary(conn, yaml_path)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'summary_%'"
            )
        }
        assert tables == set(), f"検証失敗にもかかわらず summary 表が作られている: {tables}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Issue #48 PR-3b（D1）: registry の taxon を結合した binom 単位の4表
# ---------------------------------------------------------------------------

def _build_binom_fixture(tmp_path):
    db_path = _make_combined_fixture(tmp_path, occ_rows=_OCC_ROWS + _OCC_ROWS_BINOM_EXTRA)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    stats = b13.build_summary(conn, DEFAULT_YAML)
    return conn, stats


def test_binom_tables_collapse_taxa_sharing_a_binomial(tmp_path):
    conn, _ = _build_binom_fixture(tmp_path)
    try:
        # t1（19）+ t3（20）が `Aus bus` に束ねられる。t4（binom 無し）・taxon_id NULL は出ない。
        rows = {r[0]: r for r in conn.execute(
            "SELECT binom, taxon_group, class, family, n, n_red_list, n_alien, n_places, y_from, y_to, n_years "
            "FROM summary_species_catalog"
        )}
        assert set(rows) == {"Aus bus", "Cus dus"}
        # MAX(taxon_group)＝'鳥類' と '哺乳類' の文字列比較で大きい方（v1 の MAX と同じ規則）。
        assert rows["Aus bus"][1] == max("鳥類", "哺乳類")
        assert rows["Aus bus"][4:] == (39, 7, 2, 2, 2020, 2021, 2)
        # 窓外の 1950 年のセルも種カタログには入る（窓は問い合わせで掛ける）。
        assert rows["Cus dus"][4:] == (7 + 100, 1 + 40, 0, 2, 1950, 2020, 2)
    finally:
        conn.close()


def test_group_year_folds_unresolved_and_binomless_into_group(tmp_path):
    conn, _ = _build_binom_fixture(tmp_path)
    try:
        rows = {(r[0], r[1], r[2]): r[3:] for r in conn.execute(
            "SELECT year, taxon_group, source_id, n, n_binom, n_places FROM summary_group_year"
        )}
        # taxon_id NULL（g3、n=3）は '未判定'。
        assert rows[(2020, "未判定", "gbif")] == (3, 0, 1)
        # t4（binom 無し）は '植物' に n=11 を持つが n_binom は 0。
        assert rows[(2020, "植物", "gbif")] == (11, 0, 1)
        # inat の t3 は '哺乳類'（t1 の '鳥類' とは別行）。
        assert rows[(2020, "哺乳類", "inat")] == (20, 1, 1)
        assert rows[(1950, "昆虫", "gbif")] == (100, 1, 1)
        total = conn.execute("SELECT SUM(n) FROM summary_group_year").fetchone()[0]
        assert total == 29 + 20 + 11 + 100
    finally:
        conn.close()


def test_effort_year_counts_binom_not_taxon_id(tmp_path):
    conn, _ = _build_binom_fixture(tmp_path)
    try:
        rows = {r[0]: r[1:] for r in conn.execute("SELECT year, n, n_binom, n_places FROM summary_effort_year")}
        # 2020: t1・t2・t3・t4・NULL のセルがあるが、binom は Aus bus・Cus dus の2つ（t1==t3）。
        assert rows[2020] == (10 + 7 + 3 + 4 + 20 + 11, 2, 2)  # n_places: g1・g3
    finally:
        conn.close()


def test_grid_catalog_bakes_the_year_window_but_not_the_binom_counts(tmp_path):
    conn, stats = _build_binom_fixture(tmp_path)
    try:
        rows = {r[0]: r[1:] for r in conn.execute(
            "SELECT place_id, n, n_red_list, n_binom, n_red_binom FROM summary_grid_catalog"
        )}
        # g4 は窓外（1950）のセルだけ: n=0 でも1行出て、n_binom（窓なし）は 1、n_red_binom も 1。
        assert rows["g4"] == (0, 0, 1, 1)
        # g1: t1(10,2)+t2(7,1)+t1 survey(4,0)+t3(20,5)+t4(11,0)。n_red_list>0 の binom は Aus bus・Cus dus。
        assert rows["g1"] == (10 + 7 + 4 + 20 + 11, 2 + 1 + 5, 2, 2)
        # g3: taxon_id NULL のみ。binom は 0 個。
        assert rows["g3"] == (3, 0, 0, 0)
        # 保存則は窓つきの n で数える（窓外の 100 は入らない）。
        assert stats["summary_grid_catalog"]["sum_n"] == 10 + 5 + 7 + 3 + 4 + 20 + 11
    finally:
        conn.close()


def test_binom_tables_match_independent_reference_sql(tmp_path, _registry_env):
    conn, _ = _build_binom_fixture(tmp_path)
    try:
        _attach_registry_for_reference(conn, _registry_env)
        for table_name in (
            "summary_species_catalog", "summary_group_year", "summary_effort_year", "summary_grid_catalog",
        ):
            assert conn.execute(_SELECT_ORDER[table_name]).fetchall() == \
                conn.execute(_REFERENCE_SQL[table_name]).fetchall(), table_name
    finally:
        conn.close()


def test_pipeline_fingerprint_records_registry_lineage_for_joined_tables(tmp_path):
    conn, _ = _build_binom_fixture(tmp_path)
    try:
        import json
        inputs = json.loads(conn.execute(
            "SELECT inputs FROM pipeline_fingerprint WHERE table_name='summary_species_catalog'"
        ).fetchone()[0])
        assert set(inputs) == {"occurrence_agg", "registry:taxon"}
        plain = json.loads(conn.execute(
            "SELECT inputs FROM pipeline_fingerprint WHERE table_name='summary_taxon_catalog'"
        ).fetchone()[0])
        assert set(plain) == {"occurrence_agg"}
        # registry は読み取り専用で ATTACH し、終わったら外す。
        assert "registry" not in {r[1] for r in conn.execute("PRAGMA database_list")}
    finally:
        conn.close()


def test_build_summary_stops_when_registry_is_missing(tmp_path):
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="r01_build_registry"):
            b13.build_summary(conn, DEFAULT_YAML, registry_db=tmp_path / "nonexistent.sqlite")
    finally:
        conn.close()


def test_build_summary_stops_when_registry_has_no_taxon_table(tmp_path):
    empty = tmp_path / "empty_registry.sqlite"
    sqlite3.connect(empty).close()
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="taxon 表が無い"):
            b13.build_summary(conn, DEFAULT_YAML, registry_db=empty)
        assert "registry" not in {r[1] for r in conn.execute("PRAGMA database_list")}
    finally:
        conn.close()


def test_build_summary_stops_when_taxon_join_multiplies_rows(tmp_path):
    """結合先の taxon_id が一意でないと SUM(n) が増える——保存則（結合前後）で止める。"""
    dup = _make_registry_fixture(
        tmp_path, _TAXON_ROWS + [("t1", "Aus bus", "鳥類", "Aves", "Fam1")],
        name="dup_registry.sqlite", primary_key=False,
    )
    db_path = _make_combined_fixture(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="registry との結合で SUM"):
            b13.build_summary(conn, DEFAULT_YAML, registry_db=dup)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda raw: raw["summaries"]["summary_species_catalog"].__setitem__("join", {"place": "registry"}),
         "join に未知の表"),
        (lambda raw: raw["summaries"]["summary_species_catalog"].__setitem__("join", {"taxon": "elsewhere"}),
         "registry' だけが許される"),
        (lambda raw: raw["summaries"]["summary_species_catalog"]["measures"]["family"].__setitem__(
            "col", "taxon.gbif_taxon_key"), "未知の結合先の列"),
        (lambda raw: raw["summaries"]["summary_species_catalog"]["measures"]["family"].__setitem__(
            "col", "taxon.family") or raw["summaries"]["summary_species_catalog"].__delitem__("join"),
         "宣言していない join の列"),
        (lambda raw: raw["summaries"]["summary_grid_catalog"]["measures"]["n"]["when"].__setitem__("bogus", 1),
         "未知のキー"),
        (lambda raw: raw["summaries"]["summary_grid_catalog"]["measures"]["n"]["when"].__setitem__(
            "year_between", [2026, 1970]), "year_between"),
        (lambda raw: raw["summaries"]["summary_effort_year"]["columns"]["year"].__setitem__("col", "n"),
         "どちらか一方だけ"),
        (lambda raw: raw["summaries"]["summary_species_catalog"]["filter"].__setitem__("place_kind", {"not_null": True}),
         "not_null は結合先の列にだけ"),
        (lambda raw: raw["summaries"]["summary_variable_catalog"].__setitem__("join", {"taxon": "registry"}),
         "には使えない"),
    ],
)
def test_build_summary_rejects_bad_join_vocabulary(tmp_path, mutate, match):
    raw = _load_real_yaml()
    mutate(raw)
    yaml_path = _write_yaml(tmp_path, raw)
    db_path = make_observation_agg_fixture(tmp_path, _ROWS)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match=match):
            b13.build_summary(conn, yaml_path)
    finally:
        conn.close()
