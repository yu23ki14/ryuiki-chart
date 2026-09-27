#!/usr/bin/env python3
"""`occurrence`（`data/db/v2.sqlite`、b06 が作ったファクト）と `occurrence_place`
（`data/db/v2.sqlite`、b09 が作ったサテライト）から、ADR-0025 D2・Issue #48
PR-3a の「place_kind × grain 族」の行列で `occurrence_agg` を作る
（ADR-0016 Phase B「ファクトとキューブ」O-1b・O-2b）。

    .venv/bin/python3 scripts/b07_build_occurrence_cube.py

`data/db/v2.sqlite` に `occurrence_agg` テーブルを（作り直して）追加する
（`observation`/`observation_agg`/`occurrence`/`occurrence_place` と同居。
b04/b06 と同じ理由で v2.sqlite をファイルごと作り直さない——テーブル単位で
`migrate.common.staged_table` を使う）。**入力（`occurrence`・`occurrence_place`）は
一切変更しない（`SELECT` するだけ）。**

## 対象は日付のある記録だけ（ADR-0025 D2）

`occurrence.period_raw IS NOT NULL` の816,856行だけがキューブに入る。日付の
無い6,836行はキューブの対象外（L2 にはそのまま残る。ADR-0007 原則1）。

## 「place_kind × grain 族」の行列（Issue #48 PR-3a 設計書 §1.1）

族は2つ:

- `year` 族 `{year, survey_period}`（既存。日付あり全記録の分割——年境界に
  収まる記録は `grain='year'`、年をまたぐ記録は `grain='survey_period'`）。
- `month` 族 `{month}`（同一月に収まる記録だけの分割。ADR-0024 決定3を守る
  ため、`grain='year'` の記録や月をまたぐ区間は month セルに入らない）。

`place_kind` は2つ（`PLACE_KINDS`）。このモジュールが実際に作るセルは
`CELL_FAMILIES`（grid01×year・grid01×month・watershed×year の3マス。
watershed×month は消費者が無いので作らない——足すなら `CELL_FAMILIES` に
1行足すだけでよい設計にしてある）。

`place_kind` は各セルの INSERT でリテラル（`'grid01'`/`'watershed'`）を
入れる——`occurrence.place_kind` から写さない（NULL place のセルでも族の
識別子が必ず入る）。`occurrence.place_kind` は日付あり全行で `'grid01'` の
はず（grid01 が今のところ唯一の「記録に直接ぶら下がる」place_kind）で
あることを起動時に別途確かめる（`_assert_dated_rows_are_grid01`）。

## watershed セルの解決（O-2b）

`occurrence`（日付あり）を `occurrence_place`（`place_kind='watershed'`）と
`record_id` で結合し、`place_id := occurrence_place.place_id`
（NULL のことがある——流域に解決できない記録。ADR-0025 D2「データを落とさ
ない」に従い、`place_kind='watershed', place_id NULL` のセルとして持つ）。
日付あり全行が `occurrence_place` に必ず1行（`place_kind='watershed'`）を
持つことを、セルを作る前に確かめる（`_assert_populations_complete`。b09 の
回し忘れ・別スナップショット混在を検出する——b09 は座標のある全記録が
対象で、日付あり記録はその部分集合のため、この前提が崩れていれば必ず
検出できる）。

## `grain='month' の判定（同一月に収まるか）

`substr(period_start,1,7) = substr(period_end,1,7)`（`_SAME_MONTH_EXPR`）。
月セルの `period_start`/`period_end` は暦月境界（月初日〜月末日）へ丸める
——**SQLite の日時関数は使わない**（年セルと同じ理由。ADR-0024）。月末日の
計算は Python の `calendar.monthrange()`（`_month_bounds()`）を、出現する
`YYYY-MM` の distinct 値だけに対して1回ずつ呼び、一時テーブル
`__month_bounds(ym, month_start, month_end)` に持たせて SQL 側で JOIN する
（`period_start`/`period_end` という同名列を population 側と持つと WHERE 句の
`_SAME_MONTH_EXPR`（列名を修飾しない共有述語）が曖昧になるため、一時テーブル
の列名は `month_start`/`month_end` にしてある）。`scripts/migrate/period.py`
の `month_bounds()`（`occurrence_period.py` が 'month' 形の展開に使う、
`datetime.date`/`timedelta` で「翌月1日の前日」を出す実装）と役割は同じだが、
呼び出し側の型（1件ずつ vs. distinct な YYYY-MM の集合をまとめて一時テーブル
化）が違うため、ここでは独立した薄い実装にしてある。

## 年境界の計算に SQLite の `date()` を使わない

（`_YEAR_CELLS_SQL` と同じ理由。b04 が `observation_agg` の年セルで使う
`date(period_start,'start of year')` と値は同じだが、`occurrence.period_start`/
`period_end` は `date()`/`datetime()`/`strftime()` が `+09:00` 付き文字列を
UTC へ正規化してしまう問題〔ADR-0024〕そのものへの依存を断つため、日時関数を
一切使わない）。`_assert_t1_invariant` が実行のたびに `occurrence.period_start`/
`period_end`（日付あり行）が時刻帯を持たない・10桁または19桁であることを
検証してから使う。

## 測度（Issue #48 PR-3a 決定 D3）

`n`（記録数）・`n_red_list`（`red_list_category` の原表記が NULL でも '' でも
ない記録の数。v1 の `mesh_year.rl_n`・`mesh_species.rl_species_n` と同じ定義）・
`n_alien`（`SUM(is_alien)`。`is_alien` は (source, taxon_key) ごとに一定なので
加法で正確——v1 `org_watershed.alien_n`/`watershed_rollup.org_alien_n` の
後継）。`n_distinct_taxon` は taxon 粒度で非加法なので持たない。

## `built_from` に SQLite バージョンを埋め込まない、が書き込み経路自体は3.43以降が前提

`scripts/b04_build_cube.py`（`observation_agg`）は `AVG()`/`SUM()` の
浮動小数点加算アルゴリズムが SQLite 3.43 で変わる問題（ADR-0021 決定3）を
踏まえ、`built_from` に `sqlite=...` を埋め込んで検証する。このキューブの値
（`n`/`n_red_list`/`n_alien`）は整数の `COUNT()`/`SUM(CASE ...)`/`SUM(is_alien)`
だけで、SQLite の `SUM()` は整数列に対しては常に厳密な64bit整数和を返す
（浮動小数点の丸め誤差やバージョン依存の加算アルゴリズムの対象外）。その
ため ADR-0021 決定3の検証は適用対象が無く、`built_from` はバージョンを含ま
ない `'occurrence'`（入力テーブル名）に留める。

**ただし、この書き込み経路自体は SQLite 3.43 以降が前提**（検証
（`_assert_series_totals_match_population`）が呼ぶ `scripts/migrate/common.
assert_grouped_totals_match` は `FULL OUTER JOIN`（SQLite 3.39 で追加）を
使うため、それより古い版では `sqlite3.OperationalError` で落ちる。
`build_cube()` の先頭で `common.require_sqlite_version()`（b04・b05・b08・b10
と共有するガード）を呼ぶ——`FULL OUTER JOIN` 自体が要求する最小版（3.39）
ではなく、`AVG()`/`SUM()` を使う他のスクリプトと同じ **3.43 で統一**する）。

## 機械検証（1つでも失敗すれば `common.MigrationError` で止まる）

**族×place_kind ごとの母集団を一時テーブル `__pop_grid01`/`__pop_watershed`
として1回だけ作り、以下の検証はすべてこの母集団か、実際に作ったキューブ
（`staging`）に対して行う**——`occurrence`（L2）の述語を検証のたびに数え
直すのではない（以前の実装がこの穴を持っていたことのコードレビュー指摘。
`scripts/tests/test_b07_build_occurrence_cube.py` の変異テストで再現・修正を
確認済み）。

1. **母集団の完全性**（`_assert_populations_complete`）: `__pop_grid01`/
   `__pop_watershed` の行数がどちらも「日付あり occurrence 全行数」と一致する
   （watershed 側は `occurrence_place` との JOIN が記録を落としていないかの
   検査——b09 の回し忘れ・別スナップショット混在を検出する）。
2. **系列 Σ の突合**（`_assert_series_totals_match_population`。族×place_kind
   ごと。系列は (source_id, taxon_id)）: year 族は母集団の全行、month 族は
   母集団のうち `_SAME_MONTH_EXPR` を満たす行、それぞれの Σn/Σn_red_list/
   Σn_alien が `staging`（対応する `place_kind`・`grain IN 族` で絞る）と一致する。
3. **宣言との突合**（`scripts/migrate/occurrence_cube_declarations.yaml`。4件。
   `_assert_declared_counts`）: `staging` 自身から集計した
   - leaf（`grain='survey_period'`）の Σn が `leaf_cell_source_rows`
     （grid01・watershed の両方で。記録の属性なので place_kind に依らない）。
   - year（`grain='year'`）の Σn が「日付あり行数 − leaf 宣言値」
     （grid01・watershed の両方）。
   - month（`grain='month'`、grid01）の Σn が `month_cell_source_rows`。
   - watershed の year 族を `place_id IS NOT NULL`/`IS NULL` で分けた Σn が
     `watershed_dated_resolved_rows`/`watershed_dated_unresolved_rows`。
4. **形**（`_assert_cell_shapes`）: `grain` の語彙が `GRAIN_VALUES` 以外を
   持たない。`grain='year'` の全行が暦年境界に丸められている。
   `grain='survey_period'` の全行が年をまたいでいる。`grain='month'` の全行が
   月初日始まり・同一月内・月末日終わりになっている。
5. **月セルは年セルの部分和**（`_assert_month_cells_are_subset_of_year_cells`）:
   同じ次元・同じ年で Σ(月セルの n) ≤ 対応する年セルの n、かつ対応する年
   セルが必ず存在する。
6. 次元キーの一意性（`COALESCE(c,'') の UNIQUE INDEX`。`place_kind` も鍵の
   一部——族が増えても同じ仕組みでよい）。

同じ年/月か否かの述語は `_SAME_YEAR_EXPR`/`_CROSS_YEAR_EXPR`/`_SAME_MONTH_EXPR`
の1箇所だけに持ち、セルの INSERT 側と検証側の両方がそこから作る。宣言 YAML は
`load_and_validate_cube_declarations()` が1回だけ読み、構造検証と値の取得を
同時に行う。
"""
from __future__ import annotations

