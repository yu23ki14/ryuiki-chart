# 新しいエリアを足す — Get Started

対象読者: Claude Code エージェント（この手順をそのまま実行する）と、実行結果を判断する人間。
対象作業: 神奈川県以外のエリア（例: 東京都・沖縄県・兵庫県）のデータを収集し、`ryuiki-demo`
のデータモデルに載せてカバレッジを増やす。

## 0. この文書の位置づけ

この文書は「どの方式を採るか」を決める文書ではない。方式は既に決まっている
（`docs/adr/0002-multi-region.md` / `docs/adr/0004-identifiers.md`）。ここではその決定を実務
の手順に落とす。方式そのものを見直したくなったら、まずこの文書ではなく該当 ADR を新しい ADR
で置換すること（`docs/adr/README.md` の作法）。

**先に必ず読むもの**:

- `docs/COLLECTOR_CONTRACT.md` — 収集エージェントの契約。禁止事項・User-Agent・ライセンスの
  扱い。**必読であり、この文書はそれを一切上書きしない。** 矛盾するように見えたら
  COLLECTOR_CONTRACT を優先する。
- `docs/ZONE_DEFINITION.md` — `zone`（Ridge to Reef 1–5）の操作的定義。神奈川の地形前提。
- `docs/add_utility.md` — 水道水源マップに事業体を1つ足す手順。本書と対になる文書で、「1タス
  クの粒度」「調べる→割り付ける→通す→報告する」という進め方の手本にした。
- `docs/UNDATAFIED_TIERS.md` — 神奈川の未データ化ソースの Tier 分け（Tier 1/2/3）。本書の
  Tier A/B/C とは**別の軸**（§5 で注記する）。
- `docs/adr/0002-multi-region.md` / `0004-identifiers.md` — 本書が実務化する決定そのもの。
- `docs/adr/0016-migration-plan.md` と `docs/plans/PHASE_A.md` — v2 設計の移行計画と、レジス
  トリ並走（Phase A）の実装計画。

**現在地**: 実データは神奈川県のみ。v1 のテーブル（`sites` / `measurements` /
`organism_records` 等）に地域を表す列はまだ無く、`source_id` の `_kanagawa` 接尾辞という**慣
習だけ**でエリアが分離されている。v2 設計（ADR-0001〜0020）は region を第一級の次元にする方
向で進行中で、Phase A（語彙レジストリの並走）の A-1（`variable`/`unit`/`place`/`taxon`/
`caveat` のスキーマ追加。`web/src/db/schema-registry.ts` / `data/db/registry.sqlite`）は既に
コミット済み（`phase-a/registry` ブランチ。本書を出す `main` ベースの PR にはまだ乗っていな
い）。`docs/plans/PHASE_A.md` 冒頭の「状態: 計画（未着手）」はこの時点より古い記述であり、実
態は A-1 着手済みと読み替える。ただし A-1 はレジストリ側の作業であり、**v1 のファクトテーブ
ルへの `region_id` 追加とは別物**（本書のスコープ）。つまり今エリアを1つ足すなら **v1 のテー
ブルに `region_id` 列を追加するところから**始まる（§1・§4 Step 2）。Parquet 化・キューブ化・
ID 付け替えは対象外（Phase B/C）。

**「読み取り専用」との関係**: `CLAUDE.md` は `data/db/ryuiki.sqlite` / `cells.sqlite` を「読
み取り専用」と書いているが、これは **`web/`（Next.js アプリ・API）側から見た規約**であり、書
き手は `scripts/m0x_*.py`（および `p0`〜`p3` の PDF 構造化ループ）に限られる。`web/` 側の集
計は `data/db/derived.sqlite` に分けて書く。本書の Step 4 で `m0x_*.py` が `ryuiki.sqlite`
に書き込むことはこの規約に反しない。

---

## 1. 方針

### 単一 D1 + region_id（決定済み・ADR-0002）

**エリアごとに DB もデプロイも分けない。単一の Cloudflare D1 に `region_id` 列を持たせて切り
替える。** ADR-0002 で既に下された決定であり、本書はそれを見直さない。理由の要約:

- 横断比較ができる（神奈川と他エリアの BOD 平均を並べて出す、など）。
- 語彙の統制が効く（指標名・単位・レッドリストのカテゴリを地域ごとに勝手に増やさない）。
- 地域次元は**後から入れるのが最も難しい**種類の変更（全ファクトの再構築と全 ID の付け替えを
  伴う）。最初から入れておく方が結果的に安い。

### `region_id` の形式・粒度・スコープ

ADR-0004 の例に合わせ `jp-<JIS2桁>` とする（例 `jp-14`＝神奈川県、`jp-13`＝東京都）。**粒度
は都道府県固定とする（決定済み）**。ADR-0002 の例に `jp-46-tatsugo`（市町村粒度）が挙がって
いるが、当面はこれを採らず都道府県で切る。東京の島嶼部・沖縄の離島の扱いは、より細かい
`region_id` を切るのではなく zone 定義側の別閾値セットで対応する（§7）。

**ファクト行の `region_id` は出典の管轄県で決まる**（ADR-0004:「地域は**ファクトのパーティシ
ョン列 `region_id`** で表すのであって、レジストリの ID に埋めない」）。ある地点・記録がどの
`region_id` に属すかは、地理的にどこにあるかではなく、**どの都道府県単位の出典から来たか
**（`source_registry` の出典単位）で決まる。

`common` は `sites` / `measurements` / `organism_records` のような**ファクトのスコープには使
わない**。`region_id` を持たせるのはこれらの表であり、そこに `common` という値が入ることは
（今のところ）想定しない。`common` が指すのは環境省の外来種リスト・レッドリスト・YList のよ
うな**全国母集団ソース**であり、現行モデルではそれらは `taxa` / `redlist_assessments`（レジ
ストリ側。Step 2 で `region_id` を持たせないと決めた表）に載っている。ADR-0004 規約0の「県境
をまたぐ実体（相模川・多摩川のような流域）は常に `common`」は、**レジストリ（`variable`/
`taxon`/`unit`、将来の `place`）の ID スコープ**の話であり、v1 のファクト行の `region_id` の
話ではない。混同しない（多摩川・相模川のように複数県にまたがる河川そのものの落とし穴は §7 で
扱う）。

### v1 は region 列が無い。1本目の PR は「列を足すだけ」

現行 v1 には `region_id` がまだ無い。したがって**新エリア作業の1本目の PR は「region 軸をス
キーマに足す（列の追加のみ・既存行を消さない）」**になる（§4 Step 2）。どのテーブルに足すか
は §4 Step 2 で扱う。

### 見直す条件・スコープ外

この決定を見直す条件（D1 の `rows_read` 課金や `/api/schema` のフルスキャンが実際に問題にな
った場合など）とスコープ外（Parquet 化・キューブ化・ID 付け替え）は ADR-0002 の「検討した代
替案」「影響」節、および ADR-0001／ADR-0011／ADR-0004 を参照。**エリアを1つ足すたびに勝手に
方式を変えない。**

---

## 2. 用語と命名規約

