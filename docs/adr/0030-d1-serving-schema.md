# ADR-0030: D1 の配信スキーマ — キューブを直接載せ、summary は宣言的集計、画面は `value_lod`、合成データは出さない

- 状態: 提案中（オーナー承認待ち） / 日付: 2026-09-26
- 関連: ADR-0001（D1 は L3 の配信キャッシュ）, ADR-0006（place）, ADR-0009（検閲値・
  `value_zero`/`value_lod`）, ADR-0011（キューブ・宣言的集計）, ADR-0014（応答封筒）,
  ADR-0017（書き込み系ログの扱い、合成データ）, ADR-0021（キューブの鍵）,
  ADR-0022（place.region_id）, ADR-0025（occurrence ファクトとキューブ）,
  ADR-0026（occurrence→watershed）, ADR-0028（座標の一般化はしない）,
  ADR-0029（v1 の撤去と検証の引き継ぎ。本 ADR と対で読む）,
  Issue #48, [docs/plans/V2_SERVING.md](../plans/V2_SERVING.md)（移行計画本体）

## 背景

[ADR-0001](0001-storage-layers.md) は「D1 は再構築可能な配信キャッシュ」という原則を
既に決めていたが、具体的に何を D1 に入れるかは決めていなかった。現行の D1（本番相当の
ローカルシード）は `ryuiki.sqlite`/`cells.sqlite`/`derived.sqlite` の61テーブルを素朴に
統合したもので、**L2 相当の生ファクト表（`measurements`・`organism_records` 等）と
派生33表と原本表が未分化のまま同居**している。`docs/plans/V2_SERVING.md`（Issue #48、
オーナー決定 2026-09-26、「v1 のレガシーは一切残さない」「案2＝キューブ直読みを最後まで
やる」）は、この構成を作り直す。本 ADR は、そのとき D1 に何を入れ何を落とすか、
索引・容量・代入方式・合成データの扱いという「配信スキーマ」を決める。

対になる [ADR-0029](0029-v1-removal-and-verification-handoff.md) は「v1 を撤去した後の
検証をどう引き継ぐか」を決める。本 ADR は「撤去した後の D1 の中身をどう設計するか」を
決める——両者は Issue #48 の同じオーナー決定から分岐した対の決定であり、片方だけでは
Issue #48 の設計として閉じない。

## 決定

### D1. D1 に入れるもの・落とすもの

**キューブ2表を直接配信する**（案1「v1 形の射影を D1 に持つ」は採らない）。

| 区分 | 入れる | 落とす |
|---|---|---|
| ファクト | — | `observation` / `occurrence` / `occurrence_place`（L2。ADR-0001 の原則どおり D1 は L3 の配信キャッシュに限る） |
| キューブ（L3） | `observation_agg` / `occurrence_agg` | — |
| レジストリ | `unit`/`variable`/`variable_alias`/`place`/`place_source_ref`/`taxon`/`caveat`/`caveat_scope`（既存8表）＋ 新設4表（D2） | — |
| summary（L3、宣言的集計） | 指標カタログ・地点×指標・種カタログの3表（D6） | — |
| v2 に相当物の無い原本表 | `cells`/`notes`/`documents`・`sites`・`source_registry`・Tier 1 の5表（`protected_areas`/`vegetation_polygons`/`mammal_mesh`/`wildlife_sightings`/`river_segments`） | — |
| 派生33表 | — | `meas_*`/`zone_*`/`sensor_daily`/`sensor_hour_month`/`rain_daily`/`species*`/`org_*`/`mesh_*`/`redlist_map`/`redlist_change`/`doc_series*`/`quality_monthly`/`landuse_*`/`effort_year`/`ias_species`/`var_catalog`/`site_var`/`watershed_rollup` 全33表 |
| 生ファクト（v1由来） | — | `measurements`/`sensor_timeseries`/`organism_records`/`taxa`/`redlist_assessments` |
| 書き込み系ログ・合成データ | — | `decisions`/`interventions`/`quality_transitions`/`observers`/`events`/`event_observers`（ADR-0017 が読み取り基盤の対象外とする書き込み系ログ。合成データのみで構成される表、D4） |
| （任意、PR-6） | — | `water_*`（8表）・`vocab_*`（4表）・`extraction_log` |

容量見積もり（実測、2026-09-26、索引つき）: `observation_agg` 約680MB（slim 版 約260MB）、
`occurrence_agg` 約140MB。今のローカル D1 1,295MB → **約500〜900MB**（レジストリ・
summary・残す原本表を含む）。D1 の上限（10GB、込み容量5GB）に対し余裕がある。

### D2. 新設するレジストリ表

- `place_relation`（ゾーン・流域の JOIN。ADR-0006 の「点→place の解決規約」が定義する
  辺の実体）。
