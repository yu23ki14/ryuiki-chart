#!/usr/bin/env python3
"""`data/db/ryuiki.sqlite`（読み取り専用）の `measurements` と
`sensor_timeseries` を、単一の縦持ちファクト `observation`（ADR-0007）にする
（ADR-0016 Phase B「ファクトとキューブ」。`measurements` だけの縦線は
`docs/plans/PHASE_B_FACT_SLICE.md`、`sensor_timeseries` を足したセンサーの
縦線の設計は「センサーの縦線 設計 v2」オーナー決定・ADR-0023・ADR-0024 参照）。

    .venv/bin/python3 scripts/b03_build_observation.py

`data/db/v2.sqlite` の `observation` テーブルだけを作り直す
（`scripts/migrate/common.replace_table`。ファイル全体を作り直さない —
「ファイルではなくテーブル単位」節を参照）。`reports/phase_b_fact_slice.md` に
出典ごとの節を持つ人が読む要約を書く。**入力（`ryuiki.sqlite`/`registry.sqlite`）
は読み取り専用でしか開かない。**

## ファイルではなくテーブル単位で作り直す

以前は `data/db/v2.sqlite` をファイルごと作り直していた（`common.fresh_sqlite`）。
ADR-0007 は `measurements` と `sensor_timeseries` を同じ `observation` に
統合すると決めており、将来 `occurrence`（生物のファクト。ADR-0007 決定3）が
同じ `v2.sqlite` に増えたときにファイルごと作り直すと、b03 の実行が
`occurrence` を消してしまう。そこで b04 が `observation_agg` に対して
既にやっているのと同じパターン（`migrate.common.replace_table`）を
`observation` にも使う——DROP + CREATE を `observation` テーブルだけに絞る。

## 出典ごとに1トランザクションでストリーム挿入する

以前は全行を Python のリストに溜めてから `executemany` で一括挿入していた。
`measurements`（323,164行）だけならメモリに収まったが、`sensor_timeseries`
（717,839行）を足すと合計104万行になり、リストとして保持すると数百MBになる
（実測前の見積もり。オーナー指摘）。ここでは出典（`measurements`/
`sensor_timeseries`）ごとに、読み取り専用の JOIN 済みカーソルを1行ずつ
読みながら `observation` へ直接 `INSERT` する。1つの出典の取り込み全体を
1つの sqlite トランザクションにし（`dest.commit()` を出典ごとに1回だけ呼ぶ）、
その出典で問題（alias/place 未解決・宣言に無い期間の食い違い等）が1件でも
見つかれば `dest.rollback()` してから `MigrationError` を投げる——「中途半端な
出力を書かない」という以前の方針を、出典単位に絞って引き継ぐ。**ある出典が
成功してコミットされた後に別の出典が失敗した場合、`observation` には成功した
出典の分だけが残った状態でプロセスが例外終了する**（黙って成功したことには
ならない——`main()` は例外を捕まえず素通しする）。次回の再実行は必ず
`replace_table` からやり直すため、この中途半端な状態が次回実行に持ち越される
ことは無い。

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
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from migrate import censoring, common, period  # noqa: E402

DEFAULT_RYUIKI_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_EXCEPTIONS_YAML = ROOT / "scripts" / "migrate" / "period_exceptions.yaml"
DEFAULT_TIME_LABEL_CONVENTIONS_YAML = ROOT / "scripts" / "migrate" / "time_label_conventions.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REPORT = ROOT / "reports" / "phase_b_fact_slice.md"

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

_CREATE_OBSERVATION_SQL = """
CREATE TABLE observation (
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
  event_id        TEXT,
  PRIMARY KEY (source_table, source_row_id)
)
"""

_INSERT_SQL = """
INSERT INTO observation (
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


def _problems_from_stats(stats: dict) -> list[str]:
    """出典1つぶんの統計から、b03 を止めるべき問題のメッセージ一覧を作る
    （`measurements`/`sensor_timeseries` で共通の判定基準）。
    """
    table = stats["source_table"]
    problems: list[str] = []
    if stats["dup_ids_count"]:
        problems.append(
            f"{table}: source_row_id が複数行にマッチした"
            f"（alias/place の解決が「関数」でなくなっている）: {stats['dup_ids_count']}件"
            f"（例: {stats['dup_ids_sample'][:5]}）"
        )
    if stats["unresolved_alias_count"]:
        problems.append(
            f"{table}: variable_alias で解決できない行: "
            f"{stats['unresolved_alias_count']}件（例: {stats['unresolved_alias_sample']}）"
        )
    if stats["unresolved_place_count"]:
        problems.append(
            f"{table}: place_source_ref で解決できない行: "
            f"{stats['unresolved_place_count']}件（例: {stats['unresolved_place_sample']}）"
        )
    if stats["period_mismatch_count"]:
        problems.append(
            f"{table}: value_grain と period_grain が食い違い、かつ宣言表に"
            f"宣言が無い行がある: {stats['period_mismatch_count']}件"
            f"（例（上限{_SAMPLE_LIMIT}件）: {stats['period_mismatch_sample']}）"
        )
    return problems


def _ingest_measurements(work: sqlite3.Connection, dest: sqlite3.Connection, exceptions, usage) -> dict:
    """`measurements` を1行ずつ読み、`dest` の `observation` へストリーム挿入する。

    `dest` へのコミット/ロールバックは呼び出し側（`build_and_write_observation`）の
    責務——ここでは `INSERT` するだけで `commit()` を呼ばない（出典ごとに
    1トランザクションにするため。モジュール docstring 参照）。
    """
    stats = _empty_stats("measurements")
    seen_ids: set[str] = set()
    censoring_counts: collections.Counter = collections.Counter()

    for row in work.execute(_SELECT_MEASUREMENTS_SQL):
        (
            measurement_id, site_id, measured_on, variable, source_id,
            value, value_raw, unit, quality_stage, is_synthetic, source_ref, event_id,
            variable_id, unit_id, obs_stat, value_grain,
            place_id, region_id, place_kind,
        ) = row
        stats["total"] += 1

        if measurement_id in seen_ids:
            stats["dup_ids_count"] += 1
            if len(stats["dup_ids_sample"]) < _SAMPLE_LIMIT:
                stats["dup_ids_sample"].append(measurement_id)
        seen_ids.add(measurement_id)

        if variable_id is None:
            stats["unresolved_alias_count"] += 1
            if len(stats["unresolved_alias_sample"]) < _SAMPLE_LIMIT:
                stats["unresolved_alias_sample"].append((measurement_id, variable, source_id))
            continue
        if place_id is None:
            stats["unresolved_place_count"] += 1
            if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                stats["unresolved_place_sample"].append((measurement_id, site_id))
            continue

        try:
            period_grain, period_start, period_end = period.compute_period(
                measured_on, value_grain, source_id, exceptions, usage
            )
        except period.PeriodMismatchError:
            stats["period_mismatch_count"] += 1
            if len(stats["period_mismatch_sample"]) < _SAMPLE_LIMIT:
                stats["period_mismatch_sample"].append((measurement_id, source_id, measured_on, value_grain))
            continue

        if period_grain != value_grain:
            stats["grain_mismatch_count"] += 1

        cens, cens_limit = censoring.classify_censoring(value_raw)
        censoring_counts[cens] += 1
        value_num = censoring.resolve_value_num(cens, value)
        if cens in censoring.ZERO_IMPUTED_CENSORING:
            stats["zero_imputed_count"] += 1

        dest.execute(_INSERT_SQL, (
            "measurements", measurement_id, region_id, place_id, place_kind, variable_id, obs_stat,
            unit_id, unit, value_grain, period_grain, period_start, period_end, measured_on,
            value_num, value_raw, cens, cens_limit,
            quality_stage, is_synthetic, source_ref, event_id,
        ))
        stats["n_observation"] += 1

    stats["censoring_counts"] = dict(censoring_counts)
    return stats


def _ingest_sensor_timeseries(
    work: sqlite3.Connection, dest: sqlite3.Connection, exceptions, usage, time_conventions, time_usage
) -> dict:
    """`sensor_timeseries` を1行ずつ読み、`dest` の `observation` へストリーム
    挿入する（`_ingest_measurements` と対になる関数。検閲が無いこと・
    `time_conventions`/`time_usage` を `period.compute_period` に渡すことが
    違い。alias/place の解決・重複検出・期間計算の呼び出し方はそのまま共有）。
    """
    stats = _empty_stats("sensor_timeseries")
    seen_ids: set[str] = set()

    for row in work.execute(_SELECT_SENSOR_SQL):
        (
            row_id, site_id, phenomenon_time, datastream, source_id,
            result, unit, is_synthetic,
            variable_id, unit_id, obs_stat, value_grain,
            place_id, region_id, place_kind,
        ) = row
        row_id_str = str(row_id)
        stats["total"] += 1

        if row_id_str in seen_ids:
            stats["dup_ids_count"] += 1
            if len(stats["dup_ids_sample"]) < _SAMPLE_LIMIT:
                stats["dup_ids_sample"].append(row_id_str)
        seen_ids.add(row_id_str)

        if variable_id is None:
            stats["unresolved_alias_count"] += 1
            if len(stats["unresolved_alias_sample"]) < _SAMPLE_LIMIT:
                stats["unresolved_alias_sample"].append((row_id_str, datastream, source_id))
            continue
        if place_id is None:
            stats["unresolved_place_count"] += 1
            if len(stats["unresolved_place_sample"]) < _SAMPLE_LIMIT:
                stats["unresolved_place_sample"].append((row_id_str, site_id))
            continue

        # `UnknownTimeLabelConventionError`（time_conventions に宣言が無い
        # value_grain='hour' の出典）はここで捕まえない——per-row の
        # 問題ではなく構造的な設定不足なので、即座に呼び出し側まで伝播させる
        # （モジュール docstring・period.py の当該クラスの docstring 参照）。
        try:
            period_grain, period_start, period_end = period.compute_period(
                phenomenon_time, value_grain, source_id, exceptions, usage,
                time_conventions, time_usage,
            )
        except period.PeriodMismatchError:
            stats["period_mismatch_count"] += 1
            if len(stats["period_mismatch_sample"]) < _SAMPLE_LIMIT:
                stats["period_mismatch_sample"].append((row_id_str, source_id, phenomenon_time, value_grain))
            continue

        if period_grain != value_grain:
            stats["grain_mismatch_count"] += 1

        # センサーに検閲の概念は無い（design.md T3）。value_raw は持たず、
        # censoring は常に 'none'。value_num は result をそのまま運ぶ
        # （result IS NULL の行はそのまま NULL のまま運び、b04 の
        # `WHERE v IS NOT NULL` で自然にキューブから外れる）。
        dest.execute(_INSERT_SQL, (
            "sensor_timeseries", row_id_str, region_id, place_id, place_kind, variable_id, obs_stat,
            unit_id, unit, value_grain, period_grain, period_start, period_end, phenomenon_time,
            result, None, censoring.CENSORING_NONE, None,
            None, is_synthetic, None, None,
        ))
        stats["n_observation"] += 1

    return stats


_INGEST_FUNCS = {
    "measurements": _ingest_measurements,
    "sensor_timeseries": _ingest_sensor_timeseries,
}


def build_and_write_observation(
    ryuiki_db,
    registry_db,
    exceptions_yaml=DEFAULT_EXCEPTIONS_YAML,
    time_conventions_yaml=DEFAULT_TIME_LABEL_CONVENTIONS_YAML,
    out_path=DEFAULT_OUT,
) -> dict[str, dict]:
    """`observation` を構築し、`out_path` の `observation` テーブルに書き込む
    （`out_path` の他のテーブルは触らない。モジュール docstring 参照）。

    戻り値は出典ごとの統計（`{"measurements": {...}, "sensor_timeseries": {...}}`）。
    問題が見つかった出典があれば、その時点で `common.MigrationError` を投げる
    （呼び出し側は捕まえず素通しする前提）。
    """
    exceptions = period.load_period_exceptions(exceptions_yaml)
    usage = period.PeriodExceptionUsage(exceptions)
    time_conventions = period.load_time_label_conventions(time_conventions_yaml)
    time_usage = period.TimeLabelConventionUsage(time_conventions)

    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(f"file:{out_path}", uri=True)
    dest.execute("PRAGMA journal_mode=DELETE")
    try:
        common.replace_table(dest, "observation", _CREATE_OBSERVATION_SQL)
        dest.commit()

        all_stats: dict[str, dict] = {}
        for source_table, ingest in _INGEST_FUNCS.items():
            work = sqlite3.connect(":memory:", uri=True)
            try:
                common.attach_readonly(work, ryuiki_db, "src")
                common.attach_readonly(work, registry_db, "reg")
                if source_table == "sensor_timeseries":
                    stats = ingest(work, dest, exceptions, usage, time_conventions, time_usage)
                else:
                    stats = ingest(work, dest, exceptions, usage)
            finally:
                work.close()

            problems = _problems_from_stats(stats)
            if problems:
                dest.rollback()
                raise common.MigrationError(
                    f"{source_table} の取り込みを中止した。以下の問題を解消してから"
                    "再実行すること:\n- " + "\n- ".join(problems)
                )
            dest.commit()
            all_stats[source_table] = stats

        # 宣言表（period_exceptions.yaml / time_label_conventions.yaml）は
        # 両方の出典を処理し終えてから検証する（前者は measurements、
        # 後者は sensor_timeseries の value_grain='hour' からしか使われない
        # ため、片方の出典だけを見て判定すると腐った宣言を見逃す）。
        declaration_problems: list[str] = []
        unused = usage.unused_entries()
        if unused:
            declaration_problems.append(
                f"period_exceptions.yaml に宣言されているが1件も該当しなかったエントリ: {unused}"
            )
        mismatched = usage.mismatched_expected_counts()
        if mismatched:
            declaration_problems.append(
                "period_exceptions.yaml の expected_row_count と実測件数が食い違う: "
                f"{mismatched}（宣言 (expected, actual) の順）"
            )
        unused_time = time_usage.unused_entries()
        if unused_time:
            declaration_problems.append(
                f"time_label_conventions.yaml に宣言されているが1件も該当しなかったエントリ: {unused_time}"
            )
        mismatched_time = time_usage.mismatched_expected_counts()
        if mismatched_time:
            declaration_problems.append(
                "time_label_conventions.yaml の expected_row_count と実測件数が食い違う: "
                f"{mismatched_time}（宣言 (expected, actual) の順）"
            )
        if declaration_problems:
            raise common.MigrationError(
                "observation の構築を中止した（両出典の取り込み自体は成功したが、"
                "宣言表の検証に失敗した）。以下を解消してから再実行すること:\n- "
                + "\n- ".join(declaration_problems)
            )

        # T1 不変条件（ADR-0024）: period_start/period_end が時刻帯を持たない、
        # かつ date(period_start) が period_start 自身の日付部分と一致する
        # （SQLite の date() は '+09:00' 付き文字列を UTC 側に正規化してしまう
        # ため、この不変条件が崩れていれば date() 系の SQL が黙って壊れる）。
        # 書き出した実際のテーブルに対して、全行を対象に検証する。
        bad = dest.execute(
            """
            SELECT COUNT(*) FROM observation
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
        "`measurements`・`sensor_timeseries` から `data/db/v2.sqlite` の "
        "`observation` を作った結果の要約。設計判断は "
        "`docs/plans/PHASE_B_FACT_SLICE.md`（measurements の縦線）と「センサーの"
        "縦線 設計 v2」オーナー決定・関連 ADR（`docs/adr/0023-*`・`0024-*`）参照。"
    )
    a("")
    total = sum(s["total"] for s in all_stats.values())
    total_obs = sum(s["n_observation"] for s in all_stats.values())
    a(f"- 入力（`measurements`+`sensor_timeseries`）総行数: **{total:,}**")
    a(f"- `observation` 総行数: **{total_obs:,}**")
    a("")

    for source_table in ("measurements", "sensor_timeseries"):
        stats = all_stats.get(source_table)
        if stats is None:
            continue
        a(f"## 出典: `{source_table}`")
        a("")
        a(f"- `{source_table}` 総行数: **{stats['total']:,}**")
        a(f"- `observation` 行数: **{stats['n_observation']:,}**")
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
        else:
            a(
                "センサーに検閲の概念は無い（design.md T3）。`censoring` は常に "
                "`'none'`・`value_raw` は常に NULL。`sensor_timeseries.result IS NULL` の"
                "行はそのまま `value_num=NULL` で運び、b04 の `WHERE v IS NOT NULL` で"
                "キューブから自然に除外される。"
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
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    print(f"▶ 読み取り専用で開く: {args.ryuiki_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("observation を構築して書き出し") as info:
        all_stats = build_and_write_observation(
            args.ryuiki_db, registry_db, args.exceptions_yaml, args.time_conventions_yaml, args.out
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
