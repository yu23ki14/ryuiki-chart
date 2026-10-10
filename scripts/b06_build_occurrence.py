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
  `scripts/migrate/source_regions.py`・`manifests/*.yml`）。`place`
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
  `taxon_rank`/`red_list_category`/`red_list_source`/`is_alien`/`license_class`/
  `publication_scope`: 原表記の旗（F6）。記録にそのまま運ぶ。`red_list_source` は赤リスト判定の出所
  （県版の list_id か 'national'。m03 が付ける。アダプタ経由の記録は NULL）（NULLIF 等の
  正規化はしない——空文字は空文字のまま。v1 `org_norm` の各列が
  `organism_records` の値をそのまま読んでいるのと同じ扱い）。
- `is_alien_in_scope`（Issue #34）: `n_alien`（b07）が数える旗。`scientific_name` の二名法（binom）が
  `taxon_assessment`（moe_ias_2015）に `in_scope=1` で載っていれば 1、無ければ 0。原本の `is_alien`
  （種内で 1/0 が混在し、オオクチバス・ウシガエルが 0 になる。caveat isAlien）は根拠に使わず、
  原表記の旗として `is_alien` に残す。
  `order`/`family` 等の上位分類は taxon の属性から取るので occurrence には
  持たない（O-1 設計 v2 D1 に明記）。
- `period_grain`/`period_start`/`period_end`/`period_raw`: ADR-0008・
  ADR-0024。`observed_on` から `scripts/migrate/occurrence_period.py` で展開する
  （12形。宣言表は `occurrence_period_shapes.yaml`。形の定義自体はコードが正）。
  'Z' 終端の形は `manifests/*.yml` の region の `utc_offset` でローカル時刻に
  変換する（SQLite の日時関数は使わない。Python の `datetime` で計算する）。

## adapter 経由の出現（Issue #40 Phase D）

`manifests/<source_id>.yml` の `adapter` が `builtin` でない target=occurrence の出典は、`scripts/adapters/<source_id>.py`
の `rows(ctx)` が返す行（列契約は `scripts/ingest/api.py`）を、organism_records と同じ後段（region・taxon 解決・
grid01 place・期間の展開）に流す。`record_id` は `<source_id>__<record_key>`、公開 ID は
`public_id.adapter_occurrence_id`（`common:occ:<source_id>.<key>`。`TAXON_KEY_SOURCE_NAMESPACE` への追記は要らない）。
座標の無い記録は `place_id`/`place_kind` NULL のまま落とさない（b09/b07 が watershed の place_id NULL セルにだけ入れる）。
件数・形の宣言値は yaml の宣言値とマニフェストの `expected` の和と突合する。

## 埋めない列（理由）

`observation`（ADR-0007）の列のうち `variable_id`/`unit_id`/`value_num`/
`censoring`/`stat`/`method_id`/`instrument_id`/`event_id`/`observer_id`/
`quality_stage`/`is_synthetic`/`source_ref` は、occurrence には対応する
概念が無い、または O-1 設計 v2 D1 が明示的に対象外としている
（`organism_records.is_synthetic` は全行0・`event_id`/`quality_stage`/
`source_ref` は org_norm 等の v1 派生テーブルにも現れず、この O-1a の
対象外——将来の消費者が現れたら別途追加を検討する）。

## 合成データ（`is_synthetic=1`）を除く（Issue #48 PR-0 オーナー決定・PR-2 §1）

合成データは本番に出さない——`scripts/b03_build_observation.py`（`measurements`/
`sensor_timeseries`）と同じ決定を `organism_records` にも適用する。
`organism_records.is_synthetic` は実測で全行0（合成の生物記録は無い）なので
現状は no-op だが、`_ingest` は `is_synthetic=1` の行を alias/place 解決より
前に明示的に弾く——将来合成の出現記録が足されても黙って `occurrence` に
通さないための防御。除外した行数は `stats["synthetic_excluded_count"]` に
積み、`reports/phase_b_occurrence.md` に出す。b03 と同じく除外を切り替える
オプションは持たない（b03 の `--include-synthetic` は Issue #61 で撤去した）。

