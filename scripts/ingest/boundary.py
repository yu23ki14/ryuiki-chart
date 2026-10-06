"""adapter の import 境界の AST 検査（Issue #40 Phase D、ADR-0012 改定）。

`scripts/adapters/*.py` が import してよいのは **`ingest.api` と標準ライブラリだけ**。`migrate`・`registry`・
`sqlite3`・サードパーティ・相対 import を許すと、共通検査（重複・解決率・期間・checks・宣言突合）を迂回する経路ができる。
動的な迂回（`__import__`・`importlib`・`eval`/`exec`/`compile`・`open`）も止める（入力は `ctx.input_rows()` だけ）。

テスト（`scripts/tests/test_adapter_boundary.py`）と `scripts/check_source_add_boundary.py` が同じ関数を使う。
"""
from __future__ import annotations

import ast
import pathlib
import sys

ALLOWED_THIRD_PARTY_FROM = ("ingest.api",)
# `sqlite3` は標準ライブラリだが、原本へ直接つなげてしまうので adapter では禁止する。
FORBIDDEN_STDLIB = frozenset({"sqlite3", "importlib", "subprocess", "socket", "urllib", "http", "ctypes", "pickle"})
FORBIDDEN_CALLS = frozenset({"__import__", "eval", "exec", "compile", "open"})


def _stdlib(top: str) -> bool:
    return top in sys.stdlib_module_names and top not in FORBIDDEN_STDLIB


def adapter_import_problems(path) -> list[str]:
    """`path`（adapter の .py）の境界違反を文字列のリストで返す（空なら問題なし）。"""
    path = pathlib.Path(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ingest.api":
                    continue
                if not _stdlib(alias.name.split(".")[0]):
                    problems.append(f"{path}:{node.lineno}: `import {alias.name}` は許可されない（標準ライブラリと ingest.api だけ）")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                problems.append(f"{path}:{node.lineno}: 相対 import は許可されない")
                continue
            mod = node.module or ""
            if mod in ALLOWED_THIRD_PARTY_FROM:
                continue
            if mod == "ingest" and all(a.name == "api" for a in node.names):
                continue
            if not _stdlib(mod.split(".")[0]):
                problems.append(f"{path}:{node.lineno}: `from {mod} import …` は許可されない（標準ライブラリと ingest.api だけ）")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            problems.append(f"{path}:{node.lineno}: `{node.func.id}()` は許可されない（入力は ctx.input_rows() だけ）")
    return problems


def check_adapters_dir(adapters_dir) -> list[str]:
    problems: list[str] = []
    for p in sorted(pathlib.Path(adapters_dir).glob("*.py")):
        if p.name == "__init__.py":
            continue
        problems += adapter_import_problems(p)
    return problems
