"""旧 ID → 新 ID の対応表（`registry/id_map/<entity>.csv`）の読み込みと検査
（ADR-0004 規約2。Issue #39 Phase C、docs/plans/ISSUE39_PHASE_C.md §2.5）。

`id_map` は「ID の改称」の記録。置換（`superseded_by`）とは別物で、混ぜない。
CSV は**手書きの宣言ファイル**（列: `old_id,new_id,reason,spec_version`）。
一度だけ旧ビルダーの出力から生成してコミットし、以後は人が触らない。
ビルダーは毎回、新ビルダーが実際に出した ID と宣言が一致することを検査し、
食い違えば止める（宣言済み差分を機械検証する運用）。

検査（`verify_place_id_map()`）:
1. 宣言の形: old_id・new_id が空でない / old_id が一意（new_id は重複してよい。1つの ID に旧 ID が
   複数向くことがある。例: zone の昇格前の2形式）。
2. 「再利用しない」: old_id が現行の place_id として発行されていない
   （廃止した ID を別のものに使い回すと、古いリンク・外部の引用が別物を指す）。
3. 規則との一致（汎用）: old_id の scope を new_id の scope に置き換えたものが、区切り（`-`/`.`）を除いて
   new_id と一致する（宣言が手でずれたときに止める）。scope が違ってよいのは、`PROMOTED_FROM` に
   「その kind は旧 scope から昇格した」と明示した組だけ（`jp-46:place:zone.r2r.1` のような誤った行を通さない）。
   scope が同じで old_id == new_id の行（改称になっていない）は止める。
4. 網羅: 区切りが変わった kind（site/watershed/zone）の現行 place_id は
   すべて new_id に宣言されている（宣言漏れで旧 ID が受理されなくならない）。
   逆に new_id は現行 place に実在する。
   ただし対象は「改定時に存在した出典」の place だけ。区切り改定（spec 2026-10-issue39）より後に
   できた出典（奄美など）の place には旧 ID が存在せず、宣言すると存在しなかった旧 ID を作ることになる。
   改定時の出典の集合は定数で持たず、id_map の new_id が指す place の出典
   （`place_source_ref` → `source_edition.source_id`。`place_sources` 引数）から導く。
   出典が分からない place は従来どおり宣言を要求する。
"""
import csv
import pathlib

from . import common

ID_MAP_DIR = pathlib.Path(__file__).resolve().parents[2] / "registry" / "id_map"

ID_MAP_COLUMNS = ("old_id", "new_id", "reason", "spec_version")

# ADR-0004 規約1 の改定（ns と key の区切りを `-` から `.` へ）で ID が変わる place_kind。
# grid01 は ns を持たず恒等。
PLACE_KINDS_RENAMED = frozenset({"site", "watershed", "zone"})

# 定義が地域に依存しなくなって昇格した place_kind の、昇格前の scope（同じ実体の ID の改称。
# AMAMI_STEP0 §2、ADR-0004 日付付き追記）。zone は `jp-14:` から `common:` に昇格した。
# 昇格前の ID は 2 形式ある（区切り改定前の `…zone.r2r-N` と、改定後・昇格前の `…zone.r2r.N`）。
PROMOTED_FROM = {"zone": "jp-14"}


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


def _strip_separators(local: str) -> str:
    return local.replace("-", "").replace(".", "")


def old_id_problem(old: str, new: str) -> str | None:
    """old_id が new_id の改称として規則どおりか。問題があれば理由（文字列）、なければ None。
    old_id は旧形式（`-` 区切り）を含むので `common.parse_id` は使わず、`<scope>:<entity>:<local>` に切るだけ。"""
    old_scope, e1, old_local = _split_id(old)
    new_p = common.parse_id(new)
    if e1 != new_p.entity:
        return f"entity が違う: old={old} new={new}"
    if old_scope != new_p.scope:
        if PROMOTED_FROM.get(new_p.kind) != old_scope:
            return (f"scope が違うが、{new_p.kind!r} の昇格前の scope として宣言されていない"
                    f"（PROMOTED_FROM={PROMOTED_FROM}）: old={old} new={new}")
    elif old == new:
        return f"改称になっていない（old_id == new_id）: {old}"
    if _strip_separators(old_local) != _strip_separators(new_p.local):
        return f"区切りを除いて一致しない: old={old} new={new}"
    return None


def _split_id(id_value: str) -> tuple[str, str, str]:
    scope, _, rest = id_value.partition(":")
    entity, _, local = rest.partition(":")
    return scope, entity, local


def verify_place_id_map(rows: list[dict], place_ids: set[str] | None,
                        place_sources: dict[str, set[str]] | None = None) -> None:
    """`rows`（place.csv）が現行の `place_ids`（place テーブルの place_id 全件）と
    整合していることを検査する。食い違いがあれば AssertionError。

    `place_ids=None`（`--files-only`。place を作らない）のときは、現行 place に依存しない検査
    （空でない・old/new の一意・new が新形式・old が規則どおり）だけを行う。

    `place_sources`: place_id -> その place の出典（source_id）の集合。与えたとき、網羅の検査は
    「宣言済みの new_id が指す place の出典」から出た place だけが対象になる（新しい出典の place は対象外）。"""
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
        new_seen.setdefault(new, i)
        if place_ids is not None and old in place_ids:
            problems.append(
                f"{i} 行目: 旧 ID が現行の place_id として発行されている"
                f"（廃止した ID を再利用しない。ADR-0004 規約2）: {old}"
            )
        # new_id が現行の place に実在するかは見ない（縮小サンプルのように、宣言より少ない place しか
        # 作らない環境がある。旧 ID の受理は place の有無に関わらず恒久的に宣言どおりに効く）。
        # 代わりに、new_id が新形式として分解でき、old_id が規則から導けることは常に検査する。
        try:
            why = old_id_problem(old, new)
        except ValueError as e:
            problems.append(f"{i} 行目: new_id が新形式として分解できない: {e}")
        else:
            if why:
                problems.append(f"{i} 行目: old_id が規則（scope を new_id に置き換え、区切りを除いて一致）と合わない: {why}")
    declared_new = set(new_seen)
    legacy_sources: set[str] | None = None
    if place_sources is not None:
        legacy_sources = set().union(*(place_sources.get(n, set()) for n in declared_new))
    for pid in sorted(place_ids or ()):
        try:
            p = common.parse_id(pid)
        except ValueError as e:
            problems.append(f"現行の place_id が新形式として分解できない: {e}")
            continue
        if legacy_sources is not None:
            srcs = place_sources.get(pid)
            if srcs and not (srcs & legacy_sources):
                continue   # 改定より後にできた出典だけの place。旧 ID は存在しない
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
    place_sources = None
    if full:
        place_sources = {}
        for pid, sid in conn.execute(
            "SELECT psr.place_id, e.source_id FROM place_source_ref psr "
            "JOIN source_edition e ON e.edition_id = psr.source_edition_id"
        ):
            place_sources.setdefault(pid, set()).add(sid)
    verify_place_id_map(place_rows, place_ids, place_sources)
    verify_dataset_id_map(dataset_rows, conn)
    sql = "INSERT INTO id_map (entity, old_id, new_id, reason, spec_version) VALUES (?, ?, ?, ?, ?)"
    for entity, rows in (("place", place_rows), ("dataset", dataset_rows)):
        conn.executemany(sql, [(entity, r["old_id"], r["new_id"], r["reason"], r["spec_version"]) for r in rows])
    conn.commit()
    return {"place": len(place_rows), "dataset": len(dataset_rows)}
