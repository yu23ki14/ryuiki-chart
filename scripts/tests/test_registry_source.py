"""license / source / source_edition と variable_alias.edition_key（Issue #39 Phase C 担当 B、ADR-0005）。

3 つに分かれる:
1. 宣言の検査（偽の source_registry 行で組み立てを壊し、止まることを固定する。原本は要らない）
2. 実データ（`data/db/ryuiki.sqlite` があるときだけ）: 124 source・写像漏れ 0・置換・版
3. registry.sqlite への書き込みと参照整合性、alias.edition_key、id_map/dataset.csv、resolve_edition
"""
import copy
import csv
import pathlib
import sqlite3

import pytest
import yaml

import r01_build_registry as r01
from migrate import edition as edition_mod
from migrate import common as common_migrate
from registry import build_source, build_unit_variable, common, id_map

RYUIKI = common.DB_DIR / "ryuiki.sqlite"
needs_ryuiki = pytest.mark.skipif(not RYUIKI.exists(), reason="原本 ryuiki.sqlite が無い（CI 等）")


# ---------------------------------------------------------------------------
# 偽の source_registry と宣言
# ---------------------------------------------------------------------------

def _row(source_id, *, license="L1", fetched_at="2026-08-29T10:00:00", notes=None, redistributable=1,
         record_count=10):
    return {
        "source_id": source_id, "name": f"名前 {source_id}", "publisher": "公", "url": f"https://x/{source_id}",
        "category": "水質", "access_method": "HTTP", "format": "CSV", "license": license,
        "redistributable": redistributable, "fetched_at": fetched_at, "record_count": record_count, "notes": notes,
    }


def _license_doc(raws=("L1",)):
    return {
        "license_classes": {"cc_by": {"commercial_ok": 1}, "unknown": {"commercial_ok": None}},
        "licenses": [
            {"license_id": "l_a", "name_ja": "A", "license_class": "cc_by"},
            {"license_id": "unknown", "name_ja": "?", "license_class": "unknown"},
        ],
        "mappings": [{"raw": r, "license_id": "l_a"} for r in raws],
    }


def _editions_doc(**kw):
    doc = {"update_mode_codes": ["snapshot", "append", "revision", "static"],
           "declared_editions": [], "source_declarations": {}}
    doc.update(kw)
    return doc


def _assemble(rows, lic=None, ed=None, root=None):
    return build_source.assemble(rows, lic or _license_doc(), ed or _editions_doc(), root=root)


def test_default_edition_is_one_per_source_with_fetch_date_key():
    lic, src, ed, unmapped = _assemble([_row("a"), _row("b", fetched_at="2026-09-01T00:00:01")])
    assert [e[0] for e in ed] == ["common:edition:a.20260829", "common:edition:b.20260901"]
    assert [s[1] for s in src] == ["common:source:a", "common:source:b"]
    assert unmapped == []
    # license_class と commercial_ok は license.yaml のクラスから来る
    cols = build_source._EDITION_COLUMNS
    e0 = dict(zip(cols, ed[0]))
    assert (e0["license_id"], e0["license_class"], e0["commercial_ok"], e0["license_raw"]) == ("l_a", "cc_by", 1, "L1")


def test_unmapped_license_falls_to_unknown_and_is_reported_not_raised():
    lic, src, ed, unmapped = _assemble([_row("a", license="Lx"), _row("b", license="L1")])
    assert unmapped == ["Lx"]
    by = {e[1]: dict(zip(build_source._EDITION_COLUMNS, e)) for e in ed}
    assert by["a"]["license_id"] == "unknown" and by["a"]["license_class"] == "unknown"
    assert by["a"]["license_raw"] == "Lx"  # 原文は捨てない
    assert by["b"]["license_id"] == "l_a"


def test_stale_license_mapping_halts():
    with pytest.raises(AssertionError, match="存在しない原文"):
        _assemble([_row("a")], lic=_license_doc(raws=("L1", "消えた原文")))


