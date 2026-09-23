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

`classification_basis` 内訳（taxon 単位、gbif+inat 計35,212件。`unresolved`
（`taxa`由来6,242件）を含めた全体は §6 で改めて示す）:

```
{'unresolved': 5266, 'source': 20186, 'genus_match': 3658, 'binomial_match': 6102}
```

（この節は初回実装時点の実測をそのまま残す。独立レビュー後の値は
`classification_basis='unresolved'` → `'no_match'` に改名されている——§6参照。
件数自体は改名の前後で変わらない。）

`derived.sqlite` の `org_norm`（816,856行）との record 単位の突き合わせ
（各記録の `taxon_id` を引いて `class`/`kingdom`/`phylum`/`taxon_group` を再計算し
`org_norm.cls`/`kdm`/`phy`/`taxon_group` と比較）: **突き合わせ対象 816,081行
（org_norm 816,856行のうち775行は `taxon_key` 自体が無く、元々 `taxon_id` 解決の
対象外——`scientific_name` も空文字の記録）。不一致 1件**（`gbif_kanagawa_occurrences__1829967465`、
`Sirosporium celtidis`、属単位の多数決が同数だったケース。v1 は
`Sordariomycetes` を選んでいたが、本ビルダーの明示規則（件数降順・同数ならclass昇順）
は `Dothideomycetes` を選ぶ。`taxon_group` はどちらも「菌類」で変わらない）。
この不一致件数（1件）は独立レビュー後も変わらない（§6 の修正は `status`/
`classification_basis` の**値の意味付け**を直すものであり、`class`/`kingdom`/
`phylum`/`taxon_group` の**値そのもの**は変えていないため）。

同数だった属単位の多数決は3属あった（*Martensia*・*Stilbum*・*Sirosporium*）。
このうち `org_norm` との不一致を生んだのは *Sirosporium* の1 taxon だけ
（他の2属はそもそもその属多数決に頼らないといけない taxon がその属内に
存在しなかった）。ただし「同数の属多数決を使った taxon 自体」はこの3属の中に
複数存在しうる——`status='needs_review'` にすべき件数は §6 で独立に集計し直した。

### grid01 の place

件数: 4,083（旧、`derived.mesh_all` 由来）→ **4,087**（新、`organism_records` の
座標から直接）。v1 の `mesh_species`（`derived.sqlite`、4,086セル、全年・日付フィルタ無し）
との突き合わせ: **4,086セル全件が新 grid01 place に解決できる（欠落0）**。
新 grid01 はこれに加えて `observed_on` が NULL の記録しか持たない1セルも含むため
4,087セル。

### taxon の新しい列は D1 に載せない（オーナー決定）

`kingdom`/`phylum`/`class`/`order`/`family`/`classification_basis`/
`canonical_binomial`/`taxon_group` は `scripts/schema_registry.sql`（`registry.sqlite`）
にはあるが、`web/src/db/schema-registry.ts`（D1）には**意図的に追加しない**。
`web/scripts/seed-d1-local.mjs` は「D1 の列 ∩ 元の列」の交差だけを INSERT する実装
（元にしかない列は黙って無視。`PRAGMA table_info` の交差を取る）なので、
D1 側のスキーマを変えなくてもシードは壊れない。D1 は捨てて作り直せる配信キャッシュ
（ADR-0001）で、これらの列を読む web 側の消費者がまだ無い——`place_relation` を
D1 に載せなかったのと同じ判断（`registry/README.md`「`place.region_id` と
`place_relation`」）。使う側が現れた時点で改めて D1 側にも足す。
**`status='needs_review'` だけは既存の `status` 列にそのまま値として乗るので、
D1 側のスキーマ変更なしで既にシードされている**（実測: ローカル D1 を
`db:reset`→`db:migrate --local`→`db:seed` で作り直し、`taxon` テーブルが
元の7列のまま 41,454行シードされ、`common:taxon:gbif.2621284`
（Sirosporium celtidis）の `status` が `needs_review` になっていることを確認）。

### 既存のゲートが動かないことの確認（受け入れ条件5）

`grep` で確認: `scripts/b03_build_observation.py`・`b04_build_cube.py`・
`b05_project_v1.py` のどこにも `taxon_id`/`grid01` への参照が無い（`taxon_id` は
そもそも登場せず、`place_id` は `place_source_ref(source_id='sites.site_id')`
経由の `site` place_kind だけを使う。grid01 の `place_source_ref.source_id` は
`organism_records.lat_lon` で `site` とは別値なので、`b03` の `LEFT JOIN`
条件には元々ヒットしない）。measurements/sensor の縦線（Phase B 既存ゲート）は
本 PR の影響を受けない。

## 6. 独立レビュー（/code-review・/simplify）を受けた修正と実測

Slice 0（HEAD `6a71b94`）に独立レビューを走らせ、オーナーが採否を決めた8件
（code-review 4件・修正の深さ2件・効率1件・単純化/再利用は代表8件のうち影響の
大きいもの）を反映した。**taxon_id と class/kingdom/phylum/taxon_group の値は
変えていない**（下記で明示したもの以外）。以下すべて実際にフルビルドを走らせて確認。

**レジストリの中身の差が意図どおりだけであることの検証**（修正前・修正後それぞれで
`build_taxon.build()` を実行し、`taxon` テーブルを全行 diff）:

```
taxon_id の集合: 完全一致（41,454件、片方にしかない行は0件）
scientific_name / canonical_binomial / rank / kingdom / phylum / class / order /
  family / gbif_taxon_key / vernacular_name_ja / accepted_taxon_id / taxon_group:
  全41,454行で完全一致（diff 0）
status が変わった行: 50件（すべて旧→'needs_review'。逆方向・無関係な変化は0件。
  旧時点で既に needs_review だった1件——Sirosporium celtidis——と合わせて
  新の needs_review 総数51件と一致）
classification_basis が変わった行: 8,025件（すべて旧'unresolved'→新'no_match'の
  改名のみ。それ以外の値の変化は0件）
```

`place`/`place_source_ref`/`place_relation`/`unit`/`variable`/`variable_alias`/
`caveat`/`caveat_scope` は本ラウンドでコードを変えていないため未検証（変更対象外）。

### 6-1. 分類が不確かな taxon の可視化を2点補強

1. **unresolved（taxa由来）行でも needs_review が分かるようにした**
   （旧実装は `status='unresolved'` を絶対に上書きせず、分類の多数決が同数でも
   隠れていた）。実例: *Martensia flabelliformis*（`common:taxon:ryuiki-taxa.
   martensia_flabelliformis`）は属 *Martensia* の多数決が紅藻綱
   Florideophyceae 2件 対 （端脚類側の）綱2件の同数で、`class` は
   `Dothideomycetes`型の規則で決定論的に選ばれるが、taxon_group が丸ごと
   変わりうる不確かさは以前は可視化されていなかった。今は
   `status='needs_review'` になる。
2. **属の多数決で補完した taxon は、同数でなくても属自体が複数の class に
   またがれば needs_review にする**。実測: 該当属 **26属**（アドバイザー概算と
   一致。例: `Ficus`・`Stellaria`・`Juncus` 等）。**3属の完全同数（*Martensia*・
   *Stilbum*・*Sirosporium*）はこの26属の部分集合**（2グループが同数で並ぶ時点で
   その属は自明に複数classを含むため）。

**実測（フルビルド、`status='needs_review'` の内訳）**:

```
needs_review 合計 = 51（gbif 1 / inat 23 / ryuiki-taxa(unresolved由来) 27）
全51件とも classification_basis='genus_match'
```

`status='accepted'` 35,188 / `status='needs_review'` 51 /
`status='unresolved'` 6,215（= 6,242 − 27）。合計 41,454 = `taxon` の総行数
（`reports/registry_resolution.md` §7 で機械的に検算——後述6-2）。

**kingdom 単独の同数（code-review指摘2、own class はあるが own kingdom が
二名法多数決で同数のケース）は、実データでは0件**（全51件が genus_match 経由
のため）。ただしこれは「今のデータでは起きていない」だけで、`_resolve_classification()`
の機械検証（`scripts/tests/test_registry_taxon.py::
test_kingdom_only_tie_marks_needs_review_even_with_own_class`）はこの経路を
実際に踏んで確認している——将来データが増えて発生したときに黙って見逃さない
ようにする、という指摘の趣旨どおりの「潜在バグの修正」。

### 6-2. `reports/registry_resolution.md` の内訳を固定2値から全 status 集計に直す

`scripts/r02_resolution_report.py` が `status='accepted'`/`'unresolved'` の
2つしか数えておらず、`needs_review` が内訳から漏れて合計が
`registry_taxon_total` と一致しなかった（code-review指摘4）。`GROUP BY status`
に直し、実測で合計が一致することを確認（35,188 + 51 + 6,215 = 41,454）。

### 6-3. taxon_key ごとの代表選びを完全に決定的にする

`_load_occurrence_representatives()` の `ROW_NUMBER` タイブレークに分類列
（kingdom/phylum/class/order/family）を追加し、`counted` の GROUP BY キー全体を
並びに含めることで理論上も曖昧さを無くした。さらに「最頻値の件数そのものが
複数候補で並ぶ」ケースが無いことを機械検証する assert を追加した
（code-review指摘3）。**実測: 33,613件全件で違反0件**（`F2機械検証OK` ログ）。

