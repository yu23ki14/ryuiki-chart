"""SQLite の表を、決定的な Parquet に書く（Issue #40 Phase D 担当 P）。

- 型は SQLite の宣言型から機械的に決める（INTEGER→int64・REAL→float64・TEXT→string）。
  `period_start/period_end` は文字列のまま（ADR-0024。timestamp 型にして UTC 化する事故を避ける）。
  宣言型が上の3つ以外なら黙って文字列に倒さず落とす。
- 行は呼び出し側が渡す ORDER BY（主キー順）で並べる。
- 「行集合のダイジェスト」（`Digest`）は行の順序に依らない。`datapackage.json` にはファイルの
  バイト（sha256）と行集合のダイジェストの両方を持たせ、ライブラリの非決定性でバイトが
  揺れても行集合で同一性を言えるようにする（設計書 D3 のフォールバック）。
"""
from __future__ import annotations

import hashlib
import pathlib
import sqlite3
from typing import Iterator, Sequence

from pipeline_inputs import sha256_file  # noqa: F401  (ファイルの sha256 は pipeline_inputs のものを再利用。w.sha256_file として公開)
import pyarrow as pa
import pyarrow.parquet as pq

# 書き出しの設定。1つでも変えたら出力のバイトが変わりうるので入力指紋（`WRITER_SPEC`）に含める
# （変えると全パーティションが作り直される）。
ROW_GROUP_SIZE = 131072
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3
BATCH_ROWS = 50000
WRITER_SPEC = f"parquet:{COMPRESSION}{COMPRESSION_LEVEL}:rg{ROW_GROUP_SIZE}:pyarrow{pa.__version__}"

_ARROW_TYPES = {"INTEGER": pa.int64(), "REAL": pa.float64(), "TEXT": pa.string()}
_FRICTIONLESS_TYPES = {"INTEGER": "integer", "REAL": "number", "TEXT": "string"}


class Column:
    __slots__ = ("name", "decl", "not_null")

    def __init__(self, name: str, decl: str, not_null: bool):
        self.name, self.decl, self.not_null = name, decl, not_null

    @property
    def arrow_type(self) -> pa.DataType:
        return _ARROW_TYPES[self.decl]

    @property
    def table_schema_field(self) -> dict:
        f = {"name": self.name, "type": _FRICTIONLESS_TYPES[self.decl]}
        if self.not_null:
            f["constraints"] = {"required": True}
        return f


def table_columns(conn: sqlite3.Connection, table: str) -> list[Column]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise RuntimeError(f"表 {table!r} が無い")
    cols = []
    for _cid, name, decl, notnull, _dflt, _pk in rows:
        d = (decl or "").strip().upper()
        if d not in _ARROW_TYPES:
            raise RuntimeError(
                f"{table}.{name} の宣言型 {decl!r} は dist の型対応表（INTEGER/REAL/TEXT）に無い。"
                "黙って文字列にしない。scripts/dist/writer.py に対応を足す設計判断が要る"
            )
        cols.append(Column(name, d, bool(notnull)))
    return cols


class Digest:
    """行集合のダイジェスト（行の順序に依らない）。行ごとの sha256 を 256bit 整数として総和する。

    行の符号化は `repr(tuple)`。int/float/str/None だけを扱う前提で、float の repr は最短の
    往復表現なので値が1ビットでも違えば別の文字列になる（座標を丸めると必ず変わる）。
    """

    def __init__(self) -> None:
        self.n = 0
        self._total = 0

    def add(self, row: tuple) -> None:
        self._total = (self._total + int.from_bytes(hashlib.sha256(repr(row).encode("utf-8")).digest(), "big")) % (1 << 256)
        self.n += 1

    @property
    def hexdigest(self) -> str:
        return f"{self._total:064x}"


def arrow_schema(columns: Sequence[Column]) -> pa.Schema:
    return pa.schema([pa.field(c.name, c.arrow_type, nullable=not c.not_null) for c in columns])


def _to_arrow(columns: Sequence[Column], rows: list[tuple]) -> pa.RecordBatch:
    arrays = [pa.array([r[i] for r in rows], type=c.arrow_type) for i, c in enumerate(columns)]
    return pa.RecordBatch.from_arrays(arrays, schema=arrow_schema(columns))


class Group:
    """1パーティション分の行（ダイジェスト済み・Arrow バッチで保持）。"""

    def __init__(self, key, columns: Sequence[Column]):
        self.key = key
        self.columns = list(columns)
        self.digest = Digest()
        self.batches: list[pa.RecordBatch] = []

    @property
    def rows(self) -> int:
        return self.digest.n

    def write(self, path: pathlib.Path) -> None:
        """一時ファイルへ書いてから置き換える（途中で死んでも半端なファイルを残さない）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        schema = arrow_schema(self.columns)
        table = pa.Table.from_batches(self.batches, schema=schema) if self.batches else schema.empty_table()
        pq.write_table(
            table, tmp,
            compression=COMPRESSION, compression_level=COMPRESSION_LEVEL,
            row_group_size=ROW_GROUP_SIZE, use_dictionary=True, write_statistics=True,
            data_page_version="2.0", store_schema=False,
        )
        tmp.replace(path)


def iter_groups(
    conn: sqlite3.Connection, table: str, *, order_by: Sequence[str],
    partition_by: str | None = None, where: str = "", params: Sequence = (),
) -> Iterator[Group]:
    """`table` を (partition_by, *order_by) の順に1回だけ走査し、パーティションごとの Group を返す。

    `partition_by` の列は各ファイルから落とす（hive 形式のパス `col=value/` が持つ。ファイルにも
    同名列があると DuckDB・pyarrow の hive パーティション読みが衝突する）。ダイジェストは落とした
    後の列順で取る（検査側も同じ列を同じ順に取る）。
    """
    all_cols = table_columns(conn, table)
    names = {c.name for c in all_cols}
    for c in ([partition_by] if partition_by else []) + list(order_by):
        if c not in names:
            raise RuntimeError(f"{table} に列 {c!r} が無い")
    keep = [c for c in all_cols if c.name != partition_by]
    sel = ", ".join(f'"{c.name}"' for c in keep)
    if partition_by:
        sel = f'"{partition_by}", ' + sel
    order = ", ".join(f'"{c}"' for c in ([partition_by] if partition_by else []) + list(order_by))
    sql = f'SELECT {sel} FROM "{table}"' + (f" WHERE {where}" if where else "") + (f" ORDER BY {order}" if order else "")
    off = 1 if partition_by else 0
    group: Group | None = None
    key = None
    buf: list[tuple] = []

    def flush() -> None:
        if buf:
            group.batches.append(_to_arrow(keep, buf))
            buf.clear()

    for row in conn.execute(sql, tuple(params)):
        k = row[0] if partition_by else None
        if group is None or k != key:
            if group is not None:
                flush()
                yield group
            group, key = Group(k, keep), k
        data = tuple(row[off:])
        group.digest.add(data)
        buf.append(data)
        if len(buf) >= BATCH_ROWS:
            flush()
    if group is not None:
        flush()
        yield group
    elif not partition_by:
        yield Group(None, keep)  # 空の表でも（空の）ファイルを書く
