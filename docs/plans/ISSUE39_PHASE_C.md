# Issue #39 Phase C — ID と版の正式化（設計）

対象: ADR-0004（識別子）/ ADR-0005（出典と版）/ ADR-0016 Phase C。作成: 2026-10-06。
**設計のみ。コードは変えていない。** 実測は `data/db/{registry,v2,ryuiki}.sqlite` を読み取り専用で引いた値（2026-10-06 時点）。
issue 本文の行番号は v1 撤去（#48 PR-5）で古い。現行は `docs/PIPELINE.md`。

前提（メイン決定）: 座標はぼかさない（ADR-0028）／D1 に L2（observation/occurrence/occurrence_place）は入れない
（公開 ID の発行はキューブ・レジストリ・DwC-A 等の配布物で使う範囲）／層2 snapshot・層3 b00 は緑のまま。

## 1. 現状の実測

### 1.1 ID の種類ごと

| 種類 | 現形式（例） | 件数 | 出現箇所 |
|---|---|---|---|
| variable | `common:variable:water.bod`（`<theme>.<name>`。出典名前空間なし） | 111 | registry・v2（observation/agg）・D1・web 全般 |
| unit | `common:unit:mg_per_l` | 29 | 同上 |
| taxon | `common:taxon:{gbif,inat,ryuiki-taxa}.<key>` | 41,454（gbif 21,234 / inat 13,978 / ryuiki-taxa 6,242） | registry・occurrence・occurrence_agg・D1 |
| place: grid01 | `common:place:grid01.3520_13900`（名前空間なし） | 4,087 | occurrence・occurrence_place・occurrence_agg。`web/src/lib/cube/grid.ts` が正規表現で分解 |
| place: site | `jp-14:place:site.<ns>-<local>`（`env-pubwater-0142`、`jma-jma_0387`、`atsugi-river-%E7%8E%89%E5%B7%9D`） | 495（`SITE_NAMESPACE` 11 種。`%` を含むのは 7） | observation・observation_agg・D1 |
| place: watershed | `common:place:watershed.nlni-83030-0001` | 377 | observation（土地利用）・occurrence_place・`grid.ts` の `WATERSHED_PREFIX`・`occurrence.ts` |
| place: zone | `jp-14:place:zone.r2r-3` | 5 | place_relation の親・`sites.zone` 解決 |
| caveat | `common:caveat:aboveLod`、`common:caveat:cells.<cell_id>` | 224 | caveat_scope・応答 envelope |
| source（bare） | `gbif_kanagawa` 等。`[a-z0-9_]+` のみ（`@ : . -` を含むものは0件） | 124（ryuiki.sqlite `source_registry`。うち `redistributable=0` が33、事実表から参照されるのは13） | `source_registry`・variable_alias.source_id・occurrence(_agg).source_id・summary_*・place_source_ref.source_id（別義、下記） |
| 版付き dataset | `nlni_l03b_landuse_by_watershed@2006`/`@2016`（variable_alias.dataset の46行: 2006 が22・2016 が24。alias 全200行） | 2 値 | `registry/variable_alias.csv`、`scripts/b03_build_observation.py`（699・768 行付近の `f"{LANDUSE_SOURCE_ID}@{data_year}"`、655 行の前方一致）、`scripts/migrate/cube_invariants.py`（43・71 行の `@` 正規化）、`web/src/lib/cube/series.ts`（コメントのみ）、`generated.ts`（再生成物）、テスト（`migrate_fixtures.py`、`test_b04_build_cube.py`）、ADR-0005 追記・`PHASE_B_LANDUSE.md`・`PHASE_B_INTAKE.md` |
| place_source_ref.source_id | `'sites.site_id'` 495 / `'sites.zone'` 5 / `'watershed_meta.watershed_id'` 377 / `'organism_records.lat_lon'` 4,087（計 4,964 行） | 4 値 | `scripts/registry/build_place.py`、`scripts/b03_build_observation.py`（221・237・634・646 行）、`scripts/r02_resolution_report.py`、`web/src/lib/cube/sql.ts`（126〜147）、`web/src/lib/registry/index.ts`、`web/serving_queries.yaml`（34・51・61・81）、`web/src/db/schema-registry.ts`、各テスト fixture |
| observation（公開 ID なし） | 自然キー `(source_table, source_row_id)` のみ | 1,029,034（measurements 320,899 / sensor_timeseries 698,419 / landuse 9,716） | v2.sqlite のみ（D1 に入れない） |
| occurrence | `record_id` = `<source_id>__<出典の key>`（スコープなし、最長37字） | 823,692（gbif_kanagawa_occurrences 658,360 / inaturalist_kanagawa 165,332） | v2 occurrence・occurrence_place、`scripts/x01_dwca.py` が `occurrenceID` にそのまま出す |

