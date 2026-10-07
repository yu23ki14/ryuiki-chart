"""source_access を作る（MCP の出典アクセス。docs/plans/MCP_SOURCE_ACCESS.md §1）。

出典ごとに「ツールで値が取れるか（`queryable`）、取れないならなぜか」を持つ表。MCP の
`describe_catalog(sources)` が、モデルに一覧を数えさせずに **集計済みの件数** を返すための元になる。

## 入力

- `manifests/<source_id>.yml` の `target`: observation → `get_observations`、occurrence → `get_occurrences`
  （宣言しない。二重管理にしない）。
- `registry/source/access.yaml`（手書き）: `records`（`get_records` で取れる表）・`reason`（取れない理由。
  `basis` に下書きの根拠を残す）・`extra_tools`。形は access.yaml の冒頭コメント。
- 原本 `ryuiki.sqlite`: 出典ごとの行数（`n_source_rows`）と、宣言との突き合わせ（§1.4）。

## 出力（registry.sqlite）

`source_access`: `source_registry` 1 行 = 1 行（合成データ `synthetic_sensor` を含む。生成物 TS には載せない）。

## 検査（壊すと止まる。scripts/tests/test_registry_source_access.py が変異で固定している）

静的（原本不要。`--files-only` でも `validate_static()` が走る）:
- 理由コードが語彙内・`reason` に `basis` がある・`records` と `reason` の両方は持てない
- `records` の record_set が `record_sets`（record_set → D1 の表。**正はここ 1 か所**）にあり、その表が許可リスト
  （`D1_RECORD_TABLES`＝**D1 にある表**。原本にだけある表は対象外で、理由は `not_in_d1`）内
- `reason` を持つ出典はマニフェストに無い（取れるものを「取れない」と書かない）
- `extra_tools` はマニフェストの出典にだけ付く

原本あり:
- 全出典が状態を持つ（マニフェスト由来 + `records` + `reason` が `source_registry` と過不足なく一致）
- `records` の (出典, 表) の行数が 1 以上
- `reason` の出典が、出典の列を持つ全表のどれにも 0 行（`ROW_REASONS` の `synthetic`・`not_in_d1` だけ例外。
  この2つは逆に、原本に行があることを要求する。宣言が古ければ止まる）
- `reason: superseded` ⇔ `source.superseded_by` がある
"""
import json
import pathlib
import sqlite3

import yaml

from . import common

ACCESS_YAML = common.ROOT / "registry" / "source" / "access.yaml"

TOOL_BY_TARGET = {"observation": "get_observations", "occurrence": "get_occurrences"}
EXTRA_TOOLS = {"get_edna"}
RECORDS_TOOL = "get_records"

# `record_sets` が指してよい表（**D1 にある表**。出典の列 `source_id` で絞る）。web/src/lib/records.ts の
# RECORD_TABLES の許可リスト（列）は record_set → 表を access.yaml の生成物から読む。`taxon_assessment` は語彙レジストリの表
# （registry.sqlite。原本の taxa・redlist_assessments は D1 に無い＝マイグレーション 0010 で DROP 済み）。
D1_RECORD_TABLES = frozenset(
    {"sites", "protected_areas", "vegetation_polygons", "river_segments", "mammal_mesh", "wildlife_sightings", "taxon_assessment"}
)

# n_source_rows を数える表（A の出典。B は `records` の表）。
PRIMARY_TABLES = {
    "observation": ("measurements", "sensor_timeseries"),
    "occurrence": ("organism_records", "edna_reads", "wildlife_sightings"),
}

N_BASIS = ("source_rows", "registry_record_count", "none")
_SOURCE_KEYS = {"records", "reason", "basis", "note"}
# 原本に行がある理由（合成データ・D1 に未投入）。他の理由は「原本に行が無い」ことを検査する。
ROW_REASONS = frozenset({"synthetic", "not_in_d1"})
# マニフェスト（キューブに入る）の出典だが、対応するツールでは実際に引けない（例: get_observations は測定値系データセット固定で、
# センサー系列・土地利用を引けない）。tests（queryable-via.test.ts）が実データで確かめた食い違いを宣言する。行の検査は要らない。
CUBE_ONLY_REASON = "cube_only"