import argparse
import calendar
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b09_build_occurrence_place as b09  # noqa: E402
from migrate import common, period  # noqa: E402

DEFAULT_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_DECLARATIONS_YAML = ROOT / "scripts" / "migrate" / "occurrence_cube_declarations.yaml"

# `built_from` の既定値。b04 と違いバージョンを含まない（モジュール docstring
# 「built_from に SQLite バージョンを埋め込まない」参照）。
DEFAULT_BUILT_FROM = "occurrence"

# ADR-0025 D2 の次元キー。列順はそのまま `occurrence_agg` の列順の先頭に使う。
DIM_COLUMNS = [
    "region_id", "source_id", "place_id", "place_kind", "taxon_id",
    "grain", "period_start", "period_end",
]

# Issue #48 PR-3a §0: 2つの粒度族。b08（`scripts/b08_project_occurrence_v1.py`）が
# `YEAR_GRAIN_FAMILY` を import して年キー8表の絞り込みに使う——**この2つの
# 名前は最初のコミットで確定させ、以降変えない**（U2/U4 が同じ名前を前提に
# 並行で書いている）。
YEAR_GRAIN_FAMILY = ("year", "survey_period")   # 日付あり全記録の分割
MONTH_GRAIN_FAMILY = ("month",)                  # 同一月に収まる記録だけの分割

# `staging` が実際に持ってよい grain の語彙。新しい族を足すときは、ここと
# `CELL_FAMILIES`・年キー8表の射影（`scripts/b08_project_occurrence_v1.py`。
# `GRAIN_VALUES` をこのモジュールから import して使う）を合わせて見直すこと
# ——黙って絞り込みで捨てない。
GRAIN_VALUES = YEAR_GRAIN_FAMILY + MONTH_GRAIN_FAMILY
_GRAIN_VALUES_SQL_LIST = ", ".join(repr(g) for g in GRAIN_VALUES)
_GRAIN_VALUES_LABEL = "/".join(repr(g) for g in GRAIN_VALUES)  # 例: "'year'/'survey_period'/'month'"
_YEAR_GRAIN_VALUES_SQL_LIST = ", ".join(repr(g) for g in YEAR_GRAIN_FAMILY)

GRID01_PLACE_KIND = "grid01"
WATERSHED_PLACE_KIND = b09.PLACE_KIND  # "watershed"（b09 の定義を正とする。二重に持たない）
PLACE_KINDS: tuple[str, ...] = (GRID01_PLACE_KIND, WATERSHED_PLACE_KIND)

# Issue #48 PR-3a §0 決定1: 作るセルの行列（(place_kind, 族名) の宣言表）。
# 族名は `"year"`（`YEAR_GRAIN_FAMILY`）か `"month"`（`MONTH_GRAIN_FAMILY`）。
# watershed×month（D2: 消費者が無いので作らない）を足すならここに1行足すだけ
# でよい設計にしてある（母集団・セル生成・検証はすべてこの表を読んで回る）。
CELL_FAMILIES: tuple[tuple[str, str], ...] = (
    (GRID01_PLACE_KIND, "year"),
    (GRID01_PLACE_KIND, "month"),
    (WATERSHED_PLACE_KIND, "year"),
)

_FAMILY_GRAINS = {"year": YEAR_GRAIN_FAMILY, "month": MONTH_GRAIN_FAMILY}

REQUIRED_DECLARATION_KEYS = ("expected_row_count", "note")
_LEAF_DECLARATION_NAME = "leaf_cell_source_rows"
_MONTH_DECLARATION_NAME = "month_cell_source_rows"
_WATERSHED_RESOLVED_DECLARATION_NAME = "watershed_dated_resolved_rows"
_WATERSHED_UNRESOLVED_DECLARATION_NAME = "watershed_dated_unresolved_rows"
_DECLARATION_NAMES = frozenset({
    _LEAF_DECLARATION_NAME, _MONTH_DECLARATION_NAME,
    _WATERSHED_RESOLVED_DECLARATION_NAME, _WATERSHED_UNRESOLVED_DECLARATION_NAME,
})

