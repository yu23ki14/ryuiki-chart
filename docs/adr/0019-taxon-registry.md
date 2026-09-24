# ADR-0019: 分類群レジストリと、分類カテゴリの表記ゆれの扱い

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0004（ID）, ADR-0010（語彙）, ADR-0018（公開範囲）

**2026-09-22 追記（生物の出現の縦線 Slice 0、`phase-b/occurrence-registry`）**:
Phase A の実装（`scripts/registry/build_taxon.py`）は `organism_records.taxon_key`
を出典に関わらず `common:taxon:gbif.<key>` に通していたが、iNaturalist 行の
`taxon_key` には iNaturalist 自身の `taxon.id`（GBIF の taxonKey とは無関係な
別の数値空間）が入っていた（`scripts/m03_organisms.py`）。GBIF と iNat が偶然
同じ数値を発行した**9件が衝突**し（例: `8026` は GBIF では科 *Axiidae*、iNat では
*Corvus macrorhynchos*）、件数の多い側の学名が少ない側の実体を上書きしていた。

`organism_records.source_id` で出典を判定し、GBIF 由来は
`common:taxon:gbif.<GBIFのtaxonKey>`、iNaturalist 由来は
`common:taxon:inat.<iNatのtaxon.id>` に分けた（**決定1の「`taxon_id` は `common:`
スコープ」自体は変わらない**。`gbif.`/`inat.` は `local_key` 側の名前空間で、
ADR-0004 規約1「`local_key` は出典の識別子をそのまま使ってよいが、必ず名前空間を
前置する」の具体化）。`gbif_taxon_key` 列は本物の GBIF taxonKey のときだけ埋める。

これは **ADR-0004「ID は不変」の例外**として記録する: occurrence ファクト（まだ
未着手）が `taxon_id` を参照するようになる前の、ID を組み替えても参照が壊れない
唯一の時点で行った。web・scripts 側を全件 grep し、レジストリのビルダー・検証
自身（本ファイル・`r01_build_registry.py`・関連テスト）以外に `taxon_id`/
`gbif_taxon_key` の呼び出し元が無いことを確認済み。

あわせて、v1（`web/scripts/build-biota.mjs` の `org_norm`）が記録ごとに行っていた
分類補完（`kingdom`/`phylum`/`class` の `COALESCE(own, 二名法キーの多数決,
属の多数決)`、および `taxon_group` の CASE 式）を、taxon（namespace, taxon_key）
単位でレジストリのビルダー側に移した（`taxon.kingdom`/`phylum`/`class`/`order`/
`family`/`classification_basis`/`canonical_binomial`/`taxon_group` 列を追加。
`order`/`family` は多数決で補完しない。`taxon_group` は
`registry/taxon/taxon_group.yaml` から生成）。v1 の暗黙の同数処理
（`ROW_NUMBER` の実装依存順）を明示規則（件数降順、同数なら値の昇順）に置き換えた。
`classification_basis` の解決不能値は `'unresolved'` ではなく `'no_match'` と
名付けた（`taxon.status='unresolved'`——GBIF backbone未照合——と文字列が同じで
紛らわしいため）。

**分類が不確かな taxon の可視化（`status='needs_review'`）は、独立レビュー
（/code-review）で2点補強した**: (1) 属単位の多数決が同数の場合だけでなく、
**属自体が複数の class にまたがる場合**（同数でなくても多数決の信頼性が低い）も
対象にした。(2) `status='unresolved'`（GBIF backbone未照合）の行でも、分類の
多数決が不確かなら `needs_review` に置き換えるようにした（初版は「`unresolved`
は上書きしない」としていたが、これだと *Martensia flabelliformis* のように
taxon_group 自体が丸ごと変わりうる不確かさが `taxa` 由来の unresolved 行では
一切可視化されなかった。`unresolved` と `needs_review` は別軸の事実だが `status`
は単一値なので、より新しい・具体的な判定を優先する）。実測件数・実例は
`docs/plans/PHASE_B_OCCURRENCE.md` 参照。決定そのもの（backbone は GBIF を正とする、
未解決は `unresolved` で保持する等）は変更していない。

**2回目の独立レビューで、上記の実装の同数処理・名前空間の扱いに4件の
頑健性修正を追加した**（`docs/plans/PHASE_B_OCCURRENCE.md` §7）: 名前空間を
2値に決め打ちしていた3箇所を対応表から導く形に一般化、kingdom の
needs_review 判定が (class,kingdom) の組の同数を誤って流用していたのを
列ごとの食い違いで判定する形に修正（多数決の値の選び方自体は変えていない）、
taxon_key ごとの代表選びの同数で分類には無関係な表記ゆれでもビルド全体が
止まっていた assert を撤去、指紋の古さメッセージに `organism_records` を追記。
**4件とも実データでの出力（taxon_id・分類の値・`status`）を1行も変えないことを
全41,454行の diff で確認済み**——将来のデータ・辺縁ケースに備えた防御的な修正。