class AccessError(AssertionError):
    pass


def load_access_yaml(path: pathlib.Path | None = None) -> dict:
    return yaml.safe_load((path or ACCESS_YAML).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 宣言の正規化と静的検査
# ---------------------------------------------------------------------------

def normalize_records(sid: str, records, record_sets: dict[str, str]) -> list[str]:
    """`records`（record_set 名のリスト）を検査する。不正なら止まる。"""
    if not isinstance(records, list) or not records or not all(isinstance(t, str) for t in records):
        raise AccessError(f"access.yaml: {sid} の records は 1 つ以上の record_set のリストでなければならない")
    for rs in records:
        if rs not in record_sets:
            raise AccessError(f"access.yaml: {sid} の records の {rs!r} が record_sets に無い: {sorted(record_sets)}。D1 に無い表は reason: not_in_d1 にする")
    if len(set(records)) != len(records):
        raise AccessError(f"access.yaml: {sid} の records に record_set が重複している")
    return list(records)


def validate_static(doc: dict, manifest_targets: dict[str, str]) -> dict[str, list[str]]:
    """原本不要の検査。戻り値は `{source_id: 正規化した records}`（records を持つ出典だけ）。"""
    reasons = doc.get("reasons")
    if not isinstance(reasons, dict) or not reasons:
        raise AccessError("access.yaml: reasons（理由コードの語彙）が無い")
    for code, v in reasons.items():
        if not isinstance(v, dict) or not v.get("ja"):
            raise AccessError(f"access.yaml: reasons.{code} に ja が無い")
    record_sets = doc.get("record_sets")
    if not isinstance(record_sets, dict) or not record_sets:
        raise AccessError("access.yaml: record_sets（record_set → D1 の表）が無い")
    bad = sorted(set(record_sets.values()) - D1_RECORD_TABLES)
    if bad:
        raise AccessError(f"access.yaml: record_sets の表 {bad} が D1 にある表の許可リスト（D1_RECORD_TABLES）に無い")
    sources = doc.get("sources")
    if not isinstance(sources, dict):
        raise AccessError("access.yaml: sources が無い")
    records_by_source: dict[str, list[str]] = {}
    for sid, entry in sources.items():
        if not isinstance(entry, dict):
            raise AccessError(f"access.yaml: sources.{sid} がマップではない")
        extra = set(entry) - _SOURCE_KEYS
        if extra:
            raise AccessError(f"access.yaml: sources.{sid} に未対応のキー {sorted(extra)}（使えるキー: {sorted(_SOURCE_KEYS)}）")
        has_rec, has_reason = "records" in entry, "reason" in entry
        if has_rec == has_reason:
            raise AccessError(f"access.yaml: sources.{sid} は records か reason のどちらか一方だけを持つ（両方・どちらも無しは不可）")
        if has_rec:
            records_by_source[sid] = normalize_records(sid, entry["records"], record_sets)
            if "basis" in entry:
                raise AccessError(f"access.yaml: sources.{sid} は records を持つので basis は書けない（basis は reason の根拠）")
        else:
            code = entry["reason"]
            if code not in reasons:
                raise AccessError(f"access.yaml: sources.{sid} の reason={code!r} が語彙 {sorted(reasons)} に無い")
            if not str(entry.get("basis") or "").strip():
                raise AccessError(f"access.yaml: sources.{sid} の reason に basis（根拠）が無い")
            if (sid in manifest_targets) != (code == CUBE_ONLY_REASON):
                raise AccessError(
                    f"access.yaml: sources.{sid} の reason={code!r} が合わない。マニフェストのある出典に書けるのは"
                    f" {CUBE_ONLY_REASON}（キューブにはあるが対応するツールでは引けない）だけで、"
                    f"{CUBE_ONLY_REASON} はマニフェストのある出典にだけ書ける"
                )
    extra_tools = doc.get("extra_tools") or {}
    for sid, tools in extra_tools.items():
        if sid not in manifest_targets:
            raise AccessError(f"access.yaml: extra_tools.{sid} はマニフェストの出典ではない")
        bad = [t for t in tools if t not in EXTRA_TOOLS]
        if bad:
            raise AccessError(f"access.yaml: extra_tools.{sid} の {bad} は未対応（使えるもの: {sorted(EXTRA_TOOLS)}）")
    return records_by_source


# ---------------------------------------------------------------------------
# 原本の件数
# ---------------------------------------------------------------------------

def gather_counts(ryuiki: sqlite3.Connection, registry: sqlite3.Connection) -> dict:
    """原本から数える（読み取り専用の接続）。`by_source[table][source_id]`: 出典の列を持つ全表の出典別の行数
    （`a|b` の複合値は要素ごとに数える）。D1 にある `taxon_assessment` は、いま作っている registry から数える。"""
    tables = [
        r[0] for r in ryuiki.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'source_registry' ORDER BY name")
    ]
    by_source: dict[str, dict[str, int]] = {}
    for conn_, t in [(ryuiki, t) for t in tables] + [(registry, "taxon_assessment")]:
        cols = {r[1] for r in conn_.execute(f'PRAGMA table_info("{t}")')}
        if "source_id" not in cols:
            continue
        counts: dict[str, int] = {}
        for sid, n in conn_.execute(f'SELECT source_id, count(*) FROM "{t}" WHERE source_id IS NOT NULL AND source_id != \'\' GROUP BY source_id'):
            for part in str(sid).split("|"):
                counts[part] = counts.get(part, 0) + n
        by_source[t] = counts
    return {"by_source": by_source}


def _table_rows(counts: dict, sid: str, table: str) -> int:
    return counts["by_source"].get(table, {}).get(sid, 0)


# ---------------------------------------------------------------------------
# 組み立て（DB に触らない純関数。テストが偽の宣言・件数で検査を壊せる）
# ---------------------------------------------------------------------------

COLUMNS = [
    "source_id", "state", "queryable_via", "tables", "n_source_rows", "n_source_rows_basis",
    "counted_at", "reason", "reason_ja", "reason_note",
]


def assemble(
    registry_rows: list[dict], manifest_targets: dict[str, str], doc: dict, counts: dict | None,
    *, superseded_by: dict[str, str | None] | None = None,
) -> list[tuple]:
    """`source_registry` の行（`source_id`・`record_count`・`fetched_at` を持つ辞書）から `source_access` の行を作る。

    `counts` が None なら静的検査だけ（行は作らない）。`superseded_by` は registry の `source.superseded_by`。
    """
    records_by_source = validate_static(doc, manifest_targets)
    sources = doc["sources"]
    reasons = doc["reasons"]
    extra_tools = doc.get("extra_tools") or {}
    reg = {r["source_id"]: r for r in registry_rows}
    if len(reg) != len(registry_rows):
        raise AccessError("source_registry.source_id が重複している")

    # 全出典が状態を持つ（過不足なし）
    declared = set(sources)
    unknown = sorted((declared | set(manifest_targets)) - set(reg))
    if unknown:
        raise AccessError(f"access.yaml / manifests/ の出典が source_registry に無い: {unknown}")
    # マニフェストの出典は records だけ足せる（get_records を足す）。reason・records なしは「宣言不要」。
    classified = declared | set(manifest_targets)
    missing = sorted(set(reg) - classified)
    if missing:
        raise AccessError(
            f"状態の無い出典がある（manifests/ にも access.yaml の records/reason にも無い）: {missing}。"
            "取れるなら records、取れないなら reason と basis を access.yaml に書く"
        )

    sup = superseded_by or {}
    for sid, entry in sources.items():
        is_sup = entry.get("reason") == "superseded"
        has_sup = sup.get(sid) is not None
        if is_sup != has_sup:
            raise AccessError(
                f"access.yaml: {sid} の reason=superseded と registry の superseded_by={sup.get(sid)!r} が食い違う"
                "（置換は registry/source/editions.yaml の source_declarations が正）"
            )

    if counts is None:
        return []

    # --- 原本との突き合わせ（§1.4）---
    all_source_tables = counts["by_source"]
    for sid, recs in records_by_source.items():
        for rs in recs:
            table = doc["record_sets"][rs]
            if _table_rows(counts, sid, table) == 0:
                raise AccessError(
                    f"access.yaml: {sid} の records に宣言した record_set {rs}（表 {table}）に、この出典の行が 1 つも無い"
                    "（宣言が古い。records から外すか、reason に直す）"
                )
    for sid, entry in sources.items():
        code = entry.get("reason")
        if code is None:
            continue
        have = {t: c[sid] for t, c in all_source_tables.items() if c.get(sid)}
        if code == CUBE_ONLY_REASON:
            continue
        if code in ROW_REASONS:
            if not have:
                raise AccessError(f"access.yaml: {sid} は reason={code} だが原本に行が無い（宣言が古い。{code} は行がある出典の理由）")
        elif have:
            raise AccessError(
                f"access.yaml: {sid} は reason={code}（取れない）と宣言しているが、原本に行がある: {have}"
                "（宣言が古い。records に直すか、マニフェストを足す。D1 に表が無いだけなら not_in_d1）"
            )

    counted_at = max((r["fetched_at"] for r in registry_rows if r.get("fetched_at")), default=None)

    rows = []
    for sid in sorted(reg):
        r = reg[sid]
        entry = sources.get(sid, {})
        recs = records_by_source.get(sid, [])
        target = manifest_targets.get(sid)
        via: list[str] = []
        if target and entry.get("reason") != CUBE_ONLY_REASON:
            via.append(TOOL_BY_TARGET[target])
            via.extend(extra_tools.get(sid, []))
        if recs:
            via.append(RECORDS_TOOL)
        tables = list(recs)
        reason = entry.get("reason")
        if via:
            if target:
                n = sum(all_source_tables.get(t, {}).get(sid, 0) for t in PRIMARY_TABLES[target])
                if n == 0:
                    n, basis = r["record_count"], "registry_record_count"
                else:
                    basis = "source_rows"
            else:
                n, basis = sum(_table_rows(counts, sid, doc["record_sets"][t]) for t in recs), "source_rows"
            row = (sid, "queryable", json.dumps(via), json.dumps(tables),
                   n, basis, counted_at, None, None, None)
        else:
            row = (sid, "not_queryable", "[]", "[]", None, "none", None, reason, reasons[reason]["ja"], entry.get("note"))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# registry.sqlite への書き込み
# ---------------------------------------------------------------------------

def _manifest_targets() -> dict[str, str]:
    from ingest import manifest as manifest_lib  # noqa: E402（scripts/ を sys.path に持つ実行経路でだけ読む）

    return {sid: m.target for sid, m in manifest_lib.load_manifests().items()}


def check_static() -> None:
    """`--files-only`（原本を開かない CI）で走らせる静的検査。"""
    validate_static(load_access_yaml(), _manifest_targets())


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用。src['ryuiki']: 読み取り専用の原本。`source` の後に実行する。"""
    ryuiki = src["ryuiki"]
    cur = ryuiki.execute("SELECT source_id, record_count, fetched_at FROM source_registry ORDER BY source_id")
    cols = [d[0] for d in cur.description]
    registry_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    doc = load_access_yaml()
    targets = _manifest_targets()
    records_by_source = validate_static(doc, targets)
    counts = gather_counts(ryuiki, conn)
    superseded_by = dict(conn.execute("SELECT source_id, superseded_by FROM source").fetchall())
    rows = assemble(registry_rows, targets, doc, counts, superseded_by=superseded_by)
    n = common.insert_many(conn, "source_access", COLUMNS, rows)
    return {"source_access": n}
