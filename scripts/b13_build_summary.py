#!/usr/bin/env python3
"""`observation_agg`（`scripts/b04_build_cube.py`）・`occurrence_agg`
（`scripts/b07_build_occurrence_cube.py`）——どちらも `data/db/v2.sqlite`——から、
画面・API・AI が直接読む summary 4表（`summary_variable_catalog`/
`summary_place_variable`〔observation_agg 由来〕・`summary_taxon_catalog`/
`summary_watershed_occurrence`〔occurrence_agg 由来〕。ADR-0011、
Issue #48 PR-2 §4・PR-3a §5）を作る。

    .venv/bin/python3 scripts/b13_build_summary.py

`data/db/v2.sqlite` に4表を（作り直して）追加する——`observation_agg`/
`occurrence_agg` 自体は一切変更しない（SELECT のみ）。b04 と同じ「ファイル
ではなくテーブル単位で作り直す」パターン（`migrate.common.staged_table`）を使う。

## 何を summary に落とすか（`aggregations/serving.yaml` が宣言）

`variable_id`/`地点×variable_id`/`taxon_id`/`流域` それぞれの一覧・件数・期間は、
キューブを毎回集計すると遅い（実測: 指標カタログ約1.9秒・地点×指標約2.1秒・
種カタログ約1.8秒・流域ロールアップ約1.2秒〔471k セル時点。`occurrence_agg` が
PR-3a でセル数を約3倍に増やすため、この2表は事前計算が無いと3〜4秒かかる見込み〕。
Python sqlite3、コールドキャッシュ）。この4表は「`filter` に絞ったキューブを、
系列単位（observation_agg 側は `variable_id`/`obs_stat`/`unit_id`/`value_grain`/
`grain`/`input_grain`、地点別はさらに `place_id`。occurrence_agg 側は
`taxon_id`/`place_id` そのもの）で再集計しただけ」の事前計算——**binom/
variable_id 単位への束ね・代表化はここではしない**（それは問い合わせ層
`web/src/lib/cube/catalog.ts` 等の仕事。`nPlaces` を alias/variable 単位に
単純合算すると二重計上する、という PR-1 の知見どおり）。

どの列で GROUP BY するか・どの測度（`sum`/`count_distinct`/`min`/`max`/`avg`）を
作るかは、このスクリプトではなく `aggregations/serving.yaml`（宣言的な対応表、
`scripts/reconcile/projection_manifest.yaml` と同じ流儀）に書く——表ごとの
分岐をコード側に持たない。`source`（`observation_agg`/`occurrence_agg`）も
同じ YAML の宣言——次元キー・測度列の許容集合は `source` ごとに持つ
（`b04.DIM_COLUMNS`/`b07.DIM_COLUMNS`。source をまたいだ列名の流用はできない）。

## 機械検証（1つでも失敗すれば `MigrationError` で止まる。キューブ自体は
変わらないまま——`staged_table` の `with` ブロックの中で行う。A-1）

1. **YAML の語彙検証**（`_validate_manifest_shape`/`_validate_summary_spec`）:
   `version`/`spec_version`（`scripts/migrate/common.py` の
   `SUMMARY_SPEC_VERSION` と一致するか）・`summaries` のテーブル名の集合
   （`common.V2_SUMMARY_TABLES` と過不足なく一致するか）・`source`
   （`observation_agg`/`occurrence_agg`）・`fn`
   （`sum`/`count_distinct`/`min`/`max`/`avg`）・`expr`（`year_of_period_start`）・
   `filter`/`group_by`/`key` の列（その summary の `source` の次元キーのみ）・
   測度の `col`（同じ source の次元キー、または値列）・`indexes` の列
   （group_by/measures の列のみ）が、すべて閉じた語彙に収まっているかを、
   SQL を1つも投げる前に確認する。**`source: occurrence_agg` の summary は
   `filter.grain` が無ければ止まる**（`occurrence_agg` は year 族・month 族の
   セルを同居させているため——`aggregations/serving.yaml` のコメント「
   `source: occurrence_agg` の summary は `filter.grain` を必須とする」参照）。
   **`filter.grain` の**値**も検証する**——単に列があるだけでは不十分で、
   `b07.YEAR_GRAIN_FAMILY`（`{"year", "survey_period"}`）か
   `b07.MONTH_GRAIN_FAMILY`（`{"month"}`）のどちらか1つの族にちょうど
   収まっていなければ止める（例えば `[year, month]` のように2つの族を
   跨ぐ値は、族をまたいだ二重計上を招くため無条件に拒否する。以前は
   `filter.grain` の有無しか見ておらず、値が何であっても検証1を通過して
   しまっていた。/code-review 指摘5）。
2. **次元キーの一意性**（`key` 列。`common.assert_dimension_key_unique`）。
3. **保存則**: 各 summary の `SUM(n)` が、同じ `filter` を通した `source`
   自身の `SUM(n)` と一致すること（GROUP BY で行を分けても件数の合計は
   変わらないはず、という不変条件。1で `filter.grain` を必須にしているのは、
   この保存則が「同じ〔絞り込み忘れの〕filter どうし」を比べるだけなので、
   族をまたいだ二重計上を検出できないため——絞り込み忘れそのものを検証1で
   先に止める）。
4. **行数 > 0**（`filter` が絞りすぎて0行になる事故を検出する）。

もう1つの機械検証（無作為抽出した群を、生成した SQL とは独立の固定 SQL で
再計算して一致を確認する）は `scripts/tests/test_b13_build_summary.py` の
`_REFERENCE_SQL` が担う——`aggregations/serving.yaml` から SQL を生成する
このスクリプト自身の実装バグを、宣言をなぞらない別実装で検出するのが目的
なので、宣言を読むこのスクリプトの中には置かない（族の絞り込みも
`_REFERENCE_SQL` 側で独立に書く——生成側と同じ絞り込み忘れを共有しない）。

## 指紋

各 summary の `source`（`observation_agg`/`occurrence_agg`）の指紋
（`assert_stage_fingerprint_fresh`。読み込み時に source ごと1回だけ確認し、
戻り値をその source を使う summary 表の系譜 `inputs` にそのまま使う）と、
summary 表自身の指紋（`staged_table` 経由）は記録するが、
**`record_v2_input_fingerprint`（v2 パイプラインの外側の入力＋コードの指紋）は
呼ばない**——b03/b06/b09 が記録した値を、それらの入力を一切読まない b13 が
上書きしてしまうと、実際に読んだ入力とずれた記録が残る（`scripts/migrate/
common.py` の `record_v2_input_fingerprint` docstring 参照）。
`aggregations/serving.yaml` 自体の変化は `V2_PIPELINE_STAGE_MODULES` に
`b13_build_summary` を足したことでコードの指紋（`_v2_pipeline_code_fingerprint`）
の対象に入る——別途このスクリプトが記録する必要は無い。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b04_build_cube as b04  # noqa: E402  (DIM_COLUMNS の正本を複製しない)
import b07_build_occurrence_cube as b07  # noqa: E402  (同上)
from migrate import common  # noqa: E402

DEFAULT_V2_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_YAML = ROOT / "aggregations" / "serving.yaml"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"

# 語彙は閉じる（モジュール docstring「YAML の語彙検証」参照）。
_ALLOWED_FN = frozenset({"sum", "count_distinct", "min", "max", "avg"})
_ALLOWED_EXPR = frozenset({"year_of_period_start"})
_ALLOWED_SOURCES = frozenset({"observation_agg", "occurrence_agg"})

# `source: occurrence_agg` の summary に必須の filter 列（PR-3a §9-2。モジュール
# docstring「YAML の語彙検証」参照）。
_REQUIRED_FILTER_COLUMNS_BY_SOURCE: dict[str, frozenset[str]] = {
    "occurrence_agg": frozenset({"grain"}),
}

# `filter.grain` の**値**が収まっていなければならない族（`_REQUIRED_FILTER_
# COLUMNS_BY_SOURCE` は列の有無しか見ないので、値の検証はこちらで別に持つ。
# モジュール docstring「YAML の語彙検証」参照）。b07 の族定義をそのまま使い、
# ここに族を複製しない。
_ALLOWED_GRAIN_FAMILIES_BY_SOURCE: dict[str, tuple[frozenset[str], ...]] = {
    "occurrence_agg": (frozenset(b07.YEAR_GRAIN_FAMILY), frozenset(b07.MONTH_GRAIN_FAMILY)),
}

# Issue #48 PR-3b §2.1（D1）: summary が結合してよい registry の表と、そこから読んでよい列。
# `join: {taxon: registry}` を宣言した summary だけが `taxon.<列>` を group_by（`columns`）・
# measures・filter に使える。`taxon` は `taxon_id` が主キーなので結合で行は増減しない
# （`_assert_join_conserves` が毎回確かめる）。結合先は `registry.sqlite` を
# `ATTACH ... mode=ro` した別名 `registry`。
_JOIN_ALIAS = "registry"
_ALLOWED_JOINS: dict[str, dict] = {
    "taxon": {
        "on_cube_column": "taxon_id",
        "on_join_column": "taxon_id",
        "columns": frozenset({"canonical_binomial", "taxon_group", "class", "family"}),
        "sources": frozenset({"occurrence_agg"}),
    },
}
# 測度の `when`（条件つき集計）の語彙。`year_between: [lo, hi]` は
# `year_of_period_start` の閉区間、`positive: <col>` は列 > 0。
_ALLOWED_WHEN_KEYS = frozenset({"year_between", "positive"})
# filter 値の辞書形式（`{not_null: true}` だけ）。
_ALLOWED_FILTER_OPS = frozenset({"not_null"})

_EXPR_SQL = {
    "year_of_period_start": "CAST(substr(period_start, 1, 4) AS INTEGER)",
}
_EXPR_SQL_TYPE = {
    "year_of_period_start": "INTEGER",
}
_FN_SQL = {
    "sum": "SUM({expr})",
    "count_distinct": "COUNT(DISTINCT {expr})",
    "min": "MIN({expr})",
    "max": "MAX({expr})",
    "avg": "AVG({expr})",
}

# キューブの測度列と型。`scripts/b04_build_cube.py`/`scripts/b07_build_
# occurrence_cube.py` の `_CREATE_OBSERVATION_AGG_SQL`/`_CREATE_OCCURRENCE_AGG_SQL`
# と型を揃える。**source ごとに別の許容集合を持つ**——observation_agg にしか
# 無い `value_zero` を occurrence_agg 由来の summary の測度に書けてしまうと、
# SQL 実行時（検証1より後）まで気付けない事故になる。
_CUBE_VALUE_COLUMN_TYPES_BY_SOURCE: dict[str, dict[str, str]] = {
    "observation_agg": {
        "value_zero": "REAL",
        "value_lod": "REAL",
        "n": "INTEGER",
        "n_censored": "INTEGER",
        "n_not_detected": "INTEGER",
        "n_places": "INTEGER",
    },
    "occurrence_agg": {
        "n": "INTEGER",
        "n_red_list": "INTEGER",
        "n_alien": "INTEGER",
    },
}

# `assert_stage_fingerprint_fresh` に渡す source ごとの再構築手順。
_REBUILD_HINT_BY_SOURCE = {
    "observation_agg": "scripts/b04_build_cube.py を再実行すること。",
    "occurrence_agg": "scripts/b07_build_occurrence_cube.py を再実行すること。",
}

_ALLOWED_DIM_COLUMNS_BY_SOURCE: dict[str, frozenset[str]] = {
    "observation_agg": frozenset(b04.DIM_COLUMNS),
    "occurrence_agg": frozenset(b07.DIM_COLUMNS),
}
_ALLOWED_MEASURE_COLUMNS_BY_SOURCE: dict[str, frozenset[str]] = {
    source: _ALLOWED_DIM_COLUMNS_BY_SOURCE[source] | frozenset(value_types)
    for source, value_types in _CUBE_VALUE_COLUMN_TYPES_BY_SOURCE.items()
}


def _fail(message: str) -> None:
    raise common.MigrationError(f"aggregations/serving.yaml: {message}")


def _validate_col_ref(table_name: str, where: str, ref, spec: dict, allowed_cube_columns) -> None:
    """列参照（キューブの列、または `taxon.<列>` の結合先の列）の検証。"""
    if not isinstance(ref, str):
        _fail(f"{table_name}.{where} が文字列ではない: {ref!r}")
    if _is_joined_ref(ref):
        alias, _, col = ref.partition(".")
        if alias not in _joins(spec):
            _fail(f"{table_name}.{where} が宣言していない join の列: {ref!r}（join: {sorted(_joins(spec))}）")
        if col not in _ALLOWED_JOINS[alias]["columns"]:
            _fail(
                f"{table_name}.{where} が未知の結合先の列: {ref!r}"
                f"（{alias} の許容: {sorted(_ALLOWED_JOINS[alias]['columns'])}）"
            )
    elif ref not in allowed_cube_columns:
        _fail(
            f"{table_name}.{where} が未知の列: {ref!r}"
            f"（source={spec.get('source')!r} の許容: {sorted(allowed_cube_columns)}）"
        )


def _validate_when(table_name: str, measure_name: str, when, spec: dict, allowed_cube_columns) -> None:
    where = f"measures.{measure_name}.when"
    if not isinstance(when, dict) or not when:
        _fail(f"{table_name}.{where} が空、または辞書ではない: {when!r}")
    unknown = set(when) - _ALLOWED_WHEN_KEYS
    if unknown:
        _fail(f"{table_name}.{where} に未知のキー: {sorted(unknown)}（許容: {sorted(_ALLOWED_WHEN_KEYS)}）")
    if "year_between" in when:
        yb = when["year_between"]
        if not (isinstance(yb, list) and len(yb) == 2 and all(isinstance(v, int) for v in yb) and yb[0] <= yb[1]):
            _fail(f"{table_name}.{where}.year_between は [下限, 上限]（整数2つ、下限<=上限）: {yb!r}")
    if "positive" in when:
        _validate_col_ref(table_name, f"{where}.positive", when["positive"], spec, allowed_cube_columns)


def _validate_measure(table_name: str, measure_name: str, measure, spec: dict) -> None:
    """`spec["source"]`（`_validate_summary_spec` が事前に `_ALLOWED_SOURCES` に
    属することを確認済み）ごとの許容列（`_ALLOWED_MEASURE_COLUMNS_BY_SOURCE`）と、宣言した
    join の結合先の列で `col` を検証する——source をまたいだ列名の流用は許さない
    （モジュール docstring「YAML の語彙検証」参照）。
    """
    source = spec["source"]
    if not isinstance(measure, dict):
        _fail(f"{table_name}.measures.{measure_name} が辞書ではない: {measure!r}")
    fn = measure.get("fn")
    if fn not in _ALLOWED_FN:
        _fail(f"{table_name}.measures.{measure_name}.fn が未知: {fn!r}（許容: {sorted(_ALLOWED_FN)}）")
    has_col = "col" in measure
    has_expr = "expr" in measure
    if has_col == has_expr:
        _fail(f"{table_name}.measures.{measure_name}: col と expr のどちらか一方だけを持つこと（{measure!r}）")
    allowed_measure_columns = _ALLOWED_MEASURE_COLUMNS_BY_SOURCE[source]
    if has_col:
        _validate_col_ref(table_name, f"measures.{measure_name}.col", measure["col"], spec, allowed_measure_columns)
    if has_expr and measure["expr"] not in _ALLOWED_EXPR:
        _fail(
            f"{table_name}.measures.{measure_name}.expr が未知: {measure['expr']!r}"
            f"（許容: {sorted(_ALLOWED_EXPR)}）"
        )
    if "when" in measure:
        _validate_when(table_name, measure_name, measure["when"], spec, allowed_measure_columns)
    # `when` 付きの max/min/avg は SQL としては書けるが、窓の外を NULL に落とす意図が
    # 曖昧なので使わせない（今の用途は sum と count_distinct だけ）。
    if "when" in measure and fn not in {"sum", "count_distinct"}:
        _fail(f"{table_name}.measures.{measure_name}: when は sum/count_distinct にだけ使える（fn={fn!r}）")


def _validate_join(table_name: str, spec: dict) -> None:
    join = spec.get("join")
    if join is None:
        return
    if not isinstance(join, dict) or not join:
        _fail(f"{table_name}.join が空、または辞書ではない: {join!r}")
    for name, target in join.items():
        if name not in _ALLOWED_JOINS:
            _fail(f"{table_name}.join に未知の表: {name!r}（許容: {sorted(_ALLOWED_JOINS)}）")
        if target != _JOIN_ALIAS:
            _fail(f"{table_name}.join.{name} は {_JOIN_ALIAS!r} だけが許される（registry.sqlite）: {target!r}")
        if spec["source"] not in _ALLOWED_JOINS[name]["sources"]:
            _fail(
                f"{table_name}.join.{name} は source={spec['source']!r} には使えない"
                f"（許容: {sorted(_ALLOWED_JOINS[name]['sources'])}）"
            )


def _validate_summary_spec(table_name: str, spec: dict) -> None:
    """1つの summary 宣言（`spec`）の語彙を検証する（モジュール docstring
    「YAML の語彙検証」節）。SQL を1つも投げる前に呼ぶこと。

    `source` を最初に検証してから、以降の列検証（`filter`/`group_by`/`measures`）
    をその `source` の許容集合（`_ALLOWED_DIM_COLUMNS_BY_SOURCE`/
    `_ALLOWED_MEASURE_COLUMNS_BY_SOURCE`）だけで行う——`_fail` は例外を投げる
    ため、`source` が未知ならここで止まり、以降の行が存在しない source を
    インデックスすることはない。
    """
    source = spec.get("source")
    if source not in _ALLOWED_SOURCES:
        _fail(f"{table_name}.source が未知: {source!r}（許容: {sorted(_ALLOWED_SOURCES)}）")
    allowed_dim_columns = _ALLOWED_DIM_COLUMNS_BY_SOURCE[source]
    _validate_join(table_name, spec)

    filter_spec = spec.get("filter") or {}
    if not isinstance(filter_spec, dict):
        _fail(f"{table_name}.filter が辞書ではない: {filter_spec!r}")
    for col, value in filter_spec.items():
        _validate_col_ref(table_name, f"filter.{col}", col, spec, allowed_dim_columns)
        if isinstance(value, dict):
            if set(value) - _ALLOWED_FILTER_OPS or not value:
                _fail(f"{table_name}.filter.{col} の辞書形式は {sorted(_ALLOWED_FILTER_OPS)} だけ: {value!r}")
            if not _is_joined_ref(col):
                _fail(f"{table_name}.filter.{col}: not_null は結合先の列にだけ使える（キューブの次元キーは NULL を落とさない）")
    required_filter_columns = _REQUIRED_FILTER_COLUMNS_BY_SOURCE.get(source, frozenset())
    missing_required = required_filter_columns - set(filter_spec)
    if missing_required:
        _fail(
            f"{table_name}.filter に必須の列が無い: {sorted(missing_required)}"
            f"（source={source!r} の summary は、族をまたいだ二重計上を防ぐためこの列の"
            "絞り込みを必須とする。aggregations/serving.yaml 冒頭のコメント参照）"
        )

    allowed_grain_families = _ALLOWED_GRAIN_FAMILIES_BY_SOURCE.get(source)
    if allowed_grain_families is not None and "grain" in filter_spec:
        grain_value = filter_spec["grain"]
        grain_set = frozenset(grain_value) if isinstance(grain_value, list) else frozenset({grain_value})
        if grain_set not in allowed_grain_families:
            _fail(
                f"{table_name}.filter.grain が族に収まっていない: {sorted(grain_set)}"
                f"（source={source!r} の summary は、`b07.YEAR_GRAIN_FAMILY`"
                f"（{sorted(b07.YEAR_GRAIN_FAMILY)}）か `b07.MONTH_GRAIN_FAMILY`"
                f"（{sorted(b07.MONTH_GRAIN_FAMILY)}）のどちらか1つの族にちょうど"
                "一致すること。族をまたぐ値は二重計上を招く）"
            )

    columns = spec.get("columns") or {}
    if not isinstance(columns, dict):
        _fail(f"{table_name}.columns が辞書ではない: {columns!r}")
    for name, definition in columns.items():
        if name in allowed_dim_columns:
            _fail(f"{table_name}.columns.{name} はキューブの次元キーと同名（別名を付けること）")
        if not isinstance(definition, dict):
            _fail(f"{table_name}.columns.{name} が辞書ではない: {definition!r}")
        if ("col" in definition) == ("expr" in definition):
            _fail(f"{table_name}.columns.{name}: col と expr のどちらか一方だけを持つこと（{definition!r}）")
        if "col" in definition:
            _validate_col_ref(table_name, f"columns.{name}.col", definition["col"], spec, allowed_dim_columns)
        elif definition["expr"] not in _ALLOWED_EXPR:
            _fail(f"{table_name}.columns.{name}.expr が未知: {definition['expr']!r}（許容: {sorted(_ALLOWED_EXPR)}）")
        if set(definition) - {"col", "expr", "coalesce"}:
            _fail(f"{table_name}.columns.{name} に未知のキー: {sorted(set(definition) - {'col', 'expr', 'coalesce'})}")
        if "coalesce" in definition and (not isinstance(definition["coalesce"], str) or "'" in definition["coalesce"]):
            _fail(f"{table_name}.columns.{name}.coalesce は引用符を含まない文字列であること: {definition['coalesce']!r}")

    group_by = spec.get("group_by")
    if not group_by or not isinstance(group_by, list):
        _fail(f"{table_name}.group_by が空、または一覧ではない: {group_by!r}")
    for col in group_by:
        if col not in allowed_dim_columns and col not in columns:
            _fail(
                f"{table_name}.group_by に未知の列: {col!r}"
                f"（source={source!r} の次元キー、または columns で定義した列のみ許容: "
                f"{sorted(allowed_dim_columns | set(columns))}）"
            )

    key = spec.get("key")
    if not key or set(key) != set(group_by):
        _fail(f"{table_name}.key は group_by と同じ集合であること（key={key!r}, group_by={group_by!r}）")

    measures = spec.get("measures")
    if not measures or not isinstance(measures, dict):
        _fail(f"{table_name}.measures が空、または辞書ではない: {measures!r}")
    for measure_name, measure in measures.items():
        _validate_measure(table_name, measure_name, measure, spec)
    if "n" not in measures:
        _fail(f"{table_name}.measures に n が無い（保存則が SUM(n) を比べる）")

    produced_columns = set(group_by) | set(measures)
    for index_cols in spec.get("indexes") or []:
        for col in index_cols:
            if col not in produced_columns:
                _fail(
                    f"{table_name}.indexes に summary 表に無い列: {col!r}"
                    f"（許容: group_by/measures の列のみ {sorted(produced_columns)}）"
                )


def _validate_manifest_shape(raw: dict) -> None:
    """トップレベル（`version`/`spec_version`/`summaries` のテーブル名の集合）
    の検証。各 summary 個別の宣言は `_validate_summary_spec` が担う。
    """
    if raw.get("version") != 1:
        _fail(f"version が未知: {raw.get('version')!r}（許容: 1）")
    if raw.get("spec_version") != common.SUMMARY_SPEC_VERSION:
        _fail(
            f"spec_version が scripts/migrate/common.py の SUMMARY_SPEC_VERSION と食い違う"
            f"（yaml={raw.get('spec_version')!r}, common={common.SUMMARY_SPEC_VERSION!r}）。"
            "変換規則を変えたなら両方を一緒に上げること。"
        )
    summaries = raw.get("summaries")
    if not isinstance(summaries, dict):
        _fail(f"summaries が辞書ではない: {summaries!r}")
    declared = set(summaries)
    expected = set(common.V2_SUMMARY_TABLES)
    if declared != expected:
        _fail(
            "summaries のテーブル名の集合が scripts/migrate/common.py の V2_SUMMARY_TABLES と"
            f"過不足なく一致しない（宣言: {sorted(declared)}、期待: {sorted(expected)}）"
        )


def _joins(spec: dict) -> dict:
    return spec.get("join") or {}


def _is_joined_ref(ref: str) -> bool:
    return "." in ref


def _col_sql(spec: dict, ref: str) -> str:
    """列参照を SQL に直す。`taxon.canonical_binomial` のような結合先の列はそのまま、
    キューブの列は結合があるとき `{source}.{col}`（`taxon_id` が両方にあるので曖昧さを
    避ける）、無いとき素の列名。
    """
    if _is_joined_ref(ref) or not _joins(spec):
        return ref
    return f"{spec['source']}.{ref}"


def _value_sql(spec: dict, definition: dict) -> str:
    """`{col: ...}` または `{expr: ...}`（measure・columns 共通）の基底 SQL。"""
    if "col" in definition:
        return _col_sql(spec, definition["col"])
    return _EXPR_SQL[definition["expr"]]


def _when_sql(spec: dict, when: dict) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if "year_between" in when:
        lo, hi = when["year_between"]
        clauses.append(f"{_EXPR_SQL['year_of_period_start']} BETWEEN ? AND ?")
        params.extend([lo, hi])
    if "positive" in when:
        clauses.append(f"{_col_sql(spec, when['positive'])} > 0")
    return " AND ".join(clauses), params


def _measure_expr_sql(spec: dict, measure: dict) -> tuple[str, list]:
    """測度の SQL 式とバインドパラメータ。`when` があれば `CASE WHEN ... END` で包む
    （`sum` は条件外を 0 に、他は NULL にして落とす——`SUM` が全行 NULL で NULL に
    ならないように）。
    """
    base = _value_sql(spec, measure)
    params: list = []
    when = measure.get("when")
    if when:
        cond, params = _when_sql(spec, when)
        else_sql = " ELSE 0" if measure["fn"] == "sum" else ""
        base = f"CASE WHEN {cond} THEN {base}{else_sql} END"
    return _FN_SQL[measure["fn"]].format(expr=base), params


def _measure_sql_type(measure: dict, source: str) -> str:
    if measure["fn"] == "count_distinct":
        return "INTEGER"
    if measure["fn"] == "avg":
        return "REAL"
    if "expr" in measure:
        return _EXPR_SQL_TYPE[measure["expr"]]
    if _is_joined_ref(measure["col"]):
        return "TEXT"  # 結合先（taxon の canonical_binomial/taxon_group/class/family）は文字列
    return _CUBE_VALUE_COLUMN_TYPES_BY_SOURCE[source].get(measure["col"], "REAL")


def _group_column_sql(spec: dict, name: str) -> str:
    """group_by の列 `name` の SELECT 式（`columns` の定義があればそれ、無ければキューブの次元キー）。"""
    definition = (spec.get("columns") or {}).get(name)
    if definition is None:
        return _col_sql(spec, name)
    sql = _value_sql(spec, definition)
    if "coalesce" in definition:
        sql = f"COALESCE({sql}, '{definition['coalesce']}')"
    return sql


def _group_column_type(spec: dict, name: str) -> str:
    definition = (spec.get("columns") or {}).get(name)
    if definition is not None and "expr" in definition:
        return _EXPR_SQL_TYPE[definition["expr"]]
    return "TEXT"


def _from_sql(spec: dict) -> str:
    """`FROM <source> [LEFT JOIN registry.<表> AS <表> ON ...]`。"""
    sql = spec["source"]
    for name in _joins(spec):
        j = _ALLOWED_JOINS[name]
        sql += (
            f" LEFT JOIN {_JOIN_ALIAS}.{name} AS {name}"
            f" ON {name}.{j['on_join_column']} = {spec['source']}.{j['on_cube_column']}"
        )
    return sql


def _filter_sql(spec: dict, filter_spec: dict) -> tuple[str, list]:
    """`filter`（列 -> スカラ値、列 -> 一覧〔IN 句〕、列 -> `{not_null: true}`）から
    `WHERE` 節（先頭の `WHERE ` 付き）とバインドパラメータを組み立てる。`filter` が空なら
    `("", [])`。
    """
    if not filter_spec:
        return "", []
    clauses: list[str] = []
    params: list = []
    for col, value in filter_spec.items():
        col_sql = _col_sql(spec, col)
        if isinstance(value, dict):
            clauses.append(f"{col_sql} IS NOT NULL")
        elif isinstance(value, list):
            clauses.append(f"{col_sql} IN ({', '.join('?' for _ in value)})")
            params.extend(value)
        else:
            clauses.append(f"{col_sql} = ?")
            params.append(value)
    return "WHERE " + " AND ".join(clauses), params


def _create_table_sql(spec: dict) -> str:
    source = spec["source"]
    cols = [f"{c} {_group_column_type(spec, c)}" for c in spec["group_by"]]
    cols += [f"{name} {_measure_sql_type(m, source)}" for name, m in spec["measures"].items()]
    cols += ["built_from TEXT NOT NULL", "spec_version TEXT NOT NULL"]
    return "CREATE TABLE {table} (\n  " + ",\n  ".join(cols) + "\n)"


def _insert_select_sql(spec: dict, *, built_from: str, spec_version: str) -> tuple[str, list]:
    """`{table}`（`staged_table` が作業用テーブル名を埋め込む）への
    `INSERT INTO ... SELECT ... FROM <source> [LEFT JOIN ...] WHERE ... GROUP BY ...` と、
    そのバインドパラメータを返す。パラメータの並びは SQL 文中の `?` の出現順
    （SELECT 句の測度の `when` 分、`built_from`/`spec_version` の2つ、`WHERE` 節の分の
    順）に揃えること——`sqlite3` はパラメータを文中の出現順にバインドする。
    """
    group_by = spec["group_by"]
    measures = spec["measures"]
    where_sql, where_params = _filter_sql(spec, spec.get("filter") or {})
    insert_cols = list(group_by) + list(measures) + ["built_from", "spec_version"]
    select_cols = [f"{_group_column_sql(spec, c)} AS {c}" for c in group_by]
    select_params: list = []
    for name, m in measures.items():
        expr, p = _measure_expr_sql(spec, m)
        select_cols.append(f"{expr} AS {name}")
        select_params.extend(p)
    select_cols += ["? AS built_from", "? AS spec_version"]
    group_exprs = [_group_column_sql(spec, c) for c in group_by]
    sql = (
        f'INSERT INTO {{table}} ({", ".join(insert_cols)}) '
        f'SELECT {", ".join(select_cols)} '
        f'FROM {_from_sql(spec)} '
        f'{where_sql} '
        f'GROUP BY {", ".join(group_exprs)}'
    )
    params = select_params + [built_from, spec_version] + where_params
    return sql, params


def _conservation_totals(conn: sqlite3.Connection, spec: dict) -> tuple[int, int, int]:
    """保存則の比較先を返す:
    `(結合なし・キューブ側だけの SUM(n), 結合込み・キューブ列の filter だけの SUM(n),
    結合込み・filter 全体・`n` 測度の when 込みの SUM(n))`。

    1つ目と2つ目の一致は「結合が行を増減しない」（`taxon` は主キー結合）の確認。3つ目が
    summary の `n` 測度が数えるはずの集合（結合先の列の `filter`〔`not_null`〕や `n` の
    `when`〔年の窓〕で意図的に絞った後の合計）。
    """
    source = spec["source"]
    cube_filter = {c: v for c, v in (spec.get("filter") or {}).items() if not _is_joined_ref(c)}
    plain_spec = {"source": source}
    where_cube, params_cube = _filter_sql(plain_spec, cube_filter)
    where_cube_q, _ = _filter_sql(spec, cube_filter)
    cube_total = conn.execute(f"SELECT SUM(n) FROM {source} {where_cube}", params_cube).fetchone()[0] or 0

    n_sql = _col_sql(spec, "n")
    join_total = conn.execute(
        f"SELECT SUM({n_sql}) FROM {_from_sql(spec)} {where_cube_q}", params_cube
    ).fetchone()[0] or 0

    where_sql, where_params = _filter_sql(spec, spec.get("filter") or {})
    n_when = spec["measures"]["n"].get("when")
    if n_when:
        cond, when_params = _when_sql(spec, n_when)
        where_sql = f"{where_sql} AND {cond}" if where_sql else f"WHERE {cond}"
        where_params = list(where_params) + when_params
    joined_total = conn.execute(
        f"SELECT SUM({n_sql}) FROM {_from_sql(spec)} {where_sql}", where_params
    ).fetchone()[0] or 0
    return cube_total, join_total, joined_total


def _default_built_from(source: str) -> str:
    return f"{source} (sqlite={sqlite3.sqlite_version})"


def build_summary(
    conn: sqlite3.Connection,
    yaml_path=DEFAULT_YAML,
    *,
    built_from: str | None = None,
    spec_version: str = common.SUMMARY_SPEC_VERSION,
    registry_db: pathlib.Path | None = None,
) -> dict[str, dict]:
    """`conn`（`observation_agg`/`occurrence_agg` を持つ読み書き可能な
    `v2.sqlite`）に、`yaml_path`（既定 `aggregations/serving.yaml`）が宣言する
    summary 4表（`common.V2_SUMMARY_TABLES`）を作る。戻り値は表ごとの統計
    （`{"n_rows": ..., "sum_n": ...}`）。

    `built_from`（既定 `None`）を省略すると、表ごとに宣言された `source` から
    `f"{source} (sqlite={sqlite3.sqlite_version})"` を組み立てる（`_default_
    built_from`）——summary 4表が2つの `source` にまたがるため、単一の固定値を
    既定にすると occurrence_agg 由来の表に `observation_agg` という誤った
    `built_from` が付く。明示的に渡せば全表がその値になる（既存のテスト・
    呼び出し側の互換性のため残す）。

    `registry_db`（既定 `None` = `RYUIKI_REGISTRY_DB` 環境変数 > `data/db/registry.sqlite`）:
    `join:` を宣言した summary があるときだけ使う `registry.sqlite`（`ATTACH ... mode=ro`
    で別名 `registry` として読み取り専用に開く。D1）。無い、または `taxon` 表が無ければ
    縮退せず `MigrationError` で止める（結合を黙って省くと binom 単位の表が空になる）。

    機械検証・指紋の扱いはモジュール docstring 参照。1つでも検証に失敗すれば
    `common.MigrationError` で止まり、`observation_agg`/`occurrence_agg` は
    変わらないまま（`staged_table` の `with` ブロックの中で検証するため。A-1）。

    YAML の語彙検証（機械検証1）は summary 4表**すべて**について、SQL を1つも
    投げる前に済ませる——1表ずつ検証しながら作ると、1表目の SQL を実行した
    後になって別の表の宣言が壊れていると分かる事故になる（`staged_table` は
    表ごとに独立して確定するため、後の表の失敗は前の表の差し替えを取り消さない）。
    """
    common.require_sqlite_version()
    raw = common.load_yaml(yaml_path)
    _validate_manifest_shape(raw)
    summaries = raw["summaries"]
    for table_name in common.V2_SUMMARY_TABLES:
        _validate_summary_spec(table_name, summaries[table_name])

    # 段階間の指紋（Issue #37 #1）: 各 summary が使う `source`（observation_agg/
    # occurrence_agg）が「今の上流から作られた」ことまで遡って確認する（b04/b07
    # 未実行・古いまま再実行を検出する。upstream_schemas={} は「上流も同じ conn
    # 〔同じ v2.sqlite ファイル〕の main スキーマにある」という既定の解決先で
    # 足りるため——ATTACH は使わない）。同じ source を複数の summary が使っても、
    # source ごとに1回だけ確認する（キャッシュ）——**下の表構築ループの中で
    # 初めてその source を使う表に出会った時点で確認する**（YAML の語彙検証
    # （機械検証1、上の for ループ）とは別に、ここで先に全 source をまとめて
    # 確認してしまうと、一部の summary しか使わない環境（単体テストの最小
    # フィクスチャ等）で「他の summary が使う source のテーブルが無い」という
    # 無関係な理由で早期に落ちる——実際に使う直前まで確認を遅らせる）。
    fingerprint_by_source: dict[str, str] = {}

    needs_registry = any(summaries[t].get("join") for t in common.V2_SUMMARY_TABLES)
    registry_fingerprint = None
    if needs_registry:
        registry_path = common.resolve_registry_db(
            str(registry_db) if registry_db is not None else None, DEFAULT_REGISTRY_DB,
        )
        _attach_registry(conn, registry_path)
        registry_fingerprint = common._registry_input_fingerprint(registry_path)

    try:
        return _build_summary_tables(
            conn, summaries, fingerprint_by_source, registry_fingerprint,
            built_from=built_from, spec_version=spec_version,
        )
    finally:
        if needs_registry:
            conn.execute(f"DETACH DATABASE {_JOIN_ALIAS}")


def _attach_registry(conn: sqlite3.Connection, registry_path: pathlib.Path) -> None:
    """`registry.sqlite` を読み取り専用で `registry` として ATTACH し、`taxon` が
    あることを確かめる（無ければ止める。D1・設計書 §6-2）。
    """
    if not registry_path.exists():
        raise common.MigrationError(
            f"{registry_path} が無い。summary の registry 結合（D1）に必要——"
            "先に scripts/r01_build_registry.py を実行すること。"
        )
    # `file:` URI の `?mode=ro` は %-エスケープが要る文字（`?`/`#`/`%`）を含むパスで壊れる。
    uri = "file:" + urllib.parse.quote(str(registry_path.resolve())) + "?mode=ro"
    conn.execute(f"ATTACH DATABASE ? AS {_JOIN_ALIAS}", (uri,))
    has_taxon = conn.execute(
        f"SELECT 1 FROM {_JOIN_ALIAS}.sqlite_master WHERE type='table' AND name='taxon'"
    ).fetchone()
    if not has_taxon:
        conn.execute(f"DETACH DATABASE {_JOIN_ALIAS}")
        raise common.MigrationError(
            f"{registry_path} に taxon 表が無い（--files-only で作った registry ではないか）。"
            "scripts/r01_build_registry.py のフルビルドをやり直すこと。"
        )


def _build_summary_tables(
    conn: sqlite3.Connection, summaries: dict, fingerprint_by_source: dict[str, str],
    registry_fingerprint: str | None, *, built_from: str | None, spec_version: str,
) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for table_name in common.V2_SUMMARY_TABLES:
        spec = summaries[table_name]
        source = spec["source"]
        if source not in fingerprint_by_source:
            fingerprint_by_source[source] = common.assert_stage_fingerprint_fresh(
                conn, source, upstream_schemas={},
                rebuild_hint=_REBUILD_HINT_BY_SOURCE[source],
            )
        table_built_from = built_from if built_from is not None else _default_built_from(source)
        if spec.get("join") and built_from is None:
            table_built_from += f" + {_JOIN_ALIAS}:{','.join(spec['join'])}"
        create_sql = _create_table_sql(spec)
        insert_sql, insert_params = _insert_select_sql(spec, built_from=table_built_from, spec_version=spec_version)
        lineage = {source: fingerprint_by_source[source]}
        if spec.get("join"):
            # registry は pipeline_fingerprint を持たない別機構（registry_build）なので、
            # 系譜には「消費した時点の registry の入力指紋」を値として残す（鮮度判定は
            # check_v2_fresh が v2 全体の入力指紋として registry.input_fingerprint を
            # 見ているので、ここは来歴の記録）。
            lineage[f"{_JOIN_ALIAS}:{','.join(spec['join'])}"] = registry_fingerprint

        with common.staged_table(
            conn, table_name, create_sql,
            fingerprint_inputs=lineage,
            fingerprint_spec_version=spec_version,
        ) as staging:
            cur = conn.execute(insert_sql.format(table=f'"{staging}"'), insert_params)
            n_rows = cur.rowcount

            # 機械検証2: 次元キー（key）の一意性。
            common.assert_dimension_key_unique(
                conn, staging, spec["key"],
                index_name=f"{table_name}_key_uq",
                table_label=table_name,
                cause_hint=(
                    "aggregations/serving.yaml の group_by/key の宣言、または "
                    "キューブ側の重複を確認すること。"
                ),
            )

            # 機械検証3: 保存則（GROUP BY で行を分けても SUM(n) の合計は
            # 変わらないはず）。結合があるときは、結合が行を増減しないこと（taxon は
            # 主キー結合）も先に確かめる（D1・設計書 §2.1(d)）。
            summary_total = conn.execute(f'SELECT SUM(n) FROM "{staging}"').fetchone()[0] or 0
            cube_total, join_total, expected_total = _conservation_totals(conn, spec)
            if cube_total != join_total:
                raise common.MigrationError(
                    f"{table_name}: registry との結合で SUM(n) が変わった（結合前 {cube_total} → "
                    f"結合後 {join_total}）。結合先の表のキーが一意でない可能性がある。"
                )
            if summary_total != expected_total:
                raise common.MigrationError(
                    f"{table_name}: 保存則が崩れている（summary の SUM(n)={summary_total} が "
                    f"{spec['source']}（同じ filter・when）の SUM(n)={expected_total} と一致しない）。"
                    "aggregations/serving.yaml の filter/group_by を確認すること。"
                )

            # 機械検証4: 行数 > 0（filter が絞りすぎている事故を検出する）。
            if n_rows == 0:
                raise common.MigrationError(
                    f"{table_name}: 0行しか生成されなかった（filter が絞りすぎている可能性がある）。"
                )

        # 索引は差し替え確定後（本番テーブル名）に張る（common.create_indexes
        # docstring 参照。b04 と同じ順序）。
        common.create_indexes(
            conn, table_name,
            [
                (f"{table_name}_{'_'.join(index_cols)}", tuple(index_cols))
                for index_cols in (spec.get("indexes") or [])
            ],
        )
        stats[table_name] = {"n_rows": n_rows, "sum_n": summary_total}

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--v2-db", default=str(DEFAULT_V2_DB),
        help="observation_agg/occurrence_agg を持ち、summary_* を書き込む v2.sqlite（読み書き）",
    )
    parser.add_argument("--yaml", default=str(DEFAULT_YAML), help="aggregations/serving.yaml")
    parser.add_argument(
        "--registry-db", default=None,
        help="join: を宣言した summary が読む registry.sqlite（読み取り専用。"
        "既定: RYUIKI_REGISTRY_DB 環境変数 > data/db/registry.sqlite）",
    )
    args = parser.parse_args()

    db_path = pathlib.Path(args.v2_db)
    # `--v2-db` を `sqlite3.connect` で直接開く（`fresh_sqlite` を経由しない）ため、
    # ここで個別に検査する（`scripts/migrate/common.py` の
    # `reject_protected_source_db` の docstring 参照）。
    common.reject_protected_source_db(db_path)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に scripts/b04_build_cube.py・scripts/b07_build_occurrence_cube.py "
            "までを実行すること。"
        )

    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        n_obs_agg = conn.execute("SELECT COUNT(*) FROM observation_agg").fetchone()[0]
        n_occ_agg = conn.execute("SELECT COUNT(*) FROM occurrence_agg").fetchone()[0]
        print(
            f"▶ 読み書き可能で開く（observation_agg/occurrence_agg は変更しない）: {db_path} / "
            f"observation_agg {n_obs_agg:,}行 / occurrence_agg {n_occ_agg:,}行"
        )
        with common.timed_step("summary_* を構築") as info:
            stats = build_summary(conn, pathlib.Path(args.yaml), registry_db=args.registry_db)
            info["n"] = sum(s["n_rows"] for s in stats.values())
    finally:
        conn.close()

    for table_name, s in stats.items():
        print(f"  {table_name}: {s['n_rows']:,}行（SUM(n)={s['sum_n']:,}、保存則OK）")


if __name__ == "__main__":
    main()
