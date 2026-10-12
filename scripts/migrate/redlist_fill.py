"""occurrence の赤リスト判定の補完（b06 が `red_list_category`/`red_list_source` が NULL の記録に対して呼ぶ）。

出典（GBIF/iNat は m03、eDNA はアダプタ）が自分で付けた値は触らない。付けていない記録（モニタリングサイト1000 の
アダプタ等）にだけ、m03 と同じ優先順位（地域の県版 → 全国版）で学名から引く。2026-10-12 オーナー決定:

1. 県版（記録の地域が一致するリスト）に学名が完全一致 → その県版のカテゴリー。`red_list_source` = list_id。
2. 全国版（`ryuiki.taxa.redlist_national`）に学名が完全一致 → `red_list_source` = 'national'（m03 の NATIONAL_SOURCE）。
3. 種レベルの記録（二名法）で、同じ地域の県版が**その種の亜種・変種だけ**を載せているとき → 該当。
   `red_list_source` = '<list_id>+subspecies:<掲載名>'（亜種で載っていることが利用側に見える）。複数の亜種が
   載っているときは新しい版を先に、その中で最も深刻なカテゴリー（`redlist_category.yaml` の rank。同順位なら
   掲載名の辞書順）の亜種を採り、その掲載名を出す。絶滅（EX・EW）の亜種掲載は種の記録を該当にしない。
   種で完全一致する掲載があれば 1.（種レベルが勝つ）。
   **全国版の亜種掲載は種の記録を該当にしない**（地域が決められないため）。

学名は命名者・年を落としてから（`bare_name`。掲載名の側も同じに落とす）`taxon_namespaces.norm_taxon_id` で正規化する。
亜種・変種の掲載かどうかは、落とした後の名前が種内名を持つか（3語目以降がある）で決める。県版は m03 と同じく
`regions.REGIONS[rid]["pref_redlist"]` が宣言するリストだけ（`kind=red_list` の全リストではない。例えば rdb2022p は入れない）。カテゴリーの文字列は m03 の `_cat_text`
（`カテゴリー（コード）`）と同じ形。県版の原本は registry の `taxon_assessment`（kind=red_list の list の行。
list の地域は `registry/taxon/assessment_list.yaml`）、全国版は原本の `taxa`。m03 の再実行も原本への書き込みも要らない。
"""
from __future__ import annotations

import collections
import pathlib
import re
import sqlite3
from collections import defaultdict
from typing import NamedTuple

import regions
from reconcile.common import load_yaml   # yaml は遅延 import（v2 パイプラインの import 閉包は PyYAML を要求しない。common.py 参照）
# `registry/build_taxon_assessment.load_redlist_categories()` を使わないのは、それがモジュール先頭で yaml と
# registry.common を import し、v2 の import 閉包（鮮度の指紋）に registry ビルド側のコードを引き込むため。
from taxon_namespaces import norm_taxon_id

_TAXON_REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "taxon"

NATIONAL_SOURCE = "national"   # m03_organisms.NATIONAL_SOURCE と同じ値（m03 は収集系の依存を引くので import しない）
SUBSPECIES_MARK = "+subspecies:"

RULE_PREF_EXACT = "pref_exact"
RULE_NATIONAL_EXACT = "national_exact"
RULE_SUBSPECIES = "subspecies"

_EXTINCT_CODES = frozenset({"EX", "EW"})   # 絶滅の亜種掲載は、種の記録を該当にしない

_RANK_MARKERS = frozenset({"var.", "subsp.", "ssp.", "f.", "subvar.", "forma", "fo."})
_EPITHET = re.compile(r"^[a-z][a-z\-]*$")             # 種小名・種内名（c-aureum のようにハイフンを含みうる）
_SUBGENUS = re.compile(r"^\([A-Z][A-Za-z\-]*\)$")     # 属名の直後の（亜属）
_AUTHOR_PARTICLES = frozenset({"de", "van", "von", "d'", "la", "le", "du", "del", "da", "der", "den", "ten", "ter"})


