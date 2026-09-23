# Phase B P-1a: 流域の属性（watershed_meta）— place の属性サテライトと循環の解消

対象: ADR-0016 の Phase B / 状態: **完了（watershed_meta 1テーブル。`data/db/derived.sqlite`
残り12表のうちの1本。watershed_rollup は未着手）**
作成: 2026-09-23 / 関連: ADR-0006（place）、ADR-0011（キューブ・place の属性）、
ADR-0022（region_id・place_relation）、`docs/plans/PHASE_B_OCCURRENCE.md`（grid01 の
入力切り替えの前例）、`docs/plans/PHASE_B_RECONCILIATION.md`（突合ゲートの仕組み）

## 1. 致命的な前提: 循環を断つ

`scripts/registry/build_place.py` の watershed 節は Phase A から一貫して
`derived.watershed_meta`（`web/scripts/build-geo.mjs` が
`data/processed/nlni_w12_watersheds.jsonl` から作る **v1 の派生表**）を読んでいた。
このままキューブ経由で v1 の `watershed_meta` を再現しても、「v1 の出力（derived.sqlite）
から作った registry を、v1 の出力に射影し直しただけ」の循環にしかならない
（grid01 が `derived.mesh_all` を経由していた問題と同型。
`docs/plans/PHASE_B_OCCURRENCE.md` §2-3 の前例と同じ手順で解いた）。

**決定**: `build_place.py` の watershed 節の入力を、L1 の
`data/processed/nlni_w12_watersheds.jsonl`（国土数値情報 W12 流域界 1977年版、377面。
`web/scripts/build-geo.mjs` と同じ入力）の直読みに切り替える。

## 2. 切り替えても値は1ビットも変わらないことの実測

`derived.sqlite`（v1、`watershed_id`/`water_system_code`/`water_system_name`/
`water_system_category`/`main_rivers`/`area_km2`/`centroid_lat`/`centroid_lon`/
`data_year`/`source_ref` の10列・377行）と、`nlni_w12_watersheds.jsonl` を Python の
`json.loads()` で直読みした値を、対応する9列（`watershed_id` をキーに突き合わせ）で
1行ずつ diff した:

```
v1 count 377 / jsonl count 377（watershed_id 集合が完全一致）
water_system_code / water_system_name / water_system_category / main_rivers /
area_km2 / centroid_lat / centroid_lon / data_year / source_ref:
  diffs = 0（型も一致。float は Python/JS どちらも IEEE754 double なので
  丸め・表現差も無い）
```

**丸め・型・NULL の食い違いは無かった**（brief の「食い違えば止めて報告」の分岐には
入らなかった）。理由: `web/scripts/build-geo.mjs` の watershed_meta 生成コードは
JSONL の値をほぼそのまま `INSERT`（`?? null`/`|| null` で欠落を補うだけ）しており、
変換・集計・丸めを一切行っていないため。

## 3. main_rivers・data_year の実測

`nlni_w12_watersheds.jsonl`（377行）を実測:

```
main_river_names_ja: 空文字列 143件 / null 0件 → 非空 234/377
  （brief の見積り「232/377」は概算。実測値は 234/377）
data_year: 全377行が 1977（min=max=1977）
water_system_name_ja_estimated: null 145件（水系名が確定できない流域）、空文字列は0件
```

**main_rivers は空文字列のまま持つ（NULL に丸めない）**。v1（`build-geo.mjs`）は
`main_river_names_ja` を `?? null`（nullish coalescing）で扱っており、これは
JSON の `null` だけを `null` にし、空文字列 `""` はそのまま通す。
`water_system_name_ja_estimated` だけは `|| null`（falsy coalescing）だが、
この列に空文字列は無い（145件は元から JSON `null`）ため、`??`/`||` の違いは
実データの結果に出ない。`place.name_ja` の組み立てでも v1 の式（`or None`）を
そのまま踏襲した（`scripts/registry/build_place.py` の watershed 節）。

## 4. place_watershed（属性サテライト）

