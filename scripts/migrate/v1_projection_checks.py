"""`scripts/b05_project_v1.py`（`observation_agg` → v1形13テーブルの射影）が
使う検証関数群（`PHASE_B_FACT_SLICE.md:457-459` 決定: 「次に出典固有の検証
関数を足す時点で、検証関数群を別モジュールに分ける」を実施したもの——振る舞い
は変えない純粋な移動）。

`scripts/b05_project_v1.py` は `from migrate import v1_projection_checks` で
このモジュールを import し、`v1_projection_checks.assert_alias_is_function(...)`
のように呼ぶ（`scripts/migrate/period.py`/`occurrence_period.py` を b03/b06 が
モジュールごと import して `period.func()` の形で呼ぶのと同じ流儀）。既存の
呼び出し側（`scripts/b05_project_v1.py` 自身の内部呼び出し、
`scripts/tests/test_b05_project_v1.py` の `b05.関数名(...)` という既存の
呼び出し）は、`b05_project_v1.py` 側に張った再エクスポート（同名の
モジュール変数への代入）でそのまま動く——このモジュールへの分割で
外部から見た `b05_project_v1` の API は1つも変わらない。

ここに置くのは「`work`（`cube`/`reg` を ATTACH 済みの一時接続）の中身を検証
するだけの関数」（副作用は無い、`common.MigrationError` を投げるかどうか
だけ）。SQL を組み立てて実際にテーブルを作る側（`_materialize_lookup_tables`
等）は `b05_project_v1.py` に残す——このモジュールは検証専用。
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import date, timedelta

from migrate import common

# ---------------------------------------------------------------------------
# D11: ゾーン（`place_relation`）の射影固有の前提
# ---------------------------------------------------------------------------

def _assert_place_relation_table_exists(work: sqlite3.Connection) -> None:
    """`reg.place_relation` テーブルが存在することを確認する（無いと素の
    `sqlite3.OperationalError` になり原因が分かりにくいため）。理由は D11。
    """
    row = work.execute(
        "SELECT 1 FROM reg.sqlite_master WHERE type = 'table' AND name = 'place_relation'"
    ).fetchone()
    if row is None:
        raise common.MigrationError(
            "registry.sqlite に place_relation テーブルが無い（ADR-0022 決定2で新設された"
            "テーブルなので、それより前にビルドした古い registry.sqlite には無い）。"
            "scripts/r01_build_registry.py で registry.sqlite を作り直すこと。"
        )


def _assert_zone_numbers_do_not_collide_across_zone_places(work: sqlite3.Connection) -> None:
    """異なる place のゾーンが同じゾーン番号（`zone_raw`）に解決されていない
    ことを確認する（b05 が place_id ではなく番号だけでゾーンを区別すること
    から生じる、射影固有の前提）。理由は D11。
    """
    common.raise_on_group_by_duplicates(
        work,
        "SELECT zone_raw, COUNT(DISTINCT zone_place_id) AS n_places, "
        "GROUP_CONCAT(DISTINCT zone_place_id) AS zone_place_ids "
        "FROM site_zone_lookup GROUP BY zone_raw HAVING n_places > 1 LIMIT 5",
        (),
        lambda dup: (
            f"異なるゾーンの place が同じゾーン番号に解決されている: {dup}\n"
            "zone_year/zone_clim はゾーン番号（整数）だけを鍵にしているため、"
            "由来の違うゾーンが1行に混ざる前に止める。"
        ),
    )


def _assert_zone_edges_have_fraction_one(work: sqlite3.Connection) -> None:
    """`site_zone_lookup` の `fraction` が全行1.0であることを確認する
    （v1 を非加重で再現するという b05 固有の前提。レジストリ全体の不変条件
    ではない）。理由は D11。
    """
    bad = work.execute(
        "SELECT site_id, zone_place_id, fraction FROM site_zone_lookup "
        "WHERE fraction <> 1.0 LIMIT 5"
    ).fetchall()
    if bad:
        raise common.MigrationError(
            "地点→ゾーンの辺（place_relation, relation='within'、sites.zone に解決"
            f"できたもの）に fraction が1.0でないものがある（例（site_id, zone_place_id, "
            f"fraction）: {bad}）。zone_year/zone_clim の射影は非加重の前提（v1 と同じ"
            " AVG()）で書かれており、この前提が崩れている。"
        )


def _assert_site_maps_to_at_most_one_zone(work: sqlite3.Connection) -> None:
    """`site_zone_lookup` で1つの地点が複数行を持たないことを確認する
    （結合そのものの安全性。r01 がレジストリ側で既に保証しているが、b05側の
    防御としても残す）。理由は D11。
    """
    common.raise_on_group_by_duplicates(
        work,
        "SELECT site_id, COUNT(*) AS n FROM site_zone_lookup GROUP BY site_id HAVING n > 1 LIMIT 5",
        (),
        lambda dup: (
            f"複数のゾーンに属する（またはゾーンへの辺が重複している）地点がある: {dup}\n"
            "v1 の sites.zone は単一列であり、zone_year/zone_clim は地点が1つの"
            "ゾーンにのみ、1本の辺で対応することを前提にしている。"
        ),
    )


# ---------------------------------------------------------------------------
# T5: 逆引きの検証（tuple の一意性 / 関数性）
# ---------------------------------------------------------------------------

def assert_alias_is_function(work, dataset: str = "measurements", grains: tuple[str, ...] | None = None) -> None:
    """`(variable_id, grain, stat, unit_id) → alias` が `dataset` 内で関数で
    あることを確認する。衝突があれば、どの組が何個の alias に割れているかを
    示して止まる——`MIN(alias)` 等で黙って1つを選ばない。

    `grains` を渡すと、その grain（`value_grain`）だけに絞って検証する。
    実データで `sensor_timeseries`/`jma_monthly_kanagawa` の積雪関連3変数
    （`weather.snow_depth_max`/`snowfall_depth_total`/
    `snowfall_depth_max_daily`）に、CSV の列名が年度によって揺れている
    らしく同じ `(variable_id, grain='month', stat, unit_id)` に2つの alias
    文字列（例: `'雪_最深 積雪'`／`'雪_最深積雪'`。全角スペースの有無だけの
    違い）が対応していることが実測で判明した。`sensor_daily`/`rain_daily`/
    `sensor_hour_month`（T5）はどれも `value_grain IN ('day','hour','instant')`
    しか消費せず、`grain='month'`（jma_monthly の出典配布月次値。design.md
    実測の要点「v1 の射影対象外」）は射影しない——この重複は b05 が実際に
    読む範囲の外にあるので、呼び出し側が `grains` で消費範囲だけに絞って
    検証する（月次の重複自体は登録の負債として残るが、機能には影響しない）。
    """
    grain_filter = ""
    params: tuple = (dataset,)
    if grains is not None:
        placeholders = ", ".join("?" for _ in grains)
        grain_filter = f" AND grain IN ({placeholders})"
        params = (dataset, *grains)
    common.raise_on_group_by_duplicates(
        work,
        f"""
        SELECT variable_id, grain, stat, unit_id, COUNT(DISTINCT alias) AS n_alias
        FROM reg.variable_alias
        WHERE dataset = ?{grain_filter}
        GROUP BY variable_id, grain, stat, unit_id
        HAVING n_alias > 1
        """,
        params,
        lambda dup: (
            f"({dataset}) (variable_id, grain, stat, unit_id) -> alias が関数になっていない"
            f"（同じ組に複数の alias がある）: {dup}\n"
            "b05 は『どちらの alias を v1 の variable/datastream 名として使うか』を推測できない"
            "ため、variable_alias 側の重複を解消してから再実行すること。"
        ),
    )


def assert_alias_tuple_maps_to_single_dataset(work) -> None:
    """`(variable_id, grain, stat, unit_id)` が `measurements`/
    `sensor_timeseries`/土地利用（本体の出典名。版のサフィックスは正規化して
    落とす）の間でまたがっていないことを確認する（設計 v2 T5）。崩れていると、
    同じキューブのセルが複数の出力テーブルに二重に現れる——各テーブルの
    逆引き JOIN は `dataset` ごとに絞っているだけで、tuple 自体が2つの
    dataset にまたがらないことまでは保証していないため。実測では衝突0件だが、
    `assert_alias_is_function` が捕まえる壊れ方（順方向の衝突）とは別の
    壊れ方なので、そのまま残す。

    **版付き dataset（`<source>@<year>`。ADR-0005「同じ出典に複数版が
    同居する」実例、土地利用 P-1b）は `@` より前（出典本体）に正規化してから
    比較する**——土地利用は同じ (variable_id, grain, stat, unit_id) を意図して
    複数の年版にまたがって再利用する（例: `田` は2006/2016のどちらも
    `variable_id=landuse.paddy, grain=year, stat=sum, unit_id=km2`。P-1b
    オーナー決定2「同じ日本語名の区分は年をまたいで同じ variable_id を
    共有する」）ため、正規化しないと版の数だけ誤検出してしまう。正規化後は
    `nlni_l03b_landuse_by_watershed@2006`/`@2016` はどちらも
    `nlni_l03b_landuse_by_watershed` という**同じ**出典名になるので
    `COUNT(DISTINCT ...)` は1のまま——一方で `measurements`/
    `sensor_timeseries` はそもそも `@` を含まないため正規化の影響を受けず、
    これらと土地利用側の tuple が衝突すれば正規化後も別の出典名のまま
    残るので、引き続き検出できる（コードレビュー指摘4:
    「除外」ではなく「正規化して比較」にすることで、この検証本来の保護範囲を
    狭めない）。
    """
    common.raise_on_group_by_duplicates(
        work,
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
            f"正規化した後）にまたがっている（同じキューブのセルが複数の出力テーブルに"
            f"二重に現れる恐れがある）: {dup}\nvariable_alias 側で tuple が出典をまたいで"
            "重複しないようにしてから再実行すること。"
        ),
    )


def assert_unit_raw_is_function(work) -> None:
    """`(variable_id, value_grain, obs_stat, unit_id) → unit_raw` が関数で
    あることを確認する（B-1）。`cube.observation`（ファクト）全体——
    `measurements`/`sensor_timeseries` の両方——を見る。実測では衝突0件
    （1つの系列は1種類の単位しか持たない）だが、将来2種以上の unit_raw を
    持つ系列が現れたら、どの組が何種に割れているかを示して止まる。
    """
    common.raise_on_group_by_duplicates(
        work,
        """
        SELECT variable_id, value_grain, obs_stat, unit_id, COUNT(DISTINCT unit_raw) AS n_unit_raw
        FROM cube.observation
        GROUP BY variable_id, value_grain, obs_stat, unit_id
        HAVING n_unit_raw > 1
        """,
        (),
        lambda dup: (
            "(variable_id, value_grain, obs_stat, unit_id) -> unit_raw が関数になっていない"
            f"（同じ系列に複数の unit_raw がある）: {dup}\n"
            "b05 は『どの unit_raw を v1 の unit 表記として使うか』を推測できないため、"
            "該当する系列の unit_raw の食い違いを解消してから再実行すること。"
        ),
    )


# ---------------------------------------------------------------------------
# v1 のキー列での一意性（アドバイザー指摘・オーナー採用）
# ---------------------------------------------------------------------------

def load_v1_keys(baseline_json_path, table_names) -> dict[str, list[str]]:
    """`derived_baseline.json` から `table_names` それぞれのキー列を読む。

    元は `b05_project_v1.py` の `_load_v1_keys(baseline_json_path)` で、
    テーブル名の集合を `b05_project_v1._TABLE_SQL`（モジュール変数）から
    暗黙に取っていた。このモジュールを `b05_project_v1` から独立させるため
    `table_names` を明示の引数にした（呼び出し側の `b05_project_v1.py` は
    `_TABLE_SQL` を渡す薄いラッパを持つ——振る舞いは変わらない）。
    """
    data = json.loads(pathlib.Path(baseline_json_path).read_text(encoding="utf-8"))
    return {table: list(data["tables"][table]["key"]) for table in table_names}


def assert_v1_keys_are_unique(
    projections: dict[str, tuple[list[str], list[tuple]]], keys_by_table: dict[str, list[str]]
) -> None:
    """射影したテーブルそれぞれについて、v1（`derived_baseline.json`）のキー列
    で行が一意であることを確認する（アドバイザー指摘・オーナー採用）。
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
                "ため v1 の GROUP BY を復元できない。variable_alias 側で alias を出典ごとに"
                "分けるなど、v1 の1グループに対応する alias を1つに絞ってから再実行すること。"
            )


