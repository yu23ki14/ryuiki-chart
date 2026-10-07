# MCP の出典アクセス: 状態の開示と汎用読み出し（`get_records`）設計

- 状態: 設計（2026-10-07）/ ブランチ: `feat/mcp-source-access`
- 関連: ADR-0014（応答封筒）・ADR-0020（update_mode）・ADR-0028（座標・ライセンスで絞らない）・
  `docs/UNDATAFIED_TIERS.md`・`docs/plans/KANAGAWA_EDNA.md`（`get_edna` の先例）

## 0. 要約
登録簿の出典は 125 件。実測の内訳（2026-10-07、`data/db/*.sqlite` を読み取り専用で数えた）:

| 区分 | 件数 | 内容 |
|---|---|---|
| A. 既にツールで値が取れる | 15 | 観測 11（`get_observations`。manifests の target=observation）・出現 4（`get_occurrences`。うち kanagawa_edna は `get_edna` も） |
| B. D1 に行があるが値を返すツールが無い | **18** | 本 PR で `get_records` で取れるようにする（§3） |
| C. 取れない | 92 | 91 件 + `synthetic_sensor`（行はあるが意図的に出さない）。理由を機械的に付ける（§2.2） |

「123 件中 9 件」の誤りは、モデルが一覧を自分で数えたため。`describe_catalog(sources)` に
**集計済みの `summary`**（総数・ツール別件数・取れない理由別件数）を載せ、数えさせない。

方針: `get_records` は任意 SQL ではない（出典 enum × 宣言済みの表 × 許可リストの列だけ。§3.3）。
状態・件数はリクエスト時に数えず、ビルドで事前計算する（§1）。ライセンスでは除外しない（§4。ADR-0028 との食い違いは §7-1）。

## 1. 出典ごとの状態をどう作るか（決定事項 1）
### 1.1 推奨: 宣言（YAML）+ ビルドで検査 + 件数だけ事前計算

比較:

| 案 | 長所 | 短所 |
|---|---|---|
| (a) リクエスト時に数える | 常に最新 | 125 出典 × 大表。`occurrence_agg` 145 万行。rows_read 課金・遅い。**不採用** |
| (b) b13 の後ろに新ステップ（v2 に置く） | v2 の件数も取れる | パイプライン経路が増え b00 全量ゲート・指紋の再取得が要る。r01→v2 の順序とも循環しやすい。**不採用** |
| **(c) YAML 宣言 + r01（レジストリのビルド）で原本と突き合わせ + 静的に配る** | 既存の流儀（manifests・`OCCURRENCE_SOURCE_IDS`）と同じ。リクエスト時は D1 を読まない | 件数はビルド時点の値（`counted_at` を載せる） |

(c) を採る。構成:

1. **宣言**: 新規 `registry/source/access.yaml`（人が書く。§1.2）。
2. **自動で決まるもの（宣言しない）**: manifests の `target: observation` → `get_observations`、
   `target: occurrence` → `get_occurrences`。既存の生成物 `OCCURRENCE_SOURCE_IDS` と同じ作り方で
   `OBSERVATION_SOURCE_IDS` も生成する。A の 15 件は YAML に書かない（二重管理を避ける）。
   kanagawa_edna の `get_edna` だけは YAML の `extra_tools` で足す。
3. **ビルド**: `scripts/registry/build_source.py` に `source_access` の組み立てを足す
   （新規 `scripts/registry/build_source_access.py` に切り出してよい）。出力:
   - registry.sqlite の新表 `source_access`（125 行）。列: `source_id`・`state`（`queryable`/`not_queryable`）・
     `queryable_via`（JSON 配列）・`tables`（JSON 配列。`get_records` の表）・`n_rows`・`n_rows_basis`・
     `counted_at`・`reason`・`reason_note`。
   - `web/scripts/build-registry-ts.mjs` が `generated-source.ts` に `SOURCE_ACCESS` を出す
     （`SOURCE_META` と同じ作り方。**ツールは D1 を読まない**）。
   - D1 にも 125 行入る（Drizzle: `web/src/db/schema-registry.ts` に表を足し `pnpm run db:generate`）。
