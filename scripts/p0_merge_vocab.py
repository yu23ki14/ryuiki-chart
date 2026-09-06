#!/usr/bin/env python3
"""P0の統合: サブエージェントが出力した _p0p4_*.json を集約し、
- data/vocab/vocab.json (vocab_version付き) を書き出す
- vocab_areas / vocab_indicators / vocab_units / vocab_eras に投入
- notes テーブルに P4 注記を投入
値は一切扱わない。似た名前の統合は一切行わない(そのまま並べる)。
"""
import sys, json, glob, sqlite3
sys.path.insert(0, "scripts")
from common import DB, ROOT

VOCAB_VERSION = "v1"
VOCAB_DIR = ROOT / "data/vocab"


def load_all():
    docs = []
    for f in sorted(glob.glob(str(VOCAB_DIR / "_p0p4_*.json"))):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        docs.extend(data)
    return docs


def main():
    docs = load_all()
    con = sqlite3.connect(DB / "cells.sqlite", timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()

    cur.execute("DELETE FROM vocab_areas")
    cur.execute("DELETE FROM vocab_indicators")
    cur.execute("DELETE FROM vocab_units")
    cur.execute("DELETE FROM vocab_eras")
    cur.execute("DELETE FROM notes")

    vocab_json = {"vocab_version": VOCAB_VERSION, "areas": [], "indicators": [], "units": [], "eras": []}

    n_notes = 0
    n_blocks = 0
    for d in docs:
        doc_id = d["doc_id"]
        for a in d.get("areas", []):
            if isinstance(a, str):
                a = {"name": a, "definition": None, "found_definition": False, "pages": []}
            cur.execute(
                "INSERT INTO vocab_areas (doc_id,name,definition,found_definition,pages) VALUES (?,?,?,?,?)",
                (doc_id, a.get("name"), a.get("definition"),
                 int(bool(a.get("found_definition"))), json.dumps(a.get("pages", []))),
            )
            vocab_json["areas"].append({"doc_id": doc_id, **a})
        for i in d.get("indicators", []):
            if isinstance(i, str):
                i = {"name": i, "unit": None, "method": None, "pages": []}
            cur.execute(
                "INSERT INTO vocab_indicators (doc_id,name,unit,method,pages) VALUES (?,?,?,?,?)",
                (doc_id, i.get("name"), i.get("unit"), i.get("method"), json.dumps(i.get("pages", []))),
            )
            vocab_json["indicators"].append({"doc_id": doc_id, **i})
        for u in d.get("units", []):
            if isinstance(u, str):
                u = {"literal": u, "quantity": None, "pages": []}
            cur.execute(
                "INSERT INTO vocab_units (doc_id,literal,quantity,pages) VALUES (?,?,?,?)",
                (doc_id, u.get("literal"), u.get("quantity"), json.dumps(u.get("pages", []))),
            )
            vocab_json["units"].append({"doc_id": doc_id, **u})
        for e in d.get("era_formats", []):
            if isinstance(e, str):
                e = {"literal": e, "pages": []}
            cur.execute(
                "INSERT INTO vocab_eras (doc_id,literal,pages) VALUES (?,?,?)",
                (doc_id, e.get("literal"), json.dumps(e.get("pages", []))),
            )
            vocab_json["eras"].append({"doc_id": doc_id, **e})
        for n in d.get("notes", []):
            cur.execute(
                "INSERT INTO notes (note_id,doc_id,table_ids,kind,text,page,blocks_timeseries,reason) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (n.get("note_id"), doc_id, json.dumps(n.get("table_ids", [])), n.get("kind"),
                 n.get("text"), n.get("page"), int(bool(n.get("blocks_timeseries"))), n.get("reason")),
            )
            n_notes += 1
            if n.get("blocks_timeseries"):
                n_blocks += 1

    con.commit()
    con.close()

    with open(VOCAB_DIR / "vocab.json", "w", encoding="utf-8") as f:
        json.dump(vocab_json, f, ensure_ascii=False, indent=2)

    print(f"docs merged: {len(docs)}")
    print(f"areas={len(vocab_json['areas'])} indicators={len(vocab_json['indicators'])} "
          f"units={len(vocab_json['units'])} eras={len(vocab_json['eras'])}")
    print(f"notes inserted={n_notes} (blocks_timeseries=true: {n_blocks})")


if __name__ == "__main__":
    main()
