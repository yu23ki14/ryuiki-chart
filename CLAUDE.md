# 流域カルテ デモ

- パッケージマネージャは **pnpm**。スクリプトは `pnpm run <name>`、ローカルの CLI は `pnpm wrangler ...` で呼ぶ。
  `pnpm deploy` は pnpm 組み込みのコマンドで package.json の `deploy` は動かないので、必ず `pnpm run deploy`。
- Web アプリは `web/`（Next.js 16 / App Router / TypeScript / Tailwind v4）。詳細は `web/README.md`。
- デプロイ先は Cloudflare Workers（`@opennextjs/cloudflare`）。手順と未解決点は `DEPLOYMENT.md`。
- 開発環境は `docker compose up`（リポジトリ直下）。起動時に「集計 DB 生成 → 語彙レジストリ生成 →
  D1 マイグレーション → シード」を、まだのものだけ実行する。ホストで直接動かすときは
  `cd web && pnpm run build:derived && pnpm run db:setup && pnpm run dev`
  （`db:setup` は `predb:setup` フックで語彙レジストリも「無ければ作る」。`web/scripts/ensure-registry.sh`）。
- データの置き場所は **Cloudflare D1**（デプロイ先を Cloudflare 想定にしたため）。
  61 テーブルを 1 つの D1 に統合してある。D1 に `ATTACH` は無いので `d.` / `c.` の接頭辞は使わない。
  どの原本から来たテーブルかは `web/src/lib/table-meta.ts` の `TABLE_ORIGIN`。
- D1 のスキーマは `web/src/db/schema.ts`（Drizzle）が原本。触ったら `pnpm run db:generate` で
  `web/drizzle/migrations/` を作り直す。マイグレーション SQL を直接書き換えない。
- 原本は `data/db/ryuiki.sqlite` と `data/db/cells.sqlite`。**読み取り専用**で扱う
  （この規約は `web/` 側から見たものであり、書き手は `scripts/m0x_*.py` に限る）。
  集計は `data/db/derived.sqlite` に分けて書く（`cd web && pnpm run build:derived` で再生成）。
  この 3 ファイルが D1 シードの入力になる（`web/scripts/seed-d1-local.mjs`）。
- 地図の GeoJSON は `web/public/geo/`。`data/processed` から `pnpm run prepare:geo` が写す生成物で、
  `predev` / `prebuild` に繋いである（`.gitignore` 済み）。Workers に fs は無いので `fs` で読まない。
  河川はブラウザが `/geo/rivers.geojson` を直接取り、流域界は `web/src/lib/geo.ts` が
  `/geo/watersheds.geojson` を ASSETS バインディング経由で読んで D1 の集計を載せる。
  コピーではなく JSON を詰めて書き出す（Cloudflare のアセットは内容ハッシュで重複排除されるので、
  実体が壊れたときバイト列を変えられる逃げ道が要る。経緯は `DEPLOYMENT.md`）。
- D1 はバインドパラメータが 1 クエリ 100 個まで。`IN (...)` を書くときは
  `web/src/lib/db.ts` の `queryChunked` を使う。生の `query()` は 100 個で例外を投げる。
- 語彙（指標・単位・注記・和名・zone）の正は `registry/` 配下のファイルで、web からは
  `web/src/lib/registry/`（`generated.ts`/`generated-client.ts` が再生成物、`lookup.ts`/
  `lookup-client.ts` が読み出し層。画面は `lookup-client.ts` の `caveatBody`/`shortVariable`/
  `speciesLabel` や `generated-client.ts` の `VARIABLE_NOTE` 等を直接 import する）経由で読む。
  画面ごとに個別対応を書かない。`web/src/lib/domain.ts` は Phase B で撤去済み
  （`docs/plans/PHASE_B_INTAKE.md` #6）。日付書式の混在・定量下限の 0 潰しのような
  レジストリの語彙ではないデータの癖は、それを使う画面・モジュール側（例:
  `municipality` 列に水域名が入っている件の表示名は `web/src/lib/municipality.ts`、
  `measurements.quality_stage` 等の3値は `web/src/lib/quality.ts` の `QUALITY_STAGES`）に
  1箇所だけ置く。複数画面が同じ値を使うときは、その1箇所から import する。
- 本番 D1 への投入は `pnpm run db:export` が書き出す .sql を `wrangler d1 execute --remote --file` に流す。
  `wrangler d1 export` は大きいテーブルで OOM するので使わない。
- 画面と API の出し分けは `web/src/lib/features.ts` の 1 ファイル。`EXPLORE_ENABLED` が false の間、
  `/explore`・`/api/sql`・`/api/table`・`/api/schema` は閉じている（任意 SQL と全表スキャンが公開 URL に出るため）。
  画面ごとに条件を散らさない。
