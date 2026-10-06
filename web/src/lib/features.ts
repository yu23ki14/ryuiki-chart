/**
 * 画面と API の出し分け。
 *
 * データ探索（`/explore`, `/api/sql`, `/api/table`, `/api/schema`）は、任意の SELECT と
 * 全テーブル走査を認証なしで受け付ける。公開している URL では D1 の rows_read がそのまま
 * 課金に乗るので、デモを人に見せている間は閉じておく。
 * `/api/schema` はテーブル一覧の行数のために 61 テーブルへ count(*) を投げるため、
 * 1 リクエストで 419 万行読む。ここが一番重い。
 *
 * 戻すときはここを true にするだけでよい。画面・ナビ・概況のカード・API・
 * AI の出典リンク（SQL を入れた状態で /explore を開くリンク）が揃って戻る。
 *
 * なお AI アシスタントの `run_sql` ツール（`src/lib/ai/tools.ts`）はこのフラグでは止まらない。
 * あちらはモデルが意図ツールで答えられないときの第2層で、止めるかどうかは別の判断になる
 * （フラグでは止まらないが、`runUserSql` の `catalogOnly` でカタログ外の表は読めない）。
 *
 * v1 の表は DROP 済み（PR-5）。`EXPLORE_ENABLED` を戻すかは別の判断で、任意 SQL と全表スキャンが
 * 公開 URL に出る問題は残る（PR-5 の範囲外）。
 */
export const EXPLORE_ENABLED = false;

/** 閉じているときに API と画面で出す文言。 */
export const EXPLORE_DISABLED_MESSAGE =
  "データ探索は現在ご利用いただけません。";

/**
 * MCP サーバ（`/api/mcp`、ADR-0014 の第1段 5 ツール）の出し分け。本番公開済み（認証なし）。
 *
 * false にすると route が 404 を返す（`EXPLORE_ENABLED` と同じ流儀。環境変数ではなくこの1ファイルで切り替える。
 * 画面ごとに条件を散らさない）。閉じられることは `route.test.ts` で固定している。
 *
 * MCP は任意 SQL・全表走査を出さない（`EXPLORE_ENABLED` とは独立に成立する。ツール一覧は
 * `src/lib/mcp/tools.test.ts` のスナップショットで固定）。負荷上限: バッチ16件・本文64KB・各ツールの出力 limit 最大500行
 * （出力の上限。問い合わせの読み取り量の上限ではない）・IP ごとのレート制限（下記）。
 */
export const MCP_ENABLED = true;

/**
 * `/api/mcp` のレート制限（Cloudflare Rate Limiting バインディング `MCP_RATE_LIMITER`）。
 * `wrangler.jsonc` の `ratelimits[].simple`（limit / period）と同じ値にする（バインディング側が実際の制限を持つ。
 * period は 10 か 60 秒のみ）。キーはクライアント IP（`cf-connecting-ip`）。
 */
export const MCP_RATE_LIMIT = { limit: 60, periodSeconds: 60 } as const;

/** `/api/mcp` が受ける Origin のホスト名（Origin ヘッダがあるときだけ検査。無ければ通す＝CLI/デスクトップのクライアント）。 */
export const MCP_ALLOWED_ORIGIN_HOSTS = ["ryuiki-demo.tokyo-odh-009.workers.dev", "localhost", "127.0.0.1", "[::1]"] as const;
