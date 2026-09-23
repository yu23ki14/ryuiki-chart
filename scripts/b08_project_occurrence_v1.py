#!/usr/bin/env python3
"""`occurrence`（L2）と `occurrence_agg`（キューブ。b07）から v1 の10テーブル
（`org_norm`・年キー8表・`species_month`）に射影する（ADR-0016 Phase B
「ファクトとキューブ」O-1a/O-1b。O-1 設計 v2 D3・D4・ADR-0025 D3。
番号 b07 は O-1b のキューブ用だった）。

    .venv/bin/python3 scripts/b08_project_occurrence_v1.py

`data/db/v1_projection_occurrence.sqlite`（毎回ゼロから作り直す、専用の出力
ファイル。b05 の `v1_projection.sqlite` とは別ファイル——D3参照）に10テーブル
（`org_norm`・`org_group_year`・`effort_year`・`species2`・`species_year2`・
`species_month`・`mesh_year`・`mesh_all`・`mesh_species`・`species_mesh_year`）
を書く。列名・列順は `reports/derived_baseline.json`／実物の `data/db/derived.sqlite`
（`PRAGMA table_info`）と一致させてある（`scripts/b02_derived_compare.py
--candidate ... --tables ...` がそのまま突き合わせられるように）。**`b02` 自身は
列名で `SELECT` するため列順・宣言型を見ないが**（`scripts/reconcile/datasource.py`
の `fetch_rows` 参照）、この10表のスキーマは v1（`derived.sqlite`）の実物と
そろえてある（コードレビュー指摘8。`org_norm` は O-1a のまま——本 PR では
一切変更していない）。

## O-1a: `org_norm`（`occurrence`＝L2 から）

設計・規則は変更なし（`_build_org_norm`/`build_org_norm_projection`。旧版の
振る舞いをそのまま維持——値は1ビットも変えない）。射影の規則は
`_ORG_NORM_SELECT_EXPRS` の直前にまとめてある。

## O-1b: 年キー8表は `occurrence_agg`（キューブ）だけから（ADR-0025 D3）

`org_group_year`/`effort_year`/`species2`/`species_year2`/`mesh_year`/
`mesh_all`/`mesh_species`/`species_mesh_year` は **`occurrence_agg` だけ**から
作る（`occurrence`（L2）を読まない。例外は `species2.en_name`/
`red_list_category` だけ——後述）。

- **`occurrence_agg.place_kind = 'grid01'` に明示的に絞る**（追加指示。
  `occurrence_agg` の鍵は O-2 の先取りで `place_kind` を持つ——
  `scripts/b07_build_occurrence_cube.py` のモジュール docstring参照。今は
  常に `'grid01'` だが、O-2 で `place_kind='watershed'` のロールアップセルが
  同じ表に増えても、mesh（`mlat`/`mlon`）前提のこの8表が二重に数えたり
  watershed の `place_id` を grid01 用の `place_mesh_lookup` に誤って
  引かせたりしないようにする。`place_kind` が既知の値
  （`'grid01'`/`'watershed'`）以外なら止める
  （`_assert_known_place_kinds`）。
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

from migrate import common  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_TAXON_GROUP_YAML = ROOT / "registry" / "taxon" / "taxon_group.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection_occurrence.sqlite"

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


def _assert_prerequisites(cube_db, registry_db, *, need_occurrence_agg: bool) -> None:
    """`cube_db`/`registry_db` が存在し、必要なテーブルを持つことを
    `common.fresh_sqlite(out_path)`（既存の出力を即座に消す）より前に
    確かめる。無ければ「先に何を実行すべきか」を案内して止める
    （コードレビュー指摘6。以前は出力を消した後で ATTACH に失敗し、
    生の `OperationalError` と空の `org_norm` だけが残っていた）。
    """
    cube_path = pathlib.Path(cube_db)
    if not cube_path.exists():
        needed = "scripts/b06_build_occurrence.py"
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
    """`occurrence_agg` の grain が `{'year','survey_period'}` 以外を含んで
    いない（新しい grain を黙って絞り込みで捨てない）こと、`place_kind` が
    既知の値だけであること、`place_kind='grid01'` に絞った系列
    （source_id, taxon_id）ごとの `SUM(occurrence_agg.n)` が `occurrence`
    （L2、日付あり行、同じく `place_kind='grid01'`）の件数と一致することを
    確認する。崩れていれば「b06 の後に b07 を再実行せよ」と案内して止める
    （コードレビュー指摘2）。
    """
    bad_grain = conn.execute(
        "SELECT DISTINCT grain FROM cube.occurrence_agg WHERE grain NOT IN ('year', 'survey_period')"
    ).fetchall()
    if bad_grain:
        raise common.MigrationError(
            f"occurrence_agg: grain が 'year'/'survey_period' 以外の値を持つ（{[r[0] for r in bad_grain]}）。"
            "年キー8表の射影（このファイル）はこの2つの grain だけを前提にしているため、"
            "新しい grain を足すならこの検証と射影の両方を見直すこと。"
        )
    _assert_known_place_kinds(conn)

    l2_totals = {(r[0], r[1]): r[2] for r in conn.execute(_L2_DATED_SERIES_TOTALS_SQL)}
    cube_totals = {(r[0], r[1]): r[2] for r in conn.execute(_CUBE_SERIES_TOTALS_SQL)}
    mismatches = [
        (key, l2_totals.get(key), cube_totals.get(key))
        for key in sorted(set(l2_totals) | set(cube_totals), key=lambda k: (k[0], k[1] or ""))
        if l2_totals.get(key) != cube_totals.get(key)
    ][:_SAMPLE_LIMIT]
    if mismatches:
        raise common.MigrationError(
            f"occurrence_agg: place_kind='{_MESH_PLACE_KIND}' に絞った系列（source_id, taxon_id）"
            "ごとの Σn が occurrence（L2、同じく grid01）と食い違う（occurrence_agg が「今の"
            " occurrence の分割」になっていない）。scripts/b06_build_occurrence.py の後に"
            " scripts/b07_build_occurrence_cube.py を再実行すること。"
            f"（例（上限{_SAMPLE_LIMIT}件、(source_id, taxon_id), L2側n, キューブ側n）: {mismatches}）"
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
    （`scripts/b05_project_v1.py` の `place_lookup` の重複検証と同じ考え方）。
    """
    dup = conn.execute(
        "SELECT place_id, COUNT(*) AS c FROM place_mesh_lookup GROUP BY place_id HAVING c > 1 LIMIT 5"
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "place_source_ref（source_id='organism_records.lat_lon'）が place_id について"
            f"単射でない（同じ place_id に複数の external_key が対応している。例: {dup}）。"
            "occurrence_agg の place_id から mlat/mlon を一意に復元できない。"
        )


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
_SPECIES2_L2_EXTRAS_SQL = """
CREATE TEMP TABLE species2_l2_extras AS
SELECT binom,
       MAX(COALESCE(NULLIF(vernacular_name, ''), '')) AS en_name,
       MAX(COALESCE(red_list_category, '')) AS red_list_category
FROM l2_taxon_enriched
WHERE binom IS NOT NULL AND binom <> ''
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
_ORG_GROUP_YEAR_INSERT_SQL = """
INSERT INTO org_group_year (year, taxon_group, source_id, n, species_n, mesh_n)
SELECT year, taxon_group, source_id, SUM(n) AS n,
       COUNT(DISTINCT binom) AS species_n,
       COUNT(DISTINCT mlat || '_' || mlon) AS mesh_n
