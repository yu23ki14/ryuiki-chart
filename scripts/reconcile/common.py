"""Phase B 突合ハーネスの共通処理。

- 読み取り専用オープン
- キー列の自動導出＋検証（derive_key）
- テーブルの指紋計算（compute_fingerprint）— b01 と b02 の両方が同じ実装を使うことで、
  「計算方法の違いによる見かけ上の不一致」を作らない
- 宣言的 YAML（derived_keys.yaml / adr0011_destinations.yaml）の読み込み

原本（derived.sqlite 等）は `open_readonly()` でのみ開く。このモジュールはどの関数も
1バイトも書き込まない。
"""
from __future__ import annotations

import hashlib
import itertools
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

# `reports/derived_baseline.json` の形式バージョン。b01 が書き、b02 が
# 読んで検証する（想定外なら「b01 を実行し直せ」と言って落ちる。
# `scripts/b01_derived_baseline.py` の `main()` と
# `scripts/b02_derived_compare.py` の `main()` の両方が参照する、ただ1つの定義）。
SCHEMA_VERSION = 1


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
# キー列の自動導出
# ---------------------------------------------------------------------------

class _DistinctCache:
    """列ごとの「実効カーディナリティ」を遅延計算してキャッシュする。

    候補の組み合わせ数は列数に対して指数的に増えうるが、実際に SQL を打つ前に
    「積が総行数に届かない組み合わせは鳩の巣原理で一意になり得ない」ことを
    カーディナリティだけで判定できる（`_search` 参照）。列ごとに高々1回だけ
    クエリを打てば済む。

    **`COUNT(DISTINCT col)` は NULL を数えない**が、`_is_unique` が使う
    `GROUP BY` は NULL を（他の NULL と同じ）1つのグループ値として数える。
    この2つの食い違いをそのまま鳩の巣原理の枝刈りに使うと、NULL を含む列の
    カーディナリティを1少なく見積もり、**本当は一意な組み合わせを誤って
    枝刈りしてしまう**（レビュー指摘。実測: `(a,b)` が `('x',NULL),('x','q'),
    ('y',NULL)` で一意であるにもかかわらず `COUNT(DISTINCT a)*COUNT(DISTINCT b)
    = 2*1 = 2 < 3` で枝刈りされていた）。

    壊れ方が特に悪い: 探索A（宣言型を持つ列だけの部分集合）で NULL を含む
    次元列がこうして誤って除外されると、探索Bに落ちて宣言型を持たない列
    （集計列 `avg`/`n` 等）がキーに紛れ込む — 2段階探索がまさに防ぐはずだった
    事故が、この枝刈りの穴から起きる。

    そのため、列に NULL が1件でもあれば実効カーディナリティに +1 する
    （NULL 自身も `GROUP BY` の下では区別可能な1つの値なので）。
    """

    def __init__(self, conn: sqlite3.Connection, table: str):
        self._conn = conn
        self._table = table
        self._cache: dict[str, int] = {}

    def get(self, col: str) -> int:
        if col not in self._cache:
            row = self._conn.execute(
                f'SELECT COUNT(DISTINCT "{col}"), '
                f'MAX(CASE WHEN "{col}" IS NULL THEN 1 ELSE 0 END) FROM "{self._table}"'
            ).fetchone()
            distinct_non_null, has_null = row
            self._cache[col] = distinct_non_null + (has_null or 0)
        return self._cache[col]


def _is_unique(conn: sqlite3.Connection, table: str, cols: Sequence[str]) -> bool:
    collist = ", ".join(f'"{c}"' for c in cols)
    sql = f'SELECT EXISTS(SELECT 1 FROM "{table}" GROUP BY {collist} HAVING COUNT(*) > 1)'
    return conn.execute(sql).fetchone()[0] == 0


def _search(
    conn: sqlite3.Connection,
    table: str,
    total: int,
    cache: _DistinctCache,
    base: Sequence[str],
    pool: Sequence[str],
) -> list[str] | None:
    """`base`（固定で含める列）+ `pool` から増分で選んだ列、のうち一意なものを
    列数が小さい順・`pool` の並び順で最初に見つかったものを返す。

    `pool` の並び順がそのまま探索の優先順位になる。呼び出し側
    （`derive_key`）が「型宣言のある列を先、無い列を後」の順で `pool` を渡すことで、
    集計関数由来の列（宣言型が消える）より次元列を優先させる。
    """
    base_prod = 1
    for c in base:
        base_prod *= max(cache.get(c), 1)
    for k in range(1, len(pool) + 1):
        for combo in itertools.combinations(pool, k):
            prod = base_prod
            for c in combo:
                prod *= max(cache.get(c), 1)
                if prod >= total:
                    break
            if prod < total:
                continue  # 鳩の巣原理でこの組み合わせは一意になり得ない
            key = list(base) + list(combo)
            if _is_unique(conn, table, key):
                return key
    return None


