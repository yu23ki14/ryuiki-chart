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

## D1: `occurrence_place`

    occurrence_place(record_id, place_kind, place_id NULL可, method, built_from, spec_version)
    UNIQUE (record_id, place_kind)

母集団・解決規則・PIP の実装（`scripts/migrate/point_in_polygon.py`。v1 と
違い 0.001度メモ化はしない）の詳細は ADR-0026 D1・実測節参照。ここでは
要点だけ: 座標のある全記録が対象（ADR-0007 原則1）、点が入るポリゴンが
ちょうど1つなら解決・0なら `place_id=NULL`・2つ以上または境界上なら
無条件に止める（推測で割り当てない）。`coordinate_uncertainty_m` は解決の
条件にしない。

## 機械検証（1つでも失敗すれば `common.MigrationError` で止まる）

各項目の実測値は ADR-0026 実測節・`docs/plans/PHASE_B_OCCURRENCE.md` §15
参照（すべて期待どおりだったことのみここに記す）。

1. GeoJSON の `watershed_id` 集合と registry の
   `place_source_ref(source_id='watershed_meta.watershed_id')` の
   `external_key` 集合が一致すること・`external_key` 自体が一意であること。
2. **境界上の点**（ADR-0026 D1）: 際どい座標（点から辺までの距離が
   1e-9度未満）のうち、`fractions.Fraction` で実際に辺〔頂点上を含む〕に
   厳密に乗っているものが無いこと（無条件の停止条件）。
3. **浮動小数点の曖昧さ**: 2 で境界上ではなかった際どい座標は、
   `locate_exact()`（フルの厳密判定）が float 版と一致すること。
4. **解決規則**: 一致ポリゴンが2つ以上の distinct 座標が無いこと（宣言値では
   なく無条件の停止条件）。
5. **宣言**（`scripts/migrate/occurrence_place_declarations.yaml`）:
   ポリゴン数・`place_id` NULL の記録数・解決した記録数が実測と一致すること
   （式の検算も行う）。
6. **記録×place の一意性**: `UNIQUE(record_id, place_kind)`
   （`scripts/migrate/common.assert_dimension_key_unique` で検証）。
7. **P-1a が入れた site→watershed の辺との突き合わせ**: `sites`（座標を持つ
   全地点）に同じ PIP 関数を直接実行し、`sites.watershed` 列
   （`scripts/m01_sites.py:110-128` が shapely で機械的に決定した値）と
   一致すること。
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
# `occurrence_place` の唯一の消費者（scripts/tests/occurrence_fixtures.py の
# フィクスチャ・scripts/b08_project_occurrence_v1.py の一時テーブル作成）は
# この DDL 文字列をそのまま import して使うこと（コードレビュー指摘13:
# DDL を複数箇所に手書きで複製しない）。
_DIM_COLUMNS = ["record_id", "place_kind"]
_DIM_KEY_INDEX_NAME = "occurrence_place_dim_key"

_INSERT_SQL = """
INSERT INTO {table} (record_id, place_kind, place_id, method, built_from, spec_version)
VALUES (?, ?, ?, ?, ?, ?)
"""


# ---------------------------------------------------------------------------
# 宣言 YAML（occurrence_cube_declarations.yaml と同じ流儀）
# ---------------------------------------------------------------------------