| 用語 | 意味 |
|---|---|
| `region_id` | `jp-<JIS2桁>` 形式のエリア識別子。都道府県粒度固定。全国母集団のレジストリ語彙は `common`（ファクトには使わない。§1）。 |
| `region_slug` | `region_id` に対応する英字スラグ（`kanagawa` / `tokyo` / `okinawa` / `hyogo`）。`source_id` の接尾辞・`scripts/regions.py` のキーに使う。 |
| `source_id` | 収集スクリプトが `register()` に渡す出典ID。**現行の命名は `<source>_<region_slug>`**（例 `inaturalist_kanagawa`、`gbif_kanagawa_occurrences`）。全国母集団のソース（`c21_moe_ias_list.py` の外来種リスト、`c23_ylist.py` の学名インデックスなど）は region を付けない。 |

現行の主キーは `site_id` や `record_id` のように、**`source_id` を主キーに焼き込むことで衝突を
避けている**。ただし発行しているのは汎用のコードではなく、ソースごとの直書きである——
`m01_sites.py` は `f"jma_stations_kanagawa__{r['station_id']}"`、`f"dams_kanagawa__{i+1:02d}"`
（キーは連番）のように、`source_id` に相当する固定文字列をソースごとにハードコードしている
（`source_id` という変数を読んで組み立てているわけではない。§4 Step 4）。これは ADR-0004 が問題視する「同じ
場所なのに ID の形が5種類ある」状態そのものであり、他県データを足すと
`vegetation_polygons.feature_id`（環境省 ArcGIS の生 `objectid` をそのまま主キーにしている。
`c80_biodic_ikimonomap.py` の`feature_id: attrs.get("objectid")`）のように**衝突する箇所があ
る**（§9 で詳述）。v1 のままエリアを足す間はこの限界を承知の上で運用する。

**ソースを1つ足すたびにテーブルを増やさない**（ADR-0012 / `docs/adr/README.md` §1(d) の問題
意識）。Tier 1 追加時に `protected_areas` / `vegetation_polygons` / `mammal_mesh` /
`wildlife_sightings` / `river_segments` の5テーブルが増えた前例があるが、これは「既存のモデ
ルに収まらない台帳・区域・メッシュ型のデータ」だけを新設したもの（`scripts/schema_tier1.sql`
冒頭コメント）であり、新エリアのデータは**まず既存表に収まるかを検討する**。収まるものを新エ
リア用にテーブル複製しない。

---

## 3. エリア定数表（新エリアで最初に埋めるもの）

**神奈川の値はコードから実測して埋めてある。東京都・沖縄県・兵庫県の値は、JIS 都道府県コード
（JIS X 0401 の周知の値。13/47/28）以外はすべて `要確認` とし、「調べ方」列に確認手順を書い
た。絶対に推測で埋めないこと**（`docs/COLLECTOR_CONTRACT.md` の禁止事項「数値を推測で埋めな
い」に同じ）。

`要確認` の値は、本収集に入る前に**必ず1件だけ取得して件数で検証**すること（§4 Step 1）。埋
めた値は、この文書の表に加えて **`scripts/regions.py`（まだ存在しない。§4 Step 1 で作る）
**にも反映する（決定事項1・§10）。

| パラメータ | 神奈川の値 | 参照している場所（変数名） | 東京都 | 沖縄県 | 兵庫県 | 調べ方 |
|---|---|---|---|---|---|---|
| `region_id`（提案） | `jp-14` | ADR-0004 の例 | `jp-13` | `jp-47` | `jp-28` | JIS X 0401（都道府県コード）。上書き不可の周知の値。 |
| `region_slug` | `kanagawa` | `source_id` の接尾辞（`inaturalist_kanagawa` 等） | 要確認 | 要確認 | 要確認 | 新設ソースの命名規約として決めるだけ。既存ソースとの衝突が無いか `source_registry` を grep して確認。 |
| JIS都道府県コード | `14` | `c32_nlni_a10.py` `PREFEC_CD`（属性から自動）、`c31_nlni_w05.py`/`c35_nlni_a45.py` の `prefecture_code="14"`（直書き）、`c90_estat_shozaiki.py` の `prefCode=14` | `13` | `47` | `28` | JIS X 0401。周知の値なので確認不要。 |
| bbox（lon_min, lat_min, lon_max, lat_max） | `(138.9, 35.1, 139.8, 35.7)` | `KANAGAWA_BBOX`（`scripts/m01_sites.py`）／`BBOX`（`scripts/m99_validate.py`）／`KANAGAWA_BBOX`（`scripts/c80_biodic_ikimonomap.py`）※実測では3ファイルとも完全に同一の値だった | 要確認（§7: 単一矩形が破綻する） | 要確認（§7） | 要確認（§7: 2海岸線） | 国土地理院か国勢調査の都道府県外接矩形をまず出し、**離島の有無を必ず確認する**（§7）。単一 bbox で足りるかどうかも同時に判断する。 |
| GADM gid（GBIF用） | `JPN.19_1` | `GADM`（`scripts/c02_gbif.py`） | 要確認 | 要確認 | 要確認 | `https://www.gbif.org/occurrence/search` で対象都道府県名を検索し、Administrative Area のファセットからGID形式（`JPN.<n>_1`）を1件確認する。 |
| iNaturalist place_id | `10918` | `PLACE`（`scripts/c03_inaturalist.py`） | 要確認 | 要確認 | 要確認 | `https://api.inaturalist.org/v1/places/autocomplete?q=<都道府県名>` を1回叩き、`results[].id` を確認する（都道府県の行政区分 place を選ぶこと。市区町村の place と取り違えない）。 |
| 気象庁 prec_no | `46` | `PREC`（`scripts/c10_jma.py`） | 要確認 | 要確認（**単一値ではない可能性**。§7） | 要確認 | 気象庁「過去の気象データ・ダウンロード」の地点選択画面で対象都道府県を選び、URL の `prec_no=` を読む。 |
| e-Stat prefCode | `14` | `c90_estat_shozaiki.py` の `prefCode=14`（小地域境界データAPI） | 要確認（§7: 特別区単位） | 要確認 | 要確認 | e-Stat 地図で配信されている境界データWebサービスのAPI仕様書、または対象都道府県を選んだ時のリクエストURLで確認。JIS都道府県コードと一致することが多いが**確認せず流用しない**。 |
| 国土数値情報のファイル名の県コード | `14`（`c31`の`ZIPU`、`c32`/`c33`/`c35`の`ZIPU`、`c30`の`SHP`/`W05_SHP`に埋め込み） | 各 `c3x_nlni_*.py` の `ZIPU` / `SHP` | 要確認 | 要確認 | 要確認 | `https://nlftp.mlit.go.jp/ksj/` の該当データセットのダウンロードページで、対象都道府県のZIPリンクのURLパターンを1件確認する（`W05-08_<コード>_GML.zip` のように末尾がJIS県コードのことが多いが、データセットごとに位置が違うことがある）。 |
| L03-b（土地利用細分メッシュ）の1次メッシュコード | `("5238","5239","5338","5339")` | `MESHES`（`scripts/c34_nlni_l03b.py`） | 要確認 | 要確認 | 要確認 | 対象都道府県の bbox を国土地理院の「標準地域メッシュ」対応表に当て、1次メッシュ（4桁）を機械的に算出するか、`https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-L03-b.html` のメッシュ一覧図で目視確認する。**沖縄は離島が多く1次メッシュが飛び地状に複数必要になりうる**ので特に注意。 |
| CKAN インスタンス | `catalog.opendata.pref.kanagawa.jp`（県）／`opendata.city.sagamihara.kanagawa.jp`（相模原市）（`scripts/c01_ckan.py`） | `scripts/c01_ckan.py` の一覧 | 要確認 | 要確認 | 要確認 | 対象都道府県のオープンデータポータルのトップページを確認し、CKAN製か（`/api/3/action/package_search` が応答するか）を1回叩いて確認する。CKANでない場合は別途調査（DCAT-JP等）が要る。 |
| 県レッドリストの版 | 神奈川県レッドリスト2020（植物編）／レッドデータブック2022（植物編）／レッドリスト2026（昆虫類・クモ類）／レッドデータ生物調査報告書2006（動物編）（`scripts/c20_kanagawa_redlist.py` 他） | `scripts/c20`〜`c28` | 要確認 | 要確認 | 要確認 | 対象都道府県の環境部局サイトで「レッドリスト」「レッドデータブック」を検索し、最新版とその前版の掲載ページ・ファイル形式（HTML表/PDF/xlsx）を確認する。版によって形式が変わることがある。 |
| 海岸線 | `COASTLINE_LONLAT`（約20点の折れ線近似。`scripts/m01_sites.py`） | 同上 | 要確認 | 要確認 | 要確認 | §7 参照。**折れ線近似は廃止し国土数値情報 C23（海岸線）に置き換える方針が決定済み**（決定事項8・§10）。C23 のデータ仕様は要確認。 |
| 主要水系 | 相模川水系・酒匂川水系（`scripts/c52_dams_kanagawa.py` コメント） | `scripts/c5x_*.py`、`scripts/c9x_*.py` | 要確認 | 要確認 | 要確認 | 国土数値情報 W05（河川データ）の水系コード一覧（`data/raw/nlni_codelists/WaterSystemCodeCd.html` 相当）で対象都道府県の主要水系を確認する。 |

