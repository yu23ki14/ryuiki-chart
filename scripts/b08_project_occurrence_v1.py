#!/usr/bin/env python3
"""`occurrence`（L2）・`occurrence_agg`（キューブ。b07）・`occurrence_place`
（O-2a、b09）から v1 の12テーブル（`org_norm`・年キー8表・`species_month`・
`org_watershed_year`/`org_watershed`）に射影する（ADR-0016 Phase B
「ファクトとキューブ」O-1a/O-1b/O-2a。O-1 設計 v2 D3・D4・ADR-0025 D3・
ADR-0026。番号 b07 は O-1b のキューブ用だった）。

    .venv/bin/python3 scripts/b08_project_occurrence_v1.py

`data/db/v1_projection_occurrence.sqlite`（毎回ゼロから作り直す、専用の出力
ファイル。b05 の `v1_projection.sqlite` とは別ファイル——D3参照）に12テーブル
（`org_norm`・`org_group_year`・`effort_year`・`species2`・`species_year2`・
`species_month`・`mesh_year`・`mesh_all`・`mesh_species`・`species_mesh_year`・
`org_watershed_year`・`org_watershed`）を書く。列名・列順は
`reports/derived_baseline.json`／実物の `data/db/derived.sqlite`
（`PRAGMA table_info`）と一致させてある（`scripts/b02_derived_compare.py
--candidate ... --tables ...` がそのまま突き合わせられるように）。**`b02` 自身は
列名で `SELECT` するため列順・宣言型を見ないが**（`scripts/reconcile/datasource.py`
の `fetch_rows` 参照）、この12表のスキーマは v1（`derived.sqlite`）の実物と
そろえてある（コードレビュー指摘8。`org_norm` は O-1a のまま——本 PR では
一切変更していない）。**実行順は b06 → b09 → b07 → b08**（`org_watershed_year`/
`org_watershed` は `occurrence`/`occurrence_place` だけに依存し、`occurrence_agg`
は使わない——`b07` を経由しない独立した射影）。

## O-2a: `org_watershed_year`/`org_watershed`（`occurrence` + `occurrence_place` から）

v1（`web/scripts/build-geo.mjs:112-225`）は座標を0.001度に丸めたバケットで
点内包判定の結果をメモ化し、走査順（≒rowid順）に依存する近似で流域を割り当てる
（`docs/plans/PHASE_B_OCCURRENCE.md` F3）。詳細な式・機械検証は本ファイル下方の
「O-2a」セクションのコメント・ADR-0026 参照。ここでは要点だけ:

- v1 の癖は**射影の式**（このファイル）だけに閉じている。`occurrence_place`
  （O-2a、b09）自体は v1 の割当を一切焼き込まない、正確な点内包判定の結果
  （ADR-0024/0025 と同じ「v1 の癖はキューブ/レジストリに焼き込まない」原則）。
- メモ方式と「記録自身の正確な結果」の食い違いを記録単位で実測し、宣言
  （`scripts/migrate/occurrence_watershed_v1_declarations.yaml`）と突き合わせる
  ——キー1件ずつの宣言済み差分（`scripts/reconcile/expected_diffs.yaml`）には
  **しない**（1,091件のキーを列挙してもレビューできるゴミ箱にしかならない）。

## O-1a: `org_norm`（`occurrence`＝L2 から）

設計・規則は変更なし（`_build_org_norm`/`build_org_norm_projection`。旧版の
振る舞いをそのまま維持——値は1ビットも変えない）。射影の規則は
`_ORG_NORM_SELECT_EXPRS` の直前にまとめてある。

## O-1b: 年キー8表は `occurrence_agg`（キューブ）だけから（ADR-0025 D3）

`org_group_year`/`effort_year`/`species2`/`species_year2`/`mesh_year`/
`mesh_all`/`mesh_species`/`species_mesh_year` は **`occurrence_agg` だけ**から
作る（`occurrence`（L2）を読まない。例外は `species2.en_name`/
`red_list_category` だけ——後述）。

- **`occurrence_agg.place_kind = 'grid01'` に明示的に絞る**（`place_kind`
  を鍵に持つ理由・O-2 との関係は ADR-0025 D2 参照。この8表は mesh
  〔`mlat`/`mlon`〕前提のため、`'watershed'` 等の他の `place_kind` は対象外
  にする。既知の値〔`'grid01'`/`'watershed'`〕以外なら
  `_assert_known_place_kinds` が止める）。
- **v1 の「年」はキューブのセルの `period_start` から**: `CAST(substr(period_start,1,4)
  AS INT)`。`year` セルも `survey_period`（leaf）セルも同じ式（year セルは
  `period_start` が暦年境界へ丸め済み、leaf セルは記録自身の区間の開始その
  ものなので、どちらも「その記録の開始年」を表す。ADR-0025 D3）。
- `binom`/`taxon_group`/`cls`/`family` は `occurrence_agg.taxon_id` →
  `registry.taxon` の JOIN（`taxon_id` が NULL の系列は `binom=NULL`・
  `taxon_group` は既定ラベル。`org_norm` と同じ規則）。
- `mlat`/`mlon` は `occurrence_agg.place_id` → `place_source_ref`
  （`source_id='organism_records.lat_lon'`）の外部キー（`'grid01:<mlat>,<mlon>'`）
  から復元する（`place_mesh_lookup`。`registry/build_place.py` が
  `CAST(FLOOR(lat*100) AS INT)` と同じ式で作った値そのものなので、`org_norm`
  の `mlat`/`mlon` と一致する）。`place_id` があるのに `place_mesh_lookup` で
  解決できないセルは黙って `mlat=NULL` にせず止める
  （`_assert_all_places_resolve_to_mesh`。コードレビュー指摘4）。
- `n`（記録数）は加法なので `SUM(occurrence_agg.n)` で正確。`COUNT(DISTINCT
  binom)`/`COUNT(DISTINCT mlat||'_'||mlon)` のような DISTINCT も、キューブが
  記録の分割（同じ記録が複数セルにまたがらない）であるため、粗いキー
  （`year`/`taxon_group`/`mlat,mlon` 等）で再度 `GROUP BY` した集合の上で
  正確に計算できる（複数の `taxon_id` が同じ `binom` に対応する場合も、
  `GROUP BY ... binom` で自然に1つに畳まれる——`species_mesh_year`/
  `mesh_species` のテスト参照）。
- **例外**: `species2.en_name`（`MAX(COALESCE(NULLIF(vernacular_name,''),''))`）
  と `red_list_category`（`MAX(COALESCE(red_list_category,''))`）は
  `occurrence`（L2）の記録の原表記から binom ごとに集計する
  （`occurrence_agg` は `vernacular_name`/`red_list_category` の原表記を
  セル単位で持たない——`n_red_list` という「非空かどうかの集計値」しか
  持たないため。O-1 設計 v2 D3 に明記）。

## O-1b: `species_month` は `occurrence`（L2）から直接（D10 の4例目）

v1 の `mo`（月の格）は `occurrence_agg` の `grain`（`year`/`survey_period`）の
語彙で表せない集計軸——`docs/plans/PHASE_B_FACT_SLICE.md` D10「climatology
相当の軸はキューブのセルにしない」の4例目（`sensor_hour_month` と同じ
先例）。`yr`/`mo` は `org_norm` と同じ規則（`period_raw` から）。`n>=80` の
判定には射影済みの `species2`（キューブから作った本物の出力テーブル）を
そのまま使う。

`species2.en_name`/`red_list_category`（上の例外）と `species_month` は
どちらも `occurrence`（L2、816,856行）を taxon で JOIN した同じ形の中間結果
（binom/yr/mo/vernacular_name/red_list_category）を必要とするため、
`l2_taxon_enriched`（1回の走査）に一本化してある——別々に2回 L2 をフル
スキャンしない（コードレビュー指摘10）。`species_month` はこの
`l2_taxon_enriched`（816,856行）からさらに温存テーブルを作らず、
`INSERT ... SELECT ... WHERE` で直接絞り込んで書く（`species_month` 自体は
9,997行しかない。816,856行のテーブルをもう1つ余分に作らない）。

## テーブルごとのフィルタは射影側（キューブには無い）

`yr BETWEEN 1970 AND 2026`（`org_group_year`/`effort_year`/`species_year2`/
`mesh_year`/`species_mesh_year`）・`species2.n >= 80`（全年・全記録。
`species_mesh_year`/`species_month` が使う）は、v1 の SQL 自体がそう書いて
いる（`web/scripts/build-biota.mjs`）ので、ここでも `_build_cube_projections`
の SQL 側に同じ形で書く。**`mesh_year`/`mesh_species` の座標フィルタは
v1 で扱いが違う**（以前のここの記述は誤り——両方に `lat IS NOT NULL` 相当が
あると書いていたが、`mesh_species` は v1 の SQL に一切フィルタが無い）:

- `mesh_year` は v1 の `WHERE lat IS NOT NULL` に相当する条件を持つ
  （キューブ側には `lat` が無いので `place_id IS NOT NULL`——「座標を持つ
  記録か」を表す。`_assert_all_places_resolve_to_mesh` が通っていれば
  `place_id IS NOT NULL ⟺ mlat IS NOT NULL` だが、意味としては
  `place_id`（座標の有無）で書く）。
- `mesh_species` は v1 のとおり **WHERE なし**（座標の無い記録があれば
  `(mlat, mlon) = (NULL, NULL)` の行がそのまま出る。実データでは座標が
  常にあるため現れない）。
- `species2` 自体・`mesh_all` には年フィルタが無い（v1 のとおり。`mesh_all`
  は年フィルタ済みの `mesh_year` から積み上げるので結果的に年範囲は同じだが、
  `mesh_species` は年フィルタも座標フィルタも無く本当に全期間・全記録を
  対象にする——`docs/plans/PHASE_B_OCCURRENCE.md` O-1b 節の実測
  「mesh_all と mesh_species の件数が3件違う」参照）。

## キューブが「今の occurrence の分割」であることを確かめてから使う（コードレビュー指摘2）

`occurrence_agg`（`v2.sqlite`）と `occurrence`（同じファイルだが b06/b07 は
別々に実行しうる）が食い違っている——例えば `occurrence` を b06 で作り直した
のに `occurrence_agg` を b07 で再構築し忘れた——状態を、年キー8表を作る前に
検出する（`_assert_cube_is_current_l2_partition`）。`occurrence_agg.grain` が
`{'year','survey_period'}` 以外を含んでいないこと、系列（source_id, taxon_id）
ごとの `SUM(occurrence_agg.n)` が `occurrence`（L2、日付あり行）の件数と
一致することを確認し、食い違えば「scripts/b06_build_occurrence.py の後に
scripts/b07_build_occurrence_cube.py を再実行すること」と案内して止める
（段階間の検証の最初の1本）。**これが通っていれば、`occurrence_agg.taxon_id`
は `occurrence.taxon_id` の部分集合であることが保証される**——`org_norm`
（`_build_org_norm`）が既に `occurrence.taxon_id` 全体の新鮮さを検証済みなら、
`occurrence_agg.taxon_id` の新鮮さは推移的に保証されるため、
`build_all_projections`（`org_norm` を先に作ってから年キー8表を作る）では
`occurrence_agg` に対する古い taxon 検査を重ねがけしない
（`_build_cube_projections(..., check_stale_taxon=False)`）。単独で
年キー8表だけを作る `build_occurrence_cube_projections`（テスト・単体検証用）
はこの前提を持たないため、既定で古い taxon 検査を行う。

## SQLite の版（年キー8表の経路は3.43以降が前提。コードレビュー指摘）

`_assert_cube_is_current_l2_partition`（上記）が呼ぶ
`scripts/migrate/common.assert_grouped_totals_match` は `FULL OUTER JOIN`
（SQLite 3.39 で追加）を使うため、それより古い版では `sqlite3.
OperationalError: RIGHT and FULL OUTER JOINs are not currently supported`
で落ちる（実測。古い `sqlite3` CLI 3.37.2 で確認済み）。年キー8表・
`species_month` を作る経路（`build_occurrence_cube_projections`/
`build_all_projections`）の先頭で `common.require_sqlite_version()`
（b04・b05・b07・b10 と共有するガード）を呼ぶ——`FULL OUTER JOIN` 自体が
要求する最小版（3.39）ではなく、`AVG()`/`SUM()` を使う他のスクリプトと同じ
**3.43 で統一**する（`scripts/b07_build_occurrence_cube.py` のモジュール
docstring と同じ理由。パイプライン全体を1つの基準で揃える）。
`org_norm` だけを作る `build_org_norm_projection` は `occurrence_agg`
（したがって `FULL OUTER JOIN`）を一切使わないため、このガードを呼ばない
（実際に古い SQLite でも動く。`test_b08_project_occurrence_v1.py` は
バージョンでスキップしない）。

## 前提（入力テーブル）を出力ファイルを消す前に確かめる（コードレビュー指摘6）

`common.fresh_sqlite(out_path)` は既存の `out_path` を即座に削除する。以前は
これを呼んだ**後**で `cube_db`/`registry_db` を ATTACH していたため、
`occurrence_agg` が無い `v2.sqlite`（b07 をまだ実行していない）を渡すと、
素の `sqlite3.OperationalError`（`no such table: occurrence_agg`）で落ちる
前に前回の出力が消え、空の `org_norm` だけが残った状態になっていた。
`_assert_prerequisites` が `fresh_sqlite` の**前**に、`cube_db`/`registry_db`
の存在と必要なテーブル（`occurrence`/`occurrence_agg`/`taxon`）の有無を
読み取り専用で確かめ、無ければ「b06/b07 を先に実行すること」と案内する
`MigrationError` で止める。

## 古い registry を検出する（コードレビュー指摘7。O-1a から踏襲・文脈ごとに案内を変える）

`occurrence.taxon_id`/`occurrence_agg.taxon_id` は構築時点の `registry.taxon`
に実在することを検証済みだが、`v2.sqlite` と `registry.sqlite` は別々に
作り直せるファイルなので、古い `registry.sqlite`（taxon が入れ替わった・
減った版）に対して実行すると検出漏れが起きうる。`_assert_no_stale_taxon_ids`
が `occurrence`/`occurrence_agg` それぞれの `taxon_id` の distinct 値を
`registry.taxon` と突き合わせ、食い違えば書き込みの前に止める——メッセージは
文脈（`occurrence` なら b06 の再実行、`occurrence_agg` なら b06 の後に b07 の
再実行）ごとに正しいスクリプト名を案内する。

## 書き込みは `INSERT ... SELECT`（コードレビュー指摘8・10。O-1a から踏襲）

`org_norm` と同様、年キー8表・`species_month` も出力ファイルへ書き込み用に
開いた1つの接続に `cube`/`reg` を ATTACH し、`INSERT INTO <table> (<列名>)
SELECT ...` を実行する（Python 側に行のリストを保持しない）。
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import b07_build_occurrence_cube as b07  # noqa: E402  (GRAIN_VALUES を共有する。/simplify 指摘5)
from migrate import common, period  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_TAXON_GROUP_YAML = ROOT / "registry" / "taxon" / "taxon_group.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_occurrence.sqlite"
DEFAULT_WATERSHED_DECLARATIONS_YAML = (
    ROOT / "scripts" / "migrate" / "occurrence_watershed_v1_declarations.yaml"
)

_SAMPLE_LIMIT = 20


# ---------------------------------------------------------------------------
# 前提の確認（出力ファイルを消す前に。コードレビュー指摘6）
# ---------------------------------------------------------------------------

def _existing_tables(db_path) -> set[str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def _assert_prerequisites(
    cube_db, registry_db, *, need_occurrence_agg: bool, need_occurrence_place: bool = False,
) -> None:
    """`cube_db`/`registry_db` が存在し、必要なテーブルを持つことを
    `common.fresh_sqlite(out_path)`（既存の出力を即座に消す）より前に
    確かめる。無ければ「先に何を実行すべきか」を案内して止める
    （コードレビュー指摘6。以前は出力を消した後で ATTACH に失敗し、
    生の `OperationalError` と空の `org_norm` だけが残っていた）。

    `need_occurrence_place`（O-2a、`org_watershed`/`org_watershed_year` の
    射影が要る）は `occurrence_place`（`scripts/b09_build_occurrence_place.py`
    が作るサテライト表）の有無も確かめる。
    """
    cube_path = pathlib.Path(cube_db)
    if not cube_path.exists():
        needed = "scripts/b06_build_occurrence.py"
        if need_occurrence_place:
            needed += " の後に scripts/b09_build_occurrence_place.py"
        if need_occurrence_agg:
            needed += " の後に scripts/b07_build_occurrence_cube.py"
        raise common.MigrationError(f"{cube_path} が無い。先に {needed} を実行すること。")

    registry_path = pathlib.Path(registry_db)
    if not registry_path.exists():
        raise common.MigrationError(
            f"{registry_path} が無い。先に scripts/r01_build_registry.py を実行すること。"
        )

    cube_tables = _existing_tables(cube_path)
    missing = []
    if "occurrence" not in cube_tables:
        missing.append(("occurrence", "scripts/b06_build_occurrence.py"))
    if need_occurrence_agg and "occurrence_agg" not in cube_tables:
        missing.append(("occurrence_agg", "scripts/b07_build_occurrence_cube.py"))
    if need_occurrence_place and "occurrence_place" not in cube_tables:
        missing.append(("occurrence_place", "scripts/b09_build_occurrence_place.py"))
    if missing:
        names = "・".join(f"`{n}`" for n, _ in missing)
        scripts = "・".join(dict.fromkeys(s for _, s in missing))  # 順序を保って重複除去
        raise common.MigrationError(
            f"{cube_path} に {names} テーブルが無い。先に {scripts} を実行すること。"
        )

    if "taxon" not in _existing_tables(registry_path):
        raise common.MigrationError(
            f"{registry_path} に `taxon` テーブルが無い。scripts/r01_build_registry.py を"
            "実行すること。"
        )


# ---------------------------------------------------------------------------
# 古い registry の検出（O-1a のコードレビュー指摘7を一般化。`table` は
# `cube.occurrence`/`cube.occurrence_agg` のどちらでも使う。メッセージは
# 文脈ごとに正しい再実行手順を案内する——コードレビュー指摘7）。
# ---------------------------------------------------------------------------

_REBUILD_GUIDANCE_BY_CONTEXT = {
    "occurrence": "scripts/b06_build_occurrence.py",
    "occurrence_agg": "scripts/b06_build_occurrence.py の後に scripts/b07_build_occurrence_cube.py",
}


def _stale_taxon_count_sql(table: str) -> str:
    return f"""
    SELECT COUNT(*) FROM (
      SELECT DISTINCT taxon_id FROM {table} WHERE taxon_id IS NOT NULL
    ) d
    LEFT JOIN reg.taxon t ON t.taxon_id = d.taxon_id
    WHERE t.taxon_id IS NULL
    """


def _assert_no_stale_taxon_ids(conn, table: str, context: str) -> None:
    """`table`（`cube.occurrence`/`cube.occurrence_agg`）の `taxon_id`
    （distinct 値）が現在の `reg.taxon` に実在することを確認する。古い
    registry を検出する（コードレビュー指摘7）。
    """
    stale = conn.execute(_stale_taxon_count_sql(table)).fetchone()[0]
    if stale:
        rebuild = _REBUILD_GUIDANCE_BY_CONTEXT[context]
        raise common.MigrationError(
            f"registry.taxon に無い taxon_id が{stale}種ある"
            f"（{context}.taxon_id は NULL ではないのに、registry 側にその taxon が無い＝"
            f"{context} 構築後に registry.sqlite が taxon を含まない版に入れ替わった疑いがある）。"
            f"同じ registry.sqlite で {rebuild} を再実行するか、registry.sqlite を"
            "作り直してから再実行すること。"
        )


def _load_default_taxon_group(path=DEFAULT_TAXON_GROUP_YAML) -> str:
    """`registry/taxon/taxon_group.yaml` の `default_label_ja` を読む
    （taxon_id が NULL の行の `taxon_group` に使う。リテラルを書かない）。
    """
    doc = common.load_yaml(path)
    return doc["default_label_ja"]


# ---------------------------------------------------------------------------
# O-1a: org_norm（occurrence＝L2 から）。設計・実装は変更なし。
# ---------------------------------------------------------------------------

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

# 射影の規則（D3。実データで検証済み——docs/plans/PHASE_B_OCCURRENCE.md 参照。
# O-1a から変更なし）:
#
# - `binom`/`rank_l`/`cls`/`kdm`/`phy`/`ord`/`family` は **taxon の属性**
#   （`occurrence.taxon_id` → `registry.taxon` を引く。taxon_id が NULL なら
#   全部 NULL）。v1 の記録ごとの多数決 COALESCE 補完は、taxon レジストリの
#   ビルド時（Phase B `phase-b/occurrence-registry`）に taxon 単位へ移して
#   あるため、ここでは単純な JOIN で足りる（実データで検証: 816,856行中
#   binom/rank_l/kdm/phy/ord/family は不一致0、cls は Sirosporium celtidis の
#   1件だけ宣言済み差分——`scripts/reconcile/expected_diffs.yaml` 参照）。
#   `rank_l` は taxon の属性（`registry.taxon.rank`。build_taxon.py が組み立て
#   時に既に小文字化して持つ）から取る——「記録の原表記を lower() するだけ」
#   ではない（design v2 D3 の「taxon の属性から取る」という原則どおり）。
# - `taxon_group` は `COALESCE(taxon.taxon_group, default_label_ja)`
#   （`registry/taxon/taxon_group.yaml` の既定ラベルを読む。リテラルを
#   書かない。taxon_id が NULL の775行はこの既定に落ちる）。
# - `scientific_name`/`vernacular_name`/`red_list_category`/`license_class`/
#   `is_alien` は **記録の原表記**（`occurrence` の F6 列）。
# - `yr`/`mo` は **`period_raw` から v1 の式をそのまま**適用する
#   （`yr=CAST(substr(period_raw,1,4) AS INT)`、`mo` は
#   `length(period_raw)>=7` のとき `CAST(substr(period_raw,6,2) AS INT)`。
#   `YYYY/YYYY` 区間ではこの式が「月」ではない値（18/19/20）を返すが、
#   これは v1 の癖でありここで直さない——v1 の org_norm と1ビットも変えない
#   ための意図的な再現）。`period_start`/`period_end`（区間の展開結果）では
#   なく `period_raw`（原表記）を使う点に注意——**この式は年キー8表が使う
#   キューブの `period_start`（暦年境界に丸めた値）とは別物**。年キー8表の
#   「年」は `occurrence_agg.period_start` から作り（モジュール docstring
#   O-1b 節参照）、`org_norm` の `yr`/`mo` は `occurrence.period_raw`
#   （原表記そのもの）から作る——同じ「年」でも出どころが違う。
# - `mlat`/`mlon` は `CAST(FLOOR(lat*100) AS INT)`（v1 と同じ IEEE 演算。
#   SQLite の `CAST(FLOOR(...))` を直接使う——Python 側で計算し直さない）。
# - 対象は `occurrence.period_raw IS NOT NULL`（v1 org_norm の母集団
#   `observed_on IS NOT NULL AND length(observed_on)>=4` と同値——occurrence
#   の観測日が NULL でない行は全て length>=4 であることを実測で確認済み）。
#   行数は816,856（v1 org_norm と一致）。
#
# `_ORG_NORM_COLUMNS` と同じ順で SELECT 側の式を書く（列名を明示した
# `INSERT INTO org_norm (<列名>) SELECT <式> ...` の <式> 部分）。
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


def _build_org_norm_insert_sql() -> str:
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


def _build_org_norm(conn, default_taxon_group: str) -> int:
    """`conn`（`cube`/`reg` を ATTACH 済みの書き込み用接続）に `org_norm` を
    作り、行数を返す。O-1a の実装からロジックは変更していない
    （`build_org_norm_projection` が自前で開いていた接続を、複数テーブルを
    1つのファイルに書く `build_all_projections` とも共有できるように
    切り出しただけ）。**この呼び出しが `occurrence.taxon_id` 全体の新鮮さを
    検証するため、`build_all_projections` が `_build_org_norm` を先に呼べば、
    後続の `_build_cube_projections` は `occurrence_agg` に対する同じ検査を
    重ねがけしなくてよい**（モジュール docstring「キューブが『今の
    occurrence の分割』であることを確かめてから使う」参照）。
    """
    _assert_no_stale_taxon_ids(conn, "cube.occurrence", "occurrence")
    conn.execute(_CREATE_ORG_NORM_SQL)
    conn.execute(_build_org_norm_insert_sql(), {"default_taxon_group": default_taxon_group})
    return conn.execute("SELECT COUNT(*) FROM org_norm").fetchone()[0]


def build_org_norm_projection(
    cube_db, registry_db, out_path, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
) -> dict:
    """`occurrence`（L2）から `org_norm` だけを単独で `out_path` に書く
    （`fresh_sqlite` で毎回作り直す。既存テスト・単体検証用のエントリ
    ポイント——`main()` は10テーブルまとめて書く `build_all_projections` を
    使う）。戻り値は `{"n": 行数}`。

    `FULL OUTER JOIN`（`assert_grouped_totals_match`）を使わないため、ここでは
    `common.require_sqlite_version()` を呼ばない（モジュール docstring
    「SQLite の版」参照。年キー8表側の経路とは異なり、このエントリポイントは
    実際に古い SQLite でも動く）。
    """
    _assert_prerequisites(cube_db, registry_db, need_occurrence_agg=False)
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        n = _build_org_norm(conn, default_taxon_group)
        conn.commit()
        return {"n": n}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# O-1b: 年キー8表（occurrence_agg だけから）＋ species_month（occurrence＝L2 から）
# ---------------------------------------------------------------------------

# grain の語彙は b07 の `GRAIN_VALUES` を正として import する（/simplify
# 指摘5。以前は b07・b08 それぞれが `'year', 'survey_period'` を直書きして
# いて、O-2 で grain を足すときに2箇所を直す必要があった）。
_GRAIN_VALUES_SQL_LIST = ", ".join(repr(g) for g in b07.GRAIN_VALUES)
_GRAIN_VALUES_LABEL = "/".join(repr(g) for g in b07.GRAIN_VALUES)

# 年キー8表が対象にする place_kind（O-2 で 'watershed' が増える計画。
# `_assert_known_place_kinds`/`_OCC_AGG_ENRICHED_SQL` が参照する）。
_KNOWN_PLACE_KINDS = frozenset({"grid01", "watershed"})
_MESH_PLACE_KIND = "grid01"

# `occurrence_agg` が「今の occurrence の分割」であることの確認
# （コードレビュー指摘2。モジュール docstring参照）。`place_kind='grid01'`
# に明示的に絞る——O-2 で `place_kind='watershed'` のセルが
# `occurrence_agg` に増えても、grid01 の年キー8表がそれを二重に数えない
# ようにする（追加指示。ADR-0025 D2）。`watershed` セルは grid01 セルの
# ロールアップになる想定で、L2（`occurrence`）を record 単位で直接分割した
# ものではないため、この Σn 突合の対象外（grid01 だけが L2 の直接の分割）。
_L2_DATED_SERIES_TOTALS_SQL = f"""
SELECT source_id, taxon_id, COUNT(*) AS n
FROM cube.occurrence
WHERE period_raw IS NOT NULL AND place_kind = '{_MESH_PLACE_KIND}'
GROUP BY source_id, taxon_id
"""
_CUBE_SERIES_TOTALS_SQL = f"""
SELECT source_id, taxon_id, SUM(n) AS n
FROM cube.occurrence_agg
WHERE place_kind = '{_MESH_PLACE_KIND}'
GROUP BY source_id, taxon_id
"""


def _assert_known_place_kinds(conn) -> None:
    """`occurrence_agg.place_kind` が `_KNOWN_PLACE_KINDS`（`'grid01'`/
    `'watershed'`。O-2 で `'watershed'` を使う計画）以外の値を持たないことを
    確かめる。未知の place_kind を黙って `_MESH_PLACE_KIND` 絞り込みで
    捨てない——年キー8表が想定しない place_kind のセルを静かに無視して
    しまう事故を防ぐ（追加指示）。
    """
    bad = conn.execute(
        "SELECT DISTINCT place_kind FROM cube.occurrence_agg WHERE place_kind NOT IN "
        f"({', '.join(repr(p) for p in sorted(_KNOWN_PLACE_KINDS))})"
    ).fetchall()
    if bad:
        raise common.MigrationError(
            f"occurrence_agg: place_kind が想定外の値を持つ（{[r[0] for r in bad]}）。"
            f"既知の値は {sorted(_KNOWN_PLACE_KINDS)} だけ——新しい place_kind を足すなら、"
            "この検証と年キー8表の射影（このファイル）の両方を見直すこと。"
        )


def _assert_cube_is_current_l2_partition(conn) -> None:
    """`occurrence_agg` の grain が `b07.GRAIN_VALUES` 以外を含んでいない
    （新しい grain を黙って絞り込みで捨てない）こと、`place_kind` が既知の
    値だけであること、`place_kind='grid01'` に絞った系列
    （source_id, taxon_id）ごとの `SUM(occurrence_agg.n)` が `occurrence`
    （L2、日付あり行、同じく `place_kind='grid01'`）の件数と一致することを
    確認する。崩れていれば「b06 の後に b07 を再実行せよ」と案内して止める
    （コードレビュー指摘2）。比較そのものは SQL 側で行う
    （`common.assert_grouped_totals_match`。/simplify 指摘3——実測ではこの
    Python 側の突合だけで約2.4秒かかっていた）。
    """
    bad_grain = conn.execute(
        f"SELECT DISTINCT grain FROM cube.occurrence_agg WHERE grain NOT IN ({_GRAIN_VALUES_SQL_LIST})"
    ).fetchall()
    if bad_grain:
        raise common.MigrationError(
            f"occurrence_agg: grain が {_GRAIN_VALUES_LABEL} 以外の値を持つ（{[r[0] for r in bad_grain]}）。"
            "年キー8表の射影（このファイル）はこの2つの grain だけを前提にしているため、"
            "新しい grain を足すならこの検証と射影の両方を見直すこと。"
        )
    _assert_known_place_kinds(conn)

    common.assert_grouped_totals_match(
        conn, _L2_DATED_SERIES_TOTALS_SQL, _CUBE_SERIES_TOTALS_SQL,
        key_columns=["source_id", "taxon_id"],
        value_columns=["n"],
        build_message=lambda rows: (
            f"occurrence_agg: place_kind='{_MESH_PLACE_KIND}' に絞った系列（source_id, taxon_id）"
            "ごとの Σn が occurrence（L2、同じく grid01）と食い違う（occurrence_agg が「今の"
            " occurrence の分割」になっていない）。scripts/b06_build_occurrence.py の後に"
            " scripts/b07_build_occurrence_cube.py を再実行すること。"
            f"（例（上限{_SAMPLE_LIMIT}件、(source_id, taxon_id, n_l2, n_cube)）: {rows}）"
        ),
        sample_limit=_SAMPLE_LIMIT,
    )


# place_id -> (mlat, mlon)。`registry/build_place.py` が
# `CAST(FLOOR(lat*100) AS INT)` と同じ式で作った external_key
# （'grid01:<mlat>,<mlon>'）を読み戻す。'grid01:' は7文字なので数字は
# 8文字目から始まる。
_PLACE_MESH_LOOKUP_SQL = """
CREATE TEMP TABLE place_mesh_lookup AS
SELECT place_id,
       CAST(substr(external_key, 8, instr(external_key, ',') - 8) AS INT) AS mlat,
       CAST(substr(external_key, instr(external_key, ',') + 1) AS INT) AS mlon
