# Phase B 生物の出現（occurrence）の縦線 — 事実の洗い出しと Slice 0

対象: ADR-0016 の Phase B / 状態: **Slice 0（レジストリ整備）完了、ファクトはまだ作っていない**
作成: 2026-09-22 / 関連: ADR-0004, 0006, 0007, 0018, 0019, 0022,
`docs/plans/PHASE_B_FACT_SLICE.md`（縦に薄い1本の先例）

このドキュメントは外部アドバイザー（Fable サブエージェント）による実測とオーナーの決定を、
セッションをまたいでも消えない形でリポジトリに残すもの。`measurements`→`observation`の
縦線（`PHASE_B_FACT_SLICE.md`）と対になる、`organism_records`（823,692行、この基盤最大の
ファクト）→ occurrence の縦線の設計・実測・縦線の切り方を記録する。

## 1. なぜこの縦線が難しいか

`organism_records` は `measurements` より簡単に見えて、実際には4つの独立した難所が
重なっている:

1. **taxon の ID 空間が出典ごとに違う**（F1）。GBIF と iNaturalist の数値空間が別物。
2. **流域への解決が点内包判定に依存し、v1 はメモ化で走査順依存の丸めをしている**（F3）。
3. **座標精度（`coordinate_uncertainty_m`）の75%が NULL** で、ADR-0006 規約4を文字どおり
   適用すると大半が解決不能になる（F4）。
4. **v1 の分類補完（class/kingdom/phylum の多数決）を再現しないと `org_norm` と数字が
   合わない**（F2）。

これらを一度に解決しようとすると `measurements` の縦線と同じ理由（ゲートが一度も緑に
ならない）で行き詰まる。**Slice 0 はファクトを一切作らず、レジストリ（taxon・place）だけを
先に正しくする。** ファクトの構築（occurrence テーブルそのもの）は O-1/O-2 に回す。

## 2. オーナーの決定（2026-09-22）

- **F1 taxon の ID 空間の混線** → **今 `common:taxon:inat.<id>` の名前空間を分けて
  作り直す**（occurrence が taxon_id を参照する前の今が、ID を動かしても参照が壊れない
  唯一の時点。ADR-0004「ID は不変」の例外として記録する）
- **F3 流域への解決** → **ADR-0006 規約2を改定し、点のファクトは複数の面の place に
  直接解決してよい**（記録×place の対応表、basis にポリゴンの版）。place_relation は
  面どうしの関係。キューブは正確な点内包判定、v1 互換の射影は L2 から再現して機械で検証
  （O-2。**この PR（Slice 0）では着手しない**）
- **F4 規約4（粗い座標）** → **機械グリッド（grid01）には常に解決し、
  `coordinate_uncertainty_m` を occurrence に運ぶ。規約4は地点のような細かい単位への
  解決と、公開時の一般化（ADR-0018）に適用**（O-1。**この PR では grid01 の place だけ
  先に整える**）
- （設計者が推奨どおり決定）F2 分類の補完は taxon レジストリの属性＋
  `registry/taxon/taxon_group.yaml`／F5 occurrence キューブは `source_id` を次元に持つ
  （O-1）／F6 記録の旗（RL 原表記・is_alien・license_class・vernacular_name）は
  observation の `unit_raw` と同じ流儀で原表記として occurrence に運び、射影だけが読む
  （O-1）

## 3. 実測（読み取り専用。すべて `data/db/ryuiki.sqlite` / `derived.sqlite` で確認）

### F1: iNat の taxon_key は GBIF キーではない

`scripts/m03_organisms.py` は iNat 行の `taxon_key` に iNaturalist の `taxon.id` を、
GBIF 行には GBIF `taxonKey` を入れている（`organism_records.source_id` が
`inaturalist_kanagawa`/`gbif_kanagawa_occurrences` の2値で出典を判定できる）。
旧 `scripts/registry/build_taxon.py` は両方を `common:taxon:gbif.<key>` として登録していた。

