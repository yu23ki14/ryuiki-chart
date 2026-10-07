# MCP の外部カタログ検索（`find_datasets`）設計

- 状態: 設計（2026-10-07）/ 前提: `docs/plans/MCP_SOURCE_ACCESS.md`（以下「SA 設計」。`access.yaml`・`queryable_via`・`n_source_rows`・`get_records` の仕組み）が先にマージされること
- 関連: ADR-0014（応答封筒）・ADR-0028（ライセンスで絞らない）・`scripts/c01_ckan.py`・`c86_ckan_bodik_yokohama.py`・`c64_estat_kanagawa.py`・`c90_estat_shozaiki.py`

## 0. 要約
値を D1 に取り込んでいない外部ポータルの出典について、MCP から「どんなデータがあるか（定義）」と
「最新を取れる URL」を返す。値そのものは返さない（取りに行く先を返す）。

- 対象 6 出典: `ckan_kanagawa_pref`・`ckan_sagamihara`・`ckan_bodik_kanagawa`・`ckan_yokohama`（CKAN。データセット 2,259 件）、
  `estat_agri_census_kanagawa`・`estat_census_population_kanagawa`（e-Stat の統計表 6 件）。`estat_shozaiki_kanagawa`（境界 GIS 1 件）を足して e-Stat は 7 件（§1.1）。
- 材料はすべて `data/processed` に収穫済み。**新しい収集はしない**。D1 に 2 表（`external_dataset` 2,266 行・`external_resource` 23,251 行）を足す。
- ツールは `find_datasets`（MCP + AI）。入力は q・出典・組織・形式・更新日。出力は定義 + URL 3 種 + 収穫日。
- 「最新」は、**応答の中のメタデータ自体は古い**（収穫は 8/29〜8/30）ことを前提に、
  `package_show` の API URL を正として返す（§2.1）。実測で、収穫後に更新されたデータセットがあることを確認した（§5）。

## 1. D1 の表（決定事項 1）
### 1.1 実測（2026-10-07、`data/processed` を読んだだけ）
| ファイル | 行数 | 備考 |
|---|---|---|
| ckan_datasets.jsonl | 925 | kanagawa_pref 811 + sagamihara 114（相模原は同じファイルに有る。別版ではない） |
| ckan_datasets_bodik.jsonl / _yokohama.jsonl | 680 / 654 | |
| ckan_resources.jsonl | 9,568 | kanagawa_pref 7,750 + sagamihara 1,818 |
| ckan_resources_bodik / _yokohama | 2,831 / 10,845 | 計 **23,244**。url 空が 3 件（ckan 2・bodik 1） |
| e-Stat | 表 6（農林業センサス 5 + 国勢調査速報 1）+ 境界 1 | `estat_*.jsonl` は値の行（6,422/806/5,089）で、表の定義は持たない。表題は `table_ja`、ID は `source_ref` の statInfId |
| ckan_env_index.jsonl | 1,270 行（異なる resource 510） | うち 975 行が変換済み CSV。`kanagawa_pref_web` 75 行は CKAN 外（`web_` 始まり）で除く |

- 形式（`format`）は大文字化済み。`SHP,CSV` のようにカンマ区切りが混ざる（27 件）。空が 353+55 件。
- `notes` は収穫時に 800 文字で切ってある（c01）。切れていることを `description_truncated` で返す（長さ 800 ちょうどの行）。
- 組織・ライセンス・タグ・グループは文字列（`|` 区切り）。ライセンスが空のデータセットが神奈川県 84 件（相模原に多い）。

### 1.2 表の形（Drizzle。`web/src/db/schema.ts` に追加。v1 の「原本から来る表」の流儀）
`external_dataset`（PK `dataset_key`）
| 列 | 内容 |
|---|---|
| dataset_key | `<source_id>:<dataset_id>`（e-Stat は `<source_id>:<statInfId>`） |
| source_id | `ckan_kanagawa_pref` 等（instance → source_id の写像は c01/c86 の登録名に一致） |
| portal | `ckan` / `estat` |
| dataset_id / name | CKAN の UUID と URL 用の名前（e-Stat は statInfId と NULL） |
| title / description / description_truncated | |
| organization / license / license_url / groups / tags | |
| n_resources / metadata_modified | 収穫時点の値 |
| page_url | ページ（CKAN は `{base}/dataset/{name}`。e-Stat は §2.2） |
| api_url | CKAN は `package_show` の URL（§2.1）。e-Stat は NULL |
| fetched_at | `source_registry.fetched_at`（その出典の収穫日。行ごとの収穫日は無い） |
索引: `(source_id, metadata_modified)`・`organization`。