**確認できたら1件だけ取得して件数で検証する**。例えば iNaturalist なら`place_id` を渡して観
察記録が1件でも返るか、GBIF なら `gadmGid` を渡して`count` が0でないかを確認してから、
`c0x_*.py` 相当のフル収集に進む。

---

## 4. 手順 Step 0〜9

### Step 0: どこまでやるかを決める

§6 のカバレッジ段階（L0〜L4）から、今回の作業でどこまで到達するかを最初に決め、期待値を人間
と揃える。「L1まで」「Tier A のみ」のように明示してから Step 1 に進む。途中で範囲を広げたく
なったら、Step 9 で PR を分けるか判断する。

- **触るファイル**: 無し（合意のみ）。
- **完了条件**: 目標段階が1つに決まっている。
- **落とし穴**: 「とりあえず集められるだけ集める」で始めると、Tier C（§5）に時間を溶かしてL1
  にすら届かないことがある。段階を決めてから着手する。

### Step 1: エリア定数を調べ、`scripts/regions.py` を作り、1件取得で検証する

§3 の「調べ方」列に従って `要確認` を埋める。**推測しない。1つの値も裏取りせずに埋めてはいけ
ない。** 埋めた値は §3 の表と、**`scripts/regions.py`**（まだ存在しない。`region_slug` をキ
ーにした辞書で bbox・GADM gid・iNaturalist place_id・JMA prec_no・e-Stat prefCode・NLNI 県コ
ード・L03-b メッシュ・CKAN インスタンス等をまとめる。既定は`kanagawa` として既存挙動を変えな
い。決定事項1・§10 参照）の両方に反映する。埋めたら、収集スクリプトを書く前に API を1回だけ
叩いて1件以上のレコードが返ることを確認する（例: iNaturalist なら
`https://api.inaturalist.org/v1/observations?place_id=<調べたID>&per_page=1`）。

- **触るファイル**: この文書（`docs/add_area.md`）の §3 表、`scripts/regions.py`（新規）。
- **完了条件**: 表の `要確認` がすべて具体値に置き換わり、`scripts/regions.py` に新エリアの
  キーが追加されている。値ごとの1件取得の確認ログ（URL・返ってきた件数）を
  **`reports/add_area_<region_slug>.md` に残す**（`docs/add_utility.md` の
  `reports/<utility>.md`と同型。**これが Step 1 の完了条件そのもの**）。
- **落とし穴**: GADM の GID・iNaturalist の place_id・e-Stat の prefCode はJIS コードと**似
  ているが同じ体系ではない**（例: GADM の `JPN.19_1` の `19` はJIS の `14` ではない）。JIS
  コードから機械的に導出しない。

### Step 2: region 軸を4点セットで足す（初回のみ）

**`web/src/db/schema.ts` の Drizzle 定義は D1（配信側）の定義であり、`m0x_*.py` が書く
`data/db/ryuiki.sqlite` の DDL は別（`scripts/schema_app.sql` / `schema_tier1.sql` /
`schema_water.sql` 側）。** `schema.ts` に列を足しただけでは原本には列が増えず、
`seed-d1-local.mjs` は原本に無い列を NULL のまま通す（ログに警告を出すだけで止まらない）。そ
のままだと D1 の `region_id` が全行 NULL になり、Step 5〜7 の `WHERE region_id=...` が**黙っ
て0件になる**。次の順序で4点セットとして進める:

1. **`scripts/schema_app.sql` / `scripts/schema_tier1.sql` に `region_id TEXT` を追記する
   **（新規構築時の正。対象は少なくとも `sites` / `measurements` / `sensor_timeseries` /
   `organism_records` / `protected_areas` / `vegetation_polygons` / `mammal_mesh` /
   `wildlife_sightings`）。
2. **既存の `data/db/ryuiki.sqlite` に `ALTER TABLE <table> ADD COLUMN region_id TEXT` を打
   つ**（対象は上記と同じテーブル一覧。前例: `docs/REBUILD.md`「やらないこと」節の「既存実デ
   ータ行を DELETE しない（ALTER TABLE ADD COLUMN と UPDATE のみ）」）。
3. **既存の神奈川行に `UPDATE <table> SET region_id='jp-14' WHERE region_id IS NULL` でバッ
   クフィルする。** これをやらないと横断比較も §9 の `biotaTotals()` 修正も成立しない（既存
   行が NULL のままだと `WHERE region_id='jp-14'` も0件になる）。
4. **`web/src/db/schema.ts` に同じ列を足して `cd web && pnpm run db:generate`。
   **`web/drizzle/migrations/` に新規マイグレーションが生成される。**マイグレーション SQL を
   手で書き換えない。**

`river_segments` は既に `prefecture_ja` を持つが、これは「1レコードがまたがる県」を表す自由
記述列であり `region_id` の代わりにはならない。**両方を残す**（削除しない）。

`taxa` / `redlist_assessments` は分類群レジストリなので `region_id` を持たせず、この Step の
対象外のまま据え置く。神奈川県レッドリストの評価行が `taxa.redlist_kanagawa` という**県名入
りの列名**に入っている問題（§9）はこの Step では直さない。他県のレッドリスト評価を置く場所が
無いことは既知の制約として Step 9 の表に送る。

- **触るファイル**: `scripts/schema_app.sql`、`scripts/schema_tier1.sql`、
  `web/src/db/schema.ts`、（生成される）`web/drizzle/migrations/`。
- **完了条件**: 上記1〜4がすべて終わり、`ALTER` 後の原本で該当テーブルの既存行の`region_id`
  がすべて `jp-14` になっている
  （`sqlite3 data/db/ryuiki.sqlite "select region_id,count(*) from sites group by 1"` が
  `jp-14` 1行に揃うこと）。`pnpm run db:generate` が新規マイグレーションを作り、既存テーブル
  の既存列定義に差分が出ていないこと（`git diff` で追加行だけになっていること）。
