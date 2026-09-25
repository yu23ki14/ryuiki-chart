#!/usr/bin/env python3
"""`registry.sqlite` の `place`（place_kind='watershed'）⋈ `place_watershed` ⋈
`place_source_ref` を v1 の派生表 `watershed_meta` の形に射影する
（ADR-0016 Phase B「ファクトとキューブ」P-1a、
docs/plans/PHASE_B_PLACE_ATTRIBUTES.md）。あわせて `watershed_rollup`
（P-1a が「後で同じ b11 に足す」と書いた最後の1表。Phase B 残り1表。
「ゲートの統合」実装指示 §A）も同じ出力ファイルに書く。

    .venv/bin/python3 scripts/b11_project_place_v1.py

`data/db/v1_projection_place.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
`watershed_meta`・`watershed_rollup` の2テーブルを書く。列名・列順・宣言型は
`reports/derived_baseline.json` の記録と完全に一致させてある
（`scripts/b02_derived_compare.py --candidate ... --tables watershed_meta,watershed_rollup`
がそのまま突き合わせられるように）。

`observation`/`observation_agg`（v2.sqlite）は経由しない（`watershed_meta`/
`watershed_rollup` はどちらも observation を一切経由しない静的な地理データの
結合射影——`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同じ「キューブのセルにしない」
対象。`watershed_rollup` の**SQL自体**は v2.sqlite を一切参照しない）。

**例外的に `--cube-db`（既定 `data/db/v2.sqlite`）を1つだけ持つ**（Issue #37
#1、コードレビュー指摘）。これは `site_var`/`landuse_watershed`/`org_watershed`
が記録した系譜（`observation_agg`/`occurrence`/`occurrence_place` の指紋）を、
それら自身の**今の**自己指紋と突き合わせるためだけの ATTACH で、生データは
一切読まない（`_assert_rollup_input_fingerprints_fresh`）。無ければこの
系譜チェックだけを省略して続行する——`watershed_rollup` を作るのに
v2.sqlite は要らないという設計原則は変えていない。

## watershed_rollup（v1: `web/scripts/build-geo.mjs:227-251`）

`watershed_meta`（このスクリプト自身が直前に書いたもの）・
`org_watershed`（`data/db/v1_projection_occurrence.sqlite`、b08。O-2a、
**キューブの正確な値ではなく v1 のメモ化の癖を再現した方**——そうしないと
185行ずれる）・`site_var`/`landuse_watershed`（`data/db/v1_projection.sqlite`、
b05）の4つの射影出力を読み取り専用で ATTACH して結合するだけの「D10型の
結合射影」（独立したキューブのセルにはしない。ADR-0011 の宣言も
`place_attribute` のまま動かさない）。**`site_n`/`site_var_n` は `sites.watershed`
の直接一致**（点内包判定ではない）——P-1a が入れた地点→流域の `place_relation`
の辺（`relation='within'`、278件）から `site_watershed_lookup` を組み立てて
引く（`site_n` は地点数、`site_var_n` は地点×変数の件数で地点数ではない。
実測はテスト・PR 説明参照）。4つの入力のうちどれか1つでも無ければ、
「先に何を実行すべきか」を名指しして止める（`_assert_rollup_prerequisites`。
`scripts/b08_project_occurrence_v1.py` の `_assert_prerequisites` と同じ形）。

列名・列順・**型宣言（storage class）**は v1 の実物と一致させる。v1 は
`CREATE TABLE watershed_rollup AS SELECT ...`（CTAS）で作っており、直接の列
参照（`watershed_id`/`water_system_name`/`area_km2`/`centroid_lat`/
`centroid_lon`）だけが `watershed_meta` の宣言型を引き継ぎ、残り11列（集計式・
相関サブクエリ）は無型になる（`reports/derived_baseline.json` の該当列も
`type: ""`）。ここでも同じ CTAS を使い、v1 の SQL 構造をそのまま踏襲することで
型宣言を1文字も手で書かずに揃える（P-1b の `landuse_change` が学んだ
「型を宣言すると INSERT 時に強制変換されて storage class が v1 とずれる」を
CTAS で丸ごと回避する）。

検証（`_validate_registry()`・`_assert_rollup_prerequisites()`・
`_assert_out_path_distinct_from_inputs()`・`_assert_no_stale_watershed_or_site_ids()`・
`_assert_rollup_input_fingerprints_fresh()`（段階間の指紋、Issue #37 #1）。
どれも出力ファイルに一切触れない）が全部通ってから `common.fresh_sqlite(out_path)`
で書き出す。設計根拠（`INSERT ... SELECT` を1文にする理由・列名を明示する理由・
検証と書き込みを分ける理由・各検証関数が何を防ぐか）は
`docs/plans/PHASE_B_PLACE_ATTRIBUTES.md` §6・§10・`docs/plans/
PHASE_B_RECONCILIATION.md` §12 参照（ここでは再掲しない）。`common.fresh_sqlite`
自体が原本を誤って消せる問題は P-3 側の PR の担当（このブランチでは触れない）。
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
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_place.sqlite"
# watershed_rollup が読む、他の2本の射影スクリプトの出力（読み取り専用で ATTACH する）。
DEFAULT_V1_PROJECTION_DB = ROOT / "data" / "db" / "v1_projection.sqlite"
DEFAULT_V1_PROJECTION_OCCURRENCE_DB = ROOT / "data" / "db" / "v1_projection_occurrence.sqlite"
# 段階間の指紋（Issue #37 #1）の系譜チェック専用（`_assert_rollup_input_fingerprints_fresh`
# 参照）。watershed_rollup 自体の SQL は v2.sqlite を一切参照しない
# （モジュール docstring「経由しない」参照）——ここで ATTACH するのは
# `site_var`/`landuse_watershed`/`org_watershed` が記録した系譜
# （`inputs`）の上流（`observation_agg`/`occurrence`/`occurrence_place`）
# 自身の自己指紋を安く読むためだけで、生データは一切読まない。
DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"

# v1（`web/scripts/build-geo.mjs`、`reports/derived_baseline.json`）と列名・列順・
# 宣言型を完全に一致させる。
_WATERSHED_META_COLUMNS = (
    "watershed_id", "water_system_code", "water_system_name",
    "water_system_category", "main_rivers", "area_km2",
    "centroid_lat", "centroid_lon", "data_year", "source_ref",
)

_CREATE_WATERSHED_META_SQL = """
CREATE TABLE watershed_meta (
  watershed_id TEXT, water_system_code TEXT, water_system_name TEXT,
  water_system_category TEXT, main_rivers TEXT, area_km2 REAL,
  centroid_lat REAL, centroid_lon REAL, data_year INTEGER, source_ref TEXT
)
"""

# INSERT 側にも列名を明示する（理由はモジュール docstring・
# docs/plans/PHASE_B_PLACE_ATTRIBUTES.md §10-8 参照。`_WATERSHED_META_COLUMNS` と
# SELECT の AS 別名の並びを一致させること）。
_INSERT_WATERSHED_META_SQL = f"""
INSERT INTO watershed_meta ({", ".join(_WATERSHED_META_COLUMNS)})
SELECT
  psr.external_key AS watershed_id,
  pw.water_system_code AS water_system_code,
  p.name_ja AS water_system_name,
  pw.water_system_category AS water_system_category,
  pw.main_rivers AS main_rivers,
  p.area_km2 AS area_km2,
  p.lat AS centroid_lat,
  p.lon AS centroid_lon,
  pw.data_year AS data_year,
  p.definition_ref AS source_ref
