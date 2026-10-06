"""Phase B パイプラインの共通処理（v1 との突合ハーネスの名残から、いまも使われる部分だけ残した）。

- 読み取り専用オープン（`open_readonly`）
- テーブルの指紋計算（`compute_fingerprint`。`scripts/migrate/common.py` の段階間の指紋が使う）
- YAML 読み込み（`load_yaml`）

原本（ryuiki.sqlite 等）は `open_readonly()` でのみ開く。このモジュールはどの関数も
1バイトも書き込まない。v1 との突合（キー列の自動導出・宣言済み差分の読み込み・検証）は
Issue #48 PR-5 で b01/b02 とともに消えた。
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
import sqlite3
from typing import Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - requirements.txt で入れる
    yaml = None

from . import datasource

# ---------------------------------------------------------------------------
# 読み取り専用オープン
# ---------------------------------------------------------------------------

def open_readonly(path) -> sqlite3.Connection:
    """sqlite ファイルを読み取り専用で開く。書き込もうとすると sqlite3 が例外を投げる。"""
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"sqlite ファイルが無い: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    return conn


# ---------------------------------------------------------------------------
# スキーマ情報
# ---------------------------------------------------------------------------

def table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    """PRAGMA table_info の生の行（cid, name, type, notnull, dflt_value, pk）。"""
    return conn.execute(f'PRAGMA table_info("{table}")').fetchall()


def get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in table_info(conn, table)]


def get_column_types(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {r[1]: (r[2] or "") for r in table_info(conn, table)}


def get_pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """PRAGMA table_info の pk 列（0 は非PK）。宣言順（pk の番号順）で返す。"""
    pairs = [(r[5], r[1]) for r in table_info(conn, table) if r[5] and r[5] > 0]
    pairs.sort()
    return [name for _, name in pairs]


def numeric_columns_of(conn: sqlite3.Connection, table: str, columns: Sequence[str]) -> list[str]:
    """`columns` のうち、非NULL値がすべて INTEGER/REAL ストレージクラスの列
    （数値列）だけを、元の並び順で返す。

    `CREATE TABLE ... AS SELECT` では列の宣言型が集計関数の結果に付かない
    （`derive_key` のドキストリング参照）ため、宣言型ではなく実データの
    `typeof()` で判定する。

    列ごとに独立した `SELECT COUNT(*) ...` を打つと、テーブル全体を列数ぶん
    スキャンすることになる（レビュー指摘。実測: `org_norm` 816,856行×21列で
    8.16s）。1テーブル1クエリ（列ごとに `MAX(CASE WHEN ...)` を並べる形）に
    まとめ、5.95s に短縮した（27〜30%減）。
    """
    if not columns:
        return []
    exprs = ", ".join(
        f'MAX(CASE WHEN "{c}" IS NOT NULL AND typeof("{c}") NOT IN (\'integer\',\'real\') '
        f"THEN 1 ELSE 0 END)"
        for c in columns
    )
    row = conn.execute(f'SELECT {exprs} FROM "{table}"').fetchone()
    return [c for c, non_numeric in zip(columns, row) if not (non_numeric or 0)]


# ---------------------------------------------------------------------------
# 数値の正準化
# ---------------------------------------------------------------------------

def format_number(value) -> str:
    """数値集計の丸め規則: 小数点以下6桁の固定文字列にする。

    JSON の float 表現（実装依存になりうる）に頼らず、常に文字列として持つことで、
    b01 の2回実行のバイト一致や b02 での比較を実装非依存にする。
    """
    return f"{float(value):.6f}"


def _canonicalize_scalar(value):
    """int/float は `format_number` で固定小数点の文字列に揃える。

    sqlite の `REAL` 列から来た `1.0`（Python `float`）と、手書き/他言語製の
    JSON 候補が同じ値を書いた `1`（`json.load` で Python `int` になる）は、
    そのまま `json.dumps` すると `1.0` と `1` という別のトークンになり、
    `numeric_stats` は一致するのに `content_hash` だけ食い違う
    （レビュー指摘。ドキュメントで「候補は sqlite でも JSON でもよい」と
    明言している以上、最初の非 Python 製の射影で必ず踏む）。

    文字列・None・bytes はそのまま返す（数値に見える文字列を誤って
    数値として丸めない。テキスト列の値をここで書き換えてはいけない）。
    """
    if isinstance(value, bool):
        # SQLite に真偽型は無く 0/1 の INTEGER として保持される。JSON 側が
        # true/false を書いてきても同じ扱いにする。
        return format_number(int(value))
    if isinstance(value, (int, float)):
        return format_number(value)
    return value


# `json.dumps(..., separators=(",", ":"))` は呼ぶたびに内部で `json.JSONEncoder`
# を構築し直す（`separators` を明示すると CPython の高速パスに乗らない）。
# `canonical_row_bytes` は行ごとに（207万行 × 33テーブルぶん）呼ばれるので、
# エンコーダをモジュールレベルで1つだけ作って使い回す（レビュー指摘の実測:
# 207万行×21列相当のベンチで 36.02s → 25.49s、29%減）。出力バイト列は
# `json.dumps` と同じキーワード引数を渡しているので不変（ベースライン
# JSON の作り直しは不要）。
_ROW_ENCODER = json.JSONEncoder(ensure_ascii=True, separators=(",", ":")).encode


def canonical_row_bytes(row: Sequence) -> bytes:
    """1行分の値を正準化した JSON 配列 + 改行のバイト列にする。

    数値（int/float/bool）は `_canonicalize_scalar` で固定小数点表現に揃えた
    うえで `_ROW_ENCODER`（None→null / str→エスケープ済み文字列）に渡す。
    行の区切りに改行を使うことで、値の中にたまたま同じ文字列表現が現れても
    行単位の連結は曖昧にならない。
    """
    canon = [_canonicalize_scalar(v) for v in row]
    return (_ROW_ENCODER(canon) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# 指紋計算（b01 / b02 共通）
# ---------------------------------------------------------------------------

def compute_fingerprint(
    source: datasource.DataSource,
    table: str,
    columns: Sequence[str],
    key: Sequence[str],
    numeric_columns: Sequence[str],
) -> dict:
    """`columns` の並びでテーブルを読み、`key` 順にソートしながら
    行数・内容ハッシュ・数値列ごとの (非NULL件数, min, max, 合計) を1パスで計算する。

    `source` は sqlite でも JSON でもよい（`datasource.DataSource`）。b01 は
    derived.sqlite を包んだ `SqliteSource` に対して、b02 は候補側
    （sqlite か JSON）と、必要なら実データのベースライン側の両方に対して、
    **同じこの関数**を呼ぶ。計算方法を1箇所にすることで、
    「計算方法の違いによる見かけ上の不一致」を作らない。

    合計は `math.fsum`（入力の順序に依存しない正しく丸められた総和）を使う。
    SQL の `SUM` は物理的な行の並びに集計順序が左右されうる（ドキュメントで
    保証されていない）ため、ここでは使わない。
    """
    idx = {c: i for i, c in enumerate(columns)}
    numeric_idx = [(c, idx[c]) for c in numeric_columns]
    hasher = hashlib.sha256()
    row_count = 0
    non_null = {c: 0 for c in numeric_columns}
    values: dict[str, list[float]] = {c: [] for c in numeric_columns}

    for row in source.fetch_rows(table, columns, order_by=key):
        row_count += 1
        hasher.update(canonical_row_bytes(row))
        for c, i in numeric_idx:
            v = row[i]
            if v is not None:
                non_null[c] += 1
                values[c].append(float(v))

    numeric_stats = {}
    for c in numeric_columns:
        vs = values[c]
        numeric_stats[c] = {
            "non_null": non_null[c],
            "min": format_number(min(vs)) if vs else None,
            "max": format_number(max(vs)) if vs else None,
            "sum": format_number(math.fsum(vs)) if vs else format_number(0.0),
        }

    return {
        "row_count": row_count,
        "content_hash": "sha256:" + hasher.hexdigest(),
        "numeric_stats": numeric_stats,
    }


# ---------------------------------------------------------------------------
# 宣言的 YAML
# ---------------------------------------------------------------------------

def load_yaml(path) -> dict:
    """YAML を読み、無い/空なら `{}` を返す。PyYAML が無ければ即座に失敗する
    （requirements.txt に PyYAML がある前提。scripts/r01_build_registry.py と同じ扱い）。
    """
    if yaml is None:
        raise SystemExit(
            "PyYAML が見つからない。`pip install -r requirements.txt` を実行すること。"
        )
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return data or {}
