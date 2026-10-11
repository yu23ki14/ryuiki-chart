# 奄美 Step 3c: A33 土砂災害警戒区域（新しい表）、水道の水源種別、ダムの容量（Issue #89）

Step 3 の残り。3つは性格が違う。A33 は新しい表（`hazard_zones`）を作る大きい仕事で、水道の水源種別とダムの容量は 3b と同じ「PDF の数値を cells に入れる」小さい仕事。2026-10-11 に設計担当が原資料を取得して確かめた。**2本の PR に分けることを推奨する（§9 未決 1）。**

## 0. 実測で Issue の記述と変わった点

1. **A33 は BODIK の最新版に奄美が入っている。** 国土数値情報の2018年版への切り替えは要らない。データは「鹿児島県土砂災害警戒区域データ等」（`460001_kgod016`、CC BY 4.0）の 2026-02-10 現在版（BODIK への登録は 2026-02-11）。
2. **件数は Issue の「2013年版 1,085」の約5.6倍。** 奄美5市町村の**指定済み 6,038 ポリゴン**（警戒区域 3,134・特別警戒区域 2,904）。区域の指定が進んだ結果とみられるが、原因は確認していない（比べるのは件数だけにする）。
3. **特別警戒区域は警戒区域の内側にある。** 同じ箇所番号の赤（特別）は黄（警戒）にほぼ全部含まれる（急傾斜: 赤の面積の 99.9997% が同じ箇所番号の黄に重なる）。**面積を区分をまたいで足すと二重に数える。** 表の面積は1ポリゴンごとの値にし、合計を作る場合は区分ごと（§1.4）。
4. **同じ箇所番号の行が複数ある（120箇所、最大10行）。** 箇所番号は主キーにならない（§2）。
5. **水道の水源種別は「上水道」と「簡易水道」で別の PDF・別の分類。** 上水道（奄美市・瀬戸内町・龍郷町）はダム・自流・浅井戸・深井戸・湧水などの**年間取水量（千㎥）**。簡易水道（大和村・宇検村・瀬戸内町）は**表流水・地下水・その他の取水箇所数と取水量（㎥）**。大和村・宇検村は簡易水道だけ。**単位が千㎥と㎥で違う。**
6. **ダムの容量は BODIK 版の流域治水 PDF（documents に既にある 4 ページ）には無い。** 容量は鹿児島県サイトの**10ページ版**（`aq09/documents/88914_20230208131603-1.pdf`、ファイル名の日付 2023-02-08）の p5（大和）・p6（大川）にある。これは県サイトの文書なので、ライセンスは BODIK 版（CC BY 4.0）ではなく県サイトの規約（`LICENSE_PREF_KAGOSHIMA`）。Issue の「大川 2,180千㎥・大和 721千㎥」は一致した。
7. **大和ダムの日別データは既に入っている**（Step 2b、`kagoshima_kasen_dam_amami`、`dam_2`＝大和ダム。貯水量の最大 462.2 千㎥ ≦ 容量 721 千㎥）。**大川ダムは入っていない**（河川砂防情報システムの `dam_info.js` に無い）。新しい時系列は作らない。
8. **神奈川の水道の水源の表（`water_source` など）には載せない。** あれは水源→浄水場→町丁目の経路を手で辿るグラフで、座標・親子関係・根拠資料が要る。統計の PDF の「市町村×取水の種別」は性格が違う。cells に入れる。

## 1. A33 土砂災害警戒区域（BODIK）

### 1.1 原資料（`data/raw/bodik_a33/` に保存済み。BODIK は再配布可の CC BY 4.0 だが、生ファイルは gitignore 済み）

- データセット: `https://data.bodik.jp/dataset/460001_kgod016`（CKAN の package_show の `id=460001_kgod016`）。提供は鹿児島県土木部砂防課管理係。更新頻度「随時更新」。リソースは**時点ごとに別 ZIP が積み上がる**（2022-01 から 2026-02 まで22本）。最新を使う。
- リソース: `20260210_shape.zip`（37,223,945 B）、sha256 `aa2227a89a53d794d159371571793a40d3b923792f436409b8006d190f608492`。
  `https://data.bodik.jp/dataset/cd7f7659-1898-41ca-bcb7-b5ed242656e1/resource/f5597cba-93a4-4c38-9cd4-acd015a7f54f/download/20260210_shape.zip`。URL に UUID が入るので取得は package_show で引く（c97 と同じ）。間隔は5秒以上（連続で 403）。
- 説明文: 「土砂災害警戒区域と土砂災害特別警戒区域の範囲を表す 2026.2.10 現在のデータ」。
- ZIP の中身（ファイル名は日本語。UTF-8 フラグあり）: `20260210_shapeデータ提供（鹿児島県）/{1系,2系}/{指定,未指定}/*.shp`。**奄美は `1系` だけ**（`2系` に奄美5市町村の行は0）。1系は奄美群島＋薩摩川内市（甑島）＋三島村・十島村などを含む（県全体ではない）。
- CRS: JGD2011 平面直角座標系 第I系（EPSG:6669。.prj は ESRI WKT）。DBF は cp932（.cpg は shift_jis）。ジオメトリは全て Polygon（`shapeType=5`）。
- 属性は表（d_=土石流、k_=急傾斜地の崩壊、j_=地すべり。r=特別警戒＝red、y=警戒＝yellow）で列名が違う:

| ファイル（1系/指定） | 現象 | 区分 | 箇所を表す列 | 全体件数 |
|---|---|---|---|---|
| `d_yzone1` / `d_rzone1` | 土石流 | 警戒 / 特別警戒 | `keiryunum`（渓流番号 `dok527-0032`）・`keiryuname` | 1,269 / 1,003 |
| `k_yzone1` / `k_rzone1` | 急傾斜地の崩壊 | 警戒 / 特別警戒 | `kashonum`（`kyu527-0094-01`）・`kashoname` | 3,434 / 3,576 |
| `j_yzone1` | 地滑り | 警戒（特別は無い） | `kashonum`（`jis524-2004`）・`kashoname`・`gid` | 98 |
| `未指定/sk_{y,r}zone1` | 急傾斜（基礎調査完了・未指定） | — | 同上 | 2 / 3（全部龍郷町） |

  共通: `genshoname`（現象。原文は土石流／急傾斜地の崩壊／**地滑り**）、`kubun`（警戒区域／特別警戒区域）、`new_city`（市町村）、`shozaichi`（所在地）、`jimuname`（事務所）、`koujinum`（公示番号）、`koujidate`（公示日。和暦の文字列）、`filechosho`・`filetosho`（調書・公示の PDF 名。URL ではない）、`suikeiname`・`kasenname`（水系名・河川名。土石流のみ、奄美の1,122行に値）。

### 1.2 奄美5市町村の件数（実測。`new_city` の完全一致）

指定済み（`指定/`）。`未指定/` の5行（龍郷町、`koujidate='基礎調査完了'`）は**入れない**（指定前で、区域ではない。件数だけ notes に書く）。

| ファイル | 奄美市 | 瀬戸内町 | 龍郷町 | 宇検村 | 大和村 | 計 |
|---|---|---|---|---|---|---|
| d_yzone1（土石流・警戒） | 388 | 355 | 145 | 98 | 42 | 1,028 |
| d_rzone1（土石流・特別） | 319 | 290 | 119 | 61 | 38 | 827 |
| k_yzone1（急傾斜・警戒） | 881 | 575 | 346 | 160 | 79 | 2,041 |
| k_rzone1（急傾斜・特別） | 900 | 586 | 347 | 165 | 79 | 2,077 |
| j_yzone1（地滑り・警戒） | 16 | 10 | 12 | 27 | 0 | 65 |
| 計 | 2,504 | 1,816 | 969 | 511 | 238 | **6,038** |

- `new_city` と `shozaichi` の市町村名は全行で食い違わない（検査済み）。県全体では `薩摩川内市上甑町` のような町名付きの値があるが、奄美5市町村は完全一致で足りる。
- 喜界町・徳之島の3町・沖永良部・与論は同じ ZIP にあるが**入れない**（奄美大島 5 市町村の範囲。`regions.py` の `muni_codes` と同じ）。

### 1.3 ジオメトリの実測

- 6,038 ポリゴン、頂点 198,460（1ポリゴン平均 33、最大 261）。**単純化は要らない**（植生は 437KB の行が出る。こちらは小さい）。マルチパートは1行だけ（k_y）。
- 無効なジオメトリが10行（自己交差など）。`shapely.make_valid` で直す。直した件数を出力して notes に書く。
- WGS84 に直した GeoJSON は 5 桁（約1m）で合計 4.33MB。**座標をぼかさない方針なので 6 桁（約0.1m）で持つ**（約 4.7MB 見込み。植生・奄美が 11.4MB で入っているので D1 に収まる）。1行 約 0.7KB。
- W12 流域（`nlni_w12_watersheds_amami`）に代表点（`representative_point`）が入る行は 1,822/6,038（30%）。W12 が海岸近くを覆っていないため（植生・奄美も 3,005/9,979 で同じ傾向）。**流域は引けた行だけ入れる**。残りは NULL。
- 面積: 平面直角座標（第I系）の面積。縮尺係数 0.9999 の補正はしない（誤差 約0.02%）。区分別の総和は 警戒区域 土石流 26.2・急傾斜 37.8・地滑り 2.11 km²、特別 土石流 0.75・急傾斜 20.86 km²（**足し合わせない**。0.3）。

### 1.4 公示日

- `koujidate` は 6,038 行のうち 6,003 行が `(令和|平成)(元|N)年M月D日` に合う。**35行は `令和2月3月13日`**（`令和2年3月13日` の誤記とみられる。令和2年3月13日は別の43行にある）。
- **推奨: `designated_on` は NULL、`designated_on_raw` に原文のまま。** 誤記を直さない（宣言した差）。35 件を過不足なく検査する。補う場合は別途決める（未決 5）。
- 変換は `doccells.era_to_year` ではなく月日まで要る。新しい小さな関数を `c103b` の中に置く（1箇所だけ）。年は平成24〜令和4年（平成24: 506・25: 485・26: 626・27: 1,710・28: 597・29: 590・30: 595・31: 311・令和2: 43・3: 294・4: 246）。

## 2. 新しい表 `hazard_zones`（推奨案）

前例は `vegetation_polygons`（`biodic_veg2024_amami`）。**`region_id` 列は付けない**（前例の表に無い。地域は `source_id` に `_amami` を単語として含めて表す。`regions.region_of_source_id`）。

