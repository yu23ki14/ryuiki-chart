"""observation / occurrence の公開 ID と source_edition_id（Issue #39 Phase C 担当 C、ADR-0004/0005/0016）。

受け入れ基準（ADR-0016 Phase C）の機械検証:
- 旧キー列（`(source_table, source_row_id)` / `record_id`）と新 ID 列が両方 UNIQUE = 旧 -> 新が 1 対 1 に引ける
  （壊すと止まる）
- 同じ入力 -> 同じ ID（決定的）。ID は行の位置（rowid・CSV 行番号）に依存しない
- ファクトの `source_edition_id` が `source_edition` に実在し、土地利用は `data_year` の版に解決される
- DwC-A の旧 occurrenceID -> 新の対応が 1 対 1
本物の原本は要らない（fixture の小さな sqlite だけ）。
"""
import sqlite3

import pytest

import b03_build_observation as b03
import b06_build_occurrence as b06
import dwca_id_map
from migrate import common, public_id
from registry import common as registry_common

from .migrate_fixtures import (
    DEFAULT_ALIASES,
    DEFAULT_LANDUSE_ALIASES,
    DEFAULT_LANDUSE_CSV_ROWS,
    DEFAULT_LANDUSE_VARIABLES,
    DEFAULT_PLACE_REFS,
    DEFAULT_PLACES,
    DEFAULT_SENSOR_ROWS,
    DEFAULT_WATERSHED_PLACE_REFS,
    DEFAULT_WATERSHED_PLACES,
    build_observation,
    make_landuse_csv,
    make_landuse_registry_db,
    make_landuse_source_regions_yaml,
    make_measurements_db,
    make_registry_db,
    make_time_label_conventions_yaml,
)
from .occurrence_fixtures import (
    DEFAULT_ORGANISM_RECORDS,
    make_occurrence_registry_db,
    make_organism_records_db,
    make_period_shapes_yaml,
    make_source_regions_yaml,
)


# ---------------------------------------------------------------------------
# 発行規則（純関数）
# ---------------------------------------------------------------------------

def test_id_formats_and_parse_id_round_trip():
    meas = public_id.measurement_observation_id("atsugi_river_water_quality__000000")
    assert meas == "common:obs:meas.atsugi_river_water_quality__000000"  # 可逆（__ を畳まない）
    sensor = public_id.sensor_observation_id("jp-14:place:site.x", "水位", "2020-01-01T00:00:00", "jma_amedas")
    assert sensor.startswith("common:obs:sensor.jma_amedas.") and len(sensor.rsplit(".", 1)[1]) == 16
    land = public_id.landuse_observation_id("83030-0001", "2006", "1", "area_km2")
    assert land == "common:obs:landuse.83030-0001.2006.1.area_km2"
    occ = public_id.occurrence_id("gbif_kanagawa_occurrences__1830141077", "gbif_kanagawa_occurrences")
    assert occ == "common:occ:gbif.1830141077"
    assert public_id.occurrence_id("inaturalist_kanagawa__286861", "inaturalist_kanagawa") == "common:occ:inat.286861"
    # 公開 ID は parse_id() で scope/entity/ns/key に分解できる（唯一の分解口）
    p = registry_common.parse_id(occ)
    assert (p.scope, p.entity, p.ns, p.key) == ("common", "occ", "gbif", "1830141077")
    p = registry_common.parse_id(meas)
    assert (p.scope, p.entity, p.ns) == ("common", "obs", "meas")


def test_reversible_key_does_not_collapse_and_round_trips():
    """slugify_local_key は `a__b` と `a_b` を同じ key に畳むが、公開 ID の key は畳まず、unquote で元に戻る。"""
    import urllib.parse

    for raw in ("a__b", "a_b", "x y", "a:b/c", "日本語", "100%", "a..b", "1:area_km2"):
        k = public_id.reversible_key(raw)
        assert urllib.parse.unquote(k) == raw
        assert ":" not in k and "/" not in k and " " not in k
    assert public_id.reversible_key("a__b") != public_id.reversible_key("a_b")
    with pytest.raises(common.MigrationError):
        public_id.reversible_key("")


