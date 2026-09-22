"""`organism_records.observed_on` から `(period_grain, period_start, period_end,
day_changed, month_changed)` を導出する（O-1 設計 v2 D1。
`scripts/migrate/occurrence_period_shapes.yaml` が形ごとの期待件数を宣言する）。

`scripts/migrate/period.py`（`measurements`/`sensor_timeseries` 専用）とは別モジュール
にしてある——`observed_on` の形は `measured_on`/`phenomenon_time` と重ならない
（区間・ミリ秒・秒無し等、12種類）ため、同じ分岐を無理に共有すると絡み合う。ただし
「暦年・月の区間の計算」は同じ規則（ADR-0008）なので `migrate.period` の
`year_bounds`/`month_bounds`（公開名）を再利用する——`period.py` の他の関数・挙動は
変えていない（`scripts/b03_build_observation.py` の出力は影響を受けない）。

## 形の定義の正はコード（`_SHAPE_DEFS`）

`occurrence_period_shapes.yaml` は形ごとの `expected_row_count`/`note` だけを持つ。
正規表現・`period_grain`・展開規則は**すべてこのモジュールのコード**が正で、YAML には
書かない（二重に持って食い違う余地を無くす——コードレビュー指摘4）。YAML の形の名前が
コードの `_SHAPE_DEFS` と過不足なく一致することは `assert_declared_shapes_match_code()`
が検証する。

## 分類は正規表現を順に試す（コードレビュー指摘9）

文字数（`length`）だけで形を決め打つと、将来2つの形が同じ文字数を持つように
なったときに黙って誤分類する恐れがある。`classify_shape()` は `_SHAPE_DEFS` を
**全部**試し、一致した形の名前を集める——0件なら `UnknownPeriodShapeError`、
2件以上（複数の形に同時に一致する値）なら `AmbiguousPeriodShapeError` で
止める（黙ってどちらかを選ばない）。`_SHAPE_DEFS` の並び順は読みやすさのため
だけで、全パターンを毎回試すため判定の速さにも正しさにも影響しない。

## 実在する日付・時刻としての検証（コードレビュー指摘3）

正規表現は桁の並びしか見ないため、`'2020-02-30'`（存在しない日）や
`'...T24:00'`（存在しない時刻）も通してしまう。展開の途中で
`datetime.date.fromisoformat`/`datetime.datetime.fromisoformat` に通し、
`ValueError` を `record_id`・元の値を含む `InvalidPeriodValueError`
（`MigrationError` のサブクラス）に変換する。

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
止める対象ではない（実測期待は `docs/plans/PHASE_B_OCCURRENCE.md` 参照。
このモジュールは特定の期待値を検証しない——検証していない数字をコードに
書かない）。
"""
from __future__ import annotations

import datetime
import pathlib
import re
from dataclasses import dataclass
from typing import NamedTuple

from . import period
from .common import MigrationError, load_yaml
from .period import month_bounds, parse_utc_offset, year_bounds

DEFAULT_SHAPES_YAML = pathlib.Path(__file__).resolve().parent / "occurrence_period_shapes.yaml"

REQUIRED_SHAPE_KEYS = ("expected_row_count", "note")

