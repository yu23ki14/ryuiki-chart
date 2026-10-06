# 流域カルテ デモ

- パッケージマネージャは **pnpm**。スクリプトは `pnpm run <name>`、ローカルの CLI は `pnpm wrangler ...` で呼ぶ。
  `pnpm deploy` は pnpm 組み込みのコマンドで package.json の `deploy` は動かないので、必ず `pnpm run deploy`。
- Web アプリは `web/`（Next.js 16 / App Router / TypeScript / Tailwind v4）。詳細は `web/README.md`。
- デプロイ先は Cloudflare Workers（`@opennextjs/cloudflare`）。手順と未解決点は `DEPLOYMENT.md`。
- 開発環境は `docker compose up`（リポジトリ直下）。起動時に「水源マップの GeoJSON 生成 → 語彙レジストリ生成 →
  v2（キューブ）生成 → D1 マイグレーション → シード」を、まだのものだけ実行する。ホストで直接動かすときは
  `cd web && pnpm run db:setup && pnpm run dev`
  （`db:setup` は `predb:setup` フックで語彙レジストリも v2 も「古ければ作り直す」。
  `web/scripts/ensure-registry.sh` が `scripts/r01_build_registry.py --check-fresh` を呼び、
  `web/scripts/ensure-v2.sh` が v2（`data/db/v2.sqlite`。`observation_agg`/`occurrence_agg` の
  キューブ。Issue #48 PR-0）を `scripts/check_v2_fresh.py`（0=新鮮/10=古い/それ以外=判定不能）
  一本で判定する——`pipeline_fingerprint.spec_version` の一致に加えて、読み取り専用の原本
  4表（`measurements`/`sensor_timeseries`/`organism_records`/`sites`、代理指標）・
  `data/processed` の入力2つ・`registry.sqlite` 自身の指紋・v2 パイプラインのコード
  （import で機械的に洗い出す）の中身が「最後にビルドしたとき」と一致するかを見る
  （`scripts/migrate/common.py` の `compute_v2_input_fingerprint()`/
  `check_v2_pipeline_fresh()`。手書きの mtime 走査は撤去した）。単体で作り直すだけなら
  `cd web && pnpm run build:v2`。
- データの置き場所は **Cloudflare D1**（デプロイ先を Cloudflare 想定にしたため）。
  44 テーブル（`web/drizzle/migrations/` 適用後の実測。うちシード管理用の内部表
  `_seed_state` を除く43表が `web/scripts/seed-d1-local.mjs` のシード対象）を 1 つの D1 に
  統合してある。D1 に `ATTACH` は無いので `d.` / `c.` の接頭辞は使わない。
  どの原本から来たテーブルかは `web/src/lib/table-meta.ts` の `TABLE_ORIGIN`。
- D1 のスキーマは `web/src/db/schema.ts`（v1、既存表）・`web/src/db/schema-registry.ts`
  （語彙レジストリ、Phase A）・`web/src/db/schema-cube.ts`（キューブ、Issue #48 PR-0）の
  3ファイル（Drizzle。`web/drizzle.config.ts` の `schema` が3つとも読む）が原本。触ったら
  `pnpm run db:generate` で `web/drizzle/migrations/` を作り直す。マイグレーション SQL を
  直接書き換えない。
- 原本は `data/db/ryuiki.sqlite` と `data/db/cells.sqlite`。**読み取り専用**で扱う
  （この規約は `web/` 側から見たものであり、書き手は `scripts/m0x_*.py` に限る）。
  かつての集計 DB `derived.sqlite`（v1 の派生33表）は Issue #48 PR-5 で撤去した。無い。
  `build:derived` は `build:water-geo`（水源マップの GeoJSON だけ）に改名した。
  D1 シードの入力（`web/scripts/seed-d1-local.mjs` の `SOURCES`）はこの2ファイルに加えて
  `registry.sqlite`（語彙レジストリ）・`v2.sqlite`（キューブ。上記の `ensure-v2.sh` が作る）
  の計4ファイル。
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
  `municipality` 列に水域名が入っている件の表示名は `web/src/lib/municipality.ts`）に
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
  API は `/api/geo/{protected-areas,vegetation,river-segments}`（`/api/nature` は Issue #61 で撤去）。
  `mammal_mesh` / `wildlife_sightings` は画面・API の読み手が無く、AI の run_sql / describe_schema 用の台帳表として D1 に残している。
- 収集スクリプトの User-Agent に個人名・個人アドレスを入れない（`scripts/common.py`）。
  経緯は `docs/COLLECTOR_CONTRACT.md` の追記を読むこと。
- 新しいエリア（東京都・沖縄県・兵庫県など）を足すときは `docs/add_area.md` の手順に従う。
  方式（単一 D1 + `region_id`）は `docs/adr/0002-multi-region.md` で決定済みで蒸し返さない。
