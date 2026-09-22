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
`taxon_id`/`place_id`/`region_id` は他の行と同じ規則で解決する）。

- `record_id` / `source_table`（常に `'organism_records'`）/ `source_row_id`
  （rowid。O-2 で v1 の走査順の再現に要る）/ `source_id`
  （`gbif_kanagawa_occurrences`/`inaturalist_kanagawa`。将来 O-1b のキューブが
  次元に使う）— 素の carry-over。
- `region_id`: **出典から決める**（ADR-0022 決定3の最初の実装。
  `scripts/migrate/source_regions.py`・`source_regions.yaml`）。`place`
  経由では決められない（grid01 の region_id は常に NULL——ADR-0022 決定1）。
- `taxon_id`: `scripts/taxon_namespaces.py` の名前空間から
  `common:taxon:gbif.<key>`/`common:taxon:inat.<key>` を組み立て、
  `registry.sqlite` の `taxon` に実在することを検証する。`taxon_key` が
  無い853行（日付ありは775行）は `taxon_id=NULL`。
- `place_id`/`place_kind`: grid01（`registry.build_place` が
  `organism_records` の座標から作った機械グリッド）に**必ず**解決する
  （lat/lon は全行に入っている。ADR-0006 規約4の改定——F4: 機械グリッドには
  常に解決し `coordinate_uncertainty_m` を運ぶ。使う側が精度で絞る）。
- `coordinate_uncertainty_m`/`lat`/`lon`/`scientific_name`/`vernacular_name`/
  `taxon_rank`/`red_list_category`/`is_alien`/`license_class`/
  `publication_scope`: 原表記の旗（F6）。記録にそのまま運ぶ（NULLIF 等の
  正規化はしない——空文字は空文字のまま。v1 `org_norm` の各列が
  `organism_records` の値をそのまま読んでいるのと同じ扱い）。
  `order`/`family` 等の上位分類は taxon の属性から取るので occurrence には
  持たない（O-1 設計 v2 D1 に明記）。
- `period_grain`/`period_start`/`period_end`/`period_raw`: ADR-0008・
  ADR-0024。`observed_on` から `scripts/migrate/occurrence_period.py` で展開する
  （12形。宣言表は `occurrence_period_shapes.yaml`）。'Z' 終端の形は
  `source_regions.yaml` の region の `utc_offset` でローカル時刻に変換する
  （SQLite の日時関数は使わない。Python の `datetime` で計算する）。

## 埋めない列（理由）

`observation`（ADR-0007）の列のうち `variable_id`/`unit_id`/`value_num`/
`censoring`/`stat`/`method_id`/`instrument_id`/`event_id`/`observer_id`/
`quality_stage`/`is_synthetic`/`source_ref` は、occurrence には対応する
概念が無い、または O-1 設計 v2 D1 が明示的に対象外としている
（`organism_records.is_synthetic` は全行0・`event_id`/`quality_stage`/
`source_ref` は org_norm 等の v1 派生テーブルにも現れず、この O-1a の
対象外——将来の消費者が現れたら別途追加を検討する）。

## 機械検証（1つでも失敗すれば `MigrationError` で止まる）

- 出典（`organism_records.source_id`）が `source_regions.yaml` に無い →
  即座に止まる（`UnknownSourceRegionError`）。
- `source_regions.yaml`/`occurrence_period_shapes.yaml` の宣言が1件も
  使われなかった・実測件数が `expected_row_count` と食い違う → 止まる。
- `taxon_key` はあるのに `registry.taxon` に無い → 止まる。
- 座標のある行（＝全行）で grid01 の `place_id` が解決できない → 止まる。
- 'Z' → ローカル時刻の変換で年が変わった（D3の前提が破れた）→ 止まる
  （`occurrence_period.YearBoundaryCrossedError`）。
- `period_start`/`period_end` が時刻帯（`+`/`Z`）を持つ、または
  `date(period_start)` が日付部分と一致しない（T1 と同じ不変条件。
  NULL の行は対象外）→ 止まる。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common, occurrence_period, source_regions  # noqa: E402
from taxon_namespaces import TAXON_KEY_SOURCE_NAMESPACE  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_SOURCE_REGIONS_YAML = ROOT / "scripts" / "migrate" / "source_regions.yaml"
DEFAULT_PERIOD_SHAPES_YAML = ROOT / "scripts" / "migrate" / "occurrence_period_shapes.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REPORT = ROOT / "reports" / "phase_b_occurrence.md"

_SAMPLE_LIMIT = 20

# `taxon_key` を持つ行の taxon_id 候補（`common:taxon:<ns>.<key>`）を組み立てる
# CASE 式。`TAXON_KEY_SOURCE_NAMESPACE`（正）から動的に組み立てる——ハードコードの
# 重複を作らない（`scripts/registry/build_taxon.py` の `_namespace_case_sql` と
# 同じ考え方）。
def _taxon_id_candidate_case_sql() -> str:
    branches = " ".join(
        f"WHEN o.source_id = '{source_id.replace(chr(39), chr(39) * 2)}' "
        f"THEN 'common:taxon:{ns}.' || o.taxon_key"
        for source_id, ns in TAXON_KEY_SOURCE_NAMESPACE.items()
    )
    return (
        "CASE WHEN o.taxon_key IS NULL OR o.taxon_key = '' THEN NULL "
        f"{branches} ELSE NULL END"
    )


