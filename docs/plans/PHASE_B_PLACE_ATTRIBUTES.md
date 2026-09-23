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
だけを持たせる。`water_system_code` を親 place（`water_system` という新しい
`place_kind`）＋ `place_relation` にする案も検討したが、v1 の再現（`watershed_meta`
を1テーブルへ射影し直すだけ）には過剰な設計であり、今回は単純に列として持たせた
（ADR-0006 追記に明記）。D1（`web/src/db/schema-registry.ts`）には載せない
（`place_relation` と同じ判断——消費者がまだ無い）。

## 5. place_relation: 地点 -> 流域

`sites.watershed`（`scripts/m01_sites.py:110-128` が `nlni_w12_watersheds.geojson`
への shapely の点内包判定で機械的に決定した値。申告値ではない）から、地点→流域の
`within` 辺を組み立てた。

実測: `ryuiki.sqlite` の `sites` テーブル本体で `watershed IS NOT NULL` は
**278件**（brief の見積りどおり）。全278件の `watershed` 値は
`watershed_meta.watershed_id`（377件のいずれか）に解決できる（欠落0件、
distinct 110種の流域を参照）。

r01 の不変条件に「地点は流域への `within` 辺を高々1本」を追加した
（`_assert_watershed_relation_child_is_single_valued()`。既存の
`_assert_zone_relation_child_is_single_valued()` と同じ流儀）。

## 6. b11_project_place_v1.py

`registry.sqlite` の `place`（place_kind='watershed'）⋈ `place_watershed` ⋈
`place_source_ref`（source_id='watershed_meta.watershed_id'）から `watershed_meta`
の v1形へ射影する新規スクリプト。`observation`/`observation_agg`（v2.sqlite）は
一切経由しない（静的な地理データの転記であり、ADR-0011 の「キューブのセルにしない」
対象——`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同種）。

`scripts/b05_project_v1.py` と違い、行変換が単純な JOIN だけなので、Python 側で
行をタプル列にバッファせず `CREATE TABLE`（v1 の宣言型で）→
`INSERT INTO watershed_meta SELECT ... FROM reg.place ...` の1文で組み立てる。
出力は `data/db/v1_projection_place.sqlite`（毎回ゼロから作り直す。`.gitignore` 済み）。

INNER JOIN で行が黙って欠落する事故を防ぐため、射影の前に
「`place_kind='watershed'` の各 place が `place_watershed`・
`place_source_ref(source_id='watershed_meta.watershed_id')` をそれぞれ
ちょうど1件持つこと」を機械検証する
（`_assert_every_watershed_place_has_attrs_and_ref()`）。

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

   r01 のフルビルド（実データ）:
   ```
   place: 4,964 行 / place_source_ref: 4,964 行 / place_relation: 568 行
     （旧290 + 地点→流域278）/ place_watershed: 377 行
   一意性OK: place_watershed.place_id (377) / 参照整合性OK: place_watershed.place_id -> place.place_id
   地点→ゾーンの辺は単射OK: 290 件 / 地点→流域の辺は単射OK: 278 件
   指紋(registry_build): b87f546ab1de7bea4169a27d14b0fc049cc747a8b33c188566a6aa2841253a3f（mode=full）
   ```

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

4. **pytest 全緑**: `.venv/bin/python3 -m pytest -q` で **264 件全緑**
   （リポジトリの `.venv`。`requests` あり）。

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
  `python3 -m pytest -q` が264件全緑
- 同じ venv で `RYUIKI_REGISTRY_DB=<tmp>/registry_files_only.sqlite
  python3 scripts/r01_build_registry.py --files-only` が成功
  （`place`/`place_relation`/`place_watershed`/`taxon` は空のまま——
  `--files-only` はそもそもこれらを作らない。`unit`/`variable`/`variable_alias`と
  ファイル由来の `caveat`/`caveat_scope` だけを作る既存の仕様どおり）

## 9. 設計からの逸脱・未決・既知の負債

- **watershed_rollup は今回はやらない**（brief の指示どおりスコープ外。P-1a の
  次に着手する候補——`docs/plans/PHASE_B_RECONCILIATION.md` 残り21テーブルの1つ）。
- **`derived.sqlite` は full モードの registry ビルドで依然として `open_sources()`
  経由で開かれる**（存在しないと `FileNotFoundError` で止まる）。中身を読む
  箇所は本 PR で0になった（`DERIVED_TABLES_READ`/`_hash_derived_tables()` を
  削除した）が、`common.open_sources()`/`SOURCE_NAMES` 自体は3ファイル
  （ryuiki/cells/derived）を無条件に開く既存の設計のままにした——他モジュールが
  将来 derived を使う可能性・変更の影響範囲を広げないための最小差分の判断。
  「full ビルドに `pnpm run build:derived` がもう要らない」という状態には
  していない（要る場合はオーナー判断で別途 `open_sources()` を直す）。
- **main_rivers・水系コード等の watershed 固有語彙は `place_watershed` に列として
  そのまま置いた**（ADR-0006 追記のとおり、水系を独立した place にする設計は
  見送った）。