### 6-4. 「出典→名前空間」の正を切り出す

`SOURCE_NAMESPACE` は `build_taxon.py` の private 定数だったため、レジストリを
経由しない読み手（`scripts/x01_dwca.py` の DwC-A 書き出し。`occurrence.txt` の
`taxonID` 列に `organism_records.taxon_key` を出典の区別なく生のまま書いている）
に届いていなかった（code-review指摘5）。正を `build_taxon.py` の外（当初は
`scripts/common.py`、後に `scripts/taxon_namespaces.py` に移動——経緯は
§9「CI失敗の修正」参照）の `TAXON_KEY_SOURCE_NAMESPACE` に移し、`build_taxon.py`
の SQL の CASE 式もそこから組み立てるようにした（ハードコードの重複を解消）。
**`scripts/x01_dwca.py` の書き出し自体は本PRでは直していない**（公開物の
意図的な変更になるため別PR。`docs/plans/PHASE_B_INTAKE.md` #17 に起票した）。

### 6-5. grid01 の鮮度検知の後退を直す

grid01 の入力が `derived.mesh_all`（指紋の対象）から `ryuiki.organism_records`
（指紋の対象外）に変わったことで、`m0x_*.py` が `organism_records` に新しい
座標を追記しても `--check-fresh` がそれを検知できなくなっていた（以前は
`build:derived` を挟む標準手順が間接的に伝播させていたが、その経路が無くなった。
code-review指摘7）。`organism_records` の軽い代理指標（行数・最大rowid）を
full モードの指紋に追加した。

**実測（COUNT(*)/MAX(rowid) の選択根拠）**: `SELECT COUNT(*), MAX(rowid)` を
1クエリにまとめると約160ms（SQLiteが2つの集約を同時に満たそうとしてインデックスの
高速経路を使えなくなる）。`SELECT COUNT(*)` と `SELECT MAX(rowid)` を別々に
2回打つと合計約5ms（それぞれ約5ms・ほぼ0ms）。+200ms の閾値を大きく下回るため、
2クエリ形式で両方採用した（`MAX(rowid)` だけへの縮退は不要だった）。

**`--check-fresh` の所要時間（前後）**:

| | `compute_input_fingerprint(mode=full)` 単体 | `--check-fresh` サブプロセス全体 |
|---|---|---|
| 修正前 | 約6ms | (未計測。今回計測した後の値のみ) |
| 修正後 | 約11ms（+5ms） | 約49〜59ms（Python起動オーバーヘッドが大半） |

「行数・最大rowidが変わらない書き換え（UPDATE、例: license列のバックフィル
再実行）は検知できない」という限界は明示的に残した（軽い代理指標という設計の
性質上の割り切り。`common.py` のコメント参照）。

### 6-6. 分類の多数決3関数の統合（効率）

`_load_binom_class_majority`/`_load_genus_class_majority`/
`_load_binom_phylum_majority` がそれぞれ独立に `organism_records` をスキャンし、
二名法キー(binom)を計算し直していたのを、1回だけ一時テーブル
（`_classification_population`）に落としてから3つの多数決を集計する形に
直した（code-review指摘8、simplify指摘9で1つの汎用関数 `_majority_vote()` にも
統合）。

**実測（`build_taxon.build()` 単体、`ryuiki.sqlite` 823,692行、同一マシンで
3回計測し安定した値。r01 全体ではなく taxon ステップだけを切り出して計測）**:

```
旧: _load_binom_class_majority + _load_genus_class_majority + _load_binom_phylum_majority
    = 3.28s + 5.46s + 2.95s = 11.69s（3関数合計）
    build_taxon.build() 全体 = 23.40s

新: _create_classification_population + 3×_majority_vote + _load_multi_class_genera
    = 6.79s + (1.56s + 1.10s + 1.26s) + 0.81s = 11.52s
    build_taxon.build() 全体 = 23.69s
```

**「約6秒減る」というアドバイザーの概算は実測では再現しなかった。** 3関数の
統合そのものは約1秒の短縮（11.69s→10.71s、`_load_multi_class_genera` の0.81sを
除く）にとどまり、同じPRで追加した正しさ担保のチェック（6-1の複数class属検出
0.81s、6-3の代表選びタイブレーク強化で `_load_occurrence_representatives` が
約6.3s→約8.1s に増加）がほぼ同じだけ時間を使うため、**`build_taxon.build()`
全体の所要時間は実質的に変わらない**（23.40s→23.69s、フル `r01` 全体では
約27.3s→約27.6s、体感差なし）。効率だけを見れば期待した改善は得られなかったが、
3関数の重複コードを1つの `_majority_vote()` に統合したこと自体（simplify指摘9）
と、6-3の正しさ強化は独立に価値があるため両方とも採用した。

### 6-7. classification_basis の改名（`unresolved` → `no_match`）

`classification_basis='unresolved'`（分類の多数決が引けない）と
`taxon.status='unresolved'`（GBIF backbone未照合）が同じ文字列で意味が違い
紛らわしかったため、前者を `'no_match'` に改名した（simplify指摘11）。
`registry/README.md`・`scripts/schema_registry.sql`・
`web/src/db/schema-registry.ts`・本ドキュメントのコメントを合わせて更新した。
値の意味は変わらない（文字列だけの変更）。

### 6-8. その他の単純化（simplify指摘9・10・12・13・14）

- taxon 行を組み立てる2箇所の dict リテラルを `_build_taxon_row()` に統合。
- `_resolve_classification()` の `bc.get(binom)` を1回計算に、
  `_pick_taxa_representative()` の同一引数2回呼び出しを1回に、未使用の
  `import pathlib` を削除。
- `registry/taxon/taxon_group.yaml` の読み込みに、`build_place._load_zone_yaml()`/
  `build_caveat._load_caveat_yaml()` と同じ流儀で match 条件の重複検知を追加
  （実測: 重複0件）。`open()` も `<Path>.open()` に統一。
- 同じ経緯（9件衝突・8026の例・ADR-0004例外の理由等）が8箇所に全文コピーされて
  いた指摘を受け、**決定と理由の正を ADR-0019 の追記、実測の正を本ドキュメント**
  に一本化し、他（`build_taxon.py`・`common.py`・`schema_registry.sql`・
  `schema-registry.ts`・`web/src/lib/registry/index.ts`・`registry/README.md`）は
  「なぜこの形か」を1〜2文＋参照に縮めた。

## 7. 2回目の独立レビュー（/code-review）を受けた追加修正と実測

§6（HEAD `6a294a9`〜`674ea99`）に再度 `/code-review` をかけて4件出た。
**taxon_id と分類の値（class/kingdom/phylum/order/family/taxon_group/
canonical_binomial）は今の値から変えない**のが前提——実際、実データでの
検証（後述）では**この4件どれも現在の出力を1行も変えていない**（すべて
将来のデータ・辺縁ケースに備えた防御的な修正）。

### 7-1. 名前空間が Python の3箇所で2つに決め打ちだった（medium）

`n_by_ns = {"gbif": 0, "inat": 0}` と、taxon_id の組み立て・`gbif_taxon_key` を
埋めるかどうかの判定が `if ns == "gbif" else ...` の2値決め打ちで3箇所にあった。
`TAXON_KEY_SOURCE_NAMESPACE`（この時点では `scripts/common.py`。後に
`scripts/taxon_namespaces.py` に移動——§9参照）に3つ目の出典を足しても、
これらは追随せず、`n_by_ns[ns] += 1` は `KeyError`、taxon_id の組み立ては
黙って `inat.` 扱いになって F1 が直した衝突が戻る欠陥があった。

`build_taxon.py` に「名前空間ごとの性質」の小さな対応表 `_NAMESPACE_TRAITS`
（名前空間 → `id_builder`/`fill_gbif_taxon_key`）を新設し、`_assert_namespaces_have_traits()`
で `TAXON_KEY_SOURCE_NAMESPACE` の全名前空間が `_NAMESPACE_TRAITS` に対応する
エントリを持つことをビルド開始直後に確認するようにした（無ければ明示的に
`ValueError`）。`n_by_ns` も固定2キーの辞書ではなく `occ.keys()` から動的に
集計する形に直した。

実測: フィクスチャで3つ目の名前空間（`TAXON_KEY_SOURCE_NAMESPACE`）を
`_NAMESPACE_TRAITS` 無しで足すと `_assert_namespaces_have_traits()` で
明示的に止まること、対で足すと正しい形の taxon_id になり既存の gbif/inat と
衝突しないことを確認した（`scripts/tests/test_registry_taxon.py`
`test_new_namespace_without_traits_raises_immediately`/
`test_new_namespace_with_traits_gets_correct_id_and_no_collision`）。

### 7-2. kingdom の needs_review 判定が (class,kingdom) の組の同数を誤って流用していた（low）

`_majority_vote()`（bc: 二名法キー→(class0, kingdom0) の組の多数決）の
`is_tied`（組全体が同数かどうか）を、class の needs_review 判定にも kingdom の
needs_review 判定にもそのまま使っていた。しかし bc は (class0, kingdom0) の
**組**の同数であり、例えば (ClassA, Animalia)×2 と (ClassB, Animalia)×2 が
同数のとき、class は確かに曖昧（A/B で割れる）だが kingdom はどちらも
Animalia で一致しており曖昧ではない。`is_tied` だけを見ると kingdom 側も
誤って `needs_review` にしてしまっていた。