_CREATE_OCCURRENCE_AGG_SQL = """
CREATE TABLE {table} (
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

# `red_list_category` の原表記が NULL でも '' でもない、の判定式（v1 の
# mesh_year.rl_n・mesh_species.rl_species_n と同じ定義。O-1b brief 参照）。
_RED_LIST_NONEMPTY_EXPR = "red_list_category IS NOT NULL AND red_list_category <> ''"

# 「同じ暦年に収まる記録か」「同じ暦月に収まる記録か」の述語（1箇所だけに
# 持ち、セルの INSERT 側と検証側の両方がここから作る）。列名は
# `period_start`/`period_end` のみを参照するため、`occurrence`（生の列）にも
# 母集団の一時テーブルにも `staging`（キューブのセル。leaf/month セルは
# 丸めていないので同じ意味を保つ——leaf は記録そのもの、month は月境界に
# 丸めるが同月内なので `_SAME_MONTH_EXPR` は変わらず真）にもそのまま使える。
_SAME_YEAR_EXPR = "substr(period_start, 1, 4) = substr(period_end, 1, 4)"
_CROSS_YEAR_EXPR = f"NOT ({_SAME_YEAR_EXPR})"
_SAME_MONTH_EXPR = "substr(period_start, 1, 7) = substr(period_end, 1, 7)"

# 母集団の一時テーブルの列（`record_id` は完全性検査・デバッグ用に残す。
# セルの INSERT では使わない）。
_POP_COLUMNS = (
    "record_id", "region_id", "source_id", "place_id", "taxon_id",
    "period_start", "period_end", "red_list_category", "is_alien",
)
_POP_COLUMNS_SQL = ", ".join(_POP_COLUMNS)
# `_INSERT_COLUMNS`（≡ `DIM_COLUMNS`）の列順は
# `region_id, source_id, place_id, place_kind, taxon_id, grain, ...`——
# `place_kind` は母集団の列ではなくセルごとのリテラルなので、母集団からの
# SELECT はその位置で分割する（`{{place_kind}}` を挟んで前半/後半をつなぐ）。
_POP_DIM_SELECT_PRE = "region_id, source_id, place_id"     # place_kind の前
_POP_DIM_SELECT_POST = "taxon_id"                            # place_kind の後
_POP_DIM_GROUP_BY = "region_id, source_id, place_id, taxon_id"  # GROUP BY は順不同でよい

_POP_TABLE = {GRID01_PLACE_KIND: "__pop_grid01", WATERSHED_PLACE_KIND: "__pop_watershed"}

# grid01: `occurrence.place_id`（b06 が grid01 の解決込みで書いている）が
# そのまま使える。watershed: `occurrence_place`（b09、`place_kind='watershed'`）
# と `record_id` で結合し、`place_id` を差し替える（NULL のことがある——
# 流域に解決できない記録。ADR-0025 D2「データを落とさない」）。
_POP_SOURCE_SQL = {
    GRID01_PLACE_KIND: f"""
        SELECT {_POP_COLUMNS_SQL}
        FROM occurrence
        WHERE period_raw IS NOT NULL
    """,
    WATERSHED_PLACE_KIND: f"""
        SELECT o.record_id, o.region_id, o.source_id, op.place_id, o.taxon_id,
               o.period_start, o.period_end, o.red_list_category, o.is_alien
        FROM occurrence o
        JOIN occurrence_place op
          ON op.record_id = o.record_id AND op.place_kind = {WATERSHED_PLACE_KIND!r}
        WHERE o.period_raw IS NOT NULL
    """,
}

_MEASURE_SELECT = (
    f"COUNT(*) AS n, "
    f"SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list, "
    f"SUM(is_alien) AS n_alien"
)

# 年セル: 期間が1つの暦年に収まる記録（day/instant/month/year と、同年内の
# 区間）。セルの period_start/period_end は暦年境界へ丸める（文字列演算のみ。
# モジュール docstring「年境界の計算」参照）。`{pop_table}`/`{place_kind}` は
# `.format()` で埋める（テンプレート文字列自体は変えず、母集団テーブル名と
# place_kind リテラルだけを差し替える——`_SAME_YEAR_EXPR` を含む WHERE 句の
# テキストは常に一定なので、変異テストで文字列置換の対象にできる）。
_YEAR_CELLS_SQL = f"""
SELECT {_POP_DIM_SELECT_PRE}, '{{place_kind}}' AS place_kind, {_POP_DIM_SELECT_POST}, 'year' AS grain,
       substr(period_start, 1, 4) || '-01-01' AS period_start,
       substr(period_start, 1, 4) || '-12-31' AS period_end,
       {_MEASURE_SELECT},
       ? AS built_from, ? AS spec_version
FROM "{{pop_table}}"
WHERE {_SAME_YEAR_EXPR}
GROUP BY {_POP_DIM_GROUP_BY}, substr(period_start, 1, 4)
"""

# leaf セル: 年をまたぐ区間。period_start/period_end は記録自身の区間その
# もの（丸めない）。
_LEAF_CELLS_SQL = f"""
SELECT {_POP_DIM_SELECT_PRE}, '{{place_kind}}' AS place_kind, {_POP_DIM_SELECT_POST}, 'survey_period' AS grain,
       period_start, period_end,
       {_MEASURE_SELECT},
       ? AS built_from, ? AS spec_version
FROM "{{pop_table}}"
WHERE {_CROSS_YEAR_EXPR}
GROUP BY {_POP_DIM_GROUP_BY}, period_start, period_end
"""

# 月セル: 同一月に収まる記録。period_start/period_end は暦月境界へ丸める
# （`__month_bounds` の `month_start`/`month_end` を JOIN する。列名を
# `period_start`/`period_end` にすると `_SAME_MONTH_EXPR`（列を修飾しない
# 共有述語）が母集団側とどちらを指すか曖昧になるため、月境界の一時テーブル
# 側だけ別名にしてある）。
_MONTH_CELLS_SQL = f"""
SELECT {_POP_DIM_SELECT_PRE}, '{{place_kind}}' AS place_kind, {_POP_DIM_SELECT_POST}, 'month' AS grain,
       mb.month_start AS period_start, mb.month_end AS period_end,
       {_MEASURE_SELECT},
       ? AS built_from, ? AS spec_version
FROM "{{pop_table}}" o
JOIN "__month_bounds" mb ON mb.ym = substr(o.period_start, 1, 7)
WHERE {_SAME_MONTH_EXPR}
GROUP BY {_POP_DIM_GROUP_BY}, mb.ym
"""

_INSERT_COLUMNS = DIM_COLUMNS + ["n", "n_red_list", "n_alien", "built_from", "spec_version"]

_SAMPLE_LIMIT = 20


# ---------------------------------------------------------------------------
# T1（ADR-0024）: b07 自身も入力を信用せず確かめる
# ---------------------------------------------------------------------------

def _assert_t1_invariant(conn: sqlite3.Connection) -> None:
    """`occurrence`（日付あり行）の `period_start`/`period_end` が ADR-0024 の
    T1（時刻帯を持たない・`YYYY-MM-DD`〔10桁〕または `YYYY-MM-DDTHH:MM:SS`
    〔19桁〕のどちらか）を満たすことを確かめる。`scripts/b06_build_occurrence.py`
    が構築時に同じ不変条件を検証済みだが、`occurrence`（v2.sqlite）と
    `v2.sqlite` を読む b07 の実行は別プロセス・別タイミングでありうるため、
    ここでも入力を信用せず確認する。これが通っていることが、年境界・月境界の
    計算を `date()` を使わず文字列演算だけで行ってよい前提になる。
    """
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM occurrence
        WHERE period_raw IS NOT NULL AND (
          length(period_start) NOT IN (10, 19) OR length(period_end) NOT IN (10, 19)
          OR period_start LIKE '%+%' OR period_start LIKE '%Z%'
          OR period_end LIKE '%+%' OR period_end LIKE '%Z%'
        )
        """
    ).fetchone()[0]
    if bad:
        raise common.MigrationError(
            f"occurrence_agg: occurrence.period_start/period_end が ADR-0024 の T1"
            f"（時刻帯なし・10桁または19桁）を満たさない行が{bad}件ある。"
            "scripts/b06_build_occurrence.py の T1 検証（occurrence 構築時）を確認すること。"
        )