- **データパイプライン**（Phase B / Issue #48）の詳細は `docs/PIPELINE.md`。パイプラインを触る作業では該当する節だけ読む。要点:
  - 実行順: r01 → b03 → b04 → b06 → b09 → b07 → b13（ここまでが `pnpm run build:v2`）。b07 は b09 の出力を読むので b09 が先。
  - v1 は撤去済み（PR-5）。検証は層2＝`cd web && pnpm run serving:snapshot -- --mode snapshot`（サンプルの凍結スナップショット `data/sample/serving_snapshot.json` との一致。CI の sample-gate）、層3＝b00 が書く `reports/serving_fingerprint.json`。スナップショットを更新する PR には `--mode diff` の before/after 表を貼る（`docs/plans/V2_SERVING*.md`、ADR-0027・0029）。
  - **`+09:00` 付きの時刻文字列に SQLite の日時関数を使わない**（日付が1日ずれる。ADR-0024）。
  - **キューブ・射影を作るのは Python 同梱の SQLite 3.43 以降**（`scripts/migrate/common.py` の `require_sqlite_version()`。ADR-0021）。
  - パイプラインのパス（`scripts/b00_run_full_gate.py` の `PIPELINE_*`）を触ったら、原本のある手元で `.venv/bin/python3 scripts/b00_run_full_gate.py` を回し `reports/serving_fingerprint.json` を一緒にコミットする（CI が鮮度を検査）。
  - `scripts/s02_materialize_sample.py` は本物のチェックアウト・worktree で絶対に実行しない（一時ディレクトリへの clone で）。
  - テスト・検証戦略は ADR-0027。

## 開発フロー

- あなたの役割はシステムの設計と最終的な受け入れ基準の設定を含む意思決定に責任を持つこと。
- あなた自身はコードを書かない。全て実装はSonnetエージェントに任せる。
- 設計や実装をある程度終わった段階で不安要素が残るときは、アドバイザーとしてFableサブエージェントに聞くことも大切です。
- 一度方針が決まったら毎回私に質問せず、PRを出すところまでやってください。方針に曖昧さがあるときは最初に質問をして、決めてください。
- PRはエージェントに任せるのではなく自分でだし、出す前には/code-reviewと/simplifyのスキルをつかって整えることを忘れないでください。

### 速く回すための規則

1本の PR に半日以上かかった経験（「直す→全量で確かめる→レビュー→直す」を直列に何周も回した）から決めた規則。

- **重い検証は PR を出す直前に1回だけ回す。** 数分以上かかる検証（`b00` の全量ゲート、変異込みの差分計測、
  CI の clone 再現など）は、途中の修正のたびに回さない。途中では、触った箇所に絞った速い検証
  （該当するテストファイルだけ、対象の問い合わせ・表だけ、変異なし）で確かめる。
- **全量で回す前に、検証が本番の経路を通っているかを先にレビューする。** 突合・差分の道具が、画面や API が
  実際に呼ぶ関数ではなく、道具の中の書き直しを検証していると、全量で緑でも意味がない。しかも発覚が遅れ、
  作り直しになる。統合の最初にこれを確かめてから全量を回す。
- **並行できるものは並行する。** ファイルが衝突しない単位に切って worktree で同時に進める。統合後の修正も、
  独立した論点は別の担当に分ける。
- **/code-review と /simplify は同時に回し、指摘をまとめて1回で直す。** 指摘ごとに「直す→全量で確かめる」を
  繰り返さない。
- **サブエージェントへの指示に役割の境界を書く。** 実装担当には「スキル（/simplify・/code-review 等）や
  サブエージェントを起動しない」、レビュー担当には「ファイルを変更しない・コミットしない」を毎回明記する
  （実装担当が /simplify を自走させ、レビュー用の分身が修正・全量実行・コミットまで進めたことがある）。
- **同じ重いコマンドを並行で走らせない。** 同じ worktree で同じ全量処理が複数走ると、資源の取り合いで
  かえって遅くなり、生成物も競合する。
- **生成物は入力が変わったときだけ作り直す。** 鮮度判定（`ensure-*.sh`・`--check-fresh`）があるものは
  それに任せ、worktree ごと・修正ごとに無条件に作り直さない。

### トークンを節約するための規則

1本の PR に数百万トークンを使い、週の上限に当たった経験（2026-09-27、Issue #48 PR-2〜PR-3b）から決めた規則。
原因は、エージェントの起動が多いこと・各エージェントが長い資料を丸ごと読み直すこと・長く走るエージェントの文脈が
膨らむこと・メインのセッション自体が長すぎることだった。

