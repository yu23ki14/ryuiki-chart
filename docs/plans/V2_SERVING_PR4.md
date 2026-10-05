# Issue #48 PR-4「文書・概況の切り替えと、合成デモの撤去」実装設計

前提: ブランチ `feat/48-pr4`（main = PR-3b マージ済み、`9890e37`）。実測は 2026-10-05 に `data/db/` の `cells.sqlite`・`ryuiki.sqlite`・`derived.sqlite`・`v2.sqlite`・`registry.sqlite` を `mode=ro` で読んだもの（付録）。重い処理は一切回していない。PR-3b 設計書（`V2_SERVING_PR3B.md`）の形をなぞり、短くしてある。

## 0. 要点（先に読む）

1. **web が v1 表を本当に読んでいるのは、`web/src/lib/queries.ts` の v1 関数群・`ai/tools.ts` の6か所・`table-meta.ts`・`MapPage.tsx` の events 重ね・`api/quality`・`api/geo/events`・`app/quality` だけ。** 洗い出し（§2.1、コメントを除いた SQL 文脈と引用符つき完全一致で機械的に数えた）で、`/sites`・`/sites/[id]`・`/timeseries`・`api/timeseries`・`api/geo/sites`・`app/page.tsx` に残る `"measurements"` は **v1 表ではなく registry の dataset キー**（`variable_alias.dataset`）の定数で、PR-2 で切り替え済みの残骸ではなく正当な語彙。表の参照ではないので、定数を1か所（`lib/cube/series.ts`）に寄せて import にする（許可リストを短くするため）。
2. **完了条件は vitest のテスト1本で機械的に確かめる**（§2.2）。web（`web/src`、テスト・fixture 以外）のソースから、コメントを除き、(A) SQL の `FROM/JOIN/INTO/UPDATE/TABLE` の直後、(B) 引用符で囲まれた完全一致、(C) `TABLE_ORIGIN`/`TABLE_META` のキー（実行時）に、派生33表と落とす原本表（＋D3 次第で `instruments`/`protocols`）が出たら落ちる。許可リストは理由つき・生きていること（一致しなくなったら落ちる）を検査。許可は `schema.ts`（PR-5）・生成物 `generated-client.ts`（PR-5 で registry から落とす）・dataset キー定数だけ。
3. **v1 の oracle（serving-diff の v1 側が呼ぶ `queries.ts` の v1 関数）は `web/scripts/lib/serving/v1-queries.ts` に移す**（import の1行以外は無変更）。PR-3b は「v1 関数は `queries.ts` に残す」としたが、そのままだと完了条件が許可リストなしで満たせない。移せば `web/src` は許可リスト（上記）だけでゼロになる。`db.ts` の差し替えは不要になり（新ファイルが `../v1-db-shim` を直接 import）、`register-aliases.mjs` の `db.ts` 書き換えは用済み（`server-only` の差し替えは `lib/cube` のために残す）。
4. **`doc_series*` はキューブにせず、`cells`/`notes`/`documents` からの問い合わせ時 SQL にする**（新設 `lib/cube/documents.ts`、`CubeDb` を取るので serving-diff も同じ関数を呼べる）。4,361 行の数値セルしか無く、実測 SQLite で 30ms（部分索引つき）。D1 では部分索引 `ix_cells_series` を `cells` に1本足す（rows_read を 119,533 → 約 9,000 にする）。v1 のバグ4件の直し方は §3.1。**col_key 潰れは「値が割れる年を系列から除く」が推奨で、これは 56 系列・336 点が消える（D1）。**
5. **土地利用は observation_agg（theme=landuse）から読む。summary は足さない。** `watershedRollup(db)`（新設）が `place`＋`place_relation`（site_n）＋キューブ（建物・森林・田の 2006/2016）を問い合わせ時に引き、`watershedOccurrence` と合わせて v1 の `watershed_rollup` と **全列・全377流域で差 0**（実測、付録）。応答 4ms。`landuseHighlight`（home）も同じ土台（上位8に同点なし）。
6. **概況は `overviewCounts(db)`（新設）**。`n_sites`/`n_sources`/`n_watersheds`/`y_from`/`y_to` は v1 と差 0。`n_meas`・`n_sensor`・`n_events` は **キューブからは再現できない**（L2 を D1 に入れない。`observation_agg.n` は粒度ごとの重複で行数にならない。`events` は落とす表）ので、ホームのタイルを「観測指標 75 種」に置き換える（D2）。
7. **合成データのみの画面・API・AI ツールを撤去**（§6）: `/quality`・`/api/quality`・`/api/geo/events`・`get_quality_progress`・MapPage の「介入と意思決定」重ね・ホームの導線・`lib/quality.ts`。`describe_schema` はカタログ表だけ（件数なし）、`run_sql` は実在表のうちカタログ外を拒否（実行時に `sqlite_master` から導く。ソースに表名を書かない）、`/api/column` に `EXPLORE_ENABLED` ゲート。
8. **作業は4単位・4 worktree**（U1 `lib/cube`＋schema、U2 画面・API、U3 AI・探索面・`queries.ts` 整理・参照ゼロのテスト、U4 serving-diff）。U1 が最初のコミットで型だけ出す。重い検証は PR 直前に1回ずつ（§8.3）。b00 は要らない（パイプラインのパスに触れない）。

## 決めてほしいこと（最小限）

| # | 論点 | 推奨 |
|---|---|---|
| **D1** | **`doc_series` の col_key 潰れの直し方。** v1 は `(doc, table, row_key, fiscal_year)` で `AVG` するため、同じ年に別の値のセルが複数ある 336 グループ（全 3,590 点中、140 系列にかかる）が平均されて**どの観測値でもない数**になっている。原因は2種類で、(i) 列見出しが複数年度の連結（`H25 H26 … H30`）で全部 `fiscal_year=2013` に丸められた（281 グループ）、(ii) 別の列見出し／表の副列が同じ年に並ぶ（55 グループ＋`哺乳類` のように同じ col_key で値が割れるもの）。`col_key` を GROUP BY に足すだけでは (ii) の一部（55）しか直らない（決定事項10の文言どおりでは足りない）。**A**: 値が割れる年は系列から除く。**B**: 除かずに点を残し、`ambiguous` の印を付けて表にだけ出す（チャートには描かない） | **A**（推奨）。結果: 点 3,590→3,254（−336）、系列（`n_years>=3`）470→414（**−56**、すべて `choju_kyugo_jisseki_*` と `ghg_kennai_suikei_2021` 等の複数副列の表）、`n_years`/範囲が変わる系列 5。B は UI の追加が要る（`DocumentsExplorer` の表に印の列）が系列は 470 のまま。除いた件数は serving-diff の規則 `doc_year_collapse` が数える |
| **D2** | **ホームの統計タイル。** 「測定値 N 行」「センサー観測 N 行」「観測イベント N 件」は、L2 を D1 に入れない方針とキューブの `n` の性質（粒度ごとの重複）から**再現できない**（`events` は落とす表）。**置き換え**: 「測定値」→「観測指標 75 種（1973–2026）」（`summary_variable_catalog` の DISTINCT `variable_id`）、センサー・イベントは外す（7→5 タイル。生物は PR-3b の「日付のある生物レコード」のまま） | **採用**。代案の「cube の `n` を1粒度で足して近似」は mean/min/max/point の重複や hour 入力の扱いで説明がつかない数になる（実測: 粒度ごとの Σn 内訳は付録） |
| **D3** | **`instruments`（26 行）・`protocols`（6 行）の扱い。** 実データ（調査マニュアルの機材・校正記録・手順）だが、読み手は `/quality` だけ（`instrumentList`・`protocolList`・`instrumentStats`）。V2_SERVING.md §3.1 の「落とす」にも「残す」にも載っていない | **画面ごと撤去し、PR-5 で表も落とす**（`FORBIDDEN_TABLES` に入れる）。残したいなら §3.1 の「残す」に足し、`/sources` か `/documents` に出す別 PR |

