#!/bin/sh
# 語彙レジストリ（../data/db/registry.sqlite）が無ければ作る。
# build:derived / docker-entrypoint.sh と同じ「まだ無いものだけ作る」流儀
# （340万行のシードや原本の再読み込みを毎回やり直さないため）。
#
# db:setup の predb:setup フックと docker-entrypoint.sh の両方から呼ぶ。
# 「無ければ作る」の判定はここ 1 箇所だけに書き、二重に持たない。
#
# web/package.json の scripts、docker-entrypoint.sh（cd /app/web 済み）の
# どちらから呼ばれてもカレントディレクトリは web/。
set -e

REPO_ROOT="$(cd .. && pwd)"
DB_DIR="${RYUIKI_DB_DIR:-$REPO_ROOT/data/db}"

if [ -f "$DB_DIR/registry.sqlite" ]; then
  echo "✔ 語彙レジストリあり"
else
  echo "▶ 語彙レジストリが無いので作る (build:registry)"
  npm run build:registry
fi