- **PR ごとに新しいセッションで始める。** 前の PR の経緯は Issue のコメント（申し送り）と `docs/plans/` に残し、会話の履歴に頼らない。
- **エージェントは少数・大きめの単位で。** 1本の PR で起動するのは、設計1・実装（並行）2〜4・統合と修正1・レビュー2（/code-review と /simplify を同時）を目安にする。小さな修正のためだけに新しいエージェントを起動しない（直前の担当に SendMessage で続けさせる）。
- **読ませる資料を絞る。** 指示には「読むべき節」をファイル名と節番号で明示し、設計書・ADR・ソースを丸ごと読ませない。設計書は実装担当ごとの節に分けて書く。
- **重い処理（全量ゲート・serving snapshot/fingerprint の全量・build:v2・CI の clone 再現）はエージェントに待たせない。** メインが裏で1回だけ回し、結果だけを確かめる。エージェントには速い検証（該当テスト・`--only`）だけを許す。
- **Fable は設計判断に迷ったときだけ。** 前例のある PR の設計は Sonnet に任せる。Fable に実データの計測をさせない（計測が要るなら Sonnet に）。
- **レビューは安く。**
  - /simplify は4観点を**1本のレビュー担当**にまとめて頼む（スキル既定の4並列にしない）。/code-review は `medium` を既定にする。
  - レビューの対象から生成物（`web/drizzle/migrations/meta`・`reports/`・`data/sample/`・`generated*.ts`）を外す。
  - レビュー担当には読むだけを頼み、実データの計測・全量実行・ビルドをさせない（性能の疑いは「疑わしい SQL と理由」まで。計測はメインか修正担当が1回）。
  - 修正後に差分全体を再レビューしない。直した箇所だけを、直した担当のテストとメインの確認で済ませる。
  - 1本の PR でレビューを回すのは原則1回。2回目は、1回目の修正で設計が変わったときだけ。
- **メインの応答を短く。** 途中経過の通知（「まだ作業中」）には応答しないか1行で済ませる。

## worktree の運用

サブエージェントを並行させるときは git worktree を使う。以下は実際に事故った/踏んだものだけを書いている。

- **`git add -A` / `git commit -a` を使わない。パスを明示して add する。**
  worktree は `.claude/worktrees/` に作られ、**リポジトリの中**にあるので `-A` で index に入る
  （実際に入った。コミットまでは至らなかった）。`.gitignore` に `.claude/` を足して塞いであるが、
  ユーザーが手で編集した無関係なファイルを巻き込む事故は防げないので、明示的な add を徹底する。
- **worktree には `data/db` が無い。`data/db` 自体をまるごと symlink しない。**
  `data/*` は `.gitignore` 済みなので worktree にも clone にも入らないが、`data/db` は
  読み取り専用の原本（ryuiki/cells）だけでなく、`scripts/r01_build_registry.py`
  が書く `registry.sqlite` や `scripts/b03〜b13_*.py` が書く `v2.sqlite`
  のような**生成物の置き場でもある**。ディレクトリごと symlink すると、worktree からの
  ビルドが元のチェックアウトの生成物を上書きする（実際に踏みかけた事故）。
  読み取り専用の原本・入力ファイルだけを1ファイルずつ symlink し、生成物は worktree 内の
  実ファイルに書かせる:
  ```
  mkdir -p <worktree>/data/db <worktree>/data/processed
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db/ryuiki.sqlite  <worktree>/data/db/ryuiki.sqlite
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db/cells.sqlite   <worktree>/data/db/cells.sqlite
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/taxon_crosswalk.csv \
        <worktree>/data/processed/taxon_crosswalk.csv
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/nlni_w12_watersheds.jsonl \
        <worktree>/data/processed/nlni_w12_watersheds.jsonl
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/nlni_w12_watersheds.geojson \
        <worktree>/data/processed/nlni_w12_watersheds.geojson
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/nlni_l03b_landuse_by_watershed.csv \
        <worktree>/data/processed/nlni_l03b_landuse_by_watershed.csv
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/moe_ias_list.csv \
        <worktree>/data/processed/moe_ias_list.csv
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/processed/taxon_gbif_accepted.csv \
        <worktree>/data/processed/taxon_gbif_accepted.csv
  ```
  レジストリのビルド先を明示したいときは `RYUIKI_REGISTRY_DB=<worktree の絶対パス>/data/db/registry.sqlite`
  （`scripts/r01_build_registry.py` / `web/scripts/build-registry-ts.mjs` /
  `web/src/lib/registry/generated.test.ts` が見る環境変数。既定でも worktree 内の
  `data/db/registry.sqlite` を指すので、並行して複数 worktree を動かす等で明示したいときだけでよい）。
- **原本を移動・退避しない。** `data/db/ryuiki.sqlite`(828MB) と `cells.sqlite`(42MB) は
  「100MB 超のため別配布」で `scripts/c*.py` から再生成できない。読み取り専用（`file:...?mode=ro`）でのみ開く。
- **「原本の無い環境」（CI の再現）は worktree ではなく一時ディレクトリへの `git clone` で作る。**
  `data/*` が gitignore 済みなので、原本が存在しない状態が非破壊で作れる。`actions/checkout` と同じ。
  原本を `/tmp` に退避して CI を再現しようとするな（掃除されうるし、途中で死ねば戻らない）。
- **stash は worktree 間で共有される。** bare の `git stash` / `git stash pop` を使わない
  （他のセッションの stash を pop しうる）。退避が要るなら WIP コミット。
- **使い終わったら片付ける。** `git worktree remove <path>` のあと、worktree 用に作られたブランチ
  （`worktree-agent-*`）も消す。`git worktree list` で残骸が無いことを確認する。
