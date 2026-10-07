"""m07_kanagawa_edna（原本表への投入）のテスト。fixture の小さな CSV 相当の dict で通す
（name_map は担当 C の成果物なので、ここでは fixture）。本物の ryuiki.sqlite には触らない。"""
import copy
import json
import sqlite3

import pytest

import m07_kanagawa_edna as m07


def site(key, file="r3_kenmin_gyorui.xlsx", program="kenmin", assay="fish_12S", fy=2021, date="2021-09-03", **kw):
    return {"site_key": key, "dataset_file": file, "program": program, "assay": assay, "fiscal_year": str(fy),
            "site_id_raw": key.split(":", 1)[1], "water_system_raw": "相模川サガミガワ", "water_system_ja": "相模川",
            "tributary_raw": "-", "tributary_ja": "-", "municipality_raw": "厚木市アツギシ",
            "municipality_ja": "厚木市", "collected_on": date or "", "collected_on_raw": "44442",
            "source_id": "kanagawa_edna", "source_ref": f"https://example/#{file}!H", **kw}


def read(site_key, row, name_adopted, reads, key, **kw):
    base = {"read_id": f"{site_key}:{row}", "site_key": site_key, "class_ja": "硬骨魚綱", "order_ja": "",
            "family_ja": "", "genus_ja": "", "name_raw": name_adopted, "name_adopted": name_adopted,
            "name_sci_raw": "", "name_note": "", "reads": str(reads), "is_detected": str(int(reads > 0)),
            "pident_qcov": "", "reliability": "", "national_rl_raw": "", "pref_rl_raw": "", "alien_raw": "",
            "name_key": key, "dataset_filter": "", "source_id": "kanagawa_edna"}
    base.update(kw)
    return base


def coord(key, src="estimated_from_name", lat="35.4", lon="139.3", unc="1500", **kw):
    if src == "none":
        lat = lon = unc = ""
    return {"site_key": key, "water_system_ja": "相模川", "tributary_ja": "-", "municipality_ja": "厚木市",
            "lat": lat, "lon": lon, "coord_source": src, "coordinate_uncertainty_m": unc,
            "coord_method": "river_in_municipality" if src != "none" else "none_generic_tributary",
            "evidence": "test", "grid01_ok": "1", "reviewed": "0", **kw}


def nm(key, taxon="common:taxon:gbif.1", rank="species", sci="Anguilla japonica", ja="ニホンウナギ", tier="T1"):
    return {"name_key": key, "rank": rank, "taxon_id": taxon, "scientific_name": sci,
            "vernacular_name_ja": ja, "tier": tier, "evidence": "e", "reviewed": "0"}


@pytest.fixture
def data():
    k1, k2 = "r3_kenmin_gyorui:K-21-1", "r7_kenmin_kekka:k-25-04"
    sites = [site(k1), site(k2, file="r7_kenmin_kekka.xlsx", assay="all_taxa", fy=2025, date="")]
    reads = [
        read(k1, 7, "ニホンウナギ", 98, "ニホンウナギ", national_rl_raw="絶滅危惧IB類（EN）", pref_rl_raw="X"),
        read(k1, 8, "コイ（飼育型）", 0, "コイ"),
        read(k2, 9, "ヨシノボリ属の一種 / ウキゴリ", 5, "ヨシノボリ属の一種/ウキゴリ", name_note="（cf.）",
             pident_qcov="0.99", reliability="低", pref_rl_raw="要注意種", alien_raw="特定外来",
             dataset_filter="match>=98.5%"),
    ]
    coords = [coord(k1), coord(k2, src="none")]
    names = [nm("ニホンウナギ"), nm("コイ", taxon="common:taxon:gbif.2", sci="Cyprinus carpio", ja="コイ"),
             nm("ヨシノボリ属の一種/ウキゴリ", taxon="common:taxon:gbif.3", rank="genus", sci="Rhinogobius",
                ja="", tier="T5")]
    return sites, reads, coords, names


def run(data, con=None):
    con = con or sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    return con, m07.load(con, *data)


