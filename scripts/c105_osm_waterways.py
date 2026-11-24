#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenStreetMap の河川線（waterway=river/stream の名前つき way）とダム・堰（waterway=dam/weir）を Overpass API から取る。

参照元: https://github.com/yokinist/ryuiki-map（MIT、作者の許可済み）の scripts/overpass.ts・build-rivers.ts・build-karte.ts の
問い合わせの形。ただし 1° タイルではなく、範囲（神奈川県＋相模川の山梨側上流＝桂川、奄美大島）に合わせた少数の bbox で取る。

- 生の応答を data/raw/osm_waterways/<area>_{rivers,structures}.json に保存する（`_fetched_at`・`_region_id`・`_query_hash` 等を足してある）。
  保存済みで bbox＋クエリ文面のハッシュ（`_query_hash`）が一致すれば取り直さない（途中再開。不一致・--force なら取り直す）。
- Overpass の作法: 1 本ずつ・3 秒あけ・混雑（429/5xx）は 15/30/60/120 秒で取り直し・remark に error があれば途中結果を捨てる・
  ミラー（overpass.kumi.systems）へフォールバック。User-Agent は scripts/common.py の UA（個人名なし）。
- データは ODbL 1.0（© OpenStreetMap contributors）。入れるのと source_registry への登録は m12_osm_waterways.py（件数を投入後の行数に合わせるため）。使い方: python3 scripts/c105_osm_waterways.py [--force] [--only AREA ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import common  # noqa: E402
from regions import REGIONS  # noqa: E402

RAW_DIR = common.RAW / "osm_waterways"
ENDPOINTS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
PAUSE_S = 3
BACKOFF_S = (15, 30, 60, 120)
REQUEST_TIMEOUT_S = 200  # 問い合わせの timeout（180 秒）より少し長く待って打ち切る

# area -> (region_id, (lon_min, lat_min, lon_max, lat_max))。神奈川は相模川の山梨側上流（桂川。山中湖付近 東経138.87）まで含める。
# 広く問うと混雑時に時間切れになるので東西に分ける（境界をまたぐ way は両方で返る。m12 が way id で重複を除く）。
AREAS = {
    "kanagawa_w": ("jp-14", (138.7, 35.1, 139.25, 35.8)),
    "kanagawa_e": ("jp-14", (139.25, 35.1, 139.8, 35.8)),
    "amami": ("jp-46", REGIONS["jp-46"]["bbox"]),
}


def rivers_query(bbox):
    w, s, e, n = bbox
    b = f"{s},{w},{n},{e}"
    return (f'[out:json][timeout:180];\n'
            f'(way["waterway"="river"]["name"]({b}); way["waterway"="stream"]["name"]({b});)->.w;\n'
            f'.w out tags geom;\n'
            f'relation(bw.w)["type"="waterway"]["waterway"="river"];\nout skel;')


def structures_query(bbox):
    w, s, e, n = bbox
    b = f"{s},{w},{n},{e}"
    return f'[out:json][timeout:180];\n(nwr["waterway"="dam"]({b}); nwr["waterway"="weir"]({b}););\nout center tags;'


def overpass(query, post=None):
    """1 本の問い合わせ。混雑・時間切れは待って取り直す。応答の dict（remark に error が無いもの）を返す。"""
    if post is None:
        import requests  # 遅延 import: 実際に取得するときだけ（CI の reconcile に収集の依存は無い。テストは post を差し込む）
        post = requests.post
    last = ""
    for wait in (0, *BACKOFF_S):
        if wait:
            print(f"  busy ({last}), retry in {wait}s", flush=True)
            time.sleep(wait)
        for url in ENDPOINTS:
            try:
                r = post(url, data={"data": query}, headers={"User-Agent": common.UA}, timeout=REQUEST_TIMEOUT_S)
            except Exception as ex:  # noqa: BLE001
                last = repr(ex)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                continue
            if r.status_code != 200:  # 400 等の恒久的な 4xx（クエリの誤りなど）は取り直しても同じ。すぐ止める
                raise RuntimeError(f"overpass: HTTP {r.status_code} {r.text[:300]}")
            try:
                body = r.json()
            except ValueError:
                last = "not json"
                continue
            # 時間切れ・メモリ不足でも HTTP 200 で途中までの結果が返り remark に error が書かれる。途中の結果は使わない
            if "error" in (body.get("remark") or ""):
                last = body["remark"]
                continue
            body["_endpoint"] = url
            return body
    raise RuntimeError(f"overpass: {last}")


def query_hash(bbox, query):
    return hashlib.sha256((json.dumps(list(bbox)) + "\n" + query).encode("utf-8")).hexdigest()


def cache_is_current(path, bbox, query):
    """保存済みの生の応答が、今の bbox＋クエリ文面で取ったものか（`_query_hash` の一致）。"""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("_query_hash") == query_hash(bbox, query)
    except ValueError:
        return False


def fetch_area(area, kind, force=False):
    region, bbox = AREAS[area]
    path = RAW_DIR / f"{area}_{kind}.json"
    query = (rivers_query if kind == "rivers" else structures_query)(bbox)
    if not force and cache_is_current(path, bbox, query):
        print(f"[{area}/{kind}] 取得済み（{path.name}）", flush=True)
        return path
    t0 = time.time()
    body = overpass(query)
    body.update({"_fetched_at": common.now(), "_area": area, "_region_id": region, "_bbox": list(bbox), "_query": query,
                 "_query_hash": query_hash(bbox, query)})
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    print(f"[{area}/{kind}] {len(body.get('elements', []))} 要素 {time.time() - t0:.0f}s", flush=True)
    time.sleep(PAUSE_S)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="OSM の河川線とダム・堰を Overpass から取る")
    ap.add_argument("--force", action="store_true", help="取得済みでも取り直す")
    ap.add_argument("--only", nargs="*", choices=sorted(AREAS), help="取る範囲（既定は全部）")
    args = ap.parse_args(argv)
    for area in args.only or AREAS:
        for kind in ("rivers", "structures"):
            fetch_area(area, kind, args.force)


if __name__ == "__main__":
    main()
