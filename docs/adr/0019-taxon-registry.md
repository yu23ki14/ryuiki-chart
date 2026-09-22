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
