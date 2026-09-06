#!/bin/sh
# コンテナ起動時に、必要な分だけ用意してから dev サーバを立てる。
# 3 つとも「まだなら やる」なので、2 回目以降の `docker compose up` は素通りする。
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

# 1.5. 語彙レジストリ。ryuiki/cells/derived を読み取り専用で読んで作る（scripts/r01_build_registry.py）
# 「無ければ作る」の判定は db:setup の predb:setup フックと共通（scripts/ensure-registry.sh）
scripts/ensure-registry.sh

# 2. マイグレーション。適用済みのものは wrangler が d1_migrations を見て飛ばす
echo "▶ D1 マイグレーション"
pnpm run db:migrate

# 3. シード。原本のフィンガープリントが一致していればスクリプト側で飛ばす
echo "▶ D1 シード"
pnpm run db:seed

echo "▶ dev サーバ起動"
exec pnpm run dev
