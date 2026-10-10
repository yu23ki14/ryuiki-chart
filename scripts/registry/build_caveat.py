"""caveat を作る（docs/plans/PHASE_A.md §A-5、Issue #35 で宣言ファイル化）。

入力は3つ。
  - `registry/caveat.yaml`: 注記そのもの（key・severity・kind・本文・引用・`review`）。
  - `registry/caveat_scope.yaml`: どの注記がどの範囲に掛かるか（scope の宣言）。**このファイルは
    それを読んで検査し、`caveat_scope` に書くだけ**（以前は Python 定数だった。Issue #35）。
  - `cells.sqlite` の `notes`（207行）: 行政文書の注記。`build()` だけが足す。

文言は変えない方針（Phase A）だったが、Issue #35 のレビュー（`review` 参照）で数値の誤りを直した。
経緯の古い記述（`censored` の撤去・v1 表の撤去など）は `docs/plans/V2_SERVING_PR5.md` §4.3 を参照。

## スキーマ（計画の7テーブル→8テーブル）

`caveat`（注記そのもの: `caveat_id` PK・`severity`・`kind`・`title_ja`・`body_ja`・`quote`）と
`caveat_scope(id, caveat_id, scope_kind, scope_ref, sort_order, priority)`（1注記 : N スコープ）に
分けた（1つの注記が複数の範囲に掛かるため）。

## `caveat_scope.scope_kind` と `scope_ref`（ADR-0013「scope の語彙」）

`scope_kind` は ADR-0013 の6種（`variable`/`place`/`source_edition`/`observation_set`/`dataset`/`taxon`）。
`scope_ref` は ID そのもの、または `キー=値`（`&` 連結）の選択式。選択式のキーは
`registry/caveat_scope.yaml` の `selectors` が kind ごとに許すものだけ。実行時の照合は文字列の完全一致。

旧語彙との対応: `table:sites`→`dataset:sites`、`place_kind:X`→`place:place_kind=X`、
`source_id:X`→`source_edition:source_id=X`、`variable_theme:X`→`variable:theme=X`、
`dataset:synthetic`→`observation_set:is_synthetic=1`、`cell:<doc>`→`source_edition:doc_id=<doc>`、
`cell_table:<doc>#<t>`→`observation_set:doc_table=<doc>#<t>`。`table_prefix` は廃止。

**優先度は `scope_kind` ではなく `priority` 列（既定0）が持つ。** synthetic の scope だけが1。
`sort_order` は「同じ `(scope_kind, scope_ref)` の中での宣言順」。読み出し側は
`(priority 降順, 参照の初出順 昇順, sort_order 昇順)` で並べ、caveat の key で先勝ち重複排除する
（`web/src/lib/registry/lookup-client.ts` の `resolveCaveatRefs`）。

## ビルド時の検査（失敗すれば `CaveatDeclarationError`）

- `caveat.yaml`: key の一意・全注記に完全な `review`（reviewed_on/reviewer/owner_confirmed_on/reason/changed）。
- `caveat_scope.yaml`: kind が vocabulary 内・`caveats` の key が `caveat.yaml` に存在・
  (kind, ref, caveat) の重複なし・選択式のキーが `selectors` の許可内・
  ID 参照（variable）が `variable.yaml` に存在・選択式の値（theme/variable/place_kind/source_id 等）と dataset 名が実在値・
  `ref_from` が既知の導出器（導出が空になった注記は黙って消さず、scopes か unscoped を要求する）・全注記がどこかの scope に載っている
  （意図して付けないものは `unscoped` に宣言する。休眠の synthetic は scopes に載せる）。

## cells.notes（207行）の取り込み

`notes` の列: `note_id`（177/207行で非NULL）, `doc_id`（全行）, `table_ids`（JSON配列。59行が非空）,
`kind`（`definition_change`/`footnote`/`comparability`/`survey_scope`/NULL）, `text`（原文引用）,
`blocks_timeseries`（0/1）, `reason`（このプロジェクトが付けた説明）。

- `caveat_id`: `common:caveat:cells.<note_id>`。`note_id` が NULL の30行は `"rowid<rowid>"`。
- `severity`: `blocks_timeseries` 1→`'blocking'`、0→`'info'`（原本の人の区分で、機械分類ではない）。
- `kind`: `notes.kind` をそのまま（enum 外の3値は ADR-0013 に追記して正式化。丸めない）。
- `body_ja`: `notes.reason`、`quote`: `notes.text`（原文は要約しない）。
- scope: `source_edition` の `doc_id=<doc_id>` を1行、`table_ids` の要素ごとに
  `observation_set` の `doc_table=<doc_id>#<table_id>`。
  cells.notes は配信側の `GENERATED_CAVEAT_SCOPE`（`build-registry-ts.mjs`）には含めない
  （`caveat_id` が `cells.` で始まるものを除外する）。
"""
import csv
import json
import pathlib
import sqlite3