# ---------------------------------------------------------------------------
# T6: 毎時→日次の正しさの機械検証
# ---------------------------------------------------------------------------

_HOUR_SERIES_DIM = "region_id, place_id, place_kind, variable_id, obs_stat, unit_id, value_grain"


def verify_hourly_daily_rollup(work: sqlite3.Connection, sample_limit: int = 20) -> dict:
    """`value_grain='hour'` の各系列・各日 D について、
    **キューブの日次セルの n = v1形（L2 のラベル日割り）の日 D の n
    − (日 D のラベル 00 時の件数) + (日 D+1 のラベル 00 時の件数)**
    が全日で成り立つことを検証する（T6）。あわせて、系列ごとの全期間の
    Σn・min・max がキューブの日次セルと L2 で一致することも確認する。

    どちらか一方でも崩れていれば `common.MigrationError` で止まる。
    戻り値は検証した件数（レポート用）。`_materialize_lookup_tables` の後
    （`label25_obs_keyed`/`day_keyed` を使う）に呼ぶ。

    C-4: `value_grain='hour'` の絞り込み（`label25_obs_keyed`）は以前、
    日ごとの件数（v1形）用と系列ごとの全期間 Σn・min・max 用の2つの別クエリで
    2回スキャンしていた。日ごとの集計に `MIN`/`MAX` を足して1回のスキャンで
    済ませ、系列ごとの合計（Σn・min・max）はその日次結果から Python で
    再集計する（Σn は日ごとの n の和、min/max は日ごとの min/max の
    min/max——どちらも再スキャンせず正確に求まる。MIN/MAX は選択演算であり
    加算のような丸め誤差が無いため、日次から再集計しても全期間を直接
    スキャンした場合とビット単位で一致する）。
    """
    # 日ごとの v1形の件数・「ラベルが00:00:00（日をまたぐ24時ラベル）の件数」・
    # min/max を同じクエリで求める（C-4: 1回のスキャン）。
    v1_daily = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, substr(period_raw, 1, 10) AS d,
               COUNT(*) AS n,
               SUM(CASE WHEN substr(period_raw, 12, 8) = '00:00:00' THEN 1 ELSE 0 END) AS n_midnight,
               MIN(value_num) AS vmin, MAX(value_num) AS vmax
        FROM label25_obs_keyed
        WHERE value_grain = 'hour' AND value_num IS NOT NULL
        GROUP BY {_HOUR_SERIES_DIM}, d
        """
    ).fetchall()

    # キューブの日次セル（stat='mean'。n は mean/min/max のどれでも同じ値）。
    # day_keyed は value_grain IN ('day','instant') のみに絞って作られている
    # ため（`_materialize_lookup_tables`）、ここでは observation_agg を直接見る。
    cube_daily = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM}, period_start AS d, n
        FROM cube.observation_agg
        WHERE grain = 'day' AND input_grain = 'hour' AND stat = 'mean'
        """
    ).fetchall()

    v1_n: dict[tuple, int] = {}
    v1_midnight: dict[tuple, int] = {}
    # C-4: 系列ごとの全期間 Σn・min・max を、日次の行から再集計しながら作る
    # （l2_totals を別クエリで取り直さない）。
    l2_n: dict[tuple, int] = {}
    l2_min: dict[tuple, float] = {}
    l2_max: dict[tuple, float] = {}
    for row in v1_daily:
        key = row[:7]
        d = row[7]
        n, n_midnight, vmin, vmax = row[8], row[9], row[10], row[11]
        v1_n[(key, d)] = n
        v1_midnight[(key, d)] = n_midnight
        l2_n[key] = l2_n.get(key, 0) + n
        l2_min[key] = vmin if key not in l2_min else min(l2_min[key], vmin)
        l2_max[key] = vmax if key not in l2_max else max(l2_max[key], vmax)

    cube_n: dict[tuple, int] = {}
    for row in cube_daily:
        key = row[:7]
        d = row[7]
        cube_n[(key, d)] = row[8]

    all_days = set(v1_n) | set(cube_n)
    mismatches: list[tuple] = []
    for key, d in all_days:
        d_next = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        expected = v1_n.get((key, d), 0) - v1_midnight.get((key, d), 0) + v1_midnight.get((key, d_next), 0)
        actual = cube_n.get((key, d), 0)
        if expected != actual:
            mismatches.append((key, d, expected, actual))
    if mismatches:
        raise common.MigrationError(
            "T6: キューブの日次セルの n が v1形のラベル日割りから期待される値と"
            f"食い違う日がある（{len(mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, 日, 期待値, 実際の値)）: {mismatches[:sample_limit]}）。"
            "scripts/migrate/period.py の hour_ending 変換（ラベル-1時間）または"
            "scripts/b04_build_cube.py の日割り（substr(period_start,1,10)）を確認すること。"
        )

    # 系列ごとの全期間の Σn・min・max が一致すること。L2 側（`l2_by_key`）は
    # 上で日次から再集計済み（C-4）——ここで label25_obs_keyed を読み直さない。
    cube_totals = work.execute(
        f"""
        SELECT {_HOUR_SERIES_DIM},
               SUM(CASE WHEN stat = 'mean' THEN n END) AS n,
               MIN(CASE WHEN stat = 'min' THEN value END) AS vmin,
               MAX(CASE WHEN stat = 'max' THEN value END) AS vmax
        FROM cube.observation_agg
        WHERE grain = 'day' AND input_grain = 'hour'
        GROUP BY {_HOUR_SERIES_DIM}
        """
    ).fetchall()
    l2_by_key = {key: (l2_n[key], l2_min[key], l2_max[key]) for key in l2_n}
    cube_by_key = {row[:7]: row[7:] for row in cube_totals}
    total_mismatches = []
    for key in set(l2_by_key) | set(cube_by_key):
        l2_vals = l2_by_key.get(key)
        cube_vals = cube_by_key.get(key)
        if l2_vals != cube_vals:
            total_mismatches.append((key, l2_vals, cube_vals))
    if total_mismatches:
        raise common.MigrationError(
            "T6: 系列ごとの全期間の Σn・min・max が L2 とキューブの日次セルで食い違う"
            f"（{len(total_mismatches)}件。例（上限{sample_limit}件、"
            f"(次元キー, L2側(n,min,max), キューブ側(n,min,max))）: "
            f"{total_mismatches[:sample_limit]}）。"
        )

    return {"n_series_days_checked": len(all_days), "n_series_checked": len(set(l2_by_key) | set(cube_by_key))}
