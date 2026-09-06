# 流域カルテ / Watershed Chart — デモ

尾根から海まで（Ridge to Reef）の観測データを、流域という一つの単位で見るためのモニタリングデータ基盤のデモ実装です。
要求定義（リポジトリ直下の `app_description.md`）に対して、**神奈川県の公開データだけ**で画面を組んでいます。

実運用の対象地である鹿児島県龍郷町のデータはまだ無いため、構造が同じ公開データが揃う神奈川県を使っています。
地点・測定項目・水域は設定とデータで差し替えられる作りにしてあり、地名や項目名をコードに埋め込んでいません。

## 動かす

前提: `../data/db/` に原本 `ryuiki.sqlite` と `cells.sqlite` があること。

### Docker（推奨）

```bash
docker compose up          # リポジトリ直下で
# → http://localhost:3000
```

起動時に「集計 DB の生成 → D1 マイグレーション → シード投入」を、まだのものだけ実行します。
初回は 3〜5 分。2 回目以降はローカル D1 が名前付きボリューム `d1-state` に残るので素通りします。
入れ直したいときは `docker compose down -v`。

### ホストで直接

前提: Node.js 20 以上（開発時は 22.22）。

```bash
cd web
pnpm install
pnpm run build:derived   # 集計 DB (../data/db/derived.sqlite) を作る。初回のみ・約1分
pnpm run db:setup        # D1 マイグレーション + シード投入（約1.5分）
pnpm run dev             # http://localhost:3000
```

`build:derived` は原本を**読み取り専用**で開き、集計済みテーブルだけを別ファイルに書き出します。
原本の `ryuiki.sqlite` / `cells.sqlite` は一切書き換えません。いつでも消して作り直せます。

| スクリプト | 中身 |
|---|---|
| `scripts/build-derived.mjs` | 測定値・センサー・品質・行政文書の集計 |
| `scripts/build-geo.mjs` | 流域界ポリゴンの属性、土地利用 2006/2016、生物レコードの流域への点内包判定 |
| `scripts/build-biota.mjs` | 生物レコードの分類正規化（iNaturalist の欠損補完・魚類判定）と種別集計、レッドリスト版間比較 |
| `scripts/seed-d1-local.mjs` | 原本 SQLite 3 ファイルの中身をローカル D1 に流し込む（開発専用） |
| `scripts/copy-maplibre-worker.mjs` | MapLibre のワーカーを `public/` へ配置（`pnpm run dev` / `build` の前に自動実行） |
| `scripts/copy-geo-assets.mjs` | 地図の GeoJSON を `../data/processed` から `public/geo/` へ配置（同上）。Workers に fs は無いので静的アセットで配る |
| `scripts/export-d1-sql.mjs` | ローカル D1 の中身を本番 D1 に流せる .sql に書き出す（`dist/d1/`） |
| `scripts/verify-d1-remote.mjs` | ローカル D1 と本番 D1 の行数を全テーブルで突き合わせる |

スクリプトは `pnpm run <name>` で呼ぶ。`pnpm deploy` は pnpm 組み込みのコマンドで
package.json の `deploy` は動かないので、デプロイは必ず `pnpm run deploy`。

| pnpm script | 中身 |
|---|---|
| `db:generate` | `src/db/schema.ts` から `drizzle/migrations/*.sql` を作る |
| `db:migrate` | ローカル D1 にマイグレーションを当てる（適用済みは飛ばす） |
| `db:seed` | ローカル D1 にシードを入れる（原本に変化が無ければ飛ばす） |
| `db:setup` | `db:migrate` + `db:seed` |
| `db:reset` | ローカル D1 を捨てて作り直す |
| `cf-typegen` | `wrangler.jsonc` から `worker-configuration.d.ts` を生成（`--env-interface CloudflareEnv` 必須） |
| `prepare:geo` | 地図の GeoJSON を `public/geo/` へ配置 |
| `db:migrate:remote` | 本番 D1 にマイグレーションを当てる |
| `db:export` | 本番投入用の .sql を `dist/d1/` に書き出す |
| `db:verify:remote` | ローカルと本番の行数を突き合わせる |

## データの置き場所 — D1