# 形の名前 -> (検証用の正規表現、period_grain)。`classify_shape()` はこの並びを
# 全部試し、一致した名前を集める（複数一致なら止める。コードレビュー指摘9）。
# **並び順は読みやすさのためだけ**（`day` が実測で最多なので先頭に置いてある）で、
# 判定の速さ・正しさのどちらにも影響しない——全パターンを毎回試すため。
#
# `\d` ではなく `[0-9]` を使う（コードレビュー指摘2）: Python の `re` は `str`
# パターンの `\d` を既定で Unicode 数字（全角数字 '２０２０' 等）にもマッチさせる。
# `[0-9]` は ASCII の数字だけにマッチする。
_SHAPE_DEFS: tuple[tuple[str, re.Pattern, str], ...] = (
    ("day", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"), "day"),
    ("instant_second", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$"), "instant"),
    ("instant_minute", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$"), "instant"),
    ("day_interval", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}$"), "survey_period"),
    ("year", re.compile(r"^[0-9]{4}$"), "year"),
    ("month", re.compile(r"^[0-9]{4}-[0-9]{2}$"), "month"),
    ("year_interval", re.compile(r"^[0-9]{4}/[0-9]{4}$"), "survey_period"),
    ("instant_minute_z", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z$"), "instant"),
    (
        "instant_millisecond_z",
        re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"),
        "instant",
    ),
    ("instant_second_z", re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"), "instant"),
    (
        "instant_minute_z_interval",
        re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}Z$"),
        "survey_period",
    ),
    ("month_interval", re.compile(r"^[0-9]{4}-[0-9]{2}/[0-9]{4}-[0-9]{2}$"), "survey_period"),
)

_SHAPE_NAMES: frozenset[str] = frozenset(name for name, _pattern, _grain in _SHAPE_DEFS)
_GRAIN_BY_SHAPE: dict[str, str] = {name: grain for name, _pattern, grain in _SHAPE_DEFS}

# 展開に 'Z' → ローカル時刻の変換を要する形（公開名。呼び出し側
# `scripts/b06_build_occurrence.py` が Z 変換件数の集計に使う）。
Z_SHAPES = frozenset(
    {"instant_minute_z", "instant_second_z", "instant_millisecond_z", "instant_minute_z_interval"}
)


@dataclass(frozen=True)
class PeriodShape:
    """`occurrence_period_shapes.yaml` の1エントリ。形の定義（正規表現・
    period_grain）はここには無い——コード（`_SHAPE_DEFS`）が正（モジュール
    docstring参照）。
    """

    name: str
    expected_row_count: int
    note: str


def load_period_shapes(path=DEFAULT_SHAPES_YAML) -> dict[str, PeriodShape]:
    """宣言表を読む。空（`{}`）でもよい——その場合は
    `assert_declared_shapes_match_code()` が「コードの12形が1つも宣言されて
    いない」として即座に止める。
    """
    raw = load_yaml(path)
    out: dict[str, PeriodShape] = {}
    for name, spec in raw.items():
        out[name] = PeriodShape(
            name=name,
            expected_row_count=spec["expected_row_count"],
            note=spec.get("note", ""),
        )
    return out


def validate_occurrence_period_shapes_shape(path=DEFAULT_SHAPES_YAML) -> None:
    """`occurrence_period_shapes.yaml` の構造を検証する（原本DBを必要としない。
    CI 用、かつ `scripts/b06_build_occurrence.py` も実行時に呼ぶ——コードレビュー
    指摘6）。

    - 各エントリが `REQUIRED_SHAPE_KEYS`（`expected_row_count`/`note`）を
      すべて持ち、`expected_row_count` が整数であること（必須キーの検査は
      `period.required_keys_problems()`、整数検査は
      `period.validate_expected_row_count()` に委ねる。必須キー自体が欠けて
      いるエントリは整数検査を二重にしない——/simplify 指摘5・6）。
    - **宣言された形の名前の集合が、コード（`_SHAPE_DEFS`）の12形と過不足なく
      一致すること**（コードレビュー指摘4）。片方にしかない名前があれば、
      それを名指しして止める。
    """
    raw = load_yaml(path)
    problems = period.required_keys_problems(raw, REQUIRED_SHAPE_KEYS)
    for name, spec in period.entries_with_required_keys(raw, REQUIRED_SHAPE_KEYS).items():
        count_problem = period.validate_expected_row_count(name, spec)
        if count_problem:
            problems.append(count_problem)
    if problems:
        raise MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))

    declared_names = frozenset(raw)
    missing_in_yaml = sorted(_SHAPE_NAMES - declared_names)
    extra_in_yaml = sorted(declared_names - _SHAPE_NAMES)
    if missing_in_yaml or extra_in_yaml:
        raise MigrationError(
            f"{path} の形の名前がコード（_SHAPE_DEFS）と一致しない: "
            f"YAML に無い（コードにはある）: {missing_in_yaml} / "
            f"YAML にしか無い（コードに無い）: {extra_in_yaml}"
        )


class UnknownPeriodShapeError(MigrationError):
    """`observed_on` の文字数・並びが `_SHAPE_DEFS`（コード側）のどれとも
    一致しないときに投げる。推測でパースせず即座に止まる。
    """

    def __init__(self, value: str, record_id=None):
        self.value = value
        self.record_id = record_id
        super().__init__(
            f"observed_on の形が想定外（12形のいずれにも一致しない）: {value!r}"
            f"（record_id={record_id!r}）。scripts/migrate/occurrence_period.py の "
            "_SHAPE_DEFS と scripts/migrate/occurrence_period_shapes.yaml を確認すること。"
        )


class AmbiguousPeriodShapeError(MigrationError):
    """`observed_on` が複数の形に同時に一致したときに投げる（コードレビュー
    指摘9）。`_SHAPE_DEFS` の正規表現どうしが意図せず重なった場合の検出。
    """

    def __init__(self, value: str, matched_shapes: list[str], record_id=None):
        self.value = value
        self.matched_shapes = matched_shapes
        self.record_id = record_id
        super().__init__(
            f"observed_on={value!r}（record_id={record_id!r}）が複数の形に同時に一致した: "
            f"{matched_shapes}。_SHAPE_DEFS の正規表現が重なっている。"
        )


class InvalidPeriodValueError(MigrationError):
    """`observed_on` の形は正規表現に一致するが、実在しない日付・時刻
    （`'2020-02-30'`・`'...T24:00'` 等）のときに投げる（コードレビュー指摘3）。
    素の `ValueError` ではなく、値と `record_id` を含めて止める。
    """

    def __init__(self, value: str, record_id, detail: str):
        self.value = value
        self.record_id = record_id
        self.detail = detail
        super().__init__(
            f"observed_on={value!r}（record_id={record_id!r}）が実在する日付・時刻ではない: {detail}"
        )


class YearBoundaryCrossedError(MigrationError):
    """'Z' → ローカル時刻の変換で年が変わったときに投げる（D3の前提が破れた場合。
    実測では0件——将来のデータでここに来たら、region の utc_offset か
    `source_regions.yaml` の宣言を見直すこと）。
    """

    def __init__(self, raw: str, converted_year: int, raw_year: int, record_id=None):
        self.raw = raw
        self.converted_year = converted_year
        self.raw_year = raw_year
        self.record_id = record_id
        super().__init__(
            f"'Z' → ローカル時刻の変換で年が変わった（D3の前提が破れている）: "
            f"observed_on={raw!r}（record_id={record_id!r}、元の年 {raw_year}）"
            f"→ 変換後の年 {converted_year}。"
        )


def assert_declared_shapes_match_code(shapes: dict[str, PeriodShape], path=DEFAULT_SHAPES_YAML) -> None:
    """`load_period_shapes()` の戻り値がコード（`_SHAPE_DEFS`）の12形と過不足なく
    一致することを検証する（コードレビュー指摘4）。`scripts/b06_build_occurrence.py`
    が読み込み直後に呼ぶ（`validate_occurrence_period_shapes_shape()` は生の YAML
    dict を対象にする構造検証で、こちらは実際に読み込んだ `PeriodShape` の集合を
    対象にする——二重に見えるが対象が違う。前者は CI 用に原本DB無しで呼べる）。
    """
    declared_names = frozenset(shapes)
    missing_in_yaml = sorted(_SHAPE_NAMES - declared_names)
    extra_in_yaml = sorted(declared_names - _SHAPE_NAMES)
    if missing_in_yaml or extra_in_yaml:
        raise MigrationError(
            f"{path} の形の名前がコード（_SHAPE_DEFS）と一致しない: "
            f"YAML に無い（コードにはある）: {missing_in_yaml} / "
            f"YAML にしか無い（コードに無い）: {extra_in_yaml}"
        )


def classify_shape(value: str, *, record_id=None) -> str:
    """`value`（`observed_on`、NULL でない前提）の形の名前を返す。

    `_SHAPE_DEFS` を全部試し、一致した形が0件なら `UnknownPeriodShapeError`、
    2件以上（正規表現が重なっている）なら `AmbiguousPeriodShapeError`。
    """
    matches = [name for name, pattern, _grain in _SHAPE_DEFS if pattern.fullmatch(value)]
    if not matches:
        raise UnknownPeriodShapeError(value, record_id)
    if len(matches) > 1:
        raise AmbiguousPeriodShapeError(value, matches, record_id)
    return matches[0]


def _real_date(text: str, *, value: str, record_id) -> datetime.date:
    try:
        return datetime.date.fromisoformat(text)
    except ValueError as e:
        raise InvalidPeriodValueError(value, record_id, str(e)) from e


def _real_datetime(text19: str, *, value: str, record_id) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat(text19)
    except ValueError as e:
        raise InvalidPeriodValueError(value, record_id, str(e)) from e


def _convert_z_instant(
    label: str, utc_offset: str, *, value: str, record_id
) -> tuple[str, bool, bool]:
    """'Z' 終端の瞬時ラベル（分/秒/ミリ秒のいずれか。`label` はそのラベル単体、
    区間なら片側）を、秒を補完・ミリ秒を切り捨てたうえで `utc_offset` を加えて
    ローカル時刻にする。

    戻り値: `(period_label19, day_changed, month_changed)`。実在しない日付・
    時刻なら `InvalidPeriodValueError`、年が変わっていたら
    `YearBoundaryCrossedError`。
    """
    assert label.endswith("Z")
    body = label[:-1]  # 'Z' を落とす
    if len(body) == 16:  # 'YYYY-MM-DDTHH:MM' -> 秒を補完
        body19 = body + ":00"
    else:  # 19桁（秒あり）または 23桁（秒+ミリ秒）
        body19 = body[:19]  # ミリ秒があれば切り捨て
    raw_dt = _real_datetime(body19, value=value, record_id=record_id)
    converted_dt = raw_dt + parse_utc_offset(utc_offset)
    converted19 = converted_dt.strftime("%Y-%m-%dT%H:%M:%S")

    if converted_dt.year != raw_dt.year:
        raise YearBoundaryCrossedError(value, converted_dt.year, raw_dt.year, record_id)
    day_changed = converted_dt.date() != raw_dt.date()
    month_changed = (converted_dt.year, converted_dt.month) != (raw_dt.year, raw_dt.month)
    return converted19, day_changed, month_changed


class ExpandedPeriod(NamedTuple):
    """`expand_period()` の戻り値。行ごとに1個作る（`scripts/b06_build_occurrence.py`
    が823,692行ぶん）ホットパスなので、`@dataclass` ではなく `NamedTuple`
    にしてある（属性アクセスは同じまま。/simplify 指摘11。実測で約0.9秒短縮）。
    """

    shape: str
    period_grain: str
    period_start: str
    period_end: str
    day_changed: bool
    month_changed: bool


def expand_period(
    value: str,
    utc_offset: str,
    *,
    record_id=None,
) -> ExpandedPeriod:
    """`value`（NULL でない `observed_on`）を `(period_grain, period_start,
    period_end)` に展開する。'Z' を含む形は `utc_offset`（`source_regions.py` が
    返す、その行の出典の region に属する値）でローカル時刻に変換する。

    形の分類・実在する日付/時刻としての検証は `classify_shape()`/`_real_date()`/
    `_real_datetime()` に委ねる（モジュール docstring参照）。`record_id` は
    例外メッセージにだけ使う（呼び出し側 `scripts/b06_build_occurrence.py` が
    行の識別に使えるように）。
    """
    shape = classify_shape(value, record_id=record_id)
    grain = _GRAIN_BY_SHAPE[shape]
    day_changed = False
    month_changed = False

    if shape == "year":
        year = int(value)
        _real_date(f"{year:04d}-01-01", value=value, record_id=record_id)
        start, end = year_bounds(year)
    elif shape == "month":
        _real_date(f"{value}-01", value=value, record_id=record_id)
        start, end = month_bounds(value)
    elif shape == "day":
        _real_date(value, value=value, record_id=record_id)
        start = end = value
    elif shape == "year_interval":
        y1, y2 = value.split("/")
        _real_date(f"{int(y1):04d}-01-01", value=value, record_id=record_id)
        _real_date(f"{int(y2):04d}-01-01", value=value, record_id=record_id)
        start, _ = year_bounds(int(y1))
        _, end = year_bounds(int(y2))
    elif shape == "month_interval":
        ym1, ym2 = value.split("/")
        _real_date(f"{ym1}-01", value=value, record_id=record_id)
        _real_date(f"{ym2}-01", value=value, record_id=record_id)
        start, _ = month_bounds(ym1)
        _, end = month_bounds(ym2)
    elif shape == "day_interval":
        start, end = value.split("/")
        _real_date(start, value=value, record_id=record_id)
        _real_date(end, value=value, record_id=record_id)
    elif shape == "instant_minute":
        start = end = value + ":00"
        _real_datetime(start, value=value, record_id=record_id)
    elif shape == "instant_second":
        _real_datetime(value, value=value, record_id=record_id)
        start = end = value
    elif shape in ("instant_minute_z", "instant_second_z", "instant_millisecond_z"):
        start, day_changed, month_changed = _convert_z_instant(
            value, utc_offset, value=value, record_id=record_id
        )
        end = start
    elif shape == "instant_minute_z_interval":
        raw_start, raw_end = value.split("/")
        start, day_changed_s, month_changed_s = _convert_z_instant(
            raw_start, utc_offset, value=value, record_id=record_id
        )
        end, day_changed_e, month_changed_e = _convert_z_instant(
            raw_end, utc_offset, value=value, record_id=record_id
        )
        day_changed = day_changed_s or day_changed_e
        month_changed = month_changed_s or month_changed_e
    else:  # pragma: no cover - _SHAPE_DEFS で尽くしているはず
        raise MigrationError(f"未対応の形: {shape!r}")

    if start > end:
        raise MigrationError(
            f"observed_on={value!r}（record_id={record_id!r}）の展開で "
            f"period_start({start!r}) > period_end({end!r}) になった（D3の前提が破れている）。"
        )

    return ExpandedPeriod(
        shape=shape, period_grain=grain, period_start=start, period_end=end,
        day_changed=day_changed, month_changed=month_changed,
    )
