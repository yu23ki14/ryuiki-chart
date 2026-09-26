# 流域カルテ デモ — 開発用イメージ
#
# Cloudflare Workers + D1 を想定しているので、ローカルでも wrangler / miniflare が
# 動く土台（workerd が要求する libc++）を入れておく。
# 本番デプロイは `pnpm run deploy`（@opennextjs/cloudflare）で、このイメージは使わない。

# base は node:22-trixie-slim（Debian 13）。bookworm（Debian 12）は Python 3.11 に
# SQLite 3.40.1 が同梱されており、Issue #48 で追加した v2 パイプライン
# （scripts/b04_build_cube.py・scripts/b07_build_occurrence_cube.py 等）が
# `scripts/migrate/common.py` の `require_sqlite_version()`（3.43 未満で SystemExit。
# AVG()/SUM() の加算アルゴリズムが3.43で変わる・FULL OUTER JOIN が3.39未満で使えない）
# に引っかかって止まる（実測: bookwormのpython3-yamlはPython 3.11/SQLite 3.40.1）。
# trixie は Python 3.13 に SQLite 3.46.1 が同梱されており、これを満たす（実測）。
FROM node:22-trixie-slim AS development

# workerd は libc++ を要求する。better-sqlite3 はプリビルドが無い場合にビルドする。
# python3-yaml はレジストリ・v2 パイプライン（scripts/r01_build_registry.py・
# scripts/b0*.py が import する PyYAML）用。リポジトリ直下の requirements.txt は
# `web/` の外（この Dockerfile のビルドコンテキストは ./web）なので pip では入れず、
# Debian の配布パッケージで賄う。PyYAML のバージョンは requirements.txt の固定値
# （6.0.3、ホストの .venv 用）とは厳密には一致しない（trixie は 6.0.2）が、
# ビルドスクリプト側は yaml.safe_load しか使わないので互換上の問題はない。
# COPY の手前（依存レイヤ）に置いてキャッシュを保つ。
RUN apt-get update && apt-get install -y --no-install-recommends \
      libc++1 \
      ca-certificates \
      python3 \
      python3-yaml \
      make \
      g++ \
    && rm -rf /var/lib/apt/lists/*

# Issue #48「見落としそうな危険」3: base イメージの更新で SQLite が入れ替わっても
# 気づけるよう、ビルド時に実際の版を検査してビルド自体を落とす
# （scripts/migrate/common.py の MIN_SQLITE_VERSION と同じ閾値。判定はそちらが正
# ——ここはビルドを早期に落とすための重複チェック。sqlite3 CLI ではなく、Python が
# import する sqlite3 モジュール〔標準ライブラリに静的リンクされた版〕を見るのも
# common.require_sqlite_version() と同じ観点）。
RUN python3 -c "import sqlite3; assert sqlite3.sqlite_version_info >= (3, 43, 0), f'sqlite3 (Python同梱、バージョン {sqlite3.sqlite_version}) が古すぎる。SQLite 3.43.0 以降が必要（scripts/migrate/common.py の MIN_SQLITE_VERSION）。base イメージを SQLite 3.43 以降を同梱するものに変えること。'"

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
