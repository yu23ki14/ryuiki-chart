"""unit / variable / variable_alias を作る（docs/plans/PHASE_A.md §A-2）。

対象: measurements.variable（58種）と sensor_timeseries.datastream（59種）の
出典表記をエイリアスとして束ね、名前から単位・粒度・統計量を剥がした正準 variable
（ADR-0010）を作る。domain.ts の VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE /
VARIABLE_UNIT_FALLBACK の内容をここに移す。

このモジュールは data/db/registry.sqlite への書き込みロジックだけを持つ。実データは
すべて手書きの registry/unit.yaml・registry/variable.yaml・registry/variable_alias.csv
にあり（Git 管理・レビュー対象）、ここではそれを読んで unit / variable / variable_alias
の3テーブルに INSERT するだけ（原本 measurements / sensor_timeseries には一切触れない。
build() の引数 src はシグネチャ互換のため受け取るが、この3テーブルの構築には使わない）。

3ファイルの作成根拠・resolutionの実測値（117エイリアス=100%解決、単位欠落109,078行のうち
104,410行がエイリアス側の unit_id で解決）は A-2 担当のタスク報告を参照。正式なレポートは
A-6 (scripts/r02_resolution_report.py) が作る。
"""
import csv
import pathlib
import sqlite3

import yaml

from . import common

UNIT_YAML = common.ROOT / "registry" / "unit.yaml"
VARIABLE_YAML = common.ROOT / "registry" / "variable.yaml"
VARIABLE_ALIAS_CSV = common.ROOT / "registry" / "variable_alias.csv"


def _load_unit_yaml() -> list[dict]:
    with UNIT_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["units"]
    assert len(entries) == 28, f"registry/unit.yaml は28件のはずが{len(entries)}件"
    return entries


def _load_variable_yaml() -> list[dict]:
    with VARIABLE_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["variables"]
    assert len(entries) == 85, f"registry/variable.yaml は85件のはずが{len(entries)}件"
    return entries


def _load_variable_alias_csv() -> list[dict]:
    with VARIABLE_ALIAS_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 117, f"registry/variable_alias.csv は117行のはずが{len(rows)}行"
    return rows


def _unit_rows(entries: list[dict]) -> list[tuple]:
    return [
        (e["unit_id"], e.get("symbol") or None, e.get("ucum") or None,
         e.get("name_ja") or None, e.get("quantity_kind") or None)
        for e in entries
    ]


def _variable_rows(entries: list[dict]) -> list[tuple]:
    rows = []
    for e in entries:
        hiw = e.get("higher_is_worse")
        rows.append((
            e["variable_id"], e.get("code") or None, e.get("name_ja") or None,
            e.get("name_en") or None, e.get("theme") or None, e.get("unit_id") or None,
            e.get("value_type") or None, e.get("default_stat") or None,
            None if hiw is None else int(bool(hiw)),
            e.get("description_ja") or None, e.get("status") or None,
        ))
    return rows


def _variable_alias_rows(rows: list[dict]) -> list[tuple]:
    return [
        (r["alias"], r.get("source_scope") or None, r.get("variable_id") or None,
         r.get("unit_id") or None, r.get("stat") or None, r.get("grain") or None,
         r.get("note") or None)
        for r in rows
    ]


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション
    （このモジュールでは未使用。原本は registry/*.yaml・*.csv を手書きする時点で
    参照済みであり、build() 自体は原本に触れない）。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。
    """
    unit_entries = _load_unit_yaml()
    variable_entries = _load_variable_yaml()
    alias_rows_raw = _load_variable_alias_csv()

    n_unit = common.insert_many(
        conn, "unit",
        ["unit_id", "symbol", "ucum", "name_ja", "quantity_kind"],
        _unit_rows(unit_entries),
    )
    n_variable = common.insert_many(
        conn, "variable",
        ["variable_id", "code", "name_ja", "name_en", "theme", "unit_id",
         "value_type", "default_stat", "higher_is_worse", "description_ja", "status"],
        _variable_rows(variable_entries),
    )
    n_alias = common.insert_many(
        conn, "variable_alias",
        ["alias", "source_scope", "variable_id", "unit_id", "stat", "grain", "note"],
        _variable_alias_rows(alias_rows_raw),
    )
    return {"unit": n_unit, "variable": n_variable, "variable_alias": n_alias}
