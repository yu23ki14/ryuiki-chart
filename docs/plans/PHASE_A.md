# Phase A 実装計画 — レジストリの並走

対象: ADR-0016 の Phase A / 状態: **計画（未着手）** / 作成: 2026-09-06

## 0. このフェーズの定義

**v1 のファクトを一切動かさずに、語彙レジストリ（`variable` / `unit` / `place` / `taxon` /
`caveat`）を並走させる。**

- **やること**: レジストリのテーブルとデータを作り、v1 の全ファクトがそこに解決できることを
  数字で示す。AI アシスタントと（将来の）MCP がレジストリを読むようにする。
- **やらないこと**: `measurements` / `organism_records` / `sensor_timeseries` の書き換え、
  Parquet 化、キューブ化、ID の付け替え、検閲値の修正、点→place の解決。
  **既存の画面の数値は1つも変わらない。**
- **なぜ最初にこれか**: 「MCP が誤読する」問題（README §1(b)）の大半は語彙と注記が
  データに載っていないことに起因する。Phase A だけで、ファクトを1行も動かさずにそこが解ける。

## 1. 成果物

| # | 成果物 | 実体 |
|---|---|---|
| D1 | レジストリのソースファイル | `registry/*.yaml` `registry/*.csv`（Git 管理・レビュー対象） |
| D2 | レジストリのスキーマ | `web/src/db/schema.ts` に**追加**（既存69テーブルは変更しない） |
| D3 | ビルドスクリプト | `scripts/r01_build_registry.py` → `data/db/registry.sqlite` |
| D4 | 解決レポート | `scripts/r02_resolution_report.py` → `reports/registry_resolution.md` + CSV |
| D5 | 配線 | `web/src/lib/registry/` （読み出し層）＋ `caveats.ts` / `prompt.ts` / `tools.ts` の切替 |
| D6 | 移行の足場 | `domain.ts` をレジストリ参照の薄い層にする（13ファイルの利用側は当面そのまま） |

**なぜソースをファイルに置くか**: レジストリは公開パイプラインの中核成果物であり、
他地域が最初に読む/書き換えるものになる。PR の差分としてレビューできる形が要る。
D1 は ADR-0001 により「捨てて作り直せる」ので、正は常にファイル側。

**なぜ `registry.sqlite` を経由するか**: `seed-d1-local.mjs` は既に
`ryuiki` / `cells` / `derived` の3ファイルを読む構造なので、**4本目を足すだけ**で
ローカル D1・`db:export`・本番投入の経路がすべてそのまま使える。新しい配管を作らない。

## 2. 作業項目

### A-1 スキーマ追加（S）

`web/src/db/schema.ts` に7テーブルを追加し、`pnpm run db:generate` でマイグレーションを作る。
**既存テーブルの定義には触らない**（追加のみなので既存データは無傷）。

```
unit             unit_id, symbol, ucum, name_ja, quantity_kind
variable         variable_id, code, name_ja, name_en, theme, unit_id, value_type,
                 default_stat, higher_is_worse, description_ja, status
variable_alias   alias, source_scope, variable_id, unit_id, stat, grain, note
place            place_id, region_id, place_kind, name_ja, lat, lon, elevation_m,
                 area_km2, definition_ref, status
place_source_ref place_id, external_key, source_id      -- v1 の site_id / watershed 等との対応
taxon            taxon_id, scientific_name, rank, gbif_taxon_key, vernacular_name_ja,
                 status, accepted_taxon_id
caveat           caveat_id, scope_kind, scope_ref, severity, kind, title_ja, body_ja, quote
```

`taxon_name` と `taxon_assessment`（ADR-0019）は Phase A では作らない。
和名の名寄せと版管理は Phase B 以降。

### A-2 `unit` と `variable` のレジストリ（M）

**規模は小さく、手作業で終わる**:

```
measurements.variable   58種    unit 9種
sensor_timeseries.datastream 59種   unit 22種
                      → エイリアス計 117、単位計 31
```

- 117 のエイリアスを `registry/variable_alias.csv` に列挙し、正準 `variable` に割り当てる。
- **名前から単位・粒度・統計量を剥がす**（ADR-0010）。
  `河川水位_日平均` → `variable=river_stage, unit=m, grain=day, stat=mean`。
  `OX` / `Ox(ppm)` / `光化学オキシダント_日平均` → 同一 `variable`。
- `domain.ts` の `VARIABLE_SHORT` / `VARIABLE_NOTE` / `HIGHER_IS_WORSE` /
  `VARIABLE_UNIT_FALLBACK` の内容を `variable` の列に移す。**推測で足さない**。
- 単位が原本で空の 109,078行は、**エイリアス側に単位を持たせて解決する**
  （出典が単位を落としているだけで、項目としての単位は既知のものが多い）。
  それでも決まらないものは `status='needs_review'` にして一覧に残す。

