"""レジストリビルドの共通ヘルパ。

- ID 生成（docs/adr/0004-identifiers.md 準拠、Phase A で使う具体形）
- 原本 3 ファイル（ryuiki / cells / derived）を読み取り専用で開く
- registry.sqlite の新規作成（DDL は scripts/schema_registry.sql）と書き込みユーティリティ
- ビルドの指紋（`registry_build` テーブル。phase-b/registry-atomic）: 「在る」ことと
  「正しい」ことを区別するため、`scripts/r01_build_registry.py --check-fresh` が
  作り直しの要否を判定するのに使う

各 build_*.py はここの関数だけを使ってレジストリを書く。原本への書き込みは一切しない
（open_source は読み取り専用でしか開けない）。

`registry.sqlite` 本体への書き込みの原子性（一時ファイルに作ってから os.replace()
で正規パスへ置き換える）は scripts/r01_build_registry.py 側が担う。ここ（common.py）は
一時ファイルパスの命名と後始末のユーティリティだけを持つ（判定・置き換えのオーケストレーションを
r01 側に一本化するため、二重に持たない）。
"""
import hashlib
import os
import re
import sqlite3
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DB_DIR = ROOT / "data" / "db"
SCHEMA_SQL = ROOT / "scripts" / "schema_registry.sql"
REGISTRY_DB = DB_DIR / "registry.sqlite"
# `scripts/r01_build_registry.py --files-only` の既定の書き込み先。正規の REGISTRY_DB
# とは別ファイルにする（`--files-only` は place/taxon/cells由来caveatを持たないスタブなので、
# 正規の registry.sqlite を上書きすると place 4,960/taxon 41,444/caveat 221 件が
# 154 alias だけのスタブに壊れて消える。実害あり・独立レビューで実際に踏まれた事故）。
FILES_ONLY_REGISTRY_DB = DB_DIR / "registry_files_only.sqlite"

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
    """`path`（無ければ REGISTRY_DB）に新規の registry.sqlite を作り、スキーマを流す。

    以前はここで「既存があれば消してから作る」としていたが、`path` に正規の
    `registry.sqlite` を直接渡す呼び出し方だと、この関数を呼んだ時点で前の正しい
    レジストリが消え、その後のビルドやチェックが失敗すると壊れた（または半端な）
    ファイルが正規のパスに残った（実際に踏まれた事故。phase-b/registry-atomic）。
    現在は呼び出し側（scripts/r01_build_registry.py）が `registry_tmp_path()` で
    作った使い捨ての一時ファイルパスをここに渡し、全ステップとチェックが通ってから
    `os.replace()` で正規パスへ置き換える設計にしたので、ここで既存ファイルを
    消す必要が無くなった（一時ファイル名は PID 込みで衝突しない）。
    """
    target = path or REGISTRY_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def registry_tmp_path(target: pathlib.Path) -> pathlib.Path:
    """`target` と同じディレクトリの一時ファイルパスを返す。`os.replace()` で正規パスへ
    原子的に置き換えるには同じファイルシステム上に置く必要がある（`tempfile` の既定の
    一時ディレクトリだと別ファイルシステムになりうる）。PID をファイル名に含めるので、
    同時に走る複数プロセス（並行 worktree 等、別々の RYUIKI_REGISTRY_DB を指していても
    たまたま同じディレクトリを指すような事故のケース）とも衝突しない。
    """
    return target.with_name(f"{target.name}.tmp-{os.getpid()}")


def remove_sqlite_file(path: pathlib.Path) -> None:
    """`path` 本体と、-wal/-shm/-journal の残骸をまとめて消す（無ければ何もしない）。

    一時ファイルの後始末専用（正規の registry.sqlite には使わない）。デフォルトの
    rollback journal モードでは commit + close 後に -journal は残らないはずだが、
    「一時ファイル側に残骸を残さない」という受け入れ基準を機械的に保証するため、
    接続を閉じたあとに明示的に確認して消す。
    """
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = pathlib.Path(f"{path}{suffix}")
        if p.exists():
            p.unlink()


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


def count_and_breakdown(
    conn: sqlite3.Connection, table: str, where_sql: str, group_col: str
) -> tuple[int, list[tuple]]:
    """`table` のうち `where_sql` に一致する行の (総数, group_col別内訳) を
    1クエリで返す。

    以前は「一致する行の総数」と「group_col 別の内訳」を別々の COUNT(*) / GROUP BY
    クエリで打っていた（同じ WHERE 条件を2回スキャンする無駄。scripts/r02_resolution_report.py
    の report_organism・このモジュールの build() 診断ブロックで実際に約400〜1,000ms
    ずつ計測された）。GROUP BY の結果を Python 側で合計するだけで総数も分かるため、
    ここでは GROUP BY の1クエリだけを打つ（/simplify 修正7）。

    戻り値: `(total, breakdown)`。`breakdown` は `[(group_val, n), ...]`（group_val 昇順）。
    """
    rows = conn.execute(
        f"SELECT {group_col}, COUNT(*) AS n FROM {table} WHERE {where_sql} "
        f"GROUP BY {group_col} ORDER BY {group_col}"
    ).fetchall()
    breakdown = [(r[0], r[1]) for r in rows]
    total = sum(n for _, n in breakdown)
    return total, breakdown