Cloudflare へのデプロイを見据えて、**データは D1（Cloudflare の SQLite）に置いています**。
元は 3 つの SQLite ファイルを `ATTACH` して `d.` / `c.` の接頭辞で引いていましたが、
D1 に `ATTACH` は無いので、61 テーブルを 1 つの D1 に統合し、素のテーブル名で引いています。
どの原本から来たテーブルかは `src/lib/table-meta.ts` の `TABLE_ORIGIN` が持ちます。

```
data/db/ryuiki.sqlite  ─┐
data/db/cells.sqlite   ─┼→ scripts/seed-d1-local.mjs →  D1 (61 テーブル / 419 万行 / 約 1.3GB)
data/db/derived.sqlite ─┘        （原本は readonly で開く）
```

スキーマは Drizzle で持ち、マイグレーションは drizzle-kit が生成して wrangler が当てます。

```
src/db/schema.ts        ── drizzle-kit generate ──> drizzle/migrations/0000_init.sql
                                                     └─ wrangler d1 migrations apply
```

ローカルの D1 は wrangler / miniflare が `.wrangler/state/v3/d1/` に持つただの SQLite ファイルです。
`next dev` からは `next.config.ts` の `initOpenNextCloudflareForDev()` 経由で同じものに繋がります。
344 万行を `wrangler d1 execute --file` で流すと現実的な時間で終わらないため、
シードはそのファイルへ直接 INSERT しています（開発専用の近道。本番 D1 には使えません）。

### D1 の制約で気をつけること

| 制約 | 効いてくる場所 |
|---|---|
| バインドパラメータ 100個/クエリ | `IN (...)` は `db.ts` の `queryChunked` で 80 個ずつに分割している |
| 1 データベース 10GB（有料）/ 500MB（無料） | 現状 1.3GB。無料プランには載らない |
| SQL 文 100KB / 実行 30 秒 | 現状は余裕がある |
| ATTACH 不可・ユーザー定義関数不可 | テーブルを 1 DB に統合済み。`REGEXP` は使っていない |

## 画面

| パス | 内容 |
|---|---|
| `/` | 概況。何が入っているか、比べるときに何に気をつけるか |
| `/map` | 流域マップ。単位流域 377 面の塗り分け、観測地点、生物記録メッシュ、河川、介入・意思決定 |
| `/timeseries` | 時系列比較。水域の中で地点を比べる／ゾーンで比べる／季節で比べる |
| `/biota` | 生物相。記録の中身、種のふえへり（分類群内シェア）、外来種、レッドリスト版間比較 |
| `/sites`, `/sites/[id]` | 地点カルテ。一覧と個票 |
| `/documents` | 行政PDF由来の統計。各点の出典ページと「比較を妨げる注記」 |
| `/quality` | 品質パイプライン、現場の体制、介入と意思決定のタイムライン |
| `/explore` | D1 の直接探索。テーブル閲覧・列の要約・任意の SELECT・CSV 書き出し。**現在は停止中**（`src/lib/features.ts` の `EXPLORE_ENABLED`） |
| `/sources` | 出典 101 件と抽出元文書 98 件。ライセンスと再配布可否 |

## AI データ分析アシスタント

画面右下の「AIに聞く」から、流域カルテのデータについて自然文で質問できます。データ分析の専門家でない
利用者を想定し、専門用語には説明を添え、答えられないことは「分からない」とはっきり言うようにしています。

- モデルは **Cloudflare AI Gateway** の OpenAI 互換エンドポイント（`.../compat`）経由で呼ぶ。
  既定は Workers AI の Kimi K2.6（`workers-ai/@cf/moonshotai/kimi-k2.6`。tool calling / streaming 対応・262kコンテキスト）。
  差し替えは env の `AI_MODEL` を変えるだけで、`src/lib/ai/provider.ts` は触らない。
- 必要な env は `AI_GATEWAY_ACCOUNT_ID` / `AI_GATEWAY_NAME`（既定 `default`）/ `AI_GATEWAY_TOKEN` / `AI_MODEL`。
  `.env.local.example` に取得手順のコメントがある。**未設定でもアプリ・ビルドは普通に動く**。
  `/api/chat` が 503 を返し、AIパネルには「AIが未設定です」とだけ出る。
- 中身は「意図レベルのツール」10個（`src/lib/ai/tools.ts`）。モデルが70個の関数を選ぶような作りにはしていない。
  ツールはほぼ `src/lib/queries.ts` の合成で、新しい SQL はほとんど書いていない。フォールバックとして
  `run_sql`（SELECT/WITH/EXPLAIN のみ・行数200・応答8KBまで）がある。