```sql
-- scripts/schema_tier1.sql の末尾に追加
CREATE TABLE IF NOT EXISTS hazard_zones (
  zone_id TEXT PRIMARY KEY,        -- '<箇所番号>:<r|y>:<同じ箇所番号の中の連番 1..>'。例 kyu527-0094-01:y:1
  site_code TEXT,                  -- 箇所番号（keiryunum / kashonum）
  site_name_ja TEXT,               -- 箇所名（keiryuname / kashoname。42行は空）
  phenomenon_code TEXT,            -- debris_flow / steep_slope / landslide
  phenomenon_ja TEXT,              -- 原文（土石流／急傾斜地の崩壊／地滑り）
  zone_kind_code TEXT,             -- warning / special_warning
  zone_kind_ja TEXT,               -- 原文（警戒区域／特別警戒区域）
  municipality_ja TEXT,            -- new_city
  locality_ja TEXT,                -- shozaichi
  river_name_ja TEXT,              -- suikeiname（水系名）と kasenname（河川名）を '|' でつなぐ。土石流のみ。空は NULL
  office_ja TEXT,                  -- jimuname
  designated_on TEXT, designated_on_raw TEXT,   -- 公示日（ISO / 原文）。35行は raw だけ
  notice_no_raw TEXT,              -- koujinum
  area_m2 REAL,                    -- ポリゴンごとの面積（第I系の平面）。区分をまたいで足さない
  centroid_lat REAL, centroid_lon REAL,         -- representative_point（凹形でも必ずポリゴンの内側）
  watershed TEXT,                  -- 代表点が W12 に入った行だけ
  geometry_geojson TEXT,           -- 6 桁、単純化なし
  source_id TEXT, source_ref TEXT  -- source_ref: '<shp 名>#<レコード番号>'
);
CREATE INDEX IF NOT EXISTS ix_hz ON hazard_zones(source_id, phenomenon_code, zone_kind_code, municipality_ja);
```

- **主キーを `zone_id` にする理由**: 箇所番号は120箇所で重複する（分割された区域）。連番は同じ箇所番号・同じ色の中で shapefile の順に付ける。ZIP が更新されても順が変わりうるので、`source_ref` に shp 名とレコード番号を残す。
- **`regions.name()` の規則**: source_id は `bodik_kagoshima_dosha_amami`。`c103b` の出力名も同じ接頭辞（`data/processed/bodik_kagoshima_dosha_amami.{csv,jsonl}`）。
- **神奈川は取り込まない（推奨）**。神奈川県の土砂災害警戒区域は別の提供元（国土数値情報 A33 か県）で、`hazard_zones` は `source_id` で地域を分けられるので後から足せる。今回の目的（奄美の物語）に要らない。
- 現象・区分のコードは英語スラグ（`protected_areas.category_code` と同じ流儀）。原文は `_ja` に残す。
- 表の主キー衝突対策: `m05_tier1.load_vegetation` と同じ「他の出典の行と `zone_id` が衝突したら止める」検査を入れる。

### 2.1 どこまで公開するか（推奨: 最小構成）

| 出し方 | 推奨 | 理由 |
|---|---|---|
| D1 の表（`schema.ts` → `db:generate`）・`TABLE_ORIGIN`・`TABLE_META` | **する** | `run_sql`／`describe_schema` の対象になる（AI が「この流域の警戒区域」を数えられる） |
| `get_records`（`record_sets` に `hazard_zones` を足す） | **する** | `mammal_mesh` と同じ最小構成。MCP／AI は出典単位で読める。ジオメトリは `id` 指定の1件だけ `include_geometry` |
| 地図 API `/api/geo/hazard-zones` | **しない** | 画面の読み手が無い。全件で約 5MB を返す API を、使い手が決まる前に公開しない。画面を作るときに `municipality`／`phenomenon`／bbox 必須で足す（別 Issue） |
| 画面（地図レイヤー） | **しない** | 同上。物語（2010年豪雨と並べる）で使うときに設計する |
| 流域との交差集計 | **しない** | 代表点で `watershed` が引けるのは30%。面積比の集計は W12 が海岸まで届かないと偏る。必要になったら別 Issue で、W12 ポリゴンとの面積交差をバッチで作る（`shapely` で 6,038 × 36 は数秒） |

### 2.2 `get_records` の扱い（`web/src/lib/records.ts`）

- `RECORD_TABLES.hazard_zones`: `table: RECORD_SET_TABLES.hazard_zones`、`pk: "zone_id"`、`search: ["site_name_ja","locality_ja"]`、`cols`: ジオメトリ以外の全列、`geometry: "geometry_geojson"`。
- `record_sets: hazard_zones: hazard_zones`（`registry/source/access.yaml`）。`scripts/registry/build_source_access.py` の `D1_RECORD_TABLES` に表名を足す。`records.test.ts` が DDL と列を突き合わせる。
- `get_records` の入力の説明文（`recordsInputSchema` の `record_set` の説明）と MCP ツール説明の列挙に `hazard_zones` を足す → `web/src/lib/mcp/__snapshots__/tools.test.ts.snap` と `web/src/lib/ai/__snapshots__/prompt.test.ts.snap` が変わる（`vitest -u` でなく、差分を目で確かめて直す）。

## 3. 水道の水源種別（鹿児島県 令和5年度水道統計）

### 3.1 原資料（`data/raw/kagoshima_suido/` に保存済み）

親ページ: `https://www.pref.kagoshima.jp/ae09/suidou/suidoutoukei/r5toukei.html`。URL は同じディレクトリ `…/suidou/suidoutoukei/documents/` 配下。