**値の選び方（多数決の勝者）は変えていない**（v1 の `org_norm` と同じ
「組」単位の多数決のまま）。`_majority_vote()` が、同数で並んだ候補どうしで
実際に値が食い違った列だけを `ambiguous_cols` として返すように拡張し
（`COUNT(DISTINCT col)` を同数グループ内で数える。NULL は distinct 集計から
除外されるため「NULL vs 実値」は食い違いとして扱わない——実値の方を採用する
NULL-last の判断と整合する）、`_resolve_classification()` は列ごとに
`ambiguous_cols` を見て判定するようにした。

あわせて、同数のタイブレークで **NULL を最後に回す**ように直した
（`(col IS NULL), col ASC`）。以前は kingdom0 が NULL の候補が同数で先頭に
来ると kingdom が NULL に落ち、`taxon_group` が「未判定」になりうる欠陥が
あった（実データでは bc の同数自体が0件のため顕在化していない）。

実測: フィクスチャで (ClassA,Animalia)×2 vs (ClassB,Animalia)×2 の同数では
kingdom 側に needs_review が付かないこと、(ClassA,NULL)×2 vs (ClassA,K)×2 の
同数では NULL ではなく K が選ばれることを確認した
（`test_class_tie_with_matching_kingdom_does_not_mark_kingdom_needs_review`/
`test_bc_tie_null_last_prefers_non_null_kingdom`）。実データでは bc の同数が
0件のため、この修正による実出力への影響は無い（後述7-5）。

### 7-3. 新しい assert が同数1件でビルド全体を止めていた（low）

`_load_occurrence_representatives()` に足した「taxon_key ごとの代表選びで
最頻値の件数が同数の候補は無い」という assert が、著者引用の有無や rank の
表記ゆれだけで2レコードに分かれ件数が同点になるケースでも無条件に
`AssertionError` を投げていた。これはレジストリのビルド全体（ひいては
`ensure-registry.sh` → `docker compose up` の起動）を、分類には無関係な
表記ゆれ2件だけで止める欠陥だった。

assert をやめ、既存の決定論的なタイブレーク（分類列を含めた全列の昇順、
NULL-last）で選ぶようにした。そのうえで、同数の候補どうしで**分類列
（kingdom/phylum/class/order/family）が実際に食い違うときだけ**
`representative_ambiguous=True` を返し、`build()` がこれを `needs_review`
に反映する（学名の表記ゆれ・rank違いだけなら黙って選ぶ）。

実測: フィクスチャで著者引用だけが違う2レコードの同数ではビルドが止まらず
`needs_review` にもならないこと、分類が食い違う同数では `needs_review` に
なることを確認した
（`test_representative_selection_tie_with_only_naming_difference_does_not_stop_build`/
`test_representative_selection_tie_with_classification_conflict_marks_needs_review`）。
実データでは `_load_occurrence_representatives()` の同数自体が0件
（33,613件全件確認、後述7-5）のため、この修正による実出力への影響は無い。

### 7-4. 指紋が古いときのメッセージに organism_records が出ていなかった（low）

`scripts/r01_build_registry.py` の `_check_fresh()` が「古い」と判定したときの
1行メッセージが「derived.sqlite/taxon_crosswalk.csv が変わった」としか言わず、
§6-5 で指紋に足した `ryuiki.organism_records` の軽い代理指標が抜けていた。
メッセージに `ryuiki.organism_records` を追記した。

### 7-5. 実データでの検証: 7-1〜7-3 は現在の出力を1行も変えない

修正前（`674ea99` 時点）と修正後で `build_taxon.build()` をそれぞれ実行し、
`taxon` テーブル41,454行を全行 diff した結果:

```
taxon_id の集合: 完全一致
scientific_name/canonical_binomial/rank/kingdom/phylum/class/order/family/
  gbif_taxon_key/vernacular_name_ja/accepted_taxon_id/classification_basis/
  taxon_group: 全41,454行で完全一致（diff 0）
status: 差分0（needs_reviewに新たになった行・外れた行のどちらも0件）
needs_review 総数: 51件（修正前後で不変）
```

理由: 7-1（名前空間の一般化）は現状2つの名前空間（gbif/inat）だけなら
挙動が変わらないリファクタリング。7-2（kingdom の ambiguous_cols）は、
実データでは bc（二名法キー単位の多数決）の同数が0件（`docs/plans/
PHASE_B_OCCURRENCE.md` §3 F2参照）なので影響しようがない。gc（属単位、
companion列なし）は元々 `is_tied` と `ambiguous_cols` が数学的に同値
（1列の投票に companion が無いため）で、こちらも無変化。7-3
（`_load_occurrence_representatives` の同数緩和）は、実データではこの
関数の同数自体が0件（全33,613件を確認）なので、assert を消しても
「同数の代表がある」という状況そのものが発生しない。

`org_norm`（816,856行）との突き合わせも不一致1件のまま
（*Sirosporium celtidis*、§6-1参照）で変わらない。4件とも「今は起きていない
辺縁ケースを、将来データが増えても黙って壊れないように機械的に担保する」
性質の修正であることを、実測によって確認した。

## 8. CI失敗の修正: `TAXON_KEY_SOURCE_NAMESPACE` を依存の無いモジュールに切り出す

PR #15 の CI が3ジョブとも `ModuleNotFoundError: No module named 'requests'` で
落ちた。§6-4 で `TAXON_KEY_SOURCE_NAMESPACE` を `scripts/common.py`（収集系の
共有モジュール）に移したが、そのモジュールは冒頭で `requests` を import して
いる。そのため `scripts/registry/build_taxon.py`（→ `r01_build_registry.py
--files-only`・`scripts/tests/test_registry_taxon.py`）が `requests` に
依存するようになった。CI は `requirements.txt`（PyYAML・pytest だけ）しか
入れないため落ちる。手元の `.venv` には `requests` が（収集スクリプト用に）
入っているため、この不整合はローカルでは再現しなかった。

「レジストリを経由しない読み手（`x01_dwca.py` 等）からも import できる、
レジストリのパッケージ（`scripts/registry/`）の外の1箇所」という意図は
保ったまま、**依存の無い小さなモジュール `scripts/taxon_namespaces.py`**
（標準ライブラリにも `requests` にも依存しない。import 時の副作用も無い、
`TAXON_KEY_SOURCE_NAMESPACE` の辞書リテラルだけを持つファイル）に切り出した。
`scripts/common.py` からは削除し、re-export もしない（`scripts/common.py` に
依存する既存の呼び出し元は無いことを確認済み——grep で `TAXON_KEY_SOURCE_NAMESPACE`
の参照は本PR自身のファイルだけだった）。`build_taxon.py` の import と、
エラーメッセージ・docstring・`registry/README.md`/`docs/plans/PHASE_B_OCCURRENCE.md`
中の参照先をすべて新モジュールに更新した。

**CI と同じ環境で確認**: scratchpad に `requests` の入っていない一時的な venv
（`python3 -m venv` + `pip install -r requirements.txt` だけ）を作り、その中で
`python3 -m pytest -q` と `RYUIKI_REGISTRY_DB=<tmp>/x.sqlite python3
scripts/r01_build_registry.py --files-only` が通ることを確認した（実測は
本PRのコミットメッセージ参照。venv は確認後に削除済み）。手元の `.venv`
（`requests` あり）でもフルビルド・`taxon` 41,454行・全生成物の差分0を
再確認した。

## 9. 再現の壁・申し送り

- **O-1a（`occurrence` ＋ `org_norm`）は実装済み**（`phase-b/occurrence-l2`。
  詳細・実測は §10）。**O-1b（`occurrence_agg` ＋ 年キー8表 ＋
  `species_month`）と O-2（流域2表）はまだ設計のみ**（本ドキュメント §4 の
  切り方の記述だけで、実装は無い）。キューブ拡張（`occurrence_agg`、
  `source_id` を次元に追加）・年キー8表・`species_month` の射影の詳細は
  O-1b 着手時に詰める。
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

## 10. O-1a（`occurrence` ＋ `org_norm`）実装・実測（`phase-b/occurrence-l2`）

設計の決定は [ADR-0025](../adr/0025-occurrence-fact-and-cube.md)（D1〜D4）に切り出した。
ここには実装したファイルと実測値だけを記録する。

### 構成

| ファイル | 役割 |
|---|---|
| `scripts/b06_build_occurrence.py` | `organism_records`（823,692行）から `data/db/v2.sqlite` の `occurrence` を作る（`observation`/`observation_agg` と同居） |
| `scripts/migrate/source_regions.py` / `source_regions.yaml` | 出典 → region、region → utc_offset の宣言（未知の出典・未使用宣言・件数不一致で止める） |
| `scripts/migrate/occurrence_period.py` / `occurrence_period_shapes.yaml` | `observed_on` の12形の宣言・展開・'Z' 変換（未知の形・件数不一致で止める） |
| `scripts/b08_project_occurrence_v1.py` | `occurrence` から `org_norm` を `data/db/v1_projection_occurrence.sqlite` に射影する（番号 b07 は O-1b のキューブ用に空けてある） |
| `scripts/reconcile/expected_diffs.yaml`（`org_norm:` 節） | *Sirosporium celtidis* の `cls` 1キーの宣言 |
| `scripts/tests/occurrence_fixtures.py` / `test_migrate_occurrence_period.py` / `test_migrate_source_regions.py` / `test_b06_build_occurrence.py` / `test_b08_project_occurrence_v1.py` | フィクスチャ sqlite だけで完結するテスト（原本不要） |

