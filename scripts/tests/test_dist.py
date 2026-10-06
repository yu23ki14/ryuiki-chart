"""`scripts/d01_build_dist.py`・`scripts/d02_check_dist.py`（`scripts/dist/`）のテスト（Issue #40 Phase D 担当 P）。

設計書 D6 の不変条件 1〜4 を「わざと壊すと止まる」形で固定する:
  1 合成データが出ない / 2 座標が v2 と1ビットも違わない / 3 redistributable=0 の行も絞らない /
  4 旗が registry の source_edition と一致する。
加えて、同じ入力から同じバイト（2 回ビルドの sha256 一致）と、変わった出典のパーティションだけが
書き直されること。原本・本物の v2 は要らない（自作の小さな sqlite だけ）。
"""
import hashlib
import json
import pathlib
import shutil
import sqlite3

import pytest

import b04_build_cube
import b06_build_occurrence
import b07_build_occurrence_cube
import b09_build_occurrence_place
import b03_build_observation
import d01_build_dist as d01
from dist import check as dist_check
from dist import writer as w

ROOT = pathlib.Path(__file__).resolve().parents[2]

ED_OPEN = "common:edition:src_open.20260901"
ED_RESTRICTED = "common:edition:src_restricted.20260901"  # redistributable=0（出力を絞らないことの確認用）
ED_UNKNOWN = "common:edition:src_unknown.20260901"
ED_SYNTH = "common:edition:synthetic_sensor.20260901"


def _registry(path: pathlib.Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "scripts" / "schema_registry.sql").read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO license (license_id, name_ja, license_class, attribution_text) VALUES (?,?,?,?)", [
        ("cc_by", "CC BY", "cc_by", "出典を表示する"),
        ("terms_x", "独自", "restricted", None),
        ("unknown", "未分類", "unknown", None),
        ("cc0", "CC0", "public_domain", None),
    ])
    for sid in ("src_open", "src_restricted", "src_unknown", "synthetic_sensor"):
        conn.execute("INSERT INTO source (source_id, source_ref_id, name_ja) VALUES (?,?,?)", (sid, f"common:source:{sid}", sid))
    conn.executemany(
        "INSERT INTO source_edition (edition_id, source_id, edition_key, fetched_at, license_id, license_raw, license_class,"
        " redistributable, commercial_ok, update_mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (ED_OPEN, "src_open", "20260901", "2026-09-01T00:00:00", "cc_by", "CC BY", "cc_by", 1, 1, "snapshot"),
            (ED_RESTRICTED, "src_restricted", "20260901", "2026-09-01T00:00:00", "terms_x", "独自", "restricted", 0, 0, None),
            (ED_UNKNOWN, "src_unknown", "20260901", None, "unknown", "謎", "unknown", None, None, None),
            (ED_SYNTH, "synthetic_sensor", "20260901", None, "cc0", "合成", "public_domain", 1, 1, None),
        ],
    )
    conn.execute("INSERT INTO registry_build (input_fingerprint, mode) VALUES ('fp', 'files-only')")
    conn.commit()
    conn.close()


def _obs(conn, n, table, edition, *, synthetic=0):
    conn.execute(
        "INSERT INTO observation (source_table, source_row_id, region_id, place_id, place_kind, variable_id, value_grain,"
        " period_grain, period_start, period_end, period_raw, value_num, censoring, is_synthetic, observation_id, source_edition_id)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (table, str(n), "jp-14", "p1", "site", "v1", "raw", "day", "2026-01-01T00:00:00", "2026-01-01T23:59:59",
         "2026-01-01", n * 0.1, "none", synthetic, f"jp-14:observation:{table}.{n}", edition),
    )


def _occ(conn, n, source_id, edition, lat, lon):
    conn.execute(
        "INSERT INTO occurrence (record_id, source_table, source_row_id, source_id, region_id, taxon_id, place_id, place_kind,"
        " coordinate_uncertainty_m, lat, lon, period_grain, period_start, period_end, period_raw, occurrence_id, source_edition_id,"
        " attributes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"{source_id}:{n}", "organism_records", n, source_id, "jp-14", "t1", "g1", "grid01", 12.5, lat, lon,
         "day", "2026-01-01", "2026-01-01", "2026-01-01", f"jp-14:occurrence:{source_id}.{n}", edition,
         '{"situation": "目撃"}' if n == 1 else None),
    )


