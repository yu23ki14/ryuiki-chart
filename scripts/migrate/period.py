"""期間（period_grain / period_start / period_end）の導出（design.md D4・ADR-0008・
センサーの縦線 設計 v2 T1・T2）。

`measured_on`/`phenomenon_time` は実測で4つの桁数を持つ（`measurements` は
10桁・4桁の2種、`sensor_timeseries` を足したことで7桁・25桁が加わった）:

  - 10桁（`'2015-04-08'`）        : 検体を採った1日、または日次センサー値
    → `period_grain='day'`
  - 7桁（`'2019-01'`）            : 出典が直接配った月次値（jma_monthly）
    → `period_grain='month'`
  - 25桁（`'2015-04-01T01:00:00+09:00'`）: 毎時・瞬時のセンサー値。
    `value_grain='instant'` ならラベルをそのまま採用、`value_grain='hour'`
    なら `time_label_conventions.yaml` の宣言（hour_ending）に従って
    ラベル−1時間を区間の始まりとする → `period_grain='hour'`/`'instant'`
  - 4桁（`'2015'`）               : 年次の値。`variable_alias.grain`
    （`'year'`=暦年 or `'fiscal_year'`=年度）に従って期間を展開する

「値が代表する期間の粒度」（`value_grain`。alias が言う。桁数からは再導出
しない）と「日付の精度から確実に言える期間の粒度」（`period_grain`）は
別の軸（D4）。通常はこの2つが一致するが、4桁の日付（年度番号）しか持たない
のに alias が `'year'`/`'fiscal_year'` 以外（＝日次や月次の統計量）を宣言
している行だけは、日付からは period_grain を決められない。
`period_exceptions.yaml` に宣言された `source_id` のときだけ、そこに書かれた
`period_grain_override` を使うことを許す。宣言に無い `source_id` でこの状況に
出会ったら `PeriodMismatchError` を投げる（呼び出し側の
`scripts/b03_build_observation.py` が件数・実例をまとめて報告する。ここでは
1行ずつの判定だけを行う）。

## T1: 時刻帯は持たない（新 ADR-0024）

`period_start`/`period_end` は常に時刻帯なしのローカル時刻
（`YYYY-MM-DD` または `YYYY-MM-DDTHH:MM:SS`）にする。25桁の原表記
（`+09:00` 付き）は `period_raw`（呼び出し側 `b03` が保持する）に残すが、
`period_start`/`period_end` には写さない。時刻の計算（hour_ending の
−1時間）も、時刻帯を落とした19桁の文字列に対して行う（`_strip_tz`）。
"""
from __future__ import annotations

import datetime
import pathlib
from dataclasses import dataclass

from .common import MigrationError, load_yaml

DEFAULT_EXCEPTIONS_YAML = pathlib.Path(__file__).resolve().parent / "period_exceptions.yaml"
DEFAULT_TIME_LABEL_CONVENTIONS_YAML = (
    pathlib.Path(__file__).resolve().parent / "time_label_conventions.yaml"
)

# measured_on が4桁のとき、alias の grain がこれらのどちらかなら
# period_grain もそのまま採用できる（日付の4桁が年度/暦年のどちらの
# ラベルかは alias 側の宣言に従う。design.md D4「暦年か年度かは alias の
# grain に従って展開する」）。
_YEAR_LIKE_GRAINS = ("year", "fiscal_year")

# 25桁ラベルのタイムゾーン部分。実データ（sensor_timeseries 717,839行）を
# 実測すると、25桁のラベルを持つ3出典（sagamihara_taiki_hourly・
# soramame_hourly_kanagawa・synthetic_sensor）は全行この表記だけを持つ
# （2026-09-15実測）。それ以外のオフセットは推測で読み替えず即座に止める。
_EXPECTED_TZ_SUFFIX = "+09:00"


@dataclass(frozen=True)
class PeriodException:
    """`period_exceptions.yaml` の1エントリ。"""

    source_id: str
    period_grain_override: str
    expected_row_count: int | None
    reason: str
    restoration_plan: str


