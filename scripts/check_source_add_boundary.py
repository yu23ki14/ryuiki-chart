#!/usr/bin/env python3
"""新ソース追加の PR が触ってよい範囲に収まっているかを検査する（Issue #40 Phase D・J6、ADR-0012 改定・ADR-0016 受け入れ基準）。

    .venv/bin/python3 scripts/check_source_add_boundary.py [--base origin/main]
    .venv/bin/python3 scripts/check_source_add_boundary.py --files manifests/x.yml scripts/adapters/x.py

「ライブラリに手を入れずにソースを足せる」ことの機械的な証明。ソース追加の PR が変えてよいのは次のパスだけ:

- `manifests/`（宣言）・`scripts/adapters/`（ソース固有の変換）
- `registry/`（語彙の宣言ファイルの追加・変更。`registry/source/editions.yaml` 等）
- `scripts/tests/`（テスト）
- `data/sample/`（サンプルの再生成物。`serving_snapshot.json` 等。宣言差分として PR に載せる）

`scripts/migrate/**`・`scripts/b0*`・`scripts/registry/*.py`・`scripts/ingest/**`・`web/src/**` などが差分に出たら
**落とす**（ライブラリの欠落を見つけたら、先に別 PR で直す）。変更された adapter は `ingest.api` 以外を import
していないこと（`scripts/ingest/boundary.py`）も同時に検査する。

変更ファイルの取り方: 既定は `git diff --name-only <base>...HEAD`（コミット済み）＋作業ツリーの未コミット差分＋未追跡。
`--files` を渡せばそれだけを検査する（テスト・手元確認用）。
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from ingest import boundary  # noqa: E402

ALLOWED_PREFIXES = ("manifests/", "scripts/adapters/", "registry/", "scripts/tests/", "data/sample/")
DEFAULT_BASE = "origin/main"


def violations(files: list[str]) -> list[str]:
    """許可リスト外のパス（リポジトリルートからの相対・`/` 区切り）。"""
    return sorted(f for f in files if not f.startswith(ALLOWED_PREFIXES))


def adapter_problems(files: list[str], root: pathlib.Path = ROOT) -> list[str]:
    problems: list[str] = []
    for f in files:
        if f.startswith("scripts/adapters/") and f.endswith(".py") and not f.endswith("__init__.py"):
            p = root / f
            if p.exists():  # 削除された adapter は検査できない（削除は許可リスト内）
                problems += boundary.adapter_import_problems(p)
    return problems


def _git_lines(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def changed_files(base: str) -> list[str]:
    files = set(_git_lines("diff", "--name-only", f"{base}...HEAD"))
    files |= set(_git_lines("diff", "--name-only", "HEAD"))
    files |= set(_git_lines("ls-files", "--others", "--exclude-standard"))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"比較元（既定 {DEFAULT_BASE}）")
    parser.add_argument("--files", nargs="*", default=None, help="これだけを検査する（git を使わない）")
    args = parser.parse_args()

    files = sorted(args.files) if args.files is not None else changed_files(args.base)
    bad = violations(files)
    a_problems = adapter_problems(files)
    print(f"検査したパス: {len(files)} 件（許可: {', '.join(ALLOWED_PREFIXES)}）")
    if bad:
        print("許可リスト外のパスが差分に出ている（ライブラリ側の変更。ソース追加の PR に混ぜない）:")
        for f in bad:
            print(f"  - {f}")
    for p in a_problems:
        print(f"  - {p}")
    if bad or a_problems:
        return 1
    print("OK: ソース追加の境界に収まっている")
    return 0


if __name__ == "__main__":
    sys.exit(main())
