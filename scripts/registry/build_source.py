"""license / source / source_edition を作る（ADR-0005、Issue #39 Phase C）。

入力:
- `ryuiki.sqlite` の `source_registry`（124 行。読み取り専用）: 出典の名前・URL・ライセンス原文・
  再配布可否・取得日・件数
- `registry/source/license.yaml`（手書き）: ライセンス原文（71 種）→ `license_id`/`license_class`
- `registry/source/editions.yaml`（手書き）: 分かっている版と置換関係

出力（registry.sqlite）:
- `license`: license.yaml の `licenses`
- `source`: source_registry 1 行 = 1 行（`source_id` は bare のまま）。`superseded_by`
- `source_edition`: 宣言された版 + 宣言の無い source の「取得回」の版（1 source に最低 1 つ）

**過去の取得履歴は作らない**（復元不能。捏造しない）。**隔離・出力の絞り込みの根拠にしない**:
`redistributable`/`license_class`/`commercial_ok` は出典の旗として列に残すだけで、
`embargo_reason` 列は無い（ADR-0005 改定、ADR-0028）。

`--files-only`（原本を開かない CI のモード）ではこのステップを実行しない。ただし
`editions.yaml` の宣言（`declared_editions`）だけは `load_declared_edition_ids()` が
YAML だけから読めるので、`build_unit_variable.py` が alias.edition_key の実在検査に使う。

検査（どれも壊すと止まる。scripts/tests/test_registry_source.py が固定している）:
- license.yaml: license_id 一意・license_class がコードリスト内・mappings の license_id が実在・
  raw が一意・`unknown` が定義されている
- mappings の raw が source_registry に実在する（古い宣言の掃除）
- 写像漏れの原文は `unknown` に落とし、件数と原文を出力する（止めない）
- editions.yaml: 宣言の source_id が実在・edition_key が一意・fetched_from が実在・
  update_mode がコードリスト内・content_file がリポジトリ内の相対パス
- 置換: `superseded_by` の先が実在し、自分自身ではなく、循環せず、先の source は edition を
  ちょうど 1 つ持つ（edition 側の置換先を一意に決めるため）
- `source_registry.notes` に `【SUPERSEDED` を含む行は `superseded_by` を宣言していること
- alias.edition_key の指す (source_id, edition_key) が source_edition に実在する
"""
import hashlib
import pathlib
import re
import sqlite3

import yaml

from . import common

SOURCE_DIR = common.ROOT / "registry" / "source"
LICENSE_YAML = SOURCE_DIR / "license.yaml"
EDITIONS_YAML = SOURCE_DIR / "editions.yaml"

# source_registry.fetched_at の書式。`YYYY-MM-DDTHH:MM:SS`（タイムゾーン無し）。日付の切り出しは
# 文字列操作で行い、SQLite の日時関数は使わない（ADR-0024）。
_FETCHED_AT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}:\d{2}$")

SUPERSEDED_MARKER = "【SUPERSEDED"
UNKNOWN_LICENSE_ID = "unknown"

_SOURCE_COLUMNS = [
    "source_id", "source_ref_id", "name_ja", "publisher", "homepage_url", "region_id",
    "theme", "access_method", "superseded_by", "notes",
]
_EDITION_COLUMNS = [
    "edition_id", "source_id", "edition_key", "vintage", "fetched_at", "url", "format",
    "content_sha256", "license_id", "license_raw", "license_class", "redistributable",
    "commercial_ok", "record_count", "superseded_by", "update_mode", "notes",
]


# ---------------------------------------------------------------------------
# 宣言ファイルの読み込み（YAML だけ。原本は開かない）
# ---------------------------------------------------------------------------

def load_license_yaml(path: pathlib.Path | None = None) -> dict:
    with (path or LICENSE_YAML).open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    classes = doc["license_classes"]
    licenses = doc["licenses"]
    mappings = doc["mappings"]
    common.assert_unique([e["license_id"] for e in licenses], "registry/source/license.yaml の license_id")
    common.assert_unique([m["raw"] for m in mappings], "registry/source/license.yaml の mappings[].raw")
    ids = {e["license_id"] for e in licenses}
    if UNKNOWN_LICENSE_ID not in ids:
        raise AssertionError(
            f"registry/source/license.yaml: 写像漏れの受け皿 license_id={UNKNOWN_LICENSE_ID!r} が無い"
        )
    for e in licenses:
        if e["license_class"] not in classes:
            raise AssertionError(
                f"registry/source/license.yaml: license_id={e['license_id']!r} の license_class="
                f"{e['license_class']!r} がコードリスト {sorted(classes)} に無い"
            )
    for m in mappings:
        if m["license_id"] not in ids:
            raise AssertionError(
                f"registry/source/license.yaml: mappings の license_id={m['license_id']!r} が licenses に無い"
                f"（raw={m['raw'][:40]!r}…）"
            )
    return doc


