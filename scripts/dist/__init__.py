"""`dist/`（Parquet 配布物。ADR-0001 改定）を作る・検査する部品。

書き手は `scripts/d01_build_dist.py`、検査は `scripts/d02_check_dist.py`。
`scripts/b0*.py`・`scripts/migrate/**` は import しない（v2 パイプラインの指紋に
dist の変更を混ぜない。dist は v2 の派生物であって入力ではない）。
"""
