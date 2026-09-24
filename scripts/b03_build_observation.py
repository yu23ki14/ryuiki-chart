#!/usr/bin/env python3
"""`data/db/ryuiki.sqlite`（読み取り専用）の `measurements` と
`sensor_timeseries`、および `data/processed/nlni_l03b_landuse_by_watershed.csv`
（土地利用、L1）を、単一の縦持ちファクト `observation`（ADR-0007）にする
（ADR-0016 Phase B「ファクトとキューブ」。`measurements` だけの縦線は
`docs/plans/PHASE_B_FACT_SLICE.md`、`sensor_timeseries` を足したセンサーの
縦線の設計は「センサーの縦線 設計 v2」オーナー決定・ADR-0023・ADR-0024、
土地利用の縦線（P-1b）の設計は `docs/plans/PHASE_B_LANDUSE.md` 参照）。

    .venv/bin/python3 scripts/b03_build_observation.py

`data/db/v2.sqlite` の `observation` テーブルだけを作り直す
（`scripts/migrate/common.staged_table`。ファイル全体を作り直さない —
「ファイルではなくテーブル単位」節を参照）。`reports/phase_b_fact_slice.md` に
出典ごとの節を持つ人が読む要約を書く。**入力（`ryuiki.sqlite`/`registry.sqlite`/
土地利用CSV）は読み取り専用でしか開かない。**

## ファイルではなくテーブル単位で作り直す

以前は `data/db/v2.sqlite` をファイルごと作り直していた（`common.fresh_sqlite`）。
ADR-0007 は `measurements` と `sensor_timeseries` を同じ `observation` に
統合すると決めており、将来 `occurrence`（生物のファクト。ADR-0007 決定3）が
同じ `v2.sqlite` に増えたときにファイルごと作り直すと、b03 の実行が
`occurrence` を消してしまう。そこで b04 が `observation_agg` に対して
既にやっているのと同じパターン（`migrate.common.staged_table`）を
`observation` にも使う——DDL を `observation` テーブルだけに絞る。

## 検証が全部通ってから本番名に差し替える（A-1）

以前はここで `replace_table`（DROP+CREATE、本番テーブル名 `observation` に
対して実行）を検証より先に呼んでいた。出典ごとの取り込み失敗は
`dest.rollback()` で救えていたが、途中で `dest.commit()` を呼んでいたため
（出典ごとに1回）、**両出典の取り込み自体は成功したのに、その後の宣言表の
検証（未使用エントリ・`expected_row_count` の食い違い）や T1 不変条件の検証で
失敗した場合は、それより前の `commit()` の分がすでに確定してしまっており、
`observation` は新しい（まだ全部の検証を通っていない）内容に差し替わって
いて元に戻せなかった**（バグ）。

今は `migrate.common.staged_table` を使う。DDL・DML は作業用テーブル
（`observation__building`）にだけ行い、本番テーブル名 `observation` に触る
DDL は、取り込み・宣言表の検証・T1 不変条件の検証が**全部**通って `with`
ブロックを正常に抜けたときにしか実行しない。途中で何か1つでも失敗すれば
`conn.rollback()` してから作業用テーブルを `DROP` するだけで済み、本番の
`observation` は前回実行の内容のまま一切変更されない（`staged_table` の
docstring 参照。Python 3.6 以降の `sqlite3` は DDL の前に暗黙コミットしない
ため、`commit()`/`rollback()` を明示的に呼んで制御している）。

## 出典ごとにストリーム挿入する（`executemany`。C-5）

`measurements`（323,164行）だけならメモリに収まるが、`sensor_timeseries`
（717,839行）を足すと合計104万行になり、全行を Python のリストに溜めてから
`executemany` すると数百MBになる（実測前の見積もり。オーナー指摘）。そこで
出典（`measurements`/`sensor_timeseries`）ごとに、読み取り専用の JOIN 済み
カーソルを1行ずつ読むジェネレータをそのまま `dest.executemany()` に渡す
（リストに溜めない。行ごとの `execute()` 呼び出しをやめてドライバ側の一括
挿入に任せることで、実測で数秒短縮した——受け入れ条件7参照）。重複行
（`source_table`/`source_row_id` が衝突する行）は取り込み中の行検証
（`_process_row`。B-1）がジェネレータの時点で弾く（A-2: 数えるだけで挿入
しない。以前は数えた後も挿入を試みて `IntegrityError` で落ちていた）ため、
主キー相当の一意インデックス（`_CREATE_OBSERVATION_INDEX_SQL`）は全行の
挿入が終わった後に作る——一意性チェックを行ごとに割り込ませない分だけ速い。
検証用の使い捨てなので張った直後に `DROP INDEX` する（同定数のコメント
参照。固定名の索引を本番テーブルまで残すと、次回実行が同じ固定名で索引を
作ろうとしたときに名前衝突で壊れる——実測で踏んだ）。

1つの出典の取り込み全体は1つの sqlite トランザクションにし（`dest.commit()`
を出典ごとに1回だけ呼ぶ）。その出典で問題（alias/place 未解決・宣言に無い
期間の食い違い・重複行等）が1件でも見つかれば、統計を集め終えてから
`MigrationError` を投げる——例外は `staged_table` の `with` ブロックの外まで
伝播し、作業用テーブルが `DROP` される（黙って成功したことにはならない
——`main()` は例外を捕まえず素通しする）。

## このスクリプトが埋める列・埋めない列（ADR-0007 のうち実際に使うもの）

`measurements`/`sensor_timeseries` はどちらも「主語＝place（site）」
「値＝数量（`measurements` だけ検閲ありうる）」の観測しか持たないので、
ADR-0007 の全列のうち埋まるのは次のとおり。

埋める:
  - `source_table` / `source_row_id` — 旧 `source_measurement_id` の一般化
    （design.md T3）。`source_table` は `'measurements'`/`'sensor_timeseries'`、
    `source_row_id` はそれぞれ `measurement_id`（元々 TEXT）/
    `id`（元々 INTEGER。ここで `str()` にして運ぶ）。`observation_id` は
    発行しない（ADR-0016: 公開 ID の発行は Phase C）。
  - `region_id` / `place_id` / `place_kind` — `place_source_ref` 経由で解決
    （ハードコードしない。`place.region_id`/`place.place_kind` から引く）。
  - `variable_id` / `unit_id` / `obs_stat` / `value_grain`
    — `variable_alias`（`(dataset, alias, source_id)`。`dataset` は出典に
    応じて `'measurements'`/`'sensor_timeseries'`）から引く。`obs_stat` は
    ADR-0007 の `stat` に相当するが、alias 側の値は ADR-0007 が列挙する enum
    と一致しないため、キューブ自身の集計統計量（b04 の `stat`）と区別する
    目的で意図的に別名にしている。
  - `period_grain` / `period_start` / `period_end` — ADR-0008・ADR-0024（T1）。
    `measured_on`/`phenomenon_time` から展開する（`scripts/migrate/period.py`）。
  - `value_num` / `value_raw` / `censoring` / `censoring_limit` — ADR-0009。
    `measurements` だけ `scripts/migrate/censoring.py` で分類する。
    `sensor_timeseries` に検閲の概念は無い——`censoring` は常に `'none'`、
    `value_raw` は常に NULL、`value_num` は `sensor_timeseries.result` を
    そのまま運ぶ（`result IS NULL` の行はそのまま NULL。b04 の
    `WHERE v IS NOT NULL` で自然にキューブから外れる。design.md T3）。
  - `quality_stage` / `is_synthetic` / `source_ref` / `event_id` — 既にある
    列からの素の carry-over。`sensor_timeseries` にはこのうち `is_synthetic`
    しか対応する列が無いため、`quality_stage`/`source_ref`/`event_id` は
    `sensor_timeseries` 由来の行では常に NULL（新しい情報を捏造しない）。

埋めない（理由）:
  - `observation_id` — Phase C の仕事。
  - `taxon_id` / `feature_id` — どちらの出典も生物でも地物でもない量的観測。
  - `method_id` / `instrument_id` — ADR-0007 のこの2列はレジストリ参照を
    想定しているが、Phase A は method/instrument のレジストリを作っていない。
    `measurements.method`/`instrument_id` も `sensor_timeseries.instrument_id`
    （合成センサーの `'SYN-INSTR-WTLOG-01'` 等。0.7%行程度にのみ値あり）も
    自由記述でレジストリ ID ではないので、無理に詰めない（推測でマッピング
    しない）。
  - `observer_id` / `source_edition_id` — 対応する列が無い/レジストリが
    まだ無い（Phase C の仕事）。
  - `value_text` — どちらの出典も値は常に量的（`measurements` は検閲
    ありうる数量、`sensor_timeseries` は REAL の `result`）で、テキスト値を
    持つ観測が無い。

## value_grain / period_grain の食い違い

通常は一致する。宣言的な例外表が2つある:
  - `scripts/migrate/period_exceptions.yaml`（`measurements` 専用。
    `atsugi_river_water_quality` の `measured_on` 4桁行、3,840行）。
  - `scripts/migrate/time_label_conventions.yaml`（`sensor_timeseries` の
    `value_grain='hour'` 出典専用。時刻ラベルの意味＝hour_ending の宣言。
    T2）。
宣言に無い食い違いに出会ったら（1行でも）例外を投げて止まる。どちらの
表も、エントリが1件も使われなかった場合・実測件数が宣言と食い違う場合は
止める（腐った宣言が残り続けないように）。

## alias / place 解決

`(dataset, alias, source_id)` と `place_source_ref(source_id='sites.site_id')`
は、この縦線の全1,041,003行（323,164 + 717,839）が解決するはず（design.md
実測）。1行でも解決できなければ、件数と実例を出して止まる（黙って捨てない・
黙って NULL にしない）。JOIN が1行を2行以上に増やしていないか（alias/place
の宣言が「関数」であるはずが実は多対応になっていないか）も同時に確認する。

## T1 不変条件

`observation` の全行について、`period_start`/`period_end` に時刻帯
（`+`/`Z`）を含まないこと、および `date(period_start) = substr(period_start,1,10)`
（SQLite の `date()` 関数が時刻帯付き文字列を UTC 側に正規化してしまわない
こと）を、書き出した実際のテーブルに対して検証する（`scripts/migrate/period.py`
が時刻帯を落として計算しているはずだが、それを実行のたびに確かめる）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import functools
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import censoring, common, period, source_regions  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_EXCEPTIONS_YAML = ROOT / "scripts" / "migrate" / "period_exceptions.yaml"
DEFAULT_TIME_LABEL_CONVENTIONS_YAML = ROOT / "scripts" / "migrate" / "time_label_conventions.yaml"
DEFAULT_SOURCE_REGIONS_YAML = ROOT / "scripts" / "migrate" / "source_regions.yaml"
DEFAULT_LANDUSE_CSV = ROOT / "data" / "processed" / "nlni_l03b_landuse_by_watershed.csv"
DEFAULT_OUT = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REPORT = ROOT / "reports" / "phase_b_fact_slice.md"

# P-1b（土地利用、docs/plans/PHASE_B_LANDUSE.md）。CSV の source_id 列は全行
# この定数値（`data/processed/nlni_l03b_landuse_by_watershed.csv` を実測して
# 確認済み）。source_regions.yaml の sources キー・observation.source_table・
# variable_alias.csv の dataset 接頭辞のすべてがこの文字列を共有する。
LANDUSE_SOURCE_ID = "nlni_l03b_landuse_by_watershed"

_SAMPLE_LIMIT = 20

# LEFT JOIN で拾える範囲まで含めて全列を読む。alias/place が解決できない行も
# （検出のために）ここでは捨てず、後段の集計で NULL として数える。
_SELECT_MEASUREMENTS_SQL = """
SELECT
  m.measurement_id, m.site_id, m.measured_on, m.variable, m.source_id,
  m.value, m.value_raw, m.unit, m.quality_stage, m.is_synthetic, m.source_ref, m.event_id,
  a.variable_id, a.unit_id, a.stat, a.grain,
  psr.place_id, p.region_id, p.place_kind
