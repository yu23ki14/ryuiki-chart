"""scripts/b08_project_occurrence_v1.py の `ias_species`（P-2。/code-review
対応、2026-09-23）のテスト。

本物の `data/db/*.sqlite`/`registry/taxon/*` を要さず、
`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで完結する。
`registry/taxon/assessment_scope_exclusions.yaml`（7種の除外宣言。手書きの
正本で Git 管理下）だけは実物を読む（`test_registry_taxon.py` が
`registry/taxon/vernacular_ja.csv` を実物のまま読むのと同じ扱い）。

**この射影（b08）は `registry.sqlite` だけを読み、`ryuiki.sqlite` には一切
触れない**（/code-review 指摘1。和名の解決〔taxa の畳み込み〕は
`scripts/registry/build_taxon_assessment.py` 側の責務——そちらのテストは
`test_registry_taxon_assessment.py`）ため、フィクスチャは
`taxon_assessment.vernacular_name_ja_resolved` に直接、解決済みの値を書く。

`ias_species` の経路は `FULL OUTER JOIN`/`AVG()`/`SUM()`（3.43以降が前提の
機能）を使わないため、**古い SQLite でもスキップせず実行する**（/code-review
指摘14: 受け入れ基準の「古い SQLite でも失敗0」をスキップで満たすのは
筋が悪い）。
"""
import sqlite3

import pytest

import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import (
    make_occurrence_registry_db,
    make_taxon_group_yaml,
    make_v2_db_with_occurrence,
    occurrence_row,
)

_TAXON_FOO = (
    "common:taxon:gbif.1001", "Foo bar", "species", "Insecta", "Animalia",
    "Arthropoda", "Fooales", "Fooidae", "昆虫類",
)
_TAXON_EXCLUDED = (
    "common:taxon:gbif.2002", "Nyctereutes procyonoides", "species", "Mammalia", "Animalia",
    "Chordata", "Carnivora", "Canidae", "哺乳類",
)


def _setup(tmp_path, *, occurrence_rows, taxon_assessments):
    d = tmp_path
    cube_db = d / "v2.sqlite"
    make_v2_db_with_occurrence(cube_db, occurrence_rows)

    registry_db = d / "registry.sqlite"
    make_occurrence_registry_db(
        registry_db,
        taxa=[_TAXON_FOO, _TAXON_EXCLUDED],
        places=[], place_refs=[],
        taxon_assessments=taxon_assessments,
    )
    taxon_group_yaml = d / "taxon_group.yaml"
    make_taxon_group_yaml(taxon_group_yaml, "未判定")

    return cube_db, registry_db, taxon_group_yaml


def _ta_row(
    assessment_id, scientific_name_raw, vernacular_name_ja_resolved, category_raw,
    origin="国外由来の外来種", vernacular_name_ja_raw=None,
):
    """taxon_assessment の1行（moe_ias_2015、ias_species が使う列だけ埋める）。
    `vernacular_name_ja_resolved` は `build_taxon_assessment.py` が taxa の
    畳み込みを経て解決済みの想定で直接渡す（このモジュール自身は解決しない
    ——モジュール docstring参照）。`vernacular_name_ja_raw`（未指定なら
    `vernacular_name_ja_resolved` と同じ）は診断列で ias_species の値には
    影響しない。
    """
    return (
        assessment_id, "moe_ias_2015", 2015, None,
        scientific_name_raw,
        vernacular_name_ja_raw if vernacular_name_ja_raw is not None else vernacular_name_ja_resolved,
        vernacular_name_ja_resolved,
        None, None, None,
        category_raw, None,
        None, None,
        None, origin, "moe_ias_list",
    )


def _run(cube_db, registry_db, taxon_group_yaml, tmp_path):
    out = tmp_path / "out.sqlite"
    return b08.build_ias_species_projection(cube_db, registry_db, out, taxon_group_yaml), out


def _read_ias_species(out_path):
    conn = sqlite3.connect(f"file:{out_path}?mode=ro", uri=True)
    try:
        return {
            (r[0], r[1]): r[2:] for r in conn.execute(
                "SELECT ias_category, binom, name_ja, taxon_group, en_name, n, mesh_n, "
                "y_from, y_to, n_since_2020 FROM ias_species"
            )
        }
    finally:
        conn.close()


