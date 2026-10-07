"""神奈川県 eDNA の名前 → taxon の対応表を作る（docs/plans/KANAGAWA_EDNA.md §4。担当 C）。

入力:  data/processed/kanagawa_edna_reads.csv（c89 の出力。§2.2 の edna_reads と同じ列。0 の行も含む）
       data/db/registry.sqlite（taxon を**読むだけ**）
       registry/taxon/kanagawa_edna_name_map.csv・supplement_taxa.csv（既存分。`reviewed=1` の行を保持する）
出力:  registry/taxon/kanagawa_edna_name_map.csv  … name_key → taxon_id（コミットする）
       registry/taxon/supplement_taxa.csv         … registry に無い taxon の追加行（コミットする。build_taxon が読む）

解決の段（上から順。1つの名前は1つの taxon にしか行かない。§4.2）:
  T1 学名の二名法が registry の species に一意に当たる（学名は行の学名列、または同じ公表物の中で
     同じ和名に付いた学名 `paired_sci`）。
  T2 和名が registry の `vernacular_name_ja` に一意に当たる（species のみ）。
  T3 学名はあるが registry に無い → GBIF species/match（EXACT・動物界・同じ階級のみ）で `gbif.<key>`。
  T4 和名しか無い → `common:taxon:kanagawa-edna.<slug>` を name_only（status=unresolved）で追加。学名は作らない。
  T5 属止まり・「A/B」併記 → 行の最も低い確定した階級（シートの属列、無ければ科列…）の taxon。
決まらない名前（GBIF が曖昧・届かない・registry で複数に当たる・T1 と T2 が食い違う）は**確認一覧**に出して
非 0 で終了する（T4 に落とさない。人が `reviewed=1` の行で決める）。

`name_key()` は c89・m07 と共有する正規化（NFKC・括弧書き除去・`cf.` 除去・空白除去・小文字化）。

実行: python3 -I scripts/c89c_edna_taxon_map.py [--offline] [--allow-pending]
GBIF 照会は scripts/c26_taxon_gbif_accepted.py と同じ common.get_json（スロットル・UA 共通）。担当が自分の環境で
1回だけ回し、結果の CSV をコミットする（CI は GBIF に触らない）。応答は data/processed の JSON にキャッシュする。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import pathlib
import re
import sqlite3
import sys
import unicodedata

SCRIPTS = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
from registry.common import slugify_local_key  # noqa: E402  標準ライブラリだけに依存する

READS_CSV = ROOT / "data" / "processed" / "kanagawa_edna_reads.csv"
REGISTRY_DB = pathlib.Path(os.environ.get("RYUIKI_REGISTRY_DB") or ROOT / "data" / "db" / "registry.sqlite")
NAME_MAP_CSV = ROOT / "registry" / "taxon" / "kanagawa_edna_name_map.csv"
SUPPLEMENT_CSV = ROOT / "registry" / "taxon" / "supplement_taxa.csv"
GBIF_CACHE_JSON = ROOT / "data" / "processed" / "kanagawa_edna_gbif_cache.json"

NAME_MAP_FIELDS = ["name_key", "rank", "taxon_id", "scientific_name", "vernacular_name_ja",
                   "tier", "evidence", "reviewed", "name_example"]
SUPPLEMENT_FIELDS = ["taxon_id", "scientific_name", "canonical_binomial", "rank", "kingdom", "phylum",
                     "class", "order", "family", "vernacular_name_ja", "gbif_taxon_key", "basis", "evidence"]
EDNA_ID_PREFIX = "common:taxon:kanagawa-edna."
# supplement_taxa.csv は他の出典も使う共有ファイル。c89c が所有する行は evidence をこの印で始める
OWNER_MARK = "kanagawa_edna: "
GBIF_ID_PREFIX = "common:taxon:gbif."

# シートの「綱」列（日本語）→ (kingdom, phylum, class)。name_only の追加 taxon に分類列を持たせるための小さな対応表。
# 魚類（条鰭綱）は registry の既存の魚の行と同じく class を空にする（taxon_group.yaml の魚類ルールが class 空を見る）。
# **表に無い綱は止める**（黙って未分類にしない）。
CLASS_JA_TABLE = {
    "昆虫綱": ("Animalia", "Arthropoda", "Insecta"),
    "硬骨魚綱": ("Animalia", "Chordata", ""),
    "条鰭綱": ("Animalia", "Chordata", ""),
    "軟骨魚綱": ("Animalia", "Chordata", "Elasmobranchii"),
    "頭甲綱": ("Animalia", "Chordata", "Cephalaspidomorphi"),
    "ヤツメウナギ綱": ("Animalia", "Chordata", "Cephalaspidomorphi"),
    "哺乳綱": ("Animalia", "Chordata", "Mammalia"),
    "鳥綱": ("Animalia", "Chordata", "Aves"),
    "両生綱": ("Animalia", "Chordata", "Amphibia"),
    "爬虫綱": ("Animalia", "Chordata", "Squamata"),
    "鱗竜綱": ("Animalia", "Chordata", "Squamata"),
    "被喉綱": ("Animalia", "Bryozoa", "Phylactolaemata"),
    "裸喉綱": ("Animalia", "Bryozoa", "Gymnolaemata"),
    "軟甲綱": ("Animalia", "Arthropoda", "Malacostraca"),
    "鰓脚綱": ("Animalia", "Arthropoda", "Branchiopoda"),
    "貝形虫綱": ("Animalia", "Arthropoda", "Ostracoda"),
    "カイムシ下綱": ("Animalia", "Arthropoda", "Ostracoda"),
    "鞘甲亜綱": ("Animalia", "Arthropoda", "Hexanauplia"),
    "ウオヤドリエビ綱": ("Animalia", "Arthropoda", "Malacostraca"),
    "トビムシ綱": ("Animalia", "Arthropoda", "Collembola"),
    "トビムシ目": ("Animalia", "Arthropoda", "Collembola"),
    "クモ綱（蛛形綱）": ("Animalia", "Arthropoda", "Arachnida"),
    "ムカデ綱": ("Animalia", "Arthropoda", "Chilopoda"),
    "ムカデ／唇脚綱": ("Animalia", "Arthropoda", "Chilopoda"),
    "ヤスデ綱": ("Animalia", "Arthropoda", "Diplopoda"),
    "ヤスデ／倍脚綱": ("Animalia", "Arthropoda", "Diplopoda"),
    "ヒドロ虫綱": ("Animalia", "Cnidaria", "Hydrozoa"),
    "花虫綱": ("Animalia", "Cnidaria", "Anthozoa"),
    "二枚貝綱": ("Animalia", "Mollusca", "Bivalvia"),
    "腹足綱": ("Animalia", "Mollusca", "Gastropoda"),
    "頭足綱": ("Animalia", "Mollusca", "Cephalopoda"),
    "多板綱": ("Animalia", "Mollusca", "Polyplacophora"),
    "有針綱": ("Animalia", "Nemertea", "Hoplonemertea"),
    "環帯綱": ("Animalia", "Annelida", "Clitellata"),
    "ミミズ綱": ("Animalia", "Annelida", "Clitellata"),
    "ゴカイ綱": ("Animalia", "Annelida", "Polychaeta"),
    "小鎖状綱": ("Animalia", "Platyhelminthes", "Catenulida"),
    "小鎖状目": ("Animalia", "Platyhelminthes", "Catenulida"),
    "真(車)輪虫綱": ("Animalia", "Rotifera", "Eurotatoria"),
    "普通海綿綱": ("Animalia", "Porifera", "Demospongiae"),
    "真クマムシ綱": ("Animalia", "Tardigrada", "Eutardigrada"),
}
# GBIF が class を返す魚類（registry の魚は class 空・phylum=Chordata。上の表と同じ規約）。
FISH_CLASSES = {"Actinopterygii", "Teleostei"}

LATIN_FAMILY_SUFFIXES = ("idae", "inae", "aceae")


# ---------------------------------------------------------------- 名前の正規化・分解
_PAREN = re.compile(r"\([^()]*\)")
_CF = re.compile(r"(?<![A-Za-z])cf\.?(?![A-Za-z])")


def clean_core(raw: str) -> tuple[str, list[str]]:
    """名前の原文 → (核の名前, 取り除いた括弧書き)。NFKC・括弧書き（入れ子可）・`*` を除き空白を畳む。"""
    s = unicodedata.normalize("NFKC", raw or "")
    notes: list[str] = []
    while True:
        m = _PAREN.search(s)
        if not m:
            break
        notes.append(m.group(0))
        s = s[:m.start()] + " " + s[m.end():]
    s = s.replace("*", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s, notes


def name_key(raw: str) -> str:
    """名前の正規化キー（§4.3）。NFKC・括弧書き除去・`cf.` 除去・空白除去・小文字化。`/`（併記）は残す。"""
    core, _ = clean_core(raw)
    core = _CF.sub(" ", core)
    parts = [re.sub(r"\s+", "", p) for p in core.split("/")]
    return "/".join(p.lower() for p in parts if p)


def is_ambiguous(raw: str) -> bool:
    """「A / B」併記か（NFKC で全角スラッシュも畳む。c89c の _resolve と同じ判定）。"""
    core, _ = clean_core(raw)
    return len(split_parts(_CF.sub(" ", core))) > 1


def has_cf(raw: str) -> bool:
    s = unicodedata.normalize("NFKC", raw or "")
    return bool(_CF.search(s))


_RE_LAT_JA_SUFFIX = re.compile(r"^([A-Z][A-Za-z]+)\s?(属の一種|の一種|属)(?:[\s\d].*)?$")
_RE_LAT_SP = re.compile(r"^([A-Z][a-z]+) (?:sp\.?|spp\.?)(?:\s.*)?$")
_RE_LAT_BINOM = re.compile(r"^([A-Z][a-z]+) ([a-z][a-z-]+)(?:\s+(.*))?$")
_RE_LAT_WORD = re.compile(r"^([A-Z][a-z]+)$")
_RE_JA_GENUS = re.compile(r"^([^\s\d/]+?属)(?:の一種|未同定種)?(?:[\s\d].*)?$")
_RE_JA_LINEAGE = re.compile(r"^([ぁ-んァ-ヶー一-龥々・]+?)[-‐]\d+$")
_RE_JA_FAMILY = re.compile(r"^([^\s\d/]+?科)(?:の一種)?(?:[\s\d].*)?$")
_RE_JA_GROUP = re.compile(r"^([^\s\d/]+?(?:類|種群|の近縁種))(?:[\s\d].*)?$")  # 種より上: 〜類・〜種群・〜の近縁種
_RE_JA_INFORMAL = re.compile(r"^[A-Z]{1,3}[ァ-ヶー]+$")
_RE_JA_ONLY = re.compile(r"^[ぁ-んァ-ヶー一-龥々・]+$")


def _latin_higher_rank(word: str) -> str:
    return "family" if word.lower().endswith(LATIN_FAMILY_SUFFIXES) else "genus"


def parse_part(part: str) -> dict:
    """併記を分けた1つの名前 → {kind, latin, ja}。`kind` は
    latin_species / latin_genus / latin_family / ja_species / ja_genus / ja_family / ja_group /
    ja_complex / ja_informal / other。`latin` は学名側（二名法・属名・科名）、`ja` は和名側の名前。"""
    p = _CF.sub(" ", part)
    p = re.sub(r"\s+", " ", p).strip()
    m = _RE_LAT_JA_SUFFIX.match(p)
    if m:
        return {"kind": "latin_" + _latin_higher_rank(m.group(1)), "latin": m.group(1), "ja": None}
    m = _RE_LAT_SP.match(p)
    if m:
        return {"kind": "latin_genus", "latin": m.group(1), "ja": None}
    m = _RE_LAT_BINOM.match(p)
    if m:
        tail = m.group(3) or ""
        if re.search(r"\b(complex|group)\b", tail) or re.match(r"sp(p)?\b", tail):
            return {"kind": "latin_genus", "latin": m.group(1), "ja": None}
        return {"kind": "latin_species", "latin": f"{m.group(1)} {m.group(2)}", "ja": None}
    m = _RE_LAT_WORD.match(p)
    if m:
        return {"kind": "latin_" + _latin_higher_rank(m.group(1)), "latin": m.group(1), "ja": None}
    if "種複合体" in p:
        return {"kind": "ja_complex", "latin": None, "ja": p}
    if _RE_JA_INFORMAL.match(p):
        return {"kind": "ja_informal", "latin": None, "ja": p}
    m = _RE_JA_GENUS.match(p)
    if m:
        return {"kind": "ja_genus", "latin": None, "ja": m.group(1)}
    m = _RE_JA_FAMILY.match(p)
    if m:
        return {"kind": "ja_family", "latin": None, "ja": m.group(1)}
    m = _RE_JA_GROUP.match(p)
    if m:
        return {"kind": "ja_group", "latin": None, "ja": m.group(1)}
    if _RE_JA_ONLY.match(p):
        return {"kind": "ja_species", "latin": None, "ja": p}
    m = _RE_JA_LINEAGE.match(p)
    if m:  # 「シロハラコカゲロウ-1」: 種の中の系統番号。種の名前として扱う（番号は原文に残る）
        return {"kind": "ja_species", "latin": None, "ja": m.group(1), "lineage": True}
    return {"kind": "other", "latin": None, "ja": p}


def split_parts(core: str) -> list[str]:
    return [p.strip() for p in core.split("/") if p.strip()]


def plain_binomial(sci: str) -> str | None:
    """行の学名列が「属名 種小名」だけ（cf.・sp.・併記・複合体の無い）ときだけその二名法。"""
    s = _CF.sub(" ", sci)
    s = re.sub(r"\s+", " ", s).strip()
    m = re.fullmatch(r"([A-Z][a-z]+) ([a-z][a-z-]+)", s)
    if not m or m.group(2) in ("sp", "spp", "aff"):
        return None
    return f"{m.group(1)} {m.group(2)}"


def sci_genus_hint(sci: str) -> str | None:
    """学名列が「Genus sp.」「Genus species complex …」など属止まりのときの属名。"""
    s = re.sub(r"\s+", " ", _CF.sub(" ", sci)).strip()
    if "/" in s:
        return None
    m = _RE_LAT_SP.match(s)
    if m:
        return m.group(1)
    m = _RE_LAT_BINOM.match(s)
    if m and (re.search(r"\b(complex|group)\b", m.group(3) or "") or re.match(r"sp(p)?\b", m.group(3) or "")):
        return m.group(1)
    return None


def level_label(label: str) -> tuple[str | None, str | None]:
    """シートの属・科の列 → (欧文名, 和名)。`-`・空は (None, None)。末尾の属・科は外す。"""
    s = unicodedata.normalize("NFKC", label or "").strip()
    if s in ("", "-", "－", "ー"):
        return None, None
    base = re.sub(r"(属|科)$", "", s)
    if re.fullmatch(r"[A-Z][A-Za-z]+", base):
        return base, None
    return None, s


# ---------------------------------------------------------------- registry
class Registry:
    """registry の taxon を引く索引（読み取り専用）。`rows` は dict の列。`exclude_ids` は supplement 由来の ID
    （自分が前回書いた行を registry の行として拾わない）。

    1つの学名・和名に複数の taxon が当たるのは普通（gbif.* と inat.* の両方、同物異名、亜種）なので、
    `pick_one()` の規則（下記）で機械的に1つに決め、決まらなければ確認へ回す。"""

    def __init__(self, rows, exclude_ids=()):
        self.by_id: dict[str, dict] = {}
        self.species_by_binom: dict[str, list[dict]] = collections.defaultdict(list)
        self.by_vern: dict[str, list[dict]] = collections.defaultdict(list)
        self.rank_by_name: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        excl = set(exclude_ids)
        for r in rows:
            if r["taxon_id"] in excl or r["taxon_id"].startswith(EDNA_ID_PREFIX):
                continue
            self.by_id[r["taxon_id"]] = r
            rank = (r.get("rank") or "").strip()
            if rank == "species" and r.get("canonical_binomial"):
                self.species_by_binom[r["canonical_binomial"]].append(r)
            # 和名は動物界の taxon だけを引く（eDNA の対象は動物。「コムラサキ」「ゴンズイ」は植物にも同名がある）。
            # kingdom の分からない行（和名だけの未照合 taxon）は残す
            if r.get("vernacular_name_ja") and (r.get("kingdom") or "Animalia") == "Animalia":
                self.by_vern[r["vernacular_name_ja"]].append(r)
            if rank in ("genus", "family") and r.get("scientific_name"):
                self.rank_by_name[(rank, r["scientific_name"].split(" ")[0])].append(r)

    @classmethod
    def from_db(cls, path, exclude_ids=()):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(
                "SELECT taxon_id, scientific_name, canonical_binomial, rank, family, vernacular_name_ja, status,"
                " accepted_taxon_id, kingdom FROM taxon")]
        finally:
            con.close()
        return cls(rows, exclude_ids)

    @staticmethod
    def pick_one(cands: list[dict], *, exact_name) -> tuple[dict | None, str]:
        """候補から1つを決める。-> (行, 決め方) か (None, 'ambiguous')。規則（上から）:
        1. 候補が1つならそれ。
        2. 同物異名（accepted_taxon_id が入っている行）を外す。
        3. 著者名の付かない正規形の行（kuma の規則: scientific_name が canonical と一致。属は属名だけ）を残す。
        4. それでも複数なら gbif 名前空間の行（出典が違うだけの同じ taxon。gbif.* と inat.* が両方ある場合）。
        決まらなければ ambiguous。"""
        if len(cands) == 1:
            return cands[0], "single"
        note = []
        acc = [c for c in cands if not c.get("accepted_taxon_id")]
        if acc and len(acc) < len(cands):
            cands, note = acc, note + ["synonym_dropped"]
        if len(cands) == 1:
            return cands[0], "+".join(note)
        ex = [c for c in cands if exact_name(c)]
        if ex and len(ex) < len(cands):
            cands, note = ex, note + ["exact_name"]
        if len(cands) == 1:
            return cands[0], "+".join(note)
        g = [c for c in cands if c["taxon_id"].startswith(GBIF_ID_PREFIX)]
        if len(g) == 1:
            return g[0], "+".join(note + ["prefer_gbif_namespace"])
        return None, "ambiguous"

    @staticmethod
    def _exact_species(c):
        return c.get("scientific_name") == c.get("canonical_binomial")

    def species_by_sci(self, binom: str):
        """-> (taxon 行 or None, 状態 'hit'/'none'/'ambiguous', 決め方)"""
        c = self.species_by_binom.get(binom, [])
        if not c:
            return None, "none", ""
        p, how = self.pick_one(c, exact_name=self._exact_species)
        return (p, "hit", how) if p else (None, "ambiguous", how)

    def species_by_vern(self, name: str):
        """和名 → species。species の行が無ければ、亜種・変種の親の種（二名法が1つに決まるとき）、
        それも無ければ registry が持つ和名だけの未照合 taxon（rank 空・学名なし）。"""
        allc = self.by_vern.get(name, [])
        if not allc:
            return None, "none", ""
        sp = [x for x in allc if (x.get("rank") or "") == "species"]
        if sp:
            binoms = {x.get("canonical_binomial") for x in sp}
            if len(binoms) > 1:
                acc = [x for x in sp if not x.get("accepted_taxon_id")]
                binoms = {x.get("canonical_binomial") for x in acc}
                sp = acc if acc else sp
            if len(binoms) == 1:
                p, how = self.pick_one(sp, exact_name=self._exact_species)
                return (p, "hit", how) if p else (None, "ambiguous", how)
            return None, "ambiguous", "multiple_binomials"
        infra = {x.get("canonical_binomial") for x in allc if (x.get("rank") or "") and x.get("canonical_binomial")}
        if len(infra) == 1:
            row, st, how = self.species_by_sci(next(iter(infra)))
            if st == "hit":
                return row, "hit", "infraspecific_vernacular->species " + how
            return None, "non_species", "infraspecific_without_species_row"
        if len(infra) > 1:
            return None, "ambiguous", "multiple_binomials_infraspecific"
        bare = [x for x in allc if not (x.get("rank") or "") and not x.get("scientific_name")]
        if len(bare) == 1:
            return bare[0], "hit", "registry_unresolved_wamei"
        if bare:
            return None, "ambiguous", "unresolved_wamei_multiple"
        return None, "non_species", "other_rank"

    def vern_binomials(self, name: str) -> list[str]:
        """和名に当たる species の二名法（同物異名を外したもの。複数なら学名の食い違い）。"""
        sp = [x for x in self.by_vern.get(name, []) if (x.get("rank") or "") == "species"]
        acc = [x for x in sp if not x.get("accepted_taxon_id")] or sp
        return sorted({x.get("canonical_binomial") for x in acc if x.get("canonical_binomial")})

    def higher(self, rank: str, name: str):
        c = self.rank_by_name.get((rank, name), [])
        if not c:
            return None, "none", ""
        p, how = self.pick_one(c, exact_name=lambda x: x.get("scientific_name") == name)
        return (p, "hit", how) if p else (None, "ambiguous", how)


class Dictionary:
    """出典つきの和名→学名の辞書（原本 ryuiki.sqlite の `taxa`: 環境省レッドリスト・神奈川県 RDB/レッドリスト・
    環境省 外来種リストの統合表。各行に source_id と source_ref〔URL#row〕がある）。T2b で使う。"""

    def __init__(self, rows):
        self.by_vern: dict[str, dict[str, list[str]]] = collections.defaultdict(lambda: collections.defaultdict(list))
        for r in rows:
            ja = (r.get("vernacular_name_ja") or "").strip()
            m = re.match(r"^([A-Z][a-z]+) ([a-z][a-z-]+)", (r.get("scientific_name") or "").strip())
            if ja and m:
                self.by_vern[ja][f"{m.group(1)} {m.group(2)}"].append(f"{r.get('source_id')}:{r.get('source_ref')}")

    @classmethod
    def from_db(cls, path):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(
                "SELECT vernacular_name_ja, scientific_name, source_id, source_ref FROM taxa "
                "ORDER BY source_id, source_ref")]
        finally:
            con.close()
        return cls(rows)

    def lookup(self, ja: str) -> dict[str, list[str]]:
        return dict(self.by_vern.get(ja, {}))


