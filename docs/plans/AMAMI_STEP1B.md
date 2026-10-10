# 奄美 Step 1 PR-B: 取り込み（Issue #89）

PR-A（#91）で `data/processed` に集めた奄美（`jp-46`）の分を、アプリから見えるところまで流す。
流れは「原本 → マニフェスト → registry の place → 件数の宣言 → v2 キューブ → web」。前提は `docs/plans/AMAMI_STEP1.md`。

## 0. 決定（2026-10-10）

1. **画面**（オーナーの決定）
   - 集計は2地域の合算を許す。画面の文言は「神奈川県・奄美大島」に直す。
   - 地図の初期表示は神奈川のまま。「奄美大島へ」のボタンを1つ足し、`fitBounds` で移る。
   - 地域で絞る切り替えは、別の Issue にする。
2. **海面水温**: 海域617〜620 を、座標 NULL の site（`jma_sst_amami__617` など）として `site_supplement.csv` に置く（§3 の案A）。座標を推測して作らない。
3. **奄美の哺乳類メッシュは取り込まない**: 全行が未確認で、対象の3種は奄美に在来分布しない。`file_only` のままにする。
4. **site の ID の scope は `jp-46`**（例: `jp-46:place:site.jma.<local>`）。神奈川の既存の ID は1文字も変えない。
5. **植生（9,979ポリゴン）は D1 に入れる**。神奈川と同じ扱い。
6. **赤リストの意味の違いを caveat に書く**: 奄美は鹿児島県の RDB が未収集なので、環境省の全国版だけになる。鹿児島県の RDB の収集は Step 2 でやる。
7. **奄美の流域のうち、W12 が覆わない部分の注意を caveat に書く**: 覆わない部分は流域が NULL になり、流域単位の集計に出ない。流域の作り直しは、§4 の計測を見て別の Issue にする。
8. **件数の宣言は案A**: `scripts/migrate/*.yaml` は神奈川の値のまま残す。奄美の出現の件数は、各出典のマニフェストの `expected` に書く。
   - そのため `manifest.py` を緩める。target=occurrence で builtin のときは、`expected` を任意で書けるようにする。
9. **分類群の名寄せ**: 奄美の taxon_key が `taxon_gbif_accepted.csv` に無い数を測る。多ければ、名寄せの収集を奄美の分で回す。

## 1. 出典27件の扱い

原則は「神奈川の同じ種類の出典と同じ扱い」。

| 奄美の出典 | 取り込み先 | access.yaml |
|---|---|---|
| `nlni_w05_rivers_amami` | 表には入れない。`rivers.geojson` に合流させる | `file_only`（basis に「地図の配信に使う」と書く） |
| `nlni_w05_river_nodes_amami`、A10・A15・A45、L03-b のセル 2006・2016、標高の格子、OSM の4件、`biodic_mammal_mesh_amami` | 入れない | `file_only`（「PR-B で外す」の文言は消す） |
| `nlni_w12_watersheds_amami` | registry の place（watershed 25面）、`place_watershed`、`watersheds.geojson`、b09 | `file_only`（神奈川と同じ） |
| `nlni_l03b_landuse_by_watershed_amami` | b03 → observation。マニフェストは revision・jp-46 | 消す |
| `biodic_veg2024_amami` | `vegetation_polygons`（m05） | `records: [vegetation]` |
| `gbif_amami_occurrences`、`inaturalist_amami` | `organism_records`（m03）→ b06/b09/b07。マニフェストは snapshot | 消す |
| `jma_stations_amami`、`env_kousui_stations_amami` | `sites`（m01） | `records: [sites]` |
| `soramame_stations_amami` | 座標 NULL の place（`site_supplement.csv`） | `records: [sites]` |
| `jma_monthly_amami`、`jma_daily_nase` | `sensor_timeseries`（m02）。マニフェストは append | 消す |
| `env_kousui_annual_amami`、`env_kousui_sample_amami` | `measurements`（m02）。マニフェストは append | 消す |
| `soramame_hourly_amami` | `sensor_timeseries`。マニフェストは snapshot、時刻ラベルの宣言は hour_ending | 消す |
| `jma_sst_amami` | `sensor_timeseries`（site は `jma_sst_amami__<海域>`）。マニフェストは snapshot | 消す |

