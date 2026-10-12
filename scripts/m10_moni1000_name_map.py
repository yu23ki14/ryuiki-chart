#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""モニ1000 神奈川県 5 出典の和名（と学名）→ registry の taxon の対応表を作る下書きツール。

設計: docs/plans/MONI1000.md §2.5・§8。出力 CSV（registry/taxon/moni1000_name_map.csv）をコミットする。
m10_moni1000.py は registry に問い合わせず、この CSV だけを読む（r01 が原本を読む前に m スクリプトが走るため循環になる）。

入力:  5 出典の CSV（m10_moni1000.normalize_all）/ data/db/registry.sqlite（taxon を**読み取り専用**で引く）
       registry/taxon/moni1000_name_map.csv（既存。basis=curated の行は人が決めたものなので保持する）
出力:  registry/taxon/moni1000_name_map.csv
  列: source_id, name_key, species_ja, scientific_name, taxon_id, basis, note
  name_key は m10_moni1000.name_key()（学名のある出典〔forest_bird・coast_shorebird〕は「和名|学名」、他は和名）。

basis（上から順に判定。1 つのキーは 1 つの taxon にしか行かない）:
  exclude:non_wild      ヒト・ネコ・ウコッケイ・ニワトリ（家畜・家禽・人）
  exclude:non_species   科・類・同定不能・sp.・空 等（種に決められない語）
  sci                   学名の canonical_binomial が registry の rank=species に 1 件に決まる
                        （複数なら status=accepted かつ accepted_taxon_id NULL → さらに和名が一致するもの、の順に絞る）
  ja_unique             和名が rank=species の vernacular_name_ja に 1 件に決まる（複数なら下の絞り込み）。
                        学名のある行は学名が先（和名側が別の taxon でも学名を採り、note に残す）
  ja_paired_sci         学名で決まった別の語（学名のある出典）と和名が同じで、その和名が 1 つの taxon にしか行かない
                        ときに、和名だけの語〔里地の鳥・チョウ・哺乳類、学名の古い表記〕をそこへ寄せる
  （絞り込み）出典の分類群〔鳥=Aves・チョウ=Lepidoptera・哺乳類=Mammalia〕→ accepted かつ accepted_taxon_id NULL →
              GBIF 由来の taxon（iNaturalist 由来の同名重複を除く）→ 和名が一致するもの。各段で 0 件になる絞りは使わない
  curated               人が決めた（複数候補を人が 1 件にしたもの。note に理由）。再実行しても保持する
  exclude:unresolved_taxon  registry に和名も学名も無い
  pending:ambiguous     複数候補が残った（機械で黙って選ばない。note に候補）。決まるまで occurrence に流さない

実行: python3 -I scripts/m10_moni1000_name_map.py [--check]
  --check は CSV を書かず、いまの CSV が下書きと同じか（curated を除く）だけ確かめる。
