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
- **adapter 入力表の `taxon_id` が参照する taxon の原本の行**。registry の taxon は
  サンプルに入った `organism_records`/`taxa` からしか作られない（`scripts/registry/build_taxon.py`）ので、
  adapter 出典（マニフェストの非 builtin・target=occurrence）の入力表が `taxon_id` 列で
  registry の既存 taxon を指していると、その taxon を生む原本の行がサンプルに無い限り
  b06 の `in_registry[taxon]` が止まる。taxon_id から原本の行を逆引きし（gbif/inat 名前空間は
  `organism_records` の `taxon_key`、無ければ `taxa.gbif_taxon_key`、`ryuiki-taxa.` は `taxa` の
  未照合行）、taxon ごとに rowid 最小の 1 行を足す（`select_taxon_origin_rows`）。
  サンプルに既にその taxon を生む行があれば足さない。supplement 由来の ID は
  registry が supplement から作るので対象外。
- **adapter 入力表の座標が落ちる grid01 セルを生む `organism_records` の行**。grid01 の place は
  `organism_records` の座標（`FLOOR(lat*100)`, `FLOOR(lon*100)`）からしか作られない
  （`registry/build_place.py`）ので、adapter 入力表（`lat`/`lon` 列を持つもの）の座標が落ちるセルを
  サンプルの `organism_records` が持たないと、b06 が「座標はあるのに grid01 が解決できない」で止まる。
  サンプルに無いセルごとに、そのセルを生む原本の行を rowid 最小で 1 行足す
  （`select_grid01_origin_rows`。taxon の閉包の**後**に評価する）。原本にも無いセルがあれば止まる。
- **`registry/source/access.yaml` の `records`（record_set）を宣言した各（出典, 表）の行**。r01 の
  `build_source_access` は「宣言した record_set の表に、その出典の行が 1 つ以上ある」ことを検査する
  （無ければ止まる。宣言が古いのではなく、サンプルがその出典の行を持たないだけ）。表名・出典は
  access.yaml から導き（`record_sets` の表のうち原本 ryuiki.sqlite にあるもの。registry の表
  `taxon_assessment` は原本の表ではないので対象外）、サンプルにその出典の行がまだ無い（出典, 表）に、
  rowid 最小の 1 行を足す（`select_record_set_origin_rows`。複合 `a|b` の行も区切りの完全一致で拾う）。
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
import math
import pathlib
import shutil
import sqlite3
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pipeline_inputs  # noqa: E402
from ingest import manifest as manifest_lib  # noqa: E402
from migrate import occurrence_period  # noqa: E402
from migrate import point_in_polygon as pip  # noqa: E402
from migrate import source_regions  # noqa: E402
from reconcile.common import load_yaml  # noqa: E402
from registry import build_taxon, common as registry_common  # noqa: E402
from taxon_namespaces import TAXON_KEY_SOURCE_NAMESPACE  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_CELLS_DB = ROOT / "data" / "db" / "cells.sqlite"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "processed"
DEFAULT_COVERAGE_YAML = ROOT / "data" / "sample" / "coverage.yaml"
DEFAULT_OUT_DIR = ROOT / "data" / "sample"
DEFAULT_GEOJSON = ROOT / "data" / "processed" / "nlni_w12_watersheds.geojson"
ACCESS_YAML = ROOT / "registry" / "source" / "access.yaml"
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


# adapter 出典（マニフェストの非 builtin）の入力表・ファイルを全件サンプルに入れてよい上限（行数）。
# 入力表を絞り込む経路は無い（coverage.yaml の predicate は adapter の入力表には使えず、overlay も
# expected の place/cube 値には効かない）。だから全件を入れるしかなく、上限を超えると止まる。
# 大きい入力表を持つ出典は、マニフェストの任意キー sample_input_max_rows でその出典だけ上限を上げる
# （神奈川県 eDNA の edna_detections 約 1.3 万行など。2026-10-07 オーナー判断）。
ADAPTER_INPUT_WHOLESALE_MAX_ROWS = 5000