def _assert_dated_rows_are_grid01(conn: sqlite3.Connection) -> None:
    """日付あり `occurrence` 行の `place_kind` が全て `'grid01'` であることを
    確かめる（Issue #48 PR-3a 設計書 §1.1: grid01 セルの母集団は
    `occurrence.place_id` をそのまま使うため、この前提が崩れると grid01 の
    セルに他の place_kind の place_id が紛れ込む）。
    """
    bad = conn.execute(
        "SELECT COUNT(*) FROM occurrence WHERE period_raw IS NOT NULL AND "
        f"(place_kind IS NULL OR place_kind <> '{GRID01_PLACE_KIND}')"
    ).fetchone()[0]
    if bad:
        raise common.MigrationError(
            f"occurrence_agg: occurrence（日付あり）の place_kind が {GRID01_PLACE_KIND!r} 以外の"
            f"行が{bad}件ある。grid01 母集団は occurrence.place_id をそのまま使う前提が崩れている。"
        )


# ---------------------------------------------------------------------------
# 宣言 YAML（1回だけ読む）
# ---------------------------------------------------------------------------

def load_and_validate_cube_declarations(path=DEFAULT_DECLARATIONS_YAML, count_overlay=None) -> dict:
    """`occurrence_cube_declarations.yaml` を読み、構造を検証してから返す
    （`occurrence_period_shapes.yaml` の `validate_occurrence_period_shapes_shape()`
    と同じ流儀——必須キーの検査は `period.required_keys_problems()`、整数検査は
    `period.validate_expected_row_count()` に委ねる）。宣言された名前の集合が
    `_DECLARATION_NAMES`（4件）と過不足なく一致することも確認する。

    `build_cube()` はここが返した dict から値を直接取り出す——構造検証用と
    値取得用でファイルを2回読まない。

    `count_overlay`（既定 None）は `expected_row_count` だけを差し替える
    （`period.apply_count_overlay()`。Issue #29「縮小サンプル」）。
    """
    raw = common.load_yaml(path)
    if count_overlay:
        raw = period.apply_count_overlay(raw, count_overlay)
    if not isinstance(raw, dict):
        raise common.MigrationError(f"{path} がマッピングになっていない（実際の型: {type(raw).__name__}）")
    problems = period.required_keys_problems(raw, REQUIRED_DECLARATION_KEYS)
    for name, spec in period.entries_with_required_keys(raw, REQUIRED_DECLARATION_KEYS).items():
        count_problem = period.validate_expected_row_count(name, spec)
        if count_problem:
            problems.append(count_problem)
    if problems:
        raise common.MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))

    period.assert_declared_names_match(raw, _DECLARATION_NAMES, path)
    return raw


def validate_cube_declarations_shape(path=DEFAULT_DECLARATIONS_YAML) -> None:
    """CI 用: 構造検証だけを行う（戻り値は使わない呼び出し元のため。
    `.github/workflows/ci.yml` が原本DBを必要とせずに呼ぶ）。
    """
    load_and_validate_cube_declarations(path)


# ---------------------------------------------------------------------------
# 母集団（`__pop_grid01`/`__pop_watershed`）
# ---------------------------------------------------------------------------

def _materialize_populations(conn: sqlite3.Connection) -> dict[str, str]:
    """`PLACE_KINDS` それぞれの母集団を一時テーブルに1回だけ実体化する。
    戻り値は `{place_kind: 一時テーブル名}`。呼び出し元が使い終わったら
    `_drop_populations()` で消すこと。
    """
    tables: dict[str, str] = {}
    for place_kind in PLACE_KINDS:
        name = _POP_TABLE[place_kind]
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        conn.execute(f'CREATE TEMP TABLE "{name}" AS {_POP_SOURCE_SQL[place_kind]}')
        tables[place_kind] = name
    return tables


def _drop_populations(conn: sqlite3.Connection) -> None:
    for name in _POP_TABLE.values():
        conn.execute(f'DROP TABLE IF EXISTS "{name}"')


def _assert_populations_complete(conn: sqlite3.Connection, n_dated_total: int) -> dict[str, int]:
    """母集団の完全性: `__pop_grid01`/`__pop_watershed` の行数がどちらも
    「日付あり occurrence 全行数」と一致することを確かめる。

    grid01 は `occurrence.period_raw IS NOT NULL` を素通しするだけなので
    自明に一致するが、watershed は `occurrence_place` との JOIN が実際に
    全ての日付あり記録をカバーしているか（＝b09 が今の occurrence から
    作られていて、回し忘れ・別スナップショット混在が無いか）を実際に検証
    する意味がある。戻り値は `{place_kind: 母集団行数}`
    （後続の宣言突合が「日付あり行数」として使う）。
    """
    counts: dict[str, int] = {}
    for place_kind in PLACE_KINDS:
        n = conn.execute(f'SELECT COUNT(*) FROM "{_POP_TABLE[place_kind]}"').fetchone()[0]
        if n != n_dated_total:
            hint = (
                "occurrence_place（b09 の出力）が日付あり全記録をカバーしていない可能性がある"
                "（b09 の再実行漏れ・別スナップショット混在。実行順 b06 → b09 → b07 を確認すること）。"
                if place_kind == WATERSHED_PLACE_KIND
                else "occurrence（b06 の出力）の period_raw フィルタが壊れている可能性がある。"
            )
            raise common.MigrationError(
                f"occurrence_agg: 母集団 {_POP_TABLE[place_kind]}（place_kind={place_kind!r}）の"
                f"行数（{n:,}）が日付あり occurrence 全行数（{n_dated_total:,}）と一致しない。" + hint
            )
        counts[place_kind] = n
    return counts


# ---------------------------------------------------------------------------
# 月境界（Python 側で計算し、一時テーブル `__month_bounds` に持たせる）
# ---------------------------------------------------------------------------

def _month_bounds(ym: str) -> tuple[str, str]:
    """`'YYYY-MM'` から月初日・月末日を返す（SQLite の日時関数を使わない。
    `calendar.monthrange` で月末日の日数を引く）。
    """
    year, month = int(ym[:4]), int(ym[5:7])
    last_day = calendar.monthrange(year, month)[1]
    return f"{ym}-01", f"{ym}-{last_day:02d}"


