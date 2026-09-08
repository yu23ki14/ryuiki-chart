"""検閲値のマッピング（ADR-0009 の決定・オーナー方針変更後の表のとおり）。

`measurements.value_raw` の表記から `censoring` / `censoring_limit` を決める、
ちょうど5分岐:

| value_raw の形          | censoring       | censoring_limit         |
|--------------------------|-----------------|--------------------------|
| `<...`（ASCII）          | `below_lod`     | `<` を除いた数値部分     |
| `ND`                     | `not_detected`  | `NULL`                   |
| `>...`                   | `above_lod`     | `>` を除いた数値部分     |
| `...未満`（日本語）      | `below_lod`     | `未満` を除いた数値部分  |
| それ以外                  | `none`          | `NULL`                   |

`◯未満` を `unknown` にしていた過去の実装（design.md D2）は、ADR-0009 決定3
（**意味が不明**な `detection_flag` コードを推測でマッピングしない）を誤って
`◯未満` にまで広げていた、というオーナーの指摘により撤回した。`◯未満` は
`detection_flag` のような出典コードではなく、`<` と同じ「定量下限未満」を
日本語で書いただけの、**意味が読める**表記である。意味が読める行を
`unknown`（＝「不明」）と書くのは ADR-0009 決定3の趣旨（意味が確定しない
ものだけを unknown にする）から外れる。そのため `<` と同じ `below_lod` に
写し、`censoring_limit` も同じ規則（表記の数値部分を写す。D1: 値を作り直さない）
で埋める。

`CENSORING_UNKNOWN` 自体は ADR-0009 決定3の語彙として残す（`detection_flag`
の意味不明コード '10'/'20'/'30' 等を、確認が済むまで退避する先として、
将来ここに写す想定）。**この変更の結果、このモジュールが実データに対して
`unknown` を返すことは無くなる**（実測: `below_lod` になった12行を含め、
`unknown` は0件になる）。
"""
from __future__ import annotations

CENSORING_NONE = "none"
CENSORING_BELOW_LOD = "below_lod"
CENSORING_NOT_DETECTED = "not_detected"
CENSORING_ABOVE_LOD = "above_lod"
CENSORING_UNKNOWN = "unknown"

ALL_CENSORING_VALUES = (
    CENSORING_NONE,
    CENSORING_BELOW_LOD,
    CENSORING_NOT_DETECTED,
    CENSORING_ABOVE_LOD,
    CENSORING_UNKNOWN,
)

# `imputation='zero'` が 0.0 を代入してよいのはこの2つだけ（ADR-0009 決定2・
# design.md D2）。`above_lod` に 0 を入れない理由: 0 は上限ではない
# （`<0.5` の 0.5 と違い、`>3.2` の 3.2 は「これより大きい」という下限情報であり、
# 0 を代入すると値の意味が逆転する）。`unknown` に入れない理由: 限界が
# 分からないものを推測しない（ADR-0009 決定3 と同じ原則）。
#
# **この定数がこの規則の唯一の定義。** 実際に 0 を代入する処理はここには無い
# ——`scripts/b04_build_cube.py` が `_ZERO_IMPUTED_IN_CLAUSE`（この定数から
# 組み立てる）を使った SQL の `CASE WHEN censoring IN (...) THEN 0.0 ELSE
# value_num END` で行う（レビュー指摘: 以前はここに `apply_zero_imputation`
# という「仕様の Python 版」があり、専用のテストがそれ自身を確認するだけで、
# キューブに実際に入る値の正しさは1ミリも保証していなかった。b04 の SQL が
# 正しく 0 を代入していること自体は
# `scripts/tests/test_b04_build_cube.py::test_zero_imputation_includes_below_lod_and_excludes_above_lod`
# がキューブ経由（`observation_agg` を実際に読む）で確認する——こちらが本物のテスト）。
ZERO_IMPUTED_CENSORING = (CENSORING_BELOW_LOD, CENSORING_NOT_DETECTED)


def classify_censoring(value_raw: str | None) -> tuple[str, float | None]:
    """`(censoring, censoring_limit)` を返す。

    `value_raw` が `None` の場合（実データでは0件。フィクスチャの防御的な
    分岐として扱う）は `none` にする（4つの検閲パターンのどれにも該当しない
    という扱いと同じ）。
    """
    if value_raw is None:
        return CENSORING_NONE, None
    s = value_raw.strip()
    if s.startswith("<"):
        return CENSORING_BELOW_LOD, _parse_limit(s[1:], value_raw)
    if s == "ND":
        return CENSORING_NOT_DETECTED, None
    if s.startswith(">"):
        return CENSORING_ABOVE_LOD, _parse_limit(s[1:], value_raw)
    if s.endswith("未満"):
        return CENSORING_BELOW_LOD, _parse_limit(s[: -len("未満")], value_raw)
    return CENSORING_NONE, None


def _parse_limit(number_part: str, original: str) -> float:
    """`<0.5` の `0.5`、`1未満` の `1` のように、表記の数値部分だけを写す
    （ADR-0009 の定義どおり。D1: value_raw から値を作り直すのではなく、
    検閲の記号・接尾辞を取り除くだけ）。
    """
    try:
        return float(number_part)
    except ValueError as e:
        raise ValueError(
            f"censoring_limit の数値部分が解析できない: value_raw={original!r}"
            "（'<'/'>' の直後、または '未満' の直前が数値であることを前提にしている。"
            "実データで確認済みの形と違うので、推測せず止める）"
        ) from e


def resolve_value_num(censoring: str, raw_value):
    """`observation.value_num` を決める（design.md D2）。

    `censoring='none'` のときだけ `measurements.value` を運ぶ（D1: value_raw
    から値を作り直さない。パースに失敗して既に NULL の行はそのまま NULL で運ぶ
    ＝ v1 のバグを記録として温存する）。それ以外（検閲されている）は常に NULL
    にする（ADR-0009 決定1: 検閲行の value_num に 0 を入れない）。

    v1 の格納値（`measurements.value`）は below_lod/not_detected では実質
    常に 0.0、above_lod/unknown では実質常に NULL になっている（ADR-0009 背景の
    実測）が、ここでは v1 側のその偶然の値を信用せず、`censoring` の分岐だけで
    決める。
    """
    return raw_value if censoring == CENSORING_NONE else None
