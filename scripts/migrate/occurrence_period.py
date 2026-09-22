"""`organism_records.observed_on` から `(period_grain, period_start, period_end,
day_changed, month_changed)` を導出する（O-1 設計 v2 D1。
`scripts/migrate/occurrence_period_shapes.yaml` が形ごとの期待件数を宣言する）。

`scripts/migrate/period.py`（`measurements`/`sensor_timeseries` 専用）とは別モジュール
にしてある——`observed_on` の形は `measured_on`/`phenomenon_time` と重ならない
（区間・ミリ秒・秒無し等、12種類）ため、同じ関数を無理に共有すると分岐が絡み合う。
`period.py` はこのモジュールから一切 import されず、挙動も変えていない
（`scripts/b03_build_observation.py` の出力は影響を受けない）。

## 12の形（実測。data/db/ryuiki.sqlite、2026-09-22）

`_SHAPE_BY_LENGTH` に列挙する12種類（文字数で一意に決まる）。長さがこの集合に
無い値、または長さは合うが正規表現に一致しない値は `UnknownPeriodShapeError` で
即座に止まる（推測でパースしない）。

## 'Z' の変換（ADR-0024）

'Z' 終端の形（`instant_minute_z`/`instant_second_z`/`instant_millisecond_z`/
`instant_minute_z_interval`）は、`source_regions.py` が返す region の
`utc_offset`（例 `'+09:00'`）を「引いて」（辞書を引く、の意——加減算ではなく
値を参照する）ローカル時刻に変換する。変換は Python の `datetime` で行い、
SQLite の日時関数は一切使わない（CLAUDE.md の規約）。

## 年不変の機械検証

'Z' 変換後、`substr(period_raw,1,4) == 変換後の年`（区間は両端とも）が
崩れていたら `YearBoundaryCrossedError` で即座に止まる（D3の前提。実測では
0件だが、将来のデータでこの前提が破れたときに黙って見過ごさないため）。
日・月が変わった件数（`day_changed`/`month_changed`）はログ用に返すだけで、
止める対象ではない（実測期待: 日221・月10）。
"""
from __future__ import annotations

import datetime
import pathlib
import re
from dataclasses import dataclass

from .common import MigrationError, load_yaml
from .period import EntryUsage

DEFAULT_SHAPES_YAML = pathlib.Path(__file__).resolve().parent / "occurrence_period_shapes.yaml"

REQUIRED_SHAPE_KEYS = ("length", "period_grain", "expected_row_count", "note")

