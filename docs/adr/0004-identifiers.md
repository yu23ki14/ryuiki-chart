# ADR-0004: 識別子はスコープ付きの安定IDとし、既定を `common` にする

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0002（多地域）, ADR-0005（版）, ADR-0006（place）

## 背景

現行の ID には規約が無く、出典の都合がそのまま漏れている。

- `sites.site_id`、`events.event_id`、`measurements.measurement_id` は text だが採番規則が
  ソースごとに違う。
- `watershed_id` は国土数値情報のコード（`83032-0024`）、メッシュは `mlat`/`mlon` の2列、
  ゾーンは整数 1〜5、町丁目は国勢調査の小地域コード。**同じ「場所」なのに ID の形が5種類**。
- `source_registry` では `gbif_kanagawa`（旧・586,300行時点）と `gbif_kanagawa_occurrences`
  （新・658,360行）が併存し、旧行は削除せず `notes` 冒頭に `【SUPERSEDED 2026-08-29】` を
  付けて無効化してある（`docs/REBUILD.md`）。**識別子の版管理を notes 文字列で代用している。**
- 外部公開（DwC-A の `occurrenceID`、GBIF の再取り込み）では ID の安定性が要件になるが、
  現在それを保証する仕組みがない。

## 決定

**すべてのコアエンティティの主キーを、次の形の安定 ID にする。出典 ID とは分離する。**

```
<scope>:<entity>:<local_key>          scope は 'common' または region_id

例)  common:variable:water.bod         レジストリは既定で common
     common:taxon:gbif.2480932         分類群は地域の属性ではない
     common:place:watershed.nlni-83032-0024   県境をまたぐ流域も common
     jp-14:place:site.env-pubwater-0142       出典が県単位の地点
     jp-46-tatsugo:place:zone.r2r-3           地域固有の操作的定義
```

規約:

0. **`scope` の既定は `common`。** レジストリ（`variable` / `taxon` / `unit`）と、
   県境をまたぐ実体（相模川・多摩川のような流域）は常に `common`。
   **地域固有だと分かっているものだけ** `region_id` をスコープにする。
   これは「あとで共通語彙に昇格したら ID が変わる」＝規約2（ID は不変）違反を防ぐため。
   地域は**ファクトのパーティション列 `region_id`** で表すのであって、
   レジストリの ID に埋めない（ADR-0002）。

1. **`local_key` は出典の識別子をそのまま使ってよいが、必ず名前空間を前置する**
   （`gbif.` / `nlni-w05.` / `estat.` …）。出典が変わっても衝突しない。
2. **ID は不変。** 対象の実体が変わったら新しい ID を作り、旧 ID は `superseded_by` で
   新 ID を指す行として残す（削除しない）。`notes` の文字列で表さない。
   スコープの変更（`jp-14:` → `common:`）は ID の変更にあたるので、**規約0 により
   そもそも起こさない**。判断に迷うものは `common` に置く。
3. **出典 ID（`source_id`）とエンティティ ID を混ぜない。** 同じ地点が複数出典に現れる場合、
   place は1つで、出典ごとの対応は `place_source_ref` の行として持つ。
4. **公開 ID は URI に解決できる形にする**（`https://<host>/id/jp-14/place/site.env-...`）。
   DwC-A の `occurrenceID` と DCAT の `dct:identifier` はこれを使う。
5. 合成データ（`is_synthetic=1`）は名前空間で区別する（`synthetic.` 接頭辞）。
   実データと ID 空間で混ざらないようにする。

## 影響

- **良い**: 「同じ地点か」の判定が ID で決まる。多地域で衝突しない。公開 ID の安定性が
  DwC-A / GBIF 再取り込みの要件を満たす。SUPERSEDED の扱いが構造化される。
- **コスト**: ID が長くなり、D1 のインデックスサイズと結合コストが増える。
  現行の全 ID を付け替える移行が必要（対応表を残す）。
- **注意**: `local_key` に出典の識別子を使うため、出典側が ID を再利用した場合に
  取り違えが起きうる。名前空間に版を含めるかは ADR-0005 と合わせて決める。

## 検討した代替案

- **UUID を振る**: 衝突しないが、人間が読めずデバッグと突合が辛い。出典との対応を
  常に別表で引く必要がある。却下（ただし `local_key` を作れないケースの逃げ道として残す）。
- **現行の素の文字列 ID を維持**: 移行コストゼロだが、多地域で確実に衝突し、
  「場所の ID の形が5種類」が解消されない。却下。
- **整数の連番**: サイズは最小だが、再構築のたびに値が変わりうるので公開 ID にできない。却下。
