#!/usr/bin/env python3
"""`data/db/ryuiki.sqlite`（読み取り専用）の `organism_records`（823,692行）を、
生物の出現を表す単一のファクト `occurrence`（ADR-0007 決定3。observation とは
別のファクト）にする（ADR-0016 Phase B「ファクトとキューブ」O-1a。設計は
`docs/plans/PHASE_B_OCCURRENCE.md` §4「縦線の切り方」・O-1 設計 v2 D1）。

    .venv/bin/python3 scripts/b06_build_occurrence.py

`data/db/v2.sqlite` の `occurrence` テーブルだけを作り直す
（`scripts/migrate/common.staged_table`。`observation`/`observation_agg` と
同じファイルに同居する。b03/b04 と同じ理由で v2.sqlite をファイルごと
作り直さない）。`reports/phase_b_occurrence.md` に要約を書く。**入力
（`ryuiki.sqlite`/`registry.sqlite`）は読み取り専用でしか開かない。**

## このスクリプトが埋める列・埋めない列

`organism_records` は823,692行**全行**を対象にする（`observed_on` が NULL の
6,836行も落とさない。ADR-0007 原則1「データは落とさない」。日付が無い行は
`period_grain`/`period_start`/`period_end`/`period_raw` が NULL になるだけで、
`taxon_id`/`place_id`/`region_id` は他の行と同じ規則で解決する。**座標
（`lat`/`lon`）が無い行も同じ原則で落とさない**——`organism_records` は実測で
全行に座標があるが、将来そうでない行が現れても `place_id`/`place_kind` を
NULL にするだけで扱えるようにしてある。座標があるのに grid01 に解決しない行
だけを異常として止める）。

- `record_id` / `source_table`（常に `'organism_records'`）/ `source_row_id`
  （`organism_records.rowid`。**INTEGER**。O-2 で v1 の走査順の再現に要る。
  rowid は原本のスナップショットに固有の値で、`VACUUM` 等で変わりうる——
  恒久的な識別子ではない。v1（`web/scripts/build-biota.mjs`）も同じ
  スナップショットを走査するため、O-2 の走査順の再現にはこの `rowid` を
  「同じスナップショットの中でだけ」比較に使う。**恒久的な識別子は
  `record_id`（TEXT の主キー）**）/ `source_id`
  （`gbif_kanagawa_occurrences`/`inaturalist_kanagawa`。将来 O-1b のキューブが
  次元に使う）— 素の carry-over。
- `region_id`: **出典から決める**（ADR-0022 決定3の最初の実装。
  `scripts/migrate/source_regions.py`・`source_regions.yaml`）。`place`
  経由では決められない（grid01 の region_id は常に NULL——ADR-0022 決定1）。
- `taxon_id`: `scripts/taxon_namespaces.py` の名前空間から
  `scripts/registry/common.py` の `taxon_id_gbif`/`taxon_id_inat`（taxon
  レジストリのビルドが実際に ID を組み立てるのと同じ関数）で候補を作り、
  `registry.sqlite` の `taxon` に実在することを検証する。`taxon_key` が
  無い853行（日付ありは775行）は `taxon_id=NULL`。
- `place_id`/`place_kind`: grid01（`registry.build_place` が
  `organism_records` の座標から作った機械グリッド）に解決する。座標がある
  行は**必ず**解決する（ADR-0006 規約4の改定——F4: 機械グリッドには常に解決し
  `coordinate_uncertainty_m` を運ぶ。使う側が精度で絞る）。座標が無い行は
  `place_id`/`place_kind` とも NULL（ADR-0007 原則1）。
- `coordinate_uncertainty_m`/`lat`/`lon`/`scientific_name`/`vernacular_name`/
  `taxon_rank`/`red_list_category`/`is_alien`/`license_class`/
  `publication_scope`: 原表記の旗（F6）。記録にそのまま運ぶ（NULLIF 等の
  正規化はしない——空文字は空文字のまま。v1 `org_norm` の各列が
  `organism_records` の値をそのまま読んでいるのと同じ扱い）。
  `order`/`family` 等の上位分類は taxon の属性から取るので occurrence には
  持たない（O-1 設計 v2 D1 に明記）。
- `period_grain`/`period_start`/`period_end`/`period_raw`: ADR-0008・
  ADR-0024。`observed_on` から `scripts/migrate/occurrence_period.py` で展開する
  （12形。宣言表は `occurrence_period_shapes.yaml`。形の定義自体はコードが正）。
  'Z' 終端の形は `source_regions.yaml` の region の `utc_offset` でローカル時刻に
  変換する（SQLite の日時関数は使わない。Python の `datetime` で計算する）。

## 埋めない列（理由）

`observation`（ADR-0007）の列のうち `variable_id`/`unit_id`/`value_num`/
`censoring`/`stat`/`method_id`/`instrument_id`/`event_id`/`observer_id`/
`quality_stage`/`is_synthetic`/`source_ref` は、occurrence には対応する
概念が無い、または O-1 設計 v2 D1 が明示的に対象外としている
（`organism_records.is_synthetic` は全行0・`event_id`/`quality_stage`/
`source_ref` は org_norm 等の v1 派生テーブルにも現れず、この O-1a の
対象外——将来の消費者が現れたら別途追加を検討する）。

## 機械検証（1つでも失敗すれば `MigrationError`（のサブクラス）で止まる）

- `source_regions.yaml`/`occurrence_period_shapes.yaml` の構造
  （`validate_source_regions_shape`/`validate_occurrence_period_shapes_shape`）
  を実行のたびに検証する——`.get()` で黙って検査を外さない。
  `occurrence_period_shapes.yaml` の形の名前がコード（`_SHAPE_DEFS`）と
  過不足なく一致することも含む。
- 出典（`organism_records.source_id`）が `source_regions.yaml`/
  `taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE` に無い → 即座に止まる。
- `source_regions.yaml`/`occurrence_period_shapes.yaml` の宣言が1件も
  使われなかった・実測件数が `expected_row_count` と食い違う → 止まる。
- `taxon_key` はあるのに `registry.taxon` に無い → 止まる。
- 座標が**あるのに** grid01 の `place_id` が解決できない行 → 止まる
  （座標が無い行は止めない。上記参照）。
- `observed_on` の形が想定外・複数の形に同時に一致・実在しない日付/時刻
  （`'2020-02-30'`・`'...T24:00'` 等）・'Z' → ローカル時刻の変換で年が
  変わった（D3の前提が破れた）→ 止まる（`scripts/migrate/occurrence_period.py`
  の各例外）。
- `period_start`/`period_end` が時刻帯（`+`/`Z`）を持つ、または
  `date(period_start)`/`date(period_end)` が日付部分と一致しない（T1 と
  同じ不変条件。NULL の行は対象外）→ 止まる。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common, occurrence_period, period, source_regions  # noqa: E402
from registry import common as registry_common  # noqa: E402
from taxon_namespaces import TAXON_KEY_SOURCE_NAMESPACE, assert_known_source_ids  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_SOURCE_REGIONS_YAML = ROOT / "scripts" / "migrate" / "source_regions.yaml"
DEFAULT_PERIOD_SHAPES_YAML = ROOT / "scripts" / "migrate" / "occurrence_period_shapes.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REPORT = ROOT / "reports" / "phase_b_occurrence.md"

_SAMPLE_LIMIT = 20

# 名前空間（`TAXON_KEY_SOURCE_NAMESPACE` の値。'gbif'/'inat'）ごとの taxon_id
# 組み立て関数。**taxon レジストリのビルドが実際に ID を発行するのと同じ関数**
# （`scripts/registry/common.py`）を再利用する——ID の書式（`common:taxon:...`）を
# ここで書き直さない（コードレビュー指摘12）。
_ID_BUILDER_BY_NAMESPACE = {
    "gbif": registry_common.taxon_id_gbif,
    "inat": registry_common.taxon_id_inat,
}


def _assert_namespaces_have_id_builders() -> None:
    """`TAXON_KEY_SOURCE_NAMESPACE` が出しうる名前空間ラベルは、必ず
    `_ID_BUILDER_BY_NAMESPACE` に対応するエントリを持つことをビルド開始直後に
    確認する（`scripts/registry/build_taxon.py` の
    `_assert_namespaces_have_traits()` と同じ考え方）。
    """
    missing = sorted(set(TAXON_KEY_SOURCE_NAMESPACE.values()) - set(_ID_BUILDER_BY_NAMESPACE))
    if missing:
        raise ValueError(
            "TAXON_KEY_SOURCE_NAMESPACE にある名前空間だが _ID_BUILDER_BY_NAMESPACE に"
            f"無いものがある（taxon_id の組み立て方が決まらない）: {missing}"
        )


def _assert_known_source_ids(work: sqlite3.Connection) -> None:
    """`organism_records.source_id` が `TAXON_KEY_SOURCE_NAMESPACE`
    （taxon_id 候補の組み立てに使う）に無い値を含んでいたら止める。`work` は
    `src` として `ryuiki.sqlite` を ATTACH 済みの接続。

    実際の検査（重複除去・None-safe なソート・例外送出）は
    `taxon_namespaces.assert_known_source_ids()` に一本化してある——
    `scripts/registry/build_taxon.py` の同じ検査と重複させない（/simplify
    指摘1）。`error_cls=common.MigrationError` を渡し、`build_and_write_occurrence`
    が捕まえる例外の型を揃える。
    """
    rows = work.execute("SELECT DISTINCT source_id FROM src.organism_records").fetchall()
    assert_known_source_ids((r[0] for r in rows), error_cls=common.MigrationError)


_SELECT_ORGANISM_RECORDS_SQL = """
SELECT
  o.rowid AS source_row_id, o.record_id, o.source_id, o.observed_on, o.taxon_key,
  o.lat, o.lon, o.coordinate_uncertainty_m,
  o.scientific_name, o.vernacular_name, o.taxon_rank,
  o.red_list_category, o.is_alien, o.license_class, o.publication_scope,
  psr.place_id AS place_id, p.place_kind AS place_kind
