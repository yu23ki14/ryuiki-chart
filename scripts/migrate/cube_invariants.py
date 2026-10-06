"""キューブ・registry の自己無矛盾の検証関数群（Issue #48 PR-5。
`v1_projection_checks.py`〔v1 射影 b05 の検証〕の後継）。

v1 と突き合わせる検証（v1 のキー列の一意性・ゾーンの `fraction=1.0`・ゾーン番号の
衝突など）はここに**移していない**——v1 射影固有で、v1 の撤去とともに消えた。
ここにあるのは「キューブ（`observation_agg`/`occurrence_agg`）と、それを作る入力
（`observation`・`reg.variable_alias`・`reg.place_source_ref`）が、v1 の有無に依らず
自分自身で満たすべき条件」だけ。呼ぶのは各ビルダー（b04/b07/b09）。

呼び出し側の流儀は `period.py`/`occurrence_period.py` と同じ
（`cube_invariants.関数名(...)` と呼ぶ。再エクスポートしない）。
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from migrate import common

_SAMPLE_LIMIT = 20

# ---------------------------------------------------------------------------
# registry: variable_alias（b04）
# ---------------------------------------------------------------------------

# 既知の登録負債（黙って grain を狭めて見逃さず、定数と理由つきで除外する）。
# `sensor_timeseries` の積雪3変数は、CSV の列名が年度によって揺れていて同じ
# `(variable_id, grain='month', stat, unit_id)` に2つの alias 文字列が対応している
# （例: '雪_最深 積雪'／'雪_最深積雪'。全角スペースの有無だけの違い）。
# 月次（`grain='month'`）のこの重複は、日次・毎時の射影が消費する範囲の外にあり、
# キューブのセルにも二重には現れない（b03 は alias で `variable_id` を引くだけ）。
# registry 側で alias を統一したらこの定数も空にすること。
KNOWN_DUPLICATE_ALIAS_SERIES: frozenset[tuple[str, str, str]] = frozenset({
    ("sensor_timeseries", "common:variable:weather.snow_depth_max", "month"),
    ("sensor_timeseries", "common:variable:weather.snowfall_depth_max_daily", "month"),
    ("sensor_timeseries", "common:variable:weather.snowfall_depth_total", "month"),
})


def assert_alias_is_function(conn: sqlite3.Connection) -> None:
    """`(dataset, variable_id, grain, stat, unit_id) → alias` が関数であること
    （`reg.variable_alias` 全体。土地利用の年版 `<source>@<年>` は dataset ごとに
    別に見るので、年ごとに独立して検証される）。衝突があれば、どの組が何個の alias に
    割れているかを示して止まる——`MIN(alias)` 等で黙って1つを選ばない。
    `KNOWN_DUPLICATE_ALIAS_SERIES` の組だけは既知の負債として除外する。
    """
    dups = conn.execute(
        """
        SELECT dataset, variable_id, grain, stat, unit_id, COUNT(DISTINCT alias) AS n_alias
        FROM reg.variable_alias
        GROUP BY dataset, variable_id, grain, stat, unit_id
        HAVING n_alias > 1
        """
    ).fetchall()
    dups = [d for d in dups if (d[0], d[1], d[2]) not in KNOWN_DUPLICATE_ALIAS_SERIES]
    if dups:
        raise common.MigrationError(
            "(dataset, variable_id, grain, stat, unit_id) -> alias が関数になっていない"
            f"（同じ組に複数の alias がある。例: {dups[:5]}）。\n"
            "キューブの系列がどちらの alias の観測なのかを引き戻せなくなるため、"
            "variable_alias 側の重複を解消してから再実行すること。"
        )


def assert_alias_tuple_maps_to_single_dataset(conn: sqlite3.Connection) -> None:
    """`(variable_id, grain, stat, unit_id)` が複数の出典（`measurements`/
    `sensor_timeseries`/土地利用の本体名）にまたがっていないこと。崩れていると
    同じキューブのセルがどの出典のものか決まらない。

    版付き dataset（`<source>@<年>`。ADR-0005）は `@` より前（出典本体）に正規化して
    から比べる——土地利用は同じ tuple を意図して複数の年版にまたがって再利用する
    （P-1b オーナー決定2）ため、正規化しないと版の数だけ誤検出する。一方、
    土地利用と measurements/sensor_timeseries が同じ tuple を持てば別の出典名の
    まま残るので検出できる。
    """
    common.raise_on_group_by_duplicates(
        conn,
        """
        SELECT variable_id, grain, stat, unit_id,
               COUNT(DISTINCT base_dataset) AS n_dataset,
               GROUP_CONCAT(DISTINCT base_dataset) AS datasets
        FROM (
            SELECT variable_id, grain, stat, unit_id,
                   CASE WHEN instr(dataset, '@') > 0
                        THEN substr(dataset, 1, instr(dataset, '@') - 1)
                        ELSE dataset END AS base_dataset
            FROM reg.variable_alias
        )
        GROUP BY variable_id, grain, stat, unit_id
        HAVING n_dataset > 1
        """,
        (),
        lambda dup: (
            "(variable_id, grain, stat, unit_id) が複数の出典（版のサフィックスを"
            f"正規化した後）にまたがっている（例: {dup}）。\n"
            "variable_alias 側で tuple が出典をまたいで重複しないようにしてから"
            "再実行すること。"
        ),
    )


# ---------------------------------------------------------------------------
# observation: unit_raw（b04）
# ---------------------------------------------------------------------------

def assert_unit_raw_is_function(conn: sqlite3.Connection) -> None:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` が関数であること
    （1つの系列は1つの単位表記しか持たない）。`observation`（`measurements`/
    `sensor_timeseries` の両方）全体を見る。
    """
    common.raise_on_group_by_duplicates(
        conn,
        """
        SELECT variable_id, value_grain, obs_stat, unit_id, COUNT(DISTINCT unit_raw) AS n_unit_raw
        FROM observation
        GROUP BY variable_id, value_grain, obs_stat, unit_id
        HAVING n_unit_raw > 1
        LIMIT 5
        """,
        (),
        lambda dup: (
            "(variable_id, value_grain, obs_stat, unit_id) -> unit_raw が関数になっていない"
            f"（同じ系列に複数の unit_raw がある。例: {dup}）。\n"
            "1系列に複数の単位表記が混ざったまま集計されるのを防ぐため、"
            "該当する系列の unit_raw の食い違いを解消してから再実行すること。"
        ),
    )