- **落とし穴**: 列追加であっても Drizzle の生成物は既存マイグレーションの**後ろに追記**され
  る形になるはず。既存マイグレーションファイルを編集した形跡が出たら生成をやり直す。
  **「`db:setup` が通る」は検出力が無い完了条件なので使わない**（原本の列が NULL のまま入っ
  ても seed 自体は通ってしまうため）。

### Step 2.5: `m01`〜`m05` の INSERT に `region_id` を渡す

現状 `scripts/` に `region_id` という文字列は1つも無い（`grep -rn region_id scripts/` で確認
できる）。Step 2 で列を足しただけでは値が入らないので、`m01_sites.py` /`m02_measurements.py`
/ `m03_organisms.py` / `m05_tier1.py` の各 INSERT 文に `region_id` 列と値を追加する改修が要
る（Step 4 で行うコード変更と一体。§4 Step 4 参照）。

- **触るファイル**: `scripts/m01_sites.py` / `m02_measurements.py` / `m03_organisms.py` /
  `m05_tier1.py`（各 INSERT 文）。
- **完了条件**: **`ALTER` 後の原本で `SELECT region_id, count(*) FROM sites GROUP BY 1` が期
  待どおりに割れること**（神奈川行が `jp-14`、新エリア行が新しい `region_id`）。「`db:setup`
  が通る」は検出力が無いので完了条件から外す。
- **落とし穴**: Step 2 のバックフィル（3.）を先にやっておかないと、新エリア投入後の
  `GROUP BY 1` で神奈川行が NULL のまま混ざり、検証にならない。

### Step 3: Tier A ソースを収集する

§5 の Tier A 表に従い、定数の差し替えだけで動くスクリプトから着手する。実行順は依存関係があ
る収集（§5「順序依存」参照。国土数値情報の流域界 W12 が先、地物取得や m01 が後）を除けば概ね
自由だが、まず**軽くて確認しやすいもの**（GBIF・iNaturalist・気象庁）から通し、1件検証（Step
1）で得た手応えを保つ。

```bash
. .venv/bin/activate
python scripts/c02_gbif.py       # --region <region_slug> で選ぶ（既定 kanagawa。決定済み）
python scripts/c03_inaturalist.py
python scripts/c10_jma.py
```

**新エリア対応は複製ではなく引数化に統一する（決定事項1・§10）。**各スクリプトは
`scripts/regions.py`（Step 1 で作る）から `--region <slug>` でエリア定数を選ぶ。**既存スクリ
プトの複製は禁止**——複製すると bbox の3重定義（§9）を再生産し、§5 C の「固定名の出力を上書き
する事故」を招く。既定は `kanagawa` とし既存挙動を変えない。

- **触るファイル**: `scripts/c0x_*.py` 各ファイル（`--region` 引数の追加。コード変更を伴う。
  Tier A の実行自体は Claude Code エージェントの担当範囲）、`scripts/regions.py`。
- **完了条件**: 各ソースが `source_registry` に `register()` 済みで、
  `data/processed/<source_id>.{csv,jsonl}` が存在する。無接尾辞 SID（§5 C）は**新エリア分だ
  け `<source>_<region_slug>` を付け、既存の出力を上書きしない**。
- **落とし穴**: `docs/COLLECTOR_CONTRACT.md` の「外向きアクションの禁止」に触れる収集（フォ
  ーム送信・ログイン必須のもの）が Tier A に混ざっていないか確認する。モニタリングサイト1000
  の加工2本（`process_moni1000_satochi.py` /`process_moni1000_forest_coast.py`）は Tier A か
  ら外し「対象外」節に置いた（§5・§8）。

### Step 4: `m01`〜`m06` でアプリDBへ入れる（コード変更を伴う）

```bash
. .venv/bin/activate
python scripts/m01_sites.py
python scripts/m02_measurements.py
python scripts/m03_organisms.py
python scripts/m04_protocols.py
python scripts/m05_tier1.py
python scripts/m06_water.py --dry-run   # 水道系を足す場合のみ。Tier C（§5）
```

**`m01`〜`m05` は汎用ローダーではない。** `m01_sites.py` は `jma_stations_kanagawa` /
`env_kousui_stations_kanagawa` / `dams_kanagawa` / `sagami_livecams` /
`moni1000_sites_kanagawa` のように**入力 jsonl 名と source_id を文字列で直書き**している。
`m02_measurements.py` は `SENSOR_SOURCES` のリストと `env_kousui_sample_kanagawa` /
`env_kousui_annual_kanagawa` が固定、`m03_organisms.py` は `inaturalist_kanagawa` /
`gbif_kanagawa_occurrences` が固定、`m05_tier1.py` は `read_csv("green_areas_all")` 等のCSV
ファイル名が `jobs` リストに固定で書かれている。**新エリアの jsonl/csv を`data/processed/`
に置いても何も読まれず、エラーも出ずに正常終了する。**

Step 4 は「`m01`〜`m05` に新エリアの入力を読む改修（＋ Step 2.5 の `region_id` 付与）を伴う」
と明記する。新エリアの `region_slug` 付き `source_id`（例 `jma_stations_tokyo`）を読む分岐を
各スクリプトに足す。新エリアの `zone_of()`・bbox 判定・`COASTLINE_LONLAT` はすべて神奈川前提
なので（§7）、Step 4 の時点では `zone` を NULL のままにしてよい（`elevation_m IS NULL` のと
きと同じ扱い）。

- **触るファイル**: `scripts/m01_sites.py` / `m02_measurements.py` / `m03_organisms.py` /
  `m05_tier1.py`（新エリア入力を読む改修）、`data/db/ryuiki.sqlite`（結果として書かれる。こ
  れは生成物であり Git 管理外）。`data/db/cells.sqlite` は `p0〜p3` の PDF 構造化ループの対
  象であり、Tier A の範囲では触らない。
- **完了条件**: 「エラー無く終了」ではなく、**新エリアの `source_id` の行数が期待値どおり入
  っている**こと（例: `select count(*) from sites where source_id='jma_stations_tokyo'`が取
  得件数と一致する）。
- **落とし穴**: `data/db/ryuiki.sqlite` と `data/db/cells.sqlite` は §0 で調停した通り
  `m0x_*.py` の書き込み先だが、既存の神奈川データ行を消してよいという意味ではない。
  `m05_tier1.py` の `wipe()` は `DELETE ... WHERE source_id IN (...)` で**対象 source_id限定
  **に絞っている。新エリアの投入で神奈川の `source_id` を巻き込んで消さないこと。§2 の
  「`site_id` は `f"{source_id}__{キー}"` 形式」という一般化した書き方は、実物（各ソースごと
  の直書き。キーも station_id とは限らない——`dams_kanagawa` は連番）に合わせて読むこと。

### Step 5: `m99_validate.py` で検証しカバレッジを確認する

```bash
. .venv/bin/activate
python scripts/m99_validate.py --region <region_slug>   # --region はこれから追加する（下記）
```

`m99_validate.py` は `BBOX`（神奈川固定）でレコードの bbox 外れを数える。
**`docs/DATA_INVENTORY.md`はエリア別セクションを `m99_validate.py` の `--region` 対応で自動
生成する。手書きしない**（決定事項6・§10）。`--region` 引数と `scripts/regions.py` からの
bbox読み出しはまだ実装されていないので、Step 5 の一部として `m99_validate.py` に足す。対応前
の版を暫定で使う場合、新エリアを足した直後は「bbox外」が跳ね上がるのが正常（神奈川の bbox に
他県のデータが入っている状態なので）。