4. **件数 `n_rows`**: 原本 `ryuiki.sqlite` の `source_id` 別の行数。観測系は `measurements` + `sensor_timeseries`、出現系は `organism_records`・`edna_reads`・`wildlife_sightings`、
   B は §3.2 の表。原本に行が無い A の出典（nlni_l03b_landuse_by_watershed は processed の CSV 由来）は
   `source_registry.record_count` を使い `n_rows_basis: "registry_record_count"` とする。
   C は `null`（0 と区別する）。`n_rows_basis` は `source_rows`/`registry_record_count`/`none`。
   **キューブの集計行数（145 万行）は出さない**（読み手が「記録の件数」と取り違える）。
5. **鮮度**: `r01_build_registry.py --check-fresh` の入力に `access.yaml` と、数えた原本の表の行数指紋を足す
   （足し忘れると宣言を直しても古い registry.sqlite が「新鮮」と判定される）。

### 1.2 宣言 `registry/source/access.yaml` の形
```yaml
reasons:                      # 理由コードの語彙（コードリスト。build が未知のコードを拒否）
  not_collected: {ja: "未収集（取得手段が未着手、または登録のみ）"}
  blocked_access: {ja: "ログイン・APIキー・利用アンケートが必要で自動取得できていない"}
  pdf_document: {ja: "PDF の文書のまま。表として取り出していない"}
  map_service: {ja: "地図サービス（WebGIS）。値は外部サービス側にある"}
  external_api: {ja: "外部 API・CGI。値は提供元に問い合わせる"}
  catalog_only: {ja: "データ目録（メタデータ）で、観測値・記録そのものではない"}
  license: {ja: "利用条件が不明のため取得していない"}
  file_only: {ja: "収集済みだが D1 に投入していない（ファイルのみ）"}
  superseded: {ja: "別の出典に置き換わった（superseded_by 参照）"}
  synthetic: {ja: "合成データ。実データと混ぜないため出さない"}
sources:                      # A の 15 件は書かない（manifests から決まる）
  dams_kanagawa: {records: [sites]}
  kanagawa_redlist: {records: [taxa, redlist_assessments]}
  nlni_a10_natparks: {reason: file_only, note: "data/processed に 4 ファイル。D1 の表は無い"}
  ckan_pdf_choju_higai: {reason: pdf_document}
  ...                         # C の 92 件は reason 必須。note は任意（人が読む補足）
extra_tools: {kanagawa_edna: [get_edna]}
```

規則: `records` を持つ出典は B、`reason` を持つ出典は C。どちらも持たない・両方持つ・manifests と重複する、はビルドが止まる。

### 1.3 C の理由の初期割り当て（担当が `source_registry` の category/access_method/format から下書きし、人が確認）
| 理由 | 目安（機械的な当たり） |
|---|---|
| `not_collected` | `access_method='not_collected'`（nlni_w07・a03・p05）、`record_count=0` かつ processed・raw ともに 0 |
| `blocked_access` | 「利用アンケートフォーム経由」「要ユーザー登録」「APIキー」（moni1000_lake_*・waterfowl・wetland、gsi_kiban_chizu_joho、resas_api、ikilog、snet_kahaku） |
| `pdf_document` | `format` が PDF（ckan_pdf_*・kasen_kokusei_sagami・tanzawa_shika_suigen_docs・biodic_6th・sagami_seibi_keikaku_mirror 等） |
| `map_service` | biodic_webgis、biodic_kiban_datalist |
| `external_api` | mlit_river_hydro（CGI）、kanagawa_dam_mizugame・miyagase_storage_status（動的 JSON・現況スナップショット） |
| `catalog_only` | ckan_*（目録）、geospatial_jp_*catalog/plateau/pointcloud |
| `license` | `ylist`（「利用条件が不明のため」未取得）。ほかは `redistributable=0` かつ未収集のものを人が確認 |
| `file_only` | processed のファイルがあり D1 に表が無い（nlni_a10/a15/a45/w05/w12*・l03b_2006/2016、osm_*、estat_*、gsj_*、moni1000 の収集済み、soramame_stations 等） |
| `superseded` | `gbif_kanagawa`（`gbif_kanagawa_occurrences` に置換） |
| `synthetic` | `synthetic_sensor`（行はあるが出さない） |

`file_only` と他の区別は processed の有無（`nodata.txt`。`processed>0` ⇒ `file_only`）。