| ファイル | 内容 | 頁 | sha256 |
|---|---|---|---|
| `121966_20250627104846-1.pdf`（93KB） | **（2）年間取水量，浄水量，給水量（上水道）**。市町村×水源の種別の年間取水量（千㎥）・浄水量・給水量・有収率 | 1（文字情報あり） | `0df62e48bc107929ec2e15b44843d1ad71f0525f18bfb37480db6af770d1abee` |
| `121966_20250627105147-1.pdf`（81KB） | **（1）実績，原水種別，浄水方法（簡易水道）**。箇所数・人口・取水量（表流水／地下水／その他）・浄水量 | 1（文字情報あり） | `2ca69e4023ebb08dd34541c3517e3c59ac9ebafa3f5f32072a7611d570dcab0c` |
| `121966_20250627105224-1.pdf`（88KB） | （2）簡易水道集計表。奄美の行なし（使わない） | — | `a0267e0235ed87b6bce2a67623aede4dad29ca27bec3e92087d478e027ed6626` |
| `121966_20250627162725-1.pdf`（4.2MB、23頁） | 令和5年度水道統計調査の一括版。**p2 以外は画像（文字情報なし）**。使わない（分割版の方が文字がある） | — | `c2f8b6722ccdddb22b5a60d2163cd4c535b7c68dcf8626c7b61d3436db7f65eb` |

- 刷り込みの時点は「令和６年３月」。令和5年度（2023年度）の実績。
- 前回の Issue の「令和5年度の水道統計の PDF（前回の URL は補助金の表で誤り）」は、上の2本に決まった（補助金の表は `…111151-1.pdf`）。
- ライセンス: 鹿児島県サイト（`LICENSE_PREF_KAGOSHIMA` = 「鹿児島県ホームページ（無断転載・改変不可）。事実（数値）のみ抽出し出典を明記」）。オーナー決定のとおり事実だけを抜き出し、PDF は再配布しない。`redistributable=0`。

### 3.2 表の構造と値（`water_truth.csv` が正解。48 セル）

**上水道**（p1。単位は千㎥/年。列は左から ダム・湖水・自流・伏流水・浅井戸・深井戸・湧水・合計）:

| 市町村 | ダム | 湖水 | 自流 | 伏流水 | 浅井戸 | 深井戸 | 湧水 | 合計 |
|---|---|---|---|---|---|---|---|---|
| 奄美市 | 932 | 0 | 3,291 | 0 | 126 | 1,483 | 0 | 5,832 |
| 瀬戸内町 | 0 | 0 | 1,403 | 0 | 0 | 1 | 0 | 1,404 |
| 龍郷町 | 0 | 0 | 714 | 0 | 0 | 515 | 0 | 1,229 |

- ヘッダの「地表水①（ダム・湖水・自流）」「地下水②（伏流水・浅井戸・深井戸）」「湧水③」「合計④=①+②+③」の見出しは文字の位置がずれているが、**数値は8列**（種別7つ＋合計）で、3行とも種別の和＝合計（検算済み）。
- 奄美市の他の列（浄水量 5,635・有収水量 4,785・有収率 84.9% など）は入れない（水源種別が目的）。
- **大和村・宇検村は上水道に行が無い**（簡易水道のみ）。

**簡易水道**（p1。取水量は㎥/年、箇所は取水の箇所数）:

| 市町村 | 簡易水道の箇所数 | 表流水 箇所 | 表流水 取水量 | 地下水 箇所 | 地下水 取水量 | その他 箇所 | その他 取水量 | 計 取水量 |
|---|---|---|---|---|---|---|---|---|
| 大和村 | 1 | 8 | 152,442 | 0 | 0 | 0 | 0 | 152,442 |
| 宇検村 | 1 | 1 | 337,260 | 0 | 0 | 0 | 0 | 337,260 |
| 瀬戸内町 | 10 | 16 | 108,627 | 3 | 32,250 | 0 | 0 | 140,877 |

- 検算: 3行とも 表流水＋地下水＋その他＝計。
- **宇検村の取水量 337,260 は同じ行の実績年間給水量 225,524 より多い**（刷り込みのまま）。浄水量 337,000 とは合う。事実の食い違いではなく原表の癖。notes に書き、値は直さない。
- 奄美市・龍郷町は簡易水道の行が無い。瀬戸内町は上水道と簡易の両方に行がある（別の水道）。

### 3.3 載せ方（cells。`water_source` には載せない）

- documents 2行: `kagoshima_suido_r5_joryo`（上水道）・`kagoshima_suido_r5_kani`（簡易）。publisher「鹿児島県」（PDF に課名が無いので県だけ）、url は各 PDF、n_pages 1、license `LICENSE_PREF_KAGOSHIMA`、fetched_at と doc_sha256 は取得したファイルから。
- cells: table_id `x1`（上水道）・`x2`（簡易）、page_no 1。row_key は**市町村名**（`奄美市` など。1つの表の中で一意）、col_key は上の見出しの語（`ダム`・`湖水`・`自流`・`伏流水`・`浅井戸`・`深井戸`・`湧水`・`合計`／`簡易水道の箇所数`・`表流水（取水箇所）`・`表流水（取水量）`…`計（取水量）`）。unit は `千m3`／`m3`／`箇所`。`is_total=1` は合計・計の列。value_type int、value_raw はカンマ付きの印字。
- **`fiscal_year=NULL`、`era_raw="令和5年度"`**（3b と同じ。1年だけの系列を `/documents` に作らない。水道統計は毎年出るので、系列にしたくなったら次年度を足して `fiscal_year` を入れる別 PR。未決 3）。
- extractor `pdfplumber`（文字情報から表を読む。`doccells.pdf_tables`）、verified_by は行内の和が合計に一致したセルを `auto:xtext+arith`（1.0）、一致を取れない列（箇所数）は `claude(text)`（0.9）。**単位を取り違えない**ため、`x1` と `x2` を別の table_id にし unit を必ず付ける。
- notes（事実だけ。`blocks_timeseries` 全部 0）: ①上水道と簡易水道は別の水道で、単位が違う（千㎥・㎥）、②大和村・宇検村は簡易水道のみ、奄美市・龍郷町は簡易水道の行なし、③種別の分類が違う（上水道はダム・自流・井戸など、簡易は表流水・地下水・その他）、④宇検村の取水量が給水量を上回る（原表のまま）、⑤令和5年度（刷り込み「令和６年３月」）。
- 件数: x1 が 3行×8列＝24、x2 が 3行×8列＝24。**合計 48 セル**、notes 5件。

