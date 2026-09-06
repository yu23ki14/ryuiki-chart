#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DwC-A 出力（data/dwca/）の機械検証。

`docs/FINAL_REPORT.md` §5 の検証表を再計算するためのスクリプト。
以前はこの検証が手作業のワンライナーで行われており再現できなかったため、
GBIF完走後の再検証にあたってスクリプトとして固定した。読み取り専用。

検証項目:
  1. meta.xml が宣言するフィールド数と、実ファイルのヘッダ列数の一致
  2. 列数不整合行（= タブ/改行がフィールド値に混入した行）の検出
  3. occurrence.txt / extendedmeasurementorfact.txt の eventID が event.txt に存在するか
  4. event.txt の eventDate の ISO 8601 適合性
  5. occurrence.txt の scientificName 空欄件数・license 列空欄件数
  6. 座標を一般化した（dataGeneralizations が非空の）occurrence 件数（FR-4.5）

eventDate について: Darwin Core の `eventDate` は ISO 8601-1:2019 の
date / dateTime に加えて「開始/終了」の**区間**表記を許容する
（例: 2019-08-01/2019-08-31、2019-08-01T10:00Z/2019-08-01T12:00Z）。
GBIF由来のレコードには dateTime 形式・区間形式が多数含まれるため、
`YYYY-MM-DD` のみを正とする検査は誤検出になる。本スクリプトは
date / dateTime / 区間の3形式を適合として扱う。
"""
import re, sys, pathlib, xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "data/dwca"

# ISO 8601: date (YYYY / YYYY-MM / YYYY-MM-DD) + 任意の時刻 + 任意の "/終了"
_DATE = r"\d{4}(-\d{2}(-\d{2})?)?"
_TIME = r"T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?"
_ONE = rf"{_DATE}({_TIME})?"
ISO8601 = re.compile(rf"^{_ONE}(/{_ONE})?$")


def header_cols(p):
    with open(p, encoding="utf-8") as f:
        return f.readline().rstrip("\n").split("\t")


def meta_field_counts():
    """meta.xml の core/extension ごとの宣言フィールド数（id/coreid 列を含む）"""
    ns = {"d": "http://rs.tdwg.org/dwc/text/"}
    root = ET.parse(D / "meta.xml").getroot()
    out = {}
    for tag in ("core", "extension"):
        for node in root.findall(f"d:{tag}", ns):
            loc = node.find("d:files/d:location", ns).text
            out[loc] = len(node.findall("d:field", ns)) + 1
    return out


def main():
    fail = 0
    meta = meta_field_counts()
    print("=== 1. meta.xml 宣言フィールド数 vs 実ファイル列数 ===")
    for fn in ("event.txt", "occurrence.txt", "extendedmeasurementorfact.txt"):
        actual, declared = len(header_cols(D / fn)), meta.get(fn)
        ok = declared == actual
        fail += 0 if ok else 1
        print(f"  {fn}: meta={declared} actual={actual} {'一致' if ok else '★不一致'}")

    # ---- event.txt ----
    cols = header_cols(D / "event.txt")
    i_id, i_date = cols.index("eventID"), cols.index("eventDate")
    event_ids = set()
    n_ev = bad_ev = blank_date = bad_date = 0
    bad_date_samples = []
    with open(D / "event.txt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            n_ev += 1
            if len(p) != len(cols):
                bad_ev += 1
                continue
            event_ids.add(p[i_id])
            d = p[i_date]
            if d == "":
                blank_date += 1
            elif not ISO8601.match(d):
                bad_date += 1
                if len(bad_date_samples) < 5:
                    bad_date_samples.append(d)
    fail += bad_ev + bad_date
    print(f"\n=== 2. event.txt ===")
    print(f"  行数(ヘッダ除く)={n_ev}  ユニークeventID={len(event_ids)}  列数不整合={bad_ev}")
    print(f"  eventDate 空欄={blank_date}  ISO8601(date/dateTime/区間)非適合={bad_date}"
          f"{'  例: ' + str(bad_date_samples) if bad_date_samples else ''}")

    # ---- occurrence.txt ----
    cols = header_cols(D / "occurrence.txt")
    i_ev, i_sci = cols.index("eventID"), cols.index("scientificName")
    i_gen = cols.index("dataGeneralizations") if "dataGeneralizations" in cols else None
    i_lic = cols.index("license") if "license" in cols else None
    n_oc = bad_oc = miss_ev = blank_sci = n_gen = blank_lic = 0
    with open(D / "occurrence.txt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            n_oc += 1
            if len(p) != len(cols):
                bad_oc += 1
                continue
            if p[i_ev] not in event_ids:
                miss_ev += 1
            if p[i_sci].strip() == "":
                blank_sci += 1
            if i_gen is not None and p[i_gen].strip() != "":
                n_gen += 1
            if i_lic is not None and p[i_lic].strip() == "":
                blank_lic += 1
    fail += bad_oc + miss_ev
    print(f"\n=== 3. occurrence.txt ===")
    print(f"  行数={n_oc}  列数不整合={bad_oc}")
    print(f"  eventID が event.txt に存在しない件数={miss_ev}")
    print(f"  scientificName 空欄={blank_sci}（原資料に学名が無いレコード。推測で埋めていない）")
    print(f"  license 列 空欄={blank_lic}")
    print(f"  座標一般化済み(dataGeneralizations非空)={n_gen}  ← FR-4.5")

    # ---- eMoF ----
    cols = header_cols(D / "extendedmeasurementorfact.txt")
    i_ev = cols.index("eventID")
    n_em = bad_em = miss_em = 0
    with open(D / "extendedmeasurementorfact.txt", encoding="utf-8") as f:
        f.readline()
        for line in f:
            p = line.rstrip("\n").split("\t")
            n_em += 1
            if len(p) != len(cols):
                bad_em += 1
                continue
            if p[i_ev] not in event_ids:
                miss_em += 1
    fail += bad_em + miss_em
    print(f"\n=== 4. extendedmeasurementorfact.txt ===")
    print(f"  行数={n_em}  列数不整合={bad_em}")
    print(f"  eventID が event.txt に存在しない件数={miss_em}")

    print(f"\n=== 判定: {'PASS（構造的な不整合なし）' if fail == 0 else f'FAIL（{fail}件の不整合）'} ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
