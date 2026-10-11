# 奄美大島の流域の作り直し（Issue #94）設計書

地理院の10m標高（DEM10B）から奄美大島の集水域を計算し、W12 の25面（陸の42.5%）を置き換える。担当ごとの節（§4〜§6）だけ読めば実装できるように書いた。
試算は 2026-10-11 に scratchpad で実施（本物の `data/db` は読み取り専用で開いただけ。リポジトリのファイルは変えていない）。

## §0 決定

### 決定済み（オーナー、2026-10-11。蒸し返さない）

- 地理院の10m標高から集水域を計算する。**対象は奄美大島（region `jp-46`）だけ**。神奈川は W12 のまま。
- place の流域 ID は `common:place:watershed.nlni.*` とは別の名前空間。
- W05（河川）の河口との突き合わせを検査に入れる。
- 専門家（水野研）の確認は後追い（人の確認待ちとして残す）。

### 設計での決め（メイン承認待ちのものは §8 に出す）

| # | 決め | 理由 |
|---|---|---|
| D1 | **ID**: place は `common:place:watershed.dem.amami-NNN`（ns=`dem`、key=`amami-NNN`、NNN は3桁連番）。`place_source_ref(key_space='watershed_id')` の `external_key`（= GeoJSON の `watershed_id`）は `dem-amami-NNN`。W12 の `89599-0001` 型とは名前が衝突しない。連番は出口の緯度の大きい順、同じなら経度の小さい順（決定的） | 名前空間を分ける決定に従う。key_space は流用（`registry/place/key_space.yaml` の `watershed_id`）して web の `place_source_ref` 経由の引きをそのまま使う |
| D2 | **置き換える（併存させない）**。奄美の W12 25面は place・割り当て・GeoJSON・土地利用から外す。L1 のファイル（`nlni_w12_watersheds_amami.*`）は残し、§3 の比較検査の入力に使う | 併存すると同じ点が W12 と DEM の2面に入る。`b09_build_occurrence_place.py:431` は「ちょうど1面」でなければ place_id を NULL にするので、併存は出現の解決を悪化させる（W12 の内側が全部 NULL になる）。web も同じ島に重なる2層を描いて `watershedRollup` が二重になる |
| D3 | **計算方法**: DEM10B（z14 の `dem_png`）をモザイク → 窪地を全て埋める → D8 流向 → 集水面積 → 出口（海岸の画素）ごとの流域。ツールは **pyflwdir 0.5.x（MIT）**。流向は D8 | §2 |
| D4 | **粒度**: 自分の集水面積が `A_min = 3 km²` 以上の出口を「河口」とし、それ未満の小さな海岸斜面の流域は、**共有する境界が最長の隣の面に併合**する（隣に A_min 以上の面があればそちらを優先。小さい順に処理）。面の種別 `unit_kind`: `basin`（自前の河口あり）／`coast_group`（小流域が連なって A_min に達した面）／`island`（隣のない小島） | W12 の面は 1.6〜47.4 km²（中央値 8.6）。3 km² で中央値 7.9 km² と近い。細かくし過ぎると 1 面あたりの記録が薄くなる |
| D5 | **scope は `common` のまま**（ID の見た目が `jp-46:` にならない）。地域は #93 の `place_region`（b13 が出現・観測のキューブから作る）で引く | `lib/cube/grid.ts` の `parseId` 判定と b03 の `_manifest_region`（common は照合対象外）を変えずに済む。scope を `jp-46` にする案は web・b03 の変更が増えるので却下 |
| D6 | 出力ファイルは `data/processed/gsi_dem_watersheds_amami.{geojson,jsonl}`（W12 と同じ列名を保つ。§4-A）。出典 `source_id` は `gsi_dem_watersheds_amami` | `build_place.py` の `WATERSHED_JSONL_REQUIRED_KEYS` をそのまま満たす |
| D7 | 神奈川の入力・ID・出力は1ビットも変えない（受け入れの最重要条件） | |
| D8 | 注意書き: `amamiWatershedGap` は文面を「海上・海岸線の外の記録だけが空」に書き直し、新しい `amamiWatershedDem`（計算した流域であり公式の流域界ではない）を足す。どちらも `OWNER_PENDING_KEYS` に入れる | §6 |

## §1 現状（W12 の奄美25面がどう流れるか）