ADR-0006 に追記した決定（「kind 固有の属性は `place_<kind>` サテライトに置き、
`place` 本体の列は増やさない」）の最初の実装:

```sql
CREATE TABLE place_watershed (
  place_id TEXT PRIMARY KEY,
  water_system_code TEXT,
  water_system_category TEXT,
  main_rivers TEXT,
  data_year INTEGER
);
```

`place` 本体には従来どおり5列（`name_ja`/`lat`/`lon`/`area_km2`/`definition_ref`）
だけを持たせる。却下案（`water_system_code` を親 place＋`place_relation` にする）の
理由は ADR-0006 の追記を正とする（ここでは繰り返さない）。D1
（`web/src/db/schema-registry.ts`）には載せない（`place_relation` と同じ判断——
消費者がまだ無い）。

## 5. place_relation: 地点 -> 流域

`sites.watershed`（`scripts/m01_sites.py:110-128` が `nlni_w12_watersheds.geojson`
への shapely の点内包判定で機械的に決定した値。申告値ではない）から、地点→流域の
`within` 辺を組み立てた。

実測: `ryuiki.sqlite` の `sites` テーブル本体で `watershed IS NOT NULL` は
**278件**（brief の見積りどおり）。全278件の `watershed` 値は
`watershed_meta.watershed_id`（377件のいずれか）に解決できる（欠落0件、
distinct 110種の流域を参照）。

r01 の不変条件に「地点は流域への `within` 辺を高々1本」を追加した（既存の
ゾーン版と同じ流儀。実装は §10-7 で共通関数に統合済み）。

## 6. b11_project_place_v1.py

