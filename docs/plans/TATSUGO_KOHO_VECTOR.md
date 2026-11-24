# 「広報たつごう」の記事を内容で探す（ベクトル検索）の設計（Issue #132）

対象は広報誌の記事だけ（2026-11-24 オーナー決定）。仕組みは文書の種類によらない形にし、あとで行政文書にも広げられるようにする。
記事の単位・列・取り下げは `docs/plans/TATSUGO_KOHO.md`（ブランチ `feat/tatsugo-koho`、#130/#131）の §2.3・§3.5・§9 に従う。この文書はそこへ足す部分だけを書く。

状態: 設計のみ。コードも Cloudflare 側の操作も未実施。「確認済み」は公式ドキュメントで読めたこと、
「未確認」は読めなかったか書かれていなかったことで、実装担当が最初に確かめる（§11）。

## 0. 決定の要点

| 項目 | 決定（推奨） |
|---|---|
| ベクトルの置き場 | Cloudflare Vectorize。1 モデル 1 インデックス（名前に model と版を含める）。metric は `cosine` |
| 埋め込みモデル | 第一候補 `@cf/baai/bge-m3`（1024 次元）。評価で `@cf/qwen/qwen3-embedding-0.6b`・`@cf/pfnet/plamo-embedding-1b` と比べて確定（§3） |
| チャンク | 本文 1,000 字以下の記事は 1 記事 1 チャンク（本文のある記事の約 81%）。超えるものは文末（`。`）で区切り、目標 800 字・上限 1,000 字・重なり約 100 字。約 5,700 チャンク（§4） |
| 作る・入れる経路 | Node（`web/scripts/vector/`）。Workers AI と Vectorize の REST を直接叩く。キャッシュは `data/vector/` の SQLite。差分だけ upsert、取り下げは delete（§5） |
| 検索時 | Worker のバインディング（`AI`・`VECTORIZE`）で質問を埋め込み、Vectorize を引き、D1 の `document_articles` と突き合わせる（§6） |
| ローカル開発 | Workers AI・Vectorize にローカルの模擬は無い。無いときは検索だけ無効にして他は動かす（§2） |
| 費用 | Workers Paid なら追加費用はほぼ 0（月 $0.1 未満）。Free プランは保存の上限を超える（§7） |

## 1. 参照した公式ドキュメント（2026-11-24 に読んだもの）

- Vectorize の上限: https://developers.cloudflare.com/vectorize/platform/limits/
- Vectorize の料金: https://developers.cloudflare.com/vectorize/platform/pricing/
- インデックス作成: https://developers.cloudflare.com/vectorize/best-practices/create-indexes/
- 投入: https://developers.cloudflare.com/vectorize/best-practices/insert-vectors/
- 検索: https://developers.cloudflare.com/vectorize/best-practices/query-vectors/
- メタデータの絞り込み: https://developers.cloudflare.com/vectorize/reference/metadata-filtering/
- Worker の API: https://developers.cloudflare.com/vectorize/reference/client-api/
- wrangler のコマンド: https://developers.cloudflare.com/vectorize/reference/wrangler-commands/
- REST（upsert）: https://developers.cloudflare.com/api/resources/vectorize/subresources/indexes/methods/upsert/
- REST（delete_by_ids）: https://developers.cloudflare.com/api/resources/vectorize/subresources/indexes/methods/delete_by_ids/
- Workers AI の料金: https://developers.cloudflare.com/workers-ai/platform/pricing/
- モデル: https://developers.cloudflare.com/workers-ai/models/bge-m3/ ・ `/qwen3-embedding-0.6b/` ・ `/plamo-embedding-1b/` ・ `/embeddinggemma-2/`
- Workers AI REST: https://developers.cloudflare.com/workers-ai/get-started/rest-api/
- Workers AI バインディング: https://developers.cloudflare.com/workers-ai/configuration/bindings/
- ローカル開発とリモートバインディング: https://developers.cloudflare.com/workers/development-testing/
- OpenNext のバインディング: https://opennext.js.org/cloudflare/bindings

## 2. Vectorize とローカル開発

### 2.1 Vectorize の仕様（確認済み）

- インデックスの次元と metric は作成後に変えられない。`npx wrangler vectorize create <名前> --dimensions=N --metric=cosine`（wrangler 3.71.0 以降）。
- 上限: 1 ベクトル最大 1536 次元・ID 64 バイト・メタデータ 10 KiB／1 インデックス 2,000 万ベクトル・メタデータインデックス 10 個（1 プロパティあたりインデックスされるのは 64 バイトまで）／
  upsert 1 回 1,000（Worker）・5,000（HTTP API）／topK は値かメタデータを返すとき 50、返さないとき 100。