FROM reg.place p
JOIN reg.place_source_ref psr
  ON psr.place_id = p.place_id AND psr.source_id = 'watershed_meta.watershed_id'
JOIN reg.place_watershed pw ON pw.place_id = p.place_id
WHERE p.place_kind = 'watershed'
"""

# --- watershed_rollup（v1: web/scripts/build-geo.mjs:227-251。モジュール
# docstring「watershed_rollup」節参照） -----------------------------------

# v1 と列名・列順を一致させる（テスト用。CTAS が実際に作る列順の記録でもある）。
_WATERSHED_ROLLUP_COLUMNS = (
    "watershed_id", "water_system_name", "area_km2", "centroid_lat", "centroid_lon",
    "org_n", "org_alien_n", "org_redlist_n", "site_n", "site_var_n",
    "built_km2_2016", "built_km2_2006", "forest_km2_2016", "forest_km2_2006",
    "paddy_km2_2016", "paddy_km2_2006",
)

# 地点→流域（P-1a が入れた `place_relation`、`relation='within'`、278件）から
# `site_id -> watershed_id` を引く。`sites.watershed` は sites 本体の直接一致
# （点内包判定ではない。モジュール docstring参照）——`sites.site_id` 側は
# `place_source_ref(source_id='sites.site_id')`、`watershed_id` 側は
# `watershed_meta` の INSERT と同じ `source_id='watershed_meta.watershed_id'` で
# 逆引きする（`scripts/b05_project_v1.py` の `_SITE_ZONE_LOOKUP_SQL` と同じ形。
# ゾーンと違い、watershed 側は独立した「sites.watershed」名前空間の
# place_source_ref を持たない——`watershed_meta.watershed_id` の逆引きをそのまま
# 親側の解決に使う。docs/plans/PHASE_B_PLACE_ATTRIBUTES.md §10-7参照）。
#
# 裸の SELECT（`FROM`/`JOIN` 部分だけ）として持ち、`_validate_registry()`
# （一意性の検証。`reg` だけを ATTACH した読み取り専用の一時コネクション）と
# `build_projections()`（実際に `CREATE TEMP TABLE` する書き込み用コネクション）
# の両方から同じ1つの定義を参照する（コードレビュー指摘: 以前はこの一意性検査が
# `fresh_sqlite` の**後**にあり、失敗すると前回の正しい出力が消えたまま
# 中途半端な状態が残っていた）。
_SITE_WATERSHED_LOOKUP_SELECT_SQL = """
SELECT site_ref.external_key AS site_id, watershed_ref.external_key AS watershed_id
FROM reg.place_relation pr
JOIN reg.place_source_ref site_ref
  ON site_ref.place_id = pr.child_id AND site_ref.source_id = 'sites.site_id'
