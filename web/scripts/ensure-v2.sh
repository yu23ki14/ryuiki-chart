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
# 判定は2つの**どちらか**が「古い」と言えば作り直す（OR）:
#
#   (1) mtime: v2.sqlite が、読み取る原本・入力・パイプラインのコードのどれよりも
#       古い。v2 パイプライン（b03/b04/b06/b07/b09）にはまだ
#       scripts/r01_build_registry.py --check-fresh のような「原本の指紋を直接
#       比較する」判定が無いため、その代わりの最小の判定。
#   (2) scripts/check_v2_fresh.py（r01 の --check-fresh と同じ 0=新鮮/10=古い/
#       それ以外=判定不能の終了コード）: observation_agg/occurrence_agg の
#       pipeline_fingerprint.spec_version が今のパイプラインの spec と一致するか。
#       (1) だけでは、**mtime は新しいが中身が古い形式**の v2.sqlite（例: 元の
#       チェックアウトからコピーしてきた、PR #26 より前の13列キーの実物。
#       `cp -p` で mtime を保存してコピーした場合や、単に手元に古い成果物を
#       置いたまま何も入力ファイルを触っていない場合に起こりうる）を「新鮮」と
#       誤判定してしまう——(2) はこれを検出する。(2) が「判定不能」（Python が
#       起動できない等）を返した場合は、(1) の結果だけで決める（r01 の
#       `--check-fresh` が判定不能なら既存ファイルを使い続けるのと同じ寛容さ。
#       `web/scripts/seed-d1-local.mjs` はシード直前に同じ (2) をもう一度
#       呼んでおり、そちらは判定不能も拒否する——安全側に倒す場所が違う）。
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

# v2.sqlite が読み取る原本・入力・パイプラインのコード。b03/b04/b06/b07/b09 の
# 実際の import を、それぞれが読み込む scripts/ 配下のモジュールまで推移的に
# 辿って列挙している（`python3 -c` で各スクリプトを import し、新たに
# sys.modules に載った scripts/ 配下のファイルを機械的に洗い出して確認済み）:
# `from migrate import ...`・`from registry import common as registry_common`・
# `from taxon_namespaces import ...`、そして migrate/common.py が
# `from reconcile.common import load_yaml, open_readonly` で読み、
# reconcile/common.py がさらに `from . import datasource` で読む
# scripts/reconcile/{common,datasource}.py（scripts/migrate/ 配下は YAML 宣言
# 〔source_regions.yaml 等〕も含めてまとめて1行で拾う）。registry.sqlite も
# 入力に含める（b03/b06/b09 が ATTACH/読み取りする——ensure-registry.sh が
# 別途これを新鮮に保つ。scripts/registry/・scripts/reconcile/ 配下を丸ごとは
# 含めない: 実際に import されるのは registry/common.py・reconcile/{common,
# datasource}.py だけで、r01 専用の build_*.py 群や b02 専用の reconcile の
# YAML 宣言〔projection_manifest.yaml 等〕は registry.sqlite・reconcile ゲート
# 自身の入力であって v2 の直接の入力ではない）。cells.sqlite は v2 パイプライン
# のどの段も読まないため含めない。
V2_INPUTS="
$DB_DIR/ryuiki.sqlite
$DB_DIR/registry.sqlite
$REPO_ROOT/data/processed/nlni_w12_watersheds.geojson
$REPO_ROOT/data/processed/nlni_l03b_landuse_by_watershed.csv
$REPO_ROOT/scripts/b03_build_observation.py
$REPO_ROOT/scripts/b04_build_cube.py
$REPO_ROOT/scripts/b06_build_occurrence.py
$REPO_ROOT/scripts/b07_build_occurrence_cube.py
$REPO_ROOT/scripts/b09_build_occurrence_place.py
$REPO_ROOT/scripts/migrate
$REPO_ROOT/scripts/taxon_namespaces.py
$REPO_ROOT/scripts/registry/common.py
$REPO_ROOT/scripts/reconcile/common.py
$REPO_ROOT/scripts/reconcile/datasource.py
"

# 個々のファイルはそのまま `find $p -newer` で見るが、$p がディレクトリ
# （scripts/migrate）のときは `-type f` かつ `__pycache__` 配下を除外する。
# 素朴に `find "$p" -newer "$V2_FILE"` だけだと、ディレクトリを再帰する過程で
# `__pycache__/*.pyc`（.py を import しただけで作られる／更新される）や
# ディレクトリ自身の mtime（配下にファイルが増減すると更新される）まで拾って
# しまい、ソースも入力 YAML も何も変えていないのに「古い」と誤判定して
# build:v2（1.5GB の全量再ビルド）が走る。
mtime_stale=0
if [ ! -f "$V2_FILE" ]; then
  mtime_stale=1
else
  for p in $V2_INPUTS; do
    if [ ! -e "$p" ]; then
      continue
    fi
    if [ -d "$p" ]; then
      newer="$(find "$p" -type f -not -path '*/__pycache__/*' -newer "$V2_FILE" 2>/dev/null)"
    else
      newer="$(find "$p" -newer "$V2_FILE" 2>/dev/null)"
    fi
    if [ -n "$newer" ]; then
      mtime_stale=1
      break
    fi
  done
fi

# scripts/check_v2_fresh.py 自身がファイル不在を EXIT_STALE(10) として扱うので、
# ここで存在チェックを分ける必要はない。
if scripts/run-python.sh scripts/check_v2_fresh.py --v2-db "$V2_FILE"; then
  spec_status=0
else
  spec_status=$?
fi

if [ "$mtime_stale" -eq 1 ] || [ "$spec_status" -eq 10 ]; then
  echo "▶ v2.sqlite が古い（または無い）ので作り直す (build:v2)"
  npm run build:v2
elif [ "$spec_status" -ne 0 ]; then
  echo "⚠ v2.sqlite の spec の鮮度を判定できない（scripts/check_v2_fresh.py の終了コード $spec_status）" >&2
  echo "✔ v2.sqlite は新鮮（mtime 判定のみ。既存のファイルをそのまま使う）"
else
  echo "✔ v2.sqlite は新鮮"
fi
