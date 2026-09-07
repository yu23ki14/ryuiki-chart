"""語彙レジストリ（unit / variable / variable_alias / place / place_source_ref /
taxon / caveat）を data/db/registry.sqlite として生成する（docs/plans/PHASE_A.md §A-1）。

    .venv/bin/python3 scripts/r01_build_registry.py

このファイルは薄いオーケストレータで、実際にデータを作るのは
scripts/registry/build_unit_variable.py（A-2）/ build_place.py（A-3）/
build_taxon.py（A-4）/ build_caveat.py（A-5）。並行作業で衝突しないよう
モジュールを分けてあるので、ここにロジックを足さない。

原本 data/db/ryuiki.sqlite / cells.sqlite / derived.sqlite は読み取り専用で開き、
一切書き換えない。registry.sqlite は毎回ゼロから作り直す
（レジストリの正はリポジトリの registry/ 配下と、これらの読み取り専用の原本であり、
D1 は「捨てて再構築できる」もの — ADR-0001）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIREMENTS_TXT = ROOT / "requirements.txt"

try:
    import yaml  # noqa: F401  (build_*.py が実際に使う。ここでは有無だけ確認する)
except ImportError:
    sys.exit(
        "PyYAML が見つからない。レジストリビルドの依存を先に入れる:\n"
        f"  pip install -r {REQUIREMENTS_TXT}\n"
        "（.venv を使っている場合は .venv/bin/pip install -r requirements.txt）"
    )

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from registry import common
from registry.build_unit_variable import build as build_unit_variable
from registry.build_place import build as build_place
from registry.build_taxon import build as build_taxon
from registry.build_caveat import build as build_caveat

# 実行順序に依存関係は無い（PHASE_A.md §3: A-2/A-3/A-4/A-5 は独立）。
# 並べ方はレポートの読みやすさのためだけ。
STEPS = [
    ("unit/variable/variable_alias (A-2)", build_unit_variable),
    ("place/place_source_ref (A-3)", build_place),
    ("taxon (A-4)", build_taxon),
    ("caveat (A-5)", build_caveat),
]


# PRIMARY KEY 列は SQLite が挿入時点で一意性を強制する（列の型が TEXT でも rowid alias
# ではない PK には暗黙の UNIQUE index が張られる）ので、ここでの assert は理論上
# 冗長ではある。それでも「4モジュールが同じ DB に同居したときの主キー衝突」を
# ビルドの最後に明示的に検証しておく（統合作業の受け入れ基準）。
ID_UNIQUENESS_CHECKS = [
    ("unit", "unit_id"),
    ("variable", "variable_id"),
    ("place", "place_id"),
    ("taxon", "taxon_id"),
    ("caveat", "caveat_id"),
]


def _assert_id_uniqueness(conn) -> None:
    for table, column in ID_UNIQUENESS_CHECKS:
        total = conn.execute(f"SELECT count({column}) FROM {table}").fetchone()[0]
        distinct = conn.execute(f"SELECT count(DISTINCT {column}) FROM {table}").fetchone()[0]
        if total != distinct:
            raise AssertionError(
                f"{table}.{column} が一意ではない: {total:,}行中 distinct は {distinct:,}"
            )
        print(f"  一意性OK: {table}.{column} ({distinct:,})")


def main() -> None:
    print(f"▶ 原本を読み取り専用で開く: {common.DB_DIR}")
    src = common.open_sources()
    print(f"▶ registry.sqlite を作り直す: {common.REGISTRY_DB}")
    conn = common.create_registry_db()

    try:
        totals: dict[str, int] = {}
        for label, fn in STEPS:
            print(f"▶ {label}")
            counts = fn(conn, src) or {}
            conn.commit()
            if not counts:
                print("  (0行。まだスタブ)")
            for table, n in counts.items():
                totals[table] = totals.get(table, 0) + n
                print(f"  {table}: {n:,} 行")

        grand_total = sum(totals.values())
        print(f"完了: {len(totals)} テーブル / {grand_total:,} 行 -> {common.REGISTRY_DB}")

        _assert_id_uniqueness(conn)
    finally:
        conn.close()
        for c in src.values():
            c.close()


if __name__ == "__main__":
    main()
