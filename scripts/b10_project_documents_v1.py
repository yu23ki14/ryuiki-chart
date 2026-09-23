#!/usr/bin/env python3
"""`cells.sqlite`/`ryuiki.sqlite`（原本、読み取り専用で ATTACH）から v1 の
`doc_series`/`doc_series_meta`/`quality_monthly` を射影する（ADR-0016 Phase B
「文書の証跡層と品質ワークフロー」P-3。docs/plans/PHASE_B_DOCUMENTS.md 参照）。

    .venv/bin/python3 scripts/b10_project_documents_v1.py

`data/db/v1_projection_documents.sqlite`（毎回ゼロから作り直す、専用の出力
ファイル）に3テーブルを書く。

## なぜ b03〜b05（`observation`/`observation_agg`）を経由しないか（オーナー決定）

ADR-0011「33テーブルの行き先」表は当初この3テーブルを `cube_observation`
（入力 `observation`）に分類していたが、実際の入力は `observation` ではない
（`docs/adr/0011-aggregation-cube.md` の該当節・`docs/plans/PHASE_B_DOCUMENTS.md`
参照）:

- `doc_series`/`doc_series_meta` の入力は `cells.sqlite`（行政 PDF から抽出した
  セルの表。ADR README §4 の `document`/`cell` エンティティの v1 実体）。
  主語が place ではなく文書の表、指標が `row_key` の生文字列（variable 未解決）
  で、ADR-0007 の observation の判定基準（主語が place、値が指標レジストリに
  登録済み）を満たさない。
- `quality_monthly` の入力は `ryuiki.sqlite` の `quality_transitions`
  （ADR-0017 が読み取り基盤の対象外とする書き込み系ログ。3,372行すべて
  `target_id LIKE 'SYN-MEAS-%'` の合成データ）。place も variable も無い。

そのため v2 に対応するファクトを新設せず、**cells.sqlite/ryuiki.sqlite を
直接 ATTACH して v1 と同じ SQL を再実行する射影**にする（このゲートの性格
——v1 表の持ち越しを確かめるだけで v2 変換の正しさは確かめない——は
`docs/plans/PHASE_B_DOCUMENTS.md` 冒頭参照）。

## SQL は v1（`web/scripts/build-derived.mjs:272-323`）と一字一句同じ

`CREATE TABLE ... AS SELECT`（`CREATE TABLE` + 列宣言 + `INSERT ... SELECT`
に分けない）で v1 の SQL 文字列をそのまま再実行する。理由:

1. v1 の計算列（`doc_series.label`/`value`/`n_cells`/`unit`、`doc_series_meta`
   の集計列全部、`quality_monthly` の全列）は宣言型を持たない
   （`PRAGMA table_info` で確認済み）。列を明示的に宣言する形
   （`CREATE TABLE` に型を書いてから `INSERT ... SELECT` する形）に変えると、
   この「宣言型が無い」という v1 の実際の形とわざと違えてしまう。
2. ATTACH のエイリアス（`c`=cells.sqlite、`r`=ryuiki.sqlite）も v1 と同じに
   してあるので、SQL 文字列は v1 からコピーしただけで一字一句変えていない
   （`web/scripts/build-derived.mjs` の該当行を参照すれば照合できる）。

## v1 の癖として温存するもの

宣言済み差分ではない（同じ SQL で完全再現するので b02 の差分としては出ない）。
label のバグ・`n_warnings` の相関サブクエリ・`HAVING n_years >= 3` の境界・
fiscal_year の潰れ・`page_no`/`unit` の裸列の5つ。実測は
`docs/plans/PHASE_B_DOCUMENTS.md` §3 にまとめてある（ここでは繰り返さない）。

## 3値の語彙（暫定/検証済/公開済）の正

`quality_monthly` の CASE 式が参照する3値の正は `web/src/lib/quality.ts` の
`QUALITY_STAGES`（このコメントは参照だけ。ここに新しい宣言ファイルは作らない）。

## SQLite の版を守る

`doc_series` は `AVG()` を使う。`build_documents_projection()` の先頭で
`common.require_sqlite_version()`（`scripts/migrate/common.py`。b04・b05 と
共有するガード。なぜモジュール読み込み時点で呼ばないかはそちらの docstring
参照）を呼ぶ。実測は `docs/plans/PHASE_B_DOCUMENTS.md` §2 参照。
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_CELLS_DB = ROOT / "data" / "db" / "cells.sqlite"
DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_documents.sqlite"

# v1（`web/scripts/build-derived.mjs:272-281`）と一字一句同じ。
_QUALITY_MONTHLY_SQL = """
CREATE TABLE quality_monthly AS
SELECT substr(occurred_at,1,7) AS ym,
       SUM(CASE WHEN from_stage IS NULL AND to_stage='暫定' THEN 1 ELSE 0 END) AS submitted,
       SUM(CASE WHEN from_stage='暫定'  AND to_stage='検証済' THEN 1 ELSE 0 END) AS verified,
       SUM(CASE WHEN from_stage='検証済' AND to_stage='公開済' THEN 1 ELSE 0 END) AS published,
       SUM(CASE WHEN from_stage='暫定'  AND to_stage='暫定'  THEN 1 ELSE 0 END) AS returned
