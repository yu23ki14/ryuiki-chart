"""scripts/b08_project_occurrence_v1.py の `ias_species`（P-2）のテスト。

本物の `data/db/*.sqlite`/`registry/taxon/*` を要さず、
`scripts/tests/occurrence_fixtures.py` の小さな自作 sqlite だけで完結する。
`registry/taxon/assessment_scope_exclusions.yaml`（7種の除外宣言。手書きの
正本で Git 管理下）だけは実物を読む（`test_registry_taxon.py` が
`registry/taxon/vernacular_ja.csv` を実物のまま読むのと同じ扱い）。
"""
import sqlite3

import pytest

import b08_project_occurrence_v1 as b08
from migrate import common

from .occurrence_fixtures import (
    make_occurrence_registry_db,
    make_ryuiki_taxa_db,
    make_taxon_group_yaml,
    make_v2_db_with_occurrence,
    occurrence_row,
)

pytestmark = pytest.mark.skipif(
    sqlite3.sqlite_version_info < common.MIN_SQLITE_VERSION,
    reason=f"SQLite {common.MIN_SQLITE_VERSION} 未満（実際: {sqlite3.sqlite_version}）",
)

_TAXON_FOO = (
    "common:taxon:gbif.1001", "Foo bar", "species", "Insecta", "Animalia",
    "Arthropoda", "Fooales", "Fooidae", "昆虫類",
)
_TAXON_EXCLUDED = (
    "common:taxon:gbif.2002", "Nyctereutes procyonoides", "species", "Mammalia", "Animalia",
    "Chordata", "Carnivora", "Canidae", "哺乳類",
)


def _setup(tmp_path, *, occurrence_rows, taxon_assessments, taxa_rows=()):
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

    ryuiki_db = d / "ryuiki.sqlite"
    make_ryuiki_taxa_db(ryuiki_db, taxa_rows)

    return cube_db, registry_db, taxon_group_yaml, ryuiki_db


def _ta_row(
    assessment_id, scientific_name_raw, vernacular_name_ja_raw, category_raw, origin="国外由来の外来種",
):
    """taxon_assessment の1行（moe_ias_2015、ias_species が使う列だけ埋める）。"""
    return (
        assessment_id, "moe_ias_2015", 2015, None,
        scientific_name_raw, vernacular_name_ja_raw,
        None, None, None,
        category_raw, None,
        None, None,
        None, origin, "moe_ias_list",
    )


def _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path):
    out = tmp_path / "out.sqlite"
    return b08.build_ias_species_projection(cube_db, registry_db, out, taxon_group_yaml, ryuiki_db), out


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
    cube_db, registry_db, taxon_group_yaml, ryuiki_db = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    result, out = _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path)

    assert result["ias_species"] == 1
    species = _read_ias_species(out)
    key = ("その他の総合対策外来種", "Foo bar")
    assert key in species
    _name_ja, _taxon_group, _en_name, n, mesh_n, y_from, y_to, n_since_2020 = species[key]
    assert n == 2
    assert y_from == 2019 and y_to == 2021
    assert n_since_2020 == 1  # 2021のみ


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
    cube_db, registry_db, taxon_group_yaml, ryuiki_db = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=ta)
    result, out = _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path)

    assert result["ias_species"] == 0
    assert _read_ias_species(out) == {}
    assert "Nyctereutes procyonoides" in result["hardcoded_exclusion_binoms"]


def test_name_ja_comes_from_taxa_not_raw_max(tmp_path):
    """v1 の `MAX(vernacular_name_ja)`（ias_species）は、`taxa`
    （3出典をまたいだ畳み込み済みの和名）の上で計算される——
    `taxon_assessment.vernacular_name_ja_raw`（moe_ias_list.csv 単体の生の
    和名）の文字列に直接 MAX を取ると v1 と食い違う（実測1件、
    *Coreoperca kawamebari* オヤニラミ。docs/plans/PHASE_B_TAXON_ASSESSMENT.md
    参照）。ここでは2つの moe_ias_2015 行が同じ binom・同じ category に
    畳まれるとき、`vernacular_name_ja_raw` を文字列比較で MAX すれば
    'Zebra...'（アルファベット順で最後）が勝つはずだが、実際に出力される
    name_ja は `taxa.vernacular_name_ja`（正しい和名）であることを確認する。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    ta = [
        _ta_row("moe_ias_2015_00001", "Foo bar", "Zebra alias name（文字列としては最大）", "その他の総合対策外来種"),
        _ta_row("moe_ias_2015_00002", "Foo bar", "Apple alias name", "その他の総合対策外来種"),
    ]
    cube_db, registry_db, taxon_group_yaml, ryuiki_db = _setup(
        tmp_path, occurrence_rows=rows, taxon_assessments=ta,
        taxa_rows=[("foo bar", "正しい和名（taxaの畳み込み結果）")],
    )
    result, out = _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path)

    assert result["ias_species"] == 1
    species = _read_ias_species(out)
    key = ("その他の総合対策外来種", "Foo bar")
    name_ja = species[key][0]
    assert name_ja == "正しい和名（taxaの畳み込み結果）"


def test_taxon_assessment_empty_yields_zero_rows(tmp_path):
    """taxon_assessment(list_id='moe_ias_2015') が空でもビルドは落ちず0行になる
    （既存テスト・main() の空フィクスチャが黙って壊れないことの回帰）。
    """
    rows = [
        occurrence_row("r1", "common:taxon:gbif.1001", "2020-01-01", "2020-01-01", "2020-01-01", scientific_name="Foo bar"),
    ]
    cube_db, registry_db, taxon_group_yaml, ryuiki_db = _setup(tmp_path, occurrence_rows=rows, taxon_assessments=[])
    result, out = _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path)
    assert result["ias_species"] == 0
    assert result["delta_binoms"] == []


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

    ryuiki_db = tmp_path / "ryuiki.sqlite"
    make_ryuiki_taxa_db(ryuiki_db)
    taxon_group_yaml = tmp_path / "taxon_group.yaml"
    make_taxon_group_yaml(taxon_group_yaml, "未判定")

    with pytest.raises(common.MigrationError, match="taxon_assessment"):
        _run(cube_db, registry_db, taxon_group_yaml, ryuiki_db, tmp_path)