FROM reg.place_source_ref
WHERE source_id = 'organism_records.lat_lon'
"""

# occurrence_agg のセルに taxon 属性（taxon_id 経由）・mesh 座標（place_id
# 経由）・v1 の「年」（period_start から）を載せた作業テーブル。年キー8表は
# すべてここから作る（`species2.en_name`/`red_list_category` を除く）。
# `place_id` 自体も残す——`_assert_all_places_resolve_to_mesh`（座標はある
# のに mesh が引けない事故の検出）と `mesh_year` の座標フィルタ
# （`place_id IS NOT NULL`。モジュール docstring 参照）に要る。
# **`WHERE c.place_kind = 'grid01'` で明示的に絞る**（追加指示。O-2 で
# `place_kind='watershed'` のセルが `occurrence_agg` に増えても、mesh 前提の
# 年キー8表（mlat/mlon を使う）がそれを二重に数えたり、watershed セルの
# `place_id` を grid01 用の `place_mesh_lookup` に誤って引かせたりしない
# ようにする）。
_OCC_AGG_ENRICHED_SQL = f"""
CREATE TEMP TABLE occ_agg_enriched AS
SELECT c.source_id, c.place_id,
       CAST(substr(c.period_start, 1, 4) AS INT) AS year,
       t.canonical_binomial AS binom,
       COALESCE(t.taxon_group, ?) AS taxon_group,
       t.class AS cls,
       t.family AS family,
       pm.mlat AS mlat,
       pm.mlon AS mlon,
       c.n AS n,
       c.n_red_list AS n_red_list