## 4. ダムの容量（鹿児島県 流域治水 10ページ版）

### 4.1 原資料（`data/raw/kagoshima_dam_cap/88914_20230208131603-1.pdf` に保存済み）

- URL `https://www.pref.kagoshima.jp/aq09/documents/88914_20230208131603-1.pdf`（10頁、PowerPoint 由来、文字情報あり）。sha256 `cba99583e097182a64dce9aa0877944565256beb2e89a042c582e03e2a79a744`。県の河川課の「奄美大島地域流域治水プロジェクト」（BODIK 版 4 頁と同じ題名の別版）。同じディレクトリの `…171327-1.pdf`（5頁）はこの10頁版の前の版とみられ、容量は無い。`…171419-1.pdf`（13頁）・`…171534-1.pdf`（10頁）は別の地域とみられ**未確認**（奄美の語が無い）。
- BODIK の package（`460001_1_01_ryuuikichisuipurojekuto`）に10頁版は**ない**（奄美は 4 頁の `7_1_amamiooshimatiiki.pdf` だけ）。ので、ライセンスは県サイトの規約。

### 4.2 値（`dam_truth.csv` が正解。9 セル）

| ダム | 項目 | 値 | 単位 | 頁 | 形 |
|---|---|---|---|---|---|
| 大和ダム | 有効貯水容量 | 721 | 千㎥ | 5 | 表（文字） |
| 大和ダム | 洪水調節容量 | 517（有効貯水容量の 71.7%） | 千㎥・% | 5 | 表 |
| 大和ダム | 洪水調節可能容量 | 125（17.3%） | 千㎥・% | 5 | 表 |
| 大和ダム | 水害対策に使える容量 | 642（89.0%） | 千㎥・% | 5 | 表 |
| 大川ダム | 有効貯水量 | 2,180 | 千㎥ | 6 | 図中の文字（「Ｖ＝２，１８０千㎥」。全角） |
| 大川ダム | うち洪水調節可能容量 | 106 | 千㎥ | 6 | 同上（「Ｖ＝１０６千㎥」） |

- 検算（全部通る）: 517＋125＝642、517/721＝71.7%、125/721＝17.3%、642/721＝89.0%（丸めの範囲）。大和ダムの実測の貯水量（`kagoshima_kasen_dam_amami`、日平均の最大 462.2 千㎥）は容量 721 以下で、矛盾しない（検算ではなく健全性の確認として notes に書く必要はない）。
- 大川ダムは「利水ダム」。管理者は奄美市、所有者・河川管理者は鹿児島県（同じ頁）。事前放流の実績は令和2年度に台風10号（9/3〜5）。大和ダムも同じ台風で事前放流（p5）。これらは notes にまとめて1件で足りる（数値ではない）。
- **新規ダムの時系列は作らない**。大和ダムの貯水の時系列は既にある。大川ダムの貯水量は、県の河川砂防情報システムに無く、水環境総合情報サイト（水質）にだけ地点がある（Step 2c 以降）。
- `新住用ダム`（九州電力）は容量が載っていない（事前放流の対象として名前だけ）ので入れない。

### 4.3 載せ方

- documents 1行: `kagoshima_amami_ryuiki_chisui_10p_2023`（題名「奄美大島地域流域治水プロジェクト」、n_pages 10、license `LICENSE_PREF_KAGOSHIMA`）。既存の `bodik_460001_amami_ryuiki_chisui_2022`（4頁、CC BY 4.0、cells 0）とは別の文書として並べ、notes に「同じ題名の BODIK 版（4頁）には容量が無い」と書く。
- cells: table_id `p5_t1`（大和の表。page_no 5。row_key `大和ダム`、col_key `有効貯水容量`・`洪水調節容量`・`洪水調節容量の割合`…）と `p6_text`（大川。page_no 6。row_key `大川ダム`、col_key `有効貯水量`・`うち洪水調節可能容量`）。row_key をダム名にして、col_key に項目を置く。割合は unit `%`、容量は `千m3`。
- extractor: p5 は `pdfplumber` の表、p6 は本文の文字（`manual:pdftext`）。割合の列は割り算の検算が通ったセルを `auto:xtext+arith`、それ以外は `claude(text)`。
- `fiscal_year=NULL`（ダムの諸元は一時点の値。`era_raw`: 空。PDF に基準日の記載なし。ファイル名の 2023-02-08 は notes に書く）。
- 件数: 大和ダム7（容量4＋割合3）＋大川ダム2＝**9 セル**、notes 2件。

## 5. 検算と受け入れ基準

