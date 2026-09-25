"""`scripts/s05_check_sample_gate_summary.py`（CI の `sample-gate` ジョブが
呼ぶ、ワークフローの heredoc から切り出したスクリプト）の単体テスト。
原本DB・材料化済みサンプルは不要——`scripts/b02_run_all_gates.py` の出力
文字列を模した自前の文字列だけで完結する。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import s05_check_sample_gate_summary as s05  # noqa: E402


_GOOD_SUMMARY = (
    "→ /tmp/derived_reconciliation_all.md\n"
    "33表中 一致: 25 / 宣言済み差分のみ: 8 / 不一致: 0 / 対象外: 0\n"
    "適用した宣言済み差分: 20件\n"
)


def test_parse_summary_extracts_all_fields():
    parsed = s05.parse_summary(_GOOD_SUMMARY)
    assert parsed == {
        "total": 33, "n_match": 25, "n_declared_only": 8,
        "n_mismatch": 0, "n_excluded": 0, "n_applied": 20,
    }


def test_parse_summary_missing_line_exits():
    with pytest.raises(SystemExit):
        s05.parse_summary("no summary line here")


def test_find_problems_none_when_all_good():
    summary = s05.parse_summary(_GOOD_SUMMARY)
    assert s05.find_problems(summary, expected_applied=20) == []


def test_find_problems_detects_wrong_applied_count():
    summary = s05.parse_summary(_GOOD_SUMMARY)
    problems = s05.find_problems(summary, expected_applied=18)
    assert len(problems) == 1
    assert "18" in problems[0] and "20" in problems[0]


def test_find_problems_detects_mismatch():
    text = "33表中 一致: 25 / 宣言済み差分のみ: 7 / 不一致: 1 / 対象外: 0\n適用した宣言済み差分: 20件\n"
    summary = s05.parse_summary(text)
    problems = s05.find_problems(summary, expected_applied=20)
    assert any("不一致" in p for p in problems)


def test_find_problems_detects_excluded():
    text = "32表中 一致: 25 / 宣言済み差分のみ: 7 / 不一致: 0 / 対象外: 1\n適用した宣言済み差分: 20件\n"
    summary = s05.parse_summary(text)
    problems = s05.find_problems(summary, expected_applied=20)
    assert any("対象外" in p for p in problems)
    assert any("33ではない" in p for p in problems)


def test_main_exits_zero_on_good_summary(tmp_path):
    path = tmp_path / "summary.txt"
    path.write_text(_GOOD_SUMMARY, encoding="utf-8")
    argv_backup = sys.argv
    sys.argv = ["s05_check_sample_gate_summary.py", "--summary-file", str(path)]
    try:
        assert s05.main() == 0
    finally:
        sys.argv = argv_backup


def test_main_exits_non_zero_on_bad_summary(tmp_path):
    path = tmp_path / "summary.txt"
    path.write_text(
        "33表中 一致: 25 / 宣言済み差分のみ: 7 / 不一致: 1 / 対象外: 0\n適用した宣言済み差分: 19件\n",
        encoding="utf-8",
    )
    argv_backup = sys.argv
    sys.argv = ["s05_check_sample_gate_summary.py", "--summary-file", str(path)]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s05.main()
    finally:
        sys.argv = argv_backup
    assert exc_info.value.code != 0


def test_main_missing_summary_file_gives_clear_message(tmp_path):
    argv_backup = sys.argv
    sys.argv = ["s05_check_sample_gate_summary.py", "--summary-file", str(tmp_path / "does-not-exist.txt")]
    try:
        with pytest.raises(SystemExit) as exc_info:
            s05.main()
    finally:
        sys.argv = argv_backup
    assert "が無い" in str(exc_info.value.code)


def test_default_expected_applied_matches_real_expected_diffs_key_count():
    """既定の `--expected-applied`（20）が、正本
    `scripts/reconcile/expected_diffs.yaml` の宣言済み差分の総数と一致すること
    （サンプルは正本をそのまま使う——data/sample 専用の免除ファイルは持たない）。
    """
    from reconcile.common import load_yaml

    real = load_yaml(ROOT / "scripts" / "reconcile" / "expected_diffs.yaml")
    total_keys = sum(len(v) for v in real.values())
    assert s05.DEFAULT_EXPECTED_APPLIED == total_keys