- **触るファイル**: `scripts/m99_validate.py`（`--region` 引数の追加）、
  `docs/DATA_INVENTORY.md`（生成物）。
- **完了条件**: 新エリアの `source_id` を持つ行数がレポートに現れ、想定した範囲（Step 0 で決
  めた段階）の行数になっている。
- **落とし穴**: `docs/DATA_INVENTORY.md` はコミットされるドキュメントであり、神奈川分の既存
  記述を新エリア分の数字で上書きしない。`--region` 対応がエリアごとに節を分ける前提で作る。

### Step 6: geo アセットと地図初期表示

`web/scripts/copy-geo-assets.mjs` の `FILES` は `nlni_w05_rivers.geojson` /
`nlni_w12_watersheds.geojson` / `water_zones.geojson` の3本に固定されている。これらは**無接
尾辞 SID**（§5 C）の出力そのものなので、新エリア分を県コードだけ差し替えて同名で回すと**既存
の神奈川分を上書きしてしまう**（§5 C・§9）。新エリアの河川・流域界を地図に出すには、新エリア
分の出力を `<source>_<region_slug>.geojson` のような別名で作り、`FILES` 配列にエントリを足す
か、既存の生成スクリプトの出力側で神奈川分と新エリア分をマージする必要がある。地図の初期中心
`DEFAULT_CENTER` / `DEFAULT_ZOOM`（`web/src/lib/map/basemaps.ts`。`KANAGAWA_BOUNDS` は定義だ
けで未使用）は神奈川中心の固定値であり、複数エリアを1画面に出すのか、エリア切り替えUIを作る
のかは本 Step では決めず Step 9 の未解決点に送る（UIの実装判断であり、本書のスコープはデータ
投入まで）。

- **触るファイル**: `web/public/geo/`（`prepare:geo` の生成物。Git管理外）。ソースは
  `data/processed/` の対応する geojson。
- **完了条件**: `pnpm run prepare:geo` 実行後、新エリアの河川・流域界ポリゴンが
  `web/public/geo/rivers.geojson` / `watersheds.geojson` に含まれている（`jq` 等で feature
  数が増えていることを確認）。**神奈川分の feature 数が減っていないことも確認する。**
- **落とし穴**: Workers に `fs` は無いので、地図表示用ファイルは必ず ASSETS バインディング経
  由（`web/src/lib/geo.ts`）かブラウザの直接フェッチ（`/geo/rivers.geojson`）で読む。
  `fs.readFileSync` 等を新規に足さない。

### Step 7: `build:derived` → `build:registry` → `db:setup`/シード → ローカルで画面を見る

```bash
cd web
pnpm run build:derived   # build-derived.mjs / build-geo.mjs / build-biota.mjs / build-water-geo.mjs の4本
pnpm run build:registry  # r01_build_registry.py -> data/db/registry.sqlite（Phase A A-1 で追加。無いと db:seed が止まる）
pnpm run db:setup        # db:migrate && db:seed
pnpm run dev
```

`web/scripts/seed-d1-local.mjs` は `ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite` /
**`registry.sqlite`** の**4ファイル**固定で読み、テーブル単位に**DELETE → 全INSERT**する
（`registry.sqlite` は Phase A A-1（`phase-a/registry` ブランチ）で加わったもので、4本とも
`required: true` ——1本でも無いと `db:seed` が止まる）。**エリア単位の差分投入はできない。
**新エリアを足したら、神奈川分を含む全データを毎回作り直してシードし直すことになる。

- **触るファイル**: `data/db/derived.sqlite`（生成物）、`data/db/registry.sqlite`（生成物）、
  ローカル D1（`.wrangler/` 配下）。
- **完了条件**: `/`・`/map`・`/biota`・`/water` 等の画面が起動し、新エリアのデータが地図・一
  覧・チャートのいずれかに現れる（Step 0 の目標段階に応じて確認箇所を選ぶ）。
- **落とし穴**: `web/src/lib/queries.ts` の `biotaTotals()` と `web/scripts/build-biota.mjs`
  は**どちらも** `source_id='gbif_kanagawa_occurrences'` と
  `source_id='inaturalist_kanagawa'`を**直書き**で絞っている。新エリアの生物データを入れても、
  **両方**直さない限り**黙って0件扱いになり集計が過小表示になる**。Step 7 で画面を見た時に生
  物系の合計が増えていなければ、まずここを疑う。**この2箇所の修正は本書のスコープ内（Step 7
  で直す。決定済み）**——`DEFAULT_CENTER` と UI 文言のエリア対応は別 PR に切り出す（§6）。

### Step 8: Tier B/C の県固有ソースに着手する

Step 0 で L2 以上を目標にした場合、§5 の Tier B（対象エリアの資料探しが要るもの）・Tier C
（実質別プロジェクト）に進む。Tier C の水道水源マップは`docs/add_utility.md` の手順をそのま
ま使う（本書は繰り返さない）。

- **触るファイル**: Tier に応じて `scripts/` 配下の新規スクリプト、`reports/<source>.md`。
- **完了条件**: Step 0 で決めた目標段階（§6）に到達している。
- **落とし穴**: Tier B は「同型だが対象を探すところから要る」ため、探索に時間がかかる。1ソー
  スずつ `source_registry` に登録し、見つからなかったものは`record_count=0` + `notes` で理由
  を残す（COLLECTOR_CONTRACT 通り）。

### Step 9: 記録して PR を出す

- `source_registry` へ全ソースを登録済みか確認する（`register()` 呼び出しの有無）。
- `docs/DATA_INVENTORY.md` を再生成する（`m99_validate.py --region`。§4 Step 5）。
- `docs/LICENSE_MATRIX.md` に新エリアのソースのライセンスを追記する（既存の神奈川分の記述は
  書き換えず、追記する）。
- この文書（`docs/add_area.md`）の §3 定数表を、`要確認` から実値に更新した状態のまま残す
  （次のエリアの人がそのまま読める状態にする）。`scripts/regions.py` も同様に残す。
- 方針は既に確定しているので、曖昧さが残っていない限り都度質問せず PR まで進める。曖昧さが残
  る場合（例: 地図のエリア切り替えUIの仕様）は、その論点だけ先に確認する。

---

## 5. ソースの棚卸し（Tier A / B / C）

**注意**: ここでの Tier A/B/C は `docs/UNDATAFIED_TIERS.md` の「Tier 1/2/3」とは**別の軸**で
ある。UNDATAFIED_TIERS は「神奈川において未取得のソースの取得難易度」、本書の Tier A/B/C は
「そのソースを**別の都道府県に差し替えて再実行する**ときの難易度」を表す。両者を混同しないこ
と。

### Tier A: 定数の差し替えだけで通る