def _materialize_month_bounds(conn: sqlite3.Connection, pop_table: str) -> None:
    """`pop_table`（母集団の一時テーブル）のうち `_SAME_MONTH_EXPR` を満たす
    行が持つ `YYYY-MM` の distinct 値それぞれについて、Python で月初日・月末日
    を計算し、一時テーブル `__month_bounds(ym, month_start, month_end)` に
    書く（`_MONTH_CELLS_SQL` がここに JOIN する）。
    """
    yms = [
        row[0]
        for row in conn.execute(
            f'SELECT DISTINCT substr(period_start, 1, 7) FROM "{pop_table}" WHERE {_SAME_MONTH_EXPR}'
        )
    ]
    conn.execute('DROP TABLE IF EXISTS "__month_bounds"')
    conn.execute('CREATE TEMP TABLE "__month_bounds" (ym TEXT PRIMARY KEY, month_start TEXT, month_end TEXT)')
    conn.executemany(
        'INSERT INTO "__month_bounds" VALUES (?, ?, ?)',
        [(ym, *_month_bounds(ym)) for ym in yms],
    )


def _drop_month_bounds(conn: sqlite3.Connection) -> None:
    conn.execute('DROP TABLE IF EXISTS "__month_bounds"')


# ---------------------------------------------------------------------------
# セルの構築（族×place_kind の行列。`CELL_FAMILIES` を読んで回る）
# ---------------------------------------------------------------------------

def _insert_year_family_cells(
    conn: sqlite3.Connection, staging: str, pop_table: str, place_kind: str, params: tuple,
) -> dict[str, int]:
    insert_sql = f'INSERT INTO "{staging}" ({", ".join(_INSERT_COLUMNS)}) '
    year_sql = _YEAR_CELLS_SQL.format(pop_table=pop_table, place_kind=place_kind)
    leaf_sql = _LEAF_CELLS_SQL.format(pop_table=pop_table, place_kind=place_kind)
    n_year = conn.execute(insert_sql + year_sql, params).rowcount
    n_leaf = conn.execute(insert_sql + leaf_sql, params).rowcount
    return {"year": n_year, "survey_period": n_leaf}


def _insert_month_family_cells(
    conn: sqlite3.Connection, staging: str, pop_table: str, place_kind: str, params: tuple,
) -> dict[str, int]:
    _materialize_month_bounds(conn, pop_table)
    try:
        insert_sql = f'INSERT INTO "{staging}" ({", ".join(_INSERT_COLUMNS)}) '
        month_sql = _MONTH_CELLS_SQL.format(pop_table=pop_table, place_kind=place_kind)
        n_month = conn.execute(insert_sql + month_sql, params).rowcount
    finally:
        _drop_month_bounds(conn)
    return {"month": n_month}


def _build_all_cells(
    conn: sqlite3.Connection, staging: str, pop_tables: dict[str, str], params: tuple,
) -> dict[tuple[str, str], int]:
    """`CELL_FAMILIES` の各 (place_kind, 族名) についてセルを作る。
    戻り値は `{(place_kind, grain): 作ったセル数}`。
    """
    cells: dict[tuple[str, str], int] = {}
    for place_kind, family_name in CELL_FAMILIES:
        pop_table = pop_tables[place_kind]
        if family_name == "year":
            counts = _insert_year_family_cells(conn, staging, pop_table, place_kind, params)
        else:
            counts = _insert_month_family_cells(conn, staging, pop_table, place_kind, params)
        for grain, n in counts.items():
            cells[(place_kind, grain)] = n
    return cells


# ---------------------------------------------------------------------------
# (i) 系列ごとの Σn/Σn_red_list/Σn_alien（母集団と staging を突き合わせる）
# ---------------------------------------------------------------------------

