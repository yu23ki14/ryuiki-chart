"""c94（鹿児島県 河川砂防情報システム）の解析・集約のテスト。合成の小さな CSV 文字列と ZIP だけを使う。"""
import io
import zipfile
from collections import Counter

import pytest

import c94_kagoshima_kasen as c94
import regions

SUII = (
    "危機管理型水位\n"
    "2,139,144,200\n"
    "観測時刻,第2屋仁橋,朝戸橋,他県の橋\n"
    "2024/01/01 00:00,10,***,5\n"
    "2024/01/01 06:00,-3,---,6\n"
    "2024/01/01 12:00,25,,7\n"
    "2024/01/02 00:00,abc,40,8\n"
    "2024/02/01 00:00,1,1,1\n"
)
DAM = (
    "大和ダム\n"
    "3,1,3,4,2,5,17,18\n"
    "観測時刻,貯水位,全流入量,全放流量,貯水量,空容量,貯水率（治水）,貯水率（利水）\n"
    ",[EL.10^2m],[10＾-3m3/s],[10＾-3m3/s],[10＾3m3],[10＾3m3],[10^-1%],[10^-1%]\n"
    "2024/01/01 00:10,4355,100,90,4,,5,---\n"
    "2024/01/01 12:10,4357,300,110,6,,7,\n"
)
STATION_JS = (
    'function RiverItem(no,name){}\n'
    'var river_info=new Array(new RiverItem("182","稲袋橋","住用川","1","28.27","129.40",new Array("1")),'
    'new RiverItem("1","原良橋","甲突川","0","31.59","130.54",new Array("1")));'
)
TIDE_JS = "var t=new Array(new TideItem('4','名瀬','28.384','129.4986'),new TideItem('1','出水','32.12','130.33'));"
DAM_JS = "var d=new Array(new DamItem('2','大和ダム','28.342','129.3875'));"


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text.encode("cp932"))  # 非 ASCII 名は UTF-8 フラグ付きで書かれる
    return buf.getvalue()


def test_zip_member_names_restore_cp932_when_no_utf8_flag():
    class Info:  # UTF-8 フラグ無し: zipfile は cp437 として読む
        flag_bits = 0
        filename = "suii2021/202101_危機管理型水位計.csv".encode("cp932").decode("cp437")

    class Z:
        def infolist(self):
            return [Info()]
    assert [n for _, n in c94.zip_member_names(Z())] == ["suii2021/202101_危機管理型水位計.csv"]


def test_zip_member_names_utf8_flagged_member_kept():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("suii2024_1-12/202401_水位.csv", b"x")  # 非 ASCII 名は UTF-8 フラグ付きで書かれる
    z = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    assert [n for _, n in c94.zip_member_names(z)] == ["suii2024_1-12/202401_水位.csv"]


def test_parse_wide_csv_three_header_rows_and_dam_unit_row():
    p = c94.parse_wide_csv(SUII)
    assert p["ids"] == ["139", "144", "200"] and p["names"][0] == "第2屋仁橋"
    assert p["rows"][0] == ("2024/01/01 00:00", ["10", "***", "5"])
    d = c94.parse_wide_csv(DAM, has_unit_row=True)
    assert d["label"] == "大和ダム" and d["units"][0] == "[EL.10^2m]" and len(d["rows"]) == 2


def test_classify_symbols_negative_and_other():
    assert c94.classify("-3") == (-3.0, "ok")
    assert c94.classify("***")[0] is None and "欠測" in c94.classify("***")[1]
    assert "休止" in c94.classify("---")[1] and "空欄" in c94.classify("")[1]
    assert c94.classify("abc") == (None, "other:abc")


def zin(files):
    return io.BytesIO(make_zip(files))


KIKI = "suii2024_1-12/202401_危機管理型水位計.csv"


