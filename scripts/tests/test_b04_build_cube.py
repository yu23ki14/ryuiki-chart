"""scripts/b04_build_cube.py の統合テスト（小さな自作 observation フィクスチャ）。

`observation` の列は `scripts/b03_build_observation.py` の
`_CREATE_OBSERVATION_SQL` をそのまま使う（スキーマの正を1箇所に保つ）。
"""
import sqlite3

import pytest
import yaml

import b03_build_observation as b03
import b04_build_cube as b04
from migrate import common, cube_invariants

from .migrate_fixtures import DEFAULT_ALIASES, make_registry_db, make_v2_db_with_observation, table_content_hash

# b04 は AVG()/SUM() を使うため `common.require_sqlite_version()` で古い
# SQLite を拒む（`scripts/migrate/common.py` 参照）。この版のガード自体の
# 単体テストは `scripts/tests/test_migrate_common.py`。ここでは環境の SQLite
# が実際に古いとき、意味の無い失敗の山を作らずスキップする。
pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)


def _row(
    source_table, source_row_id, period_start, period_end, value_num, value_raw, censoring,
    variable_id="common:variable:water.bod", obs_stat=None, unit_id="common:unit:mg_per_l",
    censoring_limit=None, value_grain="day", period_grain="day", period_raw=None,
):
    # unit_raw: `unit_id` が付いているときだけ実測の生表記（"mg/L"）を持たせる。
    # `unit_id=None` のケース（大半の一般テスト）は `unit_raw` も None にしておかないと、
    # Issue #48 PR-1 §4（`make_registry_db()` に既定で `unit` 表を持たせた後）で
    # `_assert_unit_evidence()` の検証2（`unit_id IS NULL AND unit_raw IS NOT NULL`
    # の未宣言の欠落。宣言 YAML は本物の
    # `scripts/migrate/unit_evidence_declarations.yaml` を見る）に、この項目とは
    # 無関係な行まで引っかかってしまう。単位の証拠検査を明示的にテストする節
    # （後方の `_assert_unit_evidence` 専用テスト）は `unit_raw` を自分で
    # `UPDATE` して上書きするので、ここの既定には影響されない。
    unit_raw = "mg/L" if unit_id is not None else None
    return (
        source_table, source_row_id, "jp-14", "place_s1", "site", variable_id, obs_stat,
        unit_id, unit_raw, value_grain, period_grain, period_start, period_end,
        period_raw if period_raw is not None else period_start, value_num, value_raw, censoring, censoring_limit,
        "公開済", 0, "ref", "ev1",
    )


def _registry_db(tmp_path):
    """`variable.default_stat` を持つ最小のレジストリ DB を作る（b04 が
    ATTACH する）。既定フィクスチャ（`weather.precipitation` が `default_stat=
    'sum'`）をそのまま使う。
    """
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(registry_db)
    return registry_db