def adapter_inputs(manifests_dir=source_regions.DEFAULT_MANIFESTS_DIR) -> dict[str, manifest_lib.Manifest]:
    """サンプルに入力を入れる必要がある出典 = マニフェストの非 builtin（adapter 経由）。
    新出典を足してもこのスクリプトを触らずに済むよう、対象はマニフェストから導く。"""
    return {sid: m for sid, m in manifest_lib.load_manifests(manifests_dir).items() if not m.is_builtin}


def select_adapter_input_tables(
    conn: sqlite3.Connection, manifests: dict[str, manifest_lib.Manifest], selected: dict[str, set[int]],
) -> dict[str, set[int]]:
    """adapter 出典の入力表（`input.table`）を、小さければ全件サンプルに入れる。
    全件入れるので adapter の出力はサンプルでも原本と同じ件数（マニフェストの宣言値がそのまま合う）。
    すでに predicate で絞って選ばれた表・上限を超える表は、黙って部分的に入れず止める。"""
    out: dict[str, set[int]] = {}
    for sid, m in sorted(manifests.items()):
        table = m.input.get("table")
        if table is None or table in out:
            continue
        if table in selected:
            raise SystemExit(
                f"{sid}: input.table={table!r} は coverage.yaml の predicate で絞られている。adapter の入力は全件入れる"
                "（件数の宣言が合わなくなる）ので、predicate を外すこと"
            )
        n = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        limit = m.sample_input_max_rows or ADAPTER_INPUT_WHOLESALE_MAX_ROWS
        if n > limit:
            raise SystemExit(
                f"{sid}: input.table={table!r} が {n:,} 行ある（全件入れる上限 {limit:,}）。"
                "adapter の入力表を絞る経路は無い。マニフェストの sample_input_max_rows でこの出典の上限を上げること"
            )
        out[table] = set(select_wholesale_rowids(conn, table))
    return out


def _supplement_taxon_ids() -> set[str]:
    p = build_taxon.SUPPLEMENT_TAXA_CSV
    if not p.exists():
        return set()
    with open(p, newline="", encoding="utf-8") as f:
        return {r["taxon_id"] for r in csv.DictReader(f)}


