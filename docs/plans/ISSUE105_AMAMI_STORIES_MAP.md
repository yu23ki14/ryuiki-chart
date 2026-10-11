# Issue #105: 奄美の地図レイヤー（土砂災害警戒区域・保護区）と物語ページ

オーナー決定（2026-10-11）: 地図レイヤーと物語ページの**両方**を作る。#93（地域切替）・#96（A10/A15/A45）・#104（`hazard_zones`）は入っている。
2026-10-11 に設計担当が読み取り専用で実データを確かめた。数字はすべてその実測。

## 0. 実測で Issue の記述と変わった点

1. **物語 1・2・3 の値のうち、豪雨の被害・雨量（`fiscal_year=NULL` の単発セル）と、流域治水のダム容量には、型のある読み手がまだ無い。** `docSeriesList/docSeriesPoints`（`web/src/lib/cube/documents.ts`）は `fiscal_year` が非 NULL の系列だけ。`get_records` の `documents`/`document_notes` は在るが `document_cells` は無い。残るのは `run_sql`（と閉じている `/explore`）だけ。→ **`records.ts` に `document_cells` を足す**（§3-0）。画面専用 SQL を書かない（ADR-0014）。
2. **土砂災害の市町村別・現象別の件数を出す既存の問い合わせは無い。** `get_records` は一覧のみ（集計なし、一覧にジオメトリなし）。→ **`records.ts` に件数の集計関数を足す**（§3-3）。ページに SQL を書かない。
3. **「短く急な川」を裏づける出典の値は、データに無い。** `river_segments` は神奈川（相模川水系）だけ。奄美の流路長・勾配の表は取り込んでいない。使える事実は京大速報の「二級河川の数（奄美大島）33・氾濫した二級河川 30」（`dpri_amami_gouu_sokuho_2011`）まで。章題は「島の川と土砂災害」とし、「短く急」とは書かない（§5 メイン決定 3）。
4. `hazard_zones` の `source_id`（`bodik_kagoshima_dosha_amami`）の `access.yaml` には `note` が無い（A10/A15/A45 には #96 で入っている）。入れ子・面積を足さない注意はまだ機械的に付かない。→ 担当1が足す（§2-5）。
5. `MapCanvas` は表示範囲（moveend）を外に出さない（`fitTo` の一方向のみ）。bbox で絞るには `onViewChange` を足す必要がある（担当2）。

## 1. PR の切り方と担当

**推奨: 1本の PR、3担当を worktree で並行**。理由: `web/src/lib/records.ts`（`document_cells` の追加、範囲絞り、件数集計）が地図 API と物語ページの両方の土台で、`get_records` の説明文を変えるので `web/src/lib/mcp/__snapshots__/tools.test.ts.snap` と `web/src/lib/ai/__snapshots__/prompt.test.ts.snap` が1回だけ動く。2本に割ると同じスナップショットを2度動かし、records.ts が衝突する。PR が大きすぎると判断するなら、担当1の API 部分＋担当2を PR-A、担当1の `document_cells`/件数集計＋担当3を PR-B（A が先）に割れる（契約は §1.1 で固定してあるので割っても崩れない）。

| 担当 | 範囲 | 触るファイル（衝突しない） |
|---|---|---|
| 1 データ層・API・registry | records.ts の拡張、地図 API 2本、access.yaml の note | `web/src/lib/records.ts`・`records.test.ts`、`web/src/app/api/geo/hazard-zones/`、`web/src/app/api/geo/protected-areas/polygons/`、`registry/source/access.yaml`、`web/src/lib/registry/generated*.ts`（再生成）、`web/src/lib/mcp/__snapshots__/`・`web/src/lib/ai/__snapshots__/`（差分を目で確かめる）、`data/sample` は触らない |
| 2 地図 UI | 凡例・レイヤー・URL の `layers` | `web/src/components/map/MapCanvas.tsx`・`MapPage.tsx`、新規 `web/src/lib/map/overlay-layers.ts`・`web/src/components/map/OverlayLegend.tsx` |
| 3 物語ページ | `/stories/amami` と導線 | 新規 `web/src/app/stories/amami/page.tsx`・`web/src/components/stories/*`・`web/src/lib/stories/amami.ts`、`SiteNav.tsx`、`HomeHighlights.tsx`（奄美のときのリンク1つ）、`app/page.tsx` は触らない |

