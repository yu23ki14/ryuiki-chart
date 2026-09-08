"""テスト用の小さな sqlite フィクスチャを作る。

`data/db/derived.sqlite` の実テーブルの「形」を縮小再現する:

- `t_pk`      : `PRIMARY KEY` 宣言あり（`redlist_map` / `watershed_meta` 相当）。
- `t_dims`    : `CREATE TABLE ... AS SELECT` 相当。宣言型を持つ次元列
                （`site`, `year`）だけでは一意にならず、宣言型を持たない列
                （`kind`）が無いと一意にならない（`meas_year` の `kind` 相当）。
- `t_dupe`    : 完全に重複する行がある。どんな列の組み合わせを使っても一意な
                キーが作れない（`derived_keys.yaml` に宣言を書かないと
                `derive_key` が例外を投げる、という失敗経路のテスト用）。
- `t_null_dim`: 宣言型を持つ次元列（`sub`）に NULL が混じる。`(grp, sub)` は
                一意（`grp='g1'` の行が `sub=NULL` と `sub='x'` で2つに分かれる
                ため）だが、`COUNT(DISTINCT sub)` は NULL を数えないので、
                誤ったカーディナリティ計算では枝刈りされてしまう
                （`common.py` の `_DistinctCache` の回帰テスト用）。
                `('g1', NULL)` と `('g1', 'x')` はキーの最初の要素が等しいので、
                これらを含む集合を素朴に `sorted()` すると `None < 'x'` の比較で
                `TypeError` になる（b02 の回帰テスト用）。
"""
import sqlite3

T_PK_ROWS = [
    ("a", "Alpha"),
    ("b", "Beta"),
    ("c", "Gamma"),
]

T_DIMS_ROWS = [
    ("s1", 2020, "daily", 10, 1.5),
    ("s1", 2020, "annual", 1, 1.5),
    ("s1", 2021, "daily", 12, 2.0),
    ("s2", 2020, "daily", 5, 3.0),
]

T_DUPE_ROWS = [
    ("x", 1),
    ("x", 1),  # t_pk と違い、こちらは全列が完全に重複する行
    ("y", 2),
]

# grp, sub は宣言型を持つ次元列（typed）。val は宣言型を持たない集計列もどき
# （untyped。もし (grp, sub) が誤って枝刈りされて探索Aで見つからなければ、
# 探索Bでこの val がキーに紛れ込んでしまう）。
T_NULL_DIM_ROWS = [
    ("g1", None, 10.0),
    ("g1", "x", 20.0),
    ("g2", None, 30.0),
]


def make_fixture_db(path, *, include_dupe: bool = True) -> None:
    """`t_pk` / `t_dims` を作る。`include_dupe=True`（既定）なら、どんな列の
    組み合わせでも一意なキーが作れない `t_dupe` も足す。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE t_pk (raw TEXT PRIMARY KEY, label TEXT)"
        )
        conn.execute("CREATE TABLE t_dims (site TEXT, year INTEGER, kind, n, avg)")
        conn.executemany("INSERT INTO t_pk VALUES (?,?)", T_PK_ROWS)
        conn.executemany("INSERT INTO t_dims VALUES (?,?,?,?,?)", T_DIMS_ROWS)
        if include_dupe:
            conn.execute("CREATE TABLE t_dupe (a TEXT, b INTEGER)")
            conn.executemany("INSERT INTO t_dupe VALUES (?,?)", T_DUPE_ROWS)
        conn.commit()
    finally:
        conn.close()


def make_null_key_fixture_db(path, *, rows=None) -> None:
    """`t_null_dim` だけを持つ小さな DB を作る（NULL を含む次元列のテスト用）。

    既存の `make_fixture_db` に足さず別関数にしてあるのは、`t_pk`/`t_dims`
    を前提にした他のテストの「このDBのテーブルはこれだけ」という assert を
    壊さないため。`rows` を渡すと `T_NULL_DIM_ROWS` の代わりに使う
    （候補側を「全部消えた」状態にするテスト等で空リストを渡す）。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t_null_dim (grp TEXT, sub TEXT, val)")
        conn.executemany("INSERT INTO t_null_dim VALUES (?,?,?)", rows if rows is not None else T_NULL_DIM_ROWS)
        conn.commit()
    finally:
        conn.close()


def dump_all_tables_as_json(db_path) -> dict:
    """フィクスチャ sqlite の全テーブルを、b02 の JSON 候補フォーマット
    （`{table: {"columns": [...], "rows": [[...], ...]}}`）にダンプする。

    候補側を JSON で与えるテスト（行の追加・削除・値の変更）の出発点として使う。
    """
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        out = {}
        for t in tables:
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{t}")')]
            collist = ", ".join(f'"{c}"' for c in cols)
            rows = [list(r) for r in conn.execute(f"SELECT {collist} FROM \"{t}\"")]
            out[t] = {"columns": cols, "rows": rows}
        return out
    finally:
        conn.close()
