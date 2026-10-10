"""c10/c11/c12/c15 の --region 対応。jp-14 の出力名・source_id・raw パスが従来と1文字も変わらないことを固定する
（ネットワークに出ない）。"""
import pytest

pytest.importorskip("pandas")
pytest.importorskip("requests")

import c10_jma, c11_soramame, c12_env_kousui, c15_jma_sst  # noqa: E402
import common  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_jp14():
    yield
    for m in (c10_jma, c11_soramame, c12_env_kousui):
        m.set_region("jp-14")


def test_c10_jp14_unchanged():
    c10_jma.set_region("jp-14")
    assert (c10_jma.SID_ST, c10_jma.SID_MON, c10_jma.SID_DAY) == (
        "jma_stations_kanagawa", "jma_monthly_kanagawa", "jma_daily_yokohama")
    assert c10_jma.PREC == 46 and c10_jma.BLOCKS is None
    assert c10_jma.RAWD == common.RAW / "jma"
    assert c10_jma.PREF_JA == "神奈川県" and c10_jma.LABEL == "神奈川県"
    assert c10_jma.TARGETS == ["横浜", "海老名", "辻堂", "小田原", "丹沢湖", "相模湖", "三浦"]
    assert c10_jma.DAILY_ST == "横浜"
    assert c10_jma.DAILY_PERIODS == [(2024, 1, 12), (2025, 1, 12), (2026, 1, 12)]


def test_c10_jp46():
    c10_jma.set_region("jp-46")
    assert (c10_jma.SID_ST, c10_jma.SID_MON, c10_jma.SID_DAY) == (
        "jma_stations_amami", "jma_monthly_amami", "jma_daily_nase")
    assert c10_jma.PREC == 88 and c10_jma.BLOCKS == {"47909", "1520", "0980"}
    assert c10_jma.RAWD == common.RAW / "jma_amami"
    assert c10_jma.TARGETS == ["名瀬", "笠利", "古仁屋"] and c10_jma.DAILY_ST == "名瀬"
    assert (2010, 10, 10) in c10_jma.DAILY_PERIODS


def test_c11_jp14_unchanged():
    c11_soramame.set_region("jp-14")
    assert (c11_soramame.SID_ST, c11_soramame.SID_TS) == ("soramame_stations_kanagawa", "soramame_hourly_kanagawa")
    assert c11_soramame.RAWD == common.RAW / "soramame" and c11_soramame.PREF == "14"
    assert c11_soramame.TARGET_STATIONS == {
        "14209050": "津久井（相模川上流・城山ダム下流）",
        "14401010": "愛川町角田（中津川・相模川中流）",
        "14321010": "寒川町役場（相模川下流）",
        "14206010": "小田原市役所（酒匂川下流）",
    }


def test_c11_jp46():
    c11_soramame.set_region("jp-46")
    assert (c11_soramame.SID_ST, c11_soramame.SID_TS) == ("soramame_stations_amami", "soramame_hourly_amami")
    assert c11_soramame.PREF == "46" and list(c11_soramame.TARGET_STATIONS) == ["46225010"]


def test_c12_jp14_unchanged():
    c12_env_kousui.set_region("jp-14")
    m = c12_env_kousui
    assert (m.SID_ST, m.SID_Y, m.SID_K) == (
        "env_kousui_stations_kanagawa", "env_kousui_annual_kanagawa", "env_kousui_sample_kanagawa")
    assert m.PREF == "14" and m.RAWD == common.RAW / "env_kousui" and m.BBOX is None


def test_c12_jp46():
    c12_env_kousui.set_region("jp-46")
    m = c12_env_kousui
    assert (m.SID_ST, m.SID_Y, m.SID_K) == (
        "env_kousui_stations_amami", "env_kousui_annual_amami", "env_kousui_sample_amami")
    assert m.PREF == "46" and m.RAWD == common.RAW / "env_kousui_amami"
    assert m.in_bbox(28.37, 129.5) and not m.in_bbox(31.5, 130.5) and not m.in_bbox(None, 129.5)


def test_c15_jp14_does_nothing(monkeypatch, capsys):
    monkeypatch.setattr(c15_jma_sst, "get", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr("sys.argv", ["c15_jma_sst.py", "--region", "jp-14"])
    c15_jma_sst.main()
    assert "何もしない" in capsys.readouterr().out


def test_c15_parse_area():
    txt = "yyyy,mm,dd,areaNo.,flag,Temp.\n1982,01,01,617,R, 21.65\n2026,10,09,617,P, 27.32\n1982,01,03,617,R,\n"
    rows = c15_jma_sst.parse_area(txt, 617, "jma_sst_amami", "u")
    assert [(r["datetime"], r["value"], r["quality_flag"]) for r in rows] == [
        ("1982-01-01", 21.65, "R"), ("2026-10-09", 27.32, "P")]
    assert rows[0]["area_name_ja"] == "奄美群島沿岸北西部" and rows[0]["unit"] == "degC"