import yaml

from . import common
from .build_unit_variable import VARIABLE_ALIAS_CSV, VARIABLE_YAML

CAVEAT_YAML = common.ROOT / "registry" / "caveat.yaml"
CAVEAT_SCOPE_YAML = common.ROOT / "registry" / "caveat_scope.yaml"

DEFAULT_PRIORITY = 0

REVIEW_FIELDS = ("reviewed_on", "reviewer", "owner_confirmed_on", "reason", "changed")
# オーナーの確認待ち（review.owner_confirmed_on が null）を許す注記の key。**ここに無い注記の null は止める**
# （確認済みだった注記を null に戻すと、確認の記録が黙って消えるため）。確認したら日付を入れて、ここから外す。
OWNER_PENDING_KEYS = frozenset({"amamiRedList", "amamiWatershedGap"})
REVIEW_CHANGED_VALUES = {"severity", "kind", "scope", "body", "new"}


class CaveatDeclarationError(ValueError):
    """`registry/caveat.yaml`・`registry/caveat_scope.yaml` の宣言が検査に通らない。"""


def _unit_unknown_variable_refs() -> list[str]:
    """`unitUnknown` の対象 variable_id を `registry/variable_alias.csv` から機械的に導出する
    （ハードコードしない）。`unit_id` 列が空の行の `variable_id` を、CSV の行順で重複排除する。
    原本 DB は開かない（`--files-only` 安全）。

    実測（2026-09-26）: 10行が variable_id 8件に畳まれる。
    """
    refs: list[str] = []
    seen: set[str] = set()
    with VARIABLE_ALIAS_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("unit_id"):
                continue
            variable_id = row.get("variable_id") or None
            if variable_id is None or variable_id in seen:
                continue
            seen.add(variable_id)
            refs.append(variable_id)
    return refs


# `ref_from` の名前 → 導出器（variable_id のリストを返す）。宣言は yaml、導出はここ。
REF_DERIVERS = {"unit_unknown_variables": _unit_unknown_variable_refs}


def _validate_review(key: str, review) -> None:
    if not isinstance(review, dict):
        raise CaveatDeclarationError(f"caveat {key!r}: review が無い（Issue #35: 全注記に人のレビュー記録が要る）")
    missing = [f for f in REVIEW_FIELDS if f not in review or review[f] in (None, "")]
    # changed は false（変更なし）が正当な値なので、None/空だけを欠落とみなす。
    # owner_confirmed_on は、キーがあれば null（オーナーの確認待ち）でもよい（奄美 Step 1 PR-B）。キー自体が無いのは欠落
    # null は OWNER_PENDING_KEYS の注記だけ許す。空文字は常に欠落。
    missing = [f for f in missing if not (f == "changed" and review.get(f) is False)
               and not (f == "owner_confirmed_on" and review.get(f) is None
                        and f in review and key in OWNER_PENDING_KEYS)]
    if missing:
        raise CaveatDeclarationError(f"caveat {key!r}: review に {missing} が無い")
    changed = review["changed"]
    if changed is not False:
        if not isinstance(changed, list) or not changed or not set(changed) <= REVIEW_CHANGED_VALUES:
            raise CaveatDeclarationError(
                f"caveat {key!r}: review.changed は false か {sorted(REVIEW_CHANGED_VALUES)} のリスト（実際: {changed!r}）"
            )


def _load_caveat_yaml() -> list[dict]:
    with CAVEAT_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["caveats"]
    common.assert_unique([e["key"] for e in entries], "registry/caveat.yaml の key")  # Issue #37 #4
    for e in entries:
        _validate_review(e["key"], e.get("review"))
    return entries


def _build_caveat_rows(entries: list[dict]) -> list[tuple]:
    rows = []
    for e in entries:
        rows.append(
            (
                common.caveat_id(e["key"]),
                e.get("severity"),
                e.get("kind"),
                e.get("title_ja"),
                e["body_ja"],
                e.get("quote"),
            )
        )
    return rows


