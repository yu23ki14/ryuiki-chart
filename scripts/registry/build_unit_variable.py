"""unit / variable / variable_alias を作る（docs/plans/PHASE_A.md §A-2、
docs/plans/PHASE_B_INTAKE.md #1）。

対象: measurements.variable（58種）と sensor_timeseries.datastream（59種）の
出典表記をエイリアスとして束ね、名前から単位・粒度・統計量を剥がした正準 variable
（ADR-0010）を作る。domain.ts の VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE /
VARIABLE_UNIT_FALLBACK の内容をここに移す。

このモジュールは data/db/registry.sqlite への書き込みロジックだけを持つ。実データは
すべて手書きの registry/unit.yaml・registry/variable.yaml・registry/variable_alias.csv
にあり（Git 管理・レビュー対象）、ここではそれを読んで unit / variable / variable_alias
の3テーブルに INSERT するだけ（原本 measurements / sensor_timeseries には一切触れない。
build() の引数 src はシグネチャ互換のため受け取るが、この3テーブルの構築には使わない）。

**原本 DB を一切開かない。** `--files-only` モード（scripts/r01_build_registry.py の
`--files-only`）で CI が走らせるのはこのモジュールだけを含む経路であり、原本
（ryuiki/cells/derived）が存在しない環境でも動くことが要件。`(dataset, alias, source_id)`
の3件組が v1 の実データと過不足なく一致するかどうかの検証は、原本を読む
scripts/r02_resolution_report.py 側の仕事（このモジュールの責務ではない）。

3ファイルの作成根拠・resolutionの実測値（154組=100%解決、単位欠落109,078行は現在
100%解決。うち104,410行は variable_alias.unit_id、残り4,668行（hydro.flow の
FLOWRATE、phase-b/variable-flow で確定）は variable.unit_id で解決している）は
A-2 担当のタスク報告と docs/plans/PHASE_B_INTAKE.md #1 の申し送りを参照。正式なレポートは
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


def _assert_unique(keys: list, label: str) -> None:
    """件数のハードコード assert ではなく、キーの一意性チェックにする（/simplify 修正5）。
    語彙が増減しても中身が壊れていなければ通る。中身（重複）が壊れていれば必ず落ちる。
    """
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"{label} が重複している: {dupes}"


def _load_unit_yaml() -> list[dict]:
    with UNIT_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["units"]
    _assert_unique([e["unit_id"] for e in entries], "registry/unit.yaml の unit_id")
    _assert_quantity_kind_codes(entries)
    return entries


def _load_variable_yaml() -> list[dict]:
    with VARIABLE_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["variables"]
    _assert_unique([e["variable_id"] for e in entries], "registry/variable.yaml の variable_id")
    return entries


def _assert_variable_unit_consistent_per_alias(rows: list[dict]) -> None:
    """同じ (dataset, alias) を共有する行は variable_id と unit_id が一致すること
    （docs/plans/PHASE_B_INTAKE.md 設計B-2）。これが崩れると
    `resolveVariableInfo()`（web/src/lib/registry/lookup.ts）が「どの source_id の
    行を引いたか」によって違う variable_id/unit_id を返しうる曖昧な状態になる。
    """
    seen: dict[tuple, tuple] = {}
    for r in rows:
        key = (r["dataset"], r["alias"])
        val = (r.get("variable_id") or None, r.get("unit_id") or None)
        prev = seen.get(key)
        if prev is not None and prev != val:
            raise AssertionError(
                f"registry/variable_alias.csv: (dataset, alias)={key!r} の行で "
                f"variable_id/unit_id が一致しない: {prev!r} と {val!r}"
            )
        seen[key] = val


def _assert_fiscal_year_not_first_when_mixed(rows: list[dict]) -> None:
    """`web/scripts/lib/registry-codegen.mjs` の `dedupeByAlias()` は、同じ alias
    文字列を持つ複数行（`(dataset, alias, source_id)` の分割で増えた分）のうち
    CSV の行順で最初の1行だけを代表として残す。ある alias に
    `grain != 'fiscal_year'` の行が1つでもあるなら、その alias の最初の行
    （CSV順）も `grain != 'fiscal_year'` でなければならない。さもないと
    `primaryAlias()`/`buildClientVariableMaps()` がこの alias を誤って
    fiscal_year 扱いし、`VARIABLE_SHORT`/`VARIABLE_NOTE` からその alias が
    黙って抜け落ちる（code-review 指摘: 以前はコードコメントだけが前提を
    保証しており、ビルドは落ちなかった）。
    """
    first_grain: dict[tuple, str] = {}
    grains: dict[tuple, set] = {}
    for r in rows:
        key = (r["dataset"], r["alias"])
        grain = r.get("grain") or ""
        first_grain.setdefault(key, grain)
        grains.setdefault(key, set()).add(grain)
    for key, first in first_grain.items():
        if first == "fiscal_year" and grains[key] != {"fiscal_year"}:
            raise AssertionError(
                f"registry/variable_alias.csv: {key!r} の最初の行が "
                f"grain='fiscal_year' だが、同じ alias に他の grain の行がある: "
                f"{sorted(grains[key])}。dedupeByAlias() がこの alias を誤って "
                "fiscal_year 扱いする。grain='fiscal_year' でない行を先に置くこと。"
            )


# grain/stat のコードリスト。一次資料調査（docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md）で
# (dataset, alias, source_id) の組ごとに固定1値へ決め切ったため、'mixed' のような
# 「行ごとに決まる」値はもう無い。ここにあるのは実際に registry/variable_alias.csv で
# 使われている値の集合であり、新しい値を推測で発明しないためのガード
# （このリストに無い値が来たらビルドを落とす。値を増やすときはこのリスト自体を
# 更新し、根拠を PHASE_B_ALIAS_STAT_SOURCES.md 等に残すこと）。
GRAIN_CODES = frozenset({"hour", "day", "month", "year", "fiscal_year"})
STAT_CODES = frozenset({
    "", "point", "mean", "min", "max", "sum",
    "p75", "p90", "max_10min", "max_1h", "max_daily",
    "mean_of_daily_min", "mean_of_daily_max",
})

# registry/unit.yaml の quantity_kind のコードリスト。GRAIN_CODES/STAT_CODES と同じ理由の
# 同じ形のガード（このリストに無い値が来たらビルドを落とす。増やすときはこのリスト自体を
# 更新し、根拠を残すこと）。既存値は QUDT（https://qudt.org/vocab/quantitykind/）の
# 量種名に揃えた命名（例: 流量は QUDT の `VolumeFlowRate` に合わせて `volume_flow_rate`）。
QUANTITY_KIND_CODES = frozenset({
    "mass_concentration", "microbial_density", "elevation", "length", "temperature",
    "area", "count", "volume_fraction", "time", "pressure", "fraction", "velocity",
    "volume_flow_rate", "dimensionless",
})


def _assert_quantity_kind_codes(entries: list[dict]) -> None:
    """quantity_kind がコードリスト外の値を持たないこと（空/未設定は許容する）。"""
    for e in entries:
        qk = e.get("quantity_kind") or ""
        if qk and qk not in QUANTITY_KIND_CODES:
            raise AssertionError(
                f"registry/unit.yaml: 未知の quantity_kind={qk!r} "
                f"unit_id={e['unit_id']!r}（コードリスト: {sorted(QUANTITY_KIND_CODES)}）"
            )


def _assert_grain_and_stat_codes(rows: list[dict]) -> None:
    """grain/stat がコードリスト外の値を持たないこと。"""
    for r in rows:
        grain = r.get("grain") or ""
        stat = r.get("stat") or ""
        if grain not in GRAIN_CODES:
            raise AssertionError(
                f"registry/variable_alias.csv: 未知の grain={grain!r} "
                f"alias={r['alias']!r} dataset={r['dataset']!r} "
                f"source_id={r.get('source_id')!r}（コードリスト: {sorted(GRAIN_CODES)}）"
            )
        if stat not in STAT_CODES:
            raise AssertionError(
                f"registry/variable_alias.csv: 未知の stat={stat!r} "
                f"alias={r['alias']!r} dataset={r['dataset']!r} "
                f"source_id={r.get('source_id')!r}（コードリスト: {sorted(STAT_CODES)}）"
            )


def _load_variable_alias_csv() -> list[dict]:
    with VARIABLE_ALIAS_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    # エイリアスは「出典 × 表記」で解決する（ADR-0010 決定1）。一意性は
    # (dataset, alias, source_id) の組で見る（source_id が空の行＝出典未記録も
    # Python 側で明示的に None として扱い、SQLite の「NULL は互いに異なる」に
    # 頼らない。web/src/db/schema-registry.ts の variableAlias 参照）。
    _assert_unique(
        [(r["dataset"] or None, r["alias"], r.get("source_id") or None) for r in rows],
        "registry/variable_alias.csv の (dataset, alias, source_id)",
    )
    _assert_variable_unit_consistent_per_alias(rows)
    _assert_grain_and_stat_codes(rows)
    _assert_fiscal_year_not_first_when_mixed(rows)
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
        (r["alias"], r.get("dataset") or None, r.get("source_id") or None,
         r.get("variable_id") or None, r.get("unit_id") or None, r.get("stat") or None,
         r.get("grain") or None, r.get("note") or None)
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
        ["alias", "dataset", "source_id", "variable_id", "unit_id", "stat", "grain", "note"],
        _variable_alias_rows(alias_rows_raw),
    )
    return {"unit": n_unit, "variable": n_variable, "variable_alias": n_alias}