# ---------------------------------------------------------------- GBIF
class GbifClient:
    """GBIF の species/match と species/{key}。応答は dict キャッシュ（JSON で保存できる）。
    `getter(url, params=None)` を注入する（本番は common.get_json。テストは偽物）。"""

    def __init__(self, getter, cache: dict | None = None):
        self.getter = getter
        self.cache = cache if cache is not None else {}
        self.calls = 0

    def _fetch(self, key: str, url: str, params):
        if key in self.cache:
            return self.cache[key]
        self.calls += 1
        try:
            val = self.getter(url, params=params) if params else self.getter(url)
        except Exception as e:  # 届かない。キャッシュしない（次回引き直す）
            return {"_error": repr(e)}
        self.cache[key] = val
        return val

    def match(self, name: str, rank: str):
        return self._fetch(f"match|{rank}|{name}", "https://api.gbif.org/v1/species/match",
                           {"name": name, "rank": rank.upper(), "kingdom": "Animalia", "strict": "true"})

    def species(self, key):
        return self._fetch(f"species|{key}", f"https://api.gbif.org/v1/species/{key}", None)


def decide_gbif(client: GbifClient, name: str, rank: str):
    """-> (info dict, None) か (None, 理由)。EXACT・動物界・同じ階級だけを採る。
    同物異名（SYNONYM）は受理名（acceptedUsageKey）を引き直して採る（受理名が引けなければ確認へ）。"""
    r = client.match(name, rank)
    if not isinstance(r, dict) or "_error" in r:
        return None, f"gbif_unreachable({(r or {}).get('_error', 'no response')})"
    if r.get("matchType") != "EXACT":
        return None, f"gbif_{(r.get('matchType') or 'NONE').lower()}"
    if (r.get("kingdom") or "") != "Animalia":
        return None, f"gbif_kingdom_{r.get('kingdom')}"
    if (r.get("rank") or "").upper() != rank.upper():
        return None, f"gbif_rank_{(r.get('rank') or '').lower()}"
    status = r.get("status") or ""
    if status == "ACCEPTED":
        return {"key": r["usageKey"], "resp": r, "via": "exact"}, None
    if status == "DOUBTFUL" and rank.upper() != "SPECIES":
        return {"key": r["usageKey"], "resp": r, "via": "doubtful"}, None  # 属・科の疑問群は、階級が合えば採る（証拠に残る）
    acc = r.get("acceptedUsageKey")
    if status in ("SYNONYM", "HETEROTYPIC_SYNONYM", "HOMOTYPIC_SYNONYM", "PROPARTE_SYNONYM") and acc:
        a = client.species(acc)
        if not isinstance(a, dict) or "_error" in a or not a.get("key"):
            return None, "gbif_accepted_unreachable"
        if (a.get("kingdom") or "") != "Animalia" or (a.get("rank") or "").upper() != rank.upper():
            return None, "gbif_accepted_mismatch"
        return {"key": a["key"], "resp": a, "via": f"synonym_of({r.get('usageKey')})"}, None
    return None, f"gbif_status_{status.lower() or 'none'}"


