#!/bin/sh
# scripts/r01_build_registry.py / scripts/r02_resolution_report.py を呼ぶための
# 薄いラッパ。「.venv/bin/python3 を直書き」をやめ、環境ごとに Python 実行系を
# 差し替えられるようにする（レビュー指摘 A-4）。
#
# 解決順位:
#   1. $RYUIKI_PYTHON 環境変数（明示指定。CI 等で使う）
#   2. リポジトリ直下の .venv（ホットのローカル開発。あれば最優先で使う）
#   3. システムの python3（コンテナ用。PyYAML は web/Dockerfile が
#      apt の python3-yaml として入れている）
#
# web/package.json の scripts から呼ばれる前提でカレントディレクトリは web/。
# 引数はリポジトリ直下からの相対パスで渡す（例: scripts/r01_build_registry.py）。
set -e

cd ..

if [ -n "$RYUIKI_PYTHON" ]; then
  PY="$RYUIKI_PYTHON"
elif [ -x .venv/bin/python3 ]; then
  PY=.venv/bin/python3
else
  PY=python3
fi

exec "$PY" "$@"
