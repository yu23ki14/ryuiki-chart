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

- `binom`/`rank_l`/`cls`/`kdm`/`phy`/`ord`/`family` は **taxon の属性**
  （`occurrence.taxon_id` → `registry.taxon` を引く。taxon_id が NULL なら
  全部 NULL）。v1 の記録ごとの多数決 COALESCE 補完は、taxon レジストリの
  ビルド時（Phase B `phase-b/occurrence-registry`）に taxon 単位へ移してある
  ため、ここでは単純な JOIN で足りる（実データで検証: 816,856行中
  binom/rank_l/kdm/phy/ord/family は不一致0、cls は Sirosporium celtidis の
  1件だけ宣言済み差分——`scripts/reconcile/expected_diffs.yaml` 参照）。
  `rank_l` は当初「記録の原表記を `lower()` するだけ」で実装していたが、
  `registry.taxon.rank`（taxon 単位、build_taxon.py が組み立て時に既に
  小文字化して持つ）と全行一致することを実測で確認したため、design v2 D3の
  「taxon の属性から取る」という原則どおりに taxon 側へ揃えた
  （コードレビュー指摘15）。
- `taxon_group` は `COALESCE(taxon.taxon_group, default_label_ja)`
  （`registry/taxon/taxon_group.yaml` の既定ラベルを読む。リテラルを
  書かない。taxon_id が NULL の775行はこの既定に落ちる）。
- `scientific_name`/`vernacular_name`/`red_list_category`/`license_class`/
  `is_alien` は **記録の原表記**（`occurrence` の F6 列）。
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

## 古い registry を検出する（コードレビュー指摘7）

`occurrence.taxon_id` は b06 実行時点の `registry.taxon` に実在することを
検証済みだが、`occurrence`（`v2.sqlite`）と `registry.sqlite` は別々に
作り直せるファイルなので、`b08` を古い `registry.sqlite`（taxon が
入れ替わった・減った版）に対して実行すると、`occurrence.taxon_id IS NOT NULL`
なのに `registry.taxon` に無い行が出うる。これを検出せず `LEFT JOIN` の
結果（`NULL`）をそのまま `COALESCE` に流すと、taxon の属性が黙って全部 NULL・
`taxon_group` が既定ラベルに落ちる——taxon が本当に未解決（`taxon_id=NULL`）
なのか、registry が古いだけなのかを区別できなくなる。`build_org_norm_projection`
は書き込みの前にこの食い違いを数えて0でなければ止める。

## 書き込みは1つの `INSERT ... SELECT`（コードレビュー指摘8・10）

以前は `work`（`cube`/`reg` を ATTACH した読み取り専用の一時接続）で
`SELECT` した結果を Python の `list[tuple]` として受け取り（約816,856行×
21列、フル展開すると1GB近く）、別の接続へ位置指定の `INSERT` で
`executemany` していた。列の並びが `CREATE TABLE` と `SELECT`（と
`cur.description` から作る `columns`）の2箇所で一致している前提に依存して
おり、どちらかがずれると値が別の列に入る事故になりうる。

いまは出力ファイルを書き込み用に開いた1つの接続に `cube`/`reg` を ATTACH し、
`INSERT INTO org_norm (<列名を明示>) SELECT ... FROM cube.occurrence ...` を
1文で実行する——SQLite 内部でストリーム処理されるため、Python 側で全行を
リストに保持しない。列の対応も SQL 文の中に列名で明示されているため、
`CREATE TABLE`/`SELECT`/挿入の3箇所がずれる余地が無い。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_TAXON_GROUP_YAML = ROOT / "registry" / "taxon" / "taxon_group.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_occurrence.sqlite"

_ORG_NORM_COLUMNS = (
    "record_id", "source_id", "yr", "mo", "binom",
    "scientific_name", "vernacular_name", "rank_l",
    "cls", "kdm", "phy", "ord", "family",
    "lat", "lon", "mlat", "mlon",
    "red_list_category", "license_class", "is_alien", "taxon_group",
)

_CREATE_ORG_NORM_SQL = (
    "CREATE TABLE org_norm ("
    "record_id TEXT, source_id TEXT, yr INT, mo INTEGER, binom TEXT, "
    "scientific_name TEXT, vernacular_name TEXT, rank_l TEXT, "
    "cls TEXT, kdm TEXT, phy TEXT, ord TEXT, family TEXT, "
    "lat REAL, lon REAL, mlat INT, mlon INT, "
    "red_list_category TEXT, license_class TEXT, is_alien INTEGER, taxon_group TEXT"
    ")"
)

