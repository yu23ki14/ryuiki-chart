# 語彙レジストリ（`registry/`）

Phase A（`docs/plans/PHASE_A.md`, ADR-0016）の成果物。v1 のファクト（`measurements` /
`organism_records` / `sensor_timeseries` 等）は一切書き換えず、`unit` / `variable` /
`place` / `taxon` / `caveat` という語彙だけを別枠で並走させたもの。

## このディレクトリの中身：手書き vs 生成物

**`registry/` 配下はすべて手書き（Git 管理・レビュー対象）。** ここには生成物は置かない。

| ファイル | 中身 |
|---|---|
| `unit.yaml` | 単位29件。`unit_id` を各行が明示する（後述） |
| `variable.yaml` | 正準指標85件 |
| `variable_alias.csv` | 出典表記→正準 `variable_id` の対応154件（列は後述「`variable_alias.csv` の列」） |
| `place/zone.yaml` | Ridge to Reef ゾーン(1-5)の操作的定義 |
| `place/site_supplement.csv` | `sites` テーブルに無い観測地点の補完（143件）。`place_local` 列は、
  `site_id` の局番コード部分（`"__"` の後ろ）が空文字で自動導出できない行にだけ
  明示の local を持たせる列（後述「空の局番コード」参照）。他の142行は空欄 |
| `taxon/vernacular_ja.csv` | 人手確認済みの和名54件（`domain.ts` の `NAME_JA` の複製） |
| `taxon/taxon_group.yaml` | 生物群の日本語ラベル（`taxon_group`）の先勝ちルール表。`web/scripts/build-biota.mjs` の `TAXON_GROUP` CASE式をデータ化したもの（Phase B `phase-b/occurrence-registry`、後述「taxon の分類補完」） |
| `caveat.yaml` | 注記14件（`domain.ts` の `DATA_CAVEATS`/`BIOTA_CAVEATS` 等の移設） |

**生成物はここには置かない。** `data/db/registry.sqlite`（gitignore 済み）が唯一の生成物で、
`scripts/r01_build_registry.py` が上記の手書きファイルと、読み取り専用の原本
（`data/db/ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite`）から毎回ゼロから作り直す。
`registry.sqlite` の中身に対して「これが正しい」という判断はしない。正は常にこのディレクトリと
原本側。ADR-0001 の「D1 はいつ捨てて作り直してもよい」がレジストリにも適用される。

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

`r01_build_registry.py` は原本3ファイル（ryuiki / cells / derived）を読み取り専用で開き、
一切書き換えない。実行時間は実測で約6秒（9テーブル・52,505行）。2回連続で実行しても
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
2. **`mode='full'` のときだけ**、追加で3つ: `derived.sqlite` のうち build_place.py が実際に
   読むテーブル（`common.DERIVED_TABLES_READ` = `watershed_meta`。ファイル全体
   449MB はハッシュせず、決まった順の SELECT 結果だけを混ぜる。`mesh_all` は
   Phase B `phase-b/occurrence-registry` で外した——grid01 の入力が `derived.mesh_all`
   から `ryuiki.organism_records` の座標に変わり、`build_place.py` がもう
   `derived.mesh_all` を読まなくなったため）、build_taxon.py が読む
   `data/processed/taxon_crosswalk.csv` の中身、そして **`ryuiki.organism_records`
   の軽い代理指標（行数・最大rowid）**（3つ目は同じ Phase B PR で追加。grid01 の入力が
   `derived.mesh_all` から `organism_records` に変わったことで、鮮度検知の経路
   （後述）が一つ抜けたのを塞ぐため）。3つとも「読み取り専用だが再生成・追記すれば
   値が変わりうる」入力で、以前は指紋の対象外だったため、これらだけを更新しても
   レジストリが「新鮮」のまま固まってしまっていた。`--files-only` はどれも開かない
   （build_place.py/build_taxon.py 自体を呼ばないため。CI に原本が無くても動く要件を保つ）。
   `full` モードで `derived.sqlite`/`ryuiki.sqlite` が無い場合はクラッシュせず
   「無い」ことを指紋に混ぜる——以前の指紋（中身がある状態で計算済み）とは必ず食い違うので
   「古い」と判定され、実際のビルドに進んで分かりやすいエラーで止まる。

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

9テーブル：`unit` / `variable` / `variable_alias` / `place` / `place_source_ref` /
`place_relation` / `taxon` / `caveat` / `caveat_scope`。DDL は `scripts/schema_registry.sql`
（= `web/src/db/schema-registry.ts` の drizzle 定義から生成。ただし `place_relation` は
まだ drizzle 側に無い。後述「`place.region_id` と `place_relation`」参照）。

計画時点（PHASE_A.md §A-1）は `caveat` 単体7テーブル構成だったが、実装時に「1つの注記が
複数テーブルに掛かる」ことが分かり、スコープを `caveat_scope` に切り出して8テーブルにした
（1:N を表現するため。詳細は `scripts/registry/build_caveat.py` のdocstring）。Phase B
（`phase-b/region-scope`, ADR-0022）で `place_relation` を新設し9テーブルになった。

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

