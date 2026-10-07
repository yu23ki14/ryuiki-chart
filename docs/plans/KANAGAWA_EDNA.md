# 神奈川県「環境DNAのページ」eDNA 調査結果の取り込み設計

対象: https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html の xlsx 9 本（R3〜R7）を occurrence に取り込む。
source_id は **`kanagawa_edna`** 1 つ（9 本は 1 つの公表物。ファイルは attributes の `dataset_file` で区別する）。region は `jp-14`。
実測は 2026-10-07、手元の `data/db/registry.sqlite`・`data/processed/*.geojson` に対して行った（大づかみの値。実装時に測り直して宣言する）。

## 0. 決定済み事項（蒸し返さない）
- occurrence には**検出（リード数 > 0）だけ**を入れる。不検出（0）は原本表に残す。D1 に eDNA 専用表は作らない
  （D1 のシードは drizzle スキーマにある表だけを入れるので、`web/src/db/schema.ts` を触らなければ原本の新表は D1 に出ない。マイグレーションも不要）。
- 同定の確度が低い行（`低`・`cf.`・属止まり）も全部入れる。属止まりは属の taxon に寄せる。確度は attributes に残す。
- 座標は公開データに無い。地点ごとの**推定位置**を、根拠区分と精度つきで持つ。判別不能は NULL。
- 出典表記: 「神奈川県ホームページ『環境ＤＮＡのページ』（https://www.pref.kanagawa.jp/docs/b4f/suigen/edna.html）を加工して作成」。
  ライセンス原文は既存の「神奈川県サイトポリシー（出典記載により利用可…）」の raw（`registry/source/license.yaml:242`）をそのまま使う
  ＝ `license.yaml` は触らない。`register()` の `license_` に**同じ文字列**を渡す。
- 本番 D1 まで反映する。

## 1. 入力の実態（実測）
| ファイル | 年度 | 地点数 | 検出セル数 | 備考 |
|---|---|---|---|---|
| r3_kenmin_gyorui | 2021 | 10 | 114 | 魚類（12S）。種名は和名のみ。信頼度列なし |
| r4_kenmin_gyorui | 2022 | 23 | 295 | 同上 |
| r5_kenmin_gyorui | 2023 | 20 | 236 | 同上 |
| r5_project_gyorui | 2023 | 33 | 543 | 同上（プロジェクト＝第47号図1の33地点） |
| r5_kenmin_mtinsects-16s | 2023 | 19 | 1,617 | 昆虫等（16S）。和名中心・属は欧文が混在。信頼度 高/中 |
| r6_kenmin_mtinsects_amphi | 2024 | 12 | 965 | **列が1つ右にずれる**（A列が分類「脊椎動物/無脊椎動物」）。信頼度に **`低` がある** |
| r6_project_mtinsects-amphi | 2024 | 51 | 4,469 | 地点ヘッダが縦5行（水系・支川名・調査日・調査時刻・市町村） |
| r7_kenmin_kekka | 2025 | 13 | 692 | 「98.5%以上の一致のみ」の絞り込み版（他と収録基準が違う）。和名＋学名 |
| r7_project_kekka | 2025 | 約90 | 5,188 | 和名＋学名＋注釈。調査日は `YYYYMMDD` 文字列 |
| 合計 | | 約271 | **約14,100** | 全セル（0 を含む）は約13.7万 |

- 値はリード数（整数）。**個体数ではない**。0 は不検出。R3〜R5 は日付の空欄がある（実測して宣言する）。
- 採水日: R3〜R6 と r7_kenmin は Excel シリアル値（`date(1899,12,30)+n`）、r7_project は `YYYYMMDD` 文字列。
- 地点 ID は年度ごとに別体系（`K-21-1`・`K-21-8,9`〔2地点の合算〕・`S-KNG-0449`・`MF-K-20`・`k-25-04`〔小文字〕・`24-K-10`・`23-Pro-01`）。
  **ID を正規化して年度をまたいで同一視しない**。キーは「ファイル×列」にする（§2）。
- 水系・支川名・市町村にふりがな（カタカナ）が連結されたセルがある（`中津川ナカツガワ`・`松田町・開成町マツダマチカイセイマチ`）。
- 各ブックの `国RL`/`地方自治体RL` シート（2,852 行・48 行）は種ごとの和名・学名の参照表として使える（RL 種だけ）。

## 2. 全体の流れと原本表
```
c89_kanagawa_edna.py ──→ data/processed/kanagawa_edna_{sites,reads}.csv        （xlsx → 長持ち。0 も全部）
c89b_edna_site_coords.py ─→ data/edna/kanagawa_edna_site_coords.csv           （地点の推定座標台帳。コミットする）
c89c_edna_taxon_map.py ──→ registry/taxon/kanagawa_edna_name_map.csv          （名前 → taxon_id。コミットする）
                         └→ registry/taxon/supplement_taxa.csv                （registry に無い taxon の追加行。コミットする）
m07_kanagawa_edna.py ────→ ryuiki.sqlite: edna_sites / edna_reads / edna_detections
manifests/kanagawa_edna.yml + scripts/adapters/kanagawa_edna.py ──→ b06（input.table = edna_detections）→ b09 → b07 → b13 → D1
```

実行順は c89 → c89b・c89c（並行可）→ m07。c89c の出力（名前→taxon_id）を m07 が `edna_detections.taxon_id` に焼く
（adapter は `ctx.input_rows()` の 1 表しか読めず、registry も見られないため）。

### 2.1 収集 c89（`scripts/c89_kanagawa_edna.py`）
- `scripts/common.py` の `get`/`download`（1.5 秒スロット・UA は共通のもの。個人名を入れない）。`edna.html` を取得し、
  `/documents/97797/` 配下の `.xlsx` リンクを**HTML から動的に拾う**（c81 と同じ流儀。ファイル名は当てにしない）。
  生の xlsx は `data/raw/kanagawa_edna/`、sha256 を `register()` の notes に残す。
