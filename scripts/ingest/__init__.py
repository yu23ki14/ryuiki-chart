"""ソース取り込みの共通ライブラリ（Issue #40 Phase D、ADR-0012 改定）。

- `manifest.py`: `manifests/<source_id>.yml` の読み込みと構造検証
- `api.py`: adapter が import してよい**唯一の面**（`scripts/adapters/*.py` は `ingest.api` と標準ライブラリだけを
  import できる。AST 検査 `scripts/tests/test_adapter_boundary.py` が固定している）
- `runner.py`: adapter を回し、共通検査（checks・重複・解決率）を通して b06 の `occurrence` 行へ変換する
"""