`external_resource`（PK `resource_key` = `<source_id>:<resource_id>`）
| 列 | 内容 |
|---|---|
| dataset_key | FK 相当（索引 `ix_er_dataset`） |
| name / format / size / last_modified | 収穫時点の値。`format` は大文字・カンマ区切りのまま |
| direct_url | 直リンク（url 空の 3 件は NULL） |
| page_url | CKAN は `{base}/dataset/{dataset_id}/resource/{resource_id}` |
| sheets_json | NULL か、`[{sheet, n_rows, n_cols, header:[...]|null}]`（§3） |
索引は `dataset_key`・`format`。

### 1.3 作り方: 新規 `scripts/m08_external_catalog.py`（原本 `ryuiki.sqlite` に書く）
- 先例は `m05_tier1.py`（processed を読んで ryuiki.sqlite の新設表へ。DDL は `scripts/schema_catalog.sql`、冪等＝出典ごとに DELETE→INSERT、
  入力が無い出典は黙って飛ばして最後に列挙）。書き手は m0x に限るという規約にも合う。
- 不採用: registry のビルド（r01）。レジストリは「語彙」の置き場で、23k 行の目録は語彙ではない。v2 のパイプラインにも載せない
  （b00 の全量ゲート・指紋は不要。`compute_v2_input_fingerprint` が見る原本 4 表に触れない）。
- e-Stat の 7 件の定義は、`m08` の中に定数で持つ（statInfId・表題・年・単位は c64/c90 のコードに既にある）。**表題は `estat_*.jsonl` の `table_ja` から引く**ので、
  statInfId と表題の食い違いは起きない。境界 GIS は `dlserveyId=A002005212020`・`code=14`（c90 の定数を import して使う）。
- `source_id` が必須。`sources` との対応は SA 設計の `access.yaml` の `catalog` 宣言（§5）で検査する。

### 1.4 容量・seed の時間
- 生で約 8〜9 MB（resource 23k 行 × 約 300 B + dataset 2.3k × 約 700 B + 索引）。D1（既存 340 万行超）に対して +0.7% の行数。
  本番 D1 の容量・書き込み行数の課金は 25k 行で無視できる。
- ローカル seed は better-sqlite3 の直 INSERT で秒単位。`web/scripts/seed-d1-local.mjs` の `SOURCES` は ryuiki.sqlite を既に読むので変更は無く、
  `web/src/lib/table-meta.ts` の `TABLE_ORIGIN` に 2 表（`main`）を足す。「44 表→46 表、シード対象 43→45」を `CLAUDE.md`・テストの数に反映する。

## 2. 「最新を取る URL」の組み立て規則（決定事項 2）
### 2.1 CKAN（4 インスタンス）
| 項目 | 規則 | 実測（2026-10-07、1 件ずつ叩いた） |
|---|---|---|
| base | kanagawa_pref `https://catalog.opendata.pref.kanagawa.jp`、sagamihara `https://opendata.city.sagamihara.kanagawa.jp`、bodik `https://data.bodik.jp`（c01 の `odcs.bodik.jp/kanagawa` は誤り。c86 の注記）、yokohama `https://data.city.yokohama.lg.jp` | 4 つとも 200・`success: true` |
| **api_url（正）** | `{base}/api/3/action/package_show?id={dataset_id}`（UUID。`name` は変わりうるので使わない） | 4 つとも 200。名前でも UUID でも引ける（bodik で両方確認）。存在しない ID は `success:false`（横浜で確認） |
| page_url | `{base}/dataset/{name}`（収穫済みの `url` と同じ） | 200 |
| resource page_url | `{base}/dataset/{dataset_id}/resource/{resource_id}` | bodik で 200 |
| 直リンク | package_show の `result.resources[].url` が**その時点の最新**。収穫済みの `direct_url` は参考 | 4 つとも `url` を持つ。相模原の一部は `.../download/.zip` のように名前が空（そのまま返す。直せない） |
- 応答の説明は固定文: 「最新の資源 URL・更新日は `api_url` の `result.resources[]` と `result.metadata_modified`。ここの値は `fetched_at` 時点」。
- 認証は不要（4 つとも匿名で 200）。
- BODIK の package_show には resource ごとに独自キー（ダウンロード数など）が付く。無視してよい。