### 1.2 実測で分かった、設計を縛る事実

1. **曖昧さの正体**: `scoped_id()` 側の `<scope>:<entity>:<local>` は `partition(":")` で既に機械分解できる（`slugify_local_key` が `:`→`.` に直す）。
   曖昧なのは **local の中の `<kind>.<ns>-<key>`** だけ。名前空間トークン自体が `-` を含む（`env-pubwater`・`jiban-chinka`・`atsugi-river`・`hiratsuka-taiki`・`ryuiki-taxa`）うえ、
   key も `-` を含む（`83030-0001`、`jiban-chinka-12-1`）ので、`-` で切ると必ず誤分割する。taxon は区切りが既に `.`（`gbif.123`、ns に `.` なし）で曖昧でない。
2. **observation の `source_row_id` は ID の素材にならない**: sensor_timeseries は原本の整数 rowid（`'1'`,`'2'`…）、土地利用は CSV 行番号由来（`"<row_number>:<suffix>"`、b03 795 行）。
   どちらも原本・CSV の並びが変わると別物を指す。measurements の `measurement_id`（323,164 件全て一意）だけが出典の識別子。
   sensor は業務キー `(site_id, datastream, phenomenon_time, source_id)` が 717,839 行で全て一意（実測）。土地利用の業務キーは b03 721 行のコメントどおり `(watershed_id, data_year, landuse_code_raw, 種別)`。
3. **`source_registry` は版を1件しか持てない**: `register()` が `INSERT OR REPLACE`（ADR-0005 追記）。`fetched_at` は全124行に入っているが取得履歴は復元不能。
   版が実在する証拠は、`gbif_kanagawa`（586,300、notes 先頭に `【SUPERSEDED 2026-08-29】`、全124行中1件）→ `gbif_kanagawa_occurrences`（658,360）、`nlni_l03b_landuse_2006`/`_2016`（別行）、地盤沈下 r5/r6（#38、source_id は1つ・`source_ref` にファイル名）。
4. **`license` は71種の自由記述**（124行）。`redistributable=0` は33行。`organism_records` だけ行単位に `license_class`/`commercial_ok` を持つ。
5. **snapshot への影響**: `data/sample/serving_snapshot.json` に出る ID は `common:variable:*` のみ（165 件。`place:`/`taxon:` は 0）。
   place ID の形を変えても層2 は動かない。層3（`reports/serving_fingerprint.json`、全量）は place_id を返す問い合わせがあれば動く（§6）。
6. `place_source_ref.source_id` の4値は出典ではなく「外部キーの空間」（v1 の `表.列`）。site だけは `site_id` に `<source>__<code>` が埋まっているので行ごとの出典が引ける。zone は自前の分類、grid01 は座標から作った機械グリッドで出典を持たない。

## 2. 決定

### 2.1 ID 文法（ADR-0004 規約1 の改定）

```
id        := scope ":" entity ":" local
scope     := "common" | region_id                  -- region_id = [a-z0-9]+(-[a-z0-9]+)*
entity    := variable | unit | taxon | place | caveat | source | edition | obs | occ
local     := [kind "."] [ns "."] key               -- どの部品があるかは entity（と place は kind）で決まる
ns        := [a-z0-9_-]+  （'.' と ':' を含まない）
key       := slugify_local_key() を通した文字列    -- '.' '-' '_' '%XX' を含んでよい
```

**区切りの比較（1つ推す）**

| 案 | 内容 | 利点 | 欠点 |
|---|---|---|---|
| **A（推す）** | ns と key の区切りを `.`。**ns に `.` を禁止**、最初の `.` で切る。place は `kind.ns.key` | taxon（41,454件）・variable・unit・caveat は**無変更**。変更は place の site/watershed/zone の877件だけ。taxon が既に使っている区切りと同じなので文法が1つ。URI でそのまま使える | key に `.` が入るので「最後の `.`」で切ってはいけない（最初の `.` で切る規則を ADR に明記）。ns なしの kind（grid01）は kind のコードリストに `ns_required=0` を持たせる |
| B | `/` | 視覚的に分かる | `slugify_local_key` が `/`→`_` にしている（変更要）。URL パス引数（`/api/.../<id>`）で常にエンコードが要る。ADR 規約4 の `/id/<scope>/<entity>/<local>` と階層が衝突 |
| C | `~` | 全 ID 文字と衝突しない | 読みにくい。ツール・シェルで扱いにくい（チルダ展開）。taxon の既存形（`.`）と二重ルールになり taxon 41,454 件も揃えるなら変更が大きい |
| D | ns から `-` を禁止（`env_pubwater`）して `-` を維持 | 区切りは変わらない | `ryuiki-taxa`（6,242 件）を含め ns を全部書き換える。key 側の `-` と読み分ける規則が暗黙のまま |

