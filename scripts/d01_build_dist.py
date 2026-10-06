#!/usr/bin/env python3
"""v2.sqlite と registry.sqlite から `dist/`（Parquet 配布物＋Frictionless 記述子）を作る
（Issue #40 Phase D 担当 P。ADR-0001 改定）。

入力（どちらも読み取り専用で開く）:
  data/db/v2.sqlite        observation / occurrence / occurrence_place / observation_agg / occurrence_agg
  data/db/registry.sqlite  place ほか（RYUIKI_REGISTRY_DB でも指せる）

出力（`--out`、既定 `dist/`。`.gitignore` 済み）:
  datapackage.json
  observation/source_table=<出典テーブル>/part-0.parquet   （出典単位のパーティション。#39 の observation_id・source_edition_id 込み）
  occurrence/source_id=<出典>/part-0.parquet
  occurrence_place.parquet  observation_agg.parquet  occurrence_agg.parquet
  registry/<表>.parquet

増分: 各リソースに「入力指紋」（書き出し仕様＋スキーマ＋入力行集合のダイジェスト）を記録し、
前回の datapackage.json と一致し、ファイルが記録どおり（sha256）なら書き直さない。変わった
出典のパーティションだけが書き直される。消えたパーティションのファイルは削除する。

公開範囲: 出力を絞らない（ADR-0028）。ただし合成データ（`is_synthetic=1` の行・`synthetic_*` の出典）は
v2 に入らない前提で、入っていたら黙って除かず**落とす**。registry 側の `synthetic_*` 出典の行だけは
配布物に入れない（出典の宣言であってデータではないため。除いた件数を記録する）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import urllib.parse

import pyarrow as pa

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dist import datapackage as dp  # noqa: E402
from dist import writer as w  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (表, パーティション列, 並び順)。並び順は主キー（公開 ID）。パーティション列はファイルから落とす。
L2_TABLES = (
    ("observation", "source_table", ("observation_id",)),
    ("occurrence", "source_id", ("occurrence_id",)),
)
# 単一ファイル（並び順は全列）。キューブ・occurrence_place は主キーが無いので全列で並べる
# （同一内容の行は区別できないので決定的）。
V2_SINGLE_TABLES = ("occurrence_place", "observation_agg", "occurrence_agg")
REGISTRY_TABLES = (
    "region", "place", "place_relation", "place_source_ref", "taxon", "taxon_assessment",
    "variable", "variable_alias", "unit", "source", "source_edition", "license", "caveat", "caveat_scope",
)
_LIKE_SYNTHETIC = dp.SYNTHETIC_SOURCE_PREFIX.replace("_", "!_") + "%"  # ESCAPE '!'
_NOT_SYNTHETIC = f"(source_id IS NULL OR source_id NOT LIKE '{_LIKE_SYNTHETIC}' ESCAPE '!')"


def _open_ro(path: pathlib.Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"入力が無い: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _schema_sig(columns) -> str:
    return ",".join(f"{c.name}:{c.decl}:{int(c.not_null)}" for c in columns)


def _part_dir_name(column: str, value: str) -> str:
    return f"{column}={urllib.parse.quote(value, safe='')}"


def preflight_no_synthetic(v2: sqlite3.Connection, reg: sqlite3.Connection) -> None:
    """合成データが v2 に居たら止める（黙って除外すると、b03/b06 の除外が壊れたことに気づけない）。

    出典は **`source_edition_id` → registry の `source_edition.source_id`** で判定する（observation の `source_table` は
    出典ではなく原本の表名〔measurements 等〕なので、そこを見ても合成の出典は見つからない）。occurrence は `source_id` 列も見る。
    """
    n = v2.execute("SELECT COUNT(*) FROM observation WHERE is_synthetic IS NOT NULL AND is_synthetic <> 0").fetchone()[0]
    if n:
        raise SystemExit(f"v2.observation に is_synthetic<>0 の行が {n} 件ある。合成データは配布物に出さない（b03 の除外を確認）")
    source_of_edition = dict(reg.execute("SELECT edition_id, source_id FROM source_edition"))
    for table in ("observation", "occurrence"):
        synthetic_editions = [
            eid for (eid,) in v2.execute(f"SELECT DISTINCT source_edition_id FROM {table} WHERE source_edition_id IS NOT NULL")
            if str(source_of_edition.get(eid, "")).startswith(dp.SYNTHETIC_SOURCE_PREFIX)
        ]
        if synthetic_editions:
            raise SystemExit(
                f"v2.{table} が {dp.SYNTHETIC_SOURCE_PREFIX}* の出典の版を参照している: {synthetic_editions}。合成データは配布物に出さない"
            )
    n = v2.execute("SELECT COUNT(*) FROM occurrence WHERE source_id LIKE ? ESCAPE '!'", (_LIKE_SYNTHETIC,)).fetchone()[0]
    if n:
        raise SystemExit(f"v2.occurrence に {dp.SYNTHETIC_SOURCE_PREFIX}* の出典の行が {n} 件ある。合成データは配布物に出さない")


def _v2_built_from(v2: sqlite3.Connection) -> dict:
    """v2 の自己指紋（pipeline_fingerprint）。表ごとの指紋と spec_version をそのまま写す。"""
    names = {r[0] for r in v2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "pipeline_fingerprint" not in names:
        return {}
    cols = [r[1] for r in v2.execute("PRAGMA table_info(pipeline_fingerprint)")]
    rows = v2.execute("SELECT * FROM pipeline_fingerprint").fetchall()
    return {"pipeline_fingerprint": sorted((dict(zip(cols, r)) for r in rows), key=lambda d: json.dumps(d, sort_keys=True))}


def _registry_built_from(reg: sqlite3.Connection) -> dict:
    r = reg.execute("SELECT input_fingerprint, mode FROM registry_build").fetchone()
    return {"input_fingerprint": r[0], "mode": r[1]} if r else {}


class Builder:
    def __init__(self, out: pathlib.Path, previous: dict | None, *, verbose: bool):
        self.out = out
        self.prev = {r["path"]: r for r in (previous or {}).get("resources", [])}
        self.resources: list[dict] = []
        self.written = 0
        self.skipped = 0
        self.verbose = verbose

    def emit(self, conn, *, table: str, rel_dir: str, order_by, partition_by: str | None, name_table: str,
             where: str = "", params=(), extra: dict | None = None) -> None:
        columns = w.table_columns(conn, table)
        file_columns = [c for c in columns if c.name != partition_by]
        for g in w.iter_groups(conn, table, order_by=order_by, partition_by=partition_by, where=where, params=params):
            if partition_by:
                rel = f"{rel_dir}/{_part_dir_name(partition_by, g.key)}/part-0.parquet"
                name = dp.resource_name(name_table, g.key)
                partition = {"column": partition_by, "value": g.key}
            else:
                rel = f"{rel_dir}.parquet" if rel_dir else f"{table}.parquet"
                name = dp.resource_name(name_table)
                partition = None
            fp = _fingerprint(dp.SPEC_VERSION, w.WRITER_SPEC, _schema_sig(file_columns), str(g.rows), g.digest.hexdigest)
            path = self.out / rel
            old = self.prev.get(rel)
            if old and old.get("input_fingerprint") == fp and path.exists() and w.sha256_file(path) == old["sha256"]:
                entry = old
                self.skipped += 1
                state = "skip"
            else:
                g.write(path)
                entry = {
                    "name": name,
                    "path": rel,
                    "format": "parquet",
                    "mediatype": dp.PARQUET_MEDIATYPE,
                    "bytes": path.stat().st_size,
                    "sha256": w.sha256_file(path),
                    "rows": g.rows,
                    "rows_sha256": g.digest.hexdigest,
                    "input_fingerprint": fp,
                    "order_by": list(order_by) if len(order_by) < len(columns) else "all_columns",
                    "schema": {"fields": [c.table_schema_field for c in file_columns]},
                }
                if partition:
                    entry["partition"] = partition
                if extra:
                    entry.update(extra)
                self.written += 1
                state = "write"
            self.resources.append(entry)
            if self.verbose:
                print(f"  [{state}] {rel} ({g.rows} 行)")


def _edition_rows(v2: sqlite3.Connection) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for table in ("observation", "occurrence"):
        for eid, n in v2.execute(f"SELECT COALESCE(source_edition_id, ''), COUNT(*) FROM {table} GROUP BY 1"):
            out.setdefault(eid, {})[table] = n
    return out


def build_dist(v2_db: pathlib.Path, registry_db: pathlib.Path, out: pathlib.Path, *, verbose: bool = False) -> tuple[dict, dict]:
    v2 = _open_ro(v2_db)
    reg = _open_ro(registry_db)
    try:
        preflight_no_synthetic(v2, reg)
        out.mkdir(parents=True, exist_ok=True)
        previous = dp.load(out / "datapackage.json")
        b = Builder(out, previous, verbose=verbose)

        for table, part, order in L2_TABLES:
            b.emit(v2, table=table, rel_dir=table, order_by=order, partition_by=part, name_table=table)
        for table in V2_SINGLE_TABLES:
            cols = tuple(c.name for c in w.table_columns(v2, table))
            b.emit(v2, table=table, rel_dir=table, order_by=cols, partition_by=None, name_table=table)

        excluded_registry: dict[str, int] = {}
        for table in REGISTRY_TABLES:
            cols = w.table_columns(reg, table)
            names = tuple(c.name for c in cols)
            where = _NOT_SYNTHETIC if "source_id" in names else ""
            if where:
                total = reg.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                kept = reg.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where}').fetchone()[0]
                if total != kept:
                    excluded_registry[table] = total - kept
            b.emit(reg, table=table, rel_dir=f"registry/{table}", order_by=names, partition_by=None,
                   name_table=f"registry.{table}", where=where)

        sources, license_summary = dp.collect_sources(reg, _edition_rows(v2))
        license_summary["registry_synthetic_rows_excluded"] = dict(sorted(excluded_registry.items()))
        built_from = {"v2": _v2_built_from(v2), "registry": _registry_built_from(reg)}
        doc = dp.build(resources=b.resources, sources=sources, license_summary=license_summary,
                       built_from=built_from, writer_spec=w.WRITER_SPEC)
    finally:
        v2.close()
        reg.close()

    # 消えたパーティション・リソースのファイルを掃除（datapackage.json に載らない .parquet を残さない）
    wanted = {r["path"] for r in b.resources}
    removed = 0
    for p in sorted(out.rglob("*.parquet*")):
        if p.relative_to(out).as_posix() not in wanted:
            p.unlink()
            removed += 1
    for d in sorted((p for p in out.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    (out / "datapackage.json").write_text(dp.dumps(doc), encoding="utf-8")
    readme_src = ROOT / "scripts" / "dist" / "README.dist.md"
    if readme_src.exists():
        shutil.copyfile(readme_src, out / "README.md")
    stats = {"written": b.written, "skipped": b.skipped, "removed": removed}
    print(f"dist: {len(b.resources)} リソース（書き込み {b.written}・据え置き {b.skipped}・削除 {removed}）"
          f" / 出典の版 {len(sources)} / 合計 {sum(r['bytes'] for r in b.resources) / 1e6:.1f} MB → {out}")
    return doc, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--v2-db", type=pathlib.Path, default=ROOT / "data" / "db" / "v2.sqlite")
    ap.add_argument("--registry-db", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("RYUIKI_REGISTRY_DB") or ROOT / "data" / "db" / "registry.sqlite"))
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "dist")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    build_dist(a.v2_db, a.registry_db, a.out, verbose=a.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
