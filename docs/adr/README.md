# ADR — 流域カルテ データ基盤

Architecture Decision Record。1ファイル＝1決定。**背景・決定・根拠・影響・却下した代替案**を
残し、後から「なぜこうなっているのか」を辿れるようにする。

対象は **データパイプライン・データモデル・データインターフェース（API/MCP）**。
可視化レイヤは対象外（今後シビックテック側で多様に増える前提であり、ここで縛らない）。

- 状態: `提案中` / `承認済` / `却下` / `置換済(→ADR-XXXX)`
- 番号は連番。決定を覆すときは既存ADRを書き換えず、新しいADRで**置換**する。

## 一覧

| # | 決定 | 状態 |
|---|---|---|
| [0001](0001-storage-layers.md) | 原本を Parquet に置き、D1 は再構築可能な配信キャッシュとする | 提案中 |
| [0002](0002-multi-region.md) | 多地域前提でモデリングし、地域固有語彙をコードリストの拡張として扱う | 提案中 |
| [0003](0003-standards-at-the-boundary.md) | 外部標準（DwC-A / SensorThings / DCAT）は境界のアダプタで満たす | 提案中 |
| [0004](0004-identifiers.md) | 識別子はスコープ付きの安定IDとし、既定を `common` にする | 提案中 |
| [0005](0005-source-editions.md) | 出典を版管理し、ライセンスを行単位で解決可能にする | 提案中 |
| [0006](0006-place-registry.md) | 空間単位を単一の `place` レジストリに統合する | 提案中 |
| [0007](0007-observation-fact.md) | 観測値を単一の縦持ちファクト `observation` に集約する | 提案中 |
| [0008](0008-time-representation.md) | 時間は「区間＋粒度」の3点セットで表す | 提案中 |
| [0009](0009-censored-values.md) | 定量下限未満を 0 で表さず、検閲を明示的に持つ | 提案中 |
| [0010](0010-variable-registry.md) | 指標レジストリを設け、出典別名をエイリアスで束ねる | 提案中 |
| [0011](0011-aggregation-cube.md) | 派生33テーブルを単一キューブ＋宣言的集計定義に置き換える | 提案中 |
| [0012](0012-source-manifests.md) | L1→L2 でソース固有コードを書かない（マニフェスト＋共通ライブラリ） | 提案中 |
| [0013](0013-caveats.md) | 注意事項（caveat）を一級エンティティにし、応答に必ず同梱する | 提案中 |
| [0014](0014-response-envelope.md) | データインターフェースの共通レスポンス封筒と MCP ツール群 | 提案中 |
| [0015](0015-domain-extensions.md) | ドメイン固有構造はコアに入れず拡張パッケージに分ける | 提案中 |
| [0016](0016-migration-plan.md) | 移行は4段階に分け、v1 の数値を再現できることを受け入れ基準にする | 提案中 |
| [0017](0017-write-path-scope.md) | 本 ADR 群は読み取り基盤に限る。書き込み経路と可変データの所在を分ける | 提案中 |
| [0018](0018-publication-scope.md) | 公開範囲と座標の一般化をデータとして持ち、公開経路で強制する | 提案中 |
| [0019](0019-taxon-registry.md) | 分類群レジストリと分類カテゴリの表記ゆれの扱い | 提案中 |
| [0020](0020-freshness-rebuild.md) | 更新方式・鮮度・再ビルド運用 | 提案中 |
| [0021](0021-observation-grain-and-cube-key.md) | 粒度は「値の粒度」と「日付の精度」に分け、キューブは入力の統計量と粒度を鍵に含める | 提案中 |

### 未着手（この順で書く予定）

| 論点 | なぜ要るか |
|---|---|
| バージョニングと後方互換 | L2スキーマ・キューブ・MCPツール署名・公開URI の変更方針と非推奨化 |
| アクセス制御・レート制限・コスト上限 | 公開 MCP は LLM エージェントが高頻度で叩く。D1 rows_read / R2 egress の上限 |
| テスト・検証戦略 | L2→L3 の決定性、v1 との照合、マニフェスト checks、ゴールデンクエリ |
| 削除・訂正・撤回（takedown） | moni1000 の前例、公開 Parquet の差し替え、GBIF 側への撤回伝播 |
| 語彙ガバナンスと命名規約 | 誰が code を承認するか、`variable.code` の命名、日英の扱い |
| ジオメトリ配信形式 | GeoJSON / PMTiles / FlatGeobuf、簡略化段階、`geometry_ref` の実体 |
| 配布物のライセンスと引用 | `cite_as` の生成規則、複合ライセンスの Frictionless 表現、OSS ライセンス |

---

## 0. 前提となる合意（2026-09-06）

| 論点 | 決定 | ADR |
|---|---|---|
| 適用範囲 | 多地域前提（神奈川デモ ＋ 奄美・龍郷を同一モデルに） | 0002 |
| ストア | Parquet/R2 が原本、D1 は配信キャッシュ | 0001 |
| 標準準拠 | DwC-A/eMoF・OGC SensorThings・DCAT/Frictionless に**境界で**合わせる | 0003 |

