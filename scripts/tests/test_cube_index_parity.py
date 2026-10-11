"""Issue #48 PR-1 §1: `observation_agg`/`occurrence_agg` の索引の正は Drizzle
（`web/src/db/schema-cube.ts` → `web/drizzle/migrations/*.sql`）。`data/db/v2.sqlite`
（`scripts/b04_build_cube.py`/`scripts/b07_build_occurrence_cube.py`）はその写しを
持つ——手で同期を保つのではなく、ここで「マイグレーション SQL から抜いた
CREATE INDEX の集合」と「b04/b07 が定義する集合」が一致することを機械検証する。

ずれたら（Drizzle 側だけ直して b04/b07 を直し忘れた、あるいはその逆）この
テストが落ちる。
"""
import pathlib
import re

import b04_build_cube as b04
import b07_build_occurrence_cube as b07

from .conftest import ROOT

MIGRATIONS_DIR = ROOT / "web" / "drizzle" / "migrations"

_CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+`(?P<name>[^`]+)`\s+ON\s+`(?P<table>[^`]+)`\s*\((?P<cols>[^)]*)\)",
    re.IGNORECASE,
)
_DROP_INDEX_RE = re.compile(r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?`(?P<name>[^`]+)`", re.IGNORECASE)

# 索引の正を持つ2表だけを見る（他の索引は Issue #48 PR-1 の対象外）。
_CUBE_TABLES = ("observation_agg", "occurrence_agg")


def _indexes_from_migrations(tables=_CUBE_TABLES) -> dict[str, dict[str, tuple[str, ...]]]:
    """`MIGRATIONS_DIR` の `*.sql` を番号順に読み、`tables` それぞれについて
    「今も生きている索引名 → 列のタプル」を返す。

    複数ファイルにまたがる `CREATE INDEX`/`DROP INDEX` を番号順に適用して
    最終状態を再現する（今は1ファイルにしか無いが、将来の追加マイグレーションで
    索引が足された場合にも対応できるように）。
    """
    result: dict[str, dict[str, tuple[str, ...]]] = {t: {} for t in tables}
    paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert paths, f"マイグレーション SQL が無い: {MIGRATIONS_DIR}"
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for m in _CREATE_INDEX_RE.finditer(text):
            table = m.group("table")
            if table not in result:
                continue
            cols = tuple(c.strip().strip("`") for c in m.group("cols").split(","))
            result[table][m.group("name")] = cols
        for m in _DROP_INDEX_RE.finditer(text):
            name = m.group("name")
            for per_table in result.values():
                per_table.pop(name, None)
    return result


def test_migration_sql_has_the_expected_cube_indexes():
    """回帰ガード: このテスト自身が「マイグレーション SQL から何も拾えていない」
    という偽陽性（正規表現がずれて両辺とも空集合で一致してしまう）に陥っていない
    ことを先に確認する。
    """
    found = _indexes_from_migrations()
    assert found["observation_agg"], "observation_agg の索引が抽出できていない"
    assert found["occurrence_agg"], "occurrence_agg の索引が抽出できていない"


def test_observation_agg_index_parity():
    from_migrations = _indexes_from_migrations()["observation_agg"]
    from_b04 = {name: tuple(cols) for name, cols in b04.OBSERVATION_AGG_INDEXES}
    assert from_b04 == from_migrations, (
        "b04_build_cube.OBSERVATION_AGG_INDEXES が Drizzle マイグレーション（正）と"
        f"一致しない。migrations={from_migrations} / b04={from_b04}"
    )


def test_occurrence_agg_index_parity():
    from_migrations = _indexes_from_migrations()["occurrence_agg"]
    from_b07 = {name: tuple(cols) for name, cols in b07.OCCURRENCE_AGG_INDEXES}
    assert from_b07 == from_migrations, (
        "b07_build_occurrence_cube.OCCURRENCE_AGG_INDEXES が Drizzle マイグレーション（正）と"
        f"一致しない。migrations={from_migrations} / b07={from_b07}"
    )


# ---------------------------------------------------------------------------
# Issue #48 PR-3b §6-1: `INDEXED BY` に使う索引名の定数（schema-cube.ts の
# `OCCURRENCE_AGG_INDEX`）が b07 の索引名と一致すること。`INDEXED BY` は索引が
# 無いと実行時エラーになるので、名前のずれをここで先に落とす。マイグレーション SQL
# （`0008_*` が出る前でも通る）に依らず、TS の定数と b07 を直接比べる。
# ---------------------------------------------------------------------------

SCHEMA_CUBE_TS = ROOT / "web" / "src" / "db" / "schema-cube.ts"


def _occurrence_agg_index_constants() -> dict[str, str]:
    text = SCHEMA_CUBE_TS.read_text(encoding="utf-8")
    block = re.search(r"export const OCCURRENCE_AGG_INDEX = \{(?P<body>.*?)\} as const;", text, re.DOTALL)
    assert block, "schema-cube.ts に OCCURRENCE_AGG_INDEX が無い"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group("body")))


def test_occurrence_agg_index_name_constants_match_b07():
    constants = _occurrence_agg_index_constants()
    assert set(constants) == {"taxonPeriod", "placePeriod", "kindGrainPeriod"}
    assert set(constants.values()) == {name for name, _ in b07.OCCURRENCE_AGG_INDEXES}


def test_drizzle_index_definitions_use_the_constants():
    """索引の定義側（`index(...)`）が文字列の直書きではなく定数を使っていること
    （直書きに戻ると、定数だけ直して定義がずれる）。"""
    text = SCHEMA_CUBE_TS.read_text(encoding="utf-8")
    for key in _occurrence_agg_index_constants():
        assert f"index(OCCURRENCE_AGG_INDEX.{key})" in text


# ---------------------------------------------------------------------------
# Issue #93: 地域別の事前集計（`*_by_region` 4表と `place_region`）の索引。正は Drizzle、b13 が写しを持つ
# （b13 の索引名は `<表>_<列…>`、Drizzle は `ix_…`。名前は違ってよいので列の組だけを比べる）。
# ---------------------------------------------------------------------------

def test_region_tables_index_parity_with_b13():
    import yaml

    import b13_build_summary as b13
    from migrate import common

    tables = (*common.V2_SUMMARY_BY_REGION_TABLES, common.V2_PLACE_REGION_TABLE, common.V2_TAXON_RED_LIST_TABLE)
    from_migrations = _indexes_from_migrations(tables)
    summaries = yaml.safe_load((ROOT / "aggregations" / "serving.yaml").read_text(encoding="utf-8"))["summaries"]

    expected: dict[str, set[tuple[str, ...]]] = {
        common.V2_PLACE_REGION_TABLE: set(b13.PLACE_REGION_INDEXES),
        common.V2_TAXON_RED_LIST_TABLE: set(b13.TAXON_RED_LIST_INDEXES),
    }
    for base in common.V2_SUMMARY_BY_REGION_BASES:
        spec = b13._by_region_spec(base, summaries[base])
        expected[f"{base}_by_region"] = {tuple(cols) for cols in spec["indexes"]}

    for table in tables:
        assert set(from_migrations[table].values()) == expected[table], table
        assert len(from_migrations[table]) == len(expected[table]), f"{table}: 同じ列の組の索引が重複している"
