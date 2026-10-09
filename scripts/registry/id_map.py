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
   ただし `SCOPE_PROMOTED_KINDS`（zone）の new_id が `common:` のときは、old_id のスコープだけが違ってよく
   （`jp-14:place:zone.r2r-N` 形、または `jp-14:place:zone.r2r.N` 形）、1つの new_id に旧 ID を最大2つ向けてよい。
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

# 定義が地域に依存しなくなって `jp-14:` から `common:` に昇格した place_kind（同じ実体の ID の改称。
# AMAMI_STEP0 §2、ADR-0004 日付付き追記）。これらの new_id には旧 ID が最大2つ向く
# （区切り改定前の `jp-14:place:zone.r2r-N` と、改定後・昇格前の `jp-14:place:zone.r2r.N`）。
# 旧 ID は一意のまま、new_id の重複はこの種別の昇格先に限って許す。
SCOPE_PROMOTED_KINDS = frozenset({"zone"})
PROMOTED_TO_SCOPE = "common"
MAX_OLD_IDS_PER_PROMOTED_NEW_ID = 2


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


def _is_promoted(new_id: str) -> bool:
    """new_id が `jp-14:` → `common:` に昇格した種別（zone）の現行 ID か。"""
    try:
        p = common.parse_id(new_id)
    except ValueError:
        return False
    return p.entity == "place" and p.kind in SCOPE_PROMOTED_KINDS and p.scope == PROMOTED_TO_SCOPE


def _promoted_old_forms(new_id: str, old_id: str) -> set[str]:
    """昇格した new_id に対し、old_id のスコープ（`common` 以外）を保った旧形式2つ
    （区切り改定前の `-` 形と、改定後・昇格前の `.` 形）。"""
    old_scope = old_id.split(":", 1)[0]
    if old_scope == PROMOTED_TO_SCOPE:
        return set()
    p = common.parse_id(new_id)
    return {
        f"{old_scope}:{p.entity}:{p.kind}.{p.ns}-{p.key}",
        f"{old_scope}:{p.entity}:{p.kind}.{p.ns}.{p.key}",
    }


def verify_place_id_map(rows: list[dict], place_ids: set[str] | None) -> None:
    """`rows`（place.csv）が現行の `place_ids`（place テーブルの place_id 全件）と
    整合していることを検査する。食い違いがあれば AssertionError。

    `place_ids=None`（`--files-only`。place を作らない）のときは、現行 place に依存しない検査
    （空でない・old/new の一意・new が新形式・old が規則どおり）だけを行う。"""
    problems: list[str] = []
    old_seen: dict[str, int] = {}
    new_seen: dict[str, int] = {}
    new_count: dict[str, int] = {}
    for i, r in enumerate(rows, start=2):  # 2 = ヘッダーの次の行
        old, new = r["old_id"], r["new_id"]
        if not old or not new:
            problems.append(f"{i} 行目: old_id/new_id が空")
            continue
        if old in old_seen:
            problems.append(f"{i} 行目: old_id が重複（{old_seen[old]} 行目と同じ）: {old}")
        old_seen[old] = i
        if new in new_seen and not _is_promoted(new):
            problems.append(f"{i} 行目: new_id が重複（{new_seen[new]} 行目と同じ）: {new}")
        new_seen.setdefault(new, i)
        new_count[new] = new_count.get(new, 0) + 1
        if _is_promoted(new) and new_count[new] > MAX_OLD_IDS_PER_PROMOTED_NEW_ID:
            problems.append(f"{i} 行目: 昇格先の new_id に旧 ID が{MAX_OLD_IDS_PER_PROMOTED_NEW_ID}つより多く向いている: {new}")
        if place_ids is not None and old in place_ids:
            problems.append(
                f"{i} 行目: 旧 ID が現行の place_id として発行されている"
                f"（廃止した ID を再利用しない。ADR-0004 規約2）: {old}"
            )
        # new_id が現行の place に実在するかは見ない（縮小サンプルのように、宣言より少ない place しか
        # 作らない環境がある。旧 ID の受理は place の有無に関わらず恒久的に宣言どおりに効く）。
        # 代わりに、new_id が新形式として分解でき、old_id が規則から導けることは常に検査する。
        try:
            expected_old = legacy_place_id(new)
        except ValueError as e:
            problems.append(f"{i} 行目: new_id が新形式として分解できない: {e}")
        else:
            if _is_promoted(new) and old in _promoted_old_forms(new, old):
                pass
            elif expected_old != old:
                problems.append(
                    f"{i} 行目: old_id が規則（ns と key の区切りを `-` に戻した形）と"
                    f"一致しない: old={old} 期待={expected_old}"
                )
    declared_new = set(new_seen)
    for pid in sorted(place_ids or ()):
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


