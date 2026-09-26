# 流域カルテ デモ

- パッケージマネージャは **pnpm**。スクリプトは `pnpm run <name>`、ローカルの CLI は `pnpm wrangler ...` で呼ぶ。
  `pnpm deploy` は pnpm 組み込みのコマンドで package.json の `deploy` は動かないので、必ず `pnpm run deploy`。
- Web アプリは `web/`（Next.js 16 / App Router / TypeScript / Tailwind v4）。詳細は `web/README.md`。
- デプロイ先は Cloudflare Workers（`@opennextjs/cloudflare`）。手順と未解決点は `DEPLOYMENT.md`。
- 開発環境は `docker compose up`（リポジトリ直下）。起動時に「集計 DB 生成 → 語彙レジストリ生成 →
  v2（キューブ）生成 → D1 マイグレーション → シード」を、まだのものだけ実行する。ホストで直接動かすときは
  `cd web && pnpm run build:derived && pnpm run db:setup && pnpm run dev`
  （`db:setup` は `predb:setup` フックで語彙レジストリも v2 も「古ければ作り直す」。
  `web/scripts/ensure-registry.sh` が `scripts/r01_build_registry.py --check-fresh` を呼び、
  `web/scripts/ensure-v2.sh` が v2（`data/db/v2.sqlite`。`observation_agg`/`occurrence_agg` の
  キューブ。Issue #48 PR-0）を「(1) mtime が、読み取る原本・入力・パイプラインのコードより
  古い、または (2) `scripts/check_v2_fresh.py`（0=新鮮/10=古い。`pipeline_fingerprint.spec_version`
  が今のパイプラインの spec と一致するか）が古いと言う」の**どちらか**で判定する（OR。
  (1) だけでは mtime は新しいが中身が古い形式の v2.sqlite を見逃すため）。単体で作り直すだけなら
  `cd web && pnpm run build:v2`（r01→b03→b04→b06→b09→b07 を順に回す）。
- データの置き場所は **Cloudflare D1**（デプロイ先を Cloudflare 想定にしたため）。
  83 テーブル（`web/drizzle/migrations/` 適用後の実測。うちシード管理用の内部表
  `_seed_state` を除く82表が `web/scripts/seed-d1-local.mjs` のシード対象）を 1 つの D1 に
  統合してある。D1 に `ATTACH` は無いので `d.` / `c.` の接頭辞は使わない。
  どの原本から来たテーブルかは `web/src/lib/table-meta.ts` の `TABLE_ORIGIN`。
