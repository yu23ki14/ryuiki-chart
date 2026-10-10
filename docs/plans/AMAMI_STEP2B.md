# 奄美 Step 2b: BODIK 河川砂防情報システムの履歴（Issue #89）

鹿児島県土木部河川課の「河川砂防情報システムデータ」（BODIK、CC BY 4.0）から、奄美大島の局を取り込む。2026-10-10 に設計担当が BODIK を実際に取得して確かめた。

## 0. 決定（2026-10-10、オーナー承認）

1. **日別に集約して入れる**。10分値・5分値の生データは `data/raw/kagoshima_kasen/` に残す（gitignore 済み）。
2. **水位（危機管理型水位計）は日最高・日最低だけ入れる**。通常は6時間おきの観測で、水位が上がると間隔が細かくなる。そのため日平均を出すと高い側に偏る。
3. **期間**: 水位は奄美の局が現れる年から（2021年の見込み。2020年は実行して確かめる）。潮位とダムは2008年から。
4. **雨量は入れない**（奄美の局が0）。風向風速は別の PR で確かめる。
5. **局の座標と所在**: 県の河川砂防情報システムの公開ページにある観測所一覧から、局名・所在・座標を事実として抜き出し、出典を明記する。
   - 取れない局は座標なしで `site_supplement.csv` に載せる（`needs_review`）。
   - 国交省の水文水質DB・川の防災情報は、ツールで取得しない。
6. **大和ダム**: 所在（大和村）を一次資料で確かめられたときだけ入れる。推定では入れない。
7. **単位**: 原表記の整数のまま持ち、それを表す単位を付ける。
   - 水位・潮位は cm（推定。alias の note に書く）。
   - 貯水率は 0.1%。
   - 流入量は 10^-3 m3/s、貯水量は 10^3 m3。この2つの単位は新しく作る。
8. **update_mode**: append にする。最新の年は月ごとに差し替わるので、毎回取り直す。

## 1. BODIK の実際（設計担当が確認）

- **データセット**: `460001_suii`（水位）、`460001_choui`（潮位）、`460001_dam`（ダム諸量）。
  - 年ごとの ZIP で、URL にリソースの UUID が入る。なので毎回 `package_show` で URL を引く。
  - 呼び出しの間は5秒以上空ける（続けて呼ぶと 403 になる）。
- **ZIP の中**: 月ごとの CSV（CP932）。
  - ZIP の中のファイル名も CP932 で、UTF-8 のフラグが無い。`filename.encode('cp437').decode('cp932')` で戻す。
  - **横持ち**で、ヘッダが3行ある（種別／局 ID／`観測時刻,局名…`）。ダムだけ4行目に単位の行がある。
  - 時刻は `2024/01/01 00:10`（JST）。月のファイルの最後の行は、翌月1日の 00:00。
- **欠測などの記号**: `***` は障害・欠測、`---` は休止・該当なし、空欄は記録なし。
  - 負の値は実在しうる（水位標の零点より下）ので、捨てない。
  - 数値にならない値は種類ごとに件数を数えて出力する（黙って捨てない）。
- **局 ID**: 種別の中で、年をまたいで変わらない。局名は種別をまたいで重複するので、キーは (種別, ID) にする。
- **局表が無い**: 座標・市町村・河川名は ZIP にも BODIK の目録にも無い。

### 奄美の局

| 種別 | 局 | 備考 |
|---|---|---|
| 危機管理型水位計 | 第2屋仁橋 ID139・朝戸橋 144・古仁屋橋 148 は確定 | ほかは ID 130〜153 付近にある候補。観測所一覧で確定させる |
| 潮位 | 名瀬（ID 4） | 2008-01〜。10分値。欠測は少ない |
| ダム | 大和ダム（推定） | 決定6のとおり、所在を確かめてから入れる |
| 通常の水位・雨量 | 無し | |

## 2. 担当 A（収集）

触るファイル:
- `scripts/c94_kagoshima_kasen.py`（新規）
- `scripts/tests/test_c94_*.py`
- `docs/LICENSE_MATRIX.md`