def test_superseded_note_without_declaration_halts():
    """notes に【SUPERSEDED を書いただけで superseded_by を宣言していない出典は止まる。"""
    rows = [_row("old", notes="【SUPERSEDED 2026-08-29】旧登録"), _row("new")]
    with pytest.raises(AssertionError, match="superseded_by を宣言されていない"):
        _assemble(rows)


def test_superseded_by_is_set_on_source_and_edition():
    rows = [_row("old", notes="【SUPERSEDED 2026-08-29】旧登録"), _row("new", fetched_at="2026-08-30T00:00:00")]
    ed = _editions_doc(source_declarations={"old": {"superseded_by": "new"}})
    _, src, editions, _ = _assemble(rows, ed=ed)
    assert {s[0]: s[8] for s in src} == {"old": "new", "new": None}
    sup = build_source._EDITION_COLUMNS.index("superseded_by")
    assert {e[1]: e[sup] for e in editions} == {"old": "common:edition:new.20260830", "new": None}


@pytest.mark.parametrize("decls, match", [
    ({"a": {"superseded_by": "a"}}, "自分自身"),
    ({"a": {"superseded_by": "zzz"}}, "source_registry に無い"),
    ({"a": {"superseded_by": "b"}, "b": {"superseded_by": "a"}}, "循環"),
    ({"nope": {"update_mode": "snapshot"}}, "source_registry に無い"),
])
def test_bad_supersession_declarations_halt(decls, match):
    with pytest.raises(AssertionError, match=match):
        _assemble([_row("a"), _row("b")], ed=_editions_doc(source_declarations=decls))


def test_superseded_by_target_with_several_editions_halts():
    """置換先の edition が複数あると edition 側の置換先が決まらない。黙って選ばない。"""
    rows = [_row("a"), _row("b"), _row("b_2006"), _row("b_2016")]
    ed = _editions_doc(
        declared_editions=[
            {"source_id": "b", "edition_key": "2006", "vintage": "2006", "fetched_from": "b_2006"},
            {"source_id": "b", "edition_key": "2016", "vintage": "2016", "fetched_from": "b_2016"},
        ],
        source_declarations={"a": {"superseded_by": "b"}},
    )
    with pytest.raises(AssertionError, match="edition が 2 個"):
        _assemble(rows, ed=ed)


def test_declared_editions_replace_the_default_and_borrow_fetch_info():
    rows = [_row("lu"), _row("lu_2006", fetched_at="2026-01-02T03:04:05"), _row("lu_2016", fetched_at="2026-02-03T00:00:00")]
    ed = _editions_doc(declared_editions=[
        {"source_id": "lu", "edition_key": "2006", "vintage": "2006", "fetched_from": "lu_2006", "update_mode": "revision"},
        {"source_id": "lu", "edition_key": "2016", "vintage": "2016", "fetched_from": "lu_2016"},
    ])
    _, _, editions, _ = _assemble(rows, ed=ed)
    mine = {e[2]: dict(zip(build_source._EDITION_COLUMNS, e)) for e in editions if e[1] == "lu"}
    assert set(mine) == {"2006", "2016"}  # 取得日の既定 edition は作らない
    assert mine["2006"]["fetched_at"] == "2026-01-02T03:04:05" and mine["2006"]["vintage"] == "2006"
    assert mine["2006"]["update_mode"] == "revision" and mine["2016"]["update_mode"] is None
    assert mine["2006"]["record_count"] is None  # 版ごとの件数は分からない。他の source の件数を借りない


@pytest.mark.parametrize("bad_decl, match", [
    ({"source_id": "zzz", "edition_key": "1", "fetched_from": "a"}, "source_registry に無い"),
    ({"source_id": "a", "edition_key": "1", "fetched_from": "zzz"}, "fetched_from"),
])
def test_bad_declared_editions_halt(bad_decl, match):
    with pytest.raises(AssertionError, match=match):
        _assemble([_row("a")], ed=_editions_doc(declared_editions=[bad_decl]))


@pytest.mark.parametrize("fetched_at", [None, "", "2026-08-29", "2026-08-29T10:00:00+09:00"])
def test_unparseable_fetched_at_halts(fetched_at):
    with pytest.raises(AssertionError, match="fetched_at"):
        _assemble([_row("a", fetched_at=fetched_at)])


