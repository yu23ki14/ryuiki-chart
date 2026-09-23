#!/usr/bin/env python3
"""`occurrence`（L2、`data/db/v2.sqlite`、b06 が作った823,692行）の座標を、流域
ポリゴン（`data/processed/nlni_w12_watersheds.geojson`、国土数値情報 W12
1977年版、377面）へ点内包判定で直接解決し、記録×place のサテライト表
`occurrence_place` を作る（ADR-0016 Phase B「ファクトとキューブ」O-2a。
ADR-0006 規約2の改定・ADR-0026）。

    .venv/bin/python3 scripts/b09_build_occurrence_place.py

`data/db/v2.sqlite` の `occurrence_place` テーブルだけを作り直す
（`scripts/migrate/common.staged_table`。`occurrence`/`occurrence_agg` と同居。
**入力（`occurrence`・`registry.sqlite`・`ryuiki.sqlite`・GeoJSON）は読み取り
専用でしか開かない**）。

実行順は **b06 → b09 → b07 → b08**（このスクリプトは b06 の出力
〔`occurrence`〕だけに依存し、b07/b08 に依存されない——O-2b でキューブに
`place_kind='watershed'` のセルを足すときに `occurrence_place` を読む計画）。

## D1: `occurrence_place`（ADR-0026）

    occurrence_place(record_id, place_kind, place_id NULL可, method, built_from, spec_version)
    UNIQUE (record_id, place_kind)

母集団は**座標のある全記録**（`occurrence.lat IS NOT NULL AND lon IS NOT NULL`。
日付の無い記録も含む——ADR-0007 原則1）。実測では `occurrence` 823,692行全件に
座標があるため、全件が対象になる（座標の無い記録は将来そうなっても行を
持たないだけで、ここでは異常として扱わない）。

**解決規則**: 点が入るポリゴンがちょうど1つ → 解決（そのポリゴンに対応する
watershed の `place_id`）。0 → `place_id=NULL` の行（座標はあるがどの流域にも
入らない）。**2つ以上、または浮動小数点で判定が際どい（境界上）→ 止める**
（推測で割り当てない）。`coordinate_uncertainty_m` は解決の条件にしない
（F4・ADR-0006 規約4の改定と同じ判断）。

`method='point_in_polygon:even_odd'`、`built_from` はポリゴン版の指紋
（`f"occurrence+nlni_w12_watersheds.geojson@sha256:{digest16}"`。`digest16` は
GeoJSON バイト列の sha256 先頭16桁）。

## PIP: 純 Python（`scripts/migrate/point_in_polygon.py`）

`web/scripts/build-geo.mjs:112-165` の移植。0.02度 bbox グリッドで候補を絞り込み、
外環の even-odd 判定→穴、MultiPolygon 対応。shapely は使わない（実測: distinct
座標224,282件で GEOS と不一致0、約9秒）。**v1 と違って 0.001度メモ化はしない**
——ここで作るのは「正確な」解決。v1 のメモ化の癖の再現は射影側
（`scripts/b08_project_occurrence_v1.py`）の責務（ADR-0024/0025 と同じ「v1 の
癖はキューブ/レジストリに焼き込まない」原則）。

`occurrence`（823,692行）のうち distinct な `(lat, lon)` だけを PIP にかけ
（実測224,282組）、結果を record 単位に配り直す——同じ座標を持つ記録は
必ず同じ判定になるため、これは近似ではなく厳密な最適化（v1 の 0.001度
メモ化〔丸めてから代表だけ判定する近似〕とは異なる）。

## 機械検証（1つでも失敗すれば `common.MigrationError` で止まる）

1. **GeoJSON の `watershed_id` の集合**が、registry の
   `place_source_ref(source_id='watershed_meta.watershed_id')` の
   `external_key` 集合と一致する（実測377=377）。食い違えば、レジストリと
   GeoJSON の版がずれている可能性があるため止まる。
2. **浮動小数点の曖昧さ**（ADR-0026）: even-odd の交差判定で
   `abs(x - x_cross) < 1e-9` になった distinct 座標は、`fractions.Fraction` で
   厳密に再判定する。float 版の一致ポリゴン集合と厳密版の一致ポリゴン集合が
   1件でも食い違えば止まる（実測: 際どい交差自体が0件）。
3. **解決規則**: 一致ポリゴンが2つ以上の distinct 座標が1件でもあれば止まる
   （宣言値ではなく無条件の停止条件。実測0件）。
4. **宣言**（`scripts/migrate/occurrence_place_declarations.yaml`）:
   ポリゴン数（377）・`place_id` が NULL になった記録数（86,285）・解決した
   記録数（737,407）を実測件数と突き合わせる。式の検算
   （823,692 − 86,285 = 737,407）も行う。
5. **記録×place の一意性**: 座標のある全記録にちょうど1行
   （`UNIQUE(record_id, place_kind)`、行数 = 座標あり行数）。
6. **P-1a が入れた site→watershed の辺との突き合わせ**: `sites`（座標を持つ
   352地点）に対して同じ PIP 関数を直接実行し、結果が `sites.watershed` 列
   （`scripts/m01_sites.py:110-128` が shapely の `contains`/`intersects` で
   機械的に決定した値。P-1a の `place_relation` の地点→流域の辺278件の元に
   なった値）と一致することを確認する。食い違えば止まる。
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common, period, point_in_polygon as pip  # noqa: E402

DEFAULT_V2_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_GEOJSON = ROOT / "data" / "processed" / "nlni_w12_watersheds.geojson"
DEFAULT_DECLARATIONS_YAML = ROOT / "scripts" / "migrate" / "occurrence_place_declarations.yaml"

PLACE_KIND = "watershed"
METHOD = "point_in_polygon:even_odd"
WATERSHED_SOURCE_ID = "watershed_meta.watershed_id"

_SAMPLE_LIMIT = 20

REQUIRED_DECLARATION_KEYS = ("expected_row_count", "note")
_DECLARATION_NAMES = (
    "n_watershed_polygons",
    "place_id_null_count",
    "resolved_count",
)

_CREATE_OCCURRENCE_PLACE_SQL = """
CREATE TABLE {table} (
  record_id     TEXT NOT NULL,
  place_kind    TEXT NOT NULL,
  place_id      TEXT,
  method        TEXT NOT NULL,
  built_from    TEXT NOT NULL,
  spec_version  TEXT NOT NULL
)
"""
_CREATE_OCCURRENCE_PLACE_INDEX_SQL = (
    "CREATE UNIQUE INDEX occurrence_place_record_kind ON {table} (record_id, place_kind)"
)
_DROP_OCCURRENCE_PLACE_INDEX_SQL = "DROP INDEX IF EXISTS occurrence_place_record_kind"

_INSERT_SQL = """
INSERT INTO {table} (record_id, place_kind, place_id, method, built_from, spec_version)
VALUES (?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# 宣言 YAML（occurrence_cube_declarations.yaml と同じ流儀）
# ---------------------------------------------------------------------------

def load_and_validate_place_declarations(path=DEFAULT_DECLARATIONS_YAML) -> dict:
    """`occurrence_place_declarations.yaml` を読み、構造を検証してから返す。

    宣言された名前の集合が `_DECLARATION_NAMES` と過不足なく一致することも
    確認する（`scripts/b07_build_occurrence_cube.py` の
    `load_and_validate_cube_declarations()` と同じ流儀）。
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
    expected_names = frozenset(_DECLARATION_NAMES)
    if declared_names != expected_names:
        raise common.MigrationError(
            f"{path} の宣言名が想定と一致しない（期待: {sorted(expected_names)}、"
            f"実際: {sorted(declared_names)}）"
        )
    return raw


def validate_place_declarations_shape(path=DEFAULT_DECLARATIONS_YAML) -> None:
    """CI 用: 構造検証だけを行う（原本DBを必要としない）。"""
    load_and_validate_place_declarations(path)


# ---------------------------------------------------------------------------
# built_from（ポリゴン版の指紋）
# ---------------------------------------------------------------------------

def _built_from(geojson_path) -> str:
    digest = hashlib.sha256(pathlib.Path(geojson_path).read_bytes()).hexdigest()
    return f"occurrence+nlni_w12_watersheds.geojson@sha256:{digest[:16]}"


# ---------------------------------------------------------------------------
# 検証1: GeoJSON の watershed_id 集合 == registry の watershed external_key 集合
# ---------------------------------------------------------------------------

def _assert_polygon_set_matches_registry(polys: list[pip.Polygon], reg_conn: sqlite3.Connection) -> None:
    geojson_ids = {p.id for p in polys}
    registry_ids = {
        row[0]
        for row in reg_conn.execute(
            "SELECT external_key FROM reg.place_source_ref WHERE source_id = ?", (WATERSHED_SOURCE_ID,)
        )
    }
    if geojson_ids != registry_ids:
        only_geojson = sorted(geojson_ids - registry_ids)[:_SAMPLE_LIMIT]
        only_registry = sorted(registry_ids - geojson_ids)[:_SAMPLE_LIMIT]
        raise common.MigrationError(
            "occurrence_place: GeoJSON の watershed_id 集合と registry の "
            f"place_source_ref(source_id={WATERSHED_SOURCE_ID!r}) の external_key 集合が"
            f"食い違う（GeoJSON にしか無い: {only_geojson} / registry にしか無い: {only_registry}）。"
            "registry.sqlite と data/processed/nlni_w12_watersheds.geojson の版がずれている"
            "可能性がある。"
        )


# ---------------------------------------------------------------------------
# PIP 本体: distinct 座標を解決する
# ---------------------------------------------------------------------------

def _resolve_distinct_coordinates(
    coords: list[tuple[float, float]],
    polys: list[pip.Polygon],
    grid: pip.Grid,
) -> tuple[dict[tuple[float, float], list[str]], list[tuple[float, float]]]:
    """各座標の一致ポリゴン id 列を返す。`near_coords` は際どい交差があった
    座標のリスト（検証2の対象）。
    """
    matches: dict[tuple[float, float], list[str]] = {}
    near_coords: list[tuple[float, float]] = []
    for lat, lon in coords:
        matched, near = pip.locate(lon, lat, polys, grid)
        matches[(lat, lon)] = matched
        if near:
            near_coords.append((lat, lon))
    return matches, near_coords


def _assert_no_float_exact_mismatch(
    near_coords: list[tuple[float, float]],
    matches: dict[tuple[float, float], list[str]],
    polys: list[pip.Polygon],
    grid: pip.Grid,
) -> int:
    """検証2: 際どい交差があった座標を `Fraction` で厳密に再判定し、float 版と
    一致ポリゴン集合が食い違えば止める。戻り値は再判定した座標数（レポート用）。
    """
    mismatches = []
    for lat, lon in near_coords:
        exact = sorted(pip.locate_exact(lon, lat, polys, grid))
        if exact != sorted(matches[(lat, lon)]):
            mismatches.append((lat, lon, matches[(lat, lon)], exact))
    if mismatches:
        raise common.MigrationError(
            "occurrence_place: 際どい交差（|x-x_cross|<1e-9）があった座標のうち、float版と"
            f"Fraction厳密版で一致ポリゴンが食い違うものが{len(mismatches)}件ある"
            f"（例（上限{_SAMPLE_LIMIT}件、(lat, lon, float版, 厳密版)）: "
            f"{mismatches[:_SAMPLE_LIMIT]}）。even-odd 判定の実装を確認すること。"
        )
    return len(near_coords)


def _assert_no_multi_match(matches: dict[tuple[float, float], list[str]]) -> None:
    """検証3: 一致ポリゴンが2つ以上の distinct 座標が1件でもあれば止める
    （宣言値ではなく無条件の停止条件）。
    """
    multi = [(lat, lon, ids) for (lat, lon), ids in matches.items() if len(ids) >= 2]
    if multi:
        raise common.MigrationError(
            f"occurrence_place: 2つ以上の流域ポリゴンに一致した座標が{len(multi)}件ある"
            f"（例（上限{_SAMPLE_LIMIT}件、(lat, lon, 一致watershed_id列)）: "
            f"{multi[:_SAMPLE_LIMIT]}）。推測で1つに絞らず止める（ADR-0026）。"
        )


# ---------------------------------------------------------------------------
# 検証6: sites（P-1a の site→watershed 辺の元）との突き合わせ
# ---------------------------------------------------------------------------

def _assert_matches_site_watershed_edges(
    ryuiki_conn: sqlite3.Connection, polys: list[pip.Polygon], grid: pip.Grid
) -> int:
    """`sites`（座標を持つ全地点）に同じ PIP 関数を直接実行し、
    `sites.watershed`（`scripts/m01_sites.py` が shapely で決定した値。
    P-1a の地点→流域の `place_relation` の辺の元になった値）と一致することを
    確認する。戻り値は突き合わせた地点数（レポート用）。
    """
    rows = ryuiki_conn.execute("SELECT site_id, lat, lon, watershed FROM ryuiki.sites").fetchall()
    checked = 0
    mismatches = []
    for site_id, lat, lon, watershed in rows:
        if lat is None or lon is None:
            continue
        checked += 1
        matched, _near = pip.locate(lon, lat, polys, grid)
        ours = matched[0] if len(matched) == 1 else (None if len(matched) == 0 else "AMBIGUOUS")
        if ours != watershed:
            mismatches.append((site_id, lat, lon, watershed, ours))
    if mismatches:
        raise common.MigrationError(
            "occurrence_place: sites.watershed（P-1a の地点→流域の辺の元、"
            "scripts/m01_sites.py の shapely 判定）と、このモジュールの PIP が"
            f"食い違う地点が{len(mismatches)}件ある（例（上限{_SAMPLE_LIMIT}件、"
            f"(site_id, lat, lon, sites.watershed, このPIPの結果)）: "
            f"{mismatches[:_SAMPLE_LIMIT]}）。"
        )
    return checked


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

def build_and_write_occurrence_place(
    v2_db,
    ryuiki_db,
    registry_db,
    geojson_path=DEFAULT_GEOJSON,
    declarations_yaml=DEFAULT_DECLARATIONS_YAML,
) -> dict:
    """`v2_db`（`occurrence` を持つ、読み書き可能な v2.sqlite）に
    `occurrence_place` を作る。`occurrence` を変更する SQL は一切実行しない
    （`SELECT` のみ）。戻り値はレポート用の統計。
    """
    declarations = load_and_validate_place_declarations(declarations_yaml)

    polys = pip.load_polygons(geojson_path)
    grid = pip.build_grid(polys)
    built_from = _built_from(geojson_path)

    n_polygons_expected = declarations["n_watershed_polygons"]["expected_row_count"]
    if len(polys) != n_polygons_expected:
        raise common.MigrationError(
            f"occurrence_place: GeoJSON のポリゴン数（{len(polys)}）が宣言"
            f"（{declarations_yaml} の n_watershed_polygons.expected_row_count="
            f"{n_polygons_expected}）と食い違う。"
        )

    conn = sqlite3.connect(f"file:{v2_db}", uri=True)
    try:
        common.attach_readonly(conn, registry_db, "reg")
        common.attach_readonly(conn, ryuiki_db, "ryuiki")

        _assert_polygon_set_matches_registry(polys, conn)
        watershed_place_id = {
            external_key: place_id
            for place_id, external_key in conn.execute(
                "SELECT place_id, external_key FROM reg.place_source_ref WHERE source_id = ?",
                (WATERSHED_SOURCE_ID,),
            )
        }

        coords = [
            (lat, lon)
            for lat, lon in conn.execute(
                "SELECT DISTINCT lat, lon FROM occurrence WHERE lat IS NOT NULL AND lon IS NOT NULL"
            )
        ]
        matches, near_coords = _resolve_distinct_coordinates(coords, polys, grid)
        n_near_checked = _assert_no_float_exact_mismatch(near_coords, matches, polys, grid)
        _assert_no_multi_match(matches)

        coord_place_id: dict[tuple[float, float], str | None] = {}
        for key, ids in matches.items():
            coord_place_id[key] = watershed_place_id[ids[0]] if len(ids) == 1 else None

        n_checked_sites = _assert_matches_site_watershed_edges(conn, polys, grid)

        with common.staged_table(conn, "occurrence_place", _CREATE_OCCURRENCE_PLACE_SQL) as staging:
            def rows():
                for record_id, lat, lon in conn.execute(
                    "SELECT record_id, lat, lon FROM occurrence "
                    "WHERE lat IS NOT NULL AND lon IS NOT NULL"
                ):
                    place_id = coord_place_id[(lat, lon)]
                    yield (record_id, PLACE_KIND, place_id, METHOD, built_from, common.SPEC_VERSION)

            conn.executemany(_INSERT_SQL.format(table=f'"{staging}"'), rows())
            conn.execute(_CREATE_OCCURRENCE_PLACE_INDEX_SQL.format(table=f'"{staging}"'))
            conn.execute(_DROP_OCCURRENCE_PLACE_INDEX_SQL)

            n_total, n_null, n_resolved = conn.execute(
                f"""
                SELECT COUNT(*), SUM(CASE WHEN place_id IS NULL THEN 1 ELSE 0 END),
                       SUM(CASE WHEN place_id IS NOT NULL THEN 1 ELSE 0 END)
                FROM "{staging}"
                """
            ).fetchone()

            n_with_coords = conn.execute(
                "SELECT COUNT(*) FROM occurrence WHERE lat IS NOT NULL AND lon IS NOT NULL"
            ).fetchone()[0]
            if n_total != n_with_coords:
                raise common.MigrationError(
                    f"occurrence_place: 行数（{n_total}）が occurrence の座標あり行数"
                    f"（{n_with_coords}）と一致しない（UNIQUE(record_id, place_kind) は"
                    "満たしているはずなので、座標のある記録の一部が取りこぼされている"
                    "可能性がある）。"
                )

            expected_null = declarations["place_id_null_count"]["expected_row_count"]
            expected_resolved = declarations["resolved_count"]["expected_row_count"]
            if n_null != expected_null or n_resolved != expected_resolved:
                raise common.MigrationError(
                    "occurrence_place: 実測件数が宣言と食い違う"
                    f"（place_id NULL: 宣言{expected_null:,} / 実測{n_null:,}、"
                    f"解決: 宣言{expected_resolved:,} / 実測{n_resolved:,}）。"
                    f"{declarations_yaml} を確認すること。"
                )
            if n_null + n_resolved != n_with_coords:
                raise common.MigrationError(
                    f"occurrence_place: 検算に失敗（NULL {n_null:,} + 解決 {n_resolved:,} != "
                    f"座標あり行数 {n_with_coords:,}）。"
                )
            # ここまで来たら with ブロックを正常に抜け、staged_table が本番名に差し替える。
    except BaseException:
        conn.close()
        raise
    conn.close()

    return {
        "n_polygons": len(polys),
        "n_total": n_total,
        "n_null": n_null,
        "n_resolved": n_resolved,
        "n_distinct_coords": len(coords),
        "n_near_checked": n_near_checked,
        "n_checked_sites": n_checked_sites,
        "built_from": built_from,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v2-db", default=str(DEFAULT_V2_DB), help="occurrence を持つ v2.sqlite（読み書き）")
    parser.add_argument("--ryuiki-db", default=str(DEFAULT_RYUIKI_DB))
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--geojson", default=str(DEFAULT_GEOJSON))
    parser.add_argument("--declarations-yaml", default=str(DEFAULT_DECLARATIONS_YAML))
    args = parser.parse_args()

    db_path = pathlib.Path(args.v2_db)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b06_build_occurrence.py` を実行すること。"
        )

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み書き可能で開く（occurrence は変更しない）: {db_path}")
    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")
    print(f"▶ 読み取り専用で開く: {args.geojson}")

    with common.timed_step("occurrence_place を構築") as info:
        stats = build_and_write_occurrence_place(
            args.v2_db, args.ryuiki_db, registry_db, args.geojson, args.declarations_yaml
        )
        info["n"] = stats["n_total"]

    print(
        f"  ポリゴン数={stats['n_polygons']} / distinct座標={stats['n_distinct_coords']:,} / "
        f"際どい交差の再判定={stats['n_near_checked']} / sites突合={stats['n_checked_sites']} / "
        f"解決={stats['n_resolved']:,} / NULL={stats['n_null']:,} / built_from={stats['built_from']}"
    )


if __name__ == "__main__":
    main()