→ **A**。place 4,964 件のうち grid01（4,087）は無変更。変更後の例:

| 旧 | 新 |
|---|---|
| `jp-14:place:site.env-pubwater-0142` | `jp-14:place:site.env-pubwater.0142` |
| `jp-14:place:site.jma-jma_0387` | `jp-14:place:site.jma.jma_0387` |
| `common:place:watershed.nlni-83030-0001` | `common:place:watershed.nlni.83030-0001` |
| `jp-14:place:zone.r2r-3` | `jp-14:place:zone.r2r.3` |

`scripts/registry/common.py` の `place_id()`（572 行 `f"{namespace}-{slug}"`）を `f"{namespace}.{slug}"` にする1箇所で生成側は済む。分解側（読む側）は `parse_id()` を `common.py` に1つ置き（Python）、
`web/src/lib/cube/grid.ts` の `WATERSHED_PREFIX = "common:place:watershed.nlni-"` と `occurrence.ts` の同コメントを `.` に直す（TS 側に `parseId()` を1つ置き、grid.ts はそれを使う）。
`scope_of()`（`partition(":")`）は無変更。合成データ（規約5）は `synthetic` を ns にする（`common:obs:synthetic.<key>`）。v2 の observation は現在 `is_synthetic=1` が0件なので発行は将来用の規則だけ置く。

**region スコープの扱い（規約0 は変えない）**: place の `jp-14` スコープ（site・zone）はそのまま。**ファクト ID（obs/occ）は `common` にする**。
理由: 出典が増えて地域の切り直しが起きても ID が変わらない（規約2）。地域は `region_id` 列で絞る。迷ったら `common`（規約0）。

### 2.2 source / source_edition / license の表設計（registry.sqlite に新設、D1 にも載せる。件数は小さい）

```
license         license_id PK, name_ja, spdx_or_url, license_class, attribution_text, notes
                  -- license_class: public_domain | cc_by | cc_by_sa | noncommercial | terms_confirmation_required | unknown （organism_records.license_class の値域に合わせる）
source          source_id PK(bare。既存124行そのまま), source_ref_id (= 'common:source:' || source_id), name_ja, publisher,
                  homepage_url, region_id, theme(= category), access_method, superseded_by(source_id NULL可), notes
source_edition  edition_id PK ('common:edition:<source_id>.<edition_key>'), source_id FK, edition_key, vintage(NULL可),
                  fetched_at, url, format, content_sha256(NULL可), license_id FK, license_class, redistributable,
                  commercial_ok, record_count, superseded_by(edition_id NULL可), embargo_reason, update_mode, notes
```

- **公開 ID と bare ID の関係**: `source_id` は `[a-z0-9_]+` のみ（実測0件が例外）なので local として**そのまま使える全単射**。公開 ID は `common:source:<source_id>`。
  cube（occurrence_agg.source_id・summary_*）・D1・alias は **bare のまま変えない**（書き換えの爆発を避ける。公開 ID が要る場所＝DwC-A・カタログ・id_map だけが関数 `source_public_id()` を通す）。
- **edition_key**: 出典自身が版を持つもの（土地利用 `2006`/`2016`、赤リスト `2020`/`2022`）は **vintage**、それ以外は取得日 `YYYYMMDD`（`source_registry.fetched_at` から）。1 source に edition は最低1つ（124 source → 初期は 124 + 宣言した追加分）。
  過去の取得履歴は**復元不能なので作らない**（捏造しない）。分かっている版だけを `registry/source/editions.yaml`（新規）に宣言する。
- **宣言する版**（`editions.yaml`）:
  - `nlni_l03b_landuse_by_watershed`: `2006`（`fetched_at` と `url` は `source_registry.nlni_l03b_landuse_2006` 行から）と `2016`（同 `_2016` 行から）。`nlni_l03b_landuse_2006/_2016` は生の取得行として source のまま残し、notes で関係を書く。
  - `gbif_kanagawa`（edition `gbif_kanagawa.<日付>`、586,300）`superseded_by` → `gbif_kanagawa_occurrences.<日付>`（658,360）。**かつ** `source.superseded_by`（source_id は不変なので source 側にも張る。ADR-0004 規約2「旧 ID は残して `superseded_by` で指す」）。`【SUPERSEDED …】` の notes 文字列は変換後の `notes` に残すが、判定には使わない（テストで `superseded_by` の存在だけを見る）。
  - 地盤沈下 r5/r6（#38）: **本 Phase では edition を分けない**（事実行に `source_ref` のファイル名しかなく、分けるにはファクト側の解決規則が要る。#38 の重複解消と一緒にやる。判断点 J3）。