継ぎ目は `scripts/regions.py:182` の `w12_stems()` / `w12_paths()`（全地域の W12 の名前を `name("nlni_w12_watersheds", rid)` で作る）。ここから下の全てが派生する。

| 段 | 場所 | 内容 |
|---|---|---|
| 収集 | `scripts/c30_nlni_w12.py --region jp-46` | 鹿児島県の823面から奄美の bbox に掛かる25面（348.5 km²）を `nlni_w12_watersheds_amami.{geojson,jsonl,csv}` に出す。水系名は W05 の流路との交差から推定 |
| 土地利用 | `scripts/c34_nlni_l03b.py:79-91, 120-143`（`nlni_lib.read_w12`） | L03-b の100mセルの重心が W12 の面に入るかで `watershed_id` を付ける。外は NULL。`nlni_l03b_landuse_by_watershed_amami.csv`（`manifests/nlni_l03b_landuse_by_watershed_amami.yml` の `expected_row_count: 283`） |
| 林地等 | `scripts/nlni_lib.py:270-309`（`w12_index`・`assign_watershed`）、`c33_nlni_a15.py:206` | 面の重心が入る W12 の面。外は NULL |
| 地点 | `scripts/m01_sites.py:52-75`（`load_watersheds`、`regions.w12_paths(PROC, missing_ok=True)`） | `sites.watershed`。外は NULL |
| 台帳 | `scripts/m05_tier1.py:63-74`（`m01_sites.load_watersheds` を再利用） | `protected_areas` 等の `watershed` |
| place | `scripts/registry/build_place.py:293-359, 639-668`（`WATERSHED_JSONLS`＝`registry/common.py:299` の `WATERSHED_JSONL_RELPATHS`） | `common.place_id("watershed", "nlni", watershed_id, scope="common")`、`place_source_ref(key_space='watershed_id')`、`place_watershed` 属性。`name_ja` は `water_system_name_ja_estimated` |
| 割り当て | `scripts/b09_build_occurrence_place.py:75-76, 431`（`DEFAULT_GEOJSONS`＝`regions.w12_paths`） | 全地域のポリゴンを連結して点内包判定。**ちょうど1面のときだけ** place_id、0面・2面以上は NULL。件数宣言は `scripts/migrate/occurrence_place_declarations.yaml:15`（`n_watershed_polygons: 402`＝377+25） |
| 観測 | `scripts/b03_build_observation.py:709-760, 826-877`（`_load_watershed_place_lookup`） | 土地利用 CSV の `watershed_id` → place |
| 鮮度 | `scripts/pipeline_inputs.py:38-48`、`scripts/migrate/common.py:1236`、`registry/common.py:499-545` | 入力ファイルの指紋に W12 の geojson・jsonl が入る |
| サンプル | `scripts/s01_build_sample.py:107, 1012`、`data/sample/processed/nlni_w12_watersheds_amami.*` | 凍結サンプルにも W12 の奄美が入っている |
| web | `web/scripts/copy-geo-assets.mjs:50`（`regionalGeojson("nlni_w12_watersheds")`＝`_amami` 付きも拾う）、`web/src/lib/cube/grid.ts:9-26`（ns `nlni` 固定）、`catalog.ts:1236, 1405`（`watershedRollup`・`watershedBases`）、`api/geo/watersheds/route.ts`、`MapPage.tsx:230, 322`（出典文言） | `/geo/watersheds.geojson` に両地域を連結。`watershed_id` で D1 の集計を載せる |
| 注意書き | `registry/caveat.yaml:410`（`amamiWatershedGap`）、`registry/caveat_scope.yaml:73-75` | GBIF・iNat・土地利用の3出典に付く |

2026-10-10 の計測（`reports/add_area_kagoshima.md`「Step 1 PR-B」）: GBIF の1面解決 37.5%、iNat 28.2%、土地利用セルの57.4%が NULL。

## §2 計算方法

### 2.1 DEM の入手