- メタデータの絞り込み: `string`・`number`・`boolean` の型。演算子は `$eq` `$ne` `$in` `$nin` `$lt` `$lte` `$gt` `$gte`。
  フィルタは先に適用され、その絞り込み後から topK を取る。フィルタの JSON は 2,048 バイト未満。
  **メタデータインデックスはベクトルを入れる前に作る**（後から作ると、それ以前に入れたベクトルは索引に入らない）。
  作成は `wrangler vectorize create-metadata-index <名前> --property-name=… --type=string|number|boolean`。
- 書き込みは非同期（ログに積まれ、あとで索引に反映される。数分で見えるようになる）。`upsert` は同じ ID を丸ごと置き換え、`insert` は先に入れたものを残す。
- Worker のバインディング: `query(vector, {topK, returnMetadata: 'none'|'indexed'|'all', filter})`・`upsert`・`deleteByIds`・`getByIds`。
  wrangler.jsonc は `"vectorize": [{"binding": "VECTORIZE", "index_name": "…"}]`。
- 本番投入の経路は 2 つある。wrangler の `vectorize insert --file x.ndjson`（NDJSON、既定 1,000 件ごと）と、REST の
  `POST /accounts/{id}/vectorize/v2/indexes/{name}/upsert`（`application/x-ndjson`）。削除は `wrangler vectorize delete-vectors --ids …` か、
  REST の `POST …/delete_by_ids`（本文 `{"ids":[…]}`。必要な権限は Vectorize Write）。一覧は `list-vectors`（最大 1,000 件・カーソル）、`get-vectors` もある。
- 未確認: REST の `delete_by_ids` と `query` の 1 回あたりの上限／REST のレート制限／`wrangler vectorize info` で mutation の反映を見る項目名／
  メタデータに文字列の配列を入れて `$in` で絞れるか（読んだページに記載なし。この設計は配列に頼らない）。

### 2.2 ローカルで動くか（確認済み）

- Workers AI にも Vectorize にも**ローカルの模擬は無い**。バインディングを使うと実リソース（本番のインデックス）へ接続する。
  設定は `"remote": true`（wrangler 4.36.0 以降で安定。`remote: false` だと Workers AI はエラー、省略は警告つきでリモート）。`wrangler dev --local` で全リモートバインディングを無効にできる。
- OpenNext は `next dev` でバインディングを使え、リモートも `remote: true` で効く（`initOpenNextCloudflareForDev()`、`web/next.config.ts`）。
- リモートに接続すると、書き込みは本番に効き、使用量は課金される。認証（wrangler login か CI のサービストークン）が要る。

### 2.3 この設計の扱い

1. **検索は機能フラグと、バインディングの有無の二重で無効にできる形にする。** `web/src/lib/features.ts` に `VECTOR_SEARCH_ENABLED` を足す（CLAUDE.md の「出し分けは features.ts 1 ファイル」）。
   さらに `getCloudflareContext().env` に `AI`・`VECTORIZE` が無い／接続が例外になるときは、ツールは `unavailable`（理由つき）を返し、
   `search_documents` は MCP・AI のツール一覧に載せない（一覧は呼び出し時に決める）。画面・テストは壊れない。
2. **ローカルは既定でベクトル検索を使わない。** `docker compose up` に足すものは無い（埋め込みの作成・投入は手元で明示的に走らせる手順で、起動時に自動実行しない。API トークンが要り、課金も絡むため）。
   ベクトル検索を手元で試したい人だけ、`wrangler login` のうえで `remote: true` の設定を使う（§11 の V1 の結果で書き方を決める）。
3. **未確認の最大の懸念（V1）**: `wrangler.jsonc` に `remote: true` のバインディングを置くと、ログインしていない環境（docker compose・CI）で `next dev` や `vitest` が起動しなくなる恐れがある。
   実装担当が最初に、未ログインで `next dev` が立ち上がるかを確かめる。起動しないなら、(a) `remote` を省いて警告だけで済むか確かめる、
   (b) それでも駄目なら本番用のバインディングを `wrangler.jsonc` の環境（`env.production` 等）に置き、`pnpm run deploy` がその環境を指すようにする、の順に当たる。
4. 画面・API は、検索が無効でも既存の `get_records`（キーワード）で記事を引けるので、機能が減るのは `search_documents` だけ。

## 3. 埋め込みモデル

