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

import copy
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


# ---------------------------------------------------------------------------
# 件数の宣言の上書き（Issue #29「縮小サンプル＋実行証明」A-2）。
#
# 原本の件数に合わせて書いた宣言（`expected_row_count`/`expected_count`/
# `breakdown.*`）は、縮小サンプルでは合わない。かといって宣言ファイル自体を
# サンプル用に複製すると「原本用と宣言が2つに増え、どちらが正か」という
# 別の問題を作る。そこで**数値だけ**を差し替える薄い上書き層をここに置く
# （reason/evidence/note のような意味の情報は宣言ファイル1つにしか持たせない）。
#
# 上書き元は `data/sample/declaration_counts.yaml`（1ファイルだけ）。キーは
# `<宣言ファイル名>:<エントリ名>[.<内訳キー>]`、値は整数だけ
# （`load_count_overlay_file` がファイル名でグルーピングし、各 `load_*` 関数は
# 自分のファイル名の分だけを `apply_count_overlay()` に渡す）。
# ---------------------------------------------------------------------------

def apply_count_overlay(entries: dict, overlay: dict[str, int]) -> dict:
    """`entries`（宣言 YAML を読んだままの「フラットな名前 -> スペック」の
    dict。`source_regions.yaml` なら `raw["sources"]` を渡す）に対し、
    `overlay`（`"名前"` または `"名前.内訳キー"` -> 新しい整数値）で
    `expected_row_count`/`expected_count`/`breakdown.<内訳キー>` だけを
    差し替えたコピーを返す。`reason`/`evidence`/`note` 等、意味の情報は
    一切書き換えない。

    `overlay` が指す名前・内訳キーが `entries` に実在しなければ `KeyError` で
    止まる（黙って無視すると、正本に新しいエントリが増えたのにサンプル側の
    宣言を更新し忘れたことに気づけなくなる）。
    """
    result = copy.deepcopy(entries)
    for flat_key, value in overlay.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"count overlay: {flat_key!r} の値は整数でなければならない（実際: {value!r}）")
        name, _, subkey = flat_key.partition(".")
        if name not in result or not isinstance(result[name], dict):
            raise KeyError(f"count overlay: エントリ {name!r} が宣言に無い（overlay キー: {flat_key!r}）")
        spec = result[name]
        if not subkey:
            if "expected_row_count" in spec:
                spec["expected_row_count"] = value
            elif "expected_count" in spec:
                spec["expected_count"] = value
            else:
                raise KeyError(
                    f"count overlay: エントリ {name!r} に expected_row_count/expected_count が無い"
                    f"（overlay キー: {flat_key!r}）"
                )
        else:
            breakdown = spec.get("breakdown")
            if not isinstance(breakdown, dict) or subkey not in breakdown:
                raise KeyError(
                    f"count overlay: エントリ {name!r} の breakdown に {subkey!r} が無い"
                    f"（overlay キー: {flat_key!r}）"
                )
            breakdown[subkey] = value
    return result


def load_count_overlay_file(path) -> dict[str, dict[str, int]]:
    """`data/sample/declaration_counts.yaml`（フラットな
    `"<宣言ファイル名>:<エントリ名>[.<内訳キー>]"` -> 整数 のマッピング、
    1ファイルにすべての宣言ファイル分をまとめて持つ）を読み、宣言ファイル名で
    グルーピングして返す（`{"period_exceptions.yaml": {"atsugi_river_water_quality":
    123}, ...}`）。各 `load_*`/`load_and_validate_*` 呼び出し側は、自分の
    宣言ファイル名に対応する部分辞書だけを `apply_count_overlay()` に渡す。

    キーに `:` が無ければ「`<ファイル名>:<エントリ名>` の形でない」として
    `MigrationError` で止まる。
    """
    raw = load_yaml(path)
    if not isinstance(raw, dict):
        raise MigrationError(f"{path} がマッピングになっていない（実際の型: {type(raw).__name__}）")
    grouped: dict[str, dict[str, int]] = {}
    for flat_key, value in raw.items():
        if ":" not in flat_key:
            raise MigrationError(
                f"{path} のキーの形が不正（'<宣言ファイル名>:<エントリ名>[.<内訳キー>]' の形でない）: {flat_key!r}"
            )
        filename, _, rest = flat_key.partition(":")
        grouped.setdefault(filename, {})[rest] = value
    return grouped