# ---------------------------------------------------------------------------
# ビルドの指紋（`registry_build` テーブル。phase-b/registry-atomic）
# ---------------------------------------------------------------------------

# `registry_build.mode`。目的の registry.sqlite が「何から」「どちらのモードで」
# 作られたかを一意に区別する（--files-only は place/taxon 等が空のスタブなので、
# 同じ入力から作っていても full と files_only は別物として扱う）。
MODE_FULL = "full"
MODE_FILES_ONLY = "files_only"


def _fingerprint_source_paths(root: pathlib.Path) -> list[pathlib.Path]:
    """指紋の対象ファイルを決まった順（root からの相対パス文字列でソート）で返す。

    対象は「ビルドの論理（コード）」と「手書きの入力（registry/ 配下）」だけ:
    scripts/schema_registry.sql・scripts/r01_build_registry.py・scripts/registry/*.py・
    registry/ 配下の全ファイル。原本（ryuiki/cells/derived）は対象に**含めない**
    ——読み取り専用で扱っており値が変わる前提が無いうえ、828MB/42MB/449MBを毎回
    ハッシュするコストが見合わない（オーナー判断。phase-b/registry-atomic）。

    存在しないパスは黙って除く（テストが一時ディレクトリに入力の一部だけを
    コピーして使うため）。
    """
    candidates = [
        root / "scripts" / "schema_registry.sql",
        root / "scripts" / "r01_build_registry.py",
        *(root / "scripts" / "registry").glob("*.py"),
        *(p for p in (root / "registry").rglob("*") if p.is_file()),
    ]
    existing = (p for p in candidates if p.exists())
    return sorted(existing, key=lambda p: p.relative_to(root).as_posix())


def compute_input_fingerprint(root: pathlib.Path | None = None) -> str:
    """ビルドの論理と手書きの入力から sha256 を計算する（`_fingerprint_source_paths()`
    が対象を決める）。相対パスと中身を決まった順に連結するので、ファイルの移動や
    リネームも検知する。実行時刻は入れない（決定論。scripts/b01_derived_baseline.py /
    scripts/b04_build_cube.py と同じ理由）。

    `root` を渡すとその配下を対象にする（テスト専用。一時ディレクトリにコピーした
    入力で指紋の変化を確認するため）。省略時はこのリポジトリ（`ROOT`）。
    """
    base = root or ROOT
    h = hashlib.sha256()
    for p in _fingerprint_source_paths(base):
        rel = p.relative_to(base).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# ID 生成（ADR-0004）
# ---------------------------------------------------------------------------

def scoped_id(entity: str, local_key: str, scope: str = "common") -> str:
    """<scope>:<entity>:<local_key>。既定スコープは common（ADR-0004 規約0）。"""
    return f"{scope}:{entity}:{local_key}"


def scope_of(scoped_id_value: str) -> str:
    """`<scope>:<entity>:<local_key>` の `<scope>` 部分を取り出す（ADR-0004）。"""
    scope, sep, _rest = scoped_id_value.partition(":")
    if not sep:
        raise ValueError(f"scoped_id の形が想定外（':' が無い）: {scoped_id_value!r}")
    return scope


def region_id_for_scoped_id(scoped_id_value: str) -> str | None:
    """エンティティの `region_id` 列は、その ID 自身のスコープと一致させる
    （ADR-0022 決定1）。`common:` なら地域非依存として NULL、それ以外はスコープ
    そのもの（例: `jp-14`）。呼び出し側が region_id 用に別の値を持ち回って
    ハードコードするのではなく、実際に発行した ID から機械的に導く
    （地域固有だと分かって scope を変えたのに region_id 列だけ古い値のまま、
    という食い違いを構造的に起こさないため）。
    """
    scope = scope_of(scoped_id_value)
    return None if scope == "common" else scope


_LOCAL_KEY_SAFE = re.compile(r"[A-Za-z0-9_.-]")