# 形の名前 -> (文字数, 検証用の正規表現)。文字数だけでも実データでは一意に形が
# 決まるが、正規表現でも形を確認する（宣言された文字数の範囲に、想定外の並びの
# 値が紛れ込んでも黙って通さないため）。
_SHAPE_DEFS: dict[str, tuple[int, re.Pattern]] = {
    "year": (4, re.compile(r"^\d{4}$")),
    "month": (7, re.compile(r"^\d{4}-\d{2}$")),
    "year_interval": (9, re.compile(r"^\d{4}/\d{4}$")),
    "day": (10, re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    "month_interval": (15, re.compile(r"^\d{4}-\d{2}/\d{4}-\d{2}$")),
    "instant_minute": (16, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")),
    "instant_minute_z": (17, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")),
    "instant_second": (19, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")),
    "instant_second_z": (20, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")),
    "day_interval": (21, re.compile(r"^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$")),
    "instant_millisecond_z": (24, re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")),
    "instant_minute_z_interval": (
        35,
        re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$"),
    ),
}

_SHAPE_BY_LENGTH: dict[int, str] = {length: name for name, (length, _pattern) in _SHAPE_DEFS.items()}

# 展開に 'Z' → ローカル時刻の変換を要する形（公開名。呼び出し側
# `scripts/b06_build_occurrence.py` が Z 変換件数の集計に使う）。
Z_SHAPES = frozenset(
    {"instant_minute_z", "instant_second_z", "instant_millisecond_z", "instant_minute_z_interval"}
)


@dataclass(frozen=True)
class PeriodShape:
    """`occurrence_period_shapes.yaml` の1エントリ。"""

    name: str
    length: int
    period_grain: str
    expected_row_count: int | None
    note: str


def _load_raw(path) -> dict:
    return load_yaml(path)


def load_period_shapes(path=DEFAULT_SHAPES_YAML) -> dict[str, PeriodShape]:
    """宣言表を読む。空（`{}`）でもよい——その場合は一切の形を許さない
    （`classify_shape` が最初の1行で `UnknownPeriodShapeError` を出す）。
    """
    raw = _load_raw(path)
    out: dict[str, PeriodShape] = {}
    for name, spec in raw.items():
        out[name] = PeriodShape(
            name=name,
            length=spec["length"],
            period_grain=spec["period_grain"],
            expected_row_count=spec.get("expected_row_count"),
            note=spec.get("note", ""),
        )
    return out


def validate_occurrence_period_shapes_shape(path=DEFAULT_SHAPES_YAML) -> None:
    """`occurrence_period_shapes.yaml` の各エントリが `REQUIRED_SHAPE_KEYS` を
    すべて持つことを検証する（原本DBを必要としない構造検証。CI 用。
    `migrate.period._validate_shape` と同じ流儀）。
    """
    raw = _load_raw(path)
    problems: list[str] = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            problems.append(f"{name}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
            continue
        missing = [k for k in REQUIRED_SHAPE_KEYS if spec.get(k) in (None, "")]
        if missing:
            problems.append(f"{name}: 必須キーが欠けている（または空）: {missing}")
    if problems:
        raise MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))


class UnknownPeriodShapeError(MigrationError):
    """`observed_on` の文字数・並びが `_SHAPE_DEFS`（コード側）のどれとも
    一致しないときに投げる。推測でパースせず即座に止まる。
    """

    def __init__(self, value: str):
        self.value = value
        super().__init__(
            f"observed_on の形が想定外（12形のいずれにも一致しない）: {value!r}。"
            "scripts/migrate/occurrence_period.py の _SHAPE_DEFS と "
            "scripts/migrate/occurrence_period_shapes.yaml を確認すること。"
        )


class UndeclaredPeriodShapeError(MigrationError):
    """形はコード側（`_SHAPE_DEFS`）には存在するが、
    `occurrence_period_shapes.yaml` に宣言が無いときに投げる（コードと宣言表が
    ずれている——宣言だけを足し忘れた場合に気づけるようにするため、
    `UnknownPeriodShapeError` とは別に区別する）。
    """

    def __init__(self, shape_name: str):
        self.shape_name = shape_name
        super().__init__(
            f"形 {shape_name!r} は scripts/migrate/occurrence_period.py の "
            "_SHAPE_DEFS にはあるが、occurrence_period_shapes.yaml に宣言が無い。"
        )


class YearBoundaryCrossedError(MigrationError):
    """'Z' → ローカル時刻の変換で年が変わったときに投げる（D3の前提が破れた場合。
    実測では0件——将来のデータでここに来たら、region の utc_offset か
    `source_regions.yaml` の宣言を見直すこと）。
    """

    def __init__(self, raw: str, converted_year: int, raw_year: int):
        self.raw = raw
        self.converted_year = converted_year
        self.raw_year = raw_year
        super().__init__(
            f"'Z' → ローカル時刻の変換で年が変わった（D3の前提が破れている）: "
            f"observed_on={raw!r}（元の年 {raw_year}）→ 変換後の年 {converted_year}。"
        )


def classify_shape(value: str, shapes: dict[str, PeriodShape]) -> str:
    """`value`（`observed_on`、NULL でない前提）の形の名前を返す。

    未知の長さ・長さは合うが正規表現に一致しない値は `UnknownPeriodShapeError`。
    コード側には定義があるが宣言表に無い形は `UndeclaredPeriodShapeError`。
    """
    name = _SHAPE_BY_LENGTH.get(len(value))
    if name is None or not _SHAPE_DEFS[name][1].fullmatch(value):
        raise UnknownPeriodShapeError(value)
    if name not in shapes:
        raise UndeclaredPeriodShapeError(name)
    return name


def _year_bounds(year: int) -> tuple[str, str]:
    return f"{year:04d}-01-01", f"{year:04d}-12-31"


def _month_bounds(ym: str) -> tuple[str, str]:
    """'YYYY-MM' の月初日〜月末日（`migrate.period._month_bounds` と同じ規則。
    `calendar` を使わず「翌月1日の前日」で求める）。
    """
    year, month = int(ym[:4]), int(ym[5:7])
    start = f"{ym}-01"
    next_month_first = (
        datetime.date(year + 1, 1, 1) if month == 12 else datetime.date(year, month + 1, 1)
    )
    end = next_month_first - datetime.timedelta(days=1)
    return start, end.isoformat()


def _parse_utc_offset(utc_offset: str) -> datetime.timedelta:
    """`'+09:00'`/`'-05:30'` のような表記を `timedelta` にする。"""
    sign = 1 if utc_offset[0] == "+" else -1
    hh, mm = utc_offset[1:].split(":")
    return sign * datetime.timedelta(hours=int(hh), minutes=int(mm))


def _convert_z_instant(value17_or_20_or_24: str, utc_offset: str) -> tuple[str, bool, bool]:
    """'Z' 終端の瞬時ラベル（分/秒/ミリ秒のいずれか）を、秒を補完・ミリ秒を切り捨てた
    うえで `utc_offset` を加えてローカル時刻にする。

    戻り値: `(period_label19, day_changed, month_changed)`。年が変わっていたら
    `YearBoundaryCrossedError` を投げる（呼び出し側に伝播させる）。
    """
    assert value17_or_20_or_24.endswith("Z")
    body = value17_or_20_or_24[:-1]  # 'Z' を落とす
    if len(body) == 16:  # 'YYYY-MM-DDTHH:MM' -> 秒を補完
        body19 = body + ":00"
    else:  # 19桁（秒あり）または 23桁（秒+ミリ秒）
        body19 = body[:19]  # ミリ秒があれば切り捨て
    raw_dt = datetime.datetime.fromisoformat(body19)
    converted_dt = raw_dt + _parse_utc_offset(utc_offset)
    converted19 = converted_dt.strftime("%Y-%m-%dT%H:%M:%S")

    if converted_dt.year != raw_dt.year:
        raise YearBoundaryCrossedError(value17_or_20_or_24, converted_dt.year, raw_dt.year)
    day_changed = converted_dt.date() != raw_dt.date()
    month_changed = (converted_dt.year, converted_dt.month) != (raw_dt.year, raw_dt.month)
    return converted19, day_changed, month_changed


@dataclass(frozen=True)
class ExpandedPeriod:
    """`expand_period()` の戻り値。"""

    shape: str
    period_grain: str
    period_start: str
    period_end: str
    day_changed: bool
    month_changed: bool


def expand_period(
    value: str,
    shapes: dict[str, PeriodShape],
    utc_offset: str,
) -> ExpandedPeriod:
    """`value`（NULL でない `observed_on`）を `(period_grain, period_start,
    period_end)` に展開する。'Z' を含む形は `utc_offset`（`source_regions.py` が
    返す、その行の出典の region に属する値）でローカル時刻に変換する。
    """
    shape = classify_shape(value, shapes)
    grain = shapes[shape].period_grain
    day_changed = False
    month_changed = False

    if shape == "year":
        start, end = _year_bounds(int(value))
    elif shape == "month":
        start, end = _month_bounds(value)
    elif shape == "day":
        start = end = value
    elif shape == "year_interval":
        y1, y2 = value.split("/")
        start, _ = _year_bounds(int(y1))
        _, end = _year_bounds(int(y2))
    elif shape == "month_interval":
        ym1, ym2 = value.split("/")
        start, _ = _month_bounds(ym1)
        _, end = _month_bounds(ym2)
    elif shape == "day_interval":
        start, end = value.split("/")
    elif shape == "instant_minute":
        start = end = value + ":00"
    elif shape == "instant_second":
        start = end = value
    elif shape in ("instant_minute_z", "instant_second_z", "instant_millisecond_z"):
        start, day_changed, month_changed = _convert_z_instant(value, utc_offset)
        end = start
    elif shape == "instant_minute_z_interval":
        raw_start, raw_end = value.split("/")
        start, day_changed_s, month_changed_s = _convert_z_instant(raw_start, utc_offset)
        end, day_changed_e, month_changed_e = _convert_z_instant(raw_end, utc_offset)
        day_changed = day_changed_s or day_changed_e
        month_changed = month_changed_s or month_changed_e
    else:  # pragma: no cover - _SHAPE_DEFS で尽くしているはず
        raise MigrationError(f"未対応の形: {shape!r}")

    if start > end:
        raise MigrationError(
            f"observed_on={value!r} の展開で period_start({start!r}) > period_end({end!r})"
            "になった（D3の前提が破れている）。"
        )

    return ExpandedPeriod(
        shape=shape, period_grain=grain, period_start=start, period_end=end,
        day_changed=day_changed, month_changed=month_changed,
    )


# `PeriodShapeUsage` は `migrate.period.EntryUsage`（形の使用状況を追跡する
# 汎用トラッカー）への別名（B-3 と同じ判断）。
PeriodShapeUsage = EntryUsage
