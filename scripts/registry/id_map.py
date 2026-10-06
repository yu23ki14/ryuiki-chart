"""旧 ID → 新 ID の対応表（`registry/id_map/<entity>.csv`）の読み込みと検査
（ADR-0004 規約2。Issue #39 Phase C、docs/plans/ISSUE39_PHASE_C.md §2.5）。

`id_map` は「ID の改称」の記録。置換（`superseded_by`）とは別物で、混ぜない。
CSV は**手書きの宣言ファイル**（列: `old_id,new_id,reason,spec_version`）。
一度だけ旧ビルダーの出力から生成してコミットし、以後は人が触らない。
ビルダーは毎回、新ビルダーが実際に出した ID と宣言が一致することを検査し、
食い違えば止める（宣言済み差分を機械検証する運用）。

検査（`verify_place_id_map()`）:
1. 宣言の形: old_id・new_id が空でない / old_id が一意 / new_id が一意（1対1）。
2. 「再利用しない」: old_id が現行の place_id として発行されていない
   （廃止した ID を別のものに使い回すと、古いリンク・外部の引用が別物を指す）。
3. 規則との一致: old_id は new_id の最初の `.`（ns と key の区切り）を `-` に
   戻したものと一致する（旧形式の定義。宣言が手でずれたときに止める）。
4. 網羅: 区切りが変わった kind（site/watershed/zone）の現行 place_id は
   すべて new_id に宣言されている（宣言漏れで旧 ID が受理されなくならない）。
   逆に new_id は現行 place に実在する。
"""
import csv
import pathlib

from . import common

ID_MAP_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "id_map"

ID_MAP_COLUMNS = ("old_id", "new_id", "reason", "spec_version")

# ADR-0004 規約1 の改定（ns と key の区切りを `-` から `.` へ）で ID が変わる place_kind。
# grid01 は ns を持たず恒等。
PLACE_KINDS_RENAMED = frozenset({"site", "watershed", "zone"})


def load_csv(entity: str, directory: pathlib.Path | None = None) -> list[dict]:
    """`registry/id_map/<entity>.csv` を読む。列は `ID_MAP_COLUMNS` と一致していること。"""
    path = (directory or ID_MAP_DIR) / f"{entity}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != ID_MAP_COLUMNS:
            raise AssertionError(
                f"{path}: 列が {ID_MAP_COLUMNS} と一致しない: {reader.fieldnames}"
            )
        return list(reader)


def legacy_place_id(new_id: str) -> str:
    """新形式の place_id から旧形式（ns と key を `-` でつないだもの）を再構成する。
    宣言（CSV）が規則からずれていないかの検査にだけ使う（受理の経路には使わない。
    受理は CSV 由来の表を引く）。"""
    p = common.parse_id(new_id)
    if p.ns is None:
        return new_id
    return f"{p.scope}:{p.entity}:{p.kind}.{p.ns}-{p.key}"


def verify_place_id_map(rows: list[dict], place_ids: set[str]) -> None:
    """`rows`（place.csv）が現行の `place_ids`（place テーブルの place_id 全件）と
    整合していることを検査する。食い違いがあれば AssertionError。"""
    problems: list[str] = []
    old_seen: dict[str, int] = {}
    new_seen: dict[str, int] = {}
    for i, r in enumerate(rows, start=2):  # 2 = ヘッダーの次の行
        old, new = r["old_id"], r["new_id"]
        if not old or not new:
            problems.append(f"{i} 行目: old_id/new_id が空")
            continue
        if old in old_seen:
            problems.append(f"{i} 行目: old_id が重複（{old_seen[old]} 行目と同じ）: {old}")
        old_seen[old] = i
        if new in new_seen:
            problems.append(f"{i} 行目: new_id が重複（{new_seen[new]} 行目と同じ）: {new}")
        new_seen[new] = i
        if old in place_ids:
            problems.append(
                f"{i} 行目: 旧 ID が現行の place_id として発行されている"
                f"（廃止した ID を再利用しない。ADR-0004 規約2）: {old}"
            )
        if new not in place_ids:
            problems.append(f"{i} 行目: new_id が現行の place に無い: {new}")
        else:
            try:
                expected_old = legacy_place_id(new)
            except ValueError as e:
                problems.append(f"{i} 行目: new_id が新形式として分解できない: {e}")
            else:
                if expected_old != old:
                    problems.append(
                        f"{i} 行目: old_id が規則（ns と key の区切りを `-` に戻した形）と"
                        f"一致しない: old={old} 期待={expected_old}"
                    )
    declared_new = set(new_seen)
    for pid in sorted(place_ids):
        try:
            p = common.parse_id(pid)
        except ValueError as e:
            problems.append(f"現行の place_id が新形式として分解できない: {e}")
            continue
        if p.kind in PLACE_KINDS_RENAMED and pid not in declared_new:
            problems.append(f"現行の place_id が id_map/place.csv に宣言されていない: {pid}")
    if problems:
        head = "\n  ".join(problems[:20])
        raise AssertionError(
            f"registry/id_map/place.csv が現行の place と整合しない（{len(problems)} 件）:\n  {head}"
        )