質問側とインデックス側は同じモデル・同じ次元を使う。モデル名・次元・モデル版は 1 つの設定 `web/src/lib/vector/config.json`（`model`・`dimensions`・`index_name`・`chunker_version`）に書き、スクリプトも web も同じファイルを読む。変えたら全件を作り直す（インデックスの名前を新しくし、旧インデックスは切り替え後に消す）。

| 候補 | ID | 次元 | 最大入力 | 料金（100 万入力トークン） | 備考 |
|---|---|---|---|---|---|
| 第一候補 | `@cf/baai/bge-m3` | 1024（モデルカードの値。CF のページには未記載） | 60,000 トークン | $0.0118（1,075 neurons） | 多言語。質問側に指示文は要らない |
| 第二候補 | `@cf/qwen/qwen3-embedding-0.6b` | 1024（既定。未確認） | 8,192 | $0.0118 | `instruction`（検索用の指示文）を質問側に付ける |
| 第三候補 | `@cf/pfnet/plamo-embedding-1b` | CF のページに記載なし。**1536 を超えるなら Vectorize に入らないので外す** | 記載なし | $0.0186 | 日本語専用 |
| 予備 | `@cf/google/embeddinggemma-2` | 768（128/256/512/768 に切れる） | 8,192 | $0.0017 | 安い。768 次元なら Workers Free の保存枠に収まる（§7）。日本語の対応は未確認 |

- 次元は初回の応答の `shape` で確かめ、`config.json` と違えば作成スクリプトが止まる。
- 3 候補の評価は §9。評価用のインデックスはモデルごとに別に作る（`ryuiki-koho-<モデル略称>-v1`）。件数が小さいので、評価の費用は無視できる（§7）。
- 記載が無かった次元・入力上限は推測で書かず、上の「未確認」のまま評価時に実測する。

## 4. チャンク

### 4.1 記事長の実測（`articles.jsonl` 6,605 件、本文あり 5,042 件・計 2,564,093 字）

| | 文字数 |
|---|---|
| p10 / p25 / p50 | 17 / 51 / 233 |
| p75 / p90 / p95 / p99 | 791 / 1,306 / 1,640 / 2,523 |
| 最大 | 11,420 |

- 1,000 字以下 4,105 件（81%）、1,000 字超 937 件、2,000 字超 123 件。30 字未満が 815 件（写真の説明・見出しだけの囲み等）。
- 本文の行数（PDF の折り返しの改行）は、1,000 字近い記事で中央値 99 行。改行は段落の区切りにならない。段落分割ではなく**文字数と文末**で区切る。

### 4.2 規則（`chunker_version: 1`。変えたら版を上げ、全件を作り直す）

1. 入力は `document_articles` の `body_text`。NFKC で正規化し、空白・改行の連なりを 1 つにし、日本語の文の途中の折り返しは詰める（正規化は 1 つの関数にして、D1 側の本文からスニペットを切るときも同じ関数を通す）。
2. 本文が NULL か 30 字未満の記事は埋め込まない（表紙・目次の `kind='cover_toc'` も除く）。取り下げの対象にはいつでも含める。
3. 正規化後 1,000 字以下は 1 チャンク。超える記事は `。`（なければ `、`、なければ文字数）で区切り、目標 800 字・上限 1,000 字、直前の約 100 字（最後の 1〜2 文）を重ねる。
4. **埋め込む文字列**は `見出し（title）\n区分（section）\nチャンク本文`。見出しが無ければ省く。話題・日付は埋め込まず、メタデータに持つ。
5. 見積もり: 約 5,700 チャンク（1 チャンクの記事 約 3,300 ＋ 長い記事の分割 約 2,400。計算は 800 字目標・100 字重なりの単純な割り算）。余裕を見て 8,000 を上限として設計する。
   埋め込み対象の文字数は約 290 万字（見出し・重なりを含む）。1 字を最大 1 トークンと見ても 300 万トークン以下。

### 4.3 識別子と差分

- **ベクトル ID** = `<sha256(article_id) の先頭 24 文字>:<seq(3桁)>`。ID の上限が 64 バイトで、`article_id`（`<doc_id>:<ページ3桁>:<h8>`）は収まる保証が無いため。
  同じ記事・同じ連番は常に同じ ID になるので、本文が変わっても upsert が置き換える。
- メタデータ（`returnMetadata: 'all'` で返す）: `article_id`・`seq`・`c0`/`c1`（正規化後の本文の中の文字位置）・`body_sha`（記事の `body_sha256`）・`chunk_sha`（埋め込む文字列の sha256）。
  インデックスするのは絞り込みに使うものだけ: `region_id`（string）・`source_id`（string）・`year`（number。発行年）・`kind`（string）。話題は配列に頼れないので索引にせず、D1 の `document_article_topics` で後から絞る（§6.2）。
