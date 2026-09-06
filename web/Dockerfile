# 流域カルテ デモ — 開発用イメージ
#
# Cloudflare Workers + D1 を想定しているので、ローカルでも wrangler / miniflare が
# 動く土台（workerd が要求する libc++）を入れておく。
# 本番デプロイは `pnpm run deploy`（@opennextjs/cloudflare）で、このイメージは使わない。

FROM node:22-bookworm-slim AS development

# workerd は libc++ を要求する。better-sqlite3 はプリビルドが無い場合にビルドする。
# python3-yaml はレジストリビルド（scripts/r01_build_registry.py が import する PyYAML）用。
# リポジトリ直下の requirements.txt は `web/` の外（この Dockerfile のビルドコンテキストは
# ./web）なので pip では入れず、Debian の配布パッケージで賄う。PyYAML のバージョンは
# requirements.txt の固定値（6.0.3、ホストの .venv 用）とは厳密には一致しない
# （bookworm は 6.0-3+b2 = PyYAML 6.0）が、ビルドスクリプト側は yaml.safe_load しか
# 使わないので互換上の問題はない。COPY の手前（依存レイヤ）に置いてキャッシュを保つ。
RUN apt-get update && apt-get install -y --no-install-recommends \
      libc++1 \
      ca-certificates \
      python3 \
      python3-yaml \
      make \
      g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/web

# pnpm を corepack 経由で固定する（web/package.json の packageManager と揃える）
RUN corepack enable && corepack prepare pnpm@10.18.3 --activate

# 依存だけ先に入れてレイヤをキャッシュする
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# ホストの UID/GID 1000 と揃える。data/ はバインドマウントなので、
# コンテナが書く derived.sqlite がホスト側で root 所有にならないようにする。
# 名前付きボリュームは作成時にこのディレクトリの所有者を引き継ぐ。
# /app/scripts と /app/registry も compose 側でバインドマウントする
# （レジストリビルドが読むリポジトリ直下の scripts/ と registry/。read-only マウント）。
RUN mkdir -p /app/web/.wrangler /app/web/.next /app/data /app/scripts /app/registry \
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