def _particle_starts_author(after: list[str]) -> bool:
    """小辞（de・van 等）の後が、（小辞が続くなら飛ばして）大文字始まりの語か末尾なら、命名者の始まり。"""
    for t in after:
        if t not in _AUTHOR_PARTICLES:
            return t[:1].isupper()
    return True


def bare_name(name: str | None) -> str:
    """命名者・年を落とした学名（属 + 小文字始まりの種小名・種内名。`var.`/`subsp.`/`f.` の標識は残す）。
    `Columba janthina janthina (Temminck, 1830)` -> `Columba janthina janthina`、
    `Polygonia c-aureum (Linnaeus, 1758)` -> `Polygonia c-aureum`（ハイフン入りの種小名は残す）、
    `Cincticostella (Cincticostella) orientalis Tshernova` -> `Cincticostella orientalis`（亜属は落とす）。
    小文字の命名者の小辞（de・van・von 等）は、大文字始まりの語か末尾が続くとき命名者の始まりとして止める。
    GBIF/iNat の名前は元から命名者を含まないが、モニ1000 のアダプタや registry の `taxon.scientific_name`、
    県版リストの掲載名（'Lemna trisulca L.'）は含む。"""
    toks = (name or "").split()
    if not toks:
        return ""
    out = [toks[0]]
    rest = toks[1:]
    if rest and _SUBGENUS.match(rest[0]) and len(rest) > 1:
        rest = rest[1:]
    for i, t in enumerate(rest):
        if t in _RANK_MARKERS:
            out.append(t)
        elif _EPITHET.match(t):
            if len(out) >= 2 and t in _AUTHOR_PARTICLES and _particle_starts_author(rest[i + 1:]):
                break
            out.append(t)
        else:
            break
    while len(out) > 1 and out[-1] in _RANK_MARKERS:   # 標識だけで種内名が無い（'Protaetia brevitarsis ssp.'）は種
        out.pop()
    return " ".join(out)


def _is_infraspecific(key: str) -> bool:
    """落とした後の名前（正規化済み）が種内名を持つか（属・種小名の後に語がある）。"""
    return len(key.split(" ")) >= 3


def _species_of(key: str) -> str:
    return " ".join(key.split(" ")[:2])


def _cat_text(category_ja: str, code: str | None) -> str:
    return f"{category_ja}（{code}）" if code else category_ja   # m03 と同じ形


class Hit(NamedTuple):
    category: str
    source: str
    rule: str
    key: str   # 引いた学名の正規化キー（統計はこれで数える）


def _pref_list_ids() -> dict[str, tuple[str, ...]]:
    """region -> 県版の list_id（m03 が引くものと同じ宣言: `regions.REGIONS[rid]["pref_redlist"]`）。"""
    out = {}
    for rid, spec in regions.REGIONS.items():
        decl = spec["pref_redlist"]
        out[rid] = tuple(decl["list_ids"]) if decl["source"] == "taxa_column" else (decl["list_id"],)
    return out


