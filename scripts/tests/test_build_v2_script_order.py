"""`web/package.json` の `build:v2` の段の順序が、`scripts/b00_run_full_gate.py`
の `PIPELINE_STEPS`（CLAUDE.md の実行順の正本）と**完全に一致する**ことを
機械検証する（Issue #48 PR-0 §2、/simplify 指摘。PR-2 §4 で b13 を追加。
PR-5 で v1 射影・v1互換キューブの段が `PIPELINE_STEPS` から消え、部分列の
判定から完全一致の判定に変わった）。

`build:v2` は r01（`scripts/ensure-registry.sh` 経由。無条件のフル再構築ではなく
「古ければ作り直す」判定に変わった——`scripts/ensure-registry.sh` 自体は
`scripts/r01_build_registry.py --check-fresh`/`build:registry` を呼ぶだけ）→
b03→b04→b06→b09→b07→b13 の7段。`PIPELINE_STEPS` も同じ7段（各要素は
`(script, args)` の組。`args` は無視する）。手で2箇所に同じ順序を書き、片方だけ
変えて食い違う事故を防ぐ。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402


def _pipeline_step_scripts() -> list[str]:
    """`PIPELINE_STEPS`（`(script, args)` の組の並び）からスクリプト名だけを
    抜き出す（`args` は順序の判定に関係ない）。
    """
    return [script for script, _args in b00.PIPELINE_STEPS]


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


def test_build_v2_steps_are_non_empty_and_parse_cleanly():
    steps = _extract_build_v2_steps()
    assert steps, "build:v2 からスクリプトが1つも抽出できなかった（正規表現が壊れている可能性）"
    assert steps[0] == _ENSURE_REGISTRY_ALIAS
    assert steps[-1] == "scripts/b13_build_summary.py"


def test_pipeline_steps_are_exactly_the_build_v2_steps():
    steps = _extract_build_v2_steps()
    pipeline = _pipeline_step_scripts()
    assert steps == pipeline, (
        f"build:v2 の順序 {steps} が PIPELINE_STEPS のスクリプト名 {pipeline} と一致しない"
        "（web/package.json の build:v2 と scripts/b00_run_full_gate.py の PIPELINE_STEPS の"
        "どちらかだけを変えて順序がずれた可能性がある）。"
    )


def test_every_pipeline_step_runs_with_default_paths():
    """全段が引数無し（既定パス）で呼ばれる——v1互換キューブの段（別ファイルへ書く引数付きの段）は無い。"""
    assert all(args == () for _script, args in b00.PIPELINE_STEPS)


def test_pipeline_steps_omit_removed_v1_scripts():
    """b05/b08/b10/b11/b12（v1 射影）と b02（v1 との突合ゲート）は Issue #48 PR-5 で
    消えた。v2 は observation/observation_agg/occurrence/occurrence_agg/occurrence_place と
    summary しか作らない。"""
    removed = {
        "scripts/b05_project_v1.py",
        "scripts/b08_project_occurrence_v1.py",
        "scripts/b10_project_documents_v1.py",
        "scripts/b11_project_place_v1.py",
        "scripts/b12_project_taxon_v1.py",
        "scripts/b02_run_all_gates.py",
    }
    assert not (set(_pipeline_step_scripts()) & removed)
    assert not any((ROOT / p).exists() for p in removed)


def test_mutating_build_v2_order_would_be_caught():
    """このテスト自体が偽陽性（何を変えても通る）でないことの自己検証——
    `build:v2` の順序を入れ替えたら `test_pipeline_steps_are_exactly_the_build_v2_steps`
    と同じ判定が落ちることを確認する。
    """
    steps = _extract_build_v2_steps()
    reordered = steps[:]
    reordered[1], reordered[2] = reordered[2], reordered[1]  # b03/b04 を入れ替える
    assert reordered != _pipeline_step_scripts()