### 1.1 担当をまたぐ契約（先に固定。担当1が最初のコミットでシグネチャを置く）

- `records.ts`: `readRecordSet(db, "document_cells", { eq: [{col:"doc_id", value}], select, order })`（既存の形のまま。担当3が呼ぶ）。
- `records.ts`: `countRecordsBy(db, set, groupBy: string[], opt?: {eq?}) : Promise<Array<Record<string, string|number|null> & { n: number }>>`。`groupBy` は表ごとの許可リスト（`hazard_zones`: `municipality_ja`・`phenomenon_ja`・`zone_kind_ja`、`protected_areas`: `category_code`・`source_id`）。それ以外は例外。件数のみ（面積は返さない）。
- `records.ts`: `ReadRecordOptions.range?: {col: string; min: number; max: number}[]`（許可リストの数値列だけ。`hazard_zones`: `centroid_lat`/`centroid_lon`、`protected_areas`: `lat`/`lon`）。
- 地図 API の URL（担当2が呼ぶ）: `GET /api/geo/hazard-zones?bbox=w,s,e,n[&kind=warning|special_warning][&phenomenon=debris_flow|steep_slope|landslide]`、`GET /api/geo/protected-areas/polygons?source_id=<id>[&bbox=w,s,e,n]`。応答は GeoJSON FeatureCollection に `truncated: boolean`・`sources: [{source_id, note, license}]` を足したもの。
- 地図の URL: `/map?region=jp-46&layers=hazard,pa_a10,pa_a15,pa_a45`（担当3の物語ページがリンクする）。`layers` に無い名前は無視。

## 2. 地図レイヤー

### 2-1 API（`/api/geo/hazard-zones`）

- 前例は `vegetation`（`readRecordSet` で `withGeometry`、`limit`・`Cache-Control: public, max-age=300`）。同じ形に揃える。`bbox` は**必須**（無ければ 400）。全件（6,038 件・約 4.7MB）を返す経路を作らない。
- bbox の当て方: `centroid_lat`/`centroid_lon`（代表点、必ずポリゴンの内側）が bbox を**0.012 度広げた**範囲に入る行。実測で最大のポリゴンの外接幅が 0.0112 度（約 1.2km）なので、この余白で画面に掛かるポリゴンを取りこぼさない。上限 2,500 件（`maxLimit`）、超えたら `truncated: true`。並びは `zone_id`（安定）。
- ジオメトリは**単純化しない・座標を丸めない**。1 ポリゴン最大 239 頂点・平均 33 頂点、1 件平均 約 0.8KB なので、2,500 件でも約 2MB（gzip 後 約 0.5MB）。D1 での単純化はできず、ETL でもう1列持つのは過剰。
- 表示の下限ズーム 11（`MIN_ZOOM`、`overlay-layers.ts` に1か所）。島全体（zoom 約 9）では取りに行かず「拡大すると表示される」を凡例に出す。
- D1 の読み行数: 範囲条件の列に索引は無いので 1 リクエストで 6,038 行を走査する。キャッシュのために bbox は 0.05 度の格子に**外向き丸め**してから送る（クライアント側、担当2）。索引は足さない（スキーマ変更とマイグレーションを避ける。`rows_read` が問題になったら別 Issue）。
- バインドパラメータは `source_id`＋範囲4＋任意の絞り2＋limit・offset で 10 個未満。`queryChunked` は要らない。

### 2-2 API（`/api/geo/protected-areas/polygons`）

既存の `/api/geo/protected-areas`（点）は**契約を変えない**。別のパスで足す。`source_id` は必須（`nlni_a10_natparks_amami`・`nlni_a15_wildlife_amami`・`nlni_a45_forest_amami` のどれか）。

| source | 件数 | ジオメトリの合計 | bbox |
|---|---|---|---|
| `nlni_a10_natparks_amami`（category: `natpark_area` 9・`natpark_special` 50・`natpark_special_protection` 2） | 61 | 約 0.78MB | 不要（全件） |
| `nlni_a15_wildlife_amami`（`wildlife_reserve` 19・`wildlife_special_protection` 1） | 20 | 約 0.11MB | 不要（全件） |
| `nlni_a45_forest_amami`（`national_forest`） | 940 | 約 1.8MB | **必須**（`lat`/`lon` の代表点＋余白 0.05 度。担当1は小班の外接幅の最大を実測して余白を決め、テストに残す） |

