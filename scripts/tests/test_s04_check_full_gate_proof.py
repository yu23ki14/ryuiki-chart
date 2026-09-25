"""`scripts/s04_check_full_gate_proof.py`（CI の `full-gate-proof-check`
ジョブが呼ぶ、ワークフローの heredoc から切り出したスクリプト）の単体テスト。
原本DBは不要——コミット済みの `reports/full_gate_proof.json`・
`data/sample/manifest.json` と、自前の小さな改変版だけで完結する。

これはレビュー指摘（ワークフローに直接埋め込んだ Python はテストされず、
`manifest.json`/`full_gate_proof.json` のキーの形が食い違ったまま
`KeyError` で落ちる不具合が気づかれずに残っていた）への対応そのもの。
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import s04_check_full_gate_proof as s04  # noqa: E402

_PROOF_PATH = ROOT / "reports" / "full_gate_proof.json"
_MANIFEST_PATH = ROOT / "data" / "sample" / "manifest.json"

pytestmark = pytest.mark.skipif(
    not _PROOF_PATH.exists() or not _MANIFEST_PATH.exists(),
    reason="reports/full_gate_proof.json または data/sample/manifest.json が無い",
)


@pytest.fixture(scope="module")
def real_proof() -> dict:
    return json.loads(_PROOF_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_manifest() -> dict:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# コミット済みの証明・manifest.json で通ること
# ---------------------------------------------------------------------------


def test_committed_proof_and_manifest_pass(capsys, monkeypatch):
    """`scripts/s04_check_full_gate_proof.py` を既定の引数（コミット済みの
    reports/full_gate_proof.json・data/sample/manifest.json）で呼ぶと
    exit 0 になる。
    """
    monkeypatch.setattr(sys, "argv", ["s04_check_full_gate_proof.py"])
    assert s04.main() == 0
    out = capsys.readouterr().out
    assert "OK" in out


def test_check_pipeline_path_hashes_no_problems_against_head(real_proof):
    """コミット済みの証明の pipeline_path_hashes は、今の HEAD と一致する
    （実際に git rev-parse を呼ぶ——`scripts/b00_run_full_gate.py` を
    パイプラインのファイルを触った後に回し直し忘れていないかの本物の検査）。
    """
    problems = s04.check_pipeline_path_hashes(real_proof)
    assert problems == []


def test_check_source_hashes_match_manifest_no_problems(real_proof, real_manifest):
    problems = s04.check_source_hashes_match_manifest(real_proof, real_manifest)
    assert problems == []


def test_shared_keys_are_non_empty(real_proof, real_manifest):
    """比べる対象（両方が持つキー）が実際に複数あることの自己チェック
    （レビュー指摘: 以前は ryuiki.sqlite/cells.sqlite の2つだけを、しかも
    キーの形が食い違ったまま比べていた）。
    """
    shared = set(real_proof["source_hashes"]) & set(real_manifest["source_files"])
    assert len(shared) >= 5


# ---------------------------------------------------------------------------
# パイプラインのファイルのハッシュが1つ違うと落ちること
# ---------------------------------------------------------------------------


def test_pipeline_path_hash_mismatch_is_detected(real_proof):
    mutated = copy.deepcopy(real_proof)
    a_path = next(iter(mutated["pipeline_path_hashes"]))
    mutated["pipeline_path_hashes"][a_path] = "0" * 40
    problems = s04.check_pipeline_path_hashes(mutated)
    assert problems
    assert any(a_path in p for p in problems)


def test_main_exits_non_zero_when_pipeline_path_hash_mismatches(tmp_path, real_proof, real_manifest):
    mutated = copy.deepcopy(real_proof)
    a_path = next(iter(mutated["pipeline_path_hashes"]))
    mutated["pipeline_path_hashes"][a_path] = "0" * 40
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(mutated), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(real_manifest), encoding="utf-8")

    argv_backup = sys.argv
    sys.argv = ["s04_check_full_gate_proof.py", "--proof", str(proof_path), "--manifest", str(manifest_path)]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s04.main()
    finally:
        sys.argv = argv_backup
    assert exc_info.value.code != 0
    assert "食い違う" in str(exc_info.value.code)


# ---------------------------------------------------------------------------
# 原本のハッシュが食い違うと落ちること
# ---------------------------------------------------------------------------


def test_check_source_hashes_match_manifest_detects_mismatch():
    proof = {"source_hashes": {"data/db/ryuiki.sqlite": "a" * 64, "data/db/cells.sqlite": "b" * 64}}
    manifest = {"source_files": {"data/db/ryuiki.sqlite": "a" * 64, "data/db/cells.sqlite": "DIFFERENT"}}
    problems = s04.check_source_hashes_match_manifest(proof, manifest)
    assert len(problems) == 1
    assert "data/db/cells.sqlite" in problems[0]


def test_check_source_hashes_match_manifest_no_shared_keys_is_a_problem():
    proof = {"source_hashes": {"data/db/ryuiki.sqlite": "a" * 64}}
    manifest = {"source_files": {"totally/different/key": "b" * 64}}
    problems = s04.check_source_hashes_match_manifest(proof, manifest)
    assert len(problems) == 1
    assert "共通のキーが" in problems[0]


def test_main_exits_non_zero_when_source_hash_mismatches(tmp_path, real_proof, real_manifest):
    mutated_manifest = copy.deepcopy(real_manifest)
    a_key = next(iter(mutated_manifest["source_files"]))
    mutated_manifest["source_files"][a_key] = "0" * 64

    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(real_proof), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(mutated_manifest), encoding="utf-8")

    argv_backup = sys.argv
    sys.argv = ["s04_check_full_gate_proof.py", "--proof", str(proof_path), "--manifest", str(manifest_path)]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s04.main()
    finally:
        sys.argv = argv_backup
    assert exc_info.value.code != 0
    assert "食い違う" in str(exc_info.value.code)


# ---------------------------------------------------------------------------
# キーが欠けていると、KeyError ではなく分かりやすいメッセージで落ちること
# ---------------------------------------------------------------------------


def test_main_missing_pipeline_path_hashes_key_gives_clear_message_not_keyerror(tmp_path, real_manifest):
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps({"source_hashes": {}}), encoding="utf-8")  # pipeline_path_hashes が無い
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(real_manifest), encoding="utf-8")

    argv_backup = sys.argv
    sys.argv = ["s04_check_full_gate_proof.py", "--proof", str(proof_path), "--manifest", str(manifest_path)]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s04.main()
    finally:
        sys.argv = argv_backup
    assert not isinstance(exc_info.value.__cause__, KeyError)
    message = str(exc_info.value.code)
    assert "pipeline_path_hashes" in message
    assert "必須キーが無い" in message


def test_main_missing_source_files_key_in_manifest_gives_clear_message(tmp_path, real_proof):
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(real_proof), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"row_counts": {}}), encoding="utf-8")  # source_files が無い

    argv_backup = sys.argv
    sys.argv = ["s04_check_full_gate_proof.py", "--proof", str(proof_path), "--manifest", str(manifest_path)]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s04.main()
    finally:
        sys.argv = argv_backup
    assert not isinstance(exc_info.value.__cause__, KeyError)
    message = str(exc_info.value.code)
    assert "source_files" in message
    assert "必須キーが無い" in message


def test_main_missing_proof_file_gives_clear_message(tmp_path, real_manifest):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(real_manifest), encoding="utf-8")

    argv_backup = sys.argv
    sys.argv = [
        "s04_check_full_gate_proof.py",
        "--proof", str(tmp_path / "does-not-exist.json"),
        "--manifest", str(manifest_path),
    ]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s04.main()
    finally:
        sys.argv = argv_backup
    assert "が無い" in str(exc_info.value.code)