def test_ids_are_deterministic_and_depend_on_business_key_not_position():
    a = public_id.sensor_observation_id("s1", "d", "t", "src")
    assert a == public_id.sensor_observation_id("s1", "d", "t", "src")
    # 業務キーの 1 成分が違えば別 ID
    assert len({a, public_id.sensor_observation_id("s2", "d", "t", "src"),
                public_id.sensor_observation_id("s1", "d2", "t", "src"),
                public_id.sensor_observation_id("s1", "d", "t2", "src"),
                public_id.sensor_observation_id("s1", "d", "t", "src2")}) == 5


def test_issuing_rules_stop_on_malformed_input():
    with pytest.raises(common.MigrationError):
        public_id.occurrence_id("gbif__1", "gbif_kanagawa_occurrences")  # 接頭辞が source_id と違う
    with pytest.raises(common.MigrationError):
        public_id.occurrence_id("synthetic__1", "synthetic")  # 名前空間が未定義の出典
    with pytest.raises(common.MigrationError):
        public_id.occurrence_id("gbif_kanagawa_occurrences__", "gbif_kanagawa_occurrences")  # key が空
    with pytest.raises(common.MigrationError):
        public_id.sensor_observation_id("s", "d", "t", None)


# ---------------------------------------------------------------------------
# b03: observation
# ---------------------------------------------------------------------------

def _build_obs(tmp_path, **kw):
    measurements_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_measurements_db(measurements_db, sensor_rows=DEFAULT_SENSOR_ROWS)
    make_registry_db(registry_db, **kw)
    make_time_label_conventions_yaml(tmp_path / "conventions.yaml")
    out = tmp_path / "v2.sqlite"
    build_observation(tmp_path, measurements_db, registry_db, tmp_path / "no_exc.yaml", tmp_path / "conventions.yaml", out)
    return out


def _rows(out, sql, params=()):
    conn = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_observation_ids_are_one_to_one_with_old_keys_and_editions_resolve(tmp_path):
    out = _build_obs(tmp_path)
    rows = _rows(out, "SELECT source_table, source_row_id, observation_id, source_edition_id FROM observation")
    assert rows
    assert len({(r[0], r[1]) for r in rows}) == len(rows)  # 旧キーが一意
    assert len({r[2] for r in rows}) == len(rows)          # 新 ID が一意 = 旧 -> 新が 1 対 1
    assert all(r[2].startswith("common:obs:") for r in rows)
    assert all(r[3] and r[3].startswith("common:edition:") for r in rows)  # 版が引ける（合成データは除外済み）
    # 新 ID は旧キーのどれとも一致しない（再利用しない・名前空間が別）
    assert not ({r[2] for r in rows} & {r[1] for r in rows})


def test_observation_ids_do_not_depend_on_row_order(tmp_path):
    """同じ原本 -> 同じ ID。出力の行順・別ディレクトリでの再構築でも、旧キー -> 新 ID の対応は同じ。"""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    sql = "SELECT source_table, source_row_id, observation_id FROM observation ORDER BY 1, 2"
    assert _rows(_build_obs(tmp_path / "a"), sql) == _rows(_build_obs(tmp_path / "b"), sql)


def test_colliding_observation_ids_stop_the_build(tmp_path, monkeypatch):
    """業務キーが衝突する（= 同じ ID が 2 行に出る）と、UNIQUE 索引で止まる。"""
    monkeypatch.setattr(public_id, "measurement_observation_id", lambda _id: "common:obs:meas.same")
    with pytest.raises(common.MigrationError, match="observation_id が一意でない"):
        _build_obs(tmp_path)


