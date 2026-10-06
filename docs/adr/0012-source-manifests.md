# ADR-0012: L1→L2 でソース固有コードを書かない（マニフェスト＋共通ライブラリ）

- 状態: 承認済（Issue #40 Phase D で下記「改定」のとおり実装・改定。既存の 5 系統は `adapter: builtin` のメタデータだけ） / 日付: 2026-09-06（改定 2026-10-06）
- 関連: ADR-0005（版）, ADR-0007（observation）, ADR-0010（指標）

## 背景

Tier 1 のデータ追加時に起きたことを数えると、1回の追加で以下が増えた。

- テーブル5つ（`protected_areas` / `vegetation_polygons` / `mammal_mesh` /
  `wildlife_sightings` / `river_segments`）＋ DDL（`scripts/schema_tier1.sql`）
- 変換スクリプト1本（`scripts/m05_tier1.py`、389行）
- API 4本（`/api/nature?kind=...`、`/api/geo/{protected-areas,vegetation,river-segments}`）（→ `/api/nature` は Issue #61 で撤去）
- Drizzle スキーマ・`TABLE_ORIGIN`・`TABLE_META` への追記

収集側（`scripts/c*.py` と `docs/COLLECTOR_CONTRACT.md`）は既に規約が明確で、
`data/processed/<source_id>.{csv,jsonl}` という一定の出力形に揃っている。
**問題は L1→L2 の変換が毎回コードとして書かれていること。**

## 決定

**L1→L2 について「ソース固有のコードを書かない」を目標にする。ただし表現手段は
汎用 DSL ではなく、(1) メタデータと検証を記述するマニフェスト ＋ (2) 共通ライブラリの
型付き写像関数、の2つに分ける。**

汎用の変換 DSL を作らないのは、ソース追加が年に数本という頻度に対して
「YAML が別の言語になる」保守コストが釣り合わないため（本 ADR の「リスク」節）。
マニフェストが担うのは**版・ライセンス・更新方式・語彙の割付・検証**であり、
複雑な写像は共通ライブラリの関数（`resolve_place` / `resolve_variable` / `to_period` …）を
呼ぶ短いコードで書く。**ソース固有のロジックが必要になったら、それは共通ライブラリの欠落**
として扱う。

```yaml
# manifests/kanagawa_kuma_sightings.yml
source: kanagawa_kuma_sightings
region: jp-14
edition:
  fetched_at: 2026-08-30
  url: https://...
  license: CC-BY-4.0
  redistributable: true
input: data/processed/kanagawa_kuma_sightings.jsonl
update_mode: append          # append | snapshot（ADR-0005）

target: occurrence           # observation | occurrence | feature | place | document
map:
  observed_on:  { from: date_raw, grain: day }
  taxon:        { const: "common:taxon:gbif.2433433" }   # ツキノワグマ
  place:
    resolve: { by: name, kind: municipality, from: city_ja }
  individual_count: { from: count_raw, type: number }
  attributes:
    situation:  { from: situation_ja, codelist: sighting_situation }
provenance:
  source_ref: { from: row_url }
checks:
  - not_null: [observed_on, place]
  - in_codelist: { column: situation, list: sighting_situation }
  - row_count_between: [1, 5000]
```

原則:

1. **マニフェストに書けないものは共通ライブラリの欠落**として扱い、ライブラリ側を汎用化する。
   ソース専用の分岐を書かない。書く場合は「なぜ書けなかったか」を記録に残す。
2. **未知の語彙は落とさず通す。** 指標・コードが未登録なら `needs_review` として記録し、
   取り込み自体は成功させる（ADR-0010）。
3. **検証はマニフェストの `checks` に書く。** 現行 `scripts/m99_validate.py` の役割を
   ソース単位に分解して宣言化する。
4. **収集（L0→L1）は現行のまま**。`scripts/c*.py` と `COLLECTOR_CONTRACT.md` は維持する。
   ここは各サイトの事情が強く、汎用化の利得が小さい。
5. マニフェストは**リポジトリの一級の成果物**。パイプラインを公開する際、
   「マニフェストの書き方」が他地域・他組織にとっての入口になる。

## 影響

- **良い**: 合格条件1（L1→L2 でソース固有コードを書かない）が満たせる。
  版・ライセンス・検証の差分が YAML で読め、非エンジニアもレビューに参加できる。
  他地域が自分のソースを足せる（Y3「フォーム定義の外部化」と同じ思想）。
- **限界の明示**: 収集（L0→L1、`scripts/c*.py`）は各サイトの事情が強く、
  今回の汎用化の対象外。Tier 1 追加のコストの大半は実はここにあった
  （`scripts/c80`〜`c88`）。**「ソース追加のコストがゼロになる」とは主張しない。**
- **コスト**: 変換エンジンの汎用化に前払いが要る（座標解決、名寄せ、コードリスト照合、
  単位変換）。当初はマニフェストで表せないケースが必ず出る。