FROM cube.occurrence_agg c
LEFT JOIN reg.taxon t ON t.taxon_id = c.taxon_id
LEFT JOIN place_mesh_lookup pm ON pm.place_id = c.place_id
WHERE c.place_kind = '{_MESH_PLACE_KIND}'
"""


def _assert_all_places_resolve_to_mesh(conn) -> None:
    """`place_id` があるのに `place_mesh_lookup` で `mlat`/`mlon` が解決
    できないセルが無いことを確かめる（コードレビュー指摘4）。座標が無い
    記録（`place_id IS NULL`）は正常系（v1 の「座標なし」に対応）だが、
    `place_id` があるのに解決できないのは `place_mesh_lookup`
    （`place_source_ref(source_id='organism_records.lat_lon')`）が
    `occurrence_agg.place_id` の全体をカバーしていない異常——黙って
    `mlat=NULL` に落とさず止める。
    """
    bad = conn.execute(
        "SELECT COUNT(*) FROM occ_agg_enriched WHERE place_id IS NOT NULL AND mlat IS NULL"
    ).fetchone()[0]
    if bad:
        raise common.MigrationError(
            f"occurrence_agg: place_id はあるのに mlat/mlon が解決できないセルが{bad}件ある"
            "（place_source_ref(source_id='organism_records.lat_lon') が grid01 以外の "
            "place_kind を含む、または該当エントリが無い可能性がある）。"
        )


def _assert_place_mesh_lookup_is_function(conn) -> None:
    """`place_mesh_lookup` が `place_id` について単射であることを確認する
    （`scripts/b05_project_v1.py` の `place_lookup` の重複検証と同じ考え方。
    実装は `scripts/migrate/common.raise_on_group_by_duplicates` に集約
    ——/simplify 指摘2）。
    """
    common.raise_on_group_by_duplicates(
        conn,
        "SELECT place_id, COUNT(*) AS c FROM place_mesh_lookup GROUP BY place_id HAVING c > 1 LIMIT 5",
        (),
        lambda dup: (
            "place_source_ref（source_id='organism_records.lat_lon'）が place_id について"
            f"単射でない（同じ place_id に複数の external_key が対応している。例: {dup}）。"
            "occurrence_agg の place_id から mlat/mlon を一意に復元できない。"
        ),
    )


# 年キー8表の SQL で繰り返し使う述語・式を1箇所にする（/simplify 指摘6。
# `scripts/b07_build_occurrence_cube.py` の `_SAME_YEAR_EXPR`/`_CROSS_YEAR_EXPR`
# と同じ流儀）。
_YEAR_RANGE_EXPR = "year BETWEEN 1970 AND 2026"


def _binom_nonempty_expr(prefix: str = "") -> str:
    """`binom` の原表記が NULL でも '' でもない、の判定式（列参照に `prefix`
    〔例: `"e."`〕を付けられる）。"""
    return f"{prefix}binom IS NOT NULL AND {prefix}binom <> ''"


def _mesh_n_expr(prefix: str = "") -> str:
    """`COUNT(DISTINCT mlat||'_'||mlon) AS mesh_n`（列参照に `prefix` を
    付けられる）。"""
    return f"COUNT(DISTINCT {prefix}mlat || '_' || {prefix}mlon) AS mesh_n"


# `species2.en_name`/`red_list_category`（例外。モジュール docstring 参照）と
# `species_month` はどちらも「occurrence（L2）を taxon で JOIN した
# binom/yr/mo/vernacular_name/red_list_category」を必要とするため、1回の
# 走査にまとめる（コードレビュー指摘10。以前は別々に L2 を2回フルスキャン
# していた）。
_L2_TAXON_ENRICHED_SQL = """
CREATE TEMP TABLE l2_taxon_enriched AS
SELECT t.canonical_binomial AS binom,
       CAST(substr(o.period_raw, 1, 4) AS INT) AS yr,
       CASE WHEN length(o.period_raw) >= 7 THEN CAST(substr(o.period_raw, 6, 2) AS INT) END AS month,
       o.vernacular_name AS vernacular_name,
       o.red_list_category AS red_list_category