def test_landuse_observation_edition_follows_data_year(tmp_path):
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    csv_path = tmp_path / "landuse.csv"
    regions_yaml = tmp_path / "source_regions.yaml"
    make_measurements_db(ryuiki_db)
    make_landuse_registry_db(registry_db)
    make_landuse_csv(csv_path)
    make_landuse_source_regions_yaml(regions_yaml)
    out = tmp_path / "v2.sqlite"
    b03.build_and_write_observation(
        ryuiki_db, registry_db, tmp_path / "no_exc.yaml", tmp_path / "no_conv.yaml", out, regions_yaml, csv_path,
    )
    rows = _rows(out, "SELECT period_raw, observation_id, source_edition_id FROM observation "
                      "WHERE source_table = ?", (b03.LANDUSE_SOURCE_ID,))
    assert rows
    for period_raw, oid, eid in rows:
        assert oid.startswith("common:obs:landuse.")
        assert eid.endswith(f".{period_raw}")  # 2006 / 2016 の版に解決されている


# ---------------------------------------------------------------------------
# b06: occurrence
# ---------------------------------------------------------------------------

def _build_occ(tmp_path, organism_rows=None):
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_organism_records_db(ryuiki_db, organism_rows)
    make_occurrence_registry_db(registry_db)
    make_source_regions_yaml(tmp_path / "sr.yaml")
    make_period_shapes_yaml(tmp_path / "ps.yaml")
    out = tmp_path / "v2.sqlite"
    b06.build_and_write_occurrence(ryuiki_db, registry_db, tmp_path / "sr.yaml", tmp_path / "ps.yaml", out)
    return out


def test_occurrence_ids_are_one_to_one_with_record_id_and_follow_the_rule(tmp_path):
    out = _build_occ(tmp_path)
    rows = _rows(out, "SELECT record_id, occurrence_id, source_id, source_edition_id FROM occurrence")
    assert len(rows) == len(DEFAULT_ORGANISM_RECORDS)
    assert len({r[0] for r in rows}) == len(rows) == len({r[1] for r in rows})
    for record_id, occ_id, source_id, eid in rows:
        assert occ_id == public_id.occurrence_id(record_id, source_id)
        assert eid == f"common:edition:{source_id}.20260101"
    assert any(r[1] == "common:occ:gbif.1" for r in rows) and any(r[1] == "common:occ:inat.1" for r in rows)


def test_colliding_occurrence_ids_stop_the_build(tmp_path, monkeypatch):
    monkeypatch.setattr(public_id, "occurrence_id", lambda *_: "common:occ:gbif.same")
    with pytest.raises(common.MigrationError, match="occurrence_id が一意でない"):
        _build_occ(tmp_path)


def test_missing_edition_stops_occurrence_build(tmp_path):
    """registry の source_edition に出典の版が無ければ、黙って NULL にせず止まる。"""
    ryuiki_db = tmp_path / "ryuiki.sqlite"
    registry_db = tmp_path / "registry.sqlite"
    make_organism_records_db(ryuiki_db)
    make_occurrence_registry_db(registry_db)
    conn = sqlite3.connect(registry_db)
    conn.execute("DELETE FROM source_edition WHERE source_id = 'inaturalist_kanagawa'")
    conn.commit()
    conn.close()
    make_source_regions_yaml(tmp_path / "sr.yaml")
    make_period_shapes_yaml(tmp_path / "ps.yaml")
    with pytest.raises(common.MigrationError, match="source_edition_id を決められない"):
        b06.build_and_write_occurrence(ryuiki_db, registry_db, tmp_path / "sr.yaml", tmp_path / "ps.yaml", tmp_path / "v2.sqlite")


# ---------------------------------------------------------------------------
# DwC-A の旧 -> 新対応
# ---------------------------------------------------------------------------

