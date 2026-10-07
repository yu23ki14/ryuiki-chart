"""神奈川県「環境DNAのページ」eDNA 調査結果（原本の投影 `edna_detections`）→ occurrence（docs/plans/KANAGAWA_EDNA.md §3）。

import は `ingest.api` と標準の `json` だけ。入力の `edna_detections` は m07 が組んだ「検出（リード数 > 0）だけ」の
投影で、種の解決（`taxon_id`）・座標（地点の推定位置と精度）・attributes は m07 までで確定している。adapter は写すだけ。

- 座標は公開データに無い。地点ごとの推定位置（台帳）を、精度（`coordinate_uncertainty_m`）つきで渡す。判別不能な地点は両方 NULL。
- 日付が空欄の行は observed_on NULL のまま取り込む（落とさない・補わない）。
- 値はリード数で、個体数ではない（`individual_count` は無い。ADR-0025 に従い n は記録数）。リード数は attributes に残る。
"""
from __future__ import annotations

import json

from ingest.api import occurrence_row


def rows(ctx):
    for r in ctx.input_rows():
        yield occurrence_row(
            r["record_key"],
            taxon_id=r["taxon_id"],
            observed_on_raw=r["observed_on"],
            lat=r["lat"],
            lon=r["lon"],
            coordinate_uncertainty_m=r["coordinate_uncertainty_m"],
            scientific_name=r["scientific_name"],
            vernacular_name=r["vernacular_name"],
            taxon_rank=r["taxon_rank"],
            red_list_category=r["red_list_category"],
            attributes=json.loads(r["attributes_json"]),
        )
