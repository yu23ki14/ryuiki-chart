import type { NextConfig } from "next";
import { initOpenNextCloudflareForDev } from "@opennextjs/cloudflare";

const nextConfig: NextConfig = {
  // 画面左下の開発用インジケータが地図の凡例に重なるので出さない
  devIndicators: false,
  experimental: {
    // 大きめの集計レスポンスをキャッシュできるように
    largePageDataBytes: 16 * 1024 * 1024,
  },
};

/**
 * `next dev` から Cloudflare のバインディング（D1 の `DB`）を触れるようにする。
 * wrangler.jsonc を読み、miniflare をローカルで立ち上げて
 * `getCloudflareContext()` に env を渡す。dev でのみ効く。
 *
 * `wrangler.jsonc` の Workers AI・Vectorize（広報たつごうのベクトル検索）は `remote: true`（実リソースへ接続）で、
 * 接続には `wrangler login` が要る。未ログインの環境（docker compose・CI）で `next dev` が起動しなくなるので、
 * 既定ではリモートのバインディングを張らない（検索だけ無効になる。src/lib/vector/bindings.ts）。
 * ベクトル検索を手元で試すときだけ `RYUIKI_REMOTE_BINDINGS=1 pnpm run dev`（要 wrangler login）。
 */
initOpenNextCloudflareForDev({ remoteBindings: process.env.RYUIKI_REMOTE_BINDINGS === "1" });

export default nextConfig;