### 実測（`data/db/ryuiki.sqlite`/`registry.sqlite`、2026-09-22。ローカル実行）

```
occurrence 総行数            823,692
  日付あり（period_raw NOT NULL）  816,856
  taxon_id NULL               853（うち日付あり 775。775 は「日付ありの母集団
                               （org_norm と同じ）」での実測、853 はそれに日付
                               無し78行を加えた全体——taxon_key='' の記録に
                               日付の有無は関係しないため、両方が正しい実測）
  region 内訳                 jp-14 823,692（全行）
  期間の形（12形）             day 740,323 / day_interval 3,723 /
                               instant_millisecond_z 800 / instant_minute 26,042 /
                               instant_minute_z 958 / instant_minute_z_interval 57 /
                               instant_second 40,633 / instant_second_z 143 /
                               month 1,320 / month_interval 14 / year 1,797 /
                               year_interval 1,046（すべて宣言の expected_row_count
                               と一致）
  'Z' → ローカル時刻の変換件数   1,958（期待どおり）
  変換で日が変わった件数        221（期待どおり）
  変換で月が変わった件数        10（期待どおり）
  変換で年が変わった件数        0（1件でもあれば構築が止まる設計。実測どおり0）
```

`org_norm` 射影（`scripts/b08_project_occurrence_v1.py`）: **816,856行**
（v1 と一致。母集団は `occurrence.period_raw IS NOT NULL`）。

### 受け入れ基準1（`scripts/b02_derived_compare.py --tables org_norm`）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite --tables org_norm
一致: 0 / 宣言済み差分のみ: 1 / 不一致: 0
適用した宣言済み差分: 1件
EXIT=0
```

宣言なし（`--no-expected-diffs`）で実行すると、不一致は `org_norm` の `cls` 列
**1行だけ**（`gbif_kanagawa_occurrences__1829967465`、*Sirosporium celtidis*）で、
数値列（`is_alien`/`lat`/`lon`/`mlat`/`mlon`/`mo`/`yr`）は816,856行全件で
差分0（実測。`docs/adr/0025-occurrence-fact-and-cube.md` D3・D1 の「実測」節
参照）。

### 既存9テーブルのゲートが動かないことの確認（受け入れ基準2）

同じ worktree で `b03`→`b04`→`b05` を実行し直しても（`b06`/`b08` の追加後）:

```
observation: 1,041,003件（323,164 + 717,839。measurements/sensor_timeseries と一致）
observation_agg: 構築成功（v2.sqlite に occurrence と同居していても b04 は
  observation/observation_agg だけを作り直す——staged_table のテーブル単位の
  分離どおり）
v1_projection.sqlite: 749,300件（9テーブル合計。既存の実測値と一致）
b02 --tables meas_daily,meas_month,meas_year,meas_clim,site_var,var_catalog,
  sensor_daily,sensor_hour_month,rain_daily: 一致3 / 宣言済み差分のみ6 / 不一致0
  （既存の実測どおり）
```

`scripts/migrate/period.py` には `EntryUsage`（`_EntryUsage` の公開名。
`source_regions.py`/`occurrence_period.py` が再利用するための1行の追加のみ）
だけを足した。`b03` の出力（`observation` 1,041,003行）・既存テストは無変更
（`test_migrate_period.py`/`test_b03_build_observation.py` 全件成功）。

### 実行時間（初回実装時点）

```
scripts/b06_build_occurrence.py    23.2s（occurrence 823,692行の構築）
scripts/b08_project_occurrence_v1.py
  org_norm へ射影                  15.1s
  v1_projection_occurrence.sqlite に書き出し  4.1s
```

### この PR での設計からの逸脱・申し送り（初回実装時点。§11 の修正で解消したものは打消し線）

- `occurrence` は ADR-0007 が挙げる `observation` の列（`quality_stage`/
  `is_synthetic`/`source_ref`/`event_id`/`method_id`/`instrument_id`/
  `observer_id`）を持たない。`organism_records.is_synthetic` は全行0で、
  他の列も v1 のどの派生テーブルからも参照されないため、O-1 設計 v2 D1 が
  明示した列（F6 の原表記の旗＋識別子＋region/taxon/place/期間）だけに絞った
  （ADR-0025「影響」節に明記）。将来これらの列を使う消費者が現れたら追加する。
- ~~`org_norm.rank_l` を `taxon.rank`（taxon の属性）ではなく `lower(記録の
  taxon_rank)`（記録の原表記）から計算していた~~（§11 で修正。design v2 D3 は
  `rank_l` を `binom`/`cls`/`kdm`/`phy`/`ord`/`family`/`taxon_group` と同列の
  「taxon の属性」として挙げているが、初回実装はこの分類を見落とし、F6の
  「記録の原表記」側の列と誤って同じ扱いにしていた）。

## 11. 独立レビュー（`/code-review`）を受けた修正と実測

O-1a（HEAD `54b459f`）に `/code-review` をかけて15件の指摘（コードレビュー
指摘1〜15）を受け、すべて反映した。**実測どおり、`occurrence`/`org_norm` の
値は（指摘5の型変更を除き）1ビットも変わっていない**——修正前後でそれぞれ
実データからビルドし、正準化した sha256 で突き合わせて確認した（下記「値の
不変性を確認した方法」参照）。

### 反映した指摘（要約）

1. **`utc_offset` の厳密な検証**: `scripts/migrate/source_regions.py` の
   `load_source_regions()`/`validate_source_regions_shape()` に
   `UTC_OFFSET_PATTERN`（`^[+-][0-9]{2}:[0-9]{2}$`）を追加。符号無し
   （`"09:00"`）等を読み込み時点で拒否する（`_parse_utc_offset` の
   `sign = 1 if s[0]=='+' else -1` が黙って負に倒れる事故を防ぐ）。
2. **`\d` を `[0-9]` に**: `scripts/migrate/occurrence_period.py` の
   `_SHAPE_DEFS` の正規表現をすべて `[0-9]` に変更（Python の `\d` は既定で
   全角数字にもマッチする——実測で確認済み、`test_classify_shape_rejects_
   fullwidth_digits` で固定）。
3. **両端の実在検証**: `expand_period()` が全形で
   `datetime.date.fromisoformat`/`datetime.datetime.fromisoformat` を通し、
   `2020-02-30`・月13・`T24:00` 等を `InvalidPeriodValueError`（値と
   `record_id` を含む）で止める。区間は両端とも検証する。`b06` の T1 検査も
   `period_end` の `date()` 一致を見るようにした。
4. **形の定義はコードが正**: `occurrence_period_shapes.yaml` から `length`/
   `period_grain` を削除し、`expected_row_count`/`note` だけにした。
   `assert_declared_shapes_match_code()`（`b06` が実行時に呼ぶ）と
   `validate_occurrence_period_shapes_shape()`（CI）が、宣言された形の名前が
   コード（`_SHAPE_DEFS`）の12形と過不足なく一致することを検証する。
6. **`expected_row_count` を実行時にも検証**: `b06` が
   `validate_source_regions_shape()`/`validate_occurrence_period_shapes_shape()`
   を実行時にも呼ぶ。`expected_row_count` が整数であることを型で検証する
   （`.get()` で黙って検査を外さない）。
9. **形の分類は正規表現を順に試す**: `_SHAPE_BY_LENGTH`（文字数で決め打ち）を
   廃止し、`_SHAPE_DEFS` を全部試して一致した形を集める方式にした。2つ以上の
   形に同時に一致したら `AmbiguousPeriodShapeError`。**実行時間への影響は
   実測で誤差の範囲**（後述「実行時間（修正後）」）。
11. **`_assert_known_source_ids` の `sorted()` 修正**: `key=lambda v:
    (v is None, v)` で `None`/`str` 混在でも例外にならないようにした。
14. **座標の無い行を落とさない**: `occurrence.place_id`/`lat`/`lon` を
    NULLABLE にし、座標が無い行は `place_id`/`place_kind` を NULL のまま
    保持する（ADR-0007 原則1）。止めるのは「座標があるのに grid01 に解決
    しない」行だけ。実測: `organism_records` は全行に座標があるため
    `no_coordinate_count` は0（レポートにログ出力）。
7. **b08: 古い registry を検出**: `occurrence.taxon_id IS NOT NULL AND
   t.taxon_id IS NULL`（registry に taxon が無い＝registry が入れ替わった
   疑い）が1件でもあれば止める。
8. / 10. **b08: 1文の `INSERT ... SELECT`**: 出力ファイルを書き込み用に開いた
   接続に `cube`/`reg` を読み取り専用で ATTACH し、`INSERT INTO org_norm
   (<列名を明示>) SELECT ...` を1文で実行する形に書き換えた。以前の
   「`work` で SELECT → Python の `list[tuple]` → 別接続へ位置指定
   `executemany`」（最大約1GBを同時に保持しうる・列順が2箇所で一致している
   前提に依存）をやめた。
5. **`source_row_id` を INTEGER に**: `occurrence.source_row_id`
   （`organism_records.rowid`）を `TEXT`（`str(rowid)`）から `INTEGER` に
   変更（`ORDER BY` が辞書順になっていた——例えば `'10' < '2'`）。docstring に
   「rowid は原本のスナップショットに固有（`VACUUM` 等で変わりうる）。v1 も
   同じスナップショットを走査するので、O-2 の走査順の再現には同じ
   スナップショットの中でだけ使う。恒久的な識別子は `record_id`」と明記した。
12. **再利用**: `scripts/migrate/period.py` に `year_bounds`/`month_bounds`
    （`_year_bounds`/`_month_bounds` の公開名）を追加し、
    `occurrence_period.py` から再利用した（`period.py` の他の関数・挙動・
    `b03` の出力は無変更）。`scripts/b06_build_occurrence.py` の taxon_id は
    `scripts/registry/common.py` の `taxon_id_gbif`/`taxon_id_inat`
    （taxon レジストリのビルドが実際に ID を発行するのと同じ関数）から作る
    ように書き換えた（SQL の CASE 式でハードコードしていた ID の書式を
    やめ、taxon 解決を Python 側の `set` 参照に変更——副次的に約4〜5秒速く
    なった。後述）。`b08` の既定 `taxon_group` は `migrate.common.load_yaml`
    （`reconcile.common.load_yaml` の re-export）を使うように整理した
    （`scripts/registry/build_taxon.py` の読み込み関数は使わなかった——
    「使わなかったものと理由」参照）。
13. **単純化**: `_PROBLEM_SPECS` の使われない `sample_limit` 次元、
    `occurrence_period.py`/`source_regions.py` の `_load_raw` 薄いラッパ、
    `source_regions.py` の `_validate_section_shape` の未使用 `path` 引数を
    削除した。
15. **ドキュメント**: `ci.yml` のコメント・ステップ名を実態に合わせて更新、
    `occurrence_period.py` の docstring を `period.py` 再利用の実態に合わせて
    修正、`render_report` の「期待 1,958/221/10」という検証していない数字の
    直書きを削除（実測値だけを出す）。`rank_l` は `registry.taxon.rank` と
    `lower(記録の taxon_rank)` が全816,856行で一致することを実測で確認し、
    design v2 D3 どおり taxon の属性（`t.rank`）から取るように修正した
    （§10「設計からの逸脱」に取消線で記録）。

### 使わなかったものと理由（指摘12）

`scripts/registry/build_taxon.py` の `_load_taxon_group_rules()`
（`default_label_ja` と `rules` を両方返す）は使わなかった。`b08` が必要なのは
`default_label_ja` だけで、`_load_taxon_group_rules()` はレジストリのビルド
文脈に閉じた private 関数（`rules` 側の重複検知等、`b08` には不要な責務まで
背負っている）。`migrate.common.load_yaml`（`reconcile.common.load_yaml` の
re-export、既に `b08` が import 済み）で `default_label_ja` 1個だけを読む方が
単純で、依存も増えない（`build_taxon.py` の import 自体は `requirements.txt`
だけの venv で通ることを確認済み——`csv`/`sqlite3`/`yaml`/`taxon_namespaces`/
`registry.common` のみ、`requests` 等の重い依存は無い。使わなかったのは
「通らないから」ではなく「責務が合わないから」）。

### 値の不変性を確認した方法

1. 修正前（HEAD `54b459f`）の `scripts/b06_build_occurrence.py`・
   `scripts/migrate/occurrence_period.py`・`scripts/migrate/source_regions.py`
   等一式を `git archive 54b459f` で別ディレクトリに展開し、同じ実データ
   （`data/db/ryuiki.sqlite`/`registry.sqlite`）に対して実行 → `v2_old.sqlite`。
2. 修正後のコードを同じ実データに対して実行 → `data/db/v2.sqlite`。
3. 両方の `occurrence` テーブルを `record_id` 順に読み、`source_row_id` だけ
   `int()` に正準化してから全21列を `repr()` で連結し sha256 を取ったところ、
   **完全一致**（823,692行）。
4. 同様に `org_norm`（`scripts/b08_project_occurrence_v1.py` の出力）も
   `record_id` 順・全21列で sha256 を取り、**完全一致**（816,856行、`rank_l`
   の実装変更を含めて1ビットも変わらない——`registry.taxon.rank` と
   `lower(記録のtaxon_rank)` が全行一致するため）。
5. `scripts/b02_derived_compare.py --candidate data/db/v1_projection_occurrence.sqlite
   --tables org_norm` は修正後も exit 0・宣言済み差分のみ1・不一致0のまま。

### 実行時間（修正後。複数回実行し変動あり）

```
scripts/b06_build_occurrence.py    19.2〜26.0s（修正前23.2s。実行のたびに
  ±5秒程度ぶれるが、修正前と比べて明確に遅くなってはいない——taxon 解決を
  SQL の LEFT JOIN から Python の set 参照に変えたことが、正規表現を全部
  試す形（指摘9）による増加分を相殺している）