### 2.2 e-Stat（3 出典・7 件）
| 項目 | 規則 | 実測 |
|---|---|---|
| ページ | `https://www.e-stat.go.jp/stat-search/files?stat_infid={statInfId}` | 200（表題は「農林業センサス …1 農業経営体数 \| ファイル」）。**c64 は appId 不要の file-download 経路** |
| 直リンク | `https://www.e-stat.go.jp/stat-search/file-download?statInfId={statInfId}&fileKind=0` | 200・octet-stream・185,344 B（000031511885） |
| 境界 GIS | ページ `https://www.e-stat.go.jp/gis/statmap-search?...`（`source_registry.url`）・データ `.../gis/statmap-search/data?dlserveyId=A002005212020&code=14` | データ URL は 200 |
| appId | **直リンクは appId・ログイン不要**。e-Stat API（`api.e-stat.go.jp` の `getStatsData`）を使うなら appId の登録が要る（c64 の冒頭・本設計では使わない） | |
- 依頼文は「API が appId を要する旨」だったが、取り込み経路は appId 不要の直リンクなので、`access` の欄に「直リンク=appId 不要／API=appId 要（本システムは API を使わない）」の 2 行で書く。
- statInfId が 7 件のため、**最新の版**（例: 農林業センサスの 2025 年版）が出ても自動では分からない。`note` に「新しい版は e-Stat の検索ページ（`source_registry.url`）で探す」と書く。

## 3. 列の定義（決定事項 3）
- **返せる**: 題名・説明・提供者・ライセンス・形式・更新日・サイズ・タグ・分野。
- **列は一部だけ**。`ckan_env_index` は resource 510 件（変換できたのは約 975 シート）で、CKAN 全 23k 資源の約 2%。
  しかも見出しの検出は信頼できない。実測（975 ファイルの 1 行目）: `needs_human=True` が 282、`col_0,col_1,…` や数値で始まる（見出し行が取れていない）ものがある。
  機械的な基準（1 行目の 3 分の 2 以上が `col_N`/`field_N`/数値でなく、`needs_human` が False）を満たすのは **495 シート・170 resource**。
  - 採用: 基準を満たすシートだけ `sheets_json.header` に入れる。満たさないシートは `header: null`（`n_rows`・`n_cols` は返す）。
  - **無いものは無いと返す**: `data_definition.columns` は `{status:"available"|"not_extracted", note}`。`not_extracted` の説明は「見出しを取り出していない。直リンクのファイルを開いて確認する」。
  - 列の意味・単位・型は返さない（元データに無い）。見出しは文字列のまま。
- e-Stat は `indicator_ja`・`unit_ja`・`area_level` の既存列（estat_*.jsonl の `DISTINCT`）から表ごとに `indicators`（上位 20）・`unit_ja` を `m08` が組み立てて `sheets_json` に入れる。値は返さない。
- ckan_env の出力 CSV（`data/processed/ckan_env/`、2.2 GB）は D1 に入れない。`output_path` も返さない（ローカルの内部パス）。