- 地理院タイル `https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/{x}/{y}.png`（DEM10B。1画素の標高は `x=65536R+256G+B`、`x<2^23` なら `0.01x`、`x>2^23` なら `0.01(x-2^24)`、`x==2^23` は無効＝海・欠測）。復号は `scripts/terrain_lib.py:57` の `decode_dem_png` を再利用する。
- **c68 と同じタイルキャッシュ** `data/raw/gsi_dem_png/14/{x}/{y}.png` を使う（404 は空ファイル、取得間隔1.5秒以上、`--no-fetch`、`--plan`）。ズームは **14 固定**（z14 が DEM10B の最大。8.4m/画素）。
- 要るタイルの決め方: `data/processed/nlni_c23_coastline.geojson` の `prefecture_code='46'` の線を `unary_union` → `polygonize` で陸のポリゴンにし（27面・820.1 km²。最大は奄美大島 711.5、加計呂麻島 77.2）、各ポリゴンの bbox を0.002度広げたものと交わる z14 タイルを列挙する。**311枚**（うち159枚は c68 が取得済み、新規152枚＝約4分、404は11枚）。bbox 全体（35×45＝1,575枚）を取らない。
- ライセンス: `docs/LICENSE_MATRIX.md` §4.8 と同じ（地理院コンテンツ利用規約、出典表示で商用可、**タイルは再配布しない**、流域のポリゴンは派生物なのでコミットしてよい）。§4.8 に c69 を1行足す。

### 2.2 ツール（試算の結論: pyflwdir）

| 候補 | 判断 |
|---|---|
| **pyflwdir 0.5.x**（MIT。依存: numba・scipy・numpy） | **採用**。`from_dem(outlets='edge')` が窪地埋め（Wang & Liu 2006）・D8・海との境の出口をまとめて持つ。7168×7168 画素（5,140万）で流向 24 秒、全体 20〜30 秒、メモリ 3.3 GB |
| pysheds | rasterio・pyproj・geopandas 系の依存が重い。却下 |
| whitebox | 外部バイナリの取得が要る。却下 |
| richdem | C++ ビルドが要る。却下 |
| 自前の numpy | 窪地埋めの優先度キューが純 Python で数十分。却下 |

- **依存の置き場**: ルートの `requirements.txt` には**足さない**（CI の reconcile は収集の依存を持たない。メモリの規約）。`scripts/requirements-dem.txt` を新設し、`pyflwdir==0.5.12`・`numba==0.68.0`・`scipy`・`shapely>=2.1`（`coverage_simplify` が要る）・`numpy`・`Pillow` を固定する。**`import pyflwdir` と `import numba` は c69 の関数の中**（`flow_units()` の先頭）に置く。純関数（併合・ポリゴン化・W05 河口の抽出・検査）は numpy と shapely だけで書き、トップで import するのも numpy・shapely まで。
- 決定性の確認（試算）: Python 3.10＋shapely 2.1.2＋numpy 2.2.6 と、Python 3.13＋shapely 2.2.0＋numpy 2.5.4（pyflwdir 0.5.12）で、**ラベル画像・GeoJSON のどちらもバイト一致**（GeoJSON の sha1 `46cb9fee…`）。

### 2.3 手順（試算で通した順）

1. タイルを1枚のモザイクにする（Web メルカトルの画素のまま。緯度ごとの1画素の面積は `terrain_lib.m_per_px`）。海（NaN）は無効、`ndimage.label`（8近傍）で陸の連結成分を作り、**0.1 km² 未満の成分（951個・合計0.96 km²。岩礁）は捨てる**。
2. `pyflwdir.from_dem(dem, nodata=-9999, outlets='edge')`。窪地は全て埋める（`max_depth=-1`）。海に接する画素がそれぞれ出口になる（試算で出口 20,692 個）。
3. 出口ごとの流域（`flw.basins`）と、その面積（画素面積の合計）を出す。
4. **併合**（D4）: 面積が `A_min` 未満の面を、小さい順に、4近傍で接する面のうち共有辺の画素数が最長のもの（`A_min` 以上の面があればその中から。同じなら番号の小さい方）へ併合し、併合先の面積を更新して繰り返す。隣のない面（小島）はそのまま `island`。面積が 0.1 km² 未満のまま残った面（試算で7個）は捨てる。
5. 面ごとに、出口＝自前の集水面積が最大の画素、`own_drainage_km2`（併合前の自前の集水面積）、`merged_share`＝1−own/area を記録する。
6. ポリゴン化: 行ごとの同じラベルの連続（run）を長方形にして `shapely.union_all`（53,000個、4秒）→ **`shapely.coverage_simplify` で許容 3 画素（約25m）**。`coverage_simplify` は隣り合う面の共有境界を一緒に簡略化するので**面同士の重なり・隙間が出ない**（面ごとの `simplify` では点が2面に入る例が出た。試算で重なる組 0）。経緯度に戻し、座標は小数6桁で丸める。
7. 水系名の推定（W12 の `water_system_name_ja_estimated` に相当）: 出口から 500m 以内にある W05 の河口（§3-1）の河川名を `water_system_name_ja_estimated` と `main_river_names_ja`（`|` 区切り）に入れる。河口が無い面（`coast_group`・`island`）は NULL・空文字。**「推定」の列名のまま**。