def test_suii_daily_max_min_missing_counts_and_negative_kept():
    acc = c94.Acc()
    wanted = {True: {139: ("suii_kiki_139", "第2屋仁橋"), 144: ("suii_kiki_144", "朝戸橋")}, False: {}}
    c94.collect_zip(zin({KIKI: SUII}), "suii", wanted, acc)
    assert not acc.mismatch
    # 00:00 は前日の 24:00: 2024/01/01 00:00 の 10 は 2023-12-31、2024/02/01 00:00 の 1 は 2024-01-31
    assert acc.vals[("suii_kiki_139", "", "2024-01-01")] == [-3.0, 25.0]
    assert acc.vals[("suii_kiki_139", "", "2023-12-31")] == [10.0]
    assert acc.vals[("suii_kiki_139", "", "2024-01-31")] == [1.0]
    assert acc.vals[("suii_kiki_144", "", "2024-01-01")] == [40.0]
    assert acc.bad[("suii_kiki_144", "障害・欠測(***)")] == 1
    assert acc.bad[("suii_kiki_144", "休止・該当なし(---)")] == 1
    assert acc.bad[("suii_kiki_144", "記録なし(空欄)")] == 1
    assert acc.bad[("suii_kiki_139", "other:abc")] == 1
    rows = c94.daily_rows(acc, (2024, 2024), {"suii_kiki_139": "第2屋仁橋"})
    d1 = {r["variable"]: r["value"] for r in rows if r["station_id"] == "suii_kiki_139" and r["datetime"] == "2024-01-01"}
    assert d1 == {"水位_日最高_cm": 25.0, "水位_日最低_cm": -3.0}
    assert all(r["unit"] == "cm" and r["source_id"] == "kagoshima_kasen_suii_kiki_amami" for r in rows)
    # 他県の局（列 ID 200）は出ない
    assert {r["station_id"] for r in rows} == {"suii_kiki_139", "suii_kiki_144"}


def test_normal_and_kiki_stations_go_to_separate_sources():
    assert c94.source_of("suii_181") == "kagoshima_kasen_suii_amami"
    assert c94.source_of("suii_kiki_139") == "kagoshima_kasen_suii_kiki_amami"
    assert c94.source_of("choui_4") == "kagoshima_kasen_choui_amami" and c94.source_of("dam_2") == "kagoshima_kasen_dam_amami"
    assert set(regions.get("jp-46")["station_series"]) == {c94.source_of(x) for x in ("suii_1", "suii_kiki_1", "choui_1", "dam_1")}


def test_name_mismatch_column_is_not_taken_and_counted():
    acc = c94.Acc()
    wanted = {True: {139: ("suii_kiki_139", "別の名前"), 144: ("suii_kiki_144", "朝戸橋")}, False: {}}
    c94.collect_zip(zin({KIKI: SUII}), "suii", wanted, acc)
    assert acc.mismatch == Counter({("suii_kiki_139", "第2屋仁橋"): 1})
    assert {k[0] for k in acc.vals} == {"suii_kiki_144"}       # 名前が違う列は取り込まない


def test_midnight_belongs_to_previous_day_so_month_end_and_last_file_have_no_partial_day():
    assert c94.obs_date("2026/10/01 00:00") == "2026-09-30" and c94.obs_date("2026/09/30 00:10") == "2026-09-30"
    assert c94.obs_date("2025/01/01 0:00") == "2024-12-31" and c94.obs_date("2025/02/30 01:00") is None
    csv_text = "危機管理型水位\n2,139\n観測時刻,第2屋仁橋\n2026/09/30 23:50,5\n2026/10/01 00:00,7\n"
    acc = c94.Acc()
    c94.collect_zip(zin({"suii2026_1-12/202609_危機管理型水位計.csv": csv_text}), "suii",
                    {True: {139: ("suii_kiki_139", "第2屋仁橋")}, False: {}}, acc)
    rows = c94.daily_rows(acc, (2026, 2026), {})
    assert {r["datetime"] for r in rows} == {"2026-09-30"} and {r["n_obs"] for r in rows} == {2}


def test_year_filter_uses_the_assigned_date():
    acc = c94.Acc()
    acc.vals[("choui_4", "", "2025-01-01")] = [7.0]
    acc.vals[("choui_4", "", "2024-12-31")] = [1.0, 3.0]
    rows = c94.daily_rows(acc, (2008, 2024), {})
    assert {(r["datetime"], r["variable"]): r["value"] for r in rows} == {
        ("2024-12-31", "潮位_日平均"): 2.0, ("2024-12-31", "潮位_日最高"): 3.0, ("2024-12-31", "潮位_日最低"): 1.0}


