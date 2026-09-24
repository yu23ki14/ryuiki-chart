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

    region_id, source_id, place_id, place_kind, taxon_id, grain, period_start, period_end

`place_kind` を鍵に持つ理由・O-2 との関係は ADR-0025 D2 参照（`occurrence.place_kind`
は今のところ常に `'grid01'` なので、この列を鍵に足しても他の列の値は1ビットも
変わらない）。

値は `n`（記録数）・`n_red_list`（`red_list_category` の原表記が NULL でも
`''` でもない記録の数。v1 の `mesh_year.rl_n`・`mesh_species.rl_species_n` と
同じ定義）。`n_distinct_taxon` は taxon 粒度で非加法なので持たない
（ADR-0025 D2）。`taxon_id`/`place_id` が NULL のセルも持つ（データを落とさない）。

## `grain ∈ {year, survey_period}` の判定（ADR-0025 D2）

`occurrence.period_start`/`period_end`（b06 が展開済み。時刻帯なしのローカル
時刻）の年が一致する記録（day/instant/month/year と、同年内に収まる区間）は
`grain='year'`——キューブのセルは `substr(period_start,1,4) || '-01-01'` 〜
`substr(period_start,1,4) || '-12-31'`（暦年境界へ正規化）に**丸める**。年が
食い違う記録（年をまたぐ区間。実測1,191行）は `grain='survey_period'`
（leaf）——セルの `period_start`/`period_end` は記録自身の区間**そのもの**
（丸めない。セルの宣言する期間＝メンバーの期間なので ADR-0024 決定3を
破らない）。

**年境界の計算に SQLite の `date()` を使わない**（文字列演算の
`substr(...)||'-01-01'`/`||'-12-31'` だけで求める。b04 が `observation_agg`
の年セルで使う `date(period_start,'start of year')` と値は同じだが、
`occurrence.period_start`/`period_end` は `date()`/`datetime()`/`strftime()`
が `+09:00` 付き文字列を UTC へ正規化してしまう問題〔ADR-0024〕そのものへの
依存を断つため、日時関数を一切使わない——コードレビュー指摘5）。
`_assert_t1_invariant` が実行のたびに `occurrence.period_start`/`period_end`
（日付あり行）が時刻帯を持たない・10桁または19桁であること（ADR-0024 の T1。
b06 が保証済みのはずだが、b07 自身も入力を信用せず確かめる）を検証してから
使う。

この2つの `grain` で、日付のある全記録がちょうど1つのセルに入る
（キューブ＝L2 の分割。ADR-0025 D2）。

## `built_from` に SQLite バージョンを埋め込まない、が書き込み経路自体は3.43以降が前提

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

**ただし、この書き込み経路自体は SQLite 3.43 以降が前提**（コードレビュー
指摘: 以前はここに「版の検査は要らない」と書いていたが誤りだった。「値の
計算に版依存が無い」ことと「使っている SQL 機能に版の前提が無い」ことは別）。
検証（`_assert_series_totals_match_l2`）が呼ぶ `scripts/migrate/common.
assert_grouped_totals_match` は `FULL OUTER JOIN`（SQLite 3.39 で追加）を
使うため、それより古い版では `sqlite3.OperationalError: RIGHT and FULL
OUTER JOINs are not currently supported` で落ちる（実測。古い `sqlite3`
CLI 3.37.2 で確認済み）。`build_cube()` の先頭で `common.
require_sqlite_version()`（b04・b05・b10 と共有するガード）を呼ぶ——
`FULL OUTER JOIN` 自体が要求する最小版（3.39）ではなく、`AVG()`/`SUM()` を
使う他のスクリプトと同じ **3.43 で統一**する（このパイプライン全体を
「SQLite 3.43 以降が前提」という1つの基準で揃え、機能ごとに違う最小版を
持ち込まない）。

## 機械検証（1つでも失敗すれば `common.MigrationError` で止まる）

**(ii)(iii) は L2（`occurrence`）の述語を数えるのではなく、実際に作った
キューブ（`staging`）に対して行う**（コードレビュー指摘1）。以前の実装は
`occurrence` に対して同じ年境界の述語を数え直していただけで、年セル/leaf
セルの SQL 自体の WHERE 句が壊れていても（例: 年セルが同年判定を落として
年をまたぐ記録まで飲み込む）検証側が同じ壊れた述語を使うため何も検出でき
なかった（レビュアーが実際に確認・`scripts/tests/test_b07_build_occurrence_cube.py`
の変異テストで再現・修正を確認済み）。

