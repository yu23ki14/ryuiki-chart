"""c89c_edna_taxon_map（神奈川県 eDNA の名前 → taxon の対応表。docs/plans/KANAGAWA_EDNA.md §4）。

ネットワークも registry.sqlite も使わない（registry の行と GBIF の応答は偽物を注入する）。
"""
from __future__ import annotations

import csv
import json

import pytest

import c89c_edna_taxon_map as c89c
from c89c_edna_taxon_map import (
    Dictionary, GbifClient, Registry, build, clean_core, name_key, parse_part, plain_binomial, sci_genus_hint,
)


# ---------------------------------------------------------------- フィクスチャ
def _tx(tid, sci, rank="species", vern=None, binom=None, family=None, accepted=None, status="accepted"):
    return {"taxon_id": tid, "scientific_name": sci, "canonical_binomial": binom if binom is not None else " ".join((sci or "").split(" ")[:2]),
            "rank": rank, "family": family, "vernacular_name_ja": vern, "status": status, "accepted_taxon_id": accepted}


REGISTRY_ROWS = [
    _tx("common:taxon:gbif.2440954", "Cervus nippon Temminck, 1838", vern="ニホンジカ"),
    _tx("common:taxon:inat.42210", "Cervus nippon"),
    _tx("common:taxon:gbif.7705930", "Sus scrofa"),
    _tx("common:taxon:inat.42134", "Sus scrofa"),
    _tx("common:taxon:gbif.100", "Anguilla japonica Temminck & Schlegel, 1846", vern="ニホンウナギ", family="Anguillidae"),
    _tx("common:taxon:gbif.200", "Hemitrygon akajei (Müller & Henle, 1841)", vern="アカエイ"),
    _tx("common:taxon:gbif.201", "Dasyatis akajei (Müller & Henle, 1841)", vern="アカエイ",
        accepted="common:taxon:gbif.200"),
    _tx("common:taxon:gbif.300", "Tenodera sinensis Saussure, 1871", vern="オオカマキリ"),
    _tx("common:taxon:gbif.301", "Tenodera aridifolia Stoll, 1813", vern="オオカマキリ"),
    _tx("common:taxon:gbif.400", "Trypoxylus dichotomus dichotomus (Linnaeus, 1771)", rank="subspecies",
        vern="カブトムシ", binom="Trypoxylus dichotomus"),
    _tx("common:taxon:gbif.401", "Trypoxylus dichotomus (Linnaeus, 1758)", vern=None),
    _tx("common:taxon:ryuiki-taxa.wamei.ugui", None, rank="", vern="ウグイ", binom=""),
    _tx("common:taxon:gbif.500", "Lucilia Robineau-Desvoidy, 1830", rank="genus", binom="Lucilia Robineau-Desvoidy,"),
    _tx("common:taxon:inat.501", "Lucilia", rank="genus", binom="Lucilia"),
    _tx("common:taxon:gbif.600", "Rhinogobius", rank="genus", binom="Rhinogobius"),
    _tx("common:taxon:gbif.700", "Gobiidae", rank="family", binom="Gobiidae"),
]


def _read(i, adopted, *, sci="", cls="昆虫綱", order="ハエ目", fam="クロバエ科", gen="Lucilia属", det=1, stem="r7_x"):
    return {"read_id": f"{stem}:{i}", "site_key": f"{stem}:K1", "class_ja": cls, "order_ja": order, "family_ja": fam,
            "genus_ja": gen, "name_raw": adopted, "name_adopted": adopted, "name_sci_raw": sci, "reads": det,
            "is_detected": det}


def _gbif_getter(table):
    """table: {(url末尾, name): 応答}。呼ばれた回数を数える。"""
    calls = []

    def get(url, params=None):
        calls.append((url, dict(params or {})))
        if "match" in url:
            return table.get(params["name"], {"matchType": "NONE"})
        key = url.rsplit("/", 1)[1]
        return table[f"species/{key}"]
    get.calls = calls
    return get


def _match(key, canonical, rank="SPECIES", **kw):
    r = {"usageKey": key, "scientificName": f"{canonical} Auth, 1900", "canonicalName": canonical, "rank": rank,
         "status": "ACCEPTED", "matchType": "EXACT", "kingdom": "Animalia", "phylum": "Arthropoda",
         "class": "Insecta", "order": "Diptera", "family": "Calliphoridae"}
    r.update(kw)
    return r


def _run(reads, *, gbif=None, existing_map=None, existing_supp=None, rows=REGISTRY_ROWS, dictionary=None):
    client = GbifClient(gbif) if gbif is not None else None
    return build(reads, Registry(rows), client, existing_map, existing_supp, dictionary)


def _by_key(out):
    return {r["name_key"]: r for r in out[0]}