def _v2(path: pathlib.Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(b03_build_observation._CREATE_OBSERVATION_SQL.format(table="observation"))
    conn.execute(b06_build_occurrence._CREATE_OCCURRENCE_SQL.format(table="occurrence"))
    conn.execute(b09_build_occurrence_place._CREATE_OCCURRENCE_PLACE_SQL.format(table="occurrence_place"))
    conn.execute(b04_build_cube._CREATE_OBSERVATION_AGG_SQL.format(table="observation_agg"))
    conn.execute(b07_build_occurrence_cube._CREATE_OCCURRENCE_AGG_SQL.format(table="occurrence_agg"))
    for i in range(3):
        _obs(conn, i, "measurements", ED_OPEN)
    for i in range(2):
        _obs(conn, i, "sensor_timeseries", ED_RESTRICTED)
    _obs(conn, 0, "land_use", ED_UNKNOWN)
    # 座標は丸めると変わる値（1ビットの違いを検出できること）
    _occ(conn, 1, "src_open", ED_OPEN, 35.123456789012345, 139.987654321098765)
    _occ(conn, 2, "src_open", ED_OPEN, 35.2, 139.3)
    _occ(conn, 1, "src_restricted", ED_RESTRICTED, 35.5555555555555, 139.1111111111111)
    _occ(conn, 1, "src_unknown", ED_UNKNOWN, None, None)
    conn.execute("INSERT INTO occurrence_place (record_id, place_kind, place_id, method, built_from, spec_version)"
                 " VALUES ('src_open:1','watershed','w1','pip','b','s')")
    conn.execute("INSERT INTO observation_agg (region_id, place_id, place_kind, variable_id, grain, stat, n, n_censored,"
                 " n_not_detected, n_places, built_from, spec_version, value_zero) VALUES"
                 " ('jp-14','p1','site','v1','day','mean',3,0,0,1,'b','s',0.1)")
    conn.execute("INSERT INTO occurrence_agg (region_id, source_id, place_id, place_kind, taxon_id, grain, period_start,"
                 " period_end, n, n_red_list, n_alien, built_from, spec_version) VALUES"
                 " ('jp-14','src_open','g1','grid01','t1','year','2026','2026',2,0,0,'b','s')")
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path):
    v2 = tmp_path / "v2.sqlite"
    reg = tmp_path / "registry.sqlite"
    _v2(v2)
    _registry(reg)
    return v2, reg, tmp_path


def _build(v2, reg, out):
    return d01.build_dist(v2, reg, out)


def _tree_hashes(out: pathlib.Path) -> dict[str, str]:
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()}


def _edit(db, sql, params=()):
    c = sqlite3.connect(db)
    c.execute(sql, params)
    c.commit()
    c.close()


# --------------------------------------------------------------------------
# 正常系・決定性・増分
# --------------------------------------------------------------------------


