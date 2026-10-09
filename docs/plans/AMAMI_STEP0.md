# 奄美大島（jp-46）Step 0：zone の共通定義と土台（設計書）

- 状態: 設計（実装前。2026-10-10 に §8 の決定を反映して改訂）/ 日付: 2026-10-10 / Issue #89 の Step 0（ブランチ `feat/amami-step0`）
- この PR では奄美のデータそのものは取り込まない。やるのは次の6つ。
  (1) zone を神奈川・奄美で共通の定義（v2）に差し替える　(2) 海岸線を手描き折れ線から国土数値情報 C23 に切り替える
  (3) 地点への zone 割り当てを「座標から判定する仕組み」に作り直す　(4) `jp-46` を足し、収集の定数を1か所に持たせる
  (5) 鹿児島県サイト PDF・希少種の位置・C23・標高タイルの扱いを文書に決める　(6) 上の変更が CI の sample-gate を通るようにする
- 実装担当ごとに読む節: **担当A**=§0・§3・§6-A、**担当B**=§0・§1・§2・§3・§6-B、**担当C**=§0・§4・§5・§6-C。
  統合（メイン）=§7・§8。**サブエージェントやスキルを起動しない・重い検証（b00 全量・build:v2・serving snapshot 全量・db:setup）を回さない**のは全担当共通（§6 冒頭）。

## 0. 前提（オーナーが決めた。蒸し返さない）

1. zone（Ridge to Reef 1〜5）を神奈川・奄美で**共通の定義**にする。番号と名称は保つ（3 の名称だけ「丘陵・台地・扇状地」にする）。標高 800/400/100m・海岸 2km の絶対閾値はやめる。
2. 海岸線は C23（国土数値情報 海岸線）に置き換える。神奈川も今回切り替え、`scripts/m01_sites.py` の手描き `COASTLINE_LONLAT` は撤去する。許諾は「非商用」（W05 等と同じ扱い）。
3. 地点への zone の割り当ては、旧 `sites.zone` 列を写すのではなく、座標から判定する。対象の地点の集合は今と同じ。Issue #86（観測局など143局に流域・zone が無い）はこの PR で解決しない。
4. 鹿児島県サイトの PDF は事実（数値・種名）を抽出し、出典の URL を明記して取り込む。PDF 自体は再配布しない。
5. 希少種の位置は GBIF・iNaturalist 等の公開元が丸めた座標をそのまま使う（こちらで細かく起こさない）。ロードキルの地点図は使わない。ADR-0028 と矛盾しない。
6. 地域の追加は `registry/region.yaml` に `jp-46` を足す。収集の定数は神奈川と同じ形で1か所に持たせ、値ではなくリストで持つ。
7. （改訂で追加）zone 1/2 は W12 に依存させず、`region.yaml` に宣言した地域の最高峰の半分で分ける。zone 4 の基準は周囲2kmの最低標高。zone の place は `common:place:zone.r2r.N`（ID に版を入れない）。島で zone 2 が大半になることは受け入れて注記する。台帳の `sites.zone` は m0x の流儀で更新する。c68 は W12 を読まない（地点→流域は #86）。


## 1. zone v2 の定義

### 1.1 判定規則（`definition_version: 2`）

入力は地点の座標から c68（§3）が計算して `data/processed/terrain_points.csv` に置く指標と、地域の最高峰（`registry/region.yaml` の宣言値）だけ。ビルドの段階では標高タイルも海岸線ポリゴンも W12 も読まない。

```
def classify(m, p, ledger_elevation_m=None):   # m: terrain_points.csv の1行、p: registry/place/zone.yaml の rule:。実装は (zone, reason) を返す
    e = m.elevation_m if m.elevation_m is not None else ledger_elevation_m   # DEM が無効（海の画素）なら台帳 sites.elevation_m
    if e is None: return None                                  # どちらも無ければ zone を付けない（推測しない）
    # --- 5: 河口・沿岸（地形の種類より先に見る。海に落ちる急斜面の麓も沿岸）
    if m.coast_dist_m is not None and m.coast_dist_m <= p.coast_dist_max_m and e <= p.coast_elev_max_m:   # 2000m, 10m
        return 5
    if m.relief_wide_m is None: return None                    # 5 は標高と海岸距離だけで決まる。5 に当たらず起伏量も無いときだけ None
    # --- 1/2: 山地（周囲 1km の起伏量 200m 以上）。標高が地域の最高峰の半分以上なら 1、未満なら 2
    if m.relief_wide_m >= p.mountain_relief_min_m:
        return 1 if e >= p.summit_ratio_min * m.summit_m else 2                                         # 0.5。m.summit_m は点の region の宣言値
    # --- 3/4: 山地でない場所。低地(4)の条件を3つとも満たせば 4、そうでなければ 3
    if m.floor_min_m is None: return 3
    if e <= p.lowland_elev_max_m and m.relief_near_m <= p.lowland_relief_max_m \
       and e - m.floor_min_m <= p.lowland_above_floor_max_m:                                             # 100m, 30m, 15m
        return 4
    return 3
```

W12 の面には依存しない（地点→流域は Issue #86 の別件）。`summit_m` は `terrain_points.csv` の列で、c68 が地点の region（出典のマニフェストの region。確認地点は yaml の `region`）の `region.yaml: terrain.summit.elevation_m` を写す。

名称と条件（`zone.yaml` の `zones:`。`condition_ja` は `definition_ref` の一文用、`ui_condition_ja` は画面・AI 用の短い表記。数値を直すときは `rule:` と両方の文言を手で揃え、揃っているかを検査するテストを置く〔§6-B〕）:

| zone | 名称 | 条件（画面用の短い表記） |
|---|---|---|
| 1 | 山地源流域 | 山地（周囲1kmの起伏量200m以上）で、標高が地域の最高峰の半分以上 |
| 2 | 山地渓流 | 山地で、標高が地域の最高峰の半分未満 |
| 3 | 丘陵・台地・扇状地 | 山地でも低地でもない場所 |
| 4 | 平野・沖積低地 | 標高100m以下・周囲250mの起伏量30m以下・周囲2kmの最低点から15m以内（山地でも沿岸でもない） |
| 5 | 河口・沿岸 | 海岸から2km以内かつ標高10m以下 |

`zone.yaml` に**地域共通の注記**を1つ置く（`note_ja`。画面・caveat から引ける文）: 「zone は地形から機械的に付けた操作的区分で、公式の区分ではない。標高の低い島（奄美大島など）では山地（zone 2）が陸の大半を占め、低地（zone 4）はほとんど現れない。これは定義の結果で、凡例・名称は地域によらず共通である。」

### 1.2 指標の定義（c68 が計算する。`zone.yaml` の `terrain:` が定義パラメータ）

| 列 | 意味 | 計算 |
|---|---|---|
| `region_id` `summit_m` | 点の region と、その地域の最高峰の標高 | `region.yaml` の `terrain.summit.elevation_m`（宣言値。DEM の最大から導出しない） |
| `elevation_m` | 標高 | 地理院 `dem_png`（DEM10B）z14 の座標を含む画素。復号は x=65536R+256G+B、x<2^23 なら h=0.01x、x≥2^23 なら 0.01(x−2^24)、(128,0,0) は無効（海・欠測）。無効なら空 |
| `relief_wide_m` | 周囲 1km の起伏量 | 半径 `relief_wide_radius_m`=1000 m の円内の有効画素の 最高−最低（海の画素は除く） |
| `relief_near_m` | 周囲 250m の起伏量 | 同、半径 `relief_near_radius_m`=250 m |
| `floor_min_m` | 周囲 2km の最低標高 | 半径 `lowland_floor_radius_m`=2000 m の円内の有効画素の最低標高。**z12 タイル（`floor_dem_tile_zoom`=12、1画素約38m）でよい**。海の画素は除く（海岸の低地は海面〔0m〕でなく陸の最低点が基準になる） |
| `coast_dist_m` | 海岸線までの距離 | C23 の線への最短距離。緯度の cos で経度を縮めた局所平面で測る（神奈川・奄美の範囲で誤差 1% 未満）。その地域の C23 が無ければ空 |
| `params_digest` | `terrain:` ブロックの sha256 先頭12桁 | ビルド側が `zone.yaml` の現在値と照合し、違えば止まる（指標の定義を変えたのに c68 を回し直していない状態を防ぐ） |

キーは `(lat, lon)`（小数6桁に丸めた文字列）。同じ座標の地点は1行を共有する（神奈川の対象290地点で242行）。

