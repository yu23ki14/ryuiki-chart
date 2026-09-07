"""caveat を作る（docs/plans/PHASE_A.md §A-5）。

domain.ts の DATA_CAVEATS（7件）・BIOTA_CAVEATS（6件）・MUNICIPALITY_LABEL の説明、
caveats.ts のテーブル→注記マッピング、cells.notes（207行）を caveat に移す。
文言は変えない（変えると web/src/lib/ai/caveats.test.ts の回帰テストが意味を失う）。
新しい注記は書き足さない。

## スキーマの逸脱（計画の7テーブル→8テーブル）

PHASE_A.md §A-1 の計画では `caveat(caveat_id PK, scope_kind, scope_ref, severity, kind,
title_ja, body_ja, quote)` という単一テーブルだった。しかし実装時に、**1つの注記が
複数のテーブルに掛かる**ことが判明した（例: `censored` は `measurements` / `meas_year` /
`meas_month` など9テーブルに掛かる。`caveats.ts` の `MEASURE_CAVEATS` を見れば分かる）。
`caveat_id` を主キーにしたまま `scope_kind`/`scope_ref` を同じ行に持たせると、
1つの注記につき1行しか持てず 1:N を表現できない。

そのため:
- `caveat` は注記そのもの（`caveat_id` PK, `severity`, `kind`, `title_ja`, `body_ja`,
  `quote`）だけにした。
- スコープは新テーブル `caveat_scope(id, caveat_id, scope_kind, scope_ref, sort_order)`
  に出した（1注記 : N スコープ）。

`web/src/db/schema-registry.ts` / `scripts/schema_registry.sql` /
`web/drizzle/migrations/` を合わせて直してある（`pnpm run db:generate` が
"No schema changes" になることと、まっさらな状態からの `pnpm run db:migrate` が
通ることを確認済み）。

## `caveat_scope.scope_kind` が取りうる値（**一致方法だけ**を表す）

- `'table'`      — scope_ref はテーブル名の完全一致（例: `'sites'`, `'measurements'`,
                   `SYNTHETIC_TABLES`）。`caveats.ts` の `SITES_CAVEATS` / `MEASURE_TABLES` /
                   `ORGANISM_TABLES` / `MESH_TABLES_EXTRA`（`species_mesh_year`）/
                   `IAS_CAVEATS`（`ias_species`）/ `SYNTHETIC_CAVEATS`（`SYNTHETIC_TABLES`）
                   すべてがこの1種類に対応する。
- `'table_prefix'` — scope_ref はテーブル名の前方一致パターン（今のところ `'mesh_'` のみ）。
                   `caveats.ts` の `t.startsWith("mesh_")` を表す。
- `'cell'`       — `cells.sqlite` の `notes` 由来。scope_ref は `notes.doc_id`
                   （原本の文書ID。全207行に必ず入っている）。
- `'cell_table'` — 同じく `notes` 由来で、`notes.table_ids`（JSON配列、59/207行で非空）が
                   指す個別の表を表す。scope_ref は `"<doc_id>#<table_ids の要素>"`
                   （`table_ids` の値は文書内で使われる略記で、文書をまたいで一意とは限らない
                   ため doc_id を前置して衝突を避けている）。
  **`'cell'` / `'cell_table'` は `caveatsForTables()` の対象外。** テーブル向けの
  `'table'` / `'table_prefix'` 側には絶対に混ぜない
  （混ぜると `caveats.test.ts` のスナップショットが壊れる）。

**優先度は `scope_kind` ではなく `priority` 列（既定0）が持つ。** 以前は `synthetic`
専用に `scope_kind='table_synthetic'` という一致方法を作り、「渡されたテーブルの中に
1つでもあれば他のどのテーブルより先頭に置く」という優先規則をそこに乗せていた。
しかしこれは「一致方法」ではなく「優先順位」の話であり、`scope_kind` に混ぜたことで
`caveatsForTables()` 側に `if (scope_kind === 'table_synthetic')` という特殊分岐が必要になり、
**実際にバグを生んだ**（複数の synthetic テーブルが別々の注記キーを持つとき、最初の1件で
`break` して2件目以降を落とす欠陥。直前のコミットで修正済み）。`priority` を明示の列として
切り出し、`synthetic` の scope 行だけ `priority=SYNTHETIC_PRIORITY`（1、他は既定0）にすることで、
「優先度が高い」という事実がデータ側に乗り、読み出し側は特殊分岐無しの一般規則で済むようにした。

## `caveatsForTables()` の順序を `caveat_scope` から復元する方法

`sort_order` は「同じ `(scope_kind, scope_ref)` の中での並び」だけを表す
（例: `('table', 'sites', ...)` は `zone` が0、`municipality` が1）。
スコープ同士（＝渡されたテーブルの間）の並びは、現行の `caveatsForTables()` と同じく
**呼び出し側が渡すテーブル名の順序**に従う。読み出し側は**単一の一般規則**でよい:

1. 渡されたテーブルを順に見て、各テーブルについて
   `scope_kind='table' AND scope_ref=<テーブル名>` または
   `scope_kind='table_prefix' AND <テーブル名> LIKE scope_ref || '%'` に一致する行を集める。
2. 全ての一致行を `(priority 降順, その行がマッチしたテーブルの呼び出し側での出現順序 昇順,
   sort_order 昇順)` で並べる。
3. `caveat_id` で重複排除（先勝ち）。

`priority` が同点（既定0同士）のときはテーブルの出現順序がそのまま並びを決めるので、
以前の「synthetic だけ先頭・残りは渡された順」という挙動は `priority` の値だけで
再現される。特殊分岐は要らない。

## cells.notes（207行）の取り込み

`cells.sqlite` の `notes` テーブルの列: `note_id`（177/207行で非NULL・非NULLの範囲では
一意）, `doc_id`（全行に存在）, `table_ids`（JSON配列文字列。59行が非空、それ以外は `"[]"`）,
`kind`（`definition_change` 58 / `footnote` 52 / `comparability` 44 / `survey_scope` 23 /
NULL 30）, `text`（原文引用。NULL の行もある）, `page`, `blocks_timeseries`（0/1 のフラグ。
132行が1）, `reason`（このプロジェクトが付けた「なぜ比較を阻害するか」の説明）。

- `caveat_id`: `common:caveat:cells.<note_id>`。ただし `note_id` が NULL の30行は
  一意な主キーが無いため、`"rowid<rowid>"`（sqlite の rowid）を代わりに使う
  （`rowid` は207行すべてで一意）。`common.caveat_id_cells_note()` に渡すキー文字列を
  このどちらかにしている。
- `severity`: `blocks_timeseries` をそのまま一般化する（ADR-0013 の決定どおり）。
  `1 -> 'blocking'`（この注記を無視した時系列比較は誤り）、`0 -> 'info'`
  （時系列比較は阻害しないが記録すべき注記）。
- `kind`: `notes.kind` をそのまま使う（`definition_change` は ADR-0013 の enum と
  文字列が一致する。`footnote` / `comparability` / `survey_scope` は enum に無い値だが、
  推測で無理に丸めず原本の値をそのまま残した。NULL はそのまま NULL）。
- `title_ja`: 無し（NULL）。
- `body_ja`: `notes.reason`（プロジェクトが書いた説明文。要約ではなく、この行が
  存在する理由そのもの）。
- `quote`: `notes.text`（原本からの抜粋。ADR-0013 の「原文は引用のみ、要約しない」を
  ここで満たす。NULL の行はそのまま NULL）。
- スコープ: `caveat_scope` に `scope_kind='cell'`, `scope_ref=doc_id` を1行、
  `table_ids` が非空ならその要素ごとに `scope_kind='cell_table'`,
  `scope_ref=f"{doc_id}#{table_id}"` を追加行として入れる。

cells.notes は `caveatsForTables()` の対象外なので、ここで作る `caveat_scope` 行は
`'cell'` / `'cell_table'` にしか出さない。

## registry/caveat.yaml との関係

`registry/caveat.yaml` に14件（`key`, `severity`, `kind`, `title_ja`, `body_ja`,
`quote`）を手書きで置いてある。`caveat_id` はここで `common.caveat_id(key)`
（`common:caveat:<key>`）から導出する（yaml 側は key だけ持つ）。
`caveat_scope`（テーブル→注記のマッピング）は yaml に出さず、下のモジュール定数として
このファイルに直接書いた。`caveats.ts` の集合演算（`Set` とテーブル名前方一致）の
複製であり、データというよりロジックの複製にあたるため。
"""
import json
import pathlib
import sqlite3