"""
from __future__ import annotations

import argparse
import collections
import csv
import pathlib
import re
import sqlite3
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import m10_moni1000 as m10  # noqa: E402

ROOT = m10.ROOT
DEFAULT_REGISTRY = ROOT / "data" / "db" / "registry.sqlite"
FIELDS = ["source_id", "name_key", "species_ja", "scientific_name", "taxon_id", "basis", "note"]

NON_WILD = {"ヒト", "ネコ", "ウコッケイ", "ニワトリ"}
NON_SPECIES_EXACT = {"不明", "未調査", "記録無し", m10.UNRESOLVED_NAME}
NON_SPECIES_RE = re.compile(r"(科|類)$|^sp\.?\d*$|同定不能|・")


def clean_ja(ja):
    """照合用の和名: 同定の不確かさを表す末尾の ?/？ を外す。"""
    return re.sub(r"[?？]+$", "", ja).strip()


# 出典ごとの分類群の絞り込み（和名の同音異義〔ホトトギス＝鳥・草・貝 など〕を機械で外す）
SOURCE_GROUP = {
    "moni1000_satochi_bird": ("class", "Aves"), "moni1000_forest_bird": ("class", "Aves"),
    "moni1000_coast_shorebird": ("class", "Aves"), "moni1000_satochi_butterfly": ("order", "Lepidoptera"),
    "moni1000_satochi_mammal": ("class", "Mammalia"),
}


def load_taxa(registry_path):
    """rank=species の taxon を学名・和名で引けるようにする（読み取り専用）。"""
    con = sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    by_sci, by_ja = collections.defaultdict(list), collections.defaultdict(list)
    for tid, canon, sci, ja, status, acc, cls, order in con.execute(
            "SELECT taxon_id, canonical_binomial, scientific_name, vernacular_name_ja, status, accepted_taxon_id, "
            "class, \"order\" FROM taxon WHERE rank='species'"):
        t = {"taxon_id": tid, "sci": sci, "status": status, "accepted_taxon_id": acc, "ja": ja,
             "class": cls, "order": order}
        if canon:
            by_sci[canon].append(t)
        if ja:
            by_ja[unicodedata.normalize("NFKC", ja)].append(t)
    con.close()
    return by_sci, by_ja


def is_primary(t):
    return t["status"] == "accepted" and t["accepted_taxon_id"] is None


def in_group(source_id, t):
    col, val = SOURCE_GROUP[source_id]
    return t[col] == val


def narrow(cands, ja=None):
    """複数候補を機械の規則で絞る（各段で 0 件になる絞りは使わない）:
    accepted かつ accepted_taxon_id NULL → GBIF の taxon（iNaturalist 由来の同名重複を除く）→ 和名が一致するもの。"""
    steps = [is_primary, lambda t: t["taxon_id"].startswith("common:taxon:gbif.")]
    if ja:
        steps.append(lambda t: bool(t["ja"]) and unicodedata.normalize("NFKC", t["ja"]) == ja)
    for f in steps:
        if len(cands) > 1:
            kept = [t for t in cands if f(t)]
            if kept:
                cands = kept
    return cands


def describe(cands):
    return "; ".join(f"{t['taxon_id']} ({t['sci']}, {t['status']}"
                     + (f", acc={t['accepted_taxon_id']}" if t["accepted_taxon_id"] else "") + ")" for t in cands)


def decide(source_id, ja, sci, by_sci, by_ja):
    """1 回目の判定。(taxon_id, basis, note, ja の候補〔照合用〕) を返す。"""
    core = clean_ja(ja)
    if core in NON_WILD:
        return "", "exclude:non_wild", "家畜・家禽・人", []
    if core in NON_SPECIES_EXACT or NON_SPECIES_RE.search(core):
        return "", "exclude:non_species", "種に決められない語（科・類・同定不能・sp. 等）", []
    ja_n = unicodedata.normalize("NFKC", core)
    ja_c = narrow([t for t in by_ja.get(ja_n, []) if in_group(source_id, t)])
    sci_c = narrow([t for t in by_sci.get(sci, []) if in_group(source_id, t)], ja_n) if sci else []
    if len(sci_c) == 1:
        note = sci_c[0]["sci"]
        if len(ja_c) == 1 and ja_c[0]["taxon_id"] != sci_c[0]["taxon_id"]:
            note += f" / registry の和名側は別の taxon（{ja_c[0]['taxon_id']} {ja_c[0]['sci']}）。学名を採る"
        return sci_c[0]["taxon_id"], "sci", note, ja_c
    if len(sci_c) > 1:
        return "", "pending:ambiguous", f"学名の候補: {describe(sci_c)}", ja_c
    if len(ja_c) == 1:
        return ja_c[0]["taxon_id"], "ja_unique", ja_c[0]["sci"] + (" / 学名は registry に無い" if sci else ""), ja_c
    if len(ja_c) > 1:
        return "", "pending:ambiguous", f"和名の候補: {describe(ja_c)}", ja_c
    return "", "exclude:unresolved_taxon", "registry に和名も学名も無い", ja_c


def build(csv_dir, registry_path, existing):
    by_sci, by_ja = load_taxa(registry_path)
    by_source = m10.normalize_all(csv_dir)
    counts, first = collections.Counter(), {}
    for sid, recs in by_source.items():
        for r in recs:
            k = r["_name_key"]
            counts[(sid, k)] += 1
            if (sid, k) not in first:
                ja = r["species_ja"] or m10.UNRESOLVED_NAME
                sci = m10.clean_sci(r["scientific_name"])
                first[(sid, k)] = (ja, sci) + decide(sid, unicodedata.normalize("NFKC", ja), sci, by_sci, by_ja)
    # 2 回目: 学名で決まった語から「和名 → taxon」を引き、学名の無い出典の和名の残りを補う（同じ和名が 1 つの taxon にしか
    # 行かないときだけ。学名の表記ゆれで複数に行く和名は補わない）
    paired = collections.defaultdict(set)
    for (sid, k), (ja, sci, tid, basis, note, ja_c) in first.items():
        if basis == "sci":
            paired[clean_ja(unicodedata.normalize("NFKC", ja))].add(tid)
    rows = []
    for (sid, k), (ja, sci, tid, basis, note, ja_c) in first.items():
        old = existing.get((sid, k))
        if old and old["basis"] == "curated":
            rows.append(old)
            continue
        if basis in ("exclude:unresolved_taxon", "pending:ambiguous") and not note.startswith("学名の候補"):
            ids = paired.get(clean_ja(unicodedata.normalize("NFKC", ja)), set())
            if ja_c:
                ids = ids & {t["taxon_id"] for t in ja_c}
            if len(ids) == 1:
                tid, basis = next(iter(ids)), "ja_paired_sci"
                note = "同じ和名に学名で決まった別の行がある（学名の出典の語から）"
        rows.append({"source_id": sid, "name_key": k, "species_ja": ja, "scientific_name": sci or "",
                     "taxon_id": tid, "basis": basis, "note": note})
    rows.sort(key=lambda r: (list(m10.SOURCES).index(r["source_id"]), r["name_key"]))
    stale = [k for k, v in existing.items() if v["basis"] == "curated" and k not in counts]
    return rows, counts, stale


def report(rows, counts):
    by_basis = collections.Counter(r["basis"] for r in rows)
    print("basis 別の語数:", dict(by_basis))
    print("basis 別の行数:", dict(collections.Counter(
        {b: sum(counts[(r["source_id"], r["name_key"])] for r in rows if r["basis"] == b) for b in by_basis})))
    print("\n== 1 件に決まらなかった語（pending）==")
    for r in rows:
        if r["basis"].startswith("pending"):
            print(f"  {r['source_id']} {r['name_key']!r} ({counts[(r['source_id'], r['name_key'])]} 行) {r['basis']}: {r['note']}")
    print("\n== 名寄せできなかった語（exclude:unresolved_taxon）==")
    un = sorted((r for r in rows if r["basis"] == "exclude:unresolved_taxon"),
                key=lambda r: -counts[(r["source_id"], r["name_key"])])
    print(f"  総数 {len(un)} 語")
    for r in un[:30]:
        print(f"  {r['source_id']} {r['name_key']!r} ({counts[(r['source_id'], r['name_key'])]} 行)")
    # 同じ和名が複数の taxon に行くもの（学名の表記ゆれ・分類の更新）
    multi = collections.defaultdict(set)
    for r in rows:
        if r["taxon_id"]:
            multi[(r["source_id"], r["species_ja"])].add(r["taxon_id"])
    print("\n== 同じ和名が複数の taxon に行く語 ==")
    for (sid, ja), ids in sorted(multi.items()):
        if len(ids) > 1:
            print(f"  {sid} {ja}: {sorted(ids)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv-dir", default=str(m10.DEFAULT_CSV_DIR))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--out", default=str(m10.DEFAULT_NAME_MAP))
    ap.add_argument("--check", action="store_true", help="CSV を書かず、いまの CSV と下書きが同じか（curated 以外）確かめる")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    existing = m10.load_name_map(out) if out.exists() else {}
    rows, counts, stale = build(args.csv_dir, args.registry, existing)
    for k in stale:
        print(f"警告: curated の行が入力に無い（捨てる）: {k}", file=sys.stderr)
    if args.check:
        cur = [{f: r.get(f, "") for f in FIELDS} for r in (existing.values())]
        new = [{f: r.get(f, "") for f in FIELDS} for r in rows]
        key = lambda r: (r["source_id"], r["name_key"])  # noqa: E731
        if sorted(cur, key=key) != sorted(new, key=key):
            raise SystemExit("名寄せ表が下書きと違う（registry か入力が変わった）。作り直して差分を確かめること")
        print("名寄せ表は下書きと同じ")
        return
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print(f"{out}: {len(rows)} 語")
    report(rows, counts)


if __name__ == "__main__":
    main()
