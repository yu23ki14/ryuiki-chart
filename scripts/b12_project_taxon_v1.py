#!/usr/bin/env python3
"""`registry.sqlite` の `taxon_assessment`（P-2、レッドリスト3版分、2,884行）を
v1 の派生表 `redlist_map`（44行、原表記の辞書）・`redlist_change`（2,884行、
版間比較）の形に射影する（ADR-0016 Phase B「ファクトとキューブ」P-2、
`docs/plans/PHASE_B_TAXON_ASSESSMENT.md`）。

    .venv/bin/python3 scripts/b12_project_taxon_v1.py

`data/db/v1_projection_taxon.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
2テーブルを書く。列名・列順・宣言型は `reports/derived_baseline.json` の記録
（`data/db/derived.sqlite` の実物）と一致させてある。`ias_species`（外来種、
173行）はここではなく `scripts/b08_project_occurrence_v1.py`
（`org_norm` の binom と結合する必要があるため、occurrence の縦線側に置く。
`docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 決定3参照）。

## `redlist_map` は `taxon_assessment` を経由しない

v1 の `redlist_map`（44行）は `registry/taxon/redlist_category.yaml`（正準:
code/label_ja/rank）＋ `redlist_category_alias.csv`（出典表記: raw -> code）の
2ファイルを突き合わせるだけで再構成できる、静的な語彙そのものである
（`taxon_assessment` の実データ行数には依存しない）。**`not_listed`
（`'―'` の alias。P-2決定1、v1 には無かったコード）は除いて44行にする**
——v1 の `redlist_map` は `'―'` を1行も持たず、`redlist_change` 側で
LEFT JOIN が一致しないことで「前回記載なし」を導いていた。`not_listed` は
`registry/taxon/redlist_category.yaml` で意図的に `rank: null` にしてあるので、
`redlist_change` 側で `not_listed` を素通りさせても `rank IS NULL` の分岐は
一致するが（下記参照）、`redlist_map` の行として出すと v1 に無い45行目になり
`scripts/b02_derived_compare.py` が不一致を検出する。

## `redlist_change` の `not_listed` を v1 互換に戻す

`taxon_assessment.prev_category_code` は `'―'`（247行）を `'not_listed'` として
明示的に持つ（登録時に黙って落とさない。P-2決定1）。v1 の `redlist_change` は
この247行で `prev_label`/`prev_code`/`prev_rank` がすべて `NULL`
（`LEFT JOIN redlist_map` が一致しなかったため）——`_v1_compat_code()` が
`not_listed` を出力直前に `None` に戻すことでこれを再現する。**`rank` の値
そのもの（`not_listed` は `rank: null`）は元から `NULL` なので、`direction`
（`前回記載なし`）の判定はこの変換の有無に関わらず一致する——変換が必要なのは
`prev_label`/`prev_code` という「v1 には無かった値」を出力に漏らさないため
だけ**（モジュールdocstring外の詳細は `registry/taxon/redlist_category.yaml`・
`scripts/registry/build_taxon_assessment.py` のコメント参照）。

## 小さい表なので SQL の `INSERT ... SELECT` ではなく Python で組み立てる

`scripts/b08_project_occurrence_v1.py`/`b11_project_place_v1.py` は数十万行の
表を1本の `INSERT ... SELECT` で書く（Python 側に行のリストを保持しないため）。
この2表は合計2,928行（44+2,884）と小さく、かつ `list_name`（`assessment_list.yaml`）・
`label_ja`/`rank`（`redlist_category.yaml`）という**SQLite の外（YAML）にある
語彙**を引く必要があるため、素直に Python の dict で引いてから
`executemany()` で書く（YAML を一時テーブルに読み込んで SQL 側で JOIN する
遠回りをしない）。意図的な設計判断——行数が3桁〜4桁のオーダーを超えて増える
なら SQL 側に寄せることを検討する。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_taxon.sqlite"

REDLIST_CATEGORY_YAML = ROOT / "registry" / "taxon" / "redlist_category.yaml"

# v1 に無かったコード（P-2決定1）。redlist_map には出さず、redlist_change の
# 出力列（prev/cur の label・code）では NULL に戻す。
_NOT_LISTED_CODE = "not_listed"

_REDLIST_LIST_IDS = ("rl2020", "rdb2022p", "rl2026")

_REDLIST_MAP_COLUMNS = ("raw", "label", "code", "rank")
_CREATE_REDLIST_MAP_SQL = """
CREATE TABLE redlist_map (raw TEXT PRIMARY KEY, label TEXT, code TEXT, rank INTEGER)
"""

_REDLIST_CHANGE_COLUMNS = (
    "assessment_id", "list_name", "list_year", "taxon_group_ja", "taxon_subgroup_ja",
    "family_ja", "vernacular_name_ja", "scientific_name", "national_category_ja",
    "prev_label", "prev_code", "prev_rank", "cur_label", "cur_code", "cur_rank", "direction",
)
_CREATE_REDLIST_CHANGE_SQL = """
CREATE TABLE redlist_change (
  assessment_id TEXT, list_name TEXT, list_year INT, taxon_group_ja TEXT,
  taxon_subgroup_ja TEXT, family_ja TEXT, vernacular_name_ja TEXT, scientific_name TEXT,
  national_category_ja TEXT, prev_label TEXT, prev_code TEXT, prev_rank INT,
  cur_label TEXT, cur_code TEXT, cur_rank INT, direction
)
"""


# ---------------------------------------------------------------------------
# 語彙の読み込み（scripts/registry/build_taxon_assessment.py と同じ検証を
# 再利用する——正はそちら1箇所）。
# ---------------------------------------------------------------------------

def _load_vocab():
    """`registry.build_taxon_assessment` の検証済みローダーをそのまま使う
    （`scripts/registry` は `scripts/` から見えるパッケージ。b08 が `registry`
    パッケージ外の YAML を `migrate.common.load_yaml` で読むのとは違い、ここは
    構造検証込みのローダーがそのまま要る——`_assert_unique`/`_assert_...` を
    ここで再実装しない）。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from registry import build_taxon_assessment as ta

    category_codes = ta.load_redlist_category_codes()
    alias = ta.load_redlist_category_alias()
    assessment_lists = ta.load_assessment_lists()
    return category_codes, alias, assessment_lists