# `_ORG_NORM_COLUMNS` と同じ順で SELECT 側の式を書く（列名を明示した
# `INSERT INTO org_norm (<列名>) SELECT <式> ...` の <式> 部分。並びがずれると
# 起動時に SQLite 自体が列数不一致で例外を投げる——`CREATE TABLE`/`INSERT`列名/
# ここの3つが常に同じ集合・同じ順であることをコード上でも保ちやすくするため、
# 列名のタプルを先に1箇所で宣言し、後述の `_build_insert_sql()` が
# `INSERT INTO org_norm (<...>) SELECT ...` の列名部分をそこから組み立てる）。
_ORG_NORM_SELECT_EXPRS = (
    "o.record_id",
    "o.source_id",
    "CAST(substr(o.period_raw, 1, 4) AS INT)",
    "CASE WHEN length(o.period_raw) >= 7 THEN CAST(substr(o.period_raw, 6, 2) AS INT) END",
    "t.canonical_binomial",
    "o.scientific_name",
    "o.vernacular_name",
    "t.rank",
    "t.class",
    "t.kingdom",
    "t.phylum",
    "t.\"order\"",
    "t.family",
    "o.lat",
    "o.lon",
    "CAST(FLOOR(o.lat * 100) AS INT)",
    "CAST(FLOOR(o.lon * 100) AS INT)",
    "o.red_list_category",
    "o.license_class",
    "o.is_alien",
    "COALESCE(t.taxon_group, :default_taxon_group)",
)

assert len(_ORG_NORM_SELECT_EXPRS) == len(_ORG_NORM_COLUMNS)


def _build_insert_sql() -> str:
    collist = ", ".join(_ORG_NORM_COLUMNS)
    exprlist = ",\n  ".join(_ORG_NORM_SELECT_EXPRS)
    return f"""
    INSERT INTO org_norm ({collist})
    SELECT
      {exprlist}
    FROM cube.occurrence o
    LEFT JOIN reg.taxon t ON t.taxon_id = o.taxon_id
    WHERE o.period_raw IS NOT NULL
    ORDER BY o.source_row_id
    """


# `occurrence.taxon_id` の distinct 値（実測 約33,613種）を `reg.taxon` と
# 突き合わせる。823,692行を直接 JOIN するより軽い（/simplify 指摘12。実測
# 1.19秒 かかっていたものを短縮）——taxon_id が古い registry に無いかどうかは
# 種類（distinct 値）の話であり、それを持つ行数を数えても意味が増えない。
_STALE_TAXON_COUNT_SQL = """
SELECT COUNT(*) FROM (
  SELECT DISTINCT o.taxon_id FROM cube.occurrence o WHERE o.taxon_id IS NOT NULL
) d
LEFT JOIN reg.taxon t ON t.taxon_id = d.taxon_id
WHERE t.taxon_id IS NULL
"""


def _load_default_taxon_group(path=DEFAULT_TAXON_GROUP_YAML) -> str:
    """`registry/taxon/taxon_group.yaml` の `default_label_ja` を読む
    （taxon_id が NULL の行の `taxon_group` に使う。リテラルを書かない）。
    `migrate.common`（`reconcile.common.load_yaml` の re-export）を使う——
    `scripts/registry/build_taxon.py` の読み込み関数は `taxon_crosswalk.csv`
    の存在確認等レジストリ全体のビルドに必要な前提を持ち込むため、ここでは
    使わない（コードレビュー指摘12）。
    """
    doc = common.load_yaml(path)
    return doc["default_label_ja"]


def build_org_norm_projection(
    cube_db, registry_db, out_path, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
) -> dict:
    """`occurrence`（L2）から `org_norm` を `out_path` に書く（`fresh_sqlite` で
    毎回作り直す）。戻り値は `{"n": 行数}`。

    `out_path` を書き込み用に開いた接続に `cube_db`/`registry_db` を読み取り
    専用で ATTACH し、`INSERT INTO org_norm (...) SELECT ...` を1文で実行する
    （モジュール docstring「書き込みは1つの INSERT ... SELECT」参照）。
    """
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")

        stale = conn.execute(_STALE_TAXON_COUNT_SQL).fetchone()[0]
        if stale:
            raise common.MigrationError(
                f"registry.taxon に無い taxon_id が{stale}種ある"
                "（occurrence.taxon_id は NULL ではないのに、registry 側にその taxon が無い＝"
                "b06 実行後に registry.sqlite が taxon を含まない版に入れ替わった"
                "疑いがある）。同じ registry.sqlite で scripts/b06_build_occurrence.py "
                "を再実行するか、registry.sqlite を作り直してから再実行すること。"
            )

        conn.execute(_CREATE_ORG_NORM_SQL)
        conn.execute(_build_insert_sql(), {"default_taxon_group": default_taxon_group})
        n = conn.execute("SELECT COUNT(*) FROM org_norm").fetchone()[0]
        conn.commit()
        return {"n": n}
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

    with common.timed_step("org_norm へ射影して書き出し") as info:
        result = build_org_norm_projection(args.cube_db, registry_db, args.out, args.taxon_group_yaml)
        info["n"] = result["n"]

    print(f"  org_norm: {result['n']:,}行")


if __name__ == "__main__":
    main()
