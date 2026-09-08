"""Phase B 突合ハーネス（scripts/b01_derived_baseline.py / scripts/b02_derived_compare.py）の
テスト共通設定。

CI に `data/db/*.sqlite`（14GB、読み取り専用の原本）は無いので、このテストは
すべて自前で作る小さなフィクスチャ sqlite だけで完結する（本物の derived.sqlite には
一切触らない）。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