def test_load_builds_three_tables(data):
    con, res = run(data)
    assert res == {"sites": 2, "reads": 3, "detections": 2}
    assert con.execute("SELECT COUNT(*) FROM edna_detections").fetchone()[0] == \
        con.execute("SELECT COUNT(*) FROM edna_reads WHERE is_detected=1").fetchone()[0]
    # 不検出は edna_reads にだけある
    assert con.execute("SELECT COUNT(*) FROM edna_detections WHERE record_key LIKE '%:8'").fetchone()[0] == 0
    assert con.execute("SELECT taxon_id FROM edna_reads WHERE read_id='r3_kenmin_gyorui:K-21-1:8'").fetchone()[0] == "common:taxon:gbif.2"
    s = con.execute("SELECT lat,lon,coord_source,coordinate_uncertainty_m,coord_note,collected_on FROM edna_sites WHERE site_key=?",
                    ("r3_kenmin_gyorui:K-21-1",)).fetchone()
    assert s == (35.4, 139.3, "estimated_from_name", 1500.0, "test", "2021-09-03")
    s2 = con.execute("SELECT lat,lon,coord_source,coordinate_uncertainty_m,collected_on FROM edna_sites WHERE site_key=?",
                     ("r7_kenmin_kekka:k-25-04",)).fetchone()
    assert s2 == (None, None, "none", None, None)    # 日付の空欄・座標なしは NULL のまま


def test_detections_projection_and_attributes(data):
    con, _ = run(data)
    d1 = con.execute("SELECT * FROM edna_detections WHERE record_key='r3_kenmin_gyorui:K-21-1:7'").fetchone()
    (key, taxon, sci, ja, rank, rl, obs, lat, lon, unc, attrs) = d1
    assert (taxon, sci, ja, rank, obs, lat, lon, unc) == ("common:taxon:gbif.1", "Anguilla japonica", "ニホンウナギ",
                                                           "species", "2021-09-03", 35.4, 139.3, 1500.0)
    assert rl == "絶滅危惧IB類（EN）"                      # 国RL があれば国RL
    a = json.loads(attrs)
    assert a["reads"] == 98 and a["cf"] is False and a["rank_reduced"] is False and a["name_ambiguous"] is False
    assert a["coord_source"] == "estimated_from_name" and a["site_key"] == "r3_kenmin_gyorui:K-21-1"
    assert "dataset_filter" not in a                      # r7_kenmin だけ
    d3 = con.execute("SELECT red_list_category, lat, attributes_json FROM edna_detections WHERE record_key LIKE 'r7%'").fetchone()
    assert d3[0] == "要注意種" and d3[1] is None          # 国RL が無ければ県RL。座標なしは NULL
    a3 = json.loads(d3[2])
    assert a3["dataset_filter"] == "match>=98.5%" and a3["cf"] is True and a3["name_ambiguous"] is True
    assert a3["rank_reduced"] is True and a3["reliability"] == "低" and a3["pident_qcov"] == 0.99
    assert a3["alien_raw"] == "特定外来" and a3["coord_source"] == "none"
    assert a3["fiscal_year"] == 2025 and a3["water_system"] == "相模川"


def test_idempotent_reload(data):
    con, _ = run(data)
    run(data, con)
    assert con.execute("SELECT COUNT(*) FROM edna_reads").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM edna_sites").fetchone()[0] == 2


def test_stops_on_unmapped_name(data):
    sites, reads, coords, names = data
    with pytest.raises(m07.M07Error, match="name_map に無い"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, coords, names[:-1])
    names2 = copy.deepcopy(names)
    names2[0]["taxon_id"] = ""
    with pytest.raises(m07.M07Error, match="taxon_id が無い"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, coords, names2)


def test_stops_when_ledger_site_set_differs(data):
    sites, reads, coords, names = data
    with pytest.raises(m07.M07Error, match="一致しない"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, coords[:1], names)
    extra = coords + [coord("r9_x:zzz")]
    with pytest.raises(m07.M07Error, match="一致しない"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, extra, names)


def test_stops_on_inconsistent_ledger_rows(data):
    sites, reads, coords, names = data
    bad = copy.deepcopy(coords)
    bad[1].update(lat="35.0", lon="139.0")                 # none なのに座標がある
    with pytest.raises(m07.M07Error, match="none"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, bad, names)
    bad = copy.deepcopy(coords)
    bad[0]["coordinate_uncertainty_m"] = ""                 # 座標あり ⇒ 精度必須
    with pytest.raises(m07.M07Error, match="空"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, bad, names)
    bad = copy.deepcopy(coords)
    bad[0]["coord_source"] = "geocoder"
    with pytest.raises(m07.M07Error, match="coord_source"):
        m07.load(sqlite3.connect(":memory:"), sites, reads, bad, names)


