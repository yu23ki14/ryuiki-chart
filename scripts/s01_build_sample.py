#!/usr/bin/env python3
"""縮小サンプル（Issue #29「縮小サンプル＋実行証明」A-1）を原本から切り出す。

    .venv/bin/python3 scripts/s01_build_sample.py

読むのは常に読み取り専用（原本 `data/db/ryuiki.sqlite`/`cells.sqlite`・
`data/processed/*`）で、書くのは `data/sample/` 配下のテキストだけ
（sqlite バイナリは一切書かない——コミット対象はテキストにする、という
CLAUDE.md 「サンプル」設計の要件）。

## 何を選ぶか（宣言）と、どう閉包を取るか（コード）

`data/sample/coverage.yaml` の `predicates`（table + where + limit の3つ組。
`ORDER BY rowid LIMIT` で決定論的に選ぶ）と `full_closures`（where に一致する
全行、上限なし）が「何を含めるか」の宣言。このスクリプトは次の閉包を
コード側で追加する:

- **地点×変数の全期間**（`measurements` のみ。`sensor_timeseries` は
  対象外——時系列が密で全期間展開すると閉包が数万行に膨らむため、
  `coverage.yaml` の predicate 自体で `source_id` ごとに小さく上限を切っている）。
- **`quality_transitions`（丸ごと）が参照する `measurements.measurement_id`**。
  `quality_transitions` は「丸ごと入れるもの」だが、参照先の測定行が
  サンプルに無いと「親行が無い」状態になる（閉包「参照の整合」）。
- **属の全記録**は `coverage.yaml` の `full_closures`（`genus = 'Sirosporium'`、
  上限なし）自体がそのまま閉包になっている——追加のコードは無い。
- **文書単位**（`cells.sqlite` の `cells`）は `document_closure.doc_ids` で
  指定した `doc_id` の全セルを入れる。

## 決定論

述語＋`ORDER BY rowid`＋固定の上限で選ぶ（乱数は使わない）。同じ原本から
2回実行するとテキストがバイト単位で一致する（`scripts/tests/
test_s01_build_sample.py::test_determinism`）。挿入順は原本の rowid 順を
保つ——`scripts/s02_materialize_sample.py` が同じ順で `INSERT` するので、
材料化したサンプルの新しい rowid も相対順が保たれる（b06 の
`source_row_id=rowid` やメモ化のタイブレークが依存する性質）。

## 出力

- `data/sample/ryuiki_schema.sql` / `data/sample/cells_schema.sql`:
  対象テーブルの `CREATE TABLE` 文（`sqlite_master.sql` からそのまま）。
- `data/sample/ryuiki/<table>.sql` / `data/sample/cells/<table>.sql`:
  `INSERT INTO ... VALUES (...);` の並び（`rowid` 昇順）。
- `data/sample/processed/<file>`: `wholesale_processed_files` のコピー。
- `data/sample/manifest.json`: 原本・入力ファイルの sha256、テーブルごとの
  サンプル行数。
- `data/sample/declaration_counts.yaml`: 件数の宣言の上書き値
  （`scripts/migrate/period.apply_count_overlay` が読む形。§A-2）。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import pathlib
import shutil
import sqlite3
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402
from migrate import occurrence_period  # noqa: E402
from migrate import point_in_polygon as pip  # noqa: E402
from migrate import source_regions  # noqa: E402
from reconcile.common import load_yaml  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_CELLS_DB = ROOT / "data" / "db" / "cells.sqlite"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "processed"
DEFAULT_COVERAGE_YAML = ROOT / "data" / "sample" / "coverage.yaml"
DEFAULT_OUT_DIR = ROOT / "data" / "sample"
DEFAULT_GEOJSON = ROOT / "data" / "processed" / "nlni_w12_watersheds.geojson"
DEFAULT_LANDUSE_CSV = ROOT / "data" / "processed" / "nlni_l03b_landuse_by_watershed.csv"

# ---------------------------------------------------------------------------
# 小さなユーティリティ
# ---------------------------------------------------------------------------


def _sql_classify_shape(value: str | None) -> str | None:
    """`data/sample/coverage.yaml` の `classify_shape(observed_on) = '...'`
    述語・`build_declaration_counts` の実測の両方から呼ぶ、`occurrence_period.
    classify_shape` の SQL 関数ラッパ。NULL は「形が無い」として NULL を返す
    （`length(observed_on) = N` の頃と同じく、NULL はどの形にも一致しない）。
    それ以外はそのまま呼ぶ——形を1つに決められない値（`UnknownPeriodShapeError`/
    `AmbiguousPeriodShapeError`）を黙って握りつぶさない（code-review 指摘: 文字数
    だけで決め打つと将来の衝突を見逃す、への対応そのものなので、ここでも
    エラーを飲み込まない）。
    """
    if value is None:
        return None
    return occurrence_period.classify_shape(value)


def register_classify_shape(conn: sqlite3.Connection) -> None:
    """`conn` に `classify_shape(observed_on)` を SQL 関数として登録する。
    `data/sample/coverage.yaml` の predicate（`select_ryuiki_rowids` 経由）と
    `build_declaration_counts` の両方が呼ぶ前提——`_open_ro` から自動的に
    登録されるが、テストのようにこの関数を経由せず自前で `sqlite3.connect()`
    する場合は呼び出し側が明示的に呼ぶ（`scripts/tests/test_s01_build_sample.py`・
    `scripts/tests/test_sample_coverage.py` 参照）。何度呼んでも安全（sqlite3 は
    同名関数の再登録を単に上書きする）。
    """
    conn.create_function("classify_shape", 1, _sql_classify_shape)


def _open_ro(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    register_classify_shape(conn)
    return conn


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (bytes, bytearray)):
        return "X'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


_INSERT_BATCH_SIZE = 200


def _write_table_sql(conn: sqlite3.Connection, table: str, rowids: list[int], out_path: pathlib.Path) -> int:
    """`rowids`（昇順であること）の行を `INSERT INTO table (...) VALUES (...), (...), ...;`
    の複数行 VALUES（`_INSERT_BATCH_SIZE` 行ごと）でまとめて `out_path` に書く。
    列名は `PRAGMA table_info` の現在の並び。

    複数行 VALUES にまとめる理由: `INSERT INTO "table" (col1, ..., colN) VALUES`
    の列名の並びを1行ごとに繰り返すと、テキストの大半が繰り返しの列名になり
    サンプルのテキスト総量（目安10MB前後）を無駄に押し上げる
    （measurements 実測: 1行ごとの INSERT で26MB → バッチ化で大幅に縮小）。
    `sqlite3.Connection.executescript()` は複数行 VALUES を問題なく実行できる。
    """
    columns = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    col_list = ", ".join(f'"{c}"' for c in columns)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"-- table: {table} ({len(rowids)} rows, generated by scripts/s01_build_sample.py)"]
    if rowids:
        select_cols = ", ".join(f'"{c}"' for c in columns)
        for i in range(0, len(rowids), _INSERT_BATCH_SIZE):
            batch = rowids[i : i + _INSERT_BATCH_SIZE]
            ph = ",".join("?" * len(batch))
            rows = conn.execute(
                f'SELECT {select_cols} FROM "{table}" WHERE rowid IN ({ph}) ORDER BY rowid', batch
            ).fetchall()
            value_tuples = [
                "(" + ", ".join(_sql_literal(row[c]) for c in columns) + ")" for row in rows
            ]
            lines.append(f'INSERT INTO "{table}" ({col_list}) VALUES\n' + ",\n".join(value_tuples) + ";")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rowids)


def _write_schema_sql(conn: sqlite3.Connection, tables: list[str], out_path: pathlib.Path) -> None:
    lines = [
        "-- generated by scripts/s01_build_sample.py（sqlite_master.sql をそのまま）",
    ]
    for table in tables:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if row is None or row["sql"] is None:
            raise SystemExit(f"{table} の CREATE TABLE 文が見つからない")
        lines.append(row["sql"].rstrip().rstrip(";") + ";")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 選択（predicates + full_closures）
# ---------------------------------------------------------------------------


def _select_rowids(conn: sqlite3.Connection, table: str, where: str, limit: int | None) -> list[int]:
    sql = f'SELECT rowid FROM "{table}" WHERE {where} ORDER BY rowid'
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql)]


def select_ryuiki_rowids(conn: sqlite3.Connection, coverage: dict) -> dict[str, set[int]]:
    """`predicates`/`full_closures` を評価し、テーブル名 -> rowid の集合を返す
    （この時点ではまだ「地点×変数の全期間」等の閉包を含まない）。
    """
    default_limit = coverage.get("default_limit", 20)
    selected: dict[str, set[int]] = defaultdict(set)
    for pred in coverage.get("predicates", []):
        table = pred["table"]
        limit = pred.get("limit", default_limit)
        rowids = _select_rowids(conn, table, pred["where"], limit)
        if not rowids:
            raise SystemExit(f"predicate {pred['name']!r}: 1行も一致しなかった（{table}: {pred['where']}）")
        selected[table].update(rowids)
    for closure in coverage.get("full_closures", []):
        table = closure["table"]
        rowids = _select_rowids(conn, table, closure["where"], None)
        if not rowids:
            raise SystemExit(f"full_closures {closure['name']!r}: 1行も一致しなかった（{table}: {closure['where']}）")
        selected[table].update(rowids)
    return selected


def apply_measurement_site_variable_closure(conn: sqlite3.Connection, rowids: set[int]) -> set[int]:
    """`measurements` の選択済み rowid から `(site_id, variable)` の組を集め、
    それぞれの組の全期間（全 rowid）を閉包に足す。

    `full_closures`（SS閉包25,167行・地盤沈下閉包3,286行）を含む数万件になり
    うるため、SQLite のバインドパラメータ上限を超えないよう大きな `IN (...)`
    は作らずテンポラリテーブルに実体化してから JOIN する。
    """
    if not rowids:
        return set(rowids)
    _create_rowid_temp_table(conn, "__s01_closure_seed", rowids)
    pairs = conn.execute(
        "SELECT DISTINCT m.site_id, m.variable FROM measurements m "
        "JOIN temp.__s01_closure_seed s ON m.rowid = s.rowid_value"
    ).fetchall()
    closed = set(rowids)
    for row in pairs:
        more = conn.execute(
            "SELECT rowid FROM measurements WHERE site_id IS ? AND variable IS ?",
            (row["site_id"], row["variable"]),
        ).fetchall()
        closed.update(r["rowid"] for r in more)
    return closed


def apply_quality_transitions_closure(conn: sqlite3.Connection, measurement_rowids: set[int]) -> set[int]:
    """`quality_transitions`（丸ごと）が参照する `measurements.measurement_id`
    を rowid に解決し、`measurement_rowids` に足す（参照の整合）。
    """
    ids = sorted({r["target_id"] for r in conn.execute(
        "SELECT DISTINCT target_id FROM quality_transitions WHERE target_table = 'measurements'"
    )})
    closed = set(measurement_rowids)
    chunk_size = 200
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        placeholder = ",".join("?" * len(chunk))
        rows = conn.execute(
            f'SELECT rowid FROM measurements WHERE measurement_id IN ({placeholder})', chunk
        ).fetchall()
        closed.update(r["rowid"] for r in rows)
    return closed


def select_wholesale_rowids(conn: sqlite3.Connection, table: str) -> list[int]:
    return [r[0] for r in conn.execute(f'SELECT rowid FROM "{table}" ORDER BY rowid')]


def select_cells_rowids(conn: sqlite3.Connection, doc_ids: list[str]) -> list[int]:
    placeholder = ",".join("?" * len(doc_ids))
    return [
        r[0]
        for r in conn.execute(
            f'SELECT rowid FROM cells WHERE doc_id IN ({placeholder}) ORDER BY rowid', doc_ids
        )
    ]


# ---------------------------------------------------------------------------
# declaration_counts.yaml（Issue #29 A-2）
# ---------------------------------------------------------------------------


def _year4(value: str | None) -> str | None:
    if not value or len(value) < 4 or not value[:4].isdigit():
        return None
    return value[:4]


def compute_leaf_cell_source_rows(rows: list[sqlite3.Row]) -> int:
    """b07 の「leaf セル」（grain='survey_period' で年をまたぐ区間）に集約される
    日付ありレコード数を数える。12形のうち区間形（'/' を含む4形）だけが対象——
    両端の年（先頭4桁）が違えば「年をまたぐ」。
    """
    n = 0
    for row in rows:
        observed_on = row["observed_on"]
        if not observed_on or "/" not in observed_on:
            continue
        left, right = observed_on.split("/", 1)
        y1, y2 = _year4(left), _year4(right)
        if y1 is not None and y2 is not None and y1 != y2:
            n += 1
    return n


def load_utc_offset_by_source(manifests_dir=source_regions.DEFAULT_MANIFESTS_DIR) -> dict[str, str]:
    """`manifests/*.yml`（target=occurrence）から `{source_id: utc_offset}`
    を組み立てる。`compute_month_cell_source_rows` が 'Z' 終端の瞬時記録を
    ローカル時刻へ変換するのに使う（region の utc_offset）。

    `load_source_regions()` 自体は「宣言が使われたか」（`EntryUsage`）を
    追跡しない素の読み込みなので、ここでの呼び出しは副作用が無く安全
    （b06 のように `mark_used()` を追う必要が無い——s01 は宣言の一部だけを
    使っても「未使用宣言」にはならない）。
    """
    sources, regions = source_regions.load_source_regions(manifests_dir, consumer="occurrence")
    return {source_id: regions[s.region_id].utc_offset for source_id, s in sources.items()}


def compute_month_cell_source_rows(rows: list[sqlite3.Row], utc_offset_by_source: dict[str, str]) -> int:
    """b07 の「月セル」（grain='month'。同一月に収まる日付ありレコード）に
    集約される件数を数える。

    `compute_leaf_cell_source_rows` の年境界判定は `observed_on` の文字列を
    直接見るだけの近似で足りた（'Z' 変換で日付が変わっても年をまたぐことは
    無い——region の utc_offset は最大でも数時間のずれで、年境界をまたぐには
    12/31深夜のような際どいケースしか無く、実測では発生しない）。月境界は
    'Z' の変換で月をまたぐことが実際にある（実測で最大10件——設計書 §0
    参照）ため、b06/b07 と同じ `migrate.occurrence_period.expand_period()`
    を呼んで実際に展開した `period_start`/`period_end` で判定する
    （近似で済ませない）。
    """
    n = 0
    for row in rows:
        observed_on = row["observed_on"]
        if not observed_on:
            continue
        utc_offset = utc_offset_by_source[row["source_id"]]
        expanded = occurrence_period.expand_period(observed_on, utc_offset, record_id=row["record_id"])
        if expanded.period_start[:7] == expanded.period_end[:7]:
            n += 1
    return n


def compute_occurrence_place_and_watershed_stats(rows: list[sqlite3.Row], geojson_path) -> dict:
    """`occurrence_place_declarations.yaml`（3件。`n_watershed_polygons` は
    読み込んだ `polys` からそのまま数える）と `occurrence_cube_declarations.yaml` の
    流域の2件（日付あり記録の解決済み・未解決）をサンプルに対して実測する。
    （v1 のメモ化の再現〔`occurrence_watershed_v1_declarations.yaml`〕は Issue #48 PR-5 で消えた。）
    """
    polys = pip.load_polygons(geojson_path)
    grid = pip.build_grid(polys)

    geo_rows = [r for r in rows if r["lat"] is not None and r["lon"] is not None]
    exact_watershed: dict[str, str | None] = {}
    for row in geo_rows:
        matched, _near = pip.locate(row["lon"], row["lat"], polys, grid)
        exact_watershed[row["record_id"]] = matched[0] if len(matched) == 1 else None

    n_null = sum(1 for v in exact_watershed.values() if v is None)
    n_resolved = len(exact_watershed) - n_null

    # occurrence_cube_declarations.yaml の watershed_dated_resolved_rows/
    # watershed_dated_unresolved_rows（Issue #48 PR-3a）: 母集団は
    # `occurrence_place_declarations.yaml`（座標のある全記録）と違い
    # 「日付あり」記録（b07 の watershed 母集団と同じ母集団）。実データでは
    # 日付あり記録は必ず座標も持つ（no_coordinate_count=0）ため
    # `exact_watershed`（座標のある記録だけを解決済み）で引けばよい——
    # 座標を持たない日付あり記録があれば `.get()` が None を返し
    # 「未解決」側に数えるが、この場合は occurrence_place 自体にその記録の
    # 行が無いはずで、実際には b07 の母集団完全性検査が別途止める。
    dated_record_ids = {r["record_id"] for r in rows if r["observed_on"] is not None}
    n_watershed_dated_resolved = sum(
        1 for rid in dated_record_ids if exact_watershed.get(rid) is not None
    )
    n_watershed_dated_unresolved = len(dated_record_ids) - n_watershed_dated_resolved

    return {
        # `polys` は既にこの関数が読み込み済みの流域ポリゴン一覧
        # （feature 1件 = Polygon 1件。`point_in_polygon.load_polygons`
        # docstring「実測: 377 feature 全件が Polygon」参照）。ここから
        # 数えることで、ハードコードした 377 を実測値に置き換える
        # （code-review 指摘対応）。
        "n_watershed_polygons": len(polys),
        "place_id_null_count": n_null,
        "resolved_count": n_resolved,
        "watershed_dated_resolved_rows": n_watershed_dated_resolved,
        "watershed_dated_unresolved_rows": n_watershed_dated_unresolved,
    }


def _create_rowid_temp_table(conn: sqlite3.Connection, name: str, rowids: set[int]) -> None:
    """`rowids`（大きな集合になりうる。バインドパラメータ100個/1000個の制限を
    避けるため、大きな `IN (...)` を作らずテンポラリテーブルに実体化する）を
    一時テーブル `name` に書く。
    """
    conn.execute(f"DROP TABLE IF EXISTS temp.{name}")
    conn.execute(f"CREATE TEMP TABLE {name} (rowid_value INTEGER PRIMARY KEY)")
    conn.executemany(f"INSERT INTO temp.{name} (rowid_value) VALUES (?)", [(r,) for r in rowids])


def count_csv_data_rows(csv_path) -> int:
    """`csv_path`（ヘッダ1行 + データ行）のデータ行数を数える。土地利用CSVは
    `wholesale_processed_files`（coverage.yaml）で丸ごとコピーするだけなので、
    サンプルの件数は原本の行数と同じになる——ハードコードした 4,858 を
    実測値に置き換える（code-review 指摘対応）。
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def build_declaration_counts(
    conn: sqlite3.Connection,
    ryuiki_selected: dict[str, set[int]],
    geojson_path=DEFAULT_GEOJSON,
    landuse_csv_path=DEFAULT_LANDUSE_CSV,
    manifests_dir=source_regions.DEFAULT_MANIFESTS_DIR,
) -> dict[str, int]:
    """`data/sample/declaration_counts.yaml` の中身（フラットな
    `"<宣言ファイル名>:<エントリ名>[.<内訳キー>]"` -> 整数）を実測する。
    """
    # occurrence_period_shapes.yaml の実測が classify_shape(observed_on) を
    # 使うため、呼び出し側が `_open_ro` を経由していない（テストが自前で
    # `sqlite3.connect()` した）場合に備えてここでも登録しておく（何度
    # 呼んでも安全。register_classify_shape docstring 参照）。
    register_classify_shape(conn)
    out: dict[str, int] = {}

    _temp_ready: set[str] = set()

    def _ensure_temp(table: str) -> str:
        """`table` 用の rowid 一時テーブルを（空でも）必ず作ってその名前を返す。
        `rowids` が空でも一時テーブル自体は作る——`count()` の早期リターンに
        頼ると、後段（`org_rows` の取得等）が無条件に参照する一時テーブルが
        1回も作られないまま残る事故になる（coverage.yaml が
        `organism_records` を一切選ばない構成でも安全に動くようにする）。
        """
        temp_name = f"__s01_{table}_rowids"
        if table not in _temp_ready:
            _create_rowid_temp_table(conn, temp_name, ryuiki_selected.get(table, set()))
            _temp_ready.add(table)
        return temp_name

    def count(table: str, where: str) -> int:
        temp_name = _ensure_temp(table)
        sql = (
            f'SELECT COUNT(*) FROM "{table}" t '
            f'JOIN temp.{temp_name} s ON t.rowid = s.rowid_value WHERE ({where})'
        )
        return conn.execute(sql).fetchone()[0]

    # organism_records の一覧は後段（occurrence_cube/place/watershed）でも
    # 使うため、ここで一時テーブルを確定させておく（0件でも作る。上の
    # `_ensure_temp` docstring 参照）。
    _ensure_temp("organism_records")

    # period_exceptions.yaml
    out["period_exceptions.yaml:atsugi_river_water_quality"] = count(
        "measurements", "source_id = 'atsugi_river_water_quality' AND length(measured_on) = 4"
    )

    # time_label_conventions.yaml（この2出典は全量が value_grain='hour' なので、
    # source_id 一致件数がそのまま該当件数になる。migrate/time_label_conventions.yaml 参照）
    out["time_label_conventions.yaml:sagamihara_taiki_hourly"] = count(
        "sensor_timeseries", "source_id = 'sagamihara_taiki_hourly'"
    )
    out["time_label_conventions.yaml:soramame_hourly_kanagawa"] = count(
        "sensor_timeseries", "source_id = 'soramame_hourly_kanagawa'"
    )

    # manifests/*.yml
    out["manifests:gbif_kanagawa_occurrences"] = count(
        "organism_records", "source_id = 'gbif_kanagawa_occurrences'"
    )
    out["manifests:inaturalist_kanagawa"] = count(
        "organism_records", "source_id = 'inaturalist_kanagawa'"
    )
    # 土地利用CSVは丸ごとコピーする（coverage.yaml の wholesale_processed_files）
    # ので、サンプルの件数は原本の行数と同じ（実測: count_csv_data_rows 参照）。
    out["manifests:nlni_l03b_landuse_by_watershed"] = count_csv_data_rows(landuse_csv_path)

    # occurrence_period_shapes.yaml。形の名前は宣言ファイル（コードの
    # `_SHAPE_DEFS` と過不足なく一致することを `assert_declared_shapes_match_code`
    # が検証済み）からそのまま読む——手で列挙すると形が増えたときに追従し忘れる
    # 余地が生まれる。分類そのものは `classify_shape`（SQL 関数として
    # `_open_ro` が登録済み）を使う（以前の `length(observed_on) = N` は
    # 「12形の文字数がたまたま全部異なる」という前提の近似だった。
    # code-review 指摘対応。coverage.yaml も同じ関数に揃えてある）。
    for name in sorted(occurrence_period.load_period_shapes()):
        out[f"occurrence_period_shapes.yaml:{name}"] = count(
            "organism_records", f"classify_shape(observed_on) = '{name}'"
        )

    # occurrence_cube_declarations.yaml
    org_rows = conn.execute(
        "SELECT t.rowid AS rowid, t.record_id, t.observed_on, t.lat, t.lon, t.scientific_name, "
        "t.is_alien, t.red_list_category, t.source_id "
        "FROM organism_records t JOIN temp.__s01_organism_records_rowids s ON t.rowid = s.rowid_value "
        "ORDER BY t.rowid"
    ).fetchall()
    out["occurrence_cube_declarations.yaml:leaf_cell_source_rows"] = compute_leaf_cell_source_rows(org_rows)
    utc_offset_by_source = load_utc_offset_by_source(manifests_dir)
    out["occurrence_cube_declarations.yaml:month_cell_source_rows"] = compute_month_cell_source_rows(
        org_rows, utc_offset_by_source,
    )

    # occurrence_place_declarations.yaml / occurrence_cube_declarations.yaml（流域の2件）
    stats = compute_occurrence_place_and_watershed_stats(org_rows, geojson_path)
    out["occurrence_place_declarations.yaml:n_watershed_polygons"] = stats["n_watershed_polygons"]
    out["occurrence_place_declarations.yaml:place_id_null_count"] = stats["place_id_null_count"]
    out["occurrence_place_declarations.yaml:resolved_count"] = stats["resolved_count"]
    out["occurrence_cube_declarations.yaml:watershed_dated_resolved_rows"] = stats[
        "watershed_dated_resolved_rows"
    ]
    out["occurrence_cube_declarations.yaml:watershed_dated_unresolved_rows"] = stats[
        "watershed_dated_unresolved_rows"
    ]

    return out