- (i) 系列（`place_kind`, `source_id`, `taxon_id`。`taxon_id IS NULL` を含む）
  ごとに `Σn(year+leaf) = occurrence の日付あり行数`、`Σn_red_list` も同様
  （`_assert_series_totals_match_l2`。**`place_kind` を系列の一部に含める**
  ——O-2 で `place_kind='watershed'` のセルが増えても、`place_kind` の違う
  セルどうしを1つの系列に混ぜて合計しない。今は `place_kind` が常に
  `'grid01'` なので、この変更自体は実測値に影響しない）。`occurrence`
  （816,856行）に対する `GROUP BY` は `_materialize_l2_series_totals` が
  最初に1回だけ行い、結果（約32,000行）を一時テーブルに残す——比較
  （`scripts/migrate/common.assert_grouped_totals_match` が SQL の
  `FULL OUTER JOIN` で行う。/simplify 指摘3: 系列数が約32,000にもなると、
  両側を Python の `dict` に展開して `set` 演算で突き合わせる実装は Python
  側の実行時間が支配的だった——実測 約3.6秒）・検証した系列数・
  `place_kind` ごとの日付あり行数（(ii)(iii) が使う）は、すべてこの一時
  テーブルを読むだけで済ませ、`occurrence` を何度もフルスキャンしない
  （以前は `_DATED_ROW_COUNT_SQL`/`_YEAR_SOURCE_ROW_COUNT_SQL` で
  `occurrence` を2回余分に読んでいた。実測で約6.4秒の短縮）。
- (ii)(iii) `_assert_cube_partition_and_shape`（**staging に対して**。
  `place_kind` ごとに行う——今は `'grid01'` だけ。O-2 で `'watershed'` が
  増えたら、この検証もその宣言値ぶん拡張すること）:
  - `grain` が `'year'`/`'survey_period'` 以外の値を持たない（`place_kind`
    に関わらず共通の語彙検査。そのまま）。
  - `staging` の `place_kind='grid01'` に絞った `SUM(n) GROUP BY grain` が、
    `survey_period` は `scripts/migrate/occurrence_cube_declarations.yaml`
    の宣言値（1,191）と、`year` は「(i) で得た `place_kind='grid01'` の
    日付あり行数 − leaf の宣言値」と、それぞれ一致する。
  - `grain='year'` の全行（`place_kind` に関わらず）が `period_start = <年>-01-01`
    かつ `period_end = <年>-12-31`（暦年境界に丸められている）。
  - `grain='survey_period'` の全行（`place_kind` に関わらず）が年をまたいで
    いる（`substr(period_start,1,4) <> substr(period_end,1,4)`）。
- 次元キーの一意性（`COALESCE(c,'') の UNIQUE INDEX`。`scripts/b04_build_cube.py`
  の C-3 と同じ。`place_kind` も鍵の一部として含める）。

同じ年か否かの述語は `_SAME_YEAR_EXPR` の1箇所だけに持ち、年セル/leaf セルの
INSERT 側と `_assert_cube_partition_and_shape` の検証側の両方がそこから作る
（コードレビュー指摘12）。宣言 YAML は `load_and_validate_cube_declarations()`
が1回だけ読み、構造検証と値の取得を同時に行う（以前は構造検証用と値取得用で
2回読んでいた。コードレビュー指摘12）。
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
# `place_kind` は O-2（watershed セル）の先取り——`observation_agg` の鍵の
# 並び（region_id, place_id, place_kind, ...）に合わせて place_id の直後に置く。
DIM_COLUMNS = [
    "region_id", "source_id", "place_id", "place_kind", "taxon_id",
    "grain", "period_start", "period_end",
]