**最高峰の宣言と検査**: `registry/region.yaml` の各 region に `terrain.summit`（`name_ja`・`lat`・`lon`・`elevation_m`）を宣言する。`jp-14` は蛭ヶ岳 1673m（座標は暫定で 35.4863, 139.1389。**担当Cが地理院地図で確認して確定**）、`jp-46` は湯湾岳 694m（暫定 28.2963, 129.3209）。c68 は宣言座標の周辺 500m の DEM 最大が宣言値 ±20m に収まるかだけを検査し、外れれば止まる（今回の実測: 蛭ヶ岳 1672m・湯湾岳 692m で収まる）。`migrate/regions.py` の `region_problems()` は `terrain` があれば形（4キーの型）を検査する。`terrain` の無い region はそのまま通る（既存のテストのフィクスチャを壊さない）が、zone を付ける地域〔c68 の対象〕では必須。

### 1.3 パラメータと根拠（`zone.yaml`）

| キー | 値 | 根拠・感度 |
|---|---|---|
| `terrain.dem_tile_zoom` | 14 | dem_png の最高ズーム。画素 約8m（北緯35°）・約8.4m（北緯28°） |
| `terrain.floor_dem_tile_zoom` | 12 | 最低点の探索は広い（半径2km）ので粗い画素で足りる。取得枚数が約1/16 |
| `terrain.relief_wide_radius_m` | 1000 | オーナー方針「周囲 1km の起伏量が 200m」。J-SHIS の微地形区分で山地を起伏量で分ける考え方に合わせた（J-SHIS のデータそのものは使わない）。半径 500m（1km 四方の窓）と読むと神奈川の山地(2)は 51→23 件に減る（宮ヶ瀬湖の地点が山地から外れる）。山間のダム湖・渓流の地点を山地に入れたいので 1000m |
| `terrain.relief_near_radius_m` | 250 | 低地の「平らさ」。500m だと台地の縁の崖を拾って、段丘崖に接する低地が丘陵になる |
| `terrain.lowland_floor_radius_m` | 2000 | 「低地」の基準になる最低点を探す半径。**3000m にしても神奈川の zone 4 は124→118 件（4→3 が6地点）で、確認地点の結果は変わらない**。相模大野（川が遠い台地）は 2km の最低点との比高 27m で 3 のまま漏れない |
| `rule.coast_dist_max_m` / `coast_elev_max_m` | 2000 / 10 | オーナー方針。標高10mの上限で、海に落ちる斜面の中腹は沿岸にならない |
| `rule.mountain_relief_min_m` | 200 | オーナー方針。150/200/250 で神奈川の山地(2)は 61/51/39 件 |
| `rule.summit_ratio_min` | 0.5 | 山地の中で 1 と 2 を分ける、地域の最高峰に対する標高の比。0.4/0.5/0.6 で神奈川の zone 1 は 7/4/2 件（旧 zone 1 の4地点が全て残るのは 0.5 まで）。神奈川は約837m以上、奄美は347m以上が 1 |
| `rule.lowland_elev_max_m` | 100 | 沖積低地は海面を基準に堆積した地形で、海面から離れた高所の平坦面は低地とみなさない。旧 zone 4 の上限（100m）を引き継ぐ。これが無いと箱根カルデラ底（芦ノ湖の湖面、標高約725m、周囲2kmの最低点との比高26m）が低地になる |
| `rule.lowland_relief_max_m` | 30 | 250m窓の起伏量 |
| `rule.lowland_above_floor_max_m` | 15 | 周囲 2km の最低点からの比高。台地（大和 17m・相模大野 27m・相模原 35m）と沖積低地（寒川 13m・厚木 10m・足柄 8m）が分かれる境が 15〜17m。境ぎりぎり（大和 17m・日吉 18m・開成 18m）は 3 側に倒れる |

### 1.4 計測の結果

条件: 2026-10-10 に再計測（W12 を外した最終の定義）。標高タイルは z14 が677枚・z12 が約140枚（1.6秒間隔で取得、スクラッチにキャッシュ）、C23 は平成18(2006)年版 `C23-06`（神奈川 597本、奄美5市町村 1,071本）。計測スクリプトはスクラッチにあるだけで、リポジトリには入れない（再現は担当Aの c68）。

**(a) 神奈川の zone 付き地点290（242座標）の旧→新**

| 旧＼新 | 1 | 2 | 3 | 4 | 5 | 付かない |
|---|---|---|---|---|---|---|
| 1 | 4 | 0 | 0 | 0 | 0 | 0 |
| 2 | 0 | 5 | 6 | 0 | 0 | 0 |
| 3 | 0 | 45 | 11 | 0 | 0 | 0 |
| 4 | 0 | 1 | 41 | 114 | 11 | 0 |
| 5 | 0 | 0 | 4 | 10 | 37 | 1 |

一致172、変更118、新しい件数は 1:4 / 2:51 / 3:62 / 4:124 / 5:49 / なし:0（レビュー後。DEM が無効な地点は台帳の標高で zone 5 を判定する）（旧は 4/11/56/167/52）。

**(b) 変わった118地点の内訳（宣言済みの差分の理由）**

| 旧→新 | 件数 | 理由 |
|---|---|---|
| 3→2 | 45 | 周囲1kmの起伏量200m以上（山間のダム湖・渓流。標高100〜400mでも山地） |
| 4→3 | 41 | 250m窓の起伏量30m超が21、2km窓の最低点から15m超が20（丘陵・台地・扇状地側に倒れる。報徳橋＝酒匂川の扇状地など） |
| 4→5 | 11 | 手描き海岸線より C23 の方が2km以内に入る（旧は手描きの折れ線が実際の海岸から離れていた） |
| 5→4 | 10 | 旧は手描きで2km以内だったが C23 では2km超（多摩川の大師橋・六郷橋など。C23 までの距離 4〜5km）、または吉田橋のように標高10m超 |
| 5→3 | 4 | 標高10m超かつ250m窓の起伏が大きい（江ノ島 54m など） |
| 2→3 | 6 | 山地の条件を外れ、標高100m超で 4 にもならない（芦ノ湖の湖面の6地点〔湖央・湖西・湖東〕。弱点 §1.5-3） |
| 4→2 | 1 | 起伏量200m以上（山間） |
| （5→なし） | 0 | レビュー後に解消。平潟湾内の地点は DEM が無効（海）だが、台帳の標高で 5 のまま |

**(c) C23 と手描き海岸線の違い**: 290地点の海岸距離の差は中央値 0.8km・90%点 2.7km・99%点 4.0km。2km 境をまたぐ地点が23（8%）。手描き折れ線（20点）は東京湾岸の入り組んだ形を省いていた。

**(d) 神奈川の地形の確認30地点**（専門家に見てもらう表。「2km窓」は標高−周囲2kmの最低点、「3km窓」は同3km。期待の集合は設計担当の地理知識）