JOIN reg.place_source_ref watershed_ref
  ON watershed_ref.place_id = pr.parent_id AND watershed_ref.source_id = 'watershed_meta.watershed_id'
WHERE pr.relation = 'within'
"""

_CREATE_SITE_WATERSHED_LOOKUP_SQL = (
    f"CREATE TEMP TABLE site_watershed_lookup AS {_SITE_WATERSHED_LOOKUP_SELECT_SQL}"
)


def _duplicate_site_watershed_message(dup: list) -> str:
    """`site_watershed_lookup` の `site_id` が単射でない（同じ地点が複数の
    流域に属している）ときのメッセージ。r01 が「地点は流域への within 辺を
    高々1本」を不変条件として保証済み（PHASE_B_PLACE_ATTRIBUTES.md §6）だが、
    `site_n`/`site_var_n` が水増しされる射影固有の壊れ方を独立に防ぐ
    （`_duplicate_watershed_source_ref_message` と同じ考え方）。
    """
    return (
        f"site_watershed_lookup の site_id が単射でない（同じ地点が複数の流域に"
        f"属している）: {dup}\n"
        "watershed_rollup の site_n/site_var_n が水増しされる。"
        "scripts/registry/build_place.py の watershed 節、または r01 の"
        "「地点は流域への within 辺を高々1本」不変条件を確認すること。"
    )


# 土地利用（`proj.landuse_watershed`）の相関サブクエリは区分・年ごとに4組。
# v1（build-geo.mjs）の SQL をそのまま踏襲し、CTAS で storage class も
# 手を加えずに揃える（モジュール docstring参照）。
_CREATE_WATERSHED_ROLLUP_SQL = """
CREATE TABLE watershed_rollup AS
SELECT w.watershed_id, w.water_system_name, w.area_km2,
       w.centroid_lat, w.centroid_lon,
       COALESCE(o.n, 0) AS org_n, COALESCE(o.alien_n, 0) AS org_alien_n,
       COALESCE(o.redlist_n, 0) AS org_redlist_n,
       (SELECT COUNT(*) FROM site_watershed_lookup swl
         WHERE swl.watershed_id = w.watershed_id) AS site_n,
       (SELECT COUNT(*) FROM site_watershed_lookup swl
         JOIN proj.site_var v ON v.site_id = swl.site_id
         WHERE swl.watershed_id = w.watershed_id) AS site_var_n,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2016
            AND l.landuse_name = '建物用地') AS built_km2_2016,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2006
            AND l.landuse_name = '建物用地') AS built_km2_2006,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2016
            AND l.landuse_name = '森林') AS forest_km2_2016,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2006
            AND l.landuse_name = '森林') AS forest_km2_2006,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2016
            AND l.landuse_name = '田') AS paddy_km2_2016,
       (SELECT SUM(area_km2) FROM proj.landuse_watershed l
          WHERE l.watershed_id = w.watershed_id AND l.year = 2006
            AND l.landuse_name = '田') AS paddy_km2_2006