## 4. ツール `find_datasets`（決定事項 4）
### 4.1 入力（MCP は `.strict()`・z.tuple 不使用。AI は既定）
| 引数 | 型 | 意味 |
|---|---|---|
| `q` | string（UTF-8 で 48 バイトまで。`get_records` と同じ検査） | title・description・tags・groups の部分一致（`LIKE ? ESCAPE '\'`。空白区切りは AND で 3 語まで） |
| `source_id` | enum（`FIND_DATASET_SOURCE_IDS`。生成物） | 出典で絞る |
| `organization` | string（48 バイトまで） | 組織名の部分一致（例「厚木市」） |
| `format` | enum（CSV/XLSX/XLS/PDF/ZIP/SHP/GEOJSON/JSON/HTML/TXT/XML） | 資源に 1 つでも含めば。カンマ区切りは要素で照合（部分一致にしない） |
| `modified_since` | `YYYY-MM-DD` | `metadata_modified` が以降。**収穫時点の値で比べる**（§6） |
| `id` | string | `dataset_key` の完全一致（1 件取り。資源を全件返す） |
| `include_resources` | boolean（既定 false） | 一覧で資源を返すか。**false の間は資源の数と形式の件数だけ**。true は `limit` が 10 以下のときだけ |
| `limit` / `offset` | 既定 20・最大 100 / 0 以上 | ページング。並びは `metadata_modified` 降順・`dataset_key` 昇順（固定） |
- 少なくとも `q`・`source_id`・`organization`・`format`・`modified_since`・`id` のどれか 1 つが要る（全件取りを拒否）。

### 4.2 出力
`buildDataEnvelope(query, { rows, offset, n_total? }, [source_id…], { caveats, truncated })`。`provenance` は**結果に出てくる出典のみ**（`ckan_*`・`estat_*`）。
`n_total` は `q` なしのとき `count(*)`（最大 2,266 行。軽い）。`q` ありは `limit+1` 件読んで `truncated`。`excluded` は 0（ADR-0028）。
行の形:
```
{ dataset_key, source_id, title, description, description_truncated, organization, license, license_url, tags[], groups[],
  n_resources, formats: {CSV: 3, PDF: 1}, metadata_modified, fetched_at,
  urls: { api_package_show, page, resources?: [{name, format, size, last_modified, direct_url, page_url}] },
  data_definition: { columns: {status, note}, sheets?: [...] },
  access: { auth: "none"|"appId_for_api_only", how_to_get_latest: "<固定文。§2>" } }
```
- 出典の注意書き（caveat）は registry の source facet から引く（出典ごとの分岐を書かない）。
- 入力検査は `McpInputError`。**e-Stat と CKAN は同じ形**にそろえる（e-Stat の `api_package_show` は null、`access.auth` が異なる）。
- AI 側にも足す。`web/src/lib/ai/tools.ts` に共通関数 `findDatasets` を呼ぶ `find_datasets` を 1 つ（`get_records` と同じ。strict にしない）。`prompt.ts` は変えない（`__snapshots__`）。

## 5. `queryable_via` と `access.yaml`（決定事項 5）
`queryable_via: ["find_datasets"]` を書く出典（7 件。SA 設計の C 区分から B 相当へ移る。C は 92→86 件、`catalog_only` 理由は消える）:
| source_id | 件数（`n_source_rows`） | SA 設計での既定理由 |
|---|---|---|
| ckan_kanagawa_pref | 811 | catalog_only |
| ckan_sagamihara | 114 | catalog_only |
| ckan_bodik_kanagawa | 680 | catalog_only |
| ckan_yokohama | 654 | catalog_only |
| estat_agri_census_kanagawa | 5 | file_only |
| estat_census_population_kanagawa | 1 | file_only |
| estat_shozaiki_kanagawa | 1 | file_only（表→出典の宣言で `get_records` にできれば併記） |
- `n_source_rows` の意味は**「目録の件数（データセット数）」**。`n_source_rows_basis` に `catalog_datasets` を足す（SA の `source_rows`/`registry_record_count`/`none` の 4 つ目）。
  e-Stat 2 件の値の行数（6,422 など）は返さない（取り違え防止）。

宣言（SA 設計 §1.2 の `sources:` に第 3 の形を足す）:
```yaml
sources:
  ckan_kanagawa_pref: {catalog: external_dataset}   # records/reason と排他。catalog を持つ出典は find_datasets
  ckan_yokohama:      {catalog: external_dataset}
  estat_agri_census_kanagawa: {catalog: external_dataset}
```
`r01` の検査: ①`catalog` の表は `external_dataset`/`external_resource` のみ ②宣言した出典の `external_dataset` が 1 行以上（原本あり）
③`external_dataset.source_id` の種類が宣言と一致（宣言漏れ・過剰を止める）④`records`/`reason` との重複禁止。変異（宣言から 1 件消す・行の無い出典を足す）で止まることを確かめる。
SA の「`reason` の出典に行がある宣言は止める」検査は `external_*` を対象外にする（表に `source_id` はあるが、これは目録であり値ではない）。