### 1.4 宣言とデータの食い違いを機械で止める
| 検査 | 場所 | 条件 | 結果 |
|---|---|---|---|
| 全出典が状態を持つ | `r01`（原本不要） | `source` 125 件 = manifests 由来 15 + `records` 18 + `reason` 92（重複・漏れ無し） | 止める |
| 語彙 | `r01` | `reason`・表名が語彙/許可リストに有る | 止める |
| 「D1 に行がある」宣言に行が無い | `r01`（原本あり） | `records` の (出典, 表) の行数が 0 | 止める |
| 「取れない」宣言なのに行がある | `r01`（原本あり） | `reason` の出典が、source_id 列を持つ全表のどれかに 1 行以上ある（`synthetic_sensor` だけ宣言で許可） | 止める（宣言が古い） |
| `queryable_via` が実際に動く | TS テスト（§5.2） | 全件を回し 1 行以上 | 落とす |
| 原本の無い環境（CI） | - | 原本依存の検査は skip（`test_registry_source.py` と同じ流儀）。静的検査だけ回る | - |

## 2. describe_catalog / search_registry の出力（決定事項 1 続き）
### 2.1 各行の形（`sourceRow()` に足す。`search_registry` の source にも同じ形で付く）

```
{ ...既存（source_id, source_edition_id, fetched_at, update_mode, age_days, name, publisher, superseded_by),
  queryable_via: string[],          // 例 ["get_records"] / ["get_occurrences","get_edna"] / []
  records_tables: string[],         // get_records の table 引数に渡す値（無ければ []）
  n_rows: number|null, n_rows_basis: "source_rows"|"registry_record_count"|"none", counted_at: string|null,
  unavailable_reason: string|null,  // 理由コード。queryable_via が空のとき必須
  unavailable_reason_ja: string|null, unavailable_note: string|null }
```

### 2.2 `summary`（モデルに数えさせない）
`what:"sources"` の応答に追加: `summary: { total, queryable, not_queryable, by_tool: {get_observations: 11, get_occurrences: 4, get_edna: 1, get_records: 18}, by_reason: {...} }`。
`by_tool` は重複あり（kanagawa_edna と kuma_sightings は 2 ツール）なので `queryable`（重複なし）と別に出す。
任意の `queryable: boolean` で絞れる（125 件は 1 回で返る）。`description` に「件数は summary を使う。数えない」と書く。

## 3. 汎用ツール `get_records`（決定事項 2・4）
### 3.1 入力（`.strict()`。z.tuple 不使用。MCP のみ strict、AI は既定）

| 引数 | 型 | 意味 |
|---|---|---|
| `source_id` | enum（B の出典のみ。生成物 `RECORD_SOURCE_IDS` から） | 必須 |
| `table` | enum | 出典に表が複数あるときだけ必須。1つなら省略可。誤った組み合わせは `McpInputError` |
| `id` | string | 主キーの完全一致（1 件取り） |
| `q` | string（LIKE の部分一致、UTF-8 で 48 バイトまで。edna と同じ検査） | 表ごとに宣言した検索列（名称・和名・学名）だけ |
| `include_geometry` | boolean | `geometry_geojson` を返す。`id` 指定時だけ許す（§3.3） |
| `limit` / `offset` | int（既定 100・最大 500 / 0 以上） | ページング。`truncated` のとき offset を進める |

列の絞り込み・並べ替え・範囲指定は持たない（要る例が見つかってから足す）。並びは主キー昇順で固定。

### 3.2 対象 18 件（出典 → 表 → 行数 → 公開する列）
行数は原本 `ryuiki.sqlite` の実測（本番 D1 はシードで同数。`source_id` で数えたもの。D1 の実数は実装担当が §6 で確認）。

