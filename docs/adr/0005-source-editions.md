# ADR-0005: 出典を版管理し、ライセンスを行単位で解決可能にする

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0001（原本）, ADR-0004（識別子）, ADR-0013（caveat）

## 背景

`source_registry`（124行）は取得元・ライセンス・再配布可否・取得日・件数を持っており、
v1 の中で最も素性が良い部分の一つ。ただし**版の概念がない**ため次が起きている。

- 同一出典の再取得が旧行を上書きするか、別 ID の行として増えるかが一貫しない。
  実例: `gbif_kanagawa` → `gbif_kanagawa_occurrences`（ADR-0004 参照）。
- 「この数字はいつ取得したデータか」がテーブル単位でしか言えない。行単位で
  `source_id` は持つが、**どの取得回か**は持たない。数値の再現ができない。
- ライセンスの扱いが場所によって違う。`organism_records` だけが `record_license` /
  `license_class` / `commercial_ok` の3列を持ち（DwC-A 出力の除外判定に使っている）、
  他のファクトは `source_registry.license` を辿るしかない。
- モニタリングサイト1000 の10ソースは、規約同意が無断で行われた経緯から
  `redistributable=0` として**配布物から隔離**されている（`docs/COLLECTOR_CONTRACT.md`）。
  データは保全しつつ出力から外すという運用が、いま人手とスクリプト個別の判断に依存している。

## 決定

**`source`（不変の出典）と `source_edition`（取得回＝版）に分け、すべてのファクトが
`source_edition_id` を持つ。ライセンスは版に属し、行単位で解決できるようにする。**

```
source          source_id, name, publisher, homepage, region_id, theme, access_method
source_edition  edition_id, source_id, fetched_at, url, format, content_sha256,
                license_id, license_class, redistributable, commercial_ok,
                record_count, superseded_by, embargo_reason, notes
license         license_id, name, spdx_or_url, class, attribution_text
```

1. **ファクトは `source_edition_id` を持つ**（`source_id` ではない）。これで「この数字は
   2026-08-29 取得の GBIF 第3ラウンド由来」まで行単位で言える。
2. **ライセンス判定はコードに書かない。** 出力・API・MCP は
   `license_class` / `redistributable` / `commercial_ok` を**フィルタ条件として受け取り**、
   除外した件数を応答に含める（ADR-0014）。DwC-A アダプタの現行ポリシー
   （`noncommercial`/`unknown` を除外）はアダプタ設定として明示する。
3. **隔離は削除ではない。** `redistributable=0` の版（実測33ソース）は `core/` に保持し、
   **`dist/`・L3・公開物からは落とす**（ADR-0001 の `core/` と `dist/` の分離）。
   落とした事実と理由（`embargo_reason`）は応答とカタログに出す。
   **`core/` は配布しない。** ここを混同すると隔離データがそのまま公開される。
4. **版の置換は `superseded_by` で表す**（`notes` の文字列ではない）。旧版は消さない。
5. `content_sha256` により、L0 の生ファイルと版が一致していることを検証可能にする。

## 影響

- **良い**: 数値の再現性が版で言える。ライセンス条件の異なるデータを1つの基盤に同居させたまま、
  出力先ごとに正しく出し分けられる。監査（何をなぜ落としたか）が構造化される。
  `docs/LICENSE_MATRIX.md` がテーブルから自動生成できるようになる。
- **コスト**: ファクトが1列増える。再取得のたびに版が増えるためカタログの行数が増える。
  「最新版だけ見たい」ためのビューが常に必要になる。
- **注意**: 版が増えたときにファクトを全部作り直すのか、版を混在させるのかは
  データセットごとに方針が要る（時系列の追記型 vs スナップショット型）。これは
  マニフェスト（ADR-0012）に `update_mode` として持たせる。

## 検討した代替案

- **`source_registry` に `version` 列を足すだけ**: 変更は小さいが、ファクト側が
  引き続き `source_id` しか持たないため「どの取得回か」が行単位で言えない。却下。
- **ライセンスをファクトの列として全テーブルに持つ**: 判定は速いが、
  `organism_records` の3列がすべてのファクトに増殖する。版で解決すれば足りる。却下。
- **再配布不可データを物理的に別ストアに置く**: 事故は起きにくいが、
  分析側で「あるはずのデータが無い」理由が見えなくなり、隔離の事実が記録から消える。却下。
