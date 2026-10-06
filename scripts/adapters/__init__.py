"""ソース固有の adapter（`manifests/<source_id>.yml` の `adapter:` が指すモジュール名）。

1 ファイル = 1 出典。`def rows(ctx) -> Iterator[dict]` だけを公開する。
import してよいのは **`ingest.api` と標準ライブラリだけ**（`scripts/tests/test_adapter_boundary.py` が AST で固定。
`migrate`・`sqlite3`・`registry` 等を直接 import して共通検査を迂回しない）。
"""
