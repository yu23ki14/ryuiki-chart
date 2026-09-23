"""scripts/registry/build_taxon_assessment.py（P-2、2026-09-23。/code-review
対応、2026-09-23）のテスト。

本物の `data/db/*.sqlite`/`data/processed/moe_ias_list.csv`（828MB/Git管理外）を
要さず、`scripts/tests/registry_fixtures.py` の小さな自作 sqlite/CSV だけで
完結する。`registry/taxon/redlist_category.yaml`・`redlist_category_alias.csv`・
`assessment_list.yaml`・`assessment_scope_exclusions.yaml` だけは実物を読む
（手書きの正本で Git 管理下——`test_registry_taxon.py` が
`registry/taxon/vernacular_ja.csv` を実物のまま読むのと同じ扱い。一部のテストは
不正な値を確かめるため、`monkeypatch` でモジュール定数を一時ファイルに差し替える）。
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


def _build(path, redlist_rows=(), taxon_rows=(), taxa_rows=()):
    """`path`（ディレクトリ。存在しなければ作る）に ryuiki/registry の
    フィクスチャを作って `build_taxon_assessment.build()` を実行する。
    `taxa_rows` は `(taxon_id, scientific_name, vernacular_name_ja)` の列
    （`ryuiki.taxa`。moe_ias 行の taxa 照合に使う）。
    """
    path.mkdir(parents=True, exist_ok=True)
    ryuiki_path = path / "ryuiki.sqlite"
    make_ryuiki_redlist_db(ryuiki_path, redlist_rows, taxa_rows)

    registry_conn = common.create_registry_db(path / "registry.sqlite")
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


def _single_ias_row(conn) -> dict:
    rows = conn.execute("SELECT * FROM taxon_assessment WHERE list_id = 'moe_ias_2015'").fetchall()
    assert len(rows) == 1, f"moe_ias_2015 の行数が1件ではない: {len(rows)}"
    return dict(rows[0])


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


def _ias_csv_row(scientific_name="Foo bar", vernacular_name_ja="和名", category_ja="重点対策外来種", **extra):
    row = {
        "category_ja": category_ja, "origin_ja": "国外由来の外来種",
        "taxon_group_ja": "哺乳類", "scientific_name": scientific_name,
        "vernacular_name_ja": vernacular_name_ja, "source_id": "moe_ias_list",
    }
    row.update(extra)
    return row


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
    assert row["vernacular_name_ja_resolved"] is None  # redlist側は常にNULL


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
# codelist・region・scope の実際の検証（/code-review 指摘9）
# ---------------------------------------------------------------------------

def test_redlist_category_unknown_scope_raises(tmp_path, monkeypatch):
    bad_yaml = tmp_path / "redlist_category.yaml"
    bad_yaml.write_text(
        "categories:\n"
        "  - code: EX\n"
        "    label_ja: \"絶滅\"\n"
        "    rank: 70\n"
        "    scope: mars\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ta_module, "REDLIST_CATEGORY_YAML", bad_yaml)
    with pytest.raises(AssertionError, match="scope"):
        ta_module.load_redlist_category_codes()


def test_assessment_list_unknown_region_raises(tmp_path, monkeypatch):
    bad_yaml = tmp_path / "assessment_list.yaml"
    bad_yaml.write_text(
        "lists:\n"
        "  - list_id: x\n"
        "    name: test\n"
        "    year: 2020\n"
        "    kind: red_list\n"
        "    region: mars\n"
        "    codelist: redlist_category\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ta_module, "ASSESSMENT_LIST_YAML", bad_yaml)
    with pytest.raises(AssertionError, match="region"):
        ta_module.load_assessment_lists()


def test_redlist_list_ids_derives_from_kind(tmp_path):
    """`redlist_list_ids()` は `assessment_list.yaml` の `kind='red_list'` から
    導出する（/code-review 指摘8: 以前はこのモジュールと b12 の両方に3件を
    直書きしていた）。"""
    assessment_lists = ta_module.load_assessment_lists()
    ids = ta_module.redlist_list_ids(assessment_lists)
    assert ids == sorted(["rl2020", "rdb2022p", "rl2026"])
    assert "moe_ias_2015" not in ids


def test_codelist_null_means_category_code_always_none(tmp_path, monkeypatch):
    """`assessment_list.yaml` の `moe_ias_2015.codelist: null` が実際に
    category_code=NULL を導く（/code-review 指摘9: codelist を実際の分岐に
    使う）。"""
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [_ias_csv_row()])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)
    conn, _ = _build(tmp_path, taxa_rows=[("foo bar", "Foo bar", "和名")])
    row = _single_ias_row(conn)
    assert row["category_code"] is None


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
# moe_ias_2015（origin_ja を持つ L1 直読み ＋ taxa の和名解決）
# ---------------------------------------------------------------------------

def test_moe_ias_rows_get_moe_ias_2015_list_id_and_carry_origin(tmp_path, monkeypatch):
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(
        csv_path,
        [_ias_csv_row(scientific_name="Herpestes javanicus", vernacular_name_ja="近縁種の和名候補", category_ja="重点対策外来種")],
    )
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)

    conn, counts = _build(
        tmp_path, taxa_rows=[("herpestes javanicus", "Herpestes javanicus", "ジャワマングース")],
    )
    assert counts["taxon_assessment"] == 1
    row = _single_ias_row(conn)
    assert row["list_id"] == "moe_ias_2015"
    assert row["list_year"] == 2015
    assert row["scientific_name_raw"] == "Herpestes javanicus"
    assert row["origin"] == "国外由来の外来種"
    assert row["category_raw"] == "重点対策外来種"
    assert row["category_code"] is None  # moe_ias_2015 に専用コードリストは無い(P-2決定3)
    # v1 の taxa 畳み込み結果（/code-review 指摘1）。moe_ias_list.csv 自身の
    # vernacular_name_ja とは別の値になりうる。
    assert row["vernacular_name_ja_raw"] == "近縁種の和名候補"
    assert row["vernacular_name_ja_resolved"] == "ジャワマングース"


def test_moe_ias_row_without_taxa_match_raises(tmp_path, monkeypatch):
    """`taxa` に対応する行が無ければ黙って空文字/NULLに丸めず止める
    （/code-review 指摘4）。"""
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [_ias_csv_row(scientific_name="Nonexistent species")])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)
    with pytest.raises(ValueError, match="taxa 行が無い"):
        _build(tmp_path)  # taxa_rows を渡さない


def test_moe_ias_null_taxa_vernacular_stays_null_not_empty_string(tmp_path, monkeypatch):
    """`taxa.vernacular_name_ja` が NULL の場合、`""` に丸めずそのまま NULL
    を持たせる（/code-review 指摘4。v1 の `MAX(vernacular_name_ja)` も
    NULL のままの行がありうる）。"""
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [_ias_csv_row(scientific_name="Foo bar")])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)
    conn, _ = _build(tmp_path, taxa_rows=[("foo bar", "Foo bar", None)])
    row = _single_ias_row(conn)
    assert row["vernacular_name_ja_resolved"] is None


def test_moe_ias_scientific_name_mismatch_with_taxa_raises(tmp_path, monkeypatch):
    """`taxa.scientific_name`（v1 が二名法を作る綴り）と moe_ias_list.csv 自身の
    綴りが食い違えば止める（/code-review 指摘10。実データでは429行すべて
    一致することを確認済み——この前提が崩れたら気づけるようにする）。"""
    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [_ias_csv_row(scientific_name="Foo bar")])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)
    # 同じ正規化キー（"foo bar"）だが綴りが違う（2重スペース）taxa 行。
    with pytest.raises(ValueError, match="綴りが食い違う"):
        _build(tmp_path, taxa_rows=[("foo bar", "Foo  bar", "和名")])


def test_ias_assessment_id_is_content_derived_and_stable_across_row_order(tmp_path, monkeypatch):
    """assessment_id は CSV の行順ではなく内容（学名＋区分＋和名）から決まる
    （/code-review 指摘7: ADR-0004 規約2「ID は不変」。行の追加・並べ替えで
    既存行の ID が変わらないことを確認する）。"""
    row_a = _ias_csv_row(scientific_name="Foo bar", vernacular_name_ja="和名A", category_ja="重点対策外来種")
    row_b = _ias_csv_row(scientific_name="Baz qux", vernacular_name_ja="和名B", category_ja="その他の総合対策外来種")
    taxa_rows = [("foo bar", "Foo bar", "和名A"), ("baz qux", "Baz qux", "和名B")]

    csv_path = tmp_path / "moe_ias_list.csv"
    write_moe_ias_list_csv(csv_path, [row_a, row_b])
    monkeypatch.setattr(ta_module, "MOE_IAS_LIST_CSV", csv_path)
    conn1, _ = _build(tmp_path / "run1", taxa_rows=taxa_rows)
    id1 = conn1.execute(
        "SELECT assessment_id FROM taxon_assessment WHERE scientific_name_raw = 'Foo bar'"
    ).fetchone()[0]

    # 行を並べ替えて（新しい行を先頭に挿入したのと同じ効果）再ビルド。
    write_moe_ias_list_csv(csv_path, [row_b, row_a])
    conn2, _ = _build(tmp_path / "run2", taxa_rows=taxa_rows)
    id2 = conn2.execute(
        "SELECT assessment_id FROM taxon_assessment WHERE scientific_name_raw = 'Foo bar'"
    ).fetchone()[0]

    assert id1 == id2
    assert id1.startswith("moe_ias_2015_")


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
        f"  - list_id: moe_ias_2015\n    scientific_name: Species{i} test\n    reasons: [unknown_reason]"
        for i in range(7)
    )
    bad_yaml.write_text(f"exclusions:\n{entries}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="未知の値"):
        ta_module.load_assessment_scope_exclusions(bad_yaml)


def test_load_assessment_scope_exclusions_rejects_unknown_list_id(tmp_path):
    """`list_id` が `assessment_list.yaml` に無ければ止める（/code-review
    指摘6: 打ち間違いだと除外が静かに効かなくなる欠陥があった）。"""
    entries = "\n".join(
        f"  - list_id: {'no_such_list' if i == 0 else 'moe_ias_2015'}\n"
        f"    scientific_name: Species{i} test\n"
        "    reasons: [domestic_origin]"
        for i in range(7)
    )
    bad_yaml = tmp_path / "assessment_scope_exclusions.yaml"
    bad_yaml.write_text(f"exclusions:\n{entries}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="list_id"):
        ta_module.load_assessment_scope_exclusions(bad_yaml)


def test_load_assessment_scope_exclusions_rejects_non_binomial_name(tmp_path):
    """`scientific_name` が二名法（空白区切りで2語）でなければ止める
    （/code-review 指摘5: 亜種名付き等の3語で書かれると `org_norm.binom` と
    一致せず除外が黙って効かなくなる）。"""
    entries = "\n".join(
        f"  - list_id: moe_ias_2015\n"
        f"    scientific_name: {'Species0 subspecies extra' if i == 0 else f'Species{i} test'}\n"
        "    reasons: [domestic_origin]"
        for i in range(7)
    )
    bad_yaml = tmp_path / "assessment_scope_exclusions.yaml"
    bad_yaml.write_text(f"exclusions:\n{entries}\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="二名法"):
        ta_module.load_assessment_scope_exclusions(bad_yaml)