# ---------------------------------------------------------------- 解決
class Taxon:
    """name_map 1行分が指す taxon（registry の行か、supplement に足す行か）。"""

    def __init__(self, taxon_id, rank, scientific_name, vernacular, family=None, genus=None, supplement=None):
        self.taxon_id = taxon_id
        self.rank = rank
        self.scientific_name = scientific_name or ""
        self.vernacular = vernacular or ""
        self.family = family
        self.genus = genus
        self.supplement = supplement  # dict（supplement_taxa の行）か None


def _how(how: str) -> str:
    return f" [{how}]" if how and how != "single" else ""


def _same_species(a: dict, b: dict) -> bool:
    """同じ種（二名法が同じ、または一方が他方の受理名を指す同物異名）。"""
    if a.get("canonical_binomial") and a.get("canonical_binomial") == b.get("canonical_binomial"):
        return True
    return a.get("accepted_taxon_id") == b["taxon_id"] or b.get("accepted_taxon_id") == a["taxon_id"]


def _binom_genus(s: str) -> str:
    return (s or "").split(" ")[0]


def _from_registry(row: dict) -> Taxon:
    sci = row.get("scientific_name") or ""
    return Taxon(row["taxon_id"], row.get("rank") or "", sci, row.get("vernacular_name_ja"),
                 family=row.get("family"), genus=_binom_genus(row.get("canonical_binomial") or sci))