| 地点 | 緯度,経度 | 標高m | 起伏量1km | 起伏量250m | 海岸距離m | 2km窓の最低点からの比高m | 3km窓 | zone | 期待 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| 丹沢山頂(蛭ヶ岳付近) | 35.4863, 139.1389 | 1672 | 628 | 188 | 23635 | 898 | 1040 | 1 | 1 | ○ |
| 大山山頂付近 | 35.4408, 139.2312 | 1252 | 594 | 191 | 16230 | 874 | 1004 | 1 | 1/2 | ○ |
| 神山(箱根) | 35.2334, 139.0209 | 1437 | 451 | 159 | 11026 | 731 | 930 | 1 | 1 | ○ |
| 芦ノ湖畔(箱根) | 35.2013, 139.0256 | 724 | 211 | 22 | 10205 | 26 | 236 | 2 | 2/3 | ○ |
| 相模湖(山間) | 35.6133, 139.1933 | 183 | 275 | 40 | 35490 | 54 | 55 | 2 | 2/3 | ○ |
| 宮ヶ瀬湖 | 35.5200, 139.2300 | 303 | 228 | 56 | 24657 | 18 | 165 | 2 | 2/3 | ○ |
| 相模野台地(大和市) | 35.4678, 139.4605 | 61 | 21 | 4 | 15632 | 17 | 22 | 3 | 3 | ○ |
| 相模野台地(相模大野) | 35.5314, 139.4373 | 90 | 22 | 7 | 19033 | 27 | 43 | 3 | 3 | ○ |
| 下末吉台地(鶴見) | 35.5128, 139.6572 | 41 | 39 | 17 | 3229 | 39 | 41 | 3 | 3 | ○ |
| 三浦丘陵(武山付近) | 35.2203, 139.6657 | 76 | 184 | 151 | 2242 | 67 | 76 | 3 | 3 | ○ |
| 相模川低地(寒川) | 35.3733, 139.3886 | 16 | 26 | 8 | 6253 | 13 | 13 | 4 | 4 | ○ |
| 相模川低地(厚木) | 35.4390, 139.3640 | 20 | 16 | 1 | 13566 | 10 | 10 | 4 | 3/4 | ○ |
| 酒匂川扇状地(開成) | 35.3236, 139.1197 | 40 | 47 | 5 | 9008 | 18 | 20 | 3 | 3/4 | ○ |
| 足柄平野(小田原飯泉) | 35.2850, 139.1550 | 16 | 30 | 1 | 3713 | 8 | 10 | 4 | 3/4 | ○ |
| 平塚 馬入(河口) | 35.3338, 139.3472 | 7 | 8 | 3 | 2143 | 5 | 7 | 4 | 5 | **×**（`known_miss`: 海岸まで2143m。座標が河口の約2km上流で、規則の境の問題） |
| 横浜 山下公園 | 35.4437, 139.6503 | 3 | 42 | 12 | 215 | 3 | 3 | 5 | 5 | ○ |
| 相模原台地(中央区) | 35.5715, 139.3733 | 125 | 12 | 3 | 26089 | 35 | 45 | 3 | 3 | ○ |
| 座間 台地 | 35.4376, 139.4318 | 42 | 28 | 13 | 13100 | 24 | 27 | 3 | 3 | ○ |
| 湘南台(藤沢台地) | 35.3938, 139.4678 | 34 | 22 | 6 | 8496 | 22 | 25 | 3 | 3 | ○ |
| 日吉(下末吉台地) | 35.5546, 139.6469 | 22 | 33 | 20 | 7543 | 18 | 18 | 3 | 3 | ○ |
| 衣笠(三浦丘陵) | 35.2635, 139.6538 | 47 | 84 | 49 | 2231 | 41 | 47 | 3 | 3 | ○ |
| 初声(三浦台地) | 35.1835, 139.6465 | 36 | 58 | 27 | 796 | 36 | 36 | 3 | 3 | ○ |
| 麻生(多摩丘陵) | 35.6000, 139.5000 | 50 | 56 | 33 | 18420 | 20 | 25 | 3 | 3 | ○ |
| 新横浜(鶴見川低地) | 35.5071, 139.6177 | 9 | 38 | 25 | 3646 | 4 | 5 | 4 | 4 | ○ |
| 酒匂(酒匂川デルタ) | 35.2715, 139.1760 | 9 | 10 | 3 | 1453 | 9 | 9 | 5 | 4/5 | ○ |
| 茅ヶ崎 柳島(相模川下流) | 35.3190, 139.3660 | 4 | 11 | 7 | 490 | 4 | 4 | 5 | 4/5 | ○ |
| 溝の口(多摩川低地) | 35.6001, 139.6101 | 19 | 33 | 20 | 13319 | 10 | 11 | 4 | 4 | ○ |
| 藤沢 境川低地 | 35.3420, 139.4700 | 10 | 48 | 10 | 2923 | 6 | 10 | 4 | 4 | ○ |
| 山北(丹沢山麓) | 35.3600, 139.0800 | 113 | 250 | 39 | 14353 | 40 | 52 | 2 | 2/3 | ○ |
| 相模原 津久井(山間) | 35.6000, 139.2200 | 201 | 147 | 69 | 33328 | 76 | 76 | 3 | 2/3 | ○ |

29/30 が期待どおり。期待外の1件（平塚馬入）は規則の境界の問題で、`known_miss` として明示してテストに残す（§6-B）。W12 を外す前は溝の口も ×（比高16m）だったが、最低点の基準を周囲2kmの画素にすると 10m で 4 になった。

**(e) 奄美の確認13地点**（座標は標高タイルで山頂・海岸の画素に寄せた値。最高峰は 694m を宣言）

| 地点 | 緯度,経度 | 標高m | 起伏量1km | 起伏量250m | 海岸距離m | 2km窓の最低点からの比高m | 3km窓 | zone | 期待 | 判定 |
|---|---|---|---|---|---|---|---|---|---|---|
| 湯湾岳山頂 | 28.2963, 129.3209 | 692 | 430 | 108 | 2960 | 572 | 690 | 1 | 1 | ○ |
| 金作原 | 28.3167, 129.4119 | 213 | 338 | 169 | 4172 | 200 | 205 | 2 | 1/2 | ○ |
| 住用 山地(中腹) | 28.2730, 129.4450 | 360 | 446 | 177 | 1022 | 360 | 360 | 1 | 1/2 | ○ |
| 住用マングローブ(河口) | 28.2954, 129.4500 | 6 | 342 | 131 | 97 | 6 | 6 | 5 | 5 | ○ |
| 名瀬市街 | 28.3772, 129.4939 | 8 | 236 | 55 | 478 | 8 | 8 | 5 | 5 | ○ |
| 新川河口付近 | 28.3790, 129.4930 | 5 | 228 | 9 | 315 | 5 | 5 | 5 | 5 | ○ |
| 龍郷湾岸 | 28.3996, 129.5243 | 6 | 230 | 96 | 152 | 6 | 6 | 5 | 5 | ○ |
| 大和村 大和浜 | 28.3241, 129.2944 | 6 | 358 | 131 | 360 | 6 | 6 | 5 | 5 | ○ |
| 古仁屋 | 28.1415, 129.3185 | 3 | 226 | 82 | 59 | 3 | 3 | 5 | 5 | ○ |
| 宇検村 湯湾 | 28.2718, 129.2956 | 6 | 270 | 57 | 125 | 6 | 6 | 5 | 5 | ○ |
| 笠利(奄美空港付近) | 28.4306, 129.7125 | 4 | 25 | 4 | 152 | 4 | 4 | 5 | 3/4/5 | ○ |
| 大川ダム付近 | 28.3300, 129.3700 | 325 | 343 | 136 | 2741 | 306 | 325 | 2 | 2/3 | ○ |
| 笠利 丘陵(内陸) | 28.4280, 129.6880 | 121 | 171 | 95 | 1509 | 121 | 121 | 3 | 3 | ○ |

13/13。最高峰の比 0.5 により、奄美の zone 1/2 は「標高347m以上か未満か」。

**島の陸の画素全体での配分**（奄美大島・加計呂麻島・請島を含む緯度28.08〜28.58・経度129.15〜129.80の陸の画素を、z12 の 300m 間隔で11,131点。W12 の範囲ではない）: zone 1: 5.7% / 2: 73.3% / 3: 13.2% / 4: 0.2% / 5: 7.6%。z12 で計算した結果は、確認13地点で z14 の結果と全て一致した。**島では zone 2 が大半を占め、zone 4 はほぼ消える**（Issue の想定どおり。受け入れて `zone.yaml` の注記に書く）。

**(f) 感度**（神奈川290地点）: 最高峰比 0.4/0.5/0.6 で zone 1 は 7/4/2 件・一致は 168/171/169。最低点の半径 2km→3km で zone 4 は124→118、一致は171→167（4→3 が6地点、確認地点は不変）。

### 1.5 弱点と専門家レビューで確かめる点

