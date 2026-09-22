"""b03/b04/b05（Phase B ファクトとキューブ）が共有する薄い土台。

- 読み取り専用オープンと YAML 読み込みは `scripts/reconcile/common.open_readonly`/
  `load_yaml` をそのまま使う（同じ規約を2箇所に書かない。既に b01/b02 が
  使っている実装。`scripts/migrate/period.py` はここから `load_yaml` を引く）。
- 出力 sqlite は毎回ゼロから作り直す（`fresh_sqlite`）。前回実行の残骸（WAL/SHM
  側車ファイルを含む）が残ったまま次の実行が古い行を引きずる事故を避ける。
- 実行時間とテーブルごとの行数を `[12.3s] ラベル / N行` の形で出す（`timed_step`）。
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

from reconcile.common import load_yaml, open_readonly  # noqa: E402,F401  (b03/b04/b05 から re-export)

# b04 の observation_agg / b05 の射影が `built_from` / `spec_version` に書く定数。
# バージョンを上げるのはこのパッケージの変換ロジックそのものを変えたとき
# （キーの構成や集計方法が変わる＝過去に作った observation_agg と比較できなくなるとき）。
SPEC_VERSION = "phase-b-fact-slice/v1"


class MigrationError(Exception):
    """b03/b04/b05 が「黙って捨てず・黙って推測せず」止まるときに投げる例外。

    データの中身に起因する想定外（alias/place が解決できない、value_grain と
    period_grain が宣言されていない食い違い方をしている等）はすべてこれを使う。
    プログラムのバグ（引数の誤り等）は通常の例外のままにして区別する。
    """


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
    """
    p = pathlib.Path(path)
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