### A-3 `place` のレジストリ（M）

Phase A で登録する範囲を**集計軸として実在するものに限る**:

| place_kind | 件数 | 出どころ |
|---|---|---|
| `site` | 352 ＋ **不足分** | `sites`。**`sensor_timeseries` の77地点中65、`measurements` の7,846行の site_id が `sites` に無い**ので、出典側の地点台帳から補って登録する |
| `watershed` | 377 | `watershed_meta` |
| `mesh3` | 4,083 | `mesh_all` |
| `zone` | 5 | `docs/ZONE_DEFINITION.md`。**閾値と「公式区分ではない」ことを `definition_ref` に持たせる** |

- `town_block`（5,089）と `river_segment`（1,547）は Phase A では登録しない
  （水道サブモデルと地物であり、キューブの軸として使うのは後）。
- `place_relation` は Phase A では作らない（点→place も含め Phase B）。
- `place_source_ref` で v1 の `site_id` / `watershed_id` / `mlat,mlon` を引けるようにする。
  **これが「v1 を動かさずに並走させる」ための接続点**になる。
- `sites.municipality` の混在（290地点が水域名）は**直さない**。事実を `caveat` に登録する。

### A-4 `taxon` のレジストリ（L・最大の難所）

実測で分かったこと（当初の想定と違う）:

```
organism_records  822,839 / 823,692 行 (99.9%) が GBIF taxon_key を持つ
                  distinct taxon_key = 33,604
taxa              8,585行。うち gbif_taxon_key を持つのは 2,643
                  gbif_match_type: EXACT 2,343 / HIGHERRANK 240 / FUZZY 60 / NONE 34 / NULL 5,908
両者の重なり       distinct taxon_key のうち taxa と一致するのは 818 だけ
学名文字列での一致  occurrence の 33,130 学名のうち taxa と一致するのは 763
```

つまり **`taxa` は occurrence の分類語彙ではない**。`taxa` はレッドリスト・外来種リスト由来の
和名中心の語彙（5,908件が GBIF 未照合）で、occurrence は GBIF 由来の学名中心。
**2つの母集団を1つの `taxon` に束ねるのが Phase A の実体**である。

方針:

1. **occurrence 側は学名文字列ではなく `taxon_key` で解決する。** 99.9% がこれで済む。
   `taxon_id = common:taxon:gbif.<key>`（ADR-0004 規約0）。
2. **`taxa` 側の 5,908 件（GBIF 未照合）は捨てず `status='unresolved'` で登録する。**
   照合できないことをデータとして残す（ADR-0019）。
   既存の `scripts/c24_taxon_crosswalk.py` の成果を再利用する。
3. **和名は `domain.ts` の `NAME_JA`（人が確認した54種）だけを正として移す。**
   `taxa` の和名を学名で機械結合しない（`Plecoglossus altivelis` に
   「リュウキュウアユ」が付く既知の事故。`domain.ts` のコメントに記録がある）。
4. `taxon_key` を持たない 853 行は `taxon_id=NULL` のまま。レポートに出す。

### A-5 `caveat` のレジストリ（M）

現在の注記の在り処は3つ:

- `domain.ts` の `DATA_CAVEATS`（7件）と `BIOTA_CAVEATS`（6件）＋ `MUNICIPALITY_LABEL` の説明
- `web/src/lib/ai/caveats.ts` の**テーブル → 注記のマッピング**（既に決定論的に実装されている）
- `cells.notes`（207行。「時系列比較を阻害する注記」のフラグ付き）

作業:

1. 上記13件＋市区町村の1件を `registry/caveat.yaml` に移す。**文言は変えない**
   （変えると次項の回帰テストが意味を失う）。
2. `caveats.ts` のテーブル→注記マッピングを、`caveat.scope_kind='table'` の行として表現する。
3. `cells.notes` の207行を `caveat` に取り込む（`severity` は既存フラグから決める）。
4. **Phase A で新しい注記を書き足さない。** 移すだけ。追加は解決レポートで
   見つかったものを別 PR で。

### A-6 解決レポート（M・受け入れゲート）

`scripts/r02_resolution_report.py` が v1 の原本を読み、レジストリで解決できるかを数える。

| 対象 | 目標 | 備考 |
|---|---|---|
| `measurements` 323,164行 → `variable_id` | **100%** | エイリアス117は有限で手作業可能 |
| `sensor_timeseries` 717,839行 → `variable_id` | **100%** | 同上 |
| `measurements` の site_id 250種 → `place_id` | **100%** | 不足分は A-3 で登録 |
| `sensor_timeseries` の site_id 77種 → `place_id` | **100%** | 65種を新規登録 |
| `organism_records` 823,692行 → `taxon_id` | **≥99.8%** | 853行は taxon_key 無し。未解決を一覧に出す |
| 単位が決まる measurement 行 | 報告のみ | 109,078行の単位欠落がどこまで埋まるかを記録 |
| `taxa` 8,585行 → `taxon_id` | 報告のみ | `unresolved` の件数を明示する |