# ---------------------------------------------------------------- 名前の正規化・分解
def test_name_key_normalization():
    assert name_key("Simulium aeneifacies（注）") == "simuliumaeneifacies"
    assert name_key("Nemertopsis cf. bivittata") == "nemertopsisbivittata"
    assert name_key("コイ（飼育型）") == name_key("コイ（野生型）") == "コイ"
    assert name_key("ＡＢ　ｃｄ") == "abcd"           # NFKC・空白除去・小文字化
    assert name_key("A（注）/ B（和名なし）") == "a/b"  # 併記は残す
    assert name_key("Foo（x（y）z）bar") == "foobar"   # 入れ子の括弧書き


def test_clean_core_returns_notes():
    core, notes = clean_core("Stenostomum sthenum（注）/Stenostomum leucops（注）")
    assert core == "Stenostomum sthenum / Stenostomum leucops" or core.count("/") == 1
    assert notes == ["(注)", "(注)"]


@pytest.mark.parametrize("raw,kind,latin,ja", [
    ("Rana ornativentris", "latin_species", "Rana ornativentris", None),
    ("Nemertopsis cf. bivittata EZ-2019", "latin_species", "Nemertopsis bivittata", None),
    ("Acanthochitona sp. B DJE-2018", "latin_genus", "Acanthochitona", None),
    ("Pristina aequiseta complex sp. CEB", "latin_genus", "Pristina", None),
    ("Hierodula属の一種", "latin_genus", "Hierodula", None),
    ("Allactoneuraの一種", "latin_genus", "Allactoneura", None),
    ("Osmylidae属の一種 EMHAU-1", "latin_family", "Osmylidae", None),
    ("ニホンジカ", "ja_species", None, "ニホンジカ"),
    ("ホソミユスリカ属の一種", "ja_genus", None, "ホソミユスリカ属"),
    ("ユキシタカワゲラ属1", "ja_genus", None, "ユキシタカワゲラ属"),
    ("ツヤミドリカワゲラ属未同定種2", "ja_genus", None, "ツヤミドリカワゲラ属"),
    ("アメマス類", "ja_group", None, "アメマス類"),
    ("アカイエカ種群", "ja_group", None, "アカイエカ種群"),
    ("ハマダモノアラガイの近縁種", "ja_group", None, "ハマダモノアラガイの近縁種"),
    ("クサリヒメウズムシ科", "ja_family", None, "クサリヒメウズムシ科"),
    ("Fコカゲロウ", "ja_informal", None, "Fコカゲロウ"),
    ("トガリミズミミズ種複合体 CEA", "ja_complex", None, "トガリミズミミズ種複合体 CEA"),
    ("シロハラコカゲロウ-1", "ja_species", None, "シロハラコカゲロウ"),
])
def test_parse_part(raw, kind, latin, ja):
    p = parse_part(clean_core(raw)[0])
    assert (p["kind"], p["latin"], p["ja"]) == (kind, latin, ja)


def test_plain_binomial_and_genus_hint():
    assert plain_binomial("Rana ornativentris") == "Rana ornativentris"
    assert plain_binomial("Baetis sp.") is None
    assert plain_binomial("A b/C d") is None
    assert sci_genus_hint("Baetis sp.") == "Baetis"
    assert sci_genus_hint("Pristina aequiseta complex sp. CEB") == "Pristina"
    assert sci_genus_hint("Rana ornativentris") is None


# ---------------------------------------------------------------- T1・T2（registry）
def test_t1_scientific_binomial_prefers_exact_name_then_gbif_namespace():
    out = _by_key(_run([_read(1, "Cervus nippon"), _read(2, "Sus scrofa")]))
    assert out["cervusnippon"]["taxon_id"] == "common:taxon:inat.42210"      # 著者名の付かない正規形（kuma の規則）
    assert out["cervusnippon"]["tier"] == "T1"
    assert out["susscrofa"]["taxon_id"] == "common:taxon:gbif.7705930"        # 両方正規形なら gbif 名前空間
    assert "prefer_gbif_namespace" in out["susscrofa"]["evidence"]


def test_t2_vernacular_and_synonym_handling():
    out = _by_key(_run([_read(1, "ニホンウナギ"), _read(2, "アカエイ"), _read(3, "カブトムシ")]))
    assert (out["ニホンウナギ"]["tier"], out["ニホンウナギ"]["taxon_id"]) == ("T2", "common:taxon:gbif.100")
    assert out["アカエイ"]["taxon_id"] == "common:taxon:gbif.200"            # 同物異名（accepted 付き）を外す
    assert out["カブトムシ"]["taxon_id"] == "common:taxon:gbif.401"          # 亜種の和名 → 親の種
    assert "infraspecific_vernacular->species" in out["カブトムシ"]["evidence"]


def test_ambiguous_vernacular_goes_to_pending_not_t4():
    out, supp, pending = _run([_read(1, "オオカマキリ")])
    assert out == [] and supp == []
    assert pending[0][0] == "オオカマキリ" and "ambiguous_vernacular" in pending[0][2]


def test_sci_column_wins_over_registry_vernacular_and_records_the_disagreement():
    out = _by_key(_run([_read(1, "オオカマキリ", sci="Tenodera sinensis")]))
    assert out["オオカマキリ"]["taxon_id"] == "common:taxon:gbif.300" and out["オオカマキリ"]["tier"] == "T1"


