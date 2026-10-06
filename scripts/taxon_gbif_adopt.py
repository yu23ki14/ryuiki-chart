"""GBIF の弱い一致（HIGHERRANK/FUZZY）を自動採用してよいかの判定（Issue #34 D3）。

標準ライブラリだけに依存する（`scripts/common.py` は requests に依存するため、判定の
純粋な部分はここに切り出してテストできるようにした。`scripts/taxon_namespaces.py` と同じ流儀）。
`scripts/c26_taxon_gbif_accepted.py` が使う。

自動採用してよいのは次の3つをすべて満たすときだけ（それ以外は unresolved のまま理由区分を残す）:

1. 学名の正規形が完全一致する: 問い合わせ名（著者・年を除いた属+種小名〔+亜種以下〕）と GBIF の
   `canonicalName`（ランク記号を除いたもの）が同じ文字列で、matchType が EXACT。
2. 返ったランクが種以下（SPECIES/SUBSPECIES/VARIETY/FORM）。
3. 候補が1つ: `alternatives` に同じ正規形・種以下のランクの別候補が無い。

理由区分（`weak_reason`）:
- `genus_or_higher`: 問い合わせ名が属以上（`spp.`・`sp.`・種小名なし）
- `annotated_name`: 著者名として読めない注記を含む（全角括弧の別名併記など）
- `fuzzy_spelling`: GBIF が綴りの違いで合わせた（matchType FUZZY）
- `infraspecific_collapsed`: 亜種以下を含む名前が、GBIF では種に丸められた（正規形が違う）
- `higher_rank`: GBIF が属以上のランクで合わせた
- `no_candidate`: GBIF が一致を返さなかった（NONE）
- `ambiguous`: 正規形が一致する候補が複数ある
- `api_failed`: API 呼び出しに失敗した
"""
import re

_SPECIES_OR_BELOW = frozenset({"SPECIES", "SUBSPECIES", "VARIETY", "FORM"})
_GENUS_STOP = frozenset({"spp.", "sp.", "cf.", "aff.", "spp", "sp"})
_RANK_MARKERS = frozenset({"var.", "subsp.", "ssp.", "f.", "forma", "subsp", "var", "ssp", "fo."})
_LOWER_WORD = re.compile(r"[a-z][a-z\-]+")
_AUTHOR_TOKEN = re.compile(r"^[A-Z(\[&]|^(ex|et|in|von|van|de|der|del|da|di|la|le)$|^\d{4}[a-z,)]?$|^[,&]$|.*[.,)\]]$")


def parse_query_name(name: str) -> dict:
    """verbatim の学名を (正規形, 理由) に分解する。

    戻り値: {"canonical": str|None, "has_infra": bool, "reason": str|None}
    `canonical` は小文字・空白1つ・ランク記号なし（例 'chara globularis hakonensis'）。
    `reason` が非 None のときは API を引かずに unresolved にする区分。
    """
    toks = re.sub(r"\s+", " ", (name or "")).strip().split(" ")
    if not toks or not toks[0]:
        return {"canonical": None, "has_infra": False, "reason": "genus_or_higher"}
    if len(toks) == 1 or toks[1].lower() in _GENUS_STOP:
        # 種小名が無い／spp. など。属以上。
        return {"canonical": None, "has_infra": False, "reason": "genus_or_higher"}
    if not _LOWER_WORD.fullmatch(toks[1]):
        # 種小名の位置が小文字で始まるのに語として読めない（'catesbeiana（別名…)' 等）は注記つき
        reason = "annotated_name" if re.match(r"[a-z]", toks[1]) else "genus_or_higher"
        return {"canonical": None, "has_infra": False, "reason": reason}
    out = [toks[0].lower(), toks[1]]
    rest = toks[2:]
    i = 0
    has_infra = False
    # 著者名の後ろに亜種以下が来る形（'Chara globularis Thuill. var. hakonensis Kasaki'）も読むため、
    # 小文字語・ランク記号を拾い、著者らしいトークンは読み飛ばす。それ以外は注記。
    while i < len(rest):
        t = rest[i]
        if t.lower() in _RANK_MARKERS:
            has_infra = True
        elif _LOWER_WORD.fullmatch(t) and t not in {"ex", "et", "in", "von", "van", "de", "der", "del", "da", "di", "la", "le"}:
            has_infra = True
            out.append(t)
        elif _AUTHOR_TOKEN.match(t):
            pass
        else:
            return {"canonical": None, "has_infra": has_infra, "reason": "annotated_name"}
        i += 1
    return {"canonical": " ".join(out), "has_infra": has_infra, "reason": None}


def normalize_canonical(canonical_name: str | None) -> str | None:
    """GBIF の canonicalName をランク記号なし・小文字・空白1つに揃える。"""
    if not canonical_name:
        return None
    toks = [t for t in re.sub(r"\s+", " ", canonical_name).strip().split(" ") if t.lower() not in _RANK_MARKERS]
    return " ".join(toks).lower() or None


def decide_weak_match(query: dict, match: dict | None) -> dict:
    """`query`＝`parse_query_name()` の戻り値、`match`＝`species/match?verbose=true` の応答
    （API 失敗なら None）。戻り値: {"resolution": "adopted"|"unresolved", "reason": str|None}
    """
    if query["reason"] is not None:
        return {"resolution": "unresolved", "reason": query["reason"]}
    if match is None:
        return {"resolution": "unresolved", "reason": "api_failed"}
    mtype = match.get("matchType")
    if mtype == "NONE" or not match.get("usageKey"):
        return {"resolution": "unresolved", "reason": "no_candidate"}
    if mtype == "FUZZY":
        return {"resolution": "unresolved", "reason": "fuzzy_spelling"}
    if match.get("rank") not in _SPECIES_OR_BELOW:
        return {"resolution": "unresolved", "reason": "higher_rank"}
    if mtype != "EXACT" or normalize_canonical(match.get("canonicalName")) != query["canonical"]:
        # HIGHERRANK で種に丸められた、など
        return {"resolution": "unresolved",
                "reason": "infraspecific_collapsed" if query["has_infra"] else "higher_rank"}
    same = [
        a for a in (match.get("alternatives") or [])
        if a.get("usageKey") != match.get("usageKey")
        and a.get("rank") in _SPECIES_OR_BELOW
        and normalize_canonical(a.get("canonicalName")) == query["canonical"]
    ]
    if same:
        return {"resolution": "unresolved", "reason": "ambiguous"}
    return {"resolution": "adopted", "reason": None}
