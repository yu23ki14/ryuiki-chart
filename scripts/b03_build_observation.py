#!/usr/bin/env python3
"""`measurements`（`data/db/ryuiki.sqlite`、読み取り専用）を単一の縦持ちファクト
`observation`（ADR-0007）にする（ADR-0016 Phase B「ファクトとキューブ」縦に薄い1本、
`docs/plans/PHASE_B_FACT_SLICE.md` 参照）。

    .venv/bin/python3 scripts/b03_build_observation.py

`data/db/v2.sqlite` に `observation` テーブルを作り、`reports/phase_b_fact_slice.md`
に人が読む要約を書く。**入力（`ryuiki.sqlite` / `registry.sqlite`）は読み取り専用
でしか開かない。出力（`v2.sqlite`）は毎回ゼロから作り直す。**

## このスクリプトが埋める列・埋めない列（ADR-0007 のうち、この縦線が実際に使うもの）

`measurements` は「主語＝site（place）」「値＝数量（検閲ありうる）」の観測しか
持たないので、ADR-0007 の全列のうち埋まるのは次のとおり。

埋める:
  - `source_measurement_id` — `measurements.measurement_id`。**`observation_id` は
    発行しない**（ADR-0016: 公開 ID の発行は Phase C）。Phase C で「旧ID→新ID」の
    対応表を作るとき、ここから引ける。
  - `region_id` / `place_id` / `place_kind` — `place_source_ref` 経由で解決
    （ハードコードしない。`place.region_id`/`place.place_kind` から引く）。
  - `variable_id` / `unit_id` / `obs_stat` / `value_grain`
    — `variable_alias`（`(dataset='measurements', alias, source_id)`）から引く。
    `obs_stat` は ADR-0007 の `stat` に相当するが、alias 側の値
    （`None`/`'point'`/`'mean'`/`'max'`/`'min'`/`'p75'`/`'p90'`）は ADR-0007 が
    列挙する enum と一致しないため、キューブ自身の集計統計量（b04 の `stat`。
    `'mean'`/`'min'`/`'max'`）と区別する目的で意図的に別名にしている（design.md D5）。
  - `period_grain` / `period_start` / `period_end` — ADR-0008。`measured_on` から
    展開する（`scripts/migrate/period.py`）。
  - `value_num` / `value_raw` / `censoring` / `censoring_limit` — ADR-0009。
    `scripts/migrate/censoring.py`。`value_num` は「そのまま運ぶ」の対象を
    `censoring='none'` の行だけに絞る（design.md D2。検閲行は 0 を入れない）。
  - `quality_stage` / `is_synthetic` / `source_ref` / `event_id` —
    `measurements` に既にある列で、レジストリ解決を要さない素の carry-over。

埋めない（理由）:
  - `observation_id` — 上記のとおり Phase C の仕事。
  - `taxon_id` / `feature_id` — `measurements` はどの行も「生物」でも「地物」でも
    ない量的観測（水質・気象・地盤沈下量など）。この縦線には無関係。
  - `method_id` / `instrument_id` — ADR-0007 のこの2列はレジストリ参照を想定して
    いるが、Phase A は method/instrument のレジストリを作っていない。
    `measurements.method`（自由記述、97.5%行に値あり）と `measurements.instrument_id`
    （0.7%行にのみ値あり、これも自由記述）はレジストリ ID ではないので、
    無理に詰めない（推測でマッピングしない）。
  - `observer_id` — `measurements` に対応する列が無い。
  - `source_edition_id` — `source_edition` レジストリは Phase C の仕事
    （ADR-0016）。
  - `value_text` — `measurements` の値は常に量的（検閲ありうる数量）で、
    テキスト値を持つ観測が無い。全部 NULL になる列は並べない（design.md の指示）。

## value_grain / period_grain の食い違い（design.md D4）

通常は一致する。唯一の宣言的な例外が `scripts/migrate/period_exceptions.yaml`
（`atsugi_river_water_quality` の `measured_on` 4桁行、3,840行）。宣言に無い
食い違いに出会ったら（1行でも）例外を投げて止まる。例外表のエントリが
1件も使われなかった場合、または実測件数が `expected_row_count` と食い違う場合も
止める（腐った宣言が残り続けないように）。

## alias / place 解決

`(dataset='measurements', alias, source_id)` と `place_source_ref
(source_id='sites.site_id')` は、この縦線の全323,164行が解決するはず
（design.md 実測）。1行でも解決できなければ、件数と実例を出して止まる
（黙って捨てない・黙って NULL にしない）。JOIN が1行を2行以上に増やしていないか
（alias/place の宣言が「関数」であるはずが実は多対応になっていないか）も
同時に確認する。
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

DEFAULT_MEASUREMENTS_DB = ROOT / "data" / "db" / "ryuiki.sqlite"
DEFAULT_REGISTRY_DB = ROOT / "data" / "db" / "registry.sqlite"
DEFAULT_EXCEPTIONS_YAML = ROOT / "scripts" / "migrate" / "period_exceptions.yaml"
DEFAULT_OUT = ROOT / "data" / "db" / "v2.sqlite"
DEFAULT_REPORT = ROOT / "reports" / "phase_b_fact_slice.md"

# LEFT JOIN で拾える範囲まで含めて全列を読む。alias/place が解決できない行も
# （検出のために）ここでは捨てず、後段の集計で NULL として数える。
_SELECT_SQL = """
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