def _gbif_taxon(info: dict, registry: Registry, rank: str) -> tuple[Taxon, bool]:
    """GBIF の採用結果 → Taxon。registry に同じ gbif キーがあればそれを使う（supplement を足さない）。"""
    key = info["key"]
    tid = f"{GBIF_ID_PREFIX}{key}"
    if tid in registry.by_id:
        return _from_registry(registry.by_id[tid]), True
    r = info["resp"]
    canonical = r.get("canonicalName") or ""
    cls = r.get("class") or ""
    if cls in FISH_CLASSES:
        cls = ""
    row = {
        "taxon_id": tid, "scientific_name": r.get("scientificName") or canonical,
        "canonical_binomial": "", "rank": rank.lower(),
        "kingdom": r.get("kingdom") or "", "phylum": r.get("phylum") or "", "class": cls,
        "order": r.get("order") or "", "family": r.get("family") or "",
        "vernacular_name_ja": "", "gbif_taxon_key": str(key), "basis": "gbif_match", "evidence": "",
    }
    return Taxon(tid, rank.lower(), row["scientific_name"], "", family=row["family"],
                 genus=_binom_genus(canonical), supplement=row), False


class Aggregates:
    """reads.csv を名前ごとに集計したもの。"""

    def __init__(self, rows):
        self.keys: dict[str, dict] = {}
        order_classes: dict[str, set] = collections.defaultdict(set)
        for r in rows:
            if (r.get("class_ja") or "") in CLASS_JA_TABLE and (r.get("order_ja") or "") not in ("", "-"):
                order_classes[r["order_ja"]].add(r["class_ja"])
        # 綱が「-」の行（r7_project の一部）は、同じ目が他の行で1つの綱にだけ付いているときその綱を使う
        self.order_to_class = {o: next(iter(c)) for o, c in order_classes.items() if len(c) == 1}
        for r in rows:
            adopted = (r.get("name_adopted") or r.get("name_raw") or "").strip()
            if not adopted:
                raise ValueError(f"名前が空の行: {r.get('read_id')}")
            k = name_key(adopted)
            e = self.keys.setdefault(k, {
                "example": adopted, "rows": 0, "detected": 0, "sci": collections.Counter(),
                "hier": collections.Counter(), "raw_forms": set()})
            e["rows"] += 1
            e["detected"] += int(r.get("is_detected") or 0)
            e["raw_forms"].add(adopted)
            if r.get("name_sci_raw"):
                e["sci"][clean_core(r["name_sci_raw"])[0]] += 1
            ym = re.match(r"r(\d+)_", (r.get("read_id") or ""))
            e["hier"][(int(ym.group(1)) if ym else 0,
                       r.get("class_ja") or "", r.get("order_ja") or "", r.get("family_ja") or "",
                       r.get("genus_ja") or "")] += 1
        for e in self.keys.values():
            e["example"] = sorted(e["raw_forms"])[0]

    def hierarchy(self, k: str) -> dict:
        """名前の分類（綱・目・科・属）。年度の新しいファイルの値を採る（同数なら件数の多い順）。"""
        h = self.keys[k]["hier"]
        known = {kk: v for kk, v in h.items() if kk[1] in CLASS_JA_TABLE}  # 綱が「-」の年は、綱の分かる年を優先
        best = max((known or h).items(), key=lambda kv: (kv[0][0], kv[1], kv[0][1:]))[0]
        cls = best[1] if best[1] in CLASS_JA_TABLE else self.order_to_class.get(best[2], best[1])
        return {"class": cls, "order": best[2], "family": best[3], "genus": best[4]}