### A33（担当1）
- 件数: §1.2 の表と過不足なく一致（ファイル別×市町村別の25通りと総数 6,038）。一致しなければ止める。
- `zone_id` が一意。`site_code` の重複が120箇所（宣言した事実）。
- ジオメトリ: 全行が Polygon／MultiPolygon、`make_valid` 後に全て有効、頂点数 198,460 以上（直した後で変わりうるので下限の検査）、WGS84 の範囲が奄美の bbox（`regions.py` の jp-46: 129.1〜129.85E・27.95〜28.8N）に入る。**外れた行は止める**（喜界などが紛れていないか）。
- 面積: ポリゴンごとの `area_m2` の総和が 警戒区域 土石流 26.2・急傾斜 37.8・地滑り 2.11 km²、特別 土石流 0.75・急傾斜 20.86 km²（±0.01）。
- 公示日: 変換できた 6,003 行と、できない 35 行（すべて `令和2月3月13日`）が過不足なく一致。
- 代表点が W12 に入る行は 1,822 前後（W12 が変わらなければ一致。ずれたら理由を調べる）。
- **正解 csv**: 抜き取りの 30 行（各ファイル×市町村の先頭1行、`site_code`・現象・区分・市町村・公示日 raw・頂点数）を `scripts/tests/fixtures/amami_a33/truth.csv` にし、`c103b` の出力と一致すること。ZIP が無い環境（CI）でも、フィクスチャ（小さい shapefile 相当の GeoJSON 数件）で変換関数をテストできる。変異（`kubun` を書き換える）で止まること。
- 書き込み後（D1 の表と原本）: `hazard_zones` の `source_id` 別行数＝6,038。ほかの出典の行が変わらない（`m05_tier1.wipe` は `source_id` 単位）。

### 水道・ダム（担当2）
- §3.2・§4.2 の正解 csv（`water_truth.csv` 48行、`dam_truth.csv` 9行）をフィクスチャ（`scripts/tests/fixtures/amami_water_dam/`）にして、cells の全セル（doc_id・table_id・row_key・col_key・value_raw・unit）と過不足なく一致。
- 行内の和＝合計（上水道 3行、簡易 3行）。大和ダムの 517＋125＝642 と割合3つ。本文／表に**その文字列が現れること**（PDF が無ければ警告して SPEC のまま。CI の最小環境）。
- `DOC_SERIES_WHERE` を通るセルが 0（`fiscal_year` が全 NULL）。`is_total=1` は上水道 3＋簡易 3＝6 セル。row_key（表の中）が一意。
- 書き込みで自分の3つの doc_id 以外の行が変わらない（`test_doccells.py` の前例）。

## 6. 登録・ライセンス・件数

新しい source_id は3つ（`_amami` を単語として含める）。

| source_id | 内容 | ライセンス | record_count | access.yaml |
|---|---|---|---|---|
| `bodik_kagoshima_dosha_amami` | A33 土砂災害警戒区域・特別警戒区域（奄美5市町村。BODIK 460001_kgod016、2026-02-10 現在） | CC BY 4.0（`redistributable=1`） | 6,038 | `records: [hazard_zones]` |
| `kagoshima_suido_amami` | 令和5年度水道統計（上水道・簡易水道の取水の種別） | `LICENSE_PREF_KAGOSHIMA`（`redistributable=0`） | 48 | `reason: document_cells`（basis: doc_id=kagoshima_suido_r5_joryo・kagoshima_suido_r5_kani） |
| `kagoshima_dam_capacity_amami` | 大和・大川ダムの有効貯水容量（県の流域治水10頁版） | `LICENSE_PREF_KAGOSHIMA`（`redistributable=0`） | 9 | `reason: document_cells`（basis: doc_id=kagoshima_amami_ryuiki_chisui_10p_2023） |

- `registry/source/license.yaml`: CC BY 4.0 は既存の mappings（BODIK 河川砂防と同じ原文）に合わせる。鹿児島県サイトの原文は既に `all_rights_reserved` に写してある（ハブ・ウミガメ・ノネコと同じ。新しい原文は無い）。**A33 のライセンス原文は package_show の `license_id=cc-by-40-intl`／`license_title`＝Creative Commons Attribution 4.0 International** なので、c97／c94 が登録に使う文字列と揃える。
- `docs/LICENSE_MATRIX.md`: 一覧に3行、Step 3 の節の続きに数行（A33 は座標を加工していない・無効ジオメトリを直した件数・公示日の誤記35件を直さず NULL・特別警戒区域は警戒区域の内側で面積を足さない／水道は事実のみ・PDF 再配布なし・上水道と簡易の単位が違う／ダム容量は県の10頁版で BODIK 版（4頁）に無い）。
- `data/sample/coverage.yaml`: `document_closure.doc_ids` に cells のある3つの doc_id を足す。**`hazard_zones` はサンプルに入れない**（Tier 1 の表はサンプルの対象外と coverage.yaml の冒頭に書いてある）。
- 件数を直書きしたテスト: `scripts/tests/test_registry_source.py` の `source` 173→176・`source_edition` 175→178（2本に分けるなら PR ごとに +2／+1）。ほか、出典の一覧を直書きしたスナップショット（`web/src/lib/mcp/__snapshots__/tools.test.ts.snap`・`web/src/lib/ai/__snapshots__/prompt.test.ts.snap`）と `web/src/lib/records.test.ts`・`web/src/lib/ai/tools-records.test.ts`・`web/src/lib/cube/__fixtures__/cube-fixture.ts`（表の DDL のフィクスチャ）を grep（`vegetation_polygons`・`173|175`）で洗い出して直す。`generated*.ts` は `build:registry:ts` で作り直す（手で書かない）。
- `web/src/lib/source-catalog.ts` は registry 由来なので触らない。

## 7. D1・シード・serving への影響

