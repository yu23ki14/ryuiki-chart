#!/usr/bin/env python3
"""`observation_agg`（`data/db/v2.sqlite`、b04 が作ったキューブ）を v1 の派生
テーブル形（`meas_daily`/`meas_month`/`meas_year`）に射影する
（ADR-0016 Phase B「ファクトとキューブ」縦に薄い1本）。

    .venv/bin/python3 scripts/b05_project_v1.py

`data/db/v1_projection.sqlite`（毎回ゼロから作り直す、専用の出力ファイル）に
3テーブルを書く。列名・列順は `reports/derived_baseline.json` の記録と
完全に一致させてある（`scripts/b02_derived_compare.py --tables
meas_daily,meas_month,meas_year` がそのまま突き合わせられるように）。

## 数値はキューブから、ラベルは引き戻しで

`observation_agg` の数値列（`value`/`n`/`n_censored` 等）をそのまま使う。v1 の
ラベル列（`site_id`/`variable`/`unit`）は、キューブの次元キーから**引き戻して**
作る:

  - `site_id` ← `place_source_ref`（`place_id` → `external_key`）の逆引き。
    `place_source_ref`（`source_id='sites.site_id'`）が `place_id` について単射である
    ことを、一意インデックスを張る前に検証する（`_materialize_lookup_tables`）。
    崩れていれば素の `IntegrityError` ではなく、実例つきで説明して止まる。
  - `variable` ← `(variable_id, value_grain, obs_stat, unit_id) → alias` の逆引き。
    **この対応が関数であることを実行時に assert する**（`assert_alias_is_function`）。
    実測では衝突0件だが、将来 alias が増えて壊れたら `MIN(alias)` を黙って選ばず
    ここで止まる。
  - `unit` ← `cube.observation`（キューブではなくファクト）から
    `(variable_id, value_grain, obs_stat, unit_id) → unit_raw` を逆引きする
    （`_UNIT_LOOKUP_SQL`。`observation_agg`（ADR-0011）は `unit_raw` を持たない
    ——b04・design.md D3 参照。原表記は「キューブが運ぶもの」ではなく
    「射影がファクトから引き戻すもの」に位置づけを変えた。CLAUDE.md の
    「レジストリの語彙ではないデータの癖は、それを使う画面・モジュール側に
    1箇所だけ置く」と同じ原則）。**この対応が関数であることも実行時に assert
    する**（`assert_unit_raw_is_function`）。実測では同一系列内の unit_raw は
    常に1種類（衝突0件）だが、2種以上あれば `MigrationError` で止める——
    黙って `MAX()` で1つを選ばない。

  **注意: `assert_alias_is_function` が検証するのは
  `(variable_id, grain, stat, unit_id) → alias` の関数性であって、v1 の
  `GROUP BY variable` を復元するのに実際に効くのは逆方向（`alias → tuple`）である。
  そちらは関数ではない（12 alias が2〜3個の tuple に対応。pH/COD/SS/BOD 等。
  アドバイザー指摘）。同じ site_id がそういう alias を共有する2出典を持つと、
  b04 は2セル作り、b05 は同じ (site_id, variable, d) の行を2つ出してしまう
  （v1 は1グループ）。今は実データで0件だが無防備なため、射影した3テーブル
  それぞれについて v1 のキー（`reports/derived_baseline.json` の
  `tables.<table>.key`）が一意であることを実行後に検証する
  （`assert_v1_keys_are_unique`。`assert_alias_is_function` は別の壊れ方
  （順方向の衝突）を捕まえるのでそのまま残す）。**

## meas_year のピボット（design.md D5・D6）

`observation_agg` の年次セルは `stat` ごとに別の行（`mean`/`min`/`max`）になって
いる（b04）。ここで同じ次元キーの3行を1行（`avg`/`min`/`max` の3列）に
まとめ直す。`kind` は `input_grain='day'` なら `'daily'`、そうでなければ
`'annual'`（キューブの `grain` が `'year'`（暦年）か `'fiscal_year'`（年度）かに
関わらず、v1 の `kind` はこの2値しか持たない）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import common  # noqa: E402

DEFAULT_CUBE_DB = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_OUT = ROOT / "data" / "db" / "v1_projection.sqlite"
DEFAULT_BASELINE_JSON = ROOT / "reports" / "derived_baseline.json"

# `variable_alias` の逆引き。`(variable_id, grain, stat, unit_id)` の組ごとに
# alias が複数あると射影が一意に決まらない。probe（design.md 実測）では衝突0件
# だったが、宣言せず信じるのではなく毎回 assert する（`assert_alias_is_function`）。
#
# NULL を含みうる `grain`/`stat`/`unit_id` を JOIN 条件で `IS` 比較すると
# SQLite は自動インデックスを使わず（`IS` は等値インデックスの対象にならない）、
# `observation_agg`（61万行超）とのネストループが実測で数分かかる。そのため
# `alias_lookup`/`year_keyed` は一時テーブルとして実体化し、NULL を空文字に
# 正準化した「結合キー」列にインデックスを張って通常の等値 JOIN にする
# （`_materialize_lookup_tables` 参照）。
_ALIAS_LOOKUP_SQL = """
SELECT variable_id, grain, stat, unit_id, alias,
       variable_id || '|' || COALESCE(grain, '') || '|' || COALESCE(stat, '') || '|' ||
       COALESCE(unit_id, '') AS akey
