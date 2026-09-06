"""レジストリビルドの共通ヘルパ。

- ID 生成（docs/adr/0004-identifiers.md 準拠、Phase A で使う具体形）
- 原本 3 ファイル（ryuiki / cells / derived）を読み取り専用で開く
- registry.sqlite の新規作成（DDL は scripts/schema_registry.sql）と書き込みユーティリティ

各 build_*.py はここの関数だけを使ってレジストリを書く。原本への書き込みは一切しない
（open_source は読み取り専用でしか開けない）。
"""
import re
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DB_DIR = ROOT / "data" / "db"
SCHEMA_SQL = ROOT / "scripts" / "schema_registry.sql"
REGISTRY_DB = DB_DIR / "registry.sqlite"

SOURCE_NAMES = ("ryuiki", "cells", "derived")


# ---------------------------------------------------------------------------
# 原本（読み取り専用）
# ---------------------------------------------------------------------------

def open_source(name: str) -> sqlite3.Connection:
    """data/db/<name>.sqlite を読み取り専用で開く。書き込もうとすると sqlite3 が例外を投げる。"""
    if name not in SOURCE_NAMES:
        raise ValueError(f"未知の原本: {name}（{SOURCE_NAMES} のいずれか）")
    path = DB_DIR / f"{name}.sqlite"
    if not path.exists():
        raise FileNotFoundError(
            f"原本が無い: {path}\n"
            + (
                "集計 DB は `cd web && pnpm run build:derived` で作る。"
                if name == "derived"
                else "data/db/ に原本を置く。"
            )
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_sources() -> dict[str, sqlite3.Connection]:
    """3 原本すべてを読み取り専用で開いて返す。"""
    return {name: open_source(name) for name in SOURCE_NAMES}


# ---------------------------------------------------------------------------
# registry.sqlite（書き込み対象）
# ---------------------------------------------------------------------------

def create_registry_db(path: pathlib.Path | None = None) -> sqlite3.Connection:
    """registry.sqlite を新規に作る。既存があれば消してから作り直す（決定論的な再生成）。"""
    target = path or REGISTRY_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    conn = sqlite3.connect(target)
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def insert_many(conn: sqlite3.Connection, table: str, columns: list[str], rows) -> int:
    """rows（columns の順のタプルの列。ジェネレータ可）を table に流し込み、件数を返す。"""
    rows = list(rows)
    if not rows:
        return 0
    placeholders = ",".join("?" for _ in columns)
    collist = ",".join(columns)
    conn.executemany(f"INSERT INTO {table} ({collist}) VALUES ({placeholders})", rows)
    return len(rows)


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------------------
# ID 生成（ADR-0004）
# ---------------------------------------------------------------------------

def scoped_id(entity: str, local_key: str, scope: str = "common") -> str:
    """<scope>:<entity>:<local_key>。既定スコープは common（ADR-0004 規約0）。"""
    return f"{scope}:{entity}:{local_key}"


def unit_slug(symbol: str) -> str:
    """正準シンボルを common:unit:<slug> の <slug> に変換する。

    / -> _per_ 、. -> _ 、°C/℃ -> degc 、小文字 ASCII 化。
    例: "mg/L" -> "mg_per_l" 、"m" -> "m" 、"°C" -> "degc" 、"dimensionless" -> "dimensionless"。
    """
    s = (symbol or "").strip().lower()
    s = s.replace("℃", "degc")
    s = re.sub(r"°\s*c\b", "degc", s)
    s = s.replace("/", "_per_")
    s = s.replace(".", "_")
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def unit_id(symbol: str, scope: str = "common") -> str:
    return scoped_id("unit", unit_slug(symbol), scope)


def variable_id(theme: str, name: str, scope: str = "common") -> str:
    return scoped_id("variable", f"{theme}.{name}", scope)


def place_id(place_kind: str, namespace: str, local: str, scope: str = "common") -> str:
    """common:place:<kind>.<namespace>-<local>。site は通常 jp-14 スコープ。"""
    return scoped_id("place", f"{place_kind}.{namespace}-{local}", scope)


def taxon_id_gbif(gbif_key, scope: str = "common") -> str:
    return scoped_id("taxon", f"gbif.{gbif_key}", scope)


def taxon_id_unresolved(taxa_pk, scope: str = "common") -> str:
    """v1 の taxa 由来で GBIF 未照合のもの。"""
    return scoped_id("taxon", f"ryuiki-taxa.{taxa_pk}", scope)


def caveat_id(key: str, scope: str = "common") -> str:
    """caveats.ts が返すキー文字列をそのまま <key> に使う。"""
    return scoped_id("caveat", key, scope)


def caveat_id_cells_note(note_pk, scope: str = "common") -> str:
    return scoped_id("caveat", f"cells.{note_pk}", scope)
