#!/bin/sh
# 語彙レジストリ（../data/db/registry.sqlite）が「今の入力から作ったもの」でなければ作る。
#
# 以前は「ファイルが在るか」しか見ていなかった（build:derived と同じ「まだ無いものだけ
# 作る」流儀を踏襲した実装）。しかしこれだと、ビルドの論理が変わった後の古いレジストリも、
# r01 が壊れて途中で残した半端なファイルも「在る」の一言で素通りしてしまう
# （phase-b/registry-atomic。`--files-only` が正規のレジストリを154 aliasのスタブで
# 上書きした事故——docs/plans/PHASE_B_INTAKE.md #7 の追記——と同じ根: 「在る」と「正しい」を
# 区別していなかった）。今は `scripts/r01_build_registry.py --check-fresh` の終了コードで
# 判定する（原本DBは開かない・何も書かない。指紋が今の入力と一致するかだけを見る）。
#
# db:setup の predb:setup フックと docker-entrypoint.sh の両方から呼ぶ。
# 「作り直すか」の判定はここ 1 箇所だけに書き、二重に持たない
# （判定ロジック本体は r01_build_registry.py 側にあり、ここは --check-fresh を呼ぶだけ）。
#
# web/package.json の scripts、docker-entrypoint.sh（cd /app/web 済み）の
# どちらから呼ばれてもカレントディレクトリは web/。
set -e

REPO_ROOT="$(cd .. && pwd)"
DB_DIR="${RYUIKI_DB_DIR:-$REPO_ROOT/data/db}"

if RYUIKI_REGISTRY_DB="$DB_DIR/registry.sqlite" scripts/run-python.sh scripts/r01_build_registry.py --check-fresh; then
  echo "✔ 語彙レジストリは新鮮"
else
  echo "▶ 語彙レジストリが古い/無いので作り直す (build:registry)"
  RYUIKI_REGISTRY_DB="$DB_DIR/registry.sqlite" npm run build:registry
fi