- xlsx は **openpyxl を使わず**標準ライブラリ（`zipfile`+`xml.etree`）で読む（CI の `requirements.txt` は PyYAML・pytest だけ。前任の
  `scratchpad/scripts/grid.py` が骨格）。共有文字列・日付シリアル・空セルを扱う。**入力は信頼しない**: 巨大セル・数式・外部参照は無視、
  シートは 1 枚目（種×地点の本体）だけ読む。
- レイアウトはファイル名ごとの宣言表 `LAYOUTS`（ヘッダ行・名前列・信頼度列・地点列の範囲・日付の形式）で持ち、**ヘッダの文字列を突き合わせて
  食い違えば止める**（列の位置を黙って信じない）。未知の .xlsx がリンクに増えた（R8 など）ときも止めて報告する（レイアウトを推測しない）。
- 地点列は「調査年度」行で識別する。ふりがなは「同じ文字列がカタカナで連結」する形なので、**元の文字列を `*_raw` に残したうえで**、
  既知の水系名・支川名・市町村名との前方一致で外した値を別列に持つ（一致しなければ raw のまま。推測で切らない）。
- 出力 CSV の列は §2.2 の表と一致させる。`register(source_id='kanagawa_edna', name='神奈川県 環境DNA調査結果（県民協働・プロジェクト）',
  publisher='神奈川県', url=edna.html, license_=<サイトポリシーの raw>, redistributable=1, ...)`。

### 2.2 原本表（`scripts/schema_edna.sql`、`m07_kanagawa_edna.py` が wipe+reload。m05 の `wipe()` と同じ流儀）
```sql
-- 地点（= ファイル × 調査地点列。269〜271 行）。座標は台帳（data/edna/…site_coords.csv）の写し。
CREATE TABLE IF NOT EXISTS edna_sites (
  site_key TEXT PRIMARY KEY,            -- '<ファイル名の stem>:<地点IDを trim したもの>'（正規化しない）
  dataset_file TEXT NOT NULL,           -- 'r6_project_mtinsects-amphi.xlsx'
  program TEXT NOT NULL,                -- 'kenmin'(県民協働) / 'project'(プロジェクト)
  assay TEXT NOT NULL,                  -- 'fish_12S' / 'insects_16S' / 'insects_amphibians' / 'all_taxa'（ファイルから宣言）
  fiscal_year INTEGER NOT NULL,         -- 2021..2025
  site_id_raw TEXT NOT NULL,
  water_system_raw TEXT, water_system_ja TEXT,
  tributary_raw TEXT,    tributary_ja TEXT,
  municipality_raw TEXT, municipality_ja TEXT,   -- 複数は「・」区切りのまま
  collected_on TEXT,                    -- YYYY-MM-DD。空欄・解釈不能は NULL（落とさない・補わない）
  collected_on_raw TEXT,                -- Excel シリアル値 or 'YYYYMMDD' の原表記
  lat REAL, lon REAL,                   -- 推定位置（台帳から）。公開データの座標ではない
  coord_source TEXT NOT NULL,           -- 'map_image' / 'estimated_from_name' / 'none'
  coordinate_uncertainty_m REAL,        -- coord_source<>'none' のとき必須
  coord_method TEXT, coord_note TEXT,
  source_id TEXT NOT NULL, source_ref TEXT NOT NULL   -- source_ref = '<URL>#<sheet>!<列>'
);
-- 検出も不検出も（約 13.7 万行）
CREATE TABLE IF NOT EXISTS edna_reads (
  read_id TEXT PRIMARY KEY,             -- '<site_key>:<xlsx の行番号>'（スナップショット内で安定）
  site_key TEXT NOT NULL REFERENCES edna_sites(site_key),
  class_ja TEXT, order_ja TEXT, family_ja TEXT, genus_ja TEXT,     -- 綱・目・科・属（原文。'-' は NULL）
  name_raw TEXT,                        -- 「参考種名（機械的な併記処理）」または「種名」
  name_adopted TEXT,                    -- 「種名（手動精査結果）」/「種和名」（採用名。fish は種名）
  name_sci_raw TEXT,                    -- r7 の「学名」。他は NULL
  name_note TEXT,                       -- 「（注）」「（和名なし）」「（cf.）」等の括弧書きを原文のまま
  reads INTEGER NOT NULL CHECK (reads >= 0),
  is_detected INTEGER NOT NULL,         -- reads > 0
  pident_qcov REAL,                     -- 'MAX(pident*qcovs)'（0〜1）。fish は NULL
  reliability TEXT,                     -- '高'/'中'/'低'。列の無いファイルは NULL
  national_rl_raw TEXT, pref_rl_raw TEXT, alien_raw TEXT, -- 各ファイルの RL・特定外来種の列（原表記）
  name_key TEXT NOT NULL,               -- 名前の正規化キー（§4）。taxon の解決はこれで引く
  taxon_id TEXT,                        -- m07 が name_map から焼く。NULL なら止める（unmapped は 0 件が条件）
  source_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_edna_reads_site ON edna_reads(site_key, is_detected);
-- adapter の入力。edna_reads の is_detected=1 に地点の列を結合した投影（m07 が同じトランザクションで作る。約 14,100 行）
CREATE TABLE IF NOT EXISTS edna_detections (
  record_key TEXT PRIMARY KEY,          -- = read_id
  taxon_id TEXT NOT NULL, scientific_name TEXT, vernacular_name TEXT, taxon_rank TEXT, red_list_category TEXT,
  observed_on TEXT,                     -- = collected_on
  lat REAL, lon REAL, coordinate_uncertainty_m REAL,
  attributes_json TEXT NOT NULL         -- §3.3 の attributes（m07 が組む。adapter は json を使う）
);
```

- `edna_detections` を別表にする理由: adapter は 1 入力しか読めない（`ctx.input_rows()`）。結合を adapter に持たせられない。
  代案「adapter 入力 = edna_reads、adapter が reads=0 を捨てる」は、全セル 13.7 万行がサンプルの上限（§6.3）と衝突するので採らない。
  m07 は `COUNT(*) FROM edna_detections = COUNT(*) FROM edna_reads WHERE is_detected=1` を検証する。
