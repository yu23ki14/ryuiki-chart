"""occurrence の赤リスト判定の補完（b06 が `red_list_category`/`red_list_source` が NULL の記録に対して呼ぶ）。

出典（GBIF/iNat は m03、eDNA はアダプタ）が自分で付けた値は触らない。付けていない記録（モニタリングサイト1000 の
アダプタ等）にだけ、m03 と同じ優先順位（地域の県版 → 全国版）で学名から引く。2026-10-12 オーナー決定:

1. 県版（記録の地域が一致するリスト）に学名が完全一致 → その県版のカテゴリー。`red_list_source` = list_id。
2. 全国版（`ryuiki.taxa.redlist_national`）に学名が完全一致 → `red_list_source` = 'national'（m03 の NATIONAL_SOURCE）。
3. 種レベルの記録（二名法）で、同じ地域の県版が**その種の亜種・変種だけ**を載せているとき → 該当。
   `red_list_source` = '<list_id>+subspecies:<掲載名>'（亜種で載っていることが利用側に見える）。複数の亜種が
   載っているときは最も深刻なカテゴリー（`redlist_category.yaml` の rank。同順位なら新しい版・掲載名の辞書順）の
   亜種を採り、その掲載名を出す。種で完全一致する掲載があれば 1.（種レベルが勝つ）。
   **全国版の亜種掲載は種の記録を該当にしない**（地域が決められないため）。

学名の正規化は `taxon_namespaces.norm_taxon_id`（m03・c25・c28 と同じ）。カテゴリーの文字列は m03 の `_cat_text`
（`カテゴリー（コード）`）と同じ形。県版の原本は registry の `taxon_assessment`（kind=red_list の list の行。
list の地域は `registry/taxon/assessment_list.yaml`）、全国版は原本の `taxa`。m03 の再実行も原本への書き込みも要らない。
"""
from __future__ import annotations

import pathlib
import sqlite3
from collections import defaultdict

from reconcile.common import load_yaml   # yaml は遅延 import（v2 パイプラインの import 閉包は PyYAML を要求しない。common.py 参照）
from taxon_namespaces import binom_of, norm_taxon_id

_TAXON_REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "taxon"

NATIONAL_SOURCE = "national"   # m03_organisms.NATIONAL_SOURCE と同じ値（m03 は収集系の依存を引くので import しない）
SUBSPECIES_MARK = "+subspecies:"

RULE_PREF_EXACT = "pref_exact"
RULE_NATIONAL_EXACT = "national_exact"
RULE_SUBSPECIES = "subspecies"


_RANK_MARKERS = frozenset({"var.", "subsp.", "ssp.", "f.", "subvar.", "forma", "fo."})


def bare_name(name: str | None) -> str:
    """命名者・年を落とした学名（属 + 小文字始まりの種小名・種内名。`var.`/`subsp.`/`f.` の標識は残す）。
    `Columba janthina janthina (Temminck, 1830)` -> `Columba janthina janthina`。GBIF/iNat の名前は元から命名者を
    含まないが、モニ1000 のアダプタ（原本 `moni1000_counts` の学名）や registry の `taxon.scientific_name` は含む。"""
    toks = (name or "").split()
    if not toks:
        return ""
    out = [toks[0]]
    for t in toks[1:]:
        if t in _RANK_MARKERS or (t[0].islower() and t.isalpha()):
            out.append(t)
        else:
            break
    return " ".join(out)


def _cat_text(category_ja: str, code: str | None) -> str:
    return f"{category_ja}（{code}）" if code else category_ja   # m03 と同じ形


class RedListResolver:
    """(region_id, scientific_name) -> (red_list_category, red_list_source, rule) | None。`work` は src/reg を ATTACH 済み。"""

    def __init__(self, work: sqlite3.Connection):
        region_of = {e["list_id"]: e["region"] for e in load_yaml(_TAXON_REGISTRY_DIR / "assessment_list.yaml")["lists"]
                     if e["kind"] == "red_list"}
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
        # 亜種掲載: region -> 種の正規化名 -> [(rank, list_year, 掲載名, カテゴリー, list_id)]
        sub: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for list_id, list_year, name, cat_raw, code in rows:
            region = region_of[list_id]
            key = norm_taxon_id(name)
            text = _cat_text(cat_raw, code)
            self._pref[region].setdefault(key, (text, list_id))
            binom = norm_taxon_id(binom_of(name))
            if binom != key:   # 亜種・変種などの掲載
                rank = (cats.get(code) or {}).get("rank")
                sub[region][binom].append((rank if rank is not None else -1, list_year or 0, name.strip(), text, list_id))
        self._subspecies: dict[str, dict[str, tuple[str, str]]] = {}
        for region, by_binom in sub.items():
            best = {}
            for binom, cands in by_binom.items():
                # 最も深刻（rank 大）→ 新しい版 → 掲載名の辞書順（決定的）
                r, _y, name, text, list_id = sorted(cands, key=lambda c: (-c[0], -c[1], c[2]))[0]
                best[binom] = (text, f"{list_id}{SUBSPECIES_MARK}{name}")
            self._subspecies[region] = best
        self._national = {
            norm_taxon_id(tid): rn for tid, rn in work.execute(
                "SELECT taxon_id, redlist_national FROM src.taxa WHERE redlist_national IS NOT NULL AND redlist_national != ''"
            ) if not tid.startswith("wamei:")
        }
        self._cache: dict[tuple[str, str], tuple[str, str, str] | None] = {}
        self._work = work
        self._taxon_name: dict[str, str | None] = {}

    def _name_of_taxon(self, taxon_id: str) -> str | None:
        if taxon_id not in self._taxon_name:
            row = self._work.execute("SELECT scientific_name FROM reg.taxon WHERE taxon_id = ?", (taxon_id,)).fetchone()
            self._taxon_name[taxon_id] = row[0] if row else None
        return self._taxon_name[taxon_id]

    def resolve(self, region_id: str, scientific_name: str | None, taxon_id: str | None = None) -> tuple[str, str, str] | None:
        """学名が無い記録（里地調査のアダプタ等）は `taxon_id` の registry 上の学名で引く。"""
        if not scientific_name and taxon_id:
            scientific_name = self._name_of_taxon(taxon_id)
        key = norm_taxon_id(bare_name(scientific_name))
        if not key:
            return None
        ck = (region_id, key)
        if ck not in self._cache:
            self._cache[ck] = self._resolve(region_id, key)
        return self._cache[ck]

    def _resolve(self, region_id: str, key: str) -> tuple[str, str, str] | None:
        hit = self._pref.get(region_id, {}).get(key)
        if hit:
            return hit[0], hit[1], RULE_PREF_EXACT
        nat = self._national.get(key)
        if nat:
            return nat, NATIONAL_SOURCE, RULE_NATIONAL_EXACT
        if len(key.split(" ")) == 2:   # 種レベルの記録だけ（亜種名の記録は完全一致で見た）
            sub = self._subspecies.get(region_id, {}).get(key)
            if sub:
                return sub[0], sub[1], RULE_SUBSPECIES
        return None