| # | source_id | 表 | 行数 | ライセンス class |
|---|---|---|---|---|
| 1 | dams_kanagawa | sites | 4 | unconfirmed |
| 2 | env_kousui_stations_kanagawa | sites | 290 | open_terms |
| 3 | jma_stations_kanagawa | sites | 12 | open_terms |
| 4 | moni1000_sites | sites | 30 | unconfirmed |
| 5 | sagami_livecams | sites | 16 | unconfirmed |
| 6 | hadano_preserved_trees | protected_areas | 30 | unconfirmed |
| 7 | hiratsuka_parks | protected_areas | 290 | unconfirmed |
| 8 | kanagawa_green_conservation | protected_areas | 379 | unconfirmed |
| 9 | kanagawa_natural_parks | protected_areas | 29 | unconfirmed |
| 10 | biodic_veg2024_kanagawa | vegetation_polygons | 13,206 | custom_terms |
| 11 | biodic_mammal_mesh_kanagawa | mammal_mesh | 75,240 | custom_terms |
| 12 | geoshape_sagami_river | river_segments | 1,547 | noncommercial |
| 13 | kanagawa_rdb2006_animals | taxa | 221 | open_terms |
| 14 | kanagawa_redlist | taxa 1,851 / redlist_assessments 1,851 | 3,702 | open_terms |
| 15 | moe_ias_list | taxa | 424 | open_terms |
| 16 | moe_redlist | taxa | 6,085 | open_terms |
| 17 | kanagawa_rdb2022_plants | redlist_assessments | 1,033 | open_terms |
| 18 | kanagawa_river_citizen_survey | protocols | 6 | unconfirmed |

追加（A に既出の出典に、`get_records` で取れる表を足すだけ。18 件には数えない）:
`env_kousui_sample_kanagawa` の `events`（29,271。`events` 全体 29,947 のうち source_id 空の 676 行は出典に属さないので出さない）、
`kanagawa_kuma_sightings` の `wildlife_sightings`（400。キューブの出現は座標なし 5 セルにしかならないので、明細はこちら）。
この 2 件は `queryable_via` に `get_records` を足す。

**公開する列（許可リスト。`web/src/lib/records.ts` の `RECORD_TABLES` に表ごとに持つ。`SELECT *` は書かない）**

| 表 | 主キー | 検索列 `q` | 返す列（`source_id` は常に返す） |
|---|---|---|---|
| sites | site_id | name, name_en | site_id, name, name_en, watershed, zone, lat, lon, elevation_m, municipality, muni_code, operator, established_on, source_ref。除外: geohash, treatment, is_synthetic |
| protected_areas | area_id | name_ja | 全列（area_id, name_ja, category_ja/code, municipality_ja, area_ha(_raw), designated_on(_raw), lat, lon, watershed, zone, note_ja, source_ref） |
| vegetation_polygons | feature_id | legend_name_ja | geometry_geojson 以外の全列（centroid_lat/lon・area_m2・naturalness 等） |
| river_segments | feature_id | name_ja | geometry_geojson 以外の全列（start/end の座標・length_m 等） |
| mammal_mesh | id | species_ja, species | 全列（mesh_code, survey_label, confirmed, lat, lon 等） |
| taxa | taxon_id | scientific_name, vernacular_name_ja | 全列（redlist_kanagawa/national・ias_category を含む） |
| redlist_assessments | assessment_id | scientific_name, vernacular_name_ja | 全列 |
| protocols | protocol_id | name | protocol_id, name, version, domain, url, steps_json |
| events | event_id | （なし） | event_id, site_id, event_date, event_time, protocol_id, weather, precip_24h_mm, water_temp_c, source_ref。除外: gps_offset_m, is_synthetic 等の内部フラグ |
| wildlife_sightings | sighting_id | species_ja, locality_ja | 全列 |

注意（実データの癖）:
- `taxa.source_id` に **複合値 `moe_redlist|moe_ias_list`（4 行）** がある。絞り込みは「完全一致 または `|` で区切った要素の一致」とし、
  この 4 行は両方の出典から見える。`n_rows` もこの扱いで数える（taxa 8,585 = 221+1,851+424+6,085+4）。
- `kanagawa_redlist` は 2 つの表を持つので `table` が必須。応答の `provenance` は出典 1 件。
- 座標の列はぼかさずそのまま返す（ADR-0028）。

### 3.3 任意 SQL・全表走査にしない・巨大列
- SQL は `RECORD_TABLES` の定義から組み立てる固定の形だけ: `SELECT <許可列> FROM <表> WHERE <source 条件> [AND pk=? | AND (col LIKE ? ESCAPE '\' OR ...)] ORDER BY pk LIMIT ? OFFSET ?`。
  表名・列名は定義済みの定数だけで、入力から組み立てない。バインドは常に数個（100 個の制限に当たらない。`queryChunked` は要らない）。
- **出典で必ず絞る**ので他の出典の行は返らない。`source_id` なしの呼び出しは入力検査で拒否（`tools.test.ts` の入力スキーマ固定に追加）。
- 件数は `count(*)` しない。事前計算の `n_rows`（`q`・`id` なしのとき `n_total` に使う）か、`limit+1` 件読んで `truncated` を出す。
  `q` ありのときは `n_total` を返さない。
