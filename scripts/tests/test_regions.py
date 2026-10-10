"""scripts/regions.py（収集の定数）の整合（docs/plans/AMAMI_STEP0.md §4）。

- `registry/region.yaml` の region と `regions.py` の region が対応する
- 書式（GADM gid・メッシュ4桁・市町村コード5桁）
- `jp-14` の値が既存の c スクリプトの直書き定数と一致する（転記だけで、c スクリプトは書き換えない）
- `jp-46` の件数
ネットワークに出ない。
"""
import pathlib
import re

import pytest

import regions as rc
from migrate import regions as region_vocab

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
GID = re.compile(r"^JPN\.\d+(\.\d+)?_1$")


def _src(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _const(name: str, pattern: str) -> str:
    m = re.search(pattern, _src(name), re.M)
    assert m, f"{name} から定数が取れない: {pattern}"
    return m.group(1)


def test_regions_match_region_yaml():
    assert set(rc.REGIONS) == set(region_vocab.load_regions())


@pytest.mark.parametrize("rid", sorted(rc.REGIONS))
def test_formats(rid):
    r = rc.REGIONS[rid]
    assert re.fullmatch(r"\d{2}", r["pref_code"])
    for m in r["muni_codes"] or ():
        assert re.fullmatch(r"\d{5}", m) and m.startswith(r["pref_code"])
    assert r["gbif_gadm_gids"] and all(GID.match(g) for g in r["gbif_gadm_gids"])
    assert r["inat_place_ids"] and all(isinstance(i, int) for i in r["inat_place_ids"])
    assert all(re.fullmatch(r"\d{4}", m) for m in r["l03b_meshes"])
    for prec, block, kind in r["jma_stations"]:
        assert isinstance(prec, int)
        assert block is None or re.fullmatch(r"\d{4,5}", block)
        assert kind in ("all", "s1", "a1")
    for key in ("gbif_gadm_gids", "inat_place_ids", "jma_stations", "env_water_prefcodes",
                "l03b_meshes", "nlni_pref_codes", "estat_pref_codes"):
        assert isinstance(r[key], tuple), key


def test_jp14_matches_hardcoded_collectors():
    r = rc.REGIONS["jp-14"]
    assert r["gbif_gadm_gids"] == (_const("c02_gbif.py", r'^GADM = "([^"]+)"'),)
    assert r["inat_place_ids"] == (int(_const("c03_inaturalist.py", r"^PLACE = (\d+)")),)
    assert r["jma_stations"][0][0] == int(_const("c10_jma.py", r"^PREC = (\d+)"))
    assert r["env_water_prefcodes"] == (_const("c12_env_kousui.py", r'^PREF = "(\d+)"'),)
    meshes = re.findall(r'"(\d{4})"', _const("c34_nlni_l03b.py", r"^MESHES = \(([^)]*)\)"))
    assert r["l03b_meshes"] == tuple(meshes)


def test_jp46_counts():
    r = rc.REGIONS["jp-46"]
    assert len(r["muni_codes"]) == 5
    assert len(r["gbif_gadm_gids"]) == 5
    assert len(r["inat_place_ids"]) == 5
    assert len(r["jma_stations"]) == 3
    assert r["l03b_meshes"] == ("4229",)
    assert len(set(r["gbif_gadm_gids"])) == 5 and len(set(r["inat_place_ids"])) == 5


def test_name_rules():
    assert rc.name("gbif_kanagawa_occurrences", "jp-14") == "gbif_kanagawa_occurrences"
    assert rc.name("gbif_kanagawa_occurrences", "jp-46") == "gbif_amami_occurrences"
    assert rc.name("jma_monthly_kanagawa", "jp-46") == "jma_monthly_amami"
    assert rc.name("nlni_w12_watersheds", "jp-14") == "nlni_w12_watersheds"
    assert rc.name("nlni_w12_watersheds", "jp-46") == "nlni_w12_watersheds_amami"


def test_get_and_arg():
    import argparse
    assert rc.get("jp-46") is rc.REGIONS["jp-46"]
    p = argparse.ArgumentParser()
    rc.add_region_arg(p)
    assert p.parse_args([]).region == "jp-14"
    assert p.parse_args(["--region", "jp-46"]).region == "jp-46"
    with pytest.raises(SystemExit):
        p.parse_args(["--region", "jp-99"])


@pytest.mark.parametrize("rid", sorted(rc.REGIONS))
def test_slug_bbox_stations(rid):
    r = rc.REGIONS[rid]
    assert re.fullmatch(r"[a-z]+", r["slug"])
    x0, y0, x1, y1 = r["bbox"]
    assert x0 < x1 and y0 < y1
    assert isinstance(r["soramame_stations"], tuple) and isinstance(r["jma_sst_areas"], tuple)
    for code, nm in r["soramame_stations"]:
        assert code.startswith(r["pref_code"]) and re.fullmatch(r"\d{8}", code) and nm
    assert all(isinstance(a, int) for a in r["jma_sst_areas"])


def test_jp14_values_match_hardcoded():
    r = rc.REGIONS["jp-14"]
    codes = re.findall(r'"(\d{8})":', _const("c11_soramame.py", r"^TARGET_STATIONS = \{([^}]*)\}"))
    assert tuple(c for c, _ in r["soramame_stations"]) == tuple(codes)
    assert r["jma_sst_areas"] == ()


def test_amami_bbox_excludes_neighbours_and_holds_c23():
    x0, y0, x1, y1 = rc.REGIONS["jp-46"]["bbox"]
    assert x1 < 129.9  # 喜界島は東経129.9度以東、徳之島の北端は北緯27.9度付近
    assert y0 > 27.9
    import json
    p = SCRIPTS.parent / "data" / "processed" / "nlni_c23_coastline.geojson"
    if not p.exists():
        pytest.skip("C23 が無い")

    def pts(c):
        if isinstance(c[0], (int, float)):
            yield c
        else:
            for d in c:
                yield from pts(d)
    n = 0
    for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
        if f["properties"]["prefecture_code"] != "46":
            continue
        for x, y in (q[:2] for q in pts(f["geometry"]["coordinates"])):
            assert x0 <= x <= x1 and y0 <= y <= y1
            n += 1
    assert n
