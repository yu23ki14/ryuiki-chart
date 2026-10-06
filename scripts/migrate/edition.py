"""ファクトの `source_edition_id` を解決する（ADR-0005、Issue #39 Phase C）。

唯一の入口は `resolve_edition(editions, source_id, *, vintage=None)`。`editions` は
`load_editions(conn)` が `registry.sqlite` の `source_edition` から作る索引。

- `vintage` を渡すと、その source の edition のうち `vintage`（または `edition_key`）が
  一致するものを返す（土地利用は `data_year` を渡す）。一致が 1 件でなければ止まる。
- `vintage` を渡さないと、その source の**唯一の** edition を返す。edition が複数ある source
  （版を持つ出典。現在は土地利用の流域別集計だけ）を `vintage` 無しで引くと止まる
  （どの版か黙って選ばない）。edition が 0 件の source も止まる。

解決のロジックはこの 1 関数に置く。b03/b06 は `source_id` の文字列から edition を組み立てず、
必ずここを通す。
"""
import sqlite3

from . import common


class EditionResolutionError(common.MigrationError):
    """source_id（と vintage）から edition を一意に決められない。"""


def load_editions(conn: sqlite3.Connection, schema: str = "main") -> dict[str, list[tuple[str, str, str | None]]]:
    """`{source_id: [(edition_id, edition_key, vintage), ...]}`（edition_id 昇順）。

    `schema` は registry.sqlite を ATTACH している名前（b03 は `reg`）。
    """
    index: dict[str, list[tuple[str, str, str | None]]] = {}
    for edition_id, source_id, edition_key, vintage in conn.execute(
        f"SELECT edition_id, source_id, edition_key, vintage FROM {schema}.source_edition ORDER BY edition_id"
    ):
        index.setdefault(source_id, []).append((edition_id, edition_key, vintage))
    return index


def resolve_edition(editions: dict, source_id: str, *, vintage: str | None = None) -> str:
    """`source_edition.edition_id` を返す。解決できなければ `EditionResolutionError`。"""
    candidates = editions.get(source_id)
    if not candidates:
        raise EditionResolutionError(f"source_id={source_id!r} の edition が registry.source_edition に無い")
    if vintage is None:
        if len(candidates) != 1:
            raise EditionResolutionError(
                f"source_id={source_id!r} は edition を {len(candidates)} 個持つ（"
                f"{[c[0] for c in candidates]}）。vintage を渡して版を指定すること"
            )
        return candidates[0][0]
    v = str(vintage)
    matched = [c for c in candidates if c[2] == v or c[1] == v]
    if len(matched) != 1:
        raise EditionResolutionError(
            f"source_id={source_id!r} vintage={v!r} に一致する edition が {len(matched)} 個"
            f"（候補: {[c[0] for c in candidates]}）"
        )
    return matched[0][0]


def make_resolver(conn: sqlite3.Connection, schema: str = "main"):
    """`resolve(source_id, *, vintage=None) -> edition_id | None` を返す（出典・版ごとにキャッシュ）。

    b03・b06・registry の build_place が使う唯一の入口（それぞれが自前のラッパーを持たない）。
    `source_id is None`（出典未記録の行）は None。解決できなければ `EditionResolutionError`
    （`MigrationError` の一種。黙って選ばない・黙って NULL にしない）。
    """
    index = load_editions(conn, schema)
    cache: dict = {}

    def resolve(source_id, *, vintage=None):
        if source_id is None:
            return None
        key = (source_id, vintage)
        if key not in cache:
            try:
                cache[key] = resolve_edition(index, source_id, vintage=vintage)
            except EditionResolutionError as e:
                raise EditionResolutionError(f"source_edition_id を決められない: {e}") from e
        return cache[key]

    return resolve
