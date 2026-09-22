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
を書く。列名は `reports/derived_baseline.json` の記録と一致させてある
（`scripts/b02_derived_compare.py --candidate ... --tables ...`
がそのまま突き合わせられるように。列**順**は `b02` が列名で SELECT するため
無関係——`scripts/reconcile/datasource.py` の `fetch_rows` 参照）。

## O-1a: `org_norm`（`occurrence`＝L2 から）

設計・規則は変更なし（`_build_org_norm`/`build_org_norm_projection`。旧版の
振る舞いをそのまま維持——値は1ビットも変えない）。詳細は各関数の docstring。

## O-1b: 年キー8表は `occurrence_agg`（キューブ）だけから（ADR-0025 D3）

`org_group_year`/`effort_year`/`species2`/`species_year2`/`mesh_year`/
`mesh_all`/`mesh_species`/`species_mesh_year` は **`occurrence_agg` だけ**から
作る（`occurrence`（L2）を読まない。例外は `species2.en_name`/
`red_list_category` だけ——後述）。

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
  の `mlat`/`mlon` と一致する）。
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

## テーブルごとのフィルタは射影側（キューブには無い）

`yr BETWEEN 1970 AND 2026`（`org_group_year`/`effort_year`/`species_year2`/
`mesh_year`/`species_mesh_year`）・`species2.n >= 80`（全年・全記録。
`species_mesh_year`/`species_month` が使う）・`lat IS NOT NULL`
（`mesh_year`/`mesh_species`。実データでは常に真だが、将来座標欠損セルが
増えても黙って混ぜない防御として残す）は、すべて `_build_cube_projections`
の SQL 側に書く（v1 の SQL 自体にこれらのフィルタがある。`web/scripts/
build-biota.mjs` 参照）。`species2` 自体・`mesh_all`/`mesh_species` には
年フィルタが無い（v1 のとおり。`mesh_all` は年フィルタ済みの `mesh_year`
から積み上げるので結果的に年範囲は同じだが、`mesh_species` は本当に
全期間を対象にする——`docs/plans/PHASE_B_OCCURRENCE.md` O-1b 節の実測
「mesh_all と mesh_species の件数が3件違う」参照）。

## 古い registry を検出する（コードレビュー指摘7。O-1a から踏襲）

`occurrence.taxon_id`/`occurrence_agg.taxon_id` は構築時点の `registry.taxon`
に実在することを検証済みだが、`v2.sqlite` と `registry.sqlite` は別々に
作り直せるファイルなので、古い `registry.sqlite`（taxon が入れ替わった・
減った版）に対して実行すると検出漏れが起きうる。`_assert_no_stale_taxon_ids`
が `occurrence`/`occurrence_agg` それぞれの `taxon_id` の distinct 値を
`registry.taxon` と突き合わせ、食い違えば書き込みの前に止める。

## 書き込みは `INSERT ... SELECT`（コードレビュー指摘8・10。O-1a から踏襲）

`org_norm` と同様、年キー8表・`species_month` も出力ファイルへ書き込み用に
開いた1つの接続に `cube`/`reg` を ATTACH し、`INSERT INTO <table> (<列名>)
SELECT ...` を実行する（Python 側に行のリストを保持しない）。
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

