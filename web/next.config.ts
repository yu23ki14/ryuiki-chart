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
 */
initOpenNextCloudflareForDev();

export default nextConfig;
