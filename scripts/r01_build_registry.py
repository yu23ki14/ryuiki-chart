"""語彙レジストリ（unit / variable / variable_alias / place / place_source_ref /
place_relation / taxon / caveat）を data/db/registry.sqlite として生成する
（docs/plans/PHASE_A.md §A-1、place_relation は Phase B `phase-b/region-scope`、ADR-0022）。

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
と、ファイル由来の `caveat`/`caveat_scope`）だけを作るモード。`place`/`place_relation`/
`taxon`、および `cells.notes`/`place`/`taxon` 由来の `caveat` は作らない（それらのテーブルは
空のまま。`place_relation` は `place` 経由でしか作れない辺なので、`place` を作らない
このモードでは当然に空になる）。
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

## 書き込みの原子性（phase-b/registry-atomic）

「在る」ことと「正しい」ことは区別する。以前は `common.create_registry_db()` が
正規パスの既存ファイルを先に消してから作っていたため、ビルド中またはビルド後の
チェック（`_assert_id_uniqueness` 等）で例外が出ると、前の正しいレジストリは
既に消えており、壊れた（または半端な）ファイルが正規のパスに残った
（`web/scripts/ensure-registry.sh` は「ファイルが在るか」しか見ないので、次の
`db:setup` はその壊れたファイルを使い続ける——独立レビューで実際に踏まれた事故と
同じ形）。

現在は `common.registry_tmp_path()` が作る同じディレクトリの一時ファイル
（`<正規パス>.tmp-<pid>`）にビルドし、全ステップと全チェックが通ってから
`os.replace()`（同一ファイルシステム内なら原子的）で正規パスへ置き換える。
途中で例外が出た場合は一時ファイルを消して正規パスには一切触れず、非0で終わる
（`--files-only` も同じ経路を通る）。

## 「何から作ったか」の指紋（`--check-fresh`）

ビルドが成功すると `registry_build(input_fingerprint, mode)` に1行書く
（指紋は `common.compute_input_fingerprint()`、`mode` は `full`/`files_only`）。
`--check-fresh` は原本DBを一切開かず・何も書かずに、対象レジストリの
`registry_build` が「今の入力」と「期待する mode」に一致するかだけを判定して
0/1 を返す。`web/scripts/ensure-registry.sh` はファイルの有無ではなくこの終了コードで
作り直すかどうかを決める。
"""
import argparse
import os
import pathlib
import sqlite3
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
# column は単一列（str）のほか、複合キー（tuple）も受け付ける（PRIMARY KEY / UNIQUE
# 制約が無い複合キー、例: place_relation の (parent_id, child_id, relation) を
# 専用関数ではなくこの宣言リストで表すため）。
ID_UNIQUENESS_CHECKS = [
    ("unit", "unit_id"),
    ("variable", "variable_id"),
    ("place", "place_id"),
    ("taxon", "taxon_id"),
    ("caveat", "caveat_id"),
    ("place_relation", ("parent_id", "child_id", "relation")),
]


def _assert_id_uniqueness(conn) -> None:
    for table, column in ID_UNIQUENESS_CHECKS:
        # SQLite の count(DISTINCT a, b) は使えない（DISTINCT は集約関数の引数1個にしか
        # 掛からない）ので、複合キーは「SELECT count(*) FROM (SELECT DISTINCT ... FROM t)」
        # の形で組み立てる。単一列でも同じ式で total/distinct とも求まる。
        cols = (column,) if isinstance(column, str) else column
        collist = ", ".join(cols)
        total = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        distinct = conn.execute(
            f"SELECT count(*) FROM (SELECT DISTINCT {collist} FROM {table})"
        ).fetchone()[0]
        if total != distinct:
            label = f"{table}.{collist}" if isinstance(column, str) else f"{table}({collist})"
            raise AssertionError(
                f"{label} が一意ではない: {total:,}行中 distinct は {distinct:,}"
            )
        if isinstance(column, str):
            print(f"  一意性OK: {table}.{collist} ({distinct:,})")
        else:
            print(f"  一意性OK: {table}({collist}) ({distinct:,})")


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
    ("place_relation", "parent_id", "place", "place_id"),
    ("place_relation", "child_id", "place", "place_id"),
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


# place.region_id は place_id 自身のスコープ（<scope>:place:...）と一致していなければ
# ならない（ADR-0022 決定1）。common.region_id_for_scoped_id() を通した値だけが入る
# 設計だが、build_place.py 以外の経路（将来の別モジュール・手動の INSERT）が
# この不変条件を破っていないかを、生成後の DB に対して機械的に検証する。
# 期待値の算出は common.region_id_for_scoped_id() 自体を使う（自前で再実装すると
# 規則が二重管理になるうえ、こちらの方が発行側より緩くなりうる。実際 place_id に
# ':' が無い壊れた行を common.scope_of() は ValueError で止めるが、split(":", 1)[0]
# は黙って ID 全体をスコープ扱いしていた）。
def _assert_region_id_scope_invariant(conn) -> None:
    rows = conn.execute("SELECT place_id, region_id FROM place").fetchall()
    bad = []
    for place_id, region_id in rows:
        expected = common.region_id_for_scoped_id(place_id)
        if region_id != expected:
            bad.append((place_id, region_id, expected))
    if bad:
        sample = "; ".join(f"{p!r}(region_id={r!r}, 期待={e!r})" for p, r, e in bad[:10])
        raise AssertionError(
            f"place.region_id が place_id のスコープと一致しない行が {len(bad):,} 件ある"
            f"（ADR-0022 決定1）。例: {sample}"
        )
    print(f"  region_id 不変条件OK: {len(rows):,} 件（common:->NULL, <region>:-><region>）")