scripts/b08_project_occurrence_v1.py へ射影して書き出し  7.8〜11.1s（修正前
  15.1s+4.1s=19.2s。fetchall+位置指定executemanyの2段階から、ATTACHした
  1本のINSERT...SELECTに変えたことで明確に速くなった）
```

## 12. 独立レビュー（`/simplify`）を受けた修正と実測

§11（HEAD `57bf83b`）に `/simplify` をかけて12件の指摘（深さ2件・再利用3件・
単純化4件・効率2件＋どちらにも数えない1件）を受け、すべて反映した。**実測どおり、
`occurrence`・`org_norm`・`observation` の値は完全に不変**——修正前
（`57bf83b`）のコード一式を `git archive` で復元して同じ実データからビルドし、
正準化した sha256 で突き合わせて確認した（§11と同じ方法）。

### 反映した指摘（要約）

- **深さ1**: `scripts/b06_build_occurrence.py` の `_assert_known_source_ids` と
  `scripts/registry/build_taxon.py` の同名関数が同じ検査（重複除去・
  None-safe なソート・例外送出）を別々に持っていたのを、依存の無い
  `scripts/taxon_namespaces.py` の `assert_known_source_ids(source_ids,
  error_cls=ValueError)` に一本化した。`error_cls` で呼び出し側が投げたい
  例外の型を選べる（`build_taxon.py` は既定の `ValueError`、`b06` は
  `common.MigrationError`）——既存テストが見ている例外の型・メッセージは
  変えていない。
- **深さ2**: `_parse_utc_offset` を `scripts/migrate/occurrence_period.py` から
  `scripts/migrate/period.py`（`_strip_tz` の隣）に移設し、公開名
  `parse_utc_offset` で再利用する形にした（時刻帯の扱いを1か所に。ADR-0024）。
- **深さ3**: ADR-0025 D1 に「`source_regions.yaml` の `regions:`（地域の属性。
  将来 `observation` も読みうる）と `sources:`（occurrence の出典ごとの
  行数検証）は意味が違う」という1文を追記した。
- **再利用4**: `_declaration_problems`（b03・b06 で同一実装）を
  `scripts/migrate/period.py` の `EntryUsage` の隣に `declaration_problems()`
  として1つだけ置き、両方から呼ぶ形にした。
- **再利用5**: `_validate_expected_row_count`（`occurrence_period.py`・
  `source_regions.py` で同一）を `period.validate_expected_row_count()` に統合。
- **再利用6**: `period._validate_shape` を「パスを読む部分」（`_validate_shape`
  のまま）と「生の dict の必須キーを検査する部分」（新設
  `required_keys_problems()`）に分割し、後者と新設のフィルタ
  `entries_with_required_keys()` を `occurrence_period.py`/`source_regions.py`
  のセクションごとの検証（`sources:`/`regions:`/形の宣言）から使うようにした。
  `period_exceptions.yaml`・`time_label_conventions.yaml` の検証結果は
  変えていない（`validate_period_exceptions_shape`/
  `validate_time_label_conventions_shape` は無変更のまま `_validate_shape` を
  呼ぶ）。
- **単純化7**: `_ingest()` の使われない引数 `shapes` を削除。
- **単純化8**: `scripts/tests/occurrence_fixtures.py` の12形の名前を、
  `migrate.occurrence_period._SHAPE_NAMES`（正）から導出する形にし、リテラルの
  重複を無くした。
- **単純化9**: `occurrence_period_shapes.yaml` の `note` を「どの原表記か」の
  識別だけに削ぎ落とし、展開規則の文章は削除した（正はコード、説明は
  ADR-0025 D1 の表の1か所だけに集約）。
- **単純化10**: `EntryUsage` の別名（`PeriodShapeUsage`・`SourceRegionUsage`・
  `RegionUsage`）を廃止し、呼び出し側（`b06`）は `period.EntryUsage` を直接
  使うようにした。
- **効率11**: `ExpandedPeriod`（1行に1個、823,692回作られるホットパス）を
  `@dataclass(frozen=True)` から `typing.NamedTuple` に変更した（属性参照は
  変わらない。実測 約0.9秒短縮）。
- **効率12**: `b08` の古い registry 検出を、`occurrence.taxon_id` を1行ずつ
  JOIN する形から、distinct 値（実測 約33,613種）だけを `reg.taxon` と
  突き合わせる形に変えた。メッセージも「行が何件」ではなく「taxon_id が
  何種」に合わせた。
- **`classify_shape` の docstring 修正**: 「実測頻度の降順」という記述が、
  全形を毎回試す実装（正しさも速さも並び順に依存しない）と矛盾して見える
  との指摘を受け、「並びは読みやすさのためだけ」と明記した。

### 見送った指摘（オーナー判断。理由は前回の指示メッセージのまま）

- 形の判定を文字数で絞る高速化（実測 約2.3秒）: `/code-review` 指摘9で
  意図的に外した特例を戻すことになるため見送り。
- `source_id` の二重走査の畳み込み（実測 約0.47秒）: 「1行も処理する前に
  全件を診断する」という `_assert_known_source_ids`/宣言表検証の設計を
  優先し見送り。
- 例外クラスの使われない属性の整理: 既存の `PeriodMismatchError` 等と同じ
  流儀のまま。全体を揃えるなら別途。

### 値の不変性を確認した方法（§11と同じ手法）

`git archive 57bf83b` で修正前のコード一式を復元し、同じ実データ
（`data/db/ryuiki.sqlite`/`registry.sqlite`）に対して実行して `v2_old.sqlite`/
`v1_projection_occurrence_old.sqlite` を作り、現在のコードの出力と
`record_id` 順・正準化 sha256 で突き合わせた。

```
occurrence（823,692行、全22列。source_row_id は int() 正準化）: 完全一致
org_norm（816,856行、全21列）: 完全一致
```

`observation` は main（`22138f2`）のコード一式を同様に復元して突き合わせ、
**完全一致**（1,041,003行、全21列）を確認した。

### 受け入れ基準（実測）

```
b06 → b08 → b02 --tables org_norm: exit 0、宣言済み差分のみ1・不一致0
既存9表のゲート（b03→b04→b05）: 一致3・宣言済み差分のみ6・不一致0（変更なし）
r01 のフルビルド（worktree の registry.sqlite）: taxon 41,454・place 4,964 等、
  すべて修正前と同じ件数