FROM r.quality_transitions GROUP BY ym ORDER BY ym
"""

# v1（`web/scripts/build-derived.mjs:290-308`）と一字一句同じ。
_DOC_SERIES_SQL = """
CREATE TABLE doc_series AS
WITH num AS (
  SELECT doc_id, table_id, page_no, row_key, col_key, fiscal_year,
         CAST(value AS REAL) AS v, unit
  FROM c.cells
  WHERE superseded = 0 AND is_total = 0
    AND value_type IN ('int','float') AND value IS NOT NULL
    AND fiscal_year IS NOT NULL AND row_key IS NOT NULL AND row_key <> ''
)
SELECT doc_id, table_id, page_no, row_key,
       CASE WHEN instr(row_key,'|') > 0
            THEN substr(row_key, length(row_key) - length(replace(substr(row_key, instr(row_key,'|')+1), '|', '')) + 1)
            ELSE row_key END AS label,
       fiscal_year, AVG(v) AS value, COUNT(*) AS n_cells, MAX(unit) AS unit
FROM num
GROUP BY doc_id, table_id, row_key, fiscal_year
"""

_DOC_SERIES_INDEX_SQL = "CREATE INDEX ix_ds ON doc_series(doc_id, table_id, row_key)"

# v1（`web/scripts/build-derived.mjs:311-322`）と一字一句同じ。
_DOC_SERIES_META_SQL = """
CREATE TABLE doc_series_meta AS
SELECT s.doc_id, s.table_id, s.row_key, MAX(s.label) AS label, MAX(s.page_no) AS page_no,
       COUNT(*) AS n_years, MIN(s.fiscal_year) AS y_from, MAX(s.fiscal_year) AS y_to,
       MAX(s.unit) AS unit, MIN(s.value) AS v_min, MAX(s.value) AS v_max,
       d.title AS doc_title, d.publisher, d.url, d.license,
       (SELECT COUNT(*) FROM c.notes n WHERE n.doc_id = s.doc_id AND n.blocks_timeseries = 1) AS n_warnings
FROM doc_series s JOIN c.documents d ON d.doc_id = s.doc_id
GROUP BY s.doc_id, s.table_id, s.row_key
HAVING n_years >= 3
"""

_DOC_SERIES_META_INDEX_SQL = "CREATE INDEX ix_dsm ON doc_series_meta(n_years DESC)"

# 出力の3テーブル（ビルド順。doc_series_meta は doc_series に従属する）。
_TABLES = ("quality_monthly", "doc_series", "doc_series_meta")


def build_documents_projection(cells_db, ryuiki_db, out_path) -> dict[str, int]:
    """`out_path` に3テーブルを書く（`fresh_sqlite` で毎回作り直す）。
    戻り値は `{table: 行数}`。

    `cells_db`/`ryuiki_db` は読み取り専用で ATTACH する
    （`c`/`r`——v1 と同じエイリアス）。各テーブルは `CREATE TABLE ... AS
    SELECT`（v1 の SQL をそのまま）で作る。

    書き終えたら3表とも0行でないことを確認する（`MigrationError`）。入力の
    スキーマ・運用が変わって `num`（`WHERE`）が1行も拾わなくなったとき、
    0行・終了コード0で黙って通るのを防ぐ（コードレビュー指摘）。

    `AVG()` を実行する前に `common.require_sqlite_version()` を呼ぶ
    （モジュール docstring「SQLite の版を守る」参照）。
    """
    common.require_sqlite_version()
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, ryuiki_db, "r")
        common.attach_readonly(conn, cells_db, "c")

        conn.execute(_QUALITY_MONTHLY_SQL)
        conn.execute(_DOC_SERIES_SQL)
        conn.execute(_DOC_SERIES_INDEX_SQL)
        conn.execute(_DOC_SERIES_META_SQL)
        conn.execute(_DOC_SERIES_META_INDEX_SQL)
        conn.commit()

        counts = {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in _TABLES
        }
        empty = [table for table, n in counts.items() if n == 0]
        if empty:
            raise common.MigrationError(
                f"0行になったテーブルがある: {empty}。cells.sqlite/ryuiki.sqlite の"
                "スキーマ・運用が変わって WHERE 句（superseded/is_total/value_type/"
                "fiscal_year/row_key、または quality_transitions 自体）が1行も拾わ"
                "なくなった疑いがある。黙って0行のまま進めない。"
            )
        return counts
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells-db", default=str(DEFAULT_CELLS_DB))
    parser.add_argument("--ryuiki-db", default=str(DEFAULT_RYUIKI_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    print(f"▶ 読み取り専用で開く: {args.cells_db}")
    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")

    with common.timed_step(f"{args.out} に射影") as info:
        counts = build_documents_projection(args.cells_db, args.ryuiki_db, args.out)
        info["n"] = sum(counts.values())

    for table in _TABLES:
        print(f"  {table}: {counts[table]:,}行")


if __name__ == "__main__":
    main()
