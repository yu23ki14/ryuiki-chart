# 奄美大島 Step 1: 取込 A（Issue #89）

Step 1 は2本の PR に分ける（オーナー決定 2026-10-10）。

- **PR-A（この文書の §1〜§6）**: 収集。c スクリプトが `scripts/regions.py` を読み、奄美（`jp-46`）の分を
  `data/processed` に**別名で**出す。神奈川の出力名・source_id・挙動は変えない。
- **PR-B（§7、PR-A の上に積む）**: 取り込み。m0x・マニフェスト・place・件数の宣言・v2 を通して、アプリで見えるところまで。

その他の決定:
- 奄美の流域は国土数値情報 W12 のまま。W12 が覆わない地点・出現・セルは流域を NULL にする（落とさない）。
  覆われない数を計測して報告し、流域の作り直しは数字を見てから別 Issue にする。
- Issue の Step 1 の 5（海面水温・そらまめ君・OSM）も含める。

## 1. 共通の規約（担当 F が最初に入れる）

### 1.1 `scripts/regions.py` に足すもの

- `slug`: `jp-14` は `"kanagawa"`、`jp-46` は `"amami"`。
- `bbox`: `(lon_min, lat_min, lon_max, lat_max)`。
  - `jp-14`: `(138.9, 35.1, 139.8, 35.7)`。`c80`・`m01` の `KANAGAWA_BBOX` を転記する。PR-A では m01 を書き換えない。
  - `jp-46`: 奄美大島・加計呂麻島・請島・与路島を含み、喜界島（東経129.9度以東）と徳之島（北緯28.0度以南）を含まない矩形。
    担当 F が C23 の奄美の海岸線（`data/processed/nlni_c23_coastline.*`）の範囲から決め、根拠を docstring に書く。
- `soramame_stations`: `jp-14` は `c11` の直書きの辞書を転記する。`jp-46` は奄美市名瀬浦上町の1局。
  局コードは担当 F がそらまめ君で確かめる。
- `jma_sst_areas`: `jp-46` は奄美群島の沿岸4海域（617〜620）。`jp-14` は空のタプル（神奈川の海面水温は範囲外）。
- 全て tuple で持つ。Step 0 の規約どおり。

### 1.2 c スクリプトの入口（関数は `scripts/regions.py` に置く）

- `add_region_arg(parser)`: `--region`（既定 `jp-14`、`REGIONS` の鍵だけ受け付ける）。
- `get(rid) -> dict`
- `name(base, rid)`: 出力名と source_id を組み立てる。規則は2つだけ。
  - 元の名前に `kanagawa` を含むもの（`gbif_kanagawa_occurrences`、`jma_monthly_kanagawa` など）は、`kanagawa` を slug に置き換える。
  - 地域名を含まないもの（`nlni_w12_watersheds`、`gsi_elevation_grid`、`nlni_l03b_landuse_2016` など）は、
    `jp-14` ならそのまま、それ以外なら `_<slug>` を末尾に付ける。
  - 神奈川の名前が1文字も変わらないことを、テストで全 c スクリプトについて固定する。
- raw のキャッシュ・進捗ファイル（`data/logs/gbif_progress.json`、`c80` のページキャッシュ、`c65` の raw ディレクトリ）も
  `name()` で地域別にする。ただし神奈川の既存パスは変えない。

### 1.3 守ること

- 神奈川の分は**ネットワークで取り直さない**。神奈川で何も変わらないことは、名前と定数のテストで示す。
- `common.register()` は原本の `source_registry` に行を足す（c スクリプトの既存の挙動）。奄美の新しい source_id は、
  `registry/source/access.yaml` に `reason: file_only` で宣言する（basis 付き）。PR-B で取り込んだら外す。
- User-Agent は `scripts/common.py` のものを使い、個人名を入れない。
- `scripts/tests/test_regions.py` の「jp-14 が c スクリプトの直書きと一致する」テストは、直書きを消したら
  「c スクリプトが regions.py を読んでいる」ことの検査に置き換える。

## 2. 担当 I1: 水系と国土数値情報の面（c31 → c30 → c62、c32〜c35）

- `c31` W05: `W05-08_46` から取る。奄美の5市町村の範囲（bbox または流路の位置）に絞る。出力は `nlni_w05_rivers_amami.*` と `nlni_w05_river_nodes_amami.*`。
- `c30` W12: 鹿児島のファイルから、奄美の範囲の流域を出す。出力は `nlni_w12_watersheds_amami.*`。
  水系名の推定は、奄美の W05 を使う。
  Issue の約36面と bbox 内の25面の差を確かめ、報告に書く（AMAMI_STEP0 §8-6）。
- `c62` 標高: グリッドの範囲を `bbox` と、その地域の W12 から作る。出力は `gsi_elevation_grid_amami.*`。
- `c32` A10・`c33` A15・`c35` A45: 県のファイルを奄美の範囲に絞る。流域の列は、奄美の W12 で付ける。W12 の外は NULL。
- `c34` L03-b: メッシュ `4229` を使う。
  - 神奈川は今までどおり「W12 に重心が入るセルだけ残す」。
  - 奄美は `bbox` 内に重心があり、かつ海でないセルを残す。流域は W12 の外なら NULL。
  - 流域ごとの集計（`*_by_watershed_amami`）は、W12 の内側だけで作る。
