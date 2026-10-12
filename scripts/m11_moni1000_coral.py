#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""モニ1000 サンゴ礁調査（SAN01）の奄美分を ryuiki.sqlite の原本表 moni1000_coral_spots に入れる。

設計: docs/plans/MONI1000.md §9。DDL は scripts/schema_moni1000_coral.sql。
入力: data/processed/moni1000_coral_amami.csv（scripts/process_moni1000_coral.py が xlsx から作る）。
種の出現ではなく地点×年度の観測値なので、occurrence にも observation にも流さない（get_records の coral_reef_surveys だけ）。
冪等: 自分の出典（moni1000_coral_amami）の行だけを wipe して同じトランザクションで入れ直す。
検査（ずれたら止まって rollback）: 行数が CSV と一致 / record_id 一意 / 列が DDL と一致 / source_registry に出典の行がある。
本物の data/db/ryuiki.sqlite に流すのは 1 回だけ（実行前に .backup を取る）。確認は --dry-run か、一時コピーへの --db で。
"""
from __future__ import annotations

import argparse
import csv
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scripts" / "schema_moni1000_coral.sql"
DEFAULT_CSV = ROOT / "data" / "processed" / "moni1000_coral_amami.csv"
SOURCE_ID = "moni1000_coral_amami"
TABLE = "moni1000_coral_spots"
INTEGER_COLS = ("fiscal_year", "site_no", "spot_no")


class M11Error(RuntimeError):
    pass


def split_ddl(sql):
    return [s.strip() for s in "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--")).split(";")
            if s.strip()]


def read_rows(path=DEFAULT_CSV):
    with open(path, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    rows = []
    for r in raw:
        row = {k: (v if v != "" else None) for k, v in r.items()}
        for k in INTEGER_COLS:
            row[k] = int(row[k])
        rows.append(row)
    return rows


def check_rows(rows, columns):
    ids = [r["record_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise M11Error("record_id が一意でない")
    for r in rows:
        if set(r) != set(columns):
            raise M11Error(f"列が DDL と合わない: {sorted(set(r) ^ set(columns))}")
        if r["source_id"] != SOURCE_ID:
            raise M11Error(f"出典が違う行: {r['record_id']}")


def load(con, rows):
    """表を作り（無ければ）、自分の出典の行を wipe → 入れ直す。呼び出し側が commit/rollback。"""
    if not con.in_transaction:
        con.execute("BEGIN")
    for stmt in split_ddl(SCHEMA.read_text(encoding="utf-8")):
        con.execute(stmt)
    columns = [r[1] for r in con.execute(f"PRAGMA table_info({TABLE})")]
    check_rows(rows, columns)
    con.execute(f"DELETE FROM {TABLE} WHERE source_id=?", (SOURCE_ID,))
    con.executemany(f"INSERT INTO {TABLE} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    [tuple(r[c] for c in columns) for r in rows])
    n = con.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE source_id=?", (SOURCE_ID,)).fetchone()[0]
    if n != len(rows):
        raise M11Error(f"投入後の行数が合わない（{n} / {len(rows)}）")
    if not con.execute("SELECT 1 FROM source_registry WHERE source_id=?", (SOURCE_ID,)).fetchone():
        raise M11Error(f"source_registry に {SOURCE_ID} の行が無い（process_moni1000_coral.py が先）")
    return {"rows": n}


def main(argv=None):
    ap = argparse.ArgumentParser(description="モニ1000 サンゴ礁調査（奄美）を moni1000_coral_spots に入れる")
    ap.add_argument("--dry-run", action="store_true", help="DB に触らず件数だけ出す")
    ap.add_argument("--db", help="書き込み先の sqlite（既定: data/db/ryuiki.sqlite。確認は一時コピーで）")
    ap.add_argument("--csv", default=str(DEFAULT_CSV))
    args = ap.parse_args(argv)
    rows = read_rows(args.csv)
    print(f"{SOURCE_ID}: {len(rows)} 行 / 地点 {len({(r['site_no'], r['spot_no']) for r in rows})}")
    if args.dry_run:
        return
    if args.db:
        con = sqlite3.connect(args.db, timeout=30)
    else:
        from common import appdb
        con = appdb()
    con.execute("PRAGMA busy_timeout = 30000")
    try:
        res = load(con, rows)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(f"{TABLE} {res['rows']} 行")


if __name__ == "__main__":
    main()
