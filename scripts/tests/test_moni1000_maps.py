"""モニ1000 の名寄せ表（registry/taxon/moni1000_name_map.csv）・地点対応表（registry/source/moni1000_site_map.csv）の検査と、
下書きツール m10_moni1000_name_map の判定規則のテスト。

表の中身の検査は、registry.sqlite・入力 CSV（data/ 配下。gitignore 済みで CI には無い）があるときだけ回す。"""
import collections
import csv
import pathlib
import sqlite3

import pytest

import m10_moni1000 as m10
import m10_moni1000_name_map as nmap

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "data" / "db" / "registry.sqlite"
HAVE_INPUT = all((m10.DEFAULT_CSV_DIR / c["csv"]).exists() for c in m10.SOURCES.values())

VALID_BASIS = {"sci", "ja_unique", "ja_paired_sci", "curated", "exclude:non_wild", "exclude:non_species",
               "exclude:unresolved_taxon"}


def rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


NAME_MAP = rows(m10.DEFAULT_NAME_MAP)
SITE_MAP = rows(m10.DEFAULT_SITE_MAP)


def test_name_map_shape():
    keys = [(r["source_id"], r["name_key"]) for r in NAME_MAP]
    assert len(keys) == len(set(keys))
    assert {r["source_id"] for r in NAME_MAP} <= set(m10.SOURCES)
    for r in NAME_MAP:
        b = r["basis"]
        assert b in VALID_BASIS or b.startswith("pending:"), r
        if b in m10.BASIS_RESOLUTION:
            assert r["taxon_id"].startswith("common:taxon:"), r          # 名寄せした語には taxon_id
        else:
            assert r["taxon_id"] == "", r                               # 除外・保留の語に taxon_id は無い
        if r["source_id"] in m10.SCI_SOURCES:
            assert "|" in r["name_key"], r                              # 学名のある出典は「和名|学名」
    for r in NAME_MAP:
        if r["basis"] == "curated":
            assert r["note"], f"curated には理由（note）が要る: {r}"


def test_site_map_shape():
    keys = [(r["source_id"], r["site_key"]) for r in SITE_MAP]
    assert len(keys) == len(set(keys))
    assert {r["source_id"] for r in SITE_MAP} == set(m10.SOURCES)
    for r in SITE_MAP:
        assert r["basis"] in ("name", "coord_municipality", "none"), r
        assert (r["basis"] == "none") == (r["place_id"] == ""), r
        assert r["site_name_ja"], r
        if r["place_id"]:
            assert r["place_id"].startswith("jp-14:place:site.moni1000.kn"), r


@pytest.mark.skipif(not REGISTRY.exists(), reason="registry.sqlite が無い（CI）")
def test_ids_exist_in_registry():
    con = sqlite3.connect(f"file:{REGISTRY}?mode=ro", uri=True)
    taxa = {t for (t,) in con.execute("SELECT taxon_id FROM taxon")}
    places = {p for (p,) in con.execute("SELECT place_id FROM place")}
    con.close()
    assert [r for r in NAME_MAP if r["taxon_id"] and r["taxon_id"] not in taxa] == []
    assert [r for r in SITE_MAP if r["place_id"] and r["place_id"] not in places] == []


@pytest.mark.skipif(not HAVE_INPUT, reason="data/processed の入力 CSV が無い（CI）")
def test_maps_cover_every_input_name_and_site():
    by = m10.normalize_all()
    names = {(sid, r["_name_key"]) for sid, rs in by.items() for r in rs}
    sites = {(sid, r["site_key"]) for sid, rs in by.items() for r in rs}
    assert names == {(r["source_id"], r["name_key"]) for r in NAME_MAP}      # 余りも不足も無い
    # 地点対応表は、記録の無い地点（出典の sites CSV にだけ在るもの）を含んでよい。記録のある地点は全部在ること
    assert sites <= {(r["source_id"], r["site_key"]) for r in SITE_MAP}


