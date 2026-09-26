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