def _assert_series_totals_match_population(
    conn: sqlite3.Connection, staging: str, pop_table: str, place_kind: str, family_name: str,
) -> int:
    """族×place_kind ごとに、系列（source_id, taxon_id。taxon_id IS NULL を
    含む）ごとの Σn/Σn_red_list/Σn_alien が母集団と `staging` で一致することを
    確かめる（`common.assert_grouped_totals_match`。母集団側は year 族なら
    全行、month 族なら `_SAME_MONTH_EXPR` を満たす行だけを対象にする——
    月をまたぐ記録は month セルに一切入らないため）。

    比較は SQL の `FULL OUTER JOIN` で行う（系列数が多いため。
    `scripts/migrate/common.py` の `assert_grouped_totals_match` 参照）。
    戻り値は検証した系列数（レポート用）。
    """
    grains = _FAMILY_GRAINS[family_name]
    grain_list_sql = ", ".join(repr(g) for g in grains)
    where = "" if family_name == "year" else f"WHERE {_SAME_MONTH_EXPR}"
    left_sql = (
        f"SELECT source_id, taxon_id, {_MEASURE_SELECT} "
        f'FROM "{pop_table}" {where} GROUP BY source_id, taxon_id'
    )
    right_sql = (
        "SELECT source_id, taxon_id, SUM(n) AS n, SUM(n_red_list) AS n_red_list, SUM(n_alien) AS n_alien "
        f'FROM "{staging}" WHERE place_kind = \'{place_kind}\' AND grain IN ({grain_list_sql}) '
        "GROUP BY source_id, taxon_id"
    )
    common.assert_grouped_totals_match(
        conn, left_sql, right_sql,
        key_columns=["source_id", "taxon_id"],
        value_columns=["n", "n_red_list", "n_alien"],
        build_message=lambda rows: (
            f"occurrence_agg: 系列（place_kind={place_kind!r}, source_id, taxon_id）ごとの "
            f"Σn/Σn_red_list/Σn_alien が族={family_name!r} の母集団と食い違う（キューブが記録を"
            f"漏らす・二重に数えている、または測度の式が壊れている可能性がある。例（上限"
            f"{_SAMPLE_LIMIT}件、(source_id, taxon_id, n_母集団, n_キューブ, n_red_list_母集団, "
            f"n_red_list_キューブ, n_alien_母集団, n_alien_キューブ)）: {rows}）。"
        ),
        sample_limit=_SAMPLE_LIMIT,
    )
    return conn.execute(
        f'SELECT COUNT(*) FROM (SELECT DISTINCT source_id, taxon_id FROM "{pop_table}" {where})'
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# (ii) 宣言との突合（staging 自身から集計する）
# ---------------------------------------------------------------------------

def _assert_declared_counts(
    conn: sqlite3.Connection, staging: str, declarations: dict,
    n_dated_by_place_kind: dict[str, int], declarations_yaml,
) -> None:
    leaf_expected = declarations[_LEAF_DECLARATION_NAME]["expected_row_count"]
    month_expected = declarations[_MONTH_DECLARATION_NAME]["expected_row_count"]
    resolved_expected = declarations[_WATERSHED_RESOLVED_DECLARATION_NAME]["expected_row_count"]
    unresolved_expected = declarations[_WATERSHED_UNRESOLVED_DECLARATION_NAME]["expected_row_count"]

    sums = conn.execute(f'SELECT place_kind, grain, SUM(n) FROM "{staging}" GROUP BY place_kind, grain').fetchall()
    by_place_kind: dict[str, dict[str, int]] = {}
    for place_kind, grain, total in sums:
        by_place_kind.setdefault(place_kind, {})[grain] = total or 0

    # leaf/year（year 族。grid01・watershed の両方——記録の属性なので
    # place_kind に依らず同じ宣言値を要求する）。
    for place_kind in PLACE_KINDS:
        grains = by_place_kind.get(place_kind, {})
        leaf_n = grains.get("survey_period", 0)
        year_n = grains.get("year", 0)
        n_dated = n_dated_by_place_kind.get(place_kind, 0)
        if leaf_n != leaf_expected:
            raise common.MigrationError(
                f"occurrence_agg: place_kind={place_kind!r} の grain='survey_period'（年をまたぐ"
                f"区間）のセルの Σn が宣言（{declarations_yaml} の "
                f"{_LEAF_DECLARATION_NAME}.expected_row_count）と食い違う"
                f"（宣言: {leaf_expected:,} / 実測: {leaf_n:,}）。occurrence の入力が変わったか、"
                "年境界の判定（年セル/leaf セルの振り分け）が壊れている可能性がある。"
            )
        expected_year_n = n_dated - leaf_expected
        if year_n != expected_year_n:
            raise common.MigrationError(
                f"occurrence_agg: place_kind={place_kind!r} の grain='year' セルの Σn"
                f"（{year_n:,}）が「{place_kind} の日付あり行数 − leaf の宣言値」"
                f"（{n_dated:,} − {leaf_expected:,} = {expected_year_n:,}）と食い違う。"
                "年境界の判定が壊れている可能性がある。"
            )

    # month（grid01 のみ——CELL_FAMILIES に無い place_kind には month セルが
    # 存在しないため、そこは既定の0のまま比較される）。
    month_n = by_place_kind.get(GRID01_PLACE_KIND, {}).get("month", 0)
    if month_n != month_expected:
        raise common.MigrationError(
            f"occurrence_agg: place_kind={GRID01_PLACE_KIND!r} の grain='month' セルの Σn が宣言"
            f"（{declarations_yaml} の {_MONTH_DECLARATION_NAME}.expected_row_count）と食い違う"
            f"（宣言: {month_expected:,} / 実測: {month_n:,}）。月境界の判定が壊れている可能性がある。"
        )

    # watershed の解決/未解決（year 族の place_id NULL/NOT NULL 内訳）。
    resolved_n, unresolved_n = conn.execute(
        "SELECT SUM(CASE WHEN place_id IS NOT NULL THEN n ELSE 0 END), "
        "SUM(CASE WHEN place_id IS NULL THEN n ELSE 0 END) "
        f'FROM "{staging}" WHERE place_kind = \'{WATERSHED_PLACE_KIND}\' '
        f"AND grain IN ({_YEAR_GRAIN_VALUES_SQL_LIST})"
    ).fetchone()
    resolved_n = resolved_n or 0
    unresolved_n = unresolved_n or 0
    if resolved_n != resolved_expected:
        raise common.MigrationError(
            f"occurrence_agg: place_kind={WATERSHED_PLACE_KIND!r} の year 族で place_id が解決済み"
            f"のセルの Σn が宣言（{declarations_yaml} の "
            f"{_WATERSHED_RESOLVED_DECLARATION_NAME}.expected_row_count）と食い違う"
            f"（宣言: {resolved_expected:,} / 実測: {resolved_n:,}）。"
        )
    if unresolved_n != unresolved_expected:
        raise common.MigrationError(
            f"occurrence_agg: place_kind={WATERSHED_PLACE_KIND!r} の year 族で place_id が NULL の"
            f"セルの Σn が宣言（{declarations_yaml} の "
            f"{_WATERSHED_UNRESOLVED_DECLARATION_NAME}.expected_row_count）と食い違う"
            f"（宣言: {unresolved_expected:,} / 実測: {unresolved_n:,}）。流域への解決"
            "（occurrence_place、b09）が変わったか、母集団の構築が壊れている可能性がある。"
        )


# ---------------------------------------------------------------------------
# (iii) 形
# ---------------------------------------------------------------------------

def _assert_cell_shapes(conn: sqlite3.Connection, staging: str) -> None:
    """`staging`（実際に作ったキューブ）に対して直接検証する。

    - grain の語彙が `GRAIN_VALUES` 以外を含まない（place_kind に関わらず共通）。
    - `grain='year'` の全行が暦年境界（`<年>-01-01`〜`<年>-12-31`）に丸められている。
    - `grain='survey_period'` の全行が年をまたいでいる（`_CROSS_YEAR_EXPR`）。
    - `grain='month'` の全行が月初日始まり・同一月内・月末日終わりになっている。
    """
    bad_grain = conn.execute(
        f'SELECT DISTINCT grain FROM "{staging}" WHERE grain NOT IN ({_GRAIN_VALUES_SQL_LIST})'
    ).fetchall()
    if bad_grain:
        raise common.MigrationError(
            f"occurrence_agg: grain が {_GRAIN_VALUES_LABEL} 以外の値を持つ行がある"
            f"（{[r[0] for r in bad_grain]}）。新しい grain を足すなら、この検証と年キー8表の"
            "射影（scripts/b08_project_occurrence_v1.py）を合わせて見直すこと。"
        )

    bad_year_shape = conn.execute(
        f"""
        SELECT COUNT(*) FROM "{staging}"
        WHERE grain = 'year' AND (
          period_start <> substr(period_start, 1, 4) || '-01-01'
          OR period_end <> substr(period_start, 1, 4) || '-12-31'
        )
        """
    ).fetchone()[0]
    if bad_year_shape:
        raise common.MigrationError(
            "occurrence_agg: grain='year' なのに period_start/period_end が暦年境界"
            f"（<年>-01-01〜<年>-12-31）に丸められていない行が{bad_year_shape}件ある。"
        )

    bad_leaf_shape = conn.execute(
        f'SELECT COUNT(*) FROM "{staging}" WHERE grain = \'survey_period\' AND {_SAME_YEAR_EXPR}'
    ).fetchone()[0]
    if bad_leaf_shape:
        raise common.MigrationError(
            "occurrence_agg: grain='survey_period'（年をまたぐ区間のはず）なのに period_start/"
            f"period_end が同じ年に収まっている行が{bad_leaf_shape}件ある。"
        )

    bad_month_shape = conn.execute(
        f"""
        SELECT COUNT(*) FROM "{staging}"
        WHERE grain = 'month' AND (
          period_start NOT LIKE '____-__-01'
          OR substr(period_end, 1, 7) <> substr(period_start, 1, 7)
          OR substr(period_end, 9, 2) NOT IN ('28', '29', '30', '31')
        )
        """
    ).fetchone()[0]
    if bad_month_shape:
        raise common.MigrationError(
            "occurrence_agg: grain='month' なのに period_start/period_end が暦月境界"
            f"（月初日始まり・同一月内・月末日終わり）に丸められていない行が{bad_month_shape}件ある。"
        )


# ---------------------------------------------------------------------------
# (iv) 月セルは年セルの部分和
# ---------------------------------------------------------------------------

_MONTH_SUBSET_KEY_COLUMNS = ["place_kind", "region_id", "source_id", "place_id", "taxon_id"]


_MONTH_BY_YEAR_TABLE = "__month_by_year"
_YEAR_CELLS_BY_KEY_TABLE = "__year_cells_by_key"


def _assert_month_cells_are_subset_of_year_cells(conn: sqlite3.Connection, staging: str) -> None:
    """同じ次元・同じ年で Σ(月セルの n) が対応する年セルの n を超えない、かつ
    対応する年セルが必ず存在する（月に収まる記録は必ず同一年に収まる年セルの
    メンバーでもあるはず——ADR-0025 D2 の分割の性質から導かれる）ことを確かめる。

    **両側を一時テーブルに実体化し、結合キー `(k, yr)` に索引を張ってから
    `LEFT JOIN` する**（`common._materialized_join_tables` と同じ理由——
    `WITH` 句のサブクエリのまま `LEFT JOIN` すると、SQLite のクエリプラン
    ナは索引の無い派生表に対してネストループへ落ち、月セル（実データで
    約57万セル、次元×年で数万グループ）×年セル（同約47万+39万セル）の
    総当たりになりうる。実測: 索引無しだと10分超えても終わらず、索引を
    張ると数秒で終わる——`scripts/migrate/common.py` の
    `_materialized_join_tables` docstring「NULL を含みうる列を `IS` で JOIN
    すると自動インデックスが効かない」と同じ根の性能事故）。
    """
    key_expr = " || '|' || ".join(f"COALESCE({c}, '')" for c in _MONTH_SUBSET_KEY_COLUMNS)
    conn.execute(f'DROP TABLE IF EXISTS "{_MONTH_BY_YEAR_TABLE}"')
    conn.execute(f'DROP TABLE IF EXISTS "{_YEAR_CELLS_BY_KEY_TABLE}"')
    try:
        conn.execute(
            f'CREATE TEMP TABLE "{_MONTH_BY_YEAR_TABLE}" AS '
            f"SELECT {key_expr} AS k, substr(period_start, 1, 4) AS yr, SUM(n) AS msum "
            f'FROM "{staging}" WHERE grain = \'month\' GROUP BY k, yr'
        )
        conn.execute(f'CREATE INDEX "{_MONTH_BY_YEAR_TABLE}_key" ON "{_MONTH_BY_YEAR_TABLE}" (k, yr)')
        conn.execute(
            f'CREATE TEMP TABLE "{_YEAR_CELLS_BY_KEY_TABLE}" AS '
            f"SELECT {key_expr} AS k, substr(period_start, 1, 4) AS yr, n "
            f'FROM "{staging}" WHERE grain = \'year\''
        )
        conn.execute(
            f'CREATE UNIQUE INDEX "{_YEAR_CELLS_BY_KEY_TABLE}_key" ON "{_YEAR_CELLS_BY_KEY_TABLE}" (k, yr)'
        )
        bad = conn.execute(
            f'SELECT COUNT(*) FROM "{_MONTH_BY_YEAR_TABLE}" m '
            f'LEFT JOIN "{_YEAR_CELLS_BY_KEY_TABLE}" y ON y.k = m.k AND y.yr = m.yr '
            "WHERE y.n IS NULL OR m.msum > y.n"
        ).fetchone()[0]
    finally:
        conn.execute(f'DROP TABLE IF EXISTS "{_MONTH_BY_YEAR_TABLE}"')
        conn.execute(f'DROP TABLE IF EXISTS "{_YEAR_CELLS_BY_KEY_TABLE}"')
    if bad:
        raise common.MigrationError(
            "occurrence_agg: 月セルは年セルの部分和のはずだが、(次元, 年) ごとの Σ(月セルの n) が"
            f"対応する年セルの n を超えている、または対応する年セルが無い組み合わせが{bad}件ある。"
        )


# ---------------------------------------------------------------------------
# 次元キーの一意性
# ---------------------------------------------------------------------------

_DIM_KEY_INDEX_NAME = "occurrence_agg_dim_key"

# Issue #48 PR-1 §1・PR-3a 決定 D6: `occurrence_agg` に張る永続索引。
# 名前・列・列順は Drizzle（`web/src/db/schema-cube.ts`）が正——ここは写し。
# `scripts/tests/test_cube_index_parity.py` がマイグレーション SQL から抜いた
# 集合とこの定数の一致を機械検証する。第3索引（D6）は族×place_kind が増えた
# ことで年の地図クエリ（`place_kind`・`grain`・`period_start` で絞る）が
# 既存2索引では全表走査になるのを避けるために足す（Drizzle 側は U4 が書く）。
OCCURRENCE_AGG_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_occurrence_agg_taxon_period", ("taxon_id", "period_start")),
    ("ix_occurrence_agg_place_period", ("place_id", "period_start")),
    ("ix_occurrence_agg_kind_grain_period", ("place_kind", "grain", "period_start")),
)