distinct taxon_key: GBIF のみ 19,626 / iNat のみ 13,969 / **両方に現れる9件**。
9件は偶然の数値の一致で**8件は別種**（例: key `8026` = GBIF 科 *Axiidae*（1行）
vs iNat *Corvus macrorhynchos*（515行）。`7046` *Chromodorididae*/*Aythya fuligula*、
`5268` *Phalacrocoracidae*/*Milvus migrans* も同様。key `1` だけ両方 kingdom
*Animalia* で名前は一致するが、実体（GBIF backbone のノード ID と iNat の
taxon.id）は別物）。出典内では `taxon_key → 二名法キー(binom)` が関数
（distinct (source_id, taxon_key) 33,613組で違反0件、`_assert_taxon_key_maps_to_single_binom()`
で機械検証）。

### F2: 分類の補完

GBIF 行では `(kingdom, phylum, class)` は taxon_key の関数（不整合0）。iNat 行は
3列とも全行 NULL（`c03_inaturalist.py` が ancestors を取れていない）→ 補完は
occurrence ではなく taxon の属性として持たせる。

v1（`web/scripts/build-biota.mjs` の `org_norm`）: `cls = COALESCE(記録の class,
二名法キーの多数決 class, 属の多数決 class)`、`kdm = COALESCE(記録の kingdom,
二名法キーの多数決 kingdom)`、`phy = COALESCE(記録の phylum, 二名法キーの多数決 phylum)`。
多数決は `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY COUNT(*) DESC)` で同数の
決め方が無い（実装依存の暗黙順）。

同数: 二名法キー単位の多数決（`bc`/`bp`）に0件、**属単位の多数決（`gc`）に3属**
（異界ホモニム: *Martensia* 紅藻/端脚類、*Stilbum* 菌/ハチ、*Sirosporium*）。
影響は**1 taxon**（GBIF `Sirosporium celtidis`、own class NULL）のみ
（他の2属は実際にその属多数決を必要とする taxon が無かった）。taxon_group は
両候補（Dothideomycetes/Sordariomycetes）とも「菌類」で変わらない。

iNat の補完到達率（レジストリの taxon 単位、distinct (namespace, taxon_key) 13,978件）:
`classification_basis` の内訳は本 PR のビルドログ参照（§5）。

### F3: 流域

v1（`web/scripts/build-geo.mjs`）は記録ごとの ray-casting の点内包判定（W12 1977年版
377面、不正ポリゴン7、重なる対4だが重なりに落ちる記録0）。`Math.round(x*1000)` の
0.001° の memo で「バケットの最初の記録の実座標」の結果が全員に配られる。

shapely で `ORDER BY rowid` に実装すると `org_watershed_year` 10,699行・
`org_watershed` 287行が完全一致。割当 732,707/816,856（89.7%）。

memo vs 正確な PIP: **11,306 記録が別の結果** → `org_watershed_year` 1,091/10,699
キー、`org_watershed` 185/287 行が変わる。走査順依存: rowid 逆順で 1,179キー/169行、
record_id 順で 1,011キー/145行が変わる。

grid01→流域: 1,145/4,086 セル（28%）が2流域以上にまたがり 441,362 記録（54%）を
含む。セル中心規則で 20.0%、セル多数決で 7.7% の記録が別流域。`species_n` は
セル多数決で 6,056/10,699 行が変わる。v1 の `species_n` は binom ではなく
**scientific_name 全文**で DISTINCT。

**F3 は O-2 の対象。この PR では着手しない。**

### F4: 粗い座標

`coordinate_uncertainty_m`: NULL **613,326（75%）** / ≤100m 149,697 / ≤500 28,431 /
≤1km 7,261 / ≤10km 12,255 / >10km 5,886。文字どおり適用すると 631,467行（77.3%）が
解決不能、`mesh_year` の 37,043 キーのうち 23,958 が消える。iNat の obscured 座標
（positional_accuracy 最大 6,818km、20km 以上 621行）は v1 もそのまま集計している。

**F4 の occurrence キューブへの適用は O-1 の対象。この PR では grid01（機械グリッド）の
place だけを先に整える（規約4は地点等の細かい単位への解決に適用し、grid01 には
適用しない、というオーナー決定に沿う）。**