def test_check_constraints_in_schema(data):
    con, _ = run(data)
    ins = ("INSERT INTO edna_reads (read_id,site_key,reads,is_detected,name_key,source_id) "
           "VALUES (?,?,?,?,?,?)")
    with pytest.raises(sqlite3.IntegrityError):            # reads >= 0
        con.execute(ins, ("x1", "r3_kenmin_gyorui:K-21-1", -1, 0, "k", "kanagawa_edna"))
    with pytest.raises(sqlite3.IntegrityError):            # is_detected = (reads > 0)
        con.execute(ins, ("x2", "r3_kenmin_gyorui:K-21-1", 0, 1, "k", "kanagawa_edna"))
    with pytest.raises(sqlite3.IntegrityError):            # 外部キー
        con.execute(ins, ("x3", "no-such-site", 1, 1, "k", "kanagawa_edna"))
    sins = ("INSERT INTO edna_sites (site_key,dataset_file,program,assay,fiscal_year,site_id_raw,lat,lon,"
            "coord_source,coordinate_uncertainty_m,source_id,source_ref) VALUES ('s','f','kenmin','fish_12S',2021,'s',?,?,?,?,'kanagawa_edna','r')")
    with pytest.raises(sqlite3.IntegrityError):            # 座標あり ⇒ 精度必須
        con.execute(sins, (35.0, 139.0, "estimated_from_name", None))
    with pytest.raises(sqlite3.IntegrityError):            # none ⇒ 座標なし
        con.execute(sins, (35.0, 139.0, "none", None))
    with pytest.raises(sqlite3.IntegrityError):            # lat/lon は片方だけ不可
        con.execute(sins, (35.0, None, "estimated_from_name", 500))


def test_cli_with_files(tmp_path, data):
    import csv
    sites, reads, coords, names = data

    def w(name, rows):
        p = tmp_path / name
        with open(p, "w", encoding="utf-8", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        return str(p)

    db = tmp_path / "t.sqlite"
    m07.main(["--db", str(db), "--sites", w("s.csv", sites), "--reads", w("r.csv", reads),
              "--coords", w("c.csv", coords), "--name-map", w("n.csv", names)])
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM edna_detections").fetchone()[0] == 2
    # name_map を欠いたら止まり、DB は元のまま（ロールバック）
    with pytest.raises(m07.M07Error):
        m07.main(["--db", str(db), "--sites", w("s.csv", sites), "--reads", w("r.csv", reads),
                  "--coords", w("c.csv", coords), "--name-map", w("n2.csv", names[:1])])
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM edna_reads").fetchone()[0] == 3


def test_stops_when_ledger_names_differ_from_sites(data):
    sites, reads, coords, names = data
    for col in ("water_system_ja", "tributary_ja", "municipality_ja"):
        bad = copy.deepcopy(coords)
        bad[0][col] = "別の名前"
        with pytest.raises(m07.M07Error, match="c89b を再実行"):
            m07.load(sqlite3.connect(":memory:"), sites, reads, bad, names)


def test_vernacular_name_from_sheet_only_for_species_level_rows(data):
    sites, reads, coords, names = data
    names = copy.deepcopy(names)
    names[1]["vernacular_name_ja"] = ""                       # コイ: 種のまま・和名が map に無い
    reads = copy.deepcopy(reads)
    reads[1].update(reads="3", is_detected="1")               # コイ（飼育型）を検出にする
    con = sqlite3.connect(":memory:")
    m07.load(con, sites, reads, coords, names)
    v = dict(con.execute("SELECT record_key, vernacular_name FROM edna_detections"))
    assert v["r3_kenmin_gyorui:K-21-1:8"] == "コイ"          # シートの採用名（括弧書きを除く）
    assert v["r3_kenmin_gyorui:K-21-1:7"] == "ニホンウナギ"   # map の和名
    assert v["r7_kenmin_kekka:k-25-04:9"] is None            # 属に寄せた行（map の和名が空）には付けない
    names[1]["scientific_name"] = ""
    reads[1]["name_adopted"] = "Cyprinus carpio"
    con2 = sqlite3.connect(":memory:")
    m07.load(con2, sites, reads, coords, names)
    assert con2.execute("SELECT vernacular_name FROM edna_detections WHERE record_key LIKE '%:8'").fetchone()[0] is None  # 学名は和名にしない


def test_cf_and_ambiguity_use_c89c_normalization(data):
    sites, reads, coords, names = data
    reads = copy.deepcopy(reads)
    reads[0].update(name_adopted="ニホンウナギ（ｃｆ．）", name_note="")      # 全角の cf.
    reads[2].update(name_adopted="ヨシノボリ属の一種／ウキゴリ", name_note="")  # 全角スラッシュ
    con = sqlite3.connect(":memory:")
    m07.load(con, sites, reads, coords, names)
    a = lambda key: json.loads(con.execute("SELECT attributes_json FROM edna_detections WHERE record_key=?", (key,)).fetchone()[0])
    assert a("r3_kenmin_gyorui:K-21-1:7")["cf"] is True
    assert a("r7_kenmin_kekka:k-25-04:9")["name_ambiguous"] is True