def _assert_dimension_key_unique(conn: sqlite3.Connection, staging: str) -> None:
    common.assert_dimension_key_unique(
        conn, staging, DIM_COLUMNS,
        index_name=_DIM_KEY_INDEX_NAME,
        table_label="occurrence_agg",
        cause_hint="年/leaf/月の集計経路が重なっている可能性がある。",
    )


# ---------------------------------------------------------------------------
# b09 の宣言との整合（Issue #48 PR-3a 設計書 §1.1: 「両宣言の整合」）
# ---------------------------------------------------------------------------

def _assert_consistent_with_place_declarations(
    watershed_resolved_expected: int, place_declarations_yaml,
) -> None:
    """b09 の宣言（`occurrence_place_declarations.yaml` の `resolved_count`。
    「座標のある全記録」のうち解決できた件数）が、この宣言（`occurrence_agg`
    の watershed_dated_resolved_rows。「日付あり記録」のうち解決できた件数）
    以上であることを確かめる（日付あり記録は座標のある記録の部分集合——
    実データでは 733,341 ≤ 737,407）。

    `place_declarations_yaml=None`: 単体テストが明示的に渡す opt-out
    （Issue #48 PR-1 で単位の証拠検査〔`scripts/b04_build_cube.py` の
    `_assert_unit_evidence`〕を直したのと同じ流儀）。この整合検証は「両方の
    宣言ファイルが実データの値を持つとき」だけ意味を持つ——本物の
    `occurrence_place_declarations.yaml` を持たない小さな単体フィクスチャは
    `None` を渡してこの検証全体を明示的にスキップする。`None` 以外を渡した
    のにファイルが存在しなければ、ここで（`load_yaml` が）自然に例外を出して
    止まる——以前は「ファイルが無ければ黙ってスキップ」していたため、
    本番経路（`main()`）が誤ってファイルを削除・移動しても検査が黙って
    消えたまま気づけなかった（`build_cube()` の既定値
    `b09.DEFAULT_DECLARATIONS_YAML` は実ファイルなので、`main()` は明示的に
    指定しなくてもこの検証を必ず通る）。
    """
    if place_declarations_yaml is None:
        return
    raw = common.load_yaml(place_declarations_yaml)
    resolved = raw.get("resolved_count", {}).get("expected_row_count")
    if resolved is not None and resolved < watershed_resolved_expected:
        raise common.MigrationError(
            f"occurrence_agg: watershed_dated_resolved_rows の宣言（{watershed_resolved_expected:,}）が"
            f"b09 の resolved_count 宣言（{place_declarations_yaml} の {resolved:,}）を上回っている。日付あり記録は"
            "座標のある記録の部分集合のはずなので、後者が前者以上でなければならない。"
        )


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def build_cube(
    conn: sqlite3.Connection,
    declarations_yaml=DEFAULT_DECLARATIONS_YAML,
    built_from: str = DEFAULT_BUILT_FROM,
    spec_version: str = common.OCCURRENCE_AGG_SPEC_VERSION,
    count_overlay: dict[str, int] | None = None,
    place_declarations_yaml=b09.DEFAULT_DECLARATIONS_YAML,
) -> dict:
    """`conn`（`occurrence`・`occurrence_place` を持つ読み書き可能な接続）に
    `occurrence_agg` を作る。

    `occurrence`・`occurrence_place` を変更する SQL は一切実行しない
    （`SELECT`のみ）。`occurrence_agg` 本体は `migrate.common.staged_table`
    （b04 の A-1 と同じ）で作り直す——検証まで全部通ってから本番名に差し替える。
    戻り値はレポート用の統計。
    """
    common.require_sqlite_version()
    # 段階間の指紋（Issue #37 #1）: b06/b09 が最後に記録した occurrence/
    # occurrence_place の指紋と、今の内容が一致することを、集計を始める前に
    # 確認する。戻り値はどちらも occurrence_agg の系譜に使う（実行順
    # b06 → b09 → b07 に固定——占有検証（`_assert_populations_complete`）が
    # occurrence_place の内容そのものにも依存するため）。
    occurrence_fingerprint = common.assert_occurrence_fingerprint_fresh(conn)
    place_fingerprint = common.assert_stage_fingerprint_fresh(
        conn, "occurrence_place",
        rebuild_hint="scripts/b09_build_occurrence_place.py を再実行すること。",
    )
    declarations = load_and_validate_cube_declarations(declarations_yaml, count_overlay=count_overlay)
    leaf_expected = declarations[_LEAF_DECLARATION_NAME]["expected_row_count"]
    # b09 の宣言との整合（`_assert_consistent_with_place_declarations`）は
    # YAML 2つだけを読む検査で `occurrence_agg`/`conn` に一切依存しない
    # ——「全検査が通ってから差し替え」を守るため、`occurrence_agg` を作り
    # 始める前（`staged_table` に入る前）に呼ぶ。以前はここより後
    # （差し替え・索引作成の後）で呼んでいたため、この検査だけが失敗しても
    # 本番の `occurrence_agg` が既に新しい内容に差し替わってしまっていた
    # （/code-review 指摘4）。
    _assert_consistent_with_place_declarations(
        declarations[_WATERSHED_RESOLVED_DECLARATION_NAME]["expected_row_count"], place_declarations_yaml,
    )
    _assert_t1_invariant(conn)
    _assert_dated_rows_are_grid01(conn)
    n_dated_total = conn.execute("SELECT COUNT(*) FROM occurrence WHERE period_raw IS NOT NULL").fetchone()[0]
    params = (built_from, spec_version)

    with common.staged_table(
        conn, "occurrence_agg", _CREATE_OCCURRENCE_AGG_SQL,
        fingerprint_inputs={"occurrence": occurrence_fingerprint, "occurrence_place": place_fingerprint},
        fingerprint_spec_version=spec_version,
    ) as staging:
        pop_tables = _materialize_populations(conn)
        try:
            n_dated_by_place_kind = _assert_populations_complete(conn, n_dated_total)

            cells = _build_all_cells(conn, staging, pop_tables, params)

            n_series_checked = 0
            for place_kind, family_name in CELL_FAMILIES:
                n_series_checked += _assert_series_totals_match_population(
                    conn, staging, pop_tables[place_kind], place_kind, family_name,
                )

            _assert_declared_counts(conn, staging, declarations, n_dated_by_place_kind, declarations_yaml)
            _assert_cell_shapes(conn, staging)
            _assert_month_cells_are_subset_of_year_cells(conn, staging)
            _assert_dimension_key_unique(conn, staging)
        finally:
            _drop_populations(conn)
    # ここまで来たら staged_table が差し替えと同じトランザクションで
    # occurrence_agg の指紋・系譜（消費した occurrence/occurrence_place の
    # 指紋）も記録済み（Issue #37 #1）。

    # Issue #48 PR-1 §1・PR-3a 決定 D6: 索引は差し替え確定後（本番テーブル名）に張る。
    common.create_indexes(conn, "occurrence_agg", OCCURRENCE_AGG_INDEXES)

    return {
        "n_dated": n_dated_total,
        "n_dated_by_place_kind": n_dated_by_place_kind,
        "n_year_cells": cells.get((GRID01_PLACE_KIND, "year"), 0),
        "n_leaf_cells": cells.get((GRID01_PLACE_KIND, "survey_period"), 0),
        "n_month_cells": cells.get((GRID01_PLACE_KIND, "month"), 0),
        "n_watershed_year_cells": cells.get((WATERSHED_PLACE_KIND, "year"), 0),
        "n_watershed_leaf_cells": cells.get((WATERSHED_PLACE_KIND, "survey_period"), 0),
        "n_total_cells": sum(cells.values()),
        "n_leaf_source_rows": leaf_expected,
        "n_year_source_rows": n_dated_total - leaf_expected,
        "n_month_source_rows": declarations[_MONTH_DECLARATION_NAME]["expected_row_count"],
        "n_watershed_resolved_rows": declarations[_WATERSHED_RESOLVED_DECLARATION_NAME]["expected_row_count"],
        "n_watershed_unresolved_rows": declarations[_WATERSHED_UNRESOLVED_DECLARATION_NAME]["expected_row_count"],
        "n_series_checked": n_series_checked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_DB), help="occurrence/occurrence_place を持つ v2.sqlite（読み書き）")
    parser.add_argument("--declarations-yaml", default=str(DEFAULT_DECLARATIONS_YAML))
    parser.add_argument(
        "--count-overlay", default=None,
        help="data/sample/declaration_counts.yaml のようなファイル。既定は使わない（本番の実行では"
        "常に None のまま、正本の expected_row_count で検証する。Issue #29「縮小サンプル」）",
    )
    args = parser.parse_args()

    db_path = pathlib.Path(args.out)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b06_build_occurrence.py` と "
            "`.venv/bin/python3 scripts/b09_build_occurrence_place.py` を実行すること。"
        )

    count_overlay = period.resolve_count_overlay(args.count_overlay, "occurrence_cube_declarations.yaml")

    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        n_occurrence = conn.execute("SELECT COUNT(*) FROM occurrence").fetchone()[0]
        print(f"▶ 読み書き可能で開く（occurrence/occurrence_place は変更しない）: {db_path} / occurrence {n_occurrence:,}行")
        with common.timed_step("occurrence_agg を構築") as info:
            stats = build_cube(conn, args.declarations_yaml, count_overlay=count_overlay)
            info["n"] = stats["n_total_cells"]
    finally:
        conn.close()

    print(f"  日付あり合計={stats['n_dated']:,} / 検証した系列数={stats['n_series_checked']:,}")
    print("  内訳（place_kind × grain）:")
    print(f"    grid01    : year={stats['n_year_cells']:,} / leaf={stats['n_leaf_cells']:,} / month={stats['n_month_cells']:,}")
    print(
        f"    watershed : year={stats['n_watershed_year_cells']:,}（解決={stats['n_watershed_resolved_rows']:,} / "
        f"未解決={stats['n_watershed_unresolved_rows']:,}） / leaf={stats['n_watershed_leaf_cells']:,}"
    )
    print(f"  総セル数={stats['n_total_cells']:,}")


if __name__ == "__main__":
    main()