## 6. 収集が古くなる問題と更新手順（決定事項 6）
- 実測: 収穫（8/27〜8/28）後に `metadata_modified` が動いたものを確認した。BODIK `142123_51662`: 収穫 2026-08-27 → 現在 2026-09-24。相模原 `todokede_eigyo`: 現在 2026-09-28
  （収穫は 8/29）。**メタデータは月単位で古くなる**。だから `api_url` を正にし、`fetched_at` を毎行返す。
- 返す: 各行の `fetched_at`・`metadata_modified`、`access.how_to_get_latest`。`modified_since` は収穫時点の値で比べるので、検索の説明文に「更新日は fetched_at 時点」と書く。
- 更新手順（`docs/PIPELINE.md` に 1 節足す。パイプラインではない運用手順）: `c01_ckan.py`（県・相模原。bodik は誤り base なので失敗して飛ばす）→
  `c86_ckan_bodik_yokohama.py`（bodik・横浜。河川データの取得も走るので重い。**目録だけ回したいときの `--catalog-only` を c86 に足すか**は決めかね。§8）→
  `m08_external_catalog.py` → `pnpm run db:export` → 本番反映（§7）。頻度は目安で四半期ごと。自動化はしない。
- 失敗の見え方: `m08` は入力 jsonl の mtime を最後に表示し、30 日超なら警告（止めない）。

## 7. 実装の分け方・受け入れ・検証・本番（決定事項 7・8）
### 7.1 担当 A（データ）: `m08`・表・宣言
触る: `scripts/m08_external_catalog.py`（新規）・`scripts/schema_catalog.sql`（新規）・`web/src/db/schema.ts`・`web/drizzle/migrations/`（`pnpm run db:generate`）・
`web/src/lib/table-meta.ts`・`registry/source/access.yaml` と `r01` の検査（SA の担当 A と同じファイル。**SA がマージ済みである前提**）・`scripts/tests/test_m08_external_catalog.py`（新規）。
- 受け入れ: ①`external_dataset` が 2,266 行（kanagawa_pref 811・sagamihara 114・bodik 680・yokohama 654・e-Stat 7）、`external_resource` が 23,251 行（url 空の 3 件は `direct_url` NULL）。
  ②`dataset_key`・`resource_key` が一意、全 resource の `dataset_key` が dataset に有る。③CKAN の `api_url`/`page_url` が規則（§2.1）どおり（4 インスタンスの各 1 件で文字列一致を検査）。
  ④`sheets_json` に header が入るのは基準を満たす 495 シートだけ（基準はテストで固定）。⑤再実行で行数が変わらない（冪等）。⑥§5 の検査が変異で止まる。
- 速い検証: `.venv/bin/python3 -m pytest scripts/tests/test_m08_external_catalog.py`（processed の抜粋でなく原本の jsonl を使うが読むだけ。数秒）、`.venv/bin/python3 scripts/m08_external_catalog.py`。
  原本の無い環境（CI）では jsonl が無いので skip する（`data/*` は gitignore 済み。縮小サンプルの対象は §8）。

