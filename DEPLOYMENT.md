# デプロイ — Cloudflare Workers + D1

`web/` の Next.js を [@opennextjs/cloudflare](https://opennext.js.org/cloudflare) で Workers 向けに
ビルドし、データは D1 に置く。開発環境（`docker compose up`）と同じ D1 スキーマ・同じデータを
そのまま本番へ持っていく。

## 現状

2026-09-01 に一通り実行して本番へ出した。

| | |
|---|---|
| URL | https://ryuiki-demo.tokyo-odh-009.workers.dev |
| Cloudflare アカウント | `tokyo_odh_009`（`1eb4c30d…`） |
| Worker | `ryuiki-demo` |
| D1 | `ryuiki` / `634bbe1b-72aa-48a0-9021-c15167f68a0b` / リージョン APAC |
| シークレット | `AI_GATEWAY_TOKEN`, `AI_GATEWAY_ACCOUNT_ID` |
| データ | 61 テーブル / 4,193,724 行 / 1.32GB（ローカル D1 と全テーブル一致を確認） |

**2026-09-05 追記**: 水道水の水源マップ（`docs/WATER_SOURCE_MAP.md`）の Phase 0〜2 を出した。
`water_*` 8 テーブル / 13,243 行を追加（マイグレーション `0002_mute_tempest.sql`）。
`/water` が増え、静的アセットに `water_zones.geojson`（9.4MB / brotli 2.1MB）が乗った。
全 9 ページと `/geo/water_zones.geojson` が 200 を返すことを確認済み。

**2026-09-06**: Phase 3（川崎・横須賀・独立系・地下水系）まで反映。
`water_*` は 8 テーブル / 18,980 行、`water_zones.geojson` は 10.0MB。
**入れ直しは「全 8 テーブルを DELETE → 連番順に流す」**。`water_zone_source_share` に主キーが無く、
二度流すと黙って重複するため（下の「詰まりどころ」参照）。本番と手元の行数一致を確認済み。
デプロイ直後は Worker が温まるまで `/water` が 25 秒で返らないことがある（2 回目以降は 0.2〜0.9 秒）。

以下は実際に流して確認したもの。

| 手順 | 状態 |
|---|---|
| `opennextjs-cloudflare build` | ✅ |
| `wrangler dev`（workerd で本番ビルドを実行） | ✅ 全ページ・全 API が 200 |
| `pnpm run db:export` | ✅ 981MB 分の .sql（既定の 20MB 刻みで 90 本ほど）・約 1 分 |
| `wrangler d1 create` / `--remote` のマイグレーション | ✅ |
| `wrangler d1 execute --remote --file`（本番投入） | ✅ ただし詰まりどころ多数。下を読むこと |
| `opennextjs-cloudflare deploy` | ✅ |
| AI アシスタント（AI Gateway 越しの Workers AI） | ✅ `/api/chat` がストリーミングを返す |

## GeoJSON は静的アセットで配る

Workers にファイルシステムは無いので、`data/processed/*.geojson` を `fs` で読むことはできない。
地図が使う 2 ファイルは `web/public/geo/` に置いて静的アセットとして配っている。

| 原本 | 公開パス | 経路 |
|---|---|---|
| `nlni_w05_rivers.geojson` (4.8MB) | `/geo/rivers.geojson` (4.5MB) | ブラウザが直接取る（Worker を通さない） |
| `nlni_w12_watersheds.geojson` (1.3MB) | `/geo/watersheds.geojson` (1.2MB) | `/api/geo/watersheds` が ASSETS バインディング経由で読み、D1 の `watershed_rollup` を載せて返す |

`web/public/geo/` は生成物（`.gitignore` 済み・`public/maplibre` と同じ扱い）で、
`web/scripts/copy-geo-assets.mjs` が `data/processed` から作る。単純なコピーではなく
JSON を読み直して詰めて書く（壊れた GeoJSON をビルド時に弾けること、と下の「アセットの実体」の件）。`predev` / `prebuild` に
繋いであるので `pnpm run dev` でも `pnpm run deploy` でも自動で走る。

**デプロイするマシンに `data/processed/*.geojson` が要る**（`public/geo/` に既に置いてあれば
警告だけ出して通る）。ASSETS の上限は 1 ファイル 25MiB・2 万ファイルなので、この 6.1MB は問題ない。
将来 GeoJSON が増えて毎回のデプロイに載せたくなくなったら R2 に移す。
その場合もバインディング経由の読みなので、外向きの HTTP にはならない。

キャッシュは `web/public/_headers` で `/geo/*` に `max-age=3600` を付けている
（エッジ側は Workers が自動でキャッシュする）。

## 前提

- Cloudflare アカウントと **Workers 有料プラン**。D1 は 1 データベース 10GB（有料）/ 500MB（無料）で、
  このデータは 1.3GB あるので無料プランには載らない。
- ローカルに原本 `data/db/ryuiki.sqlite` と `data/db/cells.sqlite`。
- `cd web && pnpm wrangler login`

## 手順

### 1. D1 を作って ID を差し替える

```bash
cd web
pnpm wrangler d1 create ryuiki
```

出てきた `database_id` を `web/wrangler.jsonc` に書く。今入っているのはローカル用の
プレースホルダ（`00000000-0000-4000-8000-000000000000`）で、ローカルでは使われないが本番では要る。

```jsonc
"d1_databases": [
  {
    "binding": "DB",
    "database_name": "ryuiki",
    "database_id": "＜ここに wrangler が出した UUID＞",
    "migrations_dir": "drizzle/migrations"
  }
]
```

書き換えたら型を作り直す。

```bash
pnpm run cf-typegen
```

### 2. 本番 D1 にスキーマを当てる

```bash
pnpm run db:migrate:remote     # wrangler d1 migrations apply ryuiki --remote
```

`d1_migrations` テーブルで適用済みを管理するので、何度実行しても足りない分だけ当たる。

### 3. データを入れる

ローカル D1 を作ってから、そこを .sql に書き出して本番へ流す。
**先にローカルを完成させる**（`docker compose up` を一度通していれば済んでいる）。

```bash
# 3-1. ローカル D1 を作る（済んでいれば飛ばす）
pnpm run build:derived     # 集計 DB。約 1 分
pnpm run db:setup          # マイグレーション + シード。約 1.5 分

# 3-2. 投入用 SQL を書き出す（dist/d1/ に 20MB 刻みで 90 本ほど・約 1 分）
pnpm run db:export

# 3-3. 本番へ流す。アップロードが散発的に落ちるのでファイル単位で再試行する
for f in dist/d1/*.sql; do
  echo "→ $f"
  ok=0
  for try in $(seq 1 12); do
    pnpm wrangler d1 execute ryuiki --remote --file="$f" -y >/dev/null 2>&1 && { ok=1; break; }
    echo "   retry $try/12"; sleep 10
  done
  [ "$ok" = 1 ] || { echo "!!! $f で停止"; break; }
done
```

全部で 30〜60 分かかる。失敗したファイルはサーバ側でロールバックされる
（`your DB will return to its original state`）ので、同じファイルの再試行は安全。

`dist/d1/` は連番になっていて、外部キーの親（`documents`）が先に来る。
順番に流すこと。途中で落ちたら、**そのファイルから**やり直せばよい（前のファイルは入り終わっている）。
同じファイルを二度流すと、主キーのあるテーブルはエラーで弾かれ、無いテーブルは黙って重複するので、
成功したものは飛ばす。

入り終わったら全テーブルの行数を突き合わせる。

```bash
pnpm run db:verify:remote      # ローカル D1 と本番 D1 の行数を全テーブルで比較
pnpm wrangler d1 info ryuiki   # サイズを見る。1.3GB 前後になるはず
```

### 4. 環境変数（AI Gateway / Mapbox）

`web/.env.local` は本番に届かない。AI アシスタントを動かすなら Workers 側に入れ直す。

ダッシュボード → AI → AI Gateway で Gateway を作り、Settings → Authentication で
**Authenticated Gateway** を有効にしてトークンを発行する。

```bash
pnpm wrangler secret put AI_GATEWAY_TOKEN        # cf-aig-authorization に載る。必ず secret
pnpm wrangler secret put AI_GATEWAY_ACCOUNT_ID   # 秘密ではないので wrangler.jsonc の vars でも可
```

`AI_GATEWAY_NAME`（既定 `default`）と `AI_MODEL`（既定 `workers-ai/@cf/moonshotai/kimi-k2.6`）は
既定値のままなら不要。変えるなら `wrangler.jsonc` に `"vars"` を足す。
`src/lib/ai/provider.ts` は `process.env` から読むが、OpenNext が起動時に Workers の
env（vars + secrets）を `process.env` に流し込むのでそのまま効く。
未設定でも `/api/chat` が 503 を返すだけで、他の画面は普通に動く。

`pnpm run preview`（workerd をローカルで動かす）では `.env.local` は読まれないので、
同じ値を `web/.dev.vars` に置く。

**`NEXT_PUBLIC_MAPBOX_TOKEN` は Workers の変数に入れても効かない。**
クライアント側（`src/lib/map/basemaps.ts`）で使うので Next がビルド時にバンドルへ埋め込む。
`pnpm run deploy` を実行するマシンの `web/.env.local` かシェル環境変数に置くこと。
無くても OpenStreetMap と地理院タイルで動く。

### 5. ビルドしてデプロイ

```bash
pnpm run deploy     # opennextjs-cloudflare build && opennextjs-cloudflare deploy
```

本番相当を手元で確かめたいときは、ローカル D1 に繋いだまま workerd で動かせる。

```bash
pnpm run preview    # opennextjs-cloudflare build && opennextjs-cloudflare preview
# → http://localhost:8787
```

### 6. 動作確認

```bash
BASE=https://ryuiki-demo.<your-subdomain>.workers.dev
for p in / /sites /timeseries /biota /documents /quality /explore /sources /map; do
  printf "%-13s " "$p"; curl -s -o /dev/null -w "%{http_code}\n" "$BASE$p"
done
for p in /api/quality "/api/biota?kind=effort" /api/geo/sites /api/geo/mesh /api/geo/events; do
  printf "%-28s " "$p"; curl -s -o /dev/null -w "%{http_code}\n" "$BASE$p"
done
```

`/geo/rivers.geojson` が 200 で返ること（4.5MB）も見ておく。404 なら `pnpm run prepare:geo` が
通っていない。本文 0 バイトの 500 なら上の「アセットの実体」を読むこと。

## 更新するとき

### スキーマを変えた

```bash
# 1. web/src/db/schema.ts を編集
pnpm run db:generate          # drizzle/migrations/NNNN_*.sql が増える
pnpm run db:migrate           # ローカルで当てて確かめる
pnpm run db:migrate:remote    # 本番へ
pnpm run deploy
```

`drizzle/migrations/*.sql` は手で書き換えない。`schema.ts` を直して生成し直す。

### 原本データが変わった

```bash
pnpm run build:derived        # 集計 DB を作り直す
pnpm run db:seed              # ローカル D1 に入れ直す（原本の変化を検出して自動で入れ直す）
pnpm run db:export
# 変わったテーブルのファイルだけ流す。全部入れ直すなら先に DELETE が要る:
#   pnpm wrangler d1 execute ryuiki --remote --command "DELETE FROM <table>"
```

本番 D1 の入れ直しは差分ではなく全消し→全入れになる。
入れ替え中に画面が壊れるので、止められない時期にやらない。
やり直したいだけなら [Time Travel](https://developers.cloudflare.com/d1/reference/time-travel/) で
直前の時点に戻せる（過去 30 日）。

### コードだけ変えた

```bash
pnpm run deploy
```

## 詰まりどころ（検証で分かったこと）

**一部のテーブルだけ本番へ足したいときは `--db` を使う。**
`web/scripts/export-d1-sql.mjs` は既定でローカル D1（`.wrangler/…`）を読むが、
`--db ../data/db/ryuiki.sqlite --table a,b,c` で原本から特定のテーブルだけ書き出せる。
1.2GB のローカル D1 を作り直さずに済む。水源マップの 8 テーブル（13,243 行 / 2.7MB）はこれで入れた。
列がマイグレーション後の本番と一致していることが前提。

```bash
cd web
pnpm run db:migrate:remote
node scripts/export-d1-sql.mjs --db ../data/db/ryuiki.sqlite --out dist/d1-water \
  --table water_utility,water_source,water_facility,water_source_doc,water_flow_edge,water_zone,water_zone_assignment,water_zone_source_share
for f in dist/d1-water/*.sql; do pnpm wrangler d1 execute ryuiki --remote --file="$f" -y || break; done
pnpm run deploy
```

**`wrangler d1 export` は大きいテーブルで落ちる。**
`wrangler d1 export ryuiki --local --output=all.sql` は全件をメモリ上で組み立てるので、
`organism_records`（82万行）でも DB 全体でも workerd の V8 がヒープ上限に当たって落ちる。

```
V8 fatal error; location = Reached heap limit; message = : allocation failed: JavaScript heap out of memory
```

`measurements`（31万行 / 220MB）までは通った。この境目に賭けたくないので、
`web/scripts/export-d1-sql.mjs` で 1 行ずつ流して書き出している。これが `pnpm run db:export`。

**Cloudflare のアセットは内容ハッシュで重複排除される。** 2026-09-02 に
`watersheds.geojson` の実体が壊れて、アセット配信が本文 0 バイトの 500 を返す状態になった。
`wrangler deploy` は同じハッシュのファイルを「already uploaded」として上げ直さないので、
再デプロイしても直らない。**別名で上げても直らない**（内容が同じなら同じ実体を指すため。
バイト同一のコピーを別パスに置いて 500、同じデータを再エンコードしたものは 200、と切り分けた）。
直すにはバイト列を変えるしかない。`copy-geo-assets.mjs` が JSON を詰めて書き出しているのは、
壊れた GeoJSON を弾く以外にこの逃げ道を確保する意味もある（`JSON.stringify` の出力は
入力が同じなら毎回同じなので、無駄な再アップロードは起きない）。

**`wrangler types` は既定で `CloudflareEnv` を作らない。** 素で実行すると `Env` という名前の
インターフェースを吐き、`getCloudflareContext()` が参照する `CloudflareEnv` が消えるので
ビルドが `Property 'DB' does not exist on type 'CloudflareEnv'` で落ちる。
`package.json` の `cf-typegen` は `wrangler types --env-interface CloudflareEnv` にしてある。

**SQL 文長はバイトで測る。** D1 の上限は 100KB。エクスポートは 64KB で切っているが、
この 64KB を**文字数**で数えていたせいで日本語の行（UTF-8 で 1 文字 3 バイト）が 190KB を超え、
本番投入で `statement too long: SQLITE_TOOBIG` になった。ローカルの SQLite にはこの上限が無いので、
書き出した .sql を復元して確かめる検証では気付けない。`Buffer.byteLength` で測ること。

**1 行だけで 100KB を超える行がある。** `vegetation_polygons.geometry_geojson`（10 行）と
`extraction_log`（6 行）。バッチをどう割っても 1 文に収まらないので、
`export-d1-sql.mjs` は大きい TEXT 列を空で INSERT してから
`UPDATE … SET col = col || '…'` で 8000 文字ずつ継ぎ足す。
追記先は主キーで特定し、主キーが無いテーブル（`extraction_log`）は分割しない列すべてで特定して、
一意にならなければエラーで止める。

**大きいファイルはアップロードで落ちる。** `wrangler d1 execute --remote --file` は
ファイルを R2 の署名付き URL に PUT してから取り込む。この PUT が 90MB のファイルではほぼ確実に
`fetch failed` になり（8 回再試行しても通らない）、20MB なら数回に 1 回の失敗で済む。
`export-d1-sql.mjs` の 1 ファイル上限を 20MB にしてあるのはこのため。
それでも散発的に落ちるので、投入ループは再試行つきで回すこと。

**SQL 文は 100KB まで。** エクスポートは複数行を 1 つの `INSERT ... VALUES (…),(…)` にまとめるが、
64KB で切って余裕を持たせている。1 ファイルは 20MB 上限（`--max-mb` で変えられる）。
`wrangler d1 execute --remote --file` 自体は 5GiB まで受けると書いてあるが、
実際にはアップロードが持たない（上を見ること）。

**バインドパラメータは 1 クエリ 100 個まで。** `IN (...)` は `web/src/lib/db.ts` の `queryChunked`
が 80 個ずつに割る。生の `query()` は 100 個を超えると例外を投げるので、新しいクエリを足すときに気付ける。

**`/explore` は全表スキャンする。** テーブル一覧の行数表示も任意 SQL も rows_read をそのまま食う。
公開 URL に置いてあるので、**2026-09-02 から閉じてある**。
スイッチは `web/src/lib/features.ts` の `EXPLORE_ENABLED` 1 つで、
画面・ナビ・概況のカード・`/api/sql`・`/api/table`・AI の「この SQL をデータ探索で開く」リンクが
まとめて切り替わる。開けるときは true にして `pnpm run deploy`。

`/api/schema` も同じフラグで閉じてある。テーブル一覧を出すのに 61 テーブルへ `count(*)` を投げるので、
1 リクエストで 419 万行読む一番重い口だった。画面からは呼んでいないので閉じても何も壊れない
（AI の `list_catalog` は HTTP を経由せず `listTables()` を直に呼ぶ）。

止まらないのは AI アシスタントの `run_sql` ツール（`src/lib/ai/tools.ts`）。
`/api/chat` 越しに同じ `runUserSql` を呼ぶので、このフラグの外にある。

**ローカル D1 の実体は 1.2GB のファイル。** `web/.wrangler/` に入る（gitignore 済み）。
docker で開発している間はコンテナ側のボリューム（`d1-state`）にあるので、
ホストの `web/.wrangler/` は消してよい。

## 参照

- [OpenNext for Cloudflare](https://opennext.js.org/cloudflare)
- [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- [D1 import / export](https://developers.cloudflare.com/d1/best-practices/import-export-data/)
- [Workers static assets](https://developers.cloudflare.com/workers/static-assets/)
