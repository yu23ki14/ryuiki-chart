#!/usr/bin/env python3
"""`dist/` の機械検査 CLI（Issue #40 Phase D 担当 P）。検査の中身は `scripts/dist/check.py`。

終了コード 0=合格 / 1=不変条件違反・整合違反。CI の sample-gate が `d01_build_dist.py` の後に回す。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dist.check import check_dist  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dist", type=pathlib.Path, default=ROOT / "dist")
    ap.add_argument("--v2-db", type=pathlib.Path, default=ROOT / "data" / "db" / "v2.sqlite")
    ap.add_argument("--registry-db", type=pathlib.Path,
                    default=pathlib.Path(os.environ.get("RYUIKI_REGISTRY_DB") or ROOT / "data" / "db" / "registry.sqlite"))
    a = ap.parse_args(argv)
    errors = check_dist(a.dist, a.v2_db, a.registry_db)
    if errors:
        print(f"dist 検査: {len(errors)} 件の違反", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"dist 検査: 合格（{a.dist}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