FROM reg.variable_alias
WHERE dataset = 'measurements'
GROUP BY variable_id, grain, stat, unit_id
"""

# `unit` の逆引き（B-1）。`observation_agg`（ADR-0011 のキューブ）は `unit_raw`
# を持たないため、`cube.observation`（キューブではなくファクト）から
# `(variable_id, value_grain, obs_stat, unit_id) → unit_raw` を引く。列名は
# `observation_agg`/`obs_agg_keyed` 側と揃っている（`variable_id`/`value_grain`/
# `obs_stat`/`unit_id`）ので、`akey` は同じ式でそのまま計算でき、
# `alias_lookup` と同じやり方（akey に一意インデックスを張った通常の等値 JOIN）
# で結合できる。`MAX(unit_raw)` は「複数候補から1つ選ぶ」のではなく
# （`assert_unit_raw_is_function` が同一 akey 内の unit_raw が常に1種類である
# ことを別途 assert する）、GROUP BY の構文上ここに集約関数が要るために書いている
# だけ——値そのものは唯一に決まっている前提で読む。
_UNIT_LOOKUP_SQL = """
SELECT variable_id, value_grain, obs_stat, unit_id,
       variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' ||
       COALESCE(unit_id, '') AS akey,
       MAX(unit_raw) AS unit_raw
FROM cube.observation
GROUP BY variable_id, value_grain, obs_stat, unit_id
"""

# `observation_agg` 側にも同じ形の結合キーを持つ VIEW を張る（`c.akey` として参照）。
_OBS_AGG_KEYED_VIEW_SQL = """
CREATE TEMP VIEW obs_agg_keyed AS
SELECT *,
       variable_id || '|' || COALESCE(value_grain, '') || '|' || COALESCE(obs_stat, '') || '|' ||
       COALESCE(unit_id, '') AS akey
FROM cube.observation_agg
"""

_MEAS_DAILY_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable, c.period_start AS d,
       c.value AS value, c.n AS n_raw, c.n_censored AS n_censored, ul.unit_raw AS unit
FROM obs_agg_keyed c
JOIN place_lookup psr ON psr.place_id = c.place_id
JOIN alias_lookup al ON al.akey = c.akey
JOIN unit_lookup ul ON ul.akey = c.akey
WHERE c.grain = 'day'
"""

_MEAS_MONTH_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable,
       substr(c.period_start, 1, 7) AS ym,
       CAST(substr(c.period_start, 1, 4) AS INT) AS year,
       CAST(substr(c.period_start, 6, 2) AS INT) AS month,
       c.n AS n, c.value AS avg, ul.unit_raw AS unit