- A10 は `natpark_area` ⊃ `natpark_special` ⊃ `natpark_special_protection` の入れ子。応答の properties に `category_code`・`category_ja`・`area_ha` を入れ、描画順（外側から内側）と色の濃淡は担当2が `category_code` で決める。
- 地域の絞り: 神奈川の保護区（`hiratsuka_parks` 等）は点・ポリゴン無し。`source_id` を奄美の3つに**固定**する（`protected_areas` を `source_id` 無条件で読まない）。神奈川を `?region=jp-14` で選んでいるときは UI がこれらのレイヤー自体を出さない（§2-4）。

### 2-3 配色（`web/src/components/viz/palette.ts` の既存の値だけ）

- 警戒区域＝`STATUS.warning`（#fab219、黄）、特別警戒区域＝`STATUS.critical`（#d03b3b、赤）。国の標識の慣習（黄・赤）とも合う。STATUS は「系列に流用せず必ずラベル」の規約なので、**凡例に必ず文字ラベルを添える**（色だけにしない）。
- 重ね順: 下から `警戒区域の面（opacity 0.45）` → `特別警戒区域の面（0.6）` → 線（白 `INK.surface`、0.6px）。特別警戒は警戒の内側にあるので、レイヤーを2つに分け（`filter: ["==", ["get","zone_kind_code"], …]`）特別警戒を後に積む。凡例も「特別警戒区域は警戒区域の内側にある」と書く（出典の note。§2-5）。
- 現象（土石流／急傾斜地の崩壊／地滑り）は**色で分けない**。チップの3択（既定は全部）で絞り、ポップアップに文字で出す。理由: 区分が STATUS の2色を使うので、現象にまた色を足すと 3×2 の組合せが読み分けにくい。**足りない**: 現象3種×区分2種を同時に色で塗り分ける検証済みの配色は palette.ts に無い。Issue の「区分と現象で色を分ける」を色で満たすなら `dataviz` の `validate_palette.js` で組合せを検証してから足す（§5 メイン決定 1）。
- 保護区（地図に同時に見える数は3以内。`MAX_SERIES_ALLPAIRS`）: A10＝`SERIES[0]`（青、`natpark_area`→`natpark_special`→`natpark_special_protection` を opacity 0.15→0.30→0.50 の濃淡）、A15＝`SERIES[2]`（緑、保護区 0.3・特別保護地区 0.5）、A45 国有林＝`SERIES[6]`（紫、0.3）。`SERIES[0]` は同じ地図の河川の線と同じ色なので、河川が ON のときは線の色を変えずそのままにし、保護区は**線なし・面のみ**にして区別する。**警戒区域（黄・赤）との同時表示でこの3色の組合せが安全かは未検証**——担当2は組合せを `validate_palette.js` に掛けて結果を PR に貼る。通らなければ A45 を線のみに落とす。
- 保護区は警戒区域の下に描く（`警戒区域` が常に読める）。

### 2-4 地域切替との関係

- `?region=jp-46`（RegionSwitcher）に連動: 奄美大島を選ぶと既存どおり `regionBounds` へ移動。レイヤーの出し分けは `overlay-layers.ts` の宣言 `{ id, label, sourceIds, minZoom }` で持ち、**表示する地域は出典の地域（`web/src/lib/cube/region.ts` の `sourceInRegion`）から機械的に決める**（手書きの地域リストを持たない）。現状は4レイヤーとも jp-46 のみ→ `region=jp-14` では切替パネルから消す。`region=all` では出す（地図は神奈川の表示のまま、ズームして奄美へ行けば bbox 取得が始まる）。
- `layers` の URL 同期は `applyRegionParam` と同じ流儀（`useSearchParams` から読む／`router.replace`）。`MapPage` の既存の `showWatersheds/showSites/showMesh/showRivers` の `useState` と並べて持つ。

### 2-5 注意書き（機械的に付ける）

