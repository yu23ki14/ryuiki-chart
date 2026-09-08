"""期間（period_grain / period_start / period_end）の導出（design.md D4・ADR-0008）。

`measurements.measured_on` は実測で2つの桁数しか持たない:

  - 10桁（`'2015-04-08'`）: 検体を採った1日 → `period_grain='day'`
  - 4桁（`'2015'`）       : 年次の値。`variable_alias.grain`（`'year'`=暦年 or
    `'fiscal_year'`=年度）に従って期間を展開する

「値が代表する期間の粒度」（`value_grain`。alias が言う。`measured_on` の桁数
からは再導出しない）と「日付の精度から確実に言える期間の粒度」
（`period_grain`）は別の軸（D4）。通常はこの2つが一致するが、4桁の日付
（年度番号）しか持たないのに alias が `'year'`/`'fiscal_year'` 以外
（＝日次や月次の統計量）を宣言している行だけは、日付からは
period_grain を決められない。`period_exceptions.yaml` に宣言された
`source_id` のときだけ、そこに書かれた `period_grain_override` を使うことを
許す。宣言に無い `source_id` でこの状況に出会ったら `PeriodMismatchError` を
投げる（呼び出し側の `scripts/b03_build_observation.py` が件数・実例をまとめて
報告する。ここでは1行ずつの判定だけを行う）。
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .common import MigrationError, load_yaml

DEFAULT_EXCEPTIONS_YAML = pathlib.Path(__file__).resolve().parent / "period_exceptions.yaml"

# measured_on が4桁のとき、alias の grain がこれらのどちらかなら
# period_grain もそのまま採用できる（日付の4桁が年度/暦年のどちらの
# ラベルかは alias 側の宣言に従う。design.md D4「暦年か年度かは alias の
# grain に従って展開する」）。
_YEAR_LIKE_GRAINS = ("year", "fiscal_year")


@dataclass(frozen=True)
class PeriodException:
    """`period_exceptions.yaml` の1エントリ。"""

    source_id: str
    period_grain_override: str
    expected_row_count: int | None
    reason: str
    restoration_plan: str


def _load_raw(path) -> dict:
    """`period_exceptions.yaml` を生の dict（YAML をそのまま読んだもの）として返す。
    無ければ `{}`。`load_period_exceptions`（値を埋めて `PeriodException` にする）と
    `validate_period_exceptions_shape`（欠けているキーそのものを検出したい）の
    両方がこの読み込みを共有する（検証ロジックを2箇所に書かないため）。

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


def validate_period_exceptions_shape(path=DEFAULT_EXCEPTIONS_YAML) -> None:
    """`period_exceptions.yaml` の各エントリが `REQUIRED_EXCEPTION_KEYS` を
    すべて持つことを検証する（原本DBを一切必要としない構造検証。CI 用）。
    1つでも欠けていれば、どのエントリの何が足りないかをまとめて示して
    `MigrationError` で止まる。
    """
    raw = _load_raw(path)
    problems: list[str] = []
    for source_id, spec in raw.items():
        if not isinstance(spec, dict):
            problems.append(f"{source_id}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
            continue
        missing = [k for k in REQUIRED_EXCEPTION_KEYS if spec.get(k) in (None, "")]
        if missing:
            problems.append(f"{source_id}: 必須キーが欠けている（または空）: {missing}")
    if problems:
        raise MigrationError(
            f"{path} の形が不正:\n- " + "\n- ".join(problems)
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


class PeriodExceptionUsage:
    """`period_exceptions.yaml` の各エントリが実際に何行に使われたかを数える。

    b03 の最後にこれを見て、1件も当たらなかったエントリが無いことを確認する
    （腐った例外が宣言だけ残り続けないように。design.md の明示的な要求）。
    """

    def __init__(self, exceptions: dict[str, PeriodException]):
        self._exceptions = exceptions
        self._used: dict[str, int] = {k: 0 for k in exceptions}

    def mark_used(self, source_id: str) -> None:
        self._used[source_id] = self._used.get(source_id, 0) + 1

    def counts(self) -> dict[str, int]:
        return dict(self._used)

    def unused_entries(self) -> list[str]:
        return [sid for sid, n in self._used.items() if n == 0]

    def mismatched_expected_counts(self) -> dict[str, tuple[int, int]]:
        """`expected_row_count` を宣言しているエントリについて、実測件数と
        食い違うものを `{source_id: (expected, actual)}` で返す。
        """
        mismatched = {}
        for sid, exc in self._exceptions.items():
            if exc.expected_row_count is None:
                continue
            actual = self._used.get(sid, 0)
            if actual != exc.expected_row_count:
                mismatched[sid] = (exc.expected_row_count, actual)
        return mismatched


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


def compute_period(
    measured_on: str,
    value_grain: str,
    source_id: str | None,
    exceptions: dict[str, PeriodException],
    usage: PeriodExceptionUsage,
) -> tuple[str, str, str]:
    """`(period_grain, period_start, period_end)` を返す。

    - `measured_on` が10桁: `period_grain='day'`、`period_start=period_end=measured_on`。
      `value_grain` が `'day'` でなければ、通常データには現れない想定外の形なので
      例外表を経由せず即座に `PeriodMismatchError`（このケースの宣言的な例外は
      現時点で存在しない）。
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
        f"measured_on の桁数が想定外（10桁か4桁のみ対応）: {measured_on!r}"
        f"（source_id={source_id!r}）。実データでは起きないはずの形。"
    )
