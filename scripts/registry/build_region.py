"""region（時刻帯の語彙）を作る（Issue #32-3、ADR-0002・ADR-0024）。

`registry/region.yaml` を読んで `region` 表に入れるだけ（原本 DB には触れない。`src` は
シグネチャ互換のため受け取るが使わない）。パイプライン側は `scripts/migrate/regions.py` が
同じファイルを直接読む（形の検証も同じ関数）。
"""
from __future__ import annotations

import sqlite3
import sys

from . import common

sys.path.insert(0, str(common.ROOT / "scripts"))
from migrate import regions as region_vocab  # noqa: E402


def build_from_files(conn: sqlite3.Connection) -> dict[str, int]:
    regions = region_vocab.load_regions(common.ROOT / "registry" / "region.yaml")
    rows = [
        (r.region_id, r.name_ja, r.tz_name, r.utc_offset, r.evidence)
        for r in sorted(regions.values(), key=lambda r: r.region_id)
    ]
    n = common.insert_many(conn, "region", ["region_id", "name_ja", "tz_name", "utc_offset", "evidence"], rows)
    return {"region": n}


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection] | None = None) -> dict[str, int]:
    return build_from_files(conn)
