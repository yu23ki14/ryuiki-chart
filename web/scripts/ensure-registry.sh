#!/bin/sh
# 語彙レジストリ（../data/db/registry.sqlite）が「今の入力から作ったもの」でなければ作る。
#
# 以前は「ファイルが在るか」しか見ていなかった（かつての build:derived と同じ「まだ無いものだけ
# 作る」流儀を踏襲した実装）。しかしこれだと、ビルドの論理が変わった後の古いレジストリも、
# r01 が壊れて途中で残した半端なファイルも「在る」の一言で素通りしてしまう
# （phase-b/registry-atomic。`--files-only` が正規のレジストリを154 aliasのスタブで
# 上書きした事故——docs/plans/PHASE_B_INTAKE.md #7 の追記——と同じ根: 「在る」と「正しい」を
# 区別していなかった）。今は `scripts/r01_build_registry.py --check-fresh` の終了コードで
# 判定する（ryuiki/cells は開かない・登録先には何も書かない。指紋が今の入力と一致するか
# だけを見る）。
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
REGISTRY_FILE="$DB_DIR/registry.sqlite"
# 以降の r01_build_registry.py 呼び出し（--check-fresh・npm run build:registry の
# どちらも）は子プロセスなのでこの export を見る。呼び出しごとに書き直さない。
export RYUIKI_REGISTRY_DB="$REGISTRY_FILE"

# 0. 外部ポータルの目録（ryuiki.sqlite の external_dataset / external_resource。find_datasets の元）。
# レジストリのビルド（r01）は access.yaml の catalog 宣言と external_dataset を突き合わせて、目録が空だと止まる。
# だから先に「無い・空のときだけ」m08 で作る（入力は data/processed の ckan_*.jsonl・estat_*.jsonl）。
# 入力も無ければ、m08 が直し方を書いて失敗する（set -e でここで止まる）。原本が無い環境（CI）では何もしない。
# 目録を作り直したときの鮮度は、下の --check-fresh が見る（指紋に出典別の件数が入っている）。
if [ -f "$DB_DIR/ryuiki.sqlite" ]; then
  scripts/run-python.sh scripts/m08_external_catalog.py --db "$DB_DIR/ryuiki.sqlite" --if-empty
fi

# --check-fresh の終了コードは3種類を区別する（r01_build_registry.py の
# EXIT_FRESH=0 / EXIT_STALE=10。それ以外は「判定できない」。fix 1, phase-b/registry-atomic）。
# `if cmd; then` の形にすると set -e に巻き込まれず $? を安全に取れる。
if scripts/run-python.sh scripts/r01_build_registry.py --check-fresh; then
  status=0
else
  status=$?
fi

if [ "$status" -eq 0 ]; then
  echo "✔ 語彙レジストリは新鮮"
elif [ "$status" -eq 10 ]; then
  echo "▶ 語彙レジストリが古いので作り直す (build:registry)"
  npm run build:registry
else
  # 判定できない（EXIT_FRESH=0 / EXIT_STALE=10 以外。理由は r01_build_registry.py の
  # モジュール docstring 参照）。「古い」と誤読しない: レジストリが在るなら警告を出して
  # 今のファイルを使い続け（以前の挙動への退避）、無いなら作る。
  echo "⚠ 語彙レジストリの鮮度を判定できない（終了コード $status）" >&2
  if [ -f "$REGISTRY_FILE" ]; then
    echo "⚠ 既存の $REGISTRY_FILE をそのまま使う（新鮮性は未確認）" >&2
  else
    echo "▶ レジストリが無いので作る (build:registry)" >&2
    npm run build:registry
  fi
fi