_SELECT_ORGANISM_RECORDS_SQL_TEMPLATE = """
WITH base AS (
  SELECT
    o.rowid AS source_row_id,
    o.record_id, o.source_id, o.observed_on,
    o.lat, o.lon, o.coordinate_uncertainty_m,
    o.scientific_name, o.vernacular_name, o.taxon_rank,
    o.red_list_category, o.is_alien, o.license_class, o.publication_scope,
    CAST(FLOOR(o.lat*100) AS INT) AS mlat,
    CAST(FLOOR(o.lon*100) AS INT) AS mlon,
    {taxon_id_candidate_case} AS taxon_id_candidate
  FROM src.organism_records o
)
SELECT
  b.source_row_id, b.record_id, b.source_id, b.observed_on,
  b.lat, b.lon, b.coordinate_uncertainty_m,
  b.scientific_name, b.vernacular_name, b.taxon_rank,
  b.red_list_category, b.is_alien, b.license_class, b.publication_scope,
  b.taxon_id_candidate, t.taxon_id AS taxon_id_resolved,
  psr.place_id AS place_id, p.place_kind AS place_kind
FROM base b
LEFT JOIN reg.taxon t ON t.taxon_id = b.taxon_id_candidate
LEFT JOIN reg.place_source_ref psr
  ON psr.source_id = 'organism_records.lat_lon'
 AND psr.external_key = 'grid01:' || b.mlat || ',' || b.mlon
LEFT JOIN reg.place p ON p.place_id = psr.place_id
ORDER BY b.source_row_id
"""