- **未解決は失敗ではない。「未解決の件数と一覧が出ること」が合格条件**である。
  黙って埋めない・落とさない（`docs/COLLECTOR_CONTRACT.md`）。
- レポートは `reports/registry_resolution.md` に出し、CI の成果物にする。

### A-7 AI アシスタントへの配線（M）

**ここが Phase A の価値が実際に出る場所。**

1. `web/src/lib/registry/` に読み出し層を作る（D1 から variable / caveat / taxon を引く）。
2. `web/src/lib/ai/caveats.ts` の注記の出どころをレジストリに切り替える。
3. `web/src/lib/ai/prompt.ts` の語彙説明をレジストリ由来にする。
4. `web/src/lib/ai/tools.ts` のツール結果に `variable_id` / `unit` / `caveat` のキーを載せる。

**回帰テスト（必須）**: 切替の前後で `caveats.ts` が返す注記の集合が
**テーブル名ごとに完全に一致する**ことを自動テストで確認する。
文言も順序も変えない。これが「Phase A は既存の挙動を変えない」の担保になる。

### A-8 `domain.ts` の扱い（S）

**13ファイルが `domain.ts` を import している**（`page.tsx` / `MapPage` / `SiteList` /
`TimeseriesExplorer` / `BiotaExplorer` / `QualityDashboard` / `DocumentsExplorer` /
`SiteDetail` / `SeriesChartCard` / ai の4ファイル）。

- Phase A では**利用側を書き換えない**。`domain.ts` を「レジストリから同じ形の定数を作る
  薄い層」にし、`@deprecated` を付ける。
- `rowKeyLabel()` `speciesLabel()` のような**関数**はレジストリの対象外。そのまま残す。
- 完全な撤去は Phase B 以降。

## 3. 実行順序と依存

```
A-1 スキーマ ──┬─→ A-2 variable/unit ──┐
               ├─→ A-3 place          ├─→ A-6 解決レポート ─→ A-7 AI配線 ─→ A-8 shim
               ├─→ A-4 taxon          │
               └─→ A-5 caveat ────────┘
```

- A-2 / A-3 / A-4 / A-5 は独立なので並行できる。**A-4 が最長**。
- A-6 は A-2〜A-5 が揃ってから。ただし**部分的に先行実装して途中経過を出す**のが望ましい
  （解決率が見えないまま語彙を作り込むと手戻りが大きい）。
- A-7 は A-5（caveat）と A-2（variable）だけあれば着手できる。A-4 の完了を待たない。

**作業量の目安**: A-1 小 / A-2 中 / A-3 中 / A-4 大 / A-5 中 / A-6 中 / A-7 中 / A-8 小。
A-4 の 33,604 taxon_key と 5,908 未照合の扱いが全体の半分近くを占める。

## 4. Phase A の完了条件

1. `pnpm run db:setup` でレジストリを含む D1 が作れる（新しい配管を足していない）
2. `reports/registry_resolution.md` が生成され、上表の目標を満たしている
3. `caveats.ts` の回帰テストが通る（**既存の挙動が1つも変わっていない**）
4. AI アシスタントの注記と語彙がレジストリ由来になっている
5. レジストリのソースがすべて `registry/` にあり、D1 を捨てて再構築できる
6. **v1 のテーブルとファクトに変更が無い**（`git diff` で確認できる）

## 5. リスク

| リスク | 対処 |
|---|---|
| A-4 の taxon 照合が想定以上に重い | A-7（AI配線）は A-4 を待たずに進める。taxon は `unresolved` を許容して段階的に埋める |
| 語彙を作りながら「ついでに直したくなる」 | Phase A では**移すだけ**。修正は解決レポートに記録して別 PR にする |
| `caveats.ts` の回帰テストが書きにくい | 先に現行実装のスナップショットテストを書いてから切り替える（切替前に緑にする） |
| レジストリが D1 のサイズを圧迫 | taxon 33,604行が最大。他は合計1万行程度で、既存340万行に対して無視できる |
| 単位の欠落 109,078行が埋まらない | 埋めないことを許容する。`needs_review` の件数が可視化されること自体が Phase A の成果 |

## 6. Phase A で**決めない**こと（Phase B 以降）

点→place の解決規約の実装（ADR-0006）、検閲値の扱いの変更（ADR-0009）、
時間の3点セット化（ADR-0008）、キューブ（ADR-0011）、ID の付け替え（ADR-0004）、
`source_edition`（ADR-0005）、公開ルールの強制（ADR-0018）、マニフェスト（ADR-0012）。

**Phase A の間、これらの ADR の決定は「まだ効いていない」。**
レジストリの列は将来それらを受けられる形にしておくが、値は埋めない。