def verify_dataset_id_map(rows: list[dict], conn) -> None:
    """`rows`（dataset.csv。旧 `<dataset>@<年>` -> 版の ID）が variable_alias の
    `(dataset, edition_key)` の集合と過不足なく一致し、`new_id` が版の ID の規則どおりであること。
    `source_edition` が空でなければ（full ビルド）new_id の実在も検査する。"""
    problems: list[str] = []
    for col in ("old_id", "new_id"):
        values = [r[col] for r in rows]
        if len(set(values)) != len(values):
            problems.append(f"{col} が重複している（旧 -> 新は 1 対 1）")
    mapped: set[tuple[str, str]] = set()
    have_editions = conn.execute("SELECT count(*) FROM source_edition").fetchone()[0] > 0
    for r in rows:
        ds, sep, key = r["old_id"].partition("@")
        if not (sep and ds and key):
            problems.append(f"old_id が <dataset>@<年> の形ではない: {r['old_id']!r}")
            continue
        expected = common.edition_id(ds, key)
        if r["new_id"] != expected:
            problems.append(f"old_id={r['old_id']!r} の new_id={r['new_id']!r} が {expected!r} ではない")
        elif have_editions and conn.execute(
            "SELECT 1 FROM source_edition WHERE edition_id = ?", (r["new_id"],)
        ).fetchone() is None:
            problems.append(f"new_id={r['new_id']!r} が source_edition に無い")
        mapped.add((ds, key))
    in_alias = set(conn.execute(
        "SELECT DISTINCT dataset, edition_key FROM variable_alias WHERE edition_key IS NOT NULL"
    ))
    if in_alias != mapped:
        problems.append(
            "variable_alias の (dataset, edition_key) と一致しない: "
            f"alias のみ={sorted(in_alias - mapped)} / id_map のみ={sorted(mapped - in_alias)}"
        )
    if problems:
        raise AssertionError("registry/id_map/dataset.csv が整合しない:\n  " + "\n  ".join(problems))


def build_id_map(conn, *, full: bool, directory: pathlib.Path | None = None) -> dict[str, int]:
    """`registry/id_map/{place,dataset}.csv` を1回だけ読み、検査し、`id_map` 表に載せる。

    原本は要らないので `--files-only` でも作る（`full=False`: place の現行 ID 依存の検査だけ省く。
    CI の生成物検査〔generated-id-map.ts〕が空のマップで上書きされないため）。
    """
    place_rows = load_csv("place", directory)
    dataset_rows = load_csv("dataset", directory)
    place_ids = {r[0] for r in conn.execute("SELECT place_id FROM place")} if full else None
    verify_place_id_map(place_rows, place_ids)
    verify_dataset_id_map(dataset_rows, conn)
    sql = "INSERT INTO id_map (entity, old_id, new_id, reason, spec_version) VALUES (?, ?, ?, ?, ?)"
    for entity, rows in (("place", place_rows), ("dataset", dataset_rows)):
        conn.executemany(sql, [(entity, r["old_id"], r["new_id"], r["reason"], r["spec_version"]) for r in rows])
    conn.commit()
    return {"place": len(place_rows), "dataset": len(dataset_rows)}