- **ライセンス**: 71種の自由記述を `registry/source/license.yaml`（新規、手書き）で `license_id` に写像する。`license_class`/`redistributable`/`commercial_ok` は**エディションの列**（ADR-0005）。写像漏れ・クラス未定は `unknown` にして**ビルドは通すが件数を `reports/` に出す**（黙って埋めない）。
- **隔離（決定: 出力を絞る根拠にしない）**: ADR-0028 とオーナー決定（扱うデータは全て公開済み、ライセンス表示も不要）により、`redistributable`/`license_class`/`commercial_ok` は**出典の旗として列に残す**が、出力・API・DwC-A を絞る根拠にしない。`embargo_reason` 列は作らない（ADR-0005 決定3 の「隔離」はこの方針で上書きされる旨を ADR 改定に書く）。人の判断待ちで止めない。
- **`content_sha256`**: L0 の生ファイルがリポジトリ外にあるものは `NULL`（理由を `notes`）。パイプライン入力 2 本（`pipeline_inputs.py` の CSV）は埋める。
- **fact 側の列**: v2 の `observation` / `occurrence` に `source_edition_id`（TEXT）を足す。解決は `scripts/migrate/edition.py`（新規）の `resolve_edition(source_id, *, vintage=None)` の1関数。
  土地利用は `data_year` を vintage に渡す（現在 `dataset = f"…@{data_year}"` を作っている b03 の1行がこれに置き換わる）。それ以外は source の唯一の edition。
  **キューブ（observation_agg/occurrence_agg）のキーは変えない**（ADR-0021/0025 のセル鍵・D1 summary_* の構造が動くため）。edition は L2 側と配布物・カタログに持たせる。

### 2.3 `variable_alias`（暫定1）

- `dataset` は論理名のまま（`measurements`/`sensor_timeseries`/`nlni_l03b_landuse_by_watershed`）。**`@<年>` を廃止**。
- 新列 `edition_key`（CSV）→ ビルドが `source_edition_id` に展開して保存。空 = 全 edition 共通。土地利用 46 行（2006: 22・2016: 24）だけが値を持つ。
- 一意キーは `(dataset, alias, source_id, edition_key)`（現行は `(dataset, alias, source_id)`）。`edition_key` が空でない行は、その `(source_id, edition_key)` が `source_edition` に実在することをビルドで検査する。
- 触る箇所（同じ注記が散っていた分をまとめて直す）: `registry/variable_alias.csv`・`scripts/registry/build_unit_variable.py`・`scripts/b03_build_observation.py`（土地利用節）・`scripts/migrate/cube_invariants.py`（`@` 正規化の撤去）・`web/src/db/schema-registry.ts`（alias に `edition_key`）・
  `web/src/lib/cube/series.ts` のコメント（`@2006` の記述）・`generated.ts`（再生成）・`registry/README.md`・`PHASE_B_LANDUSE.md`/`PHASE_B_INTAKE.md` の暫定の記述に「Phase C で解消」を追記・テスト（`migrate_fixtures.py`、`test_b04_build_cube.py` の `@2006`/`@2016` を `edition_key` 指定に）。

### 2.4 `place_source_ref`（暫定2）

ADR-0006 は `source_edition_id` を想定するが、現行4値は出典ではなく**外部キーの空間**。両方を正しく持たせる:

```
place_source_ref  place_id, key_space, external_key, source_edition_id (NULL可)
  key_space ∈ site_id | zone | watershed_id | grid01_latlon   -- 旧 'sites.site_id' 等を写す。registry/place/key_space.yaml に宣言
  source_edition_id: site は site_id の接頭辞（`<source>__`）から edition を引く（実在検査つき）/ watershed は nlni_w12_watersheds の edition / zone・grid01 は NULL（出典なし。理由を yaml に書く）
```