- `geometry_geojson`（vegetation_polygons・river_segments。1 行が数 KB〜）は一覧では返さない。
  `include_geometry: true` は `id` 指定の 1 件のときだけ許す（そうでなければ入力エラー）。応答の容量を守る。
- 応答は `buildDataEnvelope(query, { table, rows, offset, n_total? }, [source_id], { caveats, truncated })`。
  出典の注意書きは registry の caveat を source facet で引く（出典ごとの分岐を書かない。`get_edna` と同じ）。

### 3.4 AI 側
推奨: **足す**。`web/src/lib/ai/tools.ts` に共通関数 `queryRecords` を呼ぶ `get_records` を 1 つ登録する（`get_edna` と同じ。AI 側の入力は strict にしない）。
`run_sql` は第2層で `catalogOnly` が表を絞るので、出典単位で引ける入口があるほうがよい。`prompt.ts` は変えない（`__snapshots__` が動く）。AI の `list_catalog` への状態の追加は範囲外。

## 4. ライセンスの扱い（決定事項 3）
既存の規約: ADR-0028 と `registry/source/license.yaml` の冒頭、`tools.ts` の冒頭は、
「`redistributable`/`license_class`/`commercial_ok` は出典の旗であり、出力を絞る根拠にしない。`excluded` は常に 0」と明記している。
18 件はすべて `redistributable=1`（geoshape_sagami_river は class=noncommercial、biodic 2 件は custom_terms、
unconfirmed が 8 件）で、除外する行は無い。

**設計: 行を除外しない。`excluded` は 0 のまま。** 利用者がライセンスを判断できるよう、
`provenance` の `license_*`・`attribution`（既存の `sourceCitation`）をそのまま載せる。
`describe_catalog` の行に `license_class` を足すかは §7-1 で確認する。
「`excluded` の仕組みで除外する」というオーナーの指示は、将来 `redistributable=0` の出典が現れたときのために
**口だけ**用意する案を §7-1 で挙げた（本 PR では実装しない）。

## 5. 実装の分け方（決定事項 5）
2 人。衝突を避けるため、`tools.ts` は A だけが触る。B は `get_records` の定義を新規ファイルに置き、A が 1 行で登録する。

### 5.1 担当 A: 出典の状態（宣言・ビルド・describe_catalog）
- 触るファイル: `registry/source/access.yaml`（新規）、`scripts/registry/build_source.py`（または `build_source_access.py` 新規）、
  `scripts/r01_build_registry.py`（`--check-fresh` の入力）、`web/src/db/schema-registry.ts` と `web/drizzle/migrations/`（`pnpm run db:generate`）、
  `web/scripts/build-registry-ts.mjs`、`web/src/lib/registry/generated-source.ts`（再生成物）、
  `web/src/lib/cube/source-meta.ts`（`sourceAccess(sourceId)` の読み出し口）、`web/src/lib/mcp/tools.ts`、`web/src/lib/mcp/tools.test.ts`、
  `scripts/tests/test_registry_source_access.py`（新規）、`web/src/lib/table-meta.ts`（`source_access: "reg"`）。
- A は `tools.ts` で `import { getRecordsTool } from "./tools-records"` を `MCP_TOOLS` に足す（B のファイルが出来てから。それまで B のスタブで可）。
- **契約（B に渡す形）**: `generated-source.ts` に `SOURCE_ACCESS: Record<string, {state; queryableVia: string[]; tables: string[]; nRows: number|null; nRowsBasis; countedAt: string|null; reason: string|null; reasonNote: string|null}>` と `RECORD_SOURCE_IDS: readonly string[]`（`tables` が空でない出典、18 件+kuma・kousui_sample の追加分）。
- 受け入れ基準:
  1. `describe_catalog(sources)` の全件（125 件）が `queryable_via`（配列）と、空のときの `unavailable_reason` を持つ。`summary.total=125`、`by_tool`・`by_reason` の合計が整合。
  2. 取れない 92 件（`synthetic_sensor` を含む）の全件に `reason` があり、語彙の外のコードは無い。
  3. §1.4 の検査が実装され、**変異で止まる**ことを確認（宣言の `records` に行が無い表を足す／`reason` の出典に行がある宣言にする／出典を 1 つ消す、の 3 つ）。
  4. `search_registry(kind='source')` の行も同じ形。
  5. 既存の `tools.test.ts`・`source-meta.test.ts` が通る（ツール名の固定テストは B の追加後に更新）。