**PR #15 の CI が `ModuleNotFoundError: No module named 'requests'` で落ちたため、
`TAXON_KEY_SOURCE_NAMESPACE` の置き場を `scripts/common.py`（`requests` に依存する
収集系の共有モジュール）から、依存の無い `scripts/taxon_namespaces.py` に移した**
（`docs/plans/PHASE_B_OCCURRENCE.md` §8）。「レジストリのパッケージの外の1箇所」
という意図・値は変えていない。

**2026-09-23 追記（P-2、レッドリストと外来種の評価 `taxon_assessment`、
`phase-b/taxon-assessment`）**: 決定5「最新の評価はビューで表す」で構想していた
`taxon_assessment` を、v1 の `redlist_map`/`redlist_change`（神奈川県レッドリスト
2020・レッドデータブック2022・レッドリスト2026の3版、2,884行）と `ias_species`
（環境省 生態系被害防止外来種リスト、429行）の最小形として実装した。

```
taxon_assessment  assessment_id（PK）, list_id, list_year, taxon_id（NULL可）,
                  scientific_name_raw, vernacular_name_ja_raw, taxon_group_ja,
                  taxon_subgroup_ja, family_ja, category_raw, category_code,
                  prev_category_raw, prev_category_code, national_category_raw,
                  origin, source_id
```

`registry.sqlite` にのみ持ち、**D1（`web/src/db/schema-registry.ts`）には載せない**
——`taxon` の分類補完列（kingdom/phylum/…）を D1 に足さなかったのと同じ判断
（使う側〔web〕がまだ無い。`registry/README.md`「`place.region_id` と
`place_relation`」参照）。

- **カテゴリーのコードリストは `registry/taxon/redlist_category.yaml` +
  `redlist_category_alias.csv` に分けた**（`variable`/`variable_alias` と同じ
  「正準＋出典表記」の二層）。**RA（希少種、2006年版）・AT（注目種/要注意種）は、
  決定2の IUCN 準拠コードリスト（CR/EN/VU/NT/DD/LC/EX/EW/LP/NA）には無い、
  神奈川県独自の区分**として `scope: jp-14` で登録した（ADR-0002「地域固有語彙は
  コードリストの拡張として表現する」の具体化。共通語の意味を地域が上書きしない、
  という同 ADR の禁則にも抵触しない——RA/AT はそもそも共通コードリストに存在
  しないコードの追加であって上書きではない）。
- **`prev_category_raw`（前回区分）は版間の JOIN で導かない。その版の文書自身が
  書いている値をそのまま持つ**——決定5「最新の評価はビューで表す」は「評価が
  版で変わったこと自体が分析対象」という前提で書いたが、実装時に判明した
  制約により、版どうしを機械的に JOIN して「前回」を導出することはできない
  （例外として記録する）: (1) 2022年版（レッドデータブック植物編）は原資料に
  学名が無く（1,033行中1,033行で `scientific_name` NULL）、学名でも和名でも
  版をまたいだ同定ができない。(2) 2020年版が書く「前回」は2006年版（RA/AT の
  出どころ）を指すが、2006年版のレコード自体は本基盤に無い。両方とも、
  「前回の区分が何だったか」という情報は**その版の文書自身が `category_prev_ja`
  として書いている**ので、これを `prev_category_raw` にそのまま転記すれば
  情報は失われない——JOIN で導けないことは「前回が無い」ことを意味しない。
  `'―'`（辞書に無い原表記）は黙って NULL に落とさず、
  `prev_category_code='not_listed'` として明示的に持つ（v1 は LEFT JOIN の
  不一致で暗黙に「前回記載なし」を導いていた。実測件数・詳細は
  `docs/plans/PHASE_B_TAXON_ASSESSMENT.md`）。
- **除外の宣言ファイル**: v1 の `ias_species`（外来種）は二名法（binom）の
  誤ヒットを避けるため7種をハードコードで除外していた（国内の別地域個体群が
  同じ学名で神奈川県内の在来個体群にも誤ヒットする等）。この除外を
  `registry/taxon/assessment_scope_exclusions.yaml`（`list_id`,
  `scientific_name`, `reasons`）に宣言化し、v1 を完全に再現した
  （オーナー決定A。「宣言済み差分 > データを曲げる」——除外という判断を
  データから消さず、理由つきで残す）。`origin_ja`（moe_ias_list.csv。
  `taxa.ias_category` は落としている値）を基準にした場合との差（v1に
  誤って残っている行）は宣言を増やさず、ビルド時レポート
  （`reports/phase_b_taxon_assessment.md`）に実測を出すだけに留めた
  （直すのは別の意図的な変更として申し送り。ADR-0016「再現してから変える」
  の順序）。
