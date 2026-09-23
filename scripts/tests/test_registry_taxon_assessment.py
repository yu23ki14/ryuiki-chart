"""scripts/registry/build_taxon_assessment.py（P-2、2026-09-23）のテスト。

本物の `data/db/*.sqlite`/`data/processed/moe_ias_list.csv`（828MB/Git管理外）を
要さず、`scripts/tests/registry_fixtures.py` の小さな自作 sqlite/CSV だけで
完結する。`registry/taxon/redlist_category.yaml`・`redlist_category_alias.csv`・
`assessment_list.yaml`・`assessment_scope_exclusions.yaml` だけは実物を読む
（手書きの正本で Git 管理下——`test_registry_taxon.py` が
`registry/taxon/vernacular_ja.csv` を実物のまま読むのと同じ扱い）。
"""
import sqlite3

import pytest

from registry import common
import registry.build_taxon_assessment as ta_module
from registry.build_taxon_assessment import build as build_taxon_assessment

from .registry_fixtures import (
    insert_taxon_rows,
    make_ryuiki_redlist_db,
    open_taxon_assessment_src,
    write_moe_ias_list_csv,
)


@pytest.fixture(autouse=True)
def _empty_moe_ias_list(monkeypatch, tmp_path):
    """MOE_IAS_LIST_CSV（Git管理外）を空の CSV に差し替える（各テストが
    必要なら `write_moe_ias_list_csv()` で上書きする）。
    """
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)


def _build(tmp_path, redlist_rows=(), taxon_rows=()):
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    make_ryuiki_redlist_db(ryuiki_path, redlist_rows)

    registry_conn = common.create_registry_db(tmp_path / "registry.sqlite")
    registry_conn.row_factory = sqlite3.Row
    if taxon_rows:
        insert_taxon_rows(registry_conn, taxon_rows)
        registry_conn.commit()

    src = open_taxon_assessment_src(ryuiki_path)
    try:
        counts = build_taxon_assessment(registry_conn, src)
    finally:
        src["ryuiki"].close()
    return registry_conn, counts


def _assessment(conn, assessment_id):
    row = conn.execute(
        "SELECT * FROM taxon_assessment WHERE assessment_id = ?", (assessment_id,)
    ).fetchone()
    assert row is not None, f"{assessment_id} が taxon_assessment に無い"
    return dict(row)


# 実物の assessment_list.yaml の list_id と一致させる（rl2020, 2020年,
# 神奈川県レッドリスト2020）。手書きの正本を読み替えないテストなので、
# ここだけは実際の list_name/list_year に合わせる。
_RL2020_NAME = "神奈川県レッドリスト2020（植物編CSV）"


def _rl_row(
    assessment_id="rl2020_00001", category_ja="絶滅", category_prev_ja="絶滅危惧Ⅱ類",
    scientific_name="Foo bar", national_category_ja=None, source_id="kanagawa_redlist",
):
    return (
        assessment_id, _RL2020_NAME, 2020, "維管束植物", "シダ植物", "テスト科",
        "テスト和名", scientific_name, category_ja, category_prev_ja,
        national_category_ja, source_id,
    )


# ---------------------------------------------------------------------------
# カテゴリーの正規化・コード化
# ---------------------------------------------------------------------------

def test_category_and_prev_category_are_coded(tmp_path):
    conn, counts = _build(tmp_path, redlist_rows=[_rl_row()])
    assert counts["taxon_assessment"] == 1
    row = _assessment(conn, "rl2020_00001")
    assert row["list_id"] == "rl2020"
    assert row["list_year"] == 2020
    assert row["category_raw"] == "絶滅"
    assert row["category_code"] == "EX"
    assert row["prev_category_raw"] == "絶滅危惧Ⅱ類"
    assert row["prev_category_code"] == "VU"


def test_dash_prev_category_resolves_to_not_listed(tmp_path):
    """P-2決定1: `'―'`（前回記載なし）は `not_listed` として明示的に持つ
    （黙って NULL に落とさない）。"""
    conn, _ = _build(tmp_path, redlist_rows=[_rl_row(category_prev_ja="―")])
    row = _assessment(conn, "rl2020_00001")
    assert row["prev_category_raw"] == "―"
    assert row["prev_category_code"] == "not_listed"


def test_normalization_is_used_only_for_alias_lookup(tmp_path):
    """正規化（改行・半角/全角空白の除去）は alias を引くキーにだけ使う。
    `category_raw` 自体は原表記のまま無加工で残る。"""
    conn, _ = _build(tmp_path, redlist_rows=[_rl_row(category_prev_ja="準絶滅危惧\n/情報不足")])
    row = _assessment(conn, "rl2020_00001")
    assert row["prev_category_raw"] == "準絶滅危惧\n/情報不足"  # 無加工
    assert row["prev_category_code"] == "NT"  # 正規化後は「準絶滅危惧/情報不足」でNT


def test_unknown_category_raises(tmp_path):
    with pytest.raises(ValueError, match="未知のcategory_ja"):
        _build(tmp_path, redlist_rows=[_rl_row(category_ja="ありえないカテゴリー")])


def test_national_category_ja_passes_through_unprocessed(tmp_path):
    """national_category_ja は v1 と同じくコード化しない・正規化もしない
    （自由記述が混ざるため）。"""
    conn, _ = _build(
        tmp_path,
        redlist_rows=[_rl_row(national_category_ja="（ハマカキラン：\n絶滅危惧Ⅱ類）")],
    )
    row = _assessment(conn, "rl2020_00001")
    assert row["national_category_raw"] == "（ハマカキラン：\n絶滅危惧Ⅱ類）"


