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
（`--files-only` も同じ経路を通る）。`create_registry_db()` の呼び出し自体も含めて
try で囲んであり、スキーマ流し込みの失敗でも一時ファイルは残らない（fix 4）。
起動のたびに、同じ正規パスに残った古い（既定1時間より前の）一時ファイルも
まとめて掃除する（`common.cleanup_stale_tmp_files()`。SIGKILL/OOM 等で
例外ハンドラも通らず残ったものが対象。PID の生死では判定しない——理由は
そのdocstring参照）。

## 「何から作ったか」の指紋（`--check-fresh`）

ビルドが成功すると `registry_build(input_fingerprint, mode)` に1行書く
（指紋は `common.compute_input_fingerprint()`、`mode` は `full`/`files_only`）。
指紋はビルドの最初のステップより**前に1回だけ**計算する（fix 3）。以前はビルド後
（各ステップが完了した後）に計算していたため、ビルド実行中（約4〜9秒）に
`registry/variable.yaml` 等を編集すると、実際にはその場のステップは編集前の内容で
走ったのに、記録される指紋は編集後の内容になり、以後ずっと「新鮮」と誤判定され
続けるレースがあった。

`--check-fresh` は何も書かず、対象レジストリの `registry_build` が「今の入力」と
「期待する mode」に一致するかだけを判定して終了コードを返す。`cells` は一切開かない。
`ryuiki` は `mode='full'` のときだけ、`organism_records` の軽い代理指標を読むために
一瞬だけ開く（次の段落参照。実測で合計約5ms）。`web/scripts/ensure-registry.sh` は
ファイルの有無ではなくこの終了コードで作り直すかどうかを決める。

**`derived.sqlite`/`ryuiki.sqlite` は例外。** `full` モードの指紋には、build_place.py
が実際に読むテーブル（`common.DERIVED_TABLES_READ`）の中身、
`data/processed/taxon_crosswalk.csv` の中身、`ryuiki.organism_records` の軽い代理指標
（行数・最大rowid。grid01 の入力が `derived.mesh_all` から `organism_records` に
変わったための追加。`common.py` の `_hash_organism_records_freshness()` docstring
参照）も混ぜる（fix 2、phase-b/occurrence-registry）。いずれも「読み取り専用だが
再生成・追記すれば値が変わりうる」入力であり、以前は指紋の対象外だったため、
これらだけを更新してもレジストリが「新鮮」のまま固まってしまっていた。ただし
`derived.sqlite`/`ryuiki.sqlite` の**ファイル全体**は開かない・ハッシュしない
（449MB/828MB。読むのは `derived.sqlite` の2テーブルの SELECT 結果と、
`ryuiki.sqlite` の軽い集約2つだけ）。`--files-only` はこの3つのどれも開かない
（`build_place.py`/`build_taxon.py` 自体を呼ばないため。CI が原本無しで動く要件を保つ）。

**終了コードは3種類を区別する**（`web/scripts/ensure-registry.sh` がこれを読む）:

- `EXIT_FRESH`（`0`）: 今の入力から作ったものと一致する。作り直さない。
- `EXIT_STALE`（`10`）: 一致しない（ファイルが無い/古い/壊れている等）。作り直す。
- **それ以外**（Python が起動できない・`--check-fresh` の実行自体が例外で落ちた等）:
  **判定できない**。「古い」と誤読して作り直しに進むと、原因（例: PyYAML 未インストール）
  が rebuild 側でも再現してそちらも落ち、`db:setup` 全体が止まる退行を生む
  （実際に踏まれた事故。以前は本ファイルがモジュール読み込み時に無条件で PyYAML の
  有無を確認しており、`--check-fresh` もこの分岐に巻き込まれて「非0」を返していた）。
  そのため `--check-fresh` の実装は **PyYAML を一切 import しない**（yaml が要るのは
  実際にビルドする4モジュールのうちの3つだけで、`--check-fresh` はそれらを import しない。
  `_load_build_steps()` 参照）。`ensure-registry.sh` 側は「判定できない」場合、レジストリが
  在るなら警告を出して今のファイルを使い続け（以前の挙動への退避）、無いなら作る。