FROM occ_agg_enriched
WHERE year BETWEEN 1970 AND 2026
GROUP BY year, taxon_group, source_id
"""

_CREATE_EFFORT_YEAR_SQL = "CREATE TABLE effort_year (year INT, n, species_n, mesh_n, n_inat, n_gbif)"
_EFFORT_YEAR_INSERT_SQL = """
INSERT INTO effort_year (year, n, species_n, mesh_n, n_inat, n_gbif)
SELECT year, SUM(n) AS n,
       COUNT(DISTINCT binom) AS species_n,
       COUNT(DISTINCT mlat || '_' || mlon) AS mesh_n,
       SUM(CASE WHEN source_id = 'inaturalist_kanagawa' THEN n ELSE 0 END) AS n_inat,
       SUM(CASE WHEN source_id = 'gbif_kanagawa_occurrences' THEN n ELSE 0 END) AS n_gbif
FROM occ_agg_enriched
WHERE year BETWEEN 1970 AND 2026
GROUP BY year
"""

_CREATE_SPECIES2_SQL = (
    "CREATE TABLE species2 (binom, taxon_group, cls, family, en_name, red_list_category, "
    "n, y_from, y_to, n_years, mesh_n)"
)
# 全年・全記録が対象（v1 のとおり年フィルタが無い。O-1b brief 参照）。
_SPECIES2_INSERT_SQL = """
INSERT INTO species2 (binom, taxon_group, cls, family, en_name, red_list_category,
                       n, y_from, y_to, n_years, mesh_n)
SELECT e.binom, MAX(e.taxon_group) AS taxon_group, MAX(e.cls) AS cls, MAX(e.family) AS family,
       x.en_name AS en_name, x.red_list_category AS red_list_category,
       SUM(e.n) AS n, MIN(e.year) AS y_from, MAX(e.year) AS y_to,
       COUNT(DISTINCT e.year) AS n_years,
       COUNT(DISTINCT e.mlat || '_' || e.mlon) AS mesh_n
