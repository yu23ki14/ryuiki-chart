"""c94（鹿児島県 河川砂防情報システム）の解析・集約のテスト。合成の小さな CSV 文字列と ZIP だけを使う。"""
import io
import zipfile
from collections import Counter, defaultdict

import c94_kagoshima_kasen as c94

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


def test_suii_daily_max_min_missing_counts_and_negative_kept():
    blob = make_zip({"suii2024_1-12/202401_危機管理型水位計.csv": SUII})
    samples, bad, warn = defaultdict(list), Counter(), set()
    wanted = {True: {139: ("suii_kiki_139", "第2屋仁橋"), 144: ("suii_kiki_144", "朝戸橋")}, False: {}}
    c94.collect_zip(blob, "suii", wanted, None, samples, bad, warn)
    assert not warn
    assert samples[("suii_kiki_139", "2024-01-01")] == [10.0, -3.0, 25.0]
    assert samples[("suii_kiki_144", "2024-01-02")] == [40.0]
    assert bad[("suii_kiki_144", "障害・欠測(***)")] == 1
    assert bad[("suii_kiki_144", "休止・該当なし(---)")] == 1
    assert bad[("suii_kiki_144", "記録なし(空欄)")] == 1
    assert bad[("suii_kiki_139", "other:abc")] == 1
    rows = c94.daily_rows(samples, "suii", "kagoshima_kasen_suii_amami", (2024, 2024), {"suii_kiki_139": "第2屋仁橋"})
    d1 = {r["variable"]: r["value"] for r in rows if r["station_id"] == "suii_kiki_139" and r["datetime"] == "2024-01-01"}
    assert d1 == {"水位_日最高_cm": 25.0, "水位_日最低_cm": -3.0}
    assert all(r["unit"] == "cm" for r in rows)
    # 他県の局（列 ID 200）は出ない
    assert {r["station_id"] for r in rows} == {"suii_kiki_139", "suii_kiki_144"}


def test_name_mismatch_is_reported():
    blob = make_zip({"suii2024_1-12/202401_危機管理型水位計.csv": SUII})
    warn = set()
    wanted = {True: {139: ("suii_kiki_139", "別の名前")}, False: {}}
    c94.collect_zip(blob, "suii", wanted, None, defaultdict(list), Counter(), warn)
    assert warn == {("suii_kiki_139", "第2屋仁橋", "別の名前")}


def test_year_filter_drops_next_year_boundary_row():
    samples = defaultdict(list)
    samples[("choui_4", "2025-01-01")] = [7.0]
    samples[("choui_4", "2024-12-31")] = [1.0, 3.0]
    rows = c94.daily_rows(samples, "choui", "x", (2008, 2024), {})
    assert {(r["datetime"], r["variable"]): r["value"] for r in rows} == {
        ("2024-12-31", "潮位_日平均"): 2.0, ("2024-12-31", "潮位_日最高"): 3.0, ("2024-12-31", "潮位_日最低"): 1.0}


def test_dam_series_and_blank_rate_omitted():
    blob = make_zip({"dam2024_1-12/202401_ダム諸量_大和ダム.csv": DAM,
                     "dam2024_1-12/202401_ダム諸量_川辺ダム.csv": DAM.replace("大和ダム", "川辺ダム")})
    samples, bad, warn = defaultdict(list), Counter(), set()
    c94.collect_zip(blob, "dam", None, {"大和ダム": "dam_2"}, samples, bad, warn)
    rows = c94.daily_rows(samples, "dam", "kagoshima_kasen_dam_amami", (2008, 2100), {"dam_2": "大和ダム"})
    v = {r["variable"]: r for r in rows}
    assert v["貯水位_日平均"]["value"] == 4356.0 and v["貯水位_日平均"]["unit"] == "cm"
    assert v["貯水位_日最低"]["value"] == 4355.0
    assert v["全流入量_日平均"]["value"] == 200.0 and v["全流入量_日最高"]["value"] == 300.0
    assert v["全流入量_日平均"]["unit"] == "10^-3 m3/s" and v["貯水率_治水_日平均"]["unit"] == "0.1%"
    assert v["貯水率_治水_日平均"]["value"] == 6.0
    assert "貯水率_利水_日平均" not in v  # 値が '---' と空欄だけ
    assert "空容量" not in " ".join(v)
    assert {r["station_id"] for r in rows} == {"dam_2"}
    assert bad[("dam_2|貯水率（利水）", "休止・該当なし(---)")] == 1


def test_station_js_filtered_by_bbox_and_muni_from_gsi():
    bbox = (129.1, 27.95, 129.85, 28.8)
    assert [s[:2] for s in c94.amami_stations("suii", STATION_JS, bbox)] == [(182, "稲袋橋")]
    assert [s[:2] for s in c94.amami_stations("choui", TIDE_JS, bbox)] == [(4, "名瀬")]
    assert [s[:2] for s in c94.amami_stations("dam", DAM_JS, bbox)] == [(2, "大和ダム")]
    assert c94.muni_from_gsi({"results": {"muniCd": "46523", "lv01Nm": "大和浜"}}) == ("46523", "大和村")
    assert c94.muni_from_gsi({"results": {"muniCd": "99999"}}) == ("99999", None)


def test_unpadded_timestamps_and_utf8_js():
    assert c94.norm_ts("2025/3/1 0:10") == "2025/03/01 00:10" and c94.ts_date("2025/3/1 0:10") == "2025-03-01"
    assert c94.norm_ts("2025/03/01 00:10") == "2025/03/01 00:10" and c94.norm_ts("x") is None
    assert c94.decode_text("\ufeff名瀬".encode("utf-8")) == "名瀬"
    assert c94.decode_text("名瀬".encode("cp932")) == "名瀬"
    samples, bad = defaultdict(list), Counter()
    p = c94.parse_wide_csv("水位,,\n2,5\n観測時刻,橋\n2025/3/1 0:10,7\n2025/03/01 00:10,7\n")
    c94.collect_samples(p, {"5": "suii_5"}, samples, bad, "t")
    assert samples[("suii_5", "2025-03-01")] == [7.0] and not bad


def test_partial_last_day_with_only_month_start_row_is_dropped():
    csv_text = ("危機管理型水位\n" "2,139,144\n"
                "観測時刻,第2屋仁橋,朝戸橋\n"
                "2026/09/30 23:50,5,6\n2026/10/01 00:00,7,8\n")
    blob = make_zip({"suii2026_1-12/202609_危機管理型水位計.csv": csv_text})
    samples, bad, warn = defaultdict(list), Counter(), set()
    wanted = {True: {139: ("suii_kiki_139", "第2屋仁橋")}, False: {}}
    c94.collect_zip(blob, "suii", wanted, None, samples, bad, warn)
    rows = c94.daily_rows(samples, "suii", "x", (2026, 2026), {})
    assert {r["datetime"] for r in rows} == {"2026-09-30"}   # 2026-10-01 は 00:00 の1行だけ -> 出さない