import yaml

from . import common

CAVEAT_YAML = common.ROOT / "registry" / "caveat.yaml"

# --- caveats.ts のテーブル集合・注記リストの複製（順序も含めて一致させること） ---

SITES_CAVEATS = ["zone", "municipality"]

MEASURE_CAVEATS = ["measuredOn", "censored", "duplicates"]
MEASURE_TABLES = [
    "measurements",
    "meas_year",
    "meas_month",
    "meas_daily",
    "meas_clim",
    "zone_year",
    "zone_clim",
    "var_catalog",
    "site_var",
]

ORGANISM_CAVEATS = ["organismSite", "effort", "regimes", "gbifCutoff", "share"]
ORGANISM_TABLES = [
    "organism_records",
    "org_norm",
    "org_group_year",
    "org_watershed",
    "org_watershed_year",
    "species2",
    "species_year2",
    "species_month",
    "effort_year",
]

MESH_CAVEATS = ["share", "effort"]
MESH_TABLE_PREFIX = "mesh_"
MESH_TABLES_EXTRA = ["species_mesh_year"]

IAS_CAVEATS = ["isAlien"]
IAS_TABLE = "ias_species"

SYNTHETIC_CAVEATS = ["synthetic"]
SYNTHETIC_TABLES = [
    "observers",
    "interventions",
    "decisions",
    "quality_transitions",
    "quality_monthly",
    "event_observers",
]

