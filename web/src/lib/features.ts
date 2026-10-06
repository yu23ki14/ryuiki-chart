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
