# Phase B 突合ゲート — v1 派生テーブルの再現性を機械で判定する

対象: ADR-0016 の Phase B / 状態: **実データで11テーブル（`meas_daily`/`meas_month`/`meas_year`/
`meas_clim`/`site_var`/`var_catalog`/`sensor_daily`/`rain_daily`/`sensor_hour_month`/`zone_year`/
`zone_clim`）を通した（`phase-b/fact-slice` + `phase-b/meas-remainder` + `phase-b/sensor-slice`
+ `phase-b/zone-slice`。部分ゲート＝33テーブル中11テーブルだけの合格で、全体の合格ではない。
前6テーブルは宣言済み差分のみで一致、センサー由来の3テーブルとゾーン由来の2テーブルは
宣言済み差分0で完全一致）**。続けて `phase-b/occurrence-l2` + `phase-b/occurrence-cube`
（O-1a/O-1b。`occurrence` を入力に生物系10テーブル `org_norm`/`org_group_year`/`effort_year`/
`species2`/`species_year2`/`mesh_year`/`mesh_all`/`mesh_species`/`species_mesh_year`/
`species_month` を通した。一致8・宣言済み差分のみ2——`org_norm`/`species2` の `cls` 列
1行だけ。§6参照）。`phase-b/place-attributes`（P-1a、`scripts/b11_project_place_v1.py`。
`observation`/`occurrence` を経由しない別枠——§9参照）で `watershed_meta` を通した
（一致1、宣言済み差分0で完全一致）。加えて `phase-b/documents`（P-3、
`scripts/b10_project_documents_v1.py`。`observation`/`occurrence` を経由しない別枠——
`docs/plans/PHASE_B_DOCUMENTS.md` 参照）で `doc_series`/`doc_series_meta`/
`quality_monthly` の3テーブルを実データで通した（宣言済み差分0で完全一致）。
`phase-b/occurrence-watershed`（O-2a、`scripts/b09_build_occurrence_place.py` で
記録×流域の直接解決 `occurrence_place` を作り、`scripts/b08_project_occurrence_v1.py`
に `org_watershed_year`/`org_watershed` を追加——§10参照）で流域2表を実データで通した
（一致2、宣言済み差分0で完全一致）。`phase-b/taxon-assessment`（P-2、
`scripts/registry/build_taxon_assessment.py` で `taxon_assessment` を新設し、
`scripts/b12_project_taxon_v1.py` に `redlist_map`/`redlist_change` を、
`scripts/b08_project_occurrence_v1.py` に `ias_species` を追加——
`docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照）で taxon/レッドリスト系3表を
実データで通した（`redlist_map`/`redlist_change`: 一致2、宣言済み差分0。
`ias_species` を含む13表の突合: 一致11、宣言済み差分のみ2〔既存の `org_norm`/
`species2` の `cls` 1行——§6参照〕、不一致0）。`phase-b/landuse`（P-1b、
`scripts/b03_build_observation.py` に `_ingest_landuse` を追加し、既存の
`v1_projection.sqlite` に `landuse_watershed`/`landuse_change` の2表を足した
（`b04`/観測系9表は無変更）——§11参照）で土地利用2表を実データで通した
（一致2、宣言済み差分0で完全一致。`--tolerance` は使わず一致した）。
`phase-b/rollup-and-gate`（P-1a の続き、`scripts/b11_project_place_v1.py` に
`watershed_rollup`——D10型の結合射影、4つの射影出力〔`watershed_meta`・
`org_watershed`・`site_var`・`landuse_watershed`〕を結合するだけでキューブの
セルにはしない——を追加）で最後の1テーブルを実データで通した（一致1、宣言済み
差分0で完全一致。§12参照）。あわせて、5つに分かれていたゲート（candidate
ファイルごとの個別実行）を `scripts/b02_run_all_gates.py` + `scripts/reconcile/
projection_manifest.yaml` で統合し、**33テーブルすべてを1コマンドで突き合わせられる
ようになった**（§12）。
**33テーブル全てが揃い、統合ゲートで全体の合格を1コマンドで確認できる
（一致25 / 宣言済み差分のみ8 / 不一致0 / 対象外0、終了コード0）**
作成: 2026-09-07 / 更新: 2026-09-24

**このドキュメントが説明するのはゲートの仕組みと、実データで実行した結果（§6・宣言済み差分の節）。
`observation`/`occurrence` の作成とキューブ本体の設計・実測は
[docs/plans/PHASE_B_FACT_SLICE.md](PHASE_B_FACT_SLICE.md) に、ADR-0009 の検閲値マッピングの
実装は `scripts/migrate/censoring.py` に、それぞれ詳細を譲る。**

## 1. なぜ「再現性」を受け入れ基準にするのか

[docs/adr/0016-migration-plan.md](../adr/0016-migration-plan.md) から引用する。

> **受け入れ基準: `imputation='zero'` の系列で v1 の派生テーブルの値が再現できること。**
> これは「v1 が正しい」という意味ではなく、**移行の誤りと意図的な変更を分離する**ため。
> 再現を確認したうえで `imputation` を `zero`/`lod` 併記に切り替える（ADR-0009）。
> 行数・件数の突合レポートを CI の成果物にする（v1 テーブル別の行数差・値差の分布）。

および:

> Phase B で v1 が再現できない箇所が出たら、**それは v1 のバグの発見**でもある。
> 再現できない理由を1件ずつ記録する（黙って v2 の値を正とみなさない）。

`web/scripts/build-derived.mjs` は `AVG(value)` で検閲行（定量下限未満75,689行・
ND 1,067行）の `value=0` を平均に含めており、現行の平均は下方に偏っている
（[ADR-0009](../adr/0009-censored-values.md)）。ADR-0009 の決定（検閲行の
`value_num` を `NULL` にする）を先に適用すると、水質グラフの数値が一斉に動く。
その変化が「移行のバグ」なのか「意図した是正」なのかを区別する手段が無いまま
Phase B を進めると、レビューが成立しない。

そこで、**先に `imputation='zero'`（v1 と同じ 0 埋め）で v1 の派生テーブルの値を
1件残らず再現できることを確認してから**、`imputation` を `zero`/`lod` 併記に
切り替える。この文書が説明するのは、その「再現できること」を人手ではなく
機械で判定する仕組み（Phase A の `scripts/r01_build_registry.py` /
`scripts/r02_resolution_report.py` と同じ、テストファーストのパターン）。

## 2. 構成

| ファイル | 役割 |
|---|---|
| `scripts/b01_derived_baseline.py` | `data/db/derived.sqlite`（v1、読み取り専用）の33テーブルを指紋化し、`reports/derived_baseline.json`（コミット対象）と `reports/derived_baseline.md` を書く |
| `scripts/b02_derived_compare.py` | ベースラインと候補（v2 のキューブから射影した、v1 派生テーブルと同じ形のデータ）を突き合わせ、`reports/derived_reconciliation.md` を書く。差があれば非0で終了する |
| `scripts/reconcile/common.py` | キー列の自動導出・指紋計算。b01 と b02 が同じ実装を共有する |
| `scripts/reconcile/datasource.py` | 候補側（および完全モードのベースライン実データ側）を sqlite / JSON のどちらでも同じインタフェースで読む薄いラッパ |
| `scripts/reconcile/derived_keys.yaml` | 自動導出できないテーブルだけの宣言的キー（現時点で空。§3参照） |
| `scripts/reconcile/adr0011_destinations.yaml` | ADR-0011「33テーブルの行き先」表をデータとして持つ（`derived_baseline.md` が参照する） |
| `scripts/tests/` | pytest。フィクスチャ sqlite だけで完結し、本物の `data/db/*.sqlite` を必要としない |

## 3. キー列の自動導出

各派生テーブルは `(場所, [分類群], 指標, 期間, 粒度) -> 統計量`
（[ADR-0011](../adr/0011-aggregation-cube.md)）の形をしている。`derive_key()`
（`scripts/reconcile/common.py`）はテーブルごとの特殊分岐を書かずに、次の順で
一意なキー列を決める。

0. `PRAGMA table_info` に `PRIMARY KEY` 宣言があれば、それを使う（SQLite が
   挿入時点で一意性を保証済み。assert で再確認だけする）。
1. `derived_keys.yaml` に宣言があれば、それを使う（assert で一意性を確認する。
   宣言だからといって検証を省かない）。
2. **[探索A]** 「宣言型を持つ列」だけの部分集合を、列数が小さい順に試す。
   `CREATE TABLE ... AS SELECT` では、集計関数（`AVG`/`SUM`/`COUNT`）の結果は
   宣言型が消える一方、`CAST(... AS INT)` で明示的に型を付けた列（年・月など）は
   型が残る。この SQLite の実装挙動と、「次元列を先に・集計列を後に書く」という
   このリポジトリの列順の慣習を組み合わせると、探索順を「型宣言あり→なし」に
   するだけで、集計値（`avg` や `n` 等）が誤ってキーに紛れ込む事故を避けられる。
3. **[探索B]** 探索Aで見つからなければ、探索Aの対象列を全部含めた上で、
   宣言型を持たない列を1個ずつ増やして試す。
4. 2・3のどちらでも見つからなければ **例外を投げて止まる**（黙って全列を
   キーにしない）。`derived_keys.yaml` に宣言を追記して解決する
   （「なぜ自動で決まらないか」を1行のコメントで残すこと）。

**実測**: `data/db/derived.sqlite` の33テーブルは、すべて探索A・Bの範囲で
自動導出できた（`pk` 2件・`auto` 31件・`declared` 0件。詳細は
`reports/derived_baseline.md` の「キーの由来」表）。`derived_keys.yaml` に
実エントリが無いのは想定どおりで、今後テーブルが増えて自動導出が失敗した
ときのための宣言的な逃げ道として置いてある（`scripts/tests/test_common.py` の
`test_derive_key_raises_when_no_key_exists_and_no_override` が、その失敗経路
自体は正しく動くことを確認している）。

素朴な「distinct 件数が多い列から貪欲に足す」方式は却下した。実測で、
`sensor_hour_month` のキーに集計列 `avg` が、`zone_clim` では次元列 `zone` が
抜けて集計列 `n` が紛れ込んだ（どちらも「たまたま現在のデータでは一意になる」
だけの誤ったキー）。探索A→Bの2段階探索ではどちらも起きない。

## 4. 使い方

```sh
# 1. v1 のベースライン指紋を作る（data/db/derived.sqlite が要る。原本のある環境のみ）
.venv/bin/python3 scripts/b01_derived_baseline.py
git add reports/derived_baseline.json reports/derived_baseline.md
git commit -m "..."

# 2. v2 のキューブができたら、v1 の派生テーブル相当を射影したもの（sqlite か JSON）と突き合わせる
.venv/bin/python3 scripts/b02_derived_compare.py --candidate path/to/projection.sqlite
# 終了コードが非0の間は、意図的な変更（ADR-0009 の検閲値修正等）を先に進めない。
```

`b02` は候補側を **sqlite ファイルでも JSON でも**受け付ける
（`scripts/reconcile/datasource.py`。拡張子で自動判定）。JSON の形式は

```json
{ "<table_name>": { "columns": ["col_a", ...], "rows": [[v_a, ...], ...] } }
```

キューブがまだ無いいま、この柔軟さによって「射影スクリプトの出力形式を先に
決めなくてもハーネスをレビューできる」ようにしてある。

### `--tables` で対象を絞る（部分ゲート）

```sh
# meas_daily / meas_month / meas_year の3テーブルだけを対象にする
.venv/bin/python3 scripts/b02_derived_compare.py \
  --candidate path/to/projection.sqlite \
  --tables meas_daily,meas_month,meas_year
```

33テーブルを一度に全部揃えて通そうとすると、v2 側の設計・実装が全部揃うまでこのゲート自体が
一度も緑にならない。そこで最初の縦に薄い1本として `measurements` → `observation` →
`meas_daily`/`meas_month`/`meas_year` だけを先に通す。検閲値（定量下限未満）の0埋めの再現・
日付書式の混在・`place` 解決の失敗のような、このハーネスが本来検出すべき食い違いは、
どれもこの3テーブルの縦の流れの中で一通り出る（残り30テーブルを待つ理由が無い）。

`--tables` を省略すると従来通りベースラインの全テーブルが対象になる（このとき出力は
1バイトも変わらない）。指定した名前が `derived_baseline.json` に無ければ、その名前を挙げて
即座に非0で終了する（黙って無視すると「タイポで0件を突合して緑」という、このゲートの
存在意義そのものが崩れる最悪の失敗になるため）。

部分指定で通った緑を「全体が緑」と読み違えないよう、`reports/derived_reconciliation.md` の
冒頭と標準出力の両方に「部分ゲート」である旨・対象テーブル・対象外の件数を明記する
（全テーブルを対象にした場合はこの文言を出さない）。

### なぜ b02 は2種類の「ベースライン」入力を持つのか（設計判断）

`reports/derived_baseline.json` は**行データを持たない**（数百KB〜数MBに収める
という要件のため、各テーブルは行数・キー・数値集計・1個の内容ハッシュだけを
持つ）。そのため、`b02` が要求する「共通キーの行について数値列ごとの差の分布
（max/p50/p95）」「キー集合の差の先頭N件の実例」のような**行レベルの内訳**は、
JSON 単体からは絶対に計算できない（そもそもどの行がベースライン側に存在したか
という情報が JSON に無い）。

そこで `b02_derived_compare.py` は次の2つを別の入力として受け取る。

- `--baseline-json`（既定 `reports/derived_baseline.json`）: コミットされた
  指紋。**行レベルの実データが無くても存在する**ため、CI はこれの存在だけは
  常に検証できる。
- `--baseline-data`（省略時、`data/db/derived.sqlite` があれば自動的に使う）:
  ベースライン側の実データ。sqlite でも JSON でもよい。**これがある環境でだけ**、
  行レベルの内訳が出せる（**完全モード**）。無ければ、行数・内容ハッシュ・
  数値集計の一致だけを見る**縮退モード**になる（§5）。

`--baseline-data` を渡した場合、`b02` はまずそのデータから指紋を再計算し、
`--baseline-json` の記録と一致するか検証する（**鮮度チェック**）。
食い違えば「`b01` を再実行してコミットし忘れている」ことを意味するので、
その旨をレポートに書いて非0で終了する（黙って古い記録のまま突合を進めない）。

**この設計判断は呼び出し元の確認を経ていない。** タスク文の「入力は
sqlite/JSON を受ける汎用インタフェースにする」は候補側について明示していたが、
ベースライン側を「JSONの指紋」と「実データ」の2本に分けるかどうかは
サイズ制約（reports/derived_baseline.json は行を持てない）から導いた設計判断。
別解として「`b02` は常に実データ2つ（ベースライン・候補）だけを取り、
`derived_baseline.json` は突合に使わず b01 の実行記録としてのみ扱う」も
あり得るが、その場合 CI が「JSONの鮮度（存在確認以上のこと）」を一切見られなく
なる。今回は「JSONは常設の軽い検証、実データは重い検証」の二層にした。

### 候補側の余分なテーブル・列

候補（v2 のキューブから射影したもの）が v1 の33テーブルに無い**テーブル**を
余分に持っていても、`b02` はそれを不一致に数えない（レポートには参考情報として
出す）。このゲートの合格条件は「v1 の33テーブルを再現できたか」であって、
候補が新しい軸を余分に持つこと自体は再現の失敗ではないため。一方、**比較対象の
テーブルの中**で列が過不足していれば、そのテーブルは不一致として扱う。
行同士の突合が前提にしている「ベースラインと候補が同じ列構成である」が
崩れているので、行の内容を比べても意味がないため。

### テーブル単位の並列化は採らない（判断）

`b01`/`b02` はテーブルごとに独立した処理なので、`multiprocessing` で
33テーブルを並列化すれば実行時間の理論上限は最も重いテーブル1本
（`org_norm`、816,856行）の処理時間まで縮む、という指摘は測定として妥当。
それでも**採らない**。ベースライン作成・突合は滅多に走らない操作で、
実利は1分程度しかない一方、プロセスプール・ワーカーごとの sqlite 接続・
エラー伝播・決定論（2回実行のバイト一致）の再証明という複雑さを
**受け入れゲートそのもの**に持ち込む割に合わない。`b02` の完全モードは
ベースラインの鮮度チェックを `_compare_full` のマージ結合に畳み込んだ
（以前は33テーブル全体を専用の事前スキャンで1回読み、直後に同じベースラインを
比較のためもう1回読んでいた）ことで、実データ（derived.sqlite,
「値変更1・行削除1・列追加1・テーブル追加1」を仕込んだ候補との突合）で
4m2.6s → 3m34.9s に短縮した。ディスクキャッシュの状態に左右されるため
（`org_norm` 1テーブルだけで97秒前後かかり、これが二重に読まれなくなった
分が主な効果）パーセンテージは目安に留めるが、方向としては期待どおりで、
単一プロセスのままの最適化で当面十分と判断した。

## 5. CI の限界（正直に書く）

原本（`data/db/ryuiki.sqlite` / `cells.sqlite` / `derived.sqlite`、合計 14GB）は
git に置けない。Issue #29「縮小サンプル＋実行証明」で、この制約の中で「33表の
突合が壊れたときに CI が気づける」ようにする方式を決めた:**(A) 固定の縮小
サンプルをリポジトリにコミットし、CI はそのサンプルで v1・v2 の両方を毎回
回して突き合わせる（`sample-gate` ジョブ）**。**(B) 全量のゲートは手元で回し、
結果の証明ファイル（`reports/full_gate_proof.json`）をコミットする。CI は、
その証明が今のコードに対応しているかを確かめる（`full-gate-proof-check`
ジョブ）**。以下、この2ジョブが実際に保証すること・しないことを正直に書く。

### 5.1 `sample-gate`（A）が保証すること

- **CI が保証すること**:
  1. `data/sample/`（`scripts/s01_build_sample.py` が原本から切り出した、
     テキストでコミット済みの縮小サンプル。`data/sample/coverage.yaml` の
     宣言に基づく）を使い捨ての checkout に展開し、v1
     （`web/scripts/build-derived.mjs`・`build-geo.mjs`・`build-biota.mjs`）と
     v2（`scripts/r01_build_registry.py`・`scripts/b03_build_observation.py`〜
     `scripts/b12_project_taxon_v1.py`）の両方をゼロから構築できること。
  2. サンプル規模で構築した v1・v2 が、`scripts/b02_run_all_gates.py`
     （宣言済み差分は**正本の `scripts/reconcile/expected_diffs.yaml` を
     そのまま使う**。サンプル専用の免除ファイルは持たない）で33表とも
     「一致」または「宣言済み差分のみ」になり、不一致・対象外が無いこと。
     属 Sirosporium の class タイブレーク（org_norm/species2、§6参照）も
     サンプル規模で再現する——`data/sample/coverage.yaml` の
     `sirosporium_genus_full_records` 閉包は、投票元（属の class 多数決に
     実際に使われる3レコード。web/scripts/build-biota.mjs の `gc` CTE・
     `scripts/registry/build_taxon.py` の `_genus(_binom(scientific_name))`
     ——どちらも `organism_records.genus` 列ではなく学名の binom 先頭語で
     属を決める）を漏れなく含めることで実現した（初版は `genus` 列だけで
     選んでおり、学名の binom 先頭語が "Sirosporium" でも own genus 列が
     別属（`Clasterosporium`/`Helicoceras`）の2レコードを取りこぼしていた
     ——コードレビュー指摘で発覚・修正）。
  3. **空振りしていないこと**を数値で確かめる（一致+宣言済み差分のみ=33、
     不一致=0、対象外=0、適用した宣言済み差分=20件——正本と同じ件数。
     この数値が変われば、v1 側のスクリプトを触ったことが
     `data/sample/derived_baseline.json`/`.md` の差分として、v2 側が
     ずれたことが33表の突合結果として、どちらも CI に現れる）。
  4. `data/sample/declaration_counts.yaml`・`derived_keys.yaml`・
     `derived_baseline.json`/`.md` が、コミット済みのサンプル本体
     （`data/sample/ryuiki/*.sql` 等）とパイプラインのコードから実際に
     再現できること（`scripts/s03_verify_sample_artifacts.py` で作り直し、
     `git diff --exit-code` で比べる。原本を使わない——材料化済みのサンプル
     そのものと `reports/derived_baseline.json`〔全量の33表のキー、正本〕
     だけから計算できる）。
  5. **集計が空振りしていないこと**を機械で確かめる
     （`scripts/tests/test_sample_aggregation_is_not_degenerate.py`。
     `pytest`、原本不要——コミット済みの `derived_baseline.json` を読むだけ）。
     `n`/`n_raw`/`n_hours`（集計対象の生レコード数を意味する列。`species_n`/
     `mesh_n`/`n_sites` のような distinct 系の別次元件数は対象外）を持つ表
     すべてで最大値が2以上であることを確認する——1以下なら「1件をそのまま
     写しただけ」で、v1・v2 の集計方法の違いを一度も試していないことになる。
     初版は sensor_timeseries が70行・organism_records が217行しか無く、
     `sensor_hour_month`/`species_month` 等が事実上1件コピーになっていた
     （コードレビュー指摘で発覚）。`coverage.yaml` に「出典ごとに1地点の
     丸1か月分（時間値は約720〜3,700行、日値は約450〜550行、月値は約1年分）」
     と「密なメッシュ×年クラスタ・81年分の記録を持つ種」の predicate を足し、
     sensor_timeseries 6,770行・organism_records 2,519行に増やして解消した。
- **CI ができないこと（サンプルの限界）**:
  - **サンプルに無い行・癖・出典への挙動は確認できない。**
    `data/sample/coverage.yaml` が宣言する範囲（定量下限の各表記・厚木の
    4桁の測定日・地盤沈下の r5/r6 重複・負の値・センサーの時刻帯・occurrence
    の12形・流域外の座標・年をまたぐ区間・除外7種と外来種・レッドリスト種・
    同じ日の重複・全 source_id）だけが対象で、それ以外の未知の癖がサンプルに
    無ければ検出しようが無い。
  - **サンプルの件数の宣言（`declaration_counts.yaml`）が原本の件数を語ると
    誤読しないこと。** これはサンプル規模で実測した値であり、原本
    （`scripts/migrate/*.yaml` 等の正本）の `expected_row_count` とは別物。
  - **HEAD の全量で v1 と v2 が一致することは、`sample-gate` だけでは
    分からない。** サンプルで一致していても、サンプルに無い行の集計で
    全量が食い違っている可能性はゼロにならない（全量の合否は §5.2 の B、
    すなわち手元での実行に依存する）。

### 5.2 `full-gate-proof-check`（B）が保証すること

- **CI が保証すること**: `reports/full_gate_proof.json`（原本のある手元で
  `scripts/b00_run_full_gate.py` を実行して作る、コミット済みの証明）が
  記録するパイプラインのパス（`scripts/b0*.py`・`scripts/b1*.py`・
  `scripts/r01_build_registry.py`・`scripts/registry/`・`scripts/migrate/`・
  `scripts/reconcile/`・`registry/`・`reports/derived_baseline.json`・
  `web/scripts/build-{derived,biota,geo}.mjs`・`requirements.txt`・
  `web/package.json`・`web/pnpm-lock.yaml`）の git tree/blob ハッシュが、
  **今の HEAD** で計算し直しても1つ残らず一致すること。1つでも食い違えば、
  「証明を取ったときと今のコードが違う」ことが分かり、CI が非0で落ちる
  （案内文が `scripts/b00_run_full_gate.py` の再実行を促す）。あわせて、
  `data/sample/manifest.json` の原本の sha256（`ryuiki.sqlite`/`cells.sqlite`）
  が証明の原本の sha256 と一致すること（サンプルと全量の証明が同じ原本の
  スナップショットに由来することの確認）も見る。
- **CI ができないこと（証明の限界。正直に書く）**:
  - **証明が本物であることは確かめられない。** `reports/full_gate_proof.json`
    は手で書ける値でしかない——CI が確認できるのは「証明に書かれたパスの
    ハッシュが今の HEAD と一致するか」という一貫性だけで、「本当にそのハッシュの
    コードを回して33表が緑になったか」は申告を信じるしかない
    （手元で実際に回したことは、レビューでの信頼に依存する）。
  - **B は「過去に回した」という申告であり、CI がその時点の真偽を今
    確かめ直すことはできない。** 原本自体（`ryuiki.sqlite`/`cells.sqlite`）が
    CI に無いため、CI 自身が全量の33表を再現することは今回も引き続きできない。
  - **原本のスナップショットが変わっていないことは、sha256 の記録以上には
    確かめられない。** 原本を差し替えても、証明を取り直さない限り検出できない
    （sha256 自体は記録されるので、証明を取り直したときには気づける）。

### 5.3 運用

- **パイプラインのパス（§5.2 の一覧）に触る PR は、手元で
  `scripts/b00_run_full_gate.py` を回して証明を更新する必要がある。**
  原本（`ryuiki.sqlite` 828MB・`cells.sqlite` 42MB）を持たない人はパイプラインの
  PR をマージできない——この制約自体は Issue #29 が解決しようとした問題では
  ない（原本を持たない人でも「壊れていないか」を CI で機械的に確認できる
  ようにするのが `sample-gate` の役目で、`full-gate-proof-check` は「証明が
  古くないか」だけを見る）。
- サンプル本体（`data/sample/`）の展開スクリプト（`scripts/s02_materialize_sample.py`）は
  **手元の本物のチェックアウト・worktree では絶対に実行しない**（CLAUDE.md
  「worktree の運用」。安全装置——展開先に既存ファイルがあれば拒否・
  `GITHUB_ACTIONS` か `--i-am-in-a-throwaway-clone` が無ければ拒否——があっても、
  再生成できない原本を上書きする経路を自分から開かない）。手元で試すときは
  一時ディレクトリへの `git clone` で行う。
- サンプル自体を作り直す・広げる（`data/sample/coverage.yaml` に述語を足す等）
  ときは `scripts/s01_build_sample.py` を原本のある環境（worktree に原本を
  1ファイルずつ symlink した状態）で実行し、`data/sample/` 配下を丸ごと
  コミットし直す。設計・実測（サンプルのサイズ・CI のジョブの所要時間・
  宣言済み差分の内訳）は本ドキュメントの付録ではなく、Issue #29 の PR 本文に
  実測値として書く（このドキュメントは仕組みの説明に留める）。

## 6. 再現できない箇所が出たときの扱い

ADR-0016 の言葉を借りれば、**「それは v1 のバグの発見でもある」**。したがって:

- `b02_derived_compare.py --candidate ...` が非0で終了し、`reports/derived_reconciliation.md`
  に不一致テーブルが出たら、**黙って v2（候補）の値を正とみなさない**。
- 再現できない理由を**1件ずつ**、このファイルの「## 再現できなかった箇所の記録」
  節（下記の表）に追記する。理由が分かるまで、そのテーブルに依存する画面・
  AIツールの `imputation` 切り替えを進めない。
- 記録すべき内容: テーブル名 / 発見日 / 症状（行数差・値差の内容）/ 原因
  （v1側のバグか、v2の移行ミスか、意図的な変更か）/ 対応（v1を正として
  v2を直す・意図的な変更としてADRに残す・v1のバグとして別途起票する）。

### 再現できなかった箇所の記録

`phase-b/fact-slice`（`scripts/b03_build_observation.py`/`b04_build_cube.py`/`b05_project_v1.py`）
で3テーブルを実データで突合した結果、1つの原因から生じた食い違いが見つかった。原因が判明し、
v1 側のバグだと確定できたため、`scripts/reconcile/expected_diffs.yaml` にキー単位で宣言し
（§7参照）、突合結果を「宣言済み差分のみ」にした（`reports/derived_reconciliation.md` で確認、
終了コード0）。`phase-b/meas-remainder`（同じ3スクリプトの拡張。`b05` に `meas_clim`/`site_var`/
`var_catalog` を追加しただけで `b03`/`b04` は無変更）で残り3テーブルを実データで突合したところ、
**新しい原因は1つも見つからず**、同じ12行が3テーブルの集計元（`meas_clim` は `meas_daily`、
`site_var`/`var_catalog` は `meas_year`）を通じて機械的に波及した差分だけだった
（`--no-expected-diffs` で実測。2026-09-15）。

6テーブルまとめて1行にした——6テーブルとも**同じ1つの原因**（後述）から機械的に伝播した結果
であり、テーブルごとに6行書いても同じ説明を繰り返すだけになるため（「読みやすい方でよい、
理由を1行添える」という本ドキュメントの指示に対する判断）。テーブル別の内訳（件数・発見日）は
表の直下に書く（詳細は `scripts/reconcile/expected_diffs.yaml` の各テーブル節の直前コメント参照。
二重に書かない）。

| テーブル | 発見日 | 症状 | 原因 | 対応 |
|---|---|---|---|---|
| 計18キー（内訳は直下） | 2026-09-08 〜 2026-09-15（内訳は直下） | `atsugi_river_water_quality__中津川` の `浮遊物質量 SS`・`value_raw='1未満'` の12行に由来する18キーで、行の新規出現（`meas_daily`/`meas_month`）と平均・最小値・件数の変化（`meas_year`/`meas_clim`/`site_var`/`var_catalog`）が起きる | **v1 側のバグ**: `web/scripts/build-derived.mjs` は `value_raw LIKE '<%'`（ASCII の `<`）しか検閲として扱わず、日本語表記の `未満` をパースできないため `value` が `NULL` のまま集計（`AVG(value)`）から静かに落としていた。v2 は `censoring.py` が `未満` も `below_lod` として拾い、`imputation='zero'` で 0.0 を代入して集計に含める。`meas_clim`/`site_var`/`var_catalog` はそれぞれ `meas_daily`/`meas_year` を集計元にするだけなので、同じ12行の増分がそのまま波及する | `scripts/reconcile/expected_diffs.yaml` にキーを1件ずつ宣言（`kind`/`reason`/`found_on`/`record` 付き）。v1 側の是正（`build-derived.mjs` の検閲判定を直す）は本ドキュメントのスコープ外、別途起票する |

テーブル別の内訳:

- `meas_daily`: 2キー（2026-09-08）
- `meas_month`: 2キー（2026-09-08）
- `meas_year`: 9キー（2026-09-08）
- `meas_clim`: 2キー（2026-09-15）
- `site_var`: 2キー（2026-09-15）
- `var_catalog`: 1キー（2026-09-15）

続く `phase-b/sensor-slice`（`sensor_timeseries` を入力に追加し `sensor_daily`/`rain_daily`/
`sensor_hour_month` の3テーブルを通した）でも、**新しく再現できなかった箇所は無い**——
この3テーブルは宣言済み差分0で v1 と完全一致した（`reports/derived_reconciliation.md`
「一致したテーブル」）。

続く `phase-b/zone-slice`（`place_relation` 経由でゾーンに束ねた `zone_year`/`zone_clim`
の2テーブルを通した）でも、**新しく再現できなかった箇所は無い**——この2テーブルも
宣言済み差分0で v1 と完全一致した（`reports/derived_reconciliation.md` 2026-09-22実測、
「一致したテーブル」）。§6の表にある `atsugi_river_water_quality__中津川` の `未満`
表記12行は、この site_id が `sites` テーブル本体に登録が無く `sites.zone` を持たない
（したがって `place_relation` にも辺が無い）ため、ゾーン系の2テーブルには波及しない
（実測で確認済み。`docs/plans/PHASE_B_FACT_SLICE.md` §11）。

ただし1点、このゲートが**見なくなった**経路があることを正直に書く。キューブ
（`observation_agg`）は毎時値を「区間の始まりの日付」で日次セルに積み上げるが、v1（および
`sensor_daily`/`rain_daily`/`sensor_hour_month` の射影）は「ラベルの日付」で日割りしており、
この2つは食い違う（ADR-0024 決定3。区間の境界をはみ出す集計）。射影（`b05`）はこの食い違いを
避けるため、hour-grain の系列だけキューブを経由せず L2（`observation`）から v1 のラベル日割りで
直接計算する——**キューブに実際には織り込まれている「正しい日割りへの意図的な変更」は、
射影がキューブを迂回しているぶん、この突合ゲートには一切現れない。**
代わりに `b05` の `verify_hourly_daily_rollup`（T6。`docs/plans/PHASE_B_FACT_SLICE.md` §9）が、
「キューブの日次セルの n」と「v1形の日割りから機械的に導ける期待値」が全日で一致することを
検証する。ゲートが直接確認できない差分を、宣言（`expected_diffs.yaml`）ではなく計算式による
機械検証に置き換えた形で、代わりに保証している。変更量そのものの実測は
`docs/plans/PHASE_B_FACT_SLICE.md` §10「キューブに既に織り込んだ意図的な変更」を参照。

続く `phase-b/occurrence-l2`（`organism_records` を入力に `occurrence` を作り、
`org_norm` 1テーブルを通した。O-1a）では、**1行1列だけ再現できない taxon が見つかった**。

| テーブル | 発見日 | 症状 | 原因 | 対応 |
|---|---|---|---|---|
| `org_norm` | 2026-09-22 | `gbif_kanagawa_occurrences__1829967465`（*Sirosporium celtidis*）の `cls` 列が v1 と食い違う（1行1列。他816,855行・他の全列は完全一致） | **v1・v2 どちらも「間違い」ではない、決定論性の実装差**: 属 *Sirosporium* の class 多数決が同数（Dothideomycetes と Sordariomycetes）で、v1（`web/scripts/build-biota.mjs` の `ROW_NUMBER() OVER (... ORDER BY COUNT(*) DESC)`、同数時の順序は SQLite の実装依存の暗黙順）は `Sordariomycetes` を選んでいたが、taxon レジストリ（`scripts/registry/build_taxon.py` の `_majority_vote()`）は明示的な決定論的タイブレーク（件数降順・同数なら値の昇順）で `Dothideomycetes` を選ぶ。`taxon_group`（菌類）はどちらの候補でも変わらないため、この食い違いは `cls` 列だけに留まる | `scripts/reconcile/expected_diffs.yaml` の `org_norm:` にキーを1件宣言（`kind: value_diff`, `columns: [cls]`）。v1 側の是正は不要（v1 のバグではなく、v1 が同数タイブレークの規則を持たなかっただけ） |

この1件は `docs/plans/PHASE_B_OCCURRENCE.md` §3「F2: 分類の補完」で Slice 0 の時点から
実測・記載済みだった食い違い（属単位の多数決が同数だった3属のうち、実際に
`org_norm` の値へ影響したのはこの1 taxon だけ）を、O-1a でゲートに通して
再確認したもの。新しい原因は無い。

続く `phase-b/occurrence-cube`（`occurrence` を入力にキューブ `occurrence_agg`（b07）を作り、
年キー8表（`org_group_year`/`effort_year`/`species2`/`species_year2`/`mesh_year`/`mesh_all`/
`mesh_species`/`species_mesh_year`）と `species_month` の計9テーブルを通した。O-1b）では、
**org_norm と全く同じ原因からもう1件だけ**再現できない列が見つかった。

| テーブル | 発見日 | 症状 | 原因 | 対応 |
|---|---|---|---|---|
| `species2` | 2026-09-22 | `binom='Sirosporium celtidis'` の `cls` 列が v1 と食い違う（1行1列。他23,617行・他の全列は完全一致） | `org_norm` の宣言と**同一の原因**（上の表参照。属 *Sirosporium* の class 多数決の同数タイブレークが taxon レジストリと v1 で異なる）。`species2.cls` は `MAX(taxon.class)`（binom ごと）なので、taxon 単位の食い違いがそのまま1行の食い違いとして波及する | `scripts/reconcile/expected_diffs.yaml` の `species2:` にキーを1件宣言（`kind: value_diff`, `columns: [cls]`） |

年キー8表のうち残り7表（`org_group_year`/`effort_year`/`species_year2`/`mesh_year`/`mesh_all`/
`mesh_species`/`species_mesh_year`）と `species_month` は、宣言なしで全数値列が完全一致した
（`--no-expected-diffs` で実測。`reports/derived_reconciliation.md` 2026-09-22実測、
「一致したテーブル」）。`b02 --tables org_norm,org_group_year,effort_year,species2,species_year2,
species_month,mesh_year,mesh_all,mesh_species,species_mesh_year` は終了コード0（宣言済み差分は
`org_norm`・`species2` の2件だけ）。

`phase-b/documents`（P-3。`scripts/b10_project_documents_v1.py`）は `doc_series`/
`doc_series_meta`/`quality_monthly` を通したが、**`observation`/`occurrence` を経由しない**
別枠であることに注意（実際の入力が `cells.sqlite`/`quality_transitions` であり、そもそも
`b03`〜`b05` の対象外）。v1 の SQL をそのまま再実行するだけなので `--no-expected-diffs` でも
差分0（宣言なし）で完全一致する。このゲートの性格（v1 表の持ち越しを確かめるだけで v2 の
変換の正しさは確かめない）は `docs/plans/PHASE_B_DOCUMENTS.md` 冒頭参照。

## 7. 宣言済み差分（`expected_diffs.yaml`）

ADR-0016 の受け入れ基準は「`imputation='zero'` の系列で v1 の派生テーブルの値が再現できること」
だが、Phase A/B の過程で「v1 側の既知のバグ」が見つかること自体は ADR-0016 §「注意」が
明記している想定内の事象である（「それは v1 のバグの発見でもある」）。これを**散文の記録
（本ドキュメント §6 の表）のままにせず、機械検証に変える**のがこの仕組みの目的。

### 運用

- 書けるのは**キーを1件ずつ列挙したもの**だけ。ワイルドカード・テーブル単位の免除は書けない
  （`scripts/reconcile/expected_diffs.yaml` の形式そのものがこれを強制する。テーブル名 →
  `[{key, kind, reason, found_on, record}, ...]` の配列で、`key` はベースラインのキー列と
  同じ順・同じ個数）。
- **`reason` に前後の数値を手で書かない。** `reason` は「なぜその差分が出るか」（v1 側の
  バグの中身と、それがどの集計にどう波及するか）を言葉で説明するだけに絞る。「n が
  10→12」「avg が 2.606629…→2.463542…」のような**前後の値は `reason` に書かず、
  `scripts/b02_derived_compare.py` が完全モードでその場で実測して**、レポートの
  「宣言済み差分（expected_diffs.yaml で適用したもの）」節に宣言ごとの「実測の前後の値」
  として出す（`value_diff` は食い違った列だけを「列名: ベースライン→候補（差 ...）」の
  形で、`row_only_in_candidate`/`row_only_in_baseline` はその側に実在した行の値を
  「列名=値」の形で。数値は `scripts/reconcile/common.format_number` で小数点以下6桁に
  揃える。一致した列は出さない）。**理由（/simplify 指摘を受けたオーナー決定）**: 手で
  計算して `reason` に書いた数値は、テーブルが増えるたびに同じやり方の手計算が積み上がる
  うえ、b02 はそれを検証しない——1文字書き間違えても誰も気づかない。実測をレポート側に
  出すようにすれば、前後の値は毎回のゲート実行で機械的に最新のものになる（縮退モードでは
  宣言そのものを適用できない＝実測できないため、この節は完全モードのときだけ出る）。
- `scripts/b02_derived_compare.py` は宣言を**信用せず**、次をすべて検証したうえでしか
  不一致から除かない（`_compare_full` / `main()`）:
  - 宣言のテーブル名が `derived_baseline.json` に無ければ非0で止まる。
  - `key` の要素数がそのテーブルのキー列数と違えば非0で止まる。
  - `kind` が `row_only_in_candidate`/`row_only_in_baseline`/`value_diff` のいずれでもなければ
    非0で止まる。
  - **宣言したキーが実際には差分になっていない（腐った宣言）→ 非0で止まる。** 免除が
    残り続けて他の退行を隠すのを防ぐための、この仕組みで一番重要な検証。
  - 宣言した `kind` と実際の差分の種類が食い違えば非0で止まる。
  - `value_diff` の宣言は `columns`（動くと期待する列名の集合。例:
    `[n, avg, min, n_censored]`）を必須にし、実際に食い違った列の集合と完全一致
    するかを検証する → 一致しなければ非0で止まる（`row_only_in_candidate`/
    `row_only_in_baseline` には不要）。`key`/`kind` だけでは、同じキーで宣言時に
    想定していなかった別の列まで動いても緑のまま通ってしまうため（数値そのものは
    引き続き書かせない。列名の集合だけを宣言させる）。
- **縮退モード（`--baseline-data` 無し・ベースライン実データ無し）では宣言を適用できない。**
  行レベルの差分を見られないので「宣言が実際に差分になっているか」を検証できないため、
  対象テーブルに宣言が1件でもあるのに縮退モードなら黙って無視せず非0で止まる（`main()`）。
- 状態表示は宣言で説明しきれたテーブルを「一致」ではなく「**宣言済み差分のみ**」にする
  （`STATUS_LABEL["declared_diffs_only"]`）。**終了コード（合否）には数えない**——
  `n_mismatch` の集計から除外される（`main()` の `n_mismatch = sum(... status not in
  ("match", "declared_diffs_only") ...)`）ため実質的に合格として扱われる。ただし表示だけは
  「一致」と区別することで、後から見た人が「v1とv2は完全に同じ値」と誤読しないようにする。
- **`expected_diffs.yaml` を変える PR は、ローカルの完全モードで得た「宣言済み差分」節の表を
  PR 本文に貼る。** `reports/derived_reconciliation.md` は `.gitignore` 済みで、CI も
  §5「CI の限界」の通り完全モードを走らせない（原本DBが無い）ため、PR のレビューでは
  実測の前後の値（`observed`。§「宣言済み差分」参照）がそのままでは見えない。レビュアーが
  「宣言した `columns`/`kind` が実際の差分と合っているか」を確認できるよう、レポートの
  「宣言済み差分（expected_diffs.yaml で適用したもの）」節の表をそのまま PR 本文に貼る。

### なぜ免除機構を受け入れゲートに入れてよいと判断したか、その危うさ（正直に書く）

**判断した理由**: 免除を許さないと、Phase A/B で見つかる v1 側のバグ（今回のように23.4%の
検閲値のうち日本語表記だけがパース漏れしていた、というような）が1件見つかるたびに、
v1 側を直すまで v2 のゲートが恒久的に赤いままになる。ADR-0016 は「移行の誤りと意図的な変更を
分離する」ことが目的であり、「v1 のバグを直すまで一切前進しない」ことは目的ではない。
散文の記録（本ドキュメント §6 のような表）だけに頼ると、宣言した差分が本当にその通りかを
毎回人間がレビューし直す必要があり、キー1件ずつの列挙という制約下で機械検証に変えることで、
「宣言と実際の差分が食い違っていないか」を毎回のCI実行で自動的に再確認できる。

**危うさ**: それでも免除は免除であり、**運用次第でゴミ箱になりうる**——書ける形式が
「キー1件ずつ」に制限されていても、宣言のエントリ数そのものが際限なく増えていけば、
実質的にはテーブル全体を免除しているのと変わらない状態になりうる。この仕組みは
「宣言したキーが本当にその通りの差分か」しか検証せず、「宣言が増えすぎていないか」
「宣言理由が的確か」は機械では判定できない、人間のレビューに依存したままの部分である。
現状は6テーブルで18キー（1つの原因）に留まっているが、この件数が増え続けるようなら、
免除ではなく v1/v2 双方の是正を優先すべき兆候として扱う。

## 8. やっていないこと（このPRのスコープ外）

- 残り3テーブル（ADR-0011「33テーブルの行き先」参照。当初の残り12テーブルのうち、
  `meas_clim`/`site_var`/`var_catalog` は `phase-b/meas-remainder`、`sensor_daily`/
  `rain_daily`/`sensor_hour_month` は `phase-b/sensor-slice`、`zone_year`/`zone_clim` は
  `phase-b/zone-slice`、`org_norm` は `phase-b/occurrence-l2`（O-1a）、年キー8表・
  `species_month` は `phase-b/occurrence-cube`（O-1b、`occurrence` を入力にする
  生物系10テーブルはこれで揃った）、`watershed_meta` は `phase-b/place-attributes`
  （P-1a、§9参照）、`doc_series`/`doc_series_meta`/`quality_monthly` は
  `phase-b/documents`（P-3）、`org_watershed`/`org_watershed_year` は
  `phase-b/occurrence-watershed`（O-2a、§10参照。生物系はこれで12テーブル全て
  揃った）、`redlist_map`/`redlist_change`/`ias_species` は
  `phase-b/taxon-assessment`（P-2、`docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照。
  taxon/レッドリスト系はこれで3テーブル全て揃った）、`landuse_watershed`/
  `landuse_change` は `phase-b/landuse`（P-1b、§11参照）で済んだ。残り1テーブル
  （`watershed_rollup`〔流域のロールアップ〕）は `phase-b/rollup-and-gate` で済んだ
  ——これで33テーブル全て揃った。§12参照）
- `imputation='lod'` 併記（ADR-0009 決定4。今回は `zero` のみ）
- 正準単位の併記（ADR-0023。方針は決定済みだが未実装）
- Parquet 化（ADR-0001）
- キューブのゾーンのロールアップセル（ADR-0011 の `roll_up_to`。使う側が現れたら作る。
  `zone_year`/`zone_clim` は v1形からの非加重射影であり、キューブのセルではない。
  `docs/plans/PHASE_B_FACT_SLICE.md` D11参照）
- `.github/workflows/` への `phase-b/fact-slice` の11テーブル部分ゲートの配線（CI ワークフロー
  自体は `phase-b/alias-source-key` で新設済みだが、`--tables` オプションでの実行はまだ
  ジョブに組み込まれていない）
- 同様に、5つの個別ゲート（`v1_projection.sqlite`/`v1_projection_occurrence.sqlite`/
  `v1_projection_documents.sqlite`/`v1_projection_place.sqlite`/
  `v1_projection_taxon.sqlite`、それぞれの `--tables ...` 実行）も、`phase-b/
  rollup-and-gate` で新設した統合ゲート（`scripts/b02_run_all_gates.py`、§12）も、
  どちらも `.github/workflows/` にはまだ配線されていない（原本DBが要るので、
  CI では今後もそのままでは動かない。実行できるのは原本のある環境だけ）。
  「テーブル名 → (射影スクリプト, candidate ファイル) の対応表を持って全ゲートを
  まとめて回す仕組み」自体は、2026-09-24 の `phase-b/rollup-and-gate` で作った
  （§12。以前この節に書いていた「1表のためには過剰」という判断は、`b1x` 系の
  射影スクリプトが5本・candidate ファイルが5つに増えた時点で `/simplify` 指摘
  どおり超えたと判断し、着手した）。ここに残っているのは CI ワークフローへの配線
  だけ。

## 9. `watershed_meta`（`phase-b/place-attributes`、P-1a）

`observation`/`occurrence`（キューブ）を経由しない `place` の属性（ADR-0011
「place の属性」カテゴリ）の最初の例。`scripts/b11_project_place_v1.py`（新規）が
`registry.sqlite` の `place`/`place_watershed`/`place_source_ref` から直接射影する。
設計・実測の詳細は
[docs/plans/PHASE_B_PLACE_ATTRIBUTES.md](PHASE_B_PLACE_ATTRIBUTES.md)。

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_place.sqlite --tables watershed_meta
一致: 1 / 宣言済み差分のみ: 0 / 不一致: 0（終了コード0）
```

宣言済み差分0件——v1 とビット一致した。

## 10. `org_watershed`/`org_watershed_year`（`phase-b/occurrence-watershed`、O-2a）

生物系10テーブル（O-1a/O-1b）と同じ `data/db/v1_projection_occurrence.sqlite`
に2表を追加した（既存の `scripts/b08_project_occurrence_v1.py` に足しただけで、
新しい `b1x` スクリプトは作っていない・candidate ファイルも増えていない）。
入力は `occurrence`（L2、b06）＋新設の `occurrence_place`（記録×流域の直接解決、
`scripts/b09_build_occurrence_place.py`）——`occurrence_agg`（O-1bのキューブ）は
経由しない。設計・実測の詳細は
[docs/plans/PHASE_B_OCCURRENCE.md](PHASE_B_OCCURRENCE.md) §15、
[ADR-0026](../adr/0026-occurrence-place-watershed.md)。

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection_occurrence.sqlite \
    --tables org_norm,org_group_year,effort_year,species2,species_year2,species_month,mesh_year,mesh_all,mesh_species,species_mesh_year,org_watershed,org_watershed_year
一致: 10 / 宣言済み差分のみ: 2 / 不一致: 0（終了コード0）
```

`org_watershed`/`org_watershed_year` は宣言済み差分なしで完全一致（既存の
「一致8+宣言済み差分のみ2」から「一致10+宣言済み差分のみ2」に増えた——
新たに増えた宣言済み差分は0件）。

## 11. `landuse_watershed`/`landuse_change`（`phase-b/landuse`、P-1b）

既存の `v1_projection.sqlite`（observation 系11表）に2表を足した（新しい
`b1x` スクリプト・新しい candidate ファイルは無し）。入力は `observation`/
`observation_agg`——国土数値情報 L03-b 土地利用（流域別、2006/2016年版、
`data/processed/nlni_l03b_landuse_by_watershed.csv`）を `scripts/
b03_build_observation.py` の `_ingest_landuse`（3本目の取り込み）が
`observation` に流し込み、`b04`（キューブ）は無変更で既存の出典配布の
年次セル経路（`period_grain='year'`）をそのまま通る。設計・実測の詳細は
[docs/plans/PHASE_B_LANDUSE.md](PHASE_B_LANDUSE.md)。

```
$ .venv/bin/python3 scripts/b02_derived_compare.py \
    --candidate data/db/v1_projection.sqlite \
    --tables meas_daily,meas_month,meas_year,meas_clim,site_var,var_catalog,sensor_daily,sensor_hour_month,rain_daily,zone_year,zone_clim,landuse_watershed,landuse_change
一致: 7 / 宣言済み差分のみ: 6 / 不一致: 0（終了コード0）
```

`landuse_watershed`/`landuse_change` は宣言済み差分なしで完全一致（既存の
「一致5+宣言済み差分のみ6」から「一致7+宣言済み差分のみ6」に増えた——新たに
増えた宣言済み差分は0件）。`landuse_change.delta_km2` の合計は v1 でも
厳密に0にならない（実測 `sum=-0.000020`、`derived_baseline.json`）が、
`area_km2` の値そのものが CSV から observation・キューブを経て1ビットも
変わらず運ばれるため、`delta_km2`（`SUM(CASE...)` の差）も v1 と完全一致し、
`--tolerance` は使わなかった（実測: `max絶対差=0`、全数値列）。

**値の一致（b02 の数値比較）と storage class の一致は別物**（コードレビュー
指摘5）。`landuse_change` の `km2_2006`/`km2_2016`/`delta_km2` は v1 が
`CREATE TABLE ... AS SELECT`（型無し宣言）で作っているため、該当年に区分が
無い（`SUM(CASE...ELSE 0)` が整数リテラル 0 だけを合計する）行は `typeof()`
が `integer` になる——`REAL` と型を宣言すると INSERT 時に強制変換されて
storage class が v1 とずれる。`_CREATE_SQL["landuse_change"]` も型を宣言
しない形に直し、`typeof()` を実測で突き合わせた: `km2_2006`（v1/候補とも
integer 506・real 2398）・`km2_2016`（同 integer 444・real 2460）・
`delta_km2`（同 real 2904）——2,904行全件で一致（不一致0件）。詳細は
`docs/plans/PHASE_B_LANDUSE.md` §6。

既存11表（`meas_*`/`site_var`/`var_catalog`/`sensor_*`/`zone_*`）の指紋
（全列・全行を `ORDER BY` で正準化した sha256）は、土地利用を足す前後で
1ビットも変わらない（`meas_daily=700094a0f8f2b...` 等、`phase-b/sensor-slice`
以来の値と完全一致。`reconcile.common.compute_fingerprint` で
`--source-regions-yaml`/`--landuse-csv` を空フィクスチャにした候補と実データの
候補を突き合わせて確認した）。

## 12. 全体の合格（`watershed_rollup` + 33テーブルの統合ゲート、`phase-b/rollup-and-gate`）

Phase B（ADR-0016）の最後の1本。残っていた `watershed_rollup`（1表）を通し、
5つに分かれていたゲートを1コマンドに統合した。これで
**「v1 の33テーブルすべてを v2 から再現できる」ことの全体の合格**が
1コマンド・1つの終了コードで確認できる。

### watershed_rollup

v1（`web/scripts/build-geo.mjs:227-251`）は4つの入力の結合:
`watershed_meta`（P-1a）・`org_watershed`（O-2a、v1 のメモ化の癖を再現した
射影値——キューブの正確な値ではない）・`site_var`（observation 系）・
`landuse_watershed`（P-1b）。**独立したキューブのセルにはしない**（D10と同型の
「結合射影」。ADR-0011 の宣言も `place_attribute` のまま動かさない）。

置き場は P-1a が予告したとおり `scripts/b11_project_place_v1.py`
（`build_projections()` に `watershed_rollup` を追加）。`v1_projection.sqlite`
（b05。`site_var`/`landuse_watershed`）と `v1_projection_occurrence.sqlite`
（b08。`org_watershed`）を読み取り専用で ATTACH する——**b11 が他の b1x
スクリプトの出力を読む最初の例**。どちらかが無い/テーブルが欠けていれば、
「先に b05/b08 を実行せよ」と名指しして止まる
（`_assert_rollup_prerequisites`）。

`site_n`/`site_var_n` は **`sites.watershed` の直接一致**であり点内包判定では
ない。P-1a が入れた地点→流域の `place_relation`（`relation='within'`、278件）
から `site_watershed_lookup`（`site_id -> watershed_id`）を組み立てて引く
（`scripts/b05_project_v1.py` の `site_zone_lookup` と同じ形）。実測:
`site_n` の合計は278（`place_relation` の辺の総数と一致）、`site_var_n`
（地点×変数の件数。地点数ではない）の合計は5,799——どちらも v1 の実測値
（`data/db/derived.sqlite`）と完全一致。

列名・列順・**型宣言（storage class）**は v1 の実物と一致させた。v1 は
`CREATE TABLE watershed_rollup AS SELECT ...`（CTAS）で作っており、b11 側でも
同じ CTAS を使う（型を手で宣言しない）ことで、直接の列参照5列（`watershed_id`/
`water_system_name`/`area_km2`/`centroid_lat`/`centroid_lon`、TEXT/REAL）と
無型の11列（集計式・相関サブクエリ、v1でも `type: ""`）の両方を、型を1文字も
手で書かずに揃えた（P-1b の `landuse_change` が踏んだ「型を宣言すると INSERT
時に強制変換されて storage class がずれる」を CTAS で回避）。

実測（`.venv/bin/python3 scripts/b02_derived_compare.py --candidate
data/db/v1_projection_place.sqlite --tables watershed_meta,watershed_rollup`）:

```
一致: 2 / 宣言済み差分のみ: 0 / 不一致: 0（終了コード0）
```

`PRAGMA table_info`・`typeof()` の実測（377行、16列）で v1 とのビット一致を
確認済み（列の宣言型・全列の storage class 分布〔`integer`/`real`/`null`〕が
1つ残らず一致）。

### ゲートの統合

いままで candidate ファイルが5つ（`v1_projection.sqlite`/
`v1_projection_occurrence.sqlite`/`v1_projection_documents.sqlite`/
`v1_projection_place.sqlite`/`v1_projection_taxon.sqlite`）に分かれ、`--tables`
を手で並べて `scripts/b02_derived_compare.py` を5回回していた
（§8参照。プロジェクト自身が決めていた「2本目の `b1x` 系射影スクリプトが
出た時点で着手する」という閾値は、実際には5本になるまで超えられていなかった
——`/simplify` 指摘で気づき、この PR で着手した）。

**対応表**: `scripts/reconcile/projection_manifest.yaml` に、33テーブルすべて
（candidate ファイル名 → `{script, tables}`）を宣言した。テーブルごとの分岐は
コードに書かない——`scripts/reconcile/adr0011_destinations.yaml` と同じ流儀。
`scripts/tests/test_common.py` の
`test_load_projection_manifest_table_set_matches_derived_baseline_exactly` が、
この33テーブルの集合が `reports/derived_baseline.json`（実データ由来。正）の
33テーブルと過不足なく一致することを機械検証している（`adr0011_destinations.yaml`
の検証テストと同じ流儀）。`test_load_projection_manifest_candidate_file_counts_
match_the_declared_breakdown` がファイルごとの内訳（13+13+3+2+2=33）も確認する。

**実行**: 新しい入口 `scripts/b02_run_all_gates.py` を新設した（`scripts/
b02_derived_compare.py` は1行も変更していない）。`projection_manifest.yaml` の
candidate ファイルごとに、`b02_derived_compare.compare_all()`/`render_markdown()`
を import して呼ぶだけの薄いオーケストレータで、結果をマージして1つのレポート
にまとめる。射影スクリプトは自動実行しない（原本DBが要るので CI では動かない。
このゲートは「既にある candidate を突き合わせる」だけ）——candidate ファイルが
1つでも無ければ、`projection_manifest.yaml` の `script` を名指しして即座に止まる。

**判断（呼び出し元の確認を経ていない、2点。理由付き）**:

1. **新しい入口 vs `b02_derived_compare.py` への `--manifest` 追加**:
   新しい入口（`b02_run_all_gates.py`）を選んだ。`b02_derived_compare.py` は
   「ベースライン1つ・候補1つ」を突き合わせるという一貫した設計で、複数
   candidate ファイルを読んで結果をマージするロジックを持ち込むと、CLI引数の
   意味（`--candidate` が単数か複数か）から変わってしまい、単一ファイル用途の
   可読性を損なう。`compare_all`/`render_markdown` はどちらも純粋な関数として
   既に切り出されており、新しい入口から import して複数回呼ぶだけで済んだ
   （`b02_derived_compare.py` の変更行数0）。5系統の個別ゲートの使い方
   （`--candidate <1つ> --tables <その分だけ>`）も一切変わらない。
2. **レポートの出力先**: `reports/derived_reconciliation.md`（個別ゲートの既定
   出力）とは別のファイル名 `reports/derived_reconciliation_all.md` にした。
   個別ゲート・統合ゲートのどちらを先に／後に実行しても互いの結果を上書きし
   合わないようにするため（「5本のゲートを同時に回すと既存レポートが上書き
   され合う」という `/simplify` 指摘と同根の問題を、ファイル名を分けることで
   避けた）。`.gitignore` に追記済み（既存の `derived_reconciliation.md` と
   同じ理由——実行のたびに書き直す成果物で、コミット対象ではない）。

**実測**（このマシン、原本あり、完全モード）:

```
$ .venv/bin/python3 scripts/b02_run_all_gates.py
→ reports/derived_reconciliation_all.md
33表中 一致: 25 / 宣言済み差分のみ: 8 / 不一致: 0 / 対象外: 0
適用した宣言済み差分: 20件
```

終了コード0。実行時間 約70秒（このマシン。r01/b03〜b12 の再実行は含まない
——既にある5つの candidate ファイルを読むだけ）。宣言済み差分の内訳は
§6・§7の18件（measurements の '1未満' 検閲）+ §6の2件（`org_norm`/`species2`
の `cls` タイブレーク）＝ 20件で、この PR で新たに増えた宣言は0件
（`watershed_rollup` は宣言済み差分なしの完全一致）。

既存5系統の個別ゲートは変更なく動く（本セクション冒頭の `watershed_rollup`
実測、および §6・§9・§10・§11 の各実測を参照。このPRで再実測しても値は
1ビットも変わらない）。

### 設計からの逸脱・未決・既知の負債

- CI ワークフローへの配線（個別ゲート・統合ゲートのどちらも）は引き続き
  やっていない（§8参照。原本DBが要るので、CI では今後もそのままでは動かない）。
- `scripts/b02_run_all_gates.py` はテーブル単位の並列化をしない
  （§4「テーブル単位の並列化は採らない」と同じ判断——統合しても実行頻度・
  実測時間〔約70秒〕から見て見合わない）。
- `--tables` に相当する「統合ゲートの中で一部の candidate だけを対象にする」
  絞り込みオプションは付けていない（個別ゲート側の `--tables` がその役目を
  引き続き担う。統合ゲートの存在理由は「33表全部を1回で」なので、絞り込みは
  スコープ外と判断した）。

### コードレビュー対応（`/code-review` 15件）と実測

初回実装（本セクション冒頭の設計・実測）に `/code-review` をかけて15件出た。
**33テーブルの値は1ビットも変えない**という制約のもとで対応した——値を作る
SQL（`_INSERT_WATERSHED_META_SQL`/`_CREATE_WATERSHED_ROLLUP_SQL`/`compare_all`
の集計ロジック）は1文字も変えておらず、検証・エラー処理・レポートの体裁だけを
直している。

**止まるべき場面で黙って進む／壊す**（`scripts/b11_project_place_v1.py`）:

1. `site_watershed_lookup` の一意性検査を `common.fresh_sqlite(out_path)` の
   前（`_validate_registry()`）へ移した。以前は後にあり、失敗すると前回の
   正しい出力が消えたまま中途半端な状態が残っていた。実測: 検査を失敗させる
   フィクスチャ（地点が2つの流域への辺を持つ）で、1回目の正しい出力が
   1バイトも変わらないことを確認（`test_duplicate_site_watershed_edge_does_
   not_touch_previous_output`）。
2. `build_projections()` の先頭で `common.require_sqlite_version()` を呼ぶ
   （`watershed_rollup` が `SUM(area_km2)` を6つ使うため）。実測: SQLite
   バージョンを 3.42.0 に偽装すると `SystemExit`（「古すぎる」）で即座に止まり、
   出力ファイルにも一切触れないことを確認
   （`test_build_projections_calls_the_shared_sqlite_version_guard`）。
4. `site_var`/`landuse_watershed`（b05）・`org_watershed`（b08）の
   site_id/watershed_id が「今の registry.sqlite」に実在することを確認する
   `_assert_no_stale_watershed_or_site_ids` を追加した（`scripts/
   b08_project_occurrence_v1.py` の `_assert_no_stale_taxon_ids` と同じ流儀。
   文脈ごとに b05/b08 のどちらを再実行すべきか名指しする）。**実データでは
   古さ0件**（`org_watershed`/`site_var`/`landuse_watershed` はいずれも今回
   同じ `registry.sqlite` から作った）。実測: 各テーブルを個別に古くした
   フィクスチャ3種（`test_stale_site_var_raises_and_names_b05` 等）で、それぞれ
   正しいスクリプト名を出して止まり、出力ファイルには触れないことを確認。
15. `--out` が入力2つ（`v1_projection_db`/`v1_projection_occurrence_db`）と
    同じ実体（symlink 越しも `os.path.realpath` で解決）でないことを確認する
    `_assert_out_path_distinct_from_inputs` を追加した。実測: `--out
    data/db/v1_projection.sqlite`（b05 の出力そのもの、80MB）を指定すると、
    `fresh_sqlite` が消す前に `MigrationError` で止まり、そのファイルの中身が
    1バイトも変わらないことを確認（実データ・テスト双方）。

**統合ゲートの穴**（`scripts/b02_run_all_gates.py`・`scripts/b02_derived_compare.py`）:

3. `missing_in_candidate`（候補側にこのテーブルが無い）の行に、そのテーブルの
   射影スクリプト名が出るようにした（10と同じ仕組みで、全テーブルの notes に
   `candidate ファイル: ...（射影スクリプト: ...）` を追加する形で実現——
   ファイルが無い場合だけでなく表だけ足りない場合もカバーする）。
5. candidate ファイルの存在確認を、比較を1件も始める前に5ファイルぶんまとめて
   行うようにした（`_assert_all_candidates_exist`）。足りないものは全部
   `script` 付きで1回のエラーに並べる。
6. `load_projection_manifest` が存在しないパスを `load_yaml` の「無ければ
   空」に頼らず、明示的に止まるようにした（`--manifest` の打ち間違いが
   「33表と一致しない」という無関係なエラーに化けるのを防ぐ）。
7. `load_projection_manifest` が `tables`/`script` の値の型（非空の文字列の
   リスト／非空の文字列）まで検証するようにした（`tables:` が値なし・文字列
   だと `flatten_projection_manifest` が生の `TypeError`／1文字ずつ回る、を
   防ぐ）。
10. 統合レポートに、統合ゲートであること・33表を5candidateファイルで見た
    ことを見出し直後に明記し（`render_markdown` の新オプション引数
    `integrated_note`）、テーブルごとの詳細節に candidate ファイルと射影
    スクリプト名を、不一致サマリの表にも candidate ファイル列を追加した
    （`table_candidate`）。どちらも既定値 `None` で、渡さなければ
    `b02_derived_compare.py` 自身の出力は1バイトも変わらない
    （`scripts/tests/test_b02_compare.py` 38件で確認）。
14. `candidate_source` を `try/finally` の中で開閉するようにし、`compare_all`
    が `ExpectedDiffError` で例外を投げても必ず閉じられるようにした。
    `_assert_manifest_matches_baseline` の戻り値（表→candidate ファイル）を
    10の表示に使うようにした（以前は捨てていた）。

**重複・不要なもの**:

11. `b02_derived_compare.py` に `load_baseline_json`/`resolve_expected_diffs`/
    `resolve_baseline_data_path`/`guard_reduced_mode_restrictions`/
    `open_baseline_source_for_mode`/`summarize_results` を切り出し、
    `b02_derived_compare.py`・`scripts/b02_run_all_gates.py` の両方の `main()`
    から呼ぶようにした（以前は約60行がそのままコピーされ、文言だけ微妙に
    違っていた）。`b02_derived_compare.py` の CLI としての振る舞いは1ビットも
    変えていない（`scripts/tests/test_b02_compare.py` 38件が引き続き全緑）。
12. `_existing_tables`（`scripts/b08_project_occurrence_v1.py`・
    `scripts/b11_project_place_v1.py` に同型の実装が別々にあった）を
    `scripts/migrate/common.py` の `existing_tables` に集約した。
13. `watershed_rollup` の相関サブクエリ2つ（`site_n`/`site_var_n`）は
    どちらも `watershed_id` で絞っており、`site_id` の索引は実測で参照
    されないため、未使用だった `CREATE UNIQUE INDEX
    site_watershed_lookup_site_id` を削除した（一意性は指摘1の検査が担保）。

**ドキュメント**:

8. `CLAUDE.md` の「watershed の属性」段落と「統合ゲート」段落の順序を入れ替え、
   `別枠で b10 が…` の続きが統合ゲート側の文として読める状態を直した。
9. `docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`（CLAUDE.md が b11 の設計として
   指しているドキュメント）の「watershed_rollup は未着手・スコープ外」を
   実態（このセクションで完了）に更新した。

**受け入れの実測**（コードレビュー対応後の最終状態）:

```
$ .venv/bin/python3 scripts/b02_run_all_gates.py
→ reports/derived_reconciliation_all.md
33表中 一致: 25 / 宣言済み差分のみ: 8 / 不一致: 0 / 対象外: 0
適用した宣言済み差分: 20件
```

終了コード0（`real 1m12.6s`。このマシン、原本あり、完全モード）。値は
コードレビュー対応の前後で1ビットも変わっていない——31表は今回一切
再生成していない（同じファイルのまま）、`watershed_meta`/`watershed_rollup`
（`scripts/b11_project_place_v1.py` を再実行して作り直した2表）も v1 の
ベースラインに対して宣言済み差分なしの完全一致（`一致: 2`）のまま。

`pytest`: 538件全緑（対応前521件から17件増。内訳: `test_migrate_common.py`
+1〔`existing_tables`〕、`test_common.py` +3〔`load_projection_manifest` の
形の検証〕、`test_b02_run_all_gates.py` +4〔指摘3・5・10・14〕、
`test_b11_project_place_v1.py` +9〔指摘1・2・4×4・15×3〕）。

原本の無い環境（`git clone` した一時ディレクトリ、システム既定 python3.10.12・
sqlite3モジュール3.37.2の venv）でも **408 passed / 130 skipped / 失敗0**
（`--files-only` registry ビルドも成功）。skip が26件増えたのは
`scripts/tests/test_b11_project_place_v1.py`（26件全部）が新たに
`require_sqlite_version` ガード対象の `pytestmark` を持ち、他の `b04`/`b05`
系のテストファイルと同じく古い SQLite では丸ごと skip される側に移ったため
（対応前は b11 にこのガードが無く、フィクスチャだけで完結するテストは
古い SQLite でも普通に実行・合格していた）。

### `/simplify` 対応（6件）と実測

コードレビュー対応後の状態に `/simplify`（再利用・単純化・深さ）をかけて
6件出た。**33表の値は1ビットも変えていない**（引き続き検証・引数定義・
テストの形だけを直している）。

1. **b11 の docstring から「コードレビュー対応」節を削除**した。同じ経緯が
   本ドキュメントの§12と2か所にあったため、経緯は本ドキュメント（この
   セクション）の1か所に置き、`scripts/b11_project_place_v1.py` の docstring
   は個々の検証関数の docstring と同じ「何をするか」だけの形に揃えた。
2. **argparse の共通オプションを切り出した**。`--baseline-json`/
   `--baseline-data`/`--tolerance`/`--out-md`/`--reduced`/`--expected-diffs`/
   `--no-expected-diffs` の7つが `scripts/b02_derived_compare.py`・
   `scripts/b02_run_all_gates.py` にコピーされ、`--reduced`/`--baseline-data`
   の説明文が食い違っていた（統合ゲート側だけ短い文言になっていた）。
   `b02_derived_compare.py` に `_add_shared_compare_args(parser, *,
   default_out_md)` を新設し（`--out-md` の既定値だけはファイルごとに違う
   ため引数で受ける）、両方の `main()` から呼ぶようにした。`--candidate`/
   `--tables`（`b02_derived_compare.py` 専用）・`--manifest`/`--data-dir`
   （統合ゲート専用）は各自のまま。実測: `b02_derived_compare.py --help` の
   全オプション名・説明文を対応前後で突き合わせ、**内容は1文字も変わらず
   順序だけが変わった**ことを確認した（`--candidate`/`--tables` が先頭側に
   移動）。
3. **統合ゲートのループの入れ子を1段減らした**。「1つの candidate を開いて
   `compare_all` で比べ、必ず閉じる」を `_compare_one_candidate()` に
   切り出し、`ExpectedDiffError` の捕捉・`sys.exit` はループ側に残した
   （以前は `for` の中に `try/finally` が `try/except` を包む2段の入れ子が
   あった）。
4. **パスの実体比較を共通ヘルパへ集約した**。`common.reject_protected_source_db`
   （原本3ファイルの保護）と b11 の `_assert_out_path_distinct_from_inputs`
   （射影の入力2ファイルの保護）が、どちらも同じ「`os.path.realpath` で
   比べて一致したら `MigrationError`」を別々に実装していた。
   `common.assert_distinct_realpaths(path, protected: dict[label, path], *,
   message_for)` に集約し、両方がこれを呼ぶ形にした（`protected` の中身——
   固定3ファイルか可変2ファイルか——だけが呼び出し側で違う）。
5. **CLAUDE.md に b11 の実行順を1行追記**した。「b11 はこの縦線で初めて
   別系統（observation・occurrence）の出力を読むので、実行順は r01 の後、
   b05・b08 を先に（互いに依存しない）」——occurrence 系（b06→b09→b07→b08）
   と同じ書き方に揃えた。
6. **同型の複製テストを `pytest.mark.parametrize` にまとめた**。古さの検査
   3件（`site_var`/`landuse_watershed`/`org_watershed`、それぞれ
   `test_stale_*_raises_and_names_b0*` という別関数だった）を
   `test_stale_ids_raise_and_name_the_script_to_rerun`
   （`rollup_kwarg`/`stale_row`/`expected_script` でパラメータ化）に、
   出力先の検査2件を `test_out_path_same_as_an_input_raises_and_preserves_it`
   （`kwargs_key` でパラメータ化）にまとめた。pytest が数えるテストケース数
   自体は変わらない（`pytest --collect-only` で `[site_var]`/
   `[landuse_watershed]`/`[org_watershed]`・`[v1_projection_db]`/
   `[v1_projection_occurrence_db]` の5ケースが引き続き個別に見えることを確認）。

**見送った項目**（オーナー判断）: `projection_manifest.yaml`/
`adr0011_destinations.yaml`/`derived_baseline.json` の「33テーブルの一覧が
3か所にある」は**役割が違う**ため統合しない——`projection_manifest.yaml` は
「テーブル→(射影スクリプト, candidate ファイル)」という実行時の対応表、
`adr0011_destinations.yaml` は ADR-0011 の意味的な分類、`derived_baseline.json`
は実データから作った指紋そのもの。3つとも独立に `derived_baseline.json`
（実データ由来。正）と突き合わされて機械検証されている形（`scripts/tests/
test_common.py` の `test_load_destinations_table_names_match_derived_baseline_
exactly`/`test_load_projection_manifest_table_set_matches_derived_baseline_
exactly`）を保つ。

**実測**（このマシン、原本あり、完全モード）:

```
$ .venv/bin/python3 scripts/b02_run_all_gates.py
→ reports/derived_reconciliation_all.md
33表中 一致: 25 / 宣言済み差分のみ: 8 / 不一致: 0 / 対象外: 0
適用した宣言済み差分: 20件
```

終了コード0（`real 1m9.3s`）。5系統の個別ゲートも変更前と1件も変わらず
（`v1_projection.sqlite`: 一致7/差分6、`v1_projection_occurrence.sqlite`:
一致11/差分2、`v1_projection_documents.sqlite`: 一致3、
`v1_projection_place.sqlite`: 一致2、`v1_projection_taxon.sqlite`: 一致2。
合計 一致25・宣言済み差分のみ8）。`pytest`: 538件全緑（`/simplify` 前後で
件数不変——テストケース数はそのまま、関数定義だけ集約した）。原本の無い
環境（一時 clone、システム既定 python3.10.12・sqlite3モジュール3.37.2）でも
408 passed / 130 skipped / 失敗0、`--files-only` も成功（`/code-review`
対応後の実測と同一）。

---

## Phase B（ADR-0016）の全体の合格

**v1 の派生33テーブルすべてを、`scripts/b02_run_all_gates.py` 1コマンドで
再現できることを確認した**: 一致25 / 宣言済み差分のみ8（v1 側の既知のバグに
由来、内訳は§6・§7参照）/ 不一致0 / 対象外0、終了コード0、実行時間 約69秒
（このマシン、原本あり、完全モード。`watershed_rollup` を含めた5つの
candidate ファイルを1回ずつ突き合わせた合計）。これは Phase B の全ての
縦線（observation・occurrence・place・documents・taxon）が揃い、ADR-0016
の受け入れ基準「`imputation='zero'` の系列で v1 の派生テーブルの値が再現
できること」を33テーブル全数で満たしたことを意味する。