---

## 1. 診断 — なぜ作り直すか（現行 v1 の実測）

すべての ADR がこの4つの観察を共有の前提としている。

### (a) 派生層が「データの形」ではなく「画面の形」をしている

`derived.sqlite` の**33テーブル**は、画面・AIツール・チャート部品ごとに個別対応で作られている
（`meas_year` だけでも `lib/queries.ts` / `lib/ai/tools.ts` / `lib/ai/prompt.ts` /
`lib/ai/caveats.ts` / `SeriesChartCard.tsx` の5ファイルから参照される）。
決定的なのは参照の数ではなく**形**で、列構成を並べると全部が同じ骨格をしている:

```
meas_year          : site_id, variable, kind, year        -> n, avg, min, max, n_censored, unit
zone_year          : zone,    variable, kind, year        -> n_sites, n, avg, unit
zone_clim          : zone,    variable, month             -> n_sites, n, avg, unit
sensor_daily       : site_id, datastream, d               -> n, avg, min, max, unit
species_mesh_year  : binom,   mlat, mlon, year            -> n
org_watershed_year : watershed_id, year                   -> n, species_n, alien_n, redlist_n
landuse_watershed  : watershed_id, year, landuse_code     -> n_cells, area_km2
```

**すべて `(場所, [分類群], 指標, 期間, 粒度) -> 統計量`**。33テーブルは1本のキューブの射影でしかない。
このままだと *データ種類 × 集計軸 × 画面* でテーブルが増え続ける。→ ADR-0011

### (b) 意味論がアプリ側（`web/src/lib/domain.ts`）にあり、データに乗っていない

- 定量下限未満（全体の約24%）が `measurements.value = 0` で格納されている → ADR-0009
- `measured_on` が日付形式 217,710行 と年度形式 105,454行 の混在 → ADR-0008
- `sites.municipality` に水域名が入る出典が290地点ある → ADR-0006
- `measurements` 323,164行のうち **109,078行（34%）が単位なし** → ADR-0010
- `organism_records` **823,692行すべてが `site_id` NULL**（座標のみ）。「場所」の解決が未定義 → ADR-0006

**MCP クライアントは `domain.ts` を読めない。** このまま MCP を出すと「0 が観測された」
「2015-01-01 に測った」と読む分析が量産される。→ ADR-0013 / 0014

### (c) 同じ量が出典ごとに別名で入っている

```
OX / Ox(ppm) / 光化学オキシダント_日平均      <- 同じ物理量が3つの名前
SPM(mg/m3) / 浮遊粒子状物質（SPM）_日平均      <- 名前に単位と集計粒度が埋まっている
```
`measurements.variable` は58種、`source_registry.category` は124行に対し **74種の自由記述**
（`gis_river` と `河川` が併存）。→ ADR-0010

### (d) ソースを1つ足すとテーブルもAPIも画面も増える

Tier 1 追加時に `protected_areas` / `vegetation_polygons` / `mammal_mesh` /
`wildlife_sightings` / `river_segments` の5テーブル ＋ `/api/nature?kind=` ＋ `/api/geo/*` が増えた。
追加のたびにこれが繰り返される。→ ADR-0012

### (e) テーブル数の記録自体がずれている

実測: `ryuiki.sqlite` 28 + `cells.sqlite` 8 + `derived.sqlite` 33 = **69テーブル**
（`schema.ts` は `_seed_state` を含め70定義）。一方 `CLAUDE.md` と
`web/src/lib/features.ts` は「61テーブル」、`web/src/lib/table-meta.ts` は「56テーブル」と書く。
`domain.ts` の `DATA_CAVEATS.measuredOn` の内訳（216,990 / 98,328）も実データ
（217,710 / 105,454）とずれている。**コード内に手書きされた事実は腐る。**
ADR-0013（caveat のデータ化）と ADR-0010（レジストリ化）の直接の根拠になる。

### v1 で素性が良く、v2 の中核に昇格させるもの

`measurements` の縦持ち（variable/value/unit）、行単位の `source_id`/`source_ref`、
`source_registry` のライセンス・再配布可否、`organism_records` の `license_class`/`commercial_ok`、
`quality_stage` の3段階。**これらは捨てない。**

---

## 2. 合格条件（設計の良し悪しの判定基準）

1. **L1→L2 でソース固有のコードを書かない。** 触るのはマニフェストと語彙だけ（ADR-0012）。
   収集（L0→L1）はソース固有のままで、ここは汎用化の対象外
2. **新しい集計軸の追加でテーブルが増えない。** 集計定義に1行足すだけ（ADR-0011）
3. **MCP の応答だけで正しく読める。** 単位・時間粒度・検閲・ライセンス・注意事項が必ず同梱（ADR-0014）
4. **どの数字も原本まで辿れる。** observation → source_edition → document/page → 原文（ADR-0005）
5. **D1 を捨てて作り直せる。** L2 Parquet から L3 が決定的に再生成される（ADR-0001）
6. **地域を足しても語彙が壊れない。** 地域固有の値はコードリストの拡張であって分岐ではない（ADR-0002）
7. **v1 の数値を再現できてから変える。** 移行の誤りと意図的な変更を分離する（ADR-0016）
8. **公開してはいけないものが公開経路に載らない。** 隔離データ・希少種の位置（ADR-0005 / 0018）