### `place.region_id` と `place_relation`（Phase B `phase-b/region-scope`。理由・経緯は ADR-0022 参照）

`place.region_id` は `place_id` のスコープと一致させる: `common` なら `region_id=NULL`、
それ以外（例 `jp-14`）なら `region_id=<scope>` そのもの。`scripts/registry/common.py` の
`region_id_for_scoped_id()` が発行済みの `place_id` から導出し、
`scripts/r01_build_registry.py` の `_assert_region_id_scope_invariant` がビルドのたびに
検証する。実測: `common -> NULL` 4,460件（grid01 4,083 + watershed 377）、
`jp-14 -> jp-14` 500件（site 495 + zone 5）。

「所在」は `region_id` 列ではなく `place_relation` の辺で表す。Phase B で作った最初の
辺は地点→ゾーンだけ（290件 = `sites.zone IS NOT NULL` の地点数）:

```
place_relation(parent_id=ゾーンのplace_id, child_id=地点のplace_id,
                relation='within', fraction=1.0, basis=<zone.yamlの定義を指す文字列>)
```

`fraction` は NOT NULL・常に `1.0`。`(parent_id, child_id, relation)` の一意性は DDL の
`UNIQUE` 制約ではなく r01 の `ID_UNIQUENESS_CHECKS`（Python 表明）で検証する
（`ID_REFERENCE_CHECKS` に `place_relation.parent_id`/`child_id` -> `place.place_id` も
ある）。`source_edition_id`（ADR-0006 が挙げる列）はまだ持たない。

`place_relation` はまだ `web/src/db/schema-registry.ts`（D1）に無い。地域・ゾーン単位の
ロールアップ集計のような消費者がまだ無いため、載せる判断を先送りしている
（ADR-0001: D1 は捨てて作り直せる配信キャッシュ）。`web/scripts/seed-d1-local.mjs` は
D1 側に既に存在するテーブルだけをシードするので、この先送りはローカル D1 のシードを
壊さない。

### `variable_alias.csv` の列（Phase B: 出典 × 表記で解決する）

ADR-0010 決定1「エイリアスは出典 × 表記で解決する」に沿って、Phase B で列を作り直した
（`docs/plans/PHASE_B_INTAKE.md` #1）。117行（`(alias, source_scope)` 単位）から
154行（`(alias, dataset, source_id)` 単位）になっている。

| 列 | 意味 |
|---|---|
| `alias` | v1 の生の表記（`measurements.variable` / `sensor_timeseries.datastream`） |
| `dataset` | v1 のどのテーブルの表記か（`measurements` / `sensor_timeseries`）。以前の `source_scope` を改名した。「出典スコープ」を名乗りながらテーブル名を持っていたのが Phase A の実装のズレだったので、実態に合わせて改名した |
| `source_id` | v1 `source_registry.source_id`。空 = 出典未記録（`measurements.source_id IS NULL` の行。全件 `is_synthetic=1`） |
| `variable_id` / `unit_id` | 従来どおり。同じ `(dataset, alias)` を共有する行は必ず一致する（ビルド時表明。後述） |
| `stat` / `grain` | 従来どおり。`(dataset, alias, source_id)` の組ごとに固定1値（一次資料調査済み。`docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md`） |
| `note` | 従来どおり。根拠となる一次資料は `docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md` の該当節を参照する形で書く（154行全部にURLを書けないため） |

`source_id` は ADR-0010 決定1が言う `source_edition_id` の**暫定形**。`source_registry`/
`source_edition`（ADR-0005）が入る Phase C で置き換わる（`docs/plans/PHASE_B_INTAKE.md` #9
と同じ性質の暫定接続点）。

**ビルド時の表明**（`scripts/registry/build_unit_variable.py`。原本 DB は開かない）:

1. `(dataset, alias, source_id)` が一意（`source_id` が空の行も Python 側で明示的に比較する。
   SQLite の「NULL は互いに異なる」に頼らない）。
2. 同じ `(dataset, alias)` を共有する行は `variable_id` と `unit_id` が一致する
   （`resolveVariableInfo()` が「どの `source_id` の行を引いたか」に関わらず同じ結果を
   返すための根拠）。
3. `grain` は `{hour, day, month, year, fiscal_year}`、`stat` は実際に使われている値の
   集合（`point, mean, min, max, sum, p75, p90, max_10min, max_1h, max_daily,
   mean_of_daily_min, mean_of_daily_max` と空）のコードリストに入っていること。

「CSV の154組が v1 の実データの組と過不足なく一致するか」は `build_unit_variable.py` の
責務ではない（原本 DB を開かないため）。`scripts/r02_resolution_report.py`（原本を読める側）
が突合し、`reports/registry_resolution.md` §8 と `reports/registry_resolution/
alias_source_pairs_{csv,data}_only.csv` に片方向ずつのズレを出す（0件が現状）。

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