def slugify_local_key(raw: str, *, seen: dict | None = None) -> str:
    """出典の生の識別子や学名を ADR-0004 規約4（公開 ID は URI に解決できる形にする）に
    合わせて正規化する。`taxon_id_unresolved()` / `place_id()` の `local` 部分は
    必ずこれを通す（レビュー指摘: 空白・コロン・非ASCIIがそのまま ID に入っていた）。

    規則:
    - 前後の空白を落とし、内部の空白列は `_` に畳む。
    - `:` は `.` に変える（`<scope>:<entity>:<local_key>` の3分割が曖昧にならないよう。
      local_key 側に `:` が残ると分割位置が一意に決まらない）。
    - `/` は `_` に変える。
    - 連続する `_`/`.` は1文字に畳み、前後の `_`/`.` は落とす。
    - それでも残る非ASCII文字・URI的に安全でない記号（`(` `)` `,` `?` 全角文字等）は
      UTF-8 バイト列を percent-encode する（`urllib.parse.unquote` で復元できる。
      **元の文字列を捨てない** — ただし復元用途としては、通常は呼び出し元の行が
      `scientific_name` / `name_ja` 等で原文をそのまま持っているので、そちらを正とする）。

    `seen` に呼び出し側が dict を渡すと、正規化後の slug が別の元文字列（`raw`）から
    生成済みの slug と衝突した場合に例外を投げる（**別々の元キーが同じ slug に
    黙って潰れてはいけない**）。`seen` のキー空間（どの範囲で衝突を見るか）は
    呼び出し側が決める（例: place_id は place_kind・namespace ごとに区切る）。
    """
    if raw is None:
        raise ValueError("slugify_local_key: raw が None")
    s = raw.strip()
    s = re.sub(r"\s+", "_", s)
    s = s.replace(":", ".")
    s = s.replace("/", "_")
    s = re.sub(r"[_.]{2,}", lambda m: m.group(0)[0], s)
    s = s.strip("_.")
    out = []
    for ch in s:
        if _LOCAL_KEY_SAFE.match(ch):
            out.append(ch)
        else:
            out.extend(f"%{b:02X}" for b in ch.encode("utf-8"))
    slug = "".join(out)
    if not slug:
        raise ValueError(
            f"slugify_local_key: {raw!r} が空文字列の slug に潰れた"
            "（空白・区切り記号のみ等）。呼び出し元で明示的な local を用意すること。"
        )
    if seen is not None:
        prev = seen.get(slug)
        if prev is not None and prev != raw:
            raise ValueError(
                f"slugify_local_key: 衝突。{raw!r} と {prev!r} が同じ slug "
                f"{slug!r} に潰れた（黙って同じIDに束ねない）。"
            )
        seen[slug] = raw
    return slug


def variable_id(theme: str, name: str, scope: str = "common") -> str:
    return scoped_id("variable", f"{theme}.{name}", scope)


def place_id(
    place_kind: str,
    namespace: str | None,
    local: str,
    scope: str = "common",
    *,
    seen: dict | None = None,
) -> str:
    """common:place:<kind>.<namespace>-<local>。site は通常 jp-14 スコープ。

    `namespace` に None（または空文字）を渡すと `<namespace>-` を省いて
    `common:place:<kind>.<local>` にする（例: grid01 のように、値そのものが
    ID 全体で一意な出典由来のグリッド）。

    `local` は `slugify_local_key()` を通す（空白・コロン・非ASCII対策。
    レビュー指摘）。`seen` を渡すと、同じ (place_kind, namespace) の中で
    別の元 local が同じ slug に潰れた場合に例外を投げる。
    """
    slug = slugify_local_key(str(local))
    if seen is not None:
        key = (place_kind, namespace)
        bucket = seen.setdefault(key, {})
        prev = bucket.get(slug)
        if prev is not None and prev != local:
            raise ValueError(
                f"place_id 衝突: place_kind={place_kind!r} namespace={namespace!r} の下で "
                f"{local!r} と {prev!r} が同じ slug {slug!r} に潰れた。"
            )
        bucket[slug] = local
    middle = f"{namespace}-{slug}" if namespace else slug
    return scoped_id("place", f"{place_kind}.{middle}", scope)


def taxon_id_gbif(gbif_key, scope: str = "common") -> str:
    return scoped_id("taxon", f"gbif.{gbif_key}", scope)


def taxon_id_unresolved(taxa_pk, scope: str = "common", *, seen: dict | None = None) -> str:
    """v1 の taxa 由来で GBIF 未照合（`gbif_match_type` が EXACT でない、または
    GBIF に照会できていない）もの。`taxa_pk` は `slugify_local_key()` を通す
    （空白・コロン・非ASCII対策。レビュー指摘）。`seen` を渡すと、別の
    `taxa_pk` が同じ slug に潰れた場合に例外を投げる。
    """
    slug = slugify_local_key(str(taxa_pk), seen=seen)
    return scoped_id("taxon", f"ryuiki-taxa.{slug}", scope)


def caveat_id(key: str, scope: str = "common") -> str:
    """caveats.ts が返すキー文字列をそのまま <key> に使う。"""
    return scoped_id("caveat", key, scope)


def caveat_id_cells_note(note_pk, scope: str = "common") -> str:
    return scoped_id("caveat", f"cells.{note_pk}", scope)