FROM cube.occurrence o
LEFT JOIN reg.taxon t ON t.taxon_id = o.taxon_id
WHERE o.period_raw IS NOT NULL
"""

# species2.en_name/red_list_category の例外（`l2_taxon_enriched` を binom
# ごとに集計するだけ。L2 を再度読まない）。
_SPECIES2_L2_EXTRAS_SQL = f"""
CREATE TEMP TABLE species2_l2_extras AS
SELECT binom,
       MAX(COALESCE(NULLIF(vernacular_name, ''), '')) AS en_name,
       MAX(COALESCE(red_list_category, '')) AS red_list_category
FROM l2_taxon_enriched
WHERE {_binom_nonempty_expr()}
GROUP BY binom
"""

# 列名・列順・宣言型は v1（`data/db/derived.sqlite`）の実物を `PRAGMA
# table_info` で確認して合わせてある（コードレビュー指摘8）。v1 は
# `CREATE TABLE x AS SELECT ...`（CTAS）で作っているため、単純な列参照は
# 元の宣言型を引き継ぎ、集計関数（`SUM`/`COUNT`等）の結果列は宣言型を持たない
# （空文字）——**この宣言型の違いは値の格納（storage class）には影響しない**
# （宣言型が無い列は SQLite の BLOB 相当の「無親和性」になり、値の型変換を
# 一切行わない。整数値は元から INTEGER storage class で計算されるので、
# 列に型を宣言してもしなくても格納される値は変わらない——修正前後で
# 正準化 sha256 が完全一致することを実測で確認済み）。
_CREATE_ORG_GROUP_YEAR_SQL = "CREATE TABLE org_group_year (year INT, taxon_group, source_id TEXT, n, species_n, mesh_n)"
_ORG_GROUP_YEAR_INSERT_SQL = f"""
INSERT INTO org_group_year (year, taxon_group, source_id, n, species_n, mesh_n)
SELECT year, taxon_group, source_id, SUM(n) AS n,
       COUNT(DISTINCT binom) AS species_n,
       {_mesh_n_expr()}
FROM occ_agg_enriched
WHERE {_YEAR_RANGE_EXPR}
GROUP BY year, taxon_group, source_id
"""

_CREATE_EFFORT_YEAR_SQL = "CREATE TABLE effort_year (year INT, n, species_n, mesh_n, n_inat, n_gbif)"
_EFFORT_YEAR_INSERT_SQL = f"""
INSERT INTO effort_year (year, n, species_n, mesh_n, n_inat, n_gbif)
SELECT year, SUM(n) AS n,
       COUNT(DISTINCT binom) AS species_n,
       {_mesh_n_expr()},
       SUM(CASE WHEN source_id = 'inaturalist_kanagawa' THEN n ELSE 0 END) AS n_inat,
       SUM(CASE WHEN source_id = 'gbif_kanagawa_occurrences' THEN n ELSE 0 END) AS n_gbif
FROM occ_agg_enriched
WHERE {_YEAR_RANGE_EXPR}
GROUP BY year
"""

_CREATE_SPECIES2_SQL = (
    "CREATE TABLE species2 (binom, taxon_group, cls, family, en_name, red_list_category, "
    "n, y_from, y_to, n_years, mesh_n)"
)
# 全年・全記録が対象（v1 のとおり年フィルタが無い。O-1b brief 参照）。
_SPECIES2_INSERT_SQL = f"""
INSERT INTO species2 (binom, taxon_group, cls, family, en_name, red_list_category,
                       n, y_from, y_to, n_years, mesh_n)
SELECT e.binom, MAX(e.taxon_group) AS taxon_group, MAX(e.cls) AS cls, MAX(e.family) AS family,
       x.en_name AS en_name, x.red_list_category AS red_list_category,
       SUM(e.n) AS n, MIN(e.year) AS y_from, MAX(e.year) AS y_to,
       COUNT(DISTINCT e.year) AS n_years,
       {_mesh_n_expr("e.")}