---

## レビュー記録

**2026-09-06 / Fable エージェントによる査読（ADR-0001〜0015 に対して）**

指摘を受けて修正した点:

| 指摘 | 対応 |
|---|---|
| 隔離データが「公開される L2 原本」に載る矛盾 | ADR-0001 に `core/`（配布しない）と `dist/`（配布する）の分離を追加 |
| 地域接頭辞 ID と「ID 不変」が両立しない | ADR-0004 に規約0（既定は `common`、地域はファクトのパーティション列）を追加。ADR-0010 の「2地域で昇格」を撤回 |
| 点→place の解決が未定義でキューブの入力が成立しない | ADR-0006 に「点→place の解決規約」を追加。ADR-0007 の「place 必須」を緩和 |
| キューブの入力が `observation` だけで生物系11テーブルの行き先が無い | ADR-0011 に `source: occurrence` と `count` / `n_distinct` / `presence` を追加 |
| `half_lod` を既定にする根拠が弱く、`ND` 行で破綻する | ADR-0009 で既定を撤回し `imputation` を必須パラメータに。`not_detected` を別区分に |
| ADR-0012 の汎用 YAML DSL がこの規模に重い | マニフェストを「メタデータ＋検証」に縮退し、写像は共通ライブラリの型付き関数に |
| ADR-0014 の「Web も同じ HTTP 経路」が D1 課金と衝突 | 「同じモデルと語彙を使うが同じ経路は強制しない」に修正。MCP ツールを第1段5本に絞る |
| OGC SensorThings の API 実装が重い | ADR-0003 で「STA 形の JSON エクスポート」に縮退 |
| 移行の段階計画と受け入れ基準が無い | ADR-0016 を新設（Phase A〜D、`imputation='zero'` での v1 再現を基準に） |
| 数字の誤り（派生35→33、61→69テーブル、「本当の 0 が1,220行」→153行） | README と該当 ADR を実測値で修正。§1(e) を追加 |
| 抜けている論点 | ADR-0017（書き込み経路の境界）/ 0018（公開範囲）/ 0019（taxon）/ 0020（鮮度）を新設。残りは「未着手」に列挙 |

**指摘のうち、実データで確認した結果あたらなかったもの**:
「県／国レッドリスト該当種の出現 3,542 件が `publication_scope='全公開'`」という指摘は誤り。
実測では RL 該当 5,008 件はすべて `限定共有` で、**全公開は 0 件**。学名で
`redlist_assessments` に一致するのに `red_list_category` が空の行も 0 件で、
v1 のゲートは漏れていない。ただし**判定がモデル上のルールではなくスクリプト内の
一度きりの処理で、文字列に依存している**という懸念自体は妥当なので、ADR-0018 として採用した。

---

## 3. レイヤ構成（ADR-0001 の要約）

```
L0  raw          data/raw/<source_id>/                     取得したまま・ハッシュ付き・不変
L1  staging      data/processed/<source_id>.{csv,jsonl}    ソース別に正規化（現行維持）
                    │  mapping manifest (YAML) ← ここだけがソース固有
L2  canonical    core/*.parquet                            正準モデル（10エンティティ）
                    │  aggregation spec (YAML)
L3  serving      cube/*.parquet  +  D1                     集計キューブ・ジオ束（再構築可能）
                    │  adapters
    publish      DwC-A / SensorThings / DCAT / Frictionless
```

## 4. コアモデル（10エンティティ）

| エンティティ | 役割 | v1 の行き先 | ADR |
|---|---|---|---|
| `source` / `source_edition` | 出典と**版**。ライセンス・取得日・ハッシュ | `source_registry` | 0005 |
| `place` / `place_relation` | 空間単位レジストリ1本 | `sites` `watershed_meta` `mesh_*` `zone_*` `water_zone` | 0006 |
| `taxon` | 分類群レジストリ（GBIF key・シノニム） | `taxa` | 0019 |
| `variable` | 観測項目レジストリ（単位・測定法・別名） | `var_catalog` ＋ `domain.ts` | 0010 |
| `observation` | 縦持ちファクト1本 | `measurements` `sensor_timeseries` `mammal_mesh` | 0007 |
| `occurrence` | 生物出現レコード（DwC 相当） | `organism_records` `wildlife_sightings` | 0003 |
| `feature` | 属性付きジオメトリ | `protected_areas` `vegetation_polygons` `river_segments` | 0006 |
| `document` / `cell` | 行政文書の証跡層。cell → observation の昇格経路 | `documents` `cells` | 0005 |
| `event` / `protocol` / `observer` / `instrument` | 現地調査の系譜（市民科学の要件） | 同名テーブル | — |
| `caveat` | 注意事項 | `notes` ＋ `domain.ts` の `DATA_CAVEATS` | 0013 |
