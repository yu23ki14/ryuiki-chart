#!/bin/sh
# v2（../data/db/v2.sqlite。scripts/r01_build_registry.py -> scripts/b03_build_observation.py
# -> scripts/b04_build_cube.py -> scripts/b06_build_occurrence.py ->
# scripts/b09_build_occurrence_place.py -> scripts/b07_build_occurrence_cube.py が作る
# observation_agg/occurrence_agg のキューブ）が「今の入力から作ったもの」でなければ
# 作り直す（build:v2）。
#
# scripts/ensure-registry.sh と同じ役割・同じ流儀（「作り直すか」の判定はここ1箇所
# だけに書き、db:setup の predb:setup フックと docker-entrypoint.sh の両方から呼ぶ）。
#
# 判定は `scripts/check_v2_fresh.py`（`scripts/r01_build_registry.py --check-fresh` と
# 同じ 0=新鮮/10=古い/それ以外=判定不能の終了コード）一本（Issue #48 PR-0 /simplify
# 指摘1）。以前は手書きの `V2_INPUTS` を `find -newer` で mtime 走査する判定も
# OR していたが、手書きの一覧の漏れ・symlink の lstat mtime・「mtime は新しいが
# 中身は古い」を見逃す弱点があったため撤去した。今は check_v2_fresh.py 自身が
# 「読み取り専用の原本・data/processed の入力・registry.sqlite・パイプラインの
# コード」の中身の指紋一本で判定する。設計・実測（大きい原本を毎回ハッシュする
# 代わりに代理指標に倒した理由を含む）は scripts/migrate/common.py の
# 「v2 パイプラインの『入力＋コードの中身』の指紋」節を参照。
#
# (1) の内容そのものの正しさ（値が合っているか）は、b03〜b09 が実行のたびに
# 自分で検証する（段階間の指紋・機械検証。CLAUDE.md 参照）。ここでの役目は
# 「古い可能性があるときに気づいて作り直す」ことに限る。
#
# web/package.json の scripts、docker-entrypoint.sh（cd /app/web 済み）の
# どちらから呼ばれてもカレントディレクトリは web/。
set -e

REPO_ROOT="$(cd .. && pwd)"
DB_DIR="${RYUIKI_DB_DIR:-$REPO_ROOT/data/db}"
V2_FILE="$DB_DIR/v2.sqlite"

# check_v2_fresh.py 自身がファイル不在を EXIT_STALE(10) として扱うので、
# ここで存在チェックを分ける必要はない。`if cmd; then` の形にすると set -e に
# 巻き込まれず $? を安全に取れる（scripts/ensure-registry.sh と同じ流儀）。
if scripts/run-python.sh scripts/check_v2_fresh.py --v2-db "$V2_FILE"; then
  status=0
else
  status=$?
fi

if [ "$status" -eq 0 ]; then
  echo "✔ v2.sqlite は新鮮"
elif [ "$status" -eq 10 ]; then
  echo "▶ v2.sqlite が古い（または無い）ので作り直す (build:v2)"
  npm run build:v2
else
  echo "⚠ v2.sqlite の鮮度を判定できない（scripts/check_v2_fresh.py の終了コード $status）" >&2
  if [ -f "$V2_FILE" ]; then
    echo "⚠ 既存の $V2_FILE をそのまま使う（新鮮性は未確認）" >&2
  else
    echo "▶ v2.sqlite が無いので作る (build:v2)" >&2
    npm run build:v2
  fi
fi