web/src/lib/registry/generated.ts・generated-client.ts の再生成: git diff 0行
pytest: 308件成功（原本の無い一時 clone + requirements.txt だけの venv でも
  308件成功）
```

### 実行時間（`/simplify` 反映後）

```
scripts/b06_build_occurrence.py    19.2s
scripts/b08_project_occurrence_v1.py へ射影して書き出し  7.8s
```

## 13. O-1b（`occurrence_agg` ＋ 年キー8表 ＋ `species_month`）実装・実測（`phase-b/occurrence-cube`）

ADR-0025 D2・D3、`o1_design_v2.md` D2・D3 のとおり実装した。ここには実装したファイルと
実測値だけを記録する。

### 構成

| ファイル | 役割 |
|---|---|
| `scripts/b07_build_occurrence_cube.py`（新規） | `occurrence` から `data/db/v2.sqlite` の `occurrence_agg` を作る（`observation`/`observation_agg`/`occurrence` と同居） |
| `scripts/migrate/occurrence_cube_declarations.yaml`（新規） | leaf セル（`grain='survey_period'`。年をまたぐ区間）の元記録数（1,191）の宣言 |
| `scripts/b08_project_occurrence_v1.py`（拡張） | `org_group_year`/`effort_year`/`species2`/`species_year2`/`mesh_year`/`mesh_all`/`mesh_species`/`species_mesh_year`（`occurrence_agg` だけから）と `species_month`（`occurrence`＝L2 から）を追加。`org_norm` の実装・値は無変更（`build_org_norm_projection` は後方互換のまま残し、`main()` は10テーブルまとめて書く `build_all_projections` を使う） |
| `scripts/reconcile/expected_diffs.yaml`（`species2:` 節） | `org_norm` と同じ原因（*Sirosporium celtidis* の `cls`）の1キー宣言 |
| `scripts/tests/occurrence_fixtures.py`（拡張） | `occurrence_agg` を持つ v2.sqlite 相当を作る `make_v2_db_with_occurrence_and_agg` を追加 |
| `scripts/tests/test_b07_build_occurrence_cube.py`（新規） | grain 判定・機械検証 (i)〜(iii)・次元キー一意性のフィクスチャテスト |
| `scripts/tests/test_b08_occurrence_cube_projections.py`（新規） | 年キー8表・`species_month` のフィクスチャテスト（leaf セルの開始年への帰属、複数 `taxon_id` → 同じ `binom` の DISTINCT 集約、`species_month` の `mo` 非月値の再現等） |
| `.github/workflows/ci.yml`（拡張） | `occurrence_cube_declarations.yaml` の構造検証ステップを追加 |

### キューブの実測（`data/db/ryuiki.sqlite`/`registry.sqlite`、2026-09-22。ローカル実行）

```
occurrence_agg 総セル数        471,060
  year セル                   469,933
  leaf セル（survey_period）    1,127
  元記録: year                815,665
  元記録: leaf                 1,191（宣言値と一致）
  日付あり合計                816,856（= year 元記録 + leaf 元記録。(iii) 検証どおり）
  検証した系列数（source×taxon） 32,187
```

機械検証 (i)〜(iii) はすべて実データで通った:
- (i) 系列（source_id, taxon_id。taxon_id NULL を含む）ごとの Σn/Σn_red_list が
  `occurrence` の日付あり行と全件一致（32,187系列、不一致0）。
- (ii) leaf セルの元記録数 1,191 が宣言値と一致。
- (iii) year セルの元記録数 + leaf セルの元記録数 = 日付あり行数（815,665 + 1,191 = 816,856）。

### v1 射影の実測（`scripts/b08_project_occurrence_v1.py`）

```
org_norm            816,856行（O-1a と同じ。無変更）
org_group_year        1,166行
effort_year               57行
species2              23,618行
species_year2        116,899行
mesh_year             37,043行
mesh_all               4,083行
mesh_species            4,086行
species_mesh_year    276,163行
species_month           9,997行
```

すべて v1（`data/db/derived.sqlite`）の行数と一致（`reports/derived_baseline.json` 記録どおり）。

### 受け入れ基準1（`scripts/b02_derived_compare.py --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,mesh_year,mesh_all,mesh_species,species_mesh_year`）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite \
    --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,mesh_year,mesh_all,mesh_species,species_mesh_year
一致: 8 / 宣言済み差分のみ: 2 / 不一致: 0
適用した宣言済み差分: 2件
EXIT=0
```

`--no-expected-diffs` で実行すると、不一致は `org_norm.cls` 1行（O-1a と同じ）と
`species2.cls` 1行（同じ *Sirosporium celtidis*。属単位の多数決の同数タイブレークが
v1 と taxon レジストリで食い違う——原因は §3「F2: 分類の補完」と同一）の**計2件だけ**。
残り8表（`org_group_year`/`effort_year`/`species_year2`/`mesh_year`/`mesh_all`/
`mesh_species`/`species_mesh_year`/`species_month`）は数値列・文字列列とも全件一致。

### 既存11テーブル・O-1a のゲートが変わらないことの確認（受け入れ基準2）

```
b03→b04→b05 再実行後: b02 --tables meas_daily,...,zone_clim（11表）
  一致5 / 宣言済み差分のみ6 / 不一致0（EXIT=0。変更なし）
occurrence（823,692行）・org_norm（816,856行）: O-1a と同じ実装のまま
  （`_CREATE_ORG_NORM_SQL`/`_ORG_NORM_SELECT_EXPRS`/`_ORG_NORM_COLUMNS` を
  `git diff origin/phase-b/occurrence-l2` で確認——1バイトも変わっていない）
```

`b06_build_occurrence.py` は本 PR で一切変更していない。`scripts/migrate/` 配下は
`occurrence_cube_declarations.yaml`（新規。leaf セルの元記録数の宣言。b07 が読む）
を1つ足しただけで、既存ファイル（`occurrence_period.py`・`source_regions.py`・
`period.py` 等）は無編集（`git diff --stat origin/phase-b/occurrence-l2 --
scripts/b06_build_occurrence.py scripts/migrate/` は `occurrence_cube_declarations.yaml`
13行追加のみ。コードレビュー指摘14: この節の以前の記述「scripts/migrate/ 配下は
一切変更していない」は誤りだった——新規ファイルの追加を見落としていた）。

### 実行時間

```
scripts/b07_build_occurrence_cube.py      23.9s（occurrence_agg 471,060セルの構築）
scripts/b08_project_occurrence_v1.py      45.1s（10テーブル合計1,289,968行を射影して書き出し）
```

### pytest

```
scripts/tests 全体: 345件成功（O-1a までの326件 + O-1b で追加した19件
  〔test_b07_build_occurrence_cube.py 11件・test_b08_occurrence_cube_projections.py 8件〕）
原本の無い一時 clone（.gitignore 済み data/db 無し）+ requirements.txt だけの venv
（Python 3.13.7、CI の actions/setup-python と同じ版）でも345件成功
  （システムの既定 python3〔3.10系〕は sqlite3 モジュールが3.37.2で b04 の起動時
  ガードに引っかかるため、CI と同じ Python 3.13 を明示して確認した）
```

### 設計からの逸脱

