"""unit / variable / variable_alias を作る（docs/plans/PHASE_A.md §A-2）。

対象: measurements.variable（58種）と sensor_timeseries.datastream（59種）の
出典表記をエイリアスとして束ね、名前から単位・粒度・統計量を剥がした正準 variable
（ADR-0010）を作る。domain.ts の VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE /
VARIABLE_UNIT_FALLBACK の内容をここに移す。

# TODO: A-2 担当
"""
import sqlite3


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。

    # TODO: A-2 担当。registry/common.py の unit_id() / variable_id() を使って
    # unit / variable / variable_alias の3テーブルに行を入れる。
    """
    return {}