## 不在記録（`occurrence_status='ABSENT'`）を除く（2026-10-07 オーナー決定・ADR-0025）

GBIF の `occurrenceStatus=ABSENT` は「その種はいなかった」という記録で、出現ではない。`organism_records`
には残し（`occurrence_status` 列。m03 が GBIF の値をそのまま入れ、iNaturalist 等は NULL）、occurrence からだけ
除く。除いた行数は出典ごとに `stats["absent_excluded_by_source"]` に積み、`manifests/<source>.yml` の
`expected_absent_excluded_rows`（既定 0）と突合する（食い違えば止まる）。NULL/PRESENT/ABSENT 以外の値は止める。
合成データの除外と同じく、`source_usage`/`region_usage` の使用マークは除外より前に行う（宣言の使用判定を変えない）が、
`region_counts`・期間の形・解決の集計は除外後の行だけを数える。

## 機械検証（1つでも失敗すれば `MigrationError`（のサブクラス）で止まる）

- `manifests/*.yml`/`occurrence_period_shapes.yaml` の構造
  （`validate_source_regions_shape`/`validate_occurrence_period_shapes_shape`）
  を実行のたびに検証する——`.get()` で黙って検査を外さない。
  `occurrence_period_shapes.yaml` の形の名前がコード（`_SHAPE_DEFS`）と
  過不足なく一致することも含む。
- 出典（`organism_records.source_id`）が `manifests/*.yml`/
  `taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE` に無い → 即座に止まる。
- `manifests/*.yml`/`occurrence_period_shapes.yaml` の宣言が1件も
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
import json
import math
import dataclasses
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest import manifest as manifest_lib, runner as ingest_runner  # noqa: E402
from migrate import common, edition, occurrence_period, period, public_id, source_regions  # noqa: E402
from registry import common as registry_common  # noqa: E402
from taxon_namespaces import (  # noqa: E402
    IAS_LIST_ID, TAXON_KEY_SOURCE_NAMESPACE, assert_known_source_ids, binom_of,
)

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_MANIFESTS_DIR = source_regions.DEFAULT_MANIFESTS_DIR
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


_REQUIRED_ORGANISM_COLUMNS = {
    "occurrence_status": "GBIF の不在記録を除けない。`python scripts/m03_organisms.py --backfill-occurrence-status` で列を足して値を埋めること",
    "red_list_source": "赤リスト判定の出所が引けない。`python scripts/m03_organisms.py` を全件実行して列を足し値を埋めること",
}


def _assert_organism_columns(work: sqlite3.Connection) -> None:
    """`organism_records` に m03 が足す列（occurrence_status・red_list_source）が無い（古い原本）なら、
    黙って進まずに止める。"""
    cols = {r[1] for r in work.execute("PRAGMA src.table_info(organism_records)")}
    for col, hint in _REQUIRED_ORGANISM_COLUMNS.items():
        if col not in cols:
            raise common.MigrationError(f"organism_records に {col} 列が無い（{hint}）")


_SELECT_ORGANISM_RECORDS_SQL = """
SELECT
  o.rowid AS source_row_id, o.record_id, o.source_id, o.observed_on, o.taxon_key,
  o.lat, o.lon, o.coordinate_uncertainty_m,
  o.scientific_name, o.vernacular_name, o.taxon_rank,
  o.red_list_category, o.red_list_source, o.is_alien, o.license_class, o.publication_scope,
  psr.place_id AS place_id, p.place_kind AS place_kind, o.is_synthetic, o.occurrence_status
FROM src.organism_records o
LEFT JOIN reg.place_source_ref psr
  ON psr.key_space = 'grid01_latlon'
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
  publication_scope         TEXT,
  is_alien_in_scope         INTEGER,
  occurrence_id             TEXT NOT NULL,
  source_edition_id         TEXT,
  attributes                TEXT,
  red_list_source           TEXT   -- 赤リスト判定の出所（県版の list_id か 'national'）。末尾なのは既存の位置指定の挿入を壊さないため
)
"""