def declared_overlay_keys(entries: dict) -> set[str]:
    """`entries`（宣言 YAML を読んだままの「フラットな名前 -> スペック」の
    dict、`apply_count_overlay()` の第1引数と同じ形。`source_regions.yaml`
    なら `raw["sources"]` を渡す）から、`apply_count_overlay()` が受け付ける
    有効なオーバーレイキー（`"名前"` または `"名前.内訳キー"`）の集合を計算する。

    判定条件は `apply_count_overlay()` 自身が使っているのと同じもの
    （`expected_row_count`/`expected_count` の有無で `"名前"` が、`breakdown`
    の有無で `"名前.内訳キー"` が有効になる）をそのまま踏襲するだけで、
    別の判断基準を持ち込まない——`scripts/tests/test_sample_coverage.py` が
    `data/sample/declaration_counts.yaml` のキー集合を7つの宣言ファイルそれぞれと
    突き合わせるのに使う。以前はこの7ファイル分を手で書き写した
    `_flat_keys_for_*` をテスト側が個別に持っており、正本にキーの種類が
    増えても追従し忘れる余地があった（code-review 指摘対応）。
    """
    keys: set[str] = set()
    for name, spec in entries.items():
        if not isinstance(spec, dict):
            continue
        if "expected_row_count" in spec or "expected_count" in spec:
            keys.add(name)
        breakdown = spec.get("breakdown")
        if isinstance(breakdown, dict):
            keys.update(f"{name}.{subkey}" for subkey in breakdown)
    return keys


def resolve_count_overlay(count_overlay_path, filename: str) -> dict[str, int] | None:
    """`--count-overlay` CLI 引数（None なら「使わない」——本番の既定運用）から、
    `filename`（例 `"period_exceptions.yaml"`）分の上書きだけを取り出す。

    `count_overlay_path` が None なら `load_count_overlay_file()` 自体を呼ばず
    `None` を返す（サンプル用のファイルを本番実行で探しにいかない）。呼び出し側
    （各 b0x スクリプトの `main()`）はこの戻り値をそのまま各 `load_*` 関数の
    `count_overlay=` に渡す。
    """
    if count_overlay_path is None:
        return None
    grouped = load_count_overlay_file(count_overlay_path)
    return grouped.get(filename, {})


def resolve_count_overlays(
    count_overlay_path, filenames: tuple[str, ...],
) -> dict[str, dict[str, int] | None]:
    """`resolve_count_overlay()` の複数ファイル版。1本のスクリプトが複数の
    宣言ファイルを読む（`scripts/b03_build_observation.py`:
    `period_exceptions.yaml`/`time_label_conventions.yaml`/`source_regions.yaml`、
    `scripts/b06_build_occurrence.py`: `source_regions.yaml`/
    `occurrence_period_shapes.yaml`）ときに使う。`filenames` それぞれについて
    `resolve_count_overlay()` を呼んだのと同じ結果を、`load_count_overlay_file()`
    は1回だけ呼んで返す。

    以前は b03/b06 がここと同じロジック（`load_count_overlay_file` を
    `--count-overlay` があるときだけ呼び、無ければ `None`）をそれぞれ
    独自にインライン実装しており、b07/b08/b09 の `resolve_count_overlay()`
    と流儀が分かれていた（code-review 指摘対応）。
    """
    if count_overlay_path is None:
        return {name: None for name in filenames}
    grouped = load_count_overlay_file(count_overlay_path)
    return {name: grouped.get(name, {}) for name in filenames}


def load_period_exceptions(
    path=DEFAULT_EXCEPTIONS_YAML, count_overlay: dict[str, int] | None = None,
) -> dict[str, PeriodException]:
    """例外表を読む。空（`{}`）でもよい——その場合は一切の食い違いを許さない。

    `count_overlay`（既定 None）を渡すと、`apply_count_overlay()` で
    `expected_row_count` だけを差し替えてから読む（Issue #29「縮小サンプル」。
    `--count-overlay` を渡さない本番の実行では常に None のまま——挙動は
    1ビットも変わらない）。
    """
    raw = _load_raw(path)
    if count_overlay:
        raw = apply_count_overlay(raw, count_overlay)
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