1. **標高は DEM10B（10m 格子）の画素**。橋・堤防・盛土の標高が入るので、河川の水質点は河床より高く出る。zone 5 の「10m 以下」の境付近の地点（旧 5→4 の10件など）が動く。
2. **1/2 の境は「地域の最高峰の半分」という宣言値1つに依存する**。最高峰が違う地域どうしで zone 1 の標高が違う（神奈川約837m、奄美347m）。これが「共通の定義」の意味であり、同時に弱点でもある。山地の中の尾根・谷・流域内の位置は見ていない（流域は Issue #86 の別件）。
3. **標高100m 超の平坦面を 4 にしない**ため、箱根カルデラ底（芦ノ湖の湖面の6地点）が 3（丘陵・台地・扇状地）になる。山地性の高所平坦面の扱いは専門家に聞く。
4. **3/4 の境（台地と沖積低地）は成因による分類ではなく、起伏と周囲2kmの最低点からの比高による代理**。大和・日吉・開成は境ぎりぎり。扇状地は 3 にも 4 にもなる。海に近い低地は、最低点が海の画素を含まないため基準が陸の最低点になる。
5. 期待の集合（§1.4-d/e）は設計担当の知識で置いた。**水野研（または地形に詳しい人）に確かめてもらうこと**: (a) 山地を「周囲1km の起伏量200m」で切るのは奄美の低く急な山（最高694m）でも妥当か、(b) 最高峰の半分で 1/2 を分けてよいか、(c) 海岸 2km・10m は奄美のリアス式海岸・サンゴ礁の地形に合うか、(d) zone 3 に台地・丘陵・扇状地をまとめてよいか。
6. 海の画素は DEM 無効なので、起伏量は陸の画素だけで計算する。岬・海崖で窓の海側が欠け、起伏量が小さめに出る。
7. C23 は平成18年版で、その後の埋立・護岸は入っていない。
8. 座標が海上・湾内の地点は DEM が無効。台帳の標高と海岸距離で zone 5 は付くが、起伏量が無いので 5 に当たらなければ zone が付かない（神奈川で0〜1件。台帳の標高を使う規則は実装後の修正で入れた）。

## 2. zone の place のスコープ: `jp-14` から `common` に移す（決定）

**移す（決定）。** `jp-14:place:zone.r2r.N` → `common:place:zone.r2r.N`（N=1〜5。`region_id` は NULL）。

理由:
- 定義が地域に依存しなくなった。zone 1〜5 は神奈川の地点からも奄美の地点からも同じ5つの place を指す。ADR-0004 規約0（地域固有でないもの・判断に迷うものは `common`）と ADR-0022 決定1（`common` は `region_id=NULL`）にそのまま当てはまる。Phase A で `jp-14` に置いたのは「対象地域が神奈川だけだったから」で、定義が神奈川固有だったからではない。
- 移さない場合の選択肢は2つとも悪い。(i) 奄美の地点が `jp-14` スコープの zone を指す → `region_id` が神奈川の place を鹿児島の地点が参照する。(ii) `jp-46:place:zone.r2r.N` を別に作る → `place_source_ref(key_space='zone', external_key='1')` が2つになり、キューブのゾーン絞り込み（`web/src/lib/cube/sql.ts` の `zref.key_space='zone'` と番号の一致）が二重に数える。`docs/add_area.md` §7 の申し送り「zone 番号が地域間で衝突する」も、共通 place にすれば起きない。

ADR-0004 規約2 は「`jp-14:` → `common:` のスコープ変更は ID の変更」と書いており、**規約0 によりそもそも起こさない**と定める。ここで起こすのは規約0の想定外の「定義が地域非依存になった」場合なので、規約を守る形で行う。

| 効くところ | 変わるか | 対応 |
|---|---|---|
| `registry/id_map/place.csv` | 変わる。旧 `jp-14:place:zone.r2r-N`（既存10行〔5件〕の `new_id`）と `jp-14:place:zone.r2r.N` を `common:place:zone.r2r.N` に向ける。旧 ID は再利用しない（ADR-0004 規約2）。r01 が「宣言と現行 ID の一致・1対1・再利用なし」を検査して止める | 担当B。理由は「ADR-0031: zone を地域非依存の定義にしたためスコープを common に」、`spec_version` は `2026-10-zone-v2` |
| `place` / `place_relation.parent_id` / `place_source_ref.place_id`（D1 に載る） | place_id の文字列と、zone の `region_id` が NULL になる | 担当B（`build_place.py` の `PLACE_SCOPE` を zone だけ `common` に。`registry/place/key_space.yaml` の zone は変更なし） |
| `web/src/lib/registry/generated-id-map.ts`（`LEGACY_PLACE_ID_MAP`） | 再生成で zone の行の `new_id` が変わる | 統合（`pnpm run build:registry`）。画面・API は zone を `place_source_ref.external_key`（番号）で引くので挙動は変わらない |
| API / MCP / 画面 / AI の出力 | **変わらない**。ZONE_INFO は `zone.yaml` の番号と名称、キューブの絞り込みは番号。`data/sample/serving_snapshot.json` に `place:zone` の文字列は無い（0件） | 差分は zone の分類結果の変化（§1.4）だけ |
| 既存テスト・フィクスチャ | `scripts/tests/test_registry_place.py`（27・92・112〜114行）、`test_r01_invariants.py`（118〜121行）の `jp-14:place:zone` | 担当Bが直す。`test_place_id_grammar.py`・`parse-id.test.ts` は文法の例なので触らない |
| ADR | ADR-0022 決定1の実測表（`jp-14 zone 5`）が古くなる。ADR-0004 規約0 の表（66行目付近）の例 `jp-46-tatsugo:place:zone.r2r.3`「地域固有の操作的定義」も古くなる | ADR-0031 に「ADR-0022 の実測表の zone 行は `common` に移った」と追記（ADR-0022 本体は書き換えない）。**ADR-0004 には日付付きの追記を足す（担当B）**: 「zone の定義が地域非依存になったため `jp-14:place:zone.r2r.N` を `common:` に昇格した。これは別の実体への置換ではなく同じ実体の ID の改称なので `id_map` で扱い、`superseded_by` は使わない。規約0 の表の `jp-46-tatsugo:place:zone.r2r.3` の例は古くなった」。本文の表は書き換えない |

zone の定義が変わったことは place_id に入れない（`common:place:zone.r2r.N` のまま。**決定**）。定義の版は `place.definition_ref` と `place_relation.basis` に `definition_version: 2` として残す。ID 文法に版を入れる案（`r2r2`）は、v1 の zone を参照する外部の引用が存在せず（v1 の API は撤去済み）、ID を変える理由が「スコープ移動」だけで足りるので採らない。

## 3. データの流れ

```
[収集: ネットワークに出てよい。1.5秒間隔]
  c36_nlni_c23_coastline.py ─ C23 zip（神奈川14・鹿児島46）→ data/raw/ → data/processed/nlni_c23_coastline.geojson
                               （鹿児島は regions.py の市町村コード5つで絞る。神奈川は全線）
  c68_gsi_dem_terrain.py    ─ 入力: ryuiki.sqlite の sites（zone 対象 = elevation_m IS NOT NULL の座標、読み取り専用）
                                   + nlni_c23_coastline.geojson + registry/region.yaml の terrain.summit + zone.yaml の terrain:
                                   （W12 は読まない）
                              取得: dem_png z14（座標の周囲1.1km を含むタイル）と z12（周囲2.1km を含むタイル）→ data/raw/gsi_dem_png/{z}/{x}/{y}.png に保存（再取得しない）
                              検査: 宣言した最高峰の座標の周辺500mの DEM 最大が宣言値±20m に収まるか（外れたら止まる）
                              出力: data/processed/terrain_points.csv（§1.2）   ※ ここだけがビルドの入力。コミットしない（data/* は .gitignore）
[ビルド: ネットワークに出ない]
  m01_sites.py        ─ sites 台帳（zone は書かない。NULL）
  m09_site_zone.py    ─ terrain_points.csv + zone_rule で原本 sites.zone を更新（m0x が原本を書く既存の流儀。台帳の zone 列を web が読むため）
  r01 → build_place.py ─ 同じ terrain_points.csv + 同じ zone_rule で place_relation（地点→zone）を作る。台帳の sites.zone と食い違えば止まる
  b03 … b13 (build:v2) ─ zone を読まない。registry の指紋が変わるので鮮度判定で作り直しになるだけ（出力は不変）
```