- 不検出を捨てない根拠は原本表にある。occurrence にもあとで「調査した地点・日」を足すなら `edna_sites` が元になる（今回は足さない）。

## 3. adapter と occurrence への写し方
### 3.1 列

| occurrence の列 | 値 |
|---|---|
| `record_key` | `read_id`（出典内で一意。重複は止まる） |
| `taxon_id` | `edna_detections.taxon_id`（§4。全行に入る） |
| `observed_on_raw` | `collected_on`（`YYYY-MM-DD` → 形は `day`）。NULL なら NULL（期間 NULL） |
| `lat`/`lon` | 台帳の推定座標。無ければ両方 NULL |
| `coordinate_uncertainty_m` | **新設**（§5-①）。座標があるとき必須 |
| `scientific_name`/`vernacular_name`/`taxon_rank` | name_map の値（学名は外来種判定 `is_alien_in_scope` の入力になる） |
| `red_list_category` | 国RL の原表記、無ければ県RL の原表記（どちらも空なら NULL）。n_red_list は「非空」で数えるので原表記のまま渡す |
| `attributes` | §3.3 |

adapter（`scripts/adapters/kanagawa_edna.py`）は kuma と同じ短さ（`json.loads(r["attributes_json"])` と列の写しだけ。import は `ingest.api`・`json`）。

### 3.2 日付の扱い
- 年度（4〜3 月）をまたぐので**年の形（`year`）は使わない**。空欄は NULL のまま取り込む（kuma の 4 行と同じ。落とさない・補わない）。
- 範囲検査 `date_between: ["2021-04-01", "2026-03-31"]`（R7 = 2025 年度の最後が 2026-03）。

### 3.3 attributes（JSON）
`dataset_file`・`program`・`assay`・`fiscal_year`・`site_key`・`site_id_raw`・`water_system`・`tributary`・`municipality`・`reads`・
`reliability`・`pident_qcov`・`name_adopted`・`name_note`・`cf`（括弧書きに cf. があれば true）・`rank_reduced`（属止まり・併記で上位に寄せたら true）・
`name_ambiguous`（「A/B」併記）・`coord_source`・`coord_method`・`dataset_filter`（r7_kenmin だけ `"match>=98.5%"`）・`alien_raw`・`national_rl_raw`・`pref_rl_raw`。
D1 には L2 を入れないので attributes は dist 側にだけ載る（ADR-0012 追記 9）。

## 4. 種の解決（実測と方針）
### 4.1 実測（registry.sqlite の taxon 41,454 行に対する単純突合）

名前は括弧書き（`（注）`・`（和名なし）`・`（cf.）`）を除き、学名は二名法部分、和名は `taxon.vernacular_name_ja` の完全一致で引いた。
**GBIF には照会していない**（網羅度の下限値）。検出行数で重み付けすると:

| 区分 | 異なる名前 | 検出行数 | 割合 |
|---|---|---|---|
| 学名が registry の species/二名法に当たる | 406 | 2,204 | 16% |
| 和名が `vernacular_name_ja` に当たる | 388 | 2,568 | 18% |
| 属・科止まり（「X属の一種」「アメマス類」等） | 136 | 604 | 4% |
| 「A / B」併記（`タモロコ / ホンモロコ` 等） | 155 | 917 | 6% |
| 学名はあるが registry に無い（r7・r5/r6 の欧文名） | 527 | 2,775 | 20% |
| 和名のみで registry に無い（フナ類・カワゲラ類・ユスリカ類など） | 503+ | 5,048 | 36% |

- r3〜r5 の魚類は和名しか無く、`ウグイ`・`アブラハヤ`・`ゲンゴロウブナ` のような普通種も `vernacular_name_ja` に無い（和名は taxa/記録由来の補完止まり）。
- r5/r6 の昆虫は**和名のみで学名が無い**（欧文は属 `Stenostomum属` 等だけ）。和名→学名の機械的な道は無い。
- 直接当たるのは約 34%、属で受けられるものを足しても約 4 割。**残りの 5〜6 割は registry に登録する経路が要る**。
  `taxon_id=NULL` で取り込む案は、検出の過半が種別集計（`summary_taxon_catalog` 等）から消えるので採らない。

### 4.2 方針（上から順に最初に決まったもの。1 つの名前は 1 つの taxon にしか行かない）
| 段 | 条件 | taxon |
|---|---|---|
| T1 | 学名の二名法が registry の **species** に一意に当たる | その taxon_id（複数なら kuma の規則: `rank='species'` かつ `scientific_name` が `canonical_binomial` と一致するもの。決まらなければ人の確認に回す） |
| T2 | 和名が `vernacular_name_ja` に一意に当たる | その taxon_id（複数・非 species は T4 へ回さず確認に回す） |
| T3 | 学名はあるが registry に無い | GBIF Backbone の species/match（EXACT の種または属のみ）で `gbif.<key>` を引き、`supplement_taxa.csv` に追加。key が既に registry にあればそれを使う |
| T4 | 和名のみで registry に無い | `common:taxon:kanagawa-edna.<slug(和名)>` を `status='unresolved'` で追加（学名は捏造しない。和名・綱目科属の原文・rank を持つ） |
| T5 | 属止まり・併記（`A/B`） | 行の**最も低い確定した階級**（シートの属列、無ければ科列）の taxon。T1〜T4 のいずれかで解決。`rank_reduced=true`・`name_ambiguous=true`・原文は attributes |

- 併記 `A/B` は片方を選ばない（確度の主張になる）。同属なら属、違えばシートの属→科の順で上位に寄せる。
- `cf.` は種のまま扱い、`cf` を attributes に残す（行は落とさない）。
- 低確度（`低`・pident×qcov が低い）も同じ規則で解決する。確度は attributes の `reliability`・`pident_qcov` で使う側が絞る。
- **GBIF が届かない・曖昧な名前は T4 に落とさず確認一覧に出す**（誤って別種に寄せない。T4 は「和名しか無い」ものだけ）。
- 追加 taxon の分類列（kingdom/phylum/class/order/family）は、シートの綱（昆虫綱・硬骨魚綱…約 30 種）を**ツール内の小さな対応表**で
  英語の class・phylum・kingdom に写して持たせる（`taxon_group.yaml` の先勝ちルールが英語の分類を見る）。対応表に無い綱は止める。