- 速い検証（重い処理は不可）: `cd web && pnpm vitest run src/lib/mcp src/lib/cube/source-meta.test.ts`、
  `.venv/bin/python3 -m pytest scripts/tests/test_registry_source_access.py scripts/tests/test_registry_source.py`、
  `.venv/bin/python3 scripts/r01_build_registry.py`（registry だけ。数十秒。`build:v2`・b00 は回さない）、`pnpm run build:registry:ts`。

### 5.2 担当 B: `get_records`（lib・MCP・AI）
- 触るファイル: `web/src/lib/records.ts`（新規。`RECORD_TABLES`・入力スキーマ・`queryRecords`）、`web/src/lib/records.test.ts`（新規）、
  `web/src/lib/mcp/tools-records.ts`（新規。`getRecordsTool`）、`web/src/lib/mcp/tools-records.test.ts`（新規）、
  `web/src/lib/ai/tools.ts`（`get_records` を 1 つ登録）。`tools.ts`（MCP）・`generated-source.ts` は触らない。
- B は A の生成物が来るまで、テスト用の `SOURCE_ACCESS` 相当をローカルの定数で持ち、A の統合後に `generated-source.ts` から読む形へ差し替える
  （差し替えは main が行う統合の最初の作業）。
- 受け入れ基準:
  1. §3.2 の 18 件 + 追加 2 表について、`get_records` が**全件で 1 行以上**返す。テストは `RECORD_SOURCE_IDS` を回す
     （インメモリ SQLite に `schema.ts` の DDL を作り、宣言済みの (出典, 表) ごとに 1 行入れる。**サンプル DB は使わない**: `data/sample/ryuiki` に
     protected_areas・vegetation_polygons・mammal_mesh・river_segments・protocols・events が無い）。
  2. 許可リストに無い列・`geometry_geojson`（`id` なしの `include_geometry`）・`source_id` なし・出典に無い `table` は入力エラー。
     未知のキー（`.strict()`）も拒否。ツール一覧・入力スキーマの固定テストに追加。
  3. `RECORD_TABLES` の列がすべて `schema.ts` の実在列（テストで突き合わせる）。`SELECT *` が無い。
  4. 複合 source_id（`moe_redlist|moe_ias_list`）の 4 行が両方の出典から見える。
  5. `limit`/`offset` のページングで重複・欠落が無い（主キー昇順）。`excluded` は 0。`provenance` に出典 1 件。
  6. 応答のサイズ: vegetation_polygons を `limit=500` で引いても geometry を含まず 500KB 以内。
- 速い検証: `cd web && pnpm vitest run src/lib/records.test.ts src/lib/mcp src/lib/ai`、`pnpm tsc --noEmit`。
  実 D1 には触れない（ローカルの `db:setup` を使うなら 1 回だけ。無くてよい）。

### 5.3 統合（main）
1. A の `tables` と B の `RECORD_TABLES` が一致することをテスト化。
2. **全出典を回す結合テスト**（`tools.test.ts` に 1 本）: `describe_catalog(sources)` の全行について、`queryable_via` の各ツールを
   その出典で呼び、1 行以上返ること（観測系・出現系は既存フィクスチャ、`get_records` 系は B のインメモリ DB）。
3. PR 直前に 1 回だけ全量の vitest・pytest。b00 は回さない（パイプラインのパスを触らない）。

## 6. 本番反映（決定事項 6）
- **新しいマイグレーション 1 本**: `source_access`（レジストリ表）。`web/drizzle/migrations/` に `db:generate` で作る（SQL を直接書かない）。
- **流す表は `source_access` の 125 行だけ**。`get_records` は既存の 10 表（sites・protected_areas・vegetation_polygons・river_segments・mammal_mesh・taxa・
  redlist_assessments・protocols・events・wildlife_sightings）を読むだけで、**これらの表の再投入は不要**。
  手順: ローカルで `db:setup`（registry は `predb:setup` が作り直す）→ 行数の確認 → `wrangler d1 migrations apply --remote`
  → `db:export` で `source_access` の INSERT だけを `wrangler d1 execute --remote --file` に流す（`d1 export` は使わない）→ Worker を `pnpm run deploy`。
  順序は migrations → 行 → deploy（`SOURCE_ACCESS` は静的で、D1 の表は run_sql 用）。