FROM occ_agg_enriched e
LEFT JOIN species2_l2_extras x ON x.binom = e.binom
WHERE e.binom IS NOT NULL AND e.binom <> ''
GROUP BY e.binom
"""
_SPECIES2_MISSING_L2_EXTRAS_SQL = (
    "SELECT COUNT(*) FROM species2 WHERE en_name IS NULL OR red_list_category IS NULL"
)

_CREATE_SPECIES_YEAR2_SQL = "CREATE TABLE species_year2 (binom, year INT, n, mesh_n)"
_SPECIES_YEAR2_INSERT_SQL = """
INSERT INTO species_year2 (binom, year, n, mesh_n)
SELECT binom, year, SUM(n) AS n, COUNT(DISTINCT mlat || '_' || mlon) AS mesh_n
FROM occ_agg_enriched
WHERE binom IS NOT NULL AND binom <> '' AND year BETWEEN 1970 AND 2026
GROUP BY binom, year
"""

_CREATE_MESH_YEAR_SQL = "CREATE TABLE mesh_year (mlat INT, mlon INT, year INT, n, species_n, rl_n)"
# `place_id IS NOT NULL`: v1 の `WHERE lat IS NOT NULL`（座標を持つ記録か）に
# 相当する条件（モジュール docstring 参照。`mlat IS NOT NULL` ではなく
# `place_id` で書く——後者は「座標があるのに mesh 解決に失敗した」異常な
# NULL まで一緒くたに黙って落としてしまう。異常は
# `_assert_all_places_resolve_to_mesh` が別途止める）。
_MESH_YEAR_INSERT_SQL = """
INSERT INTO mesh_year (mlat, mlon, year, n, species_n, rl_n)
SELECT mlat, mlon, year, SUM(n) AS n, COUNT(DISTINCT binom) AS species_n, SUM(n_red_list) AS rl_n
FROM occ_agg_enriched
WHERE place_id IS NOT NULL AND year BETWEEN 1970 AND 2026
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
_MESH_SPECIES_INSERT_SQL = """
INSERT INTO mesh_species (mlat, mlon, species_n, rl_species_n)
SELECT mlat, mlon,
       COUNT(DISTINCT CASE WHEN binom IS NOT NULL AND binom <> '' THEN binom END) AS species_n,
       COUNT(DISTINCT CASE WHEN binom IS NOT NULL AND binom <> '' AND rl_n > 0 THEN binom END) AS rl_species_n
FROM mesh_species_agg
GROUP BY mlat, mlon
"""

_CREATE_SPECIES_MESH_YEAR_SQL = "CREATE TABLE species_mesh_year (binom, year INT, mlat INT, mlon INT, n)"
# 主要種（species2.n >= 80。全年・全記録で判定済みの本物の species2 を読む）。
_SPECIES_MESH_YEAR_INSERT_SQL = """
INSERT INTO species_mesh_year (binom, year, mlat, mlon, n)
SELECT binom, year, mlat, mlon, SUM(n) AS n
FROM occ_agg_enriched
WHERE binom IN (SELECT binom FROM species2 WHERE n >= 80) AND year BETWEEN 1970 AND 2026
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
    """
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
# 10テーブルまとめて1ファイルに書く（main() が使う）
# ---------------------------------------------------------------------------

def build_all_projections(
    cube_db, registry_db, out_path, taxon_group_yaml=DEFAULT_TAXON_GROUP_YAML,
) -> dict[str, int]:
    """`org_norm` ＋ 年キー8表 ＋ `species_month` の10テーブルを、1つの
    `fresh_sqlite` 接続で `out_path` に書く（`org_norm` を先に作ってから
    年キー8表・`species_month` を作る——後者が `species2` を読むため、かつ
    `occurrence_agg` に対する古い taxon 検査を重ねがけしないため。モジュール
    docstring参照）。戻り値はテーブルごとの行数。
    """
    _assert_prerequisites(cube_db, registry_db, need_occurrence_agg=True)
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        n_org_norm = _build_org_norm(conn, default_taxon_group)
        counts = _build_cube_projections(conn, default_taxon_group, check_stale_taxon=False)
        conn.commit()
        return {"org_norm": n_org_norm, **counts}
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
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {args.cube_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("v1 形（10テーブル）へ射影して書き出し") as info:
        counts = build_all_projections(args.cube_db, registry_db, args.out, args.taxon_group_yaml)
        info["n"] = sum(counts.values())

    for table, n in sorted(counts.items()):
        print(f"  {table}: {n:,}行")


if __name__ == "__main__":
    main()