def _write_declarations(tmp_path, declared, name="unit_evidence_declarations.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"declared": declared}, allow_unicode=True), encoding="utf-8")
    return path


def test_zero_and_lod_series_per_censoring_branch(tmp_path):
    """ADR-0009 決定4: `value_zero`/`value_lod` を4つの検閲区分（none/below_lod/
    not_detected/above_lod）それぞれについて格ごとに確認する（設計ブリーフ
    検証7の実測）。

    - `none`（2.0）: 両系列とも 2.0（代入の余地が無い）。
    - `below_lod`（<0.5）: value_zero=0.0・value_lod=0.5（censoring_limit）。
    - `not_detected`（ND）: value_zero も value_lod も NULL（どちらの系列でも代入せず
      平均・MIN/MAX から除外する）。
      セルのメンバーとして n/n_not_detected には数える。
    - `above_lod`（>9.0）: value_num が NULL（D2）のまま、どちらの系列でも
      代入されないので、メンバー条件（`_MEMBER_SQL`: `v_zero IS NOT NULL` の行と
      値を持たない ND の行）に入らず日次セル自体ができない（非メンバー。ADR-0009 決定4-C）。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", None, "<0.5", "below_lod", censoring_limit=0.5),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", None, "ND", "not_detected"),
        _row("measurements", "m4", "2020-01-04", "2020-01-04", None, ">9.0", "above_lod", censoring_limit=9.0),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        day_rows = conn.execute(
            "SELECT period_start, value_zero, value_lod, n, n_censored, n_not_detected FROM observation_agg "
            "WHERE grain='day' AND stat='mean' ORDER BY period_start"
        ).fetchall()
        assert stats["n_day"] == 9  # mean/min/max の3行 × 3日（above_lodの日は無い）
        assert ("2020-01-01", 2.0, 2.0, 1, 0, 0) in day_rows
        assert ("2020-01-02", 0.0, 0.5, 1, 1, 0) in day_rows
        assert ("2020-01-03", None, None, 1, 0, 1) in day_rows
        assert all(r[0] != "2020-01-04" for r in day_rows)
        # 検証1: value_zero/value_lod が NULL になるのは 2020-01-03（n_not_detected=n=1）
        # の日次セルだけ（`day_rows` は stat='mean' に絞っているので1行）。
        null_rows = [r for r in day_rows if r[2] is None]
        assert all((r[1] is None) == (r[2] is None) for r in day_rows)
        assert {r[0] for r in null_rows} == {"2020-01-03"}
        assert len(null_rows) == 1
    finally:
        conn.close()


def test_value_lod_report_counts(tmp_path):
    """`build_cube()` が返すレポート件数（`n_value_lod_differs`/
    `n_value_lod_null`。設計ブリーフ 検証4）を、月・年のロールアップに
    巻き込まれない出典配布セル（`period_grain='fiscal_year'`）だけの小さな
    フィクスチャで検証する（day セルは月・年へロールアップされるため、
    件数の手計算が煩雑になる。ここでは意図的にそれを避け、系列（variable_id）
    を分けて互いにロールアップで混ざらないようにする）。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-04-01", "2021-03-31", 2.0, "2.0", "none",
            variable_id="common:variable:water.bod", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
        _row(
            "measurements", "m2", "2020-04-01", "2021-03-31", None, "<0.5", "below_lod", censoring_limit=0.5,
            variable_id="common:variable:water.cod", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
        _row(
            "measurements", "m3", "2020-04-01", "2021-03-31", None, "ND", "not_detected",
            variable_id="common:variable:water.ph", value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        # 各系列は独立（variable_id が違う）なので互いにロールアップで混ざらない。
        # stat ∈ {mean, min, max} の3行 × 3系列 = 9行。
        assert stats["n_year_source"] == 9
        # none（m1）は3行とも差なし。below_lod（m2）は3行（mean/min/max）とも
        # 差あり。not_detected（m3）は3行とも value_zero/value_lod が NULL——`!=` は
        # NULL を含む比較を「異なる」として数えない（SQL の3値論理）ので
        # n_value_lod_differs には入らず、n_value_lod_null 側だけに数えられる
        # （設計ブリーフ 検証4「重なり0」）。
        assert stats["n_value_lod_differs"] == 3  # below_lod の3行のみ
        assert stats["n_value_lod_null"] == 3  # not_detected の3行
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /code-review 指摘1・指摘2: 検証1・検証3が「葉の格」と「積み上げの格」を
# 区別しない・「値は非負」を仮定していたバグの回帰テスト。
#
# ここに挙げる3つの fixture（指摘1: 「ND2行の日」＋「有値1行の日」・
# 「ND1行の日」＋「ND2行の日」、指摘2: 負の実測値＋ND）は、いずれも
# 修正前の実装（検証1: 葉・積み上げを区別せず (value_lod IS NULL) =
# (n_not_detected = n) を課す。検証3: n_not_detected の値によらず両方
# 非NULLなら value_lod >= value_zero を課す）に対して実行すると
# `common.MigrationError` で止まっていたことを、このタスク中に実際に
# 確認した（`_CHECK1_VIOLATION_SQL`/`_CHECK3_VIOLATION_SQL` を手元で
# 一時的に修正前の式へ差し替えて3つとも再実行し、それぞれ例外が起きる
# ことを確認済み）。修正後の実装ではどれも例外を投げずに通ることを、
# ここで実測として固定する。
# ---------------------------------------------------------------------------

def test_month_rollup_allows_all_nd_day_mixed_with_valid_day(tmp_path):
    """/code-review 指摘1（1つ目の形）: 同じ月に「ND 2行の日」と「有値1行の日」
    が混じると、月セルの n（日次セルの個数=2）と n_not_detected（ND 観測の
    個数の和=2）がたまたま一致するが、value_lod は NULL ではない
    （AVG(NULL, 5.0)=5.0）。旧検証1（単位を混ぜた等式）はこれを
    「value_lod IS NULL と n_not_detected=n が食い違う」と誤検出していた。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", None, "ND", "not_detected"),
        _row("measurements", "m2", "2020-01-01", "2020-01-01", None, "ND", "not_detected"),
        _row("measurements", "m3", "2020-01-02", "2020-01-02", 5.0, "5.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)  # 例外を投げなければ良い
        month_row = conn.execute(
            "SELECT value_zero, value_lod, n, n_not_detected FROM observation_agg "
            "WHERE grain='month' AND stat='mean'"
        ).fetchone()
        # 日次セル: 01-01(n=2,n_not_detected=2,value_zero=NULL,value_lod=NULL) /
        # 01-02(n=1,n_not_detected=0,value_zero=5.0,value_lod=5.0)。
        # 月セル: n=2（日次セルの個数）, n_not_detected=2（0+2）,
        # value_zero=AVG(NULL,5.0)=5.0, value_lod=AVG(NULL,5.0)=5.0
        # （Issue #61: ND の日は value_zero でも平均に入らない。以前は 2.5）。
        assert month_row == (5.0, 5.0, 2, 2)
    finally:
        conn.close()


def test_month_rollup_allows_two_all_nd_days(tmp_path):
    """/code-review 指摘1（2つ目の形）: 同じ月に「ND 1行の日」と「ND 2行の日」
    （どちらも100% ND）が混じると、月セルは n=2（日次セルの個数）・
    n_not_detected=3（1+2）で一致しないが、value_lod は正しく NULL
    （全部NDの日だけで構成される月）。旧検証1はこれも
    「n_not_detected=n が食い違う」として誤検出していた。
    """
    rows = [
        _row("measurements", "m1", "2020-02-01", "2020-02-01", None, "ND", "not_detected"),
        _row("measurements", "m2", "2020-02-02", "2020-02-02", None, "ND", "not_detected"),
        _row("measurements", "m3", "2020-02-02", "2020-02-02", None, "ND", "not_detected"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)  # 例外を投げなければ良い
        month_row = conn.execute(
            "SELECT value_zero, value_lod, n, n_not_detected FROM observation_agg "
            "WHERE grain='month' AND stat='mean'"
        ).fetchone()
        assert month_row == (None, None, 2, 3)
    finally:
        conn.close()


def test_negative_values_with_not_detected_keep_both_series_equal(tmp_path):
    """/code-review 指摘2 の後継（Issue #61）: 実測値が負の変数（河川水位等）で
    not_detected が混じっても、ND は両系列で除外されるので value_zero と
    value_lod は一致し（[-10.0, ND] はどちらも -10.0）、不等式の逆転は起きない。
    以前（value_zero が ND を 0 として平均に入れていた頃）は zero側 -5.0 >
    lod側 -10.0 と逆転していたので、検証3を `n_not_detected = 0` に限っていた。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", -10.0, "-10.0", "none"),
        _row("measurements", "m2", "2020-01-01", "2020-01-01", None, "ND", "not_detected"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)  # 例外を投げなければ良い
        day_rows = conn.execute(
            "SELECT stat, value_zero, value_lod, n, n_not_detected FROM observation_agg "
            "WHERE grain='day' ORDER BY stat"
        ).fetchall()
        # mean/min/max のどれも ND（n=2 のうち 1）を除いた -10.0。
        assert day_rows == [
            ("max", -10.0, -10.0, 2, 1), ("mean", -10.0, -10.0, 2, 1), ("min", -10.0, -10.0, 2, 1),
        ]
    finally:
        conn.close()


def test_value_zero_excludes_not_detected_from_mean_min_max_and_sum(tmp_path):
    """Issue #61: ND を含むセルで value_zero が ND を平均・MIN・MAX・SUM から除外する
    （以前は ND を 0 として含めていた）。below_lod は value_zero で 0 のまま。
    day の mean/min/max と年次の積み上げで確認する。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 4.0, "4.0", "none"),
        _row("measurements", "m2", "2020-01-01", "2020-01-01", None, "ND", "not_detected"),
        _row("measurements", "m3", "2020-01-01", "2020-01-01", None, "<0.5", "below_lod", censoring_limit=0.5),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        day = {
            r[0]: r[1:]
            for r in conn.execute(
                "SELECT stat, value_zero, value_lod, n, n_censored, n_not_detected FROM observation_agg "
                "WHERE grain='day'"
            )
        }
        # zero 側の構成は [4.0, 0.0]（ND 除外・below_lod=0）、lod 側は [4.0, 0.5]。
        assert day["mean"] == (2.0, 2.25, 3, 1, 1)
        assert day["min"] == (0.0, 0.5, 3, 1, 1)
        assert day["max"] == (4.0, 4.0, 3, 1, 1)
        year = conn.execute(
            "SELECT value_zero, value_lod FROM observation_agg WHERE grain='year' AND stat='mean'"
        ).fetchone()
        assert year == (2.0, 2.25)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /code-review 指摘4: 新しい3つの機械検証それぞれに「わざと壊すと止まる」
# ネガティブテスト（既存の一意性検証にはあったが、value_zero/value_lod の
# 3検証には無かった——述語のタイポで空回りしても pytest は全部緑のまま
# だった）。`_assert_dimension_key_unique_raises_with_examples` と同じ流儀
# （手作りの staging テーブルに直接壊れた行を入れ、検証関数を直接呼ぶ）。
# ---------------------------------------------------------------------------

_STAGING_DIM = (
    "jp-14", "place_s1", "site", "common:variable:water.bod", None, "common:unit:mg_per_l",
    "day", "2020-01-01", "2020-01-01", "day", "day", "mean",
)


def _make_staging_with_rows(conn, rows):
    """`_CREATE_OBSERVATION_AGG_SQL` と同じ形の `staging` テーブルを作り、
    `rows`（各要素が `DIM_COLUMNS` + value_zero/value_lod/n/n_censored/
    n_not_detected/n_places/built_from/spec_version の並び）を入れる
    （/simplify 指摘10: `test_assert_dimension_key_unique_raises_with_examples`
    と3つのネガティブテストが同じ処理をそれぞれ別に書いていたので、複数行を
    入れられる形に一般化して両方から使う）。
    """
    conn.execute(b04._CREATE_OBSERVATION_AGG_SQL.format(table='"staging"'))
    cols = ", ".join(
        b04.DIM_COLUMNS
        + ["value_zero", "value_lod", "n", "n_censored", "n_not_detected", "n_places", "built_from", "spec_version"]
    )
    placeholders = ", ".join("?" for _ in rows[0])
    conn.executemany(f'INSERT INTO "staging" ({cols}) VALUES ({placeholders})', rows)
    conn.commit()


@pytest.mark.parametrize(
    "row, match",
    [
        pytest.param(
            (*_STAGING_DIM, 1.0, None, 1, 0, 0, 1, "bf", "sv"),
            "value_lod IS NULL の条件が崩れている",
            id="check1_leaf_unit_mismatch",
        ),
        pytest.param(
            (*_STAGING_DIM, None, 1.0, 1, 1, 0, 1, "bf", "sv"),
            "NULL 性が食い違う",
            id="null_match_between_series",
        ),
        pytest.param(
            (*_STAGING_DIM, 1.0, 2.0, 1, 0, 0, 1, "bf", "sv"),
            "ビット一致しない",
            id="check2_bit_mismatch",
        ),
        pytest.param(
            (*_STAGING_DIM, 5.0, 3.0, 1, 1, 0, 1, "bf", "sv"),
            "value_lod が value_zero を下回る",
            id="check3_inequality_violation",
        ),
    ],
)
def test_assert_value_zero_lod_invariants_raises_when_deliberately_broken(tmp_path, row, match):
    """検証1/2/3それぞれをわざと壊すと `MigrationError` になる（/code-review
    指摘4: 既存の一意性検証にはあったが value_zero/value_lod の3検証には
    無かった——述語のタイポで空回りしても pytest は全部緑のままだった。
    /simplify 指摘8: 値と期待メッセージ以外まったく同じ形の3本を、
    `test_r01_registry_atomic.py` にある先例と同じく `parametrize` で
    1本にまとめた）。

    - check1: 葉の格（grain='day'=input_grain）で value_lod が NULL なのに
      n_not_detected（0）が n（1）と一致しない。
    - check2: below_lod の無いセル（n_censored=0）なのに
      value_zero と value_lod が異なる。
    - check3: value_lod が value_zero を下回る。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    _make_staging_with_rows(conn, [row])
    try:
        with pytest.raises(common.MigrationError, match=match):
            b04._assert_value_zero_lod_invariants(conn, "staging")
    finally:
        conn.close()


def test_day_cell_has_mean_min_max_for_every_variable(tmp_path):
    """T4-2: 日次セルは全変数で stat ∈ {mean, min, max} を必ず持つ。"""
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("measurements", "m2", "2020-01-01", "2020-01-01", 3.0, "3.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        got = dict(
            conn.execute(
                "SELECT stat, value_zero FROM observation_agg WHERE grain='day' ORDER BY stat"
            ).fetchall()
        )
        assert got == {"max": 3.0, "mean": 2.0, "min": 1.0}
    finally:
        conn.close()


def test_day_cell_sum_only_for_default_stat_sum_variables_matching_obs_stat(tmp_path):
    """T4-2: `variable.default_stat='sum'` かつ (`obs_stat IS NULL` または
    `obs_stat='sum'`) の系列だけ `stat='sum'` の日次セルが足される。
    `weather.precipitation`（フィクスチャで default_stat='sum'）で確認する。
    `obs_stat='max_10min'` を宣言する別系列には sum をかけない
    （jma_daily の「最大値」相当。回帰テスト）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01", "2020-01-01", 1.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat=None, unit_id=None,
        ),
        _row(
            "sensor_timeseries", "s2", "2020-01-01", "2020-01-01", 2.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat=None, unit_id=None,
        ),
        # 同じ variable_id でも obs_stat='max_10min' は sum の対象外。
        _row(
            "sensor_timeseries", "s3", "2020-01-01", "2020-01-01", 5.0, None, "none",
            variable_id="common:variable:weather.precipitation", obs_stat="max_10min", unit_id=None,
        ),
        # default_stat が無い変数（water.bod）は obs_stat=NULL でも sum を作らない。
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 9.0, "9.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        sum_rows = conn.execute(
            "SELECT variable_id, obs_stat, value_zero, n FROM observation_agg WHERE grain='day' AND stat='sum'"
        ).fetchall()
        assert sum_rows == [("common:variable:weather.precipitation", None, 3.0, 2)]
    finally:
        conn.close()


def test_hour_and_instant_grain_roll_up_into_day_cell_with_correct_input_grain(tmp_path):
    """T4-1: period_grain IN ('hour','instant') も日次セルに積み上げる。
    日付は substr(period_start,1,10)（区間の始まりの日付）。input_grain は
    その period_grain になる。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01T23:00:00", "2020-01-02T00:00:00", 4.0, None, "none",
            variable_id="common:variable:weather.precipitation", unit_id=None,
            value_grain="hour", period_grain="hour", period_raw="2020-01-02T00:00:00+09:00",
        ),
        _row(
            "sensor_timeseries", "s2", "2020-01-03T12:00:00", "2020-01-03T12:00:00", 6.0, None, "none",
            variable_id="common:variable:water.water_temp", unit_id=None,
            value_grain="instant", period_grain="instant", period_raw="2020-01-03T12:00:00+09:00",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        hour_day = conn.execute(
            "SELECT period_start, period_end, input_grain, value_zero, n FROM observation_agg "
            "WHERE grain='day' AND stat='mean' AND variable_id='common:variable:weather.precipitation'"
        ).fetchall()
        # 区間の始まり（23:00 の日付＝2020-01-01）が日次セルの日になる（正しい日割り）。
        assert hour_day == [("2020-01-01", "2020-01-01", "hour", 4.0, 1)]

        instant_day = conn.execute(
            "SELECT period_start, input_grain, value_zero FROM observation_agg "
            "WHERE grain='day' AND stat='mean' AND variable_id='common:variable:water.water_temp'"
        ).fetchall()
        assert instant_day == [("2020-01-03", "instant", 6.0)]
    finally:
        conn.close()


def test_month_source_cell_is_symmetric_with_year_source_cell(tmp_path):
    """T4-1: period_grain='month'（jma_monthly 相当）は日次セルを経由せず、
    出典配布の月次セルになる（grain=input_grain='month'。年次の出典配布
    セルと対称——mean/min/max の3行になる）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2019-01-01", "2019-01-31", 10.0, None, "none",
            variable_id="common:variable:weather.pressure_station", unit_id="common:unit:hpa",
            value_grain="month", period_grain="month", period_raw="2019-01",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        assert stats["n_month_source"] == 3
        assert stats["n_day"] == 0
        month_rows = conn.execute(
            "SELECT grain, input_grain, stat, value_zero, n FROM observation_agg WHERE grain='month' ORDER BY stat"
        ).fetchall()
        assert month_rows == [
            ("month", "month", "max", 10.0, 1),
            ("month", "month", "mean", 10.0, 1),
            ("month", "month", "min", 10.0, 1),
        ]
    finally:
        conn.close()


def test_year_source_cell_closed_to_year_and_fiscal_year_only(tmp_path):
    """T4-1: 出典配布の年次セルは period_grain IN ('year','fiscal_year') に
    閉じる（毎時・月次の観測を誤って年次として吸い込まない回帰テスト）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2019-01-01", "2019-01-31", 10.0, None, "none",
            variable_id="common:variable:weather.pressure_station", unit_id="common:unit:hpa",
            value_grain="month", period_grain="month", period_raw="2019-01",
        ),
        _row(
            "measurements", "m1", "2020-04-01", "2021-03-31", 4.0, "4.0", "none",
            value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        assert stats["n_month_source"] == 3
        assert stats["n_year_source"] == 3
        year_grains = conn.execute(
            "SELECT DISTINCT grain FROM observation_agg WHERE grain IN ('year','fiscal_year')"
        ).fetchall()
        assert year_grains == [("fiscal_year",)]  # 月次データが年次に混ざっていない
    finally:
        conn.close()


def test_month_and_year_from_day_inherit_input_grain_and_filter_mean(tmp_path):
    """T4-1/T4-3: 月次・年次（日次セルから積み上げる側）は input_grain を
    cube_day から引き継ぎ、かつ stat='mean' の日次セルだけを積み上げる
    （min/max/sum が混ざらない）。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", 3.0, "3.0", "none"),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", 5.0, "5.0", "none"),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        month = conn.execute(
            "SELECT n, value_zero, input_grain FROM observation_agg WHERE grain='month'"
        ).fetchall()
        assert month == [(3, 3.0, "day")]  # n=3（日次セル3個）, avg=(1+3+5)/3=3.0, min/maxは混ざらない

        year_mean = conn.execute(
            "SELECT n, value_zero, input_grain FROM observation_agg WHERE grain='year' AND stat='mean'"
        ).fetchall()
        assert year_mean == [(3, 3.0, "day")]
        year_min = conn.execute(
            "SELECT value_zero FROM observation_agg WHERE grain='year' AND stat='min'"
        ).fetchall()
        year_max = conn.execute(
            "SELECT value_zero FROM observation_agg WHERE grain='year' AND stat='max'"
        ).fetchall()
        assert year_min == [(1.0,)]
        assert year_max == [(5.0,)]
    finally:
        conn.close()


def test_annual_direct_row_bypasses_day_month_cells(tmp_path):
    """出典が直接配った年次値（period_grain <> 'day'）は day/month セルを経由せず
    直接キューブに入り、input_grain がその period_grain になる。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-04-01", "2021-03-31", 4.0, "4.0", "none",
            value_grain="fiscal_year", period_grain="fiscal_year",
        ),
    ]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        stats = b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        assert stats["n_day"] == 0
        assert stats["n_month_from_day"] == 0
        annual = conn.execute(
            "SELECT grain, input_grain, stat, value_zero, n FROM observation_agg ORDER BY stat"
        ).fetchall()
        assert annual == [
            ("fiscal_year", "fiscal_year", "max", 4.0, 1),
            ("fiscal_year", "fiscal_year", "mean", 4.0, 1),
            ("fiscal_year", "fiscal_year", "min", 4.0, 1),
        ]
    finally:
        conn.close()


def test_built_from_containing_apostrophe_does_not_break_sql(tmp_path):
    """`built_from`/`spec_version` はバインドパラメータで渡す。以前は
    `f\"'{built_from}'\"` で SQL に直接埋め込んでいたため、アポストロフィを含む値
    で構文エラーになった。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), built_from="o'brien's build", spec_version="v'1", unit_evidence_declarations_path=None)
        got = conn.execute("SELECT DISTINCT built_from, spec_version FROM observation_agg").fetchall()
        assert got == [("o'brien's build", "v'1")]
    finally:
        conn.close()


def test_dimension_key_uniqueness_is_verified(tmp_path):
    """day/month(day側/出典側)/year(day側/出典側) の5経路が互いに排他である
    ことを一意性チェックが確認する（既存の回帰テストを維持）。1系列だけの
    小さなフィクスチャでは自然に一意になるので、ここでは例外が出ないことだけ
    を確認する。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)  # 例外を投げなければ良い
    finally:
        conn.close()