def test_registry_unresolved_wamei_taxon_is_reused_for_vernacular():
    out = _by_key(_run([_read(1, "ウグイ")]))
    assert out["ウグイ"]["taxon_id"] == "common:taxon:ryuiki-taxa.wamei.ugui" and out["ウグイ"]["tier"] == "T2"
    # 同じ和名に学名（registry の種）が付いた行があれば、そちらを採る（未照合の和名 taxon より優先）
    out2 = _by_key(_run([_read(1, "ウグイ", sci="Cervus nippon")]))
    assert out2["ウグイ"]["tier"] == "T1" and out2["ウグイ"]["taxon_id"] == "common:taxon:inat.42210"


# ---------------------------------------------------------------- T3（GBIF）
def test_t3_gbif_exact_species_adds_supplement_row_with_classification():
    gbif = _gbif_getter({"Foo barus": _match(900, "Foo barus")})
    out, supp, pending = _run([_read(1, "Foo barus（注）")], gbif=gbif)
    assert pending == []
    row = out[0]
    assert (row["tier"], row["taxon_id"], row["rank"]) == ("T3", "common:taxon:gbif.900", "species")
    s = supp[0]
    assert (s["taxon_id"], s["gbif_taxon_key"], s["basis"], s["rank"]) == ("common:taxon:gbif.900", "900", "gbif_match", "species")
    assert (s["kingdom"], s["class"], s["order"], s["family"]) == ("Animalia", "Insecta", "Diptera", "Calliphoridae")
    assert s["canonical_binomial"] == "" and s["scientific_name"].startswith("Foo barus")
    assert gbif.calls[0][1]["name"] == "Foo barus"


def test_t3_fish_class_is_blank_like_registry_fish_rows():
    gbif = _gbif_getter({"Pisces fakeus": _match(901, "Pisces fakeus", phylum="Chordata", **{"class": "Actinopterygii"})})
    _, supp, _ = _run([_read(1, "Pisces fakeus", cls="硬骨魚綱")], gbif=gbif)
    assert supp[0]["class"] == "" and supp[0]["phylum"] == "Chordata"


def test_t3_key_already_in_registry_adds_no_supplement_row():
    gbif = _gbif_getter({"Anguilla bicolor": _match(100, "Anguilla bicolor")})
    out, supp, _ = _run([_read(1, "Anguilla bicolor")], gbif=gbif)
    assert out[0]["taxon_id"] == "common:taxon:gbif.100" and supp == []


@pytest.mark.parametrize("resp,why", [
    ({"matchType": "FUZZY"}, "gbif_fuzzy"),
    ({"matchType": "NONE"}, "gbif_none"),
    ({"matchType": "HIGHERRANK"}, "gbif_higherrank"),
    (_match(1, "Foo barus", kingdom="Plantae"), "gbif_kingdom_Plantae"),
    (_match(1, "Foo barus", rank="SUBSPECIES"), "gbif_rank_subspecies"),
])
def test_t3_unusable_gbif_answers_go_to_pending(resp, why):
    out, supp, pending = _run([_read(1, "Foo barus", gen="-", fam="-")], gbif=_gbif_getter({"Foo barus": resp}))
    assert out == [] and supp == []
    assert why in pending[0][2]


def test_t3_unreachable_gbif_and_offline_go_to_pending():
    def boom(url, params=None):
        raise RuntimeError("down")
    assert "gbif_unreachable" in _run([_read(1, "Foo barus")], gbif=boom)[2][0][2]
    assert "gbif_offline" in _run([_read(1, "Foo barus")])[2][0][2]


def test_t3_synonym_resolves_to_accepted_name():
    gbif = _gbif_getter({
        "Old namus": _match(910, "Old namus", status="SYNONYM", acceptedUsageKey=911),
        "species/911": {"key": 911, "scientificName": "New namus Auth, 1900", "canonicalName": "New namus",
                        "rank": "SPECIES", "kingdom": "Animalia", "phylum": "Arthropoda", "class": "Insecta",
                        "order": "Diptera", "family": "Calliphoridae"},
    })
    out, supp, _ = _run([_read(1, "Old namus")], gbif=gbif)
    assert out[0]["taxon_id"] == "common:taxon:gbif.911" and "synonym_of(910)" in out[0]["evidence"]
    assert supp[0]["scientific_name"].startswith("New namus")


def test_gbif_cache_avoids_second_call():
    gbif = _gbif_getter({"Foo barus": _match(900, "Foo barus")})
    client = GbifClient(gbif)
    build([_read(1, "Foo barus")], Registry(REGISTRY_ROWS), client)
    build([_read(1, "Foo barus")], Registry(REGISTRY_ROWS), client)
    assert len(gbif.calls) == 1