- API 応答の `sources[].note` を凡例の下にそのまま出す。`note` は `registry/source/access.yaml` が正で、A10/A15/A45 は #96 で入っている（A10「3レイヤは入れ子なので category_code をまたいで area_ha を足さない」、A15「2009年版。20件中19件は版の時点の指定期間が 2018 年までに満了」、A45「2018年度版。民有林は含まない」）。
- 担当1が `bodik_kagoshima_dosha_amami` の `note` を足す: 「奄美5市町村（2026-02-10 現在、BODIK、CC BY 4.0）。特別警戒区域は警戒区域の内側にあり、警戒と特別警戒は重なる。区分・現象をまたいで面積を足さない。件数は区域（ポリゴン）の数で、地区・箇所の数ではない」。`pnpm run build:registry:ts` で `generated*.ts` を作り直し、`describe_catalog` のスナップショット（`tools.test.ts.snap`）の差分は note の1行だけであることを確かめる。r01 の実行は担当1の worktree で（`RYUIKI_REGISTRY_DB` は worktree 内）。
- 凡例は A10 の面積を出さない（足させない）。ポップアップの `area_ha` は「この区域の面積」と添える。
- 取得が `truncated` のときは凡例に「表示範囲に収まらない分は省略した。拡大すると出る」を出す。ズームが `MIN_ZOOM` 未満のときは「拡大すると表示される」。

## 3. 物語ページ

**URL: `/stories/amami`（推奨）**。理由: 物語は奄美の話で、`?region=` で神奈川に切り替えても意味を持たない。`/regions/jp-46/story` は地域切替の概念（全体／神奈川／奄美の絞り）と紛れる。`SiteNav` には「奄美の物語」を足し（`withRegion` は使わず固定で `/stories/amami?region=jp-46`）、`HomeHighlights` は `region === "jp-46"` のときだけ入口を1つ出す。サーバコンポーネント（`app/page.tsx` と同じ `force-dynamic`、`d1CubeDb()` から lib を直接呼ぶ）。チャートは `LineChart`・`ColumnChart`（`web/src/components/viz`）。画面専用の集計は書かない。

### 3-0 `document_cells`（担当1。物語 2 と流域治水の土台）

`records.ts` の `RECORD_TABLES` に足す（`document_notes` の隣、`sourceless: true`）: `table: "cells"`、`pk: "id"`、`search: ["doc_id","row_key"]`（`q` に doc_id を渡して引く。`document_notes` と同じ流儀）、`cols: ["id","doc_id","page_no","table_id","row_key","col_key","value_raw","value","value_type","unit","fiscal_year","source_text","is_total"]`、`base: { join: "", where: "cells.superseded = 0" }`（`base` の形は `vegetation` ではなく `sites` の前例を見て合わせる）。`RECORD_SET_NAMES` が `Object.keys` なので `get_records` の enum に自動で載る＝MCP・AI も同じ層で読める。`recordsInputSchema` の `record_set` の説明に `document_cells` を足す（スナップショット2つが動く。`vitest -u` でなく差分を目で確かめる）。`records.test.ts` が DDL と列を突き合わせる。

### 3-1 章1: マングースの根絶

- 系列（`docSeriesPoints(db, "moe_mongoose_catch_h12r4", "p1_t1", rowKey)`）。実測: `わな捕獲|CPUE`＝22点（2001〜2022。2000年度は値 NULL）、`わな捕獲|捕獲頭数`＝23点、`総捕獲頭数`＝23点、`わな捕獲|のべわな日`＝23点、`探索犬|探索犬による捕獲頭数`＝（導入前の空欄を除く）。row_key の `|` を含む全体を渡す。
- 図: ① 総捕獲頭数（柱、頭）② CPUE（線、頭/1,000わな日）の2枚。単位が違うので重ねない。2000→2001 の点の欠けと CPUE の合計行（`is_total=1`、除外済み）は `docSeriesPoints` が既に処理する。実測値の例: 2000年度 3,884 頭、2005年度 2,591 頭、2010年度 311 頭（総 312）、2018年度 1 頭、2022年度 0 頭。
- 注記は `docNotes(db, doc_id)` の `text` をそのまま出す（ページに手書きしない）。必ず出す: ①「2023年度以降の数表は未取得」（`moe_mongoose_catch_h12r4` の footnote）②「2000年度はわな日の集計が不十分で CPUE 無し」③「合計の CPUE が PNG 0.616／評価シート 0.513」④「2018年度の CPUE 0.0004 は印字が他年度と桁違い」。
- 根絶宣言: `moe_mongoose_eradication_declaration_2024`（documents＋notes だけ、cells 無し）の notes を出す。「2024年9月3日、奄美大島フイリマングース防除事業検討会が根絶に達したと評価し、環境省が根絶を宣言した」「根拠確率は HBM 99.7%・REA 98.9%」「2026年8月7日に公表ページの図2が再計算結果に差し替えられたが本文の数値は修正されていない」の3つ。出典リンクは `documentsList` の `url`（`https://kyushu.env.go.jp/okinawa/press_00099.html`）。ライセンス PDL1.0 を表示。