## 2. 担当ごとの変更

### 2.0 担当 F（最初に入れる。小さい）

- `scripts/regions.py` に関数を3つ足す。
  - `region_of_source_id(source_id)`: 出典名の slug から地域を引く。`jma_daily_nase` のような例外は表で持つ。
  - `w12_stems()`: 全地域の W12 の名前を、`REGIONS` の順に返す。
  - `site_scope(prefix)`: site の ID に使う scope を返す。
- `scripts/taxon_namespaces.py` の `TAXON_KEY_SOURCE_NAMESPACE` に、`gbif_amami_occurrences: gbif` と `inaturalist_amami: inat` を足す。

### 2.1 担当 A（原本への取り込み）

触るファイル: `m01_sites.py`・`m02_measurements.py`・`m03_organisms.py`・`m05_tier1.py`・`c68_gsi_dem_terrain.py`と、それぞれのテスト。

- **m01**
  - `KANAGAWA_BBOX` を、地域ごとの `bbox` に置き換える。
  - `load_watersheds`/`find_watershed` は、`w12_stems()` の全 geojson を連結して読む。W12 の外は NULL にする。
  - 出典名の直書きのループは `for rid in REGIONS` にし、名前は `regions.name()` で組む。ファイルが無い出典は飛ばす。
  - zone は書かない。実行の順は m01 → c68 → m09。
- **c68**: `region_of_source()` は、マニフェストが無ければ `regions.region_of_source_id()` を使う。奄美の地点を、神奈川の最高峰の基準で判定しないため。
- **m02**
  - `SENSOR_SOURCES` に、奄美の気象（月別・日別）とそらまめ君を足す。
  - 海面水温は `area_code` から site_id を作る。
  - 水質（年間値・検体値）は、地域ごとに呼ぶ。
- **m03**: iNaturalist と GBIF の取り込みと backfill を、地域ごとに呼ぶ。
- **m05**
  - `Watersheds` は W12 を連結して読む。
  - 植生の取り込みは地域ごとにし、`feature_id` が重複したら止める。
  - 哺乳類メッシュは触らない。

### 2.2 担当 B（registry）

触るファイル: `scripts/registry/build_place.py`・`scripts/registry/common.py`・`registry/place/site_supplement.csv`・`registry/variable.yaml`・`registry/unit.yaml`・`registry/variable_alias.csv`・`registry/source/access.yaml`・`registry/source/editions.yaml`・`registry/caveat.yaml`と、registry のテスト。

- **build_place**
  - `PLACE_SCOPE="jp-14"` をやめ、出典の名前空間から scope を決める（`jma_stations_amami` → `jma`/jp-46 など。海面水温は `jma-sst`）。
  - `place_id` の衝突検査のキーに scope を入れる。
  - W12 の jsonl は全地域を連結して読む。
  - 神奈川の既存 ID が変わらないことをテストで固定する。
  - id_map は改称の記録なので、行を足さない。
- **common**: 奄美の W12 の jsonl を、指紋（`compute_fingerprint`）に入れる。
- **site_supplement**: そらまめ君の1局と、海面水温の4海域を足す。座標は空、状態は needs_review にする。
- **variable と alias**
  - 水質（年間値・検体値）・気象・そらまめ君の alias は、神奈川の行の `source_id` を差し替えてコピーする。
  - 土地利用の alias は、2006・2016 の行を複製する。
  - 気象の `全天日射量_平均`（単位 MJ/m2）は新しい variable と unit で足す。
  - 新しい variable `water.sea_surface_temp`（単位 degC、平均）を足す。説明には「海域の平均。点の水温ではない」と書く。
- **access.yaml**: §1 のとおり。
- **caveat**: 決定 6・7 の2件を足す。

### 2.3 担当 C（マニフェストとキューブ）

触るファイル: `manifests/*_amami.yml` と `jma_daily_nase.yml`・`scripts/ingest/manifest.py`・`scripts/b03_build_observation.py`・b06/b07/b09・`scripts/migrate/*.yaml`・`pipeline_inputs.py`・`migrate/common.py`・`s01_build_sample.py`・`data/sample/coverage.yaml`と、b0x・ingest のテスト。