def derive_key(
    conn: sqlite3.Connection, table: str, overrides: dict
) -> tuple[list[str], str, str | None]:
    """テーブルの一意なキー列を導出する。戻り値は (key, source, note)。

    `source` は `"pk"`（宣言された PRIMARY KEY）/ `"declared"`
    （`derived_keys.yaml` の宣言。自動探索より先に見る＝明示された知識を優先する）/
    `"auto"`（自動探索）のいずれか。

    手順（全テーブル共通。テーブルごとの特殊分岐は書かない）:

    0. `PRAGMA table_info` に PRIMARY KEY 宣言があれば、それをそのまま使う
       （SQLite が挿入時点で一意性を強制済み。assert で再確認だけする）。
    1. `overrides`（`derived_keys.yaml`）にこのテーブルの宣言があれば、それを使う
       （assert で一意性を確認する。宣言だからといって検証を省かない）。
    2. [A] 「宣言型を持つ列」（`CREATE TABLE ... AS SELECT` で集計関数を通さず
       素通しされた列。年度/月などは `CAST(... AS INT)` で明示的に型が付く）の
       部分集合を、列数が小さい順に試す。
    3. [B] 2 で見つからなければ、2 の全列を固定した上で「宣言型を持たない列」
       （`AVG`/`SUM`/`COUNT`/`CASE WHEN` 等の結果。宣言型が消える）を
       1個ずつ増やして試す。

    2・3 のどちらでも見つからなければ例外を投げる（黙って全列をキーにしない。
    `derived_keys.yaml` に宣言を追記するよう促すメッセージを出す）。

    なぜこの順序か: このリポジトリの派生テーブルは
    `(場所, [分類群], 指標, 期間, 粒度) -> 統計量`（ADR-0011）の形をしており、
    SELECT 句は常に次元列を先に、集計列を後に置く。「集計関数の結果は宣言型が
    消える」という SQLite の実装挙動と、「次元が先・値が後」という列順の慣習を
    組み合わせると、候補列の探索順を「型宣言あり→なし」にするだけで、
    浮動小数の集計値（`avg`/`n` 等）がキーに紛れ込む事故を避けられる。

    実測（探索アルゴリズムの検討時に確認): 素朴な「distinct 件数が多い列から
    貪欲に足す」方式では `sensor_hour_month` のキーに集計列 `avg` が、
    `zone_clim` では次元列 `zone` が抜けて集計列 `n` が紛れ込んだ
    （どちらも「たまたま現在のデータでは一意になる」だけの誤ったキー）。
    A→B の2段階探索ではどちらも起きない。
    """
    info = table_info(conn, table)
    pk_cols = get_pk_columns(conn, table)
    if pk_cols:
        if not _is_unique(conn, table, pk_cols):
            raise AssertionError(
                f"{table}: PRIMARY KEY 宣言 {pk_cols} が一意ではない（データ破損の疑い）"
            )
        return pk_cols, "pk", None

    override = overrides.get(table)
    if override is not None:
        declared_key = list(override["key"])
        if not _is_unique(conn, table, declared_key):
            raise AssertionError(
                f"{table}: derived_keys.yaml の宣言キー {declared_key} が一意ではない。宣言を見直すこと。"
            )
        return declared_key, "declared", override.get("reason")

    typed = [r[1] for r in info if (r[2] or "") != ""]
    untyped = [r[1] for r in info if (r[2] or "") == ""]
    total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    cache = _DistinctCache(conn, table)

    key = _search(conn, table, total, cache, base=[], pool=typed)
    if key is not None:
        return key, "auto", None

    key = _search(conn, table, total, cache, base=typed, pool=untyped)
    if key is not None:
        return key, "auto", None

    raise RuntimeError(
        f"{table}: 一意なキー列の組み合わせが自動で見つからなかった"
        "（宣言型を持つ列・持たない列を合わせた全列の組み合わせを試しても一意にならない）。"
        "scripts/reconcile/derived_keys.yaml に "
        f"{table} の宣言的なキーを追記すること（なぜ自動で決まらないかを1行のコメントで残す。"
        "docs/plans/PHASE_B_RECONCILIATION.md 参照）。"
    )


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


def load_key_overrides(path) -> dict:
    """`derived_keys.yaml` を読む。トップレベルはテーブル名 -> {key, reason}。"""
    return load_yaml(path)


def load_destinations(path) -> dict[str, dict]:
    """`adr0011_destinations.yaml`（ADR-0011「33テーブルの行き先」表）を読み、
    テーブル名 -> {category, label_ja} のフラットな辞書にして返す。
    """
    raw = load_yaml(path)
    flat: dict[str, dict] = {}
    for category, spec in raw.items():
        label = spec.get("label_ja", category)
        for table in spec.get("tables", []):
            flat[table] = {"category": category, "label_ja": label}
    return flat
