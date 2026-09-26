"""`web/package.json` の `build:v2` の段の順序が、`scripts/b00_run_full_gate.py`
の `PIPELINE_STEPS`（CLAUDE.md の実行順の正本）の部分列として一致することを
機械検証する（Issue #48 PR-0 §2、/simplify 指摘）。

`build:v2` は r01（`scripts/ensure-registry.sh` 経由。無条件のフル再構築ではなく
「古ければ作り直す」判定に変わった——`scripts/ensure-registry.sh` 自体は
`scripts/r01_build_registry.py --check-fresh`/`build:registry` を呼ぶだけ）→
b03→b04→b06→b09→b07 の6段。`PIPELINE_STEPS` は r01→b03→b04→b05→b06→b09→b07→
b08→b10→b11→b12 の11段（v1 射影も含む、CLAUDE.md の実行順そのまま）なので、
`build:v2` はその**部分列**（間に他の段が挟まってよいが、相対順序は保つ）で
あるべき——手で2箇所に同じ順序を書き、片方だけ変えて食い違う事故を防ぐ。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402

PACKAGE_JSON = ROOT / "web" / "package.json"

# `scripts/ensure-registry.sh` は「r01_build_registry.py --check-fresh を見て
# 古ければ build:registry（= r01_build_registry.py）を呼ぶ」というラッパーで、
# PIPELINE_STEPS 上は r01_build_registry.py の代理として扱う。
_ENSURE_REGISTRY_ALIAS = "scripts/r01_build_registry.py"


def _extract_build_v2_steps() -> list[str]:
    """`web/package.json` の `scripts["build:v2"]` から、実行されるスクリプトを
    出現順に抜き出す（`scripts/run-python.sh scripts/bNN_*.py` の並び、および
    `scripts/ensure-registry.sh` を r01 の代理として）。
    """
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    command = data["scripts"]["build:v2"]
    steps: list[str] = []
    for part in command.split("&&"):
        part = part.strip()
        if part == "scripts/ensure-registry.sh":
            steps.append(_ENSURE_REGISTRY_ALIAS)
            continue
        m = re.search(r"scripts/run-python\.sh\s+(scripts/\S+\.py)", part)
        if m:
            steps.append(m.group(1))
            continue
        raise AssertionError(f"build:v2 の中に認識できない断片がある: {part!r}")
    return steps


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """`needle` が `haystack` の部分列（間に他の要素が挟まってよいが、相対順序は
    保つ）かどうか。`in` が同じイテレータを消費し続ける性質を使った定石。
    """
    it = iter(haystack)
    return all(step in it for step in needle)


def test_build_v2_steps_are_non_empty_and_parse_cleanly():
    steps = _extract_build_v2_steps()
    assert steps, "build:v2 からスクリプトが1つも抽出できなかった（正規表現が壊れている可能性）"
    assert steps[0] == _ENSURE_REGISTRY_ALIAS
    assert steps[-1] == "scripts/b07_build_occurrence_cube.py"


def test_build_v2_steps_are_a_subsequence_of_pipeline_steps():
    steps = _extract_build_v2_steps()
    pipeline = list(b00.PIPELINE_STEPS)
    assert _is_subsequence(steps, pipeline), (
        f"build:v2 の順序 {steps} が PIPELINE_STEPS {pipeline} の部分列になっていない"
        "（web/package.json の build:v2 と scripts/b00_run_full_gate.py の "
        "PIPELINE_STEPS のどちらかだけを変えて順序がずれた可能性がある）。"
    )


def test_build_v2_steps_omit_v1_only_projection_scripts():
    """b05/b08/b10/b11/b12（v1 射影）は build:v2 に含めない
    （v2 は observation/observation_agg/occurrence/occurrence_agg/occurrence_place
    しか作らない——CLAUDE.md「build:v2」節参照）。"""
    steps = set(_extract_build_v2_steps())
    v1_only = {
        "scripts/b05_project_v1.py",
        "scripts/b08_project_occurrence_v1.py",
        "scripts/b10_project_documents_v1.py",
        "scripts/b11_project_place_v1.py",
        "scripts/b12_project_taxon_v1.py",
    }
    assert not (steps & v1_only), f"build:v2 に v1 専用の射影段が混ざっている: {steps & v1_only}"


def test_mutating_build_v2_order_would_be_caught(monkeypatch):
    """このテスト自体が偽陽性（何を変えても通る）でないことの自己検証——
    `build:v2` の順序を入れ替えたら `test_build_v2_steps_are_a_subsequence_of_pipeline_steps`
    と同じ判定が落ちることを確認する。
    """
    steps = _extract_build_v2_steps()
    reordered = steps[:]
    reordered[1], reordered[2] = reordered[2], reordered[1]  # b03/b04 を入れ替える
    assert not _is_subsequence(reordered, list(b00.PIPELINE_STEPS))