- `place_watershed`（occurrence の座標→流域の解決結果。ADR-0026 の `occurrence_place`
  サテライトのうち、配信に要る列だけを軽量に運ぶ。O-2b で `occurrence_agg` に
  `place_kind='watershed'` のセルが足された後、その裏付けとして持つ）。
- `taxon_assessment`（RL・外来種評価。`registry.sqlite` にのみあり、`scripts/registry/
  build_taxon_assessment.py` が作る。除外7種は r01 で `in_scope` 列にして持ち込む——
  `registry/taxon/assessment_scope_exclusions.yaml` の除外規約をデータとして運ぶ
  という設計は変えない）。
- `taxon` への列追加: `canonical_binomial`/`class`/`family`/`taxon_group`（`registry.sqlite`
  の `taxon` には既にあるが `web/src/db/schema-registry.ts` の `taxon` には無い）＋
  新設 `vernacular_name_en`。

いずれも既存の `web/src/db/schema-registry.ts` への追加として実装する
（`web/src/db/schema-cube.ts` は新設）。

### D3. 索引

Drizzle の schema で宣言する。

```
observation_agg(variable_id, place_id, grain, stat, period_start)
observation_agg(place_id, variable_id, grain)
occurrence_agg(taxon_id, period_start)
occurrence_agg(place_id, period_start)
```

キューブの次元キー自体（`observation_agg` の12列・`occurrence_agg` の8列、ADR-0021・
ADR-0025 D2 が既に決定済み）は変えない。索引はその上に、問い合わせ層
（`web/src/lib/cube/`、`docs/plans/V2_SERVING.md` §3.4）が実際に使うアクセスパターンに
合わせて張る。

### D4. 合成データは D1 に出さない

`is_synthetic=1` の行を、キューブの入力段階（`scripts/b03_build_observation.py`/
`scripts/b06_build_occurrence.py`）で除く。**キューブそのものを作ってから配信時に
フィルタするのではなく、ファクトを作る時点で除く**——ADR-0017 原則4「デモに含まれる
合成の可変データは当面 L2 の一部として扱う」は撤回し、合成データを配信対象外にする。

合成データしか表示しない画面（品質・介入・意思決定・ペア測定のデモ）は撤去する
（`docs/plans/V2_SERVING.md` PR-4）。書き込み系ログの表（`decisions`/`interventions`/
`quality_transitions`/`observers`/`events`/`event_observers`）も D1 に入れない（D1 の表、
上表「書き込み系ログ・合成データ」行）。

### D5. imputation の扱い

- **画面は `value_lod` 固定**（定量下限の値を代入した系列）。注記
  （`registry/caveat.yaml` の `censored`）も `value_lod` を名指しする文面に書き換える
  （ADR-0009 の「いま見えているものを名指しする方が正直」という既定の方針をそのまま
  `zero` 系列から `lod` 系列に付け替える）。
- **AI/API の応答封筒（ADR-0014）は `value_zero`/`value_lod` の両方を返す。**
  単一の `value` を返すのは呼び出し側が `imputation` を明示したときだけ（ADR-0014 決定1）。
- **`half_lod` は出さない**（保存された列ではなく `(value_zero + value_lod) / 2`
  として式で導出できる値であり、ADR-0009 決定4が「妥当な既定として黙って適用してよい
  ものではない」としたリスクをそのまま引き継ぐ——LOD が年代・検査機関で変わると系列に
  段差が出る）。
- `not_detected` の `value_zero` 例外（ADR-0009 決定4「v1 再現のための時限的な例外」）は
  v1 撤去後も**直ちには**撤去しない。`docs/plans/V2_SERVING.md` PR-6 で扱う
  （撤去すると `b05` の v1 射影——PR-5 で既に削除済み——と ADR-0016 の受け入れ基準が
  参照する対象が両方無くなるため、影響範囲を PR-6 で改めて洗い出してから撤去する）。

### D6. summary の3表は宣言的集計（ADR-0011「単一キューブ＋宣言的集計定義」の最初の実装）

重い全表集計（実測: 指標カタログ371ms・地点×指標499ms・種カタログ786ms）だけを
事前計算する。ほかの問い合わせは問い合わせ時に計算する（実測15〜70ms、
`docs/plans/V2_SERVING.md` §8）。

`aggregations/serving.yaml`（新設予定、宣言）→ `scripts/b13_build_summary.py`
（新設予定）→ `summary_variable_catalog`/`summary_place_variable`/`summary_taxon_catalog`
（表名は仮）の3表。**キューブの再集計だけを行い、L2（`observation`/`occurrence`）を
読まない**——ADR-0001 の「D1 は再構築可能な配信キャッシュ」原則を summary 表にも
適用する。`scripts/migrate/common.py` の `record_stage_fingerprint`/
`assert_stage_fingerprint_fresh` と同じ段階間の指紋機構に乗せる（ADR-0027 層4）。