### 2.4 試算の結果（`A_min=3 km²`、`coverage_simplify` 許容 3 画素）

| 項目 | 値 |
|---|---|
| 陸（DEM の有効画素） | 823.5 km²（C23 の陸 819.5 km² と 0.5% 差） |
| 面数 | 78（捨てる7を引いて **71**）。`basin` 35・`coast_group` 約31・`island` 5 |
| 面積（km²） | 中央値 7.9、p25 4.3、p75 12.0、p90 18.8、最大 96.5（住用川の河口。W12 は役勝川 44.9 などに分けている）。W12 は 1.6〜47.4・中央値 8.6 |
| 併合された斜面の割合 | 全面積の 42%（小さな海岸斜面の集まり） |
| C23 の陸のうち流域に入る | **99.8%**（817.6 / 819.5 km²。外れは 1.9 km²＝海岸線の差） |
| GeoJSON の大きさ | 0.42 MB（W12 奄美は 85 KB。許容 1 画素で 1.3 MB、2 画素で 0.65 MB） |
| 処理時間 | 流向 24 秒＋集水・併合・ポリゴン化 約 10 秒（全体 20〜30 秒）。タイル取得は新規152枚で約4分（初回のみ） |

`A_min` を変えたときの面数（捨てる前、隣優先の併合）: 2 km² → 110、3 km² → 78、5 km² → 54。

## §3 検査（c69 が `--check` で回し、結果を `reports/amami_watershed_dem_checks.json` に書く。宣言は `scripts/migrate/dem_watershed_declarations.yaml`）

宣言の形は `occurrence_place_declarations.yaml` と同じ（`name → {expected, tolerance, exceptions: [{id, reason}], note}`）。例外は「宣言済み差分」として列挙し、機械的に突き合わせる（ゲートを緑にするためにラベルを曲げない）。

| # | 検査 | 試算の値 | 閾値 |
|---|---|---|---|
| 1 | **W05 河口との突き合わせ（出口→河口）**: `unit_kind='basin'` の面の出口から最寄りの W05 河口までの距離 | 35面すべてが 443m 以内、中央値 103m、300m 以内は 30面 | 全面が **500m 以内**。外れは例外を宣言（面 ID と理由） |
| 2 | **（河口→出口）**: 標高 10m 以下の W05 河口のうち、周囲 300m に DEM の集水面積 ≥3 km² の画素があるもの（試算で40個）から最寄りの出口まで | 40個すべてが 443m 以内、中央値 138m | **90%以上が 500m 以内**、外れは例外を宣言 |
| 3 | 陸の被覆率（C23 の陸のうち流域に入る面積） | 99.8% | **≥ 99.5%** |
| 4 | 面同士の重なり（面積 > 1e-10 度²） | 0組 | **0組** |
| 5 | **W12 との重なり**: W12 の25面それぞれについて、いちばん重なる DEM の面が W12 の面積に占める割合 | 0.95〜1.00 | **各面 ≥ 0.90**（W12 は川ごとに細かく切るので、DEM の面が W12 を含む向きで見る。IoU は 0.05〜0.92 とばらつくので使わない） |
| 6 | 出口の位置が陸（有効画素）で、海に接している | — | 全面 |
| 7 | 面積の合計 = 陸の面積（画素の数え上げ）−捨てた面積 | 捨てた岩礁の成分 0.96 km²＋捨てた面（7個）は各 0.01 km² 未満 | 捨てた面積の合計 ≤ 1.1 km² |
| 8 | **決定性**: c69 を2回回して `geojson`・`jsonl` が**バイト一致**（`--check-fresh` は `params_digest` ＋モザイクの sha256 の一致を見る） | 一致（環境をまたいでも一致） | 一致 |
| 9 | 最大面の出口が住用川の河口（緯度28.25・経度129.41付近）にある | 一致 | 宣言値 |

`params_digest` は `A_min`・許容・成分の下限・pyflwdir の版・モザイクの sha256 から作り、jsonl の全行に入れる（c68 と同じ流儀）。

