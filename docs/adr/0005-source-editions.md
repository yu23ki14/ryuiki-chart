# ADR-0005: 出典を版管理し、ライセンスを行単位で解決可能にする

- 状態: 承認済（一部未実装） / 日付: 2026-09-06
- 関連: ADR-0001（原本）, ADR-0004（識別子）, ADR-0013（caveat）

**2026-09-24 追記（P-1b、`docs/plans/PHASE_B_LANDUSE.md`）**: 「同じ出典に
複数版が同居する」の最初の実例が土地利用（国土数値情報 L03-b、2006年版/
2016年版でコード体系が違う）で実際に起きた。正式な `source`/`source_edition`
分割（Phase C）より前に、`registry/variable_alias.csv` の `dataset` 列を
`<source>@<year>` の形にする暫定策で対応した（`docs/plans/PHASE_B_INTAKE.md`
に接続点として記録。恒久設計ではない）。

**2026-09-25 追記（Issue #38、`docs/plans/DATA_QUALITY_BACKLOG.md` §1・§2）**: 同型の
実例をさらに2件確認した。(1) 地盤沈下（`kanagawa_jiban_chinka`）: 神奈川県の年次報告書
r5table.xlsx（令和5年度版）と r6table.xlsx（令和6年度版）が同じ年の値を再掲しており、
両方を収集した結果 `measurements` に1,625組の重複が生じている。(2) GBIF の再取得
（`gbif_kanagawa_occurrences`）: 本文中で既に挙げた例そのものだが、`scripts/common.py`
の `register()` が `source_registry` を `source_id` 単位で `INSERT OR REPLACE` するため、
429対策の再取得（`c02_gbif_repair.py`）が初回取得（`c02_gbif.py`）の `record_count`/
`notes`/`fetched_at` を上書きし、取得回ごとの数値が復元不能になっていることを実測で
確認した。どちらも本ADRの `source_edition`＋`superseded_by`（Phase C）で解く領域。
決定は変えない。

**2026-10-06 改定（Issue #39 Phase C。`docs/plans/ISSUE39_PHASE_C.md` §2.2・§3）**: 状態を提案中から
承認済に上げ、`source`/`source_edition`/`license` を `registry.sqlite`（と D1）に実装した
（`scripts/registry/build_source.py`、手書きの正は `registry/source/{license,editions}.yaml`）。
次の点を決定として改める。

- **隔離は行わない（決定2・3を上書き）。** 扱うデータは全て公開済みで、ライセンス表示も不要というオーナー決定
  と ADR-0028（座標をぼかさない）により、`redistributable` / `license_class` / `commercial_ok` は
  **出典の旗として列に残すだけ**で、出力・API・DwC-A を絞る根拠にしない。決定3の「`dist/`・公開物から落とす」
  「`embargo_reason` を応答・カタログに出す」は撤回し、**`embargo_reason` 列は作らない**。
  人の判断待ちで出力を止めない。
- **列の確定**: `source` に `source_ref_id`（公開 ID `common:source:<source_id>`）・`theme`・`superseded_by`
  （置換先の source_id）。`source_edition` に `edition_key`・`vintage`・`update_mode`（ADR-0020 の
  snapshot/append/revision/static。分かるものだけ宣言し、無いものは NULL）・`license_raw`（原文）。
  `source_id` は bare のまま（`[a-z0-9_]+` なので公開 ID と全単射）。cube・D1 summary・variable_alias は bare を持つ。
- **edition とは取得回、または出典自身の版（vintage）。** 土地利用 L03-b の 2006/2016 は vintage、
  それ以外は取得日 `YYYYMMDD`。`edition_id` = `common:edition:<source_id>.<edition_key>`。
- **版の履歴が復元不能な既存行は作らない（捏造しない）。** `source_registry` は `INSERT OR REPLACE` で
  上書きされてきたので、現在の1版 + 宣言した版（`editions.yaml`）だけを持つ。「行単位で取得回が言える」のは
  将来の再取得から。
- **置換は `superseded_by`**: `gbif_kanagawa` → `gbif_kanagawa_occurrences` を `source.superseded_by` と
  `source_edition.superseded_by` の両方に張った（ADR-0004 規約2）。notes の `【SUPERSEDED` は、宣言の無い
  行を検出するための検査にだけ使い、参照側は常に `superseded_by` 列を使う。
- **ファクトの `source_edition_id`は L2（v2 の observation/occurrence）のみ**。キューブ・D1 summary は
  `source_id`（bare）のまま（キューブのセル鍵を動かさないため）。
- `variable_alias.dataset` の `@<年>` 後置（2026-09-24 追記の暫定）は廃止し、`edition_key`（→ `source_edition_id`）に
  置き換えた。旧→新の対応は `registry/id_map/dataset.csv`。
- `source_registry`（v1 表。D1 の `queries.ts` が使用中）は並走して残す。撤去は別 Issue。

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
                -- 2026-10-06 改定: embargo_reason は作らない。edition_key, vintage, update_mode,
                -- license_raw を足した（実装は scripts/schema_registry.sql の source_edition）
license         license_id, name, spdx_or_url, class, attribution_text
```

1. **ファクトは `source_edition_id` を持つ**（`source_id` ではない）。これで「この数字は
   2026-08-29 取得の GBIF 第3ラウンド由来」まで行単位で言える。
2. （2026-10-06 改定: 出力の絞り込みには使わない。上の改定参照）**ライセンス判定はコードに書かない。** 出力・API・MCP は
   `license_class` / `redistributable` / `commercial_ok` を**フィルタ条件として受け取り**、
   除外した件数を応答に含める（ADR-0014）。DwC-A アダプタの現行ポリシー
   （`noncommercial`/`unknown` を除外）はアダプタ設定として明示する。
3. （2026-10-06 改定: 撤回。隔離せず、旗として残すだけ。`embargo_reason` は作らない）**隔離は削除ではない。** `redistributable=0` の版（実測33ソース）は `core/` に保持し、
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