- **キャッシュの鍵** = `chunk_sha`（`sha256(model + chunker_version + 埋め込む文字列)`）。本文・見出し・モデル・規則のどれかが変わればキーが変わる。
- 記事の本文が短くなってチャンク数が減ったときの余り（`seq` が大きい側）は、同期スクリプトが前回のマニフェストとの差から削除する（§5.4）。

## 5. 埋め込みの作成と投入

### 5.1 経路: Node（`web/scripts/vector/`）

Python でなく Node にする。理由: 既存の `web/scripts/d1/`・`seed-d1-local.mjs` と同じ `better-sqlite3`・`wrangler` の流れに乗れる／`fetch` が標準で、Python の venv が要らない／web とチャンク規則・設定ファイルを共有できる（規則を二箇所に書かない）。

| ファイル | 役割 |
|---|---|
| `chunk.mjs` | §4 の正規化とチャンク分割（純関数。web からも import できるよう依存なし） |
| `embed.mjs` | 原本の `document_articles` を読み取り専用で開き、チャンクを作り、キャッシュに無いものだけ Workers AI で埋め込む |
| `sync.mjs` | 望ましい状態（キャッシュのチャンク）とマニフェスト（前回入れた状態）の差を計算し、upsert と delete を出す |
| `eval.mjs` | §9 の評価を回す |
| `status.mjs` | チャンク数・キャッシュ・マニフェスト・Vectorize 側（`info`/`list-vectors`）の件数を突き合わせる |

### 5.2 認証

- 環境変数 `CLOUDFLARE_API_TOKEN` と `CLOUDFLARE_ACCOUNT_ID`。リポジトリにも `.env` のコミットにも置かない（本番操作は `CLOUDFLARE_ACCOUNT_ID` を付ける、というこれまでの運用のとおり）。
- トークンの権限: Workers AI の Read と Edit（ドキュメントの記載）、Vectorize の Write（`delete_by_ids` の要件）。Read 系（`list-vectors`・`query`）の権限名は未確認。評価・作成用と、通常の同期用でトークンを分けるかはオーナーが決める（§12）。
- Worker 側（検索時）はバインディングを使うので、トークンは持たない。

### 5.3 キャッシュ

- `data/vector/cache.sqlite`（`data/*` は gitignore 済み。原本ではなく、再作成できる生成物）。表 `embedding(model, chunk_sha, dims, vec BLOB, created_at)`、主キー `(model, chunk_sha)`。
- 埋め込みは Workers AI の REST（`POST /accounts/{id}/ai/run/@cf/baai/bge-m3`）にバッチで送る。1 回あたりの件数上限は未確認なので、32 件から始めて 429/エラーで半分にする。
- ネットワークが切れても途中から再開できるよう、1 バッチごとにキャッシュへコミットする。

### 5.4 同期（本番へ）

- マニフェスト `data/vector/<index_name>/manifest.jsonl`: 入れた（入れたはずの）`id`・`article_id`・`chunk_sha`。
- `sync.mjs` は dry-run が既定で、増える・変わる・消える ID の件数と、変わる記事の一覧を出す。`--execute` で REST の upsert（NDJSON、1,000 件ずつ。HTTP の上限は 5,000 だが wrangler の勧め〈1 ファイル 5,000 件以下〉に合わせて小さく）と `delete_by_ids` を呼ぶ。
  成功した分だけマニフェストを更新する。メタデータインデックスの作成は**初回のベクトル投入の前**に `sync.mjs --init` が行う（既にあれば何もしない）。
- 反映は非同期（§2.1）。`--execute` の後、`status.mjs` が Vectorize 側の件数がマニフェストと一致するまで待つ。一致しないまま一定時間を超えたら非ゼロで終わる。
- 本番 D1 の入れ直し（`web/scripts/d1/`）とは別のスクリプトだが、順序は D1 が先、ベクトルが後（D1 に無い記事はベクトルがあっても返さない設計なので、順序を逆にしても検索は壊れないが、新しい記事がしばらく出ない）。
- 本番の手順と日付は `DEPLOYMENT.md` に書く（完了条件の一つ）。

### 5.5 取り下げ（`TATSUGO_KOHO.md` §9 の手順 4 の中身）

