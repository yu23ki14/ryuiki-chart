"""b03/b04/b05/b10（Phase B ファクトとキューブ、および文書/品質ワークフローの
v1射影）が共有する薄い土台。

- 読み取り専用オープンと YAML 読み込みは `scripts/reconcile/common.open_readonly`/
  `load_yaml` をそのまま使う（同じ規約を2箇所に書かない。既に b01/b02 が
  使っている実装。`scripts/migrate/period.py` はここから `load_yaml` を引く）。
- 出力 sqlite は毎回ゼロから作り直す（`fresh_sqlite`）。前回実行の残骸（WAL/SHM
  側車ファイルを含む）が残ったまま次の実行が古い行を引きずる事故を避ける。
  `fresh_sqlite` は書き込み先が読み取り専用の原本そのものでないことも検査する
  （`reject_protected_source_db` 参照）。**b03/b04 は `--out` を `sqlite3.connect`
  で直接開き `fresh_sqlite` を経由しない**ため、それぞれの `main()` が引数
  パース直後に同じ検査を個別に呼ぶ。
- 実行時間とテーブルごとの行数を `[12.3s] ラベル / N行` の形で出す（`timed_step`）。
- `AVG()`/`SUM()`（b04・b05・b10）または `FULL OUTER JOIN`（`assert_grouped_totals_match`
  経由。b07・b08）を使うスクリプトは、どちらも SQLite 3.43 以降が前提
  （`AVG()`/`SUM()` は加算アルゴリズムの正しさ、`FULL OUTER JOIN` は機能自体の
  対応のため——3.39で足りる `FULL OUTER JOIN` 単体の最小版ではなく、他の
  スクリプトと同じ3.43に揃える）。`require_sqlite_version()` を**各スクリプトの
  構築関数の先頭**で呼ぶ（モジュール読み込み時点ではない——
  `require_sqlite_version` の docstring 参照）。
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import sqlite3
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPTS = ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reconcile.common import load_yaml, open_readonly  # noqa: E402,F401  (b03/b04/b05/b10 から re-export)

# b04 の observation_agg / b05 の射影が `built_from` / `spec_version` に書く定数。
# バージョンを上げるのはこのパッケージの変換ロジックそのものを変えたとき
# （キーの構成や集計方法が変わる＝過去に作った observation_agg と比較できなくなるとき）。
SPEC_VERSION = "phase-b-fact-slice/v1"

# SQLite 3.43 未満では2つの理由でパイプラインが壊れる: (1) AVG()/SUM() の
# 加算アルゴリズムが素朴な左→右加算に落ち、平均が黙って壊れる（b04・b05・
# b10）。(2) FULL OUTER JOIN（`assert_grouped_totals_match` が使う。SQLite
# 3.39 で追加）自体が使えず `sqlite3.OperationalError` で落ちる（b07・b08）。
# 元は b04 だけに書かれていたが、他のスクリプトでも同じ「3.43 以降が前提」
# というリスクがあるため共通ヘルパへ切り出した。3.39 で足りる FULL OUTER
# JOIN 単体の最小版ではなく、AVG()/SUM() の要件に合わせて 3.43 で統一する
# （パイプライン全体を1つの基準で揃える）。バージョン・件数の実測は
# docs/plans/PHASE_B_DOCUMENTS.md §2 の1箇所にまとめてある（ここでは繰り返さない）。
MIN_SQLITE_VERSION = (3, 43, 0)


def require_sqlite_version(min_version: tuple[int, int, int] = MIN_SQLITE_VERSION) -> None:
    """`sqlite3.sqlite_version_info` が `min_version` 未満なら `SystemExit` で止まる。

    **呼び出し側（b04/b05/b07/b08/b10）は各スクリプトの構築・射影関数の先頭
    （`build_cube`/`build_projections`/`build_documents_projection`/
    `build_org_norm_projection`/`build_occurrence_cube_projections`/
    `build_all_projections`）でこれを呼ぶこと。モジュール読み込み時点
    （トップレベル）では呼ばない。** 古い SQLite の環境で `import` した瞬間に
    `SystemExit` が飛ぶと、`pytest` は複数のテストファイルを import してから
    収集するため、無関係な1ファイルの import 失敗がスイート全体の収集を
    止めてしまう（守りたい状況（古い環境）でこそ壊れる形だった——コード
    レビュー指摘。実測は `docs/plans/PHASE_B_DOCUMENTS.md` §2 参照）。関数の
    先頭で呼べば、CLI からの実行でも関数の直接呼び出しでも同じガードが効き、
    `import` 自体は安全になる。

    `assert` にしない理由は `python -O`/`PYTHONOPTIMIZE=1` では `assert` が
    丸ごと消え、まさにこのガードが要る場面で無効化されてしまうため
    （`scripts/tests/test_b04_build_cube.py::test_min_sqlite_version_guard_is_systemexit_not_assert`
    参照）。
    """
    if sqlite3.sqlite_version_info < min_version:
        raise SystemExit(
            f"sqlite3（Python 同梱、バージョン {sqlite3.sqlite_version}）が古すぎる。"
            f"SQLite {'.'.join(map(str, min_version))} 以降が必要——それより前は "
            "AVG()/SUM() が Kahan-Babuška-Neumaier 加算ではなく素朴な左→右加算に落ちて"
            "平均値が黙って変わる（b04/b05/b10）、または FULL OUTER JOIN 自体が使えず"
            "OperationalError で落ちる（b07/b08）。実測は docs/plans/PHASE_B_DOCUMENTS.md "
            "§2 参照。sqlite3 CLI のバージョンではなく、この Python が import する "
            "sqlite3 モジュール（標準ライブラリに静的リンクされた版）のバージョンを見ている。"
        )


class MigrationError(Exception):
    """b03/b04/b05/b10 が「黙って捨てず・黙って推測せず」止まるときに投げる例外。

    データの中身に起因する想定外（alias/place が解決できない、value_grain と
    period_grain が宣言されていない食い違い方をしている等）はすべてこれを使う。
    プログラムのバグ（引数の誤り等）は通常の例外のままにして区別する。
    """


# `reject_protected_source_db` が保護する読み取り専用の原本（`--out` に誤って
# これらのパスを渡されたときに拒む）。
_PROTECTED_SOURCE_DB_NAMES = ("ryuiki.sqlite", "cells.sqlite", "derived.sqlite")


def reject_protected_source_db(path: pathlib.Path) -> None:
    """`path`（書き込み先として使うつもりのパス）が `data/db/ryuiki.sqlite`/
    `cells.sqlite`/`derived.sqlite`（symlink 越しも含む）と同じ実体を指して
    いたら `MigrationError` で止まる。

    **この検査は書き込み先のパスに対する検査であり、読み取り専用で開く経路
    （`attach_readonly`・`open_readonly`）は対象外**（読み取り専用で開くこと
    自体は原本を傷つけない）。`fresh_sqlite` は内部でこれを呼ぶので、`--out`
    が `fresh_sqlite` を経由するスクリプトは自動的に保護される。**b03/b04 は
    `--out` を `sqlite3.connect` で直接開き `fresh_sqlite` を経由しないため、
    それぞれの `main()` が引数パース直後にこれを個別に呼ぶ**（コードレビュー
    指摘: `fresh_sqlite` 経由だけでは b03/b04 の `--out` が保護されておらず、
    原本に直接書き込む事故が起こりうる状態だった）。

    worktree ではこれらは symlink（CLAUDE.md「worktree の運用」）なので、
    パス文字列の比較ではなく `os.path.realpath`（symlink を解決した実パス）
    で比べる。ファイルが存在しない場合でも `realpath` は正規化したパスを返す
    ため、原本がまだ無い環境（CI 等）でも判定できる。
    """
    resolved = os.path.realpath(str(path))
    for name in _PROTECTED_SOURCE_DB_NAMES:
        protected = os.path.realpath(str(ROOT / "data" / "db" / name))
        if resolved == protected:
            raise MigrationError(
                f"{path} は読み取り専用の原本（{protected}）と同じ実体を指している。"
                "書き込み先（--out）に原本のパスを渡していないか確認すること。"
            )


@contextlib.contextmanager
def timed_step(label: str):
    """`with timed_step("観測を読み込む") as info: ... info["n"] = 件数` の形で使う。

    ブロックを抜けるときに `[12.3s] label / N件` を標準出力に出す
    （`scripts/b01_derived_baseline.py` が完了時に件数を出す流儀を、
    ステップ単位に広げたもの）。`info["n"]` を設定しなければ件数無しで出す。
    """
    t0 = time.perf_counter()
    info: dict = {"n": None}
    try:
        yield info
    finally:
        elapsed = time.perf_counter() - t0
        n = info.get("n")
        suffix = f" / {n:,}件" if n is not None else ""
        print(f"[{elapsed:.1f}s] {label}{suffix}")


def fresh_sqlite(path) -> sqlite3.Connection:
    """`path` の出力 sqlite を毎回作り直して書き込み用に開く。

    既存ファイルと WAL/SHM 側車ファイルを先に消してから作る。前回実行の残骸が
    残ったままだと、b03〜b05 を2回実行してのバイト一致確認（受け入れ条件2）が
    「たまたま同じ内容が残っていただけ」で偽陽性になりうるため、必ずゼロから作る。
    `uri=True` で開く（ATTACH で読み取り専用 DB を `file:...?mode=ro` として
    付けられるようにする。`open_attached_readonly` 参照）。

    **`path` が読み取り専用の原本そのものを指していたら、消す前に
    `MigrationError` で拒む**（`reject_protected_source_db` 参照。`--out` に
    原本のパスを誤って渡すと、以降の `unlink()` が100MB超で再生成できない
    原本を消してから失敗する——コードレビュー指摘）。
    """
    p = pathlib.Path(path)
    reject_protected_source_db(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-shm", "-wal"):
        sidecar = pathlib.Path(str(p) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    conn = sqlite3.connect(f"file:{p}", uri=True)
    conn.execute("PRAGMA journal_mode=DELETE")  # 出力ファイルを単一ファイルのまま完結させる
    return conn


def _staging_table_name(table: str) -> str:
    return f"{table}__building"


@contextlib.contextmanager
def staged_table(conn: sqlite3.Connection, table: str, create_sql: str, params=()):
    """`table`（`observation`/`observation_agg` のような本番テーブル）を
    「作業用テーブルに作る → 呼び出し側が全部挿入・検証する → 本番名に差し替える」
    の手順で作り直す（A-1）。

    以前の b03/b04 は `replace_table`（DROP+CREATE、本番名に対して実行）を検証
    より先に呼んでいた。`dest.commit()` を出典ごと・ステップごとに呼んでいた
    ため、検証に失敗しても、それより前に呼ばれた `commit()` の分だけは既に
    確定してしまっており、本番テーブルは新しい（まだ全部の検証を通っていない）
    内容に差し替わっていた。ここでは DDL・DML を**作業用の別名**
    （`f"{table}__building"`）に対してだけ行い、本番名（`table`）に触る DDL は
    `with` ブロックが例外なく終わったとき（＝全検証を通過したとき）にしか
    実行しない。

    **明示的に `commit()`/`rollback()` を呼ぶ（DDL が暗黙にコミットすることに
    頼らない）。** Python 3.6 以降の `sqlite3` モジュールは、DML（INSERT 等）の
    直前にだけ暗黙のトランザクションを開始し、DDL（CREATE/DROP/ALTER）の
    前に自動でコミットすることは**しない**（それより前の Python の挙動だった。
    実測: `executemany` の後に `DROP TABLE` するだけでは、そのままプロセスを
    `close()` すると `DROP` 自体も取り消される——保留中の DML トランザクションに
    DDL が相乗りするだけで、コミットされないため）。そのためここでは各ステップ
    （作業用テーブルの準備・失敗時の破棄・成功時の差し替え）の前後で
    `conn.commit()`/`conn.rollback()` を明示的に呼び、呼び出し側が `with`
    ブロックの中でコミットしたかどうかに依存しない。

    使い方:

        with common.staged_table(conn, "observation", CREATE_SQL) as staging:
            conn.executemany(f'INSERT INTO "{staging}" ...', rows)
            ... # 検証。失敗したら例外を投げる
        # ここまで来たら差し替え済み（本番テーブル名 "observation" で読める）

    - `with` ブロックで例外（検証失敗を含む）が起きたら、`conn.rollback()`
      （呼び出し側が積んだ未コミットの INSERT 等を破棄する）→ 作業用テーブルを
      `DROP` → `conn.commit()`（`DROP` を確定させる）の順で片付けてから、同じ
      例外をそのまま再送出する。**本番テーブルには一切触れない。**
    - ブロックが正常に終わったら、`conn.commit()`（呼び出し側が積んだ最後の
      未コミット分を確定させる）のあと、`DROP TABLE IF EXISTS`（本番テーブルを
      消す）と `ALTER TABLE ... RENAME TO`（作業用テーブルを本番名にする）を
      **明示の `BEGIN`〜`COMMIT` で1つのトランザクションにする**（コードレビュー
      指摘。SQLite は DDL をトランザクションに入れられる）。`conn.commit()` の
      直後は開いているトランザクションが無いため、この2つの DDL を裸のまま
      実行すると**それぞれが独立に即座確定する別々の操作**になる——`DROP` が
      確定した直後（`RENAME` の前）にプロセスが死ぬと（Ctrl-C・SIGKILL・OOM・
      停電）、本番テーブルは消えたまま戻らず、次回実行は残った作業用テーブルを
      起動時に `DROP` するため、前回の正しいデータが失われる（レビューで
      `os._exit()` を使って再現・修正を確認済み）。明示のトランザクションに
      包めば、この間にプロセスが死んでもコミットされておらず、再起動後の
      SQLite が未コミットの変更を自動的に巻き戻す（`DROP` も無かったことになり、
      本番テーブルは元のまま）。`with` ブロックの中で例外が起きた場合と同様、
      この2つの DDL の間で何か（通常の Python 例外）が起きたら `conn.rollback()`
      で本番テーブルを元に戻し、作業用テーブルも `DROP` する（`with` ブロックの
      失敗時と同じ「本番はそのまま・作業用は残さない」を保つ）。
      （SQLite の `RENAME` はテーブルに張ったインデックスをそのまま引き継ぐ
      ——`CREATE INDEX`/`CREATE UNIQUE INDEX` は `with` ブロック内で作業用
      テーブル名に対して行えば、差し替え後もそのまま有効に残る。ただし
      **インデックス自体の名前**は `table`（本番名）に依存させないこと——
      差し替えの前後でインデックス名は変わらないため、本番名を埋め込むと
      「作業用テーブルに対する索引なのに本番名を名乗る」中途半端な状態が
      差し替え前に一時的に生まれる）。
    - この関数の呼び出し時点で、前回のクラッシュで残った同名の作業用テーブルが
      あれば、作り始める前に `DROP` する（starting-state のクリーンアップ）。

    `create_sql` は `{table}` プレースホルダを含む文字列
    （例: `f"CREATE TABLE {{table}} (...)"`）にしておくこと——ここで作業用の
    テーブル名を埋め込む。
    """
    staging = _staging_table_name(table)
    conn.execute(f'DROP TABLE IF EXISTS "{staging}"')
    conn.execute(create_sql.format(table=f'"{staging}"'), params)
    conn.commit()
    try:
        yield staging
    except BaseException:
        conn.rollback()
        conn.execute(f'DROP TABLE IF EXISTS "{staging}"')
        conn.commit()
        raise
    conn.commit()
    # 差し替え（DROP + RENAME）を1つの明示トランザクションにする——コード
    # レビュー指摘。裸の DDL 2文のままだと、間でプロセスが死んだときに
    # 「本番テーブルが消えたまま戻らない」窓が生まれる（docstring 参照）。
    conn.execute("BEGIN")
    try:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'ALTER TABLE "{staging}" RENAME TO "{table}"')
    except BaseException:
        conn.rollback()  # 本番テーブルを元に戻す（DROP をまだ確定していない）
        conn.execute(f'DROP TABLE IF EXISTS "{staging}"')  # 作業用テーブルも残さない
        conn.commit()
        raise
    conn.commit()


def replace_table(conn: sqlite3.Connection, table: str, create_sql: str, params=()) -> None:
    """`table` を作り直す（`DROP TABLE IF EXISTS` の後に `create_sql` を実行するだけ）。

    b04/b05 は `observation`/`observation_agg` を同じ `data/db/v2.sqlite` に同居
    させる（design.md D8）。ファイル全体を作り直す `fresh_sqlite` は他のスクリプトが
    既に書いたテーブル（例: b03 が作った `observation`）まで消してしまうため使えない。
    「出力は毎回作り直す」という要件を、ファイル単位ではなく**テーブル単位**で
    満たすのがこの関数の役割（b04 が `observation_agg` だけを、b05 が射影先の
    3テーブルだけを作り直す）。

    `params` は `create_sql`（`CREATE TABLE ... AS SELECT ...` の形）内の `?` に
    バインドする値。`CREATE TEMP TABLE ... AS SELECT` でも通常の SELECT と同様に
    バインドパラメータが使える（レビュー指摘: `built_from`/`spec_version` を
    文字列で SQL に埋め込むと、値がアポストロフィを含んだときに構文エラーになる。
    `scripts/b04_build_cube.py` 参照）。
    """
    conn.execute(f'DROP TABLE IF EXISTS "{table}"')
    conn.execute(create_sql, params)


def attach_readonly(conn: sqlite3.Connection, path, alias: str) -> None:
    """書き込み用の `conn`（`fresh_sqlite` で開いたもの）に、読み取り専用の別
    sqlite ファイルを ATTACH する。原本を一切書き換えないことを型ではなく
    実行時に保証する（`mode=ro` の URI で開くので、書き込もうとすると
    sqlite3 が例外を投げる）。
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"sqlite ファイルが無い: {p}")
    conn.execute(f"ATTACH DATABASE 'file:{p}?mode=ro' AS {alias}")


