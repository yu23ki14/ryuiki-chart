"""adapter が import してよい**唯一の面**（Issue #40 Phase D、ADR-0012 改定）。

`scripts/adapters/<source_id>.py` は `def rows(ctx) -> Iterator[dict]` を公開し、import してよいのは
**このモジュールと標準ライブラリだけ**（`scripts/tests/test_adapter_boundary.py` が AST で固定する。
`migrate`・`registry`・`sqlite3` を直接 import して共通検査〔重複・解決率・期間・checks・宣言突合〕を
迂回する経路を塞ぐ）。

adapter は 1 行ごとに `ingest.api.occurrence_row(...)` を `yield` する。入力（原本の表・CSV）は
`ctx.input_rows()` でしか読めない（読み取り専用の dict の列。DB 接続は渡さない）。

## occurrence の列契約

- `record_key`（必須・出典内で一意の文字列。公開 ID の元になる）
- `taxon_id`（`common:taxon:…`。registry に実在すること。無ければ None）
- `observed_on_raw`（原表記。`occurrence_period_shapes.yaml` の 12 形のどれか。無ければ None）
- `lat`/`lon`（どちらも数値、またはどちらも None。**座標を補完しない**＝推測で埋めない）
- 任意: `scientific_name`/`vernacular_name`/`taxon_rank`/`red_list_category`/`license_class`
- `attributes`（出典固有の補助情報の dict。JSON 文字列として `occurrence.attributes` に保存される。無ければ NULL。
  D1 には L2 を入れないが dist には載る。値は JSON にできるもの〔文字列・数値・真偽・None・リスト・dict〕に限る）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator

ROW_COLUMNS = ("record_key", "taxon_id", "observed_on_raw", "lat", "lon")
OPTIONAL_COLUMNS = (
    "scientific_name", "vernacular_name", "taxon_rank", "red_list_category", "license_class", "attributes",
)


class AdapterError(Exception):
    """adapter が契約を破ったとき（ランナーが捕まえて取り込みを止める）。"""


@dataclass(frozen=True)
class Ctx:
    """adapter に渡す文脈。`input_rows()` が入力を 1 行ずつ dict で返す（ランナーが提供する読み取り専用の窓）。"""
    source_id: str
    region_id: str
    input_rows: Callable[[], Iterator[dict]]


def occurrence_row(
    record_key,
    *,
    taxon_id=None,
    observed_on_raw=None,
    lat=None,
    lon=None,
    scientific_name=None,
    vernacular_name=None,
    taxon_rank=None,
    red_list_category=None,
    license_class=None,
    attributes=None,
) -> dict:
    """occurrence の 1 行（列契約の dict）。型・組の検査はランナーが行う。"""
    return {
        "record_key": record_key, "taxon_id": taxon_id, "observed_on_raw": observed_on_raw,
        "lat": lat, "lon": lon,
        "scientific_name": scientific_name, "vernacular_name": vernacular_name, "taxon_rank": taxon_rank,
        "red_list_category": red_list_category, "license_class": license_class,
        "attributes": dict(attributes) if attributes else {},
    }