- 外来種判定は `scientific_name` の二名法一致（`taxon_assessment`）なので、T4（学名なし）の外来種は `n_alien` に出ない。
  `alien_raw` は attributes に残る。**この過少計上は宣言として書く**（§8-③）。

### 4.3 登録の経路（ライブラリ側の欠落。§5-②）
registry の taxon は `organism_records` と `taxa` からしか作られず、adapter 経路で taxon を足す口が無い（b06 は registry に無い `taxon_id` を
「解決できない行」として落として止まる）。`registry/place/site_supplement.csv` と同じ流儀で、**手書き CSV の supplement を build_taxon が読む**:

- `registry/taxon/supplement_taxa.csv`: `taxon_id, scientific_name, canonical_binomial, rank, kingdom, phylum, class, order, family,
  vernacular_name_ja, gbif_taxon_key, basis, evidence`（`basis` = `gbif_match`/`name_only`、`evidence` = 出典と確認の経緯）。
- build_taxon の検査: `taxon_id` は `common:taxon:gbif.<key>`（`gbif_taxon_key` と整合）か `common:taxon:kanagawa-edna.<slug>` のみ。
  既存の taxon_id と衝突したら止まる（上書きしない。`_insert()` の衝突検査に乗せる）。`status` は `gbif_match`→空、`name_only`→`unresolved`。
  `vernacular_ja_basis='supplement'`（既存の `override/taxa/records` と並ぶ新値）。件数は build の出力に出す。
- `registry/` 配下は registry の指紋に全ファイルが入る（`scripts/registry/common.py:351`）ので、ファイルを足せば registry は自動で作り直される。
- `kanagawa_edna_name_map.csv`: `name_key, rank, taxon_id, scientific_name, vernacular_name_ja, tier(T1..T5), evidence, reviewed`。
  `name_key` = NFKC・括弧書き除去・空白除去・小文字化・ふりがな除去（ふりがなは和名の末尾カタカナ連結。**既知の和名との前方一致でだけ外す**）。
  生成器 c89c は決定的（同じ入力で同じ出力）。人が直した行は `reviewed=1` で保持する。
- c89c の GBIF 照会は `scripts/c26_taxon_gbif_accepted.py` と同じ `common.get_json`（スロットル・UA 共通）。**この収集は担当が自分の環境で 1 回だけ回し、
  結果の CSV をコミットする**（CI は GBIF に触らない）。

## 5. 地点の推定座標
### 5.1 台帳の置き場

`data/edna/kanagawa_edna_site_coords.csv`（コミットする。`.gitignore` に `!data/edna/` を足す。`data/water/`・`data/vocab/` の「手で育てる再生成不能データ」と同じ扱い）。
`registry/` には置かない（registry の指紋が変わって語彙が無用に作り直される。台帳は語彙ではない）。列:
`site_key, water_system_ja, tributary_ja, municipality_ja, lat, lon, coord_source, coordinate_uncertainty_m, coord_method, evidence, grid01_ok, reviewed`。
m07 は台帳の `site_key` 集合と c89 の地点集合が**一致しなければ止まる**（ずれを黙って許さない）。

### 5.2 推定の手順（`scripts/c89b_edna_site_coords.py`。dev 用のツールで shapely を使ってよい。出力は台帳 CSV だけ）
使う参照データはすべてリポジトリ内にある（実測で確認）:

- `data/processed/nlni_w05_rivers.geojson`: 神奈川県の河川線 2,305 本（全件 `river_name_ja` あり・615 種の名前・`water_system_name_ja`）。
- `data/processed/estat_shozaiki_kanagawa.geojson`: 町丁・字ポリゴン 5,089 面（`muni_code`・`city_name`。58 市区町村名。区は市の和集合で扱う）。
- `data/processed/nlni_w12_watersheds.geojson`: 流域ポリゴン（検算用）。
- `data/db/ryuiki.sqlite` の `river_segments`（相模川水系 1,547 本。W05 と重なるので補助。395 本は「名称不明」）。
- `registry.sqlite` の `place_source_ref`（`key_space='grid01_latlon'`）: grid01 に解決できるかの検算。OSM の `osm_kanagawa_water` は点（重心）だけで線形が無いので使わない。

手順（地点 1 件ごと）:

1. 水系・支川名・市町村名をふりがな除去して正規化する。市町村は「・」で分け、各名を町丁ポリゴンの和集合 `G` にする。
2. 支川名が `-`・空なら本流とみなし、水系名（`相模川` 等）を支川名の代わりにする。
3. **W05 の線のうち `river_name_ja` が一致し、かつ `water_system_name_ja` が水系と一致するもの**を取る。`中津川` のように県内に同名の川が複数あるので、水系での絞り込みと `G` との交差が要る。
4. 線を `G` で切り取った集合が空でなければ、その集合の**長さ中心点**を位置とする。方式 = `river_in_municipality`。
5. 空なら、`G` の重心に最も近い同名の線の最近点を位置とし、方式 = `river_nearest_municipality`（精度に距離を足す）。
6. 支川名が一般名（`市内小河川`・`小水路`・`不明`・`本流`・`湧水`・`用水` だけ）、または W05 に名前が無い（`二ヶ領用水`・`ほたる川` 等）→ **座標 NULL**（`coord_source='none'`）。
   市町村の重心は使わない（地点を表さない値を精度付きで流すのは不可）。
7. 検算: 位置が `nlni_w12_watersheds` のどの流域に入るかを調べ、水系名と食い違えば `reviewed=0` の警告行にする。grid01 のキーが registry に無ければ `grid01_ok=0`。

`coord_source`・精度区分（`coordinate_uncertainty_m` の決め方）:

| coord_source | 条件 | coordinate_uncertainty_m |
|---|---|---|
| `estimated_from_name` | 手順 4 | 切り取った線の広がり（位置から線の端点までの最大距離）＋300 m（河川線の位置誤差）を 100 m 単位に切り上げ。下限 500 m |
| `estimated_from_name` | 手順 5 | 上に同じ＋最近点までの距離 |
| `map_image` | 第47号図1を読み取って位置合わせしたもの | 1,500 m（位置合わせの残差の 2 倍以上。下限 1,000 m） |
| `none` | 手順 6、または精度が 10,000 m を超える | NULL（lat/lon も NULL） |

- 実測の見込み: 支川名が W05/river_segments の名前に前方一致するのは 269 行中 166 行、空・`-`（本流）が 84 行、その他 19 行（用水・小河川など）。
  座標が付くのは概ね 6〜7 割の見込み（実装時に測って宣言する）。
- **`map_image`（第47号図1の 33 地点・2023 年度プロジェクト）は任意の上積み**。PDF の図を画像として読み、川の合流点・市境などの
  制御点 3 点以上で位置合わせして読み取る。制御点の残差を台帳の evidence に残す。読めなければ名前推定のままにする（失敗を許容する。受け入れ基準に入れない）。
  読み取りは担当が画像を見て行い、`reviewed=1` を付ける。
- 精度が付いた推定座標は ADR-0025/0026 の規則で **grid01（約 1km の格子）と流域へ解決される**（`coordinate_uncertainty_m` は解決の条件にしない。ADR-0006 規約4の改定 F4）。
  座標が NULL の記録は place_id NULL のまま落とさず、watershed の place_id NULL セルにだけ入る（kuma と同じ）。
- grid01 は `organism_records` の座標から作られる（4,087 セル。神奈川の範囲だけで 3,660 セル）ので、推定座標が**まだ無いセルに落ちると b06 が止まる**
  （`unresolved_place_count`）。台帳の `grid01_ok=0` は座標を NULL にして取り込む（理由を evidence に書く）のを既定とし、
  該当が行の約 5% を超えたら build_place の入力拡張（§5-③）をメインが判断する。

## 6. 境界の外の変更（ソース追加の許可リスト外）と検証
`scripts/check_source_add_boundary.py` は `manifests/`・`scripts/adapters/`・`registry/`・`scripts/tests/`・`data/sample/` だけを許す。
次は**ライブラリ側の欠落**なので、ADR-0012 の方針どおりソース追加の PR とは別（先）に直す。

| # | 変更 | 触るファイル | 検証 |
|---|---|---|---|
| ① | `occurrence_row` に任意列 `coordinate_uncertainty_m` を追加。`OPTIONAL_COLUMNS` に加え、runner の `AdapterRow`/`_validate` で「数値（非負・bool 不可）か None、lat/lon が None なら None」を検査。b06 の adapter 経路の INSERT（`b06_build_occurrence.py:520` 付近で `None` 固定）を `r.coordinate_uncertainty_m` に変える | `scripts/ingest/api.py`・`scripts/ingest/runner.py`・`scripts/b06_build_occurrence.py`・`docs/adr/0012-source-manifests.md`（追記） | 既存 adapter（kuma）の出力が 1 ビットも変わらない（`coordinate_uncertainty_m` は全行 NULL のまま）。runner の単体テスト（正常・負値・文字列・lat なしで値あり）。`scripts/tests/test_ingest_adapters.py` の既存テストが通る |
| ② | build_taxon が `registry/taxon/supplement_taxa.csv` を読む（§4.3）。ID 規則・衝突検査・`vernacular_ja_basis` の新値 | `scripts/registry/build_taxon.py`・テスト・`registry/README.md`・`docs/adr/0019-taxon-registry.md`（追記） | supplement が空（ヘッダのみ）のとき taxon の出力が現行と**全行一致**（`registry.sqlite` の taxon を前後で diff）。衝突・不正 ID・未知の `basis` で止まるテスト |
| ③ | （条件付き）grid01 に adapter 出典の座標を含める | `scripts/registry/build_place.py` | §5.2 の末尾の条件を超えたときだけ。やる場合は grid01 の件数が増える宣言差分を列挙して検証 |
| ④ | `.gitignore` に `!data/edna/`。`scripts/schema_edna.sql`・`m07`・`c89*`・`data/edna/` は収集・原本側（kuma の c81・m05 と同じ位置づけ） | — | — |

- ①②は pipeline のパス（`scripts/ingest`・`scripts/b06`・`scripts/registry`）なので、**`scripts/b00_run_full_gate.py` と `reports/serving_fingerprint.json` の更新が要る**
  （出力は動かないが、パスのハッシュが変わるため CI の鮮度検査が落ちる）。メインが PR の直前に 1 回だけ回す。
- ソース追加の PR（manifest・adapter・registry の CSV・テスト・サンプル）は `check_source_add_boundary.py` を**素のまま**通ること。
- 新規の収集・原本スクリプト（c89 系・m07・schema）は許可リスト外のパスなので、ソース追加の PR に混ぜない（kuma と同じく先行 PR に置く）。

## 7. manifest（`manifests/kanagawa_edna.yml`）
```yaml
source: kanagawa_edna
region: jp-14
target: occurrence
update_mode: snapshot          # 公表物を毎回丸ごと取り直す（m07 が wipe+reload）。年度が増えたら c89 の LAYOUTS を足して再実行
input:
  table: edna_detections
adapter: kanagawa_edna
expected_row_count: 14100      # 概算。実装後に実測で埋める
checks:
  - not_null: [record_key, taxon_id]
  - unique: [record_key]
  - row_count_between: [14000, 14300]   # 実測の ±1%程度。実測後に締める
  - in_registry: taxon
  - date_between: ["2021-04-01", "2026-03-31"]
evidence: >   # 実測値・種の解決の内訳・座標の根拠区分ごとの件数・日付が空欄の件数・出典表記を書く
expected:
  period_shapes: {day: <日付あり行数>}     # 日付なしの行は形に数えない
  place: {coord_resolved: <概算 8,500>, coord_unresolved: 0}
  cube:
    dated_rows: <日付あり行数>
    dated_no_coordinate_rows: <日付あり・座標なし>
    leaf_cell_source_rows: <座標あり・日付あり>      # grid01 の leaf 側。kuma は 0
    leaf_cell_source_rows_no_coordinate: 0
    month_cell_source_rows: <座標あり・日付あり>
    watershed_dated_resolved_rows: <座標があり流域に入る行>
    watershed_dated_unresolved_rows: <日付あり・流域に入らない/座標なし>
```

