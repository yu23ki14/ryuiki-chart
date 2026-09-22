#!/usr/bin/env python3
"""`occurrence`（`data/db/v2.sqlite`、b06 が作ったファクト）を v1 の `org_norm`
（`web/scripts/build-biota.mjs`）に射影する（ADR-0016 Phase B「ファクトとキューブ」
O-1a。O-1 設計 v2 D3・D4。番号 b07 は O-1b（キューブ）用に空けてある）。

    .venv/bin/python3 scripts/b08_project_occurrence_v1.py

`data/db/v1_projection_occurrence.sqlite`（毎回ゼロから作り直す、専用の出力
ファイル。b05 の `v1_projection.sqlite` とは別ファイル——D3参照）に `org_norm`
1テーブルだけを書く。列名・列順は `reports/derived_baseline.json` の記録と
一致させてある（`scripts/b02_derived_compare.py --candidate ... --tables org_norm`
がそのまま突き合わせられるように）。

## 射影の規則（D3。実データで検証済み——docs/plans/PHASE_B_OCCURRENCE.md 参照）

- `binom`/`cls`/`kdm`/`phy`/`ord`/`family` は **taxon の属性**
  （`occurrence.taxon_id` → `registry.taxon` を引く。taxon_id が NULL なら
  全部 NULL）。v1 の記録ごとの多数決 COALESCE 補完は、taxon レジストリの
  ビルド時（Phase B `phase-b/occurrence-registry`）に taxon 単位へ移してある
  ため、ここでは単純な JOIN で足りる（実データで検証: 816,856行中
  binom/kdm/phy/ord/family は不一致0、cls は Sirosporium celtidis の1件だけ
  宣言済み差分——`scripts/reconcile/expected_diffs.yaml` 参照）。
- `taxon_group` は `COALESCE(taxon.taxon_group, default_label_ja)`
  （`registry/taxon/taxon_group.yaml` の既定ラベルを読む。リテラルを
  書かない。taxon_id が NULL の775行はこの既定に落ちる）。
- `scientific_name`/`vernacular_name`/`taxon_rank`/`red_list_category`/
  `license_class`/`is_alien` は **記録の原表記**（`occurrence` の F6 列。
  `rank_l` だけ `lower(taxon_rank)` で v1 に合わせる）。
- `yr`/`mo` は **`period_raw` から v1 の式をそのまま**適用する
  （`yr=CAST(substr(period_raw,1,4) AS INT)`、`mo` は `length(period_raw)>=7`
  のとき `CAST(substr(period_raw,6,2) AS INT)`。`YYYY/YYYY` 区間では
  この式が「月」ではない値（18/19/20）を返すが、これは v1 の癖でありここで
  直さない——v1 の org_norm と1ビットも変えないための意図的な再現）。
  `period_start`/`period_end`（区間の展開結果）ではなく `period_raw`
  （原表記）を使う点に注意。
- `mlat`/`mlon` は `CAST(FLOOR(lat*100) AS INT)`（v1 と同じ IEEE 演算。
  SQLite の `CAST(FLOOR(...))` を直接使う——Python 側で計算し直さない）。
- 対象は `occurrence.period_raw IS NOT NULL`（v1 org_norm の母集団
  `observed_on IS NOT NULL AND length(observed_on)>=4` と同値——occurrence の
  観測日が NULL でない行は全て length>=4 であることを実測で確認済み）。
  行数は816,856（v1 org_norm と一致）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_TAXON_GROUP_YAML = ROOT / "registry" / "taxon" / "taxon_group.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_occurrence.sqlite"

_ORG_NORM_SQL = """
SELECT
  o.record_id AS record_id,
  o.source_id AS source_id,
  CAST(substr(o.period_raw, 1, 4) AS INT) AS yr,
  CASE WHEN length(o.period_raw) >= 7 THEN CAST(substr(o.period_raw, 6, 2) AS INT) END AS mo,
  t.canonical_binomial AS binom,
  o.scientific_name AS scientific_name,
  o.vernacular_name AS vernacular_name,
  lower(o.taxon_rank) AS rank_l,
  t.class AS cls,
  t.kingdom AS kdm,
  t.phylum AS phy,
  t."order" AS ord,
  t.family AS family,
  o.lat AS lat,
  o.lon AS lon,
  CAST(FLOOR(o.lat * 100) AS INT) AS mlat,
  CAST(FLOOR(o.lon * 100) AS INT) AS mlon,
  o.red_list_category AS red_list_category,
  o.license_class AS license_class,
  o.is_alien AS is_alien,
  COALESCE(t.taxon_group, :default_taxon_group) AS taxon_group
FROM cube.occurrence o
LEFT JOIN reg.taxon t ON t.taxon_id = o.taxon_id
WHERE o.period_raw IS NOT NULL
ORDER BY o.source_row_id
"""

_CREATE_ORG_NORM_SQL = (
    "CREATE TABLE org_norm ("
    "record_id TEXT, source_id TEXT, yr INT, mo INTEGER, binom TEXT, "
    "scientific_name TEXT, vernacular_name TEXT, rank_l TEXT, "
    "cls TEXT, kdm TEXT, phy TEXT, ord TEXT, family TEXT, "
    "lat REAL, lon REAL, mlat INT, mlon INT, "
    "red_list_category TEXT, license_class TEXT, is_alien INTEGER, taxon_group TEXT"
    ")"
)


def _load_default_taxon_group(path=DEFAULT_TAXON_GROUP_YAML) -> str:
    """`registry/taxon/taxon_group.yaml` の `default_label_ja` を読む
    （taxon_id が NULL の行の `taxon_group` に使う。リテラルを書かない）。
    """
    with pathlib.Path(path).open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["default_label_ja"]


def build_org_norm_projection(
    cube_db, registry_db, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
) -> tuple[list[str], list[tuple]]:
    """`(columns, rows)` を返す（ファイルには書かない）。"""
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, cube_db, "cube")
        common.attach_readonly(work, registry_db, "reg")
        cur = work.execute(_ORG_NORM_SQL, {"default_taxon_group": default_taxon_group})
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return columns, rows
    finally:
        work.close()


def write_projection(columns: list[str], rows: list[tuple], out_path) -> None:
    conn = common.fresh_sqlite(out_path)
    try:
        conn.execute(_CREATE_ORG_NORM_SQL)
        placeholders = ", ".join("?" for _ in columns)
        conn.executemany(f'INSERT INTO "org_norm" VALUES ({placeholders})', rows)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube-db", default=str(DEFAULT_CUBE_DB), help="occurrence を持つ v2.sqlite")
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--taxon-group-yaml", default=str(DEFAULT_TAXON_GROUP_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {args.cube_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("org_norm へ射影") as info:
        columns, rows = build_org_norm_projection(args.cube_db, registry_db, args.taxon_group_yaml)
        info["n"] = len(rows)

    with common.timed_step(f"{args.out} に書き出し") as info:
        write_projection(columns, rows, args.out)
        info["n"] = len(rows)

    print(f"  org_norm: {len(rows):,}行")


if __name__ == "__main__":
    main()