FROM occ_agg_enriched e
LEFT JOIN species2_l2_extras x ON x.binom = e.binom
WHERE {_binom_nonempty_expr("e.")}
GROUP BY e.binom
"""
_SPECIES2_MISSING_L2_EXTRAS_SQL = (
    "SELECT COUNT(*) FROM species2 WHERE en_name IS NULL OR red_list_category IS NULL"
)

_CREATE_SPECIES_YEAR2_SQL = "CREATE TABLE species_year2 (binom, year INT, n, mesh_n)"
_SPECIES_YEAR2_INSERT_SQL = f"""
INSERT INTO species_year2 (binom, year, n, mesh_n)
SELECT binom, year, SUM(n) AS n, {_mesh_n_expr()}
FROM occ_agg_enriched
WHERE {_binom_nonempty_expr()} AND {_YEAR_RANGE_EXPR}
GROUP BY binom, year
"""

_CREATE_MESH_YEAR_SQL = "CREATE TABLE mesh_year (mlat INT, mlon INT, year INT, n, species_n, rl_n)"
# `place_id IS NOT NULL`: v1 の `WHERE lat IS NOT NULL`（座標を持つ記録か）に
# 相当する条件（モジュール docstring 参照。`mlat IS NOT NULL` ではなく
# `place_id` で書く——後者は「座標があるのに mesh 解決に失敗した」異常な
# NULL まで一緒くたに黙って落としてしまう。異常は
# `_assert_all_places_resolve_to_mesh` が別途止める）。
_MESH_YEAR_INSERT_SQL = f"""
INSERT INTO mesh_year (mlat, mlon, year, n, species_n, rl_n)
SELECT mlat, mlon, year, SUM(n) AS n, COUNT(DISTINCT binom) AS species_n, SUM(n_red_list) AS rl_n
FROM occ_agg_enriched
WHERE place_id IS NOT NULL AND {_YEAR_RANGE_EXPR}
GROUP BY mlat, mlon, year
"""

_CREATE_MESH_ALL_SQL = "CREATE TABLE mesh_all (mlat INT, mlon INT, n, rl_n, y_from, y_to)"
# v1 のとおり mesh_year（すでに年 1970-2026・座標ありで絞ってある）から積み上げる。
_MESH_ALL_INSERT_SQL = """
INSERT INTO mesh_all (mlat, mlon, n, rl_n, y_from, y_to)
SELECT mlat, mlon, SUM(n) AS n, SUM(rl_n) AS rl_n, MIN(year) AS y_from, MAX(year) AS y_to
FROM mesh_year
GROUP BY mlat, mlon
"""

# mesh_species は v1 のとおり **WHERE なし**（モジュール docstring 参照。
# 座標の無い記録があれば (mlat,mlon)=(NULL,NULL) の行がそのまま出る）。
# 先に (mesh, binom) 単位で n_red_list を合算してから DISTINCT を数える——
# 複数 taxon_id が同じ binom に対応する場合も binom で1つに畳まれる。
_MESH_SPECIES_AGG_SQL = """
CREATE TEMP TABLE mesh_species_agg AS
SELECT mlat, mlon, binom, SUM(n_red_list) AS rl_n
FROM occ_agg_enriched
GROUP BY mlat, mlon, binom
"""
_CREATE_MESH_SPECIES_SQL = "CREATE TABLE mesh_species (mlat INT, mlon INT, species_n, rl_species_n)"
_MESH_SPECIES_INSERT_SQL = f"""
INSERT INTO mesh_species (mlat, mlon, species_n, rl_species_n)
SELECT mlat, mlon,
       COUNT(DISTINCT CASE WHEN {_binom_nonempty_expr()} THEN binom END) AS species_n,
       COUNT(DISTINCT CASE WHEN {_binom_nonempty_expr()} AND rl_n > 0 THEN binom END) AS rl_species_n
FROM mesh_species_agg
GROUP BY mlat, mlon
"""

_CREATE_SPECIES_MESH_YEAR_SQL = "CREATE TABLE species_mesh_year (binom, year INT, mlat INT, mlon INT, n)"
# 主要種（species2.n >= 80。全年・全記録で判定済みの本物の species2 を読む）。
_SPECIES_MESH_YEAR_INSERT_SQL = f"""
INSERT INTO species_mesh_year (binom, year, mlat, mlon, n)
SELECT binom, year, mlat, mlon, SUM(n) AS n
FROM occ_agg_enriched
WHERE binom IN (SELECT binom FROM species2 WHERE n >= 80) AND {_YEAR_RANGE_EXPR}
GROUP BY binom, year, mlat, mlon
"""

# species_month は l2_taxon_enriched（1回の走査。上で作成済み）から直接
# 絞り込んで書く——別の温存テーブルを経由しない（コードレビュー指摘10）。
_CREATE_SPECIES_MONTH_SQL = "CREATE TABLE species_month (binom, month, n)"
_SPECIES_MONTH_INSERT_SQL = """
INSERT INTO species_month (binom, month, n)
SELECT binom, month, COUNT(*) AS n
FROM l2_taxon_enriched
WHERE month IS NOT NULL AND yr >= 2018 AND binom IN (SELECT binom FROM species2 WHERE n >= 80)
GROUP BY binom, month
"""


def _build_cube_projections(
    conn, default_taxon_group: str, *, check_stale_taxon: bool = True,
) -> dict[str, int]:
    """`conn`（`cube`/`reg` を ATTACH 済みの書き込み用接続）に、年キー8表と
    `species_month` を作る。`species2` を先に作り終えてから
    `species_mesh_year`/`species_month` がそれを読む（v1 の依存順どおり）。

    `check_stale_taxon=False`（`build_all_projections` が渡す）のときは
    `occurrence_agg` に対する古い taxon 検査を省く——`_build_org_norm` が
    `occurrence` 全体の新鮮さを、`_assert_cube_is_current_l2_partition` が
    `occurrence_agg` が `occurrence` の忠実な分割であることをそれぞれ検証
    済みなら、`occurrence_agg.taxon_id` の新鮮さは推移的に保証されるため
    （モジュール docstring 参照）。単独で年キー8表だけを作る
    `build_occurrence_cube_projections` は既定（`True`）のまま呼ぶ。

    戻り値はテーブルごとの行数。
    """
    _assert_cube_is_current_l2_partition(conn)
    if check_stale_taxon:
        _assert_no_stale_taxon_ids(conn, "cube.occurrence_agg", "occurrence_agg")

    conn.execute(_PLACE_MESH_LOOKUP_SQL)
    _assert_place_mesh_lookup_is_function(conn)
    conn.execute(_OCC_AGG_ENRICHED_SQL, (default_taxon_group,))
    _assert_all_places_resolve_to_mesh(conn)
    conn.execute(_L2_TAXON_ENRICHED_SQL)
    conn.execute(_SPECIES2_L2_EXTRAS_SQL)

    conn.execute(_CREATE_ORG_GROUP_YEAR_SQL)
    n_org_group_year = conn.execute(_ORG_GROUP_YEAR_INSERT_SQL).rowcount

    conn.execute(_CREATE_EFFORT_YEAR_SQL)
    n_effort_year = conn.execute(_EFFORT_YEAR_INSERT_SQL).rowcount

    conn.execute(_CREATE_SPECIES2_SQL)
    n_species2 = conn.execute(_SPECIES2_INSERT_SQL).rowcount
    missing_extras = conn.execute(_SPECIES2_MISSING_L2_EXTRAS_SQL).fetchone()[0]
    if missing_extras:
        raise common.MigrationError(
            f"species2: en_name/red_list_category が埋まらなかった binom が{missing_extras}件ある"
            "（occurrence_agg の binom 集合と occurrence の binom 集合が食い違っている可能性が"
            "ある。b06/b07 が同じ occurrence から作られているか確認すること）。"
        )

    conn.execute(_CREATE_SPECIES_YEAR2_SQL)
    n_species_year2 = conn.execute(_SPECIES_YEAR2_INSERT_SQL).rowcount

    conn.execute(_CREATE_MESH_YEAR_SQL)
    n_mesh_year = conn.execute(_MESH_YEAR_INSERT_SQL).rowcount

    conn.execute(_CREATE_MESH_ALL_SQL)
    n_mesh_all = conn.execute(_MESH_ALL_INSERT_SQL).rowcount

    conn.execute(_MESH_SPECIES_AGG_SQL)
    conn.execute(_CREATE_MESH_SPECIES_SQL)
    n_mesh_species = conn.execute(_MESH_SPECIES_INSERT_SQL).rowcount

    conn.execute(_CREATE_SPECIES_MESH_YEAR_SQL)
    n_species_mesh_year = conn.execute(_SPECIES_MESH_YEAR_INSERT_SQL).rowcount

    conn.execute(_CREATE_SPECIES_MONTH_SQL)
    n_species_month = conn.execute(_SPECIES_MONTH_INSERT_SQL).rowcount

    return {
        "org_group_year": n_org_group_year,
        "effort_year": n_effort_year,
        "species2": n_species2,
        "species_year2": n_species_year2,
        "mesh_year": n_mesh_year,
        "mesh_all": n_mesh_all,
        "mesh_species": n_mesh_species,
        "species_mesh_year": n_species_mesh_year,
        "species_month": n_species_month,
    }


def build_occurrence_cube_projections(
    cube_db, registry_db, out_path, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
) -> dict[str, int]:
    """年キー8表と `species_month` だけを単独で `out_path` に書く（`org_norm`
    を含まない。既存テスト・単体検証用のエントリポイント——`main()` は
    10テーブルまとめて書く `build_all_projections` を使う）。

    `_assert_cube_is_current_l2_partition` が `FULL OUTER JOIN` を使うため、
    その前に `common.require_sqlite_version()` を呼ぶ（モジュール docstring
    「SQLite の版」参照）。
    """
    common.require_sqlite_version()
    _assert_prerequisites(cube_db, registry_db, need_occurrence_agg=True)
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        counts = _build_cube_projections(conn, default_taxon_group)
        conn.commit()
        return counts
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# O-2a: org_watershed_year / org_watershed（occurrence + occurrence_place から。
# v1（web/scripts/build-geo.mjs:112-225）の 0.001度メモ化の癖を、走査順に
# 依らない式で再現する。ADR-0026、`docs/plans/PHASE_B_OCCURRENCE.md` O-2a節）
# ---------------------------------------------------------------------------
#
# v1 は座標を 0.001度に丸めたバケット（JS の `Math.round(x*1000)`）で
# 判定結果をメモ化し、「バケットに最初に来た記録（≒rowid順の走査で最初に
# 来た記録）の正確な点内包判定結果」を同じバケットの全記録に配る。この
# 「順序」を SQL の集合演算だけで再現するため、次の**順序に依らない同値な
# 定式化**を使う（実測: 全く同じ結果になることを Python で個別に検証済み
# ——org_watershed_year 10,699行・org_watershed 287行が derived.sqlite と
# 完全一致。docs/plans/PHASE_B_OCCURRENCE.md O-2a節参照）:
#
# - バケット = `(CAST(FLOOR(lon*1000+0.5) AS INT), CAST(FLOOR(lat*1000+0.5) AS INT))`
#   （JS の `Math.round(x*1000)` と同じ丸め。正の座標では常に一致する——
#   実データは神奈川県内〔正の経緯度〕に限られるため符号の差は問題にならない）。
# - 代表 = そのバケットの中で **v1 の母集団**
#   （`occurrence.period_raw IS NOT NULL AND lat IS NOT NULL`）の
#   `MIN(source_row_id)`（`organism_records.rowid`。**全行**〔日付の無い記録も
#   含む〕で代表を取ると結果が変わる——必ず日付ありの母集団で選ぶこと。
#   実測: 69バケットで代表が変わる）。
# - 記録の流域 = **代表記録自身**の `occurrence_place`（O-2a、正確な点内包
#   判定）の解決結果（NULL を含む）。代表以外の記録の `occurrence_place` は
#   使わない——それが v1 のメモ化の癖（「代表の判定結果を全員に配る」）を
#   再現するということ。
#
# `occurrence_place` には v1 の割当を焼き込まない（ADR-0024・ADR-0025 D3 と
# 同じ「v1 の癖は射影の式に置く」原則）——v1 の癖の全ロジックはこのセクション
# （射影）だけに閉じている。

_WATERSHED_SOURCE_ID = "watershed_meta.watershed_id"
_WATERSHED_PLACE_KIND = "watershed"
_WATERSHED_NULL_SENTINEL = "__NULL_WATERSHED_ID__"  # COUNT(DISTINCT ...) で NULL も1値として数える番人（
# watershed_id は v1 形の '83030-0001' のような数字とハイフンだけの文字列なので衝突しない。
# NUL バイトは sqlite3 モジュールが SQL 文字列として受け付けないため使わない）

# v1（`web/scripts/build-geo.mjs` の `rows()` クエリ）と一字一句同じ母集団条件
# （コードレビュー指摘9: 以前は `period_raw IS NOT NULL AND lat IS NOT NULL` だけで
# `LENGTH(observed_on) >= 4` が抜けていた。実データでは b06
# （`scripts/migrate/occurrence_period.py`）が12形〔最短4桁〕以外の
# `observed_on` を弾いているため、`period_raw IS NOT NULL` の行は実測上すべて
# 4桁以上のはずだが、v1 の式と一字一句合わせて機械的に検算する——
# `_build_watershed()` が実測して報告する）。`{p}` は列参照の接頭辞
# （無指定なら空文字列、別名を使う側は `"o."` を渡す）。
_V1_POPULATION_WHERE_TMPL = "{p}period_raw IS NOT NULL AND length({p}period_raw) >= 4 AND {p}lat IS NOT NULL"

# place_id -> watershed_id（v1形、'83030-0001' 等）の逆引き。
# registry.build_place.py が作った place_source_ref(source_id='watershed_meta.watershed_id')
# と同型（scripts/b08_project_occurrence_v1.py の place_mesh_lookup と同じ流儀）。
_PLACE_WATERSHED_LOOKUP_SQL = """
CREATE TEMP TABLE place_watershed_lookup AS
SELECT place_id, external_key AS watershed_id
FROM reg.place_source_ref
WHERE source_id = ?
"""


def _assert_place_watershed_lookup_is_function(conn) -> None:
    """`place_watershed_lookup` が `place_id` について単射であることを確認する
    （`_assert_place_mesh_lookup_is_function` と同じ考え方。実装は
    `scripts/migrate/common.raise_on_group_by_duplicates` を使う）。
    """
    common.raise_on_group_by_duplicates(
        conn,
        "SELECT place_id, COUNT(*) AS c FROM place_watershed_lookup GROUP BY place_id HAVING c > 1 LIMIT 5",
        (),
        lambda dup: (
            f"place_source_ref（source_id={_WATERSHED_SOURCE_ID!r}）が place_id について"
            f"単射でない（同じ place_id に複数の external_key が対応している。例: {dup}）。"
            "occurrence_place.place_id から watershed_id を一意に復元できない。"
        ),
    )


def _assert_all_watershed_places_resolve(conn) -> None:
    """`occurrence_place.place_id`（`place_kind='watershed'`）が NULL でないのに
    `place_watershed_lookup` で `watershed_id` が引けない行があれば止める
    （コードレビュー指摘3。mesh 側の `_assert_all_places_resolve_to_mesh` と
    同じ考え方——座標が無い記録・どの流域にも入らない記録〔`place_id IS NULL`〕
    は正常系だが、`place_id` があるのに引けないのは
    `place_watershed_lookup`（`place_source_ref(source_id='watershed_meta.
    watershed_id')`）が `occurrence_place.place_id` の全体をカバーしていない
    異常——黙って NULL に落とさず止める）。
    """
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM cube.occurrence_place op
        LEFT JOIN place_watershed_lookup pw ON pw.place_id = op.place_id
        WHERE op.place_kind = ? AND op.place_id IS NOT NULL AND pw.watershed_id IS NULL
        """,
        (_WATERSHED_PLACE_KIND,),
    ).fetchone()[0]
    if bad:
        raise common.MigrationError(
            f"org_watershed_year: occurrence_place.place_id（place_kind={_WATERSHED_PLACE_KIND!r}）"
            f"はあるのに watershed_id が解決できない行が{bad}件ある（place_source_ref"
            f"(source_id={_WATERSHED_SOURCE_ID!r}) が該当 place_id を含まない可能性がある。"
            "registry.sqlite と occurrence_place を同じ版で揃えて b09 を再実行すること）。"
        )