def test_assert_dimension_key_unique_raises_with_examples(tmp_path):
    """C-3: `_assert_dimension_key_unique`（`CREATE UNIQUE INDEX` を使った
    一意性検証）自体を、重複キーを直接仕込んだ作業用テーブルに対して呼び、
    `sqlite3.IntegrityError` ではなく実例つきの `MigrationError` になる
    ことを確認する（GROUP BY へのフォールバックが機能している証拠）。
    """
    db_path = tmp_path / "t.sqlite"
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    row = (*_STAGING_DIM, 1.0, 1.0, 1, 0, 0, 1, "bf", "sv")
    _make_staging_with_rows(conn, [row, row])
    try:
        with pytest.raises(common.MigrationError, match="次元キーが一意でない"):
            b04._assert_dimension_key_unique(conn, "staging")
    finally:
        conn.close()


def test_a1_uniqueness_failure_preserves_previous_observation_agg(tmp_path, monkeypatch):
    """A-1: 1回目を成功させたあと、2回目を一意性検証の失敗で止める
    （`_assert_dimension_key_unique` をモンキーパッチして強制的に失敗させる
    ——実データで5経路を衝突させるのは難しいため、`staged_table` の
    「検証が全部通ってから差し替える」契約そのものを検証する）。前回の
    observation_agg がそのまま残り、作業用テーブルも残らない。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    before = conn.execute("SELECT * FROM observation_agg ORDER BY stat").fetchall()
    conn.close()

    def boom(conn, staging):
        raise common.MigrationError("テスト用に強制した一意性違反")

    monkeypatch.setattr(b04, "_assert_dimension_key_unique", boom)

    conn2 = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="テスト用に強制した一意性違反"):
            b04.build_cube(conn2, registry_db, unit_evidence_declarations_path=None)

        # `pipeline_fingerprint`（Issue #37 #1、段階間の指紋のメタ表）は本番/
        # 作業用の区別とは無関係な実装詳細なので除外する。
        tables = sorted(
            r[0] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if r[0] != common.PIPELINE_FINGERPRINT_TABLE
        )
        after = conn2.execute("SELECT * FROM observation_agg ORDER BY stat").fetchall()
    finally:
        conn2.close()
    assert tables == ["observation", "observation_agg"], "作業用テーブルが残っている"
    assert after == before, "前回の observation_agg が変わってしまった"


def test_a1_running_twice_successfully_does_not_collide_on_index_name(tmp_path):
    """C-3 の検証用一意インデックスは使い捨て（張った直後に DROP する）。
    固定名の索引を本番テーブルまで残すと2回目の実行が名前衝突で壊れるはず
    ——2回連続で成功することを確認して、そうなっていないことを示す
    （実測で踏んだ回帰）。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    conn.close()

    conn2 = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        stats = b04.build_cube(conn2, registry_db, unit_evidence_declarations_path=None)
    finally:
        conn2.close()
    assert stats["n_total"] > 0


