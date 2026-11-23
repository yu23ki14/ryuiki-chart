"""GBIF 経由の iNaturalist 観察と直取得の重複（Issue #125）を求める、b06 と s01 で共有する1か所。

マニフェストの `dedup_against`（`{GBIF 側の出典: 直取得の出典}`）に従い、GBIF 側の行のうち `source_ref` が
直取得側の「occurrence に残る行」の `source_ref` と一致するものを重複とする。b06 はこの集合で行を除き、
s01 はサンプルの宣言件数（b06 と同じ除外）を数える。b06 は別に、SQL の結合で重複件数を独立に数えて突合する
（`b06_build_occurrence._count_duplicates_by_join`。ここの集合の作り方とは別の経路）。

「occurrence に残る」直取得の行 = 合成でなく、不在記録でも未知の状態でもない行（`KEPT_STATUSES`）。
除かれる行の `source_ref` で GBIF 側を除くと、どちらも occurrence に無い観察が出てしまうため。
"""
from __future__ import annotations

import sqlite3

# b06 が occurrence に入れる occurrence_status（NULL は不在の概念が無い出典）。
KEPT_STATUSES = (None, "PRESENT")


def table_columns(conn: sqlite3.Connection, from_sql: str) -> set[str]:
    """`from_sql`（表名か括弧つきの副問い合わせ）の列名。"""
    return {d[0] for d in conn.execute(f"SELECT * FROM {from_sql} LIMIT 0").description}


def kept_where(columns: set[str], alias: str = "") -> str:
    """occurrence に残る行の条件（列がある範囲で。先頭に `AND` を付けない）。"""
    p = f"{alias}." if alias else ""
    parts = ["1=1"]
    if "is_synthetic" in columns:
        parts.append(f"COALESCE({p}is_synthetic, 0) <> 1")
    if "occurrence_status" in columns:
        parts.append(f"({p}occurrence_status IS NULL OR {p}occurrence_status = 'PRESENT')")
    return " AND ".join(parts)


def duplicate_refs(conn: sqlite3.Connection, pairs: dict[str, str], from_sql: str = "organism_records") -> dict[str, frozenset]:
    """`{GBIF 側の出典: 直取得側の残る行と source_ref が一致する source_ref の集合}`。
    `from_sql` は organism_records 相当の表（サンプルの選択行だけの副問い合わせでもよい）。
    source_ref の列が無い表は空の集合（小さなテスト用の表）。source_ref に索引は無いので、Python のハッシュで突き合わせる
    （相関サブクエリは使わない）。"""
    if not pairs:
        return {}
    cols = table_columns(conn, from_sql)
    if "source_ref" not in cols:
        return {sid: frozenset() for sid in pairs}
    direct_ids = sorted(set(pairs.values()))
    marks = ",".join("?" for _ in direct_ids)
    direct: dict[str, set] = {d: set() for d in direct_ids}
    for sid, ref in conn.execute(
        f"SELECT source_id, source_ref FROM {from_sql} WHERE source_id IN ({marks}) "
        f"AND source_ref IS NOT NULL AND source_ref <> '' AND {kept_where(cols)}", direct_ids,
    ):
        direct[sid].add(ref)
    out: dict[str, frozenset] = {}
    for sid, d in sorted(pairs.items()):
        shared = {
            ref for (ref,) in conn.execute(
                f"SELECT source_ref FROM {from_sql} WHERE source_id = ? AND source_ref IS NOT NULL AND source_ref <> ''", (sid,),
            ) if ref in direct[d]
        }
        out[sid] = frozenset(shared)
    return out
