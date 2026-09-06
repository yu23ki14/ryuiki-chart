"""taxon を作る（docs/plans/PHASE_A.md §A-4・最大の難所）。

organism_records の distinct taxon_key（33,604件）は common:taxon:gbif.<key> で解決する。
taxa（8,585件）のうち GBIF 未照合の 5,908件は status='unresolved' として捨てずに登録する
（scripts/c24_taxon_crosswalk.py の成果を再利用）。和名は domain.ts の NAME_JA（人が確認した
54種）だけを正として移し、taxa の和名を学名で機械結合しない。

# TODO: A-4 担当
"""
import sqlite3


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。

    # TODO: A-4 担当。registry/common.py の taxon_id_gbif() / taxon_id_unresolved() を
    # 使って taxon テーブルに行を入れる。
    """
    return {}