1. 除外リスト `scripts/data/tatsugo_koho_withdrawn.yaml` を読み、D1 を消す**前**に取った `article_id` の一覧（号なら `<doc_id>:` で始まるもの）から、マニフェストの該当 ID を引く。
2. `sync.mjs --withdraw` が、そのチャンクを `delete_by_ids` で消し、マニフェストと**キャッシュ**（取り下げた本文から作ったベクトルを手元に残さない）からも消す。
3. 確認: `status.mjs` の件数がマニフェストと一致する／`search_documents` の結果に外した `article_id` が出ない（§8）。
4. D1 の `document_articles` にその記事が無ければ、ベクトルが残っていても検索は返さない（§6.2 の突き合わせ）。つまり万一削除が遅れても、公開側の表には出ない。ただし Vectorize に本文由来のベクトルが残るので、手順 2 は省かない。

## 6. 検索の窓口

### 6.1 ツール `search_documents`（MCP と AI で共通）

名前は既存の `find_datasets`（目録）・`get_records`（行）と並べて、`search_documents`（記事の内容を探す）にする。実装は `web/src/lib/document-search.ts` の 1 関数で、MCP（`web/src/lib/mcp/`）と AI（`web/src/lib/ai/tools.ts`）が呼ぶ（ADR-0014）。

入力:

| 名前 | 型 | 内容 |
|---|---|---|
| `query` | string（必須、1〜200 字） | 探したい内容を日本語の文で |
| `region_id` | string? | 地域の絞り込み（既定は全域） |
| `year_from` / `year_to` | number? | 発行年（西暦）の範囲 |
| `topic` | string? | 話題の語彙（`TATSUGO_KOHO.md` §4）。D1 で後から絞る |
| `mode` | `'semantic'` \| `'hybrid'`? | 既定は評価で決める（§9）。キーワードだけは `get_records` の `q` を使う |
| `limit` | number? | 既定 5、最大 10（AI は応答の大きさから 5 に抑える） |

出力（1 件ごと、記事単位。同じ記事の複数チャンクは最良の 1 件にまとめる）:
`article_id`・`title`・`section`・`issue`（号の表示名）・`page`（号内の通しページ。`p.○`）・`snippet`（該当チャンクの本文。D1 の `body_text` を `c0`〜`c1` で切る。長さの上限あり）・
`score`（cosine の類似度。hybrid では順位融合の値と、元の類似度を別に）・`citation`（龍郷町「広報たつごう」○年○月号 p.○）・`pdf_url`（元の PDF の URL）・`doc_id`。
**`citation` と `pdf_url` が組み立てられない行は返さない**（`TATSUGO_KOHO.md` §6.3 の出典と URL の作り方に従う）。応答には他のツールと同じく caveats をサーバ側で機械的に付ける。
本文が NULL で読めない記事は snippet を空にせず、`unreadable_reason` を返す。

### 6.2 流れ

1. `query` を `env.AI.run(model, …)` で埋め込む（失敗は `unavailable`）。
2. `env.VECTORIZE.query(vec, {topK: 50, returnMetadata: 'all', filter})`。`filter` は `region_id`・`year`（`$gte`/`$lte`）・`kind: 'article'` のうち指定されたもの。topK 50 はメタデータを返すときの上限。
3. 結果を `article_id` ごとに最良のチャンクにまとめる。
4. `queryChunked` で `document_articles`（と号・ファイルの表）を引き、**D1 に無い `article_id`（取り下げ済み・未反映）は捨てる**。`topic` はここで `document_article_topics` を使って絞る。
   絞った結果が `limit` に足りなければ、足りないことを caveat に書く（topK を増やして再検索はしない。上限が 50 のため）。
5. メタデータの `body_sha` と D1 の `body_sha256` が違えば、そのチャンクの文字位置は信用せず、記事の冒頭を snippet にして `stale_index: true` を付ける（入れ直しの合図）。
6. 順位を `limit` に切って返す。

### 6.3 キーワードとの併用

- 固有名詞（集落名・川の名前・人名）は、ベクトルだと外れやすいので `hybrid` を用意する。キーワード側は `get_records` の `record_set=document_articles` の `q`（`title`・`body_text` への LIKE。約 5,000 行の走査）を使い、
  文の中の語を空白で区切って AND/OR のどちらにするかは評価で決める。日本語の FTS5（trigram トークナイザ）は D1 での対応を未確認なので、最初は LIKE で足りるかを測る。
- 融合は RRF（`score = Σ 1/(60 + 順位)`、semantic と keyword を等重み）。記事単位の順位で混ぜる。
- 既定を `hybrid` にする条件（§9.4）: 固有名詞の質問で recall@5 が semantic より 5 ポイント以上上がり、概念の質問で下がらない。満たさなければ `semantic` を既定にし、`hybrid` は指定したときだけ。

## 7. 費用の見積もり

