"""adapter の import 境界（AST）と、新ソース追加の境界検査 CLI（Issue #40 Phase D・J6）。

恒久テスト: `scripts/adapters/*.py` は `ingest.api` と標準ライブラリだけを import する（受け入れ基準 1 の再発防止）。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

import check_source_add_boundary as boundary_cli
from ingest import boundary

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "check_source_add_boundary.py"


def test_real_adapters_import_only_ingest_api_and_stdlib():
    assert boundary.check_adapters_dir(ROOT / "scripts" / "adapters") == []


def _problems(tmp_path, source: str) -> list[str]:
    p = tmp_path / "a.py"
    p.write_text(source, encoding="utf-8")
    return boundary.adapter_import_problems(p)


@pytest.mark.parametrize(
    "source",
    [
        "import migrate\n",
        "from migrate import common\n",
        "from migrate.common import MigrationError\n",
        "import sqlite3\n",
        "from registry import common\n",
        "import yaml\n",
        "import importlib\n",
        "from . import sibling\n",
        "from ingest import runner\n",
        "from ingest.runner import AdapterRun\n",
        "import ingest.manifest\n",
        "x = __import__('sqlite3')\n",
        "x = open('/etc/passwd')\n",
        "eval('1')\n",
        "import os, sqlite3\n",
        # 許可リスト方式: 禁止リストに無い標準ライブラリ・サードパーティも止まる
        "import os\n",
        "from pathlib import Path\n",
        "import io\n",
        "import shutil\n",
        "import csv\n",
        "import requests\n",
        "import builtins\n",
        # 属性・リフレクション経由の迂回
        "import datetime\nx = datetime.__builtins__\n",
        "x = __builtins__\n",
        "x = getattr(__builtins__, 'open')\n",
        "x = ().__class__.__bases__[0].__subclasses__()\n",
        "import json\nx = json.__dict__\n",
        "f = open\n",
        "import re\nx = re.__loader__\n",
        "x = vars()\n",
        "x = globals()\n",
    ],
)
def test_forbidden_imports_and_dynamic_escapes_are_caught(tmp_path, source):
    assert _problems(tmp_path, source), source


@pytest.mark.parametrize(
    "source",
    [
        "from ingest.api import occurrence_row\n",
        "import ingest.api\n",
        "from ingest import api\n",
        "from __future__ import annotations\nimport re, json, datetime, math\nfrom decimal import Decimal\nfrom ingest.api import occurrence_row\n",
        "import datetime\nd = datetime.date.fromisoformat('2020-01-01')\nx = re.compile('a')\n".replace("x = re.compile('a')\n", ""),
    ],
)
def test_allowed_imports_pass(tmp_path, source):
    assert _problems(tmp_path, source) == []


# ---- check_source_add_boundary.py -------------------------------------------------------------

def test_files_inside_the_allow_list_pass():
    files = ["manifests/x.yml", "scripts/adapters/x.py", "registry/source/editions.yaml", "scripts/tests/test_x.py",
             "data/sample/serving_snapshot.json"]
    assert boundary_cli.violations(files) == []


@pytest.mark.parametrize(
    "path",
    ["scripts/migrate/common.py", "scripts/b06_build_occurrence.py", "scripts/b09_build_occurrence_place.py",
     "scripts/registry/build_source.py", "scripts/ingest/runner.py", "scripts/migrate/occurrence_cube_declarations.yaml",
     "web/src/lib/db.ts", "scripts/taxon_namespaces.py"],
)
def test_library_side_paths_are_rejected(path):
    assert boundary_cli.violations(["manifests/x.yml", path]) == [path]


def test_cli_exit_codes(tmp_path):
    ok = subprocess.run([sys.executable, str(CLI), "--files", "manifests/x.yml", "scripts/tests/t.py"],
                        capture_output=True, text=True)
    assert ok.returncode == 0 and "OK" in ok.stdout
    bad = subprocess.run([sys.executable, str(CLI), "--files", "manifests/x.yml", "scripts/migrate/common.py"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "scripts/migrate/common.py" in bad.stdout


def test_cli_also_checks_adapter_imports_of_changed_adapters(tmp_path, monkeypatch):
    adapters = tmp_path / "scripts" / "adapters"
    adapters.mkdir(parents=True)
    (adapters / "x.py").write_text("from migrate import common\n", encoding="utf-8")
    assert boundary_cli.adapter_problems(["scripts/adapters/x.py"], root=tmp_path)
    (adapters / "x.py").write_text("from ingest.api import occurrence_row\n", encoding="utf-8")
    assert boundary_cli.adapter_problems(["scripts/adapters/x.py"], root=tmp_path) == []