- **`taxon_id` は解決できる分だけ埋める**（学名の完全一致 → 二名法一致の順、
  曖昧なら NULL）。決定4「照合できないことをデータとして残す」の延長だが、
  `taxon_assessment.taxon_id` は`occurrence`のような`status`列を持たず、単に
  NULL のまま残す——v1 の射影（`redlist_change`/`ias_species`）はどちらも
  名前を文字列で運ぶため、Phase B の再現には不要な診断用の列である。
- **`category_code`/`prev_category_code` が未知の原表記に遭遇したらビルド
  全体を止める。これは決定2「正規化できないものは `category_code=NULL`・
  `status='needs_review'` として可視化し、推測で埋めない」からの意図的な
  逸脱である**（/code-review 指摘11）。決定2は `taxon`（分類群そのもの）の
  分類補完について書かれたもので、`taxon.status` という「可視化のための
  状態列」を前提にしている。`taxon_assessment` にはその種の状態列が無く、
  かつ対象は44+1種という有限で把握済みの語彙（`redlist_category.yaml` +
  `redlist_category_alias.csv`）である。この語彙に対して未知の値が来ることは
  「原本 or 語彙のどちらかが実際に壊れている」ことを意味するとみなし、
  `taxon`/`place` の不変条件と同じ「黙って進めない」方針を、`needs_review`
  による可視化より優先した。

実測・実装ファイルの詳細は `docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照。

**2026-09-24 追記（`phase-b/taxon-assessment` /code-review 15件対応）**:
上記追記時点の実装に4点の設計変更を行った（値・受け入れ基準は1ビットも
変えていない——実測は `docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照）。

1. **和名の畳み込み（v1 の `taxa` が3出典をまたいで行う「同じ学名の最初の
   非空和名が勝つ」畳み込み）を、射影（`scripts/b08_project_occurrence_v1.py`）
   ではなくレジストリのビルド（`scripts/registry/build_taxon_assessment.py`）
   側に移した。** 射影は「`registry.sqlite` だけを読み、原本
   （`ryuiki.sqlite`）には一切触れない」という Phase B 全体の層分けを守る
   ため（以前は b08 が `ryuiki.sqlite` を直接 ATTACH しており、`b10` の
   前例に倣ったつもりが実際には射影の層に原本を持ち込む設計逸脱だった）。
   `taxon_assessment` に `vernacular_name_ja_resolved` 列を新設し、
   moe_ias_2015 の行だけこの畳み込み結果を持つ（redlist 側は常に NULL）。
2. **二名法（binom）は `taxa.scientific_name`（v1 が実際に使う綴り）と
   `moe_ias_list.csv` 自身の `scientific_name_raw` が一致することを機械
   検証する**ようにした（実測: 429行すべて一致。食い違えば止める）——
   これにより射影側は `scientific_name_raw` から作った binom をそのまま
   使ってよいことが保証される。
3. **外来種の `assessment_id` を、CSV の行順（`moe_ias_2015_00001`...）
   から、内容（学名の正規化＋区分＋和名の組）から決まる ID に変えた**
   （ADR-0004 規約2「ID は不変」に合わせる。行順ベースの ID は CSV に
   行の追加・削除があると既存行の連番がずれ、同じ ID が別の種を指す
   欠陥があった）。
4. **`assessment_list.yaml` の `codelist`/`region`、`redlist_category.yaml`
   の `scope` を、実際にビルドが読んで分岐・検証する形にした**（以前は
   宣言されているだけで参照されていなかった）。`codelist` はカテゴリーの
   コード化経路を決定するデータ駆動の分岐に、`region`/`scope` は既知の
   地域ID（ADR-0002）に対する検証に使う。

## 背景（実測）

生物データはこの基盤で最大のファクト（`occurrence` 823,692行）であり、
`taxa` 8,585行・`redlist_assessments` 2,884行の語彙がある。ここに次の問題がある。

**1. レッドリストのカテゴリ表記が揺れている**（`organism_records.red_list_category`）

