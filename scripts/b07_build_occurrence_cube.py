#!/usr/bin/env python3
"""`occurrence`（`data/db/v2.sqlite`、b06 が作ったファクト）から、ADR-0025 D2 の
キューブ `occurrence_agg` を作る（ADR-0016 Phase B「ファクトとキューブ」O-1b。
番号は ADR-0025 の時点で予約済み）。

    .venv/bin/python3 scripts/b07_build_occurrence_cube.py

`data/db/v2.sqlite` に `occurrence_agg` テーブルを（作り直して）追加する
（`observation`/`observation_agg`/`occurrence` と同居。b04/b06 と同じ理由で
v2.sqlite をファイルごと作り直さない——テーブル単位で `migrate.common.staged_table`
を使う）。**入力（`occurrence`）は一切変更しない（`SELECT` するだけ）。**

## 対象は日付のある記録だけ（ADR-0025 D2）

`occurrence.period_raw IS NOT NULL` の816,856行だけがキューブに入る。日付の
無い6,836行はキューブの対象外（L2 にはそのまま残る。ADR-0007 原則1）。

## 鍵と値（ADR-0025 D2・O-1 設計 v2 D2）

    region_id, source_id, place_id, taxon_id, grain, period_start, period_end

値は `n`（記録数）・`n_red_list`（`red_list_category` の原表記が NULL でも
`''` でもない記録の数。v1 の `mesh_year.rl_n`・`mesh_species.rl_species_n` と
同じ定義）。`n_distinct_taxon` は taxon 粒度で非加法なので持たない
（ADR-0025 D2）。`taxon_id`/`place_id` が NULL のセルも持つ（データを落とさない）。

## `grain ∈ {year, survey_period}` の判定（ADR-0025 D2）

`occurrence.period_start`/`period_end`（b06 が展開済み。時刻帯なしのローカル
時刻）の年が一致する記録（day/instant/month/year と、同年内に収まる区間）は
`grain='year'`——キューブのセルは `date(period_start, 'start of year')` 〜
`date(period_start, 'start of year', '+1 year', '-1 day')`（暦年境界へ正規化。
`scripts/b04_build_cube.py` の `_year_from_day_stats_sql` と同じ考え方）に
**丸める**。年が食い違う記録（年をまたぐ区間。実測1,191行）は
`grain='survey_period'`（leaf）——セルの `period_start`/`period_end` は記録
自身の区間**そのもの**（丸めない。セルの宣言する期間＝メンバーの期間なので
ADR-0024 決定3を破らない）。

`date()` に `period_start`/`period_end` をそのまま渡してよい——b06 の T1
不変条件（`occurrence` は時刻帯（`+`/`Z`）を一切持たない）により、CLAUDE.md
が禁じる「`+09:00` 付き文字列に SQLite の日時関数を使う」に該当しない
（`docs/adr/0024-local-time-and-time-labels.md`）。

この2つの `grain` で、日付のある全記録がちょうど1つのセルに入る
（キューブ＝L2 の分割。ADR-0025 D2）。

## `built_from` に SQLite バージョンを埋め込まない（b04 との相違点）

`scripts/b04_build_cube.py`（`observation_agg`）は `AVG()`/`SUM()` の
浮動小数点加算アルゴリズムが SQLite 3.43 で変わる問題（ADR-0021 決定3）を
踏まえ、`built_from` に `sqlite=...` を埋め込んで検証する。このキューブの値
（`n`/`n_red_list`）は整数の `COUNT()`/`SUM(CASE ...)` だけで、SQLite の
`SUM()` は整数列に対しては常に厳密な64bit整数和を返す（浮動小数点の丸め誤差
やバージョン依存の加算アルゴリズムの対象外）。そのため ADR-0021 決定3の
検証は適用対象が無く、`built_from` はバージョンを含まない `'occurrence'`
（入力テーブル名）に留める。ADR-0025 D2 が明示する「共通」の規律（
`staged_table`・`COALESCE(c,'') の UNIQUE INDEX`・`built_from`/`spec_version`）
はそのまま満たす。

## 機械検証（1つでも失敗すれば `common.MigrationError` で止まる）

- (i) 系列（`source_id`, `taxon_id`。`taxon_id IS NULL` を含む）ごとに
  `Σn(year+leaf) = occurrence の日付あり行数`、`Σn_red_list` も同様
  （`_assert_series_totals_match_l2`）。
- (ii) leaf セル（`grain='survey_period'`）に入る元の記録数を
  `scripts/migrate/occurrence_cube_declarations.yaml` の宣言値（1,191）と
  照合する（`_assert_leaf_source_row_count`）。宣言の構造検証
  （必須キー・宣言名の過不足）も実行のたびに行う。
- (iii) 各記録がちょうど1つのセルに入ることを明示的に確かめる: 年セルに
  入る記録数 + leaf セルに入る記録数 = 日付あり行数（`_assert_partition_covers_all_dated_rows`。
  (i) で系列ごとに保証されるのと同じ結果を、系列に分けず全体でも直接確認する）。
- 次元キーの一意性（`COALESCE(c,'') の UNIQUE INDEX`。`scripts/b04_build_cube.py`
  の C-3 と同じ）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common, period  # noqa: E402

DEFAULT_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_DECLARATIONS_YAML = ROOT / "scripts" / "migrate" / "occurrence_cube_declarations.yaml"

# `built_from` の既定値。b04 と違いバージョンを含まない（モジュール docstring
# 「built_from に SQLite バージョンを埋め込まない」参照）。
DEFAULT_BUILT_FROM = "occurrence"

# ADR-0025 D2 の次元キー。列順はそのまま `occurrence_agg` の列順の先頭に使う。
DIM_COLUMNS = ["region_id", "source_id", "place_id", "taxon_id", "grain", "period_start", "period_end"]

REQUIRED_DECLARATION_KEYS = ("expected_row_count", "note")
_LEAF_DECLARATION_NAME = "leaf_cell_source_rows"

_CREATE_OCCURRENCE_AGG_SQL = f"""
CREATE TABLE {{table}} (
  region_id     TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  place_id      TEXT,
  taxon_id      TEXT,
  grain         TEXT NOT NULL,
  period_start  TEXT NOT NULL,
  period_end    TEXT NOT NULL,
  n             INTEGER NOT NULL,
  n_red_list    INTEGER NOT NULL,
  built_from    TEXT NOT NULL,
  spec_version  TEXT NOT NULL
)
"""

# `red_list_category` の原表記が NULL でも '' でもない、の判定式（v1 の
# mesh_year.rl_n・mesh_species.rl_species_n と同じ定義。O-1b brief 参照）。
_RED_LIST_NONEMPTY_EXPR = "red_list_category IS NOT NULL AND red_list_category <> ''"

_DIM_SELECT = ", ".join(DIM_COLUMNS[:4])  # region_id, source_id, place_id, taxon_id

_INSERT_COLUMNS = DIM_COLUMNS + ["n", "n_red_list", "built_from", "spec_version"]

# 年セル: 期間が1つの暦年に収まる記録（day/instant/month/year と、同年内の
# 区間）。セルの period_start/period_end は暦年境界へ丸める
# （`date(..., 'start of year')`。b04 の `_year_from_day_stats_sql` と同じ
# 考え方）。
_YEAR_CELLS_SQL = f"""
SELECT {_DIM_SELECT}, 'year' AS grain,
       date(period_start, 'start of year') AS period_start,
       date(period_start, 'start of year', '+1 year', '-1 day') AS period_end,
       COUNT(*) AS n,
       SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list,
       ? AS built_from, ? AS spec_version
