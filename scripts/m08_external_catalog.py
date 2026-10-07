#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部ポータルの目録（CKAN 4 インスタンス + e-Stat 7 件）を ryuiki.sqlite の原本表
（external_dataset / external_resource）に入れる。

設計: docs/plans/MCP_EXTERNAL_CATALOG.md §1・§2・§3。DDL は scripts/schema_catalog.sql。
MCP / AI の `find_datasets` が読む。値そのものは持たない（定義と、最新を取りに行く URL だけ）。

入力（data/processed。新しい収集はしない）:
  ckan_datasets.jsonl / ckan_resources.jsonl                  c01（神奈川県 + 相模原市。同じファイル）
  ckan_datasets_bodik.jsonl / ckan_resources_bodik.jsonl      c86
  ckan_datasets_yokohama.jsonl / ckan_resources_yokohama.jsonl  c86
  ckan_env_index.jsonl                                        c01 系。変換済み CSV の見出し（§3）
  estat_agri_census_kanagawa.jsonl / estat_census_population_kanagawa.jsonl / estat_shozaiki_kanagawa.jsonl

方針:
- 冪等: 出典ごとに external_dataset と、その出典の dataset_key の external_resource を DELETE してから INSERT。
  入力が無い出典は黙って飛ばし、最後に列挙する（既存の行は触らない）。
- 列の定義（sheets_json の header）は、見出しを検出できたものだけ根拠つきで入れる。推測しない（§3・メインの判断 1）。
  基準は `header_is_reliable`（1 行目の 3 分の 2 以上が空・col_N/field_N・数値でなく、needs_human が False）。