- `source_id` 列は撤去（旧値→`key_space` の写像は `key_space.yaml` に4行）。クエリの `psr.source_id = 'sites.site_id'` は `psr.key_space = 'site_id'` に機械置換（`sql.ts`・`serving_queries.yaml`・`registry/index.ts`・b03・r02・fixture）。意味は同一なので層2 の結果は動かない。
- D1 のドリズル移行: `key_space`・`source_edition_id` 列追加、`source_id` 撤去（`pnpm run db:generate`）。外部キーの検索索引 `ix_place_source_ref_external(external_key)` は維持。

### 2.5 旧 ID → 新 ID の対応表と置き場

| 対象 | 変わる件数 | 置き場・生成方法 |
|---|---|---|
| place（site/watershed/zone） | 877（495+377+5。grid01 4,087 と taxon/variable/unit/caveat は恒等） | `registry/id_map/place.csv`（`old_id,new_id,reason,spec_version`）。**手書きの宣言ファイル**。一度だけ旧ビルダーの出力から生成してコミット（以後は人が触らない）。`build_place.py` は毎回「新ビルダーが出す ID と宣言が一致」「旧 ID が全て新 ID に1対1で解決」を検査して食い違えば止める（宣言済み差分を機械検証する運用） |
| source | 124（bare→公開 ID。規則で全単射） | 表を持たず `source_public_id()`/`source_local_id()` で往復。テストで 124 件の往復を固定 |
| alias の dataset（`@年`） | 2 値（46 行） | `registry/id_map/dataset.csv`（旧 `nlni_…@2006` → `dataset=nlni_…`・`edition_key=2006`） |
| place_source_ref.source_id | 4 値 | `registry/place/key_space.yaml` |
| observation | 1,029,034 | **v2.sqlite の observation 表そのもの**: 旧自然キー `(source_table, source_row_id)` に `UNIQUE`、新 `observation_id` に `UNIQUE`。ビュー `id_map_observation` で引ける。別ファイルは作らない |
| occurrence | 823,692 | 同上（`record_id`→`occurrence_id`、両方 `UNIQUE`） |
| 配布物 | | `scripts/x01_dwca.py` の `occurrenceID` を `occurrence_id` に切り替え。切替の事実と旧→新の対応は 旧→新の対応表 CSV を DwC-A と一緒に出す（`data/dwca` の再公開は本 Phase ではしない。`dist/` の生成は Phase D） |

`registry.sqlite` に表 `id_map(entity, old_id, new_id, reason, spec_version)` を作り（`place.csv`・`dataset.csv` 由来 879 行）、`superseded_by` を持つ行（source/edition/将来の taxon）は `id_map` に**書かない**（置換と ID 改称は別: 改称は `id_map`、置換は `superseded_by`）。
受け入れ検証 = 「旧 ID の凍結リスト（place 4,964・source 124・dataset 2・observation/occurrence は v2 の旧キー列）の各行が、`id_map`（または恒等）で**ちょうど1個の現行 ID** に解決する」。

### 2.6 `observation_id` / `occurrence_id` の発行規則と安定性

```
observation_id = common:obs:<tbl>.<key>
   measurements        → tbl=meas      key = slug(measurement_id)
                         例 common:obs:meas.atsugi_river_water_quality__000000
   sensor_timeseries   → tbl=sensor    key = slug(<site local>.<datastream>.<phenomenon_time>) と source_id を ns に畳む（業務キーは一意、実測済み）。長い場合は sha256 先頭16桁（衝突検査つき）
   landuse             → tbl=landuse   key = <watershed_id>.<data_year>.<landuse_code_raw>.<area|cells>（CSV 行番号は使わない）
occurrence_id  = common:occ:<ns>.<key>      ns: gbif / inat（`scripts/taxon_namespaces.py` の写像を共有）、key = 出典の key（gbifID、iNat observation id）
                         例 common:occ:gbif.1830141077   ← source が gbif_kanagawa から gbif_kanagawa_occurrences に移っても同じ ID
```

- **ID は行の位置ではなく出典の業務キーで決める**（原本の rowid・CSV 行番号に依存しない）。同じ出典の再取得で key が同じなら同じ ID、値の訂正は同じ実体の更新で `source_edition_id` が変わるだけ（ID 不変）。
- **再発行しない**: v2 は原本から毎回全量再構築されるが、規則が決定的なので同じ原本 → 同じ ID。key が消えた行の ID は再利用しない（墓標表は作らない）。**「再利用しない」は検査で固定する**: `id_map` の新 ID が一意、旧 ID が新 ID 空間（現行の全 place/obs/occ ID）に再出現しない、を `r01`/`cube_invariants` で検査し、わざと衝突させると止まるテストを置く。
- **一意性は 3 重に守る**: ① `UNIQUE INDEX` ② `cube_invariants.py` に「ID が恒等写像でも全件が規則で再計算できる」不変条件（わざと key を重複させると止まるテスト）③ 層3 fingerprint の入力に ID 列を含めない（ID 形式の変更が既存数値の指紋を動かさないようにする）。
- D1 には載せない（`web/src/lib/table-meta.ts`/`seed-d1-local.mjs` は無変更）。
- 公開 URI（規約4）: ホストは未決（判断点 J2）。Phase C は文字列 ID と `to_uri(id, base)`（base は設定）までで、解決エンドポイントは Phase D。

