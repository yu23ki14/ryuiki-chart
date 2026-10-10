"""region の語彙（`registry/region.yaml`）を読む（Issue #32-3。ADR-0002・ADR-0024）。

region_id（`jp-14` 等）ごとの**時刻帯**（IANA 名と UTC オフセット）の唯一の置き場。
手書きの正は `registry/region.yaml`、そこから `scripts/registry/build_region.py` が
`registry.sqlite` の `region` 表を作り（→ D1 → `generated-client.ts` の `REGION_TIME` →
`lookup-client.ts` の `regionTimeZone()`）、パイプライン側（b03/b06/period.py）は
この関数でファイルを直接読む（b03/b06 は出典宣言との突き合わせに使う）。

以前は `scripts/migrate/source_regions.yaml` の `regions:` に同じ情報があった。二重管理を
やめるため撤去し、残っていたら止める（`source_regions.py` の `reject_legacy_regions_key`）。
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from .common import MigrationError, load_yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REGION_YAML = ROOT / "registry" / "region.yaml"

REQUIRED_REGION_KEYS = ("name_ja", "tz_name", "utc_offset", "evidence")

# `'+09:00'`/`'-05:30'` の形だけを許す。`period.parse_utc_offset` は符号1文字＋2桁＋':'＋2桁だけを
# 前提に減算するため、`"09:00"`（符号無し）のような値は符号判定が黙って負に倒れる。
UTC_OFFSET_PATTERN = re.compile(r"^[+-][0-9]{2}:[0-9]{2}$")
# IANA 時刻帯名（`Area/Location`）の最低限の形。実在の検査は web 側のテスト（Intl）が行う。
TZ_NAME_PATTERN = re.compile(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+)+$")


# terrain.summit の数値キーと許容範囲（日本の範囲。単位は度・m）。
SUMMIT_RANGES = (("lat", 20.0, 46.0), ("lon", 122.0, 154.0), ("elevation_m", 1.0, 3800.0))


@dataclass(frozen=True)
class RegionTime:
    region_id: str
    name_ja: str
    tz_name: str
    utc_offset: str
    evidence: str
    # `migrate.period.EntryUsage`（未使用宣言の検出）が出典宣言と同じ形で扱えるようにするダミー属性。
    # region には件数の宣言が無いので常に None。
    expected_row_count: int | None = None


def region_problems(raw: object) -> list[str]:
    """`region.yaml` の生の dict の形の問題点を文字列のリストで返す（空なら問題なし。
    原本 DB を必要としない構造検証。CI とロード時の両方が使う）。"""
    if not isinstance(raw, dict) or not raw:
        return ["region.yaml が空、またはマッピングになっていない"]
    problems: list[str] = []
    for region_id, spec in raw.items():
        label = f"{region_id}"
        if not isinstance(spec, dict):
            problems.append(f"{label}: エントリがマッピングになっていない")
            continue
        missing = [k for k in REQUIRED_REGION_KEYS if not spec.get(k)]
        if missing:
            problems.append(f"{label}: 必須キーが無い/空: {missing}")
            continue
        if not UTC_OFFSET_PATTERN.fullmatch(str(spec["utc_offset"])):
            problems.append(f"{label}: utc_offset が想定外の形（'+HH:MM'/'-HH:MM' のみ。実際: {spec['utc_offset']!r}）")
        if not TZ_NAME_PATTERN.fullmatch(str(spec["tz_name"])):
            problems.append(f"{label}: tz_name が IANA 名の形でない: {spec['tz_name']!r}")
        if "terrain" in spec:
            problems.extend(_terrain_problems(label, spec["terrain"]))
    return problems


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _terrain_problems(label: str, terrain: object) -> list[str]:
    """`terrain.summit`（地域の最高峰の宣言。zone v2 の 1/2 の境に使う。AMAMI_STEP0 §1.2）の形。
    `terrain` が無い region は通す（zone を付けない地域・既存のフィクスチャを壊さない）。"""
    if not isinstance(terrain, dict) or not isinstance(terrain.get("summit"), dict):
        return [f"{label}: terrain は summit のマッピングを含む必要がある"]
    summit = terrain["summit"]
    problems: list[str] = []
    if not isinstance(summit.get("name_ja"), str) or not summit["name_ja"]:
        problems.append(f"{label}: terrain.summit.name_ja が文字列でない")
    for key, lo, hi in SUMMIT_RANGES:
        v = summit.get(key)
        if not _is_number(v):
            problems.append(f"{label}: terrain.summit.{key} が数値でない: {v!r}")
        elif not lo <= v <= hi:
            problems.append(f"{label}: terrain.summit.{key} が範囲外（{lo}〜{hi}）: {v!r}")
    return problems


def load_regions(path=DEFAULT_REGION_YAML) -> dict[str, RegionTime]:
    """`registry/region.yaml` を読んで `{region_id: RegionTime}` を返す。形が不正なら止める
    （黙って JST に倒さない）。"""
    raw = load_yaml(path)
    problems = region_problems(raw)
    if problems:
        raise MigrationError(f"{path} の形が不正:\n- " + "\n- ".join(problems))
    return {
        region_id: RegionTime(
            region_id=region_id,
            name_ja=spec["name_ja"],
            tz_name=spec["tz_name"],
            utc_offset=spec["utc_offset"],
            evidence=spec["evidence"],
        )
        for region_id, spec in raw.items()
    }
