"""`dist/` の機械検査（設計書 D6 の不変条件 1〜4＋配布物の整合）。

`check_dist()` は違反のメッセージのリストを返す（空なら合格）。`scripts/d02_check_dist.py` が CLI、
`scripts/tests/test_dist.py` が「わざと壊すと止まる」ことを固定する。

  不変条件 1  合成データが出ない（行・出典・datapackage.json の sources のどれにも）
  不変条件 2  座標が v2 と1ビットも違わない（lat/lon/coordinate_uncertainty_m の行集合ダイジェスト）
  不変条件 3  旗は出力を絞らない（redistributable=0 の出典の行も v2 と同数ある。全リソースが v2 と行集合で一致）
  不変条件 4  旗の忠実性（sources[] の license_id/license_class/redistributable/attribution が registry と一致。
              写像漏れ・未確認の件数が datapackage.json の集計と registry で一致＝黙って埋めていない）
  整合        datapackage.json の bytes/sha256/rows/rows_sha256 がファイルと一致・載っていない Parquet が無い
"""
from __future__ import annotations

import pathlib
import sqlite3
from typing import Iterator

import pyarrow.parquet as pq

from . import datapackage as dp
from . import writer as w

L2_PARTITIONED = {"observation": "source_table", "occurrence": "source_id"}
V2_SINGLE = ("occurrence_place", "observation_agg", "occurrence_agg")
COORD_COLUMNS = ("lat", "lon", "coordinate_uncertainty_m")


def _open_ro(path: pathlib.Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _parquet_rows(path: pathlib.Path, columns: list[str] | None = None) -> Iterator[tuple]:
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=50000, columns=columns):
        cols = [c.to_pylist() for c in batch.columns]
        yield from zip(*cols)


def _parquet_digest(path: pathlib.Path, columns: list[str] | None = None) -> w.Digest:
    d = w.Digest()
    for r in _parquet_rows(path, columns):
        d.add(r)
    return d


def _sqlite_digests(conn: sqlite3.Connection, table: str, partition_by: str | None, columns: list[str] | None = None,
                    where: str = "") -> dict:
    """{パーティション値(または None): Digest}。1回の全走査（出典列に索引が無いので値ごとに引かない）。"""
    cols = w.table_columns(conn, table)
    names = [c.name for c in cols if c.name != partition_by]
    if columns is not None:
        names = columns
    sel = ", ".join(f'"{n}"' for n in names)
    if partition_by:
        sel = f'"{partition_by}", {sel}'
    sql = f'SELECT {sel} FROM "{table}"' + (f" WHERE {where}" if where else "")
    out: dict = {}
    off = 1 if partition_by else 0
    for row in conn.execute(sql):
        key = row[0] if partition_by else None
        d = out.get(key)
        if d is None:
            d = out[key] = w.Digest()
        d.add(tuple(row[off:]))
    return out


def _is_synthetic_source(source_id) -> bool:
    return isinstance(source_id, str) and source_id.startswith(dp.SYNTHETIC_SOURCE_PREFIX)


