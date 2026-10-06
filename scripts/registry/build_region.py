"""region（時刻帯の語彙）を作る（Issue #32-3、ADR-0002・ADR-0024）。

`registry/region.yaml` を `scripts/migrate/regions.py`（パイプライン側と共有する読み込み・形の検証）
で読み、`region` 表に入れるだけ。原本 DB には触れない（`src` は他のビルダーとの形を揃えるための
引数で使わない。`--files-only` でもそのまま動く）。
"""
from __future__ import annotations

import sqlite3
import sys

from . import common

sys.path.insert(0, str(common.ROOT / "scripts"))
from migrate import regions as region_vocab  # noqa: E402


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection] | None = None) -> dict[str, int]:
    rows = [
        (r.region_id, r.name_ja, r.tz_name, r.utc_offset, r.evidence)
        for r in sorted(region_vocab.load_regions().values(), key=lambda r: r.region_id)
    ]
    n = common.insert_many(conn, "region", ["region_id", "name_ja", "tz_name", "utc_offset", "evidence"], rows)
    return {"region": n}