def select_taxon_origin_rows(
    conn: sqlite3.Connection, manifests: dict[str, manifest_lib.Manifest], selected: dict[str, set[int]],
    supplement_ids: set[str] | None = None,
) -> dict[str, set[int]]:
    """adapter 入力表（target=occurrence の非 builtin の `input.table`）の `taxon_id` 列が指す taxon について、
    registry がその taxon_id を生むのに要る原本の行（`organism_records` か `taxa`）を、taxon ごとに
    rowid 最小の 1 行だけ返す（`{table: {rowid}}`。サンプルに既に生む行がある taxon は足さない）。
    引けない taxon_id（supplement 由来を除く）があれば止まる。出典名は書かず、マニフェストから導く。"""
    supplement_ids = _supplement_taxon_ids() if supplement_ids is None else supplement_ids
    needed: set[str] = set()
    for m in manifests.values():
        table = m.input.get("table")
        if table is None or m.target != "occurrence":
            continue
        if "taxon_id" not in {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}:
            continue
        needed |= {r[0] for r in conn.execute(f'SELECT DISTINCT taxon_id FROM "{table}" WHERE taxon_id IS NOT NULL')}
    needed -= supplement_ids
    if not needed:
        return {}

    sources_by_ns: dict[str, list[str]] = defaultdict(list)
    for src, ns in TAXON_KEY_SOURCE_NAMESPACE.items():
        sources_by_ns[ns].append(src)
    keys_by_ns: dict[str, dict[str, str]] = defaultdict(dict)       # ns -> {taxon_key: taxon_id}
    unresolved_ids: set[str] = set()
    for tid in sorted(needed):
        for ns in sources_by_ns:
            prefix = f"common:taxon:{ns}."
            if tid.startswith(prefix) and build_taxon._taxon_id_for(ns, tid[len(prefix):]) == tid:
                keys_by_ns[ns][tid[len(prefix):]] = tid
                break
        else:
            unresolved_ids.add(tid)

    out: dict[str, set[int]] = {"organism_records": set(), "taxa": set()}
    found: set[str] = set()
    selected_org = selected.get("organism_records", set())
    _create_rowid_temp_table(conn, "sel_org", selected_org)
    for ns, by_key in sorted(keys_by_ns.items()):
        conn.execute("DROP TABLE IF EXISTS temp.need_keys")
        conn.execute("CREATE TEMP TABLE need_keys (k TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO temp.need_keys VALUES (?)", [(k,) for k in sorted(by_key)])
        srcs = ",".join("?" for _ in sources_by_ns[ns])
        have = {r[0] for r in conn.execute(
            f"SELECT DISTINCT taxon_key FROM organism_records WHERE rowid IN (SELECT rowid_value FROM temp.sel_org) "
            f"AND source_id IN ({srcs}) AND taxon_key IN (SELECT k FROM temp.need_keys)", sources_by_ns[ns])}
        rows = conn.execute(
            f"SELECT taxon_key, MIN(rowid) FROM organism_records WHERE source_id IN ({srcs}) "
            f"AND taxon_key IN (SELECT k FROM temp.need_keys) GROUP BY taxon_key", sources_by_ns[ns]).fetchall()
        for key, rowid in rows:
            found.add(by_key[key])
            if key not in have:
                out["organism_records"].add(rowid)
        if ns == "gbif":                      # organism_records に無い gbif キーは taxa（EXACT）から
            rest = sorted(set(by_key) - {r[0] for r in rows})
            conn.execute("DELETE FROM temp.need_keys")
            conn.executemany("INSERT INTO temp.need_keys VALUES (?)", [(k,) for k in rest])
            for key, rowid in conn.execute(
                    "SELECT gbif_taxon_key, MIN(rowid) FROM taxa WHERE gbif_match_type='EXACT' "
                    "AND gbif_taxon_key IN (SELECT k FROM temp.need_keys) GROUP BY gbif_taxon_key"):
                found.add(by_key[key])
                out["taxa"].add(rowid)
    if any(t.startswith("common:taxon:ryuiki-taxa.") for t in unresolved_ids):
        seen: dict = {}
        for rowid, taxa_pk, key, match in conn.execute(
                "SELECT rowid, taxon_id, COALESCE(gbif_taxon_key,''), gbif_match_type FROM taxa ORDER BY rowid"):
            if key.strip() and match == "EXACT":
                continue
            tid = registry_common.taxon_id_unresolved(taxa_pk, seen=seen)
            if tid in unresolved_ids:
                found.add(tid)
                out["taxa"].add(rowid)
    missing = sorted(needed - found)
    if missing:
        raise SystemExit(f"adapter 入力表の taxon_id のうち、原本の organism_records/taxa から registry が生める行を"
                         f"引けないものが {len(missing)} 件ある（supplement にも無い）: {missing[:10]}")
    return {t: r for t, r in out.items() if r}


def grid01_cell(lat: float, lon: float) -> tuple[int, int]:
    """grid01 のセル（`registry/build_place.py`・`b06_build_occurrence.py` の `FLOOR(lat*100)`, `FLOOR(lon*100)` と同じ規則。
    両者は式をインラインで持ち共有関数が無いので、ここでも同じ式。食い違えば test_s01 のセル一致テストが落ちる）。"""
    return math.floor(lat * 100), math.floor(lon * 100)


