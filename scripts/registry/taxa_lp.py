"""`ryuiki.taxa` の行が「地域個体群（LP）の名称」かどうかの判定（Issue #75）。

`build_taxon.py`（和名）と `build_taxon_assessment.py`（`vernacular_name_ja_resolved`）が
同じ述語を使う（判定を1か所に置く）。

判定は3つの条件の AND:

1. **区分**: `redlist_national`/`redlist_kanagawa` のどちらかが「地域個体群」（LP）。
   名称の文字列だけでは決めない（出典の属性を先に見る）。
2. **学名がある**: 学名の無い行（`wamei:*`。和名だけの行）は対象外。そこの和名
   （`ツキノワグマ`・`トビハゼ` 等）は LP 区分でも種名そのもので、LP 区分は環境省 LP の
   掲載名と和名の照合で付いた属性にすぎない。`wamei:ニホンザルの西湘地域個体群` のような
   集団名の行も、学名が無いので種・亜種の和名の候補にならず、今のまま taxon に残る。
3. **名称に限定が付いている**: 環境省の LP の掲載名は「<地域の限定>の<種名>」（西中国地域の
   ツキノワグマ・馬毛島のニホンジカ）か「…個体群/集団/系群」の形（実データの LP 47行の
   和名は全て「の」を含む。2026-10-07 実測）。`の` を含む、または 個体群・集団・系群 を
   含む名称を限定付きとみる。LP 区分でも限定語の無い名称（種名そのもの）は和名として残す。
   `の` を含む種名（例: ヤマノイモ）が LP 区分と重なった場合は誤って除外しうるが、
   その場合は和名が空になるだけで（override・records で補える）誤った名前は付かない。
"""

from __future__ import annotations

LP_MARK = "地域個体群"
_POPULATION_MARKERS = ("の", "個体群", "集団", "系群")


def is_lp_population_name(
    redlist_national: str | None,
    redlist_kanagawa: str | None,
    scientific_name: str | None,
    vernacular_name_ja: str | None,
) -> bool:
    """`taxa` 行の `vernacular_name_ja` が地域個体群の名称なら True。"""
    if not (scientific_name or "").strip() or not vernacular_name_ja:
        return False
    if LP_MARK not in (redlist_national or "") and LP_MARK not in (redlist_kanagawa or ""):
        return False
    return any(m in vernacular_name_ja for m in _POPULATION_MARKERS)