def test_content_file_hash_is_filled_only_when_the_file_exists(tmp_path):
    (tmp_path / "x.csv").write_bytes(b"abc")
    ed = _editions_doc(source_declarations={"a": {"content_file": "x.csv"}, "b": {"content_file": "none.csv"}})
    _, _, editions, _ = _assemble([_row("a"), _row("b")], ed=ed, root=tmp_path)
    sha = build_source._EDITION_COLUMNS.index("content_sha256")
    got = {e[1]: e[sha] for e in editions}
    assert got["a"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert got["b"] is None


def test_per_edition_content_file_is_hashed_and_source_level_one_is_rejected_for_versioned_sources(tmp_path):
    (tmp_path / "v2006.csv").write_bytes(b"abc")
    (tmp_path / "v2016.csv").write_bytes(b"abcd")
    rows = [_row("lu"), _row("lu_2006"), _row("lu_2016")]
    ed = _editions_doc(declared_editions=[
        {"source_id": "lu", "edition_key": "2006", "fetched_from": "lu_2006", "content_file": "v2006.csv"},
        {"source_id": "lu", "edition_key": "2016", "fetched_from": "lu_2016", "content_file": "v2016.csv"},
    ])
    _, _, editions, _ = _assemble(rows, ed=ed, root=tmp_path)
    sha = build_source._EDITION_COLUMNS.index("content_sha256")
    got = {e[2]: e[sha] for e in editions if e[1] == "lu"}
    assert got["2006"] != got["2016"] and all(got.values())  # 版ごとに別のファイルを読む
    # 版を宣言した出典に、出典単位の content_file を書くと止まる（どの版か決まらない）
    path = tmp_path / "e.yaml"
    path.write_text(yaml.safe_dump(_editions_doc(
        declared_editions=[{"source_id": "lu", "edition_key": "2006", "fetched_from": "lu_2006"}],
        source_declarations={"lu": {"content_file": "v2006.csv"}}), allow_unicode=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="content_file は、版を宣言している出典には"):
        build_source.load_editions_yaml(path)


def test_unsupported_per_edition_overrides_are_rejected_not_ignored(tmp_path):
    """版ごとの license 等の上書きは宣言できない。書いたら黙って無視せず止まる。"""
    for entry, where in (
        ({"source_id": "a", "edition_key": "1", "fetched_from": "a", "license": "CC0"}, "declared_editions"),
        ({"source_id": "a", "edition_key": "1", "fetched_from": "a", "redistributable": 0}, "declared_editions"),
    ):
        path = tmp_path / "e.yaml"
        path.write_text(yaml.safe_dump(_editions_doc(declared_editions=[entry]), allow_unicode=True), encoding="utf-8")
        with pytest.raises(AssertionError, match="未対応のキー"):
            build_source.load_editions_yaml(path)
    path.write_text(yaml.safe_dump(_editions_doc(source_declarations={"a": {"license": "x"}}), allow_unicode=True), encoding="utf-8")
    with pytest.raises(AssertionError, match="未対応のキー"):
        build_source.load_editions_yaml(path)


def _write_yaml(path, doc):
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return path


def test_license_yaml_checks_halt(tmp_path):
    good = {
        "license_classes": {"cc_by": {"commercial_ok": 1}, "unknown": {"commercial_ok": None}},
        "licenses": [{"license_id": "x", "license_class": "cc_by"}, {"license_id": "unknown", "license_class": "unknown"}],
        "mappings": [{"raw": "r", "license_id": "x"}],
    }
    build_source.load_license_yaml(_write_yaml(tmp_path / "ok.yaml", good))

    def broken(mut):
        d = copy.deepcopy(good)
        mut(d)
        return _write_yaml(tmp_path / "bad.yaml", d)

    with pytest.raises(AssertionError, match="license_class"):
        build_source.load_license_yaml(broken(lambda d: d["licenses"][0].update(license_class="なぞ")))
    with pytest.raises(AssertionError, match="licenses に無い"):
        build_source.load_license_yaml(broken(lambda d: d["mappings"][0].update(license_id="無い")))
    with pytest.raises(AssertionError, match="重複"):
        build_source.load_license_yaml(broken(lambda d: d["mappings"].append({"raw": "r", "license_id": "x"})))
    with pytest.raises(AssertionError, match="受け皿"):
        build_source.load_license_yaml(broken(lambda d: d["licenses"].pop()))


def test_editions_yaml_checks_halt(tmp_path):
    good = _editions_doc(declared_editions=[{"source_id": "a", "edition_key": "2006", "fetched_from": "a"}])
    build_source.load_editions_yaml(_write_yaml(tmp_path / "ok.yaml", good))

    def broken(mut):
        d = copy.deepcopy(good)
        mut(d)
        return _write_yaml(tmp_path / "bad.yaml", d)

    with pytest.raises(AssertionError, match="update_mode"):
        build_source.load_editions_yaml(broken(lambda d: d["declared_editions"][0].update(update_mode="weekly")))
    with pytest.raises(AssertionError, match="重複"):
        build_source.load_editions_yaml(broken(lambda d: d["declared_editions"].append(dict(d["declared_editions"][0]))))
    with pytest.raises(AssertionError, match="content_file"):
        build_source.load_editions_yaml(broken(lambda d: d["source_declarations"].update(a={"content_file": "../x"})))
    with pytest.raises(ValueError):  # edition_key に '.' は入れられない（ID 文法: ns と key の区切りが '.'）
        build_source.load_editions_yaml(broken(lambda d: d["declared_editions"][0].update(edition_key="1.5")))


# ---------------------------------------------------------------------------
# 公開 ID
# ---------------------------------------------------------------------------

def test_source_public_id_round_trip_and_rejects_bad_ids():
    assert common.source_public_id("gbif_kanagawa") == "common:source:gbif_kanagawa"
    assert common.edition_id("gbif_kanagawa", "20260829") == "common:edition:gbif_kanagawa.20260829"
    for bad in ("a.b", "a-b", "A", "a:b", ""):
        with pytest.raises(ValueError):
            common.source_public_id(bad)
    with pytest.raises(ValueError):
        common.edition_id("a", "1.5")


# ---------------------------------------------------------------------------
# 実データ
# ---------------------------------------------------------------------------

def _real_source_registry():
    conn = sqlite3.connect(f"file:{RYUIKI}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT source_id, name, publisher, url, category, access_method, format, license, "
            "redistributable, fetched_at, record_count, notes FROM source_registry"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


@needs_ryuiki
def test_real_data_every_source_has_an_edition_and_every_license_is_mapped():
    rows = _real_source_registry()
    lic, src, ed, unmapped = build_source.assemble(rows, build_source.load_license_yaml(), build_source.load_editions_yaml())
    assert unmapped == [], f"license.yaml の mappings に無いライセンス原文: {unmapped}"
    assert len(src) == len(rows)
    assert {e[1] for e in ed} == {r["source_id"] for r in rows}  # 全 source に最低 1 つ
    assert len({e[0] for e in ed}) == len(ed)
    # source_public_id は全 124 件で発行でき、一意
    assert len({s[1] for s in src}) == len(src)
    assert all(s[1] == common.source_public_id(s[0]) for s in src)
    # redistributable=0 も捨てない（隔離しない。旗として残す）
    red = build_source._EDITION_COLUMNS.index("redistributable")
    assert any(e[red] == 0 for e in ed) and any(e[red] == 1 for e in ed)


@needs_ryuiki
def test_real_data_gbif_supersession_is_declared_on_both_source_and_edition():
    """受け入れ基準（ADR-0016）: gbif_kanagawa -> gbif_kanagawa_occurrences が
    source.superseded_by と source_edition.superseded_by の両方で引ける。"""
    _, src, ed, _ = build_source.assemble(
        _real_source_registry(), build_source.load_license_yaml(), build_source.load_editions_yaml()
    )
    assert {s[0]: s[8] for s in src if s[8]} == {"gbif_kanagawa": "gbif_kanagawa_occurrences"}
    sup = build_source._EDITION_COLUMNS.index("superseded_by")
    got = {e[1]: e[sup] for e in ed if e[sup]}
    assert list(got) == ["gbif_kanagawa"]
    assert got["gbif_kanagawa"].startswith("common:edition:gbif_kanagawa_occurrences.")


@needs_ryuiki
def test_real_data_landuse_has_the_two_vintages():
    _, _, ed, _ = build_source.assemble(
        _real_source_registry(), build_source.load_license_yaml(), build_source.load_editions_yaml()
    )
    lu = sorted(e[0] for e in ed if e[1] == "nlni_l03b_landuse_by_watershed")
    assert lu == [
        "common:edition:nlni_l03b_landuse_by_watershed.2006",
        "common:edition:nlni_l03b_landuse_by_watershed.2016",
    ]


# ---------------------------------------------------------------------------
# registry.sqlite への書き込みと alias.edition_key
# ---------------------------------------------------------------------------

@pytest.fixture()
def reg(tmp_path):
    conn = common.create_registry_db(tmp_path / "registry.sqlite")
    yield conn
    conn.close()


def _fake_ryuiki(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE source_registry (source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT, "
        "category TEXT, access_method TEXT, format TEXT, license TEXT, redistributable INTEGER, "
        "fetched_at TEXT, record_count INTEGER, notes TEXT)"
    )
    cols = ["source_id", "name", "publisher", "url", "category", "access_method", "format", "license",
            "redistributable", "fetched_at", "record_count", "notes"]
    conn.executemany(
        f"INSERT INTO source_registry VALUES ({','.join('?' * len(cols))})", [[r[c] for c in cols] for r in rows]
    )
    return conn


@needs_ryuiki
def test_build_writes_the_three_tables_and_passes_the_reference_checks(reg):
    """本物の registry/ 配下の宣言 + 本物の source_registry で build() し、r01 の一意性・参照整合性の
    検査（自己参照の superseded_by を含む）が通る。alias の宣言と dataset.csv も整合する。"""
    build_unit_variable.build(reg, {})
    ryuiki = sqlite3.connect(f"file:{RYUIKI}?mode=ro", uri=True)
    try:
        counts = build_source.build(reg, {"ryuiki": ryuiki})
    finally:
        ryuiki.close()
    reg.commit()
    assert counts["source"] == 124 and counts["source_edition"] == 125
    r01._assert_id_uniqueness(reg)
    r01._assert_id_references(reg)
    assert reg.execute("SELECT count(*) FROM variable_alias WHERE edition_key IS NOT NULL").fetchone()[0] == 46
    assert reg.execute(
        "SELECT edition_key, count(*) FROM variable_alias WHERE edition_key IS NOT NULL GROUP BY 1 ORDER BY 1"
    ).fetchall() == [("2006", 22), ("2016", 24)]
    assert reg.execute("SELECT count(*) FROM source_edition WHERE license_id = 'unknown'").fetchone()[0] == 0


def test_self_referencing_reference_check_really_detects_a_dangling_superseded_by(reg):
    """unit.canonical_unit_id や source_edition.superseded_by のような「親子が同じ表」の参照検査が、
    実在しない値を実際に検出する（子と親を取り違えると、自分自身を指す行が 1 つあれば常に通ってしまう）。"""
    reg.execute("INSERT INTO license (license_id, license_class) VALUES ('l', 'cc_by')")
    reg.execute("INSERT INTO source (source_id, source_ref_id) VALUES ('a', 'common:source:a')")
    reg.execute(
        "INSERT INTO source_edition (edition_id, source_id, edition_key, license_id, license_class, superseded_by) "
        "VALUES ('common:edition:a.1', 'a', '1', 'l', 'cc_by', NULL)"
    )
    reg.execute(
        "INSERT INTO source_edition (edition_id, source_id, edition_key, license_id, license_class, superseded_by) "
        "VALUES ('common:edition:a.2', 'a', '2', 'l', 'cc_by', 'common:edition:a.無い')"
    )
    reg.commit()
    with pytest.raises(AssertionError, match="source_edition.superseded_by"):
        r01._assert_id_references(reg)


def _alias_csv(tmp_path, rows, header=None):
    header = header or ["alias", "dataset", "source_id", "variable_id", "unit_id", "stat", "grain", "unit_basis", "note",
                        "edition_key"]
    p = tmp_path / "alias.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def test_alias_edition_key_must_be_a_declared_edition(tmp_path, monkeypatch):
    base = ["1:area_km2", "nlni_l03b_landuse_by_watershed", "nlni_l03b_landuse_by_watershed",
            "common:variable:landuse.paddy", "common:unit:km2", "sum", "year", "registry", ""]
    monkeypatch.setattr(build_unit_variable, "VARIABLE_ALIAS_CSV", _alias_csv(tmp_path, [base + ["2006"]]))
    assert build_unit_variable._load_variable_alias_csv()[0]["edition_key"] == "2006"
    # 宣言の無い版、版を持たない出典に edition_key を付けた行、source_id が空の行はいずれも止まる
    for bad_key in ("1999",):
        monkeypatch.setattr(build_unit_variable, "VARIABLE_ALIAS_CSV", _alias_csv(tmp_path, [base + [bad_key]]))
        with pytest.raises(AssertionError, match="declared_editions に無い"):
            build_unit_variable._load_variable_alias_csv()
    other = list(base)
    other[2] = "atsugi_river_water_quality"
    monkeypatch.setattr(build_unit_variable, "VARIABLE_ALIAS_CSV", _alias_csv(tmp_path, [other + ["2006"]]))
    with pytest.raises(AssertionError, match="declared_editions に無い"):
        build_unit_variable._load_variable_alias_csv()


def test_alias_unique_key_includes_edition_key(tmp_path, monkeypatch):
    """同じ (dataset, alias, source_id) でも edition_key が違えば別の行。同じなら重複で止まる。"""
    r = ["1:area_km2", "nlni_l03b_landuse_by_watershed", "nlni_l03b_landuse_by_watershed",
         "common:variable:landuse.paddy", "common:unit:km2", "sum", "year", "registry", ""]
    monkeypatch.setattr(build_unit_variable, "VARIABLE_ALIAS_CSV", _alias_csv(tmp_path, [r + ["2006"], r + ["2016"]]))
    build_unit_variable._load_variable_alias_csv()
    monkeypatch.setattr(build_unit_variable, "VARIABLE_ALIAS_CSV", _alias_csv(tmp_path, [r + ["2006"], r + ["2006"]]))
    with pytest.raises(AssertionError, match="重複"):
        build_unit_variable._load_variable_alias_csv()


def test_alias_edition_must_exist_in_source_edition(reg):
    """alias.source_edition_id が source_edition に無ければ build_source が止まる。"""
    reg.execute(
        "INSERT INTO variable_alias (alias, dataset, source_id, edition_key, source_edition_id) "
        "VALUES ('a', 'd', 's', '2006', 'common:edition:s.2006')"
    )
    with pytest.raises(AssertionError, match="source_edition に実在しない"):
        build_source._assert_alias_editions_exist(reg)


def test_alias_source_id_must_exist_in_source(reg):
    reg.execute("INSERT INTO variable_alias (alias, dataset, source_id) VALUES ('a', 'd', 'no_such_source')")
    with pytest.raises(AssertionError, match="source に無い"):
        build_source._assert_alias_editions_exist(reg)


# ---------------------------------------------------------------------------
# id_map/dataset.csv
# ---------------------------------------------------------------------------

def _reg_with_landuse_editions(reg):
    reg.execute("INSERT INTO license (license_id, license_class) VALUES ('l', 'cc_by')")
    reg.execute("INSERT INTO source (source_id, source_ref_id) VALUES ('lu', 'common:source:lu')")
    for k in ("2006", "2016"):
        reg.execute(
            "INSERT INTO source_edition (edition_id, source_id, edition_key, license_id, license_class) "
            "VALUES (?, 'lu', ?, 'l', 'cc_by')", (f"common:edition:lu.{k}", k),
        )
        reg.execute(
            "INSERT INTO variable_alias (alias, dataset, source_id, edition_key, source_edition_id) "
            "VALUES (?, 'lu', 'lu', ?, ?)", (f"a{k}", k, f"common:edition:lu.{k}"),
        )


def _dataset_rows(pairs):
    return [{"old_id": o, "new_id": n, "reason": "テスト", "spec_version": "t"} for o, n in pairs]


GOOD_PAIRS = [("lu@2006", "common:edition:lu.2006"), ("lu@2016", "common:edition:lu.2016")]


def test_dataset_id_map_matches_alias_and_halts_when_broken(reg):
    _reg_with_landuse_editions(reg)
    id_map.verify_dataset_id_map(_dataset_rows(GOOD_PAIRS), reg)
    with pytest.raises(AssertionError, match="一致しない"):  # 1 行消すと alias の版と食い違う
        id_map.verify_dataset_id_map(_dataset_rows(GOOD_PAIRS[:1]), reg)
    with pytest.raises(AssertionError, match="重複"):  # 新 ID が 1 対 1 でない
        id_map.verify_dataset_id_map(_dataset_rows([GOOD_PAIRS[0], ("lu@2016", GOOD_PAIRS[0][1])]), reg)
    with pytest.raises(AssertionError, match="ではない"):  # 新 ID が規則どおりでない
        id_map.verify_dataset_id_map(_dataset_rows([GOOD_PAIRS[0], ("lu@2016", "common:edition:lu.2017")]), reg)


def test_id_map_is_built_from_csv_without_source_data_in_files_only_mode(tmp_path):
    """原本が要らない: place も source_edition も空のレジストリでも（`full=False`）、
    place.csv・dataset.csv が id_map に載る（CI の生成物検査が空のマップで上書きされない）。"""
    conn = common.create_registry_db(tmp_path / "r.sqlite")
    # dataset.csv が指す alias は variable_alias.csv 由来（--files-only でも作る）
    build_unit_variable.build(conn, {})
    counts = id_map.build_id_map(conn, full=False)
    assert counts == {"place": 877, "dataset": 2}
    assert conn.execute("SELECT count(*) FROM id_map").fetchone()[0] == 879
    conn.close()


# ---------------------------------------------------------------------------
# resolve_edition（ファクトの source_edition_id を決める唯一の入口）
# ---------------------------------------------------------------------------

def test_make_resolver_caches_and_names_the_failure(reg):
    _reg_with_landuse_editions(reg)
    resolve = edition_mod.make_resolver(reg)
    assert resolve(None) is None  # 出典未記録
    assert resolve("lu", vintage="2006") == "common:edition:lu.2006"
    with pytest.raises(common_migrate.MigrationError, match="source_edition_id を決められない"):
        resolve("lu")  # 版が複数。黙って選ばない
    with pytest.raises(edition_mod.EditionResolutionError):
        resolve("nope")


def test_resolve_edition(reg):
    _reg_with_landuse_editions(reg)
    reg.execute("INSERT INTO source (source_id, source_ref_id) VALUES ('one', 'common:source:one')")
    reg.execute(
        "INSERT INTO source_edition (edition_id, source_id, edition_key, license_id, license_class) "
        "VALUES ('common:edition:one.20260829', 'one', '20260829', 'l', 'cc_by')"
    )
    idx = edition_mod.load_editions(reg)
    assert edition_mod.resolve_edition(idx, "one") == "common:edition:one.20260829"
    assert edition_mod.resolve_edition(idx, "lu", vintage="2016") == "common:edition:lu.2016"
    assert edition_mod.resolve_edition(idx, "lu", vintage=2006) == "common:edition:lu.2006"
    with pytest.raises(edition_mod.EditionResolutionError, match="vintage を渡して"):
        edition_mod.resolve_edition(idx, "lu")  # 複数版の出典を vintage 無しで引くと黙って選ばない
    with pytest.raises(edition_mod.EditionResolutionError):
        edition_mod.resolve_edition(idx, "lu", vintage="1999")
    with pytest.raises(edition_mod.EditionResolutionError):
        edition_mod.resolve_edition(idx, "no_such_source")