def _load_raw(path) -> dict:
    """宣言 YAML（`period_exceptions.yaml`/`time_label_conventions.yaml`）を
    生の dict（YAML をそのまま読んだもの）として返す。無ければ `{}`。

    `load_period_exceptions`/`load_time_label_conventions`（値を埋めて
    `PeriodException`/`TimeLabelConvention` にする）と `_validate_shape`
    （欠けているキーそのものを検出したい。CI 用）の4つの読み込み全部がこれを
    共有する（検証ロジックを複数箇所に書かないため。B-3: 以前は
    `time_label_conventions.yaml` 側だけこれを経由せず `load_yaml` を
    直接呼んでいた）。

    読み込み自体は `scripts/reconcile/common.load_yaml` に委ねる
    （`migrate.common` が re-export したもの）。PyYAML が無いときの失敗が
    「モジュール冒頭の無条件 `import yaml` による素の `ImportError`」ではなく、
    `load_yaml` の説明的な `SystemExit` になる（レビュー指摘: 以前はここだけ
    YAML 読み込みを再実装していて、この失敗モードが `reconcile.common.load_yaml`
    と食い違っていた）。
    """
    return load_yaml(path)


def load_period_exceptions(path=DEFAULT_EXCEPTIONS_YAML) -> dict[str, PeriodException]:
    """例外表を読む。空（`{}`）でもよい——その場合は一切の食い違いを許さない。"""
    raw = _load_raw(path)
    out: dict[str, PeriodException] = {}
    for source_id, spec in raw.items():
        out[source_id] = PeriodException(
            source_id=source_id,
            period_grain_override=spec["period_grain_override"],
            expected_row_count=spec.get("expected_row_count"),
            reason=spec.get("reason", ""),
            restoration_plan=spec.get("restoration_plan", ""),
        )
    return out


# CI の構造検証（原本DBを必要としない）が要求する必須キー。`load_period_exceptions`
# は `reason`/`restoration_plan` が無くても空文字で埋めて動いてしまう（意図的な
# 「なぜ・いつ直すか」を書かせるための必須項目が、実行時のガードだけでは強制
# できない）ため、CI ではこちらで生の YAML の形を見る。
REQUIRED_EXCEPTION_KEYS = ("period_grain_override", "expected_row_count", "reason", "restoration_plan")


