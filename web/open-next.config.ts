import { defineCloudflareConfig } from "@opennextjs/cloudflare";

/**
 * Next.js を Cloudflare Workers 向けにビルドするための設定。
 * `opennextjs-cloudflare build` がこのファイルを読む。
 *
 * incrementalCache は入れていない。この画面は全ページ `dynamic = "force-dynamic"` で
 * ISR も SSG も使っておらず、キャッシュすべき生成物が無いため。
 * 静的生成を使い出したら R2 か KV の incrementalCache を足す。
 * https://opennext.js.org/cloudflare/caching
 */
export default defineCloudflareConfig();