## §4 担当A: 収集と計算（c スクリプト＋流域生成）

**触るファイル**（B・C と衝突しない）: `scripts/c69_gsi_dem_watersheds.py`（新）、`scripts/dem_watershed_lib.py`（新。純関数）、`scripts/requirements-dem.txt`（新）、`scripts/migrate/dem_watershed_declarations.yaml`（新）、`scripts/tests/test_c69_dem_watersheds.py`（新）、`docs/LICENSE_MATRIX.md` §4.8 の追記。`scripts/regions.py` は**触らない**（B が持つ。A は下の契約で読む）。

**regions.py の契約**（B が足す。A のテストは monkeypatch で通す）:

```python
"jp-46": { ..., "watershed": {"method": "dem", "stem": "gsi_dem_watersheds_amami",
                              "a_min_km2": 3.0, "min_island_km2": 0.1,
                              "simplify_px": 3, "dem_zoom": 14, "w05_match_m": 500} }
# jp-14 は "watershed": {"method": "w12", "stem": "nlni_w12_watersheds"}
```

**c69 の入口**: `scripts/c69_gsi_dem_watersheds.py [--plan] [--no-fetch] [--no-register] [--check] [--check-fresh]`（`--region jp-46` のみ）。`--plan` はタイル枚数だけ数えて終わる（ネットワークに出ない）。

**出力**: `data/processed/gsi_dem_watersheds_amami.geojson`（Feature の properties は jsonl と同じ）／`.jsonl`（1面1行）。列（W12 の10列と同じ名前を保つ＋追加）:

- 必須（`WATERSHED_JSONL_REQUIRED_KEYS`）: `watershed_id`（`dem-amami-NNN`）、`water_system_code_old`（NULL。W12 の旧コードは無い）、`water_system_name_ja_estimated`、`water_system_category_ja`（`unit_kind` の日本語: 河口の流域／沿岸の小流域群／小島）、`main_river_names_ja`、`area_km2`、`centroid_lat`、`centroid_lon`（面の重心）、`data_year`（NULL）、`source_ref`（タイルの URL＋`#params_digest=…`）
- 追加: `source_id`、`unit_kind`、`own_drainage_km2`、`merged_share`、`outlet_lat`、`outlet_lon`、`w05_mouth_distance_m`、`dem_zoom`、`params_digest`

`water_system_code_old` が NULL でも `build_place.py` は通る（`o[...]` の直接添字。値の型検査は無い）が、`place_watershed.water_system_code` の NOT NULL 制約が無いことを B が確かめる（DDL は `scripts/registry/` のスキーマ）。

**速い検証**: `.venv/bin/python3 -m pytest scripts/tests/test_c69_dem_watersheds.py -q`。合成 DEM（谷2本と平らな盆地）で、併合・ポリゴン化（重なり0）・W05 河口の抽出・決定性を見る。pyflwdir を要るテストは `pytest.importorskip("pyflwdir")`、numpy と shapely だけで済む純関数のテストは常に回す。**「依存を外して回す」確認を最初に1回やる**（`pip` で pyflwdir・numba・scipy・shapely が無い venv で、トップの import だけが原因の失敗が無いこと。CI の reconcile ジョブは収集の依存を持たない）。実データでは `c69 --plan` と、`c69` を回したあとの `--check` まで（フル実行は10分未満。メインが1回回す）。

**W05 の河口の抽出**（`dem_watershed_lib.w05_mouths`）: `nlni_w05_rivers_amami.jsonl` の流路の終点で、どの流路の始点でもないノード（試算で144個、標高10m以下は143個）。ノードは `nlni_w05_river_nodes_amami.jsonl`。

## §5 担当B: 取り込み（place・割り当て・b09・土地利用）

**触るファイル**: `scripts/regions.py`、`scripts/pipeline_inputs.py`、`scripts/registry/common.py`、`scripts/registry/build_place.py`、`registry/place/key_space.yaml`、`scripts/b09_build_occurrence_place.py`、`scripts/migrate/occurrence_place_declarations.yaml`、`scripts/migrate/common.py`（指紋の入力名）、`scripts/m01_sites.py`、`scripts/m05_tier1.py`、`scripts/nlni_lib.py`、`scripts/c33_nlni_a15.py`、`scripts/c34_nlni_l03b.py`、`scripts/c62_gsi_elevation.py`（W12 の名前を直書きしている箇所）、`scripts/s01_build_sample.py`、`manifests/*_amami.yml`、`registry/source/access.yaml`、`docs/PIPELINE.md`、`docs/add_area.md`、関連テスト（`test_regions.py`・`test_pipeline_inputs.py`・`test_registry_place*.py`・`test_b09_*.py`・`test_m01_m05_regions.py`・`test_s01_build_sample.py`・`test_place_id_grammar.py` ほか、`grep -rn "w12_stems\|w12_paths\|W12_PROCESSED\|WATERSHED_JSONL_RELPATH\|nlni_w12" scripts/tests`）。