```
絶滅危惧ⅠB類（EN） / 絶滅危惧IB類（EN） / 絶滅危惧IB 類（EN）
絶滅危惧ⅠＡ類（CR） / 絶滅危惧IA類（CR） / 絶滅危惧IA 類（CR）
絶滅危惧Ⅱ類（VU）  / 絶滅危惧II類（VU）
絶滅危惧I類（CR+EN） / 絶滅のおそれのある地域個体群（LP） / 注目種 / 情報不足（DD）
```
ローマ数字（Ⅰ）とラテン文字（I）、全角（Ⅰ Ａ）と半角、スペースの有無が混在する。
一方 `redlist_assessments.category_code` は `CR` / `EN` / `VU` / `NT` / `DD` / `EX` /
`CR+EN` / `EW` に正規化されているが、**1,151行（40%）が NULL**。

**この表記ゆれは ADR-0018 の公開ゲートの入力になっている。** 表記が1つ増えるだけで
希少種の位置が公開されうる。

**2. 名前の同定に backbone が必要**
`taxa` は GBIF taxonKey を持つが、`organism_records` の突合は学名文字列で行っている。
シノニム・和名・地域個体群（例: リュウキュウアユ `Plecoglossus altivelis ryukyuensis`）の
扱いが決まっていない。多地域（ADR-0002）では奄美の固有種・亜種が増える。

**3. 版が複数ある**
`redlist_assessments` は県RL 2020 / 県RDB 2022 / 県RL 2026昆虫 を版で併存させている
（これは良い設計）。「最新の評価」と「ある時点の評価」を区別できる必要がある。

## 決定

**`taxon` を名前ではなく ID で扱うレジストリにし、分類カテゴリをコードリストに正規化する。**

```
taxon             taxon_id (common: スコープ), scientific_name, canonical_name,
                  rank, parent_taxon_id, gbif_taxon_key, gbif_match_type,
                  vernacular_name_ja, status ('accepted'|'synonym'|'unresolved'),
                  accepted_taxon_id
taxon_name        taxon_id, name, name_type ('scientific'|'vernacular_ja'|'synonym'),
                  source_edition_id            -- 名寄せの入口
taxon_assessment  taxon_id, list_id, list_year, category_code, category_raw,
                  source_edition_id            -- 版ごとの評価（現行 redlist_assessments）
```

1. **`taxon_id` は `common:` スコープ**（ADR-0004 規約0）。分類群は地域の属性ではない。
   地域固有の評価は `taxon_assessment` に地域を持たせる。
2. **カテゴリは IUCN 準拠のコード（`CR`/`EN`/`VU`/`NT`/`DD`/`LC`/`EX`/`EW`/`LP`/`NA`）に
   正規化し、原表記を `category_raw` に残す。** 正規化できないものは
   `category_code=NULL, status='needs_review'` として**可視化する**（推測で埋めない）。
   `CR+EN`（区分されていない絶滅危惧I類）は独立のコードとして残す。
3. **ファクトはカテゴリ文字列を持たない。** `occurrence` は `taxon_id` だけを持ち、
   レッドリスト該当かどうかは `taxon_assessment` を引いて判定する。
   これで ADR-0018 の公開ゲートが文字列に依存しなくなる。
4. **backbone は GBIF を正とする。** ただし GBIF に無い／一致しないもの
   （地域個体群・和名のみの記録・`gbif_match_type` が弱いもの）を捨てず、
   `status='unresolved'` で保持する。**照合できないことをデータとして残す。**
5. **「最新の評価」はビューで表す。** `taxon_assessment` は版を消さない。
   評価が版で変わったこと自体が分析対象である（現行 `redlist_change` の役割）。

## 影響

- **良い**: 公開ゲート（ADR-0018）が文字列依存でなくなる。版間比較が素直に書ける。
  多地域で分類群語彙を共有できる。名寄せできなかったものが可視になる。
- **コスト**: 823,692行の `occurrence` を `taxon_id` に紐づけ直す照合作業。
  `category_code` が NULL の1,151行の原表記からの正規化（人手確認を含む）。
- **リスク**: GBIF backbone は更新されるため、`taxon_id` の安定性が GBIF に依存する。
  GBIF 側の変更で分類が変わった場合の扱い（`superseded_by`）を運用に含める。

## 検討した代替案

- **学名文字列を主キーにする（現行に近い）**: 照合が不要だが、表記ゆれ・シノニム・
  版差がすべて文字列比較になり、ADR-0018 のゲートが壊れやすいまま。却下。
- **GBIF taxonKey をそのまま主キーにする**: 単純だが、GBIF に無い分類群
  （地域個体群、和名のみ）を表せない。却下。
- **カテゴリを正規化せず原表記のまま扱う**: 情報は失われないが、
  比較も判定もできない。原表記は `category_raw` に残すことで両立させる。部分的に採用。