def _load_category_info() -> dict[str, tuple[str, int | None]]:
    """code -> (label_ja, rank)。`registry/taxon/redlist_category.yaml` から
    直接読む（`ta.load_redlist_category_codes()` はコードの集合しか返さない
    ため、label_ja/rank も要るここだけ生の YAML を読む）。
    """
    import yaml

    with REDLIST_CATEGORY_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return {e["code"]: (e["label_ja"], e["rank"]) for e in doc["categories"]}


# ---------------------------------------------------------------------------
# redlist_map（44行。taxon_assessment を経由しない）
# ---------------------------------------------------------------------------

def _build_redlist_map_rows(
    alias: dict[str, str], category_info: dict[str, tuple[str, int | None]]
) -> list[tuple]:
    """`alias`（`registry.build_taxon_assessment.load_redlist_category_alias()` が
    構造検証済みの raw -> code）から組み立てる。`not_listed` は除く
    （モジュール docstring「redlist_map は taxon_assessment を経由しない」参照）。
    """
    rows = []
    for raw, code in alias.items():
        if code == _NOT_LISTED_CODE:
            continue
        label, rank = category_info[code]
        rows.append((raw, label, code, rank))
    return rows


# ---------------------------------------------------------------------------
# redlist_change（2,884行）
# ---------------------------------------------------------------------------

def _v1_compat(code: str | None, category_info: dict[str, tuple[str, int | None]]) -> tuple[str | None, int | None]:
    """`code` から (label, rank) を求める。`not_listed`（v1 に無かったコード。
    モジュール docstring参照）は NULL に戻す。"""
    if code is None or code == _NOT_LISTED_CODE:
        return None, None
    label, rank = category_info[code]
    return label, rank


def _direction(cur_rank: int | None, prev_rank: int | None) -> str:
    """v1（web/scripts/build-biota.mjs 300-303行）の CASE 式そのまま。"""
    if prev_rank is None:
        return "前回記載なし"
    if cur_rank > prev_rank:
        return "悪化"
    if cur_rank < prev_rank:
        return "改善"
    return "横ばい"