def assert_attached_table_exists(conn: sqlite3.Connection, alias: str, table: str, *, hint: str) -> None:
    """`ATTACH`（`attach_readonly` 等）した `alias` に `table` が存在することを
    確認する。無いと素の `sqlite3.OperationalError`（no such table）になり原因が
    分かりにくいため（`scripts/b05_project_v1.py` の
    `_assert_place_relation_table_exists`・`scripts/b11_project_place_v1.py` の
    `_assert_place_watershed_table_exists` が同型の検証を別々に持っていたものを
    1箇所に集約した。Phase B `phase-b/place-attributes`、main へのリベース時）。

    `hint` は「テーブルが無いときに何をすべきか」を示す1文（呼び出し元ごとに
    文言が違うため呼び出し側から渡す。`raise_on_group_by_duplicates` の
    `build_message` と同じ、文言を1つのテンプレートに揃えない方針）。
    """
    row = conn.execute(
        f"SELECT 1 FROM {alias}.sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None:
        raise MigrationError(f"{alias} に {table} テーブルが無い。{hint}")


def resolve_registry_db(cli_value: str | None, default: pathlib.Path) -> pathlib.Path:
    """`--registry-db` > `RYUIKI_REGISTRY_DB` 環境変数 > `default`、の優先順位。
    `scripts/r01_build_registry.py` と同じ環境変数を見る（CLAUDE.md の規約）。

    b03/b05 が一字一句同じ実装を持っていた（レビュー指摘）ものをここに1つ置く。
    既定値だけがスクリプトごとに違うため `default` を引数で受ける。
    """
    if cli_value is not None:
        return pathlib.Path(cli_value)
    env = os.environ.get("RYUIKI_REGISTRY_DB")
    if env:
        return pathlib.Path(env)
    return default


def raise_on_group_by_duplicates(conn: sqlite3.Connection, sql: str, params: tuple, build_message) -> None:
    """`GROUP BY ... HAVING <集計> > 1` の形で重複を検出する `sql` を実行し、
    1行でも返れば `build_message(dup_rows)` が組み立てた文言で
    `MigrationError` を投げる（`scripts/b05_project_v1.py` の
    `place_lookup`/`site_zone_lookup` の一意性検証・ゾーン番号の衝突検証・
    `assert_alias_is_function` 等と、`scripts/b08_project_occurrence_v1.py` の
    `place_mesh_lookup` の単射検証はどれもこの同じ形——クエリを実行し、重複が
    見つかったら特定の文言で止める——だったものを1箇所に集約した
    （/simplify 指摘2）。

    サンプル件数の絞り込み（`LIMIT n`）を入れるかどうか・`COUNT(*)` か
    `COUNT(DISTINCT ...)` か・メッセージの文言は、すべて呼び出し側に委ねる
    （呼び出し元それぞれの検証は意味も重要度も違うため、文言を1つの
    テンプレートに揃えない——既存テストが見ているメッセージはこの関数を
    導入しても1文字も変わらない）。
    """
    dup = conn.execute(sql, params).fetchall()
    if dup:
        raise MigrationError(build_message(dup))


def assert_dimension_key_unique(
    conn: sqlite3.Connection, staging: str, dim_columns: list[str], *,
    index_name: str, table_label: str, cause_hint: str,
) -> None:
    """`staging`（`staged_table` の作業用テーブル）に `dim_columns` の
    `COALESCE(col, '')` 式で `CREATE UNIQUE INDEX` を張り、次元キーの一意性を
    確認する（`scripts/b04_build_cube.py`〔C-3〕と `scripts/b07_build_occurrence_cube.py`
    がほぼ一字一句同じ実装を持っていたものを1箇所に集約した。/simplify 指摘1）。

    索引は検証用の使い捨て——成功しても検証後に `DROP INDEX` する（固定名の
    索引を本番テーブルまで残すと、次回実行が同じ固定名で索引を作ろうとした
    ときに名前衝突で壊れる）。重複が無ければ索引の作成が成功するだけで済み、
    `GROUP BY` で全行を読み直すより速い（b04 実測: 約12.9秒。モジュール
    docstring 以上の詳細は `scripts/b04_build_cube.py` の「次元キーの一意性
    検証（C-3）」節参照——ここでは実装だけを持つ）。

    **`dim_columns` の生の列に索引を張ってはいけない**。NULL がありうる列
    （`obs_stat`/`taxon_id` 等）に対して、SQL の一意制約は NULL 同士を
    「等しくない」と扱うため、`col IS NULL` の行が2つあっても
    `CREATE UNIQUE INDEX` は重複として検出しない——`GROUP BY`（NULL 同士を
    同じグループにまとめる）となら検出結果が食い違う。`COALESCE(col, '')`
    で NULL を空文字に正準化した式に索引を張ることで、`GROUP BY` と同じ
    「NULL 同士は同じ値」という扱いに揃える。

    `index_name` は呼び出し元ごとに別の固定名にすること（同じ接続で複数の
    `staged_table` を並行して扱う場合の名前衝突を避ける）。`table_label`/
    `cause_hint` はエラーメッセージに使う（`table_label` の次元キーが一意で
    ない旨＋`cause_hint`〔原因の手がかり〕）。
    """
    key_cols = ", ".join(dim_columns)
    key_exprs = ", ".join(f"COALESCE({c}, '')" for c in dim_columns)
    try:
        conn.execute(f'CREATE UNIQUE INDEX {index_name} ON "{staging}" ({key_exprs})')
    except sqlite3.IntegrityError:
        dup = conn.execute(
            f'SELECT {key_cols}, COUNT(*) c FROM "{staging}" GROUP BY {key_exprs} HAVING c > 1 LIMIT 5'
        ).fetchall()
        raise MigrationError(f"{table_label} の次元キーが一意でない行がある（例: {dup}）。{cause_hint}")
    else:
        conn.execute(f'DROP INDEX IF EXISTS "{index_name}"')


@contextlib.contextmanager
def _materialized_join_tables(conn: sqlite3.Connection, left_sql: str, right_sql: str, key_columns: list[str]):
    """`left_sql`/`right_sql`（それぞれ `key_columns + value_columns` の並びで
    `GROUP BY` 済みの行を返す `SELECT` 文字列）の結果を一時テーブルに実体化し、
    結合キー（`key_columns` を `COALESCE` で NULL 安全にしてから `'|'` で
    連結した1列 `__k`）に `UNIQUE INDEX` を張る。`with` を抜けるときに一時
    テーブルを必ず消す。戻り値は一時テーブル名のペア `("__agtm_l", "__agtm_r")`。

    `assert_grouped_totals_match()`/`count_grouped_totals_mismatches()` が
    共有する「一時テーブル＋一意索引」の安全策（/simplify 指摘5）。**最初の
    実装は `WITH` 句のサブクエリを複数列の `IS`（NULL-safe）条件で直接
    `FULL OUTER JOIN` していたが、SQLite のクエリプランナは `IS` を使う JOIN
    条件にインデックスを使わず、ネストループ（両側とも約32,000行なら最大
    約10億回の比較）に落ちる**——実測で2分経っても終わらず、明確な性能事故に
    なった（`scripts/b05_project_v1.py` の `_alias_lookup_sql` が「NULL を
    含みうる列を `IS` で JOIN すると自動インデックスが効かない」と書いている
    問題と同じ根）。単一の計算済み列への通常の `=` ならインデックスを使う
    （実測: 実データ約32,000行×32,000行で0.15秒）。
    """
    key_expr = " || '|' || ".join(f"COALESCE({c}, '')" for c in key_columns)
    conn.execute("DROP TABLE IF EXISTS __agtm_l")
    conn.execute("DROP TABLE IF EXISTS __agtm_r")
    try:
        conn.execute(f"CREATE TEMP TABLE __agtm_l AS SELECT {key_expr} AS __k, sub.* FROM ({left_sql}) sub")
        conn.execute(f"CREATE TEMP TABLE __agtm_r AS SELECT {key_expr} AS __k, sub.* FROM ({right_sql}) sub")
        conn.execute("CREATE UNIQUE INDEX __agtm_l_key ON __agtm_l (__k)")
        conn.execute("CREATE UNIQUE INDEX __agtm_r_key ON __agtm_r (__k)")
        yield "__agtm_l", "__agtm_r"
    finally:
        conn.execute("DROP TABLE IF EXISTS __agtm_l")
        conn.execute("DROP TABLE IF EXISTS __agtm_r")


def assert_grouped_totals_match(
    conn: sqlite3.Connection,
    left_sql: str,
    right_sql: str,
    key_columns: list[str],
    value_columns: list[str],
    build_message,
    *,
    sample_limit: int = 20,
) -> None:
    """`left_sql`/`right_sql`（それぞれ `key_columns + value_columns` の並びで
    `GROUP BY` 済みの行を返す `SELECT` 文字列）を SQL の `FULL OUTER JOIN` で
    直接突き合わせ、キーの欠落・値の食い違いを最大 `sample_limit` 件だけ
    `build_message` に渡して `MigrationError` にする（SQLite 3.43 以降が前提。
    CLAUDE.md の「キューブは SQLite 3.43 以降」参照——`FULL OUTER JOIN` 自体は
    3.39 で入ったが、このコードベースの前提バージョンはそれより新しい）。

    `scripts/b07_build_occurrence_cube.py` の系列ごとの Σn 突合と
    `scripts/b08_project_occurrence_v1.py` の「キューブが今の L2 の分割か」の
    突合はどちらも「2つの GROUP BY 結果を比べ、系列（複数列のキー）ごとの
    粒度で食い違いをサンプルする」という同型の処理だった。以前はどちらも
    両方の GROUP BY 結果を Python の `dict` に展開してから `set` 演算で
    突き合わせており、系列数が約32,000にもなると Python 側の実行時間が
    支配的だった（/simplify 実測: この Python 側だけで b07 約3.6秒・b08
    約2.4秒）。比較そのものを SQL 側で行うことで、Python 側は食い違った行
    （最大 `sample_limit` 件）の整形だけになる（/simplify 指摘3）。

    系列の粒度はそのまま保つ（合計だけを比べない）——系列間で数字が入れ替わる
    壊れ方（ある系列の分が別の系列に付け替わり、全体の合計は変わらない）を
    検出できなくなるのを避けるため。

    「一時テーブル＋一意索引」の実体化は `_materialized_join_tables()` に
    集約してある。キーの比較は NULL 安全（`taxon_id` 等が NULL を取りうる
    ため、素の `=` では NULL 同士が一致しない）。`build_message(rows)` の
    `rows` は `(key_columns..., <value>_l, <value>_r 各 value_columns ごと)`
    の並びのタプルのリスト（片側にしか無いキーは無い方の値が `None`）。
    """
    with _materialized_join_tables(conn, left_sql, right_sql, key_columns) as (lt, rt):
        key_select = ", ".join(f"COALESCE(l.{c}, r.{c}) AS {c}" for c in key_columns)
        value_select = ", ".join(f"l.{c} AS {c}_l, r.{c} AS {c}_r" for c in value_columns)
        mismatch_cond = " OR ".join(f"l.{c} IS NOT r.{c}" for c in value_columns)
        sql = f"""
        SELECT {key_select}, {value_select}
        FROM {lt} l FULL OUTER JOIN {rt} r ON l.__k = r.__k
        WHERE ({mismatch_cond}) OR l.__k IS NULL OR r.__k IS NULL
        LIMIT {sample_limit}
        """
        rows = conn.execute(sql).fetchall()
    if rows:
        raise MigrationError(build_message(rows))


def count_grouped_totals_mismatches(
    conn: sqlite3.Connection,
    left_sql: str,
    right_sql: str,
    key_columns: list[str],
    value_columns: list[str],
) -> int:
    """`assert_grouped_totals_match()` と同じ「一時テーブル＋一意索引」の
    安全な `FULL OUTER JOIN`（`_materialized_join_tables()` を共有）で、
    片方にしかないキー・値が食い違うキーの**総数**を返す（/simplify 指摘5）。

    `assert_grouped_totals_match()` は最大 `sample_limit` 件で打ち切って
    無条件に `MigrationError` を投げるのに対し、こちらは「ある個数だけ
    食い違いが発生する」ことを織り込んだ検証（宣言済みの期待値と実測件数を
    突き合わせる）に使う——`scripts/b08_project_occurrence_v1.py` の
    `_measure_keys_changed_vs_exact`（`org_watershed_year` と
    `org_watershed_year_exact` の突合、宣言値 1,091）が最初の呼び出し元。
    """
    with _materialized_join_tables(conn, left_sql, right_sql, key_columns) as (lt, rt):
        mismatch_cond = " OR ".join(f"l.{c} IS NOT r.{c}" for c in value_columns)
        sql = f"""
        SELECT COUNT(*) FROM {lt} l FULL OUTER JOIN {rt} r ON l.__k = r.__k
        WHERE ({mismatch_cond}) OR l.__k IS NULL OR r.__k IS NULL
        """
        return conn.execute(sql).fetchone()[0]
