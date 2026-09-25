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
# ただし判定の中身は違う。scripts/r01_build_registry.py には原本の指紋を直接比較する
# `--check-fresh` があるが、v2 パイプライン（b03/b04/b06/b07/b09）にはまだ同等の
# ものが無い（各段が書く pipeline_fingerprint は「自分の出力が自分の記録と一致するか」
# という自己整合性の検査であり、「原本やスクリプト自体から見て古いか」の判定ではない
# ——scripts/migrate/common.py の assert_stage_fingerprint_fresh 参照）。ここでは
# mtime による最小の判定にとどめる: v2.sqlite が、読み取る原本・入力・スクリプトの
# どれよりも新しければ「新鮮」とみなす。内容そのものの正しさは、b03〜b09 が実行の
# たびに自分で検証する（段階間の指紋・機械検証。CLAUDE.md 参照）ので、ここでの
# 役目は「無駄に毎回作り直さない」ことに限る。
#
# web/package.json の scripts、docker-entrypoint.sh（cd /app/web 済み）の
# どちらから呼ばれてもカレントディレクトリは web/。
set -e

REPO_ROOT="$(cd .. && pwd)"
DB_DIR="${RYUIKI_DB_DIR:-$REPO_ROOT/data/db}"
V2_FILE="$DB_DIR/v2.sqlite"

# v2.sqlite が読み取る原本・入力・パイプラインのコード（b03/b04/b06/b07/b09 と、
# それらが import する scripts/migrate/ 一式）。registry.sqlite も入力に含める
# （b03/b06/b09 は registry.sqlite を ATTACH/読み取りする——ensure-registry.sh が
# 別途これを新鮮に保つ）。scripts/registry/ は含めない（registry.sqlite 自身の
# 入力であって v2 の直接の入力ではない）。
V2_INPUTS="
$DB_DIR/ryuiki.sqlite
$DB_DIR/cells.sqlite
$DB_DIR/registry.sqlite
$REPO_ROOT/data/processed/nlni_w12_watersheds.geojson
$REPO_ROOT/data/processed/nlni_l03b_landuse_by_watershed.csv
$REPO_ROOT/scripts/b03_build_observation.py
$REPO_ROOT/scripts/b04_build_cube.py
$REPO_ROOT/scripts/b06_build_occurrence.py
$REPO_ROOT/scripts/b07_build_occurrence_cube.py
$REPO_ROOT/scripts/b09_build_occurrence_place.py
$REPO_ROOT/scripts/migrate
"

stale=0
if [ ! -f "$V2_FILE" ]; then
  stale=1
else
  for p in $V2_INPUTS; do
    if [ -e "$p" ] && [ -n "$(find "$p" -newer "$V2_FILE" 2>/dev/null)" ]; then
      stale=1
      break
    fi
  done
fi

if [ "$stale" -eq 1 ]; then
  echo "▶ v2.sqlite が古い（または無い）ので作り直す (build:v2)"
  npm run build:v2
else
  echo "✔ v2.sqlite は新鮮"
fi