**どこで何を計算するか**
- 標高・起伏量・周囲2kmの最低点・海岸距離は**収集段階（c68）**でだけ計算する。標高タイルの取得もここだけ。ビルドは `terrain_points.csv` の数字を `rule:` の閾値と比べるだけの純関数（`scripts/registry/zone_rule.py` の `classify()`。m09・build_place・テストが同じ関数を使う）。
- 閾値（`rule:`）を変えても c68 は回し直さない。窓の半径・タイルのズーム（`terrain:`）を変えたら c68 を回し直す。`params_digest` の不一致でビルドが止まるので忘れない。最高峰（`region.yaml`）を変えたときは、`summit_m` 列が古くなるので、ビルドが `region.yaml` の現在値と csv の `summit_m` を照合して止まる（c68 を回し直す）。
- zone の判定は `build_place.py`（`_zone_relation_rows()` の入力を `classify()` の結果に変える）。対象は `sites` のうち `elevation_m IS NOT NULL` の行（今の `zone IS NOT NULL` と同じ集合、290件）。`site_supplement.csv` の補完地点と観測局は今回も対象外（Issue #86）。座標の組が `terrain_points.csv` に無い対象地点があれば、黙って捨てず地点を列挙して止める（「c68 を回して」）。
- 旧 `sites.zone` を読むのは検査のためだけ: `build_place` は `classify()` の結果と台帳の `sites.zone` が全地点で一致することを確かめ、違えば止まる（m09 の回し忘れの検知）。
- **m01 は zone を書かなくなる**（`COASTLINE_LONLAT`・`dist_to_coast_m`・`zone_of` を撤去。INSERT は `zone=NULL`）。m01 を再実行したら m09 を続けて回す。順序: c36 → c68 → m01 → m09 → r01。新しい地点が増えたときも c68 → m09 の順（c68 は台帳の座標から対象を決める）。この順序は `docs/PIPELINE.md` の「取り込み・レジストリ」に1行足す（担当C）。
- **m09 の仕様**（`m07` は `m07_kanagawa_edna.py` で使用済みなので `scripts/m09_site_zone.py`）: (a) `--dry-run`（原本を書かず、旧→新のクロス表と変更地点を標準出力に出す）。(b) 書き換える前に、対象の全地点について旧→新の一覧 `reports/zone_v2_migration.csv`（`site_id,zone_v1,zone_v2,elevation_m,relief_wide_m,relief_near_m,coast_dist_m,floor_min_m,reason`）を書き出す。これが**宣言済みの差分**（コミットする。`reason` は §1.4-b の理由コード）。`zone_v1` は、csv が既にあればその値を保持し（2回目の実行で v2 を v1 と取り違えない）、無ければ現在の `sites.zone`。(c) 冪等（同じ入力で2回回しても csv・原本が変わらない）。`--report` は Markdown のクロス表を出す。

**鮮度判定と b00**
- `terrain_points.csv` を `scripts/registry/common.py` の `compute_input_fingerprint()`（`MODE_FULL` のみ。`nlni_w12_watersheds.jsonl` と同じ扱い）に混ぜる。`zone.yaml`・`region.yaml`・`id_map`・`zone_rule.py` は `registry/` と `scripts/registry/*.py` の既存の glob に入っているので追加不要。
- `compute_v2_input_fingerprint()` は `registry.input_fingerprint`（registry.sqlite 自身の指紋）を既に含むので、**そのままで** terrain_points の変更が v2 の鮮度判定に伝わる（`V2_PROCESSED_FILES` には足さない。b03〜b13 は zone を読まない）。ただし原本 `ryuiki.sqlite` の `sites.zone` は指紋に入らない既知の限界のまま（m09 を回したら `pnpm run build:registry` を明示する。`docs/PIPELINE.md` に書く）。
- `scripts/pipeline_inputs.py` の `SOURCE_FILE_KEYS` に `data/processed/terrain_points.csv` を足す（`data/sample/coverage.yaml` の `wholesale_processed_files` と同じ集合であることを `test_pipeline_inputs.py` が見る）。`scripts/pipeline_inputs.py` は `PIPELINE_EXPLICIT_FILES`、`scripts/registry/` と `registry/` は `PIPELINE_DIRS` に入っているので、**b00 の全量ゲートを回し直して `reports/serving_fingerprint.json` をコミットする**（統合・§7）。
- ネットワークに出ないことの検査: `build_place`・`classify()` をソケット接続を禁止（`socket.socket.connect` を例外にする）した状態で `terrain_points.csv` のフィクスチャに対して動かすテストを置く（担当B）。

**CI の sample-gate に要るもの**（サンプルには原本が無いので、入力は `data/sample/` に入れる）
1. `data/sample/coverage.yaml` の `wholesale_processed_files` に `terrain_points.csv` を足す（全行を丸ごとコピー。約250行）。`s02_materialize_sample.py` が `data/processed/` に展開する。
2. サンプルの `data/sample/ryuiki/sites.sql` の `zone` 列は v2 の値で作り直す（`s01_build_sample.py` を原本のある手元で実行。m09 を先に回しておく）。`data/sample/manifest.json` のハッシュ、`data/sample/serving_snapshot.json` も更新する（統合）。
3. C23・標高タイルはサンプルに入れない（ビルドは読まない）。
4. `registry` ジョブ（`r01 --files-only`、原本を開かない）は `zone.yaml`・`region.yaml` だけで通ること。担当C の `build-registry-ts.mjs` が新しい `zone.yaml` の構造を読めること。

## 4. region `jp-46` と収集の定数

**`registry/region.yaml`** に `jp-46` を足す（`name_ja: 鹿児島県`、`tz_name: Asia/Tokyo`、`utc_offset: "+09:00"`、`evidence` は ADR-0002 のコードリストの鹿児島県。当面のデータの範囲は奄美大島5市町村）。`region.yaml` には**収集の定数は入れない**（`registry/` 配下は全ファイルが registry の指紋に入り、定数を直すたびに registry と D1 が作り直しになるため）。一方、**地域の最高峰は zone の判定に使う分類上の宣言**なので `region.yaml` に置く: 各 region に `terrain.summit`（`name_ja`・`lat`・`lon`・`elevation_m`）。`jp-14` は蛭ヶ岳 1673m、`jp-46` は湯湾岳 694m（座標は §1.2。DEM の最大から導出しない。c68 が宣言座標の周辺500mの DEM 最大が宣言値±20mに収まるかだけを検査する）。`migrate/regions.py` の `region_problems()` は `terrain` があれば形を検査し、無ければ通す（既存の `region.yaml` フィクスチャを壊さない）。`build_region.py` は `terrain` を読まない（registry.sqlite・D1 の `region` 表の列は増やさない。`generated-client.ts` へも出さない）。zone を付ける地域には必須で、c68 が `terrain.summit` の無い region の地点で止まる。

**収集の定数は `scripts/regions.py` の1か所**（`docs/add_area.md` §4 Step 1 が予告していたファイル。`region_id` をキーにした辞書。値は全てタプル/リスト）:

| フィールド | `jp-14`（神奈川。既存コードの定数を転記） | `jp-46`（奄美大島） |
|---|---|---|
| `name_ja` | 神奈川県 | 鹿児島県（奄美大島） |
| `pref_code` | `"14"` | `"46"` |
| `muni_codes`（None=県全域） | None | `("46222","46523","46524","46525","46527")` |
| `gbif_gadm_gids` | `("JPN.19_1",)`（`c02_gbif.py` の `GADM`） | `("JPN.18.4_1","JPN.18.38_1","JPN.18.41_1","JPN.18.44_1","JPN.18.34_1")` ※Issue の記述は `.4_1`/`.38`/`.41`/`.44`/`.34` の形。末尾の `_1` と区切りは **GBIF で1件取得して確かめてから確定**（§1 Step 1 の規約） |
| `inat_place_ids` | `(10918,)`（`c03_inaturalist.py` の `PLACE`） | `(34051,34081,34085,34091,34088)` |
| `jma_stations`（`(prec_no, block_no, 種別)`） | `((46, None, "all"),)`（`c10_jma.py` の `PREC`。block は観測所表から） | `((88,"47909","s1"),(88,"1520","a1"),(88,"0980","a1"))`（名瀬・笠利・古仁屋） |
| `env_water_prefcodes` | `("14",)`（`c12_env_kousui.py` の `PREF`） | `("46",)` |
| `l03b_meshes` | `("5238","5239","5338","5339")`（`c34_nlni_l03b.py` の `MESHES`） | `("4229",)` |
| `nlni_pref_codes`（C23・W12・W05 等。c68 は W12 を読まない） | `("14",)` | `("46",)` |
| `estat_pref_codes` | `("14",)` | `("46",)` |

- 神奈川の値は**転記だけ**で、各 c スクリプトの直書きをこの PR で書き換えない（Step 1 以降、各収集スクリプトを地域引数にするときに `regions.py` を import する）。食い違いを防ぐため、`c02/c03/c10/c12/c34` の直書き定数（正規表現で取れるもの）と `jp-14` の値が一致することを見るテスト `scripts/tests/test_regions.py` を置く。
- `jp-46` が既存の不変条件・テストを壊さないことの根拠: `scripts/migrate/regions.py` の `region_problems()` は必須キーの有無と（あれば）`terrain` の形だけを見る。b03/b06 は `consumer` で出典が参照する region に絞る（`source_regions.py`）ので、出典の無い `jp-46` は素通り。`place.region_id → region` の参照整合性は `jp-46` の place が無いので影響なし。D1 の `region` 表・`REGION_TIME` に1行増えるだけ（`region-time.test.ts` は `length > 0` と各行の形のみ）。担当Cは `pytest scripts/tests/test_migrate_source_regions.py scripts/tests/test_regions.py` と `cd web && pnpm exec vitest run src/lib/registry` で確かめる。
- `gbif_gadm_gids` の書式・`jma` の block は、実取得での確認が要る（推測で埋めない）。Step 0 では**1件取得の確認ログだけ**を `reports/add_area_kagoshima.md` に残し（`docs/add_area.md` Step 1 の完了条件）、データは取り込まない。