## 3. ADR 改定案（要点）

**ADR-0004**（状態の「一部未実装」から規約1 区切りと observation/occurrence ID 化を外す。承認済のまま）
- 規約1 を差し替え: local の中の ns と key の区切りは `.`、**ns は `.` `:` を含まない**、最初の `.` で切る。place は `kind.ns.key`。`-` は区切りとして使わない。例 `env-pubwater-0142` を `env-pubwater.0142` に直す。
- 規約0 に追記: **ファクト ID（obs/occ）のスコープは `common`**。
- 規約2 に追記: 改称は `id_map`（ID 変更の記録）、置換は `superseded_by`。
- 規約3 の脚注: `place_source_ref` は `key_space` と任意の `source_edition_id` を持つ。
- 新節「`obs`/`occ` の発行規則」: 業務キー主義・再利用禁止・決定的。「出典 ID は `common:source:<source_id>`」を追記。
- 2026-09-25 追記の「Phase C で行う」を、実施日付きの決定に置き換える。

**ADR-0005**（状態を提案中 → 承認済、「一部実装」）
- `source` に `superseded_by`・`source_edition` に `edition_key`/`vintage`/`update_mode` を明記（ADR-0012 の `update_mode` と接続）。edition = 取得回**または** 出典自身の版（vintage）。
- 版の履歴が復元不能な既存行は**捏造しない**（現在の1版 + 宣言した版だけ）を明記。
- `variable_alias.dataset` の `@<年>` 暫定の注記を「Phase C で `edition_key` に置換済み」に更新。
- ファクトの `source_edition_id` は L2（v2）のみ。キューブ・D1 summary は `source_id`（bare）のまま、という範囲の限定を決定として書く。

**ADR-0016**: Phase C を「実施済」にし、受け入れ基準の検証コマンドを書く。**ADR-0006**: `place_source_ref` の列定義（`key_space` 追加）。**`docs/adr/README.md`**: 「バージョニングと後方互換」「語彙ガバナンスと命名規約」の未着手 2 項目を、ID 文法を入力に Phase C 末尾で起票するか判断（J5）。

## 4. 実装の分割（ファイルが衝突しないように）

担当 A・B は並行、C は B の `edition.py` の関数シグネチャ（§2.2）だけ先に合意して並行、統合は B→C の順。

**担当 A: place の ID 文法と `key_space`（ADR-0004 規約1 実装）**
- `scripts/registry/common.py`（`place_id()` の区切り、`parse_id()` 新設、`scope_of` は不変）、`scripts/registry/build_place.py`、`registry/place/key_space.yaml`（新規）、`registry/id_map/place.csv`（新規。旧ビルダーから生成）、`registry/README.md` の place 節。
- 読む側: `web/src/lib/cube/grid.ts`・`occurrence.ts`（`WATERSHED_PREFIX`・正規表現）、`web/src/lib/registry/index.ts`、`web/src/lib/cube/sql.ts`、`web/serving_queries.yaml`、`web/src/db/schema-registry.ts` の place_source_ref、`scripts/b03_build_observation.py` の **psr 結合 SQL（221・237・634・646 行付近）だけ**、`scripts/r02_resolution_report.py`、fixture（`rollup-fixture.ts`・`cube-fixture.ts`・`occurrence-fixture.ts`・`occurrence_fixtures.py`）とテスト、`reports/registry_resolution/needs_review_place.csv`（再生成物）。
- テスト: `parse_id()` を全 place 4,964 件でラウンドトリップ・区切りを `-` に戻すと壊れる、`id_map` の1対1。

