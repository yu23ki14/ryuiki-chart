# 流域カルテ デモ — 開発用イメージ
#
# Cloudflare Workers + D1 を想定しているので、ローカルでも wrangler / miniflare が
# 動く土台（workerd が要求する libc++）を入れておく。
# 本番デプロイは `pnpm run deploy`（@opennextjs/cloudflare）で、このイメージは使わない。

FROM node:22-bookworm-slim AS development

# workerd は libc++ を要求する。better-sqlite3 はプリビルドが無い場合にビルドする。
RUN apt-get update && apt-get install -y --no-install-recommends \
      libc++1 \
      ca-certificates \
      python3 \
      make \
      g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/web

# 依存だけ先に入れてレイヤをキャッシュする
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# ホストの UID/GID 1000 と揃える。data/ はバインドマウントなので、
# コンテナが書く derived.sqlite がホスト側で root 所有にならないようにする。
# 名前付きボリュームは作成時にこのディレクトリの所有者を引き継ぐ。
RUN mkdir -p /app/web/.wrangler /app/web/.next /app/data \
    && chown -R node:node /app
USER node

# 原本 SQLite と GeoJSON は /app/data にマウントする（compose 側）。
# スクリプトは web/ から見て ../data を読む。
ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1 \
    WRANGLER_SEND_METRICS=false \
    CI=true

EXPOSE 3000

ENTRYPOINT ["/app/web/scripts/docker-entrypoint.sh"]
