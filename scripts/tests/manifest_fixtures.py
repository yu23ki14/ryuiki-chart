"""テスト用のマニフェスト（`manifests/<source_id>.yml`）フィクスチャ（Issue #40 Phase D）。

かつてのテストは `source_regions.yaml` 相当の YAML 文字列を書いていた。同じ形の文字列（`sources:` →
`region_id`/`consumer`/`expected_row_count`/`evidence`）を、`adapter: builtin` のマニフェスト置き場
（ディレクトリ）へ変換して書く。b03/b06 の既存のテストはこの変換越しに従来の意味のまま動く。
"""
from __future__ import annotations

import pathlib
import sqlite3

import yaml

_INPUT_BY_CONSUMER = {
    "occurrence": {"table": "organism_records"},
    "observation": {"file": "data/processed/nlni_l03b_landuse_by_watershed.csv"},
}


def write_manifest(
    manifests_dir, source_id: str, *, region: str = "jp-14", target: str = "observation",
    update_mode: str = "snapshot", input: dict | None = None, expected_row_count: int | None = None,
    evidence: str = "テスト用", adapter: str = "builtin", extra: dict | None = None,
) -> pathlib.Path:
    d = pathlib.Path(manifests_dir)
    d.mkdir(parents=True, exist_ok=True)
    doc = {
        "source": source_id, "region": region, "target": target, "update_mode": update_mode,
        "input": input or _INPUT_BY_CONSUMER[target], "adapter": adapter, "evidence": evidence,
    }
    if expected_row_count is not None:
        doc["expected_row_count"] = expected_row_count
    if extra:
        doc.update(extra)
    p = d / f"{source_id}.yml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def write_manifests_from_sources_text(manifests_dir, text: str) -> None:
    """旧 `source_regions.yaml` 形式の文字列（`sources: {id: {region_id, consumer, expected_row_count, evidence}}`）を
    `adapter: builtin` のマニフェストとして `manifests_dir` に書く。"""
    d = pathlib.Path(manifests_dir)
    d.mkdir(parents=True, exist_ok=True)
    doc = yaml.safe_load(text) or {}
    for source_id, spec in (doc.get("sources") or {}).items():
        write_manifest(
            d, source_id, region=spec["region_id"], target=spec["consumer"],
            expected_row_count=spec.get("expected_row_count"), evidence=spec.get("evidence", "テスト用"),
        )


def ensure_measurement_source_manifests(manifests_dir, ryuiki_db) -> None:
    """フィクスチャの measurements/sensor_timeseries にある（合成でない）出典のマニフェストを、無ければ書く。"""
    conn = sqlite3.connect(f"file:{ryuiki_db}?mode=ro", uri=True)
    try:
        for table in ("measurements", "sensor_timeseries"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            rows = conn.execute(
                f"SELECT DISTINCT source_id FROM {table} WHERE source_id IS NOT NULL AND COALESCE(is_synthetic, 0) <> 1"
            ).fetchall()
            for (sid,) in rows:
                if not (pathlib.Path(manifests_dir) / f"{sid}.yml").exists():
                    write_manifest(manifests_dir, sid, update_mode="append", input={"table": table})
    finally:
        conn.close()