`registry.sqlite` の `place`（place_kind='watershed'）⋈ `place_watershed` ⋈
`place_source_ref`（source_id='watershed_meta.watershed_id'）から `watershed_meta`
の v1形へ射影する新規スクリプト。`observation`/`observation_agg`（v2.sqlite）は
一切経由しない（静的な地理データの転記であり、ADR-0011 の「キューブのセルにしない」
対象——`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同種）。

`scripts/b05_project_v1.py` と違い、行変換が単純な JOIN だけなので、Python 側で
行をタプル列にバッファせず `CREATE TABLE`（v1 の宣言型で）→
`INSERT INTO watershed_meta (列名...) SELECT ... FROM reg.place ...`（列名を
明示した1文。§10-8）で組み立てる。出力は `data/db/v1_projection_place.sqlite`
（毎回ゼロから作り直す。`.gitignore` 済み）。

「レジストリの不変条件」と「射影固有の防御」を分ける（ゾーンの「地点はゾーンへの
辺を高々1本」と `b05` の関係と同じ考え方）。`place_kind='watershed'` の各 place が
`place_watershed`・`place_source_ref(source_id='watershed_meta.watershed_id')` を
それぞれちょうど1件持つことは**レジストリの不変条件**として r01 側
（`_assert_watershed_place_has_attributes_and_source_ref()`）が保証し、b11 は
その結果を信用する。b11 側に残すのは射影固有の防御2つだけ（§10-2・§10-3）:
`place_watershed` テーブルの存在チェックと、JOIN による行の水増し検出
（`place_source_ref` が `place_id` について単射であることの確認）。
検証はすべて出力ファイルに触れない読み取り専用の一時コネクションで行い、
全部通ってから `common.fresh_sqlite(out_path)` で書き出す（§10-4）。

## 7. 受け入れ（実測）

1. **b02 の終了コードそのものが0、一致1**:

   ```
   $ .venv/bin/python3 scripts/b02_derived_compare.py \
       --candidate data/db/v1_projection_place.sqlite --tables watershed_meta
   → reports/derived_reconciliation.md
   一致: 1 / 宣言済み差分のみ: 0 / 不一致: 0
   B02_EXIT_CODE=0
   ```

   完全モード（`data/db/derived.sqlite` が存在するため行レベル突合、許容誤差0）。
   宣言済み差分（`expected_diffs.yaml`）は0件——v1 とビット一致した。

2. **registry の watershed の place / place_source_ref が切り替え前と完全一致**:
   切り替え前（origin/main、コミット `0c9ca4b`）で一時 worktree（原本を読み取り専用
   symlink）を作り full build した registry.sqlite と、切り替え後（本 PR）の
   registry.sqlite それぞれから、`place_kind='watershed'` の377行と
   `place_source_ref(source_id='watershed_meta.watershed_id')` の377行を
   `place_id` 昇順で正準化し sha256 を取った:

   ```
   BEFORE: place rows=377 ref rows=377 sha256=958e9ffcee79eae5412179c19e732133c171847ac75741b302d70e2b8454cd16
   AFTER : place rows=377 ref rows=377 sha256=958e9ffcee79eae5412179c19e732133c171847ac75741b302d70e2b8454cd16
   ```

   **完全一致（0ビットの差も無い）**。

   r01 のフルビルド（実データ、§10 のコードレビュー対応後の最終コミット時点）:
   ```
   place: 4,964 行 / place_source_ref: 4,964 行 / place_relation: 568 行
     （旧290 + 地点→流域278）/ place_watershed: 377 行
   一意性OK: place_watershed.place_id (377) / 参照整合性OK: place_watershed.place_id -> place.place_id
   地点→ゾーンの辺は単射OK: 290 件 / 地点→流域の辺は単射OK: 278 件
   watershed place の属性/逆引きOK: 377 件（§10-6 で新設した r01 側の不変条件）
   指紋(registry_build): 853c40ae74dabe6bae73f6fcbd56942aa5c9a1938212a83b20369e36d0ab3e62（mode=full）
   ```
   直後に `--check-fresh` を実行し `EXIT_FRESH`（終了コード0、`✔ 新鮮`、同じ指紋）で
   あることを確認した。この指紋は §10 の全修正（コードの変更を含む）を反映した
   最終状態のものであり、コードを1文字でも変えるたびに変わる（決定論的だが
   「値」自体は再現用ではなく「一致確認済み」の記録）。

   `web/scripts/build-registry-ts.mjs` を `RYUIKI_REGISTRY_DB` で worktree の
   registry.sqlite を指して再実行し、`git status --porcelain
   web/src/lib/registry/generated.ts web/src/lib/registry/generated-client.ts` が
   **空（diff 0行）**であることを確認した（`place`/`place_watershed`/
   `place_relation` はどちらのファイルも参照しないため無影響、`unit`/`variable`/
   `taxon`/`caveat` は本PRで一切変えていないため）。

3. **既存のゲートが変わらない**: `scripts/b03_build_observation.py` →
   `scripts/b04_build_cube.py` → `scripts/b05_project_v1.py` を実データで再実行し、
   `scripts/b02_derived_compare.py --candidate data/db/v1_projection.sqlite --tables
   meas_daily,meas_month,meas_year,meas_clim,site_var,var_catalog,sensor_daily,
   rain_daily,sensor_hour_month,zone_year,zone_clim` を実行した:

   ```
   一致: 5 / 宣言済み差分のみ: 6 / 不一致: 0（適用した宣言済み差分: 18件）
   終了コード 0
   ```

   main の状態（`docs/plans/PHASE_B_RECONCILIATION.md` §6・§8）と完全に一致。

4. **pytest 全緑**: `.venv/bin/python3 -m pytest -q` で **274 件全緑**
   （リポジトリの `.venv`。`requests` あり。§10 のコードレビュー対応で
   10件増えた——内訳は §10 参照）。

   原本の無い環境（一時ディレクトリへの `git clone`、Python 3.13 venv、
   `pip install -r requirements.txt` だけ）でも確認した（詳細は下記§8）。

5. **実行時間**（実データ、このマシン。`.venv/bin/python3`）:

   | ステップ | 所要時間 |
   |---|---|
   | `r01_build_registry.py`（フルビルド。unit/variable/place/taxon/caveat） | 38.7s |
   | `b03_build_observation.py`（observation 1,041,003件） | 33.0s |
   | `b04_build_cube.py`（observation_agg 1,993,816件） | 59.2s |
   | `b05_project_v1.py`（11テーブル 753,629件、書き出し込み） | 59.4s |
   | `b11_project_place_v1.py`（watershed_meta 377件） | **0.0s**（<0.1s） |
   | `b02_derived_compare.py --tables watershed_meta`（完全モード） | <1s |
   | `pytest`（264件） | 30.4s |

   watershed の縦線は observation/occurrence のキューブを経由しないため、
   b03〜b05（測定・センサーの縦線）と比べて桁違いに軽い。

## 8. 原本の無い環境（CI 再現）での確認

CLAUDE.md の規約どおり、`data/db/ryuiki.sqlite`/`cells.sqlite`（原本、
まとめて900MB超）を退避せず、**一時ディレクトリへの `git clone`** で「原本が
存在しない状態」を作った（`actions/checkout` と同じ）。手順・結果は
コミットメッセージ・PR 説明に実測ログを残す。確認したこと:

- `python3 -m venv` + `pip install -r requirements.txt`（PyYAML・pytest のみ）
  だけの Python 3.13.7（CI の `PYTHON_VERSION: "3.13"` と同じメジャー系列）venv で
  `python3 -m pytest -q` が274件全緑（§10 のコードレビュー対応を反映した最終状態。
  §10-11 参照）
- 同じ venv で `RYUIKI_REGISTRY_DB=<tmp>/registry_files_only.sqlite
  python3 scripts/r01_build_registry.py --files-only` が成功
  （`place`/`place_relation`/`place_watershed`/`taxon` は空のまま——
  `--files-only` はそもそもこれらを作らない。`unit`/`variable`/`variable_alias`と
  ファイル由来の `caveat`/`caveat_scope` だけを作る既存の仕様どおり）

## 9. 設計からの逸脱・未決・既知の負債

- **watershed_rollup は今回はやらない**（brief の指示どおりスコープ外。P-1a の
  次に着手する候補——`docs/plans/PHASE_B_RECONCILIATION.md` 残り11テーブルの1つ）。
- **main_rivers・水系コード等の watershed 固有語彙は `place_watershed` に列として
  そのまま置いた**（ADR-0006 追記のとおり、水系を独立した place にする設計は
  見送った）。
- ~~b11 の `_assert_no_duplicate_watershed_source_ref_per_place`/
  `_assert_place_watershed_table_exists` を共通ヘルパに寄せる~~ **解消済み**:
  main へのリベース時に O-1b がマージ済みで `scripts/migrate/common.py` に
  `raise_on_group_by_duplicates`/`assert_dimension_key_unique`/
  `assert_grouped_totals_match` が入っていた。前者は既存のものをそのまま呼ぶだけ
  で済んだ。テーブル存在チェックの共通ヘルパ（`assert_attached_table_exists`）は
  まだ無かったため、`scripts/b05_project_v1.py` の
  `_assert_place_relation_table_exists` と同型の検証として新設し、b11 側を
  それに置き換えた（`scripts/b05_project_v1.py` 自体はこの PR のスコープ外
  なので変更していない——まだ独自実装のまま）。
- **CI への部分ゲートの配線**（`watershed_meta` を含む。`docs/plans/PHASE_B_RECONCILIATION.md`
  §8参照）は今回やらない。1表のための汎用の対応表（テーブル名→射影スクリプト・
  candidate ファイル）も作らない——過剰。2つ目の `b1x` 系射影スクリプトが出た時点で
  着手する。

（初回実装時点の負債「`derived.sqlite` が full ビルドで無条件に開かれる」は
コードレビュー対応で解消した。§10-5 参照。）

## 10. コードレビュー対応（`/code-review` 13件）と実測

初回実装（本ドキュメント §1〜§9、上記の指紋 `b87f546a...` 時点）に `/code-review` を
かけて13件出た。**watershed の place/place_source_ref/place_watershed と
watershed_meta の射影の値は変えない**という制約のもとで対応し、実際にフルビルド・
射影・突合を再実行して1ビットも変わっていないことを確認した（§7-2 の更新後の
指紋 `853c40ae...` がその最終状態）。

### 10-1. JSONL のキーを `.get()` で読んでいた（黙って壊れる型・最優先）

`_load_watershed_jsonl()` が読む10キー（`WATERSHED_JSONL_REQUIRED_KEYS`）を、
読み込み時に1行ずつ検査するようにした（欠けていれば `ValueError` で行番号付きの
メッセージを出して止まる）。検査を通った後は `build()` 側も `o.get(...)` ではなく
`o["key"]`（直接添字）で読む——キーが消えた・改名されたときに黙って NULL 埋めして
「377行できた」と通ってしまう経路を塞いだ。

実測: フィクスチャで必須キーを1つ欠いた JSONL を読ませると `ValueError`
（「必須キーが無い」）で止まることを確認（`test_load_watershed_jsonl_raises_on_missing_required_key`）。
実データ（`nlni_w12_watersheds.jsonl`、キー欠落なし）では動作は変わらない
（377行、全列 diff 0件、§2の実測を再確認済み）。

### 10-2. b11 に `place_watershed` の存在検査が無かった

`_assert_place_watershed_table_exists()` を追加（`scripts/b05_project_v1.py` の
`_assert_place_relation_table_exists()` と同じ形）。古い registry.sqlite
（P-1a より前にビルドしたもの）を渡すと、素の `sqlite3.OperationalError`
（no such table）ではなく「r01 を実行し直せ」と分かる `MigrationError` で止まる。

### 10-3. b11 の重複検査が効いていなかった（行の水増しを見逃す）

`_assert_every_watershed_place_has_attrs_and_ref()` の重複検査は
`place_source_ref` を `external_key`（v1 の watershed_id）で `GROUP BY` していたが、
実際に b11 の `JOIN` が行を水増しする条件は「同じ `place_id` に
`source_id='watershed_meta.watershed_id'` の行が複数ある」こと——`external_key` の
重複ではなく `place_id` の重複を見なければ検出できなかった（逆に、2つの異なる
place が同じ external_key を指すケースは水増しを起こさないのに誤って止めていた）。
`GROUP BY psr.place_id HAVING COUNT(*) > 1` に直した
（`_assert_no_duplicate_watershed_source_ref_per_place()`）。

実測: フィクスチャで同じ place に2件目の `place_source_ref` を足すと
`place_id について単射でない` で止まること、2つの異なる place が同じ
external_key を指すケース（水増しを起こさない）では止まらないこと（2件とも
射影される）を確認した
（`test_duplicate_source_ref_per_place_raises_and_does_not_inflate_rows`/
`test_two_places_sharing_the_same_external_key_is_not_flagged_as_inflation`）。

### 10-4. 出力ファイルを消す順序

`build_projections()` が `common.fresh_sqlite(out_path)`（既存ファイル・WAL/SHM を
削除してから開く）を検証の**前**に呼んでいたため、検証が失敗すると前回の正しい
出力が消えて空/半端なファイルが残っていた。検証（`_validate_registry()`）を
出力ファイルに一切触れない読み取り専用の一時コネクション（`:memory:` に `reg` を
ATTACH）で先に行い、**全部通ってから** `fresh_sqlite()` を呼ぶ順序に直した
（`scripts/b05_project_v1.py` が検証を先に済ませてから `write_projections()` で
書き出す構成と同じ）。

実測: フィクスチャで1回目の正しい出力を作ったあと、registry.sqlite を壊してから
2回目を実行すると `MigrationError` で止まり、出力ファイルが1バイトも変わって
いないことを確認した（`test_failed_validation_does_not_touch_previous_output`）。

**`common.fresh_sqlite` 自体が原本（ryuiki/cells/derived）を誤って消せる問題**
（`fresh_sqlite` の共通実装レベルの問題）は、並行して進んでいる P-3
（`phase-b/documents`）の PR で対応することになっているため、本 PR では触れて
いない（オーナー指示。衝突回避）。

### 10-5. `derived.sqlite` が full ビルドに無条件に必要だった（根から直す）

`scripts/registry/common.py` の `open_sources()` が `SOURCE_NAMES`
（`ryuiki`/`cells`/`derived`）を無条件に開いており、registry ビルドが
`derived.sqlite` を実際には読まなくなった（P-1a 本体の変更）後も、ファイルが
存在しないと `FileNotFoundError` で止まっていた——docstring・コメントの
「derived.sqlite を一切開かない」という説明と実装が食い違っていた。

`open_sources()` が既定で開く集合を `DEFAULT_SOURCES = ("ryuiki", "cells")` に
分離し、`derived` を含む `SOURCE_NAMES` は `open_source(name)` を個別に呼ぶときの
許可リストとしてだけ残した（将来また特定モジュールが `derived.sqlite` を読む
ようになったときのため）。`grep -rn 'src\[.derived.\]' scripts/registry/*.py`
で、どのビルドモジュールも `src["derived"]` を読んでいないことを再確認した
（0件）。`scripts/r02_resolution_report.py`（`common.open_sources()` の別の
呼び出し元）も `src["ryuiki"]` しか使っておらず影響を受けない。

**実測（`derived.sqlite` を実際に取り除いて確認）**: worktree の
`data/db/derived.sqlite`（symlink）を一時的に退避し、
`.venv/bin/python3 scripts/r01_build_registry.py` を実行:

```
完了: 10 テーブル / 53,178 行（derived.sqlite が存在するときと同じ）
指紋(registry_build): 853c40ae74dabe6bae73f6fcbd56942aa5c9a1938212a83b20369e36d0ab3e62
（derived.sqlite が存在するビルドと完全に同じ指紋——フル ビルドが derived.sqlite の
有無に一切左右されないことを示す）
終了コード 0
```

watershed の place/place_source_ref の正準化 sha256 も
`958e9ffcee79eae5412179c19e732133c171847ac75741b302d70e2b8454cd16` のまま
（derived.sqlite が有る場合と同一）。確認後、symlink は元に戻した。

**結論: full ビルドに `data/db/derived.sqlite`（`pnpm run build:derived` の成果物）
はもう要らない。** `registry/README.md`・`scripts/r01_build_registry.py` の
docstring・`scripts/registry/common.py` のコメントをこの実態に合わせて更新した。

### 10-6. 「流域 place には place_watershed が必ず1行」を registry の不変条件に

b11 が独自に行っていた「`place_kind='watershed'` の各 place が
`place_watershed`/`place_source_ref(source_id='watershed_meta.watershed_id')` を
それぞれちょうど1件持つこと」の検証を、r01 側の不変条件
`_assert_watershed_place_has_attributes_and_source_ref()` に移した（ゾーンの
「地点はゾーンへの辺を高々1本」を r01 に置いた前例と同じ「レジストリの不変条件は
書き手側で1回だけ保証し、消費側は信用してよい」という分担）。b11 に残したのは
§10-2・§10-3 の射影固有の防御だけ。

実測: r01 のフルビルドで `watershed place の属性/逆引きOK: 377 件` が出ることを
確認済み（§7-2 の更新後ログ参照）。

### 10-7. ゾーンと流域の3対のコピペを1つの宣言駆動の実装に集約

- `scripts/r01_build_registry.py`: ゾーン版・流域版それぞれの検証関数の中身を
  `RELATION_SINGLE_VALUED_CHECKS = [("sites.zone", "ゾーン"),
  ("watershed_meta.watershed_id", "流域")]` から回す共通実装
  `_assert_relation_child_is_single_valued(conn, source_id, label)` に集約した。
  `main()` は宣言を全部回す `_assert_all_relation_single_valued_checks()` を呼ぶ。
  **`/simplify` 対応（同じPR内）で、本番からは呼ばれなくなっていた薄いラッパ2つ
  （テストのためだけに名前を残していたもの）を削除した**——テスト側を
  `_assert_relation_child_is_single_valued(conn, source_id, label)` の直接呼び出しに
  書き換えた（メッセージ・挙動は変えていない）。
- `scripts/registry/build_place.py`: `_zone_relation_rows`/`_watershed_relation_rows`
  の中身を共通実装 `_relation_rows(pairs, place_id_by_external_key, *, basis,
  not_found_message)` に集約した（`not_found_message` はメッセージ文言だけを
  呼び出し側から渡す）。2つの外部キー→place_id の辞書内包も
  `_place_id_by_external_key(ref_rows, source_id)` の1関数に集約した
  （こちらは `build()` からしか呼ばれない内部関数のままで、テスト用の名前を
  残す必要が無いのでラッパは作っていない）。

実測: 既存テスト（`test_zone_relation_child_is_single_valued_*`・
`test_watershed_relation_child_is_single_valued_*`）を、呼び出し先を
`_assert_relation_child_is_single_valued(conn, source_id, label)` に変えただけで
（メッセージの検証・挙動は1つも変えず）全緑にできることを確認した。新しいテストとして、
「地点がゾーンと流域の両方への辺を持つ」（実データでは278地点が両方持つ）ケースで
両方の不変条件が独立に通ることを確認した
（`test_site_with_both_zone_and_watershed_edges_passes_both_checks`）。

### 10-8. b11 の `INSERT ... SELECT` に列名を明示

`INSERT INTO watershed_meta SELECT ...`（位置指定）を
`INSERT INTO watershed_meta (watershed_id, water_system_code, ...) SELECT ...`
に変えた。`CREATE TABLE` の列順と `SELECT` の列順という2つの離れたリテラルを
手で揃える暗黙の位置合わせをやめ、列名を静的にも検証できるようにした
（`test_insert_sql_declares_explicit_column_list`）。

### 10-9〜10-11. テスト

- `test_r01_registry_atomic.py` の `_ALL_TABLES`（ハードコードのタプル。
  `place_watershed` が漏れていた）を、`sqlite_master` から導出する
  `_all_table_names()` に置き換えた——表が増えても追随する。
- 「地点がゾーンと流域の両方への辺を持つ」テストを追加（§10-7 参照。実データの
  形——両方の辺を実際に持つ子——を初めて再現した）。
- `nlni_w12_watersheds.jsonl` が無いときの `FileNotFoundError`（worktree で
  symlink を張り忘れたときに必ず踏む経路）のテストを追加した
  （`test_load_watershed_jsonl_raises_file_not_found_when_missing`）。

### 10-12. ドキュメント（`registry/README.md`）

`DERIVED_TABLES_READ`/「derived が無い→古い」という削除済みの仕組みの説明、
「9テーブル」という古いテーブル数、watershed の新しい入力（JSONL）・
`place_watershed`（未記載だった）を実態に合わせて更新した。
`scripts/schema_registry.sql` の「最初に作る辺は地点→ゾーンの1種類だけ」という
古いコメントも、地点→流域を含む2種類に更新した。

### 10-13. `docs/plans/PHASE_B_PLACE_ATTRIBUTES.md` の指紋の再記録

本ドキュメント自身が記録していた指紋 `b87f546a...` は、記録後に
`scripts/registry/build_place.py`・`scripts/schema_registry.sql` を編集した
（§10-1〜§10-8 のコード変更）ため、コミット済みの木から作り直すと一致しなくなって
いた——データ（watershed の値）は同一だが、指紋はビルドの論理（コード）自体も
対象に含むため、コードを変えれば必ず変わる。§7-2 の指紋を最終コミット時点の値
（`853c40ae74dabe6bae73f6fcbd56942aa5c9a1938212a83b20369e36d0ab3e62`）に更新し、
その状態で `--check-fresh` が `EXIT_FRESH`（終了コード0）を返すことを確認した
（§7-2 参照）。
