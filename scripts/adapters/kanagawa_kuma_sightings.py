"""神奈川県ツキノワグマ出没・目撃記録（原本 `wildlife_sightings`）→ occurrence（Issue #40 Phase D 担当 S）。

import は `ingest.api` だけ。種は 1 種（ツキノワグマ）なので `taxon_id` は定数。
座標は原本に無い（400/400 が NULL）。補完しない（推測で埋めない）。出典固有の項目は attributes に載せる。
`individual_count` は採用しない（出現の列に無い。ADR-0025 に従い n は記録数）。
"""
from __future__ import annotations

from ingest.api import occurrence_row

# registry の taxon から `canonical_binomial='Ursus thibetanus'` かつ `rank='species'` かつ
# `scientific_name` が canonical_binomial と一致するもの（機械的に 1 件に決まる）。
# gbif.9335699 は species だが scientific_name が「Ursus thibetanus G」で一致しない。
TAXON_ID = "common:taxon:inat.41647"


def rows(ctx):
    for r in ctx.input_rows():
        yield occurrence_row(
            r["sighting_id"],
            taxon_id=TAXON_ID,
            observed_on_raw=r["observed_on"],
            lat=r["lat"],
            lon=r["lon"],
            attributes={
                "situation_ja": r["situation_ja"],
                "area_kind_ja": r["area_kind_ja"],
                "is_preliminary": bool(r["is_preliminary"]),
                "locality_ja": r["locality_ja"],
            },
        )