@pytest.mark.skipif(not (HAVE_INPUT and REGISTRY.exists()), reason="入力 CSV か registry.sqlite が無い（CI）")
def test_name_map_matches_draft_tool():
    existing = m10.load_name_map()
    drafted, _, stale = nmap.build(m10.DEFAULT_CSV_DIR, REGISTRY, existing)
    assert stale == []
    key = lambda r: (r["source_id"], r["name_key"])  # noqa: E731
    assert sorted(({f: r.get(f, "") for f in nmap.FIELDS} for r in drafted), key=key) == \
        sorted(({f: r.get(f, "") for f in nmap.FIELDS} for r in NAME_MAP), key=key)


# ── 判定規則（registry を使わない小さな fixture） ───────────

def taxon(tid, sci, ja=None, status="accepted", acc=None, cls="Aves", order="Passeriformes"):
    return {"taxon_id": tid, "sci": sci, "status": status, "accepted_taxon_id": acc, "ja": ja, "class": cls,
            "order": order}


def tables(*ts):
    by_sci, by_ja = collections.defaultdict(list), collections.defaultdict(list)
    for t in ts:
        by_sci[t["sci"].split(" (")[0]].append(t)
        if t["ja"]:
            by_ja[t["ja"]].append(t)
    return by_sci, by_ja


B = "moni1000_satochi_bird"
F = "moni1000_forest_bird"


def test_decide_exclusions_come_first():
    s, j = tables(taxon("common:taxon:gbif.1", "Homo sapiens", "ヒト", cls="Mammalia"))
    assert nmap.decide(B, "ヒト", None, s, j)[1] == "exclude:non_wild"
    assert nmap.decide(B, "カラス科", None, s, j)[1] == "exclude:non_species"
    assert nmap.decide(B, "ハイタカ類", None, s, j)[1] == "exclude:non_species"
    assert nmap.decide(F, "sp.1", None, s, j)[1] == "exclude:non_species"
    assert nmap.decide(B, "不明", None, s, j)[1] == "exclude:non_species"


def test_decide_ja_unique_and_group_filter():
    s, j = tables(taxon("common:taxon:gbif.1", "Cuculus poliocephalus", "ホトトギス"),
                  taxon("common:taxon:gbif.2", "Tricyrtis hirta", "ホトトギス", cls="Liliopsida", order="Liliales"))
    assert nmap.decide(B, "ホトトギス", None, s, j)[:2] == ("common:taxon:gbif.1", "ja_unique")


def test_decide_multiple_candidates_is_pending_not_chosen():
    s, j = tables(taxon("common:taxon:gbif.1", "Parus minor", "シジュウカラ"),
                  taxon("common:taxon:gbif.2", "Parus major", "シジュウカラ"))
    tid, basis, note, _ = nmap.decide(B, "シジュウカラ", None, s, j)
    assert (tid, basis) == ("", "pending:ambiguous") and "gbif.1" in note and "gbif.2" in note


def test_decide_prefers_primary_then_gbif_duplicates():
    s, j = tables(taxon("common:taxon:gbif.1", "Passer montanus (L.)", "スズメ"),
                  taxon("common:taxon:inat.9", "Passer montanus"),
                  taxon("common:taxon:gbif.3", "Passer montanus (L.)", "スズメ（旧）", status="unresolved"))
    # 学名: accepted だけに絞る → GBIF 由来に絞る（iNaturalist の同名重複を除く）
    assert nmap.decide(F, "スズメ", "Passer montanus", s, j)[:2] == ("common:taxon:gbif.1", "sci")


def test_decide_sci_wins_over_ja_and_notes_it():
    s, j = tables(taxon("common:taxon:gbif.1", "Horornis diphone", None),
                  taxon("common:taxon:gbif.2", "Cettia diphone", "ウグイス"))
    tid, basis, note, _ = nmap.decide(F, "ウグイス", "Horornis diphone", s, j)
    assert (tid, basis) == ("common:taxon:gbif.1", "sci") and "gbif.2" in note


def test_decide_unresolved_when_nothing_in_registry():
    s, j = tables()
    assert nmap.decide(B, "ツミ", None, s, j)[1] == "exclude:unresolved_taxon"
    assert nmap.clean_ja("フクロウ？") == "フクロウ"