### 主語・期間

`organism_records` 823,692（GBIF 658,360 / iNat 165,332）。`record_id` は PK・重複0。
`is_synthetic` 全行0。

v1 org_norm は `observed_on` NULL 6,836行（GBIF 6,592 / iNat 244）を落として
816,856行。→ occurrence には**残して**キューブ対象外とする設計（O-1、ADR-0007 原則1）。

### 座標・grid01

lat/lon NULL **0行**（823,692行全件に座標がある）。範囲 lat 35.00–35.80 /
lon 138.81–139.80。

org_norm の distinct (mlat,mlon) = 4,086、旧レジストリ（`derived.mesh_all` 由来）
= 4,083。**3セル**（(3521,13898)(3544,13913)(3544,13968)、6行、1970年より前のみ）が
`derived.mesh_all` の年フィルタ（`yr BETWEEN 1970 AND 2026`）で弾かれて place に
無かった。**+1セル**（(3537,13977)、iNat 1行、`observed_on` NULL）は
`organism_records` の座標を直接使うと初めて拾える。本 PR で grid01 の入力を
`derived.mesh_all` から `ryuiki.organism_records` の座標に変え、**4,087セル**にした
（詳細・日付の無い記録を含めるかの判断根拠は `registry/README.md`「grid01 の入力を
`derived.mesh_all` から `organism_records` の座標に変える」）。

## 4. 縦線の切り方（採用）

- **Slice 0（レジストリ整備。ファクトを作らない・v1 の値は変わらない。本PR）**:
  F1・F2・grid01 を記録の座標から生成（+4セル）。
- **O-1（grid01 の10表）**: `occurrence` ファクト → キューブ拡張（source_id を次元に、
  stat=count 等）→ 件数系6表（org_norm・mesh_year・mesh_all・mesh_species・
  effort_year・org_group_year）→ 二名法への巻き上げ系4表（species2・species_year2・
  species_month・species_mesh_year）。規約4の改定。
- **O-2（流域2表）**: 規約2の改定 → 記録×流域の直接解決 → v1 の memo 規則を射影で
  再現＋機械検証（総件数の保存、動いた記録数 11,306 の一致）。

## 5. 本PR（Slice 0）でやったことと実測

対象ファイル: `scripts/registry/build_taxon.py`（全面書き換え）、
`scripts/registry/build_place.py`（grid01 節）、`scripts/registry/common.py`
（`taxon_id_inat()`、`DERIVED_TABLES_READ` から `mesh_all` を除去、
`insert_many()` の列名クオート）、`scripts/schema_registry.sql` /
`web/src/db/schema-registry.ts`（`taxon` に列追加）、
`registry/taxon/taxon_group.yaml`（新規）。

### F1: taxon_id の名前空間分割

フルビルド（`RYUIKI_REGISTRY_DB=<worktree>/data/db/registry.sqlite
python3 scripts/r01_build_registry.py`）実測:

```
[taxon] F1機械検証OK: 出典内で taxon_key→二名法キーが関数（33,613組）
[taxon] distinct (namespace, taxon_key) = 33,613（gbif 19,635 / inat 13,978）
[taxon] gbif/inat行 = 35,212 (occurrence のみ 32,877 / occurrence+taxa 736 / taxa のみ 1,599)
```

`taxon.taxon_id` の名前空間別件数: `common:taxon:gbif.*` 21,234件（occurrence由来
19,635 + taxa-only 1,599）、`common:taxon:inat.*` 13,978件。旧衝突9件の実例
（`common:taxon:gbif.8026` / `common:taxon:inat.8026` を実際に build した
`registry.sqlite` から抽出。以下いずれも正しく分かれている）:

| key | gbif 側 | inat 側 |
|---|---|---|
| 8026 | Axiidae（科, 甲殻類, class=Malacostraca） | Corvus macrorhynchos（種, 鳥類, class=Aves） |
| 7046 | Chromodorididae（科, 貝類・軟体動物） | Aythya fuligula（種, 鳥類） |
| 5268 | Phalacrocoracidae（科, 鳥類） | Milvus migrans（種, 鳥類） |
| 1 | Animalia（kingdom, その他無脊椎動物） | Animalia（kingdom, 未判定=own分類なし） |

