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
 * あちらはモデルが意図ツールで答えられないときの第2層で、止めるかどうかは別の判断になる。
 */
export const EXPLORE_ENABLED = false;

/** 閉じているときに API と画面で出す文言。 */
export const EXPLORE_DISABLED_MESSAGE =
  "データ探索は現在ご利用いただけません。";