手順:
1. **最初に局の表を作る**: 県の河川砂防情報システムの公開ページで観測所一覧を探す。(種別, ID, 局名, 市町村, 緯度, 経度) の表を作り、出典の URL を残す。
   - 奄美かどうかは、bbox（`regions.py` の jp-46）と市町村で決める。
   - 大和ダムの所在は、一次資料（県の資料・国土数値情報のダムなど）で確かめる。
2. **c94 の作り**
   - 引数は `--kind {suii,choui,dam}` と `--years`。
   - `package_show` で URL を引き、`download()` で落とす（既にあれば使う）。
   - ZIP を読み、奄美の局だけを残して日別に集約する。
   - 出力は `data/processed/kagoshima_kasen_{suii,choui,dam}_amami.{csv,jsonl}` と `kagoshima_kasen_stations_amami.{csv,jsonl}`。
   - 出力の列は、既存の `soramame_hourly_*` などに合わせる（`station_id`・`datetime`（日付）・`variable`・`variable_ja`・`value`・`unit`・`source_id`・`source_ref`）。
3. **register()**: ライセンスは CC BY 4.0、出典は「鹿児島県 土木部河川課 河川砂防情報システムデータ（BODIK）」。
4. **テスト**: 合成の小さな CSV の文字列で確かめる（ヘッダ3行、CP932 のファイル名、記号、日の割り当て、集約）。
5. **集約の系列**
   - 水位: 日最高・日最低。
   - 潮位: 日平均・日最高・日最低。
   - ダム: 貯水位（日平均・日最低）、全流入量・全放流量（日平均・日最高）、貯水量（日平均）、貯水率（日平均。値のある項目だけ）。空容量は入れない。

## 3. 担当 B（取り込みと registry）

触るファイル:
- `scripts/regions.py`、`scripts/m02_measurements.py`、`scripts/m01_sites.py`
- `registry/variable.yaml`、`registry/unit.yaml`、`registry/variable_alias.csv`、`registry/caveat.yaml`
- `registry/place/site_supplement.csv`、`registry/source/access.yaml`、`registry/source/license.yaml`
- `manifests/kagoshima_kasen_*_amami.yml`
- `scripts/s01_build_sample.py`、`data/sample/coverage.yaml`
- テスト

作業:
- **source_id**: `kagoshima_kasen_suii_amami`・`kagoshima_kasen_choui_amami`・`kagoshima_kasen_dam_amami`・`kagoshima_kasen_stations_amami`。
  - site_id は `kagoshima_kasen_stations_amami__<種別>_<ID>`（例 `__suii_kiki_139`）。
- **m02**: `_sensor_sources()` に3つを足す。ファイルが無ければ飛ばす。
- **m01**: 座標のある局を `sites` に入れる新しいブロックを作る。座標の無い局は `site_supplement.csv` に載せる。
- **variable**: `hydro.tide_level`、`hydro.reservoir_level`、`hydro.reservoir_inflow`、`hydro.reservoir_outflow`、`hydro.reservoir_storage`、`hydro.reservoir_fill_rate`。
  - 水位は既存の `hydro.river_stage` を使う。
- **unit**: `10^-3 m3/s` と `10^3 m3` を新しく作る。既存の `cm`・`0_1percent` を使う。
- **caveat**
  - 水位の基準面が T.P. ではない。
  - 危機管理型は通常6時間おきで、日平均を出していない。
  - 潮位の基準面が不明。
  - 速報値で、検定されていない可能性がある。
- **manifest**: 3本。`region: jp-46`、`target: observation`、`input.table: sensor_timeseries`、`adapter: builtin`、append。件数は統合で実測して書く。
- **時刻ラベルの宣言**: 日別なので要らない。

## 4. 統合（実行の順。メインが回す）

1. 局の表と c94（水位 → 潮位 → ダム）
2. m01 → c68 → m09 → m02
3. r01 → `build:registry:ts` → `build:v2`
4. サンプル → 一時 clone での CI 再現 → b00

原本の扱い:
- 書き込む前に `.backup` を取り、書いた後は全表を EXCEPT で突き合わせる（`cells` も）。
- c25・c26 は流さない（`docs/plans/AMAMI_STEP2A.md` の教訓）。
- m02 は出典ごとに入れ直すだけで、ほかの出典の行は消さない。