D1 以外（土地利用の行き先・年の上限・`n_since_2020`・`v1-queries.ts` への移動・`run_sql` の方式）は設計責任者が決めた（本文）。

## 1. 範囲と非範囲

- 範囲: V2_SERVING.md §5 PR-4（`doc_series*`・`quality_monthly` の行き先・概況・土地利用・合成デモ撤去・`describe_schema`/`run_sql`/`/api/column`）、完了条件（参照ゼロ）の自動テスト、PR-3b 申し送りの小さな負債（§7）、serving-diff の追加。
- 非範囲（PR-5）: `schema.ts` の表定義の削除と DROP マイグレーション、`registry/caveat.yaml`・`build_caveat.py` の table スコープ掃除と `generated-client.ts` の再生成（パイプラインのパスなので b00 が要る）、`web/scripts/build-*.mjs`・`seed-d1-local.mjs`・`export-d1-sql.mjs` の v1 表、`v1-queries.ts` と serving-diff の v1 側そのもの、`water_*`/`vocab_*`/`extraction_log`（PR-6）。
- 追加するマイグレーションは `0009` の1本（`cells` の部分索引のみ。統合者が `pnpm run db:generate` を1回）。**NOT NULL 列の追加はない**。

## 2. 完了条件: 参照ゼロの洗い出しと機械的な確認

### 2.1 今の参照元（実測。コメントを除いた SQL 文脈 A・引用符つき完全一致 B）

「何か」は、PR-2/3b で切り替え済みの**残骸**（表の参照ではない）か、**本当に v1 を読んでいる**かの区別。

| ファイル | 表（語） | 実態 | 置き換え先 |
|---|---|---|---|
| `lib/queries.ts`（60 語） | `meas_*`・`zone_*`・`site_var`・`var_catalog`・`rain_daily`・`species*`・`mesh_*`・`org_*`・`effort_year`・`ias_species`・`redlist_*`・`watershed_meta`・`landuse_change`・`quality_*`・`interventions`・`decisions`・`observers`・`event_observers`・`events`・`measurements`・`organism_records`・`sensor_timeseries`・`doc_series*`・`watershed_rollup` | **本当に v1**。ただし画面・API・AI が呼ぶのは `overviewStats`/`landuseHighlight`/`watershedRollup`/`docSeries*`/`quality*`/`interventions`/`decisions`/`observerStats` の一部だけ。残りは serving-diff の v1 側だけが呼ぶ（PR-2/3b で画面は切り替え済み）。`landuseChange`・`instrumentStats`/`instrumentList`/`protocolList`/`pairedMeasurements` は `/quality` 以外の読み手なし（`landuseChange` は読み手ゼロ） | v1 関数は `scripts/lib/serving/v1-queries.ts` へ移動（U4）。`queries.ts` には `docNotes`・`documentsList`・`blockingNotes`・`sourceRegistry`・Tier 1 の `protectedAreas`…`riverSegmentSummary` だけ残す（いずれも残す表を読む）。`docSeries*` は `lib/cube/documents.ts`（U1）。`overviewStats`/`landuseHighlight`/`watershedRollup` は §3.2〜§3.3 |
| `lib/ai/tools.ts`（B 12） | `measurements`・`events`・`sensor_timeseries`・`watershed_meta`・`var_catalog`・`watershed_rollup`（`get_overview` の `v1Tables`）、`quality_transitions`…`event_observers`（`get_quality_progress`）、`DATASET="measurements"` | `v1Tables` は provenance と注記キー（`caveatKeysForTables`）を引くための**名前だけ**（v1 表は読んでいない）。`get_overview` は `overviewStats`/`watershedRollup`（v1）を呼ぶ。`get_quality_progress` は合成表を読む | `get_overview` は `overviewCounts`＋`watershedRollup`（cube）、provenance は実際に読む表（`sites`・`source_registry`・`place`・`place_relation`・`observation_agg`・`summary_*`）、注記は表（`sites`）＋ facet（`facetsForOccurrence`・`variable_theme=landuse`）。`get_quality_progress` 撤去。`DATASET` は定数 import |
| `lib/table-meta.ts`（A 4・キー多数） | `TABLE_ORIGIN`/`TABLE_META` のキー（派生33表・落とす原本表）、`SAMPLE_QUERIES`（`measurements`・`organism_records`・`redlist_assessments`・`sensor_timeseries`） | 説明の道案内。`describe_schema`・`prompt.ts`・`/api/schema`・`db.ts` が読む。**v1 を指す SQL の例を few-shot として AI に渡している**（`run_sql` で v1 を引かせる原因） | `TABLE_ORIGIN`/`TABLE_META` を**カタログ表だけ**に（registry 表・cube 表・summary 8表・`taxon_assessment`・`place_*` を足し、`SCHEMA_META` に `reg` を足す）。`SAMPLE_QUERIES` を summary/registry/`cells` の例に書き換え（§4.4） |
| `components/map/MapPage.tsx`（14） | `events`（`/api/geo/events` の重ね） | 合成データの重ね | 撤去（§6） |
| `app/api/quality`・`api/geo/events`・`app/quality`・`components/quality` | `observers`・`interventions`・`decisions` ほか | 合成のみ | 撤去 |
| `lib/quality.ts`・`components/viz/palette.ts` の `QUALITY_STAGE` | `quality_stage`（列名・コメント） | 読み手は `QualityDashboard`/`queries.ts` の品質関数だけ | 撤去（palette の `QUALITY_STAGE` も。「検証済みの値以外を足さない」の逆＝減らすだけなので可） |
| `app/page.tsx`・`app/sites/page.tsx`・`sites/[id]/page.tsx`・`timeseries/page.tsx`・`api/timeseries`・`api/geo/sites`・`lib/registry/lookup.ts`・`lib/cube/series.ts`/`observation.ts` | `"measurements"`（B 各1） | **残骸ではなく registry の dataset キー**（`variable_alias.dataset`）。v1 表の参照ではない | `lib/cube/series.ts` に `MEASUREMENTS_DATASET`・`SENSOR_DATASET` を1か所定義し、各所は import。許可リストは `series.ts` だけに（U1 が定義、U2/U3 が置換） |
| `lib/ai/prompt.ts`（B 2） | `"sensor_timeseries"`（`resolveVariableInfo("OX", …)`） | dataset キー | `SENSOR_DATASET` import |
| `lib/cube/caveats.ts`・`occurrence.ts` | `"organism_records"`（facet の dataset）・`"taxa"`（`basis` の値） | 表ではない（dataset 語彙・和名の出自の値） | 許可リスト（理由つき） |
| `lib/registry/generated-client.ts`（B 多数）・`generated.ts` | `caveat_scope` の table スコープ行（派生表名）・alias の dataset | 生成物。table スコープ行は `build_caveat.py` の表名集合から出る（`quality_monthly` ほか 40 行弱） | **PR-5**（registry の再生成＝b00）。PR-4 では許可リスト。dataset キーは恒久 |
| `db/schema.ts`・`schema-cube.ts`・`schema-registry.ts` | 表定義 | PR-5 | 許可リスト（`schema.ts` のみが禁止表を持つ） |

（上の B が `pointer-events-none` のような CSS クラス・`events.data` のような変数名に当たらないよう、素の単語一致ではなく A/B/C だけを数える。素の単語一致だと 20 ファイル超の偽陽性になる。）

### 2.2 テスト `web/src/lib/v1-references.test.ts`（U3、vitest、1秒未満）