- 収穫日 fetched_at は source_registry.fetched_at（出典単位）。api_url（package_show）を「最新」の正とする。
- ライセンスが空の行は NULL のまま入れる（除外しない。ADR-0028）。
- 本物の data/db/ryuiki.sqlite に流すのはメインだけ。確認は一時コピーの DB に `--db` で。
"""
import argparse
import csv
import datetime
import json
import pathlib
import re
import sqlite3
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scripts" / "schema_catalog.sql"
PROC = ROOT / "data" / "processed"

# --- CKAN（instance は c01/c86 の登録名。base は c86 の注記どおり BODIK は data.bodik.jp）---
CKAN_INSTANCES = {
    "kanagawa_pref": ("ckan_kanagawa_pref", "https://catalog.opendata.pref.kanagawa.jp"),
    "sagamihara": ("ckan_sagamihara", "https://opendata.city.sagamihara.kanagawa.jp"),
    "bodik_kanagawa": ("ckan_bodik_kanagawa", "https://data.bodik.jp"),
    "yokohama": ("ckan_yokohama", "https://data.city.yokohama.lg.jp"),
}
# 入力の組。同じファイルに複数インスタンスが入る（c01）。
CKAN_FILES = [
    ("ckan_datasets.jsonl", "ckan_resources.jsonl", ("kanagawa_pref", "sagamihara")),
    ("ckan_datasets_bodik.jsonl", "ckan_resources_bodik.jsonl", ("bodik_kanagawa",)),
    ("ckan_datasets_yokohama.jsonl", "ckan_resources_yokohama.jsonl", ("yokohama",)),
]
ENV_INDEX = "ckan_env_index.jsonl"
DESCRIPTION_CUT = 800  # c01・c86 が notes を [:800] で切っている

# --- e-Stat（c64 の statInfId・URL の形。c90 の境界 GIS の URL。test_m08 が c64/c90 の文字列との一致を固定する）---
ESTAT_PAGE = "https://www.e-stat.go.jp/stat-search/files?stat_infid={id}"
ESTAT_FILE = "https://www.e-stat.go.jp/stat-search/file-download?statInfId={id}&fileKind=0"
SHOZAIKI_DLSURVEY = "A002005212020"
SHOZAIKI_DATA = ("https://www.e-stat.go.jp/gis/statmap-search/data"
                 "?dlserveyId=A002005212020&code=14&coordSys=1&format=shape&downloadType=5")
CENSUS_POP_ID = "000040454825"
CENSUS_POP_TITLE = ("令和7年国勢調査 速報集計 人口速報集計（男女別人口及び世帯総数） 第1表 男女別人口、"
                    "2020年（令和2年）の人口（組替）、世帯数、2020年（令和2年）の世帯数（組替）、5年間の人口増減数、"
                    "5年間の人口増減率、5年間の世帯増減数、5年間の世帯増減率、人口性比、面積（参考）及び人口密度"
                    "－全国、都道府県、市区町村")
ESTAT_SOURCES = ("estat_agri_census_kanagawa", "estat_census_population_kanagawa", "estat_shozaiki_kanagawa")
ESTAT_INDICATOR_MAX = 20

CATALOG_SOURCES = tuple(sid for sid, _ in CKAN_INSTANCES.values()) + ESTAT_SOURCES
HEADER_MAX_COLS = 100
STALE_DAYS = 30

HEADER_BASIS_CSV = "converted_csv_first_row"
HEADER_BASIS_ESTAT = "harvested_indicators"


class M08Error(RuntimeError):
    pass


def read_jsonl(path: pathlib.Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def text(v):
    """空白だけ・None は None。0 などの値はそのまま文字列で返さない（呼び出し側で扱う）。"""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def to_int(v):
    s = text(v)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 列の定義（§3）
# ---------------------------------------------------------------------------
_PLACEHOLDER = re.compile(r"^(col|field|column|unnamed)[_ :]*\d*$", re.I)
_NUMERIC = re.compile(r"^[-+]?[\d,.]+%?$")


def header_is_reliable(cells: list[str], needs_human: bool) -> bool:
    """変換 CSV の 1 行目が見出しと言えるか。機械的な基準（推測しない）:
    needs_human が False で、1 行目の 3 分の 2 以上が「空でも col_N/field_N でも数値でもない」セル。"""
    if needs_human or not cells:
        return False
    good = [c for c in cells if c and not _PLACEHOLDER.match(c) and not _NUMERIC.match(c)]
    return len(good) * 3 >= 2 * len(cells)


def read_first_row(path: pathlib.Path) -> list[str] | None:
    csv.field_size_limit(1 << 27)
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        row = next(csv.reader(f), None)
    if row is None:
        return None
    return [" ".join(c.split()) for c in row]


def sheet_name(note) -> str | None:
    m = re.match(r"^sheet=(.*?)(?:\s+encoding=.*)?$", note or "")
    return text(m.group(1)) if m else None


def build_sheets(env_rows: list[dict], root: pathlib.Path) -> tuple[dict[tuple[str, str], list[dict]], dict]:
    """ckan_env_index から `{(source_id, resource_id): [sheet]}`。`web_` 始まり（CKAN 外）と
    変換できなかった行（output_path が空）は除く。戻り値の 2 つ目は集計（テスト・ログ用）。"""
    out: dict[tuple[str, str], list[dict]] = {}
    stat = {"rows": 0, "sheets": 0, "with_header": 0, "no_file": 0}
    for r in env_rows:
        rid = text(r.get("resource_id"))
        inst = r.get("instance")
        if rid is None or rid.startswith("web_") or inst not in CKAN_INSTANCES or not text(r.get("output_path")):
            continue
        stat["rows"] += 1
        p = root / r["output_path"]
        header = None
        if p.exists():
            cells = read_first_row(p)
            if cells is not None and header_is_reliable(cells, str(r.get("needs_human")) == "True"):
                header = cells
        else:
            stat["no_file"] += 1
        sheet: dict = {"sheet": sheet_name(r.get("note")), "n_rows": to_int(r.get("n_rows")), "n_cols": to_int(r.get("n_cols")),
                       "header": header}
        if header is not None:
            sheet["header_basis"] = HEADER_BASIS_CSV
            if len(header) > HEADER_MAX_COLS:
                sheet["header"] = header[:HEADER_MAX_COLS]
                sheet["header_truncated"] = True
            stat["with_header"] += 1
        stat["sheets"] += 1
        out.setdefault((CKAN_INSTANCES[inst][0], rid), []).append(sheet)
    stat["resources_with_header"] = sum(1 for v in out.values() if any(s["header"] is not None for s in v))
    return out, stat


# ---------------------------------------------------------------------------
# CKAN
# ---------------------------------------------------------------------------
def ckan_rows(processed: pathlib.Path, instances: tuple[str, ...], ds_file: str, res_file: str,
              fetched: dict[str, str], sheets: dict) -> tuple[list[tuple], list[tuple]]:
    datasets, resources = [], []
    seen_ds: set[str] = set()
    for r in read_jsonl(processed / ds_file):
        inst = r["instance"]
        if inst not in instances:
            continue
        sid, base = CKAN_INSTANCES[inst]
        did = r["dataset_id"]
        key = f"{sid}:{did}"
        if key in seen_ds:
            raise M08Error(f"dataset_key の重複: {key}")
        seen_ds.add(key)
        if r.get("url") and not r["url"].startswith(base + "/dataset/"):
            raise M08Error(f"{key}: url {r['url']!r} が base {base} の規則から外れている")
        notes = r.get("notes") or ""
        datasets.append((
            key, sid, "ckan", did, text(r.get("name")), r.get("title") or "", text(notes),
            1 if len(notes) >= DESCRIPTION_CUT else 0,
            text(r.get("organization")), text(r.get("license")), text(r.get("license_url")),
            text(r.get("groups")), text(r.get("tags")), int(r.get("n_resources") or 0), text(r.get("metadata_modified")),
            f"{base}/dataset/{r['name']}", f"{base}/api/3/action/package_show?id={did}", fetched[sid],
        ))
    seen_res: set[str] = set()
    for r in read_jsonl(processed / res_file):
        inst = r["instance"]
        if inst not in instances:
            continue
        sid, base = CKAN_INSTANCES[inst]
        dkey = f"{sid}:{r['dataset_id']}"
        if dkey not in seen_ds:
            raise M08Error(f"resource {r['resource_id']} の dataset {dkey} が目録に無い")
        rkey = f"{sid}:{r['resource_id']}"
        if rkey in seen_res:
            raise M08Error(f"resource_key の重複: {rkey}")
        seen_res.add(rkey)
        sh = sheets.get((sid, r["resource_id"]))
        resources.append((
            rkey, dkey, text(r.get("resource_name")), text(r.get("format")), to_int(r.get("size")),
            text(r.get("last_modified")), text(r.get("url")),
            f"{base}/dataset/{r['dataset_id']}/resource/{r['resource_id']}",
            json.dumps(sh, ensure_ascii=False) if sh else None,
        ))
    return datasets, resources


# ---------------------------------------------------------------------------
# e-Stat
# ---------------------------------------------------------------------------
def estat_sheet(rows: list[dict]) -> dict:
    """値の行（estat_*.jsonl）から、表の指標（列の定義）と単位。値は持たない。出現順で上位 20。"""
    inds: dict[str, str | None] = {}
    for r in rows:
        k = text(r.get("indicator_ja"))
        if k is not None and k not in inds:
            inds[k] = text(r.get("unit_ja"))
    units = sorted({u for u in inds.values() if u})
    names = list(inds)
    sheet: dict = {"sheet": None, "n_rows": None, "n_cols": None, "header": names[:ESTAT_INDICATOR_MAX] or None,
                   "header_basis": HEADER_BASIS_ESTAT if names else None, "units": units}
    if len(names) > ESTAT_INDICATOR_MAX:
        sheet["header_truncated"] = True
    if not names:
        del sheet["header_basis"]
    return sheet


def estat_rows(processed: pathlib.Path, src_meta: dict[str, dict], only: set[str]) -> tuple[list[tuple], list[tuple], list[str]]:
    datasets, resources, skipped = [], [], []

    def add(sid, did, title, desc, page, file_url, fmt, rname, sheet):
        m = src_meta[sid]
        key = f"{sid}:{did}"
        datasets.append((key, sid, "estat", did, None, title, desc, 0, text(m.get("publisher")), text(m.get("license")), None,
                         None, None, 1, None, page, None, m["fetched_at"]))
        resources.append((f"{sid}:{did}:file", key, rname, fmt, None, None, file_url, page, json.dumps([sheet], ensure_ascii=False)))

    sid = "estat_agri_census_kanagawa"
    p = processed / "estat_agri_census_kanagawa.jsonl"
    if sid in only:
        if not p.exists():
            skipped.append(sid)
        else:
            by: dict[str, list[dict]] = {}
            for r in read_jsonl(p):
                m = re.search(r"statInfId=(\d+)", r["source_ref"])
                if not m:
                    raise M08Error(f"source_ref に statInfId が無い: {r['source_ref']!r}")
                by.setdefault(m.group(1), []).append(r)
            for did in sorted(by):
                titles = {r["table_ja"] for r in by[did]}
                if len(titles) != 1:
                    raise M08Error(f"statInfId={did} の表題が一意でない: {titles}")
                title = titles.pop()
                add(sid, did, title, None, ESTAT_PAGE.format(id=did), ESTAT_FILE.format(id=did), "XLS", title, estat_sheet(by[did]))
    sid = "estat_census_population_kanagawa"
    p = processed / "estat_census_population_kanagawa.jsonl"
    if sid in only:
        if not p.exists():
            skipped.append(sid)
        else:
            rows = read_jsonl(p)
            ids = {m.group(1) for r in rows if (m := re.search(r"statInfId=(\d+)", r["source_ref"]))}
            if ids != {CENSUS_POP_ID}:
                raise M08Error(f"国勢調査の statInfId が想定（{CENSUS_POP_ID}）と違う: {ids}")
            notes = {text(r.get("notes")) for r in rows} - {None}
            add(sid, CENSUS_POP_ID, CENSUS_POP_TITLE, notes.pop() if len(notes) == 1 else None,
                ESTAT_PAGE.format(id=CENSUS_POP_ID), ESTAT_FILE.format(id=CENSUS_POP_ID), "XLS", CENSUS_POP_TITLE,
                estat_sheet(rows))
    sid = "estat_shozaiki_kanagawa"
    if sid in only:
        if not (processed / "estat_shozaiki_kanagawa.jsonl").exists():
            skipped.append(sid)
        else:
            m = src_meta[sid]
            # 境界 GIS はファイルの属性表を取り出していないので、列の定義は持たない（header: null）
            add(sid, SHOZAIKI_DLSURVEY, m["name"], None, m["url"], SHOZAIKI_DATA, "SHP", m["name"],
                {"sheet": None, "n_rows": None, "n_cols": None, "header": None})
    return datasets, resources, skipped


# ---------------------------------------------------------------------------
# 書き込み
# ---------------------------------------------------------------------------
DS_COLS = ("dataset_key", "source_id", "portal", "dataset_id", "name", "title", "description", "description_truncated",
           "organization", "license", "license_url", "groups", "tags", "n_resources", "metadata_modified",
           "page_url", "api_url", "fetched_at")
RES_COLS = ("resource_key", "dataset_key", "name", "format", "size", "last_modified", "direct_url", "page_url", "sheets_json")


def source_meta(con: sqlite3.Connection) -> dict[str, dict]:
    cur = con.execute("SELECT source_id, name, publisher, url, license, fetched_at FROM source_registry WHERE source_id IN (%s)"
                      % ",".join("?" * len(CATALOG_SOURCES)), CATALOG_SOURCES)
    cols = [d[0] for d in cur.description]
    meta = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    missing = [s for s in CATALOG_SOURCES if s not in meta or not meta[s].get("fetched_at")]
    if missing:
        raise M08Error(f"source_registry に出典（または fetched_at）が無い: {missing}")
    return meta


def load(con: sqlite3.Connection, processed: pathlib.Path, root: pathlib.Path = ROOT) -> dict:
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    meta = source_meta(con)
    fetched = {s: m["fetched_at"] for s, m in meta.items()}
    env_path = processed / ENV_INDEX
    sheets, sheet_stat = build_sheets(read_jsonl(env_path), root) if env_path.exists() else ({}, {})

    per_source: dict[str, tuple[list, list]] = {}
    skipped: list[str] = []
    for ds_file, res_file, insts in CKAN_FILES:
        if not (processed / ds_file).exists() or not (processed / res_file).exists():
            skipped.extend(CKAN_INSTANCES[i][0] for i in insts)
            continue
        ds, res = ckan_rows(processed, insts, ds_file, res_file, fetched, sheets)
        for i in insts:
            sid = CKAN_INSTANCES[i][0]
            per_source[sid] = ([d for d in ds if d[1] == sid], [r for r in res if r[1].startswith(sid + ":")])
    e_ds, e_res, e_skipped = estat_rows(processed, meta, set(ESTAT_SOURCES))
    skipped.extend(e_skipped)
    for sid in ESTAT_SOURCES:
        if sid in e_skipped:
            continue
        per_source[sid] = ([d for d in e_ds if d[1] == sid], [r for r in e_res if r[1].startswith(sid + ":")])

    # 目録の孤児（resource の dataset が無い）は ckan_rows が止める。n_resources と実数の食い違いは数えて出す（止めない）。
    for sid, (ds, res) in per_source.items():
        con.execute("DELETE FROM external_resource WHERE dataset_key IN (SELECT dataset_key FROM external_dataset WHERE source_id = ?)", (sid,))
        con.execute("DELETE FROM external_dataset WHERE source_id = ?", (sid,))
        con.executemany(f"INSERT INTO external_dataset ({','.join(DS_COLS)}) VALUES ({','.join('?' * len(DS_COLS))})", ds)
        con.executemany(f"INSERT INTO external_resource ({','.join(RES_COLS)}) VALUES ({','.join('?' * len(RES_COLS))})", res)
    n_ds = con.execute("SELECT count(*) FROM external_dataset").fetchone()[0]
    n_res = con.execute("SELECT count(*) FROM external_resource").fetchone()[0]
    orphan = con.execute("SELECT count(*) FROM external_resource r WHERE NOT EXISTS "
                         "(SELECT 1 FROM external_dataset d WHERE d.dataset_key = r.dataset_key)").fetchone()[0]
    by_source = dict(con.execute("SELECT source_id, count(*) FROM external_dataset GROUP BY source_id ORDER BY source_id"))
    unmatched = 0
    if sheets:
        have = {r[0] for r in con.execute("SELECT resource_key FROM external_resource")}
        unmatched = sum(1 for (sid, rid) in sheets if f"{sid}:{rid}" not in have)
    return {"datasets": n_ds, "resources": n_res, "orphans": orphan, "by_source": by_source, "skipped": skipped,
            "sheet_stat": sheet_stat, "sheets_unmatched": unmatched}


def stale_warnings(processed: pathlib.Path, now: float | None = None) -> list[str]:
    now = now if now is not None else time.time()
    names = [f for pair in CKAN_FILES for f in pair[:2]] + [ENV_INDEX]
    out = []
    for n in sorted(set(names)):
        p = processed / n
        if p.exists():
            days = (now - p.stat().st_mtime) / 86400
            if days > STALE_DAYS:
                out.append(f"{n}: 最終更新 {datetime.datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d}（{int(days)} 日前。収集の再実行を検討）")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", help="書き込み先の sqlite（既定: data/db/ryuiki.sqlite。確認は一時コピーで）")
    ap.add_argument("--processed", default=str(PROC))
    args = ap.parse_args(argv)
    processed = pathlib.Path(args.processed)
    con = sqlite3.connect(args.db or str(ROOT / "data" / "db" / "ryuiki.sqlite"), timeout=30)
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        res = load(con, processed)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"external_dataset {res['datasets']} / external_resource {res['resources']}（孤児 {res['orphans']}）")
    for sid, n in res["by_source"].items():
        print(f"  {sid}: {n}")
    if res["sheet_stat"]:
        s = res["sheet_stat"]
        print(f"  見出し: {s['with_header']}/{s['sheets']} シート（{s['resources_with_header']} resource）。"
              f"原本の目録に無い resource のシート {res['sheets_unmatched']}")
    if res["skipped"]:
        print(f"入力が無いので飛ばした出典: {', '.join(res['skipped'])}", file=sys.stderr)
    for w in stale_warnings(processed):
        print(f"警告: {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