ADR-0011 は依然「状態: 提案中（宣言的集計定義〔YAML〕が未実装のため）」のままだが、
本 ADR の実装（b13・`aggregations/serving.yaml`）が完了すれば ADR-0011 の決定の中核
（33テーブルの代わりに宣言的集計定義でキューブを再集計する）が初めて実装されたことになる
——ADR-0011 の状態欄の更新は、実装・機械検証が済んだ時点（`docs/plans/V2_SERVING.md`
PR-2以降）で行う（本 ADR の対象外）。

### D7. L2 は D1 に入れない

ADR-0001 の原則をあらためて明文化する。`observation`/`occurrence`/`occurrence_place`
は Parquet 相当の中間生成物（`data/db/v2.sqlite`）に留め、D1 にはロードしない。
`run_sql`（`web/src/lib/ai/tools.ts`）・`describe_schema` が対象にできるのは D1 に
実際に載っている表（キューブ・レジストリ・summary・残す原本表）だけになる。

## 根拠（却下した代替案）

- **v1 形の射影を D1 に入れる（#28 案1）**: 却下（オーナー決定）。案1は「アーキテクチャの
  きれいさ」より「画面の書き換えの少なさ」を優先する案で、33表という「画面の形をした
  テーブル」（ADR README §1(a) の診断）をそのまま配信に残す。ADR-0011 の目的
  （集計軸を足してもテーブルが増えない）を達成できない。
- **合成データを配信時にフィルタする（ファクト構築時には残す）**: 却下。ファクト段階で
  除けば、キューブ・summary・D1 のどの段階でもフィルタし忘れが起きない。配信時フィルタは
  「新しい API を1つ足すたびにフィルタ条件を書き写す」という、まさに ADR README が診断した
  「画面ごとに個別対応が増える」パターンを再導入する。
- **`half_lod` を既定の代入方式として保存する**: 却下。ADR-0009 決定4が既に「妥当な既定
  として黙って適用してよいものではない」と判断済みで、本 ADR はその判断を変えない
  （式で導出できる値をわざわざ列として持つ理由も無い）。

## 影響

- **良い**: D1 の中身が「L3（配信キャッシュ）」という単一の性格に揃う。生ファクト・
  派生33表・書き込み系ログが混在する現行の構成（ADR README §1(e) が指摘した「テーブル数の
  記録自体がずれている」原因の一つ）が解消される。合成データが本番に一切出ないことを、
  「配信時に隠す」ではなく「そもそも作らない」で保証できる。
- **コスト**: `run_sql`/`describe_schema`（AI アシスタント経由の任意 SQL・スキーマ照会）が
  触れる範囲が D1 の実表に絞られる——生ファクトに対する自由な調査ができなくなる
  （`data/db/v2.sqlite` を直接見る手元の調査は引き続き可能）。
- **リスク**: `not_detected` の `value_zero` 例外を PR-6 まで残すことで、v1 撤去後も
  ADR-0009 決定4の「時限的な例外」が一定期間残り続ける。撤去を先送りする判断が「先送り
  したまま忘れられる」リスクはある——`docs/plans/V2_SERVING.md` の閉じる条件に PR-6 を
  含めていない（PR-6 は「任意」）ため、実施時期はオーナー判断に委ねられたままになる。

## 検討した代替案

- **観測値と生物出現で異なる索引戦略にする（`observation_agg` は複合索引を1本だけ、
  `occurrence_agg` は3本）**: 却下。両キューブとも「ある軸で絞ってから期間で範囲検索する」
  という同じアクセスパターンを問い合わせ層が使うため、対称に2本ずつ張るほうが
  `web/src/lib/cube/` の実装が単純になる。
- **summary 表を持たず、全問い合わせをキューブへの直クエリにする**: 却下。実測で指標
  カタログ・地点×指標・種カタログの3種類だけが D1 のレイテンシ上許容できない
  （371〜786ms）。それ以外（15〜70ms）は事前計算の複雑さに見合わないため直クエリのままにする
  ——ADR-0011 が既に「事前計算しなかった軸は問い合わせ時の計算に任せる」としている方針を
  そのまま踏襲する。

## 状態

提案中（オーナー承認待ち）。実装は `docs/plans/V2_SERVING.md` PR-0（`schema-cube.ts`・
`schema-registry.ts` の追加）・PR-2/PR-3b（imputation の切り替え）・PR-4（合成データ
画面の撤去）・PR-5（v1 表の DROP）・PR-6（`not_detected` 例外の撤去、任意）に分かれて進む。