# ---------------------------------------------------------------- T4（和名のみ）
def test_t4_name_only_taxon_has_no_scientific_name_and_a_slug_id():
    out, supp, pending = _run([_read(1, "シマアメンボ")])
    assert pending == []
    row = out[0]
    assert row["tier"] == "T4" and row["scientific_name"] == "" and row["vernacular_name_ja"] == "シマアメンボ"
    assert row["taxon_id"] == "common:taxon:kanagawa-edna." + c89c.slugify_local_key("シマアメンボ")
    s = supp[0]
    assert (s["basis"], s["scientific_name"], s["gbif_taxon_key"], s["class"], s["kingdom"]) == (
        "name_only", "", "", "Insecta", "Animalia")


def test_t4_unknown_class_stops():
    with pytest.raises(ValueError, match="CLASS_JA_TABLE"):
        _run([_read(1, "シマアメンボ", cls="未知綱")])


def test_t4_class_dash_is_recovered_from_the_order():
    reads = [_read(1, "ニホンウナギ", cls="硬骨魚綱", order="カメ目"), _read(2, "スッポンもどき", cls="-", order="カメ目")]
    out, supp, _ = _run(reads, rows=[])
    assert supp and supp[0]["phylum"] == "Chordata"


# ---------------------------------------------------------------- T5（属止まり・併記）
def test_t5_slash_names_reduce_to_the_sheet_genus_and_flag_it():
    out = _by_key(_run([_read(1, "A属のX/Yの種", gen="Lucilia属"), _read(2, "スネアカキンバエ/コガネキンバエ", gen="Lucilia属")]))
    r = out["スネアカキンバエ/コガネキンバエ"]
    assert (r["tier"], r["taxon_id"], r["rank"]) == ("T5", "common:taxon:inat.501", "genus")  # 正規形の属を採る
    assert "name_ambiguous" in r["evidence"] and "rank_reduced" in r["evidence"]


def test_t5_genus_name_with_latin_sheet_genus_and_family_fallback():
    out = _by_key(_run([
        _read(1, "ホソミユスリカ属の一種", gen="Rhinogobius属"),
        _read(2, "ヨシノボリ類", gen="-", fam="Gobiidae"),
    ]))
    assert out["ホソミユスリカ属の一種"]["taxon_id"] == "common:taxon:gbif.600"
    assert out["ヨシノボリ類"]["taxon_id"] == "common:taxon:gbif.700" and out["ヨシノボリ類"]["rank"] == "family"


def test_t5_genus_hint_from_sci_column_beats_the_sheet():
    out = _by_key(_run([_read(1, "Fコカゲロウ", sci="Rhinogobius sp.", gen="コカゲロウ属")]))
    assert out["fコカゲロウ"]["taxon_id"] == "common:taxon:gbif.600"


def test_t5_japanese_genus_uses_latin_genus_of_a_resolved_species_in_the_same_genus():
    reads = [
        _read(1, "ニホンウナギ", gen="ウナギ属", fam="ウナギ科", cls="硬骨魚綱", order="ウナギ目"),
        _read(2, "ウナギ属", gen="ウナギ属", fam="ウナギ科", cls="硬骨魚綱", order="ウナギ目"),
    ]
    rows = REGISTRY_ROWS + [_tx("common:taxon:gbif.110", "Anguilla", rank="genus", binom="Anguilla")]
    out = _by_key(_run(reads, rows=rows))
    assert out["ウナギ属"]["taxon_id"] == "common:taxon:gbif.110" and out["ウナギ属"]["tier"] == "T5"


def test_t5_japanese_genus_without_latin_link_becomes_a_name_only_genus_t4():
    out, supp, _ = _run([_read(1, "ホソミユスリカ属の一種", gen="ホソミユスリカ属")], rows=[])
    assert out[0]["tier"] == "T4" and out[0]["rank"] == "genus" and supp[0]["vernacular_name_ja"] == "ホソミユスリカ属"


# ---------------------------------------------------------------- 決定性・reviewed・入出力
def test_build_is_deterministic_and_order_independent():
    reads = [_read(1, "ニホンウナギ"), _read(2, "シマアメンボ"), _read(3, "Cervus nippon"), _read(4, "シマアメンボ", det=0)]
    a = _run(reads)
    b = _run(list(reversed(reads)))
    assert a == b
    assert [r["name_key"] for r in a[0]] == sorted(r["name_key"] for r in a[0])


def test_reviewed_rows_are_kept_verbatim_and_their_supplement_rows_survive():
    existing = {"オオカマキリ": {"name_key": "オオカマキリ", "rank": "species", "taxon_id": "common:taxon:gbif.300",
                               "scientific_name": "Tenodera sinensis Saussure, 1871", "vernacular_name_ja": "",
                               "tier": "T2", "evidence": "人が決めた", "reviewed": "1"},
                "シマアメンボ": {"name_key": "シマアメンボ", "rank": "species",
                             "taxon_id": "common:taxon:kanagawa-edna.x", "scientific_name": "", "vernacular_name_ja": "シマアメンボ",
                             "tier": "T4", "evidence": "手で作成", "reviewed": "1"}}
    existing_supp = {"common:taxon:kanagawa-edna.x": {"taxon_id": "common:taxon:kanagawa-edna.x", "basis": "name_only"}}
    out, supp, pending = _run([_read(1, "オオカマキリ"), _read(2, "シマアメンボ")], existing_map=existing,
                              existing_supp=existing_supp)
    assert pending == []
    assert [r["evidence"] for r in out] == ["人が決めた", "手で作成"] or {r["evidence"] for r in out} == {"人が決めた", "手で作成"}
    assert [s["taxon_id"] for s in supp] == ["common:taxon:kanagawa-edna.x"]