- **`FORBIDDEN_TABLES`**: 派生33表（`derived.sqlite` の表名）＋ 落とす原本表11（`measurements`/`sensor_timeseries`/`organism_records`/`taxa`/`redlist_assessments`/`decisions`/`interventions`/`quality_transitions`/`observers`/`events`/`event_observers`、V2_SERVING.md §3.1）＋ D3 が「撤去」なら `instruments`/`protocols`。配列はテストファイルに直書き（出典を §3.1 とコメント）。PR-5 のあとも**退行防止としてそのまま残す**。
- **スキャナ `findTableReferences(source)`**: `/* … */` と `//` 以降を除き、(A) `\b(from|join|into|update|table)\s+["`]?(\w+\.)?<表>\b`（大文字小文字不問・`d.`/`c.` 接頭辞つきも）、(B) `["'`]<表>["'`]` を検出。ファイル走査は `web/src/**/*.ts(x)`、除外は `*.test.ts(x)`・`__fixtures__`・`__snapshots__`。
- **許可リスト** `{file, table|"*", reason}[]`: `src/db/schema.ts`（`*`、PR-5）・`src/lib/registry/generated-client.ts`（`*`、caveat_scope の table スコープ。PR-5 で registry から落とす）・`src/lib/registry/generated.ts`（`measurements`/`sensor_timeseries`、dataset キー）・`src/lib/cube/series.ts`（同、定数の定義）・`src/lib/cube/caveats.ts`（`organism_records`、facet の dataset）・`src/lib/cube/occurrence.ts`（`taxa`、basis の値）。**各エントリは理由が空でないこと、かつ実際に1件以上一致すること**（一致しなくなったら「許可リストから消せ」で落ちる＝腐らない）。
- **カタログの整合（実行時）**: `Object.keys(TABLE_ORIGIN)`・`Object.keys(TABLE_META)` ∩ `FORBIDDEN_TABLES` = ∅。`SAMPLE_QUERIES` の各 SQL を同じスキャナ（A）で見て、出る表が `TABLE_ORIGIN` のキーの部分集合。`schema*.ts` を `sqliteTable\("(\w+)"` で読み、全表が `TABLE_ORIGIN` か `FORBIDDEN_TABLES` のどちらかに入る（未分類を許さない。新しい表を足したら分類を迫られる）。
- **スキャナの自己診断**: `SELECT * FROM d.meas_year`・`` `FROM measurements m` ``・`"species2"` は検出、`// FROM meas_year`・`/* species2 */`・`"pointer-events-none"`・`const events = []` は非検出。
- **変異（統合者が1回）**: 任意の `web/src` ファイルに `SELECT 1 FROM species2` を足すとこのテストが落ち、戻すと緑になることを確かめる（「通りました」を自分で確かめる規則）。

## 3. 対応表: v1 の呼び出し → 置き換え先

### 3.1 `doc_series*`（U1 `lib/cube/documents.ts`、U2 `api/documents` と `DocumentsExplorer`）

入力は `cells`・`notes`・`documents`（D1 に残す原本表）。`CubeDb` を取る（D1 とメモリ SQLite の両方で動き、serving-diff が同じ関数を呼べる）。`SqliteCubeDbPaths` に `cells`（`cells.sqlite`）を足し、ATTACH で名前を引けるようにする（`sqliteCubeDb` の第3の追加パス。`ryuiki` が main、`cells` は ATTACH）。

共通の入力条件（v1 と同一）: `superseded=0 AND is_total=0 AND value_type IN ('int','float') AND value IS NOT NULL AND fiscal_year IS NOT NULL AND row_key IS NOT NULL AND row_key<>''`。

| v1 のバグ（`PHASE_B_DOCUMENTS.md` §3） | v2 の直し方 | 実測（今のデータ） |
|---|---|---|
| ① `label` が最初の `|` の次から末尾の `|` までを切り出す | **最後の `|` の後ろ**（`rowKeyLabel`: `lastIndexOf('|')`、空なら `row_key` 全体）。SQL ではなく TS の純関数 1つ（`lib/cube/documents.ts`）で `docSeriesList` が付け、API が返し、UI は再計算しない（今の `DocumentsExplorer` の `rowKeyLabel` は撤去して API の `label` を使う） | v1 meta 470 行中 `label` が変わるのは **20 行**（v2 に残る 414 行のうち 20）。`doc_series` 3,590 行中 289 行が元のバグ |
| ② `n_warnings` が doc 単位の相関サブクエリ | `notes` のうち `blocks_timeseries=1` かつ（`table_ids` が NULL・`''`・`'[]'`＝**文書全体にかかる注記**、または `json_each(table_ids)` に当該 `table_id` を含む）の件数。`table_ids` は JSON 配列文字列 | blocking 注記 132 件のうち 104 件が文書全体。v2 に残る 414 行のうち **245 行で値が減る**（例: `tanzawa_shika_r6` の 89 行が全部 9 → 表ごと） |
| ③ `col_key` が GROUP BY に無く別年の値が1つの年に潰れる | **D1 の A（推奨）**: `GROUP BY (doc, table, row_key, fiscal_year) HAVING MIN(CAST(value AS REAL)) = MAX(CAST(value AS REAL))`（値が割れる年は点にしない。値が同じ重複は1点）。`value`＝`MIN`。B を採るときは割れる年を `ambiguous=1` で残し、`n_years` には数えない | 点 3,590→3,254（−336）、meta 470→414（−56。うち元の `n_years` は 5:37・3:12・8:5・4:2）、`n_years`/`y_from`/`y_to` が変わる系列 5 |
| ④ `page_no`/`unit` が GROUP BY 外の裸列 | 点は `MIN(page_no)`・`MAX(unit)`、meta は `MAX(page_no)`・`MAX(unit)`（v1 の meta は既に MAX）。走査順に依らない | 今のデータでは 1 グループ内に 2 値以上は **0 件**＝**値は動かない**。決定性はテスト（フィクスチャで page_no を割る）で固定 |

公開関数（`lib/cube/documents.ts`）:

```ts
export interface DocSeriesMeta { docId; tableId; rowKey; label; pageNo; nYears; yFrom; yTo; unit; docTitle; publisher; url; license; nWarnings }
export interface DocSeriesPoint { fiscalYear; value; unit; pageNo }
export function rowKeyLabel(rowKey: string): string;                       // 純関数。lastIndexOf('|')
export async function docSeriesList(db: CubeDb, opt?: { minYears?: number }): Promise<DocSeriesMeta[]>;   // 既定 3（API は今も 3）。n_years DESC, doc_id, table_id
export async function docSeriesPoints(db: CubeDb, docId: string, tableId: string, rowKey: string): Promise<DocSeriesPoint[]>; // fiscal_year 昇順
```

SQL は1本（CTE で点→meta）。`json_each` は D1 可。性能（SQLite、実測）: 一覧 30ms（部分索引あり）、素の走査でも 54ms。D1 は rows_read が効くので、`schema.ts` の `cells` に **部分索引** `ix_cells_series ON cells(doc_id, table_id, row_key) WHERE <共通の入力条件>` を足す（`WHERE` の文面を問い合わせと**一字一句**揃える。SQLite は部分索引の述語が問い合わせの WHERE に含意されるときだけ使う。定数1か所 `DOC_SERIES_WHERE` を `schema.ts` と `documents.ts` が共有）。EXPLAIN をテストで固定（`USING INDEX ix_cells_series`）。drizzle-kit が部分索引の生成に失敗したら、通常索引 `(superseded, is_total, value_type, doc_id, table_id, row_key)` に落とす（SQL を手で書き換えない）。

`documentsList`/`blockingNotes`/`docNotes` は `cells`/`notes`/`documents` だけを読むので **`queries.ts` に残す**（変更なし）。

### 3.2 `quality_monthly` と合成デモ

`quality_monthly` は `quality_transitions` 3,372 行（すべて `SYN-MEAS-%` の合成。ADR-0017 の書き込み系ログ、`PHASE_B_DOCUMENTS.md` §1-2）の集計で、place も variable も無い。**行き先なし＝画面ごと撤去**（決定事項3・11）。品質・介入・意思決定・ペア測定（`pairedMeasurements`）・検証者・観測者・機器の画面と API・AI ツールをすべて撤去（§6）。`events`（29,947 行のうち 676 が合成）の「観測イベント」タイルもホームから外す（D2）。

### 3.3 概況・流域・土地利用（U1 `lib/cube/catalog.ts`）

| v1 | 置き換え | 差 |
|---|---|---|
| `overviewStats()` の `n_sites`（`COUNT(*) FROM sites`）・`n_sources`（`source_registry`） | `overviewCounts(db)` の `sites`・`sources`（同じ表を数える） | 0 |
| `n_watersheds`（`watershed_meta` 377） | `place` の `place_kind='watershed'` 377 | 0 |
| `y_from`/`y_to`（`var_catalog` の MIN/MAX＝1973/2026） | `summary_variable_catalog` の MIN(`y_from`)/MAX(`y_to`)＝1973/2026 | 0（実測） |
| `n_org`/`n_species` | PR-3b の `occurrenceTotals`（変更なし） | PR-3b の `undated_excluded` |
| `n_meas`・`n_sensor`・`n_events` | **廃止**（D2）。新設列 `variables`（`summary_variable_catalog` の DISTINCT `variable_id`＝75）で置き換え | 3列が廃止（serving-diff のレポートに「廃止列」として1行） |
| `watershedRollup()` の `area_km2`・`centroid_*`・`water_system_name` | `place`（`place_kind='watershed'`、`place_source_ref.source_id='watershed_meta.watershed_id'` の `external_key`＝v1 の `watershed_id`）の `area_km2`・`lat`・`lon`・`name_ja` | 0（377/377 全列一致、実測） |
| `site_n` | `place_relation`（`relation='within'`、`parent_id`＝流域、`child_id` が site の place）の COUNT | 0（377/377。Σ=278） |
| `built/forest/paddy_km2_2006/2016` | `observation_agg`（`place_kind='watershed'`、`grain='year'`、`stat='mean'`、`variable_id` ∈ {`landuse.building_land`・`landuse.forest`・`landuse.paddy`}、`period_start` = 版の年）の `value_lod`（土地利用は定量下限が無く `value_zero` と同じ）。`INDEXED BY ix_observation_agg_place_variable_grain` | 0（377/377 × 6列、実測。土地利用の無い流域 29 は NULL のまま） |
| `landuseHighlight(8)`（建物用地の 2006→2016 の増加上位） | `landuseHighlight(db, limit=8)`（上と同じ土台、`ORDER BY delta DESC, watershed_id`） | 0（上位 12 に同点なし） |
| `landuseChange(watershedId)` | **撤去**（読み手ゼロ） | — |

**土地利用の行き先の決定**: キューブの theme=landuse から問い合わせ時に引く（summary は足さない。理由: 流域 348 × 3 指標 × 2 版の数百行を `(place_id, variable_id, grain)` 索引で引くだけで 4ms、全表集計ではない）。**版の年は定数にしない**: 土地利用の最古・最新の `period_start`（今は 2006・2016）をデータから取って `landuseYears: {from, to}` として返す（新しい版が入っても列が増えない設計＝PHASE_B_LANDUSE §1 の決定どおり）。画面の「定義が違う」注記は **facet `variable_theme=landuse`**（`landuseDefinitionChange`、`facetsForSeries` が既に対応）で付ける——**ホームの `HomeHighlights` の土地利用カードと `/map` の流域指標（建物増減など）に `caveatBody("landuseDefinitionChange")` を出す**（今は出ていない。2006→2016 の比較は定義変更をまたぐので、切り替えと同時に付ける。値は動かさない注記の追加）。

## 4. `lib/cube` に足す公開関数・撤去・AI/探索面

### 4.1 `lib/cube`（U1。型は最初のコミットで確定）

```ts
// catalog.ts
export interface OverviewCounts { sites: number; sources: number; watersheds: number; variables: number; yFrom: number | null; yTo: number | null }
export async function overviewCounts(db: CubeDb): Promise<OverviewCounts>;

export interface LanduseCell { from: number | null; to: number | null }          // 版の年ごとの km2
export interface WatershedRollupRow {
  watershedId: string; waterSystemName: string | null; areaKm2: number; centroidLat: number; centroidLon: number;
  siteN: number; orgN: number; orgAlienN: number; orgRedlistN: number;               // org_* は PR-3b の watershedOccurrence
  built: LanduseCell; forest: LanduseCell; paddy: LanduseCell;
}
export async function watershedRollup(db: CubeDb): Promise<{ watersheds: WatershedRollupRow[]; landuseYears: { from: number; to: number } | null; outsideWatershed: { n: number } | null }>;
export async function landuseHighlight(db: CubeDb, limit?: number): Promise<{ watershedId: string; waterSystemName: string | null; delta: number; areaKm2: number }[]>;
// documents.ts: §3.1
// sql.ts: OCC_DEFAULT_TO を関数 `occDefaultTo(now?: Date)`（現在年）に、`IAS_SINCE_YEAR = 2020`（§7）
// series.ts: export const MEASUREMENTS_DATASET = "measurements"; export const SENSOR_DATASET = "sensor_timeseries";
```

`watershedRollup` は `watershedOccurrence`（PR-3b）を内部で呼んで org 列を足す（全 377 流域を返し、記録の無い流域は 0）。**`/api/geo/watersheds`・`get_overview`・serving-diff の `watershed_rollup` の3者が同じこの1関数を呼ぶ**（PR-3b の「org だけ cube、残りは v1」の混成を解消）。`db-sqlite.ts` の `SqliteCubeDbPaths` に `cells` を追加。EXPLAIN 固定テスト: 土地利用の引きが `ix_observation_agg_place_variable_grain`（第3索引 `ix_observation_agg_*` の誤選択を避ける。PR-3b §0-2 と同じ理由）。

### 4.2 画面・API（U2）

- `app/page.tsx`: `overviewStats`/`landuseHighlight`（v1）→ `overviewCounts`/`landuseHighlight`（cube）。タイルは D2（5 タイル: 観測地点・観測指標・日付のある生物レコード・単位流域・出典。`lg:grid-cols-7` → 5）。`SECTIONS` から `/quality` を削除。「一部は合成データ」の注記（`caveatBody("synthetic")`）を外す（合成を表示しなくなる）。`"measurements"` は `MEASUREMENTS_DATASET`。
- `api/documents/route.ts`: `docSeriesList(db, {minYears: 3})`・`docSeriesPoints`（cube）。応答の形は今のまま（snake_case、`label` は API が付ける）。`DocumentsExplorer.tsx`: `rowKeyLabel` を撤去し `label` を使う。
- `api/geo/watersheds/route.ts`: `watershedRollup(db)` 1 本。builtDelta 等の計算は今のまま（`landuse.from/to` から）。流域外は今のとおり。
- `MapPage.tsx`: events の `useJson`・`showEvents`・`ry-events` 重ね・トグルを撤去。流域の指標の凡例に `landuseDefinitionChange` を足す。
- `SiteNav.tsx`・`PageContextProvider.tsx`: `/quality` を削除。`/sites`・`/sites/[id]`・`/timeseries`・`api/timeseries`・`api/geo/sites` は `DATASET` 定数を import に置換するだけ（ロジック無変更）。

### 4.3 AI・探索面（U3）

- `ai/tools.ts`: `get_overview`（§0-6。`stats` は `{n_sites, n_variables, n_org, n_species, n_sources, n_watersheds, y_from, y_to}`、`watersheds` は `watershedRollup` の上位 N を v1 形（snake_case）に写す。`outside_watershed_n` は今のまま）。provenance の `tables`＝実際に読む表。注記＝`caveatKeysForTables(["sites","source_registry"])`＋`facetsForOccurrence`＋`variable_theme=landuse`（**測定値を返さなくなるので measuredOn/censored 等の注記は付かなくなる**。AI の応答の注記キーが動く点として §5 に記録）。`get_quality_progress` 撤去（`aiTools`・説明文・`run_sql` の説明の列挙）。`describe_schema`: 説明文を「カタログ表の一覧」に、`listTables` を `catalogOnly` で呼ぶ。`run_sql` の説明の「derived 系テーブルを使うこと」→「`summary_*`・registry 表を使うこと」。
- `ai/prompt.ts`: `get_quality_progress` の言及と「## 開示義務」（合成データ）を撤去。`variableVocabNote` の `"sensor_timeseries"` は `SENSOR_DATASET`。`__snapshots__/prompt.test.ts.snap` は更新（U3 が差分を目視して `-u`）。
- `lib/table-meta.ts`: §2.1。`SCHEMA_META` に `reg`（「語彙レジストリ DB」）を足し、registry 表（`unit`/`variable`/`variable_alias`/`place`/`place_source_ref`/`place_relation`/`place_watershed`/`taxon`/`taxon_assessment`/`caveat`/`caveat_scope`）・`occurrence_agg`・`summary_taxon_catalog`・`summary_watershed_occurrence` を `TABLE_ORIGIN`/`TABLE_META` に足す（今は欠けている）。`v2` の説明文の「measurements/sensor_timeseries 等を統合した」は表名を避けた言い回しに。
- `lib/db.ts`: `listTables({ catalogOnly?: boolean; counts?: boolean })`。`catalogOnly` は `TABLE_ORIGIN` のキーだけ。**`describe_schema` の一覧は `counts:false`**（今は 61 表すべてに `count(*)` を投げ 419 万行読む。`observation_agg` 200 万行・`occurrence_agg` 144 万行を含む）。表を指定したときの件数も `observation_agg`/`occurrence_agg` は取らない（null）。`/api/schema`（探索、閉じている）は従来どおり全表。
- `runUserSql(sql, maxRows, { catalogOnly })`: `catalogOnly` のとき、`sqlite_master` の実在表（isolate ごとに1回キャッシュ）から `TABLE_ORIGIN` のキーを引いた**カタログ外の実在表**の集合を実行時に導き、SQL 中の識別子（`extractTableNames` と同じ全識別子走査）がそれに当たれば `SqlError("この表は AI からは読めません（カタログ外）")`。**ソースに表名を書かない**（完了条件と両立）。PR-5 で DROP されればカタログ外の実在表は空になり自然に何も弾かなくなる。誤爆（文字列リテラル中の語）は許容（弾く側に倒す）。`tools.ts` の `run_sql` が `catalogOnly:true` で呼ぶ。
- `api/column/route.ts`: `EXPLORE_ENABLED` が false のとき `EXPLORE_DISABLED_MESSAGE` を 404 で返す（`api/table` と同じ。決定事項14・危険16件 #12）。`features.ts` のコメントに「`run_sql` はフラグでは止まらないが、カタログ外の表は読めない」を足す。

### 4.4 `SAMPLE_QUERIES`（U3）

v1 を指す 9 件のうち、地点一覧（`sites`）・文書セル（`cells`、`value_type IN ('int','float')` に直す。今の `'number'` は存在しない値で 0 行）・出典（`source_registry`）は残し、次を置き換える: 測定項目の一覧と期間 →`summary_variable_catalog ⨝ variable`、地点×年の水質平均 →`summary_place_variable ⨝ place ⨝ variable`（`value_grain`/`obs_stat` を明示）、生物年次推移 →`summary_group_year`、外来種 →`taxon_assessment`（`list_id='moe_ias_2015' AND in_scope=1`）⨝ `summary_species_catalog`、レッドリスト版間 →`taxon_assessment`、センサー時系列 →`observation_agg`（`variable_id='common:variable:weather.precipitation'`、`grain='day'`、`stat='sum'`）。各 SQL は D1 のローカル（`db:reset` 後）で1回ずつ実行して列名を確かめる（統合者のスモーク。テストは表名の部分集合だけ）。

## 5. 値が動く点の全列挙と serving-diff

### 5.1 値が動く点（実測）

| # | 動く点 | 範囲 |
|---|---|---|
| 1 | 文書系列の label（バグ①） | v2 に残る meta 414 行中 20 行 |
| 2 | 文書系列の `n_warnings`（バグ②） | 414 行中 245 行（減る方向のみ） |
| 3 | 割れる年を系列から除く（バグ③、D1=A） | 点 −336（140 系列に及ぶ）、meta −56（470→414）、`n_years`/範囲が変わる 5 |
| 4 | バグ④（裸列） | **動かない**（0 件） |
| 5 | 概況: `n_meas`/`n_sensor`/`n_events` の廃止（D2） | 3 列の廃止（画面のタイル・AI の `stats`） |
| 6 | 概況・流域の非生物列・土地利用 | **動かない**（差 0。`n_sites`/`n_sources`/`n_watersheds`/`y_*`/`area`/`centroid`/`site_n`/土地利用6列 × 377） |
| 7 | AI `get_overview` の注記キー | measuredOn/censored/duplicates/aboveLod が付かなくなる（測定値を返さない）。`landuseDefinitionChange` が付く |
| 8 | 土地利用の画面注記 | ホーム・`/map` に `landuseDefinitionChange` を出す（値は動かない） |
| 9 | 合成データの撤去 | 画面・API・AI ツールの消滅（serving-diff の対象外） |
| 10 | 年の上限（§7） | 今は動かない（最大年 2026）。2027 年以降の既定の窓が伸びる |

### 5.2 serving-diff（U4。v2 アダプタは §4.1 の関数を呼ぶ。生 SQL を持たない）

**新しい既知の系統（規則）3つ**（説明の鎖は「v1 →(規則)→ cells.sqlite からの別 SQL の再計算 →(=)→ v2」。再計算は新設 `scripts/lib/serving/docs-expect.ts` が `cells.sqlite` を `better-sqlite3` で直接読み、**`lib/cube` を import しない**）:

| 規則 | 動く点 | 説明の鎖 |
|---|---|---|
| `doc_label_rule` | #1 | v1 の `label` ＝ v1 の式（`build-derived.mjs` の `instr/replace` の式をそのまま SQL で再評価）の結果で、v2 の `label` ＝ `lastIndexOf('|')` の再計算。両方一致するときだけ説明。レポートに `moved`（キー数） |
| `doc_warning_scope` | #2 | v1 の `n_warnings` ＝ doc 単位の `COUNT(*)`、v2 ＝ `table_ids` の JSON を JS で解いた表単位の件数（再計算）。両方一致で説明 |
| `doc_year_collapse` | #3（D1=A） | 点: v1 のみに在る行は、`cells` の同じ `(doc,table,row_key,fiscal_year)` に値が2種以上ある（再計算）ときだけ説明。meta: v1 のみの行は、再計算した「値が1種の年」の数が 3 未満のときだけ、`n_years`/`y_from`/`y_to` の差は再計算の値と一致するときだけ説明。レポートに点・meta それぞれの `moved` |

**問い合わせ ID（新規4＋既存1の拡張）**:

| id | key | 比較列 | 既知の系統 |
|---|---|---|---|
| `doc_series_meta`（v1 `docSeriesList(3)`、v2 `docSeriesList`） | doc_id, table_id, row_key | n_years, y_from, y_to, page_no, n_warnings / label: label, unit, doc_title, publisher, url, license | `doc_label_rule`, `doc_warning_scope`, `doc_year_collapse` |
| `doc_series_points`（params: 470 系列ごと。domain `doc_series` は v1 の meta から列挙） | fiscal_year | value, page_no / label: unit | `doc_year_collapse` |
| `overview_counts` | （1行） | n_sites, n_sources, n_watersheds, y_from, y_to | （なし。v1 = v2。`n_meas`/`n_sensor`/`n_events` は比較しない。「廃止列」として yaml の `retired:` に3つ書き、レポートに1行） |
| `landuse_highlight` | watershed_id | delta, area_km2 / label: water_system_name | （なし） |
| `watershed_rollup`（**既存を拡張**。v2 は `watershedRollup(db)`） | watershed_id | org_n, org_alien_n, org_redlist_n（`watershed_memo`）＋ **site_n, area_km2, centroid_lat, centroid_lon, built/forest/paddy_km2_2006/2016**（既知なし） / label: water_system_name | `watershed_memo`（org 列だけ。列単位の鎖 `explainColumnChain` は PR-2 のまま） |

v1 側は `v1-queries.ts` の `docSeriesList`/`docSeriesPoints`/`overviewStats`/`landuseHighlight`/`watershedRollup`（`queries.ts` から無変更で移したもの）。`watershed_rollup` は v2 が全 377 流域を返すので、PR-3b の「v1 側の全 0 行を落とす」処理は外す（外した結果が差 0 であることが受け入れ）。

**撤去した画面・API の問い合わせ ID**: **無い**（品質・介入・意思決定・ペア測定・events は serving-diff の対象になったことがない。PR-1〜3b の ID 41 件はすべて残る）。`watershed_year`（画面の読み手なし、セルの一貫性確認）は PR-3b §6-5 の未決を「残す」で決着（`watershedYears` は `occurrence.ts` に残り、`web/src` の本番バンドルからは import されない）。

**変異の追加**:

| 変異 | 種別 | 何を狂わせるか | 期待 |
|---|---|---|---|
| `doc_label_rule_off` / `doc_warning_rule_off` / `doc_collapse_rule_off` | 分類器 | 各規則を無効化 | `doc_series_meta`/`doc_series_points` が unexplained>0 |
| `doc_label_wrong` | 行（v2） | v2 の1 label を再計算と食い違う文字列に | **規則が有効でも** unexplained>0（規則が「何でも説明する」穴でないこと） |
| `doc_drop_point` | 行（v2） | 値の割れていない年の点を1つ落とす | row_only_in_v1 → unexplained>0（`doc_year_collapse` は割れた年だけを説明するので落ちる） |
| `inflate_site_n` | 行（v2） | `watershed_rollup` の `site_n` と土地利用1列に +1 | 説明する規則が無い → unexplained>0 |
| `inflate_n`（既存）を `overview_counts` にも適用 | 行 | n_sites +1 | unexplained>0 |

`rowMutationAppliesTo` の宣言表（`mutations.ts`）に対象 ID を必ず書く（表に無い名前は全問い合わせに効くので、`doc_*` は doc の2 ID、`inflate_site_n` は `watershed_rollup` に限る）。

### 5.3 受け入れ表（PR 本文に貼る）

| # | コマンド（重い検証、PR 直前に1回） | 期待 |
|---|---|---|
| 1 | `pnpm run serving:diff --v1compat-db data/db/v2_v1compat.sqlite --imputation zero --mutate all` | 既存 41（うち `watershed_rollup` は拡張）＋ 新規 4 の計 45 の全 ID で `unexplained=0`・rotten=0。全変異が OK。**`lod_rule_off` は zero では対象外としてレポートに「skipped（lod のみ）」と出る**（§7-1） |
| 2 | `… --imputation lod`（`--mutate lod_rule_off`） | 同 `unexplained=0`。PR-4 の ID は imputation に依らないので PR-2 の測定値系の回帰確認のみ |
| 3 | レポートの規則ごと `moved`: `doc_label_rule`≈20・`doc_warning_scope`≈245・`doc_year_collapse` 点 336／meta 56＋5、「差 0」の ID（`overview_counts`・`landuse_highlight`・`watershed_rollup` の非 org 列）は 0 のまま | 実測（付録）と一致 |
| 4 | `pnpm test`・`npx tsc --noEmit`・`pnpm lint`（`v1-references.test.ts` が緑、§2.2 の変異で赤→緑） | 緑 |
| 5 | `cd web && pnpm run db:generate`（0009 は `CREATE INDEX ix_cells_series` のみ）→ `pnpm run db:reset` → スモーク（§8.3） | `/documents`・`/`・`/map` が動き、`/quality`・`/api/quality`・`/api/geo/events` が 404、`/api/column` が閉じている |

b00・pytest は回さない（パイプラインのパス・`aggregations/`・`scripts/` に触れない。`git diff --name-only` に `scripts/b0*`・`scripts/registry/`・`aggregations/` が無いことを統合者が確認してから省略する）。

## 6. 撤去するファイル

| 種別 | パス |
|---|---|
| ページ | `web/src/app/quality/page.tsx` |
| コンポーネント | `web/src/components/quality/QualityDashboard.tsx` |
| API | `web/src/app/api/quality/route.ts`・`web/src/app/api/geo/events/route.ts` |
| lib | `web/src/lib/quality.ts`（`QUALITY_STAGES`。CLAUDE.md の該当記述は統合者が直す）、`components/viz/palette.ts` の `QUALITY_STAGE` |
| `queries.ts` から（v1 関数は `v1-queries.ts` へ、合成・品質の関数は `v1-queries.ts` にも持たない＝削除） | `qualityMonthly`・`qualityByActor`・`interventions`・`decisions`・`observerStats`・`instrumentStats`・`pairedMeasurements`・`qualityTotals`・`instrumentList`・`protocolList`（serving-diff の対象外なので移さず削除）、`landuseChange`（読み手ゼロ） |
| AI | `get_quality_progress`（`tools.ts`）、`ToolResultCard.tsx` のラベル、`prompt.ts` の言及と「開示義務」 |
| ナビ・導線 | `SiteNav.tsx`・`PageContextProvider.tsx` の `/quality`、`app/page.tsx` の `SECTIONS` の1件、`MapPage.tsx` の events 重ね |
| テスト | 上記を読むテストがあれば（`grep` で確認）。`prompt.test.ts.snap` は更新 |
| 残す | `queries.ts`（`docNotes`・`documentsList`・`blockingNotes`・`sourceRegistry`・Tier 1）、`/api/documents`・`/api/nature`・`/api/geo/{protected-areas,vegetation,river-segments}` |

v1 関数の移動先 `web/scripts/lib/serving/v1-queries.ts`（U4。`queries.ts` の v1 関数を**無変更で**コピーし、`import "server-only"` を外し `import { query, queryOne, queryChunked, ph } from "../v1-db-shim"` に変えるのが唯一の変更）。`adapters-v1.ts` の import 先を変える。`register-aliases.mjs` の `db.ts` 書き換えと `v1-db-shim.ts` 冒頭の説明は、不要になった分を整える（`server-only` の差し替えは残す）。

## 7. 小さな負債（PR-3b の申し送り）

1. **`serving:diff --mutate all` が zero 実行でも `lod_rule_off` を当てて NG になる**: `mutations.ts` に変異ごとの「要る imputation」表（`lod_rule_off: "lod"`）を持たせ、`serving-diff.mts` の `MUTATE_NAMES` 展開で、現在の imputation で意味を持たない変異を `skipped` として除外（レポートに「skipped: lod_rule_off（zero 実行では対象外）」と出す。個別名で明示指定した場合は除外せず従来どおり当てる）。単体テスト: zero で `all` を展開すると `lod_rule_off` が入らず、lod では入る。
2. **`iasSpecies` の `2020`**: これは「2020 年以降」という**固定の節目の列**（画面の見出しが `2020年以降`）で、ローリング窓ではない。定数 `IAS_SINCE_YEAR = 2020`（`lib/cube/sql.ts`）を1か所に置き、SQL は `o.period_start >= ?` にバインド、列名は `nSince`・`sinceYear` を返し、API（`api/biota`）と UI の見出しがそこから出す。v1（`b08` の `n_since_2020`）との比較は adapter で `nSince → n_since_2020` に写す（v1 の列名は変えない）。
3. **既定の窓の `2026`**: `OCC_DEFAULT_TO = 2026` を `occDefaultTo(now = new Date())`（現在年。`now` を注入できる）に。`catalog.ts`/`occurrence.ts` の呼び出しはこの関数。`MESH_YEAR_FROM`（1970）は v1 の窓なので定数のまま。v1 側の `2026` は oracle なので触らない（今のデータは最大年 2026 なので差は出ない。2027 年以降は v1 がずれるが PR-5 で v1 側ごと消える）。テスト: `now` を 2027 にして窓の上限が 2027 になること。**注意**: 日付の誤記（未来年）が現在年まで表示される——今は 2026 超のセルが無いので影響なし（付録）。

## 8. 作業の分け方

### 8.1 並行単位（worktree、ファイル衝突なし）

| 単位 | 触るファイル | 読むべき節 | 依存 |
|---|---|---|---|
| **U1 `lib/cube`＋schema** | `web/src/lib/cube/{documents(新),catalog,sql,series,observation,db-sqlite,index}.ts`＋各 `.test.ts`・`__fixtures__`、`web/src/db/schema.ts`（`cells` の部分索引のみ。表の削除はしない）、`web/src/lib/registry/lookup.ts`（`MEASUREMENTS_DATASET` import） | 本書 §3.1・§3.3・§4.1・§7-2/3、`V2_SERVING_PR3B.md` §2.2（`watershedOccurrence`）・§4（`INDEXED BY` の理由） | なし。**最初のコミットで §4.1 の型とスタブだけ出す** |
| **U2 画面・API** | `app/page.tsx`・`app/documents/*`・`api/documents/route.ts`・`api/geo/watersheds/route.ts`・`api/geo/sites/route.ts`・`api/timeseries/route.ts`・`app/sites/**`・`app/timeseries/page.tsx`・`components/{HomeHighlights.tsx,documents/*,map/MapPage.tsx,SiteNav.tsx,assistant/PageContextProvider.tsx,assistant/tool-ui/ToolResultCard.tsx}`・`components/viz/palette.ts`・`components/biota/BiotaExplorer.tsx`（`IAS_SINCE_YEAR` の見出し）・`api/biota/route.ts`、**削除**: `app/quality`・`components/quality`・`api/quality`・`api/geo/events`・`lib/quality.ts` | 本書 §4.2・§6 | U1 の型 |
| **U3 AI・探索面・参照ゼロ** | `lib/ai/{tools,prompt}.ts`＋スナップショット・テスト、`lib/table-meta.ts`、`lib/db.ts`、`api/column/route.ts`、`lib/features.ts`（コメント）、`lib/queries.ts`（§6 のとおり縮める）、`web/src/lib/v1-references.test.ts`（新） | 本書 §2・§4.3・§4.4・§6 | U1 の型。`queries.ts` を縮めるので、U4 が `v1-queries.ts` へ移す元は **`git show HEAD:web/src/lib/queries.ts`**（U3 の編集に依らない） |
| **U4 serving-diff** | `web/scripts/lib/serving/{v1-queries(新),adapters-v1,adapters-v2,docs-expect(新),classify,mutations,normalize,report,register-aliases.mjs}`＋各テスト、`web/scripts/lib/v1-db-shim.ts`（説明）、`web/scripts/serving-diff.mts`、`web/serving_queries.yaml`、`reports/serving_switch_diff*`（出力のみ） | 本書 §5・§6 末尾・§7-1、`V2_SERVING_PR2.md` §3・§8.4、`V2_SERVING_PR3B.md` §3・§5.4 | U1 の公開関数 |

統合順: U1 → U2 ‖ U3 ‖ U4 → §8.4 のチェック → 重い検証（§5.3）。`pnpm run db:generate` は統合者が1回（`0009`）。**担当エージェントは `drizzle/migrations` を触らない**。`docs/plans/V2_SERVING.md` の PR-4 節の状態・ADR-0029（3規則）・ADR-0017（品質デモの撤去）・ADR-0011（`doc_series` の行き先＝問い合わせ時 SQL、`quality_monthly` の廃止）・CLAUDE.md（`lib/quality.ts` の記述）の更新は統合者が1回でまとめて行う。

### 8.2 各単位の速い検証（秒〜1分）

- U1: `pnpm vitest run src/lib/cube`（フィクスチャ。`documents` は割れた年・全 `|` の label・`table_ids` 空/表指定・`page_no` の決定性。EXPLAIN 固定: `ix_cells_series`・`ix_observation_agg_place_variable_grain`）。実 DB の統合テスト（`data/db` がある環境だけ）は `watershedRollup` の 377 行の1列比較と `docSeriesList` の件数 414。
- U2: `pnpm exec tsc --noEmit`、`pnpm run dev` で `/`・`/documents`（1 系列を開く）・`/map`（流域指標・events トグルが無いこと）の目視。
- U3: `pnpm vitest run src/lib/ai src/lib/v1-references.test.ts`、`pnpm exec tsc --noEmit`。
- U4: `pnpm vitest run scripts/lib/serving`、`pnpm run serving:diff --only doc_series_meta,doc_series_points,overview_counts,landuse_highlight,watershed_rollup`（数十秒）。

### 8.3 PR 直前に1回だけ回す重い検証

§5.3 の 1〜5 の順。メインが裏で1回回し、エージェントには待たせない。スモークは `db:reset` 後に、`/`・`/documents`・`/map`・`/sites`・`/timeseries`・`/biota` の表示と、AI の `get_overview`・`describe_schema`（件数なし）・`run_sql`（カタログ外の表を引く SQL が `SqlError`、`summary_*` は通る）・`/api/column` の閉鎖。/code-review と /simplify は同時に回し、指摘をまとめて1回で直す。

### 8.4 統合の最初のチェックポイント「検証が本番の経路を通っているか」

自動1件＋レビュー6項目。

- 自動: `adapters-v2.test.ts` の「生 SQL を持たない」検査を拡張し、`adapters-v2.ts` のソースに `cells`/`notes`/`documents`/`place`/`observation_agg` の表名が **SQL 文脈で**出ないことを確かめる（PR-3b の `occurrence_agg`/`summary_` と同じ書き方）。
- レビュー: (1) v2 アダプタの `doc_series_*`・`overview_counts`・`landuse_highlight`・`watershed_rollup` が、`api/documents`・`app/page.tsx`・`api/geo/watersheds`・`get_overview` と**同じ関数・同じ既定値**（`minYears: 3`・`limit: 8`・`watershedRollup(db)` 1本）で呼んでいる対応表を PR 本文に貼る。(2) `label` を作る場所が `rowKeyLabel` の1つで、API・UI・アダプタに複製が無い（grep `lastIndexOf("|")`）。(3) `docs-expect.ts` が `@/lib/cube` を import していない・v1 の式は `build-derived.mjs` から**そのまま**（書き直していない）。(4) `v1-queries.ts` が `queries.ts` の v1 関数と import 行以外で一致（`diff <(git show HEAD:web/src/lib/queries.ts) …` の差分が import 行と削除分だけ）。(5) `v1-references.test.ts` の許可リストが §2.2 の6件だけ・理由つき・変異で赤くなる。(6) `watershed_rollup` の v2 が全 377 流域を返し、v1 側の「0 行を落とす」処理が消えている（残っていると流域外の取りこぼしを見逃す）。

## 9. 危険・未決事項

1. **D1（col_key）の A は系列を 56 本失う**。データの欠陥（抽出側）の可視化であって失ったのではない旨を `/documents` の注記か PR 本文に書く。`doc_year_collapse` が数えるので黙って消えない。B を採るなら §3.1 の `ambiguous` と UI を足す。
2. **部分索引の述語の一致**。`WHERE` を1文字違えると使われず全走査（正しいが rows_read が 119,533 に戻る）。`DOC_SERIES_WHERE` の共有定数と EXPLAIN テストで塞ぐ。drizzle-kit が部分索引を出せない場合は §3.1 の代替。
3. **`run_sql` のカタログ外判定は識別子の全走査**。文字列リテラル中の語で誤爆しうる（弾く側に倒す）。`sqlite_master` を引く1往復が増える（isolate ごとにキャッシュ）。PR-5 で DROP されれば集合が空になり無害。
4. **`describe_schema` の一覧から件数を消す**ため、AI が「このテーブルは何行」を答えられなくなる。件数が要る表は `run_sql` の `count(*)`（カタログ内のみ）。
5. **`/api/schema`（探索）は閉じているが全表を列挙する**（PR-5 まで）。`EXPLORE_ENABLED` を戻す前に PR-5 を済ませる。`features.ts` のコメントに書く。
6. **`generated-client.ts` に派生表名の table スコープ行が PR-5 まで残る**。`caveatKeysForTables` を派生表名で呼ぶ経路が web に無いこと（U3 が grep で確認）。呼べば黙って古い注記が出る。
7. **`landuseDefinitionChange` をホーム・地図に出す**文言の置き場所（既存の注記の再掲）。注記本文は registry のまま（画面ごとに個別対応を書かない）。
8. **`cells` の索引追加は本番 D1 の DROP と無関係**だが、PR-5 の本番切り替え手順（投入→コード→DROP）に「`0009` は投入の後・コードの前でよい」を1行足す（統合者）。
9. **本番へは出さない**（v1 撤去が終わるまで本番にデプロイしない）。

---

## 付録: 実測の記録（2026-10-05、読み取り専用）

```
参照洗い出し（web/src、テスト・fixture 除く）: 素の単語一致は 36 ファイル。A（SQL 文脈）＋B（引用符完全一致）に絞ると
  queries.ts(A 約 60)・tools.ts(B 12)・table-meta.ts(A 4)・MapPage.tsx(B 1: events)・generated-client.ts/generated.ts・schema.ts・
  dataset 定数（"measurements"/"sensor_timeseries"/"organism_records"/"taxa"）の 20 ファイル弱。CSS クラス・変数名の偽陽性は 0。
cells.sqlite: cells 119,533・notes 207・documents 98。数値セル（共通の入力条件）4,361。
  グループ（doc,table,row_key,fiscal_year）3,590（col_key まで含めると 3,680）。n_cells>1 は 344 グループ、うち値が割れるもの 336、
  col_key も割れるもの 57（col_key だけでは直らない 281）。同じ col_key 内で値が割れるもの 281/287。
  v1 doc_series_meta 470（HAVING n_years>=3）。A 案: 点 3,254・meta 414・n_years>=4 は 434→390。meta から消える 56 の元 n_years 内訳 5:37・3:12・8:5・4:2。
  label: 全 `|` 2個以上の row_key は meta 20 行（label が変わるのも 20）。n_warnings: blocking 132 件、table_ids 空/[] が 104 件。
  SQLite 30ms（部分索引あり）／54ms（なし）。`ix_cells_doc(doc_id,page_no,table_id)` のみでは doc_id 単位の SEARCH。
watershed: place(kind=watershed) 377 と derived.watershed_rollup の name/area/lat/lon が 377/377 一致。site_n は place_relation（parent=watershed, child=site）
  で 377/377 一致（Σ=278）。土地利用 6 列（建物・森林・田 × 2006/2016、stat=mean、value_zero）が 377/377 一致。観測のある流域 348。SQL 4ms。
  上位 8 の建物用地増: 5.92, 5.65, 5.30, 5.18, 3.84, 3.61, 3.20, 3.17（同点なし）。
概況: v1 n_meas 323,164・n_sensor 717,839・n_events 29,947（うち合成 676）・n_watersheds 377・var_catalog 年 1973–2026。
  v2: summary_variable_catalog 119 行・DISTINCT variable_id 75・年 1973–2026。observation_agg（stat mean/sum/point）の Σn 内訳:
  day/day 550,287・day/hour 416,062・fiscal_year 102,099・month 7,674（入力 month）・year/year 3,286 → 行数にならない（L2 は 1,019,318 行）。
registry: place 4,087(grid01)+495(site)+377(watershed)+5(zone)、place_relation 568（within: 流域 278・zone 290）、place_watershed 377。
instruments 26・protocols 6（読み手は /quality のみ）。
describe_schema の count(*): 61 表で 419 万行読む（observation_agg 2,000,000・occurrence_agg 1,437,598 が大半。v2 実測）。
窓: occurrence の年は 1800〜2026（2026 超なし）。
```

---
## 設計責任者の決定（2026-10-05）
- **D1〜D3 はオーナーが推奨どおりに決定**（D1: A＝値が割れる年を系列から除く。D2: タイルを「観測指標 N 種」に置き換え、センサー・イベントを外す。D3: `instruments`/`protocols` は画面ごと撤去し、PR-5 で表も落とす）。
- 並行: U1〜U4 を同時に始める。U2〜U4 は §4.1 のシグネチャで書く。U1 は最初のコミットで型とスタブを出す。
- 全担当共通: スキル（/simplify・/code-review 等）やサブエージェントを起動しない。重い検証（build:v2・b00・serving-diff の全量・CI 再現）は回さない。`drizzle/migrations` を生成・コミットしない。worktree には原本だけを1ファイルずつ symlink し、生成物は worktree 内に書く。`git add -A` を使わない。

---
## 実測の記録（統合後、2026-10-05）
- serving-diff 全量: zero（`--mutate all`）・lod（`--mutate lod_rule_off`）とも unexplained=0・rotten=0。変異 24 種 OK、`lod_rule_off` は zero では skipped。
- 規則ごとの moved（`reports/serving_switch_diff.md`）: `doc_label_rule` 20（doc_series_meta）、`doc_warning_scope` 245（doc_series_meta）、`doc_year_collapse` 61（doc_series_meta）・243（doc_series_points）。`watershed_rollup` は 377 行中 191 一致・186 が `watershed_memo`（moved）。
- 統合後の修正（レビュー A〜I）:
  - A: `rowKeyLabel`／`expectedRowKeyLabel` に `.trim()` を戻した（空白だけの後ろは row_key 全体）。
  - B: 期待 page_no を v2 の定義（年ごとの MIN の年またぎ MAX）に揃え、v1 の page_no（不定）は v2 が期待値と一致すれば説明済みにした（meta・points とも）。
  - C: `get_overview` の重複呼び出し `watershedOccurrence` を外した。
  - D: `IasSpeciesRow.sinceYear`（読み手なし）を削除した。
  - E: `docSeriesPoints` の CTE 内で doc/table/row を絞り、部分索引の先頭3列が効くようにした。
  - F: 土地利用の差分を `landuseDelta` に一本化した。
  - G: `/api/geo/watersheds` が `landuse_years` を返し、地図のラベルの年を固定文字列でなくした。
  - H: `listTables` を `rowCount: number | null` の単一シグネチャにした。
  - I: `features.ts`・`page.tsx`・`assertCatalogOnly` のコメントを整理した。
- スモーク: `/` `/documents` `/map` `/sites` `/timeseries` `/biota` は 200、`/quality` `/api/quality` `/api/geo/events` `/api/column` は 404。ホームのタイルは5枚（観測指標 75 種・日付のある生物レコード 816,856）。
- b00 は省略（パイプラインのパスに触れていない。`git diff --name-only 9890e37` に `scripts/b0*`・`scripts/registry/`・`aggregations/` が無い）。
