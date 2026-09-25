"""`scripts/b00_run_full_gate.py` のうち、原本や実行時間を必要としない部分
（パイプラインのパス集合の計算・git 由来のヘルパ）だけを検証する。実際に
パイプライン全体を回す統合テストは原本が要るためここには無い（手元で
`.venv/bin/python3 scripts/b00_run_full_gate.py` を実行して確認する。
受け入れ基準4）。

## 漏れを機械で検出する（code-review 指摘対応）

`PIPELINE_EXPLICIT_FILES`/`PIPELINE_DIRS`/`PIPELINE_FILE_GLOBS` は手で書いた
宣言であり、`scripts/taxon_namespaces.py`（b06・registry/build_taxon.py が
import）・`scripts/schema_registry.sql`（registry/common.py が読む）・
`web/scripts/lib/csv.mjs`（build-geo.mjs が import）の3件を実際に取りこぼして
いた（レビュー指摘・実測で確認済み）。3件を足すだけでは同種の漏れが将来また
起きるため、ここでは**実際にコードを読んで**パイプラインが依存するファイルを
機械的に洗い出し、`collect_pipeline_paths()` の範囲と突き合わせる:

1. **Python の import**（`python_import_closure`）: パイプラインの入口
   （r01・b03〜b12、b00 自身、および b00 がサブプロセスで呼ぶ
   b02_run_all_gates）から、ローカルの import 文を AST で再帰的にたどる。
   b00 自身を入口に含めるのは、この回で b00 が s05 を import するように
   なった（D1）のと同種の漏れ——「b00 が新しく import したファイルを
   PIPELINE_EXPLICIT_FILES に足し忘れる」——を機械的に検出するため。
2. **JS の import**（`js_import_closure`）: v1 の3本（build-derived・
   build-biota・build-geo）から、相対パスの import を正規表現で再帰的にたどる。
3. **文字列リテラルで読むファイル**（`find_literal_filename_references`）:
   import ではなく `ROOT / "scripts" / "schema_registry.sql"` のような
   パス結合で読む `.sql`/`.yaml`/`.csv`/`.json` 等を、パス結合の最後の
   ファイル名部分（裸の文字列リテラル）で拾い、`git ls-files` で実体を
   引き当てる。**完全な経路解決はしない**（最後のファイル名だけを見る、
   `data/processed` の入力ファイルは `pipeline_inputs.SOURCE_FILE_KEYS`
   で除外する）が、`schema_registry.sql` の漏れはこれで捕まる。

3つとも、対象のファイルを集合から除くと検出できる（自己検証のテストを
併記した——`test_*_mutation_*_would_be_caught`）。
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import b00_run_full_gate as b00  # noqa: E402
import pipeline_inputs  # noqa: E402


def test_collect_pipeline_paths_includes_known_files():
    paths = b00.collect_pipeline_paths()
    assert "scripts/b03_build_observation.py" in paths
    assert "scripts/b10_project_documents_v1.py" in paths
    assert "scripts/r01_build_registry.py" in paths
    assert "scripts/registry" in paths
    assert "scripts/migrate" in paths
    assert "scripts/reconcile" in paths
    assert "registry" in paths
    assert "reports/derived_baseline.json" in paths
    assert "web/scripts/build-derived.mjs" in paths
    assert "web/scripts/build-geo.mjs" in paths
    assert "web/scripts/build-biota.mjs" in paths
    assert "requirements.txt" in paths
    assert "web/package.json" in paths
    assert "web/pnpm-lock.yaml" in paths
    # b00 自身も scripts/b0*.py にマッチする（自己参照。b00 が変わっても
    # 証明が無効になるべきなので、これは意図的）。
    assert "scripts/b00_run_full_gate.py" in paths


def test_collect_pipeline_paths_excludes_tests_and_docs():
    paths = b00.collect_pipeline_paths()
    assert not any(p.startswith("scripts/tests/") for p in paths)
    assert not any(p.startswith("docs/") for p in paths)
    assert not any(p.startswith("web/src/") for p in paths)
    assert not any(p.startswith("data/sample/") for p in paths)


def test_collect_pipeline_paths_is_sorted_and_deduplicated():
    paths = b00.collect_pipeline_paths()
    assert paths == sorted(set(paths))


def test_collect_pipeline_paths_is_deterministic():
    assert b00.collect_pipeline_paths() == b00.collect_pipeline_paths()


# ---------------------------------------------------------------------------
# Python: パイプラインの入口から import を AST で再帰的にたどる
# ---------------------------------------------------------------------------

PYTHON_ENTRY_POINTS: tuple[str, ...] = tuple(b00.PIPELINE_STEPS) + (
    "scripts/b02_run_all_gates.py",
    "scripts/b00_run_full_gate.py",
)


def _resolve_python_module_path(parts: list[str]) -> pathlib.Path | None:
    """`parts`（`["reconcile", "common"]` のような import 名の分解）を
    `scripts/` 配下のファイルパスに解決する。見つからなければ None
    （標準ライブラリ・サードパーティの import なので無視してよい）。
    """
    if not parts:
        return None
    scripts_dir = ROOT / "scripts"
    candidate = scripts_dir.joinpath(*parts).with_suffix(".py")
    if candidate.is_file():
        return candidate
    candidate_pkg = scripts_dir.joinpath(*parts) / "__init__.py"
    if candidate_pkg.is_file():
        return candidate_pkg
    return None


def _find_local_python_imports(py_file: pathlib.Path) -> set[pathlib.Path]:
    """`py_file` の `import`/`from ... import ...` 文（絶対・相対どちらも）から、
    `scripts/` 配下のローカルファイルを解決する。
    """
    found: set[pathlib.Path] = set()
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    try:
        rel = py_file.relative_to(ROOT / "scripts")
        own_package_parts = list(rel.parts[:-1])
    except ValueError:
        own_package_parts = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                p = _resolve_python_module_path(alias.name.split("."))
                if p:
                    found.add(p)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # `from . import x` / `from .. import x`（相対 import）。
                base_parts = (
                    own_package_parts[: len(own_package_parts) - (node.level - 1)]
                    if node.level > 1
                    else list(own_package_parts)
                )
                if node.module:
                    base_parts = base_parts + node.module.split(".")
            else:
                if node.module is None:
                    continue
                base_parts = node.module.split(".")
            p_pkg = _resolve_python_module_path(base_parts)
            if p_pkg:
                found.add(p_pkg)
            for alias in node.names:
                # `from reconcile import common, datasource` は common/datasource
                # というサブモジュールを import する（reconcile/__init__.py が
                # 再輸出しているとは限らない——このコードベースの実際の流儀）。
                p_sub = _resolve_python_module_path(base_parts + [alias.name])
                if p_sub:
                    found.add(p_sub)
    return found


def python_import_closure(entry_points: tuple[str, ...]) -> set[pathlib.Path]:
    visited: set[pathlib.Path] = set()
    queue = [ROOT / ep for ep in entry_points]
    while queue:
        f = queue.pop()
        if f in visited:
            continue
        visited.add(f)
        for dep in _find_local_python_imports(f):
            if dep not in visited:
                queue.append(dep)
    return visited


def _is_covered(rel_path: str, pipeline_paths: set[str], pipeline_dirs: tuple[str, ...]) -> bool:
    if rel_path in pipeline_paths:
        return True
    return any(rel_path == d or rel_path.startswith(d + "/") for d in pipeline_dirs)


def test_python_import_closure_is_covered_by_pipeline_paths():
    closure = python_import_closure(PYTHON_ENTRY_POINTS)
    pipeline_paths = set(b00.collect_pipeline_paths())
    uncovered = sorted(
        str(p.relative_to(ROOT))
        for p in closure
        if not _is_covered(str(p.relative_to(ROOT)), pipeline_paths, b00.PIPELINE_DIRS)
    )
    assert not uncovered, f"import を辿った先が証明の対象パスに入っていない: {uncovered}"


def test_python_import_closure_mutation_taxon_namespaces_would_be_caught():
    """`scripts/taxon_namespaces.py` を対象パスの集合から外すと、このテストの
    ロジックが実際に検出できることの自己検証（レビュー指摘の再発防止）。
    """
    closure = python_import_closure(PYTHON_ENTRY_POINTS)
    pipeline_paths = set(b00.collect_pipeline_paths()) - {"scripts/taxon_namespaces.py"}
    uncovered = {
        str(p.relative_to(ROOT))
        for p in closure
        if not _is_covered(str(p.relative_to(ROOT)), pipeline_paths, b00.PIPELINE_DIRS)
    }
    assert "scripts/taxon_namespaces.py" in uncovered


# ---------------------------------------------------------------------------
# JS: v1 の3本から相対 import を正規表現で再帰的にたどる
# ---------------------------------------------------------------------------

JS_ENTRY_POINTS: tuple[str, ...] = (
    "web/scripts/build-derived.mjs",
    "web/scripts/build-biota.mjs",
    "web/scripts/build-geo.mjs",
)

_JS_IMPORT_RE = re.compile(r"""import\s+(?:[^'"]+?\s+from\s+)?["']([^'"]+)["']""")


def _find_local_js_imports(js_file: pathlib.Path) -> set[pathlib.Path]:
    found: set[pathlib.Path] = set()
    text = js_file.read_text(encoding="utf-8")
    for m in _JS_IMPORT_RE.finditer(text):
        spec = m.group(1)
        if spec.startswith("."):
            resolved = (js_file.parent / spec).resolve()
            if resolved.is_file():
                found.add(resolved)
    return found


def js_import_closure(entry_points: tuple[str, ...]) -> set[pathlib.Path]:
    visited: set[pathlib.Path] = set()
    queue = [ROOT / ep for ep in entry_points]
    while queue:
        f = queue.pop()
        if f in visited:
            continue
        visited.add(f)
        for dep in _find_local_js_imports(f):
            if dep not in visited:
                queue.append(dep)
    return visited


def test_js_import_closure_is_covered_by_pipeline_paths():
    closure = js_import_closure(JS_ENTRY_POINTS)
    pipeline_paths = set(b00.collect_pipeline_paths())
    uncovered = sorted(
        str(p.relative_to(ROOT))
        for p in closure
        if not _is_covered(str(p.relative_to(ROOT)), pipeline_paths, b00.PIPELINE_DIRS)
    )
    assert not uncovered, f"相対 import を辿った先が証明の対象パスに入っていない: {uncovered}"


def test_js_import_closure_mutation_csv_mjs_would_be_caught():
    closure = js_import_closure(JS_ENTRY_POINTS)
    pipeline_paths = set(b00.collect_pipeline_paths()) - {"web/scripts/lib/csv.mjs"}
    uncovered = {
        str(p.relative_to(ROOT))
        for p in closure
        if not _is_covered(str(p.relative_to(ROOT)), pipeline_paths, b00.PIPELINE_DIRS)
    }
    assert "web/scripts/lib/csv.mjs" in uncovered


# ---------------------------------------------------------------------------
# 文字列リテラルでパス結合して読むファイル（import ではないもの）
# ---------------------------------------------------------------------------

_FILENAME_LITERAL_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(sql|ya?ml|csv|json|geojson|jsonl)$")


def find_literal_filename_references(py_files: set[pathlib.Path]) -> set[str]:
    """`py_files` の AST から、既知の拡張子を持つ「裸のファイル名」文字列
    リテラル（`ROOT / "scripts" / "schema_registry.sql"` のようなパス結合の
    最後の要素）を拾う。完全な経路解決はしない——モジュール docstring 参照。
    """
    literals: set[str] = set()
    for f in py_files:
        if f.suffix != ".py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _FILENAME_LITERAL_RE.match(node.value):
                    literals.add(node.value)
    return literals


def _tracked_files_by_basename() -> dict[str, list[str]]:
    result = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, check=True)
    by_basename: dict[str, list[str]] = {}
    for f in result.stdout.splitlines():
        by_basename.setdefault(pathlib.Path(f).name, []).append(f)
    return by_basename


def _known_data_input_basenames() -> set[str]:
    """`data/processed/*` の入力ファイルは、原本と同じく `pipeline_inputs.
    SOURCE_FILE_KEYS`（sha256 で別トラック済み）で除外する——git 管理下にも
    無い（.gitignore 済み）ため、ここでの「証明の対象パスか」の対象にしない。
    """
    return {key.rsplit("/", 1)[-1] for key in pipeline_inputs.SOURCE_FILE_KEYS if key.startswith("data/processed/")}


# `data/sample/` は `scripts/s01_build_sample.py` が書く CI サンプル固定物の
# 置き場で、`reports/derived_baseline.json` などパイプライン本体と同じ
# ファイル名（例: `derived_baseline.json`・`derived_keys.yaml`）を持つものが
# ある。この2つは中身も由来も別物（前者は縮小サンプル向けに s01/s03 が作る
# 出力、後者は原本を読む b01/reconcile が使う正）で、パイプライン本体の
# エントリポイント（`PYTHON_ENTRY_POINTS`）はどれも `data/sample/` 配下を
# 一切読まない。ここでの検出はファイル名だけを見る近似（モジュール docstring
# 参照）なので、実測でこの basename 衝突を確認した2件に限って除外する。
_KNOWN_NON_PIPELINE_PATH_PREFIXES = ("data/sample/",)

# `reports/full_gate_proof.json`（`b00.DEFAULT_OUT`）は b00 自身が**書く**出力
# ファイルの名前で、パイプラインの入力・コードではない（b00 を
# `PYTHON_ENTRY_POINTS` に加えた〔D1〕ことで初めて拾われるようになった
# リテラル）。証明の自己参照になるだけで、対象パスに要求する意味が無いため
# 除外する。
_KNOWN_OUTPUT_ONLY_BASENAMES = frozenset({"full_gate_proof.json"})


def _uncovered_literal_references(exclude_from_pipeline_paths: frozenset[str] = frozenset()) -> list[str]:
    all_py_files = python_import_closure(PYTHON_ENTRY_POINTS) | {ROOT / ep for ep in PYTHON_ENTRY_POINTS}
    literal_filenames = find_literal_filename_references(all_py_files)
    known_data_inputs = _known_data_input_basenames()
    by_basename = _tracked_files_by_basename()
    pipeline_paths = set(b00.collect_pipeline_paths()) - exclude_from_pipeline_paths

    problems: list[str] = []
    for filename in sorted(literal_filenames):
        if filename in known_data_inputs or filename in _KNOWN_OUTPUT_ONLY_BASENAMES:
            continue
        matches = by_basename.get(filename, [])
        if not matches:
            problems.append(f"{filename}: git管理下に見つからない（想定外のリテラル）")
            continue
        for m in matches:
            if m.startswith(_KNOWN_NON_PIPELINE_PATH_PREFIXES):
                continue
            if not _is_covered(m, pipeline_paths, b00.PIPELINE_DIRS):
                problems.append(f"{filename}: {m}")
    return problems


def test_literal_file_references_are_covered_or_known_data_inputs():
    problems = _uncovered_literal_references()
    assert not problems, "パイプラインが参照しているのに証明の対象パスに入っていないファイル:\n" + "\n".join(
        problems
    )


def test_literal_file_references_mutation_schema_registry_sql_would_be_caught():
    all_py_files = python_import_closure(PYTHON_ENTRY_POINTS) | {ROOT / ep for ep in PYTHON_ENTRY_POINTS}
    literal_filenames = find_literal_filename_references(all_py_files)
    assert "schema_registry.sql" in literal_filenames, (
        "このテスト自体が scripts/registry/common.py の schema_registry.sql 参照を"
        "拾えていない（検出ロジックが壊れている）"
    )
    problems = _uncovered_literal_references(exclude_from_pipeline_paths=frozenset({"scripts/schema_registry.sql"}))
    assert any("schema_registry.sql" in p for p in problems)