FROM obs_agg_keyed c
JOIN place_lookup psr ON psr.place_id = c.place_id
JOIN alias_lookup al ON al.akey = c.akey
JOIN unit_lookup ul ON ul.akey = c.akey
WHERE c.grain = 'month'
"""

# 年次セルは stat ごとに別行（b04）。同じグループを1行にまとめるための結合キー
# （NULL を含みうる obs_stat/unit_id を NULL-safe に比較する代わりに、
# 文字列に連結した1本のキーで JOIN する。design.md D6「射影側でピボット」）。
_MEAS_YEAR_SQL = """
SELECT psr.external_key AS site_id, al.alias AS variable,
       CASE WHEN m.input_grain = 'day' THEN 'daily' ELSE 'annual' END AS kind,
       CAST(substr(m.period_start, 1, 4) AS INT) AS year,
       m.n AS n, m.value AS avg, mn.value AS min, mx.value AS max,
       m.n_censored AS n_censored, ul.unit_raw AS unit
FROM year_keyed m
JOIN year_keyed mn ON mn.gkey = m.gkey AND mn.stat = 'min'
JOIN year_keyed mx ON mx.gkey = m.gkey AND mx.stat = 'max'
JOIN unit_lookup ul ON ul.akey = m.akey
JOIN place_lookup psr ON psr.place_id = m.place_id
JOIN alias_lookup al ON al.akey = m.akey
WHERE m.stat = 'mean'
"""

_TABLE_SQL = {
    "meas_daily": _MEAS_DAILY_SQL,
    "meas_month": _MEAS_MONTH_SQL,
    "meas_year": _MEAS_YEAR_SQL,
}


def _materialize_lookup_tables(work: sqlite3.Connection) -> None:
    """自動インデックスの効かない `IS`（NULL-safe）JOIN を、実体化した一時
    テーブル＋インデックスの通常の等値 JOIN に置き換える（このモジュールの
    冒頭コメント参照。`observation_agg` 61万行超 × `variable_alias` 79行の
    ネストループが実測で数分かかっていたのを解消する）。
    """
    work.execute(_OBS_AGG_KEYED_VIEW_SQL)
    work.execute(f"CREATE TEMP TABLE alias_lookup AS {_ALIAS_LOOKUP_SQL}")
    work.execute("CREATE UNIQUE INDEX alias_lookup_akey ON alias_lookup (akey)")
    # `unit_lookup`（B-1）: `observation`（ファクト）から引いた unit_raw の逆引き。
    # `assert_unit_raw_is_function` が「同一 akey 内の unit_raw は1種類だけ」を
    # 別途 assert しているので、ここでは素直に実体化するだけでよい。
    work.execute(f"CREATE TEMP TABLE unit_lookup AS {_UNIT_LOOKUP_SQL}")
    work.execute("CREATE UNIQUE INDEX unit_lookup_akey ON unit_lookup (akey)")
    work.execute(
        """
        CREATE TEMP TABLE year_keyed AS
        SELECT *,
               place_id || '|' || akey || '|' || period_start || '|' || input_grain AS gkey
        FROM obs_agg_keyed
        WHERE grain IN ('year', 'fiscal_year')
        """
    )
    work.execute("CREATE INDEX year_keyed_gkey_stat ON year_keyed (gkey, stat)")
    # `reg` は読み取り専用で ATTACH してあるので、そちらにインデックスは張れない
    # （張ろうとすると sqlite3 が書き込みエラーを投げる）。`sites.site_id` の
    # 行だけを一時テーブルに複製してから張る。
    work.execute(
        "CREATE TEMP TABLE place_lookup AS "
        "SELECT place_id, external_key FROM reg.place_source_ref WHERE source_id = 'sites.site_id'"
    )
    # `CREATE UNIQUE INDEX` は `place_source_ref`（`source_id='sites.site_id'`）が
    # `place_id` について単射であることを暗黙に仮定している。崩れていた場合、
    # 何も検証せずにインデックスを張ると素の `sqlite3.IntegrityError` になり、
    # 本当の問題（キューブのキー `place_id` から v1 の `site_id` を復元できない）が
    # 伝わらない（レビュー指摘）。先に重複を検出し、実例つきで説明して止まる。
    dup_places = work.execute(
        "SELECT place_id, COUNT(*) AS n FROM place_lookup GROUP BY place_id HAVING n > 1 LIMIT 5"
    ).fetchall()
    if dup_places:
        raise common.MigrationError(
            "place_source_ref（source_id='sites.site_id'）が place_id について単射でない"
            f"（同じ place_id に複数の external_key（site_id）が対応している。例: {dup_places}）。"
            "キューブのキー place_id から v1 の site_id を一意に復元できないため、射影が"
            "決まらない。place_source_ref 側の重複を解消してから再実行すること。"
        )
    work.execute("CREATE UNIQUE INDEX place_lookup_place_id ON place_lookup (place_id)")


def assert_alias_is_function(work) -> None:
    """`(variable_id, grain, stat, unit_id) → alias` が関数であることを確認する
    （design.md「b05 の受け入れ条件」相当）。衝突があれば、どの組が何個の alias に
    割れているかを示して止まる——`MIN(alias)` 等で黙って1つを選ばない。
    """
    dup = work.execute(
        f"""
        SELECT variable_id, grain, stat, unit_id, COUNT(DISTINCT alias) AS n_alias
        FROM reg.variable_alias
        WHERE dataset = 'measurements'
        GROUP BY variable_id, grain, stat, unit_id
        HAVING n_alias > 1
        """
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "(variable_id, grain, stat, unit_id) -> alias が関数になっていない"
            f"（同じ組に複数の alias がある）: {dup}\n"
            "b05 は『どちらの alias を v1 の variable 名として使うか』を推測できないため、"
            "variable_alias 側の重複を解消してから再実行すること。"
        )


def assert_unit_raw_is_function(work) -> None:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` が関数で
    あることを確認する（B-1）。`cube.observation`（ファクト）を見る——
    `observation_agg`（ADR-0011 のキューブ）は unit_raw を持たない。実測では
    衝突0件（1つの variable は1種類の単位しか持たない）だが、将来2種以上の
    unit_raw を持つ系列が現れたら、どの組が何種に割れているかを示して止まる
    ——`unit_lookup` の `MAX(unit_raw)` で黙って1つを選ばない。
    """
    dup = work.execute(
        """
        SELECT variable_id, value_grain, obs_stat, unit_id, COUNT(DISTINCT unit_raw) AS n_unit_raw
        FROM cube.observation
        GROUP BY variable_id, value_grain, obs_stat, unit_id
        HAVING n_unit_raw > 1
        """
    ).fetchall()
    if dup:
        raise common.MigrationError(
            "(variable_id, value_grain, obs_stat, unit_id) -> unit_raw が関数になっていない"
            f"（同じ系列に複数の unit_raw がある）: {dup}\n"
            "b05 は『どの unit_raw を v1 の unit 表記として使うか』を推測できないため、"
            "該当する系列の unit_raw の食い違いを解消してから再実行すること。"
        )


