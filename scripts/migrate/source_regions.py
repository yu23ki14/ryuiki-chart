"""出典（マニフェスト）から region_id を決める（`source_regions.yaml`。
ADR-0022 決定3・O-1 設計 v2 D1）。

`scripts/b03_build_observation.py` の `measurements`/`sensor_timeseries` は
`place_source_ref(source_id='sites.site_id')` → `place.region_id` の経路で
`observation.region_id` を決めている。occurrence（grid01。県境という概念を
持たない機械グリッド）や、P-1b で足した土地利用（watershed。common スコープ
なので `place.region_id` は常に NULL）は、この経路では region_id を決められない
（ADR-0022 決定3が明記する既知の結合）。そこでこの2つは出典
（`organism_records.source_id`/CSV の `source_id`）から直接 region_id を
決める——`scripts/migrate/period_exceptions.yaml`/`time_label_conventions.yaml` と
同じ「宣言表 + 使用状況の追跡」の流儀（未知の出典・未使用宣言・件数不一致で止める）。

## consumer（P-1b で追加）

`source_regions.yaml` の `sources:` は複数の消費者（occurrence=
`scripts/b06_build_occurrence.py`、observation=`scripts/b03_build_observation.py`）が
同じファイルを共有する。各消費者は自分が使う出典だけを見たいが、
`period.EntryUsage`／`declaration_problems()` は「宣言されているのに1件も
使われなかったエントリ」を機械的に検出する仕組みを持つ——ある消費者が
**他の消費者向けの宣言**まで見てしまうと、その宣言を自分が使わないことを
「未使用宣言」の異常として誤検出してしまう。

`load_source_regions(path, consumer=...)` の `consumer` 引数は、返す
`sources`（と、それが参照する `regions` のうち実際に使われる分）を
その消費者向けの宣言だけに絞り込む。`sources.<id>.consumer` を省略した
エントリは `_DEFAULT_CONSUMER`（`"occurrence"`。最初の消費者だったため）
として扱う——既存の宣言・既存のテストフィクスチャに `consumer` を書き足す
義務を課さないための後方互換。`consumer=None`（既定）を渡した場合は
絞り込みをしない（ファイル全体をそのまま返す。CI の構造検証や、
消費者を問わない一覧が要る場面向け）。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from . import period
from .common import MigrationError, load_yaml

DEFAULT_SOURCE_REGIONS_YAML = pathlib.Path(__file__).resolve().parent / "source_regions.yaml"

REQUIRED_SOURCE_KEYS = ("region_id", "expected_row_count", "evidence")
REQUIRED_REGION_KEYS = ("utc_offset", "evidence")

# `sources.<id>.consumer` の既定値（省略時）。occurrence が最初の消費者だった
# ため、後方互換としてこれを既定にする（モジュール docstring「consumer」節）。
_DEFAULT_CONSUMER = "occurrence"

# `consumer` が取りうる値のコードリスト（`scripts/registry/build_unit_variable.py`
# の `GRAIN_CODES`/`STAT_CODES` と同じ考え方——このリストに無い値が来たら
# ビルドを落とす）。
CONSUMER_CODES = frozenset({"occurrence", "observation"})

# `'+09:00'`/`'-05:30'` の形だけを許す（コードレビュー指摘1）。`period._parse_utc_offset`
# （時刻帯の扱いは `scripts/migrate/period.py` の `_strip_tz` の隣に集約。
# /simplify 指摘2）は符号1文字＋2桁＋':'＋2桁だけを前提に減算するため、
# `"09:00"`（符号無し）のような値を読むと符号判定が
# `sign = 1 if s[0]=='+' else -1` で黙って `-1`（負）に倒れる事故が起きる。
# 読み込み時（ここ）と構造検証（CI）の両方で同じ正規表現を使う。
UTC_OFFSET_PATTERN = re.compile(r"^[+-][0-9]{2}:[0-9]{2}$")


@dataclass(frozen=True)
class SourceRegion:
    """`sources:` の1エントリ。"""

    source_id: str
    region_id: str
    expected_row_count: int
    evidence: str


@dataclass(frozen=True)
class Region:
    """`regions:` の1エントリ。`expected_row_count` は常に `None`
    （`migrate.period.EntryUsage` が「未使用宣言」の検出に `SourceRegion`/
    `Region` のどちらも同じ形で扱えるように持つダミー属性で、regions 自体には
    件数の宣言が無い。`mismatched_expected_counts()` は `None` のエントリを
    素通りするので、regions では実質「未使用宣言」の検出だけが働く）。
    """

    region_id: str
    utc_offset: str
    evidence: str
    expected_row_count: int | None = None


def load_source_regions(
    path=DEFAULT_SOURCE_REGIONS_YAML,
    consumer: str | None = None,
) -> tuple[dict[str, SourceRegion], dict[str, Region]]:
    """`(sources, regions)` を返す。`sources` の全 `region_id` が `regions` に
    宣言されていることと、`regions` の `utc_offset` が `UTC_OFFSET_PATTERN`
    に一致することをここで検証する（黙って `KeyError` や符号違いの値を通さない）。

    `consumer` を渡すと、`sources` を `spec.get("consumer", _DEFAULT_CONSUMER)
    == consumer` の行だけに絞り込み、`regions` もその絞り込んだ `sources` が
    実際に参照する `region_id` だけに絞る（モジュール docstring「consumer」節）。
    `consumer=None`（既定）なら絞り込まず、ファイル全体をそのまま返す
    （呼び出し側で `EntryUsage` の対象を消費者ごとに正しく分けられるように
    するための機能で、`consumer` を渡さない既存の呼び出し・既存のテストの
    挙動は一切変えない）。
    """
    raw = load_yaml(path)
    sources_raw = raw.get("sources") or {}
    regions_raw = raw.get("regions") or {}

    if consumer is not None:
        sources_raw = {
            source_id: spec
            for source_id, spec in sources_raw.items()
            if spec.get("consumer", _DEFAULT_CONSUMER) == consumer
        }

    bad_offsets: list[tuple[str, str]] = []
    all_regions: dict[str, Region] = {}
    for region_id, spec in regions_raw.items():
        utc_offset = spec["utc_offset"]
        if not UTC_OFFSET_PATTERN.fullmatch(utc_offset):
            bad_offsets.append((region_id, utc_offset))
        all_regions[region_id] = Region(
            region_id=region_id,
            utc_offset=utc_offset,
            evidence=spec.get("evidence", ""),
        )
    if bad_offsets:
        raise MigrationError(
            f"{path} の regions.<region_id>.utc_offset が想定外の形"
            f"（'+HH:MM'/'-HH:MM' のみ対応）: {bad_offsets}"
        )

    sources: dict[str, SourceRegion] = {
        source_id: SourceRegion(
            source_id=source_id,
            region_id=spec["region_id"],
            expected_row_count=spec["expected_row_count"],
            evidence=spec.get("evidence", ""),
        )
        for source_id, spec in sources_raw.items()
    }

    missing_regions = sorted({s.region_id for s in sources.values()} - set(all_regions))
    if missing_regions:
        raise MigrationError(
            f"{path} の sources が参照する region_id が regions に宣言されていない: "
            f"{missing_regions}"
        )

    if consumer is None:
        regions = all_regions
    else:
        # 絞り込んだ sources が実際に参照する region だけに絞る——他の消費者
        # 向けの region まで渡すと、この consumer の EntryUsage がそれを
        # 「未使用宣言」として誤検出してしまう（モジュール docstring 参照）。
        used_region_ids = {s.region_id for s in sources.values()}
        regions = {rid: r for rid, r in all_regions.items() if rid in used_region_ids}

    return sources, regions


def validate_source_regions_shape(path=DEFAULT_SOURCE_REGIONS_YAML) -> None:
    """`source_regions.yaml` の形（`sources`/`regions` それぞれの必須キー・
    `sources` の `expected_row_count` が整数・`regions` の `utc_offset` の形）を
    検証する（原本DBを一切必要としない構造検証。CI 用）。

    必須キーの検査は `period.required_keys_problems()`（`sources`/`regions`
    それぞれに1回ずつ）に委ね、`expected_row_count`/`utc_offset` の形式検査は
    必須キーが揃ったエントリ（`period.entries_with_required_keys()`）だけに
    行う——必須キー自体が欠けているエントリを二重に報告しないため
    （/simplify 指摘6）。

    `consumer` は必須キーにしていない（省略時は `_DEFAULT_CONSUMER` として
    扱う。後方互換）が、書かれているなら `CONSUMER_CODES` の値でなければ
    ならない（推測で新しい消費者名を発明させない）。
    """
    raw = load_yaml(path)
    problems: list[str] = []

    sources = raw.get("sources")
    if sources is None:
        sources = {}
    if not isinstance(sources, dict):
        problems.append(f"sources: マッピングになっていない（実際の型: {type(sources).__name__}）")
        sources = {}
    problems += period.required_keys_problems(sources, REQUIRED_SOURCE_KEYS, label_prefix="sources.")
    for source_id, spec in period.entries_with_required_keys(sources, REQUIRED_SOURCE_KEYS).items():
        count_problem = period.validate_expected_row_count(f"sources.{source_id}", spec)
        if count_problem:
            problems.append(count_problem)
        if "consumer" in spec and spec["consumer"] not in CONSUMER_CODES:
            problems.append(
                f"sources.{source_id}.consumer が未知の値: {spec['consumer']!r}"
                f"（コードリスト: {sorted(CONSUMER_CODES)}）"
            )

    regions = raw.get("regions")
    if regions is None:
        regions = {}
    if not isinstance(regions, dict):
        problems.append(f"regions: マッピングになっていない（実際の型: {type(regions).__name__}）")
        regions = {}
    problems += period.required_keys_problems(regions, REQUIRED_REGION_KEYS, label_prefix="regions.")
    for region_id, spec in period.entries_with_required_keys(regions, REQUIRED_REGION_KEYS).items():
        utc_offset = spec.get("utc_offset")
        if not isinstance(utc_offset, str) or not UTC_OFFSET_PATTERN.fullmatch(utc_offset):
            problems.append(
                f"regions.{region_id}: utc_offset が想定外の形"
                f"（'+HH:MM'/'-HH:MM' のみ対応。実際: {utc_offset!r}）"
            )

    if problems:
        raise MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))


class UnknownSourceRegionError(MigrationError):
    """`organism_records.source_id` が `source_regions.yaml` の `sources` に
    宣言されていないときに投げる。1行だけの問題ではなく構造的な設定不足なので、
    `scripts/b06_build_occurrence.py` の per-row 集計を素通りしてすぐに止まる。
    """

    def __init__(self, source_id: str | None):
        self.source_id = source_id
        super().__init__(
            f"organism_records.source_id={source_id!r} が "
            "scripts/migrate/source_regions.yaml の sources に宣言されていない。"
            "region_id を決められない。新しい出典が増えた場合は宣言を追記すること。"
        )