class Resolver:
    def __init__(self, registry: Registry, gbif: GbifClient | None, aggregates: Aggregates,
                 dictionary: Dictionary | None = None):
        self.dictionary = dictionary
        self.registry = registry
        self.gbif = gbif
        self.agg = aggregates
        self.supp: dict[str, dict] = {}          # taxon_id -> supplement 行
        self.genus_ja_to_latin: dict[str, set] = collections.defaultdict(set)
        self.family_ja_to_latin: dict[str, set] = collections.defaultdict(set)

    # -- 低レベル: 学名・和名から
    def _sci_species(self, binom: str):
        """学名の二名法 → (Taxon, tier, evidence) か (None, None, 理由)。T1 → T3。"""
        row, st, how = self.registry.species_by_sci(binom)
        if st == "ambiguous":
            return None, None, f"registry_ambiguous_species({binom})"
        if row:
            return _from_registry(row), "T1", f"registry species {binom}" + _how(how)
        return self._gbif(binom, "species", "T3")

    def _gbif(self, name: str, rank: str, tier: str):
        if self.gbif is None:
            return None, None, f"gbif_offline({name})"
        info, why = decide_gbif(self.gbif, name, rank)
        if info is None:
            return None, None, f"{why}({name})"
        t, in_reg = _gbif_taxon(info, self.registry, rank)
        ev = f"GBIF match {rank} '{name}' -> {info['key']} ({info['via']})" + ("; registry に既存" if in_reg else "")
        return t, tier, ev

    def _name_only(self, ja: str, rank: str, hier: dict, why: str):
        cls = hier.get("class", "")
        if cls not in CLASS_JA_TABLE:
            raise ValueError(f"綱 {cls!r} が CLASS_JA_TABLE に無い（name={ja!r}）。対応表に足すこと")
        kingdom, phylum, class_en = CLASS_JA_TABLE[cls]
        tid = EDNA_ID_PREFIX + slugify_local_key(ja)
        row = {"taxon_id": tid, "scientific_name": "", "canonical_binomial": "", "rank": rank,
               "kingdom": kingdom, "phylum": phylum, "class": class_en, "order": "", "family": "",
               "vernacular_name_ja": ja, "gbif_taxon_key": "", "basis": "name_only", "evidence": why}
        return Taxon(tid, rank, "", ja, supplement=row)

    # -- 種レベルの名前
    def species_level(self, k: str, part: dict, e: dict):
        """latin_species / ja_species（併記でない1名）→ (Taxon, tier, evidence) か (None, None, 理由)。"""
        sci_plain = sorted({b for b in (plain_binomial(s) for s in e["sci"]) if b})
        if part["kind"] == "latin_species":
            return self._sci_species(part["latin"])
        ja = part["ja"]
        if len(sci_plain) > 1:
            return None, None, f"paired_sci_conflict({sci_plain})"
        row1 = row2 = None
        ev1 = ev2 = ""
        if sci_plain:
            row1, st, how = self.registry.species_by_sci(sci_plain[0])
            if st == "ambiguous":
                return None, None, f"registry_ambiguous_species({sci_plain[0]})"
            ev1 = f"registry species {sci_plain[0]} (学名列)" + _how(how)
        row2, st, how = self.registry.species_by_vern(ja)
        if st == "ambiguous":
            if row1 is None and how.startswith("multiple_binomials") and self.gbif is not None:
                binoms = self.registry.vern_binomials(ja)
                acc = [b for b in binoms if (decide_gbif(self.gbif, b, "species")[0] or {}).get("via") == "exact"]
                if len(acc) == 1:
                    t, tier, ev = self._sci_species(acc[0])
                    if t is not None:
                        return t, "T2", f"registry vernacular_name_ja {ja} は複数の種 {binoms} に当たる。GBIF の受理名は {acc[0]} だけ; " + ev
            if row1 is None:
                return None, None, f"registry_ambiguous_vernacular({ja}:{how})"
            row2 = None  # 公表物の学名列で決まる。registry の和名は複数の種に当たるので使わない
        if st == "non_species":
            row2 = None  # registry に種の行が無い。辞書（T2b）を試す
        ev2 = f"registry vernacular_name_ja {ja}" + _how(how)
        if row1 and row2 and row1["taxon_id"] != row2["taxon_id"]:
            if _same_species(row1, row2):
                pick, how = Registry.pick_one([row1, row2], exact_name=Registry._exact_species)
                if pick is None:
                    return None, None, f"T1_T2_same_species_unpicked({row1['taxon_id']} vs {row2['taxon_id']})"
                row1 = row2 = pick
            elif not row2.get("rank"):
                ev1 += f"; 同じ和名の未照合 taxon {row2['taxon_id']} が registry にある（採らない）"
            else:
                # 公表物が自分で付けた学名（T1）を、registry の和名（記録由来）より優先する。食い違いは証拠に残す
                ev1 += f"; registry の和名 {ja} は別の種 {row2['taxon_id']} を指す（採らない）"
        if row1:
            return _from_registry(row1), "T1", ev1
        if row2 and row2.get("scientific_name"):
            return _from_registry(row2), "T2", ev2
        if not sci_plain and self.dictionary is not None:
            # T2b: 和名のみ（または registry に学名の無い和名だけの taxon）→ 出典つきの辞書で学名に当て、T1→T3 に通す
            cands = self.dictionary.lookup(ja)
            if len(cands) > 1:
                return None, None, f"dictionary_ambiguous({ja}:{sorted(cands)})"
            if cands:
                binom, refs = next(iter(cands.items()))
                t, tier, ev = self._sci_species(binom)
                if t is None:
                    return None, None, ev
                return t, "T2b", f"辞書 taxa {refs[0]} ({len(refs)}行): {ja} -> {binom}; " + ev
        if row2:
            return _from_registry(row2), "T2", ev2
        if sci_plain:
            t, tier, ev = self._gbif(sci_plain[0], "species", "T3")
            if t is None:
                return None, None, ev
            return t, tier, ev + " (学名列)"
        return None, "NAME_ONLY", "registry に無い和名のみ"

    # -- 上位階級（属・科）
    def higher_latin(self, rank: str, latin: str):
        row, st, how = self.registry.higher(rank, latin)
        if st == "ambiguous":
            return None, None, f"registry_ambiguous_{rank}({latin})"
        if row:
            return _from_registry(row), "T5", f"registry {rank} {latin}" + _how(how)
        return self._gbif(latin, rank, "T5")

    def level_target(self, rank: str, label: str, hier: dict, why: str):
        """シートの属・科の列（欧文 or 和名）→ その階級の taxon。和名は他の行で解決済みの種との対応で欧文名に引く。"""
        latin, ja = level_label(label)
        if latin:
            return self.higher_latin(rank, latin)
        if not ja:
            return None, None, "no_label"
        table = self.genus_ja_to_latin if rank == "genus" else self.family_ja_to_latin
        cands = table.get(re.sub(r"(属|科)$", "", ja), set())
        if len(cands) == 1:
            return self.higher_latin(rank, next(iter(cands)))
        name = ja if ja.endswith("属" if rank == "genus" else "科") else ja + ("属" if rank == "genus" else "科")
        return self._name_only(name, rank, hier, why), "NAME_ONLY", f"{rank} 和名のみ（{why}）"

    def reduce_to_sheet(self, hier: dict, why: str, genus_hint: str | None = None, skip_genus: bool = False):
        """属止まり・併記 → シートの属→科→（目・綱は採らず確認へ）の順で最も低い確定階級。"""
        if genus_hint:
            t, tier, ev = self.higher_latin("genus", genus_hint)
            if t:
                return t, "T5", ev + f" (学名列の属 {genus_hint}; {why})"
        latin, ja = level_label(hier["genus"])
        if (latin or ja) and not skip_genus:
            t, tier, ev = self.level_target("genus", hier["genus"], hier, why)
            if t is not None and tier != "NAME_ONLY":
                return t, "T5", ev + f" (シートの属 {hier['genus']}; {why})"
            # 属が決まらない（GBIF に無い等）か和名のみで欧文名に引けない: 科で受けられるなら科（種より上の名前は T4 にしない）
            fl, fj = level_label(hier["family"])
            if fl or fj:
                t2, tier2, ev2 = self.level_target("family", hier["family"], hier, why)
                if t2 is not None and tier2 != "NAME_ONLY":
                    return t2, "T5", ev2 + f" (シートの科 {hier['family']}; 属 {hier['genus']} は決まらない; {why})"
            if t is not None:
                return t, "T5", ev + f" (シートの属 {hier['genus']}; {why})"
            return None, None, ev
        latin, ja = level_label(hier["family"])
        if latin or ja:
            t, tier, ev = self.level_target("family", hier["family"], hier, why)
            if t:
                return t, "T5", ev + f" (シートの科 {hier['family']}; {why})"
            return None, None, ev
        return None, None, f"no_genus_or_family({why})"

    # -- 1つの名前
    _GBIF_MISS = re.compile(r"^gbif_(none|fuzzy|higherrank|status_\w+|rank_\w+)\(([^)]*)\)")

    def _fallback(self, r: dict, hier: dict) -> dict:
        """GBIF に種が無い（none/fuzzy）→ 属、属も無い → シートの科。誤って別種に寄せず、階級を落として受ける（rank_reduced）。"""
        why = r.get("pending", "")
        m = self._GBIF_MISS.match(why)
        if not m:
            return r
        name = m.group(2)
        flags = dict(r["flags"], rank_reduced=True)
        genus = name.split(" ")[0] if re.match(r"^[A-Z][a-z]+ [a-z-]+$", name) else None
        if genus and m.group(1) in ("none", "fuzzy", "higherrank"):
            t, tier, ev = self.higher_latin("genus", genus)
            if t is not None:
                return self._result(t, "T5", f"種 {name} は GBIF に無い ({m.group(1)}) ので属 {genus} に寄せる; " + ev, flags)
        t, tier, ev = self.reduce_to_sheet(hier, f"{name} は GBIF で決まらない ({m.group(1)})", skip_genus=True)
        if t is not None:
            return self._result(t, "T5", ev, flags)
        return r

    def resolve(self, k: str) -> dict:
        r = self._resolve(k)
        if "pending" in r:
            r = self._fallback(r, self.agg.hierarchy(k))
        return r

    def _resolve(self, k: str) -> dict:
        e = self.agg.keys[k]
        hier = self.agg.hierarchy(k)
        core, _ = clean_core(e["example"])
        parts = split_parts(_CF.sub(" ", core))
        flags = {"rank_reduced": False, "name_ambiguous": False}
        if len(parts) > 1:
            flags["name_ambiguous"] = True
            flags["rank_reduced"] = True
            t, tier, ev = self.reduce_to_sheet(hier, "併記 " + "/".join(parts))
            return self._result(t, tier, ev, flags)
        p = parse_part(parts[0]) if parts else {"kind": "other", "ja": core}
        kind = p["kind"]
        if kind in ("latin_species", "ja_species"):
            t, tier, ev = self.species_level(k, p, e)
            if tier == "NAME_ONLY":
                t = self._name_only(p["ja"], "species", hier, ev)
                tier, ev = "T4", "和名のみ。registry に学名・和名とも無い"
            return self._result(t, tier, ev, flags)
        flags["rank_reduced"] = True
        if kind == "latin_genus":
            t, tier, ev = self.higher_latin("genus", p["latin"])
            return self._result(t, tier, ev, flags)
        if kind == "latin_family":
            t, tier, ev = self.higher_latin("family", p["latin"])
            return self._result(t, tier, ev, flags)
        hint = None
        for s in sorted(e["sci"]):
            hint = sci_genus_hint(s) or hint
        if kind in ("ja_genus", "ja_complex", "ja_informal", "ja_group", "ja_family"):
            if kind == "ja_family":
                t, tier, ev = self.level_target("family", p["ja"], hier, "科の和名")
                if t is not None and tier == "NAME_ONLY":
                    tier = "T4"
                return self._result(t, tier if tier != "NAME_ONLY" else "T4", ev, flags)
            if kind == "ja_genus" and not hint:
                t, tier, ev = self.level_target("genus", p["ja"], hier, "属の和名")
                if t is not None and tier != "NAME_ONLY":
                    return self._result(t, "T5", ev, flags)
                if t is None:
                    return self._result(None, None, ev, flags)
            t, tier, ev = self.reduce_to_sheet(hier, f"{kind} {p['ja']}", genus_hint=hint)
            if t is not None and t.supplement is not None and t.supplement["basis"] == "name_only":
                tier = "T4"  # 欧文名に引けない属・科の和名（種より上の名前。registry に学名の無い分類群）
            return self._result(t, tier, ev, flags)
        return self._result(None, None, f"unparsed_name({core})", flags)

    @staticmethod
    def _result(t, tier, ev, flags):
        if t is None:
            return {"pending": ev or "unresolved", "flags": flags}
        if tier == "T5" and t.supplement and t.supplement["basis"] == "name_only":
            tier = "T4"      # 和名しか無く taxon を新設した行はどの経路でも T4（T5 は registry/GBIF の上位 taxon に寄せたもの）
        return {"taxon": t, "tier": tier, "evidence": ev, "flags": flags}


