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