前提: チャンク 約 5,700（上限 8,000）、1024 次元、検索 月 5,000 回（上限は 40,000 回で見る）、本文の全件作り直し 月 1 回。

| 項目 | 計算 | 月額 |
|---|---|---|
| Vectorize 保存 | 5,700 × 1,024 ＝ 約 5.8M 次元（Workers Paid の含み 10M の内） | $0 |
| Vectorize 検索 | (5,000 + 5,700) × 1,024 ＝ 約 11M 次元（含まれる 50M の内） | $0。月約 41,000 回までは含まれる計算（料金ページの式から。超過は 100 万次元あたり $0.01） |
| 埋め込み（全件、1 回） | 約 300 万トークン × $0.0118/100万 ＝ 約 $0.035（約 3,200 neurons） | 約 $0.04。1 日 10,000 neurons の無料枠にも収まる |
| 埋め込み（質問） | 1 回 約 50 トークン × 5,000 回 ＝ 25 万トークン | $0.003 未満 |
| 評価（3 モデル × 全件） | 約 $0.1 を 1 度 | 1 度だけ |
| **合計** | | **Workers Paid に入っていれば、追加は月 $0.1 未満** |

- **Workers Free の保存枠は 500 万次元**（料金ページ）。1024 次元だと 約 4,900 ベクトルが上限で、5,700 チャンクは収まらない。
  すでに Workers Paid（月 $5〜）なら追加費用は上の表のとおり。Free なら、768 次元（`embeddinggemma-2`）に切れば 約 4.4M 次元で収まる。どちらの契約かをオーナーが確認する（§12）。
- 料金の根拠は §1 の URL の 2 ページ。単価が変わる可能性があるので、実装時に再確認して `DEPLOYMENT.md` に日付つきで書く。

## 8. CI とテスト

CI は原本もバインディングも無い clone で走る（sample-gate・web の lint/test）。ベクトル関連は次のように切る。

- **差し込み口**: `document-search.ts` は `embed(text): Promise<number[]>` と `index.query(vec, opts)` を引数（またはモジュール内の関数オブジェクト）として受け取り、既定でバインディングを使う。テストは差し替える。
- **偽の埋め込み**: 決定的な「文字 2-gram のハッシュを 64 次元に畳む」関数。実モデルの品質は見ず、並び替え・絞り込み・突き合わせの**配管**だけを試す。偽のインデックスはメモリ上で cosine を計算する（メタデータの `$eq`/`$gte`/`$lte` を実装）。
- テストする内容（vitest。`web/src/lib/document-search.test.ts`、`web/src/lib/ai/tools-document-search.test.ts`）:
  1. D1 に無い `article_id`（取り下げ済み）は返らない。
  2. 同じ記事の複数チャンクは 1 件にまとまり、最良のチャンクの snippet が付く。
  3. `citation` と `pdf_url` の無い行は返らない。
  4. `body_sha` 不一致で `stale_index`。
  5. `year`・`region_id` の絞り込みが Vectorize 側のフィルタに渡る。`topic` は D1 で絞る。
  6. RRF の順位融合（既知の 2 つの順位から期待の順位）。
  7. バインディングが無い・例外のとき `unavailable` を返し、他のツールは動く。
  8. ツール一覧: フラグが無効、またはバインディングが無いと `search_documents` が一覧に出ない（MCP・AI の両方。既存のスナップショット `web/src/lib/ai/__snapshots__` の更新が要るかを確認）。
  9. チャンク規則（`chunk.mjs`）: 1,000 字以下は 1 チャンク、長い記事の分割・重なり・上限、30 字未満は対象外、`chunk_sha` が本文変更で変わる、ベクトル ID が 64 バイト以下。
  10. 同期の差分計算（マニフェストと望ましい状態から、upsert・delete の ID 集合）。余りの `seq` の削除を含む。
- **サンプル**: `data/sample/` にベクトルは入れない。サンプルの serving スナップショット（sample-gate）は変えない。サンプルの記事を使う統合テストは偽の埋め込みで足りる。
- 実モデル・実インデックスに当てるテストは CI に置かない（API トークンが要る）。それは §9 の評価として手元で回す。
- 取り下げのテスト: 偽のインデックスに入れた記事を `--withdraw` の関数で消し、マニフェスト・キャッシュ・偽インデックスのどこにも残らないことを確かめる（単体）。本番での確認は手順書（§5.5 の 3）。

## 9. 評価

### 9.1 質問集