def test_build_cube_calls_the_shared_sqlite_version_guard(tmp_path, monkeypatch):
    """`build_cube()` の先頭で `common.require_sqlite_version()`（b04・b05・b10
    が共有するガード）を呼ぶことを確認する（コードレビュー指摘: 以前はこの
    ガードをモジュール読み込み時点で呼んでいたため、古い SQLite の環境では
    `import b04_build_cube` した瞬間に `SystemExit` が飛び、`pytest` の収集
    自体が止まっていた——守りたい状況でこそ壊れる形だった。関数の先頭に
    移したことで `import` は安全になり、実行時にだけ止まる。
    `-O` での assert 無効化への対処自体は `require_sqlite_version` 側のテスト
    ——`scripts/tests/test_migrate_common.py`
    ::test_require_sqlite_version_raises_systemexit_even_under_dash_o
    ——で確認する）。
    """
    monkeypatch.setattr(common.sqlite3, "sqlite_version_info", (3, 42, 0))
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    try:
        with pytest.raises(SystemExit, match="古すぎる"):
            b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 段階間の指紋（Issue #37 #1。scripts/migrate/common.py 参照）
# ---------------------------------------------------------------------------

def test_build_cube_halts_when_observation_changed_since_b03_recorded_it(tmp_path):
    """**壊れた/古い上流出力で止まることの実測**（Issue #37 受け入れ基準）:
    b04 を1回成功させた後、`observation`（b03 の出力）の内容を b03 を経由せず
    直接書き換える（＝b03 が別内容で再実行されたのに b04 が再実行されて
    いない状態を模す）と、2回目の `build_cube` は集計を始める前に
    `scripts/b03_build_observation.py を再実行すること` と案内する
    `MigrationError` で止まる。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
    b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    conn.close()

    # b03 を経由せず observation の内容を直接書き換える（b03 の再実行を模す）。
    conn2 = sqlite3.connect(f"file:{db_path}", uri=True)
    conn2.execute("UPDATE observation SET value_num = 999.0 WHERE source_row_id = 'm1'")
    conn2.commit()
    conn2.close()

    conn3 = sqlite3.connect(f"file:{db_path}", uri=True)
    try:
        with pytest.raises(common.MigrationError, match="scripts/b03_build_observation.py を再実行すること"):
            b04.build_cube(conn3, registry_db, unit_evidence_declarations_path=None)
    finally:
        conn3.close()


def test_build_cube_halts_when_observation_has_no_recorded_fingerprint(tmp_path):
    """`pipeline_fingerprint` メタ表自体が無い（この機構より前に作られた古い
    v2.sqlite、または b03 を経由せず直接組み立てたフィクスチャ）場合も、
    `observation` を読む前に案内付きの `MigrationError` で止まる。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    db_path = tmp_path / "v2.sqlite"
    registry_db = _registry_db(tmp_path)
    conn = sqlite3.connect(f"file:{db_path}", uri=True)
    conn.execute(b03._CREATE_OBSERVATION_SQL.format(table="observation"))
    conn.executemany(f"INSERT INTO observation VALUES ({', '.join('?' for _ in rows[0])})", rows)
    conn.commit()  # record_stage_fingerprint を呼ばない（指紋を記録しない）
    try:
        with pytest.raises(common.MigrationError, match="scripts/b03_build_observation.py を再実行すること"):
            b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    finally:
        conn.close()