FROM src.measurements m
LEFT JOIN reg.variable_alias a
  ON a.dataset = 'measurements' AND a.alias = m.variable
 AND (a.source_id = m.source_id OR (a.source_id IS NULL AND m.source_id IS NULL))
LEFT JOIN reg.place_source_ref psr
  ON psr.source_id = 'sites.site_id' AND psr.external_key = m.site_id
LEFT JOIN reg.place p ON p.place_id = psr.place_id
ORDER BY m.measurement_id
"""

_SELECT_SENSOR_SQL = """
SELECT
  st.id, st.site_id, st.phenomenon_time, st.datastream, st.source_id,
  st.result, st.unit, st.is_synthetic,
  a.variable_id, a.unit_id, a.stat, a.grain,
  psr.place_id, p.region_id, p.place_kind
FROM src.sensor_timeseries st
LEFT JOIN reg.variable_alias a
  ON a.dataset = 'sensor_timeseries' AND a.alias = st.datastream
 AND (a.source_id = st.source_id OR (a.source_id IS NULL AND st.source_id IS NULL))
LEFT JOIN reg.place_source_ref psr
  ON psr.source_id = 'sites.site_id' AND psr.external_key = st.site_id
LEFT JOIN reg.place p ON p.place_id = psr.place_id
ORDER BY st.id
"""

# `{table}` プレースホルダに本番名（`observation`）または作業用テーブル名
# （`observation__building`）を埋め込む（`migrate.common.staged_table` 参照。A-1）。
_CREATE_OBSERVATION_SQL = """
CREATE TABLE {table} (
  source_table    TEXT NOT NULL,
  source_row_id   TEXT NOT NULL,
  region_id       TEXT NOT NULL,
  place_id        TEXT NOT NULL,
  place_kind      TEXT NOT NULL,
  variable_id     TEXT NOT NULL,
  obs_stat        TEXT,
  unit_id         TEXT,
  unit_raw        TEXT,
  value_grain     TEXT NOT NULL,
  period_grain    TEXT NOT NULL,
  period_start    TEXT NOT NULL,
  period_end      TEXT NOT NULL,
  period_raw      TEXT NOT NULL,
  value_num       REAL,
  value_raw       TEXT,
  censoring       TEXT NOT NULL,
  censoring_limit REAL,
  quality_stage   TEXT,
  is_synthetic    INTEGER,
  source_ref      TEXT,
  event_id        TEXT
)
"""

# `(source_table, source_row_id)` の一意性は、以前は `CREATE TABLE` の
# `PRIMARY KEY` 句で挿入時に強制していた。C-5: 重複行は `_process_row`
# （A-2）が挿入前に弾くため、一意性はもう挿入の間ずっと維持する必要が無い
# ——全行を `executemany` で挿入し終えた後にまとめて索引を張る方が速い
# （挿入のたびに B-tree の一意性チェックを割り込ませない）。
#
# この索引は**検証用の使い捨て**——張った直後に `DROP INDEX` する
# （`build_and_write_observation` 参照）。`observation` を読む b04/b05 は
# `(source_table, source_row_id)` で絞り込まない（place_id・period 等で絞る）ため
# 恒久的な性能索引としては使われておらず、残す理由が無い。もう1つ理由がある:
# SQLite の索引名は DB 全体で一意で、`ALTER TABLE ... RENAME` は索引を追随
# させるが索引**名**自体は変えない。固定名の索引を本番名 `observation` まで
# 残すと、**次回**実行時に「新しい作業用テーブルへ同じ固定名で索引を張ろうと
# する」→「前回実行で本番名に差し替わった索引と名前が衝突して
# `OperationalError: index ... already exists`」で毎回2回目以降が壊れる
# （実測で踏んだ）。使い捨てて存在期間を「挿入直後の検証」だけに閉じることで、
# 名前は固定のままで衝突が起きなくなる。
_CREATE_OBSERVATION_INDEX_SQL = (
    "CREATE UNIQUE INDEX observation_source_row_pk ON {table} (source_table, source_row_id)"
)
_DROP_OBSERVATION_INDEX_SQL = "DROP INDEX IF EXISTS observation_source_row_pk"

_INSERT_SQL = """
INSERT INTO {table} (
  source_table, source_row_id, region_id, place_id, place_kind, variable_id, obs_stat,
  unit_id, unit_raw, value_grain, period_grain, period_start, period_end, period_raw,
  value_num, value_raw, censoring, censoring_limit,
  quality_stage, is_synthetic, source_ref, event_id
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _empty_stats(source_table: str) -> dict:
    return {
        "source_table": source_table,
        "total": 0,
        "n_observation": 0,
        "unresolved_alias_count": 0,
        "unresolved_alias_sample": [],
        "unresolved_place_count": 0,
        "unresolved_place_sample": [],
        "dup_ids_count": 0,
        "dup_ids_sample": [],
        "period_mismatch_count": 0,
        "period_mismatch_sample": [],
        "grain_mismatch_count": 0,
        "censoring_counts": {},
        "zero_imputed_count": 0,
    }


# B-2: 致命的な問題の判定を「`stats` の `*_count` が0でなければ報告する」という
# 規約で宣言する。各要素は (件数のキー, 対応するサンプル一覧のキー, サンプルの
# 表示上限（None なら `_SAMPLE_LIMIT` まで全部）, メッセージのテンプレート)。
# `grain_mismatch_count`/`zero_imputed_count` は致命的な問題ではない（宣言表で
# カバーされた想定内の食い違い／検閲の代入件数）ので、ここには含めない——
# 「`stats` にある `*_count` を無条件に全部拾う」のではなく、拾うべき集合を
# 明示的に宣言する（それ自体が規約）。
_PROBLEM_SPECS = (
    (
        "dup_ids_count", "dup_ids_sample", 5,
        "{table}: source_row_id が複数行にマッチした"
        "（alias/place の解決が「関数」でなくなっている）: {count}件"
        "（例: {sample}）",
    ),
    (
        "unresolved_alias_count", "unresolved_alias_sample", None,
        "{table}: variable_alias で解決できない行: "
        "{count}件（例: {sample}）",
    ),
    (
        "unresolved_place_count", "unresolved_place_sample", None,
        "{table}: place_source_ref で解決できない行: "
        "{count}件（例: {sample}）",
    ),
    (
        "period_mismatch_count", "period_mismatch_sample", None,
        "{table}: value_grain と period_grain が食い違い、かつ宣言表に"
        f"宣言が無い行がある: {{count}}件（例（上限{_SAMPLE_LIMIT}件）: {{sample}}）",
    ),
)


def _problems_from_stats(stats: dict) -> list[str]:
    """出典1つぶんの統計から、b03 を止めるべき問題のメッセージ一覧を作る
    （`measurements`/`sensor_timeseries` で共通。`_PROBLEM_SPECS` の宣言を
    なぞるだけで、出典ごとの分岐は無い）。
    """
    table = stats["source_table"]
    problems: list[str] = []
    for count_key, sample_key, sample_limit, template in _PROBLEM_SPECS:
        count = stats[count_key]
        if not count:
            continue
        sample = stats[sample_key][:sample_limit] if sample_limit is not None else stats[sample_key]
        problems.append(template.format(table=table, count=count, sample=sample))
    return problems


def _process_row(
    stats: dict,
    seen_ids: set,
    row_id: str,
    variable_label,
    source_id,
    site_id,
    measured_on: str,
    value_grain: str,
    variable_id,
    place_id,
    exceptions,
    usage,
    time_conventions=None,
    time_usage=None,
):
    """1行ぶんの共通検証（B-1: `_ingest_measurements`/`_ingest_sensor_timeseries`
    が個別に持っていた「重複検出→alias解決→place解決→`compute_period`→grainの
    食い違い集計」の5ブロックを1つに集約したもの）。

    行を捨てるべきとき（重複・alias/place 未解決・宣言に無い期間の食い違い）は
    `None` を返す——呼び出し側はこの行を挿入せず次の行へ進む（A-2: 重複を
    見つけても、ここでは数えるだけで `seen_ids` に足さないループへは進めない
    ＝挿入を試みない。以前は数えた後も挿入していて主キー違反の `IntegrityError`
    に化けていた）。それ以外は `(period_grain, period_start, period_end)` を
    返す——呼び出し側が出典固有の列（検閲の分類・挿入するタプル）を組み立てる。

    `UnknownTimeLabelConventionError`（`time_conventions` に無い
    `value_grain='hour'` の出典）はここで捕まえない——per-row の問題ではなく
    構造的な設定不足なので、呼び出し側まで即座に伝播させる
    （`scripts/migrate/period.py` の当該クラスの docstring 参照）。
    """
    stats["total"] += 1

    if row_id in seen_ids:
        stats["dup_ids_count"] += 1
        if len(stats["dup_ids_sample"]) < _SAMPLE_LIMIT:
            stats["dup_ids_sample"].append(row_id)
        return None
    seen_ids.add(row_id)

    if variable_id is None:
        stats["unresolved_alias_count"] += 1
        if len(stats["unresolved_alias_sample"]) < _SAMPLE_LIMIT:
            stats["unresolved_alias_sample"].append((row_id, variable_label, source_id))
        return None
    if place_id is None:
        stats["unresolved_place_count"] += 1
        if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
            stats["unresolved_place_sample"].append((row_id, site_id))
        return None

    try:
        period_grain, period_start, period_end = period.compute_period(
            measured_on, value_grain, source_id, exceptions, usage, time_conventions, time_usage,
        )
    except period.PeriodMismatchError:
        stats["period_mismatch_count"] += 1
        if len(stats["period_mismatch_sample"]) < _SAMPLE_LIMIT:
            stats["period_mismatch_sample"].append((row_id, source_id, measured_on, value_grain))
        return None

    if period_grain != value_grain:
        stats["grain_mismatch_count"] += 1

    return period_grain, period_start, period_end


def _ingest_measurements(work: sqlite3.Connection, dest: sqlite3.Connection, insert_table: str, exceptions, usage) -> dict:
    """`measurements` を1行ずつ読み、`insert_table`（作業用テーブル。
    `migrate.common.staged_table` が返す名前）へ `executemany` でストリーム
    挿入する（C-5）。共通の行検証は `_process_row`（B-1）。出典固有なのは
    検閲の分類（`censoring.classify_censoring`）と挿入する列の組み立てだけ。

    `dest` へのコミットは呼び出し側（`build_and_write_observation`）の
    責務——ここでは `executemany` するだけで `commit()` を呼ばない（出典ごとに
    1トランザクションにするため。モジュール docstring 参照）。
    """
    stats = _empty_stats("measurements")
    seen_ids: set[str] = set()
    censoring_counts: collections.Counter = collections.Counter()

    def rows():
        for row in work.execute(_SELECT_MEASUREMENTS_SQL):
            (
                measurement_id, site_id, measured_on, variable, source_id,
                value, value_raw, unit, quality_stage, is_synthetic, source_ref, event_id,
                variable_id, unit_id, obs_stat, value_grain,
                place_id, region_id, place_kind,
            ) = row

            result = _process_row(
                stats, seen_ids, measurement_id, variable, source_id, site_id,
                measured_on, value_grain, variable_id, place_id, exceptions, usage,
            )
            if result is None:
                continue
            period_grain, period_start, period_end = result

            cens, cens_limit = censoring.classify_censoring(value_raw)
            censoring_counts[cens] += 1
            value_num = censoring.resolve_value_num(cens, value)
            if cens in censoring.ZERO_IMPUTED_CENSORING:
                stats["zero_imputed_count"] += 1
            stats["n_observation"] += 1

            yield (
                "measurements", measurement_id, region_id, place_id, place_kind, variable_id, obs_stat,
                unit_id, unit, value_grain, period_grain, period_start, period_end, measured_on,
                value_num, value_raw, cens, cens_limit,
                quality_stage, is_synthetic, source_ref, event_id,
            )

    dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), rows())
    stats["censoring_counts"] = dict(censoring_counts)
    return stats