- チャートの配色は `web/src/components/viz/palette.ts` に集約。検証済みの値以外を足さない。
- AI アシスタントの多段ツール呼び出しの上限は `web/src/app/api/chat/route.ts` の `MAX_STEPS`。
  最後の1ステップは「ツールを外して答えを書かせる」ために予約してある。この予約を外すと
  探索でステップを使い切ったときに本文ゼロで正常終了し、「Streaming は Done なのに答えが出ない」に戻る。
  それでもモデルが答えないことがあるので、`web/src/lib/ai/stream-guard.ts` を streamText の出口に噛ませて
  ツール呼び出しの生トークン（`<|tool_call…|>`）の除去・空の本文パートの破棄・打ち切り注記の付与をしている。
- 未データ化ソースの棚卸しと難易度分けは `docs/UNDATAFIED_TIERS.md`。
  Tier 1 は収集済み（`scripts/c80`〜`c88`）で、`scripts/m05_tier1.py` がアプリモデルに流す。
  台帳・区域・メッシュ型のデータ用に `protected_areas` / `vegetation_polygons` / `mammal_mesh` /
  `wildlife_sightings` / `river_segments` を新設した（DDL は `scripts/schema_tier1.sql`）。
  API は `/api/nature?kind=...` と `/api/geo/{protected-areas,vegetation,river-segments}`。
- 収集スクリプトの User-Agent に個人名・個人アドレスを入れない（`scripts/common.py`）。
  経緯は `docs/COLLECTOR_CONTRACT.md` の追記を読むこと。
- 新しいエリア（東京都・沖縄県・兵庫県など）を足すときは `docs/add_area.md` の手順に従う。
  方式（単一 D1 + `region_id`）は `docs/adr/0002-multi-region.md` で決定済みで蒸し返さない。
- Phase B（ADR-0016）の縦に薄い1本は `scripts/b03_build_observation.py`（`measurements`→
  `observation`）/ `scripts/b04_build_cube.py`（`observation`→キューブ `observation_agg`）/
  `scripts/b05_project_v1.py`（キューブ→v1形）の3本。出力は `data/db/v2.sqlite`
  （`observation`/`observation_agg`）と `data/db/v1_projection.sqlite`
  （`meas_daily`/`meas_month`/`meas_year`）で、どちらも `.gitignore` 済み・捨てて作り直せる。
  設計・実測は `docs/plans/PHASE_B_FACT_SLICE.md`。
- **キューブ（`observation_agg`）を作るのは SQLite 3.43 以降でなければならない**
  （`b04_build_cube.py` が起動時に検証して止める。`AVG()`/`SUM()` の加算アルゴリズムが
  3.43 で変わり、それより前だと平均値が黙って変わる行がある。見るのは `sqlite3` CLI では
  なく Python 同梱の `sqlite3` モジュールのバージョン。詳細は `docs/adr/0021-observation-grain-and-cube-key.md`）。

## 開発フロー

- あなたの役割はシステムの設計と最終的な受け入れ基準の設定を含む意思決定に責任を持つこと。
- あなた自身はコードを書かない。全て実装はSonnetエージェントに任せる。
- 設計や実装をある程度終わった段階で不安要素が残るときは、アドバイザーとしてFableサブエージェントに聞くことも大切です。
- 一度方針が決まったら毎回私に質問せず、PRを出すところまでやってください。方針に曖昧さがあるときは最初に質問をして、決めてください。
- PRはエージェントに任せるのではなく自分でだし、出す前には/code-reviewと/simplifyのスキルをつかって整えることを忘れないでください。

## worktree の運用

サブエージェントを並行させるときは git worktree を使う。以下は実際に事故った/踏んだものだけを書いている。

- **`git add -A` / `git commit -a` を使わない。パスを明示して add する。**
  worktree は `.claude/worktrees/` に作られ、**リポジトリの中**にあるので `-A` で index に入る
  （実際に入った。コミットまでは至らなかった）。`.gitignore` に `.claude/` を足して塞いであるが、
  ユーザーが手で編集した無関係なファイルを巻き込む事故は防げないので、明示的な add を徹底する。
- **worktree には `data/db` が無い。** `data/*` は `.gitignore` 済みなので worktree にも clone にも
  入らない。集計や突合を走らせるなら symlink を張る:
  `ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db <worktree>/data/db`
- **原本を移動・退避しない。** `data/db/ryuiki.sqlite`(828MB) と `cells.sqlite`(42MB) は
  「100MB 超のため別配布」で `scripts/c*.py` から再生成できない（`derived.sqlite` だけは
  `pnpm run build:derived` で作り直せる）。読み取り専用（`file:...?mode=ro`）でのみ開く。
- **「原本の無い環境」（CI の再現）は worktree ではなく一時ディレクトリへの `git clone` で作る。**
  `data/*` が gitignore 済みなので、原本が存在しない状態が非破壊で作れる。`actions/checkout` と同じ。
  原本を `/tmp` に退避して CI を再現しようとするな（掃除されうるし、途中で死ねば戻らない）。
- **stash は worktree 間で共有される。** bare の `git stash` / `git stash pop` を使わない
  （他のセッションの stash を pop しうる）。退避が要るなら WIP コミット。
- **使い終わったら片付ける。** `git worktree remove <path>` のあと、worktree 用に作られたブランチ
  （`worktree-agent-*`）も消す。`git worktree list` で残骸が無いことを確認する。