# `staging` が実際に持ってよい grain の語彙（ADR-0025 D2）。将来 month セル等を
# 足すときは、ここと年キー8表の射影（scripts/b08_project_occurrence_v1.py。
# `GRAIN_VALUES` をこのモジュールから import して使う）を合わせて見直すこと
# ——黙って絞り込みで捨てない（コードレビュー指摘2）。1箇所で済むよう、
# SQL の `IN (...)` 句・メッセージの語彙表記もここから組み立てる
# （/simplify 指摘5: `_KNOWN_PLACE_KINDS` と同じ書き方）。
GRAIN_VALUES = ("year", "survey_period")
_GRAIN_VALUES_SQL_LIST = ", ".join(repr(g) for g in GRAIN_VALUES)
_GRAIN_VALUES_LABEL = "/".join(repr(g) for g in GRAIN_VALUES)  # 例: "'year'/'survey_period'"

REQUIRED_DECLARATION_KEYS = ("expected_row_count", "note")
_LEAF_DECLARATION_NAME = "leaf_cell_source_rows"

_CREATE_OCCURRENCE_AGG_SQL = f"""
CREATE TABLE {{table}} (
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
  built_from    TEXT NOT NULL,
  spec_version  TEXT NOT NULL
)
"""

# `red_list_category` の原表記が NULL でも '' でもない、の判定式（v1 の
# mesh_year.rl_n・mesh_species.rl_species_n と同じ定義。O-1b brief 参照）。
_RED_LIST_NONEMPTY_EXPR = "red_list_category IS NOT NULL AND red_list_category <> ''"

# 「同じ暦年に収まる記録か」の述語（コードレビュー指摘12: 1箇所だけに持ち、
# 年セル/leaf セルの INSERT 側と検証側（`_assert_cube_partition_and_shape`）の
# 両方がここから作る）。列名は `period_start`/`period_end` のみを参照する
# ため、`occurrence`（生の列）にも `staging`（キューブのセル。leaf セルは
# 丸めていないので同じ意味を保つ）にもそのまま使える。
_SAME_YEAR_EXPR = "substr(period_start, 1, 4) = substr(period_end, 1, 4)"
_CROSS_YEAR_EXPR = f"NOT ({_SAME_YEAR_EXPR})"

_DIM_SELECT = ", ".join(DIM_COLUMNS[:5])  # region_id, source_id, place_id, place_kind, taxon_id

_INSERT_COLUMNS = DIM_COLUMNS + ["n", "n_red_list", "built_from", "spec_version"]

# 年セル: 期間が1つの暦年に収まる記録（day/instant/month/year と、同年内の
# 区間）。セルの period_start/period_end は暦年境界へ丸める（文字列演算のみ。
# モジュール docstring「年境界の計算に SQLite の date() を使わない」参照）。
_YEAR_CELLS_SQL = f"""
SELECT {_DIM_SELECT}, 'year' AS grain,
       substr(period_start, 1, 4) || '-01-01' AS period_start,
       substr(period_start, 1, 4) || '-12-31' AS period_end,
       COUNT(*) AS n,
       SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list,
       ? AS built_from, ? AS spec_version
FROM occurrence
WHERE period_raw IS NOT NULL AND {_SAME_YEAR_EXPR}
GROUP BY {_DIM_SELECT}, substr(period_start, 1, 4)
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
WHERE period_raw IS NOT NULL AND {_CROSS_YEAR_EXPR}
GROUP BY {_DIM_SELECT}, period_start, period_end
"""

_L2_SERIES_TOTALS_SQL = f"""
SELECT place_kind, source_id, taxon_id, COUNT(*) AS n,
       SUM(CASE WHEN {_RED_LIST_NONEMPTY_EXPR} THEN 1 ELSE 0 END) AS n_red_list
FROM occurrence
WHERE period_raw IS NOT NULL
GROUP BY place_kind, source_id, taxon_id
"""

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
    ここでも入力を信用せず確認する（段階間の検証。コードレビュー指摘5）。
    これが通っていることが、年境界の計算を `date()` を使わず文字列演算だけで
    行ってよい前提になる。
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


# ---------------------------------------------------------------------------
# 宣言 YAML（1回だけ読む。コードレビュー指摘12）
# ---------------------------------------------------------------------------