### 3-2 章2: 2010年奄美豪雨

- 名瀬の日雨量: `timeseries(db, { variableId: "common:variable:weather.precipitation", scope: { type: "site", siteId: "jma_stations_amami__jma_47909" }, grain: "day", from: "2010-10-10", to: "2010-10-31", sourceIds: ["jma_daily_nase"], region: "jp-46" })`。実測: 日別の合計 2010-10-18＝7.0・19日＝91.5・**20日＝622.0**・21日＝46.0・22日＝13.0 mm（`observation_agg` の day・sum、原本 `jma_daily_nase` の「降水量_合計」と一致）。最大1時間は 20日＝78.5 mm。**検証必須**: 担当3は関数が上の値を返すことを最初に確かめる（`stat` で `max_1h` が引けない場合は 1時間値を出さない。鹿大 p38_t1 の 78.5 を手書きしない）。
- 豪雨期間の帯: 18〜21日（鹿大 表-2 の連続雨量＝18〜21日の和 766.5 mm）を `LineChart` の `bands` で示す。帯の根拠は notes の「連続雨量は気象庁の18〜21日の日降水量の和と一致」。
- 被害は**出典ごとに併記**（1つの表に列で並べる。合算・どれかに寄せることはしない）。`readRecordSet("document_cells", doc_id 絞り)` から読む。実測:

| 項目 | 京大速報（`dpri_amami_gouu_sokuho_2011`） | 鹿大 p17（県 11/26 報告、`kagoshima_univ_amami_gouu_2012`） | 鹿大 p6（文献3、同） |
|---|---|---|---|
| 死者 | 3 | 3（合計） | 3（浸水2＋崖崩れ1） |
| 全半壊の住家 | 485 | 489（全壊 10＋半壊 479） | 565 |
| 床上浸水 | 576 | 119 | 130 |
| 床下浸水 | 736 | 767 | 762 |

  **確定しているのは死者3名だけ**（3出典が一致）。全半壊・浸水は出典で食い違い、どれが正しいかは書かれていない——表の見出しに「確定は死者3名のみ。他は出典ごとに異なり、どれにも寄せていない」と、`notes` の該当 footnote を `docNotes` で出す。鹿大の「日雨量」の2通りの意味（24時間雨量と暦日）も `definition_change` の note をそのまま添える（名瀬の 622 と 648 の取り違え防止）。住用の雨量（703/131）は鹿児島県の観測所の値で気象庁ではない、も note から。
- 流域治水プロジェクト: `documentsList` から `bodik_460001_amami_ryuiki_chisui_2022`（4頁、CC BY 4.0、cells 0）と `kagoshima_amami_ryuiki_chisui_10p_2023`（10頁）の題名・出典・リンク。10頁版の cells（9）の大和ダム（有効貯水容量 721千m3、洪水調節容量 517、洪水調節可能容量 125、水害対策に使える容量 642）と大川ダム（有効貯水量 2,180、洪水調節可能 106）を、`document_cells`（`q=kagoshima_amami_ryuiki_chisui_10p_2023`）から小さな表で出す。ライセンスが「無断転載・改変不可。事実（数値）のみ抽出し出典を明記」なので、数値と出典リンクだけで文章は転載しない。

### 3-3 章3: 島の川と土砂災害

- 件数: `countRecordsBy(db, "hazard_zones", ["municipality_ja","phenomenon_ja","zone_kind_ja"])`。実測は 5市町村 × 現象 3 × 区分 2 の 24 グループで、合計 **6,038 区域**。市町村別の合計: 奄美市 2,504、瀬戸内町 1,816、龍郷町 969、宇検村 511、大和村 238。現象別の合計: 急傾斜地の崩壊 4,118（警戒 2,041・特別警戒 2,077）、土石流 1,855（警戒 1,028・特別警戒 827）、地滑り 65（警戒のみ）。地滑りに特別警戒は無い。
- 出し方: 市町村 × 現象の積み上げ棒（`BarChart`）を警戒・特別警戒で2面（区分ごとに別の面。**区分をまたいで足した総数を棒にしない**）。面積は出さない（`ChartFrame` の注記に「特別警戒は警戒の内側。面積は区分をまたいで足さない」。出典 note が正）。
- 結び: 豪雨の被害（章2）の「二級河川 33 のうち 30 が氾濫」（`dpri_amami_gouu_sokuho_2011` の cells、`二級河川の数（奄美大島）`・`氾濫した二級河川`）を事実として添える。因果は書かない。
- 地図への導線: `/map?region=jp-46&layers=hazard` へのリンク（`Link`、ページ内に1つ。市町村名からの個別リンクは作らない）。

