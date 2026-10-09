#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳 sites.zone を zone v2（地形指標による共通の定義）で更新する（docs/plans/AMAMI_STEP0.md §3）。

入力:
  data/processed/terrain_points.csv   （c68。座標ごとの標高・起伏量・最低点・海岸距離）
  registry/place/zone.yaml            （rule: の閾値。terrain: の指紋が csv の params_digest と合うこと）
  registry/region.yaml                （terrain.summit。csv の summit_m と合うこと）

やること:
- 対象は sites のうち elevation_m IS NOT NULL の行。座標が csv に無ければ地点を列挙して止める。
- 書き換える前に、対象の全地点の旧→新の一覧 reports/zone_v2_migration.csv を書く
  （宣言済みの差分。コミットする）。zone_v1 は、csv が既にあればその値を保持する
  （2回目の実行で v2 を v1 と取り違えない）。無ければ現在の sites.zone。
- 冪等: 同じ入力で2回回しても csv も原本も変わらない。
- --dry-run: 原本も csv も書かず、旧→新のクロス表と変更地点を標準出力に出す。
- --report: クロス表を Markdown で出す。
- m01 を再実行したら（INSERT OR REPLACE で zone が NULL に戻る）続けて回す。順序: c36 → c68 → m01 → m09 → r01。
- 原本 data/db/ryuiki.sqlite に書くのはメインだけ。確認は --dry-run か、一時コピーの DB を --db で。
  --db が既定（原本）でないときは --migration-csv の明示が必須（既定の reports/zone_v2_migration.csv
  〔コミットされる宣言〕を一時コピーの試行で上書きしない）。
- 標高は DEM の値、DEM が無効（海の画素）なら台帳の sites.elevation_m（zone_rule.classify）。
  理由コードは classify() が返す（ここで判定を二重に持たない）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from registry import zone_rule  # noqa: E402

DEFAULT_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REPORT_CSV = ROOT / "reports" / "zone_v2_migration.csv"

CSV_COLUMNS = ("site_id", "zone_v1", "zone_v2", "elevation_m", "relief_wide_m", "relief_near_m",
               "coast_dist_m", "floor_min_m", "reason")


class M09Error(RuntimeError):
    pass


def migration_reason(v1, v2, reason) -> str:
    """旧→新の理由コード。v1 == v2 なら unchanged、それ以外は classify() の reason。"""
    return "unchanged" if v1 == v2 else reason


def _fmt(v) -> str:
    """csv の数値（整数なら小数点なし。丸めは6桁で、再実行で同じ文字列になる）。"""
    if v is None:
        return ""
    v = round(float(v), 6)
    return str(int(v)) if v == int(v) else repr(v)


def read_previous_v1(path: pathlib.Path) -> dict[str, str]:
    """既存の移行 csv の zone_v1 を site_id で返す（無ければ空）。"""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != CSV_COLUMNS:
            raise M09Error(f"{path}: 列が {CSV_COLUMNS} と一致しない: {reader.fieldnames}")
        return {r["site_id"]: r["zone_v1"] for r in reader}


def plan(conn: sqlite3.Connection, points, rule, prev_v1: dict[str, str]):
    """`[(row_dict, v1, v2, point, reason)]`（対象の地点だけ。site_id 昇順）。zone を持つが対象外の地点があれば止まる。"""
    try:
        classified = zone_rule.classify_sites_from_db(conn, points, rule)
    except zone_rule.ZoneRuleError as e:
        raise M09Error(str(e)) from e
    out = []
    for c in classified:
        if c.point is None:
            if c.ledger_zone is not None:
                raise M09Error(f"{c.site_id}: elevation_m が無い（zone の対象外）のに sites.zone={c.ledger_zone} が入っている")
            continue
        v1_raw = prev_v1.get(c.site_id)
        v1 = (int(v1_raw) if v1_raw not in (None, "") else None) if c.site_id in prev_v1 else c.ledger_zone
        out.append(({"site_id": c.site_id, "current": c.ledger_zone}, v1, c.zone, c.point, c.reason))
    return out


def write_migration_csv(path: pathlib.Path, items) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(CSV_COLUMNS)
        for row, v1, v2, p, reason in items:
            w.writerow([
                row["site_id"], "" if v1 is None else v1, "" if v2 is None else v2,
                _fmt(p.elevation_m), _fmt(p.relief_wide_m), _fmt(p.relief_near_m),
                _fmt(p.coast_dist_m), _fmt(p.floor_min_m), migration_reason(v1, v2, reason),
            ])