def load_and_validate_cube_declarations(path=DEFAULT_DECLARATIONS_YAML) -> dict:
    """`occurrence_cube_declarations.yaml` を読み、構造を検証してから返す
    （`occurrence_period_shapes.yaml` の `validate_occurrence_period_shapes_shape()`
    と同じ流儀——必須キーの検査は `period.required_keys_problems()`、整数検査は
    `period.validate_expected_row_count()` に委ねる）。宣言された名前の集合が
    `{_LEAF_DECLARATION_NAME}` 1件と過不足なく一致することも確認する。

    `build_cube()` はここが返した dict から値を直接取り出す——構造検証用と
    値取得用でファイルを2回読まない（コードレビュー指摘12）。
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

    period.assert_declared_names_match(raw, {_LEAF_DECLARATION_NAME}, path)
    return raw


def validate_cube_declarations_shape(path=DEFAULT_DECLARATIONS_YAML) -> None:
    """CI 用: 構造検証だけを行う（戻り値は使わない呼び出し元のため。
    `.github/workflows/ci.yml` が原本DBを必要とせずに呼ぶ）。
    """
    load_and_validate_cube_declarations(path)


# ---------------------------------------------------------------------------
# (i) 系列ごとの Σn/Σn_red_list（occurrence=L2 と staging を突き合わせる）
# ---------------------------------------------------------------------------

_L2_SERIES_TOTALS_TABLE = "__l2_series_totals"


def _materialize_l2_series_totals(conn: sqlite3.Connection) -> str:
    """`occurrence`（日付あり行）を系列（place_kind, source_id, taxon_id）
    ごとに集計した一時テーブルを作り、そのテーブル名を返す。

    `occurrence`（816,856行）の `GROUP BY` はこの1回だけ行う——後続の3つの
    用途（キューブとの突合・検証した系列数・`place_kind` ごとの日付あり
    行数）は、すべてこの集計結果（約32,000行）を読むだけで済ませる
    （呼び出し元がこれらを別々のクエリで `occurrence` に対して再実行すると、
    同じ高コストな `GROUP BY` を複数回行うことになる——実装時に実際に踏んだ
    非効率）。呼び出し元が使い終わったら `DROP TABLE` すること。
    """
    conn.execute(f'DROP TABLE IF EXISTS "{_L2_SERIES_TOTALS_TABLE}"')
    conn.execute(f'CREATE TEMP TABLE "{_L2_SERIES_TOTALS_TABLE}" AS {_L2_SERIES_TOTALS_SQL}')
    return _L2_SERIES_TOTALS_TABLE


def _assert_series_totals_match_l2(conn: sqlite3.Connection, staging: str, l2_series_table: str) -> int:
    """(i): 系列（place_kind, source_id, taxon_id。taxon_id IS NULL を含む）
    ごとに Σn(year+leaf) = occurrence の日付あり行数、Σn_red_list も同様。
    `place_kind` を系列の一部に含める（O-2 の先取り。モジュール docstring
    参照）。比較そのものは SQL 側で行う（`common.assert_grouped_totals_match`。
    /simplify 指摘3: 系列数が約32,000にもなると、両側を Python の `dict` に
    展開して `set` 演算で突き合わせる実装は Python 側の実行時間が支配的だった
    ——実測 約3.6秒。系列の粒度はそのまま保つ〔合計だけを比べない〕）。

    `l2_series_table`（`_materialize_l2_series_totals` が作った一時テーブル）
    を読むだけで、`occurrence` を再度スキャンしない。戻り値は検証した系列数
    （レポート用）。
    """
    common.assert_grouped_totals_match(
        conn,
        f'SELECT place_kind, source_id, taxon_id, n, n_red_list FROM "{l2_series_table}"',
        f'SELECT place_kind, source_id, taxon_id, SUM(n) AS n, SUM(n_red_list) AS n_red_list '
        f'FROM "{staging}" GROUP BY place_kind, source_id, taxon_id',
        key_columns=["place_kind", "source_id", "taxon_id"],
        value_columns=["n", "n_red_list"],
        build_message=lambda rows: (
            "occurrence_agg: 系列（place_kind, source_id, taxon_id）ごとの Σn/Σn_red_list が "
            "occurrence（L2）と食い違う（キューブが記録を漏らす・二重に数えている可能性がある。"
            f"例（上限{_SAMPLE_LIMIT}件、(place_kind, source_id, taxon_id, n_l2, n_red_list_l2, "
            f"n_cube, n_red_list_cube)）: {rows}）。"
        ),
        sample_limit=_SAMPLE_LIMIT,
    )
    return conn.execute(f'SELECT COUNT(*) FROM "{l2_series_table}"').fetchone()[0]


def _l2_dated_count_by_place_kind(conn: sqlite3.Connection, l2_series_table: str) -> dict[str, int]:
    """`occurrence`（日付あり行）の `place_kind` ごとの件数。
    `_assert_cube_partition_and_shape` が「`place_kind='grid01'` の日付あり
    行数」として使う。`l2_series_table` を読むだけの軽いクエリ
    （`place_kind` の種類数——今は1——ぶんしか行が無い集計に対する集計）。
    """
    return dict(
        conn.execute(f'SELECT place_kind, SUM(n) FROM "{l2_series_table}" GROUP BY place_kind')
    )


# ---------------------------------------------------------------------------
# (ii)(iii) staging（実際に作ったキューブ）に対して行う（コードレビュー指摘1）
# ---------------------------------------------------------------------------

def _assert_cube_partition_and_shape(
    conn: sqlite3.Connection, staging: str, leaf_expected: int,
    n_dated_by_place_kind: dict[str, int], declarations_yaml,
) -> None:
    """`staging`（実際に作ったキューブ。本番差し替え前の作業用テーブル）に
    対して直接検証する——`occurrence`（L2）の述語を数え直すのではない
    （コードレビュー指摘1。モジュール docstring「機械検証」参照。以前の実装は
    L2 側の述語だけを検証していたため、年セル/leaf セルの SQL 自体の WHERE
    句が壊れていても検出できなかった——変異テスト
    `scripts/tests/test_b07_build_occurrence_cube.py` で再現・修正を確認済み）。

    - grain の語彙が `GRAIN_VALUES`（'year'/'survey_period'）以外を含まない
      （`place_kind` に関わらず共通）。
    - `place_kind='grid01'` に絞った `SUM(n) GROUP BY grain`: `survey_period`
      は宣言値（`leaf_expected`）、`year` は「`place_kind='grid01'` の
      日付あり行数 − leaf の宣言値」と一致する（**`place_kind` ごとに行う**。
      今は `'grid01'` だけ——O-2 で `'watershed'` が増えたら、その宣言値ぶん
      この検証も拡張すること）。
    - `grain='year'` の全行（`place_kind` に関わらず）が暦年境界
      （`<年>-01-01`〜`<年>-12-31`）に丸められている。
    - `grain='survey_period'` の全行（`place_kind` に関わらず）が年をまたいで
      いる（`_CROSS_YEAR_EXPR`）。
    """
    bad_grain = conn.execute(
        f'SELECT DISTINCT grain FROM "{staging}" WHERE grain NOT IN ({_GRAIN_VALUES_SQL_LIST})'
    ).fetchall()
    if bad_grain:
        raise common.MigrationError(
            f"occurrence_agg: grain が {_GRAIN_VALUES_LABEL} 以外の値を持つ行がある"
            f"（{[r[0] for r in bad_grain]}）。ADR-0025 D2 はこの2つの grain だけを決めている"
            "——新しい grain を足すなら、この検証と年キー8表の射影（scripts/b08_project_occurrence_v1.py）"
            "を合わせて見直すこと。"
        )

    sums = conn.execute(f'SELECT place_kind, grain, SUM(n) FROM "{staging}" GROUP BY place_kind, grain').fetchall()
    by_place_kind: dict[str, dict[str, int]] = {}
    for place_kind, grain, total in sums:
        by_place_kind.setdefault(place_kind, {})[grain] = total

    grid01_sums = by_place_kind.get("grid01", {})
    leaf_n = grid01_sums.get("survey_period", 0)
    year_n = grid01_sums.get("year", 0)
    n_dated_grid01 = n_dated_by_place_kind.get("grid01", 0)
    if leaf_n != leaf_expected:
        raise common.MigrationError(
            f"occurrence_agg: place_kind='grid01' の grain='survey_period'（年をまたぐ区間）の"
            f"セルの Σn が宣言（{declarations_yaml} の {_LEAF_DECLARATION_NAME}.expected_row_count）"
            f"と食い違う（宣言: {leaf_expected:,} / 実測: {leaf_n:,}）。occurrence の入力が変わった"
            "（新しい出典・期間の追加等）か、年境界の判定（年セル/leaf セルの振り分け）が"
            "壊れている可能性がある。実測が正しければ宣言値を更新すること。"
        )
    expected_year_n = n_dated_grid01 - leaf_expected
    if year_n != expected_year_n:
        raise common.MigrationError(
            f"occurrence_agg: place_kind='grid01' の grain='year' セルの Σn（{year_n:,}）が"
            f"「grid01 の日付あり行数 − leaf の宣言値」（{n_dated_grid01:,} − {leaf_expected:,} = "
            f"{expected_year_n:,}）と食い違う。年境界の判定（同年か否か）が壊れている可能性がある"
            "（例: 年セルの SQL が年をまたぐ記録まで飲み込んでいる）。"
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


# `scripts/b04_build_cube.py` と実装がほぼ一字一句同じだったため、
# `scripts/migrate/common.assert_dimension_key_unique` に集約した
# （/simplify 指摘1）。ここでは `DIM_COLUMNS`・索引名・メッセージの文言
# （b07 固有）だけを渡す薄い呼び出しにしてある。
_DIM_KEY_INDEX_NAME = "occurrence_agg_dim_key"


def _assert_dimension_key_unique(conn: sqlite3.Connection, staging: str) -> None:
    common.assert_dimension_key_unique(
        conn, staging, DIM_COLUMNS,
        index_name=_DIM_KEY_INDEX_NAME,
        table_label="occurrence_agg",
        cause_hint="year/leaf の集計経路が重なっている可能性がある。",
    )


def build_cube(
    conn: sqlite3.Connection,
    declarations_yaml=DEFAULT_DECLARATIONS_YAML,
    built_from: str = DEFAULT_BUILT_FROM,
    spec_version: str = common.OCCURRENCE_SPEC_VERSION,
) -> dict:
    """`conn`（`occurrence` を持つ読み書き可能な接続）に `occurrence_agg` を作る。

    `occurrence` を変更する SQL は一切実行しない（`SELECT`のみ）。
    `occurrence_agg` 本体は `migrate.common.staged_table`（b04 の A-1 と同じ）
    で作り直す——検証まで全部通ってから本番名に差し替える。戻り値はレポート用の統計。

    検証（`_assert_series_totals_match_l2`）が `FULL OUTER JOIN` を使うため、
    その前に `common.require_sqlite_version()` を呼ぶ（モジュール docstring
    「built_from に SQLite バージョンを埋め込まない、が書き込み経路自体は
    3.43以降が前提」参照）。
    """
    common.require_sqlite_version()
    declarations = load_and_validate_cube_declarations(declarations_yaml)
    leaf_expected = declarations[_LEAF_DECLARATION_NAME]["expected_row_count"]
    _assert_t1_invariant(conn)
    params = (built_from, spec_version)

    with common.staged_table(conn, "occurrence_agg", _CREATE_OCCURRENCE_AGG_SQL) as staging:
        insert_cols = ", ".join(_INSERT_COLUMNS)
        insert_sql = f'INSERT INTO "{staging}" ({insert_cols}) '

        n_year = conn.execute(insert_sql + _YEAR_CELLS_SQL, params).rowcount
        n_leaf = conn.execute(insert_sql + _LEAF_CELLS_SQL, params).rowcount

        l2_series_table = _materialize_l2_series_totals(conn)
        try:
            n_series = _assert_series_totals_match_l2(conn, staging, l2_series_table)
            n_dated_by_place_kind = _l2_dated_count_by_place_kind(conn, l2_series_table)
        finally:
            conn.execute(f'DROP TABLE IF EXISTS "{l2_series_table}"')
        _assert_cube_partition_and_shape(conn, staging, leaf_expected, n_dated_by_place_kind, declarations_yaml)
        _assert_dimension_key_unique(conn, staging)

    n_dated_grid01 = n_dated_by_place_kind.get("grid01", 0)
    return {
        "n_year_cells": n_year,
        "n_leaf_cells": n_leaf,
        "n_total_cells": n_year + n_leaf,
        "n_series_checked": n_series,
        "n_dated": sum(n_dated_by_place_kind.values()),
        "n_dated_by_place_kind": n_dated_by_place_kind,
        "n_leaf_source_rows": leaf_expected,
        "n_year_source_rows": n_dated_grid01 - leaf_expected,
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