- **D1 のマイグレーション**: `web/src/db/schema.ts` に `hazardZones`（`vegetationPolygons` の隣）を足し、`pnpm run db:generate`（0022 が1本増える。SQL を手で書かない）。`TABLE_ORIGIN.hazard_zones = "main"`（`table-meta.ts`）と `TABLE_META` に説明を足す。表数は 50→51、シード対象は 49→50 表。CLAUDE.md の「50 テーブル／49表」の数字を直す。
- **シード**: `web/scripts/seed-d1-local.mjs` は Drizzle の宣言から owner map を作る（`ryuiki` の原本に表があれば入る）ので**コード変更は不要**。原本 `ryuiki.sqlite` の変更でフィンガープリントが変わり、初回は全入れ直し（想定内）。本番は `db:export` の .sql を `wrangler d1 execute --remote --file` で流す（`hazard_zones` の INSERT は約 5MB 増。行 0.7KB で D1 の 1 行 2MB 制限に遠い）。
- **serving snapshot（`data/sample/serving_snapshot.json`）**: A33 は変わらない見込み（キューブ・系列に出ない。サンプルにも入らない）。水道・ダムは `fiscal_year=NULL` で系列が 0 なので変わらない見込み。`/sources`・`describe_catalog` に出典が3つ増える可能性があるので、`serving:snapshot --mode diff` を回して、差が**3出典の増分だけ**であることを確かめる（3b §8.6 と同じ）。
- **b00 の指紋**: パイプライン（b03〜b13）のパスを触らないので `reports/serving_fingerprint.json` は鮮度の検査に引っかからない見込み。r01 の入力に `access.yaml`・`license.yaml` が入るので registry は作り直し（`ensure-registry.sh` に任せる）。

## 8. 実装担当ごとの節

2本の PR に分ける場合（§9 未決 1）は、PR-1＝担当2＋担当3、PR-2＝担当1＋担当3の A33 分。1本にする場合は3人を並行。ファイルが衝突しないように、**登録・ライセンス・件数は担当3が一手に持つ**。

### 担当1: A33 の取得・変換・D1 の表（Python と web の表）
ファイル: `scripts/c103a_a33_fetch.py`、`scripts/c103b_a33_hazard_zones.py`、`scripts/schema_tier1.sql`（`hazard_zones` を足す）、`scripts/m05_tier1.py`（`load_hazard_zones` と `jobs` への追加）、`scripts/tests/test_c103b_a33.py`、`scripts/tests/fixtures/amami_a33/*`、`web/src/db/schema.ts`、`web/drizzle/migrations/`（`db:generate`）、`web/src/lib/table-meta.ts`、`web/src/lib/records.ts`（`RECORD_TABLES`）、`web/src/lib/records.test.ts`、`web/src/lib/cube/__fixtures__/cube-fixture.ts`。

1. `c103a`（c97 の形）: package_show → 最新の ZIP を `data/raw/bodik_a33/` に保存し sha256 を出力。呼び出しの間は5秒以上。保存済みで sha が同じなら取り直さない、違えば止める（正解 csv を作り直す前に人が確かめる）。ZIP を展開した先（`x/`）は作業用（gitignore 済み）。
2. `c103b`: `shapefile`（pyshp）で `1系/指定/*.shp` を読み（DBF は cp932）、`new_city` が5市町村の行だけ取る。座標は `pyproj`（EPSG:6669→4326、`always_xy=True`）、無効は `make_valid`、面積は変換前の平面で `shapely`、代表点は WGS84 の `representative_point`。出力は `data/processed/bodik_kagoshima_dosha_amami.{csv,jsonl}`（`feature` の GeoJSON は 6 桁）。§5 の検算を書く前に全部通す。`--dry-run`。User-Agent に個人名を入れない。
3. `m05_tier1.py` に `load_hazard_zones`（`load_vegetation` を手本に: `wipe`＋衝突検査＋`ws.find` による `watershed`）。`regions.REGIONS` の順に呼ぶ必要は無い（奄美だけ）。`scripts/tests/test_m01_m05_regions.py` の前例にならって速いテストを足す。
4. web 側は §2.2・§7 のとおり。`schema.ts` の列は DDL と一致させる（`records.test.ts` が突き合わせる）。
5. 速い検証だけ: 該当の pytest、`cd web && pnpm vitest run src/lib/records.test.ts`。`db:generate` の出力を目で確かめる。

### 担当2: 水道・ダムの cells
ファイル: `scripts/c104a_amami_water_dam_fetch.py`、`scripts/c104b_amami_water_dam_cells.py`、`scripts/tests/test_c104b_amami_water_dam_cells.py`、`scripts/tests/fixtures/amami_water_dam/{water_truth.csv,dam_truth.csv}`。
1. `c104a`（c102a の形）: §3.1 の2本（`…104846-1.pdf`・`…105147-1.pdf`）と §4.1 の1本を保存し sha256 を出力。期待する sha256 は上のとおり。5秒以上の間隔。保存済みで同じなら取り直さない。
2. `c104b`（c102b の形）: SPEC は §3.2・§4.2 の表。上水道と簡易は `doccells.pdf_tables`（pdfplumber）で読み SPEC と突き合わせる。大川ダムは本文の文字（全角）を `NFKC` で正規化して「2,180」「106」が現れることを検査。検算は §5。`doccells.commit_doc` で3つの doc_id を書き、source は §6 の2つ。`--dry-run`。
3. テスト: DB も PDF も要らない（fixtures の csv だけ）。§5 の受け入れ基準・変異・件数（48・9・合計の列6）・notes（5件・2件）。検算関数は c104b のものをそのまま呼ぶ（テストの中に書き直さない）。
4. 担当2は `registry/`・`docs/LICENSE_MATRIX.md`・`coverage.yaml`・件数直書きテストに触れない。