### 3-4 本文の置き場所

- **数値と日付は DB から（cells・notes・documents）**。ページに数字を手書きしない。根絶宣言の日付・確率・「2023年度以降の数表なし」も `notes.text` の表示で出す（言い回しが出典の文面と一致し、出典が更新されたら画面も追従する）。
- ページに書いてよい文は**章の見出しとつなぎの文**だけ（「ここから先は出典ごとの数字を並べる」程度の、事実を主張しないもの）。`web/src/lib/stories/amami.ts` に章の構造（見出し・どの doc_id/row_key を図にするか）を宣言として置き、数値は持たない。registry には置かない（語彙ではなくページ構成）。
- 出典・ライセンスは各章の末尾に `documentsList` の `publisher`/`url`/`license` から出す。鹿大・京大は「ライセンス表記なし。事実（数値）のみ抽出し出典を明記。原本の PDF は再配布しない」の `license` 文字列をそのまま表示する。

## 4. 担当ごとの節（受け入れ基準・速い検証）

### 担当1: データ層・API・registry
- 実装: §1.1 の契約、§2-1・§2-2 の2 route、§3-0、§2-5 の note、`countRecordsBy`・`range`。
- 受け入れ: `records.test.ts` に ① `document_cells` が `superseded=0` で `doc_id` 絞りの行を返す ② `countRecordsBy("hazard_zones", […])` が 24 グループ・合計 6,038（fixture 規模は小さくてよい、本物の件数は手元の読み取り専用で確認して PR に貼る）③ `range` の許可リスト外は例外 ④ A45 の余白の根拠（実測した外接幅の最大）。route のテスト: bbox 無しで 400、`truncated`、`source_id` が奄美3つ以外で 400、`Cache-Control`。`sources[].note` が応答に載る。`describe_catalog` スナップショットの差は hazard の note の1行のみ。
- 速い検証: `cd web && pnpm exec vitest run src/lib/records.test.ts src/app/api/geo src/lib/mcp src/lib/ai`、`pnpm exec tsc --noEmit`。**`b00`・`serving:snapshot`・`build:v2` は回さない**（D1 の表は増えない。cube は変わらない）。`pnpm run build:registry:ts` は r01 を worktree 内に作ってから（メインが回す）。

### 担当2: 地図 UI
- 実装: `MapCanvas` に `onViewChange?: (v: {bbox: [number,number,number,number]; zoom: number}) => void`（moveend、400ms デバウンス）、`overlay-layers.ts`（宣言）、`OverlayLegend.tsx`、`MapPage` のパネル（トグル・現象チップ・凡例・`truncated` 表示）、`layers` の URL 同期、ポップアップ（`selKind` に `hazard`・`protected` を足す）。
- 受け入れ: 既存のレイヤー（流域・地点・メッシュ・河川）の挙動が変わらない。`zoom < 11` で hazard を取りに行かない。同じ bbox（格子丸め後）で再取得しない。特別警戒が警戒の上に描かれる。`region=jp-14` で奄美のレイヤーが出ない。凡例に色＋文字ラベル。`validate_palette.js` の結果を PR に貼る（§2-3）。URL `layers=` の往復。
- 速い検証: `pnpm exec vitest run src/lib/map src/components/map`（純関数＝bbox の格子丸め・URL 同期は単体テスト）、`pnpm exec tsc --noEmit`、`pnpm exec eslint src/components/map src/lib/map`。目視は PR 前にメインが `pnpm run dev` で1回だけ。

