"""occurrence の region_id を出典（マニフェスト）から決める（`source_regions.yaml`。
ADR-0022 決定3・O-1 設計 v2 D1）。

`scripts/b03_build_observation.py` は `place_source_ref(source_id='sites.site_id')` →
`place.region_id` の経路で `observation.region_id` を決めている。occurrence は
`place` が `grid01`（県境という概念を持たない機械グリッド）にしか解決できないため、
同じ経路では region_id を決められない（ADR-0022 決定3が明記する既知の結合）。
そこで occurrence だけは出典（`organism_records.source_id`）から直接 region_id を
決める——`scripts/migrate/period_exceptions.yaml`/`time_label_conventions.yaml` と
同じ「宣言表 + 使用状況の追跡」の流儀（未知の出典・未使用宣言・件数不一致で止める）。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from .common import MigrationError, load_yaml
from .period import EntryUsage

DEFAULT_SOURCE_REGIONS_YAML = pathlib.Path(__file__).resolve().parent / "source_regions.yaml"

REQUIRED_SOURCE_KEYS = ("region_id", "expected_row_count", "evidence")
REQUIRED_REGION_KEYS = ("utc_offset", "evidence")

# `'+09:00'`/`'-05:30'` の形だけを許す（コードレビュー指摘1）。`_parse_utc_offset`
# （scripts/migrate/occurrence_period.py）は符号1文字＋2桁＋':'＋2桁だけを前提に
# 減算するため、`"09:00"`（符号無し）のような値を読むと符号判定が
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
    （`migrate.period.EntryUsage`——`RegionUsage`——が「未使用宣言」の検出に
    `SourceRegion`/`Region` のどちらも同じ形で扱えるように持つダミー属性で、
    regions 自体には件数の宣言が無い。`mismatched_expected_counts()` は
    `None` のエントリを素通りするので、regions では実質「未使用宣言」の
    検出だけが働く）。
    """

    region_id: str
    utc_offset: str
    evidence: str
    expected_row_count: int | None = None


def load_source_regions(
    path=DEFAULT_SOURCE_REGIONS_YAML,
) -> tuple[dict[str, SourceRegion], dict[str, Region]]:
    """`(sources, regions)` を返す。`sources` の全 `region_id` が `regions` に
    宣言されていることと、`regions` の `utc_offset` が `UTC_OFFSET_PATTERN`
    に一致することをここで検証する（黙って `KeyError` や符号違いの値を通さない）。
    """
    raw = load_yaml(path)
    sources_raw = raw.get("sources") or {}
    regions_raw = raw.get("regions") or {}

    bad_offsets: list[tuple[str, str]] = []
    regions: dict[str, Region] = {}
    for region_id, spec in regions_raw.items():
        utc_offset = spec["utc_offset"]
        if not UTC_OFFSET_PATTERN.fullmatch(utc_offset):
            bad_offsets.append((region_id, utc_offset))
        regions[region_id] = Region(
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

    missing_regions = sorted({s.region_id for s in sources.values()} - set(regions))
    if missing_regions:
        raise MigrationError(
            f"{path} の sources が参照する region_id が regions に宣言されていない: "
            f"{missing_regions}"
        )
    return sources, regions


def _validate_expected_row_count(label: str, spec: dict) -> str | None:
    """`expected_row_count` が「非負整数」であることを検証する（コードレビュー
    指摘6: `.get()` で黙って検査を外さない）。問題が無ければ `None`。
    """
    value = spec.get("expected_row_count")
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{label}: expected_row_count が整数でない（実際: {value!r}）"
    if value < 0:
        return f"{label}: expected_row_count が負の数（実際: {value!r}）"
    return None


def validate_source_regions_shape(path=DEFAULT_SOURCE_REGIONS_YAML) -> None:
    """`source_regions.yaml` の形（`sources`/`regions` それぞれの必須キー・
    `sources` の `expected_row_count` が整数・`regions` の `utc_offset` の形）を
    検証する（原本DBを一切必要としない構造検証。CI 用）。
    """
    raw = load_yaml(path)
    problems: list[str] = []

    sources = raw.get("sources")
    if sources is None:
        sources = {}
    if not isinstance(sources, dict):
        problems.append(f"sources: マッピングになっていない（実際の型: {type(sources).__name__}）")
    else:
        for source_id, spec in sources.items():
            if not isinstance(spec, dict):
                problems.append(f"sources.{source_id}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
                continue
            missing = [k for k in REQUIRED_SOURCE_KEYS if spec.get(k) in (None, "")]
            if missing:
                problems.append(f"sources.{source_id}: 必須キーが欠けている（または空）: {missing}")
                continue
            count_problem = _validate_expected_row_count(f"sources.{source_id}", spec)
            if count_problem:
                problems.append(count_problem)

    regions = raw.get("regions")
    if regions is None:
        regions = {}
    if not isinstance(regions, dict):
        problems.append(f"regions: マッピングになっていない（実際の型: {type(regions).__name__}）")
    else:
        for region_id, spec in regions.items():
            if not isinstance(spec, dict):
                problems.append(f"regions.{region_id}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
                continue
            missing = [k for k in REQUIRED_REGION_KEYS if spec.get(k) in (None, "")]
            if missing:
                problems.append(f"regions.{region_id}: 必須キーが欠けている（または空）: {missing}")
                continue
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


# `SourceRegionUsage`/`RegionUsage` は `migrate.period.EntryUsage`（`source_id`/
# `region_id` の使用状況を追跡する汎用トラッカー）への別名（B-3 と同じ判断。
# scripts/b06_build_occurrence.py が sources 用・regions 用にそれぞれ1つずつ作る）。
SourceRegionUsage = EntryUsage
RegionUsage = EntryUsage