def test_unknown_list_id_prefix_raises(tmp_path):
    with pytest.raises(ValueError, match="assessment_list.yaml"):
        _build(tmp_path, redlist_rows=[_rl_row(assessment_id="unknownlist_00001")])


def test_list_name_year_mismatch_raises(tmp_path):
    """assessment_id の接頭辞は `rl2020` に一致するが list_name が違う場合は
    止める（新しい版の取り違えを検知）。"""
    mismatched_row = (
        "rl2020_00001", "違う名前のリスト", 2020, None, None, None,
        None, "Foo bar", "絶滅", None, None, "kanagawa_redlist",
    )
    with pytest.raises(ValueError, match="食い違う"):
        _build(tmp_path, redlist_rows=[mismatched_row])


# ---------------------------------------------------------------------------
# taxon_id 解決（学名完全一致 -> 二名法一致。曖昧なら解決しない）
# ---------------------------------------------------------------------------

def test_taxon_id_resolves_by_exact_scientific_name(tmp_path):
    conn, _ = _build(
        tmp_path, redlist_rows=[_rl_row(scientific_name="Foo bar")],
        taxon_rows=[("common:taxon:gbif.1", "Foo bar", "Foo bar")],
    )
    row = _assessment(conn, "rl2020_00001")
    assert row["taxon_id"] == "common:taxon:gbif.1"


def test_taxon_id_falls_back_to_binomial_when_no_exact_match(tmp_path):
    """完全一致が無い場合、二名法（先頭2語）で一意に決まれば解決する。"""
    conn, _ = _build(
        tmp_path, redlist_rows=[_rl_row(scientific_name="Foo bar Auct.")],
        taxon_rows=[("common:taxon:gbif.1", "Foo bar (GBIF形)", "Foo bar")],
    )
    row = _assessment(conn, "rl2020_00001")
    assert row["taxon_id"] == "common:taxon:gbif.1"


def test_taxon_id_stays_null_when_binomial_ambiguous(tmp_path):
    """二名法一致が複数候補に割れる場合は解決しない（NULLのまま。
    推測で埋めない）。"""
    conn, _ = _build(
        tmp_path, redlist_rows=[_rl_row(scientific_name="Foo bar Auct.")],
        taxon_rows=[
            ("common:taxon:gbif.1", "Foo bar (v1)", "Foo bar"),
            ("common:taxon:inat.2", "Foo bar (v2)", "Foo bar"),
        ],
    )
    row = _assessment(conn, "rl2020_00001")
    assert row["taxon_id"] is None


# ---------------------------------------------------------------------------
# moe_ias_2015（origin_ja を持つ L1 直読み）
# ---------------------------------------------------------------------------

def test_moe_ias_rows_get_moe_ias_2015_list_id_and_carry_origin(tmp_path, monkeypatch, tmp_path_factory):
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(
        csv_path,
        [
            {
                "category_ja": "重点対策外来種", "origin_ja": "国外由来の外来種",
                "taxon_group_ja": "哺乳類", "scientific_name": "Herpestes javanicus",
                "vernacular_name_ja": "ジャワマングース", "source_id": "moe_ias_list",
            },
        ],
    )
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)

    conn, counts = _build(tmp_path)
    assert counts["taxon_assessment"] == 1
    row = _assessment(conn, "moe_ias_2015_00001")
    assert row["list_id"] == "moe_ias_2015"
    assert row["list_year"] == 2015
    assert row["scientific_name_raw"] == "Herpestes javanicus"
    assert row["origin"] == "国外由来の外来種"
    assert row["category_raw"] == "重点対策外来種"
    assert row["category_code"] is None  # moe_ias_2015 に専用コードリストは無い(P-2決定3)


# ---------------------------------------------------------------------------
# 除外7種の宣言（P-2 オーナー決定A）の構造検証
# ---------------------------------------------------------------------------

def test_load_assessment_scope_exclusions_matches_expected_counts():
    """実物の registry/taxon/assessment_scope_exclusions.yaml が、宣言どおり
    7種（domestic_origin 6件・subspecies_binomial_contraction 2件、
    Trypoxylus dichotomus は両方）であることを検証する。"""
    entries = ta_module.load_assessment_scope_exclusions()
    assert len(entries) == 7
    by_name = {e["scientific_name"]: e["reasons"] for e in entries}
    assert by_name["Trypoxylus dichotomus"] == ["domestic_origin", "subspecies_binomial_contraction"]
    assert by_name["Apis mellifera"] == ["subspecies_binomial_contraction"]
    assert by_name["Nyctereutes procyonoides"] == ["domestic_origin"]


def test_load_assessment_scope_exclusions_rejects_wrong_total(tmp_path):
    bad_yaml = tmp_path / "assessment_scope_exclusions.yaml"
    bad_yaml.write_text(
        "exclusions:\n"
        "  - list_id: moe_ias_2015\n"
        "    scientific_name: Foo bar\n"
        "    reasons: [domestic_origin]\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="総数"):
        ta_module.load_assessment_scope_exclusions(bad_yaml)


def test_load_assessment_scope_exclusions_rejects_unknown_reason(tmp_path):
    bad_yaml = tmp_path / "assessment_scope_exclusions.yaml"
    entries = "\n".join(
        f"  - list_id: moe_ias_2015\n    scientific_name: Species{i}\n    reasons: [unknown_reason]"
        for i in range(7)
    )
    bad_yaml.write_text(f"exclusions:\n{entries}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="未知の値"):
        ta_module.load_assessment_scope_exclusions(bad_yaml)
