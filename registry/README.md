# 語彙レジストリ（`registry/`）

Phase A（`docs/plans/PHASE_A.md`, ADR-0016）の成果物。v1 のファクト（`measurements` /
`organism_records` / `sensor_timeseries` 等）は一切書き換えず、`unit` / `variable` /
`place` / `taxon` / `caveat` という語彙だけを別枠で並走させたもの。

## このディレクトリの中身：手書き vs 生成物

**`registry/` 配下はすべて手書き（Git 管理・レビュー対象）。** ここには生成物は置かない。

| ファイル | 中身 |
|---|---|
| `region.yaml` | region（`jp-14` 等）ごとの時刻帯（IANA 名・UTC オフセット）。唯一の置き場（Issue #32-3、ADR-0024）。`registry.sqlite` の `region` 表 → D1 → `generated-client.ts` の `REGION_TIME` → `lookup-client.ts` の `regionTimeZone()`。b03/b06 は `scripts/migrate/regions.py` で直接読む |
| `unit.yaml` | 単位29件。`unit_id` を各行が明示する（後述） |
| `variable.yaml` | 正準指標85件 |
| `variable_alias.csv` | 出典表記→正準 `variable_id` の対応154件（列は後述「`variable_alias.csv` の列」） |
| `source/license.yaml` | 出典のライセンス（ADR-0005、Issue #39 Phase C）。`source_registry.license` の自由記述71種の原文 → `license_id`/`license_class` の写像。`registry.sqlite` の `license` 表と `source_edition.license_*` の元（後述「出典・版・ライセンス」） |
| `source/editions.yaml` | 出典の版（`source_edition`）の宣言。土地利用の 2006/2016・置換（`gbif_kanagawa` → `gbif_kanagawa_occurrences`）・`update_mode`・`content_file`。過去の取得履歴は復元不能なので書かない（捏造しない） |
| `id_map/dataset.csv` | 旧 ID → 現行 ID の対応（dataset 分: 旧 `<dataset>@<年>` → 版の ID の 2 行。凍結リストとして `build_source.py` が variable_alias と突き合わせる） |
| `place/zone.yaml` | Ridge to Reef ゾーン(1-5)の操作的定義 |
| `place/site_supplement.csv` | `sites` テーブルに無い観測地点の補完（143件）。`place_local` 列は、
  `site_id` の局番コード部分（`"__"` の後ろ）が空文字で自動導出できない行にだけ
  明示の local を持たせる列（後述「空の局番コード」参照）。他の142行は空欄 |
| `taxon/vernacular_ja.csv` | 人手確認済みの和名63件（`domain.ts` の `NAME_JA` の複製54件＋Issue #48 PR-3b D4 で足した上書き9件。出典列は `issue48-pr3b:D4`） |
| `taxon/taxon_group.yaml` | 生物群の日本語ラベル（`taxon_group`）の先勝ちルール表。`web/scripts/build-biota.mjs` の `TAXON_GROUP` CASE式をデータ化したもの（Phase B `phase-b/occurrence-registry`、後述「taxon の分類補完」） |
| `caveat.yaml` | 注記18件（移設14件＋新規4件〔`landuseDefinitionChange`・`aboveLod`・`censoredLod`・`unitUnknown`〕、Issue #35 で `flowTidalBackflow` を足し `censored` 撤去。全件に `review`） |
| `caveat_scope.yaml` | 注記がどの範囲に掛かるかの宣言（Issue #35。上の語彙の節） |

**生成物はここには置かない。** `data/db/registry.sqlite`（gitignore 済み）が唯一の生成物で、
`scripts/r01_build_registry.py` が上記の手書きファイルと、読み取り専用の原本
（`data/db/ryuiki.sqlite` / `cells.sqlite`）、および読み取り専用の配布物
（`data/processed/nlni_w12_watersheds.jsonl`・`taxon_crosswalk.csv`）から毎回ゼロから
作り直す。`derived.sqlite`（`pnpm run build:derived` の成果物）は**読まない**——
Phase B `phase-b/place-attributes`（P-1a）で watershed の入力を
`nlni_w12_watersheds.jsonl` の直読みに切り替え、registry ビルドが `derived.sqlite`
を読む箇所が無くなった（後述「watershed の入力」）。`registry.sqlite` の中身に対して
「これが正しい」という判断はしない。正は常にこのディレクトリと原本側。ADR-0001 の
「D1 はいつ捨てて作り直してもよい」がレジストリにも適用される。

## 再構築の手順

```bash
pip install -r requirements.txt          # PyYAML のみ（レジストリビルド専用の依存。ホストの .venv 向け）
cd web
pnpm run build:registry                  # data/db/registry.sqlite を作る
                                          # （scripts/run-python.sh が .venv/bin/python3 があれば
                                          #  それを、無ければ python3 を使う。$RYUIKI_PYTHON で明示も可）
pnpm run db:setup                        # migrate + seed。registry.sqlite も4本目のソースとして乗る
                                          # （registry.sqlite が無ければ predb:setup フックが
                                          #  build:registry を先に走らせるので、上の行は省略してもよい）
```

コンテナ（`docker compose up`）では `web/Dockerfile` が apt の `python3-yaml` を入れているので
`pip install` は不要。`docker-entrypoint.sh` が起動時に `registry.sqlite` が新鮮か
（後述「ビルドの指紋と `--check-fresh`」）を見て、古ければ同じ `build:registry` を走らせる
（`web/scripts/ensure-registry.sh`）。