- **`built_from` に SQLite バージョンを埋め込まない**（`scripts/b07_build_occurrence_cube.py`
  モジュール docstring 参照）。ADR-0021 決定3の SQLite バージョン検証（`AVG()`/`SUM()` の
  浮動小数点加算アルゴリズム）は `occurrence_agg` の値（`n`/`n_red_list`。ともに整数の
  `COUNT()`/`SUM(CASE ...)`）には適用対象が無い——SQLite の `SUM()` は整数列に対しては
  常に厳密な64bit整数和を返すため。ADR-0025 D2 が「共通」と明記する規律
  （`staged_table`・`COALESCE(c,'')` の `UNIQUE INDEX`・`built_from`/`spec_version`）には
  含まれていないため、b04 のような `sqlite3.sqlite_version_info` の起動時検証は実装して
  いない（意図的な判断。オーナー確認が要れば報告する）。

### 未決

なし（設計どおりに実装でき、実測がすべて期待値と一致した）。

### 既知の負債

- `docs/plans/PHASE_B_RECONCILIATION.md` の突合ゲートは、まだ全33テーブルを1回の
  `b02` 呼び出しに束ねていない（`--tables` を候補ファイルごとに個別に指定する運用の
  ままD4に明記済みの既知の負債。§4参照）。
- `mesh_all`/`mesh_species` の行数差（4,083 と 4,086）は v1 の仕様どおり（`mesh_all` は
  年 1970–2026 でフィルタ済みの `mesh_year` から積み上げるが、`mesh_species` には
  年フィルタが無いため、<1970 の記録しか持たない3メッシュ分だけ多い）。バグではないが、
  画面側でこの2表を並べて使うときに気づきにくい差なので、将来 API を生やす際は
  ドキュメント化しておくこと。

## 14. `/code-review` 15件の反映 ＋ `occurrence_agg` に `place_kind` 鍵を追加（`phase-b/occurrence-cube`）

### 反映した指摘（要約。番号はレビューでの指摘番号）

1. **b07 の (ii)(iii) を staging（実際に作ったキューブ）に対して行う**: 以前は
   `occurrence`（L2）に対して同じ年境界の述語を独立に再計算しているだけで、年セル/
   leaf セルの SQL 自体の WHERE 句が壊れていても検出できなかった。
   `_assert_cube_partition_and_shape` が `staging` を直接見るようにし、grain の語彙・
   `SUM(n) GROUP BY grain`・year セルの暦年境界丸め・leaf セルの年またぎを、すべて
   staging の実際の中身に対して検証する。
2. **b08 がキューブを「今の occurrence の分割」であることを確かめてから使う**:
   `_assert_cube_is_current_l2_partition` を新設。grain の語彙・系列
   （source_id, taxon_id）ごとの Σn を occurrence（L2）と突き合わせ、食い違えば
   「b06 の後に b07 を再実行せよ」と案内して止める。これにより `_build_org_norm` が
   `occurrence` 全体の taxon 新鮮さを検証済みなら、`occurrence_agg` に対する同じ検査の
   重ねがけ（`build_all_projections` 経由の呼び出しでは）を省ける
   （`check_stale_taxon=False`）。
4. **`mesh_species` を v1 どおり WHERE なしに戻し、`mesh_year` は `place_id IS NOT NULL`
   に**（以前は両方に `mlat IS NOT NULL` を書いていて、`mesh_species` が v1 と違う
   フィルタを持っていた）。`place_id` はあるのに mesh が引けないセルは黙って
   `mlat=NULL` にせず止める（`_assert_all_places_resolve_to_mesh`）。
5. **年境界の計算から SQLite の `date()` を外す**（文字列演算のみに）。`_assert_t1_invariant`
   を新設し、b07 自身も `occurrence.period_start`/`period_end` の T1（時刻帯なし・
   10桁/19桁）を確認してから使う。
6. **b08 が前提（`occurrence`/`occurrence_agg`/`taxon` テーブル）を出力ファイルを
   消す前に確かめる**（`_assert_prerequisites`）。以前は `fresh_sqlite` が前回の出力を
   消した後で生の `OperationalError` になり、空の `org_norm` だけが残っていた。
7. **古い registry 検出のメッセージを文脈ごとに**（`occurrence` なら b06 の再実行、
   `occurrence_agg` なら b06→b07 の再実行を案内）。
8. **9表の宣言型・列順を v1（`data/db/derived.sqlite`）の実物に合わせる**（`PRAGMA
   table_info` で確認）。値は変わらない（宣言型が無い列は SQLite の無親和性になり
   値の変換が起きないため）。`org_norm` は O-1a のまま触っていない。
9. **(ii) のメッセージが実際に渡された `--declarations-yaml` のパスを出す**（既定値
   ではなく関数引数の `declarations_yaml` を使う）。
10. **`species2_l2_extras` と `species_month_l2` を `l2_taxon_enriched`（L2 の1回の
    走査）に統合**。`species_month` はこの温存テーブルから `INSERT ... SELECT ...
    WHERE` で直接絞り込む——別の816,856行の温存テーブルを追加で作らない。
12. **同じ年か否かの述語を `_SAME_YEAR_EXPR`/`_CROSS_YEAR_EXPR` の1箇所に集約**し、
    INSERT 側・検証側の両方がそこから作る。**宣言 YAML を1回だけ読む**
    （`load_and_validate_cube_declarations` が構造検証と値取得を同時に行う）。
13. **テストに実際の b07 パイプラインを通す**: `test_b08_occurrence_cube_projections.py`
    に `_build_cube_via_b07`（occurrence フィクスチャ→本物の `b07.build_cube()`→
    occurrence_agg）を導入し、手で辻褄を合わせた `occurrence_agg` だけに頼らない
    テストへ作り替えた。taxon_id NULL のセル・`grain='month'` の混入・L2/キューブの
    Σn 食い違い・place 未解決のテストを追加。b07 には変異テスト（下記）を追加。
14. **本ドキュメント §13 の「`scripts/migrate/` 配下は一切変更していない」の訂正**
    （実際には `occurrence_cube_declarations.yaml` を1つ足していた）。
15. **O-1a の射影規則の説明を `_ORG_NORM_SELECT_EXPRS` の直前に復元**（O-1b の
    リファクタで docstring から抜け落ちていた——`yr`/`mo` を `period_raw` から取る
    理由・`mo` の非月値の癖・`rank_l` を taxon の属性から取る経緯を、コードから
    読めるように戻した）。

### 変異テストによる検証（指摘1の穴の再現と修正確認）

年セル/leaf セルの分類条件を入れ替える変異（同年の記録が `survey_period` に、年を
またぐ記録が `year` に入る——記録の総数・系列ごとの Σn は変わらないため、旧実装の
(i)(ii)(iii) はどれもこの変異をすり抜ける）を、**修正前のコード（コミット
`7026dd7`）に対して実際に適用**し、`build_cube()` が例外を投げずに完了すること
（=穴があったこと）を実測で確認した:

```
旧実装: 変異を入れても build_cube は例外を投げずに完了した（穴があった証拠）
occurrence_agg の中身（同年の記録が survey_period に、年をまたぐ記録が year に
間違って入っている）:
  ('survey_period', '2020-01-05', '2020-01-05', 1)
  ('year', '1990-01-01', '1990-12-31', 1)   # 1990-01-01/1992-12-31 の区間が
                                              # 1990年だけに切り詰められている
```

同じ変異を**現在のコード**に対して適用すると:

```
occurrence_agg: grain='survey_period'（年をまたぐ区間のはず）なのに period_start/
period_end が同じ年に収まっている行が1件ある。
```

で正しく止まることを確認した（`scripts/tests/test_b07_build_occurrence_cube.py`
の `test_mutation_year_and_leaf_classification_swapped_is_caught` として恒久化）。

### `occurrence_agg` に `place_kind` 鍵を追加（O-2 の先取り。追加指示）

鍵に `place_kind` を追加した（`region_id, source_id, place_id, place_kind, taxon_id,
grain, period_start, period_end`）。理由は ADR-0025 D2 参照
（`docs/adr/0025-occurrence-fact-and-cube.md`。ADR-0011・`observation_agg` との
関係・O-2 との関係をそこに一本化した）。

- 触ったファイル: `scripts/b07_build_occurrence_cube.py`（`DIM_COLUMNS`・
  `_assert_series_totals_match_l2`・`_assert_cube_partition_and_shape` を
  `place_kind` ごとに）、`scripts/b08_project_occurrence_v1.py`
  （`_MESH_PLACE_KIND`/`_KNOWN_PLACE_KINDS`/`_assert_known_place_kinds`
  を新設し、`occ_agg_enriched`・`_assert_cube_is_current_l2_partition` を
  `place_kind='grid01'` に絞る）、`docs/adr/0025-occurrence-fact-and-cube.md`
  （D2 の鍵の記述を更新）。
- 実測: `occurrence.place_kind` は現状すべて `'grid01'`（823,692行中823,692行。
  b06 が grid01 経由でしか場所を解決しないため）。
- **値は1ビットも変わらない**（`place_kind` は列が1つ増えるだけで、既存の全列の値は
  変わらない——下記「値の不変性」参照）。

### 値の不変性を確認した方法

`scripts/reconcile/common.compute_fingerprint`（b01/b02 と同じ正準化関数）で、
修正前（コミット `7026dd7`。`/code-review`・`place_kind` 追加のどちらも未反映）の
出力と、今回の修正後の出力を、`occurrence`・`occurrence_agg`（`place_kind` 列は
除く）・10表それぞれについて `(row_count, content_hash)` で突き合わせた。