## 5. ドキュメント

| ファイル | 内容 | 担当 |
|---|---|---|
| `docs/adr/0031-zone-definition-v2.md`（新規） | zone 定義の差し替え。背景（絶対閾値が奄美で壊れる: 湯湾岳 692m < 800m、海岸2kmが島のほぼ全域）・決定（§1 の規則とパラメータ、最高峰宣言（`region.yaml`）基準、スコープを common に・§2、C23 切り替え、sites.zone は m09、版は `definition_version`）・却下した代替案（J-SHIS: 奄美の河口で欠け再配布不可、W12 の小流域・水系域基準: 奄美で面が欠け水系も1つしかない、zone を地域別に定義: 番号が衝突）・影響（§1.4 の差分）・弱点（§1.5）。ADR-0002 の「zone の閾値を place のメタデータに地域ごとに持たせる」の部分と ADR-0022 決定1の実測表の zone 行を更新する旨を追記。`docs/adr/README.md` の一覧に0031を足す | C |
| `docs/ZONE_DEFINITION.md`（書き換え） | v2 の定義表・指標・取得方法（標高タイル・C23）・限界・v1 からの変更点（旧定義は履歴として短く残す）。`treatment` の節は残す | C |
| `docs/LICENSE_MATRIX.md` | (1) §4.1 の「非商用」に **C23 海岸線**を足す（W05・A10・A15 と同じ扱い。**zone 全体が C23 由来の海岸距離に依存する**ので、商用提案では C23 を差し替えるか zone を外す、と明記）。(2) 標高タイル（地理院 `dem_png`＝基盤地図情報数値標高モデル10mメッシュ。国土地理院コンテンツ利用規約＝政府標準利用規約2.0互換、出典表示。タイルそのものは再配布せず、派生値〔標高・起伏量〕だけを `terrain_points.csv` に持つ）の行。(3) §4 に新しい小節「鹿児島県サイトの PDF・Excel」: 県サイトは「無断転載・改変不可」でオープンライセンスの宣言が無い。**数値・種名などの事実の抽出に限り、出典の URL・取得日を明記して取り込む。PDF・Excel そのもの、表の体裁、図は再配布しない。BODIK に同じものがあればそちら（CC BY 4.0）を使う。**著作権法上、事実（数値・種名の列挙）自体は著作物ではないが、表の選択・配列に創作性がありうるので、表をそのまま写さず必要な項目を再構成する。県の許諾を取っていない旨と、問い合わせ先が決まれば連絡する旨を残す。(4) 同小節に「希少種の位置」: GBIF・iNaturalist 等の公開元が丸めた座標をそのまま使い、こちらで細かく起こさない（ADR-0028 は「こちらから座標を丸めない」決定であり、「公開元が丸めたものを細かく復元する」ことは別の話で、しないのが本方針）。ロードキルの地点図は使わない。(5) §5 の商用提案の確認項目に C23 を足す | C |
| `docs/add_area.md` | 今回触る範囲だけ: §3 の表の「海岸線」「GADM gid」「iNaturalist」「気象庁」「L03-b」の `jp-46` 列と、`scripts/regions.py` を「存在しない」から「ある」に。§7 の「zone のしきい値をエリアごとに」「`COASTLINE_LONLAT`」「申し送り（zone 番号の衝突）」を v2 の共通定義に合わせて直す。§9 の `zone / COASTLINE_LONLAT` 行を解消済みに。冒頭の「現在地: v1 の表」は v1 撤去（Issue #48 PR-5）に合わせて短く直すが、全面改稿はしない | C |
| `docs/PIPELINE.md` | 「取り込み・レジストリ」に c36 → c68 → m01 → m09 → r01 の順序と、`terrain_points.csv` が registry の指紋に入ること、m09 後は `build:registry` を明示することを数行 | C |
| `docs/ZONE_DEFINITION.md` の旧「標高の取得方法」節 | `ELEV_CAP`・`_elevation_cache.json` の記述は `sites.elevation_m`（地理院標高API）の説明として残す（zone の判定は標高タイルの標高を使う、と書き分ける） | C |


## 6. 実装の分担

**全担当共通の境界**: スキル（/simplify・/code-review 等）とサブエージェントを起動しない。`b00` の全量ゲート・`pnpm run build:v2`・`serving:snapshot` の全量・`db:setup`・`s02_materialize_sample.py`（本物のチェックアウトで）を回さない。コミットしない（メインがまとめる）。`git add -A` を使わない。原本 `data/db/ryuiki.sqlite`・`cells.sqlite` は**読み取り専用**で開く（`file:...?mode=ro`。書いてよいのは担当B の m09 が原本の `sites.zone` を更新する場合だけで、統合の段で**メインが**実行する。担当は `--dry-run` と一時コピーでだけ試す）。担当どうしのファイルは重ならない。

### 6-A　収集・指標（Python。ネットワークに出てよいのはこの担当だけ）

- **読む節**: §0、§1.2（列の定義）、§3（データの流れ）。`scripts/c31_nlni_w05.py`（zip を取って shapefile を GeoJSON/CSV/JSONL にする流儀と `register()`）、`scripts/common.py`（`get`・UA・1.5秒スロットル）、`docs/COLLECTOR_CONTRACT.md`（User-Agent に個人名を入れない）。
- **触るファイル**:
  - 新規 `scripts/c36_nlni_c23_coastline.py`: C23-06 の zip（`https://nlftp.mlit.go.jp/ksj/gml/data/C23/C23-06/C23-06_{14,46}_GML.zip`）を `data/raw/` に取り、`data/processed/nlni_c23_coastline.geojson`（＋ csv/jsonl は c31 の流儀）を作る。鹿児島は `C23_001`（行政区域コード）が `("46222","46523","46524","46525","46527")` の線だけ（`scripts/regions.py` ができるまでは定数で持ち、担当Cの `regions.py` ができたら差し替える）。出典登録（`register()`）は c31 の流儀。許諾は「非商用」。
  - 新規 `scripts/c68_gsi_dem_terrain.py` と、純関数を分けた `scripts/terrain_lib.py`（PNG 復号・円窓・起伏量・最低点・距離。ネットワーク無しでテストできるように）。出力は `data/processed/terrain_points.csv`（§1.2 の列、`lat,lon` 昇順、決定的）。取得は `data/raw/gsi_dem_png/{z}/{x}/{y}.png` にキャッシュし、1.5秒以上の間隔、`scripts/common.py` の UA。404 は空ファイルとして記録（再取得しない）。引数: `--points sites`（既定。台帳の `elevation_m IS NOT NULL` の座標。region は出典のマニフェストの region）、`--checkpoints <yaml>`（確認地点のみ。region は yaml の項目。出力は別の CSV〔`--out`〕）。**W12 は読まない。** 最高峰の検査（§1.2）を実装する。`region.yaml` に `terrain.summit` が無い region の地点があれば止まる。
  - 新規 `scripts/tests/test_c68_terrain.py`（合成 PNG で復号・円窓・起伏量・最低点・無効画素・海岸距離・最高峰の検査〔±20m の内外〕・`params_digest`、ネットワークに出ない）、`scripts/tests/test_c36_c23.py`（小さな shapefile のフィクスチャで絞り込み）。
  - 新規 `scripts/tests/fixtures/zone_checkpoints.yaml`（§1.4-d/e の43地点: 名前・緯度経度〔表のとおり〕・region・期待 zone の集合・`known_miss`〔平塚馬入〕）と、c68 `--checkpoints` が出す `scripts/tests/fixtures/zone_checkpoints_metrics.csv`（コミットする。担当Bのテストが読む）。
  - `registry/source/access.yaml`・`editions.yaml`・`license.yaml` に `nlni_c23_coastline`・`gsi_dem_terrain`（terrain_points の出典）の宣言を足す（`nlni_w05_rivers`・`gsi_elevation_grid` の宣言を手本に。r01 が出典の整合を検査するので、`python3 scripts/r01_build_registry.py --files-only` が通ることで確かめる。通らない要件が出たらその場で報告）。