def _load_variable_ids_and_themes() -> tuple[set[str], set[str]]:
    with VARIABLE_YAML.open(encoding="utf-8") as f:
        variables = yaml.safe_load(f)["variables"]
    return {v["variable_id"] for v in variables}, {v["theme"] for v in variables if v.get("theme")}


MANIFESTS_DIR = common.ROOT / "manifests"


def _manifest_source_ids() -> set[str]:
    """`manifests/<source_id>.yml` がある出典の ID（registry の source 表に載る出典。ファイルだけで引けるので
    原本を開かない --files-only でも検査できる）。source_id の選択式は、`values.source_id`
    （taxon_assessment 由来の moe_ias_list 等）とこの集合の和に対して検査する。"""
    return {p.stem for p in MANIFESTS_DIR.glob("*.yml")}


def _validate_ref(kind: str, ref: str, doc: dict, variable_ids: set[str], themes: set[str]) -> None:
    """scope_ref が語彙・実在する値に収まっていることを検査する。cells.notes 由来の
    `doc_id`・`doc_table`（ここでは宣言しない）は検査しない。"""
    selectors = doc["selectors"]
    values = doc.get("values") or {}
    rule = selectors.get(kind)
    if rule is None:
        raise CaveatDeclarationError(f"scope kind {kind!r} の selectors が caveat_scope.yaml に無い")
    if "=" not in ref:
        if not rule["id_ok"]:
            raise CaveatDeclarationError(f"scope {kind}:{ref!r}: この kind は ID 参照を許さない（キー=値の選択式のみ）")
        if kind == "variable" and ref not in variable_ids:
            raise CaveatDeclarationError(f"scope variable:{ref!r}: registry/variable.yaml に無い variable_id")
        if kind == "dataset" and ref not in values.get("dataset", []):
            raise CaveatDeclarationError(f"scope dataset:{ref!r}: values.dataset に無い dataset 名")
        return
    allowed_values = {
        "place_kind": set(values.get("place_kind", [])),
        "source_id": set(values.get("source_id", [])) | _manifest_source_ids(),
        "theme": themes,
        "variable": variable_ids,
        "is_synthetic": {"1"},
        "unit_id": {"null"},
    }
    for part in ref.split("&"):
        k, sep, v = part.partition("=")
        if not sep or not v or k not in rule["keys"]:
            raise CaveatDeclarationError(
                f"scope {kind}:{ref!r}: 選択式のキー {k!r} は許可外（許可: {rule['keys']}）"
            )
        if k in allowed_values and v not in allowed_values[k]:
            raise CaveatDeclarationError(f"scope {kind}:{ref!r}: {k}={v!r} は実在する値でない")


def _load_scope_declaration(caveat_keys: set[str]) -> list[tuple]:
    """`registry/caveat_scope.yaml` を読んで検査し、caveat_scope の行
    （caveat_id, scope_kind, scope_ref, sort_order, priority）を作る。"""
    with CAVEAT_SCOPE_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    vocabulary = doc["vocabulary"]
    variable_ids, themes = _load_variable_ids_and_themes()

    rows: list[tuple] = []
    next_order: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, str]] = set()
    covered: set[str] = set()

    for entry in doc["scopes"]:
        kind = entry["kind"]
        if kind not in vocabulary:
            raise CaveatDeclarationError(f"scope kind {kind!r} は ADR-0013 の語彙 {vocabulary} に無い")
        if "ref_from" in entry:
            deriver = REF_DERIVERS.get(entry["ref_from"])
            if deriver is None:
                raise CaveatDeclarationError(f"ref_from {entry['ref_from']!r} は既知の導出器でない（{sorted(REF_DERIVERS)}）")
            refs = [entry["ref_template"].format(variable_id=v) for v in deriver()]
            if not refs:
                # 導出が空（例: #31 で unit_id が全部埋まった）になっても注記を黙って消さない。
                # この entry の注記は covered に入れず、下の孤児検査（scopes か unscoped に載せる）に掛ける。
                continue
        else:
            refs = [entry["ref"]]
        for key in entry["caveats"]:
            if key not in caveat_keys:
                raise CaveatDeclarationError(f"scope {kind}:{refs}: caveats の {key!r} が registry/caveat.yaml に無い")
        for ref in refs:
            _validate_ref(kind, ref, doc, variable_ids, themes)
            for key in entry["caveats"]:
                if (kind, ref, key) in seen:
                    raise CaveatDeclarationError(f"scope ({kind}, {ref!r}, {key!r}) が重複している")
                seen.add((kind, ref, key))
                order = next_order.get((kind, ref), 0)
                next_order[(kind, ref)] = order + 1
                rows.append((common.caveat_id(key), kind, ref, order, entry.get("priority", DEFAULT_PRIORITY)))
        covered.update(entry["caveats"])

    unscoped = set(doc.get("unscoped") or [])
    unknown = sorted(unscoped - caveat_keys)
    if unknown:
        raise CaveatDeclarationError(f"unscoped の {unknown} が registry/caveat.yaml に無い")
    both = sorted(unscoped & covered)
    if both:
        raise CaveatDeclarationError(f"{both} は unscoped と scopes の両方に載っている")
    orphans = sorted(caveat_keys - covered - unscoped)
    if orphans:
        raise CaveatDeclarationError(f"どの scope にも載っていない注記: {orphans}（scopes か unscoped に足す）")
    return rows