- **マニフェスト9件**: 神奈川の同じ種類のファイルを写し、`source`・`region: jp-46`・`evidence`・件数だけを変える。
- **manifest.py**: 決定 8 のとおり緩める。
- **b03**: 土地利用の CSV を複数読めるようにする。
  - `source_table` は、神奈川は今のまま、奄美は出典名にする。こうしないと行番号が衝突する。
- **b09**: W12 の geojson を、地域ごとのリストで受ける。registry の流域集合との照合は、全地域の和集合で行う。
- **W12 の固定名**: `pipeline_inputs.SOURCE_FILE_KEYS`・`migrate/common.V2_PROCESSED_FILES`・`s01`・`coverage.yaml` にある固定名を、全地域の連結に直す。
- **件数の宣言**: 統合で一度回し、実測の値を書く。予想値は書かない。
- **時刻ラベル**: `time_label_conventions.yaml` に `soramame_hourly_amami` を足す。

### 2.4 担当 D（web）

- `web/src/lib/cube/catalog.ts` の `SOURCE_GBIF`/`SOURCE_INAT` を配列にする。SQL のプレースホルダは配列の長さから組む。
- `web/scripts/copy-geo-assets.mjs`: 複数の geojson を連結して、`rivers.geojson` と `watersheds.geojson` に書く。神奈川の feature 数が減らないことを確かめる。
- `web/src/lib/table-meta.ts`・`web/src/lib/mcp/tools.ts` の説明文と、画面の文言（`layout.tsx`・`page.tsx`・`SiteNav.tsx` など）を「神奈川県・奄美大島」に直す。
- 地図に「奄美大島へ」のボタンを足す。地域の範囲は、生成物か定数1か所で持つ。初期表示は変えない。

## 3. 統合（実行の順）

1. 原本で次の順に回す。
   - m01 → c68 → m09 → m02 → m03 → m05
   - r01 → `build:registry:ts`
   - `build:v2`（b03 → b04 → b06 → b09 → b07 → b13）
2. 止まったところで出た実測値を、件数の宣言に書く。
3. 一時 clone で CI を再現し、serving snapshot を `--mode diff` で比べる。
4. b00 を回す。

## 4. 計測（`reports/add_area_kagoshima.md` の PR-B 節）

- 出現（GBIF・iNaturalist）が W12 のどれに入るかを数える。区分は、1面に解決・0面（陸か海か）・座標なし。
  - 出典別、日付の有無別、丸めた座標かどうか別にも出す。
- 水質の地点と気象の地点が W12 に入る割合。
- 名寄せされていない奄美の taxon の数（決定 9）。
- 方法（計測用のスクリプトは残さない。使い捨ての Python を `.venv/bin/python3` で書く）: 原本 `ryuiki.sqlite` は
  `file:…?mode=ro` で開く。`organism_records`（`source_id IN ('gbif_amami_occurrences','inaturalist_amami')`）の
  `(lon, lat)` を `migrate/point_in_polygon.py` の `load_polygons`・`build_grid`・`locate` で
  `nlni_w12_watersheds_amami.geojson` に当て、0面の点は `nlni_l03b_landuse_2016_amami.geojson`（陸セル）に入るかで
  陸・海を分ける。丸め/秘匿は出典ファイルから引く（GBIF の `issues` に COORDINATE_ROUNDED、iNaturalist の
  `obscured`/`geoprivacy`。原本に列は無い）。taxon は `taxon_key` を `taxon_gbif_accepted.csv` の
  `gbif_key`/`accepted_key` と照らす。数字は reports の PR-B 節に残してある。

## 5. 受け入れ基準

1. 神奈川について、次のものが変わらない。
   - 既存の place の ID。
   - 神奈川の出典ごとの行数（原本・キューブ）。
   - serving snapshot の差分のうち、合算で動く以外のもの。差分の表を PR に貼る。
2. 奄美の取り込みで、次の行が入る。
   - 地点 28＋座標なし5。
   - 観測は、気象・水質・そらまめ君・海面水温・土地利用。
   - 出現は、GBIF と iNaturalist の全件（宣言との一致まで）。
   - 植生 9,979。
3. 地図で奄美の河川・流域界・地点が見え、「奄美大島へ」で移れる。
4. pytest・vitest・tsc・CI の clone 再現・b00 が通る。