# --check-fresh が「古い」と判定して1を返す理由の1行メッセージは、ensure-registry.sh の
# ログにそのまま出る（「原本を開かない・何も書かない」ので、理由を人間が読める形で
# 残しておかないと再ビルドのトリガーがブラックボックスになる）。
def _check_fresh(target_db: pathlib.Path, expected_mode: str) -> int:
    """`target_db` が「今の入力（コード + registry/ 配下）」と `expected_mode` から
    作ったものと一致するかだけを判定する。原本DB（ryuiki/cells/derived）は一切開かず、
    `target_db` にも何も書かない。一致すれば0、そうでなければ理由を1行 stderr に出し1。
    """
    if not target_db.exists():
        print(f"registry.sqlite が無い: {target_db}", file=sys.stderr)
        return 1

    try:
        conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
        try:
            has_table = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='registry_build'"
            ).fetchone()[0]
            if not has_table:
                print(
                    f"registry_build テーブルが無い（指紋を持たない古いレジストリ）: {target_db}",
                    file=sys.stderr,
                )
                return 1
            row = conn.execute("SELECT input_fingerprint, mode FROM registry_build").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        print(f"registry.sqlite が読めない（壊れている可能性）: {target_db}（{exc}）", file=sys.stderr)
        return 1

    if row is None:
        print(f"registry_build に行が無い: {target_db}", file=sys.stderr)
        return 1

    fingerprint, mode = row
    if mode != expected_mode:
        print(
            f"mode が期待と違う（期待 {expected_mode!r}、実際 {mode!r}）: {target_db}",
            file=sys.stderr,
        )
        return 1

    expected_fingerprint = common.compute_input_fingerprint()
    if fingerprint != expected_fingerprint:
        print(
            "指紋が今の入力と一致しない（コードまたは registry/ 配下が変わった）: "
            f"{target_db}（登録済み {fingerprint}、現在 {expected_fingerprint}）",
            file=sys.stderr,
        )
        return 1

    print(f"✔ 新鮮: {target_db}（mode={mode}, fingerprint={fingerprint}）")
    return 0


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
    parser.add_argument(
        "--check-fresh",
        action="store_true",
        help=(
            "ビルドせず、対象レジストリ（RYUIKI_REGISTRY_DB があればそれ、無ければ "
            "--files-only の有無で決まる既定パス）が今の入力から作ったものかだけを判定する。"
            "原本DBは開かない・何も書かない。一致すれば終了コード0、そうでなければ理由を"
            "1行出して1（web/scripts/ensure-registry.sh が使う）。"
        ),
    )
    args = parser.parse_args()

    steps = FILES_ONLY_STEPS if args.files_only else STEPS
    mode = common.MODE_FILES_ONLY if args.files_only else common.MODE_FULL
    default_db = common.FILES_ONLY_REGISTRY_DB if args.files_only else common.REGISTRY_DB
    env_override = os.environ.get("RYUIKI_REGISTRY_DB")
    target_db = pathlib.Path(env_override) if env_override else default_db

    if args.check_fresh:
        sys.exit(_check_fresh(target_db, mode))

    if args.files_only:
        print(f"▶ --files-only: 原本 DB は開かない（正規の {common.REGISTRY_DB} には触れない）")
        src: dict = {}
    else:
        print(f"▶ 原本を読み取り専用で開く: {common.DB_DIR}")
        src = common.open_sources()

    tmp_db = common.registry_tmp_path(target_db)
    if tmp_db.exists():
        # 同じ PID を使い回した等の極端に稀なケースの後始末。正規ファイルではなく
        # この実行専用の一時ファイルなので、消しても前回の正しいレジストリには影響しない。
        common.remove_sqlite_file(tmp_db)
    print(f"▶ 一時ファイルに作る（成功したら {target_db} へ置き換える）: {tmp_db}")
    conn = common.create_registry_db(tmp_db)

    try:
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
            print(f"完了: {len(totals)} テーブル / {grand_total:,} 行")

            _assert_id_uniqueness(conn)
            _assert_id_references(conn)
            _assert_region_id_scope_invariant(conn)

            fingerprint = common.compute_input_fingerprint()
            conn.execute("DELETE FROM registry_build")
            conn.execute(
                "INSERT INTO registry_build (input_fingerprint, mode) VALUES (?, ?)",
                (fingerprint, mode),
            )
            conn.commit()
            print(f"▶ 指紋(registry_build): {fingerprint}（mode={mode}）")
        except BaseException:
            # ビルド中でもチェック中でも、失敗したら一時ファイルを消して正規パスには
            # 一切触れない（前の正しいレジストリをバイト単位で残す）。
            conn.close()
            common.remove_sqlite_file(tmp_db)
            raise
    finally:
        for c in src.values():
            c.close()

    conn.close()
    os.replace(tmp_db, target_db)
    print(f"▶ 正規パスへ置き換えた: {target_db}")


if __name__ == "__main__":
    main()
