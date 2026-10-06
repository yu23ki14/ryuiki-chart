"""`dist/datapackage.json`（Frictionless Data Package 記述子）を組み立てる。

- 時刻は入れない（同じ入力なら同じバイト）。`built_from` は入力の指紋だけ。
- `sources[]` は L2（observation/occurrence）が実際に参照する版だけを、registry の
  `source_edition`/`source`/`license` から引く。旗（redistributable・license_class 等）は
  出力を絞る根拠にしない（ADR-0028）。ここでは情報として載せるだけで、写像漏れ・未確認の
  件数も黙って埋めずに出す。
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
from typing import Sequence

SPEC_VERSION = "dist@1"
PROFILE = "data-package"
PARQUET_MEDIATYPE = "application/vnd.apache.parquet"
# 合成データの出典 ID の接頭辞（ryuiki.sqlite の source_registry で is_synthetic の出典。b03/b06 が除外する）。
SYNTHETIC_SOURCE_PREFIX = "synthetic_"
# 利用条件が確定していないことを示す license_class（件数を datapackage.json と README に出す）。
UNRESOLVED_LICENSE_CLASSES = ("unknown", "unconfirmed")


def resource_name(table: str, partition_value: str | None = None) -> str:
    """Frictionless のリソース名は小文字・数字・`._-` のみ。"""
    base = table if partition_value is None else f"{table}.{partition_value}"
    return re.sub(r"[^a-z0-9._-]", "-", base.lower())


def collect_sources(
    registry: sqlite3.Connection, edition_rows: dict[str, dict[str, int]],
) -> tuple[list[dict], dict]:
    """`edition_rows`: {source_edition_id: {"observation": n, "occurrence": n}}（NULL は ""）。

    返り値: (sources[], license_summary)。edition が registry に無い ID があれば落とす
    （黙って捨てない）。source_edition_id が無い行（""）は `license_summary.rows_without_edition` に数える。
    """
    out: list[dict] = []
    rows_without_edition = {"observation": 0, "occurrence": 0}
    for eid in sorted(edition_rows):
        counts = edition_rows[eid]
        if eid == "":
            for k, v in counts.items():
                rows_without_edition[k] += v
            continue
        r = registry.execute(
            """
            SELECT e.edition_id, e.source_id, s.name_ja, s.publisher, e.edition_key, e.vintage, e.fetched_at, e.url,
                   e.update_mode, e.license_id, e.license_class, e.redistributable, e.commercial_ok,
                   e.license_raw, l.attribution_text
            FROM source_edition e
            LEFT JOIN source s ON s.source_id = e.source_id
            LEFT JOIN license l ON l.license_id = e.license_id
            WHERE e.edition_id = ?
            """,
            (eid,),
        ).fetchone()
        if r is None:
            raise RuntimeError(f"L2 が参照する source_edition_id {eid!r} が registry の source_edition に無い")
        (edition_id, source_id, name_ja, publisher, edition_key, vintage, fetched_at, url, update_mode,
         license_id, license_class, redistributable, commercial_ok, license_raw, attribution) = r
        out.append({
            "source_edition_id": edition_id,
            "source_id": source_id,
            "name_ja": name_ja,
            "publisher": publisher,
            "edition_key": edition_key,
            "vintage": vintage,
            "fetched_at": fetched_at,
            "url": url,
            "update_mode": update_mode,
            "license_id": license_id,
            "license_class": license_class,
            "license_raw": license_raw,
            "attribution": attribution,
            "redistributable": redistributable,
            "commercial_ok": commercial_ok,
            "rows": {k: counts.get(k, 0) for k in ("observation", "occurrence")},
        })
    by_class: dict[str, int] = {}
    for s in out:
        by_class[s["license_class"]] = by_class.get(s["license_class"], 0) + 1
    summary = {
        "editions": len(out),
        "by_license_class": dict(sorted(by_class.items())),
        "unresolved_license_class": {
            c: sorted(s["source_edition_id"] for s in out if s["license_class"] == c)
            for c in UNRESOLVED_LICENSE_CLASSES
        },
        "rows_without_edition": rows_without_edition,
    }
    return out, summary


def build(
    *, resources: Sequence[dict], sources: Sequence[dict], license_summary: dict, built_from: dict, writer_spec: str,
) -> dict:
    return {
        "profile": PROFILE,
        "name": "ryuiki-dist",
        "title": "流域カルテ 配布データ（L2 正準モデル・キューブ・レジストリ）",
        "spec_version": SPEC_VERSION,
        "writer": writer_spec,
        "notes": (
            "出力を絞る根拠は無い（ADR-0028。扱うデータは全て公開済み）。redistributable・license_class は"
            "出典の旗で、行を除外する条件ではない。合成データは含まない。座標は原本どおり（ぼかし・丸めなし）。"
        ),
        "built_from": built_from,
        "license_summary": license_summary,
        "sources": list(sources),
        "resources": list(resources),
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def load(path: pathlib.Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
