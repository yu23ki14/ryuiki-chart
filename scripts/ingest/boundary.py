"""adapter の import 境界の AST 検査（Issue #40 Phase D、ADR-0012 改定）。

`scripts/adapters/*.py` が import してよいのは **`ingest.api` と、許可リストの純粋な標準ライブラリだけ**
（`ALLOWED_STDLIB`: 文字列・日時・数値・JSON の処理。ファイル・プロセス・ネットワーク・リフレクションに触れないもの）。
禁止リスト方式ではなく許可リスト方式なので、`os`・`pathlib`・`io`・`shutil`・`sqlite3`・`importlib`・サードパーティ・
`migrate`/`registry`・相対 import は、どれも書いた時点で止まる（共通検査〔重複・解決率・期間・checks・宣言突合〕と
読み取り専用の入力窓 `ctx.input_rows()` を迂回する経路を作らない）。

動的な迂回も止める:

- 組み込み関数・名前: `__import__`・`eval`・`exec`・`compile`・`open`・`getattr`・`setattr`・`delattr`・`vars`・`globals`・
  `locals`・`input`・`breakpoint`・`__builtins__`・`builtins`（呼び出さなくても名前の参照だけで止める）
- 属性: 先頭が `_` の属性（`__class__`・`__subclasses__`・`__globals__`・`__dict__` …。リフレクションで迂回する道）

テスト（`scripts/tests/test_adapter_boundary.py`）と `scripts/check_source_add_boundary.py` が同じ関数を使う。
許可リストに足すときは、副作用の無い純粋なモジュールだけにする（ここを緩めるのは別 PR で、理由を書く）。
"""
from __future__ import annotations

import ast
import pathlib

ALLOWED_STDLIB = frozenset({
    "__future__", "typing", "datetime", "re", "json", "math", "decimal", "fractions",
    "collections", "itertools", "unicodedata",
})
ALLOWED_INGEST = ("ingest.api",)
FORBIDDEN_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "getattr", "setattr", "delattr", "vars", "globals", "locals",
    "input", "breakpoint", "__builtins__", "builtins",
})


def _module_allowed(module: str) -> bool:
    return module in ALLOWED_INGEST or module.split(".")[0] in ALLOWED_STDLIB


def adapter_import_problems(path) -> list[str]:
    """`path`（adapter の .py）の境界違反を文字列のリストで返す（空なら問題なし）。"""
    path = pathlib.Path(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []

    def bad(node, msg: str) -> None:
        problems.append(f"{path}:{node.lineno}: {msg}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    bad(node, f"`import {alias.name}` は許可されない（ingest.api と許可リストの標準ライブラリ {sorted(ALLOWED_STDLIB)} だけ）")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                bad(node, "相対 import は許可されない")
                continue
            mod = node.module or ""
            if mod == "ingest" and all(a.name == "api" for a in node.names):
                continue
            if not _module_allowed(mod):
                bad(node, f"`from {mod} import …` は許可されない（ingest.api と許可リストの標準ライブラリだけ）")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            bad(node, f"`{node.id}` は許可されない（入力は ctx.input_rows() だけ。リフレクション・動的 import・ファイルアクセスは使わない）")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_NAMES:
                bad(node, f"属性 `.{node.attr}` は許可されない")
            elif node.attr.startswith("_"):
                bad(node, f"先頭が `_` の属性 `.{node.attr}`（リフレクション）は許可されない")
    return problems


def check_adapters_dir(adapters_dir) -> list[str]:
    problems: list[str] = []
    for p in sorted(pathlib.Path(adapters_dir).glob("*.py")):
        if p.name == "__init__.py":
            continue
        problems += adapter_import_problems(p)
    return problems