`r01_build_registry.py` は原本（ryuiki / cells）を読み取り専用で開き、一切書き換えない
（`derived.sqlite` は開かない——上記参照）。実行時間は実測で約39秒（10テーブル・
53,178行。大半は taxon ステップの分類多数決集計。内訳は
`docs/plans/PHASE_B_OCCURRENCE.md` 参照）。2回連続で実行しても
`registry.sqlite` の中身（テーブルごとの行数・全行を安定な順序で並べたハッシュ）は同一になる
（決定論的な再生成）。書き込みは同じディレクトリの一時ファイル（`registry.sqlite.tmp-<pid>`）に
行い、全ステップとチェックが通ってから `os.replace()` で正規パスへ原子的に置き換える。途中で
例外が出ても一時ファイルを消すだけで正規の `registry.sqlite` には一切触れない（phase-b/registry-atomic。
以前は先に既存ファイルを消してから作り直しており、ビルドやチェックの失敗で壊れた/半端なファイルが
正規のパスに残る事故があった。`create_registry_db()` 自体の失敗も含めて後始末する）。
起動のたびに、同じ正規パスに残った「十分古い」（既定1時間より前）一時ファイルもまとめて掃除する
（SIGKILL/OOM 等で例外ハンドラも通らず残ったものが対象。ファイル名の PID の生死では判定しない
——docker とホストは PID 名前空間が別で無意味なため。mtime だけを見る）。

### ビルドの指紋と `--check-fresh`

`registry_build(input_fingerprint, mode)` という1行だけのメタ表を持つ。`input_fingerprint` は
ビルドの最初のステップより**前**に1回だけ計算し（ビルド中に `registry/` 配下を編集しても、
記録される指紋がビルドの実際の入力からズレないようにするため）、`scripts/registry/common.py` の
`compute_input_fingerprint()` が計算する。対象は次の3種類:

1. ビルドの論理（`scripts/schema_registry.sql` / `scripts/r01_build_registry.py` /
   `scripts/taxon_namespaces.py` / `scripts/registry/*.py`）と手書きの入力
   （`registry/` 配下の全ファイル）。`mode` に関わらず対象。
2. **`mode='full'` のときだけ**、追加で3つ: build_place.py の watershed 節が読む
   `data/processed/nlni_w12_watersheds.jsonl`（L1、`common.WATERSHED_JSONL_RELPATH`）
   の中身、build_taxon.py が読む `data/processed/taxon_crosswalk.csv` の中身、
   そして **`ryuiki.organism_records` の軽い代理指標（行数・最大rowid）**
   （grid01 の入力が `derived.mesh_all` から `organism_records` に変わったことで、
   鮮度検知の経路が一つ抜けたのを塞ぐため。Phase B `phase-b/occurrence-registry`）。
   3つとも「読み取り専用だが再生成・追記すれば値が変わりうる」入力で、以前は
   指紋の対象外だったため、これらだけを更新してもレジストリが「新鮮」のまま
   固まってしまっていた。`--files-only` はどれも開かない（build_place.py/
   build_taxon.py 自体を呼ばないため。CI に原本が無くても動く要件を保つ）。
   `full` モードでこれらのファイルが無い場合はクラッシュせず「無い」ことを
   指紋に混ぜる——以前の指紋（中身がある状態で計算済み）とは必ず食い違うので
   「古い」と判定され、実際のビルドに進んで分かりやすいエラーで止まる。

   **`derived.sqlite` は `mode` に関わらず指紋計算が一切開かない。** 以前は
   build_place.py の watershed 節が `derived.watershed_meta`（v1 の派生表）を
   読んでいたため、`common.DERIVED_TABLES_READ`/`_hash_derived_tables()` という
   専用の仕組みでその中身を指紋に混ぜていたが、Phase B `phase-b/place-attributes`
   （P-1a）で watershed の入力を上記 JSONL の直読みに切り替えたことで
   registry ビルドが `derived.sqlite` を読む箇所自体が無くなり、この仕組みは
   削除した。**full ビルドに `derived.sqlite`（`pnpm run build:derived` の成果物）
   はもう要らない**（`common.open_sources()` が既定で開くのも `ryuiki`/`cells` の
   2つだけになった。`scripts/registry/common.py` の `SOURCE_NAMES`/
   `DEFAULT_SOURCES` 参照）。

**`ryuiki.sqlite` / `cells.sqlite` の内容全体は `mode` に関わらず指紋に含めない**
（`organism_records` の行数・最大rowidだけは例外。前段落参照）。理由は
`scripts/registry/common.py` の `compute_input_fingerprint()` docstring 参照（正はそちら1箇所）。
**`m0x_*.py` で原本（ryuiki/cells）を書き換えたら、`cd web && pnpm run build:registry` を
明示的に走らせること**（`ensure-registry.sh` は行数・最大rowidが変わらない書き換え
——例: license 列のバックフィル再実行のような UPDATE——を検知できないため）。

`mode` は `full`（通常ビルド）/`files_only`（`--files-only`）。実行時刻は持たない（決定論）。

