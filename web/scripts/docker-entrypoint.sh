#!/bin/sh
# コンテナ起動時に、必要な分だけ用意してから dev サーバを立てる。
# 集計DB・マイグレーションは「無ければやる」。語彙レジストリと v2（キューブ）は
# 「古ければ作り直す」（判定はそれぞれ scripts/ensure-registry.sh・scripts/ensure-v2.sh。
# 判定は1箇所だけに書き、predb:setup フックとここの両方から同じスクリプトを呼ぶ）。
# いずれも 2 回目以降の `docker compose up` は該当ステップを素通りする。
set -e

cd /app/web

DB_DIR="${RYUIKI_DB_DIR:-/app/data/db}"

echo "▶ 原本の確認: $DB_DIR"
for f in ryuiki.sqlite cells.sqlite; do
  if [ ! -f "$DB_DIR/$f" ]; then
    echo "✗ $DB_DIR/$f が無い。ホストの data/db/ をマウントしているか確認する。" >&2
    exit 1
  fi
done

# 1. 集計 DB。原本から再生成できるものなので、無ければ作る（初回のみ・約1分）
if [ ! -f "$DB_DIR/derived.sqlite" ]; then
  echo "▶ 集計 DB が無いので作る (build:derived)"
  pnpm run build:derived
else
  echo "✔ 集計 DB あり"
fi

# 1.5. 語彙レジストリ。ryuiki/cells を読み取り専用で読んで作る（derived は読まない。
# 経緯は registry/README.md 参照。scripts/r01_build_registry.py）
# 「指紋が古ければ作り直す」判定は db:setup の predb:setup フックと共通（scripts/ensure-registry.sh）
scripts/ensure-registry.sh

# 1.6. v2（observation_agg/occurrence_agg のキューブ。Issue #48 PR-0）。
# 「古ければ作り直す」判定は db:setup の predb:setup フックと共通（scripts/ensure-v2.sh）
scripts/ensure-v2.sh

# 2. マイグレーション。適用済みのものは wrangler が d1_migrations を見て飛ばす
echo "▶ D1 マイグレーション"
pnpm run db:migrate

# 3. シード。原本のフィンガープリントが一致していればスクリプト側で飛ばす
echo "▶ D1 シード"
pnpm run db:seed

echo "▶ dev サーバ起動"
exec pnpm run dev