### F2: 分類補完の検証

`classification_basis` 内訳（taxon 単位、gbif+inat 計35,212件）:

```
{'unresolved': 5266, 'source': 20186, 'genus_match': 3658, 'binomial_match': 6102}
```

`derived.sqlite` の `org_norm`（816,856行）との record 単位の突き合わせ
（各記録の `taxon_id` を引いて `class`/`kingdom`/`phylum`/`taxon_group` を再計算し
`org_norm.cls`/`kdm`/`phy`/`taxon_group` と比較）: **突き合わせ対象 816,081行
（org_norm 816,856行のうち775行は `taxon_key` 自体が無く、元々 `taxon_id` 解決の
対象外——`scientific_name` も空文字の記録）。不一致 1件**（`gbif_kanagawa_occurrences__1829967465`、
`Sirosporium celtidis`、属単位の多数決が同数だったケース。v1 は
`Sordariomycetes` を選んでいたが、本ビルダーの明示規則（件数降順・同数ならclass昇順）
は `Dothideomycetes` を選ぶ。`taxon_group` はどちらも「菌類」で変わらない）。
この1件は `taxon.status='needs_review'` で可視化されている。

同数だった属単位の多数決は3属あったが（*Martensia*・*Stilbum*・*Sirosporium*）、
実際に不一致を生んだのは *Sirosporium* の1 taxon だけ（他の2属はそもそも
その属多数決に頼らないといけない taxon がその属内に存在しなかった）。

### grid01 の place

件数: 4,083（旧、`derived.mesh_all` 由来）→ **4,087**（新、`organism_records` の
座標から直接）。v1 の `mesh_species`（`derived.sqlite`、4,086セル、全年・日付フィルタ無し）
との突き合わせ: **4,086セル全件が新 grid01 place に解決できる（欠落0）**。
新 grid01 はこれに加えて `observed_on` が NULL の記録しか持たない1セルも含むため
4,087セル。

### 既存のゲートが動かないことの確認（受け入れ条件5）

`grep` で確認: `scripts/b03_build_observation.py`・`b04_build_cube.py`・
`b05_project_v1.py` のどこにも `taxon_id`/`grid01` への参照が無い（`taxon_id` は
そもそも登場せず、`place_id` は `place_source_ref(source_id='sites.site_id')`
経由の `site` place_kind だけを使う。grid01 の `place_source_ref.source_id` は
`organism_records.lat_lon` で `site` とは別値なので、`b03` の `LEFT JOIN`
条件には元々ヒットしない）。measurements/sensor の縦線（Phase B 既存ゲート）は
本 PR の影響を受けない。

## 6. 再現の壁・申し送り

- **O-1/O-2 はまだ設計のみ**（本ドキュメント §4 の切り方の記述だけで、実装は
  無い）。`occurrence` テーブルの DDL・キューブ拡張（`source_id` を次元に追加）・
  射影の設計は O-1 着手時に別ドキュメントで詳細化する。
- **F3（流域の点内包判定）は本 PR で一切触れていない。** ADR-0006 規約2の改定
  （複数面への直接解決）は O-2 で ADR 追記とセットで行う。
- **taxon の `parent_taxon_id`（ADR-0019 の図にはあるが実装に無い）は本 PR でも
  追加していない。** 上位分類は `kingdom`/`phylum`/`class`/`order`/`family` の
  フラット列で持つ（v1 の `org_norm` と同じ形）。ツリー構造が要る消費者が現れたら
  改めて設計する。
- **`docs/plans/PHASE_B_INTAKE.md` #8**（`taxon.accepted_taxon_id` 全行NULL）・
  **#10**（GBIF弱一致300件のunresolved化）・**#11**（`place_kind='grid01'` が
  ADR-0006のコードリストに無い）は本 PR のスコープ外のまま（#11 は grid01 の
  **入力**を変えただけで、コードリストからの逸脱自体は解消していない。詳細は
  `docs/plans/PHASE_B_INTAKE.md` #16）。