def _assert_population_has_occurrence_place(conn) -> None:
    """v1 の母集団（`_V1_POPULATION_WHERE_TMPL`）の記録が、`occurrence_place`
    （`place_kind='watershed'`）に**必ず1行**持つことを確認する
    （コードレビュー指摘6。`occ_place_watershed`/`watershed_record_enriched` は
    `cube.occurrence_place` を起点に `LEFT JOIN` するため、occurrence_place が
    古い・部分的（b06 の後に b09 を回し忘れた、`place_kind` を打ち間違えた等）
    だと、本来あるはずの行が黙って「NULL＝どの流域にも入らない」と区別が
    つかなくなる——この存在チェックで先に検出する）。
    """
    population_where = _V1_POPULATION_WHERE_TMPL.format(p="")
    joined_where = _V1_POPULATION_WHERE_TMPL.format(p="o.")
    population_n, joined_n = conn.execute(
        f"""
        SELECT
          (SELECT COUNT(*) FROM cube.occurrence WHERE {population_where}),
          (SELECT COUNT(*) FROM cube.occurrence o
           JOIN cube.occurrence_place op
             ON op.record_id = o.record_id AND op.place_kind = ?
           WHERE {joined_where})
        """,
        (_WATERSHED_PLACE_KIND,),
    ).fetchone()
    if population_n != joined_n:
        raise common.MigrationError(
            f"org_watershed_year: v1 の母集団（occurrence、{population_n:,}行）のうち、"
            f"occurrence_place（place_kind={_WATERSHED_PLACE_KIND!r}）に対応する行が"
            f"{joined_n:,}行しかない。scripts/b06_build_occurrence.py の後に"
            "scripts/b09_build_occurrence_place.py を実行し忘れている、または"
            "occurrence と occurrence_place が別々のスナップショットから作られている"
            "可能性がある。"
        )


# occurrence_place（place_kind='watershed'）の各記録の「正確な」watershed_id
# （NULL を含む）。O-2a の母集団は occurrence 全体（823,692行）だが、ここでは
# 後続のクエリが record_id で LEFT JOIN するだけなので絞り込まない。
_OCC_PLACE_WATERSHED_SQL = """
CREATE TEMP TABLE occ_place_watershed AS
SELECT op.record_id AS record_id, pw.watershed_id AS watershed_id
FROM cube.occurrence_place op
LEFT JOIN place_watershed_lookup pw ON pw.place_id = op.place_id
WHERE op.place_kind = ?
"""

# v1 の母集団（`_V1_POPULATION_WHERE_TMPL`）のバケットごとの代表
# （MIN(source_row_id)）。
_WATERSHED_BUCKET_REPR_SQL = f"""
CREATE TEMP TABLE watershed_bucket_repr AS
SELECT
  CAST(FLOOR(lon * 1000 + 0.5) AS INT) AS bx,
  CAST(FLOOR(lat * 1000 + 0.5) AS INT) AS by,
  MIN(source_row_id) AS repr_source_row_id
FROM cube.occurrence
WHERE {_V1_POPULATION_WHERE_TMPL.format(p="")}
GROUP BY bx, by
"""

# バケットごとの「メモの流域」= 代表記録自身の occ_place_watershed。
_WATERSHED_BUCKET_WATERSHED_SQL = """
CREATE TEMP TABLE watershed_bucket_watershed AS
SELECT br.bx AS bx, br.by AS by, opw.watershed_id AS memo_watershed_id
FROM watershed_bucket_repr br
JOIN cube.occurrence o ON o.source_row_id = br.repr_source_row_id
LEFT JOIN occ_place_watershed opw ON opw.record_id = o.record_id
"""

# v1 の母集団の全記録に、バケットの「メモの流域」・記録自身の「正確な流域」
# ・年・学名・外来種フラグ・RL原表記を1回の走査で載せた作業テーブル。
# org_watershed_year（メモ方式）・機械検証（6〜7）はすべてここから作る。
_WATERSHED_RECORD_ENRICHED_SQL = f"""
CREATE TEMP TABLE watershed_record_enriched AS
SELECT
  o.record_id AS record_id,
  bw.bx AS bx, bw.by AS by,
  CAST(substr(o.period_raw, 1, 4) AS INT) AS year,
  bw.memo_watershed_id AS memo_watershed_id,
  opw.watershed_id AS exact_watershed_id,
  o.scientific_name AS scientific_name,
  o.is_alien AS is_alien,
  o.red_list_category AS red_list_category
FROM cube.occurrence o
JOIN watershed_bucket_watershed bw
  ON bw.bx = CAST(FLOOR(o.lon * 1000 + 0.5) AS INT)
 AND bw.by = CAST(FLOOR(o.lat * 1000 + 0.5) AS INT)
LEFT JOIN occ_place_watershed opw ON opw.record_id = o.record_id
WHERE {_V1_POPULATION_WHERE_TMPL.format(p="o.")}
"""

# 列名・列順は v1（data/db/derived.sqlite）の実物を PRAGMA table_info で
# 確認して合わせてある（既存9表と同じ流儀）。
_CREATE_ORG_WATERSHED_YEAR_SQL = (
    "CREATE TABLE org_watershed_year (watershed_id TEXT, year INTEGER, n INTEGER, "
    "species_n INTEGER, alien_n INTEGER, redlist_n INTEGER)"
)
_ORG_WATERSHED_YEAR_INSERT_SQL = f"""
INSERT INTO org_watershed_year (watershed_id, year, n, species_n, alien_n, redlist_n)
SELECT memo_watershed_id, year, COUNT(*) AS n,
       COUNT(DISTINCT CASE WHEN scientific_name IS NOT NULL AND scientific_name <> ''
                           THEN scientific_name END) AS species_n,
       SUM(is_alien) AS alien_n,
       SUM(CASE WHEN red_list_category IS NOT NULL AND red_list_category <> '' THEN 1 ELSE 0 END) AS redlist_n
FROM watershed_record_enriched
WHERE memo_watershed_id IS NOT NULL
GROUP BY memo_watershed_id, year
"""
_CREATE_INDEX_ORG_WATERSHED_YEAR_SQL = "CREATE INDEX ix_owy ON org_watershed_year(watershed_id, year)"