def _build_redlist_change_rows(
    conn: sqlite3.Connection,
    assessment_lists: dict[str, dict],
    category_info: dict[str, tuple[str, int | None]],
) -> list[tuple]:
    rows = []
    cur = conn.execute(
        """
        SELECT assessment_id, list_id, list_year, taxon_group_ja, taxon_subgroup_ja,
               family_ja, vernacular_name_ja_raw, scientific_name_raw,
               national_category_raw, category_code, prev_category_code
        FROM reg.taxon_assessment
        WHERE list_id IN ({})
        ORDER BY assessment_id
        """.format(",".join("?" for _ in _REDLIST_LIST_IDS)),
        _REDLIST_LIST_IDS,
    )
    for row in cur:
        (
            assessment_id, list_id, list_year, taxon_group_ja, taxon_subgroup_ja,
            family_ja, vernacular_name_ja, scientific_name,
            national_category_ja, category_code, prev_category_code,
        ) = row
        list_name = assessment_lists[list_id]["name"]
        cur_label, cur_rank = _v1_compat(category_code, category_info)
        prev_label, prev_rank = _v1_compat(prev_category_code, category_info)
        direction = _direction(cur_rank, prev_rank)
        rows.append((
            assessment_id, list_name, list_year, taxon_group_ja, taxon_subgroup_ja,
            family_ja, vernacular_name_ja, scientific_name, national_category_ja,
            prev_label, prev_category_code if prev_category_code != _NOT_LISTED_CODE else None,
            prev_rank, cur_label, category_code, cur_rank, direction,
        ))
    return rows


# ---------------------------------------------------------------------------
# 組み立て・書き出し
# ---------------------------------------------------------------------------

def _assert_prerequisites(registry_db) -> None:
    registry_path = pathlib.Path(registry_db)
    if not registry_path.exists():
        raise common.MigrationError(
            f"{registry_path} が無い。先に scripts/r01_build_registry.py を実行すること。"
        )
    conn = sqlite3.connect(f"file:{registry_path}?mode=ro", uri=True)
    try:
        has_table = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='taxon_assessment'"
        ).fetchone()[0]
    finally:
        conn.close()
    if not has_table:
        raise common.MigrationError(
            f"{registry_path} に taxon_assessment テーブルが無い。"
            "scripts/r01_build_registry.py で registry.sqlite を作り直すこと"
            "（taxon_assessment (P-2) が新設されたのはこの PR）。"
        )


def build_projections(registry_db, out_path) -> dict[str, int]:
    _assert_prerequisites(registry_db)
    category_codes, alias, assessment_lists = _load_vocab()
    category_info = _load_category_info()
    assert set(category_info) == category_codes, (
        f"redlist_category.yaml（{sorted(category_info)}）と "
        f"load_redlist_category_codes()（{sorted(category_codes)}）の集合が食い違う"
    )

    redlist_map_rows = _build_redlist_map_rows(alias, category_info)

    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, registry_db, "reg")
        redlist_change_rows = _build_redlist_change_rows(conn, assessment_lists, category_info)

        conn.execute(_CREATE_REDLIST_MAP_SQL)
        conn.executemany(
            f"INSERT INTO redlist_map ({', '.join(_REDLIST_MAP_COLUMNS)}) VALUES (?,?,?,?)",
            redlist_map_rows,
        )
        conn.execute(_CREATE_REDLIST_CHANGE_SQL)
        placeholders = ",".join("?" for _ in _REDLIST_CHANGE_COLUMNS)
        conn.executemany(
            f"INSERT INTO redlist_change ({', '.join(_REDLIST_CHANGE_COLUMNS)}) VALUES ({placeholders})",
            redlist_change_rows,
        )
        conn.commit()
    finally:
        conn.close()

    return {"redlist_map": len(redlist_map_rows), "redlist_change": len(redlist_change_rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step(f"v1 形（2テーブル）へ射影して {args.out} に書き出し") as info:
        counts = build_projections(registry_db, args.out)
        info["n"] = sum(counts.values())

    for table, n in sorted(counts.items()):
        print(f"  {table}: {n:,}行")


if __name__ == "__main__":
    main()