### 7.2 担当 B（ツール）: `find_datasets`
触る: `web/src/lib/catalog-search.ts`（新規。入力スキーマ・SQL 組み立て・`findDatasets`）・同テスト・`web/src/lib/mcp/tools-find-datasets.ts`（新規）・同テスト・`web/src/lib/ai/tools.ts`（1 件登録）。
MCP の `tools.ts` は触らない（SA の A が 1 行で登録）。SQL は固定の形のみ（出力列も許可リスト。`SELECT *` 無し。`IN (...)` は使わず `queryChunked` 不要）。
- 受け入れ: ①インメモリ SQLite に 2 表を作り、6 出典の各 1 件を入れて、**`FIND_DATASET_SOURCE_IDS` の全件で `find_datasets` が 1 行以上**返し、`urls.api_package_show`（CKAN）または `urls.page`（e-Stat）が非空。
  ②`q`・`format`（`SHP,CSV` の要素一致で `CSV` に当たり、`HTML` に当たらない）・`organization`・`modified_since` の各絞り込み。③条件なしは入力エラー。未知のキー（strict）・長すぎる `q`・`include_resources` と `limit>10` の併用はエラー。
  ④`limit`/`offset` で重複・欠落が無い。⑤`header: null` のシートは `columns.status="not_extracted"`。⑥`include_resources:false` の応答が 100 件で 200KB 以内。
- 速い検証: `cd web && pnpm vitest run src/lib/catalog-search.test.ts src/lib/mcp src/lib/ai`・`pnpm tsc --noEmit`。サンプル DB に 2 表が無いのでインメモリで足す。

### 7.3 統合（main）と本番反映
- SA の結合テスト（全出典を回して `queryable_via` の各ツールが 1 行以上返す）に `find_datasets` を含める。`describe_catalog` の `summary.by_tool` に `find_datasets: 7`。
- PR 直前に 1 回だけ全量の vitest・pytest。b00 は回さない。
- 本番: **マイグレーション 1 本**（`external_dataset`・`external_resource`）。流す表は 2 表（25.3k 行）と、SA の `source_access` の入れ直し。
  順序: `m08` → ローカル `db:setup` で行数確認 → `wrangler d1 migrations apply --remote` → `db:export` の該当 INSERT を `wrangler d1 execute --remote --file`（`d1 export` 不使用）→ `pnpm run deploy`。
  反映後 curl 1 回: `find_datasets(source_id=…, limit=1)` を 6 出典で。ロールバックは Worker を戻す（表は残して無害）。

## 8. 決めかねた点（メインの判断が要る）
1. **列の定義の期待値**。実際に返せるのは CKAN 約 23k 資源のうち 170 件程度（約 0.7%）。大半は「無い」と返す。
   これで足りるか、足りないなら全資源の 1 行目取得が要る（外部への大量 HTTP＝収集になり、本設計の範囲外）。
2. **`metadata_modified` が古い問題**。静的な目録は月単位で古い。リクエスト時に `package_show` を Worker から叩いて補正する案（外部 HTTP を MCP が打つ。他ツールは打たない・失敗時の扱い・レート）は不採用にしたが、
   「最新の更新日」を謳うなら要る。本設計は URL を返して利用者側に取らせる。
3. **c86 に `--catalog-only` を足すか**。足すと更新手順が軽くなるが c86 の変更が要る（本 PR の範囲を超える）。足さないなら四半期ごとに河川データの取得も走る。
4. **対象の広げ方**。G空間情報センター（`geospatial_jp_*_catalog` 3 件。CKAN で同じ形）・`ckan_env_bulk`・`ckan_pdf_*` は本 PR に入れない。広げるときは `m08` に instance を足すだけ（収穫済みの jsonl が有るかは未確認）。
5. **e-Stat の最新版の追跡**は手作業のまま（§2.2）。statInfId が変わる版（2025 農林業センサス等）は別途 c64 の更新が先。
6. **縮小サンプル（`data/sample`）に 2 表を入れるか**。入れると CI で `find_datasets` の結合テストが回るが、`s02_materialize_sample.py` の対象追加と凍結スナップショットの更新（`--mode diff`）が要る。
   本設計はインメモリのテストで足りるとして入れない。
7. **収穫日 `fetched_at` は出典単位**（行ごとでない）。c01 は全件上書きなので実害は小さいが、bodik と県（8/29・8/30）で値が異なる。
8. **ライセンスが空の 84 件**（神奈川県・相模原）。そのまま `license: null` で返し、除外しない（ADR-0028）。`caveat` を足すかは SA の caveat 方針に合わせる。