FROM src.organism_records o
LEFT JOIN reg.place_source_ref psr
  ON psr.source_id = 'organism_records.lat_lon'
 AND psr.external_key = 'grid01:' || CAST(FLOOR(o.lat*100) AS INT) || ',' || CAST(FLOOR(o.lon*100) AS INT)
LEFT JOIN reg.place p ON p.place_id = psr.place_id
ORDER BY o.rowid
"""

_CREATE_OCCURRENCE_SQL = """
CREATE TABLE {table} (
  record_id                TEXT NOT NULL,
  source_table              TEXT NOT NULL,
  source_row_id             INTEGER NOT NULL,
  source_id                 TEXT NOT NULL,
  region_id                 TEXT NOT NULL,
  taxon_id                  TEXT,
  place_id                  TEXT,
  place_kind                TEXT,
  coordinate_uncertainty_m  REAL,
  lat                       REAL,
  lon                       REAL,
  period_grain              TEXT,
  period_start              TEXT,
  period_end                TEXT,
  period_raw                TEXT,
  scientific_name           TEXT,
  vernacular_name           TEXT,
  taxon_rank                TEXT,
  red_list_category         TEXT,
  is_alien                  INTEGER,
  license_class             TEXT,
  publication_scope         TEXT
)
"""

_CREATE_OCCURRENCE_INDEX_SQL = (
    "CREATE UNIQUE INDEX occurrence_record_id_pk ON {table} (record_id)"
)
_DROP_OCCURRENCE_INDEX_SQL = "DROP INDEX IF EXISTS occurrence_record_id_pk"

_INSERT_SQL = """
INSERT INTO {table} (
  record_id, source_table, source_row_id, source_id, region_id, taxon_id,
  place_id, place_kind, coordinate_uncertainty_m, lat, lon,
  period_grain, period_start, period_end, period_raw,
  scientific_name, vernacular_name, taxon_rank,
  red_list_category, is_alien, license_class, publication_scope
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _empty_stats() -> dict:
    return {
        "total": 0,
        "n_dated": 0,
        "no_coordinate_count": 0,
        "unresolved_taxon_count": 0,
        "unresolved_taxon_sample": [],
        "unresolved_place_count": 0,
        "unresolved_place_sample": [],
        "taxon_null_count": 0,
        "taxon_null_dated_count": 0,
        "region_counts": {},
        "shape_counts": {},
        "z_converted_count": 0,
        "day_changed_count": 0,
        "month_changed_count": 0,
    }


# (件数のキー, サンプル一覧のキー, メッセージのテンプレート)。`_SAMPLE_LIMIT` まで
# サンプルを出す（テーブルごとに上限を変える理由が無いので、値を1種類だけ持つ
# ——以前は使われない `sample_limit` 次元を持っていた。コードレビュー指摘13）。
_PROBLEM_SPECS = (
    (
        "unresolved_taxon_count", "unresolved_taxon_sample",
        "occurrence: taxon_key はあるが registry.taxon に無い行: "
        "{count}件（例: {sample}）",
    ),
    (
        "unresolved_place_count", "unresolved_place_sample",
        "occurrence: 座標はあるのに grid01 の place_id が解決できない行: "
        "{count}件（例: {sample}）",
    ),
)


def _problems_from_stats(stats: dict) -> list[str]:
    problems: list[str] = []
    for count_key, sample_key, template in _PROBLEM_SPECS:
        count = stats[count_key]
        if not count:
            continue
        problems.append(template.format(count=count, sample=stats[sample_key]))
    return problems


def _load_taxon_ids(work: sqlite3.Connection) -> set[str]:
    return {row[0] for row in work.execute("SELECT taxon_id FROM reg.taxon")}


def _ingest(
    work: sqlite3.Connection,
    dest: sqlite3.Connection,
    insert_table: str,
    taxon_ids: set[str],
    sources: dict,
    regions: dict,
    source_usage,
    region_usage,
    shape_usage,
) -> dict:
    """`organism_records` を1行ずつ読み、`insert_table` へ `executemany` で
    ストリーム挿入する（b03 の C-5 と同じ理由。823,692行を Python のリストに
    溜めない）。
    """
    stats = _empty_stats()

    def rows():
        for row in work.execute(_SELECT_ORGANISM_RECORDS_SQL):
            (
                source_row_id, record_id, source_id, observed_on, taxon_key,
                lat, lon, coordinate_uncertainty_m,
                scientific_name, vernacular_name, taxon_rank,
                red_list_category, is_alien, license_class, publication_scope,
                place_id, place_kind,
            ) = row

            stats["total"] += 1

            source_region = sources.get(source_id)
            if source_region is None:
                raise source_regions.UnknownSourceRegionError(source_id)
            source_usage.mark_used(source_id)
            region_id = source_region.region_id
            region_usage.mark_used(region_id)
            stats["region_counts"][region_id] = stats["region_counts"].get(region_id, 0) + 1
            utc_offset = regions[region_id].utc_offset

            if not taxon_key:
                taxon_id = None
                stats["taxon_null_count"] += 1
                if observed_on is not None:
                    stats["taxon_null_dated_count"] += 1
            else:
                ns = TAXON_KEY_SOURCE_NAMESPACE[source_id]  # _assert_known_source_ids 済み
                taxon_id_candidate = _ID_BUILDER_BY_NAMESPACE[ns](taxon_key)
                if taxon_id_candidate not in taxon_ids:
                    stats["unresolved_taxon_count"] += 1
                    if len(stats["unresolved_taxon_sample"]) < _SAMPLE_LIMIT:
                        stats["unresolved_taxon_sample"].append((record_id, taxon_id_candidate))
                    continue
                taxon_id = taxon_id_candidate

            if lat is None or lon is None:
                # 座標が無い記録（ADR-0007 原則1で落とさない。実測では0件だが、
                # 将来そういう記録が増えても扱えるようにしてある）。
                stats["no_coordinate_count"] += 1
            elif place_id is None:
                stats["unresolved_place_count"] += 1
                if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                    stats["unresolved_place_sample"].append((record_id, lat, lon))
                continue

            if observed_on is None:
                period_grain = period_start = period_end = period_raw = None
            else:
                expanded = occurrence_period.expand_period(
                    observed_on, utc_offset, record_id=record_id
                )
                shape_usage.mark_used(expanded.shape)
                stats["shape_counts"][expanded.shape] = stats["shape_counts"].get(expanded.shape, 0) + 1
                if expanded.shape in occurrence_period.Z_SHAPES:
                    stats["z_converted_count"] += 1
                if expanded.day_changed:
                    stats["day_changed_count"] += 1
                if expanded.month_changed:
                    stats["month_changed_count"] += 1
                period_grain = expanded.period_grain
                period_start = expanded.period_start
                period_end = expanded.period_end
                period_raw = observed_on
                stats["n_dated"] += 1

            yield (
                record_id, "organism_records", source_row_id, source_id, region_id, taxon_id,
                place_id, place_kind, coordinate_uncertainty_m, lat, lon,
                period_grain, period_start, period_end, period_raw,
                scientific_name, vernacular_name, taxon_rank,
                red_list_category, is_alien, license_class, publication_scope,
            )

    dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), rows())
    return stats