| スクリプト | 差し替える変数名 | SID／出力ファイル名の改名が必要か |
|---|---|---|
| `scripts/c02_gbif.py` | `GADM` | 不要（`source_id` は元々 `_kanagawa` 付き。新エリアは `_<region_slug>` に変えるだけ） |
| `scripts/c03_inaturalist.py` | `PLACE` | 不要（同上） |
| `scripts/c10_jma.py` | `PREC` | 不要（`SID_ST`/`SID_MON`/`SID_DAY` は元々 `_kanagawa`/`_yokohama` 付き。新エリアは接尾辞ごと差し替える） |
| `scripts/c30_nlni_w12.py` | `SHP`・`ZIPU`・`W05_SHP`（県コード／シェープファイル名の直書き） | **必要**（`SID="nlni_w12_watersheds"` は無接尾辞。§5 C） |
| `scripts/c31_nlni_w05.py` | `ZIPU` 中の県コード。`prefecture_code="14"` と `prefecture_name_ja="神奈川県"` も直書き | **必要**（`SID="nlni_w05_rivers"` は無接尾辞） |
| `scripts/c32_nlni_a10.py` | `ZIPU` 中の県コード（`prefecture_code` は `PREFEC_CD` 属性から自動だが `prefecture_name_ja="神奈川県"` は直書き） | **必要**（`SID="nlni_a10_natparks"` は無接尾辞） |
| `scripts/c33_nlni_a15.py` | `ZIPU` 中の県コード（`prefecture_code` は `PRC` 属性から自動だが `prefecture_name_ja="神奈川県"` は直書き） | **必要**（`SID="nlni_a15_wildlife"` は無接尾辞） |
| `scripts/c34_nlni_l03b.py` | `MESHES`（県コードではなく1次メッシュコードの配列） | **必要**（`SID=f"nlni_l03b_landuse_{year}"` は年区切りのみで県区別が無い） |
| `scripts/c35_nlni_a45.py` | `ZIPU` 中の県コードと `prefecture_code`/`prefecture_name_ja`（両方直書き） | **必要**（`SID="nlni_a45_forest"` は無接尾辞） |
| `scripts/c62_gsi_elevation.py` | `lon0, lon1, lat0, lat1`（bbox の直書き） | **必要**（`SOURCE_ID="gsi_elevation_grid"` は無接尾辞。順序依存あり——下記） |
| `scripts/c90_estat_shozaiki.py` | クエリ文字列中の `prefCode=14` | 不要（`SID="estat_shozaiki_kanagawa"` は元々 `_kanagawa` 付き） |
| `scripts/collect_moni1000_sites.py` | `PREF_MAP` から対象都道府県の完全一致文字列を選ぶだけ（全都道府県を1回で収集済み） | 不要（`source_id="moni1000_sites"` は全国共通の1ソースとして意図的に無接尾辞。抽出後の `moni1000_sites_<region_slug>.csv/.jsonl` を新設するだけでよい） |

**順序依存**: `c31`（河川。原データが `c30` の水系名推定に使われる）→ `c30`（W12 流域界を生
成。`SHP` に加え水系名推定用の `W05_SHP` も対象都道府県のものにする）→ `c32`/`c33`/`c34`/
`c35`（`assign_watershed()` で `watershed_id` を付与。`c34` は W12 の生シェープを直接読む）→
`c62`（W12 の和集合ポリゴンでクリップ。対象エリアの W12 が無いと動かない）→ `m01`/`m05`
（`watershed_id` 付与・zone 判定）。

### Tier B: 同型だが対象エリアの資料を探すところから要る

| 分類 | スクリプト（神奈川側の実装） | 何を探せばよいか |
|---|---|---|
| 県レッドリスト | `c20_kanagawa_redlist.py` / `c26_kanagawa_redlist_animals_2006.py` / `c27_kanagawa_redlist_plants_2022.py` / `c28_redlist_assessments.py` | 対象都道府県の環境部局サイトでレッドリスト・レッドデータブックの最新版と旧版を探す。掲載形式（HTML表/PDF/xlsx）を先に確認する。 |
| 県オープンデータ（環境系） | `c02_ckan_env.py` 一式 | CKAN か否かをまず確認（§3）。CKANでなければ個別ページのURL列挙から作り直す。 |
| 県ArcGIS・自然環境系 | `c80_biodic_ikimonomap.py` ほか（`docs/UNDATAFIED_TIERS.md` 参照） | 対象都道府県・市の統計ダッシュボード、鳥獣出没情報、緑地台帳等を個別に探す。**bbox 差し替えで動く見込みがあるのは `c80`（環境省 いきもの地図の全国共通REST API）のみ**、他は個別収集。 |
| ダム諸元 | `c52_dams_kanagawa.py` | 座標をWikipediaのgeohackから手収集した前例に倣い、対象エリアの主要ダムを個別に調べる。 |
| 県公式PDF | `c70_ckan_pdf_docs.py` | 県サイト内のPDF一覧ページのURLを個別に列挙し直す。 |
| 特定館のサイト | `c66_kanagawa_museum_biblio.py` / `c67_sagamihara_digital_archive.py` | 対象エリアの自然史博物館・デジタルアーカイブの有無を確認し、あれば書誌データの取得可否を個別に判断する。 |
| 名水・里山 | `collect_meisui_kanagawa.py` / `collect_moe_satoyama.py` | どちらも環境省の全国データを都道府県で絞る構造（`collect_moe_satoyama.py` は URL に `14_kanagawa` を直書き）。対象都道府県のページURL・該当箇所を個別に確認する。 |

### Tier C: 事実上の別プロジェクト

| 対象 | 実体 |
|---|---|
| 水道水源マップ一式 | `scripts/c90〜c93`・`scripts/m06_water.py`・`scripts/schema_water.sql`・`docs/add_utility.md`。1事業体=1タスクの粒度で `docs/add_utility.md` の手順をそのまま使う。 |
| PDF構造化ループ | `scripts/p0_merge_vocab.py`〜`p3_fixer_tanzawa.py`。対象エリアの調査プロトコル文書がPDFで存在する場合のみ着手する（`c66`/`c67` で見つかった文書が対象になりうる）。 |
| 相模川水系固有のサイト群 | `scripts/c50_kasen_kokusei.py`〜`c57_ayu_upstream_migration.py`。ライブカメラ・アユ遡上調査等、相模川水系という**個別の川**に紐づく収集であり、対象エリアの主要水系（§3）が変われば実質書き直しになる。 |

### 対象外（人間の承認待ち）

`process_moni1000_satochi.py` / `process_moni1000_forest_coast.py` は **Tier A から外す**。
入力zipは `moni1000_download_helper.py` がフォームを無断送信して得たもの
（`docs/COLLECTOR_CONTRACT.md` の【2026-08-29追記】にある違反そのもの。取得済み10ソースは
`redistributable=0` で隔離済みで、権限者の追認を待っている）。`collect_moni1000_sites.py`
（公開HTMLのサイト一覧を収集するだけ）は違反に関与しないので Tier A のままでよい。新エリアで
この2本相当の加工をしたい場合は、**先に人間の承認を取る**（§8）。

### 地域非依存でそのまま使えるもの（差し替え不要）

`scripts/common.py` / `scripts/nlni_lib.py` / `scripts/water_lib.py` /
`scripts/c21_moe_ias_list.py`（環境省 外来種リスト・全国版）/`scripts/c22_moe_redlist.py`
（環境省 レッドリスト・全国版）/`scripts/c23_ylist.py`（YList 学名インデックス・全国版）。
`scripts/p1_maker.py` / `scripts/p2_checker.py` はPDF構造化のロジック自体は地域非依存（対象
PDFが変わるだけ）。

---

## 6. カバレッジの段階（達成基準）