- 反映前に D1 の実数を確認: 18 件の `source_id` 別の行数が §3.2 と一致すること（本番に原本のシードが古くないか）。
- 反映後（curl 1 回）: `describe_catalog(sources)` が 125 件・`summary`、`get_records` を 18 件で 1 回ずつ（limit=1）。
- ロールバック: Worker を前の版へ戻す（`source_access` は残して無害）。

## 7. 不安が残る論点（オーナーの確認が要るもの）
1. **ライセンス除外の指示と ADR-0028 の食い違い**。指示は「再配布できない行は `excluded` で除外」。既存規約は「除外しない・`excluded` は常に 0」。
   本設計は既存規約に合わせた（18 件に除外対象は無い）。覆すなら ADR-0028 の改定が先で、そのうえで `access.yaml` の出典に `withhold: {reason}` を持たせ、
   `get_records` が行を返さず `excluded.by_license` に件数と理由を載せる口を足す（実装は小さいが、他の 5 ツールとの足並みが問題）。要判断。
2. **水源マップの表（`water_*` 8 表）は出典の列を持たない**。`estat_shozaiki_kanagawa`（record_count 5,089 = `water_zone` 5,089 行）、
   `water_source_docs`（69 = `water_source_doc` 69 行）は 1 対 1 に見えるが、`water_trace_yokohama`/`kawasaki`（1,718/611）は `water_zone_assignment` との対応が
   機械的に確認できない。本設計では 3 件とも C（`file_only`）に置いた。表単位の宣言（`tables` の逆引き）を足せば B に移せる（+3 件程度）。
3. **件数の意味**。`n_rows` は原本の行数で、キューブの集計行数ではない。観測系の「n」を利用者が `get_observations` の `n` と比べて混乱しないか。
   `n_rows_basis` と description で補うが、名前を `n_source_rows` にするほうがよいかもしれない。
4. **`kanagawa_kuma_sightings` の二重**。出現キューブには座標なしの 5 セル、`wildlife_sightings` には 400 行。
   `queryable_via: ["get_occurrences","get_records"]` とし、description に「明細は get_records」と書く。モデルが両方を引いて二重に数えないか。
5. **`events` の 676 行（source_id 空）**は誰の出典にも属さず出ない。合成か不明。扱いは現状維持（出さない）。
6. **理由の人手確認**。92 件の理由の初期割り当て（§1.3）は機械的な下書きで、`file_only` と `not_collected` の境目（processed の有無）は
   `nodata.txt` に依る。原本の無い環境では検査できない。担当 A が下書きを出し、main が一覧を目で確認してから確定する。
7. **鮮度の穴**。`n_rows` は registry のビルド時点の値。原本が更新されたのに registry を作り直さないと古い。
   `--check-fresh` の入力に足す（§1.1-5）が、足りているかは担当 A の変異テストで確かめる。
8. **性能**。`get_records` は `source_id` の索引が無い表（mammal_mesh 75k 行など）で主キー順に走査する。
   1 出典が表の大半を占める表ばかりなので許容と見るが、`offset` が深いと rows_read が増える。実測は main が 1 回（`EXPLAIN QUERY PLAN` と本番の rows_read）。
   問題なら `source_id` の索引を `schema.ts` に足す。

## メインの判断（2026-10-07）
1. ライセンス: ADR-0028 に合わせて除外しない（excluded は 0 のまま）。
2. water_* の8表: どの出典から作った表かを access.yaml で宣言できるものは、get_records の対象にする（表→出典の宣言を r01 が検査する）。宣言できないものは理由 `d1_no_source_column` で取れない側に置く。
3. kanagawa_kuma_sightings: queryable_via に get_occurrences と get_records（wildlife_sightings）の両方を書く。
4. 複合 source_id（`a|b`）: どちらの出典で絞っても、その行が返る。照合は区切りで分けた完全一致（LIKE の部分一致にしない）。
5. 件数の名前は `n_source_rows`。
6. テストはインメモリの SQLite で行う。
7. 92 件の理由は、registry・source_registry の情報から機械的に下書きする（宣言に `basis` を残す）。PR に理由別の件数と例を載せ、メインが抜き取りで確かめる。