def load_and_validate_place_declarations(path=DEFAULT_DECLARATIONS_YAML, count_overlay=None) -> dict:
    """`occurrence_place_declarations.yaml` を読み、構造を検証してから返す。

    宣言された名前の集合が `_DECLARATION_NAMES` と過不足なく一致することも
    確認する（`scripts/b07_build_occurrence_cube.py` の
    `load_and_validate_cube_declarations()` と同じ流儀）。

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

def _assert_watershed_external_key_unique(conn: sqlite3.Connection) -> None:
    """`place_source_ref(source_id='watershed_meta.watershed_id')` の
    `external_key` が一意であることを確認する（コードレビュー指摘5）。
    重複があると、`external_key -> place_id` の辞書内包表記が後勝ちで
    黙って別の place に束ねてしまう——`place_mesh_lookup`
    （`scripts/b08_project_occurrence_v1.py`）と同型の検証。
    """
    common.raise_on_group_by_duplicates(
        conn,
        "SELECT external_key, COUNT(*) AS c FROM reg.place_source_ref "
        "WHERE source_id = ? GROUP BY external_key HAVING c > 1 LIMIT 5",
        (WATERSHED_SOURCE_ID,),
        lambda dup: (
            "occurrence_place: place_source_ref"
            f"（source_id={WATERSHED_SOURCE_ID!r}）の external_key が一意でない"
            f"（同じ watershed_id に複数の place_id が対応している。例: {dup}）。"
            "watershed_id -> place_id の辞書を一意に構築できない。"
        ),
    )


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


def _assert_no_boundary_points(
    near_coords: list[tuple[float, float]],
    polys: list[pip.Polygon],
    grid: pip.Grid,
) -> int:
    """検証2（ADR-0026 D1「境界上なら止める」。コードレビュー指摘1）: 際どい
    座標（点から辺までの距離が1e-9度未満）のうち、`fractions.Fraction` の
    厳密演算で実際に候補ポリゴンの辺（頂点上を含む）に乗っている座標が
    1件でもあれば止める——2つ以上に一致する座標と同じく、無条件の停止条件
    （推測で割り当てない）。戻り値は判定した座標数（レポート用）。
    """
    boundary = [
        (lat, lon) for lat, lon in near_coords if pip.on_boundary(lon, lat, polys, grid)
    ]
    if boundary:
        raise common.MigrationError(
            "occurrence_place: 流域ポリゴンの境界（頂点・辺上を含む）に厳密に乗っている"
            f"座標が{len(boundary)}件ある（例（上限{_SAMPLE_LIMIT}件、(lat, lon)）: "
            f"{boundary[:_SAMPLE_LIMIT]}）。推測で割り当てず止める（ADR-0026 D1）。"
        )
    return len(near_coords)


def _assert_no_float_exact_mismatch(
    near_coords: list[tuple[float, float]],
    matches: dict[tuple[float, float], list[str]],
    polys: list[pip.Polygon],
    grid: pip.Grid,
) -> int:
    """検証3: 際どい座標（境界上ではないと検証2で確認済み）を `Fraction` で
    フルに厳密再判定し、float 版と一致ポリゴン集合が食い違えば止める。
    戻り値は再判定した座標数（レポート用）。
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
    """検証4: 一致ポリゴンが2つ以上の distinct 座標が1件でもあれば止める
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
# 検証7: sites（P-1a の site→watershed 辺の元）との突き合わせ
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
    count_overlay: dict[str, int] | None = None,
) -> dict:
    """`v2_db`（`occurrence` を持つ、読み書き可能な v2.sqlite）に
    `occurrence_place` を作る。`occurrence` を変更する SQL は一切実行しない
    （`SELECT` のみ）。戻り値はレポート用の統計。

    `count_overlay`（既定 None）は Issue #29「縮小サンプル」用（`expected_row_count`
    だけを差し替える）。
    """
    declarations = load_and_validate_place_declarations(declarations_yaml, count_overlay=count_overlay)

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
        # ATTACH 直後に表の有無を確認する（/simplify 指摘8: 無いまま SELECT
        # すると生の OperationalError になる。scripts/b11_project_place_v1.py の
        # `_validate_registry` と同じ流儀）。
        common.assert_attached_table_exists(
            conn, "reg", "place_source_ref",
            hint="scripts/r01_build_registry.py で registry.sqlite を作り直すこと。",
        )
        common.assert_attached_table_exists(
            conn, "ryuiki", "sites",
            hint="ryuiki.sqlite（原本）が壊れている、または版が古い可能性がある。",
        )
        # 段階間の指紋（Issue #37 #1）: b06 が最後に記録した occurrence の指紋と
        # 今の occurrence の内容が一致することを、座標を読む前に確認する。
        # 戻り値は occurrence_place の系譜に使う。
        occurrence_fingerprint = common.assert_occurrence_fingerprint_fresh(conn)

        _assert_polygon_set_matches_registry(polys, conn)
        _assert_watershed_external_key_unique(conn)
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
        _assert_no_boundary_points(near_coords, polys, grid)
        n_near_checked = _assert_no_float_exact_mismatch(near_coords, matches, polys, grid)
        _assert_no_multi_match(matches)

        coord_place_id: dict[tuple[float, float], str | None] = {}
        for key, ids in matches.items():
            coord_place_id[key] = watershed_place_id[ids[0]] if len(ids) == 1 else None

        n_checked_sites = _assert_matches_site_watershed_edges(conn, polys, grid)

        with common.staged_table(
            conn, "occurrence_place", _CREATE_OCCURRENCE_PLACE_SQL,
            fingerprint_inputs={"occurrence": occurrence_fingerprint},
            fingerprint_spec_version=common.OCCURRENCE_SPEC_VERSION,
        ) as staging:
            def rows():
                for record_id, lat, lon in conn.execute(
                    "SELECT record_id, lat, lon FROM occurrence "
                    "WHERE lat IS NOT NULL AND lon IS NOT NULL"
                ):
                    place_id = coord_place_id[(lat, lon)]
                    yield (record_id, PLACE_KIND, place_id, METHOD, built_from, common.OCCURRENCE_SPEC_VERSION)

            conn.executemany(_INSERT_SQL.format(table=f'"{staging}"'), rows())
            # 検証6: UNIQUE(record_id, place_kind)（コードレビュー指摘10:
            # 手書きの CREATE UNIQUE INDEX/DROP INDEX ではなく共通ヘルパを使う
            # ——重複時に生の IntegrityError ではなく、どの行かを示す
            # MigrationError になる）。
            common.assert_dimension_key_unique(
                conn, staging, _DIM_COLUMNS,
                index_name=_DIM_KEY_INDEX_NAME,
                table_label="occurrence_place",
                cause_hint="occurrence の座標あり記録が record_id について重複している可能性がある。",
            )

            n_total, n_null, n_resolved = conn.execute(
                f"""
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN place_id IS NULL THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN place_id IS NOT NULL THEN 1 ELSE 0 END), 0)
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
            # ここまで来たら with ブロックを正常に抜け、staged_table が本番名に
            # 差し替え、同じトランザクションで指紋・系譜（消費した occurrence
            # の指紋）も記録する（Issue #37 #1・/code-review 指摘の根本対応）。
            # b08 はこの指紋を見て「今の occurrence から作った occurrence_place
            # か」を検証する。
        # v2 パイプラインの入力＋コードの指紋（Issue #48 PR-0 /simplify 指摘1）:
        # `common.record_v2_input_fingerprint` の docstring 参照（b03/b06 も同じ
        # 全体像の辞書を同じ v2.sqlite に upsert する——3段のどれが最後に走っても
        # 同じ内容になる、`pipeline_fingerprint.inputs` の系譜とは別の表）。
        common.record_v2_input_fingerprint(
            conn, common.compute_v2_input_fingerprint(ryuiki_db=ryuiki_db, registry_db=registry_db),
        )
        conn.commit()
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
    parser.add_argument(
        "--count-overlay", default=None,
        help="data/sample/declaration_counts.yaml のようなファイル。既定は使わない（Issue #29「縮小サンプル」）",
    )
    args = parser.parse_args()

    db_path = pathlib.Path(args.v2_db)
    # `--v2-db` を `sqlite3.connect` で直接開く（`fresh_sqlite` を経由しない）
    # ため、ここで個別に検査する（コードレビュー指摘4。b03/b04 と同じ流儀
    # ——`scripts/migrate/common.py` の `reject_protected_source_db` の
    # docstring 参照。原本〔ryuiki/cells/derived〕を誤って `--v2-db` に渡すと
    # 書き込みで壊す事故を防ぐ）。
    common.reject_protected_source_db(db_path)
    if not db_path.exists():
        sys.exit(
            f"{db_path} が無い。先に `.venv/bin/python3 scripts/b06_build_occurrence.py` を実行すること。"
        )

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み書き可能で開く（occurrence は変更しない）: {db_path}")
    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")
    print(f"▶ 読み取り専用で開く: {args.geojson}")

    count_overlay = period.resolve_count_overlay(args.count_overlay, "occurrence_place_declarations.yaml")

    with common.timed_step("occurrence_place を構築") as info:
        stats = build_and_write_occurrence_place(
            args.v2_db, args.ryuiki_db, registry_db, args.geojson, args.declarations_yaml,
            count_overlay=count_overlay,
        )
        info["n"] = stats["n_total"]

    print(
        f"  ポリゴン数={stats['n_polygons']} / distinct座標={stats['n_distinct_coords']:,} / "
        f"際どい交差の再判定={stats['n_near_checked']} / sites突合={stats['n_checked_sites']} / "
        f"解決={stats['n_resolved']:,} / NULL={stats['n_null']:,} / built_from={stats['built_from']}"
    )


if __name__ == "__main__":
    main()