def test_ias_species_joins_org_norm_by_binom(tmp_path):
    """taxon_assessment(list_id='moe_ias_2015') の binom と org_norm.binom が
    結合され、件数・年範囲が正しく集計される。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2019-01-01", "2019-01-01", "2019-01-01", scientific_name="Foo bar"),
        occurrence_row("r2", "common:taxon:gbif.1001", "2021-06-01", "2021-06-01", "2021-06-01", scientific_name="Foo bar"),
    ]
    ta = [_ta_row("moe_ias_2015_00001", "Foo bar", "フーバー", "その他の総合対策外来種")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    (table_counts, diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)

    # (table_counts, diagnostics) の2要素タプル（/code-review指摘13。兄弟関数
    # と同じ形）。
    assert table_counts == {"ias_species": 1}
    species = _read_ias_species(out)
    key = ("その他の総合対策外来種", "Foo bar")
    assert key in species
    _name_ja, _taxon_group, _en_name, n, mesh_n, y_from, y_to, n_since_2020 = species[key]
    assert n == 2
    assert y_from == 2019 and y_to == 2021
    assert n_since_2020 == 1  # 2021のみ
    assert diagnostics["delta_binoms"] == []


def test_hardcoded_exclusion_removes_declared_species(tmp_path):
    """`registry/taxon/assessment_scope_exclusions.yaml` に宣言された7種
    （実データの binom そのまま）は、org_norm に記録があっても ias_species
    に現れない（P-2 オーナー決定A）。
    """
    rows = [
        occurrence_row(
            "r1", "common:taxon:gbif.2002", "2020-01-01", "2020-01-01", "2020-01-01",
            scientific_name="Nyctereutes procyonoides",
        ),
    ]
    ta = [_ta_row("moe_ias_2015_00001", "Nyctereutes procyonoides", "タヌキ", "重点対策外来種", origin="国内由来の外来種")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    (table_counts, diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)

    assert table_counts == {"ias_species": 0}
    assert _read_ias_species(out) == {}
    assert "Nyctereutes procyonoides" in diagnostics["hardcoded_exclusion_binoms"]


def test_max_of_resolved_vernacular_names_when_multiple_rows_share_group(tmp_path):
    """`(binom, ias_category)` が同じ複数の `taxon_assessment` 行がある場合、
    `vernacular_name_ja_resolved` の `MAX()`（v1 の `MAX(vernacular_name_ja)`
    と同じ規則）を取る。和名の畳み込み自体（どちらの行の和名が
    `vernacular_name_ja_resolved` として正しいか）はレジストリ側の責務
    （`test_registry_taxon_assessment.py`）なので、ここでは既に解決済みの
    値に対する集約規則だけを確認する。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    ta = [
        _ta_row("moe_ias_2015_00001", "Foo bar", "Zebra name", "その他の総合対策外来種"),
        _ta_row("moe_ias_2015_00002", "Foo bar", "Apple name", "その他の総合対策外来種"),
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    (table_counts, _diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)

    assert table_counts == {"ias_species": 1}
    species = _read_ias_species(out)
    key = ("その他の総合対策外来種", "Foo bar")
    assert species[key][0] == "Zebra name"  # MAX()


def test_null_resolved_vernacular_stays_null_not_empty_string(tmp_path):
    """`vernacular_name_ja_resolved` が NULL の行しか無い場合、`name_ja` は
    `""` ではなく NULL のまま（/code-review 指摘4。SQL の `MAX()` は全部NULL
    なら NULL を返す）。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    ta = [_ta_row("moe_ias_2015_00001", "Foo bar", None, "その他の総合対策外来種")]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    (table_counts, _diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)

    assert table_counts == {"ias_species": 1}
    species = _read_ias_species(out)
    key = ("その他の総合対策外来種", "Foo bar")
    assert species[key][0] is None


def test_empty_category_raw_is_excluded(tmp_path):
    """v1 の `WHERE ias_category IS NOT NULL AND ias_category <> ''` と同じ
    条件で、`category_raw` が空/NULL の行を除く（/code-review 指摘3）。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    ta = [
        _ta_row("moe_ias_2015_00001", "Foo bar", "和名", ""),  # 空文字の区分
        _ta_row("moe_ias_2015_00002", "Foo bar", "和名2", None),  # NULLの区分
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    (table_counts, _diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)

    assert table_counts == {"ias_species": 0}
    assert _read_ias_species(out) == {}


def test_taxon_assessment_empty_yields_zero_rows(tmp_path):
    """taxon_assessment(list_id='moe_ias_2015') が空でもビルドは落ちず0行になる
    （既存テスト・main() の空フィクスチャが黙って壊れないことの回帰）。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    cube_db, registry_db, taxon_group_yaml = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=[])
    (table_counts, diagnostics), out = _run(cube_db, registry_db, taxon_group_yaml, tmp_path)
    assert table_counts == {"ias_species": 0}
    assert diagnostics["delta_binoms"] == []


def test_missing_taxon_assessment_table_raises(tmp_path):
    """`registry.sqlite` に `taxon_assessment` テーブルが無い（P-2 適用前の
    古いレジストリ）場合は、はっきり案内して止める（`_assert_prerequisites`）。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    cube_db = tmp_path / "v2.sqlite"
    make_v2_db_with_occurrence(cube_db, rows)

    # taxon_assessment を持たない、古い形の registry.sqlite。
    registry_db = tmp_path / "registry_old.sqlite"
    conn = sqlite3.connect(str(registry_db))
    conn.execute(
        """CREATE TABLE taxon (
            taxon_id TEXT PRIMARY KEY, canonical_binomial TEXT, rank TEXT, class TEXT,
            kingdom TEXT, phylum TEXT, "order" TEXT, family TEXT, taxon_group TEXT
        )"""
    )
    conn.execute("INSERT INTO taxon VALUES (?,?,?,?,?,?,?,?,?)", _TAXON_FOO)
    conn.commit()
    conn.close()

    taxon_group_yaml = tmp_path / "taxon_group.yaml"
    make_taxon_group_yaml(taxon_group_yaml, "未判定")

    with pytest.raises(common.MigrationError, match="taxon_assessment"):
        _run(cube_db, registry_db, taxon_group_yaml, tmp_path)
