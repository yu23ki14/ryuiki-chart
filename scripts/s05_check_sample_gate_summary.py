#!/usr/bin/env python3
"""`scripts/b02_run_all_gates.py` の標準出力（サンプルのゲートの要約行）を
読み、「空振り」（宣言どおりの数字になっていない）していないことを数値で
確かめる（CI の `sample-gate` ジョブから呼ぶ）。

    python3 scripts/b02_run_all_gates.py ... | tee /tmp/gate_summary.txt
    python3 scripts/s05_check_sample_gate_summary.py --summary-file /tmp/gate_summary.txt

**このスクリプトはワークフローの heredoc から切り出したもの**
（`scripts/s04_check_full_gate_proof.py` と同じ理由。レビュー指摘: ワークフローに
直接埋め込んだ Python は pytest で検証されない）。

確認する内容:
- 対象テーブル数が33であること。
- 一致＋宣言済み差分のみ が33（＝不一致・対象外が無い）であること。
- 不一致が0であること。
- 対象外が0であること。
- 適用した宣言済み差分が `--expected-applied`（既定20。正本
  `scripts/reconcile/expected_diffs.yaml` の全キー数）と一致すること。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

DEFAULT_EXPECTED_APPLIED = 20

_SUMMARY_RE = re.compile(
    r"(\d+)表中 一致: (\d+) / 宣言済み差分のみ: (\d+) / 不一致: (\d+) / 対象外: (\d+)"
)
_APPLIED_RE = re.compile(r"適用した宣言済み差分: (\d+)件")


def parse_summary(text: str) -> dict[str, int]:
    """`scripts/b02_run_all_gates.py` の標準出力から要約の数字を取り出す。
    要約行が見つからなければ `SystemExit`（出力全文を添えて）。
    """
    m = _SUMMARY_RE.search(text)
    if not m:
        sys.exit(f"b02_run_all_gates.py の出力からサマリ行を抽出できなかった:\n{text}")
    total, n_match, n_declared, n_mismatch, n_excluded = (int(g) for g in m.groups())
    applied_m = _APPLIED_RE.search(text)
    n_applied = int(applied_m.group(1)) if applied_m else 0
    return {
        "total": total,
        "n_match": n_match,
        "n_declared_only": n_declared,
        "n_mismatch": n_mismatch,
        "n_excluded": n_excluded,
        "n_applied": n_applied,
    }


def find_problems(summary: dict[str, int], expected_applied: int) -> list[str]:
    problems = []
    if summary["total"] != 33:
        problems.append(f"対象テーブル数が33ではない: {summary['total']}")
    combined = summary["n_match"] + summary["n_declared_only"]
    if combined != 33:
        problems.append(f"一致+宣言済み差分のみ が33ではない: {summary['n_match']}+{summary['n_declared_only']}={combined}")
    if summary["n_mismatch"] != 0:
        problems.append(f"不一致が0ではない: {summary['n_mismatch']}")
    if summary["n_excluded"] != 0:
        problems.append(f"対象外が0ではない: {summary['n_excluded']}")
    if summary["n_applied"] != expected_applied:
        problems.append(f"適用した宣言済み差分が{expected_applied}ではない: {summary['n_applied']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary-file", required=True, help="scripts/b02_run_all_gates.py の標準出力を書いたファイル")
    parser.add_argument("--expected-applied", type=int, default=DEFAULT_EXPECTED_APPLIED)
    args = parser.parse_args()

    path = pathlib.Path(args.summary_file)
    if not path.exists():
        sys.exit(f"{path} が無い。scripts/b02_run_all_gates.py の出力を書いてから呼ぶこと。")
    text = path.read_text(encoding="utf-8")

    summary = parse_summary(text)
    problems = find_problems(summary, args.expected_applied)
    if problems:
        sys.exit("空振りしていないことの確認に失敗した:\n- " + "\n- ".join(problems))

    print(
        f"OK: 一致={summary['n_match']} / 宣言済み差分のみ={summary['n_declared_only']} / "
        f"不一致={summary['n_mismatch']} / 対象外={summary['n_excluded']} / "
        f"適用した宣言済み差分={summary['n_applied']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
