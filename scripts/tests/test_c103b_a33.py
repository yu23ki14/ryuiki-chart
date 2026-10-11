"""c103b（A33 土砂災害警戒区域）の変換と m05_tier1.load_hazard_zones（AMAMI_STEP3C §5）。

- 変換関数のテストは fixtures/amami_a33/features.json（実データから抜いた第I系の小さなポリゴン8件）だけで動く。
  shapely・pyproj が無い環境では飛ばす。
- 正解 csv（truth.csv）との突き合わせと全量検算は、手元の ZIP（data/raw/bodik_a33/x）がある環境だけ。
"""
import csv
import json
import pathlib
import sqlite3

import pytest

pytest.importorskip("shapely")
pytest.importorskip("pyproj")

import c103b_a33_hazard_zones as c  # noqa: E402
import m05_tier1  # noqa: E402

FIX = pathlib.Path(__file__).parent / "fixtures" / "amami_a33"
SCRIPTS = pathlib.Path(c.__file__).parent


@pytest.fixture(scope="module")
def feats():
    return json.loads((FIX / "features.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(feats):
    return c.build_rows(feats, c.make_transform())


def by_ref(rows):
    return {r["source_ref"]: r for r in rows}


def test_era_date():
    assert c.era_date("令和4年11月25日") == "2022-11-25"
    assert c.era_date("平成29年11月6日") == "2017-11-06"
    assert c.era_date("令和元年5月1日") == "2019-05-01"
    assert c.era_date(c.BAD_DATE_RAW) is None      # 誤記を直さない
    assert c.era_date("令和3年2月30日") is None    # 存在しない日付
    assert c.era_date("基礎調査完了") is None
    assert c.era_date("") is None


def test_rows_basic(built):
    rows, fixed = built
    r = by_ref(rows)
    assert len(rows) == 8 and len({x["zone_id"] for x in rows}) == 8
    assert all(x["source_id"] == "bodik_kagoshima_dosha_amami" for x in rows)
    # 同じ箇所番号・同じ色の連番（shapefile の順）
    assert r["k_rzone1#192"]["zone_id"] == "kyu207-0617-3:r:1"
    assert r["k_rzone1#193"]["zone_id"] == "kyu207-0617-3:r:2"
    # 公示日: 誤記は NULL・raw は原文
    bad = r["k_rzone1#2996"]
    assert bad["designated_on"] is None and bad["designated_on_raw"] == c.BAD_DATE_RAW
    assert r["j_yzone1#1"]["designated_on"] == "2021-01-19" and r["j_yzone1#1"]["phenomenon_code"] == "landslide"
    # 水系名|河川名: 片方だけ・「-」・両方空
    assert r["d_yzone1#892"]["river_name_ja"] == "|西阿室川"
    assert r["d_rzone1#721"]["river_name_ja"] is None
    assert r["k_rzone1#192"]["river_name_ja"] is None
    # 無効ジオメトリは直して数える
    assert fixed[1] >= 1
    for x in rows:
        g = json.loads(x["geometry_geojson"])
        assert g["type"] in ("Polygon", "MultiPolygon") and x["area_m2"] > 0
        lon0, lat0, lon1, lat1 = c.regions.REGIONS["jp-46"]["bbox"]
        assert lon0 <= x["centroid_lon"] <= lon1 and lat0 <= x["centroid_lat"] <= lat1
        assert x["n_vertices"] == c.count_vertices(g["coordinates"])


def test_coordinates_have_at_most_6_digits(built):
    rows, _ = built
    def walk(co):
        if isinstance(co[0], (int, float)):
            yield co
        else:
            for x in co:
                yield from walk(x)
    for x in rows:
        if x["source_ref"] == "d_rzone1#402":      # 丸めで消える欠片だけ 9 桁（このフィクスチャには無い）
            continue
        for pt in walk(json.loads(x["geometry_geojson"])["coordinates"]):
            assert all(round(v, 6) == v for v in pt)


def test_mutation_kubun_stops(feats):
    bad = json.loads(json.dumps(feats))
    bad[0]["props"]["kubun"] = "特別警戒区域" if bad[0]["props"]["kubun"] == "警戒区域" else "警戒区域"
    with pytest.raises(ValueError, match="kubun"):
        c.build_rows(bad, c.make_transform())
    bad = json.loads(json.dumps(feats))
    bad[0]["props"]["genshoname"] = "地滑り" if bad[0]["props"]["genshoname"] != "地滑り" else "土石流"
    with pytest.raises(ValueError, match="genshoname"):
        c.build_rows(bad, c.make_transform())


def test_verify_stops_on_wrong_count(built):
    rows, _ = built
    with pytest.raises(ValueError, match="件数"):
        c.verify(rows)       # 8 行は 6,038 ではない


# ---- 手元の ZIP がある環境だけ ----
needs_raw = pytest.mark.skipif(not (c.RAW / "x").exists(), reason="data/raw/bodik_a33/x が無い（CI）")


@needs_raw
def test_full_conversion_matches_truth_and_checks():
    rows, fixed = c.build_rows(c.read_features(), c.make_transform())
    c.verify(rows)           # §5 の検算（件数・面積・公示日・範囲）
    assert fixed[1] == 10    # もとの形が無効だった行
    got = {r["source_ref"]: r for r in rows}
    with open(FIX / "truth.csv", encoding="utf-8", newline="") as f:
        truth = list(csv.DictReader(f))
    assert len(truth) == 24
    for t in truth:
        r = got[t["source_ref"]]
        for k in ("zone_id", "site_code", "phenomenon_code", "zone_kind_code", "municipality_ja"):
            assert r[k] == t[k], (t["source_ref"], k)
        assert (r["designated_on_raw"] or "") == t["designated_on_raw"]
        assert r["n_vertices"] == int(t["n_vertices"])


# ---- m05_tier1.load_hazard_zones ----
@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "ryuiki.sqlite"
    con = sqlite3.connect(db)
    con.executescript((SCRIPTS / "schema_app.sql").read_text(encoding="utf-8")
                      + (SCRIPTS / "schema_tier1.sql").read_text(encoding="utf-8"))
    con.commit()
    con.close()
    monkeypatch.setattr(m05_tier1, "PROC", tmp_path)
    return tmp_path, db


class FakeWs:
    def find(self, lon, lat):
        return "W1" if lon is not None and lon > 129.5 else None


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=c.FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_load_hazard_zones(env, built):
    proc, db = env
    rows, _ = built
    con = sqlite3.connect(db)
    assert m05_tier1.load_hazard_zones(con, FakeWs()) is None      # CSV が無ければ飛ばす
    write_csv(proc / f"{c.SOURCE_ID}.csv", rows)
    msg = m05_tier1.load_hazard_zones(con, FakeWs())
    assert msg.startswith("hazard_zones[bodik_kagoshima_dosha_amami]: 8 行")
    assert m05_tier1.load_hazard_zones(con, FakeWs()).startswith("hazard_zones")    # 冪等
    n, = con.execute("SELECT count(*) FROM hazard_zones WHERE source_id=?", (c.SOURCE_ID,)).fetchone()
    assert n == 8
    row = con.execute("SELECT designated_on, designated_on_raw, area_m2 FROM hazard_zones WHERE source_ref='k_rzone1#2996'").fetchone()
    assert row[0] is None and row[1] == c.BAD_DATE_RAW and row[2] > 0
    # 他の出典の行は変わらない / zone_id が衝突したら止める
    con.execute("INSERT INTO hazard_zones (zone_id, source_id) VALUES ('other:1', 'other_src')")
    assert m05_tier1.load_hazard_zones(con, FakeWs())
    assert con.execute("SELECT count(*) FROM hazard_zones WHERE source_id='other_src'").fetchone()[0] == 1
    rows[0] = dict(rows[0], zone_id="other:1")
    write_csv(proc / f"{c.SOURCE_ID}.csv", rows)
    with pytest.raises(SystemExit, match="衝突"):
        m05_tier1.load_hazard_zones(con, FakeWs())


def test_m05_only_selects_jobs(env):
    _, db = env
    con = sqlite3.connect(db)
    jobs = m05_tier1.build_jobs(con, FakeWs())
    assert [j[0] for j in m05_tier1.select_jobs(jobs, ["hazard_zones"])] == ["hazard_zones"]
    assert [j[0] for j in m05_tier1.select_jobs(jobs, ["土砂災害警戒区域 (奄美)"])] == ["hazard_zones"]
    assert [j[0] for j in m05_tier1.select_jobs(jobs, ["vegetation"])] == [j[0] for j in jobs if j[0].startswith("vegetation:")]
    assert m05_tier1.select_jobs(jobs, None) == jobs          # 既定は全部
    with pytest.raises(SystemExit, match="合うジョブが無い"):
        m05_tier1.select_jobs(jobs, ["nope"])