**担当 B: source / source_edition / license と alias の `edition_key`**
- 新規: `scripts/registry/build_source.py`、`registry/source/{editions.yaml,license.yaml}`、`registry/id_map/dataset.csv`、`scripts/migrate/edition.py`。`scripts/r01_build_registry.py` に1段追加、`registry.sqlite` の指紋（鮮度判定）に新入力を含める。
- 変更: `registry/variable_alias.csv`、`scripts/registry/build_unit_variable.py`、`scripts/migrate/cube_invariants.py`（`@` 撤去）、`scripts/b03_build_observation.py` の **土地利用節（655・699・768 行付近）と `source_edition_id` 列の追加だけ**、`web/src/db/schema-registry.ts`（`source`/`source_edition`/`license`・alias.edition_key）、`web/drizzle/migrations/`（`db:generate`）、`web/src/lib/table-meta.ts`、`web/src/lib/registry/generated.ts`（再生成）、`series.ts` のコメント、`DEPLOYMENT.md` の `db:export --table` 一覧、alias 関連のテスト fixture。
- `source_registry`（D1 の v1 表）は**残す**（`queries.ts` の `SELECT * FROM source_registry` が使用中）。`source` はそれと並走し、`source_registry` の撤去は別 Issue。

**担当 C: observation/occurrence の公開 ID（A・B の後に統合）**
- `scripts/b03_build_observation.py`（発行関数の呼び出しと `observation_id`/`source_edition_id` 列の INSERT、表 DDL）、`scripts/b06_build_occurrence.py`（`occurrence_id`）、`scripts/b09`/`b07` は `record_id` 結合のまま（**結合キーは変えない**。`occurrence_id` は付加列）、`scripts/migrate/common.py`（発行関数・`spec_version` 更新）、`scripts/migrate/cube_invariants.py`（ID 不変条件）、`scripts/x01_dwca.py`（`occurrenceID` 切替）、`scripts/b00_run_full_gate.py` の `PIPELINE_*`（新規ファイルを足す場合のみ）、`docs/PIPELINE.md`。
- テスト: 業務キー重複で止まる・同じ入力 → 同じ ID・`id_map_observation` ビューが1対1。

**メイン（最後）**: ADR 3 本の改定、`docs/plans/ISSUE39_PHASE_C.md` の更新、D1 切替手順（`DEPLOYMENT.md`）、全量検証。

## 5. 検証（重い検証はメインが PR 直前に1回）

1. **速い検証（各担当）**: 触った箇所のテストファイル（`scripts/tests/test_registry_place.py`・`test_r01_invariants.py`・`test_b04_build_cube.py`・`web` の `cube/*.test.ts`・`registry/generated.test.ts`）。宣言済み差分のテスト: `id_map` を1行消す・ns に `.` を入れる・`edition_key` の実在しない alias を足す、がそれぞれ止まること。
2. **層2（snapshot）**: `cd web && pnpm run serving:snapshot -- --mode snapshot`。**動かない見込み**（snapshot の ID は `common:variable:*` のみ。place は含まない。実測済み）。動いたら §6 の宣言と不一致なので原因を調べる。
3. **層3（`b00`）**: 全量。**動く**（place/observation/occurrence のハッシュ。§6）。`reports/serving_fingerprint.json` を更新。`--mode diff` の before/after 表を PR に貼る。
4. **機械的な差分検証（本番経路を通す）**: before の serving 出力に `id_map` を機械適用した結果が after と**バイト一致**すること（place_id 文字列の置換以外の変化が無いことの証明）。画面・API が呼ぶ関数（`web/src/lib/cube/*`）を通した出力で行い、道具内の書き直しを検証しない。
5. **受け入れ基準（ADR-0016）**: ① 旧 ID 凍結リスト → 現行 ID が1対1（テスト）② `gbif_kanagawa` → `gbif_kanagawa_occurrences` が `source.superseded_by` と `source_edition.superseded_by` の両方で引ける（テスト・SQL）。
6. CI: `registry` ジョブ（`r01 --files-only`）に新ファイルを含める。原本なしの clone で通ることはメインが PR 直前に1回。

## 6. 動くもの・動かないものの宣言

| 対象 | 動くか | 内容 |
|---|---|---|
| 層2 `serving_snapshot.json`（サンプル） | 動かない | 出る ID は variable のみ。place/taxon/obs/occ は含まれない（実測） |
| 層3 `reports/serving_fingerprint.json` | 動く | place_id 文字列を返す問い合わせの出力ハッシュ（site 495・watershed 377・zone 5 の ID が変わる）と `pipeline_fingerprint`（observation/observation_agg/occurrence/occurrence_agg/occurrence_place の `spec_version` を上げる）。**値（n・value 等）は不変**であることを §5-4 で示す |
| D1 本番 | 再投入が要る | place 877 件の PK、`observation_agg`・`occurrence_agg`・`summary_*` の place_id、`place_source_ref` の列。web の読む側（`grid.ts` の `WATERSHED_PREFIX` 等）と D1 の中身を**同時に切り替える**（#61 の本番切り替えと同じ手順。二重読みは作らない。ロールバックは事前許可あり） |
| caveat_scope の `source_id` 行（1件）・alias.source_id・occurrence_agg.source_id | 動かない | bare `source_id` のまま |