"""
import argparse
import os
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIREMENTS_TXT = ROOT / "requirements.txt"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

# `registry.common` は sqlite3/hashlib/os/re/pathlib/time だけに依存する（PyYAML 不要）。
# `--check-fresh` はこのモジュールだけで完結するので、ここで import してよい
# （fix 1: PyYAML の無い環境でも --check-fresh が動く条件）。
from registry import common

# 実行順序に依存関係は無い（PHASE_A.md §3: A-2/A-3/A-4/A-5 は独立）。
# 並べ方はレポートの読みやすさのためだけ。
#
# `build_unit_variable`/`build_place`/`build_taxon`/`build_caveat` は PyYAML に依存する
# （registry/*.yaml を読むため）。モジュール読み込み時に無条件で import すると
# PyYAML の無い環境では `--check-fresh` まで巻き添えで起動できなくなる（fix 1 の
# 退行そのもの）ため、実際にビルドするとき（`--check-fresh` ではないとき）だけ
# `_load_build_steps()` が遅延 import して、この2つの module-level 変数を埋める。
STEPS = None
FILES_ONLY_STEPS = None


def _require_pyyaml() -> None:
    """実際にビルドするときだけ PyYAML の有無を確認する（分かりやすいエラーのため。
    `--check-fresh` はこの関数を呼ばない）。"""
    try:
        import yaml  # noqa: F401
    except ImportError:
        sys.exit(
            "PyYAML が見つからない。レジストリビルドの依存を先に入れる:\n"
            f"  pip install -r {REQUIREMENTS_TXT}\n"
            "（.venv を使っている場合は .venv/bin/pip install -r requirements.txt）"
        )


def _load_build_steps() -> None:
    """STEPS / FILES_ONLY_STEPS を実際にビルドする時点で遅延構築する（fix 1）。

    既に値が入っている変数は上書きしない（テストが
    `monkeypatch.setattr(r01, "FILES_ONLY_STEPS", [...])` でこのリストを差し替えて
    ビルド失敗ケースを作るため。二重に import しても実害は無いが、テストの
    差し替えを踏みつぶさないためのガード）。
    """
    global STEPS, FILES_ONLY_STEPS
    if STEPS is not None and FILES_ONLY_STEPS is not None:
        return

    from registry.build_unit_variable import build as build_unit_variable
    from registry.build_place import build as build_place
    from registry.build_taxon import build as build_taxon
    from registry.build_caveat import build as build_caveat, build_from_files as build_caveat_from_files

    if STEPS is None:
        STEPS = [
            ("unit/variable/variable_alias (A-2)", build_unit_variable),
            ("place/place_source_ref (A-3)", build_place),
            ("taxon (A-4)", build_taxon),
            ("caveat (A-5)", build_caveat),
        ]
    if FILES_ONLY_STEPS is None:
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
    # Phase B `phase-b/zone-slice` のコードレビュー対応で追加。実データで
    # 全 source_id について重複0件を確認済み（4件の source_id: sites.site_id/
    # sites.zone/watershed_meta.watershed_id/organism_records.lat_lon）なので、
    # sites.zone に限定せず汎用にここへ入れる。
    ("place_source_ref", ("place_id", "source_id")),
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


# ゾーン関連の不変条件（Phase B `phase-b/zone-slice` のコードレビュー対応で b05 から
# 移設。「レジストリの不変条件」と「射影〔b05〕の前提」を分ける——書き手
# scripts/registry/build_place.py の出力をここで1回だけ保証すれば、消費側
# （b05_project_v1.py）は結果を信用してよい。fraction=1.0 のような「射影固有の
# 前提」（v1 を非加重で再現するという b05 の設計判断であり、レジストリ全体が
# 守るべき不変条件ではない）はここに置かず b05 側に残す。docs/plans/
# PHASE_B_FACT_SLICE.md D11 参照。
def _assert_zone_relation_child_is_single_valued(conn) -> None:
    """地点（`place_relation.child_id`）が、ゾーン（`place_source_ref
    (source_id='sites.zone')` を持つ place を `parent_id` とする `'within'`
    辺）を高々1本しか持たないことを検証する。v1 の `sites.zone` は単一列
    であり、地点は必ず1つのゾーンにしか属さないため。
    """
    dup = conn.execute(
        """
        SELECT pr.child_id, COUNT(*) AS n
        FROM place_relation pr
        JOIN place_source_ref zref
          ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
        WHERE pr.relation = 'within'
        GROUP BY pr.child_id
        HAVING n > 1
        """
    ).fetchall()
    if dup:
        raise AssertionError(
            f"地点がゾーンへの 'within' 辺を複数持っている（child_id, 本数）: {dup[:10]}"
        )
    n = conn.execute(
        """
        SELECT COUNT(*) FROM place_relation pr
        JOIN place_source_ref zref
          ON zref.place_id = pr.parent_id AND zref.source_id = 'sites.zone'
        WHERE pr.relation = 'within'
        """
    ).fetchone()[0]
    print(f"  地点→ゾーンの辺は単射OK: {n:,} 件")


def _assert_zone_external_key_is_numeric(conn) -> None:
    """`place_source_ref(source_id='sites.zone').external_key`（ゾーン番号）が
    数字だけの文字列であることを検証する。消費側（`b05_project_v1.py`）が
    `CAST(... AS INT)` で整数に変換するため、非数値文字列（例: `'z1'`）が
    紛れ込むと黙って `0` になる。
    """
    bad = conn.execute(
        "SELECT place_id, external_key FROM place_source_ref "
        "WHERE source_id = 'sites.zone' "
        "AND (external_key IS NULL OR external_key = '' OR external_key GLOB '*[^0-9]*')"
    ).fetchall()
    if bad:
        raise AssertionError(
            f"sites.zone の external_key が数字だけの文字列でない行がある: {bad[:10]}"
        )
    n = conn.execute(
        "SELECT COUNT(*) FROM place_source_ref WHERE source_id = 'sites.zone'"
    ).fetchone()[0]
    print(f"  sites.zone の external_key 数値形式OK: {n:,} 件")


# --check-fresh の終了コード（web/scripts/ensure-registry.sh が読む。fix 1）。
# 0 でも EXIT_STALE でもない終了コード（Python が起動できない・--check-fresh 自体が
# 例外で落ちた 等）は「判定できない」を表す——このモジュールはそれ用の定数を持たない
# （`sys.exit(0/EXIT_STALE)` 以外の終了は「意図的な第3の状態」ではなく「本当に失敗した」
# ことの表れなので、あえて名前を付けて正常系のように扱わない）。
EXIT_FRESH = 0
EXIT_STALE = 10


# --check-fresh が「古い」と判定して EXIT_STALE を返す理由の1行メッセージは、
# ensure-registry.sh のログにそのまま出る（登録先には何も書かないので、理由を
# 人間が読める形で残しておかないと再ビルドのトリガーがブラックボックスになる）。
def _check_fresh(target_db: pathlib.Path, expected_mode: str) -> int:
    """`target_db` が「今の入力（コード + registry/ 配下 + [full モードのみ]
    derived.sqlite の一部テーブル・taxon_crosswalk.csv・ryuiki.organism_records の
    軽い代理指標）」と `expected_mode` から作ったものと一致するかだけを判定する。
    `cells` は一切開かない。`ryuiki` は full モードのときだけ軽い集約2つのために
    一瞬だけ開く（実測で合計約5ms。`common._hash_organism_records_freshness()`
    docstring 参照）。`target_db` にも何も書かない。一致すれば `EXIT_FRESH`、
    そうでなければ理由を1行 stderr に出し `EXIT_STALE`。

    PyYAML を import しない（fix 1）。このため呼び出し元は `_load_build_steps()`
    （PyYAML 依存の4モジュールを import する）より前に、この関数だけを呼べる。
    """
    if not target_db.exists():
        print(f"registry.sqlite が無い: {target_db}", file=sys.stderr)
        return EXIT_STALE

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
                return EXIT_STALE
            row = conn.execute("SELECT input_fingerprint, mode FROM registry_build").fetchone()
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        print(f"registry.sqlite が読めない（壊れている可能性）: {target_db}（{exc}）", file=sys.stderr)
        return EXIT_STALE

    if row is None:
        print(f"registry_build に行が無い: {target_db}", file=sys.stderr)
        return EXIT_STALE

    fingerprint, mode = row
    if mode != expected_mode:
        print(
            f"mode が期待と違う（期待 {expected_mode!r}、実際 {mode!r}）: {target_db}",
            file=sys.stderr,
        )
        return EXIT_STALE

    expected_fingerprint = common.compute_input_fingerprint(mode=expected_mode)
    if fingerprint != expected_fingerprint:
        print(
            "指紋が今の入力と一致しない（コード・registry/ 配下・"
            "[full モードのみ] derived.sqlite/taxon_crosswalk.csv/"
            "ryuiki.organism_records が変わった）: "
            f"{target_db}（登録済み {fingerprint}、現在 {expected_fingerprint}）",
            file=sys.stderr,
        )
        return EXIT_STALE

    print(f"✔ 新鮮: {target_db}（mode={mode}, fingerprint={fingerprint}）")
    return EXIT_FRESH


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
            "cells は開かない（full モードでは derived.sqlite の一部テーブルと "
            "taxon_crosswalk.csv、ryuiki.organism_records の軽い代理指標だけ読む。"
            "PyYAML は import しない）。一致すれば終了コード "
            f"{EXIT_FRESH}、古ければ{EXIT_STALE}、判定できなければそれ以外"
            "（web/scripts/ensure-registry.sh が使う）。"
        ),
    )
    args = parser.parse_args()

    mode = common.MODE_FILES_ONLY if args.files_only else common.MODE_FULL
    default_db = common.FILES_ONLY_REGISTRY_DB if args.files_only else common.REGISTRY_DB
    env_override = os.environ.get("RYUIKI_REGISTRY_DB")
    target_db = pathlib.Path(env_override) if env_override else default_db

    if args.check_fresh:
        sys.exit(_check_fresh(target_db, mode))

    # ここから下はビルド実行時だけ通る経路（PyYAML が要る）。
    _require_pyyaml()
    _load_build_steps()
    steps = FILES_ONLY_STEPS if args.files_only else STEPS

    # 起動のたびに、同じ正規パスに残った「十分古い」一時ファイル（他 PID・
    # SIGKILL/OOM 由来）を掃除する（fix 4）。--check-fresh は何も書かないので
    # この呼び出しより前で return 済み。
    common.cleanup_stale_tmp_files(target_db)

    # 指紋はここ（最初のステップより前）で1回だけ計算する（fix 3）。ビルド中に
    # 入力が書き換わっても、記録される指紋は「ビルドが実際に使った内容」のまま
    # であることを保証するため。
    fingerprint = common.compute_input_fingerprint(mode=mode)

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

    conn = None
    try:
        # create_registry_db() 自体（スキーマ流し込み）の失敗も含めて try で囲む
        # （fix 4）。以前はこの呼び出しが try の外にあり、ここで例外が出ると
        # 一時ファイルの掃除にも src コネクションの close にも到達しなかった。
        conn = common.create_registry_db(tmp_db)

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
        _assert_zone_relation_child_is_single_valued(conn)
        _assert_zone_external_key_is_numeric(conn)

        conn.execute("DELETE FROM registry_build")
        conn.execute(
            "INSERT INTO registry_build (input_fingerprint, mode) VALUES (?, ?)",
            (fingerprint, mode),
        )
        conn.commit()
        print(f"▶ 指紋(registry_build): {fingerprint}（mode={mode}, ビルド開始前に計算）")
    except BaseException:
        # ビルド中でもチェック中でも、失敗したら一時ファイルを消して正規パスには
        # 一切触れない（前の正しいレジストリをバイト単位で残す）。
        if conn is not None:
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
