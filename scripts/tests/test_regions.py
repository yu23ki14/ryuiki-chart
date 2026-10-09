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