def _validate_shape(path, required_keys: tuple[str, ...]) -> None:
    """宣言 YAML（`source_id -> エントリ`の形）の各エントリが `required_keys` を
    すべて持つことを検証する（原本DBを一切必要としない構造検証。CI 用。B-3:
    `validate_period_exceptions_shape`/`validate_time_label_conventions_shape`
    が持っていた同型の検証ループを1つに集約したもの——違いは呼び出し側が渡す
    `required_keys` だけ）。1つでも欠けていれば、どのエントリの何が足りないかを
    まとめて示して `MigrationError` で止まる。
    """
    raw = _load_raw(path)
    problems: list[str] = []
    for source_id, spec in raw.items():
        if not isinstance(spec, dict):
            problems.append(f"{source_id}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
            continue
        missing = [k for k in required_keys if spec.get(k) in (None, "")]
        if missing:
            problems.append(f"{source_id}: 必須キーが欠けている（または空）: {missing}")
    if problems:
        raise MigrationError(
            f"{path} の形が不正:\n- " + "\n- ".join(problems)
        )


def validate_period_exceptions_shape(path=DEFAULT_EXCEPTIONS_YAML) -> None:
    """`period_exceptions.yaml` の各エントリが `REQUIRED_EXCEPTION_KEYS` を
    すべて持つことを検証する（`_validate_shape` 参照）。
    """
    _validate_shape(path, REQUIRED_EXCEPTION_KEYS)


@dataclass(frozen=True)
class TimeLabelConvention:
    """`time_label_conventions.yaml` の1エントリ（T2）。"""

    source_id: str
    convention: str
    expected_row_count: int | None
    evidence: str


# 対応する convention の語彙。今のところ hour_ending（ラベル＝区間の終わり）
# しか実データに現れないため、これだけを許す。将来 hour_beginning のような
# 別の慣習を持つ出典が現れたら、ここに増やしたうえで `_hour_bounds` にも
# 対応する分岐を足す（推測で hour_ending を既定にしない）。
_SUPPORTED_TIME_LABEL_CONVENTIONS = ("hour_ending",)


def load_time_label_conventions(
    path=DEFAULT_TIME_LABEL_CONVENTIONS_YAML,
) -> dict[str, TimeLabelConvention]:
    """`time_label_conventions.yaml` を読む。空（`{}`）でもよい——その場合は
    `value_grain='hour'` の行に一切出会えない（出会えば
    `UnknownTimeLabelConventionError`）。
    """
    raw = _load_raw(path)
    out: dict[str, TimeLabelConvention] = {}
    for source_id, spec in raw.items():
        convention = spec["convention"]
        if convention not in _SUPPORTED_TIME_LABEL_CONVENTIONS:
            raise MigrationError(
                f"{path} の {source_id!r}: convention={convention!r} は未対応"
                f"（対応済み: {_SUPPORTED_TIME_LABEL_CONVENTIONS}）。推測で計算式を"
                "決めず、対応する分岐をここに足してから使うこと。"
            )
        out[source_id] = TimeLabelConvention(
            source_id=source_id,
            convention=convention,
            expected_row_count=spec.get("expected_row_count"),
            evidence=spec.get("evidence", ""),
        )
    return out


# CI の構造検証が要求する必須キー（`validate_period_exceptions_shape` と同じ思想。
# `evidence` を必須にすることで「宣言はしたが根拠を書いていない」を防ぐ）。
REQUIRED_TIME_LABEL_KEYS = ("convention", "expected_row_count", "evidence")


def validate_time_label_conventions_shape(path=DEFAULT_TIME_LABEL_CONVENTIONS_YAML) -> None:
    """`time_label_conventions.yaml` の各エントリが `REQUIRED_TIME_LABEL_KEYS` を
    すべて持つことを検証する（`_validate_shape` 参照）。
    """
    _validate_shape(path, REQUIRED_TIME_LABEL_KEYS)


class _EntryUsage:
    """宣言 YAML（`source_id -> エントリ`）の各エントリが実際に何行に使われたかを
    数える汎用トラッカー（B-3）。

    `period_exceptions.yaml`（`PeriodException`）と `time_label_conventions.yaml`
    （`TimeLabelConvention`）はどちらも「`source_id` をキーにした宣言の集まりを
    受け取り、`mark_used` で使用回数を数え、`unused_entries`/
    `mismatched_expected_counts` で『1件も当たらなかった宣言・実測件数が
    `expected_row_count` と食い違う宣言』を検出する」という同じ形をしていた
    （実際に使うのは各エントリの `expected_row_count` 属性だけで、
    `PeriodException`/`TimeLabelConvention` のどちらも持つ）。`PeriodExceptionUsage`/
    `TimeLabelConventionUsage` はこのクラスへの別名（呼び出し側の型名・
    公開 API はそのまま維持する）。
    """

    def __init__(self, entries: dict):
        self._entries = entries
        self._used: dict[str, int] = {k: 0 for k in entries}

    def mark_used(self, source_id: str) -> None:
        self._used[source_id] = self._used.get(source_id, 0) + 1

    def counts(self) -> dict[str, int]:
        return dict(self._used)

    def unused_entries(self) -> list[str]:
        return [sid for sid, n in self._used.items() if n == 0]

    def mismatched_expected_counts(self) -> dict[str, tuple[int, int]]:
        mismatched = {}
        for sid, entry in self._entries.items():
            if entry.expected_row_count is None:
                continue
            actual = self._used.get(sid, 0)
            if actual != entry.expected_row_count:
                mismatched[sid] = (entry.expected_row_count, actual)
        return mismatched


TimeLabelConventionUsage = _EntryUsage


class UnknownTimeLabelConventionError(MigrationError):
    """`value_grain='hour'` の行なのに、その `source_id` が
    `time_label_conventions.yaml` に宣言されていないときに投げる（T2）。

    `PeriodMismatchError` とは別系統の例外にしてある——こちらは「1行だけ
    たまたま食い違う」ケースではなく、宣言そのものが無いという構造的な
    問題なので、`scripts/b03_build_observation.py` の per-row の
    try/except（`PeriodMismatchError` だけを捕まえて件数を集計するもの）を
    素通りしてすぐに止まる方が、175,344行分の無駄な集計を待たせずに済む。
    """

    def __init__(self, source_id: str | None, value_grain: str):
        self.source_id = source_id
        self.value_grain = value_grain
        super().__init__(
            f"value_grain={value_grain!r} の出典 source_id={source_id!r} が "
            "time_label_conventions.yaml に宣言されていない。value_grain='hour' の"
            "出典は必ず宣言が要る（T2）。scripts/migrate/time_label_conventions.yaml に"
            "convention/expected_row_count/evidence を書いてから再実行すること。"
        )


class PeriodMismatchError(MigrationError):
    """`value_grain` と `measured_on` の桁数が矛盾していて、かつ
    `period_exceptions.yaml` に宣言が無い行に出会ったときに投げる。
    呼び出し側で1行ずつ捕まえて集計し、まとめて報告することを想定している。
    """

    def __init__(self, measured_on: str, value_grain: str, source_id: str | None):
        self.measured_on = measured_on
        self.value_grain = value_grain
        self.source_id = source_id
        super().__init__(
            f"value_grain={value_grain!r} と measured_on={measured_on!r} の桁数が"
            f"矛盾している（source_id={source_id!r}）。period_exceptions.yaml に"
            "宣言が無い。"
        )


# `PeriodExceptionUsage`（b03 の最後にこれを見て、1件も当たらなかったエントリが
# 無いことを確認する。腐った例外が宣言だけ残り続けないように）は `_EntryUsage`
# への別名（B-3。上の `TimeLabelConventionUsage` と同じクラスだった）。
PeriodExceptionUsage = _EntryUsage


def _year_bounds(year: int) -> tuple[str, str]:
    """暦年（1/1〜12/31。ADR-0008）。"""
    return f"{year:04d}-01-01", f"{year:04d}-12-31"


def _fiscal_year_bounds(year: int) -> tuple[str, str]:
    """日本の年度（4/1〜翌年3/31。ADR-0008）。`year` は年度の開始年
    （`measured_on='2015'` は2015年度＝2015-04-01〜2016-03-31）。
    """
    return f"{year:04d}-04-01", f"{year + 1:04d}-03-31"


def _bounds_for_grain(grain: str, year: int) -> tuple[str, str]:
    if grain == "year":
        return _year_bounds(year)
    if grain == "fiscal_year":
        return _fiscal_year_bounds(year)
    raise MigrationError(
        f"period_grain_override が想定外: {grain!r}（'year' か 'fiscal_year' のみ対応。"
        "period_exceptions.yaml の宣言を見直すこと）"
    )


def _month_bounds(measured_on7: str) -> tuple[str, str]:
    """出典が直接配った月次値（jma_monthly、`'2019-01'` 形。7桁）の区間。
    月の初日〜末日（閉区間の終端を明示。ADR-0008）。`calendar` を使わず
    「翌月1日の前日」で月末日を出す（うるう年を含め、標準ライブラリの
    日付演算に判定を委ねる）。
    """
    year, month = int(measured_on7[:4]), int(measured_on7[5:7])
    start = f"{measured_on7}-01"
    next_month_first = (
        datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    )
    end = next_month_first - datetime.timedelta(days=1)
    return start, end.isoformat()


def _strip_tz(label: str, source_id: str | None) -> str:
    """25桁の `'YYYY-MM-DDTHH:MM:SS+09:00'` から時刻帯を落として、19桁の
    時刻帯なしローカル時刻にする（T1: `period_start`/`period_end` は時刻帯を
    持たない。原表記は `period_raw` として呼び出し側 `b03` が別途保持する）。

    `+09:00` 以外のオフセットは実データに存在しない想定外の形として扱い、
    推測で変換せず即座に止める（`_EXPECTED_TZ_SUFFIX` のコメント参照。
    2026-09-15実測で全717,839行中25桁の全行が `+09:00` であることを確認済み）。
    """
    if len(label) != 25 or label[19:] != _EXPECTED_TZ_SUFFIX:
        raise MigrationError(
            f"時刻ラベルの形が想定外（25桁・末尾 {_EXPECTED_TZ_SUFFIX!r} のみ対応）: "
            f"{label!r}（source_id={source_id!r}）。実データでは起きないはずの形。"
        )
    return label[:19]


def _hour_ending_bounds(label19: str) -> tuple[str, str]:
    """hour_ending（T1・T2）: ラベルは区間の終わり。
    `period_start = ラベル - 1時間`、`period_end = ラベル`。

    時刻帯を落とした19桁の文字列に対して `datetime` で減算する（設計 v2 の
    指示「時刻の計算は時刻帯を落としてから行う」）。日をまたぐ `00:00:00`
    ラベル（相模原市 CSV の「24時」＝翌日 00:00）も `datetime` の減算だけで
    正しく前日 23:00:00 になる——月末・年末をまたぐケースも同様
    （`datetime` の暦計算に委ねており、ここで特別扱いしていない）。
    """
    end = datetime.datetime.fromisoformat(label19)
    start = end - datetime.timedelta(hours=1)
    return start.strftime("%Y-%m-%dT%H:%M:%S"), label19


def compute_period(
    measured_on: str,
    value_grain: str,
    source_id: str | None,
    exceptions: dict[str, PeriodException],
    usage: PeriodExceptionUsage,
    time_conventions: dict[str, TimeLabelConvention] | None = None,
    time_usage: TimeLabelConventionUsage | None = None,
) -> tuple[str, str, str]:
    """`(period_grain, period_start, period_end)` を返す。

    - `measured_on` が10桁: `period_grain='day'`、`period_start=period_end=measured_on`。
      `value_grain` が `'day'` でなければ、通常データには現れない想定外の形なので
      例外表を経由せず即座に `PeriodMismatchError`（このケースの宣言的な例外は
      現時点で存在しない）。
    - `measured_on` が7桁（`'2019-01'`）: `value_grain='month'` のときだけ
      `period_grain='month'` として月の初日〜末日を返す（`_month_bounds`）。
      それ以外の `value_grain` は想定外なので `PeriodMismatchError`。
    - `measured_on` が25桁（`'...+09:00'`）: `value_grain='instant'` なら
      ラベルをそのまま `period_start=period_end` にする（時刻帯だけ落とす）。
      `value_grain='hour'` なら `time_conventions` の宣言（T2。無ければ
      `UnknownTimeLabelConventionError`）に従ってラベル−1時間を区間の始まりに
      する。それ以外の `value_grain` は想定外なので `PeriodMismatchError`。
    - `measured_on` が4桁: `value_grain` が `'year'`/`'fiscal_year'` ならそれを
      `period_grain` として採用する。どちらでもなければ `exceptions` に
      `source_id` の宣言があるときだけ、その `period_grain_override` を使う
      （`usage.mark_used` で使用回数を記録する）。宣言が無ければ
      `PeriodMismatchError`。
    - それ以外の桁数は実データに存在しない想定外なので `MigrationError`。
    """
    n = len(measured_on)
    if n == 10:
        if value_grain != "day":
            raise PeriodMismatchError(measured_on, value_grain, source_id)
        return "day", measured_on, measured_on

    if n == 7:
        if value_grain != "month":
            raise PeriodMismatchError(measured_on, value_grain, source_id)
        start, end = _month_bounds(measured_on)
        return "month", start, end

    if n == 25:
        if value_grain == "instant":
            label19 = _strip_tz(measured_on, source_id)
            return "instant", label19, label19
        if value_grain == "hour":
            conventions = time_conventions or {}
            conv = conventions.get(source_id) if source_id is not None else None
            if conv is None:
                raise UnknownTimeLabelConventionError(source_id, value_grain)
            if time_usage is not None:
                time_usage.mark_used(source_id)
            label19 = _strip_tz(measured_on, source_id)
            # conv.convention は load_time_label_conventions が
            # _SUPPORTED_TIME_LABEL_CONVENTIONS で既に絞っているので、
            # ここでは唯一の対応値（hour_ending）を前提にしてよい。
            start, end = _hour_ending_bounds(label19)
            return "hour", start, end
        raise PeriodMismatchError(measured_on, value_grain, source_id)

    if n == 4:
        year = int(measured_on)
        if value_grain in _YEAR_LIKE_GRAINS:
            period_grain = value_grain
        else:
            exc = exceptions.get(source_id) if source_id is not None else None
            if exc is None:
                raise PeriodMismatchError(measured_on, value_grain, source_id)
            usage.mark_used(source_id)
            period_grain = exc.period_grain_override
        start, end = _bounds_for_grain(period_grain, year)
        return period_grain, start, end

    raise MigrationError(
        f"measured_on の桁数が想定外（4/7/10/25桁のみ対応）: {measured_on!r}"
        f"（source_id={source_id!r}）。実データでは起きないはずの形。"
    )