```
occurrence           row_count=823,692   content_hash 完全一致
occurrence_agg       row_count=471,060   content_hash 完全一致（place_kind 列を除く全列）
org_norm             row_count=816,856   content_hash 完全一致
org_group_year       row_count=1,166     content_hash 完全一致
effort_year          row_count=57        content_hash 完全一致
species2             row_count=23,618    content_hash 完全一致
species_year2        row_count=116,899   content_hash 完全一致
species_month        row_count=9,997     content_hash 完全一致
mesh_year             row_count=37,043    content_hash 完全一致
mesh_all              row_count=4,083     content_hash 完全一致
mesh_species          row_count=4,086     content_hash 完全一致
species_mesh_year     row_count=276,163   content_hash 完全一致
```

12テーブルすべて `content_hash` が1バイトも変わっていない。

### 受け入れ基準（実測）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite \
    --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,mesh_year,mesh_all,mesh_species,species_mesh_year
一致: 8 / 宣言済み差分のみ: 2 / 不一致: 0
EXIT=0

$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection.sqlite \
    --tables meas_daily,meas_month,meas_year,meas_clim,site_var,var_catalog,sensor_daily,rain_daily,sensor_hour_month,zone_year,zone_clim
一致: 5 / 宣言済み差分のみ: 6 / 不一致: 0（既存11テーブルのゲート。変更なし）
EXIT=0
```

### 実行時間

```
scripts/b07_build_occurrence_cube.py    15.8s（occurrence_agg 471,060セルの構築）
scripts/b08_project_occurrence_v1.py    30.5s（10テーブル合計1,289,968行を射影して書き出し）
```

### pytest

```
scripts/tests 全体: 358件成功（O-1b 初回実装時の345件 + 本ラウンドで追加した13件）
原本の無い一時 clone + requirements.txt だけの venv（Python 3.13.7）でも358件成功
```

## 15. O-2a（点→流域の解決 `occurrence_place` ＋ v1 互換射影2表）実装・実測（`phase-b/occurrence-watershed`）

設計の決定は [ADR-0026](../adr/0026-occurrence-place-watershed.md)（D1〜D3。
ADR-0006 規約2の改定を含む）に切り出した。ここには実装したファイルと実測値
だけを記録する。O-2 の対象は F3（流域への点内包判定）——§3「F3: 流域」・
§4「縦線の切り方」で「O-2 の対象。この PR では着手しない」としていた部分。

### 構成

| ファイル | 役割 |
|---|---|
| `scripts/migrate/point_in_polygon.py`（新規） | `web/scripts/build-geo.mjs:112-165` の純 Python 移植（0.02度 bbox グリッド → even-odd → 穴、MultiPolygon）。shapely は使わない |
| `scripts/b09_build_occurrence_place.py`（新規） | `occurrence`（L2）の座標を W12 流域ポリゴンへ直接解決し、`data/db/v2.sqlite` に `occurrence_place` を作る。実行順は b06 → **b09** → b07 → b08 |
| `scripts/migrate/occurrence_place_declarations.yaml`（新規） | ポリゴン数・NULL件数・解決件数の宣言 |
| `scripts/migrate/occurrence_watershed_v1_declarations.yaml`（新規） | v1 のメモ化と正確な結果の食い違い（記録単位）の宣言 |
| `scripts/b08_project_occurrence_v1.py`（拡張） | `org_watershed_year`/`org_watershed` を追加（`occurrence`+`occurrence_place` から。`occurrence_agg` は使わない）。出力は既存の `data/db/v1_projection_occurrence.sqlite` に2表追加（12テーブル） |
| `scripts/registry/build_caveat.py`（拡張） | `ORGANISM_TABLES` に `occurrence_place` を追加（`organismSite` 注記のスコープ。`org_watershed`/`org_watershed_year` は元から含まれていた） |
| `scripts/tests/occurrence_fixtures.py`（拡張） | `occurrence_place`/watershed 宣言YAML/GeoJSON/`sites`のフィクスチャヘルパを追加 |
| `scripts/tests/test_migrate_point_in_polygon.py`・`test_b09_build_occurrence_place.py`・`test_b08_watershed_projections.py`（新規） | PIP の単体テスト・b09 の統合テスト（宣言不一致・2面一致・sites突合の失敗系を含む）・b08 の統合テスト（代表選定の母集団・バケット結合・保存則） |

### 実測（`data/db/ryuiki.sqlite`/`registry.sqlite`/
`data/processed/nlni_w12_watersheds.geojson`、2026-09-23。ローカル実行）

```
occurrence_place
  母集団（座標あり occurrence）  823,692
  解決                          737,407
  NULL                           86,285
  2つ以上に一致                       0
  際どい交差（要 Fraction 再判定）      0（最短の余裕 約4.4e-9度）
  site→watershed 辺との突き合わせ  352地点、食い違い0
  distinct 座標                 224,282
  b09 実行時間                  約21〜22秒

org_watershed_year          10,699行（v1 と一致）
org_watershed                   287行（v1 と一致）
memo_moved_records            11,306（ws_to_ws 9,428 / v1_assigned_exact_unassigned 622 /
                                       v1_unassigned_exact_assigned 1,256）
memo_mixed_buckets                741
org_watershed_year_keys_changed_vs_exact  1,091
保存則: 732,707 + 1,256 − 622 = 733,341（occurrence_placeの実測と一致）
```

`org_watershed_year`/`org_watershed` は**宣言済み差分なしで完全一致**
（`org_norm`/`species2` の `cls` 1件のような既知の食い違いが無い——F2 の
分類補完タイブレークは流域の集計には影響しないため）。

### 受け入れ基準1（`scripts/b02_derived_compare.py --tables ...,org_watershed,org_watershed_year`）

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite \
    --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,mesh_year,mesh_all,mesh_species,species_mesh_year,org_watershed,org_watershed_year
一致: 10 / 宣言済み差分のみ: 2 / 不一致: 0
EXIT=0
```

「一致10」は既存8表（O-1a/O-1b で宣言なし完全一致だった6表 + `org_norm` は
宣言あり側）＋ `org_watershed`/`org_watershed_year`（本PRで新たに完全一致）。
「宣言済み差分のみ2」は `org_norm.cls`/`species2.cls`（F2、既存のまま。本PR
では増やしていない）。

### 既存テーブル・O-1a/O-1b のゲートが変わらないことの確認（受け入れ基準2）

```
occurrence（823,692行）・occurrence_agg（471,060行）: 行数不変（b09 は
  occurrence_place だけを作り、occurrence/occurrence_agg には一切触れない）
b03→b04→b05（既存11表）: 一致5 / 宣言済み差分のみ6 / 不一致0（変更なし）
```

### b09 の機械検証1〜5・b08 の6〜8（受け入れ基準3）

すべて実データで通った（上記「実測」節の数値がそのまま検証結果）。
**5（浮動小数点の曖昧さ）は実際に厳密判定に落ちる点が0件**だった——
even-odd の交差判定で `|x-x_cross|<1e-9` になった distinct 座標が実データに
存在しなかった（最短の余裕は約4.4e-9度で、閾値1e-9の4倍以上離れている）。
`fractions.Fraction` による厳密再判定のコードパス自体は
`scripts/tests/test_migrate_point_in_polygon.py::
test_near_threshold_crossing_is_flagged_and_exact_recheck_agrees` が
フィクスチャで踏んで確認している。

### b09 の実行時間（受け入れ基準5）

```
scripts/b09_build_occurrence_place.py   約21〜22秒
  （うち PIP 本体: distinct 座標224,282件に対し約9〜11秒。目安どおり）
```

### pytest（受け入れ基準4）

```
scripts/tests 全体: 432件成功（O-1b までの412件 + 本PRで追加した20件
  〔test_migrate_point_in_polygon.py 8件・test_b09_build_occurrence_place.py 7件・
  test_b08_watershed_projections.py 5件〕）
古い SQLite（システム既定 python3、sqlite3モジュール3.37.2）の venv でも
  336件成功・96件スキップ（合計432。3.43未満をスキップする既存テストに
  b08 の watershed テストが追加でスキップ対象に入っただけで、失敗は0件）
原本の無い一時 clone + requirements.txt だけの venv（Python 3.13、CIと同じ）
  でも全件成功（詳細は本PRの実装報告参照）
```

### 設計からの逸脱

なし（ADR-0026 の決定どおりに実装でき、実測がすべて期待値と一致した）。

### 未決

なし。

### 既知の負債

- **O-2b（キューブに `place_kind='watershed'` のセルを足す）は本PRでは
  着手していない**（ADR-0025 D2 が先取りで `occurrence_agg.place_kind` を
  鍵に持たせてあるので、O-2b はスキーマ変更なしで着手できる）。
- `place_kind='grid01'` の解決は `occurrence` 本体の列（ADR-0025 D1）、
  `place_kind='watershed'` の解決は `occurrence_place` サテライト表、という
  置き場の非対称性が残る（ADR-0026「影響」節に明記）。将来 site/municipality
  等が増えたときにこの非対称性をどう扱うかは未検討。
- `occurrence_watershed_v1_declarations.yaml` に書いた実測値（`memo_moved_records`
  等）は `organism_records` の rowid（原本のスナップショット）に固有——原本を
  `VACUUM` 等で書き換えたら実測し直して更新する必要がある（宣言YAMLのnoteに
  明記済み）。