FROM occurrence
WHERE period_raw IS NOT NULL AND substr(period_start, 1, 4) = substr(period_end, 1, 4)
GROUP BY {_DIM_SELECT}, date(period_start, 'start of year')
"""

# leaf セル: 年をまたぐ区間。period_start/period_end は記録自身の区間その
# もの（丸めない）。
_LEAF_CELLS_SQL = f"""
SELECT {_DIM_SELECT}, 'survey_period' AS grain,
       period_start, period_end,
       COUNT(*) AS n,
       SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list,
       ? AS built_from, ? AS spec_version
FROM occurrence
WHERE period_raw IS NOT NULL AND substr(period_start, 1, 4) <> substr(period_end, 1, 4)
GROUP BY {_DIM_SELECT}, period_start, period_end
"""

_DATED_ROW_COUNT_SQL = "SELECT COUNT(*) FROM occurrence WHERE period_raw IS NOT NULL"
_YEAR_SOURCE_ROW_COUNT_SQL = (
    "SELECT COUNT(*) FROM occurrence "
    "WHERE period_raw IS NOT NULL AND substr(period_start, 1, 4) = substr(period_end, 1, 4)"
)
_LEAF_SOURCE_ROW_COUNT_SQL = (
    "SELECT COUNT(*) FROM occurrence "
    "WHERE period_raw IS NOT NULL AND substr(period_start, 1, 4) <> substr(period_end, 1, 4)"
)

_L2_SERIES_TOTALS_SQL = f"""
SELECT source_id, taxon_id, COUNT(*) AS n,
       SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list