# ---------------------------------------------------------------- 全体
def build(reads_rows, registry: Registry, gbif: GbifClient | None, existing_map: dict | None = None,
          existing_supp: dict | None = None, dictionary: Dictionary | None = None):
    """-> (name_map 行のリスト, supplement 行のリスト, 確認一覧 [(name_key, 例, 理由)])。決定的。"""
    existing_map = existing_map or {}
    existing_supp = existing_supp or {}
    agg = Aggregates(reads_rows)
    res = Resolver(registry, gbif, agg, dictionary)

    keys = sorted(agg.keys)
    results: dict[str, dict] = {}
    # 1 巡目: 種レベルの名前（T1〜T4）。上位階級の和名→欧文名の対応表をここから作る
    for k in keys:
        if existing_map.get(k, {}).get("reviewed") == "1":
            continue
        core, _ = clean_core(agg.keys[k]["example"])
        parts = split_parts(_CF.sub(" ", core))
        if len(parts) == 1 and parse_part(parts[0])["kind"] in ("latin_species", "ja_species"):
            r = res.resolve(k)
            results[k] = r
            t = r.get("taxon")
            if t is not None and t.rank == "species" and r["tier"] in ("T1", "T2", "T3") and t.genus:
                h = agg.keys[k]["hier"]
                for (_, _c, _o, fam, gen) in h:
                    gl, gj = level_label(gen)
                    if gj:
                        res.genus_ja_to_latin[re.sub(r"属$", "", gj)].add(t.genus)
                    fl, fj = level_label(fam)
                    if fj and t.family:
                        res.family_ja_to_latin[re.sub(r"科$", "", fj)].add(t.family)
    # 2 巡目: 属止まり・併記
    for k in keys:
        if k in results or existing_map.get(k, {}).get("reviewed") == "1":
            continue
        results[k] = res.resolve(k)

    # 出力行
    out_rows: list[dict] = []
    pending: list[tuple[str, str, str]] = []
    supp_rows: dict[str, dict] = {}
    vern_votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for k in keys:
        e = agg.keys[k]
        ex = existing_map.get(k)
        if ex and ex.get("reviewed") == "1":
            row = dict(ex)
            row["name_example"] = e["example"]
            out_rows.append(row)
            continue
        r = results[k]
        if "pending" in r:
            pending.append((k, e["example"], r["pending"]))
            continue
        t: Taxon = r["taxon"]
        ev = r["evidence"]
        fl = [n for n, v in r["flags"].items() if v]
        if fl:
            ev += " [" + ",".join(fl) + "]"
        out_rows.append({"name_key": k, "rank": t.rank, "taxon_id": t.taxon_id, "scientific_name": t.scientific_name,
                         "vernacular_name_ja": t.vernacular if r["tier"] in ("T4",) else "",
                         "tier": r["tier"], "evidence": ev, "reviewed": "0", "name_example": e["example"]})
        if t.supplement is not None:
            row = supp_rows.setdefault(t.taxon_id, dict(t.supplement))
            core, _ = clean_core(e["example"])
            p = parse_part(core) if "/" not in core else {"kind": "other"}
            if t.taxon_id.startswith(GBIF_ID_PREFIX) and p["kind"] == "ja_species" and r["tier"] in ("T3",):
                vern_votes[t.taxon_id][p["ja"]] += e["detected"] + 0
            if t.taxon_id.startswith(GBIF_ID_PREFIX):
                row["evidence"] = ev.split(";")[0].split(" (")[0]
    # reviewed 行が指す supplement 行（既存の CSV から）を残す
    for row in out_rows:
        tid = row["taxon_id"]
        if row.get("reviewed") == "1" and tid not in registry.by_id and tid not in supp_rows:
            if tid not in existing_supp:
                raise ValueError(f"reviewed 行 {row['name_key']} の taxon_id {tid} が registry にも supplement にも無い")
            supp_rows[tid] = dict(existing_supp[tid])
    for tid, votes in vern_votes.items():
        best = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        supp_rows[tid]["vernacular_name_ja"] = best
    return out_rows, [supp_rows[t] for t in sorted(supp_rows)], pending