def _ingest_sensor_timeseries(
    work: sqlite3.Connection, dest: sqlite3.Connection, insert_table: str, exceptions, usage,
    time_conventions, time_usage,
) -> dict:
    """`sensor_timeseries` を1行ずつ読み、`insert_table` へストリーム挿入する
    （`_ingest_measurements` と対になる関数。検閲が無いこと・
    `time_conventions`/`time_usage` を `_process_row` に渡すことが違い。
    alias/place の解決・重複検出・期間計算の呼び出し方はそのまま共有——B-1）。
    """
    stats = _empty_stats("sensor_timeseries")
    seen_ids: set[str] = set()

    def rows():
        for row in work.execute(_SELECT_SENSOR_SQL):
            (
                row_id, site_id, phenomenon_time, datastream, source_id,
                result, unit, is_synthetic,
                variable_id, unit_id, obs_stat, value_grain,
                place_id, region_id, place_kind,
            ) = row
            row_id_str = str(row_id)

            processed = _process_row(
                stats, seen_ids, row_id_str, datastream, source_id, site_id,
                phenomenon_time, value_grain, variable_id, place_id, exceptions, usage,
                time_conventions, time_usage,
            )
            if processed is None:
                continue
            period_grain, period_start, period_end = processed
            stats["n_observation"] += 1

            # センサーに検閲の概念は無い（design.md T3）。value_raw は持たず、
            # censoring は常に 'none'。value_num は result をそのまま運ぶ
            # （result IS NULL の行はそのまま NULL のまま運び、b04 の
            # `WHERE v IS NOT NULL` で自然にキューブから外れる）。
            yield (
                "sensor_timeseries", row_id_str, region_id, place_id, place_kind, variable_id, obs_stat,
                unit_id, unit, value_grain, period_grain, period_start, period_end, phenomenon_time,
                result, None, censoring.CENSORING_NONE, None,
                None, is_synthetic, None, None,
            )

    dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), rows())
    return stats