FROM occurrence
WHERE period_raw IS NOT NULL
GROUP BY source_id, taxon_id
"""

_SAMPLE_LIMIT = 20


def validate_cube_declarations_shape(path=DEFAULT_DECLARATIONS_YAML) -> None:
    """`occurrence_cube_declarations.yaml` の構造を検証する（原本DBを必要と
    しない。CI 用、かつ b07 も実行時に呼ぶ。`occurrence_period_shapes.yaml` の
    `validate_occurrence_period_shapes_shape()` と同じ流儀——必須キーの検査は
    `period.required_keys_problems()`、整数検査は `period.validate_expected_row_count()`
    に委ねる）。宣言された名前の集合が `{_LEAF_DECLARATION_NAME}` 1件と過不足
    なく一致することも確認する。
    """
    raw = common.load_yaml(path)
    if not isinstance(raw, dict):
        raise common.MigrationError(f"{path} がマッピングになっていない（実際の型: {type(raw).__name__}）")
    problems = period.required_keys_problems(raw, REQUIRED_DECLARATION_KEYS)
    for name, spec in period.entries_with_required_keys(raw, REQUIRED_DECLARATION_KEYS).items():
        count_problem = period.validate_expected_row_count(name, spec)
        if count_problem:
            problems.append(count_problem)
    if problems:
        raise common.MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))

    declared_names = frozenset(raw)
    expected_names = frozenset({_LEAF_DECLARATION_NAME})
    if declared_names != expected_names:
        raise common.MigrationError(
            f"{path} の宣言名が想定と一致しない（期待: {sorted(expected_names)}、"
            f"実際: {sorted(declared_names)}）"
        )


def _load_leaf_expected_row_count(path=DEFAULT_DECLARATIONS_YAML) -> int:
    raw = common.load_yaml(path)
    return raw[_LEAF_DECLARATION_NAME]["expected_row_count"]


def _assert_leaf_source_row_count(conn: sqlite3.Connection, expected: int) -> int:
    """(ii): leaf セルに入る元の記録数が宣言値と一致することを確かめる。"""
    actual = conn.execute(_LEAF_SOURCE_ROW_COUNT_SQL).fetchone()[0]
    if actual != expected:
        raise common.MigrationError(
            f"occurrence_agg: grain='survey_period'（年をまたぐ区間）に入る元の記録数が"
            f"宣言（{DEFAULT_DECLARATIONS_YAML} の {_LEAF_DECLARATION_NAME}.expected_row_count）"
            f"と食い違う（宣言: {expected:,} / 実測: {actual:,}）。"
            "occurrence の入力が変わった（新しい出典・期間の追加等）可能性がある。"
            "実測が正しければ宣言値を更新すること。"
        )
    return actual


def _assert_partition_covers_all_dated_rows(conn: sqlite3.Connection, leaf_source_rows: int) -> dict:
    """(iii): 年セルに入る記録数 + leaf セルに入る記録数 = 日付あり行数
    （各記録がちょうど1つのセルに入ることの直接確認。(i) は系列ごとに同じ
    結果を保証するが、ここでは系列に分けず全体でも明示的に確かめる）。
    """
    n_dated = conn.execute(_DATED_ROW_COUNT_SQL).fetchone()[0]
    n_year = conn.execute(_YEAR_SOURCE_ROW_COUNT_SQL).fetchone()[0]
    if n_year + leaf_source_rows != n_dated:
        raise common.MigrationError(
            "occurrence_agg: 年セルの元記録数 + leaf セルの元記録数が日付あり行数と"
            f"一致しない（year={n_year:,} + leaf={leaf_source_rows:,} = {n_year + leaf_source_rows:,}、"
            f"日付あり行数={n_dated:,}）。年の一致判定（substr(period_start,1,4) = "
            "substr(period_end,1,4)）が記録を漏らす・二重に数えている可能性がある。"
        )
    return {"n_dated": n_dated, "n_year_source_rows": n_year, "n_leaf_source_rows": leaf_source_rows}


def _assert_series_totals_match_l2(conn: sqlite3.Connection, staging: str) -> int:
    """(i): 系列（source_id, taxon_id。taxon_id IS NULL を含む）ごとに
    Σn(year+leaf) = occurrence の日付あり行数、Σn_red_list も同様。
    """
    l2_totals = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(_L2_SERIES_TOTALS_SQL)}
    cube_totals = {
        (r[0], r[1]): (r[2], r[3])
        for r in conn.execute(
            f'SELECT source_id, taxon_id, SUM(n) AS n, SUM(n_red_list) AS n_red_list '
            f'FROM "{staging}" GROUP BY source_id, taxon_id'
        )
    }
    mismatches = [
        (key, l2_totals.get(key), cube_totals.get(key))
        for key in sorted(set(l2_totals) | set(cube_totals), key=lambda k: (k[0], k[1] or ""))
        if l2_totals.get(key) != cube_totals.get(key)
    ][:_SAMPLE_LIMIT]
    if mismatches:
        raise common.MigrationError(
            "occurrence_agg: 系列（source_id, taxon_id）ごとの Σn/Σn_red_list が "
            "occurrence（L2）と食い違う（キューブが記録を漏らす・二重に数えている"
            f"可能性がある。例（上限{_SAMPLE_LIMIT}件、(source_id, taxon_id), L2側(n,n_red_list), "
            f"キューブ側(n,n_red_list)）: {mismatches}）。"
        )
    return len(l2_totals)


# `scripts/b04_build_cube.py` の `_assert_dimension_key_unique` と同じ考え方
# （NULL を COALESCE で正準化した式に UNIQUE INDEX を張る。生の列に張ると
# NULL 同士が「等しくない」と扱われ GROUP BY と食い違う検出結果になる）。
_DIM_KEY_INDEX_NAME = "occurrence_agg_dim_key"


def _assert_dimension_key_unique(conn: sqlite3.Connection, staging: str) -> None:
    key_cols = ", ".join(DIM_COLUMNS)
    key_exprs = ", ".join(f"COALESCE({c}, '')" for c in DIM_COLUMNS)
    try:
        conn.execute(f'CREATE UNIQUE INDEX {_DIM_KEY_INDEX_NAME} ON "{staging}" ({key_exprs})')
    except sqlite3.IntegrityError:
        dup = conn.execute(
            f'SELECT {key_cols}, COUNT(*) c FROM "{staging}" GROUP BY {key_exprs} HAVING c > 1 LIMIT 5'
        ).fetchall()
        raise common.MigrationError(
            f"occurrence_agg の次元キーが一意でない行がある（例: {dup}）。"
            "year/leaf の集計経路が重なっている可能性がある。"
        )
    else:
        conn.execute(f'DROP INDEX IF EXISTS "{_DIM_KEY_INDEX_NAME}"')


def build_cube(
    conn: sqlite3.Connection,
    declarations_yaml=DEFAULT_DECLARATIONS_YAML,
    built_from: str = DEFAULT_BUILT_FROM,
    spec_version: str = common.SPEC_VERSION,
) -> dict:
    """`conn`（`occurrence` を持つ読み書き可能な接続）に `occurrence_agg` を作る。

    `occurrence` を変更する SQL は一切実行しない（`SELECT`のみ）。
    `occurrence_agg` 本体は `migrate.common.staged_table`（b04 の A-1 と同じ）
    で作り直す——検証まで全部通ってから本番名に差し替える。戻り値はレポート用の統計。
    """
    validate_cube_declarations_shape(declarations_yaml)
    leaf_expected = _load_leaf_expected_row_count(declarations_yaml)
    params = (built_from, spec_version)

    with common.staged_table(conn, "occurrence_agg", _CREATE_OCCURRENCE_AGG_SQL) as staging:
        insert_cols = ", ".join(_INSERT_COLUMNS)
        insert_sql = f'INSERT INTO "{staging}" ({insert_cols}) '

        n_year = conn.execute(insert_sql + _YEAR_CELLS_SQL, params).rowcount
        n_leaf = conn.execute(insert_sql + _LEAF_CELLS_SQL, params).rowcount

        leaf_source_rows = _assert_leaf_source_row_count(conn, leaf_expected)
        partition_stats = _assert_partition_covers_all_dated_rows(conn, leaf_source_rows)
        n_series = _assert_series_totals_match_l2(conn, staging)
        _assert_dimension_key_unique(conn, staging)

    return {
        "n_year_cells": n_year,
        "n_leaf_cells": n_leaf,
        "n_total_cells": n_year + n_leaf,
        "n_series_checked": n_series,
        **partition_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_DB), help="occurrence を持つ v2.sqlite（読み書き）")
    parser.add_argument("--declarations-yaml", default=str(DEFAULT_DECLARATIONS_YAML))
    args = parser.parse_args()

    db_path = pathlib.Path(args.out)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b06_build_occurrence.py` を実行すること。"
        )

    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        n_occurrence = conn.execute("SELECT COUNT(*) FROM occurrence").fetchone()[0]
        print(f"▶ 読み書き可能で開く（occurrence は変更しない）: {db_path} / occurrence {n_occurrence:,}行")
        with common.timed_step("occurrence_agg を構築") as info:
            stats = build_cube(conn, args.declarations_yaml)
            info["n"] = stats["n_total_cells"]
    finally:
        conn.close()

    print(
        f"  内訳: year={stats['n_year_cells']:,} / leaf(survey_period)={stats['n_leaf_cells']:,} / "
        f"元記録: year={stats['n_year_source_rows']:,} / leaf={stats['n_leaf_source_rows']:,} / "
        f"日付あり合計={stats['n_dated']:,} / 検証した系列数={stats['n_series_checked']:,}"
    )


if __name__ == "__main__":
    main()