`scripts/r01_build_registry.py --check-fresh` は登録先には何も書かない。`cells` は一切
開かない。`ryuiki` は `mode='full'` のときだけ `organism_records` の行数・最大rowid
（実測で合計約5ms）を読むために一瞬だけ開く（`mode='files_only'` のときは開かない）。
**PyYAML を import しない**（実際にビルドする4モジュールのうち3つが registry/*.yaml
を読むために PyYAML に依存するが、`--check-fresh` はそれらを import せずに完結する）。
終了コードは `EXIT_FRESH`=0 / `EXIT_STALE`=10 / それ以外=判定できない、の3種類。それぞれの
意味と、「判定できない」を「古い」と誤読してはいけない理由は `scripts/r01_build_registry.py`
のモジュール docstring 参照（正はそちら1箇所）。

`web/scripts/ensure-registry.sh` はこの終了コードで3分岐する: `0` なら作り直さない、`10` なら
作り直す、それ以外は「判定できない」として——レジストリが在るなら警告を出して今のファイルを
使い続け（以前の挙動への退避）、無ければ作る。ファイルの有無だけでは、ビルドの論理が変わった後の
古いレジストリや、途中で壊れた半端なファイルを見分けられないため
（`docs/plans/PHASE_B_INTAKE.md` #7 の追記「`--files-only` が正規のレジストリを154 aliasの
スタブで上書きした事故」と同根の問題への対応）。

## テーブルとID規約（ADR-0004 の Phase A での具体形）

10テーブル：`unit` / `variable` / `variable_alias` / `place` / `place_source_ref` /
`place_relation` / `place_watershed` / `taxon` / `caveat` / `caveat_scope`。DDL は
`scripts/schema_registry.sql`（= `web/src/db/schema-registry.ts` の drizzle 定義から生成。
ただし `place_relation`/`place_watershed` はまだ drizzle 側に無い。後述
「`place.region_id` と `place_relation`」「kind 固有の属性サテライト」参照）。

計画時点（PHASE_A.md §A-1）は `caveat` 単体7テーブル構成だったが、実装時に「1つの注記が
複数テーブルに掛かる」ことが分かり、スコープを `caveat_scope` に切り出して8テーブルにした
（1:N を表現するため。詳細は `scripts/registry/build_caveat.py` のdocstring）。Phase B
（`phase-b/region-scope`, ADR-0022）で `place_relation` を新設し9テーブルに、
Phase B `phase-b/place-attributes`（P-1a）で `place_watershed` を新設し10テーブルに
なった。

| entity | ID の形 | 例 |
|---|---|---|
| unit | `common:unit:<slug>` | `common:unit:mg_per_l` |
| variable | `common:variable:<theme>.<name>` | `common:variable:water.bod` |
| place（namespace あり） | `<scope>:place:<kind>.<namespace>-<local>` | `jp-14:place:site.env-pubwater-0142` |
| place（namespace 無し） | `<scope>:place:<kind>.<local>` | `common:place:grid01.3500_13900`（後述） |
| taxon（GBIF由来） | `common:taxon:gbif.<GBIFのtaxonKey>` | `common:taxon:gbif.2480932` |
| taxon（iNaturalist由来） | `common:taxon:inat.<iNatのtaxon.id>` | `common:taxon:inat.12345`（GBIFのtaxonKeyとは無関係な別の数値空間。Phase B `phase-b/occurrence-registry`、後述「taxon の名前空間分割」） |
| taxon（taxa由来・GBIF未照合） | `common:taxon:ryuiki-taxa.<slug(taxa.taxon_id)>` | 元の `taxa` 由来の識別子を後述のスラッグ化を通したもの |
| caveat | `common:caveat:<key>` | `common:caveat:censored` |
| caveat（cells.notes由来） | `common:caveat:cells.<note_id\|rowid>` | `common:caveat:cells.42` |

`scope` の既定は `common`（レジストリと県境をまたぐ実体）。地域固有と分かっているものだけ
`region_id`（例 `jp-14`）をスコープにする（ADR-0004 規約0）。`place_source_ref` が
v1 側の識別子（`sites.site_id` / `watershed_meta.watershed_id` / `mlat,mlon` / `sites.zone`）
から `place_id` を引く接続点で、「v1 を動かさずに並走させる」を成立させている。

ビルドの最後に `unit_id` / `variable_id` / `place_id` / `taxon_id` / `caveat_id` の一意性を
assert する（`scripts/r01_build_registry.py` の `_assert_id_uniqueness`）。SQLite の
PRIMARY KEY 制約により挿入時点でも保証されるが、4モジュールが同じ DB に同居する統合作業の
受け入れ基準として明示的に確認している。

### `caveat_scope.scope_kind` の語彙（Issue #35 で ADR-0013 の6種に寄せた）

`caveat_scope` は「どの範囲に注記が掛かるか」を `(scope_kind, scope_ref)` の組で持つ
（1注記:Nスコープ）。**宣言の正は `registry/caveat_scope.yaml`**（以前は `build_caveat.py` の
Python 定数）。`build_caveat.py` はそれを読んで検査し書くだけ。優先度は `priority` 列が持つ。

| scope_kind | scope_ref | 例 |
|---|---|---|
| `dataset` | 論理データセット名・配信表名 | `measurements` / `organism_records` / `sites` |
| `place` | `place_kind=<種別>` | `place_kind=site` / `zone` / `grid01` |
| `variable` | `variable_id`、または `theme=<theme>` | `common:variable:hydro.flow`（逆流）、`theme=landuse` |
| `source_edition` | `source_id=<出典ID>`、`doc_id=<文書ID>`（cells.notes） | `source_id=moe_ias_list` |
| `observation_set` | `キー=値`（`&` 連結） | `is_synthetic=1`、`variable=<id>&unit_id=null`（unitUnknown）、`doc_table=<doc>#<table>`（cells.notes） |
| `taxon` | `taxon_id`（まだ使っていない） | — |

scope_ref の照合は文字列の完全一致で、選択式は解釈しない（`web/src/lib/cube/caveats.ts` の
ヘルパが宣言と同じ文字列を作る）。選択式のキーは `caveat_scope.yaml` の `selectors` が kind ごとに許す
ものだけで、ビルド時に検査する。**v1 の `table`/`table_prefix`/`place_kind`/`source_id`/
`variable_theme`/`cell`/`cell_table` は廃止**（旧→新の対応は `scripts/registry/build_caveat.py` の
docstring と `docs/adr/0013-caveats.md` の追記）。意図して範囲に付けない注記は `unscoped` に宣言する
（`fishClass`/`inatBackfill`: 画面が直接引く）。語彙は `web/scripts/build-registry-ts.mjs` が
`caveat_scope.yaml` の `vocabulary` から読み、`CaveatScopeKind` 型も同じ配列から作る。

全注記に人のレビュー記録（`registry/caveat.yaml` の `review`）が要る。判定基準は
`docs/adr/0013-caveats.md`「severity/kind の判定基準」。

### `place.region_id` と `place_relation`（Phase B `phase-b/region-scope`。理由・経緯は ADR-0022 参照）

`place.region_id` は `place_id` のスコープと一致させる: `common` なら `region_id=NULL`、
それ以外（例 `jp-14`）なら `region_id=<scope>` そのもの。`scripts/registry/common.py` の
`region_id_for_scoped_id()` が発行済みの `place_id` から導出し、
`scripts/r01_build_registry.py` の `_assert_region_id_scope_invariant` がビルドのたびに
検証する。実測: `common -> NULL` 4,460件（grid01 4,083 + watershed 377）、
`jp-14 -> jp-14` 500件（site 495 + zone 5）。

「所在」は `region_id` 列ではなく `place_relation` の辺で表す。Phase B で作った辺は
2種類。地点→ゾーン（290件 = `sites.zone IS NOT NULL` の地点数）:

```
place_relation(parent_id=ゾーンのplace_id, child_id=地点のplace_id,
                relation='within', fraction=1.0, basis=<zone.yamlの定義を指す文字列>)
```

地点→流域（278件 = `sites.watershed IS NOT NULL` の地点数。Phase B
`phase-b/place-attributes`、P-1a）:

```
place_relation(parent_id=流域のplace_id, child_id=地点のplace_id,
                relation='within', fraction=1.0,
                basis=<m01_sites.py の点内包判定を指す文字列>)
```

`sites.watershed` は `sites.zone` と違い申告値ではなく、`scripts/m01_sites.py:110-128`
が `nlni_w12_watersheds.geojson` への点内包判定（shapely）で機械的に決定した値。

どちらも `fraction` は NOT NULL・常に `1.0`。`(parent_id, child_id, relation)` の
一意性は DDL の `UNIQUE` 制約ではなく r01 の `ID_UNIQUENESS_CHECKS`（Python 表明）で
検証する（`ID_REFERENCE_CHECKS` に `place_relation.parent_id`/`child_id` ->
`place.place_id` もある）。「地点はゾーン・流域それぞれへの `within` 辺を高々1本」も
r01 が機械検証する（`RELATION_SINGLE_VALUED_CHECKS`（宣言）から
`_assert_relation_child_is_single_valued()`（共通実装）を回す）。`source_edition_id`
（ADR-0006 が挙げる列）はまだ持たない。

`place_relation` はまだ `web/src/db/schema-registry.ts`（D1）に無い。地域・ゾーン単位の
ロールアップ集計のような消費者がまだ無いため、載せる判断を先送りしている
（ADR-0001: D1 は捨てて作り直せる配信キャッシュ）。`web/scripts/seed-d1-local.mjs` は
D1 側に既に存在するテーブルだけをシードするので、この先送りはローカル D1 のシードを
壊さない。

### kind 固有の属性サテライト: `place_watershed`（Phase B `phase-b/place-attributes`、P-1a）

ADR-0006「place の属性」（ADR-0011 の `place_attribute` カテゴリの具体形）の実装。
`place` 本体には kind をまたいで共通する列（`name_ja`/`lat`/`lon`/`area_km2`/
`definition_ref`）だけを置き、kind 固有の属性は `place_<kind>` という別表に置く。
最初の例が `place_watershed(place_id PK, water_system_code, water_system_category,
main_rivers, data_year)`。`place_kind='watershed'` の place（377件）に対して
`build_place.py` がちょうど1行ずつ作る（r01 の `_assert_watershed_place_has_attributes_and_source_ref`
が機械検証する）。`place_relation`/`place_watershed` とも D1 にはまだ載せない
（同じ理由）。却下案（親 place＋`place_relation` にする）の理由は ADR-0006 の
追記を正とする。

### watershed の入力（Phase B `phase-b/place-attributes`、P-1a）

`build_place.py` の watershed 節は `data/processed/nlni_w12_watersheds.jsonl`
（L1、国土数値情報 W12 流域界 1977年版、377面）を直読みする。以前は
`derived.watershed_meta`（v1 の派生表、`web/scripts/build-geo.mjs` が同じ JSONL
から作る）を読んでいたが、これは「v1 の出力から registry を作り、v1 に射影し直す
だけ」の循環になっていた——grid01 が `derived.mesh_all` を経由していた問題
（後述「grid01 の入力を `derived.mesh_all` から `organism_records` の座標に変える」
節）と同型。切り替えても
`place`/`place_source_ref` の watershed 行は1ビットも変わらない（実測: 切り替え前後で
377行×9列の diff 0件、正準化 sha256 も完全一致。詳細は
`docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`）。

### `variable_alias.csv` の列（Phase B: 出典 × 表記で解決する）

ADR-0010 決定1「エイリアスは出典 × 表記で解決する」に沿って、Phase B で列を作り直した
（`docs/plans/PHASE_B_INTAKE.md` #1）。117行（`(alias, source_scope)` 単位）から
154行（`(alias, dataset, source_id)` 単位）になっている。

| 列 | 意味 |
|---|---|
| `alias` | v1 の生の表記（`measurements.variable` / `sensor_timeseries.datastream`） |
| `dataset` | v1 のどのテーブルの表記か（`measurements` / `sensor_timeseries`。土地利用は出典名 `nlni_l03b_landuse_by_watershed` そのもの）。以前の `source_scope` を改名した。「出典スコープ」を名乗りながらテーブル名を持っていたのが Phase A の実装のズレだったので、実態に合わせて改名した。**`@<年>` の後置は廃止した**（Issue #39 Phase C。版は次の `edition_key`） |
| `source_id` | v1 `source_registry.source_id`。空 = 出典未記録（`measurements.source_id IS NULL` の行。全件 `is_synthetic=1`） |
| `variable_id` / `unit_id` | 従来どおり。同じ `(dataset, alias)` を共有する行は必ず一致する（ビルド時表明。後述） |
| `stat` / `grain` | 従来どおり。`(dataset, alias, source_id)` の組ごとに固定1値（一次資料調査済み。`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md`） |
| `unit_basis` | `unit_id` の根拠（Issue #31）。`source`=原本が同じ単位を報告している／`registry`=原本に単位の記載が無くレジストリが補った。`unit_id` が空の行は空。実データとの一致は b04 の `_assert_unit_basis_evidence` が機械検証する（食い違えば止まる） |
| `edition_key` | 出典が版を持つときの版（土地利用 2006/2016。46行〔2006:22・2016:24〕だけが値を持つ）。空 = 全 edition 共通。`(source_id, edition_key)` が `source/editions.yaml` の `declared_editions` に在ることをビルドが検査し、`registry.sqlite` では `source_edition_id`（`common:edition:<source_id>.<edition_key>`）に展開して持つ（`--files-only` でも同じ検査が効く） |
| `note` | 従来どおり。根拠となる一次資料は `docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` の該当節を参照する形で書く（154行全部にURLを書けないため） |

`source_id` は bare のまま変えない（cube・D1 も bare。ADR-0005 改定）。ADR-0010 決定1が言う
`source_edition_id` は、版を持つ出典だけ `edition_key` → `source_edition_id` として持つ
（以前の暫定形 `dataset` の `@<年>` 後置は Issue #39 Phase C で解消した）。

**ビルド時の表明**（`scripts/registry/build_unit_variable.py`。原本 DB は開かない）:

1. `(dataset, alias, source_id, edition_key)` が一意（`source_id`・`edition_key` が空の行も
   Python 側で明示的に比較する。SQLite の「NULL は互いに異なる」に頼らない）。
2. 同じ `(dataset, alias, edition_key)` を共有する行は `variable_id` と `unit_id` が一致する
   （`resolveVariableInfo()` が「どの `source_id` の行を引いたか」に関わらず同じ結果を
   返すための根拠）。
3. `grain` は `{hour, day, month, year, fiscal_year}`、`stat` は実際に使われている値の
   集合（`point, mean, min, max, sum, p75, p90, max_10min, max_1h, max_daily,
   mean_of_daily_min, mean_of_daily_max` と空）のコードリストに入っていること。

「CSV の154組が v1 の実データの組と過不足なく一致するか」は `build_unit_variable.py` の
責務ではない（原本 DB を開かないため）。`scripts/r02_resolution_report.py`（原本を読める側）
が突合し、`reports/registry_resolution.md` §8 と `reports/registry_resolution/
alias_source_pairs_{csv,data}_only.csv` に片方向ずつのズレを出す（0件が現状）。

**`unit_id` の埋め方（D3、Issue #48 PR-1b）**: `dataset='measurements'` の alias で
`unit_id` が空だった39行のうち38行は、原本 `measurements.unit`（unit_raw）を実測し、
`(alias, source_id)` ごとに一貫した単位文字列がレジストリの `unit.symbol` と完全一致する
ことを確認したうえで埋めた（推測でフォールバックしていない）。残り1行（流量、alias
"流量関連（公式定義未確認のため原表記のまま）"）は原本にも単位が無いため NULL のまま。
この不変条件（`unit_id` が埋まっている行は `unit_raw` と `symbol` が一致・埋まっていない
行の一覧）は `scripts/b04_build_cube.py` の `_assert_unit_evidence()` が
`data/db/v2.sqlite` の `observation`（`unit_raw` を持つ唯一の段）に対して機械的に検証する
（`sensor_timeseries` は表記ゆれ（例: raw "μg/m3" vs symbol "ug/m3"）という別の既知の
問題を抱えており対象外。宣言は `scripts/migrate/unit_evidence_declarations.yaml`）。

**`unitUnknown` 注記（Issue #48 PR-2）**: `dataset` を問わず `unit_id` が空のまま残る
全行（測定10行: 流量関連1・sensor 9〔RAIN 含む〕）から、`scripts/registry/build_caveat.py`
の `_unit_unknown_variable_refs()` が `variable_id` を機械導出し（8件に畳まれる）、
`caveat_scope` に `scope_kind='variable'` の行として付ける（上記「`caveat_scope.scope_kind`
の語彙」参照）。ハードコードしないので、`variable_alias.csv` の `unit_id` を今後埋めれば
このリストも自動的に縮む。

### 出典・版・ライセンス（`license` / `source` / `source_edition`。Issue #39 Phase C、ADR-0005）

`scripts/registry/build_source.py` が `ryuiki.sqlite` の `source_registry`（124行）と
`source/license.yaml`・`source/editions.yaml` から作る（`--files-only` では作らない。原本を開くため）。

- **`source`**: `source_registry` 1行 = 1行。`source_id` は bare のまま（`[a-z0-9_]+`。公開 ID は
  `common:source:<source_id>` で全単射。`common.source_public_id()`/`source_local_id()`）。
  `superseded_by` は置換先の source_id（`gbif_kanagawa` → `gbif_kanagawa_occurrences` の1件）。
- **`source_edition`**: 124 source に 125 edition。宣言の無い source は取得日 `YYYYMMDD` の edition を1つ
  自動で作り、土地利用の流域別集計だけは宣言した 2006/2016（出典自身の版 = vintage）を持つ。
  `edition_id` = `common:edition:<source_id>.<edition_key>`。**過去の取得履歴は復元不能なので作らない。**
  `redistributable`/`license_class`/`commercial_ok` は出典の旗として列に残すだけで、出力を絞る根拠にしない
  （`embargo_reason` は作らない。ADR-0005 改定）。原文は `license_raw`。
- **`license`**: 17件。`license_class` は public_domain / cc_by / share_alike / open_terms / noncommercial /
  custom_terms / restricted / mixed / unconfirmed / unknown（`license.yaml` が正）。写像漏れは `unknown` に
  落としてビルド出力に原文を出す（止めない）。実データでは 0 件であることをテストが見る。
- ファクト側の `source_edition_id` は `scripts/migrate/edition.py` の `resolve_edition()` 1関数で引く（L2 のみ。
  キューブ・D1 summary は bare の `source_id`）。
- 検査（壊すと止まる）: `scripts/tests/test_registry_source.py`。

### `local_key` のスラッグ化（ADR-0004 規約4）

レビューで、ID に空白（`taxon_id` 5,685件）・コロン（`local_key` 内に221件。
`<scope>:<entity>:<local_key>` の3分割が曖昧になる）・非ASCII文字（`place_id` 7件。
例: `jp-14:place:site.atsugi-river-中津川`）がそのまま入っていることが指摘された
（ADR-0004 規約4「公開 ID は URI に解決できる形にする」に反する）。

`scripts/registry/common.py` の `slugify_local_key()` に1箇所で実装し、
`place_id()` / `taxon_id_unresolved()` の `local` 部分がここを必ず通る:

- 空白列 → `_`
- `:` → `.`（`local_key` 内の `:` が3分割を曖昧にするのを防ぐ）
- `/` → `_`
- 連続する `_`/`.` は1文字に畳み、前後の `_`/`.` は落とす
- それでも残る非ASCII文字・URI的に安全でない記号は UTF-8 バイト列を percent-encode
  する（`abelia chinensis var. ionandra` → `abelia_chinensis_var._ionandra`、
  `atsugi_river_water_quality__中津川` の `中津川` → `%E4%B8%AD%E6%B4%A5%E5%B7%9D`
  のように）。**元の文字列は捨てない** — 実際には `taxon.scientific_name` /
  `taxon.vernacular_name_ja` / `place.name_ja` / `place_source_ref.external_key`
  のいずれかに元の生の文字列がそのまま残っている（実測で全件確認済み。
  percent-encode 後の ID は識別子としてのみ使い、人が読む名前はこれらの列を見る）。
- 別々の元キーが同じ slug に潰れた場合は例外を投げる（`seen` 引数。
  `place_id()` は `place_kind`・`namespace` の組ごとに、`taxon_id_unresolved()` は
  taxon 全体で1つの名前空間として衝突を見る）。実測ではこの経路での衝突は無かった
  （`gbif_taxon_key` の重複による衝突1件は方針2の EXACT 限定と無関係な既知の事象で、
  `build_taxon.py` のモジュール docstring 参照）。

### 逸脱: `place_kind='grid01'`（ADR-0006 のコードリストからの逸脱）

`mesh_all`（4,083件）は `mlat`/`mlon` が1刻み（= 0.01度刻み）で、国土地理院の
標準地域メッシュ（3次メッシュ。緯度30秒×経度45秒）とは刻み幅が違う独自グリッド
であることを実測で確認した。当初 `place_kind='mesh3'` としていたのを ADR-0006 の
コードリストの語（標準地域メッシュを指す）と混同しないよう `grid01` に改め、ID も
`common:place:mesh3.grid01-<mlat>_<mlon>` から `common:place:grid01.<mlat>_<mlon>`
に変えた（`place_id()` に `namespace=None` を渡すと `<namespace>-` を省ける形を
追加した）。`place_source_ref.external_key` も `mesh3:{mlat},{mlon}` から
`grid01:{mlat},{mlon}` に変更した。

これは ADR-0006 のコードリスト（`site`/`watershed`/`mesh3`/`municipality`/…）に
`grid01` という値を追加する逸脱であり、ADR 本体は編集していない。**Phase B 以降で
ADR-0006 のコードリストに `grid01` を正式に追記するか、将来別地域が本物の3次
メッシュを登録する時点で `mesh3` と `grid01` を明確に書き分けるかを判断する**
申し送りとする。

### grid01 の入力を `derived.mesh_all` から `organism_records` の座標に変える
（Phase B `phase-b/occurrence-registry`。docs/plans/PHASE_B_OCCURRENCE.md §2-3）

`derived.mesh_all` は年フィルタ済みの `mesh_year`（`yr BETWEEN 1970 AND 2026`）を畳んだ
ものなので、年フィルタで弾かれた記録しか持たないセルが grid01 から欠落していた
（1970年より前の記録しか無い3セル、日付の無い記録しか無い1セル。計4セル）。
`build_place.py` の grid01 節を `ryuiki.organism_records` の座標（`FLOOR(lat*100)`/
`FLOOR(lon*100)`）から直接作るように変えた。**日付の無い記録の座標も含める**
（座標は823,692行全件に入っており、日付の有無と独立。ADR-0007 原則1が occurrence に
求める「日付の無い記録も保持する」に、grid01 側もあらかじめ整合させる判断）。
実測: 4,083セル → **4,087セル**。`place_source_ref.source_id` も
`mesh_all.mlat_mlon` から `organism_records.lat_lon` に変わった（`external_key` の形
`grid01:{mlat},{mlon}` は変えない）。これに伴い、ビルドの指紋（後述）から
`derived.mesh_all` を読む記述を外した（`ryuiki.sqlite` はもともと指紋の対象外なので、
指紋計算の対象は増えていない）。

taxon の分類多数決（後述）は逆に v1 と同じ「日付ありの記録だけ」を母集団にしたまま
温存している——grid01（場所の集計単位の完全性）と taxon の分類（v1 の値を変えない）は
別の設計判断で、根拠も別々。

## taxon の名前空間分割と分類補完（Phase B `phase-b/occurrence-registry`）

**決定と理由の正は `docs/adr/0019-taxon-registry.md` の日付付き追記、実測の正は
`docs/plans/PHASE_B_OCCURRENCE.md`。ここには実装の要点だけを書く。**

**F1（taxon_id の名前空間分割）**: `organism_records.taxon_key` は出典によって
別の数値空間（GBIF の `taxonKey` / iNaturalist 自身の `taxon.id`）が入っている。
以前はどちらも `common:taxon:gbif.<key>` に通しており、偶然同じ数値を発行した
9件が衝突していた（例: `8026` = GBIF 科 *Axiidae* / iNat *Corvus macrorhynchos*）。
`organism_records.source_id` から名前空間を引く対応は `scripts/taxon_namespaces.py`
の `TAXON_KEY_SOURCE_NAMESPACE`（正。`scripts/x01_dwca.py` 等レジストリを経由しない
読み手にも届くように、`scripts/registry/build_taxon.py` の private 定数ではなく
ここに置く。当初は `scripts/common.py`——収集系の共有モジュール——に置いたが、
`requests` に依存するため CI で `ModuleNotFoundError` を起こし、依存の無い
モジュールに切り出し直した）。GBIF 由来は `common:taxon:gbif.<key>`、iNaturalist 由来は
`common:taxon:inat.<id>` に分ける。`gbif_taxon_key` 列は本物の GBIF taxonKey の
ときだけ埋める。**ADR-0004「ID は不変」の例外**（occurrence ファクトが
`taxon_id` を参照する前の今だけ安全にできる）であることの確認（呼び出し元grep等）は
ADR-0019 参照。実測: gbif 21,234件 / inat 13,978件。

**F2（kingdom/phylum/class/order/family/taxon_group）**: v1（`org_norm`）が
記録ごとに行っていた分類補完を taxon 単位でレジストリのビルダーに移した。
`classification_basis`（`source`/`binomial_match`/`genus_match`/`no_match`。
`no_match` は旧名 `unresolved`——`taxon.status='unresolved'` と紛らわしいため
改名）は `class` の解決経路。`order`/`family` は多数決で補完しない。
`taxon_group` は `registry/taxon/taxon_group.yaml` から生成する。

**これらの列は `registry.sqlite` だけにあり、D1（`schema-registry.ts`）には
載せていない**（オーナー決定。`place_relation` と同じ判断——ADR-0001。
`status='needs_review'` は既存の `status` 列にそのまま乗るので D1 側の
スキーマ変更は不要）。

**同数・不確かさの扱い**: 多数決の母集団は v1 と同じ「`observed_on` がある記録」
（v1 の値を変えないため）。同数は件数降順→値の昇順で決定論的に解決する。
属単位の多数決が同数、または**属自体が複数の class にまたがる**（同数でなくても
信頼性が低い。実測26属）場合、その taxon を `status='needs_review'` にする
（`accepted`/`unresolved` どちらの行にも起こりうる——backbone未照合と分類の
不確かさは別軸の事実なので、より新しい判定を優先する）。実測件数は
`docs/plans/PHASE_B_OCCURRENCE.md` 参照。

**検証**: `org_norm`（816,856行）との record 単位の突き合わせで `cls`/`kdm`/`phy`/
`taxon_group` の**不一致1件**（属の多数決が同数だった *Sirosporium celtidis*。
`taxon_group` は「菌類」で変わらない）。残り775行は `taxon_key` 自体が無く
元々 `taxon_id` 解決の対象外。

## `taxon.vernacular_name_en`・和名の記録由来補完（D4）（Issue #48 PR-3a）

`vernacular_name_en` は `organism_records.vernacular_name`（iNat 行は iNat API の
英語 common name、GBIF 行はデータセット付属の俗名——大半が日本語だが一部
ラテン文字）のうち **ラテン文字だけの値**を (名前空間, taxon_key) ごとに
最頻値（同数は値の昇順）で選んだもの（`scripts/registry/build_taxon.py` の
`_load_vernacular_candidates()`/`_pick_majority()`）。母集団は F1 の代表選び
（`_load_occurrence_representatives()`）と同じ（`taxon_key IS NOT NULL AND
taxon_key<>''`、日付の有無を問わない）。gbif/inat 名前空間の行にだけ付く
（`taxa` 由来の unresolved 行は organism_records に対応する taxon_key が無いため
常に NULL）。

**「英名」ではなく「ラテン文字の俗名」である**ことに注意——ラテン文字判定
（`scripts/registry/common.py` の `is_latin_script()`。ASCII 印字可能域 ∪
Latin-1 Supplement/Latin Extended-A・B の字母 ∪ 曲線引用符 `’`）は英語かどうかを
判定しないため、ローマ字表記（`Kawa-Semi`）・属の仮名（`Amara sp.`）も選ばれうる。

**和名の記録由来補完（D4）**: 同じ集計から非ラテン文字（ひらがな・カタカナ・CJK
等）の最頻値を、`vernacular_name_ja` が **NULL の行にだけ**埋める。根拠列
`vernacular_ja_basis`（`override`/`taxa`/`records`）で出処を残す。優先順は
override（`registry/taxon/vernacular_ja.csv` の人手確認済み63件）> taxa（`taxa`
由来）> records（この補完）——override は taxa 由来の値があっても無条件に
上書きする一方、records 補完は NULL の行にしか適用しないので、**既存の値は
1件も変えない**（実データ・pytest 双方でこの不変条件を確認する。
`scripts/tests/test_registry_taxon.py`）。

いずれも `registry.sqlite` の `taxon` テーブルと D1（`web/src/db/schema-registry.ts`）
の両方に載る（`taxon` は既に D1 の消費者があるため、`kingdom`/`phylum` 等とは
異なり D1 側にも追加した）。

## `taxon_assessment.in_scope`・`scope_reason`（Issue #34 で規則を出典の属性に切り替え）

除外集合は `assessment_scope_exclusions.yaml` の `rules:`（moe_ias_2015 の binom の掲載行がすべて `origin_ja` に
「国内由来」を含む。27 binom）と固定宣言 `exclusions:`（7種。Apis mellifera だけが規則外）の和集合（28）。
`in_scope=0` の行は `scope_reason`（`domestic_origin`/`subspecies_binomial_contraction`、重なれば `,` 連結）に理由を
残す。`n_alien` は `occurrence.is_alien_in_scope`（二名法が `in_scope=1` でリストに載るか）の合計（b06/b07。定義と件数は
`docs/adr/0019-taxon-registry.md` の Issue #34 追記）。`taxon.accepted_taxon_id` と弱い一致の採用は
`data/processed/taxon_gbif_accepted.csv`（`scripts/c26_taxon_gbif_accepted.py`）を読む。以下は PR-3a 時点の記述。

## `taxon_assessment.in_scope`（D7）（Issue #48 PR-3a）

`taxon_assessment.in_scope` は「除外7種」（上記「二名法(binom)は…」節、P-2
オーナー決定A）の宣言を、`taxon_assessment` 自体の行を1件も除外せずに可視化する
列。`(list_id, scientific_name_raw の二名法)` が
`registry/taxon/assessment_scope_exclusions.yaml` の (list_id, scientific_name)
と一致する行だけ `in_scope=0`、他の全行（redlist 3版を含む）は `in_scope=1`
（`scripts/registry/build_taxon_assessment.py` の `_assign_in_scope()`）。
二名法での一致規則は `scripts/b08_project_occurrence_v1.py` の
`_build_ias_species()` が `org_norm.binom` に対して行うのと同じ
（`binom_of()`）。`taxon_assessment` は Issue #48（PR-0）で既に D1
（`web/src/db/schema-registry.ts`）に載っている（`scripts/schema_registry.sql`
の同テーブルの先頭コメントは「D1には載せない」という古い記述のままだが、これは
PR-0 以前の状態を指しており実態と食い違っている——別途の訂正が必要）。

## `status='needs_review'` / `'unresolved'` が意味すること

**黙って埋めない・落とさないという契約**（`docs/COLLECTOR_CONTRACT.md`）。レジストリは
「分からない・決められない」ことをデータとして残すのであって、推測で埋めた値を正とはしない。

- `place.status='needs_review'`: 座標などが原本に無く、捏造せず `NULL` のまま登録した行
  （例: 収集スクリプト自身が緯度経度を持たない観測地点90件）。
- `taxon.status='needs_review'`: `place` とは別の意味（座標欠落ではなく分類の多数決が
  不確か）。詳細は上記「taxon の名前空間分割と分類補完」節参照。
- `taxon.status='unresolved'`: `taxa`（神奈川県RL等・和名中心）のうち、対応する
  GBIF の taxon 概念そのものとして扱えなかった6,242件（実測値。従来5,942件と
  報告していたが、レビュー指摘を受けて300件増えた）。内訳:
  - GBIF に `taxon_key` を持たない5,942件（内訳: 照会自体が未実施5,908件 /
    照会したが一致しなかった`gbif_match_type='NONE'` 34件）。
  - `gbif_taxon_key` はあるが `gbif_match_type` が `HIGHERRANK`/`FUZZY`
    （種以下まで一致していない弱い一致）の300件。**当初はこれらも
    `common:taxon:gbif.<key>` に寄せていたが、GBIF が種以下まで一致させられず
    属・科・時に kingdom まで遡った結果、同じキーに複数の無関係な種の
    `taxa` 行が衝突し（例: key=1 = Animalia に CR/EN の昆虫5種を含む10件が載る）、
    そのキーが `organism_records` に出現しない場合はレジストリ行の学名が
    たまたま代表に選ばれた taxa 側の種名になる（ID の実体は属・科・kingdom
    なのに名前は種）という事故が約200件で起きていた。ADR-0019決定4
    「`gbif_match_type` が弱いものは捨てずに `status='unresolved'` で保持する」
    に沿って、EXACT（種階級での一致）のときだけ寄せる方針に直した。**
  学名の語彙として存在はするが分類群として解決できていないことを示す。
- `variable`/`unit` 側で単位や粒度が決まらない場合も同様に `needs_review` を使う
  （ADR-0010）。

これらの件数が0になることをゴールにしない。**件数と一覧が可視化されていることがゴール**
（実測値は `scripts/registry/build_taxon.py` 等の各 `build()` が実行時に print する。
`reports/registry_resolution.md` として恒常的なレポートに出す仕事は A-6 で、本統合の
時点ではまだ実装していない）。

## レビューで見つかった細かい誤り（事実誤認）

- **`variable_alias.csv` の `pH` の `grain`**: `mean`/`fiscal_year` 系のエイリアス同様
  `day` としていたが、原本 `measurements` を数え直すと `pH` は4桁 `measured_on`
  （年度代表値。768行）と日付（採水個別値。34,165行）が同じ表記で混在していた。
  他のエイリアスの `grain` も原本の `measured_on`/`phenomenon_time` の書式分布と
  機械的に突き合わせて確認したが、不一致は `pH` のみだった（`measurements` 58種・
  `sensor_timeseries` 59種、計117エイリアス全件を確認）。`pH` を `mixed` に直した。
- **空の局番コードを `"unknown"` で埋めていた件**: `build_place.py` の
  `_site_place_id()` が `local or "unknown"` として `site.yokohama-waterlevel-unknown`
  という ID を機械的に作っていた。ID は不変（ADR-0004規約2）なのに、空文字を
  理由に自動生成した値がそのまま固定される捏造キーだった。`site_supplement.csv`
  の新設 `place_local` 列（該当する `yokohama_river_waterlevel__` の1行にだけ値を
  持たせた）で明示させ、`place_local` も無い場合は例外を投げるように直した
  （`docs/COLLECTOR_CONTRACT.md`「黙って埋めない」に沿う）。