_CREATE_OCCURRENCE_SQL = """
CREATE TABLE {table} (
  record_id                TEXT NOT NULL,
  source_table              TEXT NOT NULL,
  source_row_id             TEXT NOT NULL,
  source_id                 TEXT NOT NULL,
  region_id                 TEXT NOT NULL,
  taxon_id                  TEXT,
  place_id                  TEXT NOT NULL,
  place_kind                TEXT NOT NULL,
  coordinate_uncertainty_m  REAL,
  lat                       REAL NOT NULL,
  lon                       REAL NOT NULL,
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


def _assert_known_source_ids(work: sqlite3.Connection) -> None:
    """`organism_records.source_id` が `TAXON_KEY_SOURCE_NAMESPACE`
    （taxon_id 候補の組み立てに使う）に無い値を含んでいたら止める
    （`scripts/registry/build_taxon.py` の `_assert_known_source_ids` と同じ
    考え方——ここで止めないと taxon_id_candidate の CASE 式が未知の source_id を
    黙って NULL に落とし、taxon 解決漏れとして紛れ込む）。`work` は `src` として
    `ryuiki.sqlite` を ATTACH 済みの接続（`_ingest` と同じ入力）。
    """
    rows = work.execute("SELECT DISTINCT source_id FROM src.organism_records").fetchall()
    unknown = sorted(r[0] for r in rows if r[0] not in TAXON_KEY_SOURCE_NAMESPACE)
    if unknown:
        raise common.MigrationError(
            "organism_records に taxon_id の名前空間が未定義の source_id がある"
            f"（scripts/taxon_namespaces.py の TAXON_KEY_SOURCE_NAMESPACE に追記すること）: "
            f"{unknown}"
        )


def _empty_stats() -> dict:
    return {
        "total": 0,
        "n_dated": 0,
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


_PROBLEM_SPECS = (
    (
        "unresolved_taxon_count", "unresolved_taxon_sample", None,
        "occurrence: taxon_key はあるが registry.taxon に無い行: "
        "{count}件（例: {sample}）",
    ),
    (
        "unresolved_place_count", "unresolved_place_sample", None,
        "occurrence: 座標はあるのに grid01 の place_id が解決できない行: "
        "{count}件（例: {sample}）",
    ),
)


def _problems_from_stats(stats: dict) -> list[str]:
    problems: list[str] = []
    for count_key, sample_key, sample_limit, template in _PROBLEM_SPECS:
        count = stats[count_key]
        if not count:
            continue
        sample = stats[sample_key][:sample_limit] if sample_limit is not None else stats[sample_key]
        problems.append(template.format(count=count, sample=sample))
    return problems


def _ingest(
    work: sqlite3.Connection,
    dest: sqlite3.Connection,
    insert_table: str,
    sources: dict,
    regions: dict,
    source_usage,
    region_usage,
    shapes: dict,
    shape_usage,
) -> dict:
    """`organism_records` を1行ずつ読み、`insert_table` へ `executemany` で
    ストリーム挿入する（b03 の C-5 と同じ理由。823,692行を Python のリストに
    溜めない）。
    """
    stats = _empty_stats()
    sql = _SELECT_ORGANISM_RECORDS_SQL_TEMPLATE.format(
        taxon_id_candidate_case=_taxon_id_candidate_case_sql()
    )

    def rows():
        for row in work.execute(sql):
            (
                source_row_id, record_id, source_id, observed_on,
                lat, lon, coordinate_uncertainty_m,
                scientific_name, vernacular_name, taxon_rank,
                red_list_category, is_alien, license_class, publication_scope,
                taxon_id_candidate, taxon_id_resolved,
                place_id, place_kind,
            ) = row

            stats["total"] += 1
            source_row_id = str(source_row_id)

            source_region = sources.get(source_id)
            if source_region is None:
                raise source_regions.UnknownSourceRegionError(source_id)
            source_usage.mark_used(source_id)
            region_id = source_region.region_id
            region_usage.mark_used(region_id)
            stats["region_counts"][region_id] = stats["region_counts"].get(region_id, 0) + 1
            utc_offset = regions[region_id].utc_offset

            if taxon_id_candidate is None:
                taxon_id = None
                stats["taxon_null_count"] += 1
                if observed_on is not None:
                    stats["taxon_null_dated_count"] += 1
            elif taxon_id_resolved is None:
                stats["unresolved_taxon_count"] += 1
                if len(stats["unresolved_taxon_sample"]) < _SAMPLE_LIMIT:
                    stats["unresolved_taxon_sample"].append((record_id, taxon_id_candidate))
                continue
            else:
                taxon_id = taxon_id_resolved

            if place_id is None:
                stats["unresolved_place_count"] += 1
                if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                    stats["unresolved_place_sample"].append((record_id, lat, lon))
                continue

            if observed_on is None:
                period_grain = period_start = period_end = period_raw = None
            else:
                expanded = occurrence_period.expand_period(observed_on, shapes, utc_offset)
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


def _declaration_problems(usage, yaml_label: str) -> list[str]:
    problems: list[str] = []
    unused = usage.unused_entries()
    if unused:
        problems.append(f"{yaml_label} に宣言されているが1件も該当しなかったエントリ: {unused}")
    mismatched = usage.mismatched_expected_counts()
    if mismatched:
        problems.append(
            f"{yaml_label} の expected_row_count と実測件数が食い違う: "
            f"{mismatched}（宣言 (expected, actual) の順）"
        )
    return problems


def build_and_write_occurrence(
    ryuiki_db,
    registry_db,
    source_regions_yaml=DEFAULT_SOURCE_REGIONS_YAML,
    period_shapes_yaml=DEFAULT_PERIOD_SHAPES_YAML,
    out_path=DEFAULT_OUT,
) -> dict:
    """`occurrence` を構築し、`out_path` の `occurrence` テーブルに書き込む
    （`out_path` の他のテーブル——`observation`/`observation_agg`——は触らない）。

    問題が見つかれば（宣言表の未使用・件数不一致・解決漏れ・年境界越え・T1
    不変条件違反のいずれか）`common.MigrationError`（または
    `occurrence_period.YearBoundaryCrossedError`。どちらも `MigrationError` の
    サブクラス）を投げる。A-1: `migrate.common.staged_table` の `with` ブロックの
    中で全検証を行うため、失敗すれば本番の `occurrence` には一切触れずに終わる。
    """
    sources, regions = source_regions.load_source_regions(source_regions_yaml)
    source_usage = source_regions.SourceRegionUsage(sources)
    region_usage = source_regions.RegionUsage(regions)
    shapes = occurrence_period.load_period_shapes(period_shapes_yaml)
    shape_usage = occurrence_period.PeriodShapeUsage(shapes)

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
                stats = _ingest(
                    work, dest, staging, sources, regions, source_usage, region_usage,
                    shapes, shape_usage,
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
                _declaration_problems(source_usage, "source_regions.yaml (sources)")
                + _declaration_problems(region_usage, "source_regions.yaml (regions)")
                + _declaration_problems(shape_usage, "occurrence_period_shapes.yaml")
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
            # date(period_start) が period_start 自身の日付部分と一致する
            # （NULL の行——observed_on が無い記録——は対象外）。
            bad = dest.execute(
                f"""
                SELECT COUNT(*) FROM "{staging}"
                WHERE period_start IS NOT NULL AND (
                  period_start LIKE '%+%' OR period_start LIKE '%Z%'
                  OR period_end LIKE '%+%' OR period_end LIKE '%Z%'
                  OR date(period_start) IS NULL
                  OR date(period_start) <> substr(period_start, 1, 10)
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
    a(
        f"- 'Z' → ローカル時刻の変換件数: **{stats['z_converted_count']:,}**"
        f"（期待 1,958）"
    )
    a(
        f"- 変換で日が変わった件数: **{stats['day_changed_count']:,}**（期待 221） / "
        f"月が変わった件数: **{stats['month_changed_count']:,}**（期待 10） / "
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
