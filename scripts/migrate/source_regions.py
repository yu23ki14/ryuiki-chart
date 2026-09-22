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
from dataclasses import dataclass

from .common import MigrationError, load_yaml
from .period import EntryUsage

DEFAULT_SOURCE_REGIONS_YAML = pathlib.Path(__file__).resolve().parent / "source_regions.yaml"

REQUIRED_SOURCE_KEYS = ("region_id", "expected_row_count", "evidence")
REQUIRED_REGION_KEYS = ("utc_offset", "evidence")


@dataclass(frozen=True)
class SourceRegion:
    """`sources:` の1エントリ。"""

    source_id: str
    region_id: str
    expected_row_count: int | None
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


def _load_raw(path) -> dict:
    return load_yaml(path)


def load_source_regions(
    path=DEFAULT_SOURCE_REGIONS_YAML,
) -> tuple[dict[str, SourceRegion], dict[str, Region]]:
    """`(sources, regions)` を返す。`sources` の全 `region_id` が `regions` に
    宣言されていることをここで検証する（黙って `KeyError` にしない）。
    """
    raw = _load_raw(path)
    sources_raw = raw.get("sources") or {}
    regions_raw = raw.get("regions") or {}

    regions: dict[str, Region] = {
        region_id: Region(
            region_id=region_id,
            utc_offset=spec["utc_offset"],
            evidence=spec.get("evidence", ""),
        )
        for region_id, spec in regions_raw.items()
    }
    sources: dict[str, SourceRegion] = {
        source_id: SourceRegion(
            source_id=source_id,
            region_id=spec["region_id"],
            expected_row_count=spec.get("expected_row_count"),
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


def _validate_section_shape(path, raw: dict, section: str, required_keys: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    entries = raw.get(section)
    if entries is None:
        entries = {}
    if not isinstance(entries, dict):
        return [f"{section}: マッピング（{{キー: {{...}}}}）になっていない（実際の型: {type(entries).__name__}）"]
    for key, spec in entries.items():
        if not isinstance(spec, dict):
            problems.append(f"{section}.{key}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
            continue
        missing = [k for k in required_keys if spec.get(k) in (None, "")]
        if missing:
            problems.append(f"{section}.{key}: 必須キーが欠けている（または空）: {missing}")
    return problems


def validate_source_regions_shape(path=DEFAULT_SOURCE_REGIONS_YAML) -> None:
    """`source_regions.yaml` の形（`sources`/`regions` それぞれの必須キー）を検証する
    （原本DBを一切必要としない構造検証。CI 用。`migrate.period._validate_shape` と
    同じ流儀）。
    """
    raw = _load_raw(path)
    problems = _validate_section_shape(path, raw, "sources", REQUIRED_SOURCE_KEYS)
    problems += _validate_section_shape(path, raw, "regions", REQUIRED_REGION_KEYS)
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