def merge_supplement(foreign: dict, mine: list) -> list:
    """共有 supplement の書き出し行 = 他の出典の行（そのまま）+ c89c の行（印つき）。taxon_id 順。"""
    out = dict(foreign)
    for row in mine:
        if row["taxon_id"] in foreign:
            raise ValueError(f"supplement の {row['taxon_id']} は他の出典の行（evidence が {OWNER_MARK!r} で始まらない）と"
                             "衝突する。eDNA の行なら evidence の先頭に印を付けてから再実行する")
        row = dict(row)
        if not row.get("evidence", "").startswith(OWNER_MARK):
            row["evidence"] = OWNER_MARK + row.get("evidence", "")
        out[row["taxon_id"]] = row
    return [out[k] for k in sorted(out)]


def summarize(rows, agg_rows):
    """tier 別の (名前数, 検出行数)。"""
    det = collections.Counter()
    for r in agg_rows:
        det[name_key((r.get("name_adopted") or r.get("name_raw") or "").strip())] += int(r.get("is_detected") or 0)
    by = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["tier"]][0] += 1
        by[r["tier"]][1] += det[r["name_key"]]
    return dict(sorted(by.items()))


# ---------------------------------------------------------------- 入出力
def read_reads(path: pathlib.Path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if rows and "name_key" in rows[0]:
        for r in rows:
            nm = (r.get("name_adopted") or r.get("name_raw") or "").strip()
            if r["name_key"] != name_key(nm):
                raise ValueError(f"reads の name_key が c89c の name_key() と食い違う: {r['name_key']!r} vs {name_key(nm)!r} ({nm!r})")
    return rows


def owned(row: dict) -> bool:
    """supplement の行が c89c の所有か（evidence の印、または eDNA 専用の taxon_id）。"""
    return (row.get("evidence") or "").startswith(OWNER_MARK) or (row.get("taxon_id") or "").startswith(EDNA_ID_PREFIX)


def read_csv_rows(path) -> list[dict]:
    """CSV を dict の列で読む（共有の読み出し。c89b・m07 もこれを使う）。"""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_csv_dict(path: pathlib.Path, key: str) -> dict:
    if not path.exists():
        return {}
    return {r[key]: r for r in read_csv_rows(path)}


def text(v):
    """前後空白を除き、空は None（m07 などが共有）。"""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def write_csv(path: pathlib.Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--reads", type=pathlib.Path, default=READS_CSV)
    ap.add_argument("--registry-db", type=pathlib.Path, default=REGISTRY_DB)
    ap.add_argument("--name-map", type=pathlib.Path, default=NAME_MAP_CSV)
    ap.add_argument("--supplement", type=pathlib.Path, default=SUPPLEMENT_CSV)
    ap.add_argument("--gbif-cache", type=pathlib.Path, default=GBIF_CACHE_JSON)
    ap.add_argument("--dictionary-db", type=pathlib.Path, default=ROOT / "data" / "db" / "ryuiki.sqlite",
                    help="和名→学名の辞書（原本の taxa 表。読み取り専用）。無ければ T2b を使わない")
    ap.add_argument("--offline", action="store_true", help="GBIF に照会しない（キャッシュも使わない）")
    ap.add_argument("--allow-pending", action="store_true", help="確認一覧が残っていても書き出して 0 で終わる")
    args = ap.parse_args(argv)

    rows = read_reads(args.reads)
    existing_map = read_csv_dict(args.name_map, "name_key")
    all_supp = read_csv_dict(args.supplement, "taxon_id")
    existing_supp = {k: v for k, v in all_supp.items() if owned(v)}     # 自分の行だけを入れ替える
    foreign_supp = {k: v for k, v in all_supp.items() if k not in existing_supp}
    registry = Registry.from_db(args.registry_db, exclude_ids=existing_supp)
    dictionary = Dictionary.from_db(args.dictionary_db) if args.dictionary_db.exists() else None
    gbif = None
    if not args.offline:
        from common import get_json  # requests に依存するのでここで import
        cache = json.loads(args.gbif_cache.read_text(encoding="utf-8")) if args.gbif_cache.exists() else {}
        gbif = GbifClient(get_json, cache)
    try:
        out_rows, supp_rows, pending = build(rows, registry, gbif, existing_map, existing_supp, dictionary)
    finally:
        if gbif is not None:
            args.gbif_cache.parent.mkdir(parents=True, exist_ok=True)
            args.gbif_cache.write_text(json.dumps(gbif.cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"名前 {len(out_rows) + len(pending)} 件（解決 {len(out_rows)}・確認 {len(pending)}）, GBIF 呼び出し {gbif.calls if gbif else 0} 回")
    for tier, (n, d) in summarize(out_rows, rows).items():
        print(f"  {tier}: 名前 {n} 件 / 検出行 {d}")
    if pending:
        print("確認一覧（人が reviewed=1 の行で決める）:")
        for k, ex, why in pending:
            print(f"  {k}\t{ex}\t{why}")
        if not args.allow_pending:
            return 1
    write_csv(args.name_map, NAME_MAP_FIELDS, out_rows)
    write_csv(args.supplement, SUPPLEMENT_FIELDS, merge_supplement(foreign_supp, supp_rows))
    print(f"書き出し: {args.name_map} ({len(out_rows)} 行), {args.supplement} ({len(supp_rows)} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