def test_running_twice_yields_identical_observation_agg_content_hash(tmp_path):
    """決定論: 同じ `observation` に対して `build_cube()` を2回実行すると
    `observation_agg` の content_hash がバイト一致する（設計ブリーフ 検証8。
    `scripts/tests/test_b03_build_observation.py::test_running_twice_yields_identical_content_hash`
    と同じ流儀）。値の異なる4区分（none/below_lod/not_detected/above_lod）を
    混ぜたフィクスチャで確認する——`value_zero`/`value_lod` のどちらも
    決定論が崩れていないことの回帰。
    """
    rows = [
        _row("measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none"),
        _row("measurements", "m2", "2020-01-02", "2020-01-02", None, "<0.5", "below_lod", censoring_limit=0.5),
        _row("measurements", "m3", "2020-01-03", "2020-01-03", None, "ND", "not_detected"),
        _row("measurements", "m4", "2020-01-04", "2020-01-04", None, ">9.0", "above_lod", censoring_limit=9.0),
    ]
    registry_db = _registry_db(tmp_path)

    def build(db_name):
        db_path = tmp_path / db_name
        conn = make_v2_db_with_observation(db_path, b03._CREATE_OBSERVATION_SQL, rows)
        try:
            b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
        finally:
            conn.close()
        return db_path

    def fingerprint(path):
        return table_content_hash(path, "observation_agg", b04.DIM_COLUMNS)

    out1 = build("v2_1.sqlite")
    out2 = build("v2_2.sqlite")
    assert fingerprint(out1) == fingerprint(out2)


# ---------------------------------------------------------------------------
# 単位の証拠検査（Issue #48 PR-1b §3.7、D3。`b04._assert_unit_evidence()`）
# ---------------------------------------------------------------------------


def _registry_db_with_unit(tmp_path, units, name="registry.sqlite"):
    """`make_registry_db()` の `unit` 表を、この検査が使う `(unit_id, symbol)` の
    組だけに絞った registry.sqlite を作る（既定の `DEFAULT_UNITS` を使わず、
    テストごとに意図した unit_id だけを持たせる——意図せぬ一致/不一致を防ぐ）。
    """
    registry_db = tmp_path / name
    make_registry_db(registry_db, units=units)
    return registry_db


def _observation_conn_with_attached_registry(tmp_path, rows, registry_db, db_name="v2.sqlite"):
    """`observation` だけを持つ v2.sqlite 相当のフィクスチャを作り、`reg` として
    `registry_db` を ATTACH した接続を返す（`_assert_unit_evidence()` の前提と
    同じ状態。呼び出し側が `close()` すること）。
    """
    conn = make_v2_db_with_observation(tmp_path / db_name, b03._CREATE_OBSERVATION_SQL, rows)
    common.attach_readonly(conn, registry_db, "reg")
    return conn


def test_unit_evidence_runs_by_default_because_fixture_now_has_a_unit_table(tmp_path):
    """Issue #48 PR-1 §4: `_assert_unit_evidence()` はもう `reg.unit` の有無で
    素通りしない（`make_registry_db()` が既定で `unit` を持つようになったため、
    そもそも「無い」経路には実運用でも通常のテストでも入らない）。既定の
    `_registry_db()`（`DEFAULT_UNITS`＝`common:unit:mg_per_l`→"mg/L"）と
    既定の `_row()`（`unit_id="common:unit:mg_per_l"` なら `unit_raw="mg/L"`）が
    整合していることを確認する回帰テスト。
    """
    rows = [_row("measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none")]
    registry_db = _registry_db(tmp_path)  # 既定で unit テーブルあり（DEFAULT_UNITS）
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    try:
        stats = b04._assert_unit_evidence(conn, declarations_path=_write_declarations(tmp_path, []))
        assert stats["n_unit_symbol_mismatch"] == 0
    finally:
        conn.close()


def test_unit_evidence_passes_when_unit_raw_matches_symbol(tmp_path):
    """`source_table='measurements'` で `unit_id` が埋まっている行の `unit_raw` が
    `unit.symbol` と一致すれば通る（D3 の前提が保たれている状態）。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none",
            unit_id="common:unit:mg_per_l",
        ),
    ]
    registry_db = _registry_db_with_unit(tmp_path, [("common:unit:mg_per_l", "mg/L")])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    try:
        stats = b04._assert_unit_evidence(
            conn, declarations_path=_write_declarations(tmp_path, [])
        )
        assert stats["n_unit_symbol_mismatch"] == 0
    finally:
        conn.close()


def test_unit_evidence_raises_when_measurements_unit_raw_does_not_match_symbol(tmp_path):
    """変異: `source_table='measurements'` の `unit_raw` がレジストリの `symbol`
    と食い違う行を1つ混ぜると `_assert_unit_evidence()` が
    `common.MigrationError` で止まる（D3 の前提が崩れたことを機械的に拾う）。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none",
            unit_id="common:unit:mg_per_l",
        ),
    ]
    # symbol を "mg/L" ではなく別の値にして不一致を作る。
    registry_db = _registry_db_with_unit(tmp_path, [("common:unit:mg_per_l", "mg/l")])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    try:
        with pytest.raises(common.MigrationError, match="unit.symbol と一致しない"):
            b04._assert_unit_evidence(conn, declarations_path=_write_declarations(tmp_path, []))
    finally:
        conn.close()