# v1 と同じく org_watershed_year から積み上げる（L2 を読み直さない）。
_CREATE_ORG_WATERSHED_SQL = "CREATE TABLE org_watershed (watershed_id TEXT, n, alien_n, redlist_n, y_from, y_to)"
_ORG_WATERSHED_INSERT_SQL = """
INSERT INTO org_watershed (watershed_id, n, alien_n, redlist_n, y_from, y_to)
SELECT watershed_id, SUM(n) AS n, SUM(alien_n) AS alien_n, SUM(redlist_n) AS redlist_n,
       MIN(year) AS y_from, MAX(year) AS y_to
FROM org_watershed_year
GROUP BY watershed_id
"""
_CREATE_INDEX_ORG_WATERSHED_SQL = "CREATE INDEX ix_ow ON org_watershed(watershed_id)"

# 比較専用（出力しない）: 記録自身の「正確な」流域だけで同じ式を集計し直した
# org_watershed_year 相当。宣言（org_watershed_year_keys_changed_vs_exact）の
# 実測に使う。
_ORG_WATERSHED_YEAR_EXACT_SQL = f"""
CREATE TEMP TABLE org_watershed_year_exact AS
SELECT exact_watershed_id AS watershed_id, year, COUNT(*) AS n,
       COUNT(DISTINCT CASE WHEN scientific_name IS NOT NULL AND scientific_name <> ''
                           THEN scientific_name END) AS species_n,
       SUM(is_alien) AS alien_n,
       SUM(CASE WHEN red_list_category IS NOT NULL AND red_list_category <> '' THEN 1 ELSE 0 END) AS redlist_n
FROM watershed_record_enriched
WHERE exact_watershed_id IS NOT NULL
GROUP BY exact_watershed_id, year
"""
# `org_watershed_year` 側の `ix_owy` と対にする（効率。コードレビュー指摘1:
# 索引が無いと `_measure_keys_changed_vs_exact` の FULL OUTER JOIN がネスト
# ループになる——実測 31.2秒 → 索引ありで0.034秒、約900倍。値〔1,091〕は
# 変わらない）。
_CREATE_INDEX_ORG_WATERSHED_YEAR_EXACT_SQL = (
    "CREATE INDEX ix_owy_exact ON org_watershed_year_exact(watershed_id, year)"
)


# ---------------------------------------------------------------------------
# 宣言 YAML（scripts/migrate/occurrence_watershed_v1_declarations.yaml）。
# occurrence_period_shapes.yaml 等（name -> {expected_row_count, note}）とは
# 形が違う（内訳を持つ・行数ではない実測値を扱う）ため、専用の検証にする。
# ---------------------------------------------------------------------------

_WATERSHED_DECLARATION_NAMES = frozenset({
    "memo_moved_records", "memo_mixed_buckets", "org_watershed_year_keys_changed_vs_exact",
})
_MOVED_BREAKDOWN_KEYS = ("ws_to_ws", "v1_assigned_exact_unassigned", "v1_unassigned_exact_assigned")


def load_and_validate_watershed_declarations(path=DEFAULT_WATERSHED_DECLARATIONS_YAML) -> dict:
    """`occurrence_watershed_v1_declarations.yaml` を読み、構造を検証してから
    返す。3つの宣言名（`_WATERSHED_DECLARATION_NAMES`）と過不足なく一致し、
    `memo_moved_records` は `breakdown` の3値の合計が `expected_count` と
    一致することも確認する（宣言ファイル自体の自己矛盾を防ぐ）。
    """
    raw = common.load_yaml(path)
    if not isinstance(raw, dict):
        raise common.MigrationError(f"{path} がマッピングになっていない（実際の型: {type(raw).__name__}）")

    period.assert_declared_names_match(raw, _WATERSHED_DECLARATION_NAMES, path)

    problems: list[str] = []
    for name in ("memo_mixed_buckets", "org_watershed_year_keys_changed_vs_exact"):
        spec = raw[name]
        if not isinstance(spec, dict) or not spec.get("note"):
            problems.append(f"{name}: note が無い（または空）")
            continue
        p = period.non_negative_int_problem(f"{name}.expected_count", spec.get("expected_count"))
        if p:
            problems.append(p)

    moved = raw.get("memo_moved_records")
    if not isinstance(moved, dict) or not moved.get("note"):
        problems.append("memo_moved_records: note が無い（または空）")
    else:
        p = period.non_negative_int_problem("memo_moved_records.expected_count", moved.get("expected_count"))
        if p:
            problems.append(p)
        breakdown = moved.get("breakdown")
        if not isinstance(breakdown, dict) or frozenset(breakdown) != frozenset(_MOVED_BREAKDOWN_KEYS):
            problems.append(
                f"memo_moved_records.breakdown のキーが {list(_MOVED_BREAKDOWN_KEYS)} と一致しない"
                f"（実際: {sorted(breakdown) if isinstance(breakdown, dict) else breakdown!r}）"
            )
        else:
            bp = [
                period.non_negative_int_problem(f"memo_moved_records.breakdown.{k}", breakdown[k])
                for k in _MOVED_BREAKDOWN_KEYS
            ]
            problems.extend(p for p in bp if p)
            if not problems and isinstance(moved.get("expected_count"), int):
                total = sum(breakdown[k] for k in _MOVED_BREAKDOWN_KEYS)
                if total != moved["expected_count"]:
                    problems.append(
                        "memo_moved_records: breakdown の合計"
                        f"（{total}）が expected_count（{moved['expected_count']}）と一致しない"
                    )
    if problems:
        raise common.MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))
    return raw


def validate_watershed_declarations_shape(path=DEFAULT_WATERSHED_DECLARATIONS_YAML) -> None:
    """CI 用: 構造検証だけを行う（原本DBを必要としない）。"""
    load_and_validate_watershed_declarations(path)


# ---------------------------------------------------------------------------
# 機械検証6・7: メモ方式と正確な結果の食い違いを記録単位で実測し、宣言と
# 突き合わせる。キー1件ずつの宣言済み差分にはしない
# （docs/plans/PHASE_B_OCCURRENCE.md O-2a節参照）。
# ---------------------------------------------------------------------------

def _measure_moved_records(conn) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN COALESCE(memo_watershed_id,'') <> COALESCE(exact_watershed_id,'')
                   THEN 1 ELSE 0 END) AS moved,
          SUM(CASE WHEN memo_watershed_id IS NOT NULL AND exact_watershed_id IS NOT NULL
                        AND memo_watershed_id <> exact_watershed_id THEN 1 ELSE 0 END) AS ws_to_ws,
          SUM(CASE WHEN memo_watershed_id IS NOT NULL AND exact_watershed_id IS NULL
                   THEN 1 ELSE 0 END) AS v1_assigned_exact_unassigned,
          SUM(CASE WHEN memo_watershed_id IS NULL AND exact_watershed_id IS NOT NULL
                   THEN 1 ELSE 0 END) AS v1_unassigned_exact_assigned
        FROM watershed_record_enriched
        """
    ).fetchone()
    return {
        "memo_moved_records": row[0] or 0,
        "ws_to_ws": row[1] or 0,
        "v1_assigned_exact_unassigned": row[2] or 0,
        "v1_unassigned_exact_assigned": row[3] or 0,
    }


def _measure_mixed_buckets(conn) -> int:
    return conn.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT bx, by FROM watershed_record_enriched
          GROUP BY bx, by
          HAVING COUNT(DISTINCT COALESCE(exact_watershed_id, '{_WATERSHED_NULL_SENTINEL}')) > 1
        )
        """
    ).fetchone()[0]


def _measure_keys_changed_vs_exact(conn) -> int:
    """メモ方式の `org_watershed_year`（本番の作業用テーブル。この時点で
    構築済み）と `org_watershed_year_exact`（比較専用の一時テーブル）を
    `(watershed_id, year)` で突き合わせ、キーが片方にしか無い、または
    4値のいずれかが違う、のどちらかに該当するキー数を返す。

    比較そのものは `common.count_grouped_totals_mismatches()`（`assert_
    grouped_totals_match()` と同じ「一時テーブル＋一意索引」の安全な
    `FULL OUTER JOIN`）に寄せてある（/simplify 指摘5: 以前は手書きの
    `FULL OUTER JOIN` で、`org_watershed_year_exact` に索引が無いとネスト
    ループに落ちる穴があった）。
    """
    return common.count_grouped_totals_mismatches(
        conn,
        "SELECT watershed_id, year, n, species_n, alien_n, redlist_n FROM org_watershed_year",
        "SELECT watershed_id, year, n, species_n, alien_n, redlist_n FROM org_watershed_year_exact",
        key_columns=["watershed_id", "year"],
        value_columns=["n", "species_n", "alien_n", "redlist_n"],
    )


def _assert_watershed_declarations_match(conn, declarations: dict, declarations_yaml) -> dict:
    """機械検証6・7・保存則をすべて行い、食い違えば `common.MigrationError` で
    止める。戻り値は実測値（レポート用）。
    """
    moved = _measure_moved_records(conn)
    mixed = _measure_mixed_buckets(conn)
    keys_changed = _measure_keys_changed_vs_exact(conn)

    expected_moved = declarations["memo_moved_records"]
    expected_breakdown = expected_moved["breakdown"]
    problems = []
    if moved["memo_moved_records"] != expected_moved["expected_count"]:
        problems.append(
            f"memo_moved_records: 宣言{expected_moved['expected_count']:,} / "
            f"実測{moved['memo_moved_records']:,}"
        )
    for key in _MOVED_BREAKDOWN_KEYS:
        if moved[key] != expected_breakdown[key]:
            problems.append(f"memo_moved_records.breakdown.{key}: 宣言{expected_breakdown[key]:,} / 実測{moved[key]:,}")
    expected_mixed = declarations["memo_mixed_buckets"]["expected_count"]
    if mixed != expected_mixed:
        problems.append(f"memo_mixed_buckets: 宣言{expected_mixed:,} / 実測{mixed:,}")
    expected_keys_changed = declarations["org_watershed_year_keys_changed_vs_exact"]["expected_count"]
    if keys_changed != expected_keys_changed:
        problems.append(
            f"org_watershed_year_keys_changed_vs_exact: 宣言{expected_keys_changed:,} / "
            f"実測{keys_changed:,}"
        )
    if problems:
        raise common.MigrationError(
            f"org_watershed_year/org_watershed: 記録単位の実測が宣言（{declarations_yaml}）と"
            "食い違う（原本のスナップショットが変わった、または点内包判定の実装が壊れている"
            "可能性がある。実測が正しければ宣言値を更新すること）:\n- " + "\n- ".join(problems)
        )
    return {
        **moved,
        "memo_mixed_buckets": mixed,
        "org_watershed_year_keys_changed_vs_exact": keys_changed,
    }