- 値は**すべて実装後に実測で埋める**（宣言を通すために曲げない。差分は理由を書く）。上は関係式。`coord_resolved + coord_unresolved` = 座標ありの行数で、
  `coord_unresolved` は grid01 に解決できない行（`grid01_ok=0` を NULL にする運用なら 0）。
- `taxon_id` を `not_null` に入れる（T4 で全行に入る設計。入らなければ c89c/m07 側で止める）。
- `redistributable` は旗でしかない（ADR-0028）。`edition` は付けない（kuma と同じ。`source_registry` の行から `source_edition` が作られる）。

## 8. 実装担当（ファイルが衝突しない 3 単位）
読ませる資料は各担当に書いた節だけ。重い処理（b00 全量・build:v2 全量・serving snapshot の全量・CI の clone 再現）は担当に回させない（メインが 1 回）。
担当は「スキル（/simplify・/code-review 等）やサブエージェントを起動しない」。レビュー担当は「ファイルを変更しない・コミットしない」。
`ryuiki.sqlite` は読み取り専用で開く。書くのは m07 だけで、手元の確認は**一時コピーの DB**に書く（本物の `data/db` に m07 を流す前にメインの確認を取る）。
xlsx は信頼できない入力として扱う（`python -I`・シートの外部参照や数式は読まない）。

### 担当 A: 収集・原本表・座標台帳（PR-A。ライブラリに触れない）
- 読む節: 本書 §1・§2・§3.2・§5。参考実装: `scripts/c81_kanagawa_kuma.py`、`scripts/m05_tier1.py:121`（`load_wildlife`）・`wipe()`、`scripts/schema_tier1.sql`。
- 触るファイル（新規）: `scripts/c89_kanagawa_edna.py`、`scripts/c89b_edna_site_coords.py`、`scripts/m07_kanagawa_edna.py`、`scripts/schema_edna.sql`、
  `data/edna/kanagawa_edna_site_coords.csv`、`scripts/tests/test_c89_kanagawa_edna.py`、`scripts/tests/test_m07_kanagawa_edna.py`、
  `scripts/tests/test_c89b_edna_site_coords.py`、`.gitignore`（`!data/edna/` の 1 行）、`docs/UNDATAFIED_TIERS.md`（1 行）。
  m07 は `registry/taxon/kanagawa_edna_name_map.csv`（担当 C の出力）を**読むだけ**。担当 C が出すまではテスト用 fixture の CSV で通す。
- 受け入れ基準:
  1. 9 本の xlsx から `kanagawa_edna_sites.csv`（約 271 行）と `kanagawa_edna_reads.csv`（約 13.7 万行）が出る。各ファイルの地点数・検出セル数が §1 の表と一致（実測値を `LAYOUTS` に宣言して突合）。
  2. 列の位置がずれたファイル・未知のファイル・日付形式の食い違いで**止まる**（テストで変異を当てて確かめる。「通った」を鵜呑みにしない）。
  3. 採水日は ISO、空欄は NULL。r6_kenmin の列ずれ・r7_project の `YYYYMMDD`・小文字の地点 ID・`K-21-8,9` が正しく扱われる。ふりがな除去が既知名との前方一致だけで、一致しなければ raw のまま。
  4. 台帳が全地点を持つ。`coord_source` の分布・精度の分布・`grid01_ok=0` の件数・水系と流域の食い違い警告の件数を出力に出す。座標ありの精度は §5.2 の表どおり、`none` は lat/lon/精度が NULL。
  5. m07 が 3 表を作り、`edna_detections` の件数が `edna_reads WHERE is_detected=1` と一致。`name_map` に無い名前が 1 件でもあれば止まる。CHECK 制約（reads>=0・座標あり⇒精度あり）。
  6. User-Agent は `scripts/common.py` のものを使う（個人名を入れない）。
- 速い検証: `.venv/bin/python3 -m pytest scripts/tests/test_c89_kanagawa_edna.py scripts/tests/test_m07_kanagawa_edna.py scripts/tests/test_c89b_edna_site_coords.py -q`。
  c89 の実行は `.venv/bin/python3 scripts/c89_kanagawa_edna.py --offline`（取得済みの xlsx を使う。ネットワーク無しでも回る）。

### 担当 B: ライブラリ（PR-B。ソース追加ではない）
- 読む節: 本書 §4.3・§6 の①②（③は判断待ち）。ファイルは `docs/adr/0012-source-manifests.md:105-131`、`scripts/ingest/{api,runner}.py`、
  `scripts/b06_build_occurrence.py:466-535`、`scripts/registry/build_taxon.py`（`_insert`・`_load_vernacular_overrides`・`build()`）。
- 触るファイル: `scripts/ingest/api.py`、`scripts/ingest/runner.py`、`scripts/b06_build_occurrence.py`、`scripts/registry/build_taxon.py`、
  `scripts/tests/`（上の変更に対応する既存テストの拡張。新規は `test_build_taxon_supplement.py` 程度）、`docs/adr/0012-source-manifests.md`・`docs/adr/0019-taxon-registry.md`（日付付き追記）、
  `registry/README.md`（supplement の説明）、`registry/taxon/supplement_taxa.csv`（**ヘッダ行だけの空ファイル**。担当 C が中身を入れる）。