| 段階 | 判定できる確認手順 | 画面に出るもの |
|---|---|---|
| **L0** | `SELECT count(*) FROM sites WHERE region_id='jp-XX'` が0でない。地図の `web/public/geo/watersheds.geojson` / `rivers.geojson` に対象エリアの feature が含まれる。 | 地図に流域界と河川が出る。 |
| **L1** | `SELECT count(*) FROM organism_records WHERE region_id='jp-XX'`（列追加後）または該当 `source_id` で件数確認。 | 生物出現（`/biota`）にエリアの記録が乗る。**ただし `biotaTotals()`/`build-biota.mjs` の直書き（§9）を直さない限り、合計カードには反映されない。** |
| **L2** | `measurements` / `sensor_timeseries` に該当 `region_id`（または `source_id`）の行があり、`m99_validate.py` の期間集計に現れる。 | 水質・気象の時系列（`/quality` 等）にエリアの系列が出る。 |
| **L3** | `protected_areas` / `vegetation_polygons` / `mammal_mesh` / `wildlife_sightings` / `river_segments` のいずれかに該当エリアの行がある。`/api/nature?kind=...` が空でない応答を返す。 | Tier1相当の自然系データ（保護区・植生・メッシュ分布・出没記録）が地図・一覧に出る。 |
| **L4** | `water_zone` 等の水道系テーブルに該当エリアの行があり、`docs/add_utility.md` の検証（`m06_water.py --dry-run`）が通る。行政文書（`documents` / `cells`）にも該当エリアの文書がある。 | 神奈川と同等（行政文書の参照、水道水源マップ）。 |

**どの段階なら公開してよいか**: 少なくとも **L2 まで到達し、§9 の
「biotaTotals()/build-biota.mjs の直書き」「table-meta.ts の県名直書き（AIプロンプトへの混入）」
「地図の DEFAULT_CENTER」の3点を対応してから**、デモとして公開してよい（後2者は別 PR。決定
事項7・§10）。L0/L1 だけの状態を外
部に見せると、既存の合計カード・AIアシスタントの説明文が神奈川のみを前提にした文言のまま新エ
リアのデータと混在し、閲覧者に誤った理解を与える。

---

## 7. エリア別の地形・制度の落とし穴

- **東京都**: 伊豆諸島・小笠原諸島が含まれるため、単一の矩形bboxは実質破綻する。ただし
  `c62_gsi_elevation.py` は**bbox内の全格子点を舐めるのではない**——生成後に
  `nlni_w12_watersheds.geojson`（流域界ポリゴン）の和集合でクリップして「陸域のみ」（神奈川
  では約3000点。docstring参照）に絞ってから標高APIを叩く実装になっている。実際に効くのは、
  (1) `m01_sites.py` の `in_bbox()` と `m99_validate.py` の `BBOX`——伊豆・小笠原を含む単一矩
  形では「範囲内/外」の判定が意味を失う（本土と島嶼の間の広大な海域が bbox 内に入るため）、
  (2) `COASTLINE_LONLAT`（手描き折れ線）——本土の海岸線しか無いので島嶼部の地点は最寄り海岸を
  誤る（C23 への置き換えで解消する方針。下記）、の2点。`c62` は対象エリアの W12（`c30` のク
  リップ元）が先に無いと動かない（§5「順序依存」）。**多摩川は東京都・神奈川県だけでなく山梨
  県にも源流を持つ**（本書で以前「東京都と神奈川県にまたがる」としていたのは不正確だったので
  訂正する。region_id は出典単位で決まるため——§1——この3県にまたがること自体は region_id 割り
  当てには影響しない）。
- **沖縄県**: 離島群のためbboxが広大かつ大半が海域になる。`docs/ZONE_DEFINITION.md`の標高し
  きい値（800m/400m/100m）は本州の急峻な地形を前提にしており、沖縄の低い山地にはそのまま当て
  はまらない（最高峰でも800mに届かない）。zone のしきい値自体をエリアごとに定義し直す必要が
  ある。
- `要確認`: **気象庁 `prec_no` は沖縄県内で複数に分かれる**（本島・大東島・宮古島・石垣島）。
  §3 の表は「1県1値」を前提にした形なので、`scripts/regions.py` の定数は**値でなくリストを許
  す形**にする必要がある。
- `要確認`: 沖縄・東京島嶼では「海岸線から2km以内」がほぼ全域になり、
  `docs/ZONE_DEFINITION.md` の zone 4（平野・沖積低地）が事実上消滅する。しきい値だけでなく
  分類の意味が変わる。
- **兵庫県**: 日本海側（但馬）と瀬戸内海側（播磨・淡路含む）の**2つの海岸線**を持つ。
  `COASTLINE_LONLAT` のような単一の折れ線近似は成り立たない。
- **内陸県一般**（今回の3県には無いが今後の参考として）: zone 5（河口・沿岸）に相当する地点
  が存在せず、海岸距離の計算自体が不要になる。
- `要確認`: 東京都は e-Stat の市区町村名が特別区単位になる（`docs/add_utility.md` の政令市の
  注記と同型の問題）。
- `要確認`: W12（昭和52年版）の島嶼部の収録範囲。

**海岸線は `COASTLINE_LONLAT`（手描き折れ線）を捨て、国土数値情報 C23（海岸線）を新ソースと
して1回取り、全エリア共通で最近傍距離を取る方針にする（決定済み）。** 兵庫の2海岸線も、県境
付近（川崎の地点に東京湾岸の東京都側が最近傍になる等）も自然に解ける。`要確認`: C23 のデータ
仕様・ファイル名・都道府県単位かどうか。

zone のしきい値・海岸線の定義はエリアごとに持つべきというのは、ADR-0002 が既に指示している方
向性（「`zone` のような操作的分類は `place_kind='zone'` の place として地域ごとに定義し、定
義そのもの（閾値・出典・作成日）を place のメタデータに持たせる」）そのものである。本書の v1
の枠組みでは place レジストリがまだ無いので、当面は`docs/ZONE_DEFINITION.md` に相当するエリ
ア別ドキュメント（例 `docs/ZONE_DEFINITION_tokyo.md`）を都度作り、`scripts/m01_sites.py` の
`zone_of()` 相当をエリア別に分岐させずに済む形（設定値の外出し）で実装することを推奨する。

---

## 8. やってはいけないこと

`docs/COLLECTOR_CONTRACT.md` の禁止事項の要約（**原文が優先。必ずリンク先を読むこと**）:

- 数値を推測で埋めない。読めなければ null にして理由を残す。
- 外部サイトのフォーム送信・利用規約への同意操作・組織名や氏名を名乗る行為・アカウント登録や
  APIキー取得・ログインを要する取得は**人間の承認なしに行わない**。
- User-Agent（`scripts/common.py` の `UA`）に個人名・個人アドレスを入れない。
- 再配布不可・要申請のデータは**ダウンロードせず**
  `register(redistributable=0, record_count=0, notes=...)` だけ残す。

このリポジトリ固有の禁止事項:

- `data/db/ryuiki.sqlite` と `data/db/cells.sqlite` の書き手は `scripts/m0x_*.py` /PDF構造化
  ループに限る（`web/` 側から見た「読み取り専用」との関係は §0 参照）。**既存の実データ行を
  DELETE しない**（`m05_tier1.py` の `wipe()` のように対象 `source_id`を限定した削除のみ許容
  する）。
- **`data/processed/` の既存ファイルを上書きしない。** 無接尾辞 SID（§5 C）を新エリアで再利
  用するときは必ず `<source>_<region_slug>` を付ける。
- `web/drizzle/migrations/` の SQL を直接書き換えない。スキーマ変更は必ず
  `web/src/db/schema.ts` を編集して `pnpm run db:generate` で再生成する。
