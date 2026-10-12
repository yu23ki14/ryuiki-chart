"""モニタリングサイト1000 里地調査 鳥類調査（原本 `moni1000_counts` の source_id=moni1000_satochi_bird）→ occurrence（docs/plans/MONI1000.md §3）。

import は `ingest.api` だけ（boundary.py）。入力表は全出典で共有なので、自出典かつ `in_occurrence=1` の行だけを返す
（個体数 0・名寄せ不能・非野生は m10 が `in_occurrence=0` にした行。生の表には残る）。
座標は出典の値のまま渡し（丸め・補完をしない）、精度（`coordinate_uncertainty_m`）は m10 が小数桁数から計算した列をそのまま渡す。
個体数は attributes に残し、occurrence の n（記録の行数）には使わない（ADR-0025。n は個体数ではない）。
"""
from __future__ import annotations

from ingest.api import occurrence_row

SOURCE = "moni1000_satochi_bird"

_ATTRIBUTE_KEYS = (
    "survey_id", "site_key", "site_name_ja", "place_id", "season_ja", "survey_round", "section_ja",
    "individual_count", "individual_count_raw", "count_qualifier", "id_note_ja", "out_of_range", "out_of_time",
    "start_time",
)


def rows(ctx):
    for r in ctx.input_rows():
        if r["source_id"] != SOURCE or r["in_occurrence"] != 1:
            continue
        has_xy = r["lat"] is not None and r["lon"] is not None
        yield occurrence_row(
            r["record_id"],
            taxon_id=r["taxon_id"],
            observed_on_raw=r["observed_on"],
            lat=r["lat"] if has_xy else None,
            lon=r["lon"] if has_xy else None,
            coordinate_uncertainty_m=r["coordinate_uncertainty_m"] if has_xy else None,
            scientific_name=r["scientific_name"],
            vernacular_name=r["species_ja"],
            attributes={k: r[k] for k in _ATTRIBUTE_KEYS},
        )