- D1 のスキーマは `web/src/db/schema.ts`（v1、既存表）・`web/src/db/schema-registry.ts`
  （語彙レジストリ、Phase A）・`web/src/db/schema-cube.ts`（キューブ、Issue #48 PR-0）の
  3ファイル（Drizzle。`web/drizzle.config.ts` の `schema` が3つとも読む）が原本。触ったら
  `pnpm run db:generate` で `web/drizzle/migrations/` を作り直す。マイグレーション SQL を
  直接書き換えない。
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
- Phase B（ADR-0016）の縦に薄い1本は `scripts/b03_build_observation.py`（`measurements`・
  `sensor_timeseries`・土地利用CSV〔P-1b、`data/processed/nlni_l03b_landuse_by_watershed.csv`、
  `_ingest_landuse`〕の3出典→`observation`）/ `scripts/b04_build_cube.py`（`observation`→
  キューブ `observation_agg`。土地利用を足しても無変更）/ `scripts/b05_project_v1.py`
  （キューブ→v1形）の3本。出力は
  `data/db/v2.sqlite`（`observation`/`observation_agg`）と `data/db/v1_projection.sqlite`
  （13テーブル: `meas_daily`/`meas_month`/`meas_year`/`meas_clim`/`site_var`/`var_catalog`/
  `sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/`zone_clim`/
  `landuse_watershed`/`landuse_change`）で、どちらも
  `.gitignore` 済み・捨てて作り直せる。設計・実測は `docs/plans/PHASE_B_FACT_SLICE.md`
  （土地利用は `docs/plans/PHASE_B_LANDUSE.md`）。土地利用は区分ごとの面積・セル数を
  別々の variable にし、region は `scripts/migrate/source_regions.yaml`
  （`consumer='observation'`。occurrence 側〔下記〕と consumer で宣言を分ける）から決める。
  生物の出現（occurrence、O-1a/O-1b/O-2a）は別の縦線。**実行順は
  b06 → b09 → b07 → b08**（b09/b07 は互いに依存しないので入れ替え可能）:
  `scripts/b06_build_occurrence.py`（`organism_records`→`occurrence`。
  `data/db/v2.sqlite` に `observation`/`observation_agg` と同居）/
  `scripts/b09_build_occurrence_place.py`（O-2a。`occurrence` の座標を
  `data/processed/nlni_w12_watersheds.geojson`〔W12流域、377面〕へ純 Python の
  点内包判定〔`scripts/migrate/point_in_polygon.py`〕で直接解決し、記録×place の
  サテライト `occurrence_place` を作る。同じ `data/db/v2.sqlite` に同居）/
  `scripts/b07_build_occurrence_cube.py`（`occurrence`→キューブ
  `occurrence_agg`。同じ `data/db/v2.sqlite` に同居）/
  `scripts/b08_project_occurrence_v1.py`（`occurrence`/`occurrence_agg`/
  `occurrence_place`→v1形12テーブル: `org_norm`・`org_group_year`・
  `effort_year`・`species2`・`species_year2`・`species_month`・`mesh_year`・
  `mesh_all`・`mesh_species`・`species_mesh_year`・`org_watershed_year`・
  `org_watershed`〔後者2つは O-2a、`occurrence`+`occurrence_place` だけから
  ——`occurrence_agg` は経由しない〕、出力 `data/db/v1_projection_occurrence.sqlite`）
  の4本。設計・実測は `docs/plans/PHASE_B_OCCURRENCE.md`・
  `docs/adr/0025-occurrence-fact-and-cube.md`・
  `docs/adr/0026-occurrence-place-watershed.md`。
- watershed の属性（`watershed_meta`・`watershed_rollup`）は
  `scripts/b11_project_place_v1.py`（`watershed_rollup` は
  `v1_projection.sqlite`〔b05〕/`v1_projection_occurrence.sqlite`〔b08〕を
  ATTACH して結合するだけの D10型の射影。キューブのセルにはしない）。
  **b11 はこの縦線で初めて別系統（observation・occurrence）の出力を読むので、
  実行順は r01 の後、b05・b08 を先に済ませてから b11**（b05・b08 は互いに
  依存しないので入れ替え可能）。出力は `data/db/v1_projection_place.sqlite`
  （`.gitignore` 済み・捨てて作り直せる）。
  設計・実測は `docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`。
  別枠で `scripts/b10_project_documents_v1.py`（`cells.sqlite`/`ryuiki.sqlite` を直接
  ATTACH、`observation` は経由しない）が `data/db/v1_projection_documents.sqlite`
  （`doc_series`/`doc_series_meta`/`quality_monthly` の3テーブル、`.gitignore` 済み）を作る。
  設計・実測は `docs/plans/PHASE_B_DOCUMENTS.md`。
- Phase B の v1 派生33表**全て**の突合を1コマンドで確認するゲートは
  `scripts/b02_run_all_gates.py`（`scripts/reconcile/projection_manifest.yaml`
  の対応表を読んで5つの candidate ファイルを回す。`b02_derived_compare.py` 自体は無変更）。
  設計・実測は `docs/plans/PHASE_B_RECONCILIATION.md` §12。
- レッドリスト・外来種の評価（`taxon_assessment`、P-2）は
  `scripts/registry/build_taxon_assessment.py`（`ryuiki.redlist_assessments`
  〔3版〕と `data/processed/moe_ias_list.csv`〔外来種、`ryuiki.taxa` ではなく
  L1 を直読み〕→ `registry.sqlite` の `taxon_assessment`。**D1 には載せない**。
  外来種の表示名〔`vernacular_name_ja_resolved`〕は `ryuiki.taxa` から
  ここで解決する——v1（`taxa`）は3出典〔`kanagawa_redlist.csv`→
  `moe_redlist.csv`→`moe_ias_list.csv`〕をまたいだ和名の畳み込みをしており、
  moe_ias_list.csv単体では再現できないため）が r01 の `taxon`（A-4）の直後に
  作る。v1形への射影は2本に分かれ、**どちらも `registry.sqlite` だけを読み、
  `ryuiki.sqlite` には一切触れない**: `scripts/b12_project_taxon_v1.py`
  （`taxon_assessment` → `redlist_map`/`redlist_change`、出力
  `data/db/v1_projection_taxon.sqlite`）と、`scripts/b08_project_occurrence_v1.py`
  に足した `ias_species`（`org_norm` の binom と結合するため occurrence の
  縦線側に同居）。除外7種の宣言は
  `registry/taxon/assessment_scope_exclusions.yaml`。設計・実測は
  `docs/plans/PHASE_B_TAXON_ASSESSMENT.md`。
- **`+09:00` 付きの時刻文字列に SQLite の日時関数（`date`/`datetime`/`strftime`）を使わない**
  （UTC に正規化されて日付が1日ずれる。`observation.period_start` は時刻帯なしのローカル時刻で
  持つ。詳細は `docs/adr/0024-local-time-and-time-labels.md`）。
- **キューブ（`observation_agg`/`occurrence_agg`）・v1形への射影・`doc_series`
  （`AVG()`/`SUM()`、または `occurrence_agg` 側は `FULL OUTER JOIN`
  〔`assert_grouped_totals_match`〕を使う）を作るのは SQLite 3.43 以降でなければ
  ならない**（`b04_build_cube.py`/`b05_project_v1.py`/`b07_build_occurrence_cube.py`/
  `b08_project_occurrence_v1.py`/`b10_project_documents_v1.py` それぞれの
  構築・射影関数の先頭（モジュール読み込み時点ではない）で `scripts/migrate/common.py` の
  `require_sqlite_version()` を呼んで検証する。加算アルゴリズムが3.43で変わり、
  それより前だと平均値が黙って変わる行がある（`FULL OUTER JOIN` は3.39未満だと
  そもそも使えない）。見るのは
  `sqlite3` CLI ではなく Python 同梱の `sqlite3` モジュールのバージョン。詳細は
  `docs/adr/0021-observation-grain-and-cube-key.md`）。
- **段階間の指紋**（`scripts/migrate/common.py` の `record_stage_fingerprint`/
  `assert_stage_fingerprint_fresh`/`track_reads`）: `b04`/`b05`/`b07`/`b09`/
  `b08`/`b11` は上流の段の出力が今も一致するか（(a)、系譜を再帰的に(b)）・
  実際に読んだ表を検証し忘れていないか（読み取りの機械監査）を読み込み時に
  確認し、崩れていれば止まる。設計・実測は `docs/plans/PHASE_B_FACT_SLICE.md` 参照。
- `b05_project_v1.py` の出典固有の検証関数群は
  `scripts/migrate/v1_projection_checks.py`（`v1_projection_checks.関数名(...)` で呼ぶ）。
- テスト・検証戦略は4層（フィクスチャ・縮小サンプル・全量の実行証明・段階間の指紋）。
  詳細は `docs/adr/0027-test-and-verification-strategy.md`。パイプラインのパス
  （`scripts/b0*.py`/`b1*.py`・`scripts/migrate/`・`scripts/reconcile/`・`scripts/registry/`
  等、`scripts/b00_run_full_gate.py` の `PIPELINE_*` 参照）を触ったら、原本のある手元で
  `.venv/bin/python3 scripts/b00_run_full_gate.py` を回して `reports/full_gate_proof.json`
  を更新し、一緒にコミットすること（CI の `full-gate-proof-check` が鮮度を検査する）。
  サンプルの展開スクリプト（`scripts/s02_materialize_sample.py`）は手元の本物の
  チェックアウト・worktree では絶対に実行しない（安全装置はあるが、CLAUDE.md
  「worktree の運用」に従い一時ディレクトリへの git clone で試すこと）。

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
- **worktree には `data/db` が無い。`data/db` 自体をまるごと symlink しない。**
  `data/*` は `.gitignore` 済みなので worktree にも clone にも入らないが、`data/db` は
  読み取り専用の原本（ryuiki/cells/derived）だけでなく、`scripts/r01_build_registry.py`
  が書く `registry.sqlite` や `scripts/b03〜b05_*.py` が書く `v2.sqlite`/`v1_projection.sqlite`
  のような**生成物の置き場でもある**。ディレクトリごと symlink すると、worktree からの
  ビルドが元のチェックアウトの生成物を上書きする（実際に踏みかけた事故）。
  読み取り専用の原本・入力ファイルだけを1ファイルずつ symlink し、生成物は worktree 内の
  実ファイルに書かせる:
  ```
  mkdir -p <worktree>/data/db <worktree>/data/processed
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db/ryuiki.sqlite  <worktree>/data/db/ryuiki.sqlite
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db/cells.sqlite   <worktree>/data/db/cells.sqlite
  ln -s /home/yu23ki14/cfj/ryuiki-demo/data/db/derived.sqlite <worktree>/data/db/derived.sqlite
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
  ```
  レジストリのビルド先を明示したいときは `RYUIKI_REGISTRY_DB=<worktree の絶対パス>/data/db/registry.sqlite`
  （`scripts/r01_build_registry.py` / `web/scripts/build-registry-ts.mjs` /
  `web/src/lib/registry/generated.test.ts` が見る環境変数。既定でも worktree 内の
  `data/db/registry.sqlite` を指すので、並行して複数 worktree を動かす等で明示したいときだけでよい）。
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