def _load_watershed_place_lookup(work: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """`watershed_id -> (place_id, place_kind)` を返す
    （`place_source_ref(source_id='watershed_meta.watershed_id')` 経由。
    ハードコードしない——`measurements`/`sensor_timeseries` が地点の place を
    解決するのと同じ流儀。P-1a（`scripts/registry/build_place.py`）が
    既に登録済みの watershed place をここで再利用するだけで、新規には作らない）。
    """
    rows = work.execute(
        "SELECT psr.external_key, psr.place_id, p.place_kind "
        "FROM reg.place_source_ref psr "
        "JOIN reg.place p ON p.place_id = psr.place_id "
        "WHERE psr.source_id = 'watershed_meta.watershed_id'"
    ).fetchall()
    return {external_key: (place_id, place_kind) for external_key, place_id, place_kind in rows}


def _load_landuse_alias_map(work: sqlite3.Connection) -> dict[tuple[str, str, str], tuple]:
    """`(dataset, alias, source_id) -> (variable_id, unit_id, stat, grain)` を返す
    （`dataset` が `f"{LANDUSE_SOURCE_ID}@"` で始まる行だけ。P-1b オーナー決定2:
    土地利用は2006/2016でコード体系が違うため `dataset` を版付きにしてある）。
    """
    rows = work.execute(
        "SELECT dataset, alias, source_id, variable_id, unit_id, stat, grain "
        "FROM reg.variable_alias WHERE dataset LIKE ?",
        (f"{LANDUSE_SOURCE_ID}@%",),
    ).fetchall()
    return {
        (dataset, alias, source_id): (variable_id, unit_id, stat, grain)
        for dataset, alias, source_id, variable_id, unit_id, stat, grain in rows
    }


def _ingest_landuse(
    work: sqlite3.Connection,
    dest: sqlite3.Connection,
    insert_table: str,
    exceptions,
    usage,
    csv_path,
    landuse_sources: dict,
    source_usage,
    region_usage,
) -> dict:
    """`csv_path`（既定 `data/processed/nlni_l03b_landuse_by_watershed.csv`。
    国土数値情報 L03-b 土地利用、流域別・2006/2016年版に前処理済みのCSV、L1）を
    1行ずつ読み、`insert_table` へ `executemany` でストリーム挿入する
    （`_ingest_measurements`/`_ingest_sensor_timeseries` と同じくジェネレータを
    直接渡す。C-5）。

    第三の出典（`ryuiki.sqlite` のテーブルではなく CSV）なので `work` の
    `src`（ryuiki_db）は使わない——`reg`（registry_db）だけを読む。

    CSV の1行（watershed × year × landuse_code）から、区分の**面積**と
    **セル数**という2つの observation 行を作る（P-1b オーナー決定1:
    observation に「n」の列が無いため、セル数は面積とは別の variable にする。
    それぞれの `variable_id`/`unit_id`/`obs_stat`/`value_grain` は
    `variable_alias`（`dataset` は `f"{LANDUSE_SOURCE_ID}@{data_year}"` で
    版付き。2006/2016でコード体系が違う——`assert_grain_and_stat_codes` 等が
    書き手側で既に検証済み）から引く。

    `region_id` は `source_regions.yaml`（consumer='observation'。
    `landuse_sources`/`source_usage`/`region_usage` は呼び出し側
    `build_and_write_observation` が `consumer='observation'` で絞り込んで
    渡す）から決める——watershed の place は `common` スコープで
    `place.region_id` が常に NULL（ADR-0022 決定1）なので、place 経由では
    決められない（ADR-0022 決定3・P-1b オーナー決定3）。

    未知の `source_id`（CSV の `source_id` 列が `landuse_sources` に無い）は
    1行だけの問題ではなく構造的な設定不足なので、`_process_row` と違って
    per-row の集計を経由せず即座に `UnknownSourceRegionError` で止まる
    （`scripts/b06_build_occurrence.py` の `_ingest` と同じ判断）。
    """
    stats = _empty_stats(LANDUSE_SOURCE_ID)
    watershed_place = _load_watershed_place_lookup(work)
    alias_map = _load_landuse_alias_map(work)
    seen_ids: set[str] = set()

    def rows():
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row_number, row in enumerate(reader, start=1):
                stats["total"] += 1
                source_id = row["source_id"]

                source_region = landuse_sources.get(source_id)
                if source_region is None:
                    raise source_regions.UnknownSourceRegionError(source_id)
                source_usage.mark_used(source_id)
                region_id = source_region.region_id
                region_usage.mark_used(region_id)

                watershed_id = row["watershed_id"]
                place = watershed_place.get(watershed_id)
                if place is None:
                    stats["unresolved_place_count"] += 1
                    if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                        stats["unresolved_place_sample"].append((row_number, watershed_id))
                    continue
                place_id, place_kind = place

                data_year = row["data_year"]
                code = row["landuse_code_raw"]
                dataset = f"{LANDUSE_SOURCE_ID}@{data_year}"
                alias_area = f"{code}:area_km2"
                alias_ncells = f"{code}:n_cells"
                area_entry = alias_map.get((dataset, alias_area, source_id))
                ncells_entry = alias_map.get((dataset, alias_ncells, source_id))
                if area_entry is None or ncells_entry is None:
                    stats["unresolved_alias_count"] += 1
                    if len(stats["unresolved_alias_sample"]) < _SAMPLE_LIMIT:
                        missing_alias = alias_area if area_entry is None else alias_ncells
                        stats["unresolved_alias_sample"].append((row_number, dataset, missing_alias, source_id))
                    continue

                period_grain, period_start, period_end = period.compute_period(
                    data_year, "year", source_id, exceptions, usage,
                )
                source_ref = row["source_ref"]

                for suffix, entry, value_str in (
                    ("area_km2", area_entry, row["area_km2"]),
                    ("n_cells", ncells_entry, row["n_cells"]),
                ):
                    variable_id, unit_id, obs_stat, value_grain = entry
                    source_row_id = f"{row_number}:{suffix}"
                    if source_row_id in seen_ids:
                        stats["dup_ids_count"] += 1
                        if len(stats["dup_ids_sample"]) < _SAMPLE_LIMIT:
                            stats["dup_ids_sample"].append(source_row_id)
                        continue
                    seen_ids.add(source_row_id)
                    stats["n_observation"] += 1
                    yield (
                        LANDUSE_SOURCE_ID, source_row_id, region_id, place_id, place_kind,
                        variable_id, obs_stat, unit_id, None, value_grain, period_grain,
                        period_start, period_end, data_year,
                        float(value_str), None, censoring.CENSORING_NONE, None,
                        None, 0, source_ref, None,
                    )

    dest.executemany(_INSERT_SQL.format(table=f'"{insert_table}"'), rows())
    return stats


def build_and_write_observation(
    ryuiki_db,
    registry_db,
    exceptions_yaml=DEFAULT_EXCEPTIONS_YAML,
    time_conventions_yaml=DEFAULT_TIME_LABEL_CONVENTIONS_YAML,
    out_path=DEFAULT_OUT,
    source_regions_yaml=None,
    landuse_csv=None,
) -> dict[str, dict]:
    """`observation` を構築し、`out_path` の `observation` テーブルに書き込む
    （`out_path` の他のテーブルは触らない。モジュール docstring 参照）。

    戻り値は出典ごとの統計（`{"measurements": {...}, "sensor_timeseries": {...},
    "nlni_l03b_landuse_by_watershed": {...}}`）。問題が見つかった出典・宣言表・
    T1 不変条件があれば、その時点で `common.MigrationError` を投げる
    （呼び出し側は捕まえず素通しする前提）。A-1: いずれの検証も
    `migrate.common.staged_table` の `with` ブロックの中で行うため、失敗すれば
    本番の `observation` には一切触れずに終わる。

    `source_regions_yaml`/`landuse_csv` の既定は `None`（呼び出し側で
    `DEFAULT_SOURCE_REGIONS_YAML`/`DEFAULT_LANDUSE_CSV` をここで解決する）。
    直接デフォルト値にせず、モジュールレベル変数への遅延参照にしてある
    ——`scripts/tests/test_b03_build_observation.py` の既存テスト（P-1b より
    前に書かれ、この2引数を渡さない）が `monkeypatch.setattr(b03,
    "DEFAULT_LANDUSE_CSV", ...)` でこの既定を差し替えられるようにするため
    （関数定義時に束縛される素のデフォルト引数だと、インポート後の
    monkeypatch が効かない）。
    """
    if source_regions_yaml is None:
        source_regions_yaml = DEFAULT_SOURCE_REGIONS_YAML
    if landuse_csv is None:
        landuse_csv = DEFAULT_LANDUSE_CSV

    exceptions = period.load_period_exceptions(exceptions_yaml)
    usage = period.PeriodExceptionUsage(exceptions)
    time_conventions = period.load_time_label_conventions(time_conventions_yaml)
    time_usage = period.TimeLabelConventionUsage(time_conventions)

    # P-1b（土地利用）: consumer='observation' で自分の宣言だけに絞り込む
    # （scripts/migrate/source_regions.py モジュール docstring「consumer」節。
    # b06_build_occurrence.py が consumer='occurrence' で絞り込むのと対称）。
    source_regions.validate_source_regions_shape(source_regions_yaml)
    landuse_sources, landuse_regions = source_regions.load_source_regions(
        source_regions_yaml, consumer="observation"
    )
    landuse_source_usage = period.EntryUsage(landuse_sources)
    landuse_region_usage = period.EntryUsage(landuse_regions)

    # B-2: 出典ごとに違う追加引数（`sensor_timeseries` だけが要る
    # `time_conventions`/`time_usage`）は、呼び出し側の `if source_table ==
    # "sensor_timeseries":` 分岐ではなく、ここで `functools.partial` に
    # 持たせる。呼び出し側はどちらの出典でも同じ形（`ingest(work, dest,
    # staging)`）で呼べる。
    ingest_funcs = {
        "measurements": functools.partial(_ingest_measurements, exceptions=exceptions, usage=usage),
        "sensor_timeseries": functools.partial(
            _ingest_sensor_timeseries, exceptions=exceptions, usage=usage,
            time_conventions=time_conventions, time_usage=time_usage,
        ),
        LANDUSE_SOURCE_ID: functools.partial(
            _ingest_landuse, exceptions=exceptions, usage=usage,
            csv_path=landuse_csv, landuse_sources=landuse_sources,
            source_usage=landuse_source_usage, region_usage=landuse_region_usage,
        ),
    }

    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(f"file:{out_path}", uri=True)
    dest.execute("PRAGMA journal_mode=DELETE")
    try:
        with common.staged_table(dest, "observation", _CREATE_OBSERVATION_SQL) as staging:
            all_stats: dict[str, dict] = {}
            for source_table, ingest in ingest_funcs.items():
                work = sqlite3.connect(":memory:", uri=True)
                try:
                    common.attach_readonly(work, ryuiki_db, "src")
                    common.attach_readonly(work, registry_db, "reg")
                    stats = ingest(work, dest, staging)
                finally:
                    work.close()

                problems = _problems_from_stats(stats)
                if problems:
                    raise common.MigrationError(
                        f"{source_table} の取り込みを中止した。以下の問題を解消してから"
                        "再実行すること:\n- " + "\n- ".join(problems)
                    )
                dest.commit()
                all_stats[source_table] = stats

            # C-5: 重複行は _process_row が挿入前に弾いているので、ここでの
            # 一意インデックス作成は安全に「挿入後」へ回せる。検証用の使い捨て
            # なので張った直後に DROP する（_CREATE_OBSERVATION_INDEX_SQL の
            # コメント参照。固定名を本番テーブルまで残すと次回実行の索引作成が
            # 名前衝突で壊れる）。
            dest.execute(_CREATE_OBSERVATION_INDEX_SQL.format(table=f'"{staging}"'))
            dest.execute(_DROP_OBSERVATION_INDEX_SQL)

            # 宣言表（period_exceptions.yaml / time_label_conventions.yaml /
            # source_regions.yaml）は全出典を処理し終えてから検証する
            # （period_exceptions.yaml は measurements、time_label_conventions.yaml
            # は sensor_timeseries の value_grain='hour'、source_regions.yaml
            # （consumer='observation'）は土地利用からしか使われないため、
            # 1つの出典だけを見て判定すると腐った宣言を見逃す。B-3）。
            declaration_problems = (
                period.declaration_problems(usage, "period_exceptions.yaml")
                + period.declaration_problems(time_usage, "time_label_conventions.yaml")
                + period.declaration_problems(
                    landuse_source_usage, "source_regions.yaml (sources, consumer=observation)"
                )
                + period.declaration_problems(
                    landuse_region_usage, "source_regions.yaml (regions, consumer=observation)"
                )
            )
            if declaration_problems:
                raise common.MigrationError(
                    "observation の構築を中止した（全出典の取り込み自体は成功したが、"
                    "宣言表の検証に失敗した）。以下を解消してから再実行すること:\n- "
                    + "\n- ".join(declaration_problems)
                )

            # T1 不変条件（ADR-0024）: period_start/period_end が時刻帯を持たない、
            # かつ date(period_start) が period_start 自身の日付部分と一致する
            # （SQLite の date() は '+09:00' 付き文字列を UTC 側に正規化してしまう
            # ため、この不変条件が崩れていれば date() 系の SQL が黙って壊れる）。
            # 書き出した実際のテーブル（作業用テーブル。A-1）に対して、全行を
            # 対象に検証する。
            bad = dest.execute(
                f"""
                SELECT COUNT(*) FROM "{staging}"
                WHERE period_start LIKE '%+%' OR period_start LIKE '%Z%'
                   OR period_end LIKE '%+%' OR period_end LIKE '%Z%'
                   OR date(period_start) IS NULL
                   OR date(period_start) <> substr(period_start, 1, 10)
                """
            ).fetchone()[0]
            if bad:
                raise common.MigrationError(
                    f"T1 の不変条件（period_start/period_end が時刻帯を持たない・"
                    "date(period_start) が period_start の日付部分と一致する）が崩れている行が"
                    f"{bad}件ある。scripts/migrate/period.py の時刻帯除去（_strip_tz）が"
                    "正しく効いているか確認すること。"
                )
            # ここまで来たら with ブロックを正常に抜け、staged_table が
            # 作業用テーブルを本番名 "observation" に差し替える（A-1）。
    except BaseException:
        dest.close()
        raise
    dest.close()
    return all_stats


def render_report(all_stats: dict[str, dict]) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Phase B ファクト移行 — observation の要約")
    a("")
    a(
        "`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の "
        "`measurements`・`sensor_timeseries` と "
        "`data/processed/nlni_l03b_landuse_by_watershed.csv`（土地利用、P-1b）から "
        "`data/db/v2.sqlite` の `observation` を作った結果の要約。設計判断は "
        "`docs/plans/PHASE_B_FACT_SLICE.md`（measurements の縦線）と「センサーの"
        "縦線 設計 v2」オーナー決定・関連 ADR（`docs/adr/0023-*`・`0024-*`）、"
        "`docs/plans/PHASE_B_LANDUSE.md`（土地利用の縦線）参照。"
    )
    a("")
    total = sum(s["total"] for s in all_stats.values())
    total_obs = sum(s["n_observation"] for s in all_stats.values())
    a(f"- 入力（`measurements`+`sensor_timeseries`+土地利用CSV）総行数: **{total:,}**")
    a(f"- `observation` 総行数: **{total_obs:,}**")
    a("")

    for source_table in ("measurements", "sensor_timeseries", LANDUSE_SOURCE_ID):
        stats = all_stats.get(source_table)
        if stats is None:
            continue
        a(f"## 出典: `{source_table}`")
        a("")
        a(f"- `{source_table}` 総行数: **{stats['total']:,}**")
        a(f"- `observation` 行数: **{stats['n_observation']:,}**")
        if source_table == LANDUSE_SOURCE_ID:
            # 土地利用は1行（watershed×year×landuse_code）から面積・セル数の
            # 2つの observation 行を作るため（P-1b オーナー決定1）、他2出典と
            # 違って「1:1」の解決率という表現にならない。
            a(
                "- alias（variable_alias）/ place（place_source_ref）解決率: "
                f"{stats['n_observation']:,} / {stats['total'] * 2:,} "
                "（CSV1行→面積・セル数の2 observation 行。全行解決。1行でも未解決なら、"
                "このレポート自体が作られず b03 が例外で止まる）"
            )
        else:
            a(
                "- alias（variable_alias）解決率: "
                f"{stats['n_observation']:,} / {stats['total']:,} "
                "（全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）"
            )
            a(
                "- place（place_source_ref）解決率: "
                f"{stats['n_observation']:,} / {stats['total']:,} "
                "（同上。全行解決）"
            )
        a("")
        if source_table == "measurements":
            a("### censoring の内訳（ADR-0009・design.md D2）")
            a("")
            a("| censoring | 行数 |")
            a("|---|---:|")
            for key in censoring.ALL_CENSORING_VALUES:
                n = stats["censoring_counts"].get(key, 0)
                a(f"| `{key}` | {n:,} |")
            a("")
            a(
                f"`imputation='zero'` で値（0.0）が入る行（`below_lod` + `not_detected`）: "
                f"**{stats['zero_imputed_count']:,}行**"
                "（`above_lod`/`unknown` には代入しない。design.md D2）。"
            )
        elif source_table == "sensor_timeseries":
            a(
                "センサーに検閲の概念は無い（design.md T3）。`censoring` は常に "
                "`'none'`・`value_raw` は常に NULL。`sensor_timeseries.result IS NULL` の"
                "行はそのまま `value_num=NULL` で運び、b04 の `WHERE v IS NOT NULL` で"
                "キューブから自然に除外される。"
            )
        else:
            a(
                "検閲の概念は無い（`censoring` は常に `'none'`）。区分の面積（km2）と"
                "セル数（count）をそれぞれ別の variable として持つ（P-1b オーナー決定1）。"
                "region は `source_regions.yaml`（consumer='observation'）の宣言から決める"
                "（ADR-0022 決定3・P-1b オーナー決定3）。"
            )
        a("")
        a(
            f"value_grain != period_grain（食い違う行。宣言表でカバーされている分のみ"
            f"許される）: **{stats['grain_mismatch_count']:,}行**"
        )
        a("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ryuiki-db", default=str(DEFAULT_RYUIKI_DB),
        help="measurements/sensor_timeseries を持つ ryuiki.sqlite",
    )
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--exceptions-yaml", default=str(DEFAULT_EXCEPTIONS_YAML))
    parser.add_argument("--time-conventions-yaml", default=str(DEFAULT_TIME_LABEL_CONVENTIONS_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument(
        "--source-regions-yaml", default=str(DEFAULT_SOURCE_REGIONS_YAML),
        help="土地利用（consumer='observation'）の region 宣言（P-1b）",
    )
    parser.add_argument(
        "--landuse-csv", default=str(DEFAULT_LANDUSE_CSV),
        help="国土数値情報 L03-b 土地利用（流域別、2006/2016年版）のCSV（P-1b）",
    )
    args = parser.parse_args()

    # `--out` を `sqlite3.connect` で直接開く（`fresh_sqlite` を経由しない）ため、
    # ここで個別に検査する（`scripts/migrate/common.py` の
    # `reject_protected_source_db` の docstring 参照）。
    common.reject_protected_source_db(pathlib.Path(args.out))

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")
    print(f"▶ 読み取り専用で読む: {args.landuse_csv}")

    with common.timed_step("observation を構築して書き出し") as info:
        all_stats = build_and_write_observation(
            args.ryuiki_db, registry_db, args.exceptions_yaml, args.time_conventions_yaml, args.out,
            args.source_regions_yaml, args.landuse_csv,
        )
        info["n"] = sum(s["n_observation"] for s in all_stats.values())

    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(all_stats), encoding="utf-8")
    print(f"→ {report_path}")
    for source_table, stats in sorted(all_stats.items()):
        print(f"  {source_table}: {stats['n_observation']:,}行")


if __name__ == "__main__":
    main()