def _load_v1_keys(baseline_json_path) -> dict[str, list[str]]:
    """`reports/derived_baseline.json` の `tables.<table>.key` を読む
    （`scripts/b02_derived_compare.py` が同じ列を『ベースラインの一意キー』として
    使っているのと同じ定義。ここで独自にキー列を決め直さない）。
    """
    data = json.loads(pathlib.Path(baseline_json_path).read_text(encoding="utf-8"))
    return {table: list(data["tables"][table]["key"]) for table in _TABLE_SQL}


def assert_v1_keys_are_unique(
    projections: dict[str, tuple[list[str], list[tuple]]], keys_by_table: dict[str, list[str]]
) -> None:
    """射影した3テーブルそれぞれについて、v1（`derived_baseline.json`）のキー列で
    行が一意であることを確認する（アドバイザー指摘・オーナー採用）。

    `assert_alias_is_function` は `(variable_id, grain, stat, unit_id) → alias` を
    関数として検証するが、v1 の `GROUP BY variable` を復元するのに実際に効くのは
    **逆向き**（`alias → tuple`）で、そちらは今日も関数ではない（12 alias が
    2〜3個の (variable_id, value_grain, obs_stat, unit_id) に対応している）。
    同じ site_id が、そういう alias を共有する2出典の観測を持つと、b04 は
    （tuple が違うので）2セル作り、b05 は同じ (site_id, variable, d) 等の行を
    2つ出してしまう（v1 は1グループにまとまる）。実データでは0件だが、
    黙って信用せず実行のたびに確認する。
    """
    for table, (columns, rows) in projections.items():
        key_cols = keys_by_table[table]
        idx = [columns.index(c) for c in key_cols]
        counts: dict[tuple, int] = {}
        for row in rows:
            k = tuple(row[i] for i in idx)
            counts[k] = counts.get(k, 0) + 1
        dup = [(k, n) for k, n in counts.items() if n > 1][:5]
        if dup:
            raise common.MigrationError(
                f"{table}: v1 のキー {key_cols} が一意でない行がある（例（キー, 件数）: {dup}）。"
                "alias が複数の (variable_id, value_grain, obs_stat, unit_id) に対応している"
                "ため v1 の GROUP BY variable を復元できない（同じ site_id がそれらの出典を"
                "両方持つ場合に重複が起きる）。variable_alias 側で alias を出典ごとに"
                "分けるなど、v1 の1グループに対応する alias を1つに絞ってから再実行すること。"
            )