- **計測（報告に書く）**: 奄美の W12 の面数と面積、島の陸域のうち W12 が覆う割合。L03-b のセルのうち流域が NULL の割合。

## 3. 担当 I2: 出現と土地被覆（c02・c03・c80・c65）

- `c02` GBIF: GADM の5つをループで取り、`gbifID` で重複を除く。進捗ファイルは地域別にする。出力は `gbif_amami_*`。件数の目安は約4.8万件。
- `c03` iNaturalist: place の5つをループで取り、`id` で重複を除く。出力は `inaturalist_amami.jsonl`。目安は約1.4万件。
- `c80` 植生（レイヤー7）: `bbox` を regions.py から取る。source_id は `biodic_veg2024_amami`。ページキャッシュは地域別にする。
  - 哺乳類のメッシュ（`biodic_mammal_mesh_*`）も同じ仕組みで取れるなら、奄美の分も出す。
- `c65` OSM: Overpass の範囲を `ISO3166-2` ではなく `bbox` で指定する。神奈川は `JP-14` のまま変えない。
  - 出力は `osm_amami_*`。
  - 喜界島など5市町村の外が bbox に入るなら、市町村の境界（`admin_level=7` の area）で絞る方式に切り替え、報告に書く。
- 希少種の座標は、GBIF・iNaturalist が丸めたまま受け取る。こちらで細かくしない（Issue #89 Step 0）。

## 4. 担当 I3: 気象・水質・大気・海面水温（c10・c12・c11・新規 c15）

- `c10` 気象庁:
  - `jp-46` は `jma_stations` の block_no を直接指定して取る。名瀬は官署（s1）、笠利と古仁屋はアメダス（a1）。
  - 神奈川は今までどおり、県のページから block_no を取る。
  - 出力は `jma_stations_amami.*` と `jma_monthly_amami.*`。期間は神奈川と同じ。
  - 2010年奄美豪雨の名瀬の日降水量が取れることを確かめる。日別の出力は、神奈川の `jma_daily_yokohama` に当たるものを
    名瀬で作るかどうか、作業量を見て判断し、報告に書く。
- `c12` 公共用水域: `prefcode=46` で取り、地点は `bbox` で絞る。出力は `env_kousui_*_amami.*`。
  地点数・年度の範囲・項目を報告する。L2 に届くかの判定材料になる。
- `c11` そらまめ君: 1局（F が regions.py に入れた局コード）。出力は `soramame_*_amami.*`。
- **新規 `c15_jma_sst.py`**: 気象庁の「沿岸の海面水温」の海域 617〜620 の CSV（1982年〜）を取る。
  - 出力は `jma_sst_amami.{csv,jsonl}`。列は海域コード・海域名・年月（日）・水温・平年差など。
  - ライセンスは PDL1.0。`register()` で登録する。
  - 観測項目（variable）の語彙の追加は PR-B でやる。

## 5. 受け入れ基準（PR-A）

1. 全ての対象 c スクリプトが `--region` を受け付け、`--region jp-14`（既定）での出力名・source_id・raw パスが
   変更前と1文字も変わらない（テストで固定）。
2. `--region jp-46` で全ての対象の出力が `data/processed` にできる。件数・期間・範囲は `reports/add_area_kagoshima.md` の
   「Step 1 取得結果」節に表で書く。
3. 原本の `source_registry` の変化は、奄美の新しい source_id の追加だけ。神奈川の行は変わらない
   （バックアップとの差分で確かめる）。
4. 新しい source_id は全て `access.yaml` に `reason: file_only` で宣言されている。r01 が通る。
   serving snapshot の差分は出典数だけ（`--mode diff` の表を PR に貼る）。
5. pytest・vitest・tsc が通る。b00 を1回回し、`reports/serving_fingerprint.json` をコミットする。

## 6. 並行の切り方

1. 担当 F（§1）が最初に入れる。小さい。
2. F のコミットの上で、I1・I2・I3 を worktree で同時に進める。触るファイルは重ならない。
   - 例外は `access.yaml` と `reports/add_area_kagoshima.md`。各担当は自分の節（コメントで区切る）だけを書き、統合でまとめる。
3. 奄美の収集（ネットワーク）は各担当が自分の範囲で回す。worktree の `data/processed` は、元のチェックアウトの実ファイルに
   symlink しない。出力は worktree 内に書き、統合のときに元のチェックアウトへ写す。
   `register()` は原本に書くので、原本の `ryuiki.sqlite` だけは symlink で共有する。

## 7. PR-B の見通し（PR-A の後に詳細を書く）

- m01〜m05 の source_id 直書きを regions.py に寄せる。
- 奄美の地点の流域を W12 で決める（外は NULL）。m01 の `KANAGAWA_BBOX` を `bbox` に置き換える。
- `manifests/*_amami.yml`（`region: jp-46`）を足す。
- build_place の `PLACE_SCOPE` を地域別にする。
- b09 の「GeoJSON と registry の流域集合の一致」を、地域ごとの W12 の和集合にする。
- 件数の宣言（cube・occurrence_place・period）を足す。
- `web/src/lib/cube/catalog.ts` の `SOURCE_GBIF`/`SOURCE_INAT` を寄せる。
- `copy-geo-assets.mjs` の `FILES` に奄美の分を足す。
- 件数を直書きしたテスト（377・882・127）を、宣言から導く形に直す。
- `docs/add_area.md` の旧記述を直す。