def test_unit_evidence_ignores_sensor_timeseries_symbol_mismatch(tmp_path):
    """検証1は `source_table='measurements'` に限る——`sensor_timeseries` の
    表記ゆれ（実測: raw "μg/m3" vs registry symbol "ug/m3" 等、48,489件）は
    D3 の対象外なので、ここで不一致があっても素通りする。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none",
            unit_id="common:unit:ug_per_m3",
        ),
    ]
    registry_db = _registry_db_with_unit(tmp_path, [("common:unit:ug_per_m3", "ug/m3")])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    conn.execute(
        "UPDATE observation SET unit_raw = 'μg/m3' WHERE source_row_id = 's1'"
    )
    conn.commit()
    try:
        stats = b04._assert_unit_evidence(conn, declarations_path=_write_declarations(tmp_path, []))
        assert stats["n_unit_symbol_mismatch"] == 0
    finally:
        conn.close()


def test_unit_evidence_declared_gap_passes(tmp_path):
    """`unit_id IS NULL AND unit_raw IS NOT NULL` の系列が、宣言 YAML の内容と
    過不足なく一致すれば通る（D3 のスコープ外に残った既知の欠落、例:
    `scripts/migrate/unit_evidence_declarations.yaml` の
    sensor_timeseries/water_temp 系列と同じ形）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01", "2020-01-01", 12.3, "12.3", "none",
            variable_id="common:variable:water.water_temp", unit_id=None, value_grain="instant",
        ),
    ]
    registry_db = _registry_db_with_unit(tmp_path, [])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    conn.execute("UPDATE observation SET unit_raw = 'degC' WHERE source_row_id = 's1'")
    conn.commit()
    declarations_path = _write_declarations(
        tmp_path,
        [
            {
                "source_table": "sensor_timeseries",
                "variable_id": "common:variable:water.water_temp",
                "obs_stat": None,
                "value_grain": "instant",
            }
        ],
    )
    try:
        stats = b04._assert_unit_evidence(conn, declarations_path=declarations_path)
        assert stats["n_unit_evidence_declared"] == 1
    finally:
        conn.close()


def test_unit_evidence_raises_on_undeclared_gap(tmp_path):
    """変異: 上と同じ欠落があるのに宣言 YAML が空だと、
    `_assert_unit_evidence()` が「宣言されていない欠落」で止まる
    （新しい欠落が黙って増えるのを防ぐ）。
    """
    rows = [
        _row(
            "sensor_timeseries", "s1", "2020-01-01", "2020-01-01", 12.3, "12.3", "none",
            variable_id="common:variable:water.water_temp", unit_id=None, value_grain="instant",
        ),
    ]
    registry_db = _registry_db_with_unit(tmp_path, [])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    conn.execute("UPDATE observation SET unit_raw = 'degC' WHERE source_row_id = 's1'")
    conn.commit()
    try:
        with pytest.raises(common.MigrationError, match="宣言されていない欠落"):
            b04._assert_unit_evidence(conn, declarations_path=_write_declarations(tmp_path, []))
    finally:
        conn.close()


def test_unit_evidence_raises_on_stale_declaration(tmp_path):
    """変異: 宣言 YAML に無くなった（解決済みの）系列が残っていると、
    `_assert_unit_evidence()` が「宣言が腐っている」で止まる
    （解決済みの宣言を消し忘れる退行を防ぐ。CLAUDE.md「宣言済み差分 >
    データを曲げる」）。
    """
    rows = [
        _row(
            "measurements", "m1", "2020-01-01", "2020-01-01", 2.0, "2.0", "none",
            unit_id="common:unit:mg_per_l",
        ),
    ]
    registry_db = _registry_db_with_unit(tmp_path, [("common:unit:mg_per_l", "mg/L")])
    conn = _observation_conn_with_attached_registry(tmp_path, rows, registry_db)
    declarations_path = _write_declarations(
        tmp_path,
        [
            {
                # 実データにはもう存在しない、解決済みのはずの系列。
                "source_table": "sensor_timeseries",
                "variable_id": "common:variable:water.water_temp",
                "obs_stat": None,
                "value_grain": "instant",
            }
        ],
    )
    try:
        with pytest.raises(common.MigrationError, match="宣言を削除すること"):
            b04._assert_unit_evidence(conn, declarations_path=declarations_path)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 自己不変条件（Issue #48 PR-5。`scripts/migrate/cube_invariants.py`。b05 から移設）
# ---------------------------------------------------------------------------

def _alias(dataset, alias, variable_id, unit_id, stat, grain):
    return (dataset, alias, "src", variable_id, unit_id, stat, grain)


def _registry_with_aliases(tmp_path, aliases):
    registry_db = tmp_path / "registry.sqlite"
    make_registry_db(registry_db, aliases=aliases)
    return registry_db