def test_reviewed_row_pointing_to_unknown_taxon_stops():
    existing = {"シマアメンボ": {"name_key": "シマアメンボ", "rank": "species", "taxon_id": "common:taxon:kanagawa-edna.zzz",
                             "tier": "T4", "evidence": "x", "reviewed": "1"}}
    with pytest.raises(ValueError, match="registry にも supplement にも無い"):
        _run([_read(1, "シマアメンボ")], existing_map=existing)


def test_previous_supplement_taxa_are_not_mistaken_for_registry_taxa():
    rows = REGISTRY_ROWS + [_tx("common:taxon:gbif.900", "Foo barus Auth", vern=None)]
    reg = Registry(rows, exclude_ids={"common:taxon:gbif.900"})
    assert "common:taxon:gbif.900" not in reg.by_id and not reg.species_by_binom.get("Foo barus")


def test_edna_ids_in_registry_are_ignored_by_lookups():
    reg = Registry(REGISTRY_ROWS + [_tx("common:taxon:kanagawa-edna.x", None, rank="species", vern="シマアメンボ", binom="")])
    assert reg.by_vern.get("シマアメンボ") is None


def test_reads_name_key_must_agree_with_name_key_function(tmp_path):
    p = tmp_path / "reads.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["read_id", "name_adopted", "name_raw", "name_key"])
        w.writeheader()
        w.writerow({"read_id": "r7_x:1", "name_adopted": "Foo barus（注）", "name_raw": "Foo barus（注）", "name_key": "foobarus"})
        w.writerow({"read_id": "r7_x:2", "name_adopted": "シマアメンボ", "name_raw": "シマアメンボ", "name_key": "しまあめんぼ"})
    with pytest.raises(ValueError, match="name_key"):
        c89c.read_reads(p)


def test_empty_name_stops():
    with pytest.raises(ValueError, match="名前が空"):
        _run([_read(1, "  ")])