- 受け入れ基準: §6 の①②の「検証」欄。加えて `scripts/tests/test_adapter_boundary.py` が通る（adapter の import 境界は動かさない）。
  **既存出力が動かないこと**を、`registry.sqlite`（taxon の全行）と b06 の出力（kuma を含む `occurrence` の全行）の前後 diff 0 件で示す（縮小サンプルで可。全量はメインが b00 で 1 回）。
- 速い検証: `.venv/bin/python3 -m pytest scripts/tests/test_ingest_adapters.py scripts/tests/test_ingest_manifest.py scripts/tests/test_adapter_boundary.py scripts/tests/test_registry_taxon*.py -q`。

### 担当 C: 種の解決・manifest・adapter・サンプル（PR-C。ソース追加。担当 A・B のマージ後に最終確認）
- 読む節: 本書 §3・§4・§7。ファイルは `manifests/kanagawa_kuma_sightings.yml`、`scripts/adapters/kanagawa_kuma_sightings.py`、`scripts/tests/test_adapter_kanagawa_kuma_sightings.py`、
  `scripts/s01_build_sample.py:264-312`、`data/sample/coverage.yaml`、`docs/adr/0012-source-manifests.md:105-131`。
- 触るファイル: 担当 C は 2 つの PR に分かれて出す（ファイルは担当 A と重ならない）。
  - **PR-A に載せる分（許可リスト外のため）**: `scripts/c89c_edna_taxon_map.py`、`scripts/tests/test_c89c_edna_taxon_map.py`。担当 A のブランチへ main が統合する（c89 の CSV 出力契約〔§2.2〕を前提に先行で書ける）。
  - **PR-C**: `registry/taxon/kanagawa_edna_name_map.csv`、`registry/taxon/supplement_taxa.csv`（中身）、`manifests/kanagawa_edna.yml`、`scripts/adapters/kanagawa_edna.py`、
    `scripts/tests/test_adapter_kanagawa_edna.py`（＋manifest の既存テストの期待値更新）、`data/sample/`（再生成物。一時ディレクトリへの clone で。本物のチェックアウトで `s02` を回さない）、
    任意: `registry/caveat.yaml`・`registry/caveat_scope.yaml`（`source_edition` の `source_id=kanagawa_edna` に「リード数は個体数ではない」「座標は推定（精度つき）」「年度で解析・収録基準が違う」）。
    `registry/caveat_scope.yaml` の `values.source_id` に `kanagawa_edna` を足す必要があるか（現状は `moe_ias_list` だけ）を最初に確認する。
- 受け入れ基準:
  1. name_map が全名前を持ち（unmapped 0）、各行に tier と evidence がある。T1/T2 で複数に当たった名前は 0（確認済み）。supplement の taxon_id が registry の再ビルド後に全件存在し、既存 ID と衝突しない。
  2. 解決の内訳（T1〜T5 の名前数・検出行数）を実測して本書 §4.1 の表を更新する。T4 の件数が想定（検出の 3〜4 割）から大きく外れたらメインに報告する。
  3. adapter は `ingest.api` と `json` のみ import。`scripts/check_source_add_boundary.py` が差分を**変更なしで**通す。
  4. 縮小サンプルで b06→b09→b07→b13 が通り、宣言（`expected`）がサンプルでも合う（§9-②を先に決める）。
  5. 実データでの宣言値は、一時ディレクトリにコピーした DB に m07 を流して b06 までを回して測る。全量 b00 はメインが 1 回。
- 速い検証: `.venv/bin/python3 -m pytest scripts/tests/test_adapter_kanagawa_edna.py scripts/tests/test_ingest_manifest.py scripts/tests/test_adapter_boundary.py -q`、
  `.venv/bin/python3 scripts/check_source_add_boundary.py --files manifests/kanagawa_edna.yml scripts/adapters/kanagawa_edna.py registry/taxon/supplement_taxa.csv`。

### PR の順序
PR-A（収集・原本表・台帳・c89c。担当 A と C の分を統合）と PR-B（ライブラリ）は独立なので並行。PR-C は A と B が main に入ってからベースを付け替える（親がマージされたら子のベースを main へ）。
b00 の全量ゲートは PR-B と PR-C で各 1 回（PR-B は出力不変の証明、PR-C は新出典の宣言値と `reports/serving_fingerprint.json`・`serving_snapshot.json` の更新）。
PR-C の本文に `serving:snapshot -- --mode diff` の before/after 表を貼る（スナップショットを更新するため）。

## 9. 本番反映
前提: PR-A/B/C がマージ済み・`build:v2` が新鮮・`reports/serving_fingerprint.json` の `git_head` が今のコード。drizzle のスキーマ変更は無い
（新しい原本表は D1 に出ない。`web/drizzle/migrations` を触らない）ので、**停止を伴う切り替えは無い**。

1. 手元: `cd web && pnpm run db:setup`（レジストリ・v2 は鮮度判定で必要なものだけ作り直す）→ `pnpm run db:verify` 相当でローカル D1 の行数を確認。
2. 流す表と順序（`web/src/lib/table-meta.ts` の `TABLE_ORIGIN` と照合。DEPLOYMENT.md の「新しい表だけを書き出して流す」と同じ手順）:
   - registry 側: `taxon`（supplement の追加分）・`source`・`source_edition`（`caveat`・`caveat_scope` は追記したときだけ）。`license`・`place`・`place_source_ref` は変わらない見込み（変われば足す）。
   - キューブ側: `occurrence_agg`・`summary_taxon_catalog`・`summary_watershed_occurrence`・`summary_species_catalog`・`summary_group_year`・`summary_effort_year`・`summary_grid_catalog`。
     `observation_agg` は変わらない（流さない）。
   - 本番に行がある表は流す前に `DELETE FROM`（`export-d1-sql.mjs` は素の INSERT）。**registry の表（taxon・source・source_edition）を先、キューブを後**にする（キューブの taxon_id が参照先を持つ状態を保つ）。
3. **流す前に旧状態を控える**: `pnpm run db:export -- --table <上の表>` の .sql を、変更前の本番相当（main の直前のビルド）で書き出して保管する（ロールバック用）。
   `wrangler d1 export` は使わない（OOM）。流し方は 20MB 刻みのファイル単位の再試行ループ。