- ツールが触れたテーブルから、`domain.ts` の注記（測定値の癖・観察努力バイアス・合成データ等）を
  **決定論的に**引いて必ず証跡カードに出す（`src/lib/ai/caveats.ts`）。モデルの文章に注記の有無を委ねない。
- 会話は `AssistantPanel`（`src/components/assistant/`）が `app/layout.tsx` に常駐して持つので、
  画面を遷移しても会話は消えない。

## 地図の差し替え（OpenStreetMap → Mapbox）

地図は **MapLibre GL JS**（Mapbox GL JS のオープンソース版）で描いています。
既定はトークン不要の OpenStreetMap と地理院タイルです。

`.env.local` に

```
NEXT_PUBLIC_MAPBOX_TOKEN=pk.xxxxx
```

を置くだけで、ベースマップの選択肢に Mapbox のスタイル（Light / Streets / Outdoors / Satellite / Dark）が増えます。
`mapbox://` スキームの書き換えとトークン付与は `src/lib/map/basemaps.ts` の `mapTransformRequest` が行います。
別のプロバイダに変えるときも、触るのはこのファイルだけです。

## 構成

```
src/
  app/            画面（App Router）と API ルート
  components/
    viz/          チャート（SVG 自前実装）と配色トークン
    map/          MapLibre のラッパとレイヤ定義
    explore/      データ探索 UI
  db/
    schema.ts     D1 のスキーマ定義（Drizzle）。マイグレーションの生成元
  lib/
    db.ts         D1 接続。参照系のみ。バインド上限の分割もここ
    queries.ts    画面が使う問い合わせ（すべて async）
    domain.ts     原本の癖と注記の文言
    map/          ベースマップの抽象化
drizzle/
  migrations/     drizzle-kit が生成した D1 マイグレーション
scripts/          派生 DB のビルドと D1 シード
```

### 配色

チャートの配色は `src/components/viz/palette.ts` に集約し、色覚多様性・コントラストの検証を通した値だけを使っています。

- 系列（実体の識別）: 8色固定。9系列目は作らず「その他」にまとめる
- ゾーン 1–5（順序尺度）: 単一色相の序列ランプ
- 連続量（件数・密度）: 別色相の逐次ランプ
- 正負のある量（土地利用の増減）: 発散配色（中央は無彩色）
- 状態（品質段階）: 状態色。必ずラベルを添える

### データの扱いで決めていること

- アプリから D1 へ書き込まない。`/explore` の SQL コンソールも参照系しか通さない
- ただしその `/explore` と `/api/sql` `/api/table` `/api/schema` は、任意 SQL と全表スキャンが認証なしで叩けて
  D1 の rows_read がそのまま課金に乗るため、公開デモの間は `EXPLORE_ENABLED = false` で閉じている
- 原本 SQLite は集計スクリプトもシードも `readonly` で開く。一切書き換えない
- 値を補完・推測しない。欠けているものは欠けたまま出す
- 定量下限未満（`<0.5` など）は 0 として描かず、中抜きの点で示す
- 生物の件数は観察努力を強く反映するため、増減は分類群内のシェアかメッシュ占有率で見る
- 合成データ（観測者・介入・意思決定・品質段階の遷移）は画面上で必ずその旨を書く
- 再配布できない出典の数値は、どのグラフにも使わない

## 既知の限界

- ゾーン 1（標高 800m 超）には水質データが無く、ゾーン比較は 2–5 の4段階まで
- 生物レコードには `site_id` が無いため、流域への割り当ては座標からの点内包判定による
- GBIF 側の取り込みは 2024年12月で途切れており、2025年以降の鳥類の減少はデータの都合
- 降雨・大気の観測点は緯度経度が公開されておらず、地図に出せない

## デプロイ

Cloudflare Workers + D1 へのデプロイ手順は、リポジトリ直下の `DEPLOYMENT.md` にまとめてある。
**GeoJSON がファイルシステム読みのままなので、そのまま出すと `/map` の流域界と河川が出ない。**
その 1 点だけ先に潰す必要がある（詳細と直し方は `DEPLOYMENT.md`）。

```bash
pnpm run preview   # 本番ビルドを workerd で手元実行 → http://localhost:8787
pnpm run deploy    # opennextjs-cloudflare build && deploy
pnpm run db:export # 本番 D1 に流し込む .sql を dist/d1/ に書き出す
```