def _cells_local_key(note_id, rowid) -> str:
    return note_id if note_id is not None else f"rowid{rowid}"


def _build_cells_notes(cells_conn: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    """cells.sqlite の notes 207行から caveat 行と caveat_scope 行を作る。"""
    caveat_rows: list[tuple] = []
    scope_rows: list[tuple] = []

    cur = cells_conn.execute(
        "SELECT rowid, note_id, doc_id, table_ids, kind, text, blocks_timeseries, reason "
        "FROM notes ORDER BY rowid"
    )
    for row in cur:
        local_key = _cells_local_key(row["note_id"], row["rowid"])
        cid = common.caveat_id_cells_note(local_key)
        severity = "blocking" if row["blocks_timeseries"] == 1 else "info"

        caveat_rows.append(
            (
                cid,
                severity,
                row["kind"],
                None,  # title_ja
                row["reason"],  # body_ja: プロジェクトが付けた説明
                row["text"],  # quote: 原文からの抜粋（要約しない）
            )
        )

        doc_id = row["doc_id"]
        scope_rows.append((cid, "source_edition", f"doc_id={doc_id}", 0, DEFAULT_PRIORITY))

        table_ids = json.loads(row["table_ids"] or "[]")
        for i, table_id in enumerate(table_ids):
            scope_rows.append((cid, "observation_set", f"doc_table={doc_id}#{table_id}", i + 1, DEFAULT_PRIORITY))

    return caveat_rows, scope_rows


# caveat / caveat_scope の列リストは1箇所にまとめる（code-review 指摘: build_from_files()
# と build() の両方が同じ2つの列リストを別々に書いており、列を足す/直すときに
# 2箇所編集が必要で、片方だけ直すと INSERT の列不一致に気づきにくかった）。
CAVEAT_COLUMNS = ["caveat_id", "severity", "kind", "title_ja", "body_ja", "quote"]
CAVEAT_SCOPE_COLUMNS = ["caveat_id", "scope_kind", "scope_ref", "sort_order", "priority"]


def _insert_caveat_and_scope(
    conn: sqlite3.Connection, caveat_rows: list[tuple], scope_rows: list[tuple]
) -> dict[str, int]:
    n_caveat = common.insert_many(conn, "caveat", CAVEAT_COLUMNS, caveat_rows)
    n_scope = common.insert_many(conn, "caveat_scope", CAVEAT_SCOPE_COLUMNS, scope_rows)
    return {"caveat": n_caveat, "caveat_scope": n_scope}


def build_from_files(conn: sqlite3.Connection) -> dict[str, int]:
    """`registry/caveat.yaml` と `registry/caveat_scope.yaml`（注記→範囲の
    マッピング）だけから caveat / caveat_scope を作る。原本 DB には一切触れない
    （docs/plans/PHASE_B_INTAKE.md #7。`scripts/r01_build_registry.py --files-only` が
    使う。`place`/`taxon`/`cells.notes` 由来の caveat（`build()` が足す分）は含まない）。
    """
    entries = _load_caveat_yaml()
    caveat_rows = _build_caveat_rows(entries)
    scope_rows = _load_scope_declaration({e["key"] for e in entries})
    return _insert_caveat_and_scope(conn, caveat_rows, scope_rows)


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ...} の読み取り専用コネクション
    （`common.open_sources()` の既定の集合。'derived' は含まれない）。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。
    """
    counts = build_from_files(conn)

    cells_caveat_rows, cells_scope_rows = _build_cells_notes(src["cells"])
    cells_counts = _insert_caveat_and_scope(conn, cells_caveat_rows, cells_scope_rows)
    counts["caveat"] += cells_counts["caveat"]
    counts["caveat_scope"] += cells_counts["caveat_scope"]
    return counts