- **受け入れ基準**:
  1. `c36` で神奈川 597 本・奄美5市町村 1,071 本前後の線が `nlni_c23_coastline.geojson` に入る（件数はログに出す）。
  2. `c68` の既定実行で `terrain_points.csv` が約242行（現在の台帳）できる。再実行で標高タイルを再取得しない（キャッシュ）。同じ入力で2回出力して同一バイト。
  3. `--checkpoints` の出力が §1.4-d/e の表の数値と、標高・起伏量・海岸距離・最低点からの比高で ±1%（座標の丸め誤差。最低点は z12 の画素の分 ±数m）以内に一致する。
  4. 蛭ヶ岳 1673m・湯湾岳 694m の検査が通る（DEM 最大 1672m・692m）。
  5. ネットワーク無しのテストが通る。
- **速い検証**: `.venv/bin/python3 -m pytest scripts/tests/test_c68_terrain.py scripts/tests/test_c36_c23.py -q`。実取得は c68 を**1回だけ**（z14 約680枚＋z12 約140枚、1.5秒間隔で約25分）。並行して別の担当に c68 を回させない。
- **やらないこと**: `sites.zone` を書く（担当B）。W05・W12 は使わない。`c30` の一般化（Step 1）。

### 6-B　zone の規則とビルド（Python。ネットワーク禁止）

- **読む節**: §0、§1（全部）、§2、§3。`scripts/registry/build_place.py` の zone と `_zone_relation_rows`、`scripts/registry/common.py` の `compute_input_fingerprint`、`registry/id_map/place.csv`、`scripts/pipeline_inputs.py`、`docs/adr/0004-identifiers.md` 規約0・2、`docs/adr/0022-place-region-scope.md` 決定1・2、`scripts/m07_kanagawa_edna.py` の冒頭（m0x が原本に書く流儀の例）。
- **触るファイル**:
  - `registry/place/zone.yaml`: 構造を `definition_version: 2` / `note_ja`（§1.1 の地域共通の注記）/ `terrain:` / `rule:` / `zones:`（5件、`zone`・`name_ja`・`condition_ja`・`ui_condition_ja`）に変える（§1.3 の値）。冒頭のコメントを v2 に合わせて直す。**この構造が担当C の `build-registry-ts.mjs` との契約**。`highland_basis` は置かない。
  - 新規 `scripts/registry/zone_rule.py`: `load_zone_definition()`（`zone.yaml` の読み込みと形の検証）、`classify(row, rule)`（§1.1。純関数）、`terrain_params_digest(terrain)`、`load_terrain_points(path, region_summits)`（`params_digest` と `summit_m` の照合を含む。座標の組をキーにした辞書）。
  - `scripts/registry/build_place.py`: `_load_zone_yaml()` を新構造に。zone place を `PLACE_SCOPE` ではなく `common` スコープで発行（§2）。`definition_ref` に `definition_version: 2` と v2 の免責文と `note_ja`。`_zone_relation_rows()` の入力は `classify()` の結果（対象は `elevation_m IS NOT NULL` の `sites` 行。`basis` に `zone.yaml v2` と `params_digest` を入れる）。台帳の `sites.zone` との一致検査（§3）。`terrain_points.csv` に無い対象座標は列挙して止める。ネットワークに出ない。
  - `scripts/registry/common.py`: `compute_input_fingerprint()` の `MODE_FULL` に `data/processed/terrain_points.csv` を混ぜる（`taxon_gbif_accepted.csv` と同じ扱い）。
  - `scripts/pipeline_inputs.py`: `SOURCE_FILE_KEYS` に `data/processed/terrain_points.csv`。`data/sample/coverage.yaml`: `wholesale_processed_files` に `terrain_points.csv`。
  - `registry/id_map/place.csv`: zone の行（§2）。`docs/adr/0004-identifiers.md`: 日付付きの追記（§2 の表の ADR の行）。
  - `scripts/m01_sites.py`: `COASTLINE_LONLAT`・`_dist_m_point_to_segment`・`dist_to_coast_m`・`zone_of` と `add_site()` 内の呼び出しを撤去（`zone=None` を入れる）。docstring の zone の節を直す。新規 `scripts/m09_site_zone.py`（§3 の仕様。`--dry-run`・`--report`・書き換え前の `reports/zone_v2_migration.csv`・冪等）。`scripts/m99_validate.py` の zone の節の文言を v2 に。
  - テスト: `scripts/tests/test_zone_rule.py`（`classify()` の境界値、`known_miss` を含む確認地点の表〔担当Aの `zone_checkpoints_metrics.csv`〕、`zone.yaml` の条件文言の数値と `rule:` の整合、ネットワーク禁止下で `build_place` が動く）、`scripts/tests/test_zone_v2_migration.py`（`reports/zone_v2_migration.csv` の `zone_v2` が、サンプルの `terrain_points.csv` と `sites` で `classify()` の結果と一致する〔サンプルに無い地点は飛ばす〕。パラメータやデータを変えて zone が動いたら、この宣言を作り直さない限り落ちる）、`scripts/tests/test_m09_site_zone.py`（一時 DB で `--dry-run`・冪等・`zone_v1` の保持）、`test_registry_place.py`・`test_r01_invariants.py` の直し、`test_pipeline_inputs.py`。
- **受け入れ基準**:
  1. `classify()` が §1.1 のとおり。標高なし→None、海岸（2000m ちょうど・10m ちょうどは 5）、山地（起伏量200m ちょうどは山地）、最高峰の比（0.5 ちょうどは 1）、`floor_min_m` なし→3、`known_miss` の1件以外の確認地点が期待の集合に入る。
  2. 担当Aの実データが無くても、手書きの小さな `terrain_points.csv` フィクスチャで `build_place` が通る。zone place は `common:place:zone.r2r.{1..5}`・`region_id` NULL、辺の数は対象地点数（`elevation_m IS NOT NULL` かつ zone が付くもの）と一致。
  3. `params_digest` 不一致、`summit_m` が `region.yaml` と不一致、座標が csv に無い、台帳の `sites.zone` と不一致、のそれぞれで止まる（テスト）。
  4. 統合後（メイン）に: 290地点の旧→新のクロス表が §1.4-a と一致する。
- **速い検証**: `.venv/bin/python3 -m pytest scripts/tests/test_zone_rule.py scripts/tests/test_zone_v2_migration.py scripts/tests/test_m09_site_zone.py scripts/tests/test_registry_place.py scripts/tests/test_r01_invariants.py scripts/tests/test_pipeline_inputs.py scripts/tests/test_place_id_grammar.py -q`（原本を開かない）。r01 は `--files-only` だけ。

### 6-C　region・定数・web の読み出し・文書（担当A・B と別ファイル）

- **読む節**: §0、§1.2（最高峰の宣言）、§2（効くところの表）、§4、§5。`docs/add_area.md` §1・§3・§4 Step 1〜2・§7・§9、`web/scripts/build-registry-ts.mjs` の zone.yaml を読む箇所（230〜246行付近）。
- **触るファイル**:
  - `registry/region.yaml`（`jp-46` と、`jp-14`・`jp-46` の `terrain.summit`）、`scripts/migrate/regions.py`（`region_problems()` に `terrain` の形の検査。無ければ通す）、新規 `scripts/regions.py`（§4）、新規 `scripts/tests/test_regions.py`（`region.yaml` の region と `regions.py` の対応、書式〔GID は `^JPN\.\d+(\.\d+)?_1$`、メッシュ4桁、市町村コード5桁〕、`jp-14` が既存の c スクリプトの直書きと一致、`jp-46` の件数: GID 5・iNat 5・JMA 3・市町村 5）と、`terrain.summit` の検査のテスト（`test_migrate_source_regions.py` の追記）。`reports/add_area_kagoshima.md`（1件取得の確認ログ。GBIF は `gadmGid` で count>0、iNat は `place_id` で結果あり、JMA は名瀬の1か月、水環境は `prefcode=46` の地点数）。最高峰の座標は地理院地図で確認して確定する（暫定値は §1.2）。
  - `web/scripts/build-registry-ts.mjs`: `zone.yaml` の新構造（`zones:` の配列）を読む。`definition_version` を `generated-client.ts` の `ZONE_DEFINITION_VERSION` として出す。`ZONE_INFO` の形（`zone`/`label`/`cond`）は変えない。web のテスト（`generated.test.ts` 等）を新構造に。**生成物（`generated-*.ts`）は手で書き換えない**（統合で `pnpm run build:registry`）。
  - `registry/caveat.yaml` の `zone`（本文の「標高800m超」を v2 の説明に。`zone.yaml` の `note_ja` と同じ文を含める。「zone 1 には水質データが無い」は新 zone 1 の4地点〔気象庁1・モニ1000 3〕でも成り立つ。`review` の欄は、本文が変わったので `reviewed_on`/`reason` を更新し、`owner_confirmed_on` は**触らず**統合で人の確認を取る）、`web/src/components/timeseries/TimeseriesExplorer.tsx` 653行の「ゾーン1（標高800m超）」、`web/src/components/viz/palette.ts` のコメント。
  - 文書（§5 の全部）。