### 担当3: 物語ページ
- 実装: §3 の全部。担当1が未完でも `readRecordSet`/`countRecordsBy` の契約（§1.1）に沿ってスタブを呼び、結合は担当1のコミット後。
- 受け入れ: ① 系列の点の数（CPUE 22・総捕獲 23）と豪雨日の 622.0 を返す関数の単体テスト（fixture か `cells.sqlite` を読み取り専用で引く既存の仕組みに合わせる）② 被害の表の死者がどの列も 3 ③ ページの JSX に数字のリテラルが無い（章の構造宣言のテストで確認）④ 3つの必須注記（2023年度以降の数表なし・根絶宣言の確率と日付・「確定は死者3名のみ」）が空でないとき必ず出る（空なら例外を投げて静かに欠けない）⑤ `?region=jp-14` で開いても壊れない ⑥ ナビの導線、`HomeHighlights` は `jp-46` 以外では出ない。
- 速い検証: `pnpm exec vitest run src/lib/stories src/components/stories`、`pnpm exec tsc --noEmit`、`pnpm exec eslint src/app/stories src/components/stories`。

### メインが最後に1回
`b00` は回さない（パイプラインに触れない）。確認: ①担当1・3 の結合（物語の被害表の死者が 3、地図 API を `curl` して件数）② `/map?region=jp-46&layers=hazard,pa_a10` を `pnpm run dev` で目視 ③ スナップショット2つの差分が `document_cells` の語と hazard の note だけ ④ `/code-review`（medium）と `/simplify`（レビュー担当1本）を同時に。

## 5. 未解決

### オーナーに聞く（設計では決められない）
1. **土砂災害の現象（土石流／急傾斜／地滑り）を「色」で塗り分けるか。** 推奨: しない（区分＝STATUS の黄・赤、現象はチップとポップアップ）。色で分けるなら検証済みでない組合せを足すことになる（§2-3）。Issue の文面は「区分と現象で色を分ける」。これは見え方の好みと検証コストの交換で、オーナーの許可が要る。

（それ以外に、データの事実・出典の扱いでオーナーに聞くべきものは無い。被害の「確定は死者3名のみ」・2023年度以降の数表なし・根絶宣言の確率は、Issue と notes で決まっている。）

### メインが決められる（推奨つき）
1. 現象の色分け（上）を保留したまま進める: 推奨は「色なし・チップ」。オーナーが色を望めば担当2の追加だけで済む（API・凡例の形は変わらない）。
2. 1本の PR か2本か: 推奨は1本（§1）。PR の大きさをレビューで嫌うなら §1 の切り方で割る。
3. 章3の題を「島の川と土砂災害」にして「短く急」を使わない: 推奨は使わない（奄美の流路長・勾配の出典が取り込まれていない。§0-3）。足すなら別 Issue（国土数値情報の河川データの奄美分の収集）。
4. `get_records` に `document_cells` を公開する: 推奨は公開（`document_notes` の前例どおり `q=doc_id`。ADR-0014）。公開しない場合は `RECORD_SET_NAMES` から外す分岐が要り、`readRecordSet` だけの内部利用になる。
5. 件数の集計を MCP に出すか（`countRecordsBy`）: 推奨は**この PR では出さない**（lib に置くので後から `get_records` の `group_by` で出せる。スナップショットの動きをこれ以上増やさない）。後続 Issue に積む。
6. 索引を足さない（§2-1）。`rows_read` が問題になったら `ix_hz_centroid` を別 Issue。
7. A15・A45 の細部（A15 は 2009年版、20件中19件が指定期間満了）は、地図でも note をそのまま出す（変えない）。
8. ナビの導線: `SiteNav` に常設（地域に関わらず）。神奈川にいる人にも奄美の物語が見えるが、リンク先の冒頭に「奄美大島の物語」と出すので害は小さい。

## 6. 決定（2026-10-11）
- オーナー: 現象は色で分けない（区分＝STATUS の黄・赤だけ。現象はチップとポップアップ）。
- オーナー: 物語への導線は**奄美を選んだとき（`region=jp-46`）だけ**。SiteNav・HomeHighlights とも、全体・神奈川では出さない（§5 メイン8 の「常設」は採らない）。
- メイン: §5 の 2〜7 は推奨どおり（PR 1本、章3「島の川と土砂災害」、`document_cells` を get_records に公開、`countRecordsBy` は MCP に出さない、索引なし、note はそのまま）。
- 作業場所: 担当1はメインのチェックアウト（registry 再生成に実データが要る）、担当2・3は worktree。