def load_editions_yaml(path: pathlib.Path | None = None) -> dict:
    with (path or EDITIONS_YAML).open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    codes = set(doc["update_mode_codes"])
    declared = doc.get("declared_editions") or []
    decls = doc.get("source_declarations") or {}
    common.assert_unique(
        [(e["source_id"], str(e["edition_key"])) for e in declared],
        "registry/source/editions.yaml の declared_editions (source_id, edition_key)",
    )
    for e in declared:
        common.edition_id(e["source_id"], str(e["edition_key"]))  # 形式検査（例外で止まる）
    for label, entry in [(f"declared_editions {e['source_id']}/{e['edition_key']}", e) for e in declared] + [
        (f"source_declarations {k}", v) for k, v in decls.items()
    ]:
        um = entry.get("update_mode")
        if um is not None and um not in codes:
            raise AssertionError(
                f"registry/source/editions.yaml: {label} の update_mode={um!r} がコードリスト {sorted(codes)} に無い"
            )
        cf = entry.get("content_file")
        if cf is not None:
            p = pathlib.PurePosixPath(cf)
            if p.is_absolute() or ".." in p.parts:
                raise AssertionError(
                    f"registry/source/editions.yaml: {label} の content_file={cf!r} はリポジトリ内の相対パスでなければならない"
                )
    return doc


def load_declared_edition_ids(path: pathlib.Path | None = None) -> set[tuple[str, str]]:
    """`declared_editions` の `(source_id, edition_key)` の集合（YAML だけから。原本不要）。

    `build_unit_variable.py` が `registry/variable_alias.csv` の `edition_key` の実在を検査する
    のに使う（alias が版を指してよいのは宣言された版だけ。`--files-only` でも同じ検査が効く）。
    """
    doc = load_editions_yaml(path)
    return {(e["source_id"], str(e["edition_key"])) for e in doc.get("declared_editions") or []}


# ---------------------------------------------------------------------------
# 組み立て
# ---------------------------------------------------------------------------

def _default_edition_key(source_id: str, fetched_at: str | None) -> str:
    m = _FETCHED_AT_RE.match(fetched_at or "")
    if not m:
        raise AssertionError(
            f"source_registry.fetched_at が YYYY-MM-DDTHH:MM:SS ではない（取得回の edition_key を作れない）: "
            f"source_id={source_id!r} fetched_at={fetched_at!r}"
        )
    return "".join(m.groups())