CROSSTAB_AXIS = [1, 2, 3, 4, 5, None]


def crosstab_matrix(items) -> list[list[int]]:
    """旧（行）× 新（列）の件数。軸は CROSSTAB_AXIS（None は「付かない」）。"""
    ct = collections.Counter((it[1], it[2]) for it in items)
    return [[ct.get((r, c), 0) for c in CROSSTAB_AXIS] for r in CROSSTAB_AXIS]


def format_crosstab_text(items) -> str:
    m = crosstab_matrix(items)
    name = lambda c: "なし" if c is None else str(c)  # noqa: E731
    lines = ["旧＼新 " + " ".join(f"{name(c):>5}" for c in CROSSTAB_AXIS)]
    for r, row in zip(CROSSTAB_AXIS, m):
        lines.append(f"{name(r):>5} " + " ".join(f"{n:>5}" for n in row))
    total = sum(map(sum, m))
    same = sum(m[i][i] for i in range(len(CROSSTAB_AXIS)))
    lines.append(f"一致 {same} / 変更 {total - same} / 対象 {total}")
    return "\n".join(lines)


def format_crosstab_markdown(items) -> str:
    m = crosstab_matrix(items)
    name = lambda c: "付かない" if c is None else str(c)  # noqa: E731
    lines = ["| 旧＼新 | " + " | ".join(name(c) for c in CROSSTAB_AXIS) + " |", "|" + "---|" * (len(CROSSTAB_AXIS) + 1)]
    for r, row in zip(CROSSTAB_AXIS, m):
        lines.append(f"| {name(r)} | " + " | ".join(str(n) for n in row) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB, help="更新する ryuiki.sqlite（既定は原本。確認は一時コピーで）")
    ap.add_argument("--terrain", type=pathlib.Path, default=zone_rule.TERRAIN_POINTS_CSV)
    ap.add_argument("--zone-yaml", type=pathlib.Path, default=zone_rule.ZONE_YAML)
    ap.add_argument("--region-yaml", type=pathlib.Path, default=zone_rule.REGION_YAML)
    ap.add_argument("--migration-csv", type=pathlib.Path, default=None,
                    help="宣言済み差分の出力先。既定は reports/zone_v2_migration.csv（--db が原本のときだけ。他の --db では必須）")
    ap.add_argument("--dry-run", action="store_true", help="何も書かず、旧→新のクロス表と変更地点を出す")
    ap.add_argument("--report", action="store_true", help="クロス表を Markdown で出す")
    args = ap.parse_args(argv)
    if args.migration_csv is None:
        if args.db.resolve() != DEFAULT_DB.resolve():
            ap.error("--db が既定（原本）でないときは --migration-csv の明示が必要"
                     "（コミットされる reports/zone_v2_migration.csv を一時コピーの試行で上書きしないため）")
        args.migration_csv = DEFAULT_REPORT_CSV

    try:
        defn = zone_rule.load_zone_definition(args.zone_yaml)
        points = zone_rule.load_terrain_points(
            args.terrain, defn["terrain"], zone_rule.load_region_summits(args.region_yaml))
    except zone_rule.ZoneRuleError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    rule = defn["rule"]

    mode = "ro" if args.dry_run else "rw"
    conn = sqlite3.connect(f"file:{args.db}?mode={mode}", uri=True)
    try:
        items = plan(conn, points, rule, read_previous_v1(args.migration_csv))
    except (M09Error, zone_rule.ZoneRuleError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.dry_run or args.report:
        print(format_crosstab_markdown(items) if args.report else format_crosstab_text(items))
    if args.dry_run:
        for row, v1, v2, _p, reason in items:
            if v1 != v2:
                print(f"  {row['site_id']}: {v1} -> {v2} ({migration_reason(v1, v2, reason)})")
        conn.close()
        return 0

    # 書き換える前に宣言済みの差分を書く（zone_v1 は既存 csv の値を保持）。
    write_migration_csv(args.migration_csv, items)
    changed = 0
    with conn:
        # 対象外（elevation_m が無い）地点は plan() が zone=NULL であることを確かめ済み。
        for row, _v1, v2, _p, _r in items:
            if row["current"] != v2:
                conn.execute("UPDATE sites SET zone = ? WHERE site_id = ?", (v2, row["site_id"]))
                changed += 1
    conn.close()
    print(f"m09: 対象 {len(items)} 地点、sites.zone を {changed} 件更新。{args.migration_csv} を書いた。")
    print(format_crosstab_text(items))
    print("次: cd web && pnpm run build:registry（原本の sites.zone は指紋に入らないので明示する）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