def test_main_offline_writes_files_only_when_nothing_is_pending(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "registry.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE taxon (taxon_id TEXT, scientific_name TEXT, canonical_binomial TEXT, rank TEXT,"
                " family TEXT, vernacular_name_ja TEXT, status TEXT, accepted_taxon_id TEXT, kingdom TEXT)")
    for r in REGISTRY_ROWS:
        con.execute("INSERT INTO taxon VALUES (?,?,?,?,?,?,?,?,?)",
                    (r["taxon_id"], r["scientific_name"], r["canonical_binomial"], r["rank"], r["family"],
                     r["vernacular_name_ja"], r["status"], r["accepted_taxon_id"], "Animalia"))
    con.commit()
    con.close()
    reads = tmp_path / "reads.csv"
    rows = [_read(1, "ニホンウナギ"), _read(2, "シマアメンボ")]
    with open(reads, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    nm, sp = tmp_path / "nm.csv", tmp_path / "supp.csv"
    argv = ["--offline", "--reads", str(reads), "--registry-db", str(db), "--name-map", str(nm), "--supplement", str(sp)]
    assert c89c.main(argv) == 0
    mapped = list(csv.DictReader(open(nm, encoding="utf-8")))
    assert [m["tier"] for m in mapped] == ["T2", "T4"] or {m["tier"] for m in mapped} == {"T2", "T4"}
    assert list(csv.DictReader(open(sp, encoding="utf-8")))[0]["basis"] == "name_only"
    first = nm.read_text(encoding="utf-8")
    assert c89c.main(argv) == 0 and nm.read_text(encoding="utf-8") == first      # 再実行しても同じ（reviewed=0 は作り直し）
    # 確認が残るとき（GBIF が要る名前）は書かずに 1 で終わる。--allow-pending なら書く
    with open(reads, "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=list(rows[0])).writerow(_read(3, "Foo barus"))
    nm.unlink()
    assert c89c.main(argv) == 1 and not nm.exists()
    assert c89c.main(argv + ["--allow-pending"]) == 0 and nm.exists()


# ---------------------------------------------------------------- T2b（出典つきの和名→学名の辞書）
DICT_ROWS = [
    {"vernacular_name_ja": "ホンドタヌキ", "scientific_name": "Cervus nippon Temminck, 1838",
     "source_id": "moe_redlist", "source_ref": "https://example/list.csv#row=5"},
    {"vernacular_name_ja": "ホンドタヌキ", "scientific_name": "Cervus nippon Temminck, 1838",
     "source_id": "kanagawa_redlist", "source_ref": "https://example/k.csv#row=9"},
    {"vernacular_name_ja": "ナゾノムシ", "scientific_name": "Foo barus L.", "source_id": "moe_redlist", "source_ref": "u#row=1"},
    {"vernacular_name_ja": "ナゾノムシ", "scientific_name": "Foo bazus L.", "source_id": "kanagawa_redlist", "source_ref": "u#row=2"},
    {"vernacular_name_ja": "モノノムシ", "scientific_name": "Foo quxus L.", "source_id": "moe_redlist", "source_ref": "u#row=3"},
    {"vernacular_name_ja": "空", "scientific_name": "", "source_id": "moe_redlist", "source_ref": "u#row=4"},
]


def test_t2b_dictionary_resolves_wamei_through_t1_and_keeps_provenance():
    out = _by_key(_run([_read(1, "ホンドタヌキ")], dictionary=Dictionary(DICT_ROWS)))
    r = out["ホンドタヌキ"]
    assert (r["tier"], r["taxon_id"]) == ("T2b", "common:taxon:inat.42210")
    assert "moe_redlist:https://example/list.csv#row=5" in r["evidence"] and "2行" in r["evidence"]


def test_t2b_goes_through_gbif_when_the_species_is_not_in_the_registry():
    gbif = _gbif_getter({"Foo quxus": _match(950, "Foo quxus")})
    out, supp, pending = _run([_read(1, "モノノムシ")], gbif=gbif, dictionary=Dictionary(DICT_ROWS))
    assert pending == [] and out[0]["tier"] == "T2b" and supp[0]["taxon_id"] == "common:taxon:gbif.950"
    # GBIF が使えなければ T4 に落とさず確認へ
    _, _, pending = _run([_read(1, "モノノムシ")], dictionary=Dictionary(DICT_ROWS))
    assert "gbif_offline" in pending[0][2]


def test_t2b_homonym_goes_to_pending_and_unknown_names_stay_t4():
    out, supp, pending = _run([_read(1, "ナゾノムシ"), _read(2, "シマアメンボ")], dictionary=Dictionary(DICT_ROWS))
    assert "dictionary_ambiguous" in pending[0][2]
    assert out[0]["tier"] == "T4"


def test_t5_japanese_genus_prefers_the_family_over_a_name_only_genus():
    rows = REGISTRY_ROWS
    out = _by_key(_run([_read(1, "ホソミユスリカ属の一種", gen="ホソミユスリカ属", fam="Gobiidae")], rows=rows))
    r = out["ホソミユスリカ属の一種"]
    assert (r["tier"], r["taxon_id"], r["rank"]) == ("T5", "common:taxon:gbif.700", "family")


# ---------------------------------------------------------------- 階級を落として受ける・和名の曖昧さの解消
def test_species_missing_in_gbif_falls_back_to_genus_then_sheet_family():
    gbif = _gbif_getter({"Foo": _match(960, "Foo", rank="GENUS")})   # 種 Foo barus は無い（NONE）、属 Foo はある
    out, supp, _ = _run([_read(1, "Foo barus（注）", gen="Foo属")], gbif=gbif)
    r = out[0]
    assert (r["tier"], r["taxon_id"], r["rank"]) == ("T5", "common:taxon:gbif.960", "genus")
    assert "GBIF に無い" in r["evidence"] and "rank_reduced" in r["evidence"]
    # 属も無ければシートの科（registry の科）
    out2, _, _ = _run([_read(1, "Foo barus", gen="Foo属", fam="Gobiidae")], gbif=_gbif_getter({}))
    assert out2[0]["taxon_id"] == "common:taxon:gbif.700" and out2[0]["rank"] == "family"


def test_vernacular_matching_several_species_is_settled_by_gbif_accepted_status():
    rows = [
        _tx("common:taxon:gbif.5129588", "Cynthia cardui (Linnaeus, 1758)", vern="ヒメアカタテハ"),
        _tx("common:taxon:gbif.4299368", "Vanessa cardui (Linnaeus, 1758)", vern="ヒメアカタテハ"),
    ]
    gbif = _gbif_getter({"Cynthia cardui": _match(1, "Cynthia cardui", status="SYNONYM"),
                         "Vanessa cardui": _match(4299368, "Vanessa cardui")})
    out, _, pending = _run([_read(1, "ヒメアカタテハ")], gbif=gbif, rows=rows)
    assert pending == [] and out[0]["taxon_id"] == "common:taxon:gbif.4299368" and "受理名は Vanessa cardui" in out[0]["evidence"]


def test_vernacular_lookup_ignores_non_animal_taxa():
    rows = [dict(_tx("common:taxon:gbif.1", "Callicarpa dichotoma (Lour.) K.Koch", vern="コムラサキ"), kingdom="Plantae"),
            dict(_tx("common:taxon:gbif.2", "Apatura metis Frey, 1829", vern="コムラサキ"), kingdom="Animalia")]
    out = _by_key(_run([_read(1, "コムラサキ")], rows=rows))
    assert out["コムラサキ"]["taxon_id"] == "common:taxon:gbif.2"


def test_genus_level_sci_without_period_is_not_a_species():
    assert plain_binomial("Misgurnus sp") is None


# ---------------------------------------------------------------- 共有 supplement・併記の T4・判定の共有
def test_slash_name_that_falls_to_name_only_is_t4_like_other_paths():
    out, supp, _ = _run([_read(1, "ホソミユスリカ/ヒメユスリカ", gen="ホソミユスリカ属")], rows=[])
    assert out[0]["tier"] == "T4" and supp[0]["basis"] == "name_only"


def test_is_ambiguous_uses_the_same_normalization_as_the_resolver():
    assert c89c.is_ambiguous("A属／B属") and c89c.is_ambiguous("タモロコ / ホンモロコ（注）")
    assert not c89c.is_ambiguous("Foo barus（注/参考）")


def test_merge_supplement_keeps_other_sources_rows_and_marks_its_own():
    foreign = {"common:taxon:gbif.1": {"taxon_id": "common:taxon:gbif.1", "evidence": "別の出典"}}
    mine = [{"taxon_id": "common:taxon:gbif.2", "evidence": "GBIF match"},
            {"taxon_id": "common:taxon:kanagawa-edna.x", "evidence": "kanagawa_edna: 和名のみ"}]
    out = c89c.merge_supplement(foreign, mine)
    assert [r["taxon_id"] for r in out] == ["common:taxon:gbif.1", "common:taxon:gbif.2", "common:taxon:kanagawa-edna.x"]
    assert out[0]["evidence"] == "別の出典" and out[1]["evidence"].startswith(c89c.OWNER_MARK)
    assert out[2]["evidence"].count(c89c.OWNER_MARK) == 1
    assert c89c.owned(out[1]) and c89c.owned(out[2]) and not c89c.owned(out[0])
    with pytest.raises(ValueError, match="衝突"):
        c89c.merge_supplement(foreign, [{"taxon_id": "common:taxon:gbif.1", "evidence": "x"}])


def test_main_keeps_foreign_supplement_rows(tmp_path):
    import sqlite3
    db = tmp_path / "registry.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE taxon (taxon_id TEXT, scientific_name TEXT, canonical_binomial TEXT, rank TEXT,"
                " family TEXT, vernacular_name_ja TEXT, status TEXT, accepted_taxon_id TEXT, kingdom TEXT)")
    con.commit()
    con.close()
    reads = tmp_path / "reads.csv"
    rows = [_read(1, "シマアメンボ")]
    with open(reads, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    sp = tmp_path / "supp.csv"
    with open(sp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=c89c.SUPPLEMENT_FIELDS)
        w.writeheader()
        w.writerow({"taxon_id": "common:taxon:gbif.77", "scientific_name": "Other sp", "basis": "gbif_match", "evidence": "他の出典"})
    argv = ["--offline", "--reads", str(reads), "--registry-db", str(db), "--name-map", str(tmp_path / "nm.csv"),
            "--supplement", str(sp)]
    assert c89c.main(argv) == 0 and c89c.main(argv) == 0      # 2 回目でも他の出典の行は残り、自分の行は増えない
    got = list(csv.DictReader(open(sp, encoding="utf-8")))
    assert got[0]["taxon_id"] == "common:taxon:gbif.77" and got[0]["evidence"] == "他の出典"
    assert len(got) == 2 and got[1]["evidence"].startswith(c89c.OWNER_MARK)


# ---------------------------------------------------------------- T2c（GBIF vernacular）・併記の同属・T3 の受け入れ条件
def _vern_getter(search=None, species=None, match=None):
    """species/search（vernacular）・species/{key}・species/match を表で返す偽物。"""
    calls = []

    def get(url, params=None):
        calls.append((url, dict(params or {})))
        if url.endswith("/species/search"):
            return {"results": (search or {}).get(params["q"], [])}
        if url.endswith("/species/match"):
            return (match or {}).get(params["name"], {"matchType": "NONE"})
        return (species or {})[url.rsplit("/", 1)[1]]
    get.calls = calls
    return get


def _hit(key, name, lang="jpn", status="ACCEPTED", **kw):
    r = {"key": key, "rank": "SPECIES", "kingdom": "Animalia", "taxonomicStatus": status,
         "vernacularNames": [{"vernacularName": name, "language": lang}]}
    r.update(kw)
    return r


def _sp(key, canonical, **kw):
    r = {"key": key, "scientificName": canonical + " Auth", "canonicalName": canonical, "rank": "SPECIES",
         "kingdom": "Animalia", "phylum": "Chordata", "class": "Actinopterygii", "order": "Carangiformes",
         "family": "Carangidae"}
    r.update(kw)
    return r


def test_t2c_gbif_vernacular_unique_japanese_exact_match():
    g = _vern_getter(search={"ロウニンアジ": [_hit(1, "ロウニンアジ"), _hit(2, "ロウニンアジ", lang="eng")]},
                     species={"1": _sp(1, "Caranx ignobilis")})
    out, supp, pending = _run([_read(1, "ロウニンアジ", cls="硬骨魚綱", order="スズキ目", fam="アジ科", gen="-")], gbif=g, rows=[])
    assert pending == [] and out[0]["tier"] == "T2c" and out[0]["taxon_id"] == "common:taxon:gbif.1"
    assert "gbif_vernacular" in out[0]["evidence"] and supp[0]["class"] == ""   # 魚は registry と同じく class 空


def test_t2c_ambiguous_wrong_language_and_phylum_mismatch_do_not_resolve():
    two = _vern_getter(search={"ナゾ": [_hit(1, "ナゾ"), _hit(2, "ナゾ")]}, species={"1": _sp(1, "A b"), "2": _sp(2, "C d")})
    assert "gbif_vernacular_ambiguous" in _run([_read(1, "ナゾ")], gbif=two, rows=[])[2][0][2]
    en = _vern_getter(search={"ナゾ": [_hit(1, "ナゾ", lang="eng")]})
    assert _run([_read(1, "ナゾ")], gbif=en, rows=[])[0][0]["tier"] == "T4"        # 該当なし → 和名のみ
    wrong = _vern_getter(search={"ナゾ": [_hit(1, "ナゾ")]}, species={"1": _sp(1, "A b", phylum="Mollusca")})
    assert "phylum_mismatch" in _run([_read(1, "ナゾ")], gbif=wrong, rows=[])[2][0][2]   # 昆虫綱（節足動物）に軟体動物


def test_t3_gbif_doubtful_is_not_accepted_and_falls_back_to_the_sheet():
    g = _gbif_getter({"Foo": _match(960, "Foo", rank="GENUS", status="DOUBTFUL")})
    out, _, _ = _run([_read(1, "Foo属の一種", gen="Foo属", fam="Gobiidae")], gbif=g)
    assert out[0]["taxon_id"] == "common:taxon:gbif.700"       # 属は採らず、シートの科（registry）


def test_slash_name_with_members_in_one_genus_reduces_to_that_genus_not_the_family():
    rows = [
        _tx("common:taxon:gbif.801", "Helicoverpa armigera (Hübner, 1808)", vern="オオタバコガ", family="Noctuidae"),
        _tx("common:taxon:gbif.802", "Helicoverpa assulta (Guenée, 1852)", vern="タバコガ", family="Noctuidae"),
        _tx("common:taxon:gbif.803", "Helicoverpa", rank="genus", binom="Helicoverpa"),
        _tx("common:taxon:gbif.804", "Noctuidae", rank="family", binom="Noctuidae"),
    ]
    out = _by_key(_run([_read(1, "タバコガ/オオタバコガ", gen="-", fam="ヤガ科")], rows=rows))
    r = out["タバコガ/オオタバコガ"]
    assert (r["tier"], r["taxon_id"], r["rank"]) == ("T5", "common:taxon:gbif.803", "genus")
    assert "併記の全成員が属 Helicoverpa" in r["evidence"]


def test_slash_name_across_genera_goes_to_sheet_family_resolved_through_species_of_the_same_family():
    rows = [
        _tx("common:taxon:gbif.801", "Helicoverpa armigera", vern="オオタバコガ", family="Noctuidae"),
        _tx("common:taxon:gbif.810", "Spodoptera litura", vern="ハスモンヨトウ", family="Noctuidae"),
        _tx("common:taxon:gbif.804", "Noctuidae", rank="family", binom="Noctuidae"),
    ]
    reads = [_read(1, "オオタバコガ", gen="タバコガ属", fam="ヤガ科"), _read(2, "ハスモンヨトウ", gen="ヨトウガ属", fam="ヤガ科"),
             _read(3, "オオタバコガ/ハスモンヨトウ", gen="-", fam="ヤガ科")]
    r = _by_key(_run(reads, rows=rows))["オオタバコガ/ハスモンヨトウ"]
    assert (r["taxon_id"], r["rank"]) == ("common:taxon:gbif.804", "family")    # name_only の「ヤガ科」を作らない


def test_name_only_row_gets_english_family_and_order_only_when_known_from_a_species():
    rows = [dict(_tx("common:taxon:gbif.801", "Helicoverpa armigera", vern="オオタバコガ", family="Noctuidae"), order="Lepidoptera")]
    reads = [_read(1, "オオタバコガ", gen="タバコガ属", fam="ヤガ科", order="チョウ目"),
             _read(2, "ナゾノガ", gen="-", fam="ヤガ科", order="チョウ目"),
             _read(3, "ナゾノアブ", gen="-", fam="ムシヒキアブ科", order="ハエ目")]
    _, supp, _ = _run(reads, rows=rows)
    by = {s["vernacular_name_ja"]: s for s in supp}
    assert (by["ナゾノガ"]["family"], by["ナゾノガ"]["order"]) == ("Noctuidae", "Lepidoptera")
    assert (by["ナゾノアブ"]["family"], by["ナゾノアブ"]["order"]) == ("", "")      # 和名の科しか無ければ空
    assert by["ナゾノガ"]["class"] == "Insecta" and "シート: 昆虫綱/チョウ目/ヤガ科" in by["ナゾノガ"]["evidence"]
