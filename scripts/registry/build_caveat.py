"""caveat を作る（docs/plans/PHASE_A.md §A-5）。

domain.ts の DATA_CAVEATS（7件）・BIOTA_CAVEATS（6件）・MUNICIPALITY_LABEL の説明、
caveats.ts のテーブル→注記マッピング（scope_kind='table' の行として表現）、
cells.notes（207行）を caveat に移す。文言は変えない（変えると A-1 で先に固定した
web/src/lib/ai/caveats.test.ts の回帰テストが意味を失う）。新しい注記は書き足さない。

# TODO: A-5 担当
"""
import sqlite3


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。

    # TODO: A-5 担当。registry/common.py の caveat_id() / caveat_id_cells_note() を
    # 使って caveat テーブルに行を入れる。
    """
    return {}