def _build_with_aliases(tmp_path, aliases, rows=None):
    """`aliases` を持つ registry で `build_cube()` を呼ぶ（b04 が alias の検査を
    呼ぶことの確認。`rows` 省略時は1行だけの `observation`）。
    """
    rows = rows or [_row("measurements", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none")]
    conn = make_v2_db_with_observation(tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, rows)
    try:
        return b04.build_cube(conn, _registry_with_aliases(tmp_path, aliases), unit_evidence_declarations_path=None)
    finally:
        conn.close()


_BOD = ("common:variable:water.bod", "common:unit:mg_per_l")


def test_alias_collision_halts_build_cube(tmp_path):
    with pytest.raises(common.MigrationError, match="関数になっていない"):
        _build_with_aliases(tmp_path, [
            _alias("measurements", "BOD", *_BOD, None, "day"),
            _alias("measurements", "BOD_alt", *_BOD, None, "day"),  # 同じ組に別名
        ])


def test_alias_collision_in_a_landuse_year_version_halts(tmp_path):
    """土地利用の年版 dataset（`<source>@<年>`）ごとにも関数性を見る。"""
    ds = "nlni_l03b_landuse_by_watershed@2006"
    with pytest.raises(common.MigrationError, match="関数になっていない"):
        _build_with_aliases(tmp_path, [
            _alias(ds, "1:area_km2", "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
            _alias(ds, "01:area_km2", "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
        ])


def test_alias_collision_passes_for_default_fixture_and_landuse_year_sharing(tmp_path):
    """衝突の無い既定の registry と、土地利用が年版をまたいで同じ tuple を共有する
    正常系（正規化後は同じ出典名）は通る。
    """
    _build_with_aliases(tmp_path, list(DEFAULT_ALIASES) + [
        _alias("nlni_l03b_landuse_by_watershed@2006", "1:area_km2",
               "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
        _alias("nlni_l03b_landuse_by_watershed@2016", "0100:area_km2",
               "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
    ])


def test_alias_tuple_spanning_two_datasets_halts_build_cube(tmp_path):
    with pytest.raises(common.MigrationError, match="複数の出典.*にまたがっている"):
        _build_with_aliases(tmp_path, [
            _alias("measurements", "水温", "common:variable:water.water_temp", None, None, "instant"),
            _alias("sensor_timeseries", "WTEMP", "common:variable:water.water_temp", None, None, "instant"),
        ])


def test_alias_tuple_collision_between_landuse_and_measurements_is_still_detected(tmp_path):
    with pytest.raises(common.MigrationError, match="複数の出典.*にまたがっている"):
        _build_with_aliases(tmp_path, [
            _alias("measurements", "何か", "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
            _alias("nlni_l03b_landuse_by_watershed@2006", "1:area_km2",
                   "common:variable:landuse.paddy", "common:unit:km2", "sum", "year"),
        ])


def test_known_snow_month_alias_duplicates_are_excluded_by_declared_constant(tmp_path):
    """積雪3変数の月次 alias 揺れ（既知の登録負債）は定数で除外され止まらない。
    同じ dataset でも grain が違えば（日次の重複は）止まる——grain を黙って狭めない。
    """
    var = "common:variable:weather.snow_depth_max"
    dup_month = [
        _alias("sensor_timeseries", "雪_最深 積雪", var, "common:unit:cm", "max", "month"),
        _alias("sensor_timeseries", "雪_最深積雪", var, "common:unit:cm", "max", "month"),
    ]
    _build_with_aliases(tmp_path, dup_month)
    assert ("sensor_timeseries", var, "month") in cube_invariants.KNOWN_DUPLICATE_ALIAS_SERIES
    dup_day = [(*a[:6], "day") for a in dup_month]
    (tmp_path / "sub").mkdir()
    with pytest.raises(common.MigrationError, match="関数になっていない"):
        _build_with_aliases(tmp_path / "sub", dup_day)


def test_two_unit_raw_in_one_series_halts_build_cube(tmp_path):
    rows = [
        _row("sensor_timeseries", "m1", "2020-01-01", "2020-01-01", 1.0, "1.0", "none"),
        _row("sensor_timeseries", "m2", "2020-01-02", "2020-01-02", 1.0, "1.0", "none"),
    ]
    # （単位の証拠検査は measurements だけが対象なので、sensor_timeseries で作る。）
    # 同じ系列（variable・value_grain・obs_stat・unit_id）に別の単位表記。
    rows[1] = rows[1][:8] + ("mg/l",) + rows[1][9:]
    conn = make_v2_db_with_observation(tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, rows)
    try:
        with pytest.raises(common.MigrationError, match="unit_raw が関数になっていない"):
            b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
    finally:
        conn.close()


def _hour_rows():
    """毎時の1系列: 2020-01-01 の 01・02 時ラベルと 2020-01-02 の 00 時ラベル（=前日 23 時の
    観測）。period_start は b03 が「ラベル-1時間」にしたもの。"""
    kw = dict(
        variable_id="common:variable:weather.precipitation", unit_id=None,
        value_grain="hour", period_grain="hour",
    )
    return [
        _row("sensor_timeseries", "h1", "2020-01-01T00:00:00", "2020-01-01T01:00:00", 1.0, None, "none",
             period_raw="2020-01-01T01:00:00+09:00", **kw),
        _row("sensor_timeseries", "h2", "2020-01-01T01:00:00", "2020-01-01T02:00:00", 2.0, None, "none",
             period_raw="2020-01-01T02:00:00+09:00", **kw),
        _row("sensor_timeseries", "h3", "2020-01-01T23:00:00", "2020-01-02T00:00:00", 4.0, None, "none",
             period_raw="2020-01-02T00:00:00+09:00", **kw),
    ]


def test_hourly_daily_rollup_passes_through_build_cube(tmp_path):
    conn = make_v2_db_with_observation(tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, _hour_rows())
    try:
        b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
        n = conn.execute(
            "SELECT n FROM observation_agg WHERE grain='day' AND input_grain='hour' AND stat='mean' "
            "AND period_start='2020-01-01'"
        ).fetchone()[0]
        assert n == 3  # 00 時ラベル（前日 23 時）も 01-01 のセルに入る
    finally:
        conn.close()


def test_hourly_daily_rollup_mutation_is_caught_in_build_cube(tmp_path, monkeypatch):
    """日次セルの n を壊す変異（b04 の SQL が壊れた状況）は T6 が止める。
    直前の検証（value_zero/value_lod の関係）の位置で `staging` の n を壊して注入する。
    """
    real = b04._assert_value_zero_lod_invariants

    def break_then_check(conn, staging):
        conn.execute(
            f'UPDATE "{staging}" SET n = n + 100 WHERE grain = \'day\' AND input_grain = \'hour\' AND stat = \'mean\''
        )
        real(conn, staging)

    monkeypatch.setattr(b04, "_assert_value_zero_lod_invariants", break_then_check)
    conn = make_v2_db_with_observation(tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, _hour_rows())
    try:
        with pytest.raises(common.MigrationError, match="T6"):
            b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
    finally:
        conn.close()


def test_verify_hourly_daily_rollup_function_directly():
    """期待式（キューブの日次 n = ラベル日割りの n − 00 時ラベル + 翌日の 00 時ラベル）を、
    手作りの `observation` と `staging` で直接確かめる。
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE observation (region_id, place_id, place_kind, variable_id, obs_stat, "
        "unit_id, value_grain, period_raw, value_num)"
    )
    conn.execute(
        "CREATE TABLE staging (region_id, place_id, place_kind, variable_id, obs_stat, "
        "unit_id, value_grain, period_start, period_end, grain, input_grain, stat, value_zero, n)"
    )
    dim = ("jp-14", "place_s1", "site", "v1", None, "u1", "hour")
    conn.executemany(
        "INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (*dim, "2020-01-01T01:00:00+09:00", 1.0),
            (*dim, "2020-01-01T02:00:00+09:00", 2.0),
            (*dim, "2020-01-01T03:00:00+09:00", 3.0),
            (*dim, "2020-01-02T00:00:00+09:00", 4.0),
        ],
    )
    # 4件すべてが 2020-01-01 のセル（00 時ラベルは前日側）。
    conn.executemany(
        "INSERT INTO staging VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "mean", 2.5, 4),
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "min", 1.0, 4),
            (*dim, "2020-01-01", "2020-01-01", "day", "hour", "max", 4.0, 4),
        ],
    )
    stats = cube_invariants.verify_hourly_daily_rollup(conn, "staging")
    assert stats["n_series_days_checked"] >= 1

    # Σn は合っていても max が違えば（系列ごとの全期間の突合）止まる。
    conn.execute("UPDATE staging SET value_zero = 3.0 WHERE stat = 'max'")
    with pytest.raises(common.MigrationError, match="T6.*Σn・min・max"):
        cube_invariants.verify_hourly_daily_rollup(conn, "staging")


# ---------------------------------------------------------------------------
# 無作為抽出セルの独立再計算（Issue #48 PR-5 §2.3）
# ---------------------------------------------------------------------------

def _sampling_rows():
    """日次・月次/年次の積み上げ・出典配布セル（fiscal_year・month）・検閲を一通り含む観測。"""
    rows = []
    for d in range(1, 31):
        day = f"2020-01-{d:02d}"
        if d == 15:
            rows.append(_row("measurements", f"m{d}", day, day, None, "<0.5", "below_lod", censoring_limit=0.5))
        elif d == 16:
            rows.append(_row("measurements", f"m{d}", day, day, None, "ND", "not_detected"))
        else:
            rows.append(_row("measurements", f"m{d}", day, day, float(d), str(d), "none"))
    rows.append(_row(
        "measurements", "fy1", "2020-04-01", "2021-03-31", 3.0, "3.0", "none",
        variable_id="common:variable:water.cod", value_grain="fiscal_year", period_grain="fiscal_year",
    ))
    rows.append(_row(
        "measurements", "mo1", "2020-02-01", "2020-02-29", 5.0, "5.0", "none",
        variable_id="common:variable:water.ph", value_grain="month", period_grain="month",
    ))
    return rows


def _built_cube_conn(tmp_path, rows=None):
    conn = make_v2_db_with_observation(
        tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, rows or _sampling_rows(),
    )
    b04.build_cube(conn, _registry_db(tmp_path), unit_evidence_declarations_path=None)
    return conn


def _recheck(conn, fingerprint="fp"):
    return b04._assert_sampled_cells_recompute_from_observation(conn, "observation_agg", fingerprint, "sv")


def test_sampled_recompute_passes_on_a_correct_cube_and_covers_every_cell_path(tmp_path):
    conn = _built_cube_conn(tmp_path)
    try:
        stats = _recheck(conn)
        # 小さな入力では各層が丸ごと抽出される（≤200セル）。
        assert stats["n_sampled_cells"] == conn.execute("SELECT COUNT(*) FROM observation_agg").fetchone()[0]
        assert stats["n_sampled_censored_cells"] > 0
        # 経路ごとに1つ以上のセルがある（day/月・年の積み上げ/出典配布 month・fiscal_year）。
        paths = {r[0] for r in conn.execute("SELECT DISTINCT grain || '/' || input_grain FROM observation_agg")}
        assert {"day/day", "month/day", "year/day", "month/month", "fiscal_year/fiscal_year"} <= paths
    finally:
        conn.close()


@pytest.mark.parametrize(
    "where, column",
    [
        pytest.param("grain='day' AND stat='mean' AND period_start='2020-01-15'", "value_lod", id="day_value_lod"),
        pytest.param("grain='day' AND stat='mean' AND period_start='2020-01-03'", "n", id="day_n"),
        pytest.param("grain='day' AND stat='max' AND period_start='2020-01-03'", "value_zero", id="day_max"),
        pytest.param("grain='day' AND stat='mean' AND period_start='2020-01-15'", "n_censored", id="day_n_censored"),
        pytest.param("grain='month' AND input_grain='day'", "value_zero", id="month_from_day"),
        pytest.param("grain='month' AND input_grain='day'", "n_not_detected", id="month_from_day_nd"),
        pytest.param("grain='year' AND input_grain='day' AND stat='min'", "value_lod", id="year_from_day_min"),
        pytest.param("grain='year' AND input_grain='day' AND stat='mean'", "n", id="year_from_day_n"),
        pytest.param("grain='fiscal_year'", "value_zero", id="source_fiscal_year"),
        pytest.param("grain='month' AND input_grain='month' AND stat='max'", "value_zero", id="source_month"),
    ],
)
def test_sampled_recompute_detects_a_corrupted_cell(tmp_path, where, column):
    """staging の1セルを壊すと（層の全セルが抽出される小さな入力なので）必ず落ちる。"""
    conn = _built_cube_conn(tmp_path)
    try:
        cur = conn.execute(f"UPDATE observation_agg SET {column} = COALESCE({column}, 0) + 1 WHERE {where}")
        assert cur.rowcount >= 1
        with pytest.raises(common.MigrationError, match="独立な再計算と一致しない"):
            _recheck(conn)
    finally:
        conn.close()


def test_sampled_recompute_detects_a_phantom_cell(tmp_path):
    """観測に無いセル（期待 n=0 に対して n=1）も食い違いとして落ちる。"""
    conn = _built_cube_conn(tmp_path)
    try:
        conn.execute(
            "INSERT INTO observation_agg SELECT region_id, place_id, place_kind, variable_id, obs_stat, unit_id, "
            "value_grain, '2019-05-05', '2019-05-05', grain, input_grain, stat, value_zero, value_lod, n, "
            "n_censored, n_not_detected, n_places, built_from, spec_version FROM observation_agg "
            "WHERE grain='day' AND stat='mean' AND period_start='2020-01-03'"
        )
        with pytest.raises(common.MigrationError, match="独立な再計算と一致しない"):
            _recheck(conn)
    finally:
        conn.close()


def _picked(conn, fingerprint):
    seed = b04._sample_seed(fingerprint, "sv")
    return b04._pick_sample_rowids(conn, "observation_agg", seed)


def test_sampling_is_deterministic_and_depends_on_the_observation_fingerprint(tmp_path, monkeypatch):
    conn = _built_cube_conn(tmp_path)
    try:
        monkeypatch.setattr(b04, "SAMPLE_CELLS_PER_STRATUM", 3)
        monkeypatch.setattr(b04, "SAMPLE_CENSORED_CELLS_PER_STRATUM", 0)
        assert _picked(conn, "fp-a") == _picked(conn, "fp-a")
        assert len({tuple(_picked(conn, f"fp-{i}")) for i in range(8)}) > 1
    finally:
        conn.close()


def test_sampling_always_includes_the_max_n_cell_and_censored_cells(tmp_path, monkeypatch):
    """ランダム枠を0にしても、各層の n 最大のセルと検閲を含むセルは必ず抽出される。"""
    conn = _built_cube_conn(tmp_path)
    try:
        monkeypatch.setattr(b04, "SAMPLE_CELLS_PER_STRATUM", 0)
        picked = set(_picked(conn, "fp"))
        censored = {
            r[0] for r in conn.execute(
                "SELECT rowid FROM observation_agg WHERE grain='day' AND input_grain='day' "
                "AND stat='mean' AND (n_censored > 0 OR n_not_detected > 0)"
            )
        }
        assert len(censored) == 2 and censored <= picked
        max_month = conn.execute(
            "SELECT rowid FROM observation_agg WHERE grain='month' AND input_grain='day' AND stat='mean' "
            "ORDER BY n DESC LIMIT 1"
        ).fetchone()[0]
        assert max_month in picked
    finally:
        conn.close()


def test_sampled_recompute_is_wired_into_build_cube_and_keeps_the_previous_cube_on_failure(tmp_path, monkeypatch):
    """`build_cube()` の中で呼ばれ、落ちれば本番名へ差し替えない（前回の observation_agg が残る）。
    前の検証をすり抜ける形で staging の日次セルの値を壊す変異を注入する。"""
    conn = make_v2_db_with_observation(tmp_path / "v2.sqlite", b03._CREATE_OBSERVATION_SQL, _sampling_rows())
    registry_db = _registry_db(tmp_path)
    b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
    before = conn.execute("SELECT COUNT(*), SUM(value_zero) FROM observation_agg").fetchone()

    real = cube_invariants.verify_hourly_daily_rollup

    def corrupt_then_check(c, staging, *args, **kwargs):
        # 前の検証（value_zero/value_lod の関係・T6）をすり抜ける、両系列そろった値の改ざん。
        c.execute(
            f'UPDATE "{staging}" SET value_zero = value_zero + 1, value_lod = value_lod + 1 '
            "WHERE grain='day' AND stat='mean' AND period_start='2020-01-03'"
        )
        return real(c, staging, *args, **kwargs)

    monkeypatch.setattr(cube_invariants, "verify_hourly_daily_rollup", corrupt_then_check)
    conn.execute("DETACH DATABASE reg")  # 2回目の build_cube が ATTACH し直す
    try:
        with pytest.raises(common.MigrationError, match="独立な再計算と一致しない"):
            b04.build_cube(conn, registry_db, unit_evidence_declarations_path=None)
        assert conn.execute("SELECT COUNT(*), SUM(value_zero) FROM observation_agg").fetchone() == before
    finally:
        conn.close()