def test_dwca_occurrence_id_mapping_is_one_to_one(tmp_path):
    p = tmp_path / "m.csv"
    dwca_id_map.write_occurrence_id_mapping(p, [
        ("gbif_kanagawa_occurrences__1", "common:occ:gbif.1", "ev_gbif_kanagawa_occurrences__1", "ev_common:occ:gbif.1"),
        ("inaturalist_kanagawa__2", "common:occ:inat.2", "EV-SRC", "EV-SRC"),
    ])
    assert p.read_text(encoding="utf-8").splitlines() == [
        "old_occurrenceID,new_occurrenceID,old_eventID,new_eventID",
        "gbif_kanagawa_occurrences__1,common:occ:gbif.1,ev_gbif_kanagawa_occurrences__1,ev_common:occ:gbif.1",
        "inaturalist_kanagawa__2,common:occ:inat.2,EV-SRC,EV-SRC",
    ]
    with pytest.raises(SystemExit):  # 新 ID が重複（旧 -> 新が 1 対 1 でない）
        dwca_id_map.write_occurrence_id_mapping(p, [("a", "common:occ:gbif.1", "e1", "e1"), ("b", "common:occ:gbif.1", "e2", "e2")])
    with pytest.raises(SystemExit):  # 旧 ID が重複
        dwca_id_map.write_occurrence_id_mapping(p, [("a", "common:occ:gbif.1", "e1", "e1"), ("a", "common:occ:gbif.2", "e2", "e2")])
    with pytest.raises(SystemExit):  # 同じ旧 eventID が別の新 eventID に写る
        dwca_id_map.write_occurrence_id_mapping(p, [("a", "common:occ:gbif.1", "e", "x"), ("b", "common:occ:gbif.2", "e", "y")])


# ---------------------------------------------------------------------------
# ADR-0016 Phase C 受け入れ基準（生成済みの registry.sqlite があるときだけ）
# ---------------------------------------------------------------------------

_REGISTRY = registry_common.REGISTRY_DB
needs_registry = pytest.mark.skipif(not _REGISTRY.exists(), reason="registry.sqlite が無い（CI 等）")


@needs_registry
def test_acceptance_old_ids_resolve_to_exactly_one_current_id_and_supersession_is_declared():
    """① 旧 ID の凍結リスト（place 877・dataset 2）の各行が id_map でちょうど 1 個の現行 ID に解決する
    （旧 ID は現行 ID として再利用されていない・新 ID は一意）。② `gbif_kanagawa` の置換が
    `source.superseded_by` と `source_edition.superseded_by` の両方で引ける。"""
    conn = sqlite3.connect(f"file:{_REGISTRY}?mode=ro", uri=True)
    try:
        counts = dict(conn.execute("SELECT entity, count(*) FROM id_map GROUP BY entity"))
        assert counts == {"place": 877, "dataset": 2}
        assert conn.execute("SELECT count(*) FROM (SELECT old_id FROM id_map GROUP BY old_id HAVING count(*) > 1)").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM (SELECT new_id FROM id_map GROUP BY new_id HAVING count(*) > 1)").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM id_map WHERE old_id IN (SELECT place_id FROM place)").fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM id_map WHERE entity = 'place' AND new_id NOT IN (SELECT place_id FROM place)"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT count(*) FROM id_map WHERE entity = 'dataset' AND new_id NOT IN (SELECT edition_id FROM source_edition)"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT superseded_by FROM source WHERE source_id = 'gbif_kanagawa'").fetchone() == (
            "gbif_kanagawa_occurrences",
        )
        (edition_sup,) = conn.execute(
            "SELECT superseded_by FROM source_edition WHERE source_id = 'gbif_kanagawa'"
        ).fetchone()
        assert edition_sup and edition_sup.startswith("common:edition:gbif_kanagawa_occurrences.")
        # place_source_ref.source_edition_id: site/watershed は埋まり、zone/grid01 は出典を持たず NULL
        got = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT key_space, count(*), count(source_edition_id) FROM place_source_ref GROUP BY key_space")}
        assert got["site_id"][0] == got["site_id"][1] and got["watershed_id"][0] == got["watershed_id"][1]
        assert got["zone"][1] == 0 and got["grid01_latlon"][1] == 0
    finally:
        conn.close()