def select_grid01_origin_rows(
    conn: sqlite3.Connection, manifests: dict[str, manifest_lib.Manifest], selected: dict[str, set[int]],
) -> dict[str, set[int]]:
    """adapter 入力表（target=occurrence の非 builtin・`lat`/`lon` 列あり）の座標が落ちる grid01 セルのうち、
    サンプルの `organism_records`（`selected`）にまだ無いセルを、そのセルを生む原本の行（rowid 最小）で足す。
    原本にもそのセルを生む行が無ければ止まる。"""
    need: set[tuple[int, int]] = set()
    for m in manifests.values():
        table = m.input.get("table")
        if table is None or m.target != "occurrence":
            continue
        cols = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        if not {"lat", "lon"} <= cols:
            continue
        need |= {grid01_cell(la, lo) for la, lo in conn.execute(
            f'SELECT DISTINCT lat, lon FROM "{table}" WHERE lat IS NOT NULL AND lon IS NOT NULL')}
    if not need:
        return {}
    _create_rowid_temp_table(conn, "sel_org_cells", selected.get("organism_records", set()))
    cell_sql = "CAST(FLOOR(lat*100) AS INT), CAST(FLOOR(lon*100) AS INT)"
    have = {tuple(r) for r in conn.execute(
        f"SELECT DISTINCT {cell_sql} FROM organism_records WHERE lat IS NOT NULL AND lon IS NOT NULL "
        "AND rowid IN (SELECT rowid_value FROM temp.sel_org_cells)")}
    origin = {(r[0], r[1]): r[2] for r in conn.execute(
        f"SELECT {cell_sql}, MIN(rowid) FROM organism_records WHERE lat IS NOT NULL AND lon IS NOT NULL "
        f"GROUP BY {cell_sql}")}
    missing = sorted(need - have)
    unresolvable = [c for c in missing if c not in origin]
    if unresolvable:
        raise SystemExit(f"adapter 入力表の座標が落ちる grid01 セルのうち、原本の organism_records にも無いものが "
                         f"{len(unresolvable)} 件ある: {unresolvable[:5]}")
    rows = {origin[c] for c in missing}
    return {"organism_records": rows} if rows else {}


def select_record_set_origin_rows(
    conn: sqlite3.Connection, access_doc: dict, selected: dict[str, set[int]],
) -> dict[str, set[int]]:
    """access.yaml の `records` で宣言された（出典, 表）ごとに、サンプルにその出典の行が無ければ、
    原本のその表のその出典の行を rowid 最小で 1 行足す（`{table: {rowid}}`）。出典の値は `a|b` の複合も
    区切りの完全一致で拾う。原本に表が無い（registry の表 `taxon_assessment` など）ものは対象外。
    原本にも行が無ければ止まる（r01 の検査と同じ宣言を、サンプルの側でも保証する）。"""
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    record_sets = access_doc.get("record_sets") or {}
    out: dict[str, set[int]] = {}
    for sid, entry in sorted((access_doc.get("sources") or {}).items()):
        for rs in entry.get("records") or []:
            table = record_sets[rs]
            if table not in existing:
                continue
            rowids = [r[0] for r in conn.execute(
                f'SELECT rowid FROM "{table}" WHERE instr(\'|\' || source_id || \'|\', \'|\' || ? || \'|\') > 0 '
                "ORDER BY rowid", (sid,))]
            if not rowids:
                raise SystemExit(f"access.yaml: {sid} の records {rs}（表 {table}）に、原本にもこの出典の行が無い")
            have = selected.get(table, set()) | out.get(table, set())
            if not have.intersection(rowids):
                out.setdefault(table, set()).add(rowids[0])
    return out