## 7. リスクと判断を仰ぐ点

リスク
- **R1** place_id 切り替えは D1 の `observation_agg`（1,999,844 行）の PK 文字列を含む再投入になる。web とデータの切替が非原子的だと一時的に place が引けない。→ #61 と同じ手順で1回の切り替えにする。
- **R2** `slugify_local_key` が `.` を許すので、key に `.` が入った ID（`watershed` 以外の将来の出典）で「最初の `.`」規則を破るコードが書かれうる。→ `parse_id()` を唯一の分解口にし、他所の `split('.')`/正規表現を grep で禁じるテストを置く（現在 `grid.ts` の正規表現が該当）。
- **R3** sensor の業務キー ID は長い（≈70字 × 698k 行）。v2.sqlite（2.8GB）の増分は 100MB 前後。許容できなければ sha256 短縮に倒す（衝突検査つき）。
- **R4** 版の履歴は復元不能。edition が実質 1 つの source が大半で、ADR-0005 の「行単位で取得回が言える」は**将来の再取得から**効く。過大に約束しない。
- **R5（解決）** `embargo_reason` は作らない（§2.2）。担当 B は止まらない。
- **R6** `x01_dwca.py` の `occurrenceID` 切替は**公開物の契約変更**。GBIF 再投入の相手がいるなら事前に告知が要る（PHASE_B_INTAKE #17 の taxonID 問題と同じ型）。

判断（メイン回答済み）
- **J1** 区切りは `.`。**追加要件: 旧 ID 受理経路**（§2.7）。
- **J2** 文字列 ID まで。URI は Phase D 以降。
- **J3** 地盤沈下 r5/r6 の edition 分割は #38（閉じ済み）に戻さず、申し送り（§8）に残す。Issue は作らない。
- **J4** 墓標表は作らない。「再利用しない」は検査で固定（§2.6）。
- **J5** ADR README の2項目は申し送り（§8）に書くだけ。
- **J6** ファクト ID は `common`。
- **R6** DwC-A の `occurrenceID` 切替は可。旧→新の対応を公開物と一緒に出す（`data/dwca` の再公開はしない）。

## 2.7 旧 ID の受理（既存リンクを壊さない）

> **実装の現状（Issue #39 実装時に確認）**: place_id を URL・クエリ・ツール引数で受ける経路が
> 画面・API・AI ツールのどこにも無い。リゾルバ（`web/src/lib/registry/legacy-id.ts`）とテストは作ったが、
> **どの経路にも接続していない**。経路ができたらここを通す。下の「適用箇所」は将来の規約であって、現時点では未適用。

place ID が変わる877件について、旧 ID を受けたら `id_map` で新 ID に解決する。
- 入口は1か所: `web/src/lib/registry/index.ts` に `resolveLegacyId(id)`（`registry.id_map` 由来の生成物 `generated*.ts` の小さな Map、877+2件。新 ID はそのまま通す）。
- 適用箇所: place_id を URL・クエリ・ツール引数で受ける全経路（`/api` の place 指定、画面の URL パラメータ、AI ツール `web/src/lib/ai/tools.ts` の引数）。解決できたら ① 画面はサーバ側で新 ID の URL へ 308 リダイレクト ② API・AI ツールは新 ID で処理し、応答に `resolvedFrom: <旧 ID>` を付ける。どちらでも解決しない ID は従来どおり not found。
- AI のディープリンクは新 ID で生成する（旧 ID は生成しない）。
- テスト: 877件すべてで旧→新が引ける、新 ID は恒等、未知の ID は null。担当 A の範囲（`index.ts` と、place_id を受ける route/tools）。
- 旧 ID の受理は恒久的に残す（撤去時期は決めない）。

## 8. 申し送り（本 Phase では実施しない）
- 地盤沈下 r5/r6 の edition 分割と重複解消（#38 は閉じ済み。ファクト側の `source_ref` ファイル名による解決規則が要る）。
- ADR README 未着手の「バージョニングと後方互換」「語彙ガバナンスと命名規約」は、ID 文法が固まったので入力は揃った。別途起票するかは Phase C 後に判断。
- 公開 URI（ADR-0004 規約4）の解決は Phase D 以降。ホスト未決。
- 実装のベースは #31→#32→#34→#35→#45 を積んだ上。ベース確定後に担当 A/B/C を起こす。