def build_projections(
    cube_db, registry_db, baseline_json=DEFAULT_BASELINE_JSON
) -> dict[str, list[tuple]]:
    """3テーブルぶんの `(columns, rows)` を返す（ファイルには書かない）。"""
    # プライベートな :memory: 接続（レビュー指摘。`scripts/b03_build_observation.py`
    # の同種の修正と同じ理由——`file::memory:?cache=shared` は共有する理由が
    # 無いのに接続間のテーブルロックという失敗モードだけを増やす）。ATTACH は
    # `try` の中で行い、片方が失敗しても `work` を漏らさない。
    work = sqlite3.connect(":memory:", uri=True)
    try:
        common.attach_readonly(work, cube_db, "cube")
        common.attach_readonly(work, registry_db, "reg")
        assert_alias_is_function(work)
        assert_unit_raw_is_function(work)
        _materialize_lookup_tables(work)
        out = {}
        for table, sql in _TABLE_SQL.items():
            cur = work.execute(sql)
            columns = [d[0] for d in cur.description]
            out[table] = (columns, cur.fetchall())
        assert_v1_keys_are_unique(out, _load_v1_keys(baseline_json))
        return out
    finally:
        work.close()


_CREATE_SQL = {
    "meas_daily": (
        "CREATE TABLE meas_daily (site_id TEXT, variable TEXT, d TEXT, value REAL, "
        "n_raw INTEGER, n_censored INTEGER, unit TEXT)"
    ),
    "meas_month": (
        "CREATE TABLE meas_month (site_id TEXT, variable TEXT, ym TEXT, year INTEGER, "
        "month INTEGER, n INTEGER, avg REAL, unit TEXT)"
    ),
    "meas_year": (
        "CREATE TABLE meas_year (site_id TEXT, variable TEXT, kind TEXT, year INTEGER, "
        "n INTEGER, avg REAL, min REAL, max REAL, n_censored INTEGER, unit TEXT)"
    ),
}


def write_projections(projections: dict[str, tuple[list[str], list[tuple]]], out_path) -> None:
    conn = common.fresh_sqlite(out_path)
    try:
        for table, (columns, rows) in projections.items():
            conn.execute(_CREATE_SQL[table])
            placeholders = ", ".join("?" for _ in columns)
            conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cube-db", default=str(DEFAULT_CUBE_DB), help="observation_agg を持つ v2.sqlite")
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--baseline-json",
        default=str(DEFAULT_BASELINE_JSON),
        help="v1 のキー列を読む derived_baseline.json（assert_v1_keys_are_unique 用）",
    )
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)
    print(f"▶ 読み取り専用で開く: {args.cube_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("v1 形へ射影") as info:
        projections = build_projections(args.cube_db, registry_db, args.baseline_json)
        info["n"] = sum(len(rows) for _, rows in projections.values())

    with common.timed_step(f"{args.out} に書き出し") as info:
        write_projections(projections, args.out)
        info["n"] = sum(len(rows) for _, rows in projections.values())

    for table, (_, rows) in sorted(projections.items()):
        print(f"  {table}: {len(rows):,}行")


if __name__ == "__main__":
    main()