def required_keys_problems(
    entries: dict, required_keys: tuple[str, ...], label_prefix: str = ""
) -> list[str]:
    """`entries`（`{名前: {...}, ...}` という、既に読み込んだ生の YAML dict）の
    各エントリが `required_keys` をすべて持つことを検証し、問題があれば理由の
    文字列のリストを返す（無ければ空リスト）。

    「宣言 YAML の各エントリが必須キーを持つか」という同じ形の検証を
    `period_exceptions.yaml`/`time_label_conventions.yaml`（このモジュール、
    `source_id -> エントリ` の1階層）と `source_regions.yaml`
    （`scripts/migrate/source_regions.py`、`sources:`/`regions:` の2階層）が
    別々に持っていたのを、**生の dict を受け取る部分**として1つに集約した
    （/simplify 指摘6）。ファイルを読む部分（`_validate_shape`）とは責務を分けて
    ある——呼び出し側がどの階層のどの辞書を渡すか決められるようにするため。
    `label_prefix` はエラーメッセージの接頭辞（`source_regions.py` が
    `"sources."`/`"regions."` を渡す。`period_exceptions.yaml` 等は不要なので
    既定の空文字のまま）。
    """
    problems: list[str] = []
    for name, spec in entries.items():
        label = f"{label_prefix}{name}"
        if not isinstance(spec, dict):
            problems.append(f"{label}: エントリがマッピングになっていない（実際の型: {type(spec).__name__}）")
            continue
        missing = [k for k in required_keys if spec.get(k) in (None, "")]
        if missing:
            problems.append(f"{label}: 必須キーが欠けている（または空）: {missing}")
    return problems


def entries_with_required_keys(entries: dict, required_keys: tuple[str, ...]) -> dict:
    """`entries` のうち、`required_keys` をすべて持つ（かつ値が dict である）
    ものだけを返す。`required_keys_problems()` が既に報告した壊れたエントリを、
    後続の追加検証（型・形式チェック等）が二重に触らないようにするための
    フィルタ（`scripts/migrate/source_regions.py` が `sources`/`regions` の
    それぞれで使う）。
    """
    return {
        name: spec
        for name, spec in entries.items()
        if isinstance(spec, dict) and all(spec.get(k) not in (None, "") for k in required_keys)
    }