# ---------------------------------------------------------------------------
# 古い registry の検出（O-1a のコードレビュー指摘7を一般化。`table` は
# `cube.occurrence`/`cube.occurrence_agg` のどちらでも使う）。
# ---------------------------------------------------------------------------

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
        raise common.MigrationError(
            f"registry.taxon に無い taxon_id が{stale}種ある"
            f"（{context}.taxon_id は NULL ではないのに、registry 側にその taxon が無い＝"
            f"{context} 構築後に registry.sqlite が taxon を含まない版に入れ替わった疑いがある）。"
            f"同じ registry.sqlite で{context}を再ビルドするか、registry.sqlite を"
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
    切り出しただけ）。
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
_OCC_AGG_ENRICHED_SQL = """
CREATE TEMP TABLE occ_agg_enriched AS
SELECT c.source_id,
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
"""

# species2.en_name/red_list_category の例外（occurrence＝L2 の原表記から
# binom ごとに集計。モジュール docstring 参照）。
_SPECIES2_L2_EXTRAS_SQL = """
CREATE TEMP TABLE species2_l2_extras AS
SELECT t.canonical_binomial AS binom,
       MAX(COALESCE(NULLIF(o.vernacular_name, ''), '')) AS en_name,
       MAX(COALESCE(o.red_list_category, '')) AS red_list_category
FROM cube.occurrence o
LEFT JOIN reg.taxon t ON t.taxon_id = o.taxon_id
WHERE o.period_raw IS NOT NULL AND t.canonical_binomial IS NOT NULL AND t.canonical_binomial <> ''
GROUP BY t.canonical_binomial
"""

_CREATE_ORG_GROUP_YEAR_SQL = (
    "CREATE TABLE org_group_year (year INTEGER, taxon_group TEXT, source_id TEXT, "
    "n INTEGER, species_n INTEGER, mesh_n INTEGER)"
)
_ORG_GROUP_YEAR_INSERT_SQL = """
INSERT INTO org_group_year (year, taxon_group, source_id, n, species_n, mesh_n)
SELECT year, taxon_group, source_id, SUM(n) AS n,
       COUNT(DISTINCT binom) AS species_n,
       COUNT(DISTINCT mlat || '_' || mlon) AS mesh_n
FROM occ_agg_enriched
WHERE year BETWEEN 1970 AND 2026
GROUP BY year, taxon_group, source_id
"""

_CREATE_EFFORT_YEAR_SQL = (
    "CREATE TABLE effort_year (year INTEGER, n INTEGER, species_n INTEGER, mesh_n INTEGER, "
    "n_inat INTEGER, n_gbif INTEGER)"
)
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
    "CREATE TABLE species2 (binom TEXT, taxon_group TEXT, cls TEXT, family TEXT, "
    "en_name TEXT, red_list_category TEXT, n INTEGER, y_from INTEGER, y_to INTEGER, "
    "n_years INTEGER, mesh_n INTEGER)"
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

_CREATE_SPECIES_YEAR2_SQL = "CREATE TABLE species_year2 (binom TEXT, year INTEGER, n INTEGER, mesh_n INTEGER)"
_SPECIES_YEAR2_INSERT_SQL = """
INSERT INTO species_year2 (binom, year, n, mesh_n)
SELECT binom, year, SUM(n) AS n, COUNT(DISTINCT mlat || '_' || mlon) AS mesh_n
FROM occ_agg_enriched
WHERE binom IS NOT NULL AND binom <> '' AND year BETWEEN 1970 AND 2026
GROUP BY binom, year
"""

_CREATE_MESH_YEAR_SQL = (
    "CREATE TABLE mesh_year (mlat INTEGER, mlon INTEGER, year INTEGER, "
    "n INTEGER, species_n INTEGER, rl_n INTEGER)"
)
_MESH_YEAR_INSERT_SQL = """
INSERT INTO mesh_year (mlat, mlon, year, n, species_n, rl_n)
SELECT mlat, mlon, year, SUM(n) AS n, COUNT(DISTINCT binom) AS species_n, SUM(n_red_list) AS rl_n
FROM occ_agg_enriched
WHERE mlat IS NOT NULL AND year BETWEEN 1970 AND 2026
GROUP BY mlat, mlon, year
"""

_CREATE_MESH_ALL_SQL = (
    "CREATE TABLE mesh_all (mlat INTEGER, mlon INTEGER, n INTEGER, rl_n INTEGER, "
    "y_from INTEGER, y_to INTEGER)"
)
# v1 のとおり mesh_year（すでに年 1970-2026 で絞ってある）から積み上げる。
_MESH_ALL_INSERT_SQL = """
INSERT INTO mesh_all (mlat, mlon, n, rl_n, y_from, y_to)
SELECT mlat, mlon, SUM(n) AS n, SUM(rl_n) AS rl_n, MIN(year) AS y_from, MAX(year) AS y_to
FROM mesh_year
GROUP BY mlat, mlon
"""

# mesh_species は年フィルタが無い（v1 のとおり。モジュール docstring 参照）。
# 先に (mesh, binom) 単位で n_red_list を合算してから DISTINCT を数える——
# 複数 taxon_id が同じ binom に対応する場合も binom で1つに畳まれる。
_MESH_SPECIES_AGG_SQL = """
CREATE TEMP TABLE mesh_species_agg AS
SELECT mlat, mlon, binom, SUM(n_red_list) AS rl_n
FROM occ_agg_enriched
WHERE mlat IS NOT NULL
GROUP BY mlat, mlon, binom
"""
_CREATE_MESH_SPECIES_SQL = (
    "CREATE TABLE mesh_species (mlat INTEGER, mlon INTEGER, species_n INTEGER, rl_species_n INTEGER)"
)
_MESH_SPECIES_INSERT_SQL = """
INSERT INTO mesh_species (mlat, mlon, species_n, rl_species_n)
SELECT mlat, mlon,
       COUNT(DISTINCT CASE WHEN binom IS NOT NULL AND binom <> '' THEN binom END) AS species_n,
       COUNT(DISTINCT CASE WHEN binom IS NOT NULL AND binom <> '' AND rl_n > 0 THEN binom END) AS rl_species_n
FROM mesh_species_agg
GROUP BY mlat, mlon
"""

_CREATE_SPECIES_MESH_YEAR_SQL = (
    "CREATE TABLE species_mesh_year (binom TEXT, year INTEGER, mlat INTEGER, mlon INTEGER, n INTEGER)"
)
# 主要種（species2.n >= 80。全年・全記録で判定済みの本物の species2 を読む）。
_SPECIES_MESH_YEAR_INSERT_SQL = """
INSERT INTO species_mesh_year (binom, year, mlat, mlon, n)
SELECT binom, year, mlat, mlon, SUM(n) AS n
FROM occ_agg_enriched
WHERE binom IN (SELECT binom FROM species2 WHERE n >= 80) AND year BETWEEN 1970 AND 2026
GROUP BY binom, year, mlat, mlon
"""

# species_month は occurrence（L2）から直接（モジュール docstring 参照）。
# yr/mo は org_norm と同じ式を period_raw に適用する。
_SPECIES_MONTH_L2_SQL = """
CREATE TEMP TABLE species_month_l2 AS
SELECT t.canonical_binomial AS binom,
       CAST(substr(o.period_raw, 1, 4) AS INT) AS yr,
       CASE WHEN length(o.period_raw) >= 7 THEN CAST(substr(o.period_raw, 6, 2) AS INT) END AS month
FROM cube.occurrence o
LEFT JOIN reg.taxon t ON t.taxon_id = o.taxon_id
WHERE o.period_raw IS NOT NULL
"""
_CREATE_SPECIES_MONTH_SQL = "CREATE TABLE species_month (binom TEXT, month INTEGER, n INTEGER)"
_SPECIES_MONTH_INSERT_SQL = """
INSERT INTO species_month (binom, month, n)
SELECT binom, month, COUNT(*) AS n
FROM species_month_l2
WHERE month IS NOT NULL AND yr >= 2018 AND binom IN (SELECT binom FROM species2 WHERE n >= 80)
GROUP BY binom, month
"""


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


def _build_cube_projections(conn, default_taxon_group: str) -> dict[str, int]:
    """`conn`（`cube`/`reg` を ATTACH 済みの書き込み用接続）に、年キー8表と
    `species_month` を作る。`species2` を先に作り終えてから
    `species_mesh_year`/`species_month` がそれを読む（v1 の依存順どおり）。
    戻り値はテーブルごとの行数。
    """
    _assert_no_stale_taxon_ids(conn, "cube.occurrence_agg", "occurrence_agg")

    conn.execute(_PLACE_MESH_LOOKUP_SQL)
    _assert_place_mesh_lookup_is_function(conn)
    conn.execute(_OCC_AGG_ENRICHED_SQL, (default_taxon_group,))
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

    conn.execute(_SPECIES_MONTH_L2_SQL)
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
    年キー8表・`species_month` を作る——後者が `species2` を読むため）。
    戻り値はテーブルごとの行数。
    """
    default_taxon_group = _load_default_taxon_group(taxon_group_yaml)
    conn = common.fresh_sqlite(out_path)
    try:
        common.attach_readonly(conn, cube_db, "cube")
        common.attach_readonly(conn, registry_db, "reg")
        n_org_norm = _build_org_norm(conn, default_taxon_group)
        counts = _build_cube_projections(conn, default_taxon_group)
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