- 20〜30 問。置き場は `scripts/data/tatsugo_koho_eval.yaml`（質問・種別・正解の `article_id`・付けた人と日付）。コミットする（質問と ID だけ。本文は入れない）。
- 話題の分類（`TATSUGO_KOHO.md` §4 の語彙）ごとに 2〜3 問、残りは種別で埋める。種別を付ける:
  - **概念**: 記事の語を含まない言い換え（例「大雨で道が通れなくなった話」）
  - **固有名詞**: 集落名・川の名前・行事名を含む
  - **時期**: 年や季節で絞る（フィルタの試験）
  - 各種別に少なくとも 5 問。
- 作り方: 評価対象のモデルから正解を作らない（循環を避ける）。話題ごとに、`get_records` のキーワード（見出し・本文の LIKE）で候補の記事を人が集め、質問文を人が書く。
  正解は候補から**人が**決め、複数ありうる質問は全部付ける。正解が 1 件も無い質問（ネガティブ）を数問混ぜ、「出ない」ことも見る。Sonnet が質問の下書きを作るのは構わないが、正解の確定は人。

### 9.2 指標

- **recall@5**: 上位 5 件に正解が 1 件以上ある質問の割合（質問単位）。正解が複数ある質問は、上位 5 件に入った正解の割合（平均）も併記。
- 種別ごと・話題ごとの内訳も出す。MRR（最初の正解の順位の逆数）を参考に添える。

### 9.3 手順（API トークンが要る。手元で人が回す）

1. `config.json` を評価用に切り替え（モデル・次元・`index_name` をモデルごとに別名で）、`embed.mjs` と `sync.mjs --init --execute` で 3 モデルぶんのインデックスを作る。
2. `eval.mjs --index <名前> --mode semantic|hybrid` が質問集を順に引き、上位 5 件の `article_id` を質問ごとに記録して、種別・話題ごとの表を出す。結果は PR の説明と Issue のコメントに表で貼る。
3. モデル 3 × {semantic, hybrid} の 6 通りを 1 表にまとめる。
4. 評価後、選ばなかったインデックスは削除する（保存次元は無料枠内だが、更新時に迷わないように）。

### 9.4 モデルとモードの決め方（提案）

- 全体の recall@5 が最も高いモデルを採る。差が 3 ポイント以内なら、費用が低く次元の小さいほうを採る。
- いずれのモデルでも概念の質問で recall@5 が 0.6 に届かないなら、チャンク規則（§4）を見直してから比べ直す（モデルを替えて解決しようとしない）。
- `hybrid` を既定にする条件は §6.3。

### 9.5 評価の結果（2026-11-24、実施済み）と決定

実装: `web/scripts/vector/eval.mjs`（キャッシュ済みのベクトルへの全探索 cosine。Vectorize・Cloudflare への書き込みなし）。
質問集 `scripts/data/tatsugo_koho_eval.yaml` は 26 問（正解あり 25 問＋記事に無い話題の否定 1 問）。**正解付けはモデル（Sonnet）で、人の確認はまだ**（本文が段組みで崩れた記事が多く、取りこぼしがありうる）。
入力は本物の cells.sqlite の記事 5,307 件（再抽出後）→ 対象 3,905 件・チャンク 5,127（埋め込み 5,107 種。再抽出前の 5,296 件でも表は同じ）。次元は両モデルとも 1024（V2 確認）。
経路は AI Gateway の `/compat/embeddings`（新しいトークンなし）。bge-m3 の全件埋め込み 69 秒、qwen3-embedding-0.6b は 521 秒（レート制限の再試行を含む）。
キーワード側は質問を `Intl.Segmenter` で語に分け（ひらがなだけの語は捨てる・最大 6 語）、D1 の LIKE に当たる語の IDF 合計で順位づけし、RRF（k=60）で混ぜた。

| モデル | 方式 | recall@5 全体 | 概念(16) | 固有名詞(5) | 時期(4) | 平均再現（複数正解） | MRR |
|---|---|---|---|---|---|---|---|
| bge-m3 | **semantic** | **88%** (22/25) | **88%** | 80% | 100% | 74% | 0.651 |
| bge-m3 | keyword（LIKE） | 64% (16/25) | 50% | 100% | 75% | 51% | 0.473 |
| bge-m3 | hybrid（RRF） | 84% (21/25) | 81% | 100% | 75% | 77% | 0.735 |
| qwen3-0.6b | semantic | 76% (19/25) | 75% | 60% | 100% | 68% | 0.630 |
| qwen3-0.6b | keyword（LIKE） | 64% (16/25) | 50% | 100% | 75% | 51% | 0.473 |
| qwen3-0.6b | hybrid（RRF） | 80% (20/25) | 75% | 80% | 100% | 74% | 0.682 |