def adapter_input_files(manifests: dict[str, manifest_lib.Manifest]) -> list[str]:
    """adapter 出典の入力ファイル（`input.file`。`data/processed/` 配下のファイル名）。サンプルの processed/ に丸ごと写す。"""
    names: list[str] = []
    for sid, m in sorted(manifests.items()):
        f = m.input.get("file")
        if f is None:
            continue
        path = pathlib.PurePosixPath(f)
        if path.parent != pathlib.PurePosixPath("data/processed"):
            raise SystemExit(f"{sid}: input.file={f!r} は data/processed/ 直下のファイルでなければならない（サンプルに写せない）")
        names.append(path.name)
    return names


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
    # adapter 出典は入力を全件サンプルに入れる（select_adapter_input_tables）ので、取り込み件数は原本と同じ。
    # マニフェストの宣言値（expected_row_count）をそのまま持つ（キーはマニフェストから導く。新出典で s01 を触らない）。
    all_manifests = manifest_lib.load_manifests(manifests_dir)
    for sid, m in sorted(all_manifests.items()):
        if not m.is_builtin:
            out[f"manifests:{sid}"] = m.expected_row_count
    # 不在記録（occurrence_status='ABSENT'）として b06 が除く行数。内訳キーは Manifest.count_breakdown が決める
    # （source_regions.load_source_regions が出すキーと同じ。宣言を持つ出典だけ）。
    for sid, m in sorted(all_manifests.items()):
        if "absent_excluded_rows" in m.count_breakdown:
            out[f"manifests:{sid}.absent_excluded_rows"] = count(
                "organism_records", f"source_id = '{sid}' AND occurrence_status = 'ABSENT'"
            )

    # occurrence_period_shapes.yaml。形の名前は宣言ファイル（コードの
    # `_SHAPE_DEFS` と過不足なく一致することを `assert_declared_shapes_match_code`
    # が検証済み）からそのまま読む——手で列挙すると形が増えたときに追従し忘れる
    # 余地が生まれる。分類そのものは `classify_shape`（SQL 関数として
    # `_open_ro` が登録済み）を使う（以前の `length(observed_on) = N` は
    # 「12形の文字数がたまたま全部異なる」という前提の近似だった。
    # code-review 指摘対応。coverage.yaml も同じ関数に揃えてある）。
    for name in sorted(occurrence_period.load_period_shapes()):
        out[f"occurrence_period_shapes.yaml:{name}"] = count(
            "organism_records",
            f"classify_shape(observed_on) = '{name}' AND occurrence_status IS NOT 'ABSENT'"
        )

    # occurrence_cube_declarations.yaml
    org_rows = conn.execute(
        "SELECT t.rowid AS rowid, t.record_id, t.observed_on, t.lat, t.lon, t.scientific_name, "
        "t.is_alien, t.red_list_category, t.source_id "
        "FROM organism_records t JOIN temp.__s01_organism_records_rowids s ON t.rowid = s.rowid_value "
        "WHERE t.occurrence_status IS NOT 'ABSENT' "   # 不在記録は occurrence に入らない（b06）
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
    parser.add_argument("--manifests-dir", default=str(source_regions.DEFAULT_MANIFESTS_DIR))
    parser.add_argument("--access-yaml", default=str(ACCESS_YAML))
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
    # adapter 出典（マニフェストの非 builtin）の入力表は、coverage.yaml に書かなくてもマニフェストから導いて入れる
    manifests = adapter_inputs(args.manifests_dir)
    for table, rowids in select_adapter_input_tables(ryuiki_conn, manifests, selected).items():
        selected[table] = rowids
    # 入力表の taxon_id が指す既存 taxon を、registry が作れるように原本の行を足す
    for table, rowids in select_taxon_origin_rows(ryuiki_conn, manifests, selected).items():
        selected[table] = selected.get(table, set()) | rowids
    # 入力表の座標が落ちる grid01 セルを、サンプルの organism_records が持つようにする（taxon の閉包の後）
    for table, rowids in select_grid01_origin_rows(ryuiki_conn, manifests, selected).items():
        selected[table] = selected.get(table, set()) | rowids

    # access.yaml で records を宣言した（出典, 表）の行が、サンプルに 1 つ以上あるようにする
    for table, rowids in select_record_set_origin_rows(
            ryuiki_conn, load_yaml(args.access_yaml), selected).items():
        selected[table] = selected.get(table, set()) | rowids

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
    for name in [*coverage.get("wholesale_processed_files", []), *adapter_input_files(manifests)]:
        shutil.copyfile(processed_dir / name, processed_out / name)

    # --- declaration_counts.yaml ---
    geojson_path = pathlib.Path(args.processed_dir) / "nlni_w12_watersheds.geojson"
    landuse_csv_path = pathlib.Path(args.processed_dir) / "nlni_l03b_landuse_by_watershed.csv"
    counts = build_declaration_counts(ryuiki_conn, selected, geojson_path, landuse_csv_path, manifests_dir=args.manifests_dir)
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
