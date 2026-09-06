# ADR-0019: 分類群レジストリと、分類カテゴリの表記ゆれの扱い

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0004（ID）, ADR-0010（語彙）, ADR-0018（公開範囲）

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