- **受け入れ基準**:
  1. `jp-46` を足して既存の速い検証が通る: `.venv/bin/python3 -m pytest scripts/tests/test_migrate_source_regions.py scripts/tests/test_ingest_manifest.py scripts/tests/test_regions.py -q`、`cd web && pnpm exec vitest run src/lib/registry`。
  2. `pnpm run build:registry` が（B の新 `zone.yaml` で）通り、`ZONE_INFO` が5件・名称5つ（3 は「丘陵・台地・扇状地」）。
  3. 文書の数値が §1 と一致し、LICENSE_MATRIX に C23・標高タイル・鹿児島県サイト・希少種の位置が入る。
- **速い検証**: 上のコマンド。web のビルド（`next build`）・全テストは回さない。
- **担当B との契約**: `zone.yaml` の構造は §1.3・§6-B のとおり。B が先に `zone.yaml` だけを書いてよい（C は B の完成を待たず、構造に合わせて読み出しを書く）。`region.yaml` の `terrain.summit` は C が書き、B・A は読むだけ。

## 7. PR 全体の受け入れ基準（統合・メインが確かめる）

1. **神奈川の zone 付き290地点の旧→新のクロス表と、変わった地点の一覧が PR に付く。** `m09 --report` の出力を貼る。宣言は `reports/zone_v2_migration.csv`（`site_id,zone_v1,zone_v2,elevation_m,relief_wide_m,relief_near_m,coast_dist_m,floor_min_m,reason`。m09 が書き換える前に書き出す）で、`test_zone_v2_migration.py` が機械的に検証する。クロス表は §1.4-a（一致172・変更118・なし0）と一致する。**一致しなければ、規則やデータの差の原因を特定する（ラベルを曲げて合わせない）。**
2. **奄美の確認地点が期待どおりの zone になる**: `scripts/tests/fixtures/zone_checkpoints_metrics.csv` に対する `test_zone_rule.py` が通る（神奈川30地点のうち期待外は `known_miss` の1件〔平塚馬入〕だけ、奄美13/13；最高峰の宣言値の検査〔蛭ヶ岳・湯湾岳〕も通る）。PR に表を貼る。
3. **生成物の鮮度判定に新しい入力が入る**: `terrain_points.csv` を書き換えると `python3 scripts/r01_build_registry.py --check-fresh` が古いと言う（変異テスト。メインが1回）。`zone.yaml` の `terrain:` を変えて c68 を回さないとビルドが `params_digest` で止まる。
4. **ビルドの段階でネットワークに出ない**: ソケット禁止下のテストが通る。`scripts/registry/zone_rule.py`・`build_place.py`・`m09_site_zone.py` は `requests`・`urllib` を import しない。
5. **CI の sample-gate が通る**: §3 の「CI の sample-gate に要るもの」が入っている。具体的には、原本のある手元で (a) c36・c68 を実行、(b) m01 を再実行せず m09 だけを実行（台帳の他の列を動かさない）、(c) `scripts/s01_build_sample.py` でサンプルを作り直し、(d) 一時ディレクトリへの `git clone` で `s02_materialize_sample.py` → `r01` → `b03〜b13` → `serving:snapshot -- --mode snapshot` が緑（CLAUDE.md の「CI の再現は clone で。原本を退避しない」）。
6. **serving snapshot の差分（`--mode diff`）を PR に貼る**: zone の分類の変化（`zone_min`/`zone_max`、ゾーン別の集計）だけが動く。他の問い合わせが動いたら原因を調べる。
7. **b00 の全量ゲートを PR を出す直前に1回だけ**回し、`reports/serving_fingerprint.json` をコミットする（`pipeline_inputs.py`・`scripts/registry/`・`registry/` を触るため）。
8. `jp-46` を足しても `pytest scripts/tests`（速いもの）と `web` の registry 関連テストが緑。`pnpm run build:registry` の生成物の差分が、zone の条件文言・`ZONE_DEFINITION_VERSION`・zone の `LEGACY_PLACE_ID_MAP`・`REGION_TIME` の `jp-46` だけである。
9. 文書: ADR-0031、`ZONE_DEFINITION.md`、`LICENSE_MATRIX.md`（C23・標高タイル・鹿児島県サイト・希少種の位置）、`add_area.md`（今回触る範囲）、`PIPELINE.md`。

統合の順序（メイン）: A・B・C を並行 → A の c36・c68 を1回実行して実データを作る（B・C はフィクスチャで進める）→ 担当B の `m09`（書き換え前に旧→新の一覧 `reports/zone_v2_migration.csv` を自動で書き出す。`--dry-run` で先に確認）→ `pnpm run build:registry` → 上の 1・2 を確認 → 速い検証 → `s01` でサンプル再生成・clone で sample-gate 再現 → snapshot diff → `/code-review`（medium）と `/simplify` を同時に → b00 を1回 → PR。
10. 島の配分: c68 の確認と別に、奄美の陸の画素全体の配分（§1.4-e、zone 2 が約7割・zone 4 が約0.2%）が `zone.yaml` の注記と矛盾しないこと（担当Aが再現スクリプトの出力を PR に貼る必要は無く、統合で数字が §1.4 と大きく違わなければよい）。


## 8. 設計担当の自信が無い点（アドバイザーに聞く点）

**決定済み（改訂で閉じた）**: (1) zone 1/2 は W12 に依存させず、`region.yaml` に宣言した地域の最高峰の半分で分ける。(2) zone 4 は3条件の構造を保ち、基準を周囲2kmの最低標高からの比高にする（標高100m上限の根拠は「沖積低地は海面を基準に堆積した地形」）。(3) zone の ID は `common:place:zone.r2r.N` のまま、版は `definition_ref`/`basis` に持つ。ADR-0004 に日付付きの追記。(4) 台帳の `sites.zone` は m0x の流儀（`m09_site_zone.py`）で更新し、`build_place` は座標から判定して一致を検査する。(5) 島で zone 2 が大半になることは受け入れて `zone.yaml` の注記に書く。(6) c68 は W12 を読まない。

**残っている確認点**:
1. 最高峰の宣言座標（蛭ヶ岳 35.4863, 139.1389・湯湾岳 28.2963, 129.3209）は DEM の山頂画素から取った暫定値。地理院地図での確定は担当C。神奈川は蛭ヶ岳 1673m を基準にするため、zone 1 は丹沢・箱根の約837m以上だけになる（旧 zone 1 の4地点は全て残る）。
2. 低地(4)の3条件の数値（250m窓の起伏30m・最低点比高15m）は、私が置いた期待30地点に合わせて決めた。過学習の恐れがあり、専門家の確認が要る（大和・日吉・開成は境ぎりぎりで 3 側に倒れる）。
3. 旧 zone 付き地点の集合を `elevation_m IS NOT NULL` と定義し直した点。今の `zone IS NOT NULL`（290件）と同じ集合になることは確かめた（62件は標高が無い）が、標高タイルで標高が取れる62件に将来 zone を付けるかは #86 に残してよいか。
4. 鹿児島県サイトの許諾の整理（事実の抽出に限る）は、法的な見解ではなく運用方針の記述。オーナーが最終的に確認する必要がある。
5. 神奈川の確認地点の「期待 zone」は私の地理知識で置いたもの。専門家の確認は未了（§1.5-5）。
6. Step 1 で `c30` を一般化するとき、奄美付近の W12 の面数（Issue は約36、bbox 内は25面、種別はすべて 0）の差を確かめる。zone には使わなくなったので、この PR には影響しない。