class RedListResolver:
    """(region_id, scientific_name, taxon_id) -> Hit | None。`work` は src/reg を ATTACH 済み。"""

    def __init__(self, work: sqlite3.Connection):
        lists = _pref_list_ids()
        region_of = {lid: rid for rid, ids in lists.items() for lid in ids}
        cats = {e["code"]: e for e in load_yaml(_TAXON_REGISTRY_DIR / "redlist_category.yaml")["categories"]}
        ph = ",".join("?" * len(region_of))
        rows = work.execute(
            f"SELECT list_id, list_year, scientific_name_raw, category_raw, category_code "
            f"FROM reg.taxon_assessment WHERE list_id IN ({ph}) "
            f"AND scientific_name_raw IS NOT NULL AND category_raw IS NOT NULL "
            f"ORDER BY list_year DESC, list_id, assessment_id",
            list(region_of),
        ).fetchall()
        # 県版の完全一致: region -> 正規化名 -> (カテゴリー, list_id)（新しい版が先）
        self._pref: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)
        # 亜種掲載: region -> 種の正規化名 -> [(list_year, rank, 掲載名, カテゴリー, list_id)]
        sub: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for list_id, list_year, name, cat_raw, code in rows:
            region = region_of[list_id]
            key = norm_taxon_id(bare_name(name))
            if not key:
                continue
            text = _cat_text(cat_raw, code)
            self._pref[region].setdefault(key, (text, list_id))
            if _is_infraspecific(key) and code not in _EXTINCT_CODES:   # 亜種・変種などの掲載
                rank = (cats.get(code) or {}).get("rank")
                sub[region][_species_of(key)].append(
                    (list_year or 0, rank if rank is not None else -1, bare_name(name), text, list_id))
        self._subspecies: dict[str, dict[str, tuple[str, str]]] = {}
        for region, by_species in sub.items():
            best = {}
            for species, cands in by_species.items():
                # 新しい版 → 最も深刻（rank 大）→ 掲載名の辞書順（決定的）
                _y, _r, name, text, list_id = sorted(cands, key=lambda c: (-c[0], -c[1], c[2]))[0]
                best[species] = (text, f"{list_id}{SUBSPECIES_MARK}{name}")
            self._subspecies[region] = best
        self._national = {
            norm_taxon_id(tid): rn for tid, rn in work.execute(
                "SELECT taxon_id, redlist_national FROM src.taxa WHERE redlist_national IS NOT NULL AND redlist_national != ''"
            ) if not tid.startswith("wamei:")
        }
        self._work = work
        self._taxon: dict[str, tuple[str | None, str | None]] = {}
        self._cache: dict[tuple[str, str | None, str | None], Hit | None] = {}

    def _taxon_row(self, taxon_id: str) -> tuple[str | None, str | None]:
        if taxon_id not in self._taxon:
            row = self._work.execute(
                "SELECT canonical_binomial, scientific_name FROM reg.taxon WHERE taxon_id = ?", (taxon_id,)).fetchone()
            self._taxon[taxon_id] = (row[0], row[1]) if row else (None, None)
        return self._taxon[taxon_id]

    def _key(self, scientific_name: str | None, taxon_id: str | None) -> str:
        """引くための正規化キー。taxon_id が registry の分類群なら、その canonical_binomial（+ 記録の名前が持つ
        種内名）を優先する（名前の文字列の解釈に頼らない）。無ければ名前（無ければ registry の学名）から。"""
        canonical, reg_name = self._taxon_row(taxon_id) if taxon_id else (None, None)
        parsed = norm_taxon_id(bare_name(scientific_name or reg_name))
        if canonical:
            base = norm_taxon_id(canonical)
            return parsed if parsed.startswith(base + " ") else base
        return parsed

    def resolve(self, region_id: str, scientific_name: str | None, taxon_id: str | None = None) -> Hit | None:
        ck = (region_id, scientific_name, taxon_id)
        if ck not in self._cache:
            key = self._key(scientific_name, taxon_id)
            self._cache[ck] = self._resolve(region_id, key) if key else None
        return self._cache[ck]

    def _resolve(self, region_id: str, key: str) -> Hit | None:
        hit = self._pref.get(region_id, {}).get(key)
        if hit:
            return Hit(hit[0], hit[1], RULE_PREF_EXACT, key)
        nat = self._national.get(key)
        if nat:
            return Hit(nat, NATIONAL_SOURCE, RULE_NATIONAL_EXACT, key)
        if not _is_infraspecific(key):   # 種レベルの記録だけ（亜種名の記録は完全一致で見た）
            sub = self._subspecies.get(region_id, {}).get(key)
            if sub:
                return Hit(sub[0], sub[1], RULE_SUBSPECIES, key)
        return None