FROM watershed_meta w
LEFT JOIN occ.org_watershed o USING (watershed_id)
"""


# 「テーブルの存在確認」「GROUP BY での重複検出」はどちらも
# `scripts/b05_project_v1.py`/`scripts/b08_project_occurrence_v1.py` と同型の
# 検証だったため、共通ヘルパ（`scripts/migrate/common.py` の
# `assert_attached_table_exists`/`raise_on_group_by_duplicates`）を呼ぶだけにした
# （main へのリベースで O-1b がこれらの共通ヘルパを追加済みのため移した。
# 以前はこのモジュールに専用関数を2つ持っていた）。


def _duplicate_watershed_source_ref_message(dup: list) -> str:
    """`place_source_ref(source_id='watershed_meta.watershed_id')` が `place_id`
    について単射でないときのメッセージを組み立てる。

    同じ place に対応する行が2つあると、`_INSERT_WATERSHED_META_SQL` の
    `JOIN reg.place_source_ref psr ON psr.place_id = p.place_id AND ...` が
    その place を2回ヒットさせ、377件が378件に水増しされる——一番気づきにくい
    壊れ方（行数だけを見ていると気づけない。code-review 指摘: 以前は
    `external_key` で GROUP BY しており、この水増しを検出できていなかった）。
    `(place_id, source_id)` の一意性自体は r01 の `ID_UNIQUENESS_CHECKS` が
    build_place.py の出力に対して保証済みだが（レジストリ全体の不変条件）、
    射影する側でも独立に確かめる（射影固有の防御）。
    """
    return (
        "place_source_ref(source_id='watershed_meta.watershed_id') が place_id に"
        f"ついて単射でない（同じ place に複数の external_key が対応している）: {dup}\n"
        "watershed_meta への射影が行を水増しする。scripts/registry/build_place.py の "
        "watershed 節、または r01 の ID_UNIQUENESS_CHECKS を確認すること。"
    )


def _validate_registry(registry_db) -> None:
    """`registry_db` を読み取り専用の一時コネクションで検証する。出力ファイルには
    一切触れない（モジュール docstring参照）。
    """
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, registry_db, "reg")
        common.assert_attached_table_exists(
            work, "reg", "place_watershed",
            hint=(
                "Phase B `phase-b/place-attributes` で新設されたテーブルなので、それより前に"
                "ビルドした古い registry.sqlite には無い。"
                "scripts/r01_build_registry.py で registry.sqlite を作り直すこと。"
            ),
        )
        common.raise_on_group_by_duplicates(
            work,
            """
            SELECT psr.place_id, COUNT(*) AS n FROM reg.place_source_ref psr
            WHERE psr.source_id = 'watershed_meta.watershed_id'
            GROUP BY psr.place_id HAVING COUNT(*) > 1
            LIMIT 5
            """,
            (),
            _duplicate_watershed_source_ref_message,
        )
        # watershed_rollup の site_watershed_lookup が読む（ADR-0022 決定2で新設）。
        common.assert_attached_table_exists(
            work, "reg", "place_relation",
            hint=(
                "ADR-0022 決定2で新設されたテーブルなので、それより前にビルドした古い "
                "registry.sqlite には無い。scripts/r01_build_registry.py で "
                "registry.sqlite を作り直すこと。"
            ),
        )
        # site_watershed_lookup（watershed_rollup の site_n/site_var_n が使う）の
        # 一意性を、出力ファイルに触れる前にここで確かめる（コードレビュー指摘1:
        # 以前はこの検査が `common.fresh_sqlite(out_path)` の**後**にあり、
        # 失敗すると前回の正しい出力が消えたまま中途半端な状態が残っていた。
        # `place_relation`/`place_source_ref` の存在は直前で確認済みなので、
        # ここで安全に `_SITE_WATERSHED_LOOKUP_SELECT_SQL` を実行できる）。
        common.raise_on_group_by_duplicates(
            work,
            f"SELECT site_id, COUNT(*) AS n FROM ({_SITE_WATERSHED_LOOKUP_SELECT_SQL}) "
            "GROUP BY site_id HAVING COUNT(*) > 1 LIMIT 5",
            (),
            _duplicate_site_watershed_message,
        )
    finally:
        work.close()


def _assert_rollup_prerequisites(v1_projection_db, v1_projection_occurrence_db) -> None:
    """watershed_rollup が ATTACH する2つの射影出力（`v1_projection_db` の
    `site_var`/`landuse_watershed`、`v1_projection_occurrence_db` の
    `org_watershed`）が存在し、必要なテーブルを持つことを、出力ファイルに
    触れる前に確かめる（`scripts/b08_project_occurrence_v1.py` の
    `_assert_prerequisites` と同じ形。無ければ素の `FileNotFoundError`/
    `OperationalError` ではなく「先に何を実行すべきか」を名指しして止める）。
    """
    proj_path = pathlib.Path(v1_projection_db)
    if not proj_path.exists():
        raise common.MigrationError(
            f"{proj_path} が無い。watershed_rollup（site_var/landuse_watershed を読む）の"
            "ために先に scripts/b05_project_v1.py を実行すること。"
        )
    missing_proj = [
        t for t in ("site_var", "landuse_watershed") if t not in common.existing_tables(proj_path)
    ]
    if missing_proj:
        names = "・".join(f"`{t}`" for t in missing_proj)
        raise common.MigrationError(
            f"{proj_path} に {names} テーブルが無い。先に scripts/b05_project_v1.py を"
            "実行すること。"
        )

    occ_path = pathlib.Path(v1_projection_occurrence_db)
    if not occ_path.exists():
        raise common.MigrationError(
            f"{occ_path} が無い。watershed_rollup（org_watershed を読む）のために先に "
            "scripts/b08_project_occurrence_v1.py を実行すること"
            "（実行順は b06 → b09 → b07 → b08）。"
        )
    if "org_watershed" not in common.existing_tables(occ_path):
        raise common.MigrationError(
            f"{occ_path} に `org_watershed` テーブルが無い。先に "
            "scripts/b08_project_occurrence_v1.py を実行すること。"
        )


def _assert_out_path_distinct_from_inputs(out_path, v1_projection_db, v1_projection_occurrence_db) -> None:
    """`--out` が `v1_projection_db`/`v1_projection_occurrence_db`（b11 が
    ATTACH で読む2つの入力）と同じ実体を指していないことを確認する。

    `common.fresh_sqlite(out_path)` は `out_path` を検証より前に即座に消す
    ため、`--out data/db/v1_projection.sqlite` のように入力の1つと同じパスを
    渡すと、b05 の出力を消してから ATTACH に失敗する——前回の正しい出力
    （v1_projection.sqlite）が復元できない形で失われる、この検証群の中で
    唯一「他スクリプトの正しい出力を壊す」壊れ方。`common.assert_distinct_
    realpaths`（`common.reject_protected_source_db` が原本3つを保護するのと
    同じ realpath 比較ヘルパ）を、こちらはこのスクリプトが新たに ATTACH する
    可変の2つの入力に対して呼ぶ。
    """
    inputs = {
        "v1_projection_db（scripts/b05_project_v1.py の出力）": v1_projection_db,
        "v1_projection_occurrence_db（scripts/b08_project_occurrence_v1.py の出力）": (
            v1_projection_occurrence_db
        ),
    }
    common.assert_distinct_realpaths(
        out_path, inputs,
        message_for=lambda label, other: (
            f"--out（{out_path}）が入力 {label}（{other}）と同じ実体を指している。"
            "このまま実行すると common.fresh_sqlite が入力を消してから ATTACH に"
            "失敗し、b05/b08 の正しい出力が失われる。--out に別のパスを指定すること。"
        ),
    )


# 地点/流域IDの「古さ」検査（コードレビュー指摘4。scripts/b08_project_occurrence_v1.py
# の `_assert_no_stale_taxon_ids` と同じ流儀）: `site_var`/`landuse_watershed`
# （b05）・`org_watershed`（b08）が「今の registry.sqlite」に対して作られたもの
# であることを確認する。古いままだと、該当する流域/地点が watershed_rollup の
# LEFT JOIN・相関サブクエリで**黙って** 0/減少して現れる（org_n=0 になる、
# site_var_n が実際より少なくなる等）——行数は変わらないので `_assert_rollup_
# prerequisites`（テーブルの有無だけを見る）では検出できない。
_STALE_ID_REBUILD_GUIDANCE = {
    "site_var": "scripts/b05_project_v1.py",
    "landuse_watershed": "scripts/b05_project_v1.py",
    "org_watershed": "scripts/b08_project_occurrence_v1.py（実行順は b06 → b09 → b07 → b08）",
}


def _stale_id_count_sql(table_ref: str, id_column: str, source_id: str) -> str:
    """`table_ref`（ATTACH 済みのテーブル、例 `'proj.landuse_watershed'`）の
    `id_column`（distinct・NOT NULL）のうち、現在の registry の
    `place_source_ref(source_id=<source_id>)` に無い値の件数を数える SQL
    （`scripts/b08_project_occurrence_v1.py` の `_stale_taxon_count_sql` と
    同じ、LEFT JOIN で不一致を数える形）。
    """
    return f"""
    SELECT COUNT(*) FROM (
      SELECT DISTINCT {id_column} AS id FROM {table_ref} WHERE {id_column} IS NOT NULL
    ) d
    LEFT JOIN reg.place_source_ref ref
      ON ref.external_key = d.id AND ref.source_id = '{source_id}'
    WHERE ref.external_key IS NULL
    """


def _assert_no_stale_ids(conn, *, table_ref: str, id_column: str, source_id: str, context: str) -> None:
    stale = conn.execute(_stale_id_count_sql(table_ref, id_column, source_id)).fetchone()[0]
    if stale:
        rebuild = _STALE_ID_REBUILD_GUIDANCE[context]
        raise common.MigrationError(
            f"{table_ref}.{id_column} に、今の registry.sqlite の "
            f"place_source_ref(source_id='{source_id}') に無い値が{stale}件ある"
            f"（{table_ref} が構築された後に registry.sqlite が入れ替わった疑いがある）。"
            f"同じ registry.sqlite で {rebuild} を再実行してから watershed_rollup を"
            "作り直すこと。"
        )


def _assert_no_stale_watershed_or_site_ids(
    registry_db, v1_projection_db, v1_projection_occurrence_db
) -> None:
    """`site_var`/`landuse_watershed`（b05）・`org_watershed`（b08）の
    site_id/watershed_id が、今の `registry.sqlite` に実在することを
    確かめる（コードレビュー指摘4）。出力ファイルには一切触れない読み取り
    専用の一時コネクションで、書き込みの前に確かめる。
    """
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, registry_db, "reg")
        common.attach_readonly(work, v1_projection_db, "proj")
        common.attach_readonly(work, v1_projection_occurrence_db, "occ")
        _assert_no_stale_ids(
            work, table_ref="proj.site_var", id_column="site_id",
            source_id="sites.site_id", context="site_var",
        )
        _assert_no_stale_ids(
            work, table_ref="proj.landuse_watershed", id_column="watershed_id",
            source_id="watershed_meta.watershed_id", context="landuse_watershed",
        )
        _assert_no_stale_ids(
            work, table_ref="occ.org_watershed", id_column="watershed_id",
            source_id="watershed_meta.watershed_id", context="org_watershed",
        )
    finally:
        work.close()


def _assert_rollup_input_fingerprints_fresh(
    v1_projection_db, v1_projection_occurrence_db, cube_db=None,
) -> dict[str, str]:
    """`site_var`/`landuse_watershed`（b05）・`org_watershed`（b08）の内容が、
    それぞれの構築スクリプトが最後に記録した指紋と一致することを確認する
    （(a)。Issue #37 #1。`_assert_no_stale_watershed_or_site_ids` は
    watershed_id/site_id の**実在**だけを見るため、id 集合が変わらないまま
    値だけが変わった再構築は検出できない——指紋はその隙間を埋める）。

    **(b) 系譜チェック（コードレビュー指摘の穴埋め）**: (a) だけでは
    「site_var 自身は無傷だが、その系譜先（`observation_agg`）が作り直された
    後 b05 が再実行されていない」壊れ方（b03/b04 だけ再実行して b05 を
    忘れる）を検出できない。`site_var`/`landuse_watershed` の系譜
    （`inputs["observation_agg"]`）・`org_watershed` の系譜
    （`inputs["occurrence"]`/`inputs["occurrence_place"]`）を、`cube_db`
    （`v2.sqlite`）に ATTACH した `observation_agg`/`occurrence`/
    `occurrence_place` 自身の自己指紋（生データは読まない安い参照）と
    突き合わせる。

    **検証範囲の明示（コードレビュー指摘への回答）**: `cube_db` が渡され、
    かつファイルが実在する場合だけ ATTACH して (b) を有効にする——
    watershed_rollup の SQL 自体は v2.sqlite を一切読まない設計
    （モジュール docstring「経由しない」）を保つため、`cube_db` を必須の
    ATTACH にはしない。`cube_db` が無い/渡されない場合は (b) を行わず
    (a) だけに留める（`main()` は常に既定パス `DEFAULT_CUBE_DB` を渡すため、
    Phase B を実行順どおり通した実運用では常に (b) も効く。`cube_db` 無しで
    呼ぶのは、v2.sqlite を必要としない既存の単体テストのため）。

    出力ファイルには一切触れない読み取り専用の一時コネクションで、
    `common.fresh_sqlite(out_path)`（既存の出力を即座に消す）より前に行う
    （`_assert_no_stale_watershed_or_site_ids` と同じ位置づけ）。戻り値は
    (a) で確認した3テーブルの現在の指紋（呼び出し側が `watershed_rollup` の
    系譜に使う）。
    """
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, v1_projection_db, "proj")
        common.attach_readonly(work, v1_projection_occurrence_db, "occ")
        cube_attached = cube_db is not None and pathlib.Path(cube_db).exists()
        if cube_attached:
            common.attach_readonly(work, cube_db, "cube_v2")
        # "observation" は b05 が `observation_agg` 経由の系譜（`site_var` の
        # inputs から `observation_agg` を辿った先）だけでなく、`site_var`
        # 自身の inputs にも直接持たせている（b05 側の /code-review 対応
        # ——`cube.observation` を直接読む表の inputs に observation 自身も
        # 含めた）。両方の経路から解決できるよう明示しておく（無いと、
        # `site_var.inputs["observation"]` を直接たどる1段目では `schema`
        # の既定値〔`table` 自身と同じ "proj"〕にフォールバックしてしまい、
        # 実在しない `proj.observation` を探して壊れる——実測で踏んだ）。
        upstream_schemas = (
            {
                "observation_agg": "cube_v2", "observation": "cube_v2",
                "occurrence": "cube_v2", "occurrence_place": "cube_v2",
            }
            if cube_attached else None
        )
        site_var_fp = common.assert_stage_fingerprint_fresh(
            work, "site_var", schema="proj",
            rebuild_hint="scripts/b05_project_v1.py を再実行すること。",
            upstream_schemas=upstream_schemas,
        )
        landuse_watershed_fp = common.assert_stage_fingerprint_fresh(
            work, "landuse_watershed", schema="proj",
            rebuild_hint="scripts/b05_project_v1.py を再実行すること。",
            upstream_schemas=upstream_schemas,
        )
        org_watershed_fp = common.assert_stage_fingerprint_fresh(
            work, "org_watershed", schema="occ",
            rebuild_hint=(
                "scripts/b08_project_occurrence_v1.py を再実行すること"
                "（実行順は b06 → b09 → b07 → b08）。"
            ),
            upstream_schemas=upstream_schemas,
        )
        return {
            "site_var": site_var_fp,
            "landuse_watershed": landuse_watershed_fp,
            "org_watershed": org_watershed_fp,
        }
    finally:
        work.close()


def build_projections(
    registry_db,
    out_path,
    *,
    v1_projection_db=DEFAULT_V1_PROJECTION_DB,
    v1_projection_occurrence_db=DEFAULT_V1_PROJECTION_OCCURRENCE_DB,
    cube_db=None,
) -> dict[str, int]:
    """`registry_db`・`v1_projection_db`・`v1_projection_occurrence_db` を検証
    してから `data/db/v1_projection_place.sqlite` に `watershed_meta`・
    `watershed_rollup` を書き、テーブルごとの行数を返す（ログ表示用）。

    `watershed_rollup` は `SUM(area_km2)` を6つ使う（土地利用の相関サブクエリ）
    ため、先頭で `common.require_sqlite_version()` を呼ぶ（コードレビュー
    指摘2。`scripts/b04_build_cube.py`/`scripts/b05_project_v1.py` 等と同じ
    位置・同じ理由。モジュール読み込み時点では呼ばない——古い環境で `import`
    した瞬間に落ちて `pytest` の収集自体が止まる事故を避ける）。

    検証が1つでも失敗すれば `out_path` には一切触れない（前回の正しい出力が
    残る。モジュール docstring参照）。`_validate_registry`/
    `_assert_rollup_prerequisites`/`_assert_out_path_distinct_from_inputs`/
    `_assert_no_stale_watershed_or_site_ids`/`_assert_rollup_input_fingerprints_fresh`
    はどれも出力ファイルに一切触れない読み取り専用の検証で、
    `common.fresh_sqlite(out_path)`（既存の出力を即座に消す）より前にすべて終える。
    """
    common.require_sqlite_version()
    _validate_registry(registry_db)
    _assert_rollup_prerequisites(v1_projection_db, v1_projection_occurrence_db)
    _assert_out_path_distinct_from_inputs(out_path, v1_projection_db, v1_projection_occurrence_db)
    _assert_no_stale_watershed_or_site_ids(registry_db, v1_projection_db, v1_projection_occurrence_db)
    verified_fingerprints = _assert_rollup_input_fingerprints_fresh(
        v1_projection_db, v1_projection_occurrence_db, cube_db,
    )

    work = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(work, registry_db, "reg")
        common.attach_readonly(work, v1_projection_db, "proj")
        common.attach_readonly(work, v1_projection_occurrence_db, "occ")

        work.execute(_CREATE_WATERSHED_META_SQL)
        work.execute(_INSERT_WATERSHED_META_SQL)

        # site_watershed_lookup の一意性は _validate_registry() で検証済み
        # （コードレビュー指摘1）。CREATE UNIQUE INDEX は無い——2つの相関
        # サブクエリ（site_n/site_var_n）はどちらも watershed_id で絞るので
        # site_id の索引は実測で参照されない（コードレビュー指摘13）。
        work.execute(_CREATE_SITE_WATERSHED_LOOKUP_SQL)

        work.execute(_CREATE_WATERSHED_ROLLUP_SQL)

        # 段階間の指紋（Issue #37 #1）: 全段の出力に指紋を持たせる方針どおり、
        # このファイルの2テーブル両方に記録する（現時点でこれらを読む後続の
        # 段は無いが、将来のために一貫して記録する）。`watershed_rollup` には
        # 系譜（`_assert_rollup_input_fingerprints_fresh` が (a) で確認済みの
        # site_var/landuse_watershed/org_watershed の指紋）も添える。
        common.record_stage_fingerprint(work, "watershed_meta")
        common.record_stage_fingerprint(work, "watershed_rollup", inputs=verified_fingerprints)

        work.commit()
        n_meta = work.execute("SELECT COUNT(*) FROM watershed_meta").fetchone()[0]
        n_rollup = work.execute("SELECT COUNT(*) FROM watershed_rollup").fetchone()[0]
    finally:
        work.close()
    return {"watershed_meta": n_meta, "watershed_rollup": n_rollup}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument(
        "--v1-projection-db",
        default=str(DEFAULT_V1_PROJECTION_DB),
        help="watershed_rollup が読む site_var/landuse_watershed（scripts/b05_project_v1.py の出力）",
    )
    parser.add_argument(
        "--v1-projection-occurrence-db",
        default=str(DEFAULT_V1_PROJECTION_OCCURRENCE_DB),
        help="watershed_rollup が読む org_watershed（scripts/b08_project_occurrence_v1.py の出力）",
    )
    parser.add_argument(
        "--cube-db",
        default=str(DEFAULT_CUBE_DB),
        help=(
            "段階間の指紋の系譜チェック専用（Issue #37 #1）。site_var/landuse_watershed/"
            "org_watershed が今の observation_agg/occurrence/occurrence_place から作られたかを"
            "確かめるためだけに ATTACH する（watershed_rollup の SQL 自体はこのファイルを"
            "読まない）。無い/存在しない場合は (b) の系譜チェックだけを省略して続行する。"
        ),
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step(f"v1 形へ射影して {args.out} に書き出し") as info:
        counts = build_projections(
            registry_db,
            args.out,
            v1_projection_db=args.v1_projection_db,
            v1_projection_occurrence_db=args.v1_projection_occurrence_db,
            cube_db=args.cube_db,
        )
        info["n"] = sum(counts.values())

    for table, n in sorted(counts.items()):
        print(f"  {table}: {n:,}行")


if __name__ == "__main__":
    main()