def build_and_write_occurrence(
    ryuiki_db,
    registry_db,
    source_regions_yaml=DEFAULT_SOURCE_REGIONS_YAML,
    period_shapes_yaml=DEFAULT_PERIOD_SHAPES_YAML,
    out_path=DEFAULT_OUT,
) -> dict:
    """`occurrence` を構築し、`out_path` の `occurrence` テーブルに書き込む
    （`out_path` の他のテーブル——`observation`/`observation_agg`——は触らない）。

    問題が見つかれば（宣言表の構造・未使用・件数不一致・解決漏れ・形の異常・
    年境界越え・T1 不変条件違反のいずれか）`common.MigrationError`（のサブクラス）
    を投げる。A-1: `migrate.common.staged_table` の `with` ブロックの中で全検証を
    行うため、失敗すれば本番の `occurrence` には一切触れずに終わる。
    """
    _assert_namespaces_have_id_builders()

    # 宣言表の構造検証（コードレビュー指摘6: `.get()` で黙って検査を外さない。
    # CI 用の `validate_*_shape` を実行時にも呼ぶ）。
    source_regions.validate_source_regions_shape(source_regions_yaml)
    occurrence_period.validate_occurrence_period_shapes_shape(period_shapes_yaml)

    # consumer="occurrence": P-1b で source_regions.yaml に土地利用
    # （consumer="observation"）の宣言が同居するようになったため、b06 が
    # 自分の使わない宣言を「未使用宣言」として誤検出しないように絞り込む
    # （scripts/migrate/source_regions.py モジュール docstring「consumer」節）。
    sources, regions = source_regions.load_source_regions(source_regions_yaml, consumer="occurrence")
    source_usage = period.EntryUsage(sources)
    region_usage = period.EntryUsage(regions)
    shapes = occurrence_period.load_period_shapes(period_shapes_yaml)
    # `validate_occurrence_period_shapes_shape()` は生の YAML dict に対して
    # 同じ名前集合の一致を既に検証済みだが、ここでは `load_period_shapes()` が
    # 実際に作った `PeriodShape` の集合に対して独立にもう一度確認する
    # （読み込み処理自体が将来変わって2つの結果がずれても黙って見逃さないため。
    # 12要素の集合比較で安価）。
    occurrence_period.assert_declared_shapes_match_code(shapes, period_shapes_yaml)
    shape_usage = period.EntryUsage(shapes)

    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(f"file:{out_path}", uri=True)
    dest.execute("PRAGMA journal_mode=DELETE")
    try:
        with common.staged_table(dest, "occurrence", _CREATE_OCCURRENCE_SQL) as staging:
            work = sqlite3.connect(":memory:", uri=True)
            try:
                common.attach_readonly(work, ryuiki_db, "src")
                common.attach_readonly(work, registry_db, "reg")
                _assert_known_source_ids(work)
                taxon_ids = _load_taxon_ids(work)
                stats = _ingest(
                    work, dest, staging, taxon_ids, sources, regions, source_usage, region_usage,
                    shape_usage,
                )
            finally:
                work.close()

            problems = _problems_from_stats(stats)
            if problems:
                raise common.MigrationError(
                    "occurrence の取り込みを中止した。以下の問題を解消してから"
                    "再実行すること:\n- " + "\n- ".join(problems)
                )
            dest.commit()

            declaration_problems = (
                period.declaration_problems(source_usage, "source_regions.yaml (sources)")
                + period.declaration_problems(region_usage, "source_regions.yaml (regions)")
                + period.declaration_problems(shape_usage, "occurrence_period_shapes.yaml")
            )
            if declaration_problems:
                raise common.MigrationError(
                    "occurrence の構築を中止した（取り込み自体は成功したが、宣言表の検証に"
                    "失敗した）。以下を解消してから再実行すること:\n- "
                    + "\n- ".join(declaration_problems)
                )

            dest.execute(_CREATE_OCCURRENCE_INDEX_SQL.format(table=f'"{staging}"'))
            dest.execute(_DROP_OCCURRENCE_INDEX_SQL)

            # T1 不変条件（ADR-0024）: period_start/period_end が時刻帯を持たない、
            # date(period_start)/date(period_end) がそれぞれ自身の日付部分と一致する
            # （NULL の行——observed_on が無い記録——は対象外）。period_end も見る
            # （以前は period_start だけだった。コードレビュー指摘3）。
            bad = dest.execute(
                f"""
                SELECT COUNT(*) FROM "{staging}"
                WHERE period_start IS NOT NULL AND (
                  period_start LIKE '%+%' OR period_start LIKE '%Z%'
                  OR period_end LIKE '%+%' OR period_end LIKE '%Z%'
                  OR date(period_start) IS NULL
                  OR date(period_start) <> substr(period_start, 1, 10)
                  OR date(period_end) IS NULL
                  OR date(period_end) <> substr(period_end, 1, 10)
                  OR period_start > period_end
                )
                """
            ).fetchone()[0]
            if bad:
                raise common.MigrationError(
                    f"T1 の不変条件（時刻帯を持たない・日付部分が一致する・start<=end）が"
                    f"崩れている行が{bad}件ある。scripts/migrate/occurrence_period.py を"
                    "確認すること。"
                )
            # ここまで来たら with ブロックを正常に抜け、staged_table が
            # 作業用テーブルを本番名 "occurrence" に差し替える（A-1）。

        # 段階間の指紋（Issue #37 #1）: b07/b09/b08 が「今の occurrence から
        # 作った出力か」を検証できるよう、確定した occurrence の内容を記録する
        # （scripts/migrate/common.py の該当コメント参照）。
        common.record_stage_fingerprint(dest, "occurrence")
        dest.commit()
    except BaseException:
        dest.close()
        raise
    dest.close()
    return stats