# ---------------------------------------------------------------------------
# T6: 毎時→日次の正しさ（b04）
# ---------------------------------------------------------------------------

_HOUR_SERIES_DIM = "region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain"


def verify_hourly_daily_rollup(conn: sqlite3.Connection, staging: str, sample_limit: int = _SAMPLE_LIMIT) -> dict:
    """`value_grain='hour'` の各系列・各日 D について、
    **キューブの日次セルの n = ラベル日割り（`period_raw` の先頭10桁）の日 D の n
    − (日 D のラベル 00 時の件数) + (日 D+1 のラベル 00 時の件数)**
    が全日で成り立つことを検証する（T6。b03 が hour_ending を「ラベル−1時間」で
    区間の始まりへ直しているので、ラベル 00:00 の観測は前日のセルに入る）。
    あわせて、系列ごとの全期間の Σn・min・max が `observation` と
    キューブの日次セルで一致することも確認する。

    `conn` は `observation` と、`staged_table` の作業用テーブル `staging`
    （`observation_agg` と同じ形）を持つこと。どちらか一方でも崩れていれば
    `common.MigrationError` で止まる。戻り値は検証した件数（レポート用）。

    日付の1日進めは Python（`date.fromisoformat`）で行う——`+09:00` 付きの時刻
    文字列に SQLite の日時関数を使わない（ADR-0024）。日ごとの集計に MIN/MAX も
    足して1回のスキャンで済ませ、系列ごとの合計は日次の結果から Python で再集計する
    （MIN/MAX は丸め誤差が無いので、全期間を直接スキャンした値とビット単位で一致する）。
    """
    obs_daily = conn.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, substr(period_raw, 1, 10) AS d,
               COUNT(*) AS n,
               SUM(CASE WHEN substr(period_raw, 12, 8) = '00:00:00' THEN 1 ELSE 0 END) AS n_midnight,
               MIN(value_num) AS vmin, MAX(value_num) AS vmax
        FROM observation
        WHERE value_grain = 'hour' AND value_num IS NOT NULL
        GROUP BY {_HOUR_SERIES_DIM}, d
        """
    ).fetchall()

    # キューブの日次セル（stat='mean'。n は mean/min/max のどれでも同じ値）。
    cube_daily = conn.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, period_start AS d, n
        FROM "{staging}"
        WHERE grain = 'day' AND input_grain = 'hour' AND stat = 'mean'
        """
    ).fetchall()

    obs_n: dict[tuple, int] = {}
    obs_midnight: dict[tuple, int] = {}
    tot_n: dict[tuple, int] = {}
    tot_min: dict[tuple, float] = {}
    tot_max: dict[tuple, float] = {}
    for row in obs_daily:
        key, d = row[:7], row[7]
        n, n_midnight, vmin, vmax = row[8], row[9], row[10], row[11]
        obs_n[(key, d)] = n
        obs_midnight[(key, d)] = n_midnight
        tot_n[key] = tot_n.get(key, 0) + n
        tot_min[key] = vmin if key not in tot_min else min(tot_min[key], vmin)
        tot_max[key] = vmax if key not in tot_max else max(tot_max[key], vmax)

    cube_n: dict[tuple, int] = {(row[:7], row[7]): row[8] for row in cube_daily}

    all_days = set(obs_n) | set(cube_n)
    mismatches: list[tuple] = []
    for key, d in all_days:
        d_next = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        expected = obs_n.get((key, d), 0) - obs_midnight.get((key, d), 0) + obs_midnight.get((key, d_next), 0)
        actual = cube_n.get((key, d), 0)
        if expected != actual:
            mismatches.append((key, d, expected, actual))
    if mismatches:
        raise common.MigrationError(
            "T6: キューブの日次セルの n がラベル日割りから期待される値と"
            f"食い違う日がある（{len(mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, 日, 期待値, 実際の値)）: {mismatches[:sample_limit]}）。"
            "scripts/migrate/period.py の hour_ending 変換（ラベル-1時間）または"
            "scripts/b04_build_cube.py の日割り（substr(period_start,1,10)）を確認すること。"
        )

    # 系列ごとの全期間の Σn・min・max。ADR-0009 決定4: この検証は
    # `sensor_timeseries`（censoring は常に 'none'）が対象で、`value_zero` と
    # `value_lod` は同じ値になるので `value_zero` を読む。
    cube_totals = conn.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM},
               SUM(CASE WHEN stat = 'mean' THEN n END) AS n,
               MIN(CASE WHEN stat = 'min' THEN value_zero END) AS vmin,
               MAX(CASE WHEN stat = 'max' THEN value_zero END) AS vmax
        FROM "{staging}"
        WHERE grain = 'day' AND input_grain = 'hour'
        GROUP BY {_HOUR_SERIES_DIM}
        """
    ).fetchall()
    obs_by_key = {key: (tot_n[key], tot_min[key], tot_max[key]) for key in tot_n}
    cube_by_key = {row[:7]: row[7:] for row in cube_totals}
    total_mismatches = []
    for key in set(obs_by_key) | set(cube_by_key):
        o, c = obs_by_key.get(key), cube_by_key.get(key)
        if o != c:
            total_mismatches.append((key, o, c))
    if total_mismatches:
        raise common.MigrationError(
            "T6: 系列ごとの全期間の Σn・min・max が observation とキューブの日次セルで"
            f"食い違う（{len(total_mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, observation側(n,min,max), キューブ側(n,min,max))）: "
            f"{total_mismatches[:sample_limit]}）。"
        )

    return {"n_series_days_checked": len(all_days), "n_series_checked": len(set(obs_by_key) | set(cube_by_key))}


# ---------------------------------------------------------------------------
# b07: 流域セルの (place, 年) 粒度の保存則
# ---------------------------------------------------------------------------

def assert_place_year_totals_match_population(
    conn: sqlite3.Connection, staging: str, pop_table: str, place_kind: str,
    year_grains: tuple[str, ...], measure_select: str, sample_limit: int = _SAMPLE_LIMIT,
) -> int:
    """`place_kind` の年族セル（`place_id IS NOT NULL`）を (place_id, 年) に畳んだ
    n/n_red_list/n_alien が、母集団（`pop_table`）を同じ粒度で畳んだものと一致する
    こと。b07 既存の系列粒度（source_id, taxon_id）の検査を place×年へ細かくしたもの
    ——系列の合計は合っていて、place や年の間で数字が入れ替わる壊れ方を捕まえる。
    `place_id IS NULL`（どの流域にも入らない記録）は place が無いので対象外
    （その件数は b07 の宣言検証が見る）。戻り値は検証した (place, 年) の数。
    """
    grain_list = ", ".join(repr(g) for g in year_grains)
    left_sql = (
        f"SELECT place_id, substr(period_start, 1, 4) AS yr, {measure_select} "
        f'FROM "{pop_table}" WHERE place_id IS NOT NULL GROUP BY place_id, yr'
    )
    right_sql = (
        "SELECT place_id, substr(period_start, 1, 4) AS yr, "
        "SUM(n) AS n, SUM(n_red_list) AS n_red_list, SUM(n_alien) AS n_alien "
        f'FROM "{staging}" WHERE place_kind = \'{place_kind}\' AND grain IN ({grain_list}) '
        "AND place_id IS NOT NULL GROUP BY place_id, yr"
    )
    common.assert_grouped_totals_match(
        conn, left_sql, right_sql,
        key_columns=["place_id", "yr"],
        value_columns=["n", "n_red_list", "n_alien"],
        build_message=lambda rows: (
            f"occurrence_agg: (place_id, 年)（place_kind={place_kind!r}）ごとの "
            "Σn/Σn_red_list/Σn_alien が母集団と食い違う（キューブが記録を別の place・年に"
            f"付け替えている、漏らしている可能性がある。例（上限{sample_limit}件、"
            "(place_id, 年, n_母集団, n_キューブ, n_red_list_母集団, n_red_list_キューブ, "
            f"n_alien_母集団, n_alien_キューブ)）: {rows}）。"
        ),
        sample_limit=sample_limit,
    )
    return conn.execute(
        f'SELECT COUNT(*) FROM (SELECT 1 FROM "{pop_table}" WHERE place_id IS NOT NULL '
        "GROUP BY place_id, substr(period_start, 1, 4))"
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# b09: place_id と place_source_ref の関係
# ---------------------------------------------------------------------------

MESH_SOURCE_ID = "organism_records.lat_lon"


def assert_place_source_ref_is_injective(conn: sqlite3.Connection, source_id: str) -> None:
    """`reg.place_source_ref(source_id=...)` が `place_id` について単射であること
    （同じ place_id に複数の external_key が対応していない）。`place_id` から
    `external_key`（流域 ID・メッシュ座標）を一意に復元できる前提。
    """
    common.raise_on_group_by_duplicates(
        conn,
        "SELECT place_id, COUNT(*) AS c FROM reg.place_source_ref "
        "WHERE source_id = ? GROUP BY place_id HAVING c > 1 LIMIT 5",
        (source_id,),
        lambda dup: (
            f"place_source_ref（source_id={source_id!r}）が place_id について単射でない"
            f"（同じ place_id に複数の external_key が対応している。例: {dup}）。"
            "place_id から external_key を一意に復元できない。"
        ),
    )


def assert_occurrence_places_resolve(conn: sqlite3.Connection, source_id: str = MESH_SOURCE_ID) -> None:
    """`occurrence.place_id`（b06 が座標から解決した grid01 の place。NULL は座標なしの
    正常系）が、すべて `reg.place_source_ref(source_id=...)` で引けること。引けない
    place_id は registry と occurrence の版がずれている異常——黙って NULL に落とさず止める。
    """
    # 記録ごとの相関サブクエリにせず、distinct な place_id（数百〜数千）だけを引く
    # （80万行の occurrence を place_source_ref に総当たりさせない）。
    bad = conn.execute(
        """
        SELECT COUNT(*) FROM (SELECT DISTINCT place_id FROM occurrence WHERE place_id IS NOT NULL) d
        LEFT JOIN (SELECT DISTINCT place_id FROM reg.place_source_ref WHERE source_id = ?) r
          ON r.place_id = d.place_id
        WHERE r.place_id IS NULL
        """,
        (source_id,),
    ).fetchone()[0]
    if bad:
        raise common.MigrationError(
            f"occurrence: place_id はあるのに place_source_ref(source_id={source_id!r}) で"
            f"引けない place_id が{bad:,}種ある（registry.sqlite と occurrence の版がずれている、"
            "または grid01 以外の place_id が混ざっている可能性がある。"
            "scripts/r01_build_registry.py と b06 を同じ版で揃えて再実行すること）。"
        )
