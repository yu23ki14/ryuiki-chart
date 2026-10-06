"""DwC-A の旧 -> 新 ID の対応 CSV（`occurrenceID_mapping.csv`）を書く純粋な関数（Issue #39 Phase C）。

`scripts/x01_dwca.py` は `scripts/common.py`（冒頭で `requests` を import する）を使うので CI の
reconcile ジョブ（requirements.txt だけ）では import できない。テストできるよう、依存の無いこのモジュールに分けた
（`scripts/taxon_namespaces.py` を切り出したのと同じ理由）。
"""
import csv

COLUMNS = ["old_occurrenceID", "new_occurrenceID", "old_eventID", "new_eventID"]


def write_occurrence_id_mapping(path, rows):
    """`occurrenceID_mapping.csv`（列: old_occurrenceID,new_occurrenceID,old_eventID,new_eventID）。
    occurrenceID の旧 -> 新は 1 対 1（重複すれば止まる）。eventID は複数の occurrence で共有されうるので
    重複を許すが、同じ旧 eventID が別の新 eventID に写ることは許さない。"""
    olds = [r[0] for r in rows]
    news = [r[1] for r in rows]
    if len(set(olds)) != len(olds) or len(set(news)) != len(news):
        raise SystemExit("occurrenceID の旧->新が1対1でない（record_id か公開 ID が重複している）")
    ev: dict[str, str] = {}
    for _o, _n, old_ev, new_ev in rows:
        if ev.setdefault(old_ev, new_ev) != new_ev:
            raise SystemExit(f"同じ旧 eventID {old_ev!r} が複数の新 eventID に写っている")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows(rows)