def test_dam_series_and_blank_rate_omitted():
    acc = c94.Acc()
    files = {"dam2024_1-12/202401_ダム諸量_大和ダム.csv": DAM,
             "dam2024_1-12/202401_ダム諸量_川辺ダム.csv": DAM.replace("大和ダム", "川辺ダム")}
    c94.collect_zip(zin(files), "dam", {"大和ダム": "dam_2"}, acc)
    rows = c94.daily_rows(acc, (2008, 2100), {"dam_2": "大和ダム"})
    v = {r["variable"]: r for r in rows}
    assert v["貯水位_日平均"]["value"] == 4356.0 and v["貯水位_日平均"]["unit"] == "cm"
    assert v["貯水位_日最低"]["value"] == 4355.0
    assert v["全流入量_日平均"]["value"] == 200.0 and v["全流入量_日最高"]["value"] == 300.0
    assert v["全流入量_日平均"]["unit"] == "10^-3 m3/s" and v["貯水率_治水_日平均"]["unit"] == "0.1%"
    assert v["貯水率_治水_日平均"]["value"] == 6.0
    assert "貯水率_利水_日平均" not in v  # 値が '---' と空欄だけ
    assert "空容量" not in " ".join(v)
    assert {r["station_id"] for r in rows} == {"dam_2"}
    assert acc.bad[("dam_2", "休止・該当なし(---)")] == 1


def test_dam_unit_row_mismatch_stops_with_member_and_column():
    bad = DAM.replace("[EL.10^2m]", "[EL.m]")
    with pytest.raises(ValueError, match=r"202401_ダム諸量_大和ダム\.csv.*貯水位.*EL\.m"):
        c94.collect_zip(zin({"dam2024_1-12/202401_ダム諸量_大和ダム.csv": bad}), "dam", {"大和ダム": "dam_2"}, c94.Acc())


def test_station_js_filtered_by_bbox_and_muni_from_gsi():
    bbox = (129.1, 27.95, 129.85, 28.8)
    assert [s[:2] for s in c94.amami_stations(STATION_JS, bbox)] == [(182, "稲袋橋")]
    assert [s[:2] for s in c94.amami_stations(TIDE_JS, bbox)] == [(4, "名瀬")]
    assert [s[:2] for s in c94.amami_stations(DAM_JS, bbox)] == [(2, "大和ダム")]
    assert c94.muni_from_gsi({"results": {"muniCd": "46523", "lv01Nm": "大和浜"}}) == ("46523", "大和村")
    assert c94.muni_from_gsi({"results": {"muniCd": "99999"}}) == ("99999", None)
    assert set(c94.MUNI_NAME) == set(regions.get("jp-46")["muni_codes"])


def test_unpadded_timestamps_and_utf8_js():
    assert c94.norm_ts("2025/3/1 0:10") == "2025/03/01 00:10" and c94.obs_date("2025/3/1 0:10") == "2025-03-01"
    assert c94.norm_ts("2025/03/01 00:10") == "2025/03/01 00:10" and c94.norm_ts("x") is None
    assert c94.decode_text("\ufeff名瀬".encode("utf-8")) == "名瀬"
    assert c94.decode_text("名瀬".encode("cp932")) == "名瀬"
    acc = c94.Acc()
    p = c94.parse_wide_csv("水位,,\n2,5\n観測時刻,橋\n2025/3/1 0:10,7\n2025/03/01 00:10,7\n")
    c94.collect_samples(p, {"5": ("suii_5", "")}, acc, "t")
    assert acc.vals[("suii_5", "", "2025-03-01")] == [7.0] and not acc.bad


def test_dam_file_without_unit_row_keeps_first_observation_row():
    old = "\n".join(l for i, l in enumerate(DAM.splitlines()) if i != 3) + "\n"   # 2018年までの形式: 単位行なし
    p = c94.parse_wide_csv(old, has_unit_row=True)
    assert p["units"] is None and len(p["rows"]) == 2 and p["rows"][0][0] == "2024/01/01 00:10"
    acc = c94.Acc()
    c94.collect_zip(zin({"dam2010_1-12/201001_ダム諸量_大和ダム.csv": old}), "dam", {"大和ダム": "dam_2"}, acc)
    assert acc.unchecked_units == 6 and acc.vals[("dam_2", "貯水位", "2024-01-01")] == [4355.0, 4357.0]