- `moni1000_download_helper.py` を**再実行・複製しない**（§5「対象外」参照。既に発生した違反
  の再演になる）。
- そのほかのリポジトリ規約（`pnpm run deploy` / `queryChunked` / Workers に `fs` が無いこと
  等）は `CLAUDE.md` を参照。

---

## 9. 既知の未解決点（エリアを増やす前に効いてくる順）

| 論点 | 何が起きるか | どこで直すか |
|---|---|---|
| `web/src/lib/queries.ts` の `biotaTotals()` と `web/scripts/build-biota.mjs` がともに `source_id='gbif_kanagawa_occurrences'` / `'inaturalist_kanagawa'` を直書き | 他県の生物データを入れても**黙って0件扱いになり**、合計カードと派生集計が過小表示になる | Step 7 で直す（本書スコープ内。決定済み）。恒久対応は `region_id` 列で `WHERE region_id = ?` に置き換えるだけで足りる |
| `web/src/lib/table-meta.ts` の `TABLE_META` 説明文に「神奈川県相当範囲」等の県固有記述 | `web/src/lib/ai/prompt.ts` の `tableCatalog()` がこの文言をそのまま**AIのシステムプロンプトに埋め込む**ため、他県データが増えてもAIが神奈川限定の説明のまま答え続ける | ADR-0016 Phase A（`docs/plans/PHASE_A.md` A-7「AIアシスタントへの配線」）でレジストリ由来の説明に切り替える計画がある。それまでは手動で文言を都度更新する |
| `taxa.redlist_kanagawa` という県名入りの列名 | 他県のレッドリスト評価を入れる場所が構造上ない | ADR-0019（taxon レジストリ）／Phase A の `taxon` テーブル設計まで待つ。当面は列を増やさず `caveat` に「未対応」と記録する |
| `vegetation_polygons.feature_id` が環境省 ArcGIS の生 `objectid` をそのまま主キーにしている | 他県分を足すと**主キー衝突のリスクが最も高い**（`objectid` は都道府県ごとに独立に採番されている可能性が高い） | 投入前に `source_id` を前置した合成キーに変える（Step 4 相当の投入スクリプト側で対応。スキーマの主キー制約自体は変えず、値の作り方を直す） |
| bbox の3重定義（`KANAGAWA_BBOX` in `m01_sites.py` / `BBOX` in `m99_validate.py` / `KANAGAWA_BBOX` in `c80_biodic_ikimonomap.py`） | 新エリアの bbox を1箇所直しても他の2箇所が神奈川のままになり、検証・収集が食い違う | 3ファイルとも直す。恒久対応は `scripts/regions.py` への集約（Step 1・決定事項1・§10） |
| 固定名の geojson を読んでいる箇所（`m01_sites.py`/`m05_tier1.py`/`c62_gsi_elevation.py`/`c61_gsj_seamless.py` が `nlni_w12_watersheds.geojson` を、`web/scripts/copy-geo-assets.mjs` が `nlni_w05_rivers.geojson`/`nlni_w12_watersheds.geojson` を、`web/scripts/build-geo.mjs` が `nlni_w12_watersheds.geojson`/`.jsonl` と `nlni_l03b_landuse_by_watershed.csv` を、それぞれ固定名で読む） | 新エリア分を無接尾辞のまま作ると §5 C の上書き事故になる。逆に接尾辞を付けて作ると、これらの箇所は新エリア分を見つけられない | Step 6・§5 C の改名規約に従い、新エリア分は別名で作った上で、これらの読み出し側にエリア一覧からの解決を足す（未着手） |
| `web/scripts/seed-d1-local.mjs` の全置換（テーブル単位 DELETE→全INSERT。`ryuiki`/`cells`/`derived`/`registry` の4ファイル固定） | エリア単位の差分投入ができず、新エリアを足すたびに神奈川分を含む全データを毎回作り直してシードし直す必要がある | Phase A以降のレジストリ運用が固まった段階で、エリア単位の差分シードを検討する（未着手） |
| `web/scripts/copy-geo-assets.mjs` の `FILES` 固定と `web/scripts/build-water-geo.mjs` の入力 `estat_shozaiki_kanagawa.geojson` | 新エリアの河川・流域界・町丁目ポリゴンを地図に出すには、この配列とファイル名を都度手で足す必要がある | Step 6 で個別対応。恒久対応は入力ファイルの発見をエリアリストから生成する仕組み（未着手） |
| 地図の `DEFAULT_CENTER` / `DEFAULT_ZOOM`（`web/src/lib/map/basemaps.ts`。`KANAGAWA_BOUNDS` は定義だけで未使用） | 複数エリアのデータが入っても地図の初期表示は神奈川中心のまま | UI 文言とあわせて別 PR に切り出す（決定事項7・§10）。エリア切り替え UI の要否はその PR で決める |
| UI と `table-meta.ts` の県名直書き（`web/src/app/layout.tsx` / `page.tsx` / `water/page.tsx` / `components/SiteNav.tsx` / `components/biota/BiotaExplorer.tsx` 等） | 画面の文言が神奈川限定のまま残り、他県データが表示されても説明文と矛盾する | L2到達時点（§6）で文言をエリア非依存の表現に書き換える。AIプロンプト混入分は上記のtable-meta.ts行と合わせて対応 |
| `zone` / `COASTLINE_LONLAT` の神奈川前提 | 他エリアの地点に対して誤った zone・海岸距離が算出される、または常にNULLになる | §7 参照。C23（海岸線）への置き換え（決定済み）と、zoneの定義をplaceのメタデータに持たせる設計（Phase B以降） |
| `scripts/x01_dwca.py` のEML（title/abstract・packageIDに「神奈川県」を直書き） | DwC-A を外部公開する場合、パッケージのメタデータが神奈川限定の説明のまま他県データを含むことになる | DwC-A公開前に対応する。現状はDwC-A自体が外部公開前（`docs/COLLECTOR_CONTRACT.md` の追記にある通りEMLの連絡先の組織承認待ち）なので緊急度は低い |

---

## 10. 決定事項一覧（索引）

本書中に埋め込んだ決定事項の一覧。「両論併記にしない」（本書の前提）ので、詳細は該当節を参照。

1. 新エリア対応は複製ではなく引数化に統一する（`scripts/regions.py` + `--region`。既定は
   `kanagawa`）。詳細: Step 1・Step 3・§9 bbox3重定義の行。
2. `region_id` の粒度は都道府県固定とする。詳細: §1。
3. 神奈川行のバックフィルは Step 2 でやる。詳細: Step 2。
4. 既存の無接尾辞 SID は改名しない（新エリア分だけ `_<region_slug>` を付ける）。詳細: §5
   Tier A・§8。
5. 1件検証の証跡は `reports/add_area_<region_slug>.md` に残すことを必須にする。詳細: Step 1。
6. `docs/DATA_INVENTORY.md` はエリア別セクションを `m99_validate.py --region` で自動生成する。
   詳細: Step 5。
7. `biotaTotals()` / `build-biota.mjs` の SID 直書き修正は本書スコープ内（Step 7）とし、
   `DEFAULT_CENTER` と UI 文言は別 PR に切り出す。詳細: Step 7・§6。
8. 海岸線は `COASTLINE_LONLAT` を廃止し、国土数値情報 C23（海岸線）に置き換える。詳細: §3・§
   7。