## メインの判断（2026-10-07）
前提: PR #82（出典の状態 `registry/source/access.yaml`・`source_access`・describe_catalog の queryable_via・get_records・get_observations の source_ids）は main に入り、本番反映済み。新ツールはこの上に乗せる。access.yaml の現在の形（`record_sets` など）に合わせて `catalog:` を足すこと。
1. 列の定義: 見出しを検出できたもの（約 0.7%）だけを、根拠（`columns_basis`）つきで返す。それ以外は null（不明）。推測しない。
2. サーバー（Worker）から package_show を叩いて更新日を補正しない。`api_url` と `fetched_at` を返し、最新の確認は利用側に任せる。
3. c86 の `--catalog-only` は今回は足さない。
4. G空間情報センター等への対象の拡大はしない。
5. 縮小サンプルに2表の数行を入れ（s01 の閉包か coverage.yaml）、CI で検査されるようにする。
6. ライセンスが空の行（84 件）は除外せず、license を null（不明）として返す。

## 実装メモ（2026-10-07、実装担当）
設計どおりに実装した。差が出た点だけ書く。
- 件数: `external_dataset` 2,266（県 811・相模原 114・BODIK 680・横浜 654・e-Stat 7）、`external_resource` 23,251（url 空 3 件は `direct_url` NULL）。設計の見込みと一致。
- 見出しを検出できたシート: §3 の「495 シート・170 resource」は `kanagawa_pref_web`（CKAN 外の `web_` 始まり。目録に載らない）の 44 シートを含んでいた。
  目録に載る資源で数えると **452 シート・148 resource**（基準は同じ `header_is_reliable`）。
- `description_truncated`: 収穫物の `notes` の最大長は 587 文字で、800 文字で切れた行は 0 件（列は設計どおり持つ）。
- e-Stat は表題・statInfId を `estat_*.jsonl` から引き、国勢調査の表題（jsonl に `table_ja` が無い）と境界 GIS の URL は `m08` の定数。
  c64/c90 は `requests`・`shapely` が要るので import せず、`test_m08_external_catalog.py` が文字列の一致を固定する。
- `sheets_json` の e-Stat は `header`＝指標（出現順・上位 20。`header_basis: harvested_indicators`）と `units`。値は持たない。
- `find_datasets` の `format` 絞りは `instr(',' || format || ',', ',CSV,')`。資源は `json_each(?)`（バインド 1 個）で取る。
- r01 の検査: `catalog` は `external_dataset` だけ。`records`/`reason` と排他。出典の過不足は `external_dataset.source_id` の種類との一致で止める。
- 本番反映後、`access.yaml`・`registry` を触ったので `reports/serving_fingerprint.json`（b00）と `data/sample/manifest.json` の原本 sha256 は、
  m08 を流した本物の `ryuiki.sqlite` で作り直す（原本が変わるため）。

## レビュー反映（2026-10-07、修正担当）
- 起動手順: `ensure-registry.sh` が、`external_dataset` が無い・空のときだけ `m08_external_catalog.py --if-empty` を先に回す（入力も無ければ直し方を書いて止まる）。r01 が目録の空を理由に止まって `db:setup` が通らない状態を避ける。
- registry の鮮度: `external_dataset` は `source_id` 列を持つ小さい表なので、指紋の出典別の件数（`_hash_source_access_counts`）に既に入っている。m08 の流し直しで件数が変われば古いと判定される（テストで固定）。
- 件数の上限: 資源は 1 データセット 50 件（`resources_truncated`・`n_resources`・`next_resource_offset`。続きは `id` + `resource_offset`）。MCP の応答は 96KB（行を先頭から減らし `truncated`・`next_offset`）。AI は `makeResult` の行単位モード（`headRows`）で、入れ子の資源を間引かない。
- format: 原文は `external_resource.format` に残し、正規化（前後の空白・先頭の `.` を除く・大文字・XLSK→XLSX・JPG→JPEG）した要素ごとの行を `external_resource_format` に持つ。`format` 絞りはその表への等号。許可リストは実在する 19 形式。
- `modified_since`: `metadata_modified` が NULL の行は除き、`excluded_no_modified` で件数を返す。存在しない日は弾く。`n_total` は offset=0 のときだけ。`n_with_header` は m08 がデータセットの列に持つ（`sheets_json` は展開しない）。
