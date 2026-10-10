"""局の表（regions の station_tables の出典）のうち、座標の無い局を registry/place/site_supplement.csv に載せる。

m01 は座標のある局だけを sites に入れる（座標を推測しない）。座標の無い局は sensor_timeseries にだけ現れ、
build_place が「site_supplement.csv に無い site_id」として止まるので、局の表
（data/processed/<出典>.jsonl。例 kagoshima_kasen_stations_amami）から機械的に行を作る。
lat/lon は空のまま（place は status=needs_review になる）。再実行しても同じ結果（この出典の行だけ入れ直す）。

    python3 scripts/r03_site_supplement.py --source kagoshima_kasen_stations_amami [--check]

--check は書かずに、CSV が局の表と一致するかだけ見る（ずれていれば終了コード 1）。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import regions  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
SUPPLEMENT = ROOT / "registry" / "place" / "site_supplement.csv"
COLUMNS = ("site_id", "name_ja", "lat", "lon", "definition_ref", "place_local")


def supplement_lines(src: str, stations: list[dict]) -> list[str]:
    """座標の無い局 → CSV の行（改行なし）。局の表の順を保つ。"""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in stations:
        if r.get("lat") is not None and r.get("lon") is not None:
            continue
        ref = r.get("source_ref") or src
        w.writerow([f"{src}__{r['station_id']}", r["station_name_ja"], "", "",
                    f"{ref}（data/processed/{src}.jsonl station_id={r['station_id']}; "
                    "局の表に座標が無いので推測していない）", ""])
    return buf.getvalue().splitlines()


def merge(text: str, src: str, new_lines: list[str]) -> str:
    """text から src の行を除き、new_lines を末尾に足す（ほかの行はそのまま）。"""
    nl = "\r\n" if "\r\n" in text else "\n"   # 既存の改行（site_supplement.csv は CRLF）を保つ
    keep = [l for l in text.splitlines() if not l.startswith(f"{src}__")]
    return nl.join(keep + new_lines) + nl


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    declared = sorted(t for r in regions.REGIONS.values() for t in r.get("station_tables", ()))
    ap.add_argument("--source", required=True, choices=declared)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--proc", default=str(PROC))
    ap.add_argument("--csv", default=str(SUPPLEMENT))
    a = ap.parse_args(argv)
    src = a.source
    p = pathlib.Path(a.proc) / f"{src}.jsonl"
    if not p.exists():
        print(f"{p.name} が無いので何もしない")
        return 0
    stations = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    path = pathlib.Path(a.csv)
    text = path.open(encoding="utf-8", newline="").read()
    new = merge(text, src, supplement_lines(src, stations))
    if a.check:
        ok = new.rstrip() == text.rstrip()
        print("一致" if ok else "ずれている（r03_site_supplement.py を実行する）")
        return 0 if ok else 1
    path.open("w", encoding="utf-8", newline="").write(new)
    print(f"{src}: 座標の無い局 {len(supplement_lines(src, stations))} 行を {path.name} に反映")
    return 0


if __name__ == "__main__":
    sys.exit(main())