def check_dist(dist_dir: pathlib.Path, v2_db: pathlib.Path, registry_db: pathlib.Path) -> list[str]:
    errors: list[str] = []
    doc = dp.load(dist_dir / "datapackage.json")
    if doc is None:
        return [f"{dist_dir}/datapackage.json が無い"]
    resources = doc.get("resources", [])
    by_path = {r["path"]: r for r in resources}
    readable: set[str] = set()  # 存在し Parquet として開けたリソース（以降の検査はこれだけ読む）

    # ---- 整合: ファイルと記述子 ----
    on_disk = {p.relative_to(dist_dir).as_posix() for p in dist_dir.rglob("*.parquet*")}
    for extra in sorted(on_disk - set(by_path)):
        errors.append(f"[整合] datapackage.json に載っていないファイルがある: {extra}")
    for r in resources:
        p = dist_dir / r["path"]
        if not p.exists():
            errors.append(f"[整合] ファイルが無い: {r['path']}")
            continue
        if p.stat().st_size != r["bytes"] or w.sha256_file(p) != r["sha256"]:
            errors.append(f"[整合] bytes/sha256 が記述子と違う: {r['path']}")
        try:
            n = pq.ParquetFile(p).metadata.num_rows
        except Exception as e:  # 壊れたファイルでも検査を最後まで回して違反として報告する
            errors.append(f"[整合] Parquet として読めない: {r['path']}（{type(e).__name__}）")
            continue
        if n != r["rows"]:
            errors.append(f"[整合] 行数が記述子と違う: {r['path']}")
        readable.add(r["path"])

    v2 = _open_ro(v2_db)
    reg = _open_ro(registry_db)
    try:
        # ---- 不変条件 1: 合成データが出ない ----
        for r in resources:
            part = r.get("partition") or {}
            if _is_synthetic_source(part.get("value")) or dp.SYNTHETIC_SOURCE_PREFIX in r["path"]:
                errors.append(f"[1 合成] 合成データの出典のリソースがある: {r['path']}")
        for s in doc.get("sources", []):
            if _is_synthetic_source(s.get("source_id")):
                errors.append(f"[1 合成] datapackage.json の sources に合成データの出典がある: {s['source_id']}")
        for r in resources:
            if r["name"].split(".")[0] == "observation" and r["path"] in readable:
                names = [f["name"] for f in r["schema"]["fields"]]
                if "is_synthetic" in names:
                    col = pq.read_table(dist_dir / r["path"], columns=["is_synthetic"]).column(0).to_pylist()
                    bad = sum(1 for v in col if v not in (None, 0))
                    if bad:
                        errors.append(f"[1 合成] {r['path']} に is_synthetic<>0 の行が {bad} 件ある")
        for table in ("source", "source_edition", "variable_alias", "taxon_assessment"):
            path = dist_dir / "registry" / f"{table}.parquet"
            if f"registry/{table}.parquet" in readable and "source_id" in pq.ParquetFile(path).schema_arrow.names:
                for sid in set(pq.read_table(path, columns=["source_id"]).column(0).to_pylist()):
                    if _is_synthetic_source(sid):
                        errors.append(f"[1 合成] registry/{table}.parquet に合成データの出典 {sid} の行がある")

        # ---- 不変条件 2・3: v2 と行集合が一致（座標は別に取り出して明示） ----
        for table, part_col in L2_PARTITIONED.items():
            expect = _sqlite_digests(v2, table, part_col)
            coord = _sqlite_digests(v2, table, part_col, list(COORD_COLUMNS)) if table == "occurrence" else {}
            got_parts = {}
            for r in resources:
                if r["name"].split(".")[0] != table or "partition" not in r or not r["path"] in readable:
                    continue
                got_parts[r["partition"]["value"]] = r
            for key in sorted(set(expect) - set(got_parts)):
                errors.append(f"[3 絞らない] v2.{table} の {part_col}={key!r}（{expect[key].n} 行）が dist に無い")
            for key in sorted(set(got_parts) - set(expect)):
                errors.append(f"[3 絞らない] dist.{table} に v2 に無い {part_col}={key!r} がある")
            for key in sorted(set(expect) & set(got_parts)):
                path = dist_dir / got_parts[key]["path"]
                got = _parquet_digest(path)
                e = expect[key]
                if got.n != e.n:
                    errors.append(f"[3 絞らない] {table}/{part_col}={key}: 行数が v2 {e.n} と dist {got.n} で違う")
                elif got.hexdigest != e.hexdigest:
                    errors.append(f"[3 値] {table}/{part_col}={key}: 行集合が v2 と一致しない（値が変わっている）")
                if coord:
                    cg = _parquet_digest(path, list(COORD_COLUMNS))
                    ce = coord[key]
                    if (cg.n, cg.hexdigest) != (ce.n, ce.hexdigest):
                        errors.append(f"[2 座標] occurrence/{part_col}={key}: lat/lon/coordinate_uncertainty_m が v2 と1ビット違う")
        for table in V2_SINGLE:
            r = by_path.get(f"{table}.parquet")
            if r is None:
                errors.append(f"[3 絞らない] {table}.parquet が dist に無い")
                continue
            if r["path"] not in readable:
                continue  # 読めないことは整合の節で報告済み
            expect = _sqlite_digests(v2, table, None).get(None) or w.Digest()
            got = _parquet_digest(dist_dir / r["path"])
            if (got.n, got.hexdigest) != (expect.n, expect.hexdigest):
                errors.append(f"[3 絞らない] {table}: v2（{expect.n} 行）と dist（{got.n} 行）が一致しない")

        # ---- 不変条件 3 の続き: 版ごとの件数（redistributable=0 の出典の行も v2 と同数） ----
        v2_counts: dict[str, dict[str, int]] = {}
        dist_counts: dict[str, dict[str, int]] = {}
        for table in L2_PARTITIONED:
            for eid, n in v2.execute(f"SELECT COALESCE(source_edition_id, ''), COUNT(*) FROM {table} GROUP BY 1"):
                v2_counts.setdefault(eid, {})[table] = n
            for r in resources:
                if r["name"].split(".")[0] != table or not r["path"] in readable:
                    continue
                for eid in pq.read_table(dist_dir / r["path"], columns=["source_edition_id"]).column(0).to_pylist():
                    dist_counts.setdefault(eid or "", {}).setdefault(table, 0)
                    dist_counts[eid or ""][table] += 1
        if v2_counts != dist_counts:
            errors.append("[3 絞らない] 版（source_edition_id）ごとの行数が v2 と dist で一致しない")

        # ---- 不変条件 4: 旗の忠実性 ----
        sources = {s["source_edition_id"]: s for s in doc.get("sources", [])}
        referenced = {e for e in v2_counts if e}
        if set(sources) != referenced:
            errors.append(
                f"[4 旗] sources[] の版が L2 が参照する版と違う（不足 {sorted(referenced - set(sources))[:3]}、"
                f"余分 {sorted(set(sources) - referenced)[:3]}）"
            )
        for eid, s in sorted(sources.items()):
            row = reg.execute(
                "SELECT e.license_id, e.license_class, e.redistributable, l.attribution_text, e.update_mode, e.fetched_at "
                "FROM source_edition e LEFT JOIN license l ON l.license_id = e.license_id WHERE e.edition_id = ?",
                (eid,),
            ).fetchone()
            if row is None:
                errors.append(f"[4 旗] {eid} が registry の source_edition に無い")
                continue
            got = (s.get("license_id"), s.get("license_class"), s.get("redistributable"), s.get("attribution"),
                   s.get("update_mode"), s.get("fetched_at"))
            if got != tuple(row):
                errors.append(f"[4 旗] {eid}: license_id/license_class/redistributable/attribution/update_mode/fetched_at が registry と違う")
        reg_unresolved = {
            c: sorted(e for (e,) in reg.execute("SELECT edition_id FROM source_edition WHERE license_class = ?", (c,))
                      if e in referenced)
            for c in dp.UNRESOLVED_LICENSE_CLASSES
        }
        if doc.get("license_summary", {}).get("unresolved_license_class") != reg_unresolved:
            errors.append("[4 旗] 写像漏れ・未確認（license_class=unknown/unconfirmed）の件数が registry と違う（黙って埋めていないか）")
        # dist/registry の source_edition.parquet も registry と同じ旗か（配布した registry 表の忠実性）
        p = dist_dir / "registry" / "source_edition.parquet"
        if "registry/source_edition.parquet" in readable:
            want = reg.execute(
                "SELECT edition_id, license_id, license_class, redistributable FROM source_edition "
                f"WHERE (source_id IS NULL OR source_id NOT LIKE '{dp.SYNTHETIC_SOURCE_PREFIX.replace('_', '!_')}%' ESCAPE '!')"
            ).fetchall()
            have = list(_parquet_rows(p, ["edition_id", "license_id", "license_class", "redistributable"]))
            if sorted(map(repr, want)) != sorted(map(repr, have)):
                errors.append("[4 旗] dist/registry/source_edition.parquet の旗が registry と違う")
    finally:
        v2.close()
        reg.close()
    return errors