# 「渡されたテーブルの中に synthetic 対象が1つでもあれば、他のどのテーブルより先頭に
# 置く」という優先規則を表す priority 値（既定は 0）。scope_kind ではなくここで表す
# （このファイル冒頭のモジュール docstring 参照）。
SYNTHETIC_PRIORITY = 1
DEFAULT_PRIORITY = 0


def _load_caveat_yaml() -> list[dict]:
    with CAVEAT_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["caveats"]
    keys = [e["key"] for e in entries]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"registry/caveat.yaml の key が重複している: {dupes}"
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


def _build_table_scope_rows() -> list[tuple]:
    """caveats.ts のテーブル→注記マッピングを caveat_scope の行として複製する。"""
    rows: list[tuple] = []

    def add_table_group(
        tables: list[str], keys: list[str], priority: int = DEFAULT_PRIORITY
    ) -> None:
        for t in tables:
            for i, key in enumerate(keys):
                rows.append((common.caveat_id(key), "table", t, i, priority))

    add_table_group(["sites"], SITES_CAVEATS)
    add_table_group(MEASURE_TABLES, MEASURE_CAVEATS)
    add_table_group(ORGANISM_TABLES, ORGANISM_CAVEATS)
    add_table_group(MESH_TABLES_EXTRA, MESH_CAVEATS)
    add_table_group([IAS_TABLE], IAS_CAVEATS)
    add_table_group(SYNTHETIC_TABLES, SYNTHETIC_CAVEATS, priority=SYNTHETIC_PRIORITY)

    # mesh_ 接頭辞は個別テーブル名ではなくパターンなので table_prefix で1回だけ持つ。
    for i, key in enumerate(MESH_CAVEATS):
        rows.append((common.caveat_id(key), "table_prefix", MESH_TABLE_PREFIX, i, DEFAULT_PRIORITY))

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
        scope_rows.append((cid, "cell", doc_id, 0, DEFAULT_PRIORITY))

        table_ids = json.loads(row["table_ids"] or "[]")
        for i, table_id in enumerate(table_ids):
            scope_rows.append((cid, "cell_table", f"{doc_id}#{table_id}", i + 1, DEFAULT_PRIORITY))

    return caveat_rows, scope_rows


def build_from_files(conn: sqlite3.Connection) -> dict[str, int]:
    """`registry/caveat.yaml` とこのファイルのモジュール定数（テーブル→注記の
    マッピング）だけから caveat / caveat_scope を作る。原本 DB には一切触れない
    （docs/plans/PHASE_B_INTAKE.md #7。`scripts/r01_build_registry.py --files-only` が
    使う。`place`/`taxon`/`cells.notes` 由来の caveat（`build()` が足す分）は含まない）。
    """
    entries = _load_caveat_yaml()
    caveat_rows = _build_caveat_rows(entries)
    scope_rows = _build_table_scope_rows()

    n_caveat = common.insert_many(
        conn,
        "caveat",
        ["caveat_id", "severity", "kind", "title_ja", "body_ja", "quote"],
        caveat_rows,
    )
    n_scope = common.insert_many(
        conn,
        "caveat_scope",
        ["caveat_id", "scope_kind", "scope_ref", "sort_order", "priority"],
        scope_rows,
    )
    return {"caveat": n_caveat, "caveat_scope": n_scope}


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {テーブル名: 挿入した行数}（ログ表示用）。
    """
    counts = build_from_files(conn)

    cells_caveat_rows, cells_scope_rows = _build_cells_notes(src["cells"])
    n_caveat = common.insert_many(
        conn,
        "caveat",
        ["caveat_id", "severity", "kind", "title_ja", "body_ja", "quote"],
        cells_caveat_rows,
    )
    n_scope = common.insert_many(
        conn,
        "caveat_scope",
        ["caveat_id", "scope_kind", "scope_ref", "sort_order", "priority"],
        cells_scope_rows,
    )
    counts["caveat"] += n_caveat
    counts["caveat_scope"] += n_scope
    return counts