4. 行数検証: `pnpm run db:verify:remote`。加えて `wrangler d1 execute ryuiki --remote --command "SELECT source_id, COUNT(*) FROM occurrence_agg GROUP BY 1"` で
   `kanagawa_edna` の n の合計が b07 の出力と一致すること、`SELECT COUNT(*) FROM taxon WHERE taxon_id LIKE 'common:taxon:kanagawa-edna.%'` が supplement と一致すること。
5. コードのデプロイ: `registry/` の再生成物（`web/src/lib/registry/generated-source.ts` の source・`OCCURRENCE_SOURCE_IDS` など）が変わるので `pnpm run deploy`（`pnpm deploy` ではない）。
   **データを先、コードを後**（新コードは新しい source_id を前提にするが、旧コードは未知の source_id の行を無視するだけ）。
6. 動作確認: `/biota`・`/map`・AI のツール経由で eDNA 出典が出る・出典表記が出る・座標なしの出現が地図で落ちない。
7. ロールバック: コードは `wrangler rollback`。データは手順 3 の旧 .sql を `DELETE FROM` のあと流し直す（スキーマ変更が無いので追加の逆操作は無い）。
   DEPLOYMENT.md の「ここで問題が出たら旧コードへ戻すだけ」と同じ構造。事前にオーナーの許可を取る（本番への破壊的操作〔DELETE〕を伴うため）。

## 10. 不安が残る論点
1. **推定座標が地図で「正確な点」に見える**。cube・地図側は `coordinate_uncertainty_m` を見ない（web の cube 層に参照が無い。ADR-0025 は「使う側が精度で絞る」としている）。
   1km 格子に 3km の不確かさを持つ点が入る。対策は caveat（任意）と attributes・精度の保持まで。画面での扱い（精度が大きい点を地図から外す等）は別 Issue にするか、
   今回は精度の上限を 10,000 m→3,000 m に絞って座標を付ける点を減らすか、オーナーに決めてほしい。
2. **座標なしの記録が流域に入らない**。水系名（相模川など）は分かっているのに、座標が NULL だと watershed の place_id NULL セルに入る。
   水系名から流域 place へ直接割り当てる道は ADR-0026 の範囲外（推測で割り当てない）。座標が付く割合（6〜7 割の見込み）がそのまま流域別集計の被覆率になる。
3. **外来種の過少計上**。T4（学名なし）の外来種は `n_alien` に出ない。`alien_raw` は attributes にあるので、後から和名で `taxon_assessment` に寄せる拡張はできる。今回は宣言として残す。
4. **和名のみの昆虫 5 割が unresolved の taxon になる**（約 700〜1,000 件の `status='unresolved'` 行が taxon に増える）。学名を捏造しない代わりに、
   registry の `taxon` 表の見かけの件数・種数の集計（`summary_species_catalog`）に「未照合の和名種」が混ざる。画面の種数の説明に影響しうる。後続の和名→学名の照合は別 Issue。
5. **年度間・ファイル間の比較ができない**（アッセイ・参照 DB・収録基準・信頼度の閾値が違う。r7_kenmin は 98.5% 以上のみ）。attributes と caveat に出すが、
   n（記録数）を年度で並べると見かけの増減が出る。ADR-0025 の「n は記録数」のまま。
6. **サンプルの上限**: 検出 14,100 行は `ADAPTER_INPUT_WHOLESALE_MAX_ROWS=5000` を超える。`coverage.yaml` の predicate で絞ると、マニフェストの `expected` の絞り込み版が要るが、
   `declaration_counts.yaml` の overlay が覆うのは `expected_row_count` と period_shapes・cube 宣言までで、`expected:` の place/cube 値の overlay があるかは未確認。
   担当 C が最初に確かめる。足りなければ、①上限の引き上げ（`scripts/s01_build_sample.py`。ライブラリ側の別 PR）か、②サンプル専用の小さい入力にする、をメインが選ぶ。
7. **同じ名前の別種・同名異物**: `vernacular_name_ja` の完全一致は同名の別 taxon（例: 別階級の同名）に当たりうる。T1/T2 で複数に当たれば確認に回す規則にしているが、
   一意に当たったものが誤りの場合は検出できない。`reviewed` の抜き取り確認（各 tier から 30 件程度）を担当 C の完了条件に足すのが安全。
8. **新規利用規約の確認**: 加工の旨の表記は §0 のとおり。第三者が権利を持つ部分（第47号の図・写真）は取り込まない（座標の読み取りだけに使い、図は再配布しない）。

## 11. メインの判断（2026-10-07）
- 原本ローダの名前は `m07_kanagawa_edna.py`（`m06_water.py` が既にあるため。本文の m06 は m07 に読み替え済み）。
- §10-1（2026-10-07 オーナー決定: 10km＋流域一意）: `estimated_from_name` の精度の上限は **10,000 m**。ただし切り取った線（手順5は最近点を含む線）が W12 流域（b09 の流域解決と同じ層）の**ただ1つに長さ 98% 以上収まり、置いた点もその流域の内側**にある地点だけに座標を付ける。収まらないもの・超えたものは `coord_source='none'`（lat/lon/精度 NULL。evidence に `multi_watershed` 等）。`map_image` は任意の上積みのまま。
- §5.2 末尾の `grid01_ok=0`: まず件数を実測して報告する（座標を NULL にする処理はまだ入れない）。件数を見てメインが③（build_place の入力拡張）か NULL 化かを決める。
- §10-2・10-3・10-4・10-5: 宣言として受け入れる（PR 本文と caveat に書く）。
- §10-6: 担当 C が最初に確かめて報告。決めるのはメイン。
- §10-7: 各 tier から 30 件の抜き取り確認を担当 C の完了条件に足す。
- `m07` を本物の `data/db/ryuiki.sqlite` に流すのはメインだけ（流す前に別名のコピーを取る）。担当は一時コピーの DB で確かめる。