_CREATE_OBSERVATION_SQL = """
CREATE TABLE observation (
  source_measurement_id TEXT PRIMARY KEY,
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

_INSERT_SQL = """
INSERT INTO observation (
  source_measurement_id, region_id, place_id, place_kind, variable_id, obs_stat,
  unit_id, unit_raw, value_grain, period_grain, period_start, period_end, period_raw,
  value_num, value_raw, censoring, censoring_limit,
  quality_stage, is_synthetic, source_ref, event_id
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

_SAMPLE_LIMIT = 20


def build_observation(measurements_db, registry_db, exceptions_yaml) -> tuple[list[tuple], dict]:
    """observation の全行と、報告用の統計を作る（ファイルには書かない）。

    戻り値は `(rows, stats)`。`rows` は `_INSERT_SQL` の列順に揃えたタプルのリスト。
    問題（alias/place 未解決・宣言に無い grain の食い違い・例外表の不整合）が
    1つでもあれば `common.MigrationError` を投げる——**その場合 rows は返らない**
    （中途半端な出力を書かないため、呼び出し側は例外を捕まえず素通しする）。
    """
    exceptions = period.load_period_exceptions(exceptions_yaml)
    usage = period.PeriodExceptionUsage(exceptions)

    # プライベートな :memory: 接続に、読み取り専用の原本2つを ATTACH して1本の SQL で
    # JOIN する（`scripts/reconcile` 側は単一 DB 前提なのでここだけ独自に開く）。
    # `file::memory:?cache=shared`（共有キャッシュ）ではなく、`sqlite3.connect(":memory:")`
    # と同じ意味のプライベート DB にする（レビュー指摘: 共有キャッシュはプロセス全体で
    # 見える DB で、ここでは他の接続と共有する理由が無いのに「接続間のテーブルロック」
    # という共有DB特有の失敗モードだけが増える）。`uri=True` は残す——`:memory:` 自体は
    # URI 構文ではなく素通りするが、この接続に ATTACH する `file:...?mode=ro` を
    # URI として解釈させるにはこのフラグが要る（`common.fresh_sqlite` と同じ理由）。
    # 原本はどちらも `mode=ro` でしか開かない（`attach_readonly` が保証する）。
    work = sqlite3.connect(":memory:", uri=True)

    total = 0
    unresolved_alias: list[tuple] = []
    unresolved_alias_count = 0
    unresolved_place: list[tuple] = []
    unresolved_place_count = 0
    dup_measurement_ids: list[str] = []
    period_mismatches: list[tuple] = []
    period_mismatch_count = 0
    censoring_counts: collections.Counter = collections.Counter()
    zero_imputed_count = 0
    grain_mismatch_count = 0
    seen_measurement_ids: set[str] = set()

    rows: list[tuple] = []

    # ATTACH をこの `try` の中で行う（レビュー指摘: 以前は `try` の外で ATTACH して
    # いたため、2つ目の ATTACH が失敗すると `work` が close されずに漏れ、共有
    # キャッシュ DB が生き続けていた。プライベート DB にした今も、接続の閉じ忘れ
    # そのものはリソースリークなので、ここで直しておく）。
    try:
        common.attach_readonly(work, measurements_db, "src")
        common.attach_readonly(work, registry_db, "reg")
        for row in work.execute(_SELECT_SQL):
            (
                measurement_id, site_id, measured_on, variable, source_id,
                value, value_raw, unit, quality_stage, is_synthetic, source_ref, event_id,
                variable_id, unit_id, obs_stat, value_grain,
                place_id, region_id, place_kind,
            ) = row
            total += 1

            if measurement_id in seen_measurement_ids:
                dup_measurement_ids.append(measurement_id)
            seen_measurement_ids.add(measurement_id)

            if variable_id is None:
                unresolved_alias_count += 1
                if len(unresolved_alias) < _SAMPLE_LIMIT:
                    unresolved_alias.append((measurement_id, variable, source_id))
                continue
            if place_id is None:
                unresolved_place_count += 1
                if len(unresolved_place) < _SAMPLE_LIMIT:
                    unresolved_place.append((measurement_id, site_id))
                continue

            try:
                period_grain, period_start, period_end = period.compute_period(
                    measured_on, value_grain, source_id, exceptions, usage
                )
            except period.PeriodMismatchError:
                period_mismatch_count += 1
                if len(period_mismatches) < _SAMPLE_LIMIT:
                    period_mismatches.append((measurement_id, source_id, measured_on, value_grain))
                continue

            if period_grain != value_grain:
                grain_mismatch_count += 1

            cens, cens_limit = censoring.classify_censoring(value_raw)
            censoring_counts[cens] += 1
            value_num = censoring.resolve_value_num(cens, value)
            if cens in censoring.ZERO_IMPUTED_CENSORING:
                zero_imputed_count += 1

            rows.append((
                measurement_id, region_id, place_id, place_kind, variable_id, obs_stat,
                unit_id, unit, value_grain, period_grain, period_start, period_end, measured_on,
                value_num, value_raw, cens, cens_limit,
                quality_stage, is_synthetic, source_ref, event_id,
            ))
    finally:
        work.close()

    problems: list[str] = []
    if dup_measurement_ids:
        problems.append(
            f"measurement_id が複数行にマッチした（alias/place の解決が「関数」で"
            f"なくなっている）: {len(dup_measurement_ids)}件 "
            f"（例: {dup_measurement_ids[:5]}）"
        )
    if unresolved_alias_count:
        problems.append(
            f"variable_alias で解決できない (variable, source_id) の行: "
            f"{unresolved_alias_count}件（例: {unresolved_alias}）"
        )
    if unresolved_place_count:
        problems.append(
            f"place_source_ref で解決できない site_id の行: "
            f"{unresolved_place_count}件（例: {unresolved_place}）"
        )
    if period_mismatch_count:
        problems.append(
            f"value_grain と period_grain が食い違い、かつ period_exceptions.yaml に"
            f"宣言が無い行がある: {period_mismatch_count}件"
            f"（例（上限{_SAMPLE_LIMIT}件）: {period_mismatches}）"
        )
    unused = usage.unused_entries()
    if unused:
        problems.append(
            f"period_exceptions.yaml に宣言されているが1件も該当しなかったエントリ: {unused}"
        )
    mismatched_expected = usage.mismatched_expected_counts()
    if mismatched_expected:
        problems.append(
            "period_exceptions.yaml の expected_row_count と実測件数が食い違う: "
            f"{mismatched_expected}（宣言 (expected, actual) の順）"
        )

    if problems:
        raise common.MigrationError(
            "observation の構築を中止した。以下の問題を解消してから再実行すること:\n- "
            + "\n- ".join(problems)
        )

    stats = {
        "total_measurements": total,
        "n_observation": len(rows),
        "censoring_counts": dict(censoring_counts),
        "zero_imputed_count": zero_imputed_count,
        "grain_mismatch_count": grain_mismatch_count,
        "exception_usage": usage.counts(),
    }
    return rows, stats


def write_observation(rows: list[tuple], out_path) -> None:
    conn = common.fresh_sqlite(out_path)
    try:
        conn.execute(_CREATE_OBSERVATION_SQL)
        conn.executemany(_INSERT_SQL, rows)
        conn.commit()
    finally:
        conn.close()


def render_report(stats: dict) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Phase B ファクト移行 — observation の要約")
    a("")
    a(
        "`scripts/b03_build_observation.py` が `data/db/ryuiki.sqlite` の "
        "`measurements` から `data/db/v2.sqlite` の `observation` を作った結果の要約。"
        "詳細な設計判断は `docs/plans/PHASE_B_FACT_SLICE.md` 参照。"
    )
    a("")
    a(f"- `measurements` 総行数: **{stats['total_measurements']:,}**")
    a(f"- `observation` 行数: **{stats['n_observation']:,}**")
    a(
        "- alias（variable_alias）解決率: "
        f"{stats['n_observation']:,} / {stats['total_measurements']:,} "
        "（全行解決。1行でも未解決なら、このレポート自体が作られず b03 が例外で止まる）"
    )
    a(
        "- place（place_source_ref）解決率: "
        f"{stats['n_observation']:,} / {stats['total_measurements']:,} "
        "（同上。全行解決）"
    )
    a("")
    a("## censoring の内訳（ADR-0009・design.md D2）")
    a("")
    a("| censoring | 行数 |")
    a("|---|---:|")
    # 5値をここに直書きしない。`censoring.ALL_CENSORING_VALUES` はまさにこの
    # 用途（censoring の全語彙を1箇所から引く）のために定義されている
    # （レビュー指摘: 定義済みの定数が他のどこからも使われていなかった）。
    for key in censoring.ALL_CENSORING_VALUES:
        n = stats["censoring_counts"].get(key, 0)
        a(f"| `{key}` | {n:,} |")
    a("")
    a(
        f"`imputation='zero'` で値（0.0）が入る行（`below_lod` + `not_detected`）: "
        f"**{stats['zero_imputed_count']:,}行**"
        "（`above_lod`/`unknown` には代入しない。design.md D2）。"
    )
    a("")
    a("## value_grain != period_grain（design.md D4）")
    a("")
    a(
        f"食い違う行: **{stats['grain_mismatch_count']:,}行**"
        "（すべて `period_exceptions.yaml` の宣言でカバーされている。"
        "宣言に無い食い違いが1件でもあれば b03 は例外で止まる）。"
    )
    a("")
    a("宣言ごとの実測件数（`period_exceptions.yaml`）:")
    a("")
    a("| source_id | 該当行数 |")
    a("|---|---:|")
    for sid, n in sorted(stats["exception_usage"].items()):
        a(f"| `{sid}` | {n:,} |")
    a("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurements-db", default=str(DEFAULT_MEASUREMENTS_DB))
    parser.add_argument(
        "--registry-db",
        default=None,
        help=f"既定は RYUIKI_REGISTRY_DB 環境変数、それも無ければ {DEFAULT_REGISTRY_DB}",
    )
    parser.add_argument("--exceptions-yaml", default=str(DEFAULT_EXCEPTIONS_YAML))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    registry_db = common.resolve_registry_db(args.registry_db, DEFAULT_REGISTRY_DB)

    print(f"▶ 読み取り専用で開く: {args.measurements_db}")
    print(f"▶ 読み取り専用で開く: {registry_db}")

    with common.timed_step("observation を構築") as info:
        rows, stats = build_observation(args.measurements_db, registry_db, args.exceptions_yaml)
        info["n"] = len(rows)

    with common.timed_step(f"{args.out} に書き出し") as info:
        write_observation(rows, args.out)
        info["n"] = len(rows)

    report_path = pathlib.Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(stats), encoding="utf-8")
    print(f"→ {report_path}")


if __name__ == "__main__":
    main()
