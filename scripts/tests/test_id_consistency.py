"""ID 文法の定数が Python と TS で食い違わないこと、key_space.yaml の宣言が build_place の出力と一致すること
（Issue #39 Phase C。どちらも「二重管理を一致テストで固定する」もの）。"""
import pathlib
import re

import pytest

from registry import build_place, common

ROOT = pathlib.Path(__file__).resolve().parents[2]
PARSE_ID_TS = ROOT / "web" / "src" / "lib" / "registry" / "parse-id.ts"


def test_ts_parse_id_constants_match_python():
    ts = PARSE_ID_TS.read_text(encoding="utf-8")
    kinds = re.search(r"PLACE_KINDS_WITHOUT_NAMESPACE[^=]*=\s*new Set\(\[([^\]]*)\]\)", ts)
    assert kinds, "parse-id.ts に PLACE_KINDS_WITHOUT_NAMESPACE が見つからない"
    assert set(re.findall(r'"([^"]+)"', kinds.group(1))) == set(common.PLACE_KINDS_WITHOUT_NAMESPACE)
    ns = re.search(r"const NAMESPACE_RE = /\^(.+)\$/;", ts)
    assert ns, "parse-id.ts に NAMESPACE_RE が見つからない"
    assert ns.group(1) == common._NAMESPACE_RE.pattern  # ns に許す文字は Python と同じ規則


def test_namespace_validation_is_one_function():
    assert common.is_valid_namespace("env-pubwater") and common.is_valid_namespace("jma_2")
    for bad in ("", "a.b", "a:b", "A", "a b"):
        assert not common.is_valid_namespace(bad)


def _ks(kind_by_ks):
    return [{"key_space": ks, "place_kind": kind} for ks, kind in kind_by_ks.items()]


def test_key_space_place_kind_must_match_the_places_actually_built():
    places = [("p_site", "jp-14", "site"), ("p_ws", None, "watershed")]
    refs = [("p_site", "a__1", "site_id"), ("p_ws", "83030-0001", "watershed_id")]
    build_place._assert_key_space_place_kinds(_ks({"site_id": "site", "watershed_id": "watershed"}), refs, places)
    with pytest.raises(AssertionError, match="place_kind が実際の place の種類と一致しない"):
        build_place._assert_key_space_place_kinds(_ks({"site_id": "zone", "watershed_id": "watershed"}), refs, places)