def _sha256_of(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assemble(registry_rows: list[dict], license_doc: dict, editions_doc: dict, *, root: pathlib.Path | None = None):
    """`source_registry` の行（辞書のリスト）と 2 つの宣言から、3 表に入れる行を作る。

    DB に触らない純関数（テストが偽の source_registry 行で検査を壊せるようにするため）。
    戻り値: `(license_rows, source_rows, edition_rows, unmapped)`。`unmapped` は写像漏れの原文のリスト。
    """
    root = root or common.ROOT
    reg = {r["source_id"]: r for r in registry_rows}
    common.assert_unique(list(reg), "source_registry.source_id")

    lic_by_id = {e["license_id"]: e for e in license_doc["licenses"]}
    classes = license_doc["license_classes"]
    raw_to_lic = {m["raw"]: m["license_id"] for m in license_doc["mappings"]}
    raws_in_data = {r["license"] for r in registry_rows}
    stale = sorted(set(raw_to_lic) - raws_in_data)
    if stale:
        raise AssertionError(
            "registry/source/license.yaml の mappings に、source_registry.license に存在しない原文がある"
            f"（古い宣言。削除する）: {[s[:50] for s in stale]}"
        )
    unmapped = sorted(raws_in_data - set(raw_to_lic), key=lambda x: (x is None, x))

    decls = editions_doc.get("source_declarations") or {}
    declared = editions_doc.get("declared_editions") or []
    for sid in decls:
        if sid not in reg:
            raise AssertionError(f"registry/source/editions.yaml: source_declarations の {sid!r} が source_registry に無い")
    declared_by_source: dict[str, list[dict]] = {}
    for e in declared:
        if e["source_id"] not in reg:
            raise AssertionError(f"registry/source/editions.yaml: declared_editions の source_id={e['source_id']!r} が source_registry に無い")
        if e["fetched_from"] not in reg:
            raise AssertionError(
                f"registry/source/editions.yaml: declared_editions {e['source_id']}/{e['edition_key']} の "
                f"fetched_from={e['fetched_from']!r} が source_registry に無い"
            )
        declared_by_source.setdefault(e["source_id"], []).append(e)

    # --- 置換（source 側）の検査 ---
    superseded = {sid: d["superseded_by"] for sid, d in decls.items() if d.get("superseded_by")}
    for old, new in superseded.items():
        if new not in reg:
            raise AssertionError(f"registry/source/editions.yaml: {old!r} の superseded_by={new!r} が source_registry に無い")
        if new == old:
            raise AssertionError(f"registry/source/editions.yaml: {old!r} が自分自身に置換されている")
    for start in superseded:
        seen, cur = {start}, superseded.get(start)
        while cur is not None:
            if cur in seen:
                raise AssertionError(f"registry/source/editions.yaml: superseded_by が循環している（{start!r} から）")
            seen.add(cur)
            cur = superseded.get(cur)
    for sid, r in reg.items():
        if SUPERSEDED_MARKER in (r.get("notes") or "") and sid not in superseded:
            raise AssertionError(
                f"source_registry.notes に {SUPERSEDED_MARKER} を含む source_id={sid!r} が editions.yaml の "
                "source_declarations で superseded_by を宣言されていない（置換は notes の文字列ではなく "
                "superseded_by 列で表す。ADR-0005）"
            )

    # --- 版の組み立て ---
    edition_rows: list[tuple] = []
    editions_of: dict[str, list[str]] = {}
    for sid in sorted(reg):
        r = reg[sid]
        d = decls.get(sid, {})
        lic_raw = r["license"]
        lic_id = raw_to_lic.get(lic_raw, UNKNOWN_LICENSE_ID)
        lic_class = lic_by_id[lic_id]["license_class"]
        commercial_ok = classes[lic_class].get("commercial_ok")
        content_sha = _sha256_of(root / d["content_file"]) if d.get("content_file") else None
        redistributable = r["redistributable"]

        if sid in declared_by_source:
            specs = []
            for e in declared_by_source[sid]:
                src_row = reg[e["fetched_from"]]
                specs.append({
                    "edition_key": str(e["edition_key"]), "vintage": e.get("vintage"),
                    "fetched_at": src_row["fetched_at"], "url": src_row["url"],
                    "record_count": None, "update_mode": e.get("update_mode"), "notes": e.get("notes"),
                })
        else:
            specs = [{
                "edition_key": _default_edition_key(sid, r["fetched_at"]), "vintage": None,
                "fetched_at": r["fetched_at"], "url": r["url"],
                "record_count": r["record_count"], "update_mode": d.get("update_mode"), "notes": None,
            }]
        for sp in specs:
            eid = common.edition_id(sid, sp["edition_key"])
            editions_of.setdefault(sid, []).append(eid)
            edition_rows.append([
                eid, sid, sp["edition_key"], sp["vintage"], sp["fetched_at"], sp["url"], r["format"],
                content_sha, lic_id, lic_raw, lic_class, redistributable, commercial_ok,
                sp["record_count"], None, sp["update_mode"], sp["notes"],
            ])

    # --- 置換（edition 側）: 置換先 source は edition をちょうど 1 つ持つ ---
    sup_idx = _EDITION_COLUMNS.index("superseded_by")
    for old, new in superseded.items():
        targets = editions_of[new]
        if len(targets) != 1:
            raise AssertionError(
                f"superseded_by の先 {new!r} の edition が {len(targets)} 個ある。edition 側の置換先が一意に決まらない"
                "（版ごとの置換は declared_editions に書いて拡張する）"
            )
        for row in edition_rows:
            if row[1] == old:
                row[sup_idx] = targets[0]

    source_rows = []
    for sid in sorted(reg):
        r = reg[sid]
        source_rows.append((
            sid, common.source_public_id(sid), r["name"], r["publisher"], r["url"], None,
            r["category"], r["access_method"], superseded.get(sid), r["notes"],
        ))
    license_rows = [
        (e["license_id"], e["name_ja"], e.get("spdx_or_url"), e["license_class"],
         e.get("attribution_text"), e.get("notes"))
        for e in license_doc["licenses"]
    ]
    return license_rows, source_rows, [tuple(x) for x in edition_rows], unmapped


def _assert_alias_editions_exist(conn: sqlite3.Connection) -> None:
    """variable_alias.source_edition_id が source_edition に実在すること。"""
    bad = conn.execute(
        "SELECT a.alias, a.source_id, a.edition_key FROM variable_alias a "
        "WHERE a.source_edition_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM source_edition e WHERE e.edition_id = a.source_edition_id) LIMIT 5"
    ).fetchall()
    if bad:
        raise AssertionError(
            "variable_alias の (source_id, edition_key) が source_edition に実在しない"
            f"（例: {[tuple(b) for b in bad]}）。registry/source/editions.yaml に版を宣言するか、"
            "registry/variable_alias.csv の edition_key を直す"
        )
    bad = conn.execute(
        "SELECT a.alias, a.source_id FROM variable_alias a WHERE a.source_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM source s WHERE s.source_id = a.source_id) LIMIT 5"
    ).fetchall()
    if bad:
        raise AssertionError(
            f"variable_alias.source_id が source に無い（source_registry に無い出典。例: {[tuple(b) for b in bad]}）"
        )


DATASET_ID_MAP_CSV = common.ROOT / "registry" / "id_map" / "dataset.csv"


def assert_dataset_id_map(conn: sqlite3.Connection, path: pathlib.Path | None = None) -> int:
    """`registry/id_map/dataset.csv`（旧 `<dataset>@<年>` -> 版の ID）が、variable_alias の
    `(dataset, edition_key)` の集合と過不足なく一致し、`new_id` が source_edition に実在すること。

    旧 ID の凍結リスト（ADR-0016 の受け入れ基準「旧 ID が ちょうど 1 個の現行 ID に解決する」）の
    dataset 分。`new_id` は 1 対 1（重複すれば止まる）。行数を返す。
    """
    import csv

    with (path or DATASET_ID_MAP_CSV).open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    common.assert_unique([r["old_id"] for r in rows], "registry/id_map/dataset.csv の old_id")
    common.assert_unique([r["new_id"] for r in rows], "registry/id_map/dataset.csv の new_id")
    mapped: set[tuple[str, str]] = set()
    for r in rows:
        ds, sep, key = r["old_id"].partition("@")
        if not sep or not ds or not key:
            raise AssertionError(f"registry/id_map/dataset.csv: old_id が <dataset>@<年> の形ではない: {r['old_id']!r}")
        if r["new_id"] != common.edition_id(ds, key):
            raise AssertionError(
                f"registry/id_map/dataset.csv: old_id={r['old_id']!r} の new_id={r['new_id']!r} が "
                f"{common.edition_id(ds, key)!r} ではない"
            )
        if conn.execute("SELECT 1 FROM source_edition WHERE edition_id = ?", (r["new_id"],)).fetchone() is None:
            raise AssertionError(f"registry/id_map/dataset.csv: new_id={r['new_id']!r} が source_edition に無い")
        mapped.add((ds, key))
    in_alias = {
        (d, k) for d, k in conn.execute(
            "SELECT DISTINCT dataset, edition_key FROM variable_alias WHERE edition_key IS NOT NULL"
        )
    }
    if in_alias != mapped:
        raise AssertionError(
            "registry/id_map/dataset.csv と variable_alias の (dataset, edition_key) が一致しない: "
            f"alias のみ={sorted(in_alias - mapped)} / id_map のみ={sorted(mapped - in_alias)}"
        )
    return len(rows)


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用。src['ryuiki']: 読み取り専用の原本。"""
    ryuiki = src["ryuiki"]
    cur = ryuiki.execute(
        "SELECT source_id, name, publisher, url, category, access_method, format, license, "
        "redistributable, fetched_at, record_count, notes FROM source_registry ORDER BY source_id"
    )
    cols = [d[0] for d in cur.description]
    registry_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    license_rows, source_rows, edition_rows, unmapped = assemble(
        registry_rows, load_license_yaml(), load_editions_yaml()
    )
    if unmapped:
        n_src = sum(1 for r in registry_rows if r["license"] in set(unmapped))
        print(
            f"  警告: license.yaml に写像の無いライセンス原文が {len(unmapped)} 種（{n_src} source）。"
            f"license_id={UNKNOWN_LICENSE_ID!r} に落とした。registry/source/license.yaml の mappings に足す:"
        )
        for raw in unmapped:
            print(f"    {raw!r}")

    n_license = common.insert_many(conn, "license", ["license_id", "name_ja", "spdx_or_url", "license_class", "attribution_text", "notes"], license_rows)
    n_source = common.insert_many(conn, "source", _SOURCE_COLUMNS, source_rows)
    n_edition = common.insert_many(conn, "source_edition", _EDITION_COLUMNS, edition_rows)
    _assert_alias_editions_exist(conn)
    assert_dataset_id_map(conn)
    return {"license": n_license, "source": n_source, "source_edition": n_edition}