- **決定: モデルは bge-m3、既定は semantic。** 全体 recall@5 は bge-m3 が qwen3 より 12 ポイント高い（§9.4 の「差 3 ポイント以内なら安いほう」に当たらない）。
  概念の質問は 88%（§9.4 の 0.6 以上）。
- hybrid は固有名詞で +20 ポイント（80→100%）と §6.3 の条件（+5 ポイント）を満たすが、概念で 88→81% に下がるので「概念で下がらない」を満たさない。
  既定は semantic のまま、`mode: "hybrid"` を指定できるようにした（MRR と複数正解の再現は hybrid が上）。固有名詞の質問は AI のプロンプトで hybrid を勧める余地がある。
- 否定の質問（記事に無い話題）の最上位の cosine は 0.667 で、正解のある質問の最上位の平均 0.602 より高い。**cosine に閾値を置いて「該当なし」を判定できない**。ツールの説明に、snippet を読んで確かめるよう書いた。
- 母数が小さい（25 問）。1 問が 4 ポイントに当たるので、方式間の差のうち数ポイントは誤差。人が正解を直したら `eval.mjs` を回し直す（キャッシュがあるので質問の埋め込みだけ）。
- 取りこぼしの傾向: 本文が崩れた記事（q05・q09）、見出しが空の記事、質問と記事で語が離れる問い（「毒蛇＝ハブ」q22）。チャンク規則の見直しより前に、PDF 抽出（c106）の段組みの質が効く。

## 10. 実装の割り当て（衝突しない単位）

| 担当 | 範囲 | 先に読む節 |
|---|---|---|
| A スクリプト | `web/scripts/vector/`（chunk・embed・sync・status・eval）と `config.json`、チャンク・差分のテスト | §3〜§5、§8 の 9・10、§9 |
| B web | `web/src/lib/document-search.ts`・MCP と AI のツール登録・`features.ts`・`wrangler.jsonc` のバインディング・型 | §2.3、§6、§8 の 1〜8 |
| C 手順書 | `DEPLOYMENT.md`、CLAUDE.md の要点の追記、評価の質問集の枠（正解付けは人） | §5.4〜§5.5、§7、§9 |

A と B は `config.json` の形だけが接点なので並行できる。B の本番バインディングは、インデックスが無いと `wrangler deploy` が失敗するので、デプロイの前にインデックスを作る（作成の担当は §12）。

## 11. 実装担当が最初に確かめること（未確認の一覧）

- **V1** 未ログインで `next dev` と `vitest` が、`ai`・`vectorize` のバインディング入りの `wrangler.jsonc` で立ち上がるか（§2.3 の 3）。
- **V2** `bge-m3` の次元（`shape`）、`plamo-embedding-1b` の次元（1536 以下か）、REST の埋め込みの 1 回あたりの件数上限。
- **V3** REST の `delete_by_ids`・`query` の上限、REST のレート制限、`info` で mutation の反映を見る項目名。
- **V4** メタデータに配列を入れて絞れるか（できれば話題を索引にできる）。
- **V5** D1 で日本語の全文検索（FTS5 trigram）が使えるか。使えなければ LIKE のまま。
- **V6** `getCloudflareContext().env.AI.run(...)` の埋め込みの入出力の形（バインディングのページには埋め込みの例が無かった）。

## 12. オーナーが決めること

1. Cloudflare は Workers Paid か Free か（Free なら 768 次元に落とす、または Paid にする。§7）。
2. API トークンを作って渡す人と、権限の分け方（作成・同期用と評価用を分けるか）。インデックスの作成（`wrangler vectorize create`）をオーナーの操作とするか。
3. 評価の質問集の正解付けを誰がやるか（§9.1。人の作業）。
4. 検索の既定を `hybrid` か `semantic` にするのは、評価の結果で決めてよいか。
5. 30 字未満の記事（815 件。写真の説明など）を検索の対象外にしてよいか（既定は対象外）。

## 13. 受け入れ基準（#132 の受け入れの具体化）

- 質問集 20〜30 問の recall@5 を、モデル候補 × キーワード併用の有無の表で報告している。
- 本番で、MCP と AI アシスタントから内容で記事を探せ、すべての結果に `citation` と `pdf_url` が付く。
- 記事を取り下げると D1 と Vectorize の両方から消える（§8 の単体テストと、§5.5 の本番確認）。
- ローカル（docker compose・未ログイン）と CI でベクトル検索が無効でも、画面・API・既存ツール・テストが壊れない。
- 構成と手順が本書と `DEPLOYMENT.md` にある。