def _assert_watershed_conservation(conn, moved: dict) -> dict:
    """保存則（O-2a brief 受け入れ3）: `Σ org_watershed_year.n` +
    `v1_unassigned_exact_assigned` − `v1_assigned_exact_unassigned` が
    `occurrence_place` で「日付があり・watershed に解決した」記録数と一致する
    ことを検証する。

    コードレビュー指摘6: `sum_n`（本番の出力テーブル `org_watershed_year` から）
    と `exact_resolved_dated` は**別々の経路**で計算する——以前は
    `exact_resolved_dated` も `watershed_record_enriched`（`occ_place_watershed`
    経由で `cube.occurrence_place` を間接的に参照する中間テーブル）から数えて
    いたため、`occurrence_place` が古い・部分的でもこの保存則自体は
    （辻褄が合ったまま）通ってしまっていた。ここでは `cube.occurrence_place` を
    直接 `cube.occurrence` と JOIN して独立に数える。
    """
    sum_n = conn.execute("SELECT COALESCE(SUM(n), 0) FROM org_watershed_year").fetchone()[0]
    exact_resolved_dated = conn.execute(
        f"""
        SELECT COUNT(*) FROM cube.occurrence o
        JOIN cube.occurrence_place op ON op.record_id = o.record_id AND op.place_kind = ?
        WHERE {_V1_POPULATION_WHERE_TMPL.format(p="o.")} AND op.place_id IS NOT NULL
        """,
        (_WATERSHED_PLACE_KIND,),
    ).fetchone()[0]
    lhs = sum_n + moved["v1_unassigned_exact_assigned"] - moved["v1_assigned_exact_unassigned"]
    if lhs != exact_resolved_dated:
        raise common.MigrationError(
            "org_watershed_year: 保存則が崩れている（Σn "
            f"{sum_n:,} + v1_unassigned_exact_assigned {moved['v1_unassigned_exact_assigned']:,} − "
            f"v1_assigned_exact_unassigned {moved['v1_assigned_exact_unassigned']:,} = {lhs:,} != "
            f"occurrence_place で日付あり・watershed 解決の記録数 {exact_resolved_dated:,}）。"
        )
    return {"sum_n": sum_n, "exact_resolved_dated": exact_resolved_dated}


def _build_watershed(
    conn, declarations_yaml=DEFAULT_WATERSHED_DECLARATIONS_YAML,
) -> tuple[dict[str, int], dict]:
    """`conn`（`cube`/`reg` を ATTACH 済みの書き込み用接続）に
    `org_watershed_year`/`org_watershed` を作る。`_build_org_norm`/
    `_build_cube_projections` と独立に呼べる（`occurrence`/`occurrence_place`
    だけに依存し、`occurrence_agg` は読まない）。

    戻り値は `(table_counts, diagnostics)` の2要素タプル
    （コードレビュー指摘2・12: 以前はテーブル行数と機械検証の実測値
    〔`memo_moved_records` 等、行数ではない統計値〕を同じ dict に混ぜていた
    ため、`main()`/呼び出し側が `sum(counts.values())`・`set(counts)` を
    テーブル行数だけの集合として扱えなかった。`table_counts` は
    `{"org_watershed_year": n, "org_watershed": n}` の2キーだけを持つ）。
    """
    declarations = load_and_validate_watershed_declarations(declarations_yaml)

    conn.execute(_PLACE_WATERSHED_LOOKUP_SQL, (_WATERSHED_SOURCE_ID,))
    _assert_place_watershed_lookup_is_function(conn)
    _assert_all_watershed_places_resolve(conn)
    conn.execute(_OCC_PLACE_WATERSHED_SQL, (_WATERSHED_PLACE_KIND,))
    _assert_population_has_occurrence_place(conn)
    conn.execute(_WATERSHED_BUCKET_REPR_SQL)
    conn.execute(_WATERSHED_BUCKET_WATERSHED_SQL)
    conn.execute(_WATERSHED_RECORD_ENRICHED_SQL)

    conn.execute(_CREATE_ORG_WATERSHED_YEAR_SQL)
    n_org_watershed_year = conn.execute(_ORG_WATERSHED_YEAR_INSERT_SQL).rowcount
    conn.execute(_CREATE_INDEX_ORG_WATERSHED_YEAR_SQL)

    conn.execute(_CREATE_ORG_WATERSHED_SQL)
    n_org_watershed = conn.execute(_ORG_WATERSHED_INSERT_SQL).rowcount
    conn.execute(_CREATE_INDEX_ORG_WATERSHED_SQL)

    conn.execute(_ORG_WATERSHED_YEAR_EXACT_SQL)
    conn.execute(_CREATE_INDEX_ORG_WATERSHED_YEAR_EXACT_SQL)
    moved = _assert_watershed_declarations_match(conn, declarations, declarations_yaml)
    conservation = _assert_watershed_conservation(conn, moved)

    table_counts = {"org_watershed_year": n_org_watershed_year, "org_watershed": n_org_watershed}
    diagnostics = {**moved, **conservation}
    return table_counts, diagnostics


def build_watershed_projections(
    cube_db, registry_db, out_path, declarations_yaml=DEFAULT_WATERSHED_DECLARATIONS_YAML,
) -> tuple[dict[str, int], dict]:
    """`org_watershed_year`/`org_watershed` だけを単独で `out_path` に書く
    （既存テスト・単体検証用のエントリポイント——`main()` は12テーブルまとめて
    書く `build_all_projections` を使う）。戻り値は `_build_watershed()` と
    同じ `(table_counts, diagnostics)`。

    `_measure_keys_changed_vs_exact` が `FULL OUTER JOIN` を使うため、その前に
    `common.require_sqlite_version()` を呼ぶ。
    """
    common.require_sqlite_version()
    _assert_prerequisites(cube_db, registry_db, need_occurrence_agg=False, need_occurrence_place=True)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        table_counts, diagnostics = _build_watershed(conn, declarations_yaml)
        conn.commit()
        return table_counts, diagnostics
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 12テーブルまとめて1ファイルに書く（main() が使う）
# ---------------------------------------------------------------------------

def build_all_projections(
    cube_db, registry_db, out_path, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
    watershed_declarations_yaml=DEFAULT_WATERSHED_DECLARATIONS_YAML,
) -> tuple[dict[str, int], dict]:
    """`org_norm` ＋ 年キー8表 ＋ `species_month` ＋ `org_watershed_year`/
    `org_watershed`（O-2a）の12テーブルを、1つの `fresh_sqlite` 接続で
    `out_path` に書く（`org_norm` を先に作ってから年キー8表・
    `species_month` を作る——後者が `species2` を読むため、かつ
    `occurrence_agg` に対する古い taxon 検査を重ねがけしないため。モジュール
    docstring参照）。

    戻り値は `(table_counts, watershed_diagnostics)` の2要素タプル
    （コードレビュー指摘2・12）。`table_counts` はこの12テーブルの行数**だけ**
    を持つ dict（`set(table_counts) == {12テーブル名}` が常に成り立つ——
    `memo_moved_records` のような行数ではない機械検証の実測値は混ぜない）。
    `watershed_diagnostics` は `_build_watershed()` の2つ目の戻り値そのもの。

    `_assert_cube_is_current_l2_partition`/`_measure_keys_changed_vs_exact` が
    `FULL OUTER JOIN` を使うため、その前に `common.require_sqlite_version()`
    を呼ぶ（モジュール docstring「SQLite の版」参照）。
    """
    common.require_sqlite_version()
    _assert_prerequisites(
        cube_db, registry_db, need_occurrence_agg=True, need_occurrence_place=True,
    )
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        n_org_norm = _build_org_norm(conn, default_taxon_group)
        counts = _build_cube_projections(conn, default_taxon_group, check_stale_taxon=False)
        watershed_table_counts, watershed_diagnostics = _build_watershed(conn, watershed_declarations_yaml)
        conn.commit()
        table_counts = {"org_norm": n_org_norm, **counts, **watershed_table_counts}
        return table_counts, watershed_diagnostics
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube-db", default=str(DEFAULT_CUBE_DB), help="occurrence/occurrence_agg を持つ v2.sqlite")
    parser.add_argument(
        "--registry-db", default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--taxon-group-yaml", default=str(DEFAULT_TAXON_GROUP_YAML))
    parser.add_argument("--watershed-declarations-yaml", default=str(DEFAULT_WATERSHED_DECLARATIONS_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {args.cube_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("v1 形（12テーブル）へ射影して書き出し") as info:
        counts, watershed_diagnostics = build_all_projections(
            args.cube_db, registry_db, args.out, args.taxon_group_yaml, args.watershed_declarations_yaml,
        )
        # `counts` はテーブル行数だけを持つ（コードレビュー指摘2・12）ので、
        # 除外リストなしでそのまま合計できる。
        info["n"] = sum(counts.values())

    for table, n in sorted(counts.items()):
        print(f"  {table}: {n:,}行")
    print(
        f"  [org_watershed] memo_moved_records={watershed_diagnostics['memo_moved_records']:,} "
        f"(ws_to_ws={watershed_diagnostics['ws_to_ws']:,} / "
        f"v1_assigned_exact_unassigned={watershed_diagnostics['v1_assigned_exact_unassigned']:,} / "
        f"v1_unassigned_exact_assigned={watershed_diagnostics['v1_unassigned_exact_assigned']:,}) / "
        f"memo_mixed_buckets={watershed_diagnostics['memo_mixed_buckets']:,} / "
        f"keys_changed_vs_exact={watershed_diagnostics['org_watershed_year_keys_changed_vs_exact']:,} / "
        f"保存則: sum_n={watershed_diagnostics['sum_n']:,} / "
        f"exact_resolved_dated={watershed_diagnostics['exact_resolved_dated']:,}"
    )


if __name__ == "__main__":
    main()
