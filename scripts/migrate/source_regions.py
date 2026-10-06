"""出典（マニフェスト）から region_id を決める（ADR-0022 決定3・Issue #40 Phase D）。

かつては `scripts/migrate/source_regions.yaml`（ADR-0012 の `region:` 欄の先取り）が持っていた宣言を、
`manifests/<source_id>.yml`（`scripts/ingest/manifest.py`）に吸収した。このモジュールは、b03/b06/s01 が
従来と同じ形（`SourceRegion`・`load_source_regions(consumer=…)`・`EntryUsage` での使用状況の追跡）で
マニフェストの `region`/`expected_row_count`/`evidence` を読むための薄い層として残してある。

## 決め方（ADR-0022 決定3、Phase D で統一）

`observation.region_id`/`occurrence.region_id` は**どちらも出典（マニフェスト）の `region` から決める**。
place 経由（`place.region_id`）は決定の根拠ではなく**照合**に格下げした（b03 が、place が region を持つ行で
マニフェストの region と食い違えば止まる）。未知の出典・宣言はあるが 1 行も現れなかった出典（未使用宣言）・
実測件数が `expected_row_count` と食い違う場合はいずれも、その出典を読む b0x スクリプトを止める
（`scripts/migrate/period_exceptions.yaml` と同じ流儀）。

## consumer

マニフェストの `target`（`observation`|`occurrence`）。各消費者は自分が使う出典だけを見たいので、
`load_source_regions(path, consumer=...)` は `target` が一致するマニフェストだけを返す
（`regions` も、その出典が参照する region だけ）。他の消費者向けの宣言まで見ると、それを使わないことを
「未使用宣言」と誤検出する。`consumer=None` はファイル全体（CI の構造検証・一覧向け）。

## expected_row_count

`adapter: builtin` の measurements/sensor_timeseries の出典は件数宣言を持たない（`None`。件数は
`period_exceptions.yaml` 等の別の宣言が見ている）ので、`EntryUsage` は件数の突合をしない（`None` は素通し）。

**regions（時刻帯）は `registry/region.yaml` が正**（Issue #32-3。ADR-0024）。
"""
from __future__ import annotations

from dataclasses import dataclass

from ingest import manifest as manifest_lib

from . import period, regions as region_vocab
from .common import MigrationError

DEFAULT_MANIFESTS_DIR = manifest_lib.DEFAULT_MANIFESTS_DIR
DEFAULT_REGION_YAML = region_vocab.DEFAULT_REGION_YAML

# `consumer` が取りうる値のコードリスト（= マニフェストの `target`）。
CONSUMER_CODES = frozenset(manifest_lib.TARGET_CODES)


@dataclass(frozen=True)
class SourceRegion:
    """マニフェスト 1 件の region 宣言。`consumer` はマニフェストの `target`。"""

    source_id: str
    region_id: str
    consumer: str
    expected_row_count: int | None
    evidence: str


def load_source_regions(
    path=DEFAULT_MANIFESTS_DIR,
    consumer: str | None = None,
    count_overlay: dict[str, int] | None = None,
    regions_path=DEFAULT_REGION_YAML,
) -> tuple[dict[str, SourceRegion], dict[str, region_vocab.RegionTime]]:
    """`(sources, regions)` を返す。`path` は `manifests/` ディレクトリ。`regions` は
    `registry/region.yaml`（`regions_path`）から読む。`sources` の全 region が region.yaml に宣言されている
    ことをここで検証する（黙って `KeyError` を通さない）。

    `consumer` を渡すと `target == consumer` のマニフェストだけに絞り、`regions` もその出典が参照する
    region だけに絞る（モジュール docstring「consumer」節）。

    `count_overlay`（既定 None）は `expected_row_count` だけを差し替える（`period.apply_count_overlay()`。
    Issue #29「縮小サンプル」）。件数宣言を持たないマニフェストを overlay が指せば `KeyError` で止まる。
    """
    manifests = manifest_lib.load_manifests(path)
    sources_raw = {
        sid: {
            "region_id": m.region, "consumer": m.target, "evidence": m.evidence,
            **({"expected_row_count": m.expected_row_count} if m.expected_row_count is not None else {}),
        }
        for sid, m in manifests.items()
    }
    if count_overlay:
        sources_raw = period.apply_count_overlay(sources_raw, count_overlay)

    all_regions = region_vocab.load_regions(regions_path)
    all_sources: dict[str, SourceRegion] = {
        sid: SourceRegion(
            source_id=sid, region_id=spec["region_id"], consumer=spec["consumer"],
            expected_row_count=spec.get("expected_row_count"), evidence=spec["evidence"],
        )
        for sid, spec in sources_raw.items()
    }

    missing_regions = sorted({s.region_id for s in all_sources.values()} - set(all_regions))
    if missing_regions:
        raise MigrationError(
            f"{path} のマニフェストが参照する region が {regions_path}（registry/region.yaml）に"
            f"宣言されていない: {missing_regions}"
        )

    if consumer is None:
        return all_sources, all_regions
    sources = {sid: s for sid, s in all_sources.items() if s.consumer == consumer}
    used_region_ids = {s.region_id for s in sources.values()}
    return sources, {rid: r for rid, r in all_regions.items() if rid in used_region_ids}


def validate_source_regions_shape(path=DEFAULT_MANIFESTS_DIR) -> None:
    """マニフェストの構造検証（原本 DB 不要。CI 用）。`scripts/ingest/manifest.py` に委ねる。"""
    manifest_lib.validate_manifests_shape(path)


class UnknownSourceRegionError(MigrationError):
    """出典が `manifests/` に宣言されていないときに投げる。1 行だけの問題ではなく構造的な設定不足なので、
    b03/b06 の per-row 集計を素通りしてすぐに止まる。
    """

    def __init__(self, source_id: str | None):
        self.source_id = source_id
        super().__init__(
            f"source_id={source_id!r} が manifests/ に宣言されていない。"
            "region_id を決められない。新しい出典が増えた場合は manifests/<source_id>.yml を追加すること。"
        )