def _dump_declaration_counts_yaml(counts: dict[str, int]) -> str:
    lines = [
        "# scripts/s01_build_sample.py が生成した、縮小サンプルの件数の宣言の上書き値。",
        "# 手で編集しない（scripts/s01_build_sample.py を再実行して作り直すこと）。",
        "# 形式・使い方は docs/plans/PHASE_B_RECONCILIATION.md §5 と",
        "# scripts/migrate/period.py の apply_count_overlay/load_count_overlay_file を参照。",
        "",
    ]
    for key in sorted(counts):
        lines.append(f'"{key}": {int(counts[key])}')
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ryuiki-db", default=str(DEFAULT_RYUIKI_DB))
    parser.add_argument("--cells-db", default=str(DEFAULT_CELLS_DB))
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--coverage-yaml", default=str(DEFAULT_COVERAGE_YAML))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    coverage = load_yaml(args.coverage_yaml)
    out_dir = pathlib.Path(args.out_dir)

    ryuiki_conn = _open_ro(args.ryuiki_db)
    cells_conn = _open_ro(args.cells_db)

    # --- 選択 ---
    selected = select_ryuiki_rowids(ryuiki_conn, coverage)
    selected["measurements"] = apply_measurement_site_variable_closure(
        ryuiki_conn, selected.get("measurements", set())
    )
    selected["measurements"] = apply_quality_transitions_closure(ryuiki_conn, selected["measurements"])
    for table in coverage.get("wholesale_ryuiki_tables", []):
        selected[table] = set(select_wholesale_rowids(ryuiki_conn, table))

    doc_ids = coverage["document_closure"]["doc_ids"]
    if len(doc_ids) < coverage["document_closure"]["min_documents"]:
        raise SystemExit("document_closure.doc_ids が min_documents に足りない")
    cells_selected: dict[str, list[int]] = {"cells": select_cells_rowids(cells_conn, doc_ids)}
    for table in coverage.get("wholesale_cells_tables", []):
        cells_selected[table] = select_wholesale_rowids(cells_conn, table)

    # --- テキストの書き出し ---
    ryuiki_tables = sorted(selected)
    _write_schema_sql(ryuiki_conn, ryuiki_tables, out_dir / "ryuiki_schema.sql")
    row_counts: dict[str, int] = {}
    for table in ryuiki_tables:
        rowids = sorted(selected[table])
        row_counts[table] = _write_table_sql(ryuiki_conn, table, rowids, out_dir / "ryuiki" / f"{table}.sql")

    cells_tables = sorted(cells_selected)
    _write_schema_sql(cells_conn, cells_tables, out_dir / "cells_schema.sql")
    for table in cells_tables:
        rowids = sorted(cells_selected[table])
        row_counts[f"cells.{table}"] = _write_table_sql(cells_conn, table, rowids, out_dir / "cells" / f"{table}.sql")

    processed_dir = pathlib.Path(args.processed_dir)
    processed_out = out_dir / "processed"
    processed_out.mkdir(parents=True, exist_ok=True)
    for name in coverage.get("wholesale_processed_files", []):
        shutil.copyfile(processed_dir / name, processed_out / name)

    # --- declaration_counts.yaml ---
    geojson_path = pathlib.Path(args.processed_dir) / "nlni_w12_watersheds.geojson"
    landuse_csv_path = pathlib.Path(args.processed_dir) / "nlni_l03b_landuse_by_watershed.csv"
    counts = build_declaration_counts(ryuiki_conn, selected, geojson_path, landuse_csv_path)
    (out_dir / "declaration_counts.yaml").write_text(_dump_declaration_counts_yaml(counts), encoding="utf-8")

    # --- manifest.json ---
    # source_files のキーの形（"data/db/ryuiki.sqlite" 等）は pipeline_inputs.py
    # が一元管理する（scripts/b00_run_full_gate.py の source_hashes() と同じ
    # 関数・同じ定数を使うことで、キーの形が2箇所で食い違う事故を防ぐ。
    # レビュー指摘: 以前はこのスクリプトが独自に "ryuiki.sqlite"/"processed/<name>"
    # という別のキー形式を使っており、CI の full-gate-proof-check が
    # KeyError で落ちる不具合になっていた）。
    source_hashes = pipeline_inputs.compute_source_hashes(args.ryuiki_db, args.cells_db, args.processed_dir)
    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "scripts/s01_build_sample.py",
        "source_files": source_hashes,
        "row_counts": dict(sorted(row_counts.items())),
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8"
    )

    ryuiki_conn.close()
    cells_conn.close()

    print(f"→ {out_dir}")
    for table, n in sorted(row_counts.items()):
        print(f"  {table}: {n:,}行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
