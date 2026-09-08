"""語彙レジストリ（unit / variable / variable_alias / place / place_source_ref /
taxon / caveat）を data/db/registry.sqlite として生成する（docs/plans/PHASE_A.md §A-1）。

    .venv/bin/python3 scripts/r01_build_registry.py
    .venv/bin/python3 scripts/r01_build_registry.py --files-only

このファイルは薄いオーケストレータで、実際にデータを作るのは
scripts/registry/build_unit_variable.py（A-2）/ build_place.py（A-3）/
build_taxon.py（A-4）/ build_caveat.py（A-5）。並行作業で衝突しないよう
モジュールを分けてあるので、ここにロジックを足さない。

原本 data/db/ryuiki.sqlite / cells.sqlite / derived.sqlite は読み取り専用で開き、
一切書き換えない。registry.sqlite は毎回ゼロから作り直す
（レジストリの正はリポジトリの registry/ 配下と、これらの読み取り専用の原本であり、
D1 は「捨てて再構築できる」もの — ADR-0001）。

## `--files-only`（docs/plans/PHASE_B_INTAKE.md #7、CI 用）

原本 DB（`ryuiki`/`cells`/`derived`）を一切開かず、`registry/` 配下の手書きファイルと
`build_caveat.py` の Python 定数だけから作れる部分（`unit`/`variable`/`variable_alias`
と、ファイル由来の `caveat`/`caveat_scope`）だけを作るモード。`place`/`taxon`、および
`cells.notes`/`place`/`taxon` 由来の `caveat` は作らない（それらのテーブルは空のまま）。
CI がこのモードで registry.sqlite を作り、`web/scripts/build-registry-ts.mjs` で
`generated.ts`/`generated-client.ts` を再生成して `git diff --exit-code` することで、
レジストリ（手書きファイル）と生成物のずれを検出する。原本 DB が存在しない環境
（CI ランナー）でも動くことが要件。

**書き込み先は既定で正規の `data/db/registry.sqlite` とは別のファイル**
（`common.FILES_ONLY_REGISTRY_DB` = `data/db/registry_files_only.sqlite`）。
`--files-only` は place/taxon/cells由来caveatを持たないスタブなので、正規の
registry.sqlite を上書きすると完全なレジストリ（place 4,960/taxon 41,444/
caveat 221 件）が154 alias だけのスタブに黙って壊れて消える
（独立レビューで実際に踏まれた事故。`web/scripts/ensure-registry.sh` は
「ファイルが無いとき」しか作り直さないので、壊れたことに誰も気づけない）。
書き込み先は `RYUIKI_REGISTRY_DB` 環境変数で明示的に上書きできる
（`--files-only` の有無に関わらず。CI はこれで files-only 用のパスを指定する。
`web/scripts/build-registry-ts.mjs` / `web/src/lib/registry/generated.test.ts` も
同じ環境変数を見るので、CI では3箇所が同じファイルを指す）。
"""
import argparse
import os
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
from registry.build_caveat import build as build_caveat, build_from_files as build_caveat_from_files

# 実行順序に依存関係は無い（PHASE_A.md §3: A-2/A-3/A-4/A-5 は独立）。
# 並べ方はレポートの読みやすさのためだけ。
STEPS = [
    ("unit/variable/variable_alias (A-2)", build_unit_variable),
    ("place/place_source_ref (A-3)", build_place),
    ("taxon (A-4)", build_taxon),
    ("caveat (A-5)", build_caveat),
]

# --files-only: 原本 DB を開かないので、src を受け取らない関数だけを実行する。
FILES_ONLY_STEPS = [
    ("unit/variable/variable_alias (A-2)", build_unit_variable),
    ("caveat, ファイル由来のみ (A-5, --files-only)", lambda conn, _src: build_caveat_from_files(conn)),
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


# 外部キーが親テーブルの主キーを指しているかの検証（/simplify 指摘A: 同型の参照整合性
# チェックが web/src/lib/registry/generated.test.ts に3つ手書きで並び、しかも
# place_source_ref.place_id -> place.place_id は1つも検査されていなかった。生成物
# （generated.ts/generated-client.ts）は registry.sqlite から機械的に作るので、
# ここで DB を検証すれば TS 側の個別テストは不要になる）。
# NULL の外部キーは「未設定」であって「壊れている」ではないので検査対象から外す
# （例: variable.unit_id は値の無い指標があるため NULL 可）。
ID_REFERENCE_CHECKS = [
    # (子テーブル, 外部キー列, 親テーブル, 主キー列)
    ("variable", "unit_id", "unit", "unit_id"),
    ("variable_alias", "unit_id", "unit", "unit_id"),
    ("variable_alias", "variable_id", "variable", "variable_id"),
    ("caveat_scope", "caveat_id", "caveat", "caveat_id"),
    ("place_source_ref", "place_id", "place", "place_id"),
]


def _assert_id_references(conn) -> None:
    for child, fk_col, parent, pk_col in ID_REFERENCE_CHECKS:
        missing = conn.execute(
            f"SELECT count(*) FROM {child} "
            f"WHERE {fk_col} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} WHERE {parent}.{pk_col} = {child}.{fk_col})"
        ).fetchone()[0]
        if missing:
            raise AssertionError(
                f"{child}.{fk_col} が {parent}.{pk_col} に無い値を参照している行が "
                f"{missing:,} 件ある"
            )
        print(f"  参照整合性OK: {child}.{fk_col} -> {parent}.{pk_col}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--files-only",
        action="store_true",
        help=(
            "原本 DB（ryuiki/cells/derived）を開かず、registry/ 配下の手書きファイルと "
            "build_caveat.py の Python 定数だけから unit/variable/variable_alias と "
            "ファイル由来の caveat/caveat_scope だけを作る（CI 用）。書き込み先は既定で "
            f"正規の {common.REGISTRY_DB.name} とは別ファイル "
            f"（{common.FILES_ONLY_REGISTRY_DB.name}）にする。RYUIKI_REGISTRY_DB で上書き可。"
        ),
    )
    args = parser.parse_args()

    steps = FILES_ONLY_STEPS if args.files_only else STEPS
    default_db = common.FILES_ONLY_REGISTRY_DB if args.files_only else common.REGISTRY_DB
    env_override = os.environ.get("RYUIKI_REGISTRY_DB")
    target_db = pathlib.Path(env_override) if env_override else default_db

    if args.files_only:
        print(f"▶ --files-only: 原本 DB は開かない（正規の {common.REGISTRY_DB} には触れない）")
        src: dict = {}
    else:
        print(f"▶ 原本を読み取り専用で開く: {common.DB_DIR}")
        src = common.open_sources()
    print(f"▶ registry.sqlite を作り直す: {target_db}")
    conn = common.create_registry_db(target_db)

    try:
        totals: dict[str, int] = {}
        for label, fn in steps:
            print(f"▶ {label}")
            counts = fn(conn, src) or {}
            conn.commit()
            if not counts:
                print("  (0行。まだスタブ)")
            for table, n in counts.items():
                totals[table] = totals.get(table, 0) + n
                print(f"  {table}: {n:,} 行")

        grand_total = sum(totals.values())
        print(f"完了: {len(totals)} テーブル / {grand_total:,} 行 -> {target_db}")

        _assert_id_uniqueness(conn)
        _assert_id_references(conn)
    finally:
        conn.close()
        for c in src.values():
            c.close()


if __name__ == "__main__":
    main()