1. `regions.py`: 上の契約の `watershed` を `REGIONS` に足す。`w12_stems`/`w12_paths`/`W12_PROCESSED_FILES` を **`watershed_stems`/`watershed_paths`/`WATERSHED_PROCESSED_FILES` に改名**（全 grep で機械的に。`w12_*` の名前を残すと嘘になる）。`watershed_stems()` は地域ごとに `REGIONS[rid]["watershed"]["stem"]` を返す。**神奈川の stem が `nlni_w12_watersheds` のままであること、順序（神奈川が先頭）を `test_regions.py` で固定**。
2. `build_place.py`: ID の ns を行から決める。`watershed_id` が `dem-` で始まれば `place_id("watershed", "dem", watershed_id.removeprefix("dem-"), scope="common")`、それ以外は従来の `nlni`。`place_source_ref.external_key` は常に `watershed_id` の全体。逆引き（`placeIdOfWatershedId`）も同じ規則で、**この規則は `scripts/registry/common.py` に1関数（`watershed_ns_and_key(watershed_id)`）で置き、web の `grid.ts` が同じ規則を持つことを C が検査する**。`watershed_edition_source` は stem（`gsi_dem_watersheds_amami`）。`key_space.yaml` の `edition_note` に DEM の版を足す。
3. `b09`: `n_watershed_polygons` を 377＋71（確定値は c69 の出力の行数）に。`place_id_null_count`・`resolved_count` は神奈川の値のまま（奄美の分は各出典のマニフェストの `expected.place`）。**併存でないこと**を `test_b09_*` で固定（W12 の奄美ファイルが入力に入らない）。
4. `m01`/`m05`/`nlni_lib.assign_watershed`: `w12_index(rid)` を `watershed_index(rid)` に改名し、jp-46 は DEM の GeoJSON から作る（`watershed_join_method` の文言も「地理院10m標高から計算した流域に内包」）。`c33` は呼び出しの文言だけ。
5. `c34 --region jp-46`: W12 のシェープではなく DEM の GeoJSON で割り当て、`nlni_l03b_landuse_by_watershed_amami.csv` を作り直す（`water_system_code_old` は空、`water_system_name_ja_estimated` は DEM の面から）。`manifests/nlni_l03b_landuse_by_watershed_amami.yml` の `expected_row_count`（現 283）と `expected.place` を新しい実測に。c34 は L03-b の zip を再取得する（キャッシュ済みなら不要）。
6. `s01_build_sample.py`: サンプルの流域ファイルは `watershed_paths` から（W12 奄美の代わりに `gsi_dem_watersheds_amami.*` を `data/sample/processed/` に入れる）。**`s02_materialize_sample.py` は本物のチェックアウトで実行しない**（一時ディレクトリへの clone で）。
7. 指紋: `pipeline_inputs.py` の `SOURCE_FILE_KEYS`、`migrate/common.py:1236` の `V2_PROCESSED_FILES`、`registry/common.py` の指紋が `watershed_*` 経由になるだけ（神奈川の指紋のキーは従来のまま）。

**速い検証**: 触った箇所のテストだけ（`.venv/bin/python3 -m pytest scripts/tests/test_regions.py scripts/tests/test_pipeline_inputs.py scripts/tests/test_registry_place.py scripts/tests/test_registry_place_amami.py scripts/tests/test_b09_build_occurrence_place.py scripts/tests/test_m01_m05_regions.py scripts/tests/test_s01_build_sample.py scripts/tests/test_place_id_grammar.py -q`）。実データの `r01`・`b09`・`build:v2` は走らせない（メインが1回）。

## §6 担当C: web と注意書き

