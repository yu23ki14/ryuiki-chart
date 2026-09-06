"""place / place_source_ref を作る（docs/plans/PHASE_A.md §A-3）。

対象: site（sites 352件 + sensor_timeseries/measurements 側で不足する分）、
watershed（watershed_meta 377件）、mesh3（mesh_all 4,083件）、
zone（docs/ZONE_DEFINITION.md 5件）。town_block と river_segment は Phase A では
登録しない。place_source_ref で v1 の site_id / watershed_id / mlat,mlon を
引けるようにする（ADR-0006）。

# TODO: A-3 担当
"""
import sqlite3


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。

    # TODO: A-3 担当。registry/common.py の place_id() を使って
    # place / place_source_ref の2テーブルに行を入れる。
    """
    return {}
