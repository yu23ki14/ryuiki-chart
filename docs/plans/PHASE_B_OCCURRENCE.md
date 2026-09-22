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

### 6-4. 「出典→名前空間」の正を `scripts/common.py` に移す

`SOURCE_NAMESPACE` は `build_taxon.py` の private 定数だったため、レジストリを
経由しない読み手（`scripts/x01_dwca.py` の DwC-A 書き出し。`occurrence.txt` の
`taxonID` 列に `organism_records.taxon_key` を出典の区別なく生のまま書いている）
に届いていなかった（code-review指摘5）。正を `scripts/common.py` の
`TAXON_KEY_SOURCE_NAMESPACE` に移し、`build_taxon.py` の SQL の CASE 式も
そこから組み立てるようにした（ハードコードの重複を解消）。
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

## 7. 再現の壁・申し送り

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