**触るファイル**: `web/scripts/copy-geo-assets.mjs`、`web/src/lib/cube/grid.ts`（と `grid.test.ts` など）、`web/src/components/map/MapPage.tsx`（出典文言）、`web/src/app/api/geo/watersheds/route.ts`（コメント）、`web/src/app/sources` 周りの出典文言、`registry/caveat.yaml`、`registry/caveat_scope.yaml`、`scripts/registry/build_caveat.py`（`OWNER_PENDING_KEYS`）、`web/src/lib/registry/generated*.ts`（再生成物。`r01_build_registry.py --files-only` ＋ `web/scripts/build-registry-ts.mjs`）、関連テスト（`caveats.test.ts`・`ai/caveats.test.ts`・prompt のスナップショット）。

1. `copy-geo-assets.mjs`: `watersheds` の `src` を **明示の名前の配列**にする。`regionalGeojson("nlni_w12_watersheds")` は `nlni_w12_watersheds_amami.geojson`（残す L1）も拾うので使わない。`["nlni_w12_watersheds.geojson", "gsi_dem_watersheds_amami.geojson"]`。この2つが `scripts/regions.py` の `watershed_stems()` と一致することを `scripts/tests/test_regions.py`（A・B のテストに加えて C が1本）でファイルの文字列を読んで検査する。先頭（神奈川）が無いときの扱い・feature 数の検査は従来どおり。
2. `grid.ts`: `watershedIdOfPlaceId` が ns `nlni` と `dem` の両方を受け、`dem` は `dem-<key>` を返す。`placeIdOfWatershedId` は `dem-` 始まりを `dem` に。B の規則と同じ（`registry/common.py` の関数と同じ入出力の表をテストに）。`catalog.ts:1236` はそのまま。
3. 注意書き（D8）:
   - `amamiWatershedGap` の本文: 「奄美大島の流域は地理院の10m標高から計算した面で決めている。海上や海岸線の外にずれた座標（特に iNaturalist の秘匿された座標）の記録は流域が空になり、流域ごとの集計には出ない。島全体の件数と流域別の合計は一致しない。」`kind: coverage_gap` のまま。
   - 新規 `amamiWatershedDem`（`severity: warning`、`kind: definition`）: 「奄美大島の流域は国土数値情報 W12 の公式の流域界ではなく、国土地理院の10m標高から集水域を計算したもの。小さな海岸斜面は隣の流域に含めてある。河川（W05）の河口との位置は検査済みだが、専門家の確認は済んでいない。」`review.owner_confirmed_on: null`、`OWNER_PENDING_KEYS` に追加。
   - `caveat_scope.yaml:73-75`: `gbif_amami_occurrences`・`inaturalist_amami`・`nlni_l03b_landuse_by_watershed_amami` の3出典に `amamiWatershedDem` を足す。地図の流域レイヤに付く注意書きの出し口があれば同じ。
4. `MapPage.tsx:230`（「国土数値情報 W12 の単位流域 … 神奈川・奄美とも197…」）と `:322`（出典）を地域別の文言に。奄美は「地理院10m標高から計算した流域」＋出典「国土地理院」。地域の切り替え（`RegionUi`）の宣言に従い、画面ごとの条件を散らさない。
5. `/geo/watersheds.geojson` は 0.5 MB 程度増える（試算 0.42 MB）。キャッシュヘッダは従来どおり。

**速い検証**: `cd web && pnpm vitest run src/lib/cube/grid.test.ts src/lib/ai/caveats.test.ts src/lib/cube/caveats.test.ts`、`.venv/bin/python3 -m pytest scripts/tests/test_regions.py -q`。`pnpm run build` は走らせない。

## §7 受け入れ基準（数字）

メインが PR の直前に1回だけ回す: c69（フル）→ c34 `--region jp-46` → `r01_build_registry.py` → `pnpm run build:v2` → `pnpm run serving:snapshot -- --mode diff`（before/after 表を PR に貼る）→ `b00_run_full_gate.py`（`reports/serving_fingerprint.json` を一緒にコミット。パイプラインのパスを触るので必須）。