def render_report(stats: dict) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Phase B ファクト移行 — occurrence の要約（O-1a）")
    a("")
    a(
        "`scripts/b06_build_occurrence.py` が `data/db/ryuiki.sqlite` の "
        "`organism_records` から `data/db/v2.sqlite` の `occurrence` を作った結果の"
        "要約。設計は `docs/plans/PHASE_B_OCCURRENCE.md`（O-1a節）参照。"
    )
    a("")
    a(f"- `organism_records` 総行数: **{stats['total']:,}**")
    a(f"- `occurrence` 行数: **{stats['total']:,}**（全行取り込む。ADR-0007原則1）")
    a(f"- 日付あり（`period_raw` NOT NULL）: **{stats['n_dated']:,}**")
    a(f"- 座標なし（`lat`/`lon` NULL）: **{stats['no_coordinate_count']:,}**")
    a(
        f"- `taxon_id` NULL: **{stats['taxon_null_count']:,}**"
        f"（うち日付あり: {stats['taxon_null_dated_count']:,}）"
    )
    a("")
    a("## region 内訳")
    a("")
    a("| region_id | 行数 |")
    a("|---|---:|")
    for region_id, n in sorted(stats["region_counts"].items()):
        a(f"| `{region_id}` | {n:,} |")
    a("")
    a("## 期間の形（12形）ごとの件数")
    a("")
    a("| 形 | 行数 |")
    a("|---|---:|")
    for shape, n in sorted(stats["shape_counts"].items()):
        a(f"| `{shape}` | {n:,} |")
    a("")
    a(f"- 'Z' → ローカル時刻の変換件数: **{stats['z_converted_count']:,}**")
    a(
        f"- 変換で日が変わった件数: **{stats['day_changed_count']:,}** / "
        f"月が変わった件数: **{stats['month_changed_count']:,}** / "
        "年が変わった件数: 0（1件でもあれば構築自体が止まる。D3の前提）"
    )
    a("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ryuiki-db", default=str(DEFAULT_RYUIKI_DB))
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--source-regions-yaml", default=str(DEFAULT_SOURCE_REGIONS_YAML))
    parser.add_argument("--period-shapes-yaml", default=str(DEFAULT_PERIOD_SHAPES_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("occurrence を構築して書き出し") as info:
        stats = build_and_write_occurrence(
            args.ryuiki_db, registry_db, args.source_regions_yaml, args.period_shapes_yaml, args.out
        )
        info["n"] = stats["total"]

    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(stats), encoding="utf-8")
    print(f"→ {report_path}")
    print(f"  occurrence: {stats['total']:,}行（日付あり {stats['n_dated']:,}）")


if __name__ == "__main__":
    main()