_CREATE_OCCURRENCE_INDEX_SQL = (
    "CREATE UNIQUE INDEX occurrence_record_id_pk ON {table} (record_id)"
)
_DROP_OCCURRENCE_INDEX_SQL = "DROP INDEX IF EXISTS occurrence_record_id_pk"
# Issue #39 Phase C（担当 C）: 公開 ID（`migrate/public_id.py`）も同じ流儀で一意性を検証する
# （旧キー record_id と occurrence_id の両方が UNIQUE = 旧 -> 新が1対1に引ける）。
_CREATE_OCCURRENCE_ID_INDEX_SQL = (
    "CREATE UNIQUE INDEX occurrence_occurrence_id_pk ON {table} (occurrence_id)"
)
_DROP_OCCURRENCE_ID_INDEX_SQL = "DROP INDEX IF EXISTS occurrence_occurrence_id_pk"

_INSERT_SQL = """
INSERT INTO {table} (
  record_id, source_table, source_row_id, source_id, region_id, taxon_id,
  place_id, place_kind, coordinate_uncertainty_m, lat, lon,
  period_grain, period_start, period_end, period_raw,
  scientific_name, vernacular_name, taxon_rank,
  red_list_category, is_alien, license_class, publication_scope,
  is_alien_in_scope, occurrence_id, source_edition_id, attributes, red_list_source
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


# occurrence_status の語彙（GBIF のまま。NULL は不在の概念が無い出典 = iNaturalist 等）。
STATUS_ABSENT = "ABSENT"
_KNOWN_STATUSES = frozenset({None, "PRESENT", STATUS_ABSENT})

# 除外の理由（_exclusion_reason の戻り値）
_EXCLUDE_SYNTHETIC = "synthetic"
_EXCLUDE_ABSENT = "absent"
_EXCLUDE_UNKNOWN_STATUS = "unknown_status"


def _exclusion_reason(is_synthetic, occurrence_status) -> str | None:
    """occurrence に入れない行の理由（入れる行は None）。優先順は 合成データ → 不在記録 → 未知の状態。
    - 合成データ（`is_synthetic=1`）: Issue #48 PR-0 オーナー決定。本番に出さない。
    - 不在記録（`occurrence_status='ABSENT'`）: 2026-10-07 オーナー決定・ADR-0025。原本には残し occurrence からだけ除く。
    - 未知の状態: 語彙が増えた。除いたうえで `_problems_from_stats` が止める。"""
    if is_synthetic == 1:
        return _EXCLUDE_SYNTHETIC
    if occurrence_status == STATUS_ABSENT:
        return _EXCLUDE_ABSENT
    if occurrence_status not in _KNOWN_STATUSES:
        return _EXCLUDE_UNKNOWN_STATUS
    return None


def _count_exclusion(stats: dict, reason: str, source_id: str, record_id: str, occurrence_status) -> None:
    """除外を stats に積む。不在記録は出典別（マニフェストの `expected_absent_excluded_rows` と突合する）。"""
    if reason == _EXCLUDE_SYNTHETIC:
        stats["synthetic_excluded_count"] += 1
    elif reason == _EXCLUDE_ABSENT:
        stats["absent_excluded_count"] += 1
        by_source = stats["absent_excluded_by_source"]
        by_source[source_id] = by_source.get(source_id, 0) + 1
    else:
        stats["unknown_status_count"] += 1
        if len(stats["unknown_status_sample"]) < _SAMPLE_LIMIT:
            stats["unknown_status_sample"].append((record_id, occurrence_status))


def _empty_stats() -> dict:
    return {
        "total": 0,
        "synthetic_excluded_count": 0,
        "absent_excluded_count": 0,
        "n_occurrence": 0,
        "absent_excluded_by_source": {},
        "unknown_status_count": 0,
        "unknown_status_sample": [],
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
        "adapter_counts": {},
        "adapter_attributes_count": {},
        "adapter_problems": [],
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
    (
        "unknown_status_count", "unknown_status_sample",
        "occurrence: organism_records.occurrence_status が NULL/PRESENT/ABSENT のどれでもない行: "
        "{count}件（例: {sample}）。GBIF の語彙が増えた——出現として数えるか除くかを決めてから b06 を直すこと",
    ),
)


def _problems_from_stats(stats: dict) -> list[str]:
    problems: list[str] = []
    for count_key, sample_key, template in _PROBLEM_SPECS:
        count = stats[count_key]
        if not count:
            continue
        problems.append(template.format(count=count, sample=stats[sample_key]))
    problems.extend(stats["adapter_problems"])
    return problems


def _absent_excluded_problems(sources: dict, measured: dict[str, int]) -> list[str]:
    """不在記録（`occurrence_status='ABSENT'`）として除いた行数を、マニフェストの
    `expected_absent_excluded_rows`（既定 0）と出典ごとに突合する。"""
    problems = [
        f"manifests/{sid}.yml の expected_absent_excluded_rows={src.expected_absent_excluded_rows} と、"
        f"organism_records.occurrence_status='ABSENT' で除いた行の実測 {measured.get(sid, 0)} が食い違う"
        "（原本の不在記録が増減した、または宣言が古い。宣言を測り直す）"
        for sid, src in sorted(sources.items())
        if measured.get(sid, 0) != src.expected_absent_excluded_rows
    ]
    problems += [
        f"occurrence_status='ABSENT' の行が出典 {sid!r} にあるが、manifests/ に宣言されていない"
        for sid in sorted(set(measured) - set(sources))
    ]
    return problems


def _load_alien_binoms(work: sqlite3.Connection) -> frozenset[str]:
    """外来種として数える binom（`taxon_assessment` の moe_ias_2015 で `in_scope=1`）。
    Issue #34: `is_alien_in_scope` の根拠は原本の `is_alien` 旗（種内で 1/0 が混在し、オオクチバス・
    ウシガエルが 0 になる。caveat isAlien）ではなく、環境省リストの binom 一致と除外規則
    （`registry/taxon/assessment_scope_exclusions.yaml`）にする。"""
    return frozenset(
        r[0] for r in work.execute(
            "SELECT DISTINCT binom FROM reg.taxon_assessment "
            "WHERE list_id = ? AND in_scope = 1 AND binom IS NOT NULL",
            (IAS_LIST_ID,),
        )
    )


def _load_taxon_ids(work: sqlite3.Connection) -> set[str]:
    return {row[0] for row in work.execute("SELECT taxon_id FROM reg.taxon")}


def _add_manifest_shape_counts(shapes: dict, extra: dict[str, int]) -> dict:
    """マニフェストの `expected.period_shapes` を、yaml の形ごとの宣言件数に足す。未知の形名は止める。"""
    unknown = sorted(set(extra) - set(shapes))
    if unknown:
        raise common.MigrationError(
            f"マニフェストの expected.period_shapes に occurrence_period_shapes.yaml に無い形がある: {unknown}"
        )
    return {
        name: dataclasses.replace(sh, expected_row_count=sh.expected_row_count + extra.get(name, 0))
        for name, sh in shapes.items()
    }


def _period_fields(stats: dict, shape_usage, observed_on, utc_offset, record_id) -> tuple:
    """`(period_grain, period_start, period_end, period_raw)`。日付の無い記録は全て None。形の使用・件数を `stats` に積む
    （organism_records と adapter 経由の行で同じ規則を使う）。"""
    if observed_on is None:
        return None, None, None, None
    expanded = occurrence_period.expand_period(observed_on, utc_offset, record_id=record_id)
    shape_usage.mark_used(expanded.shape)
    stats["shape_counts"][expanded.shape] = stats["shape_counts"].get(expanded.shape, 0) + 1
    if expanded.shape in occurrence_period.Z_SHAPES:
        stats["z_converted_count"] += 1
    if expanded.day_changed:
        stats["day_changed_count"] += 1
    if expanded.month_changed:
        stats["month_changed_count"] += 1
    stats["n_dated"] += 1
    return expanded.period_grain, expanded.period_start, expanded.period_end, observed_on


def _load_grid01_places(work: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """`grid01:<floor(lat*100)>,<floor(lon*100)>` -> (place_id, place_kind)（organism_records の SQL JOIN と同じキー）。"""
    return {
        ext: (pid, kind) for ext, pid, kind in work.execute(
            "SELECT psr.external_key, psr.place_id, p.place_kind FROM reg.place_source_ref psr "
            "JOIN reg.place p ON p.place_id = psr.place_id WHERE psr.key_space = 'grid01_latlon'"
        )
    }


@dataclasses.dataclass(frozen=True)
class _IngestContext:
    """`_ingest()` が1行ごとの解決に使う宣言・参照集合（引数が増えたのでまとめた）。"""
    taxon_ids: set[str]
    alien_binoms: frozenset[str]
    sources: dict
    regions: dict
    source_usage: object
    region_usage: object
    shape_usage: object
    adapter_manifests: tuple = ()


def _ingest(
    work: sqlite3.Connection,
    dest: sqlite3.Connection,
    insert_table: str,
    ctx: _IngestContext,
) -> dict:
    """`organism_records` を1行ずつ読み、`insert_table` へ `executemany` で
    ストリーム挿入する（b03 の C-5 と同じ理由。823,692行を Python のリストに
    溜めない）。
    """
    stats = _empty_stats()
    edition_of = edition.make_resolver(work, "reg")  # その出典の唯一の版（解決できなければ止まる）

    taxon_ids, alien_binoms, sources, regions = ctx.taxon_ids, ctx.alien_binoms, ctx.sources, ctx.regions
    source_usage, region_usage, shape_usage = ctx.source_usage, ctx.region_usage, ctx.shape_usage

    def rows():
        for row in work.execute(_SELECT_ORGANISM_RECORDS_SQL):
            (
                source_row_id, record_id, source_id, observed_on, taxon_key,
                lat, lon, coordinate_uncertainty_m,
                scientific_name, vernacular_name, taxon_rank,
                red_list_category, red_list_source, is_alien, license_class, publication_scope,
                place_id, place_kind, is_synthetic, occurrence_status,
            ) = row
            # 原表記の旗 is_alien は変えない。n_alien（b07）は registry（環境省リスト＋除外規則）から
            # 導いたこちらを数える（原本の旗を遮蔽するのではなく置き換える）。
            is_alien_in_scope = 1 if binom_of(scientific_name) in alien_binoms else 0

            stats["total"] += 1

            source_region = sources.get(source_id)
            if source_region is None:
                raise source_regions.UnknownSourceRegionError(source_id)
            source_usage.mark_used(source_id)
            region_id = source_region.region_id
            region_usage.mark_used(region_id)

            # occurrence に入れない行（合成データ・不在記録・未知の状態）。宣言の使用マーキングは除外の行でも
            # 行った後（将来 source_id 丸ごとが除外対象だけになっても「宣言未使用」の誤検出にしないため）、
            # region_counts への計上・alias/place 解決より前に弾く（モジュール docstring の各節）。
            reason = _exclusion_reason(is_synthetic, occurrence_status)
            if reason is not None:
                _count_exclusion(stats, reason, source_id, record_id, occurrence_status)
                continue

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

            period_grain, period_start, period_end, period_raw = _period_fields(
                stats, shape_usage, observed_on, utc_offset, record_id
            )

            yield (
                record_id, "organism_records", source_row_id, source_id, region_id, taxon_id,
                place_id, place_kind, coordinate_uncertainty_m, lat, lon,
                period_grain, period_start, period_end, period_raw,
                scientific_name, vernacular_name, taxon_rank,
                red_list_category, is_alien, license_class, publication_scope,
                is_alien_in_scope,
                public_id.occurrence_id(record_id, source_id), edition_of(source_id), None,
                red_list_source,
            )

    runs = [ingest_runner.AdapterRun(m, work, taxon_ids) for m in ctx.adapter_manifests]
    grid01_places: dict | None = None

    def adapter_rows():
        """`scripts/adapters/` 経由の出現（非 builtin のマニフェスト）。organism_records と同じ後段
        （region・taxon 解決・place・期間）を通す。座標の無い記録は place_id NULL のまま落とさない
        （ADR-0007 原則 1。grid01 には入れず、b09/b07 が watershed の place_id NULL セルにだけ入れる）。"""
        nonlocal grid01_places
        for run in runs:
            m = run.manifest
            source_id = m.source
            source_region = sources[source_id]
            region_id = source_region.region_id
            utc_offset = regions[region_id].utc_offset
            source_table = next(iter(m.input.values()))
            for n, r in enumerate(run.rows(), start=1):
                stats["total"] += 1
                source_usage.mark_used(source_id)
                region_usage.mark_used(region_id)
                stats["region_counts"][region_id] = stats["region_counts"].get(region_id, 0) + 1
                record_id = f"{source_id}__{r.record_key}"

                taxon_id = r.taxon_id
                if taxon_id is None:
                    stats["taxon_null_count"] += 1
                    if r.observed_on_raw is not None:
                        stats["taxon_null_dated_count"] += 1
                elif taxon_id not in taxon_ids:
                    stats["unresolved_taxon_count"] += 1
                    if len(stats["unresolved_taxon_sample"]) < _SAMPLE_LIMIT:
                        stats["unresolved_taxon_sample"].append((record_id, taxon_id))
                    continue

                place_id = place_kind = None
                if r.lat is None:
                    stats["no_coordinate_count"] += 1
                else:
                    if grid01_places is None:
                        grid01_places = _load_grid01_places(work)
                    key = f"grid01:{math.floor(r.lat * 100)},{math.floor(r.lon * 100)}"
                    resolved = grid01_places.get(key)
                    if resolved is None:
                        stats["unresolved_place_count"] += 1
                        if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                            stats["unresolved_place_sample"].append((record_id, r.lat, r.lon))
                        continue
                    place_id, place_kind = resolved

                period_grain, period_start, period_end, period_raw = _period_fields(
                    stats, shape_usage, r.observed_on_raw, utc_offset, record_id
                )
                is_alien_in_scope = 1 if binom_of(r.scientific_name) in alien_binoms else 0
                yield (
                    record_id, source_table, n, source_id, region_id, taxon_id,
                    place_id, place_kind, r.coordinate_uncertainty_m, r.lat, r.lon,
                    period_grain, period_start, period_end, period_raw,
                    r.scientific_name, r.vernacular_name, r.taxon_rank,
                    r.red_list_category, None, r.license_class, None,
                    is_alien_in_scope,
                    public_id.adapter_occurrence_id(source_id, r.record_key), edition_of(source_id),
                    json.dumps(r.attributes, ensure_ascii=False, sort_keys=True) if r.attributes else None,
                    None,   # red_list_source: アダプタ経由の記録は出所を持たない
                )

    dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), rows())
    if runs:
        dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), adapter_rows())
        for run in runs:
            stats["adapter_counts"][run.manifest.source] = run.n_rows
            stats["adapter_attributes_count"][run.manifest.source] = run.n_attributes
            stats["adapter_problems"].extend(run.problems())
    stats["n_occurrence"] = stats["total"] - stats["synthetic_excluded_count"] - stats["absent_excluded_count"]
    return stats


def build_and_write_occurrence(
    ryuiki_db,
    registry_db,
    manifests_dir=DEFAULT_MANIFESTS_DIR,
    period_shapes_yaml=DEFAULT_PERIOD_SHAPES_YAML,
    out_path=DEFAULT_OUT,
    count_overlay_by_file: dict[str, dict[str, int]] | None = None,
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
    source_regions.validate_source_regions_shape(manifests_dir)
    occurrence_period.validate_occurrence_period_shapes_shape(period_shapes_yaml)

    # consumer="occurrence": P-1b で manifests/*.yml に土地利用
    # （consumer="observation"）の宣言が同居するようになったため、b06 が
    # 自分の使わない宣言を「未使用宣言」として誤検出しないように絞り込む
    # （scripts/migrate/source_regions.py モジュール docstring「consumer」節）。
    # `count_overlay_by_file`（既定 None）は Issue #29「縮小サンプル」用——
    # `--count-overlay` を渡さない本番の実行では常に None のまま。
    overlay = count_overlay_by_file or {}
    sources, regions = source_regions.load_source_regions(
        manifests_dir, consumer="occurrence", count_overlay=overlay.get("manifests")
    )
    source_usage = period.EntryUsage(sources)
    region_usage = period.EntryUsage(regions)
    shapes = occurrence_period.load_period_shapes(
        period_shapes_yaml, count_overlay=overlay.get("occurrence_period_shapes.yaml")
    )
    # 非 builtin のマニフェスト（adapter 経由の出現）の宣言値（`expected`）は yaml の宣言値に足して突合する
    # （ソース追加で scripts/migrate/ を触らない。J6）。既存出典の宣言は従来どおり yaml のまま。
    manifests = manifest_lib.apply_expected_overlay(
        manifest_lib.load_manifests(manifests_dir), overlay.get("manifests"))
    adapter_manifests = tuple(
        m for m in manifests.values() if m.target == "occurrence" and not m.is_builtin
    )
    shapes = _add_manifest_shape_counts(shapes, manifest_lib.expected_sums(manifests).period_shapes)
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
    # 系譜（Issue #45）: 読み取りから自動生成する（b03 と同じ）。
    work_external = {
        "src": common.ryuiki_external(ryuiki_db, extra_tables=common.manifest_inputs(manifests_dir)[0]),
        "reg": common.registry_external(registry_db),
    }
    try:
        with common.LineageTracker(dest) as lineage, common.staged_table(
            dest, "occurrence", _CREATE_OCCURRENCE_SQL, lineage=lineage,
        ) as staging:
            work = sqlite3.connect(":memory:", uri=True)
            try:
                common.attach_readonly(work, ryuiki_db, "src")
                common.attach_readonly(work, registry_db, "reg")
                lineage.watch(work, external=work_external)
                _assert_known_source_ids(work)
                _assert_organism_columns(work)
                taxon_ids = _load_taxon_ids(work)
                ctx = _IngestContext(
                    taxon_ids, _load_alien_binoms(work), sources, regions,
                    source_usage, region_usage, shape_usage, adapter_manifests,
                )
                stats = _ingest(work, dest, staging, ctx)
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
                _absent_excluded_problems(sources, stats["absent_excluded_by_source"])
                + period.declaration_problems(source_usage, "manifests/ (sources, target=occurrence)")
                + period.declaration_problems(region_usage, "manifests/ (regions, target=occurrence)")
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
            try:
                dest.execute(_CREATE_OCCURRENCE_ID_INDEX_SQL.format(table=f'"{staging}"'))
            except sqlite3.IntegrityError as e:
                raise common.MigrationError(
                    f"occurrence_id が一意でない（出典の key が重複している。ADR-0004）: {e}"
                ) from e
            dest.execute(_DROP_OCCURRENCE_ID_INDEX_SQL)

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
            # 作業用テーブルを本番名 "occurrence" に差し替え、同じ
            # トランザクションで指紋も記録する（Issue #37 #1・/code-review
            # 指摘の根本対応。`lineage=`——`occurrence` は基底
            # テーブルで、系譜は原本・registry の ext: 来歴だけ）。b07/b09 はこの指紋を見て「今の
            # occurrence から作った出力か」を検証する。
        # v2 パイプラインの入力＋コードの指紋（Issue #48 PR-0 /simplify 指摘1）:
        # `common.record_v2_input_fingerprint` の docstring 参照
        # （`pipeline_fingerprint.inputs` の系譜とは別の表）。
        common.record_v2_input_fingerprint(
            dest, common.compute_v2_input_fingerprint(ryuiki_db=ryuiki_db, registry_db=registry_db),
        )
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
    n_occurrence = stats["n_occurrence"]
    a(f"- `organism_records` 総行数: **{stats['total']:,}**")
    a(
        f"- 合成データ（`is_synthetic=1`）を除外した行数: "
        f"**{stats['synthetic_excluded_count']:,}**"
        "（本番に出さない。Issue #48 PR-0 オーナー決定。実測では常に0——"
        "`organism_records` に合成の出現記録は無い。将来行が増えても"
        "黙って通さないための防御）"
    )
    a(
        f"- 不在記録（`occurrence_status='ABSENT'`）を除外した行数: **{stats['absent_excluded_count']:,}**"
        "（原本には残す。出現として数えない。2026-10-07 オーナー決定・ADR-0025。出典別: "
        + (", ".join(f"`{k}` {v:,}" for k, v in sorted(stats["absent_excluded_by_source"].items())) or "なし")
        + "。マニフェストの `expected_absent_excluded_rows` と突合済み）"
    )
    a(
        f"- `occurrence` 行数: **{n_occurrence:,}**"
        "（合成データ・不在記録を除く全行を取り込む。ADR-0007原則1の例外——"
        "Issue #48 PR-0 オーナー決定）"
    )
    a(f"- 日付あり（`period_raw` NOT NULL）: **{stats['n_dated']:,}**")
    a(f"- 座標なし（`lat`/`lon` NULL）: **{stats['no_coordinate_count']:,}**")
    a(
        f"- `taxon_id` NULL: **{stats['taxon_null_count']:,}**"
        f"（うち日付あり: {stats['taxon_null_dated_count']:,}）"
    )
    if stats["adapter_counts"]:
        a("")
        a("## adapter 経由の出典（`manifests/*.yml` の `adapter` が builtin でないもの）")
        a("")
        a("| source_id | 取り込み行数 | attributes を持つ行 |")
        a("|---|---:|---:|")
        for sid, n in sorted(stats["adapter_counts"].items()):
            a(f"| `{sid}` | {n:,} | {stats['adapter_attributes_count'][sid]:,} |")
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
    parser.add_argument("--manifests-dir", default=str(DEFAULT_MANIFESTS_DIR))
    parser.add_argument("--period-shapes-yaml", default=str(DEFAULT_PERIOD_SHAPES_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--count-overlay", default=None,
        help="data/sample/declaration_counts.yaml のようなファイル。既定は使わない（本番の実行では"
        "常に None のまま、正本の expected_row_count で検証する。Issue #29「縮小サンプル」）",
    )
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    count_overlay_by_file = period.resolve_count_overlays(
        args.count_overlay, ("manifests", "occurrence_period_shapes.yaml"),
    )

    with common.timed_step("occurrence を構築して書き出し") as info:
        stats = build_and_write_occurrence(
            args.ryuiki_db, registry_db, args.manifests_dir, args.period_shapes_yaml, args.out,
            count_overlay_by_file,
        )
        info["n"] = stats["n_occurrence"]

    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(stats), encoding="utf-8")
    print(f"→ {report_path}")
    n_occurrence = stats["n_occurrence"]
    print(
        f"  occurrence: {n_occurrence:,}行（日付あり {stats['n_dated']:,}、"
        f"合成データ除外 {stats['synthetic_excluded_count']:,}、不在記録除外 {stats['absent_excluded_count']:,}）"
    )


if __name__ == "__main__":
    main()