| # | 基準 | 現状 | 目標（試算） |
|---|---|---|---|
| 1 | C23 の陸のうち流域に入る面積 | 42.5%（348.5 / 820.1 km²） | **≥ 99.5%**（試算 99.8%） |
| 2 | GBIF（47,874件）で1面に解決する割合 | 37.5% | **≥ 95%**（試算 95.9%＝45,892件。残りの3.3%は海上の座標）。C23 の陸の点に限れば **≥ 99%** |
| 3 | iNaturalist（13,539件）で1面に解決する割合 | 28.2% | **≥ 62%**（試算 63.3%＝8,576件。残りは秘匿で海側にずれた座標） |
| 4 | 出現キューブの奄美の流域解決（日付あり）GBIF | 17,696 / 46,312 | **≥ 95%**（見込み 約44,400） |
| 5 | 同 iNaturalist | 3,809 / 13,528 | **≥ 62%**（見込み 約8,500） |
| 6 | 地点（陸上の観測局） | 河川の水質 5/6、気象 0/3、河川砂防 8/9 | 陸上の局は水質 6/6・気象 3/3、河川砂防は8/9のまま（試算で DEM の外に残る1局は位置を確認して、海上なら例外に宣言）。海域の水質局19は海の上なので NULL のまま（正しい） |
| 7 | L03-b セルの流域 NULL の割合 | 57.4% | **≤ 2%** |
| 8 | W05 河口との突き合わせ（§3-1・2） | — | 500m 以内: 出口側 100%、河口側 ≥90%、外れは宣言 |
| 9 | W12 との重なり（§3-5） | — | 25面すべて ≥ 0.90 |
| 10 | 面同士の重なり／決定性（§3-4・8） | — | 0組／バイト一致 |
| 11 | 神奈川への影響 | — | `--mode diff` の `region=jp-14` の行・神奈川だけの問い合わせが**1行も変わらない**。神奈川の place_id・指紋のキーが不変 |
| 12 | place の流域数 | 402 | 377＋71＝448（確定値は c69 の行数） |

**serving snapshot・サンプル・fingerprint への影響**: 奄美の流域別の行（`watershedRollup`・`summary_watershed_occurrence`・土地利用の流域別の観測）が全面的に変わる。`data/sample/serving_snapshot.json`（奄美の記述が41行）・`data/sample/coverage.yaml`・`declaration_counts.yaml`・`processed/` は作り直し、`reports/serving_fingerprint.json` も更新する。変わる行は「奄美の流域の行」と「奄美の `region=all` への寄与」に限られ、**差分を列挙して機械検証する**（宣言済み差分。変えたくない行は 11 のとおり）。`summary_*_by_region`（#93）と `place_region` は作り方が変わらない。`spec_version`（`migrate/common.py`）は place の集合が変わるので上げる（神奈川の値が変わらないことを 11 で確かめる）。

## §8 未決・リスク（オーナーに聞くこと）

**オーナー決定（2026-10-11）: 1〜3 はすべて推奨どおり。** `A_min = 3 km²`（71面）、小さな海岸斜面は併合して `unit_kind`・`merged_share` を開示、奄美の W12 の ID はそのまま置き換える（旧→新の対応表は作らない。本番反映は #93〜#105 とまとめて1回）。

1. **粒度（`A_min`）**: 推奨 **3 km²（71面）**。2 km² なら約100面（記録が薄い面が増える）、5 km² なら約47面（W12 に近いが細かい川が埋もれる）。
2. **小さな海岸斜面を隣の流域に併合する**（全面積の42%が併合）。推奨は併合＋`unit_kind`・`merged_share` を開示。代替は併合せず約200の小さな流域をそれぞれ place にすること（面が細かすぎて集計に向かないので非推奨）。解釈が変わる決めなので専門家（水野研）に確認する項目の筆頭。
3. **奄美の W12 の ID（`watershed.nlni.89599-*`）が本番に出ているか**。D2 の置き換えで消える。奄美の本番反映がまだなら影響なし。出ているなら `registry/id_map/place.csv` に旧→新の対応は作れない（面が1対1でない）ので、消えることの周知が要る。メインが把握していれば不要。
4. （リスクとして記録）DEM は橋・堤防・暗渠を拾わないので、市街地（名瀬）の小流域の境は実際の下水・水路と違いうる。平地の流向は窪地埋めの結果。W05 の河口との距離で粗く縛るが、細部は専門家の確認に回す。
5. （リスク）GSI がタイルを更新すると面が変わりうる。`params_digest` にモザイクの sha256 を入れ、c69 `--check-fresh` が違いを検出する。ID は連番なので、再計算で番号が入れ替わると「宣言済み差分」として一覧にする。
6. 専門家確認待ち: `amamiWatershedDem` が人の確認待ちの注意書き（`OWNER_PENDING_KEYS`）。確認項目は §8-1・2・4。