- **リスク**: YAML が「別の言語」になって複雑化する危険がある。**表現力を意図的に絞り**、
  複雑な前処理は L1 側（`scripts/c*.py` の出力）に押し戻す方針を明記する。

## 検討した代替案

- **変換スクリプトの共通ライブラリ化（コードのまま）**: 現行の `m0x` の延長。
  柔軟だが、追加のたびにコードレビューとデプロイが要り、非エンジニアが足せない。却下。
- **dbt など既存の変換ツールを使う**: 成熟しているが、SQL 中心で
  「ソース別の名寄せ・座標解決・コードリスト照合」の記述には向かず、
  Parquet/R2 前提の配布（ADR-0001）との噛み合わせも良くない。将来 L2→L3 の集計
  （ADR-0011）で再検討する余地は残す。見送り。
- **取り込みを完全自動化（スキーマ推論）**: 手間は最小だが、
  「推測で埋めない」という収集規約の根幹に反する。却下。

## 改定（2026-10-06、Issue #40 Phase D）

上の「決定」の `map:`（YAML で `from:`/`const:`/`resolve:` を書く案）は**採らなかった**。「表現力を意図的に絞る」と
言いながら別の言語になるリスク（本 ADR の影響節）が現実になる前に、変換だけを Python に戻した。実装と異なる部分は
次のとおり読み替える（`scripts/ingest/manifest.py` の docstring が現行の仕様）。

1. **マニフェスト = 宣言（`manifests/<source_id>.yml`）、変換 = adapter（`scripts/adapters/<source_id>.py` の短い
   `rows(ctx)`）**。変換 DSL は作らない。adapter が import してよいのは **`ingest.api` と標準ライブラリだけ**
   （AST 検査 `scripts/tests/test_adapter_boundary.py` が固定。`migrate`・`registry`・`sqlite3` を直接 import して
   共通検査〔重複・解決率・期間・checks・宣言突合〕を迂回する経路を塞ぐ）。
2. `edition`/`license` はインラインで書かない。`edition` は `registry/source/editions.yaml` の `edition_key` を
   参照するだけ（ADR-0005）。`update_mode` は**マニフェストが正**（必須。`snapshot|append|revision|static`。
   未宣言・enum 外は止まる）で、registry ビルドが `source_edition.update_mode` に流す。editions.yaml に同じ出典が
   あって食い違えば止まる（二重管理にしない）。
3. `target` は `observation`/`occurrence` のみ（`feature|place|document` は需要が出るまで書けない＝検証で止まる）。
   adapter 経由の取り込みは現状 occurrence のみ実装（非 builtin の observation は b03 が止まる）。
4. `checks` の語彙は実装済みの 5 つだけ: `not_null` / `unique` / `row_count_between` / `in_registry`（taxon）/
   `date_between`。`in_codelist` は codelist 表が無いので入れない。
5. `redistributable` は出典の旗で、出力を絞らない（ADR-0028）。
6. **既存 5 系統（measurements・sensor_timeseries・土地利用・organism_records の 13 出典）は `adapter: builtin`**
   （region・update_mode・件数・版参照のメタデータだけ。変換は b03/b06 のまま。出力を 1 ビットも動かさない）。
   13 出典の `update_mode`（各 `manifests/*.yml` の `evidence` に根拠）は **2026-10-07 オーナー確認済み**（値は変更なし）。
   マニフェストに無い出典・マニフェストにあるのに誰も処理しない出典はどちらも止まる。
7. 新出典の宣言値（期間の形ごとの件数・leaf/month/流域の解決件数・座標なしの件数）は、`scripts/migrate/*.yaml` を
   触らずに済むよう、マニフェストの `expected:` ブロックに書く（b06/b07/b09 は yaml の宣言値とこの値の和と突合する。
   宣言は残る＝黙って自動計算にしない）。ソース追加の PR が触れるのは `manifests/`・`scripts/adapters/`・`registry/`・
   `scripts/tests/`・サンプル再生成物だけで、`scripts/check_source_add_boundary.py` が差分で機械的に検査する。
8. 例の `taxon: common:taxon:gbif.2433433` は registry に存在しない ID だった（ツキノワグマは `gbif.6163862`〔亜種〕・
   `gbif.9335699`・`inat.41647`〔species〕・`inat.418146`〔亜種〕）。`const` の taxon は registry に実在することを
   ビルドが検査する（`in_registry`）。
9. adapter の `attributes`（出典固有の補助情報）は `occurrence.attributes`（JSON 文字列、NULL 可）に保存する。
   既存の builtin 出典は NULL。D1 には L2 を入れない（変わらない）、dist には載る。
10. **未対応・着手条件**: ①非 builtin の observation adapter（b03 が止まる）は、観測型の新出典が実際に要る時に
   alias・単位・期間の解決を ingest.api に足して実装する。②出典の鮮度一覧 CLI（`scripts/freshness.py`）は作らない
   （鮮度は応答封筒の `age_days`/`update_mode` で足りる。一覧が運用で要る時に足す）。