### 担当3: 登録・ライセンス・件数・スナップショット
ファイル: `registry/source/access.yaml`（`record_sets` に `hazard_zones`、出典3つ）、`registry/source/license.yaml`、`scripts/registry/build_source_access.py`（`D1_RECORD_TABLES` に `hazard_zones`）、`docs/LICENSE_MATRIX.md`、`data/sample/coverage.yaml`、`scripts/tests/test_registry_source.py` と件数・出典の一覧を直書きしたテスト・スナップショット、`web/src/lib/registry/generated*.ts`（`pnpm run build:registry:ts`。r01 を先に回すのはメイン）、`CLAUDE.md` の表数。
1. §6 のとおり。source_id と原文は担当1・2と共有する定数（上の表）。c103b／c104b がまだ無くても先に書ける。
2. 件数を直す前に grep で洗い出す（§6）。3b の前例（`5389b51` 付近）。
3. 速い検証だけ: `test_registry_source.py`・`build_source_access` のテスト、`cd web && pnpm vitest run src/lib/registry src/lib/mcp src/lib/ai`。

### どちらも
- スキル（/simplify・/code-review 等）やサブエージェントを起動しない。`git add` はパスを明示する。
- `build:v2`・b00・全量ゲート・サンプルの再生成・clone での CI 再現は回さない（メインが回す）。
- `p1_maker`・`p1_maker_v2`・`p3_fixer`・`c25`・`c26` は回さない。
- 原本 `data/db/*.sqlite` は書き込み前に `.backup` を取る。原本への書き込みは検算が通った後にメインが回す。

## 9. 統合（メインと担当。3b §8 と同じ）

1. 書く前に `cells.sqlite` と `ryuiki.sqlite` を `.backup`。`c103b` → `m05_tier1.py` → `ryuiki.sqlite`、`c104b` → `cells.sqlite`。
2. 自分の行以外が変わらないこと: cells 側は3つの doc_id 以外の cells・documents・notes・extraction_log・source_registry を EXCEPT で突き合わせて差0。`ryuiki.sqlite` 側は `hazard_zones` 以外の表の行数が書く前と同じ（`source_registry` は+2〜3行だけ）。
3. 書く前に、検証が本番の経路を通っているかを確かめる: c103b／c104b の検算が、テストの中の書き直しではなく関数を呼んでいること。`get_records(record_set=hazard_zones, source_id=bodik_kagoshima_dosha_amami)` で行が読め、`id` 指定＋`include_geometry` で1件のジオメトリが返ること。`web/src/lib/cube/documents.ts` を通した問い合わせで水道・ダムの文書の系列が0本であること。
4. r01 → `build:registry:ts` → `build:v2` → `db:setup`（マイグレーション0022・シード）。
5. サンプル（`s01`。`s02` は本物のチェックアウトで回さない）→ 一時ディレクトリへの clone での CI 再現 → b00（`reports/serving_fingerprint.json` を一緒にコミット）。
6. serving スナップショットは §7 のとおり変わらない見込み。`--mode snapshot` が通ること。差があれば `--mode diff` の表を PR に貼る。
7. 重い処理（4〜6）はメインが裏で1回だけ回す。

## 10. 未決（オーナーに聞くこと。推奨案つき）

1. **1本の PR にするか、2本に分けるか。** 推奨: **2本**。PR-1＝水道＋ダム（3b と同じ形の小さい仕事）、PR-2＝A33（新しい表・マイグレーション・`get_records`・スナップショット）。A33 はレビューの論点（表の形・公開範囲）が違い、水道・ダムを待たせない。出典の件数のテストが衝突するので、PR-2 は PR-1 のマージ後に件数だけ直す（PR-1 を先に出す）。1本にするなら担当3人を並行し、件数は +3 に一度で直す。
2. **A33 の公開範囲。** 推奨: **D1 の表と `get_records` まで。地図 API・画面・流域交差集計は作らない**（§2.1）。画面で使う段（2010年豪雨の物語で、警戒区域の中の被害を並べる）で別 Issue にする。
3. **水道の `fiscal_year`。** 推奨: **NULL**（§3.3。1年だけの系列を作らない）。年次の系列にしたいなら、令和4年度以前の水道統計（同じ表がある）を足して複数年にしてから `fiscal_year` を入れる別 PR。
4. **大川ダムの容量の出典。** 推奨: **県サイトの10頁版を使う**（`LICENSE_PREF_KAGOSHIMA`、事実のみ）。BODIK 版（4頁）には容量が無い。10頁版を BODIK に載せるよう依頼するのは任意。
5. **公示日の誤記 35 件（`令和2月3月13日`）。** 推奨: **直さない（`designated_on`＝NULL、raw は原文）。** 別の43行が `令和2年3月13日` なので誤記とみられるが、推定で値を作らない。直すなら、宣言した差として35行を列挙し機械検証する。
6. **`未指定/` の5行（基礎調査完了・龍郷町）。** 推奨: **入れない**（指定前で区域ではない）。入れる場合は `zone_kind_code` ではなく別の列（`designated` 0/1）が要り、利用者が区域と取り違える。
7. **A33 の2013年版（国土数値情報）との比較。** 推奨: **しない**。Issue の 1,085 と今回の 6,038 は定義（指定済みか、基礎調査分か）が違う可能性があり、確認していない。件数を物語で比べるなら、国土数値情報の2018年版を別に取ってから。
8. **神奈川を入れるか。** 推奨: **入れない**（§2）。`hazard_zones` は `source_id` で地域を分けられる設計にしてある。

## 11. 決定（メイン、2026-10-11）

- §10 の 1 は分けない。1本の PR にする（登録系が担当3に集まっていて衝突せず、全量ゲートを1回で済ませるため）。
- §10 の 2〜8 は推奨案どおり。
