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
直接 ATTACH して v1 と同じ SQL を再実行する射影**にする。このゲートは
「v1 表をそのまま持ち越せる（＝原本が変わっていない）」ことを確かめるだけで、
v2 変換の正しさを確かめるものではない（ADR-0017 原則4「デモの合成分は
当面 L2 の一部として扱う」と同じ扱い。org_norm や meas_year のような
`observation`/`occurrence` 経由の射影とは性格が違う）。

## SQL は v1（`web/scripts/build-derived.mjs:272-323`）と一字一句同じ

`CREATE TABLE ... AS SELECT`（`CREATE TABLE` + 列宣言 + `INSERT ... SELECT`
に分けない）で v1 の SQL 文字列をそのまま再実行する。理由:

1. v1 の計算列（`doc_series.label`/`value`/`n_cells`/`unit`、`doc_series_meta`
   の集計列全部、`quality_monthly` の全列）は宣言型を持たない
   （`PRAGMA table_info` で確認済み）。列を明示的に宣言する形
   （`scripts/b08_project_occurrence_v1.py` の流儀）に変えると、この「宣言型
   が無い」という v1 の実際の形とわざと違えてしまう。
2. ATTACH のエイリアス（`c`=cells.sqlite、`r`=ryuiki.sqlite）も v1 と同じに
   してあるので、SQL 文字列は v1 からコピーしただけで一字一句変えていない
   （`web/scripts/build-derived.mjs` の該当行を参照すれば照合できる）。

## v1 の癖として温存し、記録するもの（宣言済み差分ではない。同じ SQL で
完全再現するので b02 の差分としては出ない。実測は
`docs/plans/PHASE_B_DOCUMENTS.md` 参照）

- **`row_key` に `|` が2個以上あると `label` が誤る**: `label` の式は
  「最初の `|` より後ろから、末尾の `|` の直後まで」を切り出すバグを持つ
  （意図は「最後の `|` より後ろ（末尾トークン）」だが実装が違う）。実測:
  `cells`（集約前）で328行、`doc_series`（集約後）で289行が該当し、うち7行は
  `label` が `|` で始まる（例: `'山北町|三保|入猟者数'` → `'保|入猟者数'`）。
- **`doc_series_meta.n_warnings` は doc 単位の相関サブクエリ**（`table_id`/
  `row_key` で絞らない）: 同じ `doc_id` の全 `doc_series_meta` 行に、その文書
  全体の `notes.blocks_timeseries=1` 件数がそのまま重複して入る。実測:
  13文書・378行（`doc_series_meta` 470行中）が対象。
- **`doc_series_meta` の `HAVING n_years >= 3`**: 画面側（`web/src/lib/
  queries.ts` の `docSeriesList`）は既定 `minYears=4` で読むため、
  `n_years==3` の行（実測36行）はテーブルには残るが既定表示では見えない。
- **別年の値が1つの `fiscal_year` に潰れて平均される**: `col_key` に複数年度
  が連結された出典（例 `'H25 H26 H27 H28 H29 H30'`）が単一の `fiscal_year`
  に丸められているため、`AVG(v)` が本来別々の年の値を平均する。実測:
  `n_cells > 1` の344グループ中336グループで実際に値が異なる
  （`choju_higai_gaiyou_2019`/`p1_t4` で確認済み）。

## 3値の語彙（暫定/検証済/公開済）の正

`quality_monthly` の CASE 式が参照する3値の正は `web/src/lib/quality.ts` の
`QUALITY_STAGES`（このコメントは参照だけ。ここに新しい宣言ファイルは作らない）。
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
    """
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

        return {
            table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in _TABLES
        }
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