def non_negative_int_problem(label: str, value) -> str | None:
    """`value` が非負整数であることを検証する。問題が無ければ `None`、あれば
    `"{label} が整数でない/負の数（実際: ...）"` の理由文字列を返す（`bool` は
    `int` のサブクラスだが整数として扱わない）。`label` は呼び出し側が
    メッセージに出したいフィールドの表示名をそのまま渡す。

    `validate_expected_row_count()`（下記）と
    `scripts/b08_project_occurrence_v1.py` の宣言値検証（`expected_count`・
    `breakdown` の各値）が共有する下請け（/simplify 指摘4: 後者は以前
    「整数でない」だけを見て「負の数」を検査していなかった）。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{label} が整数でない（実際: {value!r}）"
    if value < 0:
        return f"{label} が負の数（実際: {value!r}）"
    return None


def validate_expected_row_count(label: str, spec: dict) -> str | None:
    """`spec["expected_row_count"]` が「非負整数」であることを検証する。問題が
    無ければ `None`、あれば理由の文字列を返す（`.get()` で黙って検査を外さない。
    `scripts/migrate/occurrence_period.py`・`scripts/migrate/source_regions.py`
    が同じ検証を別々に持っていたのを統合した。/simplify 指摘5）。
    """
    return non_negative_int_problem(f"{label}: expected_row_count", spec.get("expected_row_count"))


def assert_declared_names_match(raw: dict, expected_names, path) -> None:
    """宣言 YAML のトップレベルキー集合（`raw`）が `expected_names` と過不足
    なく一致することを確認する。食い違えば `MigrationError`（`path` を
    メッセージに含める）。`scripts/b07_build_occurrence_cube.py`・
    `scripts/b08_project_occurrence_v1.py`・
    `scripts/b09_build_occurrence_place.py` が同じ約10行を別々に持っていたのを
    1箇所に集約した（/simplify 指摘3）。
    """
    declared_names = frozenset(raw)
    expected_names = frozenset(expected_names)
    if declared_names != expected_names:
        raise MigrationError(
            f"{path} の宣言名が想定と一致しない（期待: {sorted(expected_names)}、"
            f"実際: {sorted(declared_names)}）"
        )


def _validate_shape(path, required_keys: tuple[str, ...]) -> None:
    """宣言 YAML（`source_id -> エントリ`の形）の各エントリが `required_keys` を
    すべて持つことを検証する（原本DBを一切必要としない構造検証。CI 用。B-3:
    `validate_period_exceptions_shape`/`validate_time_label_conventions_shape`
    が持っていた同型の検証ループを1つに集約したもの——違いは呼び出し側が渡す
    `required_keys` だけ）。1つでも欠けていれば、どのエントリの何が足りないかを
    まとめて示して `MigrationError` で止まる。

    「パスを読む」部分と「生の dict の必須キーを検査する」部分を分けてある
    （/simplify 指摘6）——後者は `required_keys_problems()`。
    """
    raw = _load_raw(path)
    problems = required_keys_problems(raw, required_keys)
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
    count_overlay: dict[str, int] | None = None,
) -> dict[str, TimeLabelConvention]:
    """`time_label_conventions.yaml` を読む。空（`{}`）でもよい——その場合は
    `value_grain='hour'` の行に一切出会えない（出会えば
    `UnknownTimeLabelConventionError`）。

    `count_overlay` は `load_period_exceptions()` と同じ（Issue #29）。
    """
    raw = _load_raw(path)
    if count_overlay:
        raw = apply_count_overlay(raw, count_overlay)
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


def declaration_problems(usage: _EntryUsage, yaml_label: str) -> list[str]:
    """`usage`（`EntryUsage`）の「1件も該当しなかったエントリ」「実測件数が
    `expected_row_count` と食い違うエントリ」を問題メッセージのリストにする。

    `scripts/b03_build_observation.py`（`period_exceptions.yaml`/
    `time_label_conventions.yaml`）と `scripts/b06_build_occurrence.py`
    （`source_regions.yaml`/`occurrence_period_shapes.yaml`）が同一の関数を
    それぞれ持っていたのを、`EntryUsage` の隣（このモジュール）に1つだけ
    置くように統合した（/simplify 指摘4）。`yaml_label` はメッセージに出す
    宣言表の表示名。
    """
    problems: list[str] = []
    unused = usage.unused_entries()
    if unused:
        problems.append(f"{yaml_label} に宣言されているが1件も該当しなかったエントリ: {unused}")
    mismatched = usage.mismatched_expected_counts()
    if mismatched:
        problems.append(
            f"{yaml_label} の expected_row_count と実測件数が食い違う: "
            f"{mismatched}（宣言 (expected, actual) の順）"
        )
    return problems


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

# `_EntryUsage` は「`source_id`（や任意のキー文字列）->宣言」の使用状況を追跡する
# 汎用トラッカーで、measurements/sensor_timeseries 固有ではない。occurrence の縦線
# （scripts/migrate/source_regions.py・scripts/migrate/occurrence_period.py）も同じ
# 形の宣言表（出典→region、期間の形→期待件数）を持つため、同じ実装をここから公開名
# で再利用する（B-3 と同じ判断: 同じ形のトラッカーを2つ目書かない）。measurements 用の
# 2エイリアス（`PeriodExceptionUsage`/`TimeLabelConventionUsage`）は呼び出し側の型名を
# 変えないためにそのまま残す。
EntryUsage = _EntryUsage


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


# 公開名（B-3・EntryUsage と同じ判断）。`scripts/migrate/occurrence_period.py` の
# 'year'/'month' 形（区間の両端の計算を含む）が同じ規則を要るため、ここから
# 再利用する（二重実装を避ける）。measurements 側の呼び出し（`_bounds_for_grain`
# 等）は引き続き private 名 `_year_bounds`/`_month_bounds` を直接使い、
# 挙動は一切変えない。
year_bounds = _year_bounds
month_bounds = _month_bounds


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


def _parse_utc_offset(utc_offset: str) -> datetime.timedelta:
    """`'+09:00'`/`'-05:30'` のような表記を `timedelta` にする。時刻帯の扱いを
    1か所にまとめる（ADR-0024。/simplify 指摘2。旧 `occurrence_period.py`
    private 実装をここへ移設——`scripts/migrate/occurrence_period.py` から
    公開名 `parse_utc_offset` で再利用する）。呼び出し側
    （`scripts/migrate/source_regions.py` の `load_source_regions()`）が
    `^[+-][0-9]{2}:[0-9]{2}$` で検証済みの値を渡す前提で、ここでは二重に
    検証しない。
    """
    sign = 1 if utc_offset[0] == "+" else -1
    hh, mm = utc_offset[1:].split(":")
    return sign * datetime.timedelta(hours=int(hh), minutes=int(mm))


parse_utc_offset = _parse_utc_offset


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