def test_clean_build_passes_all_checks(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    assert dist_check.check_dist(out, v2, reg) == []
    doc = json.loads((out / "datapackage.json").read_text(encoding="utf-8"))
    paths = {r["path"] for r in doc["resources"]}
    assert "observation/source_table=measurements/part-0.parquet" in paths
    assert "occurrence/source_id=src_open/part-0.parquet" in paths
    assert "registry/place.parquet" in paths and "observation_agg.parquet" in paths
    # パーティション列はファイルに持たない（hive のパスが持つ）
    obs = next(r for r in doc["resources"] if r["path"].startswith("observation/source_table=measurements"))
    assert "source_table" not in [f["name"] for f in obs["schema"]["fields"]]
    assert "observation_id" in [f["name"] for f in obs["schema"]["fields"]]
    # occurrence.attributes（JSON 文字列・NULL 可。Phase D）は dist に載り、値がそのまま往復する
    occ = next(r for r in doc["resources"] if r["path"] == "occurrence/source_id=src_open/part-0.parquet")
    assert "attributes" in [f["name"] for f in occ["schema"]["fields"]]
    import pyarrow.parquet as pq

    attrs = pq.read_table(out / occ["path"], columns=["attributes"]).column(0).to_pylist()
    assert '{"situation": "目撃"}' in attrs
    # MCP の export_dataset（web/src/lib/mcp/tools.ts の datapackageResources）が読む形: name・path・sha256（16進 64 桁）・bytes
    for r in doc["resources"]:
        assert isinstance(r["name"], str) and isinstance(r["path"], str) and isinstance(r["bytes"], int)
        assert len(r["sha256"]) == 64 and set(r["sha256"]) <= set("0123456789abcdef")
    # 写像漏れ・未確認の件数を黙って埋めずに出す
    assert doc["license_summary"]["unresolved_license_class"]["unknown"] == [ED_UNKNOWN]
    # 合成出典の宣言は registry からも出さない（件数を記録）
    assert doc["license_summary"]["registry_synthetic_rows_excluded"] == {"source": 1, "source_edition": 1}
    # redistributable=0 の出典の行も含む（絞らない）
    restricted = next(s for s in doc["sources"] if s["source_edition_id"] == ED_RESTRICTED)
    assert restricted["redistributable"] == 0 and restricted["rows"] == {"observation": 2, "occurrence": 1}


def test_two_builds_are_byte_identical(env):
    v2, reg, tmp = env
    _build(v2, reg, tmp / "a")
    _build(v2, reg, tmp / "b")
    ha, hb = _tree_hashes(tmp / "a"), _tree_hashes(tmp / "b")
    assert ha == hb
    # 行集合のダイジェスト（バイトが揺れたときの正）は順序に依らない
    assert w.rowset_digest([(1, "a"), (2, "b")]) == w.rowset_digest([(2, "b"), (1, "a")])
    assert w.rowset_digest([(1, "a")]) != w.rowset_digest([(1, "b")])


def test_rebuild_rewrites_only_changed_partitions(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _doc, first = _build(v2, reg, out)
    assert first["skipped"] == 0 and first["written"] > 3
    _doc, again = _build(v2, reg, out)
    assert again["written"] == 0 and again["skipped"] == first["written"]
    # 1 出典（occurrence の src_open）だけ値が変わる
    _edit(v2, "UPDATE occurrence SET lat = 35.3 WHERE source_id = 'src_open' AND source_row_id = 2")
    _doc, third = _build(v2, reg, out)
    assert third["written"] == 1
    assert dist_check.check_dist(out, v2, reg) == []
    # 出典が消えたらそのパーティションのファイルも消える
    _edit(v2, "DELETE FROM occurrence WHERE source_id = 'src_unknown'")
    _doc, fourth = _build(v2, reg, out)
    assert fourth["removed"] == 1
    assert not (out / "occurrence" / "source_id=src_unknown").exists()


# --------------------------------------------------------------------------
# 不変条件 1: 合成データが出ない
# --------------------------------------------------------------------------


def test_invariant1_build_refuses_synthetic_observation_rows(env):
    v2, reg, tmp = env
    _edit(v2, "UPDATE observation SET is_synthetic = 1 WHERE source_table = 'land_use'")
    with pytest.raises(SystemExit, match="is_synthetic"):
        _build(v2, reg, tmp / "dist")


def test_invariant1_build_refuses_synthetic_sources(env):
    v2, reg, tmp = env
    c = sqlite3.connect(v2)
    _occ(c, 9, "synthetic_sensor", ED_SYNTH, 35.0, 139.0)
    c.commit()
    c.close()
    with pytest.raises(SystemExit, match="synthetic_"):
        _build(v2, reg, tmp / "dist")


def test_invariant1_check_catches_synthetic_in_datapackage_and_registry(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    dpj = out / "datapackage.json"
    doc = json.loads(dpj.read_text(encoding="utf-8"))
    doc["sources"].append({**doc["sources"][0], "source_id": "synthetic_sensor", "source_edition_id": ED_SYNTH})
    dpj.write_text(json.dumps(doc), encoding="utf-8")
    errs = dist_check.check_dist(out, v2, reg)
    assert any("[1 合成]" in e and "sources" in e for e in errs)


def test_invariant1_check_catches_synthetic_registry_rows(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    # 合成出典の行を registry 側へ混ぜた dist を、書き手を迂回して作る
    shutil.copyfile(out / "registry" / "source.parquet", tmp / "orig.parquet")
    conn = sqlite3.connect(reg)
    g = next(w.iter_groups(conn, "source", order_by=("source_id",)))
    g.write(out / "registry" / "source.parquet")  # 絞らずに全行（synthetic_sensor 込み）を書いた dist
    conn.close()
    errs = dist_check.check_dist(out, v2, reg)
    assert any("[1 合成]" in e and "registry/source.parquet" in e for e in errs)


# --------------------------------------------------------------------------
# 不変条件 2: 座標が v2 と1ビットも違わない
# --------------------------------------------------------------------------


def test_invariant2_coordinates_roundtrip_exactly(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    import pyarrow.parquet as pq
    t = pq.read_table(out / "occurrence" / "source_id=src_open" / "part-0.parquet")
    got = sorted(zip(t["lat"].to_pylist(), t["lon"].to_pylist()))
    assert got == [(35.123456789012345, 139.987654321098765), (35.2, 139.3)]


def test_invariant2_check_catches_rounded_coordinates(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    # 丸めた（ぼかした）v2 に対して、元の dist を検査する = dist が v2 とずれている状況
    _edit(v2, "UPDATE occurrence SET lat = round(lat, 3), lon = round(lon, 3)")
    errs = dist_check.check_dist(out, v2, reg)
    assert any("[2 座標]" in e for e in errs)
    # 逆向き: 丸めた v2 から作った dist を、丸める前の v2 に照らしても落ちる
    out2 = tmp / "dist2"
    _build(v2, reg, out2)
    _edit(v2, "UPDATE occurrence SET lat = 35.123456789012345 WHERE source_id = 'src_open' AND source_row_id = 1")
    assert any("[2 座標]" in e for e in dist_check.check_dist(out2, v2, reg))


# --------------------------------------------------------------------------
# 不変条件 3: 旗は出力を絞らない
# --------------------------------------------------------------------------


def test_invariant3_check_catches_filtering_by_redistributable(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    # 「redistributable=0 の出典を除く」実装が入った状況を再現: 除いた v2 から作った dist を、完全な v2 に照らす
    filtered = tmp / "v2_filtered.sqlite"
    shutil.copyfile(v2, filtered)
    _edit(filtered, "DELETE FROM observation WHERE source_edition_id = ?", (ED_RESTRICTED,))
    _edit(filtered, "DELETE FROM occurrence WHERE source_edition_id = ?", (ED_RESTRICTED,))
    _build(filtered, reg, out)
    errs = dist_check.check_dist(out, v2, reg)
    assert any("[3 絞らない]" in e for e in errs)


def test_invariant3_check_catches_dropped_rows_within_partition(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    thinner = tmp / "v2_thin.sqlite"
    shutil.copyfile(v2, thinner)
    _edit(thinner, "DELETE FROM observation WHERE source_table = 'measurements' AND source_row_id = '0'")
    out2 = tmp / "dist2"
    _build(thinner, reg, out2)
    errs = dist_check.check_dist(out2, v2, reg)
    assert any("[3 絞らない]" in e and "行数" in e for e in errs)


# --------------------------------------------------------------------------
# 不変条件 4: 旗の忠実性
# --------------------------------------------------------------------------


def test_invariant4_check_catches_license_rewrite_in_datapackage(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    dpj = out / "datapackage.json"
    doc = json.loads(dpj.read_text(encoding="utf-8"))
    for s in doc["sources"]:
        if s["source_edition_id"] == ED_RESTRICTED:
            s["license_class"] = "cc_by"
            s["redistributable"] = 1
    dpj.write_text(json.dumps(doc), encoding="utf-8")
    assert any("[4 旗]" in e for e in dist_check.check_dist(out, v2, reg))


def test_invariant4_check_catches_registry_flag_drift(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    # registry 側の旗が dist のビルド後に変わった（または dist が古い）
    _edit(reg, "UPDATE source_edition SET license_class = 'cc_by', redistributable = 1 WHERE edition_id = ?", (ED_RESTRICTED,))
    errs = dist_check.check_dist(out, v2, reg)
    assert any("[4 旗]" in e for e in errs)


def test_invariant4_check_catches_hidden_unresolved_count(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    dpj = out / "datapackage.json"
    doc = json.loads(dpj.read_text(encoding="utf-8"))
    doc["license_summary"]["unresolved_license_class"]["unknown"] = []
    dpj.write_text(json.dumps(doc), encoding="utf-8")
    assert any("写像漏れ" in e for e in dist_check.check_dist(out, v2, reg))


# --------------------------------------------------------------------------
# 整合・型
# --------------------------------------------------------------------------


def test_check_catches_tampered_file_and_stray_file(env):
    v2, reg, tmp = env
    out = tmp / "dist"
    _build(v2, reg, out)
    shutil.copyfile(out / "registry" / "place.parquet", out / "stray.parquet")
    assert any("載っていない" in e for e in dist_check.check_dist(out, v2, reg))
    (out / "stray.parquet").unlink()
    p = out / "observation_agg.parquet"
    p.write_bytes(p.read_bytes() + b"\0")
    assert any("sha256" in e for e in dist_check.check_dist(out, v2, reg))


def test_unknown_declared_type_is_not_silently_stringified(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.sqlite")
    conn.execute("CREATE TABLE t (a BLOB)")
    with pytest.raises(RuntimeError, match="型対応表"):
        w.table_columns(conn, "t")
